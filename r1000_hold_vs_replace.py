"""Plan C v3.6 Phase F (G0-hardened) -- Hold-vs-Replace Discipline.

Pure logic module. Decides whether to HOLD, TRIM, REPLACE, or move to CASH
each position. Output is a sized order book (trim_pct, weight_delta,
target_weight_after, cash_delta) ready for broker-ledger replay.

G0 hardening applied (post Phase F first-pass review):
  G0-A  PIT availability guard       -- candidates filtered by available_from_ts
  G0-B  Global replacement priority  -- broken+heavy positions get first pick
                                        of the cap, not the iteration order
  G0-C  Trim sizing                  -- explicit trim_pct, weight_delta,
                                        target_weight_after, cash_delta
  G0-D  Same-sector policy           -- allow / penalize / block / block_industry
                                        instead of unconditional same-sector ban
  G0-E  Data quality audit           -- missing entry_price -> review_required,
                                        not silent neutral
  G0-F  Candidate score calibration  -- evaluator concatenates pools BEFORE
                                        z-scoring (see run_hold_vs_replace_evaluator)
  G0-G  Enriched decision schema     -- candidate_source + data_quality_flag

Decision matrix (CODEX_HANDOFF v3.6 Section 18.1, refined by G0 review):
    winner_intact         -> HOLD
    weakening (-5..-15%)  -> REPLACE if priority+candidate, else TRIM 25% (or HOLD if no need)
    broken (<-15% / MA200 break / RS<30)
                          -> REPLACE if priority+candidate, else CASH (crisis) or TRIM 50%
    winner_overextended   -> HOLD
    review_required       -> HOLD pending human audit (e.g. missing entry_price)

Plan ref:
    CODEX_HANDOFF_PLAN_C_V3_5_20260520.md Section 18 (Phase F)
    research/final_integrated_engine_20260524/plan.md Section 3 F1-F4
    G0 review feedback: 2026-05-24 (this commit)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Constants (CODEX_HANDOFF v3.6 Section 18.2 + G0 hardening)
# ---------------------------------------------------------------------------

NORMAL_REPLACEMENT_SIGMA = 0.75
WEAKENING_REPLACEMENT_SIGMA = 0.35
CRISIS_QUALITY_FLOOR = 0.70
MAX_REPLACEMENTS_PER_REBALANCE = 2

# G0-C: explicit sizing. (state, zone) -> trim_pct (0.0 = hold, 1.0 = fully exit)
TRIM_PCT_BY_STATE_AND_ZONE: dict[tuple[str, str], float] = {
    ("weakening", "normal"):  0.25,
    ("weakening", "caution"): 0.25,
    ("weakening", "defense"): 0.50,
    ("weakening", "crisis"):  0.50,
    ("broken",    "normal"):  0.50,
    ("broken",    "caution"): 0.50,
    ("broken",    "defense"): 0.75,
    ("broken",    "crisis"):  0.75,
}

# G0-B: priority weights for global replacement ranking
STATE_PRIORITY: dict[str, int] = {
    "broken": 2,
    "weakening": 1,
    "winner_overextended": 0,
    "winner_intact": 0,
    "neutral": 0,
    "review_required": 0,
}

# G0-D: same-sector policy menu
SECTOR_POLICY_BY_ZONE: dict[str, str] = {
    "normal":  "allow",
    "caution": "allow",
    "defense": "penalize",
    "crisis":  "block",
}
SECTOR_PENALTY_SIGMA = 0.50  # subtracted from candidate score_z when penalizing


# ---------------------------------------------------------------------------
# F1 -- Position state classifier (G0-E hardened for missing entry_price)
# ---------------------------------------------------------------------------


@dataclass
class PositionState:
    ticker: str
    state: str
    drawdown_from_entry: float
    rs_rank: Optional[float] = None
    ma200_violated: bool = False
    above_target_gain: bool = False
    data_quality_flag: str = "ok"     # ok / missing_entry_price / missing_score


def _is_missing_number(x) -> bool:
    """Treat None, NaN, NaT, +-inf as missing."""
    if x is None:
        return True
    try:
        f = float(x)
    except (TypeError, ValueError):
        return True
    if np.isnan(f) or np.isinf(f):
        return True
    return False


def classify_position_state(
    ticker: str,
    current_price: float,
    entry_price: float,
    rs_rank: Optional[float] = None,
    ma200: Optional[float] = None,
    target_gain_pct: float = 0.30,
    pe_zscore: Optional[float] = None,
) -> PositionState:
    """Classify a position into one of six states.

    G0-E: when entry_price is missing/<=0/NaN, return `review_required` with
    `data_quality_flag="missing_entry_price"`. Caller MUST NOT silently treat
    these as neutral -- they need broker-ledger avg_cost fallback or human
    review before any action is taken.
    """
    if _is_missing_number(entry_price) or float(entry_price) <= 0 or _is_missing_number(current_price):
        return PositionState(
            ticker=ticker,
            state="review_required",
            drawdown_from_entry=0.0,
            rs_rank=rs_rank,
            data_quality_flag="missing_entry_price",
        )
    cp = float(current_price)
    ep = float(entry_price)
    dd = (cp / ep) - 1.0
    ma200_break = (
        ma200 is not None
        and not _is_missing_number(ma200)
        and cp < float(ma200)
    )
    overextended = (
        dd > target_gain_pct
        and pe_zscore is not None
        and not _is_missing_number(pe_zscore)
        and float(pe_zscore) > 2.0
    )
    rs_low = (
        rs_rank is not None
        and not _is_missing_number(rs_rank)
        and float(rs_rank) < 30
    )

    # Priority cascade -- broken always wins over weakening
    if dd <= -0.15 or ma200_break or rs_low:
        state = "broken"
    elif dd <= -0.05:
        state = "weakening"
    elif overextended:
        state = "winner_overextended"
    elif dd > -0.05 and (rs_rank is None or _is_missing_number(rs_rank) or float(rs_rank) >= 60):
        state = "winner_intact"
    else:
        state = "neutral"

    return PositionState(
        ticker=ticker,
        state=state,
        drawdown_from_entry=float(dd),
        rs_rank=float(rs_rank) if (rs_rank is not None and not _is_missing_number(rs_rank)) else None,
        ma200_violated=ma200_break,
        above_target_gain=bool(dd > target_gain_pct),
        data_quality_flag="ok",
    )


# ---------------------------------------------------------------------------
# F2 -- Replacement candidate selection (G0-A PIT + G0-D sector policy)
# ---------------------------------------------------------------------------


@dataclass
class ReplacementDecision:
    held_ticker: str
    action: str                          # hold / trim / replace / cash
    candidate_ticker: Optional[str] = None
    score_delta_sigma: float = 0.0
    reason: str = ""
    blocked_by: list[str] = field(default_factory=list)
    # G0-C sizing
    trim_pct: float = 0.0
    weight_delta: float = 0.0            # signed (negative = reduce held)
    target_weight_after: float = 0.0
    cash_delta: float = 0.0              # signed (positive = adds to cash)
    # G0-G enriched audit fields
    candidate_source: Optional[str] = None
    data_quality_flag: str = "ok"


def _apply_pit_filter(
    pool: pd.DataFrame, as_of_date: Optional[pd.Timestamp]
) -> pd.DataFrame:
    """G0-A: drop candidates whose available_from_ts > as_of_date.

    If as_of_date is None, returns pool unchanged. If as_of_date is given
    but a candidate's available_from_ts is missing/NaT, that candidate is
    NOT eligible (conservative).
    """
    if as_of_date is None or pool.empty:
        return pool
    if "available_from_ts" not in pool.columns:
        # Caller did not provide PIT timestamps -> all candidates ineligible
        return pool.iloc[0:0]
    ts = pd.to_datetime(pool["available_from_ts"], errors="coerce")
    mask = ts.notna() & (ts <= pd.Timestamp(as_of_date))
    return pool[mask]


def _apply_sector_policy(
    pool: pd.DataFrame,
    held_sector: Optional[str],
    held_industry: Optional[str],
    sector_policy: str,
) -> pd.DataFrame:
    """G0-D: refined same-sector handling.

    sector_policy values:
      "allow"          -- no filter (normal mode)
      "penalize"       -- subtract SECTOR_PENALTY_SIGMA from score_z of
                          same-sector candidates (they can still win if strong)
      "block"          -- drop same-sector
      "block_industry" -- drop only same-industry (more specific than sector)
    """
    if pool.empty:
        return pool
    if sector_policy == "allow":
        return pool
    if sector_policy == "block" and held_sector and "sector" in pool.columns:
        return pool[pool["sector"].astype(str).str.lower() != str(held_sector).lower()]
    if sector_policy == "block_industry" and held_industry and "industry" in pool.columns:
        return pool[pool["industry"].astype(str).str.lower() != str(held_industry).lower()]
    if sector_policy == "penalize" and held_sector and "sector" in pool.columns:
        pool = pool.copy()
        same_mask = pool["sector"].astype(str).str.lower() == str(held_sector).lower()
        pool.loc[same_mask, "score_z"] = (
            pd.to_numeric(pool.loc[same_mask, "score_z"], errors="coerce")
            - SECTOR_PENALTY_SIGMA
        )
        return pool
    return pool


def select_replacement_candidate(
    held_score_z: float,
    candidates: pd.DataFrame,
    held_sector: Optional[str] = None,
    held_industry: Optional[str] = None,
    crisis_zone: str = "normal",
    threshold_sigma: float = NORMAL_REPLACEMENT_SIGMA,
    as_of_date: Optional[pd.Timestamp] = None,
    sector_policy: Optional[str] = None,
) -> Optional[pd.Series]:
    """Return the best candidate row satisfying threshold + safety guards.

    candidates DataFrame columns:
      ticker (str, required)
      score_z (float, required)
      sector (str, optional)
      industry (str, optional)               -- G0-D more granular block
      quality_growth_score (float, optional) -- crisis floor
      available_from_ts (timestamp, optional)-- G0-A PIT filter
      candidate_source (str, optional)       -- G0-G provenance
    """
    if candidates is None or candidates.empty:
        return None
    needed = ("ticker", "score_z")
    for c in needed:
        if c not in candidates.columns:
            return None
    pool = candidates.copy()
    # G0-A: PIT filter
    pool = _apply_pit_filter(pool, as_of_date)
    if pool.empty:
        return None
    # G0-D: sector policy (default determined by crisis zone)
    if sector_policy is None:
        sector_policy = SECTOR_POLICY_BY_ZONE.get(crisis_zone, "allow")
    pool = _apply_sector_policy(pool, held_sector, held_industry, sector_policy)
    if pool.empty:
        return None
    # Crisis mode: quality_growth_score >= floor
    if crisis_zone in ("defense", "crisis") and "quality_growth_score" in pool.columns:
        pool = pool[
            pd.to_numeric(pool["quality_growth_score"], errors="coerce")
            >= CRISIS_QUALITY_FLOOR
        ]
    if pool.empty:
        return None
    # Threshold: candidate's z-score must beat held by >= threshold_sigma
    pool = pool[
        pd.to_numeric(pool["score_z"], errors="coerce")
        >= held_score_z + threshold_sigma
    ]
    if pool.empty:
        return None
    best = pool.sort_values("score_z", ascending=False).iloc[0]
    return best


# ---------------------------------------------------------------------------
# G0-C sizing helpers
# ---------------------------------------------------------------------------


def _sizing_for_trim(state: str, crisis_zone: str, weight: float) -> dict:
    pct = TRIM_PCT_BY_STATE_AND_ZONE.get((state, crisis_zone), 0.50)
    weight_delta = -pct * weight
    return {
        "trim_pct": pct,
        "weight_delta": weight_delta,
        "target_weight_after": weight + weight_delta,
        "cash_delta": -weight_delta,
    }


def _sizing_for_replace(weight: float) -> dict:
    # 100% out of held, 100% into candidate (preserves weight); cash unchanged
    return {
        "trim_pct": 1.0,
        "weight_delta": -weight,
        "target_weight_after": 0.0,
        "cash_delta": 0.0,
    }


def _sizing_for_cash(weight: float) -> dict:
    return {
        "trim_pct": 1.0,
        "weight_delta": -weight,
        "target_weight_after": 0.0,
        "cash_delta": weight,
    }


def _sizing_for_hold() -> dict:
    return {"trim_pct": 0.0, "weight_delta": 0.0, "target_weight_after": 0.0, "cash_delta": 0.0}


# ---------------------------------------------------------------------------
# decide_action (G0-A PIT, G0-D sector policy, G0-G fields)
# ---------------------------------------------------------------------------


def decide_action(
    position: PositionState,
    held_score_z: float,
    candidates: pd.DataFrame,
    held_sector: Optional[str] = None,
    held_industry: Optional[str] = None,
    crisis_zone: str = "normal",
    as_of_date: Optional[pd.Timestamp] = None,
    sector_policy: Optional[str] = None,
    weight: float = 0.0,
) -> ReplacementDecision:
    """Combine position state + candidate availability into an action.

    Caller-provided `weight` is required for trim/replace sizing. If 0.0,
    weight_delta/cash_delta will also be 0.0 (no orders).
    """
    base_fields = {
        "held_ticker": position.ticker,
        "data_quality_flag": position.data_quality_flag,
    }
    if position.state == "review_required":
        sz = _sizing_for_hold()
        return ReplacementDecision(
            **base_fields,
            action="hold",
            reason="review_required: " + position.data_quality_flag,
            blocked_by=["data_quality"],
            **sz,
        )
    if position.state in ("winner_intact", "winner_overextended"):
        sz = _sizing_for_hold()
        return ReplacementDecision(
            **base_fields,
            action="hold",
            reason=f"{position.state} (dd={position.drawdown_from_entry:+.2%})",
            **sz,
        )
    if position.state == "neutral":
        sz = _sizing_for_hold()
        return ReplacementDecision(
            **base_fields,
            action="hold",
            reason="neutral state",
            **sz,
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
        held_industry=held_industry,
        crisis_zone=crisis_zone,
        threshold_sigma=threshold,
        as_of_date=as_of_date,
        sector_policy=sector_policy,
    )
    if cand is None:
        # No candidate -> trim (normal) or cash (crisis + broken)
        if position.state == "broken" and crisis_zone in ("defense", "crisis"):
            sz = _sizing_for_cash(weight)
            return ReplacementDecision(
                **base_fields,
                action="cash",
                reason=f"broken in {crisis_zone}, no replacement, route to cash",
                blocked_by=["no_candidate", f"crisis_zone={crisis_zone}"],
                **sz,
            )
        sz = _sizing_for_trim(position.state, crisis_zone, weight)
        return ReplacementDecision(
            **base_fields,
            action="trim",
            reason=f"{position.state}, no qualified replacement, trim {int(sz['trim_pct']*100)}%",
            blocked_by=["no_candidate"],
            **sz,
        )
    delta = float(cand["score_z"]) - held_score_z
    sz = _sizing_for_replace(weight)
    cand_source = str(cand.get("candidate_source")) if "candidate_source" in cand.index else None
    return ReplacementDecision(
        **base_fields,
        action="replace",
        candidate_ticker=str(cand["ticker"]),
        score_delta_sigma=delta,
        candidate_source=cand_source,
        reason=f"{position.state} -> replace (delta={delta:+.2f}sigma, threshold={threshold})",
        **sz,
    )


# ---------------------------------------------------------------------------
# F3 -- Two-pass batch evaluator (G0-B global priority + sizing + concentrated floor)
# ---------------------------------------------------------------------------


def _decision_to_dict(d: ReplacementDecision, position: PositionState) -> dict:
    return {
        "ticker": d.held_ticker,
        "state": position.state,
        "drawdown_from_entry": position.drawdown_from_entry,
        "weight": 0.0,  # filled by caller
        "action": d.action,
        "candidate_ticker": d.candidate_ticker,
        "candidate_source": d.candidate_source,
        "score_delta_sigma": d.score_delta_sigma,
        "trim_pct": d.trim_pct,
        "weight_delta": d.weight_delta,
        "target_weight_after": d.target_weight_after,
        "cash_delta": d.cash_delta,
        "data_quality_flag": d.data_quality_flag,
        "reason": d.reason,
        "blocked_by": ",".join(d.blocked_by) if d.blocked_by else None,
    }


def evaluate_portfolio_holds_vs_replaces(
    holdings: pd.DataFrame,
    candidates: pd.DataFrame,
    crisis_zone: str = "normal",
    concentrated_floor: float = 0.30,
    max_replacements: int = MAX_REPLACEMENTS_PER_REBALANCE,
    as_of_date: Optional[pd.Timestamp] = None,
    sector_policy: Optional[str] = None,
) -> pd.DataFrame:
    """Two-pass evaluator with G0-B global replacement priority.

    holdings DataFrame columns:
      ticker, current_price, entry_price, weight, score_z, sector
      (optional: industry, rs_rank, ma200, pe_zscore)

    G0-B: Pass 1 = classify all positions; Pass 2 = rank potential
    replacements globally (broken > weakening, then weight, then delta);
    Pass 3 = assign replacements within the cap and fall through to
    trim/cash for the rest.

    G0-C: Every output row has trim_pct + weight_delta + target_weight_after
    + cash_delta filled, so the result is a complete order book.
    """
    if holdings is None or holdings.empty:
        return pd.DataFrame()
    # === Pass 1: classify each holding ===
    states: list[PositionState] = []
    rows: list[dict] = []
    for r in holdings.itertuples(index=False):
        pos = classify_position_state(
            ticker=str(r.ticker),
            current_price=getattr(r, "current_price", float("nan")),
            entry_price=getattr(r, "entry_price", float("nan")),
            rs_rank=getattr(r, "rs_rank", None),
            ma200=getattr(r, "ma200", None),
            pe_zscore=getattr(r, "pe_zscore", None),
        )
        states.append(pos)
        rows.append({
            "row": r,
            "weight": float(getattr(r, "weight", 0.0) or 0.0),
            "held_score_z": float(getattr(r, "score_z", 0.0) or 0.0),
            "sector": getattr(r, "sector", None),
            "industry": getattr(r, "industry", None),
        })

    # === Pass 2: globally rank potential replacements ===
    # Each entry: (priority_key_tuple, holding_idx, position, sector, industry, held_z, weight)
    # We compute a "best candidate score delta if free" for ranking purposes,
    # but the actual assignment in Pass 3 may pick a different candidate (the
    # one available after others have consumed their picks).
    eligible = []
    for i, pos in enumerate(states):
        if pos.state not in ("broken", "weakening"):
            continue
        r = rows[i]
        # Provisional candidate (best ignoring other holdings -- for priority ranking)
        threshold = (
            WEAKENING_REPLACEMENT_SIGMA
            if pos.state == "weakening"
            else NORMAL_REPLACEMENT_SIGMA
        )
        cand = select_replacement_candidate(
            held_score_z=r["held_score_z"],
            candidates=candidates,
            held_sector=r["sector"],
            held_industry=r["industry"],
            crisis_zone=crisis_zone,
            threshold_sigma=threshold,
            as_of_date=as_of_date,
            sector_policy=sector_policy,
        )
        if cand is None:
            continue
        provisional_delta = float(cand["score_z"]) - r["held_score_z"]
        priority_key = (
            STATE_PRIORITY.get(pos.state, 0),  # broken > weakening
            r["weight"],                        # larger weight wins
            provisional_delta,                  # larger delta wins
        )
        eligible.append((priority_key, i, provisional_delta))
    # Sort descending by priority_key tuple
    eligible.sort(key=lambda x: x[0], reverse=True)

    # === Pass 3: assign replacements, respecting cap + candidate exhaustion ===
    candidate_pool = candidates.copy() if candidates is not None else pd.DataFrame()
    # Avoid self-swap: remove all held tickers from pool
    if not candidate_pool.empty and "ticker" in candidate_pool.columns:
        held_tickers = {str(r["row"].ticker).upper() for r in rows}
        candidate_pool = candidate_pool[
            ~candidate_pool["ticker"].astype(str).str.upper().isin(held_tickers)
        ]
    replacement_assignments: dict[int, dict] = {}  # holding_idx -> {candidate_row, delta}
    for _, idx, _ in eligible:
        if len(replacement_assignments) >= max_replacements:
            break
        pos = states[idx]
        r = rows[idx]
        threshold = (
            WEAKENING_REPLACEMENT_SIGMA
            if pos.state == "weakening"
            else NORMAL_REPLACEMENT_SIGMA
        )
        cand = select_replacement_candidate(
            held_score_z=r["held_score_z"],
            candidates=candidate_pool,
            held_sector=r["sector"],
            held_industry=r["industry"],
            crisis_zone=crisis_zone,
            threshold_sigma=threshold,
            as_of_date=as_of_date,
            sector_policy=sector_policy,
        )
        if cand is None:
            continue  # candidate was taken by higher-priority position; fall through
        replacement_assignments[idx] = {
            "candidate": cand,
            "delta": float(cand["score_z"]) - r["held_score_z"],
        }
        candidate_pool = candidate_pool[candidate_pool["ticker"].astype(str) != str(cand["ticker"])]

    # === Pass 4: build full decision rows ===
    decisions: list[dict] = []
    for i, pos in enumerate(states):
        r = rows[i]
        w = r["weight"]
        if i in replacement_assignments:
            assign = replacement_assignments[i]
            cand = assign["candidate"]
            sz = _sizing_for_replace(w)
            d = ReplacementDecision(
                held_ticker=pos.ticker,
                action="replace",
                candidate_ticker=str(cand["ticker"]),
                score_delta_sigma=assign["delta"],
                candidate_source=str(cand.get("candidate_source"))
                    if "candidate_source" in cand.index
                    else None,
                reason=f"{pos.state} -> replace (delta={assign['delta']:+.2f}sigma)",
                data_quality_flag=pos.data_quality_flag,
                **sz,
            )
        elif pos.state == "review_required":
            sz = _sizing_for_hold()
            d = ReplacementDecision(
                held_ticker=pos.ticker,
                action="hold",
                reason=f"review_required: {pos.data_quality_flag}",
                blocked_by=["data_quality"],
                data_quality_flag=pos.data_quality_flag,
                **sz,
            )
        elif pos.state in ("winner_intact", "winner_overextended", "neutral"):
            sz = _sizing_for_hold()
            d = ReplacementDecision(
                held_ticker=pos.ticker,
                action="hold",
                reason=pos.state,
                data_quality_flag=pos.data_quality_flag,
                **sz,
            )
        else:
            # weakening / broken with no assigned replacement -> trim or cash
            blocked = ["no_candidate_after_priority"]
            if pos.state == "broken" and crisis_zone in ("defense", "crisis"):
                sz = _sizing_for_cash(w)
                d = ReplacementDecision(
                    held_ticker=pos.ticker,
                    action="cash",
                    reason=f"broken in {crisis_zone}, no replacement, route to cash",
                    blocked_by=blocked + [f"crisis_zone={crisis_zone}"],
                    data_quality_flag=pos.data_quality_flag,
                    **sz,
                )
            else:
                sz = _sizing_for_trim(pos.state, crisis_zone, w)
                d = ReplacementDecision(
                    held_ticker=pos.ticker,
                    action="trim",
                    reason=f"{pos.state}, no replacement, trim {int(sz['trim_pct']*100)}%",
                    blocked_by=blocked,
                    data_quality_flag=pos.data_quality_flag,
                    **sz,
                )
        row_dict = _decision_to_dict(d, pos)
        row_dict["weight"] = w
        decisions.append(row_dict)

    out = pd.DataFrame(decisions)
    if out.empty:
        return out

    # === Pass 5: concentrated floor safety (unchanged from v1) ===
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
                w = float(out.at[idx, "weight"])
                removed += w
                # Convert cash -> trim with proper sizing
                state = out.at[idx, "state"]
                sz = _sizing_for_trim(state, crisis_zone, w)
                out.at[idx, "action"] = "trim"
                out.at[idx, "trim_pct"] = sz["trim_pct"]
                out.at[idx, "weight_delta"] = sz["weight_delta"]
                out.at[idx, "target_weight_after"] = sz["target_weight_after"]
                out.at[idx, "cash_delta"] = sz["cash_delta"]
                prev = out.at[idx, "blocked_by"]
                tag = "concentrated_floor"
                out.at[idx, "blocked_by"] = f"{prev},{tag}" if prev else tag
    return out


def decision_summary(decisions: pd.DataFrame) -> dict:
    if decisions is None or decisions.empty:
        return {"total": 0, "by_action": {}}
    counts = decisions["action"].value_counts().to_dict()
    return {
        "total": int(len(decisions)),
        "by_action": {k: int(v) for k, v in counts.items()},
        "replacement_pairs": [
            {
                "out": r["ticker"],
                "in": r["candidate_ticker"],
                "delta": float(r["score_delta_sigma"]),
                "source": r.get("candidate_source"),
            }
            for _, r in decisions[decisions["action"] == "replace"].iterrows()
        ],
        "review_required_count": int((decisions["data_quality_flag"] != "ok").sum())
        if "data_quality_flag" in decisions.columns
        else 0,
        "total_cash_delta": float(decisions["cash_delta"].sum())
        if "cash_delta" in decisions.columns
        else 0.0,
    }
