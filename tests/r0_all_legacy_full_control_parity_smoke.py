#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from argparse import Namespace
from dataclasses import replace
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.r0_all_legacy_full_control_parity import (
    NOT_AVAILABLE,
    _blocked_inputs,
    _native_args,
    build_evaluation_spec,
    build_legacy_specs,
    compare_replay_artifacts,
    compare_target_books,
    hash_path,
    run_g3_comparison,
    target_gate_then,
    validate_isolated_paths,
    validate_native_identity,
    validate_r0_strategy,
)


def check(condition: bool, message: str = "check failed") -> None:
    if not condition:
        raise AssertionError(message)


def expect_error(func, contains: str) -> None:
    try:
        func()
    except Exception as exc:
        check(contains in str(exc), f"{contains!r} not in {exc!r}")
        return
    raise AssertionError("expected exception")


def _write_targets(root: Path, *, weight: float = 0.6, reverse: bool = False) -> Path:
    root.mkdir(parents=True)
    rows = [
        {
            "rebalance_date": "2026-01-30",
            "ticker": "AAA",
            "weight": weight,
            "reason": "legacy",
        },
        {
            "rebalance_date": "2026-01-30",
            "ticker": "CASH",
            "weight": 1.0 - weight,
            "reason": "cash",
        },
    ]
    if reverse:
        rows.reverse()
    for kind in ("main", "concentrated"):
        frame = pd.DataFrame(rows)
        frame["generated_at_utc"] = (
            "2026-10-07T00:00:00Z"
            if not reverse
            else "2099-01-01T00:00:00Z"
        )
        frame.to_csv(root / f"official_{kind}_target_book.csv", index=False)
    return root


def _write_replay(root: Path, *, cash: float = 50.0, with_orders: bool = False) -> Path:
    root.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "date": "2026-01-30",
                "ticker": "AAA",
                "side": "BUY",
                "quantity": 5,
                "fill_price": 10.0,
                "fee_usd": 0.125,
                "reason": "target_rebalance",
            }
        ]
    ).to_csv(root / "trades.csv", index=False)
    pd.DataFrame(
        [{"date": "2026-01-30", "ticker": "AAA", "shares": 5, "weight": 0.5}]
    ).to_csv(root / "holdings_daily.csv", index=False)
    pd.DataFrame([{"ticker": "AAA", "shares": 5, "weight": 0.5}]).to_csv(
        root / "positions_latest.csv", index=False
    )
    pd.DataFrame([{"date": "2026-01-30", "cash_usd": cash}]).to_csv(
        root / "cash_ledger.csv", index=False
    )
    pd.DataFrame(
        [
            {
                "date": "2026-01-30",
                "equity_usd": 100.0,
                "cash_usd": cash,
                "cash_weight": cash / 100.0,
            }
        ]
    ).to_csv(root / "equity_curve.csv", index=False)
    (root / "account_state_latest.json").write_text(
        json.dumps(
            {
                "cash_usd": cash,
                "positions": {"AAA": 5},
                "generated_at_utc": "a",
            }
        ),
        encoding="utf-8",
    )
    (root / "metrics.json").write_text(
        json.dumps(
            {
                "status": "completed",
                "metric_mode": "broker_ledger_next_close",
                "trade_count": 1,
                "total_fees_usd": 0.125,
                "cagr": 0.1,
                "max_dd": -0.05,
            }
        ),
        encoding="utf-8",
    )
    if with_orders:
        pd.DataFrame(
            [
                {
                    "date": "2026-01-30",
                    "ticker": "AAA",
                    "side": "BUY",
                    "quantity": 5,
                }
            ]
        ).to_csv(root / "orders.csv", index=False)
    return root


