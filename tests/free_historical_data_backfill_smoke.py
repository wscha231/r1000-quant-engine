#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.collect_alphavantage_listing_status import read_csv_payload  # noqa: E402
from tools.collect_fmp_earnings_calendar_history import normalize_rows  # noqa: E402
from tools.audit_free_historical_data_coverage import audit, parse_args  # noqa: E402


def test_av_listing_status_parser_labels_lifecycle_proxy() -> None:
    payload = (
        "symbol,name,exchange,assetType,ipoDate,delistingDate,status\n"
        "ABC,ABC Corp,NASDAQ,Stock,2019-01-02,,Active\n"
        "XYZ,XYZ Inc,NYSE,Stock,2017-03-01,2024-05-10,Delisted\n"
    ).encode("utf-8")
    frame = read_csv_payload(payload, source_state="delisted", collected_at="2026-07-10T00:00:00Z")
    assert len(frame) == 2
    assert set(frame["source_state"]) == {"delisted"}
    assert set(frame["source"]) == {"alphavantage_listing_status"}
    assert "delisting_date" in frame.columns


def test_fmp_earnings_calendar_parser_blocks_historical_pit_feature_use() -> None:
    frame = normalize_rows(
        [
            {
                "symbol": "AAPL",
                "date": "2024-01-25",
                "epsEstimated": 2.10,
                "eps": 2.18,
                "revenueEstimated": 118000000000,
                "revenue": 119500000000,
                "time": "amc",
            }
        ],
        collected_at="2026-07-10T00:00:00Z",
    )
    assert len(frame) == 1
    row = frame.iloc[0].to_dict()
    assert row["ticker"] == "AAPL"
    assert row["pit_backtest_allowed"] is False
    assert row["pit_usage_label"] == "vendor_historical_snapshot_not_revision_history"


def test_free_data_workflow_exposes_historical_backfill_switches() -> None:
    text = (ROOT / ".github" / "workflows" / "free_data_lake_bootstrap.yml").read_text(encoding="utf-8")
    for token in [
        "listing_status",
        "fmp_earnings_calendar",
        "ALPHAVANTAGE_API_KEY",
        "FMP_API_KEY",
        "--listing-status",
        "--fmp-earnings-calendar",
        "data_pit/events",
        "data/catalog.json",
        "audit_free_historical_data_coverage.py",
    ]:
        assert token in text


def test_dedicated_historical_backfill_workflow_is_collector_only() -> None:
    text = (ROOT / ".github" / "workflows" / "free_historical_data_backfill.yml").read_text(encoding="utf-8")
    for token in [
        "collect_alphavantage_listing_status.py",
        "collect_fmp_earnings_calendar_history.py",
        "audit_free_historical_data_coverage.py",
        "data_pit/events",
        "data_raw/free",
        "data/catalog.json",
    ]:
        assert token in text
    assert "run_broker_ledger_replay.py" not in text
    assert "full_rebuild_manual.yml" not in text


def test_data_catalog_tracks_new_free_history_feeds() -> None:
    text = (ROOT / "tools" / "build_data_catalog.py").read_text(encoding="utf-8")
    for token in [
        "av_listing_status",
        "fmp_earnings_calendar_history",
        "forward_earnings_estimate_snapshots",
        "forward_earnings_revision_signals",
    ]:
        assert token in text


def test_free_historical_data_coverage_blocks_without_universe() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        args = parse_args()
        args.universe_file = ""
        args.latest_run = str(tmp_path / "missing_latest")
        args.companyfacts_zip = str(tmp_path / "missing_companyfacts.zip")
        args.listing_status = str(tmp_path / "missing_listing.parquet")
        args.earnings_calendar = str(tmp_path / "missing_calendar.parquet")
        args.estimate_snapshot_dir = str(tmp_path / "missing_estimates")
        args.output_dir = str(tmp_path / "coverage")
        summary = audit(args)
        assert summary["status"] == "blocked_no_universe"
        assert (tmp_path / "coverage" / "summary.json").exists()


def main() -> None:
    test_av_listing_status_parser_labels_lifecycle_proxy()
    test_fmp_earnings_calendar_parser_blocks_historical_pit_feature_use()
    test_free_data_workflow_exposes_historical_backfill_switches()
    test_dedicated_historical_backfill_workflow_is_collector_only()
    test_data_catalog_tracks_new_free_history_feeds()
    test_free_historical_data_coverage_blocks_without_universe()
    print(json.dumps({"status": "PASS", "tests": 6}, sort_keys=True))


if __name__ == "__main__":
    main()
