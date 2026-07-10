#!/usr/bin/env python3
from __future__ import annotations

import json
import hashlib
import os
import sys
import tempfile
import zipfile
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.collect_alphavantage_listing_status import read_csv_payload  # noqa: E402
from tools import collect_fmp_earnings_calendar_history as fmp_collector  # noqa: E402
from tools import collect_sec_company_tickers as sec_collector  # noqa: E402
from tools.collect_fmp_earnings_calendar_history import normalize_rows  # noqa: E402
from tools.collect_sec_company_tickers import parse_company_tickers  # noqa: E402
from tools.audit_free_historical_data_coverage import audit, parse_args  # noqa: E402
from tools.build_data_catalog import inspect_dataset  # noqa: E402


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
        "collect_sec_company_tickers.py",
        "sec_company_tickers.parquet",
        "company_tickers_manifest.json",
        "collect_alphavantage_listing_status.py",
        "collect_fmp_earnings_calendar_history.py",
        "audit_free_historical_data_coverage.py",
        "data_pit/events",
        "data_raw/free",
        "data/catalog.json",
        "run_free_data_selection_overlay.py",
        "outputs/free_data_selection_overlay",
    ]:
        assert token in text
    assert "run_broker_ledger_replay.py" not in text
    assert "full_rebuild_manual.yml" not in text


def test_data_catalog_tracks_new_free_history_feeds() -> None:
    text = (ROOT / "tools" / "build_data_catalog.py").read_text(encoding="utf-8")
    for token in [
        "sec_company_tickers_reference",
        "av_listing_status",
        "fmp_earnings_calendar_history",
        "forward_earnings_estimate_snapshots",
        "forward_estimate_collection_universe",
        "forward_estimate_collection_checkpoint",
        "forward_earnings_revision_signals",
    ]:
        assert token in text


def test_data_catalog_snapshot_freshness_ignores_queue_metadata() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        snapshot_dir = Path(tmp) / "earnings_estimates"
        snapshot_dir.mkdir()
        snapshot = snapshot_dir / "estimates_20260601.parquet"
        snapshot.write_bytes(b"old-snapshot")
        stale_timestamp = pd.Timestamp.now(tz="UTC").timestamp() - 10 * 86400
        os.utime(snapshot, (stale_timestamp, stale_timestamp))
        (snapshot_dir / "collection_checkpoint.json").write_text("{}\n", encoding="utf-8")
        (snapshot_dir / "collection_universe.csv").write_text("ticker\nAAA\n", encoding="utf-8")

        item = inspect_dataset(
            {
                "name": "test_forward_snapshots",
                "path": str(snapshot_dir),
                "kind": "dir",
                "file_glob": "estimates_*.parquet",
                "layer": "forward_estimates",
                "owner_workflow": "earnings_estimates_daily.yml",
                "cadence_days": 4,
            }
        )
        assert item["file_count"] == 1
        assert item["bytes"] == len(b"old-snapshot")
        assert item["freshness"] == "STALE"


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


def test_sec_company_tickers_parser_preserves_provenance() -> None:
    payload = json.dumps(
        {
            "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
            "1": {"cik_str": "0000012345", "ticker": "BRK.B", "title": "Example"},
        }
    ).encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()
    frame = parse_company_tickers(
        payload,
        source_url="https://www.sec.gov/files/company_tickers.json",
        source_sha256=digest,
        available_from="2026-07-10T00:00:00Z",
        ingested_at_utc="2026-07-10T00:01:00Z",
    )
    assert frame.set_index("ticker").loc["AAPL", "cik10"] == "0000320193"
    assert frame.set_index("ticker").loc["BRK-B", "cik10"] == "0000012345"
    assert set(frame["source_sha256"]) == {digest}
    assert set(frame["available_from"]) == {"2026-07-10T00:00:00Z"}
    assert set(frame["ingested_at_utc"]) == {"2026-07-10T00:01:00Z"}


