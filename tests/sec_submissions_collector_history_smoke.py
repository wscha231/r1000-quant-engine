#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.run_sec_submissions_collector as collector  # noqa: E402


def test_sec_submissions_collector_includes_older_archive_files() -> None:
    recent_payload = {
        "filings": {
            "recent": {
                "form": ["13F-HR"],
                "accessionNumber": ["0001777813-26-000001"],
                "primaryDocument": ["primary_doc.xml"],
                "acceptanceDateTime": ["2026-05-15T20:00:00.000Z"],
                "filingDate": ["2026-05-15"],
                "reportDate": ["2026-03-31"],
            },
            "files": [
                {"name": "CIK0001777813-submissions-001.json", "filingCount": 2},
            ],
        }
    }
    archive_payload = {
        "filings": {
            "recent": {
                "form": ["13F-HR", "4"],
                "accessionNumber": ["0001777813-19-000001", "0001777813-17-000001"],
                "primaryDocument": ["primary_doc.xml", "xslForm4.xml"],
                "acceptanceDateTime": ["2019-02-14T20:00:00.000Z", "2017-02-14T20:00:00.000Z"],
                "filingDate": ["2019-02-14", "2017-02-14"],
                "reportDate": ["2018-12-31", "2017-02-13"],
            }
        }
    }

    def fake_load_company_tickers(raw_dir: Path, **_: object) -> pd.DataFrame:
        return pd.DataFrame(columns=["ticker", "cik10", "name"])

    def fake_fetch_submissions(cik: str, raw_dir: Path, **_: object) -> dict:
        assert cik == "0001777813"
        return recent_payload

    def fake_fetch_archive(file_name: str, raw_dir: Path, **_: object) -> dict:
        assert file_name == "CIK0001777813-submissions-001.json"
        return archive_payload

    original_load = collector.load_company_tickers
    original_fetch = collector.fetch_submissions
    original_archive = collector.fetch_submission_archive
    try:
        collector.load_company_tickers = fake_load_company_tickers  # type: ignore[assignment]
        collector.fetch_submissions = fake_fetch_submissions  # type: ignore[assignment]
        collector.fetch_submission_archive = fake_fetch_archive  # type: ignore[assignment]
        with tempfile.TemporaryDirectory() as tmp:
            rows = collector.collect_filings_index(
                tickers=[],
                cik_rows=collector.cik_rows_from_inputs("ATREIDES:0001777813"),
                raw_dir=Path(tmp),
                forms=["13F-HR"],
                include_older_submissions=True,
                history_start="2018-01-01",
                safety_delay_hours=0.0,
            )
    finally:
        collector.load_company_tickers = original_load  # type: ignore[assignment]
        collector.fetch_submissions = original_fetch  # type: ignore[assignment]
        collector.fetch_submission_archive = original_archive  # type: ignore[assignment]

    assert len(rows) == 2, rows
    assert set(rows["accession_number"]) == {"0001777813-26-000001", "0001777813-19-000001"}
    assert rows["source"].astype(str).str.contains("archive").any()
    assert rows["period_of_report"].min() == "2018-12-31"


def test_recent_refresh_does_not_redownload_historical_archives() -> None:
    recent_refresh_values: list[bool] = []
    archive_refresh_values: list[bool] = []

    def fake_load_company_tickers(raw_dir: Path, **_: object) -> pd.DataFrame:
        return pd.DataFrame(columns=["ticker", "cik10", "name"])

    def fake_fetch_submissions(cik: str, raw_dir: Path, **kwargs: object) -> dict:
        recent_refresh_values.append(bool(kwargs.get("refresh")))
        return {
            "filings": {
                "recent": {
                    "form": ["13F-HR"],
                    "accessionNumber": ["0001777813-26-000002"],
                    "primaryDocument": ["primary_doc.xml"],
                    "acceptanceDateTime": ["2026-08-14T20:00:00.000Z"],
                    "filingDate": ["2026-08-14"],
                    "reportDate": ["2026-06-30"],
                },
                "files": [{"name": "CIK0001777813-submissions-001.json"}],
            }
        }

    def fake_fetch_archive(file_name: str, raw_dir: Path, **kwargs: object) -> dict:
        archive_refresh_values.append(bool(kwargs.get("refresh")))
        return {"filings": {"recent": {}}}

    original_load = collector.load_company_tickers
    original_fetch = collector.fetch_submissions
    original_archive = collector.fetch_submission_archive
    try:
        collector.load_company_tickers = fake_load_company_tickers  # type: ignore[assignment]
        collector.fetch_submissions = fake_fetch_submissions  # type: ignore[assignment]
        collector.fetch_submission_archive = fake_fetch_archive  # type: ignore[assignment]
        with tempfile.TemporaryDirectory() as tmp:
            rows = collector.collect_filings_index(
                tickers=[],
                cik_rows=collector.cik_rows_from_inputs("ATREIDES:0001777813"),
                raw_dir=Path(tmp),
                forms=["13F-HR"],
                refresh_recent_submissions=True,
                include_older_submissions=True,
                history_start="2018-01-01",
            )
    finally:
        collector.load_company_tickers = original_load  # type: ignore[assignment]
        collector.fetch_submissions = original_fetch  # type: ignore[assignment]
        collector.fetch_submission_archive = original_archive  # type: ignore[assignment]

    assert rows["period_of_report"].tolist() == ["2026-06-30"]
    assert recent_refresh_values == [True]
    assert archive_refresh_values == [False]


def test_recent_refresh_failure_does_not_emit_error_only_manager_history() -> None:
    def fake_load_company_tickers(raw_dir: Path, **_: object) -> pd.DataFrame:
        return pd.DataFrame(columns=["ticker", "cik10", "name"])

    def failing_fetch_submissions(cik: str, raw_dir: Path, **kwargs: object) -> dict:
        raise OSError("temporary SEC failure")

    original_load = collector.load_company_tickers
    original_fetch = collector.fetch_submissions
    try:
        collector.load_company_tickers = fake_load_company_tickers  # type: ignore[assignment]
        collector.fetch_submissions = failing_fetch_submissions  # type: ignore[assignment]
        with tempfile.TemporaryDirectory() as tmp:
            try:
                collector.collect_filings_index(
                    tickers=[],
                    cik_rows=collector.cik_rows_from_inputs("ATREIDES:0001777813"),
                    raw_dir=Path(tmp),
                    forms=["13F-HR"],
                    refresh_recent_submissions=True,
                    include_older_submissions=True,
                )
            except RuntimeError as exc:
                assert "refusing to replace the durable index" in str(exc)
            else:
                raise AssertionError("strict current-submissions refresh must fail closed")
    finally:
        collector.load_company_tickers = original_load  # type: ignore[assignment]
        collector.fetch_submissions = original_fetch  # type: ignore[assignment]


if __name__ == "__main__":
    test_sec_submissions_collector_includes_older_archive_files()
    test_recent_refresh_does_not_redownload_historical_archives()
    test_recent_refresh_failure_does_not_emit_error_only_manager_history()
    print("sec_submissions_collector_history_smoke: PASS")
