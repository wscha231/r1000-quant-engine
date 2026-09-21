#!/usr/bin/env python3
from __future__ import annotations

import math
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.us_strict_market_snapshot_v1 import (
    UsStrictMarketError,
    compute_snapshot,
)


def frame(growth: float, periods: int = 281) -> pd.DataFrame:
    dates = pd.bdate_range(end="2026-09-18", periods=periods)
    closes = [100.0 * math.exp(growth * i) for i in range(periods)]
    return pd.DataFrame({"date": dates, "close": closes, "volume": [1000] * periods})


def base_kwargs() -> dict:
    return {
        "asset_id": "US:AVGO",
        "ticker": "AVGO",
        "session_date": "2026-09-18",
        "observed_at": "2026-09-18T20:00:00+00:00",
        "available_at": "2026-09-18T20:05:00+00:00",
        "collected_at": "2026-09-18T20:06:00+00:00",
        "source_identity": "ALPACA_V2_IEX_RAW_SPLIT_CONCORDANCE_V1",
        "raw_artifact_id": "RAW-MKT:US:AVGO:2026-09-18:v1",
        "raw_sha256": "a" * 64,
    }


def test_reviewed_proxy_and_exact_rs() -> None:
    asset = frame(0.0014)
    bench = frame(0.0006)
    out = compute_snapshot(asset, asset.copy(), bench, bench.copy(), **base_kwargs())
    assert out["data_quality"] == "REVIEWED_OBSERVED"
    assert out["basis_review_status"] == "REVIEWED"
    assert out["corporate_action_quarantine"] is False
    assert out["historical_pit_certified"] is False
    assert out["validated_er_eligible"] is False
    assert out["selector_eligible"] is False
    for horizon in (20, 60, 120, 240):
        expected = (
            math.log1p(out[f"return_{horizon}d"])
            - math.log1p(out[f"benchmark_return_{horizon}d"])
        )
        assert abs(out[f"rs_{horizon}d"] - expected) <= 1e-12


def test_raw_split_mismatch_fails_closed() -> None:
    asset_split = frame(0.0014)
    asset_raw = asset_split.copy()
    asset_raw.loc[asset_raw.index[-100], "close"] *= 2.0
    bench = frame(0.0006)
    try:
        compute_snapshot(
            asset_split, asset_raw, bench, bench.copy(), **base_kwargs()
        )
    except UsStrictMarketError as exc:
        assert "corporate_action_basis_mismatch" in str(exc)
    else:
        raise AssertionError("raw/split mismatch was accepted")


def test_missing_session_fails_closed() -> None:
    asset = frame(0.0014)
    missing = asset.drop(index=asset.index[-50]).reset_index(drop=True)
    bench = frame(0.0006)
    try:
        compute_snapshot(missing, missing.copy(), bench, bench.copy(), **base_kwargs())
    except UsStrictMarketError as exc:
        assert "incomplete_241_session_grid" in str(exc)
    else:
        raise AssertionError("incomplete session grid was accepted")


def test_time_order_fails_closed() -> None:
    asset = frame(0.0014)
    bench = frame(0.0006)
    kwargs = base_kwargs()
    kwargs["collected_at"] = "2026-09-18T20:04:00+00:00"
    try:
        compute_snapshot(asset, asset.copy(), bench, bench.copy(), **kwargs)
    except UsStrictMarketError as exc:
        assert "market_time_order" in str(exc)
    else:
        raise AssertionError("noncausal timing was accepted")


if __name__ == "__main__":
    test_reviewed_proxy_and_exact_rs()
    test_raw_split_mismatch_fails_closed()
    test_missing_session_fails_closed()
    test_time_order_fails_closed()
    print("us strict market snapshot v1 smoke: PASS")
