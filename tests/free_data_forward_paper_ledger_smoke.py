#!/usr/bin/env python3
"""Focused synthetic-price smoke tests for the forward paper ledger."""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.run_free_data_forward_paper_ledger import (  # noqa: E402
    EVENT_LOG_NAME,
    load_nyse_sessions,
    read_events,
    run,
)
from tools.run_weekly_evaluation import px_cache_name  # noqa: E402


def _write_prices(cache: Path, ticker: str, dates: pd.DatetimeIndex, values: np.ndarray, *, adjusted: bool = True) -> None:
    cache.mkdir(parents=True, exist_ok=True)
    payload = {"Close": values}
    if adjusted:
        payload["Adj Close"] = values
    pd.DataFrame(payload, index=dates).to_parquet(cache / px_cache_name(ticker))


def _nyse_dates(start: str, end: str, count: int) -> pd.DatetimeIndex:
    dates = load_nyse_sessions(pd.Timestamp(start), pd.Timestamp(end))
    assert dates is not None and len(dates) >= count
    return dates[:count]


def _write_overlay(root: Path, decision_date: str, tickers: list[str], *, generated_at: str | None = None) -> tuple[Path, Path]:
    overlay = root / f"overlay_{decision_date.replace('-', '')}_{'_'.join(tickers)}"
    overlay.mkdir(parents=True)
    rows = []
    for rank, ticker in enumerate(tickers, start=1):
        rows.append(
            {
                "ticker": ticker,
                "free_data_selection_rank": rank,
                "free_data_selection_score": 0.9 - rank * 0.01,
                "free_data_base_rank_score": 0.8,
                "free_data_forward_estimate_score": 0.7,
                "free_data_recent_actual_score": 0.2,
                "free_data_evidence_coverage_count": 2,
                "estimate_revision_confirmed": 1,
                "has_forward_estimate": 1,
                "free_data_selection_label": "research_only_latest_overlay",
                "production_promotion_allowed": False,
                "historical_backtest_acceptance_allowed": False,
            }
        )
    candidates = overlay / "selected_candidates.csv"
    pd.DataFrame(rows).to_csv(candidates, index=False)
    summary = overlay / "summary.json"
    summary.write_text(
        json.dumps(
            {
                "schema_version": "free-data-selection-overlay-v1",
                "status": "completed",
                "decision_date": decision_date,
                "generated_at_utc": generated_at or f"{decision_date}T20:00:00Z",
                "production_promotion_allowed": False,
                "historical_backtest_acceptance_allowed": False,
            }
        ),
        encoding="utf-8",
    )
    return candidates, summary


def _args(candidates: Path, summary: Path, cache: Path, output: Path, as_of: str) -> argparse.Namespace:
    return argparse.Namespace(
        candidates=str(candidates),
        overlay_summary=str(summary),
        price_cache=str(cache),
        output_dir=str(output),
        benchmark="SPY",
        as_of_date=as_of,
    )


