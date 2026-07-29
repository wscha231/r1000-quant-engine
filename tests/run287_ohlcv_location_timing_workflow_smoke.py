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
    targets = text.index("python tools/build_run287_same_close_target_books.py")
    ledger = text.index("python tools/run_daily_simulated_fill_ledger.py", targets)
    assert producer < targets < ledger < timing
    timing_block = text[timing : timing + 1800]
    assert "--producer-status outputs/run287_exact_packet_producer/status.json" in timing_block
    assert "--holding-watch outputs/holding_risk_watch/holding_risk_watch.csv" in timing_block
    assert '--valuation-date "$PAPER_ASOF"' in timing_block
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
    target_block = text[targets:ledger]
    assert "ohlcv_location_timing" not in target_block
    assert "timing_challenger" not in target_block
    print("run287 ohlcv location timing workflow smoke: PASS")


if __name__ == "__main__":
    main()
