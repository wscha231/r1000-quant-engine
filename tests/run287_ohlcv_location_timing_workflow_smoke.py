#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "daily_operating_selection_refresh.yml"


def main() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    producer = text.index("python tools/run_run287_exact_packet_producer.py")
    timing = text.index(
        "python tools/build_run287_ohlcv_location_timing_challenger.py"
    )
    memory = text.index("python tools/archive_run287_ohlcv_pattern_memory.py")
    targets = text.index("python tools/build_run287_same_close_target_books.py")
    ledger = text.index("python tools/run_daily_simulated_fill_ledger.py", targets)
    assert producer < targets < ledger < timing < memory
    timing_block = text[timing : timing + 1800]
    assert "--producer-status outputs/run287_exact_packet_producer/status.json" in timing_block
    assert "--holding-watch outputs/holding_risk_watch/holding_risk_watch.csv" in timing_block
    assert (
        "--pattern-memory-dir outputs/run287_decision_observation_archive/ohlcv_pattern_memory"
        in timing_block
    )
    assert '--valuation-date "$PAPER_AS_OF"' in timing_block
    assert (
        '--observation-accepted-at-utc "$OBSERVATION_ACCEPTED_AT_UTC"'
        in timing_block
    )
    assert "OBSERVATION_ACCEPTED_AT_UTC=\"$(date -u" in text
    assert "PAPER_ASOF" not in timing_block
    assert "if python tools/build_run287_ohlcv_location_timing_challenger.py" in text
    assert (
        "after the same-close transaction boundary"
        in timing_block
    )
    assert "outputs/run287_ohlcv_location_timing_exact_close_*/" in text
    assert (
        "outputs/full_rebuild_logs/daily_run287_ohlcv_location_timing_challenger.log"
        in text
    )
    memory_block = text[memory : memory + 1200]
    assert '--timing-summary "$OHLCV_TIMING_DIR/summary.json"' in memory_block
    assert '--valuation-date "$PAPER_AS_OF"' in memory_block
    assert (
        "--output-dir outputs/run287_decision_observation_archive/ohlcv_pattern_memory"
        in memory_block
    )
    assert "daily_run287_ohlcv_pattern_memory.log" in memory_block
    assert "targets/ledger were not mutated" in memory_block
    assert (
        "missing exact session keeps all later pattern statistics/proposals suppressed"
        in memory_block
    )
    assert "--record-failed-session-reason timing_builder_blocked" in memory_block
    target_block = text[targets:ledger]
    assert "ohlcv_location_timing" not in target_block
    assert "timing_challenger" not in target_block
    assert "ohlcv_pattern_memory" not in target_block
    print("run287 ohlcv location timing workflow smoke: PASS")


if __name__ == "__main__":
    main()
