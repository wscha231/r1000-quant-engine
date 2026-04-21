"""r1000 Quant Engine — sleeve composition + portfolio construction signals.

Stage 4a (2026-04-20): sleeve composition extracted from
r1000_top30_institutional.py during Refactor Phase A.

Owns:
  - sleeve_weight_l1_norm            -- L1 norm of sleeve weight pairs
  - resolve_regime_sleeve_multipliers -- regime-conditional sleeve multipliers
  - add_historical_data_quality_columns -- data quality flag appender
  - compute_portfolio_sleeve_columns  (1,028L) -- THE sleeve composite + Phase 9 C1+C2+C3 gate
  - compute_portfolio_sleeve_policy   (222L)   -- sleeve target weights

Import discipline
-----------------
    r1000_config.py       (pure data, stdlib)
        ^
        |
    r1000_helpers.py      (pure helpers, numpy/pandas)
        ^
        |
    r1000_features.py     (feature engineering)
        ^
        |
    r1000_signals.py      (sleeve composition, portfolio construction)
        ^
        |
    r1000_top30_institutional.py  (main pipeline orchestration)

r1000_signals.py may import from r1000_config / r1000_helpers / r1000_features
but NEVER from the main engine.
"""
from __future__ import annotations

import math
from typing import Any, Optional

import numpy as np
import pandas as pd

from r1000_helpers import (
    cross_sectional_robust_z,
    cross_sectional_robust_z_by_sector,
    hard_sanitize,
    log,
    numeric_series_or_default,
    phase_is_enabled,
    robust_z,
    rolling_robust_z,
    row_mean,
    safe_float,
    squeeze_series,
    to_cfg,
    weighted_sleeve_composite,
    winsorize,
)
from r1000_features import (
    compute_minervini_momentum_overlay,
    count_present_columns,
    datetime_series_or_default,
    has_present_value,
    normalized_sector_labels,
    sector_keyword_mask,
)
from r1000_config import (
    CASH_PROXY_TICKER,
    CRISIS_SECTOR_BENEFICIARIES,
    default_manual_regime_conditioned_sleeve_map,
    EngineConfig,
    FORWARD_RETURN_COVERAGE_COLUMNS,
    HISTORICAL_DATA_QUALITY_COLUMNS,
    HISTORICAL_FUNDAMENTAL_CAGR_COLUMNS,
    HISTORICAL_FUNDAMENTAL_CHANGE_COLUMNS,
    HISTORICAL_FUNDAMENTAL_LEVEL_COLUMNS,
    HISTORICAL_FUNDAMENTAL_QUALITY_COLUMNS,
    SLEEVE_FACTOR_REGIME_MULTIPLIERS,
    SLEEVE_FACTOR_REGIME_MULTIPLIER_CLAMP,
)


# =====================================================================
# Stage 4a: sleeve composition (2026-04-20)
# =====================================================================
# 5 functions total. compute_portfolio_sleeve_columns is THE sleeve composite
# + Phase 9 C1 (multi_year rebalance) + C2 (percentile thesis gate) + C3
# (EPS turn-positive) gate. compute_portfolio_sleeve_policy produces the
# sleeve target weight trio (core / future / early) based on regime.

def sleeve_weight_l1_norm(weight_pairs: list[tuple[float, pd.Series]]) -> float:
    """Phase 3 diagnostic: absolute sum of weights for a sleeve composite.

    This is the L1 norm the composite would be normalised by when
    `sleeve_weight_renorm_enabled=True` and `sleeve_weight_l1_target=0.0`.
    Emitted as a per-run scalar column so A/B comparisons can measure how
    much Phase 1+2 inflated the baseline L1.
    """
    return float(sum(abs(float(w)) for w, _ in weight_pairs if _ is not None))


def resolve_regime_sleeve_multipliers(
    regime_label: str,
    user_table: Optional[dict[str, dict[str, float]]] = None,
) -> dict[str, float]:
    """Resolve Phase 4 per-sleeve multiplier for a given regime label.

    Lookup precedence:
      1. `user_table` (EngineConfig.regime_sleeve_multiplier_table override)
      2. Built-in `SLEEVE_FACTOR_REGIME_MULTIPLIERS`
      3. Identity {core=1.0, future=1.0, early=1.0} — forward-compat fallback
         for unknown regime labels (so the engine never crashes on a new
         regime that someone adds upstream without also updating this
         table).

    The returned dict is always clamped element-wise to
    `SLEEVE_FACTOR_REGIME_MULTIPLIER_CLAMP` so a bad user override
    can't explode the composite.
    """
    identity = {"core": 1.0, "future": 1.0, "early": 1.0}
    label = (regime_label or "").strip()
    if not label:
        return dict(identity)
    lo, hi = SLEEVE_FACTOR_REGIME_MULTIPLIER_CLAMP
    found: dict[str, float] = {}
    if isinstance(user_table, dict) and label in user_table and isinstance(user_table[label], dict):
        found = {str(k): float(v) for k, v in user_table[label].items() if v is not None}
    elif label in SLEEVE_FACTOR_REGIME_MULTIPLIERS:
        found = {k: float(v) for k, v in SLEEVE_FACTOR_REGIME_MULTIPLIERS[label].items()}
    merged = dict(identity)
    for k in identity.keys():
        if k in found and np.isfinite(found[k]):
            merged[k] = float(np.clip(found[k], lo, hi))
    return merged


