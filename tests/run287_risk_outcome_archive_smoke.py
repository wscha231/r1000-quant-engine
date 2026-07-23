#!/usr/bin/env python3
"""Smoke tests for the forward-only Run287 risk outcome archive."""
from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
import sys

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.resolve_run287_risk_outcomes import (  # noqa: E402
    BLOCKED_STATUS,
    NEEDS_PRICE_CACHE_STATUS,
    READY_STATUS,
    SKIPPED_STATUS,
    EVENT_LOG_NAME,
    group_metrics,
    load_nyse_sessions,
    run,
    sha256_file,
)
from tools.run_weekly_evaluation import px_cache_name  # noqa: E402


DECISION = "2026-01-05"


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def base_flags() -> dict:
    return {
        "portfolio_transition_allowed": False,
        "orders_generated": False,
        "target_books_mutated": False,
        "selector_weight_changed_by_archive": False,
        "historical_cagr_mdd_evidence_changed": False,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
    }


def write_archive(path: Path, *, candidate_state: str = "WATCH", unsafe: bool = False) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "manifest.json").write_text(
        json.dumps({"status": "READY_DECISION_OBSERVATION_ARCHIVE_REVIEW_ONLY", "archive_passed": True}),
        encoding="utf-8",
    )
    candidate = {
        "event_id": "candidate-bbb",
        "as_of_date": DECISION,
        "ticker": "BBB",
        "risk_state": candidate_state,
        "advisory_action": "REVIEW_BEFORE_INCREMENTAL_BUY",
        "reason_codes": "volatility_spike",
        "history_observations": 400,
        "return_1d": -0.04,
        "spy_excess_return_1d": -0.03,
        "return_21d": -0.08,
        "spy_excess_return_21d": -0.06,
        "drawdown_63d": -0.15,
        "risk_state_may_authorize_buy": False,
        **base_flags(),
    }
    if unsafe:
        candidate["orders_generated"] = True
    write_jsonl(path / "candidate_risk_history.jsonl", [candidate])
    rows = []
    for scenario in ["strict_registered_current", "prior_hold_transition_bridge"]:
        rows.append(
            {
                "event_id": f"held-aaa-{scenario}",
                "as_of_date": DECISION,
                "portfolio_kind": "main",
                "scenario": scenario,
                "ticker": "AAA",
                "marked_weight": 0.20,
                "official_prior_weight": 0.19,
                "advisory_weight": 0.18,
                "proposed_new_entry": False,
                "held_risk_state": "ALERT",
                "held_risk_advisory_action": "FREEZE_INCREMENTAL_BUY_AND_MANUAL_REVIEW",
                "held_risk_reason_codes": "idiosyncratic_shock",
                **base_flags(),
            }
        )
    rows.append(
        {
            "event_id": "proposed-bbb",
            "as_of_date": DECISION,
            "portfolio_kind": "concentrated",
            "scenario": "strict_registered_current",
            "ticker": "BBB",
            "marked_weight": 0.0,
            "official_prior_weight": 0.0,
            "advisory_weight": 0.10,
            "proposed_new_entry": True,
            "held_risk_state": "",
            "held_risk_advisory_action": "",
            "held_risk_reason_codes": "",
            **base_flags(),
        }
    )
    write_jsonl(path / "position_history.jsonl", rows)


def args(archive: Path, cache: Path, output: Path, as_of: str) -> argparse.Namespace:
    return argparse.Namespace(
        decision_archive=str(archive),
        price_cache=str(cache),
        output_dir=str(output),
        contract=str(ROOT / "docs" / "run287_risk_outcome_archive_contract.json"),
        as_of_date=as_of,
    )


def sessions_through_126() -> pd.DatetimeIndex:
    sessions = load_nyse_sessions(pd.Timestamp(DECISION), pd.Timestamp("2026-08-31"))
    assert sessions is not None and len(sessions) > 126
    assert pd.Timestamp(DECISION) in sessions
    return sessions[:127]


