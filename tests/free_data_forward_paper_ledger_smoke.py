#!/usr/bin/env python3
"""Focused synthetic-price smoke tests for the forward paper ledger."""
from __future__ import annotations

import argparse
import hashlib
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
    build_review_readiness,
    load_nyse_sessions,
    read_events,
    run,
)
from tools.run_weekly_evaluation import px_cache_name  # noqa: E402
import tools.run_free_data_forward_paper_ledger as ledger  # noqa: E402


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
                "free_data_base_selection_rank": rank,
                "free_data_selection_score": 0.9 - rank * 0.01,
                "free_data_base_rank_score": 0.8,
                "free_data_forward_estimate_score": 0.7,
                "free_data_recent_actual_score": 0.2,
                "free_data_evidence_coverage_count": 2,
                "estimate_revision_confirmed": 1,
                "has_forward_estimate": 1,
                "free_data_forward_estimate_evidence_present": True,
                "free_data_selection_label": "research_only_latest_overlay",
                "production_promotion_allowed": False,
                "historical_backtest_acceptance_allowed": False,
            }
        )
    candidates = overlay / "selected_candidates.csv"
    pd.DataFrame(rows).to_csv(candidates, index=False)
    selected_sha256 = hashlib.sha256(candidates.read_bytes()).hexdigest()
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
                "selected_candidates_sha256": selected_sha256,
            }
        ),
        encoding="utf-8",
    )
    return candidates, summary


