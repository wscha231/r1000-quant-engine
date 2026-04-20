"""r1000 Quant Engine -- feature engineering module.

This module owns cross-sectional feature computation (industry / fundamental /
macro) extracted from r1000_top30_institutional.py during Refactor Phase A
Stage 3. Each function is pure (takes DataFrame, returns DataFrame with new
columns; no side effects except docstring-level warnings).

Stage 3a (this commit): industry relative strength + O'Neil leadership +
sub-industry leader/laggard + industry rotation. These 8 functions are
invoked in sequence by build_universe_monthly to attach ~24 Phase 2
columns per ticker per rebalance date.

Import discipline
-----------------
    r1000_config.py   (pure data, stdlib)
        ^
        |
    r1000_helpers.py  (pure helpers, numpy/pandas)
        ^
        |
    r1000_features.py (feature engineering, numpy/pandas/r1000_config)
        ^
        |
    r1000_top30_institutional.py  (main pipeline orchestration)
    r1000_data_collector.py
    r1000_operator.py
    r1000_portfolio_state.py

r1000_features.py may import from r1000_config.py and r1000_helpers.py,
but NEVER from the main engine.
"""
from __future__ import annotations

from typing import Any, Optional

import numpy as np
import pandas as pd

from r1000_config import (
    PHASE5_LEADER_LAGGARD_COLUMNS,
    YF_INDUSTRY_TO_GICS_GROUP,
)


# =====================================================================
# Industry feature engineering (Stage 3a, 2026-04-20)
# =====================================================================
# 8 functions invoked by build_universe_monthly to attach the Phase 2
# industry metadata + relative-strength + O'Neil leadership stack:
#
#   attach_industry_metadata
#     -> add_industry_relative_strength
#     -> compute_oneil_leadership_score
#     -> add_sub_industry_leader_laggard_signals
#     -> add_industry_rotation_signal
#
# map_yf_industry_to_group is a pure-lookup helper called during the
# attach step.  _demean_within_group and _group_mean_to_row are private
# computational helpers used by add_industry_relative_strength.

def map_yf_industry_to_group(industry: Any) -> str:
    """Fold a yfinance industry string into the coarse GICS-style bucket
    used by `YF_INDUSTRY_TO_GICS_GROUP`.  Returns 'Other' on miss / NaN.
    """
    if industry is None:
        return "Other"
    s = str(industry).strip()
    if not s or s.lower() in {"nan", "none"}:
        return "Other"
    upper = s.upper()
    for label, keys in YF_INDUSTRY_TO_GICS_GROUP:
        if not keys:
            continue
        for k in keys:
            if k in upper:
                return label
    return "Other"


def attach_industry_metadata(
    monthly: pd.DataFrame,
    industry_meta: pd.DataFrame,
) -> pd.DataFrame:
    """Merge the yfinance industry-metadata cache onto a monthly universe
    frame and derive the engine-side `industry` and `industry_group` columns.

    - `industry`         := preferred yfinance industry display, falling back
                            to the raw industry key, then 'Unknown'.
    - `industry_group`   := coarse GICS-style bucket from
                            `YF_INDUSTRY_TO_GICS_GROUP`.
    - `subindustry`      := alias of `industry` so downstream code that looks
                            for either name (e.g. `compute_sage_sector_labels`)
                            keeps working.
    """
    if monthly is None or monthly.empty:
        return monthly
    if industry_meta is None or industry_meta.empty:
        out = monthly.copy()
        for c in ("industry", "industry_group", "subindustry"):
            if c not in out.columns:
                out[c] = "Unknown"
        return out
    cols_keep = [c for c in ("ticker", "yf_industry", "yf_industry_disp", "yf_industry_key", "yf_sector", "yf_sector_key") if c in industry_meta.columns]
    meta = industry_meta[cols_keep].copy().drop_duplicates("ticker", keep="last")
    out = monthly.merge(meta, on="ticker", how="left")
    if "industry" not in out.columns or out["industry"].isna().all():
        out["industry"] = (
            out.get("yf_industry_disp")
            .fillna(out.get("yf_industry"))
            .fillna(out.get("yf_industry_key"))
            .fillna("Unknown")
            .astype(str)
        )
    else:
        out["industry"] = out["industry"].fillna(
            out.get("yf_industry_disp")
            .fillna(out.get("yf_industry"))
            .fillna(out.get("yf_industry_key"))
            .fillna("Unknown")
        ).astype(str)
    out["subindustry"] = out["industry"]
    out["industry_group"] = out["industry"].map(map_yf_industry_to_group).fillna("Other").astype(str)
    return out


