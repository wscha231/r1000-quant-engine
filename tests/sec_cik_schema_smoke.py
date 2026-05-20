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


if __name__ == "__main__":
    test_normalize_cik10_preserves_ten_digit_strings()
    test_normalize_cik_series_returns_object_ten_digit_strings()
    test_cik_rows_from_inputs_supports_13f_manager_ciks()
    print("sec_cik_schema_smoke: PASS")