def _args(candidates: Path, summary: Path, cache: Path, output: Path, as_of: str) -> argparse.Namespace:
    return argparse.Namespace(
        candidates=str(candidates),
        ranked_universe="",
        overlay_summary=str(summary),
        price_cache=str(cache),
        output_dir=str(output),
        benchmark="SPY",
        as_of_date=as_of,
        # Unit tests that exercise event progression use deliberately tiny
        # fixtures.  The CLI has no corresponding bypass and fails closed.
        _test_allow_incomplete_cohorts=True,
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
        assert "overlay_selected_candidates_sha256_mismatch" in rejected_revision["capture_audit"]["blockers"]
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


def test_same_decision_ticker_snapshot_change_is_immutable_conflict() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache_prices"
        output = root / "ledger"
        candidates, summary_path = _write_overlay(root, "2026-03-10", ["IMM"])
        first = run(
            _args(candidates, summary_path, cache, output, "2026-03-10"),
            now_utc="2026-03-10T21:00:00Z",
        )
        assert first["coverage"]["observation_count"] == 1
        prefix = (output / EVENT_LOG_NAME).read_bytes()
        revised = pd.read_csv(candidates)
        revised.loc[0, "free_data_selection_score"] = 0.123
        revised.to_csv(candidates, index=False)
        summary_payload = json.loads(summary_path.read_text(encoding="utf-8"))
        summary_payload["selected_candidates_sha256"] = hashlib.sha256(candidates.read_bytes()).hexdigest()
        summary_path.write_text(json.dumps(summary_payload), encoding="utf-8")
        second = run(
            _args(candidates, summary_path, cache, output, "2026-03-10"),
            now_utc="2026-03-10T21:30:00Z",
        )
        assert any(
            blocker.startswith("immutable_decision_ticker_snapshot_conflict:")
            for blocker in second["capture_audit"]["blockers"]
        )
        assert second["coverage"]["observation_count"] == 1
        assert (output / EVENT_LOG_NAME).read_bytes() == prefix


def test_existing_writer_lock_fails_closed() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache_prices"
        output = root / "ledger"
        candidates, summary_path = _write_overlay(root, "2026-03-10", ["LOCK"])
        output.mkdir(parents=True)
        (output / ".forward_paper_ledger.lock").write_text("fixture\n", encoding="utf-8")
        try:
            run(
                _args(candidates, summary_path, cache, output, "2026-03-10"),
                now_utc="2026-03-10T21:00:00Z",
            )
        except RuntimeError as exc:
            assert "already locked" in str(exc)
        else:
            raise AssertionError("concurrent ledger writer was not blocked")


def test_reference_close_is_strictly_after_late_source_observation() -> None:
    schedule = ledger.load_nyse_schedule(pd.Timestamp("2026-01-05"), pd.Timestamp("2026-01-08"))
    assert schedule is not None
    sessions = pd.DatetimeIndex(schedule.index)
    prices = pd.DataFrame(
        {"close": [100.0 + index for index in range(len(sessions))]},
        index=sessions,
    )
    observation = {
        "observation_id": "late-source",
        "decision_date": "2026-01-05",
        "source_observed_at_utc": "2026-01-06T22:00:00Z",
        "ticker": "AAA",
        "benchmark_ticker": "SPY",
    }
    reference, status = ledger._reference_candidate(
        observation,
        prices,
        "adjusted_close",
        prices,
        "adjusted_close",
        sessions,
        schedule["market_close"],
        as_of_date=pd.Timestamp("2026-01-08"),
        recorded_at_utc="2026-01-08T23:00:00Z",
    )
    assert status == "reference_observed"
    assert reference is not None
    assert reference["next_close_date"] == "2026-01-07"


def test_v2_persisted_cohort_membership_is_not_recomputed_from_snapshot() -> None:
    observation = {
        "schema_version": ledger.SCHEMA_VERSION,
        "event_type": "signal_observed",
        "event_id": "event",
        "observation_id": "obs",
        "decision_date": "2026-01-05",
        "ticker": "AAA",
        "signal_snapshot": {
            "free_data_selection_rank": 1,
            "prior_free_data_selection_rank": 1,
            "has_forward_estimate": 1,
            "free_data_forward_estimate_evidence_present": True,
            "estimate_revision_confirmed": True,
        },
        "base_top30_member": False,
        "overlay_top30_member": False,
        "matched_control_member": True,
        "true_forward_signal": False,
        "forward_arm_member": False,
        "forward_signal_state": "neutral_missing_or_unconfirmed",
        "cohort_memberships": ["matched_control_ranks31_60"],
    }
    status = ledger.build_current_status([observation], {})
    assert bool(status.iloc[0]["matched_control_member"])
    assert not bool(status.iloc[0]["overlay_top30_member"])
    assert not bool(status.iloc[0]["true_forward_signal"])


def test_full_ranked_universe_captures_fixed_cohort_union_and_missing_is_neutral() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache_prices"
        output = root / "ledger"
        candidates, summary_path = _write_overlay(root, "2026-04-01", [f"T{i:02d}" for i in range(1, 31)])
        ranked_rows = []
        for rank in range(1, 66):
            prior_rank = 61 if rank == 1 else (1 if rank == 61 else rank)
            ranked_rows.append(
                {
                    "ticker": f"T{rank:02d}",
                    "free_data_selection_rank": rank,
                    "free_data_base_selection_rank": prior_rank,
                    "prior_free_data_selection_rank": prior_rank,
                    "free_data_selection_score": 1.0 - rank / 100.0,
                    "free_data_selection_label": "research_only_latest_overlay",
                    "has_forward_estimate": 1 if rank == 1 else 0,
                    "free_data_forward_estimate_evidence_present": rank == 1,
                    "estimate_revision_confirmed": 1 if rank == 1 else 0,
                    "production_promotion_allowed": False,
                    "historical_backtest_acceptance_allowed": False,
                }
            )
        pd.DataFrame(ranked_rows[:30]).to_csv(candidates, index=False)
        initial_summary = json.loads(summary_path.read_text(encoding="utf-8"))
        initial_summary["selected_candidates_sha256"] = hashlib.sha256(candidates.read_bytes()).hexdigest()
        summary_path.write_text(json.dumps(initial_summary), encoding="utf-8")
        initial = run(
            _args(candidates, summary_path, cache, output, "2026-04-01"),
            now_utc="2026-04-01T21:00:00Z",
        )
        assert initial["event_counts"] == {"signal_observed": 30}
        initial_prefix = (output / EVENT_LOG_NAME).read_bytes()
        initial_status = pd.read_csv(output / "current_status.csv")
        assert initial_status["reference_status"].astype(str).str.startswith("pending_").all()
        assert initial_status["outcome_21d_status"].eq("pending_reference").all()

        pd.DataFrame(ranked_rows).to_csv(candidates.parent / "ranked_universe.csv", index=False)
        overlay_summary = json.loads(summary_path.read_text(encoding="utf-8"))
        overlay_summary["ranked_universe_sha256"] = hashlib.sha256(
            (candidates.parent / "ranked_universe.csv").read_bytes()
        ).hexdigest()
        summary_path.write_text(json.dumps(overlay_summary), encoding="utf-8")
        summary = run(
            _args(candidates, summary_path, cache, output, "2026-04-01"),
            now_utc="2026-04-01T21:30:00Z",
        )
        assert summary["event_counts"] == {"signal_observed": 61}
        assert summary["appended_event_counts"] == {"signal_observed": 31}
        assert (output / EVENT_LOG_NAME).read_bytes().startswith(initial_prefix)
        capture = summary["capture_audit"]["cohort_capture"]
        assert capture["source_mode"] == "full_ranked_universe"
        assert capture["cohort_counts"] == {
            "base_top30": 30,
            "overlay_top30": 30,
            "matched_control_ranks31_60": 30,
            "true_forward_signal": 1,
            "forward_arm": 1,
        }
        status = pd.read_csv(output / "current_status.csv")
        assert len(status) == 61
        assert status["base_top30_member"].sum() == 30
        assert status["overlay_top30_member"].sum() == 30
        assert status["matched_control_member"].sum() == 30
        assert status["forward_arm_member"].sum() == 1
        assert status.loc[status["ticker"].eq("T01"), "forward_signal_state"].iloc[0] == "true_forward"
        assert status.loc[status["ticker"].eq("T02"), "forward_signal_state"].iloc[0] == "neutral_missing_or_unconfirmed"
        assert status.loc[status["ticker"].eq("T61"), "base_top30_member"].iloc[0]
        schema = json.loads((output / "schema.json").read_text(encoding="utf-8"))
        assert schema["cohort_contract"]["observation_universe"].startswith("union of base_top30")
        assert schema["cohort_contract"]["missing_forward_evidence_policy"] == "neutral_missing_or_unconfirmed"
        assert "next distinct decision date" in schema["cohort_contract"]["migration_policy"]


def test_explicit_ranked_universe_with_custom_filename_uses_ranked_hash() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache_prices"
        output = root / "ledger"
        candidates, summary_path = _write_overlay(root, "2026-04-01", ["AAA"])
        ranked = candidates.parent / "snapshot_20260710.csv"
        pd.read_csv(candidates).to_csv(ranked, index=False)
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        summary["ranked_universe_sha256"] = hashlib.sha256(ranked.read_bytes()).hexdigest()
        summary_path.write_text(json.dumps(summary), encoding="utf-8")
        args = _args(candidates, summary_path, cache, output, "2026-04-01")
        args.ranked_universe = str(ranked)
        result = run(args, now_utc="2026-04-01T21:00:00Z")
        assert result["capture_audit"]["blockers"] == []
        assert result["capture_audit"]["cohort_capture"]["source_mode"] == "full_ranked_universe"


def test_review_readiness_requires_and_reports_all_predeclared_paper_gates() -> None:
    rows = []
    decision_dates = pd.date_range("2025-01-06", periods=12, freq="7D")
    for index in range(200):
        row = {
            "observation_id": f"F{index}",
            "decision_date": str(decision_dates[index % len(decision_dates)].date()),
            "ticker": f"FWD{index % 50:02d}",
            "true_forward_signal": True,
            "forward_arm_member": True,
            "base_top30_member": index % 2 == 0,
            "overlay_top30_member": True,
            "matched_control_member": False,
        }
        for horizon in (21, 63, 126):
            row[f"outcome_{horizon}d_status"] = "completed"
            row[f"outcome_{horizon}d_excess_total_return"] = 0.03
            row[f"outcome_{horizon}d_ticker_max_drawdown"] = -0.05
        rows.append(row)
    for index in range(200):
        row = {
            "observation_id": f"C{index}",
            "decision_date": str(decision_dates[index % len(decision_dates)].date()),
            "ticker": f"CTL{index:03d}",
            "true_forward_signal": False,
            "forward_arm_member": False,
            "base_top30_member": False,
            "overlay_top30_member": False,
            "matched_control_member": True,
        }
        for horizon in (21, 63, 126):
            row[f"outcome_{horizon}d_status"] = "completed"
            row[f"outcome_{horizon}d_excess_total_return"] = 0.01
            row[f"outcome_{horizon}d_ticker_max_drawdown"] = -0.04
        rows.append(row)

    readiness = build_review_readiness(pd.DataFrame(rows))
    assert readiness["status"] == "REVIEW_READY_PAPER_ONLY"
    assert readiness["review_ready"] is True
    assert readiness["distinct_true_forward_ticker_count"] == 50
    assert readiness["resolved_outcome_count"] == 200
    assert readiness["resolved_horizon_row_count_diagnostic"] == 600
    assert readiness["cohort_metrics"]["true_forward_arm"]["21d"]["decision_week_block_count"] == 12
    assert readiness["cohort_metrics"]["true_forward_arm"]["63d"]["decision_week_block_count"] == 12
    assert readiness["evidence_checks"]["week_block_bootstrap_lower_nonnegative_21d"]["passed"] is True
    assert abs(readiness["drawdown_degradation_vs_matched_control"]["21d"] - 0.01) < 1e-12
    assert readiness["evidence_checks"]["mean_spy_excess_direction_positive_126d"]["passed"] is True
    assert readiness["valid_for_historical_backtest_acceptance"] is False


def test_new_capture_fails_closed_without_complete_ranked_cohorts() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        candidates, summary_path = _write_overlay(root, "2026-04-01", ["AAA"])
        args = _args(candidates, summary_path, root / "cache", root / "ledger", "2026-04-01")
        args._test_allow_incomplete_cohorts = False
        result = run(args, now_utc="2026-04-01T21:00:00Z")
        assert result["status"] == "blocked_no_observations"
        assert result["coverage"]["observation_count"] == 0
        assert "full_ranked_universe_required_for_new_decision" in result["capture_audit"]["blockers"]
        assert any(
            item.startswith("incomplete_fixed_cohort:")
            for item in result["capture_audit"]["blockers"]
        )


def test_new_capture_rejects_prior_rank_as_contemporaneous_base_rank() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        candidates, summary_path = _write_overlay(root, "2026-04-01", [f"T{i:02d}" for i in range(1, 31)])
        ranked = candidates.parent / "ranked_universe.csv"
        rows = []
        for rank in range(1, 61):
            rows.append(
                {
                    "ticker": f"T{rank:02d}",
                    "free_data_selection_rank": rank,
                    "prior_free_data_selection_rank": rank,
                    "free_data_selection_score": 1.0 - rank / 100.0,
                    "free_data_selection_label": "research_only_latest_overlay",
                    "has_forward_estimate": 0,
                    "production_promotion_allowed": False,
                    "historical_backtest_acceptance_allowed": False,
                }
            )
        pd.DataFrame(rows).to_csv(ranked, index=False)
        overlay_summary = json.loads(summary_path.read_text(encoding="utf-8"))
        overlay_summary["ranked_universe_sha256"] = hashlib.sha256(ranked.read_bytes()).hexdigest()
        summary_path.write_text(json.dumps(overlay_summary), encoding="utf-8")
        args = _args(candidates, summary_path, root / "cache", root / "ledger", "2026-04-01")
        args._test_allow_incomplete_cohorts = False
        result = run(args, now_utc="2026-04-01T21:00:00Z")
        assert result["coverage"]["observation_count"] == 0
        assert "contemporaneous_base_selection_rank_required" in result["capture_audit"]["blockers"]


def test_resolved_gate_counts_unique_primary_63d_observations_not_horizon_cells() -> None:
    rows = []
    dates = pd.date_range("2025-01-06", periods=12, freq="7D")
    for index in range(67):
        row = {
            "decision_date": str(dates[index % len(dates)].date()),
            "ticker": f"F{index % 50:02d}",
            "true_forward_signal": True,
            "forward_arm_member": True,
            "matched_control_member": False,
        }
        for horizon in (21, 63, 126):
            row[f"outcome_{horizon}d_status"] = "completed"
            row[f"outcome_{horizon}d_excess_total_return"] = 0.03
            row[f"outcome_{horizon}d_ticker_max_drawdown"] = -0.05
        rows.append(row)
    result = build_review_readiness(pd.DataFrame(rows))
    assert result["resolved_outcome_count"] == 67
    assert result["resolved_horizon_row_count_diagnostic"] == 201
    assert result["status"] == "UNDERPOWERED"


def test_matched_control_and_paired_week_coverage_are_required() -> None:
    rows = []
    dates = pd.date_range("2025-01-06", periods=12, freq="7D")
    for index in range(200):
        row = {
            "decision_date": str(dates[index % len(dates)].date()),
            "ticker": f"F{index % 50:02d}",
            "true_forward_signal": True,
            "forward_arm_member": True,
            "matched_control_member": False,
        }
        for horizon in (21, 63, 126):
            row[f"outcome_{horizon}d_status"] = "completed"
            row[f"outcome_{horizon}d_excess_total_return"] = 0.03
            row[f"outcome_{horizon}d_ticker_max_drawdown"] = -0.05
        rows.append(row)
    control = {
        "decision_date": str(dates[0].date()),
        "ticker": "ONLY_CONTROL",
        "true_forward_signal": False,
        "forward_arm_member": False,
        "matched_control_member": True,
    }
    for horizon in (21, 63, 126):
        control[f"outcome_{horizon}d_status"] = "completed"
        control[f"outcome_{horizon}d_excess_total_return"] = 0.01
        control[f"outcome_{horizon}d_ticker_max_drawdown"] = -0.04
    rows.append(control)
    result = build_review_readiness(pd.DataFrame(rows))
    assert result["status"] == "UNDERPOWERED"
    assert result["sample_checks"]["matched_control_decision_week_blocks_21d"]["passed"] is False
    assert result["sample_checks"]["paired_drawdown_decision_week_blocks_63d"]["passed"] is False


def test_backfill_workflow_restores_runs_and_durably_syncs_forward_ledger() -> None:
    workflow = (ROOT / ".github" / "workflows" / "free_historical_data_backfill.yml").read_text(
        encoding="utf-8"
    )
    assert "python tools/run_free_data_forward_paper_ledger.py" in workflow
    assert "--ranked-universe outputs/free_data_selection_overlay/ranked_universe.csv" in workflow
    assert "outputs/free_data_forward_paper_ledger/" in workflow
    assert "research_state/${SAFE_BRANCH}/free_data_forward_paper_ledger" in workflow


if __name__ == "__main__":
    tests = [fn for name, fn in sorted(globals().items()) if name.startswith("test_") and callable(fn)]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"free_data_forward_paper_ledger_smoke: {len(tests)}/{len(tests)} PASS")