# =====================================================================
# Phase 2.4: industry-level relative strength (O'Neil-style)
# =====================================================================
def _demean_within_group(
    df: pd.DataFrame,
    value_col: str,
    group_cols: list[str],
    out_col: str,
    min_group_size: int = 4,
) -> pd.DataFrame:
    """Subtract the within-group mean from `value_col` and write to `out_col`.

    Falls back to zero (rather than NaN) when the within-group sample is too
    small to be informative — this avoids spurious extreme RS values for
    micro-buckets like "Other" with two members.
    """
    if value_col not in df.columns:
        df[out_col] = 0.0
        return df
    vals = pd.to_numeric(df[value_col], errors="coerce")
    grp = df.groupby(group_cols, dropna=False)
    means = grp[value_col].transform(lambda x: pd.to_numeric(x, errors="coerce").mean())
    counts = grp[value_col].transform("count")
    demeaned = (vals - means).where(counts >= int(min_group_size), 0.0)
    df[out_col] = pd.to_numeric(demeaned, errors="coerce").fillna(0.0)
    return df


def _group_mean_to_row(
    df: pd.DataFrame,
    value_col: str,
    group_cols: list[str],
    out_col: str,
) -> pd.DataFrame:
    """Broadcast the within-group mean of `value_col` back to each row.  Useful
    for top-down "industry momentum" signals (rotation, leadership)."""
    if value_col not in df.columns:
        df[out_col] = 0.0
        return df
    vals = pd.to_numeric(df[value_col], errors="coerce")
    means = vals.groupby([df[c] for c in group_cols]).transform("mean")
    df[out_col] = pd.to_numeric(means, errors="coerce").fillna(0.0)
    return df


def add_industry_relative_strength(monthly: pd.DataFrame) -> pd.DataFrame:
    """Add industry- and industry-group-level relative-strength features.

    Produces:
      - `rs_industry_{1m,3m,6m,12m}`         : within-yfinance-industry RS
      - `rs_industry_group_{1m,3m,6m,12m}`   : within-coarse-bucket RS
      - `industry_mom_mean_{3m,6m,12m}`      : mean momentum of the industry
      - `industry_group_mom_mean_{3m,6m,12m}`: mean momentum of the bucket
      - `industry_breadth_above_ma200`       : fraction of industry above MA200
      - `industry_group_breadth_above_ma200` : same for coarse bucket
    """
    if monthly is None or monthly.empty:
        return monthly
    if "rebalance_date" not in monthly.columns:
        return monthly
    out = monthly.copy()
    if "industry" not in out.columns:
        out["industry"] = "Unknown"
    if "industry_group" not in out.columns:
        out["industry_group"] = "Other"

    horizon_cols = [
        ("mom_1m", "rs_industry_1m", "rs_industry_group_1m"),
        ("mom_3m", "rs_industry_3m", "rs_industry_group_3m"),
        ("mom_6m", "rs_industry_6m", "rs_industry_group_6m"),
        ("mom_12m", "rs_industry_12m", "rs_industry_group_12m"),
    ]
    for src, ind_col, grp_col in horizon_cols:
        out = _demean_within_group(
            out, src, ["rebalance_date", "industry"], ind_col, min_group_size=4
        )
        out = _demean_within_group(
            out, src, ["rebalance_date", "industry_group"], grp_col, min_group_size=8
        )

    # Industry-level momentum means (top-down rotation signals).
    for src, mean_col_ind, mean_col_grp in [
        ("mom_3m", "industry_mom_mean_3m", "industry_group_mom_mean_3m"),
        ("mom_6m", "industry_mom_mean_6m", "industry_group_mom_mean_6m"),
        ("mom_12m", "industry_mom_mean_12m", "industry_group_mom_mean_12m"),
    ]:
        out = _group_mean_to_row(out, src, ["rebalance_date", "industry"], mean_col_ind)
        out = _group_mean_to_row(out, src, ["rebalance_date", "industry_group"], mean_col_grp)

    if "price_above_ma200" in out.columns:
        out = _group_mean_to_row(
            out,
            "price_above_ma200",
            ["rebalance_date", "industry"],
            "industry_breadth_above_ma200",
        )
        out = _group_mean_to_row(
            out,
            "price_above_ma200",
            ["rebalance_date", "industry_group"],
            "industry_group_breadth_above_ma200",
        )
    else:
        out["industry_breadth_above_ma200"] = 0.0
        out["industry_group_breadth_above_ma200"] = 0.0
    return out


