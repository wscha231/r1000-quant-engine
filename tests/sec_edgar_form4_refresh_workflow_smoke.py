#!/usr/bin/env python3
"""Smoke checks for SEC EDGAR Form 4 refresh workflow."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "sec_edgar_form4_refresh.yml"


def test_sec_edgar_form4_refresh_syncs_drive_data_lake_paths() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "SEC EDGAR Form 4 Refresh" in text
    assert "tools/run_sec_submissions_collector.py" in text
    assert "tools/run_sec_form4_parser.py" in text
    assert "tools/run_sec_ownership_signals.py" in text
    assert "lookback_years" in text
    assert "include_archive_files" in text
    assert "all_sec_tickers" in text
    assert "--append-existing" in text
    assert "--skip-existing-accessions" in text
    assert "--include-archive-files" in text
    assert "--shard-index" in text
    assert "andrewcha231@gmail.com" in text
    assert "data_raw/sec" in text
    assert "data_pit/sec" in text
    assert "manifests/sec_edgar" in text
    assert "sec_ownership_signals.parquet" in text
    assert "research_runs/sec_edgar_form4/${GITHUB_RUN_ID}" in text


def main() -> int:
    test_sec_edgar_form4_refresh_syncs_drive_data_lake_paths()
    print("sec_edgar_form4_refresh_workflow_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
