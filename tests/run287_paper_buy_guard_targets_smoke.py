#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
import sys

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import build_run287_paper_buy_guard_targets as guard  # noqa: E402
from tools.run_daily_simulated_fill_ledger import (  # noqa: E402
    PaperLedgerIntegrityError,
    validate_target_handoff,
)


VALUATION_DATE = "2026-08-20"


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def target_frame() -> pd.DataFrame:
    frame = pd.DataFrame(
        [
            {"rebalance_date": VALUATION_DATE, "ticker": "AAA", "weight": 0.50},
            {"rebalance_date": VALUATION_DATE, "ticker": "BBB", "weight": 0.30},
            {"rebalance_date": VALUATION_DATE, "ticker": "CASH", "weight": 0.20},
        ]
    )
    for reason in guard.RESERVE_REASONS:
        frame[reason] = 0.0
    frame.loc[frame["ticker"].eq("CASH"), "capacity_unallocated"] = 0.20
    frame["reserve_reason_source_hash"] = guard.reserve_reason_hash(frame)
    frame["same_close_target_hash"] = guard.normalized_target_hash(frame)
    return frame


def write_account(path: Path, portfolio: str) -> None:
    write_json(
        path,
        {
            "portfolio_kind": portfolio,
            "as_of_date": VALUATION_DATE,
            "cash_weight": 0.40,
            "positions": [
                {"ticker": "AAA", "weight": 0.40},
                {"ticker": "CCC", "weight": 0.20},
            ],
            "review_only": True,
            "live_trading_enabled": False,
            "production_mutation_allowed": False,
        },
    )


def fixture(root: Path, state: str) -> argparse.Namespace:
    same_close = root / "same_close"
    paper = root / "paper"
    output = root / "guard"
    same_close.mkdir(parents=True)
    outputs: dict[str, dict] = {}
    for portfolio in guard.PORTFOLIOS:
        path = same_close / f"same_close_{portfolio}_target_book.csv"
        target_frame().to_csv(path, index=False, lineterminator="\n")
        outputs[f"{portfolio}_target_book"] = guard.fingerprint(path)
        write_account(paper / portfolio / "account_state_latest.json", portfolio)
    write_json(
        same_close / "status.json",
        {
            "schema_version": guard.SOURCE_SCHEMA,
            "status": guard.SOURCE_STATUS,
            "valuation_close_date": VALUATION_DATE,
            "target_book_file_written": True,
            "orders_generated": False,
            "crisis_policy_applied_to_operating_target": False,
            "crisis_policy_shadow_only": True,
            "canonical_crisis_state": {
                "state": state,
                "component_availability": [
                    {
                        "component": "vix",
                        "available": True,
                        "fresh": True,
                        "critical": True,
                    }
                ],
                "missing_critical_components": [],
            },
            "outputs": outputs,
        },
    )
    return argparse.Namespace(
        same_close_status=str(same_close / "status.json"),
        state_dir=str(paper),
        valuation_date=VALUATION_DATE,
        output_dir=str(output),
    )


def target_weights(result: dict, portfolio: str) -> dict[str, float]:
    frame = pd.read_csv(result["outputs"][f"{portfolio}_target_book"]["path"])
    return dict(zip(frame["ticker"], frame["weight"]))


def test_watch_limits_only_incremental_buys() -> None:
    with tempfile.TemporaryDirectory(prefix="paper_buy_guard_watch_", dir=ROOT / "_tmp_tests") as temp:
        args = fixture(Path(temp), "WATCH")
        result = guard.build(args)
        assert result["status"] == guard.READY_STATUS
        assert result["macro_crisis_inputs_bound"] is True
        for portfolio in guard.PORTFOLIOS:
            weights = target_weights(result, portfolio)
            assert abs(weights["AAA"] - 0.40) < 1e-12
            assert "BBB" not in weights or abs(weights["BBB"]) < 1e-12
            assert abs(weights["CASH"] - 0.60) < 1e-12
            summary = result["portfolio_summaries"][portfolio]
            assert abs(summary["blocked_incremental_weight"] - 0.40) < 1e-12
            assert summary["forced_crisis_sale_weight"] == 0.0


def test_reentry_and_green_multipliers() -> None:
    expected = {
        "REENTRY_STAGE_1": {"AAA": 0.425, "BBB": 0.075, "CASH": 0.50},
        "REENTRY_STAGE_2": {"AAA": 0.46, "BBB": 0.18, "CASH": 0.36},
        "GREEN": {"AAA": 0.50, "BBB": 0.30, "CASH": 0.20},
    }
    for state, wanted in expected.items():
        with tempfile.TemporaryDirectory(prefix=f"paper_buy_guard_{state.lower()}_", dir=ROOT / "_tmp_tests") as temp:
            result = guard.build(fixture(Path(temp), state))
            assert result["status"] == guard.READY_STATUS
            observed = target_weights(result, "main")
            for ticker, value in wanted.items():
                assert abs(observed[ticker] - value) < 1e-12


def test_missing_state_evidence_fails_closed() -> None:
    with tempfile.TemporaryDirectory(prefix="paper_buy_guard_blocked_", dir=ROOT / "_tmp_tests") as temp:
        args = fixture(Path(temp), "WATCH")
        status_path = Path(args.same_close_status)
        status = json.loads(status_path.read_text(encoding="utf-8"))
        status["canonical_crisis_state"]["component_availability"] = []
        write_json(status_path, status)
        result = guard.build(args)
        assert result["status"] == guard.BLOCKED_STATUS
        assert result["target_book_file_written"] is False
        assert not list(Path(args.output_dir).glob("*target_book.csv"))


def test_paper_ledger_accepts_only_complete_guard_handoff() -> None:
    with tempfile.TemporaryDirectory(prefix="paper_buy_guard_handoff_", dir=ROOT / "_tmp_tests") as temp:
        result = guard.build(fixture(Path(temp), "WATCH"))
        manifest_path = Path(temp) / "guard" / "status.json"
        target_paths = {
            portfolio: Path(result["outputs"][f"{portfolio}_target_book"]["path"])
            for portfolio in guard.PORTFOLIOS
        }
        args = SimpleNamespace(
            target_handoff_manifest=str(manifest_path),
            expected_target_handoff_sha256=guard.sha256_file(manifest_path),
            main_target_sha256=guard.sha256_file(target_paths["main"]),
            concentrated_target_sha256=guard.sha256_file(target_paths["concentrated"]),
        )
        audit = validate_target_handoff(
            args=args,
            target_paths=target_paths,
            as_of_date=pd.Timestamp(VALUATION_DATE),
        )
        assert audit["source_manifest_schema_version"] == guard.SCHEMA_VERSION

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["macro_crisis_inputs_bound"] = False
        write_json(manifest_path, manifest)
        args.expected_target_handoff_sha256 = guard.sha256_file(manifest_path)
        try:
            validate_target_handoff(
                args=args,
                target_paths=target_paths,
                as_of_date=pd.Timestamp(VALUATION_DATE),
            )
        except PaperLedgerIntegrityError as exc:
            assert "BLOCKED_TARGET_HANDOFF" in str(exc)
        else:
            raise AssertionError("unsafe paper buy guard handoff was accepted")


def main() -> int:
    (ROOT / "_tmp_tests").mkdir(exist_ok=True)
    test_watch_limits_only_incremental_buys()
    test_reentry_and_green_multipliers()
    test_missing_state_evidence_fails_closed()
    test_paper_ledger_accepts_only_complete_guard_handoff()
    print("run287 paper buy guard target smoke tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