# =====================================================================
# Phase 2.5: O'Neil leadership score (industry-leader rank * group strength)
# =====================================================================
def compute_oneil_leadership_score(monthly: pd.DataFrame) -> pd.DataFrame:
    """O'Neil/IBD-style leadership score:
        leadership = industry_group_strength * within_industry_leader_rank

    The first factor captures the macro tailwind ("buy stocks in strong
    groups"); the second captures the within-industry pecking order ("buy the
    #1 or #2 name in that strong group").  Combining them surfaces the names
    that benefit from both effects — semiconductor leaders during a chip
    cycle, regional-bank leaders during a banking-stress recovery, etc.
    """
    if monthly is None or monthly.empty:
        return monthly
    if "rebalance_date" not in monthly.columns:
        return monthly
    out = monthly.copy()
    if "industry" not in out.columns:
        out["industry"] = "Unknown"
    if "industry_group" not in out.columns:
        out["industry_group"] = "Other"

    # Group strength: combine medium-term industry-group momentum mean with
    # breadth and our existing benchmark RS.
    grp_mom = pd.to_numeric(out.get("industry_group_mom_mean_6m"), errors="coerce").fillna(0.0)
    grp_breadth = pd.to_numeric(out.get("industry_group_breadth_above_ma200"), errors="coerce").fillna(0.0)
    grp_strength = (grp_mom + 0.40 * grp_breadth)
    grp_strength_z = grp_strength.groupby(out["rebalance_date"]).transform(
        lambda x: (x - x.mean()) / (x.std(ddof=0) + 1e-8)
    ).fillna(0.0)
    out["industry_group_strength_score"] = grp_strength_z

    # Within-industry leader rank: rank by mom_6m and rs_benchmark_6m.
    def _rank_within(col: str) -> pd.Series:
        if col not in out.columns:
            return pd.Series(0.0, index=out.index, dtype=float)
        s = pd.to_numeric(out[col], errors="coerce")
        # rank(pct=True) returns [0..1]; we want leaders at +1 and laggards at -1.
        ranks = s.groupby([out["rebalance_date"], out["industry"]]).rank(
            pct=True, ascending=True, method="average"
        )
        return (ranks * 2.0 - 1.0).fillna(0.0)

    leader_rank_mom = _rank_within("mom_6m")
    leader_rank_rs = _rank_within("rs_benchmark_6m")
    leader_rank_eps = _rank_within("eps_growth_yoy")
    out["industry_within_leader_rank"] = (
        0.40 * leader_rank_mom + 0.40 * leader_rank_rs + 0.20 * leader_rank_eps
    ).fillna(0.0)

    # Final O'Neil leadership score.  Multiplied form so a strong leader in
    # a weak group is muted — exactly what O'Neil's CAN SLIM "L" leg
    # demands.  We add a small additive floor so an exceptional within-group
    # leader still shows up in a neutral-strength group.
    multiplicative = grp_strength_z.clip(lower=-2.5, upper=2.5) * out["industry_within_leader_rank"]
    additive_floor = 0.30 * out["industry_within_leader_rank"]
    out["oneil_leadership_score"] = (multiplicative + additive_floor).clip(lower=-3.0, upper=3.0)
    return out


