"""r1000 Quant Engine — pure utility helpers.

This module owns small, dependency-free utility functions extracted from
`r1000_top30_institutional.py` during Refactor Phase A Stage 2.

Stage 2a (this commit): the smallest/safest helpers — git commit SHA
resolver, phase-toggle env-var check, timestamp + log print helpers.
All stdlib-only; no numpy/pandas, no r1000_config, no r1000_top30.

Import discipline
-----------------
    r1000_config.py           (pure data, stdlib)
        ^
        |
    r1000_helpers.py          (pure helpers, stdlib + maybe numpy/pandas
                               in later sub-stages)
        ^                     ^
        |                     |
    r1000_top30_institutional.py
        ^
        |
    r1000_data_collector.py
    r1000_operator.py
    r1000_portfolio_state.py

r1000_helpers.py may import from r1000_config.py (e.g. EngineConfig for
`to_cfg`), but NEVER from the main engine or collectors. This keeps the
dependency graph acyclic.
"""
from __future__ import annotations

import os
import subprocess
from datetime import datetime
from pathlib import Path
import pandas as pd
from dataclasses import asdict
from typing import Any, Iterable, Optional
from r1000_config import EngineConfig, ROBUST_Z_CLIP, ROBUST_Z_WINSOR_P
import numpy as np


# ---------------------------------------------------------------------
# Git commit SHA provenance (Stage 2a)
# ---------------------------------------------------------------------

