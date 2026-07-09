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
    assert "collector_max_errors" in text
    assert 'MAX_ERRORS="5000"' in text
    assert 'MAX_ERRORS="100"' in text
    assert "build_forward_estimate_catchup_universe.py" in text
    assert "all_shards_catchup" in text
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
    assert "AAPL,MSFT,NVDA,AMD" in text
    assert "schedule" in text
    assert "full_rebuild_manual" not in text


if __name__ == "__main__":
    test_workflow_rotates_broad_universe_shards_and_persists_metadata()
    print("earnings_estimate_workflow_rotation_smoke: PASS")
