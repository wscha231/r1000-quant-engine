#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "daily_operating_selection_refresh.yml"


def main() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    pending = text.index(
        "--record-failed-session-reason current_session_pending"
    )
    first_ledger = text.index("python tools/run_daily_simulated_fill_ledger.py")
    catchup_timing = text.index(
        "python tools/build_run287_ohlcv_location_timing_challenger.py",
        first_ledger,
    )
    static_cache = text.index(
        "- name: Restore Run287 research-static archive cache"
    )
    static_restore = text.index(
        "- name: Restore verified Run287 research-static archive"
    )
    producer = text.index(
        "python tools/run_run287_exact_packet_producer.py",
        catchup_timing,
    )
    targets = text.index("python tools/build_run287_same_close_target_books.py")
    ledger = text.index("python tools/run_daily_simulated_fill_ledger.py", targets)
    timing = text.index(
        "python tools/build_run287_ohlcv_location_timing_challenger.py",
        ledger,
    )
    memory = text.index(
        "python tools/archive_run287_ohlcv_pattern_memory.py",
        timing,
    )
    assert (
        static_cache
        < static_restore
        < pending
        < first_ledger
        < catchup_timing
        < producer
        < targets
        < ledger
        < timing
        < memory
    )
    catchup_block = text[catchup_timing:producer]
    static_restore_block = text[static_restore:first_ledger]
    assert (
        "if: steps.market.outputs.ready == 'yes'\n"
        "        id: run287-research-static-cache"
        in text[static_cache : static_cache + 300]
    )
    assert (
        "if: steps.market.outputs.ready == 'yes'\n"
        "        id: run287-research-static"
        in text[static_restore : static_restore + 300]
    )
    assert (
        "chronological catch-up requires the hash-pinned frozen "
        "price histories" in static_restore_block
    )
    assert (
        "pre-launch paper catch-up skips pattern/static evidence"
        in static_restore_block
    )
    assert '--destination-root run287_research_static' in static_restore_block
    prelaunch_guard = text.index(
        'if [[ "$PAPER_AS_OF" < "$PATTERN_FORWARD_LAUNCH_SESSION" ]]'
    )
    assert prelaunch_guard < pending < first_ledger
    assert (
        'if [ "$PATTERN_SESSION_ELIGIBLE" != yes ]; then'
        in text[first_ledger:catchup_timing]
    )
    assert (
        "pre-launch paper mark accepted without pattern observation"
        in text[first_ledger:catchup_timing]
    )
    assert "CATCHUP_ARTIFACT_ROOT" in text[first_ledger:catchup_timing]
    assert "PATTERN_CATCHUP_SOURCE" in text[first_ledger:catchup_timing]
    assert (
        'CATCHUP_SOURCE_LAYOUT="$(' in text[first_ledger:catchup_timing]
    )
    assert (
        'if [ "$CATCHUP_SOURCE_LAYOUT" = '
        '"MULTI_SESSION_READ_ONLY_CAPTURE" ]; then'
        in text[first_ledger:catchup_timing]
    )
    assert (
        "--record-failed-session-reason "
        "price_only_capture_pattern_evidence_unavailable"
        in text[first_ledger:catchup_timing]
    )
    assert (
        "OHLCV pattern memory remains BLOCKED and proposal-ineligible"
        in text[first_ledger:catchup_timing]
    )
    assert (
        'elif [ "$CATCHUP_SOURCE_LAYOUT" = '
        '"LEGACY_SINGLE_SESSION_DAILY_ARTIFACT" ]; then'
        in text[first_ledger:catchup_timing]
    )
    assert (
        text[first_ledger:catchup_timing].index(
            '"MULTI_SESSION_READ_ONLY_CAPTURE"'
        )
        < text[first_ledger:catchup_timing].index(
            "PATTERN_CATCHUP_SOURCE"
        )
    )
    assert (
        '--observation-accepted-at-utc "$PATTERN_CATCHUP_ACCEPTED_AT_UTC"'
        in catchup_block
    )
    assert "--historical-catchup-artifact-root" in catchup_block
    assert "--historical-catchup-artifact-metadata" in catchup_block
    assert "--historical-catchup-price-evidence" in catchup_block
    assert (
        "--record-failed-session-reason pattern_catchup_timing_blocked"
        in catchup_block
    )
    assert (
        '--timing-summary "$PATTERN_CATCHUP_TIMING_DIR/summary.json"'
        in catchup_block
    )
    assert (
        "chronological pattern-memory catch-up accepted from pinned "
        "exact-session artifact" in catchup_block
    )
    assert (
        'PAPER_CATCHUP_MODE:-no}" = "yes"'
        in text
    )
    assert (
        "ohlcv_pattern_memory/accepted_head.json" in text
    )
    assert (
        text.index(
            "from tools import archive_run287_ohlcv_pattern_memory as memory"
        )
        < targets
    )
    assert "PATTERN_RECOVERY_DESCRIPTOR" in text[pending:targets]
    assert "REQUIRED_PATTERN_RETRY_SESSION" in text[pending:targets]
    assert "PATTERN_RECOVERY_SUMMARY" in text[pending:targets]
    assert (
        "select_recovery_evidence_summary"
        in text[pending:targets]
    )
    assert (
        "required_observation_payload_sha256s"
        in text[pending:targets]
    )
    assert "--preserve-blocked-publication" in text[pending:targets]
    assert '--pending-session-date "$PAPER_AS_OF"' in text[pending:targets]
    assert (
        "while preserving the current BLOCKED public marker"
        in text[pending:targets]
    )
    assert (
        "validated and staged unaccepted OHLCV pattern session"
        in text[pending:targets]
    )
    post_ledger = text[ledger:timing]
    assert 'if [ -n "$PATTERN_RECOVERY_SESSION" ]; then' in post_ledger
    assert (
        '--valuation-date "$PATTERN_RECOVERY_SESSION"' in post_ledger
    )
    assert (
        "--commit-head-preserve-blocked-publication" in post_ledger
    )
    assert '--pending-session-date "$PAPER_AS_OF"' in post_ledger
    assert (
        "published recovered OHLCV pattern session "
        "${PATTERN_RECOVERY_SESSION} after the same-close transaction "
        "boundary and before current-session pattern construction"
        in post_ledger
    )
    assert (
        'if [ "$PATTERN_RECOVERY_READY" != yes ]; then' in post_ledger
    )
    assert "memory.exact_target_session(sys.argv[1], 1)" in post_ledger
    assert "PATTERN_CURRENT_SESSION_CHRONOLOGICAL=no" in post_ledger
    assert (
        "intervening OHLCV pattern sessions require explicit "
        "chronological catch-up" in post_ledger
    )
    assert (
        'elif [ "$PATTERN_RECOVERY_SESSION" = "$PAPER_AS_OF" ]; then'
        in post_ledger
    )
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
    assert (
        "elif python tools/build_run287_ohlcv_location_timing_challenger.py"
        in text
    )
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
    assert (
        "--record-failed-session-reason exact_packet_producer_blocked"
        in text
    )
    target_block = text[targets:ledger]
    assert "ohlcv_location_timing" not in target_block
    assert "timing_challenger" not in target_block
    assert "ohlcv_pattern_memory" not in target_block
    print("run287 ohlcv location timing workflow smoke: PASS")


if __name__ == "__main__":
    main()