def test_sec_refresh_preserves_prior_artifacts_when_download_is_invalid() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        raw = tmp_path / "company_tickers.json"
        manifest = tmp_path / "company_tickers_manifest.json"
        reference = tmp_path / "sec_company_tickers.parquet"
        summary_path = tmp_path / "summary.json"
        originals = {
            raw: b'{"old":"raw"}\n',
            manifest: b'{"old":"manifest"}\n',
            reference: b"old-reference-bytes",
            summary_path: b'{"old":"summary"}\n',
        }
        for path, payload in originals.items():
            path.write_bytes(payload)

        class EmptyResponse:
            content = b"{}"
            headers = {"Date": "Fri, 10 Jul 2026 03:00:00 GMT"}

            @staticmethod
            def raise_for_status() -> None:
                return None

        args = sec_collector.parse_args()
        args.raw_output = str(raw)
        args.manifest_output = str(manifest)
        args.reference_output = str(reference)
        args.summary = str(summary_path)
        args.refresh = True
        args.user_agent = "test-suite test@example.com"
        original_get = sec_collector.requests.get
        sec_collector.requests.get = lambda *_args, **_kwargs: EmptyResponse()
        try:
            try:
                sec_collector.collect(args)
                raise AssertionError("invalid SEC response should fail before replacement")
            except ValueError as exc:
                assert "no valid ticker/CIK rows" in str(exc)
        finally:
            sec_collector.requests.get = original_get

        for path, payload in originals.items():
            assert path.read_bytes() == payload
        assert not list(tmp_path.glob(".*.tmp"))


def test_coverage_repairs_blank_ciks_without_overwrite_or_placeholder_collision() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        universe_path = tmp_path / "universe.csv"
        pd.DataFrame(
            [
                {"ticker": "AAA", "cik10": "0000000001"},
                {"ticker": "BBB", "cik10": ""},
                {"ticker": "D.UP", "cik10": ""},
                {"ticker": "CASH", "cik10": ""},
                {"ticker": "KEEP", "cik10": "0000000007"},
                {"ticker": "MISS", "cik10": ""},
                {"ticker": "NOZIP", "cik10": ""},
                {"ticker": "BRK.B", "cik10": ""},
            ]
        ).to_csv(universe_path, index=False)

        raw = json.dumps(
            {
                "0": {"cik_str": 1, "ticker": "AAA", "title": "AAA"},
                "1": {"cik_str": 2, "ticker": "BBB", "title": "BBB"},
                "2": {"cik_str": 3, "ticker": "D.UP", "title": "Duplicate A"},
                "3": {"cik_str": 4, "ticker": "D-UP", "title": "Duplicate B"},
                "4": {"cik_str": 9, "ticker": "CASH", "title": "Real issuer collision"},
                "5": {"cik_str": 8, "ticker": "KEEP", "title": "Current conflict"},
                "6": {"cik_str": 5, "ticker": "NOZIP", "title": "No facts"},
                "7": {"cik_str": 6, "ticker": "BRK-B", "title": "Punctuation"},
            }
        ).encode("utf-8")
        digest = hashlib.sha256(raw).hexdigest()
        reference = parse_company_tickers(
            raw,
            source_url="https://www.sec.gov/files/company_tickers.json",
            source_sha256=digest,
            available_from="2026-07-10T00:00:00Z",
            ingested_at_utc="2026-07-10T00:01:00Z",
        )
        reference_path = tmp_path / "sec_company_tickers.csv"
        reference.to_csv(reference_path, index=False)

        companyfacts = tmp_path / "companyfacts.zip"
        with zipfile.ZipFile(companyfacts, "w") as zf:
            for cik in [1, 2, 6, 7]:
                zf.writestr(f"CIK{cik:010d}.json", "{}")

        args = parse_args()
        args.universe_file = str(universe_path)
        args.latest_run = str(tmp_path / "missing_latest")
        args.companyfacts_zip = str(companyfacts)
        args.sec_ticker_map = str(reference_path)
        args.listing_status = str(tmp_path / "missing_listing.parquet")
        args.earnings_calendar = str(tmp_path / "missing_calendar.parquet")
        args.estimate_snapshot_dir = str(tmp_path / "missing_estimates")
        args.output_dir = str(tmp_path / "coverage")
        summary = audit(args)
        result = pd.read_csv(tmp_path / "coverage" / "universe_coverage.csv", dtype=str).fillna("").set_index("ticker")

        assert summary["coverage"]["sec_companyfacts_before_cik_mapping"]["covered_ticker_count"] == 2
        assert summary["coverage"]["sec_companyfacts"]["covered_ticker_count"] == 4
        assert summary["sec_cik_mapping"]["filled_from_reference_count"] == 3
        assert summary["sec_cik_mapping"]["existing_cik_conflict_count"] == 1
        assert summary["sec_cik_mapping"]["existing_cik_conflict_tickers"] == ["KEEP"]
        assert summary["sec_cik_mapping"]["unresolved_equity_ticker_count"] == 2
        assert summary["sec_ticker_reference"]["source_sha256"] == digest
        assert result.loc["KEEP", "cik10"] == "0000000007"
        assert result.loc["KEEP", "cik_mapping_status"] == "existing_cik_conflict_sec_reference_preserved"
        assert result.loc["CASH", "cik10"] == ""
        assert result.loc["CASH", "cik_mapping_status"] == "non_equity_placeholder"
        assert result.loc["D-UP", "cik_mapping_status"] == "ambiguous_sec_ticker_reference"
        assert result.loc["BRK-B", "cik10"] == "0000000006"
        assert result.loc["NOZIP", "sec_companyfacts_missing_reason"] == "cik_not_in_companyfacts_zip"
        assert (tmp_path / "coverage" / "sec_cik_mapping_report.md").exists()
        assert (tmp_path / "coverage" / "sec_cik_mapping_unresolved.csv").exists()


