"""r1000 Quant Engine — configuration constants.

This module owns module-level DATA constants that were previously defined in
`r1000_top30_institutional.py`. During Refactor Phase A (2026-04-20 onwards)
these are being extracted in stages so the monolith can shrink without
changing behaviour.

Stage 1a (this commit): PHASE*_COLUMNS whitelists for feature_store
keep_cols / hard_sanitize. Pure data — no engine logic here.

Import discipline
-----------------
This module must NEVER import anything from `r1000_top30_institutional`,
`r1000_data_collector`, `r1000_operator`, or `r1000_portfolio_state`.
It contains pure data + stdlib imports only so the dependency graph is
unambiguous:

    r1000_config.py  (pure data)
        ^
        |
    r1000_top30_institutional.py  (imports r1000_config)
    r1000_data_collector.py       (imports r1000_top30_institutional)
    r1000_operator.py             (imports r1000_top30_institutional)

Any new pure-data constant added to the engine should land HERE, not in
the main file. See REFACTOR_PLAN.md §6 migration checklist + §11.3
COLUMN_OWNERSHIP registry for the full invariant.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional


# =====================================================================
# Phase 2 (2026-04-16): industry-level relative strength + O'Neil / IBD
# =====================================================================
# leadership + industry-rotation signal. These columns are attached to the
# monthly frame inside `build_universe_monthly` via
#   attach_industry_metadata -> add_industry_relative_strength
#   -> compute_oneil_leadership_score -> add_industry_rotation_signal
# They are NOT re-derived later in the latest-scoring path (unlike Phase 1
# blueprint columns, which are recomputed via compute_strategy_blueprint_columns
# at score_latest_month / prepare_latest_scored_data). Therefore they MUST be
# whitelisted in `build_feature_store.keep_cols`, otherwise:
#   (1) they get dropped from feature_store_latest.parquet, and
#   (2) every walk-forward iteration sees them as missing -> sleeve composites
#       at compute_dual_sleeve_composite_scores silently fall back to 0.0 via
#       numeric_series_or_default, effectively zeroing out Phase 2's
#       contribution to the historical backtest AND the latest scored export.
# Keep this list in sync with the zero-placeholder block in
# `build_universe_monthly` under `if not phase_is_enabled("phase2_industry"): ...`.
PHASE2_INDUSTRY_COLUMNS = [
    # yfinance metadata (string-typed)
    "industry",
    "industry_group",
    "subindustry",
    # industry / industry-group relative strength
    "rs_industry_1m",
    "rs_industry_3m",
    "rs_industry_6m",
    "rs_industry_12m",
    "rs_industry_group_1m",
    "rs_industry_group_3m",
    "rs_industry_group_6m",
    "rs_industry_group_12m",
    # group-mean momentum (used to derive RS above; keep for diagnostics)
    "industry_mom_mean_3m",
    "industry_mom_mean_6m",
    "industry_mom_mean_12m",
    "industry_group_mom_mean_3m",
    "industry_group_mom_mean_6m",
    "industry_group_mom_mean_12m",
    # breadth within (sub)industry / group
    "industry_breadth_above_ma200",
    "industry_group_breadth_above_ma200",
    # O'Neil / IBD leadership composites
    "industry_group_strength_score",
    "industry_within_leader_rank",
    "oneil_leadership_score",
    # rotation (acceleration of group RS vs benchmark)
    "industry_rotation_signal",
]


# =====================================================================
# Phase 5: sub-industry leader/laggard pair signals (PHASE_ROADMAP §2.5).
# =====================================================================
# Three numeric columns produced by `add_sub_industry_leader_laggard_signals`
# during `build_universe_monthly`, right after `compute_oneil_leadership_score`.
# Like Phase 2's industry metadata, these columns are NOT re-derived
# inside `score_latest_month` / `prepare_latest_scored_data` - they must
# survive the feature_store whitelist (Invariant #8 in PHASE_ROADMAP §5),
# so this list is appended to `build_feature_store.keep_cols`.
# Keep in sync with the zero-placeholder block in `build_universe_monthly`
# under `if not phase_is_enabled("phase5_leader_laggard"): ...`.
PHASE5_LEADER_LAGGARD_COLUMNS = [
    "industry_leader_gap",           # (top-quartile mean - median) / std within industry_group
    "industry_leader_bonus_score",   # positive bonus for top-quartile in a clearly-separated strong group
    "industry_laggard_penalty_score",# symmetric penalty for bottom-quartile in the same strong group
]


# =====================================================================
# Phase 1 (turnaround / value / uptrend alpha) - keep_cols survival list.
# =====================================================================
# Original Phase 1 (2026-04-16 12:27 KST commit `d464e9d`) added 5 new
# cross-sectional alpha columns via `compute_strategy_blueprint_columns`.
# That helper is re-invoked on `latest_df` at `score_latest_month` and
# `prepare_latest_scored_data`, so Phase 1 columns show up in
# `scored_latest.csv` via the latest-scoring path.
#
# BUT - `compute_strategy_blueprint_columns` inside `build_feature_store`
# runs BEFORE the `keep_cols = [...]` whitelist at line ~13900, and the
# whitelist did not list these 5 columns. Result: Phase 1 signal was
# silently dropped from `feature_store_latest.parquet` and therefore
# absent from every walk-forward training row across 83 months.
# Factor IC measurement on 2026-04-17 confirmed the columns are missing
# from `scored_oos_latest.parquet` (see DIAGNOSIS_FACTOR_IC.md).
#
# This is the exact same class of bug as the Phase 2 keepcols-fix
# (commit `1d4fb40`, 2026-04-16). Fix: list the 5 columns here and
# append to `build_feature_store.keep_cols`, plus bump
# `ENGINE_REUSE_VERSION` so the feature_store is regenerated with
# Phase 1 columns included.
PHASE1_ALPHA_COLUMNS = [
    "fundamental_turnaround_acceleration_score",  # loss->profit sign flip + loss-narrowing + under-loss CF growth
    "cashflow_inflection_under_loss_score",       # OCF/FCF turning positive while NI still negative (Lynch/O'Neil)
    "value_inflection_score",                     # cheap val + earnings catching up + Stage-1->2 setup with quality floor
    "uptrend_continuation_score",                 # 52w-high + full MA-stack + intact mom + intact earnings
    "uptrend_breakdown_penalty",                  # fires when strong names lose MA50/MA200, gap-down on earnings, etc.
]


# =====================================================================
# Phase 8b.1: long-lookback momentum (PHASE_8_PROPOSAL.md).
# =====================================================================
# Factor IC analysis (DIAGNOSIS_FACTOR_IC.md) revealed the current
# engine caps momentum at mom_12m, leaving multi-year winners
# (NVDA 2021-2024, AVGO 2018-2025, MU 2020-2024) cross-sectionally
# equivalent to 12-month-only rallies. Fundamental factor IC is
# 2-4x stronger at r_12m than r_1m, implying long-horizon momentum
# should also matter. Added:
#   mom_18m / mom_24m / mom_36m  raw price pct-change (1y, 2y, 3y)
#   multi_year_winner_score      blend 0.5*z(mom_12m) + 0.8*z(mom_24m)
#                                + 0.6*z(mom_36m), winsorised [-6,6].
#                                Zero-masked where mom_24m is NaN.
#   persistence_trend_24m        binary flag for mom_12m>0.15 AND
#                                mom_24m>0.30 AND mom_36m>0.50
# Toggle: PHASE_PHASE8B_LONG_LOOKBACK_ENABLED + cfg flag.
PHASE8B_LONG_LOOKBACK_COLUMNS = [
    "mom_18m",
    "mom_24m",
    "mom_36m",
    "multi_year_winner_score",
    "persistence_trend_24m",
]


# =====================================================================
# Phase 9 C3: EPS / profitability turn-positive flags exposed to feature
# store so Phase 9 C2 early-scout gate can admit names via explicit
# Q-over-Q sign transition (user definition: "early 는 eps 적자거나
# 양전환 막 하거나"). Design in PHASE_9_C3_PROPOSAL.md.
#
# Two column classes bundled here:
#   (a) 4 NEW user-facing aliases + 1 NEW roe sign-flip flag:
#       profit_turn_positive_4q, cashflow_turn_positive_4q,
#       roe_turn_positive_4q, any_profitability_turn_positive_4q,
#       roe_sign_flip_pos
#   (b) 3 EXISTING-BUT-UNEXPOSED continuous scores from fund_panel that
#       never survived the old keep_cols filter:
#       ocf_under_loss_growth, fcf_under_loss_growth, ni_loss_narrowing_4q
#
# ENGINE_REUSE_VERSION bump required because feature_store parquet
# schema gains these 8 columns. One FULL REBUILD needed per machine.
# =====================================================================
# Phase 14 (2026-04-25): hybrid alpha — production wire of validated
# Aggressive scanner signals into 정석 ML feature set.
# =====================================================================
# Sources (commit history):
#   2e5fc19 — Opus H1/H6 multipliers in aggressive/scanner.py
#   6fd6afe — Stage 2 breakout overextension penalty in aggressive/scanner.py
#   d62fbb6 — themes.yaml expanded + theme_phase_multiplier numeric mapping
#   1d04f78 — T4 RS Acceleration validated +10% alpha audit
#
# These signals were proven in research / Aggressive scanner side. Phase 14
# adds them to the 정석 production ML feature set so the walk-forward model
# learns optimal weights against r_*m forward returns. ENGINE_REUSE_VERSION
# bump REQUIRED — feature_store schema gains 6 columns. One FULL REBUILD
# needed per machine.
PHASE14_HYBRID_ALPHA_COLUMNS = [
    "rs_acceleration_score",                # T4 +10% alpha (90d, 24mo backtest)
    "h1_oversold_value_score",              # Opus H1 +8.67% (n=1149, p<0.0001)
    "h6_dynamic_leader_score",              # Opus H6 +7.38% (n=704, p<0.0001)
    "stage2_overext_penalty",               # T1 -2.5% alpha protection
    "theme_phase_multiplier_primary",       # themes.yaml phase classifier (primary)
    "theme_phase_multiplier_max",           # themes.yaml phase classifier (max across themes)
]

# Phase 15-A (2026-04-28) cycle-leader rescue + earnings-revision catalyst.
# Two new ML features that target the gap exposed by the SHIPPED Phase 14
# scored_latest.csv: SNDK rank 37/595 score 3.69 was completely unassigned
# (sleeve=unassigned) because multi_year_winner_score=0 from sitting at the
# memory cycle bottom. ENGINE_REUSE_VERSION bump REQUIRED — feature_store
# schema gains 2 columns. One FULL REBUILD per machine.
PHASE15_ALPHA_COLUMNS = [
    "cycle_recovery_score",                 # cycle bottom + 6m turn + EPS sign flip
    "eps_revision_score",                   # forward EPS estimate change (analyst upgrade catalyst)
    "early_cycle_inflection_score",         # 6mo-pre-breakout detector — find next SNDK/MU early
]


PHASE9_C3_TURNAROUND_COLUMNS = [
    "profit_turn_positive_4q",
    "cashflow_turn_positive_4q",
    "roe_turn_positive_4q",
    "any_profitability_turn_positive_4q",
    "roe_sign_flip_pos",
    "ocf_under_loss_growth",
    "fcf_under_loss_growth",
    "ni_loss_narrowing_4q",
    # Phase 15-A wiring fix (2026-04-28): the ni/op/ocf/fcf sign-flip flags
    # are produced by compute_fundamental_trend_features but were missing
    # from the keep_cols whitelist, so they got dropped before reaching
    # scored_latest.csv. Phase 15-A cycle_recovery_score and Phase 15-B
    # early_cycle_inflection_score both read any_profit_sign_flip_pos as
    # their EPS-turn condition. Adding the underlying flags ensures the
    # signals survive build_feature_store and reach the ML feature set.
    "any_profit_sign_flip_pos",
    "ni_sign_flip_pos",
    "op_income_sign_flip_pos",
    "ocf_sign_flip_pos",
    "fcf_sign_flip_pos",
    "gp_sign_flip_pos",
]

# =====================================================================
# Stage 1b (2026-04-20): column whitelists + macro/event/sleeve data
# =====================================================================
# Extracted from r1000_top30_institutional.py lines 399-1173 (pre-move).
# 35 constants, ~770 lines. Pure data; no helpers, no EngineConfig deps.
# Kept in original declaration order to preserve local inter-dependencies
# (DEFAULT_FEATURES references MACRO_REGIME_COLUMNS etc.;
#  HISTORICAL_FUNDAMENTAL_HISTORY_COLUMNS references 4 earlier HISTORICAL_*).


CRISIS_SECTOR_BENEFICIARIES = {
    "war_oil_rate_shock": {"Energy": 0.85, "Industrials": 0.40},
    "systemic_crisis": {"Health Care": 0.60, "Consumer Staples": 0.70, "Utilities": 0.65},
    "stagflation": {"Energy": 0.70, "Materials": 0.50, "Consumer Staples": 0.45},
    "carry_unwind": {"Consumer Staples": 0.50, "Health Care": 0.45, "Utilities": 0.55},
}

CORE_FUNDAMENTAL_COLUMNS = [
    "shares",
    "assets",
    "liabilities",
    "revenues",
    "cost_of_revenue",
    "gross_profit",
    "op_income",
    "net_income",
    "ocf",
    "capex",
    "revenues_ttm",
    "cost_of_revenue_ttm",
    "gross_profit_ttm",
    "op_income_ttm",
    "net_income_ttm",
    "ocf_ttm",
    "capex_ttm",
]

MACRO_PRICE_TICKERS = {
    "spy": "SPY",
    "qqq": "QQQ",
    "smh": "SMH",
    "gld": "GLD",
    "slv": "SLV",
    "cper": "CPER",
    "dba": "DBA",
    "uso": "USO",
    "ung": "UNG",
}

MACRO_FRED_SERIES = {
    "vix": "VIXCLS",
    "dgs10": "DGS10",
    "dxy": "DTWEXBGS",
    "m2": "M2SL",
    "fed_assets": "WALCL",
    "reverse_repo": "RRPTSYD",
    "tga": "WDTGAL",
    "sp500": "SP500",
    "hy_oas": "BAMLH0A0HYM2",
    "cpi": "CPIAUCSL",
    "core_cpi": "CPILFESL",
    "ppi": "PPIFDG",
    "unrate": "UNRATE",
    "sahm": "SAHMREALTIME",
}

CNN_FEAR_GREED_URL = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
CNN_FEAR_GREED_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.cnn.com/markets/fear-and-greed",
    "Origin": "https://www.cnn.com",
}

ROBUST_Z_WINSOR_P = 0.01
ROBUST_Z_CLIP = 6.0

MACRO_REGIME_COLUMNS = [
    "spy_ret_1m",
    "spy_ret_3m",
    "spy_above_ma200",
    "qqq_rel_spy_1m",
    "smh_rel_spy_1m",
    "vix_z_63d",
    "vix_change_1m",
    "dgs10_change_1m",
    "hy_oas_level",
    "hy_oas_change_1m",
    "dxy_ret_1m",
    "dba_ret_1m",
    "gld_ret_1m",
    "slv_ret_1m",
    "cper_ret_1m",
    "uso_ret_1m",
    "ung_ret_1m",
    "m2_yoy_lag1m",
    "cpi_yoy",
    "core_cpi_yoy",
    "cpi_3m_ann",
    "ppi_yoy",
    "ppi_cpi_gap",
    "unrate_level",
    "unrate_3m_change",
    "sahm_realtime",
    "fed_assets_bil",
    "reverse_repo_bil",
    "tga_bil",
    "net_liquidity_bil",
    "fed_assets_change_1m_bil",
    "reverse_repo_change_1m_bil",
    "tga_change_1m_bil",
    "net_liquidity_change_1m_bil",
    "liquidity_impulse_score",
    "liquidity_drain_score",
    "fear_greed_score",
    "fear_greed_delta_1w",
    "fear_greed_risk_off_score",
    "fear_greed_risk_on_score",
    "macro_risk_off_score",
    "market_regime_score",
    "inflation_pressure_score",
    "liquidity_regime_score",
    "inflation_reacceleration_score",
    "upstream_cost_pressure_score",
    "labor_softening_score",
    "stagflation_score",
    "growth_liquidity_reentry_score",
]

MACRO_INTERACTION_COLUMNS = [
    "macro_beta_vix_interaction",
    "macro_duration_rate_interaction",
    "macro_tech_leadership_interaction",
    "macro_semis_cycle_interaction",
    "macro_energy_oil_interaction",
    "macro_materials_copper_interaction",
    "macro_defensive_riskoff_interaction",
    "macro_momentum_regime_interaction",
]

DYNAMIC_LEADER_COLUMNS = [
    "sector_leader_score",
    "within_sector_leader_score",
    "leader_emergence_score",
    "leader_safety_score",
    "dynamic_leader_score",
]

MOAT_PROXY_COLUMNS = [
    "size_saturation_score",
    "pricing_power_score",
    "durability_proxy_score",
    "dominance_proxy_score",
    "moat_proxy_score",
]

TREND_TEMPLATE_COLUMNS = [
    "price_above_ma20",
    "ma20_above_ma50",
    "price_above_ma150",
    "ma50_above_ma150",
    "ma150_above_ma200",
    "golden_cross_fresh_20d",
    "death_cross_recent_20d",
    "near_52w_high_pct",
    "ma200_slope_1m",
    "breakout_distance_63d",
    "breakout_fresh_20d",
    "breakout_volume_z",
    "volume_dryup_20d",
    "volatility_contraction_score",
    "atr14_pct",
    "post_breakout_hold_score",
]

MARKET_ADAPTATION_COLUMNS = [
    "market_breadth_above_ma200",
    "market_breadth_above_ma150",
    "market_trend_template_ratio",
    "market_near_high_ratio",
    "market_sector_participation",
    "market_leadership_narrowing",
    "market_overheat_ratio",
    "market_breadth_regime_score",
]

BENCHMARK_RELATIVE_COLUMNS = [
    "bench_ret_1m",
    "bench_ret_3m",
    "bench_ret_6m",
    "bench_ret_12m",
    "bench_dd_1y",
    "rs_benchmark_3m",
    "rs_benchmark_6m",
    "rs_benchmark_12m",
    "dd_gap_benchmark",
]

REGIME_ROTATION_COLUMNS = [
    "systemic_crisis_score",
    "carry_unwind_stress_score",
    "war_oil_rate_shock_score",
    "defensive_rotation_score",
    "growth_reentry_score",
]

LIVE_EVENT_ALERT_COLUMNS = [
    "live_event_risk_score",
    "live_event_systemic_score",
    "live_event_war_oil_rate_score",
    "live_event_defensive_score",
    "live_event_growth_reentry_score",
]

FUND_TTM_FALLBACK_COLUMNS = [
    "revenues_ttm",
    "gross_profit_ttm",
    "op_income_ttm",
    "net_income_ttm",
    "ocf_ttm",
    "capex_ttm",
    "asset_growth_yoy",
    "sales_growth_yoy",
    "sales_cagr_1y", "sales_cagr_2y", "sales_cagr_3y", "sales_cagr_5y", "sales_cagr_best",
    "op_income_growth_yoy",
    "op_income_cagr_1y", "op_income_cagr_2y", "op_income_cagr_3y", "op_income_cagr_5y", "op_income_cagr_best",
    "net_income_growth_yoy",
    "net_income_cagr_1y", "net_income_cagr_2y", "net_income_cagr_3y", "net_income_cagr_5y", "net_income_cagr_best",
    "ocf_growth_yoy",
    "ocf_cagr_1y", "ocf_cagr_2y", "ocf_cagr_3y", "ocf_cagr_5y", "ocf_cagr_best",
    "eps_cagr_1y", "eps_cagr_2y", "eps_cagr_3y", "eps_cagr_5y", "eps_cagr_best",
    "fcf_cagr_1y", "fcf_cagr_2y", "fcf_cagr_3y", "fcf_cagr_5y", "fcf_cagr_best",
    "gp_to_assets_ttm",
    "op_margin_ttm",
    "margin_stability_8q",
    "accruals_to_assets",
    "debt_to_equity",
    "debt_to_equity_delta_4q",
    "roe_proxy",
    "roe_trend_4q",
    "shares_yoy",
    "fund_history_quarters_available",
]

DEFAULT_FEATURES = [
    "mom_1m",
    "mom_3m",
    "mom_6m",
    "mom_12m",
    # Phase 8b.1: long-lookback momentum for multi-year-trend detection.
    "mom_18m",
    "mom_24m",
    "mom_36m",
    "multi_year_winner_score",
    "persistence_trend_24m",
    # Phase 1 alpha signals — blueprint-class composites. Added to
    # DEFAULT_FEATURES on 2026-04-17 (Phase 8 final audit) because every
    # other blueprint composite (strategy_blueprint_score, revision_blueprint_score,
    # moat_quality_blueprint_score, etc.) is already here, and now that
    # the Phase 8b.3 keepcols fix ensures these 5 columns reach
    # feature_store_latest.parquet, the walk-forward ML should use
    # them as model inputs. Previous omission was an artefact of the
    # keep_cols bug that dropped Phase 1 columns from feature_store.
    "fundamental_turnaround_acceleration_score",
    "cashflow_inflection_under_loss_score",
    "value_inflection_score",
    "uptrend_continuation_score",
    "uptrend_breakdown_penalty",
    "dist_ma200",
    "price_above_ma20",
    "price_above_ma50",
    "price_above_ma200",
    "ma20_above_ma50",
    "ma50_above_ma200",
    "price_above_ma150",
    "ma50_above_ma150",
    "ma150_above_ma200",
    "golden_cross_fresh_20d",
    "death_cross_recent_20d",
    "trend_template_full",
    "trend_template_relaxed",
    "high_tight_30_bonus",
    "near_52w_high_pct",
    "ma200_slope_1m",
    "breakout_distance_63d",
    "breakout_fresh_20d",
    "breakout_volume_z",
    "volume_dryup_20d",
    "volatility_contraction_score",
    "atr14_pct",
    "post_breakout_hold_score",
    "rsi14",
    "macd_hist",
    "bb_pb",
    "obv_trend",
    "vol_252d",
    "dd_1y",
    "dollar_vol_20d",
    "ep_ttm",
    "sp_ttm",
    "fcfy_ttm",
    "forward_pe_final",
    "peg_final",
    "forward_ps_final",
    "op_margin_ttm",
    "gp_to_assets_ttm",
    "return_on_equity_effective",
    "roa_proxy",
    "asset_turnover_ttm",
    "book_to_market_proxy",
    "roe_trend_4q",
    "debt_to_equity",
    "debt_to_equity_delta_4q",
    "sales_growth_yoy",
    "sales_cagr_1y", "sales_cagr_2y", "sales_cagr_3y", "sales_cagr_5y", "sales_cagr_best",
    "op_income_cagr_1y", "op_income_cagr_2y", "op_income_cagr_3y", "op_income_cagr_5y", "op_income_cagr_best",
    "net_income_cagr_1y", "net_income_cagr_2y", "net_income_cagr_3y", "net_income_cagr_5y", "net_income_cagr_best",
    "ocf_cagr_1y", "ocf_cagr_2y", "ocf_cagr_3y", "ocf_cagr_5y", "ocf_cagr_best",
    "asset_growth_yoy",
    "shares_yoy",
    "eps_growth_yoy",
    "eps_cagr_1y", "eps_cagr_2y", "eps_cagr_3y", "eps_cagr_5y", "eps_cagr_best",
    "fcf_growth_yoy",
    "fcf_cagr_1y", "fcf_cagr_2y", "fcf_cagr_3y", "fcf_cagr_5y", "fcf_cagr_best",
    "dividend_policy_score",
    "garp_score",
    "capital_efficiency_score",
    "sector_adjusted_quality_score",
    "fundamental_presence_score",
    "fundamental_reliability_score",
    "margin_stability_8q",
    "accruals_to_assets",
    "earn_gap_1d",
    "rs_sector_6m",
    "rev_growth_accel_4q",
    "margin_trend_4q",
    "ocf_ni_quality_4q",
    "forward_value_score",
    "revision_score",
    "quality_trend_score",
    "event_reaction_score",
    "moat_proxy_score",
    "profitability_inflection_score",
    "anticipatory_growth_score",
    "archetype_emerging_growth_score",
    "archetype_compounder_score",
    "archetype_cyclical_recovery_score",
    "archetype_defensive_value_score",
    "archetype_alignment_score",
    "future_winner_scout_score",
    "long_hold_compounder_score",
    "revision_blueprint_score",
    "growth_blueprint_score",
    "valuation_blueprint_score",
    "moat_quality_blueprint_score",
    "technical_blueprint_score",
    "macro_hedge_score",
    "strategy_blueprint_score",
    # SAGE: Sector-Adaptive Growth Engine
    "sage_composite_score",
    "sage_g_score",
    "sage_v_score",
    "sage_q_score",
    "sage_c_score",
    "rule_of_40",
    "fcf_margin",
    "net_margin",
    "gross_margin_ttm",
    "roic_approx",
    "sbc_to_revenue",
    "dilution_penalty",
    "val_residual_ep",
    "val_residual_sp",
    "val_residual_fcfy",
] + MACRO_REGIME_COLUMNS + MACRO_INTERACTION_COLUMNS + DYNAMIC_LEADER_COLUMNS + MARKET_ADAPTATION_COLUMNS + BENCHMARK_RELATIVE_COLUMNS + REGIME_ROTATION_COLUMNS + LIVE_EVENT_ALERT_COLUMNS + PHASE14_HYBRID_ALPHA_COLUMNS + PHASE15_ALPHA_COLUMNS

PILLAR_SCORE_COLUMNS = [
    "institutional_flow_actual_score",
    "insider_flow_actual_score",
    "institutional_flow_signal_score",
    "insider_flow_signal_score",
    "ownership_flow_pillar_score",
    "fundamental_pillar_score",
    "technical_pillar_score",
    "event_revision_pillar_score",
    "macro_pillar_score",
    "compounder_pillar_score",
    "multidimensional_breadth_score",
    "multidimensional_confirmation_score",
]

FUNDAMENTAL_COVERAGE_COLUMNS = [
    "accepted",
    "shares",
    "assets",
    "liabilities",
    "revenues_ttm",
    "gross_profit_ttm",
    "op_income_ttm",
    "net_income_ttm",
    "ep_ttm",
    "sp_ttm",
    "fcfy_ttm",
    "op_margin_ttm",
    "roe_proxy",
    "return_on_equity_effective",
    "roa_proxy",
    "asset_turnover_ttm",
    "book_to_market_proxy",
    "forward_pe_final",
    "peg_final",
    "capital_efficiency_score",
    "sector_adjusted_quality_score",
    "dividend_yield_ttm",
    "dividend_payout_ratio",
    "dividend_policy_score",
    "garp_score",
    "fundamental_presence_score",
    "fundamental_reliability_score",
    "sales_growth_yoy",
    "net_income_growth_yoy",
    "op_income_growth_yoy",
    "ocf_growth_yoy",
    "sales_cagr_3y",
    "sales_cagr_5y",
    "op_income_cagr_3y",
    "op_income_cagr_5y",
    "net_income_cagr_3y",
    "net_income_cagr_5y",
    "ocf_cagr_3y",
    "ocf_cagr_5y",
    "gross_margins",
    "operating_margins",
    "asset_growth_yoy",
    "fund_history_quarters_available",
    "accruals_to_assets",
    "earn_gap_1d",
    "rs_sector_6m",
]

SEC_13F_COLUMNS = [
    "sec13f_holders_count",
    "sec13f_shares",
    "sec13f_value",
    "sec13f_delta_shares",
    "sec13f_delta_value",
]

SEC_FORM345_COLUMNS = [
    "sec_form345_txn_count",
    "sec_form345_buy_shares",
    "sec_form345_sell_shares",
    "sec_form345_net_shares",
    "sec_form345_buy_ratio",
]

LATEST_ONLY_SIGNAL_COLUMNS = [
    "forward_pe",
    "peg_ratio",
    "trailing_pe",
    "price_to_sales",
    "market_cap_live",
    "target_mean_price",
    "target_median_price",
    "recommendation_mean",
    "earnings_growth",
    "revenue_growth",
    "gross_margins",
    "operating_margins",
    "return_on_equity_live",
    "free_cashflow_live",
    "current_price_live",
    "av_forward_pe",
    "av_peg_ratio",
    "av_trailing_pe",
    "av_price_to_sales",
    "av_ev_to_ebitda",
    "av_profit_margin",
    "av_operating_margin",
    "av_return_on_equity",
    "av_quarterly_earnings_growth_yoy",
    "av_quarterly_revenue_growth_yoy",
    "eps_est_q_next",
    "rev_est_q_next",
    "eps_est_fy1",
    "rev_est_fy1",
    "eps_est_fy2",
    "rev_est_fy2",
    "eps_revision_proxy",
    "forward_pe_final",
    "ev_to_ebitda_final",
    "peg_final",
    "target_upside_pct",
    "analyst_coverage_proxy",
    "earnings_growth_final",
    "revenue_growth_final",
    "forward_value_score",
    "revision_score",
    "institutional_holders_count",
    "institutional_holders_shares",
    "institutional_holders_value",
    "mutualfund_holders_count",
    "mutualfund_holders_shares",
    "mutualfund_holders_value",
    "insider_txn_count",
    "insider_buy_shares",
    "insider_sell_shares",
    "insider_net_shares",
    "insider_buy_ratio",
    "institutional_ownership_proxy",
    "institutional_holding_intensity",
    "insider_net_shares_ratio",
    "insider_buy_ratio_final",
    "insider_txn_count_final",
    "institutional_count_final",
    "institutional_flow_score",
    "insider_flow_score",
]

# Keep/export coverage uses the broader latest-only list above because some of those
# columns are repaired or re-derived from PIT-safe inputs later in the pipeline.
# Acceptance checks, however, should only flag raw latest/live inputs that should
# never leak into historical rows.
LATEST_ONLY_ACCEPTANCE_COLUMNS = [
    "forward_pe",
    "peg_ratio",
    "trailing_pe",
    "price_to_sales",
    "target_mean_price",
    "target_median_price",
    "recommendation_mean",
    "earnings_growth",
    "revenue_growth",
    "return_on_equity_live",
    "free_cashflow_live",
    "av_forward_pe",
    "av_peg_ratio",
    "av_trailing_pe",
    "av_price_to_sales",
    "av_ev_to_ebitda",
    "av_profit_margin",
    "av_operating_margin",
    "av_return_on_equity",
    "av_quarterly_earnings_growth_yoy",
    "av_quarterly_revenue_growth_yoy",
    "eps_est_q_next",
    "rev_est_q_next",
    "eps_est_fy1",
    "rev_est_fy1",
    "eps_est_fy2",
    "rev_est_fy2",
    "eps_revision_proxy",
    "institutional_holders_count",
    "institutional_holders_shares",
    "institutional_holders_value",
    "mutualfund_holders_count",
    "mutualfund_holders_shares",
    "mutualfund_holders_value",
    "insider_txn_count",
    "insider_buy_shares",
    "insider_sell_shares",
    "insider_net_shares",
    "insider_buy_ratio",
]

ACTUAL_PRIORITY_COLUMNS = [
    "actual_report_age_days_latest",
    "actual_report_age_days",
    "actual_report_available",
    "actual_priority_weight",
    "proxy_fallback_weight",
    "actual_results_score",
]

# Phase 1/2/5/8b/9C3 column whitelists now live in r1000_config.py
# (Refactor Phase A Stage 1a, 2026-04-20). Import occurs at file top.



# =====================================================================
# Phase 4: regime-conditional sleeve multipliers (PHASE_ROADMAP §2.4).
# =====================================================================
# Maps a confirmed regime label -> per-sleeve multiplicative scalar that
# is applied to the final `core_score` / `future_score` / `early_score`
# inside `compute_portfolio_sleeve_columns` AFTER Phase 3 composition
# and BEFORE the sparse-history penalty subtraction.
#
# Design rationale:
#  - growth_reentry: lean into future_winner (1.30) and early_scout (1.15);
#    core keeps a mild boost (1.10) because compounders still compound.
#  - balanced: identity (1.00/1.00/1.00), i.e. legacy behaviour.
#  - stagflation: tilt away from future_winner (growth multiples compress),
#    preserve core defensive compounders lightly, rotate into early_scout
#    (industry rotation, value inflections).
#  - systemic_crisis: deep de-emphasis on core (0.55) — long-duration
#    compounders de-rate hardest — and future_winner (0.70); early_scout
#    gets the biggest boost (1.30) because value-inflection / turnaround
#    scout signals dominate when the tide goes out.
#  - carry_unwind: moderate de-risk across all sleeves, early benefits
#    from macro vol mean reversion setups.
#  - war_oil_rate_shock: less severe than systemic_crisis, mild
#    de-risk; early_scout unchanged — rotation into energy / materials
#    is captured through industry_rotation_signal.
#
# Any regime label NOT present here is treated as identity {1.0, 1.0, 1.0}
# by `_resolve_regime_sleeve_multipliers` so forward-compatibility with
# future regime labels is automatic.
SLEEVE_FACTOR_REGIME_MULTIPLIERS: dict[str, dict[str, float]] = {
    "growth_reentry":     {"core": 1.10, "future": 1.30, "early": 1.15},
    "balanced":           {"core": 1.00, "future": 1.00, "early": 1.00},
    "stagflation":        {"core": 0.85, "future": 0.90, "early": 1.15},
    "systemic_crisis":    {"core": 0.55, "future": 0.70, "early": 1.30},
    "carry_unwind":       {"core": 0.75, "future": 0.80, "early": 1.10},
    "war_oil_rate_shock": {"core": 0.80, "future": 0.85, "early": 1.05},
}
# Per-sleeve [min, max] clamp applied to the multiplier after user
# override merge. This is a belt-and-suspenders guard — if somebody
# accidentally puts 10.0 or -5.0 into their custom table we don't want
# the composite to explode. Treat [0.4, 1.6] as the sane operational
# band; extreme regimes are already at 0.55 / 1.30 in the built-in map.
SLEEVE_FACTOR_REGIME_MULTIPLIER_CLAMP: tuple[float, float] = (0.40, 1.60)


SATELLITE_ONLY_FEATURE_COLUMNS = [
    "forward_value_score",
    "revision_score",
    "institutional_flow_score",
    "insider_flow_score",
    "fear_greed_score",
    "fear_greed_delta_1w",
    "fear_greed_risk_off_score",
    "fear_greed_risk_on_score",
]

CRITICAL_TTM_COVERAGE_COLUMNS = [
    "revenues_ttm",
    "net_income_ttm",
    "op_margin_ttm",
]

CRITICAL_VALUATION_COVERAGE_COLUMNS = [
    "ep_ttm",
    "sp_ttm",
    "fcfy_ttm",
]

COMPREHENSIVE_FUNDAMENTAL_COVERAGE_COLUMNS = [
    "shares",
    "assets",
    "liabilities",
    "revenues_ttm",
    "gross_profit_ttm",
    "op_income_ttm",
    "net_income_ttm",
    "ocf_ttm",
    "capex_ttm",
    "sales_growth_yoy",
    "net_income_growth_yoy",
    "op_income_growth_yoy",
    "ocf_growth_yoy",
    "sales_cagr_1y", "sales_cagr_2y", "sales_cagr_3y", "sales_cagr_5y", "sales_cagr_best",
    "op_income_cagr_1y", "op_income_cagr_2y", "op_income_cagr_3y", "op_income_cagr_5y", "op_income_cagr_best",
    "net_income_cagr_1y", "net_income_cagr_2y", "net_income_cagr_3y", "net_income_cagr_5y", "net_income_cagr_best",
    "ocf_cagr_1y", "ocf_cagr_2y", "ocf_cagr_3y", "ocf_cagr_5y", "ocf_cagr_best",
    "roe_proxy",
    "return_on_equity_effective",
    "roa_proxy",
    "asset_turnover_ttm",
    "book_to_market_proxy",
    "capital_efficiency_score",
    "sector_adjusted_quality_score",
    "debt_to_equity",
    "accruals_to_assets",
    "gross_margins",
    "operating_margins",
    "eps_ttm",
    "eps_growth_yoy",
    "eps_cagr_1y", "eps_cagr_2y", "eps_cagr_3y", "eps_cagr_5y", "eps_cagr_best",
    "fcf_ttm",
    "fcf_growth_yoy",
    "fcf_cagr_1y", "fcf_cagr_2y", "fcf_cagr_3y", "fcf_cagr_5y", "fcf_cagr_best",
    "fund_history_quarters_available",
    # SAGE metrics
    "fcf_margin",
    "net_margin",
    "gross_margin_ttm",
    "rule_of_40",
    "sbc_to_revenue",
    "rd_intensity",
    "roic_approx",
    "interest_coverage",
    "dilution_penalty",
    "sage_composite_score",
    "sage_g_score",
    "sage_v_score",
    "sage_q_score",
    "sage_c_score",
    "sage_sector",
]

HISTORICAL_FUNDAMENTAL_LEVEL_COLUMNS = [
    "revenues_ttm",
    "gross_profit_ttm",
    "op_income_ttm",
    "net_income_ttm",
    "ocf_ttm",
    "fcf_ttm",
]

HISTORICAL_FUNDAMENTAL_CHANGE_COLUMNS = [
    "sales_growth_yoy",
    "op_income_growth_yoy",
    "net_income_growth_yoy",
    "ocf_growth_yoy",
    "fcf_growth_yoy",
    "eps_growth_yoy",
    "roe_trend_4q",
    "margin_trend_4q",
    "rev_growth_accel_4q",
]

HISTORICAL_FUNDAMENTAL_CAGR_COLUMNS = [
    "sales_cagr_3y",
    "sales_cagr_5y",
    "op_income_cagr_3y",
    "op_income_cagr_5y",
    "net_income_cagr_3y",
    "net_income_cagr_5y",
    "ocf_cagr_3y",
    "ocf_cagr_5y",
    "fcf_cagr_3y",
    "fcf_cagr_5y",
    "eps_cagr_3y",
    "eps_cagr_5y",
]

HISTORICAL_FUNDAMENTAL_QUALITY_COLUMNS = [
    "return_on_equity_effective",
    "roa_proxy",
    "asset_turnover_ttm",
    "capital_efficiency_score",
    "sector_adjusted_quality_score",
    "accruals_to_assets",
    "debt_to_equity",
    "gross_margins",
    "operating_margins",
]

HISTORICAL_FUNDAMENTAL_HISTORY_COLUMNS = list(
    dict.fromkeys(
        HISTORICAL_FUNDAMENTAL_LEVEL_COLUMNS
        + HISTORICAL_FUNDAMENTAL_CHANGE_COLUMNS
        + HISTORICAL_FUNDAMENTAL_CAGR_COLUMNS
        + HISTORICAL_FUNDAMENTAL_QUALITY_COLUMNS
        + ["fund_history_quarters_available"]
    )
)

FORWARD_RETURN_COVERAGE_COLUMNS = ["r_1m", "r_3m", "r_6m", "r_12m", "r_24m", "r_36m"]

HISTORICAL_DATA_QUALITY_COLUMNS = [
    "fundamental_history_level_coverage",
    "fundamental_history_change_coverage",
    "fundamental_history_cagr_coverage",
    "fundamental_history_quality_coverage",
    "fundamental_history_depth_3y_score",
    "fundamental_history_depth_5y_score",
    "fundamental_history_coverage_score",
    "growth_sleeve_technical_confirmation_score",
    "growth_sleeve_data_confidence",
    "growth_sleeve_sparse_history_penalty",
    "data_history_quality_label",
    "forward_return_coverage_score",
]

CORE_FUNDAMENTAL_MINIMUM_FIELDS = [
    "revenues_ttm",
    "op_income_ttm",
    "net_income_ttm",
    "assets",
    "liabilities",
]

# Phase 11 (2026-04-20): Multibagger Lifecycle Learning sleeve columns.
# These 3 columns are added to feature_store by compute_phase11_predictions.
# Must be included in keep_cols (build_feature_store) and hard_sanitize whitelist.
PHASE11_MULTIBAGGER_COLUMNS = [
    "phase11_p_entry",
    "phase11_p_takeprofit",
    "phase11_p_stoploss",
]

# =====================================================================
# Stage 1c (2026-04-20): SEC/yfinance schema + sector/industry maps
# =====================================================================
# Extracted from r1000_top30_institutional.py lines 185-520 (pre-move).
# 14 constants including YF_INDUSTRY_TO_GICS_GROUP (largest single dict in
# the codebase), SAGE_SECTOR_MAP, FSDS_TAG_* SEC-tag dispatch tables.
# Uses `Any` from typing module for polymorphic tuple-key annotations.


REGIME_LABEL_NEAREST_FALLBACKS: dict[str, tuple[str, ...]] = {
    "growth_reentry_alert": ("growth_reentry",),
    "growth_reentry": ("growth_reentry_alert",),
    "systemic_alert": ("systemic_crisis", "risk_off_alert"),
    "systemic_crisis": ("systemic_alert", "risk_off_alert"),
    "war_oil_rate_alert": ("war_oil_rate_shock", "risk_off_alert"),
    "war_oil_rate_shock": ("war_oil_rate_alert", "risk_off_alert"),
    "risk_off_alert": ("carry_unwind", "stagflation"),
    "carry_unwind": ("risk_off_alert", "stagflation"),
    "stagflation": ("risk_off_alert", "carry_unwind"),
}

YF_OVERRIDES = {
    "BRKB": "BRK-B",
    "BRKA": "BRK-A",
    "BFB": "BF-B",
    "BFA": "BF-A",
    "UHALB": "UHAL-B",
    "UHALA": "UHAL-A",
}

HEADERS_ISHARES = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

SCAN_PATTERNS = {
    "leakage": [
        r"earn_post_5d",
        r"earn_post_20d",
        r"forward_return\(",
    ],
    "pit": [
        r"accepted",
        r"feature_date",
        r"merge\(",
    ],
    "validation": [
        r"build_universe",
        r"IWB_PAGE",
        r"train_models",
        r"build_targets",
    ],
}

FSDS_TAGS = {
    "assets": "Assets",
    "liabilities": "Liabilities",
    "revenues": "Revenues",
    "cost_of_revenue": "CostOfRevenue",
    "gross_profit": "GrossProfit",
    "op_income": "OperatingIncomeLoss",
    "net_income": "NetIncomeLoss",
    "ocf": "NetCashProvidedByUsedInOperatingActivities",
    "capex": "PaymentsToAcquirePropertyPlantAndEquipment",
    "shares": "CommonStockSharesOutstanding",
    # SAGE additions — collected from companyfacts.zip (already present in bulk archive)
    "sbc": "ShareBasedCompensation",
    "rd_expense": "ResearchAndDevelopmentExpense",
    "interest_expense": "InterestExpense",
    "equity": "StockholdersEquity",
    "inventory": "InventoryNet",
    "long_term_debt": "LongTermDebt",
    "current_liabilities": "LiabilitiesCurrent",
    "cash": "CashAndCashEquivalentsAtCarryingValue",
}

FSDS_TAG_ALIASES = {
    "assets": ["Assets"],
    "liabilities": ["Liabilities"],
    "revenues": [
        "Revenues",
        "RevenueFromContractWithCustomer",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "SalesRevenueNet",
        "SalesRevenueServicesNet",
        "SalesRevenueGoodsNet",
        "SalesRevenueGoodsGross",
        "OperatingRevenue",
        "NetSales",
        "RevenueFromContractWithCustomerExcludingTax",
    ],
    "cost_of_revenue": [
        "CostOfRevenue",
        "CostOfGoodsSold",
        "CostOfGoodsAndServicesSold",
        "CostOfSales",
        "CostOfGoodsAndServiceExcludingDepreciationDepletionAndAmortization",
    ],
    "gross_profit": [
        "GrossProfit",
        "GrossProfitIncludingLeaseAndRentalRevenue",
    ],
    "op_income": [
        "OperatingIncomeLoss",
        "OperatingIncome",
        "OperatingProfitLoss",
        "IncomeFromOperations",
        "IncomeLossFromOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
        "IncomeLossFromOperationsBeforeIncomeTaxesMinorityInterest",
        "ProfitLossFromOperatingActivities",
        "OperatingEarningsLoss",
    ],
    "net_income": [
        "NetIncomeLoss",
        "ProfitLoss",
        "NetIncomeLossAvailableToCommonStockholdersBasic",
        "NetIncomeLossAvailableToCommonStockholdersDiluted",
    ],
    "ocf": [
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
        "NetCashProvidedByUsedInContinuingOperations",
    ],
    "capex": [
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "CapitalExpendituresIncurredButNotYetPaid",
        "CapitalExpendituresIncurredButNotYetPaidAcquisitions",
    ],
    "shares": ["CommonStockSharesOutstanding", "EntityCommonStockSharesOutstanding"],
    "sbc": [
        "ShareBasedCompensation",
        "AllocatedShareBasedCompensationExpense",
        "EmployeeBenefitsAndShareBasedCompensation",
    ],
    "rd_expense": [
        "ResearchAndDevelopmentExpense",
        "ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost",
        "ResearchAndDevelopmentExpenseNet",
    ],
    "interest_expense": [
        "InterestExpense",
        "InterestExpenseDebt",
        "InterestAndDebtExpense",
        "InterestExpenseNet",
    ],
    "equity": [
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ],
    "inventory": [
        "InventoryNet",
        "Inventories",
        "InventoryFinishedGoodsAndWorkInProcess",
    ],
    "long_term_debt": [
        "LongTermDebt",
        "LongTermDebtNoncurrent",
        "LongTermDebtAndCapitalLeaseObligations",
    ],
    "current_liabilities": [
        "LiabilitiesCurrent",
        "LiabilitiesCurrentOther",
    ],
    "cash": [
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsAndShortTermInvestments",
        "CashAndCashEquivalents",
    ],
}

FSDS_TAG_CANON = {
    alias: FSDS_TAGS[key]
    for key, aliases in FSDS_TAG_ALIASES.items()
    for alias in aliases
}

BAL_TAGS = {
    FSDS_TAGS["assets"], FSDS_TAGS["liabilities"], FSDS_TAGS["shares"],
    FSDS_TAGS["equity"], FSDS_TAGS["inventory"], FSDS_TAGS["long_term_debt"],
    FSDS_TAGS["current_liabilities"], FSDS_TAGS["cash"],
}
FLOW_TAGS = {
    FSDS_TAGS["revenues"],
    FSDS_TAGS["cost_of_revenue"],
    FSDS_TAGS["gross_profit"],
    FSDS_TAGS["op_income"],
    FSDS_TAGS["net_income"],
    FSDS_TAGS["ocf"],
    FSDS_TAGS["capex"],
    FSDS_TAGS["sbc"],
    FSDS_TAGS["rd_expense"],
    FSDS_TAGS["interest_expense"],
}
NEEDED_TAGS = set(FSDS_TAG_CANON.keys())

YF_QUARTERLY_COL_MAP = {
    "Total Revenue": "revenues",
    "Revenue": "revenues",
    "TotalRevenue": "revenues",
    "Cost Of Revenue": "cost_of_revenue",
    "CostOfRevenue": "cost_of_revenue",
    "Gross Profit": "gross_profit",
    "GrossProfit": "gross_profit",
    "Operating Income": "op_income",
    "OperatingIncome": "op_income",
    "Net Income": "net_income",
    "NetIncome": "net_income",
    "Net Income Common Stockholders": "net_income",
    "NetIncomeCommonStockholders": "net_income",
    "Total Assets": "assets",
    "TotalAssets": "assets",
    "Total Liabilities Net Minority Interest": "liabilities",
    "TotalLiabilitiesNetMinorityInterest": "liabilities",
    "Ordinary Shares Number": "shares",
    "OrdinarySharesNumber": "shares",
    "Share Issued": "shares",
    "ShareIssued": "shares",
    "Operating Cash Flow": "ocf",
    "OperatingCashFlow": "ocf",
    "Capital Expenditure": "capex",
    "CapitalExpenditure": "capex",
    # SAGE additions — yfinance field names for new SEC tags
    "Stock Based Compensation": "sbc",
    "StockBasedCompensation": "sbc",
    "Share Based Compensation": "sbc",
    "ShareBasedCompensation": "sbc",
    "Research And Development": "rd_expense",
    "ResearchAndDevelopment": "rd_expense",
    "Research Development": "rd_expense",
    "ResearchDevelopment": "rd_expense",
    "Interest Expense": "interest_expense",
    "InterestExpense": "interest_expense",
    "Interest Expense Non Operating": "interest_expense",
    "Stockholders Equity": "equity",
    "StockholdersEquity": "equity",
    "Total Equity Gross Minority Interest": "equity",
    "TotalEquityGrossMinorityInterest": "equity",
    "Inventory": "inventory",
    "Inventories": "inventory",
    "Long Term Debt": "long_term_debt",
    "LongTermDebt": "long_term_debt",
    "Long Term Debt And Capital Lease Obligation": "long_term_debt",
    "LongTermDebtAndCapitalLeaseObligation": "long_term_debt",
    "Current Liabilities": "current_liabilities",
    "CurrentLiabilities": "current_liabilities",
    "Cash And Cash Equivalents": "cash",
    "CashAndCashEquivalents": "cash",
    "Cash Cash Equivalents And Short Term Investments": "cash",
    "CashCashEquivalentsAndShortTermInvestments": "cash",
}

ACCEPTED_SEC_FORMS = {
    "10-Q",
    "10-Q/A",
    "10-K",
    "10-K/A",
    "20-F",
    "20-F/A",
    "6-K",
    "6-K/A",
}

# Stage 1b (2026-04-20): CRISIS_SECTOR_BENEFICIARIES + CORE_FUNDAMENTAL_COLUMNS
# + MACRO_* + DEFAULT_FEATURES + PILLAR/SEC/LATEST/ACTUAL/SLEEVE/SATELLITE/
# CRITICAL/COMPREHENSIVE/HISTORICAL/FORWARD/CORE_FUNDAMENTAL_MINIMUM_FIELDS
# moved to r1000_config.py. Import block at file top is extended accordingly.


SECTOR_GATE_FINANCIAL_KEYWORDS = ("FINANCIAL",)
SECTOR_GATE_REAL_ASSET_KEYWORDS = ("REAL ESTATE", "UTILITY")
SECTOR_GATE_RESOURCE_KEYWORDS = ("ENERGY", "MATERIAL")

# SAGE: Sector-Adaptive Growth Engine — 8-bucket sector classification.
# Matched against normalized (uppercased) sector labels from the universe.
# Priority order matters: first match wins (most specific listed first).
SAGE_SECTOR_MAP: list[tuple[str, tuple[str, ...]]] = [
    ("Semiconductor", ("SEMICONDUCTOR", "MICROELECTRONIC")),
    ("Software",      ("INFORMATION TECHNOLOGY", "SOFTWARE", "INTERNET", "COMMUNICATION SERVICES", "TECH")),
    ("MedTech",       ("HEALTH CARE", "HEALTHCARE", "MEDICAL", "DIAGNOSTIC", "BIOTECH", "PHARMACEUTICAL", "LIFE SCIENCE")),
    ("Banking",       ("FINANCIAL", "BANK", "CAPITAL MARKET", "ASSET MANAGEMENT", "BROKERAGE", "INSURANCE")),
    ("Industrial",    ("INDUSTRIAL", "AEROSPACE", "DEFENSE", "ELECTRICAL", "AUTOMATION", "MACHINERY")),
    ("Consumer",      ("CONSUMER", "RETAIL", "APPAREL", "RESTAURANT", "HOTEL", "LEISURE", "FOOD", "BEVERAGE", "HOUSEHOLD")),
    ("Energy",        ("ENERGY", "OIL", "GAS", "COAL", "MINING", "METAL", "CHEMICAL", "MATERIAL", "REAL ESTATE", "UTILITY")),
    ("General",       ()),   # catch-all — always last
]

# =====================================================================
# Phase 2.2: yfinance industry → coarse GICS-style industry-group map
# =====================================================================
# yfinance's `info["industry"]` strings are far more granular than the GICS
# Industry Groups (25 buckets) we want for cross-sectional industry-RS work.
# This map takes the most common yfinance industry labels seen in the
# Russell-1000 universe and folds them up to a stable 24-bucket taxonomy
# (close to GICS Industry Group + a few aggregated leaf cases) so we can
# compute meaningful within-group relative strength even when only ~10-30
# names share the same group.  Anything not matched falls back to "Other".
#
# Match rule: case-insensitive substring search against the yfinance industry
# string — first match in the list wins, so put more specific entries first.
YF_INDUSTRY_TO_GICS_GROUP: list[tuple[str, tuple[str, ...]]] = [
    # --- Technology Hardware & Semiconductors -------------------------
    ("Semiconductors",                     ("SEMICONDUCTOR EQUIPMENT", "SEMICONDUCTOR", "MICROELECTRONIC")),
    ("Tech Hardware & Storage",            ("COMPUTER HARDWARE", "ELECTRONIC COMPONENT", "ELECTRONIC EQUIPMENT", "DATA STORAGE", "SOLAR")),
    # --- Software & Services ------------------------------------------
    ("Software - Infrastructure",          ("SOFTWARE - INFRASTRUCTURE", "INFORMATION TECHNOLOGY SERVICES")),
    ("Software - Application",             ("SOFTWARE - APPLICATION", "SOFTWARE—APPLICATION")),
    ("Internet Content & Information",     ("INTERNET CONTENT", "INTERNET RETAIL")),
    ("Communication Equipment",            ("COMMUNICATION EQUIPMENT", "TELECOM SERVICES", "TELECOMMUNICATIONS")),
    # --- Healthcare ----------------------------------------------------
    ("Biotechnology",                      ("BIOTECHNOLOGY", "GENETIC", "DRUG MANUFACTURERS - SPECIALTY")),
    ("Pharmaceuticals",                    ("DRUG MANUFACTURERS", "PHARMACEUTICAL")),
    ("Medical Devices",                    ("MEDICAL DEVICES", "MEDICAL INSTRUMENTS", "MEDICAL APPLIANCES")),
    ("Diagnostics & Research",             ("DIAGNOSTICS", "MEDICAL CARE FACILITIES", "MEDICAL DISTRIBUTION", "HEALTH INFORMATION", "HEALTH PLANS", "HEALTHCARE PLANS")),
    # --- Financials ----------------------------------------------------
    ("Banks - Diversified",                ("BANKS - DIVERSIFIED", "BANKS—DIVERSIFIED", "BANK - DIVERSIFIED")),
    ("Banks - Regional",                   ("BANKS - REGIONAL", "BANKS—REGIONAL", "BANK - REGIONAL", "REGIONAL BANK")),
    ("Capital Markets",                    ("CAPITAL MARKETS", "ASSET MANAGEMENT", "FINANCIAL DATA", "FINANCIAL CONGLOMERATES")),
    ("Insurance",                          ("INSURANCE", "REINSURANCE")),
    ("Consumer Finance",                   ("CREDIT SERVICES", "MORTGAGE FINANCE", "FINANCIAL - CREDIT", "PAYMENT")),
    # --- Consumer Discretionary ---------------------------------------
    ("Auto Manufacturers & Parts",         ("AUTO MANUFACTURERS", "AUTO PARTS", "AUTO & TRUCK DEALERSHIPS", "RECREATIONAL VEHICLES")),
    ("Apparel & Luxury",                   ("APPAREL", "FOOTWEAR", "LUXURY GOODS", "TEXTILE", "PACKAGING & CONTAINERS")),
    ("Specialty Retail",                   ("SPECIALTY RETAIL", "DEPARTMENT STORES", "HOME IMPROVEMENT RETAIL", "AUTO PARTS RETAIL", "LEISURE")),
    ("Hotels Restaurants & Leisure",       ("RESTAURANTS", "LODGING", "GAMBLING", "RESORTS")),
    # --- Consumer Staples ---------------------------------------------
    ("Food Beverage & Tobacco",            ("BEVERAGES", "PACKAGED FOODS", "TOBACCO", "FARM PRODUCTS", "CONFECTIONERS")),
    ("Household & Personal Products",      ("HOUSEHOLD", "PERSONAL PRODUCTS", "PERSONAL SERVICES")),
    ("Food & Staples Retailing",           ("DISCOUNT STORES", "GROCERY STORES", "FOOD DISTRIBUTION")),
    # --- Industrials --------------------------------------------------
    ("Aerospace & Defense",                ("AEROSPACE", "DEFENSE")),
    ("Capital Goods - Machinery",          ("FARM & HEAVY CONSTRUCTION MACHINERY", "INDUSTRIAL DISTRIBUTION", "SPECIALTY INDUSTRIAL MACHINERY", "TOOLS & ACCESSORIES", "ELECTRICAL EQUIPMENT")),
    ("Construction & Engineering",         ("ENGINEERING & CONSTRUCTION", "BUILDING PRODUCTS", "BUILDING MATERIALS", "INFRASTRUCTURE OPERATIONS")),
    ("Transportation & Logistics",         ("AIRLINES", "RAILROAD", "TRUCKING", "MARINE SHIPPING", "INTEGRATED FREIGHT", "AIRPORTS")),
    ("Commercial Services",                ("BUSINESS SERVICES", "STAFFING", "CONSULTING", "RENTAL", "WASTE MANAGEMENT", "SECURITY")),
    # --- Energy & Materials -------------------------------------------
    ("Oil Gas & Consumable Fuels",         ("OIL & GAS", "THERMAL COAL", "URANIUM", "GAS UTILITIES")),
    ("Metals & Mining",                    ("GOLD", "SILVER", "COPPER", "STEEL", "ALUMINUM", "OTHER PRECIOUS METALS", "MINING")),
    ("Chemicals",                          ("CHEMICALS", "AGRICULTURAL INPUTS")),
    # --- Real Estate & Utilities --------------------------------------
    ("Equity REITs",                       ("REIT", "REAL ESTATE")),
    ("Utilities",                          ("UTILITIES", "WATER UTILITIES", "RENEWABLE UTILITIES", "INDEPENDENT POWER")),
    # --- Catch-all -----------------------------------------------------
    ("Other",                              ()),
]

# =====================================================================
# Stage 1d-i (2026-04-20): scalar constants (cache version + regex/ticker)
# =====================================================================
# Primitive module-level constants extracted from main engine file.
# ENGINE_REUSE_VERSION drives feature_store cache invalidation; bump it
# any time a schema-changing column is added to PHASE*_COLUMNS or
# compute_fundamental_features.
# TICKER_RE / SEC_COMPANYFACTS_MEMBER_RE are compiled regexes; EXCLUDE_NAME
# is the fund/ETF exclusion tuple; CASH_PROXY_TICKER is the synthetic
# ticker used by the cash sleeve in backtest_portfolio.

ENGINE_REUSE_VERSION = "2026-04-28-phase15b-early-inflection"

TICKER_RE = re.compile(r"^[A-Z0-9]{1,6}([.-][A-Z0-9]{1,4})?$")
EXCLUDE_NAME = ("ETF", "ETN", "TRUST", "FUND", "INDEX", "NOTES", "NOTE")
CASH_PROXY_TICKER = "CASH"
SEC_COMPANYFACTS_MEMBER_RE = re.compile(r"(?:^|/)(?:CIK)?(\d{10})\.json$", re.IGNORECASE)


# ---------------------------------------------------------------------
# Helper collocated with EngineConfig (below): default_factory for the
# `manual_regime_conditioned_sleeve_map` field. Not pure data (its a
# function that returns a dict literal), but lives here because its sole
# role is to seed EngineConfig's default. Also imported back into main
# engine for 3 call sites that compose against user-overrides.
# ---------------------------------------------------------------------
def default_manual_regime_conditioned_sleeve_map() -> dict[str, dict[str, Any]]:
    return {
        "ALL": {"core": 0.22, "future": 0.46, "early": 0.24, "cash": 0.08, "policy_label": "manual_all_22_46_24_cash8"},
        "balanced": {"core": 0.24, "future": 0.44, "early": 0.24, "cash": 0.08, "policy_label": "manual_balanced_24_44_24_cash8"},
        "growth_reentry": {"core": 0.16, "future": 0.46, "early": 0.30, "cash": 0.08, "policy_label": "manual_growth_16_46_30_cash8"},
        "growth_reentry_alert": {"core": 0.14, "future": 0.48, "early": 0.30, "cash": 0.08, "policy_label": "manual_growth_alert_14_48_30_cash8"},
        "systemic_crisis": {"core": 0.18, "future": 0.24, "early": 0.08, "cash": 0.50, "policy_label": "manual_systemic_18_24_08_cash50"},
        "carry_unwind": {"core": 0.22, "future": 0.34, "early": 0.14, "cash": 0.30, "policy_label": "manual_carry_22_34_14_cash30"},
        "war_oil_rate_shock": {"core": 0.24, "future": 0.32, "early": 0.14, "cash": 0.30, "policy_label": "manual_war_24_32_14_cash30"},
        "stagflation": {"core": 0.24, "future": 0.34, "early": 0.12, "cash": 0.30, "policy_label": "manual_stagflation_24_34_12_cash30"},
        "systemic_alert": {"core": 0.20, "future": 0.30, "early": 0.10, "cash": 0.40, "policy_label": "manual_systemic_alert_20_30_10_cash40"},
        "war_oil_rate_alert": {"core": 0.22, "future": 0.34, "early": 0.14, "cash": 0.30, "policy_label": "manual_war_alert_22_34_14_cash30"},
        "risk_off_alert": {"core": 0.18, "future": 0.36, "early": 0.18, "cash": 0.28, "policy_label": "manual_riskoff_18_36_18_cash28"},
    }

# =====================================================================
# Stage 1d-ii (2026-04-20): EngineConfig dataclass (665 lines, biggest)
# =====================================================================
# Moved from main engine lines 605-1268. EngineConfig holds every tunable
# knob: cache/refresh cadences, walk-forward windows, sleeve weights,
# Phase 1..9 toggles (dual-gate: this cfg flag + PHASE_*_ENABLED env var),
# concentrated grid candidates (CE v2 widened defaults), macro lag settings,
# API keys/user-agents. References DEFAULT_FEATURES + SLEEVE_FACTOR_
# REGIME_MULTIPLIERS already defined earlier in this file.

@dataclass
class EngineConfig:
    base_dir: str = "/content/drive/MyDrive/r1000_top30_institutional"
    sec_user_agent: str = "R1000InstitutionalBot (contact: andrewcha231@gmail.com)"
    alpha_vantage_api_key: str = "JOUOW3UV8ZV23AOZ"
    fred_api_key: str = "dac25101c8dc447c12fa29c8bff99ba3"   # user key 2026-04-24
    alpha_vantage_free_tier_mode: bool = True
    alpha_vantage_free_refresh_tickers: int = 8
    alpha_vantage_free_statement_repair_tickers: int = 6
    alpha_vantage_free_statement_refresh_days: int = 14
    start_date: str = "2016-01-01"
    end_date: str = datetime.utcnow().strftime("%Y-%m-%d")

    universe_size: int = 1000
    top_n: int = 30
    min_price: float = 5.0
    min_dollar_vol_20d: float = 20_000_000
    min_mktcap: float = 2_000_000_000
    max_vol_252: float = 0.60
    max_dd_1y: float = 0.65
    live_min_marketcap_proxy: float = 1_000_000_000
    universe_mode: str = "historical_snapshot_preferred"
    universe_membership_path: str = ""
    universe_fallback_mode: str = "current_constituents"
    adr_universe_min_mcap_usd_b: float = 8.0
    adr_global_alpha_fallback_enabled: bool = True
    adr_global_alpha_confirmation_min: float = 0.50
    adr_global_alpha_score_floor: float = 1.50
    adr_global_alpha_score_quantile_floor: float = 0.60
    archive_current_universe_snapshots: bool = True
    auto_membership_snapshot_max_lag_days: int = 45

    target_1m_days: int = 21
    target_3m_days: int = 63
    target_6m_days: int = 126
    target_12m_days: int = 252
    target_24m_days: int = 504
    target_36m_days: int = 756
    target_blend_1m: float = 0.10
    target_blend_3m: float = 0.45
    target_blend_6m: float = 0.45
    future_target_blend_12m: float = 0.25
    future_target_blend_24m: float = 0.45
    future_target_blend_36m: float = 0.30
    future_target_excess_weight: float = 0.65
    train_lookback_years: int = 5
    default_backtest_years: int = 8
    backtest_window_comparison_years: list[int] = field(default_factory=lambda: [5, 8, 10])
    embargo_days: int = 126
    min_train_samples: int = 3000

    ridge_alpha: float = 8.0
    logreg_c: float = 1.0
    ensemble_linear_weight: float = 0.20
    ensemble_cat_weight: float = 0.45
    ensemble_rank_weight: float = 0.35
    regime_ensemble_weights_enabled: bool = True
    regime_ensemble_weights_min_months: int = 6
    regime_ensemble_weights_strength: float = 0.50
    cat_reg_iterations: int = 350
    cat_cls_iterations: int = 350
    cat_rank_iterations: int = 250
    cat_depth: int = 6
    cat_learning_rate: float = 0.05
    ranking_enabled: bool = True
    random_seed: int = 42

    stock_weight_min: float = 0.01
    stock_weight_max: float = 0.20
    stock_weight_max_high_conviction: float = 0.50
    stock_weight_max_no_ttm: float = 0.14
    stock_weight_max_no_ttm_confirmed: float = 0.20
    cash_buffer_enabled: bool = True
    cash_weight_max: float = 0.60
    cash_target_growth_cap: float = 0.03
    cash_target_balanced_cap: float = 0.04
    cash_target_mild_risk_cap: float = 0.08
    core_compounder_sleeve_base_weight: float = 0.12
    future_winner_sleeve_base_weight: float = 0.58
    future_winner_sleeve_min_weight: float = 0.12
    future_winner_sleeve_max_weight: float = 0.74
    early_scout_sleeve_base_weight: float = 0.22
    early_scout_sleeve_min_weight: float = 0.04
    early_scout_sleeve_max_weight: float = 0.36
    early_scout_growth_floor_weight: float = 0.18
    early_scout_growth_floor_min_signal: float = 0.34
    early_scout_growth_floor_max_risk: float = 0.60
    early_scout_candidate_floor_min_share: float = 0.01
    future_winner_entry_weight_cap: float = 0.12
    future_winner_drift_weight_cap: float = 0.22
    future_winner_hard_weight_cap: float = 0.32
    early_scout_entry_weight_cap: float = 0.06
    early_scout_drift_weight_cap: float = 0.12
    early_scout_hard_weight_cap: float = 0.18
    sleeve_drift_headroom_pct: float = 0.35
    early_scout_promotion_edge_max: float = 0.04
    early_scout_promotion_confidence_max: float = 0.06
    early_scout_promotion_min_score: float = 0.84
    portfolio_size_comparison_sizes: list[int] = field(default_factory=lambda: [1, 3, 5, 8, 12, 20, 30])
    rebalance_interval_months: int = 1
    sleeve_specific_rebalance_enabled: bool = True
    core_compounder_rebalance_interval_months: int = 1
    future_winner_rebalance_interval_months: int = 2
    early_scout_rebalance_interval_months: int = 1
    rebalance_interval_comparison_months: list[int] = field(default_factory=lambda: [1, 3, 6])
    run_comparison_backtests: bool = True
    run_portfolio_size_comparison: bool = True
    run_rebalance_interval_comparison: bool = True
    run_backtest_window_comparison: bool = True
    run_sleeve_regime_comparison: bool = True
    sleeve_regime_comparison_cash_max: float = 0.02
    sleeve_regime_apply_champion: bool = True
    regime_conditioned_sleeve_map: dict[str, dict[str, Any]] = field(default_factory=dict)
    manual_regime_conditioned_sleeve_map: dict[str, dict[str, Any]] = field(default_factory=default_manual_regime_conditioned_sleeve_map)
    run_regime_map_method_comparison: bool = True
    run_sleeve_cap_policy_comparison: bool = True
    run_ai_four_sleeve_comparison: bool = True
    ai_four_sleeve_max_candidates: int = 8
    sleeve_cap_policy_apply_champion: bool = True
    sleeve_cap_policy_max_candidates: int = 6
    sleeve_cap_policy_objective_excess_weight: float = 1.15
    sleeve_cap_policy_objective_sharpe_weight: float = 1.0
    sleeve_cap_policy_objective_sortino_weight: float = 0.50
    sleeve_cap_policy_objective_drawdown_weight: float = 0.65
    sleeve_cap_policy_objective_turnover_weight: float = 0.20
    sleeve_cap_policy_objective_concentration_weight: float = 0.25
    sleeve_cap_policy_objective_cash_drag_weight: float = 0.15
    run_standalone_sleeve_backtest_comparison: bool = True
    standalone_sleeve_top_n: int = 7
    standalone_sleeve_rebalance_intervals: list[int] = field(default_factory=lambda: [1, 3])
    run_concentrated_backtest_comparison: bool = True
    # Phase 9 CE (Concentrated Expansion, 2026-04-18): lifted N≤3 cap to
    # challenge beyond 29.89% CAGR. Previous optimum was N=3 conviction_curve
    # monthly (concentrated_backtest_metrics.json). New grid tests higher N,
    # multi-month intervals, and score_power weighting. See CHANGELOG.
    concentrated_top_n_candidates: list[int] = field(default_factory=lambda: [1, 2, 3, 4, 5, 7, 10])
    concentrated_rebalance_intervals: list[int] = field(default_factory=lambda: [1, 2, 3])
    concentrated_weighting_modes: list[str] = field(default_factory=lambda: ["conviction_curve", "winner_take_all", "score_power"])
    concentrated_allowed_sleeves: list[str] = field(default_factory=lambda: ["future_winner", "early_scout"])
    # Phase 15-A (2026-04-28): relaxed 0.45 -> 0.30. Default rejected cyclical
    # leaders (SNDK/MU/WDC class) where score is high but multi_year_winner_score
    # is 0 because price is recovering from a memory cycle bottom. Combined with
    # the new `rank_fallback_top_decile` lane in select_concentrated_portfolio_topk
    # this admits high-rank cycle plays without breaking the diversified core.
    concentrated_min_confirmation: float = 0.30
    concentrated_score_future_weight: float = 0.95
    concentrated_score_early_weight: float = 1.05
    concentrated_score_sage_weight: float = 0.45
    concentrated_score_confirmation_weight: float = 0.40
    concentrated_score_breakout_weight: float = 0.30
    concentrated_score_momentum_weight: float = 0.35
    concentrated_score_exit_risk_penalty: float = 0.40
    concentrated_max_single_name_weight: float = 1.00
    concentrated_monitoring_review_days: int = 7
    run_historical_data_quality_reports: bool = True
    growth_history_confidence_penalty_weight: float = 0.18
    growth_history_confidence_min_for_full_sleeve: float = 0.35
    minervini_future_engine_weight: float = 0.65
    minervini_portfolio_seed_weight: float = 0.40
    minervini_broken_trend_penalty_weight: float = 0.50
    # ------------------------------------------------------------------
    # Phase 3: sleeve weight renormalization (A/B gated)
    # ------------------------------------------------------------------
    # row_mean averages N sleeve-composite terms into sum/N, which means
    # every time Phase 1 or Phase 2 added new terms the PRE-EXISTING
    # factors lost effective weight (the /N denominator grew). When
    # renorm is enabled the composites become a true weighted average
    # sum(w_i * z_i) / L1 where L1 = sum(|w_i|), so each factor's
    # relative contribution stays proportional to its own weight
    # regardless of how many other phases added terms.
    # Both `sleeve_weight_renorm_enabled=True` AND the env var
    # `PHASE_PHASE3_RENORM_ENABLED` (not set to 0/false/off/disabled)
    # are required to flip on. Default OFF until A/B validates.
    # `sleeve_weight_l1_target=0.0` means "use the sleeve's own L1 norm"
    # (pure weighted average). A positive value lets you target a
    # specific L1 magnitude (e.g. match the pre-Phase-1+2 core L1 of
    # ~7.32) so the downstream winsorize/clip(-6,+6) receives the same
    # magnitude range as the legacy path.
    sleeve_weight_renorm_enabled: bool = False
    sleeve_weight_l1_target: float = 0.0
    # ------------------------------------------------------------------
    # Phase 4: regime-conditional dynamic sleeve weights (PHASE_ROADMAP §2.4).
    # ------------------------------------------------------------------
    # The sleeve composites in `compute_portfolio_sleeve_columns` today
    # use static factor weights that are identical across every regime
    # (balanced, growth_reentry, stagflation, systemic_crisis, ...). The
    # right emphasis for `uptrend_continuation_score` in a risk-on bull
    # market is however very different from the right emphasis in a
    # systemic-crisis regime. Phase 4 multiplies the final per-sleeve
    # composite by a regime-specific scalar (keyed on `event_regime_label`)
    # so the same factor table can produce differentiated risk
    # emphasis per regime without re-weighting individual factors.
    #
    # Both `regime_dynamic_sleeve_weights_enabled=True` AND the env var
    # `PHASE_PHASE4_REGIME_WEIGHTS_ENABLED` (not 0/false/off/disabled)
    # are required to flip on. Default OFF until A/B validates.
    #
    # `regime_sleeve_multiplier_table=None` means "use the built-in
    # `SLEEVE_FACTOR_REGIME_MULTIPLIERS` default". Supply a dict of the
    # same shape `{regime_label: {"core": float, "future": float,
    # "early": float}}` to override only specific regimes; missing
    # entries fall through to the built-in default (which is identity
    # 1.0 for unknown regimes).
    regime_dynamic_sleeve_weights_enabled: bool = False
    regime_sleeve_multiplier_table: Optional[dict[str, dict[str, float]]] = None
    # ------------------------------------------------------------------
    # Phase 5: sub-industry leader/laggard pair signals (PHASE_ROADMAP §2.5).
    # ------------------------------------------------------------------
    # Within a strong industry_group, the top-quartile names earn a
    # bonus and the bottom-quartile names earn a symmetric penalty.
    # This is the IBD / O'Neil empirical regularity ("leaders pull
    # away, laggards get left behind in a rotating group"). Unlike
    # Phase 3 / Phase 4 which are default OFF, Phase 5 is default ON
    # per PHASE_ROADMAP because the signals are purely additive to the
    # existing factor tables: when disabled via env var the three new
    # columns are zero-filled so downstream sleeve composites are
    # unaffected. Default ON means the next FULL rebuild bakes the
    # signals into `feature_store_latest.parquet` immediately.
    #
    # `sub_industry_min_group_size=6` skips groups with fewer than 6
    # names to avoid spurious quartile ranking on tiny groups.
    # `sub_industry_leader_gap_threshold=0.8` is the std-units gap the
    # within-group top-quartile has to exceed the median by before the
    # bonus fires (a "clear separation" guard).
    # Phase 5 default flipped to False on 2026-04-17 after factor IC
    # measurement (DIAGNOSIS_FACTOR_IC.md) showed industry_leader_bonus_score
    # and industry_leader_gap both have IC near zero (~-0.006 / -0.001) over
    # 83 months. The signal has no alpha even after the dilution fix in
    # commit c4d50fd. Keep the infrastructure + toggle so future re-enable
    # via PHASE_PHASE5_LEADER_LAGGARD_ENABLED=1 + cfg override is trivial.
    sub_industry_leader_laggard_enabled: bool = False
    sub_industry_min_group_size: int = 6
    sub_industry_leader_gap_threshold: float = 0.8
    # Phase 15-A (2026-04-28): sub-industry sub-cap to prevent mega-cap
    # dominance inside broad sectors like Information Technology. Within each
    # listed sector, cap names per sub_industry / industry_group at this
    # count. Solves the SHIPPED Phase 14 case where NVDA+LRCX absorbed the IT
    # sector cap and locked out MU/WDC/CIEN/SNDK (memory + networking
    # sub-industries with valid scores).
    sub_industry_cap_enabled: bool = True
    sub_industry_max_per_sector: int = 2
    sub_industry_cap_sectors: list[str] = field(default_factory=lambda: [
        "Information Technology",
        "Communication Services",
        "Health Care",
        "Financials",
        "Consumer Discretionary",
    ])
    export_extended_outputs: bool = True
    export_explain_outputs: bool = True
    turnover_cap_monthly: float = 0.55
    trade_cost_bps_per_side: float = 25.0
    roundtrip_cost_bps: float = 50.0
    starting_capital_usd: float = 100000.0
    min_port_names: int = 5
    min_dynamic_port_names: int = 12
    alert_review_days: int = 7

    cap_leader_weight: float = 0.60
    cap_base_weight: float = 0.40
    cap_overheated_weight: float = 0.30
    cap_lagger_weight: float = 0.22
    leader_n_sectors: int = 3
    lagger_n_sectors: int = 3
    overheat_thr: float = 0.15
    overheat_penalty_scale: float = 0.35
    overheat_penalty_trigger: float = 0.55
    overheat_penalty_seed_weight: float = 0.40
    overheat_rsi_threshold: float = 68.0
    overheat_bb_pb_threshold: float = 0.92
    strategy_blueprint_weight: float = 0.22
    min_live_estimate_coverage: float = 0.25
    watchlist_penalty_scale: float = 0.12
    manual_moat_path: str = ""
    manual_moat_half_life_days: int = 365
    archetype_mixture_weight: float = 0.10

    risk_penalty_scale: float = 0.65
    weight_score_power: float = 1.20
    weight_invvol_power: float = 0.12
    optimizer_risk_aversion: float = 0.90
    optimizer_turnover_penalty: float = 0.30
    optimizer_liquidity_reward: float = 0.20
    max_names_per_cik: int = 1
    benchmark_ticker: str = "^GSPC"
    benchmark_history_source: str = "fred_sp500"
    target_excess_weight: float = 0.70
    defensive_rotation_strength: float = 0.40
    growth_reentry_strength: float = 0.38
    benchmark_hugging_penalty: float = 0.10
    event_regime_sensitivity: float = 0.55
    live_event_alert_strength: float = 0.35
    live_event_risk_threshold: float = 0.50
    live_event_growth_threshold: float = 0.55

    yf_retry: int = 2
    yf_sleep: float = 0.05
    yf_enable_batch_download: bool = True
    yf_batch_download_size: int = 64
    sec_sleep: float = 0.20
    fsds_quarters_backfill: int = 60
    fsds_quarters_each_run: int = 24
    price_history_years: int = 15
    max_new_yf_info: int = 300
    live_refresh_days: int = 2
    max_live_refresh_tickers: int = 1000
    # Phase 2: yfinance industry metadata refresh budget
    industry_metadata_max_new_per_run: int = 250
    industry_metadata_refresh_days: int = 60
    max_alpha_vantage_refresh_tickers: int = 60
    latest_statement_repair_enabled: bool = True
    latest_statement_repair_tickers: int = 60
    latest_statement_repair_refresh_days: int = 7
    companyfacts_refresh_days: int = 3
    companyfacts_max_retries: int = 4
    companyfacts_retry_backoff: float = 1.0
    use_sec_companyfacts_bulk_local: bool = True
    sec_companyfacts_bulk_path: str = ""
    macro_refresh_days: int = 3
    macro_m2_release_lag_months: int = 1
    macro_slow_release_lag_months: int = 1
    fund_panel_repair_quarters: int = 12
    force_full_fund_panel_rebuild: bool = False
    fund_ttm_ffill_quarters: int = 2
    fund_balance_ffill_quarters: int = 4
    fund_ttm_fallback_max_age_days: int = 180
    targeted_repair_only_weak_ciks: bool = True
    targeted_repair_max_ciks: int = 300
    targeted_repair_flow_cov_threshold: float = 0.50
    targeted_repair_stale_days: int = 220

    baseline_v42_code: str = ""
    features: list[str] = field(default_factory=lambda: DEFAULT_FEATURES.copy())
    use_wikipedia_lists: bool = False
    w_quality_trend: float = 0.20
    w_forward_revision: float = 0.25
    w_event_reaction: float = 0.10
    w_institutional_flow: float = 0.10
    w_insider_flow: float = 0.08
    w_actual_results: float = 0.18
    w_garp: float = 0.14
    w_multidimensional_confirmation: float = 0.08
    anticipatory_growth_weight: float = 0.16
    future_winner_scout_weight: float = 0.12
    future_winner_model_weight: float = 0.08
    actual_results_fresh_days: int = 150
    proxy_decay_after_actual: float = 0.75
    use_sec_actual_data: bool = True
    sec_actual_local_dir: str = ""
    rank_eval_top_k: int = 20
    reuse_phase4_models_for_latest_recommendations: bool = True
    require_historical_membership_for_backtest: bool = True
    min_ttm_feature_coverage: float = 0.70
    min_valuation_feature_coverage: float = 0.60
    min_core_fundamental_fields_required: int = 4
    sector_adjusted_gate_enabled: bool = True
    sector_adjusted_financial_min_fields: int = 3
    sector_adjusted_realasset_min_fields: int = 4
    sector_adjusted_resource_min_fields: int = 4
    partial_scout_gate_enabled: bool = True
    partial_scout_min_fields: int = 2
    partial_scout_confirmation_min: float = 0.55
    partial_scout_score_floor: float = 2.25
    future_winner_min_fundamental_fields_required: int = 3
    future_winner_confirmation_min: float = 0.42
    future_winner_fundamental_presence_min: float = 0.32
    future_winner_fundamental_reliability_min: float = 0.36
    early_scout_min_fundamental_fields_required: int = 2
    early_scout_confirmation_min: float = 0.34
    early_scout_fundamental_presence_min: float = 0.18
    early_scout_fundamental_reliability_min: float = 0.24
    stock_weight_max_sector_adjusted: float = 0.08
    stock_weight_max_partial_scout: float = 0.04
    partial_scout_total_weight_cap: float = 0.10
    speculative_stop_loss_pct: float = 0.25
    speculative_weight_max: float = 0.04
    speculative_total_weight_max: float = 0.15
    speculative_min_rs_composite: float = 0.0
    # Phase 15-A (2026-04-28): concentrated-sleeve specific stop-loss + regime
    # cash gates. Concentrated has only 5 names so a single -25% drawdown
    # contributes -5% to the sleeve total — too loose. Use a tighter trailing
    # stop. Combined with the tighter VIX gate below this is the loss-min
    # half of the "수익 극대 / 손실 최소" mandate.
    concentrated_stop_loss_pct: float = 0.15            # -15% hard stop (vs core -25%)
    concentrated_trailing_stop_pct: float = 0.12        # -12% trailing from peak
    concentrated_trailing_stop_enabled: bool = True
    concentrated_regime_cash_vix_threshold: float = 25.0  # VIX > 25 (vs core 30)
    concentrated_regime_cash_breadth_threshold: float = 0.30  # breadth_above_ma200 < 30%
    concentrated_regime_cash_pct: float = 0.30          # force 30% cash when regime risk-off
    # Phase 15-R1 (2026-04-21): trailing stop from peak on early_scout positions.
    # Complements the entry-point -25% hard stop with a peak-relative exit so
    # the engine preserves realized gains when a held position rolls over.
    # Dual-gate: both cfg flag AND env var PHASE_PHASE15_R1_TRAILING_ENABLED
    # must be truthy for the trailing stop to activate — default OFF until A/B
    # ship gate passes.
    trailing_stop_enabled: bool = False
    trailing_stop_early_scout_pct: float = 0.15
    trailing_stop_future_winner_pct: float = 0.0  # 0 = disabled; A/B cell D tests 0.15
    # Phase 15-R2 (2026-04-22): force-exit a position when its analyst revision
    # score is negative for N consecutive months. Triggers AFTER fundamental
    # thesis breaks but BEFORE -25% hard stop. Default OFF.
    revision_break_exit_enabled: bool = False
    revision_break_consecutive_months: int = 2
    revision_break_score_threshold: float = 0.0  # < this counts as negative
    # Phase 15-R3 (2026-04-22): force-exit a position whose RS percentile
    # was once top X% and has since dropped below Y%. Catches "growth fade"
    # earlier than monthly score-based rotation. Default OFF.
    rs_break_exit_enabled: bool = False
    rs_break_min_peak_pctile: float = 0.85   # was once at >= 85th pctile (top 15%)
    rs_break_drop_to_pctile: float = 0.30    # now at <= 30th pctile
    # Phase 15-S1a (2026-04-21): prune three factors from the future_winner
    # composite whose per-factor rank-IC is negative at BOTH 1-month and
    # 3-month horizons over 94 OOS months (see
    # research/phase15_s1_future_winner_factor_ic.csv):
    #   fundamental_turnaround_acceleration_score  IR_1m=-0.19 IR_3m=-0.27
    #   cashflow_inflection_under_loss_score       IR_1m=-0.15 IR_3m=-0.20
    #   uptrend_breakdown_penalty                  IR_3m=-2.03 (sign flipped)
    # These add noise regardless of rebalance horizon. Dual-gate: cfg flag AND
    # env var PHASE_PHASE15_S1A_FUTURE_PRUNE_ENABLED must both be truthy.
    # Default OFF — A/B via run_local.py with the env var to measure ship gate.
    # Only the future_winner weight_pairs are gated; core and early sleeves
    # keep their original weights (IC drag there may be offset by other
    # sleeve-specific factors, untested).
    phase15_s1a_future_prune_enabled: bool = False
    # Phase 15-A1 (2026-04-22): drop three features with NEGATIVE rank-IC on
    # forward_r_3m whose usage sites apply POSITIVE weights (so the raw
    # negative alpha leaks into composites):
    #   macro_hedge_score                  IR_3m = -0.398
    #   focus_defensive_regime_score       IR_3m = -0.332
    #   focus_live_event_defensive_score   IR_3m = -0.333
    # See research/phase15_selection_deep_audit_report.md.
    # atr14_pct also had IR -0.323 but is used as a PENALTY (subtracted) so
    # the sign inversion makes its effective contribution positive — kept.
    # Dual-gate: cfg flag AND env var PHASE_PHASE15_A1_DROP_NEGATIVE_FEATURES_ENABLED
    # must both be truthy. Default OFF — A/B via env var.
    phase15_a1_drop_negative_features_enabled: bool = False
    # 2026-04-22: --ab-quick mode flag. When True, apply_fast_mode disables
    # ALL comparison grids (concentrated, sleeve_cap, portfolio_size,
    # rebalance_interval, backtest_window) so the pipeline runs main backtest
    # only — ~2-5 min for fast A/B iteration. Default False (regular fast_mode
    # behavior preserved).
    ab_quick_mode: bool = False
    run_engine_diagnostics_report: bool = True
    engine_diagnostics_top_n: int = 7
    universe_change_warn_count: int = 10
    use_macro_regime_features: bool = True
    optimizer_regime_sensitivity: float = 0.35
    reuse_existing_artifacts: bool = True
    resume_partial_walkforward: bool = True
    walkforward_checkpoint_every: int = 6
    walkforward_retrain_frequency_months: int = 3
    cat_validation_months: int = 6
    cat_early_stopping_rounds: int = 40
    use_benchmark_beating_focus_overlay: bool = True
    focus_overlay_strength: float = 0.42
    focus_sector_crowding_penalty: float = 0.12
    focus_target_n: int = 18
    focus_riskoff_target_n: int = 7
    focus_portfolio_utility_boost: float = 0.0
    focus_direct_ticker_tiebreak: float = 0.0
    focus_no_ttm_bonus_cap_weak: float = 2.5
    focus_no_ttm_bonus_cap_confirmed: float = 4.5
    focus_negative_momentum_emergence_penalty: float = 0.65
    portfolio_confirmation_utility_boost: float = 0.0
    portfolio_confirmation_conviction_boost: float = 0.0
    portfolio_seed_confirmation_boost: float = 0.0
    portfolio_midterm_utility_boost: float = 0.0
    portfolio_seed_midterm_boost: float = 0.0
    portfolio_garp_utility_boost: float = 0.0
    portfolio_anticipatory_utility_boost: float = 0.0
    portfolio_seed_anticipatory_boost: float = 0.0
    portfolio_top1_conviction_boost: float = 0.0
    portfolio_top2_conviction_boost: float = 0.0
    fear_greed_live_overlay_weight: float = 0.03
    adaptive_rebalance_enabled: bool = True
    adaptive_rebalance_growth_months: int = 1
    adaptive_rebalance_balanced_months: int = 3
    adaptive_rebalance_riskoff_months: int = 6
    adaptive_rebalance_distance_penalty: float = 0.75
    adaptive_rebalance_risk_threshold: float = 0.60
    adaptive_rebalance_growth_threshold: float = 0.60
    adaptive_rebalance_hold_until_due: bool = True
    adaptive_ensemble_enabled: bool = True
    adaptive_ensemble_lookback_months: int = 12
    adaptive_ensemble_min_months: int = 6
    adaptive_ensemble_strength: float = 0.65
    adaptive_ensemble_floor_weight: float = 0.10
    adaptive_ensemble_temperature: float = 4.0
    adaptive_ensemble_rank_ic_weight: float = 0.70
    adaptive_ensemble_recent_half_life_months: float = 4.0
    ops_min_realized_coverage: float = 0.90
    cash_release_max_per_rebalance: float = 0.20
    portfolio_hold_policy_enabled: bool = True
    portfolio_hold_policy_seed_weight: float = 0.14
    portfolio_hold_policy_weight: float = 0.18
    portfolio_hold_policy_prev_weight_bonus: float = 0.06
    portfolio_hold_policy_exit_penalty_weight: float = 0.12
    portfolio_low_growth_penalty: float = 0.10
    portfolio_long_hold_bonus_weight: float = 0.14
    dividend_policy_yield_only_weight: float = 0.35
    dividend_quality_trend_weight: float = 0.20
    dividend_presence_weight: float = 0.03
    dividend_growth_gate_floor: float = 0.15
    w_fundamental_reliability: float = 0.08
    score_missing_fundamental_penalty: float = 0.12
    focus_missing_fundamental_penalty: float = 0.20
    portfolio_fundamental_utility_boost: float = 0.0
    show_output_previews_after_run: bool = True
    strict_live_backtest_alignment: bool = True
    require_acceptance_for_portfolio_export: bool = True
    focus_primary_tickers: list[str] = field(default_factory=list)
    focus_optional_tickers: list[str] = field(default_factory=list)
    focus_ai_infra_tickers: list[str] = field(default_factory=list)
    focus_power_infra_tickers: list[str] = field(default_factory=list)
    focus_hedge_tickers: list[str] = field(default_factory=list)
    focus_defense_tickers: list[str] = field(default_factory=list)
    focus_energy_hedge_tickers: list[str] = field(default_factory=list)
    focus_watchlist_tickers: list[str] = field(default_factory=list)
    yf_quarterly_cache_enabled: bool = True
    yf_quarterly_refresh_days: int = 7
    yf_quarterly_max_tickers_per_run: int = 1000
    yf_quarterly_refresh_only_poor_coverage: bool = True
    # --------------- conviction hold (hold winners longer) ---------------
    conviction_hold_cum_return_threshold: float = 0.25  # position must be up 25%+ (inferred from drift)
    conviction_hold_seed_bonus: float = 0.35            # extra seed bonus for conviction-hold names
    conviction_hold_utility_bonus: float = 0.30         # extra utility bonus for conviction-hold names
    conviction_hold_min_months: int = 2                 # minimum months held before conviction status
    # --------------- winner scaling (add to winners, cut losers) ---------------
    winner_scale_top_quartile_boost: float = 1.20       # multiply weight by 1.20 for top performers
    winner_scale_bottom_quartile_cut: float = 0.70      # multiply weight by 0.70 for bottom performers
    # --------------- revision acceleration ---------------
    revision_seed_score_weight: float = 0.22            # revision_blueprint_score weight in seed_score
    # --------------- valuation extreme penalty ---------------
    valuation_extreme_pe_threshold: float = 80.0        # forward PE above this triggers penalty
    valuation_extreme_penalty_weight: float = 0.20      # seed_score penalty for extreme valuation
    # --------------- drawdown circuit breaker (legacy single-threshold; kept for backward compat) ---------------
    drawdown_circuit_breaker_threshold: float = 0.20    # portfolio drawdown that triggers cash raise
    drawdown_circuit_breaker_cash_target: float = 0.50  # force cash to 50% in drawdown
    drawdown_circuit_breaker_recovery: float = 0.10     # drawdown recovers below this to exit breaker
    # ---------------
    # Phase 6a: 3-level drawdown circuit breaker (PHASE_ROADMAP §2.6)
    # ---------------
    # Expands the legacy single-threshold breaker into an asymmetric
    # 3-level ladder. When a level is tripped, the portfolio's cash
    # weight is floored at `level_N_cash_floor` AND non-cash weights
    # are shrunk by `level_N_scale`. Recovery uses equity-level tracking
    # (not drawdown percentage) to avoid oscillation: after level N
    # trips at `dd_trigger_equity`, the breaker only steps down when
    # `running_equity >= dd_trigger_equity * (1 + recovery_buffer)`.
    # Default ON per PHASE_ROADMAP §2.6. When disabled via env var or
    # cfg flag the active path reverts to the legacy single-threshold
    # breaker so prior runs remain reproducible.
    drawdown_breaker_multilevel_enabled: bool = True
    drawdown_breaker_level_1_threshold: float = 0.08    # -8% peak-to-running DD
    drawdown_breaker_level_1_cash_floor: float = 0.15
    drawdown_breaker_level_1_scale: float = 0.90
    drawdown_breaker_level_2_threshold: float = 0.15    # -15%
    drawdown_breaker_level_2_cash_floor: float = 0.35
    drawdown_breaker_level_2_scale: float = 0.70
    drawdown_breaker_level_3_threshold: float = 0.25    # -25%
    drawdown_breaker_level_3_cash_floor: float = 0.60
    drawdown_breaker_level_3_scale: float = 0.40
    drawdown_breaker_recovery_buffer: float = 0.03      # require equity to overshoot trigger by 3% before stepping down
    # ---------------
    # Phase 6b: VIX level hard guard (PHASE_ROADMAP §2.6 + PROPOSAL §3)
    # ---------------
    # VIX-level-triggered cash floor, applied inside
    # `compute_regime_portfolio_controls()` right before the final
    # `np.clip(cash_target, ...)`. Four tiers escalate the cash floor
    # based on absolute VIX level:
    #   VIX >= 22 -> cash >= 10%
    #   VIX >= 28 -> cash >= 25%
    #   VIX >= 35 -> cash >= 40%
    #   VIX >= 45 -> cash >= 55%
    # This catches fast VIX spikes that the 63-day z-score regime
    # detection lags. Composes via max() with other cash-target
    # controls (regime policy + Phase 6a breaker) so the MORE
    # defensive floor always wins.
    # Default ON per PHASE_ROADMAP §2.6. When toggled off the
    # `vix_level_guard_enabled` flag or the env gate skips the
    # VIX-floor step, leaving cash_target at the regime-policy value.
    vix_level_guard_enabled: bool = True
    vix_level_tier1_threshold: float = 22.0
    vix_level_tier1_cash_floor: float = 0.10
    vix_level_tier2_threshold: float = 28.0
    vix_level_tier2_cash_floor: float = 0.25
    vix_level_tier3_threshold: float = 35.0
    vix_level_tier3_cash_floor: float = 0.40
    vix_level_tier4_threshold: float = 45.0
    vix_level_tier4_cash_floor: float = 0.55
    # ---------------
    # Phase 6c: volatility targeting (PHASE_ROADMAP §2.6 + PROPOSAL §7)
    # ---------------
    # Tracks realized portfolio volatility over a rolling window of
    # monthly net returns and scales non-cash weights down when vol
    # exceeds target. Formula:
    #   vol_scale = clip(target_vol / max(realized_vol, target_vol),
    #                    vol_scale_floor, vol_scale_ceiling)
    # `target_vol` is ANNUALIZED. The floor of 0.5 means we never
    # shrink non-cash below 50% of its constructed weight; the ceiling
    # of 1.0 means we never LEVER up (would need margin anyway).
    # Default OFF per PHASE_ROADMAP §2.6 — vol targeting can hurt
    # CAGR in calm markets, so user must explicitly opt in.
    volatility_targeting_enabled: bool = False
    vol_target_annualized: float = 0.12
    vol_lookback_months: int = 6
    vol_scale_floor: float = 0.50
    vol_scale_ceiling: float = 1.00
    # ---------------
    # Phase 7a: Insider flow + accruals quality sleeve wiring (PHASE_ROADMAP §Phase 7 candidates)
    # ---------------
    # `insider_flow_signal_score` is already computed end-to-end in the
    # engine (yfinance `insider_transactions` -> optional SEC Form 3/4/5
    # actual-data override -> z-scored composite in `build_live_factor_overlay`)
    # and is already consumed by the main `total_score` via the
    # pre-existing `w_insider_flow` weight. Phase 7a adds it to the
    # sleeve composites (future/early) so the sleeve-specific tilt also
    # captures insider conviction.
    # `accruals_to_assets` = (NI_ttm - OCF_ttm) / assets is computed
    # automatically in the fundamentals pipeline (line ~11760). High
    # accruals = earnings-quality risk (Sloan effect) -> negative
    # contribution on the `core` compounder sleeve.
    # Default OFF per the plan — A/B measurement first.
    phase7a_insider_accruals_enabled: bool = False
    phase7a_insider_early_weight: float = 0.25   # insider flow bonus on early_scout
    phase7a_insider_future_weight: float = 0.15  # insider flow bonus on future_winner
    phase7a_accruals_core_weight: float = -0.20  # negative = high accruals penalised on core

    # --------------- Phase 8a.4: hold persistence bonus ---------------
    # Reduces turnover (measured at 49.5%/mo -> target 25%/mo) by adding
    # a composite bonus to held names that are still trending. See
    # compute_portfolio_sleeve_columns for the formula. Default ON.
    phase8a_hold_persistence_enabled: bool = True
    phase8a_hold_persistence_weight: float = 0.90    # weight of bonus in each sleeve composite

    # --------------- Phase 8b.1: long-lookback momentum ---------------
    # Adds mom_18m / mom_24m / mom_36m and two composites
    # (multi_year_winner_score, persistence_trend_24m) so the engine can
    # identify multi-year trend names (NVDA/AVGO/MU pattern).
    phase8b_long_lookback_enabled: bool = True
    phase8b_multi_year_future_weight: float = 0.90   # weight on future sleeve
    phase8b_multi_year_early_weight: float = 0.60    # weight on early sleeve (lower — early is bottom-fishing focused)
    phase8b_multi_year_core_weight: float = 0.40     # weight on core sleeve (moderate — compounders benefit less)
    phase8b_persistence_trend_future_weight: float = 0.50  # binary-flag boost on future
    phase8b_persistence_trend_core_weight: float = 0.30    # binary-flag boost on core

    # --------------- Phase 8c.1: mega-cap future-sleeve override ---------------
    # When a name is mega-cap (>$50B) AND has strong revenue growth (>25%)
    # AND is a multi-year trend winner (multi_year_winner_score>1.0),
    # force-classify it into future_winner sleeve so it gets the full
    # 58% sleeve allocation instead of being stranded in core's 12%.
    phase8c_megacap_future_override_enabled: bool = True
    phase8c_megacap_threshold_usd: float = 50.0e9            # market cap floor for override
    phase8c_megacap_min_revenue_growth: float = 0.25         # rev-growth gate
    phase8c_megacap_min_multi_year_score: float = 1.0        # multi_year_winner_score gate (top-quartile)

    # --------------- Phase 8c.2: growth-adjusted valuation dampen ---------------
    # Zero out the valuation PENALTY when a name has strong revenue
    # growth. High P/E is justified for high-growth names — penalising
    # them is what caused NVDA to rank 23 during its best 2024-01 month.
    phase8c_growth_adj_valuation_enabled: bool = True

    # --------------- Phase 8d.1: IC-proportional sleeve weight boost ---------------
    # Boost 2 specific underweighted factors whose factor IC is top-tier
    # in their sleeves (strategy_blueprint 0.017, industry_group_strength 0.016).
    # When active: strategy_blueprint core 0.25->1.00; industry_group_strength
    # core 0.10->0.50, future 0.30->0.60. When inactive: legacy weights.
    phase8d_ic_reweight_enabled: bool = True

    # --------------- Phase 8d.2: long-horizon alpha composite ---------------
    # Aggregates the 5 best r_12m-IC fundamental factors (ep_ttm, fcfy_ttm,
    # sp_ttm, roe_proxy, sage_composite_score) into a single composite
    # and wires it into sleeve tables with meaningful weights. Bypasses
    # the walk-forward ML ensemble's r_1m training myopia (which under-
    # weights factors whose alpha materialises over longer horizons).
    # "Phase 8e lite" without the walk-forward refactor risk of proper
    # r_12m ML retraining.
    phase8d_long_horizon_alpha_enabled: bool = True
    phase8d_long_horizon_alpha_core_weight: float = 1.00      # full weight on core (quality+value thesis)
    phase8d_long_horizon_alpha_future_weight: float = 0.60    # moderate on future (momentum-first sleeve)
    phase8d_long_horizon_alpha_early_weight: float = 0.50     # moderate on early (inflection-first sleeve)

    # --------------- Phase 9 C1: Phase 8b multi_year weight rebalance ---------------
    # Phase 8 measured run (d87160d) showed Future sleeve absorbing ~72% of
    # portfolio (target 45%) and Early sleeve collapsing to 0 names. The
    # multi_year_winner_score sleeve weights (future 0.90, early 0.60, core 0.40)
    # were too future-heavy. Rebalanced to:
    #   future 0.50 (-44%)  reduce future absorption of multi-year trends
    #   early  0.80 (+33%)  let multi-year early candidates surface
    #   core   0.30 (-25%)  mega-cap auto-catch (Phase 9 C2) means core 가중치 작음
    # Net L1: 1.90 -> 1.60 (signal preserved, dominance rebalanced).
    # Override the legacy phase8b_multi_year_*_weight defaults above.
    # When Phase 9 C1 disabled (env or cfg), legacy values restore.
    phase9_c1_rebalance_enabled: bool = True
    phase9_c1_multi_year_future_weight: float = 0.50
    phase9_c1_multi_year_early_weight: float = 0.80
    phase9_c1_multi_year_core_weight: float = 0.30

    # --------------- Phase 9 C2: Sleeve thesis-gate (percentile-based) ---------------
    # Replaces argmax-of-3-sleeve-scores assignment with EXPLICIT THESIS GATES.
    # Solves the structural problem documented in ARCHITECTURE_REVIEW.md §6b
    # ("sleeve taxonomy collapsed — early scout 0 names, sleeve labels lost
    # archetype meaning"). Uses CROSS-SECTIONAL PERCENTILES (not absolute $)
    # so thresholds remain valid as market grows over time (user feedback:
    # "$500B 도 10년 후엔 작을 수 있다 — 능동적으로 분리").
    #
    # Validated by 2026-04-17 simulation on 610-name universe:
    #   CORE eligible:    58 names ( 9.5%)  mega 31 + quality 36
    #   FUTURE eligible:  54 names ( 8.9%)
    #   EARLY eligible:   55 names ( 9.0%)
    #   UNASSIGNED:      443 names (72.6%)  ← thesis-less names auto-dropped
    #
    # Percentile thresholds (top X% by mktcap rank within rebalance_date):
    phase9_thesis_gate_enabled: bool = True
    phase9_core_megacap_percentile: float = 0.95           # top 5%  -> mega-cap auto-core
    phase9_core_quality_size_percentile: float = 0.70      # top 30% size for "quality" core
    phase9_future_size_lower_percentile: float = 0.30      # bottom of future band
    phase9_future_size_upper_percentile: float = 0.95      # top of future band (mega excluded)
    phase9_early_size_upper_percentile: float = 0.70       # bottom 70% (excludes top 30% large-mega)
    # Quality thresholds for core "rule 2"
    phase9_core_quality_min_roe: float = 0.15
    phase9_core_quality_min_margin: float = 0.10           # net OR op margin
    phase9_core_quality_rev_growth_min: float = 0.02       # 안정 성장 하한
    phase9_core_quality_rev_growth_max: float = 0.30       # hyper-grow 는 future
    # Future criteria
    phase9_future_min_rev_growth: float = 0.20
    phase9_future_min_mom_24m: float = 0.50                # 2-year mom OR rev growth gate
    # Early signal thresholds (data-validated; Phase 1 inflection scores
    # rarely reach > 1.0 cross-sectionally so calibrated to 0.3 / 0.5)
    phase9_early_inflection_threshold: float = 0.3         # turnaround / cf_inflection
    phase9_early_value_inflection_threshold: float = 0.5   # value_inflection_score
    phase9_early_breakout_threshold: float = 0.5           # breakout_fresh_20d
    phase9_early_golden_cross_threshold: float = 0.3       # golden_cross_fresh_20d

    # --------------- Phase 9 C3: EPS turn-positive gate ---------------
    # Adds 2 new admission branches to the early-scout gate (inside the
    # Phase 9 C2 thesis-gate block):
    #   (1) _p9_eps_turn_positive: any of profit/cashflow/roe turn-positive
    #       flag > 0.5 (binary, from fund_panel _sign_flip_pos helper).
    #   (2) _p9_still_loss_but_improving: net_income_ttm < 0 AND
    #       (ocf_under_loss_growth > threshold OR fcf_under_loss_growth >
    #       threshold OR ni_loss_narrowing_4q > threshold).
    # Encodes the user definition of early sleeve exactly: "eps 적자거나
    # 양전환 막 하거나" (still losing OR just turned positive). C3 is
    # DEPENDENT on C2 (ships together when C2 active); disabling this
    # toggle reverts to pure C2 (inflect/breakout) gate.
    phase9_c3_turnaround_enabled: bool = True
    phase9_c3_loss_narrowing_threshold: float = 0.3

    # --------------- Phase 11: Multibagger Watch Sleeve ---------------
    # 4th sleeve alongside core_compounder / future_winner / early_scout.
    # 3 ML classifiers (entry + take_profit + stop_loss) identify stocks
    # that match the multibagger lifecycle pattern. See
    # research/phase11_*.py for the underlying training methodology.
    # Default OFF -- must be explicitly enabled via env or cfg for A/B testing.
    phase11_multibagger_sleeve_enabled: bool = False
    phase11_sleeve_size: int = 5                       # top N by P(entry) selected each month
    phase11_allocation_pct: float = 0.20               # portion of portfolio weight allocated to this sleeve (walk-forward optimum: 20%)
    phase11_p_entry_threshold: float = 0.30            # minimum P(entry) for selection
    phase11_p_takeprofit_threshold: float = 0.50       # P(tp) above this -> exclude from sleeve (익절)
    phase11_p_stoploss_threshold: float = 0.70         # P(sl) above this -> exclude from sleeve (손절)
    phase11_p_stoploss_select_threshold: float = 0.50  # softer P(sl) cap at selection time
    phase11_quality_min_mcap: float = 1e9              # $1B minimum at selection time
    phase11_quality_min_revenue: float = 1e8           # $100M revenues_ttm
    phase11_weighting_mode: str = "pscore"             # "equal" | "pscore" (P(entry)-weighted)
    phase11_classifier_iterations: int = 500           # CatBoost iterations
    phase11_classifier_depth: int = 6
    phase11_classifier_learning_rate: float = 0.03
    phase11_min_positive_examples: int = 30            # skip training if < this many positives in label set
    phase11_train_split_date: str = "2022-06-30"       # train/evaluate split for diagnostic output

    # --------------- breakout entry gate ---------------
    early_scout_breakout_min_score: float = 0.15        # minimum breakout_setup_quality for scout entry
    # --------------- fast mode ---------------
    fast_mode: bool = False  # set True to cut Phase 4+5 runtime by ~60%


__all__ = [
    "PHASE2_INDUSTRY_COLUMNS",
    "PHASE5_LEADER_LAGGARD_COLUMNS",
    "PHASE1_ALPHA_COLUMNS",
    "PHASE8B_LONG_LOOKBACK_COLUMNS",
    "PHASE9_C3_TURNAROUND_COLUMNS",
    "CRISIS_SECTOR_BENEFICIARIES",
    "CORE_FUNDAMENTAL_COLUMNS",
    "MACRO_PRICE_TICKERS",
    "MACRO_FRED_SERIES",
    "CNN_FEAR_GREED_URL",
    "CNN_FEAR_GREED_HEADERS",
    "ROBUST_Z_WINSOR_P",
    "ROBUST_Z_CLIP",
    "MACRO_REGIME_COLUMNS",
    "MACRO_INTERACTION_COLUMNS",
    "DYNAMIC_LEADER_COLUMNS",
    "MOAT_PROXY_COLUMNS",
    "TREND_TEMPLATE_COLUMNS",
    "MARKET_ADAPTATION_COLUMNS",
    "BENCHMARK_RELATIVE_COLUMNS",
    "REGIME_ROTATION_COLUMNS",
    "LIVE_EVENT_ALERT_COLUMNS",
    "FUND_TTM_FALLBACK_COLUMNS",
    "DEFAULT_FEATURES",
    "PILLAR_SCORE_COLUMNS",
    "FUNDAMENTAL_COVERAGE_COLUMNS",
    "SEC_13F_COLUMNS",
    "SEC_FORM345_COLUMNS",
    "LATEST_ONLY_SIGNAL_COLUMNS",
    "LATEST_ONLY_ACCEPTANCE_COLUMNS",
    "ACTUAL_PRIORITY_COLUMNS",
    "SLEEVE_FACTOR_REGIME_MULTIPLIERS",
    "SLEEVE_FACTOR_REGIME_MULTIPLIER_CLAMP",
    "SATELLITE_ONLY_FEATURE_COLUMNS",
    "CRITICAL_TTM_COVERAGE_COLUMNS",
    "CRITICAL_VALUATION_COVERAGE_COLUMNS",
    "COMPREHENSIVE_FUNDAMENTAL_COVERAGE_COLUMNS",
    "HISTORICAL_FUNDAMENTAL_LEVEL_COLUMNS",
    "HISTORICAL_FUNDAMENTAL_CHANGE_COLUMNS",
    "HISTORICAL_FUNDAMENTAL_CAGR_COLUMNS",
    "HISTORICAL_FUNDAMENTAL_QUALITY_COLUMNS",
    "HISTORICAL_FUNDAMENTAL_HISTORY_COLUMNS",
    "FORWARD_RETURN_COVERAGE_COLUMNS",
    "HISTORICAL_DATA_QUALITY_COLUMNS",
    "CORE_FUNDAMENTAL_MINIMUM_FIELDS",
    "PHASE11_MULTIBAGGER_COLUMNS",
    "REGIME_LABEL_NEAREST_FALLBACKS",
    "YF_OVERRIDES",
    "HEADERS_ISHARES",
    "SCAN_PATTERNS",
    "FSDS_TAGS",
    "FSDS_TAG_ALIASES",
    "FSDS_TAG_CANON",
    "BAL_TAGS",
    "FLOW_TAGS",
    "NEEDED_TAGS",
    "YF_QUARTERLY_COL_MAP",
    "ACCEPTED_SEC_FORMS",
    "SECTOR_GATE_FINANCIAL_KEYWORDS",
    "SECTOR_GATE_REAL_ASSET_KEYWORDS",
    "SECTOR_GATE_RESOURCE_KEYWORDS",
    "SAGE_SECTOR_MAP",
    "YF_INDUSTRY_TO_GICS_GROUP",
    "ENGINE_REUSE_VERSION",
    "TICKER_RE",
    "EXCLUDE_NAME",
    "CASH_PROXY_TICKER",
    "SEC_COMPANYFACTS_MEMBER_RE",
    "default_manual_regime_conditioned_sleeve_map",
    "EngineConfig",
]