def write_price(cache: Path, ticker: str, sessions: pd.DatetimeIndex, values: np.ndarray) -> None:
    cache.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"Close": values, "Adj Close": values}, index=sessions).to_parquet(cache / px_cache_name(ticker))
    cache_files = {}
    for path in sorted(cache.glob("*.parquet")):
        cache_ticker = path.stem
        cache_files[cache_ticker] = {
            "file": path.name,
            "sha256": sha256_file(path),
            "bytes": path.stat().st_size,
        }
    (cache / "replay_price_cache_manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "run287-replay-price-cache-manifest-v2",
                "book_inputs": [],
                "cache_files": cache_files,
                "review_only": True,
                "production_mutation_allowed": False,
                "live_trading_enabled": False,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )


def test_capture_pending_and_bounded_price_universe() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        archive, cache, output = root / "archive", root / "cache", root / "out"
        write_archive(archive)
        result = run(args(archive, cache, output, DECISION), now_utc="2026-01-06T01:00:00Z")
        assert result["status"] == NEEDS_PRICE_CACHE_STATUS, result
        assert result["signal_observation_count"] == 2
        assert result["held_signal_observation_count"] == 1
        assert result["candidate_signal_observation_count"] == 1
        assert result["forward_outcome_event_count"] == 0
        assert result["mechanism_review_ready"] is False
        assert result["orders_generated"] is False
        universe = pd.read_csv(output / "price_universe.csv")
        assert set(universe["ticker"]) == {"AAA", "BBB", "SPY"}
        assert result["price_universe_unique_ticker_count"] == 3


def test_restored_price_cache_bootstraps_new_observation_ticker() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        archive, cache, output = root / "archive", root / "cache", root / "out"
        write_archive(archive)
        sessions = sessions_through_126()[:2]
        write_price(cache, "AAA", sessions, np.linspace(100, 99, len(sessions)))
        write_price(cache, "SPY", sessions, np.linspace(100, 101, len(sessions)))
        assert (cache / "replay_price_cache_manifest.json").is_file()
        assert not (cache / px_cache_name("BBB")).exists()

        result = run(
            args(
                archive,
                cache,
                output,
                pd.Timestamp(sessions[-1]).date().isoformat(),
            ),
            now_utc="2026-01-07T01:00:00Z",
        )

        assert result["status"] == NEEDS_PRICE_CACHE_STATUS, result
        assert result["price_cache_bootstrap_required"] is True
        assert result["missing_price_cache_tickers"] == ["BBB"]
        assert json.loads((output / "summary.json").read_text(encoding="utf-8"))[
            "status"
        ] == NEEDS_PRICE_CACHE_STATUS
        universe = pd.read_csv(output / "price_universe.csv")
        assert set(universe["ticker"]) == {"AAA", "BBB", "SPY"}
        status = pd.read_csv(output / "current_status.csv")
        bbb = status[status["ticker"].eq("BBB")].iloc[0]
        assert (
            bbb["outcome_1d_status"]
            == "pending_ticker_adjusted_price_unavailable"
        )


def test_missing_initial_source_skips_without_breaking_daily_workflow() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        result = run(args(root / "missing", root / "cache", root / "out", DECISION))
        assert result["status"] == SKIPPED_STATUS
        assert result["signal_observation_count"] == 0
        assert result["orders_generated"] is False
        for field in (
            "mechanism_promotion_allowed",
            "threshold_tuning_allowed",
            "stop_or_exit_rule_created",
            "selector_weights_changed",
            "cash_policy_changed",
            "portfolio_transition_allowed",
            "orders_generated",
            "target_books_mutated",
            "historical_cagr_mdd_evidence_changed",
            "backtest_executed",
            "fullrun_executed",
            "production_activation_allowed",
            "live_trading_enabled",
        ):
            assert result[field] is False, field
        assert not (root / "out" / EVENT_LOG_NAME).exists()


