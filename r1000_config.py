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
PHASE9_C3_TURNAROUND_COLUMNS = [
    "profit_turn_positive_4q",
    "cashflow_turn_positive_4q",
    "roe_turn_positive_4q",
    "any_profitability_turn_positive_4q",
    "roe_sign_flip_pos",
    "ocf_under_loss_growth",
    "fcf_under_loss_growth",
    "ni_loss_narrowing_4q",
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
] + MACRO_REGIME_COLUMNS + MACRO_INTERACTION_COLUMNS + DYNAMIC_LEADER_COLUMNS + MARKET_ADAPTATION_COLUMNS + BENCHMARK_RELATIVE_COLUMNS + REGIME_ROTATION_COLUMNS + LIVE_EVENT_ALERT_COLUMNS

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

ENGINE_REUSE_VERSION = "2026-04-18-phase9c3-turnaround-flags"

TICKER_RE = re.compile(r"^[A-Z0-9]{1,6}([.-][A-Z0-9]{1,4})?$")
EXCLUDE_NAME = ("ETF", "ETN", "TRUST", "FUND", "INDEX", "NOTES", "NOTE")
CASH_PROXY_TICKER = "CASH"
SEC_COMPANYFACTS_MEMBER_RE = re.compile(r"(?:^|/)(?:CIK)?(\d{10})\.json$", re.IGNORECASE)

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
]
