#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import archive_run287_ohlcv_pattern_memory as memory  # noqa: E402
from tools.build_run287_holding_risk_watch import sha256_file, write_json  # noqa: E402


def fingerprint(path: Path) -> dict[str, object]:
    return {
        "path": str(path),
        "exists": True,
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def write_timing(
    root: Path,
    *,
    as_of_date: str,
    stock_close: float,
    stock_prior_return: float,
    stock_return: float,
    spy_close: float,
    spy_prior_return: float,
    spy_return: float,
) -> Path:
    source = root / f"timing_{as_of_date}"
    source.mkdir(parents=True)
    security = {
        "ticker": "AAA",
        "as_of_date": as_of_date,
        "close": stock_close,
        "prior_return_1d": stock_prior_return,
        "return_1d": stock_return,
        "return_2d": (1.0 + stock_prior_return) * (1.0 + stock_return) - 1.0,
        "return_transition_signature": memory_signature(
            stock_prior_return,
            stock_return,
        ),
        "prior_down_current_up": stock_prior_return < 0.0 < stock_return,
        "data_reason": "",
        "is_held": True,
        "portfolios": "main",
        "shadow_action": "HOLD_REVIEW",
        "forward_outcome_status": "UNRESOLVED",
    }
    observations = source / "forward_observations.jsonl"
    observations.write_text(
        json.dumps(security, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    benchmark = source / "benchmark_location.csv"
    pd.DataFrame(
        [
            {
                "ticker": "SPY",
                "close": spy_close,
                "prior_return_1d": spy_prior_return,
                "return_1d": spy_return,
                "return_2d": (1.0 + spy_prior_return) * (1.0 + spy_return)
                - 1.0,
                "return_transition_signature": memory_signature(
                    spy_prior_return,
                    spy_return,
                ),
                "data_reason": "",
            },
            {
                "ticker": "QQQ",
                "close": spy_close * 0.9,
                "prior_return_1d": -0.02,
                "return_1d": -0.01,
                "return_2d": (1.0 - 0.02) * (1.0 - 0.01) - 1.0,
                "return_transition_signature": "CONTINUED_DOWN",
                "data_reason": "",
            },
        ]
    ).to_csv(benchmark, index=False)
    summary = source / "summary.json"
    write_json(
        summary,
        {
            "schema_version": "run287-ohlcv-location-timing-challenger-v1",
            "status": "READY_OHLCV_LOCATION_TIMING_FORWARD_REVIEW_ONLY",
            "as_of_date": as_of_date,
            "available_from": f"{as_of_date}T20:00:00Z",
            "forward_observation_window": {
                "observation_accepted_at_utc": f"{as_of_date}T21:00:00Z"
            },
            "portfolio_transition_allowed": False,
            "orders_generated": False,
            "target_books_mutated": False,
            "selector_weights_changed": False,
            "cash_policy_changed": False,
            "champion_changed": False,
            "backtest_executed": False,
            "fullrun_executed": False,
            "production_activation_allowed": False,
            "live_trading_enabled": False,
            "outputs": {
                "forward_observations": fingerprint(observations),
                "benchmark_location": fingerprint(benchmark),
            },
        },
    )
    return summary


def memory_signature(prior: float, current: float) -> str:
    if prior < 0.0 < current:
        return "DOWN_TO_UP_REVERSAL"
    if prior > 0.0 > current:
        return "UP_TO_DOWN_REVERSAL"
    if prior < 0.0 and current < 0.0:
        return "CONTINUED_DOWN"
    if prior > 0.0 and current > 0.0:
        return "CONTINUED_UP"
    return "FLAT_OR_INSUFFICIENT"


def args_for(summary: Path, archive: Path, date: str) -> argparse.Namespace:
    return argparse.Namespace(
        timing_summary=str(summary),
        contract=str(
            ROOT / "docs" / "run287_ohlcv_pattern_memory_contract.json"
        ),
        valuation_date=date,
        output_dir=str(archive),
    )


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        archive = root / "archive" / "ohlcv_pattern_memory"
        first_summary = write_timing(
            root,
            as_of_date="2026-07-29",
            stock_close=96.0,
            stock_prior_return=-0.04,
            stock_return=0.06,
            spy_close=500.0,
            spy_prior_return=-0.02,
            spy_return=0.03,
        )
        first = memory.build(args_for(first_summary, archive, "2026-07-29"))
        assert first["status"] == memory.READY_STATUS, first
        assert first["appended_observation_count"] == 3
        assert first["resolved_outcome_event_count"] == 0
        assert first["proposal_eligible"] is False

        repeated = memory.build(args_for(first_summary, archive, "2026-07-29"))
        assert repeated["status"] == memory.READY_STATUS, repeated
        assert repeated["appended_observation_count"] == 0
        assert repeated["appended_outcome_count"] == 0

        second_summary = write_timing(
            root,
            as_of_date="2026-07-30",
            stock_close=100.0,
            stock_prior_return=0.06,
            stock_return=-0.02,
            spy_close=505.0,
            spy_prior_return=0.03,
            spy_return=0.01,
        )
        second = memory.build(args_for(second_summary, archive, "2026-07-30"))
        assert second["status"] == memory.READY_STATUS, second
        assert second["appended_observation_count"] == 3
        assert second["appended_outcome_count"] == 3
        assert second["resolved_outcome_event_count"] == 3
        security_aggregate = next(
            row
            for row in second["aggregates"]
            if row["source_kind"] == "SECURITY"
            and row["pattern_signature"] == "DOWN_TO_UP_REVERSAL"
            and row["horizon_nyse_sessions"] == 1
        )
        assert security_aggregate["resolved_observation_count"] == 1
        assert security_aggregate["underpowered"] is True
        assert security_aggregate["directional_statistics_published"] is False
        assert "directional_statistics" not in security_aggregate

        observations = memory.read_jsonl(archive / "observations.jsonl")
        outcomes = memory.read_jsonl(archive / "outcomes.jsonl")
        assert len(observations) == 6
        assert len(outcomes) == 3
        stock_outcome = next(
            row for row in outcomes if row["source_kind"] == "SECURITY"
        )
        assert abs(stock_outcome["forward_return"] - (100.0 / 96.0 - 1.0)) < 1e-12
        assert stock_outcome["target_session_date"] == "2026-07-30"
        assert stock_outcome["resolution_policy"] == (
            "EXACT_ARCHIVED_NYSE_TARGET_SESSION_ONLY"
        )

        out_of_order = memory.build(
            args_for(first_summary, archive, "2026-07-29")
        )
        assert out_of_order["status"] == memory.BLOCKED_STATUS
        assert "out-of-order observation" in " ".join(
            out_of_order["contract_failures"]
        )
        assert len(memory.read_jsonl(archive / "observations.jsonl")) == 6

        second_payload = json.loads(
            second_summary.read_text(encoding="utf-8")
        )
        source_observations = Path(
            second_payload["outputs"]["forward_observations"]["path"]
        )
        source_observations.write_text(
            source_observations.read_text(encoding="utf-8").replace(
                '"close":100.0',
                '"close":101.0',
            ),
            encoding="utf-8",
        )
        changed = memory.build(
            args_for(second_summary, archive, "2026-07-30")
        )
        assert changed["status"] == memory.BLOCKED_STATUS
        assert "fingerprint mismatch" in " ".join(changed["contract_failures"])
        assert len(memory.read_jsonl(archive / "observations.jsonl")) == 6

    # A report failure may occur after the append-only observation commit.
    # The next invocation resumes by event identity without duplicating rows.
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        archive = root / "archive" / "ohlcv_pattern_memory"
        summary = write_timing(
            root,
            as_of_date="2026-07-29",
            stock_close=96.0,
            stock_prior_return=-0.04,
            stock_return=0.06,
            spy_close=500.0,
            spy_prior_return=-0.02,
            spy_return=0.03,
        )
        original_atomic_write_text = memory.atomic_write_text

        def fail_report(path: Path, text: str) -> None:
            if path.name == "report.md":
                raise OSError("simulated report failure")
            original_atomic_write_text(path, text)

        memory.atomic_write_text = fail_report
        try:
            interrupted = memory.build(
                args_for(summary, archive, "2026-07-29")
            )
        finally:
            memory.atomic_write_text = original_atomic_write_text
        assert interrupted["status"] == memory.BLOCKED_STATUS
        assert len(memory.read_jsonl(archive / "observations.jsonl")) == 3
        resumed = memory.build(args_for(summary, archive, "2026-07-29"))
        assert resumed["status"] == memory.READY_STATUS, resumed
        assert resumed["appended_observation_count"] == 0
        assert len(memory.read_jsonl(archive / "observations.jsonl")) == 3

        rows = memory.read_jsonl(archive / "observations.jsonl")
        rows[0]["event_hash"] = "0" * 64
        (archive / "observations.jsonl").write_text(
            "".join(
                json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n"
                for row in rows
            ),
            encoding="utf-8",
        )
        tampered = memory.build(args_for(summary, archive, "2026-07-29"))
        assert tampered["status"] == memory.BLOCKED_STATUS
        assert "archive event hash mismatch" in " ".join(
            tampered["contract_failures"]
        )

    print("run287_ohlcv_pattern_memory_smoke: PASS")


if __name__ == "__main__":
    main()
