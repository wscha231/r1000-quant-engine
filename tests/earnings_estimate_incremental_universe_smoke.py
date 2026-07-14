#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.build_forward_estimate_incremental_universe import build_incremental_universe  # noqa: E402
from tools.collect_earnings_estimates_finnhub import acknowledge_collection_attempts  # noqa: E402


def run_queue(
    root: Path,
    *,
    coverage_file: Path,
    include_file: Path | None = None,
    latest_run: Path | None = None,
    max_new_tickers: int = 1,
    max_missing_tickers: int = 1,
    max_covered_tickers: int = 1,
    max_retry_tickers: int = 1,
) -> dict:
    return build_incremental_universe(
        shard_dir=str(root / "unused_shards"),
        snapshot_dir=str(root / "data_pit" / "events" / "earnings_estimates"),
        coverage_file=str(coverage_file),
        latest_run=str(latest_run or (root / "missing_latest_run")),
        canonical_universe=str(root / "data_pit" / "events" / "earnings_estimates" / "collection_universe.csv"),
        checkpoint=str(root / "data_pit" / "events" / "earnings_estimates" / "collection_checkpoint.json"),
        output=str(root / "outputs" / "earnings_estimates_daily" / "incremental_universe.csv"),
        queue_output=str(root / "outputs" / "earnings_estimates_daily" / "collection_queue.csv"),
        summary=str(root / "outputs" / "earnings_estimates_daily" / "incremental_universe_summary.json"),
        report=str(root / "outputs" / "earnings_estimates_daily" / "collection_queue_report.md"),
        include_file=str(include_file) if include_file else "",
        expected_universe_count=6,
        as_of_date="2026-07-10",
        stale_after_days=7,
        max_new_tickers=max_new_tickers,
        max_missing_tickers=max_missing_tickers,
        max_covered_tickers=max_covered_tickers,
        max_retry_tickers=max_retry_tickers,
    )


def test_queue_reuses_fresh_success_and_resumes_from_checkpoint() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        snapshot_dir = root / "data_pit" / "events" / "earnings_estimates"
        snapshot_dir.mkdir(parents=True)
        coverage = root / "coverage.csv"
        pd.DataFrame({"ticker": ["AAA", "BBB", "CCC", "DDD", "EEE", "__CASH__"]}).to_csv(coverage, index=False)
        retry_hint = root / "retry_hint.csv"
        pd.DataFrame({"ticker": ["EEE"]}).to_csv(retry_hint, index=False)
        pd.DataFrame(
            [
                {"ticker": "AAA", "available_from": "2026-07-09", "has_forward_estimate": 1},
                {"ticker": "BBB", "available_from": "2026-06-20", "has_forward_estimate": 1},
                {"ticker": "CCC", "available_from": "2026-07-09", "has_forward_estimate": 0},
                {"ticker": "EEE", "available_from": "2026-07-09", "has_forward_estimate": 0},
            ]
        ).to_parquet(snapshot_dir / "estimates_20260709.parquet", index=False)

        first = run_queue(root, coverage_file=coverage, include_file=retry_hint)

        output = root / "outputs" / "earnings_estimates_daily" / "incremental_universe.csv"
        queue = pd.read_csv(root / "outputs" / "earnings_estimates_daily" / "collection_queue.csv")
        assert pd.read_csv(output)["ticker"].tolist() == ["BBB", "DDD", "EEE"]
        assert first["current_universe_ticker_count"] == 6
        assert first["eligible_universe_ticker_count"] == 5
        assert first["non_equity_placeholder_ticker_count"] == 1
        assert first["fresh_success_reused_ticker_count"] == 1
        assert first["universe_source_mode"] == "coverage_file_seed"
        assert first["universe_source"]["sha256"]
        assert first["canonical_universe"]["sha256"]
        assert first["snapshot_source_aggregate_sha256"]
        assert queue.loc[queue["ticker"] == "AAA", "queue_action"].item() == "reuse"
        assert queue.loc[queue["ticker"] == "CCC", "queue_action"].item() == "wait"
        assert queue.loc[queue["ticker"] == "EEE", "selection_reason"].item() == "slow_rotating_uncovered_retry"
        assert queue.loc[queue["ticker"] == "__CASH__", "queue_state"].item() == "non_equity_placeholder"
        assert "__CASH__" not in pd.read_csv(output)["ticker"].tolist()

        ack = acknowledge_collection_attempts(
            snapshot_dir / "collection_checkpoint.json",
            root / "outputs" / "earnings_estimates_daily" / "collection_queue.csv",
            ["EEE"],
            attempted_at_utc="2026-07-10T12:00:00Z",
        )
        assert ack["acknowledged_ticker_count"] == 1

        second = run_queue(root, coverage_file=root / "coverage_not_restored.csv")

        assert second["universe_source_mode"] == "checkpointed_canonical_reuse"
        assert second["checkpoint_input_valid"] is True
        assert pd.read_csv(output)["ticker"].tolist() == ["BBB", "CCC", "DDD"]
        checkpoint = json.loads(
            (snapshot_dir / "collection_checkpoint.json").read_text(encoding="utf-8")
        )
        states = {row["ticker"]: row for row in checkpoint["ticker_states"]}
        assert states["EEE"]["selection_count"] == 1
        assert states["CCC"]["selection_count"] == 0
        assert states["BBB"]["selection_count"] == 0
        assert checkpoint["selection_checkpoint_policy"] == (
            "advance_only_after_collector_attempt_acknowledgement"
        )
        assert checkpoint["research_only"] is True
        assert checkpoint["forward_only"] is True
        assert checkpoint["historical_backfill_allowed"] is False


