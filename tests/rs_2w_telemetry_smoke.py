#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys
import tempfile

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from r1000_helpers import px_cache_name  # noqa: E402
from tools.run_alphaops_vnext_policy_replay import alphaops_score, enrich_relative_strength  # noqa: E402


def _write_prices(cache: Path, ticker: str, closes: list[float]) -> None:
    idx = pd.bdate_range("2020-01-01", periods=len(closes))
    frame = pd.DataFrame({"Open": closes, "Close": closes}, index=idx)
    frame.to_parquet(cache / px_cache_name(ticker))


def test_enrich_relative_strength_emits_2w_telemetry() -> None:
    with tempfile.TemporaryDirectory() as tmp_raw:
        cache = Path(tmp_raw) / "cache_prices"
        cache.mkdir()
        _write_prices(cache, "AAA", [100 + i for i in range(30)])
        for bench in ("SPY", "QQQ", "SMH", "SOXX"):
            _write_prices(cache, bench, [100 + 0.2 * i for i in range(30)])
        candidate = pd.DataFrame(
            [
                {
                    "rebalance_date": "2020-02-11",
                    "ticker": "AAA",
                    "lane_confidence": 1.0,
                    "market_leader_lane_score": 1.0,
                    "valuation_support_score": 1.0,
                }
            ]
        )

        out = enrich_relative_strength(candidate, cache)

    assert "ticker_ret_2w" in out.columns
    assert "rs_spy_2w" in out.columns
    assert "rs_qqq_2w" in out.columns
    assert "rs_benchmark_2w" in out.columns
    assert bool(out.iloc[0]["rs_price_coverage_2w"])


def test_2w_rs_does_not_enter_alphaops_score_yet() -> None:
    frame = pd.DataFrame(
        [
            {
                "lane_confidence": 1.0,
                "market_leader_lane_score": 2.0,
                "valuation_support_score": 1.0,
                "rs_benchmark_1w": 0.10,
                "rs_semis_3m": 0.20,
                "top7_support_boost": 0.0,
                "evidence_support_score": 1.0,
                "rs_benchmark_2w": -9.0,
            },
            {
                "lane_confidence": 0.5,
                "market_leader_lane_score": 1.0,
                "valuation_support_score": 0.5,
                "rs_benchmark_1w": 0.05,
                "rs_semis_3m": 0.10,
                "top7_support_boost": 0.0,
                "evidence_support_score": 0.5,
                "rs_benchmark_2w": 9.0,
            },
        ]
    )
    baseline = alphaops_score(frame)
    changed = frame.copy()
    changed["rs_benchmark_2w"] = [99.0, -99.0]

    pd.testing.assert_series_equal(baseline, alphaops_score(changed))


if __name__ == "__main__":
    test_enrich_relative_strength_emits_2w_telemetry()
    test_2w_rs_does_not_enter_alphaops_score_yet()
    print("rs_2w_telemetry_smoke: PASS")
