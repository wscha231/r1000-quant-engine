#!/usr/bin/env python3
"""Smoke checks for SEC CIK normalization schema stability."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from r1000_helpers import normalize_cik10, normalize_cik_series  # noqa: E402
import tools.run_sec_submissions_collector as submissions  # noqa: E402
from tools.run_sec_submissions_collector import cik_rows_from_inputs  # noqa: E402


def assert_cik10(value: object, expected: str) -> None:
    actual = normalize_cik10(value)
    assert actual == expected
    assert isinstance(actual, str)
    assert len(actual) == 10
    assert actual.isdigit()


def test_normalize_cik10_preserves_ten_digit_strings() -> None:
    cases = [
        ("0000320193", "0000320193"),
        ("320193", "0000320193"),
        (320193, "0000320193"),
        (320193.0, "0000320193"),
        ("CIK 0000789019", "0000789019"),
        ("  0000051143  ", "0000051143"),
        ("0000000001", "0000000001"),
    ]
    for value, expected in cases:
        assert_cik10(value, expected)

    assert normalize_cik10(None) is None
    assert normalize_cik10(pd.NA) is None
    assert normalize_cik10("") is None
    assert normalize_cik10("not-a-cik") is None
    assert normalize_cik10("0000000000") is None


def test_normalize_cik_series_returns_object_ten_digit_strings() -> None:
    index = pd.Index(["AAPL", "MSFT", "MISSING", "BRK"], name="ticker")
    series = normalize_cik_series(["0000320193", 789019, pd.NA, "0001067983"], index=index)

    assert list(series.index) == list(index)
    assert str(series.dtype) == "object"
    assert series.to_dict() == {
        "AAPL": "0000320193",
        "MSFT": "0000789019",
        "MISSING": None,
        "BRK": "0001067983",
    }
    assert all(isinstance(cik, str) for cik in series.dropna())
    assert all(len(cik) == 10 and cik.isdigit() for cik in series.dropna())


def test_cik_rows_from_inputs_supports_13f_manager_ciks() -> None:
    rows = cik_rows_from_inputs("BRK:1067983,0001649339")
    assert rows.to_dict("records") == [
        {"ticker": "BRK", "cik10": "0001067983", "name": "BRK"},
        {"ticker": "CIK0001649339", "cik10": "0001649339", "name": ""},
    ]
    assert str(rows["cik10"].dtype) == "object"


def test_collect_filings_index_keeps_running_after_bad_manager_cik() -> None:
    original_load = submissions.load_company_tickers
    original_fetch = submissions.fetch_submissions
    try:
        submissions.load_company_tickers = lambda *args, **kwargs: pd.DataFrame(columns=["ticker", "cik10", "name"])

        def fake_fetch(cik: str, *args: object, **kwargs: object) -> dict[str, object]:
            if cik == "0000000001":
                raise RuntimeError("404 test")
            return {
                "filings": {
                    "recent": {
                        "form": ["13F-HR"],
                        "accessionNumber": ["0000000002-26-000001"],
                        "primaryDocument": ["info.xml"],
                        "acceptanceDateTime": ["2026-05-15T18:00:00.000Z"],
                        "filingDate": ["2026-05-15"],
                        "reportDate": ["2026-03-31"],
                    }
                }
            }

        submissions.fetch_submissions = fake_fetch
        rows = submissions.cik_rows_from_inputs("BAD:1,GOOD:2")
        frame = submissions.collect_filings_index(
            tickers=[],
            cik_rows=rows,
            raw_dir=ROOT,
            forms=["13F-HR"],
        )
        assert len(frame) == 2
        statuses = dict(zip(frame["ticker"], frame["download_status"]))
        assert statuses["BAD"] == "fetch_error"
        assert statuses["GOOD"] == "indexed"
        assert frame.loc[frame["ticker"].eq("BAD"), "parse_status"].iloc[0].startswith("fetch_error:")
    finally:
        submissions.load_company_tickers = original_load
        submissions.fetch_submissions = original_fetch


def test_collect_filings_index_supports_stable_issuer_shards() -> None:
    original_load = submissions.load_company_tickers
    original_fetch = submissions.fetch_submissions
    try:
        submissions.load_company_tickers = lambda *args, **kwargs: pd.DataFrame(
            [
                {"ticker": "DDD", "cik10": "0000000004", "name": "D"},
                {"ticker": "AAA", "cik10": "0000000001", "name": "A"},
                {"ticker": "CCC", "cik10": "0000000003", "name": "C"},
                {"ticker": "BBB", "cik10": "0000000002", "name": "B"},
            ]
        )

        def fake_fetch(cik: str, *args: object, **kwargs: object) -> dict[str, object]:
            return {
                "filings": {
                    "recent": {
                        "form": ["4"],
                        "accessionNumber": [f"{cik}-26-000001"],
                        "primaryDocument": ["form4.xml"],
                        "acceptanceDateTime": ["2026-05-21T18:00:00.000Z"],
                        "filingDate": ["2026-05-21"],
                        "reportDate": ["2026-05-21"],
                    }
                }
            }

        submissions.fetch_submissions = fake_fetch
        shard0 = submissions.collect_filings_index(
            tickers=[],
            raw_dir=ROOT,
            forms=["4"],
            shard_index=0,
            shard_count=2,
        )
        shard1 = submissions.collect_filings_index(
            tickers=[],
            raw_dir=ROOT,
            forms=["4"],
            shard_index=1,
            shard_count=2,
        )
        assert set(shard0["ticker"]) == {"AAA", "CCC"}
        assert set(shard1["ticker"]) == {"BBB", "DDD"}
        assert set(shard0["ticker"]).isdisjoint(set(shard1["ticker"]))
    finally:
        submissions.load_company_tickers = original_load
        submissions.fetch_submissions = original_fetch


if __name__ == "__main__":
    test_normalize_cik10_preserves_ten_digit_strings()
    test_normalize_cik_series_returns_object_ten_digit_strings()
    test_cik_rows_from_inputs_supports_13f_manager_ciks()
    test_collect_filings_index_keeps_running_after_bad_manager_cik()
    test_collect_filings_index_supports_stable_issuer_shards()
    print("sec_cik_schema_smoke: PASS")
