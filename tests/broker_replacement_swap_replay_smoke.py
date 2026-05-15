#!/usr/bin/env python3
"""Smoke checks for broker replacement-swap replay."""
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.run_broker_replacement_swap_replay import run  # noqa: E402
from tools.run_weekly_evaluation import px_cache_name  # noqa: E402


def _write_px(cache_dir: Path, ticker: str, closes: list[float], start: str = "2026-01-02") -> None:
    idx = pd.bdate_range(start=start, periods=len(closes))
    df = pd.DataFrame(
        {
            "Open": closes,
            "Close": closes,
            "Adj Close": closes,
            "Volume": [1_000_000] * len(closes),
        },
        index=idx,
    )
    df.to_parquet(cache_dir / px_cache_name(ticker))


def test_replacement_swap_uses_scores_not_forward_labels() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache_prices"
        out = root / "swap"
        cache.mkdir()
        _write_px(cache, "AAA", [100, 99, 98, 97, 96, 95])
        _write_px(cache, "BBB", [50, 51, 55, 60, 65, 70])
        _write_px(cache, "CCC", [10, 10, 10, 10, 10, 10])
        target = root / "targets.csv"
        candidates = root / "candidate_replay_book.csv"
        pd.DataFrame(
            [
                {
                    "rebalance_date": "2026-01-02",
                    "ticker": "AAA",
                    "Name": "Weak Inc",
                    "sector": "Tech",
                    "weight": 0.95,
                    "regime_state": "bull",
                    "portfolio_stale_mega_leader_score": 0.60,
                    "portfolio_risk_entry_block_score": 0.0,
                    "rs_acceleration_score": -0.20,
                }
            ]
        ).to_csv(target, index=False)
        pd.DataFrame(
            [
                {
                    "rebalance_date": "2026-01-02",
                    "ticker": "AAA",
                    "Name": "Weak Inc",
                    "sector": "Tech",
                    "score": 1.0,
                    "portfolio_future_winner_engine_score": 0.10,
                    "portfolio_monster_early_score": 0.10,
                    "h6_dynamic_leader_score": 0.10,
                    "relative_strength_composite": 0.10,
                    "rs_acceleration_score": -0.20,
                    "portfolio_stale_mega_leader_score": 0.60,
                    "portfolio_risk_entry_block_score": 0.0,
                    "portfolio_candidate_gate_label": "future_relaxed",
                    "market_cap_live": 5_000_000_000,
                    "dollar_vol_20d": 50_000_000,
                    "period_forward_return": -0.50,
                },
                {
                    "rebalance_date": "2026-01-02",
                    "ticker": "BBB",
                    "Name": "Leader Inc",
                    "sector": "Tech",
                    "score": 10.0,
                    "portfolio_future_winner_engine_score": 0.95,
                    "portfolio_monster_early_score": 0.90,
                    "h6_dynamic_leader_score": 0.95,
                    "relative_strength_composite": 0.90,
                    "rs_acceleration_score": 0.80,
                    "portfolio_stale_mega_leader_score": 0.0,
                    "portfolio_risk_entry_block_score": 0.0,
                    "portfolio_candidate_gate_label": "future_relaxed",
                    "market_cap_live": 6_000_000_000,
                    "dollar_vol_20d": 80_000_000,
                    "period_forward_return": 0.20,
                },
                {
                    "rebalance_date": "2026-01-02",
                    "ticker": "CCC",
                    "Name": "Leaky Forward Winner",
                    "sector": "Tech",
                    "score": 0.1,
                    "portfolio_future_winner_engine_score": 0.0,
                    "portfolio_monster_early_score": 0.0,
                    "h6_dynamic_leader_score": 0.0,
                    "relative_strength_composite": 0.0,
                    "rs_acceleration_score": 0.0,
                    "portfolio_stale_mega_leader_score": 0.0,
                    "portfolio_risk_entry_block_score": 0.0,
                    "portfolio_candidate_gate_label": "future_relaxed",
                    "market_cap_live": 10_000_000_000,
                    "dollar_vol_20d": 100_000_000,
                    "period_forward_return": 9.99,
                },
            ]
        ).to_csv(candidates, index=False)
        metrics = run(
            argparse.Namespace(
                target_book=str(target),
                candidate_book=str(candidates),
                price_cache=str(cache),
                output_dir=str(out),
                portfolio_kind="main",
                starting_capital=10_000.0,
                fill_mode="next_close",
                cost_bps=25.0,
                no_integer_shares=False,
                max_fill_lag_days=7,
                max_swaps_per_date=1,
                min_score_advantage=0.10,
                weak_score_threshold=0.45,
                min_market_cap_usd=1_000_000_000.0,
                min_dollar_volume_usd=5_000_000.0,
                replacement_weight_scale=1.0,
                allowed_regimes="bull,neutral",
                allow_monster_gate_override=True,
            )
        )
        assert metrics["status"] == "completed"
        assert metrics["replacement_swap_count"] == 1
        assert metrics["used_forward_return_for_selection"] is False
        decisions = pd.read_csv(out / "replacement_swap_decisions.csv")
        assert decisions.iloc[0]["held_ticker"] == "AAA"
        assert decisions.iloc[0]["replacement_ticker"] == "BBB"
        book = pd.read_csv(out / "replacement_target_book.csv")
        assert set(book["ticker"]) == {"BBB"}
        trades = pd.read_csv(out / "trades.csv")
        assert "BBB" in set(trades["ticker"])


def main() -> int:
    test_replacement_swap_uses_scores_not_forward_labels()
    print("broker_replacement_swap_replay_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
