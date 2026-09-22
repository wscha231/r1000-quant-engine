#!/usr/bin/env python3
"""Offline contract for Alpaca research price adjustment and cache identity."""
from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from aggressive import data_alpaca as bars


def fake_alpaca(capture: dict[str, object]) -> dict[str, ModuleType]:
    root = ModuleType("alpaca")
    data = ModuleType("alpaca.data")
    enums = ModuleType("alpaca.data.enums")
    historical = ModuleType("alpaca.data.historical")
    requests = ModuleType("alpaca.data.requests")
    timeframe = ModuleType("alpaca.data.timeframe")

    class Adjustment:
        RAW = "RAW"
        SPLIT = "SPLIT"

    class TimeFrame:
        Day = "1Day"

    class StockBarsRequest:
        def __init__(self, **kwargs):
            capture.update(kwargs)

    class Client:
        def __init__(self, *_args):
            pass

        def get_stock_bars(self, _request):
            index = pd.MultiIndex.from_tuples(
                [("APH", pd.Timestamp("2026-09-18", tz="UTC"))]
            )
            frame = pd.DataFrame({"close": [100.0], "volume": [1.0]}, index=index)
            return SimpleNamespace(df=frame)

    enums.Adjustment = Adjustment
    historical.StockHistoricalDataClient = Client
    requests.StockBarsRequest = StockBarsRequest
    timeframe.TimeFrame = TimeFrame
    return {
        "alpaca": root,
        "alpaca.data": data,
        "alpaca.data.enums": enums,
        "alpaca.data.historical": historical,
        "alpaca.data.requests": requests,
        "alpaca.data.timeframe": timeframe,
    }


def test_cache_basis_is_part_of_identity() -> None:
    split_path = bars._cache_path("APH", 260, "split")
    raw_path = bars._cache_path("APH", 260, "raw")
    assert split_path != raw_path
    assert split_path.name.endswith("_split.parquet")
    assert raw_path.name.endswith("_raw.parquet")


def test_legacy_default_remains_raw() -> None:
    capture: dict[str, object] = {}
    with patch.dict(sys.modules, fake_alpaca(capture)), \
            patch.object(bars, "_cache_is_fresh", return_value=False), \
            patch.object(bars, "get_alpaca_credentials", return_value=("key", "secret")), \
            patch.object(pd.DataFrame, "to_parquet", return_value=None):
        frame = bars.fetch_daily_bars("APH", days=1, force_refresh=True)
    assert not frame.empty
    assert capture["adjustment"] == "RAW", capture


def test_research_wrapper_is_split_adjusted() -> None:
    capture: dict[str, object] = {}
    with patch.dict(sys.modules, fake_alpaca(capture)), \
            patch.object(bars, "_cache_is_fresh", return_value=False), \
            patch.object(bars, "get_alpaca_credentials", return_value=("key", "secret")), \
            patch.object(pd.DataFrame, "to_parquet", return_value=None):
        frame = bars.fetch_research_daily_bars("APH", days=1, force_refresh=True)
    assert not frame.empty
    assert capture["adjustment"] == "SPLIT", capture


def test_raw_request_remains_explicitly_available() -> None:
    capture: dict[str, object] = {}
    with patch.dict(sys.modules, fake_alpaca(capture)), \
            patch.object(bars, "_cache_is_fresh", return_value=False), \
            patch.object(bars, "get_alpaca_credentials", return_value=("key", "secret")), \
            patch.object(pd.DataFrame, "to_parquet", return_value=None):
        frame = bars.fetch_daily_bars(
            "APH", days=1, force_refresh=True, adjustment="raw"
        )
    assert not frame.empty
    assert capture["adjustment"] == "RAW", capture


def test_unknown_adjustment_fails_before_provider_use() -> None:
    try:
        bars.fetch_daily_bars("APH", adjustment="mystery")
    except ValueError as exc:
        assert "unsupported_price_adjustment" in str(exc)
    else:
        raise AssertionError("unknown adjustment accepted")


if __name__ == "__main__":
    test_cache_basis_is_part_of_identity()
    test_legacy_default_remains_raw()
    test_research_wrapper_is_split_adjusted()
    test_raw_request_remains_explicitly_available()
    test_unknown_adjustment_fails_before_provider_use()
    print("data alpaca adjustment smoke: PASS")
