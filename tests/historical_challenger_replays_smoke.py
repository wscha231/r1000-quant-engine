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
from tools.run_lifecycle_review_overlay import replay as lifecycle_overlay_replay  # noqa: E402
from tools.run_governance_catalyst_report import run as governance_report_run  # noqa: E402
from tools.run_leader_drop_diagnostics_sidecar import run as leader_drop_run  # noqa: E402
from tools.run_position_aware_risk_replay import replay as risk_replay  # noqa: E402
from tools.run_style_regime_report import run as style_regime_run  # noqa: E402
from tools.historical_replay_lib import infer_return_col, score_power_weights  # noqa: E402
from r1000_config import EngineConfig  # noqa: E402
from r1000_pipeline import concentrated_weight_map  # noqa: E402


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
        "theme_phase_primary",
        "theme_horizon_primary",
        "theme_holding_profile_primary",
        "theme_event_risk_sensitivity_primary",
        "theme_event_risk_sensitivity_max",
        "theme_structural_growth_primary",
        "theme_structural_growth_max",
        "theme_target_hold_months_primary",
        "theme_max_hold_months_primary",
        "theme_short_cycle_flag_primary",
        "theme_short_cycle_flag_max",
        "market_style_regime_label",
        "style_breakout_preference",
        "style_turnaround_preference",
        "style_quality_compounder_preference",
        "style_cash_defense_preference",
        "style_liquidity_tailwind_score",
        "style_rate_pressure_score",
        "style_inflation_pressure_score",
        "style_overheat_risk_score",
        "style_calendar_month",
        "style_calendar_quarter",
        "style_calendar_years_since_start",
        "style_calendar_month_sin",
        "style_calendar_month_cos",
        "style_calendar_quarter_sin",
        "style_calendar_quarter_cos",
        "style_row_breakout_fit",
        "style_row_turnaround_fit",
        "style_row_compounder_fit",
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
                    "theme_phase_primary": "early",
                    "theme_horizon_primary": "structural_growth",
                    "theme_holding_profile_primary": "long_duration",
                    "theme_event_risk_sensitivity_primary": 0.15,
                    "theme_event_risk_sensitivity_max": 0.15,
                    "theme_structural_growth_primary": 1.0,
                    "theme_structural_growth_max": 1.0,
                    "theme_target_hold_months_primary": 36,
                    "theme_max_hold_months_primary": 84,
                    "theme_short_cycle_flag_primary": 0,
                    "theme_short_cycle_flag_max": 0,
                    "market_style_regime_label": "breakout_growth",
                    "style_breakout_preference": 0.8,
                    "style_turnaround_preference": 0.2,
                    "style_quality_compounder_preference": 0.3,
                    "style_cash_defense_preference": 0.1,
                    "style_liquidity_tailwind_score": 0.7,
                    "style_rate_pressure_score": 0.1,
                    "style_inflation_pressure_score": 0.1,
                    "style_overheat_risk_score": 0.2,
                    "style_calendar_month": 1,
                    "style_calendar_quarter": 1,
                    "style_calendar_years_since_start": 0.0,
                    "style_calendar_month_sin": 0.5,
                    "style_calendar_month_cos": 0.866,
                    "style_calendar_quarter_sin": 1.0,
                    "style_calendar_quarter_cos": 0.0,
                    "style_row_breakout_fit": 0.8,
                    "style_row_turnaround_fit": 0.1,
                    "style_row_compounder_fit": 0.3,
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
                    "theme_phase_primary": "maturing",
                    "theme_horizon_primary": "commodity_cycle",
                    "theme_holding_profile_primary": "tactical_cycle",
                    "theme_event_risk_sensitivity_primary": 0.85,
                    "theme_event_risk_sensitivity_max": 0.85,
                    "theme_structural_growth_primary": 0.25,
                    "theme_structural_growth_max": 0.25,
                    "theme_target_hold_months_primary": 4,
                    "theme_max_hold_months_primary": 12,
                    "theme_short_cycle_flag_primary": 1,
                    "theme_short_cycle_flag_max": 1,
                    "market_style_regime_label": "turnaround_accumulation",
                    "style_breakout_preference": 0.2,
                    "style_turnaround_preference": 0.7,
                    "style_quality_compounder_preference": 0.4,
                    "style_cash_defense_preference": 0.2,
                    "style_liquidity_tailwind_score": 0.6,
                    "style_rate_pressure_score": 0.3,
                    "style_inflation_pressure_score": 0.4,
                    "style_overheat_risk_score": 0.2,
                    "style_calendar_month": 1,
                    "style_calendar_quarter": 1,
                    "style_calendar_years_since_start": 0.0,
                    "style_calendar_month_sin": 0.5,
                    "style_calendar_month_cos": 0.866,
                    "style_calendar_quarter_sin": 1.0,
                    "style_calendar_quarter_cos": 0.0,
                    "style_row_breakout_fit": 0.1,
                    "style_row_turnaround_fit": 0.7,
                    "style_row_compounder_fit": 0.2,
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