def test_queue_detects_new_universe_and_fails_closed_without_exact_source() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        snapshot_dir = root / "data_pit" / "events" / "earnings_estimates"
        snapshot_dir.mkdir(parents=True)
        original = root / "coverage_original.csv"
        pd.DataFrame({"ticker": ["AAA", "BBB", "CCC", "DDD", "EEE", "__CASH__"]}).to_csv(original, index=False)
        run_queue(root, coverage_file=original)

        changed = root / "coverage_changed.csv"
        pd.DataFrame({"ticker": ["AAA", "BBB", "CCC", "DDD", "FFF", "__CASH__"]}).to_csv(changed, index=False)
        payload = run_queue(root, coverage_file=changed)
        queue = pd.read_csv(root / "outputs" / "earnings_estimates_daily" / "collection_queue.csv")
        fff = queue.loc[queue["ticker"] == "FFF"].iloc[0]
        assert fff["queue_state"] == "new_universe"
        assert bool(fff["selected"]) is True
        assert payload["new_universe_ticker_count"] == 1
        assert payload["retired_universe_ticker_count"] == 1

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        incomplete = root / "coverage_incomplete.csv"
        pd.DataFrame({"ticker": ["AAA", "BBB", "CCC", "DDD", "__CASH__"]}).to_csv(incomplete, index=False)
        blocked = run_queue(root, coverage_file=incomplete)
        assert blocked["status"] == "blocked_incomplete_universe"
        assert blocked["output_ticker_count"] == 0
        assert pd.read_csv(root / "outputs" / "earnings_estimates_daily" / "incremental_universe.csv").empty
        assert not (root / "data_pit" / "events" / "earnings_estimates" / "collection_checkpoint.json").exists()


def test_queue_can_seed_from_exact_tracked_latest_run_union() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        latest = root / "cloud_results" / "full_rebuild" / "latest_global_alpha_universe"
        (latest / "reports").mkdir(parents=True)
        pd.DataFrame({"ticker": ["AAA", "BBB", "CCC"]}).to_csv(latest / "scored_latest.csv", index=False)
        pd.DataFrame({"ticker": ["DDD", "EEE"]}).to_csv(latest / "reports" / "candidate_replay_book.csv", index=False)
        pd.DataFrame({"ticker": ["CASH"]}).to_csv(latest / "reports" / "concentrated_strategy_holdings.csv", index=False)
        pd.DataFrame({"ticker": []}).to_csv(latest / "reports" / "main_monthly_weights.csv", index=False)
        missing_coverage = root / "missing_coverage.csv"

        payload = run_queue(root, coverage_file=missing_coverage, latest_run=latest)

        assert payload["status"] == "ready_for_forward_archive_incremental"
        assert payload["universe_source_mode"] == "latest_run_seed"
        assert payload["current_universe_ticker_count"] == 6
        assert payload["eligible_universe_ticker_count"] == 5
        assert payload["non_equity_placeholder_tickers"] == ["CASH"]
        assert payload["universe_source"]["source_kind"] == "latest_run_exact_universe_union"
        assert len(payload["universe_source"]["source_files"]) == 4