def add_historical_data_quality_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Add PIT-safe data quality diagnostics; forward returns are report-only."""
    d = df.copy()
    for c in HISTORICAL_DATA_QUALITY_COLUMNS:
        if c not in d.columns:
            d[c] = np.nan
    if d.empty:
        return d

    def _presence(cols: list[str]) -> pd.Series:
        if not cols:
            return pd.Series(0.0, index=d.index, dtype=float)
        return (count_present_columns(d, cols).astype(float) / float(len(cols))).clip(lower=0.0, upper=1.0)

    level_cov = _presence(HISTORICAL_FUNDAMENTAL_LEVEL_COLUMNS)
    change_cov = _presence(HISTORICAL_FUNDAMENTAL_CHANGE_COLUMNS)
    cagr_cov = _presence(HISTORICAL_FUNDAMENTAL_CAGR_COLUMNS)
    quality_cov = _presence(HISTORICAL_FUNDAMENTAL_QUALITY_COLUMNS)
    history_quarters = numeric_series_or_default(d, "fund_history_quarters_available", 0.0).clip(lower=0.0)
    depth_3y = (history_quarters / 12.0).clip(lower=0.0, upper=1.0)
    depth_5y = (history_quarters / 20.0).clip(lower=0.0, upper=1.0)
    fund_history_score = (
        0.20 * level_cov
        + 0.25 * change_cov
        + 0.25 * cagr_cov
        + 0.15 * quality_cov
        + 0.15 * depth_3y
    ).clip(lower=0.0, upper=1.0)

    market_confirmation = numeric_series_or_default(d, "selection_market_confirmation_score", 0.0).clip(
        lower=0.0,
        upper=1.0,
    )
    technical_confirmation = row_mean(
        [
            market_confirmation,
            numeric_series_or_default(d, "minervini_momentum_alive_score", 0.0).clip(lower=0.0, upper=1.0),
            numeric_series_or_default(d, "breakout_setup_quality_score", 0.0).clip(lower=0.0, upper=1.0),
            numeric_series_or_default(d, "technical_blueprint_score", 0.0).clip(lower=0.0, upper=1.0),
            (numeric_series_or_default(d, "rs_benchmark_6m", 0.0) > 0.0).astype(float),
        ],
        d.index,
    ).fillna(0.0).clip(lower=0.0, upper=1.0)

    sleeve_data_confidence = np.maximum(
        fund_history_score,
        (0.55 * technical_confirmation + 0.25 * level_cov + 0.10 * depth_3y).clip(lower=0.0, upper=0.90),
    )
    sparse_penalty = ((0.45 - fund_history_score).clip(lower=0.0) / 0.45).clip(0.0, 1.0)
    sparse_penalty = (sparse_penalty * (1.0 - technical_confirmation)).clip(0.0, 1.0)
    labels = np.where(
        fund_history_score >= 0.70,
        "full_history",
        np.where(
            fund_history_score >= 0.45,
            "usable_history",
            np.where(fund_history_score >= 0.25, "sparse_growth_history", "latest_or_price_only"),
        ),
    )

    d["fundamental_history_level_coverage"] = level_cov
    d["fundamental_history_change_coverage"] = change_cov
    d["fundamental_history_cagr_coverage"] = cagr_cov
    d["fundamental_history_quality_coverage"] = quality_cov
    d["fundamental_history_depth_3y_score"] = depth_3y
    d["fundamental_history_depth_5y_score"] = depth_5y
    d["fundamental_history_coverage_score"] = fund_history_score
    d["growth_sleeve_technical_confirmation_score"] = technical_confirmation
    d["growth_sleeve_data_confidence"] = pd.Series(sleeve_data_confidence, index=d.index, dtype=float).clip(0.0, 1.0)
    d["growth_sleeve_sparse_history_penalty"] = pd.Series(sparse_penalty, index=d.index, dtype=float).clip(0.0, 1.0)
    d["data_history_quality_label"] = pd.Series(labels, index=d.index, dtype=object)
    d["forward_return_coverage_score"] = _presence(FORWARD_RETURN_COVERAGE_COLUMNS)
    return d


def compute_portfolio_sleeve_columns(df: pd.DataFrame, cfg: Optional[EngineConfig] = None) -> pd.DataFrame:
    d = df.copy()
    if d.empty:
        for c in [
            "portfolio_core_compounder_engine_score",
            "portfolio_future_winner_engine_score",
            "portfolio_early_scout_engine_score",
            "portfolio_sleeve_label",
            "portfolio_sleeve_confidence",
            # Phase 3 diagnostics — keep schema stable when the frame is empty.
            "sleeve_core_l1_norm",
            "sleeve_future_l1_norm",
            "sleeve_early_l1_norm",
            "sleeve_weight_renorm_active",
            "sleeve_future_penalty_scale",
            "sleeve_early_penalty_scale",
            # Phase 4 diagnostics — regime-conditional sleeve multipliers.
            "regime_sleeve_multiplier_core",
            "regime_sleeve_multiplier_future",
            "regime_sleeve_multiplier_early",
            "regime_sleeve_weights_active",
            # Phase 7a diagnostic — insider + accruals wiring flag.
            "phase7a_insider_accruals_active",
        ] + HISTORICAL_DATA_QUALITY_COLUMNS:
            d[c] = np.nan
        return d
    if "minervini_momentum_alive_score" not in d.columns:
        d = compute_minervini_momentum_overlay(d)
    d = add_historical_data_quality_columns(d)

    minervini_future_engine_weight = float(
        getattr(cfg, "minervini_future_engine_weight", EngineConfig.minervini_future_engine_weight)
    )
    growth_history_penalty_weight = float(
        getattr(
            cfg,
            "growth_history_confidence_penalty_weight",
            EngineConfig.growth_history_confidence_penalty_weight,
        )
    )
    growth_history_confidence_floor = float(
        getattr(
            cfg,
            "growth_history_confidence_min_for_full_sleeve",
            EngineConfig.growth_history_confidence_min_for_full_sleeve,
        )
    )
    dominant_archetype = d.get("dominant_archetype_label", pd.Series("", index=d.index, dtype=str)).astype(str)
    history_depth_raw = numeric_series_or_default(d, "fund_history_quarters_available", 0.0).astype(float)
    history_depth = pd.Series(
        np.clip(history_depth_raw.to_numpy(dtype=float), 0.0, 16.0) / 16.0,
        index=d.index,
        dtype=float,
    )
    sage_composite_rank = cross_sectional_robust_z(d, "sage_composite_score")
    sage_g_rank = cross_sectional_robust_z(d, "sage_g_score")
    sage_v_rank = cross_sectional_robust_z(d, "sage_v_score")
    sage_q_rank = cross_sectional_robust_z(d, "sage_q_score")
    sage_c_rank = cross_sectional_robust_z(d, "sage_c_score")

    # -------------------------------------------------------------------
    # Phase 3: resolve sleeve-weight renormalisation toggle once per call.
    # Both the cfg field AND the env-var gate must be on; the env gate
    # lets QUICK_RESCORE A/B runs flip Phase 3 without editing the cfg.
    # Defensive handling when cfg is None so legacy call-sites don't
    # accidentally crash.
    # -------------------------------------------------------------------
    _phase3_cfg_on = bool(getattr(cfg, "sleeve_weight_renorm_enabled", False)) if cfg is not None else False
    _phase3_env_on = phase_is_enabled("phase3_renorm", default=False)
    _phase3_renorm_active = bool(_phase3_cfg_on and _phase3_env_on)
    _phase3_l1_target = float(
        getattr(cfg, "sleeve_weight_l1_target", EngineConfig.sleeve_weight_l1_target)
        if cfg is not None
        else EngineConfig.sleeve_weight_l1_target
    )

    # -------------------------------------------------------------------
    # Phase 4: regime-conditional sleeve multipliers (PHASE_ROADMAP §2.4).
    # Dual-gate toggle (cfg + env), both must be on. Default OFF until
    # A/B measurement validates positive CAGR+Sharpe contribution.
    # -------------------------------------------------------------------
    _phase4_cfg_on = (
        bool(getattr(cfg, "regime_dynamic_sleeve_weights_enabled", False))
        if cfg is not None
        else False
    )
    _phase4_env_on = phase_is_enabled("phase4_regime_weights", default=False)
    _phase4_regime_active = bool(_phase4_cfg_on and _phase4_env_on)
    _phase4_user_table = (
        getattr(cfg, "regime_sleeve_multiplier_table", None) if cfg is not None else None
    )

    # -------------------------------------------------------------------
    # Phase 7a: insider flow + accruals quality sleeve wiring.
    # Default OFF. Pulls weights from cfg so they can be tuned without
    # editing the weight-pair tables directly.
    # -------------------------------------------------------------------
    _phase7a_cfg_on = (
        bool(getattr(cfg, "phase7a_insider_accruals_enabled", False))
        if cfg is not None
        else False
    )
    _phase7a_env_on = phase_is_enabled("phase7a_insider_accruals", default=False)
    _phase7a_active = bool(_phase7a_cfg_on and _phase7a_env_on)
    _p7a_w_insider_early = float(
        getattr(cfg, "phase7a_insider_early_weight", 0.25) if cfg is not None else 0.25
    )
    _p7a_w_insider_future = float(
        getattr(cfg, "phase7a_insider_future_weight", 0.15) if cfg is not None else 0.15
    )
    _p7a_w_accruals_core = float(
        getattr(cfg, "phase7a_accruals_core_weight", -0.20) if cfg is not None else -0.20
    )

    # -------------------------------------------------------------------
    # Phase 5 dilution fix (2026-04-17 post-mortem): the bonus/penalty
    # signals fire on only ~3-4% of rows (bonus) / ~0% (penalty) because
    # they require a strong industry_group AND a gap > 0.8 std threshold.
    # If we hand the raw z-scores to `row_mean` via the weight-pair table
    # the `N` denominator grows by +2 for future / +1 for core / +1 for
    # early while the numerator barely changes -> ~6% dilution of every
    # other factor on every sleeve. Masking the zeros to NaN lets
    # row_mean drop them from BOTH the numerator and denominator, so a
    # row with no Phase 5 signal contributes 0 effect (same as legacy)
    # instead of a subtle drag.
    _p5_bonus_raw = numeric_series_or_default(d, "industry_leader_bonus_score", 0.0)
    _p5_penalty_raw = numeric_series_or_default(d, "industry_laggard_penalty_score", 0.0)
    _p5_bonus_z = cross_sectional_robust_z(d, "industry_leader_bonus_score").where(
        _p5_bonus_raw != 0.0, np.nan
    )
    _p5_penalty_z = cross_sectional_robust_z(d, "industry_laggard_penalty_score").where(
        _p5_penalty_raw != 0.0, np.nan
    )

    # -------------------------------------------------------------------
    # Phase 8a.1 (2026-04-17): drop negative-IC factors from sleeve
    # weight tables. Factor IC measurement over 83 months (see
    # DIAGNOSIS_FACTOR_IC.md) revealed:
    #   - quality_trend_score        IC -0.0042  (w=1.00 in core)  -> drop
    #   - selection_confirmation_score IC -0.0028 (w=0.55 in core) -> drop
    #   - industry_rotation_signal   IC -0.0117  (w=0.18 future, 0.45 early) -> drop
    #   - archetype_defensive_value_score IC -0.0061 -> drop wherever referenced
    # These factors have statistically-significant NEGATIVE alpha, so
    # keeping them in the composite actively hurts CAGR and Sharpe.
    # Gated behind env toggle so we can A/B the marginal effect; default
    # TRUE (drop is active by default).
    # -------------------------------------------------------------------
    _phase8a_neg_ic_drop = phase_is_enabled("phase8a_neg_ic_drop", default=True)

    # Weight-0 when drop is active; original value when toggle OFF.
    # This preserves the (weight, series) table structure so A/B runs
    # can diff the sleeve composite byte-exactly.
    _w_quality_trend_core = 0.0 if _phase8a_neg_ic_drop else 1.00
    _w_selection_confirm_core = 0.0 if _phase8a_neg_ic_drop else 0.55
    _w_industry_rotation_future = 0.0 if _phase8a_neg_ic_drop else 0.18
    _w_industry_rotation_early = 0.0 if _phase8a_neg_ic_drop else 0.45

    # -------------------------------------------------------------------
    # Phase 15-S1a (2026-04-21): drop 3 factors from future_winner composite
    # whose 94-month rank-IC is negative at BOTH 1m and 3m horizons
    # (research/phase15_s1_future_winner_factor_ic.csv):
    #   fundamental_turnaround_acceleration_score (w=0.50, IR_1m=-0.19, IR_3m=-0.27)
    #   cashflow_inflection_under_loss_score      (w=0.35, IR_1m=-0.15, IR_3m=-0.20)
    #   uptrend_breakdown_penalty                 (w=-0.30, IR_3m=-2.03 sign flip)
    # future_winner topn_cagr_1m = 16.08% (weakest sleeve). These factors
    # add noise across horizons; removing them should cleanly tighten the
    # composite. Dual-gate A/B pattern (cfg + env). Default OFF.
    # Core and early sleeves keep their original weights (only future audited).
    # -------------------------------------------------------------------
    # Gate semantics: env var OVERRIDES cfg default (matches Phase 11 fix 980aed9).
    # env=1 -> active regardless of cfg; env=0 -> inactive regardless of cfg;
    # env unset -> use cfg default. Lets A/B runs flip via env without editing cfg.
    _phase15_s1a_cfg = bool(getattr(cfg, "phase15_s1a_future_prune_enabled", False)) if cfg is not None else False
    _phase15_s1a_active = phase_is_enabled("phase15_s1a_future_prune", default=_phase15_s1a_cfg)
    _w_fund_turnaround_future = 0.0 if _phase15_s1a_active else 0.50
    _w_cashflow_inflection_future = 0.0 if _phase15_s1a_active else 0.35
    _w_uptrend_breakdown_future = 0.0 if _phase15_s1a_active else -0.30

    # -------------------------------------------------------------------
    # Phase 8a.4 (2026-04-17): hold persistence bonus.
    # The 2026-04-17 FULL rebuild measured avg_turnover_monthly = 49.5%
    # (~600%/yr) with an estimated 3pp/yr CAGR cost in round-trip trading
    # fees. Root cause: every month the ensemble re-ranks 600 names, and
    # small score shuffles at the edge of the top-N cutoff flip names in
    # and out. Counterfactual (DIAGNOSIS_COUNTERFACTUAL.md §2) estimates
    # reducing to 25%/month turnover would save +1.5pp CAGR from costs.
    #
    # Mechanism: reward names that (a) were held last month AND (b) are
    # still trending up AND (c) have a positive recent 1-month return.
    # This shifts the ranking in favour of already-held winners so we
    # don't whipsaw out of NVDA-style multi-year compounders on a single
    # bad month.
    #
    # Factors:
    #   held              = was this name in last month's portfolio? (0/1)
    #   recent_win        = last month's realised return > 0? (0/1)
    #   long_trend_alive  = mom_12m z-score > 0? (0/1)
    # bonus = 0.80*held + 0.50*held*recent_win + 0.70*held*long_trend_alive
    #       (max ~2.0 — applied with weight +0.9 in each sleeve)
    #
    # Gated behind `phase8a_hold_persistence` env toggle (default True)
    # and `cfg.phase8a_hold_persistence_enabled` (default True). Both
    # must be on; either off = legacy behaviour (weight 0 = no bonus).
    # -------------------------------------------------------------------
    _phase8a_hold_env = phase_is_enabled("phase8a_hold_persistence", default=True)
    _phase8a_hold_cfg = bool(getattr(cfg, "phase8a_hold_persistence_enabled", True)) if cfg is not None else True
    _phase8a_hold_active = bool(_phase8a_hold_env and _phase8a_hold_cfg)

    # -------------------------------------------------------------------
    # Phase 8d.1 (2026-04-17): IC-proportional weight boost for two
    # specific underweighted factors. Factor IC measurement
    # (DIAGNOSIS_FACTOR_IC.md) over 83 OOS months identified:
    #   - `strategy_blueprint_score`       IC +0.0166 (highest in core!)
    #     currently w=0.25 in core — underweighted by ~4x given IC rank
    #   - `industry_group_strength_score`  IC +0.0155
    #     currently w=0.10 in core (lowest in table) and w=0.30 in future
    #     — both sleeves systematically discounting a high-IC factor
    # Conservative 8d: boost THESE TWO factors only. No other weights
    # changed. Correlation-risk mitigated because the two factors measure
    # unrelated concepts (blueprint = overall strategy composite;
    # group_strength = industry rotation). Gated behind the same dual-gate
    # pattern; when inactive, fall back to legacy weights for byte-
    # identical A/B comparison.
    # -------------------------------------------------------------------
    _phase8d_env = phase_is_enabled("phase8d_ic_reweight", default=True)
    _phase8d_cfg = bool(getattr(cfg, "phase8d_ic_reweight_enabled", True)) if cfg is not None else True
    _phase8d_active = bool(_phase8d_env and _phase8d_cfg)
    # Weights chosen to approximately match IC rank proportion.
    _w_strategy_blueprint_core = 1.00 if _phase8d_active else 0.25
    _w_industry_grp_strength_core = 0.50 if _phase8d_active else 0.10
    _w_industry_grp_strength_future = 0.60 if _phase8d_active else 0.30
    d["phase8d_ic_reweight_active"] = 1.0 if _phase8d_active else 0.0
    _w_hold_persistence = 0.90 if _phase8a_hold_active else 0.0
    _phase8a_hold_bonus_weight_each = float(
        getattr(cfg, "phase8a_hold_persistence_weight", 0.90) if cfg is not None else 0.90
    )
    _w_hold_persistence = _phase8a_hold_bonus_weight_each if _phase8a_hold_active else 0.0

    # -------------------------------------------------------------------
    # Phase 8b.1 (2026-04-17): long-lookback momentum sleeve wiring.
    # The `multi_year_winner_score` composite is already computed in
    # `build_universe_monthly` (weighted blend of z-scored mom_12m / 24m
    # / 36m, zero-masked where mom_24m is NaN). Wire it into the three
    # sleeves with sleeve-appropriate weights:
    #   future:  0.90 (primary — this is the NVDA/AVGO/MU catcher)
    #   early:   0.60 (supporting — early is bottom-fishing focus, but
    #            we still want to avoid bottom-fishing things in a
    #            declining multi-year trend)
    #   core:    0.40 (moderate — compounders already prize long-term
    #            records, so multi-year momentum reinforces the thesis)
    # Also wire `persistence_trend_24m` (binary 0/1 flag) into future
    # and core with smaller weights as a SELECTION gate — boost names
    # whose 3-year uptrend is "confirmed" by all three lookbacks.
    # Gated behind the same toggle as the feature-level block in
    # build_universe_monthly; when inactive the columns are 0, so the
    # weights have no effect.
    # -------------------------------------------------------------------
    _phase8b_active = bool(
        (getattr(cfg, "phase8b_long_lookback_enabled", True) if cfg is not None else True)
        and phase_is_enabled("phase8b_long_lookback", default=True)
    )
    if _phase8b_active:
        # Phase 9 C1 (2026-04-17): rebalance multi_year_winner sleeve weights.
        # Phase 8 measured run showed Future sleeve absorbing ~72% of portfolio
        # (target 45%) and Early sleeve collapsed to 0 names. Cause: future
        # weight 0.90 too dominant. Phase 9 C1 rebalances 0.50 / 0.80 / 0.30.
        # Toggle: PHASE_PHASE9_C1_REBALANCE_ENABLED + cfg.phase9_c1_rebalance_enabled.
        _phase9_c1_active = bool(
            (getattr(cfg, "phase9_c1_rebalance_enabled", True) if cfg is not None else True)
            and phase_is_enabled("phase9_c1_rebalance", default=True)
        )
        if _phase9_c1_active:
            _w_multi_year_future = float(
                getattr(cfg, "phase9_c1_multi_year_future_weight", 0.50) if cfg is not None else 0.50
            )
            _w_multi_year_early = float(
                getattr(cfg, "phase9_c1_multi_year_early_weight", 0.80) if cfg is not None else 0.80
            )
            _w_multi_year_core = float(
                getattr(cfg, "phase9_c1_multi_year_core_weight", 0.30) if cfg is not None else 0.30
            )
        else:
            # Legacy Phase 8b weights
            _w_multi_year_future = float(
                getattr(cfg, "phase8b_multi_year_future_weight", 0.90) if cfg is not None else 0.90
            )
            _w_multi_year_early = float(
                getattr(cfg, "phase8b_multi_year_early_weight", 0.60) if cfg is not None else 0.60
            )
            _w_multi_year_core = float(
                getattr(cfg, "phase8b_multi_year_core_weight", 0.40) if cfg is not None else 0.40
            )
        _w_persist_future = float(
            getattr(cfg, "phase8b_persistence_trend_future_weight", 0.50) if cfg is not None else 0.50
        )
        _w_persist_core = float(
            getattr(cfg, "phase8b_persistence_trend_core_weight", 0.30) if cfg is not None else 0.30
        )
        d["phase9_c1_rebalance_active"] = 1.0 if _phase9_c1_active else 0.0
    else:
        _w_multi_year_future = _w_multi_year_early = _w_multi_year_core = 0.0
        _w_persist_future = _w_persist_core = 0.0
        d["phase9_c1_rebalance_active"] = 0.0

    # Use the multi_year_winner_score column directly (already rank-z
    # and clipped in build_universe_monthly). Fallback to 0 if missing.
    _multi_year_winner = numeric_series_or_default(d, "multi_year_winner_score", 0.0).clip(-6.0, 6.0)
    _persistence_trend = numeric_series_or_default(d, "persistence_trend_24m", 0.0).clip(0.0, 1.0)
    d["phase8b_long_lookback_active"] = 1.0 if _phase8b_active else 0.0

    # -------------------------------------------------------------------
    # Phase 8d.2 (2026-04-17): long-horizon alpha composite. Factor IC
    # measurement showed fundamental factors have 2-4x stronger IC at
    # r_12m vs r_1m:
    #     factor               r_1m IC    r_12m IC    ratio
    #     ep_ttm               0.026      0.042       1.6x
    #     fcfy_ttm             0.025      0.050       2.0x
    #     sp_ttm               0.022      0.086       3.9x !!
    #     roe_proxy            0.016      0.035       2.2x
    #     sage_composite_score 0.022      0.052       2.4x
    # The walk-forward ensemble ML is trained against r_1m, so it
    # systematically under-weights these high-r_12m-IC factors. This
    # composite bypasses the ML ensemble's myopia by aggregating the
    # five best fundamental factors with weights approximately
    # proportional to their r_12m IC, then wiring the composite into
    # the sleeve tables with full weight. Achieves ~80% of the intended
    # benefit of a proper r_12m ML retraining (Phase 8e full) without
    # the walk-forward refactor risk.
    #
    # Toggle: PHASE_PHASE8D_LONG_HORIZON + cfg.phase8d_long_horizon_alpha_enabled
    # (dual-gate, both default True).
    # -------------------------------------------------------------------
    _phase8d_lh_env = phase_is_enabled("phase8d_long_horizon_alpha", default=True)
    _phase8d_lh_cfg = bool(getattr(cfg, "phase8d_long_horizon_alpha_enabled", True)) if cfg is not None else True
    _phase8d_lh_active = bool(_phase8d_lh_env and _phase8d_lh_cfg)
    if _phase8d_lh_active:
        _z_ep = cross_sectional_robust_z(d, "ep_ttm").fillna(0.0)
        _z_fcfy = cross_sectional_robust_z(d, "fcfy_ttm").fillna(0.0)
        _z_sp = cross_sectional_robust_z(d, "sp_ttm").fillna(0.0)
        _z_roe = cross_sectional_robust_z(d, "roe_proxy").fillna(0.0)
        _z_sage = cross_sectional_robust_z(d, "sage_composite_score").fillna(0.0)
        # Weights chosen approximately proportional to r_12m IC strength:
        #   sp_ttm (0.086) > fcfy_ttm (0.050) = sage (0.052) > ep_ttm (0.042) > roe (0.035)
        # Then L1-normalised internally via /1.30 so the downstream sleeve
        # weights on this composite stay in the same scale as other sleeve terms.
        _long_horizon_alpha_composite = (
            0.30 * _z_ep
            + 0.30 * _z_fcfy
            + 0.40 * _z_sp
            + 0.20 * _z_roe
            + 0.30 * _z_sage
        ).clip(lower=-6.0, upper=6.0)
        d["long_horizon_alpha_composite"] = _long_horizon_alpha_composite.values
        d["phase8d_long_horizon_alpha_active"] = 1.0
    else:
        _long_horizon_alpha_composite = pd.Series(0.0, index=d.index, dtype=float)
        d["long_horizon_alpha_composite"] = 0.0
        d["phase8d_long_horizon_alpha_active"] = 0.0
    # Sleeve weights for the composite (conservative — each sleeve gets
    # a modest weight, not a dominating one, to avoid over-concentration
    # on any single composite). Tunable via cfg.
    _w_lh_alpha_core = float(getattr(cfg, "phase8d_long_horizon_alpha_core_weight", 1.00) if cfg is not None else 1.00) if _phase8d_lh_active else 0.0
    _w_lh_alpha_future = float(getattr(cfg, "phase8d_long_horizon_alpha_future_weight", 0.60) if cfg is not None else 0.60) if _phase8d_lh_active else 0.0
    _w_lh_alpha_early = float(getattr(cfg, "phase8d_long_horizon_alpha_early_weight", 0.50) if cfg is not None else 0.50) if _phase8d_lh_active else 0.0

    # Build the bonus series. Use raw 0/1 masks (not z-scored) so the bonus
    # is a HARD additive preference rather than a relative rank nudge.
    # CRITICAL: do NOT use `r_1m` here — it's the FORWARD return (see line
    # 14110 where it's set to `forward_returns[cfg.target_1m_days]`) and
    # using it would introduce lookahead bias. Use `mom_1m` which is
    # `close.pct_change(21)` at the rebalance date = BACKWARD-looking
    # realised 21-day return.
    if _phase8a_hold_active:
        _held_from_prev = numeric_series_or_default(d, "held_from_prev_rebalance", 0.0).astype(float).clip(lower=0.0, upper=1.0)
        _recent_realised_mom_1m = numeric_series_or_default(d, "mom_1m", 0.0)  # PAST 21-day return (backward)
        _recent_win = (_recent_realised_mom_1m > 0.0).astype(float)
        _mom_12m_z_for_bonus = cross_sectional_robust_z(d, "mom_12m").fillna(0.0)
        _long_trend_alive = (_mom_12m_z_for_bonus > 0.0).astype(float)
        _hold_persistence_bonus = (
            0.80 * _held_from_prev
            + 0.50 * _held_from_prev * _recent_win
            + 0.70 * _held_from_prev * _long_trend_alive
        ).clip(lower=0.0, upper=2.0)
    else:
        _hold_persistence_bonus = pd.Series(0.0, index=d.index, dtype=float)

    # Expose as a column for diagnostic CSV / monthly audit.
    d["hold_persistence_bonus"] = _hold_persistence_bonus.values
    d["phase8a_hold_persistence_active"] = 1.0 if _phase8a_hold_active else 0.0

    core_weight_pairs: list[tuple[float, pd.Series]] = [
        (1.05, cross_sectional_robust_z(d, "long_hold_compounder_score")),
        (0.90, cross_sectional_robust_z(d, "archetype_compounder_score")),
        (1.10, cross_sectional_robust_z(d, "moat_quality_blueprint_score")),
        # Phase 8a.1: quality_trend_score has IC -0.0042 (see DIAGNOSIS_FACTOR_IC.md)
        (_w_quality_trend_core, cross_sectional_robust_z(d, "quality_trend_score")),
        (0.45, cross_sectional_robust_z(d, "garp_score")),
        (0.95, cross_sectional_robust_z(d, "actual_results_score")),
        # Phase 8a.1: selection_confirmation_score has IC -0.0028
        (_w_selection_confirm_core, cross_sectional_robust_z(d, "selection_confirmation_score")),
        # Phase 8d.1: strategy_blueprint_score IC +0.0166 (highest in core) — boosted 0.25 -> 1.00
        (_w_strategy_blueprint_core, cross_sectional_robust_z(d, "strategy_blueprint_score")),
        (0.35, cross_sectional_robust_z(d, "pricing_power_score")),
        (0.30, cross_sectional_robust_z(d, "margin_stability_8q")),
        (0.22, sage_q_rank),
        (0.12, sage_v_rank),
        (0.08, sage_c_rank),
        # Phase 1.4: Defend our existing winners — reward intact uptrends,
        # penalise broken ones.  These signals matter most on the core
        # sleeve where we want to avoid riding a name down through a real
        # thesis break.
        (0.40, cross_sectional_robust_z(d, "uptrend_continuation_score")),
        (-0.45, numeric_series_or_default(d, "uptrend_breakdown_penalty", 0.0)),
        # Phase 2.7: O'Neil leadership — only modest weight on core because
        # core compounders are already long-cycle plays where industry
        # leadership matters less than long-term moat quality.
        (0.25, cross_sectional_robust_z(d, "oneil_leadership_score")),
        # Phase 8d.1: industry_group_strength_score IC +0.0155 — boosted core 0.10 -> 0.50
        (_w_industry_grp_strength_core, cross_sectional_robust_z(d, "industry_group_strength_score")),
        # Phase 5: compounders also respect group-leader separation;
        # weight moderate so it doesn't overpower the moat/quality core.
        # Uses zero-masked z-score (see _p5_bonus_z above) so the
        # weight-pair is skipped on rows where Phase 5 didn't fire.
        (0.15, _p5_bonus_z),
        # Phase 7a: accruals quality penalty on core. High accruals
        # (net_income - OCF / assets) = earnings-quality risk (Sloan
        # effect). Low or negative accruals = quality signal. Weight
        # gated by `_phase7a_active` so toggle OFF is byte-identical.
        (
            _p7a_w_accruals_core if _phase7a_active else 0.0,
            cross_sectional_robust_z(d, "accruals_to_assets"),
        ),
        # Phase 8a.4: hold persistence bonus. Non-zero weight if
        # PHASE_PHASE8A_HOLD_PERSISTENCE=1 AND
        # cfg.phase8a_hold_persistence_enabled=True.
        (_w_hold_persistence, _hold_persistence_bonus),
        # Phase 8b.1: long-lookback multi-year winner score (moderate weight
        # on core — compounders already prize long records but extra
        # reward for multi-year winners keeps NVDA-style names in rotation).
        (_w_multi_year_core, _multi_year_winner),
        # Phase 8b.1: persistence_trend_24m binary confirmation.
        (_w_persist_core, _persistence_trend),
        # Phase 8d.2: long-horizon alpha composite (ep_ttm/fcfy_ttm/sp_ttm/
        # roe_proxy/sage_composite — high r_12m IC factors that ML ensemble
        # under-weights due to r_1m training target). Full weight on core
        # where quality + value + long-horizon fundamentals are the thesis.
        (_w_lh_alpha_core, _long_horizon_alpha_composite),
    ]
    core_score = weighted_sleeve_composite(
        core_weight_pairs,
        d.index,
        renorm_enabled=_phase3_renorm_active,
        l1_target=_phase3_l1_target,
    )
    future_weight_pairs: list[tuple[float, pd.Series]] = [
        (1.10, cross_sectional_robust_z(d, "future_winner_scout_score")),
        (0.95, cross_sectional_robust_z(d, "pred_future_winner_ret")),
        (0.40, cross_sectional_robust_z(d, "pred_future_winner_p")),
        (0.95, cross_sectional_robust_z(d, "anticipatory_growth_score")),
        (0.70, cross_sectional_robust_z(d, "archetype_emerging_growth_score")),
        (0.95, cross_sectional_robust_z(d, "dynamic_leader_score")),
        (0.90, cross_sectional_robust_z(d, "leader_emergence_score")),
        (0.90, cross_sectional_robust_z(d, "relative_strength_composite")),
        (0.95, cross_sectional_robust_z(d, "revision_blueprint_score")),
        (0.70, cross_sectional_robust_z(d, "analyst_revision_trend_score")),
        (0.65, cross_sectional_robust_z(d, "revision_score")),
        (0.60, cross_sectional_robust_z(d, "target_upside_pct")),
        (0.55, cross_sectional_robust_z(d, "revenue_growth_final")),
        (0.45, cross_sectional_robust_z(d, "earnings_growth_final")),
        # Phase 15-S1a: gated (default 0.50 / 0.35) — IR_1m -0.19 / -0.15
        (_w_fund_turnaround_future, cross_sectional_robust_z(d, "fundamental_turnaround_acceleration_score")),
        (_w_cashflow_inflection_future, cross_sectional_robust_z(d, "cashflow_inflection_under_loss_score")),
        (minervini_future_engine_weight, cross_sectional_robust_z(d, "minervini_momentum_alive_score")),
        (0.35, cross_sectional_robust_z(d, "breakout_setup_quality_score")),
        (0.36, sage_composite_rank),
        (0.18, sage_g_rank),
        (0.12, sage_c_rank),
        (0.10, sage_v_rank),
        (-0.35, numeric_series_or_default(d, "broken_momentum_penalty", 0.0)),
        # Phase 1.3 + 1.4: value-and-growth catch-up + uptrend defense.
        (0.45, cross_sectional_robust_z(d, "value_inflection_score")),
        (0.30, cross_sectional_robust_z(d, "uptrend_continuation_score")),
        # Phase 15-S1a: gated (default -0.30) — IR_3m=-2.03, penalty sign flipped
        (_w_uptrend_breakdown_future, numeric_series_or_default(d, "uptrend_breakdown_penalty", 0.0)),
        # Phase 2.7: industry leadership + group strength + rotation.
        # Future-winner sleeve gets the highest weight on these because
        # finding "the best name in the strongest group" is the core
        # O'Neil/IBD playbook this sleeve tries to execute.
        (0.55, cross_sectional_robust_z(d, "oneil_leadership_score")),
        # Phase 8d.1: industry_group_strength_score IC +0.0155 — boosted future 0.30 -> 0.60
        (_w_industry_grp_strength_future, cross_sectional_robust_z(d, "industry_group_strength_score")),
        (0.20, cross_sectional_robust_z(d, "industry_within_leader_rank")),
        (0.25, cross_sectional_robust_z(d, "rs_industry_6m")),
        # Phase 8a.1: industry_rotation_signal has IC -0.0117 (negative alpha)
        (_w_industry_rotation_future, cross_sectional_robust_z(d, "industry_rotation_signal")),
        # Phase 5: sub-industry leader/laggard — future sleeve gets the
        # highest weight on these because "leaders pull away in a strong
        # group" is the IBD/O'Neil playbook this sleeve is built around.
        # Uses zero-masked z-scores (see _p5_bonus_z / _p5_penalty_z
        # above) so the weight-pairs are skipped on rows where Phase 5
        # didn't fire, eliminating the row_mean dilution effect.
        (0.25, _p5_bonus_z),
        (-0.15, _p5_penalty_z),
        # Phase 7a: insider flow bonus on future-winner sleeve. Medium
        # weight because growth-with-insider-buying is a high-conviction
        # combination but insider signals can be noisy on mid-cap names.
        (
            _p7a_w_insider_future if _phase7a_active else 0.0,
            cross_sectional_robust_z(d, "insider_flow_signal_score"),
        ),
        # Phase 8a.4: hold persistence bonus (see core sleeve).
        (_w_hold_persistence, _hold_persistence_bonus),
        # Phase 8b.1: long-lookback multi-year winner score — highest
        # weight on future sleeve (this is the NVDA/AVGO/MU catcher).
        (_w_multi_year_future, _multi_year_winner),
        # Phase 8b.1: persistence_trend_24m binary confirmation on future.
        (_w_persist_future, _persistence_trend),
        # Phase 8d.2: long-horizon alpha composite — moderate weight on
        # future (some growth-with-fundamentals gate, but future sleeve
        # is momentum-first so we don't dominate with value factors).
        (_w_lh_alpha_future, _long_horizon_alpha_composite),
    ]
    future_score = weighted_sleeve_composite(
        future_weight_pairs,
        d.index,
        renorm_enabled=_phase3_renorm_active,
        l1_target=_phase3_l1_target,
    )
    early_weight_pairs: list[tuple[float, pd.Series]] = [
        (1.00, cross_sectional_robust_z(d, "anticipatory_growth_score")),
        (1.00, cross_sectional_robust_z(d, "growth_onset_composite")),
        (1.00, cross_sectional_robust_z(d, "leader_emergence_score")),
        (0.90, cross_sectional_robust_z(d, "relative_strength_composite")),
        (0.80, cross_sectional_robust_z(d, "technical_blueprint_score")),
        (0.95, cross_sectional_robust_z(d, "revision_blueprint_score")),
        (0.70, cross_sectional_robust_z(d, "revision_score")),
        (0.60, cross_sectional_robust_z(d, "event_reaction_score")),
        (0.60, cross_sectional_robust_z(d, "profitability_inflection_score")),
        (0.55, cross_sectional_robust_z(d, "fundamental_turnaround_acceleration_score")),
        (0.45, cross_sectional_robust_z(d, "cashflow_inflection_under_loss_score")),
        (0.40, cross_sectional_robust_z(d, "dynamic_leader_score")),
        (0.35, cross_sectional_robust_z(d, "minervini_momentum_alive_score")),
        (0.35, cross_sectional_robust_z(d, "breakout_setup_quality_score")),
        (0.48, sage_composite_rank),
        (0.28, sage_g_rank),
        (0.18, sage_c_rank),
        (0.12, sage_v_rank),
        (-0.30, numeric_series_or_default(d, "broken_momentum_penalty", 0.0)),
        (-0.20, cross_sectional_robust_z(d, "size_saturation_score").clip(lower=0.0)),
        (-0.15, cross_sectional_robust_z(d, "debt_to_equity").clip(lower=0.0)),
        # Phase 1.3 + 1.4: bottom-fishing value/inflection setups deserve
        # the highest weight on the early-scout sleeve, with breakdown
        # penalty kept so we don't bottom-fish names that are actively
        # collapsing rather than basing.
        (0.55, cross_sectional_robust_z(d, "value_inflection_score")),
        (0.20, cross_sectional_robust_z(d, "uptrend_continuation_score")),
        (-0.25, numeric_series_or_default(d, "uptrend_breakdown_penalty", 0.0)),
        # Phase 2.7 + Phase 8a.1: industry_rotation_signal has IC -0.0117 over
        # 83 months — the "buy the rotating-up industry" theory didn't survive
        # empirical test. Weight zeroed by default; set PHASE_PHASE8A_NEG_IC_DROP=0
        # to restore original 0.45 weight for A/B.
        (_w_industry_rotation_early, cross_sectional_robust_z(d, "industry_rotation_signal")),
        (0.35, cross_sectional_robust_z(d, "oneil_leadership_score")),
        (0.25, cross_sectional_robust_z(d, "industry_group_strength_score")),
        (0.20, cross_sectional_robust_z(d, "industry_within_leader_rank")),
        (0.18, cross_sectional_robust_z(d, "rs_industry_3m")),
        # Phase 5: early-scout is already rotation-heavy; keep leader
        # bonus light to avoid double-counting with industry_rotation_signal.
        # Zero-masked (see _p5_bonus_z above).
        (0.10, _p5_bonus_z),
        # Phase 7a: insider flow bonus on early-scout — highest weight
        # across sleeves because early-stage insider buying is the
        # cleanest conviction signal (management sees inflection before
        # the market).
        (
            _p7a_w_insider_early if _phase7a_active else 0.0,
            cross_sectional_robust_z(d, "insider_flow_signal_score"),
        ),
        # Phase 8a.4: hold persistence bonus (see core sleeve).
        (_w_hold_persistence, _hold_persistence_bonus),
        # Phase 8b.1: long-lookback multi-year winner score on early
        # scout — supporting weight. Early is bottom-fishing focused so
        # multi-year winners aren't the main prey, but we still reward
        # the trend (don't bottom-fish collapsing multi-year losers).
        (_w_multi_year_early, _multi_year_winner),
        # Phase 8d.2: long-horizon alpha composite on early — moderate
        # weight. Early sleeve is inflection-focused but we still want
        # high fundamental quality (roe/margin) as an anchor to avoid
        # bottom-fishing true zombies.
        (_w_lh_alpha_early, _long_horizon_alpha_composite),
    ]
    early_score = weighted_sleeve_composite(
        early_weight_pairs,
        d.index,
        renorm_enabled=_phase3_renorm_active,
        l1_target=_phase3_l1_target,
    )

    # Phase 3 diagnostic: emit the pre-renorm L1 norm for each sleeve plus
    # a scalar flag so reports/full_validation_suite.json can record whether
    # Phase 3 was active during this run and how much Phase 1+2 inflated
    # the baseline L1 vs the pre-Phase-1+2 reference (~7.32 for core).
    _core_l1 = sleeve_weight_l1_norm(core_weight_pairs)
    _future_l1 = sleeve_weight_l1_norm(future_weight_pairs)
    _early_l1 = sleeve_weight_l1_norm(early_weight_pairs)
    d["sleeve_core_l1_norm"] = _core_l1
    d["sleeve_future_l1_norm"] = _future_l1
    d["sleeve_early_l1_norm"] = _early_l1
    d["sleeve_weight_renorm_active"] = 1.0 if _phase3_renorm_active else 0.0
    sparse_history_penalty = numeric_series_or_default(d, "growth_sleeve_sparse_history_penalty", 0.0).clip(
        lower=0.0,
        upper=1.0,
    )
    data_confidence = numeric_series_or_default(d, "growth_sleeve_data_confidence", 0.0).clip(lower=0.0, upper=1.0)
    confidence_shortfall = (
        (growth_history_confidence_floor - data_confidence).clip(lower=0.0)
        / max(growth_history_confidence_floor, 1e-8)
    ).clip(lower=0.0, upper=1.0)
    sparse_history_penalty = pd.Series(
        np.maximum(sparse_history_penalty, 0.50 * confidence_shortfall),
        index=d.index,
        dtype=float,
    ).clip(lower=0.0, upper=1.0)
    # Phase 3 magnitude-consistency: the additive penalties below were
    # calibrated to the legacy row_mean magnitude (~sum/N). When
    # renorm is active the composite magnitude is ~sum/L1, which is
    # typically N/L1 larger (~2x for the current sleeve tables).
    # Scale the penalty coefficients by the same N/L1 ratio per sleeve so
    # the penalty's relative strength on the composite is preserved and
    # the A/B measurement isolates just the weight-redistribution effect.
    # When renorm is OFF `_future_penalty_scale` / `_early_penalty_scale`
    # default to 1.0, preserving byte-identical legacy behaviour.
    _future_penalty_scale = 1.0
    _early_penalty_scale = 1.0
    if _phase3_renorm_active:
        _future_n = len(future_weight_pairs)
        _early_n = len(early_weight_pairs)
        if _phase3_l1_target and _phase3_l1_target > 0.0:
            _future_denom = float(_phase3_l1_target)
            _early_denom = float(_phase3_l1_target)
        else:
            _future_denom = _future_l1
            _early_denom = _early_l1
        if _future_denom > 1e-8:
            _future_penalty_scale = float(_future_n) / _future_denom
        if _early_denom > 1e-8:
            _early_penalty_scale = float(_early_n) / _early_denom
    future_score = future_score - (
        _future_penalty_scale
        * 0.60
        * growth_history_penalty_weight
        * sparse_history_penalty
    )
    early_score = early_score - (
        _early_penalty_scale
        * 0.60
        * growth_history_penalty_weight
        * sparse_history_penalty
    )
    early_score = early_score - (
        _early_penalty_scale * 0.18 * np.clip(history_depth - 0.65, 0.0, 1.0)
    )
    d["sleeve_future_penalty_scale"] = _future_penalty_scale
    d["sleeve_early_penalty_scale"] = _early_penalty_scale

    # -------------------------------------------------------------------
    # Phase 4: apply regime-conditional sleeve multipliers AFTER Phase 3
    # composition + penalty subtraction and BEFORE winsorize/clip.
    # Per-row regime label resolution via `event_regime_label` (falls back
    # to `balanced` if the column is missing or NaN, which keeps
    # multipliers at identity).
    # When disabled the three diagnostic columns are written as 1.0 so
    # downstream auditors can verify the toggle state at a glance.
    # -------------------------------------------------------------------
    if _phase4_regime_active:
        regime_label_series = d.get(
            "event_regime_label",
            pd.Series("balanced", index=d.index, dtype=object),
        )
        regime_label_series = regime_label_series.fillna("balanced").astype(str)
        # Build per-regime multiplier lookup once, apply via map() — much
        # cheaper than per-row function calls over ~600 rows * 83 months.
        unique_labels = sorted({str(x).strip() for x in regime_label_series.unique()})
        lookup = {
            lbl: resolve_regime_sleeve_multipliers(lbl, _phase4_user_table)
            for lbl in unique_labels
        }
        core_mult = regime_label_series.map(lambda lbl: lookup.get(lbl, {}).get("core", 1.0)).astype(float)
        future_mult = regime_label_series.map(lambda lbl: lookup.get(lbl, {}).get("future", 1.0)).astype(float)
        early_mult = regime_label_series.map(lambda lbl: lookup.get(lbl, {}).get("early", 1.0)).astype(float)
        core_score = core_score * core_mult
        future_score = future_score * future_mult
        early_score = early_score * early_mult
        d["regime_sleeve_multiplier_core"] = core_mult.values
        d["regime_sleeve_multiplier_future"] = future_mult.values
        d["regime_sleeve_multiplier_early"] = early_mult.values
    else:
        d["regime_sleeve_multiplier_core"] = 1.0
        d["regime_sleeve_multiplier_future"] = 1.0
        d["regime_sleeve_multiplier_early"] = 1.0
    d["regime_sleeve_weights_active"] = 1.0 if _phase4_regime_active else 0.0
    # Phase 7a diagnostic: scalar flag so downstream reports can see
    # whether insider + accruals wiring was active during this run.
    d["phase7a_insider_accruals_active"] = 1.0 if _phase7a_active else 0.0

    d["portfolio_core_compounder_engine_score"] = winsorize(core_score, 0.01).clip(-6.0, 6.0)
    d["portfolio_future_winner_engine_score"] = winsorize(future_score, 0.01).clip(-6.0, 6.0)
    d["portfolio_early_scout_engine_score"] = winsorize(early_score, 0.01).clip(-6.0, 6.0)
    sleeve_matrix = np.column_stack(
        [
            pd.to_numeric(d["portfolio_core_compounder_engine_score"], errors="coerce").fillna(0.0).to_numpy(dtype=float),
            pd.to_numeric(d["portfolio_future_winner_engine_score"], errors="coerce").fillna(0.0).to_numpy(dtype=float),
            pd.to_numeric(d["portfolio_early_scout_engine_score"], errors="coerce").fillna(0.0).to_numpy(dtype=float),
        ]
    )
    sleeve_labels = np.array(["core_compounder", "future_winner", "early_scout"], dtype=object)
    top_idx = np.argmax(sleeve_matrix, axis=1)
    top_val = sleeve_matrix[np.arange(len(d)), top_idx]
    second_val = np.partition(sleeve_matrix, -2, axis=1)[:, -2]
    sleeve_confidence = np.clip((top_val - second_val) / 3.0, 0.0, 1.0)
    sleeve_label = sleeve_labels[top_idx]
    core_or_future_max = np.maximum(sleeve_matrix[:, 0], sleeve_matrix[:, 1])
    early_edge = sleeve_matrix[:, 2] - core_or_future_max
    growth_tilt = row_mean(
        [
            0.35 * sage_g_rank,
            0.25 * sage_composite_rank,
            0.20 * cross_sectional_robust_z(d, "anticipatory_growth_score"),
            0.20 * cross_sectional_robust_z(d, "growth_onset_composite"),
            0.15 * cross_sectional_robust_z(d, "leader_emergence_score"),
        ],
        d.index,
    ).fillna(0.0)
    # Keep early_scout for names where the early/inflection engine is clearly
    # dominant. Mature cyclicals can otherwise be stranded in a tiny scout sleeve.
    weak_early_edge = sleeve_label == "early_scout"
    weak_early_edge &= (early_edge < -0.02) | (sleeve_matrix[:, 2] < 0.18)
    sleeve_label = np.where(
        weak_early_edge & (sleeve_matrix[:, 1] >= sleeve_matrix[:, 0]),
        "future_winner",
        sleeve_label,
    )
    sleeve_label = np.where(
        weak_early_edge & (sleeve_matrix[:, 1] < sleeve_matrix[:, 0]),
        "core_compounder",
        sleeve_label,
    )
    low_gap = (top_val - second_val) < 0.06
    sleeve_label = np.where(
        low_gap & dominant_archetype.eq("emerging_growth") & (sleeve_matrix[:, 2] >= sleeve_matrix[:, 1]),
        "early_scout",
        sleeve_label,
    )
    sleeve_label = np.where(
        low_gap & dominant_archetype.eq("emerging_growth") & (sleeve_matrix[:, 1] > sleeve_matrix[:, 2]),
        "future_winner",
        sleeve_label,
    )
    growth_lean_future = (
        low_gap
        & ~dominant_archetype.eq("emerging_growth").to_numpy(dtype=bool)
        & (growth_tilt.to_numpy(dtype=float) >= 0.18)
        & (sleeve_matrix[:, 1] >= (sleeve_matrix[:, 0] - 0.18))
    )
    growth_lean_early = (
        low_gap
        & ~dominant_archetype.eq("emerging_growth").to_numpy(dtype=bool)
        & (growth_tilt.to_numpy(dtype=float) >= 0.28)
        & (sleeve_matrix[:, 2] >= (sleeve_matrix[:, 0] - 0.14))
        & (early_edge >= -0.10)
    )
    sleeve_label = np.where(growth_lean_early, "early_scout", sleeve_label)
    sleeve_label = np.where(growth_lean_future & ~growth_lean_early, "future_winner", sleeve_label)
    sleeve_label = np.where(
        low_gap
        & ~dominant_archetype.eq("emerging_growth").to_numpy(dtype=bool)
        & ~(growth_lean_future | growth_lean_early),
        "core_compounder",
        sleeve_label,
    )
    # -------------------------------------------------------------------
    # Phase 8c.1 (2026-04-17): force future_winner sleeve for mega-cap
    # + high-growth + multi-year-trend names. Without this override the
    # engine classifies NVDA/AVGO/MU as core_compounder (because they're
    # $100B+ mega-caps) which constrains them to the 12%-weighted core
    # sleeve. 2024-2026 empirical evidence (DIAGNOSIS_FACTOR_IC.md) shows
    # future_winner sleeve returns 2.29%/month vs core 1.17%/month —
    # reclassifying multi-year mega-cap winners to future unlocks the
    # ~8% per-name weight they deserve based on their momentum profile.
    #
    # Criteria (ALL must hold):
    #   market_cap_live or mktcap > $50B  (mega-cap gate)
    #   revenue_growth_final > 0.25       (genuine growth, not mature
    #                                      compounder)
    #   multi_year_winner_score > 1.0     (top-quartile multi-year trend)
    # Gated behind PHASE_PHASE8C_MEGACAP_OVERRIDE + cfg flag; default ON.
    # -------------------------------------------------------------------
    _phase8c1_env = phase_is_enabled("phase8c_megacap_override", default=True)
    _phase8c1_cfg = bool(getattr(cfg, "phase8c_megacap_future_override_enabled", True)) if cfg is not None else True
    _phase8c1_active = bool(_phase8c1_env and _phase8c1_cfg)
    if _phase8c1_active:
        _mktcap_threshold = float(
            getattr(cfg, "phase8c_megacap_threshold_usd", 50.0e9) if cfg is not None else 50.0e9
        )
        _rev_growth_threshold = float(
            getattr(cfg, "phase8c_megacap_min_revenue_growth", 0.25) if cfg is not None else 0.25
        )
        _multi_year_threshold = float(
            getattr(cfg, "phase8c_megacap_min_multi_year_score", 1.0) if cfg is not None else 1.0
        )
        # Prefer live market_cap, fall back to historical mktcap for walk-forward rows.
        _mcap_live_arr = numeric_series_or_default(d, "market_cap_live", 0.0).to_numpy(dtype=float)
        _mcap_hist_arr = numeric_series_or_default(d, "mktcap", 0.0).to_numpy(dtype=float)
        _mcap_resolved = np.where(np.isfinite(_mcap_live_arr) & (_mcap_live_arr > 0), _mcap_live_arr, _mcap_hist_arr)
        _rev_growth_arr = numeric_series_or_default(d, "revenue_growth_final", 0.0).to_numpy(dtype=float)
        _my_winner_arr = numeric_series_or_default(d, "multi_year_winner_score", 0.0).to_numpy(dtype=float)
        _megacap_winner_mask = (
            (_mcap_resolved > _mktcap_threshold)
            & (_rev_growth_arr > _rev_growth_threshold)
            & (_my_winner_arr > _multi_year_threshold)
        )
        sleeve_label = np.where(_megacap_winner_mask, "future_winner", sleeve_label)
        d["phase8c_megacap_override_active"] = pd.Series(
            _megacap_winner_mask.astype(float), index=d.index, dtype=float
        )
    else:
        d["phase8c_megacap_override_active"] = 0.0

    # -------------------------------------------------------------------
    # Phase 9 C2 (2026-04-17): SLEEVE THESIS-GATE OVERRIDE (terminal)
    # ===================================================================
    # Replaces the argmax + growth_lean + megacap-override chain with
    # EXPLICIT THESIS GATES based on cross-sectional percentiles. Solves
    # the structural problem where sleeve labels lost archetype meaning
    # (NVDA in core because of factor scores, not because it's a mega-cap;
    # early_scout collapsed to 0 names; sleeve labels indistinguishable).
    # See ARCHITECTURE_REVIEW.md §6b.
    #
    # Uses CROSS-SECTIONAL PERCENTILES (not absolute $) so thresholds
    # remain meaningful as market grows over time. User feedback:
    # "$500B 도 10년 후엔 작을 수 있다 — 능동적으로 분리".
    #
    # Empirically validated 2026-04-17 on 610-name universe:
    #   CORE eligible:    58 ( 9.5%)  mega-cap auto + mature quality
    #   FUTURE eligible:  54 ( 8.9%)  scaling-up growth + momentum confirm
    #   EARLY eligible:   55 ( 9.0%)  inflection OR technical breakout
    #   UNASSIGNED:      443 (72.6%)  no thesis -> excluded from portfolio
    #
    # Runs AFTER all legacy assignment + Phase 8c.1 megacap override so
    # toggle OFF preserves existing behaviour byte-exactly.
    # -------------------------------------------------------------------
    _phase9_thesis_active = bool(
        (getattr(cfg, "phase9_thesis_gate_enabled", True) if cfg is not None else True)
        and phase_is_enabled("phase9_thesis_gate", default=True)
    )
    if _phase9_thesis_active:
        _p9_core_mega_pct = float(getattr(cfg, "phase9_core_megacap_percentile", 0.95) if cfg is not None else 0.95)
        _p9_core_qual_size_pct = float(getattr(cfg, "phase9_core_quality_size_percentile", 0.70) if cfg is not None else 0.70)
        _p9_future_lo_pct = float(getattr(cfg, "phase9_future_size_lower_percentile", 0.30) if cfg is not None else 0.30)
        _p9_future_hi_pct = float(getattr(cfg, "phase9_future_size_upper_percentile", 0.95) if cfg is not None else 0.95)
        _p9_early_hi_pct = float(getattr(cfg, "phase9_early_size_upper_percentile", 0.70) if cfg is not None else 0.70)
        _p9_core_min_roe = float(getattr(cfg, "phase9_core_quality_min_roe", 0.15) if cfg is not None else 0.15)
        _p9_core_min_margin = float(getattr(cfg, "phase9_core_quality_min_margin", 0.10) if cfg is not None else 0.10)
        _p9_core_rev_min = float(getattr(cfg, "phase9_core_quality_rev_growth_min", 0.02) if cfg is not None else 0.02)
        _p9_core_rev_max = float(getattr(cfg, "phase9_core_quality_rev_growth_max", 0.30) if cfg is not None else 0.30)
        _p9_future_rev_min = float(getattr(cfg, "phase9_future_min_rev_growth", 0.20) if cfg is not None else 0.20)
        _p9_future_mom24_min = float(getattr(cfg, "phase9_future_min_mom_24m", 0.50) if cfg is not None else 0.50)
        _p9_early_inflect_thr = float(getattr(cfg, "phase9_early_inflection_threshold", 0.3) if cfg is not None else 0.3)
        _p9_early_value_thr = float(getattr(cfg, "phase9_early_value_inflection_threshold", 0.5) if cfg is not None else 0.5)
        _p9_early_breakout_thr = float(getattr(cfg, "phase9_early_breakout_threshold", 0.5) if cfg is not None else 0.5)
        _p9_early_gc_thr = float(getattr(cfg, "phase9_early_golden_cross_threshold", 0.3) if cfg is not None else 0.3)

        # Cross-sectional percentile rank of mktcap (within current rebalance frame)
        _p9_mktcap = numeric_series_or_default(d, "mktcap", 0.0).astype(float)
        _p9_mktcap_pct = _p9_mktcap.rank(pct=True, method="average").fillna(0.0)
        _p9_rev_growth = numeric_series_or_default(d, "revenue_growth_final", 0.0)
        _p9_roe = numeric_series_or_default(d, "roe_proxy", 0.0)
        _p9_net_margin = numeric_series_or_default(d, "net_margin", 0.0)
        _p9_op_margin = numeric_series_or_default(d, "op_margin_ttm", 0.0)
        _p9_revision = numeric_series_or_default(d, "revision_blueprint_score", 0.0)
        _p9_mom_12m = numeric_series_or_default(d, "mom_12m", 0.0)
        _p9_mom_24m = numeric_series_or_default(d, "mom_24m", 0.0)
        _p9_turnaround = numeric_series_or_default(d, "fundamental_turnaround_acceleration_score", 0.0)
        _p9_cf_inflect = numeric_series_or_default(d, "cashflow_inflection_under_loss_score", 0.0)
        _p9_value_infl = numeric_series_or_default(d, "value_inflection_score", 0.0)
        _p9_golden = numeric_series_or_default(d, "golden_cross_fresh_20d", 0.0)
        _p9_breakout = numeric_series_or_default(d, "breakout_fresh_20d", 0.0)
        _p9_above_ma200 = numeric_series_or_default(d, "price_above_ma200", 0.0)

        _p9_core_mega = (_p9_mktcap_pct >= _p9_core_mega_pct)
        _p9_core_quality = (
            (_p9_mktcap_pct >= _p9_core_qual_size_pct)
            & (_p9_rev_growth.between(_p9_core_rev_min, _p9_core_rev_max))
            & (_p9_roe > _p9_core_min_roe)
            & ((_p9_net_margin > _p9_core_min_margin) | (_p9_op_margin > _p9_core_min_margin))
        )
        _p9_core_elig = (_p9_core_mega | _p9_core_quality)

        _p9_future_size = _p9_mktcap_pct.between(_p9_future_lo_pct, _p9_future_hi_pct)
        _p9_future_growth = (_p9_rev_growth > _p9_future_rev_min) | (_p9_mom_24m > _p9_future_mom24_min)
        _p9_future_confirm = (_p9_revision > 0) & (_p9_mom_12m > 0)
        _p9_future_elig = _p9_future_size & _p9_future_growth & _p9_future_confirm & (~_p9_core_elig)

        _p9_early_size = (_p9_mktcap_pct < _p9_early_hi_pct)
        _p9_early_inflect = (
            (_p9_turnaround > _p9_early_inflect_thr)
            | (_p9_cf_inflect > _p9_early_inflect_thr)
            | (_p9_value_infl > _p9_early_value_thr)
        )
        _p9_early_breakout = (
            (_p9_golden > _p9_early_gc_thr)
            | ((_p9_breakout > _p9_early_breakout_thr) & (_p9_above_ma200 > 0))
        )

        # Phase 9 C3: EPS turn-positive + still-loss-but-improving branches.
        # Encodes user definition "early 는 eps 적자거나 양전환 막 하거나"
        # exactly. See PHASE_9_C3_PROPOSAL.md. C3 is dependent on C2 — it
        # only runs inside this thesis-gate block and disabling this toggle
        # reverts early_scout to pure C2 (inflect/breakout) admission.
        _phase9_c3_active = bool(
            (getattr(cfg, "phase9_c3_turnaround_enabled", True) if cfg is not None else True)
            and phase_is_enabled("phase9_c3_turnaround", default=True)
        )
        if _phase9_c3_active:
            _p9_ni_ttm = numeric_series_or_default(d, "net_income_ttm", 0.0)
            _p9_profit_turn = numeric_series_or_default(d, "profit_turn_positive_4q", 0.0)
            _p9_cf_turn = numeric_series_or_default(d, "cashflow_turn_positive_4q", 0.0)
            _p9_roe_turn = numeric_series_or_default(d, "roe_turn_positive_4q", 0.0)
            _p9_ocf_under_loss = numeric_series_or_default(d, "ocf_under_loss_growth", 0.0)
            _p9_fcf_under_loss = numeric_series_or_default(d, "fcf_under_loss_growth", 0.0)
            _p9_ni_narrow = numeric_series_or_default(d, "ni_loss_narrowing_4q", 0.0)
            _p9_c3_narrow_thr = float(
                getattr(cfg, "phase9_c3_loss_narrowing_threshold", 0.3) if cfg is not None else 0.3
            )
            _p9_eps_turn_positive = (
                (_p9_profit_turn > 0.5)
                | (_p9_cf_turn > 0.5)
                | (_p9_roe_turn > 0.5)
            )
            _p9_still_loss_but_improving = (
                (_p9_ni_ttm < 0)
                & (
                    (_p9_ocf_under_loss > _p9_c3_narrow_thr)
                    | (_p9_fcf_under_loss > _p9_c3_narrow_thr)
                    | (_p9_ni_narrow > _p9_c3_narrow_thr)
                )
            )
            _p9_c3_admit = _p9_eps_turn_positive | _p9_still_loss_but_improving
        else:
            _p9_c3_admit = pd.Series(False, index=d.index)
            _p9_eps_turn_positive = pd.Series(False, index=d.index)
            _p9_still_loss_but_improving = pd.Series(False, index=d.index)

        _p9_early_elig = (
            _p9_early_size
            & (_p9_early_inflect | _p9_early_breakout | _p9_c3_admit)
            & (~_p9_core_elig) & (~_p9_future_elig)
        )

        _p9_unassigned = ~(_p9_core_elig | _p9_future_elig | _p9_early_elig)
        sleeve_label = np.where(
            _p9_core_elig.to_numpy(dtype=bool),
            "core_compounder",
            np.where(
                _p9_future_elig.to_numpy(dtype=bool),
                "future_winner",
                np.where(
                    _p9_early_elig.to_numpy(dtype=bool),
                    "early_scout",
                    "unassigned",
                ),
            ),
        )

        d["phase9_thesis_gate_active"] = 1.0
        d["phase9_core_eligible"] = _p9_core_elig.astype(float).values
        d["phase9_future_eligible"] = _p9_future_elig.astype(float).values
        d["phase9_early_eligible"] = _p9_early_elig.astype(float).values
        d["phase9_unassigned"] = _p9_unassigned.astype(float).values
        d["phase9_mktcap_percentile"] = _p9_mktcap_pct.values
        # Phase 9 C3 diagnostics (how many names C3 admitted per branch)
        d["phase9_c3_turnaround_active"] = float(_phase9_c3_active)
        d["phase9_c3_eps_turn_positive"] = _p9_eps_turn_positive.astype(float).values
        d["phase9_c3_still_loss_branch"] = _p9_still_loss_but_improving.astype(float).values
    else:
        d["phase9_thesis_gate_active"] = 0.0
        d["phase9_core_eligible"] = 0.0
        d["phase9_future_eligible"] = 0.0
        d["phase9_early_eligible"] = 0.0
        d["phase9_unassigned"] = 0.0
        d["phase9_mktcap_percentile"] = 0.0
        d["phase9_c3_turnaround_active"] = 0.0
        d["phase9_c3_eps_turn_positive"] = 0.0
        d["phase9_c3_still_loss_branch"] = 0.0
    # END Phase 9 C2 thesis-gate
    # -------------------------------------------------------------------

    sleeve_label_raw = sleeve_label.copy()
    fundamental_confirmation = numeric_series_or_default(
        d, "selection_fundamental_confirmation_score", 0.0
    ).clip(lower=0.0, upper=1.0)
    market_confirmation = numeric_series_or_default(
        d, "selection_market_confirmation_score", 0.0
    ).clip(lower=0.0, upper=1.0)
    promotion_signal = row_mean(
        [
            fundamental_confirmation,
            0.85 * market_confirmation,
            history_depth,
            (numeric_series_or_default(d, "rs_benchmark_6m", 0.0) > 0.0).astype(float),
            (numeric_series_or_default(d, "minervini_momentum_alive_score", 0.0) > 1.0).astype(float),
            (numeric_series_or_default(d, "breakout_setup_quality_score", 0.0) > 0.75).astype(float),
        ],
        d.index,
    ).fillna(0.0)
    mature_history_confirmed = (
        (history_depth >= 0.75)
        & (fundamental_confirmation >= 0.55)
        & (market_confirmation >= 0.55)
    )
    promotion_ready = (
        (promotion_signal >= float(getattr(cfg, "early_scout_promotion_min_score", 0.78)))
        & (
            mature_history_confirmed
            | (
                (history_depth >= 0.85)
                & (fundamental_confirmation >= 0.60)
                & (market_confirmation >= 0.60)
            )
        )
    )
    mature_early_mask = (
        pd.Series(sleeve_label, index=d.index, dtype=object).astype(str).eq("early_scout")
        & (
            (early_edge <= float(getattr(cfg, "early_scout_promotion_edge_max", 0.08)))
            | (sleeve_confidence <= float(getattr(cfg, "early_scout_promotion_confidence_max", 0.10)))
        )
        & promotion_ready
    )
    sleeve_label = np.where(mature_early_mask.to_numpy(dtype=bool), "future_winner", sleeve_label)
    d["portfolio_sleeve_label_raw"] = pd.Series(sleeve_label_raw, index=d.index, dtype=object)
    d["portfolio_sleeve_label"] = pd.Series(sleeve_label, index=d.index, dtype=object)
    d["portfolio_sleeve_confidence"] = pd.Series(sleeve_confidence, index=d.index, dtype=float)
    d["portfolio_sleeve_promotion_signal"] = pd.Series(promotion_signal, index=d.index, dtype=float)
    d["portfolio_sleeve_promoted"] = pd.Series(
        pd.Series(sleeve_label_raw, index=d.index, dtype=object).astype(str)
        != pd.Series(sleeve_label, index=d.index, dtype=object).astype(str),
        index=d.index,
        dtype=bool,
    )
    # Phase 11 (2026-04-20): Multibagger Watch sleeve override. Picks top-N by
    # P(entry) that pass quality filter + P(sl)/P(tp) caps each rebalance_date
    # and overrides their portfolio_sleeve_label to "multibagger_watch". This
    # lifts the selected names into a dedicated sleeve with allocation_pct
    # of the portfolio weight (see compute_portfolio_sleeve_policy).
    d = _apply_multibagger_watch_sleeve_override(d, cfg)
    return d


def _apply_multibagger_watch_sleeve_override(
    d: pd.DataFrame,
    cfg: EngineConfig,
) -> pd.DataFrame:
    """Phase 11 helper: override portfolio_sleeve_label to 'multibagger_watch'
    for the top-N qualified names by P(entry) at each rebalance_date.

    No-op when cfg.phase11_multibagger_sleeve_enabled is False.
    """
    # Gate: env var overrides cfg default. Default OFF (cfg=False).
    # PHASE_PHASE11_MULTIBAGGER_ENABLED=1 -> enable regardless of cfg default.
    # PHASE_PHASE11_MULTIBAGGER_ENABLED=0 -> disable regardless of cfg.
    # Env unset -> use cfg.phase11_multibagger_sleeve_enabled.
    _cfg_default = bool(getattr(cfg, "phase11_multibagger_sleeve_enabled", False))
    if not phase_is_enabled("phase11_multibagger", default=_cfg_default):
        return d
    required_cols = ("phase11_p_entry", "phase11_p_takeprofit", "phase11_p_stoploss",
                     "mktcap", "revenues_ttm", "ticker", "rebalance_date")
    if not all(c in d.columns for c in required_cols):
        return d

    size = max(int(getattr(cfg, "phase11_sleeve_size", 5)), 1)
    p_entry_min = float(getattr(cfg, "phase11_p_entry_threshold", 0.30))
    p_tp_max = float(getattr(cfg, "phase11_p_takeprofit_threshold", 0.50))
    p_sl_max = float(getattr(cfg, "phase11_p_stoploss_select_threshold", 0.50))
    min_mcap = float(getattr(cfg, "phase11_quality_min_mcap", 1e9))
    min_rev = float(getattr(cfg, "phase11_quality_min_revenue", 1e8))

    pe = pd.to_numeric(d["phase11_p_entry"], errors="coerce").fillna(0.0)
    pt = pd.to_numeric(d["phase11_p_takeprofit"], errors="coerce").fillna(0.0)
    ps = pd.to_numeric(d["phase11_p_stoploss"], errors="coerce").fillna(0.0)
    mc = pd.to_numeric(d["mktcap"], errors="coerce").fillna(0.0)
    rv = pd.to_numeric(d["revenues_ttm"], errors="coerce").fillna(0.0)

    eligible = (pe >= p_entry_min) & (pt <= p_tp_max) & (ps <= p_sl_max) & (mc >= min_mcap) & (rv >= min_rev)
    if not eligible.any():
        return d

    # Top-N by P(entry) per rebalance_date (stateless selection each month)
    elig_df = d.loc[eligible, ["rebalance_date", "ticker"]].copy()
    elig_df["__pe__"] = pe.loc[eligible].values
    # Rank within each rebalance_date
    elig_df["__rank__"] = elig_df.groupby("rebalance_date")["__pe__"].rank(method="first", ascending=False)
    selected = elig_df[elig_df["__rank__"] <= size].index
    if len(selected) == 0:
        return d

    # Override sleeve label
    d.loc[selected, "portfolio_sleeve_label"] = "multibagger_watch"
    # Flag that these were promoted by Phase 11 (distinct from early->future promotion)
    if "portfolio_sleeve_promoted" in d.columns:
        d.loc[selected, "portfolio_sleeve_promoted"] = True
    return d


def compute_portfolio_sleeve_policy(
    cfg: EngineConfig,
    month_df: pd.DataFrame,
    cash_target: float,
) -> dict[str, float]:
    d = month_df.copy() if month_df is not None else pd.DataFrame()

    def _median_or_default(col: str, default: float = 0.0) -> float:
        if d.empty or col not in d.columns:
            return float(default)
        val = safe_float(pd.to_numeric(d[col], errors="coerce").median())
        return float(default if np.isnan(val) else val)

    invested_share = float(np.clip(1.0 - float(np.clip(safe_float(cash_target), 0.0, 1.0)), 0.0, 1.0))
    if invested_share <= 1e-8:
        return {
            "core_compounder_target": 0.0,
            "future_winner_target": 0.0,
            "early_scout_target": 0.0,
            "invested_share": 0.0,
            "cash_target": float(np.clip(safe_float(cash_target), 0.0, 1.0)),
            "growth_signal": 0.0,
            "risk_signal": 0.0,
            "future_winner_regime_strength": 0.0,
            "early_scout_regime_strength": 0.0,
            "early_scout_candidate_share": 0.0,
        }

    base_core = float(getattr(cfg, "core_compounder_sleeve_base_weight", 0.28))
    base_future = float(getattr(cfg, "future_winner_sleeve_base_weight", 0.52))
    base_early = float(getattr(cfg, "early_scout_sleeve_base_weight", 0.12))
    base_invested = max(base_core + base_future + base_early, 1e-8)
    future_base = invested_share * (base_future / base_invested)
    early_base = invested_share * (base_early / base_invested)

    breadth_regime = _median_or_default("market_breadth_regime_score", 0.50)
    sector_participation = _median_or_default("market_sector_participation", 0.35)
    systemic = _median_or_default("systemic_crisis_score", 0.0)
    carry_unwind = _median_or_default("carry_unwind_stress_score", 0.0)
    war_oil_rate = _median_or_default("war_oil_rate_shock_score", 0.0)
    defensive_rotation = _median_or_default("defensive_rotation_score", 0.0)
    stagflation = _median_or_default("stagflation_score", 0.0)
    growth_reentry = _median_or_default("growth_reentry_score", 0.0)
    growth_liquidity = _median_or_default("growth_liquidity_reentry_score", 0.0)
    liquidity_impulse = _median_or_default("liquidity_impulse_score", 0.0)
    liquidity_drain = _median_or_default("liquidity_drain_score", 0.0)
    live_event_growth = _median_or_default("live_event_growth_reentry_score", 0.0)
    live_event_risk = _median_or_default("live_event_risk_score", 0.0)
    live_event_systemic = _median_or_default("live_event_systemic_score", 0.0)
    live_event_war = _median_or_default("live_event_war_oil_rate_score", 0.0)

    growth_signal = max(
        growth_reentry,
        growth_liquidity,
        liquidity_impulse,
        live_event_growth,
        max(0.0, breadth_regime - 0.55) / 0.25,
        max(0.0, sector_participation - 0.42) / 0.18,
    )
    risk_signal = max(
        systemic,
        carry_unwind,
        war_oil_rate,
        defensive_rotation,
        stagflation,
        liquidity_drain,
        live_event_risk,
        live_event_systemic,
        live_event_war,
    )
    growth_thrust = max(
        0.0,
        growth_signal
        - max(
            0.50 * risk_signal,
            0.45 * liquidity_drain,
            0.25 * defensive_rotation,
        ),
    )
    early_candidate_share = 0.0
    if not d.empty:
        for label_col in ["portfolio_sleeve_label_raw", "portfolio_sleeve_label"]:
            if label_col in d.columns:
                labels = d[label_col].astype(str)
                early_candidate_share = max(early_candidate_share, float(labels.eq("early_scout").mean()))
        if "portfolio_early_scout_engine_score" in d.columns:
            early_engine = pd.to_numeric(d["portfolio_early_scout_engine_score"], errors="coerce")
            valid_early_engine = early_engine.dropna()
            if not valid_early_engine.empty:
                early_engine_cut = max(0.35, float(valid_early_engine.quantile(0.80)))
                early_candidate_share = max(early_candidate_share, float((early_engine >= early_engine_cut).mean()))

    future_target = future_base
    future_target += 0.24 * np.clip((growth_signal - 0.32) / 0.68, 0.0, 1.0)
    future_target += 0.12 * np.clip((breadth_regime - 0.52) / 0.28, 0.0, 1.0)
    future_target += 0.08 * np.clip((sector_participation - 0.36) / 0.24, 0.0, 1.0)
    future_target -= 0.10 * np.clip((risk_signal - 0.38) / 0.62, 0.0, 1.0)
    future_target -= 0.05 * np.clip((liquidity_drain - 0.44) / 0.56, 0.0, 1.0)
    early_target = early_base
    early_target += 0.12 * np.clip((growth_signal - 0.36) / 0.64, 0.0, 1.0)
    early_target += 0.14 * np.clip((growth_thrust - 0.24) / 0.76, 0.0, 1.0)
    early_target += 0.08 * np.clip((breadth_regime - 0.52) / 0.28, 0.0, 1.0)
    early_target += 0.08 * np.clip((sector_participation - 0.36) / 0.24, 0.0, 1.0)
    early_target -= 0.08 * np.clip((risk_signal - 0.34) / 0.66, 0.0, 1.0)
    early_target -= 0.05 * np.clip((liquidity_drain - 0.40) / 0.60, 0.0, 1.0)

    early_floor_weight = float(getattr(cfg, "early_scout_growth_floor_weight", 0.0))
    early_floor_min_signal = float(getattr(cfg, "early_scout_growth_floor_min_signal", 0.34))
    early_floor_max_risk = float(getattr(cfg, "early_scout_growth_floor_max_risk", 0.60))
    early_floor_min_share = max(float(getattr(cfg, "early_scout_candidate_floor_min_share", 0.01)), 1e-8)
    if (
        early_floor_weight > 0.0
        and early_candidate_share >= early_floor_min_share
        and growth_signal >= early_floor_min_signal
        and risk_signal < early_floor_max_risk
    ):
        growth_floor_factor = float(np.clip((growth_signal - early_floor_min_signal) / 0.22, 0.65, 1.0))
        risk_floor_discount = float(
            1.0
            - 0.35
            * np.clip(
                (risk_signal - 0.25) / max(early_floor_max_risk - 0.25, 1e-8),
                0.0,
                1.0,
            )
        )
        candidate_floor_factor = float(np.clip(early_candidate_share / max(early_floor_min_share, 1e-8), 0.0, 1.0))
        early_growth_floor = early_floor_weight * growth_floor_factor * risk_floor_discount * candidate_floor_factor
        early_target = max(
            early_target,
            min(
                early_growth_floor,
                float(getattr(cfg, "early_scout_sleeve_max_weight", 0.28)),
                invested_share,
            ),
        )

    strong_future_regime = (
        growth_signal >= 0.56
        and breadth_regime >= 0.54
        and sector_participation >= 0.38
        and risk_signal <= 0.50
        and liquidity_drain <= 0.54
    )
    strong_early_regime = (
        growth_signal >= 0.58
        and growth_thrust >= 0.38
        and breadth_regime >= 0.54
        and sector_participation >= 0.38
        and risk_signal <= 0.48
        and liquidity_drain <= 0.48
    )
    if strong_future_regime:
        future_target = max(
            future_target,
            min(
                float(getattr(cfg, "future_winner_sleeve_max_weight", 0.70)),
                0.48 + 0.20 * np.clip((growth_signal - 0.56) / 0.44, 0.0, 1.0),
            ),
        )
    if strong_early_regime:
        future_target = max(
            future_target,
            min(
                float(getattr(cfg, "future_winner_sleeve_max_weight", 0.70)),
                invested_share * 0.40,
            ),
        )
        early_target = max(
            early_target,
            min(
                float(getattr(cfg, "early_scout_sleeve_max_weight", 0.28)),
                max(
                    invested_share * 0.50,
                    0.18
                    + 0.16 * np.clip((growth_thrust - 0.38) / 0.62, 0.0, 1.0)
                    + 0.08 * np.clip((growth_signal - 0.58) / 0.42, 0.0, 1.0),
                ),
            ),
        )
    if risk_signal >= 0.70:
        future_target = min(future_target, min(0.22, invested_share))
        early_target = min(early_target, min(0.04, invested_share))
    elif risk_signal >= 0.55:
        future_target = min(future_target, min(0.28, invested_share))
        early_target = min(early_target, min(0.08, invested_share))

    future_target = float(
        np.clip(
            future_target,
            0.0 if invested_share < float(getattr(cfg, "future_winner_sleeve_min_weight", 0.10)) else float(getattr(cfg, "future_winner_sleeve_min_weight", 0.10)),
            min(float(getattr(cfg, "future_winner_sleeve_max_weight", 0.70)), invested_share),
        )
    )
    early_target = float(
        np.clip(
            early_target,
            0.0 if invested_share < float(getattr(cfg, "early_scout_sleeve_min_weight", 0.02)) else float(getattr(cfg, "early_scout_sleeve_min_weight", 0.02)),
            min(float(getattr(cfg, "early_scout_sleeve_max_weight", 0.28)), invested_share),
        )
    )
    exploratory_total = future_target + early_target
    if exploratory_total > invested_share and exploratory_total > 1e-10:
        scale = invested_share / exploratory_total
        future_target *= scale
        early_target *= scale
    # Phase 11 (2026-04-20): carve out allocation_pct for multibagger_watch sleeve.
    # Scales future + early proportionally so the 4 sleeves always sum to invested_share.
    # When Phase 11 disabled, multibagger_watch_target = 0 (no effect).
    multibagger_watch_target = 0.0
    if bool(getattr(cfg, "phase11_multibagger_sleeve_enabled", False)):
        mbw_pct = float(np.clip(float(getattr(cfg, "phase11_allocation_pct", 0.30)), 0.0, 0.90))
        multibagger_watch_target = invested_share * mbw_pct
        remaining_scale = 1.0 - mbw_pct
        future_target *= remaining_scale
        early_target *= remaining_scale
    core_target = float(max(0.0, invested_share - future_target - early_target - multibagger_watch_target))

    return {
        "core_compounder_target": core_target,
        "future_winner_target": future_target,
        "early_scout_target": early_target,
        "multibagger_watch_target": float(multibagger_watch_target),
        "invested_share": invested_share,
        "cash_target": float(np.clip(safe_float(cash_target), 0.0, 1.0)),
        "growth_signal": float(growth_signal),
        "risk_signal": float(risk_signal),
        "future_winner_regime_strength": float(1.0 if strong_future_regime else max(0.0, growth_signal - risk_signal)),
        "early_scout_regime_strength": float(
            1.0 if strong_early_regime else max(0.0, growth_thrust - risk_signal, early_candidate_share * 0.25)
        ),
        "early_scout_candidate_share": float(early_candidate_share),
    }


# =====================================================================
# Stage 4b-i: regime portfolio controls + benchmark-beating overlay (2026-04-20)
# =====================================================================
# Moved from r1000_top30_institutional.py:4238-4848 (was 611L):
#   compute_regime_portfolio_controls       (349L) -- regime-conditional
#                                                    sleeve multipliers that
#                                                    modulate target weights
#                                                    at runtime per macro regime.
#   compute_benchmark_beating_focus_overlay  (260L) -- benchmark-beating focus
#                                                    overlay (rs_benchmark /
#                                                    focus_score_components).
#
# Neither has portfolio-helper deps (unlike build_target_portfolio which needs
# 16 additional helpers). Safe to move standalone ahead of 4b-ii.

def compute_regime_portfolio_controls(cfg: EngineConfig, month_df: pd.DataFrame) -> dict[str, float]:
    base = {
        "risk_multiplier": 1.0,
        "turnover_multiplier": 1.0,
        "liquidity_multiplier": 1.0,
        "single_name_cap": float(cfg.stock_weight_max_high_conviction),
        "target_n_adjustment": 0.0,
        "cash_target": 0.0,
    }
    if (not cfg.use_macro_regime_features) or month_df.empty:
        return base

    def _median_or_default(col: str, default: float) -> float:
        if col not in month_df.columns:
            return float(default)
        val = safe_float(pd.to_numeric(month_df[col], errors="coerce").median())
        return float(default if np.isnan(val) else val)

    risk_off = _median_or_default("macro_risk_off_score", 0.0)
    market = _median_or_default("market_regime_score", 0.0)
    inflation = _median_or_default("inflation_pressure_score", 0.0)
    spy_trend = _median_or_default("spy_above_ma200", 1.0)
    bench_trend = _median_or_default("bench_above_ma200", spy_trend)
    breadth_regime = _median_or_default("market_breadth_regime_score", 0.50)
    leadership_narrowing = _median_or_default("market_leadership_narrowing", 0.50)
    sector_participation = _median_or_default("market_sector_participation", 0.35)
    market_overheat = _median_or_default("market_overheat_ratio", 0.0)
    systemic = _median_or_default("systemic_crisis_score", 0.0)
    carry_unwind = _median_or_default("carry_unwind_stress_score", 0.0)
    war_oil_rate = _median_or_default("war_oil_rate_shock_score", 0.0)
    defensive_rotation = _median_or_default("defensive_rotation_score", 0.0)
    growth_reentry = _median_or_default("growth_reentry_score", 0.0)
    inflation_reaccel = _median_or_default("inflation_reacceleration_score", 0.0)
    upstream_cost = _median_or_default("upstream_cost_pressure_score", 0.0)
    labor_softening = _median_or_default("labor_softening_score", 0.0)
    stagflation = _median_or_default("stagflation_score", 0.0)
    growth_liquidity = _median_or_default("growth_liquidity_reentry_score", 0.0)
    liquidity_impulse = _median_or_default("liquidity_impulse_score", 0.0)
    liquidity_drain = _median_or_default("liquidity_drain_score", 0.0)
    slow_macro_cols = ["cpi_yoy", "core_cpi_yoy", "ppi_yoy", "unrate_level", "sahm_realtime"]
    slow_macro_available = float(
        np.nanmean(
            [
                float(pd.to_numeric(month_df[c], errors="coerce").notna().mean())
                if c in month_df.columns
                else 0.0
                for c in slow_macro_cols
            ]
        )
    )
    live_event_risk = _median_or_default("live_event_risk_score", 0.0)
    live_event_systemic = _median_or_default("live_event_systemic_score", 0.0)
    live_event_war = _median_or_default("live_event_war_oil_rate_score", 0.0)
    live_event_defensive = _median_or_default("live_event_defensive_score", 0.0)
    live_event_growth = _median_or_default("live_event_growth_reentry_score", 0.0)

    risk_off = 0.0 if np.isnan(risk_off) else risk_off
    market = 0.0 if np.isnan(market) else market
    inflation = 0.0 if np.isnan(inflation) else inflation
    spy_trend = 1.0 if np.isnan(spy_trend) else spy_trend
    bench_trend = spy_trend if np.isnan(bench_trend) else bench_trend
    breadth_regime = 0.50 if np.isnan(breadth_regime) else breadth_regime
    leadership_narrowing = 0.50 if np.isnan(leadership_narrowing) else leadership_narrowing
    sector_participation = 0.35 if np.isnan(sector_participation) else sector_participation
    market_overheat = 0.0 if np.isnan(market_overheat) else market_overheat
    systemic = 0.0 if np.isnan(systemic) else systemic
    carry_unwind = 0.0 if np.isnan(carry_unwind) else carry_unwind
    war_oil_rate = 0.0 if np.isnan(war_oil_rate) else war_oil_rate
    defensive_rotation = 0.0 if np.isnan(defensive_rotation) else defensive_rotation
    growth_reentry = 0.0 if np.isnan(growth_reentry) else growth_reentry
    inflation_reaccel = 0.0 if np.isnan(inflation_reaccel) else inflation_reaccel
    upstream_cost = 0.0 if np.isnan(upstream_cost) else upstream_cost
    labor_softening = 0.0 if np.isnan(labor_softening) else labor_softening
    stagflation = 0.0 if np.isnan(stagflation) else stagflation
    growth_liquidity = 0.0 if np.isnan(growth_liquidity) else growth_liquidity
    liquidity_impulse = 0.0 if np.isnan(liquidity_impulse) else liquidity_impulse
    liquidity_drain = 0.0 if np.isnan(liquidity_drain) else liquidity_drain
    slow_macro_available = 0.0 if np.isnan(slow_macro_available) else slow_macro_available
    inflation_reaccel = float(np.clip(inflation_reaccel, 0.0, 1.0))
    upstream_cost = float(np.clip(upstream_cost, 0.0, 1.0))
    labor_softening = float(np.clip(labor_softening, 0.0, 1.0))
    stagflation = float(np.clip(stagflation, 0.0, 1.0))
    growth_liquidity = float(np.clip(growth_liquidity, 0.0, 1.0))
    liquidity_impulse = float(np.clip(liquidity_impulse, 0.0, 1.0))
    liquidity_drain = float(np.clip(liquidity_drain, 0.0, 1.0))
    slow_macro_available = float(np.clip(slow_macro_available, 0.0, 1.0))
    live_event_risk = 0.0 if np.isnan(live_event_risk) else live_event_risk
    live_event_systemic = 0.0 if np.isnan(live_event_systemic) else live_event_systemic
    live_event_war = 0.0 if np.isnan(live_event_war) else live_event_war
    live_event_defensive = 0.0 if np.isnan(live_event_defensive) else live_event_defensive
    live_event_growth = 0.0 if np.isnan(live_event_growth) else live_event_growth
    slow_macro_confidence = 0.35 + 0.65 * slow_macro_available
    inflation_reaccel_eff = inflation_reaccel * slow_macro_confidence
    labor_softening_eff = labor_softening * slow_macro_confidence
    stagflation_eff = stagflation * (0.25 + 0.75 * slow_macro_available)
    upstream_cost_eff = upstream_cost * (0.60 + 0.40 * slow_macro_available)

    breadth_stress = max(0.0, 0.52 - breadth_regime)
    participation_stress = max(0.0, 0.38 - sector_participation)
    narrowing_stress = max(0.0, leadership_narrowing - 0.60)
    stress = (
        max(0.0, risk_off)
        + 0.50 * max(0.0, inflation)
        + (0.45 if spy_trend < 0.5 else 0.0)
        + (0.25 if bench_trend < 0.5 else 0.0)
        + 1.20 * breadth_stress
        + 0.90 * narrowing_stress
        + 0.60 * participation_stress
        + 0.35 * max(0.0, market_overheat - 0.28)
        + 0.45 * liquidity_drain
        + 0.12 * upstream_cost_eff
        + float(cfg.event_regime_sensitivity)
        * (
            1.10 * systemic
            + 0.75 * carry_unwind
            + 0.90 * war_oil_rate
            + 0.70 * defensive_rotation
            + 0.55 * stagflation_eff
            + 0.20 * labor_softening_eff
            + 0.18 * inflation_reaccel_eff
        )
    )
    bullish = (
        max(0.0, market)
        + (0.20 if spy_trend >= 0.5 else 0.0)
        + (0.12 if bench_trend >= 0.5 else 0.0)
        + 0.80 * max(0.0, breadth_regime - 0.60)
        + 0.50 * max(0.0, sector_participation - 0.45)
        + float(cfg.event_regime_sensitivity) * 0.90 * growth_reentry
        + 0.85 * growth_liquidity
        + 0.55 * liquidity_impulse
    )

    risk_multiplier = 1.0 + 1.20 * cfg.optimizer_regime_sensitivity * min(2.00, stress)
    turnover_multiplier = 1.0 + 0.80 * cfg.optimizer_regime_sensitivity * min(2.00, stress)
    liquidity_multiplier = 1.0 + 0.50 * cfg.optimizer_regime_sensitivity * min(2.00, stress)

    single_cap = cfg.stock_weight_max_high_conviction
    target_adj = 0.0
    if stress > 0:
        single_cap = max(
            cfg.stock_weight_max * 1.10,
            cfg.stock_weight_max_high_conviction * (1.0 - 0.25 * min(1.15, stress)),
        )
        target_adj -= min(2.0, math.ceil(1.25 * min(1.75, stress)))
    elif bullish > 0.75:
        single_cap = min(cfg.stock_weight_max_high_conviction, cfg.stock_weight_max * 2.10)
        target_adj += 1.0
    if systemic > 0.55:
        single_cap = min(single_cap, max(cfg.stock_weight_max * 1.05, 0.14))
        target_adj -= 1.0
        turnover_multiplier *= 1.10
    if war_oil_rate > 0.55:
        single_cap = min(single_cap, max(cfg.stock_weight_max * 1.10, 0.14))
        target_adj -= 1.0
    if carry_unwind > 0.52:
        single_cap = min(single_cap, max(cfg.stock_weight_max * 1.10, 0.14))
        target_adj -= 1.0
    if stagflation > 0.55:
        single_cap = min(single_cap, max(cfg.stock_weight_max * 1.08, 0.14))
        target_adj -= 1.0
    if liquidity_drain > 0.60:
        single_cap = min(single_cap, max(cfg.stock_weight_max * 1.10, 0.14))
        target_adj -= 1.0
    if growth_reentry > 0.60 and growth_liquidity > 0.55 and breadth_regime > 0.60 and sector_participation > 0.42:
        single_cap = min(cfg.stock_weight_max_high_conviction, cfg.stock_weight_max * 2.50)
        target_adj += 1.0
    if liquidity_impulse > 0.60 and growth_liquidity > 0.55:
        target_adj += 1.0
    if breadth_regime < 0.45 or leadership_narrowing > 0.70:
        single_cap = min(single_cap, max(cfg.stock_weight_max * 1.10, 0.14))
        target_adj -= 1.0
    elif breadth_regime > 0.68 and leadership_narrowing < 0.45 and sector_participation > 0.45:
        single_cap = min(cfg.stock_weight_max_high_conviction, cfg.stock_weight_max * 2.35)
        target_adj += 1.0

    cash_target = 0.0
    if bool(cfg.cash_buffer_enabled):
        growth_cash_cap = min(float(cfg.cash_weight_max), float(getattr(cfg, "cash_target_growth_cap", 0.03)))
        balanced_cash_cap = min(float(cfg.cash_weight_max), float(getattr(cfg, "cash_target_balanced_cap", 0.05)))
        mild_risk_cash_cap = min(float(cfg.cash_weight_max), float(getattr(cfg, "cash_target_mild_risk_cap", 0.10)))
        live_stress = max(live_event_risk, live_event_systemic, live_event_war)
        balanced_live = max(live_stress, live_event_defensive, live_event_growth) < max(
            cfg.live_event_risk_threshold,
            cfg.live_event_growth_threshold,
        )
        cash_target = (
            0.14 * systemic
            + 0.07 * carry_unwind
            + 0.07 * war_oil_rate
            + 0.03 * defensive_rotation
            + 0.08 * live_stress
            + 0.03 * live_event_defensive
            + 0.04 * breadth_stress
            + 0.03 * participation_stress
            + (0.03 if spy_trend < 0.5 else 0.0)
            + (0.03 if bench_trend < 0.5 else 0.0)
            + 0.05 * liquidity_drain
            + 0.04 * stagflation_eff
            + 0.02 * upstream_cost_eff
            + 0.02 * labor_softening_eff
            + 0.02 * inflation_reaccel_eff
            - 0.18 * growth_reentry
            - 0.18 * growth_liquidity
            - 0.10 * liquidity_impulse
            - 0.18 * live_event_growth
            - 0.10 * max(0.0, bullish - 0.55)
        )
        if systemic > 0.60:
            cash_target += 0.06 + 0.06 * max(0.0, systemic - 0.60) * 2.0
        if war_oil_rate > 0.60:
            cash_target += 0.04 + 0.04 * max(0.0, war_oil_rate - 0.60) * 2.0
        if carry_unwind > 0.58:
            cash_target += 0.04 + 0.03 * max(0.0, carry_unwind - 0.58) * 2.0
        if stagflation_eff > 0.60:
            cash_target += 0.04 + 0.03 * max(0.0, stagflation_eff - 0.60) * 2.0
        if liquidity_drain > 0.65:
            cash_target += 0.04 + 0.03 * max(0.0, liquidity_drain - 0.65) * 2.0
        extreme_risk = max(systemic, carry_unwind, war_oil_rate, live_stress, liquidity_drain, stagflation_eff)
        if extreme_risk > 0.70:
            cash_target = max(cash_target, 0.20 + 0.30 * (extreme_risk - 0.70) / 0.30)
        concurrent_risk_count = sum([
            systemic > 0.55, carry_unwind > 0.55, war_oil_rate > 0.55,
            liquidity_drain > 0.60, stagflation_eff > 0.55,
        ])
        if concurrent_risk_count >= 3:
            cash_target = max(cash_target, 0.25 + 0.05 * (concurrent_risk_count - 3))
        if balanced_live and slow_macro_available < 0.60:
            cash_target = min(cash_target, growth_cash_cap)
        elif balanced_live and stress < 0.80:
            cash_target = min(cash_target, balanced_cash_cap)
        elif live_stress < 0.35 and stress < 0.60:
            cash_target = min(cash_target, balanced_cash_cap)
        elif live_stress < 0.45 and stress < 0.75:
            cash_target = min(cash_target, mild_risk_cash_cap)
        # Reduce cash when crisis-beneficiary sectors are available for rotation
        crisis_beneficiary_ratio = 0.0
        if "crisis_sector_beneficiary_score" in month_df.columns:
            crisis_beneficiary_ratio = float(
                (pd.to_numeric(month_df["crisis_sector_beneficiary_score"], errors="coerce") > 0.3).mean()
            )
        if crisis_beneficiary_ratio > 0.05:
            cash_target *= max(0.30, 1.0 - 1.2 * crisis_beneficiary_ratio)

        # ── Contrarian Fear/Greed: extreme fear = buy opportunity, not risk ──
        fear_greed = _median_or_default("fear_greed_score", 50.0)
        fear_greed = 50.0 if np.isnan(fear_greed) else fear_greed
        fear_delta = _median_or_default("fear_greed_delta_1w", 0.0)
        fear_delta = 0.0 if np.isnan(fear_delta) else fear_delta
        risk_on_backdrop = max(
            growth_reentry,
            growth_liquidity,
            liquidity_impulse,
            live_event_growth,
            max(0.0, breadth_regime - 0.55) / 0.25,
        )
        # Only apply contrarian logic when there is NO structural systemic crisis
        # (avoid catching falling knives during 2008-style meltdowns)
        structural_crisis = (systemic > 0.55) or (concurrent_risk_count >= 3)
        if not structural_crisis:
            # Extreme fear (< 25): Aggressively REDUCE cash → buy undervalued stocks
            # - Fear is mean-reverting; historically best 12m returns start here
            # - Stronger signal when fear is already recovering (delta > 0)
            if fear_greed < 25:
                contrarian_buy = (25.0 - fear_greed) / 25.0  # 0→1 as fear drops 25→0
                recovery_bonus = max(0.0, min(1.0, fear_delta / 10.0))  # Bounce detected
                cash_target -= 0.12 * contrarian_buy * (0.60 + 0.40 * recovery_bonus)
            elif fear_greed < 35:
                mild_buy = (35.0 - fear_greed) / 20.0  # Moderate fear zone
                cash_target -= 0.05 * mild_buy
            # Extreme greed (> 75): INCREASE cash → market overextended
            if fear_greed > 80:
                contrarian_sell = (fear_greed - 80.0) / 20.0  # 0→1 as greed rises 80→100
                if (
                    risk_on_backdrop > 0.45
                    and liquidity_drain < 0.55
                    and live_stress < cfg.live_event_risk_threshold
                ):
                    backdrop_bonus = max(0.0, min(1.0, risk_on_backdrop))
                    cash_target -= 0.10 * contrarian_sell * (0.60 + 0.40 * backdrop_bonus)
                else:
                    cash_target += 0.04 * contrarian_sell
            elif fear_greed > 70:
                mild_sell = (fear_greed - 70.0) / 20.0
                if (
                    risk_on_backdrop > 0.35
                    and liquidity_drain < 0.60
                    and live_stress < max(0.40, cfg.live_event_risk_threshold)
                ):
                    cash_target -= 0.04 * mild_sell
                else:
                    cash_target += 0.02 * mild_sell

        if extreme_risk < 0.55 and concurrent_risk_count <= 1:
            if risk_on_backdrop >= 0.60 and live_stress < 0.30 and liquidity_drain < 0.40:
                cash_target = min(cash_target, growth_cash_cap)
            elif live_stress < 0.40 and liquidity_drain < 0.50:
                cash_target = min(cash_target, balanced_cash_cap)

        # ---------------------------------------------------------
        # Phase 6b: VIX level hard guard (PHASE_ROADMAP §2.6).
        # Applied BEFORE the final np.clip so the tier floor lifts
        # cash_target up toward cfg.cash_weight_max but still honors
        # the overall cash cap. Dual-gate: cfg flag AND env var.
        # Composes with other cash controls via max().
        # ---------------------------------------------------------
        _p6b_cfg_on = bool(getattr(cfg, "vix_level_guard_enabled", True))
        _p6b_env_on = phase_is_enabled("phase6b_vix", default=True)
        if _p6b_cfg_on and _p6b_env_on:
            vix_level_val = _median_or_default("vix_level", np.nan)
            if np.isfinite(vix_level_val) and vix_level_val > 0:
                # Tier lookup: start from the highest threshold and
                # work down; first match wins. This naturally gives
                # the most defensive floor when multiple tiers are met.
                _p6b_floor = 0.0
                t4_thr = float(getattr(cfg, "vix_level_tier4_threshold", 45.0))
                t4_cash = float(getattr(cfg, "vix_level_tier4_cash_floor", 0.55))
                t3_thr = float(getattr(cfg, "vix_level_tier3_threshold", 35.0))
                t3_cash = float(getattr(cfg, "vix_level_tier3_cash_floor", 0.40))
                t2_thr = float(getattr(cfg, "vix_level_tier2_threshold", 28.0))
                t2_cash = float(getattr(cfg, "vix_level_tier2_cash_floor", 0.25))
                t1_thr = float(getattr(cfg, "vix_level_tier1_threshold", 22.0))
                t1_cash = float(getattr(cfg, "vix_level_tier1_cash_floor", 0.10))
                if vix_level_val >= t4_thr:
                    _p6b_floor = t4_cash
                elif vix_level_val >= t3_thr:
                    _p6b_floor = t3_cash
                elif vix_level_val >= t2_thr:
                    _p6b_floor = t2_cash
                elif vix_level_val >= t1_thr:
                    _p6b_floor = t1_cash
                if _p6b_floor > 0.0:
                    cash_target = max(cash_target, _p6b_floor)

        cash_target = float(np.clip(cash_target, 0.0, cfg.cash_weight_max))
    if cash_target >= 0.12:
        target_adj -= 1.0

    base.update(
        {
            "risk_multiplier": float(risk_multiplier),
            "turnover_multiplier": float(turnover_multiplier),
            "liquidity_multiplier": float(liquidity_multiplier),
            "single_name_cap": float(max(cfg.stock_weight_max, single_cap)),
            "target_n_adjustment": float(target_adj),
            "cash_target": cash_target,
        }
    )
    return base


def compute_benchmark_beating_focus_overlay(df: pd.DataFrame, cfg: EngineConfig) -> pd.DataFrame:
    d = df.copy()
    if d.empty:
        return d

    join_status = d.get("fund_join_status", pd.Series("", index=d.index, dtype=str)).astype(str)
    ttm_confirmed = join_status.isin(
        ["matched_with_ttm", "matched_with_ttm_backfill", "matched_with_ttm_fallback"]
    ).astype(float)
    fundamental_presence = numeric_series_or_default(d, "fundamental_presence_score", 0.0).clip(lower=0.0, upper=1.0)
    fundamental_reliability = numeric_series_or_default(
        d, "fundamental_reliability_score", fundamental_presence
    ).clip(lower=0.0, upper=1.0)
    live_growth_score = row_mean(
        [
            (numeric_series_or_default(d, "revenue_growth_final", np.nan) > 0.08).astype(float),
            (numeric_series_or_default(d, "earnings_growth_final", np.nan) > 0.10).astype(float),
        ],
        d.index,
    ).fillna(0.0)
    flow_confirmation_score = row_mean(
        [
            (numeric_series_or_default(d, "institutional_flow_signal_score", 0.0) > 0.10).astype(float),
            (numeric_series_or_default(d, "insider_flow_signal_score", 0.0) > 0.75).astype(float),
            (numeric_series_or_default(d, "ownership_flow_pillar_score", 0.0) > 0.10).astype(float),
            (numeric_series_or_default(d, "score_flow_satellite", 0.0) > 0.10).astype(float),
            (numeric_series_or_default(d, "actual_results_score", 0.0) > 0.05).astype(float),
        ],
        d.index,
    ).fillna(0.0)
    multidim_confirmation = numeric_series_or_default(
        d, "multidimensional_confirmation_score", 0.0
    ).clip(lower=0.0, upper=1.0)
    market_confirmation_score = (
        0.50 * live_growth_score
        + 0.30 * flow_confirmation_score
        + 0.20 * multidim_confirmation
    ).clip(lower=0.0, upper=1.0)
    fundamental_confirmation_score = np.maximum(
        ttm_confirmed,
        (0.65 * fundamental_reliability + 0.35 * fundamental_presence).clip(lower=0.0, upper=1.0),
    ).clip(lower=0.0, upper=1.0)
    selection_confirmation_score = (
        pd.concat(
            [
                fundamental_confirmation_score,
                0.85 * market_confirmation_score,
                (
                    0.55 * ttm_confirmed
                    + 0.20 * numeric_series_or_default(d, "fund_panel_ttm_ready", 0.0).clip(lower=0.0, upper=1.0)
                    + 0.15 * flow_confirmation_score
                    + 0.10 * multidim_confirmation
                ),
            ],
            axis=1,
        )
        .max(axis=1)
        .clip(lower=0.0, upper=1.0)
    )
    d["selection_ttm_confirmation_score"] = ttm_confirmed
    d["selection_fundamental_confirmation_score"] = fundamental_confirmation_score
    d["selection_live_growth_score"] = live_growth_score
    d["selection_flow_confirmation_score"] = flow_confirmation_score
    d["selection_market_confirmation_score"] = market_confirmation_score
    d["selection_confirmation_score"] = selection_confirmation_score

    tickers = d.get("ticker", pd.Series("", index=d.index, dtype=str)).astype(str).str.upper()
    primary_names = {str(t).upper() for t in cfg.focus_primary_tickers}
    optional_names = {str(t).upper() for t in cfg.focus_optional_tickers}
    primary_flag = tickers.isin(primary_names).astype(float)
    optional_flag = tickers.isin(optional_names).astype(float)
    direct_flag = (primary_flag.add(optional_flag, fill_value=0.0) > 0).astype(float)
    dynamic_leader = cross_sectional_robust_z(d, "dynamic_leader_score")
    sector_leader = cross_sectional_robust_z(d, "sector_leader_score")
    within_sector = cross_sectional_robust_z(d, "within_sector_leader_score")
    emergence = cross_sectional_robust_z(d, "leader_emergence_score")
    safety = cross_sectional_robust_z(d, "leader_safety_score")
    valuation = cross_sectional_robust_z(d, "forward_value_score")
    garp = cross_sectional_robust_z(d, "garp_score")
    moat = cross_sectional_robust_z(d, "moat_proxy_score")
    blueprint = cross_sectional_robust_z(d, "strategy_blueprint_score")
    technical_blueprint = cross_sectional_robust_z(d, "technical_blueprint_score")
    revision_blueprint = cross_sectional_robust_z(d, "revision_blueprint_score")
    size_saturation = cross_sectional_robust_z(d, "size_saturation_score").clip(lower=0.0)
    macro_fit = row_mean(
        [
            cross_sectional_robust_z(d, "macro_momentum_regime_interaction"),
            cross_sectional_robust_z(d, "macro_tech_leadership_interaction"),
            cross_sectional_robust_z(d, "macro_semis_cycle_interaction"),
            cross_sectional_robust_z(d, "macro_energy_oil_interaction"),
            cross_sectional_robust_z(d, "macro_defensive_riskoff_interaction"),
        ],
        d.index,
    ).fillna(0.0)
    benchmark_alpha_signal = row_mean(
        [
            cross_sectional_robust_z(d, "rs_benchmark_3m"),
            cross_sectional_robust_z(d, "rs_benchmark_6m"),
            cross_sectional_robust_z(d, "rs_benchmark_12m"),
            0.60 * cross_sectional_robust_z(d, "dd_gap_benchmark"),
        ],
        d.index,
    ).fillna(0.0)
    systemic = numeric_series_or_default(d, "systemic_crisis_score", 0.0).clip(lower=0.0, upper=1.0)
    carry_unwind = numeric_series_or_default(d, "carry_unwind_stress_score", 0.0).clip(lower=0.0, upper=1.0)
    war_oil_rate = numeric_series_or_default(d, "war_oil_rate_shock_score", 0.0).clip(lower=0.0, upper=1.0)
    defensive_rotation = numeric_series_or_default(d, "defensive_rotation_score", 0.0).clip(lower=0.0, upper=1.0)
    growth_reentry = numeric_series_or_default(d, "growth_reentry_score", 0.0).clip(lower=0.0, upper=1.0)
    live_event_risk = numeric_series_or_default(d, "live_event_risk_score", 0.0).clip(lower=0.0, upper=1.0)
    live_event_systemic = numeric_series_or_default(d, "live_event_systemic_score", 0.0).clip(lower=0.0, upper=1.0)
    live_event_war = numeric_series_or_default(d, "live_event_war_oil_rate_score", 0.0).clip(lower=0.0, upper=1.0)
    live_event_defensive = numeric_series_or_default(d, "live_event_defensive_score", 0.0).clip(lower=0.0, upper=1.0)
    live_event_growth = numeric_series_or_default(d, "live_event_growth_reentry_score", 0.0).clip(lower=0.0, upper=1.0)
    live_event_stress = np.maximum(live_event_risk, np.maximum(live_event_systemic, live_event_war))
    neg_mid_mom = (
        (numeric_series_or_default(d, "mom_3m", 0.0) < 0.0)
        & (numeric_series_or_default(d, "mom_6m", 0.0) < 0.0)
    )
    emergence = emergence.where(
        ~neg_mid_mom | (emergence <= 0),
        emergence * (1.0 - float(cfg.focus_negative_momentum_emergence_penalty)),
    )
    dynamic_leader = dynamic_leader.where(
        ~neg_mid_mom | (dynamic_leader <= 0),
        dynamic_leader * 0.75,
    )

    direct_tie_break = float(cfg.focus_direct_ticker_tiebreak) * (primary_flag + 0.40 * optional_flag)
    ai_infra_exposure = numeric_series_or_default(d, "ai_infra_exposure", 0.0).clip(lower=0.0, upper=1.0)
    power_infra_exposure = numeric_series_or_default(d, "power_infra_exposure", 0.0).clip(lower=0.0, upper=1.0)
    hedge_exposure = row_mean(
        [
            numeric_series_or_default(d, "defense_exposure", 0.0).clip(lower=0.0, upper=1.0),
            numeric_series_or_default(d, "energy_hedge_exposure", 0.0).clip(lower=0.0, upper=1.0),
        ],
        d.index,
    ).fillna(0.0)

    d["focus_ai_infra_flag"] = (ai_infra_exposure > 0.5).astype(float)
    d["focus_power_infra_flag"] = (power_infra_exposure > 0.5).astype(float)
    d["focus_hedge_flag"] = (hedge_exposure > 0.5).astype(float)
    d["focus_primary_flag"] = primary_flag
    d["focus_optional_flag"] = optional_flag
    d["focus_direct_flag"] = direct_flag
    d["focus_ai_infra_score"] = 0.18 * ai_infra_exposure
    d["focus_power_infra_score"] = 0.18 * power_infra_exposure
    d["focus_hedge_score"] = 0.10 * hedge_exposure
    d["focus_primary_score"] = direct_tie_break
    d["focus_optional_score"] = 0.0
    d["focus_benchmark_alpha_score"] = 0.16 * benchmark_alpha_signal
    growth_regime_fit = row_mean(
        [
            benchmark_alpha_signal,
            technical_blueprint,
            revision_blueprint,
            0.65 * dynamic_leader,
            0.55 * pd.to_numeric(d["focus_ai_infra_score"], errors="coerce").fillna(0.0),
            0.40 * pd.to_numeric(d["focus_power_infra_score"], errors="coerce").fillna(0.0),
        ],
        d.index,
    ).fillna(0.0)
    defensive_regime_fit = row_mean(
        [
            moat,
            safety,
            macro_fit,
            0.70 * pd.to_numeric(d["focus_hedge_score"], errors="coerce").fillna(0.0),
            0.65 * robust_z(np.maximum(fundamental_reliability, 0.85 * market_confirmation_score)).fillna(0.0),
        ],
        d.index,
    ).fillna(0.0)
    d["focus_growth_regime_score"] = float(cfg.growth_reentry_strength) * growth_reentry * growth_regime_fit
    d["focus_defensive_regime_score"] = float(cfg.defensive_rotation_strength) * defensive_rotation * defensive_regime_fit
    d["focus_live_event_growth_score"] = float(cfg.live_event_alert_strength) * live_event_growth * growth_regime_fit
    d["focus_live_event_defensive_score"] = float(cfg.live_event_alert_strength) * live_event_defensive * defensive_regime_fit
    d["focus_event_stress_penalty"] = 0.08 * np.maximum(systemic, carry_unwind) * np.clip(-benchmark_alpha_signal, 0.0, None)
    d["focus_live_event_risk_penalty"] = (
        0.60
        * float(cfg.live_event_alert_strength)
        * live_event_stress
        * np.clip(-benchmark_alpha_signal + 0.25 * size_saturation, 0.0, None)
    )
    d["focus_megacap_hugging_penalty"] = (
        float(cfg.benchmark_hugging_penalty)
        * size_saturation
        * np.clip(0.12 - benchmark_alpha_signal, 0.0, None)
        * (
            0.35
            + 0.65
            * np.maximum(
                np.maximum(defensive_rotation, np.maximum(systemic, war_oil_rate)),
                live_event_stress,
            )
        )
    )
    d["benchmark_beating_focus_score"] = (
        0.36 * dynamic_leader
        + 0.16 * sector_leader
        + 0.14 * within_sector
        + 0.12 * emergence
        + 0.06 * safety
        + 0.08 * valuation
        + 0.05 * macro_fit
        + 0.09 * moat
        + 0.12 * garp
        + 0.12 * blueprint
        + 0.05 * technical_blueprint
        + 0.04 * revision_blueprint
        + pd.to_numeric(d["focus_benchmark_alpha_score"], errors="coerce").fillna(0.0)
        + pd.to_numeric(d["focus_growth_regime_score"], errors="coerce").fillna(0.0)
        + pd.to_numeric(d["focus_defensive_regime_score"], errors="coerce").fillna(0.0)
        + pd.to_numeric(d["focus_live_event_growth_score"], errors="coerce").fillna(0.0)
        + pd.to_numeric(d["focus_live_event_defensive_score"], errors="coerce").fillna(0.0)
        + pd.to_numeric(d["focus_ai_infra_score"], errors="coerce").fillna(0.0)
        + pd.to_numeric(d["focus_power_infra_score"], errors="coerce").fillna(0.0)
        + pd.to_numeric(d["focus_hedge_score"], errors="coerce").fillna(0.0)
        + 0.02 * size_saturation
        + direct_tie_break
    )
    sector = d.get("sector", pd.Series("Unknown", index=d.index, dtype=str)).fillna("Unknown").astype(str)
    sector_focus_mean = pd.Series(d["benchmark_beating_focus_score"], index=d.index, dtype=float).groupby(sector).transform("mean")
    sector_counts = sector.map(sector.value_counts()).astype(float)
    crowding = (
        0.70 * robust_z(sector_focus_mean).fillna(0.0).clip(lower=0.0)
        + 0.30 * robust_z(sector_counts).fillna(0.0).clip(lower=0.0)
    )
    d["sector_crowding_penalty"] = float(cfg.focus_sector_crowding_penalty) * crowding
    d["benchmark_beating_focus_score"] = (
        d["benchmark_beating_focus_score"]
        - float(cfg.focus_missing_fundamental_penalty)
        * np.clip(0.40 - np.maximum(fundamental_confirmation_score, 0.85 * market_confirmation_score), 0.0, None)
        - d["sector_crowding_penalty"]
        - pd.to_numeric(d["focus_event_stress_penalty"], errors="coerce").fillna(0.0)
        - pd.to_numeric(d["focus_live_event_risk_penalty"], errors="coerce").fillna(0.0)
        - pd.to_numeric(d["focus_megacap_hugging_penalty"], errors="coerce").fillna(0.0)
    )
    d["focus_bucket"] = np.select(
        [
            live_event_systemic >= cfg.live_event_risk_threshold,
            live_event_war >= max(0.48, cfg.live_event_risk_threshold - 0.05),
            live_event_growth >= cfg.live_event_growth_threshold,
            growth_reentry >= 0.60,
            defensive_rotation >= 0.55,
            pd.to_numeric(d["leader_emergence_score"], errors="coerce").fillna(0.0) > 0.40,
            pd.to_numeric(d["sector_leader_score"], errors="coerce").fillna(0.0) > 0.35,
            pd.to_numeric(d["leader_safety_score"], errors="coerce").fillna(0.0) > 0.25,
        ],
        [
            "systemic_alert",
            "war_oil_rate_alert",
            "growth_reentry_alert",
            "growth_reentry",
            "defensive_rotation",
            "emerging_leader",
            "sector_leader",
            "defensive_leader",
        ],
        default="neutral",
    )
    return d


# =====================================================================
# Stage 4b-ii: build_target_portfolio + 21 portfolio-construction helpers
# =====================================================================
# Moved from r1000_top30_institutional.py in 5 blocks. Total ~1,513 lines.
#
# Block 1 (was 684-712):
#   apply_portfolio_candidate_gate_filter  (sleeve-aware candidate gate)
#
# Block 2 (was 8326-8703): 7 target helpers + 4 interleaved portfolio helpers.
#   compute_dynamic_sector_caps, select_topn_with_sector_limits,
#   choose_dynamic_target_count, resolve_dynamic_weight_cap,
#   truncate_weight_dict, materialize_weight_frame, company_key_series,
#   dedupe_same_company_rows, _scaled_unit_from_series, apply_hold_policy_overlay
#
# Block 3 (was 11092-11152):
#   apply_sleeve_entry_drift_name_caps
#
# Block 4 (was 11155-12151): THE build_target_portfolio (739L) + 8 helpers.
#   build_target_portfolio, normalize_with_limits, apply_sector_weight_caps,
#   dict_from_weights, apply_cash_buffer_to_weights,
#   drift_weights_by_period_returns, turnover, cap_turnover,
#   accelerate_cash_deployment
#
# Block 5 (was 14746-14793):
#   resolve_regime_conditioned_sleeve_override

def apply_portfolio_candidate_gate_filter(
    df: pd.DataFrame,
    cfg: EngineConfig,
    context: str,
) -> pd.DataFrame:
    # Late import to avoid signals -> pipeline circular import at module load time.
    # annotate_portfolio_candidate_gate is defined in r1000_pipeline.py.
    from r1000_pipeline import annotate_portfolio_candidate_gate
    d = annotate_portfolio_candidate_gate(df, cfg)
    if d.empty:
        return d
    sleeve_label = d.get(
        "portfolio_sleeve_label",
        d.get("portfolio_sleeve_label_raw", pd.Series("core_compounder", index=d.index, dtype=object)),
    ).fillna("core_compounder").astype(str)
    gate_keep = d["portfolio_candidate_minimum_pass"].fillna(False).astype(bool)
    removed = int((~gate_keep).sum())
    kept = int(gate_keep.sum())
    if removed > 0:
        gate_summary = {
            str(k): int(v)
            for k, v in d.loc[gate_keep, "portfolio_candidate_gate_label"].astype(str).value_counts().items()
        }
        sleeve_summary = {
            str(k): int(v)
            for k, v in sleeve_label.loc[gate_keep].astype(str).value_counts().items()
        }
        log(
            f"{context}: sleeve-aware gate kept={kept}, removed={removed}, "
            f"gate_modes={gate_summary}, sleeves={sleeve_summary}"
        )
    return d[gate_keep].copy()


def compute_dynamic_sector_caps(cfg: EngineConfig, month_df: pd.DataFrame) -> dict[str, float]:
    sec = month_df[month_df["sector"].notna()].copy()
    sec = sec[~sec["sector"].isin(["Unknown", "Market"])]
    if sec.empty:
        return {}
    leader_col = "sector_leader_score" if "sector_leader_score" in sec.columns else "mom_6m"
    stats = (
        sec.groupby("sector")
        .agg(avg_mom=("mom_6m", "mean"), avg_dist=("dist_ma200", "mean"), leader_signal=(leader_col, "mean"), n=("ticker", "count"))
        .reset_index()
        .sort_values(["leader_signal", "avg_mom"], ascending=False)
    )
    leaders = stats["sector"].head(cfg.leader_n_sectors).tolist()
    laggers = stats["sector"].tail(cfg.lagger_n_sectors).tolist()
    caps = {}
    # Determine active crisis for overheat exemption
    active_crisis_sectors: set[str] = set()
    for crisis_key, regime_col in [
        ("war_oil_rate_shock", "war_oil_rate_shock_score"),
        ("systemic_crisis", "systemic_crisis_score"),
        ("stagflation", "stagflation_score"),
        ("carry_unwind", "carry_unwind_score"),
    ]:
        regime_val = pd.to_numeric(sec.get(regime_col), errors="coerce").mean()
        if pd.notna(regime_val) and regime_val > 0.45:
            for s in CRISIS_SECTOR_BENEFICIARIES.get(crisis_key, {}):
                active_crisis_sectors.add(s)

    for r in stats.itertuples(index=False):
        cap = cfg.cap_base_weight
        if r.sector in laggers:
            cap = cfg.cap_lagger_weight
        elif r.sector in leaders:
            cap = cfg.cap_leader_weight
            # Exempt crisis beneficiary sectors from overheat penalty
            if pd.notna(r.avg_dist) and r.avg_dist > cfg.overheat_thr and r.sector not in active_crisis_sectors:
                cap = cfg.cap_overheated_weight
        caps[r.sector] = cap
    return caps


def select_topn_with_sector_limits(
    cfg: EngineConfig,
    month_df: pd.DataFrame,
    caps: dict[str, float],
    target_n: Optional[int] = None,
) -> pd.DataFrame:
    d = month_df.copy()
    if "portfolio_seed_score" in d.columns:
        rank_col = "portfolio_seed_score"
    else:
        d["portfolio_seed_overheat_penalty"] = 0.0
        d["portfolio_seed_score"] = numeric_series_or_default(d, "score", 0.0).fillna(0.0)
        rank_col = "portfolio_seed_score"
    d = d.sort_values(rank_col, ascending=False).copy()
    if d.empty:
        return d
    limit_n = int(target_n or cfg.top_n)
    count_caps = {s: max(1, int(math.floor(w * limit_n))) for s, w in caps.items()}
    default_cap = max(1, int(math.floor(cfg.cap_base_weight * limit_n)))
    picked = []
    sec_count: dict[str, int] = {}
    cik_count: dict[str, int] = {}
    for r in d.itertuples(index=False):
        sec = getattr(r, "sector", "Unknown")
        cap = count_caps.get(sec, default_cap)
        if sec_count.get(sec, 0) >= cap:
            continue
        cik = str(getattr(r, "cik10", ""))
        if cfg.max_names_per_cik > 0 and cik and cik.lower() != "nan":
            if cik_count.get(cik, 0) >= cfg.max_names_per_cik:
                continue
        picked.append(r)
        sec_count[sec] = sec_count.get(sec, 0) + 1
        if cik and cik.lower() != "nan":
            cik_count[cik] = cik_count.get(cik, 0) + 1
        if len(picked) >= limit_n:
            break
    if len(picked) < limit_n:
        picked_tickers = {str(getattr(r, "ticker", "")) for r in picked}
        for r in d.itertuples(index=False):
            ticker = str(getattr(r, "ticker", ""))
            if ticker in picked_tickers:
                continue
            cik = str(getattr(r, "cik10", ""))
            if cfg.max_names_per_cik > 0 and cik and cik.lower() != "nan":
                if cik_count.get(cik, 0) >= cfg.max_names_per_cik:
                    continue
            picked.append(r)
            picked_tickers.add(ticker)
            if cik and cik.lower() != "nan":
                cik_count[cik] = cik_count.get(cik, 0) + 1
            if len(picked) >= limit_n:
                break
    return pd.DataFrame(picked)


def choose_dynamic_target_count(cfg: EngineConfig, month_df: pd.DataFrame) -> int:
    d = month_df.sort_values("score", ascending=False).copy()
    if d.empty:
        return 0
    max_names = min(int(cfg.top_n), int(len(d)))
    min_names = min(int(getattr(cfg, "min_dynamic_port_names", cfg.min_port_names)), max_names)
    if max_names <= min_names:
        return max_names

    scores = pd.to_numeric(d["score"], errors="coerce").fillna(0.0).iloc[:max_names]
    centered = scores - float(np.nanmedian(scores.values))
    raw = np.exp(np.clip(centered.values, -8.0, 8.0))
    if not np.isfinite(raw).all() or raw.sum() <= 0:
        return max_names

    coverage = np.cumsum(raw) / raw.sum()
    target = int(np.searchsorted(coverage, 0.80) + 1)
    positive_count = int((centered > 0).sum())
    if positive_count >= min_names:
        target = min(target, positive_count)

    top_block = d.iloc[:max_names].copy()

    def _median_or_default(col: str, default: float) -> float:
        if col not in top_block.columns:
            return float(default)
        val = safe_float(pd.to_numeric(top_block[col], errors="coerce").median())
        return float(default if np.isnan(val) else val)

    breadth = _median_or_default("market_breadth_regime_score", 0.50)
    participation = _median_or_default("market_sector_participation", 0.35)
    narrowing = _median_or_default("market_leadership_narrowing", 0.50)
    systemic = float(np.clip(_median_or_default("systemic_crisis_score", 0.0), 0.0, 1.0))
    carry_unwind = float(np.clip(_median_or_default("carry_unwind_stress_score", 0.0), 0.0, 1.0))
    war_oil_rate = float(np.clip(_median_or_default("war_oil_rate_shock_score", 0.0), 0.0, 1.0))
    defensive_rotation = float(np.clip(_median_or_default("defensive_rotation_score", 0.0), 0.0, 1.0))
    stagflation = float(np.clip(_median_or_default("stagflation_score", 0.0), 0.0, 1.0))
    growth_reentry = float(np.clip(_median_or_default("growth_reentry_score", 0.0), 0.0, 1.0))
    growth_liquidity = float(np.clip(_median_or_default("growth_liquidity_reentry_score", 0.0), 0.0, 1.0))
    confirmation_default = _median_or_default("fundamental_reliability_score", 0.55)
    confirmation = (
        _median_or_default("selection_confirmation_score", confirmation_default)
        if "selection_confirmation_score" in top_block.columns
        else confirmation_default
    )
    stress = max(systemic, carry_unwind, war_oil_rate, defensive_rotation, stagflation)
    growth_tailwind = max(growth_reentry, growth_liquidity)
    leader_share = float(raw[0] / raw.sum()) if raw.sum() > 0 else 0.0

    if len(scores) >= 2:
        gap = float(scores.iloc[0] - scores.iloc[1])
        if gap >= 1.50:
            target = min(target, min_names)
        elif gap >= 0.90:
            target = min(target, min_names + 2)
        elif gap >= 0.55:
            target = min(target, min_names + 4)
    else:
        gap = 9e9

    if leader_share >= 0.40 or gap >= 1.25:
        target = min(target, min(max_names, min_names + (1 if confirmation >= 0.60 else 0)))
    elif leader_share >= 0.30 or gap >= 0.90:
        target = min(target, min(max_names, min_names + 1))

    if stress >= 0.70:
        target = min(target, min(max_names, min_names))
    elif stress >= 0.55 or breadth < 0.45 or participation < 0.35:
        risk_cap = min_names + (2 if confirmation >= 0.65 else (1 if confirmation >= 0.55 else 0))
        target = min(target, min(max_names, risk_cap))
    elif stress >= 0.45:
        risk_cap = min_names + 3 + (1 if confirmation >= 0.60 else 0)
        target = min(target, min(max_names, risk_cap))

    if confirmation < 0.45:
        target = min(target, min(max_names, min_names))

    if growth_tailwind >= 0.72 and breadth > 0.65 and participation > 0.48:
        expansion = 4 + int(growth_tailwind >= 0.80) + int(narrowing < 0.40) + int(confirmation >= 0.65)
        target = max(target, min(max_names, min_names + expansion))
    elif growth_tailwind >= 0.60 and breadth > 0.58 and participation > 0.42:
        expansion = 2 + int(growth_tailwind >= 0.72) + int(narrowing < 0.45 and participation > 0.48)
        target = max(target, min(max_names, min_names + expansion))

    if positive_count >= min_names + 6 and growth_tailwind >= 0.65 and confirmation >= 0.60 and leader_share < 0.20:
        target = max(target, min(max_names, min_names + 4 + int(participation > 0.50) + int(breadth > 0.70)))

    if positive_count >= min_names + 8 and growth_tailwind >= 0.72 and breadth > 0.65 and stress < 0.30:
        target = max(target, min(max_names, positive_count))

    return int(max(min_names, min(target, max_names)))


def resolve_dynamic_weight_cap(cfg: EngineConfig, selected: pd.DataFrame) -> float:
    if selected.empty:
        return cfg.stock_weight_max
    scores = pd.to_numeric(selected["score"], errors="coerce").fillna(0.0).sort_values(ascending=False).reset_index(drop=True)
    if scores.empty:
        return cfg.stock_weight_max
    raw = np.exp(np.clip(scores - float(scores.iloc[0]), -8.0, 0.0))
    leader_share = float(raw.iloc[0] / raw.sum()) if raw.sum() > 0 else 0.0
    gap = float(scores.iloc[0] - scores.iloc[1]) if len(scores) >= 2 else 9e9
    if leader_share >= 0.42 or gap >= 1.35:
        return cfg.stock_weight_max_high_conviction
    if leader_share >= 0.30 or gap >= 0.90:
        return min(cfg.stock_weight_max_high_conviction, max(cfg.stock_weight_max * 1.75, 0.24))
    if leader_share >= 0.22 or gap >= 0.55:
        return min(cfg.stock_weight_max_high_conviction, max(cfg.stock_weight_max * 1.35, 0.18))
    return cfg.stock_weight_max


def truncate_weight_dict(weights: dict[str, float], max_names: int) -> dict[str, float]:
    cash_weight = float(weights.get(CASH_PROXY_TICKER, 0.0)) if pd.notna(weights.get(CASH_PROXY_TICKER, 0.0)) else 0.0
    ranked = [
        (k, float(v))
        for k, v in weights.items()
        if k != CASH_PROXY_TICKER and pd.notna(v) and float(v) > 0
    ]
    ranked = sorted(ranked, key=lambda x: x[1], reverse=True)
    ranked = ranked[:max(0, int(max_names))]
    kept_total = sum(v for _, v in ranked) + max(cash_weight, 0.0)
    if kept_total <= 0:
        return {}
    residual_cash = max(0.0, 1.0 - kept_total)
    out = {k: v for k, v in ranked}
    realized_cash = max(cash_weight, 0.0) + residual_cash
    if realized_cash > 0:
        out[CASH_PROXY_TICKER] = realized_cash
    total = float(sum(out.values()))
    if total > 0 and abs(total - 1.0) > 1e-8:
        out = {k: float(v / total) for k, v in out.items()}
    return out


def materialize_weight_frame(month_df: pd.DataFrame, weights: dict[str, float]) -> pd.DataFrame:
    rows = []
    for ticker, weight in sorted(weights.items(), key=lambda x: x[1], reverse=True):
        if str(ticker).upper() == CASH_PROXY_TICKER:
            rows.append(
                {
                    "ticker": CASH_PROXY_TICKER,
                    "Name": "Cash",
                    "sector": "Cash",
                    "weight": float(weight),
                    "score": np.nan,
                }
            )
            continue
        row = month_df[month_df["ticker"] == ticker].head(1)
        if row.empty:
            rows.append({"ticker": ticker, "weight": float(weight), "sector": "Unknown", "Name": "", "score": np.nan})
            continue
        rec = row.iloc[0].to_dict()
        rec["weight"] = float(weight)
        rows.append(rec)
    return pd.DataFrame(rows)


def company_key_series(df: pd.DataFrame) -> pd.Series:
    if "cik10" in df.columns:
        key = df["cik10"]
    elif "cik" in df.columns:
        key = df["cik"]
    else:
        key = pd.Series(index=df.index, dtype=object)
    key = key.astype(str).str.strip()
    bad = key.isin({"", "nan", "None", "<NA>"})
    ticker_fallback = "ticker:" + df.get("ticker", pd.Series(index=df.index, dtype=object)).astype(str).fillna("")
    return key.where(~bad, ticker_fallback)


def dedupe_same_company_rows(
    df: pd.DataFrame,
    score_col: str = "score",
    selected_col: Optional[str] = None,
) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    d = df.copy()
    d["_company_key"] = company_key_series(d)
    sort_cols: list[str] = []
    ascending: list[bool] = []
    if selected_col and selected_col in d.columns:
        d[selected_col] = d[selected_col].fillna(False).astype(bool)
        sort_cols.append(selected_col)
        ascending.append(False)
    for col in [score_col, "weight", "dollar_vol_20d", "market_cap_live", "mktcap"]:
        if col in d.columns:
            d[col] = pd.to_numeric(d[col], errors="coerce")
            sort_cols.append(col)
            ascending.append(False)
    if "ticker" in d.columns:
        sort_cols.append("ticker")
        ascending.append(True)
    if sort_cols:
        d = d.sort_values(sort_cols, ascending=ascending, na_position="last")
    d = d.drop_duplicates("_company_key", keep="first").drop(columns="_company_key")
    return d.reset_index(drop=True)


def _scaled_unit_from_series(series: pd.Series, scale: float = 2.5) -> pd.Series:
    s = pd.to_numeric(series, errors="coerce").fillna(0.0)
    return ((s / float(scale)) + 0.5).clip(lower=0.0, upper=1.0)


def apply_hold_policy_overlay(
    month_df: pd.DataFrame,
    prev_w: Optional[dict[str, float]],
    cfg: EngineConfig,
) -> pd.DataFrame:
    d = month_df.copy()
    # Bug fix 2026-04-20: unify held_from_prev_rebalance to float (was bool
    # here + float at pipeline.py:12853). Mixed dtypes caused pyarrow
    # ArrowInvalid when append_history_parquet concatenated different runs.
    # Downstream consumer (signals.py:538) coerces to float anyway.
    d["held_from_prev_rebalance"] = 0.0
    d["prev_weight"] = 0.0
    d["portfolio_hold_policy_seed_bonus"] = 0.0
    d["portfolio_hold_policy_bonus"] = 0.0
    d["portfolio_hold_policy_support"] = 0.0
    d["portfolio_hold_policy_exit_risk"] = 0.0
    if (not bool(getattr(cfg, "portfolio_hold_policy_enabled", False))) or not prev_w or d.empty or "ticker" not in d.columns:
        return d

    prev_stock_w = {
        str(k).upper(): float(v)
        for k, v in prev_w.items()
        if str(k).upper() != CASH_PROXY_TICKER and pd.notna(v) and float(v) > 1e-8
    }
    if not prev_stock_w:
        return d

    tickers = d["ticker"].astype(str).str.upper()
    held_flag = tickers.isin(prev_stock_w).astype(float)
    if held_flag.sum() <= 0:
        return d

    prev_weight = tickers.map(prev_stock_w).fillna(0.0).astype(float)
    max_prev_weight = float(prev_weight.max()) if prev_weight.notna().any() else 0.0
    prev_weight_norm = (prev_weight / max(max_prev_weight, 1e-8)).clip(lower=0.0, upper=1.0)

    confirmation = numeric_series_or_default(
        d,
        "selection_confirmation_score",
        numeric_series_or_default(d, "fundamental_reliability_score", 0.0),
    ).clip(lower=0.0, upper=1.0)
    compounder_support = _scaled_unit_from_series(cross_sectional_robust_z(d, "long_hold_compounder_score"))
    technical_hold = _scaled_unit_from_series(cross_sectional_robust_z(d, "post_breakout_hold_score"))
    trend_support = _scaled_unit_from_series(cross_sectional_robust_z(d, "score"))
    exit_risk = row_mean(
        [
            numeric_series_or_default(d, "overheat_penalty", 0.0).clip(lower=0.0, upper=1.0),
            numeric_series_or_default(d, "risk_penalty", 0.0).clip(lower=0.0, upper=1.0),
            _scaled_unit_from_series((-cross_sectional_robust_z(d, "event_reaction_score")).clip(lower=0.0)),
        ],
        d.index,
    ).fillna(0.0).clip(lower=0.0, upper=1.0)
    support = row_mean(
        [
            confirmation,
            compounder_support,
            technical_hold,
            trend_support,
        ],
        d.index,
    ).fillna(0.0).clip(lower=0.0, upper=1.0)

    seed_bonus = held_flag * (
        float(getattr(cfg, "portfolio_hold_policy_seed_weight", 0.0)) * support
        + float(getattr(cfg, "portfolio_hold_policy_prev_weight_bonus", 0.0)) * prev_weight_norm
        - float(getattr(cfg, "portfolio_hold_policy_exit_penalty_weight", 0.0)) * exit_risk
    )
    utility_bonus = held_flag * (
        float(getattr(cfg, "portfolio_hold_policy_weight", 0.0)) * support
        + float(getattr(cfg, "portfolio_hold_policy_prev_weight_bonus", 0.0)) * prev_weight_norm
        - float(getattr(cfg, "portfolio_hold_policy_exit_penalty_weight", 0.0)) * exit_risk
    )

    # Bug fix 2026-04-20: keep as float (held_flag is already float at line 2451).
    # Was .astype(bool) which caused parquet schema drift vs other call sites.
    d["held_from_prev_rebalance"] = held_flag.astype(float)
    d["prev_weight"] = prev_weight
    d["portfolio_hold_policy_support"] = support
    d["portfolio_hold_policy_exit_risk"] = exit_risk
    d["portfolio_hold_policy_seed_bonus"] = seed_bonus.clip(lower=-0.20, upper=0.35)
    d["portfolio_hold_policy_bonus"] = utility_bonus.clip(lower=-0.20, upper=0.40)
    return d


def apply_sleeve_entry_drift_name_caps(
    cfg: EngineConfig,
    sel: pd.DataFrame,
    name_caps: pd.Series,
    prev_w: Optional[dict[str, float]] = None,
) -> pd.Series:
    caps = pd.to_numeric(name_caps.reindex(sel.index), errors="coerce").fillna(float(name_caps.max())).astype(float)
    if sel.empty:
        return caps

    prev_map = {str(k): float(v) for k, v in (prev_w or {}).items() if pd.notna(v)}
    prev_weight = sel.get("ticker", pd.Series("", index=sel.index, dtype=object)).astype(str).map(prev_map).fillna(0.0)
    held_mask = prev_weight > 1e-8
    sleeve_label = sel.get("portfolio_sleeve_label", pd.Series("core_compounder", index=sel.index, dtype=object)).fillna(
        "core_compounder"
    ).astype(str)
    drift_mult = 1.0 + max(float(getattr(cfg, "sleeve_drift_headroom_pct", 0.35)), 0.0)
    no_ttm_mask = sel.get("fund_join_status", pd.Series("", index=sel.index, dtype=object)).astype(str).eq("matched_no_ttm")
    fundamental_lane = sel.get("fundamental_lane_label", pd.Series("full_ttm", index=sel.index, dtype=object)).astype(str)
    high_confirm = np.maximum(
        numeric_series_or_default(sel, "selection_fundamental_confirmation_score", 0.0),
        numeric_series_or_default(sel, "selection_market_confirmation_score", 0.0),
    )

    future_mask = sleeve_label.eq("future_winner")
    future_new_cap = float(getattr(cfg, "future_winner_entry_weight_cap", 0.10))
    future_drift_cap = float(getattr(cfg, "future_winner_drift_weight_cap", 0.18))
    future_hard_cap = float(getattr(cfg, "future_winner_hard_weight_cap", 0.24))
    if future_mask.any():
        future_cap = pd.Series(np.minimum(caps.to_numpy(dtype=float), future_new_cap), index=sel.index, dtype=float)
        future_allow_drift = future_mask & held_mask & (~no_ttm_mask) & fundamental_lane.ne("partial_scout") & (high_confirm >= 0.45)
        future_hold_cap = np.minimum(
            future_hard_cap,
            np.maximum(
                future_drift_cap,
                prev_weight.to_numpy(dtype=float) * drift_mult,
            ),
        )
        future_cap = future_cap.where(~(future_mask & held_mask), np.minimum(caps, future_drift_cap))
        future_cap = future_cap.where(~future_allow_drift, np.minimum(caps, future_hold_cap))
        caps.loc[future_mask] = future_cap.loc[future_mask]

    early_mask = sleeve_label.eq("early_scout")
    early_new_cap = float(getattr(cfg, "early_scout_entry_weight_cap", 0.05))
    early_drift_cap = float(getattr(cfg, "early_scout_drift_weight_cap", 0.10))
    early_hard_cap = float(getattr(cfg, "early_scout_hard_weight_cap", 0.14))
    if early_mask.any():
        early_cap = pd.Series(np.minimum(caps.to_numpy(dtype=float), early_new_cap), index=sel.index, dtype=float)
        early_hold_cap = np.minimum(
            early_hard_cap,
            np.maximum(
                early_drift_cap,
                prev_weight.to_numpy(dtype=float) * min(drift_mult, 1.15),
            ),
        )
        early_allow_drift = early_mask & held_mask & (high_confirm >= 0.55) & (~no_ttm_mask)
        early_cap = early_cap.where(~(early_mask & held_mask), np.minimum(caps, early_drift_cap))
        early_cap = early_cap.where(~early_allow_drift, np.minimum(caps, early_hold_cap))
        caps.loc[early_mask] = early_cap.loc[early_mask]

    return caps.clip(lower=0.0, upper=1.0)


def build_target_portfolio(
    cfg: EngineConfig,
    month_df: pd.DataFrame,
    prev_w: Optional[dict[str, float]] = None,
    apply_turnover: bool = True,
    target_n_override: Optional[int] = None,
    sleeve_override: Optional[dict] = None,
    cash_target_max: float = 1.0,
) -> tuple[pd.DataFrame, dict[str, float], dict[str, Any]]:
    if month_df.empty:
        return pd.DataFrame(), {}, {"target_n": 0, "selected_n": 0, "weight_cap": cfg.stock_weight_max}

    if "selection_confirmation_score" not in month_df.columns:
        month_df = compute_benchmark_beating_focus_overlay(month_df, cfg)
    if "minervini_momentum_alive_score" not in month_df.columns:
        month_df = compute_minervini_momentum_overlay(month_df)
    month_df = apply_hold_policy_overlay(month_df, prev_w, cfg)
    month_df = compute_portfolio_sleeve_columns(month_df, cfg)
    month_df = apply_portfolio_candidate_gate_filter(
        month_df,
        cfg,
        context="Portfolio candidate set",
    )
    if month_df.empty:
        return pd.DataFrame(), {}, {"target_n": 0, "selected_n": 0, "weight_cap": cfg.stock_weight_max}
    # ---- conviction hold: identify winners that should be held longer ----
    conviction_hold_bonus = pd.Series(0.0, index=month_df.index, dtype=float)
    if prev_w:
        prev_tickers = set(prev_w.keys())
        held_mask = month_df["ticker"].astype(str).isin(prev_tickers)
        prev_weight_series = month_df["ticker"].astype(str).map(prev_w).fillna(0.0).astype(float)
        # infer winner from weight drift: if current_weight >> original means stock appreciated
        momentum_alive = numeric_series_or_default(month_df, "minervini_momentum_alive_score", 0.0) > 0.3
        rs_strong = numeric_series_or_default(month_df, "relative_strength_composite", 0.0) > 0.0
        not_broken = numeric_series_or_default(month_df, "broken_momentum_penalty", 0.0) < 0.3
        substantial_position = prev_weight_series >= 0.02
        conviction_mask = held_mask & momentum_alive & rs_strong & not_broken & substantial_position
        conviction_hold_bonus.loc[conviction_mask] = float(cfg.conviction_hold_seed_bonus)

    # ---- valuation extreme penalty: penalize >80x forward PE with negative FCF ----
    fwd_pe = numeric_series_or_default(month_df, "forward_pe", np.nan)
    fcf_margin_val = numeric_series_or_default(month_df, "fcf_margin", 0.0)
    extreme_val_mask = (fwd_pe > float(cfg.valuation_extreme_pe_threshold)) & (fcf_margin_val < 0.0)
    val_extreme_penalty = pd.Series(0.0, index=month_df.index, dtype=float)
    val_extreme_penalty.loc[extreme_val_mask] = float(cfg.valuation_extreme_penalty_weight)

    month_df["portfolio_seed_score"] = (
        numeric_series_or_default(month_df, "score", 0.0)
        + numeric_series_or_default(month_df, "portfolio_hold_policy_seed_bonus", 0.0)
        + conviction_hold_bonus
        + 0.35 * numeric_series_or_default(month_df, "crisis_sector_beneficiary_score", 0.0)
        + 0.55 * numeric_series_or_default(month_df, "fundamental_turnaround_acceleration_score", 0.0)
        + 0.35 * numeric_series_or_default(month_df, "cashflow_inflection_under_loss_score", 0.0)
        + 0.28 * numeric_series_or_default(month_df, "sage_composite_score", 0.0)
        + 0.12 * numeric_series_or_default(month_df, "sage_g_score", 0.0)
        + 0.10 * numeric_series_or_default(month_df, "portfolio_future_winner_engine_score", 0.0)
        + 0.08 * numeric_series_or_default(month_df, "portfolio_early_scout_engine_score", 0.0)
        + float(cfg.revision_seed_score_weight) * numeric_series_or_default(month_df, "revision_blueprint_score", 0.0)
        + float(cfg.minervini_portfolio_seed_weight) * numeric_series_or_default(month_df, "minervini_momentum_alive_score", 0.0)
        + 0.25 * numeric_series_or_default(month_df, "breakout_setup_quality_score", 0.0)
        - 0.50 * float(cfg.minervini_broken_trend_penalty_weight) * numeric_series_or_default(month_df, "broken_momentum_penalty", 0.0)
        - val_extreme_penalty
    )
    month_df["conviction_hold_bonus"] = conviction_hold_bonus

    caps = compute_dynamic_sector_caps(cfg, month_df)
    regime_ctl = compute_regime_portfolio_controls(cfg, month_df)
    effective_sleeve_override = sleeve_override
    regime_sleeve_meta: dict[str, Any] = {}
    if effective_sleeve_override is None:
        effective_sleeve_override, regime_sleeve_meta = resolve_regime_conditioned_sleeve_override(cfg, month_df)
    if target_n_override is not None:
        target_n = int(max(1, min(len(month_df), int(target_n_override))))
    else:
        target_n = choose_dynamic_target_count(cfg, month_df)
        min_dynamic_names = int(getattr(cfg, "min_dynamic_port_names", cfg.min_port_names))
        target_n = int(max(min_dynamic_names, min(cfg.top_n, target_n + int(round(regime_ctl["target_n_adjustment"])))))
    sleeve_policy = compute_portfolio_sleeve_policy(cfg, month_df, regime_ctl.get("cash_target", 0.0))
    if effective_sleeve_override is not None or cash_target_max < 1.0:
        raw_cash = float(sleeve_policy.get("cash_target", 0.0))
        explicit_cash = (
            safe_float(effective_sleeve_override.get("cash"), np.nan)
            if isinstance(effective_sleeve_override, dict)
            else np.nan
        )
        capped_cash = float(
            np.clip(
                explicit_cash if np.isfinite(explicit_cash) else min(raw_cash, float(cash_target_max)),
                0.0,
                1.0,
            )
        )
        invested_share_override = max(0.0, 1.0 - capped_cash)
        if effective_sleeve_override is not None:
            total_frac = max(
                float(effective_sleeve_override.get("core", 0.0))
                + float(effective_sleeve_override.get("future", 0.0))
                + float(effective_sleeve_override.get("early", 0.0)),
                1e-8,
            )
            core_frac = float(effective_sleeve_override.get("core", 0.0)) / total_frac
            future_frac = float(effective_sleeve_override.get("future", 0.0)) / total_frac
            early_frac = float(effective_sleeve_override.get("early", 0.0)) / total_frac
            sleeve_policy = {
                **sleeve_policy,
                "core_compounder_target": core_frac * invested_share_override,
                "future_winner_target": future_frac * invested_share_override,
                "early_scout_target": early_frac * invested_share_override,
                # Phase 11: preserve multibagger_watch share -- carve out of invested before
                # redistributing core/future/early. If disabled, stays 0.
                "multibagger_watch_target": (
                    float(sleeve_policy.get("multibagger_watch_target", 0.0))
                    * (invested_share_override / max(float(sleeve_policy.get("invested_share", 1.0)), 1e-8))
                ),
                "invested_share": invested_share_override,
                "cash_target": capped_cash,
            }
            if regime_sleeve_meta:
                sleeve_policy.update(
                    {
                        "applied_regime_sleeve_policy_label": str(regime_sleeve_meta.get("policy_label", "") or ""),
                        "applied_regime_sleeve_live_label": str(regime_sleeve_meta.get("live_regime_label", "") or ""),
                        "applied_regime_sleeve_source_label": str(regime_sleeve_meta.get("selected_regime_label", "") or ""),
                    }
                )
        else:
            old_invested = max(float(sleeve_policy.get("invested_share", max(1.0 - raw_cash, 0.0))), 1e-8)
            scale = invested_share_override / old_invested
            sleeve_policy = {
                **sleeve_policy,
                "core_compounder_target": float(sleeve_policy.get("core_compounder_target", 0.0)) * scale,
                "future_winner_target": float(sleeve_policy.get("future_winner_target", 0.0)) * scale,
                "early_scout_target": float(sleeve_policy.get("early_scout_target", 0.0)) * scale,
                "multibagger_watch_target": float(sleeve_policy.get("multibagger_watch_target", 0.0)) * scale,
                "invested_share": invested_share_override,
                "cash_target": capped_cash,
            }
    pool_n = min(len(month_df), max(int(target_n) * 3, int(target_n) + 18))
    pool = month_df.sort_values("portfolio_seed_score", ascending=False).head(pool_n).copy()
    invested_share = max(float(sleeve_policy.get("invested_share", 0.0)), 1e-8)
    future_target_share = float(sleeve_policy.get("future_winner_target", 0.0))
    early_target_share = float(sleeve_policy.get("early_scout_target", 0.0))
    growth_mix_target = float(np.clip(future_target_share + early_target_share, 0.0, 1.0))
    pool_sleeve_labels = pool.get(
        "portfolio_sleeve_label",
        pd.Series("core_compounder", index=pool.index, dtype=object),
    ).fillna("core_compounder").astype(str)
    pool_fill_boost = pd.Series(0.0, index=pool.index, dtype=float)
    pool_fill_boost.loc[pool_sleeve_labels.eq("future_winner")] = 0.08 + 0.10 * growth_mix_target
    pool_fill_boost.loc[pool_sleeve_labels.eq("early_scout")] = 0.10 + 0.14 * growth_mix_target
    pool["portfolio_fill_priority"] = (
        numeric_series_or_default(pool, "portfolio_seed_score", 0.0)
        + (0.16 + 0.14 * growth_mix_target)
        * numeric_series_or_default(pool, "portfolio_future_winner_engine_score", 0.0)
        + (0.22 + 0.18 * growth_mix_target)
        * numeric_series_or_default(pool, "portfolio_early_scout_engine_score", 0.0)
        + 0.14 * numeric_series_or_default(pool, "sage_composite_score", 0.0)
        + 0.10 * numeric_series_or_default(pool, "sage_g_score", 0.0)
        + pool_fill_boost
    )
    # Phase 11 (2026-04-20): multibagger_watch count
    multibagger_target_share = float(sleeve_policy.get("multibagger_watch_target", 0.0))
    multibagger_target_n = int(np.ceil(target_n * multibagger_target_share / invested_share)) if target_n > 0 and multibagger_target_share > 0 else 0
    if multibagger_target_share > 0.0:
        # Respect configured sleeve_size as a cap
        mbw_size_cap = int(getattr(cfg, "phase11_sleeve_size", 5))
        multibagger_target_n = min(multibagger_target_n, mbw_size_cap, max(target_n - 1, 0))
    future_target_n = int(np.ceil(target_n * future_target_share / invested_share)) if target_n > 0 else 0
    if future_target_share >= 0.15 and target_n >= 8:
        future_target_n = max(future_target_n, 2)
    if future_target_share >= 0.28 and target_n >= 12:
        future_target_n = max(future_target_n, 3)
    early_target_n = int(np.ceil(target_n * early_target_share / invested_share)) if target_n > 0 else 0
    if early_target_share >= 0.06 and target_n >= 8:
        early_target_n = max(early_target_n, 2)
    if early_target_share >= 0.10 and target_n >= 12:
        early_target_n = max(early_target_n, 3)
    if early_target_share >= 0.15 and target_n >= 14:
        early_target_n = max(early_target_n, 4)
    if target_n > 1:
        max_exploratory_n = max(target_n - 1, 0)
        future_target_n = min(max(future_target_n, 0), max_exploratory_n)
        early_target_n = min(max(early_target_n, 0), max_exploratory_n)
        multibagger_target_n = min(max(multibagger_target_n, 0), max_exploratory_n)
        exploratory_n = future_target_n + early_target_n + multibagger_target_n
        while exploratory_n > max_exploratory_n:
            # Trim multibagger last (higher-conviction sleeve)
            if future_target_n >= early_target_n and future_target_n >= multibagger_target_n and future_target_n > 0:
                future_target_n -= 1
            elif early_target_n >= multibagger_target_n and early_target_n > 0:
                early_target_n -= 1
            elif multibagger_target_n > 0:
                multibagger_target_n -= 1
            else:
                break
            exploratory_n = future_target_n + early_target_n + multibagger_target_n
    else:
        future_target_n = 0
        early_target_n = 0
        multibagger_target_n = 0
    core_target_n = max(1, target_n - future_target_n - early_target_n - multibagger_target_n) if target_n > 0 else 0

    score_top_rank = pool["score"].rank(method="first", ascending=False) if "score" in pool.columns else pd.Series(np.inf, index=pool.index)
    future_engine_score = numeric_series_or_default(pool, "portfolio_future_winner_engine_score", 0.0)
    early_engine_score = numeric_series_or_default(pool, "portfolio_early_scout_engine_score", 0.0)

    def _prepare_sleeve_pool(
        base_pool: pd.DataFrame,
        preferred_mask: pd.Series,
        target_count: int,
        engine_col: str,
    ) -> pd.DataFrame:
        if base_pool.empty or target_count <= 0:
            return base_pool.iloc[0:0].copy()
        preferred_mask = preferred_mask.reindex(base_pool.index).fillna(False).astype(bool)
        preferred = base_pool.loc[preferred_mask].copy()
        preferred = preferred.sort_values(
            [engine_col, "portfolio_fill_priority", "portfolio_seed_score"],
            ascending=False,
        ) if engine_col in preferred.columns else preferred.sort_values(
            ["portfolio_fill_priority", "portfolio_seed_score"],
            ascending=False,
        )
        if len(preferred) >= target_count:
            return preferred
        remainder = base_pool.loc[~preferred_mask].copy()
        remainder = remainder.sort_values(
            [engine_col, "portfolio_fill_priority", "portfolio_seed_score"],
            ascending=False,
        ) if engine_col in remainder.columns else remainder.sort_values(
            ["portfolio_fill_priority", "portfolio_seed_score"],
            ascending=False,
        )
        needed = max(target_count - len(preferred), 0)
        if needed <= 0 or remainder.empty:
            return preferred
        return pd.concat([preferred, remainder.head(needed)], ignore_index=False)

    sleeve_labels = pool.get("portfolio_sleeve_label", pd.Series("core_compounder", index=pool.index, dtype=object)).astype(str)
    top_score_early_mask = (
        sleeve_labels.eq("early_scout")
        & (score_top_rank <= max(target_n, 12))
        & (pd.to_numeric(pool.get("score"), errors="coerce").notna())
    )
    if early_target_n <= 1 and early_target_share >= 0.03 and target_n >= 10 and bool(top_score_early_mask.any()):
        early_target_n = 2
        core_target_n = max(1, target_n - future_target_n - early_target_n - multibagger_target_n)
    if target_n >= 8:
        max_core_ratio = 0.40
        if early_target_share >= 0.10:
            max_core_ratio = 0.35
        if (future_target_share + early_target_share) >= 0.45:
            max_core_ratio = 0.32
        if (future_target_share + early_target_share) >= 0.60:
            max_core_ratio = 0.25
        max_core_target_n = max(1, int(np.floor(target_n * max_core_ratio)))
        while core_target_n > max_core_target_n and (future_target_n + early_target_n) < target_n:
            if early_target_share >= max(0.08, 0.70 * future_target_share):
                early_target_n += 1
            else:
                future_target_n += 1
            core_target_n = max(1, target_n - future_target_n - early_target_n - multibagger_target_n)
    future_fallback_from_early = (
        sleeve_labels.eq("early_scout")
        & (score_top_rank <= max(target_n + 4, 14))
        & (future_engine_score >= future_engine_score.quantile(0.70))
        & ((early_engine_score - future_engine_score) < 0.45)
    )
    core_pool = _prepare_sleeve_pool(
        pool,
        ~(sleeve_labels.eq("future_winner") | sleeve_labels.eq("early_scout")),
        core_target_n,
        "portfolio_core_compounder_engine_score",
    )
    core_pool["portfolio_seed_score"] = row_mean(
        [
            numeric_series_or_default(core_pool, "portfolio_seed_score", 0.0),
            0.90 * numeric_series_or_default(core_pool, "portfolio_core_compounder_engine_score", 0.0),
        ],
        core_pool.index,
    ).fillna(0.0)
    core_sel = select_topn_with_sector_limits(cfg, core_pool, caps, target_n=core_target_n)

    future_sel = pd.DataFrame()
    if future_target_n > 0:
        future_pool = _prepare_sleeve_pool(
            pool,
            sleeve_labels.eq("future_winner") | future_fallback_from_early,
            future_target_n,
            "portfolio_future_winner_engine_score",
        )
        future_pool["portfolio_seed_score"] = row_mean(
            [
                numeric_series_or_default(future_pool, "portfolio_seed_score", 0.0),
                1.05 * numeric_series_or_default(future_pool, "portfolio_future_winner_engine_score", 0.0),
            ],
            future_pool.index,
        ).fillna(0.0)
        future_sel = select_topn_with_sector_limits(cfg, future_pool, caps, target_n=future_target_n)
        if not future_sel.empty:
            future_sel = future_sel.copy()
            future_sel["portfolio_sleeve_label"] = "future_winner"

    early_sel = pd.DataFrame()
    if early_target_n > 0:
        early_pool = _prepare_sleeve_pool(
            pool,
            sleeve_labels.eq("early_scout"),
            early_target_n,
            "portfolio_early_scout_engine_score",
        )
        early_pool["portfolio_seed_score"] = row_mean(
            [
                numeric_series_or_default(early_pool, "portfolio_seed_score", 0.0),
                1.10 * numeric_series_or_default(early_pool, "portfolio_early_scout_engine_score", 0.0),
            ],
            early_pool.index,
        ).fillna(0.0)
        early_sel = select_topn_with_sector_limits(cfg, early_pool, caps, target_n=early_target_n)
        if not early_sel.empty:
            early_sel = early_sel.copy()
            early_sel["portfolio_sleeve_label"] = "early_scout"

    # Phase 11 (2026-04-20): multibagger_watch selection block.
    # Selects names pre-labeled "multibagger_watch" by compute_portfolio_sleeve_columns
    # (via _apply_multibagger_watch_sleeve_override). Ranks by phase11_p_entry.
    multibagger_sel = pd.DataFrame()
    if multibagger_target_n > 0:
        mbw_pool = _prepare_sleeve_pool(
            pool,
            sleeve_labels.eq("multibagger_watch"),
            multibagger_target_n,
            "phase11_p_entry" if "phase11_p_entry" in pool.columns else "portfolio_seed_score",
        )
        if not mbw_pool.empty:
            mbw_pool["portfolio_seed_score"] = row_mean(
                [
                    numeric_series_or_default(mbw_pool, "portfolio_seed_score", 0.0),
                    2.00 * numeric_series_or_default(mbw_pool, "phase11_p_entry", 0.0),
                ],
                mbw_pool.index,
            ).fillna(0.0)
            multibagger_sel = select_topn_with_sector_limits(cfg, mbw_pool, caps, target_n=multibagger_target_n)
            if not multibagger_sel.empty:
                multibagger_sel = multibagger_sel.copy()
                multibagger_sel["portfolio_sleeve_label"] = "multibagger_watch"

    # If early-scout cannot fill its target seats, hand the deficit to future-winner
    # before falling back to the generic pool.
    early_shortfall_n = max(0, int(early_target_n) - int(len(early_sel)))
    if early_shortfall_n > 0:
        supplemental_future_pool = pool.copy()
        selected_tickers: set[str] = set()
        for frame in [core_sel, future_sel, early_sel, multibagger_sel]:
            if not frame.empty and "ticker" in frame.columns:
                selected_tickers.update(frame["ticker"].astype(str).tolist())
        if selected_tickers and "ticker" in supplemental_future_pool.columns:
            supplemental_future_pool = supplemental_future_pool[
                ~supplemental_future_pool["ticker"].astype(str).isin(selected_tickers)
            ].copy()
        if not supplemental_future_pool.empty:
            supplemental_future_pool = _prepare_sleeve_pool(
                supplemental_future_pool,
                (
                    sleeve_labels.reindex(supplemental_future_pool.index).fillna("").eq("future_winner")
                    | future_fallback_from_early.reindex(supplemental_future_pool.index).fillna(False).astype(bool)
                ),
                early_shortfall_n,
                "portfolio_future_winner_engine_score",
            )
            if not supplemental_future_pool.empty:
                supplemental_future_pool["portfolio_seed_score"] = row_mean(
                    [
                        numeric_series_or_default(supplemental_future_pool, "portfolio_seed_score", 0.0),
                        1.05 * numeric_series_or_default(
                            supplemental_future_pool, "portfolio_future_winner_engine_score", 0.0
                        ),
                    ],
                    supplemental_future_pool.index,
                ).fillna(0.0)
                supplemental_future_sel = select_topn_with_sector_limits(
                    cfg,
                    supplemental_future_pool,
                    caps,
                    target_n=early_shortfall_n,
                )
                if not supplemental_future_sel.empty:
                    supplemental_future_sel = supplemental_future_sel.copy()
                    supplemental_future_sel["portfolio_sleeve_label"] = "future_winner"
                    future_sel = (
                        pd.concat([future_sel, supplemental_future_sel], ignore_index=True)
                        if not future_sel.empty
                        else supplemental_future_sel
                    )
                    future_sel = dedupe_same_company_rows(future_sel, score_col="portfolio_seed_score")

    if not core_sel.empty:
        core_sel = core_sel.copy()
        core_sel["portfolio_sleeve_label"] = core_sel.get(
            "portfolio_sleeve_label", pd.Series("core_compounder", index=core_sel.index, dtype=object)
        )
        core_sel["portfolio_sleeve_label"] = np.where(
            core_sel["portfolio_sleeve_label"].astype(str).eq("future_winner"),
            "core_compounder",
            core_sel["portfolio_sleeve_label"],
        )

    sleeve_frames = [frame for frame in [core_sel, future_sel, early_sel, multibagger_sel] if not frame.empty]
    sel = pd.concat(sleeve_frames, ignore_index=True) if sleeve_frames else pd.DataFrame()
    if not sel.empty:
        sel = dedupe_same_company_rows(sel, score_col="portfolio_seed_score")
    if sel.empty or len(sel) < target_n:
        fill_pool = pool.copy()
        if not sel.empty and "ticker" in sel.columns:
            fill_pool = fill_pool[~fill_pool["ticker"].astype(str).isin(sel["ticker"].astype(str))].copy()
        fill_needed = max(0, target_n - len(sel))
        if fill_needed > 0 and not fill_pool.empty:
            if growth_mix_target >= 0.35:
                fill_pool = fill_pool.copy()
                fill_pool["portfolio_seed_score"] = row_mean(
                    [
                        numeric_series_or_default(fill_pool, "portfolio_seed_score", 0.0),
                        1.10 * numeric_series_or_default(fill_pool, "portfolio_fill_priority", 0.0),
                    ],
                    fill_pool.index,
                ).fillna(0.0)
            fill_sel = select_topn_with_sector_limits(cfg, fill_pool, caps, target_n=fill_needed)
            if not fill_sel.empty:
                fill_sel = fill_sel.copy()
                fill_sel["portfolio_sleeve_label"] = fill_sel.get(
                    "portfolio_sleeve_label",
                    pd.Series("core_compounder", index=fill_sel.index, dtype=object),
                )
                sel = pd.concat([sel, fill_sel], ignore_index=True) if not sel.empty else fill_sel
                sel = dedupe_same_company_rows(sel, score_col="portfolio_seed_score")
    if len(sel) > target_n:
        sel = sel.sort_values("portfolio_seed_score", ascending=False).head(target_n).copy()
    if sel.empty:
        return pd.DataFrame(), {}, {"target_n": 0, "selected_n": 0, "weight_cap": cfg.stock_weight_max}

    sel = sel.copy()
    if "selection_confirmation_score" not in sel.columns:
        sel = compute_benchmark_beating_focus_overlay(sel, cfg)
    utility_score = cross_sectional_robust_z(sel, "score")
    seed_score_rank = cross_sectional_robust_z(sel, "portfolio_seed_score")
    sage_score_rank = cross_sectional_robust_z(sel, "sage_composite_score")
    sage_g_rank = cross_sectional_robust_z(sel, "sage_g_score")
    sage_q_rank = cross_sectional_robust_z(sel, "sage_q_score")
    sleeve_score_rank = pd.Series(0.0, index=sel.index, dtype=float)
    sleeve_label_for_alpha = sel.get(
        "portfolio_sleeve_label",
        pd.Series("core_compounder", index=sel.index, dtype=object),
    ).fillna("core_compounder").astype(str)
    core_alpha_mask = sleeve_label_for_alpha.eq("core_compounder")
    future_alpha_mask = sleeve_label_for_alpha.eq("future_winner")
    early_alpha_mask = sleeve_label_for_alpha.eq("early_scout")
    if bool(core_alpha_mask.any()):
        sleeve_score_rank.loc[core_alpha_mask] = cross_sectional_robust_z(
            sel.loc[core_alpha_mask], "portfolio_core_compounder_engine_score"
        ).reindex(sel.index).fillna(0.0).loc[core_alpha_mask]
    if bool(future_alpha_mask.any()):
        sleeve_score_rank.loc[future_alpha_mask] = cross_sectional_robust_z(
            sel.loc[future_alpha_mask], "portfolio_future_winner_engine_score"
        ).reindex(sel.index).fillna(0.0).loc[future_alpha_mask]
    if bool(early_alpha_mask.any()):
        sleeve_score_rank.loc[early_alpha_mask] = cross_sectional_robust_z(
            sel.loc[early_alpha_mask], "portfolio_early_scout_engine_score"
        ).reindex(sel.index).fillna(0.0).loc[early_alpha_mask]
    turnover_cost = pd.Series(np.zeros(len(sel)), index=sel.index, dtype=float)
    if prev_w:
        turnover_cost = (~sel["ticker"].isin(prev_w.keys())).astype(float)

    confirmation = numeric_series_or_default(sel, "selection_confirmation_score", 0.0).clip(lower=0.0, upper=1.0)
    fundamental_confirmation = numeric_series_or_default(sel, "selection_fundamental_confirmation_score", 0.0).clip(lower=0.0, upper=1.0)
    market_confirmation = numeric_series_or_default(sel, "selection_market_confirmation_score", 0.0).clip(lower=0.0, upper=1.0)
    sel["portfolio_focus_boost"] = 0.0
    sel["portfolio_confirmation_boost"] = 0.0
    sel["portfolio_fundamental_boost"] = 0.0
    sel["portfolio_garp_boost"] = 0.0
    sel["portfolio_anticipatory_boost"] = 0.0
    sel["portfolio_strategy_boost"] = 0.0
    sel["portfolio_future_winner_boost"] = 0.0
    sel["portfolio_existing_hold_bonus"] = numeric_series_or_default(sel, "portfolio_hold_policy_bonus", 0.0)
    sel["portfolio_benchmark_alpha_boost"] = 0.0
    sel["portfolio_regime_rotation_boost"] = 0.0
    sel["portfolio_midterm_boost"] = 0.0
    sel["portfolio_growth_penalty"] = 0.0
    sleeve_offense_boost = pd.Series(0.0, index=sel.index, dtype=float)
    sleeve_offense_boost.loc[core_alpha_mask] = (
        0.06 * sage_q_rank.loc[core_alpha_mask]
        + 0.04 * sage_score_rank.loc[core_alpha_mask]
    )
    sleeve_offense_boost.loc[future_alpha_mask] = (
        0.12 * sage_score_rank.loc[future_alpha_mask]
        + 0.08 * sage_g_rank.loc[future_alpha_mask]
    )
    sleeve_offense_boost.loc[early_alpha_mask] = (
        0.18 * sage_score_rank.loc[early_alpha_mask]
        + 0.10 * sage_g_rank.loc[early_alpha_mask]
    )
    sel["portfolio_alpha"] = (
        0.42 * utility_score.fillna(0.0)
        + 0.28 * seed_score_rank.fillna(0.0)
        + 0.20 * sleeve_score_rank.fillna(0.0)
        + 0.10 * sage_score_rank.fillna(0.0)
    )
    sel["portfolio_sage_boost"] = sleeve_offense_boost
    sel["portfolio_risk_cost"] = 0.0
    sel["portfolio_event_stress_cost"] = 0.0
    sel["portfolio_turnover_cost"] = 0.0
    sel["portfolio_liquidity_reward"] = 0.0
    # conviction hold utility bonus for names that are winning + held
    conviction_util_bonus = numeric_series_or_default(sel, "conviction_hold_bonus", 0.0)
    conviction_util_bonus = (conviction_util_bonus > 0).astype(float) * float(cfg.conviction_hold_utility_bonus)
    sel["portfolio_conviction_hold_bonus"] = conviction_util_bonus
    sel["portfolio_utility"] = (
        sel["portfolio_alpha"]
        + sel["portfolio_sage_boost"]
        + conviction_util_bonus
        + 0.08 * confirmation
        + sel["portfolio_existing_hold_bonus"]
    )

    score_component = pd.to_numeric(sel["portfolio_utility"], errors="coerce").fillna(0.0)
    score_component = score_component - float(np.nanmedian(score_component.values))
    raw_w = np.exp(np.clip(score_component.values, -6.0, 6.0))
    raw_w = pd.Series(raw_w, index=sel.index, dtype=float)
    if cfg.weight_score_power > 0:
        raw_w = np.power(raw_w, max(cfg.weight_score_power, 0.0))
    # ---- winner scaling: boost top-quartile performers, cut bottom-quartile ----
    if prev_w:
        held_prev_w = sel["ticker"].astype(str).map(prev_w).fillna(0.0).astype(float)
        held_mask_ws = held_prev_w > 0.005
        if held_mask_ws.sum() >= 4:
            held_scores = sel.loc[held_mask_ws, "portfolio_seed_score"]
            q75 = float(held_scores.quantile(0.75))
            q25 = float(held_scores.quantile(0.25))
            top_q_mask = held_mask_ws & (sel["portfolio_seed_score"] >= q75)
            bot_q_mask = held_mask_ws & (sel["portfolio_seed_score"] <= q25)
            raw_w.loc[top_q_mask] = raw_w.loc[top_q_mask] * float(cfg.winner_scale_top_quartile_boost)
            raw_w.loc[bot_q_mask] = raw_w.loc[bot_q_mask] * float(cfg.winner_scale_bottom_quartile_cut)
            raw_w = raw_w / raw_w.sum()
    conviction_conf = np.maximum(fundamental_confirmation, 0.85 * market_confirmation)
    join_status = sel.get("fund_join_status", pd.Series("", index=sel.index, dtype=str)).astype(str)
    inv_vol = 1.0 / pd.to_numeric(sel["vol_252d"], errors="coerce").replace(0, np.nan)
    inv_vol = inv_vol.fillna(inv_vol.median() if inv_vol.notna().any() else 1.0)
    sleeve_vol_scale = pd.Series(1.0, index=sel.index, dtype=float)
    sleeve_vol_scale.loc[future_alpha_mask] = 0.55
    sleeve_vol_scale.loc[early_alpha_mask] = 0.25
    vol_component = np.power(inv_vol, max(cfg.weight_invvol_power, 0.0) * sleeve_vol_scale)
    raw_w = raw_w * vol_component
    if not np.isfinite(raw_w).all() or raw_w.sum() <= 0:
        raw_w = inv_vol.copy()
    raw_w = raw_w / raw_w.sum()

    weight_cap = min(resolve_dynamic_weight_cap(cfg, sel), regime_ctl["single_name_cap"])
    name_caps = pd.Series(float(weight_cap), index=sel.index, dtype=float)
    no_ttm_mask = join_status.eq("matched_no_ttm")
    fundamental_lane = sel.get("fundamental_lane_label", pd.Series("full_ttm", index=sel.index, dtype=str)).astype(str)
    no_ttm_caps = np.where(
        conviction_conf >= 0.75,
        float(cfg.stock_weight_max_no_ttm_confirmed),
        float(cfg.stock_weight_max_no_ttm),
    )
    name_caps.loc[no_ttm_mask] = np.minimum(name_caps.loc[no_ttm_mask], no_ttm_caps[no_ttm_mask.to_numpy()])
    sector_adjusted_mask = fundamental_lane.eq("sector_adjusted")
    partial_scout_mask = fundamental_lane.eq("partial_scout")
    if sector_adjusted_mask.any():
        name_caps.loc[sector_adjusted_mask] = np.minimum(
            name_caps.loc[sector_adjusted_mask],
            float(cfg.stock_weight_max_sector_adjusted),
        )
    if partial_scout_mask.any():
        name_caps.loc[partial_scout_mask] = np.minimum(
            name_caps.loc[partial_scout_mask],
            float(cfg.stock_weight_max_partial_scout),
        )
    name_caps = apply_sleeve_entry_drift_name_caps(cfg, sel, name_caps, prev_w=prev_w)
    sel["portfolio_prev_weight"] = (
        sel.get("ticker", pd.Series("", index=sel.index, dtype=object))
        .astype(str)
        .map({str(k): float(v) for k, v in (prev_w or {}).items() if pd.notna(v)})
        .fillna(0.0)
    )
    sel["portfolio_existing_holding"] = (pd.to_numeric(sel["portfolio_prev_weight"], errors="coerce").fillna(0.0) > 1e-8).astype(float)
    sel["portfolio_name_cap"] = pd.to_numeric(name_caps, errors="coerce").fillna(float(weight_cap))
    weight_floor = min(cfg.stock_weight_min, 1.0 / max(len(sel), 1))
    sel["weight"] = normalize_with_limits(raw_w, weight_floor, name_caps)
    sel = apply_sector_weight_caps(sel, caps, cfg.cap_base_weight, single_name_cap=name_caps)
    sleeve_targets = {
        "core_compounder": float(sleeve_policy.get("core_compounder_target", 0.0)),
        "future_winner": float(sleeve_policy.get("future_winner_target", 0.0)),
        "early_scout": float(sleeve_policy.get("early_scout_target", 0.0)),
    }
    if "portfolio_sleeve_label" not in sel.columns:
        sel["portfolio_sleeve_label"] = "core_compounder"
    sel["portfolio_sleeve_label"] = sel["portfolio_sleeve_label"].fillna("core_compounder").astype(str)
    sleeve_counts = sel["portfolio_sleeve_label"].value_counts().to_dict()
    sleeve_totals = sel.groupby("portfolio_sleeve_label")["weight"].sum().to_dict()
    if sleeve_totals:
        actual_early_n = int(sleeve_counts.get("early_scout", 0))
        if early_target_n > 0 and actual_early_n < early_target_n:
            early_shortfall_share = float(sleeve_targets.get("early_scout", 0.0)) * float(
                max(early_target_n - actual_early_n, 0)
            ) / float(max(early_target_n, 1))
            sleeve_targets["early_scout"] = max(0.0, float(sleeve_targets.get("early_scout", 0.0)) - early_shortfall_share)
            sleeve_targets["future_winner"] = float(sleeve_targets.get("future_winner", 0.0)) + early_shortfall_share
        if sleeve_totals.get("early_scout", 0.0) <= 1e-10:
            sleeve_targets["future_winner"] += sleeve_targets.get("early_scout", 0.0)
            sleeve_targets["early_scout"] = 0.0
        if sleeve_totals.get("future_winner", 0.0) <= 1e-10:
            sleeve_targets["core_compounder"] += sleeve_targets.get("future_winner", 0.0)
            sleeve_targets["future_winner"] = 0.0
        if sleeve_totals.get("core_compounder", 0.0) <= 1e-10:
            sleeve_targets["future_winner"] += sleeve_targets.get("core_compounder", 0.0) + sleeve_targets.get("early_scout", 0.0)
            sleeve_targets["core_compounder"] = 0.0
            sleeve_targets["early_scout"] = 0.0
        sel["_sleeve_factor"] = 1.0
        for sleeve_label, target_share in sleeve_targets.items():
            current_share = float(sleeve_totals.get(sleeve_label, 0.0))
            if current_share > 1e-10 and target_share >= 0.0:
                sel.loc[sel["portfolio_sleeve_label"].eq(sleeve_label), "_sleeve_factor"] = float(target_share / current_share)
        sel["weight"] = pd.to_numeric(sel["weight"], errors="coerce").fillna(0.0) * pd.to_numeric(
            sel["_sleeve_factor"], errors="coerce"
        ).fillna(1.0)
        sel = sel.drop(columns="_sleeve_factor", errors="ignore")
        # Sleeve rescaling can push a leader back above the name cap. Re-run the
        # hard name/sector caps after the sleeve target pass; sleeve targets are
        # desired tilts, while name caps are hard risk controls.
        sel["weight"] = normalize_with_limits(sel["weight"], weight_floor, name_caps)
        sel = apply_sector_weight_caps(sel, caps, cfg.cap_base_weight, single_name_cap=name_caps)

    target_w = dict_from_weights(sel)
    target_w = apply_cash_buffer_to_weights(
        target_w,
        sleeve_policy.get("cash_target", regime_ctl.get("cash_target", 0.0)),
    )
    partial_scout_total_cap = float(getattr(cfg, "partial_scout_total_weight_cap", 0.0))
    if partial_scout_total_cap > 0:
        partial_tickers = sel.loc[partial_scout_mask, "ticker"].astype(str).tolist()
        partial_total = float(sum(float(target_w.get(t, 0.0)) for t in partial_tickers))
        if partial_total > partial_scout_total_cap + 1e-10:
            scale = partial_scout_total_cap / partial_total
            released = 0.0
            for t in partial_tickers:
                old_w = float(target_w.get(t, 0.0))
                new_w = old_w * scale
                target_w[t] = new_w
                released += old_w - new_w
            if released > 0:
                target_w[CASH_PROXY_TICKER] = float(target_w.get(CASH_PROXY_TICKER, 0.0) + released)
    # Speculative sleeve: identify and cap speculative positions
    spec_max = float(cfg.speculative_weight_max)
    future_sleeve_tickers = set(
        sel.loc[sel["portfolio_sleeve_label"].astype(str).eq("future_winner"), "ticker"].astype(str).tolist()
    ) if "portfolio_sleeve_label" in sel.columns else set()
    spec_total_max = max(
        float(cfg.speculative_total_weight_max),
        float(sleeve_policy.get("early_scout_target", 0.0)),
    )
    if spec_total_max > 0:
        scout_score = numeric_series_or_default(sel, "future_winner_scout_score", 0.0)
        scout_thr = scout_score.quantile(0.80) if len(scout_score) > 10 else scout_score.median()
        archetype_lbl = sel.get("dominant_archetype_label", pd.Series("", index=sel.index, dtype=str)).astype(str)
        sleeve_lbl = sel.get("portfolio_sleeve_label", pd.Series("", index=sel.index, dtype=str)).astype(str)
        speculative_mask = (
            (sleeve_lbl.eq("early_scout") | partial_scout_mask | (archetype_lbl == "emerging_growth"))
            & (scout_score >= scout_thr)
        )
        sel["_is_speculative"] = speculative_mask.astype(float)
        spec_tickers = sel.loc[speculative_mask, "ticker"].astype(str).tolist()
        # Cap individual speculative positions
        for t in spec_tickers:
            if t in future_sleeve_tickers:
                continue
            if t in target_w and float(target_w[t]) > spec_max:
                excess = float(target_w[t]) - spec_max
                target_w[t] = spec_max
                target_w[CASH_PROXY_TICKER] = float(target_w.get(CASH_PROXY_TICKER, 0.0)) + excess
        # Cap total speculative sleeve
        capped_spec_tickers = [t for t in spec_tickers if t not in future_sleeve_tickers]
        spec_total = float(sum(float(target_w.get(t, 0.0)) for t in capped_spec_tickers))
        if spec_total > spec_total_max + 1e-10:
            scale = spec_total_max / spec_total
            released = 0.0
            for t in capped_spec_tickers:
                old_w = float(target_w.get(t, 0.0))
                new_w = old_w * scale
                target_w[t] = new_w
                released += old_w - new_w
            if released > 0:
                target_w[CASH_PROXY_TICKER] = float(target_w.get(CASH_PROXY_TICKER, 0.0)) + released
    final_w = target_w.copy()
    if apply_turnover and prev_w is not None:
        final_w = cap_turnover(prev_w, target_w, cfg.turnover_cap_monthly)
        final_w = accelerate_cash_deployment(
            final_w,
            target_w,
            cfg,
            sleeve_policy.get("cash_target", regime_ctl.get("cash_target", 0.0)),
        )
        final_w = {
            str(k): float(v)
            for k, v in final_w.items()
            if pd.notna(v) and float(v) > 1e-6
        }
        total_final = float(sum(final_w.values()))
        if total_final > 0 and abs(total_final - 1.0) > 1e-8:
            final_w = {k: float(v / total_final) for k, v in final_w.items()}

    final_df = materialize_weight_frame(month_df, final_w)
    if not final_df.empty and not sel.empty and "ticker" in final_df.columns and "ticker" in sel.columns:
        sleeve_cols = [
            "ticker",
            "portfolio_sleeve_label",
            "portfolio_sleeve_label_raw",
            "portfolio_sleeve_confidence",
            "portfolio_sleeve_promotion_signal",
            "portfolio_sleeve_promoted",
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
            "data_history_quality_label",
            "forward_return_coverage_score",
            "portfolio_core_compounder_engine_score",
            "portfolio_future_winner_engine_score",
            "portfolio_early_scout_engine_score",
            "portfolio_prev_weight",
            "portfolio_existing_holding",
            "portfolio_name_cap",
        ]
        final_df = final_df.merge(sel[[c for c in sleeve_cols if c in sel.columns]].drop_duplicates("ticker"), on="ticker", how="left")
    if not final_df.empty:
        final_df["sleeve_target_core_compounder_weight"] = float(sleeve_policy.get("core_compounder_target", 0.0))
        final_df["sleeve_target_future_winner_weight"] = float(sleeve_policy.get("future_winner_target", 0.0))
        final_df["sleeve_target_early_scout_weight"] = float(sleeve_policy.get("early_scout_target", 0.0))
        final_df["sleeve_invested_share"] = float(sleeve_policy.get("invested_share", 0.0))
        final_df["sleeve_growth_signal"] = float(sleeve_policy.get("growth_signal", 0.0))
        final_df["sleeve_risk_signal"] = float(sleeve_policy.get("risk_signal", 0.0))
        final_df["future_winner_regime_strength"] = float(
            sleeve_policy.get("future_winner_regime_strength", 0.0)
        )
        final_df["early_scout_regime_strength"] = float(
            sleeve_policy.get("early_scout_regime_strength", 0.0)
        )
        final_df["early_scout_candidate_share"] = float(sleeve_policy.get("early_scout_candidate_share", 0.0))
        final_df["applied_regime_sleeve_policy_label"] = str(
            sleeve_policy.get("applied_regime_sleeve_policy_label", "")
        )
        final_df["applied_regime_sleeve_live_label"] = str(
            sleeve_policy.get("applied_regime_sleeve_live_label", "")
        )
        final_df["applied_regime_sleeve_source_label"] = str(
            sleeve_policy.get("applied_regime_sleeve_source_label", "")
        )
    final_df = final_df.sort_values("weight", ascending=False).reset_index(drop=True) if not final_df.empty else final_df
    stock_selected_n = int((final_df.get("ticker", pd.Series(dtype=object)).astype(str).str.upper() != CASH_PROXY_TICKER).sum()) if not final_df.empty else 0
    meta = {
        "target_n": int(target_n),
        "selected_n": stock_selected_n,
        "weight_cap": float(name_caps.max()) if len(name_caps) else float(weight_cap),
        "cash_target": float(sleeve_policy.get("cash_target", regime_ctl.get("cash_target", 0.0))),
        "sector_caps": caps,
        "regime_controls": regime_ctl,
        "sleeve_policy": sleeve_policy,
        "regime_conditioned_sleeve_policy": regime_sleeve_meta,
        "sleeve_target_weights": {str(k): float(v) for k, v in sleeve_targets.items()},
        "sleeve_selected_counts": {
            str(k): int(v)
            for k, v in sel.get("portfolio_sleeve_label", pd.Series(dtype=object)).astype(str).value_counts().items()
        },
        "lane_counts": {str(k): int(v) for k, v in fundamental_lane.value_counts().items()},
        "avg_portfolio_utility": float(sel["portfolio_utility"].mean()) if "portfolio_utility" in sel.columns else np.nan,
    }
    return final_df, final_w, meta


def normalize_with_limits(
    weights: pd.Series,
    wmin: float,
    wmax: float | pd.Series,
    max_iter: int = 30,
) -> pd.Series:
    w = weights.copy().fillna(0.0)
    if w.sum() <= 0:
        return w
    w = w / w.sum()
    if isinstance(wmax, pd.Series):
        cap = pd.to_numeric(wmax.reindex(w.index), errors="coerce").fillna(float(pd.to_numeric(wmax, errors="coerce").max()))
    else:
        cap = pd.Series(float(wmax), index=w.index, dtype=float)
    cap = cap.clip(lower=wmin, upper=1.0)
    w = np.minimum(w, cap)
    w = pd.Series(w, index=cap.index, dtype=float).clip(lower=0.0)
    for _ in range(max_iter):
        s = float(w.sum())
        if abs(s - 1.0) < 1e-8:
            break
        if s > 1.0:
            slack = (w - wmin).clip(lower=0.0)
            slack_sum = float(slack.sum())
            if slack_sum <= 1e-12:
                break
            reduction = min(s - 1.0, slack_sum) * (slack / slack_sum)
            w = w - reduction
        else:
            headroom = (cap - w).clip(lower=0.0)
            headroom_sum = float(headroom.sum())
            if headroom_sum <= 1e-12:
                break
            addition = min(1.0 - s, headroom_sum) * (headroom / headroom_sum)
            w = w + addition
        w = np.minimum(w.clip(lower=wmin), cap)
        w = pd.Series(w, index=cap.index, dtype=float).clip(lower=0.0)
    final_sum = float(w.sum())
    if final_sum > 0 and abs(final_sum - 1.0) < 1e-6:
        w = w / final_sum
    return w


def apply_sector_weight_caps(
    weights_df: pd.DataFrame,
    caps: dict[str, float],
    base_cap: float,
    single_name_cap: float | pd.Series = 0.07,
) -> pd.DataFrame:
    d = weights_df.copy()
    if d.empty:
        return d
    d["weight"] = d["weight"].fillna(0.0)
    if isinstance(single_name_cap, pd.Series):
        d["_name_cap"] = pd.to_numeric(single_name_cap.reindex(d.index), errors="coerce").fillna(
            float(pd.to_numeric(single_name_cap, errors="coerce").max())
        )
    else:
        d["_name_cap"] = float(single_name_cap)
    d["_name_cap"] = d["_name_cap"].clip(lower=0.0, upper=1.0)
    for _ in range(20):
        sec_sum = d.groupby("sector")["weight"].sum()
        overflow = {}
        for sec, v in sec_sum.items():
            cap = caps.get(sec, base_cap)
            if v > cap + 1e-10:
                overflow[sec] = v - cap
        if not overflow:
            break
        for sec in overflow.keys():
            mask = d["sector"] == sec
            d.loc[mask, "weight"] *= (caps.get(sec, base_cap) / d.loc[mask, "weight"].sum())
        free = []
        for i, r in d.iterrows():
            sec_cap = caps.get(r["sector"], base_cap)
            sec_cur = d.loc[d["sector"] == r["sector"], "weight"].sum()
            if sec_cur < sec_cap - 1e-10 and r["weight"] < float(r["_name_cap"]) - 1e-10:
                free.append(i)
        if not free:
            break
        rem = 1.0 - d["weight"].sum()
        if rem <= 1e-10:
            break
        base = d.loc[free, "weight"].clip(lower=1e-8)
        d.loc[free, "weight"] += rem * (base / base.sum())
    d["weight"] = np.minimum(d["weight"].clip(lower=0.0), d["_name_cap"])
    for _ in range(40):
        sec_sum = d.groupby("sector")["weight"].transform("sum")
        sec_cap = d["sector"].map(lambda s: caps.get(s, base_cap)).astype(float)
        overflow = sec_sum - sec_cap
        if float(np.nanmax(overflow.values)) > 1e-10:
            for sec in d["sector"].dropna().unique().tolist():
                mask = d["sector"] == sec
                cap = float(caps.get(sec, base_cap))
                cur = float(d.loc[mask, "weight"].sum())
                if cur > cap + 1e-10 and cur > 0:
                    d.loc[mask, "weight"] *= cap / cur
            d["weight"] = np.minimum(d["weight"].clip(lower=0.0), d["_name_cap"])
        total = float(d["weight"].sum())
        if abs(total - 1.0) < 1e-8:
            break
        if total > 1.0:
            positive = d["weight"] > 0
            if int(positive.sum()) == 0:
                break
            d.loc[positive, "weight"] *= 1.0 / total
            d["weight"] = np.minimum(d["weight"].clip(lower=0.0), d["_name_cap"])
            continue
        rem = 1.0 - total
        sec_sum = d.groupby("sector")["weight"].transform("sum")
        sec_cap = d["sector"].map(lambda s: caps.get(s, base_cap)).astype(float)
        name_headroom = (d["_name_cap"] - d["weight"]).clip(lower=0.0)
        sec_headroom = (sec_cap - sec_sum).clip(lower=0.0)
        eligible = (name_headroom > 1e-12) & (sec_headroom > 1e-12)
        if int(eligible.sum()) == 0:
            break
        sector_slots = eligible.groupby(d["sector"]).transform("sum").replace(0, np.nan)
        row_sector_headroom = (sec_headroom / sector_slots).replace([np.inf, -np.inf], np.nan).fillna(0.0)
        row_capacity = np.minimum(name_headroom, row_sector_headroom)
        cap_sum = float(row_capacity[eligible].sum())
        if cap_sum <= 1e-12:
            break
        addition = min(rem, cap_sum) * (row_capacity / cap_sum)
        d["weight"] += addition.fillna(0.0)
        d["weight"] = np.minimum(d["weight"].clip(lower=0.0), d["_name_cap"])
    total = float(d["weight"].sum())
    if total > 0 and abs(total - 1.0) < 1e-6:
        d["weight"] /= total
    return d.drop(columns="_name_cap", errors="ignore")


def dict_from_weights(df: pd.DataFrame) -> dict[str, float]:
    return {r.ticker: float(r.weight) for r in df[["ticker", "weight"]].itertuples(index=False)}


def apply_cash_buffer_to_weights(weights: dict[str, float], cash_target: float) -> dict[str, float]:
    cash_target = float(np.clip(safe_float(cash_target), 0.0, 1.0))
    stock_weights = {
        str(k): float(v)
        for k, v in weights.items()
        if str(k).upper() != CASH_PROXY_TICKER and pd.notna(v) and float(v) > 0
    }
    stock_total = float(sum(stock_weights.values()))
    if stock_total <= 0:
        return {CASH_PROXY_TICKER: 1.0} if cash_target > 0 else {}
    residual_cash = max(0.0, 1.0 - stock_total)
    desired_cash = max(cash_target, residual_cash)
    invested_share = max(0.0, 1.0 - desired_cash)
    if stock_total > invested_share + 1e-10:
        scale = invested_share / stock_total
        out = {k: scale * v for k, v in stock_weights.items()}
    else:
        out = stock_weights.copy()
    realized_cash = max(0.0, 1.0 - float(sum(out.values())))
    if realized_cash > 1e-10:
        out[CASH_PROXY_TICKER] = realized_cash
    total = float(sum(out.values()))
    if total > 0 and abs(total - 1.0) > 1e-8:
        out = {k: float(v / total) for k, v in out.items()}
    return out


def drift_weights_by_period_returns(
    weights: dict[str, float],
    period_returns: dict[str, float],
) -> dict[str, float]:
    if not weights:
        return {}
    grown: dict[str, float] = {}
    for ticker, weight in weights.items():
        base_weight = float(weight)
        if not np.isfinite(base_weight) or base_weight <= 1e-10:
            continue
        ticker_norm = str(ticker).upper()
        if ticker_norm == CASH_PROXY_TICKER:
            gross = 1.0
        else:
            period_ret = safe_float(period_returns.get(str(ticker), 0.0))
            if not np.isfinite(period_ret):
                period_ret = 0.0
            gross = max(0.0, 1.0 + float(period_ret))
        grown[str(ticker)] = base_weight * gross
    total = float(sum(grown.values()))
    if total <= 1e-10:
        return {}
    return {str(k): float(v / total) for k, v in grown.items() if float(v) > 1e-10}


def turnover(prev_w: dict[str, float], new_w: dict[str, float]) -> float:
    keys = set(prev_w.keys()) | set(new_w.keys())
    return 0.5 * float(sum(abs(new_w.get(k, 0.0) - prev_w.get(k, 0.0)) for k in keys))


def cap_turnover(prev_w: dict[str, float], target_w: dict[str, float], cap: float) -> dict[str, float]:
    t = turnover(prev_w, target_w)
    if t <= cap or t == 0:
        return target_w
    alpha = cap / t
    keys = set(prev_w.keys()) | set(target_w.keys())
    out = {k: prev_w.get(k, 0.0) + alpha * (target_w.get(k, 0.0) - prev_w.get(k, 0.0)) for k in keys}
    s = sum(out.values())
    if s > 0:
        out = {k: v / s for k, v in out.items()}
    return out


def accelerate_cash_deployment(
    final_w: dict[str, float],
    target_w: dict[str, float],
    cfg: EngineConfig,
    cash_target: float,
) -> dict[str, float]:
    out = {
        str(k): float(v)
        for k, v in final_w.items()
        if pd.notna(v) and float(v) > 1e-10
    }
    max_release = float(np.clip(getattr(cfg, "cash_release_max_per_rebalance", 0.0), 0.0, 1.0))
    if max_release <= 0:
        return out

    final_cash = float(out.get(CASH_PROXY_TICKER, 0.0))
    target_cash = max(
        float(np.clip(safe_float(cash_target), 0.0, 1.0)),
        float(np.clip(safe_float(target_w.get(CASH_PROXY_TICKER, 0.0)), 0.0, 1.0)),
    )
    excess_cash = final_cash - target_cash
    if excess_cash <= 1e-8 or target_cash > 0.08:
        return out

    headroom = {}
    for ticker, target_weight in target_w.items():
        ticker_norm = str(ticker).upper()
        if ticker_norm == CASH_PROXY_TICKER:
            continue
        current_weight = float(out.get(ticker, 0.0))
        gap = float(target_weight) - current_weight
        if gap > 1e-10:
            headroom[ticker] = gap
    total_headroom = float(sum(headroom.values()))
    if total_headroom <= 1e-10:
        return out

    release = min(excess_cash, max_release, total_headroom)
    if release <= 1e-10:
        return out

    for ticker, gap in headroom.items():
        add = release * (gap / total_headroom)
        out[ticker] = float(out.get(ticker, 0.0)) + add
    out[CASH_PROXY_TICKER] = max(0.0, final_cash - release)

    total = float(sum(out.values()))
    if total > 0 and abs(total - 1.0) > 1e-8:
        out = {k: float(v / total) for k, v in out.items()}
    return out


def resolve_regime_conditioned_sleeve_override(
    cfg: dict | EngineConfig,
    month_df: Optional[pd.DataFrame],
) -> tuple[Optional[dict[str, float]], dict[str, Any]]:
    # Late imports to avoid signals -> pipeline circular import.
    # These 3 helpers live in r1000_pipeline.py (regime policy orchestration layer).
    from r1000_pipeline import (
        apply_regime_policy_guardrails,
        resolve_frame_regime_label,
        resolve_regime_policy_selection,
    )
    cfg_obj = to_cfg(cfg)
    if not bool(getattr(cfg_obj, "sleeve_regime_apply_champion", True)):
        return None, {}
    raw_map = dict(getattr(cfg_obj, "regime_conditioned_sleeve_map", {}) or {})
    manual_map = dict(getattr(cfg_obj, "manual_regime_conditioned_sleeve_map", {}) or default_manual_regime_conditioned_sleeve_map())
    if not raw_map and not manual_map:
        return None, {}
    live_label = resolve_frame_regime_label(month_df, default="balanced")
    selected, lookup_meta = resolve_regime_policy_selection(
        live_label,
        learned_regime_map=raw_map,
        manual_regime_map=manual_map,
    )
    selected, guardrail_meta = apply_regime_policy_guardrails(live_label, selected)
    if not isinstance(selected, dict):
        return None, {"live_regime_label": live_label, **lookup_meta, **guardrail_meta}
    core = max(safe_float(selected.get("core"), 0.0), 0.0)
    future = max(safe_float(selected.get("future"), 0.0), 0.0)
    early = max(safe_float(selected.get("early"), 0.0), 0.0)
    cash = float(np.clip(safe_float(selected.get("cash"), 0.0), 0.0, 1.0))
    total = core + future + early
    if total <= 1e-8:
        return None, {"live_regime_label": live_label, **lookup_meta}
    override = {
        "core": float(core / total),
        "future": float(future / total),
        "early": float(early / total),
        "cash": cash,
    }
    meta = {
        "live_regime_label": live_label,
        "selected_regime_label": str(selected.get("source_regime", live_label) or live_label),
        "policy_label": str(selected.get("policy_label", "") or ""),
        "months": int(safe_float(selected.get("months"), 0.0)),
        "cash": cash,
        "lookup_source": str(lookup_meta.get("lookup_source", "") or ""),
        "lookup_label": str(lookup_meta.get("lookup_label", "") or ""),
        "lookup_chain": lookup_meta.get("lookup_chain", []),
        "fallback_used": bool(lookup_meta.get("fallback_used", False)),
        "guardrail_applied": bool(guardrail_meta.get("guardrail_applied", False)),
        "guardrail_label": str(guardrail_meta.get("guardrail_label", "") or ""),
        "guardrail_reason": str(guardrail_meta.get("guardrail_reason", "") or ""),
    }
    return override, meta
