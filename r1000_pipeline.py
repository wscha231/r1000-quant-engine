"""r1000 Quant Engine -- pipeline orchestration module.

Stage 5 (2026-04-20): full pipeline extracted from r1000_top30_institutional.py
during Refactor Phase A. This module owns:
  - Universe + feature_store builders (build_universe_monthly, build_feature_store)
  - ML training (train_walkforward) + backtest (backtest_portfolio)
  - Latest recommendations (build_latest_recommendations, build_latest_portfolio)
  - Concentrated grid (select/backtest/compare_concentrated_portfolio_*)
  - Sleeve-cap policy comparison (generate/compare_sleeve_cap_policy_*)
  - Standalone sleeve backtest (backtest_standalone_sleeve_topn + comparer)
  - Macro regime builders deferred from Stage 3d-ii-b
  - Export + run-all orchestration (export_outputs, run_all, run_default_pipeline)
  - Validation (validate_config, run_full_validation_suite)

Import discipline
-----------------
    r1000_config.py       (pure data, stdlib)
        ^
    r1000_helpers.py      (pure helpers, numpy/pandas)
        ^
    r1000_features.py     (feature engineering)
        ^
    r1000_signals.py      (sleeve composition, portfolio construction)
        ^
    r1000_pipeline.py     (THIS FILE -- orchestration, training, backtest,
                           export, validation, run_all)
        ^
    r1000_top30_institutional.py  (FACADE -- re-exports everything from
                                   r1000_pipeline for backward compat)

r1000_pipeline.py may import from r1000_config / r1000_helpers /
r1000_features / r1000_signals but NEVER from the main engine facade.
"""

from __future__ import annotations

import importlib
import io
import json
import logging
import math
import os
import re
import shutil
import subprocess
import time
import zipfile
import hashlib
import warnings
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
import pickle
from typing import Any, Dict, Iterable, Mapping, Optional

try:
    from catboost import CatBoostClassifier, CatBoostRanker, CatBoostRegressor, Pool
except Exception:  # catboost not strictly required at import time
    CatBoostClassifier = CatBoostRanker = CatBoostRegressor = Pool = None  # type: ignore
try:
    from sklearn.preprocessing import StandardScaler
except Exception:
    StandardScaler = None  # type: ignore

import numpy as np
import pandas as pd
import requests
import yfinance as yf
from sklearn.linear_model import LogisticRegression, Ridge
try:
    import pandas_market_calendars as mcal
except Exception:
    mcal = None

# Refactor Phase A Stage 1a (2026-04-20): PHASE*_COLUMNS extracted to
# r1000_config.py (pure-data whitelist constants). Other constants +
# EngineConfig still live below; they migrate in Stage 1b/c/d.
# See REFACTOR_PLAN.md §6 checklist + CHANGELOG 2026-04-20 entry.
from r1000_config import (
    PHASE2_INDUSTRY_COLUMNS,
    PHASE5_LEADER_LAGGARD_COLUMNS,
    PHASE1_ALPHA_COLUMNS,
    PHASE8B_LONG_LOOKBACK_COLUMNS,
    PHASE9_C3_TURNAROUND_COLUMNS,
    PHASE11_MULTIBAGGER_COLUMNS,
    CRISIS_SECTOR_BENEFICIARIES,
    CORE_FUNDAMENTAL_COLUMNS,
    MACRO_PRICE_TICKERS,
    MACRO_FRED_SERIES,
    CNN_FEAR_GREED_URL,
    CNN_FEAR_GREED_HEADERS,
    ROBUST_Z_WINSOR_P,
    ROBUST_Z_CLIP,
    MACRO_REGIME_COLUMNS,
    MACRO_INTERACTION_COLUMNS,
    DYNAMIC_LEADER_COLUMNS,
    MOAT_PROXY_COLUMNS,
    TREND_TEMPLATE_COLUMNS,
    MARKET_ADAPTATION_COLUMNS,
    BENCHMARK_RELATIVE_COLUMNS,
    REGIME_ROTATION_COLUMNS,
    LIVE_EVENT_ALERT_COLUMNS,
    FUND_TTM_FALLBACK_COLUMNS,
    DEFAULT_FEATURES,
    PILLAR_SCORE_COLUMNS,
    FUNDAMENTAL_COVERAGE_COLUMNS,
    SEC_13F_COLUMNS,
    SEC_FORM345_COLUMNS,
    LATEST_ONLY_SIGNAL_COLUMNS,
    LATEST_ONLY_ACCEPTANCE_COLUMNS,
    ACTUAL_PRIORITY_COLUMNS,
    SLEEVE_FACTOR_REGIME_MULTIPLIERS,
    SLEEVE_FACTOR_REGIME_MULTIPLIER_CLAMP,
    SATELLITE_ONLY_FEATURE_COLUMNS,
    CRITICAL_TTM_COVERAGE_COLUMNS,
    CRITICAL_VALUATION_COVERAGE_COLUMNS,
    COMPREHENSIVE_FUNDAMENTAL_COVERAGE_COLUMNS,
    HISTORICAL_FUNDAMENTAL_LEVEL_COLUMNS,
    HISTORICAL_FUNDAMENTAL_CHANGE_COLUMNS,
    HISTORICAL_FUNDAMENTAL_CAGR_COLUMNS,
    HISTORICAL_FUNDAMENTAL_QUALITY_COLUMNS,
    HISTORICAL_FUNDAMENTAL_HISTORY_COLUMNS,
    FORWARD_RETURN_COVERAGE_COLUMNS,
    HISTORICAL_DATA_QUALITY_COLUMNS,
    CORE_FUNDAMENTAL_MINIMUM_FIELDS,
    REGIME_LABEL_NEAREST_FALLBACKS,
    YF_OVERRIDES,
    HEADERS_ISHARES,
    SCAN_PATTERNS,
    FSDS_TAGS,
    FSDS_TAG_ALIASES,
    FSDS_TAG_CANON,
    BAL_TAGS,
    FLOW_TAGS,
    NEEDED_TAGS,
    YF_QUARTERLY_COL_MAP,
    ACCEPTED_SEC_FORMS,
    SECTOR_GATE_FINANCIAL_KEYWORDS,
    SECTOR_GATE_REAL_ASSET_KEYWORDS,
    SECTOR_GATE_RESOURCE_KEYWORDS,
    SAGE_SECTOR_MAP,
    YF_INDUSTRY_TO_GICS_GROUP,
    ENGINE_REUSE_VERSION,
    TICKER_RE,
    EXCLUDE_NAME,
    CASH_PROXY_TICKER,
    SEC_COMPANYFACTS_MEMBER_RE,
    default_manual_regime_conditioned_sleeve_map,
    EngineConfig,
)

# Refactor Phase A Stage 2a (2026-04-20): pure utility helpers moved to
# r1000_helpers.py. See REFACTOR_PLAN.md §6 migration order step 2.
from r1000_helpers import (
    _resolve_engine_commit_sha,
    ENGINE_COMMIT_SHA,
    phase_is_enabled,
    now_ts,
    log,
    apply_fast_mode,
    to_cfg,
    configure_last_n_years_backtest,
    winsorize,
    robust_z,
    squeeze_series,
    hard_sanitize,
    safe_float,
    cross_sectional_robust_z,
    cross_sectional_robust_z_by_sector,
    numeric_series_or_default,
    rolling_robust_z,
    row_mean,
    weighted_sleeve_composite,
    mount_drive_if_colab,
    safe_mkdir,
    append_history_parquet,
    safe_read_json_file,
    safe_read_parquet_file,
    safe_run_token,
    current_git_commit,
    build_run_identity,
    archive_run_outputs,
    get_paths,
    load_previous_live_weights,
    load_previous_live_policy,
    _robust_retry,
    _http_get_inner,
    http_get,
    normalize_ticker,
    is_valid_ticker,
    is_valid_price_symbol,
    looks_like_noncommon,
    px_cache_name,
    to_yf_symbol,
    companyfacts_cache_file,
    normalize_cik10,
    normalize_cik_list,
    normalize_cik_series,
    cache_live_file,
    cache_live_statement_file,
    is_cache_fresh,
    effective_alpha_vantage_refresh_tickers,
    effective_latest_statement_repair_tickers,
    effective_latest_statement_refresh_days,
    alpha_vantage_pause_seconds,
)

# Refactor Phase A Stage 3a (2026-04-20): industry feature engineering
# moved to r1000_features.py (Phase 2 RS + O'Neil leadership + sub-industry
# leader/laggard + rotation). See REFACTOR_PLAN.md §6 migration step 3.
from r1000_features import (
    _demean_within_group,
    _group_mean_to_row,
    add_industry_relative_strength,
    add_industry_rotation_signal,
    add_sub_industry_leader_laggard_signals,
    alpha_vantage_get,
    alpha_vantage_reports_frame,
    attach_industry_metadata,
    compute_actual_priority_columns,
    compute_flow_ttm_with_cum_fallback,
    compute_fundamental_trend_features,
    compute_latest_flow_factor_columns,
    compute_live_factor_columns,
    compute_moat_proxy_features,
    compute_oneil_leadership_score,
    compute_sage_sector_labels,
    count_present_columns,
    datetime_series_or_default,
    fetch_alpha_vantage_earnings_estimates,
    fetch_alpha_vantage_overview,
    fetch_alpha_vantage_statement_snapshot,
    fetch_live_fundamentals_one,
    fetch_yf_live_fundamentals,
    fetch_yfinance_quarterly_statements,
    first_numeric_from_report,
    has_present_value,
    load_cached_json_if_any,
    load_or_fetch_alpha_vantage_statement_snapshot,
    map_yf_industry_to_group,
    merge_live_fundamentals,
    merge_trend_features_into_monthly,
    normalize_table_columns,
    normalized_sector_labels,
    preserve_cached_fields,
    refresh_live_fundamentals,
    repair_latest_statement_fundamentals,
    sector_keyword_mask,
    statement_snapshot_has_payload,
    sum_first_numeric_column,
    sum_latest_numeric_reports,
    summarize_holder_table,
    summarize_insider_transactions,
    yf_table_or_empty,
    yoy_latest_numeric_reports,
    _flexible_lag,
    _cagr_from_lag,
    recompute_fund_panel_derived_columns,
    compute_event_regime_features,
    sector_indicator,
    compute_macro_interaction_features,
    compute_market_adaptation_features,
    compute_dynamic_leadership_features,
    load_manual_moat_overrides,
    apply_manual_ticker_overlays,
    compute_three_level_relative_strength,
    compute_crisis_sector_fit,
    compute_strategy_blueprint_columns,
    compute_multidimensional_pillar_scores,
    compute_minervini_momentum_overlay,
)

# Refactor Phase A Stage 4a (2026-04-20): sleeve composition +
# portfolio construction moved to r1000_signals.py.
from r1000_signals import (
    sleeve_weight_l1_norm,
    resolve_regime_sleeve_multipliers,
    add_historical_data_quality_columns,
    compute_portfolio_sleeve_columns,
    compute_portfolio_sleeve_policy,
    compute_regime_portfolio_controls,
    compute_benchmark_beating_focus_overlay,
    apply_portfolio_candidate_gate_filter,
    compute_dynamic_sector_caps,
    select_topn_with_sector_limits,
    choose_dynamic_target_count,
    resolve_dynamic_weight_cap,
    truncate_weight_dict,
    materialize_weight_frame,
    company_key_series,
    dedupe_same_company_rows,
    apply_hold_policy_overlay,
    apply_sleeve_entry_drift_name_caps,
    build_target_portfolio,
    normalize_with_limits,
    apply_sector_weight_caps,
    dict_from_weights,
    apply_cash_buffer_to_weights,
    drift_weights_by_period_returns,
    turnover,
    cap_turnover,
    accelerate_cash_deployment,
    resolve_regime_conditioned_sleeve_override,
)

warnings.filterwarnings("ignore")
logging.getLogger("yfinance").setLevel(logging.CRITICAL)
logging.getLogger("yfinance").propagate = False
logging.getLogger("urllib3").setLevel(logging.WARNING)

# Stage 1d-i (2026-04-20): ENGINE_REUSE_VERSION moved to r1000_config.py.


# Stage 2a (2026-04-20): _resolve_engine_commit_sha + ENGINE_COMMIT_SHA
# moved to r1000_helpers.py (re-imported at file top).


# Stage 2a (2026-04-20): phase_is_enabled moved to r1000_helpers.py.


# Stage 1d-i (2026-04-20): TICKER_RE, EXCLUDE_NAME, CASH_PROXY_TICKER,
# SEC_COMPANYFACTS_MEMBER_RE moved to r1000_config.py (imported at file top).
_COMPANYFACTS_BULK_MEMBER_MAP_CACHE: dict[str, dict[str, str]] = {}
_CATBOOST_COMPONENTS_CACHE: Optional[dict[str, Any]] = None


# Stage 1d-ii (2026-04-20): default_manual_regime_conditioned_sleeve_map
# moved to r1000_config.py (it is the default_factory for EngineConfig
# field; re-imported at file top for the 3 call sites that compose it
# against user-supplied overrides).



# Stage 1c (2026-04-20): REGIME_LABEL_NEAREST_FALLBACKS + YF_OVERRIDES
# + HEADERS_ISHARES + SCAN_PATTERNS + FSDS_TAGS/ALIASES/CANON + BAL_TAGS
# + FLOW_TAGS + NEEDED_TAGS + YF_QUARTERLY_COL_MAP + ACCEPTED_SEC_FORMS
# + SECTOR_GATE_* + SAGE_SECTOR_MAP + YF_INDUSTRY_TO_GICS_GROUP moved to
# r1000_config.py. Import block at file top is extended accordingly.



# Stage 3a (2026-04-20): 8 industry functions (map_yf_industry_to_group,
# attach_industry_metadata, _demean_within_group, _group_mean_to_row,
# add_industry_relative_strength, compute_oneil_leadership_score,
# add_sub_industry_leader_laggard_signals, add_industry_rotation_signal)
# moved to r1000_features.py.



# Stage 1d-ii (2026-04-20): EngineConfig dataclass moved to r1000_config.py.
# Every tunable knob (cache TTLs, walk-forward windows, sleeve weights,
# Phase 1..9 toggles, concentrated grid candidates, API keys) lives there.
# apply_fast_mode() below is a helper function - stays in main (Stage 2 target).



# Stage 2b (2026-04-20): apply_fast_mode moved to r1000_helpers.py.


# Stage 2a (2026-04-20): now_ts + log moved to r1000_helpers.py.


# Stage 2b (2026-04-20): to_cfg moved to r1000_helpers.py.


# Stage 2b (2026-04-20): configure_last_n_years_backtest moved to r1000_helpers.py.



def run_last_n_years_backtest(
    cfg: Optional[dict | EngineConfig] = None,
    years: int = 5,
    *,
    end_date: Optional[str] = None,
    train_lookback_years: Optional[int] = None,
    reuse_existing_artifacts: Optional[bool] = None,
    resume_partial_walkforward: Optional[bool] = None,
) -> dict[str, Any]:
    cfg_obj = configure_last_n_years_backtest(
        cfg,
        years=years,
        end_date=end_date,
        train_lookback_years=train_lookback_years,
    )
    if reuse_existing_artifacts is not None:
        cfg_obj.reuse_existing_artifacts = bool(reuse_existing_artifacts)
    if resume_partial_walkforward is not None:
        cfg_obj.resume_partial_walkforward = bool(resume_partial_walkforward)
    log(
        "Running rolling backtest window "
        f"{cfg_obj.start_date} -> {cfg_obj.end_date} "
        f"(window_years={years}, train_lookback_years={cfg_obj.train_lookback_years})"
    )
    return run_all(cfg_obj)


def run_default_pipeline(cfg: Optional[dict | EngineConfig] = None) -> dict[str, Any]:
    cfg_obj = to_cfg(cfg)
    window_years = max(int(cfg_obj.default_backtest_years), 1)
    log(
        f"[commit={ENGINE_COMMIT_SHA}] [engine_version={ENGINE_REUSE_VERSION}] "
        "Running default full pipeline with rolling window "
        f"(years={window_years}, end_date={cfg_obj.end_date}, "
        f"reuse_existing_artifacts={cfg_obj.reuse_existing_artifacts}, "
        f"resume_partial_walkforward={cfg_obj.resume_partial_walkforward})"
    )
    return run_last_n_years_backtest(
        cfg_obj,
        years=window_years,
        end_date=cfg_obj.end_date,
        train_lookback_years=cfg_obj.train_lookback_years,
        reuse_existing_artifacts=cfg_obj.reuse_existing_artifacts,
        resume_partial_walkforward=cfg_obj.resume_partial_walkforward,
    )


# Stage 2d (2026-04-20): 27 helpers (mount_drive, safe_mkdir,
# append_history_parquet, safe_read_*, safe_run_token, current_git_commit,
# build_run_identity, archive_run_outputs, get_paths, load_previous_live_*,
# _robust_retry, _http_get_inner, normalize_ticker, is_valid_*,
# px_cache_name, to_yf_symbol, cache_live_*, is_cache_fresh,
# effective_*_refresh_*, alpha_vantage_pause_seconds) moved to
# r1000_helpers.py.



# Stage 3b (2026-04-20): 28 data-fetch + fundamental trend functions
# (alpha_vantage_*, yf_* fetchers, repair_latest_statement_fundamentals,
# refresh_live_fundamentals, compute_fundamental_trend_features,
# merge_*_features, compute_sage_sector_labels) moved to r1000_features.py.



# Stage 3c (2026-04-20): datetime_series_or_default + count_present_columns
# + normalized_sector_labels + sector_keyword_mask + compute_live_factor_columns
# + compute_actual_priority_columns + compute_latest_flow_factor_columns
# + compute_moat_proxy_features moved to r1000_features.py.



def apply_latest_only_signal_guard(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    if d.empty or "rebalance_date" not in d.columns:
        return d
    rebalance = pd.to_datetime(d["rebalance_date"], errors="coerce")
    if rebalance.notna().sum() == 0:
        return d
    latest_dt = rebalance.max()
    history_mask = rebalance < latest_dt
    for c in LATEST_ONLY_SIGNAL_COLUMNS:
        if c not in d.columns:
            d[c] = np.nan
        d.loc[history_mask, c] = np.nan
    if "return_on_equity_effective" in d.columns:
        roe_proxy = numeric_series_or_default(d, "roe_proxy", np.nan)
        d.loc[history_mask, "return_on_equity_effective"] = roe_proxy.loc[history_mask]
    return d


def clear_latest_only_signal_columns(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    for c in LATEST_ONLY_SIGNAL_COLUMNS:
        if c in d.columns:
            d[c] = np.nan
    if "return_on_equity_effective" in d.columns:
        d["return_on_equity_effective"] = numeric_series_or_default(d, "roe_proxy", np.nan)
    return d


def add_core_fundamental_minimum_flags(df: pd.DataFrame, cfg: EngineConfig) -> pd.DataFrame:
    d = df.copy()
    required_cols = [c for c in CORE_FUNDAMENTAL_MINIMUM_FIELDS if c in d.columns]
    if not required_cols:
        d["core_fundamental_fields_present"] = 0
        d["sector_adjusted_fields_present"] = 0
        d["partial_scout_confirmation_score"] = 0.0
        d["sector_adjusted_fundamental_pass"] = False
        d["partial_scout_fundamental_pass"] = False
        d["fundamental_lane_label"] = "insufficient"
        d["core_fundamental_minimum_pass"] = False
        return d

    d["core_fundamental_fields_present"] = count_present_columns(d, required_cols)
    full_pass = d["core_fundamental_fields_present"] >= int(cfg.min_core_fundamental_fields_required)

    sector_labels = normalized_sector_labels(d)
    finance_mask = sector_keyword_mask(sector_labels, SECTOR_GATE_FINANCIAL_KEYWORDS)
    real_asset_mask = sector_keyword_mask(sector_labels, SECTOR_GATE_REAL_ASSET_KEYWORDS)
    resource_mask = sector_keyword_mask(sector_labels, SECTOR_GATE_RESOURCE_KEYWORDS)

    sector_adjusted_fields_present = pd.Series(0, index=d.index, dtype=int)
    sector_adjusted_pass = pd.Series(False, index=d.index, dtype=bool)
    if bool(getattr(cfg, "sector_adjusted_gate_enabled", True)):
        financial_present = count_present_columns(
            d,
            [
                "assets",
                "liabilities",
                "net_income_ttm",
                "ep_ttm",
                "return_on_equity_effective",
                "roa_proxy",
                "book_to_market_proxy",
                "sector_adjusted_quality_score",
            ],
        )
        real_asset_present = count_present_columns(
            d,
            [
                "assets",
                "liabilities",
                "revenues_ttm",
                "net_income_ttm",
                "sp_ttm",
                "fcfy_ttm",
                "dividend_policy_score",
                "sector_adjusted_quality_score",
            ],
        )
        resource_present = count_present_columns(
            d,
            [
                "assets",
                "liabilities",
                "revenues_ttm",
                "net_income_ttm",
                "ocf_ttm",
                "fcfy_ttm",
                "sector_adjusted_quality_score",
            ],
        )
        sector_adjusted_fields_present = sector_adjusted_fields_present.where(~finance_mask, financial_present)
        sector_adjusted_fields_present = sector_adjusted_fields_present.where(~real_asset_mask, real_asset_present)
        sector_adjusted_fields_present = sector_adjusted_fields_present.where(~resource_mask, resource_present)
        sector_adjusted_pass = sector_adjusted_pass | (
            finance_mask & (financial_present >= int(cfg.sector_adjusted_financial_min_fields))
        )
        sector_adjusted_pass = sector_adjusted_pass | (
            real_asset_mask & (real_asset_present >= int(cfg.sector_adjusted_realasset_min_fields))
        )
        sector_adjusted_pass = sector_adjusted_pass | (
            resource_mask & (resource_present >= int(cfg.sector_adjusted_resource_min_fields))
        )

    score_series = (
        pd.to_numeric(d["score"], errors="coerce")
        if "score" in d.columns
        else pd.Series(np.nan, index=d.index, dtype=float)
    )
    if score_series.notna().any():
        partial_score_floor = max(
            float(getattr(cfg, "partial_scout_score_floor", 0.0)),
            float(score_series.quantile(0.80)),
        )
    else:
        partial_score_floor = float("inf")
    partial_confirmation = row_mean(
        [
            (numeric_series_or_default(d, "event_reaction_score", 0.0) > 0.10).astype(float),
            (numeric_series_or_default(d, "dynamic_leader_score", 0.0) > 0.10).astype(float),
            (numeric_series_or_default(d, "rs_benchmark_6m", 0.0) > 0.0).astype(float),
            (numeric_series_or_default(d, "mom_6m", 0.0) > 0.0).astype(float),
            (numeric_series_or_default(d, "sales_growth_yoy", np.nan) > 0.05).astype(float),
            (numeric_series_or_default(d, "fundamental_presence_score", 0.0) >= 0.40).astype(float),
            (numeric_series_or_default(d, "sector_adjusted_quality_score", 0.0) > 0.0).astype(float),
        ],
        d.index,
    ).fillna(0.0)
    partial_scout_pass = pd.Series(False, index=d.index, dtype=bool)
    if bool(getattr(cfg, "partial_scout_gate_enabled", True)):
        partial_scout_pass = (
            ~full_pass
            & ~sector_adjusted_pass
            & (d["core_fundamental_fields_present"] >= int(cfg.partial_scout_min_fields))
            & (numeric_series_or_default(d, "fundamental_presence_score", 0.0) >= 0.40)
            & (numeric_series_or_default(d, "fundamental_reliability_score", 0.0) >= 0.45)
            & (partial_confirmation >= float(cfg.partial_scout_confirmation_min))
            & (score_series >= partial_score_floor)
        )
    future_confirmation = row_mean(
        [
            (numeric_series_or_default(d, "event_reaction_score", 0.0) > 0.05).astype(float),
            (numeric_series_or_default(d, "dynamic_leader_score", 0.0) > 0.05).astype(float),
            (numeric_series_or_default(d, "leader_emergence_score", 0.0) > 0.05).astype(float),
            (numeric_series_or_default(d, "rs_benchmark_6m", 0.0) > 0.0).astype(float),
            (numeric_series_or_default(d, "mom_6m", 0.0) > 0.0).astype(float),
            (numeric_series_or_default(d, "sales_growth_yoy", np.nan) > 0.0).astype(float),
            (
                numeric_series_or_default(d, "fundamental_presence_score", 0.0)
                >= float(getattr(cfg, "future_winner_fundamental_presence_min", 0.32))
            ).astype(float),
            (
                numeric_series_or_default(d, "fundamental_reliability_score", 0.0)
                >= float(getattr(cfg, "future_winner_fundamental_reliability_min", 0.36))
            ).astype(float),
        ],
        d.index,
    ).fillna(0.0)
    early_confirmation = row_mean(
        [
            (numeric_series_or_default(d, "event_reaction_score", 0.0) > 0.05).astype(float),
            (numeric_series_or_default(d, "growth_onset_composite", 0.0) > 0.0).astype(float),
            (numeric_series_or_default(d, "profitability_inflection_score", 0.0) > 0.0).astype(float),
            (numeric_series_or_default(d, "technical_blueprint_score", 0.0) > 0.0).astype(float),
            (numeric_series_or_default(d, "breakout_setup_quality_score", 0.0)
             >= float(getattr(cfg, "early_scout_breakout_min_score", 0.15))).astype(float),
            (numeric_series_or_default(d, "rs_benchmark_3m", 0.0) > 0.0).astype(float),
            (numeric_series_or_default(d, "rs_benchmark_6m", 0.0) > 0.0).astype(float),
            (
                numeric_series_or_default(d, "fundamental_presence_score", 0.0)
                >= float(getattr(cfg, "early_scout_fundamental_presence_min", 0.18))
            ).astype(float),
        ],
        d.index,
    ).fillna(0.0)
    future_relaxed_pass = (
        ~full_pass
        & ~sector_adjusted_pass
        & (
            d["core_fundamental_fields_present"]
            >= int(getattr(cfg, "future_winner_min_fundamental_fields_required", 3))
        )
        & (
            numeric_series_or_default(d, "fundamental_presence_score", 0.0)
            >= float(getattr(cfg, "future_winner_fundamental_presence_min", 0.32))
        )
        & (
            numeric_series_or_default(d, "fundamental_reliability_score", 0.0)
            >= float(getattr(cfg, "future_winner_fundamental_reliability_min", 0.36))
        )
        & (
            future_confirmation
            >= float(getattr(cfg, "future_winner_confirmation_min", 0.42))
        )
    )
    early_relaxed_pass = (
        ~full_pass
        & ~sector_adjusted_pass
        & (
            d["core_fundamental_fields_present"]
            >= int(getattr(cfg, "early_scout_min_fundamental_fields_required", 2))
        )
        & (
            numeric_series_or_default(d, "fundamental_presence_score", 0.0)
            >= float(getattr(cfg, "early_scout_fundamental_presence_min", 0.18))
        )
        & (
            numeric_series_or_default(d, "fundamental_reliability_score", 0.0)
            >= float(getattr(cfg, "early_scout_fundamental_reliability_min", 0.24))
        )
        & (
            early_confirmation
            >= float(getattr(cfg, "early_scout_confirmation_min", 0.34))
        )
    )

    d["sector_adjusted_fields_present"] = sector_adjusted_fields_present.astype(int)
    d["partial_scout_confirmation_score"] = partial_confirmation
    d["future_winner_confirmation_score"] = future_confirmation
    d["early_scout_confirmation_score"] = early_confirmation
    d["sector_adjusted_fundamental_pass"] = sector_adjusted_pass
    d["partial_scout_fundamental_pass"] = partial_scout_pass
    d["future_winner_fundamental_pass"] = full_pass | sector_adjusted_pass | future_relaxed_pass
    d["early_scout_fundamental_pass"] = full_pass | sector_adjusted_pass | partial_scout_pass | early_relaxed_pass
    d["fundamental_lane_label"] = "insufficient"
    d.loc[partial_scout_pass, "fundamental_lane_label"] = "partial_scout"
    d.loc[sector_adjusted_pass, "fundamental_lane_label"] = "sector_adjusted"
    d.loc[full_pass, "fundamental_lane_label"] = "full_ttm"
    d["core_fundamental_minimum_pass"] = full_pass | sector_adjusted_pass | partial_scout_pass
    return d


def apply_core_fundamental_minimum_filter(
    df: pd.DataFrame,
    cfg: EngineConfig,
    context: str,
) -> pd.DataFrame:
    d = add_core_fundamental_minimum_flags(df, cfg)
    if d.empty:
        return d
    keep_mask = d["core_fundamental_minimum_pass"].fillna(False).astype(bool)
    removed = int((~keep_mask).sum())
    kept = int(keep_mask.sum())
    if removed > 0:
        lane_summary = {}
        if "fundamental_lane_label" in d.columns:
            lane_counts = d.loc[keep_mask, "fundamental_lane_label"].astype(str).value_counts()
            lane_summary = {str(k): int(v) for k, v in lane_counts.items()}
        log(
            f"{context}: core fundamental minimum filter kept={kept}, removed={removed}, "
            f"required_fields>={int(cfg.min_core_fundamental_fields_required)}, "
            f"lanes={lane_summary}"
    )
    return d[keep_mask].copy()


def annotate_portfolio_candidate_gate(
    df: pd.DataFrame,
    cfg: EngineConfig,
) -> pd.DataFrame:
    d = add_core_fundamental_minimum_flags(df, cfg)
    if d.empty:
        return d
    sleeve_label = d.get(
        "portfolio_sleeve_label",
        d.get("portfolio_sleeve_label_raw", pd.Series("core_compounder", index=d.index, dtype=object)),
    ).fillna("core_compounder").astype(str)
    gate_keep = pd.Series(False, index=d.index, dtype=bool)
    gate_keep = gate_keep | (
        sleeve_label.eq("core_compounder")
        & d["core_fundamental_minimum_pass"].fillna(False).astype(bool)
    )
    gate_keep = gate_keep | (
        sleeve_label.eq("future_winner")
        & d["future_winner_fundamental_pass"].fillna(False).astype(bool)
    )
    gate_keep = gate_keep | (
        sleeve_label.eq("early_scout")
        & d["early_scout_fundamental_pass"].fillna(False).astype(bool)
    )
    d["portfolio_candidate_minimum_pass"] = gate_keep
    d["portfolio_candidate_gate_label"] = "rejected"
    d.loc[
        sleeve_label.eq("core_compounder") & gate_keep,
        "portfolio_candidate_gate_label",
    ] = "core_strict"
    d.loc[
        sleeve_label.eq("future_winner") & gate_keep,
        "portfolio_candidate_gate_label",
    ] = "future_relaxed"
    d.loc[
        sleeve_label.eq("early_scout") & gate_keep,
        "portfolio_candidate_gate_label",
    ] = "early_relaxed"
    return d


# Stage 4b-ii (2026-04-20): apply_portfolio_candidate_gate_filter -> r1000_signals.py.




def apply_latest_ranking_eligibility(
    df: pd.DataFrame,
    cfg: EngineConfig,
    context: str,
) -> pd.DataFrame:
    d = df.copy()
    if d.empty:
        d["ranking_eligible"] = False
        return d
    if "portfolio_sleeve_label" not in d.columns:
        d = compute_portfolio_sleeve_columns(d, cfg)
    d = annotate_portfolio_candidate_gate(d, cfg)
    d["ranking_eligible"] = d["portfolio_candidate_minimum_pass"].fillna(False).astype(bool)
    # Phase 9 C2 (2026-04-17): when thesis-gate is active, names labeled
    # "unassigned" (no clear archetype thesis) MUST be excluded from
    # portfolio candidates regardless of model score. This is the quality
    # gate that prevents "high-score-but-no-thesis" names (e.g. CVX with
    # rev -5% and no inflection signal) from entering the portfolio.
    if "portfolio_sleeve_label" in d.columns:
        _p9_unassigned_mask = d["portfolio_sleeve_label"].astype(str).eq("unassigned")
        if _p9_unassigned_mask.any():
            d.loc[_p9_unassigned_mask, "ranking_eligible"] = False
    eligible_count = int(d["ranking_eligible"].sum())
    ineligible_count = int(len(d) - eligible_count)
    if ineligible_count > 0:
        gate_summary = {
            str(k): int(v)
            for k, v in d.loc[d["ranking_eligible"], "portfolio_candidate_gate_label"].astype(str).value_counts().items()
        }
        sleeve_summary = {
            str(k): int(v)
            for k, v in d.loc[d["ranking_eligible"], "portfolio_sleeve_label"].fillna("core_compounder").astype(str).value_counts().items()
        }
        log(
            f"{context}: ranking eligibility kept={eligible_count}, removed={ineligible_count}, "
            f"gate_modes={gate_summary}, sleeves={sleeve_summary}"
        )
    return d


def add_total_score_columns(
    df: pd.DataFrame,
    cfg: EngineConfig,
    include_satellite: bool = False,
    include_latest_only_satellite: bool = False,
) -> pd.DataFrame:
    d = df.copy()
    actual_priority = numeric_series_or_default(df, "actual_priority_weight", 0.0).clip(lower=0.0, upper=1.0)
    proxy_fallback = numeric_series_or_default(df, "proxy_fallback_weight", 1.0).clip(lower=0.0, upper=1.0)
    actual_results = numeric_series_or_default(df, "actual_results_score", 0.0)
    fundamental_presence = numeric_series_or_default(d, "fundamental_presence_score", 0.0).clip(lower=0.0, upper=1.0)
    fundamental_reliability = numeric_series_or_default(
        d, "fundamental_reliability_score", fundamental_presence
    ).clip(lower=0.0, upper=1.0)
    market_fallback_confirmation = row_mean(
        [
            (numeric_series_or_default(d, "event_reaction_score", 0.0) > 0.10).astype(float),
            (numeric_series_or_default(d, "institutional_flow_signal_score", 0.0) > 0.10).astype(float),
            (numeric_series_or_default(d, "insider_flow_signal_score", 0.0) > 0.50).astype(float),
            (numeric_series_or_default(d, "actual_results_score", 0.0) > 0.05).astype(float),
            (numeric_series_or_default(d, "dynamic_leader_score", 0.0) > 0.10).astype(float),
            (numeric_series_or_default(d, "multidimensional_breadth_score", 0.0) > 0.50).astype(float),
        ],
        d.index,
    ).fillna(0.0)
    score_fundamental_confidence = pd.Series(
        np.maximum(fundamental_reliability.to_numpy(dtype=float), (0.80 * market_fallback_confirmation).to_numpy(dtype=float)),
        index=d.index,
        dtype=float,
    ).clip(lower=0.0, upper=1.0)
    linear_w = numeric_series_or_default(d, "ensemble_weight_linear", float(cfg.ensemble_linear_weight))
    cat_w = numeric_series_or_default(d, "ensemble_weight_catboost", float(cfg.ensemble_cat_weight))
    rank_w = numeric_series_or_default(d, "ensemble_weight_ranker", float(cfg.ensemble_rank_weight))
    d["score_model_core"] = (
        linear_w * numeric_series_or_default(d, "score_linear", 0.0)
        + cat_w * numeric_series_or_default(d, "score_cat", 0.0)
        + rank_w * numeric_series_or_default(d, "score_ranker", 0.0)
        - numeric_series_or_default(d, "risk_penalty", 0.0)
    )
    d["score_quality_core"] = (
        cfg.w_quality_trend
        * (1.0 + 0.50 * actual_priority)
        * (0.35 + 0.65 * score_fundamental_confidence)
        * numeric_series_or_default(d, "quality_trend_score", 0.0)
    )
    d["score_event_core"] = (
        cfg.w_event_reaction
        * (1.0 + 0.50 * actual_priority)
        * numeric_series_or_default(d, "event_reaction_score", 0.0)
    )
    d["score_actual_core"] = cfg.w_actual_results * actual_priority * actual_results
    d["score_garp_core"] = (
        cfg.w_garp
        * (0.50 + 0.50 * score_fundamental_confidence)
        * numeric_series_or_default(d, "garp_score", 0.0)
    )
    score_anticipatory_confidence = pd.Series(
        np.maximum(
            score_fundamental_confidence.to_numpy(dtype=float),
            (0.75 * market_fallback_confirmation).to_numpy(dtype=float),
        ),
        index=d.index,
        dtype=float,
    ).clip(lower=0.0, upper=1.0)
    d["score_anticipatory_growth"] = (
        float(cfg.anticipatory_growth_weight)
        * (0.60 + 0.40 * score_anticipatory_confidence)
        * row_mean(
            [
                numeric_series_or_default(d, "anticipatory_growth_score", 0.0),
                0.75 * numeric_series_or_default(d, "profitability_inflection_score", 0.0),
            ],
            d.index,
        ).fillna(0.0)
    )
    d["score_archetype_mixture"] = (
        float(cfg.archetype_mixture_weight)
        * row_mean(
            [
                numeric_series_or_default(d, "archetype_alignment_score", 0.0),
                0.60 * numeric_series_or_default(d, "dominant_archetype_confidence", 0.0),
            ],
            d.index,
        ).fillna(0.0)
    )
    d["score_future_winner_scout"] = (
        float(cfg.future_winner_scout_weight)
        * row_mean(
            [
                numeric_series_or_default(d, "future_winner_scout_score", 0.0),
                0.65 * numeric_series_or_default(d, "long_hold_compounder_score", 0.0),
            ],
            d.index,
        ).fillna(0.0)
    )
    d["score_future_winner_model"] = (
        float(cfg.future_winner_model_weight)
        * row_mean(
            [
                robust_z(numeric_series_or_default(d, "pred_future_winner_ret", 0.0)).fillna(0.0),
                0.75 * robust_z(numeric_series_or_default(d, "pred_future_winner_p", 0.0)).fillna(0.0),
                0.35 * numeric_series_or_default(d, "future_winner_scout_score", 0.0),
            ],
            d.index,
        ).fillna(0.0)
    )
    d["score_forward_revision_satellite"] = (
        cfg.w_forward_revision
        * proxy_fallback
        * (
            numeric_series_or_default(d, "forward_value_score", 0.0)
            + numeric_series_or_default(d, "revision_score", 0.0)
        )
        / 2.0
    )
    d["score_strategy_blueprint"] = (
        float(cfg.strategy_blueprint_weight)
        * numeric_series_or_default(d, "strategy_blueprint_score", 0.0)
    )
    d["score_flow_satellite"] = (
        cfg.w_institutional_flow * numeric_series_or_default(d, "institutional_flow_signal_score", 0.0)
        + cfg.w_insider_flow * numeric_series_or_default(d, "insider_flow_signal_score", 0.0)
    )
    d["score_multidimensional_confirmation"] = (
        float(cfg.w_multidimensional_confirmation)
        * (0.50 + 0.50 * score_fundamental_confidence)
        * numeric_series_or_default(d, "multidimensional_confirmation_score", 0.0)
    )
    reliability_centered = ((fundamental_reliability - 0.50) / 0.25).clip(lower=-1.5, upper=1.5)
    d["score_fundamental_reliability_adjustment"] = (
        cfg.w_fundamental_reliability * reliability_centered.fillna(0.0)
    )
    d["score_missing_fundamental_penalty"] = (
        cfg.score_missing_fundamental_penalty
        * np.clip(0.45 - score_fundamental_confidence, 0.0, None)
    )
    d["score_market_fallback_confirmation"] = market_fallback_confirmation
    d["score_fundamental_confidence"] = score_fundamental_confidence
    d["score_core"] = (
        d["score_model_core"]
        + d["score_quality_core"]
        + d["score_event_core"]
        + d["score_actual_core"]
        + d["score_garp_core"]
        + d["score_anticipatory_growth"]
        + d["score_archetype_mixture"]
        + d["score_future_winner_scout"]
        + d["score_future_winner_model"]
        + d["score_strategy_blueprint"]
        + d["score_multidimensional_confirmation"]
        + d["score_fundamental_reliability_adjustment"]
        - d["score_missing_fundamental_penalty"]
    )
    d["score_satellite"] = d["score_flow_satellite"]
    if include_latest_only_satellite:
        d["score_satellite"] = d["score_satellite"] + d["score_forward_revision_satellite"]
    d["score_model"] = d["score_core"]
    d["score_live_overlay"] = d["score_forward_revision_satellite"]
    d["score"] = d["score_core"] + (d["score_satellite"] if include_satellite else 0.0)
    return d


def compute_total_score(df: pd.DataFrame, cfg: EngineConfig, include_flow: bool = False) -> pd.Series:
    return add_total_score_columns(
        df,
        cfg,
        include_satellite=include_flow,
        include_latest_only_satellite=False,
    )["score"]


def apply_latest_sentiment_satellite_overlay(df: pd.DataFrame, cfg: EngineConfig) -> pd.DataFrame:
    d = df.copy()
    if d.empty:
        return d
    overlay_weight = float(getattr(cfg, "fear_greed_live_overlay_weight", 0.0))
    if overlay_weight <= 0:
        d["score_fear_greed_satellite"] = 0.0
        return d
    fg_risk_off = numeric_series_or_default(d, "fear_greed_risk_off_score", 0.0).clip(lower=0.0, upper=1.0)
    fg_risk_on = numeric_series_or_default(d, "fear_greed_risk_on_score", 0.0).clip(lower=0.0, upper=1.0)
    risk_on_tilt = row_mean(
        [
            cross_sectional_robust_z(d, "dynamic_leader_score"),
            cross_sectional_robust_z(d, "macro_semis_cycle_interaction"),
            cross_sectional_robust_z(d, "technical_blueprint_score"),
        ],
        d.index,
    ).fillna(0.0)
    risk_off_tilt = row_mean(
        [
            cross_sectional_robust_z(d, "quality_trend_score"),
            cross_sectional_robust_z(d, "moat_proxy_score"),
            -0.75 * cross_sectional_robust_z(d, "overheat_penalty"),
        ],
        d.index,
    ).fillna(0.0)
    # Contrarian extreme-fear bonus: favor undervalued + quality stocks when fear is extreme
    # "Be greedy when others are fearful" — buy quality at a discount
    fg_score = numeric_series_or_default(d, "fear_greed_score", 50.0).fillna(50.0).median()
    contrarian_extreme_fear = max(0.0, (25.0 - fg_score) / 25.0) if fg_score < 25 else 0.0
    contrarian_buy_tilt = row_mean(
        [
            cross_sectional_robust_z(d, "valuation_blueprint_score"),   # Cheap
            cross_sectional_robust_z(d, "moat_quality_blueprint_score"),  # Quality moat
            cross_sectional_robust_z(d, "fundamental_reliability_score"),  # Reliable data
            cross_sectional_robust_z(d, "long_hold_compounder_score"),  # Compounders
            -cross_sectional_robust_z(d, "debt_to_equity"),  # Low leverage
        ],
        d.index,
    ).fillna(0.0)
    d["score_fear_greed_satellite"] = overlay_weight * (
        fg_risk_on * risk_on_tilt + fg_risk_off * risk_off_tilt
        + 1.5 * contrarian_extreme_fear * contrarian_buy_tilt
    )
    d["score_live_overlay"] = numeric_series_or_default(d, "score_live_overlay", 0.0) + d["score_fear_greed_satellite"]
    d["score"] = numeric_series_or_default(d, "score", 0.0) + d["score_fear_greed_satellite"]
    return d


def write_fundamental_coverage_report(
    paths: dict[str, Path],
    latest_df: pd.DataFrame,
    final_filename: str = "fundamental_coverage_latest.csv",
) -> Path:
    path = write_stage_coverage_report(paths, "fundamental_latest", latest_df, FUNDAMENTAL_COVERAGE_COLUMNS)
    final_path = paths["out"] / final_filename
    pd.read_csv(path).to_csv(final_path, index=False)
    return final_path


def write_comprehensive_fundamental_coverage_report(paths: dict[str, Path], latest_df: pd.DataFrame) -> Path:
    rows = []
    n = len(latest_df)
    for c in COMPREHENSIVE_FUNDAMENTAL_COVERAGE_COLUMNS:
        if c in latest_df.columns:
            series = numeric_series_or_default(latest_df, c, np.nan)
            non_null = int(series.notna().sum())
        else:
            non_null = 0
        rows.append(
            {
                "column": c,
                "non_null_count": non_null,
                "non_null_ratio": float(non_null / n) if n else 0.0,
            }
        )
    out = pd.DataFrame(rows).sort_values(["non_null_ratio", "column"], ascending=[False, True]).reset_index(drop=True)
    path = paths["out"] / "fundamental_comprehensive_coverage_latest.csv"
    out.to_csv(path, index=False)
    return path


def repair_latest_history_depth_from_diagnostics(paths: dict[str, Path], latest_df: pd.DataFrame) -> pd.DataFrame:
    d = latest_df.copy()
    if d.empty:
        return d
    current = (
        pd.to_numeric(d["fund_history_quarters_available"], errors="coerce")
        if "fund_history_quarters_available" in d.columns
        else pd.Series(np.nan, index=d.index, dtype=float)
    )
    current_valid = current > 0
    if float(current_valid.fillna(False).mean()) >= 0.25:
        return d

    diag_path = paths["reports"] / "fundamental_join_latest_diagnostics.csv"
    if not diag_path.exists():
        return d
    try:
        diag = pd.read_csv(diag_path)
    except Exception:
        return d
    if diag.empty or "fund_history_quarters_available" not in diag.columns:
        return d

    keep = [c for c in ["ticker", "cik10", "rebalance_date", "fund_history_quarters_available"] if c in diag.columns]
    if len(keep) < 2:
        return d
    diag = diag[keep].copy()
    if "ticker" in d.columns:
        d["ticker"] = d["ticker"].astype(str).str.upper().str.strip()
    if "ticker" in diag.columns:
        diag["ticker"] = diag["ticker"].astype(str).str.upper().str.strip()
    if "cik10" in d.columns:
        d["cik10"] = normalize_cik_series(d["cik10"], index=d.index)
    if "cik10" in diag.columns:
        diag["cik10"] = normalize_cik_series(diag["cik10"], index=diag.index)
    diag["fund_history_quarters_available"] = pd.to_numeric(diag["fund_history_quarters_available"], errors="coerce")
    diag = diag[diag["fund_history_quarters_available"] > 0].copy()
    if diag.empty:
        return d

    if "rebalance_date" in diag.columns:
        diag["rebalance_date"] = pd.to_datetime(diag["rebalance_date"], errors="coerce")
    if "rebalance_date" in d.columns:
        d["rebalance_date"] = pd.to_datetime(d["rebalance_date"], errors="coerce")

    merge_keys = [c for c in ["ticker", "cik10", "rebalance_date"] if c in d.columns and c in diag.columns]
    if len(merge_keys) < 2:
        merge_keys = [c for c in ["ticker", "cik10"] if c in d.columns and c in diag.columns]
    if not merge_keys:
        return d

    repair = diag.drop_duplicates(merge_keys, keep="last")
    for key in merge_keys:
        if key == "rebalance_date":
            continue
        if key in d.columns:
            d[key] = d[key].astype(str)
        if key in repair.columns:
            repair[key] = repair[key].astype(str)
    d = d.merge(repair, on=merge_keys, how="left", suffixes=("", "_diag"))
    _fhqa = pd.to_numeric(
        d["fund_history_quarters_available"] if "fund_history_quarters_available" in d.columns else pd.Series(np.nan, index=d.index),
        errors="coerce",
    )
    _fhqa_diag = pd.to_numeric(
        d["fund_history_quarters_available_diag"] if "fund_history_quarters_available_diag" in d.columns else pd.Series(np.nan, index=d.index),
        errors="coerce",
    )
    d["fund_history_quarters_available"] = _fhqa.where(lambda s: s > 0, _fhqa_diag)
    d = d.drop(columns=["fund_history_quarters_available_diag"], errors="ignore")
    return d


def normalize_latest_fundamental_snapshot(
    cfg: dict | EngineConfig,
    paths: dict[str, Path],
    latest_df: pd.DataFrame,
    *,
    clear_latest_only_signals: bool = False,
    apply_statement_repair: bool = True,
    add_fundamental_flags: bool = True,
) -> pd.DataFrame:
    cfg = to_cfg(cfg)
    d = latest_df.copy()
    if d.empty:
        return d
    d = repair_latest_history_depth_from_diagnostics(paths, d)
    if clear_latest_only_signals:
        d = clear_latest_only_signal_columns(d)
    if apply_statement_repair:
        d = repair_latest_statement_fundamentals(cfg, paths, d)
    d = compute_live_factor_columns(d, cfg)
    if "mktcap" not in d.columns:
        d["mktcap"] = np.nan
    d["mktcap"] = pd.to_numeric(d["mktcap"], errors="coerce")
    if "market_cap_live" in d.columns:
        d["mktcap"] = d["mktcap"].fillna(pd.to_numeric(d["market_cap_live"], errors="coerce"))
    d = compute_valuation_columns(d, cfg)
    if add_fundamental_flags:
        d = add_core_fundamental_minimum_flags(d, cfg)
    return d


def write_live_fundamental_coverage_report(
    paths: dict[str, Path],
    latest_df: pd.DataFrame,
    final_filename: str = "live_fundamental_coverage_latest.csv",
) -> Path:
    cols = [
        "ep_ttm",
        "sp_ttm",
        "fcfy_ttm",
        "forward_pe_final",
        "peg_final",
        "earnings_growth_final",
        "revenue_growth_final",
        "gross_margins",
        "operating_margins",
        "net_income_growth_yoy",
        "op_income_growth_yoy",
        "ocf_growth_yoy",
        "ocf_cagr_3y",
        "ocf_cagr_5y",
        "return_on_equity_live",
        "av_operating_margin",
        "av_return_on_equity",
        "eps_est_q_next",
        "eps_est_fy1",
        "eps_est_fy2",
        "eps_revision_proxy",
        "revision_coverage_ratio",
        "rev_growth_accel_4q",
        "margin_trend_4q",
        "ocf_ni_quality_4q",
        "institutional_holders_count",
        "institutional_holders_value",
        "mutualfund_holders_count",
        "insider_txn_count",
        "institutional_flow_score",
        "insider_flow_score",
        "institutional_flow_actual_score",
        "insider_flow_actual_score",
        "institutional_flow_signal_score",
        "insider_flow_signal_score",
        "ownership_flow_pillar_score",
        "multidimensional_breadth_score",
        "multidimensional_confirmation_score",
        "institutional_actual_available",
        "insider_actual_available",
        "sec13f_value",
        "sec13f_delta_value",
        "sec_form345_net_shares",
        "sec_form345_buy_ratio",
    ]
    rows = []
    n = len(latest_df)
    positive_coverage_cols = {
        "revision_coverage_ratio",
        "institutional_actual_available",
        "insider_actual_available",
    }
    for c in cols:
        if c in latest_df.columns:
            series = numeric_series_or_default(latest_df, c, np.nan)
            if c in positive_coverage_cols:
                non_null = int((series.fillna(0.0) > 0).sum())
            else:
                non_null = int(series.notna().sum())
        else:
            non_null = 0
        rows.append(
            {
                "column": c,
                "non_null_count": non_null,
                "non_null_ratio": float(non_null / n) if n else 0.0,
            }
        )
    out = pd.DataFrame(rows)
    path = paths["out"] / final_filename
    out.to_csv(path, index=False)
    return path


def feature_store_fundamental_coverage_status(feature_store_path: Path, cfg: EngineConfig) -> dict[str, Any]:
    status = {
        "ttm_mean": 0.0,
        "valuation_mean": 0.0,
        "ok": False,
        "latest_rows": 0,
    }
    if not feature_store_path.exists():
        return status

    cols = ["rebalance_date"] + CRITICAL_TTM_COVERAGE_COLUMNS + CRITICAL_VALUATION_COVERAGE_COLUMNS
    try:
        df = pd.read_parquet(feature_store_path, columns=list(dict.fromkeys(cols)))
    except Exception:
        try:
            df = pd.read_parquet(feature_store_path)
        except Exception:
            return status
    if df is None or df.empty or "rebalance_date" not in df.columns:
        return status

    df["rebalance_date"] = pd.to_datetime(df["rebalance_date"], errors="coerce")
    latest_dt = df["rebalance_date"].max()
    latest = df[df["rebalance_date"] == latest_dt].copy() if pd.notna(latest_dt) else df.copy()
    if latest.empty:
        return status

    ttm_cov = [
        float(latest[c].notna().mean()) if c in latest.columns else 0.0
        for c in CRITICAL_TTM_COVERAGE_COLUMNS
    ]
    valuation_cov = [
        float(latest[c].notna().mean()) if c in latest.columns else 0.0
        for c in CRITICAL_VALUATION_COVERAGE_COLUMNS
    ]
    ttm_mean = float(np.nanmean(ttm_cov)) if ttm_cov else 0.0
    valuation_mean = float(np.nanmean(valuation_cov)) if valuation_cov else 0.0
    status["ttm_mean"] = ttm_mean
    status["valuation_mean"] = valuation_mean
    status["latest_rows"] = int(len(latest))
    status["ok"] = bool(
        ttm_mean >= cfg.min_ttm_feature_coverage and valuation_mean >= cfg.min_valuation_feature_coverage
    )
    return status


def stage_flag_path(paths: dict[str, Path]) -> Path:
    return paths["checkpoints"] / "stage_flags.json"


def walkforward_progress_path(paths: dict[str, Path]) -> Path:
    return paths["checkpoints"] / "walkforward_progress.json"


def walkforward_partial_scored_path(paths: dict[str, Path]) -> Path:
    return paths["feature_store"] / "scored_oos_partial.parquet"


def load_stage_flags(paths: dict[str, Path]) -> dict[str, Any]:
    p = stage_flag_path(paths)
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:
            return {}
    return {}


def save_stage_flag(paths: dict[str, Path], stage: str, status: str, extra: Optional[dict[str, Any]] = None) -> None:
    d = load_stage_flags(paths)
    d[stage] = {"status": status, "timestamp": datetime.now().isoformat(timespec="seconds"), "extra": extra or {}}
    stage_flag_path(paths).write_text(json.dumps(d, indent=2))


def stage_is_reusable(flags: dict[str, Any], stage: str, fingerprint: Optional[str] = None) -> bool:
    rec = flags.get(stage, {})
    status_ok = str(rec.get("status", "")).lower() in {"completed", "reused"}
    if not status_ok:
        return False
    if fingerprint is None:
        return True
    return str(rec.get("extra", {}).get("fingerprint", "")) == str(fingerprint)


def load_walkforward_progress(paths: dict[str, Path]) -> dict[str, Any]:
    p = walkforward_progress_path(paths)
    if p.exists():
        try:
            payload = json.loads(p.read_text())
            return payload if isinstance(payload, dict) else {}
        except Exception:
            return {}
    return {}


def save_walkforward_progress(
    paths: dict[str, Path],
    completed_dates: Iterable[str],
    extra: Optional[dict[str, Any]] = None,
) -> None:
    payload = {
        "completed_dates": sorted(set(str(x) for x in completed_dates)),
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "extra": extra or {},
    }
    walkforward_progress_path(paths).write_text(json.dumps(payload, indent=2))


def reuse_fingerprint(cfg: EngineConfig, scope: str) -> str:
    payload = {
        "engine_version": ENGINE_REUSE_VERSION,
        "scope": str(scope),
        "config": asdict(cfg),
    }
    raw = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def validate_config(cfg: EngineConfig) -> None:
    ua = (cfg.sec_user_agent or "").lower()
    if "example.com" in ua or "your_email" in ua:
        raise ValueError("SEC_USER_AGENT must include a real contact email before execution.")
    if cfg.min_port_names > cfg.top_n:
        raise ValueError("min_port_names cannot exceed top_n.")
    if cfg.min_dynamic_port_names < 1:
        raise ValueError("min_dynamic_port_names must be >= 1.")
    if cfg.min_dynamic_port_names > cfg.top_n:
        raise ValueError("min_dynamic_port_names cannot exceed top_n.")
    if cfg.stock_weight_max_high_conviction < cfg.stock_weight_max:
        raise ValueError("stock_weight_max_high_conviction must be >= stock_weight_max.")
    if cfg.stock_weight_max_no_ttm <= 0 or cfg.stock_weight_max_no_ttm_confirmed <= 0:
        raise ValueError("stock_weight_max_no_ttm caps must be > 0.")
    if cfg.stock_weight_max_no_ttm_confirmed < cfg.stock_weight_max_no_ttm:
        raise ValueError("stock_weight_max_no_ttm_confirmed must be >= stock_weight_max_no_ttm.")
    if cfg.stock_weight_max_high_conviction < cfg.stock_weight_max_no_ttm_confirmed:
        raise ValueError("stock_weight_max_high_conviction must be >= stock_weight_max_no_ttm_confirmed.")
    if not (0.0 <= cfg.proxy_decay_after_actual <= 1.0):
        raise ValueError("proxy_decay_after_actual must be between 0 and 1.")
    target_w = cfg.target_blend_1m + cfg.target_blend_3m + cfg.target_blend_6m
    if target_w <= 0:
        raise ValueError("At least one target blend weight must be positive.")
    future_target_w = (
        cfg.future_target_blend_12m
        + cfg.future_target_blend_24m
        + cfg.future_target_blend_36m
    )
    if future_target_w <= 0:
        raise ValueError("At least one future target blend weight must be positive.")
    if cfg.target_12m_days <= cfg.target_6m_days:
        raise ValueError("target_12m_days must be greater than target_6m_days.")
    if cfg.target_24m_days <= cfg.target_12m_days:
        raise ValueError("target_24m_days must be greater than target_12m_days.")
    if cfg.target_36m_days <= cfg.target_24m_days:
        raise ValueError("target_36m_days must be greater than target_24m_days.")
    if cfg.default_backtest_years < 1:
        raise ValueError("default_backtest_years must be >= 1.")
    if not cfg.backtest_window_comparison_years:
        raise ValueError("backtest_window_comparison_years must not be empty.")
    if any(int(x) < 1 for x in cfg.backtest_window_comparison_years):
        raise ValueError("backtest_window_comparison_years values must be >= 1.")
    model_w = cfg.ensemble_linear_weight + cfg.ensemble_cat_weight + cfg.ensemble_rank_weight
    if model_w <= 0:
        raise ValueError("At least one model ensemble weight must be positive.")
    if not (0.0 <= cfg.min_ttm_feature_coverage <= 1.0):
        raise ValueError("min_ttm_feature_coverage must be between 0 and 1.")
    if not (0.0 <= cfg.min_valuation_feature_coverage <= 1.0):
        raise ValueError("min_valuation_feature_coverage must be between 0 and 1.")
    if cfg.macro_m2_release_lag_months < 0:
        raise ValueError("macro_m2_release_lag_months must be >= 0.")
    if cfg.macro_slow_release_lag_months < 0:
        raise ValueError("macro_slow_release_lag_months must be >= 0.")
    if cfg.fund_panel_repair_quarters < 1:
        raise ValueError("fund_panel_repair_quarters must be >= 1.")
    if cfg.fund_ttm_ffill_quarters < 0:
        raise ValueError("fund_ttm_ffill_quarters must be >= 0.")
    if cfg.fund_balance_ffill_quarters < 0:
        raise ValueError("fund_balance_ffill_quarters must be >= 0.")
    if cfg.fund_ttm_fallback_max_age_days < 1:
        raise ValueError("fund_ttm_fallback_max_age_days must be >= 1.")
    if cfg.targeted_repair_max_ciks < 1:
        raise ValueError("targeted_repair_max_ciks must be >= 1.")
    if not (0.0 <= cfg.targeted_repair_flow_cov_threshold <= 1.0):
        raise ValueError("targeted_repair_flow_cov_threshold must be between 0 and 1.")
    if cfg.targeted_repair_stale_days < 1:
        raise ValueError("targeted_repair_stale_days must be >= 1.")
    if cfg.companyfacts_max_retries < 1:
        raise ValueError("companyfacts_max_retries must be >= 1.")
    if cfg.companyfacts_retry_backoff < 0:
        raise ValueError("companyfacts_retry_backoff must be >= 0.")
    if cfg.optimizer_regime_sensitivity < 0:
        raise ValueError("optimizer_regime_sensitivity must be >= 0.")
    if cfg.event_regime_sensitivity < 0:
        raise ValueError("event_regime_sensitivity must be >= 0.")
    if not (0.0 <= cfg.target_excess_weight <= 1.0):
        raise ValueError("target_excess_weight must be between 0 and 1.")
    if not (0.0 <= cfg.future_target_excess_weight <= 1.0):
        raise ValueError("future_target_excess_weight must be between 0 and 1.")
    if cfg.defensive_rotation_strength < 0 or cfg.growth_reentry_strength < 0:
        raise ValueError("rotation strengths must be >= 0.")
    if cfg.benchmark_hugging_penalty < 0:
        raise ValueError("benchmark_hugging_penalty must be >= 0.")
    if cfg.live_event_alert_strength < 0:
        raise ValueError("live_event_alert_strength must be >= 0.")
    if cfg.archetype_mixture_weight < 0:
        raise ValueError("archetype_mixture_weight must be >= 0.")
    if cfg.future_winner_scout_weight < 0:
        raise ValueError("future_winner_scout_weight must be >= 0.")
    if cfg.future_winner_model_weight < 0:
        raise ValueError("future_winner_model_weight must be >= 0.")
    if not (0.0 <= cfg.live_event_risk_threshold <= 1.0):
        raise ValueError("live_event_risk_threshold must be between 0 and 1.")
    if not (0.0 <= cfg.live_event_growth_threshold <= 1.0):
        raise ValueError("live_event_growth_threshold must be between 0 and 1.")
    if cfg.walkforward_checkpoint_every < 1:
        raise ValueError("walkforward_checkpoint_every must be >= 1.")
    if cfg.walkforward_retrain_frequency_months < 1:
        raise ValueError("walkforward_retrain_frequency_months must be >= 1.")
    if cfg.cat_validation_months < 0:
        raise ValueError("cat_validation_months must be >= 0.")
    if cfg.cat_early_stopping_rounds < 0:
        raise ValueError("cat_early_stopping_rounds must be >= 0.")
    if cfg.focus_overlay_strength < 0:
        raise ValueError("focus_overlay_strength must be >= 0.")
    if cfg.focus_sector_crowding_penalty < 0:
        raise ValueError("focus_sector_crowding_penalty must be >= 0.")
    if cfg.focus_portfolio_utility_boost < 0:
        raise ValueError("focus_portfolio_utility_boost must be >= 0.")
    if cfg.focus_no_ttm_bonus_cap_weak < 0 or cfg.focus_no_ttm_bonus_cap_confirmed < 0:
        raise ValueError("focus_no_ttm_bonus caps must be >= 0.")
    if cfg.focus_negative_momentum_emergence_penalty < 0:
        raise ValueError("focus_negative_momentum_emergence_penalty must be >= 0.")
    if cfg.portfolio_confirmation_utility_boost < 0:
        raise ValueError("portfolio_confirmation_utility_boost must be >= 0.")
    if cfg.portfolio_confirmation_conviction_boost < 0:
        raise ValueError("portfolio_confirmation_conviction_boost must be >= 0.")
    if cfg.portfolio_seed_confirmation_boost < 0:
        raise ValueError("portfolio_seed_confirmation_boost must be >= 0.")
    if cfg.portfolio_midterm_utility_boost < 0:
        raise ValueError("portfolio_midterm_utility_boost must be >= 0.")
    if cfg.portfolio_seed_midterm_boost < 0:
        raise ValueError("portfolio_seed_midterm_boost must be >= 0.")
    if cfg.portfolio_garp_utility_boost < 0:
        raise ValueError("portfolio_garp_utility_boost must be >= 0.")
    if cfg.portfolio_anticipatory_utility_boost < 0:
        raise ValueError("portfolio_anticipatory_utility_boost must be >= 0.")
    if cfg.portfolio_long_hold_bonus_weight < 0:
        raise ValueError("portfolio_long_hold_bonus_weight must be >= 0.")
    if cfg.portfolio_seed_anticipatory_boost < 0:
        raise ValueError("portfolio_seed_anticipatory_boost must be >= 0.")
    if cfg.portfolio_top1_conviction_boost < 0 or cfg.portfolio_top2_conviction_boost < 0:
        raise ValueError("portfolio_top conviction boosts must be >= 0.")
    if cfg.fear_greed_live_overlay_weight < 0:
        raise ValueError("fear_greed_live_overlay_weight must be >= 0.")
    if cfg.adaptive_ensemble_lookback_months < 1 or cfg.adaptive_ensemble_min_months < 1:
        raise ValueError("adaptive_ensemble lookback/min months must be >= 1.")
    if cfg.adaptive_ensemble_min_months > cfg.adaptive_ensemble_lookback_months:
        raise ValueError("adaptive_ensemble_min_months cannot exceed adaptive_ensemble_lookback_months.")
    if not (0.0 <= cfg.adaptive_ensemble_strength <= 1.0):
        raise ValueError("adaptive_ensemble_strength must be between 0 and 1.")
    if not (0.0 <= cfg.adaptive_ensemble_floor_weight <= 1.0):
        raise ValueError("adaptive_ensemble_floor_weight must be between 0 and 1.")
    if cfg.adaptive_ensemble_temperature <= 0:
        raise ValueError("adaptive_ensemble_temperature must be > 0.")
    if not (0.0 <= cfg.adaptive_ensemble_rank_ic_weight <= 1.0):
        raise ValueError("adaptive_ensemble_rank_ic_weight must be between 0 and 1.")
    if cfg.adaptive_ensemble_recent_half_life_months <= 0:
        raise ValueError("adaptive_ensemble_recent_half_life_months must be > 0.")
    if not (0.0 <= cfg.cash_release_max_per_rebalance <= 1.0):
        raise ValueError("cash_release_max_per_rebalance must be between 0 and 1.")
    if not (0.0 <= cfg.cash_target_growth_cap <= 0.20):
        raise ValueError("cash_target_growth_cap must be between 0 and 0.20.")
    if not (0.0 <= cfg.cash_target_balanced_cap <= 0.20):
        raise ValueError("cash_target_balanced_cap must be between 0 and 0.20.")
    if not (0.0 <= cfg.cash_target_mild_risk_cap <= 0.25):
        raise ValueError("cash_target_mild_risk_cap must be between 0 and 0.25.")
    if cfg.cash_target_growth_cap > cfg.cash_target_balanced_cap:
        raise ValueError("cash_target_growth_cap cannot exceed cash_target_balanced_cap.")
    if cfg.cash_target_balanced_cap > cfg.cash_target_mild_risk_cap:
        raise ValueError("cash_target_balanced_cap cannot exceed cash_target_mild_risk_cap.")
    if not (0.0 <= cfg.core_compounder_sleeve_base_weight <= 1.0):
        raise ValueError("core_compounder_sleeve_base_weight must be between 0 and 1.")
    if not (0.0 <= cfg.future_winner_sleeve_base_weight <= 1.0):
        raise ValueError("future_winner_sleeve_base_weight must be between 0 and 1.")
    if not (0.0 <= cfg.future_winner_sleeve_min_weight <= 1.0):
        raise ValueError("future_winner_sleeve_min_weight must be between 0 and 1.")
    if not (0.0 <= cfg.future_winner_sleeve_max_weight <= 1.0):
        raise ValueError("future_winner_sleeve_max_weight must be between 0 and 1.")
    if cfg.future_winner_sleeve_min_weight > cfg.future_winner_sleeve_max_weight:
        raise ValueError("future_winner_sleeve_min_weight cannot exceed future_winner_sleeve_max_weight.")
    if not (0.0 <= cfg.early_scout_sleeve_base_weight <= 1.0):
        raise ValueError("early_scout_sleeve_base_weight must be between 0 and 1.")
    if not (0.0 <= cfg.early_scout_sleeve_min_weight <= 1.0):
        raise ValueError("early_scout_sleeve_min_weight must be between 0 and 1.")
    if not (0.0 <= cfg.early_scout_sleeve_max_weight <= 1.0):
        raise ValueError("early_scout_sleeve_max_weight must be between 0 and 1.")
    if cfg.early_scout_sleeve_min_weight > cfg.early_scout_sleeve_max_weight:
        raise ValueError("early_scout_sleeve_min_weight cannot exceed early_scout_sleeve_max_weight.")
    for name in [
        "early_scout_growth_floor_weight",
        "early_scout_growth_floor_min_signal",
        "early_scout_growth_floor_max_risk",
        "early_scout_candidate_floor_min_share",
        "future_winner_entry_weight_cap",
        "future_winner_drift_weight_cap",
        "future_winner_hard_weight_cap",
        "early_scout_entry_weight_cap",
        "early_scout_drift_weight_cap",
        "early_scout_hard_weight_cap",
        "sleeve_drift_headroom_pct",
        "early_scout_promotion_edge_max",
        "early_scout_promotion_confidence_max",
        "early_scout_promotion_min_score",
        "growth_history_confidence_penalty_weight",
        "growth_history_confidence_min_for_full_sleeve",
    ]:
        value = float(getattr(cfg, name))
        if not (0.0 <= value <= 1.0):
            raise ValueError(f"{name} must be between 0 and 1.")
    if cfg.future_winner_entry_weight_cap > cfg.future_winner_hard_weight_cap:
        raise ValueError("future_winner_entry_weight_cap cannot exceed future_winner_hard_weight_cap.")
    if cfg.future_winner_drift_weight_cap > cfg.future_winner_hard_weight_cap:
        raise ValueError("future_winner_drift_weight_cap cannot exceed future_winner_hard_weight_cap.")
    if cfg.early_scout_entry_weight_cap > cfg.early_scout_hard_weight_cap:
        raise ValueError("early_scout_entry_weight_cap cannot exceed early_scout_hard_weight_cap.")
    if cfg.early_scout_drift_weight_cap > cfg.early_scout_hard_weight_cap:
        raise ValueError("early_scout_drift_weight_cap cannot exceed early_scout_hard_weight_cap.")
    if (
        cfg.core_compounder_sleeve_base_weight
        + cfg.future_winner_sleeve_base_weight
        + cfg.early_scout_sleeve_base_weight
    ) >= 1.0:
        raise ValueError(
            "core_compounder_sleeve_base_weight + future_winner_sleeve_base_weight + early_scout_sleeve_base_weight must be < 1.0."
        )
    if cfg.portfolio_hold_policy_seed_weight < 0 or cfg.portfolio_hold_policy_weight < 0:
        raise ValueError("portfolio_hold_policy weights must be >= 0.")
    if cfg.portfolio_hold_policy_prev_weight_bonus < 0 or cfg.portfolio_hold_policy_exit_penalty_weight < 0:
        raise ValueError("portfolio_hold_policy bonus/penalty weights must be >= 0.")
    if cfg.portfolio_low_growth_penalty < 0:
        raise ValueError("portfolio_low_growth_penalty must be >= 0.")
    if not 0.0 <= cfg.dividend_policy_yield_only_weight <= 1.0:
        raise ValueError("dividend_policy_yield_only_weight must be between 0 and 1.")
    if cfg.dividend_quality_trend_weight < 0:
        raise ValueError("dividend_quality_trend_weight must be >= 0.")
    if not 0.0 <= cfg.dividend_presence_weight <= 0.20:
        raise ValueError("dividend_presence_weight must be between 0 and 0.20.")
    if not 0.0 <= cfg.dividend_growth_gate_floor <= 1.0:
        raise ValueError("dividend_growth_gate_floor must be between 0 and 1.")
    if cfg.w_fundamental_reliability < 0:
        raise ValueError("w_fundamental_reliability must be >= 0.")
    if cfg.w_garp < 0:
        raise ValueError("w_garp must be >= 0.")
    if cfg.w_multidimensional_confirmation < 0:
        raise ValueError("w_multidimensional_confirmation must be >= 0.")
    if cfg.anticipatory_growth_weight < 0:
        raise ValueError("anticipatory_growth_weight must be >= 0.")
    if cfg.score_missing_fundamental_penalty < 0:
        raise ValueError("score_missing_fundamental_penalty must be >= 0.")
    if cfg.focus_missing_fundamental_penalty < 0:
        raise ValueError("focus_missing_fundamental_penalty must be >= 0.")
    if cfg.portfolio_fundamental_utility_boost < 0:
        raise ValueError("portfolio_fundamental_utility_boost must be >= 0.")
    if cfg.strategy_blueprint_weight < 0:
        raise ValueError("strategy_blueprint_weight must be >= 0.")
    if not 0.0 <= cfg.cash_weight_max <= 1.0:
        raise ValueError("cash_weight_max must be between 0 and 1.0.")
    if cfg.trade_cost_bps_per_side < 0 or cfg.roundtrip_cost_bps < 0:
        raise ValueError("trade cost settings must be >= 0.")
    if cfg.starting_capital_usd <= 0:
        raise ValueError("starting_capital_usd must be > 0.")
    if not cfg.portfolio_size_comparison_sizes:
        raise ValueError("portfolio_size_comparison_sizes must not be empty.")
    if any(int(x) < 1 for x in cfg.portfolio_size_comparison_sizes):
        raise ValueError("portfolio_size_comparison_sizes values must be >= 1.")
    if int(cfg.rebalance_interval_months) < 1:
        raise ValueError("rebalance_interval_months must be >= 1.")
    for name in [
        "core_compounder_rebalance_interval_months",
        "future_winner_rebalance_interval_months",
        "early_scout_rebalance_interval_months",
    ]:
        if int(getattr(cfg, name)) < 1:
            raise ValueError(f"{name} must be >= 1.")
    if not cfg.rebalance_interval_comparison_months:
        raise ValueError("rebalance_interval_comparison_months must not be empty.")
    if any(int(x) < 1 for x in cfg.rebalance_interval_comparison_months):
        raise ValueError("rebalance_interval_comparison_months values must be >= 1.")
    if int(cfg.sleeve_cap_policy_max_candidates) < 1:
        raise ValueError("sleeve_cap_policy_max_candidates must be >= 1.")
    if int(cfg.standalone_sleeve_top_n) < 1:
        raise ValueError("standalone_sleeve_top_n must be >= 1.")
    if not cfg.standalone_sleeve_rebalance_intervals:
        raise ValueError("standalone_sleeve_rebalance_intervals must not be empty.")
    if any(int(x) < 1 for x in cfg.standalone_sleeve_rebalance_intervals):
        raise ValueError("standalone_sleeve_rebalance_intervals values must be >= 1.")
    if not cfg.concentrated_top_n_candidates:
        raise ValueError("concentrated_top_n_candidates must not be empty.")
    if any(int(x) < 1 or int(x) > 30 for x in cfg.concentrated_top_n_candidates):
        # Phase 9 CE: raised upper bound 3 -> 30 to explore wider concentration
        # ladder. Top 30 is the main portfolio boundary; beyond that we're
        # diluting into full diversified mode.
        raise ValueError("concentrated_top_n_candidates values must be between 1 and 30.")
    if not cfg.concentrated_rebalance_intervals:
        raise ValueError("concentrated_rebalance_intervals must not be empty.")
    if any(int(x) < 1 for x in cfg.concentrated_rebalance_intervals):
        raise ValueError("concentrated_rebalance_intervals values must be >= 1.")
    if not cfg.concentrated_weighting_modes:
        raise ValueError("concentrated_weighting_modes must not be empty.")
    if any(str(x) not in {"conviction_curve", "winner_take_all", "score_power"} for x in cfg.concentrated_weighting_modes):
        raise ValueError("concentrated_weighting_modes values must be one of conviction_curve, winner_take_all, score_power.")
    if not cfg.concentrated_allowed_sleeves:
        raise ValueError("concentrated_allowed_sleeves must not be empty.")
    if any(str(x) not in {"future_winner", "early_scout", "core_compounder"} for x in cfg.concentrated_allowed_sleeves):
        raise ValueError("concentrated_allowed_sleeves must be limited to core_compounder/future_winner/early_scout.")
    for name in [
        "concentrated_min_confirmation",
        "concentrated_score_future_weight",
        "concentrated_score_early_weight",
        "concentrated_score_sage_weight",
        "concentrated_score_confirmation_weight",
        "concentrated_score_breakout_weight",
        "concentrated_score_momentum_weight",
        "concentrated_score_exit_risk_penalty",
        "concentrated_max_single_name_weight",
    ]:
        val = float(getattr(cfg, name))
        if val < 0:
            raise ValueError(f"{name} must be >= 0.")
    if cfg.concentrated_max_single_name_weight <= 0 or cfg.concentrated_max_single_name_weight > 1.0:
        raise ValueError("concentrated_max_single_name_weight must be in (0, 1].")
    if int(cfg.concentrated_monitoring_review_days) < 1:
        raise ValueError("concentrated_monitoring_review_days must be >= 1.")
    for name in [
        "sleeve_cap_policy_objective_excess_weight",
        "sleeve_cap_policy_objective_sharpe_weight",
        "sleeve_cap_policy_objective_sortino_weight",
        "sleeve_cap_policy_objective_drawdown_weight",
        "sleeve_cap_policy_objective_turnover_weight",
        "sleeve_cap_policy_objective_concentration_weight",
        "sleeve_cap_policy_objective_cash_drag_weight",
    ]:
        if float(getattr(cfg, name)) < 0:
            raise ValueError(f"{name} must be >= 0.")
    if int(cfg.alert_review_days) < 1:
        raise ValueError("alert_review_days must be >= 1.")
    if not 0.0 <= cfg.min_live_estimate_coverage <= 1.0:
        raise ValueError("min_live_estimate_coverage must be between 0 and 1.")
    if cfg.min_core_fundamental_fields_required < 1 or cfg.min_core_fundamental_fields_required > len(CORE_FUNDAMENTAL_MINIMUM_FIELDS):
        raise ValueError(
            f"min_core_fundamental_fields_required must be between 1 and {len(CORE_FUNDAMENTAL_MINIMUM_FIELDS)}."
        )
    if cfg.sector_adjusted_financial_min_fields < 1 or cfg.sector_adjusted_realasset_min_fields < 1 or cfg.sector_adjusted_resource_min_fields < 1:
        raise ValueError("sector-adjusted minimum field counts must be >= 1.")
    if cfg.partial_scout_min_fields < 1:
        raise ValueError("partial_scout_min_fields must be >= 1.")
    if not (0.0 <= cfg.partial_scout_confirmation_min <= 1.0):
        raise ValueError("partial_scout_confirmation_min must be between 0 and 1.")
    if cfg.partial_scout_score_floor < 0:
        raise ValueError("partial_scout_score_floor must be >= 0.")
    if cfg.future_winner_min_fundamental_fields_required < 1:
        raise ValueError("future_winner_min_fundamental_fields_required must be >= 1.")
    if cfg.early_scout_min_fundamental_fields_required < 1:
        raise ValueError("early_scout_min_fundamental_fields_required must be >= 1.")
    for name in [
        "future_winner_confirmation_min",
        "future_winner_fundamental_presence_min",
        "future_winner_fundamental_reliability_min",
        "early_scout_confirmation_min",
        "early_scout_fundamental_presence_min",
        "early_scout_fundamental_reliability_min",
    ]:
        if not (0.0 <= float(getattr(cfg, name)) <= 1.0):
            raise ValueError(f"{name} must be between 0 and 1.")
    if cfg.stock_weight_max_sector_adjusted <= 0 or cfg.stock_weight_max_partial_scout <= 0:
        raise ValueError("sector-adjusted and partial-scout stock caps must be > 0.")
    if not (0.0 <= cfg.partial_scout_total_weight_cap <= 1.0):
        raise ValueError("partial_scout_total_weight_cap must be between 0 and 1.")
    if cfg.latest_statement_repair_tickers < 0:
        raise ValueError("latest_statement_repair_tickers must be >= 0.")
    if cfg.latest_statement_repair_refresh_days < 0:
        raise ValueError("latest_statement_repair_refresh_days must be >= 0.")
    if cfg.alpha_vantage_free_refresh_tickers < 0:
        raise ValueError("alpha_vantage_free_refresh_tickers must be >= 0.")
    if cfg.alpha_vantage_free_statement_repair_tickers < 0:
        raise ValueError("alpha_vantage_free_statement_repair_tickers must be >= 0.")
    if cfg.alpha_vantage_free_statement_refresh_days < 0:
        raise ValueError("alpha_vantage_free_statement_refresh_days must be >= 0.")
    if cfg.manual_moat_half_life_days < 1:
        raise ValueError("manual_moat_half_life_days must be >= 1.")
    if cfg.watchlist_penalty_scale < 0:
        raise ValueError("watchlist_penalty_scale must be >= 0.")
    if cfg.focus_direct_ticker_tiebreak < 0:
        raise ValueError("focus_direct_ticker_tiebreak must be >= 0.")
    if cfg.focus_target_n < 1 or cfg.focus_riskoff_target_n < 1:
        raise ValueError("focus_target_n and focus_riskoff_target_n must be >= 1.")
    if cfg.focus_target_n > cfg.top_n or cfg.focus_riskoff_target_n > cfg.top_n:
        raise ValueError("focus portfolio sizes cannot exceed top_n.")
    if int(cfg.engine_diagnostics_top_n) < 1:
        raise ValueError("engine_diagnostics_top_n must be >= 1.")
    if cfg.adaptive_rebalance_growth_months < 1 or cfg.adaptive_rebalance_balanced_months < 1 or cfg.adaptive_rebalance_riskoff_months < 1:
        raise ValueError("adaptive rebalance month settings must be >= 1.")
    if cfg.adaptive_rebalance_distance_penalty < 0:
        raise ValueError("adaptive_rebalance_distance_penalty must be >= 0.")
    if not (0.0 <= cfg.adaptive_rebalance_risk_threshold <= 1.0):
        raise ValueError("adaptive_rebalance_risk_threshold must be between 0 and 1.")
    if not (0.0 <= cfg.adaptive_rebalance_growth_threshold <= 1.0):
        raise ValueError("adaptive_rebalance_growth_threshold must be between 0 and 1.")
    if not (0.0 <= cfg.ops_min_realized_coverage <= 1.0):
        raise ValueError("ops_min_realized_coverage must be between 0 and 1.")


def model_feature_columns(cfg: EngineConfig) -> list[str]:
    return list(
        dict.fromkeys(
            [
                f
                for f in (cfg.features + PILLAR_SCORE_COLUMNS)
                if f not in SATELLITE_ONLY_FEATURE_COLUMNS
            ]
        )
    )


def save_baseline_code(cfg: EngineConfig, paths: dict[str, Path]) -> Path:
    baseline_path = paths["baseline"] / "baseline_v4_2.py"
    if cfg.baseline_v42_code.strip():
        baseline_path.write_text(cfg.baseline_v42_code)
    elif not baseline_path.exists():
        baseline_path.write_text(
            "# baseline_v4_2.py placeholder\n"
            "# Set cfg['baseline_v42_code'] to original code string to run full static audit.\n"
        )
    return baseline_path


def scan_file_patterns(file_path: Path, patterns: dict[str, list[str]]) -> dict[str, list[dict[str, Any]]]:
    txt = file_path.read_text(encoding="utf-8", errors="ignore")
    lines = txt.splitlines()
    out: dict[str, list[dict[str, Any]]] = {}
    for group, pats in patterns.items():
        out[group] = []
        for pat in pats:
            rx = re.compile(pat)
            for i, ln in enumerate(lines, start=1):
                if rx.search(ln):
                    out[group].append({"pattern": pat, "line": i, "snippet": ln[:250]})
    return out


def write_audit_reports(scan: dict[str, list[dict[str, Any]]], paths: dict[str, Path]) -> dict[str, Path]:
    reports: dict[str, Path] = {}
    leakage = paths["reports"] / "leakage_audit.md"
    pit = paths["reports"] / "pit_audit.md"
    validation = paths["reports"] / "validation_gap.md"

    leakage_lines = ["# Leakage Audit", "", "## Findings"]
    if scan["leakage"]:
        for hit in scan["leakage"][:200]:
            leakage_lines.append(f"- L{hit['line']}: `{hit['pattern']}` -> `{hit['snippet']}`")
    else:
        leakage_lines.append("- No explicit leakage patterns matched.")
    leakage_lines += ["", "## Mandatory Fixes", "- Remove any feature using post-event forward returns.", "- Keep only signal-time observable variables in feature set.", "- Build labels from future open prices only after signal timestamp."]
    leakage.write_text("\n".join(leakage_lines), encoding="utf-8")

    pit_lines = ["# PIT Audit", "", "## Findings"]
    if scan["pit"]:
        for hit in scan["pit"][:300]:
            pit_lines.append(f"- L{hit['line']}: `{hit['pattern']}` -> `{hit['snippet']}`")
    else:
        pit_lines.append("- No PIT patterns matched.")
    pit_lines += ["", "## Mandatory Fixes", "- Enforce `accepted <= feature_date <= rebalance_date` for all rows.", "- Use per-CIK `merge_asof` for fundamentals joins.", "- Store and test PIT integrity constraints each run."]
    pit.write_text("\n".join(pit_lines), encoding="utf-8")

    val_lines = ["# Validation Gap Audit", "", "## Findings"]
    if scan["validation"]:
        for hit in scan["validation"][:200]:
            val_lines.append(f"- L{hit['line']}: `{hit['pattern']}` -> `{hit['snippet']}`")
    else:
        val_lines.append("- No validation-related patterns matched.")
    val_lines += ["", "## Mandatory Fixes", "- Monthly walk-forward OOS only.", "- Apply embargo window before each test month.", "- Report cost-adjusted metrics and monthly turnover."]
    validation.write_text("\n".join(val_lines), encoding="utf-8")

    reports["leakage_audit"] = leakage
    reports["pit_audit"] = pit
    reports["validation_gap"] = validation
    return reports


def run_phase0_code_search(cfg: EngineConfig, paths: dict[str, Path]) -> dict[str, Any]:
    baseline_path = save_baseline_code(cfg, paths)
    scan = scan_file_patterns(baseline_path, SCAN_PATTERNS)
    reports = write_audit_reports(scan, paths)
    summary = {
        "baseline_path": str(baseline_path),
        "scan_hits": {k: len(v) for k, v in scan.items()},
        "reports": {k: str(v) for k, v in reports.items()},
    }
    (paths["reports"] / "phase0_scan_summary.json").write_text(json.dumps(summary, indent=2))
    return summary


def load_sec_company_tickers(cfg: EngineConfig, paths: dict[str, Path]) -> pd.DataFrame:
    path = paths["data_raw"] / "sec_company_tickers.parquet"
    if path.exists():
        return pd.read_parquet(path)
    headers = {
        "User-Agent": cfg.sec_user_agent,
        "Accept-Encoding": "gzip, deflate",
        "Host": "www.sec.gov",
    }
    url = "https://www.sec.gov/files/company_tickers.json"
    log("Downloading SEC company_tickers.json ...")
    data = http_get(url, headers=headers, timeout=60).json()
    m = pd.DataFrame.from_dict(data, orient="index")
    m["ticker"] = m["ticker"].str.upper()
    m["cik10"] = m["cik_str"].astype(int).astype(str).str.zfill(10)
    m = m[["ticker", "cik10", "title"]].drop_duplicates("ticker", keep="first")
    m.to_parquet(path, index=False)
    return m


# Stage 3d-i-prep (2026-04-20): companyfacts_cache_file + normalize_cik10 +
# normalize_cik_list + normalize_cik_series moved to r1000_helpers.py.


def companyfacts_bulk_store_candidates(cfg: EngineConfig, paths: dict[str, Path]) -> list[Path]:
    candidates: list[Path] = []
    raw = str(getattr(cfg, "sec_companyfacts_bulk_path", "") or "").strip()
    if raw:
        p = Path(raw)
        candidates.append(p if p.is_absolute() else paths["base"] / p)
    for root in [paths["cache_sec_actual"], paths["data_raw"], paths["base"]]:
        candidates.extend(
            [
                root / "companyfacts.zip",
                root / "companyfacts",
                root / "sec_companyfacts_bulk",
            ]
        )
    out: list[Path] = []
    seen: set[str] = set()
    for p in candidates:
        key = str(p)
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


def companyfacts_bulk_member_map(store: Path) -> dict[str, str]:
    try:
        cache_key = str(store.resolve())
    except Exception:
        cache_key = str(store)
    cached = _COMPANYFACTS_BULK_MEMBER_MAP_CACHE.get(cache_key)
    if cached is not None:
        return cached

    mapping: dict[str, str] = {}
    if store.is_file() and store.suffix.lower() == ".zip":
        try:
            with zipfile.ZipFile(store) as zf:
                for name in zf.namelist():
                    norm = str(name).replace("\\", "/")
                    m = SEC_COMPANYFACTS_MEMBER_RE.search(norm)
                    if m:
                        mapping[str(m.group(1)).zfill(10)] = name
        except Exception:
            mapping = {}
    elif store.is_dir():
        try:
            for path in store.rglob("*.json"):
                norm = path.as_posix()
                m = SEC_COMPANYFACTS_MEMBER_RE.search(norm)
                if m:
                    mapping[str(m.group(1)).zfill(10)] = str(path)
        except Exception:
            mapping = {}

    _COMPANYFACTS_BULK_MEMBER_MAP_CACHE[cache_key] = mapping
    return mapping


def companyfacts_bulk_sources(
    cfg: EngineConfig,
    paths: dict[str, Path],
    cik_list: list[str],
) -> list[tuple[Path, dict[str, str]]]:
    if not getattr(cfg, "use_sec_companyfacts_bulk_local", True):
        return []
    requested = normalize_cik_list(cik_list)
    if not requested:
        return []

    sources: list[tuple[Path, dict[str, str]]] = []
    for store in companyfacts_bulk_store_candidates(cfg, paths):
        if not store.exists():
            continue
        member_map = companyfacts_bulk_member_map(store)
        if not any(cik in member_map for cik in requested):
            continue
        sources.append((store, member_map))
    return sources


def load_local_companyfacts_bulk_payload(
    paths: dict[str, Path],
    store: Path,
    member_map: dict[str, str],
    cik: str,
    zf: Optional[zipfile.ZipFile] = None,
) -> dict[str, Any]:
    member_name = member_map.get(str(cik).zfill(10))
    if not member_name:
        return {}
    try:
        if zf is not None:
            with zf.open(member_name) as fh:
                payload = json.load(fh)
        elif store.is_file() and store.suffix.lower() == ".zip":
            with zipfile.ZipFile(store) as zf_local:
                with zf_local.open(member_name) as fh:
                    payload = json.load(fh)
        else:
            payload = json.loads(Path(member_name).read_text())
    except Exception:
        return {}
    if not isinstance(payload, dict) or not payload.get("facts"):
        return {}
    try:
        companyfacts_cache_file(paths, cik).write_text(json.dumps(payload))
    except Exception:
        pass
    return payload


def load_sec_companyfacts_json(cfg: EngineConfig, paths: dict[str, Path], cik: str) -> dict[str, Any]:
    cik10 = str(cik).zfill(10)
    cache_path = companyfacts_cache_file(paths, cik10)
    if is_cache_fresh(cache_path, cfg.companyfacts_refresh_days):
        try:
            payload = json.loads(cache_path.read_text())
            return payload if isinstance(payload, dict) else {}
        except Exception:
            pass

    headers = {
        "User-Agent": cfg.sec_user_agent,
        "Accept-Encoding": "gzip, deflate",
        "Host": "data.sec.gov",
    }
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik10}.json"
    max_retries = max(int(cfg.companyfacts_max_retries), 1)
    last_err = ""
    for attempt in range(max_retries):
        try:
            payload = http_get(url, headers=headers, timeout=60).json()
            if isinstance(payload, dict) and payload.get("facts"):
                cache_path.write_text(json.dumps(payload))
                time.sleep(cfg.sec_sleep)
                return payload
            last_err = "empty companyfacts payload"
        except Exception as e:
            last_err = str(e)
        if attempt + 1 < max_retries:
            wait_s = max(float(cfg.sec_sleep), float(cfg.companyfacts_retry_backoff) * float(attempt + 1))
            time.sleep(wait_s)

    if cache_path.exists():
        try:
            payload = json.loads(cache_path.read_text())
            if last_err:
                log(f"[WARN] companyfacts fetch failed for CIK{cik10}; using stale cache ({last_err})")
            return payload if isinstance(payload, dict) else {}
        except Exception:
            return {}
    if last_err:
        log(f"[WARN] companyfacts fetch failed for CIK{cik10}: {last_err}")
    return {}


def infer_fiscal_year_end_month(group: pd.DataFrame) -> Optional[int]:
    if group is None or group.empty:
        return None
    annual_mask = group["fp"].astype(str).str.upper().eq("FY")
    if "duration_days" in group.columns:
        annual_mask |= pd.to_numeric(group["duration_days"], errors="coerce").fillna(0) >= 300
    annual_periods = pd.to_datetime(group.loc[annual_mask, "period"], errors="coerce").dropna()
    if not annual_periods.empty:
        return int(annual_periods.iloc[-1].month)
    return None


def infer_quarter_from_period(period: Any, fiscal_year_end_month: Optional[int]) -> Optional[int]:
    dt = pd.to_datetime(period, errors="coerce")
    if pd.isna(dt) or fiscal_year_end_month is None:
        return None
    month_diff = (int(dt.month) - int(fiscal_year_end_month)) % 12
    q_idx = 4 if month_diff == 0 else int(month_diff // 3)
    return q_idx if q_idx in {1, 2, 3, 4} else None


def companyfacts_quarter_index(
    fp: Any,
    frame: Any = None,
    *,
    period: Any = None,
    duration_days: Optional[float] = None,
    fiscal_year_end_month: Optional[int] = None,
) -> Optional[int]:
    txt = str(fp).upper().strip() if fp is not None else ""
    mapping = {
        "Q1": 1,
        "Q2": 2,
        "Q3": 3,
        "Q4": 4,
        "FY": 4,
        "H1": 2,
        "HY": 2,
        "H2": 4,
        "YTDQ1": 1,
        "YTDQ2": 2,
        "YTDQ3": 3,
        "YTDQ4": 4,
    }
    if txt in mapping:
        return mapping[txt]
    frame_txt = str(frame).upper().strip() if frame is not None else ""
    m = re.search(r"Q([1-4])", frame_txt)
    if m:
        return int(m.group(1))
    if pd.notna(duration_days):
        dd = float(duration_days)
        if 70 <= dd <= 120:
            inferred = infer_quarter_from_period(period, fiscal_year_end_month)
            if inferred is not None:
                return inferred
        if dd >= 300:
            return 4
        if 150 <= dd <= 210:
            inferred = infer_quarter_from_period(period, fiscal_year_end_month)
            if inferred in {2, 4}:
                return inferred
    inferred = infer_quarter_from_period(period, fiscal_year_end_month)
    if inferred is not None:
        return inferred
    return None


def companyfacts_duration_days(start: Any, end: Any) -> Optional[int]:
    s = pd.to_datetime(start, errors="coerce")
    e = pd.to_datetime(end, errors="coerce")
    if pd.isna(s) or pd.isna(e):
        return None
    return int((e - s).days) + 1


def extract_companyfacts_records(payload: dict[str, Any], cik: str, field_name: str) -> pd.DataFrame:
    if not payload or "facts" not in payload:
        return pd.DataFrame(columns=["cik", "period", "accepted", "fy", "fp", "form", "field_name", "value"])

    facts = payload.get("facts", {})
    rows = []
    aliases = FSDS_TAG_ALIASES.get(field_name, [])
    for namespace in ["us-gaap", "dei", "ifrs-full"]:
        ns_facts = facts.get(namespace, {})
        if not isinstance(ns_facts, dict):
            continue
        for alias in aliases:
            fact = ns_facts.get(alias)
            if not isinstance(fact, dict):
                continue
            units = fact.get("units", {})
            if not isinstance(units, dict):
                continue
            for _, vals in units.items():
                if not isinstance(vals, list):
                    continue
                for item in vals:
                    if not isinstance(item, dict):
                        continue
                    end = pd.to_datetime(item.get("end"), errors="coerce")
                    filed_at = pd.to_datetime(item.get("filed"), errors="coerce")
                    val = safe_float(item.get("val"))
                    if pd.isna(end) or pd.isna(filed_at) or not np.isfinite(val):
                        continue
                    rows.append(
                        {
                            "cik": str(cik).zfill(10),
                            "period": end,
                            "accepted": filed_at,
                            "fy": item.get("fy"),
                            "fp": item.get("fp"),
                            "frame": item.get("frame"),
                            "form": item.get("form"),
                            "start": pd.to_datetime(item.get("start"), errors="coerce"),
                            "duration_days": companyfacts_duration_days(item.get("start"), item.get("end")),
                            "field_name": field_name,
                            "source_tag": alias,
                            "value": float(val),
                        }
                    )
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out = out.sort_values(["cik", "period", "accepted"]).drop_duplicates(
        ["cik", "period", "field_name", "source_tag", "accepted"], keep="last"
    )
    return out


def companyfacts_quarterly_flows(flow_records: pd.DataFrame) -> pd.DataFrame:
    if flow_records is None or flow_records.empty:
        return pd.DataFrame(columns=["cik", "period", "accepted", "field_name", "q_idx", "cum_value", "flow"])

    d = flow_records.copy()
    rows = []
    for (cik, field_name, fy), g in d.groupby(["cik", "field_name", "fy"], sort=False, dropna=False):
        fiscal_year_end_month = infer_fiscal_year_end_month(g)
        gg = g.copy()
        gg["q_idx"] = [
            companyfacts_quarter_index(
                fp,
                frame,
                period=period,
                duration_days=duration_days,
                fiscal_year_end_month=fiscal_year_end_month,
            )
            for fp, frame, period, duration_days in zip(
                gg["fp"],
                gg["frame"],
                gg["period"],
                gg["duration_days"],
            )
        ]
        gg = gg[gg["q_idx"].notna()].copy()
        if gg.empty:
            continue
        gg["q_idx"] = gg["q_idx"].astype(int)
        gg = gg.sort_values(["q_idx", "accepted"]).drop_duplicates(["q_idx"], keep="last")
        cumulative_by_q: dict[int, float] = {}
        for r in gg.itertuples(index=False):
            q_idx = int(getattr(r, "q_idx"))
            if q_idx < 1 or q_idx > 4:
                continue
            val = safe_float(getattr(r, "value"))
            if not np.isfinite(val):
                continue
            duration_days = getattr(r, "duration_days")
            fp = str(getattr(r, "fp", "")).upper()
            is_cumulative = bool(
                (q_idx == 4 and (fp == "FY" or (pd.notna(duration_days) and float(duration_days) >= 300)))
                or (q_idx in {2, 3, 4} and pd.notna(duration_days) and float(duration_days) > 120)
            )
            prev_cum = cumulative_by_q.get(q_idx - 1)
            if is_cumulative:
                flow = val - prev_cum if (q_idx > 1 and prev_cum is not None and np.isfinite(prev_cum)) else (val if q_idx == 1 else np.nan)
                cum_value = val
                cumulative_by_q[q_idx] = val
            else:
                flow = val
                if q_idx == 1:
                    cum_value = val
                    cumulative_by_q[q_idx] = val
                elif prev_cum is not None and np.isfinite(prev_cum):
                    cum_value = prev_cum + val
                    cumulative_by_q[q_idx] = cum_value
                else:
                    cum_value = np.nan
            rows.append(
                {
                    "cik": cik,
                    "period": getattr(r, "period"),
                    "accepted": getattr(r, "accepted"),
                    "field_name": field_name,
                    "q_idx": q_idx,
                    "cum_value": cum_value,
                    "flow": flow,
                }
            )
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out = out.dropna(subset=["period", "accepted"])
    out = out[out["flow"].notna() | out["cum_value"].notna()]
    out = out.sort_values(["cik", "period", "accepted"]).drop_duplicates(
        ["cik", "period", "field_name"], keep="last"
    )
    return out


def build_companyfacts_panel_for_ciks(cfg: EngineConfig, paths: dict[str, Path], cik_list: list[str]) -> pd.DataFrame:
    if not cik_list:
        return pd.DataFrame()

    norm_ciks = normalize_cik_list(cik_list)
    bulk_sources = companyfacts_bulk_sources(cfg, paths, norm_ciks)
    local_bulk_hits = sum(1 for cik in norm_ciks if any(cik in member_map for _, member_map in bulk_sources))
    if local_bulk_hits:
        log(
            "Using local SEC companyfacts bulk store "
            f"for {local_bulk_hits}/{len(norm_ciks)} CIKs (streaming payloads)."
        )

    balance_fields = ["assets", "liabilities", "shares"]
    flow_fields = ["revenues", "cost_of_revenue", "gross_profit", "op_income", "net_income", "ocf", "capex"]
    balance_frames = []
    flow_frames = []
    flow_cum_frames = []
    quarter_frames = []
    open_zip_sources: list[tuple[Path, dict[str, str], Optional[zipfile.ZipFile]]] = []
    try:
        for store, member_map in bulk_sources:
            zf: Optional[zipfile.ZipFile] = None
            if store.is_file() and store.suffix.lower() == ".zip":
                try:
                    zf = zipfile.ZipFile(store)
                except Exception:
                    continue
            open_zip_sources.append((store, member_map, zf))

        for i, cik in enumerate(norm_ciks, start=1):
            payload: dict[str, Any] = {}
            for store, member_map, zf in open_zip_sources:
                if cik not in member_map:
                    continue
                payload = load_local_companyfacts_bulk_payload(paths, store, member_map, cik, zf=zf)
                if payload:
                    break
            if not payload:
                payload = load_sec_companyfacts_json(cfg, paths, cik)
            if not payload:
                continue
            for field_name in balance_fields:
                rec = extract_companyfacts_records(payload, cik, field_name)
                if rec.empty:
                    continue
                rec = rec[rec["form"].astype(str).str.upper().isin(ACCEPTED_SEC_FORMS)].copy()
                if rec.empty:
                    continue
                rec = rec.sort_values(["cik", "period", "accepted"]).drop_duplicates(
                    ["cik", "period", "field_name"], keep="last"
                )
                balance_frames.append(rec[["cik", "period", "accepted", "field_name", "value"]])
            for field_name in flow_fields:
                rec = extract_companyfacts_records(payload, cik, field_name)
                if rec.empty:
                    continue
                rec = rec[rec["form"].astype(str).str.upper().isin(ACCEPTED_SEC_FORMS)].copy()
                if rec.empty:
                    continue
                flow_q = companyfacts_quarterly_flows(rec)
                if not flow_q.empty:
                    flow_frames.append(flow_q[["cik", "period", "accepted", "field_name", "flow"]])
                    flow_cum = flow_q[["cik", "period", "accepted", "field_name", "cum_value"]].copy()
                    flow_cum["field_name"] = flow_cum["field_name"].astype(str) + "_cum_value"
                    flow_cum = flow_cum.rename(columns={"cum_value": "value"})
                    flow_cum_frames.append(flow_cum[["cik", "period", "accepted", "field_name", "value"]])
                    quarter_frames.append(
                        flow_q[["cik", "period", "accepted", "q_idx"]].rename(columns={"q_idx": "quarter_index"})
                    )
            if i % 20 == 0:
                time.sleep(cfg.sec_sleep)
    finally:
        for _, _, zf in open_zip_sources:
            if zf is None:
                continue
            try:
                zf.close()
            except Exception:
                pass

    bal = pd.concat(balance_frames, ignore_index=True) if balance_frames else pd.DataFrame()
    flow = pd.concat(flow_frames, ignore_index=True) if flow_frames else pd.DataFrame()
    flow_cum = pd.concat(flow_cum_frames, ignore_index=True) if flow_cum_frames else pd.DataFrame()
    quarter_meta = pd.concat(quarter_frames, ignore_index=True) if quarter_frames else pd.DataFrame()
    if bal.empty and flow.empty:
        return pd.DataFrame()

    def pivot_panel(d: pd.DataFrame, value_col: str) -> pd.DataFrame:
        if d.empty:
            return pd.DataFrame(columns=["cik", "period"])
        p = d.pivot_table(index=["cik", "period"], columns="field_name", values=value_col, aggfunc="last").reset_index()
        p.columns = [c if isinstance(c, str) else str(c) for c in p.columns]
        return p

    acc_frames = []
    if not bal.empty:
        acc_frames.append(bal[["cik", "period", "accepted"]])
    if not flow.empty:
        acc_frames.append(flow[["cik", "period", "accepted"]])
    if not flow_cum.empty:
        acc_frames.append(flow_cum[["cik", "period", "accepted"]])
    acc = (
        pd.concat(acc_frames, ignore_index=True)
        .sort_values(["cik", "period", "accepted"])
        .drop_duplicates(["cik", "period"], keep="last")
        if acc_frames
        else pd.DataFrame(columns=["cik", "period", "accepted"])
    )

    panel = pivot_panel(bal, "value").merge(pivot_panel(flow, "flow"), on=["cik", "period"], how="outer")
    if not flow_cum.empty:
        panel = panel.merge(pivot_panel(flow_cum, "value"), on=["cik", "period"], how="outer")
    panel = panel.merge(acc, on=["cik", "period"], how="left")
    if not quarter_meta.empty:
        quarter_meta = (
            quarter_meta.sort_values(["cik", "period", "accepted"])
            .drop_duplicates(["cik", "period"], keep="last")
            .drop(columns=["accepted"], errors="ignore")
        )
        panel = panel.merge(quarter_meta, on=["cik", "period"], how="left")
    panel["asof_quarter"] = "companyfacts"
    panel["source"] = "companyfacts"
    return recompute_fund_panel_derived_columns(
        panel,
        ffill_quarters=cfg.fund_ttm_ffill_quarters,
        balance_ffill_quarters=cfg.fund_balance_ffill_quarters,
    )


def combine_fund_panels(primary: pd.DataFrame, secondary: pd.DataFrame) -> pd.DataFrame:
    if primary is None or primary.empty:
        return pd.DataFrame() if secondary is None else secondary.copy()
    if secondary is None or secondary.empty:
        return primary.copy()

    pri = primary.copy()
    sec = secondary.copy()
    pri["_source_rank"] = 0
    sec["_source_rank"] = 1
    combo = pd.concat([pri, sec], ignore_index=True, sort=False)
    combo["cik"] = normalize_cik_series(combo["cik"], index=combo.index)
    combo["period"] = pd.to_datetime(combo["period"], errors="coerce")
    combo["accepted"] = datetime_series_or_default(combo, "accepted")
    combo = combo.sort_values(["cik", "period", "_source_rank", "accepted"], ascending=[True, True, True, False])
    grouped = combo.groupby(["cik", "period"], as_index=False).first()
    if "_source_rank" in grouped.columns:
        grouped = grouped.drop(columns=["_source_rank"])
    return grouped


def _ishares_try_read_csv(url: str) -> pd.DataFrame:
    raw = http_get(url, headers=HEADERS_ISHARES, timeout=60).content.decode("utf-8", errors="replace")
    lines = raw.splitlines()
    header_idx = next((i for i, ln in enumerate(lines) if ln.startswith("Ticker,")), None)
    if header_idx is None:
        return pd.DataFrame()
    df = pd.read_csv(io.StringIO("\n".join(lines[header_idx:])))
    df.columns = [c.strip() for c in df.columns]
    return df


def read_ishares_holdings(product_url: str, etf_symbol: str) -> pd.DataFrame:
    html = http_get(product_url, headers=HEADERS_ISHARES, timeout=60).text
    ajax_ids = list(dict.fromkeys(re.findall(r"(\d{13})\.ajax", html)))
    if not ajax_ids:
        raise RuntimeError(f"No .ajax id found: {product_url}")
    base = product_url.rstrip("/")
    for aid in ajax_ids:
        url = f"{base}/{aid}.ajax?fileType=csv&fileName={etf_symbol}_holdings&dataType=fund"
        df = _ishares_try_read_csv(url)
        if not df.empty and "Ticker" in df.columns:
            return df
        time.sleep(0.2)
    raise RuntimeError(f"Failed to fetch iShares holdings for {etf_symbol}")


def fetch_wikipedia_tickers(url: str, table_idx: int, ticker_col: str) -> pd.DataFrame:
    tables = pd.read_html(url)
    if table_idx >= len(tables):
        return pd.DataFrame(columns=["ticker", "Name"])
    t = tables[table_idx].copy()
    if ticker_col not in t.columns:
        return pd.DataFrame(columns=["ticker", "Name"])
    name_col = "Security" if "Security" in t.columns else ("Company" if "Company" in t.columns else ticker_col)
    out = pd.DataFrame({"ticker": t[ticker_col].map(normalize_ticker), "Name": t[name_col].astype(str)})
    out = out[out["ticker"].map(is_valid_ticker)]
    return out


def read_table_auto(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".parquet":
        return pd.read_parquet(path)
    if suffix in {".csv", ".txt"}:
        return pd.read_csv(path)
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(path)
    if suffix == ".json":
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, list):
            return pd.DataFrame(raw)
        if isinstance(raw, dict):
            payload = raw.get("data", raw)
            if isinstance(payload, list):
                return pd.DataFrame(payload)
            if isinstance(payload, dict):
                try:
                    return pd.DataFrame(payload)
                except Exception:
                    return pd.DataFrame([payload])
    return pd.DataFrame()


def normalize_membership_frame(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=["ticker", "Name", "sector", "cik10", "rebalance_date", "date_from", "date_to"])

    d = df.copy()
    cols = {c.lower(): c for c in d.columns}
    ticker_col = next((cols[c] for c in ["ticker", "symbol"] if c in cols), None)
    if ticker_col is None:
        return pd.DataFrame(columns=["ticker", "Name", "sector", "cik10", "rebalance_date", "date_from", "date_to"])

    out = pd.DataFrame({"ticker": d[ticker_col].map(normalize_ticker)})
    name_col = next((cols[c] for c in ["name", "company", "security", "title"] if c in cols), None)
    sector_col = next((cols[c] for c in ["sector", "gics_sector", "industry_sector"] if c in cols), None)
    cik_col = next((cols[c] for c in ["cik10", "cik", "cik_str"] if c in cols), None)
    snap_col = next((cols[c] for c in ["rebalance_date", "asof_date", "effective_date", "date"] if c in cols), None)
    from_col = next((cols[c] for c in ["date_from", "effective_from", "start_date", "from_date"] if c in cols), None)
    to_col = next((cols[c] for c in ["date_to", "effective_to", "end_date", "to_date"] if c in cols), None)

    out["Name"] = d[name_col].astype(str) if name_col is not None else ""
    out["sector"] = d[sector_col].astype(str) if sector_col is not None else "Unknown"
    if cik_col is not None:
        out["cik10"] = normalize_cik_series(d[cik_col], index=d.index)
    else:
        out["cik10"] = pd.Series(np.nan, index=d.index, dtype=object)
    out["rebalance_date"] = pd.to_datetime(d[snap_col], errors="coerce") if snap_col is not None else pd.NaT
    out["date_from"] = pd.to_datetime(d[from_col], errors="coerce") if from_col is not None else pd.NaT
    out["date_to"] = pd.to_datetime(d[to_col], errors="coerce") if to_col is not None else pd.NaT
    out = out[out["ticker"].map(is_valid_ticker)]
    out = out[~out.apply(lambda r: looks_like_noncommon(r["ticker"], r.get("Name")), axis=1)]
    out = out.drop_duplicates().reset_index(drop=True)
    return out


def auto_membership_archive_dir(paths: dict[str, Path]) -> Path:
    p = paths["data_raw"] / "universe_membership_snapshots"
    safe_mkdir(p)
    return p


def write_current_universe_membership_snapshot(
    cfg: EngineConfig,
    paths: dict[str, Path],
    universe: pd.DataFrame,
) -> Optional[Path]:
    if (not getattr(cfg, "archive_current_universe_snapshots", True)) or universe is None or universe.empty:
        return None

    snapshot_dt = pd.to_datetime(getattr(cfg, "end_date", None), errors="coerce")
    now_dt = pd.Timestamp.utcnow().tz_localize(None).normalize()
    if pd.isna(snapshot_dt):
        snapshot_dt = now_dt
    snapshot_dt = pd.Timestamp(snapshot_dt).normalize()
    if abs(int((now_dt - snapshot_dt).days)) > max(int(cfg.auto_membership_snapshot_max_lag_days), 0):
        return None

    keep_cols = ["ticker", "Name", "sector", "cik10"]
    snap = universe.copy()
    for c in keep_cols:
        if c not in snap.columns:
            snap[c] = np.nan
    snap = snap[keep_cols].copy()
    snap["ticker"] = snap["ticker"].map(normalize_ticker)
    snap = snap[snap["ticker"].map(is_valid_ticker)]
    snap["rebalance_date"] = snapshot_dt
    snap = snap.drop_duplicates(["ticker", "rebalance_date"]).sort_values(["rebalance_date", "ticker"])
    if snap.empty:
        return None

    archive_dir = auto_membership_archive_dir(paths)
    monthly_path = archive_dir / f"historical_universe_membership_{snapshot_dt.strftime('%Y_%m')}.csv"
    snap.to_csv(monthly_path, index=False)

    combined_path = paths["data_raw"] / "historical_universe_membership_auto.csv"
    if combined_path.exists():
        try:
            existing = normalize_membership_frame(read_table_auto(combined_path))
        except Exception:
            existing = pd.DataFrame(columns=snap.columns)
    else:
        existing = pd.DataFrame(columns=snap.columns)
    combo = pd.concat([existing, snap], ignore_index=True, sort=False)
    combo = combo.drop_duplicates(["ticker", "rebalance_date"], keep="last").sort_values(["rebalance_date", "ticker"])
    combo.to_csv(combined_path, index=False)
    return monthly_path


def historical_membership_candidates(cfg: EngineConfig, paths: dict[str, Path]) -> list[Path]:
    explicit = (cfg.universe_membership_path or "").strip()
    cands: list[Path] = []
    if explicit:
        cands.append(Path(explicit))
    cands.extend(
        [
            paths["data_raw"] / "historical_universe_membership_auto.csv",
            paths["data_raw"] / "historical_universe_membership.parquet",
            paths["data_raw"] / "historical_universe_membership.csv",
            paths["data_raw"] / "historical_universe_membership.xlsx",
        ]
    )
    return cands


def load_historical_universe_membership(cfg: EngineConfig, paths: dict[str, Path]) -> pd.DataFrame:
    for path in historical_membership_candidates(cfg, paths):
        if not path.exists():
            continue
        try:
            d = normalize_membership_frame(read_table_auto(path))
            if not d.empty:
                return d
        except Exception as e:
            log(f"[WARN] failed to read historical universe membership {path.name}: {e}")
    return pd.DataFrame(columns=["ticker", "Name", "sector", "cik10", "rebalance_date", "date_from", "date_to"])


def apply_historical_membership_filter(monthly: pd.DataFrame, membership: pd.DataFrame) -> pd.DataFrame:
    if monthly.empty or membership is None or membership.empty:
        return monthly

    d = monthly.copy()
    d["rebalance_date"] = pd.to_datetime(d["rebalance_date"], errors="coerce")
    m = membership.copy()
    m["rebalance_date"] = pd.to_datetime(m.get("rebalance_date"), errors="coerce")
    m["date_from"] = pd.to_datetime(m.get("date_from"), errors="coerce")
    m["date_to"] = pd.to_datetime(m.get("date_to"), errors="coerce")

    if m["rebalance_date"].notna().any():
        keep = m[["ticker", "rebalance_date"]].dropna().drop_duplicates()
        covered_dates = set(pd.to_datetime(keep["rebalance_date"], errors="coerce").dropna().tolist())
        out = d.merge(keep.assign(_keep=1), on=["ticker", "rebalance_date"], how="left")
        keep_mask = (~out["rebalance_date"].isin(covered_dates)) | (pd.to_numeric(out["_keep"], errors="coerce").fillna(0.0) > 0)
        return out.loc[keep_mask].drop(columns="_keep")

    if m["date_from"].notna().any() or m["date_to"].notna().any():
        chunks = []
        for ticker, g in d.groupby("ticker", sort=False):
            mem = m[m["ticker"] == ticker]
            if mem.empty:
                continue
            if mem[["date_from", "date_to"]].isna().all().all():
                chunks.append(g)
                continue
            mask = pd.Series(False, index=g.index)
            for r in mem.itertuples(index=False):
                start = getattr(r, "date_from", pd.NaT)
                end = getattr(r, "date_to", pd.NaT)
                cond = pd.Series(True, index=g.index)
                if pd.notna(start):
                    cond &= g["rebalance_date"] >= start
                if pd.notna(end):
                    cond &= g["rebalance_date"] <= end
                mask |= cond
            chunks.append(g[mask])
        return pd.concat(chunks, ignore_index=True) if chunks else d.iloc[0:0].copy()

    keep = set(m["ticker"].dropna().astype(str).tolist())
    return d[d["ticker"].isin(keep)].copy()


def sec_actual_root(cfg: EngineConfig, paths: dict[str, Path]) -> Path:
    explicit = (cfg.sec_actual_local_dir or "").strip()
    return Path(explicit) if explicit else (paths["data_raw"] / "sec_actual")


def normalize_sec_13f_snapshot(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=["ticker", "filed_at"] + SEC_13F_COLUMNS)

    d = normalize_table_columns(df)
    ticker_col = next((c for c in ["ticker", "symbol"] if c in d.columns), None)
    filed_col = next((c for c in ["filed_at", "filing_date", "accepted", "asof_date", "report_date"] if c in d.columns), None)
    if ticker_col is None or filed_col is None:
        return pd.DataFrame(columns=["ticker", "filed_at"] + SEC_13F_COLUMNS)

    out = pd.DataFrame(
        {
            "ticker": d[ticker_col].map(normalize_ticker),
            "filed_at": pd.to_datetime(d[filed_col], errors="coerce"),
            "sec13f_holders_count": pd.to_numeric(d.get("holders_count", d.get("manager_count")), errors="coerce"),
            "sec13f_shares": pd.to_numeric(d.get("shares", d.get("shares_held")), errors="coerce"),
            "sec13f_value": pd.to_numeric(d.get("value", d.get("market_value")), errors="coerce"),
            "sec13f_delta_shares": pd.to_numeric(d.get("delta_shares", d.get("position_change_shares")), errors="coerce"),
            "sec13f_delta_value": pd.to_numeric(d.get("delta_value", d.get("position_change_value")), errors="coerce"),
        }
    )
    out = out[out["ticker"].map(is_valid_ticker)]
    out = out.dropna(subset=["filed_at"]).sort_values(["ticker", "filed_at"])
    if out.empty:
        return out
    agg = (
        out.groupby(["ticker", "filed_at"], as_index=False)[SEC_13F_COLUMNS]
        .sum(min_count=1)
        .sort_values(["ticker", "filed_at"])
    )
    return agg


def normalize_sec_form345_snapshot(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=["ticker", "filed_at"] + SEC_FORM345_COLUMNS)

    d = normalize_table_columns(df)
    ticker_col = next((c for c in ["ticker", "symbol"] if c in d.columns), None)
    filed_col = next((c for c in ["filed_at", "filing_date", "accepted", "transaction_date", "date"] if c in d.columns), None)
    if ticker_col is None or filed_col is None:
        return pd.DataFrame(columns=["ticker", "filed_at"] + SEC_FORM345_COLUMNS)

    out = pd.DataFrame(
        {
            "ticker": d[ticker_col].map(normalize_ticker),
            "filed_at": pd.to_datetime(d[filed_col], errors="coerce"),
            "sec_form345_txn_count": pd.to_numeric(d.get("txn_count", 1), errors="coerce"),
            "sec_form345_buy_shares": pd.to_numeric(d.get("buy_shares", d.get("shares_bought")), errors="coerce"),
            "sec_form345_sell_shares": pd.to_numeric(d.get("sell_shares", d.get("shares_sold")), errors="coerce"),
            "sec_form345_net_shares": pd.to_numeric(d.get("net_shares", d.get("share_change")), errors="coerce"),
            "sec_form345_buy_ratio": pd.to_numeric(d.get("buy_ratio"), errors="coerce"),
        }
    )
    out = out[out["ticker"].map(is_valid_ticker)]
    out = out.dropna(subset=["filed_at"]).sort_values(["ticker", "filed_at"])
    if out.empty:
        return out
    agg = (
        out.groupby(["ticker", "filed_at"], as_index=False)[SEC_FORM345_COLUMNS]
        .sum(min_count=1)
        .sort_values(["ticker", "filed_at"])
    )
    ratio_base = agg["sec_form345_buy_shares"].fillna(0.0) + agg["sec_form345_sell_shares"].fillna(0.0)
    agg["sec_form345_buy_ratio"] = agg["sec_form345_buy_shares"].fillna(0.0) / ratio_base.where(ratio_base > 0, np.nan)
    return agg


def load_local_sec_actual_snapshots(cfg: EngineConfig, paths: dict[str, Path], kind: str) -> pd.DataFrame:
    if not cfg.use_sec_actual_data:
        return pd.DataFrame()

    root = sec_actual_root(cfg, paths)
    if not root.exists():
        return pd.DataFrame()

    patterns = {
        "13f": ["*13f*.parquet", "*13f*.csv", "*13f*.xlsx", "*form13f*.parquet", "*form13f*.csv", "*form13f*.xlsx"],
        "345": ["*345*.parquet", "*345*.csv", "*345*.xlsx", "*form4*.parquet", "*form4*.csv", "*form4*.xlsx"],
    }
    rows = []
    for pat in patterns.get(kind, []):
        rows.extend(sorted(root.glob(pat)))
    rows = list(dict.fromkeys(rows))
    if not rows:
        return pd.DataFrame()

    frames = []
    for path in rows:
        try:
            raw = read_table_auto(path)
            norm = normalize_sec_13f_snapshot(raw) if kind == "13f" else normalize_sec_form345_snapshot(raw)
            if not norm.empty:
                frames.append(norm)
        except Exception as e:
            log(f"[WARN] failed to normalize SEC actual file {path.name}: {e}")
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    out = out.sort_values(["ticker", "filed_at"]).drop_duplicates(["ticker", "filed_at"], keep="last")
    return out


def merge_sec_actual_snapshots(monthly: pd.DataFrame, sec13f: pd.DataFrame, form345: pd.DataFrame) -> pd.DataFrame:
    if monthly.empty:
        return monthly

    d = monthly.copy()
    d["rebalance_date"] = pd.to_datetime(d["rebalance_date"], errors="coerce")

    def _merge_asof_per_ticker(base: pd.DataFrame, snap: pd.DataFrame) -> pd.DataFrame:
        if snap is None or snap.empty:
            return base
        snap = snap.copy()
        snap["filed_at"] = pd.to_datetime(snap["filed_at"], errors="coerce")
        snap = snap.dropna(subset=["filed_at"]).sort_values(["ticker", "filed_at"])
        chunks = []
        for ticker, g in base.groupby("ticker", sort=False):
            s = snap[snap["ticker"] == ticker]
            gg = g.sort_values("rebalance_date").copy()
            if s.empty:
                for c in snap.columns:
                    if c not in {"ticker", "filed_at"} and c not in gg.columns:
                        gg[c] = np.nan
                chunks.append(gg)
                continue
            merged = pd.merge_asof(
                gg,
                s.sort_values("filed_at"),
                left_on="rebalance_date",
                right_on="filed_at",
                by="ticker",
                direction="backward",
            )
            if "filed_at" in merged.columns:
                merged = merged.drop(columns=["filed_at"])
            chunks.append(merged)
        return pd.concat(chunks, ignore_index=True)

    d = _merge_asof_per_ticker(d, sec13f)
    d = _merge_asof_per_ticker(d, form345)
    return d


def write_stage_coverage_report(paths: dict[str, Path], name: str, df: pd.DataFrame, columns: list[str]) -> Path:
    rows = []
    n = len(df)
    for c in dict.fromkeys(columns):
        rows.append(
            {
                "column": c,
                "non_null_count": int(df[c].notna().sum()) if c in df.columns else 0,
                "non_null_ratio": float(df[c].notna().mean()) if c in df.columns and n else 0.0,
            }
        )
    out = pd.DataFrame(rows)
    path = paths["reports"] / f"{name}_coverage.csv"
    out.to_csv(path, index=False)
    return path


def write_universe_change_report(
    paths: dict[str, Path],
    previous_df: Optional[pd.DataFrame],
    current_df: pd.DataFrame,
    warn_count: int = 10,
) -> dict[str, Path]:
    summary_path = paths["reports"] / "candidate_universe_change_latest.json"
    detail_path = paths["reports"] / "candidate_universe_change_latest.csv"

    prev = previous_df.copy() if previous_df is not None else pd.DataFrame()
    curr = current_df.copy()
    prev_tickers = set(prev.get("ticker", pd.Series(dtype=str)).dropna().astype(str).tolist())
    curr_tickers = set(curr.get("ticker", pd.Series(dtype=str)).dropna().astype(str).tolist())
    added = sorted(curr_tickers - prev_tickers)
    removed = sorted(prev_tickers - curr_tickers)

    rows = (
        [{"change_type": "added", "ticker": t} for t in added]
        + [{"change_type": "removed", "ticker": t} for t in removed]
    )
    pd.DataFrame(rows, columns=["change_type", "ticker"]).to_csv(detail_path, index=False)

    summary = {
        "previous_count": int(len(prev_tickers)),
        "current_count": int(len(curr_tickers)),
        "added_count": int(len(added)),
        "removed_count": int(len(removed)),
        "added_sample": added[:warn_count],
        "removed_sample": removed[:warn_count],
    }
    summary_path.write_text(json.dumps(summary, indent=2))

    if added or removed:
        log(
            "Universe change detected: "
            f"current={len(curr_tickers)}, added={len(added)}, removed={len(removed)}"
        )
        if added:
            log(f"Universe added sample: {', '.join(added[:warn_count])}")
        if removed:
            log(f"Universe removed sample: {', '.join(removed[:warn_count])}")
    else:
        log(f"Universe change detected: no membership change (current={len(curr_tickers)})")

    return {
        "candidate_universe_change_summary": summary_path,
        "candidate_universe_change_detail": detail_path,
    }


def log_core_fundamental_coverage(df: pd.DataFrame, label: str) -> None:
    if df is None or df.empty:
        log(f"{label}: no rows")
        return

    cols = [
        "revenues_ttm",
        "gross_profit_ttm",
        "op_income_ttm",
        "op_margin_ttm",
        "net_income_ttm",
        "roe_proxy",
        "gross_margins",
        "operating_margins",
        "return_on_equity_live",
    ]
    parts = []
    low_parts = []
    for c in cols:
        if c not in df.columns:
            ratio = 0.0
        else:
            ratio = float(pd.to_numeric(df[c], errors="coerce").notna().mean())
        parts.append(f"{c}={ratio:.1%}")
        if ratio < 0.70:
            low_parts.append(f"{c}={ratio:.1%}")

    log(f"{label}: " + ", ".join(parts))
    if low_parts:
        log(f"{label} low-coverage fields: " + ", ".join(low_parts))


def write_market_adaptation_report(paths: dict[str, Path], df: pd.DataFrame, cfg: Optional[EngineConfig] = None) -> Path:
    path = paths["reports"] / "market_adaptation_latest.json"
    if df is None or df.empty:
        path.write_text(json.dumps({"empty": True}, indent=2), encoding="utf-8")
        return path

    d = df.copy()
    d["rebalance_date"] = datetime_series_or_default(d, "rebalance_date")
    latest_dt = d["rebalance_date"].max()
    latest = d[d["rebalance_date"] == latest_dt].copy() if pd.notna(latest_dt) else d.copy()
    if latest.empty:
        path.write_text(json.dumps({"empty": True}, indent=2), encoding="utf-8")
        return path

    score_col = "score" if "score" in latest.columns else ("strategy_blueprint_score" if "strategy_blueprint_score" in latest.columns else "mom_6m")
    if score_col not in latest.columns:
        latest[score_col] = np.nan
    sector_summary = (
        latest.groupby("sector", as_index=False)
        .agg(
            avg_score=(score_col, "mean"),
            avg_mom_6m=("mom_6m", "mean"),
            avg_breadth=("price_above_ma200", "mean"),
            names=("ticker", "count"),
        )
        .sort_values(["avg_score", "avg_mom_6m"], ascending=[False, False])
        .head(8)
    )
    sample = latest.iloc[0]
    stagflation_score = float(np.nan_to_num(safe_float(sample.get("stagflation_score")), nan=0.0))
    growth_liquidity_score = float(np.nan_to_num(safe_float(sample.get("growth_liquidity_reentry_score")), nan=0.0))
    growth_reentry_score = float(np.nan_to_num(safe_float(sample.get("growth_reentry_score")), nan=0.0))
    liquidity_impulse_score = float(np.nan_to_num(safe_float(sample.get("liquidity_impulse_score")), nan=0.0))
    liquidity_drain_score = float(np.nan_to_num(safe_float(sample.get("liquidity_drain_score")), nan=0.0))
    fear_greed_score = safe_float(sample.get("fear_greed_score"))
    fear_greed_risk_off = float(np.nan_to_num(safe_float(sample.get("fear_greed_risk_off_score")), nan=0.0))
    fear_greed_risk_on = float(np.nan_to_num(safe_float(sample.get("fear_greed_risk_on_score")), nan=0.0))
    summary = {
        "latest_rebalance_date": str(pd.Timestamp(latest_dt).date()) if pd.notna(latest_dt) else None,
        "market_breadth_above_ma200": safe_float(sample.get("market_breadth_above_ma200")),
        "market_breadth_above_ma150": safe_float(sample.get("market_breadth_above_ma150")),
        "market_trend_template_ratio": safe_float(sample.get("market_trend_template_ratio")),
        "market_near_high_ratio": safe_float(sample.get("market_near_high_ratio")),
        "market_sector_participation": safe_float(sample.get("market_sector_participation")),
        "market_leadership_narrowing": safe_float(sample.get("market_leadership_narrowing")),
        "market_overheat_ratio": safe_float(sample.get("market_overheat_ratio")),
        "market_breadth_regime_score": safe_float(sample.get("market_breadth_regime_score")),
        "systemic_crisis_score": safe_float(sample.get("systemic_crisis_score")),
        "carry_unwind_stress_score": safe_float(sample.get("carry_unwind_stress_score")),
        "war_oil_rate_shock_score": safe_float(sample.get("war_oil_rate_shock_score")),
        "defensive_rotation_score": safe_float(sample.get("defensive_rotation_score")),
        "growth_reentry_score": safe_float(sample.get("growth_reentry_score")),
        "inflation_reacceleration_score": safe_float(sample.get("inflation_reacceleration_score")),
        "upstream_cost_pressure_score": safe_float(sample.get("upstream_cost_pressure_score")),
        "labor_softening_score": safe_float(sample.get("labor_softening_score")),
        "stagflation_score": safe_float(sample.get("stagflation_score")),
        "growth_liquidity_reentry_score": safe_float(sample.get("growth_liquidity_reentry_score")),
        "m2_yoy_lag1m": safe_float(sample.get("m2_yoy_lag1m")),
        "fed_assets_bil": safe_float(sample.get("fed_assets_bil")),
        "reverse_repo_bil": safe_float(sample.get("reverse_repo_bil")),
        "tga_bil": safe_float(sample.get("tga_bil")),
        "net_liquidity_bil": safe_float(sample.get("net_liquidity_bil")),
        "net_liquidity_change_1m_bil": safe_float(sample.get("net_liquidity_change_1m_bil")),
        "liquidity_impulse_score": safe_float(sample.get("liquidity_impulse_score")),
        "liquidity_drain_score": safe_float(sample.get("liquidity_drain_score")),
        "fear_greed_score": fear_greed_score,
        "fear_greed_delta_1w": safe_float(sample.get("fear_greed_delta_1w")),
        "fear_greed_risk_off_score": safe_float(sample.get("fear_greed_risk_off_score")),
        "fear_greed_risk_on_score": safe_float(sample.get("fear_greed_risk_on_score")),
        "cpi_yoy": safe_float(sample.get("cpi_yoy")),
        "core_cpi_yoy": safe_float(sample.get("core_cpi_yoy")),
        "cpi_3m_ann": safe_float(sample.get("cpi_3m_ann")),
        "ppi_yoy": safe_float(sample.get("ppi_yoy")),
        "ppi_cpi_gap": safe_float(sample.get("ppi_cpi_gap")),
        "unrate_level": safe_float(sample.get("unrate_level")),
        "unrate_3m_change": safe_float(sample.get("unrate_3m_change")),
        "sahm_realtime": safe_float(sample.get("sahm_realtime")),
        "event_regime_label": str(sample.get("event_regime_label", "")),
        "live_event_alert_label": str(sample.get("live_event_alert_label", "")),
        "live_event_risk_score": safe_float(sample.get("live_event_risk_score")),
        "live_event_systemic_score": safe_float(sample.get("live_event_systemic_score")),
        "live_event_war_oil_rate_score": safe_float(sample.get("live_event_war_oil_rate_score")),
        "live_event_defensive_score": safe_float(sample.get("live_event_defensive_score")),
        "live_event_growth_reentry_score": safe_float(sample.get("live_event_growth_reentry_score")),
        "macro_style_tilt_label": (
            "value_dividend_defensive"
            if stagflation_score >= max(growth_liquidity_score, growth_reentry_score, 0.55)
            else ("growth_liquidity_reentry" if max(growth_liquidity_score, growth_reentry_score) >= 0.60 else "balanced")
        ),
        "liquidity_backdrop_label": (
            "liquidity_tailwind"
            if liquidity_impulse_score >= max(liquidity_drain_score, 0.55)
            else (
                "liquidity_headwind"
                if liquidity_drain_score >= max(liquidity_impulse_score, 0.55)
                else "mixed_liquidity"
            )
        ),
        "fear_greed_label": (
            "extreme_fear"
            if (fear_greed_score is not None and not np.isnan(fear_greed_score) and fear_greed_score <= 25.0)
            else (
                "fear"
                if (fear_greed_score is not None and not np.isnan(fear_greed_score) and fear_greed_score <= 45.0)
                else (
                    "extreme_greed"
                    if (fear_greed_score is not None and not np.isnan(fear_greed_score) and fear_greed_score >= 75.0)
                    else ("greed" if (fear_greed_score is not None and not np.isnan(fear_greed_score) and fear_greed_score >= 55.0) else "neutral")
                )
            )
        ),
        "benchmark_history_source": benchmark_history_source_label(cfg) if cfg is not None else "",
        "top_sectors": sector_summary.to_dict(orient="records"),
    }
    path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return path


def build_candidate_universe(cfg: EngineConfig, paths: dict[str, Path]) -> pd.DataFrame:
    out_path = paths["feature_store"] / "candidate_universe_latest.parquet"
    log("Building candidate universe from free sources ...")
    hist_membership = load_historical_universe_membership(cfg, paths)
    try:
        prev = pd.read_parquet(out_path) if out_path.exists() else pd.DataFrame()
    except Exception:
        prev = pd.DataFrame()

    if not hist_membership.empty:
        uni = hist_membership.copy()
        if uni["Name"].replace("", np.nan).notna().sum() == 0:
            uni["Name"] = ""
        if "sector" not in uni.columns:
            uni["sector"] = "Unknown"
        uni["universe_source"] = "historical_membership_file"
    else:
        iwb_url = "https://www.ishares.com/us/products/239707/ishares-russell-1000-etf"
        frames = []
        try:
            iwb = read_ishares_holdings(iwb_url, "IWB")
            iwb = iwb.rename(columns={"Ticker": "ticker"})
            iwb["ticker"] = iwb["ticker"].map(normalize_ticker)
            iwb["Name"] = iwb["Name"].astype(str) if "Name" in iwb.columns else ""
            iwb["sector"] = iwb["Sector"].astype(str) if "Sector" in iwb.columns else "Unknown"
            iwb = iwb[iwb["ticker"].map(is_valid_ticker)]
            iwb = iwb[~iwb.apply(lambda r: looks_like_noncommon(r["ticker"], r.get("Name")), axis=1)]
            frames.append(iwb[["ticker", "Name", "sector"]])
        except Exception as e:
            log(f"[WARN] IWB holdings fetch failed: {e}")

        if cfg.use_wikipedia_lists:
            try:
                sp500 = fetch_wikipedia_tickers(
                    "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
                    table_idx=0,
                    ticker_col="Symbol",
                )
                sp500["sector"] = "Unknown"
                frames.append(sp500[["ticker", "Name", "sector"]])
            except Exception as e:
                log(f"[WARN] S&P500 fetch failed: {e}")

            try:
                ndx = fetch_wikipedia_tickers(
                    "https://en.wikipedia.org/wiki/Nasdaq-100",
                    table_idx=4,
                    ticker_col="Ticker",
                )
                ndx["sector"] = "Unknown"
                frames.append(ndx[["ticker", "Name", "sector"]])
            except Exception as e:
                log(f"[WARN] Nasdaq-100 fetch failed: {e}")

        if not frames:
            raise RuntimeError("Unable to build candidate universe from sources.")

        uni = pd.concat(frames, ignore_index=True)
        uni["universe_source"] = "current_constituents_proxy"

    uni["ticker"] = uni["ticker"].map(normalize_ticker)
    uni = uni[uni["ticker"].map(is_valid_ticker)]
    uni = uni[~uni["ticker"].duplicated(keep="first")].copy()

    sec_map = load_sec_company_tickers(cfg, paths)
    uni = uni.merge(sec_map, on="ticker", how="left")
    uni["Name"] = uni["Name"].replace("", np.nan)
    uni["Name"] = uni["Name"].fillna(uni["title"]).fillna("")
    uni["sector"] = uni["sector"].fillna("Unknown")
    if "cik10_x" in uni.columns or "cik10_y" in uni.columns:
        cik10_x = uni["cik10_x"] if "cik10_x" in uni.columns else pd.Series(np.nan, index=uni.index)
        cik10_y = uni["cik10_y"] if "cik10_y" in uni.columns else pd.Series(np.nan, index=uni.index)
        uni["cik10"] = cik10_x.fillna(cik10_y)
    uni = uni[["ticker", "Name", "sector", "cik10", "universe_source"]].copy()
    snapshot_path = write_current_universe_membership_snapshot(cfg, paths, uni)
    if snapshot_path is not None:
        log(f"Archived current universe membership snapshot: {snapshot_path.name}")
    write_universe_change_report(paths, prev, uni, warn_count=int(cfg.universe_change_warn_count))
    uni.to_parquet(out_path, index=False)
    return uni


def load_fail_tickers(paths: dict[str, Path]) -> set[str]:
    p = paths["cache_misc"] / "yf_fail_tickers.json"
    if p.exists():
        try:
            return set(json.loads(p.read_text()))
        except Exception:
            return set()
    return set()


def save_fail_tickers(paths: dict[str, Path], fail: set[str]) -> None:
    (paths["cache_misc"] / "yf_fail_tickers.json").write_text(json.dumps(sorted(fail)))


def load_px(paths: dict[str, Path], ticker: str) -> Optional[pd.DataFrame]:
    p = paths["cache_prices"] / px_cache_name(ticker)
    if not p.exists():
        return None
    try:
        df = pd.read_parquet(p)
    except Exception:
        return None
    df.index = pd.to_datetime(df.index).tz_localize(None)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df


def save_px(paths: dict[str, Path], ticker: str, df: pd.DataFrame) -> None:
    p = paths["cache_prices"] / px_cache_name(ticker)
    x = df.copy()
    x.index = pd.to_datetime(x.index).tz_localize(None)
    if isinstance(x.columns, pd.MultiIndex):
        x.columns = x.columns.get_level_values(0)
    x.to_parquet(p, index=True)


def adjusted_open_series(hist: pd.DataFrame) -> pd.Series:
    if hist is None or hist.empty or "Open" not in hist.columns:
        return pd.Series(dtype=float)
    d = hist.copy()
    d.index = pd.to_datetime(d.index).tz_localize(None)
    open_ = pd.to_numeric(squeeze_series(d["Open"]), errors="coerce").astype(float)
    close = pd.to_numeric(squeeze_series(d.get("Close")), errors="coerce").astype(float)
    if "Adj Close" in d.columns:
        adj_close = pd.to_numeric(squeeze_series(d["Adj Close"]), errors="coerce").astype(float)
        adj_factor = adj_close / close.replace(0, np.nan)
    else:
        adj_factor = pd.Series(1.0, index=open_.index, dtype=float)
    adj_open = open_ * adj_factor.replace([np.inf, -np.inf], np.nan).fillna(1.0)
    adj_open.index = d.index
    return adj_open.astype(float)


def macro_cache_file(paths: dict[str, Path], name: str) -> Path:
    return paths["cache_macro"] / f"{name}.parquet"


def price_close_series(hist: pd.DataFrame) -> pd.Series:
    if hist is None or hist.empty:
        return pd.Series(dtype=float)
    if "Adj Close" in hist.columns:
        close = pd.to_numeric(squeeze_series(hist["Adj Close"]), errors="coerce")
    else:
        close = pd.to_numeric(squeeze_series(hist.get("Close")), errors="coerce")
    close.index = pd.to_datetime(close.index).tz_localize(None)
    return close.astype(float).dropna()


# Stage 2c (2026-04-20): rolling_robust_z + row_mean moved to r1000_helpers.py.


# Stage 4a (2026-04-20): sleeve_weight_l1_norm + resolve_regime_sleeve_multipliers
# moved to r1000_signals.py (with the main compute_portfolio_sleeve_* block).




# Stage 2c (2026-04-20): weighted_sleeve_composite moved to r1000_helpers.py.


def to_naive_datetime_index(values: Any) -> pd.DatetimeIndex:
    dt = pd.to_datetime(values, errors="coerce", utc=True)
    if isinstance(dt, pd.Series):
        dt = dt.dt.tz_convert(None)
        return pd.DatetimeIndex(dt)
    return pd.DatetimeIndex(dt).tz_convert(None)


def load_fred_series(cfg: EngineConfig, paths: dict[str, Path], name: str, series_id: str) -> pd.Series:
    cache_path = macro_cache_file(paths, f"fred_{name}_{series_id}")
    if is_cache_fresh(cache_path, cfg.macro_refresh_days):
        try:
            df = pd.read_parquet(cache_path)
            s = pd.to_numeric(df["value"], errors="coerce")
            s.index = to_naive_datetime_index(df["date"])
            return s.sort_index()
        except Exception:
            pass

    # Prefer FRED API with key (higher rate limit), fallback to CSV scrape
    fred_key = getattr(cfg, "fred_api_key", "")
    if fred_key:
        api_url = (
            f"https://api.stlouisfed.org/fred/series/observations"
            f"?series_id={series_id}&api_key={fred_key}&file_type=json"
        )
        headers_api = {"User-Agent": cfg.sec_user_agent}
        try:
            resp = http_get(api_url, headers=headers_api, timeout=120)
            data = resp.json()
            obs = data.get("observations", [])
            if obs:
                df = pd.DataFrame(obs)
                df = pd.DataFrame({
                    "date": pd.to_datetime(df["date"], errors="coerce"),
                    "value": pd.to_numeric(df["value"], errors="coerce"),
                }).dropna(subset=["date"])
                df = df.sort_values("date").drop_duplicates("date", keep="last")
                df.to_parquet(cache_path, index=False)
                time.sleep(cfg.sec_sleep)
                s = pd.to_numeric(df["value"], errors="coerce")
                s.index = to_naive_datetime_index(df["date"])
                return s.sort_index()
        except Exception:
            pass  # Fallback to CSV scrape below

    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    headers = {"User-Agent": cfg.sec_user_agent}
    try:
        text = http_get(url, headers=headers, timeout=120).text
        raw = pd.read_csv(io.StringIO(text))
        if raw.shape[1] < 2:
            return pd.Series(dtype=float)
        raw.columns = [str(c).strip().lower() for c in raw.columns]
        date_col = raw.columns[0]
        value_col = raw.columns[1]
        df = pd.DataFrame(
            {
                "date": pd.to_datetime(raw[date_col], errors="coerce"),
                "value": pd.to_numeric(raw[value_col], errors="coerce"),
            }
        ).dropna(subset=["date"])
        df = df.sort_values("date").drop_duplicates("date", keep="last")
        df.to_parquet(cache_path, index=False)
        time.sleep(cfg.sec_sleep)
        s = pd.to_numeric(df["value"], errors="coerce")
        s.index = to_naive_datetime_index(df["date"])
        return s.sort_index()
    except Exception:
        if cache_path.exists():
            try:
                df = pd.read_parquet(cache_path)
                s = pd.to_numeric(df["value"], errors="coerce")
                s.index = to_naive_datetime_index(df["date"])
                return s.sort_index()
            except Exception:
                return pd.Series(dtype=float)
        return pd.Series(dtype=float)


def macro_series_to_billions(name: str, s: pd.Series) -> pd.Series:
    out = pd.to_numeric(s, errors="coerce").astype(float)
    if out.empty:
        return out
    if name in {"fed_assets", "tga"}:
        out = out / 1000.0
    return out


def load_cnn_fear_greed_table(cfg: EngineConfig, paths: dict[str, Path]) -> pd.DataFrame:
    cache_path = macro_cache_file(paths, "cnn_fear_greed")
    if is_cache_fresh(cache_path, max(int(cfg.macro_refresh_days), 1)):
        try:
            cached = pd.read_parquet(cache_path)
            if isinstance(cached, pd.DataFrame) and not cached.empty:
                cached["date"] = pd.to_datetime(cached.get("date"), errors="coerce", utc=True).dt.tz_convert(None)
                return cached.sort_values("date")
        except Exception:
            pass

    rows: list[dict[str, Any]] = []
    try:
        payload = http_get(CNN_FEAR_GREED_URL, headers=CNN_FEAR_GREED_HEADERS, timeout=60).json()
        hist = ((payload or {}).get("fear_and_greed_historical") or {}).get("data") or []
        for item in hist:
            rows.append(
                {
                    "date": pd.to_datetime(item.get("x"), unit="ms", errors="coerce"),
                    "fear_greed_score": safe_float(item.get("y")),
                }
            )
        latest = (payload or {}).get("fear_and_greed") or {}
        latest_ts = latest.get("timestamp")
        latest_score = safe_float(latest.get("score"))
        if latest_ts is not None and not np.isnan(latest_score):
            rows.append(
                {
                    "date": pd.to_datetime(latest_ts, unit="ms", errors="coerce"),
                    "fear_greed_score": latest_score,
                }
            )
    except Exception:
        rows = []

    if rows:
        df = pd.DataFrame(rows)
        df["date"] = pd.to_datetime(df["date"], errors="coerce", utc=True).dt.tz_convert(None)
        df["date"] = df["date"].dt.normalize()
        df["fear_greed_score"] = pd.to_numeric(df["fear_greed_score"], errors="coerce")
        df = df.dropna(subset=["date"]).sort_values("date").drop_duplicates("date", keep="last")
        if not df.empty:
            try:
                df.to_parquet(cache_path, index=False)
            except Exception:
                pass
            return df

    if cache_path.exists():
        try:
            cached = pd.read_parquet(cache_path)
            cached["date"] = pd.to_datetime(cached.get("date"), errors="coerce", utc=True).dt.tz_convert(None)
            return cached.sort_values("date")
        except Exception:
            pass
    return pd.DataFrame(columns=["date", "fear_greed_score"])


def benchmark_history_source_label(cfg: EngineConfig) -> str:
    source = str(cfg.benchmark_history_source or "").strip().lower()
    if source == "fred_sp500":
        return "FRED:SP500 (fallback ^GSPC)"
    if source in {"ticker", "yfinance", "yf"}:
        return f"YF:{(cfg.benchmark_ticker or '^GSPC').strip().upper()}"
    if source:
        return source
    return f"YF:{(cfg.benchmark_ticker or '^GSPC').strip().upper()}"


def load_benchmark_price_series(cfg: EngineConfig, paths: dict[str, Path]) -> pd.Series:
    source = str(cfg.benchmark_history_source or "").strip().lower()
    if source == "fred_sp500":
        s = load_fred_series(cfg, paths, "benchmark_sp500", MACRO_FRED_SERIES["sp500"])
        s = pd.to_numeric(s, errors="coerce").dropna().sort_index()
        if not s.empty:
            return s

    bench_ticker = (cfg.benchmark_ticker or "^GSPC").strip().upper()
    if is_valid_price_symbol(bench_ticker):
        ensure_prices_cached_incremental(cfg, paths, [bench_ticker])
    bench_px = load_px(paths, bench_ticker)
    if bench_px is None or bench_px.empty:
        return pd.Series(dtype=float)
    return price_close_series(bench_px).dropna().sort_index()


def return_series_to_series(close: pd.Series, start_dt: pd.Timestamp, horizon: int) -> Optional[float]:
    if close is None or close.empty:
        return None
    idx = pd.DatetimeIndex(pd.to_datetime(close.index).tz_localize(None))
    dt0 = get_date_on_or_after(idx, pd.Timestamp(start_dt))
    if dt0 is None:
        return None
    i0 = int(np.where(idx == dt0)[0][0])
    i1 = i0 + int(horizon)
    if i1 >= len(idx):
        return None
    p0 = float(close.iloc[i0])
    p1 = float(close.iloc[i1])
    if p0 == 0 or not np.isfinite(p0) or not np.isfinite(p1):
        return None
    return p1 / p0 - 1.0


def return_series_between_dates(close: pd.Series, entry_dt: pd.Timestamp, exit_dt: pd.Timestamp) -> Optional[float]:
    if close is None or close.empty:
        return None
    idx = pd.DatetimeIndex(pd.to_datetime(close.index).tz_localize(None))
    dt0 = get_date_on_or_after(idx, pd.Timestamp(entry_dt))
    dt1 = get_date_on_or_after(idx, pd.Timestamp(exit_dt))
    if dt0 is None:
        return None
    if dt1 is None:
        return -1.0
    p0 = float(close.loc[dt0]) if dt0 in close.index else np.nan
    p1 = float(close.loc[dt1]) if dt1 in close.index else np.nan
    if p0 == 0 or not np.isfinite(p0) or not np.isfinite(p1):
        return None
    return p1 / p0 - 1.0


def portfolio_forward_return_from_holdings(
    cfg: EngineConfig,
    paths: dict[str, Path],
    holdings: pd.DataFrame,
    start_dt: pd.Timestamp,
    horizon: int,
    as_of_date: Optional[pd.Timestamp] = None,
    benchmark_close: Optional[pd.Series] = None,
) -> dict[str, Optional[float]]:
    if holdings is None or holdings.empty:
        return {"portfolio_return": None, "benchmark_return": None, "coverage_weight": 0.0}
    bench = benchmark_close if benchmark_close is not None else load_benchmark_price_series(cfg, paths)
    if bench is not None and not bench.empty and pd.notna(as_of_date):
        bench = bench[pd.to_datetime(bench.index).tz_localize(None) <= pd.Timestamp(as_of_date)]
    weighted_sum = 0.0
    covered_weight = 0.0
    for row in holdings.itertuples(index=False):
        ticker = normalize_ticker(getattr(row, "ticker", None))
        weight = safe_float(getattr(row, "weight", 0.0))
        if not ticker or pd.isna(weight) or float(weight) <= 1e-10:
            continue
        if ticker == CASH_PROXY_TICKER:
            covered_weight += float(weight)
            continue
        px = load_px(paths, ticker)
        close = price_close_series(px) if px is not None and not px.empty else pd.Series(dtype=float)
        if close.empty:
            continue
        if pd.notna(as_of_date):
            close = close[pd.to_datetime(close.index).tz_localize(None) <= pd.Timestamp(as_of_date)]
        ret = return_series_to_series(close, start_dt, horizon)
        if ret is None:
            continue
        covered_weight += float(weight)
        weighted_sum += float(weight) * float(ret)
    port_ret = float(weighted_sum / covered_weight) if covered_weight > 1e-10 else None
    bench_ret = return_series_to_series(bench, start_dt, horizon) if bench is not None and not bench.empty else None
    return {
        "portfolio_return": port_ret,
        "benchmark_return": None if bench_ret is None else float(bench_ret),
        "coverage_weight": float(covered_weight),
    }


def refresh_operational_realized_history(
    cfg: EngineConfig,
    paths: dict[str, Path],
    as_of_date: Optional[pd.Timestamp] = None,
) -> pd.DataFrame:
    holdings_path = paths["ops"] / "portfolio_holdings_history.parquet"
    realized_path = paths["ops"] / "portfolio_realized_performance.parquet"
    holdings = safe_read_parquet_file(holdings_path)
    if holdings.empty or "rebalance_date" not in holdings.columns:
        return pd.DataFrame()
    d = holdings.copy()
    d["rebalance_date"] = pd.to_datetime(d["rebalance_date"], errors="coerce")
    d["weight"] = pd.to_numeric(d.get("weight"), errors="coerce").fillna(0.0)
    d = d.dropna(subset=["rebalance_date"])
    if d.empty:
        return pd.DataFrame()
    run_key_cols = [c for c in ["run_timestamp_utc", "portfolio_kind", "rebalance_date"] if c in d.columns]
    bench_close = load_benchmark_price_series(cfg, paths)
    if bench_close is not None and not bench_close.empty and pd.notna(as_of_date):
        bench_close = bench_close[pd.to_datetime(bench_close.index).tz_localize(None) <= pd.Timestamp(as_of_date)]
    horizon_map = {"1m": 21, "3m": 63, "6m": 126, "12m": 252}
    rows: list[dict[str, Any]] = []
    grouped = d.groupby(run_key_cols, dropna=False) if run_key_cols else [(("latest", "operational", d["rebalance_date"].max()), d)]
    min_coverage = float(np.clip(getattr(cfg, "ops_min_realized_coverage", 0.90), 0.0, 1.0))
    for group_key, grp in grouped:
        if grp.empty:
            continue
        if not isinstance(group_key, tuple):
            group_key = (group_key,)
        row: dict[str, Any] = {}
        for idx, col in enumerate(run_key_cols):
            row[col] = group_key[idx] if idx < len(group_key) else None
        _rebal_dates = pd.to_datetime(grp["rebalance_date"], errors="coerce").dropna()
        if _rebal_dates.empty:
            continue
        rebalance_dt = _rebal_dates.iloc[0]
        row["as_of_date"] = str(pd.Timestamp(as_of_date).date()) if pd.notna(as_of_date) else None
        stock_mask = grp.get("ticker", pd.Series(dtype=object)).astype(str).str.upper().ne(CASH_PROXY_TICKER)
        row["selected_n"] = int(stock_mask.sum())
        row["cash_weight"] = float(grp.loc[~stock_mask, "weight"].sum()) if len(grp) else 0.0
        for label, horizon in horizon_map.items():
            stats = portfolio_forward_return_from_holdings(
                cfg,
                paths,
                grp,
                rebalance_dt,
                horizon,
                as_of_date=as_of_date,
                benchmark_close=bench_close,
            )
            port_ret = stats.get("portfolio_return")
            bench_ret = stats.get("benchmark_return")
            coverage_weight = float(stats.get("coverage_weight", 0.0) or 0.0)
            coverage_ok = bool(port_ret is not None and coverage_weight >= min_coverage)
            row[f"portfolio_return_raw_{label}"] = port_ret
            row[f"benchmark_return_raw_{label}"] = bench_ret
            row[f"coverage_weight_{label}"] = coverage_weight
            row[f"coverage_ok_{label}"] = coverage_ok
            row[f"portfolio_return_{label}"] = float(port_ret) if coverage_ok and port_ret is not None else None
            row[f"benchmark_return_{label}"] = float(bench_ret) if coverage_ok and bench_ret is not None else None
            row[f"excess_return_{label}"] = (
                float(port_ret) - float(bench_ret)
                if coverage_ok and port_ret is not None and bench_ret is not None
                else None
            )
            row[f"matured_{label}"] = bool(coverage_ok)
        rows.append(row)
    realized = pd.DataFrame(rows)
    if not realized.empty:
        append_history_parquet(
            realized_path,
            realized,
            dedupe_subset=run_key_cols,
            sort_columns=[c for c in ["rebalance_date", "run_timestamp_utc", "portfolio_kind"] if c in realized.columns],
        )
        realized = safe_read_parquet_file(realized_path)
    return realized


def build_benchmark_feature_table(cfg: EngineConfig, paths: dict[str, Path]) -> pd.DataFrame:
    close = load_benchmark_price_series(cfg, paths)
    if close.empty:
        return pd.DataFrame(columns=["bench_date"] + BENCHMARK_RELATIVE_COLUMNS + ["bench_above_ma200"])
    out = pd.DataFrame(index=close.index)
    out["bench_ret_1m"] = close.pct_change(21)
    out["bench_ret_3m"] = close.pct_change(63)
    out["bench_ret_6m"] = close.pct_change(126)
    out["bench_ret_12m"] = close.pct_change(252)
    bench_ma200 = close.rolling(200).mean()
    out["bench_above_ma200"] = (close > bench_ma200).astype(float)
    bench_dd = close / close.cummax() - 1.0
    out["bench_dd_1y"] = bench_dd.rolling(252).min().abs()
    out.index.name = "bench_date"
    return out.reset_index()


def merge_benchmark_relative_features(cfg: EngineConfig, paths: dict[str, Path], monthly: pd.DataFrame) -> pd.DataFrame:
    d = monthly.copy()
    if d.empty:
        for c in BENCHMARK_RELATIVE_COLUMNS + ["bench_above_ma200"]:
            if c not in d.columns:
                d[c] = np.nan
        return d

    bench = build_benchmark_feature_table(cfg, paths)
    if bench.empty:
        for c in BENCHMARK_RELATIVE_COLUMNS + ["bench_above_ma200"]:
            if c not in d.columns:
                d[c] = np.nan
        return d

    d["rebalance_date"] = pd.to_datetime(d["rebalance_date"], errors="coerce")
    d = d.sort_values("rebalance_date")
    bench["bench_date"] = pd.to_datetime(bench["bench_date"], errors="coerce")
    bench = bench.sort_values("bench_date").drop_duplicates("bench_date", keep="last")
    merge_cols = ["bench_date"] + [c for c in BENCHMARK_RELATIVE_COLUMNS + ["bench_above_ma200"] if c in bench.columns]
    d = pd.merge_asof(
        d,
        bench[merge_cols],
        left_on="rebalance_date",
        right_on="bench_date",
        direction="backward",
    )
    d = d.drop(columns=["bench_date"], errors="ignore")
    d["rs_benchmark_1m"] = pd.to_numeric(d.get("mom_1m"), errors="coerce") - pd.to_numeric(d.get("bench_ret_1m"), errors="coerce")
    d["rs_benchmark_3m"] = pd.to_numeric(d.get("mom_3m"), errors="coerce") - pd.to_numeric(d.get("bench_ret_3m"), errors="coerce")
    d["rs_benchmark_6m"] = pd.to_numeric(d.get("mom_6m"), errors="coerce") - pd.to_numeric(d.get("bench_ret_6m"), errors="coerce")
    d["rs_benchmark_12m"] = pd.to_numeric(d.get("mom_12m"), errors="coerce") - pd.to_numeric(d.get("bench_ret_12m"), errors="coerce")
    d["dd_gap_benchmark"] = pd.to_numeric(d.get("bench_dd_1y"), errors="coerce") - pd.to_numeric(d.get("dd_1y"), errors="coerce")
    return d


def attach_benchmark_forward_returns(cfg: EngineConfig, paths: dict[str, Path], monthly: pd.DataFrame) -> pd.DataFrame:
    d = monthly.copy()
    for c in ["bench_r_1m", "bench_r_3m", "bench_r_6m", "bench_r_12m", "bench_r_24m", "bench_r_36m"]:
        if c not in d.columns:
            d[c] = np.nan
    if d.empty or "rebalance_date" not in d.columns:
        return d

    close = load_benchmark_price_series(cfg, paths)
    if close.empty:
        return d

    rows = []
    unique_dates = pd.to_datetime(d["rebalance_date"], errors="coerce").dropna().drop_duplicates().sort_values()
    for dt in unique_dates:
        start_dt = pd.Timestamp(dt) + pd.Timedelta(days=1)
        rows.append(
            {
                "rebalance_date": pd.Timestamp(dt),
                "bench_r_1m": return_series_to_series(close, start_dt, cfg.target_1m_days),
                "bench_r_3m": return_series_to_series(close, start_dt, cfg.target_3m_days),
                "bench_r_6m": return_series_to_series(close, start_dt, cfg.target_6m_days),
                "bench_r_12m": return_series_to_series(close, start_dt, cfg.target_12m_days),
                "bench_r_24m": return_series_to_series(close, start_dt, cfg.target_24m_days),
                "bench_r_36m": return_series_to_series(close, start_dt, cfg.target_36m_days),
            }
        )
    if not rows:
        return d
    bench_forward = pd.DataFrame(rows)
    d["rebalance_date"] = pd.to_datetime(d["rebalance_date"], errors="coerce")
    return d.merge(bench_forward, on="rebalance_date", how="left")

# Stage 3d-ii-min (2026-04-20): compute_event_regime_features moved to r1000_features.py.




def build_live_event_alert_table(cfg: EngineConfig, paths: dict[str, Path]) -> pd.DataFrame:
    alert_path = paths["feature_store"] / "live_event_alert_latest.parquet"
    if alert_path.exists() and is_cache_fresh(alert_path, max(int(cfg.macro_refresh_days), 1)):
        try:
            cached = pd.read_parquet(alert_path)
            if isinstance(cached, pd.DataFrame) and not cached.empty:
                cached["event_date"] = pd.to_datetime(cached.get("event_date"), errors="coerce")
                return cached.sort_values("event_date")
        except Exception:
            pass

    ensure_prices_cached_incremental(cfg, paths, ["QQQ", "USO", "GLD"])
    frames: list[pd.DataFrame] = []

    benchmark_close = load_benchmark_price_series(cfg, paths)
    if not benchmark_close.empty:
        bench = pd.DataFrame(index=benchmark_close.index)
        bench["bench_close"] = benchmark_close
        bench["bench_ret_5d"] = benchmark_close.pct_change(5)
        bench["bench_ret_20d"] = benchmark_close.pct_change(20)
        bench_ma50 = benchmark_close.rolling(50).mean()
        bench_ma200 = benchmark_close.rolling(200).mean()
        bench["bench_above_ma50"] = (benchmark_close > bench_ma50).astype(float)
        bench["bench_above_ma200"] = (benchmark_close > bench_ma200).astype(float)
        frames.append(bench)

    qqq_px = load_px(paths, "QQQ")
    if qqq_px is not None and not qqq_px.empty:
        qqq_close = price_close_series(qqq_px)
        qqq = pd.DataFrame(index=qqq_close.index)
        qqq["qqq_ret_5d"] = qqq_close.pct_change(5)
        qqq["qqq_ret_20d"] = qqq_close.pct_change(20)
        frames.append(qqq)

    uso_px = load_px(paths, "USO")
    if uso_px is not None and not uso_px.empty:
        uso_close = price_close_series(uso_px)
        uso = pd.DataFrame(index=uso_close.index)
        uso["uso_ret_5d_live"] = uso_close.pct_change(5)
        uso["uso_ret_20d_live"] = uso_close.pct_change(20)
        frames.append(uso)

    gld_px = load_px(paths, "GLD")
    if gld_px is not None and not gld_px.empty:
        gld_close = price_close_series(gld_px)
        gld = pd.DataFrame(index=gld_close.index)
        gld["gld_ret_5d_live"] = gld_close.pct_change(5)
        frames.append(gld)

    vix = load_fred_series(cfg, paths, "vix", MACRO_FRED_SERIES["vix"])
    if not vix.empty:
        vix_df = pd.DataFrame(index=vix.index)
        vix_df["vix_level_live"] = vix
        vix_df["vix_change_5d_live"] = vix.diff(5)
        frames.append(vix_df)

    dgs10 = load_fred_series(cfg, paths, "dgs10", MACRO_FRED_SERIES["dgs10"])
    if not dgs10.empty:
        dgs_df = pd.DataFrame(index=dgs10.index)
        dgs_df["dgs10_change_5d_live"] = dgs10.diff(5)
        frames.append(dgs_df)

    hy_oas = load_fred_series(cfg, paths, "hy_oas", MACRO_FRED_SERIES["hy_oas"])
    if not hy_oas.empty:
        hy_df = pd.DataFrame(index=hy_oas.index)
        hy_df["hy_oas_level_live"] = hy_oas
        hy_df["hy_oas_change_5d_live"] = hy_oas.diff(5)
        frames.append(hy_df)

    dxy = load_fred_series(cfg, paths, "dxy", MACRO_FRED_SERIES["dxy"])
    if not dxy.empty:
        dxy_df = pd.DataFrame(index=dxy.index)
        dxy_df["dxy_ret_5d_live"] = dxy.pct_change(5)
        frames.append(dxy_df)

    if not frames:
        return pd.DataFrame(columns=["event_date"] + LIVE_EVENT_ALERT_COLUMNS + ["live_event_alert_label"])

    alert = pd.concat(frames, axis=1).sort_index()
    alert.index = pd.to_datetime(alert.index).tz_localize(None)
    alert = alert[~alert.index.duplicated(keep="last")].ffill()

    if {"qqq_ret_5d", "bench_ret_5d"}.issubset(alert.columns):
        alert["qqq_rel_bench_5d"] = alert["qqq_ret_5d"] - alert["bench_ret_5d"]
    else:
        alert["qqq_rel_bench_5d"] = np.nan

    def alert_series(col: str, default: float = np.nan) -> pd.Series:
        return numeric_series_or_default(alert, col, default).reindex(alert.index)

    def pos_live(col: str, window: int = 63, scale: float = 2.0) -> pd.Series:
        base = alert_series(col, np.nan)
        return (rolling_robust_z(base, window=window).fillna(0.0) / scale).clip(lower=0.0, upper=1.0)

    def neg_live(col: str, window: int = 63, scale: float = 2.0) -> pd.Series:
        base = alert_series(col, np.nan)
        return (-rolling_robust_z(base, window=window).fillna(0.0) / scale).clip(lower=0.0, upper=1.0)

    live_risk = row_mean(
        [
            pos_live("vix_level_live", window=63, scale=1.6),
            pos_live("vix_change_5d_live", window=63, scale=1.6),
            pos_live("hy_oas_level_live", window=63, scale=1.5),
            pos_live("hy_oas_change_5d_live", window=63, scale=1.5),
            neg_live("bench_ret_5d", window=63, scale=1.7),
            pos_live("dxy_ret_5d_live", window=63, scale=1.8),
        ],
        alert.index,
    ).fillna(0.0).clip(lower=0.0, upper=1.0)

    live_systemic = row_mean(
        [
            pos_live("vix_level_live", window=63, scale=1.5),
            pos_live("hy_oas_level_live", window=63, scale=1.4),
            pos_live("hy_oas_change_5d_live", window=63, scale=1.4),
            neg_live("bench_ret_20d", window=63, scale=1.7),
            neg_live("qqq_rel_bench_5d", window=63, scale=1.8),
            pos_live("dxy_ret_5d_live", window=63, scale=1.9),
        ],
        alert.index,
    ).fillna(0.0).clip(lower=0.0, upper=1.0)

    live_war = row_mean(
        [
            pos_live("uso_ret_5d_live", window=63, scale=1.6),
            pos_live("dgs10_change_5d_live", window=63, scale=1.7),
            pos_live("hy_oas_change_5d_live", window=63, scale=1.6),
            pos_live("dxy_ret_5d_live", window=63, scale=1.9),
            neg_live("qqq_rel_bench_5d", window=63, scale=1.9),
        ],
        alert.index,
    ).fillna(0.0).clip(lower=0.0, upper=1.0)

    live_defensive = (
        0.45 * live_systemic
        + 0.35 * live_war
        + 0.20 * pos_live("gld_ret_5d_live", window=63, scale=1.9)
    ).clip(lower=0.0, upper=1.0)

    live_growth = row_mean(
        [
            alert_series("bench_above_ma50", 0.0),
            alert_series("bench_above_ma200", 0.0),
            pos_live("bench_ret_20d", window=63, scale=1.8),
            pos_live("qqq_rel_bench_5d", window=63, scale=1.8),
            neg_live("hy_oas_change_5d_live", window=63, scale=1.8),
            neg_live("vix_level_live", window=63, scale=1.8),
            neg_live("uso_ret_5d_live", window=63, scale=2.2),
        ],
        alert.index,
    ).fillna(0.0).clip(lower=0.0, upper=1.0)

    labels = np.full(len(alert), "balanced", dtype=object)
    labels = np.where(
        (live_systemic >= live_defensive) & (live_systemic >= live_growth) & (live_systemic >= cfg.live_event_risk_threshold),
        "systemic_alert",
        labels,
    )
    labels = np.where(
        (live_war >= 0.48) & (live_defensive >= cfg.live_event_risk_threshold),
        "war_oil_rate_alert",
        labels,
    )
    labels = np.where(
        (live_risk >= cfg.live_event_risk_threshold) & (live_defensive >= live_growth),
        "risk_off_alert",
        labels,
    )
    labels = np.where(
        (live_growth >= cfg.live_event_growth_threshold) & (live_risk < cfg.live_event_risk_threshold),
        "growth_reentry_alert",
        labels,
    )

    alert_out = pd.DataFrame(
        {
            "event_date": pd.to_datetime(alert.index),
            "live_event_risk_score": live_risk,
            "live_event_systemic_score": live_systemic,
            "live_event_war_oil_rate_score": live_war,
            "live_event_defensive_score": live_defensive,
            "live_event_growth_reentry_score": live_growth,
            "live_event_alert_label": pd.Series(labels, index=alert.index, dtype=object),
        }
    ).sort_values("event_date")
    alert_out.to_parquet(alert_path, index=False)
    return alert_out


def merge_live_event_alert_features(cfg: EngineConfig, paths: dict[str, Path], monthly: pd.DataFrame) -> pd.DataFrame:
    d = monthly.copy()
    if d.empty:
        for c in LIVE_EVENT_ALERT_COLUMNS:
            if c not in d.columns:
                d[c] = np.nan
        if "live_event_alert_label" not in d.columns:
            d["live_event_alert_label"] = ""
        return d

    alert = build_live_event_alert_table(cfg, paths)
    if alert.empty:
        for c in LIVE_EVENT_ALERT_COLUMNS:
            if c not in d.columns:
                d[c] = np.nan
        if "live_event_alert_label" not in d.columns:
            d["live_event_alert_label"] = ""
        return d

    d["rebalance_date"] = pd.to_datetime(d["rebalance_date"], errors="coerce")
    d = d.sort_values("rebalance_date")
    alert["event_date"] = pd.to_datetime(alert["event_date"], errors="coerce")
    alert = alert.sort_values("event_date").drop_duplicates("event_date", keep="last")
    merge_cols = ["event_date"] + LIVE_EVENT_ALERT_COLUMNS + ["live_event_alert_label"]
    d = pd.merge_asof(
        d,
        alert[merge_cols],
        left_on="rebalance_date",
        right_on="event_date",
        direction="backward",
    )
    d = d.drop(columns=["event_date"], errors="ignore")
    return d


def write_live_event_alert_report(cfg: EngineConfig, paths: dict[str, Path]) -> Path:
    path = paths["reports"] / "event_alert_latest.json"
    alert = build_live_event_alert_table(cfg, paths)
    if alert.empty:
        path.write_text(json.dumps({"empty": True}, indent=2), encoding="utf-8")
        return path
    latest = alert.sort_values("event_date").iloc[-1]
    payload = {
        "event_date": str(pd.Timestamp(latest["event_date"]).date()) if pd.notna(latest["event_date"]) else None,
        "benchmark_history_source": benchmark_history_source_label(cfg),
        "live_event_alert_label": str(latest.get("live_event_alert_label", "")),
        "live_event_risk_score": safe_float(latest.get("live_event_risk_score")),
        "live_event_systemic_score": safe_float(latest.get("live_event_systemic_score")),
        "live_event_war_oil_rate_score": safe_float(latest.get("live_event_war_oil_rate_score")),
        "live_event_defensive_score": safe_float(latest.get("live_event_defensive_score")),
        "live_event_growth_reentry_score": safe_float(latest.get("live_event_growth_reentry_score")),
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def compute_macro_price_block(hist: pd.DataFrame, prefix: str) -> pd.DataFrame:
    close = price_close_series(hist)
    if close.empty:
        return pd.DataFrame()
    out = pd.DataFrame(index=close.index)
    out[f"{prefix}_ret_1m"] = close.pct_change(21)
    out[f"{prefix}_ret_3m"] = close.pct_change(63)
    ma200 = close.rolling(200).mean()
    out[f"{prefix}_above_ma200"] = (close > ma200).astype(float)
    return out


def build_macro_regime_table(cfg: EngineConfig, paths: dict[str, Path]) -> pd.DataFrame:
    macro_path = paths["feature_store"] / "macro_regime_latest.parquet"
    if not cfg.use_macro_regime_features:
        empty = pd.DataFrame(columns=["macro_date"] + MACRO_REGIME_COLUMNS)
        empty.to_parquet(macro_path, index=False)
        return empty

    ensure_prices_cached_incremental(cfg, paths, list(MACRO_PRICE_TICKERS.values()))
    frames: list[pd.DataFrame] = []

    for name, ticker in MACRO_PRICE_TICKERS.items():
        hist = load_px(paths, ticker)
        block = compute_macro_price_block(hist, name)
        if not block.empty:
            frames.append(block)

    vix = load_fred_series(cfg, paths, "vix", MACRO_FRED_SERIES["vix"])
    if not vix.empty:
        vix_df = pd.DataFrame(index=vix.index)
        vix_df["vix_level"] = vix
        vix_df["vix_z_63d"] = rolling_robust_z(vix, 63)
        vix_df["vix_change_1m"] = vix.diff(21)
        frames.append(vix_df)

    dgs10 = load_fred_series(cfg, paths, "dgs10", MACRO_FRED_SERIES["dgs10"])
    if not dgs10.empty:
        dgs_df = pd.DataFrame(index=dgs10.index)
        dgs_df["dgs10_level"] = dgs10
        dgs_df["dgs10_change_1m"] = dgs10.diff(21)
        frames.append(dgs_df)

    hy_oas = load_fred_series(cfg, paths, "hy_oas", MACRO_FRED_SERIES["hy_oas"])
    if not hy_oas.empty:
        hy_df = pd.DataFrame(index=hy_oas.index)
        hy_df["hy_oas_level"] = hy_oas
        hy_df["hy_oas_change_1m"] = hy_oas.diff(21)
        frames.append(hy_df)

    dxy = load_fred_series(cfg, paths, "dxy", MACRO_FRED_SERIES["dxy"])
    if not dxy.empty:
        dxy_df = pd.DataFrame(index=dxy.index)
        dxy_df["dxy_level"] = dxy
        dxy_df["dxy_ret_1m"] = dxy.pct_change(21)
        frames.append(dxy_df)

    m2 = load_fred_series(cfg, paths, "m2", MACRO_FRED_SERIES["m2"])
    if not m2.empty:
        m2 = m2.sort_index().resample("MS").last().ffill(limit=3)
        if cfg.macro_m2_release_lag_months > 0:
            m2 = m2.shift(int(cfg.macro_m2_release_lag_months))
        m2_df = pd.DataFrame(index=m2.index)
        m2_df["m2_yoy_lag1m"] = m2.pct_change(12)
        frames.append(m2_df)

    fed_assets = load_fred_series(cfg, paths, "fed_assets", MACRO_FRED_SERIES["fed_assets"])
    reverse_repo = load_fred_series(cfg, paths, "reverse_repo", MACRO_FRED_SERIES["reverse_repo"])
    tga = load_fred_series(cfg, paths, "tga", MACRO_FRED_SERIES["tga"])
    if (not fed_assets.empty) or (not reverse_repo.empty) or (not tga.empty):
        liq_df = pd.DataFrame(index=pd.Index([], dtype="datetime64[ns]"))
        if not fed_assets.empty:
            liq_df = liq_df.reindex(liq_df.index.union(fed_assets.index))
            liq_df["fed_assets_bil"] = macro_series_to_billions("fed_assets", fed_assets).reindex(liq_df.index)
        if not reverse_repo.empty:
            liq_df = liq_df.reindex(liq_df.index.union(reverse_repo.index))
            liq_df["reverse_repo_bil"] = macro_series_to_billions("reverse_repo", reverse_repo).reindex(liq_df.index)
        if not tga.empty:
            liq_df = liq_df.reindex(liq_df.index.union(tga.index))
            liq_df["tga_bil"] = macro_series_to_billions("tga", tga).reindex(liq_df.index)
        if not liq_df.empty:
            liq_df = liq_df.sort_index()
            liq_df["net_liquidity_bil"] = (
                pd.to_numeric(liq_df.get("fed_assets_bil"), errors="coerce")
                - pd.to_numeric(liq_df.get("reverse_repo_bil"), errors="coerce").fillna(0.0)
                - pd.to_numeric(liq_df.get("tga_bil"), errors="coerce").fillna(0.0)
            )
            frames.append(liq_df)

    cpi = load_fred_series(cfg, paths, "cpi", MACRO_FRED_SERIES["cpi"])
    if not cpi.empty:
        cpi = cpi.sort_index().resample("MS").last().ffill(limit=3)
        if cfg.macro_slow_release_lag_months > 0:
            cpi = cpi.shift(int(cfg.macro_slow_release_lag_months))
        cpi_df = pd.DataFrame(index=cpi.index)
        cpi_df["cpi_yoy"] = cpi.pct_change(12)
        cpi_df["cpi_3m_ann"] = np.power((cpi / cpi.shift(3)).replace(0, np.nan), 4) - 1.0
        frames.append(cpi_df)

    core_cpi = load_fred_series(cfg, paths, "core_cpi", MACRO_FRED_SERIES["core_cpi"])
    if not core_cpi.empty:
        core_cpi = core_cpi.sort_index().resample("MS").last().ffill(limit=3)
        if cfg.macro_slow_release_lag_months > 0:
            core_cpi = core_cpi.shift(int(cfg.macro_slow_release_lag_months))
        core_cpi_df = pd.DataFrame(index=core_cpi.index)
        core_cpi_df["core_cpi_yoy"] = core_cpi.pct_change(12)
        frames.append(core_cpi_df)

    ppi = load_fred_series(cfg, paths, "ppi", MACRO_FRED_SERIES["ppi"])
    if not ppi.empty:
        ppi = ppi.sort_index().resample("MS").last().ffill(limit=3)
        if cfg.macro_slow_release_lag_months > 0:
            ppi = ppi.shift(int(cfg.macro_slow_release_lag_months))
        ppi_df = pd.DataFrame(index=ppi.index)
        ppi_df["ppi_yoy"] = ppi.pct_change(12)
        frames.append(ppi_df)

    unrate = load_fred_series(cfg, paths, "unrate", MACRO_FRED_SERIES["unrate"])
    if not unrate.empty:
        unrate = unrate.sort_index().resample("MS").last()
        if cfg.macro_slow_release_lag_months > 0:
            unrate = unrate.shift(int(cfg.macro_slow_release_lag_months))
        unrate_df = pd.DataFrame(index=unrate.index)
        unrate_df["unrate_level"] = unrate
        unrate_df["unrate_3m_change"] = unrate.diff(3)
        frames.append(unrate_df)

    sahm = load_fred_series(cfg, paths, "sahm", MACRO_FRED_SERIES["sahm"])
    if not sahm.empty:
        sahm = sahm.sort_index().resample("MS").last()
        if cfg.macro_slow_release_lag_months > 0:
            sahm = sahm.shift(int(cfg.macro_slow_release_lag_months))
        sahm_df = pd.DataFrame(index=sahm.index)
        sahm_df["sahm_realtime"] = sahm
        frames.append(sahm_df)

    fear_greed = load_cnn_fear_greed_table(cfg, paths)
    if not fear_greed.empty:
        fg = fear_greed.copy()
        fg["date"] = pd.to_datetime(fg["date"], errors="coerce")
        fg = fg.dropna(subset=["date"]).sort_values("date").set_index("date")
        fg_df = pd.DataFrame(index=fg.index)
        fg_df["fear_greed_score"] = pd.to_numeric(fg.get("fear_greed_score"), errors="coerce")
        frames.append(fg_df)

    if not frames:
        empty = pd.DataFrame(columns=["macro_date"] + MACRO_REGIME_COLUMNS)
        empty.to_parquet(macro_path, index=False)
        return empty

    macro = pd.concat(frames, axis=1).sort_index()
    macro.index = pd.to_datetime(macro.index).tz_localize(None)
    macro = macro[~macro.index.duplicated(keep="last")]
    # Daily market rows coexist with weekly/monthly macro releases. Carry the
    # latest published values forward so merge_asof lands on the newest macro
    # snapshot instead of a recent trading day full of NaNs.
    carry_forward_cols = [
        "m2_yoy_lag1m",
        "cpi_yoy",
        "core_cpi_yoy",
        "cpi_3m_ann",
        "ppi_yoy",
        "unrate_level",
        "unrate_3m_change",
        "sahm_realtime",
        "fed_assets_bil",
        "reverse_repo_bil",
        "tga_bil",
        "net_liquidity_bil",
        "fear_greed_score",
    ]
    present_carry_forward_cols = [c for c in carry_forward_cols if c in macro.columns]
    if present_carry_forward_cols:
        macro[present_carry_forward_cols] = macro[present_carry_forward_cols].ffill(limit=90)

    # VIX-based Fear&Greed proxy for historical periods without CNN data
    _vix_raw = pd.to_numeric(macro.get("vix_level"), errors="coerce") if "vix_level" in macro.columns else None
    if _vix_raw is not None:
        _vix_chg = pd.to_numeric(macro.get("vix_change_1m"), errors="coerce").fillna(0)
        _spy_1m = pd.to_numeric(macro.get("spy_ret_1m"), errors="coerce").fillna(0)
        _fg_proxy = (
            0.50 * (100 - 2.5 * (_vix_raw - 10)).clip(0, 100)
            + 0.25 * (50 - 5 * _vix_chg).clip(0, 100)
            + 0.25 * (50 + 200 * _spy_1m).clip(0, 100)
        ).clip(0, 100)
        if "fear_greed_score" in macro.columns:
            _fg_nan = macro["fear_greed_score"].isna()
            if _fg_nan.any():
                macro.loc[_fg_nan, "fear_greed_score"] = _fg_proxy.loc[_fg_nan]
        else:
            macro["fear_greed_score"] = _fg_proxy

    if "fear_greed_score" in macro.columns:
        macro["fear_greed_delta_1w"] = pd.to_numeric(macro["fear_greed_score"], errors="coerce").diff(5)
    else:
        macro["fear_greed_delta_1w"] = np.nan
    if "fed_assets_bil" in macro.columns:
        macro["fed_assets_change_1m_bil"] = pd.to_numeric(macro["fed_assets_bil"], errors="coerce").diff(21)
    else:
        macro["fed_assets_change_1m_bil"] = np.nan
    if "reverse_repo_bil" in macro.columns:
        macro["reverse_repo_change_1m_bil"] = pd.to_numeric(macro["reverse_repo_bil"], errors="coerce").diff(21)
    else:
        macro["reverse_repo_change_1m_bil"] = np.nan
    if "tga_bil" in macro.columns:
        macro["tga_change_1m_bil"] = pd.to_numeric(macro["tga_bil"], errors="coerce").diff(21)
    else:
        macro["tga_change_1m_bil"] = np.nan
    if "net_liquidity_bil" in macro.columns:
        macro["net_liquidity_change_1m_bil"] = pd.to_numeric(macro["net_liquidity_bil"], errors="coerce").diff(21)
    else:
        macro["net_liquidity_change_1m_bil"] = np.nan

    if {"qqq_ret_1m", "spy_ret_1m"}.issubset(macro.columns):
        macro["qqq_rel_spy_1m"] = macro["qqq_ret_1m"] - macro["spy_ret_1m"]
    else:
        macro["qqq_rel_spy_1m"] = np.nan
    if {"smh_ret_1m", "spy_ret_1m"}.issubset(macro.columns):
        macro["smh_rel_spy_1m"] = macro["smh_ret_1m"] - macro["spy_ret_1m"]
    else:
        macro["smh_rel_spy_1m"] = np.nan

    spy_1m_z = rolling_robust_z(macro["spy_ret_1m"], 126) if "spy_ret_1m" in macro.columns else pd.Series(np.nan, index=macro.index)
    spy_3m_z = rolling_robust_z(macro["spy_ret_3m"], 126) if "spy_ret_3m" in macro.columns else pd.Series(np.nan, index=macro.index)
    qqq_rel_z = rolling_robust_z(macro["qqq_rel_spy_1m"], 126) if "qqq_rel_spy_1m" in macro.columns else pd.Series(np.nan, index=macro.index)
    smh_rel_z = rolling_robust_z(macro["smh_rel_spy_1m"], 126) if "smh_rel_spy_1m" in macro.columns else pd.Series(np.nan, index=macro.index)
    dxy_1m_z = rolling_robust_z(macro["dxy_ret_1m"], 126) if "dxy_ret_1m" in macro.columns else pd.Series(np.nan, index=macro.index)
    dgs10_1m_z = rolling_robust_z(macro["dgs10_change_1m"], 126) if "dgs10_change_1m" in macro.columns else pd.Series(np.nan, index=macro.index)
    hy_oas_z = rolling_robust_z(macro["hy_oas_level"], 126) if "hy_oas_level" in macro.columns else pd.Series(np.nan, index=macro.index)
    hy_oas_change_z = rolling_robust_z(macro["hy_oas_change_1m"], 126) if "hy_oas_change_1m" in macro.columns else pd.Series(np.nan, index=macro.index)
    uso_1m_z = rolling_robust_z(macro["uso_ret_1m"], 126) if "uso_ret_1m" in macro.columns else pd.Series(np.nan, index=macro.index)
    ung_1m_z = rolling_robust_z(macro["ung_ret_1m"], 126) if "ung_ret_1m" in macro.columns else pd.Series(np.nan, index=macro.index)
    cper_1m_z = rolling_robust_z(macro["cper_ret_1m"], 126) if "cper_ret_1m" in macro.columns else pd.Series(np.nan, index=macro.index)
    dba_1m_z = rolling_robust_z(macro["dba_ret_1m"], 126) if "dba_ret_1m" in macro.columns else pd.Series(np.nan, index=macro.index)
    m2_yoy_z = robust_z(pd.to_numeric(macro["m2_yoy_lag1m"], errors="coerce")).reindex(macro.index) if "m2_yoy_lag1m" in macro.columns else pd.Series(np.nan, index=macro.index)
    vix_z = macro["vix_z_63d"] if "vix_z_63d" in macro.columns else pd.Series(np.nan, index=macro.index)
    vix_change_z = rolling_robust_z(macro["vix_change_1m"], 63) if "vix_change_1m" in macro.columns else pd.Series(np.nan, index=macro.index)
    spy_above = pd.to_numeric(macro["spy_above_ma200"], errors="coerce") if "spy_above_ma200" in macro.columns else pd.Series(np.nan, index=macro.index)
    macro["ppi_cpi_gap"] = pd.to_numeric(macro.get("ppi_yoy"), errors="coerce") - pd.to_numeric(macro.get("cpi_yoy"), errors="coerce")
    cpi_yoy_z = rolling_robust_z(macro["cpi_yoy"], 60) if "cpi_yoy" in macro.columns else pd.Series(np.nan, index=macro.index)
    core_cpi_yoy_z = rolling_robust_z(macro["core_cpi_yoy"], 60) if "core_cpi_yoy" in macro.columns else pd.Series(np.nan, index=macro.index)
    cpi_3m_ann_z = rolling_robust_z(macro["cpi_3m_ann"], 60) if "cpi_3m_ann" in macro.columns else pd.Series(np.nan, index=macro.index)
    ppi_yoy_z = rolling_robust_z(macro["ppi_yoy"], 60) if "ppi_yoy" in macro.columns else pd.Series(np.nan, index=macro.index)
    ppi_gap_z = rolling_robust_z(macro["ppi_cpi_gap"], 60) if "ppi_cpi_gap" in macro.columns else pd.Series(np.nan, index=macro.index)
    unrate_level_z = rolling_robust_z(macro["unrate_level"], 60) if "unrate_level" in macro.columns else pd.Series(np.nan, index=macro.index)
    unrate_change_z = rolling_robust_z(macro["unrate_3m_change"], 60) if "unrate_3m_change" in macro.columns else pd.Series(np.nan, index=macro.index)
    fed_assets_change_z = rolling_robust_z(macro["fed_assets_change_1m_bil"], 126) if "fed_assets_change_1m_bil" in macro.columns else pd.Series(np.nan, index=macro.index)
    reverse_repo_change_z = rolling_robust_z(macro["reverse_repo_change_1m_bil"], 126) if "reverse_repo_change_1m_bil" in macro.columns else pd.Series(np.nan, index=macro.index)
    tga_change_z = rolling_robust_z(macro["tga_change_1m_bil"], 126) if "tga_change_1m_bil" in macro.columns else pd.Series(np.nan, index=macro.index)
    net_liquidity_change_z = rolling_robust_z(macro["net_liquidity_change_1m_bil"], 126) if "net_liquidity_change_1m_bil" in macro.columns else pd.Series(np.nan, index=macro.index)
    fear_greed_delta_z = rolling_robust_z(macro["fear_greed_delta_1w"], 126) if "fear_greed_delta_1w" in macro.columns else pd.Series(np.nan, index=macro.index)
    sahm_scaled = (
        ((pd.to_numeric(macro["sahm_realtime"], errors="coerce") - 0.25) / 0.35).clip(lower=0.0, upper=1.0)
        if "sahm_realtime" in macro.columns
        else pd.Series(np.nan, index=macro.index)
    )
    macro["liquidity_impulse_score"] = row_mean(
        [
            (net_liquidity_change_z / 2.0).clip(lower=0.0, upper=1.0),
            (-reverse_repo_change_z / 2.0).clip(lower=0.0, upper=1.0),
            (-tga_change_z / 2.0).clip(lower=0.0, upper=1.0),
            (fed_assets_change_z / 2.0).clip(lower=0.0, upper=1.0),
            (m2_yoy_z / 2.0).clip(lower=0.0, upper=1.0),
        ],
        macro.index,
    ).clip(lower=0.0, upper=1.0)
    macro["liquidity_drain_score"] = row_mean(
        [
            (-net_liquidity_change_z / 2.0).clip(lower=0.0, upper=1.0),
            (reverse_repo_change_z / 2.0).clip(lower=0.0, upper=1.0),
            (tga_change_z / 2.0).clip(lower=0.0, upper=1.0),
            (-fed_assets_change_z / 2.0).clip(lower=0.0, upper=1.0),
            (-m2_yoy_z / 2.0).clip(lower=0.0, upper=1.0),
        ],
        macro.index,
    ).clip(lower=0.0, upper=1.0)
    fg_score_raw = (
        pd.to_numeric(macro["fear_greed_score"], errors="coerce")
        if "fear_greed_score" in macro.columns
        else pd.Series(np.nan, index=macro.index)
    )
    macro["fear_greed_risk_off_score"] = row_mean(
        [
            ((50.0 - fg_score_raw) / 25.0).clip(lower=0.0, upper=1.0),
            (-fear_greed_delta_z / 2.0).clip(lower=0.0, upper=1.0),
        ],
        macro.index,
    ).clip(lower=0.0, upper=1.0)
    macro["fear_greed_risk_on_score"] = row_mean(
        [
            ((fg_score_raw - 55.0) / 25.0).clip(lower=0.0, upper=1.0),
            (fear_greed_delta_z / 2.0).clip(lower=0.0, upper=1.0),
        ],
        macro.index,
    ).clip(lower=0.0, upper=1.0)

    macro["macro_risk_off_score"] = row_mean(
        [
            vix_z,
            vix_change_z,
            hy_oas_z,
            hy_oas_change_z,
            -spy_1m_z,
            -qqq_rel_z,
            dxy_1m_z,
            0.85 * pd.to_numeric(macro["liquidity_drain_score"], errors="coerce"),
        ],
        macro.index,
    )
    macro["market_regime_score"] = row_mean(
        [
            spy_3m_z,
            qqq_rel_z,
            spy_above,
            -hy_oas_change_z,
            -vix_z,
            -dxy_1m_z,
            0.65 * pd.to_numeric(macro["liquidity_impulse_score"], errors="coerce"),
        ],
        macro.index,
    )
    macro["inflation_pressure_score"] = row_mean(
        [
            uso_1m_z,
            ung_1m_z,
            cper_1m_z,
            0.35 * dba_1m_z,
            dgs10_1m_z,
        ],
        macro.index,
    )
    macro["liquidity_regime_score"] = row_mean(
        [
            0.45 * m2_yoy_z,
            0.90 * net_liquidity_change_z,
            -0.70 * reverse_repo_change_z,
            -0.60 * tga_change_z,
            0.50 * fed_assets_change_z,
            -dxy_1m_z,
            -dgs10_1m_z,
            -hy_oas_change_z,
            spy_3m_z,
        ],
        macro.index,
    )
    macro["inflation_reacceleration_score"] = row_mean(
        [
            cpi_yoy_z,
            core_cpi_yoy_z,
            cpi_3m_ann_z,
            0.50 * dgs10_1m_z,
        ],
        macro.index,
    )
    macro["upstream_cost_pressure_score"] = row_mean(
        [
            ppi_yoy_z,
            ppi_gap_z,
            0.60 * uso_1m_z,
            0.40 * cper_1m_z,
            0.30 * dba_1m_z,
        ],
        macro.index,
    )
    macro["labor_softening_score"] = row_mean(
        [
            unrate_level_z,
            unrate_change_z,
            sahm_scaled,
            0.35 * hy_oas_change_z,
        ],
        macro.index,
    )
    macro["stagflation_score"] = row_mean(
        [
            macro["inflation_reacceleration_score"],
            macro["upstream_cost_pressure_score"],
            0.70 * macro["labor_softening_score"],
            0.60 * macro["inflation_pressure_score"],
        ],
        macro.index,
    )
    macro["growth_liquidity_reentry_score"] = row_mean(
        [
            macro["liquidity_regime_score"],
            macro["market_regime_score"],
            0.85 * pd.to_numeric(macro["liquidity_impulse_score"], errors="coerce"),
            -0.55 * pd.to_numeric(macro["liquidity_drain_score"], errors="coerce"),
            qqq_rel_z,
            0.45 * smh_rel_z,
            -0.80 * macro["inflation_reacceleration_score"],
            -0.70 * macro["upstream_cost_pressure_score"],
            -0.65 * macro["labor_softening_score"],
        ],
        macro.index,
    )

    for c in MACRO_REGIME_COLUMNS:
        if c not in macro.columns:
            macro[c] = np.nan

    # Phase 8a.5 (2026-04-17): belt-and-suspenders clamp on every macro
    # regime score. These columns are either `.clip(0, 1)` probability-style
    # or row_mean of z-scores that should live in roughly [-3, +3].
    # Clamp to [-6, 6] to catch any residual blow-up from rolling_robust_z
    # (which is now z-clipped but could still compose into large magnitudes
    # via row_mean of many terms).  This is cheap (vectorised) and
    # eliminates the class of bug that produced `labor_softening_score =
    # -2e14` on 2024-06-01.
    _MACRO_CLAMP_MIN, _MACRO_CLAMP_MAX = -6.0, 6.0
    for _macro_col in MACRO_REGIME_COLUMNS:
        if _macro_col in macro.columns:
            macro[_macro_col] = (
                pd.to_numeric(macro[_macro_col], errors="coerce")
                .replace([np.inf, -np.inf], np.nan)
                .clip(lower=_MACRO_CLAMP_MIN, upper=_MACRO_CLAMP_MAX)
            )

    macro.index.name = "macro_date"
    macro = macro.reset_index()
    first_col = str(macro.columns[0])
    if first_col != "macro_date":
        macro = macro.rename(columns={first_col: "macro_date", "index": "macro_date", "date": "macro_date", "Date": "macro_date"})
    if "macro_date" not in macro.columns:
        macro.insert(0, "macro_date", pd.to_datetime(macro.index, errors="coerce"))
    macro["macro_date"] = pd.to_datetime(macro["macro_date"], errors="coerce")
    macro.to_parquet(macro_path, index=False)
    write_stage_coverage_report(paths, "macro_regime", macro, MACRO_REGIME_COLUMNS)
    return macro


def merge_macro_regime_features(cfg: EngineConfig, paths: dict[str, Path], monthly: pd.DataFrame) -> pd.DataFrame:
    d = monthly.copy()
    if d.empty:
        for c in MACRO_REGIME_COLUMNS:
            if c not in d.columns:
                d[c] = np.nan
        return d

    macro = build_macro_regime_table(cfg, paths)
    if macro.empty:
        for c in MACRO_REGIME_COLUMNS:
            if c not in d.columns:
                d[c] = np.nan
        return d

    if "macro_date" not in macro.columns:
        if "date" in macro.columns:
            macro = macro.rename(columns={"date": "macro_date"})
        else:
            macro = macro.reset_index().rename(columns={"index": "macro_date", "date": "macro_date"})

    macro = macro.sort_values("macro_date").drop_duplicates("macro_date", keep="last")
    d["rebalance_date"] = pd.to_datetime(d["rebalance_date"], errors="coerce")
    d = d.sort_values("rebalance_date")
    d = pd.merge_asof(
        d,
        macro[["macro_date"] + MACRO_REGIME_COLUMNS].sort_values("macro_date"),
        left_on="rebalance_date",
        right_on="macro_date",
        direction="backward",
    )
    d = d.drop(columns=["macro_date"], errors="ignore")
    return d


# Stage 3d-ii-min (2026-04-20): sector_indicator + compute_macro_interaction_features
# moved to r1000_features.py.




# Stage 3d-iii (2026-04-20): compute_market_adaptation_features +
# compute_dynamic_leadership_features + load_manual_moat_overrides +
# apply_manual_ticker_overlays + compute_three_level_relative_strength +
# compute_crisis_sector_fit moved to r1000_features.py.




# Stage 3d-iv (2026-04-20): compute_strategy_blueprint_columns +
# compute_multidimensional_pillar_scores moved to r1000_features.py.




# Stage 4b-i (2026-04-20): compute_regime_portfolio_controls +
# compute_benchmark_beating_focus_overlay moved to r1000_signals.py.




# Stage 3d-iv (2026-04-20): compute_minervini_momentum_overlay moved to r1000_features.py.




def apply_focus_score_overlay(df: pd.DataFrame, cfg: EngineConfig) -> pd.DataFrame:
    d = df.copy()
    d["score_focus_bonus"] = 0.0
    d["score_pre_focus_total"] = numeric_series_or_default(d, "score", 0.0)
    d["score_base_model"] = numeric_series_or_default(d, "score_model_core", 0.0)
    d = compute_benchmark_beating_focus_overlay(d, cfg)
    if cfg.use_benchmark_beating_focus_overlay:
        d["score_focus_bonus_raw"] = (
            float(cfg.focus_overlay_strength)
            * robust_z(pd.to_numeric(d["benchmark_beating_focus_score"], errors="coerce")).fillna(0.0)
        )
        join_status = d.get("fund_join_status", pd.Series("", index=d.index, dtype=str)).astype(str)
        confirmation = numeric_series_or_default(d, "selection_confirmation_score", 0.0).clip(lower=0.0, upper=1.0)
        fundamental_confirmation = numeric_series_or_default(
            d, "selection_fundamental_confirmation_score", 0.0
        ).clip(lower=0.0, upper=1.0)
        market_confirmation = numeric_series_or_default(
            d, "selection_market_confirmation_score", 0.0
        ).clip(lower=0.0, upper=1.0)
        weak_no_ttm = (join_status == "matched_no_ttm") & (confirmation < 0.35)
        moderate_no_ttm = (join_status == "matched_no_ttm") & (confirmation >= 0.35) & (confirmation < 0.65)
        severe_no_ttm = (join_status == "matched_no_ttm") & (np.maximum(fundamental_confirmation, 0.85 * market_confirmation) < 0.25)
        bonus_cap = pd.Series(np.inf, index=d.index, dtype=float)
        bonus_cap.loc[moderate_no_ttm] = float(cfg.focus_no_ttm_bonus_cap_confirmed)
        bonus_cap.loc[weak_no_ttm] = float(cfg.focus_no_ttm_bonus_cap_weak)
        bonus_cap.loc[severe_no_ttm] = min(float(cfg.focus_no_ttm_bonus_cap_weak), 1.25)
        d["focus_bonus_cap"] = bonus_cap.replace(np.inf, np.nan)
        d["score_focus_bonus"] = pd.to_numeric(d["score_focus_bonus_raw"], errors="coerce").fillna(0.0)
        cap_mask = d["score_focus_bonus"] > bonus_cap
        d.loc[cap_mask, "score_focus_bonus"] = bonus_cap.loc[cap_mask]
        d["score_focus_bonus"] = d["score_focus_bonus"] - float(cfg.focus_missing_fundamental_penalty) * np.clip(
            0.40 - np.maximum(fundamental_confirmation, 0.85 * market_confirmation), 0.0, None
        )
        d["score"] = numeric_series_or_default(d, "score", 0.0) + numeric_series_or_default(d, "score_focus_bonus", 0.0)
    d["score_total"] = numeric_series_or_default(d, "score", 0.0)
    return d


def chunked(items: list[Any], size: int) -> Iterable[list[Any]]:
    step = max(int(size), 1)
    for i in range(0, len(items), step):
        yield items[i : i + step]


def normalize_price_download_frame(d: pd.DataFrame) -> pd.DataFrame:
    if d is None or d.empty:
        return pd.DataFrame()
    out = d.copy()
    if isinstance(out.columns, pd.MultiIndex) and out.columns.nlevels > 1:
        out.columns = out.columns.get_level_values(-1)
    out.index = pd.to_datetime(out.index).tz_localize(None)
    out = out.dropna(how="all")
    return out


def extract_batch_price_frame(downloaded: pd.DataFrame, ysym: str) -> pd.DataFrame:
    if downloaded is None or downloaded.empty:
        return pd.DataFrame()
    if not isinstance(downloaded.columns, pd.MultiIndex):
        return normalize_price_download_frame(downloaded)

    sub = pd.DataFrame()
    cols = downloaded.columns
    lvl0 = [str(x) for x in cols.get_level_values(0)]
    lvl1 = [str(x) for x in cols.get_level_values(1)]
    try:
        if ysym in lvl1:
            sub = downloaded.xs(ysym, axis=1, level=1, drop_level=True)
        elif ysym in lvl0:
            sub = downloaded.xs(ysym, axis=1, level=0, drop_level=True)
    except Exception:
        sub = pd.DataFrame()
    return normalize_price_download_frame(sub)


def merge_price_cache_frame(paths: dict[str, Path], ticker: str, base_df: Optional[pd.DataFrame], new_df: pd.DataFrame) -> bool:
    d = normalize_price_download_frame(new_df)
    if d.empty:
        return True if (base_df is not None and not base_df.empty) else False
    merged = pd.concat([base_df, d], axis=0) if (base_df is not None and not base_df.empty) else d
    merged = merged[~merged.index.duplicated(keep="last")]
    save_px(paths, ticker, merged)
    return True


def download_yf_price_batch(symbols: list[str], **kwargs: Any) -> dict[str, pd.DataFrame]:
    if not symbols:
        return {}
    try:
        downloaded = yf.download(
            symbols,
            auto_adjust=False,
            actions=True,
            progress=False,
            **kwargs,
        )
    except Exception:
        return {}
    out: dict[str, pd.DataFrame] = {}
    for sym in symbols:
        sub = extract_batch_price_frame(downloaded, sym)
        if not sub.empty:
            out[str(sym)] = sub
    if len(symbols) == 1 and symbols[0] not in out:
        sub = normalize_price_download_frame(downloaded)
        if not sub.empty:
            out[str(symbols[0])] = sub
    return out


def update_one_ticker_incremental(cfg: EngineConfig, paths: dict[str, Path], ticker: str) -> bool:
    base_df = load_px(paths, ticker)
    ysym = to_yf_symbol(ticker)
    end_dt = pd.Timestamp.utcnow().normalize() + pd.Timedelta(days=1)
    end_str = end_dt.strftime("%Y-%m-%d")
    try:
        full_refresh = bool(base_df is not None and not base_df.empty and "Dividends" not in base_df.columns)
        if base_df is None or base_df.empty or full_refresh:
            period = f"{cfg.price_history_years}y"
            d = download_yf_price_batch([ysym], period=period, interval="1d").get(ysym, pd.DataFrame())
        else:
            last_dt = pd.Timestamp(pd.to_datetime(base_df.index).max()).normalize()
            today_utc = pd.Timestamp.utcnow().normalize()
            if last_dt >= (today_utc - pd.Timedelta(days=1)):
                return True
            start_dt = last_dt + pd.Timedelta(days=1)
            if start_dt >= end_dt:
                return True
            d = download_yf_price_batch(
                [ysym],
                start=start_dt.strftime("%Y-%m-%d"),
                end=end_str,
                interval="1d",
            ).get(ysym, pd.DataFrame())
        return merge_price_cache_frame(paths, ticker, base_df, d)
    except Exception:
        return True if (base_df is not None and not base_df.empty) else False


def ensure_prices_cached_incremental(cfg: EngineConfig, paths: dict[str, Path], tickers: list[str]) -> None:
    tickers = [t for t in tickers if is_valid_price_symbol(t)]
    fail = load_fail_tickers(paths)
    # Prevent blacklist poisoning: clear oversized blacklist and keep only currently relevant symbols.
    fail = {t for t in fail if t in set(tickers)}
    if len(fail) > int(0.50 * max(1, len(tickers))):
        log(f"[WARN] Blacklist is oversized ({len(fail)}/{len(tickers)}). Auto-clearing blacklist.")
        fail = set()
        save_fail_tickers(paths, fail)

    need = [t for t in tickers if t not in fail]
    log(f"Updating price cache for {len(need):,} tickers (blacklist={len(fail)}) ...")
    new_fail: set[str] = set()
    today_utc = pd.Timestamp.utcnow().normalize()
    end_dt = today_utc + pd.Timedelta(days=1)
    end_str = end_dt.strftime("%Y-%m-%d")
    full_refresh: list[tuple[str, str, Optional[pd.DataFrame], bool]] = []
    grouped_incremental: dict[str, list[tuple[str, str, Optional[pd.DataFrame], bool]]] = {}
    fallback_single: list[tuple[str, Optional[pd.DataFrame], bool]] = []

    for t in need:
        base_df = load_px(paths, t)
        has_cache = base_df is not None and not base_df.empty
        ysym = to_yf_symbol(t)
        try:
            full = bool(has_cache and "Dividends" not in base_df.columns)
            if (not has_cache) or full:
                full_refresh.append((t, ysym, base_df, has_cache))
                continue
            last_dt = pd.Timestamp(pd.to_datetime(base_df.index).max()).normalize()
            if last_dt >= (today_utc - pd.Timedelta(days=1)):
                continue
            start_dt = last_dt + pd.Timedelta(days=1)
            if start_dt >= end_dt:
                continue
            grouped_incremental.setdefault(start_dt.strftime("%Y-%m-%d"), []).append((t, ysym, base_df, has_cache))
        except Exception:
            fallback_single.append((t, base_df, has_cache))

    def _finalize_result(ok: bool, ticker: str, has_cache: bool) -> None:
        if (not ok) and (not has_cache):
            new_fail.add(ticker)

    use_batch = bool(getattr(cfg, "yf_enable_batch_download", True))
    batch_size = max(int(getattr(cfg, "yf_batch_download_size", 64)), 1)

    def _run_batch(rows: list[tuple[str, str, Optional[pd.DataFrame], bool]], **kwargs: Any) -> None:
        if not rows:
            return
        if (not use_batch) or len(rows) == 1:
            for ticker, _, base_df, has_cache in rows:
                ok = False
                for _ in range(cfg.yf_retry):
                    if update_one_ticker_incremental(cfg, paths, ticker):
                        ok = True
                        break
                    time.sleep(0.4)
                _finalize_result(ok, ticker, has_cache)
            return

        for batch in chunked(rows, batch_size):
            symbols = [ysym for _, ysym, _, _ in batch]
            frames: dict[str, pd.DataFrame] = {}
            for _ in range(cfg.yf_retry):
                frames = download_yf_price_batch(symbols, **kwargs)
                if frames:
                    break
                time.sleep(0.4)
            for ticker, ysym, base_df, has_cache in batch:
                frame = frames.get(ysym, pd.DataFrame())
                ok = merge_price_cache_frame(paths, ticker, base_df, frame)
                if (not ok) and (not has_cache):
                    # Fall back to single-name download before blacklisting a missing cache.
                    ok = update_one_ticker_incremental(cfg, paths, ticker)
                _finalize_result(ok, ticker, has_cache)
            time.sleep(cfg.yf_sleep)

    _run_batch(full_refresh, period=f"{cfg.price_history_years}y", interval="1d")
    for start_str, rows in sorted(grouped_incremental.items()):
        _run_batch(rows, start=start_str, end=end_str, interval="1d")
    for ticker, base_df, has_cache in fallback_single:
        ok = update_one_ticker_incremental(cfg, paths, ticker)
        _finalize_result(ok, ticker, has_cache)
    if new_fail:
        fail_ratio = len(new_fail) / max(1, len(need))
        # Provider outage/rate-limit safety: do not permanently blacklist everyone.
        if fail_ratio > 0.60 and len(new_fail) > 50:
            log(
                f"[WARN] High yfinance failure ratio detected ({fail_ratio:.1%}, {len(new_fail)} tickers). "
                "Skipping blacklist update to avoid poisoning."
            )
        else:
            fail |= new_fail
            save_fail_tickers(paths, fail)
            log(f"[WARN] Added {len(new_fail)} yfinance failures to blacklist.")


def load_mktcap_proxy_cache(paths: dict[str, Path]) -> pd.DataFrame:
    p = paths["cache_misc"] / "yf_mktcap_proxy.parquet"
    if not p.exists():
        return pd.DataFrame(columns=["ticker", "mktcap_proxy", "updated_at"])
    try:
        return pd.read_parquet(p)
    except Exception:
        return pd.DataFrame(columns=["ticker", "mktcap_proxy", "updated_at"])


def save_mktcap_proxy_cache(paths: dict[str, Path], df: pd.DataFrame) -> None:
    p = paths["cache_misc"] / "yf_mktcap_proxy.parquet"
    df.to_parquet(p, index=False)


def fetch_mktcap_proxy(ticker: str) -> dict[str, Any]:
    try:
        t = yf.Ticker(to_yf_symbol(ticker))
        info = t.info or {}
        val = info.get("marketCap")
        mkt = float(val) if val is not None else np.nan
    except Exception:
        mkt = np.nan
    return {"ticker": ticker, "mktcap_proxy": mkt, "updated_at": datetime.utcnow().isoformat(timespec="seconds")}


def ensure_mktcap_proxy(cfg: EngineConfig, paths: dict[str, Path], tickers: list[str], max_new: int = 500) -> pd.DataFrame:
    cache = load_mktcap_proxy_cache(paths)
    cache["updated_at"] = pd.to_datetime(cache.get("updated_at"), errors="coerce")
    recent_cut = pd.Timestamp.utcnow().tz_localize(None) - pd.Timedelta(days=14)
    fresh = cache[cache["updated_at"] >= recent_cut] if not cache.empty else pd.DataFrame()
    have = set(fresh["ticker"].tolist()) if not fresh.empty else set()
    need = [t for t in tickers if t not in have][:max_new]
    if need:
        rows = []
        for i, t in enumerate(need, start=1):
            rows.append(fetch_mktcap_proxy(t))
            if i % 40 == 0:
                time.sleep(1.0)
        add = pd.DataFrame(rows)
        cache = pd.concat([cache, add], ignore_index=True) if not cache.empty else add
        cache = cache.sort_values("updated_at").drop_duplicates("ticker", keep="last")
        save_mktcap_proxy_cache(paths, cache)
    return cache


# =====================================================================
# Phase 2.1: yfinance industry / sub-industry metadata cache
# =====================================================================
INDUSTRY_METADATA_COLUMNS = [
    "ticker",
    "yf_sector",
    "yf_industry",
    "yf_industry_disp",
    "yf_sector_key",
    "yf_industry_key",
    "updated_at",
]


def load_industry_metadata_cache(paths: dict[str, Path]) -> pd.DataFrame:
    p = paths["cache_misc"] / "yf_industry_metadata.parquet"
    if not p.exists():
        return pd.DataFrame(columns=INDUSTRY_METADATA_COLUMNS)
    try:
        df = pd.read_parquet(p)
    except Exception:
        return pd.DataFrame(columns=INDUSTRY_METADATA_COLUMNS)
    for c in INDUSTRY_METADATA_COLUMNS:
        if c not in df.columns:
            df[c] = pd.Series(dtype=object)
    return df


def save_industry_metadata_cache(paths: dict[str, Path], df: pd.DataFrame) -> None:
    p = paths["cache_misc"] / "yf_industry_metadata.parquet"
    df.to_parquet(p, index=False)


def fetch_ticker_industry_metadata(ticker: str) -> dict[str, Any]:
    """Fetch yfinance industry / sub-industry metadata for a single ticker.

    yfinance's `info` payload exposes `industry`, `industryDisp`, `industryKey`,
    `sector`, and `sectorKey` for most US equities.  We capture all of them so
    the engine can either use the raw yfinance taxonomy or fall back to the
    coarser SAGE/GICS bucket map (`YF_INDUSTRY_TO_GICS_GROUP`) when needed.
    """
    record: dict[str, Any] = {
        "ticker": ticker,
        "yf_sector": None,
        "yf_industry": None,
        "yf_industry_disp": None,
        "yf_sector_key": None,
        "yf_industry_key": None,
        # Use pd.Timestamp (tz-naive UTC) so downstream concat/sort stays in
        # datetime64 dtype.  Writing an ISO string here previously caused a
        # dtype mismatch (str vs Timestamp) after concat with a freshly-loaded
        # cache and crashed `sort_values("updated_at")`.
        "updated_at": pd.Timestamp.utcnow().tz_localize(None),
    }
    try:
        t = yf.Ticker(to_yf_symbol(ticker))
        info = t.info or {}
        record["yf_sector"] = info.get("sector") or None
        record["yf_industry"] = info.get("industry") or None
        record["yf_industry_disp"] = info.get("industryDisp") or info.get("industry") or None
        record["yf_sector_key"] = info.get("sectorKey") or None
        record["yf_industry_key"] = info.get("industryKey") or None
    except Exception:
        pass
    return record


def ensure_industry_metadata(
    cfg: EngineConfig,
    paths: dict[str, Path],
    tickers: list[str],
    max_new: int = 500,
    refresh_days: int = 60,
) -> pd.DataFrame:
    """Return a fresh industry-metadata table for `tickers`, refreshing yfinance
    lookups for any ticker missing or older than `refresh_days`.  Cap each call
    at `max_new` new fetches so a cold start does not blow through Yahoo's
    rate limits in one shot.
    """
    cache = load_industry_metadata_cache(paths)
    cache["updated_at"] = pd.to_datetime(cache.get("updated_at"), errors="coerce")
    recent_cut = pd.Timestamp.utcnow().tz_localize(None) - pd.Timedelta(days=int(max(refresh_days, 1)))
    fresh = cache[cache["updated_at"] >= recent_cut] if not cache.empty else pd.DataFrame()
    have = set(fresh["ticker"].astype(str).tolist()) if not fresh.empty else set()
    need = [t for t in tickers if str(t) not in have][: int(max(max_new, 0))]
    if need:
        log(
            f"[yf_industry] Fetching industry metadata for {len(need)} tickers "
            f"(cached={len(have)}, refresh_days={refresh_days}) ..."
        )
        rows: list[dict[str, Any]] = []
        for i, t in enumerate(need, start=1):
            rows.append(fetch_ticker_industry_metadata(t))
            if i % 40 == 0:
                time.sleep(1.0)
            if i % 200 == 0 or i == len(need):
                log(f"[yf_industry]   progress: {i}/{len(need)}")
        add = pd.DataFrame(rows)
        # Force `updated_at` to datetime64 on both sides before concat so a
        # string-typed legacy cache file never poisons the sort that follows.
        if "updated_at" in add.columns:
            add["updated_at"] = pd.to_datetime(add["updated_at"], errors="coerce")
        if not cache.empty and "updated_at" in cache.columns:
            cache["updated_at"] = pd.to_datetime(cache["updated_at"], errors="coerce")
        cache = pd.concat([cache, add], ignore_index=True) if not cache.empty else add
        # Belt-and-suspenders: re-coerce after concat in case a column ended up
        # object-typed due to mixed inputs, then sort.
        cache["updated_at"] = pd.to_datetime(cache["updated_at"], errors="coerce")
        cache = (
            cache.sort_values("updated_at", na_position="first")
            .drop_duplicates("ticker", keep="last")
            .reset_index(drop=True)
        )
        save_industry_metadata_cache(paths, cache)
    # Always return a cache with updated_at coerced to datetime so downstream
    # consumers (recent_cut filters etc.) see a consistent dtype even if we
    # skipped the fetch branch above.
    if "updated_at" in cache.columns and not cache.empty:
        cache["updated_at"] = pd.to_datetime(cache["updated_at"], errors="coerce")
    return cache


def get_nyse_days(start_date: str, end_date: str) -> pd.DatetimeIndex:
    if mcal is not None:
        cal = mcal.get_calendar("NYSE")
        sch = cal.schedule(start_date=start_date, end_date=end_date)
        return pd.DatetimeIndex(pd.to_datetime(sch.index).tz_localize(None))
    # Fallback when pandas_market_calendars is unavailable.
    return pd.bdate_range(start=start_date, end=end_date)


def month_end_trading_days(start_date: str, end_date: str) -> list[pd.Timestamp]:
    days = get_nyse_days(start_date, end_date)
    if len(days) == 0:
        return []
    df = pd.DataFrame(index=days)
    df["ym"] = df.index.to_period("M")
    out = df.groupby("ym").tail(1).index.tolist()
    return [pd.Timestamp(x) for x in out]


def select_rebalance_dates_by_interval(
    months: Iterable[pd.Timestamp | str],
    interval_months: int = 1,
    anchor_to_latest: bool = True,
) -> list[pd.Timestamp]:
    clean = sorted(pd.to_datetime(list(months), errors="coerce").dropna().unique().tolist())
    if not clean:
        return []
    interval = max(int(interval_months), 1)
    if interval <= 1:
        return [pd.Timestamp(x) for x in clean]
    if anchor_to_latest:
        selected = [
            pd.Timestamp(dt)
            for i, dt in enumerate(clean)
            if ((len(clean) - 1 - i) % interval) == 0
        ]
    else:
        selected = [pd.Timestamp(dt) for dt in clean[::interval]]
    if len(selected) < 2 and len(clean) >= 2:
        selected = [pd.Timestamp(clean[-2]), pd.Timestamp(clean[-1])]
    return sorted(pd.to_datetime(selected, errors="coerce").dropna().tolist())


def next_rebalance_date_for_interval(last_rebalance_date: Any, interval_months: int = 1) -> Optional[pd.Timestamp]:
    last_dt = pd.to_datetime(last_rebalance_date, errors="coerce")
    if pd.isna(last_dt):
        return None
    interval = max(int(interval_months), 1)
    target_period = (pd.Timestamp(last_dt).to_period("M") + interval)
    target_start = str(target_period.start_time.date())
    target_end = str(target_period.end_time.date())
    target_days = month_end_trading_days(target_start, target_end)
    if not target_days:
        return None
    return pd.Timestamp(target_days[-1])


def next_nyse_trading_day_on_or_after(date_like: Any, max_search_days: int = 14) -> Optional[pd.Timestamp]:
    dt = pd.to_datetime(date_like, errors="coerce")
    if pd.isna(dt):
        return None
    start = pd.Timestamp(dt).normalize()
    end = start + pd.Timedelta(days=max(int(max_search_days), 1))
    days = get_nyse_days(str(start.date()), str(end.date()))
    if len(days) == 0:
        return None
    return pd.Timestamp(days[0])


def compute_rsi(close: pd.Series, n: int = 14) -> pd.Series:
    delta = close.diff()
    up = delta.clip(lower=0)
    down = (-delta).clip(lower=0)
    roll_up = up.ewm(alpha=1 / n, adjust=False).mean()
    roll_down = down.ewm(alpha=1 / n, adjust=False).mean()
    rs = roll_up / roll_down.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def compute_daily_tech_table(hist: pd.DataFrame) -> pd.DataFrame:
    if hist is None or hist.empty:
        return pd.DataFrame()
    d = hist.copy()
    d.index = pd.to_datetime(d.index).tz_localize(None)
    if "Adj Close" in d.columns:
        close = pd.to_numeric(squeeze_series(d["Adj Close"]), errors="coerce").astype(float)
    else:
        close = pd.to_numeric(squeeze_series(d["Close"]), errors="coerce").astype(float)
    open_ = adjusted_open_series(d)
    high = (
        pd.to_numeric(squeeze_series(d["High"]), errors="coerce").astype(float)
        if "High" in d.columns
        else close.copy()
    )
    low = (
        pd.to_numeric(squeeze_series(d["Low"]), errors="coerce").astype(float)
        if "Low" in d.columns
        else close.copy()
    )
    vol = pd.to_numeric(squeeze_series(d["Volume"]), errors="coerce").astype(float)
    dividends = (
        pd.to_numeric(squeeze_series(d["Dividends"]), errors="coerce").astype(float)
        if "Dividends" in d.columns
        else pd.Series(0.0, index=close.index, dtype=float)
    )

    def recent_event_score(event: pd.Series, lookback: int) -> pd.Series:
        event_bool = event.fillna(False).astype(bool)
        pos = pd.Series(np.arange(len(event_bool), dtype=float), index=event_bool.index, dtype=float)
        last_hit = pd.Series(np.where(event_bool.to_numpy(), pos.to_numpy(), np.nan), index=event_bool.index, dtype=float).ffill()
        age = pos - last_hit
        score = (1.0 - age / float(max(int(lookback), 1))).clip(lower=0.0, upper=1.0)
        return score.where(last_hit.notna(), 0.0).fillna(0.0)

    out = pd.DataFrame(index=close.index)
    out["px"] = close
    out["open_px"] = open_
    out["dividends_ttm_ps"] = dividends.rolling(252, min_periods=1).sum()
    out["dividend_yield_ttm"] = out["dividends_ttm_ps"] / close.replace(0, np.nan)
    out["mom_1m"] = close.pct_change(21)
    out["mom_3m"] = close.pct_change(63)
    out["mom_6m"] = close.pct_change(126)
    out["mom_12m"] = close.pct_change(252)
    # Phase 8b.1 (2026-04-17): long-lookback momentum. Factor IC analysis
    # (DIAGNOSIS_FACTOR_IC.md) showed fundamental factors have 2-4x
    # stronger IC at r_12m than r_1m, but our engine only had mom up to
    # 12m — we were blind to multi-year winners (NVDA/AVGO/MU) in their
    # multi-year-trend phase. Three new lookbacks + a composite
    # "multi_year_winner_score" that rewards names with persistent
    # positive returns across 1y / 2y / 3y horizons.
    out["mom_18m"] = close.pct_change(378)
    out["mom_24m"] = close.pct_change(504)
    out["mom_36m"] = close.pct_change(756)
    ma20 = close.rolling(20).mean()
    ma50 = close.rolling(50).mean()
    ma150 = close.rolling(150).mean()
    ma200 = close.rolling(200).mean()
    out["dist_ma200"] = close / ma200.replace(0, np.nan) - 1.0
    out["price_above_ma20"] = (close > ma20).astype(float)
    out["price_above_ma50"] = (close > ma50).astype(float)
    out["price_above_ma200"] = (close > ma200).astype(float)
    out["ma20_above_ma50"] = (ma20 > ma50).astype(float)
    out["ma50_above_ma200"] = (ma50 > ma200).astype(float)
    out["price_above_ma150"] = (close > ma150).astype(float)
    out["ma50_above_ma150"] = (ma50 > ma150).astype(float)
    out["ma150_above_ma200"] = (ma150 > ma200).astype(float)
    golden_cross = (ma50 > ma200) & (ma50.shift(1) <= ma200.shift(1))
    death_cross = (ma50 < ma200) & (ma50.shift(1) >= ma200.shift(1))
    out["golden_cross_fresh_20d"] = recent_event_score(golden_cross, 20)
    out["death_cross_recent_20d"] = recent_event_score(death_cross, 20)
    out["trend_template_full"] = ((close > ma50) & (ma50 > ma150) & (ma150 > ma200)).astype(float)
    out["trend_template_relaxed"] = ((close > ma50) & (ma50 > ma200)).astype(float)
    out["ret_1d"] = close.pct_change()
    out["vol_252d"] = out["ret_1d"].rolling(252).std()
    out["rsi14"] = compute_rsi(close, n=14)
    high_52w = close.rolling(252).max()
    out["near_52w_high_pct"] = close / high_52w.replace(0, np.nan) - 1.0
    out["high_tight_30_bonus"] = (out["near_52w_high_pct"] >= -0.30).astype(float)
    out["ma200_slope_1m"] = ma200.pct_change(21)

    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    out["macd_hist"] = macd - signal

    m20 = close.rolling(20).mean()
    s20 = close.rolling(20).std()
    upper = m20 + 2 * s20
    lower = m20 - 2 * s20
    out["bb_pb"] = (close - lower) / (upper - lower).replace(0, np.nan)

    obv = np.where(close > close.shift(1), vol, np.where(close < close.shift(1), -vol, 0.0))
    obv = pd.Series(obv, index=close.index).cumsum()
    obv_sma = obv.rolling(20).mean()
    out["obv_trend"] = (obv - obv_sma) / (obv_sma.abs() + 1e-9)
    vol_mean20 = vol.rolling(20).mean()
    vol_mean63 = vol.rolling(63).mean()
    vol_std20 = vol.rolling(20).std()
    vol_z20 = (vol - vol_mean20) / vol_std20.replace(0, np.nan)
    breakout_ref = close.rolling(63).max().shift(1)
    breakout_flag = (close >= breakout_ref) & (out["ret_1d"] > 0)
    out["breakout_distance_63d"] = close / breakout_ref.replace(0, np.nan) - 1.0
    out["breakout_fresh_20d"] = recent_event_score(breakout_flag, 20)
    out["breakout_volume_z"] = vol_z20.where(breakout_flag, 0.0)
    out["volume_dryup_20d"] = (1.0 - vol_mean20 / vol_mean63.replace(0, np.nan)).clip(lower=-1.0, upper=1.0)
    short_vol = out["ret_1d"].rolling(21).std()
    long_vol = out["ret_1d"].rolling(63).std()
    out["volatility_contraction_score"] = 1.0 - (short_vol / long_vol.replace(0, np.nan))
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            (high - low).abs().rename("hl"),
            (high - prev_close).abs().rename("hc"),
            (low - prev_close).abs().rename("lc"),
        ],
        axis=1,
    ).max(axis=1)
    out["atr14_pct"] = tr.rolling(14).mean() / close.replace(0, np.nan)
    hold_components = row_mean(
        [
            out["breakout_fresh_20d"],
            out["price_above_ma20"],
            out["price_above_ma50"],
            (out["breakout_distance_63d"] > -0.03).astype(float),
            (out["dist_ma200"] > -0.02).astype(float),
        ],
        out.index,
    ).fillna(0.0)
    out["post_breakout_hold_score"] = hold_components.clip(lower=0.0, upper=1.0)

    out["dollar_vol_20d"] = (close * vol).rolling(20).mean()
    dd = close / close.cummax() - 1.0
    out["dd_1y"] = dd.rolling(252).min().abs()
    return out


def compute_forward_returns_for_dates(
    hist: pd.DataFrame,
    base_dates: pd.Series,
    horizons: list[int],
) -> tuple[pd.Series, dict[int, pd.Series]]:
    base = pd.to_datetime(base_dates, errors="coerce")
    entry_dates = pd.Series(pd.NaT, index=base.index, dtype="datetime64[ns]")
    returns = {int(h): pd.Series(np.nan, index=base.index, dtype=float) for h in horizons}
    if hist is None or hist.empty or "Open" not in hist.columns:
        return entry_dates, returns

    idx = pd.DatetimeIndex(pd.to_datetime(hist.index).tz_localize(None))
    if len(idx) == 0:
        return entry_dates, returns
    open_px = pd.to_numeric(adjusted_open_series(hist), errors="coerce").astype(float)
    raw_pos = idx.searchsorted((base + pd.Timedelta(days=1)).to_numpy(), side="left")
    valid_entry = base.notna().to_numpy() & (raw_pos < len(idx))
    if valid_entry.any():
        entry_vals = idx.to_numpy()[raw_pos[valid_entry]]
        entry_dates.loc[valid_entry] = pd.to_datetime(entry_vals)

    open_arr = open_px.to_numpy(dtype=float)
    for h in horizons:
        target_pos = raw_pos + int(h)
        valid = valid_entry & (target_pos < len(idx))
        if not valid.any():
            continue
        p0 = open_arr[raw_pos[valid]]
        p1 = open_arr[target_pos[valid]]
        out = np.full(valid.sum(), np.nan, dtype=float)
        good = np.isfinite(p0) & np.isfinite(p1) & (p0 != 0)
        out[good] = p1[good] / p0[good] - 1.0
        returns[int(h)].loc[valid] = out
    return entry_dates, returns


def compute_earn_gap_1d_for_dates(hist: pd.DataFrame, accepted_dates: pd.Series) -> pd.Series:
    accepted = pd.to_datetime(accepted_dates, errors="coerce")
    out = pd.Series(np.nan, index=accepted.index, dtype=float)
    if hist is None or hist.empty:
        return out
    idx = pd.DatetimeIndex(pd.to_datetime(hist.index).tz_localize(None))
    if len(idx) == 0:
        return out
    ccol = "Adj Close" if "Adj Close" in hist.columns else "Close"
    close = pd.to_numeric(squeeze_series(hist[ccol]), errors="coerce").astype(float).to_numpy(dtype=float)
    raw_pos = idx.searchsorted((accepted + pd.Timedelta(days=1)).to_numpy(), side="left")
    valid = accepted.notna().to_numpy() & (raw_pos > 0) & (raw_pos < len(idx))
    if not valid.any():
        return out
    prev_close = close[raw_pos[valid] - 1]
    cur_close = close[raw_pos[valid]]
    vals = np.full(valid.sum(), np.nan, dtype=float)
    good = np.isfinite(prev_close) & np.isfinite(cur_close) & (prev_close != 0)
    vals[good] = cur_close[good] / prev_close[good] - 1.0
    out.loc[valid] = vals
    return out


def get_date_on_or_after(idx: pd.DatetimeIndex, dt: pd.Timestamp) -> Optional[pd.Timestamp]:
    pos = idx.searchsorted(dt, side="left")
    if pos >= len(idx):
        return None
    return pd.Timestamp(idx[pos])


def return_open_to_open(hist: pd.DataFrame, start_dt: pd.Timestamp, horizon: int) -> Optional[float]:
    if hist is None or hist.empty or "Open" not in hist.columns:
        return None
    idx = pd.DatetimeIndex(pd.to_datetime(hist.index).tz_localize(None))
    dt0 = get_date_on_or_after(idx, pd.Timestamp(start_dt))
    if dt0 is None:
        return None
    i0 = int(np.where(idx == dt0)[0][0])
    i1 = i0 + int(horizon)
    if i1 >= len(idx):
        return None
    op = adjusted_open_series(hist)
    p0 = float(op.iloc[i0])
    p1 = float(op.iloc[i1])
    if p0 == 0 or not np.isfinite(p0) or not np.isfinite(p1):
        return None
    return p1 / p0 - 1.0


def earn_gap_1d_feature(paths: dict[str, Path], ticker: str, accepted: pd.Timestamp) -> float:
    df = load_px(paths, ticker)
    if df is None or df.empty:
        return np.nan
    idx = pd.DatetimeIndex(pd.to_datetime(df.index).tz_localize(None))
    nx = get_date_on_or_after(idx, pd.Timestamp(accepted) + pd.Timedelta(days=1))
    if nx is None:
        return np.nan
    pos = idx.get_indexer([nx])[0]
    if pos <= 0:
        return np.nan
    ccol = "Adj Close" if "Adj Close" in df.columns else "Close"
    close = pd.to_numeric(squeeze_series(df[ccol]), errors="coerce").astype(float)
    prev_close = float(close.iloc[pos - 1])
    cur_close = float(close.iloc[pos])
    if prev_close == 0 or not np.isfinite(prev_close) or not np.isfinite(cur_close):
        return np.nan
    return cur_close / prev_close - 1.0


def quarter_list_last_n(nq: int) -> list[tuple[int, int]]:
    today = date.today()
    cur_q = (today.month - 1) // 3 + 1
    q = cur_q - 1
    y = today.year
    if q == 0:
        y -= 1
        q = 4
    out = []
    for _ in range(nq):
        out.append((y, q))
        q -= 1
        if q == 0:
            y -= 1
            q = 4
    return out


def download_fsds_zip(cfg: EngineConfig, paths: dict[str, Path], year: int, q: int) -> Optional[Path]:
    name = f"{year}q{q}.zip"
    url = f"https://www.sec.gov/files/dera/data/financial-statement-data-sets/{name}"
    out = paths["cache_fsds"] / name
    if out.exists():
        return out
    headers = {
        "User-Agent": cfg.sec_user_agent,
        "Accept-Encoding": "gzip, deflate",
        "Host": "www.sec.gov",
    }
    try:
        log(f"Downloading FSDS {name} ...")
        out.write_bytes(http_get(url, headers=headers, timeout=180).content)
        time.sleep(cfg.sec_sleep)
        return out
    except Exception:
        return None


def read_fsds_tables(zip_path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    with zipfile.ZipFile(zip_path) as z:
        with z.open("sub.txt") as f:
            sub = pd.read_csv(f, sep="\t", low_memory=False)
        with z.open("num.txt") as f:
            num = pd.read_csv(f, sep="\t", low_memory=False)
    return sub, num


def prep_sub(sub: pd.DataFrame) -> pd.DataFrame:
    keep = ["adsh", "cik", "period", "fy", "fp", "accepted", "form", "name"]
    out = sub[keep].copy()
    out["accepted"] = pd.to_datetime(out["accepted"], errors="coerce")
    out["period"] = pd.to_datetime(out["period"], errors="coerce")
    out["cik"] = normalize_cik_series(out["cik"], index=out.index)
    out["form"] = out["form"].astype(str).str.upper()
    out = out[out["form"].isin(ACCEPTED_SEC_FORMS)]
    return out


def prep_num(num: pd.DataFrame) -> pd.DataFrame:
    keep = ["adsh", "tag", "ddate", "qtrs", "uom", "value"]
    out = num[keep].copy()
    out["ddate"] = pd.to_datetime(out["ddate"], errors="coerce")
    out["qtrs"] = pd.to_numeric(out["qtrs"], errors="coerce")
    out["value"] = pd.to_numeric(out["value"], errors="coerce")
    return out


def quarterly_flow_from_ytd(df: pd.DataFrame) -> pd.DataFrame:
    d = df.sort_values(["cik", "tag", "fy", "accepted"])
    out = []
    for (cik, tag, fy), g in d.groupby(["cik", "tag", "fy"], sort=False, dropna=False):
        g = g.sort_values(["accepted"])
        prev: dict[int, float] = {}
        flows = []
        for _, r in g.iterrows():
            qtrs = int(r["qtrs"]) if pd.notna(r["qtrs"]) else 1
            val = r["value"]
            if qtrs <= 1:
                flow = val
                prev[qtrs] = val
            else:
                prev_val = prev.get(qtrs - 1, np.nan)
                flow = val - prev_val if pd.notna(prev_val) else np.nan
                prev[qtrs] = val
            flows.append(flow)
        gg = g.copy()
        gg["flow"] = flows
        out.append(gg)
    if not out:
        return pd.DataFrame(columns=list(df.columns) + ["flow"])
    return pd.concat(out, ignore_index=True)


# Stage 3d-i (2026-04-20): _flexible_lag + _cagr_from_lag +
# recompute_fund_panel_derived_columns moved to r1000_features.py.
# See features.py "Stage 3d-i" block header for details on scope preservation
# of the 3 nested helpers (_sign_flip_pos, _loss_narrowing_rate,
# _under_loss_growth) that drive Phase 9 C3.




def panel_latest_flow_coverage(panel: pd.DataFrame) -> float:
    if panel is None or panel.empty or "period" not in panel.columns:
        return 0.0
    d = panel.copy()
    d["period"] = pd.to_datetime(d["period"], errors="coerce")
    d["accepted"] = datetime_series_or_default(d, "accepted")
    d = d.sort_values(["cik", "period", "accepted"]).drop_duplicates(["cik"], keep="last")
    cols = [c for c in ["revenues_ttm", "net_income_ttm", "op_income_ttm"] if c in d.columns]
    if not cols:
        return 0.0
    ratios = [float(d[c].notna().mean()) for c in cols]
    return float(np.nanmean(ratios)) if ratios else 0.0


def select_targeted_repair_ciks(cfg: EngineConfig, base_panel: pd.DataFrame, cik_list: list[str]) -> list[str]:
    all_ciks = normalize_cik_list(cik_list)
    if not all_ciks:
        return []
    if base_panel is None or base_panel.empty:
        return all_ciks[: int(cfg.targeted_repair_max_ciks)]

    d = base_panel.copy()
    d["cik"] = normalize_cik_series(d["cik"], index=d.index)
    d["period"] = pd.to_datetime(d["period"], errors="coerce")
    d["accepted"] = pd.to_datetime(d["accepted"], errors="coerce")
    try:
        if getattr(d["accepted"].dt, "tz", None) is not None:
            d["accepted"] = d["accepted"].dt.tz_localize(None)
    except Exception:
        pass
    d = d.dropna(subset=["cik"]).sort_values(["cik", "period", "accepted"]).drop_duplicates(["cik", "period"], keep="last")
    if d.empty:
        return all_ciks[: int(cfg.targeted_repair_max_ciks)]

    flow_cols = ["revenues", "op_income", "net_income", "ocf", "capex"]
    today = pd.Timestamp.utcnow()
    try:
        if getattr(today, "tzinfo", None) is not None:
            today = today.tz_localize(None)
    except Exception:
        pass
    today = today.normalize()
    rows = []
    for cik, g in d.groupby("cik", sort=False):
        gg = g.sort_values(["period", "accepted"]).copy()
        latest = gg.tail(1)
        latest_accepted = pd.to_datetime(latest["accepted"].iloc[0], errors="coerce") if not latest.empty else pd.NaT
        stale_days = float((today - latest_accepted).days) if pd.notna(latest_accepted) else 9e9
        flow_cov = float(
            np.nanmean([float(gg.tail(4)[c].notna().mean()) if c in gg.columns else 0.0 for c in flow_cols])
        )
        ttm_ready = float(numeric_series_or_default(latest, "fund_ttm_ready", 0.0).iloc[0]) if not latest.empty else 0.0
        rows.append(
            {
                "cik": str(cik).zfill(10),
                "flow_cov_4q": flow_cov,
                "fund_ttm_ready": ttm_ready,
                "stale_days": stale_days,
            }
        )
    stats = pd.DataFrame(rows)
    if stats.empty:
        return all_ciks[: int(cfg.targeted_repair_max_ciks)]

    missing_ciks = sorted(set(all_ciks) - set(stats["cik"].astype(str)))
    weak = stats[
        (stats["fund_ttm_ready"] < 0.5)
        | (stats["flow_cov_4q"] < float(cfg.targeted_repair_flow_cov_threshold))
        | (stats["stale_days"] > float(cfg.targeted_repair_stale_days))
    ].copy()
    weak = weak.sort_values(
        ["fund_ttm_ready", "flow_cov_4q", "stale_days", "cik"],
        ascending=[True, True, False, True],
    )

    ordered = missing_ciks + weak["cik"].astype(str).tolist()
    seen = set()
    selected = []
    for cik in ordered:
        if cik in seen:
            continue
        seen.add(cik)
        selected.append(cik)

    min_selected = min(len(all_ciks), max(50, int(0.15 * len(all_ciks))))
    if len(selected) < min_selected:
        topup = stats.sort_values(["flow_cov_4q", "stale_days", "fund_ttm_ready"], ascending=[True, False, True])
        for cik in topup["cik"].astype(str):
            if cik in seen:
                continue
            seen.add(cik)
            selected.append(cik)
            if len(selected) >= min_selected:
                break

    return selected[: int(cfg.targeted_repair_max_ciks)]


def write_fund_panel_recent_flow_report(paths: dict[str, Path], panel: pd.DataFrame) -> Path:
    flow_cols = ["revenues", "op_income", "net_income", "ocf", "capex"]
    path = paths["reports"] / "fund_panel_recent4q_flow_coverage.csv"
    if panel is None or panel.empty:
        pd.DataFrame(
            columns=["cik", "latest_period", "quarters_available"] + [f"{c}_4q_cov" for c in flow_cols] + ["flow_4q_cov_mean"]
        ).to_csv(path, index=False)
        return path

    d = panel.copy()
    d["cik"] = normalize_cik_series(d["cik"], index=d.index)
    d["period"] = pd.to_datetime(d["period"], errors="coerce")
    d = d.dropna(subset=["cik", "period"]).sort_values(["cik", "period"])
    rows = []
    for cik, g in d.groupby("cik", sort=False):
        gg = g.tail(4).copy()
        covs = {f"{c}_4q_cov": float(gg[c].notna().mean()) if c in gg.columns else 0.0 for c in flow_cols}
        mean_cov = float(np.nanmean(list(covs.values()))) if covs else 0.0
        rows.append(
            {
                "cik": cik,
                "latest_period": str(pd.Timestamp(gg["period"].max()).date()) if gg["period"].notna().any() else None,
                "quarters_available": int(len(gg)),
                **covs,
                "flow_4q_cov_mean": mean_cov,
            }
        )
    pd.DataFrame(rows).sort_values(["flow_4q_cov_mean", "cik"], ascending=[False, True]).to_csv(path, index=False)
    return path


def attach_fund_panel_join_diagnostics(monthly: pd.DataFrame, panel: pd.DataFrame) -> pd.DataFrame:
    d = monthly.copy()
    diag_cols = [
        "fund_latest_period_overall",
        "fund_latest_accepted_overall",
        "fund_history_quarters_available",
        "fund_panel_raw_flow_4q_cov_mean",
        "fund_panel_ttm_ready",
        "fund_ttm_cum_fallback_used",
        "fund_ttm_backfill_used",
        "fund_ttm_fallback_used",
        "fund_ttm_fallback_age_days",
        "fund_effective_accepted",
        "fund_effective_period",
        "fund_effective_age_days",
        "fund_join_status",
        "fund_join_gap_days",
    ]
    if d.empty:
        for c in diag_cols:
            if c not in d.columns:
                d[c] = np.nan
        return d
    if panel is None or panel.empty:
        for c in diag_cols:
            if c not in d.columns:
                d[c] = np.nan
        return d

    p = panel.copy()
    p["cik"] = normalize_cik_series(p["cik"], index=p.index)
    p["period"] = pd.to_datetime(p["period"], errors="coerce")
    p["accepted"] = pd.to_datetime(p["accepted"], errors="coerce")
    p = p.sort_values(["cik", "period", "accepted"]).drop_duplicates(["cik", "period"], keep="last")

    flow_cols = ["revenues", "op_income", "net_income", "ocf", "capex"]
    latest_panel = (
        p.sort_values(["cik", "accepted", "period"])
        .drop_duplicates(["cik"], keep="last")
        .rename(
            columns={
                "cik": "cik10",
                "period": "fund_latest_period_overall",
                "accepted": "fund_latest_accepted_overall",
            }
        )
    )
    latest_panel["fund_panel_ttm_ready"] = pd.to_numeric(
        latest_panel.get("fund_ttm_ready"),
        errors="coerce",
    ).fillna(0.0)
    cov_rows = []
    for cik, g in p.groupby("cik", sort=False):
        gg = g.tail(4).copy()
        cov_rows.append(
            {
                "cik10": str(cik).zfill(10),
                "fund_panel_raw_flow_4q_cov_mean": float(
                    np.nanmean([float(gg[c].notna().mean()) if c in gg.columns else 0.0 for c in flow_cols])
                ),
            }
        )
    cov_df = pd.DataFrame(cov_rows)

    d["cik10"] = normalize_cik_series(d["cik10"], index=d.index)
    # Preserve PIT-matched history depth from the asof join. Re-merging identically
    # named columns from latest_panel would suffix away the base field and make
    # downstream diagnostics/scored outputs look like history depth is missing.
    d = d.merge(
        latest_panel[
            [
                "cik10",
                "fund_latest_period_overall",
                "fund_latest_accepted_overall",
            ]
        ],
        on="cik10",
        how="left",
    )
    d = d.merge(cov_df, on="cik10", how="left")
    if "fund_history_quarters_available" not in d.columns:
        d["fund_history_quarters_available"] = np.nan
    d["fund_history_quarters_available"] = pd.to_numeric(
        d["fund_history_quarters_available"],
        errors="coerce",
    )
    accepted = datetime_series_or_default(d, "accepted")
    panel_latest_accepted = datetime_series_or_default(d, "fund_latest_accepted_overall")
    d["fund_join_gap_days"] = (
        pd.to_datetime(d["rebalance_date"], errors="coerce")
        - accepted
    ).dt.days
    cik_missing = d["cik10"].isna() | d["cik10"].astype(str).isin({"", "nan", "None"})
    matched = accepted.notna()
    panel_exists = panel_latest_accepted.notna()
    effective_ttm_ready = pd.concat(
        [
            numeric_series_or_default(d, "revenues_ttm", np.nan),
            numeric_series_or_default(d, "net_income_ttm", np.nan),
            numeric_series_or_default(d, "op_margin_ttm", np.nan),
        ],
        axis=1,
    ).notna().all(axis=1)
    sector_labels = normalized_sector_labels(d)
    finance_mask = sector_keyword_mask(sector_labels, SECTOR_GATE_FINANCIAL_KEYWORDS)
    financial_ready_fields = pd.concat(
        [
            numeric_series_or_default(d, "assets", np.nan),
            numeric_series_or_default(d, "liabilities", np.nan),
            numeric_series_or_default(d, "net_income_ttm", np.nan),
            numeric_series_or_default(d, "roe_proxy", np.nan),
            numeric_series_or_default(d, "revenues_ttm", np.nan),
            numeric_series_or_default(d, "ocf_ttm", np.nan),
        ],
        axis=1,
    )
    financial_ttm_ready = financial_ready_fields.notna().sum(axis=1) >= 4
    ttm_ready = effective_ttm_ready.where(~finance_mask, financial_ttm_ready)
    ttm_backfill = numeric_series_or_default(d, "fund_ttm_backfill_used", 0.0) > 0
    ttm_fallback = numeric_series_or_default(d, "fund_ttm_fallback_used", 0.0) > 0
    d["fund_panel_ttm_ready"] = ttm_ready.astype(float)
    d["fund_join_status"] = np.select(
        [
            cik_missing,
            matched & ttm_ready & ttm_fallback,
            matched & ttm_ready & ttm_backfill,
            matched & ttm_ready,
            matched & (~ttm_ready),
            (~matched) & panel_exists,
        ],
        [
            "missing_cik",
            "matched_with_ttm_fallback",
            "matched_with_ttm_backfill",
            "matched_with_ttm",
            "matched_no_ttm",
            "panel_exists_but_no_pit_match",
        ],
        default="no_panel_for_cik",
    )
    return d


def write_fundamental_join_diagnostics(paths: dict[str, Path], monthly: pd.DataFrame) -> Path:
    path = paths["reports"] / "fundamental_join_latest_diagnostics.csv"
    if monthly is None or monthly.empty:
        pd.DataFrame(
            columns=[
                "ticker",
                "Name",
                "sector",
                "cik10",
                "rebalance_date",
                "accepted",
                "period",
                "fund_join_status",
                "fund_join_gap_days",
                "fund_history_quarters_available",
                "fund_panel_raw_flow_4q_cov_mean",
                "fund_ttm_cum_fallback_used",
                "fund_ttm_backfill_used",
                "fund_ttm_fallback_used",
                "fund_ttm_fallback_age_days",
                "fund_effective_accepted",
                "fund_effective_period",
                "sales_cagr_3y",
                "sales_cagr_5y",
                "op_income_cagr_3y",
                "op_income_cagr_5y",
                "net_income_cagr_3y",
                "net_income_cagr_5y",
                "revenues_ttm",
                "net_income_ttm",
                "op_margin_ttm",
                "ep_ttm",
                "sp_ttm",
                "fcfy_ttm",
            ]
        ).to_csv(path, index=False)
        return path

    d = monthly.copy()
    d["rebalance_date"] = pd.to_datetime(d["rebalance_date"], errors="coerce")
    latest_dt = d["rebalance_date"].max()
    latest = d[d["rebalance_date"] == latest_dt].copy() if pd.notna(latest_dt) else d.copy()
    keep = [
        "ticker",
        "Name",
        "sector",
        "cik10",
        "rebalance_date",
        "accepted",
        "period",
        "fund_latest_period_overall",
        "fund_latest_accepted_overall",
        "fund_join_status",
        "fund_join_gap_days",
        "fund_history_quarters_available",
        "fund_panel_raw_flow_4q_cov_mean",
        "fund_panel_ttm_ready",
        "fund_ttm_cum_fallback_used",
        "fund_ttm_backfill_used",
        "fund_ttm_fallback_used",
        "fund_ttm_fallback_age_days",
        "fund_effective_accepted",
        "fund_effective_period",
        "sales_cagr_3y",
        "sales_cagr_5y",
        "op_income_cagr_3y",
        "op_income_cagr_5y",
        "net_income_cagr_3y",
        "net_income_cagr_5y",
        "revenues_ttm",
        "net_income_ttm",
        "op_margin_ttm",
        "ep_ttm",
        "sp_ttm",
        "fcfy_ttm",
        "score",
    ]
    for c in keep:
        if c not in latest.columns:
            latest[c] = np.nan
    latest = latest[keep].sort_values(["fund_join_status", "score"], ascending=[True, False])
    latest.to_csv(path, index=False)

    summary = (
        latest["fund_join_status"].value_counts(dropna=False).rename_axis("fund_join_status").reset_index(name="count")
    )
    summary.to_csv(paths["reports"] / "fundamental_join_latest_summary.csv", index=False)
    return path


def write_fundamental_collection_audit(
    paths: dict[str, Path],
    panel: pd.DataFrame,
    monthly: pd.DataFrame,
    latest_normalized: Optional[pd.DataFrame] = None,
) -> dict[str, Path]:
    summary_path = paths["reports"] / "fundamental_collection_audit.json"
    missing_path = paths["reports"] / "fundamental_collection_missing_latest.csv"
    panel_path = paths["reports"] / "fundamental_panel_latest_snapshot.csv"

    if panel is None or panel.empty:
        pd.DataFrame().to_csv(missing_path, index=False)
        pd.DataFrame().to_csv(panel_path, index=False)
        summary_path.write_text(json.dumps({"panel_empty": True, "monthly_empty": monthly is None or monthly.empty}, indent=2))
        return {
            "fundamental_collection_audit": summary_path,
            "fundamental_collection_missing_latest": missing_path,
            "fundamental_panel_latest_snapshot": panel_path,
        }

    p = panel.copy()
    p["cik"] = normalize_cik_series(p["cik"], index=p.index)
    p["period"] = pd.to_datetime(p["period"], errors="coerce")
    p["accepted"] = pd.to_datetime(p["accepted"], errors="coerce")
    p = p.sort_values(["cik", "period", "accepted"]).drop_duplicates(["cik", "period"], keep="last")
    latest_panel = p.sort_values(["cik", "accepted", "period"]).drop_duplicates(["cik"], keep="last").copy()

    panel_keep = [
        "cik",
        "period",
        "accepted",
        "source",
        "asof_quarter",
        "quarter_index",
        "fund_history_quarters_available",
        "fund_ttm_ready",
        "fund_ttm_cum_fallback_used",
        "fund_ttm_backfill_used",
        "revenues",
        "op_income",
        "net_income",
        "ocf",
        "capex",
        "revenues_ttm",
        "sales_cagr_3y",
        "sales_cagr_5y",
        "op_income_ttm",
        "gross_profit_ttm",
        "gross_margins",
        "operating_margins",
        "op_income_growth_yoy",
        "op_income_cagr_3y",
        "op_income_cagr_5y",
        "ocf_growth_yoy",
        "ocf_cagr_3y",
        "ocf_cagr_5y",
        "op_margin_ttm",
        "net_income_ttm",
        "net_income_growth_yoy",
        "net_income_cagr_3y",
        "net_income_cagr_5y",
    ]
    for c in panel_keep:
        if c not in latest_panel.columns:
            latest_panel[c] = np.nan
    latest_panel[panel_keep].to_csv(panel_path, index=False)
    hist_depth = pd.to_numeric(
        latest_panel.get("fund_history_quarters_available", pd.Series(np.nan, index=latest_panel.index)),
        errors="coerce",
    )

    summary: dict[str, Any] = {
        "panel_rows": int(len(p)),
        "panel_ciks": int(p["cik"].nunique()),
        "latest_panel_ciks": int(latest_panel["cik"].nunique()),
        "latest_panel_ttm_ready_ratio": float(numeric_series_or_default(latest_panel, "fund_ttm_ready", 0.0).mean()),
        "latest_panel_cum_fallback_ratio": float(numeric_series_or_default(latest_panel, "fund_ttm_cum_fallback_used", 0.0).mean()),
        "latest_panel_backfill_ratio": float(numeric_series_or_default(latest_panel, "fund_ttm_backfill_used", 0.0).mean()),
        "latest_panel_source_counts": latest_panel.get("source", pd.Series(dtype=str)).fillna("unknown").astype(str).value_counts().to_dict(),
        "latest_panel_ttm_coverage": {
            "revenues_ttm": float(latest_panel["revenues_ttm"].notna().mean()) if "revenues_ttm" in latest_panel.columns else 0.0,
            "gross_profit_ttm": float(latest_panel["gross_profit_ttm"].notna().mean()) if "gross_profit_ttm" in latest_panel.columns else 0.0,
            "op_income_ttm": float(latest_panel["op_income_ttm"].notna().mean()) if "op_income_ttm" in latest_panel.columns else 0.0,
            "op_margin_ttm": float(latest_panel["op_margin_ttm"].notna().mean()) if "op_margin_ttm" in latest_panel.columns else 0.0,
            "net_income_ttm": float(latest_panel["net_income_ttm"].notna().mean()) if "net_income_ttm" in latest_panel.columns else 0.0,
            "gross_margins": float(latest_panel["gross_margins"].notna().mean()) if "gross_margins" in latest_panel.columns else 0.0,
            "operating_margins": float(latest_panel["operating_margins"].notna().mean()) if "operating_margins" in latest_panel.columns else 0.0,
        },
        "latest_panel_growth_coverage": {
            "sales_growth_yoy": float(latest_panel["sales_growth_yoy"].notna().mean()) if "sales_growth_yoy" in latest_panel.columns else 0.0,
            "sales_cagr_3y": float(latest_panel["sales_cagr_3y"].notna().mean()) if "sales_cagr_3y" in latest_panel.columns else 0.0,
            "sales_cagr_5y": float(latest_panel["sales_cagr_5y"].notna().mean()) if "sales_cagr_5y" in latest_panel.columns else 0.0,
            "op_income_growth_yoy": float(latest_panel["op_income_growth_yoy"].notna().mean()) if "op_income_growth_yoy" in latest_panel.columns else 0.0,
            "op_income_cagr_3y": float(latest_panel["op_income_cagr_3y"].notna().mean()) if "op_income_cagr_3y" in latest_panel.columns else 0.0,
            "op_income_cagr_5y": float(latest_panel["op_income_cagr_5y"].notna().mean()) if "op_income_cagr_5y" in latest_panel.columns else 0.0,
            "net_income_growth_yoy": float(latest_panel["net_income_growth_yoy"].notna().mean()) if "net_income_growth_yoy" in latest_panel.columns else 0.0,
            "net_income_cagr_3y": float(latest_panel["net_income_cagr_3y"].notna().mean()) if "net_income_cagr_3y" in latest_panel.columns else 0.0,
            "net_income_cagr_5y": float(latest_panel["net_income_cagr_5y"].notna().mean()) if "net_income_cagr_5y" in latest_panel.columns else 0.0,
            "ocf_growth_yoy": float(latest_panel["ocf_growth_yoy"].notna().mean()) if "ocf_growth_yoy" in latest_panel.columns else 0.0,
            "ocf_cagr_3y": float(latest_panel["ocf_cagr_3y"].notna().mean()) if "ocf_cagr_3y" in latest_panel.columns else 0.0,
            "ocf_cagr_5y": float(latest_panel["ocf_cagr_5y"].notna().mean()) if "ocf_cagr_5y" in latest_panel.columns else 0.0,
        },
        "latest_panel_history_depth": {
            "quarters_available_median": float(hist_depth.median()),
            "quarters_available_p25": float(hist_depth.quantile(0.25)),
            "quarters_available_p75": float(hist_depth.quantile(0.75)),
            "five_year_history_ratio": float(hist_depth.ge(20).fillna(False).mean()),
        },
    }

    if monthly is None or monthly.empty:
        pd.DataFrame().to_csv(missing_path, index=False)
        summary["monthly_empty"] = True
        summary_path.write_text(json.dumps(summary, indent=2))
        return {
            "fundamental_collection_audit": summary_path,
            "fundamental_collection_missing_latest": missing_path,
            "fundamental_panel_latest_snapshot": panel_path,
        }

    d = monthly.copy()
    d["rebalance_date"] = pd.to_datetime(d["rebalance_date"], errors="coerce")
    latest_dt = d["rebalance_date"].max()
    latest = d[d["rebalance_date"] == latest_dt].copy() if pd.notna(latest_dt) else d.copy()
    latest["accepted"] = datetime_series_or_default(latest, "accepted")
    latest["fund_effective_accepted"] = datetime_series_or_default(latest, "fund_effective_accepted")
    latest["fund_report_age_days"] = (
        latest["rebalance_date"] - latest["fund_effective_accepted"]
    ).dt.days
    latest["fund_missing_count"] = pd.concat(
        [
            numeric_series_or_default(latest, "revenues_ttm", np.nan).isna().astype(float),
            numeric_series_or_default(latest, "op_margin_ttm", np.nan).isna().astype(float),
            numeric_series_or_default(latest, "net_income_ttm", np.nan).isna().astype(float),
        ],
        axis=1,
    ).sum(axis=1)

    missing_keep = [
        "ticker",
        "Name",
        "sector",
        "cik10",
        "rebalance_date",
        "fund_join_status",
        "fund_missing_count",
        "fund_panel_raw_flow_4q_cov_mean",
        "fund_panel_ttm_ready",
        "fund_history_quarters_available",
        "fund_ttm_cum_fallback_used",
        "fund_ttm_backfill_used",
        "fund_ttm_fallback_used",
        "fund_ttm_fallback_age_days",
        "fund_report_age_days",
        "accepted",
        "fund_effective_accepted",
        "fund_effective_period",
        "sales_cagr_3y",
        "sales_cagr_5y",
        "op_income_cagr_3y",
        "op_income_cagr_5y",
        "net_income_cagr_3y",
        "net_income_cagr_5y",
        "revenues_ttm",
        "op_income_ttm",
        "op_margin_ttm",
        "net_income_ttm",
        "ep_ttm",
        "sp_ttm",
        "fcfy_ttm",
        "gross_margins",
        "operating_margins",
        "earnings_growth_final",
        "forward_pe_final",
        "peg_final",
    ]
    for c in missing_keep:
        if c not in latest.columns:
            latest[c] = np.nan
    latest_missing = latest[
        latest["fund_missing_count"] > 0
    ][missing_keep].sort_values(
        ["fund_missing_count", "fund_join_status", "fund_panel_raw_flow_4q_cov_mean"],
        ascending=[False, True, True],
    )
    latest_missing.to_csv(missing_path, index=False)

    summary["monthly_empty"] = False
    summary["latest_rebalance_date"] = str(pd.Timestamp(latest_dt).date()) if pd.notna(latest_dt) else None
    summary["latest_rows"] = int(len(latest))
    summary["latest_join_status_counts"] = latest.get("fund_join_status", pd.Series(dtype=str)).fillna("unknown").astype(str).value_counts().to_dict()
    summary["latest_missing_rows"] = int(len(latest_missing))
    using_normalized_latest = latest_normalized is not None and not latest_normalized.empty
    latest_cov_view = latest_normalized.copy() if using_normalized_latest else latest.copy()
    summary["latest_coverage_basis"] = "normalized_latest_snapshot" if using_normalized_latest else "raw_latest_monthly"
    summary["latest_critical_coverage"] = {
        "revenues_ttm": float(numeric_series_or_default(latest_cov_view, "revenues_ttm", np.nan).notna().mean()),
        "op_margin_ttm": float(numeric_series_or_default(latest_cov_view, "op_margin_ttm", np.nan).notna().mean()),
        "net_income_ttm": float(numeric_series_or_default(latest_cov_view, "net_income_ttm", np.nan).notna().mean()),
        "earnings_growth_final": float(numeric_series_or_default(latest_cov_view, "earnings_growth_final", np.nan).notna().mean()),
        "forward_pe_final": float(numeric_series_or_default(latest_cov_view, "forward_pe_final", np.nan).notna().mean()),
        "peg_final": float(numeric_series_or_default(latest_cov_view, "peg_final", np.nan).notna().mean()),
        "gross_margins": float(numeric_series_or_default(latest_cov_view, "gross_margins", np.nan).notna().mean()),
        "operating_margins": float(numeric_series_or_default(latest_cov_view, "operating_margins", np.nan).notna().mean()),
    }
    summary["latest_comprehensive_coverage"] = {
        c: float(numeric_series_or_default(latest_cov_view, c, np.nan).notna().mean()) if c in latest_cov_view.columns else 0.0
        for c in COMPREHENSIVE_FUNDAMENTAL_COVERAGE_COLUMNS
    }
    summary["latest_comprehensive_coverage_mean"] = float(
        np.nanmean(list(summary["latest_comprehensive_coverage"].values()))
    ) if summary["latest_comprehensive_coverage"] else 0.0
    summary["latest_median_report_age_days"] = float(pd.to_numeric(latest["fund_report_age_days"], errors="coerce").median()) if len(latest) else np.nan
    summary_path.write_text(json.dumps(summary, indent=2))
    return {
        "fundamental_collection_audit": summary_path,
        "fundamental_collection_missing_latest": missing_path,
        "fundamental_panel_latest_snapshot": panel_path,
    }


def build_fund_panel_for_ciks(
    cfg: EngineConfig,
    paths: dict[str, Path],
    cik_list: list[str],
    quarters_to_fetch: int,
) -> pd.DataFrame:
    all_rows = []
    qlist = quarter_list_last_n(quarters_to_fetch)
    for y, q in qlist:
        zp = download_fsds_zip(cfg, paths, y, q)
        if zp is None:
            continue
        try:
            sub, num = read_fsds_tables(zp)
        except Exception:
            continue
        sub = prep_sub(sub)
        num = prep_num(num)

        sub = sub[sub["cik"].isin(cik_list)]
        if sub.empty:
            continue

        num = num[num["adsh"].isin(sub["adsh"].unique())]
        num = num[num["tag"].isin(NEEDED_TAGS)]
        if num.empty:
            continue

        merged = num.merge(sub[["adsh", "cik", "period", "fy", "fp", "accepted", "form"]], on="adsh", how="left")
        merged["tag"] = merged["tag"].map(FSDS_TAG_CANON).fillna(merged["tag"])
        bal = merged[merged["tag"].isin(BAL_TAGS)].copy()
        flow = merged[merged["tag"].isin(FLOW_TAGS)].copy()

        bal["qtrs0"] = (bal["qtrs"].fillna(0) == 0).astype(int)
        bal = bal.sort_values(["cik", "period", "tag", "qtrs0", "accepted"], ascending=[True, True, True, False, False])
        bal = bal.drop_duplicates(["cik", "period", "tag"], keep="first")

        flow = flow[flow["qtrs"].fillna(1).between(1, 4)]
        if not flow.empty:
            flow = quarterly_flow_from_ytd(flow)
            flow = flow.sort_values(["cik", "period", "tag", "accepted"], ascending=[True, True, True, False])
            flow = flow.drop_duplicates(["cik", "period", "tag"], keep="first")

        def pivot_wide(d: pd.DataFrame, val_col: str) -> pd.DataFrame:
            if d.empty:
                return pd.DataFrame(columns=["cik", "period"])
            p = d.pivot_table(index=["cik", "period"], columns="tag", values=val_col, aggfunc="last").reset_index()
            p.columns = [c if isinstance(c, str) else str(c) for c in p.columns]
            return p

        acc = sub[["cik", "period", "accepted"]].dropna()
        acc = acc.sort_values(["cik", "period", "accepted"]).drop_duplicates(["cik", "period"], keep="last")

        wide = pivot_wide(bal, "value").merge(pivot_wide(flow, "flow"), on=["cik", "period"], how="outer")
        wide = wide.merge(acc, on=["cik", "period"], how="left")
        wide["asof_quarter"] = f"{y}Q{q}"
        all_rows.append(wide)

    panel = pd.concat(all_rows, ignore_index=True) if all_rows else pd.DataFrame()
    if panel.empty:
        return panel

    panel = panel.rename(columns={v: k for k, v in FSDS_TAGS.items()})
    return recompute_fund_panel_derived_columns(
        panel,
        ffill_quarters=cfg.fund_ttm_ffill_quarters,
        balance_ffill_quarters=cfg.fund_balance_ffill_quarters,
    )


def build_yfinance_quarterly_panel(
    cfg: EngineConfig,
    paths: dict[str, Path],
    ticker_cik_map: dict[str, str],
    existing_panel: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """Build yfinance quarterly panel for tickers with poor SEC coverage."""
    if not cfg.yf_quarterly_cache_enabled or not ticker_cik_map:
        return pd.DataFrame()

    cache_dir = paths["cache_misc"] / "yf_quarterly_cache"
    safe_mkdir(cache_dir)

    refresh_cut = pd.Timestamp.utcnow().tz_localize(None) - pd.Timedelta(days=cfg.yf_quarterly_refresh_days)

    # Prioritize tickers with poor existing coverage
    poor_coverage_tickers = []
    ok_tickers = []
    existing_ciks_with_data = set()
    if existing_panel is not None and not existing_panel.empty and "cik" in existing_panel.columns:
        cik_counts = existing_panel.groupby("cik")["period"].nunique()
        existing_ciks_with_data = set(cik_counts[cik_counts >= 8].index.astype(str))

    for ticker, cik in ticker_cik_map.items():
        if str(cik) in existing_ciks_with_data:
            ok_tickers.append(ticker)
        else:
            poor_coverage_tickers.append(ticker)

    ordered_tickers = (
        poor_coverage_tickers
        if bool(getattr(cfg, "yf_quarterly_refresh_only_poor_coverage", True))
        else poor_coverage_tickers + ok_tickers
    )

    tickers_to_fetch = []
    for ticker in ordered_tickers:
        safe_name = ticker.replace("/", "_").replace("\\", "_")
        cache_path = cache_dir / f"{safe_name}.parquet"
        if cache_path.exists():
            try:
                mtime = pd.Timestamp(cache_path.stat().st_mtime, unit="s")
                if mtime >= refresh_cut:
                    continue
            except Exception:
                pass
        tickers_to_fetch.append(ticker)

    tickers_to_fetch = tickers_to_fetch[: cfg.yf_quarterly_max_tickers_per_run]

    if tickers_to_fetch:
        log(f"[yf_quarterly] Fetching {len(tickers_to_fetch)} tickers ({len(poor_coverage_tickers)} low-coverage) ...")
        for i, ticker in enumerate(tickers_to_fetch, 1):
            safe_name = ticker.replace("/", "_").replace("\\", "_")
            cache_path = cache_dir / f"{safe_name}.parquet"
            try:
                df = fetch_yfinance_quarterly_statements(ticker)
                if not df.empty:
                    df.to_parquet(cache_path, index=False)
                else:
                    pd.DataFrame(columns=["period"]).to_parquet(cache_path, index=False)
            except Exception as e:
                log(f"[yf_quarterly] {ticker}: {e}")
            if i % 20 == 0:
                time.sleep(max(cfg.yf_sleep, 0.05))
                log(f"[yf_quarterly] {i}/{len(tickers_to_fetch)} done")
        log(f"[yf_quarterly] Fetch complete: {len(tickers_to_fetch)} tickers")

    # Load all cached data
    all_rows = []
    for ticker, cik in ticker_cik_map.items():
        safe_name = ticker.replace("/", "_").replace("\\", "_")
        cache_path = cache_dir / f"{safe_name}.parquet"
        if not cache_path.exists():
            continue
        try:
            df = pd.read_parquet(cache_path)
            if df.empty or "period" not in df.columns or len(df) == 0:
                continue
            if df.columns.tolist() == ["period"]:
                continue
            df["cik"] = str(cik)
            df["source"] = "yfinance"
            df["asof_quarter"] = "yfinance"
            all_rows.append(df)
        except Exception:
            continue

    if not all_rows:
        log("[yf_quarterly] No yfinance quarterly data loaded")
        return pd.DataFrame()

    panel = pd.concat(all_rows, ignore_index=True)
    panel["period"] = pd.to_datetime(panel["period"], errors="coerce")
    panel["accepted"] = pd.to_datetime(panel["accepted"], errors="coerce")
    n_ciks = panel["cik"].nunique()
    n_rows = len(panel)
    log(f"[yf_quarterly] Loaded {n_rows} rows for {n_ciks} CIKs")
    return recompute_fund_panel_derived_columns(
        panel,
        ffill_quarters=cfg.fund_ttm_ffill_quarters,
        balance_ffill_quarters=cfg.fund_balance_ffill_quarters,
    )


def select_fund_panel_refresh_ciks(
    cfg: EngineConfig,
    paths: dict[str, Path],
    base: pd.DataFrame,
    cik_list: list[str],
) -> list[str]:
    """Refresh only the stale or missing CIK subset when cached coverage is already healthy."""
    norm_ciks = normalize_cik_list(cik_list)
    if not norm_ciks:
        return []
    if base is None or base.empty or "cik" not in base.columns:
        return norm_ciks

    base_ciks = set(normalize_cik_list(base.get("cik", pd.Series(dtype=str)).tolist()))
    refresh_ciks: list[str] = []
    refresh_days = max(int(cfg.companyfacts_refresh_days), 0)
    for cik in norm_ciks:
        if cik not in base_ciks:
            refresh_ciks.append(cik)
            continue
        if refresh_days <= 0:
            refresh_ciks.append(cik)
            continue
        if not is_cache_fresh(companyfacts_cache_file(paths, cik), refresh_days):
            refresh_ciks.append(cik)
    return refresh_ciks


def load_or_update_fund_panel(
    cfg: EngineConfig,
    paths: dict[str, Path],
    cik_list: list[str],
    ticker_cik_map: Optional[dict[str, str]] = None,
) -> pd.DataFrame:
    latest_path = paths["feature_store"] / "fund_panel_latest.parquet"
    base = pd.read_parquet(latest_path) if latest_path.exists() else pd.DataFrame()
    base_cov = panel_latest_flow_coverage(base) if not base.empty else np.nan
    repair_quarters = max(int(cfg.fsds_quarters_each_run), int(cfg.fund_panel_repair_quarters))
    refresh_ciks = cik_list
    if not base.empty and base_cov < 0.20:
        if cfg.force_full_fund_panel_rebuild:
            log("[WARN] Existing fund_panel coverage is too low; forcing full FSDS rebuild.")
            base = pd.DataFrame()
        else:
            if base_cov < 0.05:
                refresh_ciks = cik_list
                log(
                    f"[WARN] Existing fund_panel coverage is critically low ({base_cov:.1%}); "
                    "running broad repair across the full CIK set before resuming targeted refresh."
                )
            elif cfg.targeted_repair_only_weak_ciks:
                refresh_ciks = select_targeted_repair_ciks(cfg, base, cik_list)
            else:
                refresh_ciks = cik_list
            log(
                f"[WARN] Existing fund_panel coverage is too low ({base_cov:.1%}); "
                f"running repair refresh ({repair_quarters} quarters, "
                f"{len(refresh_ciks)}/{len(cik_list)} ciks) instead of full rebuild."
            )
    if not base.empty and pd.notna(base_cov) and base_cov >= 0.20 and not cfg.force_full_fund_panel_rebuild:
        refresh_ciks = select_fund_panel_refresh_ciks(cfg, paths, base, cik_list)
        if refresh_ciks:
            log(
                f"Fund panel incremental refresh: {len(refresh_ciks)}/{len(cik_list)} stale or missing CIKs "
                "selected for SEC/FSDS parsing."
            )
        else:
            log("Fund panel incremental refresh: reusing cached SEC/FSDS panel without broad reparsing.")

    q = cfg.fsds_quarters_each_run if not base.empty else cfg.fsds_quarters_backfill
    if not base.empty and pd.notna(base_cov) and base_cov < 0.20 and not cfg.force_full_fund_panel_rebuild:
        q = repair_quarters
    companyfacts_panel = build_companyfacts_panel_for_ciks(cfg, paths, refresh_ciks) if refresh_ciks else pd.DataFrame()
    fsds_panel = build_fund_panel_for_ciks(cfg, paths, refresh_ciks, q) if refresh_ciks else pd.DataFrame()
    new_panel = combine_fund_panels(companyfacts_panel, fsds_panel) if (not companyfacts_panel.empty or not fsds_panel.empty) else pd.DataFrame()
    if base.empty:
        panel = new_panel
    elif new_panel.empty:
        panel = base.copy()
    else:
        panel = combine_fund_panels(new_panel, base)
    # yfinance quarterly supplement: fills gaps where SEC data is missing
    if ticker_cik_map:
        yf_panel = build_yfinance_quarterly_panel(cfg, paths, ticker_cik_map, existing_panel=panel)
        if yf_panel is not None and not yf_panel.empty:
            panel = combine_fund_panels(panel, yf_panel)
    if panel.empty:
        return panel
    panel = recompute_fund_panel_derived_columns(
        panel,
        ffill_quarters=cfg.fund_ttm_ffill_quarters,
        balance_ffill_quarters=cfg.fund_balance_ffill_quarters,
    )
    panel.to_parquet(latest_path, index=False)
    return panel


def asof_join_fundamentals(
    base_df: pd.DataFrame,
    panel: pd.DataFrame,
    ttm_fallback_max_age_days: int = 180,
) -> pd.DataFrame:
    if base_df.empty:
        return base_df
    if panel is None or panel.empty:
        for c in ["accepted"] + CORE_FUNDAMENTAL_COLUMNS + FUND_TTM_FALLBACK_COLUMNS + [
            "fund_ttm_fallback_accepted",
            "fund_ttm_fallback_period",
            "fund_ttm_fallback_age_days",
            "fund_ttm_fallback_used",
            "fund_effective_accepted",
            "fund_effective_period",
            "fund_effective_age_days",
        ]:
            if c not in base_df.columns:
                base_df[c] = np.nan
        return base_df

    d = base_df.copy()
    d["rebalance_date"] = pd.to_datetime(d["rebalance_date"], errors="coerce")
    panel = panel.copy()
    panel["cik"] = normalize_cik_series(panel["cik"], index=panel.index)
    panel["accepted"] = pd.to_datetime(panel["accepted"], errors="coerce")
    panel["period"] = datetime_series_or_default(panel, "period")
    panel = panel.sort_values(["cik", "accepted"])
    ttm_fallback_cols = [c for c in FUND_TTM_FALLBACK_COLUMNS if c in panel.columns]
    ttm_meta_cols = [
        c
        for c in ["accepted", "period", "source", "asof_quarter", "fund_ttm_ready", "fund_ttm_backfill_used"]
        if c in panel.columns
    ]
    max_age_days = max(int(ttm_fallback_max_age_days), 1)

    chunks = []
    for cik, g in d.groupby("cik10", sort=False):
        if pd.isna(cik):
            gg = g.copy()
            for c in panel.columns:
                if c not in gg.columns:
                    gg[c] = np.nan
            chunks.append(gg)
            continue
        p = panel[panel["cik"] == str(cik)]
        gg = g.sort_values("rebalance_date").copy()
        if p.empty:
            for c in panel.columns:
                if c not in gg.columns:
                    gg[c] = np.nan
            chunks.append(gg)
            continue

        left = gg.reset_index().rename(columns={"index": "_base_idx"})
        m = pd.merge_asof(
            left,
            p.sort_values("accepted"),
            left_on="rebalance_date",
            right_on="accepted",
            direction="backward",
        )
        m = m.set_index("_base_idx").sort_index()

        p_ttm = p[numeric_series_or_default(p, "fund_ttm_ready", 0.0) > 0].copy()
        if not p_ttm.empty and ttm_fallback_cols:
            fb = pd.merge_asof(
                left[["_base_idx", "rebalance_date"]],
                p_ttm[ttm_meta_cols + ttm_fallback_cols].sort_values("accepted"),
                left_on="rebalance_date",
                right_on="accepted",
                direction="backward",
            ).set_index("_base_idx")
            fb = fb.rename(columns={c: f"ttm_fb_{c}" for c in fb.columns if c != "rebalance_date"})
            fb = fb.drop(columns=["rebalance_date"], errors="ignore")
            m = m.join(fb.reindex(m.index))

            fb_accepted = datetime_series_or_default(m, "ttm_fb_accepted")
            fb_age = (pd.to_datetime(m["rebalance_date"], errors="coerce") - fb_accepted).dt.days
            valid_fb = fb_accepted.notna() & fb_age.ge(0) & fb_age.le(max_age_days)
            fallback_used = pd.Series(False, index=m.index, dtype=bool)
            for c in ttm_fallback_cols:
                if c not in m.columns:
                    m[c] = np.nan
                fb_col = f"ttm_fb_{c}"
                if fb_col not in m.columns:
                    continue
                current = pd.to_numeric(m[c], errors="coerce")
                fallback = pd.to_numeric(m[fb_col], errors="coerce")
                use_fb = valid_fb & current.isna() & fallback.notna()
                if use_fb.any():
                    m.loc[use_fb, c] = fallback.loc[use_fb]
                    fallback_used = fallback_used | use_fb

            m["fund_ttm_fallback_accepted"] = fb_accepted.where(valid_fb, pd.NaT)
            m["fund_ttm_fallback_period"] = datetime_series_or_default(m, "ttm_fb_period").where(valid_fb, pd.NaT)
            m["fund_ttm_fallback_age_days"] = fb_age.where(valid_fb, np.nan)
            m["fund_ttm_fallback_used"] = fallback_used.astype(float)
            m["fund_effective_accepted"] = datetime_series_or_default(m, "accepted")
            m["fund_effective_period"] = datetime_series_or_default(m, "period")
            m["fund_effective_age_days"] = (
                pd.to_datetime(m["rebalance_date"], errors="coerce") - m["fund_effective_accepted"]
            ).dt.days
            use_effective = fallback_used & pd.to_datetime(m["fund_ttm_fallback_accepted"], errors="coerce").notna()
            if use_effective.any():
                m.loc[use_effective, "fund_effective_accepted"] = pd.to_datetime(
                    m.loc[use_effective, "fund_ttm_fallback_accepted"],
                    errors="coerce",
                )
                m.loc[use_effective, "fund_effective_period"] = pd.to_datetime(
                    m.loc[use_effective, "fund_ttm_fallback_period"],
                    errors="coerce",
                )
                m.loc[use_effective, "fund_effective_age_days"] = pd.to_numeric(
                    m.loc[use_effective, "fund_ttm_fallback_age_days"],
                    errors="coerce",
                )
        else:
            m["fund_ttm_fallback_accepted"] = pd.NaT
            m["fund_ttm_fallback_period"] = pd.NaT
            m["fund_ttm_fallback_age_days"] = np.nan
            m["fund_ttm_fallback_used"] = 0.0
            m["fund_effective_accepted"] = datetime_series_or_default(m, "accepted")
            m["fund_effective_period"] = datetime_series_or_default(m, "period")
            m["fund_effective_age_days"] = (
                pd.to_datetime(m["rebalance_date"], errors="coerce") - m["fund_effective_accepted"]
            ).dt.days
        m = m.drop(columns=[c for c in m.columns if c.startswith("ttm_fb_")], errors="ignore")
        chunks.append(m)
    out = pd.concat(chunks, ignore_index=True)
    if "accepted" in out.columns and "fund_accepted" not in out.columns:
        out["fund_accepted"] = pd.to_datetime(out["accepted"], errors="coerce")
    if "period" in out.columns and "fund_period" not in out.columns:
        out["fund_period"] = pd.to_datetime(out["period"], errors="coerce")
    if "source" in out.columns and "fund_source" not in out.columns:
        out["fund_source"] = out["source"]
    if "asof_quarter" in out.columns and "fund_asof_quarter" not in out.columns:
        out["fund_asof_quarter"] = out["asof_quarter"]
    return out


def build_universe_monthly(cfg: dict | EngineConfig) -> pd.DataFrame:
    cfg = to_cfg(cfg)
    paths = get_paths(cfg)
    log("Phase 1/2: building monthly universe ...")

    hist_membership = load_historical_universe_membership(cfg, paths)
    candidates = build_candidate_universe(cfg, paths)
    tickers = candidates["ticker"].dropna().unique().tolist()
    ensure_prices_cached_incremental(cfg, paths, tickers)

    cik_list = normalize_cik_list(candidates["cik10"].tolist())
    ticker_cik_map = dict(
        candidates.dropna(subset=["ticker", "cik10"])
        .drop_duplicates("ticker")[["ticker", "cik10"]]
        .values.tolist()
    )
    panel = load_or_update_fund_panel(cfg, paths, cik_list, ticker_cik_map=ticker_cik_map)
    trend_panel = panel.copy() if panel is not None else pd.DataFrame()
    write_fund_panel_recent_flow_report(paths, panel)

    rebal_dates = month_end_trading_days(cfg.start_date, cfg.end_date)
    if not rebal_dates:
        raise RuntimeError("No monthly rebalance dates were generated.")

    all_rows = []
    loaded_px_cnt = 0
    for i, t in enumerate(tickers, start=1):
        px = load_px(paths, t)
        if px is None or px.empty:
            continue
        loaded_px_cnt += 1
        tech_daily = compute_daily_tech_table(px)
        if tech_daily.empty:
            continue
        month_df = tech_daily.reindex(pd.DatetimeIndex(rebal_dates), method="ffill").reset_index()
        if "rebalance_date" not in month_df.columns:
            first_col = month_df.columns[0]
            month_df = month_df.rename(columns={first_col: "rebalance_date"})
        month_df["ticker"] = t
        all_rows.append(month_df)
        if i % 150 == 0:
            time.sleep(cfg.yf_sleep)

    if not all_rows:
        raise RuntimeError(
            "No monthly tech rows built. "
            f"loaded_price_caches={loaded_px_cnt}, tickers={len(tickers)}. "
            "Check cache_prices folder and clear yf_fail_tickers.json before retry."
        )

    monthly = pd.concat(all_rows, ignore_index=True)
    monthly = monthly.merge(candidates, on="ticker", how="left")
    monthly["cik10"] = normalize_cik_series(monthly["cik10"], index=monthly.index)
    if "universe_source" in monthly.columns:
        monthly["universe_source"] = monthly["universe_source"].fillna(
            "historical_membership_file" if not hist_membership.empty else "current_constituents_proxy"
        )
    else:
        monthly["universe_source"] = "historical_membership_file" if not hist_membership.empty else "current_constituents_proxy"
    if not hist_membership.empty:
        monthly = apply_historical_membership_filter(monthly, hist_membership)
    monthly = asof_join_fundamentals(monthly, panel, cfg.fund_ttm_fallback_max_age_days)
    monthly = merge_trend_features_into_monthly(monthly, trend_panel)
    monthly = attach_fund_panel_join_diagnostics(monthly, panel)
    write_stage_coverage_report(paths, "fund_panel_latest", panel, CORE_FUNDAMENTAL_COLUMNS + ["sales_growth_yoy", "op_margin_ttm", "roe_proxy"])

    monthly["mktcap"] = pd.to_numeric(monthly["px"], errors="coerce") * pd.to_numeric(monthly.get("shares"), errors="coerce")
    if monthly["mktcap"].notna().mean() < 0.30:
        log("[WARN] FSDS shares coverage is low; applying bounded Yahoo marketCap proxy fallback.")
        mc = ensure_mktcap_proxy(cfg, paths, monthly["ticker"].dropna().unique().tolist(), max_new=600)
        if not mc.empty:
            monthly = monthly.merge(mc[["ticker", "mktcap_proxy"]], on="ticker", how="left")
            monthly["mktcap"] = monthly["mktcap"].fillna(pd.to_numeric(monthly["mktcap_proxy"], errors="coerce"))
            if "market_cap_live" not in monthly.columns:
                monthly["market_cap_live"] = np.nan
            monthly["market_cap_live"] = pd.to_numeric(monthly["market_cap_live"], errors="coerce").fillna(
                pd.to_numeric(monthly["mktcap_proxy"], errors="coerce")
            )
    mktcap_cov = float(monthly["mktcap"].notna().mean())
    use_mktcap_filter = mktcap_cov >= 0.25
    if use_mktcap_filter:
        monthly["mktcap"] = monthly["mktcap"].where(monthly["mktcap"] >= cfg.min_mktcap, np.nan)
        monthly["size_metric"] = monthly["mktcap"]
    else:
        log(f"[WARN] mktcap coverage too low ({mktcap_cov:.2%}); falling back to dollar-vol size metric.")
        monthly["size_metric"] = pd.to_numeric(monthly["dollar_vol_20d"], errors="coerce")

    base_mask = (
        (monthly["px"].fillna(0) >= cfg.min_price)
        & (monthly["dollar_vol_20d"].fillna(0) >= cfg.min_dollar_vol_20d)
        & (monthly["vol_252d"].fillna(9e9) <= cfg.max_vol_252)
        & (monthly["dd_1y"].fillna(9e9) <= cfg.max_dd_1y)
    )
    if use_mktcap_filter:
        base_mask &= monthly["mktcap"].notna()
    monthly = monthly[base_mask].copy()
    monthly = monthly.sort_values(["rebalance_date", "size_metric"], ascending=[True, False])
    monthly["rank_size"] = monthly.groupby("rebalance_date")["size_metric"].rank(method="first", ascending=False)
    monthly = monthly[monthly["rank_size"] <= cfg.universe_size].copy()

    for _rs_period, _rs_col in [("mom_1m", "rs_sector_1m"), ("mom_3m", "rs_sector_3m"), ("mom_6m", "rs_sector_6m"), ("mom_12m", "rs_sector_12m")]:
        if _rs_period in monthly.columns:
            monthly[_rs_col] = monthly.groupby(["rebalance_date", "sector"])[_rs_period].transform(lambda x: x - np.nanmean(x.values))
            monthly[_rs_col] = pd.to_numeric(monthly[_rs_col], errors="coerce").fillna(0.0)

    # Phase 2.3: enrich the monthly frame with yfinance industry metadata so
    # downstream features can compute industry-level relative strength and
    # leadership.  Cache lives in `cache_misc/yf_industry_metadata.parquet`;
    # we only refresh tickers older than `industry_metadata_refresh_days`.
    # A/B toggle: PHASE_PHASE2_INDUSTRY_ENABLED=0 skips the yfinance fetch
    # and the three industry-RS / leadership / rotation builders, but still
    # writes zero placeholder columns so downstream sleeve composites keep
    # their column schema.
    if phase_is_enabled("phase2_industry", default=True):
        industry_meta = ensure_industry_metadata(
            cfg,
            paths,
            monthly["ticker"].dropna().astype(str).unique().tolist(),
            max_new=int(getattr(cfg, "industry_metadata_max_new_per_run", 250)),
            refresh_days=int(getattr(cfg, "industry_metadata_refresh_days", 60)),
        )
        monthly = attach_industry_metadata(monthly, industry_meta)
        monthly = add_industry_relative_strength(monthly)
        monthly = compute_oneil_leadership_score(monthly)
        monthly = add_industry_rotation_signal(monthly)
    else:
        log(
            "[phase2_industry] disabled via env PHASE_PHASE2_INDUSTRY_ENABLED=0 "
            "— skipping yfinance metadata fetch + industry RS / leadership / rotation."
        )
        for _p2_str_col in ("industry", "industry_group", "subindustry"):
            if _p2_str_col not in monthly.columns:
                monthly[_p2_str_col] = ""
        _p2_zero_cols = (
            "rs_industry_1m", "rs_industry_3m", "rs_industry_6m", "rs_industry_12m",
            "rs_industry_group_1m", "rs_industry_group_3m",
            "rs_industry_group_6m", "rs_industry_group_12m",
            "industry_mom_mean_3m", "industry_mom_mean_6m", "industry_mom_mean_12m",
            "industry_group_mom_mean_3m", "industry_group_mom_mean_6m",
            "industry_group_mom_mean_12m",
            "industry_breadth_above_ma200", "industry_group_breadth_above_ma200",
            "industry_group_strength_score", "industry_within_leader_rank",
            "oneil_leadership_score", "industry_rotation_signal",
        )
        for _p2_col in _p2_zero_cols:
            if _p2_col not in monthly.columns:
                monthly[_p2_col] = 0.0
    # -----------------------------------------------------------------
    # Phase 5: sub-industry leader/laggard (PHASE_ROADMAP §2.5).
    # Depends on industry_group + industry_group_strength_score from
    # Phase 2, so it must come after the Phase 2 block above. Toggle
    # pattern mirrors Phase 2: when disabled via env var, zero-fill the
    # three Phase 5 columns so downstream sleeve code + keep_cols
    # whitelist (Invariant #8) never see them as missing.
    # -----------------------------------------------------------------
    if phase_is_enabled("phase5_leader_laggard", default=False):
        _p5_enabled_cfg = bool(getattr(cfg, "sub_industry_leader_laggard_enabled", True))
        if _p5_enabled_cfg:
            _p5_min_grp = int(getattr(cfg, "sub_industry_min_group_size", 6))
            _p5_gap_thr = float(getattr(cfg, "sub_industry_leader_gap_threshold", 0.8))
            monthly = add_sub_industry_leader_laggard_signals(
                monthly,
                min_group_size=_p5_min_grp,
                gap_threshold=_p5_gap_thr,
            )
        else:
            log("[phase5_leader_laggard] disabled via cfg — zero-filling columns.")
            for _p5_col in PHASE5_LEADER_LAGGARD_COLUMNS:
                if _p5_col not in monthly.columns:
                    monthly[_p5_col] = 0.0
    else:
        log(
            "[phase5_leader_laggard] disabled via env PHASE_PHASE5_LEADER_LAGGARD_ENABLED=0 "
            "— skipping sub-industry leader/laggard signals."
        )
        for _p5_col in PHASE5_LEADER_LAGGARD_COLUMNS:
            if _p5_col not in monthly.columns:
                monthly[_p5_col] = 0.0
    # -----------------------------------------------------------------
    # Phase 8b.1: long-lookback momentum composites.
    # mom_18m / mom_24m / mom_36m are already computed in
    # `compute_price_features`. Here we build the two cross-sectional
    # composites that the sleeve composites will read:
    #   multi_year_winner_score: weighted blend of mom_12m / 24m / 36m
    #                            (cross-sectional rank-z). Rewards names
    #                            with compound multi-year uptrends (NVDA
    #                            / AVGO / MU pattern).
    #   persistence_trend_24m:   binary flag (1 if mom_12m > 0.15 AND
    #                            mom_24m > 0.30 AND mom_36m > 0.50, else 0).
    #                            Pure confirmation that the trend isn't
    #                            a one-year pop but a sustained multi-year
    #                            rally.
    # Toggle: PHASE_PHASE8B_LONG_LOOKBACK_ENABLED env var (default True)
    # AND cfg.phase8b_long_lookback_enabled (default True).
    # When disabled, zero-fill so downstream sleeve composites never see
    # a missing column.
    # -----------------------------------------------------------------
    _phase8b_long_env = phase_is_enabled("phase8b_long_lookback", default=True)
    _phase8b_long_cfg = bool(getattr(cfg, "phase8b_long_lookback_enabled", True)) if cfg is not None else True
    _phase8b_long_active = bool(_phase8b_long_env and _phase8b_long_cfg)

    if _phase8b_long_active:
        # Multi-year winner score: weighted blend of z-scored multi-year momentum.
        # Weights: 0.50 * mom_12m + 0.80 * mom_24m + 0.60 * mom_36m
        # (heaviest on 24m to capture the NVDA-style 2-year trend phase).
        _mom_12m_num = pd.to_numeric(monthly.get("mom_12m", 0.0), errors="coerce")
        _mom_24m_num = pd.to_numeric(monthly.get("mom_24m", 0.0), errors="coerce")
        _mom_36m_num = pd.to_numeric(monthly.get("mom_36m", 0.0), errors="coerce")

        def _xsec_z_on(col_series: pd.Series) -> pd.Series:
            """Cross-sectional robust z within each rebalance_date group."""
            def _z(x: pd.Series) -> pd.Series:
                arr = x.to_numpy(dtype=float)
                med = np.nanmedian(arr)
                mad = np.nanmedian(np.abs(arr - med))
                denom = 1.4826 * max(float(mad), max(abs(med) * 0.01, 1e-6))
                z = (arr - med) / denom
                return pd.Series(np.clip(z, -6.0, 6.0), index=x.index, dtype=float)
            return col_series.groupby(monthly["rebalance_date"]).transform(_z)

        _z_mom12 = _xsec_z_on(_mom_12m_num.fillna(0.0))
        _z_mom24 = _xsec_z_on(_mom_24m_num.fillna(0.0))
        _z_mom36 = _xsec_z_on(_mom_36m_num.fillna(0.0))
        # Blend: heaviest on 24m. Skip rows where mom_24m is NaN (first
        # 504 trading days of a ticker's history) so the composite doesn't
        # reward short-history names with bogus zeros.
        _blend_raw = (
            0.50 * _z_mom12.fillna(0.0)
            + 0.80 * _z_mom24.fillna(0.0)
            + 0.60 * _z_mom36.fillna(0.0)
        )
        # Mask: score is valid only if mom_24m has real data (not fillna).
        _valid_24m = _mom_24m_num.notna()
        monthly["multi_year_winner_score"] = _blend_raw.where(_valid_24m, 0.0).clip(lower=-6.0, upper=6.0)
        # Persistence flag: 1 if all three conditions met, 0 otherwise.
        # Thresholds chosen so that only names with genuine multi-year
        # uptrends get the flag (NVDA 2021-2024 pattern).
        monthly["persistence_trend_24m"] = (
            (_mom_12m_num > 0.15)
            & (_mom_24m_num > 0.30)
            & (_mom_36m_num > 0.50)
        ).astype(float)
    else:
        log(
            "[phase8b_long_lookback] disabled via env PHASE_PHASE8B_LONG_LOOKBACK_ENABLED=0 "
            "or cfg.phase8b_long_lookback_enabled=False — zero-filling composite columns."
        )
        if "multi_year_winner_score" not in monthly.columns:
            monthly["multi_year_winner_score"] = 0.0
        if "persistence_trend_24m" not in monthly.columns:
            monthly["persistence_trend_24m"] = 0.0

    # Ensure raw mom_18m/24m/36m columns exist (they might already be
    # populated from compute_price_features, but defensive-fill with 0
    # for any row where the ticker has < 756 days of history).
    for _p8b_col in ("mom_18m", "mom_24m", "mom_36m"):
        if _p8b_col not in monthly.columns:
            monthly[_p8b_col] = 0.0

    live_candidates = (
        monthly.sort_values(["rebalance_date", "dollar_vol_20d"], ascending=[False, False])["ticker"]
        .dropna()
        .astype(str)
        .unique()
        .tolist()[: cfg.max_live_refresh_tickers]
    )
    live_df = refresh_live_fundamentals(cfg, paths, live_candidates)
    if not live_df.empty and "market_cap_live" in live_df.columns:
        live_df["market_cap_live"] = pd.to_numeric(live_df["market_cap_live"], errors="coerce")
        live_df = live_df[
            live_df["market_cap_live"].isna() | (live_df["market_cap_live"] >= cfg.live_min_marketcap_proxy)
        ].copy()
    monthly = merge_live_fundamentals(monthly, live_df)
    sec13f = load_local_sec_actual_snapshots(cfg, paths, "13f")
    form345 = load_local_sec_actual_snapshots(cfg, paths, "345")
    monthly = merge_sec_actual_snapshots(monthly, sec13f, form345)
    monthly = compute_live_factor_columns(monthly, cfg)
    monthly = compute_latest_flow_factor_columns(monthly)
    monthly = merge_macro_regime_features(cfg, paths, monthly)
    monthly = merge_benchmark_relative_features(cfg, paths, monthly)
    monthly = merge_live_event_alert_features(cfg, paths, monthly)
    monthly = apply_latest_only_signal_guard(monthly)
    write_stage_coverage_report(
        paths,
        "universe_monthly",
        monthly,
        FUNDAMENTAL_COVERAGE_COLUMNS
        + TREND_TEMPLATE_COLUMNS
        + ["forward_value_score", "revision_score"]
        + SEC_13F_COLUMNS
        + SEC_FORM345_COLUMNS
        + MACRO_REGIME_COLUMNS
        + BENCHMARK_RELATIVE_COLUMNS
        + LIVE_EVENT_ALERT_COLUMNS,
    )
    latest_dt = pd.to_datetime(monthly["rebalance_date"], errors="coerce").max()
    latest_view = monthly[monthly["rebalance_date"] == latest_dt].copy() if pd.notna(latest_dt) else monthly.copy()
    latest_view_normalized = normalize_latest_fundamental_snapshot(
        cfg,
        paths,
        latest_view,
        clear_latest_only_signals=False,
        apply_statement_repair=True,
        add_fundamental_flags=True,
    )
    write_fundamental_join_diagnostics(paths, monthly)
    write_fundamental_collection_audit(paths, panel, monthly, latest_normalized=latest_view_normalized)
    log(
        "Universe snapshot: "
        f"source={latest_view.get('universe_source', pd.Series(dtype=str)).astype(str).mode().iloc[0] if not latest_view.empty and 'universe_source' in latest_view.columns and not latest_view.get('universe_source', pd.Series(dtype=str)).mode().empty else 'unknown'}, "
        f"latest_rows={len(latest_view)}, "
        f"candidate_tickers={monthly.get('ticker', pd.Series(dtype=str)).astype(str).nunique()}"
    )
    log_core_fundamental_coverage(latest_view_normalized, "Core fundamental coverage (latest universe)")
    if "core_fundamental_minimum_pass" in latest_view_normalized.columns and len(latest_view_normalized):
        log(
            "Core fundamental minimum pass rate (latest universe): "
            f"{float(pd.to_numeric(latest_view_normalized['core_fundamental_minimum_pass'], errors='coerce').fillna(0.0).mean()):.1%}"
        )
    monthly.to_parquet(paths["feature_store"] / "universe_monthly_latest.parquet", index=False)
    return monthly


def _sage_ols_residual(
    y: pd.Series,
    X: pd.DataFrame,
) -> pd.Series:
    """OLS residual: actual - predicted. Returns zeros on degenerate input."""
    try:
        y_arr = y.to_numpy(dtype=float)
        X_arr = np.column_stack([np.ones(len(X))] + [X[c].to_numpy(dtype=float) for c in X.columns])
        valid = np.isfinite(y_arr) & np.all(np.isfinite(X_arr), axis=1)
        if valid.sum() < max(len(X.columns) + 2, 10):
            return pd.Series(0.0, index=y.index)
        coef, *_ = np.linalg.lstsq(X_arr[valid], y_arr[valid], rcond=None)
        pred = X_arr @ coef
        resid = y_arr - pred
        out = pd.Series(resid, index=y.index, dtype=float)
        out.loc[~valid] = 0.0
        return out
    except Exception:
        return pd.Series(0.0, index=y.index)


def compute_valuation_residuals(d: pd.DataFrame) -> pd.DataFrame:
    """Compute sector-relative valuation residuals per rebalance_date × sage_sector group.
    Residual < 0 → cheaper than peers given fundamentals; > 0 → more expensive.
    Adds columns: val_residual_ep, val_residual_sp, val_residual_fcfy."""
    if "sage_sector" not in d.columns or "rebalance_date" not in d.columns:
        for c in ("val_residual_ep", "val_residual_sp", "val_residual_fcfy"):
            d[c] = 0.0
        return d

    residual_ep = pd.Series(np.nan, index=d.index, dtype=float)
    residual_sp = pd.Series(np.nan, index=d.index, dtype=float)
    residual_fcfy = pd.Series(np.nan, index=d.index, dtype=float)

    regressors_base = ["sales_cagr_best", "fcf_margin", "gross_margin_ttm", "net_margin"]
    quality_regs = ["roic_approx", "op_margin_ttm", "return_on_equity_effective"]

    for (rd, sc), grp in d.groupby(["rebalance_date", "sage_sector"], group_keys=False):
        if len(grp) < 8:
            residual_ep.loc[grp.index] = 0.0
            residual_sp.loc[grp.index] = 0.0
            residual_fcfy.loc[grp.index] = 0.0
            continue

        available_regs = [c for c in regressors_base + quality_regs if c in grp.columns]
        if not available_regs:
            residual_ep.loc[grp.index] = 0.0
            residual_sp.loc[grp.index] = 0.0
            residual_fcfy.loc[grp.index] = 0.0
            continue

        X_raw = grp[available_regs].copy()
        for c in available_regs:
            col_vals = pd.to_numeric(X_raw[c], errors="coerce")
            lo, hi = col_vals.quantile(0.05), col_vals.quantile(0.95)
            X_raw[c] = col_vals.clip(lo, hi).fillna(col_vals.median())

        if "ep_ttm" in grp.columns:
            y_ep = pd.to_numeric(grp["ep_ttm"], errors="coerce")
            residual_ep.loc[grp.index] = _sage_ols_residual(y_ep, X_raw)
        else:
            residual_ep.loc[grp.index] = 0.0

        if "sp_ttm" in grp.columns:
            y_sp = pd.to_numeric(grp["sp_ttm"], errors="coerce")
            residual_sp.loc[grp.index] = _sage_ols_residual(y_sp, X_raw)
        else:
            residual_sp.loc[grp.index] = 0.0

        if "fcfy_ttm" in grp.columns:
            y_fcfy = pd.to_numeric(grp["fcfy_ttm"], errors="coerce")
            residual_fcfy.loc[grp.index] = _sage_ols_residual(y_fcfy, X_raw)
        else:
            residual_fcfy.loc[grp.index] = 0.0

    d["val_residual_ep"] = residual_ep.fillna(0.0)
    d["val_residual_sp"] = residual_sp.fillna(0.0)
    d["val_residual_fcfy"] = residual_fcfy.fillna(0.0)
    return d


def compute_sage_scores(d: pd.DataFrame) -> pd.DataFrame:
    """Compute SAGE (Sector-Adaptive Growth Engine) composite score.

    Adds columns:
      sage_sector        — 8-bucket sector label
      sage_g_score       — Growth axis (sector-gated z-score blend)
      sage_v_score       — Valuation axis (residual-based)
      sage_q_score       — Quality axis (FCF, ROIC, SBC, dilution)
      sage_c_score       — Confirmation axis (momentum + revisions)
      sage_composite_score — 0.35G + 0.25V + 0.25Q + 0.15C
    """
    if d.empty:
        for c in ("sage_sector", "sage_g_score", "sage_v_score", "sage_q_score", "sage_c_score", "sage_composite_score"):
            d[c] = 0.0
        return d

    d["sage_sector"] = compute_sage_sector_labels(d)
    d = compute_valuation_residuals(d)

    def _sz(col: str) -> pd.Series:
        return cross_sectional_robust_z_by_sector(d, col, "sage_sector")

    def _uz(col: str) -> pd.Series:
        return cross_sectional_robust_z(d, col)

    def _w_mean(*pairs) -> pd.Series:
        total = pd.Series(0.0, index=d.index)
        weight_sum = pd.Series(0.0, index=d.index)
        for w, s in pairs:
            valid = pd.to_numeric(s, errors="coerce").notna()
            total += w * pd.to_numeric(s, errors="coerce").fillna(0.0)
            weight_sum += w * valid.astype(float)
        return (total / weight_sum.replace(0, np.nan)).fillna(0.0)

    sector = d["sage_sector"]
    sw_mask  = sector.isin(["Software", "Semiconductor"])
    med_mask = sector == "MedTech"
    fin_mask = sector == "Banking"
    ene_mask = sector == "Energy"

    # Growth axis
    g_growth_universal = _w_mean(
        (0.40, _sz("sales_cagr_best")),
        (0.30, _sz("revenue_growth_final")),
        (0.20, _sz("eps_cagr_best")),
        (0.10, _sz("ocf_cagr_best")),
    )
    g_sw = _w_mean(
        (0.40, _sz("rule_of_40")),
        (0.35, _sz("sales_cagr_best")),
        (0.25, _sz("eps_cagr_best")),
    )
    g_med = _w_mean(
        (0.55, _sz("sales_cagr_best")),
        (0.25, _sz("revenue_growth_final")),
        (0.20, _sz("eps_cagr_best")),
    )
    g_fin = _w_mean(
        (0.45, _sz("return_on_equity_effective")),
        (0.35, _sz("sales_cagr_best")),
        (0.20, _sz("eps_cagr_best")),
    )
    g_ene = _w_mean(
        (0.40, _sz("ocf_cagr_best")),
        (0.35, _sz("sales_cagr_best")),
        (0.25, _sz("eps_cagr_best")),
    )
    g_base = g_growth_universal.copy()
    g_base.loc[sw_mask]  = g_sw.loc[sw_mask]
    g_base.loc[med_mask] = g_med.loc[med_mask]
    g_base.loc[fin_mask] = g_fin.loc[fin_mask]
    g_base.loc[ene_mask] = g_ene.loc[ene_mask]
    d["sage_g_score"] = g_base.fillna(0.0)

    # Valuation axis
    v_base = _w_mean(
        (0.40, _sz("val_residual_ep")),
        (0.35, _sz("val_residual_sp")),
        (0.25, _sz("val_residual_fcfy")),
    )
    v_direct = _w_mean(
        (0.35, _uz("fcfy_ttm")),
        (0.35, _uz("ep_ttm")),
        (0.30, -_uz("forward_pe_final")),
    )
    v_score = v_base.copy()
    v_score.loc[fin_mask | ene_mask] = (
        0.40 * v_base.loc[fin_mask | ene_mask] + 0.60 * v_direct.loc[fin_mask | ene_mask]
    )
    d["sage_v_score"] = v_score.fillna(0.0)

    # Quality axis
    q_base = _w_mean(
        (0.30, _sz("fcf_margin")),
        (0.25, _sz("gross_margin_ttm")),
        (0.20, _sz("roic_approx")),
        (-0.15, _sz("sbc_to_revenue")),
        (-0.10, _sz("dilution_penalty")),
    )
    q_fin = _w_mean(
        (0.50, _sz("return_on_equity_effective")),
        (0.30, _sz("roa_proxy")),
        (0.20, -_sz("debt_to_equity")),
    )
    q_ene = _w_mean(
        (0.40, _sz("roic_approx")),
        (0.35, _sz("fcf_margin")),
        (0.25, _sz("op_margin_ttm")),
    )
    q_score = q_base.copy()
    q_score.loc[fin_mask] = q_fin.loc[fin_mask]
    q_score.loc[ene_mask] = q_ene.loc[ene_mask]
    d["sage_q_score"] = q_score.fillna(0.0)

    # Confirmation axis
    c_score = _w_mean(
        (0.35, _uz("mom_6m")),
        (0.20, _uz("mom_3m")),
        (0.20, _uz("rs_sector_6m")),
        (0.15, _uz("revision_score")),
        (0.10, _uz("earn_gap_1d")),
    )
    d["sage_c_score"] = c_score.fillna(0.0)

    # Composite
    d["sage_composite_score"] = (
        0.35 * d["sage_g_score"]
        + 0.25 * d["sage_v_score"]
        + 0.25 * d["sage_q_score"]
        + 0.15 * d["sage_c_score"]
    ).fillna(0.0)

    return d


def compute_valuation_columns(df: pd.DataFrame, cfg: Optional[EngineConfig] = None) -> pd.DataFrame:
    d = df.copy()
    d["mktcap"] = pd.to_numeric(d["mktcap"], errors="coerce")
    net_income_ttm = numeric_series_or_default(d, "net_income_ttm", np.nan)
    revenues_ttm = numeric_series_or_default(d, "revenues_ttm", np.nan)
    ocf_ttm = numeric_series_or_default(d, "ocf_ttm", np.nan)
    capex_ttm = numeric_series_or_default(d, "capex_ttm", np.nan)
    sales_growth_yoy = numeric_series_or_default(d, "sales_growth_yoy", np.nan)
    revenue_growth_final = numeric_series_or_default(d, "revenue_growth_final", np.nan)
    earnings_growth_final = numeric_series_or_default(d, "earnings_growth_final", np.nan)
    op_margin_ttm = numeric_series_or_default(d, "op_margin_ttm", np.nan)
    assets = numeric_series_or_default(d, "assets", np.nan).replace(0, np.nan)

    d["ep_ttm"] = net_income_ttm / d["mktcap"]
    d["sp_ttm"] = revenues_ttm / d["mktcap"]
    d["fcf_ttm"] = ocf_ttm - capex_ttm
    d["fcfy_ttm"] = d["fcf_ttm"] / d["mktcap"]
    gross_profit_ttm = numeric_series_or_default(d, "gross_profit_ttm", np.nan)
    op_income_ttm = numeric_series_or_default(d, "op_income_ttm", np.nan)
    d["gross_margins"] = numeric_series_or_default(d, "gross_margins", np.nan).fillna(
        gross_profit_ttm / revenues_ttm.replace(0, np.nan)
    )
    d["op_margin_ttm"] = numeric_series_or_default(d, "op_margin_ttm", np.nan).fillna(
        op_income_ttm / revenues_ttm.replace(0, np.nan)
    )
    d["operating_margins"] = numeric_series_or_default(d, "operating_margins", np.nan).fillna(
        d["op_margin_ttm"]
    )
    d["gp_to_assets_ttm"] = numeric_series_or_default(d, "gp_to_assets_ttm", np.nan).fillna(
        gross_profit_ttm / assets
    )
    d["roa_proxy"] = net_income_ttm / assets
    d["asset_turnover_ttm"] = revenues_ttm / assets
    equity_proxy = (numeric_series_or_default(d, "assets", np.nan) - numeric_series_or_default(d, "liabilities", np.nan)).replace(
        0, np.nan
    )
    d["roe_proxy"] = numeric_series_or_default(d, "roe_proxy", np.nan).fillna(
        net_income_ttm / equity_proxy
    )
    d["book_to_market_proxy"] = equity_proxy / d["mktcap"].replace(0, np.nan)
    d["forward_pe_final"] = numeric_series_or_default(d, "forward_pe_final", np.nan)
    d["forward_pe_final"] = d["forward_pe_final"].fillna(numeric_series_or_default(d, "av_forward_pe", np.nan))
    d["forward_pe_final"] = d["forward_pe_final"].fillna(numeric_series_or_default(d, "forward_pe", np.nan))
    d["forward_pe_final"] = d["forward_pe_final"].fillna(
        (1.0 / d["ep_ttm"]).where(d["ep_ttm"] > 0)
    )
    d["ev_to_ebitda_final"] = numeric_series_or_default(d, "ev_to_ebitda_final", np.nan)
    d["ev_to_ebitda_final"] = d["ev_to_ebitda_final"].fillna(numeric_series_or_default(d, "av_ev_to_ebitda", np.nan))
    d["peg_final"] = numeric_series_or_default(d, "peg_final", np.nan)
    d["peg_final"] = d["peg_final"].fillna(numeric_series_or_default(d, "av_peg_ratio", np.nan))
    d["peg_final"] = d["peg_final"].fillna(numeric_series_or_default(d, "peg_ratio", np.nan))
    earnings_growth_pct = (earnings_growth_final * 100.0).where(earnings_growth_final > 0)
    d["peg_final"] = d["peg_final"].fillna(
        d["forward_pe_final"] / earnings_growth_pct.replace(0, np.nan)
    )
    d["dividends_ttm_ps"] = numeric_series_or_default(d, "dividends_ttm_ps", np.nan)
    d["dividend_yield_ttm"] = numeric_series_or_default(d, "dividend_yield_ttm", np.nan)
    shares = numeric_series_or_default(d, "shares", np.nan).replace(0, np.nan)
    px = numeric_series_or_default(d, "px", np.nan).replace(0, np.nan)
    dividends_ps = d["dividends_ttm_ps"].fillna(d["dividend_yield_ttm"] * px)
    d["dividends_ttm_ps"] = dividends_ps
    shares_proxy = d["mktcap"] / px
    shares_effective = shares.fillna(shares_proxy.replace([np.inf, -np.inf], np.nan))
    d["shares_effective"] = shares_effective
    eps_ttm = net_income_ttm / shares_effective.replace(0, np.nan)
    dividends_total = dividends_ps * shares_effective
    payout_eps = dividends_ps / eps_ttm.replace(0, np.nan)
    payout_eps = payout_eps.where((eps_ttm > 0) & np.isfinite(eps_ttm), np.nan)
    payout_ni = dividends_total / net_income_ttm.replace(0, np.nan)
    payout_ni = payout_ni.where(net_income_ttm > 0, np.nan)
    payout_fcf = dividends_total / d["fcf_ttm"].replace(0, np.nan)
    payout_fcf = payout_fcf.where(d["fcf_ttm"] > 0, np.nan)
    payout = payout_eps.fillna(payout_ni).fillna(payout_fcf)
    payout = payout.where(dividends_ps.fillna(0.0) > 0, np.nan)
    d["dividend_payout_ratio"] = payout
    div_yield = d["dividend_yield_ttm"].clip(lower=0.0)
    yield_score = (1.0 - (div_yield - 0.03).abs() / 0.03).clip(lower=0.0, upper=1.0)
    payout_score = (1.0 - (d["dividend_payout_ratio"] - 0.45).abs() / 0.35).clip(lower=0.0, upper=1.0)
    payout_score = payout_score.where(d["dividend_payout_ratio"].between(0.0, 1.20), 0.0)
    div_positive = ((dividends_ps.fillna(0.0) > 0) | (div_yield.fillna(0.0) > 0)).astype(float)
    payout_available = d["dividend_payout_ratio"].notna().astype(float)
    yield_only_weight = float(cfg.dividend_policy_yield_only_weight) if cfg is not None else 0.35
    d["dividend_policy_score"] = np.where(
        payout_available > 0,
        0.55 * yield_score + 0.45 * payout_score,
        yield_only_weight * yield_score,
    )
    d["dividend_policy_score"] = pd.Series(d["dividend_policy_score"], index=d.index).fillna(0.0) * div_positive
    growth_support = row_mean(
        [
            (sales_growth_yoy > 0.05).astype(float),
            (revenue_growth_final > 0.06).astype(float),
            (earnings_growth_final > 0.08).astype(float),
            (op_margin_ttm > 0.08).astype(float),
            (pd.to_numeric(d["fcfy_ttm"], errors="coerce") > 0.0).astype(float),
        ],
        d.index,
    ).fillna(0.0)
    div_floor = float(cfg.dividend_growth_gate_floor) if cfg is not None else 0.15
    dividend_relevance = (div_floor + (1.0 - div_floor) * growth_support).clip(lower=0.0, upper=1.0)
    d["dividend_policy_score"] = pd.to_numeric(d["dividend_policy_score"], errors="coerce").fillna(0.0) * dividend_relevance
    if ("assets" in d.columns) and ("liabilities" in d.columns):
        equity = (pd.to_numeric(d["assets"], errors="coerce") - pd.to_numeric(d["liabilities"], errors="coerce")).replace(0, np.nan)
        d["debt_to_equity"] = pd.to_numeric(d["liabilities"], errors="coerce") / equity
    else:
        d["debt_to_equity"] = np.nan
    roe_effective = numeric_series_or_default(d, "return_on_equity_effective", np.nan)
    roe_effective = roe_effective.fillna(numeric_series_or_default(d, "return_on_equity_live", np.nan))
    roe_effective = roe_effective.fillna(numeric_series_or_default(d, "av_return_on_equity", np.nan))
    roe_effective = roe_effective.fillna(numeric_series_or_default(d, "roe_proxy", np.nan))
    d["return_on_equity_effective"] = roe_effective
    ttm_presence = row_mean(
        [
            revenues_ttm.notna().astype(float),
            net_income_ttm.notna().astype(float),
            op_margin_ttm.notna().astype(float),
            pd.to_numeric(d["ep_ttm"], errors="coerce").notna().astype(float),
            pd.to_numeric(d["sp_ttm"], errors="coerce").notna().astype(float),
            pd.to_numeric(d["fcfy_ttm"], errors="coerce").notna().astype(float),
        ],
        d.index,
    ).fillna(0.0)
    balance_presence = row_mean(
        [
            numeric_series_or_default(d, "assets", np.nan).notna().astype(float),
            numeric_series_or_default(d, "liabilities", np.nan).notna().astype(float),
            shares_effective.notna().astype(float),
        ],
        d.index,
    ).fillna(0.0)
    dividend_presence = row_mean([div_positive, payout_available], d.index).fillna(0.0) * dividend_relevance
    dividend_presence_weight = float(cfg.dividend_presence_weight) if cfg is not None else 0.03
    d["fundamental_presence_score"] = (
        (0.75 - dividend_presence_weight) * ttm_presence
        + 0.25 * balance_presence
        + dividend_presence_weight * dividend_presence
    ).clip(lower=0.0, upper=1.0)
    join_status = d.get("fund_join_status", pd.Series("", index=d.index, dtype=str)).astype(str)
    join_strength = pd.Series(0.30, index=d.index, dtype=float)
    join_strength = join_strength.where(~join_status.eq("matched_no_ttm"), 0.35)
    join_strength = join_strength.where(~join_status.eq("matched_with_ttm_fallback"), 0.75)
    join_strength = join_strength.where(~join_status.eq("matched_with_ttm_backfill"), 0.85)
    join_strength = join_strength.where(~join_status.eq("matched_with_ttm"), 1.00)
    panel_ttm_ready = numeric_series_or_default(d, "fund_panel_ttm_ready", 0.0).clip(lower=0.0, upper=1.0)
    d["fundamental_reliability_score"] = (
        0.55 * d["fundamental_presence_score"] + 0.30 * join_strength + 0.15 * panel_ttm_ready
    ).clip(lower=0.0, upper=1.0)
    live_growth_presence = row_mean(
        [
            revenue_growth_final.notna().astype(float),
            earnings_growth_final.notna().astype(float),
            numeric_series_or_default(d, "forward_pe_final", np.nan).notna().astype(float),
            numeric_series_or_default(d, "peg_final", np.nan).notna().astype(float),
        ],
        d.index,
    ).fillna(0.0)
    growth_score = row_mean(
        [
            cross_sectional_robust_z(d, "sales_growth_yoy"),
            cross_sectional_robust_z(d, "sales_cagr_3y"),
            cross_sectional_robust_z(d, "sales_cagr_5y"),
            cross_sectional_robust_z(d, "revenue_growth_final"),
            cross_sectional_robust_z(d, "earnings_growth_final"),
            0.50 * cross_sectional_robust_z(d, "actual_results_score"),
        ],
        d.index,
    ).fillna(0.0)
    d["capital_efficiency_score"] = row_mean(
        [
            cross_sectional_robust_z(d, "return_on_equity_effective"),
            cross_sectional_robust_z(d, "roa_proxy"),
            cross_sectional_robust_z(d, "asset_turnover_ttm"),
            0.50 * cross_sectional_robust_z(d, "ocf_ni_quality_4q"),
        ],
        d.index,
    ).fillna(0.0)
    sector_labels = normalized_sector_labels(d)
    finance_mask = sector_keyword_mask(sector_labels, SECTOR_GATE_FINANCIAL_KEYWORDS)
    real_asset_mask = sector_keyword_mask(sector_labels, SECTOR_GATE_REAL_ASSET_KEYWORDS)
    resource_mask = sector_keyword_mask(sector_labels, SECTOR_GATE_RESOURCE_KEYWORDS)
    financial_quality = row_mean(
        [
            cross_sectional_robust_z(d, "return_on_equity_effective"),
            cross_sectional_robust_z(d, "roa_proxy"),
            cross_sectional_robust_z(d, "ep_ttm"),
            cross_sectional_robust_z(d, "book_to_market_proxy"),
            0.60 * cross_sectional_robust_z(d, "capital_efficiency_score"),
        ],
        d.index,
    ).fillna(0.0)
    real_asset_quality = row_mean(
        [
            cross_sectional_robust_z(d, "fcfy_ttm"),
            cross_sectional_robust_z(d, "dividend_policy_score"),
            cross_sectional_robust_z(d, "book_to_market_proxy"),
            cross_sectional_robust_z(d, "capital_efficiency_score"),
            -cross_sectional_robust_z(d, "debt_to_equity"),
        ],
        d.index,
    ).fillna(0.0)
    resource_quality = row_mean(
        [
            cross_sectional_robust_z(d, "fcfy_ttm"),
            cross_sectional_robust_z(d, "sp_ttm"),
            cross_sectional_robust_z(d, "op_margin_ttm"),
            cross_sectional_robust_z(d, "capital_efficiency_score"),
            0.50 * cross_sectional_robust_z(d, "ocf_ni_quality_4q"),
        ],
        d.index,
    ).fillna(0.0)
    default_quality = row_mean(
        [
            cross_sectional_robust_z(d, "capital_efficiency_score"),
            cross_sectional_robust_z(d, "op_margin_ttm"),
            cross_sectional_robust_z(d, "fcfy_ttm"),
            -cross_sectional_robust_z(d, "debt_to_equity"),
        ],
        d.index,
    ).fillna(0.0)
    d["sector_adjusted_quality_score"] = default_quality
    d.loc[finance_mask, "sector_adjusted_quality_score"] = financial_quality.loc[finance_mask]
    d.loc[real_asset_mask, "sector_adjusted_quality_score"] = real_asset_quality.loc[real_asset_mask]
    d.loc[resource_mask, "sector_adjusted_quality_score"] = resource_quality.loc[resource_mask]

    # --- SAGE: Sector-Adaptive Growth Engine scores ---
    d = compute_sage_scores(d)

    value_score = row_mean(
        [
            cross_sectional_robust_z(d, "ep_ttm"),
            cross_sectional_robust_z(d, "sp_ttm"),
            cross_sectional_robust_z(d, "fcfy_ttm"),
            -cross_sectional_robust_z(d, "forward_pe_final"),
            -cross_sectional_robust_z(d, "peg_final"),
            -cross_sectional_robust_z(d, "forward_ps_final"),
        ],
        d.index,
    ).fillna(0.0)
    quality_support = row_mean(
        [
            cross_sectional_robust_z(d, "op_margin_ttm"),
            cross_sectional_robust_z(d, "quality_trend_score"),
            cross_sectional_robust_z(d, "capital_efficiency_score"),
            -cross_sectional_robust_z(d, "debt_to_equity"),
        ],
        d.index,
    ).fillna(0.0)
    garp_confidence = pd.Series(
        np.maximum(
            pd.to_numeric(d["fundamental_reliability_score"], errors="coerce").to_numpy(dtype=float),
            (0.75 * live_growth_presence).to_numpy(dtype=float),
        ),
        index=d.index,
        dtype=float,
    ).clip(lower=0.0, upper=1.0)
    garp = (
        0.45 * growth_score
        + 0.35 * value_score
        + 0.20 * quality_support
    ) * (0.55 + 0.45 * garp_confidence)
    d["garp_score"] = winsorize(garp, 0.01).clip(-6.0, 6.0)
    return d


def build_feature_store(cfg: dict | EngineConfig) -> pd.DataFrame:
    cfg = to_cfg(cfg)
    paths = get_paths(cfg)
    log("Phase 3: building feature store ...")

    universe = build_universe_monthly(cfg)
    write_fundamental_join_diagnostics(paths, universe)
    if "rebalance_date" not in universe.columns and "Date" in universe.columns:
        universe = universe.rename(columns={"Date": "rebalance_date"})
    universe["rebalance_date"] = pd.to_datetime(universe["rebalance_date"], errors="coerce")
    if universe["rebalance_date"].notna().sum() == 0:
        raise RuntimeError(
            "rebalance_date parsing failed in build_feature_store. "
            f"available_date_cols={[c for c in universe.columns if 'date' in c.lower()]}"
        )
    universe = universe.sort_values(["ticker", "rebalance_date"]).reset_index(drop=True)
    universe["feature_date"] = pd.to_datetime(universe["rebalance_date"], errors="coerce")
    universe["entry_date"] = pd.NaT
    universe["r_1m"] = np.nan
    universe["r_3m"] = np.nan
    universe["r_6m"] = np.nan
    universe["r_12m"] = np.nan
    universe["r_24m"] = np.nan
    universe["r_36m"] = np.nan
    universe["earn_gap_1d"] = np.nan
    for t, g in universe.groupby("ticker", sort=False):
        px = load_px(paths, t)
        if px is None or px.empty:
            continue
        gg = g.sort_values("rebalance_date")
        entry_dates, forward_returns = compute_forward_returns_for_dates(
            px,
            gg["rebalance_date"],
            [
                cfg.target_1m_days,
                cfg.target_3m_days,
                cfg.target_6m_days,
                cfg.target_12m_days,
                cfg.target_24m_days,
                cfg.target_36m_days,
            ],
        )
        universe.loc[gg.index, "entry_date"] = entry_dates.values
        universe.loc[gg.index, "r_1m"] = forward_returns[int(cfg.target_1m_days)].values
        universe.loc[gg.index, "r_3m"] = forward_returns[int(cfg.target_3m_days)].values
        universe.loc[gg.index, "r_6m"] = forward_returns[int(cfg.target_6m_days)].values
        universe.loc[gg.index, "r_12m"] = forward_returns[int(cfg.target_12m_days)].values
        universe.loc[gg.index, "r_24m"] = forward_returns[int(cfg.target_24m_days)].values
        universe.loc[gg.index, "r_36m"] = forward_returns[int(cfg.target_36m_days)].values
        universe.loc[gg.index, "earn_gap_1d"] = compute_earn_gap_1d_for_dates(px, gg["accepted"]).values
    universe = attach_benchmark_forward_returns(cfg, paths, universe)

    chk = universe.dropna(subset=["accepted", "feature_date", "rebalance_date"])
    bad = chk[~((chk["accepted"] <= chk["feature_date"]) & (chk["feature_date"] <= chk["rebalance_date"]))]
    if len(bad) > 0:
        log(f"[WARN] PIT check found {len(bad)} suspicious rows; dropping them.")
        universe = universe.drop(index=bad.index)

    universe = compute_actual_priority_columns(universe, cfg)
    universe = apply_latest_only_signal_guard(universe)
    universe = compute_valuation_columns(universe, cfg)
    universe = compute_macro_interaction_features(universe)
    universe = compute_market_adaptation_features(universe)
    universe = compute_event_regime_features(universe)
    universe = compute_moat_proxy_features(universe)
    universe = compute_dynamic_leadership_features(universe)
    universe = compute_three_level_relative_strength(universe)
    universe = compute_crisis_sector_fit(universe)
    universe = compute_strategy_blueprint_columns(universe, cfg)
    universe = compute_multidimensional_pillar_scores(universe)
    universe = add_core_fundamental_minimum_flags(universe, cfg)

    keep_cols = list(
        dict.fromkeys(
            [
                "ticker",
                "Name",
                "sector",
                "universe_source",
                "cik10",
                "period",
                "accepted",
                "fund_period",
                "fund_accepted",
                "fund_source",
                "fund_asof_quarter",
                "feature_date",
                "entry_date",
                "rebalance_date",
                "r_12m",
                "r_24m",
                "r_36m",
                "bench_r_12m",
                "bench_r_24m",
                "bench_r_36m",
                "px",
                "open_px",
                "mktcap",
                "fund_latest_period_overall",
                "fund_latest_accepted_overall",
                "fund_panel_raw_flow_4q_cov_mean",
                "fund_panel_ttm_ready",
                "fund_ttm_cum_fallback_used",
                "fund_ttm_backfill_used",
                "fund_ttm_fallback_used",
                "fund_ttm_fallback_age_days",
                "fund_effective_accepted",
                "fund_effective_period",
                "fund_effective_age_days",
                "fund_join_status",
                "fund_join_gap_days",
                "event_regime_label",
                "live_event_alert_label",
                "selection_fundamental_confirmation_score",
                "selection_market_confirmation_score",
                "selection_confirmation_score",
            ]
            + CORE_FUNDAMENTAL_COLUMNS
            + FUNDAMENTAL_COVERAGE_COLUMNS
            + COMPREHENSIVE_FUNDAMENTAL_COVERAGE_COLUMNS
            + cfg.features
            + ACTUAL_PRIORITY_COLUMNS
            + SEC_13F_COLUMNS
            + SEC_FORM345_COLUMNS
            + PILLAR_SCORE_COLUMNS
            + MACRO_REGIME_COLUMNS
            + MACRO_INTERACTION_COLUMNS
            + LATEST_ONLY_SIGNAL_COLUMNS
            + PHASE2_INDUSTRY_COLUMNS
            + PHASE5_LEADER_LAGGARD_COLUMNS
            + PHASE1_ALPHA_COLUMNS
            + PHASE8B_LONG_LOOKBACK_COLUMNS
            + PHASE9_C3_TURNAROUND_COLUMNS
            + PHASE11_MULTIBAGGER_COLUMNS
            + ["r_1m", "r_3m", "r_6m", "bench_r_1m", "bench_r_3m", "bench_r_6m"]
        )
    )
    for c in keep_cols:
        if c not in universe.columns:
            universe[c] = np.nan
    fs = universe[keep_cols].copy()
    # Phase 2 industry metadata is string-typed (industry / industry_group /
    # subindustry) and must NOT be force-converted to numeric by hard_sanitize.
    # Sanitize only the numeric Phase 2 columns (rs_industry_*, breadth, O'Neil
    # leadership score, industry_within_leader_rank, industry_rotation_signal).
    _PHASE2_NUMERIC_COLUMNS = [
        c for c in PHASE2_INDUSTRY_COLUMNS
        if c not in ("industry", "industry_group", "subindustry")
    ]
    fs = hard_sanitize(
        fs,
        CORE_FUNDAMENTAL_COLUMNS
        + cfg.features
        + ACTUAL_PRIORITY_COLUMNS
        + SEC_13F_COLUMNS
        + SEC_FORM345_COLUMNS
        + PILLAR_SCORE_COLUMNS
        + _PHASE2_NUMERIC_COLUMNS
        + PHASE5_LEADER_LAGGARD_COLUMNS
        + PHASE1_ALPHA_COLUMNS
        + PHASE8B_LONG_LOOKBACK_COLUMNS
        + PHASE9_C3_TURNAROUND_COLUMNS
        + PHASE11_MULTIBAGGER_COLUMNS
        + ["r_1m", "r_3m", "r_6m", "r_12m", "r_24m", "r_36m", "bench_r_1m", "bench_r_3m", "bench_r_6m", "bench_r_12m", "bench_r_24m", "bench_r_36m", "mktcap"],
        clip=1e12,
    )
    fs["rebalance_date"] = pd.to_datetime(fs["rebalance_date"], errors="coerce")
    fs["feature_date"] = pd.to_datetime(fs["feature_date"], errors="coerce")
    (paths["reports"] / "feature_store_quality.json").write_text(
        json.dumps(
            {
                "rows": int(len(fs)),
                "rebalance_notna": int(fs["rebalance_date"].notna().sum()),
                "feature_notna": int(fs["feature_date"].notna().sum()),
                "label_notna": int((fs["r_1m"].notna() | fs["r_3m"].notna() | fs["r_6m"].notna()).sum()),
                "mktcap_notna": int(fs["mktcap"].notna().sum()),
                "universe_mode": "historical_membership_file"
                if fs.get("universe_source", pd.Series(dtype=str)).astype(str).eq("historical_membership_file").any()
                else "current_constituents_proxy",
            },
            indent=2,
        )
    )
    fs.to_parquet(paths["feature_store"] / "feature_store_latest.parquet", index=False)
    write_stage_coverage_report(
        paths,
        "feature_store",
        fs,
        FUNDAMENTAL_COVERAGE_COLUMNS
        + ["r_1m", "r_3m", "r_6m"]
        + SEC_13F_COLUMNS
        + SEC_FORM345_COLUMNS
        + MACRO_REGIME_COLUMNS
        + MACRO_INTERACTION_COLUMNS
        + _PHASE2_NUMERIC_COLUMNS
        + PHASE5_LEADER_LAGGARD_COLUMNS
        + PHASE1_ALPHA_COLUMNS
        + PHASE8B_LONG_LOOKBACK_COLUMNS
        + LIVE_EVENT_ALERT_COLUMNS,
    )
    write_fundamental_coverage_report(
        paths,
        fs,
        final_filename="feature_store_fundamental_coverage_latest.csv",
    )
    write_live_fundamental_coverage_report(
        paths,
        fs,
        final_filename="feature_store_live_fundamental_coverage_latest.csv",
    )
    # Phase 11 (2026-04-20): add P(entry)/P(tp)/P(sl) columns. If sleeve disabled,
    # writes zeros so keep_cols whitelist never drops missing columns.
    try:
        fs = compute_phase11_predictions(cfg, fs, paths)
    except Exception as exc:
        log(f"[Phase 11] predictions failed; falling back to zeros: {exc}")
        for c in ("phase11_p_entry", "phase11_p_takeprofit", "phase11_p_stoploss"):
            if c not in fs.columns:
                fs[c] = 0.0
    return fs


# =====================================================================
# Phase 11: Multibagger Watch -- classifier training + prediction
# =====================================================================
# 3 classifiers trained on historical 5x+ episodes (research/multibagger_episodes.csv):
#   P(entry)       AUC 0.84 -- pre/early surge detection
#   P(takeprofit)  AUC 0.75 -- peak detection (익절 signal)
#   P(stoploss)    AUC 0.62 -- forward-loss detection (손절 signal)
# Design + validation: research/phase11_{retrospective,entry_classifier,exit_classifier,sleeve_backtest}.py

PHASE11_MODELS_SUBDIR = "phase11_models"
PHASE11_EPISODES_REL = "research/multibagger_episodes.csv"

PHASE11_FEATURE_EXCLUDE = {
    "ticker", "Name", "sector", "industry", "industry_group", "subindustry",
    "universe_source", "cik10", "period", "accepted", "fund_period",
    "fund_accepted", "fund_source", "fund_asof_quarter", "feature_date",
    "entry_date", "rebalance_date", "macro_regime_label",
    "event_regime_label", "live_event_alert_label",
    "regime_rotation_label", "regime_rotation_short_label",
    "yf_sector", "yf_industry", "yf_industry_group", "yf_subindustry",
    "sage_sector", "cnn_fear_greed_label", "company_key",
    "r_1m", "r_3m", "r_6m", "r_12m", "r_24m", "r_36m",
    "bench_r_1m", "bench_r_3m", "bench_r_6m", "bench_r_12m",
    "bench_r_24m", "bench_r_36m",
    # Label columns (prevent leakage)
    "label", "tp_label", "sl_label",
    # Phase 11 prediction columns (self-prediction guard)
    "phase11_p_entry", "phase11_p_takeprofit", "phase11_p_stoploss",
}


def _prep_phase11_features(
    df: pd.DataFrame, nan_threshold: float = 0.50
) -> tuple[pd.DataFrame, list[str]]:
    """Select + impute + clip features for Phase 11 classifier training/prediction."""
    numeric = df.select_dtypes(include=[np.number]).columns.tolist()
    feats = [c for c in numeric if c not in PHASE11_FEATURE_EXCLUDE and not c.startswith("score")]
    nan_pct = df[feats].isna().mean()
    good = nan_pct[nan_pct < nan_threshold].index.tolist()
    X = df[good].copy()
    for c in good:
        med = X[c].median()
        X[c] = X[c].fillna(med if pd.notna(med) else 0.0)
        if X[c].std() > 0:
            z = (X[c] - X[c].mean()) / X[c].std()
            X[c] = X[c].where(z.abs() < 5, X[c].mean())
    return X, good


def _load_phase11_episodes() -> Optional[pd.DataFrame]:
    """Load historical 5x+ multibagger episodes. Returns None if CSV missing."""
    p = Path(__file__).resolve().parent / PHASE11_EPISODES_REL
    if not p.exists():
        log(f"[Phase 11] episodes CSV not found at {p}; skipping training")
        return None
    try:
        df = pd.read_csv(p)
    except Exception as exc:
        log(f"[Phase 11] failed to read episodes CSV: {exc}")
        return None
    df["surge_start_date"] = pd.to_datetime(df["surge_start_date"], errors="coerce")
    df["peak_date"] = pd.to_datetime(df["peak_date"], errors="coerce")
    return df.dropna(subset=["ticker", "surge_start_date", "peak_date"])


def train_phase11_classifiers(
    cfg: dict | EngineConfig,
    fs: pd.DataFrame,
    paths: dict[str, Path],
) -> Optional[dict[str, Any]]:
    """Train entry + takeprofit + stoploss classifiers on feature_store history.
    Saves models to paths["cache_misc"]/phase11_models/. Returns artifact dict or None.
    """
    cfg_obj = to_cfg(cfg)
    # Gate: env var overrides cfg default.
    _cfg_default = bool(getattr(cfg_obj, "phase11_multibagger_sleeve_enabled", False))
    if not phase_is_enabled("phase11_multibagger", default=_cfg_default):
        return None

    episodes = _load_phase11_episodes()
    if episodes is None or episodes.empty:
        log("[Phase 11] no episodes available; skipping training")
        return None

    log("Phase 11: training multibagger classifiers (entry + takeprofit + stoploss) ...")

    df = fs.copy()
    df["rebalance_date"] = pd.to_datetime(df["rebalance_date"], errors="coerce")
    df = df.dropna(subset=["ticker", "rebalance_date"]).reset_index(drop=True)

    # Construct labels
    PRE = 6
    POST_SURGE = 3
    AMB_POST_PEAK = 6

    df["label"] = 0
    for ticker, grp in episodes.groupby("ticker"):
        mask_t = df["ticker"] == ticker
        for _, ep in grp.iterrows():
            pre = ep["surge_start_date"] - pd.DateOffset(months=PRE)
            post = ep["surge_start_date"] + pd.DateOffset(months=POST_SURGE)
            df.loc[mask_t & (df["rebalance_date"] >= pre) & (df["rebalance_date"] <= post), "label"] = 1

    df["tp_label"] = -9
    for ticker, grp in episodes.groupby("ticker"):
        mask_t = df["ticker"] == ticker
        for _, ep in grp.iterrows():
            peak = ep["peak_date"]
            near_start = peak - pd.DateOffset(months=2)
            near_end = peak + pd.DateOffset(months=1)
            healthy_end = peak - pd.DateOffset(months=3)
            pos = (df["rebalance_date"] >= near_start) & (df["rebalance_date"] <= near_end)
            df.loc[mask_t & pos, "tp_label"] = 1
            neg = (df["rebalance_date"] >= ep["surge_start_date"]) & (df["rebalance_date"] <= healthy_end)
            curr = df.loc[mask_t & neg, "tp_label"]
            df.loc[curr.index[curr == -9], "tp_label"] = 0

    df["sl_label"] = -9
    r12 = pd.to_numeric(df.get("r_12m", pd.Series(np.nan, index=df.index)), errors="coerce")
    df.loc[r12 < -0.15, "sl_label"] = 1
    df.loc[r12 > 0.20, "sl_label"] = 0

    X_full, good_feats = _prep_phase11_features(df)

    min_pos = int(getattr(cfg_obj, "phase11_min_positive_examples", 30))
    iters = int(getattr(cfg_obj, "phase11_classifier_iterations", 500))
    depth = int(getattr(cfg_obj, "phase11_classifier_depth", 6))
    lr = float(getattr(cfg_obj, "phase11_classifier_learning_rate", 0.03))

    try:
        from catboost import CatBoostClassifier
        from sklearn.linear_model import LogisticRegression
        from sklearn.preprocessing import StandardScaler
    except Exception as exc:
        log(f"[Phase 11] sklearn/catboost not available: {exc}")
        return None

    artifacts: dict[str, Any] = {"features": good_feats}

    def _train_one(label_col: str, name: str) -> bool:
        mask = df[label_col].isin([0, 1])
        if mask.sum() == 0:
            log(f"[Phase 11] {name}: no labeled rows; skipping")
            return False
        y = df.loc[mask, label_col].astype(int).values
        if y.sum() < min_pos or (y == 0).sum() < min_pos:
            log(f"[Phase 11] {name}: too few examples (pos={int(y.sum())}, neg={int((y==0).sum())})")
            return False
        X = X_full.loc[mask].values
        scaler = StandardScaler().fit(X)
        lr_model = LogisticRegression(
            penalty="l2", C=1.0, class_weight="balanced",
            max_iter=2000, solver="lbfgs", random_state=42,
        ).fit(scaler.transform(X), y)
        cb_model = CatBoostClassifier(
            iterations=iters, learning_rate=lr, depth=depth,
            loss_function="Logloss", auto_class_weights="Balanced",
            random_seed=42, verbose=False,
        ).fit(X, y)
        artifacts[name] = {
            "scaler": scaler,
            "lr": lr_model,
            "cb": cb_model,
            "n_train_pos": int(y.sum()),
            "n_train_neg": int((y == 0).sum()),
        }
        log(f"[Phase 11] {name}: trained (pos={int(y.sum())}, neg={int((y==0).sum())})")
        return True

    entry_ok = _train_one("label", "entry")
    tp_ok = _train_one("tp_label", "takeprofit")
    sl_ok = _train_one("sl_label", "stoploss")

    if not (entry_ok or sl_ok):
        # Entry + stoploss are critical; take_profit is optional
        log("[Phase 11] critical classifiers failed; aborting")
        return None

    # Persist
    import pickle
    models_dir = paths["cache_misc"] / PHASE11_MODELS_SUBDIR
    safe_mkdir(models_dir)
    with open(models_dir / "artifacts.pkl", "wb") as f:
        pickle.dump(artifacts, f)
    log(f"[Phase 11] saved artifacts to {models_dir / 'artifacts.pkl'}")
    return artifacts


def _load_phase11_models(paths: dict[str, Path]) -> Optional[dict[str, Any]]:
    """Load previously-trained Phase 11 artifacts, or None if missing."""
    import pickle
    p = paths["cache_misc"] / PHASE11_MODELS_SUBDIR / "artifacts.pkl"
    if not p.exists():
        return None
    try:
        with open(p, "rb") as f:
            return pickle.load(f)
    except Exception as exc:
        log(f"[Phase 11] failed to load models from {p}: {exc}")
        return None


def compute_phase11_predictions(
    cfg: dict | EngineConfig,
    fs: pd.DataFrame,
    paths: dict[str, Path],
) -> pd.DataFrame:
    """Add phase11_p_entry / phase11_p_takeprofit / phase11_p_stoploss columns to fs.
    If Phase 11 disabled OR models unavailable, writes zeros (so downstream keep_cols
    whitelist never drops missing columns).
    """
    cfg_obj = to_cfg(cfg)
    out = fs.copy()
    for c in ("phase11_p_entry", "phase11_p_takeprofit", "phase11_p_stoploss"):
        if c not in out.columns:
            out[c] = 0.0

    _cfg_default = bool(getattr(cfg_obj, "phase11_multibagger_sleeve_enabled", False))
    if not phase_is_enabled("phase11_multibagger", default=_cfg_default):
        return out

    artifacts = _load_phase11_models(paths)
    if artifacts is None:
        # Try to train now
        artifacts = train_phase11_classifiers(cfg_obj, fs, paths)
    if artifacts is None:
        log("[Phase 11] no models available; returning zero predictions")
        return out

    X_full, good_feats = _prep_phase11_features(out)
    # Align with training features (use intersection)
    train_feats = artifacts.get("features", good_feats)
    common = [c for c in train_feats if c in X_full.columns]
    if not common:
        log("[Phase 11] feature alignment failed; returning zeros")
        return out
    X = X_full[common].values

    def _predict(classifier_key: str, col: str) -> None:
        if classifier_key not in artifacts:
            return
        m = artifacts[classifier_key]
        try:
            p_lr = m["lr"].predict_proba(m["scaler"].transform(X))[:, 1]
            p_cb = m["cb"].predict_proba(X)[:, 1]
            out[col] = 0.5 * p_lr + 0.5 * p_cb
        except Exception as exc:
            log(f"[Phase 11] prediction failed for {classifier_key}: {exc}")

    _predict("entry", "phase11_p_entry")
    _predict("takeprofit", "phase11_p_takeprofit")
    _predict("stoploss", "phase11_p_stoploss")
    log(f"[Phase 11] predictions written for {len(out)} rows")
    return out


@dataclass
class ModelBundle:
    task_type: str
    ensemble_weights: dict[str, float]
    linear_feature_weights: dict[str, float]
    score_columns: list[str]
    oos_rows: int
    ranking_enabled: bool = False
    target_spec: dict[str, Any] = field(default_factory=dict)
    ranking_metrics: dict[str, float] = field(default_factory=dict)
    adaptive_ensemble_weights: dict[str, float] = field(default_factory=dict)
    adaptive_ensemble_diagnostics: dict[str, Any] = field(default_factory=dict)
    regime_ensemble_weights: dict[str, dict[str, float]] = field(default_factory=dict)


def load_model_bundle_json(paths: dict[str, Path]) -> Optional[ModelBundle]:
    path = paths["models"] / "model_bundle_latest.json"
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text())
        if not isinstance(payload, dict):
            return None
        return ModelBundle(**payload)
    except Exception:
        return None


def phase4_latest_model_paths(paths: dict[str, Path]) -> dict[str, Path]:
    return {
        "meta": paths["models"] / "phase4_latest_scoring_meta.json",
        "cat_reg": paths["models"] / "phase4_latest_cat_reg.cbm",
        "cat_cls": paths["models"] / "phase4_latest_cat_cls.cbm",
        "cat_rank": paths["models"] / "phase4_latest_cat_rank.cbm",
    }


def _safe_unlink(path: Path) -> None:
    try:
        if path.exists():
            path.unlink()
    except Exception:
        pass


def save_phase4_latest_scoring_artifacts(
    paths: dict[str, Path],
    model_features: list[str],
    scaler: Optional[dict[str, dict[str, float]]],
    reg: Any,
    clf: Any,
    future_reg: Any,
    future_clf: Any,
    cbr: Any,
    cbc: Any,
    cbrk: Any,
    ranking_enabled: bool,
) -> None:
    if scaler is None or reg is None:
        return
    art = phase4_latest_model_paths(paths)
    meta: dict[str, Any] = {
        "model_features": list(model_features),
        "scaler": scaler,
        "ranking_enabled": bool(ranking_enabled),
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "ridge": {
            "coef": [float(x) for x in np.asarray(getattr(reg, "coef_", []), dtype=float).tolist()],
            "intercept": float(getattr(reg, "intercept_", 0.0)),
        },
        "logreg": None,
        "future_ridge": None,
        "future_logreg": None,
    }
    if clf is not None and hasattr(clf, "coef_") and hasattr(clf, "intercept_"):
        meta["logreg"] = {
            "coef": [float(x) for x in np.asarray(clf.coef_[0], dtype=float).tolist()],
            "intercept": float(np.asarray(clf.intercept_, dtype=float)[0]),
        }
    if future_reg is not None and hasattr(future_reg, "coef_") and hasattr(future_reg, "intercept_"):
        meta["future_ridge"] = {
            "coef": [float(x) for x in np.asarray(getattr(future_reg, "coef_", []), dtype=float).tolist()],
            "intercept": float(getattr(future_reg, "intercept_", 0.0)),
        }
    if future_clf is not None and hasattr(future_clf, "coef_") and hasattr(future_clf, "intercept_"):
        meta["future_logreg"] = {
            "coef": [float(x) for x in np.asarray(future_clf.coef_[0], dtype=float).tolist()],
            "intercept": float(np.asarray(future_clf.intercept_, dtype=float)[0]),
        }
    art["meta"].write_text(json.dumps(meta, indent=2))
    if cbr is not None:
        cbr.save_model(str(art["cat_reg"]))
    else:
        _safe_unlink(art["cat_reg"])
    if cbc is not None:
        cbc.save_model(str(art["cat_cls"]))
    else:
        _safe_unlink(art["cat_cls"])
    if cbrk is not None:
        cbrk.save_model(str(art["cat_rank"]))
    else:
        _safe_unlink(art["cat_rank"])


def load_phase4_latest_scoring_artifacts(
    paths: dict[str, Path],
    model_features: list[str],
) -> Optional[dict[str, Any]]:
    art = phase4_latest_model_paths(paths)
    if not art["meta"].exists():
        return None
    try:
        meta = json.loads(art["meta"].read_text())
    except Exception:
        return None
    if list(meta.get("model_features", [])) != list(model_features):
        return None
    return meta if isinstance(meta, dict) else None


def ridge_predict_from_meta(X: np.ndarray, meta: dict[str, Any], key: str = "ridge") -> np.ndarray:
    ridge = meta.get(key, {}) if isinstance(meta, dict) else {}
    coef = np.asarray(ridge.get("coef", []), dtype=float)
    intercept = float(ridge.get("intercept", 0.0))
    if X.ndim != 2 or X.shape[1] != len(coef):
        return np.zeros(X.shape[0], dtype=float)
    return X @ coef + intercept


def logreg_predict_proba_from_meta(X: np.ndarray, meta: dict[str, Any], key: str = "logreg") -> np.ndarray:
    logreg = meta.get(key) if isinstance(meta, dict) else None
    if not isinstance(logreg, dict):
        return np.zeros(X.shape[0], dtype=float)
    coef = np.asarray(logreg.get("coef", []), dtype=float)
    intercept = float(logreg.get("intercept", 0.0))
    if X.ndim != 2 or X.shape[1] != len(coef):
        return np.zeros(X.shape[0], dtype=float)
    z = X @ coef + intercept
    z = np.clip(z, -40.0, 40.0)
    return 1.0 / (1.0 + np.exp(-z))


def make_targets(df: pd.DataFrame, cfg: EngineConfig) -> tuple[np.ndarray, np.ndarray]:
    r1 = numeric_series_or_default(df, "r_1m", np.nan)
    r3 = numeric_series_or_default(df, "r_3m", np.nan)
    r6 = numeric_series_or_default(df, "r_6m", np.nan)
    w1, w3, w6 = cfg.target_blend_1m, cfg.target_blend_3m, cfg.target_blend_6m
    abs_num = w1 * r1.fillna(0) + w3 * r3.fillna(0) + w6 * r6.fillna(0)
    abs_den = (
        w1 * r1.notna().astype(float) + w3 * r3.notna().astype(float) + w6 * r6.notna().astype(float)
    ).replace(0, np.nan)
    abs_y = abs_num / abs_den

    b1 = numeric_series_or_default(df, "bench_r_1m", np.nan)
    b3 = numeric_series_or_default(df, "bench_r_3m", np.nan)
    b6 = numeric_series_or_default(df, "bench_r_6m", np.nan)
    excess_num = (
        w1 * (r1 - b1).fillna(0)
        + w3 * (r3 - b3).fillna(0)
        + w6 * (r6 - b6).fillna(0)
    )
    excess_den = (
        w1 * (r1.notna() & b1.notna()).astype(float)
        + w3 * (r3.notna() & b3.notna()).astype(float)
        + w6 * (r6.notna() & b6.notna()).astype(float)
    ).replace(0, np.nan)
    excess_y = excess_num / excess_den

    excess_w = float(cfg.target_excess_weight)
    abs_w = 1.0 - excess_w
    y = abs_w * abs_y.fillna(0.0) + excess_w * excess_y.fillna(abs_y).fillna(0.0)
    y = y.fillna(0).values

    bucket = pd.to_datetime(df["feature_date"]).dt.to_period("M").astype(str)
    ybin = np.zeros(len(df), dtype=int)
    for _, idxs in pd.Series(range(len(df))).groupby(bucket):
        ii = idxs.values
        yy = pd.Series(y, index=df.index).iloc[ii]
        if yy.notna().sum() < 100:
            continue
        thr = yy.quantile(0.90)
        ybin[ii] = (yy >= thr).fillna(False).astype(int).values
    return y, ybin


def make_future_winner_targets(
    df: pd.DataFrame,
    cfg: EngineConfig,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    r12 = numeric_series_or_default(df, "r_12m", np.nan)
    r24 = numeric_series_or_default(df, "r_24m", np.nan)
    r36 = numeric_series_or_default(df, "r_36m", np.nan)
    b12 = numeric_series_or_default(df, "bench_r_12m", np.nan)
    b24 = numeric_series_or_default(df, "bench_r_24m", np.nan)
    b36 = numeric_series_or_default(df, "bench_r_36m", np.nan)
    w12 = float(cfg.future_target_blend_12m)
    w24 = float(cfg.future_target_blend_24m)
    w36 = float(cfg.future_target_blend_36m)

    abs_num = w12 * r12.fillna(0.0) + w24 * r24.fillna(0.0) + w36 * r36.fillna(0.0)
    abs_den = (
        w12 * r12.notna().astype(float)
        + w24 * r24.notna().astype(float)
        + w36 * r36.notna().astype(float)
    ).replace(0.0, np.nan)
    abs_y = abs_num / abs_den

    excess_num = (
        w12 * (r12 - b12).fillna(0.0)
        + w24 * (r24 - b24).fillna(0.0)
        + w36 * (r36 - b36).fillna(0.0)
    )
    excess_den = (
        w12 * (r12.notna() & b12.notna()).astype(float)
        + w24 * (r24.notna() & b24.notna()).astype(float)
        + w36 * (r36.notna() & b36.notna()).astype(float)
    ).replace(0.0, np.nan)
    excess_y = excess_num / excess_den

    breakout_bonus = (
        0.18 * np.clip(r12.fillna(0.0) - 0.50, 0.0, None)
        + 0.28 * np.clip(r24.fillna(0.0) - 1.00, 0.0, None)
        + 0.32 * np.clip(r36.fillna(0.0) - 1.50, 0.0, None)
        + 0.12 * np.clip((r24 - b24).fillna(0.0) - 0.50, 0.0, None)
        + 0.16 * np.clip((r36 - b36).fillna(0.0) - 0.75, 0.0, None)
    )
    excess_w = float(cfg.future_target_excess_weight)
    abs_w = 1.0 - excess_w
    available = (r12.notna() | r24.notna() | r36.notna()).astype(bool)
    y = abs_w * abs_y.fillna(0.0) + excess_w * excess_y.fillna(abs_y).fillna(0.0) + breakout_bonus
    y = y.where(available, np.nan)

    bucket = pd.to_datetime(df["feature_date"]).dt.to_period("M").astype(str)
    ybin = np.zeros(len(df), dtype=int)
    for _, idxs in pd.Series(range(len(df))).groupby(bucket):
        ii = idxs.values
        yy = y.iloc[ii]
        if yy.notna().sum() < 80:
            continue
        r12_i = r12.iloc[ii]
        r24_i = r24.iloc[ii]
        r36_i = r36.iloc[ii]
        hard_hit = (
            (r36_i >= 1.5)
            | (r24_i >= 1.0)
            | ((r12_i >= 0.50) & (r24_i.isna() | (r24_i >= 0.75) | (r36_i >= 1.2)))
        ).fillna(False)
        soft_thr = yy.quantile(0.92)
        soft_hit = (yy >= soft_thr).fillna(False)
        ybin[ii] = (hard_hit | soft_hit).astype(int).values

    # Multibagger diagnostic: 5x in 36m, 3x in 24m, or 2x in 12m.
    tenbagger_hit = (
        (r36 >= 4.0)
        | (r24 >= 2.0)
        | ((r12 >= 1.0) & (r24.isna() | (r24 >= 1.5) | (r36 >= 3.0)))
    ).fillna(False).astype(float)
    df["tenbagger_hit"] = tenbagger_hit.values

    return y.values, ybin, available.values.astype(bool)


def fit_scaler(train_df: pd.DataFrame, features: list[str]) -> dict[str, dict[str, float]]:
    scaler: dict[str, dict[str, float]] = {}
    for f in features:
        x = pd.to_numeric(train_df[f], errors="coerce")
        lo, hi = x.quantile(0.01), x.quantile(0.99)
        w = x.clip(lo, hi)
        med = float(np.nanmedian(w.values))
        mad = float(np.nanmedian(np.abs(w.values - med)))
        scaler[f] = {"lo": float(lo) if pd.notna(lo) else np.nan, "hi": float(hi) if pd.notna(hi) else np.nan, "med": med, "mad": mad if mad > 0 else 1.0}
    return scaler


def apply_scaler(df: pd.DataFrame, scaler: dict[str, dict[str, float]], features: list[str]) -> np.ndarray:
    arr = []
    for f in features:
        x = pd.to_numeric(df[f], errors="coerce")
        st = scaler[f]
        x = x.clip(st["lo"], st["hi"])
        z = (x - st["med"]) / (1.4826 * st["mad"])
        arr.append(z.fillna(0.0).values.reshape(-1, 1))
    return np.hstack(arr) if arr else np.empty((len(df), 0))


def split_walkforward_train_valid(
    train_df: pd.DataFrame,
    validation_months: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if train_df is None or train_df.empty or int(validation_months) <= 0:
        return train_df.copy(), pd.DataFrame(columns=train_df.columns if train_df is not None else [])

    d = train_df.copy()
    d["rebalance_date"] = pd.to_datetime(d["rebalance_date"], errors="coerce")
    months = sorted(d["rebalance_date"].dropna().unique().tolist())
    if len(months) <= int(validation_months) + 6:
        return d, pd.DataFrame(columns=d.columns)

    valid_months = set(pd.Timestamp(x) for x in months[-int(validation_months):])
    valid_df = d[d["rebalance_date"].isin(valid_months)].copy()
    fit_df = d[~d["rebalance_date"].isin(valid_months)].copy()
    min_valid_rows = max(250, int(0.10 * len(d)))
    min_fit_rows = max(1000, int(0.50 * len(d)))
    if len(valid_df) < min_valid_rows or len(fit_df) < min_fit_rows:
        return d, pd.DataFrame(columns=d.columns)
    return fit_df, valid_df


def walkforward_anchor_index(idx: int, retrain_frequency_months: int) -> int:
    freq = max(int(retrain_frequency_months), 1)
    return int(idx - (idx % freq))


def resolve_optional_catboost() -> dict[str, Any]:
    global _CATBOOST_COMPONENTS_CACHE
    if _CATBOOST_COMPONENTS_CACHE is not None and bool(_CATBOOST_COMPONENTS_CACHE.get("available", False)):
        return _CATBOOST_COMPONENTS_CACHE

    components: dict[str, Any] = {
        "available": False,
        "error": "",
        "CatBoostClassifier": None,
        "CatBoostRanker": None,
        "CatBoostRegressor": None,
        "Pool": None,
    }
    try:
        module = importlib.import_module("catboost")
        components["CatBoostClassifier"] = getattr(module, "CatBoostClassifier", None)
        components["CatBoostRanker"] = getattr(module, "CatBoostRanker", None)
        components["CatBoostRegressor"] = getattr(module, "CatBoostRegressor", None)
        components["Pool"] = getattr(module, "Pool", None)
        missing = [
            key
            for key in ("CatBoostClassifier", "CatBoostRanker", "CatBoostRegressor", "Pool")
            if components[key] is None
        ]
        if missing:
            components["error"] = "catboost import incomplete: missing " + ", ".join(missing)
        else:
            components["available"] = True
    except Exception as exc:
        components["error"] = f"{type(exc).__name__}: {exc}"

    _CATBOOST_COMPONENTS_CACHE = components if bool(components.get("available", False)) else None
    return components


def choose_catboost_task_type() -> str:
    try:
        from catboost.utils import get_gpu_device_count  # type: ignore
        return "GPU" if int(get_gpu_device_count()) > 0 else "CPU"
    except Exception:
        return "CPU"


def monthly_test_dates(df: pd.DataFrame) -> list[pd.Timestamp]:
    d = pd.to_datetime(df["rebalance_date"], errors="coerce").dropna()
    if d.empty:
        return []
    months = pd.Series(sorted(d.unique()))
    return [pd.Timestamp(x) for x in months]


def month_group_ids(dates: pd.Series) -> np.ndarray:
    keys = pd.to_datetime(dates, errors="coerce").dt.strftime("%Y-%m-%d").fillna("missing")
    return pd.factorize(keys, sort=True)[0].astype(int)


def ndcg_at_k(y_true: np.ndarray, y_score: np.ndarray, k: int = 30) -> float:
    if len(y_true) == 0 or len(y_score) == 0:
        return np.nan
    y_true = np.nan_to_num(y_true.astype(float), nan=0.0)
    if np.isfinite(y_true).any():
        y_true = y_true - float(np.nanmin(y_true))
    order = np.argsort(-y_score)[:k]
    ideal = np.argsort(-y_true)[:k]
    gains = np.power(2.0, y_true[order]) - 1.0
    ideal_gains = np.power(2.0, y_true[ideal]) - 1.0
    discounts = 1.0 / np.log2(np.arange(2, len(order) + 2))
    dcg = float(np.sum(gains * discounts))
    idcg = float(np.sum(ideal_gains * discounts))
    return dcg / idcg if idcg > 0 else np.nan


def evaluate_ranking_quality(scored: pd.DataFrame, score_col: str = "score", target_col: str = "y_blend", k: int = 30) -> dict[str, float]:
    if scored is None or scored.empty or score_col not in scored.columns or target_col not in scored.columns:
        return {"months": 0, "rank_ic_mean": np.nan, "ndcg_at_k_mean": np.nan, "precision_at_k_mean": np.nan}

    d = scored.copy()
    d["rebalance_date"] = pd.to_datetime(d["rebalance_date"], errors="coerce")
    rank_ic, ndcg_vals, precision_vals = [], [], []
    for _, g in d.groupby("rebalance_date"):
        g = g.dropna(subset=[score_col, target_col])
        if len(g) < max(10, min(k, 10)):
            continue
        rank_ic.append(float(g[score_col].corr(g[target_col], method="spearman")))
        y_true = pd.to_numeric(g[target_col], errors="coerce").fillna(0.0).values
        y_score = pd.to_numeric(g[score_col], errors="coerce").fillna(0.0).values
        ndcg_vals.append(float(ndcg_at_k(y_true, y_score, k=k)))
        order = np.argsort(-y_score)[: min(k, len(g))]
        top_true = np.argsort(-y_true)[: min(k, len(g))]
        precision_vals.append(float(len(set(order.tolist()) & set(top_true.tolist())) / max(len(order), 1)))
    return {
        "months": int(len(rank_ic)),
        "rank_ic_mean": float(np.nanmean(rank_ic)) if rank_ic else np.nan,
        "ndcg_at_k_mean": float(np.nanmean(ndcg_vals)) if ndcg_vals else np.nan,
        "precision_at_k_mean": float(np.nanmean(precision_vals)) if precision_vals else np.nan,
    }


# Regime-conditional ensemble weight priors (Option A: intuition-based defaults).
# Ridge is more robust in stress regimes; CatBoost dominates in trending growth markets.
# These are used as priors and blended with OOS-learned weights when data is available.
REGIME_ENSEMBLE_WEIGHT_PRIORS: dict[str, dict[str, float]] = {
    "balanced":           {"linear": 0.20, "catboost": 0.45, "ranker": 0.35},
    "growth_reentry":     {"linear": 0.15, "catboost": 0.52, "ranker": 0.33},
    "stagflation":        {"linear": 0.30, "catboost": 0.38, "ranker": 0.32},
    "war_oil_rate_shock": {"linear": 0.35, "catboost": 0.35, "ranker": 0.30},
    "carry_unwind":       {"linear": 0.32, "catboost": 0.38, "ranker": 0.30},
    "systemic_crisis":    {"linear": 0.40, "catboost": 0.32, "ranker": 0.28},
}


def normalized_ensemble_weights_from_cfg(cfg: EngineConfig) -> dict[str, float]:
    raw = {
        "linear": max(float(cfg.ensemble_linear_weight), 0.0),
        "catboost": max(float(cfg.ensemble_cat_weight), 0.0),
        "ranker": max(float(cfg.ensemble_rank_weight), 0.0),
    }
    total = sum(raw.values()) or 1.0
    return {k: float(v / total) for k, v in raw.items()}


def compute_regime_conditional_ensemble_weights(
    history: pd.DataFrame,
    cfg: EngineConfig,
    as_of_date: Optional[Any] = None,
) -> dict[str, dict[str, float]]:
    """Compute per-regime ensemble weights from OOS history (Option B).

    For each known regime label:
    - Filters OOS months matching that regime
    - Computes exponentially-weighted IC quality per model component
    - Blends with REGIME_ENSEMBLE_WEIGHT_PRIORS (Option A) when OOS months are sparse
    - Falls back to global REGIME_ENSEMBLE_WEIGHT_PRIORS when data is insufficient

    Returns dict[regime_label, {"linear": w, "catboost": w, "ranker": w}].
    """
    if not bool(getattr(cfg, "regime_ensemble_weights_enabled", True)):
        return {}

    base_weights = normalized_ensemble_weights_from_cfg(cfg)
    min_months = max(int(getattr(cfg, "regime_ensemble_weights_min_months", 6)), 1)
    strength = float(np.clip(getattr(cfg, "regime_ensemble_weights_strength", 0.50), 0.0, 1.0))
    ic_mix = float(np.clip(getattr(cfg, "adaptive_ensemble_rank_ic_weight", 0.70), 0.0, 1.0))
    half_life = max(float(getattr(cfg, "adaptive_ensemble_recent_half_life_months", 4.0)), 0.25)
    temp = max(float(getattr(cfg, "adaptive_ensemble_temperature", 4.0)), 0.1)
    floor_w = float(np.clip(getattr(cfg, "adaptive_ensemble_floor_weight", 0.10), 0.0, 0.95))

    if history is None or history.empty or "rebalance_date" not in history.columns:
        return {}

    d = history.copy()
    d["rebalance_date"] = pd.to_datetime(d["rebalance_date"], errors="coerce")
    d = d.dropna(subset=["rebalance_date"])
    if as_of_date is not None:
        cutoff = pd.to_datetime(as_of_date, errors="coerce")
        if pd.notna(cutoff):
            d = d[d["rebalance_date"] < cutoff]
    if d.empty or "y_blend" not in d.columns:
        return {}

    # Determine regime label column (same as backtest_portfolio output)
    regime_col = None
    for cand in ("live_event_alert_label", "event_regime_label", "regime_label"):
        if cand in d.columns:
            regime_col = cand
            break
    if regime_col is None:
        return {}

    component_cols = {"linear": "score_linear", "catboost": "score_cat", "ranker": "score_ranker"}
    known_regimes = list(REGIME_ENSEMBLE_WEIGHT_PRIORS.keys())
    result: dict[str, dict[str, float]] = {}

    for regime in known_regimes:
        prior = REGIME_ENSEMBLE_WEIGHT_PRIORS[regime]
        # Normalize prior
        prior_total = sum(prior.values()) or 1.0
        prior_norm = {k: float(v / prior_total) for k, v in prior.items()}

        regime_data = d[d[regime_col].astype(str) == regime]
        months = sorted(regime_data["rebalance_date"].dropna().unique().tolist())

        if len(months) < min_months:
            # Not enough regime history — use prior blended toward global base
            blend = 0.40  # light prior when data absent
            blended = {
                k: blend * prior_norm.get(k, base_weights[k]) + (1.0 - blend) * base_weights[k]
                for k in base_weights
            }
            total = sum(blended.values()) or 1.0
            result[regime] = {k: float(v / total) for k, v in blended.items()}
            continue

        # Compute exponentially-decayed IC quality per component for this regime
        quality_map: dict[str, float] = {}
        for name, col in component_cols.items():
            if col not in regime_data.columns:
                quality_map[name] = np.nan
                continue
            monthly_scores: list[float] = []
            monthly_wts: list[float] = []
            for age, month in enumerate(reversed(months)):
                g = regime_data[regime_data["rebalance_date"] == pd.Timestamp(month)].copy()
                g = g.dropna(subset=["y_blend", col])
                if len(g) < 10:
                    continue
                rank_ic = g[col].corr(g["y_blend"], method="spearman")
                y_true = pd.to_numeric(g["y_blend"], errors="coerce").fillna(0.0).values
                y_score = pd.to_numeric(g[col], errors="coerce").fillna(0.0).values
                top_n = min(max(10, int(getattr(cfg, "rank_eval_top_k", 30))), len(g))
                order = np.argsort(-y_score)[:top_n]
                ideal = np.argsort(-y_true)[:top_n]
                precision = float(len(set(order.tolist()) & set(ideal.tolist())) / max(top_n, 1))
                component_quality = (
                    ic_mix * float(np.nan_to_num(rank_ic, nan=0.0))
                    + (1.0 - ic_mix) * float(np.nan_to_num((precision - 0.5) * 2.0, nan=0.0))
                )
                monthly_scores.append(component_quality)
                monthly_wts.append(float(0.5 ** (age / half_life)))
            if monthly_scores and sum(monthly_wts) > 0:
                quality_map[name] = float(np.average(monthly_scores, weights=monthly_wts))
            else:
                quality_map[name] = np.nan

        usable = {k: v for k, v in quality_map.items() if pd.notna(v)}
        if len(usable) < 2:
            # Fall back to prior
            result[regime] = prior_norm.copy()
            continue

        # Softmax over quality scores
        quality_vals = pd.Series(usable, dtype=float)
        shifted = quality_vals - float(quality_vals.max())
        adaptive = np.exp(temp * shifted)
        adaptive = adaptive.clip(lower=floor_w)
        adaptive = adaptive / adaptive.sum()

        # Blend: OOS learned ← strength → global base, then blend with prior
        learned: dict[str, float] = {}
        for name in base_weights:
            a_w = float(adaptive.get(name, base_weights[name]))
            learned[name] = (1.0 - strength) * base_weights[name] + strength * a_w
        learned_total = sum(learned.values()) or 1.0
        learned = {k: float(v / learned_total) for k, v in learned.items()}

        # Final: blend OOS-learned with prior (prior anchors when OOS regime months are few)
        prior_weight = float(np.exp(-0.3 * max(len(months) - min_months, 0)))
        final = {
            k: prior_weight * prior_norm.get(k, learned[k]) + (1.0 - prior_weight) * learned[k]
            for k in base_weights
        }
        final_total = sum(final.values()) or 1.0
        result[regime] = {k: float(v / final_total) for k, v in final.items()}

    return result


def compute_adaptive_ensemble_state(
    history: pd.DataFrame,
    cfg: EngineConfig,
    as_of_date: Optional[Any] = None,
) -> dict[str, Any]:
    base_weights = normalized_ensemble_weights_from_cfg(cfg)
    state = {
        "weights": base_weights.copy(),
        "quality": {k: np.nan for k in base_weights},
        "history_months": 0,
        "active": False,
    }
    if (not bool(getattr(cfg, "adaptive_ensemble_enabled", False))) or history is None or history.empty:
        return state

    d = history.copy()
    if "rebalance_date" not in d.columns:
        return state
    d["rebalance_date"] = pd.to_datetime(d["rebalance_date"], errors="coerce")
    d = d.dropna(subset=["rebalance_date"])
    if as_of_date is not None:
        cutoff = pd.to_datetime(as_of_date, errors="coerce")
        if pd.notna(cutoff):
            d = d[d["rebalance_date"] < cutoff]
    if d.empty or "y_blend" not in d.columns:
        return state

    months = sorted(pd.Series(d["rebalance_date"].dropna().unique()).tolist())
    if not months:
        return state
    lookback = max(int(getattr(cfg, "adaptive_ensemble_lookback_months", 12)), 1)
    min_months = max(int(getattr(cfg, "adaptive_ensemble_min_months", 6)), 1)
    months = months[-lookback:]
    if len(months) < min_months:
        state["history_months"] = int(len(months))
        return state

    half_life = max(float(getattr(cfg, "adaptive_ensemble_recent_half_life_months", 4.0)), 0.25)
    ic_mix = float(np.clip(getattr(cfg, "adaptive_ensemble_rank_ic_weight", 0.70), 0.0, 1.0))
    component_cols = {
        "linear": "score_linear",
        "catboost": "score_cat",
        "ranker": "score_ranker",
    }
    quality_map: dict[str, float] = {}
    for name, col in component_cols.items():
        if col not in d.columns:
            quality_map[name] = np.nan
            continue
        monthly_scores: list[float] = []
        monthly_weights: list[float] = []
        for age, month in enumerate(reversed(months)):
            g = d[d["rebalance_date"] == pd.Timestamp(month)].copy()
            g = g.dropna(subset=["y_blend", col])
            if len(g) < 15:
                continue
            rank_ic = g[col].corr(g["y_blend"], method="spearman")
            y_true = pd.to_numeric(g["y_blend"], errors="coerce").fillna(0.0).values
            y_score = pd.to_numeric(g[col], errors="coerce").fillna(0.0).values
            precision = np.nan
            if len(g) >= 10:
                top_n = min(int(max(10, getattr(cfg, "rank_eval_top_k", 30))), len(g))
                order = np.argsort(-y_score)[:top_n]
                ideal = np.argsort(-y_true)[:top_n]
                precision = float(len(set(order.tolist()) & set(ideal.tolist())) / max(top_n, 1))
            component_quality = (
                ic_mix * float(np.nan_to_num(rank_ic, nan=0.0))
                + (1.0 - ic_mix) * float(np.nan_to_num((precision - 0.5) * 2.0, nan=0.0))
            )
            monthly_scores.append(component_quality)
            monthly_weights.append(float(0.5 ** (age / half_life)))
        if monthly_scores and sum(monthly_weights) > 0:
            quality_map[name] = float(np.average(monthly_scores, weights=monthly_weights))
        else:
            quality_map[name] = np.nan

    usable = {k: v for k, v in quality_map.items() if pd.notna(v)}
    state["quality"] = quality_map
    state["history_months"] = int(len(months))
    if len(usable) < 2:
        return state

    quality_vals = pd.Series(usable, dtype=float)
    temp = max(float(getattr(cfg, "adaptive_ensemble_temperature", 4.0)), 0.1)
    shifted = quality_vals - float(quality_vals.max())
    adaptive = np.exp(temp * shifted)
    adaptive = adaptive / adaptive.sum()
    floor_w = float(np.clip(getattr(cfg, "adaptive_ensemble_floor_weight", 0.10), 0.0, 0.95))
    adaptive = adaptive.clip(lower=floor_w)
    adaptive = adaptive / adaptive.sum()
    strength = float(np.clip(getattr(cfg, "adaptive_ensemble_strength", 0.65), 0.0, 1.0))
    final = {}
    for name in base_weights:
        adaptive_w = float(adaptive.get(name, base_weights[name]))
        final[name] = (1.0 - strength) * float(base_weights[name]) + strength * adaptive_w
    total = sum(final.values()) or 1.0
    final = {k: float(v / total) for k, v in final.items()}
    state["weights"] = final
    state["active"] = True
    return state


def apply_adaptive_ensemble_state(
    df: pd.DataFrame,
    state: Optional[dict[str, Any]],
    regime_weights: Optional[dict[str, dict[str, float]]] = None,
) -> pd.DataFrame:
    """Apply ensemble weights to df.

    When `regime_weights` is provided, weights are applied per-row based on the
    regime label in `live_event_alert_label` (falling back to global `state["weights"]`).
    This enables regime-conditional model blending (Option A+B dynamic ensemble).
    """
    d = df.copy()
    global_weights = ((state or {}).get("weights") or {}) if state is not None else {}
    active = bool((state or {}).get("active", False)) if state is not None else False
    history_months = int((state or {}).get("history_months", 0) or 0) if state is not None else 0
    quality = ((state or {}).get("quality") or {}) if state is not None else {}

    if regime_weights:
        # Determine per-row regime label
        regime_col = None
        for cand in ("live_event_alert_label", "event_regime_label"):
            if cand in d.columns:
                regime_col = cand
                break
        if regime_col is not None:
            labels = d[regime_col].astype(str).fillna("balanced")
            d["ensemble_weight_linear"] = labels.map(
                lambda r: float(regime_weights.get(r, global_weights).get("linear", global_weights.get("linear", 0.0)))
            )
            d["ensemble_weight_catboost"] = labels.map(
                lambda r: float(regime_weights.get(r, global_weights).get("catboost", global_weights.get("catboost", 0.0)))
            )
            d["ensemble_weight_ranker"] = labels.map(
                lambda r: float(regime_weights.get(r, global_weights).get("ranker", global_weights.get("ranker", 0.0)))
            )
            d["regime_ensemble_active"] = True
        else:
            d["ensemble_weight_linear"] = float(global_weights.get("linear", 0.0))
            d["ensemble_weight_catboost"] = float(global_weights.get("catboost", 0.0))
            d["ensemble_weight_ranker"] = float(global_weights.get("ranker", 0.0))
            d["regime_ensemble_active"] = False
    else:
        d["ensemble_weight_linear"] = float(global_weights.get("linear", 0.0))
        d["ensemble_weight_catboost"] = float(global_weights.get("catboost", 0.0))
        d["ensemble_weight_ranker"] = float(global_weights.get("ranker", 0.0))
        d["regime_ensemble_active"] = False

    d["adaptive_ensemble_active"] = bool(active)
    d["adaptive_ensemble_history_months"] = int(history_months)
    d["adaptive_quality_linear"] = float(np.nan_to_num(quality.get("linear"), nan=0.0))
    d["adaptive_quality_catboost"] = float(np.nan_to_num(quality.get("catboost"), nan=0.0))
    d["adaptive_quality_ranker"] = float(np.nan_to_num(quality.get("ranker"), nan=0.0))
    return d


def add_model_score_columns(month_df: pd.DataFrame, pred_cols: dict[str, str], cfg: Optional[EngineConfig] = None) -> pd.DataFrame:
    d = month_df.copy()
    for c in pred_cols.values():
        if c not in d.columns:
            d[c] = 0.0
    d["z_lin_ret"] = robust_z(d[pred_cols["lin_ret"]]).fillna(0.0)
    d["z_lin_p"] = robust_z(d[pred_cols["lin_p"]]).fillna(0.0)
    d["z_cat_ret"] = robust_z(d[pred_cols["cat_ret"]]).fillna(0.0)
    d["z_cat_p"] = robust_z(d[pred_cols["cat_p"]]).fillna(0.0)
    rank_col = pred_cols.get("rank")
    if rank_col and rank_col in d.columns:
        d["z_rank"] = robust_z(d[rank_col]).fillna(0.0)
    else:
        d["z_rank"] = 0.0
    d["score_linear"] = 0.65 * d["z_lin_ret"] + 0.35 * d["z_lin_p"]
    d["score_cat"] = 0.65 * d["z_cat_ret"] + 0.35 * d["z_cat_p"]
    d["score_ranker"] = d["z_rank"]
    vol_pen = robust_z(winsorize(d["vol_252d"], 0.01)).fillna(0.0)
    dd_pen = robust_z(winsorize(d["dd_1y"], 0.01)).fillna(0.0)
    liq_pen = robust_z(winsorize(-d["dollar_vol_20d"], 0.01)).fillna(0.0)
    mom1_heat = cross_sectional_robust_z(d, "mom_1m").clip(lower=0.0).fillna(0.0)
    dist_ma200_heat = cross_sectional_robust_z(d, "dist_ma200").clip(lower=0.0).fillna(0.0)
    near_high_heat = cross_sectional_robust_z(d, "near_52w_high_pct").clip(lower=0.0).fillna(0.0)
    rsi14 = numeric_series_or_default(d, "rsi14", np.nan)
    bb_pb = numeric_series_or_default(d, "bb_pb", np.nan)
    rsi_cutoff = float(cfg.overheat_rsi_threshold) if cfg is not None else 68.0
    bb_cutoff = float(cfg.overheat_bb_pb_threshold) if cfg is not None else 0.92
    rsi_heat = ((rsi14 - rsi_cutoff) / 10.0).clip(lower=0.0).fillna(0.0)
    bb_heat = ((bb_pb - bb_cutoff) / 0.25).clip(lower=0.0).fillna(0.0)
    trend_heat = row_mean(
        [
            cross_sectional_robust_z(d, "mom_3m").clip(lower=0.0).fillna(0.0),
            cross_sectional_robust_z(d, "mom_6m").clip(lower=0.0).fillna(0.0),
        ],
        d.index,
    ).fillna(0.0)
    d["overheat_signal_score"] = (
        0.28 * mom1_heat
        + 0.22 * dist_ma200_heat
        + 0.20 * near_high_heat
        + 0.15 * rsi_heat
        + 0.15 * bb_heat
        + 0.15 * trend_heat
    ).fillna(0.0)
    overheat_trigger = float(cfg.overheat_penalty_trigger) if cfg is not None else 0.55
    overheat_scale = float(cfg.overheat_penalty_scale) if cfg is not None else 0.35
    breadth_regime = numeric_series_or_default(d, "market_breadth_regime_score", 0.50).clip(lower=0.0, upper=1.0)
    leadership_narrowing = numeric_series_or_default(d, "market_leadership_narrowing", 0.50).clip(lower=0.0, upper=1.0)
    market_overheat_ratio = numeric_series_or_default(d, "market_overheat_ratio", 0.0).clip(lower=0.0, upper=1.0)
    overheat_multiplier = (
        1.0
        + 0.55 * np.clip(0.50 - breadth_regime, 0.0, None)
        + 0.35 * np.clip(leadership_narrowing - 0.55, 0.0, None)
        + 0.25 * np.clip(market_overheat_ratio - 0.28, 0.0, None)
    )
    d["overheat_penalty"] = (
        overheat_scale
        * overheat_multiplier
        * (pd.to_numeric(d["overheat_signal_score"], errors="coerce").fillna(0.0) - overheat_trigger).clip(lower=0.0)
    ).clip(lower=0.0, upper=3.0)
    scale = float(cfg.risk_penalty_scale) if cfg is not None else 1.0
    d["risk_penalty"] = scale * (0.7 * vol_pen + 0.7 * dd_pen + 0.8 * liq_pen) + d["overheat_penalty"]
    return d


def train_walkforward(cfg: dict | EngineConfig, features: pd.DataFrame) -> ModelBundle:
    cfg = to_cfg(cfg)
    paths = get_paths(cfg)
    model_features = model_feature_columns(cfg)
    phase4_fp = reuse_fingerprint(cfg, "phase4_modeling")
    log("Phase 4: monthly walk-forward training ...")
    catboost_components = resolve_optional_catboost()
    catboost_available = bool(catboost_components.get("available", False))
    CatBoostClassifier = catboost_components.get("CatBoostClassifier")
    CatBoostRanker = catboost_components.get("CatBoostRanker")
    CatBoostRegressor = catboost_components.get("CatBoostRegressor")
    Pool = catboost_components.get("Pool")
    if not catboost_available:
        log(
            "[WARN] Phase 4: catboost unavailable; continuing with linear-only walk-forward models. "
            f"reason={catboost_components.get('error') or 'not installed'}"
        )

    d = features.copy()
    if "rebalance_date" not in d.columns and "Date" in d.columns:
        d = d.rename(columns={"Date": "rebalance_date"})
    d["rebalance_date"] = pd.to_datetime(d["rebalance_date"], errors="coerce")
    d["feature_date"] = pd.to_datetime(d["feature_date"], errors="coerce")
    if d["feature_date"].notna().sum() == 0 and d["rebalance_date"].notna().sum() > 0:
        d["feature_date"] = d["rebalance_date"]
    d = clear_latest_only_signal_columns(d)
    d = d.sort_values(["rebalance_date", "ticker"]).reset_index(drop=True)

    for f in model_features:
        if f not in d.columns:
            d[f] = 0.0

    mktcap_cov = float(d["mktcap"].notna().mean()) if len(d) else 0.0
    if mktcap_cov >= 0.25:
        d = d[d["mktcap"].notna()]
    else:
        log(f"[WARN] train mktcap coverage too low ({mktcap_cov:.2%}); skipping mktcap-notna filter.")
    d = d[d["px"].fillna(0) >= cfg.min_price]
    dv = pd.to_numeric(d["dollar_vol_20d"], errors="coerce")
    min_dv = cfg.min_dollar_vol_20d
    dv_max = float(np.nanmax(dv.values)) if len(dv.dropna()) else np.nan
    if pd.notna(dv_max) and dv_max <= 1_100_000 and cfg.min_dollar_vol_20d > dv_max:
        log(
            "[WARN] dollar_vol_20d appears clipped/low-scale. "
            f"Auto-relaxing min_dollar_vol_20d from {cfg.min_dollar_vol_20d:,.0f} to 500,000."
        )
        min_dv = 500_000.0
    d = d[dv.fillna(0) >= min_dv]
    d = d[d["feature_date"].notna()]
    d = d[d["r_1m"].notna() | d["r_3m"].notna() | d["r_6m"].notna()]
    d = hard_sanitize(
        d,
        model_features
        + ["r_1m", "r_3m", "r_6m", "r_12m", "r_24m", "r_36m", "bench_r_1m", "bench_r_3m", "bench_r_6m", "bench_r_12m", "bench_r_24m", "bench_r_36m", "mktcap"],
        clip=1e12,
    )

    y_all, ybin_all = make_targets(d, cfg)
    d["y_blend"] = y_all
    d["y_bin"] = ybin_all
    future_y_all, future_ybin_all, future_avail_all = make_future_winner_targets(d, cfg)
    d["future_winner_y"] = future_y_all
    d["future_winner_bin"] = future_ybin_all
    d["future_winner_available"] = future_avail_all

    dates = monthly_test_dates(d)
    if not dates:
        raise RuntimeError(
            "No test months available for walk-forward training. "
            f"rows_after_filters={len(d)}, rebalance_notna={int(d['rebalance_date'].notna().sum())}, "
            f"feature_notna={int(d['feature_date'].notna().sum())}, "
            f"labels_notna={int((d['r_1m'].notna() | d['r_3m'].notna() | d['r_6m'].notna()).sum())}"
        )

    task_type = choose_catboost_task_type() if catboost_available else "CPU"
    if catboost_available:
        log(f"CatBoost task type = {task_type}")
    retrain_every = max(int(cfg.walkforward_retrain_frequency_months), 1)
    early_stopping_rounds = max(int(cfg.cat_early_stopping_rounds), 0)

    partial_scored = pd.DataFrame()
    completed_dates = set()
    if cfg.resume_partial_walkforward:
        progress = load_walkforward_progress(paths)
        progress_fp = str(progress.get("extra", {}).get("fingerprint", ""))
        partial_path = walkforward_partial_scored_path(paths)
        if partial_path.exists() and progress_fp == phase4_fp:
            try:
                partial_scored = pd.read_parquet(partial_path)
                partial_scored["rebalance_date"] = pd.to_datetime(partial_scored["rebalance_date"], errors="coerce")
                completed_dates |= set(
                    partial_scored["rebalance_date"].dropna().dt.strftime("%Y-%m-%d").astype(str).tolist()
                )
            except Exception:
                partial_scored = pd.DataFrame()
        if progress_fp == phase4_fp:
            completed_dates |= set(str(x) for x in progress.get("completed_dates", []))

    pending_dates = [pd.Timestamp(x) for x in dates if pd.Timestamp(x).strftime("%Y-%m-%d") not in completed_dates]
    pending_anchor_indices = sorted(
        {
            walkforward_anchor_index(i, retrain_every)
            for i, x in enumerate(dates)
            if pd.Timestamp(x).strftime("%Y-%m-%d") not in completed_dates
        }
    )
    fits_per_retrain = (2 + int(cfg.ranking_enabled)) if catboost_available else 0
    log(
        f"Phase 4 plan: pending_months={len(pending_dates)}/{len(dates)}, "
        f"retrain_every_months={retrain_every}, pending_retrains={len(pending_anchor_indices)}, "
        f"catboost_fits_per_retrain<={fits_per_retrain}."
    )

    oos_rows = [partial_scored] if not partial_scored.empty else []
    lin_coef_acc = []
    completed_now = 0
    current_anchor_idx: Optional[int] = None
    current_scaler: Optional[dict[str, dict[str, float]]] = None
    current_reg: Optional[Ridge] = None
    current_clf: Optional[LogisticRegression] = None
    current_future_reg: Optional[Ridge] = None
    current_future_clf: Optional[LogisticRegression] = None
    current_cbr: Optional[Any] = None
    current_cbc: Optional[Any] = None
    current_cbrk: Optional[Any] = None
    current_rank_enabled = bool(cfg.ranking_enabled and catboost_available)

    for idx, test_dt in enumerate(dates):
        date_key = pd.Timestamp(test_dt).strftime("%Y-%m-%d")
        if date_key in completed_dates:
            continue
        test_mask = d["rebalance_date"] == test_dt
        if test_mask.sum() == 0:
            continue
        test_df = d[test_mask].copy()
        anchor_idx = walkforward_anchor_index(idx, retrain_every)
        need_retrain = current_scaler is None or current_anchor_idx != anchor_idx
        if need_retrain:
            anchor_dt = pd.Timestamp(dates[anchor_idx])
            anchor_train_end = anchor_dt - pd.Timedelta(days=cfg.embargo_days)
            anchor_train_start = anchor_dt - pd.DateOffset(years=cfg.train_lookback_years)
            anchor_train_mask = (d["feature_date"] >= anchor_train_start) & (d["feature_date"] <= anchor_train_end)
            anchor_train_df = d[anchor_train_mask].copy()

            if len(anchor_train_df) < cfg.min_train_samples:
                current_train_end = test_dt - pd.Timedelta(days=cfg.embargo_days)
                current_train_start = test_dt - pd.DateOffset(years=cfg.train_lookback_years)
                current_train_mask = (d["feature_date"] >= current_train_start) & (d["feature_date"] <= current_train_end)
                anchor_train_df = d[current_train_mask].copy()
            if len(anchor_train_df) < cfg.min_train_samples:
                continue

            fit_df, valid_df = split_walkforward_train_valid(anchor_train_df, cfg.cat_validation_months)
            current_scaler = fit_scaler(fit_df, model_features)
            X_fit = apply_scaler(fit_df, current_scaler, model_features)
            y_fit = fit_df["y_blend"].values
            ybin_fit = fit_df["y_bin"].values
            X_valid = np.empty((0, 0))
            y_valid = np.array([])
            valid_groups = np.array([], dtype=int)
            use_eval = not valid_df.empty and early_stopping_rounds > 0
            if use_eval:
                X_valid = apply_scaler(valid_df, current_scaler, model_features)
                y_valid = valid_df["y_blend"].values
                valid_groups = month_group_ids(valid_df["rebalance_date"])

            current_reg = Ridge(alpha=cfg.ridge_alpha, fit_intercept=True, random_state=cfg.random_seed)
            current_reg.fit(X_fit, y_fit)
            lin_coef_acc.append(current_reg.coef_)

            if len(np.unique(ybin_fit)) >= 2:
                current_clf = LogisticRegression(C=cfg.logreg_c, max_iter=1200, random_state=cfg.random_seed)
                current_clf.fit(X_fit, ybin_fit)
            else:
                current_clf = None

            future_fit_df = fit_df[fit_df["future_winner_available"].fillna(False).astype(bool)].copy()
            current_future_reg = None
            current_future_clf = None
            if len(future_fit_df) >= max(500, cfg.min_train_samples // 4):
                X_fit_future = apply_scaler(future_fit_df, current_scaler, model_features)
                y_future_fit = pd.to_numeric(future_fit_df["future_winner_y"], errors="coerce").fillna(0.0).values
                current_future_reg = Ridge(
                    alpha=max(float(cfg.ridge_alpha) * 0.75, 0.10),
                    fit_intercept=True,
                    random_state=cfg.random_seed,
                )
                current_future_reg.fit(X_fit_future, y_future_fit)
                ybin_future_fit = pd.to_numeric(
                    future_fit_df["future_winner_bin"], errors="coerce"
                ).fillna(0).astype(int).values
                if len(np.unique(ybin_future_fit)) >= 2 and int(ybin_future_fit.sum()) >= max(40, int(0.02 * len(ybin_future_fit))):
                    current_future_clf = LogisticRegression(
                        C=max(float(cfg.logreg_c) * 0.8, 0.25),
                        max_iter=1200,
                        random_state=cfg.random_seed,
                    )
                    current_future_clf.fit(X_fit_future, ybin_future_fit)

            current_cbr = None
            current_cbc = None
            current_cbrk = None
            current_rank_enabled = bool(cfg.ranking_enabled and catboost_available)

            if catboost_available:
                try:
                    current_cbr = CatBoostRegressor(
                        loss_function="RMSE",
                        iterations=cfg.cat_reg_iterations,
                        depth=cfg.cat_depth,
                        learning_rate=cfg.cat_learning_rate,
                        random_seed=cfg.random_seed,
                        verbose=False,
                        task_type=task_type,
                    )
                    fit_kwargs = {}
                    if use_eval:
                        fit_kwargs = {
                            "eval_set": (X_valid, y_valid),
                            "use_best_model": True,
                            "early_stopping_rounds": early_stopping_rounds,
                        }
                    current_cbr.fit(X_fit, y_fit, **fit_kwargs)
                except Exception:
                    current_cbr = None

            if len(np.unique(ybin_fit)) >= 2 and catboost_available:
                try:
                    current_cbc = CatBoostClassifier(
                        loss_function="Logloss",
                        iterations=cfg.cat_cls_iterations,
                        depth=cfg.cat_depth,
                        learning_rate=cfg.cat_learning_rate,
                        random_seed=cfg.random_seed,
                        verbose=False,
                        task_type=task_type,
                    )
                    fit_kwargs = {}
                    if use_eval:
                        fit_kwargs = {
                            "eval_set": (X_valid, valid_df["y_bin"].values),
                            "use_best_model": True,
                            "early_stopping_rounds": early_stopping_rounds,
                        }
                    current_cbc.fit(X_fit, ybin_fit, **fit_kwargs)
                except Exception:
                    current_cbc = None

            if catboost_available and cfg.ranking_enabled:
                try:
                    current_cbrk = CatBoostRanker(
                        loss_function="YetiRankPairwise",
                        eval_metric=f"NDCG:top={max(int(cfg.rank_eval_top_k), 5)}",
                        iterations=cfg.cat_rank_iterations,
                        depth=cfg.cat_depth,
                        learning_rate=cfg.cat_learning_rate,
                        random_seed=cfg.random_seed,
                        verbose=False,
                        task_type=task_type,
                    )
                    train_pool = Pool(X_fit, y_fit, group_id=month_group_ids(fit_df["rebalance_date"]))
                    fit_kwargs = {}
                    if use_eval:
                        eval_pool = Pool(X_valid, y_valid, group_id=valid_groups)
                        fit_kwargs = {
                            "eval_set": eval_pool,
                            "use_best_model": True,
                            "early_stopping_rounds": early_stopping_rounds,
                        }
                    current_cbrk.fit(train_pool, **fit_kwargs)
                except Exception:
                    current_cbrk = None
            current_anchor_idx = anchor_idx

        if current_scaler is None or current_reg is None:
            continue

        X_test = apply_scaler(test_df, current_scaler, model_features)
        lin_ret = current_reg.predict(X_test)
        if current_clf is not None:
            lin_p = current_clf.predict_proba(X_test)[:, 1]
        else:
            lin_p = np.zeros(len(test_df))
        if current_future_reg is not None:
            future_ret = current_future_reg.predict(X_test)
        else:
            future_ret = np.zeros(len(test_df))
        if current_future_clf is not None:
            future_p = current_future_clf.predict_proba(X_test)[:, 1]
        else:
            future_p = np.zeros(len(test_df))

        cat_ret = current_cbr.predict(X_test) if current_cbr is not None else np.zeros(len(test_df))
        cat_p = current_cbc.predict_proba(X_test)[:, 1] if current_cbc is not None else np.zeros(len(test_df))
        rank_pred = current_cbrk.predict(X_test) if (current_rank_enabled and current_cbrk is not None) else np.zeros(len(test_df))

        tmp = test_df.copy()
        tmp["pred_lin_ret"] = lin_ret
        tmp["pred_lin_p"] = lin_p
        tmp["pred_future_winner_ret"] = future_ret
        tmp["pred_future_winner_p"] = future_p
        tmp["pred_cat_ret"] = cat_ret
        tmp["pred_cat_p"] = cat_p
        tmp["pred_rank"] = rank_pred
        tmp = add_model_score_columns(
            tmp,
            {
                "lin_ret": "pred_lin_ret",
                "lin_p": "pred_lin_p",
                "cat_ret": "pred_cat_ret",
                "cat_p": "pred_cat_p",
                "rank": "pred_rank",
            },
            cfg=cfg,
        )
        adaptive_history = pd.concat(oos_rows, ignore_index=True) if oos_rows else pd.DataFrame()
        adaptive_state = compute_adaptive_ensemble_state(adaptive_history, cfg, as_of_date=test_dt)
        month_regime_weights = (
            compute_regime_conditional_ensemble_weights(adaptive_history, cfg, as_of_date=test_dt)
            if bool(getattr(cfg, "regime_ensemble_weights_enabled", True)) and not adaptive_history.empty
            else None
        )
        tmp = apply_adaptive_ensemble_state(tmp, adaptive_state, regime_weights=month_regime_weights)
        tmp = add_total_score_columns(tmp, cfg, include_satellite=True)
        tmp = apply_focus_score_overlay(tmp, cfg)
        oos_rows.append(tmp)
        completed_dates.add(date_key)
        completed_now += 1
        if cfg.resume_partial_walkforward and (
            completed_now == len(pending_dates)
            or (completed_now % int(cfg.walkforward_checkpoint_every) == 0)
        ):
            partial = pd.concat(oos_rows, ignore_index=True) if oos_rows else pd.DataFrame()
            partial.to_parquet(walkforward_partial_scored_path(paths), index=False)
            save_walkforward_progress(
                paths,
                completed_dates,
                {
                    "completed_count": len(completed_dates),
                    "total_dates": len(dates),
                    "last_completed_date": date_key,
                    "fingerprint": phase4_fp,
                },
            )
            log(f"Phase 4 progress: completed_months={len(completed_dates)}/{len(dates)} (latest={date_key})")

    if not oos_rows:
        raise RuntimeError("No OOS rows were generated in walk-forward training.")
    scored = pd.concat(oos_rows, ignore_index=True)
    scored = scored.sort_values(["rebalance_date", "score"], ascending=[True, False])
    scored = scored.drop_duplicates(["rebalance_date", "ticker"], keep="last")
    scored.to_parquet(paths["feature_store"] / "scored_oos_latest.parquet", index=False)
    if cfg.resume_partial_walkforward:
        save_walkforward_progress(
            paths,
            completed_dates,
            {
                "completed_count": len(completed_dates),
                "total_dates": len(dates),
                "status": "completed",
                "fingerprint": phase4_fp,
            },
        )
    ranking_metrics = evaluate_ranking_quality(scored, score_col="score", target_col="y_blend", k=cfg.rank_eval_top_k)
    adaptive_state_latest = compute_adaptive_ensemble_state(scored, cfg)
    regime_ens_weights = compute_regime_conditional_ensemble_weights(scored, cfg)

    coef = np.nanmean(np.vstack(lin_coef_acc), axis=0) if lin_coef_acc else np.zeros(len(model_features))
    coef_map = {f: float(c) for f, c in zip(model_features, coef.tolist())}
    denom = sum(abs(v) for v in coef_map.values()) or 1.0
    coef_map = {k: v / denom for k, v in coef_map.items()}

    bundle = ModelBundle(
        task_type=task_type,
        ensemble_weights={
            "linear": cfg.ensemble_linear_weight,
            "catboost": cfg.ensemble_cat_weight,
            "ranker": cfg.ensemble_rank_weight,
        },
        linear_feature_weights=coef_map,
        score_columns=[
            "score_linear",
            "score_cat",
            "score_ranker",
            "score_core",
            "score_satellite",
            "score_future_winner_model",
            "risk_penalty",
            "quality_trend_score",
            "event_reaction_score",
            "score",
        ],
        oos_rows=len(scored),
        ranking_enabled=bool(cfg.ranking_enabled),
        target_spec={
            "r_1m": float(cfg.target_blend_1m),
            "r_3m": float(cfg.target_blend_3m),
            "r_6m": float(cfg.target_blend_6m),
            "target_excess_weight": float(cfg.target_excess_weight),
            "future_r_12m": float(cfg.future_target_blend_12m),
            "future_r_24m": float(cfg.future_target_blend_24m),
            "future_r_36m": float(cfg.future_target_blend_36m),
            "future_target_excess_weight": float(cfg.future_target_excess_weight),
            "benchmark_history_source": benchmark_history_source_label(cfg),
        },
        ranking_metrics=ranking_metrics,
        adaptive_ensemble_weights={k: float(v) for k, v in adaptive_state_latest.get("weights", {}).items()},
        adaptive_ensemble_diagnostics={
            "history_months": int(adaptive_state_latest.get("history_months", 0)),
            "active": bool(adaptive_state_latest.get("active", False)),
            "quality": {
                str(k): float(np.nan_to_num(v, nan=0.0))
                for k, v in dict(adaptive_state_latest.get("quality", {})).items()
            },
        },
        regime_ensemble_weights={
            regime: {k: float(v) for k, v in w.items()}
            for regime, w in (regime_ens_weights or {}).items()
        },
    )
    (paths["models"] / "model_bundle_latest.json").write_text(json.dumps(asdict(bundle), indent=2))
    save_phase4_latest_scoring_artifacts(
        paths,
        model_features,
        current_scaler,
        current_reg,
        current_clf,
        current_future_reg,
        current_future_clf,
        current_cbr,
        current_cbc,
        current_cbrk,
        current_rank_enabled,
    )
    return bundle


@dataclass
class BacktestResult:
    holdings: pd.DataFrame
    monthly_returns: pd.DataFrame
    metrics: dict[str, Any]
    equity_curve: pd.DataFrame


# Stage 4b-ii (2026-04-20): 10 portfolio helpers (compute_dynamic_sector_caps ..
# apply_hold_policy_overlay) -> r1000_signals.py.




# Stage 6 Subtractive (2026-04-20): 17 _legacy_unused_* dead functions removed
# (-2,307L). Zero callers verified via grep. List:
#   _legacy_unused_compute_portfolio_sleeve_columns       (96L)
#   _legacy_unused_compute_portfolio_sleeve_policy        (163L)
#   _legacy_unused_build_target_portfolio                 (592L)
#   _legacy_unused_normalize_with_limits                   (41L)
#   _legacy_unused_apply_sector_weight_caps                (86L)
#   _legacy_unused_dict_from_weights                        (2L)
#   _legacy_unused_apply_cash_buffer_to_weights            (25L)
#   _legacy_unused_turnover                                 (3L)
#   _legacy_unused_cap_turnover                            (11L)
#   _legacy_unused_accelerate_cash_deployment              (50L)
#   _legacy_unused_month_forward_return_open               (19L)
#   _legacy_unused_performance_metrics                     (23L)
#   _legacy_unused_run_acceptance_checks                  (144L)
#   _legacy_unused_backtest_portfolio                     (600L)
#   _legacy_unused_build_latest_recommendations           (352L)
#   _legacy_unused_fallback_latest_recommendations_from_scored (68L)
#   _legacy_unused_bt_metrics_row                          (32L)
# The active versions of each are either in r1000_signals.py (Stage 4b-ii)
# or remain in main as Stage 5 targets (backtest_portfolio, etc.).




def compare_portfolio_size_backtests(
    cfg: dict | EngineConfig,
    signals: pd.DataFrame,
    sizes: Optional[Iterable[int]] = None,
) -> pd.DataFrame:
    cfg_obj = to_cfg(cfg)
    candidates = sizes if sizes is not None else cfg_obj.portfolio_size_comparison_sizes
    clean_sizes = sorted({int(x) for x in candidates if int(x) >= 1})
    bt_dynamic = backtest_portfolio(cfg_obj, signals)
    rows = [_bt_metrics_row(bt_dynamic, cfg_obj, portfolio_mode="dynamic",
                            target_stock_names=int(round(float(bt_dynamic.metrics.get("avg_stock_names", 0.0)))))]
    for size in clean_sizes:
        rows.append(_bt_metrics_row(
            backtest_portfolio(cfg_obj, signals, target_n_override=size),
            cfg_obj, portfolio_mode="fixed", target_stock_names=int(size)))
    return pd.DataFrame(rows).sort_values(["target_stock_names", "portfolio_mode"]).reset_index(drop=True)


def compare_rebalance_interval_backtests(
    cfg: dict | EngineConfig,
    signals: pd.DataFrame,
    intervals: Optional[Iterable[int]] = None,
) -> pd.DataFrame:
    cfg_obj = to_cfg(cfg)
    candidates = intervals if intervals is not None else cfg_obj.rebalance_interval_comparison_months
    clean_intervals = sorted({int(x) for x in candidates if int(x) >= 1})
    bt_adaptive = backtest_portfolio(cfg_obj, signals)
    rows = [_bt_metrics_row(bt_adaptive, cfg_obj, portfolio_mode="dynamic", policy_mode="adaptive")]
    for interval in clean_intervals:
        rows.append(_bt_metrics_row(
            backtest_portfolio(cfg_obj, signals, rebalance_interval_months_override=interval),
            cfg_obj, portfolio_mode="dynamic", policy_mode="fixed_interval",
            rebalance_interval_months=int(interval)))
    return pd.DataFrame(rows).sort_values("rebalance_interval_months").reset_index(drop=True)




# Stage 4a (2026-04-20): add_historical_data_quality_columns +
# compute_portfolio_sleeve_columns (1,028L with Phase 9 C1+C2+C3 gate) +
# compute_portfolio_sleeve_policy moved to r1000_signals.py.




# Stage 4b-ii (2026-04-20): apply_sleeve_entry_drift_name_caps -> r1000_signals.py.




# Stage 4b-ii (2026-04-20): build_target_portfolio + 8 portfolio helpers -> r1000_signals.py.




def month_forward_return_open(paths: dict[str, Path], ticker: str, entry_dt: pd.Timestamp, exit_dt: pd.Timestamp) -> Optional[float]:
    if str(ticker).upper() == CASH_PROXY_TICKER:
        return 0.0
    px = load_px(paths, ticker)
    if px is None or px.empty or "Open" not in px.columns:
        return None
    idx = pd.DatetimeIndex(pd.to_datetime(px.index).tz_localize(None))
    sdt = get_date_on_or_after(idx, entry_dt)
    edt = get_date_on_or_after(idx, exit_dt)
    if sdt is None:
        return None
    if edt is None:
        return -1.0
    op = adjusted_open_series(px)
    p0 = float(op.loc[sdt]) if sdt in op.index else np.nan
    p1 = float(op.loc[edt]) if edt in op.index else np.nan
    if not np.isfinite(p0) or not np.isfinite(p1) or p0 == 0:
        return None
    return p1 / p0 - 1.0


def performance_metrics(monthly: pd.Series, benchmark: Optional[pd.Series] = None) -> dict[str, float]:
    r = monthly.dropna()
    if r.empty:
        return {k: float("nan") for k in ["cagr", "sharpe", "sortino", "max_dd", "calmar", "ir", "vol_ann"]}
    n = len(r)
    equity = (1.0 + r).cumprod()
    years = n / 12.0
    cagr = float(equity.iloc[-1] ** (1 / years) - 1) if years > 0 else np.nan
    vol_ann = float(r.std(ddof=0) * math.sqrt(12))
    sharpe = float((r.mean() * 12) / (vol_ann + 1e-12))
    downside = r[r < 0]
    sortino = float((r.mean() * 12) / ((downside.std(ddof=0) * math.sqrt(12)) + 1e-12))
    dd = equity / equity.cummax() - 1.0
    mdd = float(dd.min())
    calmar = float(cagr / abs(mdd)) if mdd < 0 else np.nan
    ir = np.nan
    if benchmark is not None:
        x = benchmark.reindex(r.index).dropna()
        y = r.reindex(x.index)
        if len(x) > 3:
            ex = y - x
            ir = float((ex.mean() * 12) / ((ex.std(ddof=0) * math.sqrt(12)) + 1e-12))
    return {"cagr": cagr, "sharpe": sharpe, "sortino": sortino, "max_dd": mdd, "calmar": calmar, "ir": float(ir) if pd.notna(ir) else np.nan, "vol_ann": vol_ann}


def sleeve_backtest_returns_from_holdings(holdings: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    if holdings is None or holdings.empty:
        return pd.DataFrame(), pd.DataFrame()
    required = {"rebalance_date", "ticker", "weight", "portfolio_sleeve_label", "period_forward_return"}
    if not required.issubset(holdings.columns):
        return pd.DataFrame(), pd.DataFrame()
    d = holdings.copy()
    d["rebalance_date"] = pd.to_datetime(d["rebalance_date"], errors="coerce")
    d["weight"] = pd.to_numeric(d["weight"], errors="coerce").fillna(0.0)
    d["period_forward_return"] = pd.to_numeric(d["period_forward_return"], errors="coerce")
    d["portfolio_sleeve_label"] = d["portfolio_sleeve_label"].fillna("core_compounder").astype(str)
    d = d[d["ticker"].astype(str).str.upper().ne(CASH_PROXY_TICKER)].dropna(
        subset=["rebalance_date", "period_forward_return"]
    )
    if d.empty:
        return pd.DataFrame(), pd.DataFrame()
    d["weighted_forward_return"] = d["weight"] * d["period_forward_return"]
    monthly_rows = []
    for (dt, sleeve), g in d.groupby(["rebalance_date", "portfolio_sleeve_label"], sort=True):
        sleeve_weight = float(g["weight"].sum())
        contribution = float(g["weighted_forward_return"].sum())
        sleeve_return = float(contribution / sleeve_weight) if sleeve_weight > 1e-10 else np.nan
        monthly_rows.append(
            {
                "rebalance_date": dt,
                "portfolio_sleeve_label": sleeve,
                "sleeve_weight": sleeve_weight,
                "selected_names": int(g["ticker"].nunique()),
                "sleeve_return": sleeve_return,
                "portfolio_contribution": contribution,
            }
        )
    monthly = pd.DataFrame(monthly_rows)
    if monthly.empty:
        return pd.DataFrame(), pd.DataFrame()
    summary_rows = []
    for sleeve, g in monthly.groupby("portfolio_sleeve_label", sort=True):
        returns = pd.Series(g["sleeve_return"].to_numpy(dtype=float), index=pd.to_datetime(g["rebalance_date"]))
        returns = returns.dropna()
        metrics = performance_metrics(returns)
        summary_rows.append(
            {
                "portfolio_sleeve_label": str(sleeve),
                "months": int(len(returns)),
                "sleeve_cagr": float(metrics.get("cagr", np.nan)),
                "sleeve_sharpe": float(metrics.get("sharpe", np.nan)),
                "sleeve_sortino": float(metrics.get("sortino", np.nan)),
                "sleeve_max_dd": float(metrics.get("max_dd", np.nan)),
                "sleeve_vol_ann": float(metrics.get("vol_ann", np.nan)),
                "avg_sleeve_weight": float(g["sleeve_weight"].mean()),
                "avg_selected_names": float(g["selected_names"].mean()),
                "avg_monthly_return": float(returns.mean()) if len(returns) else np.nan,
                "win_rate": float((returns > 0).mean()) if len(returns) else np.nan,
                "avg_portfolio_contribution": float(g["portfolio_contribution"].mean()),
            }
        )
    summary = pd.DataFrame(summary_rows).sort_values("sleeve_cagr", ascending=False)
    return monthly.sort_values(["rebalance_date", "portfolio_sleeve_label"]).reset_index(drop=True), summary.reset_index(drop=True)


def build_engine_diagnostics_report_frames(
    cfg: EngineConfig,
    scored: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    hist = scored.copy() if scored is not None else pd.DataFrame()
    if hist.empty:
        return pd.DataFrame(), pd.DataFrame()
    if "rebalance_date" not in hist.columns:
        return pd.DataFrame(), pd.DataFrame()
    hist["rebalance_date"] = pd.to_datetime(hist["rebalance_date"], errors="coerce")
    hist = hist[hist["rebalance_date"].notna()].copy()
    if hist.empty:
        return pd.DataFrame(), pd.DataFrame()
    hist = add_core_fundamental_minimum_flags(hist, cfg)
    hist = compute_portfolio_sleeve_columns(hist, cfg)
    hist = annotate_portfolio_candidate_gate(hist, cfg)
    top_n = max(int(getattr(cfg, "engine_diagnostics_top_n", 7)), 1)
    score_col_map = {
        "core_compounder": "portfolio_core_compounder_engine_score",
        "future_winner": "portfolio_future_winner_engine_score",
        "early_scout": "portfolio_early_scout_engine_score",
    }
    sleeve_labels = ["core_compounder", "future_winner", "early_scout"]
    monthly_rows: list[dict[str, Any]] = []
    for dt, grp in hist.groupby("rebalance_date", sort=True):
        raw_labels = grp.get("portfolio_sleeve_label_raw", pd.Series("core_compounder", index=grp.index, dtype=object)).fillna("core_compounder").astype(str)
        final_labels = grp.get("portfolio_sleeve_label", pd.Series("core_compounder", index=grp.index, dtype=object)).fillna("core_compounder").astype(str)
        gate_pass = grp.get("portfolio_candidate_minimum_pass", pd.Series(False, index=grp.index, dtype=bool)).fillna(False).astype(bool)
        for sleeve in sleeve_labels:
            raw_mask = raw_labels.eq(sleeve)
            final_mask = final_labels.eq(sleeve)
            gated = grp.loc[final_mask & gate_pass].copy()
            score_col = score_col_map.get(sleeve, "score")
            sort_cols = [c for c in [score_col, "score"] if c in gated.columns]
            if sort_cols:
                gated = gated.sort_values(sort_cols, ascending=[False] * len(sort_cols))
            top = gated.head(top_n).copy()
            top_r_1m = pd.to_numeric(top.get("r_1m", pd.Series(dtype=float)), errors="coerce")
            top_r_3m = pd.to_numeric(top.get("r_3m", pd.Series(dtype=float)), errors="coerce")
            monthly_rows.append(
                {
                    "rebalance_date": pd.Timestamp(dt),
                    "portfolio_sleeve_label": sleeve,
                    "raw_label_count": int(raw_mask.sum()),
                    "final_label_count": int(final_mask.sum()),
                    "gate_pass_count": int((final_mask & gate_pass).sum()),
                    "promoted_in_count": int((~raw_mask & final_mask).sum()),
                    "promoted_out_count": int((raw_mask & ~final_mask).sum()),
                    "topn_selected_count": int(len(top)),
                    "topn_avg_r_1m": float(top_r_1m.mean()) if top_r_1m.notna().any() else np.nan,
                    "topn_win_rate_1m": float((top_r_1m > 0).mean()) if top_r_1m.notna().any() else np.nan,
                    "topn_loss_rate_1m": float((top_r_1m < 0).mean()) if top_r_1m.notna().any() else np.nan,
                    "topn_worst_r_1m": float(top_r_1m.min()) if top_r_1m.notna().any() else np.nan,
                    "topn_avg_r_3m": float(top_r_3m.mean()) if top_r_3m.notna().any() else np.nan,
                    "topn_win_rate_3m": float((top_r_3m > 0).mean()) if top_r_3m.notna().any() else np.nan,
                    "topn_engine_score_mean": float(pd.to_numeric(top.get(score_col, pd.Series(dtype=float)), errors="coerce").mean()) if not top.empty and score_col in top.columns else np.nan,
                    "topn_score_mean": float(pd.to_numeric(top.get("score", pd.Series(dtype=float)), errors="coerce").mean()) if not top.empty and "score" in top.columns else np.nan,
                }
            )
    monthly = pd.DataFrame(monthly_rows)
    if monthly.empty:
        return pd.DataFrame(), pd.DataFrame()
    summary_rows: list[dict[str, Any]] = []
    for sleeve, grp in monthly.groupby("portfolio_sleeve_label", sort=True):
        r1 = pd.Series(pd.to_numeric(grp["topn_avg_r_1m"], errors="coerce").to_numpy(dtype=float), index=pd.to_datetime(grp["rebalance_date"]))
        r1 = r1.dropna()
        metrics = performance_metrics(r1)
        summary_rows.append(
            {
                "portfolio_sleeve_label": str(sleeve),
                "months": int(len(grp)),
                "empty_month_ratio": float(grp["topn_selected_count"].eq(0).mean()),
                "avg_raw_label_count": float(pd.to_numeric(grp["raw_label_count"], errors="coerce").mean()),
                "avg_final_label_count": float(pd.to_numeric(grp["final_label_count"], errors="coerce").mean()),
                "avg_gate_pass_count": float(pd.to_numeric(grp["gate_pass_count"], errors="coerce").mean()),
                "avg_promoted_in_count": float(pd.to_numeric(grp["promoted_in_count"], errors="coerce").mean()),
                "avg_promoted_out_count": float(pd.to_numeric(grp["promoted_out_count"], errors="coerce").mean()),
                "avg_topn_selected_count": float(pd.to_numeric(grp["topn_selected_count"], errors="coerce").mean()),
                "topn_avg_r_1m": float(pd.to_numeric(grp["topn_avg_r_1m"], errors="coerce").mean()),
                "topn_avg_r_3m": float(pd.to_numeric(grp["topn_avg_r_3m"], errors="coerce").mean()),
                "topn_win_rate_1m": float(pd.to_numeric(grp["topn_win_rate_1m"], errors="coerce").mean()),
                "topn_loss_rate_1m": float(pd.to_numeric(grp["topn_loss_rate_1m"], errors="coerce").mean()),
                "topn_cagr_1m": float(metrics.get("cagr", np.nan)),
                "topn_sharpe_1m": float(metrics.get("sharpe", np.nan)),
                "topn_sortino_1m": float(metrics.get("sortino", np.nan)),
                "topn_max_dd_1m": float(metrics.get("max_dd", np.nan)),
                "latest_raw_label_count": int(pd.to_numeric(grp["raw_label_count"], errors="coerce").iloc[-1]),
                "latest_final_label_count": int(pd.to_numeric(grp["final_label_count"], errors="coerce").iloc[-1]),
                "latest_gate_pass_count": int(pd.to_numeric(grp["gate_pass_count"], errors="coerce").iloc[-1]),
                "latest_topn_selected_count": int(pd.to_numeric(grp["topn_selected_count"], errors="coerce").iloc[-1]),
            }
        )
    summary = pd.DataFrame(summary_rows).sort_values("topn_cagr_1m", ascending=False).reset_index(drop=True)
    monthly = monthly.sort_values(["rebalance_date", "portfolio_sleeve_label"]).reset_index(drop=True)
    return monthly, summary




def build_historical_data_quality_report_frames(
    cfg: EngineConfig,
    scored: pd.DataFrame,
    scored_latest: pd.DataFrame,
    portfolio_latest: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    hist = add_historical_data_quality_columns(scored.copy() if scored is not None else pd.DataFrame())
    latest = add_historical_data_quality_columns(scored_latest.copy() if scored_latest is not None else pd.DataFrame())
    if not hist.empty and "portfolio_sleeve_label" not in hist.columns:
        hist = compute_portfolio_sleeve_columns(hist, cfg)
    if not latest.empty and "portfolio_sleeve_label" not in latest.columns:
        latest = compute_portfolio_sleeve_columns(latest, cfg)

    coverage_cols = list(
        dict.fromkeys(
            [
                "revenues_ttm",
                "gross_profit_ttm",
                "op_income_ttm",
                "net_income_ttm",
                "ocf_ttm",
                "fcf_ttm",
                "sales_growth_yoy",
                "op_income_growth_yoy",
                "net_income_growth_yoy",
                "ocf_growth_yoy",
                "fcf_growth_yoy",
                "eps_growth_yoy",
                "sales_cagr_3y",
                "sales_cagr_5y",
                "op_income_cagr_3y",
                "net_income_cagr_3y",
                "ocf_cagr_3y",
                "fcf_cagr_3y",
                "eps_cagr_3y",
                "fund_history_quarters_available",
            ]
            + FORWARD_RETURN_COVERAGE_COLUMNS
        )
    )
    score_cols = [
        "fundamental_history_coverage_score",
        "fundamental_history_level_coverage",
        "fundamental_history_change_coverage",
        "fundamental_history_cagr_coverage",
        "fundamental_history_quality_coverage",
        "fundamental_history_depth_3y_score",
        "fundamental_history_depth_5y_score",
        "growth_sleeve_data_confidence",
        "growth_sleeve_technical_confirmation_score",
        "growth_sleeve_sparse_history_penalty",
        "forward_return_coverage_score",
    ]
    label_values = ["full_history", "usable_history", "sparse_growth_history", "latest_or_price_only"]

    def _group_value(v: Any) -> Any:
        if isinstance(v, pd.Timestamp):
            return str(v.date())
        if pd.isna(v):
            return None
        return v

    def _summarize(frame: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
        if frame.empty or not all(c in frame.columns for c in group_cols):
            return pd.DataFrame()
        rows: list[dict[str, Any]] = []
        work = frame.copy()
        if "rebalance_date" in work.columns:
            work["rebalance_date"] = pd.to_datetime(work["rebalance_date"], errors="coerce")
        for keys, grp in work.groupby(group_cols, dropna=False, sort=True):
            key_tuple = keys if isinstance(keys, tuple) else (keys,)
            row: dict[str, Any] = {c: _group_value(v) for c, v in zip(group_cols, key_tuple)}
            row["rows"] = int(len(grp))
            row["tickers"] = int(grp["ticker"].nunique()) if "ticker" in grp.columns else int(len(grp))
            for c in score_cols:
                if c in grp.columns:
                    vals = pd.to_numeric(grp[c], errors="coerce")
                    row[f"{c}_mean"] = float(vals.mean()) if vals.notna().any() else np.nan
                    row[f"{c}_median"] = float(vals.median()) if vals.notna().any() else np.nan
            for c in coverage_cols:
                row[f"{c}_coverage"] = float(grp[c].notna().mean()) if c in grp.columns and len(grp) else 0.0
            label = grp.get("data_history_quality_label", pd.Series("", index=grp.index, dtype=object)).fillna("").astype(str)
            for v in label_values:
                row[f"{v}_share"] = float(label.eq(v).mean()) if len(label) else 0.0
            rows.append(row)
        return pd.DataFrame(rows)

    by_month = _summarize(hist, ["rebalance_date"])
    by_sleeve = _summarize(hist, ["rebalance_date", "portfolio_sleeve_label"])

    if not latest.empty:
        selected_tickers: set[str] = set()
        if portfolio_latest is not None and not portfolio_latest.empty and "ticker" in portfolio_latest.columns:
            port_tickers = portfolio_latest["ticker"].astype(str).str.upper()
            selected_tickers = set(port_tickers.loc[port_tickers.ne(CASH_PROXY_TICKER)])
        latest["selected_for_portfolio"] = latest.get(
            "selected_for_portfolio",
            pd.Series(False, index=latest.index, dtype=bool),
        ).fillna(False).astype(bool) | latest.get("ticker", pd.Series("", index=latest.index)).astype(str).str.upper().isin(selected_tickers)
        keep_cols = [
            "rebalance_date",
            "ticker",
            "Name",
            "sector",
            "score",
            "weight",
            "selected_for_portfolio",
            "portfolio_sleeve_label",
            "portfolio_sleeve_label_raw",
            "portfolio_sleeve_confidence",
            "portfolio_core_compounder_engine_score",
            "portfolio_future_winner_engine_score",
            "portfolio_early_scout_engine_score",
        ] + HISTORICAL_DATA_QUALITY_COLUMNS + coverage_cols + [
            "minervini_momentum_alive_score",
            "technical_blueprint_score",
            "breakout_setup_quality_score",
            "selection_market_confirmation_score",
            "selection_fundamental_confirmation_score",
        ]
        keep_cols = [c for c in dict.fromkeys(keep_cols) if c in latest.columns]
        latest_detail = latest[keep_cols].copy()
        if "rebalance_date" in latest_detail.columns:
            latest_detail["rebalance_date"] = pd.to_datetime(
                latest_detail["rebalance_date"],
                errors="coerce",
            ).dt.date.astype(str)
        sort_cols = [c for c in ["selected_for_portfolio", "score"] if c in latest_detail.columns]
        if sort_cols:
            latest_detail = latest_detail.sort_values(
                sort_cols,
                ascending=[False] * len(sort_cols),
            )
        latest_detail = latest_detail.reset_index(drop=True)
    else:
        latest_detail = pd.DataFrame()

    return by_month.reset_index(drop=True), by_sleeve.reset_index(drop=True), latest_detail


def run_acceptance_checks(
    cfg: EngineConfig,
    paths: dict[str, Path],
    feature_store: pd.DataFrame,
    scored: pd.DataFrame,
    backtest: BacktestResult,
) -> dict[str, Any]:
    checks: dict[str, Any] = {}

    fs = feature_store.copy()
    fs["accepted"] = datetime_series_or_default(fs, "accepted")
    fs["feature_date"] = datetime_series_or_default(fs, "feature_date")
    fs["rebalance_date"] = datetime_series_or_default(fs, "rebalance_date")
    fs = add_historical_data_quality_columns(fs)
    pit = fs.dropna(subset=["accepted", "feature_date", "rebalance_date"])
    pit_bad = pit[~((pit["accepted"] <= pit["feature_date"]) & (pit["feature_date"] <= pit["rebalance_date"]))]
    checks["pit_violation_count"] = int(len(pit_bad))
    checks["pit_ok"] = int(len(pit_bad)) == 0

    exact_banned = {"r_1m", "r_3m", "r_6m"}
    prefix_banned = ("earn_post_", "future_")
    allowed_forward_named_features = {"future_winner_scout_score"}
    active_feature_columns = model_feature_columns(cfg)
    leakage_cols = [
        c
        for c in active_feature_columns
        if c not in allowed_forward_named_features
        and ((c in exact_banned) or any(c.startswith(pref) for pref in prefix_banned))
    ]
    checks["feature_leakage_columns"] = leakage_cols
    checks["leakage_ok"] = len(leakage_cols) == 0

    scored_months = pd.to_datetime(scored["rebalance_date"], errors="coerce").dropna()
    if not scored_months.empty:
        expected = month_end_trading_days(str(scored_months.min().date()), str(scored_months.max().date()))
        got = sorted(pd.Series(scored_months.unique()).tolist())
        missing = sorted(list(set(pd.to_datetime(expected)) - set(pd.to_datetime(got))))
    else:
        missing = []
    checks["oos_missing_months"] = [str(pd.Timestamp(x).date()) for x in missing]
    checks["oos_month_coverage_ok"] = len(missing) == 0

    checks["backtest_months"] = int(backtest.metrics.get("months", 0))
    checks["turnover_avg"] = float(backtest.metrics.get("avg_turnover_monthly", np.nan))
    checks["cost_bps_roundtrip"] = float(backtest.metrics.get("cost_bps_roundtrip", np.nan))

    latest_dt = fs["rebalance_date"].max()
    history_mask = fs["rebalance_date"] < latest_dt
    latest_only_nonnull = 0
    if pd.notna(latest_dt):
        for c in LATEST_ONLY_ACCEPTANCE_COLUMNS:
            if c in fs.columns:
                latest_only_nonnull += int(fs.loc[history_mask, c].notna().sum())
    checks["live_feature_history_nonnull"] = int(latest_only_nonnull)
    checks["live_feature_history_ok"] = int(latest_only_nonnull) == 0
    checks["universe_mode"] = (
        "historical_membership_file"
        if fs.get("universe_source", pd.Series(dtype=str)).astype(str).eq("historical_membership_file").any()
        else "current_constituents_proxy"
    )
    checks["survivorship_bias_warning"] = checks["universe_mode"] != "historical_membership_file"
    checks["historical_membership_required"] = bool(cfg.require_historical_membership_for_backtest)
    checks["historical_membership_ok"] = not (
        cfg.require_historical_membership_for_backtest and checks["survivorship_bias_warning"]
    )

    latest_view = fs[fs["rebalance_date"] == latest_dt].copy() if pd.notna(latest_dt) else fs.copy()
    latest_view = normalize_latest_fundamental_snapshot(
        cfg,
        paths,
        latest_view,
        clear_latest_only_signals=False,
        apply_statement_repair=True,
        add_fundamental_flags=True,
    )
    ttm_cov = {
        c: float(latest_view[c].notna().mean()) if c in latest_view.columns and len(latest_view) else 0.0
        for c in CRITICAL_TTM_COVERAGE_COLUMNS
    }
    valuation_cov = {
        c: float(latest_view[c].notna().mean()) if c in latest_view.columns and len(latest_view) else 0.0
        for c in CRITICAL_VALUATION_COVERAGE_COLUMNS
    }
    comprehensive_cov = {
        c: float(latest_view[c].notna().mean()) if c in latest_view.columns and len(latest_view) else 0.0
        for c in COMPREHENSIVE_FUNDAMENTAL_COVERAGE_COLUMNS
    }
    checks["critical_ttm_coverage"] = ttm_cov
    checks["critical_valuation_coverage"] = valuation_cov
    checks["comprehensive_fundamental_coverage"] = comprehensive_cov
    checks["critical_ttm_coverage_mean"] = float(np.nanmean(list(ttm_cov.values()))) if ttm_cov else 0.0
    checks["critical_valuation_coverage_mean"] = (
        float(np.nanmean(list(valuation_cov.values()))) if valuation_cov else 0.0
    )
    checks["comprehensive_fundamental_coverage_mean"] = (
        float(np.nanmean(list(comprehensive_cov.values()))) if comprehensive_cov else 0.0
    )
    latest_view = add_core_fundamental_minimum_flags(latest_view, cfg)
    latest_view = add_historical_data_quality_columns(latest_view)
    core_pass = numeric_series_or_default(latest_view, "core_fundamental_minimum_pass", 0.0)
    checks["core_fundamental_pass_ratio"] = float(core_pass.mean()) if len(core_pass) else 0.0
    checks["core_fundamental_pass_count"] = int(core_pass.sum()) if len(core_pass) else 0
    checks["core_fundamental_minimum_ok"] = bool(
        checks["core_fundamental_pass_count"] >= int(cfg.min_port_names)
    )
    checks["fundamental_coverage_ok"] = bool(
        checks["critical_ttm_coverage_mean"] >= cfg.min_ttm_feature_coverage
        and checks["critical_valuation_coverage_mean"] >= cfg.min_valuation_feature_coverage
        and checks["core_fundamental_minimum_ok"]
    )
    checks["fundamental_coverage_warning"] = not checks["fundamental_coverage_ok"]
    checks["comprehensive_fundamental_coverage_warning"] = bool(
        checks["comprehensive_fundamental_coverage_mean"] < 0.75
    )
    checks["backtest_research_only"] = bool(
        checks["survivorship_bias_warning"] or checks["fundamental_coverage_warning"]
    )
    checks["backtest_usable"] = bool(
        checks["pit_ok"]
        and checks["leakage_ok"]
        and checks["oos_month_coverage_ok"]
        and checks["live_feature_history_ok"]
        and checks["historical_membership_ok"]
        and checks["fundamental_coverage_ok"]
    )
    checks["all_pass"] = checks["backtest_usable"]

    # Phase 6 verification: CAGR coverage per rebalance month
    cagr_coverage_per_month = {}
    for dt_val, grp in fs.groupby("rebalance_date"):
        dt_str = str(pd.Timestamp(dt_val).date())
        cagr_3y_cov = float(grp["sales_cagr_3y"].notna().mean()) if "sales_cagr_3y" in grp.columns else 0.0
        cagr_5y_cov = float(grp["sales_cagr_5y"].notna().mean()) if "sales_cagr_5y" in grp.columns else 0.0
        ttm_cov_m = float(grp["revenues_ttm"].notna().mean()) if "revenues_ttm" in grp.columns else 0.0
        cagr_coverage_per_month[dt_str] = {
            "revenues_ttm": round(ttm_cov_m, 3),
            "sales_cagr_3y": round(cagr_3y_cov, 3),
            "sales_cagr_5y": round(cagr_5y_cov, 3),
        }
    checks["cagr_coverage_per_month_sample"] = dict(list(cagr_coverage_per_month.items())[-6:])
    all_cagr3 = [v["sales_cagr_3y"] for v in cagr_coverage_per_month.values()]
    checks["cagr_3y_coverage_mean"] = round(float(np.nanmean(all_cagr3)), 3) if all_cagr3 else 0.0
    checks["cagr_3y_low_months"] = sum(1 for x in all_cagr3 if x < 0.20)
    checks["historical_data_quality_latest"] = {}
    if not latest_view.empty:
        for c in [
            "fundamental_history_coverage_score",
            "growth_sleeve_data_confidence",
            "growth_sleeve_sparse_history_penalty",
            "forward_return_coverage_score",
        ]:
            if c in latest_view.columns:
                vals = pd.to_numeric(latest_view[c], errors="coerce")
                checks["historical_data_quality_latest"][f"{c}_mean"] = (
                    round(float(vals.mean()), 3) if vals.notna().any() else 0.0
                )
        if "data_history_quality_label" in latest_view.columns:
            checks["historical_data_quality_latest"]["quality_label_counts"] = {
                str(k): int(v)
                for k, v in latest_view["data_history_quality_label"]
                .fillna("unknown")
                .astype(str)
                .value_counts()
                .items()
            }

    (paths["reports"] / "acceptance_checks.json").write_text(json.dumps(checks, indent=2))
    return checks


def resolve_sleeve_rebalance_interval_map(cfg: EngineConfig) -> dict[str, int]:
    base_interval = max(int(getattr(cfg, "rebalance_interval_months", 1)), 1)
    return {
        "core_compounder": max(
            int(getattr(cfg, "core_compounder_rebalance_interval_months", base_interval)),
            1,
        ),
        "future_winner": max(
            int(getattr(cfg, "future_winner_rebalance_interval_months", base_interval)),
            1,
        ),
        "early_scout": max(
            int(getattr(cfg, "early_scout_rebalance_interval_months", base_interval)),
            1,
        ),
    }


def apply_sleeve_rebalance_interval_columns(
    frame: pd.DataFrame,
    cfg: EngineConfig,
    interval_map: Optional[dict[str, int]] = None,
) -> pd.DataFrame:
    out = frame.copy()
    if out.empty:
        return out
    interval_map = interval_map or resolve_sleeve_rebalance_interval_map(cfg)
    sleeve_label = out.get(
        "portfolio_sleeve_label",
        pd.Series("core_compounder", index=out.index, dtype=object),
    ).fillna("core_compounder").astype(str)
    out["sleeve_rebalance_interval_months"] = sleeve_label.map(
        lambda x: int(interval_map.get(str(x), max(int(getattr(cfg, "rebalance_interval_months", 1)), 1)))
    ).fillna(max(int(getattr(cfg, "rebalance_interval_months", 1)), 1)).astype(int)
    return out


def _current_sleeve_map_from_portfolio(portfolio: pd.DataFrame) -> dict[str, str]:
    if portfolio is None or portfolio.empty or "ticker" not in portfolio.columns:
        return {}
    labels = portfolio.get(
        "portfolio_sleeve_label",
        pd.Series("core_compounder", index=portfolio.index, dtype=object),
    ).fillna("core_compounder").astype(str)
    return {
        normalize_ticker(tkr): str(lbl)
        for tkr, lbl in zip(portfolio["ticker"].astype(str), labels)
        if normalize_ticker(tkr) and normalize_ticker(tkr) != CASH_PROXY_TICKER
    }


def merge_partial_sleeve_rebalance_state(
    month_df: pd.DataFrame,
    current_w: dict[str, float],
    current_sleeve_map: dict[str, str],
    target_portfolio: pd.DataFrame,
    target_w: dict[str, float],
    due_sleeves: Iterable[str],
    cfg: EngineConfig,
    interval_map: Optional[dict[str, int]] = None,
) -> tuple[pd.DataFrame, dict[str, float], dict[str, str]]:
    due_set = {str(x) for x in due_sleeves}
    interval_map = interval_map or resolve_sleeve_rebalance_interval_map(cfg)
    target_sleeve_map = _current_sleeve_map_from_portfolio(target_portfolio)
    preserved_weights = {
        str(tkr): float(weight)
        for tkr, weight in current_w.items()
        if str(tkr).upper() != CASH_PROXY_TICKER
        and current_sleeve_map.get(normalize_ticker(tkr), "core_compounder") not in due_set
        and normalize_ticker(tkr) not in target_sleeve_map
    }
    due_target_weights = {
        str(tkr): float(weight)
        for tkr, weight in target_w.items()
        if str(tkr).upper() != CASH_PROXY_TICKER
        and target_sleeve_map.get(normalize_ticker(tkr), "core_compounder") in due_set
    }
    preserved_total = float(sum(preserved_weights.values()))
    target_cash = float(target_w.get(CASH_PROXY_TICKER, 0.0))
    due_target_total = float(sum(due_target_weights.values())) + max(target_cash, 0.0)
    remaining_weight = max(0.0, 1.0 - preserved_total)
    combined_weights = preserved_weights.copy()
    if due_target_total > 1e-10 and remaining_weight > 1e-10:
        scale = remaining_weight / due_target_total
        for tkr, weight in due_target_weights.items():
            combined_weights[str(tkr)] = float(weight * scale)
        cash_weight = float(max(target_cash, 0.0) * scale)
    else:
        cash_weight = float(remaining_weight)
    if cash_weight > 1e-10:
        combined_weights[CASH_PROXY_TICKER] = cash_weight
    total_weight = float(sum(combined_weights.values()))
    if total_weight > 0 and abs(total_weight - 1.0) > 1e-8:
        combined_weights = {
            str(k): float(v / total_weight)
            for k, v in combined_weights.items()
            if pd.notna(v) and float(v) > 1e-10
        }

    combined_sleeve_map = {
        normalize_ticker(tkr): sleeve
        for tkr, sleeve in current_sleeve_map.items()
        if normalize_ticker(tkr) and normalize_ticker(tkr) not in target_sleeve_map
    }
    for tkr, sleeve in target_sleeve_map.items():
        if str(sleeve) in due_set:
            combined_sleeve_map[normalize_ticker(tkr)] = str(sleeve)

    combined_portfolio = materialize_weight_frame(month_df, combined_weights)
    if not combined_portfolio.empty:
        ticker_norm = combined_portfolio.get("ticker", pd.Series(dtype=object)).astype(str).map(normalize_ticker)
        combined_portfolio["portfolio_sleeve_label"] = ticker_norm.map(
            lambda x: combined_sleeve_map.get(x, "cash" if str(x).upper() == CASH_PROXY_TICKER else "core_compounder")
        )
        combined_portfolio["portfolio_sleeve_role"] = combined_portfolio["portfolio_sleeve_label"].map(
            lambda x: "cash" if str(x) == "cash" else SLEEVE_STANDALONE_ROLE_MAP.get(str(x), str(x))
        )
        combined_portfolio = apply_sleeve_rebalance_interval_columns(combined_portfolio, cfg, interval_map=interval_map)
    return combined_portfolio, combined_weights, combined_sleeve_map


def backtest_portfolio(
    cfg: dict | EngineConfig,
    signals: pd.DataFrame,
    target_n_override: Optional[int] = None,
    rebalance_interval_months_override: Optional[int] = None,
    adaptive_interval_policy_override: Optional[bool] = None,
    sleeve_override: Optional[dict] = None,
    cash_target_max: float = 1.0,
) -> BacktestResult:
    cfg = to_cfg(cfg)
    paths = get_paths(cfg)
    log("Phase 5: running monthly portfolio backtest ...")

    d = signals.copy()
    d["rebalance_date"] = pd.to_datetime(d["rebalance_date"], errors="coerce")
    d = d.sort_values(["rebalance_date", "score"], ascending=[True, False]).reset_index(drop=True)
    fixed_interval_months = max(
        int(
            rebalance_interval_months_override
            if rebalance_interval_months_override is not None
            else getattr(cfg, "rebalance_interval_months", 1)
        ),
        1,
    )
    adaptive_interval_policy = (
        bool(getattr(cfg, "adaptive_rebalance_enabled", True))
        if adaptive_interval_policy_override is None
        else bool(adaptive_interval_policy_override)
    )
    if rebalance_interval_months_override is not None:
        adaptive_interval_policy = False
    sleeve_specific_rebalance_enabled = bool(getattr(cfg, "sleeve_specific_rebalance_enabled", True))
    sleeve_specific_rebalance_enabled = sleeve_specific_rebalance_enabled and rebalance_interval_months_override is None
    sleeve_interval_map = (
        resolve_sleeve_rebalance_interval_map(cfg)
        if sleeve_specific_rebalance_enabled
        else {
            "core_compounder": int(fixed_interval_months),
            "future_winner": int(fixed_interval_months),
            "early_scout": int(fixed_interval_months),
        }
    )
    if sleeve_specific_rebalance_enabled:
        adaptive_interval_policy = False
    months = sorted(pd.to_datetime(d["rebalance_date"].dropna().unique()).tolist())
    if len(months) < 2:
        raise RuntimeError("Need at least two months of OOS signals for backtest.")
    allowed_intervals = (
        [int(fixed_interval_months)]
        if rebalance_interval_months_override is not None
        else sorted({int(x) for x in getattr(cfg, "rebalance_interval_comparison_months", [fixed_interval_months]) if int(x) >= 1})
    )
    if not allowed_intervals:
        allowed_intervals = [int(fixed_interval_months)]

    cost_candidates = [
        safe_float(getattr(cfg, "roundtrip_cost_bps", np.nan)),
        2.0 * safe_float(getattr(cfg, "trade_cost_bps_per_side", 0.0)),
    ]
    cost_candidates = [float(x) for x in cost_candidates if np.isfinite(x)]
    effective_roundtrip_cost_bps = float(max(cost_candidates)) if cost_candidates else 0.0
    starting_capital_usd = float(max(safe_float(getattr(cfg, "starting_capital_usd", 100000.0)), 1.0))

    current_w: dict[str, float] = {}
    current_portfolio = pd.DataFrame()
    current_sleeve_map: dict[str, str] = {}
    current_meta: dict[str, Any] = {
        "target_n": 0,
        "weight_cap": float(cfg.stock_weight_max),
        "cash_target": 0.0,
    }
    active_interval_months = int(fixed_interval_months)
    next_scheduled_dt = pd.NaT
    next_scheduled_dt_by_sleeve = {
        sleeve: pd.NaT
        for sleeve in sleeve_interval_map.keys()
    }
    rebalance_dates_taken: list[pd.Timestamp] = []
    sleeve_rebalance_counts = {sleeve: 0 for sleeve in sleeve_interval_map.keys()}
    holdings_rows = []
    ret_rows = []
    # Stop-loss tracking for speculative positions
    speculative_cum_ret: dict[str, float] = {}  # ticker -> cumulative return since entry
    stopped_out_tickers: set[str] = set()  # tickers stopped out this cycle
    stop_loss_pct = float(getattr(cfg, "speculative_stop_loss_pct", 0.25))
    running_equity = 1.0
    portfolio_peak = 1.0
    circuit_breaker_active = False
    breaker_threshold = float(max(safe_float(getattr(cfg, "drawdown_circuit_breaker_threshold", 0.0), 0.0), 0.0))
    breaker_cash_target = float(np.clip(safe_float(getattr(cfg, "drawdown_circuit_breaker_cash_target", 0.0), 0.0), 0.0, 1.0))
    breaker_recovery = float(max(safe_float(getattr(cfg, "drawdown_circuit_breaker_recovery", 0.0), 0.0), 0.0))

    # -----------------------------------------------------------------
    # Phase 6a: 3-level drawdown breaker state (PHASE_ROADMAP §2.6).
    # Dual-gate toggle — both cfg flag AND env var must be on. When
    # off, the active path reverts to the legacy single-threshold
    # breaker above (byte-identical to pre-Phase-6a).
    # -----------------------------------------------------------------
    _phase6a_cfg_on = bool(getattr(cfg, "drawdown_breaker_multilevel_enabled", True))
    _phase6a_env_on = phase_is_enabled("phase6a_breaker", default=True)
    _phase6a_active = bool(_phase6a_cfg_on and _phase6a_env_on)
    dd_active_level = 0  # 0 = no breaker, 1/2/3 = ladder level
    dd_trigger_equity = 1.0  # equity level recorded when active level was tripped
    _p6a_level_thresholds = [
        float(max(safe_float(getattr(cfg, "drawdown_breaker_level_1_threshold", 0.08), 0.08), 1e-6)),
        float(max(safe_float(getattr(cfg, "drawdown_breaker_level_2_threshold", 0.15), 0.15), 1e-6)),
        float(max(safe_float(getattr(cfg, "drawdown_breaker_level_3_threshold", 0.25), 0.25), 1e-6)),
    ]
    _p6a_level_cash = [
        float(np.clip(safe_float(getattr(cfg, "drawdown_breaker_level_1_cash_floor", 0.15), 0.15), 0.0, 1.0)),
        float(np.clip(safe_float(getattr(cfg, "drawdown_breaker_level_2_cash_floor", 0.35), 0.35), 0.0, 1.0)),
        float(np.clip(safe_float(getattr(cfg, "drawdown_breaker_level_3_cash_floor", 0.60), 0.60), 0.0, 1.0)),
    ]
    _p6a_level_scale = [
        float(np.clip(safe_float(getattr(cfg, "drawdown_breaker_level_1_scale", 0.90), 0.90), 0.0, 1.0)),
        float(np.clip(safe_float(getattr(cfg, "drawdown_breaker_level_2_scale", 0.70), 0.70), 0.0, 1.0)),
        float(np.clip(safe_float(getattr(cfg, "drawdown_breaker_level_3_scale", 0.40), 0.40), 0.0, 1.0)),
    ]
    _p6a_recovery_buffer = float(max(safe_float(getattr(cfg, "drawdown_breaker_recovery_buffer", 0.03), 0.03), 0.0))

    # -----------------------------------------------------------------
    # Phase 6c: volatility targeting state (PHASE_ROADMAP §2.6).
    # Default OFF — user must explicitly set
    # cfg.volatility_targeting_enabled=True AND
    # PHASE_PHASE6C_VOLTARGET_ENABLED=1.
    # -----------------------------------------------------------------
    _phase6c_cfg_on = bool(getattr(cfg, "volatility_targeting_enabled", False))
    _phase6c_env_on = phase_is_enabled("phase6c_voltarget", default=False)
    _phase6c_active = bool(_phase6c_cfg_on and _phase6c_env_on)
    _p6c_target_vol = float(max(safe_float(getattr(cfg, "vol_target_annualized", 0.12), 0.12), 1e-4))
    _p6c_lookback = int(max(int(getattr(cfg, "vol_lookback_months", 6) or 6), 3))
    _p6c_floor = float(np.clip(safe_float(getattr(cfg, "vol_scale_floor", 0.50), 0.50), 0.0, 1.0))
    _p6c_ceiling = float(np.clip(safe_float(getattr(cfg, "vol_scale_ceiling", 1.0), 1.0), _p6c_floor, 1.0))
    recent_returns: list[float] = []  # trailing monthly net returns for vol calc

    def _live_label_for_month(month_df: pd.DataFrame) -> str:
        if month_df.empty or "live_event_alert_label" not in month_df.columns:
            return "balanced"
        mode = month_df["live_event_alert_label"].dropna().astype(str).mode()
        return str(mode.iloc[0]) if not mode.empty else "balanced"

    def _month_gap(later: pd.Timestamp, earlier: pd.Timestamp) -> int:
        return int((later.year - earlier.year) * 12 + (later.month - earlier.month))

    def _normalize_breaker_mix(payload: Optional[dict[str, Any]]) -> Optional[dict[str, float]]:
        if not isinstance(payload, dict):
            return None
        core = max(safe_float(payload.get("core"), payload.get("core_compounder", 0.0)), 0.0)
        future = max(safe_float(payload.get("future"), payload.get("future_winner", 0.0)), 0.0)
        early = max(safe_float(payload.get("early"), payload.get("early_scout", 0.0)), 0.0)
        total = core + future + early
        if total <= 1e-8:
            return None
        return {
            "core": float(core / total),
            "future": float(future / total),
            "early": float(early / total),
            "cash": float(np.clip(safe_float(payload.get("cash"), 0.0), 0.0, 1.0)),
        }

    def _current_breaker_mix() -> dict[str, float]:
        base_payload = _normalize_breaker_mix(sleeve_override)
        if base_payload is None and isinstance(current_meta, dict):
            base_payload = _normalize_breaker_mix(current_meta.get("sleeve_target_weights"))
        if base_payload is None and current_w:
            sleeve_weights = {"core": 0.0, "future": 0.0, "early": 0.0}
            for ticker, weight in current_w.items():
                if str(ticker).upper() == CASH_PROXY_TICKER:
                    continue
                sleeve_label = str(current_sleeve_map.get(str(ticker), "core_compounder"))
                if sleeve_label == "future_winner":
                    sleeve_weights["future"] += float(weight)
                elif sleeve_label == "early_scout":
                    sleeve_weights["early"] += float(weight)
                else:
                    sleeve_weights["core"] += float(weight)
            total = float(sum(sleeve_weights.values()))
            if total > 1e-8:
                base_payload = {
                    "core": float(sleeve_weights["core"] / total),
                    "future": float(sleeve_weights["future"] / total),
                    "early": float(sleeve_weights["early"] / total),
                    "cash": float(np.clip(current_w.get(CASH_PROXY_TICKER, 0.0), 0.0, 1.0)),
                }
        if base_payload is None:
            base_payload = {"core": 0.60, "future": 0.25, "early": 0.15, "cash": 0.0}
        return base_payload

    for i in range(len(months) - 1):
        dt = pd.Timestamp(months[i])
        next_dt = pd.Timestamp(months[i + 1])
        mm = d[d["rebalance_date"] == dt].copy()
        drawdown_before_month = float((running_equity - portfolio_peak) / max(portfolio_peak, 1e-8))
        breaker_event = ""
        # Phase 6a: 3-level ladder with equity-based recovery hysteresis.
        # When `_phase6a_active` is True this path replaces the legacy
        # single-threshold breaker; when False the legacy path runs
        # unchanged (byte-identical).
        if _phase6a_active:
            # current_dd as a positive number (0 when above peak, increases
            # as equity falls). positive-valued ladder makes the math
            # cleaner than the legacy negative drawdown_before_month.
            current_dd = max(0.0, 1.0 - (running_equity / max(portfolio_peak, 1e-8)))
            # Target level: the deepest threshold whose DD we meet.
            target_level = 0
            if current_dd >= _p6a_level_thresholds[2]:
                target_level = 3
            elif current_dd >= _p6a_level_thresholds[1]:
                target_level = 2
            elif current_dd >= _p6a_level_thresholds[0]:
                target_level = 1
            # Escalation: never step down on DD deepening; only go up.
            if target_level > dd_active_level:
                dd_active_level = target_level
                dd_trigger_equity = running_equity
                circuit_breaker_active = True
                breaker_event = f"triggered_level_{target_level}"
            elif dd_active_level > 0:
                # Recovery: equity must overshoot the trigger level by
                # `recovery_buffer` before we step all the way down to 0.
                # PROPOSAL_defensive_upgrades.md line 153 math: use
                # `running_equity >= dd_trigger_equity * (1 + buffer)`,
                # NOT a negative comparison.
                if running_equity >= dd_trigger_equity * (1.0 + _p6a_recovery_buffer):
                    dd_active_level = 0
                    dd_trigger_equity = 1.0
                    circuit_breaker_active = False
                    breaker_event = "recovered"
            if dd_active_level > 0:
                effective_breaker_cash_floor = _p6a_level_cash[dd_active_level - 1]
            else:
                effective_breaker_cash_floor = 0.0
        elif breaker_threshold > 0:
            # Legacy single-threshold path (unchanged — kept byte-identical
            # so Phase 6a OFF runs reproduce prior results).
            if circuit_breaker_active and drawdown_before_month >= -breaker_recovery:
                circuit_breaker_active = False
                breaker_event = "recovered"
            elif (not circuit_breaker_active) and drawdown_before_month <= -breaker_threshold:
                circuit_breaker_active = True
                breaker_event = "triggered"
            effective_breaker_cash_floor = breaker_cash_target if circuit_breaker_active else 0.0
        else:
            effective_breaker_cash_floor = 0.0
        force_breaker_rebalance = bool(current_w) and (
            circuit_breaker_active or breaker_event.startswith("recovered") or breaker_event.startswith("triggered")
        )
        breaker_sleeve_override = _current_breaker_mix() if circuit_breaker_active else None
        # Phase 6c: volatility targeting. When realized portfolio
        # vol (annualized from last `lookback` monthly net returns)
        # exceeds `_p6c_target_vol`, shrink non-cash exposure by
        # vol_scale, which we express as an equivalent cash floor.
        # Both the cfg flag and env gate must be on. Default OFF.
        vol_cash_floor_p6c = 0.0
        if _phase6c_active and len(recent_returns) >= _p6c_lookback:
            try:
                realized_vol = float(np.std(recent_returns[-_p6c_lookback:], ddof=1) * np.sqrt(12))
            except Exception:
                realized_vol = float("nan")
            if np.isfinite(realized_vol) and realized_vol > 0:
                vol_scale = float(
                    np.clip(
                        _p6c_target_vol / max(realized_vol, _p6c_target_vol),
                        _p6c_floor,
                        _p6c_ceiling,
                    )
                )
                # Express vol shrinkage as an equivalent cash floor:
                # if vol_scale=0.7, at least 30% of the book goes to cash.
                vol_cash_floor_p6c = float(np.clip(1.0 - vol_scale, 0.0, 1.0))
        effective_cash_target_max = float(cash_target_max)
        if circuit_breaker_active:
            effective_cash_target_max = max(effective_cash_target_max, effective_breaker_cash_floor)
        if vol_cash_floor_p6c > 0.0:
            effective_cash_target_max = max(effective_cash_target_max, vol_cash_floor_p6c)
        if sleeve_specific_rebalance_enabled:
            if force_breaker_rebalance:
                due_sleeves = list(sleeve_interval_map.keys())
                rebalance_due = True
            elif not current_w:
                due_sleeves = list(sleeve_interval_map.keys())
                rebalance_due = True
            else:
                due_sleeves = [
                    sleeve
                    for sleeve, sched_dt in next_scheduled_dt_by_sleeve.items()
                    if pd.isna(sched_dt) or (dt >= pd.Timestamp(sched_dt))
                ]
                rebalance_due = bool(due_sleeves)
        else:
            due_sleeves = list(sleeve_interval_map.keys())
            rebalance_due = force_breaker_rebalance or (not current_w) or pd.isna(next_scheduled_dt) or (dt >= pd.Timestamp(next_scheduled_dt))
        turn = 0.0
        cost = 0.0
        rebalance_action = "scheduled_hold"

        if rebalance_due:
            if not mm.empty:
                prev_w = current_w.copy()
                sel, final_w, meta = build_target_portfolio(
                    cfg,
                    mm,
                    prev_w=prev_w if prev_w else None,
                    apply_turnover=True,
                    target_n_override=target_n_override,
                    sleeve_override=breaker_sleeve_override if breaker_sleeve_override is not None else sleeve_override,
                    cash_target_max=effective_cash_target_max,
                )
                if not sel.empty and final_w:
                    current_meta = {
                        **meta,
                        "sleeve_rebalance_interval_map": {k: int(v) for k, v in sleeve_interval_map.items()},
                        "due_sleeves": [str(x) for x in due_sleeves],
                        "drawdown_circuit_breaker_active": bool(circuit_breaker_active),
                        "drawdown_circuit_breaker_event": breaker_event,
                        "drawdown_before_rebalance": drawdown_before_month,
                    }
                    clean_target_w = {
                        str(k): float(v)
                        for k, v in final_w.items()
                        if pd.notna(v) and float(v) > 1e-10
                    }
                    if sleeve_specific_rebalance_enabled and prev_w and len(due_sleeves) < len(sleeve_interval_map):
                        current_portfolio, current_w, current_sleeve_map = merge_partial_sleeve_rebalance_state(
                            mm,
                            current_w,
                            current_sleeve_map,
                            sel.copy(),
                            clean_target_w,
                            due_sleeves,
                            cfg,
                            interval_map=sleeve_interval_map,
                        )
                        rebalance_action = f"partial_rebalance:{','.join(sorted(due_sleeves))}"
                    else:
                        current_portfolio = apply_sleeve_rebalance_interval_columns(
                            sel.copy(),
                            cfg,
                            interval_map=sleeve_interval_map,
                        )
                        current_w = clean_target_w
                        current_sleeve_map = _current_sleeve_map_from_portfolio(current_portfolio)
                        rebalance_action = "initial_rebalance" if not prev_w else "rebalance"
                    if circuit_breaker_active:
                        rebalance_action = "circuit_breaker_rebalance"
                    elif breaker_event == "recovered":
                        rebalance_action = "circuit_breaker_release"
                    turn = turnover(prev_w, current_w)
                    cost = turn * (effective_roundtrip_cost_bps / 10000.0)
                    rebalance_dates_taken.append(dt)
                    if sleeve_specific_rebalance_enabled:
                        for sleeve in due_sleeves:
                            next_scheduled_dt_by_sleeve[sleeve] = next_rebalance_date_for_interval(
                                dt,
                                interval_months=int(sleeve_interval_map.get(sleeve, fixed_interval_months)),
                            )
                            sleeve_rebalance_counts[sleeve] = int(sleeve_rebalance_counts.get(sleeve, 0)) + 1
                        scheduled_values = [
                            pd.Timestamp(x)
                            for x in next_scheduled_dt_by_sleeve.values()
                            if pd.notna(x)
                        ]
                        next_scheduled_dt = min(scheduled_values) if scheduled_values else pd.NaT
                        active_interval_months = int(
                            max(
                                round(
                                    float(
                                        np.mean(
                                            [
                                                float(sleeve_interval_map.get(sleeve, fixed_interval_months))
                                                for sleeve in due_sleeves
                                            ]
                                        )
                                    )
                                ),
                                1,
                            )
                        )
                    elif adaptive_interval_policy:
                        policy = infer_rebalance_interval_policy(
                            cfg,
                            mm,
                            latest_live_event_alert=_live_label_for_month(mm),
                            allowed_intervals=allowed_intervals,
                        )
                        active_interval_months = int(policy.get("target_interval_months", fixed_interval_months))
                    else:
                        active_interval_months = int(fixed_interval_months)
                        next_scheduled_dt = next_rebalance_date_for_interval(
                            dt,
                            interval_months=active_interval_months,
                        )
                else:
                    rebalance_action = "hold_after_empty_rebalance" if current_w else "skip_empty_rebalance"
            else:
                rebalance_action = "hold_missing_signals" if current_w else "skip_missing_signals"

        if not current_w:
            continue

        holdings_source = current_portfolio if not current_portfolio.empty else mm
        month_holding_row_indices: list[int] = []
        due_sleeves_value = ",".join(sorted({str(x) for x in due_sleeves})) if rebalance_due and due_sleeves else ""
        for tkr, ww in current_w.items():
            row = holdings_source[holdings_source["ticker"] == tkr]
            if str(tkr).upper() == CASH_PROXY_TICKER:
                sec = "Cash"
                nm = "Cash"
            else:
                sec = row["sector"].iloc[0] if not row.empty else "Unknown"
                nm = row["Name"].iloc[0] if not row.empty else ""
            sleeve_label_value = (
                str(row["portfolio_sleeve_label"].iloc[0])
                if not row.empty and "portfolio_sleeve_label" in row.columns
                else ("cash" if str(tkr).upper() == CASH_PROXY_TICKER else "core_compounder")
            )
            sleeve_role_value = (
                str(row["portfolio_sleeve_role"].iloc[0])
                if not row.empty and "portfolio_sleeve_role" in row.columns
                else {
                    "future_winner": "multi_bagger",
                    "early_scout": "early_scout",
                    "core_compounder": "core_compounder",
                    "cash": "cash",
                }.get(sleeve_label_value, sleeve_label_value)
            )
            month_holding_row_indices.append(len(holdings_rows))
            holdings_rows.append(
                {
                    "rebalance_date": dt,
                    "ticker": tkr,
                    "Name": nm,
                    "sector": sec,
                    "weight": ww,
                    "raw_score": float(row["score"].iloc[0]) if not row.empty else np.nan,
                    "portfolio_sleeve_label": sleeve_label_value,
                    "portfolio_sleeve_role": sleeve_role_value,
                    "portfolio_selection_path": (
                        str(row["portfolio_selection_path"].iloc[0])
                        if not row.empty and "portfolio_selection_path" in row.columns
                        else ""
                    ),
                    "period_forward_return": np.nan,
                    "weighted_forward_return": np.nan,
                    "target_n": int(current_meta.get("target_n", 0)),
                    "weight_cap": float(current_meta.get("weight_cap", cfg.stock_weight_max)),
                    "cash_target": float(current_meta.get("cash_target", 0.0)),
                    "rebalance_action": rebalance_action,
                    "due_sleeves": due_sleeves_value,
                    "active_rebalance_interval_months": int(active_interval_months),
                    "sleeve_rebalance_interval_months": int(
                        row["sleeve_rebalance_interval_months"].iloc[0]
                    ) if not row.empty and "sleeve_rebalance_interval_months" in row.columns else int(
                        sleeve_interval_map.get(sleeve_label_value, active_interval_months)
                    ),
                    "next_scheduled_rebalance_date": str(pd.Timestamp(next_scheduled_dt).date()) if pd.notna(next_scheduled_dt) else None,
                }
            )

        month_ret = 0.0
        missing = 0
        ticker_month_returns: dict[str, float] = {}
        for tkr, ww in current_w.items():
            ri = month_forward_return_open(paths, tkr, dt + pd.Timedelta(days=1), next_dt + pd.Timedelta(days=1))
            if ri is None:
                missing += 1
                continue
            month_ret += ww * ri
            ticker_month_returns[tkr] = float(ri)
        for row_idx in month_holding_row_indices:
            held_ticker = str(holdings_rows[row_idx].get("ticker", ""))
            held_return = ticker_month_returns.get(held_ticker, 0.0 if held_ticker.upper() == CASH_PROXY_TICKER else np.nan)
            holdings_rows[row_idx]["period_forward_return"] = float(held_return) if pd.notna(held_return) else np.nan
            held_weight = float(holdings_rows[row_idx].get("weight", 0.0))
            holdings_rows[row_idx]["weighted_forward_return"] = held_weight * float(held_return) if pd.notna(held_return) else np.nan
        net_ret = month_ret - cost
        running_equity = running_equity * (1.0 + net_ret)
        portfolio_peak = max(portfolio_peak, running_equity)
        drawdown_after_month = float((running_equity - portfolio_peak) / max(portfolio_peak, 1e-8))
        # Phase 6c: track trailing monthly net returns for vol targeting.
        # Always populated so diagnostics are consistent; Phase 6c only
        # ACTS on it when `_phase6c_active` is True above.
        recent_returns.append(float(net_ret))
        if len(recent_returns) > max(int(_p6c_lookback), 12):
            # cap memory to at most 12 months to avoid unbounded growth.
            recent_returns = recent_returns[-12:]
        current_w = drift_weights_by_period_returns(current_w, ticker_month_returns)

        # Hard stop-loss: track speculative positions and force-exit at -25%
        if stop_loss_pct > 0:
            is_spec = {}
            if not current_portfolio.empty and "_is_speculative" in current_portfolio.columns:
                for _, row in current_portfolio.iterrows():
                    t = str(row.get("ticker", ""))
                    if float(row.get("_is_speculative", 0.0)) > 0.5:
                        is_spec[t] = True
            # Update cumulative returns
            new_cum = {}
            for tkr in list(current_w.keys()):
                if tkr == CASH_PROXY_TICKER:
                    continue
                r_m = ticker_month_returns.get(tkr, 0.0)
                if tkr in speculative_cum_ret:
                    new_cum[tkr] = (1 + speculative_cum_ret[tkr]) * (1 + r_m) - 1
                elif is_spec.get(tkr, False):
                    new_cum[tkr] = r_m
            speculative_cum_ret = new_cum
            # Check stop-loss
            for tkr, cum_r in list(speculative_cum_ret.items()):
                if cum_r <= -stop_loss_pct:
                    stopped_out_tickers.add(tkr)
                    if tkr in current_w:
                        released = float(current_w.pop(tkr, 0.0))
                        current_w[CASH_PROXY_TICKER] = float(current_w.get(CASH_PROXY_TICKER, 0.0)) + released
                    del speculative_cum_ret[tkr]
            # Clean up tickers no longer held
            for tkr in list(speculative_cum_ret.keys()):
                if tkr not in current_w:
                    del speculative_cum_ret[tkr]
            # Clear stopped_out set at rebalance (allow re-entry if signals improve)
            if rebalance_action in ("rebalance", "initial_rebalance") or str(rebalance_action).startswith("partial_rebalance:"):
                stopped_out_tickers.clear()
        if current_w:
            current_total = float(sum(float(v) for v in current_w.values() if pd.notna(v)))
            if current_total > 0 and abs(current_total - 1.0) > 1e-8:
                current_w = {str(k): float(v / current_total) for k, v in current_w.items() if pd.notna(v) and float(v) > 1e-10}
        if not current_portfolio.empty and "ticker" in current_portfolio.columns:
            keep_tickers = {
                str(k)
                for k in current_w.keys()
                if str(k).upper() != CASH_PROXY_TICKER
            }
            current_portfolio = current_portfolio[
                current_portfolio["ticker"].astype(str).isin(keep_tickers)
            ].copy()
        sleeve_policy_snapshot = current_meta.get("sleeve_policy", {}) if isinstance(current_meta, dict) else {}
        ret_rows.append(
            {
                "rebalance_date": dt,
                "next_rebalance_date": next_dt,
                "gross_return": month_ret,
                "cost": cost,
                "net_return": net_ret,
                "turnover": turn,
                "missing_tickers": missing,
                "cash_weight": float(current_w.get(CASH_PROXY_TICKER, 0.0)),
                "rebalance_action": rebalance_action,
                "due_sleeves": due_sleeves_value,
                "active_rebalance_interval_months": int(active_interval_months),
                "next_scheduled_rebalance_date": str(pd.Timestamp(next_scheduled_dt).date()) if pd.notna(next_scheduled_dt) else None,
                "sleeve_specific_rebalance_enabled": bool(sleeve_specific_rebalance_enabled),
                "sleeve_rebalance_interval_map": json.dumps(
                    {str(k): int(v) for k, v in sleeve_interval_map.items()},
                    sort_keys=True,
                ),
                "target_n": int(current_meta.get("target_n", 0)),
                "weight_cap": float(current_meta.get("weight_cap", cfg.stock_weight_max)),
                "cash_target": float(current_meta.get("cash_target", 0.0)),
                "regime_label": _live_label_for_month(mm),
                "core_target": float(sleeve_policy_snapshot.get("core_compounder_target", np.nan)),
                "future_target": float(sleeve_policy_snapshot.get("future_winner_target", np.nan)),
                "early_target": float(sleeve_policy_snapshot.get("early_scout_target", np.nan)),
                "cash_target_used": float(sleeve_policy_snapshot.get("cash_target", current_meta.get("cash_target", np.nan))),
                "growth_signal": float(sleeve_policy_snapshot.get("growth_signal", np.nan)),
                "risk_signal": float(sleeve_policy_snapshot.get("risk_signal", np.nan)),
                "drawdown_before_month": drawdown_before_month,
                "drawdown_after_month": drawdown_after_month,
                "equity_after_month": running_equity,
                "equity_peak": portfolio_peak,
                "drawdown_circuit_breaker_active": bool(circuit_breaker_active),
                "drawdown_circuit_breaker_event": breaker_event,
                "drawdown_circuit_breaker_cash_target": float(breaker_cash_target if circuit_breaker_active else 0.0),
                # Phase 6a diagnostics (always populated; 0 when Phase 6a off).
                "dd_breaker_level": int(dd_active_level) if _phase6a_active else 0,
                "dd_trigger_equity": float(dd_trigger_equity) if _phase6a_active else 0.0,
                "dd_breaker_multilevel_active": 1 if _phase6a_active else 0,
                # Phase 6c diagnostics (vol targeting).
                "vol_target_active": 1 if _phase6c_active else 0,
                "vol_cash_floor_p6c": float(vol_cash_floor_p6c) if _phase6c_active else 0.0,
                "recent_returns_len": int(len(recent_returns)),
            }
        )

    ret_df = pd.DataFrame(ret_rows)
    if ret_df.empty:
        raise RuntimeError("Backtest produced no monthly returns.")
    ret_df["rebalance_date"] = pd.to_datetime(ret_df["rebalance_date"])
    ret_df = ret_df.sort_values("rebalance_date")
    ret_df["equity"] = (1.0 + ret_df["net_return"]).cumprod()
    ret_df["equity_value_usd"] = starting_capital_usd * ret_df["equity"]

    bench = []
    benchmark_close = load_benchmark_price_series(cfg, paths)
    if not benchmark_close.empty:
        for r in ret_df.itertuples(index=False):
            rr = return_series_between_dates(
                benchmark_close,
                r.rebalance_date + pd.Timedelta(days=1),
                r.next_rebalance_date + pd.Timedelta(days=1),
            )
            bench.append(rr if rr is not None else np.nan)
    else:
        bench = [np.nan] * len(ret_df)
    ret_df["bench_return"] = bench

    metrics = performance_metrics(ret_df["net_return"], benchmark=ret_df["bench_return"])
    metrics["avg_turnover_monthly"] = float(ret_df["turnover"].mean())
    metrics["avg_cash_weight"] = float(ret_df["cash_weight"].mean()) if "cash_weight" in ret_df.columns else 0.0
    metrics["trade_cost_bps_per_side"] = float(effective_roundtrip_cost_bps / 2.0)
    metrics["cost_bps_roundtrip"] = float(effective_roundtrip_cost_bps)
    metrics["months"] = int(len(ret_df))
    metrics["target_n_override"] = int(target_n_override) if target_n_override is not None else None
    rebalance_intervals = (
        [_month_gap(later, earlier) for earlier, later in zip(rebalance_dates_taken[:-1], rebalance_dates_taken[1:])]
        if len(rebalance_dates_taken) >= 2
        else []
    )
    avg_interval = float(np.mean(rebalance_intervals)) if rebalance_intervals else float(active_interval_months)
    metrics["rebalance_interval_months"] = int(
        max(int(round(avg_interval)), 1)
        if (adaptive_interval_policy or sleeve_specific_rebalance_enabled)
        else int(fixed_interval_months)
    )
    metrics["avg_rebalance_interval_months"] = float(avg_interval)
    metrics["adaptive_rebalance_policy"] = bool(adaptive_interval_policy)
    metrics["sleeve_specific_rebalance_enabled"] = bool(sleeve_specific_rebalance_enabled)
    metrics["sleeve_rebalance_interval_map"] = {
        str(k): int(v) for k, v in sleeve_interval_map.items()
    }
    metrics["sleeve_rebalance_counts"] = {
        str(k): int(v) for k, v in sleeve_rebalance_counts.items()
    }
    metrics["rebalance_count"] = int(len(rebalance_dates_taken))
    metrics["rebalanced_month_ratio"] = float(len(rebalance_dates_taken) / max(len(ret_df), 1))
    metrics["benchmark_source"] = benchmark_history_source_label(cfg)
    metrics["starting_capital_usd"] = starting_capital_usd
    if ret_df["bench_return"].notna().any():
        bench_eq = (1.0 + ret_df["bench_return"].fillna(0.0)).cumprod()
        ret_df["benchmark_equity"] = bench_eq
        ret_df["benchmark_value_usd"] = starting_capital_usd * bench_eq
        years = max(len(ret_df), 1) / 12.0
        metrics["benchmark_cagr"] = float(bench_eq.iloc[-1] ** (1.0 / years) - 1.0) if years > 0 else np.nan
        metrics["excess_cagr"] = float(metrics.get("cagr", np.nan) - metrics.get("benchmark_cagr", np.nan))
        metrics["beat_month_ratio"] = float((ret_df["net_return"] > ret_df["bench_return"]).mean())
        metrics["benchmark_ending_capital_usd"] = float(ret_df["benchmark_value_usd"].iloc[-1])
    else:
        metrics["benchmark_cagr"] = np.nan
        metrics["excess_cagr"] = np.nan
        metrics["beat_month_ratio"] = np.nan
        ret_df["benchmark_equity"] = np.nan
        ret_df["benchmark_value_usd"] = np.nan
        metrics["benchmark_ending_capital_usd"] = np.nan
    metrics["ending_capital_usd"] = float(ret_df["equity_value_usd"].iloc[-1])

    holdings_df = pd.DataFrame(holdings_rows)
    if not holdings_df.empty:
        stock_names = holdings_df[
            holdings_df["ticker"].astype(str).str.upper() != CASH_PROXY_TICKER
        ].groupby("rebalance_date")["ticker"].nunique()
        metrics["avg_stock_names"] = float(stock_names.mean()) if not stock_names.empty else 0.0
    else:
        metrics["avg_stock_names"] = 0.0
    # Base equity columns + any Phase 6a / 6c diagnostic columns that
    # were populated in ret_rows. `equity_curve.csv` downstream is the
    # only end-user view of these diagnostics; keep them if they exist
    # so the next run-verification step can inspect breaker activations
    # / vol-target floors without re-running the backtest.
    _equity_cols = [
        "rebalance_date",
        "equity",
        "equity_value_usd",
        "benchmark_equity",
        "benchmark_value_usd",
        "net_return",
        "bench_return",
    ]
    for _diag_col in (
        "drawdown_before_month",
        "drawdown_after_month",
        "equity_peak",
        "drawdown_circuit_breaker_active",
        "drawdown_circuit_breaker_event",
        "drawdown_circuit_breaker_cash_target",
        "dd_breaker_level",
        "dd_trigger_equity",
        "dd_breaker_multilevel_active",
        "vol_target_active",
        "vol_cash_floor_p6c",
        "recent_returns_len",
    ):
        if _diag_col in ret_df.columns and _diag_col not in _equity_cols:
            _equity_cols.append(_diag_col)
    equity_df = ret_df[_equity_cols].copy()
    return BacktestResult(holdings=holdings_df, monthly_returns=ret_df, metrics=metrics, equity_curve=equity_df)


def build_latest_recommendations(cfg: dict | EngineConfig, features: pd.DataFrame) -> pd.DataFrame:
    cfg = to_cfg(cfg)
    paths = get_paths(cfg)
    model_features = model_feature_columns(cfg)
    model_bundle = load_model_bundle_json(paths)
    log("Phase 5b: scoring latest recommendation set ...")
    catboost_components = resolve_optional_catboost()
    catboost_available = bool(catboost_components.get("available", False))
    CatBoostClassifier = catboost_components.get("CatBoostClassifier")
    CatBoostRanker = catboost_components.get("CatBoostRanker")
    CatBoostRegressor = catboost_components.get("CatBoostRegressor")
    if not catboost_available:
        log(
            "[WARN] Phase 5b: catboost unavailable; continuing with linear-only latest scoring. "
            f"reason={catboost_components.get('error') or 'not installed'}"
        )

    d = features.copy()
    if "rebalance_date" not in d.columns and "Date" in d.columns:
        d = d.rename(columns={"Date": "rebalance_date"})
    d["rebalance_date"] = pd.to_datetime(d["rebalance_date"], errors="coerce")
    d["feature_date"] = pd.to_datetime(d["feature_date"], errors="coerce")
    d = d.sort_values(["rebalance_date", "ticker"]).reset_index(drop=True)
    latest_dt = pd.to_datetime(d["rebalance_date"], errors="coerce").max()
    if pd.isna(latest_dt):
        raise RuntimeError("Latest recommendation scoring failed because no rebalance_date is available.")

    for f in model_features:
        if f not in d.columns:
            d[f] = 0.0

    latest_df = d[d["rebalance_date"] == latest_dt].copy()
    latest_df = latest_df[latest_df["feature_date"].notna()]
    latest_df = normalize_latest_fundamental_snapshot(
        cfg,
        paths,
        latest_df,
        clear_latest_only_signals=bool(cfg.strict_live_backtest_alignment),
        apply_statement_repair=True,
        add_fundamental_flags=False,
    )
    latest_df = hard_sanitize(latest_df, model_features + ["mktcap"], clip=1e12)

    hist = clear_latest_only_signal_columns(d)
    hist = compute_live_factor_columns(hist, cfg)
    hist = compute_valuation_columns(hist, cfg)
    hist = hard_sanitize(
        hist,
        model_features
        + ["r_1m", "r_3m", "r_6m", "r_12m", "r_24m", "r_36m", "bench_r_1m", "bench_r_3m", "bench_r_6m", "bench_r_12m", "bench_r_24m", "bench_r_36m", "mktcap"],
        clip=1e12,
    )
    hist = hist[hist["feature_date"].notna()]
    hist = hist[hist["r_1m"].notna() | hist["r_3m"].notna() | hist["r_6m"].notna()]

    mktcap_cov = float(hist["mktcap"].notna().mean()) if len(hist) else 0.0
    if mktcap_cov >= 0.25:
        hist = hist[hist["mktcap"].notna()]
        latest_df = latest_df[latest_df["mktcap"].notna()]

    hist = hist[hist["px"].fillna(0) >= cfg.min_price]
    latest_df = latest_df[latest_df["px"].fillna(0) >= cfg.min_price]

    hist_dv = pd.to_numeric(hist["dollar_vol_20d"], errors="coerce")
    latest_dv = pd.to_numeric(latest_df["dollar_vol_20d"], errors="coerce")
    min_dv = cfg.min_dollar_vol_20d
    hist_dv_max = float(np.nanmax(hist_dv.values)) if len(hist_dv.dropna()) else np.nan
    if pd.notna(hist_dv_max) and hist_dv_max <= 1_100_000 and cfg.min_dollar_vol_20d > hist_dv_max:
        min_dv = 500_000.0
    hist = hist[hist_dv.fillna(0) >= min_dv]
    latest_df = latest_df[latest_dv.fillna(0) >= min_dv]

    if latest_df.empty:
        raise RuntimeError("Latest recommendation set is empty after price/liquidity filters.")

    y_all, ybin_all = make_targets(hist, cfg)
    hist["y_blend"] = y_all
    hist["y_bin"] = ybin_all
    future_y_all, future_ybin_all, future_avail_all = make_future_winner_targets(hist, cfg)
    hist["future_winner_y"] = future_y_all
    hist["future_winner_bin"] = future_ybin_all
    hist["future_winner_available"] = future_avail_all

    train_start = latest_dt - pd.DateOffset(years=cfg.train_lookback_years)
    train_end = latest_dt - pd.Timedelta(days=cfg.embargo_days)
    train_df = hist[(hist["feature_date"] >= train_start) & (hist["feature_date"] <= train_end)].copy()
    if len(train_df) < max(800, cfg.min_train_samples // 3):
        train_df = hist[(hist["feature_date"] >= train_start) & (hist["rebalance_date"] < latest_dt)].copy()
    if len(train_df) < 500:
        raise RuntimeError(
            "Latest recommendation training set is too small. "
            f"train_rows={len(train_df)}, latest_date={pd.Timestamp(latest_dt).date()}"
        )

    latest_df = compute_actual_priority_columns(latest_df, cfg)
    latest_df = compute_latest_flow_factor_columns(latest_df)
    latest_df = compute_macro_interaction_features(latest_df)
    latest_df = compute_market_adaptation_features(latest_df)
    latest_df = compute_event_regime_features(latest_df)
    latest_df = compute_moat_proxy_features(latest_df)
    latest_df = compute_dynamic_leadership_features(latest_df)
    latest_df = compute_three_level_relative_strength(latest_df)
    latest_df = compute_crisis_sector_fit(latest_df)
    latest_df = compute_strategy_blueprint_columns(latest_df, cfg)
    latest_df = compute_multidimensional_pillar_scores(latest_df)
    latest_df = add_core_fundamental_minimum_flags(latest_df, cfg)
    live_coverage = numeric_series_or_default(latest_df, "analyst_coverage_proxy", 0.0)
    coverage_mask = live_coverage >= float(cfg.min_live_estimate_coverage)
    min_keep = max(int(cfg.top_n) * 2, 40)
    if int(coverage_mask.sum()) >= min_keep:
        latest_df = latest_df[coverage_mask].copy()
    latest_df = add_core_fundamental_minimum_flags(latest_df, cfg)

    adaptive_history = pd.DataFrame()
    scored_oos_path = paths["feature_store"] / "scored_oos_latest.parquet"
    if scored_oos_path.exists():
        try:
            adaptive_history = pd.read_parquet(scored_oos_path)
        except Exception:
            adaptive_history = pd.DataFrame()
    adaptive_as_of = pd.to_datetime(latest_df["rebalance_date"], errors="coerce").max()

    reuse_meta = None
    if bool(getattr(cfg, "reuse_phase4_models_for_latest_recommendations", True)):
        reuse_meta = load_phase4_latest_scoring_artifacts(paths, model_features)
    if reuse_meta is not None:
        log("Phase 5b: reusing freshest phase4 models for latest scoring ...")
        X_latest = apply_scaler(latest_df, reuse_meta["scaler"], model_features)
        latest_df["pred_lin_ret"] = ridge_predict_from_meta(X_latest, reuse_meta)
        latest_df["pred_lin_p"] = logreg_predict_proba_from_meta(X_latest, reuse_meta)
        latest_df["pred_future_winner_ret"] = ridge_predict_from_meta(X_latest, reuse_meta, key="future_ridge")
        latest_df["pred_future_winner_p"] = logreg_predict_proba_from_meta(X_latest, reuse_meta, key="future_logreg")
        latest_df["pred_cat_ret"] = 0.0
        latest_df["pred_cat_p"] = 0.0
        latest_df["pred_rank"] = 0.0
        art = phase4_latest_model_paths(paths)
        if catboost_available:
            try:
                if art["cat_reg"].exists():
                    cat_reg = CatBoostRegressor()
                    cat_reg.load_model(str(art["cat_reg"]))
                    latest_df["pred_cat_ret"] = cat_reg.predict(X_latest)
            except Exception:
                latest_df["pred_cat_ret"] = 0.0
            try:
                if art["cat_cls"].exists():
                    cat_cls = CatBoostClassifier()
                    cat_cls.load_model(str(art["cat_cls"]))
                    latest_df["pred_cat_p"] = cat_cls.predict_proba(X_latest)[:, 1]
            except Exception:
                latest_df["pred_cat_p"] = 0.0
            try:
                if bool(reuse_meta.get("ranking_enabled", False)) and art["cat_rank"].exists():
                    cat_rank = CatBoostRanker()
                    cat_rank.load_model(str(art["cat_rank"]))
                    latest_df["pred_rank"] = cat_rank.predict(X_latest)
            except Exception:
                latest_df["pred_rank"] = 0.0

        latest_df = add_model_score_columns(
            latest_df,
            {
                "lin_ret": "pred_lin_ret",
                "lin_p": "pred_lin_p",
                "cat_ret": "pred_cat_ret",
                "cat_p": "pred_cat_p",
                "rank": "pred_rank",
            },
            cfg=cfg,
        )
        latest_adaptive_state = compute_adaptive_ensemble_state(adaptive_history, cfg, as_of_date=adaptive_as_of)
        if (not latest_adaptive_state.get("active")) and model_bundle is not None:
            latest_adaptive_state = {
                "weights": dict(getattr(model_bundle, "adaptive_ensemble_weights", {}) or {}),
                "quality": dict((getattr(model_bundle, "adaptive_ensemble_diagnostics", {}) or {}).get("quality", {}) or {}),
                "history_months": int((getattr(model_bundle, "adaptive_ensemble_diagnostics", {}) or {}).get("history_months", 0)),
                "active": bool((getattr(model_bundle, "adaptive_ensemble_diagnostics", {}) or {}).get("active", False)),
            }
        _regime_w = dict(getattr(model_bundle, "regime_ensemble_weights", {}) or {}) if model_bundle is not None else {}
        latest_df = apply_adaptive_ensemble_state(latest_df, latest_adaptive_state, regime_weights=_regime_w or None)
        latest_df = add_total_score_columns(
            latest_df,
            cfg,
            include_satellite=True,
            include_latest_only_satellite=not bool(cfg.strict_live_backtest_alignment),
        )
        latest_df = apply_focus_score_overlay(latest_df, cfg)
        latest_df = apply_latest_sentiment_satellite_overlay(latest_df, cfg)
        latest_df = compute_portfolio_sleeve_columns(latest_df, cfg)
        latest_df = apply_latest_ranking_eligibility(latest_df, cfg, context="Phase 5b latest ranking")
        eligible_count = int(latest_df["ranking_eligible"].sum())
        if eligible_count < int(cfg.min_port_names):
            raise RuntimeError(
                "Latest recommendation set does not have enough sleeve-qualified names after screening. "
                f"eligible={eligible_count}, required={int(cfg.min_port_names)}"
            )
        if eligible_count < int(cfg.top_n):
            log(
                "[WARN] Latest ranking has fewer sleeve-qualified names than requested top_n. "
                f"eligible={eligible_count}, top_n={int(cfg.top_n)}"
            )
        latest_df = apply_sleeve_rebalance_interval_columns(latest_df, cfg)
        latest_df["score_rank"] = latest_df["score"].rank(method="first", ascending=False)
        latest_df = latest_df.sort_values(["ranking_eligible", "score"], ascending=[False, False]).reset_index(drop=True)
        latest_df.to_parquet(paths["feature_store"] / "latest_recommendations.parquet", index=False)
        return latest_df

    scaler = fit_scaler(train_df, model_features)
    X_train = apply_scaler(train_df, scaler, model_features)
    X_latest = apply_scaler(latest_df, scaler, model_features)
    y_train = train_df["y_blend"].values
    ybin_train = train_df["y_bin"].values
    future_train_df = train_df[train_df["future_winner_available"].fillna(False).astype(bool)].copy()

    reg = Ridge(alpha=cfg.ridge_alpha, fit_intercept=True, random_state=cfg.random_seed)
    reg.fit(X_train, y_train)
    latest_df["pred_lin_ret"] = reg.predict(X_latest)

    if len(np.unique(ybin_train)) >= 2:
        clf = LogisticRegression(C=cfg.logreg_c, max_iter=1200, random_state=cfg.random_seed)
        clf.fit(X_train, ybin_train)
        latest_df["pred_lin_p"] = clf.predict_proba(X_latest)[:, 1]
    else:
        latest_df["pred_lin_p"] = 0.0

    latest_df["pred_future_winner_ret"] = 0.0
    latest_df["pred_future_winner_p"] = 0.0
    if len(future_train_df) >= max(300, cfg.min_train_samples // 5):
        X_future_train = apply_scaler(future_train_df, scaler, model_features)
        y_future_train = pd.to_numeric(future_train_df["future_winner_y"], errors="coerce").fillna(0.0).values
        future_reg = Ridge(
            alpha=max(float(cfg.ridge_alpha) * 0.75, 0.10),
            fit_intercept=True,
            random_state=cfg.random_seed,
        )
        future_reg.fit(X_future_train, y_future_train)
        latest_df["pred_future_winner_ret"] = future_reg.predict(X_latest)
        ybin_future_train = pd.to_numeric(
            future_train_df["future_winner_bin"], errors="coerce"
        ).fillna(0).astype(int).values
        if len(np.unique(ybin_future_train)) >= 2 and int(ybin_future_train.sum()) >= max(30, int(0.02 * len(ybin_future_train))):
            future_clf = LogisticRegression(
                C=max(float(cfg.logreg_c) * 0.8, 0.25),
                max_iter=1200,
                random_state=cfg.random_seed,
            )
            future_clf.fit(X_future_train, ybin_future_train)
            latest_df["pred_future_winner_p"] = future_clf.predict_proba(X_latest)[:, 1]

    task_type = choose_catboost_task_type() if catboost_available else "CPU"
    if catboost_available:
        try:
            cbr = CatBoostRegressor(
                loss_function="RMSE",
                iterations=cfg.cat_reg_iterations,
                depth=cfg.cat_depth,
                learning_rate=cfg.cat_learning_rate,
                random_seed=cfg.random_seed,
                verbose=False,
                task_type=task_type,
            )
            cbr.fit(X_train, y_train)
            latest_df["pred_cat_ret"] = cbr.predict(X_latest)
        except Exception:
            latest_df["pred_cat_ret"] = 0.0
    else:
        latest_df["pred_cat_ret"] = 0.0

    if len(np.unique(ybin_train)) >= 2 and catboost_available:
        try:
            cbc = CatBoostClassifier(
                loss_function="Logloss",
                iterations=cfg.cat_cls_iterations,
                depth=cfg.cat_depth,
                learning_rate=cfg.cat_learning_rate,
                random_seed=cfg.random_seed,
                verbose=False,
                task_type=task_type,
            )
            cbc.fit(X_train, ybin_train)
            latest_df["pred_cat_p"] = cbc.predict_proba(X_latest)[:, 1]
        except Exception:
            latest_df["pred_cat_p"] = 0.0
    else:
        latest_df["pred_cat_p"] = 0.0

    if cfg.ranking_enabled and catboost_available:
        try:
            cbrk = CatBoostRanker(
                loss_function="YetiRankPairwise",
                eval_metric=f"NDCG:top={max(int(cfg.rank_eval_top_k), 5)}",
                iterations=cfg.cat_rank_iterations,
                depth=cfg.cat_depth,
                learning_rate=cfg.cat_learning_rate,
                random_seed=cfg.random_seed,
                verbose=False,
                task_type=task_type,
            )
            cbrk.fit(X_train, y_train, group_id=month_group_ids(train_df["rebalance_date"]))
            latest_df["pred_rank"] = cbrk.predict(X_latest)
        except Exception:
            latest_df["pred_rank"] = 0.0
    else:
        latest_df["pred_rank"] = 0.0

    latest_df = add_model_score_columns(
        latest_df,
        {
            "lin_ret": "pred_lin_ret",
            "lin_p": "pred_lin_p",
            "cat_ret": "pred_cat_ret",
            "cat_p": "pred_cat_p",
            "rank": "pred_rank",
        },
        cfg=cfg,
    )
    latest_adaptive_state = compute_adaptive_ensemble_state(adaptive_history, cfg, as_of_date=adaptive_as_of)
    if (not latest_adaptive_state.get("active")) and model_bundle is not None:
        latest_adaptive_state = {
            "weights": dict(getattr(model_bundle, "adaptive_ensemble_weights", {}) or {}),
            "quality": dict((getattr(model_bundle, "adaptive_ensemble_diagnostics", {}) or {}).get("quality", {}) or {}),
            "history_months": int((getattr(model_bundle, "adaptive_ensemble_diagnostics", {}) or {}).get("history_months", 0)),
            "active": bool((getattr(model_bundle, "adaptive_ensemble_diagnostics", {}) or {}).get("active", False)),
        }
    _regime_w = dict(getattr(model_bundle, "regime_ensemble_weights", {}) or {}) if model_bundle is not None else {}
    latest_df = apply_adaptive_ensemble_state(latest_df, latest_adaptive_state, regime_weights=_regime_w or None)
    latest_df = add_total_score_columns(
        latest_df,
        cfg,
        include_satellite=True,
        include_latest_only_satellite=not bool(cfg.strict_live_backtest_alignment),
    )
    latest_df = apply_focus_score_overlay(latest_df, cfg)
    latest_df = apply_latest_sentiment_satellite_overlay(latest_df, cfg)
    latest_df = compute_portfolio_sleeve_columns(latest_df, cfg)
    latest_df = apply_latest_ranking_eligibility(latest_df, cfg, context="Phase 5b latest ranking")
    eligible_count = int(latest_df["ranking_eligible"].sum())
    if eligible_count < int(cfg.min_port_names):
        raise RuntimeError(
            "Latest recommendation set does not have enough sleeve-qualified names after screening. "
            f"eligible={eligible_count}, required={int(cfg.min_port_names)}"
        )
    if eligible_count < int(cfg.top_n):
        log(
            "[WARN] Latest ranking has fewer sleeve-qualified names than requested top_n. "
            f"eligible={eligible_count}, top_n={int(cfg.top_n)}"
        )
    latest_df = apply_sleeve_rebalance_interval_columns(latest_df, cfg)
    latest_df["score_rank"] = latest_df["score"].rank(method="first", ascending=False)
    latest_df = latest_df.sort_values(["ranking_eligible", "score"], ascending=[False, False]).reset_index(drop=True)
    latest_df.to_parquet(paths["feature_store"] / "latest_recommendations.parquet", index=False)
    return latest_df


def fallback_latest_recommendations_from_scored(
    cfg: dict | EngineConfig,
    paths: dict[str, Path],
    feature_store: pd.DataFrame,
    scored: pd.DataFrame,
    reason: Optional[BaseException] = None,
) -> pd.DataFrame:
    cfg = to_cfg(cfg)
    scored_latest = scored.copy()
    if scored_latest.empty:
        raise RuntimeError("Latest recommendation fallback failed because scored signals are empty.")
    if "rebalance_date" not in scored_latest.columns:
        raise RuntimeError("Latest recommendation fallback failed because scored signals lack rebalance_date.")
    scored_latest["rebalance_date"] = pd.to_datetime(scored_latest["rebalance_date"], errors="coerce")
    latest_dt = pd.to_datetime(scored_latest["rebalance_date"], errors="coerce").max()
    if pd.isna(latest_dt):
        raise RuntimeError("Latest recommendation fallback failed because scored signals have no valid latest date.")
    scored_latest = scored_latest[scored_latest["rebalance_date"] == latest_dt].copy()
    if scored_latest.empty:
        raise RuntimeError("Latest recommendation fallback failed because latest scored slice is empty.")

    if "ticker" in scored_latest.columns:
        scored_latest["ticker"] = scored_latest["ticker"].astype(str).str.upper().str.strip()
    if "rebalance_date" in feature_store.columns:
        feature_latest = feature_store.copy()
        feature_latest["rebalance_date"] = pd.to_datetime(feature_latest["rebalance_date"], errors="coerce")
        feature_latest = feature_latest[feature_latest["rebalance_date"] == latest_dt].copy()
        if "ticker" in feature_latest.columns:
            feature_latest["ticker"] = feature_latest["ticker"].astype(str).str.upper().str.strip()
        merge_keys = [c for c in ["ticker", "rebalance_date"] if c in scored_latest.columns and c in feature_latest.columns]
        if merge_keys:
            extra_cols = [c for c in feature_latest.columns if c not in scored_latest.columns and c not in merge_keys]
            if extra_cols:
                scored_latest = scored_latest.merge(
                    feature_latest[merge_keys + extra_cols].drop_duplicates(merge_keys, keep="last"),
                    on=merge_keys,
                    how="left",
                )

    scored_latest = normalize_latest_fundamental_snapshot(
        cfg,
        paths,
        scored_latest,
        clear_latest_only_signals=False,
        apply_statement_repair=False,
        add_fundamental_flags=True,
    )
    if "score" not in scored_latest.columns:
        if "score_total" in scored_latest.columns:
            scored_latest["score"] = pd.to_numeric(scored_latest["score_total"], errors="coerce")
        else:
            scored_latest["score"] = 0.0
    scored_latest["score"] = pd.to_numeric(scored_latest["score"], errors="coerce").fillna(0.0)
    scored_latest = compute_portfolio_sleeve_columns(scored_latest, cfg)
    scored_latest = apply_latest_ranking_eligibility(
        scored_latest,
        cfg,
        context="Phase 5b fallback latest ranking",
    )
    scored_latest = apply_sleeve_rebalance_interval_columns(scored_latest, cfg)
    scored_latest = scored_latest.sort_values(["ranking_eligible", "score"], ascending=[False, False]).reset_index(drop=True)
    scored_latest.to_parquet(paths["feature_store"] / "latest_recommendations.parquet", index=False)
    if reason is not None:
        log(
            "[WARN] Phase 5b: falling back to latest scored snapshot because latest recommendation scoring failed. "
            f"reason={type(reason).__name__}: {reason}"
        )
    return scored_latest


def _bt_metrics_row(bt, cfg_obj: EngineConfig, **extra) -> dict[str, Any]:
    m = bt.metrics
    row = {
        "adaptive_rebalance_policy": bool(m.get("adaptive_rebalance_policy", False)),
        "avg_rebalance_interval_months": float(m.get("avg_rebalance_interval_months", np.nan)),
        "rebalance_count": int(m.get("rebalance_count", 0)),
        "rebalanced_month_ratio": float(m.get("rebalanced_month_ratio", np.nan)),
        "strategy_cagr": float(m.get("cagr", np.nan)),
        "benchmark_cagr": float(m.get("benchmark_cagr", np.nan)),
        "excess_cagr": float(m.get("excess_cagr", np.nan)),
        "sharpe": float(m.get("sharpe", np.nan)),
        "sortino": float(m.get("sortino", np.nan)),
        "max_dd": float(m.get("max_dd", np.nan)),
        "ir": float(m.get("ir", np.nan)) if pd.notna(m.get("ir", np.nan)) else np.nan,
        "beat_month_ratio": float(m.get("beat_month_ratio", np.nan)),
        "avg_turnover_monthly": float(m.get("avg_turnover_monthly", np.nan)),
        "avg_cash_weight": float(m.get("avg_cash_weight", 0.0)),
        "avg_stock_names": float(m.get("avg_stock_names", 0.0)),
        "rebalance_interval_months": int(m.get("rebalance_interval_months", getattr(cfg_obj, "rebalance_interval_months", 1))),
        "trade_cost_bps_per_side": float(m.get("trade_cost_bps_per_side", np.nan)),
        "starting_capital_usd": float(m.get("starting_capital_usd", np.nan)),
        "ending_capital_usd": float(m.get("ending_capital_usd", np.nan)),
        "months": int(m.get("months", 0)),
        "benchmark_source": str(m.get("benchmark_source", benchmark_history_source_label(cfg_obj))),
    }
    row.update(extra)
    return row




SLEEVE_CAP_POLICY_FIELDS: tuple[str, ...] = (
    "core_compounder_sleeve_base_weight",
    "future_winner_sleeve_base_weight",
    "future_winner_sleeve_min_weight",
    "future_winner_sleeve_max_weight",
    "early_scout_sleeve_base_weight",
    "early_scout_sleeve_min_weight",
    "early_scout_sleeve_max_weight",
    "early_scout_growth_floor_weight",
    "early_scout_growth_floor_min_signal",
    "early_scout_growth_floor_max_risk",
    "early_scout_candidate_floor_min_share",
    "future_winner_entry_weight_cap",
    "future_winner_drift_weight_cap",
    "future_winner_hard_weight_cap",
    "early_scout_entry_weight_cap",
    "early_scout_drift_weight_cap",
    "early_scout_hard_weight_cap",
    "sleeve_drift_headroom_pct",
    "stock_weight_max",
    "stock_weight_max_high_conviction",
    "cash_target_growth_cap",
    "cash_target_balanced_cap",
    "cash_target_mild_risk_cap",
    "min_dynamic_port_names",
)


def clone_cfg_with_updates(cfg: dict | EngineConfig, updates: dict[str, Any]) -> EngineConfig:
    cfg_obj = to_cfg(cfg)
    out = to_cfg(asdict(cfg_obj))
    for key, value in updates.items():
        if hasattr(out, key):
            setattr(out, key, value)
    return out


def generate_sleeve_cap_policy_candidates(cfg: dict | EngineConfig) -> list[dict[str, Any]]:
    cfg_obj = to_cfg(cfg)
    base = {field: getattr(cfg_obj, field) for field in SLEEVE_CAP_POLICY_FIELDS if hasattr(cfg_obj, field)}

    def candidate(name: str, description: str, **updates: Any) -> dict[str, Any]:
        row = dict(base)
        row.update(updates)
        row["sleeve_cap_policy_name"] = name
        row["sleeve_cap_policy_description"] = description
        return row

    return [
        candidate(
            "baseline_current",
            "Current configured sleeve/cap policy.",
        ),
        candidate(
            "defensive_drawdown_control",
            "High core weight, low exploratory sleeves, lower caps, and higher mild-risk cash ceiling.",
            core_compounder_sleeve_base_weight=0.55,
            future_winner_sleeve_base_weight=0.25,
            future_winner_sleeve_min_weight=0.00,
            future_winner_sleeve_max_weight=0.35,
            early_scout_sleeve_base_weight=0.10,
            early_scout_sleeve_min_weight=0.02,
            early_scout_sleeve_max_weight=0.18,
            early_scout_growth_floor_weight=0.10,
            early_scout_growth_floor_min_signal=0.34,
            early_scout_growth_floor_max_risk=0.60,
            future_winner_entry_weight_cap=0.07,
            future_winner_drift_weight_cap=0.12,
            future_winner_hard_weight_cap=0.18,
            early_scout_entry_weight_cap=0.04,
            early_scout_drift_weight_cap=0.08,
            early_scout_hard_weight_cap=0.12,
            stock_weight_max=0.12,
            stock_weight_max_high_conviction=0.25,
            cash_target_growth_cap=0.03,
            cash_target_balanced_cap=0.07,
            cash_target_mild_risk_cap=0.18,
            min_dynamic_port_names=18,
        ),
        candidate(
            "quality_balanced",
            "Quality compounder dominant, with a smaller multi-bagger sleeve.",
            core_compounder_sleeve_base_weight=0.50,
            future_winner_sleeve_base_weight=0.32,
            future_winner_sleeve_min_weight=0.08,
            future_winner_sleeve_max_weight=0.50,
            early_scout_sleeve_base_weight=0.15,
            early_scout_sleeve_min_weight=0.02,
            early_scout_sleeve_max_weight=0.22,
            early_scout_growth_floor_weight=0.10,
            future_winner_entry_weight_cap=0.09,
            future_winner_drift_weight_cap=0.16,
            future_winner_hard_weight_cap=0.24,
            early_scout_entry_weight_cap=0.04,
            early_scout_drift_weight_cap=0.08,
            early_scout_hard_weight_cap=0.12,
            stock_weight_max=0.16,
            stock_weight_max_high_conviction=0.38,
            min_dynamic_port_names=14,
        ),
        candidate(
            "growth_balanced",
            "Higher future-winner exposure without letting early scout dominate.",
            core_compounder_sleeve_base_weight=0.25,
            future_winner_sleeve_base_weight=0.45,
            future_winner_sleeve_min_weight=0.12,
            future_winner_sleeve_max_weight=0.68,
            early_scout_sleeve_base_weight=0.30,
            early_scout_sleeve_min_weight=0.05,
            early_scout_sleeve_max_weight=0.36,
            early_scout_growth_floor_weight=0.18,
            future_winner_entry_weight_cap=0.14,
            future_winner_drift_weight_cap=0.24,
            future_winner_hard_weight_cap=0.36,
            early_scout_entry_weight_cap=0.06,
            early_scout_drift_weight_cap=0.12,
            early_scout_hard_weight_cap=0.18,
            stock_weight_max=0.20,
            stock_weight_max_high_conviction=0.48,
            min_dynamic_port_names=10,
        ),
        candidate(
            "future_winner_tilt",
            "Multi-bagger sleeve leads in growth regimes; core remains a stabilizer.",
            core_compounder_sleeve_base_weight=0.20,
            future_winner_sleeve_base_weight=0.58,
            future_winner_sleeve_min_weight=0.12,
            future_winner_sleeve_max_weight=0.72,
            early_scout_sleeve_base_weight=0.18,
            early_scout_sleeve_min_weight=0.03,
            early_scout_sleeve_max_weight=0.30,
            early_scout_growth_floor_weight=0.14,
            future_winner_entry_weight_cap=0.15,
            future_winner_drift_weight_cap=0.30,
            future_winner_hard_weight_cap=0.42,
            early_scout_entry_weight_cap=0.06,
            early_scout_drift_weight_cap=0.13,
            early_scout_hard_weight_cap=0.20,
            stock_weight_max=0.20,
            stock_weight_max_high_conviction=0.50,
            min_dynamic_port_names=10,
        ),
        candidate(
            "future_early_barbell",
            "Reduce core materially and let future plus early share most of the invested risk budget.",
            core_compounder_sleeve_base_weight=0.10,
            future_winner_sleeve_base_weight=0.52,
            future_winner_sleeve_min_weight=0.14,
            future_winner_sleeve_max_weight=0.76,
            early_scout_sleeve_base_weight=0.28,
            early_scout_sleeve_min_weight=0.06,
            early_scout_sleeve_max_weight=0.42,
            early_scout_growth_floor_weight=0.18,
            early_scout_growth_floor_min_signal=0.30,
            early_scout_growth_floor_max_risk=0.55,
            future_winner_entry_weight_cap=0.15,
            future_winner_drift_weight_cap=0.28,
            future_winner_hard_weight_cap=0.40,
            early_scout_entry_weight_cap=0.08,
            early_scout_drift_weight_cap=0.18,
            early_scout_hard_weight_cap=0.28,
            sleeve_drift_headroom_pct=0.55,
            stock_weight_max=0.20,
            stock_weight_max_high_conviction=0.50,
            min_dynamic_port_names=9,
        ),
        candidate(
            "early_scout_bull",
            "Bull-market needle-finding policy; early scout can expand materially only when regime confirms.",
            core_compounder_sleeve_base_weight=0.15,
            future_winner_sleeve_base_weight=0.38,
            future_winner_sleeve_min_weight=0.08,
            future_winner_sleeve_max_weight=0.60,
            early_scout_sleeve_base_weight=0.30,
            early_scout_sleeve_min_weight=0.04,
            early_scout_sleeve_max_weight=0.42,
            early_scout_growth_floor_weight=0.20,
            early_scout_growth_floor_min_signal=0.32,
            early_scout_growth_floor_max_risk=0.48,
            future_winner_entry_weight_cap=0.14,
            future_winner_drift_weight_cap=0.28,
            future_winner_hard_weight_cap=0.40,
            early_scout_entry_weight_cap=0.08,
            early_scout_drift_weight_cap=0.18,
            early_scout_hard_weight_cap=0.28,
            sleeve_drift_headroom_pct=0.50,
            stock_weight_max=0.20,
            stock_weight_max_high_conviction=0.50,
            min_dynamic_port_names=9,
        ),
        candidate(
            "future_early_supercycle",
            "Most aggressive diversified growth mix short of a pure scout portfolio.",
            core_compounder_sleeve_base_weight=0.08,
            future_winner_sleeve_base_weight=0.47,
            future_winner_sleeve_min_weight=0.12,
            future_winner_sleeve_max_weight=0.72,
            early_scout_sleeve_base_weight=0.35,
            early_scout_sleeve_min_weight=0.08,
            early_scout_sleeve_max_weight=0.48,
            early_scout_growth_floor_weight=0.22,
            early_scout_growth_floor_min_signal=0.30,
            early_scout_growth_floor_max_risk=0.48,
            future_winner_entry_weight_cap=0.15,
            future_winner_drift_weight_cap=0.30,
            future_winner_hard_weight_cap=0.42,
            early_scout_entry_weight_cap=0.09,
            early_scout_drift_weight_cap=0.20,
            early_scout_hard_weight_cap=0.32,
            sleeve_drift_headroom_pct=0.65,
            stock_weight_max=0.22,
            stock_weight_max_high_conviction=0.50,
            min_dynamic_port_names=8,
        ),
        candidate(
            "early_scout_very_bull",
            "Most aggressive growth-thrust policy; early scout is large but capped per name.",
            core_compounder_sleeve_base_weight=0.10,
            future_winner_sleeve_base_weight=0.40,
            future_winner_sleeve_min_weight=0.08,
            future_winner_sleeve_max_weight=0.65,
            early_scout_sleeve_base_weight=0.50,
            early_scout_sleeve_min_weight=0.05,
            early_scout_sleeve_max_weight=0.55,
            early_scout_growth_floor_weight=0.20,
            early_scout_growth_floor_min_signal=0.32,
            early_scout_growth_floor_max_risk=0.45,
            future_winner_entry_weight_cap=0.16,
            future_winner_drift_weight_cap=0.32,
            future_winner_hard_weight_cap=0.45,
            early_scout_entry_weight_cap=0.10,
            early_scout_drift_weight_cap=0.22,
            early_scout_hard_weight_cap=0.36,
            sleeve_drift_headroom_pct=0.65,
            stock_weight_max=0.22,
            stock_weight_max_high_conviction=0.50,
            min_dynamic_port_names=8,
        ),
        candidate(
            "concentrated_leaders",
            "Let proven leaders run while keeping early scout smaller.",
            core_compounder_sleeve_base_weight=0.12,
            future_winner_sleeve_base_weight=0.65,
            future_winner_sleeve_min_weight=0.12,
            future_winner_sleeve_max_weight=0.75,
            early_scout_sleeve_base_weight=0.15,
            early_scout_sleeve_min_weight=0.03,
            early_scout_sleeve_max_weight=0.24,
            early_scout_growth_floor_weight=0.10,
            future_winner_entry_weight_cap=0.18,
            future_winner_drift_weight_cap=0.36,
            future_winner_hard_weight_cap=0.50,
            early_scout_entry_weight_cap=0.06,
            early_scout_drift_weight_cap=0.14,
            early_scout_hard_weight_cap=0.22,
            sleeve_drift_headroom_pct=0.75,
            stock_weight_max=0.22,
            stock_weight_max_high_conviction=0.50,
            min_dynamic_port_names=8,
        ),
        candidate(
            "risk_guarded_growth",
            "Growth tilt with wider mild-risk cash protection and moderate concentration.",
            core_compounder_sleeve_base_weight=0.40,
            future_winner_sleeve_base_weight=0.40,
            future_winner_sleeve_min_weight=0.10,
            future_winner_sleeve_max_weight=0.60,
            early_scout_sleeve_base_weight=0.15,
            early_scout_sleeve_min_weight=0.02,
            early_scout_sleeve_max_weight=0.24,
            early_scout_growth_floor_weight=0.12,
            future_winner_entry_weight_cap=0.11,
            future_winner_drift_weight_cap=0.22,
            future_winner_hard_weight_cap=0.34,
            early_scout_entry_weight_cap=0.05,
            early_scout_drift_weight_cap=0.10,
            early_scout_hard_weight_cap=0.16,
            stock_weight_max=0.16,
            stock_weight_max_high_conviction=0.40,
            cash_target_growth_cap=0.03,
            cash_target_balanced_cap=0.06,
            cash_target_mild_risk_cap=0.16,
            min_dynamic_port_names=12,
        ),
    ]


def holdings_concentration_metrics(holdings: pd.DataFrame) -> dict[str, float]:
    if holdings is None or holdings.empty or not {"rebalance_date", "ticker", "weight"}.issubset(holdings.columns):
        return {
            "avg_top_name_weight": np.nan,
            "max_top_name_weight": np.nan,
            "avg_hhi": np.nan,
            "max_hhi": np.nan,
        }
    d = holdings.copy()
    d["rebalance_date"] = pd.to_datetime(d["rebalance_date"], errors="coerce")
    d["weight"] = pd.to_numeric(d["weight"], errors="coerce").fillna(0.0)
    d = d[d["ticker"].astype(str).str.upper().ne(CASH_PROXY_TICKER)].dropna(subset=["rebalance_date"])
    if d.empty:
        return {
            "avg_top_name_weight": np.nan,
            "max_top_name_weight": np.nan,
            "avg_hhi": np.nan,
            "max_hhi": np.nan,
        }
    per_month = d.groupby("rebalance_date")["weight"].agg(
        top_name_weight="max",
        hhi=lambda x: float(np.square(pd.to_numeric(x, errors="coerce").fillna(0.0)).sum()),
    )
    return {
        "avg_top_name_weight": float(per_month["top_name_weight"].mean()),
        "max_top_name_weight": float(per_month["top_name_weight"].max()),
        "avg_hhi": float(per_month["hhi"].mean()),
        "max_hhi": float(per_month["hhi"].max()),
    }




def sleeve_cap_policy_objective(row: dict[str, Any], cfg: EngineConfig) -> float:
    strategy_cagr = safe_float(row.get("strategy_cagr"), 0.0)
    benchmark_cagr = safe_float(row.get("benchmark_cagr"), np.nan)
    excess_cagr = safe_float(row.get("excess_cagr"), np.nan)
    if not np.isfinite(excess_cagr):
        excess_cagr = strategy_cagr - benchmark_cagr if np.isfinite(benchmark_cagr) else strategy_cagr
    sharpe = safe_float(row.get("sharpe"), 0.0)
    sortino = safe_float(row.get("sortino"), 0.0)
    max_dd = min(safe_float(row.get("max_dd"), 0.0), 0.0)
    turnover = max(safe_float(row.get("avg_turnover_monthly"), 0.0), 0.0)
    avg_cash = max(safe_float(row.get("avg_cash_weight"), 0.0), 0.0)
    avg_top = max(safe_float(row.get("avg_top_name_weight"), 0.0), 0.0)
    avg_hhi = max(safe_float(row.get("avg_hhi"), 0.0), 0.0)
    concentration_penalty = max(0.0, avg_top - 0.22) + 0.50 * max(0.0, avg_hhi - 0.12)
    return float(
        float(cfg.sleeve_cap_policy_objective_excess_weight) * excess_cagr
        + float(cfg.sleeve_cap_policy_objective_sharpe_weight) * 0.05 * sharpe
        + float(cfg.sleeve_cap_policy_objective_sortino_weight) * 0.03 * sortino
        - float(cfg.sleeve_cap_policy_objective_drawdown_weight) * abs(max_dd)
        - float(cfg.sleeve_cap_policy_objective_turnover_weight) * turnover
        - float(cfg.sleeve_cap_policy_objective_concentration_weight) * concentration_penalty
        - float(cfg.sleeve_cap_policy_objective_cash_drag_weight) * avg_cash
    )


def compare_sleeve_cap_policy_backtests(
    cfg: dict | EngineConfig,
    signals: pd.DataFrame,
    candidates: Optional[Iterable[dict[str, Any]]] = None,
) -> pd.DataFrame:
    cfg_obj = to_cfg(cfg)
    raw_candidates = list(candidates) if candidates is not None else generate_sleeve_cap_policy_candidates(cfg_obj)
    max_candidates = max(int(getattr(cfg_obj, "sleeve_cap_policy_max_candidates", len(raw_candidates))), 1)
    rows: list[dict[str, Any]] = []
    backtests_by_policy: dict[str, BacktestResult] = {}
    for idx, policy in enumerate(raw_candidates[:max_candidates], start=1):
        name = str(policy.get("sleeve_cap_policy_name", f"candidate_{idx}"))
        updates = {field: policy[field] for field in SLEEVE_CAP_POLICY_FIELDS if field in policy}
        row: dict[str, Any] = {
            "sleeve_cap_policy_rank": int(idx),
            "sleeve_cap_policy_name": name,
            "sleeve_cap_policy_description": str(policy.get("sleeve_cap_policy_description", "")),
            **updates,
        }
        try:
            policy_cfg = clone_cfg_with_updates(cfg_obj, updates)
            validate_config(policy_cfg)
            bt = backtest_portfolio(policy_cfg, signals)
            row.update(_bt_metrics_row(bt, policy_cfg, portfolio_mode="dynamic", policy_mode="sleeve_cap_policy"))
            row.update(holdings_concentration_metrics(bt.holdings))
            backtests_by_policy[name] = bt
            row["policy_status"] = "ok"
            row["policy_error"] = ""
            row["sleeve_cap_policy_objective"] = sleeve_cap_policy_objective(row, cfg_obj)
        except Exception as exc:
            row["policy_status"] = "failed"
            row["policy_error"] = f"{type(exc).__name__}: {exc}"
            row["sleeve_cap_policy_objective"] = -np.inf
        rows.append(row)
    if not rows:
        return pd.DataFrame()
    out = pd.DataFrame(rows)
    out["_status_sort"] = np.where(out["policy_status"].astype(str).eq("ok"), 0, 1)
    out = out.sort_values(["_status_sort", "sleeve_cap_policy_objective"], ascending=[True, False]).drop(
        columns=["_status_sort"]
    )
    out["sleeve_cap_policy_rank"] = np.arange(1, len(out) + 1)
    out.attrs["backtests_by_policy"] = backtests_by_policy
    if bool(getattr(cfg_obj, "run_sleeve_regime_comparison", True)) or bool(
        getattr(cfg_obj, "sleeve_regime_apply_champion", True)
    ):
        ok = out[out["policy_status"].astype(str).eq("ok")].copy()
        if not ok.empty:
            champion_row = ok.sort_values("sleeve_cap_policy_objective", ascending=False).iloc[0].to_dict()
            champion_cfg = apply_sleeve_cap_policy_to_cfg(cfg_obj, champion_row)
            regime_cash_max = float(getattr(champion_cfg, "sleeve_regime_comparison_cash_max", 0.02))
            regime_grid, regime_best = compare_sleeve_policy_per_regime(
                champion_cfg,
                signals,
                cash_target_max=regime_cash_max,
            )
            regime_map = build_regime_conditioned_sleeve_map(regime_best)
            manual_regime_map = normalize_regime_conditioned_sleeve_map(
                getattr(champion_cfg, "manual_regime_conditioned_sleeve_map", {}) or default_manual_regime_conditioned_sleeve_map(),
                fallback_source="manual",
            )
            regime_method_compare = (
                compare_regime_conditioned_sleeve_map_methods(
                    champion_cfg,
                    signals,
                    learned_regime_map=regime_map,
                    manual_regime_map=manual_regime_map,
                    cash_target_max=regime_cash_max,
                )
                if bool(getattr(champion_cfg, "run_regime_map_method_comparison", True))
                else pd.DataFrame()
            )
            live_label = resolve_frame_regime_label(
                signals.loc[
                    pd.to_datetime(signals.get("rebalance_date"), errors="coerce")
                    == pd.to_datetime(signals.get("rebalance_date"), errors="coerce").max()
                ].copy()
                if isinstance(signals, pd.DataFrame) and "rebalance_date" in signals.columns
                else signals,
                default="balanced",
            )
            live_regime_policy, live_regime_meta = resolve_regime_policy_selection(
                live_label,
                learned_regime_map=regime_map,
                manual_regime_map=manual_regime_map,
            )
            out.attrs["sleeve_regime_grid"] = regime_grid
            out.attrs["sleeve_regime_best"] = regime_best
            out.attrs["regime_conditioned_sleeve_map"] = regime_map
            out.attrs["manual_regime_conditioned_sleeve_map"] = manual_regime_map
            out.attrs["regime_sleeve_method_compare"] = regime_method_compare
            out.attrs["live_regime_label"] = live_label
            out.attrs["live_regime_policy"] = dict(live_regime_policy or {})
            out.attrs["live_regime_policy_meta"] = live_regime_meta
    result = out.reset_index(drop=True)
    result.attrs = dict(out.attrs)
    return result


def _clean_json_scalar(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if not np.isfinite(float(value)) else float(value)
    if isinstance(value, float):
        return None if not np.isfinite(value) else float(value)
    if not isinstance(value, (dict, list, tuple, str)):
        try:
            if pd.isna(value):
                return None
        except Exception:
            pass
    return value


SLEEVE_REGIME_LABEL_COLUMNS: tuple[str, ...] = ("live_event_alert_label", "event_regime_label", "regime_label")


def resolve_frame_regime_label(frame: Optional[pd.DataFrame], default: str = "balanced") -> str:
    d = frame.copy() if isinstance(frame, pd.DataFrame) else pd.DataFrame()
    if d.empty:
        return str(default)
    for cand in SLEEVE_REGIME_LABEL_COLUMNS:
        if cand not in d.columns:
            continue
        mode = d[cand].dropna().astype(str).str.strip().replace("", np.nan).dropna().mode()
        if not mode.empty:
            return str(mode.iloc[0])
    return str(default)


def build_regime_conditioned_sleeve_map(best_df: Optional[pd.DataFrame]) -> dict[str, dict[str, Any]]:
    if best_df is None or best_df.empty:
        return {}
    out: dict[str, dict[str, Any]] = {}
    for _, row in best_df.iterrows():
        label = str(row.get("regime_label", "") or "").strip()
        if not label:
            continue
        core = max(safe_float(row.get("core_frac"), 0.0), 0.0)
        future = max(safe_float(row.get("future_frac"), 0.0), 0.0)
        early = max(safe_float(row.get("early_frac"), 0.0), 0.0)
        cash = float(np.clip(safe_float(row.get("cash_frac"), 0.0), 0.0, 1.0))
        total = core + future + early
        if total <= 1e-8:
            continue
        out[label] = {
            "core": float(core / total),
            "future": float(future / total),
            "early": float(early / total),
            "cash": cash,
            "policy_label": str(row.get("policy_label", "") or ""),
            "source_regime": label,
            "months": int(safe_float(row.get("months"), 0.0)),
            "regime_policy_objective": float(safe_float(row.get("regime_policy_objective"), np.nan)),
            "cagr": float(safe_float(row.get("cagr"), np.nan)),
            "sharpe": float(safe_float(row.get("sharpe"), np.nan)),
            "max_dd": float(safe_float(row.get("max_dd"), np.nan)),
        }
    return out


def normalize_regime_conditioned_sleeve_map(
    regime_map: Optional[dict[str, Any]],
    *,
    fallback_source: str = "",
) -> dict[str, dict[str, Any]]:
    raw_map = dict(regime_map or {})
    out: dict[str, dict[str, Any]] = {}
    for raw_label, raw_payload in raw_map.items():
        label = str(raw_label or "").strip()
        if not label or not isinstance(raw_payload, dict):
            continue
        core = max(safe_float(raw_payload.get("core"), 0.0), 0.0)
        future = max(safe_float(raw_payload.get("future"), 0.0), 0.0)
        early = max(safe_float(raw_payload.get("early"), 0.0), 0.0)
        cash = float(np.clip(safe_float(raw_payload.get("cash"), 0.0), 0.0, 1.0))
        total = core + future + early
        if total <= 1e-8:
            continue
        out[label] = {
            "core": float(core / total),
            "future": float(future / total),
            "early": float(early / total),
            "cash": cash,
            "policy_label": str(raw_payload.get("policy_label", "") or f"{fallback_source}_{label}").strip("_"),
            "source_regime": str(raw_payload.get("source_regime", label) or label),
            "months": int(safe_float(raw_payload.get("months"), 0.0)),
            "regime_policy_objective": float(safe_float(raw_payload.get("regime_policy_objective"), np.nan)),
            "cagr": float(safe_float(raw_payload.get("cagr"), np.nan)),
            "sharpe": float(safe_float(raw_payload.get("sharpe"), np.nan)),
            "max_dd": float(safe_float(raw_payload.get("max_dd"), np.nan)),
        }
    return out


REGIME_EXPLORATORY_GUARDRAILS: dict[str, dict[str, float]] = {
    "balanced": {"future_min": 0.18, "early_min": 0.08, "cash_max": 0.10},
    "growth_reentry": {"future_min": 0.24, "early_min": 0.12, "cash_max": 0.10},
    "growth_reentry_alert": {"future_min": 0.28, "early_min": 0.16, "cash_max": 0.10},
}


def apply_regime_policy_guardrails(
    live_label: Optional[str],
    selected_policy: Optional[dict[str, Any]],
) -> tuple[Optional[dict[str, Any]], dict[str, Any]]:
    if not isinstance(selected_policy, dict):
        return selected_policy, {"guardrail_applied": False}
    normalized_live_label = str(live_label or "").strip() or "balanced"
    source_label = str(selected_policy.get("source_regime", normalized_live_label) or normalized_live_label)
    guard = REGIME_EXPLORATORY_GUARDRAILS.get(source_label) or REGIME_EXPLORATORY_GUARDRAILS.get(normalized_live_label)
    if not isinstance(guard, dict):
        return dict(selected_policy), {"guardrail_applied": False}

    payload = dict(selected_policy)
    core = max(safe_float(payload.get("core"), 0.0), 0.0)
    future = max(safe_float(payload.get("future"), 0.0), 0.0)
    early = max(safe_float(payload.get("early"), 0.0), 0.0)
    cash = float(np.clip(safe_float(payload.get("cash"), 0.0), 0.0, 1.0))
    original = {"core": core, "future": future, "early": early, "cash": cash}

    future = max(future, float(guard.get("future_min", 0.0)))
    early = max(early, float(guard.get("early_min", 0.0)))
    cash = min(cash, float(guard.get("cash_max", 1.0)))
    invested_share = max(1.0 - cash, 0.0)
    exploratory_total = future + early
    if exploratory_total > invested_share and exploratory_total > 1e-8:
        scale = invested_share / exploratory_total
        future *= scale
        early *= scale
        core = 0.0
    else:
        core = max(invested_share - future - early, 0.0)

    updated = {
        "core": float(core),
        "future": float(future),
        "early": float(early),
        "cash": float(cash),
    }
    applied = any(abs(updated[k] - original[k]) > 1e-8 for k in updated)
    if applied:
        payload.update(updated)
        raw_policy_label = str(payload.get("policy_label", "") or "")
        if raw_policy_label and not raw_policy_label.endswith("_guardrailed"):
            payload["policy_label"] = f"{raw_policy_label}_guardrailed"
    return payload, {
        "guardrail_applied": bool(applied),
        "guardrail_label": source_label,
        "guardrail_reason": "exploratory_floor" if applied else "",
    }


def build_regime_label_lookup_chain(label: Optional[str]) -> list[str]:
    raw_label = str(label or "").strip() or "balanced"
    candidates: list[str] = [raw_label]
    if raw_label.endswith("_alert"):
        candidates.append(raw_label[: -len("_alert")])
    if raw_label.endswith("_shock"):
        candidates.append(raw_label.replace("_shock", "_alert"))
    if raw_label.endswith("_crisis"):
        candidates.append(raw_label.replace("_crisis", "_alert"))
    candidates.extend(REGIME_LABEL_NEAREST_FALLBACKS.get(raw_label, ()))
    candidates.extend(["balanced", "ALL"])
    out: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        normalized = str(candidate or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        out.append(normalized)
    return out or ["balanced", "ALL"]


def resolve_regime_policy_selection(
    live_label: Optional[str],
    *,
    learned_regime_map: Optional[dict[str, Any]] = None,
    manual_regime_map: Optional[dict[str, Any]] = None,
) -> tuple[Optional[dict[str, Any]], dict[str, Any]]:
    learned = normalize_regime_conditioned_sleeve_map(learned_regime_map, fallback_source="learned")
    manual = normalize_regime_conditioned_sleeve_map(manual_regime_map, fallback_source="manual")
    lookup_chain = build_regime_label_lookup_chain(live_label)
    normalized_live_label = str(live_label or "").strip() or "balanced"
    meta = {
        "live_regime_label": normalized_live_label,
        "lookup_chain": lookup_chain,
        "lookup_source": "",
        "lookup_label": "",
        "fallback_used": False,
    }
    for lookup_label in lookup_chain:
        for lookup_source, regime_map in (("learned", learned), ("manual", manual)):
            if not regime_map:
                continue
            selected = regime_map.get(lookup_label)
            if not isinstance(selected, dict):
                continue
            payload = dict(selected)
            payload.setdefault("source_regime", lookup_label)
            meta.update(
                {
                    "lookup_source": lookup_source,
                    "lookup_label": lookup_label,
                    "fallback_used": lookup_source != "learned" or lookup_label != normalized_live_label,
                }
            )
            return payload, meta
    return None, meta


def compare_regime_conditioned_sleeve_map_methods(
    cfg: dict | EngineConfig,
    signals: pd.DataFrame,
    *,
    learned_regime_map: Optional[dict[str, Any]] = None,
    manual_regime_map: Optional[dict[str, Any]] = None,
    cash_target_max: float = 0.02,
) -> pd.DataFrame:
    cfg_obj = to_cfg(cfg)
    latest_frame = (
        signals.loc[
            pd.to_datetime(signals.get("rebalance_date"), errors="coerce")
            == pd.to_datetime(signals.get("rebalance_date"), errors="coerce").max()
        ].copy()
        if isinstance(signals, pd.DataFrame) and "rebalance_date" in signals.columns
        else pd.DataFrame()
    )
    live_label = resolve_frame_regime_label(latest_frame, default="balanced")
    candidates = [
        ("learned_regime_map", normalize_regime_conditioned_sleeve_map(learned_regime_map, fallback_source="learned")),
        (
            "manual_forced_regime_map",
            normalize_regime_conditioned_sleeve_map(
                manual_regime_map or getattr(cfg_obj, "manual_regime_conditioned_sleeve_map", {}) or {},
                fallback_source="manual",
            ),
        ),
    ]
    rows: list[dict[str, Any]] = []
    for method_label, regime_map in candidates:
        if not regime_map:
            continue
        selected, lookup_meta = resolve_regime_policy_selection(
            live_label,
            learned_regime_map=regime_map if method_label == "learned_regime_map" else None,
            manual_regime_map=regime_map if method_label != "learned_regime_map" else None,
        )
        selected = dict(selected or {})
        policy_cfg = clone_cfg_with_updates(
            cfg_obj,
            {
                "regime_conditioned_sleeve_map": regime_map,
                "sleeve_regime_apply_champion": True,
            },
        )
        try:
            bt = backtest_portfolio(policy_cfg, signals, cash_target_max=cash_target_max)
            metrics = dict(bt.metrics or {})
            row = {
                "method_label": method_label,
                "comparison_status": "ok",
                "comparison_error": "",
                "live_regime_label": live_label,
                "selected_regime_label": str(selected.get("source_regime", live_label) or live_label),
                "lookup_source": str(lookup_meta.get("lookup_source", "") or ""),
                "lookup_label": str(lookup_meta.get("lookup_label", "") or ""),
                "fallback_used": bool(lookup_meta.get("fallback_used", False)),
                "live_policy_label": str(selected.get("policy_label", "") or ""),
                "live_core_frac": float(safe_float(selected.get("core"), np.nan)),
                "live_future_frac": float(safe_float(selected.get("future"), np.nan)),
                "live_early_frac": float(safe_float(selected.get("early"), np.nan)),
                "live_cash_frac": float(np.clip(safe_float(selected.get("cash"), 0.0), 0.0, 1.0)),
                "map_size": int(len(regime_map)),
                "cagr": float(safe_float(metrics.get("cagr"), np.nan)),
                "benchmark_cagr": float(safe_float(metrics.get("benchmark_cagr"), np.nan)),
                "excess_cagr": float(safe_float(metrics.get("excess_cagr"), np.nan)),
                "sharpe": float(safe_float(metrics.get("sharpe"), np.nan)),
                "sortino": float(safe_float(metrics.get("sortino"), np.nan)),
                "max_dd": float(safe_float(metrics.get("max_dd"), np.nan)),
                "ir": float(safe_float(metrics.get("ir"), np.nan)),
                "avg_turnover_monthly": float(safe_float(metrics.get("avg_turnover_monthly"), np.nan)),
                "avg_cash_weight": float(safe_float(metrics.get("avg_cash_weight"), np.nan)),
                "avg_stock_names": float(safe_float(metrics.get("avg_stock_names"), np.nan)),
                "rebalance_count": int(safe_float(metrics.get("rebalance_count"), 0.0)),
                "rebalanced_month_ratio": float(safe_float(metrics.get("rebalanced_month_ratio"), np.nan)),
                "months": int(safe_float(metrics.get("months"), 0.0)),
                "ending_capital_usd": float(safe_float(metrics.get("ending_capital_usd"), np.nan)),
                "regime_map_json": json.dumps(
                    {
                        str(k): {
                            "core": round(float(v.get("core", 0.0)), 4),
                            "future": round(float(v.get("future", 0.0)), 4),
                            "early": round(float(v.get("early", 0.0)), 4),
                            "cash": round(float(v.get("cash", 0.0)), 4),
                            "policy_label": str(v.get("policy_label", "") or ""),
                        }
                        for k, v in regime_map.items()
                    },
                    sort_keys=True,
                ),
            }
            row["comparison_objective"] = sleeve_regime_policy_objective(row)
        except Exception as exc:
            row = {
                "method_label": method_label,
                "comparison_status": "error",
                "comparison_error": str(exc),
                "live_regime_label": live_label,
                "selected_regime_label": str(selected.get("source_regime", live_label) or live_label),
                "lookup_source": str(lookup_meta.get("lookup_source", "") or ""),
                "lookup_label": str(lookup_meta.get("lookup_label", "") or ""),
                "fallback_used": bool(lookup_meta.get("fallback_used", False)),
                "live_policy_label": str(selected.get("policy_label", "") or ""),
                "live_core_frac": float(safe_float(selected.get("core"), np.nan)),
                "live_future_frac": float(safe_float(selected.get("future"), np.nan)),
                "live_early_frac": float(safe_float(selected.get("early"), np.nan)),
                "live_cash_frac": float(np.clip(safe_float(selected.get("cash"), 0.0), 0.0, 1.0)),
                "map_size": int(len(regime_map)),
                "cagr": np.nan,
                "benchmark_cagr": np.nan,
                "excess_cagr": np.nan,
                "sharpe": np.nan,
                "sortino": np.nan,
                "max_dd": np.nan,
                "ir": np.nan,
                "avg_turnover_monthly": np.nan,
                "avg_cash_weight": np.nan,
                "avg_stock_names": np.nan,
                "rebalance_count": 0,
                "rebalanced_month_ratio": np.nan,
                "months": 0,
                "ending_capital_usd": np.nan,
                "comparison_objective": -np.inf,
                "regime_map_json": json.dumps(
                    {
                        str(k): {
                            "core": round(float(v.get("core", 0.0)), 4),
                            "future": round(float(v.get("future", 0.0)), 4),
                            "early": round(float(v.get("early", 0.0)), 4),
                            "cash": round(float(v.get("cash", 0.0)), 4),
                            "policy_label": str(v.get("policy_label", "") or ""),
                        }
                        for k, v in regime_map.items()
                    },
                    sort_keys=True,
                ),
            }
        rows.append(row)
    if not rows:
        return pd.DataFrame()
    out = pd.DataFrame(rows)
    out["_status_sort"] = np.where(out["comparison_status"].astype(str).eq("ok"), 0, 1)
    out = out.sort_values(["_status_sort", "comparison_objective", "cagr"], ascending=[True, False, False]).drop(columns=["_status_sort"])
    out["comparison_rank"] = np.arange(1, len(out) + 1)
    return out.reset_index(drop=True)


# Stage 4b-ii (2026-04-20): resolve_regime_conditioned_sleeve_override -> r1000_signals.py.




def sleeve_regime_policy_objective(row: dict[str, Any]) -> float:
    cagr = safe_float(row.get("cagr"), np.nan)
    sharpe = safe_float(row.get("sharpe"), 0.0)
    sortino = safe_float(row.get("sortino"), 0.0)
    ir = safe_float(row.get("ir"), 0.0)
    max_dd = min(safe_float(row.get("max_dd"), 0.0), 0.0)
    if not np.isfinite(cagr):
        cagr = 0.0
    return float(
        1.35 * float(cagr)
        + 0.05 * float(sharpe)
        + 0.02 * float(sortino)
        + 0.02 * float(ir)
        - 0.35 * abs(float(max_dd))
    )


def choose_sleeve_cap_policy(policy_compare: Optional[pd.DataFrame]) -> dict[str, Any]:
    if policy_compare is None or policy_compare.empty or "policy_status" not in policy_compare.columns:
        return {}
    ok = policy_compare[policy_compare["policy_status"].astype(str).eq("ok")].copy()
    if ok.empty:
        return {}
    if "sleeve_cap_policy_objective" in ok.columns:
        ok = ok.sort_values("sleeve_cap_policy_objective", ascending=False)
    best = ok.iloc[0].to_dict()
    learned_regime_map = normalize_regime_conditioned_sleeve_map(
        dict((policy_compare.attrs or {}).get("regime_conditioned_sleeve_map", {}) or {}),
        fallback_source="learned",
    )
    manual_regime_map = normalize_regime_conditioned_sleeve_map(
        dict((policy_compare.attrs or {}).get("manual_regime_conditioned_sleeve_map", {}) or {}),
        fallback_source="manual",
    )
    regime_method_compare = (policy_compare.attrs or {}).get("regime_sleeve_method_compare")
    chosen_method_label = "learned_regime_map" if learned_regime_map else ""
    best_method_row: dict[str, Any] = {}
    if isinstance(regime_method_compare, pd.DataFrame) and not regime_method_compare.empty:
        best_method_row = regime_method_compare.iloc[0].to_dict()
        chosen_method_label = str(best_method_row.get("method_label", "") or chosen_method_label)
    chosen_regime_map = learned_regime_map
    if chosen_method_label == "manual_forced_regime_map" and manual_regime_map:
        chosen_regime_map = manual_regime_map
    elif not chosen_regime_map and manual_regime_map:
        chosen_regime_map = manual_regime_map
    if chosen_regime_map:
        best["regime_conditioned_sleeve_map"] = chosen_regime_map
        live_label = str(
            best_method_row.get(
                "live_regime_label",
                (policy_compare.attrs or {}).get("live_regime_label", "balanced"),
            )
            or "balanced"
        )
        best["live_regime_label"] = live_label
        live_regime_policy = dict(
            chosen_regime_map.get(live_label)
            or chosen_regime_map.get("balanced")
            or chosen_regime_map.get("ALL")
            or {}
        )
        if live_regime_policy:
            best["live_regime_sleeve_policy"] = {
                str(k): _clean_json_scalar(v) for k, v in live_regime_policy.items()
            }
    if chosen_method_label:
        best["regime_sleeve_map_method"] = chosen_method_label
    if best_method_row:
        for field in [
            "comparison_rank",
            "comparison_objective",
            "comparison_status",
            "live_policy_label",
            "selected_regime_label",
        ]:
            if field in best_method_row and best_method_row[field] is not None:
                best[f"regime_sleeve_map_{field}"] = _clean_json_scalar(best_method_row[field])
    return {str(k): _clean_json_scalar(v) for k, v in best.items() if not str(k).startswith("_")}


def apply_sleeve_cap_policy_to_cfg(cfg: dict | EngineConfig, selected_policy: dict[str, Any]) -> EngineConfig:
    updates = {
        field: selected_policy[field]
        for field in SLEEVE_CAP_POLICY_FIELDS
        if field in selected_policy and selected_policy[field] is not None
    }
    if "regime_conditioned_sleeve_map" in selected_policy and selected_policy["regime_conditioned_sleeve_map"] is not None:
        updates["regime_conditioned_sleeve_map"] = dict(selected_policy["regime_conditioned_sleeve_map"] or {})
    return clone_cfg_with_updates(cfg, updates)




SLEEVE_STANDALONE_LABELS: tuple[str, ...] = ("core_compounder", "future_winner", "early_scout")
SLEEVE_STANDALONE_ROLE_MAP: dict[str, str] = {
    "core_compounder": "core_compounder",
    "future_winner": "multi_bagger",
    "early_scout": "early_scout",
}
SLEEVE_STANDALONE_ENGINE_COL: dict[str, str] = {
    "core_compounder": "portfolio_core_compounder_engine_score",
    "future_winner": "portfolio_future_winner_engine_score",
    "early_scout": "portfolio_early_scout_engine_score",
}


def prepare_standalone_sleeve_frame(cfg: EngineConfig, frame: pd.DataFrame) -> pd.DataFrame:
    d = frame.copy()
    if d.empty:
        return d
    if "score" not in d.columns:
        if "score_total" in d.columns:
            d["score"] = pd.to_numeric(d["score_total"], errors="coerce").fillna(0.0)
        else:
            d["score"] = pd.Series(0.0, index=d.index, dtype=float)
    if "selection_confirmation_score" not in d.columns:
        d = compute_benchmark_beating_focus_overlay(d, cfg)
    if "minervini_momentum_alive_score" not in d.columns:
        d = compute_minervini_momentum_overlay(d)
    d = compute_portfolio_sleeve_columns(d, cfg)
    return d


def select_standalone_sleeve_topn(
    cfg: EngineConfig,
    month_df: pd.DataFrame,
    sleeve_label: str,
    top_n: int,
) -> pd.DataFrame:
    if month_df.empty or int(top_n) <= 0:
        return month_df.iloc[0:0].copy()
    if sleeve_label not in SLEEVE_STANDALONE_LABELS:
        raise ValueError(f"Unknown standalone sleeve label: {sleeve_label}")
    engine_col = SLEEVE_STANDALONE_ENGINE_COL[sleeve_label]
    d = prepare_standalone_sleeve_frame(cfg, month_df)
    if d.empty:
        return d
    labels = d.get("portfolio_sleeve_label", pd.Series("core_compounder", index=d.index, dtype=object)).fillna("core_compounder").astype(str)
    raw_labels = d.get("portfolio_sleeve_label_raw", labels).fillna(labels).astype(str)
    d["sleeve_standalone_score"] = row_mean(
        [
            cross_sectional_robust_z(d, "score"),
            1.25 * numeric_series_or_default(d, engine_col, 0.0),
            0.35 * cross_sectional_robust_z(d, "relative_strength_composite"),
            0.30 * numeric_series_or_default(d, "minervini_momentum_alive_score", 0.0),
            0.25 * numeric_series_or_default(d, "breakout_setup_quality_score", 0.0),
            -0.35 * numeric_series_or_default(d, "broken_momentum_penalty", 0.0),
        ],
        d.index,
    ).fillna(0.0)
    selected_parts: list[pd.DataFrame] = []
    selected_tickers: set[str] = set()

    def _take(mask: pd.Series, source: str, limit: int) -> None:
        nonlocal selected_tickers
        if limit <= 0:
            return
        mask = mask.reindex(d.index).fillna(False).astype(bool)
        pool = d.loc[mask].copy()
        if pool.empty:
            return
        if selected_tickers and "ticker" in pool.columns:
            pool = pool[~pool["ticker"].astype(str).isin(selected_tickers)].copy()
        if pool.empty:
            return
        pool = pool.sort_values(["sleeve_standalone_score", engine_col, "score"], ascending=False)
        pool = dedupe_same_company_rows(pool, score_col="sleeve_standalone_score").head(limit).copy()
        if pool.empty:
            return
        pool["sleeve_standalone_selection_source"] = source
        selected_parts.append(pool)
        if "ticker" in pool.columns:
            selected_tickers.update(pool["ticker"].astype(str).tolist())

    _take(labels.eq(sleeve_label), "final_label", int(top_n))
    remaining = int(top_n) - sum(len(x) for x in selected_parts)
    if remaining > 0:
        _take(raw_labels.eq(sleeve_label), "raw_label_fallback", remaining)
    remaining = int(top_n) - sum(len(x) for x in selected_parts)
    if remaining > 0:
        engine_series = numeric_series_or_default(d, engine_col, 0.0)
        engine_cut = float(engine_series.quantile(0.70)) if len(engine_series) else 0.0
        _take(engine_series >= engine_cut, "engine_score_fallback", remaining)
    if not selected_parts:
        return d.iloc[0:0].copy()
    out = pd.concat(selected_parts, ignore_index=False)
    out = dedupe_same_company_rows(out, score_col="sleeve_standalone_score").head(int(top_n)).copy()
    out["portfolio_sleeve_label"] = sleeve_label
    out["portfolio_sleeve_role"] = SLEEVE_STANDALONE_ROLE_MAP.get(sleeve_label, sleeve_label)
    return out


def backtest_standalone_sleeve_topn(
    cfg: dict | EngineConfig,
    signals: pd.DataFrame,
    sleeve_label: str,
    top_n: int = 7,
    rebalance_interval_months: int = 1,
) -> BacktestResult:
    cfg_obj = to_cfg(cfg)
    paths = get_paths(cfg_obj)
    top_n = max(int(top_n), 1)
    interval_months = max(int(rebalance_interval_months), 1)
    d = signals.copy()
    if "score" not in d.columns:
        if "score_total" in d.columns:
            d["score"] = pd.to_numeric(d["score_total"], errors="coerce").fillna(0.0)
        else:
            d["score"] = 0.0
    d["rebalance_date"] = pd.to_datetime(d["rebalance_date"], errors="coerce")
    d = d.dropna(subset=["rebalance_date"]).sort_values(["rebalance_date", "score"], ascending=[True, False]).reset_index(drop=True)
    months = sorted(pd.to_datetime(d["rebalance_date"].dropna().unique()).tolist())
    if len(months) < 2:
        raise RuntimeError("Need at least two months of OOS signals for standalone sleeve backtest.")

    cost_candidates = [
        safe_float(getattr(cfg_obj, "roundtrip_cost_bps", np.nan)),
        2.0 * safe_float(getattr(cfg_obj, "trade_cost_bps_per_side", 0.0)),
    ]
    cost_candidates = [float(x) for x in cost_candidates if np.isfinite(x)]
    effective_roundtrip_cost_bps = float(max(cost_candidates)) if cost_candidates else 0.0
    starting_capital_usd = float(max(safe_float(getattr(cfg_obj, "starting_capital_usd", 100000.0)), 1.0))

    current_w: dict[str, float] = {}
    current_portfolio = pd.DataFrame()
    next_scheduled_dt = pd.NaT
    rebalance_dates_taken: list[pd.Timestamp] = []
    holdings_rows: list[dict[str, Any]] = []
    ret_rows: list[dict[str, Any]] = []

    def _month_gap(later: pd.Timestamp, earlier: pd.Timestamp) -> int:
        return int((later.year - earlier.year) * 12 + (later.month - earlier.month))

    for i in range(len(months) - 1):
        dt = pd.Timestamp(months[i])
        next_dt = pd.Timestamp(months[i + 1])
        mm = d[d["rebalance_date"] == dt].copy()
        rebalance_due = (not current_w) or pd.isna(next_scheduled_dt) or (dt >= pd.Timestamp(next_scheduled_dt))
        turn = 0.0
        cost = 0.0
        rebalance_action = "scheduled_hold"

        if rebalance_due:
            prev_w = current_w.copy()
            sel = select_standalone_sleeve_topn(cfg_obj, mm, sleeve_label=sleeve_label, top_n=top_n)
            if not sel.empty:
                tickers = sel["ticker"].astype(str).tolist()
                equal_weight = 1.0 / max(len(tickers), 1)
                current_w = {str(t): float(equal_weight) for t in tickers}
                current_portfolio = sel.copy()
            else:
                current_w = {CASH_PROXY_TICKER: 1.0}
                current_portfolio = pd.DataFrame()
            turn = turnover(prev_w, current_w)
            cost = turn * (effective_roundtrip_cost_bps / 10000.0)
            rebalance_action = "initial_rebalance" if not prev_w else "rebalance"
            rebalance_dates_taken.append(dt)
            next_scheduled_dt = next_rebalance_date_for_interval(dt, interval_months=interval_months)

        if not current_w:
            current_w = {CASH_PROXY_TICKER: 1.0}

        holdings_source = current_portfolio if not current_portfolio.empty else mm
        month_holding_row_indices: list[int] = []
        for tkr, ww in current_w.items():
            row = holdings_source[holdings_source["ticker"].astype(str).eq(str(tkr))] if "ticker" in holdings_source.columns else pd.DataFrame()
            month_holding_row_indices.append(len(holdings_rows))
            holdings_rows.append(
                {
                    "rebalance_date": dt,
                    "ticker": tkr,
                    "Name": row["Name"].iloc[0] if not row.empty and "Name" in row.columns else ("Cash" if str(tkr).upper() == CASH_PROXY_TICKER else ""),
                    "sector": row["sector"].iloc[0] if not row.empty and "sector" in row.columns else ("Cash" if str(tkr).upper() == CASH_PROXY_TICKER else "Unknown"),
                    "weight": float(ww),
                    "raw_score": float(row["score"].iloc[0]) if not row.empty and "score" in row.columns else np.nan,
                    "portfolio_sleeve_label": "cash" if str(tkr).upper() == CASH_PROXY_TICKER else sleeve_label,
                    "portfolio_sleeve_role": "cash" if str(tkr).upper() == CASH_PROXY_TICKER else SLEEVE_STANDALONE_ROLE_MAP.get(sleeve_label, sleeve_label),
                    "sleeve_standalone_score": float(row["sleeve_standalone_score"].iloc[0]) if not row.empty and "sleeve_standalone_score" in row.columns else np.nan,
                    "sleeve_standalone_selection_source": str(row["sleeve_standalone_selection_source"].iloc[0]) if not row.empty and "sleeve_standalone_selection_source" in row.columns else "",
                    "period_forward_return": np.nan,
                    "weighted_forward_return": np.nan,
                    "target_n": int(top_n),
                    "rebalance_action": rebalance_action,
                    "active_rebalance_interval_months": int(interval_months),
                    "next_scheduled_rebalance_date": str(pd.Timestamp(next_scheduled_dt).date()) if pd.notna(next_scheduled_dt) else None,
                }
            )

        month_ret = 0.0
        missing = 0
        ticker_month_returns: dict[str, float] = {}
        for tkr, ww in current_w.items():
            ri = month_forward_return_open(paths, tkr, dt + pd.Timedelta(days=1), next_dt + pd.Timedelta(days=1))
            if ri is None:
                missing += 1
                continue
            month_ret += float(ww) * float(ri)
            ticker_month_returns[str(tkr)] = float(ri)
        for row_idx in month_holding_row_indices:
            held_ticker = str(holdings_rows[row_idx].get("ticker", ""))
            held_return = ticker_month_returns.get(held_ticker, 0.0 if held_ticker.upper() == CASH_PROXY_TICKER else np.nan)
            holdings_rows[row_idx]["period_forward_return"] = float(held_return) if pd.notna(held_return) else np.nan
            held_weight = float(holdings_rows[row_idx].get("weight", 0.0))
            holdings_rows[row_idx]["weighted_forward_return"] = held_weight * float(held_return) if pd.notna(held_return) else np.nan
        net_ret = month_ret - cost
        current_w = drift_weights_by_period_returns(current_w, ticker_month_returns)
        if current_w:
            total_w = float(sum(float(v) for v in current_w.values() if pd.notna(v)))
            if total_w > 0 and abs(total_w - 1.0) > 1e-8:
                current_w = {str(k): float(v / total_w) for k, v in current_w.items() if pd.notna(v) and float(v) > 1e-10}
        ret_rows.append(
            {
                "rebalance_date": dt,
                "next_rebalance_date": next_dt,
                "gross_return": float(month_ret),
                "cost": float(cost),
                "net_return": float(net_ret),
                "turnover": float(turn),
                "missing_tickers": int(missing),
                "cash_weight": float(current_w.get(CASH_PROXY_TICKER, 0.0)),
                "rebalance_action": rebalance_action,
                "active_rebalance_interval_months": int(interval_months),
                "next_scheduled_rebalance_date": str(pd.Timestamp(next_scheduled_dt).date()) if pd.notna(next_scheduled_dt) else None,
                "target_n": int(top_n),
                "portfolio_sleeve_label": str(sleeve_label),
                "portfolio_sleeve_role": SLEEVE_STANDALONE_ROLE_MAP.get(sleeve_label, sleeve_label),
            }
        )

    ret_df = pd.DataFrame(ret_rows)
    if ret_df.empty:
        raise RuntimeError("Standalone sleeve backtest produced no monthly returns.")
    ret_df["rebalance_date"] = pd.to_datetime(ret_df["rebalance_date"])
    ret_df = ret_df.sort_values("rebalance_date")
    ret_df["equity"] = (1.0 + ret_df["net_return"]).cumprod()
    ret_df["equity_value_usd"] = starting_capital_usd * ret_df["equity"]
    benchmark_close = load_benchmark_price_series(cfg_obj, paths)
    bench = []
    if not benchmark_close.empty:
        for r in ret_df.itertuples(index=False):
            rr = return_series_between_dates(
                benchmark_close,
                r.rebalance_date + pd.Timedelta(days=1),
                r.next_rebalance_date + pd.Timedelta(days=1),
            )
            bench.append(rr if rr is not None else np.nan)
    else:
        bench = [np.nan] * len(ret_df)
    ret_df["bench_return"] = bench
    metrics = performance_metrics(ret_df["net_return"], benchmark=ret_df["bench_return"])
    metrics["avg_turnover_monthly"] = float(ret_df["turnover"].mean())
    metrics["avg_cash_weight"] = float(ret_df["cash_weight"].mean()) if "cash_weight" in ret_df.columns else 0.0
    metrics["trade_cost_bps_per_side"] = float(effective_roundtrip_cost_bps / 2.0)
    metrics["cost_bps_roundtrip"] = float(effective_roundtrip_cost_bps)
    metrics["months"] = int(len(ret_df))
    metrics["target_n_override"] = int(top_n)
    metrics["rebalance_interval_months"] = int(interval_months)
    rebalance_intervals = (
        [_month_gap(later, earlier) for earlier, later in zip(rebalance_dates_taken[:-1], rebalance_dates_taken[1:])]
        if len(rebalance_dates_taken) >= 2
        else []
    )
    metrics["avg_rebalance_interval_months"] = float(np.mean(rebalance_intervals)) if rebalance_intervals else float(interval_months)
    metrics["adaptive_rebalance_policy"] = False
    metrics["rebalance_count"] = int(len(rebalance_dates_taken))
    metrics["rebalanced_month_ratio"] = float(len(rebalance_dates_taken) / max(len(ret_df), 1))
    metrics["benchmark_source"] = benchmark_history_source_label(cfg_obj)
    metrics["starting_capital_usd"] = starting_capital_usd
    if ret_df["bench_return"].notna().any():
        bench_eq = (1.0 + ret_df["bench_return"].fillna(0.0)).cumprod()
        ret_df["benchmark_equity"] = bench_eq
        ret_df["benchmark_value_usd"] = starting_capital_usd * bench_eq
        years = max(len(ret_df), 1) / 12.0
        metrics["benchmark_cagr"] = float(bench_eq.iloc[-1] ** (1.0 / years) - 1.0) if years > 0 else np.nan
        metrics["excess_cagr"] = float(metrics.get("cagr", np.nan) - metrics.get("benchmark_cagr", np.nan))
        metrics["beat_month_ratio"] = float((ret_df["net_return"] > ret_df["bench_return"]).mean())
        metrics["benchmark_ending_capital_usd"] = float(ret_df["benchmark_value_usd"].iloc[-1])
    else:
        metrics["benchmark_cagr"] = np.nan
        metrics["excess_cagr"] = np.nan
        metrics["beat_month_ratio"] = np.nan
        ret_df["benchmark_equity"] = np.nan
        ret_df["benchmark_value_usd"] = np.nan
        metrics["benchmark_ending_capital_usd"] = np.nan
    metrics["ending_capital_usd"] = float(ret_df["equity_value_usd"].iloc[-1])
    holdings_df = pd.DataFrame(holdings_rows)
    if not holdings_df.empty:
        stock_names = holdings_df[
            holdings_df["ticker"].astype(str).str.upper() != CASH_PROXY_TICKER
        ].groupby("rebalance_date")["ticker"].nunique()
        metrics["avg_stock_names"] = float(stock_names.mean()) if not stock_names.empty else 0.0
    else:
        metrics["avg_stock_names"] = 0.0
    # Base equity columns + any Phase 6a / 6c diagnostic columns that
    # were populated in ret_rows. `equity_curve.csv` downstream is the
    # only end-user view of these diagnostics; keep them if they exist
    # so the next run-verification step can inspect breaker activations
    # / vol-target floors without re-running the backtest.
    _equity_cols = [
        "rebalance_date",
        "equity",
        "equity_value_usd",
        "benchmark_equity",
        "benchmark_value_usd",
        "net_return",
        "bench_return",
    ]
    for _diag_col in (
        "drawdown_before_month",
        "drawdown_after_month",
        "equity_peak",
        "drawdown_circuit_breaker_active",
        "drawdown_circuit_breaker_event",
        "drawdown_circuit_breaker_cash_target",
        "dd_breaker_level",
        "dd_trigger_equity",
        "dd_breaker_multilevel_active",
        "vol_target_active",
        "vol_cash_floor_p6c",
        "recent_returns_len",
    ):
        if _diag_col in ret_df.columns and _diag_col not in _equity_cols:
            _equity_cols.append(_diag_col)
    equity_df = ret_df[_equity_cols].copy()
    return BacktestResult(holdings=holdings_df, monthly_returns=ret_df, metrics=metrics, equity_curve=equity_df)


def compare_standalone_sleeve_topn_backtests(
    cfg: dict | EngineConfig,
    signals: pd.DataFrame,
    top_n: Optional[int] = None,
    intervals: Optional[Iterable[int]] = None,
    active_backtest: Optional[BacktestResult] = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    cfg_obj = to_cfg(cfg)
    test_top_n = int(top_n if top_n is not None else getattr(cfg_obj, "standalone_sleeve_top_n", 7))
    candidates = intervals if intervals is not None else getattr(cfg_obj, "standalone_sleeve_rebalance_intervals", [1, 3])
    clean_intervals = sorted({int(x) for x in candidates if int(x) >= 1})
    rows: list[dict[str, Any]] = []
    monthly_frames: list[pd.DataFrame] = []
    holdings_frames: list[pd.DataFrame] = []
    log(
        f"Phase 5c: standalone sleeve top{test_top_n} backtests "
        f"(sleeves={','.join(SLEEVE_STANDALONE_LABELS)}, intervals={clean_intervals}) ..."
    )
    for sleeve in SLEEVE_STANDALONE_LABELS:
        for interval in clean_intervals:
            bt = backtest_standalone_sleeve_topn(
                cfg_obj,
                signals,
                sleeve_label=sleeve,
                top_n=test_top_n,
                rebalance_interval_months=int(interval),
            )
            rows.append(
                _bt_metrics_row(
                    bt,
                    cfg_obj,
                    portfolio_mode="standalone_sleeve_topn",
                    policy_mode="fixed_interval",
                    sleeve_test=str(sleeve),
                    sleeve_role=SLEEVE_STANDALONE_ROLE_MAP.get(sleeve, sleeve),
                    target_stock_names=int(test_top_n),
                    weighting_mode="equal_weight",
                    rebalance_interval_months=int(interval),
                )
            )
            m = bt.monthly_returns.copy()
            m["sleeve_test"] = str(sleeve)
            m["sleeve_role"] = SLEEVE_STANDALONE_ROLE_MAP.get(sleeve, sleeve)
            m["target_stock_names"] = int(test_top_n)
            m["policy_mode"] = "fixed_interval"
            monthly_frames.append(m)
            h = bt.holdings.copy()
            h["sleeve_test"] = str(sleeve)
            h["sleeve_role"] = SLEEVE_STANDALONE_ROLE_MAP.get(sleeve, sleeve)
            h["target_stock_names"] = int(test_top_n)
            h["policy_mode"] = "fixed_interval"
            holdings_frames.append(h)
    if active_backtest is not None:
        rows.append(
            _bt_metrics_row(
                active_backtest,
                cfg_obj,
                portfolio_mode="adaptive_three_sleeve",
                policy_mode="adaptive",
                sleeve_test="adaptive_three_sleeve",
                sleeve_role="adaptive_three_sleeve",
                target_stock_names=int(round(float(active_backtest.metrics.get("avg_stock_names", 0.0)))),
                weighting_mode="dynamic_score_invvol_caps",
            )
        )
    compare = pd.DataFrame(rows)
    if not compare.empty:
        compare = compare.sort_values(
            ["portfolio_mode", "sleeve_test", "rebalance_interval_months"],
            ascending=[True, True, True],
        ).reset_index(drop=True)
    monthly = pd.concat(monthly_frames, ignore_index=True) if monthly_frames else pd.DataFrame()
    holdings = pd.concat(holdings_frames, ignore_index=True) if holdings_frames else pd.DataFrame()
    return compare, monthly, holdings



def build_latest_standalone_sleeve_holdings(
    cfg: dict | EngineConfig,
    latest_frame: pd.DataFrame,
    standalone_compare: Optional[pd.DataFrame] = None,
    current_portfolio: Optional[pd.DataFrame] = None,
    top_n: Optional[int] = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    cfg_obj = to_cfg(cfg)
    d = latest_frame.copy() if isinstance(latest_frame, pd.DataFrame) else pd.DataFrame()
    if d.empty:
        return pd.DataFrame(), pd.DataFrame()
    d["rebalance_date"] = pd.to_datetime(d["rebalance_date"], errors="coerce")
    latest_dt = d["rebalance_date"].max()
    d = d[d["rebalance_date"] == latest_dt].copy()
    if d.empty:
        return pd.DataFrame(), pd.DataFrame()

    portfolio_weight_map: dict[str, float] = {}
    if isinstance(current_portfolio, pd.DataFrame) and not current_portfolio.empty and {"ticker", "weight"}.issubset(current_portfolio.columns):
        portfolio_weight_map = {
            normalize_ticker(tkr): float(w)
            for tkr, w in current_portfolio[["ticker", "weight"]].itertuples(index=False)
            if normalize_ticker(tkr)
        }

    compare_df = standalone_compare.copy() if isinstance(standalone_compare, pd.DataFrame) else pd.DataFrame()
    if not compare_df.empty and "portfolio_mode" in compare_df.columns:
        compare_df = compare_df[compare_df["portfolio_mode"].astype(str).eq("standalone_sleeve_topn")].copy()
    test_top_n = int(top_n if top_n is not None else getattr(cfg_obj, "standalone_sleeve_top_n", 7))
    selected_frames: list[pd.DataFrame] = []
    summary_rows: list[dict[str, Any]] = []

    for sleeve in SLEEVE_STANDALONE_LABELS:
        if not compare_df.empty and "sleeve_test" in compare_df.columns:
            sleeve_compare = compare_df.loc[
                compare_df["sleeve_test"].fillna("").astype(str).eq(str(sleeve))
            ].copy()
        else:
            sleeve_compare = pd.DataFrame()
        best_interval = int(getattr(cfg_obj, "rebalance_interval_months", 1))
        best_cagr = np.nan
        best_sharpe = np.nan
        best_max_dd = np.nan
        if not sleeve_compare.empty:
            ranked = sleeve_compare.sort_values(
                ["strategy_cagr", "sharpe", "rebalance_interval_months"],
                ascending=[False, False, True],
            ).reset_index(drop=True)
            best = ranked.iloc[0]
            best_interval = int(
                pd.to_numeric(
                    pd.Series([best.get("rebalance_interval_months", best_interval)]),
                    errors="coerce",
                ).fillna(best_interval).iloc[0]
            )
            best_cagr = safe_float(best.get("strategy_cagr"), np.nan)
            best_sharpe = safe_float(best.get("sharpe"), np.nan)
            best_max_dd = safe_float(best.get("max_dd"), np.nan)

        selected = select_standalone_sleeve_topn(cfg_obj, d, sleeve_label=sleeve, top_n=test_top_n)
        if selected.empty:
            summary_rows.append(
                {
                    "sleeve_test": str(sleeve),
                    "sleeve_role": SLEEVE_STANDALONE_ROLE_MAP.get(sleeve, sleeve),
                    "rebalance_date": str(pd.Timestamp(latest_dt).date()) if pd.notna(latest_dt) else None,
                    "target_stock_names": int(test_top_n),
                    "selected_names": 0,
                    "weighting_mode": "equal_weight",
                    "recommended_rebalance_interval_months": int(best_interval),
                    "strategy_cagr": float(best_cagr) if pd.notna(best_cagr) else np.nan,
                    "sharpe": float(best_sharpe) if pd.notna(best_sharpe) else np.nan,
                    "max_dd": float(best_max_dd) if pd.notna(best_max_dd) else np.nan,
                }
            )
            continue

        selected = selected.sort_values(["sleeve_standalone_score", "score"], ascending=[False, False]).reset_index(drop=True).copy()
        selected["rank"] = np.arange(1, len(selected) + 1)
        selected["standalone_weight"] = 1.0 / max(len(selected), 1)
        selected["weight"] = selected["standalone_weight"]
        selected["weighting_mode"] = "equal_weight"
        selected["target_stock_names"] = int(test_top_n)
        selected["recommended_rebalance_interval_months"] = int(best_interval)
        selected["standalone_strategy_cagr"] = float(best_cagr) if pd.notna(best_cagr) else np.nan
        selected["standalone_strategy_sharpe"] = float(best_sharpe) if pd.notna(best_sharpe) else np.nan
        selected["standalone_strategy_max_dd"] = float(best_max_dd) if pd.notna(best_max_dd) else np.nan
        selected["current_portfolio_weight"] = (
            selected.get("ticker", pd.Series(dtype=object))
            .astype(str)
            .map(lambda x: portfolio_weight_map.get(normalize_ticker(x), 0.0))
            .fillna(0.0)
        )
        selected["current_portfolio_selected"] = pd.to_numeric(selected["current_portfolio_weight"], errors="coerce").fillna(0.0) > 1e-10
        selected_frames.append(selected)

        summary_rows.append(
            {
                "sleeve_test": str(sleeve),
                "sleeve_role": SLEEVE_STANDALONE_ROLE_MAP.get(sleeve, sleeve),
                "rebalance_date": str(pd.Timestamp(latest_dt).date()) if pd.notna(latest_dt) else None,
                "target_stock_names": int(test_top_n),
                "selected_names": int(len(selected)),
                "weighting_mode": "equal_weight",
                "recommended_rebalance_interval_months": int(best_interval),
                "strategy_cagr": float(best_cagr) if pd.notna(best_cagr) else np.nan,
                "sharpe": float(best_sharpe) if pd.notna(best_sharpe) else np.nan,
                "max_dd": float(best_max_dd) if pd.notna(best_max_dd) else np.nan,
            }
        )

    holdings = pd.concat(selected_frames, ignore_index=True) if selected_frames else pd.DataFrame()
    summary = pd.DataFrame(summary_rows)
    return holdings, summary


def prepare_concentrated_frame(cfg: EngineConfig, frame: pd.DataFrame) -> pd.DataFrame:
    d = prepare_standalone_sleeve_frame(cfg, frame)
    if d.empty:
        return d
    labels = d.get("portfolio_sleeve_label", pd.Series("core_compounder", index=d.index, dtype=object)).fillna("core_compounder").astype(str)
    raw_labels = d.get("portfolio_sleeve_label_raw", labels).fillna(labels).astype(str)
    sleeve_bonus = labels.map(
        {
            "early_scout": 0.35,
            "future_winner": 0.20,
            "core_compounder": -0.15,
        }
    ).fillna(0.0)
    d["concentrated_preferred_sleeve"] = labels.isin(set(getattr(cfg, "concentrated_allowed_sleeves", ["future_winner", "early_scout"]))).astype(bool)
    d["concentrated_preferred_sleeve_raw"] = raw_labels.isin(set(getattr(cfg, "concentrated_allowed_sleeves", ["future_winner", "early_scout"]))).astype(bool)
    d["concentrated_score"] = row_mean(
        [
            cross_sectional_robust_z(d, "score"),
            float(getattr(cfg, "concentrated_score_future_weight", 0.95))
            * numeric_series_or_default(d, "portfolio_future_winner_engine_score", 0.0),
            float(getattr(cfg, "concentrated_score_early_weight", 1.05))
            * numeric_series_or_default(d, "portfolio_early_scout_engine_score", 0.0),
            float(getattr(cfg, "concentrated_score_sage_weight", 0.45))
            * numeric_series_or_default(d, "sage_composite_score", 0.0),
            float(getattr(cfg, "concentrated_score_confirmation_weight", 0.40))
            * numeric_series_or_default(d, "selection_confirmation_score", 0.0),
            float(getattr(cfg, "concentrated_score_breakout_weight", 0.30))
            * numeric_series_or_default(d, "breakout_setup_quality_score", 0.0),
            float(getattr(cfg, "concentrated_score_momentum_weight", 0.35))
            * cross_sectional_robust_z(d, "relative_strength_composite"),
            0.25 * numeric_series_or_default(d, "score_future_winner_model", 0.0),
            0.20 * numeric_series_or_default(d, "future_winner_scout_score", 0.0),
            -float(getattr(cfg, "concentrated_score_exit_risk_penalty", 0.40))
            * numeric_series_or_default(d, "portfolio_hold_policy_exit_risk", 0.0),
            -0.20 * numeric_series_or_default(d, "broken_momentum_penalty", 0.0),
        ],
        d.index,
    ).fillna(0.0) + pd.to_numeric(sleeve_bonus, errors="coerce").fillna(0.0)
    return d


def select_concentrated_portfolio_topk(
    cfg: EngineConfig,
    month_df: pd.DataFrame,
    top_n: int,
) -> pd.DataFrame:
    if month_df.empty or int(top_n) <= 0:
        return month_df.iloc[0:0].copy()
    d = prepare_concentrated_frame(cfg, month_df)
    if d.empty:
        return d
    # Phase 9 CE v2 (2026-04-18): inner clamp 3 -> 30. First CE commit
    # f93a4a2 lifted 3 OUTER clamps but missed this one; result was N=3..10
    # producing identical metrics because the grid was silently clamping
    # back to 3 here. See CHANGELOG 19:30 KST entry.
    top_n = max(1, min(int(top_n), 30))
    min_confirmation = float(getattr(cfg, "concentrated_min_confirmation", 0.45))
    selected_parts: list[pd.DataFrame] = []
    selected_tickers: set[str] = set()

    def _take(mask: pd.Series, source: str, limit: int) -> None:
        nonlocal selected_tickers
        if limit <= 0:
            return
        mask = mask.reindex(d.index).fillna(False).astype(bool)
        pool = d.loc[mask].copy()
        if pool.empty:
            return
        if selected_tickers and "ticker" in pool.columns:
            pool = pool[~pool["ticker"].astype(str).isin(selected_tickers)].copy()
        if pool.empty:
            return
        pool = pool.loc[
            pd.to_numeric(pool.get("selection_confirmation_score"), errors="coerce").fillna(0.0) >= min_confirmation
        ].copy()
        if pool.empty:
            return
        pool = pool.sort_values(
            ["concentrated_score", "selection_confirmation_score", "score"],
            ascending=False,
        )
        pool = dedupe_same_company_rows(pool, score_col="concentrated_score").head(limit).copy()
        if pool.empty:
            return
        pool["concentrated_selection_source"] = source
        selected_parts.append(pool)
        if "ticker" in pool.columns:
            selected_tickers.update(pool["ticker"].astype(str).tolist())

    _take(pd.Series(d["concentrated_preferred_sleeve"], index=d.index), "preferred_final_label", top_n)
    remaining = top_n - sum(len(x) for x in selected_parts)
    if remaining > 0:
        _take(pd.Series(d["concentrated_preferred_sleeve_raw"], index=d.index), "preferred_raw_label", remaining)
    remaining = top_n - sum(len(x) for x in selected_parts)
    if remaining > 0:
        score_cut = float(pd.to_numeric(d["concentrated_score"], errors="coerce").quantile(0.80)) if len(d) else 0.0
        _take(pd.to_numeric(d["concentrated_score"], errors="coerce").fillna(0.0) >= score_cut, "score_fallback", remaining)
    if not selected_parts:
        return d.iloc[0:0].copy()
    out = pd.concat(selected_parts, ignore_index=False)
    out = dedupe_same_company_rows(out, score_col="concentrated_score").head(top_n).copy()
    out["concentrated_target_n"] = int(top_n)
    return out


def concentrated_weight_map(
    cfg: EngineConfig,
    selected: pd.DataFrame,
    weighting_mode: str,
) -> dict[str, float]:
    if selected.empty or "ticker" not in selected.columns:
        return {}
    mode = str(weighting_mode or "conviction_curve").strip() or "conviction_curve"
    ranked = selected.sort_values(["concentrated_score", "score"], ascending=False).reset_index(drop=True).copy()
    tickers = ranked["ticker"].astype(str).tolist()
    n = len(tickers)
    if n <= 0:
        return {}
    if mode == "winner_take_all":
        weights = np.zeros(n, dtype=float)
        weights[0] = 1.0
    elif mode == "score_power":
        raw = pd.to_numeric(ranked.get("concentrated_score"), errors="coerce").fillna(0.0)
        shifted = (raw - float(raw.min()) + 0.25).clip(lower=1e-6)
        weights = normalize_with_limits(
            pd.Series(np.power(shifted.to_numpy(dtype=float), 2.0), index=ranked.index, dtype=float),
            wmin=0.0,
            wmax=float(getattr(cfg, "concentrated_max_single_name_weight", 1.0)),
        ).to_numpy(dtype=float)
    else:
        curve = {
            1: np.array([1.0], dtype=float),
            2: np.array([0.70, 0.30], dtype=float),
            3: np.array([0.50, 0.30, 0.20], dtype=float),
        }
        weights = curve.get(n, curve[3][:n]).astype(float)
        weights = weights / max(float(weights.sum()), 1e-8)
    out = {
        str(t): float(w)
        for t, w in zip(tickers, weights.tolist())
        if pd.notna(w) and float(w) > 1e-10
    }
    total = float(sum(out.values()))
    if total > 0:
        out = {k: float(v / total) for k, v in out.items()}
    return out


def backtest_concentrated_portfolio(
    cfg: dict | EngineConfig,
    signals: pd.DataFrame,
    *,
    top_n: int = 3,
    rebalance_interval_months: int = 1,
    weighting_mode: str = "conviction_curve",
) -> BacktestResult:
    cfg_obj = to_cfg(cfg)
    paths = get_paths(cfg_obj)
    # Phase 9 CE v2 (2026-04-18): inner clamp 3 -> 30 (second missed site).
    # Without this lift, every grid point with top_n>3 reports the N=3 backtest.
    top_n = max(1, min(int(top_n), 30))
    interval_months = max(int(rebalance_interval_months), 1)
    d = signals.copy()
    if "score" not in d.columns:
        if "score_total" in d.columns:
            d["score"] = pd.to_numeric(d["score_total"], errors="coerce").fillna(0.0)
        else:
            d["score"] = 0.0
    d["rebalance_date"] = pd.to_datetime(d["rebalance_date"], errors="coerce")
    d = d.dropna(subset=["rebalance_date"]).sort_values(["rebalance_date", "score"], ascending=[True, False]).reset_index(drop=True)
    months = sorted(pd.to_datetime(d["rebalance_date"].dropna().unique()).tolist())
    if len(months) < 2:
        raise RuntimeError("Need at least two months of OOS signals for concentrated backtest.")

    cost_candidates = [
        safe_float(getattr(cfg_obj, "roundtrip_cost_bps", np.nan)),
        2.0 * safe_float(getattr(cfg_obj, "trade_cost_bps_per_side", 0.0)),
    ]
    cost_candidates = [float(x) for x in cost_candidates if np.isfinite(x)]
    effective_roundtrip_cost_bps = float(max(cost_candidates)) if cost_candidates else 0.0
    starting_capital_usd = float(max(safe_float(getattr(cfg_obj, "starting_capital_usd", 100000.0)), 1.0))

    current_w: dict[str, float] = {}
    current_portfolio = pd.DataFrame()
    next_scheduled_dt = pd.NaT
    rebalance_dates_taken: list[pd.Timestamp] = []
    holdings_rows: list[dict[str, Any]] = []
    ret_rows: list[dict[str, Any]] = []

    def _month_gap(later: pd.Timestamp, earlier: pd.Timestamp) -> int:
        return int((later.year - earlier.year) * 12 + (later.month - earlier.month))

    for i in range(len(months) - 1):
        dt = pd.Timestamp(months[i])
        next_dt = pd.Timestamp(months[i + 1])
        mm = d[d["rebalance_date"] == dt].copy()
        rebalance_due = (not current_w) or pd.isna(next_scheduled_dt) or (dt >= pd.Timestamp(next_scheduled_dt))
        turn = 0.0
        cost = 0.0
        rebalance_action = "scheduled_hold"

        if rebalance_due:
            prev_w = current_w.copy()
            sel = select_concentrated_portfolio_topk(cfg_obj, mm, top_n=top_n)
            if not sel.empty:
                current_w = concentrated_weight_map(cfg_obj, sel, weighting_mode=weighting_mode)
                current_portfolio = sel.copy()
            else:
                current_w = {CASH_PROXY_TICKER: 1.0}
                current_portfolio = pd.DataFrame()
            turn = turnover(prev_w, current_w)
            cost = turn * (effective_roundtrip_cost_bps / 10000.0)
            rebalance_action = "initial_rebalance" if not prev_w else "rebalance"
            rebalance_dates_taken.append(dt)
            next_scheduled_dt = next_rebalance_date_for_interval(dt, interval_months=interval_months)

        if not current_w:
            current_w = {CASH_PROXY_TICKER: 1.0}

        holdings_source = current_portfolio if not current_portfolio.empty else mm
        month_holding_row_indices: list[int] = []
        for tkr, ww in current_w.items():
            row = holdings_source[holdings_source["ticker"].astype(str).eq(str(tkr))] if "ticker" in holdings_source.columns else pd.DataFrame()
            month_holding_row_indices.append(len(holdings_rows))
            holdings_rows.append(
                {
                    "rebalance_date": dt,
                    "ticker": tkr,
                    "Name": row["Name"].iloc[0] if not row.empty and "Name" in row.columns else ("Cash" if str(tkr).upper() == CASH_PROXY_TICKER else ""),
                    "sector": row["sector"].iloc[0] if not row.empty and "sector" in row.columns else ("Cash" if str(tkr).upper() == CASH_PROXY_TICKER else "Unknown"),
                    "weight": float(ww),
                    "raw_score": float(row["score"].iloc[0]) if not row.empty and "score" in row.columns else np.nan,
                    "concentrated_score": float(row["concentrated_score"].iloc[0]) if not row.empty and "concentrated_score" in row.columns else np.nan,
                    "portfolio_sleeve_label": "cash" if str(tkr).upper() == CASH_PROXY_TICKER else str(row["portfolio_sleeve_label"].iloc[0]) if not row.empty and "portfolio_sleeve_label" in row.columns else "unknown",
                    "concentrated_selection_source": str(row["concentrated_selection_source"].iloc[0]) if not row.empty and "concentrated_selection_source" in row.columns else "",
                    "period_forward_return": np.nan,
                    "weighted_forward_return": np.nan,
                    "target_n": int(top_n),
                    "weighting_mode": str(weighting_mode),
                    "rebalance_action": rebalance_action,
                    "active_rebalance_interval_months": int(interval_months),
                    "next_scheduled_rebalance_date": str(pd.Timestamp(next_scheduled_dt).date()) if pd.notna(next_scheduled_dt) else None,
                }
            )

        month_ret = 0.0
        missing = 0
        ticker_month_returns: dict[str, float] = {}
        for tkr, ww in current_w.items():
            ri = month_forward_return_open(paths, tkr, dt + pd.Timedelta(days=1), next_dt + pd.Timedelta(days=1))
            if ri is None:
                missing += 1
                continue
            month_ret += float(ww) * float(ri)
            ticker_month_returns[str(tkr)] = float(ri)
        for row_idx in month_holding_row_indices:
            held_ticker = str(holdings_rows[row_idx].get("ticker", ""))
            held_return = ticker_month_returns.get(held_ticker, 0.0 if held_ticker.upper() == CASH_PROXY_TICKER else np.nan)
            holdings_rows[row_idx]["period_forward_return"] = float(held_return) if pd.notna(held_return) else np.nan
            held_weight = float(holdings_rows[row_idx].get("weight", 0.0))
            holdings_rows[row_idx]["weighted_forward_return"] = held_weight * float(held_return) if pd.notna(held_return) else np.nan
        net_ret = month_ret - cost
        current_w = drift_weights_by_period_returns(current_w, ticker_month_returns)
        if current_w:
            total_w = float(sum(float(v) for v in current_w.values() if pd.notna(v)))
            if total_w > 0 and abs(total_w - 1.0) > 1e-8:
                current_w = {str(k): float(v / total_w) for k, v in current_w.items() if pd.notna(v) and float(v) > 1e-10}
        ret_rows.append(
            {
                "rebalance_date": dt,
                "next_rebalance_date": next_dt,
                "gross_return": float(month_ret),
                "cost": float(cost),
                "net_return": float(net_ret),
                "turnover": float(turn),
                "missing_tickers": int(missing),
                "cash_weight": float(current_w.get(CASH_PROXY_TICKER, 0.0)),
                "rebalance_action": rebalance_action,
                "active_rebalance_interval_months": int(interval_months),
                "next_scheduled_rebalance_date": str(pd.Timestamp(next_scheduled_dt).date()) if pd.notna(next_scheduled_dt) else None,
                "target_n": int(top_n),
                "weighting_mode": str(weighting_mode),
                "portfolio_mode": "concentrated_alpha",
            }
        )

    ret_df = pd.DataFrame(ret_rows)
    if ret_df.empty:
        raise RuntimeError("Concentrated backtest produced no monthly returns.")
    ret_df["rebalance_date"] = pd.to_datetime(ret_df["rebalance_date"])
    ret_df = ret_df.sort_values("rebalance_date")
    ret_df["equity"] = (1.0 + ret_df["net_return"]).cumprod()
    ret_df["equity_value_usd"] = starting_capital_usd * ret_df["equity"]
    benchmark_close = load_benchmark_price_series(cfg_obj, paths)
    bench = []
    if not benchmark_close.empty:
        for r in ret_df.itertuples(index=False):
            rr = return_series_between_dates(
                benchmark_close,
                r.rebalance_date + pd.Timedelta(days=1),
                r.next_rebalance_date + pd.Timedelta(days=1),
            )
            bench.append(rr if rr is not None else np.nan)
    else:
        bench = [np.nan] * len(ret_df)
    ret_df["bench_return"] = bench
    metrics = performance_metrics(ret_df["net_return"], benchmark=ret_df["bench_return"])
    metrics["portfolio_mode"] = "concentrated_alpha"
    metrics["avg_turnover_monthly"] = float(ret_df["turnover"].mean())
    metrics["avg_cash_weight"] = float(ret_df["cash_weight"].mean()) if "cash_weight" in ret_df.columns else 0.0
    metrics["trade_cost_bps_per_side"] = float(effective_roundtrip_cost_bps / 2.0)
    metrics["cost_bps_roundtrip"] = float(effective_roundtrip_cost_bps)
    metrics["months"] = int(len(ret_df))
    metrics["target_n_override"] = int(top_n)
    metrics["weighting_mode"] = str(weighting_mode)
    metrics["rebalance_interval_months"] = int(interval_months)
    rebalance_intervals = (
        [_month_gap(later, earlier) for earlier, later in zip(rebalance_dates_taken[:-1], rebalance_dates_taken[1:])]
        if len(rebalance_dates_taken) >= 2
        else []
    )
    metrics["avg_rebalance_interval_months"] = float(np.mean(rebalance_intervals)) if rebalance_intervals else float(interval_months)
    metrics["adaptive_rebalance_policy"] = False
    metrics["rebalance_count"] = int(len(rebalance_dates_taken))
    metrics["rebalanced_month_ratio"] = float(len(rebalance_dates_taken) / max(len(ret_df), 1))
    metrics["benchmark_source"] = benchmark_history_source_label(cfg_obj)
    metrics["starting_capital_usd"] = starting_capital_usd
    if ret_df["bench_return"].notna().any():
        bench_eq = (1.0 + ret_df["bench_return"].fillna(0.0)).cumprod()
        ret_df["benchmark_equity"] = bench_eq
        ret_df["benchmark_value_usd"] = starting_capital_usd * bench_eq
        years = max(len(ret_df), 1) / 12.0
        metrics["benchmark_cagr"] = float(bench_eq.iloc[-1] ** (1.0 / years) - 1.0) if years > 0 else np.nan
        metrics["excess_cagr"] = float(metrics.get("cagr", np.nan) - metrics.get("benchmark_cagr", np.nan))
        metrics["beat_month_ratio"] = float((ret_df["net_return"] > ret_df["bench_return"]).mean())
        metrics["benchmark_ending_capital_usd"] = float(ret_df["benchmark_value_usd"].iloc[-1])
    else:
        metrics["benchmark_cagr"] = np.nan
        metrics["excess_cagr"] = np.nan
        metrics["beat_month_ratio"] = np.nan
        ret_df["benchmark_equity"] = np.nan
        ret_df["benchmark_value_usd"] = np.nan
        metrics["benchmark_ending_capital_usd"] = np.nan
    metrics["ending_capital_usd"] = float(ret_df["equity_value_usd"].iloc[-1])
    holdings_df = pd.DataFrame(holdings_rows)
    if not holdings_df.empty:
        stock_names = holdings_df[
            holdings_df["ticker"].astype(str).str.upper() != CASH_PROXY_TICKER
        ].groupby("rebalance_date")["ticker"].nunique()
        metrics["avg_stock_names"] = float(stock_names.mean()) if not stock_names.empty else 0.0
        metrics["max_top_name_weight"] = float(
            holdings_df[holdings_df["ticker"].astype(str).str.upper() != CASH_PROXY_TICKER]
            .groupby("rebalance_date")["weight"]
            .max()
            .max()
        ) if not stock_names.empty else 0.0
    else:
        metrics["avg_stock_names"] = 0.0
        metrics["max_top_name_weight"] = 0.0
    # Base equity columns + any Phase 6a / 6c diagnostic columns that
    # were populated in ret_rows. `equity_curve.csv` downstream is the
    # only end-user view of these diagnostics; keep them if they exist
    # so the next run-verification step can inspect breaker activations
    # / vol-target floors without re-running the backtest.
    _equity_cols = [
        "rebalance_date",
        "equity",
        "equity_value_usd",
        "benchmark_equity",
        "benchmark_value_usd",
        "net_return",
        "bench_return",
    ]
    for _diag_col in (
        "drawdown_before_month",
        "drawdown_after_month",
        "equity_peak",
        "drawdown_circuit_breaker_active",
        "drawdown_circuit_breaker_event",
        "drawdown_circuit_breaker_cash_target",
        "dd_breaker_level",
        "dd_trigger_equity",
        "dd_breaker_multilevel_active",
        "vol_target_active",
        "vol_cash_floor_p6c",
        "recent_returns_len",
    ):
        if _diag_col in ret_df.columns and _diag_col not in _equity_cols:
            _equity_cols.append(_diag_col)
    equity_df = ret_df[_equity_cols].copy()
    return BacktestResult(holdings=holdings_df, monthly_returns=ret_df, metrics=metrics, equity_curve=equity_df)


def concentrated_strategy_objective(row: Mapping[str, Any]) -> float:
    cagr = safe_float(row.get("strategy_cagr"), np.nan)
    sharpe = safe_float(row.get("sharpe"), 0.0)
    max_dd = min(safe_float(row.get("max_dd"), 0.0), 0.0)
    beat_ratio = safe_float(row.get("beat_month_ratio"), 0.0)
    if not np.isfinite(cagr):
        cagr = 0.0
    return float(1.10 * cagr + 0.08 * sharpe + 0.04 * beat_ratio - 0.45 * abs(max_dd))


def compare_concentrated_portfolio_backtests(
    cfg: dict | EngineConfig,
    signals: pd.DataFrame,
    *,
    top_n_candidates: Optional[Iterable[int]] = None,
    intervals: Optional[Iterable[int]] = None,
    weighting_modes: Optional[Iterable[str]] = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    cfg_obj = to_cfg(cfg)
    # Phase 9 CE: upper bound 3 -> 30 so the grid can explore concentrated
    # ladders wider than N=3. The EngineConfig validator already gates
    # user-visible values to [1, 30]; this guard is final defensive clamp.
    clean_top_n = sorted({max(1, min(int(x), 30)) for x in (top_n_candidates if top_n_candidates is not None else getattr(cfg_obj, "concentrated_top_n_candidates", [1, 2, 3, 4, 5, 7, 10]))})
    clean_intervals = sorted({max(1, int(x)) for x in (intervals if intervals is not None else getattr(cfg_obj, "concentrated_rebalance_intervals", [1]))})
    clean_modes = [str(x) for x in (weighting_modes if weighting_modes is not None else getattr(cfg_obj, "concentrated_weighting_modes", ["conviction_curve", "winner_take_all"])) if str(x)]
    rows: list[dict[str, Any]] = []
    monthly_frames: list[pd.DataFrame] = []
    holdings_frames: list[pd.DataFrame] = []
    log(
        f"Phase 5e: concentrated alpha backtests (top_n={clean_top_n}, intervals={clean_intervals}, modes={clean_modes}) ..."
    )
    for top_n in clean_top_n:
        for interval in clean_intervals:
            for mode in clean_modes:
                bt = backtest_concentrated_portfolio(
                    cfg_obj,
                    signals,
                    top_n=int(top_n),
                    rebalance_interval_months=int(interval),
                    weighting_mode=str(mode),
                )
                row = _bt_metrics_row(
                    bt,
                    cfg_obj,
                    portfolio_mode="concentrated_alpha",
                    policy_mode="fixed_interval",
                    sleeve_test="future_early_concentrated",
                    sleeve_role="concentrated_alpha",
                    target_stock_names=int(top_n),
                    weighting_mode=str(mode),
                    rebalance_interval_months=int(interval),
                )
                row["comparison_objective"] = concentrated_strategy_objective(row)
                rows.append(row)
                m = bt.monthly_returns.copy()
                m["target_stock_names"] = int(top_n)
                m["weighting_mode"] = str(mode)
                m["portfolio_mode"] = "concentrated_alpha"
                monthly_frames.append(m)
                h = bt.holdings.copy()
                h["target_stock_names"] = int(top_n)
                h["weighting_mode"] = str(mode)
                h["portfolio_mode"] = "concentrated_alpha"
                holdings_frames.append(h)
    compare = pd.DataFrame(rows)
    if not compare.empty:
        compare = compare.sort_values(
            ["comparison_objective", "strategy_cagr", "sharpe"],
            ascending=[False, False, False],
        ).reset_index(drop=True)
    monthly = pd.concat(monthly_frames, ignore_index=True) if monthly_frames else pd.DataFrame()
    holdings = pd.concat(holdings_frames, ignore_index=True) if holdings_frames else pd.DataFrame()
    return compare, monthly, holdings


def build_latest_concentrated_holdings(
    cfg: dict | EngineConfig,
    latest_frame: pd.DataFrame,
    concentrated_compare: Optional[pd.DataFrame] = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    cfg_obj = to_cfg(cfg)
    d = latest_frame.copy() if isinstance(latest_frame, pd.DataFrame) else pd.DataFrame()
    if d.empty:
        return pd.DataFrame(), {}
    d["rebalance_date"] = pd.to_datetime(d["rebalance_date"], errors="coerce")
    latest_dt = d["rebalance_date"].max()
    d = d[d["rebalance_date"] == latest_dt].copy()
    if d.empty:
        return pd.DataFrame(), {}

    compare_df = concentrated_compare.copy() if isinstance(concentrated_compare, pd.DataFrame) else pd.DataFrame()
    if not compare_df.empty and "portfolio_mode" in compare_df.columns:
        compare_df = compare_df[compare_df["portfolio_mode"].astype(str).eq("concentrated_alpha")].copy()
    # Phase 9 CE: latest-holdings picker clamp bumped 3 -> 30 so the
    # winning N from the concentrated grid can drive the live recommendation
    # regardless of size (was silently clipping N=5 winners back to 3).
    top_n = int(max(1, min(30, safe_float(compare_df["target_stock_names"].iloc[0], 3.0)))) if not compare_df.empty and "target_stock_names" in compare_df.columns else int(max(1, min(30, getattr(cfg_obj, "concentrated_top_n_candidates", [3])[0])))
    weighting_mode = str(compare_df["weighting_mode"].iloc[0]) if not compare_df.empty and "weighting_mode" in compare_df.columns else str(getattr(cfg_obj, "concentrated_weighting_modes", ["conviction_curve"])[0])
    interval = int(safe_float(compare_df["rebalance_interval_months"].iloc[0], 1.0)) if not compare_df.empty and "rebalance_interval_months" in compare_df.columns else 1
    best_metrics = compare_df.iloc[0].to_dict() if not compare_df.empty else {}

    selected = select_concentrated_portfolio_topk(cfg_obj, d, top_n=top_n)
    if selected.empty:
        return pd.DataFrame(), {
            "portfolio_mode": "concentrated_alpha",
            "selected_names": 0,
            "target_stock_names": int(top_n),
            "weighting_mode": str(weighting_mode),
            "recommended_rebalance_interval_months": int(interval),
            "monitoring_review_days": int(getattr(cfg_obj, "concentrated_monitoring_review_days", 7)),
        }
    selected = selected.sort_values(["concentrated_score", "score"], ascending=[False, False]).reset_index(drop=True).copy()
    weight_map = concentrated_weight_map(cfg_obj, selected, weighting_mode=weighting_mode)
    selected["weight"] = selected["ticker"].astype(str).map(lambda x: weight_map.get(str(x), 0.0)).fillna(0.0)
    selected = selected[selected["weight"] > 1e-10].copy()
    selected = selected.sort_values("weight", ascending=False).reset_index(drop=True)
    selected["rank"] = np.arange(1, len(selected) + 1)
    selected["portfolio_mode"] = "concentrated_alpha"
    selected["weighting_mode"] = str(weighting_mode)
    selected["target_stock_names"] = int(top_n)
    selected["recommended_rebalance_interval_months"] = int(interval)
    selected["monitoring_review_days"] = int(getattr(cfg_obj, "concentrated_monitoring_review_days", 7))
    selected["concentrated_strategy_cagr"] = float(safe_float(best_metrics.get("strategy_cagr"), np.nan))
    selected["concentrated_strategy_sharpe"] = float(safe_float(best_metrics.get("sharpe"), np.nan))
    selected["concentrated_strategy_max_dd"] = float(safe_float(best_metrics.get("max_dd"), np.nan))
    selected["concentrated_strategy_objective"] = float(safe_float(best_metrics.get("comparison_objective"), np.nan))
    summary = {
        "portfolio_mode": "concentrated_alpha",
        "rebalance_date": str(pd.Timestamp(latest_dt).date()) if pd.notna(latest_dt) else None,
        "selected_names": int(len(selected)),
        "target_stock_names": int(top_n),
        "weighting_mode": str(weighting_mode),
        "recommended_rebalance_interval_months": int(interval),
        "monitoring_review_days": int(getattr(cfg_obj, "concentrated_monitoring_review_days", 7)),
        "strategy_cagr": float(safe_float(best_metrics.get("strategy_cagr"), np.nan)),
        "sharpe": float(safe_float(best_metrics.get("sharpe"), np.nan)),
        "max_dd": float(safe_float(best_metrics.get("max_dd"), np.nan)),
        "comparison_objective": float(safe_float(best_metrics.get("comparison_objective"), np.nan)),
        "operating_notes": [
            "Run a full rebalance monthly.",
            f"Run monitoring checks every {int(getattr(cfg_obj, 'concentrated_monitoring_review_days', 7))} days.",
            "Use concentrated holdings as a separate sleeve from the main portfolio.",
            "Allow immediate review if exit risk spikes or breakout support fails.",
        ],
    }
    return selected, summary


_SLEEVE_POLICY_CANDIDATES: list[dict] = [
    {"label": "core_only",           "core": 1.00, "future": 0.00, "early": 0.00},
    {"label": "def_60_25_15",        "core": 0.60, "future": 0.25, "early": 0.15},
    {"label": "bal_50_30_20",        "core": 0.50, "future": 0.30, "early": 0.20},
    {"label": "growth_40_40_20",     "core": 0.40, "future": 0.40, "early": 0.20},
    {"label": "growth_25_45_30",     "core": 0.25, "future": 0.45, "early": 0.30},
    {"label": "aggr_35_30_35",       "core": 0.35, "future": 0.30, "early": 0.35},
    {"label": "aggr_25_35_40",       "core": 0.25, "future": 0.35, "early": 0.40},
    {"label": "aggr_10_40_50",       "core": 0.10, "future": 0.40, "early": 0.50},
]


def generate_ai_four_sleeve_policy_candidates(cfg: dict | EngineConfig) -> list[dict[str, Any]]:
    cfg_obj = to_cfg(cfg)
    candidates = [
        {"label": "ai_bal_24_42_22_cash12", "core": 0.24, "future": 0.42, "early": 0.22, "cash": 0.12},
        {"label": "ai_bal_20_46_22_cash12", "core": 0.20, "future": 0.46, "early": 0.22, "cash": 0.12},
        {"label": "ai_growth_16_48_26_cash10", "core": 0.16, "future": 0.48, "early": 0.26, "cash": 0.10},
        {"label": "ai_growth_14_48_30_cash08", "core": 0.14, "future": 0.48, "early": 0.30, "cash": 0.08},
        {"label": "ai_growth_10_52_28_cash10", "core": 0.10, "future": 0.52, "early": 0.28, "cash": 0.10},
        {"label": "ai_barbell_12_42_32_cash14", "core": 0.12, "future": 0.42, "early": 0.32, "cash": 0.14},
        {"label": "ai_barbell_08_46_32_cash14", "core": 0.08, "future": 0.46, "early": 0.32, "cash": 0.14},
        {"label": "ai_early_08_42_38_cash12", "core": 0.08, "future": 0.42, "early": 0.38, "cash": 0.12},
        {"label": "ai_hot_06_52_34_cash08", "core": 0.06, "future": 0.52, "early": 0.34, "cash": 0.08},
        {"label": "ai_reentry_12_44_34_cash10", "core": 0.12, "future": 0.44, "early": 0.34, "cash": 0.10},
        {"label": "ai_risk_12_36_22_cash30", "core": 0.12, "future": 0.36, "early": 0.22, "cash": 0.30},
        {"label": "ai_risk_10_40_18_cash32", "core": 0.10, "future": 0.40, "early": 0.18, "cash": 0.32},
    ]
    max_candidates = max(int(getattr(cfg_obj, "ai_four_sleeve_max_candidates", len(candidates))), 1)
    return candidates[:max_candidates]


def compare_sleeve_policy_per_regime(
    cfg: dict | EngineConfig,
    signals: pd.DataFrame,
    candidates: Optional[list[dict]] = None,
    cash_target_max: float = 0.02,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Run each sleeve policy candidate against OOS backtest and break results down by market regime.

    Returns (grid_df, best_per_regime_df).
    - grid_df: one row per (policy_label, regime_label) with CAGR, Sharpe, max_dd, months.
      An extra row with regime_label='ALL' covers the full backtest period.
    - best_per_regime_df: one row per regime showing the highest-Sharpe policy.
    """
    cfg_obj = to_cfg(cfg)
    if candidates is None:
        candidates = _SLEEVE_POLICY_CANDIDATES

    rows: list[dict] = []
    for cand in candidates:
        lbl = str(cand.get("label", "unknown"))
        raw_cash = safe_float(cand.get("cash"), np.nan)
        so = {
            "core": float(cand.get("core", 0.70)),
            "future": float(cand.get("future", 0.20)),
            "early": float(cand.get("early", 0.10)),
        }
        cash_frac = float(
            np.clip(
                raw_cash if np.isfinite(raw_cash) else max(0.0, 1.0 - sum(so.values())),
                0.0,
                1.0,
            )
        )
        if cash_frac > 0.0:
            so["cash"] = cash_frac
        effective_cash_target_max = max(float(cash_target_max), cash_frac)
        log(f"  sleeve_policy_per_regime: policy={lbl} cash_max={effective_cash_target_max:.2%} ...")
        try:
            bt = backtest_portfolio(
                cfg_obj,
                signals,
                sleeve_override=so,
                cash_target_max=effective_cash_target_max,
            )
        except Exception as exc:
            log(f"  sleeve_policy_per_regime: backtest failed for {lbl}: {exc}")
            continue
        mr = bt.monthly_returns
        if mr.empty or "net_return" not in mr.columns:
            continue

        def _regime_row(label: str, ret_s: pd.Series, bench_s: Optional[pd.Series] = None) -> dict:
            m = performance_metrics(ret_s.reset_index(drop=True), bench_s.reset_index(drop=True) if bench_s is not None else None)
            row = {
                "policy_label": lbl,
                "core_frac": so["core"],
                "future_frac": so["future"],
                "early_frac": so["early"],
                "cash_frac": cash_frac,
                "cash_target_max": effective_cash_target_max,
                "regime_label": label,
                "months": len(ret_s),
                "cagr": m.get("cagr", np.nan),
                "sharpe": m.get("sharpe", np.nan),
                "sortino": m.get("sortino", np.nan),
                "max_dd": m.get("max_dd", np.nan),
                "vol_ann": m.get("vol_ann", np.nan),
                "ir": m.get("ir", np.nan),
            }
            row["regime_policy_objective"] = sleeve_regime_policy_objective(row)
            return row

        bench_col = mr["bench_return"] if "bench_return" in mr.columns else None
        rows.append(_regime_row("ALL", mr["net_return"], bench_col))
        if "regime_label" in mr.columns:
            for regime, grp in mr.groupby("regime_label"):
                if len(grp) < 3:
                    continue
                bench_grp = grp["bench_return"] if "bench_return" in grp.columns else None
                rows.append(_regime_row(str(regime), grp["net_return"], bench_grp))

    grid_df = pd.DataFrame(rows)
    if grid_df.empty:
        return grid_df, pd.DataFrame()
    grid_df = grid_df.sort_values(["regime_label", "regime_policy_objective", "sharpe"], ascending=[True, False, False]).reset_index(drop=True)

    best_rows: list[dict] = []
    for regime, grp in grid_df.groupby("regime_label"):
        valid = grp.dropna(subset=["regime_policy_objective"])
        if valid.empty:
            continue
        best_rows.append(valid.sort_values(["regime_policy_objective", "sharpe"], ascending=[False, False]).iloc[0].to_dict())
    best_df = pd.DataFrame(best_rows).sort_values("regime_label").reset_index(drop=True) if best_rows else pd.DataFrame()
    return grid_df, best_df


def compare_ai_four_sleeve_adaptive_model(
    cfg: dict | EngineConfig,
    signals: pd.DataFrame,
    *,
    active_backtest: Optional[BacktestResult] = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any], Optional[BacktestResult]]:
    cfg_obj = to_cfg(cfg)
    candidates = generate_ai_four_sleeve_policy_candidates(cfg_obj)
    if not candidates:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), {}, None
    regime_cash_max = max(float(getattr(cfg_obj, "sleeve_regime_comparison_cash_max", 0.02)), 0.08)
    grid_df, best_df = compare_sleeve_policy_per_regime(
        cfg_obj,
        signals,
        candidates=candidates,
        cash_target_max=regime_cash_max,
    )
    if grid_df.empty or best_df.empty:
        return pd.DataFrame(), grid_df, best_df, {}, None

    selected_map = build_regime_conditioned_sleeve_map(best_df)
    adaptive_cfg = clone_cfg_with_updates(
        cfg_obj,
        {
            "regime_conditioned_sleeve_map": selected_map,
            "sleeve_regime_apply_champion": True,
        },
    )
    adaptive_bt = backtest_portfolio(adaptive_cfg, signals, cash_target_max=regime_cash_max)
    baseline_bt = active_backtest if active_backtest is not None else backtest_portfolio(cfg_obj, signals)

    rows: list[dict[str, Any]] = []
    for model_label, bt_obj, model_cfg, selected_regime_map in [
        ("current_dynamic_baseline", baseline_bt, cfg_obj, {}),
        ("ai_four_sleeve_adaptive", adaptive_bt, adaptive_cfg, selected_map),
    ]:
        row = {
            "model_label": model_label,
            "candidate_count": int(len(candidates)) if model_label == "ai_four_sleeve_adaptive" else 0,
            "regime_map_size": int(len(selected_regime_map)) if selected_regime_map else 0,
        }
        row.update(_bt_metrics_row(bt_obj, model_cfg, portfolio_mode="dynamic", policy_mode=model_label))
        row.update(holdings_concentration_metrics(bt_obj.holdings))
        row["comparison_objective"] = sleeve_cap_policy_objective(
            {
                "strategy_cagr": row.get("strategy_cagr", np.nan),
                "benchmark_cagr": row.get("benchmark_cagr", np.nan),
                "excess_cagr": row.get("excess_cagr", np.nan),
                "sharpe": row.get("sharpe", np.nan),
                "sortino": row.get("sortino", np.nan),
                "max_dd": row.get("max_dd", np.nan),
                "avg_turnover_monthly": row.get("avg_turnover_monthly", np.nan),
                "avg_cash_weight": row.get("avg_cash_weight", np.nan),
                "avg_top_name_weight": row.get("avg_top_name_weight", np.nan),
                "avg_hhi": row.get("avg_hhi", np.nan),
            },
            cfg_obj,
        )
        if model_label == "ai_four_sleeve_adaptive":
            row["selected_regime_map_json"] = json.dumps(
                {
                    str(k): {
                        "core": round(float(v.get("core", 0.0)), 4),
                        "future": round(float(v.get("future", 0.0)), 4),
                        "early": round(float(v.get("early", 0.0)), 4),
                        "cash": round(float(v.get("cash", 0.0)), 4),
                        "policy_label": str(v.get("policy_label", "") or ""),
                    }
                    for k, v in selected_regime_map.items()
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        rows.append(row)
    comparison_df = pd.DataFrame(rows).sort_values("comparison_objective", ascending=False).reset_index(drop=True)
    return comparison_df, grid_df, best_df, selected_map, adaptive_bt


def compare_backtest_window_years(
    cfg: dict | EngineConfig,
    signals: pd.DataFrame,
    years_list: Optional[Iterable[int]] = None,
) -> pd.DataFrame:
    cfg_obj = to_cfg(cfg)
    candidates = years_list if years_list is not None else cfg_obj.backtest_window_comparison_years
    clean_years = sorted({int(x) for x in candidates if int(x) >= 1})
    d = signals.copy()
    d["rebalance_date"] = pd.to_datetime(d["rebalance_date"], errors="coerce")
    d = d.dropna(subset=["rebalance_date"]).copy()
    if d.empty:
        return pd.DataFrame()
    latest_dt = pd.Timestamp(d["rebalance_date"].max())
    earliest_dt = pd.Timestamp(d["rebalance_date"].min())
    _nan_keys = ["strategy_cagr", "benchmark_cagr", "excess_cagr", "sharpe", "sortino",
                 "max_dd", "ir", "beat_month_ratio", "avg_turnover_monthly", "avg_cash_weight", "avg_stock_names"]
    rows: list[dict[str, Any]] = []
    for years in clean_years:
        requested_start = (latest_dt - pd.DateOffset(years=int(years))).normalize()
        subset = d[d["rebalance_date"] >= requested_start].copy()
        months = sorted(subset["rebalance_date"].dropna().unique().tolist())
        full_window = bool(pd.Timestamp(earliest_dt) <= pd.Timestamp(requested_start))
        actual_start = pd.Timestamp(months[0]) if months else pd.NaT
        row: dict[str, Any] = {
            "window_years": int(years),
            "requested_start_date": str(pd.Timestamp(requested_start).date()),
            "actual_start_date": str(pd.Timestamp(actual_start).date()) if pd.notna(actual_start) else None,
            "end_date": str(pd.Timestamp(latest_dt).date()),
            "available_months": int(max(len(months) - 1, 0)),
            "actual_window_years": float(max((latest_dt - actual_start).days, 0) / 365.25) if pd.notna(actual_start) else 0.0,
            "available_years_covered": float(max((latest_dt - earliest_dt).days, 0) / 365.25),
        }
        if len(months) < 2:
            row.update({"available": False, "full_window_available": full_window,
                        **{k: np.nan for k in _nan_keys},
                        "benchmark_source": benchmark_history_source_label(cfg_obj), "status": "insufficient_months"})
        else:
            bt = backtest_portfolio(cfg_obj, subset)
            row.update(_bt_metrics_row(bt, cfg_obj))
            row.update({"available": True, "full_window_available": full_window,
                        "status": "ok" if full_window else "partial_window"})
        rows.append(row)
    return pd.DataFrame(rows).sort_values("window_years").reset_index(drop=True)


def _closest_rebalance_interval(allowed_intervals: Iterable[int], target_interval: int) -> int:
    allowed = sorted({max(int(x), 1) for x in allowed_intervals if pd.notna(x)})
    if not allowed:
        return int(max(target_interval, 1))
    target = int(max(target_interval, 1))
    return int(min(allowed, key=lambda x: (abs(int(x) - target), int(x))))


def _available_rebalance_intervals(
    interval_compare: Optional[pd.DataFrame],
    cfg: Optional[dict | EngineConfig],
    default_interval: int,
) -> list[int]:
    cfg_obj = to_cfg(cfg) if cfg is not None else None
    allowed: list[int] = []
    if interval_compare is not None and not interval_compare.empty and "rebalance_interval_months" in interval_compare.columns:
        allowed = [
            int(x)
            for x in pd.to_numeric(interval_compare["rebalance_interval_months"], errors="coerce").dropna().tolist()
            if int(x) >= 1
        ]
    if not allowed and cfg_obj is not None:
        allowed = [int(x) for x in getattr(cfg_obj, "rebalance_interval_comparison_months", []) if int(x) >= 1]
    if not allowed:
        allowed = [int(max(default_interval, 1))]
    return sorted(set(allowed))


def infer_rebalance_interval_policy(
    cfg: dict | EngineConfig,
    latest_frame: Optional[pd.DataFrame],
    latest_live_event_alert: str = "balanced",
    allowed_intervals: Optional[Iterable[int]] = None,
) -> dict[str, Any]:
    cfg_obj = to_cfg(cfg)
    allowed = sorted(
        {
            max(int(x), 1)
            for x in (
                list(allowed_intervals)
                if allowed_intervals is not None
                else list(getattr(cfg_obj, "rebalance_interval_comparison_months", []) or [cfg_obj.rebalance_interval_months])
            )
            if pd.notna(x)
        }
    )
    if not allowed:
        allowed = [int(max(getattr(cfg_obj, "rebalance_interval_months", 1), 1))]

    if not bool(getattr(cfg_obj, "adaptive_rebalance_enabled", True)):
        target = _closest_rebalance_interval(allowed, int(getattr(cfg_obj, "rebalance_interval_months", 1)))
        return {
            "target_interval_months": int(target),
            "regime_interval_label": "fixed_default",
            "regime_interval_reason": "Adaptive rebalance policy is disabled; use the configured default interval.",
            "regime_risk_signal": 0.0,
            "regime_growth_signal": 0.0,
        }

    d = latest_frame.copy() if latest_frame is not None else pd.DataFrame()

    def _median_or_default(col: str, default: float = 0.0) -> float:
        if d.empty or col not in d.columns:
            return float(default)
        val = safe_float(pd.to_numeric(d[col], errors="coerce").median())
        return float(default if np.isnan(val) else val)

    live_label = str(latest_live_event_alert or "balanced")
    if (not latest_live_event_alert) and (not d.empty) and "live_event_alert_label" in d.columns:
        label_mode = d["live_event_alert_label"].dropna().astype(str).mode()
        if not label_mode.empty:
            live_label = str(label_mode.iloc[0])
    breadth_regime = _median_or_default("market_breadth_regime_score", 0.50)
    sector_participation = _median_or_default("market_sector_participation", 0.35)
    systemic = _median_or_default("systemic_crisis_score", 0.0)
    carry_unwind = _median_or_default("carry_unwind_stress_score", 0.0)
    war_oil_rate = _median_or_default("war_oil_rate_shock_score", 0.0)
    defensive_rotation = _median_or_default("defensive_rotation_score", 0.0)
    growth_reentry = _median_or_default("growth_reentry_score", 0.0)
    growth_liquidity = _median_or_default("growth_liquidity_reentry_score", 0.0)
    liquidity_impulse = _median_or_default("liquidity_impulse_score", 0.0)
    liquidity_drain = _median_or_default("liquidity_drain_score", 0.0)
    live_event_risk = _median_or_default("live_event_risk_score", 0.0)
    live_event_systemic = _median_or_default("live_event_systemic_score", 0.0)
    live_event_war = _median_or_default("live_event_war_oil_rate_score", 0.0)
    live_event_defensive = _median_or_default("live_event_defensive_score", 0.0)
    live_event_growth = _median_or_default("live_event_growth_reentry_score", 0.0)

    breadth_stress = max(0.0, 0.50 - breadth_regime)
    participation_stress = max(0.0, 0.38 - sector_participation)
    risk_signal = max(
        systemic,
        carry_unwind,
        war_oil_rate,
        defensive_rotation,
        liquidity_drain,
        live_event_risk,
        live_event_systemic,
        live_event_war,
        live_event_defensive,
        breadth_stress,
        participation_stress,
    )
    growth_signal = max(
        growth_reentry,
        growth_liquidity,
        liquidity_impulse,
        live_event_growth,
        max(0.0, breadth_regime - 0.50),
    )

    target_interval = int(getattr(cfg_obj, "adaptive_rebalance_growth_months", 1))
    label = "balanced_monthly"
    reason = "Base case is monthly refresh so leadership changes are captured unless the regime clearly argues for a slower cycle."
    risk_alert_like = {"systemic_alert", "war_oil_rate_alert", "risk_off_alert"}
    if (
        live_label in risk_alert_like
        or risk_signal >= float(getattr(cfg_obj, "adaptive_rebalance_risk_threshold", 0.60))
        or (liquidity_drain >= 0.55 and breadth_regime < 0.48)
    ):
        target_interval = int(getattr(cfg_obj, "adaptive_rebalance_riskoff_months", 6))
        label = "risk_off_slow"
        reason = "Risk-off or liquidity-drain regime; extend the rebalance interval to reduce turnover and let defensive winners compound."
    elif (
        risk_signal >= 0.35
        or liquidity_drain >= 0.35
        or breadth_regime < 0.58
        or sector_participation < 0.40
        or live_event_defensive >= 0.45
    ):
        target_interval = int(getattr(cfg_obj, "adaptive_rebalance_balanced_months", 3))
        label = "balanced_quarterly"
        reason = "Breadth or risk backdrop is mixed; slow the cadence to quarterly until market participation improves."
    elif (
        growth_signal >= float(getattr(cfg_obj, "adaptive_rebalance_growth_threshold", 0.60))
        and live_event_risk < float(getattr(cfg_obj, "live_event_risk_threshold", 0.55))
        and liquidity_drain < 0.45
    ):
        target_interval = int(getattr(cfg_obj, "adaptive_rebalance_growth_months", 1))
        label = "growth_fast"
        reason = "Growth/liquidity re-entry regime; use faster monthly refresh to capture leadership rotation."

    chosen_target = _closest_rebalance_interval(allowed, target_interval)
    return {
        "target_interval_months": int(chosen_target),
        "regime_interval_label": str(label),
        "regime_interval_reason": str(reason),
        "regime_risk_signal": float(risk_signal),
        "regime_growth_signal": float(growth_signal),
    }


def choose_best_rebalance_interval(
    interval_compare: pd.DataFrame,
    default_interval: int = 1,
    latest_frame: Optional[pd.DataFrame] = None,
    latest_live_event_alert: str = "balanced",
    cfg: Optional[dict | EngineConfig] = None,
) -> dict[str, Any]:
    cfg_obj = to_cfg(cfg) if cfg is not None else None
    allowed = _available_rebalance_intervals(interval_compare, cfg_obj, default_interval)
    regime_policy = infer_rebalance_interval_policy(
        cfg_obj if cfg_obj is not None else {"base_dir": os.getcwd(), "rebalance_interval_comparison_months": allowed},
        latest_frame,
        latest_live_event_alert=latest_live_event_alert,
        allowed_intervals=allowed,
    )
    target_interval = int(regime_policy.get("target_interval_months", max(default_interval, 1)))
    if interval_compare is None or interval_compare.empty:
        return {
            "rebalance_interval_months": int(target_interval),
            **regime_policy,
        }

    ranked = interval_compare.copy()
    if "policy_mode" in ranked.columns:
        fixed_ranked = ranked[ranked["policy_mode"].astype(str).eq("fixed_interval")].copy()
        if not fixed_ranked.empty:
            ranked = fixed_ranked
    ranked["interval_num"] = pd.to_numeric(ranked.get("rebalance_interval_months"), errors="coerce")
    ranked = ranked[ranked["interval_num"].notna()].copy()
    if ranked.empty:
        return {
            "rebalance_interval_months": int(target_interval),
            **regime_policy,
        }
    ranked["interval_num"] = ranked["interval_num"].astype(int)

    metric_specs = [
        ("ir", "ir_sort"),
        ("excess_cagr", "excess_sort"),
        ("strategy_cagr", "cagr_sort"),
        ("max_dd", "maxdd_sort"),
    ]
    rank_cols: list[str] = []
    for metric_col, sort_col in metric_specs:
        ranked[sort_col] = pd.to_numeric(ranked.get(metric_col), errors="coerce").fillna(-np.inf)
        rank_col = f"{sort_col}_rank"
        ranked[rank_col] = ranked[sort_col].rank(ascending=False, method="dense")
        rank_cols.append(rank_col)

    distance_penalty = float(getattr(cfg_obj, "adaptive_rebalance_distance_penalty", 0.75)) if cfg_obj is not None else 0.75
    ranked["regime_distance"] = (ranked["interval_num"] - int(target_interval)).abs()
    ranked["performance_rank_sum"] = ranked[rank_cols].sum(axis=1)
    ranked["policy_rank"] = ranked["performance_rank_sum"] + distance_penalty * ranked["regime_distance"]
    ranked = ranked.sort_values(
        ["policy_rank", "regime_distance", "ir_sort", "excess_sort", "cagr_sort", "maxdd_sort", "interval_num"],
        ascending=[True, True, False, False, False, False, True],
    )

    raw_top = ranked.iloc[0].to_dict()
    top: dict[str, Any] = {}
    for key, value in raw_top.items():
        if isinstance(value, np.generic):
            top[key] = value.item()
        else:
            top[key] = value
    interval_value = pd.to_numeric(pd.Series([top.get("interval_num", top.get("rebalance_interval_months"))]), errors="coerce").iloc[0]
    if not np.isfinite(interval_value):
        interval_value = float(target_interval)
    top["rebalance_interval_months"] = int(max(interval_value, 1.0))
    top["target_interval_months"] = int(target_interval)
    top.update(regime_policy)
    return top


def build_next_run_recommendation(
    cfg: dict | EngineConfig,
    latest_rebalance_date: Any,
    latest_live_event_alert: str,
    recommended_interval_months: int,
    previous_live_policy: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    cfg_obj = to_cfg(cfg)
    latest_dt = pd.to_datetime(latest_rebalance_date, errors="coerce")
    interval_months = max(int(recommended_interval_months), 1)
    previous_policy = previous_live_policy if isinstance(previous_live_policy, dict) else {}
    prev_sched_dt = pd.to_datetime(previous_policy.get("next_scheduled_rebalance_date"), errors="coerce")
    prev_interval_raw = pd.to_numeric(
        pd.Series(
            [
                previous_policy.get(
                    "active_rebalance_interval_months",
                    previous_policy.get(
                        "recommended_rebalance_interval_months",
                        previous_policy.get("rebalance_interval_months", interval_months),
                    ),
                )
            ]
        ),
        errors="coerce",
    ).iloc[0]
    prev_interval = int(max(prev_interval_raw, 1.0)) if np.isfinite(prev_interval_raw) else int(interval_months)
    live_label = str(latest_live_event_alert or "balanced")
    alert_like = {"systemic_alert", "war_oil_rate_alert", "risk_off_alert"}
    review_dt = None
    policy_due = True
    active_interval = int(interval_months)
    scheduled_dt = next_rebalance_date_for_interval(latest_dt, interval_months=interval_months)
    run_mode = "full_step1_and_step2"
    action = "rebalance"
    reason = f"Run again on the next {interval_months}-month rebalance date."

    if (
        bool(getattr(cfg_obj, "adaptive_rebalance_hold_until_due", True))
        and pd.notna(prev_sched_dt)
        and pd.notna(latest_dt)
        and pd.Timestamp(latest_dt) < pd.Timestamp(prev_sched_dt)
    ):
        policy_due = False
        active_interval = int(max(prev_interval, 1))
        scheduled_dt = pd.Timestamp(prev_sched_dt)
        run_mode = "hold_until_scheduled_rebalance"
        action = "hold"
        reason = (
            f"Existing {active_interval}-month live cycle is still active; "
            "keep the current portfolio until the scheduled rebalance date."
        )

    if live_label in alert_like:
        review_target = pd.Timestamp.today().normalize() + pd.Timedelta(days=int(cfg_obj.alert_review_days))
        review_dt = next_nyse_trading_day_on_or_after(review_target, max_search_days=10)
        if review_dt is not None:
            run_mode = "step2_only_review"
            action = "review_and_hold" if not policy_due else "review_then_rebalance"
            reason = (
                f"Live alert is {live_label}; do an interim Step 2 review sooner, "
                "then run the full pipeline again on the scheduled rebalance date."
            )
    recommended_dt = review_dt if review_dt is not None else scheduled_dt
    return {
        "recommended_rebalance_interval_months": int(interval_months),
        "active_rebalance_interval_months": int(active_interval),
        "policy_rebalance_due": bool(policy_due),
        "next_rebalance_action": str(action),
        "deferred_rebalance_interval_months": (
            int(interval_months)
            if (not policy_due and int(interval_months) != int(active_interval))
            else None
        ),
        "next_scheduled_rebalance_date": str(pd.Timestamp(scheduled_dt).date()) if pd.notna(scheduled_dt) else None,
        "interim_review_date": str(pd.Timestamp(review_dt).date()) if pd.notna(review_dt) else None,
        "recommended_next_run_date": str(pd.Timestamp(recommended_dt).date()) if pd.notna(recommended_dt) else None,
        "recommended_next_run_mode": run_mode,
        "recommended_next_run_reason": reason,
    }


def build_latest_portfolio(cfg: dict | EngineConfig, latest_recommendations: pd.DataFrame) -> pd.DataFrame:
    cfg = to_cfg(cfg)
    paths = get_paths(cfg)
    latest = latest_recommendations.copy()
    if latest.empty:
        return latest
    latest["rebalance_date"] = pd.to_datetime(latest["rebalance_date"], errors="coerce")
    latest_dt = latest["rebalance_date"].max()
    previous_live_policy = load_previous_live_policy(paths, latest_dt=latest_dt)
    prev_w = load_previous_live_weights(paths, latest_dt=latest_dt)
    prev_holdings_count = int(
        sum(1 for k, v in prev_w.items() if str(k).upper() != CASH_PROXY_TICKER and pd.notna(v) and float(v) > 1e-10)
    )
    prev_holdings_applied = bool(prev_holdings_count > 0)
    latest = latest[latest["rebalance_date"] == latest_dt].copy()
    if "ranking_eligible" in latest.columns:
        latest = latest[latest["ranking_eligible"].fillna(False)].copy()
    else:
        latest = add_core_fundamental_minimum_flags(latest, cfg)
        latest = latest[latest["core_fundamental_minimum_pass"].fillna(False)].copy()
    if latest.empty:
        return latest

    live_alert = build_live_event_alert_table(cfg, paths)
    live_alert_sample = live_alert.sort_values("event_date").iloc[-1] if isinstance(live_alert, pd.DataFrame) and not live_alert.empty else None
    live_risk = 0.0
    live_systemic = 0.0
    live_war = 0.0
    live_defensive = 0.0
    live_growth = 0.0
    live_label = "balanced"
    alert_like = {"systemic_alert", "war_oil_rate_alert", "risk_off_alert"}
    if live_alert_sample is not None:
        live_risk = float(np.nan_to_num(safe_float(live_alert_sample.get("live_event_risk_score")), nan=0.0))
        live_systemic = float(np.nan_to_num(safe_float(live_alert_sample.get("live_event_systemic_score")), nan=0.0))
        live_war = float(np.nan_to_num(safe_float(live_alert_sample.get("live_event_war_oil_rate_score")), nan=0.0))
        live_defensive = float(np.nan_to_num(safe_float(live_alert_sample.get("live_event_defensive_score")), nan=0.0))
        live_growth = float(np.nan_to_num(safe_float(live_alert_sample.get("live_event_growth_reentry_score")), nan=0.0))
        live_label = str(live_alert_sample.get("live_event_alert_label", "balanced"))
        latest["live_event_alert_label"] = live_label
        latest["live_event_risk_score"] = live_risk
        latest["live_event_systemic_score"] = live_systemic
        latest["live_event_war_oil_rate_score"] = live_war
        latest["live_event_defensive_score"] = live_defensive
        latest["live_event_growth_reentry_score"] = live_growth

    prev_sched_dt = pd.to_datetime(previous_live_policy.get("next_scheduled_rebalance_date"), errors="coerce")
    prev_interval_raw = pd.to_numeric(
        pd.Series(
            [
                previous_live_policy.get(
                    "active_rebalance_interval_months",
                    previous_live_policy.get(
                        "recommended_rebalance_interval_months",
                        previous_live_policy.get("rebalance_interval_months", cfg.rebalance_interval_months),
                    ),
                )
            ]
        ),
        errors="coerce",
    ).iloc[0]
    prev_interval_months = int(max(prev_interval_raw, 1.0)) if np.isfinite(prev_interval_raw) else int(max(cfg.rebalance_interval_months, 1))
    scheduled_hold_active = bool(
        getattr(cfg, "adaptive_rebalance_hold_until_due", True)
        and prev_holdings_applied
        and pd.notna(prev_sched_dt)
        and pd.notna(latest_dt)
        and pd.Timestamp(latest_dt) < pd.Timestamp(prev_sched_dt)
        and live_label not in alert_like
    )

    if scheduled_hold_active:
        prior_holdings = previous_live_policy.get("holdings") or {}
        latest_lookup = latest.copy()
        latest_lookup["ticker"] = latest_lookup["ticker"].astype(str).str.upper()
        latest_lookup = latest_lookup.drop_duplicates(subset=["ticker"], keep="first").set_index("ticker", drop=False)
        hold_rows: list[pd.Series] = []
        for raw_ticker, raw_weight in prior_holdings.items():
            ticker = normalize_ticker(raw_ticker)
            weight = safe_float(raw_weight)
            if not ticker or pd.isna(weight) or float(weight) <= 1e-10:
                continue
            if ticker == CASH_PROXY_TICKER:
                row = pd.Series(
                    {
                        "ticker": CASH_PROXY_TICKER,
                        "Name": "Cash",
                        "sector": "Cash",
                        "rebalance_date": latest_dt,
                    }
                )
            elif ticker in latest_lookup.index:
                row = latest_lookup.loc[ticker]
                if isinstance(row, pd.DataFrame):
                    row = row.iloc[0]
                row = row.copy()
            else:
                row = pd.Series(
                    {
                        "ticker": ticker,
                        "Name": ticker,
                        "sector": np.nan,
                        "rebalance_date": latest_dt,
                    }
                )
            row["weight"] = float(weight)
            row["selected_for_portfolio"] = True
            row["held_from_prev_rebalance"] = 0.0 if ticker == CASH_PROXY_TICKER else 1.0
            row["prev_weight"] = float(weight)
            hold_rows.append(row)
        hold_portfolio = pd.DataFrame(hold_rows)
        if not hold_portfolio.empty and "weight" in hold_portfolio.columns:
            hold_portfolio["weight"] = pd.to_numeric(hold_portfolio["weight"], errors="coerce").fillna(0.0)
            total_weight = float(hold_portfolio["weight"].sum())
            if total_weight > 0:
                hold_portfolio["weight"] = hold_portfolio["weight"] / total_weight
        if not hold_portfolio.empty:
            hold_portfolio["rebalance_date"] = latest_dt
            hold_portfolio["selected_for_portfolio"] = True
            hold_portfolio["target_n"] = int(previous_live_policy.get("target_n") or max(prev_holdings_count, 0))
            weight_cap = safe_float(previous_live_policy.get("weight_cap"))
            cash_target = safe_float(previous_live_policy.get("cash_target"))
            hold_portfolio["weight_cap"] = float(weight_cap) if pd.notna(weight_cap) else float(cfg.stock_weight_max_high_conviction)
            hold_portfolio["cash_target"] = float(cash_target) if pd.notna(cash_target) else float(
                pd.to_numeric(
                    hold_portfolio.loc[
                        hold_portfolio.get("ticker", pd.Series(dtype=object)).astype(str).str.upper().eq(CASH_PROXY_TICKER),
                        "weight",
                    ],
                    errors="coerce",
                ).fillna(0.0).sum()
            )
            hold_portfolio["prev_holdings_applied"] = bool(prev_holdings_applied)
            hold_portfolio["prev_holdings_count"] = int(prev_holdings_count)
            hold_portfolio["rebalance_action"] = "scheduled_hold"
            hold_portfolio["active_rebalance_interval_months"] = int(prev_interval_months)
            hold_portfolio["scheduled_rebalance_due"] = False
            hold_portfolio["next_scheduled_rebalance_date"] = str(pd.Timestamp(prev_sched_dt).date())
            hold_portfolio = apply_sleeve_rebalance_interval_columns(hold_portfolio, cfg)
            hold_portfolio = hold_portfolio.sort_values("weight", ascending=False).reset_index(drop=True)
            hold_portfolio.insert(0, "rank", np.arange(1, len(hold_portfolio) + 1))
            return hold_portfolio

    cfg_port = cfg
    focus_n = int(min(cfg.top_n, max(cfg.min_port_names, getattr(cfg, "focus_target_n", cfg.top_n))))
    severe_risk_off = False
    mild_risk_off = False
    live_growth_on = False
    strong_growth = False
    if bool(cfg.strict_live_backtest_alignment):
        latest = latest.sort_values("score", ascending=False).copy()
    else:
        if "selection_confirmation_score" not in latest.columns:
            latest = compute_benchmark_beating_focus_overlay(latest, cfg)
    allow_live_policy_overrides = bool(cfg.use_benchmark_beating_focus_overlay) and not bool(
        cfg.strict_live_backtest_alignment
    )
    if allow_live_policy_overrides:
        regime_ctl = compute_regime_portfolio_controls(cfg, latest)
        live_stress = max(live_risk, live_systemic, live_war)
        severe_risk_off = (live_stress >= max(0.65, cfg.live_event_risk_threshold + 0.08)) or (
            regime_ctl["risk_multiplier"] > 1.22 and live_stress >= 0.30
        )
        mild_risk_off = severe_risk_off or (max(live_risk, live_defensive) >= cfg.live_event_risk_threshold) or (
            regime_ctl["risk_multiplier"] > 1.08 and live_stress >= 0.25
        )
        live_growth_on = (live_growth >= cfg.live_event_growth_threshold) and (live_risk < cfg.live_event_risk_threshold)
        strong_growth = live_growth_on and live_growth >= 0.72 and live_risk < 0.35
        focus_n = cfg.focus_riskoff_target_n if severe_risk_off else cfg.focus_target_n
        cfg_port = to_cfg(asdict(cfg))
        if severe_risk_off:
            focus_n = min(focus_n, max(cfg.min_dynamic_port_names, cfg.focus_riskoff_target_n - 2))
        elif mild_risk_off:
            focus_n = min(focus_n, max(cfg.min_dynamic_port_names + 2, cfg.focus_riskoff_target_n + 1))
        elif strong_growth:
            focus_n = min(cfg.top_n, max(focus_n + 6, 22))
        elif live_growth_on:
            focus_n = min(cfg.top_n, max(focus_n + 3, 15))
        elif live_label == "balanced":
            focus_n = max(focus_n, min(cfg.top_n, 18))
        cfg_port.top_n = int(cfg.top_n)
        cfg_port.min_port_names = cfg.min_port_names
        dynamic_floor = int(focus_n) - (4 if severe_risk_off else (2 if live_growth_on else 3))
        cfg_port.min_dynamic_port_names = min(
            cfg_port.top_n,
            max(int(cfg.min_dynamic_port_names), dynamic_floor),
        )
        if severe_risk_off:
            cfg_port.stock_weight_max_high_conviction = min(cfg_port.stock_weight_max_high_conviction, 0.25)
            cfg_port.stock_weight_max_no_ttm = min(cfg_port.stock_weight_max_no_ttm, 0.08)
            cfg_port.stock_weight_max_no_ttm_confirmed = min(cfg_port.stock_weight_max_no_ttm_confirmed, 0.10)
        elif mild_risk_off:
            cfg_port.stock_weight_max_high_conviction = min(cfg_port.stock_weight_max_high_conviction, 0.30)
            cfg_port.stock_weight_max_no_ttm = min(cfg_port.stock_weight_max_no_ttm, 0.10)
            cfg_port.stock_weight_max_no_ttm_confirmed = min(cfg_port.stock_weight_max_no_ttm_confirmed, 0.14)
        elif strong_growth:
            cfg_port.stock_weight_max_high_conviction = min(max(cfg_port.stock_weight_max_high_conviction, 0.50), 0.50)
            cfg_port.stock_weight_max_no_ttm = min(cfg_port.stock_weight_max_no_ttm, 0.16)
            cfg_port.stock_weight_max_no_ttm_confirmed = min(cfg_port.stock_weight_max_no_ttm_confirmed, 0.22)
        elif live_growth_on:
            cfg_port.stock_weight_max_high_conviction = min(max(cfg_port.stock_weight_max_high_conviction, 0.45), 0.50)
            cfg_port.stock_weight_max_no_ttm = min(cfg_port.stock_weight_max_no_ttm, 0.14)
            cfg_port.stock_weight_max_no_ttm_confirmed = min(cfg_port.stock_weight_max_no_ttm_confirmed, 0.20)
        else:
            cfg_port.stock_weight_max_high_conviction = min(cfg_port.stock_weight_max_high_conviction, 0.40)
        if severe_risk_off:
            cfg_port.cap_base_weight = min(cfg_port.cap_base_weight, 0.25)
            cfg_port.cap_leader_weight = min(cfg_port.cap_leader_weight, 0.35)
            cfg_port.cap_overheated_weight = min(cfg_port.cap_overheated_weight, 0.18)
            cfg_port.cap_lagger_weight = min(cfg_port.cap_lagger_weight, 0.15)
        elif mild_risk_off:
            cfg_port.cap_base_weight = min(max(cfg_port.cap_base_weight, 0.30), 0.34)
            cfg_port.cap_leader_weight = min(max(cfg_port.cap_leader_weight, 0.42), 0.48)
            cfg_port.cap_overheated_weight = min(max(cfg_port.cap_overheated_weight, 0.22), 0.26)
        elif strong_growth:
            cfg_port.cap_base_weight = min(max(cfg_port.cap_base_weight, 0.48), 0.55)
            cfg_port.cap_leader_weight = min(max(cfg_port.cap_leader_weight, 0.75), 0.80)
            cfg_port.cap_overheated_weight = min(max(cfg_port.cap_overheated_weight, 0.38), 0.42)
        elif live_growth_on:
            cfg_port.cap_base_weight = min(max(cfg_port.cap_base_weight, 0.44), 0.50)
            cfg_port.cap_leader_weight = min(max(cfg_port.cap_leader_weight, 0.68), 0.75)
            cfg_port.cap_overheated_weight = min(max(cfg_port.cap_overheated_weight, 0.34), 0.38)
        else:
            cfg_port.cap_base_weight = min(max(cfg_port.cap_base_weight, 0.40), 0.44)
            cfg_port.cap_leader_weight = min(max(cfg_port.cap_leader_weight, 0.62), 0.66)
            cfg_port.cap_overheated_weight = min(max(cfg_port.cap_overheated_weight, 0.32), 0.36)
        if severe_risk_off:
            cfg_port.stock_weight_max = min(cfg_port.stock_weight_max, 0.06)
        elif mild_risk_off:
            cfg_port.stock_weight_max = min(cfg_port.stock_weight_max, 0.08)
        elif strong_growth:
            cfg_port.stock_weight_max = min(max(cfg_port.stock_weight_max, 0.14), 0.16)
        elif live_growth_on:
            cfg_port.stock_weight_max = min(max(cfg_port.stock_weight_max, 0.12), 0.14)
        else:
            cfg_port.stock_weight_max = min(max(cfg_port.stock_weight_max, 0.10), 0.12)
        latest["portfolio_seed_overheat_penalty"] = 0.0
        latest["portfolio_seed_score"] = (
            pd.to_numeric(latest["score"], errors="coerce").fillna(0.0)
            + 0.28 * numeric_series_or_default(latest, "sage_composite_score", 0.0)
            + 0.12 * numeric_series_or_default(latest, "sage_g_score", 0.0)
            + 0.10 * numeric_series_or_default(latest, "portfolio_future_winner_engine_score", 0.0)
            + 0.08 * numeric_series_or_default(latest, "portfolio_early_scout_engine_score", 0.0)
        )
        candidate_n = max(int(cfg.top_n) * 2, int(focus_n) + 12)
        latest = latest.sort_values(["portfolio_seed_score", "score"], ascending=[False, False]).head(candidate_n).copy()

    def _portfolio_shape(frame: pd.DataFrame) -> tuple[int, float]:
        if frame.empty or "ticker" not in frame.columns:
            return 0, 0.0
        tickers = frame["ticker"].astype(str).str.upper()
        stock_n = int(tickers.ne(CASH_PROXY_TICKER).sum())
        cash_weight = float(pd.to_numeric(frame.loc[tickers.eq(CASH_PROXY_TICKER), "weight"], errors="coerce").fillna(0.0).sum())
        return stock_n, cash_weight

    portfolio, _, meta = build_target_portfolio(
        cfg_port,
        latest,
        prev_w=prev_w if prev_holdings_applied else None,
        apply_turnover=False,
    )
    stock_n, cash_weight = _portfolio_shape(portfolio)
    growth_cash_cap = min(cfg_port.cash_weight_max, float(getattr(cfg_port, "cash_target_growth_cap", 0.03)))
    balanced_cash_cap = min(cfg_port.cash_weight_max, float(getattr(cfg_port, "cash_target_balanced_cap", 0.05)))
    mild_risk_cash_cap = min(cfg_port.cash_weight_max, float(getattr(cfg_port, "cash_target_mild_risk_cap", 0.10)))
    min_live_names = 3 if severe_risk_off else (5 if mild_risk_off else (12 if strong_growth else (10 if live_growth_on else 8)))
    max_live_cash = (
        min(cfg_port.cash_weight_max, 0.25)
        if severe_risk_off
        else (
            mild_risk_cash_cap
            if mild_risk_off
            else (growth_cash_cap if strong_growth else (min(balanced_cash_cap, 0.04) if live_growth_on else balanced_cash_cap))
        )
    )
    if allow_live_policy_overrides and (portfolio.empty or stock_n < min_live_names or cash_weight > max_live_cash + 1e-6):
        retry_cfg = to_cfg(asdict(cfg_port))
        retry_cfg.min_dynamic_port_names = min(
            retry_cfg.top_n,
            max(int(retry_cfg.min_dynamic_port_names), min_live_names),
        )
        retry_cfg.cash_weight_max = min(retry_cfg.cash_weight_max, max_live_cash)
        if not severe_risk_off:
            retry_cfg.cap_base_weight = max(retry_cfg.cap_base_weight, 0.44 if live_growth_on else 0.40)
            retry_cfg.cap_leader_weight = max(retry_cfg.cap_leader_weight, 0.68 if live_growth_on else 0.62)
            retry_cfg.cap_overheated_weight = max(retry_cfg.cap_overheated_weight, 0.34 if live_growth_on else 0.32)
        retry_target_n = min(retry_cfg.top_n, max(min_live_names, int(focus_n)))
        retry_portfolio, _, retry_meta = build_target_portfolio(
            retry_cfg,
            latest,
            prev_w=prev_w if prev_holdings_applied else None,
            apply_turnover=False,
            target_n_override=retry_target_n,
        )
        retry_stock_n, retry_cash_weight = _portfolio_shape(retry_portfolio)
        retry_better = False
        if retry_stock_n > stock_n:
            retry_better = True
        elif retry_stock_n >= min_live_names and (
            retry_cash_weight + 0.005 < cash_weight
            or (cash_weight > max_live_cash + 1e-6 and retry_cash_weight < cash_weight)
        ):
            retry_better = True
        elif portfolio.empty and not retry_portfolio.empty:
            retry_better = True
        if retry_better:
            portfolio = retry_portfolio
            meta = retry_meta
            cfg_port = retry_cfg
            stock_n, cash_weight = retry_stock_n, retry_cash_weight
    if allow_live_policy_overrides and not severe_risk_off and cash_weight > max_live_cash + 1e-6:
        fill_cfg = to_cfg(asdict(cfg_port))
        fill_cfg.min_dynamic_port_names = fill_cfg.top_n
        fill_cfg.cash_weight_max = min(fill_cfg.cash_weight_max, max_live_cash)
        fill_cfg.cap_base_weight = max(fill_cfg.cap_base_weight, 0.46 if live_growth_on else 0.44)
        fill_cfg.cap_leader_weight = max(fill_cfg.cap_leader_weight, 0.72 if live_growth_on else 0.68)
        fill_cfg.cap_overheated_weight = max(fill_cfg.cap_overheated_weight, 0.36 if live_growth_on else 0.34)
        if strong_growth or live_growth_on:
            fill_cfg.stock_weight_max = max(fill_cfg.stock_weight_max, 0.14)
        fill_portfolio, _, fill_meta = build_target_portfolio(
            fill_cfg,
            latest,
            prev_w=prev_w if prev_holdings_applied else None,
            apply_turnover=False,
            target_n_override=int(fill_cfg.top_n),
        )
        fill_stock_n, fill_cash_weight = _portfolio_shape(fill_portfolio)
        if (
            (fill_stock_n >= stock_n and fill_cash_weight + 0.005 < cash_weight)
            or fill_cash_weight <= max_live_cash + 1e-6
            or (portfolio.empty and not fill_portfolio.empty)
        ):
            portfolio = fill_portfolio
            meta = fill_meta
            cfg_port = fill_cfg
    if portfolio.empty:
        return portfolio
    portfolio = dedupe_same_company_rows(portfolio, score_col="weight")
    if "weight" in portfolio.columns:
        portfolio["weight"] = pd.to_numeric(portfolio["weight"], errors="coerce").fillna(0.0)
        total_weight = float(portfolio["weight"].sum())
        if total_weight > 0:
            portfolio["weight"] = portfolio["weight"] / total_weight
    portfolio["rebalance_date"] = latest_dt
    portfolio["selected_for_portfolio"] = True
    portfolio["target_n"] = int(meta.get("target_n", len(portfolio)))
    portfolio["weight_cap"] = float(meta.get("weight_cap", cfg_port.stock_weight_max))
    portfolio["cash_target"] = float(meta.get("cash_target", 0.0))
    portfolio["prev_holdings_applied"] = bool(prev_holdings_applied)
    portfolio["prev_holdings_count"] = int(prev_holdings_count)
    portfolio["rebalance_action"] = "full_rebalance"
    portfolio["active_rebalance_interval_months"] = int(prev_interval_months if prev_holdings_applied else max(cfg.rebalance_interval_months, 1))
    portfolio["scheduled_rebalance_due"] = True
    portfolio = apply_sleeve_rebalance_interval_columns(portfolio, cfg)
    portfolio = portfolio.sort_values("weight", ascending=False).reset_index(drop=True)
    portfolio.insert(0, "rank", np.arange(1, len(portfolio) + 1))
    return portfolio


def update_operational_tracking(
    cfg: EngineConfig,
    paths: dict[str, Path],
    top30_operational: pd.DataFrame,
    portfolio_operational: pd.DataFrame,
    research_top30_operational: pd.DataFrame,
    research_portfolio_operational: pd.DataFrame,
    acceptance_checks: dict[str, Any],
    backtest: BacktestResult,
    best_rebalance_interval: dict[str, Any],
    next_run_recommendation: dict[str, Any],
) -> dict[str, str]:
    ops_dir = paths["ops"]
    safe_mkdir(ops_dir)
    decision_path = ops_dir / "portfolio_decision_history.parquet"
    holdings_path = ops_dir / "portfolio_holdings_history.parquet"
    recommendations_path = ops_dir / "top30_recommendation_history.parquet"
    realized_path = ops_dir / "portfolio_realized_performance.parquet"

    active_portfolio = portfolio_operational.copy() if portfolio_operational is not None and not portfolio_operational.empty else research_portfolio_operational.copy()
    active_top30 = top30_operational.copy() if top30_operational is not None and not top30_operational.empty else research_top30_operational.copy()
    portfolio_kind = "operational" if portfolio_operational is not None and not portfolio_operational.empty else "research_only"
    latest_dt = pd.to_datetime(active_top30["rebalance_date"], errors="coerce").max() if (not active_top30.empty and "rebalance_date" in active_top30.columns) else pd.NaT
    if pd.isna(latest_dt) and not active_portfolio.empty and "rebalance_date" in active_portfolio.columns:
        latest_dt = pd.to_datetime(active_portfolio["rebalance_date"], errors="coerce").max()
    run_timestamp = datetime.utcnow().isoformat(timespec="seconds")

    def _first_numeric(frame: pd.DataFrame, column: str, default: float = np.nan) -> float:
        if frame is None or frame.empty or column not in frame.columns:
            return float(default)
        values = pd.to_numeric(frame[column], errors="coerce").dropna()
        return float(values.iloc[0]) if not values.empty else float(default)

    def _max_numeric(frame: pd.DataFrame, column: str, default: float = 0.0) -> float:
        if frame is None or frame.empty or column not in frame.columns:
            return float(default)
        values = pd.to_numeric(frame[column], errors="coerce").dropna()
        return float(values.max()) if not values.empty else float(default)

    selected_n = 0
    cash_weight = 0.0
    target_n = 0
    weight_cap = np.nan
    cash_target = 0.0
    prev_holdings_applied = False
    prev_holdings_count = 0
    rebalance_action = str(next_run_recommendation.get("next_rebalance_action", "rebalance"))
    active_rebalance_interval_months = int(
        next_run_recommendation.get(
            "active_rebalance_interval_months",
            best_rebalance_interval.get("rebalance_interval_months", getattr(cfg, "rebalance_interval_months", 1)),
        )
    )
    scheduled_rebalance_due = bool(next_run_recommendation.get("policy_rebalance_due", True))
    adaptive_active = False
    adaptive_history_months = 0
    sleeve_actual_weights = {"core_compounder": 0.0, "future_winner": 0.0, "early_scout": 0.0}
    sleeve_selected_counts = {"core_compounder": 0, "future_winner": 0, "early_scout": 0}
    sleeve_target_core = 0.0
    sleeve_target_future = 0.0
    sleeve_target_early = 0.0
    future_regime_strength = 0.0
    early_regime_strength = 0.0
    sleeve_growth_signal = 0.0
    sleeve_risk_signal = 0.0
    if not active_portfolio.empty:
        tickers = active_portfolio.get("ticker", pd.Series(dtype=object)).astype(str).str.upper()
        selected_n = int(tickers.ne(CASH_PROXY_TICKER).sum())
        cash_weight = float(pd.to_numeric(active_portfolio.loc[tickers.eq(CASH_PROXY_TICKER), "weight"], errors="coerce").fillna(0.0).sum())
        target_n = int(_first_numeric(active_portfolio, "target_n", default=0.0))
        weight_cap = _first_numeric(active_portfolio, "weight_cap", default=np.nan)
        cash_target = _first_numeric(active_portfolio, "cash_target", default=0.0)
        prev_holdings_applied = bool(active_portfolio.get("prev_holdings_applied", pd.Series(dtype=bool)).fillna(False).astype(bool).any())
        prev_holdings_count = int(_max_numeric(active_portfolio, "prev_holdings_count", default=0.0))
        if "rebalance_action" in active_portfolio.columns:
            action_mode = active_portfolio["rebalance_action"].dropna().astype(str).mode()
            if not action_mode.empty:
                rebalance_action = str(action_mode.iloc[0])
        active_rebalance_interval_months = int(
            _first_numeric(
                active_portfolio,
                "active_rebalance_interval_months",
                default=float(active_rebalance_interval_months),
            )
        )
        if "scheduled_rebalance_due" in active_portfolio.columns:
            scheduled_rebalance_due = bool(active_portfolio["scheduled_rebalance_due"].fillna(True).astype(bool).all())
        adaptive_active = bool(active_portfolio.get("adaptive_ensemble_active", pd.Series(dtype=bool)).fillna(False).astype(bool).any())
        adaptive_history_months = int(_max_numeric(active_portfolio, "adaptive_ensemble_history_months", default=0.0))
        stock_only = active_portfolio[tickers.ne(CASH_PROXY_TICKER)].copy()
        if not stock_only.empty and "portfolio_sleeve_label" in stock_only.columns and "weight" in stock_only.columns:
            grouped = (
                stock_only.assign(
                    portfolio_sleeve_label=stock_only["portfolio_sleeve_label"].fillna("core_compounder").astype(str)
                )
                .groupby("portfolio_sleeve_label")["weight"]
                .sum()
            )
            sleeve_actual_weights = {
                "core_compounder": float(grouped.get("core_compounder", 0.0)),
                "future_winner": float(grouped.get("future_winner", 0.0)),
                "early_scout": float(grouped.get("early_scout", 0.0)),
            }
            sleeve_selected_counts = {
                "core_compounder": int(stock_only["portfolio_sleeve_label"].fillna("core_compounder").astype(str).eq("core_compounder").sum()),
                "future_winner": int(stock_only["portfolio_sleeve_label"].fillna("core_compounder").astype(str).eq("future_winner").sum()),
                "early_scout": int(stock_only["portfolio_sleeve_label"].fillna("core_compounder").astype(str).eq("early_scout").sum()),
            }
        sleeve_target_core = _first_numeric(active_portfolio, "sleeve_target_core_compounder_weight", default=0.0)
        sleeve_target_future = _first_numeric(active_portfolio, "sleeve_target_future_winner_weight", default=0.0)
        sleeve_target_early = _first_numeric(active_portfolio, "sleeve_target_early_scout_weight", default=0.0)
        future_regime_strength = _first_numeric(active_portfolio, "future_winner_regime_strength", default=0.0)
        early_regime_strength = _first_numeric(active_portfolio, "early_scout_regime_strength", default=0.0)
        sleeve_growth_signal = _first_numeric(active_portfolio, "sleeve_growth_signal", default=0.0)
        sleeve_risk_signal = _first_numeric(active_portfolio, "sleeve_risk_signal", default=0.0)

    decision_row = pd.DataFrame(
        [
            {
                "run_timestamp_utc": run_timestamp,
                "portfolio_kind": portfolio_kind,
                "rebalance_date": str(pd.Timestamp(latest_dt).date()) if pd.notna(latest_dt) else None,
                "backtest_usable": bool(acceptance_checks.get("backtest_usable", False)),
                "research_only_backtest": bool(acceptance_checks.get("backtest_research_only", False)),
                "selected_n": int(selected_n),
                "cash_weight": float(cash_weight),
                "target_n": int(target_n),
                "weight_cap": float(weight_cap) if pd.notna(weight_cap) else None,
                "cash_target": float(cash_target),
                "sleeve_target_core_compounder_weight": float(sleeve_target_core),
                "sleeve_target_future_winner_weight": float(sleeve_target_future),
                "sleeve_target_early_scout_weight": float(sleeve_target_early),
                "sleeve_actual_core_compounder_weight": float(sleeve_actual_weights.get("core_compounder", 0.0)),
                "sleeve_actual_future_winner_weight": float(sleeve_actual_weights.get("future_winner", 0.0)),
                "sleeve_actual_early_scout_weight": float(sleeve_actual_weights.get("early_scout", 0.0)),
                "sleeve_selected_core_compounder_count": int(sleeve_selected_counts.get("core_compounder", 0)),
                "sleeve_selected_future_winner_count": int(sleeve_selected_counts.get("future_winner", 0)),
                "sleeve_selected_early_scout_count": int(sleeve_selected_counts.get("early_scout", 0)),
                "future_winner_regime_strength": float(future_regime_strength),
                "early_scout_regime_strength": float(early_regime_strength),
                "sleeve_growth_signal": float(sleeve_growth_signal),
                "sleeve_risk_signal": float(sleeve_risk_signal),
                "prev_holdings_applied": bool(prev_holdings_applied),
                "prev_holdings_count": int(prev_holdings_count),
                "rebalance_action": str(rebalance_action),
                "active_rebalance_interval_months": int(active_rebalance_interval_months),
                "scheduled_rebalance_due": bool(scheduled_rebalance_due),
                "adaptive_ensemble_active": bool(adaptive_active),
                "adaptive_ensemble_history_months": int(adaptive_history_months),
                "rebalance_interval_months": int(backtest.metrics.get("rebalance_interval_months", getattr(cfg, "rebalance_interval_months", 1))),
                "adaptive_rebalance_policy": bool(backtest.metrics.get("adaptive_rebalance_policy", False)),
                "avg_rebalance_interval_months": float(backtest.metrics.get("avg_rebalance_interval_months", np.nan)),
                "rebalance_count": int(backtest.metrics.get("rebalance_count", 0)),
                "rebalanced_month_ratio": float(backtest.metrics.get("rebalanced_month_ratio", np.nan)),
                "recommended_rebalance_interval_months": int(best_rebalance_interval.get("rebalance_interval_months", getattr(cfg, "rebalance_interval_months", 1))),
                "next_scheduled_rebalance_date": next_run_recommendation.get("next_scheduled_rebalance_date"),
                "recommended_next_run_date": next_run_recommendation.get("recommended_next_run_date"),
                "recommended_next_run_mode": next_run_recommendation.get("recommended_next_run_mode"),
                "oos_cagr": float(backtest.metrics.get("cagr", np.nan)),
                "oos_excess_cagr": float(backtest.metrics.get("excess_cagr", np.nan)),
                "oos_ir": float(backtest.metrics.get("ir", np.nan)),
                "oos_max_dd": float(backtest.metrics.get("max_dd", np.nan)),
                "oos_avg_turnover_monthly": float(backtest.metrics.get("avg_turnover_monthly", np.nan)),
                "top_tickers": ",".join(active_portfolio.get("ticker", pd.Series(dtype=object)).astype(str).head(10).tolist()),
            }
        ]
    )
    append_history_parquet(
        decision_path,
        decision_row,
        dedupe_subset=["run_timestamp_utc", "portfolio_kind"],
        sort_columns=["rebalance_date", "run_timestamp_utc", "portfolio_kind"],
    )

    if not active_portfolio.empty:
        holdings_frame = active_portfolio.copy()
        holdings_frame["run_timestamp_utc"] = run_timestamp
        holdings_frame["portfolio_kind"] = portfolio_kind
        holdings_frame["recommended_rebalance_interval_months"] = int(best_rebalance_interval.get("rebalance_interval_months", getattr(cfg, "rebalance_interval_months", 1)))
        holdings_frame["current_rebalance_interval_months"] = int(backtest.metrics.get("rebalance_interval_months", getattr(cfg, "rebalance_interval_months", 1)))
        append_history_parquet(
            holdings_path,
            holdings_frame,
            dedupe_subset=["run_timestamp_utc", "portfolio_kind", "ticker"],
            sort_columns=["rebalance_date", "run_timestamp_utc", "portfolio_kind", "rank"],
        )

    if not active_top30.empty:
        recommendations_frame = active_top30.copy()
        recommendations_frame["run_timestamp_utc"] = run_timestamp
        recommendations_frame["portfolio_kind"] = portfolio_kind
        recommendations_frame["recommended_rebalance_interval_months"] = int(best_rebalance_interval.get("rebalance_interval_months", getattr(cfg, "rebalance_interval_months", 1)))
        append_history_parquet(
            recommendations_path,
            recommendations_frame,
            dedupe_subset=["run_timestamp_utc", "portfolio_kind", "ticker"],
            sort_columns=["rebalance_date", "run_timestamp_utc", "portfolio_kind", "rank"],
        )

    refresh_operational_realized_history(cfg, paths, as_of_date=latest_dt if pd.notna(latest_dt) else None)
    return {
        "portfolio_decision_history": str(decision_path),
        "portfolio_holdings_history": str(holdings_path),
        "top30_recommendation_history": str(recommendations_path),
        "portfolio_realized_performance": str(realized_path),
    }


def export_outputs(cfg: dict | EngineConfig, artifacts: dict[str, Any]) -> dict[str, str]:
    cfg = to_cfg(cfg)
    paths = get_paths(cfg)
    model_features = model_feature_columns(cfg)
    log("Phase 6: exporting outputs ...")

    def _artifact_frame(name: str) -> pd.DataFrame:
        value = artifacts.get(name)
        if value is None:
            return pd.DataFrame()
        if isinstance(value, pd.DataFrame):
            return value.copy()
        return pd.DataFrame(value).copy()

    scored = artifacts["scored"].copy()
    bt: BacktestResult = artifacts["backtest"]
    model_bundle: ModelBundle = artifacts["model_bundle"]
    current_scored = artifacts.get("latest_recommendations")
    current_portfolio = artifacts.get("latest_portfolio")
    research_only_portfolio_artifact = artifacts.get("research_only_portfolio")
    acceptance_checks = artifacts.get("acceptance_checks", {})
    raw_sleeve_cap_policy_compare = artifacts.get("sleeve_cap_policy_compare")
    sleeve_cap_policy_compare = _artifact_frame("sleeve_cap_policy_compare")
    selected_sleeve_cap_policy = dict(artifacts.get("selected_sleeve_cap_policy") or {})
    sleeve_regime_grid = _artifact_frame("sleeve_regime_grid")
    sleeve_regime_best = _artifact_frame("sleeve_regime_best")
    regime_sleeve_method_compare = _artifact_frame("regime_sleeve_method_compare")
    manual_regime_conditioned_sleeve_map = dict(artifacts.get("manual_regime_conditioned_sleeve_map") or {})
    if isinstance(raw_sleeve_cap_policy_compare, pd.DataFrame):
        if sleeve_regime_grid.empty:
            attr_grid = raw_sleeve_cap_policy_compare.attrs.get("sleeve_regime_grid")
            if isinstance(attr_grid, pd.DataFrame) and not attr_grid.empty:
                sleeve_regime_grid = attr_grid.copy()
        if sleeve_regime_best.empty:
            attr_best = raw_sleeve_cap_policy_compare.attrs.get("sleeve_regime_best")
            if isinstance(attr_best, pd.DataFrame) and not attr_best.empty:
                sleeve_regime_best = attr_best.copy()
        if regime_sleeve_method_compare.empty:
            attr_method_compare = raw_sleeve_cap_policy_compare.attrs.get("regime_sleeve_method_compare")
            if isinstance(attr_method_compare, pd.DataFrame) and not attr_method_compare.empty:
                regime_sleeve_method_compare = attr_method_compare.copy()
        if not manual_regime_conditioned_sleeve_map:
            manual_regime_conditioned_sleeve_map = dict(
                raw_sleeve_cap_policy_compare.attrs.get("manual_regime_conditioned_sleeve_map", {}) or {}
            )
    standalone_sleeve_compare = _artifact_frame("standalone_sleeve_compare")
    standalone_sleeve_monthly = _artifact_frame("standalone_sleeve_monthly")
    standalone_sleeve_holdings = _artifact_frame("standalone_sleeve_holdings")
    concentrated_compare = _artifact_frame("concentrated_compare")
    concentrated_monthly = _artifact_frame("concentrated_monthly")
    concentrated_holdings = _artifact_frame("concentrated_holdings")
    ai_four_sleeve_compare = _artifact_frame("ai_four_sleeve_compare")
    ai_four_sleeve_regime_grid = _artifact_frame("ai_four_sleeve_regime_grid")
    ai_four_sleeve_regime_best = _artifact_frame("ai_four_sleeve_regime_best")
    ai_four_sleeve_selected_map = dict(artifacts.get("ai_four_sleeve_selected_map") or {})

    if current_scored is None or current_scored.empty:
        latest_dt = pd.to_datetime(scored["rebalance_date"], errors="coerce").max()
        scored_latest = scored[scored["rebalance_date"] == latest_dt].sort_values("score", ascending=False).copy()
    else:
        current_scored = current_scored.copy()
        current_scored["rebalance_date"] = pd.to_datetime(current_scored["rebalance_date"], errors="coerce")
        latest_dt = current_scored["rebalance_date"].max()
        scored_latest = current_scored[current_scored["rebalance_date"] == latest_dt].sort_values("score", ascending=False).copy()
    scored_latest = normalize_latest_fundamental_snapshot(
        cfg,
        paths,
        scored_latest,
        clear_latest_only_signals=False,
        apply_statement_repair=True,
        add_fundamental_flags=True,
    )
    scored_latest = compute_portfolio_sleeve_columns(scored_latest, cfg)
    scored_latest = apply_latest_ranking_eligibility(
        scored_latest,
        cfg,
        context="Phase 6 latest export ranking",
    )
    scored_latest = apply_sleeve_rebalance_interval_columns(scored_latest, cfg)
    full_rank = scored_latest[scored_latest["ranking_eligible"].fillna(False)].copy()
    partial_watchlist = scored_latest[~scored_latest["ranking_eligible"].fillna(False)].copy()
    full_rank = full_rank.sort_values("score", ascending=False).reset_index(drop=True)
    partial_watchlist = partial_watchlist.sort_values("score", ascending=False).reset_index(drop=True)

    def _normalize_portfolio_frame(frame: Any) -> pd.DataFrame:
        if frame is None:
            return pd.DataFrame(
                columns=["rank", "ticker", "Name", "sector", "weight", "selected_for_portfolio", "rebalance_date"]
            )
        out = pd.DataFrame(frame).copy()
        if "rebalance_date" in out.columns:
            out["rebalance_date"] = pd.to_datetime(out["rebalance_date"], errors="coerce")
            out = out[out["rebalance_date"] == latest_dt].copy()
        if out.empty:
            return out
        enrich_cols = [
            "ticker",
            "score",
            "score_total",
            "score_pre_focus_total",
            "score_base_model",
            "score_model_core",
            "portfolio_seed_score",
            "portfolio_alpha",
            "portfolio_sage_boost",
            "portfolio_utility",
            "score_strategy_blueprint",
            "ensemble_weight_linear",
            "ensemble_weight_catboost",
            "ensemble_weight_ranker",
            "adaptive_ensemble_active",
            "adaptive_ensemble_history_months",
            "adaptive_quality_linear",
            "adaptive_quality_catboost",
            "adaptive_quality_ranker",
            "score_garp_core",
            "score_focus_bonus",
            "garp_score",
            "archetype_alignment_score",
            "dominant_archetype_label",
            "future_winner_scout_score",
            "portfolio_sleeve_label",
            "portfolio_sleeve_confidence",
            "portfolio_core_compounder_engine_score",
            "portfolio_future_winner_engine_score",
            "portfolio_early_scout_engine_score",
            "sleeve_target_core_compounder_weight",
            "sleeve_target_future_winner_weight",
            "sleeve_target_early_scout_weight",
            "future_winner_regime_strength",
            "early_scout_regime_strength",
            "long_hold_compounder_score",
            "score_future_winner_model",
            "pred_future_winner_ret",
            "pred_future_winner_p",
            "sage_sector",
            "sage_composite_score",
            "sage_g_score",
            "sage_v_score",
            "sage_q_score",
            "sage_c_score",
            "fundamental_lane_label",
            "sector_adjusted_fields_present",
            "partial_scout_confirmation_score",
            "latest_statement_repair_used",
            "roa_proxy",
            "asset_turnover_ttm",
            "book_to_market_proxy",
            "capital_efficiency_score",
            "sector_adjusted_quality_score",
            "market_cap_live",
            "current_price_live",
            "return_on_equity_effective",
            "revenue_growth_final",
            "earnings_growth_final",
            "strategy_blueprint_score",
            "technical_blueprint_score",
            "revision_blueprint_score",
            "growth_blueprint_score",
            "valuation_blueprint_score",
            "moat_quality_blueprint_score",
            "ownership_flow_pillar_score",
            "fundamental_pillar_score",
            "technical_pillar_score",
            "event_revision_pillar_score",
            "macro_pillar_score",
            "compounder_pillar_score",
            "multidimensional_breadth_score",
            "held_from_prev_rebalance",
            "prev_weight",
            "portfolio_hold_policy_seed_bonus",
            "portfolio_hold_policy_bonus",
            "portfolio_hold_policy_support",
            "portfolio_hold_policy_exit_risk",
            "multidimensional_confirmation_score",
            "institutional_flow_actual_score",
            "insider_flow_actual_score",
            "institutional_flow_signal_score",
            "insider_flow_signal_score",
            "liquidity_impulse_score",
            "liquidity_drain_score",
            "fear_greed_score",
            "smh_rel_spy_1m",
            "dba_ret_1m",
            "macro_semis_cycle_interaction",
            "inflation_reacceleration_score",
            "upstream_cost_pressure_score",
            "labor_softening_score",
            "stagflation_score",
            "growth_liquidity_reentry_score",
            "rs_benchmark_3m",
            "rs_benchmark_6m",
            "rs_benchmark_12m",
            "defensive_rotation_score",
            "growth_reentry_score",
            "event_regime_label",
            "live_event_risk_score",
            "live_event_systemic_score",
            "live_event_war_oil_rate_score",
            "live_event_defensive_score",
            "live_event_growth_reentry_score",
            "live_event_alert_label",
            "overheat_penalty",
            "fund_join_status",
            "fundamental_presence_score",
            "fundamental_reliability_score",
            "core_fundamental_fields_present",
            "sector_adjusted_fields_present",
            "partial_scout_confirmation_score",
            "selection_confirmation_score",
            "selection_fundamental_confirmation_score",
            "selection_market_confirmation_score",
        ]
        enrich_cols = [c for c in enrich_cols if c in scored_latest.columns]
        if enrich_cols:
            enrich_map = scored_latest[enrich_cols].drop_duplicates("ticker")
            missing_cols = [c for c in enrich_map.columns if c != "ticker" and c not in out.columns]
            if missing_cols:
                out = out.merge(
                    enrich_map[["ticker"] + missing_cols],
                    on="ticker",
                    how="left",
                )
        if "raw_score" not in out.columns or pd.to_numeric(
            out.get("raw_score"), errors="coerce"
        ).isna().all():
            out["raw_score"] = pd.to_numeric(out.get("score"), errors="coerce")
        out = apply_sleeve_rebalance_interval_columns(out, cfg)
        return out.sort_values("weight", ascending=False).copy()

    def _annotate_output_frame(frame: pd.DataFrame, *, research_only_output: bool) -> pd.DataFrame:
        out = frame.copy()
        out["backtest_usable"] = bool(acceptance_checks.get("backtest_usable", False))
        out["research_only_backtest"] = bool(acceptance_checks.get("backtest_research_only", False))
        out["research_only_output"] = bool(research_only_output)
        return out

    def _build_top_table(rank_df: pd.DataFrame, portfolio_df: pd.DataFrame) -> pd.DataFrame:
        top = rank_df.copy()
        if not portfolio_df.empty and "ticker" in portfolio_df.columns and "weight" in portfolio_df.columns:
            top = top.merge(portfolio_df[["ticker", "weight"]], on="ticker", how="left")
        else:
            top["weight"] = 0.0
        top["weight"] = pd.to_numeric(top["weight"], errors="coerce").fillna(0.0)
        top["selected_for_portfolio"] = top["weight"] > 0
        top = dedupe_same_company_rows(
            top,
            score_col="score",
            selected_col="selected_for_portfolio",
        ).head(max(int(cfg.top_n), 30)).copy()
        top.insert(0, "rank", np.arange(1, len(top) + 1))
        return top

    def _build_explain_frame(base_df: pd.DataFrame) -> pd.DataFrame:
        explain_df = base_df.copy()
        if explain_df.empty:
            return explain_df
        for f in model_features:
            if f in explain_df.columns:
                z = robust_z(winsorize(explain_df[f], 0.01)).fillna(0.0)
                explain_df[f"contrib_{f}"] = float(coef.get(f, 0.0)) * z
        explain_df["contrib_score_model_core"] = numeric_series_or_default(explain_df, "score_model_core", 0.0)
        explain_df["contrib_score_quality_core"] = numeric_series_or_default(explain_df, "score_quality_core", 0.0)
        explain_df["contrib_score_event_core"] = numeric_series_or_default(explain_df, "score_event_core", 0.0)
        explain_df["contrib_score_garp_core"] = numeric_series_or_default(explain_df, "score_garp_core", 0.0)
        explain_df["contrib_score_anticipatory_growth"] = numeric_series_or_default(
            explain_df, "score_anticipatory_growth", 0.0
        )
        explain_df["contrib_score_archetype_mixture"] = numeric_series_or_default(
            explain_df, "score_archetype_mixture", 0.0
        )
        explain_df["contrib_score_future_winner_scout"] = numeric_series_or_default(
            explain_df, "score_future_winner_scout", 0.0
        )
        explain_df["contrib_score_future_winner_model"] = numeric_series_or_default(
            explain_df, "score_future_winner_model", 0.0
        )
        explain_df["contrib_score_strategy_blueprint"] = numeric_series_or_default(explain_df, "score_strategy_blueprint", 0.0)
        explain_df["contrib_score_fundamental_reliability_adjustment"] = numeric_series_or_default(
            explain_df, "score_fundamental_reliability_adjustment", 0.0
        )
        explain_df["contrib_score_missing_fundamental_penalty"] = -numeric_series_or_default(
            explain_df, "score_missing_fundamental_penalty", 0.0
        )
        explain_df["contrib_institutional_flow"] = cfg.w_institutional_flow * numeric_series_or_default(
            explain_df, "institutional_flow_signal_score", 0.0
        )
        explain_df["contrib_insider_flow"] = cfg.w_insider_flow * numeric_series_or_default(
            explain_df, "insider_flow_signal_score", 0.0
        )
        explain_df["contrib_multidimensional_confirmation"] = numeric_series_or_default(
            explain_df, "score_multidimensional_confirmation", 0.0
        )
        explain_df["contrib_actual_results"] = (
            cfg.w_actual_results
            * numeric_series_or_default(explain_df, "actual_priority_weight", 0.0)
            * numeric_series_or_default(explain_df, "actual_results_score", 0.0)
        )
        explain_df["contrib_focus_overlay"] = numeric_series_or_default(explain_df, "score_focus_bonus", 0.0)
        explain_df["contrib_sector_crowding_penalty"] = -numeric_series_or_default(explain_df, "sector_crowding_penalty", 0.0)
        explain_df["contrib_overheat_penalty"] = -numeric_series_or_default(explain_df, "overheat_penalty", 0.0)
        explain_df["contrib_portfolio_seed_overheat_penalty"] = -numeric_series_or_default(
            explain_df, "portfolio_seed_overheat_penalty", 0.0
        )
        explain_df["contrib_watchlist_quality_penalty"] = -numeric_series_or_default(
            explain_df, "watchlist_quality_penalty", 0.0
        )
        explain_df["contrib_rs_benchmark_6m"] = cross_sectional_robust_z(explain_df, "rs_benchmark_6m")
        explain_df["contrib_defensive_rotation_score"] = numeric_series_or_default(explain_df, "defensive_rotation_score", 0.0)
        explain_df["contrib_growth_reentry_score"] = numeric_series_or_default(explain_df, "growth_reentry_score", 0.0)
        explain_df["contrib_live_event_defensive_score"] = numeric_series_or_default(explain_df, "live_event_defensive_score", 0.0)
        explain_df["contrib_live_event_growth_reentry_score"] = numeric_series_or_default(explain_df, "live_event_growth_reentry_score", 0.0)
        explain_df["contrib_live_event_risk_penalty"] = -numeric_series_or_default(explain_df, "live_event_risk_score", 0.0)
        explain_df["contrib_forward_revision_satellite"] = numeric_series_or_default(
            explain_df, "score_forward_revision_satellite", 0.0
        )
        explain_df["contrib_flow_satellite"] = numeric_series_or_default(explain_df, "score_flow_satellite", 0.0)
        explain_df["score_live_overlay"] = numeric_series_or_default(explain_df, "score_live_overlay", 0.0)
        return explain_df

    def _build_operational_view(frame: pd.DataFrame, include_selected: bool = True) -> pd.DataFrame:
        out = frame.copy()
        if out.empty:
            return out
        cols = [
            "rank",
            "ticker",
            "Name",
            "sector",
            "weight",
            "selected_for_portfolio",
            "score",
            "score_model_core",
            "score_total",
            "score_focus_bonus",
            "portfolio_seed_score",
            "portfolio_alpha",
            "portfolio_sage_boost",
            "portfolio_utility",
            "ensemble_weight_linear",
            "ensemble_weight_catboost",
            "ensemble_weight_ranker",
            "adaptive_ensemble_active",
            "adaptive_ensemble_history_months",
            "adaptive_quality_linear",
            "adaptive_quality_catboost",
            "adaptive_quality_ranker",
            "anticipatory_growth_score",
            "profitability_inflection_score",
            "dominant_archetype_label",
            "archetype_alignment_score",
            "portfolio_sleeve_label",
            "portfolio_sleeve_confidence",
            "portfolio_core_compounder_engine_score",
            "portfolio_future_winner_engine_score",
            "portfolio_early_scout_engine_score",
            "sage_sector",
            "sage_composite_score",
            "sage_g_score",
            "sage_v_score",
            "sage_q_score",
            "sage_c_score",
            "sleeve_target_core_compounder_weight",
            "sleeve_target_future_winner_weight",
            "sleeve_target_early_scout_weight",
            "sleeve_invested_share",
            "sleeve_growth_signal",
            "sleeve_risk_signal",
            "future_winner_regime_strength",
            "early_scout_regime_strength",
            "future_winner_scout_score",
            "long_hold_compounder_score",
            "score_future_winner_model",
            "pred_future_winner_ret",
            "pred_future_winner_p",
            "strategy_blueprint_score",
            "stagflation_score",
            "growth_liquidity_reentry_score",
            "m2_yoy_lag1m",
            "fed_assets_bil",
            "reverse_repo_bil",
            "tga_bil",
            "net_liquidity_bil",
            "net_liquidity_change_1m_bil",
            "liquidity_impulse_score",
            "liquidity_drain_score",
            "fear_greed_score",
            "fear_greed_delta_1w",
            "fear_greed_risk_off_score",
            "fear_greed_risk_on_score",
            "fund_join_status",
            "fundamental_reliability_score",
            "core_fundamental_fields_present",
            "sector_adjusted_fields_present",
            "partial_scout_confirmation_score",
            "fundamental_lane_label",
            "latest_statement_repair_used",
            "revenues_ttm",
            "gross_profit_ttm",
            "op_income_ttm",
            "net_income_ttm",
            "op_margin_ttm",
            "gross_margins",
            "operating_margins",
            "roe_proxy",
            "roa_proxy",
            "asset_turnover_ttm",
            "book_to_market_proxy",
            "capital_efficiency_score",
            "sector_adjusted_quality_score",
            "market_cap_live",
            "current_price_live",
            "return_on_equity_effective",
            "revenue_growth_final",
            "earnings_growth_final",
            "forward_pe_final",
            "peg_final",
            "sales_growth_yoy",
            "net_income_growth_yoy",
            "op_income_growth_yoy",
            "ocf_growth_yoy",
            "sales_cagr_3y",
            "sales_cagr_5y",
            "net_income_cagr_3y",
            "net_income_cagr_5y",
            "op_income_cagr_3y",
            "op_income_cagr_5y",
            "ocf_cagr_3y",
            "ocf_cagr_5y",
            "ep_ttm",
            "sp_ttm",
            "fcfy_ttm",
            "price_above_ma20",
            "ma20_above_ma50",
            "golden_cross_fresh_20d",
            "death_cross_recent_20d",
            "breakout_fresh_20d",
            "breakout_volume_z",
            "volume_dryup_20d",
            "post_breakout_hold_score",
            "held_from_prev_rebalance",
            "prev_weight",
            "portfolio_hold_policy_seed_bonus",
            "portfolio_hold_policy_bonus",
            "portfolio_hold_policy_support",
            "portfolio_hold_policy_exit_risk",
            "target_n",
            "weight_cap",
            "cash_target",
            "prev_holdings_applied",
            "prev_holdings_count",
            "rebalance_action",
            "due_sleeves",
            "active_rebalance_interval_months",
            "sleeve_rebalance_interval_months",
            "scheduled_rebalance_due",
            "recommended_rebalance_interval_months",
            "next_scheduled_rebalance_date",
            "recommended_next_run_date",
            "recommended_next_run_mode",
            "atr14_pct",
            "event_regime_label",
            "live_event_alert_label",
            "applied_regime_sleeve_policy_label",
            "applied_regime_sleeve_live_label",
            "applied_regime_sleeve_source_label",
            "backtest_usable",
            "research_only_backtest",
            "research_only_output",
            # Phase 12A (2026-04-21): live-state columns enriched after this view
            "entry_date", "entry_price", "reference_price", "shares_held",
            "last_trade_date", "thesis_status", "manual_lock",
            "held_days", "unrealized_return",
        ]
        if not include_selected:
            cols = [c for c in cols if c != "selected_for_portfolio"]
        cols = [c for c in cols if c in out.columns]
        return out[cols].copy()

    def _enrich_with_live_state(frame: pd.DataFrame) -> pd.DataFrame:
        """Phase 12A (2026-04-21): merge live_portfolio_state.json positions into
        portfolio output frame. Adds: entry_date, entry_price (avg_cost),
        reference_price, last_trade_date, thesis_status, manual_lock,
        held_days, unrealized_return.

        Failsafe: if state JSON missing or ticker not in state, columns get NaN
        (so the new columns always exist for downstream consumers).
        """
        out = frame.copy()
        # Ensure columns exist even when state is empty/missing
        for col in ("entry_date", "last_trade_date", "thesis_status"):
            if col not in out.columns:
                out[col] = ""
        for col in ("entry_price", "reference_price", "shares_held",
                    "held_days", "unrealized_return"):
            if col not in out.columns:
                out[col] = np.nan
        if "manual_lock" not in out.columns:
            out["manual_lock"] = False
        if out.empty or "ticker" not in out.columns:
            return out
        try:
            from r1000_portfolio_state import load_live_portfolio_state, positions_frame_from_state
            state_payload = load_live_portfolio_state(paths)
            pos_df = positions_frame_from_state(state_payload)
        except Exception as exc:
            log(f"[Phase 12A] live state unavailable: {exc}")
            return out
        if pos_df is None or pos_df.empty:
            return out
        merge_cols = ["ticker", "shares", "avg_cost", "reference_price",
                      "entry_date", "last_trade_date", "manual_lock", "thesis_status"]
        merge_cols = [c for c in merge_cols if c in pos_df.columns]
        joined = out.merge(
            pos_df[merge_cols].rename(columns={"shares": "shares_held",
                                               "avg_cost": "entry_price"}),
            on="ticker", how="left", suffixes=("", "__live"),
        )
        # Prefer live values where available
        for live_col in ("entry_price", "reference_price", "shares_held",
                         "entry_date", "last_trade_date", "manual_lock", "thesis_status"):
            other = f"{live_col}__live"
            if other in joined.columns:
                if live_col in ("entry_price", "reference_price", "shares_held"):
                    joined[live_col] = pd.to_numeric(joined[other], errors="coerce").combine_first(
                        pd.to_numeric(joined.get(live_col), errors="coerce")
                    )
                elif live_col == "manual_lock":
                    joined[live_col] = joined[other].fillna(False).astype(bool)
                else:
                    joined[live_col] = joined[other].fillna(joined.get(live_col, "")).astype(str)
                joined = joined.drop(columns=[other])
        # Compute derived columns
        try:
            today = pd.Timestamp.utcnow().normalize()
            entry_dt = pd.to_datetime(joined["entry_date"], errors="coerce")
            joined["held_days"] = (today - entry_dt).dt.days
        except Exception:
            joined["held_days"] = np.nan
        # Unrealized return: prefer live current_price_live / market_cap-derived price
        cur_price_col = None
        for c in ("current_price_live", "px", "open_px", "reference_price"):
            if c in joined.columns and pd.to_numeric(joined[c], errors="coerce").notna().any():
                cur_price_col = c
                break
        if cur_price_col is not None:
            cur = pd.to_numeric(joined[cur_price_col], errors="coerce")
            ent = pd.to_numeric(joined["entry_price"], errors="coerce")
            joined["unrealized_return"] = (cur / ent - 1.0).where(ent > 0, np.nan)
        return joined

    def _build_lifetime_equity_curve(
        backtest_eq: pd.DataFrame,
        portfolio_frame: pd.DataFrame,
    ) -> tuple[pd.DataFrame, dict[str, Any]]:
        """Phase 12C (2026-04-21): extend backtest equity_curve.csv with live
        portfolio value snapshots so users see ONE continuous equity timeline
        from backtest start through today.

        Approach:
          1. Backtest equity (rebalance_date + equity column, 83 months) is the
             historical anchor. Last row's equity = baseline_eq, last date = anchor_date.
          2. Live extension: for each snapshot date AFTER anchor_date in
             live_portfolio_state_history.parquet, compute portfolio_value =
             sum(shares * current_reference_price). If shares/avg_cost are NaN
             (bootstrap state), live_equity stays at baseline_eq -- degenerate
             but consistent until user fills manual_positions.yaml.
          3. Output: lifetime_equity_curve.csv with two phases (backtest, live),
             plus lifetime_metrics dict (lifetime_cagr, lifetime_total_return,
             lifetime_years, anchor_date, live_only_return).
        """
        from r1000_portfolio_state import load_live_portfolio_state, positions_frame_from_state
        # Failsafe defaults
        meta = {
            "anchor_date": None,
            "anchor_equity": float(np.nan),
            "lifetime_cagr": float(np.nan),
            "lifetime_total_return": float(np.nan),
            "lifetime_years": float(np.nan),
            "live_only_return": float(np.nan),
            "live_only_days": 0,
            "live_value_method": "n/a",
        }
        if backtest_eq is None or backtest_eq.empty or "equity" not in backtest_eq.columns:
            return pd.DataFrame(), meta
        bt = backtest_eq.copy()
        bt["rebalance_date"] = pd.to_datetime(bt["rebalance_date"], errors="coerce")
        bt = bt.dropna(subset=["rebalance_date"]).sort_values("rebalance_date").reset_index(drop=True)
        if bt.empty:
            return pd.DataFrame(), meta
        anchor_date = bt["rebalance_date"].iloc[-1]
        anchor_eq = float(bt["equity"].iloc[-1])
        meta["anchor_date"] = str(anchor_date.date())
        meta["anchor_equity"] = anchor_eq

        # Build live extension rows
        live_rows: list[dict[str, Any]] = []
        try:
            state = load_live_portfolio_state(paths)
            pos_df = positions_frame_from_state(state)
        except Exception as exc:
            log(f"[Phase 12C] live state read failed: {exc}")
            pos_df = pd.DataFrame()

        # Compute live portfolio value: sum(shares * reference_price)
        live_value = anchor_eq
        live_method = "no_live_data"
        if not pos_df.empty:
            shares = pd.to_numeric(pos_df.get("shares"), errors="coerce")
            ref = pd.to_numeric(pos_df.get("reference_price"), errors="coerce")
            avg_cost = pd.to_numeric(pos_df.get("avg_cost"), errors="coerce")
            weight = pd.to_numeric(pos_df.get("weight"), errors="coerce").fillna(0.0)
            if shares.notna().any() and ref.notna().any():
                # Method A: shares × reference_price + cash
                holding_value = (shares.fillna(0.0) * ref.fillna(0.0)).sum()
                # Cash residual: assume initial book = sum(shares * avg_cost) when avail
                book = (shares.fillna(0.0) * avg_cost.fillna(0.0)).sum()
                if book > 0:
                    live_only_ret = (holding_value / book) - 1.0
                    live_value = anchor_eq * (1.0 + live_only_ret)
                    live_method = "shares_x_reference_price"
                    meta["live_only_return"] = float(live_only_ret)
            elif weight.sum() > 0 and ref.notna().any() and avg_cost.notna().any():
                # Method B: weighted return per ticker
                ret_per_t = (ref.fillna(0.0) / avg_cost.replace(0, np.nan) - 1.0).fillna(0.0)
                w = (weight / weight.sum()).fillna(0.0)
                live_only_ret = float((w * ret_per_t).sum())
                live_value = anchor_eq * (1.0 + live_only_ret)
                live_method = "weighted_ticker_returns"
                meta["live_only_return"] = float(live_only_ret)

        meta["live_value_method"] = live_method
        # Phase 12C: ensure tz-naive for comparison with backtest dates (which are tz-naive)
        as_of = pd.Timestamp.utcnow().tz_localize(None).normalize()
        anchor_date_naive = anchor_date.tz_localize(None) if anchor_date.tzinfo else anchor_date
        if as_of > anchor_date_naive and live_method != "no_live_data":
            live_rows.append({
                "rebalance_date": as_of,
                "equity": float(live_value),
                "equity_value_usd": float(live_value * 100000.0),
                "phase": "live",
            })
        # Tag backtest rows
        bt["phase"] = "backtest"
        # Compose lifetime
        lifetime_cols = ["rebalance_date", "equity", "equity_value_usd", "phase"]
        bt_subset = bt.reindex(columns=lifetime_cols)
        live_df = pd.DataFrame(live_rows)
        lifetime = pd.concat([bt_subset, live_df], ignore_index=True) if not live_df.empty else bt_subset
        lifetime["rebalance_date"] = pd.to_datetime(lifetime["rebalance_date"], errors="coerce")

        # Lifetime metrics
        if not lifetime.empty and lifetime["equity"].iloc[0] > 0:
            initial_eq = float(lifetime["equity"].iloc[0])
            final_eq = float(lifetime["equity"].iloc[-1])
            initial_dt = lifetime["rebalance_date"].iloc[0]
            final_dt = lifetime["rebalance_date"].iloc[-1]
            # Defensive tz strip
            initial_dt = initial_dt.tz_localize(None) if hasattr(initial_dt, 'tzinfo') and initial_dt.tzinfo else initial_dt
            final_dt = final_dt.tz_localize(None) if hasattr(final_dt, 'tzinfo') and final_dt.tzinfo else final_dt
            years = max((final_dt - initial_dt).days / 365.25, 1e-6)
            total_ret = (final_eq / initial_eq) - 1.0
            cagr = (final_eq / initial_eq) ** (1.0 / years) - 1.0 if final_eq > 0 else np.nan
            meta["lifetime_total_return"] = float(total_ret)
            meta["lifetime_cagr"] = float(cagr)
            meta["lifetime_years"] = float(years)
            if live_method != "no_live_data":
                meta["live_only_days"] = int((as_of - anchor_date_naive).days)
        return lifetime, meta

    coef = model_bundle.linear_feature_weights
    portfolio_latest = _normalize_portfolio_frame(current_portfolio)
    research_only_portfolio = _normalize_portfolio_frame(research_only_portfolio_artifact)
    portfolio_export_blocked = bool(
        cfg.require_acceptance_for_portfolio_export and not acceptance_checks.get("backtest_usable", False)
    )

    if portfolio_export_blocked:
        log("[WARN] Acceptance hard gate active: operational top30/portfolio exports blocked because backtest_usable=False.")
        top30 = _build_top_table(full_rank.iloc[0:0].copy(), pd.DataFrame())
        portfolio_latest = portfolio_latest.iloc[0:0].copy()
        research_only_top30 = _build_top_table(full_rank, research_only_portfolio)
    else:
        top30 = _build_top_table(full_rank, portfolio_latest)
        research_only_top30 = _build_top_table(full_rank.iloc[0:0].copy(), pd.DataFrame())
        research_only_portfolio = research_only_portfolio.iloc[0:0].copy()

    full_rank = _annotate_output_frame(full_rank, research_only_output=portfolio_export_blocked)
    partial_watchlist = _annotate_output_frame(partial_watchlist, research_only_output=True)
    top30 = _annotate_output_frame(top30, research_only_output=False)
    portfolio_latest = _annotate_output_frame(portfolio_latest, research_only_output=False)
    research_only_top30 = _annotate_output_frame(research_only_top30, research_only_output=True)
    research_only_portfolio = _annotate_output_frame(research_only_portfolio, research_only_output=True)
    top30_operational = _build_operational_view(top30, include_selected=True)
    portfolio_operational = _build_operational_view(portfolio_latest, include_selected=False)
    research_top30_operational = _build_operational_view(research_only_top30, include_selected=True)
    research_portfolio_operational = _build_operational_view(research_only_portfolio, include_selected=False)
    # Phase 12A (2026-04-21): enrich portfolio_latest with live state (entry_date,
    # entry_price, held_days, unrealized_return). User sees buy info directly
    # in portfolio_latest.csv instead of digging through ops/live_*.parquet.
    portfolio_operational = _enrich_with_live_state(portfolio_operational)
    research_portfolio_operational = _enrich_with_live_state(research_portfolio_operational)

    top30_path = paths["out"] / "top30_latest.csv"
    top20_path = paths["out"] / "top20_latest.csv"
    portfolio_path = paths["out"] / "portfolio_latest.csv"
    concentrated_portfolio_path = paths["out"] / "concentrated_portfolio_latest.csv"
    concentrated_top1_path = paths["out"] / "concentrated_top1_latest.csv"
    full_rank_path = paths["out"] / "full_fundamental_rank_latest.csv"
    partial_watchlist_path = paths["out"] / "partial_data_watchlist_latest.csv"
    research_top30_path = paths["out"] / "research_only_top30_latest.csv"
    research_portfolio_path = paths["out"] / "research_only_portfolio_latest.csv"
    scored_path = paths["out"] / "scored_latest.csv"
    weights_path = paths["out"] / "weights_latest.json"
    bt_metrics_path = paths["out"] / "backtest_metrics.json"
    concentrated_metrics_path = paths["out"] / "concentrated_backtest_metrics.json"
    concentrated_operating_guide_path = paths["out"] / "concentrated_operating_guide.json"
    equity_path = paths["out"] / "equity_curve.csv"
    summary_path = paths["out"] / "run_summary.json"
    ranking_path = paths["reports"] / "ranking_quality.json"
    benchmark_compare_path = paths["reports"] / "benchmark_comparison_latest.json"
    portfolio_size_compare_path = paths["reports"] / "portfolio_size_comparison.csv"
    rebalance_interval_compare_path = paths["reports"] / "rebalance_interval_comparison.csv"
    backtest_window_compare_path = paths["reports"] / "backtest_window_comparison.csv"
    sleeve_regime_grid_path = paths["reports"] / "sleeve_policy_per_regime_grid.csv"
    sleeve_regime_best_path = paths["reports"] / "sleeve_policy_per_regime_best.csv"
    regime_sleeve_method_compare_path = paths["reports"] / "regime_sleeve_map_method_comparison.csv"
    fund_panel_flow_path = paths["reports"] / "fund_panel_recent4q_flow_coverage.csv"
    fund_join_diag_path = paths["reports"] / "fundamental_join_latest_diagnostics.csv"
    fund_collection_audit_path = paths["reports"] / "fundamental_collection_audit.json"
    fund_collection_missing_path = paths["reports"] / "fundamental_collection_missing_latest.csv"
    fund_panel_snapshot_path = paths["reports"] / "fundamental_panel_latest_snapshot.csv"
    universe_change_summary_path = paths["reports"] / "candidate_universe_change_latest.json"
    universe_change_detail_path = paths["reports"] / "candidate_universe_change_latest.csv"
    market_adaptation_path = paths["reports"] / "market_adaptation_latest.json"
    event_alert_path = paths["reports"] / "event_alert_latest.json"
    macro_regime_path = paths["feature_store"] / "macro_regime_latest.parquet"
    explain_path = paths["out"] / "top30_explain_latest.csv"
    research_explain_path = paths["out"] / "research_only_top30_explain_latest.csv"
    latest_sleeve_standalone_holdings_path = paths["out"] / "latest_sleeve_standalone_holdings.csv"
    latest_sleeve_standalone_summary_path = paths["reports"] / "latest_sleeve_standalone_summary.csv"
    latest_core_standalone_path = paths["out"] / "core_compounder_latest_standalone.csv"
    latest_future_standalone_path = paths["out"] / "future_winner_latest_standalone.csv"
    latest_early_standalone_path = paths["out"] / "early_scout_latest_standalone.csv"
    engine_diagnostics_monthly_path = paths["reports"] / "engine_diagnostics_by_month.csv"
    engine_diagnostics_summary_path = paths["reports"] / "engine_diagnostics_summary.csv"
    ai_four_sleeve_compare_path = paths["reports"] / "ai_four_sleeve_adaptive_comparison.csv"
    ai_four_sleeve_regime_grid_path = paths["reports"] / "ai_four_sleeve_adaptive_regime_grid.csv"
    ai_four_sleeve_regime_best_path = paths["reports"] / "ai_four_sleeve_adaptive_regime_best.csv"
    ai_four_sleeve_selected_map_path = paths["reports"] / "ai_four_sleeve_adaptive_selected_map.json"
    run_identity = build_run_identity(cfg)

    def _safe_unlink(path: Path) -> None:
        try:
            if path.exists():
                path.unlink()
        except Exception:
            pass

    top30_operational.to_csv(top30_path, index=False)
    top30_operational.head(20).to_csv(top20_path, index=False)
    portfolio_operational.to_csv(portfolio_path, index=False)
    scored_latest.to_csv(scored_path, index=False)
    if bool(cfg.export_extended_outputs):
        full_rank.to_csv(full_rank_path, index=False)
        partial_watchlist.to_csv(partial_watchlist_path, index=False)
        research_top30_operational.to_csv(research_top30_path, index=False)
        research_portfolio_operational.to_csv(research_portfolio_path, index=False)
    else:
        for path in [
            full_rank_path,
            partial_watchlist_path,
            research_top30_path,
            research_portfolio_path,
        ]:
            _safe_unlink(path)

    latest_standalone_sleeve_holdings, latest_standalone_sleeve_summary = build_latest_standalone_sleeve_holdings(
        cfg,
        scored_latest,
        standalone_compare=standalone_sleeve_compare,
        current_portfolio=portfolio_latest,
    )
    if not latest_standalone_sleeve_holdings.empty:
        latest_standalone_sleeve_holdings.to_csv(latest_sleeve_standalone_holdings_path, index=False)
        if "sleeve_test" in latest_standalone_sleeve_holdings.columns:
            sleeve_test = latest_standalone_sleeve_holdings["sleeve_test"].fillna("").astype(str)
            latest_standalone_sleeve_holdings.loc[
                sleeve_test.eq("core_compounder")
            ].to_csv(latest_core_standalone_path, index=False)
            latest_standalone_sleeve_holdings.loc[
                sleeve_test.eq("future_winner")
            ].to_csv(latest_future_standalone_path, index=False)
            latest_standalone_sleeve_holdings.loc[
                sleeve_test.eq("early_scout")
            ].to_csv(latest_early_standalone_path, index=False)
        else:
            pd.DataFrame().to_csv(latest_core_standalone_path, index=False)
            pd.DataFrame().to_csv(latest_future_standalone_path, index=False)
            pd.DataFrame().to_csv(latest_early_standalone_path, index=False)
    else:
        _safe_unlink(latest_sleeve_standalone_holdings_path)
        _safe_unlink(latest_core_standalone_path)
        _safe_unlink(latest_future_standalone_path)
        _safe_unlink(latest_early_standalone_path)
    if not latest_standalone_sleeve_summary.empty:
        latest_standalone_sleeve_summary.to_csv(latest_sleeve_standalone_summary_path, index=False)
    else:
        _safe_unlink(latest_sleeve_standalone_summary_path)

    concentrated_latest_holdings, concentrated_latest_summary = build_latest_concentrated_holdings(
        cfg,
        scored_latest,
        concentrated_compare=concentrated_compare,
    )
    if not concentrated_latest_holdings.empty:
        concentrated_latest_holdings.to_csv(concentrated_portfolio_path, index=False)
        concentrated_top1_path.write_text(
            concentrated_latest_holdings.head(1).to_csv(index=False),
            encoding="utf-8",
        )
    else:
        _safe_unlink(concentrated_portfolio_path)
        _safe_unlink(concentrated_top1_path)
    concentrated_metrics_payload = {
        str(k): v
        for k, v in dict(concentrated_latest_summary or {}).items()
    }
    concentrated_metrics_path.write_text(json.dumps(concentrated_metrics_payload, indent=2), encoding="utf-8")
    concentrated_operating_guide_path.write_text(
        json.dumps(
            {
                "portfolio_mode": "concentrated_alpha",
                "latest_summary": concentrated_metrics_payload,
                "operating_principles": [
                    "Use this as a separate high-conviction sleeve from the main diversified portfolio.",
                    "Default cadence: monthly full rebalance.",
                    f"Monitoring cadence: every {int(getattr(cfg, 'concentrated_monitoring_review_days', 7))} days.",
                    "If top conviction materially changes, rotate within the concentrated sleeve rather than forcing changes into the main portfolio.",
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    # Persist live weights only after the rebalance policy recommendation is resolved.
    benchmark_compare = {
        "benchmark_source": str(bt.metrics.get("benchmark_source", benchmark_history_source_label(cfg))),
        "strategy_cagr": float(bt.metrics.get("cagr", np.nan)),
        "benchmark_cagr": float(bt.metrics.get("benchmark_cagr", np.nan)),
        "excess_cagr": float(bt.metrics.get("excess_cagr", np.nan)),
        "beat_month_ratio": float(bt.metrics.get("beat_month_ratio", np.nan)),
        "avg_cash_weight": float(bt.metrics.get("avg_cash_weight", 0.0)),
        "trade_cost_bps_per_side": float(bt.metrics.get("trade_cost_bps_per_side", np.nan)),
        "starting_capital_usd": float(bt.metrics.get("starting_capital_usd", np.nan)),
        "ending_capital_usd": float(bt.metrics.get("ending_capital_usd", np.nan)),
        "benchmark_ending_capital_usd": float(bt.metrics.get("benchmark_ending_capital_usd", np.nan)),
        "ir": float(bt.metrics.get("ir", np.nan)) if pd.notna(bt.metrics.get("ir", np.nan)) else np.nan,
    }
    benchmark_compare_path.write_text(json.dumps(benchmark_compare, indent=2))
    run_portfolio_size_compare = bool(getattr(cfg, "run_portfolio_size_comparison", cfg.run_comparison_backtests))
    run_rebalance_interval_compare = bool(
        getattr(cfg, "run_rebalance_interval_comparison", cfg.run_comparison_backtests)
    )
    run_backtest_window_compare = bool(
        getattr(cfg, "run_backtest_window_comparison", cfg.run_comparison_backtests)
    )
    if run_portfolio_size_compare:
        portfolio_size_compare = compare_portfolio_size_backtests(cfg, scored, cfg.portfolio_size_comparison_sizes)
        portfolio_size_compare.to_csv(portfolio_size_compare_path, index=False)
    else:
        portfolio_size_compare = pd.DataFrame()
        _safe_unlink(portfolio_size_compare_path)
    if run_rebalance_interval_compare:
        rebalance_interval_compare = compare_rebalance_interval_backtests(
            cfg,
            scored,
            cfg.rebalance_interval_comparison_months,
        )
        rebalance_interval_compare.to_csv(rebalance_interval_compare_path, index=False)
    else:
        rebalance_interval_compare = pd.DataFrame()
        _safe_unlink(rebalance_interval_compare_path)
    if run_backtest_window_compare:
        backtest_window_compare = compare_backtest_window_years(
            cfg,
            scored,
            cfg.backtest_window_comparison_years,
        )
        backtest_window_compare.to_csv(backtest_window_compare_path, index=False)
    else:
        backtest_window_compare = pd.DataFrame()
        _safe_unlink(backtest_window_compare_path)

    run_sleeve_regime_compare = bool(getattr(cfg, "run_sleeve_regime_comparison", False))
    sleeve_regime_cash_max = float(getattr(cfg, "sleeve_regime_comparison_cash_max", 0.02))
    if run_sleeve_regime_compare:
        if sleeve_regime_grid.empty and sleeve_regime_best.empty:
            log("Phase 5: running sleeve policy per-regime comparison ...")
            sleeve_regime_grid, sleeve_regime_best = compare_sleeve_policy_per_regime(
                cfg,
                scored,
                cash_target_max=sleeve_regime_cash_max,
            )
        if not sleeve_regime_grid.empty:
            sleeve_regime_grid.to_csv(sleeve_regime_grid_path, index=False)
        else:
            _safe_unlink(sleeve_regime_grid_path)
        if not sleeve_regime_best.empty:
            sleeve_regime_best.to_csv(sleeve_regime_best_path, index=False)
        else:
            _safe_unlink(sleeve_regime_best_path)
    else:
        sleeve_regime_grid = pd.DataFrame()
        sleeve_regime_best = pd.DataFrame()
        _safe_unlink(sleeve_regime_grid_path)
        _safe_unlink(sleeve_regime_best_path)
    run_regime_map_method_compare = bool(getattr(cfg, "run_regime_map_method_comparison", True))
    if run_regime_map_method_compare:
        if regime_sleeve_method_compare.empty:
            learned_map_for_compare = normalize_regime_conditioned_sleeve_map(
                dict(getattr(cfg, "regime_conditioned_sleeve_map", {}) or {}),
                fallback_source="learned",
            )
            manual_map_for_compare = normalize_regime_conditioned_sleeve_map(
                manual_regime_conditioned_sleeve_map or getattr(cfg, "manual_regime_conditioned_sleeve_map", {}) or default_manual_regime_conditioned_sleeve_map(),
                fallback_source="manual",
            )
            if learned_map_for_compare and manual_map_for_compare:
                log("Phase 5: running manual vs learned regime sleeve map comparison ...")
                regime_sleeve_method_compare = compare_regime_conditioned_sleeve_map_methods(
                    cfg,
                    scored,
                    learned_regime_map=learned_map_for_compare,
                    manual_regime_map=manual_map_for_compare,
                    cash_target_max=sleeve_regime_cash_max,
                )
        if not regime_sleeve_method_compare.empty:
            regime_sleeve_method_compare.to_csv(regime_sleeve_method_compare_path, index=False)
        else:
            _safe_unlink(regime_sleeve_method_compare_path)
    else:
        regime_sleeve_method_compare = pd.DataFrame()
        _safe_unlink(regime_sleeve_method_compare_path)

    regime_sleeve_method_best = (
        {str(k): _clean_json_scalar(v) for k, v in regime_sleeve_method_compare.iloc[0].to_dict().items()}
        if not regime_sleeve_method_compare.empty
        else {}
    )
    regime_sleeve_method_records = (
        [{str(k): _clean_json_scalar(v) for k, v in row.items()} for row in regime_sleeve_method_compare.to_dict(orient="records")]
        if not regime_sleeve_method_compare.empty
        else []
    )

    def _regime_method_snapshot(method_label: str) -> dict[str, Any]:
        if regime_sleeve_method_compare.empty or "method_label" not in regime_sleeve_method_compare.columns:
            return {}
        hit = regime_sleeve_method_compare[
            regime_sleeve_method_compare["method_label"].astype(str).eq(str(method_label))
        ]
        if hit.empty:
            return {}
        return {str(k): _clean_json_scalar(v) for k, v in hit.iloc[0].to_dict().items()}

    # Write sleeve cap policy comparison results (computed in run_all Phase 5c)
    sleeve_cap_policy_compare_path = paths["reports"] / "sleeve_cap_policy_comparison.csv"
    sleeve_cap_policy_champion_path = paths["reports"] / "sleeve_cap_policy_champion_latest.json"
    if bool(getattr(cfg, "run_sleeve_cap_policy_comparison", True)) and not sleeve_cap_policy_compare.empty:
        sleeve_cap_policy_compare.to_csv(sleeve_cap_policy_compare_path, index=False)
        sleeve_cap_policy_champion_path.write_text(
            json.dumps(selected_sleeve_cap_policy or {}, indent=2), encoding="utf-8"
        )
    else:
        _safe_unlink(sleeve_cap_policy_compare_path)
        _safe_unlink(sleeve_cap_policy_champion_path)

    # Write standalone sleeve top-N comparison results (computed in run_all Phase 5d)
    standalone_sleeve_compare_path = paths["reports"] / "portfolio_sleeve_top7_standalone_comparison.csv"
    standalone_sleeve_monthly_path = paths["reports"] / "portfolio_sleeve_top7_standalone_monthly.csv"
    standalone_sleeve_holdings_path = paths["reports"] / "portfolio_sleeve_top7_standalone_holdings.csv"
    concentrated_compare_path = paths["reports"] / "concentrated_strategy_comparison.csv"
    concentrated_monthly_path = paths["reports"] / "concentrated_strategy_monthly.csv"
    concentrated_holdings_path = paths["reports"] / "concentrated_strategy_holdings.csv"
    run_standalone_sleeve_compare = bool(getattr(cfg, "run_standalone_sleeve_backtest_comparison", True))
    if run_standalone_sleeve_compare and not standalone_sleeve_compare.empty:
        standalone_sleeve_compare.to_csv(standalone_sleeve_compare_path, index=False)
        standalone_sleeve_monthly.to_csv(standalone_sleeve_monthly_path, index=False)
        standalone_sleeve_holdings.to_csv(standalone_sleeve_holdings_path, index=False)
    else:
        _safe_unlink(standalone_sleeve_compare_path)
        _safe_unlink(standalone_sleeve_monthly_path)
        _safe_unlink(standalone_sleeve_holdings_path)
    if bool(getattr(cfg, "run_concentrated_backtest_comparison", True)) and not concentrated_compare.empty:
        concentrated_compare.to_csv(concentrated_compare_path, index=False)
        concentrated_monthly.to_csv(concentrated_monthly_path, index=False)
        concentrated_holdings.to_csv(concentrated_holdings_path, index=False)
    else:
        _safe_unlink(concentrated_compare_path)
        _safe_unlink(concentrated_monthly_path)
        _safe_unlink(concentrated_holdings_path)
    if bool(getattr(cfg, "run_ai_four_sleeve_comparison", True)) and not ai_four_sleeve_compare.empty:
        ai_four_sleeve_compare.to_csv(ai_four_sleeve_compare_path, index=False)
        ai_four_sleeve_regime_grid.to_csv(ai_four_sleeve_regime_grid_path, index=False)
        ai_four_sleeve_regime_best.to_csv(ai_four_sleeve_regime_best_path, index=False)
        ai_four_sleeve_selected_map_path.write_text(json.dumps(ai_four_sleeve_selected_map, indent=2), encoding="utf-8")
    else:
        _safe_unlink(ai_four_sleeve_compare_path)
        _safe_unlink(ai_four_sleeve_regime_grid_path)
        _safe_unlink(ai_four_sleeve_regime_best_path)
        _safe_unlink(ai_four_sleeve_selected_map_path)

    # Historical data quality reports (computed here since scored_latest is available)
    historical_quality_monthly_path = paths["reports"] / "historical_data_quality_by_month.csv"
    historical_quality_sleeve_path = paths["reports"] / "historical_data_quality_by_sleeve.csv"
    historical_quality_latest_path = paths["reports"] / "historical_data_quality_latest.csv"
    historical_quality_monthly = pd.DataFrame()
    historical_quality_sleeve = pd.DataFrame()
    historical_quality_latest = pd.DataFrame()
    if bool(getattr(cfg, "run_historical_data_quality_reports", True)):
        try:
            portfolio_for_dq = _normalize_portfolio_frame(current_portfolio)
            historical_quality_monthly, historical_quality_sleeve, historical_quality_latest = (
                build_historical_data_quality_report_frames(cfg, scored, scored_latest, portfolio_for_dq)
            )
            historical_quality_monthly.to_csv(historical_quality_monthly_path, index=False)
            historical_quality_sleeve.to_csv(historical_quality_sleeve_path, index=False)
            historical_quality_latest.to_csv(historical_quality_latest_path, index=False)
        except Exception as exc:
            log(f"[WARN] Historical data quality report failed: {exc}")
            _safe_unlink(historical_quality_monthly_path)
            _safe_unlink(historical_quality_sleeve_path)
            _safe_unlink(historical_quality_latest_path)
    else:
        _safe_unlink(historical_quality_monthly_path)
        _safe_unlink(historical_quality_sleeve_path)
        _safe_unlink(historical_quality_latest_path)

    engine_diagnostics_monthly = pd.DataFrame()
    engine_diagnostics_summary = pd.DataFrame()
    if bool(getattr(cfg, "run_engine_diagnostics_report", True)):
        try:
            engine_diagnostics_monthly, engine_diagnostics_summary = build_engine_diagnostics_report_frames(cfg, scored)
            engine_diagnostics_monthly.to_csv(engine_diagnostics_monthly_path, index=False)
            engine_diagnostics_summary.to_csv(engine_diagnostics_summary_path, index=False)
        except Exception as exc:
            log(f"[WARN] Engine diagnostics report failed: {exc}")
            _safe_unlink(engine_diagnostics_monthly_path)
            _safe_unlink(engine_diagnostics_summary_path)
    else:
        _safe_unlink(engine_diagnostics_monthly_path)
        _safe_unlink(engine_diagnostics_summary_path)

    if bool(cfg.export_extended_outputs):
        sector_exposure = (
            bt.holdings.groupby(["rebalance_date", "sector"])["weight"].sum().reset_index()
            if not bt.holdings.empty
            else pd.DataFrame(columns=["rebalance_date", "sector", "weight"])
        )
        sector_exposure.to_csv(paths["reports"] / "sector_exposure.csv", index=False)
    else:
        _safe_unlink(paths["reports"] / "sector_exposure.csv")

    if bool(cfg.export_explain_outputs):
        explain = _build_explain_frame(top30)
        research_explain = _build_explain_frame(research_only_top30)
        explain.to_csv(explain_path, index=False)
        research_explain.to_csv(research_explain_path, index=False)
    else:
        _safe_unlink(explain_path)
        _safe_unlink(research_explain_path)
    write_market_adaptation_report(paths, full_rank if not full_rank.empty else scored_latest, cfg)
    write_live_event_alert_report(cfg, paths)
    coverage_path = write_fundamental_coverage_report(paths, scored_latest)
    comprehensive_coverage_path = write_comprehensive_fundamental_coverage_report(paths, scored_latest)
    live_coverage_path = write_live_fundamental_coverage_report(paths, scored_latest)
    ranking_metrics = evaluate_ranking_quality(scored, score_col="score", target_col="y_blend", k=cfg.rank_eval_top_k)
    ranking_path.write_text(json.dumps(ranking_metrics, indent=2))
    latest_live_event_alert = "balanced"
    try:
        event_alert_payload = json.loads(event_alert_path.read_text(encoding="utf-8"))
        latest_live_event_alert = str(event_alert_payload.get("live_event_alert_label", "balanced"))
    except Exception:
        latest_live_event_alert = "balanced"
    previous_live_policy = load_previous_live_policy(paths, latest_dt=latest_dt)
    best_rebalance_interval = choose_best_rebalance_interval(
        rebalance_interval_compare,
        default_interval=int(getattr(cfg, "rebalance_interval_months", 1)),
        latest_frame=full_rank if not full_rank.empty else scored_latest,
        latest_live_event_alert=latest_live_event_alert,
        cfg=cfg,
    )
    next_run_recommendation = build_next_run_recommendation(
        cfg,
        latest_dt,
        latest_live_event_alert,
        int(best_rebalance_interval.get("rebalance_interval_months", getattr(cfg, "rebalance_interval_months", 1))),
        previous_live_policy=previous_live_policy,
    )

    def _apply_rebalance_policy_columns(frame: pd.DataFrame) -> pd.DataFrame:
        out = frame.copy()
        if out.empty:
            return out
        action_value = str(next_run_recommendation.get("next_rebalance_action", "rebalance"))
        out["recommended_rebalance_interval_months"] = int(
            best_rebalance_interval.get("rebalance_interval_months", getattr(cfg, "rebalance_interval_months", 1))
        )
        out["active_rebalance_interval_months"] = int(
            next_run_recommendation.get(
                "active_rebalance_interval_months",
                best_rebalance_interval.get("rebalance_interval_months", getattr(cfg, "rebalance_interval_months", 1)),
            )
        )
        out["scheduled_rebalance_due"] = bool(next_run_recommendation.get("policy_rebalance_due", True))
        out["next_scheduled_rebalance_date"] = next_run_recommendation.get("next_scheduled_rebalance_date")
        out["recommended_next_run_date"] = next_run_recommendation.get("recommended_next_run_date")
        out["recommended_next_run_mode"] = next_run_recommendation.get("recommended_next_run_mode")
        if "rebalance_action" not in out.columns:
            out["rebalance_action"] = action_value
        else:
            out["rebalance_action"] = out["rebalance_action"].replace("", np.nan).fillna(action_value)
        return out

    full_rank = _apply_rebalance_policy_columns(full_rank)
    partial_watchlist = _apply_rebalance_policy_columns(partial_watchlist)
    top30 = _apply_rebalance_policy_columns(top30)
    portfolio_latest = _apply_rebalance_policy_columns(portfolio_latest)
    research_only_top30 = _apply_rebalance_policy_columns(research_only_top30)
    research_only_portfolio = _apply_rebalance_policy_columns(research_only_portfolio)

    top30_operational = _build_operational_view(top30, include_selected=True)
    portfolio_operational = _build_operational_view(portfolio_latest, include_selected=False)
    research_top30_operational = _build_operational_view(research_only_top30, include_selected=True)
    research_portfolio_operational = _build_operational_view(research_only_portfolio, include_selected=False)
    # Phase 12A (2026-04-21): same enrichment for the rebalance-policy export path
    portfolio_operational = _enrich_with_live_state(portfolio_operational)
    research_portfolio_operational = _enrich_with_live_state(research_portfolio_operational)

    top30_operational.to_csv(top30_path, index=False)
    top30_operational.head(20).to_csv(top20_path, index=False)
    portfolio_operational.to_csv(portfolio_path, index=False)
    scored_latest.to_csv(scored_path, index=False)
    if bool(cfg.export_extended_outputs):
        full_rank.to_csv(full_rank_path, index=False)
        partial_watchlist.to_csv(partial_watchlist_path, index=False)
        research_top30_operational.to_csv(research_top30_path, index=False)
        research_portfolio_operational.to_csv(research_portfolio_path, index=False)

    def _portfolio_first_numeric(column: str, default: float = np.nan) -> float:
        if portfolio_latest.empty or column not in portfolio_latest.columns:
            return float(default)
        values = pd.to_numeric(portfolio_latest[column], errors="coerce").dropna()
        return float(values.iloc[0]) if not values.empty else float(default)

    def _portfolio_max_numeric(column: str, default: float = 0.0) -> float:
        if portfolio_latest.empty or column not in portfolio_latest.columns:
            return float(default)
        values = pd.to_numeric(portfolio_latest[column], errors="coerce").dropna()
        return float(values.max()) if not values.empty else float(default)

    def _portfolio_first_text(column: str, default: str = "") -> str:
        if portfolio_latest.empty or column not in portfolio_latest.columns:
            return str(default)
        values = portfolio_latest[column].dropna().astype(str).str.strip()
        values = values[values != ""]
        return str(values.iloc[0]) if not values.empty else str(default)

    def _frame_mean_numeric(frame: pd.DataFrame, column: str, default: float = np.nan) -> float:
        if frame.empty or column not in frame.columns:
            return float(default)
        values = pd.to_numeric(frame[column], errors="coerce").dropna()
        return float(values.mean()) if not values.empty else float(default)

    def _frame_mode_text(frame: pd.DataFrame, column: str, default: str = "") -> str:
        if frame.empty or column not in frame.columns:
            return str(default)
        values = frame[column].dropna().astype(str).str.strip()
        values = values[values != ""]
        if values.empty:
            return str(default)
        mode = values.mode()
        return str(mode.iloc[0]) if not mode.empty else str(default)

    def _portfolio_sleeve_weight_map(frame: pd.DataFrame) -> dict[str, float]:
        if frame.empty or "ticker" not in frame.columns or "weight" not in frame.columns:
            return {}
        stock_only = frame[
            frame["ticker"].astype(str).str.upper().ne(CASH_PROXY_TICKER)
        ].copy()
        if stock_only.empty or "portfolio_sleeve_label" not in stock_only.columns:
            return {}
        grouped = (
            stock_only.assign(
                portfolio_sleeve_label=stock_only["portfolio_sleeve_label"]
                .fillna("core_compounder")
                .astype(str)
            )
            .groupby("portfolio_sleeve_label")["weight"]
            .sum()
        )
        return {str(k): float(v) for k, v in grouped.items()}

    def _complete_sleeve_weight_map(weight_map: dict[str, float] | None) -> dict[str, float]:
        weight_map = weight_map or {}
        return {
            "core_compounder": float(weight_map.get("core_compounder", 0.0) or 0.0),
            "future_winner": float(weight_map.get("future_winner", 0.0) or 0.0),
            "early_scout": float(weight_map.get("early_scout", 0.0) or 0.0),
        }

    def _complete_sleeve_count_map(count_map: dict[str, int] | None) -> dict[str, int]:
        count_map = count_map or {}
        return {
            "core_compounder": int(count_map.get("core_compounder", 0) or 0),
            "future_winner": int(count_map.get("future_winner", 0) or 0),
            "early_scout": int(count_map.get("early_scout", 0) or 0),
        }

    def _frame_sage_by_sleeve(frame: pd.DataFrame) -> dict[str, float]:
        if frame.empty or "portfolio_sleeve_label" not in frame.columns or "sage_composite_score" not in frame.columns:
            return {}
        stock_only = frame[
            frame.get("ticker", pd.Series(dtype=object)).astype(str).str.upper().ne(CASH_PROXY_TICKER)
        ].copy()
        if stock_only.empty:
            return {}
        grouped = (
            stock_only.assign(
                portfolio_sleeve_label=stock_only["portfolio_sleeve_label"].fillna("core_compounder").astype(str),
                sage_composite_score=pd.to_numeric(stock_only["sage_composite_score"], errors="coerce"),
            )
            .dropna(subset=["sage_composite_score"])
            .groupby("portfolio_sleeve_label")["sage_composite_score"]
            .mean()
        )
        return {str(k): float(v) for k, v in grouped.items()}

    portfolio_sleeve_actual_weights = _complete_sleeve_weight_map(_portfolio_sleeve_weight_map(portfolio_latest))
    portfolio_sleeve_selected_counts = _complete_sleeve_count_map(
        {
            str(k): int(v)
            for k, v in portfolio_latest.loc[
                portfolio_latest.get("ticker", pd.Series(dtype=object)).astype(str).str.upper().ne(CASH_PROXY_TICKER),
                "portfolio_sleeve_label",
            ]
            .fillna("core_compounder")
            .astype(str)
            .value_counts()
            .items()
        }
        if not portfolio_latest.empty and "portfolio_sleeve_label" in portfolio_latest.columns
        else {}
    )
    sage_snapshot = {
        "top30_mean_sage_composite_score": _frame_mean_numeric(top30, "sage_composite_score", default=np.nan),
        "portfolio_mean_sage_composite_score": _frame_mean_numeric(
            portfolio_latest,
            "sage_composite_score",
            default=np.nan,
        ),
        "portfolio_mean_sage_g_score": _frame_mean_numeric(portfolio_latest, "sage_g_score", default=np.nan),
        "portfolio_mean_sage_v_score": _frame_mean_numeric(portfolio_latest, "sage_v_score", default=np.nan),
        "portfolio_mean_sage_q_score": _frame_mean_numeric(portfolio_latest, "sage_q_score", default=np.nan),
        "portfolio_mean_sage_c_score": _frame_mean_numeric(portfolio_latest, "sage_c_score", default=np.nan),
        "portfolio_sage_sector_mode": _frame_mode_text(portfolio_latest, "sage_sector", default=""),
        "portfolio_sage_by_sleeve": _frame_sage_by_sleeve(portfolio_latest),
    }

    # Pre-refresh live state from the PREVIOUS weights before overwriting,
    # so the operator compares old holdings vs new targets correctly.
    try:
        if weights_path.exists():
            _old_weights = json.loads(weights_path.read_text(encoding="utf-8"))
            if isinstance(_old_weights, dict) and _old_weights.get("holdings"):
                from r1000_portfolio_state import ensure_live_portfolio_state as _ensure_state
                _ensure_state(
                    paths,
                    weights_payload=_old_weights,
                    strategy_version=ENGINE_REUSE_VERSION,
                    force_refresh=True,
                )
    except Exception:
        pass

    # Phase 12B (2026-04-21): apply manual_positions.yaml if present.
    # User-edited file with real broker info (avg_cost, shares, entry_date)
    # overrides the bootstrap state so portfolio_latest.csv shows actual buy data.
    # Template auto-written on first run so user knows where to edit.
    try:
        from r1000_portfolio_state import (
            apply_manual_positions_from_yaml,
            write_manual_positions_template,
            manual_positions_path as _mpos_path,
        )
        _mpos_file = _mpos_path(paths)
        if not _mpos_file.exists():
            write_manual_positions_template(paths)
            log(f"[Phase 12B] wrote manual_positions.yaml template at {_mpos_file}")
        _, _applied = apply_manual_positions_from_yaml(paths)
        if _applied:
            log(f"[Phase 12B] applied manual positions from {_mpos_file}")
    except Exception as exc:
        log(f"[Phase 12B] manual_positions.yaml apply skipped: {exc}")

    weights_payload = {
        "run_id": run_identity["run_id"],
        "run_ts": run_identity["run_ts"],
        "git_commit": run_identity["git_commit"],
        "engine_version": run_identity["engine_version"],
        "config_fingerprint": run_identity["config_fingerprint"],
        "rebalance_date": str(pd.Timestamp(latest_dt).date()) if pd.notna(latest_dt) else None,
        "holdings": {
            str(r.ticker): float(r.weight)
            for r in portfolio_operational[["ticker", "weight"]].itertuples(index=False)
        }
        if not portfolio_operational.empty
        else {},
        "selected_n": int(
            portfolio_latest.get("ticker", pd.Series(dtype=object)).astype(str).str.upper().ne(CASH_PROXY_TICKER).sum()
        )
        if not portfolio_latest.empty
        else 0,
        "cash_weight": float(
            portfolio_latest.loc[
                portfolio_latest.get("ticker", pd.Series(dtype=object)).astype(str).str.upper() == CASH_PROXY_TICKER,
                "weight",
            ].sum()
        )
        if not portfolio_latest.empty
        else 0.0,
        "target_n": int(_portfolio_first_numeric("target_n", default=0.0)),
        "weight_cap": _portfolio_first_numeric("weight_cap", default=np.nan),
        "cash_target": _portfolio_first_numeric("cash_target", default=0.0),
        "sleeve_target_weights": {
            "core_compounder": _portfolio_first_numeric("sleeve_target_core_compounder_weight", default=0.0),
            "future_winner": _portfolio_first_numeric("sleeve_target_future_winner_weight", default=0.0),
            "early_scout": _portfolio_first_numeric("sleeve_target_early_scout_weight", default=0.0),
        },
        "sleeve_actual_weights": portfolio_sleeve_actual_weights,
        "sleeve_selected_counts": portfolio_sleeve_selected_counts,
        "sleeve_specific_rebalance_enabled": bool(bt.metrics.get("sleeve_specific_rebalance_enabled", False)),
        "sleeve_rebalance_interval_map": dict(bt.metrics.get("sleeve_rebalance_interval_map", {}) or {}),
        "sleeve_rebalance_counts": {
            str(k): int(v)
            for k, v in dict(bt.metrics.get("sleeve_rebalance_counts", {}) or {}).items()
        },
        "future_winner_regime_strength": _portfolio_first_numeric("future_winner_regime_strength", default=0.0),
        "early_scout_regime_strength": _portfolio_first_numeric("early_scout_regime_strength", default=0.0),
        "sleeve_growth_signal": _portfolio_first_numeric("sleeve_growth_signal", default=0.0),
        "sleeve_risk_signal": _portfolio_first_numeric("sleeve_risk_signal", default=0.0),
        "applied_regime_sleeve_policy_label": _portfolio_first_text("applied_regime_sleeve_policy_label"),
        "applied_regime_sleeve_live_label": _portfolio_first_text("applied_regime_sleeve_live_label"),
        "applied_regime_sleeve_source_label": _portfolio_first_text("applied_regime_sleeve_source_label"),
        "regime_sleeve_method_best": regime_sleeve_method_best,
        "learned_regime_sleeve_method": _regime_method_snapshot("learned_regime_map"),
        "manual_regime_sleeve_method": _regime_method_snapshot("manual_forced_regime_map"),
        "prev_holdings_applied": bool(
            portfolio_latest.get("prev_holdings_applied", pd.Series(dtype=bool)).fillna(False).astype(bool).any()
        )
        if not portfolio_latest.empty
        else False,
        "prev_holdings_count": int(_portfolio_max_numeric("prev_holdings_count", default=0.0)),
        "adaptive_ensemble_weights": dict(getattr(model_bundle, "adaptive_ensemble_weights", {}) or {}),
        "adaptive_ensemble_active": bool((getattr(model_bundle, "adaptive_ensemble_diagnostics", {}) or {}).get("active", False)),
        "adaptive_ensemble_history_months": int((getattr(model_bundle, "adaptive_ensemble_diagnostics", {}) or {}).get("history_months", 0)),
        "regime_ensemble_weights": {
            regime: {k: round(float(v), 4) for k, v in w.items()}
            for regime, w in (dict(getattr(model_bundle, "regime_ensemble_weights", {}) or {})).items()
        },
        "rebalance_interval_months": int(bt.metrics.get("rebalance_interval_months", getattr(cfg, "rebalance_interval_months", 1))),
        "adaptive_rebalance_policy": bool(bt.metrics.get("adaptive_rebalance_policy", False)),
        "avg_rebalance_interval_months": float(bt.metrics.get("avg_rebalance_interval_months", np.nan)),
        "rebalance_count": int(bt.metrics.get("rebalance_count", 0)),
        "rebalanced_month_ratio": float(bt.metrics.get("rebalanced_month_ratio", np.nan)),
        "recommended_rebalance_interval_months": int(
            best_rebalance_interval.get("rebalance_interval_months", getattr(cfg, "rebalance_interval_months", 1))
        ),
        "active_rebalance_interval_months": int(
            next_run_recommendation.get(
                "active_rebalance_interval_months",
                best_rebalance_interval.get("rebalance_interval_months", getattr(cfg, "rebalance_interval_months", 1)),
            )
        ),
        "policy_rebalance_due": bool(next_run_recommendation.get("policy_rebalance_due", True)),
        "rebalance_action": next_run_recommendation.get("next_rebalance_action"),
        "deferred_rebalance_interval_months": next_run_recommendation.get("deferred_rebalance_interval_months"),
        "next_scheduled_rebalance_date": next_run_recommendation.get("next_scheduled_rebalance_date"),
        "recommended_next_run_date": next_run_recommendation.get("recommended_next_run_date"),
        "recommended_next_run_mode": next_run_recommendation.get("recommended_next_run_mode"),
        "recommended_next_run_reason": next_run_recommendation.get("recommended_next_run_reason"),
        "regime_interval_label": best_rebalance_interval.get("regime_interval_label"),
        "regime_interval_reason": best_rebalance_interval.get("regime_interval_reason"),
        "regime_target_interval_months": int(
            best_rebalance_interval.get("target_interval_months", getattr(cfg, "rebalance_interval_months", 1))
        ),
        "strict_live_backtest_alignment": bool(cfg.strict_live_backtest_alignment),
        "ops_min_realized_coverage": float(cfg.ops_min_realized_coverage),
        "sage_snapshot": sage_snapshot,
        "event_regime_label": (
            portfolio_latest.get("event_regime_label", pd.Series(dtype=object)).dropna().astype(str).mode().iloc[0]
            if not portfolio_latest.empty
            and "event_regime_label" in portfolio_latest.columns
            and not portfolio_latest.get("event_regime_label", pd.Series(dtype=object)).dropna().empty
            else None
        ),
        "live_event_alert_label": (
            portfolio_latest.get("live_event_alert_label", pd.Series(dtype=object)).dropna().astype(str).mode().iloc[0]
            if not portfolio_latest.empty
            and "live_event_alert_label" in portfolio_latest.columns
            and not portfolio_latest.get("live_event_alert_label", pd.Series(dtype=object)).dropna().empty
            else None
        ),
    }
    weights_path.write_text(json.dumps(weights_payload, indent=2))
    bt_metrics_path.write_text(json.dumps(bt.metrics, indent=2))
    bt.equity_curve.to_csv(equity_path, index=False)

    # Phase 12C (2026-04-21): build lifetime equity curve (backtest + live).
    # Failsafe: errors get logged but don't kill pipeline.
    try:
        lifetime_eq_df, lifetime_meta = _build_lifetime_equity_curve(
            bt.equity_curve, portfolio_operational
        )
        lifetime_path = paths["out"] / "lifetime_equity_curve.csv"
        lifetime_metrics_path = paths["out"] / "lifetime_metrics.json"
        if lifetime_eq_df is not None and not lifetime_eq_df.empty:
            lifetime_eq_df.to_csv(lifetime_path, index=False)
            lifetime_metrics_path.write_text(json.dumps(lifetime_meta, indent=2, default=str))
            log(
                f"[Phase 12C] lifetime equity curve: {len(lifetime_eq_df)} rows, "
                f"CAGR {lifetime_meta.get('lifetime_cagr', float('nan')):.2%} over "
                f"{lifetime_meta.get('lifetime_years', 0):.2f} years "
                f"(live_method={lifetime_meta.get('live_value_method')})"
            )
    except Exception as exc:
        log(f"[Phase 12C] lifetime equity curve build failed: {exc}")
    ops_output_files = update_operational_tracking(
        cfg,
        paths,
        top30_operational,
        portfolio_operational,
        research_top30_operational,
        research_portfolio_operational,
        acceptance_checks,
        bt,
        best_rebalance_interval,
        next_run_recommendation,
    )

    perf_md = [
        "# OOS Performance Report",
        "",
        f"- Run timestamp: {datetime.now().isoformat(timespec='seconds')}",
        f"- Period: {cfg.start_date} ~ {cfg.end_date}",
        f"- Months: {bt.metrics.get('months')}",
        f"- CAGR: {bt.metrics.get('cagr'):.4f}",
        f"- Benchmark source: {bt.metrics.get('benchmark_source')}",
        f"- Benchmark CAGR: {bt.metrics.get('benchmark_cagr'):.4f}",
        f"- Excess CAGR: {bt.metrics.get('excess_cagr'):.4f}",
        f"- Sharpe: {bt.metrics.get('sharpe'):.4f}",
        f"- Sortino: {bt.metrics.get('sortino'):.4f}",
        f"- MaxDD: {bt.metrics.get('max_dd'):.4f}",
        f"- Calmar: {bt.metrics.get('calmar'):.4f}",
        f"- IR vs {bt.metrics.get('benchmark_source')}: {bt.metrics.get('ir'):.4f}",
        f"- Beat-month ratio: {bt.metrics.get('beat_month_ratio'):.4f}",
        f"- Trade cost (per side, bps): {bt.metrics.get('trade_cost_bps_per_side'):.2f}",
        f"- Starting capital (USD): {bt.metrics.get('starting_capital_usd'):.2f}",
        f"- Ending capital (USD): {bt.metrics.get('ending_capital_usd'):.2f}",
        f"- Avg cash weight: {bt.metrics.get('avg_cash_weight'):.4f}",
        f"- Avg turnover (monthly): {bt.metrics.get('avg_turnover_monthly'):.4f}",
        f"- Rebalance interval (months): {int(bt.metrics.get('rebalance_interval_months', getattr(cfg, 'rebalance_interval_months', 1)))}",
        f"- Adaptive rebalance policy active: {bool(bt.metrics.get('adaptive_rebalance_policy', False))}",
        f"- Avg rebalance interval (months): {float(bt.metrics.get('avg_rebalance_interval_months', np.nan)):.2f}",
        f"- Rebalance count: {int(bt.metrics.get('rebalance_count', 0))}",
        f"- Rebalanced month ratio: {float(bt.metrics.get('rebalanced_month_ratio', np.nan)):.4f}",
        f"- Rank IC mean: {ranking_metrics.get('rank_ic_mean'):.4f}",
        f"- NDCG@{cfg.rank_eval_top_k}: {ranking_metrics.get('ndcg_at_k_mean'):.4f}",
        f"- Precision@{cfg.rank_eval_top_k}: {ranking_metrics.get('precision_at_k_mean'):.4f}",
        f"- Backtest usable: {bool(acceptance_checks.get('backtest_usable', False))}",
        f"- Research only: {bool(acceptance_checks.get('backtest_research_only', False))}",
        f"- Recommended rebalance interval (months): {int(best_rebalance_interval.get('rebalance_interval_months', getattr(cfg, 'rebalance_interval_months', 1)))}",
        f"- Active live rebalance interval (months): {int(next_run_recommendation.get('active_rebalance_interval_months', best_rebalance_interval.get('rebalance_interval_months', getattr(cfg, 'rebalance_interval_months', 1))))}",
        f"- Rebalance action: {next_run_recommendation.get('next_rebalance_action')}",
        f"- Rebalance regime label: {best_rebalance_interval.get('regime_interval_label')}",
        f"- Next scheduled rebalance date: {next_run_recommendation.get('next_scheduled_rebalance_date')}",
        f"- Recommended next run date: {next_run_recommendation.get('recommended_next_run_date')}",
        f"- Recommended next run mode: {next_run_recommendation.get('recommended_next_run_mode')}",
        f"- Recommendation note: {next_run_recommendation.get('recommended_next_run_reason')}",
        f"- Strict live/backtest alignment: {bool(cfg.strict_live_backtest_alignment)}",
        f"- Operational realized coverage threshold: {float(cfg.ops_min_realized_coverage):.2f}",
        f"- Backtest window comparison years: {', '.join(str(int(x)) for x in cfg.backtest_window_comparison_years)}",
    ]
    (paths["reports"] / "oos_performance.md").write_text("\n".join(perf_md), encoding="utf-8")

    output_files = {
        "top30_latest.csv": str(top30_path),
        "top20_latest.csv": str(top20_path),
        "portfolio_latest.csv": str(portfolio_path),
        "scored_latest.csv": str(scored_path),
        "weights_latest.json": str(weights_path),
        "backtest_metrics.json": str(bt_metrics_path),
        "equity_curve.csv": str(equity_path),
        "fundamental_coverage_latest.csv": str(coverage_path),
        "fundamental_comprehensive_coverage_latest.csv": str(comprehensive_coverage_path),
        "live_fundamental_coverage_latest.csv": str(live_coverage_path),
        "macro_regime_latest.parquet": str(macro_regime_path),
        "model_bundle_latest.json": str(paths["models"] / "model_bundle_latest.json"),
    }
    output_files.update(ops_output_files)
    if bool(cfg.export_extended_outputs):
        output_files.update(
            {
                "full_fundamental_rank_latest.csv": str(full_rank_path),
                "partial_data_watchlist_latest.csv": str(partial_watchlist_path),
                "research_only_top30_latest.csv": str(research_top30_path),
                "research_only_portfolio_latest.csv": str(research_portfolio_path),
                "ranking_quality.json": str(ranking_path),
                "benchmark_comparison_latest.json": str(benchmark_compare_path),
                "fund_panel_recent4q_flow_coverage.csv": str(fund_panel_flow_path),
                "fundamental_join_latest_diagnostics.csv": str(fund_join_diag_path),
                "fundamental_collection_audit.json": str(fund_collection_audit_path),
                "fundamental_collection_missing_latest.csv": str(fund_collection_missing_path),
                "fundamental_panel_latest_snapshot.csv": str(fund_panel_snapshot_path),
                "candidate_universe_change_latest.json": str(universe_change_summary_path),
                "candidate_universe_change_latest.csv": str(universe_change_detail_path),
                "market_adaptation_latest.json": str(market_adaptation_path),
                "event_alert_latest.json": str(event_alert_path),
            }
        )
    if bool(cfg.export_explain_outputs):
        output_files.update(
            {
                "top30_explain_latest.csv": str(explain_path),
                "research_only_top30_explain_latest.csv": str(research_explain_path),
            }
        )
    if run_portfolio_size_compare:
        output_files["portfolio_size_comparison.csv"] = str(portfolio_size_compare_path)
    if run_rebalance_interval_compare:
        output_files["rebalance_interval_comparison.csv"] = str(rebalance_interval_compare_path)
    if run_backtest_window_compare:
        output_files["backtest_window_comparison.csv"] = str(backtest_window_compare_path)
    if run_sleeve_regime_compare and not sleeve_regime_grid.empty:
        output_files["sleeve_policy_per_regime_grid.csv"] = str(sleeve_regime_grid_path)
        output_files["sleeve_policy_per_regime_best.csv"] = str(sleeve_regime_best_path)
    if run_regime_map_method_compare and not regime_sleeve_method_compare.empty:
        output_files["regime_sleeve_map_method_comparison.csv"] = str(regime_sleeve_method_compare_path)
    if not latest_standalone_sleeve_holdings.empty:
        output_files["latest_sleeve_standalone_holdings.csv"] = str(latest_sleeve_standalone_holdings_path)
        output_files["core_compounder_latest_standalone.csv"] = str(latest_core_standalone_path)
        output_files["future_winner_latest_standalone.csv"] = str(latest_future_standalone_path)
        output_files["early_scout_latest_standalone.csv"] = str(latest_early_standalone_path)
    if not latest_standalone_sleeve_summary.empty:
        output_files["latest_sleeve_standalone_summary.csv"] = str(latest_sleeve_standalone_summary_path)
    if not concentrated_latest_holdings.empty:
        output_files["concentrated_portfolio_latest.csv"] = str(concentrated_portfolio_path)
        output_files["concentrated_top1_latest.csv"] = str(concentrated_top1_path)
    output_files["concentrated_backtest_metrics.json"] = str(concentrated_metrics_path)
    output_files["concentrated_operating_guide.json"] = str(concentrated_operating_guide_path)
    if not engine_diagnostics_monthly.empty:
        output_files["engine_diagnostics_by_month.csv"] = str(engine_diagnostics_monthly_path)
    if not engine_diagnostics_summary.empty:
        output_files["engine_diagnostics_summary.csv"] = str(engine_diagnostics_summary_path)
    if bool(getattr(cfg, "run_ai_four_sleeve_comparison", True)) and not ai_four_sleeve_compare.empty:
        output_files["ai_four_sleeve_adaptive_comparison.csv"] = str(ai_four_sleeve_compare_path)
        output_files["ai_four_sleeve_adaptive_regime_grid.csv"] = str(ai_four_sleeve_regime_grid_path)
        output_files["ai_four_sleeve_adaptive_regime_best.csv"] = str(ai_four_sleeve_regime_best_path)
        output_files["ai_four_sleeve_adaptive_selected_map.json"] = str(ai_four_sleeve_selected_map_path)

    operator_outputs: dict[str, Any] = {"plan": pd.DataFrame(), "summary": {}, "output_files": {}}

    summary = {
        "run_id": run_identity["run_id"],
        "run_ts": run_identity["run_ts"],
        "git_commit": run_identity["git_commit"],
        "engine_version": run_identity["engine_version"],
        "config_fingerprint": run_identity["config_fingerprint"],
        "base_dir": cfg.base_dir,
        "n_scored_latest": int(len(scored_latest)),
        "n_top30": int(len(top30)),
        "n_portfolio": int(
            (
                portfolio_latest.get("ticker", pd.Series(dtype=object)).astype(str).str.upper()
                != CASH_PROXY_TICKER
            ).sum()
        ) if not portfolio_latest.empty else 0,
        "portfolio_cash_weight": float(
            pd.to_numeric(
                portfolio_latest.loc[
                    portfolio_latest.get("ticker", pd.Series(dtype=object)).astype(str).str.upper() == CASH_PROXY_TICKER,
                    "weight",
                ],
                errors="coerce",
            ).sum()
        ) if not portfolio_latest.empty else 0.0,
        "portfolio_sleeve_actual_weights": portfolio_sleeve_actual_weights,
        "portfolio_sleeve_selected_counts": portfolio_sleeve_selected_counts,
        "sage_snapshot": sage_snapshot,
        "sleeve_specific_rebalance_enabled": bool(bt.metrics.get("sleeve_specific_rebalance_enabled", False)),
        "sleeve_rebalance_interval_map": dict(bt.metrics.get("sleeve_rebalance_interval_map", {}) or {}),
        "sleeve_rebalance_counts": {
            str(k): int(v)
            for k, v in dict(bt.metrics.get("sleeve_rebalance_counts", {}) or {}).items()
        },
        "portfolio_sleeve_target_weights": {
            "core_compounder": _portfolio_first_numeric("sleeve_target_core_compounder_weight", default=0.0),
            "future_winner": _portfolio_first_numeric("sleeve_target_future_winner_weight", default=0.0),
            "early_scout": _portfolio_first_numeric("sleeve_target_early_scout_weight", default=0.0),
        },
        "future_winner_regime_strength": _portfolio_first_numeric("future_winner_regime_strength", default=0.0),
        "early_scout_regime_strength": _portfolio_first_numeric("early_scout_regime_strength", default=0.0),
        "sleeve_growth_signal": _portfolio_first_numeric("sleeve_growth_signal", default=0.0),
        "sleeve_risk_signal": _portfolio_first_numeric("sleeve_risk_signal", default=0.0),
        "n_research_only_top30": int(len(research_only_top30)),
        "n_research_only_portfolio": int(
            (
                research_only_portfolio.get("ticker", pd.Series(dtype=object)).astype(str).str.upper()
                != CASH_PROXY_TICKER
            ).sum()
        ) if not research_only_portfolio.empty else 0,
        "latest_rebalance_date": str(pd.Timestamp(latest_dt).date()) if pd.notna(latest_dt) else None,
        "latest_event_regime": (
            str(scored_latest.get("event_regime_label", pd.Series(dtype=str)).mode().iloc[0])
            if "event_regime_label" in scored_latest.columns
            and not scored_latest.get("event_regime_label", pd.Series(dtype=str)).mode().empty
            else "balanced"
        ),
        "latest_live_event_alert": latest_live_event_alert,
        "rebalance_interval_months": int(bt.metrics.get("rebalance_interval_months", getattr(cfg, "rebalance_interval_months", 1))),
        "adaptive_rebalance_policy": bool(bt.metrics.get("adaptive_rebalance_policy", False)),
        "avg_rebalance_interval_months": float(bt.metrics.get("avg_rebalance_interval_months", np.nan)),
        "rebalance_count": int(bt.metrics.get("rebalance_count", 0)),
        "rebalanced_month_ratio": float(bt.metrics.get("rebalanced_month_ratio", np.nan)),
        "recommended_rebalance_interval_months": int(best_rebalance_interval.get("rebalance_interval_months", getattr(cfg, "rebalance_interval_months", 1))),
        "active_rebalance_interval_months": int(
            next_run_recommendation.get(
                "active_rebalance_interval_months",
                best_rebalance_interval.get("rebalance_interval_months", getattr(cfg, "rebalance_interval_months", 1)),
            )
        ),
        "policy_rebalance_due": bool(next_run_recommendation.get("policy_rebalance_due", True)),
        "rebalance_action": next_run_recommendation.get("next_rebalance_action"),
        "rebalance_interval_optimization": best_rebalance_interval,
        "next_run_recommendation": next_run_recommendation,
        "trade_cost_bps_per_side": float(bt.metrics.get("trade_cost_bps_per_side", np.nan)),
        "starting_capital_usd": float(bt.metrics.get("starting_capital_usd", np.nan)),
        "ending_capital_usd": float(bt.metrics.get("ending_capital_usd", np.nan)),
        "benchmark_ending_capital_usd": float(bt.metrics.get("benchmark_ending_capital_usd", np.nan)),
        "universe_mode": (
            "historical_membership_file"
            if scored_latest.get("universe_source", pd.Series(dtype=str)).astype(str).eq("historical_membership_file").any()
            else "current_constituents_proxy"
        ),
        "portfolio_export_blocked": portfolio_export_blocked,
        "metrics": bt.metrics,
        "benchmark_comparison": benchmark_compare,
        "portfolio_size_comparison_sizes": [int(x) for x in cfg.portfolio_size_comparison_sizes],
        "rebalance_interval_comparison_months": [int(x) for x in cfg.rebalance_interval_comparison_months],
        "backtest_window_comparison_years": [int(x) for x in cfg.backtest_window_comparison_years],
        "ranking_metrics": ranking_metrics,
        "target_spec": model_bundle.target_spec,
        "adaptive_ensemble_weights": dict(getattr(model_bundle, "adaptive_ensemble_weights", {}) or {}),
        "adaptive_ensemble_diagnostics": dict(getattr(model_bundle, "adaptive_ensemble_diagnostics", {}) or {}),
        "strict_live_backtest_alignment": bool(cfg.strict_live_backtest_alignment),
        "ops_min_realized_coverage": float(cfg.ops_min_realized_coverage),
        "backtest_usable": bool(acceptance_checks.get("backtest_usable", False)),
        "research_only_backtest": bool(acceptance_checks.get("backtest_research_only", False)),
        "run_comparison_backtests": bool(cfg.run_comparison_backtests),
        "run_portfolio_size_comparison": run_portfolio_size_compare,
        "run_rebalance_interval_comparison": run_rebalance_interval_compare,
        "run_backtest_window_comparison": run_backtest_window_compare,
        "run_sleeve_regime_comparison": run_sleeve_regime_compare,
        "run_regime_map_method_comparison": run_regime_map_method_compare,
        "sleeve_regime_comparison_cash_max": sleeve_regime_cash_max,
        "applied_regime_sleeve_policy_label": _portfolio_first_text("applied_regime_sleeve_policy_label"),
        "applied_regime_sleeve_live_label": _portfolio_first_text("applied_regime_sleeve_live_label"),
        "applied_regime_sleeve_source_label": _portfolio_first_text("applied_regime_sleeve_source_label"),
        "run_sleeve_cap_policy_comparison": bool(getattr(cfg, "run_sleeve_cap_policy_comparison", True)),
        "run_standalone_sleeve_backtest_comparison": run_standalone_sleeve_compare,
        "run_concentrated_backtest_comparison": bool(getattr(cfg, "run_concentrated_backtest_comparison", True)),
        "run_ai_four_sleeve_comparison": bool(getattr(cfg, "run_ai_four_sleeve_comparison", True)),
        "run_historical_data_quality_reports": bool(getattr(cfg, "run_historical_data_quality_reports", True)),
        "champion_sleeve_cap_policy": selected_sleeve_cap_policy,
        "ai_four_sleeve_adaptive_best": (
            ai_four_sleeve_compare.head(3).to_dict(orient="records")
            if not ai_four_sleeve_compare.empty
            else []
        ),
        "ai_four_sleeve_adaptive_selected_map": ai_four_sleeve_selected_map,
        "regime_conditioned_sleeve_map": dict(getattr(cfg, "regime_conditioned_sleeve_map", {}) or {}),
        "manual_regime_conditioned_sleeve_map": manual_regime_conditioned_sleeve_map,
        "regime_sleeve_map_method_comparison": regime_sleeve_method_records,
        "regime_sleeve_map_method_best": regime_sleeve_method_best,
        "sleeve_cap_policy_optimization_snapshot": (
            sleeve_cap_policy_compare.head(5).to_dict(orient="records")
            if not sleeve_cap_policy_compare.empty
            else []
        ),
        "latest_sleeve_standalone_summary": (
            latest_standalone_sleeve_summary.to_dict(orient="records")
            if not latest_standalone_sleeve_summary.empty
            else []
        ),
        "concentrated_summary": concentrated_metrics_payload,
        "engine_diagnostics_summary": (
            engine_diagnostics_summary.to_dict(orient="records")
            if not engine_diagnostics_summary.empty
            else []
        ),
        "operator_summary": {},
        "export_extended_outputs": bool(cfg.export_extended_outputs),
        "export_explain_outputs": bool(cfg.export_explain_outputs),
        "acceptance_checks": acceptance_checks,
        "output_files": output_files,
    }
    summary_path.write_text(json.dumps(summary, indent=2))

    try:
        from r1000_operator import refresh_live_operator_outputs

        operator_outputs = refresh_live_operator_outputs(
            paths,
            strategy_version=ENGINE_REUSE_VERSION,
            run_id=run_identity["run_id"],
            run_ts=run_identity["run_ts"],
            git_commit=run_identity["git_commit"],
            config_fingerprint=run_identity["config_fingerprint"],
        )
        output_files.update(dict(operator_outputs.get("output_files", {}) or {}))
        summary["operator_summary"] = dict(operator_outputs.get("summary", {}) or {})
        summary["output_files"] = output_files
        summary_path.write_text(json.dumps(summary, indent=2))
    except Exception as exc:
        operator_outputs = {
            "plan": pd.DataFrame(),
            "summary": {"error": str(exc)},
            "output_files": {},
        }
        summary["operator_summary"] = {"error": str(exc)}
        summary_path.write_text(json.dumps(summary, indent=2))
        log(f"[WARN] live operator output refresh failed: {exc}")

    result_outputs = {
        "top30_latest": str(top30_path),
        "top20_latest": str(top20_path),
        "portfolio_latest": str(portfolio_path),
        "scored_latest": str(scored_path),
        "weights_latest": str(weights_path),
        "backtest_metrics": str(bt_metrics_path),
        "equity_curve": str(equity_path),
        "fundamental_coverage_latest": str(coverage_path),
        "fundamental_comprehensive_coverage_latest": str(comprehensive_coverage_path),
        "live_fundamental_coverage_latest": str(live_coverage_path),
        "macro_regime_latest": str(macro_regime_path),
        "model_bundle_latest": str(paths["models"] / "model_bundle_latest.json"),
        "run_summary": str(summary_path),
    }
    result_outputs.update(ops_output_files)
    result_outputs.update(dict(operator_outputs.get("output_files", {}) or {}))
    if bool(cfg.export_extended_outputs):
        result_outputs.update(
            {
                "full_fundamental_rank_latest": str(full_rank_path),
                "partial_data_watchlist_latest": str(partial_watchlist_path),
                "research_only_top30_latest": str(research_top30_path),
                "research_only_portfolio_latest": str(research_portfolio_path),
                "ranking_quality": str(ranking_path),
                "benchmark_comparison_latest": str(benchmark_compare_path),
                "fund_panel_recent4q_flow_coverage": str(fund_panel_flow_path),
                "fundamental_join_latest_diagnostics": str(fund_join_diag_path),
                "fundamental_collection_audit": str(fund_collection_audit_path),
                "fundamental_collection_missing_latest": str(fund_collection_missing_path),
                "fundamental_panel_latest_snapshot": str(fund_panel_snapshot_path),
                "candidate_universe_change_summary": str(universe_change_summary_path),
                "candidate_universe_change_detail": str(universe_change_detail_path),
                "market_adaptation_latest": str(market_adaptation_path),
                "event_alert_latest": str(event_alert_path),
            }
        )
    if bool(cfg.export_explain_outputs):
        result_outputs.update(
            {
                "top30_explain_latest": str(explain_path),
                "research_only_top30_explain_latest": str(research_explain_path),
            }
        )
    if run_portfolio_size_compare:
        result_outputs["portfolio_size_comparison"] = str(portfolio_size_compare_path)
    if run_rebalance_interval_compare:
        result_outputs["rebalance_interval_comparison"] = str(rebalance_interval_compare_path)
    if run_backtest_window_compare:
        result_outputs["backtest_window_comparison"] = str(backtest_window_compare_path)
    if run_sleeve_regime_compare and not sleeve_regime_best.empty:
        result_outputs["sleeve_policy_per_regime_grid"] = str(sleeve_regime_grid_path)
        result_outputs["sleeve_policy_per_regime_best"] = str(sleeve_regime_best_path)
    if run_regime_map_method_compare and not regime_sleeve_method_compare.empty:
        result_outputs["regime_sleeve_map_method_comparison"] = str(regime_sleeve_method_compare_path)
    if not latest_standalone_sleeve_holdings.empty:
        result_outputs["latest_sleeve_standalone_holdings"] = str(latest_sleeve_standalone_holdings_path)
        result_outputs["core_compounder_latest_standalone"] = str(latest_core_standalone_path)
        result_outputs["future_winner_latest_standalone"] = str(latest_future_standalone_path)
        result_outputs["early_scout_latest_standalone"] = str(latest_early_standalone_path)
    if not latest_standalone_sleeve_summary.empty:
        result_outputs["latest_sleeve_standalone_summary"] = str(latest_sleeve_standalone_summary_path)
    if not concentrated_latest_holdings.empty:
        result_outputs["concentrated_portfolio_latest"] = str(concentrated_portfolio_path)
        result_outputs["concentrated_top1_latest"] = str(concentrated_top1_path)
    result_outputs["concentrated_backtest_metrics"] = str(concentrated_metrics_path)
    result_outputs["concentrated_operating_guide"] = str(concentrated_operating_guide_path)
    if not engine_diagnostics_monthly.empty:
        result_outputs["engine_diagnostics_by_month"] = str(engine_diagnostics_monthly_path)
    if not engine_diagnostics_summary.empty:
        result_outputs["engine_diagnostics_summary"] = str(engine_diagnostics_summary_path)
    if bool(getattr(cfg, "run_sleeve_cap_policy_comparison", True)) and not sleeve_cap_policy_compare.empty:
        result_outputs["sleeve_cap_policy_comparison"] = str(sleeve_cap_policy_compare_path)
        result_outputs["sleeve_cap_policy_champion_latest"] = str(sleeve_cap_policy_champion_path)
    if run_standalone_sleeve_compare and not standalone_sleeve_compare.empty:
        result_outputs["portfolio_sleeve_top7_standalone_comparison"] = str(standalone_sleeve_compare_path)
        result_outputs["portfolio_sleeve_top7_standalone_monthly"] = str(standalone_sleeve_monthly_path)
        result_outputs["portfolio_sleeve_top7_standalone_holdings"] = str(standalone_sleeve_holdings_path)
    if bool(getattr(cfg, "run_concentrated_backtest_comparison", True)) and not concentrated_compare.empty:
        result_outputs["concentrated_strategy_comparison"] = str(concentrated_compare_path)
        result_outputs["concentrated_strategy_monthly"] = str(concentrated_monthly_path)
        result_outputs["concentrated_strategy_holdings"] = str(concentrated_holdings_path)
    if bool(getattr(cfg, "run_ai_four_sleeve_comparison", True)) and not ai_four_sleeve_compare.empty:
        result_outputs["ai_four_sleeve_adaptive_comparison"] = str(ai_four_sleeve_compare_path)
        result_outputs["ai_four_sleeve_adaptive_regime_grid"] = str(ai_four_sleeve_regime_grid_path)
        result_outputs["ai_four_sleeve_adaptive_regime_best"] = str(ai_four_sleeve_regime_best_path)
        result_outputs["ai_four_sleeve_adaptive_selected_map"] = str(ai_four_sleeve_selected_map_path)
    if bool(getattr(cfg, "run_historical_data_quality_reports", True)) and not historical_quality_monthly.empty:
        result_outputs["historical_data_quality_by_month"] = str(historical_quality_monthly_path)
        result_outputs["historical_data_quality_by_sleeve"] = str(historical_quality_sleeve_path)
        result_outputs["historical_data_quality_latest"] = str(historical_quality_latest_path)
    result_outputs.update(output_files)
    result_outputs["run_summary.json"] = str(summary_path)
    manifest = {
        "run_id": run_identity["run_id"],
        "run_ts": run_identity["run_ts"],
        "git_commit": run_identity["git_commit"],
        "engine_version": run_identity["engine_version"],
        "config_fingerprint": run_identity["config_fingerprint"],
        "base_dir": cfg.base_dir,
        "start_date": str(cfg.start_date),
        "end_date": str(cfg.end_date),
        "fast_mode": bool(getattr(cfg, "fast_mode", False)),
        "reuse_existing_artifacts": bool(cfg.reuse_existing_artifacts),
        "resume_partial_walkforward": bool(cfg.resume_partial_walkforward),
        "output_files": {str(k): str(v) for k, v in result_outputs.items()},
    }
    archive_info = archive_run_outputs(
        paths,
        run_id=run_identity["run_id"],
        manifest=manifest,
        output_files=result_outputs,
    )
    result_outputs["run_manifest"] = str(archive_info["latest_manifest_path"])
    result_outputs["archive_dir"] = str(archive_info["archive_dir"])
    summary["run_manifest"] = str(archive_info["latest_manifest_path"])
    summary["archive_dir"] = str(archive_info["archive_dir"])
    summary["output_files"] = result_outputs
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return result_outputs


def show_output_table_previews(output_paths: dict[str, str]) -> None:
    def _read_csv(path_str: Optional[str]) -> pd.DataFrame:
        if not path_str:
            return pd.DataFrame()
        try:
            path = Path(path_str)
            if not path.exists():
                return pd.DataFrame()
            return pd.read_csv(path)
        except Exception:
            return pd.DataFrame()

    try:
        from IPython.display import display  # type: ignore

        def _show(df: pd.DataFrame) -> None:
            display(df)

    except Exception:

        def _show(df: pd.DataFrame) -> None:
            if df.empty:
                print("(empty)")
            else:
                print(df.to_string(index=False))

    preview_specs: list[tuple[str, str, int, Optional[list[str]]]] = [
        ("Full Fundamental Rank", "full_fundamental_rank_latest", 30, None),
        ("Partial Data Watchlist", "partial_data_watchlist_latest", 30, None),
        ("Top 30", "top30_latest", 30, None),
        ("Portfolio", "portfolio_latest", 30, None),
        (
            "Sleeve Policy Best-per-Regime",
            "sleeve_policy_per_regime_best",
            20,
            ["regime_label", "policy_label", "core_frac", "future_frac", "early_frac", "months", "cagr", "sharpe", "max_dd"],
        ),
        ("Research Only Top30", "research_only_top30_latest", 30, None),
        ("Research Only Portfolio", "research_only_portfolio_latest", 30, None),
        (
            "Explain",
            "top30_explain_latest",
            30,
            [
                "rank",
                "ticker",
                "Name",
                "sector",
                "score",
                "score_total",
                "strategy_blueprint_score",
                "dominant_archetype_label",
                "archetype_alignment_score",
                "future_winner_scout_score",
                "score_future_winner_model",
                "revision_blueprint_score",
                "growth_blueprint_score",
                "valuation_blueprint_score",
                "moat_quality_blueprint_score",
                "technical_blueprint_score",
                "overheat_penalty",
                "contrib_score_future_winner_scout",
                "contrib_score_future_winner_model",
                "contrib_score_archetype_mixture",
                "contrib_score_strategy_blueprint",
                "contrib_overheat_penalty",
                "contrib_watchlist_quality_penalty",
                "weight",
            ],
        ),
        (
            "Research Only Explain",
            "research_only_top30_explain_latest",
            30,
            [
                "rank",
                "ticker",
                "Name",
                "sector",
                "score",
                "score_total",
                "strategy_blueprint_score",
                "dominant_archetype_label",
                "archetype_alignment_score",
                "future_winner_scout_score",
                "score_future_winner_model",
                "revision_blueprint_score",
                "growth_blueprint_score",
                "valuation_blueprint_score",
                "moat_quality_blueprint_score",
                "technical_blueprint_score",
                "overheat_penalty",
                "contrib_score_future_winner_scout",
                "contrib_score_future_winner_model",
                "contrib_score_archetype_mixture",
                "contrib_score_strategy_blueprint",
                "contrib_overheat_penalty",
                "contrib_watchlist_quality_penalty",
                "weight",
            ],
        ),
    ]

    for title, key, limit, columns in preview_specs:
        path_str = output_paths.get(key, "")
        df = _read_csv(path_str)
        print(f"\n=== {title} ===")
        print(path_str or "(missing path)")
        if df.empty:
            print("(empty)")
            continue
        if columns:
            keep = [c for c in columns if c in df.columns]
            if keep:
                df = df[keep].copy()
        _show(df.head(limit).copy())


def run_all(cfg: Optional[dict | EngineConfig] = None) -> dict[str, Any]:
    cfg = to_cfg(cfg)
    validate_config(cfg)
    cfg = apply_fast_mode(cfg)
    mount_drive_if_colab()
    paths = get_paths(cfg)
    flags = load_stage_flags(paths)
    phase0_fp = reuse_fingerprint(cfg, "phase0_code_search")
    phase13_fp = reuse_fingerprint(cfg, "phase1_to_phase3_data")
    phase4_fp = reuse_fingerprint(cfg, "phase4_modeling")
    save_stage_flag(paths, "start", "running")

    phase0_summary_path = paths["reports"] / "phase0_scan_summary.json"
    if cfg.reuse_existing_artifacts and stage_is_reusable(flags, "phase0_code_search", phase0_fp) and phase0_summary_path.exists():
        p0 = json.loads(phase0_summary_path.read_text())
        log("Phase 0: reusing existing code search artifacts ...")
        save_stage_flag(paths, "phase0_code_search", "reused", {"scan_hits": p0.get("scan_hits", {}), "fingerprint": phase0_fp})
    else:
        p0 = run_phase0_code_search(cfg, paths)
        save_stage_flag(paths, "phase0_code_search", "completed", {"scan_hits": p0.get("scan_hits", {}), "fingerprint": phase0_fp})

    feature_store_path = paths["feature_store"] / "feature_store_latest.parquet"
    feature_store_reuse_ok = False
    feature_store_reuse_status: dict[str, Any] = {}
    if cfg.reuse_existing_artifacts and stage_is_reusable(flags, "phase1_to_phase3_data", phase13_fp) and feature_store_path.exists():
        feature_store_reuse_status = feature_store_fundamental_coverage_status(feature_store_path, cfg)
        feature_store_reuse_ok = bool(feature_store_reuse_status.get("ok", False))
        if not feature_store_reuse_ok:
            log(
                "[WARN] Existing feature store reuse skipped because fundamental coverage is still weak "
                f"(ttm_mean={feature_store_reuse_status.get('ttm_mean', 0.0):.1%}, "
                f"valuation_mean={feature_store_reuse_status.get('valuation_mean', 0.0):.1%}, "
                f"latest_rows={int(feature_store_reuse_status.get('latest_rows', 0))})."
            )
    if feature_store_reuse_ok:
        log("Phase 1/2/3: reusing existing feature store ...")
        feature_store = pd.read_parquet(feature_store_path)
        save_stage_flag(
            paths,
            "phase1_to_phase3_data",
            "reused",
            {
                "rows": int(len(feature_store)),
                "fingerprint": phase13_fp,
                "coverage_status": feature_store_reuse_status,
            },
        )
    else:
        feature_store = build_feature_store(cfg)
        save_stage_flag(paths, "phase1_to_phase3_data", "completed", {"rows": int(len(feature_store)), "fingerprint": phase13_fp})

    scored_path = paths["feature_store"] / "scored_oos_latest.parquet"
    cached_bundle = load_model_bundle_json(paths)
    if cfg.reuse_existing_artifacts and stage_is_reusable(flags, "phase4_modeling", phase4_fp) and scored_path.exists() and cached_bundle is not None:
        log("Phase 4: reusing existing walk-forward outputs ...")
        model_bundle = cached_bundle
        save_stage_flag(
            paths,
            "phase4_modeling",
            "reused",
            {
                "oos_rows": model_bundle.oos_rows,
                "ranking_metrics": model_bundle.ranking_metrics,
                "target_spec": model_bundle.target_spec,
                "fingerprint": phase4_fp,
            },
        )
    else:
        model_bundle = train_walkforward(cfg, feature_store)
        save_stage_flag(
            paths,
            "phase4_modeling",
            "completed",
            {
                "oos_rows": model_bundle.oos_rows,
                "ranking_metrics": model_bundle.ranking_metrics,
                "target_spec": model_bundle.target_spec,
                "fingerprint": phase4_fp,
            },
        )

    scored = pd.read_parquet(scored_path)
    bt = backtest_portfolio(cfg, scored)
    save_stage_flag(paths, "phase5_backtest", "completed", {"months": int(bt.metrics.get("months", 0))})

    # Phase 5c: Sleeve/cap policy optimization (OOS champion selection)
    sleeve_cap_policy_compare = pd.DataFrame()
    selected_sleeve_cap_policy: dict[str, Any] = {}
    if bool(getattr(cfg, "run_sleeve_cap_policy_comparison", True)):
        log("Phase 5c: running sleeve/cap policy comparison ...")
        try:
            sleeve_cap_policy_compare = compare_sleeve_cap_policy_backtests(cfg, scored)
            selected_sleeve_cap_policy = choose_sleeve_cap_policy(sleeve_cap_policy_compare)
            if bool(getattr(cfg, "sleeve_cap_policy_apply_champion", True)) and selected_sleeve_cap_policy:
                cfg = apply_sleeve_cap_policy_to_cfg(cfg, selected_sleeve_cap_policy)
                log(f"[INFO] Applied champion sleeve/cap policy: {selected_sleeve_cap_policy.get('sleeve_cap_policy_name', '?')}")
                bt = backtest_portfolio(cfg, scored)
                save_stage_flag(
                    paths,
                    "phase5_backtest",
                    "completed",
                    {
                        "months": int(bt.metrics.get("months", 0)),
                        "sleeve_cap_policy_applied": True,
                        "sleeve_cap_policy_name": str(selected_sleeve_cap_policy.get("sleeve_cap_policy_name", "")),
                    },
                )
        except Exception as exc:
            log(f"[WARN] Sleeve cap policy comparison failed: {exc}")
    save_stage_flag(paths, "phase5c_sleeve_cap_policy", "completed", {"candidates": int(len(sleeve_cap_policy_compare))})

    # Phase 5d: Standalone per-sleeve top-N backtest comparisons
    standalone_sleeve_compare = pd.DataFrame()
    standalone_sleeve_monthly = pd.DataFrame()
    standalone_sleeve_holdings = pd.DataFrame()
    if bool(getattr(cfg, "run_standalone_sleeve_backtest_comparison", True)):
        log("Phase 5d: running standalone sleeve top-N backtest comparisons ...")
        try:
            standalone_sleeve_compare, standalone_sleeve_monthly, standalone_sleeve_holdings = (
                compare_standalone_sleeve_topn_backtests(
                    cfg,
                    scored,
                    top_n=int(getattr(cfg, "standalone_sleeve_top_n", 7)),
                    intervals=list(getattr(cfg, "standalone_sleeve_rebalance_intervals", [1, 3])),
                    active_backtest=bt,
                )
            )
        except Exception as exc:
            log(f"[WARN] Standalone sleeve comparison failed: {exc}")
    save_stage_flag(paths, "phase5d_standalone_sleeve", "completed", {"rows": int(len(standalone_sleeve_compare))})

    concentrated_compare = pd.DataFrame()
    concentrated_monthly = pd.DataFrame()
    concentrated_holdings = pd.DataFrame()
    if bool(getattr(cfg, "run_concentrated_backtest_comparison", True)):
        log("Phase 5e: running concentrated alpha backtest comparisons ...")
        try:
            concentrated_compare, concentrated_monthly, concentrated_holdings = (
                compare_concentrated_portfolio_backtests(
                    cfg,
                    scored,
                    top_n_candidates=list(getattr(cfg, "concentrated_top_n_candidates", [1, 2, 3])),
                    intervals=list(getattr(cfg, "concentrated_rebalance_intervals", [1])),
                    weighting_modes=list(getattr(cfg, "concentrated_weighting_modes", ["conviction_curve", "winner_take_all"])),
                )
            )
        except Exception as exc:
            log(f"[WARN] Concentrated alpha comparison failed: {exc}")
    save_stage_flag(paths, "phase5e_concentrated_alpha", "completed", {"rows": int(len(concentrated_compare))})

    ai_four_sleeve_compare = pd.DataFrame()
    ai_four_sleeve_regime_grid = pd.DataFrame()
    ai_four_sleeve_regime_best = pd.DataFrame()
    ai_four_sleeve_selected_map: dict[str, Any] = {}
    if bool(getattr(cfg, "run_ai_four_sleeve_comparison", True)):
        log("Phase 5e: running adaptive 4-sleeve (core/future/early/cash) comparison ...")
        try:
            (
                ai_four_sleeve_compare,
                ai_four_sleeve_regime_grid,
                ai_four_sleeve_regime_best,
                ai_four_sleeve_selected_map,
                _,
            ) = compare_ai_four_sleeve_adaptive_model(cfg, scored, active_backtest=bt)
        except Exception as exc:
            log(f"[WARN] Adaptive 4-sleeve comparison failed: {exc}")
    save_stage_flag(paths, "phase5e_ai_four_sleeve", "completed", {"rows": int(len(ai_four_sleeve_compare))})

    try:
        latest_recommendations = build_latest_recommendations(cfg, feature_store)
    except Exception as exc:
        latest_recommendations = fallback_latest_recommendations_from_scored(
            cfg,
            paths,
            feature_store,
            scored,
            reason=exc,
        )
    checks = run_acceptance_checks(cfg, paths, feature_store, scored, bt)
    save_stage_flag(paths, "acceptance_checks", "completed", checks)
    if not checks.get("backtest_usable", False):
        log(
            "[WARN] Backtest is not production-usable. "
            f"research_only={checks.get('backtest_research_only', True)}, "
            f"fundamental_coverage_ok={checks.get('fundamental_coverage_ok', False)}, "
            f"historical_membership_ok={checks.get('historical_membership_ok', False)}"
        )
    research_only_portfolio = pd.DataFrame(
        columns=["rank", "ticker", "Name", "sector", "weight", "selected_for_portfolio", "rebalance_date"]
    )
    if bool(cfg.require_acceptance_for_portfolio_export) and not checks.get("backtest_usable", False):
        log("[WARN] Latest operational portfolio build skipped because acceptance hard gate is active.")
        latest_portfolio = pd.DataFrame(
            columns=["rank", "ticker", "Name", "sector", "weight", "selected_for_portfolio", "rebalance_date"]
        )
        research_only_portfolio = build_latest_portfolio(cfg, latest_recommendations)
        log(f"[INFO] Research-only portfolio built with {len(research_only_portfolio)} names.")
    else:
        latest_portfolio = build_latest_portfolio(cfg, latest_recommendations)
    save_stage_flag(
        paths,
        "phase5b_latest_recommendations",
        "completed",
        {
            "latest_rows": int(len(latest_recommendations)),
            "portfolio_rows": int(len(latest_portfolio)),
            "research_only_portfolio_rows": int(len(research_only_portfolio)),
            "portfolio_blocked": bool(cfg.require_acceptance_for_portfolio_export and not checks.get("backtest_usable", False)),
        },
    )

    output_paths = export_outputs(
        cfg,
        {
            "scored": scored,
            "backtest": bt,
            "model_bundle": model_bundle,
            "latest_recommendations": latest_recommendations,
            "latest_portfolio": latest_portfolio,
            "research_only_portfolio": research_only_portfolio,
            "acceptance_checks": checks,
            "sleeve_cap_policy_compare": sleeve_cap_policy_compare,
            "selected_sleeve_cap_policy": selected_sleeve_cap_policy,
            "standalone_sleeve_compare": standalone_sleeve_compare,
            "standalone_sleeve_monthly": standalone_sleeve_monthly,
            "standalone_sleeve_holdings": standalone_sleeve_holdings,
            "concentrated_compare": concentrated_compare,
            "concentrated_monthly": concentrated_monthly,
            "concentrated_holdings": concentrated_holdings,
            "ai_four_sleeve_compare": ai_four_sleeve_compare,
            "ai_four_sleeve_regime_grid": ai_four_sleeve_regime_grid,
            "ai_four_sleeve_regime_best": ai_four_sleeve_regime_best,
            "ai_four_sleeve_selected_map": ai_four_sleeve_selected_map,
        },
    )
    save_stage_flag(paths, "phase6_export", "completed", output_paths)
    if bool(cfg.show_output_previews_after_run):
        log("Phase 6b: previewing latest output tables ...")
        show_output_table_previews(output_paths)
    save_stage_flag(paths, "done", "completed")

    return {
        "phase0": p0,
        "feature_store_rows": int(len(feature_store)),
        "model_bundle": asdict(model_bundle),
        "backtest_metrics": bt.metrics,
        "latest_recommendation_rows": int(len(latest_recommendations)),
        "latest_portfolio_rows": int(len(latest_portfolio)),
        "research_only_portfolio_rows": int(len(research_only_portfolio)),
        "acceptance_checks": checks,
        "outputs": output_paths,
    }


DEFAULT_CFG = asdict(EngineConfig())


if __name__ == "__main__":
    result = run_default_pipeline(DEFAULT_CFG)
    print(json.dumps(result.get("outputs", {}), indent=2))
    print(json.dumps(result.get("acceptance_checks", {}), indent=2))