def test_append_only_progression_and_spy_relative_outcomes() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache_prices"
        output = root / "ledger"
        candidates, summary_path = _write_overlay(root, "2026-01-02", ["AAA"])
        dates = _nyse_dates("2026-01-05", "2026-08-31", 140)
        ticker_values = 100.0 * np.power(1.001, np.arange(len(dates)))
        spy_values = 200.0 * np.power(1.0005, np.arange(len(dates)))
        _write_prices(cache, "AAA", dates, ticker_values)
        _write_prices(cache, "SPY", dates, spy_values)

        first = run(
            _args(candidates, summary_path, cache, output, "2026-01-02"),
            now_utc="2026-01-02T21:00:00Z",
        )
        assert first["event_counts"] == {"signal_observed": 1}
        status = pd.read_csv(output / "current_status.csv")
        assert status.loc[0, "reference_status"] == "pending_next_close_not_elapsed"
        assert status.loc[0, "outcome_21d_status"] == "pending_reference"
        original_prefix = (output / EVENT_LOG_NAME).read_bytes()

        mid_date = str(dates[70].date())
        second = run(
            _args(candidates, summary_path, cache, output, mid_date),
            now_utc=f"{mid_date}T23:00:00Z",
        )
        appended = second["appended_event_counts"]
        assert appended == {"next_close_reference_observed": 1, "forward_outcome_observed": 2}, appended
        events = read_events(output / EVENT_LOG_NAME)
        assert [event["event_type"] for event in events].count("signal_observed") == 1
        assert (output / EVENT_LOG_NAME).read_bytes().startswith(original_prefix)
        status = pd.read_csv(output / "current_status.csv")
        assert status.loc[0, "next_close_date"] == "2026-01-05"
        assert status.loc[0, "outcome_21d_status"] == "completed"
        assert status.loc[0, "outcome_63d_status"] == "completed"
        assert status.loc[0, "outcome_126d_status"] == "pending_not_elapsed"
        expected_ticker_21 = ticker_values[21] / ticker_values[0] - 1.0
        expected_spy_21 = spy_values[21] / spy_values[0] - 1.0
        assert abs(status.loc[0, "outcome_21d_ticker_total_return"] - expected_ticker_21) < 1e-12
        assert abs(status.loc[0, "outcome_21d_excess_total_return"] - (expected_ticker_21 - expected_spy_21)) < 1e-12
        assert status.loc[0, "outcome_21d_ticker_max_drawdown"] == 0.0

        prefix_after_mid = (output / EVENT_LOG_NAME).read_bytes()
        last_date = str(dates[130].date())
        third = run(
            _args(candidates, summary_path, cache, output, last_date),
            now_utc=f"{last_date}T23:00:00Z",
        )
        assert third["appended_event_counts"] == {"forward_outcome_observed": 1}
        assert (output / EVENT_LOG_NAME).read_bytes().startswith(prefix_after_mid)
        status = pd.read_csv(output / "current_status.csv")
        assert status.loc[0, "outcome_126d_status"] == "completed"
        assert third["coverage"]["horizons"]["126d"]["completed_ratio"] == 1.0

        before_rerun = (output / EVENT_LOG_NAME).read_bytes()
        fourth = run(
            _args(candidates, summary_path, cache, output, last_date),
            now_utc=f"{last_date}T23:30:00Z",
        )
        assert fourth["appended_event_counts"] == {}
        assert (output / EVENT_LOG_NAME).read_bytes() == before_rerun
        schema = json.loads((output / "schema.json").read_text(encoding="utf-8"))
        assert schema["event_log_append_only"] is True
        assert schema["historical_backtest_acceptance_allowed"] is False
        assert schema["valid_for_backtest"] is False
        assert schema["production_promotion_allowed"] is False
        assert schema["valid_for_production"] is False
        assert schema["live_trading_enabled"] is False


def test_missing_price_path_stays_pending_until_available() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache_prices"
        output = root / "ledger"
        candidates, summary_path = _write_overlay(root, "2026-02-02", ["BBB"])
        dates = _nyse_dates("2026-02-03", "2026-04-30", 40)
        spy = 100.0 + np.arange(len(dates), dtype=float)
        ticker = 50.0 + np.arange(len(dates), dtype=float)
        _write_prices(cache, "SPY", dates, spy)
        missing_date = dates[21]
        keep = dates != missing_date
        _write_prices(cache, "BBB", dates[keep], ticker[keep])

        run(
            _args(candidates, summary_path, cache, output, "2026-02-02"),
            now_utc="2026-02-02T21:00:00Z",
        )
        as_of = str(dates[30].date())
        pending = run(
            _args(candidates, summary_path, cache, output, as_of),
            now_utc=f"{as_of}T23:00:00Z",
        )
        status = pd.read_csv(output / "current_status.csv")
        assert status.loc[0, "reference_status"] == "reference_observed"
        assert status.loc[0, "outcome_21d_status"] == "pending_ticker_price_path_unavailable"
        assert pending["event_counts"].get("forward_outcome_observed", 0) == 0

        prefix = (output / EVENT_LOG_NAME).read_bytes()
        _write_prices(cache, "BBB", dates, ticker)
        completed = run(
            _args(candidates, summary_path, cache, output, as_of),
            now_utc=f"{as_of}T23:30:00Z",
        )
        assert completed["appended_event_counts"] == {"forward_outcome_observed": 1}
        assert (output / EVENT_LOG_NAME).read_bytes().startswith(prefix)
        status = pd.read_csv(output / "current_status.csv")
        assert status.loc[0, "outcome_21d_status"] == "completed"


