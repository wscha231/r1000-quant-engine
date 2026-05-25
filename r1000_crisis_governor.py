"""Plan C v3.6 Phase E5+E6 -- CAGR-preserving crisis governor.

Pure logic module. No I/O, no network, no SEC/yfinance calls. The pipeline
imports the two public entry points (apply_exposure_ladder + compute_reentry_score)
and calls them only when cfg.crisis_governor_apply_to_live is True
(see r1000_pipeline._apply_evidence_kill_switch for the kill switch pattern).

Design principles (from CODEX_HANDOFF v3.6 Section 17):
  1. NORMAL markets keep cash 0-5%. No defensive drag during good times.
  2. CAUTION (0.30 <= crisis < 0.50): throttle NEW buys, hold winners,
     trim breaks only if replacement is available.
  3. DEFENSE (0.50 <= crisis < 0.70): cash 10-25%, broken high-beta trimmed,
     replacement preferred over cash.
  4. CRISIS (>= 0.70): cash 25-50%, concentrated exposure floor 0.30, re-entry
     ladder armed.
  5. RE-ENTRY: monotonic increase. reentry_score crosses 0.40 -> add 25% risk;
     0.60 -> 50-70%; 0.75 -> full normal.

Crisis-type-specific pacing (Phase E6 nuance):
  - shock_crash: fast defense + fast re-entry (2020 COVID needed 4-week return)
  - slow_bear:   gradual defense + slow re-entry (2022 needs quarterly confirmation)
  - credit_crisis: fast defense + wait for credit spread stabilization

Plan ref:
    CODEX_HANDOFF_PLAN_C_V3_5_20260520.md Section 17.6-17.7 (Phase E5+E6)
    research/final_integrated_engine_20260524/plan.md Section 2 E5+E6
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Optional

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Zone classification (E5 backbone)
# ---------------------------------------------------------------------------


def crisis_zone(
    crisis_score: float,
    low: float = 0.30,
    mid: float = 0.50,
    high: float = 0.70,
) -> str:
    """Map a clipped [0,1] crisis_score to a named zone."""
    if pd.isna(crisis_score):
        return "normal"
    s = float(crisis_score)
    if s < low:
        return "normal"
    if s < mid:
        return "caution"
    if s < high:
        return "defense"
    return "crisis"


# ---------------------------------------------------------------------------
# Exposure ladder (E5)
# ---------------------------------------------------------------------------


@dataclass
class ExposureTarget:
    """Result of one exposure-ladder evaluation."""
    zone: str
    target_cash_floor: float           # do not let cash drop below this
    target_cash_ceiling: float         # do not let cash rise above this
    block_new_buys: bool
    trim_broken_only: bool             # True = don't trim winners
    require_replacement_before_cash: bool
    concentrated_exposure_floor: float # min concentrated equity exposure


def evaluate_exposure_target(
    crisis_score: float,
    cfg_thresholds: Optional[Mapping[str, float]] = None,
    new_buy_throttle_at: float = 0.30,
    concentrated_floor: float = 0.30,
) -> ExposureTarget:
    """Return ladder zone + cash range + behavioural flags for a given crisis_score.

    cfg_thresholds keys (all optional, defaults match Plan E5):
        low, mid, high                            -- zone boundaries
        cash_floor_normal/caution/defense/crisis  -- low end of cash range
        cash_ceiling_normal/caution/defense/crisis -- high end of cash range
    """
    cfg = dict(cfg_thresholds or {})
    low = float(cfg.get("low", 0.30))
    mid = float(cfg.get("mid", 0.50))
    high = float(cfg.get("high", 0.70))
    zone = crisis_zone(crisis_score, low=low, mid=mid, high=high)

    cash_ranges = {
        "normal":  (cfg.get("cash_floor_normal",  0.00), cfg.get("cash_ceiling_normal",  0.05)),
        "caution": (cfg.get("cash_floor_caution", 0.05), cfg.get("cash_ceiling_caution", 0.10)),
        "defense": (cfg.get("cash_floor_defense", 0.10), cfg.get("cash_ceiling_defense", 0.25)),
        "crisis":  (cfg.get("cash_floor_crisis",  0.25), cfg.get("cash_ceiling_crisis",  0.50)),
    }
    floor, ceiling = cash_ranges[zone]
    block_new = bool(float(crisis_score or 0.0) >= new_buy_throttle_at and zone != "normal")
    return ExposureTarget(
        zone=zone,
        target_cash_floor=float(floor),
        target_cash_ceiling=float(ceiling),
        block_new_buys=block_new,
        trim_broken_only=(zone in ("caution", "defense")),
        require_replacement_before_cash=(zone == "defense"),
        concentrated_exposure_floor=float(concentrated_floor),
    )


def apply_exposure_ladder(
    weights: pd.Series,
    crisis_score: float,
    target: Optional[ExposureTarget] = None,
    cfg_thresholds: Optional[Mapping[str, float]] = None,
    cash_ticker: str = "CASH",
) -> pd.Series:
    """Re-shape an existing weight vector to obey the exposure ladder.

    Algorithm:
      1. Compute current cash weight (or 0 if no cash row).
      2. Determine target cash range from crisis_score zone.
      3. If current_cash < floor -> scale non-cash weights down proportionally
         to lift cash to floor (preserves relative ranking inside non-cash).
      4. If current_cash > ceiling -> trim cash to ceiling, re-distribute
         saved weight to non-cash proportionally.
      5. Re-normalise to sum exactly to 1.0 (handles tiny float drift).

    weights must be indexed by ticker. The function does NOT mutate the input.
    """
    target = target or evaluate_exposure_target(crisis_score, cfg_thresholds=cfg_thresholds)
    w = weights.copy().astype(float)
    if w.empty:
        return w
    cash_mask = w.index.astype(str).str.upper() == cash_ticker.upper()
    cash_weight = float(w[cash_mask].sum())
    noncash_sum = float(w[~cash_mask].sum())
    total = cash_weight + noncash_sum
    if total <= 0:
        return w
    new_cash = float(np.clip(cash_weight, target.target_cash_floor * total,
                              target.target_cash_ceiling * total))
    new_noncash_sum = total - new_cash
    # Scale non-cash proportionally
    if noncash_sum > 0 and new_noncash_sum > 0:
        scale = new_noncash_sum / noncash_sum
        w.loc[~cash_mask] = w.loc[~cash_mask] * scale
    # Distribute new cash to first cash row, or append a synthetic CASH row
    if cash_mask.any():
        w.loc[cash_mask] = 0.0
        first_cash_idx = w.index[cash_mask][0]
        w.loc[first_cash_idx] = new_cash
    else:
        w = pd.concat([w, pd.Series({cash_ticker: new_cash})])
    s = float(w.sum())
    if s > 0:
        w = w / s
    return w


# ---------------------------------------------------------------------------
# Re-entry score (E6)
# ---------------------------------------------------------------------------


def compute_reentry_score(features: pd.Series) -> float:
    """Compute reentry_score from a single row of daily features.

    Formula (CODEX_HANDOFF v3.6 Section 17.7):
        0.30 * vix_normalization        (vix_zscore_60d below 0.5)
      + 0.25 * qqq_ma_reclaim           (qqq_close >= ma20 OR ma50)
      + 0.20 * breadth_thrust           (placeholder: market trend recovery proxy)
      + 0.15 * credit_spread_stable     (hy_oas_zscore <= 0.8)
      + 0.10 * leadership_recovery      (placeholder: spy_5d_dd >= -0.02)

    Each component is clipped to [0, 1] before weighting. Returns float in [0,1].
    """
    def get(col: str, default: float = np.nan) -> float:
        if col not in features.index:
            return default
        v = features[col]
        try:
            return float(v) if pd.notna(v) else default
        except (TypeError, ValueError):
            return default

    vix_z = get("vix_zscore_60d", default=2.0)
    vix_norm = float(np.clip(1.0 - max(vix_z, 0.0) / 1.0, 0.0, 1.0))

    qqq_close = get("qqq_close")
    qqq_ma20 = get("qqq_ma20")
    qqq_ma50 = get("qqq_ma50")
    qqq_reclaim = 0.0
    if not np.isnan(qqq_close) and not np.isnan(qqq_ma20):
        qqq_reclaim = max(qqq_reclaim, 1.0 if qqq_close >= qqq_ma20 else 0.5 * (qqq_close / qqq_ma20))
    if not np.isnan(qqq_close) and not np.isnan(qqq_ma50):
        qqq_reclaim = max(qqq_reclaim, 1.0 if qqq_close >= qqq_ma50 else 0.0)
    qqq_reclaim = float(np.clip(qqq_reclaim, 0.0, 1.0))

    # Breadth thrust proxy: spy_20d_dd recovers to >= -2%
    spy_20d_dd = get("spy_20d_dd", default=0.0)
    breadth = float(np.clip(1.0 + spy_20d_dd / 0.02, 0.0, 1.0))

    hy_z = get("hy_oas_zscore_60d", default=2.0)
    credit_stable = float(np.clip(1.0 - max(hy_z, 0.0) / 0.8, 0.0, 1.0))

    spy_5d_dd = get("spy_5d_dd", default=0.0)
    leadership = float(np.clip(1.0 + spy_5d_dd / 0.02, 0.0, 1.0))

    score = (
        0.30 * vix_norm
        + 0.25 * qqq_reclaim
        + 0.20 * breadth
        + 0.15 * credit_stable
        + 0.10 * leadership
    )
    return float(np.clip(score, 0.0, 1.0))


def reentry_exposure_multiplier(reentry_score: float, prior_multiplier: float = 0.0) -> float:
    """Map reentry_score -> incremental risk-on multiplier in [0, 1].

    Ladder (CODEX_HANDOFF v3.6 Section 17.7):
      < 0.40         -> hold (no change)
      0.40 .. 0.60   -> at least 0.25
      0.60 .. 0.75   -> at least 0.60
      >= 0.75        -> 1.00 (full normal risk)

    The function returns the GREATER of the threshold floor and prior_multiplier
    so the ladder is MONOTONIC (Phase E6 invariant: risk-on never reverses
    without crisis_score deterioration). Caller is responsible for tracking
    prior_multiplier across days.
    """
    if pd.isna(reentry_score):
        return float(prior_multiplier)
    s = float(reentry_score)
    if s < 0.40:
        floor = 0.0
    elif s < 0.60:
        floor = 0.25
    elif s < 0.75:
        floor = 0.60
    else:
        floor = 1.00
    return float(max(floor, prior_multiplier))


# ---------------------------------------------------------------------------
# Public façade (called from r1000_pipeline behind kill switch)
# ---------------------------------------------------------------------------


def maybe_apply_governor(
    weights: pd.Series,
    crisis_score: float,
    reentry_score: Optional[float],
    prior_multiplier: float,
    cfg,
) -> tuple[pd.Series, ExposureTarget, float]:
    """One-shot governor application -- intended call site from pipeline.

    Returns (new_weights, exposure_target, new_reentry_multiplier).

    Caller MUST check cfg.crisis_governor_apply_to_live BEFORE invoking this
    function. We do not check the kill switch internally so callers retain
    explicit control and tests can exercise governor logic without monkey-
    patching cfg.
    """
    thr = {
        "low":  float(getattr(cfg, "crisis_score_thresholds_low", 0.30)),
        "mid":  float(getattr(cfg, "crisis_score_thresholds_mid", 0.50)),
        "high": float(getattr(cfg, "crisis_score_thresholds_high", 0.70)),
    }
    target = evaluate_exposure_target(
        crisis_score,
        cfg_thresholds=thr,
        new_buy_throttle_at=float(getattr(cfg, "crisis_new_buy_throttle_at", 0.30)),
        concentrated_floor=float(getattr(cfg, "crisis_concentrated_exposure_floor", 0.30)),
    )
    new_weights = apply_exposure_ladder(weights, crisis_score, target=target, cfg_thresholds=thr)
    new_multiplier = reentry_exposure_multiplier(
        reentry_score if reentry_score is not None else 1.0,
        prior_multiplier=prior_multiplier,
    )
    return new_weights, target, new_multiplier
