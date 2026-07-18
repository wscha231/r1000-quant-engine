#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "earnings_estimates_daily.yml"


def test_workflow_rotates_broad_universe_shards_and_persists_metadata() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "Resolve ticker set and universe shard" in text
    assert "outputs/forward_estimate_universe_plan_20260709/shards" in text
    assert "EVENT_NAME" in text
    assert '"${EVENT_NAME}" = "schedule"' in text
    assert "DAY_INDEX" in text
    assert "SHARD_INDEX" in text
    assert "catchup_all_universe_shards" in text
    assert "incremental_universe_addons" in text
    assert "collection_universe_file" in text
    assert "collection_checkpoint.json" in text
    assert "collection_universe.csv" in text
    assert "collection_queue.csv" in text
    assert "collection_queue_report.md" in text
    assert "--expected-universe-count 993" in text
    assert "--latest-run cloud_results/full_rebuild/latest_global_alpha_universe" in text
    assert "--max-missing-tickers" in text
    assert "--max-retry-tickers" in text
    assert "RESOLVED_COLLECTION_REQUIRED" in text
    assert "if: env.RESOLVED_COLLECTION_REQUIRED == 'true'" in text
    assert "group: earnings-estimates-daily-durable-archive" in text
    assert "group: earnings-estimates-daily-${{ github.ref }}" not in text
    assert "id: build_manifest" in text
    assert text.count("if: ${{ always() && steps.build_manifest.outcome == 'success' }}") == 2
    assert "max_new_universe_tickers" in text
    assert "max_known_covered_tickers" in text
    assert "collector_max_errors" in text
    assert 'MAX_ERRORS="5000"' in text
    assert 'MAX_ERRORS="100"' in text
    assert "build_forward_estimate_catchup_universe.py" in text
    assert "build_forward_estimate_incremental_universe.py" in text
    assert "all_shards_catchup" in text
    assert "incremental_addons" in text
    assert "RESOLVED_TICKERS" in text
    assert "RESOLVED_UNIVERSE_FILE" in text
    assert "RESOLVED_SHARD_ID" in text
    assert "RESOLVED_SHARD_FILE" in text
    assert "RESOLVED_SHARD_MODE" in text
    assert "RESOLVED_MAX_ERRORS" in text
    assert "--tickers \"${RESOLVED_TICKERS}\"" in text
    assert "--universe-file \"${RESOLVED_UNIVERSE_FILE}\"" in text
    assert "--shard-id \"${RESOLVED_SHARD_ID:-}\"" in text
    assert "--shard-file \"${RESOLVED_SHARD_FILE:-}\"" in text
    assert "--shard-mode \"${RESOLVED_SHARD_MODE:-}\"" in text
    assert "--max-errors \"${RESOLVED_MAX_ERRORS:-100}\"" in text
    assert "--queue-checkpoint data_pit/events/earnings_estimates/collection_checkpoint.json" in text
    assert "--collection-checkpoint data_pit/events/earnings_estimates/collection_checkpoint.json" in text
    assert "--collection-queue outputs/earnings_estimates_daily/collection_queue.csv" in text
    assert "AAPL,MSFT,NVDA,AMD" in text
    assert "schedule" in text
    assert "full_rebuild_manual" not in text


def test_workflow_appends_bounded_forward_paper_archive_after_completed_session() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    for token in (
        "Resolve completed NYSE session for forward paper archive",
        "tools/run_daily_market_session_gate.py",
        "--min-close-age-minutes 90",
        "--max-close-age-hours 36",
        "if: steps.forward_market.outputs.ready == 'yes'",
        'LATEST="cloud_results/full_rebuild/latest_global_alpha_universe"',
        "tools/run_free_data_selection_overlay.py",
        '--decision-date "$LAST_NYSE_SESSION_DATE"',
        "outputs/free_data_selection_overlay_previous/ranked_universe.csv",
        "outputs/free_data_selection_overlay/ranked_universe.csv",
        "tools/build_forward_paper_price_universe.py",
        "tools/build_replay_price_cache.py",
        "--start 2026-07-01",
        "--refresh-stale-days 1",
        "tools/run_free_data_forward_paper_ledger.py",
        "tools/audit_run287_forward_estimate_evidence_gate.py",
        "outputs/run287_forward_estimate_evidence_gate",
        "--ranked-universe outputs/free_data_selection_overlay/ranked_universe.csv",
        "--price-cache cache_prices_forward_paper",
        '--as-of-date "$LAST_NYSE_SESSION_DATE"',
        "research_state/free_data_forward_paper_ledger",
        "research_state/free_data_selection_overlay",
        "research_state/free_data_forward_paper_price_cache",
    ):
        assert token in text, token
    assert "fmp_calendar" not in text.lower()
    assert "fullrun" not in text.lower()
    assert "live_trading" not in text.lower()
    assert "production" not in text.lower()


def test_workflow_checkout_is_bounded_to_daily_inputs() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "sparse-checkout: |" in text
    assert "sparse-checkout-cone-mode: true" in text
    sparse_block = text.split("sparse-checkout: |", 1)[1].split(
        "sparse-checkout-cone-mode:", 1
    )[0]
    for path in (
        ".github",
        "cloud_results/full_rebuild/latest_global_alpha_universe",
        "data_static",
        "outputs/forward_estimate_universe_plan_20260709",
        "tools",
    ):
        assert path in sparse_block, path
    assert "cloud_results/full_rebuild/202" not in sparse_block


if __name__ == "__main__":
    test_workflow_rotates_broad_universe_shards_and_persists_metadata()
    test_workflow_appends_bounded_forward_paper_archive_after_completed_session()
    test_workflow_checkout_is_bounded_to_daily_inputs()
    print("earnings_estimate_workflow_rotation_smoke: PASS")