def test_restored_signals_continue_resolving_when_daily_source_skips() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        archive, cache, output = root / "archive", root / "cache", root / "out"
        write_archive(archive)
        assert run(args(archive, cache, output, DECISION))["signal_observation_count"] == 2
        sessions = sessions_through_126()
        short = sessions[:6]
        write_price(cache, "AAA", short, np.linspace(100, 95, len(short)))
        write_price(cache, "BBB", short, np.linspace(80, 82, len(short)))
        write_price(cache, "SPY", short, np.linspace(100, 101, len(short)))
        missing_archive = root / "daily-source-skipped"
        result = run(
            args(missing_archive, cache, output, pd.Timestamp(short[-1]).date().isoformat()),
            now_utc="2026-01-13T01:00:00Z",
        )
        assert result["status"] == READY_STATUS
        assert result["signal_observation_count"] == 2
        assert result["forward_outcome_event_count"] == 4
        assert result["appended_event_counts"] == {"forward_outcome_observed": 4}


def test_elapsed_outcomes_and_idempotence() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        archive, cache, output = root / "archive", root / "cache", root / "out"
        write_archive(archive)
        sessions = sessions_through_126()
        x = np.arange(len(sessions), dtype=float)
        write_price(cache, "AAA", sessions, 100.0 - 0.40 * x)
        write_price(cache, "BBB", sessions, 80.0 + 0.25 * x)
        write_price(cache, "SPY", sessions, 100.0 + 0.10 * x)
        as_of = pd.Timestamp(sessions[21]).date().isoformat()
        first = run(args(archive, cache, output, as_of), now_utc="2026-02-05T01:00:00Z")
        assert first["status"] == READY_STATUS
        assert first["forward_outcome_event_count"] == 6
        assert first["appended_event_counts"] == {"risk_signal_observed": 2, "forward_outcome_observed": 6}
        status = pd.read_csv(output / "current_status.csv")
        assert set(status["outcome_1d_status"]) == {"completed"}
        assert set(status["outcome_5d_status"]) == {"completed"}
        assert set(status["outcome_21d_status"]) == {"completed"}
        assert set(status["outcome_63d_status"]) == {"pending_not_elapsed"}
        assert set(first["group_metrics"]) == {"1d", "21d", "63d"}
        assert first["group_metrics"]["1d"]["warning"]["count"] == 2
        assert first["group_metrics"]["1d"]["warning"]["distinct_tickers"] == 2
        assert first["group_metrics"]["1d"]["warning"]["mean_actionable_spy_excess_total_return"] is None
        report = (output / "report.md").read_text(encoding="utf-8")
        assert "1D resolved warning/normal (diagnostic only): `2` / `0`" in report
        assert "1D actionable metrics are not applicable" in report
        aaa = status[status["ticker"].eq("AAA")].iloc[0]
        expected = (100.0 - 0.40 * 21) / 100.0 - 1.0
        assert abs(float(aaa["outcome_21d_ticker_total_return"]) - expected) < 1e-12
        assert float(aaa["outcome_21d_ticker_max_drawdown"]) < 0
        assert pd.notna(aaa["outcome_21d_actionable_ticker_total_return"])
        before = (output / EVENT_LOG_NAME).read_bytes()
        second = run(args(archive, cache, output, as_of), now_utc="2026-02-05T02:00:00Z")
        assert second["appended_event_counts"] == {}
        assert (output / EVENT_LOG_NAME).read_bytes() == before