def test_queue_rejects_wrong_placeholder_contract_for_seed_and_checkpoint() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        no_placeholder = root / "coverage_no_placeholder.csv"
        pd.DataFrame({"ticker": ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF"]}).to_csv(
            no_placeholder, index=False
        )
        blocked = run_queue(root, coverage_file=no_placeholder)
        assert blocked["status"] == "blocked_incomplete_universe"

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        two_placeholders = root / "coverage_two_placeholders.csv"
        pd.DataFrame({"ticker": ["AAA", "BBB", "CCC", "DDD", "CASH", "__CASH__"]}).to_csv(
            two_placeholders, index=False
        )
        blocked = run_queue(root, coverage_file=two_placeholders)
        assert blocked["status"] == "blocked_incomplete_universe"

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        valid = root / "coverage_valid.csv"
        pd.DataFrame({"ticker": ["AAA", "BBB", "CCC", "DDD", "EEE", "CASH"]}).to_csv(valid, index=False)
        run_queue(root, coverage_file=valid)

        snapshot_dir = root / "data_pit" / "events" / "earnings_estimates"
        canonical = snapshot_dir / "collection_universe.csv"
        checkpoint_path = snapshot_dir / "collection_checkpoint.json"
        pd.DataFrame({"ticker": ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF"]}).to_csv(
            canonical, index=False
        )
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        checkpoint["universe"]["canonical_snapshot"]["sha256"] = hashlib.sha256(canonical.read_bytes()).hexdigest()
        checkpoint_path.write_text(json.dumps(checkpoint), encoding="utf-8")

        blocked = run_queue(root, coverage_file=root / "coverage_not_restored.csv")
        assert blocked["status"] == "blocked_incomplete_universe"
        assert blocked["eligible_universe_ticker_count"] == 0


def test_zero_limits_disable_lanes_and_negative_limits_are_rejected() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        coverage = root / "coverage.csv"
        pd.DataFrame({"ticker": ["AAA", "BBB", "CCC", "DDD", "EEE", "CASH"]}).to_csv(coverage, index=False)
        payload = run_queue(
            root,
            coverage_file=coverage,
            max_new_tickers=0,
            max_missing_tickers=0,
            max_covered_tickers=0,
            max_retry_tickers=0,
        )
        assert payload["status"] == "complete_no_collection_due"
        assert payload["output_ticker_count"] == 0

        try:
            run_queue(root, coverage_file=coverage, max_missing_tickers=-1)
        except ValueError as exc:
            assert "max_missing_tickers" in str(exc)
        else:
            raise AssertionError("negative selection limit was not rejected")


def test_success_becomes_stale_when_threshold_days_have_elapsed() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        snapshot_dir = root / "data_pit" / "events" / "earnings_estimates"
        snapshot_dir.mkdir(parents=True)
        coverage = root / "coverage.csv"
        pd.DataFrame({"ticker": ["AAA", "BBB", "CCC", "DDD", "EEE", "CASH"]}).to_csv(coverage, index=False)
        pd.DataFrame(
            [{"ticker": "AAA", "available_from": "2026-07-03", "has_forward_estimate": 1}]
        ).to_parquet(snapshot_dir / "estimates_20260703.parquet", index=False)

        payload = run_queue(
            root,
            coverage_file=coverage,
            max_new_tickers=0,
            max_missing_tickers=0,
            max_covered_tickers=1,
            max_retry_tickers=0,
        )
        assert payload["selected_tickers"] == ["AAA"]
        assert payload["selection_reason_counts"] == {"stale_success_refresh": 1}


if __name__ == "__main__":
    test_queue_reuses_fresh_success_and_resumes_from_checkpoint()
    test_queue_detects_new_universe_and_fails_closed_without_exact_source()
    test_queue_can_seed_from_exact_tracked_latest_run_union()
    test_queue_rejects_wrong_placeholder_contract_for_seed_and_checkpoint()
    test_zero_limits_disable_lanes_and_negative_limits_are_rejected()
    test_success_becomes_stale_when_threshold_days_have_elapsed()
    print("earnings_estimate_incremental_universe_smoke: PASS")