def test_missing_exact_next_nyse_session_does_not_shift_reference() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache_prices"
        output = root / "ledger"
        candidates, summary_path = _write_overlay(root, "2026-01-02", ["GAP"])
        dates = _nyse_dates("2026-01-05", "2026-03-31", 30)
        _write_prices(cache, "GAP", dates, 50.0 + np.arange(len(dates), dtype=float))
        _write_prices(cache, "SPY", dates[1:], 100.0 + np.arange(len(dates) - 1, dtype=float))

        run(
            _args(candidates, summary_path, cache, output, "2026-01-02"),
            now_utc="2026-01-02T21:00:00Z",
        )
        as_of = str(dates[10].date())
        summary = run(
            _args(candidates, summary_path, cache, output, as_of),
            now_utc=f"{as_of}T23:00:00Z",
        )
        status = pd.read_csv(output / "current_status.csv")
        assert status.loc[0, "reference_status"] == "pending_benchmark_reference_price_unavailable"
        assert summary["event_counts"] == {"signal_observed": 1}
        assert not any(
            event["event_type"] == "next_close_reference_observed"
            for event in read_events(output / EVENT_LOG_NAME)
        )


def test_stale_overlay_cannot_seed_or_revise_forward_observations() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache_prices"

        stale_candidates, stale_summary = _write_overlay(root, "2020-01-02", ["OLD"])
        stale_output = root / "stale_ledger"
        blocked = run(
            _args(stale_candidates, stale_summary, cache, stale_output, "2026-07-10"),
            now_utc="2026-07-10T03:00:00Z",
        )
        assert blocked["status"] == "blocked_no_observations"
        assert "source_observation_not_contemporaneous_with_ledger_receipt" in blocked["capture_audit"]["blockers"]
        assert read_events(stale_output / EVENT_LOG_NAME) == []

        current_candidates, current_summary = _write_overlay(root, "2026-01-02", ["CUR"])
        current_output = root / "current_ledger"
        first = run(
            _args(current_candidates, current_summary, cache, current_output, "2026-01-02"),
            now_utc="2026-01-02T21:00:00Z",
        )
        assert first["coverage"]["observation_count"] == 1
        revised = pd.read_csv(current_candidates)
        revised.loc[0, "free_data_selection_score"] = 0.123
        revised.to_csv(current_candidates, index=False)
        prefix = (current_output / EVENT_LOG_NAME).read_bytes()
        rejected_revision = run(
            _args(current_candidates, current_summary, cache, current_output, "2026-07-10"),
            now_utc="2026-07-10T03:00:00Z",
        )
        assert "source_observation_not_contemporaneous_with_ledger_receipt" in rejected_revision["capture_audit"]["blockers"]
        assert rejected_revision["capture_audit"]["blocked_observation_rows"] == 1
        assert rejected_revision["coverage"]["observation_count"] == 1
        assert (current_output / EVENT_LOG_NAME).read_bytes() == prefix


def test_novel_older_decision_is_not_backfilled() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache_prices"
        output = root / "ledger"
        newer_candidates, newer_summary = _write_overlay(root, "2026-03-10", ["NEW"])
        first = run(
            _args(newer_candidates, newer_summary, cache, output, "2026-03-10"),
            now_utc="2026-03-10T23:00:00Z",
        )
        assert first["coverage"]["observation_count"] == 1
        prefix = (output / EVENT_LOG_NAME).read_bytes()

        older_candidates, older_summary = _write_overlay(root, "2026-03-09", ["OLD"])
        blocked = run(
            _args(older_candidates, older_summary, cache, output, "2026-03-10"),
            now_utc="2026-03-10T23:30:00Z",
        )
        blockers = blocked["capture_audit"]["blockers"]
        assert "pre_observation_signal_backfill_blocked_by_monotonic_decision_date" in blockers
        assert blocked["capture_audit"]["blocked_observation_rows"] == 1
        assert blocked["coverage"]["observation_count"] == 1
        assert (output / EVENT_LOG_NAME).read_bytes() == prefix
        status = pd.read_csv(output / "current_status.csv")
        assert status["ticker"].tolist() == ["NEW"]
        assert status["pre_observation_signal_backfill_allowed"].tolist() == [False]


if __name__ == "__main__":
    tests = [fn for name, fn in sorted(globals().items()) if name.startswith("test_") and callable(fn)]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"free_data_forward_paper_ledger_smoke: {len(tests)}/{len(tests)} PASS")