# =====================================================================
# Phase 5: sub-industry leader/laggard pair signals (PHASE_ROADMAP §2.5).
# =====================================================================
def add_sub_industry_leader_laggard_signals(
    monthly: pd.DataFrame,
    min_group_size: int = 6,
    gap_threshold: float = 0.8,
) -> pd.DataFrame:
    """Within each (rebalance_date, industry_group), score:
      - `industry_leader_gap`: (top-quartile mean - median) / std.
        Large gap = clear leader separation; small gap = homogeneous group.
      - `industry_leader_bonus_score`: positive multiplier for top-quartile
        names WHEN industry_group is in the upper half of
        `industry_group_strength_score` AND the gap exceeds `gap_threshold`.
      - `industry_laggard_penalty_score`: mirror negative multiplier for
        bottom-quartile names in the same strong group.

    Groups with fewer than `min_group_size` names are skipped entirely
    (all three columns set to 0.0 for rows in that group).

    The within-group percentile ranking reuses `industry_within_leader_rank`
    (already computed upstream in `compute_oneil_leadership_score`) if
    present, or falls back to a freshly-ranked composite of mom_6m +
    rs_benchmark_6m so the function is robust to call-order changes.
    """
    required = [
        "rebalance_date", "industry_group", "industry_group_strength_score",
    ]
    # Defensive: when this runs with Phase 2 disabled some columns may be
    # missing. Return zero-filled columns without raising so downstream
    # code still finds the expected schema.
    if not all(c in monthly.columns for c in required):
        for col in PHASE5_LEADER_LAGGARD_COLUMNS:
            monthly[col] = 0.0
        return monthly

    out = monthly.copy()
    # 1. Get the within-group leader rank. Prefer the existing column;
    #    fall back to an on-the-fly rank if missing.
    if "industry_within_leader_rank" in out.columns:
        leader_rank = pd.to_numeric(out["industry_within_leader_rank"], errors="coerce")
    else:
        mom = pd.to_numeric(out.get("mom_6m", 0.0), errors="coerce").fillna(0.0)
        rs = pd.to_numeric(out.get("rs_benchmark_6m", 0.0), errors="coerce").fillna(0.0)
        composite = 0.60 * mom + 0.40 * rs
        leader_rank = (
            composite
            .groupby([out["rebalance_date"], out["industry_group"].astype(str)])
            .rank(pct=True, method="average", ascending=True)
            .mul(2.0)
            .sub(1.0)
        )
    out["_p5_leader_rank"] = leader_rank.fillna(0.0)

    # 2. Per-group stats (count, top-quartile mean, median, std) to
    #    compute the leader gap.
    grp_keys = [out["rebalance_date"], out["industry_group"].astype(str)]
    grp_size = out["_p5_leader_rank"].groupby(grp_keys).transform("size")
    # Top-quartile mean: mean over rows where leader_rank >= +0.5
    # (since rank is in [-1, +1], >=+0.5 is the top quartile).
    top_q_mask = (out["_p5_leader_rank"] >= 0.5).astype(float)
    top_q_sum = (out["_p5_leader_rank"] * top_q_mask).groupby(grp_keys).transform("sum")
    top_q_count = top_q_mask.groupby(grp_keys).transform("sum").clip(lower=1.0)
    top_q_mean = top_q_sum / top_q_count
    grp_median = out["_p5_leader_rank"].groupby(grp_keys).transform("median")
    grp_std = out["_p5_leader_rank"].groupby(grp_keys).transform("std").fillna(0.0).clip(lower=1e-6)
    leader_gap_raw = (top_q_mean - grp_median) / grp_std
    # Zero out groups too small to trust, and NaN edges.
    leader_gap = pd.Series(
        np.where(grp_size >= int(min_group_size), leader_gap_raw.fillna(0.0), 0.0),
        index=out.index,
        dtype=float,
    ).clip(lower=0.0, upper=4.0)  # gap is definitionally non-negative, cap for safety
    out["industry_leader_gap"] = leader_gap

    # 3. Strong-group gate: only fire bonus/penalty when the group is
    #    in the upper half of industry_group_strength_score (>= 0) AND
    #    the leader gap exceeds the threshold.
    group_strength = pd.to_numeric(out["industry_group_strength_score"], errors="coerce").fillna(0.0)
    strong_group = (group_strength >= 0.0).astype(float)
    gap_strong = (leader_gap >= float(gap_threshold)).astype(float)
    active = strong_group * gap_strong

    # 4. Leader bonus: top-quartile rows in active groups get a positive
    #    score proportional to both the leader rank AND the gap strength.
    top_q_row = (out["_p5_leader_rank"] >= 0.5).astype(float)
    bot_q_row = (out["_p5_leader_rank"] <= -0.5).astype(float)
    # Normalise gap into [0, 1] range for multiplier construction
    gap_strength = (leader_gap / 2.0).clip(lower=0.0, upper=1.0)

    bonus = (
        active * top_q_row * (0.60 * out["_p5_leader_rank"].clip(lower=0.0, upper=1.0)
                              + 0.40 * gap_strength)
    )
    penalty = (
        active * bot_q_row * (0.60 * out["_p5_leader_rank"].clip(lower=-1.0, upper=0.0).abs()
                              + 0.40 * gap_strength)
    )
    out["industry_leader_bonus_score"] = bonus.fillna(0.0).clip(lower=0.0, upper=1.0)
    out["industry_laggard_penalty_score"] = penalty.fillna(0.0).clip(lower=0.0, upper=1.0)

    out.drop(columns=["_p5_leader_rank"], errors="ignore", inplace=True)
    return out


