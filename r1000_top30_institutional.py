"""
 Russell 1000 proxy top-candidate institutional-grade engine for Google Colab.

Key properties:
- One-click Colab + Google Drive workflow.
- Incremental caches for prices, FSDS, and metadata.
- Point-in-time (PIT) approximated monthly universe using liquidity/size filters.
- PIT fundamentals joined by SEC accepted timestamp.
- Monthly walk-forward training with embargo (look-ahead protection).
- Linear + CatBoost ensemble with GPU fallback.
- Portfolio construction with inverse-vol weighting, stock/sector caps, turnover cap, and costs.
- Exports top-candidate/scored/metrics/equity/summary files to Drive.
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
from typing import Any, Dict, Iterable, Optional

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



# =====================================================================
# Refactor Phase A Stage 5 (2026-04-20): FACADE
# =====================================================================
# All pipeline orchestration + training + backtest + export moved to
# r1000_pipeline.py. This file is now a facade that re-exports everything
# so existing `from r1000_top30_institutional import FN` imports still work.
#
# If you are editing the engine code, go to the appropriate module:
#   r1000_config.py     -- constants, EngineConfig
#   r1000_helpers.py    -- stats, IO, cache, CIK helpers
#   r1000_features.py   -- feature engineering (industry, fund, macro, blueprint)
#   r1000_signals.py    -- sleeve composition, portfolio construction
#   r1000_pipeline.py   -- training, backtest, export, run_all
#
# DO NOT add new code to this file -- it should remain a pure re-export layer.

from r1000_pipeline import *  # noqa: F401,F403

# Explicit re-exports for names that may be missed by `import *` (e.g.
# names starting with underscore, or names imported-but-not-defined in pipeline).
# Most names are already covered by the star import above; this list captures
# the ones external scripts (colab_run.ipynb, run_local.py, collector) rely on.
from r1000_pipeline import (  # noqa: F401
    run_all,
    run_default_pipeline,
    run_last_n_years_backtest,
    run_acceptance_checks,
    backtest_portfolio,
    train_walkforward,
    export_outputs,
    validate_config,
    build_feature_store,
    build_universe_monthly,
    build_latest_portfolio,
    build_latest_recommendations,
    ModelBundle,
    BacktestResult,
    DEFAULT_CFG,
)


if __name__ == "__main__":
    import json as _json
    result = run_default_pipeline(DEFAULT_CFG)
    print(_json.dumps(result.get("acceptance_checks", {}), indent=2))
