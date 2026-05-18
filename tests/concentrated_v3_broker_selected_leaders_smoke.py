#!/usr/bin/env python3
"""Smoke checks for concentrated v3 broker-selected leaders."""
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.run_concentrated_v3_broker_selected_leaders import run  # noqa: E402
from tools.run_weekly_evaluation import px_cache_name  # noqa: E402


def _write_px(cache_dir: Path, ticker: str, closes: list[float], start: str = "2026-01-02") -> None:
    idx = pd.bdate_range(start=start, periods=len(closes))
    pd.DataFrame(
        {"Open": closes, "Close": closes, "Adj Close": closes, "Volume": [1_000_000] * len(closes)},
        index=idx,
    ).to_parquet(cache_dir / px_cache_name(ticker))


def test_concentrated_v3_excludes_n7_and_runs_broker_replay() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache_prices"
        cache.mkdir()
        for ticker, closes in {
            "AAA": [100, 102, 104, 106, 108, 110, 112],
            "BBB": [50, 51, 52, 53, 54, 55, 56],
            "CCC": [30, 30.5, 31, 31.5, 32, 32.5, 33],
        }.items():
            _write_px(cache, ticker, closes)
        rows = []
        for dt in ["2026-01-02", "2026-01-05"]:
            for idx, ticker in enumerate(["AAA", "BBB", "CCC"]):
                rows.append(
                    {
                        "rebalance_date": dt,
                        "ticker": ticker,
                        "Name": ticker,
                        "sector": "Tech" if ticker != "CCC" else "Industrial",
                        "portfolio_sleeve_label": "future_winner",
                        "portfolio_candidate_gate_label": "future_relaxed",
                        "portfolio_future_winner_engine_score": 0.95 - idx * 0.1,
                        "portfolio_early_scout_engine_score": 0.70 - idx * 0.1,
                        "portfolio_monster_early_score": 0.75 - idx * 0.1,
                        "leader_onset_score": 0.90 - idx * 0.1,
                        "rs_acceleration_score": 0.80 - idx * 0.1,
                        "industry_group_strength_score": 0.70,
                        "relative_strength_composite": 0.80,
                        "portfolio_risk_entry_block_score": 0.0,
                        "portfolio_stale_mega_leader_score": 0.0,
                        "px": 100.0,
                        "dollar_vol_20d": 100_000_000,
                        "mktcap": 10_000_000_000,
                    }
                )
        candidate = root / "candidate_replay_book.csv"
        pd.DataFrame(rows).to_csv(candidate, index=False)
        out = root / "out"
        payload = run(
            argparse.Namespace(
                candidate_book=str(candidate),
                price_cache=str(cache),
                output_dir=str(out),
                sec_signals="",
                starting_capital=10_000.0,
                fill_mode="next_close",
                cost_bps=0.0,
                cost_bps_list="0",
                no_integer_shares=False,
                max_fill_lag_days=7,
                target_ns="2,7",
                single_name_caps="0.50",
                same_theme_caps="0.70",
                staged_entry="0.50,0.80,1.00",
                score_sources="future_market",
                min_market_cap_usd=1_000_000_000.0,
                min_dollar_volume_usd=1_000_000.0,
                min_price=5.0,
                allow_unfillable_targets=False,
            )
        )
        assert payload["status"] == "completed"
        assert payload["n7_champion_allowed"] is False
        assert payload["banned_target_ns_requested"] == [7]
        summary = pd.read_csv(out / "summary.csv")
        assert set(summary["target_stock_names"]) == {2}
        target = pd.read_csv(next(out.glob("future_market_N2_cap*/target_book.csv")))
        assert target["target_stock_names"].eq(2).all()
        assert not target["target_stock_names"].eq(7).any()
        assert target["weight"].max() <= 0.50


def main() -> int:
    test_concentrated_v3_excludes_n7_and_runs_broker_replay()
    print("concentrated_v3_broker_selected_leaders_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
