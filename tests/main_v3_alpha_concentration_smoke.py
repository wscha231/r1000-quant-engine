#!/usr/bin/env python3
"""Smoke checks for Main v3 alpha-concentration replay."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.run_main_v3_alpha_concentration import replay  # noqa: E402


def write_candidate_book(path: Path) -> None:
    rows = []
    dates = ["2026-01-31", "2026-02-28", "2026-03-31"]
    for idx, dt in enumerate(dates):
        for rank in range(1, 15):
            strong = rank <= 4
            rows.append(
                {
                    "rebalance_date": dt,
                    "ticker": f"T{rank:02d}",
                    "Name": f"Ticker {rank}",
                    "sector": "Technology",
                    "score": 10 - rank,
                    "score_total": 10 - rank,
                    "period_forward_return": 0.08 - rank * 0.003 + idx * 0.001,
                    "portfolio_core_compounder_engine_score": 0.5 if not strong else 0.8,
                    "portfolio_future_winner_engine_score": 0.4 if not strong else 0.95,
                    "portfolio_early_scout_engine_score": 0.3 if not strong else 0.75,
                    "portfolio_monster_early_score": 0.1 if not strong else 0.85,
                    "future_winner_scout_score": 0.2 if not strong else 0.9,
                    "multi_year_winner_score": 0.2 if not strong else 0.8,
                    "oneil_leadership_score": 0.2 if not strong else 0.9,
                    "industry_group_strength_score": 0.2 if not strong else 0.9,
                    "rs_acceleration_score": 0.0 if not strong else 0.6,
                    "h1_oversold_value_score": 0.0,
                    "price_above_ma200": 1.0,
                    "price_above_ma50": 1.0,
                    "breakout_fresh_20d": 1.0 if strong else 0.0,
                    "post_breakout_hold_score": 0.7 if strong else 0.1,
                    "fundamental_reliability_score": 0.7,
                    "portfolio_candidate_gate_label": "future_relaxed",
                    "portfolio_candidate_minimum_pass": True,
                    "portfolio_risk_entry_block_score": 0.0,
                    "portfolio_stale_mega_leader_score": 0.0,
                    "risk_penalty": 0.0,
                    "stage2_overext_penalty": 0.0,
                    "overheat_penalty": 0.0,
                    "regime_state": "bull",
                    "market_style_regime_label": "breakout_growth",
                    "style_row_breakout_fit": 0.9 if strong else 0.2,
                    "style_row_turnaround_fit": 0.2,
                    "style_row_compounder_fit": 0.5,
                    "style_breakout_preference": 0.8,
                    "style_turnaround_preference": 0.1,
                    "style_quality_compounder_preference": 0.2,
                    "style_cash_defense_preference": 0.0,
                    "theme_phase_multiplier_primary": 1.2,
                    "theme_phase_multiplier_max": 1.2,
                    "theme_event_risk_sensitivity_primary": 0.2,
                    "theme_event_risk_sensitivity_max": 0.2,
                    "theme_structural_growth_primary": 0.9,
                    "theme_structural_growth_max": 0.9,
                    "profit_turn_positive_4q": 1 if strong else 0,
                    "cashflow_turn_positive_4q": 1 if strong else 0,
                    "ni_loss_narrowing_4q": 1 if strong else 0,
                    "any_profit_sign_flip_pos": 1 if strong else 0,
                    "profitability_inflection_score": 0.7 if strong else 0.1,
                    "cashflow_inflection_under_loss_score": 0.7 if strong else 0.1,
                }
            )
    pd.DataFrame(rows).to_csv(path, index=False)


def test_main_v3_alpha_concentration_outputs_replay_book() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        book = root / "candidate_replay_book.csv"
        out = root / "main_v3"
        write_candidate_book(book)
        metrics = replay(book, out, cost_bps=0.0, single_name_cap=0.25, cash_floor=0.03)
        assert metrics["status"] == "completed"
        assert metrics["research_only"] is True
        assert metrics["production_activation_allowed"] is False
        assert metrics["broker_ledger_required_for_official_verdict"] is True
        assert metrics["avg_position_count"] <= 11
        assert metrics["avg_cash_weight"] <= 0.051
        holdings = pd.read_csv(out / "monthly_holdings.csv")
        returns = pd.read_csv(out / "monthly_returns.csv")
        assert {"rebalance_date", "ticker", "weight"}.issubset(holdings.columns)
        assert holdings["weight"].max() <= 0.250001
        assert "main_v3_sleeves" in holdings.columns
        assert "cash_weight" in returns.columns


def main() -> int:
    test_main_v3_alpha_concentration_outputs_replay_book()
    print("main_v3_alpha_concentration_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