# =====================================================================
# Phase 2.6: Industry rotation signal (rising-from-bottom industries)
# =====================================================================
def add_industry_rotation_signal(monthly: pd.DataFrame) -> pd.DataFrame:
    """Industry-rotation signal: which industries are bottoming and now
    accelerating.  Targets the user's "buy the bottom-out turnaround
    industry" mandate by combining:
      (a) `industry_group_mom_mean_3m` rising relative to the broader market;
      (b) the change in 3m mean (i.e. industry-level acceleration);
      (c) breadth turning back above 50%.
    """
    if monthly is None or monthly.empty:
        return monthly
    if "rebalance_date" not in monthly.columns or "industry_group" not in monthly.columns:
        return monthly
    out = monthly.copy()

    # Universe-mean momentum at each rebalance — used as "the market".
    market_mom_3m = pd.to_numeric(out.get("mom_3m"), errors="coerce").groupby(
        out["rebalance_date"]
    ).transform("mean").fillna(0.0)
    market_mom_6m = pd.to_numeric(out.get("mom_6m"), errors="coerce").groupby(
        out["rebalance_date"]
    ).transform("mean").fillna(0.0)

    grp_mom_3m = pd.to_numeric(out.get("industry_group_mom_mean_3m"), errors="coerce").fillna(0.0)
    grp_mom_6m = pd.to_numeric(out.get("industry_group_mom_mean_6m"), errors="coerce").fillna(0.0)

    # Industry beating the market on 3m but lagging on 6m → fresh rotation up.
    rotation_3m_lead = (grp_mom_3m - market_mom_3m).clip(-0.50, 0.50)
    catch_up_signal = ((grp_mom_3m > market_mom_3m) & (grp_mom_6m < market_mom_6m)).astype(float)

    # Industry-level breadth recovering above 50%.
    grp_breadth = pd.to_numeric(out.get("industry_group_breadth_above_ma200"), errors="coerce").fillna(0.0)
    breadth_recovery = ((grp_breadth >= 0.50) & (grp_breadth <= 0.80)).astype(float)

    # Industry acceleration: short-term mean momentum versus medium-term mean.
    grp_accel = (grp_mom_3m - grp_mom_6m).clip(-0.50, 0.50)

    rotation = (
        0.40 * rotation_3m_lead
        + 0.30 * grp_accel
        + 0.20 * catch_up_signal
        + 0.10 * breadth_recovery
    )
    # Standardise per rebalance so the signal is comparable to other z-scores.
    rotation_z = rotation.groupby(out["rebalance_date"]).transform(
        lambda x: (x - x.mean()) / (x.std(ddof=0) + 1e-8)
    ).fillna(0.0)
    out["industry_rotation_signal"] = rotation_z.clip(lower=-3.0, upper=3.0)
    return out

__all__ = [
    "map_yf_industry_to_group",
    "attach_industry_metadata",
    "_demean_within_group",
    "_group_mean_to_row",
    "add_industry_relative_strength",
    "compute_oneil_leadership_score",
    "add_sub_industry_leader_laggard_signals",
    "add_industry_rotation_signal",
]
