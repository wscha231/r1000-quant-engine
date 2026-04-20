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


__all__ = [
    "PHASE1_ALPHA_COLUMNS",
    "PHASE2_INDUSTRY_COLUMNS",
    "PHASE5_LEADER_LAGGARD_COLUMNS",
    "PHASE8B_LONG_LOOKBACK_COLUMNS",
    "PHASE9_C3_TURNAROUND_COLUMNS",
]