def test_all_legacy_and_evaluation_contract() -> None:
    main, conc = build_legacy_specs(
        candidate_ref="/frozen/candidates.csv",
        crisis_features_ref="/frozen/features.parquet",
        crisis_thresholds_ref="/frozen/thresholds.json",
    )
    evaluation = build_evaluation_spec(
        universe_data_ref="u",
        calendar_ref="NYSE",
        price_cache_ref="/frozen/cache",
    )
    check(main.hold_exit_module == "LEGACY")
    check(conc.parameters == ())
    check(evaluation.execution_mode == "next_close")
    check(evaluation.cost_bps == 25.0)
    check(evaluation.integer_shares is True)
    check(evaluation.max_fill_lag_days == 7)
    check(evaluation.initial_capital == 100000.0)


def test_g2_selected_fails_closed() -> None:
    main, _ = build_legacy_specs(
        candidate_ref="c",
        crisis_features_ref="f",
        crisis_thresholds_ref="t",
    )
    expect_error(
        lambda: validate_r0_strategy(replace(main, hold_exit_module="G2")),
        "hold_exit_module",
    )


def test_different_evaluation_spec_fails_closed() -> None:
    evaluation = build_evaluation_spec(
        universe_data_ref="u",
        calendar_ref="NYSE",
        price_cache_ref="p",
    )
    from tools.legacy_control_adapter import validate_evaluation_spec

    expect_error(
        lambda: validate_evaluation_spec(
            replace(evaluation, execution_mode="next_open")
        ),
        "execution_mode",
    )


def test_wrong_native_input_identity_fails_closed() -> None:
    main, conc = build_legacy_specs(
        candidate_ref="/frozen/candidate.csv",
        crisis_features_ref="/frozen/features",
        crisis_thresholds_ref="/frozen/thresholds",
    )
    evaluation = build_evaluation_spec(
        universe_data_ref="u",
        calendar_ref="NYSE",
        price_cache_ref="/frozen/cache",
    )
    args = Namespace(
        candidate_book="/wrong/candidate.csv",
        price_cache="/frozen/cache",
        portfolio_kind="both",
        main_target_n=15,
        concentrated_target_n=5,
        production_output_mode="shadow_only",
        skip_broker_replay=True,
        cost_bps=25.0,
        max_fill_lag_days=7,
        long_crisis_features="/frozen/features",
        long_crisis_thresholds="/frozen/thresholds",
    )
    expect_error(
        lambda: validate_native_identity(main, conc, evaluation, args),
        "candidate identity mismatch",
    )


def test_same_output_directory_fails_closed() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        frozen = root / "frozen"
        frozen.mkdir()
        out = root / "out"
        expect_error(
            lambda: validate_isolated_paths(
                direct_dir=out,
                modular_dir=out,
                frozen_paths=[frozen],
            ),
            "must differ",
        )


def test_output_nested_inside_input_fails_closed() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        frozen = root / "frozen"
        frozen.mkdir()
        expect_error(
            lambda: validate_isolated_paths(
                direct_dir=frozen / "direct",
                modular_dir=root / "modular",
                frozen_paths=[frozen],
            ),
            "nested inside frozen input",
        )


def test_target_canonical_sort_and_provenance_normalization() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        direct = _write_targets(root / "direct", reverse=False)
        modular = _write_targets(root / "modular", reverse=True)
        result = compare_target_books(direct, modular)
        check(result["status"] == "parity")


def test_target_divergence_stops_broker_stage() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        direct = _write_targets(root / "direct", weight=0.6)
        modular = _write_targets(root / "modular", weight=0.7)
        result = compare_target_books(direct, modular)
        calls = {"count": 0}

        def broker():
            calls["count"] += 1
            return "should-not-run"

        gated, value = target_gate_then(result, broker)
        check(gated is False)
        check(value is None)
        check(calls["count"] == 0)


def test_target_parity_allows_broker_stage() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        result = compare_target_books(
            _write_targets(root / "direct"),
            _write_targets(root / "modular"),
        )
        calls = {"count": 0}

        def broker():
            calls["count"] += 1
            return "ok"

        gated, value = target_gate_then(result, broker)
        check(gated is True and value == "ok" and calls["count"] == 1)