def test_missing_path_stays_pending_and_never_zero_filled() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        archive, cache, output = root / "archive", root / "cache", root / "out"
        write_archive(archive)
        sessions = sessions_through_126()
        short = sessions[:6]
        write_price(cache, "AAA", short, np.linspace(100, 95, len(short)))
        bbb_values = np.linspace(80, 85, len(short))
        write_price(cache, "BBB", short.delete(3), np.delete(bbb_values, 3))
        write_price(cache, "SPY", short, np.linspace(100, 101, len(short)))
        result = run(
            args(archive, cache, output, pd.Timestamp(short[-1]).date().isoformat()),
            now_utc="2026-01-13T01:00:00Z",
        )
        assert result["status"] == READY_STATUS
        status = pd.read_csv(output / "current_status.csv")
        bbb = status[status["ticker"].eq("BBB")].iloc[0]
        assert bbb["outcome_5d_status"] == "pending_ticker_price_path_unavailable"
        assert pd.isna(bbb["outcome_5d_ticker_total_return"])


def test_changed_or_unsafe_source_fails_closed() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        archive, cache, output = root / "archive", root / "cache", root / "out"
        write_archive(archive)
        assert (
            run(args(archive, cache, output, DECISION))["status"]
            == NEEDS_PRICE_CACHE_STATUS
        )
        before = (output / EVENT_LOG_NAME).read_bytes()
        write_archive(archive, candidate_state="ALERT")
        conflict = run(args(archive, cache, output, DECISION))
        assert conflict["status"] == BLOCKED_STATUS
        assert any("immutable_signal_conflict" in value for value in conflict["blockers"])
        assert (output / EVENT_LOG_NAME).read_bytes() == before
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        archive, cache, output = root / "archive", root / "cache", root / "out"
        write_archive(archive, unsafe=True)
        unsafe = run(args(archive, cache, output, DECISION))
        assert unsafe["status"] == BLOCKED_STATUS
        assert any("orders_generated_true" in value for value in unsafe["blockers"])
        assert not (output / EVENT_LOG_NAME).exists()


def test_daily_workflow_wires_bounded_resolution_and_persistence() -> None:
    workflow = (ROOT / ".github" / "workflows" / "daily_operating_selection_refresh.yml").read_text(encoding="utf-8")
    required = [
        "tools/resolve_run287_risk_outcomes.py",
        "outputs/run287_risk_outcome_archive",
        "outputs/run287_risk_outcome_price_cache",
        "--max-tickers 150",
        "daily_run287_risk_outcomes.log",
        "paper_archive/run287_risk_outcome_archive",
    ]
    for token in required:
        assert token in workflow, token


def test_data_insufficient_is_not_a_normal_control() -> None:
    frame = pd.DataFrame(
        [
            {"decision_date": DECISION, "ticker": "AAA", "family": "held", "portfolio_kind": "main", "risk_state": "NORMAL", "iso_decision_week": "2026-W02", "outcome_21d_status": "completed", "outcome_21d_spy_excess_total_return": 0.01, "outcome_21d_ticker_max_drawdown": -0.02, "outcome_21d_actionable_spy_excess_total_return": 0.01},
            {"decision_date": DECISION, "ticker": "MISS", "family": "held", "portfolio_kind": "main", "risk_state": "DATA_INSUFFICIENT", "iso_decision_week": "2026-W02", "outcome_21d_status": "completed", "outcome_21d_spy_excess_total_return": -0.50, "outcome_21d_ticker_max_drawdown": -0.60, "outcome_21d_actionable_spy_excess_total_return": -0.50},
        ]
    )
    metrics = group_metrics(frame, 21)
    assert metrics["normal"]["count"] == 1
    assert abs(metrics["normal"]["mean_spy_excess_total_return"] - 0.01) < 1e-12


def main() -> int:
    test_capture_pending_and_bounded_price_universe()
    test_restored_price_cache_bootstraps_new_observation_ticker()
    test_missing_initial_source_skips_without_breaking_daily_workflow()
    test_restored_signals_continue_resolving_when_daily_source_skips()
    test_elapsed_outcomes_and_idempotence()
    test_missing_path_stays_pending_and_never_zero_filled()
    test_changed_or_unsafe_source_fails_closed()
    test_daily_workflow_wires_bounded_resolution_and_persistence()
    test_data_insufficient_is_not_a_normal_control()
    print("run287_risk_outcome_archive_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