def _resolve_engine_commit_sha() -> str:
    """Return short git SHA of the engine repo for run provenance.

    Printed in every run banner so logs/notebooks self-identify which
    code version produced them. Falls back to '(unknown)' if git isn't
    available (e.g. engine installed as a wheel instead of a clone, or
    the git binary is missing from PATH).
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(Path(__file__).resolve().parent),
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        sha = (result.stdout or "").strip()
        return sha if sha else "(unknown)"
    except Exception:
        return "(unknown)"


# Evaluated once at import time. The main engine imports this symbol for
# run-banner prints. If pre-computing at import is undesirable (e.g. for
# test isolation), callers can invoke `_resolve_engine_commit_sha()`
# directly instead.
ENGINE_COMMIT_SHA = _resolve_engine_commit_sha()


# ---------------------------------------------------------------------
# Phase toggle dual-gate: cfg flag + PHASE_<KEY>_ENABLED env var (Stage 2a)
# ---------------------------------------------------------------------
# Every phase (1 .. 9) has a pair:
#     cfg.phaseN_*_enabled: bool  (programmatic override)
#     PHASE_PHASEN_*_ENABLED env  (runtime override, wins vs cfg)
# This function reads the env; the cfg branch is handled at call site.
#
# Usage (main engine or notebook):
#     import os
#     os.environ["PHASE_PHASE1_ALPHA_ENABLED"] = "0"       # disable Phase 1
#     os.environ["PHASE_PHASE2_INDUSTRY_ENABLED"] = "0"    # disable Phase 2
#
# Any of: "0", "false", "no", "off", "disabled" (case-insensitive) turns
# a phase OFF.  Anything else (including unset) leaves it at the default.

def phase_is_enabled(phase_key: str, default: bool = True) -> bool:
    """Check env var PHASE_{KEY}_ENABLED.  Returns `default` when unset."""
    env_name = f"PHASE_{phase_key.upper()}_ENABLED"
    raw = os.environ.get(env_name, "")
    val = str(raw).strip().lower()
    if val == "":
        return bool(default)
    if val in ("0", "false", "no", "off", "disabled"):
        return False
    if val in ("1", "true", "yes", "on", "enabled"):
        return True
    return bool(default)


# ---------------------------------------------------------------------
# Timestamp + log helpers (Stage 2a)
# ---------------------------------------------------------------------

def now_ts() -> str:
    """Return current local time as YYYYMMDD_HHMMSS (used in archive paths)."""
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def log(msg: str) -> None:
    """Stamp `msg` with [HH:MM:SS] and print to stdout.

    Intentionally simple — all engine progress logging uses this single
    function so a future switch to `logging.getLogger` is one-file.
    """
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

# ---------------------------------------------------------------------
# Config helpers (Stage 2b) — transform EngineConfig instances
# ---------------------------------------------------------------------
# All 3 functions operate on EngineConfig (from r1000_config) or dict
# form thereof. Require pandas for date arithmetic in
# configure_last_n_years_backtest.

def apply_fast_mode(cfg: "EngineConfig") -> "EngineConfig":
    """Apply runtime-reduction overrides when cfg.fast_mode is True.

    Phase 1/2 savings:
      - live fundamentals refresh limited to the highest-liquidity subset
      - slower-changing statement supplements refreshed less often
      - yfinance quarterly supplement capped to a smaller stale subset

    Phase 4 savings:
      - CatBoost iterations cut ~40%: reg 350→200, cls 350→200, rank 250→150
      - ranking_enabled disabled: ~30% faster per retrain cycle
      - retrain frequency halved: 3m→6m  (fewer training windows)

    Phase 5 savings:
      - regime-per-regime comparison disabled (-12 backtests)
      - AI four-sleeve comparison disabled (-13 backtests)
      - regime-map-method comparison disabled (-2 backtests)
      - standalone sleeve comparison disabled (-6 backtests)
      - sleeve-cap policy candidates reduced to 3 (-3 backtests vs default 6)
    Net: ~5 backtests instead of ~44.  Estimated runtime: ~1.5h vs ~8h.
    """
    if not cfg.fast_mode:
        return cfg
    # Phase 1/2 — collector I/O and supplement refresh
    cfg.live_refresh_days = max(int(cfg.live_refresh_days), 2)
    cfg.max_live_refresh_tickers = min(int(cfg.max_live_refresh_tickers), 400)
    cfg.latest_statement_repair_refresh_days = max(int(cfg.latest_statement_repair_refresh_days), 14)
    cfg.yf_quarterly_refresh_days = max(int(cfg.yf_quarterly_refresh_days), 14)
    cfg.yf_quarterly_max_tickers_per_run = min(int(cfg.yf_quarterly_max_tickers_per_run), 120)
    # Phase 4 — model complexity
    cfg.cat_reg_iterations = 200
    cfg.cat_cls_iterations = 200
    cfg.cat_rank_iterations = 150
    cfg.ranking_enabled = False
    cfg.walkforward_retrain_frequency_months = 6
    cfg.cat_validation_months = 4
    # Phase 5 — comparison suites
    cfg.run_sleeve_regime_comparison = False
    cfg.run_ai_four_sleeve_comparison = False
    cfg.run_regime_map_method_comparison = False
    cfg.run_standalone_sleeve_backtest_comparison = False
    cfg.run_concentrated_backtest_comparison = True
    # Phase 9 CE (2026-04-18): fast_mode used to strip concentrated grid to
    # [N=1,2,3] × [monthly] × [conviction_curve] = 3 backtests. Expand to the
    # CE grid so fast_mode runs still measure the full concentration ladder.
    # Cost: 7 × 3 × 3 = 63 concentrated backtests × ~6s each = ~6.3 min extra,
    # negligible next to walk-forward training time.
    cfg.concentrated_top_n_candidates = [1, 2, 3, 4, 5, 7, 10]
    cfg.concentrated_rebalance_intervals = [1, 2, 3]
    cfg.concentrated_weighting_modes = ["conviction_curve", "winner_take_all", "score_power"]
    cfg.sleeve_cap_policy_max_candidates = 3
    log("[fast_mode] ON -- lighter collector refresh + ~5 backtests, retrain every 6m; Phase 9 CE concentrated grid expanded to 63 combos.")
    return cfg

def to_cfg(cfg: Optional[dict | EngineConfig]) -> EngineConfig:
    if cfg is None:
        return EngineConfig()
    if isinstance(cfg, EngineConfig):
        return cfg
    base = EngineConfig()
    allowed = set(asdict(base).keys())
    for k, v in cfg.items():
        if k in allowed:
            setattr(base, k, v)
    if not base.alpha_vantage_api_key:
        base.alpha_vantage_api_key = os.getenv("ALPHA_VANTAGE_API_KEY", "")
    if not base.sec_user_agent or "your_email" in base.sec_user_agent:
        base.sec_user_agent = os.getenv("SEC_USER_AGENT", base.sec_user_agent)
    return base

def configure_last_n_years_backtest(
    cfg: Optional[dict | EngineConfig] = None,
    years: int = 5,
    *,
    end_date: Optional[str] = None,
    train_lookback_years: Optional[int] = None,
) -> EngineConfig:
    cfg_obj = to_cfg(cfg)
    years = int(years)
    if years < 1:
        raise ValueError("years must be >= 1")
    end_ts = pd.Timestamp(end_date or cfg_obj.end_date).normalize()
    if pd.isna(end_ts):
        raise ValueError("end_date could not be parsed")
    start_ts = (end_ts - pd.DateOffset(years=years)).normalize()
    cfg_obj.start_date = str(start_ts.date())
    cfg_obj.end_date = str(end_ts.date())
    if train_lookback_years is not None:
        cfg_obj.train_lookback_years = int(train_lookback_years)
    return cfg_obj

# ---------------------------------------------------------------------
# Stats primitives (Stage 2c) -- numpy/pandas pure-function helpers
# ---------------------------------------------------------------------
# All pure (no side effects except log() in edge cases). Heavily called
# by Phase 1-9 signal computation + sleeve composition paths.

def winsorize(s: pd.Series, p: float = 0.01) -> pd.Series:
    s = pd.to_numeric(s, errors="coerce").astype(float)
    if s.dropna().empty:
        return s
    lo, hi = s.quantile(p), s.quantile(1 - p)
    return s.clip(lo, hi)


def robust_z(s: pd.Series) -> pd.Series:
    base = winsorize(pd.to_numeric(s, errors="coerce").astype(float), ROBUST_Z_WINSOR_P)
    x = base.values
    med = np.nanmedian(x)
    mad = np.nanmedian(np.abs(x - med))
    if mad == 0 or np.isnan(mad):
        return pd.Series(np.zeros(len(s)), index=s.index)
    z = pd.Series((x - med) / (1.4826 * mad), index=s.index)
    return z.clip(lower=-ROBUST_Z_CLIP, upper=ROBUST_Z_CLIP)


def squeeze_series(x: Any) -> pd.Series:
    if isinstance(x, pd.DataFrame):
        if x.shape[1] == 0:
            return pd.Series([], dtype=float)
        return x.iloc[:, 0].copy()
    if isinstance(x, pd.Series):
        return x.copy()
    return pd.Series(x)


def hard_sanitize(df: pd.DataFrame, cols: Iterable[str], clip: float = 1e12) -> pd.DataFrame:
    d = df.copy()
    # Phase 8 review fix (2026-04-17): dedup `cols` to prevent pandas
    # `ValueError: Columns must be same length as key` when callers pass
    # overlapping lists (e.g. DEFAULT_FEATURES contains Phase 1 columns
    # which are also in PHASE1_ALPHA_COLUMNS, and similarly for Phase 8b).
    # `d[cols] = d[cols].replace(...)` requires len(cols) to match the
    # right-hand-side column count; with duplicates in `cols`, the RHS
    # returns one column per unique name, so shapes mismatch.
    # dict.fromkeys preserves order + removes duplicates in one pass.
    cols = [c for c in dict.fromkeys(cols) if c in d.columns]
    if not cols:
        return d
    d[cols] = d[cols].replace([np.inf, -np.inf], np.nan)
    for c in cols:
        d[c] = pd.to_numeric(d[c], errors="coerce").clip(-clip, clip)
    return d

def safe_float(x: Any, default: float = np.nan) -> float:
    try:
        if x is None or (isinstance(x, str) and x.strip() == ""):
            return float(default)
        return float(x)
    except Exception:
        return float(default)


LIVE_CACHE_ALPHA_PRESERVE_FIELDS = [
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
    "eps_revision_proxy",
    "eps_est_fy1",
    "rev_est_fy1",
    "eps_est_fy2",
    "rev_est_fy2",
]

def cross_sectional_robust_z(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns:
        return pd.Series(np.zeros(len(df)), index=df.index, dtype=float)
    if "rebalance_date" not in df.columns:
        return robust_z(pd.to_numeric(df[col], errors="coerce")).fillna(0.0)
    return (
        df.groupby("rebalance_date", group_keys=False)[col]
        .apply(lambda s: robust_z(pd.to_numeric(s, errors="coerce")).fillna(0.0))
        .reindex(df.index)
        .fillna(0.0)
    )


def cross_sectional_robust_z_by_sector(df: pd.DataFrame, col: str, sector_col: str = "sage_sector") -> pd.Series:
    """Sector-gated robust z-score: standardizes col within each (rebalance_date, sage_sector) group.
    Falls back to universe-wide cross_sectional_robust_z when sage_sector is absent or a group is too small."""
    if col not in df.columns:
        return pd.Series(np.zeros(len(df)), index=df.index, dtype=float)
    if sector_col not in df.columns or "rebalance_date" not in df.columns:
        return cross_sectional_robust_z(df, col)
    result = pd.Series(np.nan, index=df.index, dtype=float)
    for (rd, sc), grp in df.groupby(["rebalance_date", sector_col], group_keys=False):
        vals = pd.to_numeric(grp[col], errors="coerce")
        if vals.notna().sum() >= 5:
            result.loc[grp.index] = robust_z(vals).fillna(0.0)
        else:
            result.loc[grp.index] = 0.0
    # Fill any gaps with universe-wide z-score
    gap_mask = result.isna()
    if gap_mask.any():
        result.loc[gap_mask] = cross_sectional_robust_z(df, col).loc[gap_mask]
    return result.fillna(0.0)

def numeric_series_or_default(df: pd.DataFrame, col: str, default: float = 0.0) -> pd.Series:
    if col not in df.columns:
        return pd.Series(np.full(len(df), default), index=df.index, dtype=float)
    raw = df[col]
    if isinstance(raw, pd.DataFrame):
        # Duplicate column names can appear after merges; keep the first non-null value per row.
        raw = raw.bfill(axis=1).iloc[:, 0]
    out = pd.to_numeric(raw, errors="coerce")
    if not isinstance(out, pd.Series):
        out = pd.Series(out, index=df.index, dtype=float)
    return out.reindex(df.index).fillna(default)

def rolling_robust_z(s: pd.Series, window: int = 63) -> pd.Series:
    """Rolling robust z-score (median / MAD).

    Post-2026-04-17 hardening (see DIAGNOSIS_BUGS.md): the previous
    implementation only replaced `mad == 0` with NaN, leaving very small
    MAD values (e.g. 1e-10) to produce z-scores like 1e14 when the
    rolling window happened to have near-constant values followed by a
    jump. This was the root cause of the 2024-06 macro corruption that
    propagated `labor_softening_score = -2e14` to all 600 stock-level
    scores via `compute_macro_regime_features`.

    Fix:
    - Floor MAD at `max(|median| * 0.01, 1e-6)` so the denominator can
      never collapse below a scale-aware floor.
    - Clip the final z-score to [-10, 10]. Any legitimate rolling z-score
      beyond +-10 standard-MADs is almost certainly a data artefact;
      clipping here is cheaper than relying on downstream hard_sanitize.
    """
    x = pd.to_numeric(s, errors="coerce").astype(float)
    min_periods = max(12, window // 3)
    med = x.rolling(window, min_periods=min_periods).median()
    mad = (x - med).abs().rolling(window, min_periods=min_periods).median()
    # Scale-aware MAD floor: prevents near-zero-denominator blow-ups.
    abs_med = med.abs().fillna(0.0)
    mad_floor = np.maximum(abs_med * 0.01, 1e-6)
    mad_safe = np.maximum(mad.fillna(0.0), mad_floor)
    z = (x - med) / (1.4826 * mad_safe)
    z = z.replace([np.inf, -np.inf], np.nan)
    return z.clip(lower=-10.0, upper=10.0)


def row_mean(parts: list[pd.Series], index: pd.Index) -> pd.Series:
    clean = [pd.to_numeric(p, errors="coerce").reindex(index) for p in parts if p is not None]
    if not clean:
        return pd.Series(np.nan, index=index, dtype=float)
    return pd.concat(clean, axis=1).mean(axis=1)

def weighted_sleeve_composite(
    weight_pairs: list[tuple[float, pd.Series]],
    index: pd.Index,
    *,
    renorm_enabled: bool = False,
    l1_target: float = 0.0,
) -> pd.Series:
    """Compute a sleeve composite score from (weight, z-score-series) pairs.

    renorm_enabled=False (default) -> equivalent to
        row_mean([w * s for w, s in pairs])
    This matches the legacy pre-Phase-3 behaviour exactly, so flipping the
    toggle off yields byte-identical sleeve scores.

    renorm_enabled=True -> per-row weighted average
        sum_valid(w_i * s_i) / L1_valid
    where L1_valid is either `l1_target` when positive, or the sum of
    |w_i| over the terms that are non-NaN on that specific row. Rows
    with a NaN z-score for term i have both the numerator contribution
    AND the denominator contribution skipped, matching `row_mean`'s
    NaN-skipping semantics so the A/B measurement isolates the
    "weighted-vs-equal" effect from NaN handling differences.

    L1 semantics with negative weights (penalties):
        Dividing by sum(|w|) rather than sum(w) is intentional. Phase 3's
        stated goal is that each factor's contribution stays proportional
        to its own |w_i| / L1. A negative weight (penalty) still consumes
        |w_i| of the L1 budget and contributes proportionally to the
        numerator with the correct sign. Using sum(w) would shrink the
        denominator when penalties are large, which paradoxically
        strengthens the penalty's relative impact — the opposite of what
        the "magnitude-preserving weighted average" semantics want.

    Notes on downstream compatibility:
        The renorm path typically produces a composite whose magnitude is
        ~N/L1 times the legacy row_mean magnitude. For the sleeve tables
        built in `compute_portfolio_sleeve_columns` this ratio is
        ~2x. Downstream `winsorize(..).clip(-6,6)` handles this, but any
        post-processing additive penalty (e.g. `sparse_history_penalty`)
        calibrated to the legacy magnitude should be scaled by the same
        ratio to keep its relative strength constant — see the
        `compute_portfolio_sleeve_columns` penalty block for the
        Phase-3-aware scaling.
    """
    if not weight_pairs:
        return pd.Series(0.0, index=index, dtype=float)
    weighted_terms: list[pd.Series] = []
    abs_weights: list[float] = []
    for w, s in weight_pairs:
        if s is None:
            continue
        # Phase 8 review fix (2026-04-17): skip weight-0 pairs to prevent
        # row_mean denominator dilution. `row_mean` computes
        # `sum / count_of_non_NaN`, so `0.0 * non_NaN_z_score = 0.0`
        # would count as a valid term and silently dilute every other
        # factor's effective weight by ~1/N. Phase 8a.1 (negative-IC
        # drop), 8a.4 (hold-persistence when inactive), 8b.1 (multi-year
        # when inactive), 8c (when inactive) all set weight to 0 to mean
        # "drop this factor" — without this guard they'd be producing
        # the opposite effect. Threshold 1e-10 catches exact zeros but
        # preserves intentionally-small weights like 0.05.
        if abs(float(w)) < 1e-10:
            continue
        weighted_terms.append(float(w) * s)
        abs_weights.append(abs(float(w)))
    if not weighted_terms:
        return pd.Series(0.0, index=index, dtype=float)
    if not renorm_enabled:
        return row_mean(weighted_terms, index).fillna(0.0)
    # Renorm path: per-row NaN-aware weighted average.
    term_df = pd.concat(
        [pd.to_numeric(t, errors="coerce").reindex(index) for t in weighted_terms],
        axis=1,
    )
    abs_w_arr = np.asarray(abs_weights, dtype=float)
    valid_mask = term_df.notna().to_numpy(dtype=float)  # (n_rows, n_terms)
    if l1_target and l1_target > 0.0:
        denom = np.full(len(index), float(l1_target), dtype=float)
    else:
        denom = valid_mask @ abs_w_arr  # per-row L1, excluding NaN terms
    total = term_df.fillna(0.0).sum(axis=1).to_numpy(dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        result = np.where(denom > 1e-8, total / denom, 0.0)
    return pd.Series(result, index=index, dtype=float).fillna(0.0)


__all__ = [
    "_resolve_engine_commit_sha",
    "phase_is_enabled",
    "now_ts",
    "log",
    "apply_fast_mode",
    "to_cfg",
    "configure_last_n_years_backtest",
    "winsorize",
    "robust_z",
    "squeeze_series",
    "hard_sanitize",
    "safe_float",
    "cross_sectional_robust_z",
    "cross_sectional_robust_z_by_sector",
    "numeric_series_or_default",
    "rolling_robust_z",
    "row_mean",
    "weighted_sleeve_composite",
    "ENGINE_COMMIT_SHA",
    "LIVE_CACHE_ALPHA_PRESERVE_FIELDS",
]
