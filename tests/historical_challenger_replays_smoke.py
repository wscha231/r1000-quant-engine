#!/usr/bin/env python3
"""Smoke test historical challenger replay runners."""
from __future__ import annotations

import csv
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "tools"))

from tools.run_alpha_sprint_backtest import replay as alpha_replay  # noqa: E402
from tools.run_concentrated_policy_replay import replay as concentrated_replay  # noqa: E402
from tools.run_main_v2_backtest import replay as main_v2_replay  # noqa: E402
from tools.run_monster_lifecycle_replay import replay as monster_replay  # noqa: E402
from tools.run_position_aware_risk_replay import replay as risk_replay  # noqa: E402


def write_candidate_book(path: Path) -> None:
    fieldnames = [
        "rebalance_date",
        "ticker",
        "Name",
        "sector",
        "industry_group",
        "score",
        "period_forward_return",
        "portfolio_core_compounder_engine_score",
        "portfolio_future_winner_engine_score",
        "portfolio_early_scout_engine_score",
        "long_hold_compounder_score",
        "capital_efficiency_score",
        "sector_adjusted_quality_score",
        "multi_year_winner_score",
        "fundamental_reliability_score",
        "risk_penalty",
        "stage2_overext_penalty",
        "overheat_penalty",
        "price_above_ma200",
        "price_above_ma50",
        "rs_acceleration_score",
        "h1_oversold_value_score",
        "theme_phase_multiplier_primary",
        "theme_phase_multiplier_max",
        "oneil_leadership_score",
        "industry_group_strength_score",
        "future_winner_scout_score",
        "profitability_inflection_score",
        "cashflow_inflection_under_loss_score",
        "profit_turn_positive_4q",
        "cashflow_turn_positive_4q",
        "ni_loss_narrowing_4q",
        "any_profit_sign_flip_pos",
        "breakout_fresh_20d",
        "post_breakout_hold_score",
        "entry_quality_score",
        "concentrated_entry_quality_gate_pass",
        "concentrated_score",
        "selection_confirmation_score",
        "ml_technical_agreement_score",
        "trend_template_full",
        "breakout_setup_quality_score",
        "volatility_contraction_score",
        "explosion_entry_score",
        "explosion_exit_score",
        "h6_dynamic_leader_score",
        "eps_revision_score",
        "revision_score",
        "revenue_growth_final",
        "rev_growth_accel_4q",
        "live_event_risk_score",
        "atr14_pct",
        "rsi14",
        "dollar_vol_20d",
        "market_cap_live",
        "current_price_live",
        "regime_state",
    ]
    rows = []
    for month, ret in [("2024-01-31", 0.08), ("2024-02-29", -0.04), ("2024-03-31", 0.12)]:
        rows.extend(
            [
                {
                    "rebalance_date": month,
                    "ticker": "AAA",
                    "Name": "AAA",
                    "sector": "Tech",
                    "industry_group": "Semis",
                    "score": 3.0,
                    "period_forward_return": ret,
                    "portfolio_core_compounder_engine_score": 0.8,
                    "portfolio_future_winner_engine_score": 0.9,
                    "portfolio_early_scout_engine_score": 0.5,
                    "long_hold_compounder_score": 0.8,
                    "capital_efficiency_score": 0.8,
                    "sector_adjusted_quality_score": 0.7,
                    "multi_year_winner_score": 0.9,
                    "fundamental_reliability_score": 0.8,
                    "risk_penalty": 0.0,
                    "stage2_overext_penalty": 0.0,
                    "overheat_penalty": 0.0,
                    "price_above_ma200": 1,
                    "price_above_ma50": 1,
                    "rs_acceleration_score": 0.8,
                    "h1_oversold_value_score": 0.1,
                    "theme_phase_multiplier_primary": 1.2,
                    "theme_phase_multiplier_max": 1.3,
                    "oneil_leadership_score": 0.7,
                    "industry_group_strength_score": 0.8,
                    "future_winner_scout_score": 0.7,
                    "profitability_inflection_score": 0.6,
                    "cashflow_inflection_under_loss_score": 0.4,
                    "profit_turn_positive_4q": 1,
                    "cashflow_turn_positive_4q": 1,
                    "ni_loss_narrowing_4q": 0,
                    "any_profit_sign_flip_pos": 1,
                    "breakout_fresh_20d": 1,
                    "post_breakout_hold_score": 0.8,
                    "entry_quality_score": 0.9,
                    "concentrated_entry_quality_gate_pass": 1,
                    "concentrated_score": 0.9,
                    "selection_confirmation_score": 0.8,
                    "ml_technical_agreement_score": 0.8,
                    "trend_template_full": 1,
                    "breakout_setup_quality_score": 0.8,
                    "volatility_contraction_score": 0.7,
                    "explosion_entry_score": 0.4,
                    "explosion_exit_score": 0.0,
                    "h6_dynamic_leader_score": 0.7,
                    "eps_revision_score": 0.5,
                    "revision_score": 0.5,
                    "revenue_growth_final": 0.3,
                    "rev_growth_accel_4q": 0.1,
                    "live_event_risk_score": 0.0,
                    "atr14_pct": 0.05,
                    "rsi14": 65,
                    "dollar_vol_20d": 50000000,
                    "market_cap_live": 10000000000,
                    "current_price_live": 50,
                    "regime_state": "bull",
                },
                {
                    "rebalance_date": month,
                    "ticker": "BBB",
                    "Name": "BBB",
                    "sector": "Health",
                    "industry_group": "Tools",
                    "score": 2.0,
                    "period_forward_return": 0.02,
                    "portfolio_core_compounder_engine_score": 0.7,
                    "portfolio_future_winner_engine_score": 0.4,
                    "portfolio_early_scout_engine_score": 0.2,
                    "fundamental_reliability_score": 0.8,
                    "price_above_ma200": 1,
                    "price_above_ma50": 1,
                    "entry_quality_score": 0.7,
                    "concentrated_entry_quality_gate_pass": 1,
                    "concentrated_score": 0.5,
                    "regime_state": "bull",
                },
            ]
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def test_historical_challenger_replays() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        book = root / "candidate_replay_book.csv"
        write_candidate_book(book)
        main_metrics = main_v2_replay(book, root / "main_v2", cost_bps=0.0)
        concentrated_metrics = concentrated_replay(book, root / "conc", [3, 5], [0.25, 0.50], cost_bps=0.0)
        alpha_metrics = alpha_replay(book, root / "alpha", cost_bps=0.0, allow_neutral=False)
        risk_metrics = risk_replay(root / "main_v2" / "monthly_holdings.csv", root / "risk", hard_stop=-0.08, trailing_stop=-0.15)
        monster_metrics = monster_replay(book, root / "monster", policy_name="concentrated", cost_bps=0.0)
        assert main_metrics["status"] == "completed"
        assert concentrated_metrics["status"] == "completed"
        assert alpha_metrics["status"] in {"completed", "inactive_no_bull_months_or_candidates"}
        assert risk_metrics["status"] == "completed"
        assert monster_metrics["status"] == "completed"
        assert (root / "main_v2" / "monthly_holdings.csv").exists()
        assert (root / "conc" / "comparison.csv").exists()
        assert (root / "risk" / "actions.csv").exists()
        assert (root / "monster" / "events.csv").exists()


if __name__ == "__main__":
    test_historical_challenger_replays()
    print("historical_challenger_replays_smoke: ok")
