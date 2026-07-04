#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.run_regime_nowcast_dial import run  # noqa: E402
from tools.run_weekly_evaluation import px_cache_name  # noqa: E402


def _write_price(cache: Path, ticker: str, closes: np.ndarray, dates: pd.DatetimeIndex) -> None:
    frame = pd.DataFrame(
        {
            "Open": closes,
            "High": closes,
            "Low": closes,
            "Close": closes,
            "Adj Close": closes,
            "Volume": 1000000,
        },
        index=dates,
    )
    frame.to_parquet(cache / px_cache_name(ticker))


def test_price_cache_adds_vol_breadth_and_ai_bucket_coverage() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache"
        cache.mkdir()
        dates = pd.bdate_range("2025-07-01", periods=260)
        as_of = pd.Timestamp(dates[-1]).date().isoformat()
        base = np.linspace(100.0, 130.0, len(dates))

        _write_price(cache, "SPY", base, dates)
        _write_price(cache, "QQQ", np.linspace(100.0, 135.0, len(dates)), dates)
        for ticker, end in [("AMD", 140.0), ("MU", 142.0), ("SNDK", 138.0), ("WDC", 136.0)]:
            _write_price(cache, ticker, np.linspace(100.0, end, len(dates)), dates)
        for idx in range(30):
            _write_price(cache, f"T{idx:02d}", np.linspace(50.0 + idx, 75.0 + idx, len(dates)), dates)

        payload = run(
            argparse.Namespace(
                signal_panel="",
                price_cache=str(cache),
                as_of_date=as_of,
                output_dir=str(root / "out"),
                coverage_mode="service",
                allow_state_override=False,
            )
        )

        coverage = payload["critical_group_coverage"]
        assert payload["covered_signal_count"] >= 6, payload
        assert coverage["trend"] is True, payload
        assert coverage["volatility_stress"] is True, payload
        assert coverage["breadth"] is True, payload
        assert coverage["ai_bucket_rs"] is True, payload
        assert "vix_spike_or_above_25" not in payload["missing_signals"], payload
        assert "universe_above_200dma_below_40pct" not in payload["missing_signals"], payload
        assert "ai_capex_bucket_rs_breakdown" not in payload["missing_signals"], payload
        assert payload["current_state"] == "DATA_INSUFFICIENT", payload
        assert "credit_liquidity" in payload["missing_critical_groups"], payload
        assert "earnings_guidance" in payload["missing_critical_groups"], payload
        assert payload["policy_hook_allowed"] is False
        assert payload["public_display_allowed"] is False


def main() -> int:
    test_price_cache_adds_vol_breadth_and_ai_bucket_coverage()
    print("regime_nowcast_price_cache_coverage_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