def write_monthly_weights(path: Path) -> None:
    fieldnames = ["rebalance_date", "ticker", "weight", "period_forward_return", "cash_target"]
    rows = [
        {"rebalance_date": "2024-01-31", "ticker": "AAA", "weight": 0.30, "period_forward_return": 0.08, "cash_target": 0.0},
        {"rebalance_date": "2024-01-31", "ticker": "BBB", "weight": 0.20, "period_forward_return": 0.02, "cash_target": 0.0},
        {"rebalance_date": "2024-02-29", "ticker": "AAA", "weight": 0.28, "period_forward_return": -0.04, "cash_target": 0.0},
        {"rebalance_date": "2024-02-29", "ticker": "BBB", "weight": 0.20, "period_forward_return": 0.02, "cash_target": 0.0},
        {"rebalance_date": "2024-03-31", "ticker": "AAA", "weight": 0.28, "period_forward_return": 0.12, "cash_target": 0.0},
        {"rebalance_date": "2024-03-31", "ticker": "BBB", "weight": 0.20, "period_forward_return": 0.02, "cash_target": 0.0},
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def test_historical_challenger_replays() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        book = root / "candidate_replay_book.csv"
        monthly_weights = root / "main_monthly_weights.csv"
        write_candidate_book(book)
        write_monthly_weights(monthly_weights)
        main_metrics = main_v2_replay(book, root / "main_v2", cost_bps=0.0)
        concentrated_metrics = concentrated_replay(book, root / "conc", [3, 5], [0.25, 0.50], cost_bps=0.0)
        alpha_metrics = alpha_replay(book, root / "alpha", cost_bps=0.0, allow_neutral=False)
        risk_metrics = risk_replay(root / "main_v2" / "monthly_holdings.csv", root / "risk", hard_stop=-0.08, trailing_stop=-0.15)
        monster_metrics = monster_replay(book, root / "monster", policy_name="concentrated", cost_bps=0.0)
        lifecycle_review_metrics = monster_replay(book, root / "monster_review", policy_name="lifecycle_review_concentrated", cost_bps=0.0)
        overlay_metrics = lifecycle_overlay_replay(monthly_weights, book, root / "overlay", policy_name="lifecycle_review_main", cost_bps=0.0)
        latest = root / "latest"
        latest_reports = latest / "reports"
        latest_reports.mkdir(parents=True, exist_ok=True)
        (latest_reports / "candidate_replay_book.csv").write_text(book.read_text(encoding="utf-8"), encoding="utf-8")
        style_metrics = style_regime_run(latest, root / "style")
        assert main_metrics["status"] == "completed"
        assert concentrated_metrics["status"] == "completed"
        assert alpha_metrics["status"] in {"completed", "inactive_no_bull_months_or_candidates"}
        assert risk_metrics["status"] == "completed"
        assert monster_metrics["status"] == "completed"
        assert lifecycle_review_metrics["status"] == "completed"
        assert overlay_metrics["status"] == "completed"
        assert style_metrics["status"] == "completed"
        assert lifecycle_review_metrics["entry_requires_leadership"]
        assert (root / "main_v2" / "monthly_holdings.csv").exists()
        assert (root / "conc" / "comparison.csv").exists()
        assert (root / "risk" / "actions.csv").exists()
        assert (root / "monster" / "events.csv").exists()
        assert (root / "monster_review" / "events.csv").exists()
        assert (root / "overlay" / "holdings.csv").exists()
        assert (root / "style" / "monthly.csv").exists()
        with (root / "conc" / "holdings.csv").open(encoding="utf-8", newline="") as f:
            assert max(float(row["weight"]) for row in csv.DictReader(f)) <= 0.5000001
        with (root / "monster" / "monthly.csv").open(encoding="utf-8", newline="") as f:
            first_month = next(csv.DictReader(f))
            assert float(first_month["gross_return"]) > 0.0
        with (root / "monster" / "holdings.csv").open(encoding="utf-8", newline="") as f:
            first_holding = next(csv.DictReader(f))
            assert "theme_event_risk_sensitivity_max" in first_holding
            assert "theme_structural_growth_max" in first_holding


def test_latest_diagnostics_sidecars() -> None:
    import argparse

    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        latest = root / "latest"
        reports = latest / "reports"
        reports.mkdir(parents=True, exist_ok=True)
        scored_fields = [
            "ticker",
            "Name",
            "sector",
            "score",
            "portfolio_sleeve_label",
            "portfolio_candidate_gate_label",
            "portfolio_monster_early_score",
            "portfolio_stale_mega_leader_score",
            "portfolio_risk_entry_block_score",
            "rs_acceleration_score",
            "ownership_flow_pillar_score",
            "insider_cluster_boost_score",
            "event_revision_pillar_score",
            "event_reaction_score",
            "live_event_growth_reentry_score",
            "live_event_risk_score",
        ]
        rows = [
            {
                "ticker": "AAA",
                "Name": "AAA",
                "sector": "Tech",
                "score": 5,
                "portfolio_sleeve_label": "future_winner",
                "portfolio_candidate_gate_label": "keep",
                "portfolio_monster_early_score": 0.72,
                "portfolio_stale_mega_leader_score": 0.0,
                "portfolio_risk_entry_block_score": 0.1,
                "rs_acceleration_score": 0.8,
                "ownership_flow_pillar_score": 0.8,
                "insider_cluster_boost_score": 0.4,
                "event_revision_pillar_score": 0.7,
                "event_reaction_score": 0.5,
                "live_event_growth_reentry_score": 0.4,
                "live_event_risk_score": 0.0,
            },
            {
                "ticker": "BBB",
                "Name": "BBB",
                "sector": "Tech",
                "score": 4,
                "portfolio_sleeve_label": "unassigned",
                "portfolio_candidate_gate_label": "rejected",
                "portfolio_monster_early_score": 0.2,
                "portfolio_stale_mega_leader_score": 0.8,
                "portfolio_risk_entry_block_score": 0.8,
                "rs_acceleration_score": -1.0,
            },
        ]
        latest.mkdir(parents=True, exist_ok=True)
        with (latest / "scored_latest.csv").open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=scored_fields)
            writer.writeheader()
            writer.writerows(rows)
        with (latest / "portfolio_latest.csv").open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["ticker", "weight"])
            writer.writeheader()
            writer.writerow({"ticker": "AAA", "weight": 0.1})
        with (latest / "concentrated_portfolio_latest.csv").open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["ticker", "weight"])
            writer.writeheader()
            writer.writerow({"ticker": "CCC", "weight": 0.3})
        leader_payload = leader_drop_run(
            argparse.Namespace(latest_run=str(latest), output_dir=str(reports), watchlist="INTC", force=True)
        )
        governance_payload = governance_report_run(
            argparse.Namespace(latest_run=str(latest), output_dir=str(root / "governance"), top_n=10, watchlist="INTC")
        )
        assert leader_payload["rows"] == 3
        assert (reports / "leader_drop_diagnostics_latest.csv").exists()
        assert governance_payload["status"] == "completed"
        assert (root / "governance" / "governance_catalyst_latest.csv").exists()


def test_weight_caps_and_return_column_fallback() -> None:
    rows = [{"ticker": "AAA", "score": 100.0}, {"ticker": "BBB", "score": 1.0}]
    weights = score_power_weights(rows, "score", single_name_cap=0.5)
    assert max(weights.values()) <= 0.5000001

    cfg = EngineConfig(concentrated_max_single_name_weight=0.50)
    import pandas as pd

    selected = pd.DataFrame(
        [
            {"ticker": "AAA", "concentrated_score": 10.0, "score": 10.0},
            {"ticker": "BBB", "concentrated_score": 1.0, "score": 1.0},
        ]
    )
    prod_weights = concentrated_weight_map(cfg, selected, "winner_take_all")
    assert max(prod_weights.values()) <= 0.5000001

    frame = pd.DataFrame({"period_forward_return": [float("nan")], "y_blend": [0.12]})
    assert infer_return_col(frame) == "y_blend"


if __name__ == "__main__":
    test_historical_challenger_replays()
    test_latest_diagnostics_sidecars()
    test_weight_caps_and_return_column_fallback()
    print("historical_challenger_replays_smoke: ok")
