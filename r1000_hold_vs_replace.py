"""Plan C v3.6 Phase F -- Hold-vs-Replace Discipline.

Pure logic module. Decides whether to HOLD an existing position, TRIM it,
or REPLACE it with a stronger candidate. Designed to be called AFTER the
Phase E crisis governor has set the exposure ladder, so the inputs are
already cash-adjusted.

Decision matrix (CODEX_HANDOFF v3.6 Section 18.1):
    winner_intact         -> HOLD (do not sell only because of market vol)
    weakening (-5..-15%)  -> TRIM 25-50% only if a clearly better replacement
    broken (<-15% or
            MA200 break
            or RS<30)     -> REPLACE if candidate available, else CASH (crisis)
    winner_overextended   -> HOLD (let it run, no add)

Replacement thresholds (CODEX_HANDOFF v3.6 Section 18.2):
    NORMAL_REPLACEMENT_THRESHOLD = 0.75 sigma
    WEAKENING_REPLACEMENT_THRESHOLD = 0.35 sigma
    CRISIS_REPLACEMENT_RULE = "quality_defensive_only"

Safety guards (Section 18.3):
    * No replace if candidate in same broken sector AND industry
    * No reduce concentrated below crisis_concentrated_exposure_floor (0.30)
    * Crisis-mode replacement = quality_growth_score > 0.7 pool ONLY
    * Replacement requires PIT-clean available_from_ts
    * Max 2 replacements per rebalance (avoid churn)

Plan ref:
    CODEX_HANDOFF_PLAN_C_V3_5_20260520.md Section 18 (Phase F)
    research/final_integrated_engine_20260524/plan.md Section 3 F1-F4
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Constants (CODEX_HANDOFF v3.6 Section 18.2)
# ---------------------------------------------------------------------------

NORMAL_REPLACEMENT_SIGMA = 0.75
WEAKENING_REPLACEMENT_SIGMA = 0.35
CRISIS_QUALITY_FLOOR = 0.70          # quality_growth_score min for crisis swap
MAX_REPLACEMENTS_PER_REBALANCE = 2


# ---------------------------------------------------------------------------
# F1 -- Position state classifier
# ---------------------------------------------------------------------------


@dataclass
class PositionState:
    ticker: str
    state: str                    # winner_intact / weakening / broken / winner_overextended / neutral
    drawdown_from_entry: float
    rs_rank: Optional[float] = None
    ma200_violated: bool = False
    above_target_gain: bool = False


def classify_position_state(
    ticker: str,
    current_price: float,
    entry_price: float,
    rs_rank: Optional[float] = None,
    ma200: Optional[float] = None,
    target_gain_pct: float = 0.30,
    pe_zscore: Optional[float] = None,
) -> PositionState:
    """Classify a position into one of five states.

    Inputs deliberately keep both Phase F (decision side) and the engine
    (data side) loosely coupled: only the float values are required, no
    cfg/paths dependencies.
    """
    if entry_price <= 0:
        return PositionState(ticker=ticker, state="neutral", drawdown_from_entry=0.0)
    dd = (current_price / entry_price) - 1.0
    ma200_break = ma200 is not None and current_price < ma200
    overextended = dd > target_gain_pct and (pe_zscore is not None and pe_zscore > 2.0)

    # Priority cascade -- broken always wins over weakening
    if dd <= -0.15 or ma200_break or (rs_rank is not None and rs_rank < 30):
        state = "broken"
    elif dd <= -0.05:
        state = "weakening"
    elif overextended:
        state = "winner_overextended"
    elif dd > -0.05 and (rs_rank is None or rs_rank >= 60):
        state = "winner_intact"
    else:
        state = "neutral"
    return PositionState(
        ticker=ticker,
        state=state,
        drawdown_from_entry=float(dd),
        rs_rank=rs_rank,
        ma200_violated=ma200_break,
        above_target_gain=bool(dd > target_gain_pct),
    )


# ---------------------------------------------------------------------------
# F2 -- Replacement candidate selection
# ---------------------------------------------------------------------------


@dataclass
class ReplacementDecision:
    held_ticker: str
    action: str                   # hold / trim / replace / cash
    candidate_ticker: Optional[str] = None
    score_delta_sigma: float = 0.0
    reason: str = ""
    blocked_by: list[str] = field(default_factory=list)


def select_replacement_candidate(
    held_score_z: float,
    candidates: pd.DataFrame,
    held_sector: Optional[str] = None,
    crisis_zone: str = "normal",
    threshold_sigma: float = NORMAL_REPLACEMENT_SIGMA,
) -> Optional[pd.Series]:
    """Return the best candidate row satisfying the threshold + safety guards.

    candidates DataFrame must have columns:
      ticker (str)
      score_z (float)               -- robust z-score of selection_score
      sector  (str)                 -- for same-sector safety guard
      quality_growth_score (float)  -- 0..1 (used in crisis mode)
      available_from_ts (timestamp) -- PIT check (caller verifies <= as_of_date)

    Returns the single best candidate Series, or None if no candidate clears
    the threshold + guards.
    """
    if candidates is None or candidates.empty:
        return None
    needed = ("ticker", "score_z")
    for c in needed:
        if c not in candidates.columns:
            return None
    pool = candidates.copy()
    # Safety guard: drop same-sector candidates when we're replacing a broken position
    if held_sector and "sector" in pool.columns:
        pool = pool[pool["sector"].astype(str).str.lower() != str(held_sector).lower()]
    # Crisis mode: must have quality_growth_score above floor
    if crisis_zone in ("defense", "crisis") and "quality_growth_score" in pool.columns:
        pool = pool[pd.to_numeric(pool["quality_growth_score"], errors="coerce") >= CRISIS_QUALITY_FLOOR]
    # Threshold: candidate's z-score must beat held by >= threshold_sigma
    pool = pool[pd.to_numeric(pool["score_z"], errors="coerce") >= held_score_z + threshold_sigma]
    if pool.empty:
        return None
    # Pick best by score_z descending
    best = pool.sort_values("score_z", ascending=False).iloc[0]
    return best


def decide_action(
    position: PositionState,
    held_score_z: float,
    candidates: pd.DataFrame,
    held_sector: Optional[str] = None,
    crisis_zone: str = "normal",
) -> ReplacementDecision:
    """Combine position state + candidate availability into an action."""
    if position.state in ("winner_intact", "winner_overextended"):
        return ReplacementDecision(
            held_ticker=position.ticker,
            action="hold",
            reason=f"{position.state} (dd={position.drawdown_from_entry:+.2%})",
        )
    if position.state == "neutral":
        return ReplacementDecision(
            held_ticker=position.ticker,
            action="hold",
            reason="neutral state",
        )
    # weakening / broken
    threshold = (
        WEAKENING_REPLACEMENT_SIGMA
        if position.state == "weakening"
        else NORMAL_REPLACEMENT_SIGMA
    )
    cand = select_replacement_candidate(
        held_score_z=held_score_z,
        candidates=candidates,
        held_sector=held_sector,
        crisis_zone=crisis_zone,
        threshold_sigma=threshold,
    )
    if cand is None:
        # No candidate: weakening -> trim 25%, broken -> cash (crisis) or trim
        if position.state == "weakening":
            return ReplacementDecision(
                held_ticker=position.ticker,
                action="trim",
                reason="weakening, no qualified replacement",
                blocked_by=["no_candidate"],
            )
        # broken
        if crisis_zone in ("defense", "crisis"):
            return ReplacementDecision(
                held_ticker=position.ticker,
                action="cash",
                reason=f"broken in {crisis_zone}, no replacement, route to cash",
                blocked_by=["no_candidate", f"crisis_zone={crisis_zone}"],
            )
        return ReplacementDecision(
            held_ticker=position.ticker,
            action="trim",
            reason="broken, no qualified replacement, partial trim",
            blocked_by=["no_candidate"],
        )
    delta = float(cand["score_z"]) - held_score_z
    return ReplacementDecision(
        held_ticker=position.ticker,
        action="replace",
        candidate_ticker=str(cand["ticker"]),
        score_delta_sigma=delta,
        reason=f"{position.state} -> replace (delta={delta:+.2f}sigma, threshold={threshold})",
    )


# ---------------------------------------------------------------------------
# F3 -- Batch evaluation with safety guards
# ---------------------------------------------------------------------------


def evaluate_portfolio_holds_vs_replaces(
    holdings: pd.DataFrame,
    candidates: pd.DataFrame,
    crisis_zone: str = "normal",
    concentrated_floor: float = 0.30,
    max_replacements: int = MAX_REPLACEMENTS_PER_REBALANCE,
) -> pd.DataFrame:
    """Walk current holdings, classify each, decide actions, apply caps.

    holdings DataFrame must have columns:
      ticker, current_price, entry_price, weight, score_z, sector
      (optional: rs_rank, ma200, pe_zscore)

    Returns: DataFrame of decisions with action breakdown.

    Caps applied AFTER per-position decisions:
      * Replacements > max_replacements -> later ones revert to "hold"
      * Concentrated mode: if reducing equity would breach floor, revert to "trim"
    """
    if holdings is None or holdings.empty:
        return pd.DataFrame()
    decisions: list[dict] = []
    candidate_pool = candidates.copy() if candidates is not None else pd.DataFrame()
    replace_count = 0

    for r in holdings.itertuples(index=False):
        position = classify_position_state(
            ticker=str(r.ticker),
            current_price=float(r.current_price),
            entry_price=float(r.entry_price),
            rs_rank=float(r.rs_rank) if hasattr(r, "rs_rank") else None,
            ma200=float(r.ma200) if hasattr(r, "ma200") and not pd.isna(r.ma200) else None,
            pe_zscore=float(r.pe_zscore) if hasattr(r, "pe_zscore") and not pd.isna(r.pe_zscore) else None,
        )
        # Drop this ticker from the candidate pool so we don't self-swap
        if not candidate_pool.empty and "ticker" in candidate_pool.columns:
            candidate_pool = candidate_pool[candidate_pool["ticker"].astype(str) != str(r.ticker)]
        held_z = float(r.score_z) if hasattr(r, "score_z") else 0.0
        sector = getattr(r, "sector", None)
        action = decide_action(
            position=position,
            held_score_z=held_z,
            candidates=candidate_pool,
            held_sector=sector,
            crisis_zone=crisis_zone,
        )
        # Apply replacement cap
        if action.action == "replace":
            if replace_count >= max_replacements:
                action = ReplacementDecision(
                    held_ticker=position.ticker,
                    action="hold",
                    reason=f"replacement cap reached ({max_replacements})",
                    blocked_by=["replacement_cap"],
                )
            else:
                replace_count += 1
                # Remove the chosen candidate from pool so subsequent positions
                # can't pick the same one.
                if not candidate_pool.empty:
                    candidate_pool = candidate_pool[
                        candidate_pool["ticker"].astype(str) != action.candidate_ticker
                    ]
        decisions.append({
            "ticker": position.ticker,
            "state": position.state,
            "drawdown_from_entry": position.drawdown_from_entry,
            "weight": float(getattr(r, "weight", 0.0)),
            "action": action.action,
            "candidate_ticker": action.candidate_ticker,
            "score_delta_sigma": action.score_delta_sigma,
            "reason": action.reason,
            "blocked_by": ",".join(action.blocked_by) if action.blocked_by else None,
        })

    out = pd.DataFrame(decisions)
    if out.empty:
        return out
    # Concentrated floor safety: if cumulative equity drop would breach floor,
    # revert "cash" actions to "trim" so equity stays above floor.
    if crisis_zone in ("crisis", "defense"):
        cash_mask = out["action"] == "cash"
        equity_to_remove = float(out.loc[cash_mask, "weight"].sum())
        current_equity = float(out["weight"].sum())
        if current_equity - equity_to_remove < concentrated_floor:
            # Walk back the lowest-weight cash actions until floor is OK
            cash_rows = out.loc[cash_mask].sort_values("weight")
            removed = 0.0
            for idx in cash_rows.index:
                if current_equity - (equity_to_remove - removed) >= concentrated_floor:
                    break
                removed += float(out.at[idx, "weight"])
                out.at[idx, "action"] = "trim"
                # blocked_by may already be set; append
                prev = out.at[idx, "blocked_by"]
                tag = "concentrated_floor"
                out.at[idx, "blocked_by"] = (
                    f"{prev},{tag}" if prev else tag
                )
    return out


def decision_summary(decisions: pd.DataFrame) -> dict:
    if decisions is None or decisions.empty:
        return {"total": 0, "by_action": {}}
    counts = decisions["action"].value_counts().to_dict()
    return {
        "total": int(len(decisions)),
        "by_action": {k: int(v) for k, v in counts.items()},
        "replacement_pairs": [
            {"out": r["ticker"], "in": r["candidate_ticker"], "delta": float(r["score_delta_sigma"])}
            for _, r in decisions[decisions["action"] == "replace"].iterrows()
        ],
    }
