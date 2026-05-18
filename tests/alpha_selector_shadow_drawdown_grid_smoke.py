#!/usr/bin/env python3
"""Smoke checks for alpha-selector shadow-account drawdown grid."""
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.run_alpha_selector_shadow_drawdown_grid import run  # noqa: E402
from tools.run_weekly_evaluation import px_cache_name  # noqa: E402


def _write_px(cache_dir: Path, ticker: str, closes: list[float], start: str = "2025-10-01") -> None:
    idx = pd.bdate_range(start=start, periods=len(closes))
    pd.DataFrame(
        {
            "Open": closes,
            "Close": closes,
            "Adj Close": closes,
            "Volume": [1_000_000] * len(closes),
        },
        index=idx,
    ).to_parquet(cache_dir / px_cache_name(ticker))


def test_shadow_drawdown_grid_scales_after_observable_shadow_loss() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache_prices"
        out = root / "shadow_drawdown"
        cache.mkdir()
        # Full-risk shadow account rises, suffers an observable drawdown, then
        # recovers. The scaled target book may only react after that drawdown.
        aaa = [100 + i for i in range(20)] + [120, 112, 103, 95, 90, 88, 92, 97, 104, 112] + [115 + i for i in range(20)]
        bbb = [50 + 0.2 * i for i in range(len(aaa))]
        _write_px(cache, "AAA", aaa)
        _write_px(cache, "BBB", bbb)
        target = root / "target_book.csv"
        pd.DataFrame(
            [
                {"rebalance_date": "2025-10-01", "ticker": "AAA", "weight": 0.70, "Name": "Leader A"},
                {"rebalance_date": "2025-10-01", "ticker": "BBB", "weight": 0.30, "Name": "Leader B"},
            ]
        ).to_csv(target, index=False)
        payload = run(
            argparse.Namespace(
                alpha_selector_dir=str(root / "missing_alpha_selector_dir"),
                target_book=str(target),
                top_variants=1,
                price_cache=str(cache),
                portfolio_kind="main",
                output_dir=str(out),
                grid="-0.08:-0.14:0.70:0.40:-0.04",
                starting_capital=10_000.0,
                fill_mode="next_close",
                cost_bps=0.0,
                no_integer_shares=False,
                max_fill_lag_days=7,
            )
        )
        assert payload["status"] == "completed"
        assert payload["valid_for_production"] is True
        summary = pd.read_csv(out / "summary.csv")
        assert len(summary) == 1
        states = pd.read_csv(next(out.glob("*/shadow_drawdown_states.csv")))
        assert {"date", "state", "multiplier", "shadow_drawdown"}.issubset(states.columns)
        assert (states["multiplier"] < 1.0).any()
        scaled_target = pd.read_csv(next(out.glob("*/shadow_drawdown_target_book.csv")))
        assert set(scaled_target["ticker"]) == {"AAA", "BBB"}
        assert float(scaled_target["weight"].min()) < 0.30


def main() -> int:
    test_shadow_drawdown_grid_scales_after_observable_shadow_loss()
    print("alpha_selector_shadow_drawdown_grid_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