def test_fmp_entitlement_block_stops_after_one_chunk() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        args = fmp_collector.parse_args()
        args.start = "2016-01-01"
        args.end = "2016-04-30"
        args.chunk_days = 31
        args.max_chunks = 0
        args.max_errors = 20
        args.sleep_seconds = 0.0
        args.raw_dir = str(tmp_path / "raw")
        args.output = str(tmp_path / "calendar.parquet")
        args.summary = str(tmp_path / "summary.json")

        original_key = os.environ.get("FMP_API_KEY")
        original_fetch = fmp_collector.fetch_chunk

        def blocked_fetch(*_args, **_kwargs):
            response = requests.Response()
            response.status_code = 402
            response.url = fmp_collector.FMP_BASE
            raise requests.HTTPError("402 Payment Required", response=response)

        os.environ["FMP_API_KEY"] = "test-only-placeholder"
        fmp_collector.fetch_chunk = blocked_fetch
        try:
            summary = fmp_collector.collect(args)
        finally:
            fmp_collector.fetch_chunk = original_fetch
            if original_key is None:
                os.environ.pop("FMP_API_KEY", None)
            else:
                os.environ["FMP_API_KEY"] = original_key

        assert summary["status"] == "blocked"
        assert summary["chunks_attempted"] == 1
        assert summary["chunks_unattempted"] > 0
        assert summary["terminal_block"]["http_status"] == 402
        assert summary["terminal_block"]["do_not_retry_same_endpoint_without_access_change"] is True


def main() -> None:
    test_av_listing_status_parser_labels_lifecycle_proxy()
    test_fmp_earnings_calendar_parser_blocks_historical_pit_feature_use()
    test_free_data_workflow_exposes_historical_backfill_switches()
    test_dedicated_historical_backfill_workflow_is_collector_only()
    test_data_catalog_tracks_new_free_history_feeds()
    test_data_catalog_snapshot_freshness_ignores_queue_metadata()
    test_free_historical_data_coverage_blocks_without_universe()
    test_sec_company_tickers_parser_preserves_provenance()
    test_sec_refresh_preserves_prior_artifacts_when_download_is_invalid()
    test_coverage_repairs_blank_ciks_without_overwrite_or_placeholder_collision()
    test_fmp_entitlement_block_stops_after_one_chunk()
    print(json.dumps({"status": "PASS", "tests": 11}, sort_keys=True))


if __name__ == "__main__":
    main()
