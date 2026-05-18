#!/usr/bin/env python3
"""Smoke checks for alpha-selector dynamic regime grid."""
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.run_alpha_selector_dynamic_regime_grid import run  # noqa: E402
from tools.run_weekly_evaluation import px_cache_name  # noqa: E402


def _write_px(cache_dir: Path, ticker: str, closes: list[float], start: str = "2026-01-02") -> None:
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


def _candidate_row(dt: str, ticker: str, score: float, regime: str) -> dict[str, object]:
    return {
        "rebalance_date": dt,
        "ticker": ticker,
        "Name": ticker,
        "sector": "Tech",
        "score": score,
        "regime_state": regime,
        "portfolio_sleeve_label": "future_winner",
        "portfolio_candidate_gate_label": "future_relaxed",
        "portfolio_future_winner_engine_score": score,
        "portfolio_early_scout_engine_score": score * 0.9,
        "portfolio_monster_early_score": score * 0.8,
        "h6_dynamic_leader_score": score * 0.7,
        "rs_acceleration_score": score * 0.6,
        "industry_group_strength_score": score * 0.5,
        "portfolio_risk_entry_block_score": 0.0,
        "portfolio_stale_mega_leader_score": 0.0,
        "px": 50.0,
        "dollar_vol_20d": 50_000_000,
        "mktcap": 5_000_000_000,
        "period_forward_return": 99.0,
    }


def test_dynamic_regime_grid_switches_specs_without_forward_labels() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache_prices"
        out = root / "dynamic_regime"
        cache.mkdir()
        _write_px(cache, "AAA", [100, 101, 102, 103, 104, 105, 106, 107])
        _write_px(cache, "BBB", [50, 51, 52, 53, 54, 55, 56, 57])
        _write_px(cache, "CCC", [30, 31, 32, 33, 34, 35, 36, 37])
        rows = []
        for dt, regime in [("2026-01-02", "bull"), ("2026-01-05", "bear")]:
            rows.extend(
                [
                    _candidate_row(dt, "AAA", 0.95, regime),
                    _candidate_row(dt, "BBB", 0.80, regime),
                    _candidate_row(dt, "CCC", 0.70, regime),
                ]
            )
        candidate = root / "candidate_replay_book.csv"
        pd.DataFrame(rows).to_csv(candidate, index=False)
        payload = run(
            argparse.Namespace(
                candidate_book=str(candidate),
                price_cache=str(cache),
                output_dir=str(out),
                portfolio_kind="main",
                bull_variants="future_heavy_N1_cap1.0",
                neutral_variants="future_heavy_N2_cap0.5",
                bear_variants="future_heavy_N2_cap0.5",
                neutral_multipliers="1.0",
                bear_multipliers="0.5",
                min_market_cap_usd=1_000_000_000.0,
                min_dollar_volume_usd=1_000_000.0,
                min_price=5.0,
                starting_capital=10_000.0,
                fill_mode="next_close",
                cost_bps=0.0,
                no_integer_shares=False,
                max_fill_lag_days=7,
                allow_unfillable_targets=False,
                max_variants=1,
            )
        )
        assert payload["status"] == "completed"
        assert payload["valid_for_production"] is True
        summary = pd.read_csv(out / "summary.csv")
        assert len(summary) == 1
        target = pd.read_csv(next(out.glob("*/target_book.csv")))
        assert "period_forward_return" not in target.columns or "period_forward_return" not in set(target.columns)
        bull = target[target["dynamic_regime_state"].eq("bull")]
        bear = target[target["dynamic_regime_state"].eq("bear")]
        assert bull["ticker"].nunique() == 1
        assert bear["ticker"].nunique() == 2
        assert abs(float(bear["weight"].sum()) - 0.5) < 1e-6


def main() -> int:
    test_dynamic_regime_grid_switches_specs_without_forward_labels()
    print("alpha_selector_dynamic_regime_grid_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
