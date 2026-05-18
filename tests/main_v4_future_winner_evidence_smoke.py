#!/usr/bin/env python3
"""Smoke checks for Main v4 future-winner evidence challenger."""
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.run_main_v4_future_winner_evidence import run  # noqa: E402
from tools.run_weekly_evaluation import px_cache_name  # noqa: E402


def _write_px(cache_dir: Path, ticker: str, closes: list[float], start: str = "2026-01-02") -> None:
    idx = pd.bdate_range(start=start, periods=len(closes))
    pd.DataFrame(
        {"Open": closes, "Close": closes, "Adj Close": closes, "Volume": [1_000_000] * len(closes)},
        index=idx,
    ).to_parquet(cache_dir / px_cache_name(ticker))


def test_main_v4_runs_without_forward_label_selection() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache_prices"
        cache.mkdir()
        for ticker, closes in {
            "AAA": [100, 101, 102, 103, 104, 105, 106, 107],
            "BBB": [50, 51, 52, 53, 54, 55, 56, 57],
            "CCC": [30, 31, 32, 33, 34, 35, 36, 37],
            "LEAK": [10, 9, 8, 7, 6, 5, 4, 3],
        }.items():
            _write_px(cache, ticker, closes)
        rows = []
        for dt in ["2026-01-02", "2026-01-05", "2026-01-06"]:
            rows.extend(
                [
                    {
                        "rebalance_date": dt,
                        "ticker": "AAA",
                        "Name": "Future Winner A",
                        "sector": "Tech",
                        "portfolio_sleeve_label": "future_winner",
                        "portfolio_candidate_gate_label": "future_relaxed",
                        "portfolio_future_winner_engine_score": 0.95,
                        "portfolio_early_scout_engine_score": 0.70,
                        "portfolio_monster_early_score": 0.65,
                        "h6_dynamic_leader_score": 0.50,
                        "rs_acceleration_score": 0.80,
                        "industry_group_strength_score": 0.75,
                        "relative_strength_composite": 0.85,
                        "price_above_ma50": 1.0,
                        "price_above_ma200": 1.0,
                        "breakout_setup_quality_score": 0.75,
                        "volume_accumulation_score": 0.70,
                        "portfolio_risk_entry_block_score": 0.0,
                        "portfolio_stale_mega_leader_score": 0.0,
                        "px": 100.0,
                        "dollar_vol_20d": 100_000_000,
                        "mktcap": 10_000_000_000,
                        "period_forward_return": 0.05,
                    },
                    {
                        "rebalance_date": dt,
                        "ticker": "BBB",
                        "Name": "Evidence B",
                        "sector": "Tech",
                        "portfolio_sleeve_label": "early_scout",
                        "portfolio_candidate_gate_label": "early_relaxed",
                        "portfolio_future_winner_engine_score": 0.55,
                        "portfolio_early_scout_engine_score": 0.60,
                        "portfolio_monster_early_score": 0.50,
                        "h6_dynamic_leader_score": 0.45,
                        "rs_acceleration_score": 0.55,
                        "industry_group_strength_score": 0.50,
                        "relative_strength_composite": 0.60,
                        "price_above_ma50": 1.0,
                        "price_above_ma200": 1.0,
                        "breakout_setup_quality_score": 0.50,
                        "volume_accumulation_score": 0.50,
                        "portfolio_risk_entry_block_score": 0.0,
                        "portfolio_stale_mega_leader_score": 0.0,
                        "px": 50.0,
                        "dollar_vol_20d": 80_000_000,
                        "mktcap": 8_000_000_000,
                        "period_forward_return": 0.03,
                    },
                    {
                        "rebalance_date": dt,
                        "ticker": "LEAK",
                        "Name": "Forward Only",
                        "sector": "Tech",
                        "portfolio_sleeve_label": "unassigned",
                        "portfolio_candidate_gate_label": "rejected",
                        "portfolio_future_winner_engine_score": 0.0,
                        "portfolio_early_scout_engine_score": 0.0,
                        "portfolio_monster_early_score": 0.0,
                        "h6_dynamic_leader_score": 0.0,
                        "rs_acceleration_score": 0.0,
                        "industry_group_strength_score": 0.0,
                        "relative_strength_composite": 0.0,
                        "portfolio_risk_entry_block_score": 0.0,
                        "portfolio_stale_mega_leader_score": 0.0,
                        "px": 10.0,
                        "dollar_vol_20d": 90_000_000,
                        "mktcap": 9_000_000_000,
                        "period_forward_return": 99.0,
                    },
                ]
            )
        candidate = root / "candidate_replay_book.csv"
        pd.DataFrame(rows).to_csv(candidate, index=False)
        sec_path = root / "sec_ownership_signals.parquet"
        pd.DataFrame(
            [
                {
                    "ticker": "BBB",
                    "as_of_date": "2026-01-02",
                    "sec_form4_cluster_buy_score": 1.0,
                    "early_evidence_score": 1.0,
                    "evidence_confidence_score": 1.0,
                }
            ]
        ).to_parquet(sec_path, index=False)
        out = root / "out"
        payload = run(
            argparse.Namespace(
                candidate_book=str(candidate),
                price_cache=str(cache),
                output_dir=str(out),
                sec_signals=str(sec_path),
                starting_capital=10_000.0,
                fill_mode="next_close",
                cost_bps=0.0,
                cost_bps_list="0",
                no_integer_shares=False,
                max_fill_lag_days=7,
                target_ns="2",
                score_sources="future_winner,leader_onset_sec_shadow",
                single_name_caps="0.60",
                cash_floor=0.03,
                replace_threshold_z=0.75,
                broken_threshold_z=0.35,
                min_market_cap_usd=1_000_000_000.0,
                min_dollar_volume_usd=1_000_000.0,
                min_price=5.0,
                allow_unfillable_targets=False,
            )
        )
        assert payload["status"] == "completed"
        summary = pd.read_csv(out / "summary.csv")
        assert len(summary) == 2
        assert set(summary["score_source"]) == {"future_winner", "leader_onset_sec_shadow"}
        target = pd.read_csv(next(out.glob("future_winner_N2_cap*/target_book.csv")))
        assert "LEAK" not in set(target["ticker"])
        assert {"AAA", "BBB"}.issubset(set(target["ticker"]))
        assert target.groupby("rebalance_date")["weight"].sum().max() <= 0.98
        assert "period_forward_return" not in target.columns


def main() -> int:
    test_main_v4_runs_without_forward_label_selection()
    print("main_v4_future_winner_evidence_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