def test_hash_path_is_deterministic_and_detects_mutation() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "a.txt").write_text("a", encoding="utf-8")
        before = hash_path(root)
        again = hash_path(root)
        check(before == again)
        (root / "a.txt").write_text("b", encoding="utf-8")
        after = hash_path(root)
        check(before["sha256"] != after["sha256"])


def test_missing_real_price_cache_blocks() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        latest = root / "latest"
        latest.mkdir()
        candidate = root / "candidate.csv"
        candidate.write_text("ticker\nAAA\n", encoding="utf-8")
        features = root / "features.parquet"
        features.write_bytes(b"x")
        thresholds = root / "thresholds.json"
        thresholds.write_text("{}", encoding="utf-8")
        missing = _blocked_inputs(
            latest_run=latest,
            candidate_book=candidate,
            price_cache=root / "missing_cache",
            crisis_features=features,
            crisis_thresholds=thresholds,
        )
        check(any(item.startswith("price_cache:") for item in missing))


def test_native_args_enforce_shadow_only_and_target_gate() -> None:
    args = _native_args(
        latest_run=Path("/x/latest"),
        candidate_book=Path("/x/candidate"),
        price_cache=Path("/x/cache"),
        output_dir=Path("/x/out"),
        crisis_features=Path("/x/features"),
        crisis_thresholds=Path("/x/thresholds"),
    )
    check(args.production_output_mode == "shadow_only")
    check(args.skip_broker_replay is True)
    check(args.cost_bps == 25.0)
    check(args.max_fill_lag_days == 7)


def test_broker_parity_and_optional_orders_not_available() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        direct = _write_replay(root / "direct")
        modular = _write_replay(root / "modular")
        result = compare_replay_artifacts(direct, modular)
        check(result["status"] == "parity")
        check("orders.csv" in result["not_available"])
        check(result["artifacts"]["orders.csv"]["status"] == NOT_AVAILABLE)


def test_broker_economic_divergence_detected() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        direct = _write_replay(root / "direct", cash=50.0)
        modular = _write_replay(root / "modular", cash=49.0)
        result = compare_replay_artifacts(direct, modular)
        check(result["status"] == "divergence")


def test_g3_read_only_no_divergence() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        direct = _write_replay(root / "direct")
        modular = _write_replay(root / "modular")
        before = (hash_path(direct), hash_path(modular))
        result = run_g3_comparison(direct, modular, "main")
        after = (hash_path(direct), hash_path(modular))
        check(result["report"]["status"] == "no_divergence")
        check(result["read_only_verified"] is True)
        check(before == after)


def test_same_replay_ref_fails_closed() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        replay = _write_replay(Path(tmp) / "replay")
        expect_error(
            lambda: compare_replay_artifacts(replay, replay),
            "same directory",
        )


def test_structural_fixture_is_not_full_r0_pass() -> None:
    check("R0_FULL_CONTROL_PARITY_PASS" not in globals())


def run_all() -> int:
    tests = [
        value
        for key, value in sorted(globals().items())
        if key.startswith("test_") and callable(value)
    ]
    for func in tests:
        func()
    print(
        f"r0_all_legacy_full_control_parity_smoke: PASS "
        f"({len(tests)} structural tests)"
    )
    return len(tests)


def main() -> int:
    count = run_all()
    if sys.flags.optimize == 0 and os.environ.get("R0_OPTIMIZED_CHILD") != "1":
        env = dict(os.environ)
        env["R0_OPTIMIZED_CHILD"] = "1"
        proc = subprocess.run(
            [sys.executable, "-O", str(Path(__file__).resolve())],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            check=False,
        )
        check(proc.returncode == 0, proc.stdout + proc.stderr)
        check(
            f"PASS ({count} structural tests)" in proc.stdout,
            "optimized structural smoke did not report the same test count",
        )
        print("r0_all_legacy_full_control_parity_smoke: OPTIMIZED PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
