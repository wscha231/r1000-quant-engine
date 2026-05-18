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

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

import numpy as np
import pandas as pd
import requests
import yfinance as yf

from r1000_helpers import (
    alpha_vantage_pause_seconds,
    cache_live_file,
    LIVE_CACHE_ALPHA_PRESERVE_FIELDS,
    normalize_ticker,
    cache_live_statement_file,
    cross_sectional_robust_z,
    effective_alpha_vantage_refresh_tickers,
    effective_latest_statement_refresh_days,
    effective_latest_statement_repair_tickers,
    is_cache_fresh,
    is_valid_ticker,
    log,
    normalize_cik_series,
    numeric_series_or_default,
    phase_is_enabled,
    robust_z,
    row_mean,
    safe_float,
    to_yf_symbol,
    winsorize,
)
from r1000_config import (
    BENCHMARK_RELATIVE_COLUMNS,
    CORE_FUNDAMENTAL_COLUMNS,
    CRISIS_SECTOR_BENEFICIARIES,
    DYNAMIC_LEADER_COLUMNS,
    EngineConfig,
    FUND_TTM_FALLBACK_COLUMNS,
    LATEST_ONLY_SIGNAL_COLUMNS,
    MACRO_REGIME_COLUMNS,
    MARKET_ADAPTATION_COLUMNS,
    MOAT_PROXY_COLUMNS,
    PHASE5_LEADER_LAGGARD_COLUMNS,
    PHASE9_C3_TURNAROUND_COLUMNS,
    PILLAR_SCORE_COLUMNS,
    REGIME_ROTATION_COLUMNS,
    SAGE_SECTOR_MAP,
    YF_INDUSTRY_TO_GICS_GROUP,
    YF_QUARTERLY_COL_MAP,
    PHASE21_STYLE_REGIME_COLUMNS,
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

# =====================================================================
# Alpha Vantage + yfinance data fetchers + fundamental trend features
# (Stage 3b, 2026-04-20)
# =====================================================================
# 28 functions covering:
#  - Alpha Vantage HTTP calls + response parsing + statement snapshots
#    + OVERVIEW / earnings estimates / balance / cash-flow reports
#  - yfinance live fundamentals + quarterly statements + holder tables
#    + insider transactions
#  - Latest-statement repair bridging cached SEC fundamentals with
#    Alpha-Vantage snapshots when SEC coverage gaps
#  - Fundamental trend feature computation + merge into monthly frame
#  - SAGE sector label assignment from YF industry strings

def load_cached_json_if_any(path: Path) -> dict[str, Any]:
    try:
        if path.exists():
            payload = json.loads(path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}
    return {}


def has_present_value(x: Any) -> bool:
    if x is None:
        return False
    if isinstance(x, str) and x.strip() == "":
        return False
    try:
        return not pd.isna(x)
    except Exception:
        return True


def preserve_cached_fields(
    base: dict[str, Any],
    cached: dict[str, Any],
    fields: Iterable[str],
) -> dict[str, Any]:
    out = dict(base)
    if not cached:
        return out
    for field in fields:
        if not has_present_value(out.get(field)) and has_present_value(cached.get(field)):
            out[field] = cached[field]
    return out


def statement_snapshot_has_payload(snapshot: dict[str, Any]) -> bool:
    payload_fields = [
        "av_stmt_assets",
        "av_stmt_liabilities",
        "av_stmt_shares",
        "av_stmt_revenues",
        "av_stmt_revenues_ttm",
        "av_stmt_gross_profit_ttm",
        "av_stmt_op_income_ttm",
        "av_stmt_net_income_ttm",
        "av_stmt_ocf_ttm",
        "av_stmt_capex_ttm",
        "av_stmt_quarter_count",
    ]
    return any(has_present_value(snapshot.get(field)) for field in payload_fields)


def compute_flow_ttm_with_cum_fallback(
    group: pd.DataFrame,
    field_name: str,
) -> tuple[pd.Series, pd.Series]:
    flow = (
        pd.to_numeric(group[field_name], errors="coerce")
        if field_name in group.columns
        else pd.Series(np.nan, index=group.index, dtype=float)
    )
    base_ttm = flow.rolling(4, min_periods=4).sum()
    fallback_ttm = pd.Series(np.nan, index=group.index, dtype=float)
    used_fallback = pd.Series(0.0, index=group.index, dtype=float)
    cum_col = f"{field_name}_cum_value"
    if cum_col not in group.columns or "quarter_index" not in group.columns:
        return base_ttm, used_fallback

    q_idx = pd.to_numeric(group["quarter_index"], errors="coerce")
    cum = pd.to_numeric(group[cum_col], errors="coerce")
    q_idx_lag4 = q_idx.shift(4)
    same_q_prev_year = cum.shift(4).where(q_idx_lag4.eq(q_idx))
    prev_annual = cum.where(q_idx.eq(4)).ffill().shift(1)

    q4_mask = q_idx.eq(4) & cum.notna()
    fallback_ttm.loc[q4_mask] = cum.loc[q4_mask]

    ytd_mask = q_idx.isin([1, 2, 3]) & cum.notna() & prev_annual.notna() & same_q_prev_year.notna()
    fallback_ttm.loc[ytd_mask] = prev_annual.loc[ytd_mask] + cum.loc[ytd_mask] - same_q_prev_year.loc[ytd_mask]

    result = base_ttm.where(base_ttm.notna(), fallback_ttm)
    used_mask = base_ttm.isna() & result.notna()
    used_fallback.loc[used_mask] = 1.0
    return result, used_fallback


def alpha_vantage_get(function: str, symbol: str, api_key: str) -> dict[str, Any]:
    """Alpha Vantage API call. Daily rate limit (25/day) → immediate fail, no retry."""
    url = "https://www.alphavantage.co/query"
    params = {
        "function": function,
        "symbol": symbol,
        "apikey": api_key,
    }
    try:
        r = requests.get(url, params=params, timeout=60)
        r.raise_for_status()
        payload = r.json()
        if isinstance(payload, dict) and (payload.get("Note") or payload.get("Information")):
            msg = payload.get("Note") or payload.get("Information")
            log(f"[WARN] Alpha Vantage daily limit reached for {symbol} — skipping remaining AV calls.")
            return {}
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def yf_table_or_empty(tk: Any, attr_name: str) -> pd.DataFrame:
    try:
        raw = getattr(tk, attr_name, None)
    except Exception:
        return pd.DataFrame()
    try:
        if callable(raw):
            raw = raw()
    except Exception:
        return pd.DataFrame()
    if raw is None:
        return pd.DataFrame()
    if isinstance(raw, pd.DataFrame):
        return raw.copy()
    if isinstance(raw, pd.Series):
        return raw.to_frame().T
    if isinstance(raw, list):
        return pd.DataFrame(raw)
    if isinstance(raw, dict):
        return pd.DataFrame([raw])
    return pd.DataFrame()


def normalize_table_columns(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy()
    out.columns = [
        re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", str(c).strip().lower())).strip("_")
        for c in out.columns
    ]
    return out


def sum_first_numeric_column(df: pd.DataFrame, candidates: list[str]) -> float:
    for c in candidates:
        if c in df.columns:
            vals = pd.to_numeric(df[c], errors="coerce")
            if vals.notna().any():
                return float(vals.sum())
    return np.nan


def summarize_holder_table(df: pd.DataFrame, prefix: str) -> dict[str, Any]:
    out = {
        f"{prefix}_holders_count": np.nan,
        f"{prefix}_holders_shares": np.nan,
        f"{prefix}_holders_value": np.nan,
    }
    d = normalize_table_columns(df)
    if d.empty:
        return out
    out[f"{prefix}_holders_count"] = int(len(d))
    out[f"{prefix}_holders_shares"] = sum_first_numeric_column(
        d,
        ["shares", "shares_held", "position", "position_shares"],
    )
    out[f"{prefix}_holders_value"] = sum_first_numeric_column(
        d,
        ["value", "value_held", "market_value"],
    )
    return out


def summarize_insider_transactions(df: pd.DataFrame) -> dict[str, Any]:
    out = {
        "insider_txn_count": np.nan,
        "insider_buy_shares": np.nan,
        "insider_sell_shares": np.nan,
        "insider_net_shares": np.nan,
        "insider_buy_ratio": np.nan,
    }
    d = normalize_table_columns(df)
    if d.empty:
        return out

    shares = pd.Series(np.nan, index=d.index, dtype=float)
    for c in ["shares", "shares_traded", "shares_delta", "amount"]:
        if c in d.columns:
            shares = pd.to_numeric(d[c], errors="coerce")
            if shares.notna().any():
                break

    text_cols = [c for c in ["transaction", "transaction_type", "text", "description", "type"] if c in d.columns]
    if text_cols:
        txt = d[text_cols].fillna("").astype(str).agg(" ".join, axis=1).str.lower()
        buy_mask = txt.str.contains(r"buy|purchase|acquir", regex=True, na=False)
        sell_mask = txt.str.contains(r"sell|sale|dispos", regex=True, na=False)
    else:
        buy_mask = shares > 0
        sell_mask = shares < 0

    out["insider_txn_count"] = int(len(d))
    if shares.notna().any():
        buy_shares = float(shares.where(buy_mask, 0.0).clip(lower=0.0).sum())
        sell_shares = float((-shares.where(sell_mask, 0.0)).clip(lower=0.0).sum())
        net_shares = float(shares.fillna(0.0).sum())
        out["insider_buy_shares"] = buy_shares
        out["insider_sell_shares"] = sell_shares
        out["insider_net_shares"] = net_shares
    buy_count = int(buy_mask.fillna(False).sum())
    out["insider_buy_ratio"] = float(buy_count / max(int(len(d)), 1))
    return out


def fetch_yf_live_fundamentals(ticker: str) -> dict[str, Any]:
    out = {"ticker": ticker}
    tk = None
    try:
        tk = yf.Ticker(to_yf_symbol(ticker))
        info = tk.info or {}
    except Exception:
        info = {}

    out["forward_pe"] = safe_float(info.get("forwardPE"))
    out["peg_ratio"] = safe_float(info.get("pegRatio"))
    out["trailing_pe"] = safe_float(info.get("trailingPE"))
    out["price_to_sales"] = safe_float(info.get("priceToSalesTrailing12Months"))
    out["market_cap_live"] = safe_float(info.get("marketCap"))
    out["target_mean_price"] = safe_float(info.get("targetMeanPrice"))
    out["target_median_price"] = safe_float(info.get("targetMedianPrice"))
    out["recommendation_mean"] = safe_float(info.get("recommendationMean"))
    out["earnings_growth"] = safe_float(info.get("earningsGrowth"))
    out["revenue_growth"] = safe_float(info.get("revenueGrowth"))
    out["gross_margins"] = safe_float(info.get("grossMargins"))
    out["operating_margins"] = safe_float(info.get("operatingMargins"))
    out["return_on_equity_live"] = safe_float(info.get("returnOnEquity"))
    out["free_cashflow_live"] = safe_float(info.get("freeCashflow"))
    out["current_price_live"] = safe_float(info.get("currentPrice"))
    out.update(summarize_holder_table(yf_table_or_empty(tk, "institutional_holders"), "institutional"))
    out.update(summarize_holder_table(yf_table_or_empty(tk, "mutualfund_holders"), "mutualfund"))
    out.update(summarize_insider_transactions(yf_table_or_empty(tk, "insider_transactions")))
    out["updated_at"] = datetime.utcnow().isoformat(timespec="seconds")
    return out


def fetch_yfinance_quarterly_statements(ticker: str) -> pd.DataFrame:
    """Fetch quarterly financial statements from yfinance as SEC data supplement."""
    try:
        tk = yf.Ticker(to_yf_symbol(ticker))
    except Exception:
        return pd.DataFrame()

    rows: dict[pd.Timestamp, dict[str, float]] = {}

    def _extract(stmt, label: str) -> None:
        if stmt is None or (hasattr(stmt, "empty") and stmt.empty):
            return
        for col_date in stmt.columns:
            dt = pd.Timestamp(col_date).tz_localize(None) if hasattr(pd.Timestamp(col_date), "tz") and pd.Timestamp(col_date).tz else pd.Timestamp(col_date)
            if dt not in rows:
                rows[dt] = {}
            for idx_name in stmt.index:
                mapped = YF_QUARTERLY_COL_MAP.get(str(idx_name))
                if mapped and mapped not in rows[dt]:
                    val = stmt.loc[idx_name, col_date]
                    if pd.notna(val):
                        rows[dt][mapped] = float(val)

    try:
        _extract(tk.quarterly_income_stmt, "income")
    except Exception:
        pass
    try:
        _extract(tk.quarterly_balance_sheet, "balance")
    except Exception:
        pass
    try:
        _extract(tk.quarterly_cashflow, "cashflow")
    except Exception:
        pass

    if not rows:
        return pd.DataFrame()

    records = []
    for dt, fields in sorted(rows.items()):
        rec = {"period": dt, "accepted": dt + pd.Timedelta(days=45)}
        rec.update(fields)
        records.append(rec)
    df = pd.DataFrame(records)
    if "capex" in df.columns:
        df["capex"] = df["capex"].abs()
    return df


def fetch_alpha_vantage_overview(ticker: str, api_key: str) -> dict[str, Any]:
    raw = alpha_vantage_get("OVERVIEW", ticker, api_key)
    if not raw or "Symbol" not in raw:
        return {"ticker": ticker}

    return {
        "ticker": ticker,
        "av_forward_pe": safe_float(raw.get("ForwardPE")),
        "av_peg_ratio": safe_float(raw.get("PEGRatio")),
        "av_trailing_pe": safe_float(raw.get("PERatio")),
        "av_price_to_sales": safe_float(raw.get("PriceToSalesRatioTTM")),
        "av_ev_to_ebitda": safe_float(raw.get("EVToEBITDA")),
        "av_profit_margin": safe_float(raw.get("ProfitMargin")),
        "av_operating_margin": safe_float(raw.get("OperatingMarginTTM")),
        "av_return_on_equity": safe_float(raw.get("ReturnOnEquityTTM")),
        "av_quarterly_earnings_growth_yoy": safe_float(raw.get("QuarterlyEarningsGrowthYOY")),
        "av_quarterly_revenue_growth_yoy": safe_float(raw.get("QuarterlyRevenueGrowthYOY")),
        "updated_at": datetime.utcnow().isoformat(timespec="seconds"),
    }


def fetch_alpha_vantage_earnings_estimates(ticker: str, api_key: str) -> dict[str, Any]:
    raw = alpha_vantage_get("EARNINGS_ESTIMATES", ticker, api_key)
    if not raw:
        return {"ticker": ticker}

    annual = raw.get("annualEstimates", []) or []
    quarterly = raw.get("quarterlyEstimates", []) or []
    out = {"ticker": ticker}

    if quarterly:
        q0 = quarterly[0]
        out["eps_est_q_next"] = safe_float(q0.get("estimatedEPS"))
        out["rev_est_q_next"] = safe_float(q0.get("estimatedRevenue"))
        hist = q0.get("estimatedEPSAvg") or q0.get("estimatedEPS")
        out["eps_revision_proxy"] = safe_float(hist)

    if len(annual) >= 1:
        out["eps_est_fy1"] = safe_float(annual[0].get("estimatedEPS"))
        out["rev_est_fy1"] = safe_float(annual[0].get("estimatedRevenue"))
    if len(annual) >= 2:
        out["eps_est_fy2"] = safe_float(annual[1].get("estimatedEPS"))
        out["rev_est_fy2"] = safe_float(annual[1].get("estimatedRevenue"))

    out["updated_at"] = datetime.utcnow().isoformat(timespec="seconds")
    return out


def alpha_vantage_reports_frame(raw: dict[str, Any], key: str) -> pd.DataFrame:
    reports = raw.get(key, []) if isinstance(raw, dict) else []
    if not isinstance(reports, list) or not reports:
        return pd.DataFrame()
    df = pd.DataFrame(reports)
    if "fiscalDateEnding" in df.columns:
        df["fiscalDateEnding"] = pd.to_datetime(df["fiscalDateEnding"], errors="coerce")
        df = df.sort_values("fiscalDateEnding", ascending=False)
    return df.reset_index(drop=True)


def first_numeric_from_report(df: pd.DataFrame, candidates: list[str]) -> float:
    if df is None or df.empty:
        return np.nan
    row = df.iloc[0]
    for c in candidates:
        if c in df.columns:
            val = safe_float(row.get(c))
            if pd.notna(val):
                return float(val)
    return np.nan


def sum_latest_numeric_reports(
    df: pd.DataFrame,
    candidates: list[str],
    count: int = 4,
    abs_value: bool = False,
) -> float:
    if df is None or df.empty or len(df) < count:
        return np.nan
    vals = []
    for _, row in df.head(count).iterrows():
        val = np.nan
        for c in candidates:
            if c in df.columns:
                val = safe_float(row.get(c))
                if pd.notna(val):
                    break
        vals.append(val)
    s = pd.Series(vals, dtype=float)
    if s.notna().sum() < count:
        return np.nan
    if abs_value:
        s = s.abs()
    return float(s.sum())


def yoy_latest_numeric_reports(df: pd.DataFrame, candidates: list[str]) -> float:
    if df is None or df.empty or len(df) < 5:
        return np.nan
    latest = first_numeric_from_report(df.head(1), candidates)
    prior = first_numeric_from_report(df.iloc[4:5], candidates)
    if pd.isna(latest) or pd.isna(prior) or prior == 0:
        return np.nan
    return float(latest / prior - 1.0)


def fetch_alpha_vantage_statement_snapshot(
    ticker: str,
    api_key: str,
    pause_seconds: float = 0.15,
) -> dict[str, Any]:
    out = {"ticker": ticker}
    if not api_key or not ticker:
        return out

    income_raw = alpha_vantage_get("INCOME_STATEMENT", ticker, api_key)
    time.sleep(max(float(pause_seconds), 0.0))
    balance_raw = alpha_vantage_get("BALANCE_SHEET", ticker, api_key)
    time.sleep(max(float(pause_seconds), 0.0))
    cash_raw = alpha_vantage_get("CASH_FLOW", ticker, api_key)

    income_q = alpha_vantage_reports_frame(income_raw, "quarterlyReports")
    balance_q = alpha_vantage_reports_frame(balance_raw, "quarterlyReports")
    cash_q = alpha_vantage_reports_frame(cash_raw, "quarterlyReports")

    revenue_cols = [
        "totalRevenue",
        "revenueFromContractWithCustomerExcludingAssessedTax",
        "revenueFromContractWithCustomerIncludingAssessedTax",
    ]
    cost_cols = [
        "costOfRevenue",
        "costOfGoodsSold",
        "costOfGoodsAndServicesSold",
        "costOfSales",
    ]
    gross_cols = ["grossProfit"]
    op_income_cols = ["operatingIncome", "operatingIncomeLoss"]
    net_income_cols = ["netIncome"]
    ocf_cols = ["operatingCashflow", "cashflowFromOperations"]
    capex_cols = ["capitalExpenditures", "paymentsForCapitalImprovements"]
    assets_cols = ["totalAssets"]
    liabilities_cols = ["totalLiabilities", "totalLiabilitiesNetMinorityInterest"]
    shares_cols = ["commonStockSharesOutstanding", "commonStockSharesIssued"]

    latest_revenue = first_numeric_from_report(income_q, revenue_cols)
    latest_cost = first_numeric_from_report(income_q, cost_cols)
    latest_gross = first_numeric_from_report(income_q, gross_cols)
    if pd.isna(latest_gross) and pd.notna(latest_revenue) and pd.notna(latest_cost):
        latest_gross = latest_revenue - latest_cost

    revenue_ttm = sum_latest_numeric_reports(income_q, revenue_cols, count=4)
    cost_ttm = sum_latest_numeric_reports(income_q, cost_cols, count=4, abs_value=True)
    gross_ttm = sum_latest_numeric_reports(income_q, gross_cols, count=4)
    if pd.isna(gross_ttm) and pd.notna(revenue_ttm) and pd.notna(cost_ttm):
        gross_ttm = revenue_ttm - cost_ttm

    op_income_ttm = sum_latest_numeric_reports(income_q, op_income_cols, count=4)
    net_income_ttm = sum_latest_numeric_reports(income_q, net_income_cols, count=4)
    ocf_ttm = sum_latest_numeric_reports(cash_q, ocf_cols, count=4)
    capex_ttm = sum_latest_numeric_reports(cash_q, capex_cols, count=4, abs_value=True)

    out.update(
        {
            "av_stmt_assets": first_numeric_from_report(balance_q, assets_cols),
            "av_stmt_liabilities": first_numeric_from_report(balance_q, liabilities_cols),
            "av_stmt_shares": first_numeric_from_report(balance_q, shares_cols),
            "av_stmt_revenues": latest_revenue,
            "av_stmt_cost_of_revenue": latest_cost,
            "av_stmt_gross_profit": latest_gross,
            "av_stmt_op_income": first_numeric_from_report(income_q, op_income_cols),
            "av_stmt_net_income": first_numeric_from_report(income_q, net_income_cols),
            "av_stmt_ocf": first_numeric_from_report(cash_q, ocf_cols),
            "av_stmt_capex": abs(first_numeric_from_report(cash_q, capex_cols)) if pd.notna(first_numeric_from_report(cash_q, capex_cols)) else np.nan,
            "av_stmt_revenues_ttm": revenue_ttm,
            "av_stmt_cost_of_revenue_ttm": cost_ttm,
            "av_stmt_gross_profit_ttm": gross_ttm,
            "av_stmt_op_income_ttm": op_income_ttm,
            "av_stmt_net_income_ttm": net_income_ttm,
            "av_stmt_ocf_ttm": ocf_ttm,
            "av_stmt_capex_ttm": capex_ttm,
            "av_stmt_revenue_growth_yoy_actual": yoy_latest_numeric_reports(income_q, revenue_cols),
            "av_stmt_earnings_growth_yoy_actual": yoy_latest_numeric_reports(income_q, net_income_cols),
            "av_stmt_quarter_count": float(max(len(income_q), len(balance_q), len(cash_q))),
            "av_stmt_updated_at": datetime.utcnow().isoformat(timespec="seconds"),
        }
    )
    return out


def load_or_fetch_alpha_vantage_statement_snapshot(
    cfg: EngineConfig,
    paths: dict[str, Path],
    ticker: str,
) -> dict[str, Any]:
    p = cache_live_statement_file(paths, ticker)
    existing = load_cached_json_if_any(p)
    refresh_days = effective_latest_statement_refresh_days(cfg)
    if is_cache_fresh(p, refresh_days):
        return existing or {"ticker": ticker}

    if not cfg.alpha_vantage_api_key:
        return existing or {"ticker": ticker}

    data = fetch_alpha_vantage_statement_snapshot(
        ticker,
        cfg.alpha_vantage_api_key,
        pause_seconds=alpha_vantage_pause_seconds(cfg, statement=True),
    )
    data["ticker"] = ticker
    if not statement_snapshot_has_payload(data):
        if existing:
            try:
                p.write_text(json.dumps(existing), encoding="utf-8")
            except Exception:
                pass
            return existing
        return data
    try:
        p.write_text(json.dumps(data), encoding="utf-8")
    except Exception:
        pass
    return data


def repair_latest_statement_fundamentals(
    cfg: EngineConfig,
    paths: dict[str, Path],
    df: pd.DataFrame,
) -> pd.DataFrame:
    d = df.copy()
    existing_stmt_cols = [c for c in d.columns if str(c).startswith("av_stmt_")]
    if existing_stmt_cols:
        d = d.drop(columns=existing_stmt_cols, errors="ignore")
    d["latest_statement_repair_used"] = False
    if (
        d.empty
        or not bool(getattr(cfg, "latest_statement_repair_enabled", True))
        or not cfg.alpha_vantage_api_key
        or "ticker" not in d.columns
    ):
        return d

    limit = effective_latest_statement_repair_tickers(cfg)
    if limit <= 0:
        return d

    order_cols = [c for c in ["score", "dollar_vol_20d", "market_cap_live", "mktcap"] if c in d.columns]
    ranked = d.copy()
    for c in order_cols:
        ranked[c] = pd.to_numeric(ranked[c], errors="coerce")
    if "score" in ranked.columns:
        ranked = ranked.sort_values(["score", "dollar_vol_20d"], ascending=[False, False], na_position="last")
    elif "dollar_vol_20d" in ranked.columns:
        ranked = ranked.sort_values(["dollar_vol_20d"], ascending=[False], na_position="last")
    repair_missing_cols = [
        "assets",
        "liabilities",
        "shares",
        "revenues_ttm",
        "gross_profit_ttm",
        "op_income_ttm",
        "net_income_ttm",
        "ocf_ttm",
        "capex_ttm",
        "revenue_growth_final",
        "earnings_growth_final",
    ]
    present_repair_cols = [c for c in repair_missing_cols if c in ranked.columns]
    if present_repair_cols:
        ranked["statement_missing_count"] = pd.concat(
            [pd.to_numeric(ranked[c], errors="coerce").isna().rename(c) for c in present_repair_cols],
            axis=1,
        ).sum(axis=1)
        ranked = ranked[ranked["statement_missing_count"] > 0].copy()
        secondary_sort_cols = ["statement_missing_count"]
        secondary_sort_asc = [False]
        for c in ["score", "dollar_vol_20d", "market_cap_live", "mktcap", "mom_6m"]:
            if c in ranked.columns:
                secondary_sort_cols.append(c)
                secondary_sort_asc.append(False)
        ranked = ranked.sort_values(
            secondary_sort_cols,
            ascending=secondary_sort_asc,
            na_position="last",
        )
    if ranked.empty:
        return d
    repair_tickers = (
        ranked["ticker"].dropna().astype(str).str.upper().drop_duplicates().head(limit).tolist()
    )
    rows = []
    for t in repair_tickers:
        rows.append(load_or_fetch_alpha_vantage_statement_snapshot(cfg, paths, t))
        time.sleep(0.05)
    repair_df = pd.DataFrame(rows)
    if repair_df.empty:
        return d

    d = d.merge(repair_df, on="ticker", how="left")
    fill_pairs = [
        ("assets", "av_stmt_assets"),
        ("liabilities", "av_stmt_liabilities"),
        ("shares", "av_stmt_shares"),
        ("revenues", "av_stmt_revenues"),
        ("cost_of_revenue", "av_stmt_cost_of_revenue"),
        ("gross_profit", "av_stmt_gross_profit"),
        ("op_income", "av_stmt_op_income"),
        ("net_income", "av_stmt_net_income"),
        ("ocf", "av_stmt_ocf"),
        ("capex", "av_stmt_capex"),
        ("revenues_ttm", "av_stmt_revenues_ttm"),
        ("cost_of_revenue_ttm", "av_stmt_cost_of_revenue_ttm"),
        ("gross_profit_ttm", "av_stmt_gross_profit_ttm"),
        ("op_income_ttm", "av_stmt_op_income_ttm"),
        ("net_income_ttm", "av_stmt_net_income_ttm"),
        ("ocf_ttm", "av_stmt_ocf_ttm"),
        ("capex_ttm", "av_stmt_capex_ttm"),
        ("fund_history_quarters_available", "av_stmt_quarter_count"),
        ("revenue_growth_final", "av_stmt_revenue_growth_yoy_actual"),
        ("earnings_growth_final", "av_stmt_earnings_growth_yoy_actual"),
    ]
    repair_used = pd.Series(False, index=d.index, dtype=bool)
    for base_col, repair_col in fill_pairs:
        if repair_col not in d.columns:
            continue
        if base_col not in d.columns:
            d[base_col] = np.nan
        base_vals = pd.to_numeric(d[base_col], errors="coerce")
        repair_vals = pd.to_numeric(d[repair_col], errors="coerce")
        use_mask = base_vals.isna() & repair_vals.notna()
        if use_mask.any():
            d.loc[use_mask, base_col] = repair_vals.loc[use_mask]
            repair_used = repair_used | use_mask

    if "gross_profit_ttm" in d.columns and "revenues_ttm" in d.columns and "cost_of_revenue_ttm" in d.columns:
        gp_ttm = pd.to_numeric(d["gross_profit_ttm"], errors="coerce")
        rev_ttm = pd.to_numeric(d["revenues_ttm"], errors="coerce")
        cost_ttm = pd.to_numeric(d["cost_of_revenue_ttm"], errors="coerce")
        use_mask = gp_ttm.isna() & rev_ttm.notna() & cost_ttm.notna()
        if use_mask.any():
            d.loc[use_mask, "gross_profit_ttm"] = rev_ttm.loc[use_mask] - cost_ttm.loc[use_mask]
            repair_used = repair_used | use_mask
    if "gross_profit" in d.columns and "revenues" in d.columns and "cost_of_revenue" in d.columns:
        gp = pd.to_numeric(d["gross_profit"], errors="coerce")
        rev = pd.to_numeric(d["revenues"], errors="coerce")
        cost = pd.to_numeric(d["cost_of_revenue"], errors="coerce")
        use_mask = gp.isna() & rev.notna() & cost.notna()
        if use_mask.any():
            d.loc[use_mask, "gross_profit"] = rev.loc[use_mask] - cost.loc[use_mask]
            repair_used = repair_used | use_mask

    d["latest_statement_repair_used"] = repair_used
    return d


def fetch_live_fundamentals_one(
    cfg: EngineConfig,
    paths: dict[str, Path],
    ticker: str,
    use_alpha_vantage: bool = True,
) -> dict[str, Any]:
    p = cache_live_file(paths, ticker)
    existing = load_cached_json_if_any(p)
    if is_cache_fresh(p, cfg.live_refresh_days):
        return existing or {"ticker": ticker}

    data = {"ticker": ticker}
    data.update(fetch_yf_live_fundamentals(ticker))

    if use_alpha_vantage and cfg.alpha_vantage_api_key and ticker:
        av_ov = fetch_alpha_vantage_overview(ticker, cfg.alpha_vantage_api_key)
        data.update(av_ov)
        time.sleep(alpha_vantage_pause_seconds(cfg))

    data = preserve_cached_fields(data, existing, LIVE_CACHE_ALPHA_PRESERVE_FIELDS)

    data["ticker"] = ticker
    data["updated_at"] = datetime.utcnow().isoformat(timespec="seconds")
    try:
        p.write_text(json.dumps(data), encoding="utf-8")
    except Exception:
        pass
    return data


def refresh_live_fundamentals(cfg: EngineConfig, paths: dict[str, Path], tickers: list[str]) -> pd.DataFrame:
    seen_live: set[str] = set()
    ordered_tickers: list[str] = []
    for ticker in tickers:
        if not is_valid_ticker(ticker):
            continue
        norm = str(ticker).upper()
        if norm in seen_live:
            continue
        seen_live.add(norm)
        ordered_tickers.append(norm)
    tickers = ordered_tickers[: cfg.max_live_refresh_tickers]
    av_limit = effective_alpha_vantage_refresh_tickers(cfg)
    av_tickers: set[str] = set()
    if av_limit > 0:
        for t in tickers:
            if len(av_tickers) >= av_limit:
                break
            cache_path = cache_live_file(paths, t)
            if not cache_path.exists():
                av_tickers.add(t)
                continue
            try:
                cached = json.loads(cache_path.read_text(encoding="utf-8"))
            except Exception:
                av_tickers.add(t)
                continue
            needs_refresh = False
            for key in ["av_forward_pe", "av_quarterly_revenue_growth_yoy", "av_quarterly_earnings_growth_yoy"]:
                val = cached.get(key)
                if val in (None, "", []):
                    needs_refresh = True
                    break
                try:
                    if pd.isna(val):
                        needs_refresh = True
                        break
                except Exception:
                    needs_refresh = True
                    break
            if needs_refresh:
                av_tickers.add(t)
        if len(av_tickers) < av_limit and not bool(getattr(cfg, "alpha_vantage_free_tier_mode", False)):
            av_tickers.update(tickers[:av_limit])
            av_tickers = set(list(av_tickers)[:av_limit])

    rows = []
    for i, t in enumerate(tickers, start=1):
        use_alpha_vantage = bool(cfg.alpha_vantage_api_key and t in av_tickers)
        row = fetch_live_fundamentals_one(cfg, paths, t, use_alpha_vantage=use_alpha_vantage)
        if use_alpha_vantage:
            row.update(fetch_alpha_vantage_earnings_estimates(t, cfg.alpha_vantage_api_key))
            row = preserve_cached_fields(row, load_cached_json_if_any(cache_live_file(paths, t)), LIVE_CACHE_ALPHA_PRESERVE_FIELDS)
            row["updated_at"] = datetime.utcnow().isoformat(timespec="seconds")
            try:
                cache_live_file(paths, t).write_text(json.dumps(row), encoding="utf-8")
            except Exception:
                pass
            time.sleep(alpha_vantage_pause_seconds(cfg))
        rows.append(row)
        if i % 20 == 0:
            time.sleep(1.0)

    df = pd.DataFrame(rows) if rows else pd.DataFrame(columns=["ticker"])
    if not df.empty:
        df.to_parquet(paths["cache_live_fund"] / "live_fundamentals_latest.parquet", index=False)
    return df


def compute_fundamental_trend_features(panel: pd.DataFrame) -> pd.DataFrame:
    TREND_COLS = [
        "rev_growth_accel_4q", "margin_trend_4q", "ocf_ni_quality_4q",
        "revenue_accel_2nd_deriv", "growth_inflection_signal", "margin_expansion_at_growth",
    ]
    if panel is None or panel.empty:
        return pd.DataFrame(
            columns=["cik", "period", "trend_accepted"] + TREND_COLS
        )

    d = panel.copy().sort_values(["cik", "period"]).reset_index(drop=True)
    d["trend_accepted"] = pd.to_datetime(d.get("accepted"), errors="coerce")

    if "revenues_ttm" in d.columns:
        d["rev_growth_yoy"] = d.groupby("cik")["revenues_ttm"].pct_change(4)
        d["rev_growth_accel_4q"] = d.groupby("cik")["rev_growth_yoy"].diff(1)
        # 2nd derivative: acceleration of acceleration
        d["revenue_accel_2nd_deriv"] = d.groupby("cik")["rev_growth_accel_4q"].diff(1)

    if "op_margin_ttm" in d.columns:
        d["margin_trend_4q"] = d.groupby("cik")["op_margin_ttm"].diff(4)

    if "ocf_ttm" in d.columns and "net_income_ttm" in d.columns:
        ni = pd.to_numeric(d["net_income_ttm"], errors="coerce").replace(0, np.nan)
        d["ocf_ni_quality_4q"] = pd.to_numeric(d["ocf_ttm"], errors="coerce") / ni

    # Growth inflection: growth just turned positive with acceleration
    sgy = pd.to_numeric(d.get("sales_growth_yoy"), errors="coerce")
    sgy_prev = d.groupby("cik")["sales_growth_yoy"].shift(4) if "sales_growth_yoy" in d.columns else pd.Series(np.nan, index=d.index)
    rga = pd.to_numeric(d.get("rev_growth_accel_4q"), errors="coerce")
    d["growth_inflection_signal"] = (
        (sgy > 0) & (sgy_prev <= 0.05) & (rga > 0)
    ).astype(float).fillna(0.0)

    # Margin expansion during growth phase
    opm = pd.to_numeric(d.get("op_margin_ttm"), errors="coerce")
    opm_prev = d.groupby("cik")["op_margin_ttm"].shift(4) if "op_margin_ttm" in d.columns else pd.Series(np.nan, index=d.index)
    d["margin_expansion_at_growth"] = (
        (opm > opm_prev) & (sgy > 0.15)
    ).astype(float).fillna(0.0)

    keep = ["cik", "period", "trend_accepted"]
    for c in TREND_COLS:
        if c not in d.columns:
            d[c] = np.nan
        keep.append(c)
    return d[keep].copy()


TREND_MERGE_COLS = [
    "rev_growth_accel_4q", "margin_trend_4q", "ocf_ni_quality_4q",
    "revenue_accel_2nd_deriv", "growth_inflection_signal", "margin_expansion_at_growth",
]


def merge_trend_features_into_monthly(monthly: pd.DataFrame, panel: pd.DataFrame) -> pd.DataFrame:
    if monthly.empty:
        return monthly
    if panel is None or panel.empty:
        d = monthly.copy()
        for c in TREND_MERGE_COLS:
            if c not in d.columns:
                d[c] = np.nan
        return d

    trend_panel = compute_fundamental_trend_features(panel)
    if "trend_accepted" not in trend_panel.columns:
        trend_panel["trend_accepted"] = pd.NaT
    trend_panel["trend_accepted"] = pd.to_datetime(trend_panel["trend_accepted"], errors="coerce")
    trend_panel = trend_panel.dropna(subset=["trend_accepted"]).drop(columns=["period"], errors="ignore").sort_values(["cik", "trend_accepted"])

    d = monthly.copy()
    d["rebalance_date"] = pd.to_datetime(d["rebalance_date"], errors="coerce")
    chunks = []

    for cik, g in d.groupby("cik10", sort=False):
        gg = g.sort_values("rebalance_date").copy()
        if pd.isna(cik):
            for c in TREND_MERGE_COLS:
                gg[c] = np.nan
            chunks.append(gg)
            continue

        p = trend_panel[trend_panel["cik"] == str(cik)]
        if p.empty:
            for c in TREND_MERGE_COLS:
                gg[c] = np.nan
            chunks.append(gg)
            continue

        merged = pd.merge_asof(
            gg,
            p.sort_values("trend_accepted"),
            left_on="rebalance_date",
            right_on="trend_accepted",
            direction="backward",
        )
        if "trend_accepted" in merged.columns:
            merged = merged.drop(columns=["trend_accepted"])
        chunks.append(merged)

    return pd.concat(chunks, ignore_index=True)


def merge_live_fundamentals(monthly: pd.DataFrame, live_df: pd.DataFrame) -> pd.DataFrame:
    if monthly.empty:
        return monthly
    d = monthly.copy()
    if live_df is None or live_df.empty:
        for c in LATEST_ONLY_SIGNAL_COLUMNS:
            if c not in d.columns:
                d[c] = np.nan
        return d
    return d.merge(live_df, on="ticker", how="left")


# Stage 2c (2026-04-20): cross_sectional_robust_z + _by_sector moved to r1000_helpers.py.


def compute_sage_sector_labels(df: pd.DataFrame) -> pd.Series:
    """Classify each row into one of 8 SAGE sectors using SAGE_SECTOR_MAP keyword matching.
    Returns a Series with values like 'Software', 'Semiconductor', 'Banking', etc."""
    label_cols = [
        "industry",
        "subindustry",
        "gics_sub_industry",
        "industry_group",
        "industry_sector",
        "gics_sector",
        "sector",
    ]
    available_label_cols = [c for c in label_cols if c in df.columns]
    if available_label_cols:
        sector_labels = (
            df[available_label_cols]
            .fillna("")
            .astype(str)
            .agg(" ".join, axis=1)
            .str.upper()
            .str.replace("&", " AND ", regex=False)
            .str.replace(r"\s+", " ", regex=True)
            .str.strip()
        )
    else:
        sector_labels = normalized_sector_labels(df)
    result = pd.Series("General", index=df.index, dtype=str)
    for sage_name, keywords in SAGE_SECTOR_MAP:
        if sage_name == "General":
            break  # catch-all — skip, already initialized to "General"
        if not keywords:
            continue
        mask = sector_keyword_mask(sector_labels, keywords)
        # Only assign where not yet classified (first match wins)
        unclassified = result == "General"
        result.loc[mask & unclassified] = sage_name
    return result


# Stage 2c (2026-04-20): numeric_series_or_default moved to r1000_helpers.py.

# =====================================================================
# Live / satellite / moat / gate feature engineering (Stage 3c, 2026-04-20)
# =====================================================================
# 8 functions covering live factor assembly, actual-priority weighting,
# latest-flow satellite features, moat proxy composite, plus small
# sector-label normalisation and column-counting helpers.
# compute_live_factor_columns is the largest single feature function
# in the engine (265 lines) -- it assembles the cross-sectional live
# factor stack (sage_* scores, fundamental_confidence, revision_scores)
# that feeds the sleeve composite at latest-scoring time.

def datetime_series_or_default(df: pd.DataFrame, col: str) -> pd.Series:
    """Convert column to datetime[ns] Series, returning NaT for invalid.

    Phase 15-C fix (2026-04-28): also mask 1970-01-01 (Unix epoch 0) as NaT.
    `pd.to_datetime(0)` returns 1970-01-01, which leaks into outputs when an
    upstream source has integer 0 for missing periods (e.g. some SEC
    companyfacts payloads). For SEC fundamentals + market dates, anything
    pre-1990 is bogus by construction. Mask these to NaT so downstream
    code (and CSV exports) shows blanks instead of 1970 placeholders.
    """
    if col not in df.columns:
        return pd.Series(pd.NaT, index=df.index, dtype="datetime64[ns]")
    out = pd.to_datetime(df[col], errors="coerce")
    # Mask 1970-era false positives — only valid SEC/market dates land here.
    return out.where(out >= pd.Timestamp("1990-01-01"), pd.NaT)


def count_present_columns(df: pd.DataFrame, cols: list[str]) -> pd.Series:
    if df is None or df.empty:
        return pd.Series(dtype=int)
    frames = []
    for c in cols:
        if c in df.columns:
            frames.append(pd.to_numeric(df[c], errors="coerce").notna().rename(c))
        else:
            frames.append(pd.Series(False, index=df.index, name=c, dtype=bool))
    return pd.concat(frames, axis=1).sum(axis=1).astype(int)


def normalized_sector_labels(df: pd.DataFrame) -> pd.Series:
    if df is None or df.empty or "sector" not in df.columns:
        return pd.Series("", index=getattr(df, "index", pd.Index([])), dtype=str)
    return (
        df["sector"]
        .fillna("")
        .astype(str)
        .str.upper()
        .str.replace("&", " AND ", regex=False)
        .str.replace(r"\s+", " ", regex=True)
        .str.strip()
    )


def sector_keyword_mask(sector_series: pd.Series, keywords: tuple[str, ...]) -> pd.Series:
    if sector_series is None or sector_series.empty:
        return pd.Series(dtype=bool)
    pattern = "|".join(re.escape(k) for k in keywords if k)
    if not pattern:
        return pd.Series(False, index=sector_series.index, dtype=bool)
    return sector_series.astype(str).str.contains(pattern, regex=True, na=False)


def _load_finnhub_features_for_fallback() -> pd.DataFrame:
    """Phase 15-D D1 (2026-04-29): load the aggressive Finnhub features parquet
    so main pipeline's compute_live_factor_columns can use it as fallback for
    eps_ttm / forward_pe / peg / dividend_yield when SEC + AlphaVantage chain
    yields NaN.

    On the SHIPPED 2026-04-28 scored_latest.csv: eps_ttm was 17% populated,
    peg_final 49%, forward_pe_final 74%. Adding Finnhub TTM fallback lifts
    each by 20-40% expected (Finnhub API has 99% R1000 coverage).

    Returns DataFrame with ticker + fh_pe_ratio / fh_peg / fh_eps_ttm /
    fh_dividend_yield columns. Empty DataFrame if file not found.
    """
    try:
        from pathlib import Path as _Path
        # Locate the Finnhub parquet relative to the package root.
        repo_root = _Path(__file__).resolve().parent
        candidate_paths = [
            repo_root / "aggressive" / "state" / "finnhub" / "r1000_features.parquet",
            repo_root.parent / "aggressive" / "state" / "finnhub" / "r1000_features.parquet",
        ]
        for p in candidate_paths:
            if p.exists():
                df = pd.read_parquet(p)
                return df
    except Exception:
        pass
    return pd.DataFrame()


def compute_live_factor_columns(df: pd.DataFrame, cfg: Optional[EngineConfig] = None) -> pd.DataFrame:
    d = df.copy()

    def presence(col: str) -> pd.Series:
        if col not in d.columns:
            return pd.Series(0.0, index=d.index, dtype=float)
        return pd.to_numeric(d[col], errors="coerce").notna().astype(float)

    d["current_price_live"] = numeric_series_or_default(d, "current_price_live", np.nan)
    d["current_price_live"] = d["current_price_live"].fillna(numeric_series_or_default(d, "px", np.nan))

    d["market_cap_live"] = numeric_series_or_default(d, "market_cap_live", np.nan)
    d["market_cap_live"] = d["market_cap_live"].fillna(numeric_series_or_default(d, "mktcap", np.nan))
    d["market_cap_live"] = d["market_cap_live"].fillna(numeric_series_or_default(d, "mktcap_proxy", np.nan))
    market_cap_effective = d["market_cap_live"].replace(0, np.nan)
    net_income_ttm = numeric_series_or_default(d, "net_income_ttm", np.nan)
    revenues_ttm = numeric_series_or_default(d, "revenues_ttm", np.nan)
    ocf_ttm = numeric_series_or_default(d, "ocf_ttm", np.nan)
    capex_ttm = numeric_series_or_default(d, "capex_ttm", np.nan)
    gross_profit_ttm = numeric_series_or_default(d, "gross_profit_ttm", np.nan)
    op_income_ttm = numeric_series_or_default(d, "op_income_ttm", np.nan)
    op_margin_proxy = op_income_ttm / revenues_ttm.replace(0, np.nan)
    d["op_margin_ttm"] = numeric_series_or_default(d, "op_margin_ttm", np.nan).fillna(op_margin_proxy)
    d["gross_margins"] = numeric_series_or_default(d, "gross_margins", np.nan).fillna(
        gross_profit_ttm / revenues_ttm.replace(0, np.nan)
    )
    d["operating_margins"] = numeric_series_or_default(d, "operating_margins", np.nan).fillna(
        d["op_margin_ttm"]
    )
    d["fcf_ttm"] = numeric_series_or_default(d, "fcf_ttm", np.nan).fillna(ocf_ttm - capex_ttm)
    d["ep_ttm"] = numeric_series_or_default(d, "ep_ttm", np.nan).fillna(
        net_income_ttm / market_cap_effective
    )
    d["sp_ttm"] = numeric_series_or_default(d, "sp_ttm", np.nan).fillna(
        revenues_ttm / market_cap_effective
    )
    d["fcfy_ttm"] = numeric_series_or_default(d, "fcfy_ttm", np.nan).fillna(
        d["fcf_ttm"] / market_cap_effective
    )

    d["return_on_equity_effective"] = numeric_series_or_default(d, "return_on_equity_live", np.nan)
    d["return_on_equity_effective"] = d["return_on_equity_effective"].fillna(
        numeric_series_or_default(d, "av_return_on_equity", np.nan)
    )
    d["return_on_equity_effective"] = d["return_on_equity_effective"].fillna(
        numeric_series_or_default(d, "roe_proxy", np.nan)
    )

    # Phase 15-D D1 (2026-04-29): merge Finnhub fallback features once per call
    # for use across forward_pe / peg / eps_ttm / dividend cascades. The main
    # pipeline doesn't read aggressive/state/finnhub/r1000_features.parquet
    # directly — only the advisor v3 does. Without this merge, eps_ttm was
    # 17% / forward_pe_final 74% / peg_final 49% on SHIPPED data because
    # SEC companyfacts + AlphaVantage free-tier (25 calls/day) leaves a wide
    # gap. Finnhub has near-100% R1000 coverage.
    _fh_features = _load_finnhub_features_for_fallback()
    if not _fh_features.empty and "ticker" in d.columns:
        # Use prefix to avoid collision with existing fh_* columns already in df
        _fh_subset = _fh_features.rename(
            columns={c: f"_fh_lookup_{c}" for c in _fh_features.columns if c != "ticker"}
        )
        d = d.merge(_fh_subset, on="ticker", how="left", suffixes=("", "_dup"))
        # Drop any duplicate columns from suffix
        d = d.loc[:, ~d.columns.duplicated(keep="first")]

    def _fh_lookup(col: str) -> pd.Series:
        """Helper to fetch finnhub fallback Series by original column name."""
        return numeric_series_or_default(d, f"_fh_lookup_{col}", np.nan)

    d["forward_pe_final"] = numeric_series_or_default(d, "av_forward_pe", np.nan)
    d["forward_pe_final"] = d["forward_pe_final"].fillna(numeric_series_or_default(d, "forward_pe", np.nan))
    # Phase 15-D D1: Finnhub TTM PE fallback (peExclExtraTTM is the canonical TTM PE)
    d["forward_pe_final"] = d["forward_pe_final"].fillna(_fh_lookup("fh_peExclExtra_ttm"))
    d["forward_pe_final"] = d["forward_pe_final"].fillna(_fh_lookup("fh_peBasicExclExtra_ttm"))
    d["forward_pe_final"] = d["forward_pe_final"].fillna(
        (1.0 / numeric_series_or_default(d, "ep_ttm", np.nan)).where(
            numeric_series_or_default(d, "ep_ttm", np.nan) > 0
        )
    )
    d["ev_to_ebitda_final"] = numeric_series_or_default(d, "av_ev_to_ebitda", np.nan)

    d["peg_final"] = numeric_series_or_default(d, "av_peg_ratio", np.nan)
    d["peg_final"] = d["peg_final"].fillna(numeric_series_or_default(d, "peg_ratio", np.nan))
    # Phase 15-D D1: Finnhub PEG fallback (peg_5y based on peExclExtraTTM / 5Y growth)
    d["peg_final"] = d["peg_final"].fillna(_fh_lookup("fh_peg_5y"))
    d["peg_final"] = d["peg_final"].fillna(_fh_lookup("fh_peg_quarterly"))

    d["earnings_growth_final"] = numeric_series_or_default(d, "earnings_growth_final", np.nan)
    d["earnings_growth_final"] = d["earnings_growth_final"].fillna(
        numeric_series_or_default(d, "earnings_growth", np.nan)
    )
    d["earnings_growth_final"] = d["earnings_growth_final"].fillna(
        numeric_series_or_default(d, "av_quarterly_earnings_growth_yoy", np.nan)
    )
    d["earnings_growth_final"] = d["earnings_growth_final"].fillna(
        numeric_series_or_default(d, "av_stmt_earnings_growth_yoy_actual", np.nan)
    )
    d["earnings_growth_final"] = d["earnings_growth_final"].fillna(
        numeric_series_or_default(d, "net_income_growth_yoy", np.nan)
    )
    d["earnings_growth_final"] = d["earnings_growth_final"].fillna(
        numeric_series_or_default(d, "op_income_growth_yoy", np.nan)
    )
    d["earnings_growth_final"] = d["earnings_growth_final"].fillna(
        numeric_series_or_default(d, "ocf_growth_yoy", np.nan)
    )
    d["earnings_growth_final"] = d["earnings_growth_final"].fillna(
        numeric_series_or_default(d, "net_income_cagr_3y", np.nan)
    )
    d["earnings_growth_final"] = d["earnings_growth_final"].fillna(
        numeric_series_or_default(d, "net_income_cagr_5y", np.nan)
    )
    d["earnings_growth_final"] = d["earnings_growth_final"].fillna(
        numeric_series_or_default(d, "op_income_cagr_best", np.nan)
    )
    d["earnings_growth_final"] = d["earnings_growth_final"].fillna(
        numeric_series_or_default(d, "op_income_cagr_3y", np.nan)
    )
    d["earnings_growth_final"] = d["earnings_growth_final"].fillna(
        numeric_series_or_default(d, "op_income_cagr_5y", np.nan)
    )
    d["earnings_growth_final"] = d["earnings_growth_final"].fillna(
        numeric_series_or_default(d, "ocf_cagr_best", np.nan)
    )
    d["earnings_growth_final"] = d["earnings_growth_final"].fillna(
        numeric_series_or_default(d, "ocf_cagr_3y", np.nan)
    )
    d["earnings_growth_final"] = d["earnings_growth_final"].fillna(
        numeric_series_or_default(d, "ocf_cagr_5y", np.nan)
    )
    earnings_growth_pct = (
        numeric_series_or_default(d, "earnings_growth_final", np.nan) * 100.0
    ).where(numeric_series_or_default(d, "earnings_growth_final", np.nan) > 0)
    d["peg_final"] = d["peg_final"].fillna(
        numeric_series_or_default(d, "forward_pe_final", np.nan) / earnings_growth_pct.replace(0, np.nan)
    )

    d["revenue_growth_final"] = numeric_series_or_default(d, "revenue_growth_final", np.nan)
    d["revenue_growth_final"] = d["revenue_growth_final"].fillna(
        numeric_series_or_default(d, "revenue_growth", np.nan)
    )
    d["revenue_growth_final"] = d["revenue_growth_final"].fillna(
        numeric_series_or_default(d, "av_quarterly_revenue_growth_yoy", np.nan)
    )
    d["revenue_growth_final"] = d["revenue_growth_final"].fillna(
        numeric_series_or_default(d, "av_stmt_revenue_growth_yoy_actual", np.nan)
    )
    d["revenue_growth_final"] = d["revenue_growth_final"].fillna(
        numeric_series_or_default(d, "sales_growth_yoy", np.nan)
    )
    d["revenue_growth_final"] = d["revenue_growth_final"].fillna(
        numeric_series_or_default(d, "sales_cagr_best", np.nan)
    )
    d["revenue_growth_final"] = d["revenue_growth_final"].fillna(
        numeric_series_or_default(d, "sales_cagr_3y", np.nan)
    )
    d["revenue_growth_final"] = d["revenue_growth_final"].fillna(
        numeric_series_or_default(d, "sales_cagr_5y", np.nan)
    )

    # Forward P/S: market_cap / (revenues_ttm * (1 + revenue_growth_final))
    _rev_fwd = numeric_series_or_default(d, "revenues_ttm", np.nan) * (
        1.0 + numeric_series_or_default(d, "revenue_growth_final", 0.0).clip(lower=-0.50, upper=2.0)
    )
    _mktcap = numeric_series_or_default(d, "mktcap", np.nan)
    _mktcap = _mktcap.fillna(numeric_series_or_default(d, "market_cap_live", np.nan))
    d["forward_ps"] = (_mktcap / _rev_fwd.replace(0, np.nan)).where(_rev_fwd > 0)
    # Forward P/S final: prefer live price_to_sales adjusted, fallback to computed
    _trailing_ps = numeric_series_or_default(d, "price_to_sales", np.nan).fillna(
        numeric_series_or_default(d, "av_price_to_sales", np.nan)
    )
    _growth_adj = 1.0 + numeric_series_or_default(d, "revenue_growth_final", 0.0).clip(lower=-0.50, upper=2.0)
    d["forward_ps_final"] = (_trailing_ps / _growth_adj).where(_growth_adj > 0)
    d["forward_ps_final"] = d["forward_ps_final"].fillna(d["forward_ps"])

    ref_px = numeric_series_or_default(d, "current_price_live", np.nan)
    d["target_upside_pct"] = numeric_series_or_default(d, "target_mean_price", np.nan) / ref_px.replace(0, np.nan) - 1.0
    d["analyst_coverage_proxy"] = row_mean(
        [
            presence("eps_est_q_next"),
            presence("rev_est_q_next"),
            presence("eps_est_fy1"),
            presence("rev_est_fy1"),
            presence("eps_est_fy2"),
            presence("rev_est_fy2"),
            presence("target_mean_price"),
            presence("recommendation_mean"),
        ],
        d.index,
    ).fillna(0.0)

    d["forward_value_score"] = row_mean(
        [
            -cross_sectional_robust_z(d, "forward_pe_final"),
            -cross_sectional_robust_z(d, "peg_final"),
            -cross_sectional_robust_z(d, "forward_ps_final"),
            -cross_sectional_robust_z(d, "ev_to_ebitda_final"),
            cross_sectional_robust_z(d, "fcfy_ttm"),
        ],
        d.index,
    ).fillna(0.0)
    # -------------------------------------------------------------------
    # Phase 8c.2 (2026-04-17): growth-adjusted valuation dampening.
    # The raw forward_value_score above gives NVDA / AVGO / AMD (25%+
    # revenue growth mega-caps) a NEGATIVE score because their P/E, P/S
    # are above cross-sectional median. But a 45%-revenue-growth name
    # SHOULD trade at a premium — penalising it for that is what caused
    # our engine to rank NVDA 23rd during its best 2024-01 month.
    #
    # Fix: when revenue_growth_final is high, cap the valuation
    # PENALTY (negative score) — we don't want to reward high P/E, but
    # we shouldn't punish it either when earnings are catching up fast.
    # POSITIVE score (cheap names) is unchanged; only NEGATIVE score
    # (expensive names being penalised) is dampened.
    #
    # Thresholds:
    #   rev_growth > 0.40  -> zero out the penalty (growth fully justifies)
    #   rev_growth > 0.20  -> halve the penalty
    #   rev_growth <= 0.20 -> no change (legacy behaviour)
    # -------------------------------------------------------------------
    _phase8c2_env = phase_is_enabled("phase8c_growth_adj_valuation", default=True)
    _phase8c2_cfg = bool(getattr(cfg, "phase8c_growth_adj_valuation_enabled", True)) if cfg is not None else True
    if _phase8c2_env and _phase8c2_cfg:
        _rev_gr_for_value = numeric_series_or_default(d, "revenue_growth_final", 0.0)
        _fwd_val = pd.to_numeric(d["forward_value_score"], errors="coerce").fillna(0.0)
        _is_penalty = (_fwd_val < 0.0)
        # Dampening factor: 0.0 when growth>0.40, 0.5 when 0.20<growth<=0.40, 1.0 otherwise.
        _dampen = pd.Series(1.0, index=d.index, dtype=float)
        _dampen = _dampen.where(~((_rev_gr_for_value > 0.20) & (_rev_gr_for_value <= 0.40)), 0.5)
        _dampen = _dampen.where(~(_rev_gr_for_value > 0.40), 0.0)
        # Only apply to NEGATIVE (penalty) rows — keep positive (cheap) rows intact.
        d["forward_value_score"] = np.where(
            _is_penalty, _fwd_val * _dampen.to_numpy(dtype=float), _fwd_val
        )
        d["phase8c_growth_adj_valuation_active"] = 1.0
    else:
        d["phase8c_growth_adj_valuation_active"] = 0.0

    revision_components = [
        "eps_est_q_next",
        "eps_est_fy1",
        "eps_est_fy2",
        "rev_est_q_next",
        "rev_est_fy1",
        "rev_est_fy2",
        "eps_revision_proxy",
        "target_upside_pct",
    ]
    revision_raw = row_mean(
        [cross_sectional_robust_z(d, c) for c in revision_components],
        d.index,
    ).fillna(0.0)
    revision_avail = pd.concat(
        [
            (pd.to_numeric(d[c], errors="coerce") if c in d.columns else pd.Series(np.nan, index=d.index, dtype=float))
            .notna()
            .rename(c)
            for c in revision_components
        ],
        axis=1,
    )
    global_revision_cov = float(revision_avail.mean().mean()) if not revision_avail.empty else 0.0
    d["revision_coverage_ratio"] = revision_avail.mean(axis=1).fillna(0.0) * global_revision_cov
    analyst_sentiment = row_mean(
        [
            cross_sectional_robust_z(d, "target_upside_pct"),
            -cross_sectional_robust_z(d, "recommendation_mean"),
        ],
        d.index,
    ).fillna(0.0)
    d["revision_score"] = (
        0.80 * revision_raw + 0.20 * analyst_sentiment
    ) * (0.55 + 0.45 * d["revision_coverage_ratio"])

    div_weight = float(cfg.dividend_quality_trend_weight) if cfg is not None else 0.20
    d["quality_trend_score"] = (
        cross_sectional_robust_z(d, "rev_growth_accel_4q")
        + cross_sectional_robust_z(d, "margin_trend_4q")
        + cross_sectional_robust_z(d, "ocf_ni_quality_4q")
        + cross_sectional_robust_z(d, "roe_trend_4q")
        - cross_sectional_robust_z(d, "debt_to_equity_delta_4q")
        + cross_sectional_robust_z(d, "margin_stability_8q")
        + div_weight * cross_sectional_robust_z(d, "dividend_policy_score")
    ) / (6.0 + div_weight)
    d["quality_trend_score"] = winsorize(d["quality_trend_score"], 0.01).clip(-6.0, 6.0)

    d["event_reaction_score"] = (
        cross_sectional_robust_z(d, "earn_gap_1d")
        + cross_sectional_robust_z(d, "mom_1m")
    ) / 2.0

    # Phase 15-D D4 (2026-04-29): PER/PEG verification — recompute trailing PE
    # from raw mktcap / net_income and log delta vs forward_pe_final source.
    # Helps catch data freshness issues (stale prices, mcap clipped) and lets
    # users sanity-check valuation in scored_latest.csv.
    _ni_ttm = numeric_series_or_default(d, "net_income_ttm", np.nan)
    _mcap = numeric_series_or_default(d, "mktcap", np.nan)
    # trailing PE = mktcap / net_income_ttm (positive earnings only)
    d["trailing_pe_recomputed"] = (
        _mcap.where(_mcap > 0) / _ni_ttm.where(_ni_ttm > 0)
    )
    # earnings yield from raw fundamentals (independent of analyst estimates)
    d["earnings_yield_recomputed"] = (
        _ni_ttm / _mcap.where(_mcap > 0)
    )
    # Source tracking — which fallback path produced forward_pe_final
    fwd = numeric_series_or_default(d, "forward_pe_final", np.nan)
    av = numeric_series_or_default(d, "av_forward_pe", np.nan)
    legacy = numeric_series_or_default(d, "forward_pe", np.nan)
    fh = numeric_series_or_default(d, "_fh_lookup_fh_peExclExtra_ttm", np.nan)  # NaN if already cleaned
    # Order of fallback in compute_live_factor_columns above:
    # 1) av_forward_pe, 2) forward_pe (legacy), 3) fh_peExclExtra_ttm, 4) 1/ep_ttm
    forward_pe_source = pd.Series("none", index=d.index, dtype=object)
    forward_pe_source = forward_pe_source.where(fwd.isna(), "ep_ttm")
    forward_pe_source = forward_pe_source.where(fh.isna() | fwd.isna() | (fwd != fh), "finnhub")
    forward_pe_source = forward_pe_source.where(legacy.isna() | fwd.isna() | (fwd != legacy), "legacy")
    forward_pe_source = forward_pe_source.where(av.isna() | fwd.isna() | (fwd != av), "alpha_vantage")
    d["forward_pe_source"] = forward_pe_source

    # Phase 15-D D1 (2026-04-29): drop the temporary _fh_lookup_* columns
    # used only for Finnhub fallback merges; downstream code should reference
    # forward_pe_final / peg_final / etc. (already-merged final values).
    _fh_lookup_cols = [c for c in d.columns if c.startswith("_fh_lookup_")]
    if _fh_lookup_cols:
        d = d.drop(columns=_fh_lookup_cols)

    return d


def compute_actual_priority_columns(df: pd.DataFrame, cfg: EngineConfig) -> pd.DataFrame:
    d = df.copy()
    accepted = datetime_series_or_default(d, "accepted")
    rebalance = datetime_series_or_default(d, "rebalance_date")
    age_days_latest = (rebalance - accepted).dt.days
    age_days_latest = age_days_latest.where(age_days_latest >= 0, np.nan)
    fallback_age = numeric_series_or_default(d, "fund_ttm_fallback_age_days", np.nan)
    fallback_used = numeric_series_or_default(d, "fund_ttm_fallback_used", 0.0) > 0
    age_days = age_days_latest.copy()
    if fallback_age.notna().any():
        age_days = age_days.where(
            ~fallback_used,
            np.fmax(age_days_latest.fillna(-1.0), fallback_age.fillna(-1.0)),
        )
        age_days = age_days.where(age_days >= 0, np.nan)
    effective_age = numeric_series_or_default(d, "fund_effective_age_days", np.nan)
    if effective_age.notna().any():
        age_days = effective_age.where(effective_age >= 0, np.nan)

    fresh_window = max(int(cfg.actual_results_fresh_days), 1)
    priority = 1.0 - (age_days / fresh_window)
    priority = priority.clip(lower=0.0, upper=1.0)

    d["actual_report_age_days_latest"] = age_days_latest
    d["actual_report_age_days"] = age_days
    d["actual_report_available"] = age_days.notna().astype(float)
    d["actual_priority_weight"] = priority.fillna(0.0)
    d["proxy_fallback_weight"] = 1.0 - cfg.proxy_decay_after_actual * d["actual_priority_weight"]

    d["actual_results_score"] = (
        cross_sectional_robust_z(d, "sales_growth_yoy")
        + cross_sectional_robust_z(d, "op_margin_ttm")
        + cross_sectional_robust_z(d, "ep_ttm")
        + cross_sectional_robust_z(d, "earn_gap_1d")
        + cross_sectional_robust_z(d, "roe_trend_4q")
        + cross_sectional_robust_z(d, "sales_cagr_3y")
        + 0.75 * cross_sectional_robust_z(d, "sales_cagr_5y")
    ) / 6.75
    return d


def compute_latest_flow_factor_columns(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    inst_value_proxy = numeric_series_or_default(d, "institutional_holders_value", np.nan)
    mf_value = numeric_series_or_default(d, "mutualfund_holders_value", np.nan)
    inst_shares_proxy = numeric_series_or_default(d, "institutional_holders_shares", np.nan)
    mf_shares = numeric_series_or_default(d, "mutualfund_holders_shares", np.nan)
    inst_count_proxy = (
        numeric_series_or_default(d, "institutional_holders_count", np.nan)
        + numeric_series_or_default(d, "mutualfund_holders_count", np.nan)
    )
    sec13f_value = numeric_series_or_default(d, "sec13f_value", np.nan)
    sec13f_shares = numeric_series_or_default(d, "sec13f_shares", np.nan)
    sec13f_count = numeric_series_or_default(d, "sec13f_holders_count", np.nan)
    market_cap = numeric_series_or_default(d, "market_cap_live", np.nan)
    market_cap = market_cap.fillna(numeric_series_or_default(d, "mktcap", np.nan)).replace(0, np.nan)
    shares_out = numeric_series_or_default(d, "shares", np.nan).replace(0, np.nan)
    insider_net_proxy = numeric_series_or_default(d, "insider_net_shares", np.nan)
    insider_buy_ratio_proxy = numeric_series_or_default(d, "insider_buy_ratio", np.nan)
    insider_txn_proxy = numeric_series_or_default(d, "insider_txn_count", np.nan)
    sec_form345_net = numeric_series_or_default(d, "sec_form345_net_shares", np.nan)
    sec_form345_buy_ratio = numeric_series_or_default(d, "sec_form345_buy_ratio", np.nan)
    sec_form345_txn = numeric_series_or_default(d, "sec_form345_txn_count", np.nan)

    inst_value = sec13f_value.fillna(inst_value_proxy.fillna(0.0) + mf_value.fillna(0.0))
    inst_shares = sec13f_shares.fillna(inst_shares_proxy.fillna(0.0) + mf_shares.fillna(0.0))
    inst_count = sec13f_count.fillna(inst_count_proxy)
    insider_net = sec_form345_net.fillna(insider_net_proxy)
    insider_buy_ratio = sec_form345_buy_ratio.fillna(insider_buy_ratio_proxy)
    insider_txn = sec_form345_txn.fillna(insider_txn_proxy)
    sec13f_hold_ratio_actual = sec13f_shares / shares_out
    sec13f_value_ratio_actual = sec13f_value / market_cap
    sec13f_delta_share_ratio_actual = numeric_series_or_default(d, "sec13f_delta_shares", np.nan) / shares_out
    sec13f_delta_value_ratio_actual = numeric_series_or_default(d, "sec13f_delta_value", np.nan) / market_cap
    insider_net_ratio_actual = sec_form345_net / shares_out

    d["institutional_actual_available"] = sec13f_value.notna().astype(float)
    d["insider_actual_available"] = sec_form345_net.notna().astype(float)
    d["institutional_ownership_actual"] = sec13f_value_ratio_actual
    d["institutional_holding_intensity_actual"] = sec13f_hold_ratio_actual
    d["institutional_delta_shares_ratio_actual"] = sec13f_delta_share_ratio_actual
    d["institutional_delta_value_ratio_actual"] = sec13f_delta_value_ratio_actual
    d["insider_net_shares_ratio_actual"] = insider_net_ratio_actual
    d["institutional_ownership_proxy"] = inst_value / market_cap
    d["institutional_holding_intensity"] = inst_shares / shares_out
    d["insider_net_shares_ratio"] = insider_net / shares_out
    d["insider_buy_ratio_final"] = insider_buy_ratio
    d["insider_txn_count_final"] = insider_txn
    d["institutional_count_final"] = inst_count

    d["institutional_flow_score"] = (
        cross_sectional_robust_z(d, "institutional_count_final")
        + cross_sectional_robust_z(d, "institutional_ownership_proxy")
        + cross_sectional_robust_z(d, "institutional_holding_intensity")
    ) / 3.0

    d["insider_flow_score"] = (
        cross_sectional_robust_z(d, "insider_net_shares_ratio")
        + cross_sectional_robust_z(d, "insider_buy_ratio_final")
        + cross_sectional_robust_z(d, "insider_txn_count_final")
    ) / 3.0
    return d


def compute_moat_proxy_features(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    if d.empty:
        for c in MOAT_PROXY_COLUMNS:
            d[c] = np.nan
        return d

    market_cap = numeric_series_or_default(d, "market_cap_live", np.nan)
    market_cap = market_cap.fillna(numeric_series_or_default(d, "mktcap", np.nan)).replace(0, np.nan)
    log_mktcap = np.log(market_cap)
    size_saturation = robust_z(log_mktcap).clip(lower=0.0).fillna(0.0)

    pricing_power = row_mean(
        [
            cross_sectional_robust_z(d, "op_margin_ttm"),
            cross_sectional_robust_z(d, "gp_to_assets_ttm"),
            cross_sectional_robust_z(d, "gross_margins"),
            cross_sectional_robust_z(d, "operating_margins"),
            cross_sectional_robust_z(d, "margin_stability_8q"),
        ],
        d.index,
    ).fillna(0.0)
    durability = row_mean(
        [
            cross_sectional_robust_z(d, "return_on_equity_effective"),
            cross_sectional_robust_z(d, "roa_proxy"),
            cross_sectional_robust_z(d, "capital_efficiency_score"),
            cross_sectional_robust_z(d, "sales_cagr_3y"),
            cross_sectional_robust_z(d, "sales_cagr_5y"),
            cross_sectional_robust_z(d, "quality_trend_score"),
            -cross_sectional_robust_z(d, "debt_to_equity"),
        ],
        d.index,
    ).fillna(0.0)
    holding_intensity_safe = numeric_series_or_default(d, "institutional_holding_intensity_actual", np.nan)
    holding_intensity_safe = holding_intensity_safe.where(
        holding_intensity_safe.notna(),
        numeric_series_or_default(d, "institutional_holding_intensity", np.nan),
    )
    dominance = (
        0.35 * robust_z(holding_intensity_safe).fillna(0.0)
        + 0.25 * cross_sectional_robust_z(d, "rs_sector_6m").fillna(0.0)
        + 0.20 * cross_sectional_robust_z(d, "near_52w_high_pct").fillna(0.0)
        + 0.20 * size_saturation
    )
    moat = (
        0.40 * pricing_power
        + 0.35 * durability
        + 0.20 * dominance
        + 0.05 * size_saturation
    )

    d["size_saturation_score"] = size_saturation
    d["pricing_power_score"] = winsorize(pricing_power, 0.01).clip(-6.0, 6.0)
    d["durability_proxy_score"] = winsorize(durability, 0.01).clip(-6.0, 6.0)
    d["dominance_proxy_score"] = winsorize(dominance, 0.01).clip(-6.0, 6.0)
    d["moat_proxy_score"] = winsorize(moat, 0.01).clip(-6.0, 6.0)
    return d

__all__ = [
    "map_yf_industry_to_group",
    "attach_industry_metadata",
    "_demean_within_group",
    "_group_mean_to_row",
    "add_industry_relative_strength",
    "compute_oneil_leadership_score",
    "add_sub_industry_leader_laggard_signals",
    "add_industry_rotation_signal",
    "load_cached_json_if_any",
    "has_present_value",
    "preserve_cached_fields",
    "statement_snapshot_has_payload",
    "compute_flow_ttm_with_cum_fallback",
    "alpha_vantage_get",
    "yf_table_or_empty",
    "normalize_table_columns",
    "sum_first_numeric_column",
    "summarize_holder_table",
    "summarize_insider_transactions",
    "fetch_yf_live_fundamentals",
    "fetch_yfinance_quarterly_statements",
    "fetch_alpha_vantage_overview",
    "fetch_alpha_vantage_earnings_estimates",
    "alpha_vantage_reports_frame",
    "first_numeric_from_report",
    "sum_latest_numeric_reports",
    "yoy_latest_numeric_reports",
    "fetch_alpha_vantage_statement_snapshot",
    "load_or_fetch_alpha_vantage_statement_snapshot",
    "repair_latest_statement_fundamentals",
    "fetch_live_fundamentals_one",
    "refresh_live_fundamentals",
    "compute_fundamental_trend_features",
    "merge_trend_features_into_monthly",
    "merge_live_fundamentals",
    "compute_sage_sector_labels",
    "datetime_series_or_default",
    "count_present_columns",
    "normalized_sector_labels",
    "sector_keyword_mask",
    "compute_live_factor_columns",
    "compute_actual_priority_columns",
    "compute_latest_flow_factor_columns",
    "compute_moat_proxy_features",
    "_flexible_lag",
    "_cagr_from_lag",
    "recompute_fund_panel_derived_columns",
    "compute_event_regime_features",
    "sector_indicator",
    "compute_macro_interaction_features",
    "compute_market_style_regime_features",
    "compute_market_adaptation_features",
    "compute_dynamic_leadership_features",
    "load_manual_moat_overrides",
    "apply_manual_ticker_overlays",
    "compute_three_level_relative_strength",
    "compute_crisis_sector_fit",
    "compute_strategy_blueprint_columns",
    "compute_multidimensional_pillar_scores",
    "compute_minervini_momentum_overlay",
    # Phase 14 (2026-04-25): production wire of validated Aggressive scanner signals
    "compute_rs_acceleration_score",
    "compute_h1_oversold_value_score",
    "compute_h6_dynamic_leader_score",
    "compute_stage2_overext_penalty",
    "compute_theme_phase_features",
    "PHASE14_HYBRID_ALPHA_COLUMNS",
    # Short-RS trap fixes (2026-05-13): split short/long RS + chase-extension penalty
    "compute_rs_short_long_scores",
    "compute_short_extension_risk_penalty",
    "SHORT_RS_TRAP_COLUMNS",
    # Phase 15-A (2026-04-28): cycle-leader rescue + EPS revision catalyst
    "compute_cycle_recovery_score",
    "compute_eps_revision_score",
    # Phase 15-B (2026-04-28): early-cycle inflection — find next SNDK/MU early
    "compute_early_cycle_inflection_score",
    # Phase 15-C (2026-04-28): scanner trade_card discipline internalized
    "compute_entry_quality_score",
    # Phase 15-C (2026-04-28): ML conviction × technical confirmation gate
    "compute_ml_technical_agreement_score",
    # Phase 15-C P19 (2026-04-28): best-of-best in sub_industry rank
    "compute_sub_industry_rs_score",
    # Phase 15-C P20 (2026-04-28): insider buy cluster boost
    "compute_insider_cluster_boost_score",
]


# =====================================================================
# Stage 3d-i: fundamental panel derived columns (2026-04-20)
# =====================================================================
# Moved from r1000_top30_institutional.py lines 7684-8236.
#
# Functions:
#   _flexible_lag  -- calendar-time accurate N-quarter row lag (handles
#                    annual-only 20-F filers correctly via merge_asof on period).
#   _cagr_from_lag -- CAGR = (cur/lag)^(1/years) - 1 with variable elapsed time.
#   recompute_fund_panel_derived_columns -- THE big fund panel derivator (458L).
#                    Owns fund_history_quarters_available + TTM flows + sign-flip
#                    flags (ni_sign_flip_pos / any_profit_sign_flip_pos / roe_sign_flip_pos)
#                    that drive Phase 9 C3 early_scout gate. Contains 3 nested
#                    helpers: _sign_flip_pos, _loss_narrowing_rate, _under_loss_growth.
#
# Nested-helper scope is preserved by moving recompute_fund_panel_derived_columns
# as a single contiguous slice. Do NOT split the nested helpers out -- Phase 9 C3
# depends on their closure over `d` (the working copy of panel).

def _flexible_lag(d: pd.DataFrame, col: str, target_q: int, tol: int = 2) -> tuple:
    """Calendar-time accurate lag: finds value ~target_q fiscal quarters ago by period date.

    Uses pd.merge_asof per CIK so it works correctly for both quarterly filers
    (4 rows/yr) and annual-only filers (1 row/yr, e.g. 20-F filers).  The old
    row-count shift(12) treated annual filers as if 12 rows = 12 years, which
    made sales_cagr_3y always NaN for them.

    Falls back to the legacy row-shift when the 'period' column is absent/sparse.
    Returns (lag_series, actual_quarters_series) so CAGR can use actual elapsed time.
    """
    if d.empty or col not in d.columns:
        return pd.Series(np.nan, index=d.index), pd.Series(float(target_q), index=d.index)

    DAYS_PER_Q = 365.25 / 4.0
    TOL_DAYS = 46  # ±~1.5-month window per quarter-end boundary

    if "period" not in d.columns or d["period"].notna().mean() < 0.5:
        # --- legacy row-shift fallback ---
        res = d.groupby("cik")[col].shift(target_q)
        aq = pd.Series(float(target_q), index=d.index)
        for off in range(1, tol + 1):
            for delta in [target_q - off, target_q + off]:
                if delta < 4:
                    continue
                cand = d.groupby("cik")[col].shift(delta)
                mask = res.isna() & cand.notna()
                res = res.where(~mask, cand)
                aq = aq.where(~mask, float(delta))
        return res, aq

    res = pd.Series(np.nan, index=d.index, dtype=float)
    aq = pd.Series(float(target_q), index=d.index, dtype=float)
    # Try exact delta first, then closest neighbours
    delta_order = [target_q] + [
        x for off in range(1, tol + 1)
        for x in [target_q - off, target_q + off] if x >= 4
    ]

    for _cik, grp in d.groupby("cik", sort=False):
        g = grp.copy()
        g["_p"] = pd.to_datetime(g["period"], errors="coerce")
        g["_v"] = pd.to_numeric(g[col], errors="coerce")

        lkp = (
            g[g["_p"].notna() & g["_v"].notna()][["_p", "_v"]]
            .sort_values("_p")
        )
        if lkp.empty:
            continue
        qry = g[g["_p"].notna()].copy()
        if qry.empty:
            continue

        for dq in delta_order:
            unfilled = qry[res[qry.index].isna()]
            if unfilled.empty:
                break
            approx_days = int(dq * DAYS_PER_Q + 0.5)
            uf = unfilled.copy()
            uf["_tgt"] = uf["_p"] - pd.Timedelta(days=approx_days)

            mrg = pd.merge_asof(
                uf[["_tgt", "_p"]].rename_axis("_oi").reset_index().sort_values("_tgt"),
                lkp.rename(columns={"_p": "_lp", "_v": "_lv"}),
                left_on="_tgt",
                right_on="_lp",
                direction="nearest",
                tolerance=pd.Timedelta(days=TOL_DAYS),
            )
            hit = mrg["_lv"].notna()
            if hit.any():
                sub = mrg[hit]
                res.loc[sub["_oi"].values] = sub["_lv"].values
                elapsed = (sub["_p"] - sub["_lp"]).dt.days
                aq.loc[sub["_oi"].values] = (elapsed / DAYS_PER_Q).values

    return res, aq


def _cagr_from_lag(current: pd.Series, lag: pd.Series, actual_q: pd.Series,
                   require_positive: bool = True) -> pd.Series:
    """Compute CAGR = (current / lag)^(1/years) - 1 with variable elapsed time."""
    years = actual_q / 4.0
    denom = lag.replace(0, np.nan)
    ratio = current / denom
    if require_positive:
        valid = (ratio > 0) & (current > 0) & (lag > 0)
    else:
        valid = ratio > 0
    cagr = pd.Series(np.nan, index=current.index)
    cagr = cagr.where(~valid, np.power(ratio, 1.0 / years) - 1.0)
    return cagr


def recompute_fund_panel_derived_columns(
    panel: pd.DataFrame,
    ffill_quarters: int = 2,
    balance_ffill_quarters: int = 4,
) -> pd.DataFrame:
    if panel is None or panel.empty:
        return pd.DataFrame() if panel is None else panel

    d = panel.copy()
    d["cik"] = normalize_cik_series(d["cik"], index=d.index)
    d["period"] = pd.to_datetime(d["period"], errors="coerce")
    d["accepted"] = pd.to_datetime(d["accepted"], errors="coerce")
    d = d.sort_values(["cik", "period", "accepted"]).drop_duplicates(["cik", "period"], keep="last")
    d = d.sort_values(["cik", "period"]).reset_index(drop=True)
    d["fund_history_quarters_available"] = d.groupby("cik").cumcount() + 1

    for c in CORE_FUNDAMENTAL_COLUMNS:
        if c in d.columns:
            d[c] = pd.to_numeric(d[c], errors="coerce")

    balance_cols = [c for c in ["assets", "liabilities", "shares"] if c in d.columns]
    if balance_cols:
        balance_before = d[balance_cols].notna().copy()
        if int(balance_ffill_quarters) > 0:
            bal_limit = int(balance_ffill_quarters)
            for c in balance_cols:
                d[c] = d.groupby("cik")[c].transform(lambda s: s.ffill(limit=bal_limit))
        balance_after = d[balance_cols].notna()
        d["fund_balance_backfill_used"] = (
            balance_after & ~balance_before
        ).any(axis=1).astype(float)
    else:
        d["fund_balance_backfill_used"] = 0.0

    flow_ttm_fallback_cols = []
    for c in ["revenues", "cost_of_revenue", "gross_profit", "op_income", "net_income", "ocf", "capex"]:
        if c in d.columns:
            ttm_parts = []
            fallback_parts = []
            for _, g in d.groupby("cik", sort=False):
                ttm, used = compute_flow_ttm_with_cum_fallback(g, c)
                ttm_parts.append(ttm)
                fallback_parts.append(used)
            d[f"{c}_ttm"] = pd.concat(ttm_parts).sort_index() if ttm_parts else np.nan
            used_col = f"{c}_ttm_cum_fallback_used"
            d[used_col] = pd.concat(fallback_parts).sort_index() if fallback_parts else 0.0
            flow_ttm_fallback_cols.append(used_col)
    if flow_ttm_fallback_cols:
        d["fund_ttm_cum_fallback_used"] = (
            d[flow_ttm_fallback_cols]
            .apply(pd.to_numeric, errors="coerce")
            .fillna(0.0)
            .max(axis=1)
        )
    else:
        d["fund_ttm_cum_fallback_used"] = 0.0

    if {"revenues", "cost_of_revenue"}.issubset(d.columns):
        gp = pd.to_numeric(d.get("gross_profit"), errors="coerce")
        rev = pd.to_numeric(d["revenues"], errors="coerce")
        cost = pd.to_numeric(d["cost_of_revenue"], errors="coerce")
        use_mask = gp.isna() & rev.notna() & cost.notna()
        if use_mask.any():
            d.loc[use_mask, "gross_profit"] = rev.loc[use_mask] - cost.loc[use_mask]
    if {"revenues_ttm", "cost_of_revenue_ttm"}.issubset(d.columns):
        gp_ttm = pd.to_numeric(d.get("gross_profit_ttm"), errors="coerce")
        rev_ttm = pd.to_numeric(d["revenues_ttm"], errors="coerce")
        cost_ttm = pd.to_numeric(d["cost_of_revenue_ttm"], errors="coerce")
        use_mask = gp_ttm.isna() & rev_ttm.notna() & cost_ttm.notna()
        if use_mask.any():
            d.loc[use_mask, "gross_profit_ttm"] = rev_ttm.loc[use_mask] - cost_ttm.loc[use_mask]

    if "assets" in d.columns:
        d["asset_growth_yoy"] = d.groupby("cik")["assets"].pct_change(4)
    if "shares" in d.columns:
        d["shares_yoy"] = d.groupby("cik")["shares"].pct_change(4)
    if "revenues_ttm" in d.columns:
        d["sales_growth_yoy"] = d.groupby("cik")["revenues_ttm"].pct_change(4)
        lag1, aq1 = _flexible_lag(d, "revenues_ttm", 4, tol=1)
        lag2, aq2 = _flexible_lag(d, "revenues_ttm", 8, tol=2)
        lag3, aq3 = _flexible_lag(d, "revenues_ttm", 12, tol=2)
        lag5, aq5 = _flexible_lag(d, "revenues_ttm", 20, tol=2)
        d["sales_cagr_1y"] = _cagr_from_lag(d["revenues_ttm"], lag1, aq1, require_positive=False)
        d["sales_cagr_2y"] = _cagr_from_lag(d["revenues_ttm"], lag2, aq2, require_positive=False)
        d["sales_cagr_3y"] = _cagr_from_lag(d["revenues_ttm"], lag3, aq3, require_positive=False)
        d["sales_cagr_5y"] = _cagr_from_lag(d["revenues_ttm"], lag5, aq5, require_positive=False)
        # Best available: 3y preferred, fallback 2y then 1y
        d["sales_cagr_best"] = d["sales_cagr_3y"].fillna(d["sales_cagr_2y"]).fillna(d["sales_cagr_1y"])
    if "op_income_ttm" in d.columns:
        lag4_prev = d.groupby("cik")["op_income_ttm"].shift(4)
        d["op_income_growth_yoy"] = (d["op_income_ttm"] / lag4_prev.replace(0, np.nan) - 1.0).where(
            (d["op_income_ttm"] > 0) & (lag4_prev > 0)
        )
        lag1, aq1 = _flexible_lag(d, "op_income_ttm", 4, tol=1)
        lag2, aq2 = _flexible_lag(d, "op_income_ttm", 8, tol=2)
        lag3, aq3 = _flexible_lag(d, "op_income_ttm", 12, tol=2)
        lag5, aq5 = _flexible_lag(d, "op_income_ttm", 20, tol=2)
        d["op_income_cagr_1y"] = _cagr_from_lag(d["op_income_ttm"], lag1, aq1)
        d["op_income_cagr_2y"] = _cagr_from_lag(d["op_income_ttm"], lag2, aq2)
        d["op_income_cagr_3y"] = _cagr_from_lag(d["op_income_ttm"], lag3, aq3)
        d["op_income_cagr_5y"] = _cagr_from_lag(d["op_income_ttm"], lag5, aq5)
        d["op_income_cagr_best"] = d["op_income_cagr_3y"].fillna(d["op_income_cagr_2y"]).fillna(d["op_income_cagr_1y"])
    if "ocf_ttm" in d.columns:
        lag4_prev = d.groupby("cik")["ocf_ttm"].shift(4)
        d["ocf_growth_yoy"] = (d["ocf_ttm"] / lag4_prev.replace(0, np.nan) - 1.0).where(
            (d["ocf_ttm"] > 0) & (lag4_prev > 0)
        )
        lag1, aq1 = _flexible_lag(d, "ocf_ttm", 4, tol=1)
        lag2, aq2 = _flexible_lag(d, "ocf_ttm", 8, tol=2)
        lag3, aq3 = _flexible_lag(d, "ocf_ttm", 12, tol=2)
        lag5, aq5 = _flexible_lag(d, "ocf_ttm", 20, tol=2)
        d["ocf_cagr_1y"] = _cagr_from_lag(d["ocf_ttm"], lag1, aq1)
        d["ocf_cagr_2y"] = _cagr_from_lag(d["ocf_ttm"], lag2, aq2)
        d["ocf_cagr_3y"] = _cagr_from_lag(d["ocf_ttm"], lag3, aq3)
        d["ocf_cagr_5y"] = _cagr_from_lag(d["ocf_ttm"], lag5, aq5)
        d["ocf_cagr_best"] = d["ocf_cagr_3y"].fillna(d["ocf_cagr_2y"]).fillna(d["ocf_cagr_1y"])
    if "gross_profit_ttm" in d.columns and "assets" in d.columns:
        d["gp_to_assets_ttm"] = d["gross_profit_ttm"] / d["assets"].replace(0, np.nan)
    if "op_income_ttm" in d.columns and "revenues_ttm" in d.columns:
        d["op_margin_ttm"] = d["op_income_ttm"] / d["revenues_ttm"].replace(0, np.nan)
        d["margin_stability_8q"] = (
            -d.groupby("cik")["op_margin_ttm"]
            .rolling(8, min_periods=4)
            .std()
            .reset_index(level=0, drop=True)
        )
    if "net_income_ttm" in d.columns and "ocf_ttm" in d.columns and "assets" in d.columns:
        d["accruals_to_assets"] = (d["net_income_ttm"] - d["ocf_ttm"]) / d["assets"].replace(0, np.nan)
    if "net_income_ttm" in d.columns:
        lag4_prev = d.groupby("cik")["net_income_ttm"].shift(4)
        d["net_income_growth_yoy"] = (d["net_income_ttm"] / lag4_prev.replace(0, np.nan) - 1.0).where(
            (d["net_income_ttm"] > 0) & (lag4_prev > 0)
        )
        lag1, aq1 = _flexible_lag(d, "net_income_ttm", 4, tol=1)
        lag2, aq2 = _flexible_lag(d, "net_income_ttm", 8, tol=2)
        lag3, aq3 = _flexible_lag(d, "net_income_ttm", 12, tol=2)
        lag5, aq5 = _flexible_lag(d, "net_income_ttm", 20, tol=2)
        d["net_income_cagr_1y"] = _cagr_from_lag(d["net_income_ttm"], lag1, aq1)
        d["net_income_cagr_2y"] = _cagr_from_lag(d["net_income_ttm"], lag2, aq2)
        d["net_income_cagr_3y"] = _cagr_from_lag(d["net_income_ttm"], lag3, aq3)
        d["net_income_cagr_5y"] = _cagr_from_lag(d["net_income_ttm"], lag5, aq5)
        d["net_income_cagr_best"] = d["net_income_cagr_3y"].fillna(d["net_income_cagr_2y"]).fillna(d["net_income_cagr_1y"])
    # --- EPS & FCF TTM + CAGR ---
    if "net_income_ttm" in d.columns and "shares" in d.columns:
        d["eps_ttm"] = d["net_income_ttm"] / d["shares"].replace(0, np.nan)
        d["eps_growth_yoy"] = d.groupby("cik")["eps_ttm"].pct_change(4)
        lag1, aq1 = _flexible_lag(d, "eps_ttm", 4, tol=1)
        lag2, aq2 = _flexible_lag(d, "eps_ttm", 8, tol=2)
        lag3, aq3 = _flexible_lag(d, "eps_ttm", 12, tol=2)
        lag5, aq5 = _flexible_lag(d, "eps_ttm", 20, tol=2)
        d["eps_cagr_1y"] = _cagr_from_lag(d["eps_ttm"], lag1, aq1)
        d["eps_cagr_2y"] = _cagr_from_lag(d["eps_ttm"], lag2, aq2)
        d["eps_cagr_3y"] = _cagr_from_lag(d["eps_ttm"], lag3, aq3)
        d["eps_cagr_5y"] = _cagr_from_lag(d["eps_ttm"], lag5, aq5)
        d["eps_cagr_best"] = d["eps_cagr_3y"].fillna(d["eps_cagr_2y"]).fillna(d["eps_cagr_1y"])
    if "ocf_ttm" in d.columns and "capex_ttm" in d.columns:
        d["fcf_ttm"] = d["ocf_ttm"] - d["capex_ttm"].abs()
        d["fcf_growth_yoy"] = d.groupby("cik")["fcf_ttm"].pct_change(4)
        lag1, aq1 = _flexible_lag(d, "fcf_ttm", 4, tol=1)
        lag2, aq2 = _flexible_lag(d, "fcf_ttm", 8, tol=2)
        lag3, aq3 = _flexible_lag(d, "fcf_ttm", 12, tol=2)
        lag5, aq5 = _flexible_lag(d, "fcf_ttm", 20, tol=2)
        d["fcf_cagr_1y"] = _cagr_from_lag(d["fcf_ttm"], lag1, aq1)
        d["fcf_cagr_2y"] = _cagr_from_lag(d["fcf_ttm"], lag2, aq2)
        d["fcf_cagr_3y"] = _cagr_from_lag(d["fcf_ttm"], lag3, aq3)
        d["fcf_cagr_5y"] = _cagr_from_lag(d["fcf_ttm"], lag5, aq5)
        d["fcf_cagr_best"] = d["fcf_cagr_3y"].fillna(d["fcf_cagr_2y"]).fillna(d["fcf_cagr_1y"])

    # --- Turnaround / loss-to-profit sign-flip + loss-narrowing features ---
    # These detect the loss → profit transition (or loss-narrowing) using
    # explicit lag-4 comparison at the panel level so we do not have to rely
    # on NaN-heuristics downstream.  Each "sign_flip_pos" flag is 1 only when
    # the latest TTM crossed from non-positive to strictly positive between the
    # prior fiscal year and the current period.  The "loss_narrowing_rate" is
    # the year-over-year improvement (units of underlying TTM scaled by abs of
    # prior year value) when the firm is still loss-making but improving.
    def _sign_flip_pos(series_name: str) -> pd.Series:
        if series_name not in d.columns:
            return pd.Series(0.0, index=d.index)
        cur = pd.to_numeric(d[series_name], errors="coerce")
        prev = d.groupby("cik")[series_name].shift(4)
        prev_num = pd.to_numeric(prev, errors="coerce")
        flip = ((cur > 0.0) & (prev_num <= 0.0) & prev_num.notna()).astype(float)
        return flip.fillna(0.0)

    def _loss_narrowing_rate(series_name: str) -> pd.Series:
        if series_name not in d.columns:
            return pd.Series(0.0, index=d.index)
        cur = pd.to_numeric(d[series_name], errors="coerce")
        prev = pd.to_numeric(d.groupby("cik")[series_name].shift(4), errors="coerce")
        # Both negative; loss narrowing means cur > prev (less negative).
        improvement = (cur - prev) / prev.abs().replace(0.0, np.nan)
        mask_both_neg = (cur < 0.0) & (prev < 0.0)
        out = improvement.where(mask_both_neg).clip(lower=-1.0, upper=2.0)
        return out.fillna(0.0)

    def _under_loss_growth(series_name: str, ni_name: str = "net_income_ttm") -> pd.Series:
        """Magnitude of growth/inflection while net income is still negative."""
        if series_name not in d.columns or ni_name not in d.columns:
            return pd.Series(0.0, index=d.index)
        cur = pd.to_numeric(d[series_name], errors="coerce")
        prev = pd.to_numeric(d.groupby("cik")[series_name].shift(4), errors="coerce")
        ni_cur = pd.to_numeric(d[ni_name], errors="coerce")
        # Either turning positive while NI still negative, OR materially
        # improving cash flow despite NI still negative.
        score = pd.Series(0.0, index=d.index)
        flip_mask = (cur > 0.0) & (prev <= 0.0) & prev.notna() & (ni_cur < 0.0)
        score = score.where(~flip_mask, 1.0)
        improving_mask = (cur > prev) & (cur < 0.0) & (prev < 0.0) & (ni_cur < 0.0)
        improvement_norm = ((cur - prev) / prev.abs().replace(0.0, np.nan)).clip(0.0, 2.0)
        score = score.where(~improving_mask, improvement_norm.fillna(0.0).clip(0.0, 1.0))
        return score.fillna(0.0)

    d["op_income_sign_flip_pos"] = _sign_flip_pos("op_income_ttm")
    d["ocf_sign_flip_pos"] = _sign_flip_pos("ocf_ttm")
    d["fcf_sign_flip_pos"] = _sign_flip_pos("fcf_ttm")
    d["ni_sign_flip_pos"] = _sign_flip_pos("net_income_ttm")
    d["gp_sign_flip_pos"] = _sign_flip_pos("gross_profit_ttm")

    d["op_income_loss_narrowing_4q"] = _loss_narrowing_rate("op_income_ttm")
    d["ocf_loss_narrowing_4q"] = _loss_narrowing_rate("ocf_ttm")
    d["fcf_loss_narrowing_4q"] = _loss_narrowing_rate("fcf_ttm")
    d["ni_loss_narrowing_4q"] = _loss_narrowing_rate("net_income_ttm")

    d["ocf_under_loss_growth"] = _under_loss_growth("ocf_ttm", "net_income_ttm")
    d["fcf_under_loss_growth"] = _under_loss_growth("fcf_ttm", "net_income_ttm")
    d["op_income_under_loss_growth"] = _under_loss_growth("op_income_ttm", "net_income_ttm")

    # Composite "any inflection" flag — handy for downstream binary gating.
    d["any_profit_sign_flip_pos"] = (
        pd.concat(
            [
                d["op_income_sign_flip_pos"],
                d["ocf_sign_flip_pos"],
                d["fcf_sign_flip_pos"],
                d["ni_sign_flip_pos"],
            ],
            axis=1,
        )
        .max(axis=1)
        .fillna(0.0)
    )

    # -----------------------------------------------------------------
    # Phase 9 C3: user-facing alias columns for feature_store export.
    # These mirror existing internal sign-flip flags under intention-revealing
    # names so the Phase 9 C2 early-scout gate (in compute_portfolio_sleeve_columns)
    # can reference them directly without depending on fund_panel internals.
    # See PHASE9_C3_TURNAROUND_COLUMNS constant + PHASE_9_C3_PROPOSAL.md §3.
    # -----------------------------------------------------------------
    d["profit_turn_positive_4q"] = d["ni_sign_flip_pos"]
    d["cashflow_turn_positive_4q"] = (
        pd.concat([d["ocf_sign_flip_pos"], d["fcf_sign_flip_pos"]], axis=1)
        .max(axis=1)
        .fillna(0.0)
    )

    if "assets" in d.columns and "liabilities" in d.columns:
        equity = (d["assets"] - d["liabilities"]).replace(0, np.nan)
        d["debt_to_equity"] = d["liabilities"] / equity
        if "net_income_ttm" in d.columns:
            d["roe_proxy"] = d["net_income_ttm"] / equity
            d["roe_trend_4q"] = d.groupby("cik")["roe_proxy"].diff(4)
            # Phase 9 C3: ROE sign-flip flag + user-facing alias (parallel to op/ocf/fcf/ni).
            d["roe_sign_flip_pos"] = _sign_flip_pos("roe_proxy")
            d["roe_turn_positive_4q"] = d["roe_sign_flip_pos"]
        d["debt_to_equity_delta_4q"] = d.groupby("cik")["debt_to_equity"].diff(4)

    # Phase 9 C3 union composite — 3-way OR across profit/cashflow/roe.
    # Defensive: fill missing roe_* columns with 0 so the union still computes
    # even when the roe_proxy block above was skipped (missing assets/liab).
    if "roe_sign_flip_pos" not in d.columns:
        d["roe_sign_flip_pos"] = 0.0
    if "roe_turn_positive_4q" not in d.columns:
        d["roe_turn_positive_4q"] = 0.0
    d["any_profitability_turn_positive_4q"] = (
        pd.concat(
            [
                d["profit_turn_positive_4q"],
                d["cashflow_turn_positive_4q"],
                d["roe_turn_positive_4q"],
            ],
            axis=1,
        )
        .max(axis=1)
        .fillna(0.0)
    )

    # --- SAGE derived metrics (proxy-safe: fallback to approximations when new tags absent) ---
    rev_ttm = pd.to_numeric(d.get("revenues_ttm"), errors="coerce").replace(0, np.nan)
    fcf_col = pd.to_numeric(d.get("fcf_ttm"), errors="coerce")
    op_inc_col = pd.to_numeric(d.get("op_income_ttm"), errors="coerce")
    net_inc_col = pd.to_numeric(d.get("net_income_ttm"), errors="coerce")
    gp_col = pd.to_numeric(d.get("gross_profit_ttm"), errors="coerce")
    assets_col = pd.to_numeric(d.get("assets"), errors="coerce").replace(0, np.nan)
    liab_col = pd.to_numeric(d.get("liabilities"), errors="coerce").replace(0, np.nan)
    shares_yoy_col = pd.to_numeric(d.get("shares_yoy"), errors="coerce")

    if rev_ttm is not None and rev_ttm.notna().any():
        if fcf_col is not None and fcf_col.notna().any():
            d["fcf_margin"] = (fcf_col / rev_ttm).clip(-1.0, 1.0)
        if net_inc_col is not None and net_inc_col.notna().any():
            d["net_margin"] = (net_inc_col / rev_ttm).clip(-1.0, 1.0)
        if gp_col is not None and gp_col.notna().any():
            d["gross_margin_ttm"] = (gp_col / rev_ttm).clip(0.0, 1.0)
        if op_inc_col is not None and op_inc_col.notna().any():
            d["op_margin_calc_ttm"] = (op_inc_col / rev_ttm).clip(-1.0, 1.0)

        # Rule of 40 = revenue_growth + FCF margin (SAGE Software core signal)
        rev_growth = pd.to_numeric(d.get("revenue_growth_final", d.get("sales_growth_yoy")), errors="coerce")
        if rev_growth is not None and "fcf_margin" in d.columns:
            d["rule_of_40"] = (rev_growth + d["fcf_margin"]).clip(-0.5, 1.5)

        # SBC proxy: actual if available, else dilution-based approximation
        if "sbc" in d.columns and pd.to_numeric(d["sbc"], errors="coerce").notna().any():
            sbc_ttm = d.groupby("cik")["sbc"].transform(lambda s: s.rolling(4, min_periods=1).sum())
            d["sbc_to_revenue"] = (sbc_ttm / rev_ttm).clip(0.0, 0.50)
        elif shares_yoy_col is not None and shares_yoy_col.notna().any():
            d["sbc_to_revenue"] = (shares_yoy_col.clip(0.0, 0.40) * 0.70).fillna(0.0)
        else:
            d["sbc_to_revenue"] = 0.0

        # R&D intensity: actual if available, else gross_margin - op_margin proxy
        if "rd_expense" in d.columns and pd.to_numeric(d["rd_expense"], errors="coerce").notna().any():
            rd_ttm = d.groupby("cik")["rd_expense"].transform(lambda s: s.rolling(4, min_periods=1).sum())
            d["rd_intensity"] = (rd_ttm / rev_ttm).clip(0.0, 0.80)
        elif "gross_margin_ttm" in d.columns and "op_margin_calc_ttm" in d.columns:
            d["rd_intensity"] = (d["gross_margin_ttm"] - d["op_margin_calc_ttm"]).clip(0.0, 0.80)
        else:
            d["rd_intensity"] = np.nan

    # ROIC approximation: NOPAT / Invested Capital proxy
    if assets_col is not None and liab_col is not None and op_inc_col is not None:
        if "current_liabilities" in d.columns and pd.to_numeric(d["current_liabilities"], errors="coerce").notna().any():
            curr_liab = pd.to_numeric(d["current_liabilities"], errors="coerce").replace(0, np.nan)
        else:
            curr_liab = (liab_col * 0.30)
        invested_capital = (assets_col - curr_liab).replace(0, np.nan)
        nopat = op_inc_col * 0.79
        d["roic_approx"] = (nopat / invested_capital).clip(-0.50, 1.00)
        d["roic_approx"] = d.groupby("cik")["roic_approx"].transform(lambda s: s.ffill(limit=4))

    # Interest coverage proxy
    if op_inc_col is not None:
        if "interest_expense" in d.columns and pd.to_numeric(d["interest_expense"], errors="coerce").notna().any():
            int_exp_ttm = d.groupby("cik")["interest_expense"].transform(lambda s: s.rolling(4, min_periods=1).sum())
            int_exp_ttm = pd.to_numeric(int_exp_ttm, errors="coerce").replace(0, np.nan).abs()
            d["interest_coverage"] = (op_inc_col / int_exp_ttm).clip(-5.0, 30.0)
        elif liab_col is not None:
            est_int = (liab_col * 0.04).replace(0, np.nan)
            d["interest_coverage"] = (op_inc_col / est_int).clip(-5.0, 30.0)

    # Dilution penalty
    if shares_yoy_col is not None and shares_yoy_col.notna().any():
        d["dilution_penalty"] = shares_yoy_col.clip(-0.05, 0.30)

    ttm_ready_cols = ["revenues_ttm", "net_income_ttm", "op_margin_ttm"]
    carry_cols = [
        "revenues_ttm",
        "gross_profit_ttm",
        "op_income_ttm",
        "net_income_ttm",
        "ocf_ttm",
        "capex_ttm",
        "asset_growth_yoy",
        "shares_yoy",
        "sales_growth_yoy",
        "sales_cagr_1y",
        "sales_cagr_2y",
        "sales_cagr_3y",
        "sales_cagr_5y",
        "sales_cagr_best",
        "op_income_growth_yoy",
        "op_income_cagr_1y",
        "op_income_cagr_2y",
        "op_income_cagr_3y",
        "op_income_cagr_5y",
        "op_income_cagr_best",
        "ocf_growth_yoy",
        "ocf_cagr_1y",
        "ocf_cagr_2y",
        "ocf_cagr_3y",
        "ocf_cagr_5y",
        "ocf_cagr_best",
        "gp_to_assets_ttm",
        "op_margin_ttm",
        "margin_stability_8q",
        "accruals_to_assets",
        "debt_to_equity",
        "roe_proxy",
        "net_income_growth_yoy",
        "net_income_cagr_1y",
        "net_income_cagr_2y",
        "net_income_cagr_3y",
        "net_income_cagr_5y",
        "net_income_cagr_best",
        "roe_trend_4q",
        "debt_to_equity_delta_4q",
        "eps_ttm",
        "eps_growth_yoy",
        "eps_cagr_1y",
        "eps_cagr_2y",
        "eps_cagr_3y",
        "eps_cagr_5y",
        "eps_cagr_best",
        "fcf_ttm",
        "fcf_growth_yoy",
        "fcf_cagr_1y",
        "fcf_cagr_2y",
        "fcf_cagr_3y",
        "fcf_cagr_5y",
        "fcf_cagr_best",
        "fund_history_quarters_available",
        # Turnaround / loss-to-profit inflection panel features (Phase 1.1+1.2)
        "op_income_sign_flip_pos",
        "ocf_sign_flip_pos",
        "fcf_sign_flip_pos",
        "ni_sign_flip_pos",
        "gp_sign_flip_pos",
        "op_income_loss_narrowing_4q",
        "ocf_loss_narrowing_4q",
        "fcf_loss_narrowing_4q",
        "ni_loss_narrowing_4q",
        "ocf_under_loss_growth",
        "fcf_under_loss_growth",
        "op_income_under_loss_growth",
        "any_profit_sign_flip_pos",
        # Phase 9 C3: user-facing alias + ROE sign-flip (PHASE9_C3_TURNAROUND_COLUMNS)
        "profit_turn_positive_4q",
        "cashflow_turn_positive_4q",
        "roe_turn_positive_4q",
        "any_profitability_turn_positive_4q",
        "roe_sign_flip_pos",
        # SAGE derived metrics
        "fcf_margin",
        "net_margin",
        "gross_margin_ttm",
        "rule_of_40",
        "sbc_to_revenue",
        "rd_intensity",
        "roic_approx",
        "interest_coverage",
        "dilution_penalty",
    ]
    for c in set(ttm_ready_cols + carry_cols):
        if c not in d.columns:
            d[c] = np.nan
    d["fund_ttm_ready_raw"] = d[ttm_ready_cols].notna().all(axis=1).astype(float)
    if int(ffill_quarters) > 0:
        limit = int(ffill_quarters)
        for c in carry_cols:
            d[c] = d.groupby("cik")[c].transform(lambda s: s.ffill(limit=limit))
    d["fund_ttm_ready"] = d[ttm_ready_cols].notna().all(axis=1).astype(float)
    d["fund_ttm_backfill_used"] = (
        (pd.to_numeric(d["fund_ttm_ready_raw"], errors="coerce").fillna(0.0) < 0.5)
        & (pd.to_numeric(d["fund_ttm_ready"], errors="coerce").fillna(0.0) > 0.5)
    ).astype(float)
    return d


# =====================================================================
# Stage 3d-ii (min): event + macro regime transforms (2026-04-20)
# =====================================================================
# Moved from r1000_top30_institutional.py:
#   compute_event_regime_features          (was 3521-3664)
#   sector_indicator                       (was 4378-4381)
#   compute_macro_interaction_features     (was 4384-4436)
#
# All three are pure transforms: they take a DataFrame + config constants
# (REGIME_ROTATION_COLUMNS / MACRO_REGIME_COLUMNS / MARKET_ADAPTATION_COLUMNS
# / BENCHMARK_RELATIVE_COLUMNS) and return the frame with event/macro
# regime labels attached. No IO, no builders.
#
# Larger 3d-ii items (load_fred_series, load_cnn_fear_greed_table,
# build_macro_regime_table 417L, build_live_event_alert_table 187L, the
# benchmark + merge helpers) deferred to 3d-ii-b because they cascade
# into ensure_prices_cached_incremental + load_px + macro_cache_file +
# write_stage_coverage_report (5+ main-file helpers) which have not yet
# been moved to helpers.py.

def compute_event_regime_features(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    if d.empty:
        for c in REGIME_ROTATION_COLUMNS:
            d[c] = np.nan
        d["event_regime_label"] = ""
        return d

    date_col = None
    regime_df = d
    if "rebalance_date" in d.columns:
        d["rebalance_date"] = pd.to_datetime(d["rebalance_date"], errors="coerce")
        unique_dates = d["rebalance_date"].dropna().unique()
        existing_cols = [c for c in REGIME_ROTATION_COLUMNS if c in d.columns]
        if len(unique_dates) <= 1 and existing_cols:
            existing_ready = any(pd.to_numeric(d[c], errors="coerce").notna().any() for c in existing_cols)
            if existing_ready:
                if "event_regime_label" not in d.columns:
                    d["event_regime_label"] = "balanced"
                return d
        date_col = "rebalance_date"
        keep_cols = [
            c
            for c in [date_col]
            + MARKET_ADAPTATION_COLUMNS
            + BENCHMARK_RELATIVE_COLUMNS
            + MACRO_REGIME_COLUMNS
            if c in d.columns
        ]
        regime_df = d[keep_cols].dropna(subset=[date_col]).drop_duplicates(date_col, keep="last").sort_values(date_col).reset_index(drop=True)
        if regime_df.empty:
            for c in REGIME_ROTATION_COLUMNS:
                d[c] = np.nan
            d["event_regime_label"] = ""
            return d

    def pos_signal(col: str, scale: float = 2.0) -> pd.Series:
        base = regime_df.get(col, pd.Series(np.nan, index=regime_df.index, dtype=float))
        return (robust_z(pd.to_numeric(base, errors="coerce")).fillna(0.0) / scale).clip(lower=0.0, upper=1.0)

    def neg_signal(col: str, scale: float = 2.0) -> pd.Series:
        base = regime_df.get(col, pd.Series(np.nan, index=regime_df.index, dtype=float))
        return (-robust_z(pd.to_numeric(base, errors="coerce")).fillna(0.0) / scale).clip(lower=0.0, upper=1.0)

    breadth = numeric_series_or_default(regime_df, "market_breadth_regime_score", 0.50).clip(lower=0.0, upper=1.0)
    participation = numeric_series_or_default(regime_df, "market_sector_participation", 0.35).clip(lower=0.0, upper=1.0)
    narrowing = numeric_series_or_default(regime_df, "market_leadership_narrowing", 0.50).clip(lower=0.0, upper=1.0)
    overheat = numeric_series_or_default(regime_df, "market_overheat_ratio", 0.0).clip(lower=0.0, upper=1.0)
    risk_off = numeric_series_or_default(regime_df, "macro_risk_off_score", 0.0)
    market = numeric_series_or_default(regime_df, "market_regime_score", 0.0)
    inflation = numeric_series_or_default(regime_df, "inflation_pressure_score", 0.0)
    liquidity = numeric_series_or_default(regime_df, "liquidity_regime_score", 0.0)
    inflation_reaccel = numeric_series_or_default(regime_df, "inflation_reacceleration_score", 0.0)
    upstream_cost = numeric_series_or_default(regime_df, "upstream_cost_pressure_score", 0.0)
    labor_softening = numeric_series_or_default(regime_df, "labor_softening_score", 0.0)
    stagflation = numeric_series_or_default(regime_df, "stagflation_score", 0.0)
    growth_liquidity = numeric_series_or_default(regime_df, "growth_liquidity_reentry_score", 0.0)
    bench_trend = numeric_series_or_default(regime_df, "bench_above_ma200", np.nan).fillna(
        numeric_series_or_default(regime_df, "spy_above_ma200", 1.0)
    )
    qqq_rel = numeric_series_or_default(regime_df, "qqq_rel_spy_1m", 0.0)

    systemic = (
        0.22 * pos_signal("vix_z_63d", scale=1.4)
        + 0.18 * pos_signal("hy_oas_level", scale=1.5)
        + 0.18 * pos_signal("hy_oas_change_1m", scale=1.5)
        + 0.14 * ((0.55 - breadth) / 0.35).clip(lower=0.0, upper=1.0)
        + 0.10 * ((narrowing - 0.60) / 0.30).clip(lower=0.0, upper=1.0)
        + 0.10 * pos_signal("bench_dd_1y", scale=1.3)
        + 0.08 * ((0.50 - bench_trend) * 2.0).clip(lower=0.0, upper=1.0)
        + 0.08 * labor_softening.clip(lower=0.0, upper=1.0)
    ).clip(lower=0.0, upper=1.0)

    carry_unwind = (
        0.26 * pos_signal("vix_z_63d", scale=1.5)
        + 0.20 * pos_signal("dxy_ret_1m", scale=1.5)
        + 0.16 * neg_signal("qqq_rel_spy_1m", scale=1.5)
        + 0.14 * ((0.52 - breadth) / 0.30).clip(lower=0.0, upper=1.0)
        + 0.12 * ((narrowing - 0.58) / 0.28).clip(lower=0.0, upper=1.0)
        + 0.12 * pos_signal("hy_oas_change_1m", scale=1.6)
    ).clip(lower=0.0, upper=1.0)

    war_oil_rate = (
        0.28 * pos_signal("uso_ret_1m", scale=1.5)
        + 0.20 * pos_signal("dgs10_change_1m", scale=1.5)
        + 0.18 * pos_signal("inflation_pressure_score", scale=1.5)
        + 0.08 * inflation_reaccel.clip(lower=0.0, upper=1.0)
        + 0.06 * upstream_cost.clip(lower=0.0, upper=1.0)
        + 0.14 * pos_signal("macro_risk_off_score", scale=1.8)
        + 0.12 * pos_signal("hy_oas_change_1m", scale=1.6)
        + 0.08 * ((0.58 - breadth) / 0.35).clip(lower=0.0, upper=1.0)
    ).clip(lower=0.0, upper=1.0)

    defensive_rotation = (
        0.42 * systemic
        + 0.34 * war_oil_rate
        + 0.16 * carry_unwind
        + 0.14 * stagflation.clip(lower=0.0, upper=1.0)
        + 0.08 * ((0.45 - participation) / 0.25).clip(lower=0.0, upper=1.0)
    ).clip(lower=0.0, upper=1.0)

    growth_reentry = (
        0.22 * ((breadth - 0.58) / 0.24).clip(lower=0.0, upper=1.0)
        + 0.18 * ((participation - 0.42) / 0.20).clip(lower=0.0, upper=1.0)
        + 0.16 * ((bench_trend - 0.50) * 2.0).clip(lower=0.0, upper=1.0)
        + 0.14 * pos_signal("market_regime_score", scale=1.8)
        + 0.10 * pos_signal("liquidity_regime_score", scale=1.8)
        + 0.10 * growth_liquidity.clip(lower=0.0, upper=1.0)
        + 0.08 * pos_signal("qqq_rel_spy_1m", scale=1.8)
        + 0.12 * pos_signal("bench_ret_6m", scale=1.8)
        + 0.08 * ((0.35 - overheat) / 0.35).clip(lower=0.0, upper=1.0)
        - 0.08 * defensive_rotation
        - 0.08 * stagflation.clip(lower=0.0, upper=1.0)
        - 0.06 * ((0.0 - market).clip(lower=0.0) / 1.5).clip(lower=0.0, upper=1.0)
    ).clip(lower=0.0, upper=1.0)

    labels = np.full(len(regime_df), "balanced", dtype=object)
    labels = np.where((systemic >= carry_unwind) & (systemic >= war_oil_rate) & (systemic >= 0.55), "systemic_crisis", labels)
    labels = np.where((carry_unwind > systemic) & (carry_unwind >= war_oil_rate) & (carry_unwind >= 0.52), "carry_unwind", labels)
    labels = np.where((war_oil_rate > systemic) & (war_oil_rate > carry_unwind) & (war_oil_rate >= 0.52), "war_oil_rate_shock", labels)
    labels = np.where(
        (stagflation >= 0.55)
        & (stagflation > np.maximum(systemic, np.maximum(carry_unwind, war_oil_rate)))
        & (stagflation >= growth_reentry),
        "stagflation",
        labels,
    )
    labels = np.where((growth_reentry >= 0.60) & (growth_reentry > defensive_rotation), "growth_reentry", labels)

    regime_df = regime_df.copy()
    regime_df["systemic_crisis_score"] = systemic
    regime_df["carry_unwind_stress_score"] = carry_unwind
    regime_df["war_oil_rate_shock_score"] = war_oil_rate
    regime_df["defensive_rotation_score"] = defensive_rotation
    regime_df["growth_reentry_score"] = growth_reentry
    regime_df["event_regime_label"] = pd.Series(labels, index=regime_df.index, dtype=object)

    if date_col is None:
        return regime_df

    merge_cols = [date_col] + REGIME_ROTATION_COLUMNS + ["event_regime_label"]
    d = d.drop(columns=REGIME_ROTATION_COLUMNS + ["event_regime_label"], errors="ignore")
    d = d.merge(regime_df[merge_cols], on=date_col, how="left")
    return d


def sector_indicator(series: pd.Series, patterns: list[str]) -> pd.Series:
    txt = series.fillna("").astype(str).str.lower()
    regex = "|".join(re.escape(p.lower()) for p in patterns)
    return txt.str.contains(regex, regex=True).astype(float)


def compute_macro_interaction_features(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    if not MACRO_REGIME_COLUMNS:
        return d

    sector = d.get("sector", pd.Series("", index=d.index, dtype=str))
    tech_flag = sector_indicator(sector, ["technology", "communication"])
    energy_flag = sector_indicator(sector, ["energy"])
    materials_flag = sector_indicator(sector, ["materials"])
    defensive_flag = sector_indicator(sector, ["utilities", "consumer staples", "health care", "healthcare", "real estate"])

    beta_proxy = (
        cross_sectional_robust_z(d, "vol_252d")
        + cross_sectional_robust_z(d, "dd_1y")
        + cross_sectional_robust_z(d, "mom_6m")
    ) / 3.0
    duration_proxy = (
        -cross_sectional_robust_z(d, "ep_ttm")
        - cross_sectional_robust_z(d, "sp_ttm")
        - cross_sectional_robust_z(d, "fcfy_ttm")
        + cross_sectional_robust_z(d, "mom_6m")
    ) / 4.0
    defensive_quality_proxy = (
        cross_sectional_robust_z(d, "op_margin_ttm")
        + cross_sectional_robust_z(d, "roe_proxy")
        - cross_sectional_robust_z(d, "vol_252d")
        - cross_sectional_robust_z(d, "dd_1y")
    ) / 4.0
    momentum_proxy = (
        cross_sectional_robust_z(d, "mom_3m")
        + cross_sectional_robust_z(d, "mom_6m")
        + cross_sectional_robust_z(d, "dist_ma200")
    ) / 3.0

    vix = numeric_series_or_default(d, "vix_z_63d", 0.0)
    rates = numeric_series_or_default(d, "dgs10_change_1m", 0.0)
    qqq_rel = numeric_series_or_default(d, "qqq_rel_spy_1m", 0.0)
    smh_rel = numeric_series_or_default(d, "smh_rel_spy_1m", 0.0)
    oil = numeric_series_or_default(d, "uso_ret_1m", 0.0)
    copper = numeric_series_or_default(d, "cper_ret_1m", 0.0)
    risk_off = numeric_series_or_default(d, "macro_risk_off_score", 0.0)
    regime = numeric_series_or_default(d, "market_regime_score", 0.0)

    d["macro_beta_vix_interaction"] = beta_proxy * vix
    d["macro_duration_rate_interaction"] = duration_proxy * rates
    d["macro_tech_leadership_interaction"] = tech_flag * qqq_rel
    d["macro_semis_cycle_interaction"] = tech_flag * smh_rel
    d["macro_energy_oil_interaction"] = energy_flag * oil
    d["macro_materials_copper_interaction"] = materials_flag * copper
    d["macro_defensive_riskoff_interaction"] = defensive_flag * defensive_quality_proxy * risk_off
    d["macro_momentum_regime_interaction"] = momentum_proxy * regime

    return d


def compute_market_style_regime_features(df: pd.DataFrame) -> pd.DataFrame:
    """Research-only style regime router for breakout vs turnaround modes."""
    d = df.copy()
    if d.empty:
        for col in PHASE21_STYLE_REGIME_COLUMNS:
            d[col] = np.nan
        return d

    def num(col: str, default: float = 0.0) -> pd.Series:
        return numeric_series_or_default(d, col, default).astype(float)

    def clip01(series: pd.Series) -> pd.Series:
        return pd.to_numeric(series, errors="coerce").fillna(0.0).clip(lower=0.0, upper=1.0)

    def pos_scaled(col: str, scale: float = 0.10) -> pd.Series:
        return (num(col, 0.0) / scale).clip(lower=0.0, upper=1.0)

    market = clip01(num("market_regime_score", 0.50))
    liquidity = clip01(num("liquidity_regime_score", 0.50))
    liquidity_impulse = clip01(num("liquidity_impulse_score", 0.0))
    liquidity_drain = clip01(num("liquidity_drain_score", 0.0))
    growth_reentry = clip01(num("growth_liquidity_reentry_score", 0.0))
    risk_off = clip01(num("macro_risk_off_score", 0.0))
    inflation = clip01(num("inflation_pressure_score", 0.0))
    inflation_reaccel = clip01(num("inflation_reacceleration_score", 0.0))
    stagflation = clip01(num("stagflation_score", 0.0))
    breadth = clip01(num("market_breadth_regime_score", 0.50))
    participation = clip01(num("market_sector_participation", 0.35))
    narrowing = clip01(num("market_leadership_narrowing", 0.50))
    overheat = clip01(num("market_overheat_ratio", 0.0))
    bench_above = clip01(num("bench_above_ma200", np.nan).fillna(num("spy_above_ma200", 1.0)))
    qqq_rel = pos_scaled("qqq_rel_spy_1m", scale=0.06)
    vix_stress = clip01(num("vix_z_63d", 0.0) / 2.0)
    credit_stress = clip01(num("hy_oas_change_1m", 0.0) / 1.5)
    rate_pressure = clip01(
        0.45 * pos_scaled("dgs10_change_1m", scale=0.35)
        + 0.30 * inflation
        + 0.25 * inflation_reaccel
    )
    liquidity_tailwind = clip01(
        0.40 * liquidity
        + 0.25 * liquidity_impulse
        + 0.20 * growth_reentry
        + 0.15 * (1.0 - liquidity_drain)
    )
    overheat_risk = clip01(
        0.35 * overheat
        + 0.25 * narrowing
        + 0.20 * vix_stress
        + 0.20 * rate_pressure
    )
    cash_defense = clip01(
        0.28 * risk_off
        + 0.20 * vix_stress
        + 0.18 * credit_stress
        + 0.16 * (1.0 - bench_above)
        + 0.10 * liquidity_drain
        + 0.08 * stagflation
    )
    breakout_pref = clip01(
        0.24 * growth_reentry
        + 0.20 * market
        + 0.18 * liquidity_tailwind
        + 0.14 * qqq_rel
        + 0.12 * bench_above
        + 0.12 * breadth
        - 0.16 * overheat_risk
        - 0.10 * cash_defense
    )
    turnaround_pref = clip01(
        0.24 * liquidity_tailwind
        + 0.18 * growth_reentry
        + 0.16 * (1.0 - breadth)
        + 0.14 * (1.0 - participation)
        + 0.12 * clip01(rate_pressure * 0.6 + inflation * 0.4)
        + 0.10 * (1.0 - overheat)
        + 0.06 * (1.0 - qqq_rel)
        - 0.18 * cash_defense
    )
    quality_pref = clip01(
        0.24 * risk_off
        + 0.20 * rate_pressure
        + 0.16 * inflation
        + 0.14 * (1.0 - liquidity_tailwind)
        + 0.14 * bench_above
        + 0.12 * (1.0 - overheat)
    )

    labels = np.full(len(d), "balanced", dtype=object)
    labels = np.where(cash_defense >= 0.58, "cash_defense", labels)
    labels = np.where((breakout_pref >= turnaround_pref) & (breakout_pref >= quality_pref) & (breakout_pref >= 0.48) & (cash_defense < 0.58), "breakout_growth", labels)
    labels = np.where((turnaround_pref > breakout_pref) & (turnaround_pref >= quality_pref) & (turnaround_pref >= 0.45) & (cash_defense < 0.58), "turnaround_accumulation", labels)
    labels = np.where((quality_pref > breakout_pref) & (quality_pref > turnaround_pref) & (quality_pref >= 0.45) & (cash_defense < 0.58), "quality_compounder", labels)

    date_source = None
    for col in ("rebalance_date", "feature_date", "accepted"):
        if col in d.columns:
            date_source = pd.to_datetime(d[col], errors="coerce")
            break
    if date_source is None:
        date_source = pd.Series(pd.NaT, index=d.index)
    month = date_source.dt.month.fillna(0).astype(int)
    quarter = date_source.dt.quarter.fillna(0).astype(int)
    weekday = date_source.dt.weekday.fillna(0).astype(int)
    min_date = date_source.dropna().min() if date_source.notna().any() else pd.NaT
    years_since_start = pd.Series(0.0, index=d.index) if pd.isna(min_date) else (date_source - min_date).dt.days.fillna(0.0) / 365.25

    breakout_setup = row_mean(
        [
            numeric_series_or_default(d, "breakout_fresh_20d", 0.0),
            numeric_series_or_default(d, "post_breakout_hold_score", 0.0),
            numeric_series_or_default(d, "h6_dynamic_leader_score", 0.0),
            (numeric_series_or_default(d, "near_52w_high_pct", -1.0) >= -0.12).astype(float),
        ],
        d.index,
    ).fillna(0.0)
    turnaround_setup = row_mean(
        [
            numeric_series_or_default(d, "value_inflection_score", 0.0),
            numeric_series_or_default(d, "fundamental_turnaround_acceleration_score", 0.0),
            numeric_series_or_default(d, "h1_oversold_value_score", 0.0),
            numeric_series_or_default(d, "industry_rotation_signal", 0.0),
            numeric_series_or_default(d, "early_cycle_inflection_score", 0.0),
            numeric_series_or_default(d, "profitability_inflection_score", 0.0),
        ],
        d.index,
    ).fillna(0.0)
    compounder_setup = row_mean(
        [
            numeric_series_or_default(d, "long_hold_compounder_score", 0.0),
            numeric_series_or_default(d, "capital_efficiency_score", 0.0),
            numeric_series_or_default(d, "sector_adjusted_quality_score", 0.0),
            numeric_series_or_default(d, "moat_proxy_score", 0.0),
            numeric_series_or_default(d, "fundamental_reliability_score", 0.5),
        ],
        d.index,
    ).fillna(0.0)

    d["market_style_regime_label"] = pd.Series(labels, index=d.index, dtype=object)
    d["style_breakout_preference"] = breakout_pref
    d["style_turnaround_preference"] = turnaround_pref
    d["style_quality_compounder_preference"] = quality_pref
    d["style_cash_defense_preference"] = cash_defense
    d["style_liquidity_tailwind_score"] = liquidity_tailwind
    d["style_rate_pressure_score"] = rate_pressure
    d["style_inflation_pressure_score"] = clip01(0.6 * inflation + 0.4 * inflation_reaccel)
    d["style_overheat_risk_score"] = overheat_risk
    d["style_calendar_month"] = month
    d["style_calendar_quarter"] = quarter
    d["style_calendar_weekday"] = weekday
    d["style_calendar_years_since_start"] = years_since_start
    d["style_calendar_month_sin"] = np.sin(2.0 * np.pi * month.clip(lower=1) / 12.0)
    d["style_calendar_month_cos"] = np.cos(2.0 * np.pi * month.clip(lower=1) / 12.0)
    d["style_calendar_quarter_sin"] = np.sin(2.0 * np.pi * quarter.clip(lower=1) / 4.0)
    d["style_calendar_quarter_cos"] = np.cos(2.0 * np.pi * quarter.clip(lower=1) / 4.0)
    d["style_calendar_weekday_sin"] = np.sin(2.0 * np.pi * weekday.clip(lower=0) / 7.0)
    d["style_calendar_weekday_cos"] = np.cos(2.0 * np.pi * weekday.clip(lower=0) / 7.0)
    d["style_row_breakout_fit"] = (breakout_pref * breakout_setup).clip(lower=-6.0, upper=6.0)
    d["style_row_turnaround_fit"] = (turnaround_pref * turnaround_setup).clip(lower=-6.0, upper=6.0)
    d["style_row_compounder_fit"] = (quality_pref * compounder_setup).clip(lower=-6.0, upper=6.0)
    return d


# =====================================================================
# Stage 3d-iii: market/dynamic-leadership/manual-overlay/crisis (2026-04-20)
# =====================================================================
# Moved from r1000_top30_institutional.py:4245-4796 (6 functions):
#   compute_market_adaptation_features     (157L) -- market breadth + sector
#                                                  participation scoring
#   compute_dynamic_leadership_features    (180L) -- dominant/emerging leader
#                                                  composite (nested within_group_z)
#   load_manual_moat_overrides              (51L) -- YAML manual override loader
#   apply_manual_ticker_overlays            (87L) -- user override applier
#   compute_three_level_relative_strength   (38L) -- 3-tier RS
#   compute_crisis_sector_fit               (29L) -- crisis-regime beneficiary flag
#
# All pure DataFrame transforms (plus YAML loader which is IO).

def compute_market_adaptation_features(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    if d.empty:
        for c in MARKET_ADAPTATION_COLUMNS:
            d[c] = np.nan
        return d
    if "rebalance_date" not in d.columns:
        for c in MARKET_ADAPTATION_COLUMNS:
            d[c] = 0.0
        return d

    d = d.drop(columns=[c for c in MARKET_ADAPTATION_COLUMNS if c in d.columns], errors="ignore")

    d["rebalance_date"] = pd.to_datetime(d["rebalance_date"], errors="coerce")
    if "sector" not in d.columns:
        d["sector"] = "Unknown"
    d["sector"] = d["sector"].fillna("Unknown").astype(str)

    for c, default in [
        ("price_above_ma200", 0.0),
        ("price_above_ma150", 0.0),
        ("trend_template_relaxed", np.nan),
        ("ma50_above_ma150", 0.0),
        ("ma150_above_ma200", 0.0),
        ("near_52w_high_pct", np.nan),
        ("dist_ma200", np.nan),
        ("rsi14", np.nan),
        ("bb_pb", np.nan),
        ("mom_3m", 0.0),
        ("mom_6m", 0.0),
        ("quality_trend_score", 0.0),
    ]:
        if c not in d.columns:
            d[c] = default

    rows = []
    for rebalance_dt, g in d.groupby("rebalance_date", sort=False):
        gg = g.copy()
        if gg.empty:
            continue
        breadth_ma200 = float(pd.to_numeric(gg["price_above_ma200"], errors="coerce").fillna(0.0).mean())
        breadth_ma150 = float(pd.to_numeric(gg["price_above_ma150"], errors="coerce").fillna(0.0).mean())
        trend_ratio_raw = pd.to_numeric(gg.get("trend_template_relaxed"), errors="coerce")
        if trend_ratio_raw.notna().any():
            trend_ratio = float(trend_ratio_raw.fillna(0.0).mean())
        else:
            trend_ratio = float(
                row_mean(
                    [
                        pd.to_numeric(gg["price_above_ma150"], errors="coerce"),
                        pd.to_numeric(gg["ma50_above_ma150"], errors="coerce"),
                        pd.to_numeric(gg["ma150_above_ma200"], errors="coerce"),
                    ],
                    gg.index,
                ).fillna(0.0).mean()
            )
        near_high_ratio = float((pd.to_numeric(gg["near_52w_high_pct"], errors="coerce") >= -0.35).fillna(False).mean())
        overheat_ratio = float(
            (
                (pd.to_numeric(gg["dist_ma200"], errors="coerce") > 0.18)
                | (pd.to_numeric(gg["rsi14"], errors="coerce") > 72.0)
                | (pd.to_numeric(gg["bb_pb"], errors="coerce") > 0.92)
            ).fillna(False).mean()
        )

        sector_stats = (
            gg.groupby("sector", as_index=False)
            .agg(
                sector_mom_3m=("mom_3m", "mean"),
                sector_mom_6m=("mom_6m", "mean"),
                sector_breadth=("price_above_ma200", "mean"),
                sector_quality=("quality_trend_score", "mean"),
            )
        )
        sector_count = max(int(len(sector_stats)), 1)
        sector_participation = float(
            (
                (pd.to_numeric(sector_stats["sector_mom_3m"], errors="coerce") > 0.0)
                & (pd.to_numeric(sector_stats["sector_breadth"], errors="coerce") > 0.50)
            ).mean()
        ) if not sector_stats.empty else 0.0

        sector_mom_6m = numeric_series_or_default(sector_stats, "sector_mom_6m", 0.0).astype(float)
        sector_breadth = numeric_series_or_default(sector_stats, "sector_breadth", 0.0).astype(float)
        sector_quality = numeric_series_or_default(sector_stats, "sector_quality", 0.0).astype(float)
        strength = (
            pd.Series(np.clip(sector_mom_6m.to_numpy(dtype=float), 0.0, None), index=sector_stats.index, dtype=float)
            + 0.75
            * pd.Series(np.clip((sector_breadth - 0.50).to_numpy(dtype=float), 0.0, None), index=sector_stats.index, dtype=float)
            + 0.35
            * pd.Series(np.clip(sector_quality.to_numpy(dtype=float), 0.0, None), index=sector_stats.index, dtype=float)
        )
        if float(strength.sum()) > 0:
            weights = strength / float(strength.sum())
            hhi = float(np.square(weights).sum())
            min_hhi = 1.0 / float(sector_count)
            leadership_narrowing = float(
                np.clip((hhi - min_hhi) / max(1e-12, 1.0 - min_hhi), 0.0, 1.0)
            ) if sector_count > 1 else 1.0
        else:
            leadership_narrowing = 1.0 if sector_count <= 1 else 0.5

        breadth_regime = (
            0.24 * breadth_ma200
            + 0.18 * breadth_ma150
            + 0.16 * trend_ratio
            + 0.16 * near_high_ratio
            + 0.16 * sector_participation
            - 0.12 * overheat_ratio
            - 0.10 * leadership_narrowing
        )
        breadth_regime = float(np.clip(breadth_regime, 0.0, 1.0))
        rows.append(
            {
                "rebalance_date": rebalance_dt,
                "market_breadth_above_ma200": breadth_ma200,
                "market_breadth_above_ma150": breadth_ma150,
                "market_trend_template_ratio": trend_ratio,
                "market_near_high_ratio": near_high_ratio,
                "market_sector_participation": sector_participation,
                "market_leadership_narrowing": leadership_narrowing,
                "market_overheat_ratio": overheat_ratio,
                "market_breadth_regime_score": breadth_regime,
            }
        )

    breadth_df = pd.DataFrame(rows)
    if breadth_df.empty:
        for c in MARKET_ADAPTATION_COLUMNS:
            d[c] = np.nan
        return d
    breadth_df = breadth_df.sort_values("rebalance_date").reset_index(drop=True)
    smooth_cols = [
        "market_breadth_above_ma200",
        "market_breadth_above_ma150",
        "market_trend_template_ratio",
        "market_near_high_ratio",
        "market_sector_participation",
        "market_leadership_narrowing",
        "market_overheat_ratio",
    ]
    for c in smooth_cols:
        breadth_df[c] = (
            pd.to_numeric(breadth_df[c], errors="coerce")
            .rolling(3, min_periods=1)
            .mean()
        )
    breadth_df["market_breadth_regime_score"] = (
        0.24 * pd.to_numeric(breadth_df["market_breadth_above_ma200"], errors="coerce").fillna(0.0)
        + 0.18 * pd.to_numeric(breadth_df["market_breadth_above_ma150"], errors="coerce").fillna(0.0)
        + 0.16 * pd.to_numeric(breadth_df["market_trend_template_ratio"], errors="coerce").fillna(0.0)
        + 0.16 * pd.to_numeric(breadth_df["market_near_high_ratio"], errors="coerce").fillna(0.0)
        + 0.16 * pd.to_numeric(breadth_df["market_sector_participation"], errors="coerce").fillna(0.0)
        - 0.12 * pd.to_numeric(breadth_df["market_overheat_ratio"], errors="coerce").fillna(0.0)
        - 0.10 * pd.to_numeric(breadth_df["market_leadership_narrowing"], errors="coerce").fillna(0.0)
    ).clip(lower=0.0, upper=1.0)
    return d.merge(breadth_df, on="rebalance_date", how="left")


def compute_dynamic_leadership_features(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    if d.empty:
        for c in DYNAMIC_LEADER_COLUMNS:
            d[c] = np.nan
        return d
    if "rebalance_date" not in d.columns:
        for c in DYNAMIC_LEADER_COLUMNS:
            d[c] = 0.0
        return d

    # Recompute these columns from scratch so repeated calls on latest slices
    # do not create merge suffixes like sector_leader_score_x/_y.
    drop_cols = set(DYNAMIC_LEADER_COLUMNS)
    drop_cols |= {f"{c}_x" for c in DYNAMIC_LEADER_COLUMNS}
    drop_cols |= {f"{c}_y" for c in DYNAMIC_LEADER_COLUMNS}
    d = d.drop(columns=[c for c in drop_cols if c in d.columns], errors="ignore")

    d["rebalance_date"] = pd.to_datetime(d["rebalance_date"], errors="coerce")
    if "sector" not in d.columns:
        d["sector"] = "Unknown"
    d["sector"] = d["sector"].fillna("Unknown").astype(str)

    for c in [
        "mom_1m",
        "mom_3m",
        "mom_6m",
        "price_above_ma200",
        "price_above_ma150",
        "ma50_above_ma200",
        "ma50_above_ma150",
        "ma150_above_ma200",
        "dist_ma200",
        "near_52w_high_pct",
        "ma200_slope_1m",
        "breakout_volume_z",
        "volatility_contraction_score",
        "vol_252d",
        "dd_1y",
        "event_reaction_score",
        "quality_trend_score",
        "actual_results_score",
        "forward_value_score",
        "macro_tech_leadership_interaction",
        "macro_semis_cycle_interaction",
        "macro_energy_oil_interaction",
        "macro_momentum_regime_interaction",
        "macro_defensive_riskoff_interaction",
    ]:
        if c not in d.columns:
            d[c] = 0.0

    gcols = ["rebalance_date", "sector"]

    def within_group_z(col: str) -> pd.Series:
        return (
            d.groupby(gcols, group_keys=False)[col]
            .apply(lambda s: robust_z(pd.to_numeric(s, errors="coerce")).fillna(0.0))
            .reindex(d.index)
            .fillna(0.0)
        )

    sector_stats = (
        d.groupby(gcols, as_index=False)
        .agg(
            sector_avg_mom_6m=("mom_6m", "mean"),
            sector_avg_mom_3m=("mom_3m", "mean"),
            sector_breadth=("price_above_ma200", "mean"),
            sector_event=("event_reaction_score", "mean"),
            sector_actual=("actual_results_score", "mean"),
            sector_quality=("quality_trend_score", "mean"),
            sector_macro_fit=("macro_momentum_regime_interaction", "mean"),
            sector_macro_tech=("macro_tech_leadership_interaction", "mean"),
            sector_macro_semis=("macro_semis_cycle_interaction", "mean"),
            sector_macro_energy=("macro_energy_oil_interaction", "mean"),
            sector_high_tight=("near_52w_high_pct", "mean"),
            sector_breakout=("breakout_volume_z", "mean"),
            sector_contraction=("volatility_contraction_score", "mean"),
            sector_trend_slope=("ma200_slope_1m", "mean"),
            sector_safety=("dd_1y", "mean"),
        )
    )
    for c in [
        "sector_avg_mom_6m",
        "sector_avg_mom_3m",
        "sector_breadth",
        "sector_event",
        "sector_actual",
        "sector_quality",
        "sector_macro_fit",
        "sector_macro_tech",
        "sector_macro_semis",
        "sector_macro_energy",
        "sector_high_tight",
        "sector_breakout",
        "sector_contraction",
        "sector_trend_slope",
        "sector_safety",
    ]:
        sector_stats[f"{c}_z"] = (
            sector_stats.groupby("rebalance_date", group_keys=False)[c]
            .apply(lambda s: robust_z(pd.to_numeric(s, errors="coerce")).fillna(0.0))
            .reset_index(level=0, drop=True)
        )
    sector_stats["sector_leader_score"] = (
        0.24 * sector_stats["sector_avg_mom_6m_z"]
        + 0.12 * sector_stats["sector_avg_mom_3m_z"]
        + 0.14 * sector_stats["sector_breadth_z"]
        + 0.12 * sector_stats["sector_event_z"]
        + 0.12 * sector_stats["sector_actual_z"]
        + 0.10 * sector_stats["sector_quality_z"]
        + 0.08 * sector_stats["sector_macro_fit_z"]
        + 0.03 * sector_stats["sector_macro_tech_z"]
        + 0.03 * sector_stats["sector_macro_semis_z"]
        + 0.03 * sector_stats["sector_macro_energy_z"]
        + 0.07 * sector_stats["sector_high_tight_z"]
        + 0.05 * sector_stats["sector_breakout_z"]
        + 0.05 * sector_stats["sector_contraction_z"]
        + 0.04 * sector_stats["sector_trend_slope_z"]
        - 0.08 * sector_stats["sector_safety_z"]
    )
    sector_stats["sector_leader_score"] = winsorize(sector_stats["sector_leader_score"], 0.01).clip(-6.0, 6.0)
    d = d.merge(sector_stats[["rebalance_date", "sector", "sector_leader_score"]], on=["rebalance_date", "sector"], how="left")

    within_sector_score = row_mean(
        [
            within_group_z("mom_6m"),
            within_group_z("mom_3m"),
            within_group_z("near_52w_high_pct"),
            within_group_z("breakout_volume_z"),
            within_group_z("ma200_slope_1m"),
            within_group_z("event_reaction_score"),
            within_group_z("actual_results_score"),
            within_group_z("quality_trend_score"),
            -0.50 * within_group_z("vol_252d"),
            -0.35 * within_group_z("dd_1y"),
        ],
        d.index,
    )
    extension_penalty = cross_sectional_robust_z(d, "dist_ma200").abs().fillna(0.0)
    d["within_sector_leader_score"] = winsorize(pd.to_numeric(within_sector_score, errors="coerce").fillna(0.0), 0.01).clip(-6.0, 6.0)
    d["leader_emergence_score"] = row_mean(
        [
            cross_sectional_robust_z(d, "mom_1m"),
            cross_sectional_robust_z(d, "event_reaction_score"),
            cross_sectional_robust_z(d, "actual_results_score"),
            cross_sectional_robust_z(d, "quality_trend_score"),
            cross_sectional_robust_z(d, "near_52w_high_pct"),
            0.75 * cross_sectional_robust_z(d, "breakout_volume_z"),
            0.50 * cross_sectional_robust_z(d, "ma200_slope_1m"),
            0.50 * cross_sectional_robust_z(d, "macro_momentum_regime_interaction"),
            -0.35 * extension_penalty,
        ],
        d.index,
    ).fillna(0.0)
    d["leader_emergence_score"] = winsorize(d["leader_emergence_score"], 0.01).clip(-6.0, 6.0)
    d["leader_safety_score"] = row_mean(
        [
            -cross_sectional_robust_z(d, "vol_252d"),
            -cross_sectional_robust_z(d, "dd_1y"),
            cross_sectional_robust_z(d, "price_above_ma200"),
            cross_sectional_robust_z(d, "price_above_ma150"),
            cross_sectional_robust_z(d, "ma50_above_ma200"),
            cross_sectional_robust_z(d, "ma50_above_ma150"),
            cross_sectional_robust_z(d, "ma150_above_ma200"),
            0.50 * cross_sectional_robust_z(d, "volatility_contraction_score"),
            0.50 * cross_sectional_robust_z(d, "forward_value_score"),
            0.35 * cross_sectional_robust_z(d, "macro_defensive_riskoff_interaction"),
        ],
        d.index,
    ).fillna(0.0)
    d["leader_safety_score"] = winsorize(d["leader_safety_score"], 0.01).clip(-6.0, 6.0)
    d["dynamic_leader_score"] = (
        0.34 * pd.to_numeric(d["sector_leader_score"], errors="coerce").fillna(0.0)
        + 0.31 * pd.to_numeric(d["within_sector_leader_score"], errors="coerce").fillna(0.0)
        + 0.22 * pd.to_numeric(d["leader_emergence_score"], errors="coerce").fillna(0.0)
        + 0.13 * pd.to_numeric(d["leader_safety_score"], errors="coerce").fillna(0.0)
    )
    d["dynamic_leader_score"] = winsorize(d["dynamic_leader_score"], 0.01).clip(-6.0, 6.0)
    return d


def load_manual_moat_overrides(cfg: EngineConfig) -> pd.DataFrame:
    candidate_paths: list[Path] = []
    if str(cfg.manual_moat_path).strip():
        candidate_paths.append(Path(str(cfg.manual_moat_path).strip()))
    base = Path(cfg.base_dir)
    candidate_paths.append(base / "manual_moat_overrides.csv")
    candidate_paths.append(base / "baseline" / "manual_moat_overrides.csv")

    keep_cols = [
        "ticker",
        "moat_score_manual",
        "ai_infra_exposure",
        "power_infra_exposure",
        "defense_exposure",
        "energy_hedge_exposure",
        "structural_value_exposure",
        "effective_from",
        "expires_on",
        "confidence",
        "reviewed_at",
    ]
    for path in candidate_paths:
        try:
            if not path.exists():
                continue
            raw = pd.read_csv(path)
            if raw.empty or "ticker" not in raw.columns:
                continue
            out = raw.copy()
            out["ticker"] = out["ticker"].map(normalize_ticker)
            out = out[out["ticker"].map(is_valid_ticker)].copy()
            for c in [
                "moat_score_manual",
                "ai_infra_exposure",
                "power_infra_exposure",
                "defense_exposure",
                "energy_hedge_exposure",
                "structural_value_exposure",
                "confidence",
            ]:
                if c not in out.columns:
                    out[c] = np.nan
                out[c] = pd.to_numeric(out[c], errors="coerce")
            for c in ["effective_from", "expires_on", "reviewed_at"]:
                if c not in out.columns:
                    out[c] = pd.NaT
                out[c] = pd.to_datetime(out[c], errors="coerce")
            return out[keep_cols].drop_duplicates("ticker")
        except Exception:
            continue
    return pd.DataFrame(columns=keep_cols)


def apply_manual_ticker_overlays(df: pd.DataFrame, cfg: EngineConfig) -> pd.DataFrame:
    d = df.copy()
    tickers = d.get("ticker", pd.Series("", index=d.index, dtype=str)).astype(str).str.upper()
    overlays = load_manual_moat_overrides(cfg)
    overlay_cols = [
        "moat_score_manual",
        "ai_infra_exposure",
        "power_infra_exposure",
        "defense_exposure",
        "energy_hedge_exposure",
        "structural_value_exposure",
    ]
    if not overlays.empty:
        mapped = overlays.copy()
        mapped = mapped.rename(columns={c: f"{c}_overlay" for c in mapped.columns if c != "ticker"})
        d = d.merge(mapped, on="ticker", how="left")
        rebalance = datetime_series_or_default(d, "rebalance_date")
        effective_from = datetime_series_or_default(d, "effective_from_overlay")
        expires_on = datetime_series_or_default(d, "expires_on_overlay")
        reviewed_at = datetime_series_or_default(d, "reviewed_at_overlay")
        confidence = numeric_series_or_default(d, "confidence_overlay", 1.0).clip(lower=0.0, upper=1.0)

        active = pd.Series(True, index=d.index, dtype=bool)
        active &= effective_from.isna() | (rebalance >= effective_from)
        active &= expires_on.isna() | (rebalance <= expires_on)

        review_age_days = (rebalance - reviewed_at).dt.days
        review_age_days = review_age_days.where(review_age_days >= 0, 0.0).fillna(0.0)
        half_life = max(int(cfg.manual_moat_half_life_days), 1)
        decay = np.exp(-np.log(2.0) * (review_age_days / float(half_life)))
        overlay_strength = (active.astype(float) * confidence * decay).clip(lower=0.0, upper=1.0)

        d["manual_moat_override_active"] = active.astype(float)
        d["manual_moat_override_confidence"] = confidence
        d["manual_moat_override_decay"] = decay
        d["manual_moat_override_strength"] = overlay_strength
        for c in overlay_cols:
            existing = (
                pd.to_numeric(d.get(c), errors="coerce")
                if c in d.columns
                else pd.Series(np.nan, index=d.index, dtype=float)
            )
            overlay_series = numeric_series_or_default(d, f"{c}_overlay", np.nan)
            overlay_series = overlay_series * overlay_strength
            d[c] = existing.where(existing.notna(), overlay_series)
        d = d.drop(
            columns=[
                f"{c}_overlay"
                for c in [
                    "moat_score_manual",
                    "ai_infra_exposure",
                    "power_infra_exposure",
                    "defense_exposure",
                    "energy_hedge_exposure",
                    "structural_value_exposure",
                    "effective_from",
                    "expires_on",
                    "confidence",
                    "reviewed_at",
                ]
            ],
            errors="ignore",
        )
    else:
        d["manual_moat_override_active"] = 0.0
        d["manual_moat_override_confidence"] = 0.0
        d["manual_moat_override_decay"] = 0.0
        d["manual_moat_override_strength"] = 0.0

    ai_default = tickers.isin({str(t).upper() for t in cfg.focus_ai_infra_tickers}).astype(float)
    power_default = tickers.isin({str(t).upper() for t in cfg.focus_power_infra_tickers}).astype(float)
    defense_names = {str(t).upper() for t in (cfg.focus_defense_tickers or cfg.focus_hedge_tickers)}
    energy_names = {str(t).upper() for t in cfg.focus_energy_hedge_tickers}
    defense_default = tickers.isin(defense_names).astype(float)
    # Auto-detect energy sector stocks (was manual-only, causing 0% energy in crisis)
    sector_is_energy = d["sector"].astype(str).str.upper().isin({"ENERGY"}).astype(float) if "sector" in d.columns else pd.Series(0.0, index=d.index)
    energy_default = np.maximum(tickers.isin(energy_names).astype(float), sector_is_energy)
    structural_default = tickers.isin({str(t).upper() for t in cfg.focus_watchlist_tickers}).astype(float) * 0.0

    if "moat_score_manual" not in d.columns:
        d["moat_score_manual"] = np.nan
    d["ai_infra_exposure"] = numeric_series_or_default(d, "ai_infra_exposure", np.nan).fillna(ai_default)
    d["power_infra_exposure"] = numeric_series_or_default(d, "power_infra_exposure", np.nan).fillna(power_default)
    d["defense_exposure"] = numeric_series_or_default(d, "defense_exposure", np.nan).fillna(defense_default)
    d["energy_hedge_exposure"] = numeric_series_or_default(d, "energy_hedge_exposure", np.nan).fillna(energy_default)
    d["structural_value_exposure"] = numeric_series_or_default(d, "structural_value_exposure", np.nan).fillna(structural_default)
    return d


def compute_three_level_relative_strength(df: pd.DataFrame) -> pd.DataFrame:
    """Compute composite RS: stock-vs-market, stock-vs-sector, sector-vs-market."""
    d = df.copy()
    # Tier 1: Stock vs Market
    rs_m1 = numeric_series_or_default(d, "rs_benchmark_1m", 0.0)
    rs_m3 = numeric_series_or_default(d, "rs_benchmark_3m", 0.0)
    rs_m6 = numeric_series_or_default(d, "rs_benchmark_6m", 0.0)
    rs_m12 = numeric_series_or_default(d, "rs_benchmark_12m", 0.0)
    d["rs_market_composite"] = 0.15 * rs_m1 + 0.30 * rs_m3 + 0.35 * rs_m6 + 0.20 * rs_m12

    # Tier 2: Stock vs Sector
    rs_s1 = numeric_series_or_default(d, "rs_sector_1m", 0.0)
    rs_s3 = numeric_series_or_default(d, "rs_sector_3m", 0.0)
    rs_s6 = numeric_series_or_default(d, "rs_sector_6m", 0.0)
    rs_s12 = numeric_series_or_default(d, "rs_sector_12m", 0.0)
    d["rs_sector_composite"] = 0.15 * rs_s1 + 0.30 * rs_s3 + 0.35 * rs_s6 + 0.20 * rs_s12

    # Tier 3: Sector vs Market (reuse sector_leader_score)
    sl = numeric_series_or_default(d, "sector_leader_score", 0.0)

    # Composite: z-score normalize within each rebalance date, then blend
    if "rebalance_date" in d.columns:
        rs_mkt_z = d.groupby("rebalance_date", group_keys=False)["rs_market_composite"].apply(
            lambda s: robust_z(s).fillna(0.0)
        ).reindex(d.index).fillna(0.0)
        rs_sec_z = d.groupby("rebalance_date", group_keys=False)["rs_sector_composite"].apply(
            lambda s: robust_z(s).fillna(0.0)
        ).reindex(d.index).fillna(0.0)
    else:
        rs_mkt_z = robust_z(d["rs_market_composite"]).fillna(0.0)
        rs_sec_z = robust_z(d["rs_sector_composite"]).fillna(0.0)

    d["relative_strength_composite"] = 0.40 * rs_mkt_z + 0.35 * rs_sec_z + 0.25 * sl

    # RS acceleration (momentum of momentum): 3-month delta
    d["rs_market_acceleration"] = d["rs_market_composite"] - d.groupby("cik10" if "cik10" in d.columns else "ticker")["rs_market_composite"].shift(3).fillna(0.0)
    d["rs_sector_acceleration"] = d["rs_sector_composite"] - d.groupby("cik10" if "cik10" in d.columns else "ticker")["rs_sector_composite"].shift(3).fillna(0.0)
    return d


def compute_crisis_sector_fit(df: pd.DataFrame) -> pd.DataFrame:
    """Score stocks by alignment to active crisis regime beneficiary sectors."""
    d = df.copy()
    d["crisis_sector_beneficiary_score"] = 0.0
    if "sector" not in d.columns:
        return d
    sector_upper = d["sector"].astype(str).str.strip()

    regime_cols = {
        "war_oil_rate_shock": "war_oil_rate_shock_score",
        "systemic_crisis": "systemic_crisis_score",
        "stagflation": "stagflation_score",
        "carry_unwind": "carry_unwind_score",
    }
    for crisis_key, regime_col in regime_cols.items():
        if regime_col not in d.columns:
            continue
        regime_strength = pd.to_numeric(d[regime_col], errors="coerce").fillna(0.0)
        if (regime_strength <= 0.01).all():
            continue
        beneficiaries = CRISIS_SECTOR_BENEFICIARIES.get(crisis_key, {})
        for sector_name, sector_weight in beneficiaries.items():
            mask = sector_upper == sector_name
            if mask.any():
                d.loc[mask, "crisis_sector_beneficiary_score"] += (
                    regime_strength.loc[mask] * sector_weight
                )
    d["crisis_sector_beneficiary_score"] = d["crisis_sector_beneficiary_score"].clip(upper=1.0)
    return d


# =====================================================================
# Stage 3d-iv: strategy blueprint + pillar + minervini (2026-04-20)
# =====================================================================
# Moved from r1000_top30_institutional.py:
#   compute_strategy_blueprint_columns       (was 4259-5184, 926L)
#   compute_multidimensional_pillar_scores   (was 5187-5372, 186L)
#   compute_minervini_momentum_overlay       (was 5988-6131, 144L)
#
# compute_strategy_blueprint_columns is the LARGEST function in the codebase.
# Phase 1 alpha (turnaround + value + uptrend) scoring lives here. It has
# nested helper sector_median that stays encapsulated.
#
# Sleeve/portfolio functions that lived between blueprint and minervini
# (compute_regime_portfolio_controls, compute_benchmark_beating_focus_overlay)
# remain in main -- they are Stage 4 (sleeve composition) targets, not 3d.

def compute_strategy_blueprint_columns(df: pd.DataFrame, cfg: EngineConfig) -> pd.DataFrame:
    d = apply_manual_ticker_overlays(df.copy(), cfg)
    if d.empty:
        for c in [
            "revision_blueprint_score",
            "growth_blueprint_score",
            "valuation_blueprint_score",
            "moat_quality_blueprint_score",
            "technical_blueprint_score",
            "profitability_inflection_score",
            "anticipatory_growth_confirmation",
            "anticipatory_growth_score",
            "archetype_emerging_growth_score",
            "archetype_compounder_score",
            "archetype_cyclical_recovery_score",
            "archetype_defensive_value_score",
            "archetype_alignment_score",
            "dominant_archetype_score",
            "dominant_archetype_confidence",
            "dominant_archetype_label",
            "future_winner_scout_score",
            "long_hold_compounder_score",
            "macro_hedge_score",
            "strategy_blueprint_score",
            "watchlist_quality_penalty",
            # Phase 1 new alpha signals
            "fundamental_turnaround_acceleration_score",
            "cashflow_inflection_under_loss_score",
            "value_inflection_score",
            "uptrend_continuation_score",
            "uptrend_breakdown_penalty",
        ]:
            d[c] = np.nan
        return d

    if "sector" not in d.columns:
        d["sector"] = "Unknown"
    d["sector"] = d["sector"].fillna("Unknown").astype(str)
    if "rebalance_date" in d.columns:
        d["rebalance_date"] = pd.to_datetime(d["rebalance_date"], errors="coerce")
    groupers: list[pd.Series] = [d["sector"]]
    if "rebalance_date" in d.columns and d["rebalance_date"].notna().any():
        groupers = [d["rebalance_date"], d["sector"]]

    def sector_median(col: str) -> pd.Series:
        if col not in d.columns:
            return pd.Series(np.nan, index=d.index, dtype=float)
        s = pd.to_numeric(d[col], errors="coerce")
        return s.groupby(groupers).transform("median")

    forward_pe = numeric_series_or_default(d, "forward_pe_final", np.nan).replace(0, np.nan)
    ev_to_ebitda = numeric_series_or_default(d, "ev_to_ebitda_final", np.nan).replace(0, np.nan)
    fcf_yield = numeric_series_or_default(d, "fcfy_ttm", np.nan)
    sector_pe_med = sector_median("forward_pe_final").replace(0, np.nan)
    sector_ev_med = sector_median("ev_to_ebitda_final").replace(0, np.nan)
    sector_fcf_med = sector_median("fcfy_ttm")

    pe_rel = np.log(forward_pe / sector_pe_med)
    ev_rel = np.log(ev_to_ebitda / sector_ev_med)
    fcf_rel = fcf_yield - sector_fcf_med

    target_support = row_mean(
        [
            cross_sectional_robust_z(d, "target_upside_pct"),
            -cross_sectional_robust_z(d, "recommendation_mean"),
        ],
        d.index,
    ).fillna(0.0)
    guidance_proxy = row_mean(
        [
            cross_sectional_robust_z(d, "actual_results_score"),
            cross_sectional_robust_z(d, "earn_gap_1d"),
        ],
        d.index,
    ).fillna(0.0)
    revision_proxy = row_mean(
        [
            cross_sectional_robust_z(d, "eps_revision_proxy"),
            cross_sectional_robust_z(d, "eps_est_fy1"),
            cross_sectional_robust_z(d, "eps_est_fy2"),
            cross_sectional_robust_z(d, "rev_est_fy1"),
            cross_sectional_robust_z(d, "rev_est_fy2"),
            cross_sectional_robust_z(d, "revision_score"),
        ],
        d.index,
    ).fillna(0.0)
    revision_cov = numeric_series_or_default(d, "revision_coverage_ratio", 0.0).clip(lower=0.0, upper=1.0)
    d["revision_blueprint_score"] = (
        0.60 * revision_proxy
        + 0.20 * target_support
        + 0.20 * guidance_proxy
    ) * (0.55 + 0.45 * revision_cov)

    d["growth_blueprint_score"] = (
        # Use _cagr_best (3y preferred, falls back to 2y then 1y) for broader coverage
        0.10 * cross_sectional_robust_z(d, "sales_cagr_best")
        + 0.06 * cross_sectional_robust_z(d, "sales_cagr_5y")
        + 0.08 * cross_sectional_robust_z(d, "op_income_cagr_best")
        + 0.05 * cross_sectional_robust_z(d, "op_income_cagr_5y")
        + 0.06 * cross_sectional_robust_z(d, "net_income_cagr_best")
        + 0.04 * cross_sectional_robust_z(d, "net_income_cagr_5y")
        + 0.06 * cross_sectional_robust_z(d, "ocf_cagr_best")
        + 0.03 * cross_sectional_robust_z(d, "ocf_cagr_5y")
        + 0.05 * cross_sectional_robust_z(d, "eps_cagr_best")
        + 0.05 * cross_sectional_robust_z(d, "fcf_cagr_best")
        + 0.14 * cross_sectional_robust_z(d, "revenue_growth_final")
        + 0.12 * cross_sectional_robust_z(d, "earnings_growth_final")
        + 0.06 * cross_sectional_robust_z(d, "sales_growth_yoy")
        + 0.04 * cross_sectional_robust_z(d, "ocf_growth_yoy")
        + 0.06 * cross_sectional_robust_z(d, "actual_results_score")
    ).fillna(0.0)

    d["valuation_blueprint_score"] = (
        0.24 * -robust_z(pe_rel).fillna(0.0)
        + 0.22 * -robust_z(ev_rel).fillna(0.0)
        + 0.20 * robust_z(fcf_rel).fillna(0.0)
        + 0.20 * -cross_sectional_robust_z(d, "peg_final")
        + 0.14 * -cross_sectional_robust_z(d, "forward_ps_final")
    ).fillna(0.0)

    moat_manual_raw = numeric_series_or_default(d, "moat_score_manual", np.nan)
    moat_manual_score = robust_z(moat_manual_raw).fillna(0.0)
    moat_proxy_score = cross_sectional_robust_z(d, "moat_proxy_score").fillna(0.0)
    moat_anchor = pd.Series(
        np.where(moat_manual_raw.notna(), 0.60 * moat_manual_score + 0.40 * moat_proxy_score, moat_proxy_score),
        index=d.index,
        dtype=float,
    )
    d["moat_quality_blueprint_score"] = (
        0.30 * moat_anchor
        + 0.18 * cross_sectional_robust_z(d, "op_margin_ttm")
        + 0.14 * cross_sectional_robust_z(d, "gp_to_assets_ttm")
        + 0.14 * cross_sectional_robust_z(d, "roe_proxy")
        + 0.12 * cross_sectional_robust_z(d, "quality_trend_score")
        + 0.06 * cross_sectional_robust_z(d, "margin_stability_8q")
        + 0.06 * cross_sectional_robust_z(d, "pricing_power_score")
        - 0.10 * cross_sectional_robust_z(d, "debt_to_equity")
    ).fillna(0.0)

    breadth_regime = numeric_series_or_default(d, "market_breadth_regime_score", 0.50).clip(lower=0.0, upper=1.0)
    sector_participation = numeric_series_or_default(d, "market_sector_participation", 0.35).clip(lower=0.0, upper=1.0)
    leadership_narrowing = numeric_series_or_default(d, "market_leadership_narrowing", 0.50).clip(lower=0.0, upper=1.0)
    market_overheat = numeric_series_or_default(d, "market_overheat_ratio", 0.0).clip(lower=0.0, upper=1.0)
    systemic_crisis = numeric_series_or_default(d, "systemic_crisis_score", 0.0).clip(lower=0.0, upper=1.0)
    carry_unwind = numeric_series_or_default(d, "carry_unwind_stress_score", 0.0).clip(lower=0.0, upper=1.0)
    war_oil_rate = numeric_series_or_default(d, "war_oil_rate_shock_score", 0.0).clip(lower=0.0, upper=1.0)
    defensive_rotation = numeric_series_or_default(d, "defensive_rotation_score", 0.0).clip(lower=0.0, upper=1.0)
    growth_reentry = numeric_series_or_default(d, "growth_reentry_score", 0.0).clip(lower=0.0, upper=1.0)
    inflation_reaccel = numeric_series_or_default(d, "inflation_reacceleration_score", 0.0).clip(lower=0.0, upper=1.0)
    upstream_cost = numeric_series_or_default(d, "upstream_cost_pressure_score", 0.0).clip(lower=0.0, upper=1.0)
    labor_softening = numeric_series_or_default(d, "labor_softening_score", 0.0).clip(lower=0.0, upper=1.0)
    stagflation = numeric_series_or_default(d, "stagflation_score", 0.0).clip(lower=0.0, upper=1.0)
    growth_liquidity = numeric_series_or_default(d, "growth_liquidity_reentry_score", 0.0).clip(lower=0.0, upper=1.0)
    benchmark_alpha = row_mean(
        [
            cross_sectional_robust_z(d, "rs_benchmark_3m"),
            cross_sectional_robust_z(d, "rs_benchmark_6m"),
            cross_sectional_robust_z(d, "rs_benchmark_12m"),
            0.60 * cross_sectional_robust_z(d, "dd_gap_benchmark"),
        ],
        d.index,
    ).fillna(0.0)

    rsi_penalty = ((numeric_series_or_default(d, "rsi14", np.nan) - 75.0) / 10.0).clip(lower=0.0).fillna(0.0)
    timing_confirmation = row_mean(
        [
            numeric_series_or_default(d, "price_above_ma20", 0.0),
            numeric_series_or_default(d, "ma20_above_ma50", 0.0),
            numeric_series_or_default(d, "golden_cross_fresh_20d", 0.0),
            numeric_series_or_default(d, "breakout_fresh_20d", 0.0),
            cross_sectional_robust_z(d, "breakout_volume_z"),
            numeric_series_or_default(d, "post_breakout_hold_score", 0.0),
            cross_sectional_robust_z(d, "volume_dryup_20d"),
        ],
        d.index,
    ).fillna(0.0)
    breakdown_penalty = row_mean(
        [
            numeric_series_or_default(d, "death_cross_recent_20d", 0.0),
            cross_sectional_robust_z(d, "atr14_pct").clip(lower=0.0).fillna(0.0),
        ],
        d.index,
    ).fillna(0.0)
    trend_template_weight = 0.14 + 0.06 * breadth_regime + 0.02 * sector_participation
    high_tight_weight = (0.06 + 0.06 * breadth_regime - 0.03 * leadership_narrowing).clip(lower=0.02)
    overheat_penalty_weight = (
        0.04
        + 0.10 * leadership_narrowing
        + 0.08 * market_overheat
        + 0.06 * np.clip(0.50 - breadth_regime, 0.0, None)
    )
    d["technical_blueprint_score"] = (
        0.18 * cross_sectional_robust_z(d, "mom_6m")
        + 0.16 * cross_sectional_robust_z(d, "mom_12m")
        + 0.14 * cross_sectional_robust_z(d, "rs_sector_6m")
        + 0.14 * cross_sectional_robust_z(d, "near_52w_high_pct")
        + 0.10 * benchmark_alpha
        + trend_template_weight * numeric_series_or_default(d, "trend_template_relaxed", 0.0)
        + 0.10 * numeric_series_or_default(d, "trend_template_full", 0.0)
        + high_tight_weight * numeric_series_or_default(d, "high_tight_30_bonus", 0.0)
        + 0.10 * timing_confirmation
        + float(cfg.growth_reentry_strength)
        * growth_reentry
        * row_mean(
            [
                cross_sectional_robust_z(d, "rs_benchmark_3m"),
                cross_sectional_robust_z(d, "rs_benchmark_6m"),
                cross_sectional_robust_z(d, "mom_6m"),
                0.60 * cross_sectional_robust_z(d, "revision_score"),
            ],
            d.index,
        ).fillna(0.0)
        - 0.06 * rsi_penalty
        - overheat_penalty_weight * numeric_series_or_default(d, "overheat_penalty", 0.0)
        - 0.06 * breakdown_penalty
        - 0.08 * defensive_rotation * cross_sectional_robust_z(d, "vol_252d").clip(lower=0.0).fillna(0.0)
    ).fillna(0.0)

    negative_margin = np.clip(-numeric_series_or_default(d, "op_margin_ttm", 0.0), 0.0, None)
    deep_negative_margin_penalty = robust_z(negative_margin).clip(lower=0.0).fillna(0.0)
    leverage_penalty = cross_sectional_robust_z(d, "debt_to_equity").clip(lower=0.0).fillna(0.0)
    d["profitability_inflection_score"] = (
        0.24 * cross_sectional_robust_z(d, "margin_trend_4q")
        + 0.18 * cross_sectional_robust_z(d, "rev_growth_accel_4q")
        + 0.14 * cross_sectional_robust_z(d, "event_reaction_score")
        + 0.12 * cross_sectional_robust_z(d, "earn_gap_1d")
        + 0.12 * cross_sectional_robust_z(d, "ocf_ni_quality_4q")
        + 0.10 * cross_sectional_robust_z(d, "actual_results_score")
        + 0.10 * benchmark_alpha
        - 0.08 * deep_negative_margin_penalty
        - 0.08 * leverage_penalty
    ).fillna(0.0)

    # =====================================================================
    # Phase 1.1+1.2: Turnaround / cash-flow inflection scores
    # =====================================================================
    # These scores hunt for the WDC/LITE-style setup the system was missing
    # before: revenue still growing AND a real loss-to-profit transition (or
    # loss-narrowing) on the operating-income / OCF / FCF / EBITDA lines, with
    # leverage improving and accruals quality holding up.  We rely on the
    # panel-level sign-flip and loss-narrowing features added in
    # `add_fundamental_features` (op_income_sign_flip_pos, ocf_sign_flip_pos,
    # fcf_sign_flip_pos, ni_sign_flip_pos, op_income_loss_narrowing_4q,
    # ocf_loss_narrowing_4q, fcf_loss_narrowing_4q, ocf_under_loss_growth,
    # fcf_under_loss_growth) which carry through the standard fundamental
    # ffill pipeline.
    op_inc_flip = numeric_series_or_default(d, "op_income_sign_flip_pos", 0.0).clip(0.0, 1.0)
    ocf_flip = numeric_series_or_default(d, "ocf_sign_flip_pos", 0.0).clip(0.0, 1.0)
    fcf_flip = numeric_series_or_default(d, "fcf_sign_flip_pos", 0.0).clip(0.0, 1.0)
    ni_flip = numeric_series_or_default(d, "ni_sign_flip_pos", 0.0).clip(0.0, 1.0)
    gp_flip = numeric_series_or_default(d, "gp_sign_flip_pos", 0.0).clip(0.0, 1.0)
    op_inc_narrowing = numeric_series_or_default(d, "op_income_loss_narrowing_4q", 0.0).clip(-1.0, 2.0)
    fcf_narrowing = numeric_series_or_default(d, "fcf_loss_narrowing_4q", 0.0).clip(-1.0, 2.0)
    ocf_narrowing = numeric_series_or_default(d, "ocf_loss_narrowing_4q", 0.0).clip(-1.0, 2.0)
    ni_narrowing = numeric_series_or_default(d, "ni_loss_narrowing_4q", 0.0).clip(-1.0, 2.0)
    ocf_under_loss = numeric_series_or_default(d, "ocf_under_loss_growth", 0.0).clip(0.0, 1.0)
    fcf_under_loss = numeric_series_or_default(d, "fcf_under_loss_growth", 0.0).clip(0.0, 1.0)

    sales_yoy_v = numeric_series_or_default(d, "sales_growth_yoy", 0.0).fillna(0.0)
    rev_growth_pos = (sales_yoy_v > 0.0).astype(float)
    rev_growth_strong = (sales_yoy_v > 0.10).astype(float)

    # Gate sign-flips on the existence of revenue growth so we don't reward
    # cost-cutting-only profitability swings (those are not turnarounds we
    # want to ride).
    op_flip_gated = op_inc_flip * rev_growth_pos
    ocf_flip_gated = ocf_flip * rev_growth_pos
    fcf_flip_gated = fcf_flip * rev_growth_pos
    ni_flip_gated = ni_flip * rev_growth_pos
    gp_flip_gated = gp_flip * rev_growth_pos

    # === Fundamental turnaround acceleration score ===========================
    # Captures: revenue acceleration + multi-line P&L loss-to-profit flip +
    # narrowing losses + improving leverage + earnings revisions confirming.
    revision_alpha = cross_sectional_robust_z(d, "revision_score").fillna(0.0)
    margin_expansion_at_growth = cross_sectional_robust_z(d, "margin_expansion_at_growth").fillna(0.0)
    deleveraging_alpha = (-cross_sectional_robust_z(d, "debt_to_equity_delta_4q")).fillna(0.0)
    accruals_quality_alpha = cross_sectional_robust_z(d, "ocf_ni_quality_4q").fillna(0.0)

    d["fundamental_turnaround_acceleration_score"] = (
        0.18 * cross_sectional_robust_z(d, "rev_growth_accel_4q")
        + 0.13 * robust_z(op_flip_gated).fillna(0.0)
        + 0.10 * robust_z(ni_flip_gated).fillna(0.0)
        + 0.08 * robust_z(gp_flip_gated).fillna(0.0)
        + 0.10 * cross_sectional_robust_z(d, "margin_trend_4q")
        + 0.07 * robust_z(op_inc_narrowing.clip(lower=0.0)).fillna(0.0)
        + 0.05 * robust_z(ni_narrowing.clip(lower=0.0)).fillna(0.0)
        + 0.06 * cross_sectional_robust_z(d, "growth_inflection_signal")
        + 0.05 * margin_expansion_at_growth
        + 0.05 * cross_sectional_robust_z(d, "revenue_accel_2nd_deriv")
        + 0.04 * cross_sectional_robust_z(d, "roe_trend_4q")
        + 0.05 * deleveraging_alpha
        + 0.04 * accruals_quality_alpha
        + 0.04 * revision_alpha
        - 0.06 * deep_negative_margin_penalty
        - 0.04 * leverage_penalty
    ).fillna(0.0)

    # === Cashflow inflection under loss score ================================
    # OCF/FCF turning positive (or sharply improving) while net income is
    # still negative — the classic Lynch/O'Neil "cash flow leads earnings"
    # leading indicator of a turnaround.  Also rewards firms with high
    # OCF/NI quality already running cash-positive while consensus still
    # treats them as loss-makers.
    ocf_quality_v = numeric_series_or_default(d, "ocf_ni_quality_4q", 0.0).fillna(0.0)
    cashflow_quality_inflection = (
        (ocf_quality_v > 1.0).astype(float) * ocf_quality_v.clip(0.0, 3.0)
    )
    fcf_pos_growing = (
        (numeric_series_or_default(d, "fcf_ttm", 0.0) > 0.0).astype(float)
        * rev_growth_strong
    )
    op_yoy_alpha = cross_sectional_robust_z(d, "op_income_growth_yoy").fillna(0.0)
    ocf_yoy_alpha = cross_sectional_robust_z(d, "ocf_growth_yoy").fillna(0.0)
    fcf_yoy_alpha = cross_sectional_robust_z(d, "fcf_growth_yoy").fillna(0.0)

    d["cashflow_inflection_under_loss_score"] = (
        0.18 * robust_z(ocf_under_loss).fillna(0.0)
        + 0.16 * robust_z(fcf_under_loss).fillna(0.0)
        + 0.10 * robust_z(ocf_flip_gated).fillna(0.0)
        + 0.10 * robust_z(fcf_flip_gated).fillna(0.0)
        + 0.08 * robust_z(fcf_pos_growing).fillna(0.0)
        + 0.08 * accruals_quality_alpha
        + 0.06 * robust_z(cashflow_quality_inflection).fillna(0.0)
        + 0.05 * robust_z(ocf_narrowing.clip(lower=0.0)).fillna(0.0)
        + 0.05 * robust_z(fcf_narrowing.clip(lower=0.0)).fillna(0.0)
        + 0.05 * ocf_yoy_alpha
        + 0.05 * fcf_yoy_alpha
        + 0.04 * op_yoy_alpha
        + 0.04 * cross_sectional_robust_z(d, "rev_growth_accel_4q")
        - 0.06 * leverage_penalty
    ).fillna(0.0)

    # =====================================================================
    # Phase 1.3: Value inflection score (cheap + growing + reversing)
    # =====================================================================
    # Targets the setup the user described: a stock whose PE is
    # compressing because earnings/revenue are growing faster than the
    # price (or the price has been beaten down), AND the chart has just
    # started to reverse from oversold / Stage 1 base.  Hunts for the
    # "expectations gap closing" trade — a value-and-growth combination
    # that classic momentum-only models miss.
    near_high = numeric_series_or_default(d, "near_52w_high_pct", 0.0)
    dd_1y_v = numeric_series_or_default(d, "dd_1y", 0.0).clip(lower=0.0, upper=1.5)
    mom_1m_v = numeric_series_or_default(d, "mom_1m", 0.0)
    mom_3m_v = numeric_series_or_default(d, "mom_3m", 0.0)
    mom_6m_v = numeric_series_or_default(d, "mom_6m", 0.0)
    price_above_ma50_v = numeric_series_or_default(d, "price_above_ma50", 0.0).clip(0.0, 1.0)
    price_above_ma200_v = numeric_series_or_default(d, "price_above_ma200", 0.0).clip(0.0, 1.0)
    ma50_above_ma200_v = numeric_series_or_default(d, "ma50_above_ma200", 0.0).clip(0.0, 1.0)

    eps_growth_yoy_v = numeric_series_or_default(d, "eps_growth_yoy", np.nan)
    op_inc_growth_yoy_v = numeric_series_or_default(d, "op_income_growth_yoy", np.nan)
    fcf_growth_yoy_v = numeric_series_or_default(d, "fcf_growth_yoy", np.nan)

    # Cheapness: high earnings yield (low PE), low EV/EBITDA, low forward PE
    cheapness = row_mean(
        [
            cross_sectional_robust_z(d, "ep_ttm"),
            -cross_sectional_robust_z(d, "forward_pe_final"),
            -cross_sectional_robust_z(d, "ev_to_ebitda_final"),
            cross_sectional_robust_z(d, "fcfy_ttm"),
        ],
        d.index,
    ).fillna(0.0)

    # Earnings catching up to price: positive growth on multiple lines
    earnings_catchup = row_mean(
        [
            cross_sectional_robust_z(d, "eps_growth_yoy"),
            cross_sectional_robust_z(d, "op_income_growth_yoy"),
            cross_sectional_robust_z(d, "fcf_growth_yoy"),
            cross_sectional_robust_z(d, "rev_growth_accel_4q"),
        ],
        d.index,
    ).fillna(0.0)

    # Earnings-up-while-price-still-down (the heart of "PE shrinking"):
    # any positive growth combined with currently being below 52w high.
    fundamentals_growing = (
        ((eps_growth_yoy_v > 0.0) | (op_inc_growth_yoy_v > 0.0) | (fcf_growth_yoy_v > 0.0)).astype(float)
    )
    price_beaten_down = (near_high < -0.15).astype(float)
    pe_compression_setup = fundamentals_growing * price_beaten_down

    # Reversal: oversold previously (deep dd) but now the most recent
    # 1m / 3m momentum has flipped positive, ideally with the price
    # reclaiming MA50.
    oversold_recovery = (
        (dd_1y_v > 0.20).astype(float)
        * ((mom_1m_v > 0.0).astype(float) + (mom_3m_v > 0.0).astype(float))
    ).clip(upper=2.0)
    stage_one_to_two_transition = (
        (price_above_ma200_v > 0.5).astype(float)
        * (price_above_ma50_v > 0.5).astype(float)
        * (ma50_above_ma200_v > 0.5).astype(float)
        * (near_high < -0.10).astype(float)  # not yet at the high → early stage 2
    )

    # Quality / safety filters — avoid value traps with crumbling fundamentals.
    not_deep_negative_margin = (
        numeric_series_or_default(d, "op_margin_ttm", 0.0) > -0.05
    ).astype(float)
    not_high_leverage = (
        numeric_series_or_default(d, "debt_to_equity", 0.0).clip(lower=0.0) < 3.0
    ).astype(float)
    quality_floor = (not_deep_negative_margin * not_high_leverage).clip(0.0, 1.0)

    d["value_inflection_score"] = (
        (
            0.20 * cheapness
            + 0.18 * earnings_catchup
            + 0.12 * robust_z(pe_compression_setup).fillna(0.0)
            + 0.10 * robust_z(oversold_recovery).fillna(0.0)
            + 0.10 * robust_z(stage_one_to_two_transition).fillna(0.0)
            + 0.08 * cross_sectional_robust_z(d, "ocf_ni_quality_4q")
            + 0.06 * cross_sectional_robust_z(d, "rev_growth_accel_4q")
            + 0.06 * cross_sectional_robust_z(d, "margin_trend_4q")
            + 0.05 * cross_sectional_robust_z(d, "revision_score")
            + 0.05 * cross_sectional_robust_z(d, "actual_results_score")
            - 0.06 * deep_negative_margin_penalty
            - 0.04 * leverage_penalty
        )
        * (0.30 + 0.70 * quality_floor)
    ).fillna(0.0)

    # =====================================================================
    # Phase 1.4: Uptrend continuation score + uptrend breakdown penalty
    # =====================================================================
    # User mandate: keep names that are at the 52w high with MAs aligned and
    # earnings still beating; aggressively penalise those names the moment a
    # leg of the thesis cracks (price loses MA50/MA200, earnings disappoint,
    # revisions roll over).  This is the defensive-overlay for our existing
    # winners.
    above_ma20_v = numeric_series_or_default(d, "price_above_ma20", 0.0).clip(0.0, 1.0)
    above_ma150_v = numeric_series_or_default(d, "price_above_ma150", 0.0).clip(0.0, 1.0)
    ma150_above_ma200_v = numeric_series_or_default(d, "ma150_above_ma200", 0.0).clip(0.0, 1.0)
    ma20_above_ma50_v = numeric_series_or_default(d, "ma20_above_ma50", 0.0).clip(0.0, 1.0)
    ma50_above_ma150_v = numeric_series_or_default(d, "ma50_above_ma150", 0.0).clip(0.0, 1.0)

    actual_results_v = numeric_series_or_default(d, "actual_results_score", 0.0)
    revision_score_v = numeric_series_or_default(d, "revision_score", 0.0)
    earn_gap_v = numeric_series_or_default(d, "earn_gap_1d", 0.0)
    rs_bench_3m_v = numeric_series_or_default(d, "rs_benchmark_3m", 0.0)
    rs_bench_6m_v = numeric_series_or_default(d, "rs_benchmark_6m", 0.0)
    death_cross_v = numeric_series_or_default(d, "death_cross_recent_20d", 0.0).clip(0.0, 1.0)

    full_trend_alignment = (
        above_ma20_v
        * ma20_above_ma50_v
        * price_above_ma50_v
        * ma50_above_ma150_v
        * above_ma150_v
        * ma150_above_ma200_v
    ).clip(0.0, 1.0)

    near_high_strong = ((near_high >= -0.10).astype(float)).clip(0.0, 1.0)
    momentum_intact = (
        (mom_3m_v > 0.0).astype(float)
        + (mom_6m_v > 0.0).astype(float)
        + (rs_bench_3m_v > 0.0).astype(float)
        + (rs_bench_6m_v > 0.0).astype(float)
    ) / 4.0
    earnings_intact = (
        (actual_results_v > 0.0).astype(float)
        + (revision_score_v > 0.0).astype(float)
        + (earn_gap_v > -0.02).astype(float)
    ) / 3.0
    fundamentals_compounding = (
        ((sales_yoy_v > 0.05).astype(float))
        * ((eps_growth_yoy_v > 0.0).fillna(False).astype(float))
    )

    d["uptrend_continuation_score"] = (
        0.22 * robust_z(full_trend_alignment).fillna(0.0)
        + 0.16 * robust_z(near_high_strong).fillna(0.0)
        + 0.14 * robust_z(momentum_intact).fillna(0.0)
        + 0.12 * robust_z(earnings_intact).fillna(0.0)
        + 0.10 * robust_z(fundamentals_compounding).fillna(0.0)
        + 0.08 * cross_sectional_robust_z(d, "rs_benchmark_6m")
        + 0.06 * cross_sectional_robust_z(d, "minervini_momentum_alive_score")
        + 0.06 * numeric_series_or_default(d, "trend_template_full", 0.0)
        + 0.04 * cross_sectional_robust_z(d, "revision_score")
    ).fillna(0.0)

    # Uptrend breakdown penalty — fires when a previously-strong name cracks.
    # Components: (a) was strong/near high (uses near_high relaxed) but now
    # below MA50 or below MA200; (b) negative earnings event (gap-down or
    # revision rolling over); (c) momentum has flipped negative.
    was_strong = (near_high >= -0.20).astype(float)  # within 20% of 52w high
    lost_ma50 = (price_above_ma50_v <= 0.0).astype(float)
    lost_ma200 = (price_above_ma200_v <= 0.0).astype(float)
    earnings_disappointment = (
        ((earn_gap_v < -0.05).astype(float))
        + ((actual_results_v < -0.5).astype(float))
        + ((revision_score_v < -0.5).astype(float))
    ).clip(upper=2.0) / 2.0
    momentum_rollover = (
        ((mom_3m_v < 0.0).astype(float))
        + ((rs_bench_3m_v < 0.0).astype(float))
        + ((mom_1m_v < -0.05).astype(float))
    ).clip(upper=2.0) / 2.0

    breakdown_components = row_mean(
        [
            was_strong * lost_ma50,
            was_strong * lost_ma200,
            earnings_disappointment,
            momentum_rollover,
            0.50 * death_cross_v,
        ],
        d.index,
    ).fillna(0.0)
    d["uptrend_breakdown_penalty"] = breakdown_components.clip(lower=0.0, upper=1.5)

    # ---------------------------------------------------------------------
    # Phase 1 A/B toggle.  When PHASE_PHASE1_ALPHA_ENABLED=0 we keep the
    # column schema intact but zero the 5 new alpha scores so we can
    # measure Phase 1's marginal contribution by running the same cfg twice.
    # Intermediate locals above (e.g. `quality_floor`, `revision_alpha`) are
    # preserved because they're re-used elsewhere in this function.
    # ---------------------------------------------------------------------
    if not phase_is_enabled("phase1_alpha", default=True):
        for _p1_col in (
            "fundamental_turnaround_acceleration_score",
            "cashflow_inflection_under_loss_score",
            "value_inflection_score",
            "uptrend_continuation_score",
            "uptrend_breakdown_penalty",
        ):
            if _p1_col in d.columns:
                d[_p1_col] = 0.0

    anticipatory_market_confirmation = row_mean(
        [
            (numeric_series_or_default(d, "event_reaction_score", 0.0) > 0.0).astype(float),
            (benchmark_alpha > 0.0).astype(float),
            (numeric_series_or_default(d, "dynamic_leader_score", 0.0) > 0.0).astype(float),
            (numeric_series_or_default(d, "revision_score", 0.0) > 0.0).astype(float),
        ],
        d.index,
    ).fillna(0.0)
    d["anticipatory_growth_confirmation"] = np.maximum(
        numeric_series_or_default(d, "fundamental_reliability_score", 0.0).clip(lower=0.0, upper=1.0),
        0.75 * anticipatory_market_confirmation,
    )
    # Growth onset composite for ten-bagger detection
    log_mktcap = pd.to_numeric(d.get("log_mktcap", d.get("mktcap", pd.Series(np.nan, index=d.index))), errors="coerce")
    if "log_mktcap" not in d.columns and "mktcap" in d.columns:
        log_mktcap = np.log(pd.to_numeric(d["mktcap"], errors="coerce").clip(lower=1e6))
    small_base_high_growth = (
        np.clip(1.0 - (log_mktcap - 9.0) / 3.0, 0.0, 1.0)
        * np.maximum(0.0, numeric_series_or_default(d, "sales_growth_yoy", 0.0))
    ).fillna(0.0)
    # EPS/FCF acceleration — captures profit inflection better than revenue alone
    eps_accel = cross_sectional_robust_z(d, "eps_growth_yoy").fillna(0.0)
    fcf_accel = cross_sectional_robust_z(d, "fcf_growth_yoy").fillna(0.0)
    earnings_momentum = row_mean([eps_accel, fcf_accel], d.index).fillna(0.0)
    d["growth_onset_composite"] = (
        0.18 * cross_sectional_robust_z(d, "revenue_accel_2nd_deriv")
        + 0.18 * numeric_series_or_default(d, "growth_inflection_signal", 0.0)
        + 0.15 * numeric_series_or_default(d, "margin_expansion_at_growth", 0.0)
        + 0.12 * robust_z(small_base_high_growth).fillna(0.0)
        + 0.12 * cross_sectional_robust_z(d, "rs_market_acceleration")
        + 0.15 * earnings_momentum
        + 0.10 * cross_sectional_robust_z(d, "breakout_volume_z")
    ).fillna(0.0)

    # Multi-dimensional growth composite: revenue + earnings + cashflow
    multi_growth_z = row_mean(
        [
            cross_sectional_robust_z(d, "sales_cagr_3y"),
            cross_sectional_robust_z(d, "eps_cagr_3y"),
            cross_sectional_robust_z(d, "fcf_cagr_3y"),
            cross_sectional_robust_z(d, "op_income_cagr_3y"),
        ],
        d.index,
    ).fillna(0.0)
    multi_growth_5y_z = row_mean(
        [
            cross_sectional_robust_z(d, "sales_cagr_5y"),
            cross_sectional_robust_z(d, "eps_cagr_5y"),
            cross_sectional_robust_z(d, "fcf_cagr_5y"),
            cross_sectional_robust_z(d, "op_income_cagr_5y"),
        ],
        d.index,
    ).fillna(0.0)
    # Supply-demand proxy: volume confirmation + institutional flow
    supply_demand_signal = row_mean(
        [
            cross_sectional_robust_z(d, "breakout_volume_z"),
            cross_sectional_robust_z(d, "obv_trend"),
            numeric_series_or_default(d, "institutional_flow_signal_score", 0.0),
        ],
        d.index,
    ).fillna(0.0)
    # Macro-aligned growth boost: stronger when macro is expansionary
    macro_growth_boost = (
        0.50 * growth_reentry
        + 0.30 * numeric_series_or_default(d, "growth_liquidity_reentry_score", 0.0)
        + 0.20 * numeric_series_or_default(d, "liquidity_impulse_score", 0.0)
    )
    anticipatory_raw = (
        0.11 * cross_sectional_robust_z(d, "rev_growth_accel_4q")
        + 0.09 * cross_sectional_robust_z(d, "sales_growth_yoy")
        + 0.09 * multi_growth_z
        + 0.05 * multi_growth_5y_z
        + 0.09 * benchmark_alpha
        + 0.11 * cross_sectional_robust_z(d, "growth_onset_composite")
        + 0.07 * cross_sectional_robust_z(d, "technical_blueprint_score")
        + 0.06 * cross_sectional_robust_z(d, "event_reaction_score")
        + 0.06 * cross_sectional_robust_z(d, "dynamic_leader_score")
        + 0.05 * cross_sectional_robust_z(d, "leader_emergence_score")
        + 0.05 * cross_sectional_robust_z(d, "revision_blueprint_score")
        + 0.06 * numeric_series_or_default(d, "profitability_inflection_score", 0.0)
        + 0.06 * supply_demand_signal
        + 0.05 * macro_growth_boost * row_mean(
            [
                cross_sectional_robust_z(d, "rs_benchmark_3m"),
                cross_sectional_robust_z(d, "rs_benchmark_6m"),
                cross_sectional_robust_z(d, "mom_3m"),
            ],
            d.index,
        ).fillna(0.0)
        - 0.08 * numeric_series_or_default(d, "overheat_penalty", 0.0)
        - 0.05 * leverage_penalty
    ).fillna(0.0)
    d["anticipatory_growth_score"] = (
        anticipatory_raw
        * (0.60 + 0.40 * numeric_series_or_default(d, "anticipatory_growth_confirmation", 0.0))
    ).fillna(0.0)

    low_vol_quality = row_mean(
        [
            -cross_sectional_robust_z(d, "vol_252d"),
            -cross_sectional_robust_z(d, "dd_1y"),
            cross_sectional_robust_z(d, "fundamental_reliability_score"),
        ],
        d.index,
    ).fillna(0.0)
    structural_value_bias = row_mean(
        [
            cross_sectional_robust_z(d, "valuation_blueprint_score"),
            0.75 * cross_sectional_robust_z(d, "garp_score"),
            cross_sectional_robust_z(d, "structural_value_exposure"),
        ],
        d.index,
    ).fillna(0.0)
    d["archetype_emerging_growth_score"] = (
        0.22 * cross_sectional_robust_z(d, "anticipatory_growth_score")
        + 0.16 * cross_sectional_robust_z(d, "profitability_inflection_score")
        + 0.16 * cross_sectional_robust_z(d, "technical_blueprint_score")
        + 0.10 * cross_sectional_robust_z(d, "revision_blueprint_score")
        + 0.08 * cross_sectional_robust_z(d, "dynamic_leader_score")
        + 0.07 * benchmark_alpha
        + 0.06 * cross_sectional_robust_z(d, "leader_emergence_score")
        + 0.06 * earnings_momentum
        + 0.05 * supply_demand_signal
        + 0.04 * cross_sectional_robust_z(d, "relative_strength_composite")
        - 0.08 * numeric_series_or_default(d, "overheat_penalty", 0.0)
        - 0.05 * leverage_penalty
    ).fillna(0.0)
    d["archetype_compounder_score"] = (
        0.20 * cross_sectional_robust_z(d, "moat_quality_blueprint_score")
        + 0.14 * cross_sectional_robust_z(d, "quality_trend_score")
        + 0.12 * cross_sectional_robust_z(d, "growth_blueprint_score")
        + 0.10 * multi_growth_5y_z
        + 0.08 * cross_sectional_robust_z(d, "op_margin_ttm")
        + 0.08 * cross_sectional_robust_z(d, "margin_stability_8q")
        + 0.08 * benchmark_alpha
        + 0.06 * cross_sectional_robust_z(d, "fundamental_reliability_score")
        + 0.06 * low_vol_quality
        + 0.04 * cross_sectional_robust_z(d, "fcf_cagr_5y")
        + 0.04 * cross_sectional_robust_z(d, "eps_cagr_5y")
        - 0.06 * leverage_penalty
    ).fillna(0.0)
    d["archetype_cyclical_recovery_score"] = (
        0.20 * cross_sectional_robust_z(d, "valuation_blueprint_score")
        + 0.16 * cross_sectional_robust_z(d, "profitability_inflection_score")
        + 0.12 * cross_sectional_robust_z(d, "margin_trend_4q")
        + 0.10 * cross_sectional_robust_z(d, "sales_growth_yoy")
        + 0.10 * cross_sectional_robust_z(d, "event_reaction_score")
        + 0.08 * cross_sectional_robust_z(d, "actual_results_score")
        + 0.08 * benchmark_alpha
        + 0.08 * cross_sectional_robust_z(d, "energy_hedge_exposure")
        + 0.08 * structural_value_bias
        - 0.08 * numeric_series_or_default(d, "overheat_penalty", 0.0)
    ).fillna(0.0)
    balance_resilience = row_mean(
        [
            -cross_sectional_robust_z(d, "vol_252d"),
            -cross_sectional_robust_z(d, "dd_1y"),
            -cross_sectional_robust_z(d, "debt_to_equity"),
            cross_sectional_robust_z(d, "fundamental_reliability_score"),
        ],
        d.index,
    ).fillna(0.0)
    dividend_support = cross_sectional_robust_z(d, "dividend_policy_score").clip(lower=0.0).fillna(0.0)
    valuation_support = pd.to_numeric(d["valuation_blueprint_score"], errors="coerce").clip(lower=0.0).fillna(0.0)
    moat_support = pd.to_numeric(d["moat_quality_blueprint_score"], errors="coerce").clip(lower=0.0).fillna(0.0)
    # Phase 15-A1 gate: raw macro_hedge_score has IR_3m = -0.398 yet is used
    # with positive weights downstream (archetype_defensive_value_score 0.22,
    # strategy_blueprint_score macro_weight, macro_pillar_score row_mean).
    # When the phase toggle is active we zero the column at source so every
    # downstream positive-weight usage automatically gets 0 contribution.
    _phase15_a1_cfg_feat = bool(getattr(cfg, "phase15_a1_drop_negative_features_enabled", False)) if cfg is not None else False
    _phase15_a1_active_feat = phase_is_enabled("phase15_a1_drop_negative_features", default=_phase15_a1_cfg_feat)
    _phase15_a1_mult_feat = 0.0 if _phase15_a1_active_feat else 1.0
    d["macro_hedge_score"] = (_phase15_a1_mult_feat * (
        0.25 * numeric_series_or_default(d, "ai_infra_exposure", 0.0)
        + 0.25 * numeric_series_or_default(d, "power_infra_exposure", 0.0)
        + 0.20 * numeric_series_or_default(d, "defense_exposure", 0.0)
        + 0.15 * numeric_series_or_default(d, "energy_hedge_exposure", 0.0)
        + 0.15 * balance_resilience
        + 0.10 * defensive_rotation * balance_resilience
        + 0.06 * war_oil_rate * numeric_series_or_default(d, "energy_hedge_exposure", 0.0)
        + 0.05 * systemic_crisis * numeric_series_or_default(d, "defense_exposure", 0.0)
        + 0.10 * stagflation * dividend_support
        + 0.08 * np.maximum(war_oil_rate, stagflation) * valuation_support
        + 0.06 * labor_softening * moat_support
    )).fillna(0.0)
    d["archetype_defensive_value_score"] = (
        0.22 * cross_sectional_robust_z(d, "macro_hedge_score")
        + 0.18 * cross_sectional_robust_z(d, "valuation_blueprint_score")
        + 0.16 * cross_sectional_robust_z(d, "moat_quality_blueprint_score")
        + 0.12 * cross_sectional_robust_z(d, "dividend_policy_score")
        + 0.10 * low_vol_quality
        + 0.08 * cross_sectional_robust_z(d, "defense_exposure")
        + 0.08 * cross_sectional_robust_z(d, "energy_hedge_exposure")
        + 0.08 * benchmark_alpha
        - 0.08 * cross_sectional_robust_z(d, "mom_1m").clip(lower=0.0).fillna(0.0)
    ).fillna(0.0)
    archetype_growth_mode = pd.Series(np.maximum(growth_reentry, growth_liquidity), index=d.index, dtype=float)
    archetype_defense_mode = pd.Series(
        np.maximum.reduce(
            [
                defensive_rotation.values,
                systemic_crisis.values,
                carry_unwind.values,
                war_oil_rate.values,
                stagflation.values,
            ]
        ),
        index=d.index,
        dtype=float,
    )
    archetype_balance_mode = pd.Series(
        np.clip(1.0 - np.maximum(archetype_growth_mode, archetype_defense_mode), 0.0, 1.0),
        index=d.index,
        dtype=float,
    )
    archetype_growth_weight = 0.25 + 0.75 * archetype_growth_mode
    archetype_compounder_weight = 0.45 + 0.20 * breadth_regime + 0.15 * sector_participation + 0.10 * archetype_balance_mode
    archetype_cyclical_weight = 0.20 + 0.45 * np.maximum(war_oil_rate, upstream_cost) + 0.15 * structural_value_bias.clip(lower=0.0)
    archetype_defensive_weight = 0.20 + 0.55 * archetype_defense_mode + 0.15 * labor_softening
    archetype_weight_sum = (
        archetype_growth_weight
        + archetype_compounder_weight
        + archetype_cyclical_weight
        + archetype_defensive_weight
    )
    d["archetype_alignment_score"] = (
        archetype_growth_weight * d["archetype_emerging_growth_score"]
        + archetype_compounder_weight * d["archetype_compounder_score"]
        + archetype_cyclical_weight * d["archetype_cyclical_recovery_score"]
        + archetype_defensive_weight * d["archetype_defensive_value_score"]
    ) / np.where(archetype_weight_sum == 0, 1.0, archetype_weight_sum)
    d["archetype_alignment_score"] = pd.to_numeric(d["archetype_alignment_score"], errors="coerce").fillna(0.0)
    archetype_cols = [
        "archetype_emerging_growth_score",
        "archetype_compounder_score",
        "archetype_cyclical_recovery_score",
        "archetype_defensive_value_score",
    ]
    archetype_labels = np.array(
        [
            "emerging_growth",
            "compounder",
            "cyclical_recovery",
            "defensive_value",
        ],
        dtype=object,
    )
    archetype_matrix = d[archetype_cols].apply(pd.to_numeric, errors="coerce").fillna(-np.inf).to_numpy(dtype=float)
    archetype_top_idx = np.argmax(archetype_matrix, axis=1)
    archetype_top = archetype_matrix[np.arange(len(d)), archetype_top_idx]
    archetype_second = np.partition(archetype_matrix, -2, axis=1)[:, -2]
    d["dominant_archetype_score"] = pd.Series(archetype_top, index=d.index).replace(-np.inf, np.nan).fillna(0.0)
    d["dominant_archetype_confidence"] = (
        pd.Series(archetype_top - archetype_second, index=d.index).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    )
    d["dominant_archetype_label"] = pd.Series(archetype_labels[archetype_top_idx], index=d.index, dtype=object)
    history_depth_raw = numeric_series_or_default(d, "fund_history_quarters_available", 0.0).astype(float)
    history_depth = pd.Series(
        np.clip(history_depth_raw.to_numpy(dtype=float), 0.0, 20.0) / 20.0,
        index=d.index,
        dtype=float,
    )
    long_base_quality = row_mean(
        [
            cross_sectional_robust_z(d, "technical_blueprint_score"),
            0.80 * benchmark_alpha,
            0.75 * cross_sectional_robust_z(d, "moat_quality_blueprint_score"),
            0.70 * cross_sectional_robust_z(d, "sales_cagr_5y"),
            0.55 * cross_sectional_robust_z(d, "op_income_cagr_5y"),
            0.50 * cross_sectional_robust_z(d, "net_income_cagr_5y"),
            0.70 * cross_sectional_robust_z(d, "archetype_alignment_score"),
            0.40 * cross_sectional_robust_z(d, "near_52w_high_pct"),
        ],
        d.index,
    ).fillna(0.0)
    overextended_penalty = row_mean(
        [
            numeric_series_or_default(d, "overheat_penalty", 0.0),
            cross_sectional_robust_z(d, "mom_12m").clip(lower=0.0).fillna(0.0),
        ],
        d.index,
    ).fillna(0.0)
    d["long_hold_compounder_score"] = (
        0.30 * cross_sectional_robust_z(d, "archetype_compounder_score")
        + 0.18 * cross_sectional_robust_z(d, "moat_quality_blueprint_score")
        + 0.14 * cross_sectional_robust_z(d, "quality_trend_score")
        + 0.10 * multi_growth_5y_z
        + 0.08 * cross_sectional_robust_z(d, "margin_stability_8q")
        + 0.08 * benchmark_alpha
        + 0.06 * cross_sectional_robust_z(d, "fcf_cagr_5y")
        + 0.06 * cross_sectional_robust_z(d, "eps_cagr_5y")
        - 0.06 * leverage_penalty
    ).fillna(0.0)
    # === FUTURE WINNER SCOUT: combines all signals to detect next big winner ===
    # Core philosophy: "Future > Past" — weight technical, macro, supply-demand
    # more than pure financial metrics. Financials confirm; price/flow leads.
    d["future_winner_scout_score"] = (
        (0.60 + 0.40 * np.maximum(history_depth, numeric_series_or_default(d, "fundamental_reliability_score", 0.0)))
        * (
            # --- Forward-looking: technical + macro + supply-demand (55%) ---
            0.14 * cross_sectional_robust_z(d, "anticipatory_growth_score")
            + 0.12 * cross_sectional_robust_z(d, "growth_onset_composite")
            + 0.10 * cross_sectional_robust_z(d, "technical_blueprint_score")
            + 0.07 * cross_sectional_robust_z(d, "relative_strength_composite")
            + 0.06 * supply_demand_signal
            + 0.06 * macro_growth_boost
            # --- Quality confirmation (30%) ---
            + 0.10 * cross_sectional_robust_z(d, "archetype_alignment_score")
            + 0.08 * cross_sectional_robust_z(d, "long_hold_compounder_score")
            + 0.06 * cross_sectional_robust_z(d, "revision_blueprint_score")
            + 0.06 * cross_sectional_robust_z(d, "dynamic_leader_score")
            # --- Catalysts (15%) ---
            + 0.05 * long_base_quality
            + 0.05 * cross_sectional_robust_z(d, "event_reaction_score")
            + 0.05 * earnings_momentum
            # --- Penalties ---
            - 0.10 * overextended_penalty
            - 0.05 * leverage_penalty
        )
    ).fillna(0.0)

    watchlist_flag = (
        d.get("ticker", pd.Series("", index=d.index, dtype=str))
        .astype(str)
        .str.upper()
        .isin({str(t).upper() for t in cfg.focus_watchlist_tickers})
        .astype(float)
    )
    d["watchlist_quality_penalty"] = float(cfg.watchlist_penalty_scale) * watchlist_flag * (
        0.60 * np.clip(-d["valuation_blueprint_score"], 0.0, None)
        + 0.40 * np.clip(cross_sectional_robust_z(d, "debt_to_equity"), 0.0, None)
    )
    size_saturation = cross_sectional_robust_z(d, "size_saturation_score").clip(lower=0.0).fillna(0.0)
    benchmark_hugging_penalty = (
        float(cfg.benchmark_hugging_penalty)
        * size_saturation
        * np.clip(0.10 - benchmark_alpha, 0.0, None)
        * (0.35 + 0.65 * np.maximum(defensive_rotation, systemic_crisis))
    )
    growth_weight = (
        0.22
        + 0.04 * np.clip(breadth_regime - 0.55, 0.0, None)
        - 0.03 * np.clip(leadership_narrowing - 0.60, 0.0, None)
        + float(cfg.growth_reentry_strength) * np.clip(growth_reentry - 0.45, 0.0, None)
        - 0.08 * np.maximum(defensive_rotation, systemic_crisis)
        - 0.06 * stagflation
        - 0.03 * labor_softening
    )
    moat_weight = (
        0.20
        + 0.05 * np.clip(leadership_narrowing - 0.55, 0.0, None)
        + 0.06 * defensive_rotation
        + 0.04 * labor_softening
    )
    valuation_weight = (
        0.16
        + 0.03 * np.clip(leadership_narrowing - 0.55, 0.0, None)
        + 0.04 * war_oil_rate
        + 0.05 * stagflation
        + 0.03 * upstream_cost
    )
    technical_weight = (
        0.14
        + 0.06 * np.clip(breadth_regime - 0.55, 0.0, None)
        - 0.04 * np.clip(leadership_narrowing - 0.60, 0.0, None)
        + 0.05 * growth_reentry
        + 0.03 * growth_liquidity
        - 0.05 * np.maximum(systemic_crisis, carry_unwind)
        - 0.04 * stagflation
    )
    macro_weight = (
        0.04
        + 0.03 * np.clip(leadership_narrowing - 0.55, 0.0, None)
        + float(cfg.defensive_rotation_strength) * defensive_rotation
        + 0.05 * carry_unwind
        + 0.07 * stagflation
        + 0.03 * labor_softening
    )
    anticipatory_weight = (
        0.12
        + 0.04 * np.clip(breadth_regime - 0.50, 0.0, None)
        + 0.04 * growth_reentry
        + 0.03 * growth_liquidity
        - 0.04 * np.maximum(defensive_rotation, systemic_crisis)
        - 0.04 * stagflation
    )
    d["strategy_blueprint_score"] = (
        0.24 * d["revision_blueprint_score"]
        + growth_weight * d["growth_blueprint_score"]
        + moat_weight * d["moat_quality_blueprint_score"]
        + valuation_weight * d["valuation_blueprint_score"]
        + technical_weight * d["technical_blueprint_score"]
        + anticipatory_weight * d["anticipatory_growth_score"]
        + macro_weight * d["macro_hedge_score"]
        - d["watchlist_quality_penalty"]
        - benchmark_hugging_penalty
    ).fillna(0.0)
    return d


def compute_multidimensional_pillar_scores(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    if d.empty:
        for c in PILLAR_SCORE_COLUMNS:
            d[c] = np.nan
        return d

    market_cap = numeric_series_or_default(d, "market_cap_live", np.nan)
    market_cap = market_cap.fillna(numeric_series_or_default(d, "mktcap", np.nan)).replace(0, np.nan)
    shares_out = numeric_series_or_default(d, "shares", np.nan).replace(0, np.nan)

    inst_actual_available = (
        numeric_series_or_default(d, "institutional_actual_available", 0.0).fillna(0.0) > 0
    ).astype(float)
    insider_actual_available = (
        numeric_series_or_default(d, "insider_actual_available", 0.0).fillna(0.0) > 0
    ).astype(float)

    sec13f_hold_ratio_actual = numeric_series_or_default(d, "institutional_holding_intensity_actual", np.nan)
    if sec13f_hold_ratio_actual.notna().sum() == 0:
        sec13f_hold_ratio_actual = numeric_series_or_default(d, "sec13f_shares", np.nan) / shares_out
    sec13f_value_ratio_actual = numeric_series_or_default(d, "institutional_ownership_actual", np.nan)
    if sec13f_value_ratio_actual.notna().sum() == 0:
        sec13f_value_ratio_actual = numeric_series_or_default(d, "sec13f_value", np.nan) / market_cap
    sec13f_delta_share_ratio_actual = numeric_series_or_default(d, "institutional_delta_shares_ratio_actual", np.nan)
    if sec13f_delta_share_ratio_actual.notna().sum() == 0:
        sec13f_delta_share_ratio_actual = numeric_series_or_default(d, "sec13f_delta_shares", np.nan) / shares_out
    sec13f_delta_value_ratio_actual = numeric_series_or_default(d, "institutional_delta_value_ratio_actual", np.nan)
    if sec13f_delta_value_ratio_actual.notna().sum() == 0:
        sec13f_delta_value_ratio_actual = numeric_series_or_default(d, "sec13f_delta_value", np.nan) / market_cap
    sec13f_count_actual = numeric_series_or_default(d, "sec13f_holders_count", np.nan)

    insider_net_ratio_actual = numeric_series_or_default(d, "insider_net_shares_ratio_actual", np.nan)
    if insider_net_ratio_actual.notna().sum() == 0:
        insider_net_ratio_actual = numeric_series_or_default(d, "sec_form345_net_shares", np.nan) / shares_out
    insider_buy_ratio_actual = numeric_series_or_default(d, "sec_form345_buy_ratio", np.nan)
    insider_buy_balance_actual = (2.0 * insider_buy_ratio_actual) - 1.0
    insider_txn_actual = np.log1p(
        numeric_series_or_default(d, "sec_form345_txn_count", np.nan).clip(lower=0.0)
    )

    institutional_hold_component = row_mean(
        [
            robust_z(sec13f_hold_ratio_actual).fillna(0.0),
            robust_z(sec13f_value_ratio_actual).fillna(0.0),
            robust_z(sec13f_count_actual).fillna(0.0),
        ],
        d.index,
    ).fillna(0.0)
    institutional_delta_component = row_mean(
        [
            robust_z(sec13f_delta_share_ratio_actual).fillna(0.0),
            robust_z(sec13f_delta_value_ratio_actual).fillna(0.0),
        ],
        d.index,
    ).fillna(0.0)
    institutional_flow_actual = (
        0.60 * institutional_delta_component + 0.40 * institutional_hold_component
    ).where(inst_actual_available > 0, np.nan)

    insider_flow_actual = (
        0.55 * robust_z(insider_net_ratio_actual).fillna(0.0)
        + 0.30 * robust_z(insider_buy_balance_actual).fillna(0.0)
        + 0.15 * robust_z(insider_txn_actual).fillna(0.0)
    ).where(insider_actual_available > 0, np.nan)

    institutional_flow_live = numeric_series_or_default(d, "institutional_flow_score", np.nan)
    insider_flow_live = numeric_series_or_default(d, "insider_flow_score", np.nan)

    d["institutional_flow_actual_score"] = institutional_flow_actual
    d["insider_flow_actual_score"] = insider_flow_actual
    d["institutional_flow_signal_score"] = institutional_flow_actual.where(
        inst_actual_available > 0,
        institutional_flow_live,
    ).fillna(0.0)
    d["insider_flow_signal_score"] = insider_flow_actual.where(
        insider_actual_available > 0,
        insider_flow_live,
    ).fillna(0.0)

    holding_intensity_signal = sec13f_hold_ratio_actual.where(
        sec13f_hold_ratio_actual.notna(),
        numeric_series_or_default(d, "institutional_holding_intensity", np.nan),
    )
    insider_net_signal = insider_net_ratio_actual.where(
        insider_net_ratio_actual.notna(),
        numeric_series_or_default(d, "insider_net_shares_ratio", np.nan),
    )
    actual_depth = row_mean(
        [
            numeric_series_or_default(d, "actual_report_available", 0.0).clip(lower=0.0, upper=1.0),
            inst_actual_available,
            insider_actual_available,
        ],
        d.index,
    ).fillna(0.0)

    d["ownership_flow_pillar_score"] = (
        0.80
        * row_mean(
            [
                robust_z(pd.to_numeric(d["institutional_flow_signal_score"], errors="coerce")).fillna(0.0),
                robust_z(pd.to_numeric(d["insider_flow_signal_score"], errors="coerce")).fillna(0.0),
                0.60 * robust_z(holding_intensity_signal).fillna(0.0),
                0.40 * robust_z(insider_net_signal).fillna(0.0),
            ],
            d.index,
        ).fillna(0.0)
        + 0.20 * actual_depth
    ).fillna(0.0)

    d["fundamental_pillar_score"] = row_mean(
        [
            cross_sectional_robust_z(d, "quality_trend_score"),
            cross_sectional_robust_z(d, "garp_score"),
            cross_sectional_robust_z(d, "capital_efficiency_score"),
            cross_sectional_robust_z(d, "sector_adjusted_quality_score"),
            0.75 * cross_sectional_robust_z(d, "actual_results_score"),
        ],
        d.index,
    ).fillna(0.0)
    d["technical_pillar_score"] = row_mean(
        [
            cross_sectional_robust_z(d, "technical_blueprint_score"),
            cross_sectional_robust_z(d, "dynamic_leader_score"),
            cross_sectional_robust_z(d, "sector_leader_score"),
            cross_sectional_robust_z(d, "rs_benchmark_6m"),
            cross_sectional_robust_z(d, "mom_6m"),
        ],
        d.index,
    ).fillna(0.0)
    d["event_revision_pillar_score"] = row_mean(
        [
            cross_sectional_robust_z(d, "event_reaction_score"),
            cross_sectional_robust_z(d, "revision_blueprint_score"),
            cross_sectional_robust_z(d, "actual_results_score"),
            0.60 * cross_sectional_robust_z(d, "forward_value_score"),
            0.50 * cross_sectional_robust_z(d, "earn_gap_1d"),
        ],
        d.index,
    ).fillna(0.0)
    d["macro_pillar_score"] = row_mean(
        [
            cross_sectional_robust_z(d, "macro_hedge_score"),
            cross_sectional_robust_z(d, "macro_momentum_regime_interaction"),
            cross_sectional_robust_z(d, "macro_tech_leadership_interaction"),
            cross_sectional_robust_z(d, "macro_semis_cycle_interaction"),
            cross_sectional_robust_z(d, "macro_defensive_riskoff_interaction"),
        ],
        d.index,
    ).fillna(0.0)
    d["compounder_pillar_score"] = row_mean(
        [
            cross_sectional_robust_z(d, "future_winner_scout_score"),
            cross_sectional_robust_z(d, "long_hold_compounder_score"),
            cross_sectional_robust_z(d, "archetype_alignment_score"),
            cross_sectional_robust_z(d, "moat_quality_blueprint_score"),
            0.50 * cross_sectional_robust_z(d, "anticipatory_growth_score"),
        ],
        d.index,
    ).fillna(0.0)

    d["multidimensional_breadth_score"] = row_mean(
        [
            (pd.to_numeric(d["fundamental_pillar_score"], errors="coerce") > 0.10).astype(float),
            (pd.to_numeric(d["technical_pillar_score"], errors="coerce") > 0.10).astype(float),
            (pd.to_numeric(d["event_revision_pillar_score"], errors="coerce") > 0.05).astype(float),
            (pd.to_numeric(d["ownership_flow_pillar_score"], errors="coerce") > 0.05).astype(float),
            (pd.to_numeric(d["macro_pillar_score"], errors="coerce") > 0.0).astype(float),
            (pd.to_numeric(d["compounder_pillar_score"], errors="coerce") > 0.10).astype(float),
        ],
        d.index,
    ).fillna(0.0)
    d["multidimensional_confirmation_score"] = row_mean(
        [
            pd.to_numeric(d["multidimensional_breadth_score"], errors="coerce").clip(lower=0.0, upper=1.0),
            (pd.to_numeric(d["fundamental_pillar_score"], errors="coerce") > 0.25).astype(float),
            (pd.to_numeric(d["technical_pillar_score"], errors="coerce") > 0.20).astype(float),
            (pd.to_numeric(d["event_revision_pillar_score"], errors="coerce") > 0.10).astype(float),
            (pd.to_numeric(d["ownership_flow_pillar_score"], errors="coerce") > 0.10).astype(float),
            (pd.to_numeric(d["compounder_pillar_score"], errors="coerce") > 0.15).astype(float),
            0.75 * actual_depth,
        ],
        d.index,
    ).fillna(0.0)
    return d


def compute_minervini_momentum_overlay(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    if d.empty:
        return d

    price_above_ma50 = numeric_series_or_default(d, "price_above_ma50", 0.0).clip(lower=0.0, upper=1.0)
    price_above_ma150 = numeric_series_or_default(d, "price_above_ma150", 0.0).clip(lower=0.0, upper=1.0)
    price_above_ma200 = numeric_series_or_default(d, "price_above_ma200", 0.0).clip(lower=0.0, upper=1.0)
    ma50_above_ma150 = numeric_series_or_default(d, "ma50_above_ma150", 0.0).clip(lower=0.0, upper=1.0)
    ma150_above_ma200 = numeric_series_or_default(d, "ma150_above_ma200", 0.0).clip(lower=0.0, upper=1.0)
    ma200_slope_positive = (numeric_series_or_default(d, "ma200_slope_1m", 0.0) > 0.0).astype(float)
    ma_order_score = row_mean(
        [
            price_above_ma50,
            price_above_ma150,
            price_above_ma200,
            ma50_above_ma150,
            ma150_above_ma200,
            ma200_slope_positive,
        ],
        d.index,
    ).fillna(0.0)
    near_high = numeric_series_or_default(d, "near_52w_high_pct", -1.0)
    near_high_score = ((near_high + 0.30) / 0.30).clip(lower=0.0, upper=1.0).fillna(0.0)
    trend_template_score = row_mean(
        [
            numeric_series_or_default(d, "trend_template_full", 0.0).clip(lower=0.0, upper=1.0),
            numeric_series_or_default(d, "trend_template_relaxed", 0.0).clip(lower=0.0, upper=1.0),
            ma_order_score,
            near_high_score,
        ],
        d.index,
    ).fillna(0.0)

    absolute_momentum = row_mean(
        [
            cross_sectional_robust_z(d, "mom_3m"),
            cross_sectional_robust_z(d, "mom_6m"),
            cross_sectional_robust_z(d, "mom_12m"),
        ],
        d.index,
    ).fillna(0.0)
    relative_momentum = row_mean(
        [
            cross_sectional_robust_z(d, "rs_benchmark_3m"),
            cross_sectional_robust_z(d, "rs_benchmark_6m"),
            cross_sectional_robust_z(d, "rs_benchmark_12m"),
            0.80 * cross_sectional_robust_z(d, "relative_strength_composite"),
        ],
        d.index,
    ).fillna(0.0)
    volume_breakout = row_mean(
        [
            0.80 * cross_sectional_robust_z(d, "breakout_volume_z"),
            numeric_series_or_default(d, "breakout_fresh_20d", 0.0).clip(lower=0.0, upper=1.0),
            numeric_series_or_default(d, "post_breakout_hold_score", 0.0).clip(lower=0.0, upper=1.0),
            0.50 * cross_sectional_robust_z(d, "obv_trend"),
        ],
        d.index,
    ).fillna(0.0)
    volatility_setup = row_mean(
        [
            cross_sectional_robust_z(d, "volume_dryup_20d"),
            cross_sectional_robust_z(d, "volatility_contraction_score"),
        ],
        d.index,
    ).fillna(0.0)
    positive_rs_consistency = row_mean(
        [
            (numeric_series_or_default(d, "rs_benchmark_3m", 0.0) > 0.0).astype(float),
            (numeric_series_or_default(d, "rs_benchmark_6m", 0.0) > 0.0).astype(float),
            (numeric_series_or_default(d, "rs_benchmark_12m", 0.0) > 0.0).astype(float),
            (numeric_series_or_default(d, "mom_3m", 0.0) > 0.0).astype(float),
            (numeric_series_or_default(d, "mom_6m", 0.0) > 0.0).astype(float),
        ],
        d.index,
    ).fillna(0.0)
    rsi14 = numeric_series_or_default(d, "rsi14", np.nan)
    rsi_not_extended = (1.0 - ((rsi14 - 82.0) / 10.0).clip(lower=0.0, upper=1.0)).fillna(0.65)
    bb_pb = numeric_series_or_default(d, "bb_pb", np.nan)
    bollinger_not_extended = (1.0 - ((bb_pb - 1.05) / 0.25).clip(lower=0.0, upper=1.0)).fillna(0.65)
    breakout_follow_through = row_mean(
        [
            numeric_series_or_default(d, "breakout_fresh_20d", 0.0).clip(lower=0.0, upper=1.0),
            numeric_series_or_default(d, "post_breakout_hold_score", 0.0).clip(lower=0.0, upper=1.0),
            (numeric_series_or_default(d, "breakout_volume_z", 0.0) > 0.0).astype(float),
            (numeric_series_or_default(d, "obv_trend", 0.0) > 0.0).astype(float),
        ],
        d.index,
    ).fillna(0.0)
    broken_trend = row_mean(
        [
            (price_above_ma50 <= 0.0).astype(float),
            (price_above_ma150 <= 0.0).astype(float),
            (price_above_ma200 <= 0.0).astype(float),
            (ma150_above_ma200 <= 0.0).astype(float),
            numeric_series_or_default(d, "death_cross_recent_20d", 0.0).clip(lower=0.0, upper=1.0),
            (numeric_series_or_default(d, "mom_3m", 0.0) < 0.0).astype(float),
            (numeric_series_or_default(d, "mom_6m", 0.0) < 0.0).astype(float),
            (numeric_series_or_default(d, "rs_benchmark_3m", 0.0) < 0.0).astype(float),
        ],
        d.index,
    ).fillna(0.0)
    atr_high_penalty = cross_sectional_robust_z(d, "atr14_pct").clip(lower=0.0).fillna(0.0)
    setup_quality_raw = row_mean(
        [
            1.15 * trend_template_score,
            1.00 * positive_rs_consistency,
            0.85 * near_high_score,
            0.70 * breakout_follow_through,
            0.55 * robust_z(volatility_setup).fillna(0.0).clip(lower=-1.0, upper=2.0),
            0.50 * rsi_not_extended,
            0.45 * bollinger_not_extended,
        ],
        d.index,
    ).fillna(0.0)
    setup_quality_score = (setup_quality_raw - 0.55 * broken_trend - 0.18 * atr_high_penalty).clip(
        lower=-2.0,
        upper=2.5,
    )
    minervini_raw = (
        0.33 * robust_z(trend_template_score).fillna(0.0)
        + 0.23 * relative_momentum
        + 0.15 * absolute_momentum
        + 0.14 * robust_z(setup_quality_score).fillna(0.0)
        + 0.09 * volume_breakout
        + 0.06 * volatility_setup
    )
    d["minervini_trend_template_score"] = trend_template_score.clip(lower=0.0, upper=1.0)
    d["momentum_alive_relative_score"] = relative_momentum
    d["momentum_alive_absolute_score"] = absolute_momentum
    d["momentum_alive_volume_score"] = volume_breakout
    d["broken_momentum_penalty"] = broken_trend.clip(lower=0.0, upper=1.0)
    d["breakout_setup_quality_score"] = setup_quality_score
    d["minervini_momentum_alive_score"] = (minervini_raw - 0.65 * d["broken_momentum_penalty"]).clip(
        lower=-4.0,
        upper=4.0,
    )
    d["minervini_trend_pass"] = (
        (d["minervini_trend_template_score"] >= 0.75)
        & (near_high >= -0.30)
        & (numeric_series_or_default(d, "rs_benchmark_6m", 0.0) > 0.0)
    ).astype(float)
    return d


# =====================================================================
# Phase 14 (2026-04-25): Hybrid alpha — production wire of validated
# Aggressive scanner signals into 정석 ML feature set.
# =====================================================================
# Sources (commit 2e5fc19, 1d04f78, ADR_PLAYBOOK):
#   F  rs_acceleration_score         T4 +10% alpha (90d, 24mo backtest)
#   G  h1_oversold_value_score       Opus H1 +8.67% alpha 12m (n=1149, p<0.0001)
#   G  h6_dynamic_leader_score       Opus H6 +7.38% alpha 12m (n=704, p<0.0001)
#   G  stage2_overext_penalty        T1 -2.5% alpha protection (chase 52w high)
#   H  theme_phase_multiplier_*      themes.yaml phase classifier (early/.../dead)
#
# All five are point-in-time safe (use mom_*m past returns + current PE/margin).
# No leakage (regression.pattern_miner_excludes_forward_returns guards future).

PHASE14_HYBRID_ALPHA_COLUMNS = [
    "rs_acceleration_score",
    "h1_oversold_value_score",
    "h6_dynamic_leader_score",
    "stage2_overext_penalty",
    "theme_phase_multiplier_primary",
    "theme_phase_multiplier_max",
]


# Short-term RS separation + chase-extension penalty (2026-05-13).
# rs_short_score / rs_long_score split the prior single rs_acceleration_score
# into independent components so short-term breakdown (PLTR-style: 1m/3m RS
# negative while 6m/12m still positive) gets explicit weight rather than
# averaging out. short_extension_risk_penalty fires on overextended single-month
# moves that lack structural-growth confirmation (theme_horizon + multi-year mom).
SHORT_RS_TRAP_COLUMNS = [
    "rs_short_score",
    "rs_long_score",
    "rs_short_breakdown_penalty",
    "short_extension_risk_penalty",
]


def compute_rs_short_long_scores(df: pd.DataFrame) -> pd.DataFrame:
    """Split RS into short (1m + 3m) and long (6m + 12m) components.

    Why: PLTR shows rs_industry_6m=-0.27 and rs_industry_3m=-0.14 but the prior
    single rs_acceleration_score (3m_z - 12m_z) compressed both into -0.07 — too
    weak to drive the total score down. Splitting them lets the final composite
    apply distinct weights, and a `rs_short_breakdown_penalty` fires when BOTH
    short-side components are negative (clean short-term weakness signal).

    Columns added:
      rs_short_score              = z(mean of rs_industry_1m, rs_industry_3m,
                                       rs_industry_group_1m, rs_industry_group_3m,
                                       rs_benchmark_1m, rs_benchmark_3m)
      rs_long_score               = z(mean of rs_industry_6m, rs_industry_12m,
                                       rs_industry_group_6m, rs_industry_group_12m,
                                       rs_benchmark_6m, rs_benchmark_12m)
      rs_short_breakdown_penalty  = clip(-min(rs_short_score, 0), 0, 1)
                                    fires only when short_score < 0 (1m/3m weak)
    """
    d = df.copy() if df is not None else pd.DataFrame()
    if d.empty:
        d["rs_short_score"] = pd.Series(dtype=float)
        d["rs_long_score"] = pd.Series(dtype=float)
        d["rs_short_breakdown_penalty"] = pd.Series(dtype=float)
        return d
    short_cols = [
        "rs_industry_1m", "rs_industry_3m",
        "rs_industry_group_1m", "rs_industry_group_3m",
        "rs_benchmark_1m", "rs_benchmark_3m",
    ]
    long_cols = [
        "rs_industry_6m", "rs_industry_12m",
        "rs_industry_group_6m", "rs_industry_group_12m",
        "rs_benchmark_6m", "rs_benchmark_12m",
    ]
    short_components = [cross_sectional_robust_z(d, c) for c in short_cols]
    long_components = [cross_sectional_robust_z(d, c) for c in long_cols]
    short_mean = pd.concat(short_components, axis=1).mean(axis=1)
    long_mean = pd.concat(long_components, axis=1).mean(axis=1)
    d["rs_short_score"] = short_mean.clip(lower=-3.0, upper=3.0).fillna(0.0)
    d["rs_long_score"] = long_mean.clip(lower=-3.0, upper=3.0).fillna(0.0)
    d["rs_short_breakdown_penalty"] = (
        (-d["rs_short_score"]).clip(lower=0.0, upper=1.5) / 1.5
    ).clip(lower=0.0, upper=1.0).fillna(0.0)
    return d


def compute_rs_acceleration_score(df: pd.DataFrame) -> pd.DataFrame:
    """T4 RS Acceleration — recent (3m) RS minus longer (12m) RS.

    Validated +10% alpha (90d horizon, 24mo backtest per audit 1d04f78).

    Positive score: stock's outperformance is accelerating (3m RS > 12m RS).
    Negative score: outperformance is decaying — early sign of leadership rotation.

    Returns df with 'rs_acceleration_score' column added (z-scored, clipped [-3, 3]).
    """
    d = df.copy() if df is not None else pd.DataFrame()
    if d.empty:
        d["rs_acceleration_score"] = pd.Series(dtype=float)
        return d
    rs_3m_z = cross_sectional_robust_z(d, "rs_benchmark_3m")
    rs_12m_z = cross_sectional_robust_z(d, "rs_benchmark_12m")
    d["rs_acceleration_score"] = (rs_3m_z - rs_12m_z).clip(lower=-3.0, upper=3.0).fillna(0.0)
    return d


def compute_h1_oversold_value_score(df: pd.DataFrame) -> pd.DataFrame:
    """Opus H1 oversold-value-beat — bear-regime mean reversion signal.

    Validated +8.67% alpha 12m, p<0.0001, n=1149. Strongest in bear/recovery
    regimes (2021_bull +27%, 2020_covid +12%, 2022_bear +10%).

    Original Aggressive scanner condition (commit 2e5fc19):
        RSI(14) < 45 AND EP_TTM > 0.05 AND mom_12m < -0.10

    Production translation:
        rsi14 (already in feature_store) < 45
        ep_ttm = 1/forward_pe_final or ep_ttm column directly
        mom_12m < -0.10

    Returns continuous score [0.0, 1.0] — 1.0 = full fire (all conditions met),
    fractional = partial. Use as ML feature OR multiplier.
    """
    d = df.copy() if df is not None else pd.DataFrame()
    if d.empty:
        d["h1_oversold_value_score"] = pd.Series(dtype=float)
        return d
    rsi14 = numeric_series_or_default(d, "rsi14", 50.0)
    ep_ttm = numeric_series_or_default(d, "ep_ttm", 0.0)
    # Fall back to 1/forward_pe_final if ep_ttm absent
    fwd_pe = numeric_series_or_default(d, "forward_pe_final", np.nan)
    ep_from_pe = (1.0 / fwd_pe).where(fwd_pe > 0, 0.0).fillna(0.0)
    ep_effective = ep_ttm.where(ep_ttm > 0, ep_from_pe)
    mom_12m = numeric_series_or_default(d, "mom_12m", 0.0)

    # Continuous interpretation: each condition contributes to score
    rsi_part = ((45.0 - rsi14) / 15.0).clip(lower=0.0, upper=1.0)         # 1.0 at RSI=30, 0 at RSI>=45
    ep_part = ((ep_effective - 0.05) / 0.05).clip(lower=0.0, upper=1.0)   # 1.0 at EP>=10%, 0 at EP<=5%
    mom_part = ((-0.10 - mom_12m) / 0.20).clip(lower=0.0, upper=1.0)      # 1.0 at mom<=-30%, 0 at mom>=-10%
    d["h1_oversold_value_score"] = (rsi_part * ep_part * mom_part).clip(lower=0.0, upper=1.0).fillna(0.0)
    return d


def compute_h6_dynamic_leader_score(df: pd.DataFrame) -> pd.DataFrame:
    """Opus H6 dynamic-leader-compounder — pro-cyclical compounder signal.

    Validated +7.38% alpha 12m, p<0.0001, n=704. Strongest in growth/recovery
    regimes (2023_recovery +9%, 2024_ai_bull +7.5%, 2020_covid +5%).

    Original Aggressive scanner condition:
        mom_3m > 0.05 AND op_margin_ttm > 0.15

    Returns continuous score [0.0, 1.0].
    """
    d = df.copy() if df is not None else pd.DataFrame()
    if d.empty:
        d["h6_dynamic_leader_score"] = pd.Series(dtype=float)
        return d
    mom_3m = numeric_series_or_default(d, "mom_3m", 0.0)
    op_margin = numeric_series_or_default(d, "op_margin_ttm", 0.0)

    mom_part = ((mom_3m - 0.05) / 0.10).clip(lower=0.0, upper=1.0)        # 1.0 at mom>=15%, 0 at mom<=5%
    margin_part = ((op_margin - 0.15) / 0.10).clip(lower=0.0, upper=1.0)  # 1.0 at margin>=25%, 0 at margin<=15%
    d["h6_dynamic_leader_score"] = (mom_part * margin_part).clip(lower=0.0, upper=1.0).fillna(0.0)
    return d


def compute_stage2_overext_penalty(df: pd.DataFrame) -> pd.DataFrame:
    """T1 Stage 2 breakout overextension penalty — chase-the-top protection.

    Backtest finding (1d04f78): T1 Stage 2 = -2.5% alpha. Compound 4-factor gate
    fires only when ALL hold:
      near_52w_high > 0.95 AND RSI(14) > 72 AND no_catalyst AND weak_fund

    Returns continuous penalty score [0.0, 1.0]. 1.0 = full penalty.
    Use as multiplicative penalty (e.g. final_score *= (1 - 0.15 * penalty))
    OR as direct ML feature (model learns weight).
    """
    d = df.copy() if df is not None else pd.DataFrame()
    if d.empty:
        d["stage2_overext_penalty"] = pd.Series(dtype=float)
        return d
    near_52w = numeric_series_or_default(d, "near_52w_high_pct", 0.0).clip(lower=0.0, upper=1.0)
    rsi14 = numeric_series_or_default(d, "rsi14", 50.0)
    op_margin = numeric_series_or_default(d, "op_margin_ttm", np.nan)
    fwd_pe = numeric_series_or_default(d, "forward_pe_final", np.nan)
    eps_growth = numeric_series_or_default(d, "earnings_growth_yoy", np.nan)

    # Each gate as continuous: 1.0 = condition fully met
    near_52w_part = ((near_52w - 0.95) / 0.05).clip(lower=0.0, upper=1.0)         # 1.0 at near_52w>=1.0
    rsi_part = ((rsi14 - 72.0) / 8.0).clip(lower=0.0, upper=1.0)                  # 1.0 at RSI>=80, 0 at RSI<=72
    weak_margin = ((0.05 - op_margin) / 0.05).clip(lower=0.0, upper=1.0).fillna(1.0)  # 1.0 if op_margin<=0 OR NaN
    expensive_pe = ((fwd_pe - 50.0) / 30.0).clip(lower=0.0, upper=1.0).fillna(0.0)    # 1.0 at PE>=80, 0 at PE<=50
    no_growth = (eps_growth.isna() | (eps_growth <= 0.0)).astype(float)
    weak_fund = pd.concat([weak_margin, expensive_pe, no_growth], axis=1).max(axis=1)
    # Conservative: penalty fires only when ALL three primary gates active
    d["stage2_overext_penalty"] = (
        near_52w_part * rsi_part * weak_fund
    ).clip(lower=0.0, upper=1.0).fillna(0.0)
    return d


def compute_short_extension_risk_penalty(df: pd.DataFrame) -> pd.DataFrame:
    """Short-horizon overextension penalty with structural-growth exemption.

    Companion to stage2_overext_penalty (52w-high / RSI / weak_fund). That gate
    catches the classic chase-the-top pattern but misses single-month parabolic
    moves on names that lack 52w-high or RSI extremes (e.g. small-cap thematic
    pumps). This gate fires on excess short-term distance from MA20 when not
    backed by structural-growth confirmation.

    Fires on ANY of:
      mom_1m > 0.20                   # > +20% in one month
      bb_pb > 0.95                    # near top of Bollinger band

    NOTE on price/MA20 trigger removal (2026-05-14): The original design
    included a third trigger `price/MA20 ratio > 1.20`, but `price_to_ma20_ratio`
    is not actually computed anywhere in the pipeline — the prior implementation
    fell back to a `1.0 + mom_1m * 0.5` proxy that effectively duplicated the
    mom_1m trigger (would only add new firings at mom_1m > 0.40, already 100%
    saturated by the mom_part). The trigger was therefore dead code disguised
    as independent confirmation. Removed to avoid misleading attribution.
    If a real ma20 ratio is later wired, add it back here explicitly.

    Exempt (multiplied by 0.0) when ALL of:
      theme_horizon_primary == 'structural_growth'
      mom_24m > 0 OR mom_36m > 0      # multi-year structural uptrend
      industry_group_strength_score > 0

    Returns continuous penalty [0.0, 1.0]. Apply as multiplicative
    (final_score *= (1 - 0.20 * penalty)) so 1.0 = -20% score.
    """
    d = df.copy() if df is not None else pd.DataFrame()
    if d.empty:
        d["short_extension_risk_penalty"] = pd.Series(dtype=float)
        return d
    mom_1m = numeric_series_or_default(d, "mom_1m", 0.0)
    bb_pb = numeric_series_or_default(d, "bb_pb", 0.5)

    mom_part = ((mom_1m - 0.20) / 0.20).clip(lower=0.0, upper=1.0)            # 1.0 at mom_1m >= 40%
    bb_part = ((bb_pb - 0.95) / 0.05).clip(lower=0.0, upper=1.0)              # 1.0 at bb_pb >= 1.0

    raw_penalty = pd.concat([mom_part, bb_part], axis=1).max(axis=1)

    theme_horizon = d.get("theme_horizon_primary", pd.Series("", index=d.index)).astype(str)
    mom_24m = numeric_series_or_default(d, "mom_24m", 0.0)
    mom_36m = numeric_series_or_default(d, "mom_36m", 0.0)
    group_strength = numeric_series_or_default(d, "industry_group_strength_score", 0.0)

    structural_exempt = (
        (theme_horizon == "structural_growth")
        & ((mom_24m > 0.0) | (mom_36m > 0.0))
        & (group_strength > 0.0)
    )
    d["short_extension_risk_penalty"] = (
        raw_penalty.where(~structural_exempt, 0.0)
    ).clip(lower=0.0, upper=1.0).fillna(0.0)
    return d


def compute_sub_industry_rs_score(df: pd.DataFrame) -> pd.DataFrame:
    """Phase 15-C P19: sub-industry-relative RS rank (best of best in industry).

    Existing P2 sub_industry sector cap prevents NVDA + LRCX from absorbing
    the IT sector cap (good — diversifies sub-industries). But it doesn't
    REWARD being top within the sub-industry. A name that's #1 in its
    sub_industry should rank higher than a name that's #5.

    This score: cross-sectional rank of `mom_12m` within sub_industry.
      - 1.0 = #1 in sub_industry by 12-month momentum
      - 0.5 = median in sub_industry
      - 0.0 = bottom in sub_industry

    Captures "leader of leaders" effect — when memory is hot, MU + WDC + SNDK
    all rise but MU as the strongest 12mo performer ranks highest.

    Falls back to mom_6m, mom_3m as ranking signal cascade when mom_12m
    is unavailable (e.g. recent IPOs).

    Falls back to industry_group, then industry, then sector if sub_industry
    not populated. Pure ranking — uses mom_*m which is always present in the
    feature_store (unlike `score` which is computed post-ML).

    Phase 15-C bug fix (2026-04-28 22:30 KST): original used `d.get("score")`
    which returned scalar NaN when "score" column didn't exist (during
    build_feature_store before ML runs), crashing with AttributeError
    'numpy.float64 object has no attribute isna'. Switched to mom_12m
    (always available) and added explicit Series guard.
    """
    d = df.copy() if df is not None else pd.DataFrame()
    if d.empty:
        d["sub_industry_rs_score"] = pd.Series(dtype=float)
        return d

    # Pick first available ranking signal — cascade through 12m -> 6m -> 3m.
    rank_signal = None
    for col in ("mom_12m", "mom_6m", "mom_3m"):
        if col in d.columns:
            cand = pd.to_numeric(d[col], errors="coerce")
            if isinstance(cand, pd.Series) and cand.notna().any():
                rank_signal = cand
                break
    if rank_signal is None:
        d["sub_industry_rs_score"] = 0.5
        return d

    # Group by best available granularity
    group_col_priority = ["sub_industry", "subindustry", "industry_group", "industry", "sector"]
    chosen = None
    for c in group_col_priority:
        if c in d.columns and d[c].notna().any():
            chosen = c
            break
    if chosen is None:
        d["sub_industry_rs_score"] = 0.5
        return d

    group_series = d[chosen].astype(str).fillna("Unknown")
    # Rank within group (pct rank, 0=lowest, 1=highest)
    rank_within = rank_signal.groupby(group_series).rank(pct=True, method="average")
    d["sub_industry_rs_score"] = rank_within.fillna(0.5).astype(float)
    return d


def compute_insider_cluster_boost_score(df: pd.DataFrame) -> pd.DataFrame:
    """Phase 15-C P20: insider buy cluster confirmation boost.

    Finnhub collector already produces:
      - fh_insider_cluster_30d_score: aggregate cluster signal
      - fh_insider_n_buyers_30d:      number of distinct buyers (>=3 = cluster)
      - fh_insider_buy_value_30d:     total $ value
      - fh_insider_n_sales_30d:       sales counter (negative signal)

    Currently `insider_flow_actual_score` exists but tends to be 0/1 binary.
    This score gives a continuous boost when MULTIPLE insiders are buying
    (cluster signal — strongest when >= 3 distinct insiders, low confidence
    when only 1 buyer).

    Returns [0, 1]:
      0.0  = no insider buys (or net selling)
      0.3  = 1 buyer (weak)
      0.6  = 2 buyers
      1.0  = 3+ buyers (cluster — high conviction)
      Capped lower if sales > buyers (selling cluster overrides).
    """
    d = df.copy() if df is not None else pd.DataFrame()
    if d.empty:
        d["insider_cluster_boost_score"] = pd.Series(dtype=float)
        return d
    n_buyers = numeric_series_or_default(d, "fh_insider_n_buyers_30d", 0.0)
    n_sales = numeric_series_or_default(d, "fh_insider_n_sales_30d", 0.0)

    # Buyer-count progression
    boost = pd.Series(0.0, index=d.index, dtype=float)
    boost = boost.where(n_buyers < 1, 0.3)
    boost = boost.where(n_buyers < 2, 0.6)
    boost = boost.where(n_buyers < 3, 1.0)

    # Sale override — if more sellers than buyers, cap at 0.3
    sale_dominant = (n_sales > n_buyers)
    boost = boost.where(~sale_dominant, boost.clip(upper=0.3))

    d["insider_cluster_boost_score"] = boost.fillna(0.0)
    return d


def compute_ml_technical_agreement_score(df: pd.DataFrame) -> pd.DataFrame:
    """Phase 15-C ML x technical agreement — demote false-positive ML picks.

    ML score (Ridge / Logistic blend) sometimes ranks high on names whose
    technicals warn (negative momentum, RS broken, weak relative strength
    vs benchmark). These are typically value-trap or fundamental-improving-
    but-price-rolling-over names. Walk-forward backtest training period
    might reward them historically (e.g. 2020 covid bottom buyers won)
    but live execution catches them mid-decline.

    This score gates ML conviction by technical confirmation:
      Agreement = 1.0 when ALL of:
        - mom_3m > 0
        - rs_benchmark_3m > 0
        - mom_1m > -0.05  (no fresh weakness)
      Agreement = 0.5 partial when 2 of 3 fire
      Agreement = 0.2 when only 1 fires
      Agreement = 0.0 when none fire

    Used in selection as a multiplier on the ML score for ranking — names
    with strong ML score but failing technical agreement get demoted out
    of the top-N. Also as a feature so ML can recursively learn its weight.

    Returns continuous score [0.0, 1.0].
    """
    d = df.copy() if df is not None else pd.DataFrame()
    if d.empty:
        d["ml_technical_agreement_score"] = pd.Series(dtype=float)
        return d
    mom_3m = numeric_series_or_default(d, "mom_3m", 0.0)
    rs_3m = numeric_series_or_default(d, "rs_benchmark_3m", 0.0)
    mom_1m = numeric_series_or_default(d, "mom_1m", 0.0)

    cond1 = (mom_3m > 0).astype(float)
    cond2 = (rs_3m > 0).astype(float)
    cond3 = (mom_1m > -0.05).astype(float)
    n_fire = cond1 + cond2 + cond3

    # Step function: 3 fire = 1.0, 2 fire = 0.5, 1 fire = 0.2, 0 fire = 0.0
    score = pd.Series(0.0, index=d.index, dtype=float)
    score = score.where(n_fire < 1, 0.2)
    score = score.where(n_fire < 2, 0.5)
    score = score.where(n_fire < 3, 1.0)
    d["ml_technical_agreement_score"] = score
    return d


def compute_entry_quality_score(df: pd.DataFrame) -> pd.DataFrame:
    """Phase 15-C entry quality — internalize scanner trade_card discipline.

    The Aggressive scanner produces a `trade_card` per candidate with pivot,
    buy_zone, stop_loss, base_tightness, extension_from_pivot, R:R ratio,
    entry_status (READY/EARLY/EXTENDED) and warnings. This data is precise
    but lives in scanner JSON and is consumed only by `daily_review` /
    advisor v3 — the main backtest pipeline never sees it.

    Phase 15-C fix: compute the equivalent quality metrics directly from
    existing feature_store columns so EVERY historical rebalance month
    benefits, not just live entries. Backtest sees the filter retroactively
    and the ML walk-forward learns the proper weight.

    Score [0.0, 1.0] combines 4 conditions multiplicatively:

      1. Extension penalty (peaks at +0% to +5% above 52w-MA, decays
         toward 0 at +30% above i.e. chasing).
      2. RSI zone (peaks at 50-65, decays at <30 or >75).
      3. Momentum sweet spot (peaks at mom_3m +5% to +15%, penalizes
         mom_3m > +50% as already-extended).
      4. Volume confirmation (boost when volume_ratio_50d >= 1.5).

    Higher score = "ideal entry setup" (READY in scanner terms). Lower =
    EXTENDED / chase-worthy / low-conviction.

    Used as ML feature so Ridge/Logistic learn weight, AND as a
    cross-sectional rank input for sleeve assignment via the
    `entry_quality_score` column entering DEFAULT_FEATURES.
    """
    d = df.copy() if df is not None else pd.DataFrame()
    if d.empty:
        d["entry_quality_score"] = pd.Series(dtype=float)
        return d
    dist_ma200 = numeric_series_or_default(d, "dist_ma200", 0.0)
    rsi14 = numeric_series_or_default(d, "rsi14", 50.0)
    mom_3m = numeric_series_or_default(d, "mom_3m", 0.0)
    near_52w_high = numeric_series_or_default(d, "near_52w_high_pct", 0.0)
    # Volume ratio is scanner-only; use mom_3m * volatility proxy if absent.
    # Most feature_store doesn't carry the 50d volume ratio — fall back to
    # neutral 1.0 (no boost / no penalty) when missing.
    volume_ratio_50d = numeric_series_or_default(d, "volume_ratio_50d", 1.0)

    # 1. Extension penalty: +0-5% above 200-MA = ideal, decay above +20%.
    extension_part = pd.Series(1.0, index=d.index, dtype=float)
    extension_part = extension_part.mask(
        dist_ma200 > 0.05,
        (1.0 - ((dist_ma200 - 0.05) / 0.25)).clip(lower=0.0, upper=1.0),
    )
    extension_part = extension_part.mask(
        dist_ma200 < -0.20,
        (1.0 + ((dist_ma200 + 0.20) / 0.20)).clip(lower=0.0, upper=1.0),
    )

    # 2. RSI zone: 50-65 ideal, decay outside [40, 75].
    rsi_part = pd.Series(1.0, index=d.index, dtype=float)
    rsi_part = rsi_part.mask(
        (rsi14 < 40) | (rsi14 > 75),
        0.4,
    )
    rsi_part = rsi_part.mask(rsi14 > 80, 0.0)

    # 3. Momentum sweet spot: mom_3m +5% to +15% = ideal, > +50% = chase.
    mom_part = pd.Series(1.0, index=d.index, dtype=float)
    mom_part = mom_part.mask(
        mom_3m > 0.50,
        (1.0 - ((mom_3m - 0.50) / 0.50)).clip(lower=0.0, upper=1.0),
    )
    mom_part = mom_part.mask(mom_3m < -0.10, 0.5)

    # 4. Volume confirmation boost (multiplicative, capped at 1.2x).
    vol_boost = (1.0 + ((volume_ratio_50d - 1.0) * 0.2)).clip(lower=0.5, upper=1.2)

    score = (extension_part * rsi_part * mom_part * vol_boost).clip(lower=0.0, upper=1.0).fillna(0.5)
    d["entry_quality_score"] = score
    return d


def compute_early_cycle_inflection_score(df: pd.DataFrame) -> pd.DataFrame:
    """Phase 15-B early-cycle inflection — find the next SNDK / MU before breakout.

    The Phase 15-A cycle_recovery_score requires mom_6m > 30% AND mom_3m > 10% —
    by that point the breakout is well underway (e.g. SNDK +125% mom_3m as of
    SHIPPED scored_latest.csv). That score rescues already-extended cycle
    leaders but captures little forward alpha.

    This score targets the OPPOSITE end: tickers that look like SNDK / MU did
    6 months BEFORE their move. Stage 1 -> Stage 2 transition with early
    institutional accumulation, no consensus yet, earnings just turning, but
    price still near MA200 (not yet broken out).

    Six conditions split into a multiplicative GATE and an additive BOOST:

      GATE (must all fire — multiplicative, score=0 if any fails):
        1. Price near MA200 zone (-10% <= dist_ma200 <= +5%)
        2. mom_12m still cycle-bottom (-30% <= mom_12m <= +5%)
        3. mom_3m early turn (-5% <= mom_3m <= +20%)

      BOOST (additive bonuses on top of gate):
        4. eps_revision_proxy > +3% (40% boost weight)
        5. any_profit_sign_flip_pos = 1 (30% boost weight)
        6. industry_breadth_above_ma200 mid-recovery (30% boost weight)

    Final: score = gate * (0.50 + 0.50 * boost). Gate-only fire -> 0.50,
    full gate + full boost -> 1.00.

    The multiplicative gate is critical: previous additive design was admitting
    already-extended names (NEU mom_12m +23%, CEG +50%) into top 30 because
    cond1+cond3+cond6 partial credit was overriding cond2 (cycle bottom)
    failure. The new design hard-rejects names outside the cycle-bottom zone.

    Returns continuous score [0.0, 1.0]. >= 0.50 = full gate fires (early-cycle
    setup confirmed), >= 0.70 = strong setup with eps + industry support,
    >= 0.85 = textbook "next SNDK 6mo prior" signal.
    """
    d = df.copy() if df is not None else pd.DataFrame()
    if d.empty:
        d["early_cycle_inflection_score"] = pd.Series(dtype=float)
        return d
    dist_ma200 = numeric_series_or_default(d, "dist_ma200", np.nan)
    mom_12m = numeric_series_or_default(d, "mom_12m", np.nan)
    mom_3m = numeric_series_or_default(d, "mom_3m", 0.0)
    eps_rev = numeric_series_or_default(d, "eps_revision_proxy", 0.0)
    any_flip = numeric_series_or_default(d, "any_profit_sign_flip_pos", 0.0)
    ind_breadth = numeric_series_or_default(d, "industry_breadth_above_ma200", np.nan)

    # GATE 1: Price near breakout zone. Hard reject if outside [-10%, +5%].
    cond1 = pd.Series(0.0, index=d.index, dtype=float)
    in_zone1 = (dist_ma200 >= -0.10) & (dist_ma200 <= 0.05)
    cond1 = cond1.mask(in_zone1,
                       1.0 - ((dist_ma200 - (-0.025)).abs() / 0.075).clip(lower=0.0, upper=1.0))
    cond1 = cond1.where(dist_ma200.notna(), 0.0).clip(lower=0.0, upper=1.0)

    # GATE 2: Cycle-bottom 12m. Hard reject if outside [-30%, +5%].
    cond2 = pd.Series(0.0, index=d.index, dtype=float)
    in_zone2 = (mom_12m >= -0.30) & (mom_12m <= 0.05)
    cond2 = cond2.mask(in_zone2,
                       1.0 - ((mom_12m - (-0.10)).abs() / 0.20).clip(lower=0.0, upper=1.0))
    cond2 = cond2.where(mom_12m.notna(), 0.0).clip(lower=0.0, upper=1.0)

    # GATE 3: Early-turn 3m. Hard reject if outside [-5%, +20%].
    cond3 = pd.Series(0.0, index=d.index, dtype=float)
    in_zone3 = (mom_3m >= -0.05) & (mom_3m <= 0.20)
    cond3 = cond3.mask(in_zone3,
                       1.0 - ((mom_3m - 0.075).abs() / 0.125).clip(lower=0.0, upper=1.0))
    cond3 = cond3.where(mom_3m.notna(), 0.0).clip(lower=0.0, upper=1.0)

    # Multiplicative gate — any single failure zeros the score.
    gate = (cond1 * cond2 * cond3).clip(lower=0.0, upper=1.0)

    # BOOST 4: EPS revision turning up: 0 at +0.03, 1.0 at +0.15.
    boost4 = ((eps_rev - 0.03) / 0.12).clip(lower=0.0, upper=1.0).fillna(0.0)
    # BOOST 5: Profitability improving — broad signal (Phase 15-C fix).
    # Original used `any_profit_sign_flip_pos` only (2/625 firing on SHIPPED
    # snapshot). New: any of sign_flip / loss_narrowing / eps_growth>10% /
    # phase9_c3_eps_turn_positive. Covers SNDK-class (still loss but
    # narrowing) which the strict sign-flip never captured.
    loss_narrowing = numeric_series_or_default(d, "ni_loss_narrowing_4q", 0.0)
    eps_growth_yoy = numeric_series_or_default(d, "eps_growth_yoy", 0.0)
    c3_eps_turn = numeric_series_or_default(d, "phase9_c3_eps_turn_positive", 0.0)
    boost5 = (
        (any_flip > 0)
        | (loss_narrowing > 0)
        | (eps_growth_yoy > 0.10)
        | (c3_eps_turn > 0)
    ).astype(float)
    # BOOST 6: Industry mid-recovery (peaks at 0.35, OK from 0.20 to 0.50).
    boost6 = pd.Series(0.0, index=d.index, dtype=float)
    boost6 = boost6.mask((ind_breadth >= 0.20) & (ind_breadth <= 0.50),
                         1.0 - ((ind_breadth - 0.35).abs() / 0.15).clip(lower=0.0, upper=1.0))
    boost6 = boost6.where(ind_breadth.notna(), 0.0).clip(lower=0.0, upper=1.0)

    boost = (0.40 * boost4 + 0.30 * boost5 + 0.30 * boost6).clip(lower=0.0, upper=1.0)

    # Combine: gate-only fire -> 0.50, full gate + full boost -> 1.00.
    score = (gate * (0.50 + 0.50 * boost)).clip(lower=0.0, upper=1.0).fillna(0.0)
    d["early_cycle_inflection_score"] = score
    return d


def compute_cycle_recovery_score(df: pd.DataFrame) -> pd.DataFrame:
    """Phase 15-A cycle recovery — rescue cyclical leaders from gate exclusion.

    Memory / foundry-equipment / cyclical-semis names (SNDK / MU / WDC /
    AMKR class) systematically fail the Phase 9 thesis-gate because their
    `multi_year_winner_score` is 0 — by construction. They've spent the last
    24-36 months in a cycle bottom, so mom_24m and mom_36m are negative or
    near zero, but mom_6m / mom_3m are strongly positive as the cycle turns.

    This score fires when ALL of:
      - mom_24m < 0.10           (still below 24mo ago, i.e. cycle bottom)
      - mom_6m  > 0.30           (turning up sharply)
      - mom_3m  > 0.10           (recent confirmation)
      - earnings improving       (broad EPS trend signal — see below)

    Phase 15-C fix (2026-04-28): the original definition used only
    `any_profit_sign_flip_pos` which is genuinely sparse (only 2/625 firing
    in the SHIPPED scored_latest because most R1000 names are either long-
    profitable or still in deep loss). SNDK is currently loss-making
    (net_income_ttm = -$1.64B) so the sign-flip flag legitimately = 0 —
    BUT SNDK is exactly the cycle-recovery name we want to capture.

    Broader EPS-improving signal: any of
      (a) any_profit_sign_flip_pos = 1  (just turned positive)
      (b) ni_loss_narrowing_4q = 1       (still loss but loss decreasing)
      (c) eps_growth_yoy > 0.10          (positive EPS growth >= 10%)
      (d) phase9_c3_eps_turn_positive    (Phase 9 C3 combined signal)

    Returns continuous score [0.0, 1.0]. Used by Phase 15-A as a thesis-gate
    bypass: tickers with cycle_recovery_score >= 0.5 can be assigned to a
    sleeve even when multi_year_winner_score is too low.

    Does NOT require sub_industry classification — purely technical/fundamental.
    Captures the same "cycle bottom + EPS turn" signal that the user's
    intuition flagged as missing for SNDK / MU.
    """
    d = df.copy() if df is not None else pd.DataFrame()
    if d.empty:
        d["cycle_recovery_score"] = pd.Series(dtype=float)
        return d
    mom_24m = numeric_series_or_default(d, "mom_24m", np.nan)
    mom_6m = numeric_series_or_default(d, "mom_6m", 0.0)
    mom_3m = numeric_series_or_default(d, "mom_3m", 0.0)

    # Broad earnings-improving signal (Phase 15-C): any of 4 conditions fires.
    sign_flip = numeric_series_or_default(d, "any_profit_sign_flip_pos", 0.0)
    loss_narrowing = numeric_series_or_default(d, "ni_loss_narrowing_4q", 0.0)
    eps_growth = numeric_series_or_default(d, "eps_growth_yoy", 0.0)
    c3_eps_turn = numeric_series_or_default(d, "phase9_c3_eps_turn_positive", 0.0)
    earnings_improving = (
        (sign_flip > 0) | (loss_narrowing > 0) | (eps_growth > 0.10) | (c3_eps_turn > 0)
    ).astype(float)

    # Bottom signal: still below 24mo ago (recovering, not yet exceeded prior peak)
    bottom_part = ((0.10 - mom_24m) / 0.30).clip(lower=0.0, upper=1.0)
    # Turn-up signal: 6m strongly positive
    turn_part = ((mom_6m - 0.30) / 0.20).clip(lower=0.0, upper=1.0)
    # Recent confirmation: 3m positive too
    recent_part = ((mom_3m - 0.10) / 0.20).clip(lower=0.0, upper=1.0)

    score = (bottom_part * turn_part * recent_part * earnings_improving).clip(lower=0.0, upper=1.0).fillna(0.0)
    # If mom_24m is NaN (insufficient history), score is 0 (no cycle context)
    score = score.where(mom_24m.notna(), 0.0)
    d["cycle_recovery_score"] = score
    return d


def compute_eps_revision_score(df: pd.DataFrame) -> pd.DataFrame:
    """Phase 15-A EPS revision momentum — analyst upgrade catalyst signal.

    Phase 15-C fix (2026-04-28): the original implementation read
    `eps_revision_proxy` which depends on Alpha Vantage `quarterlyEstimates`
    data. AV free tier is 25 calls/day, so in the SHIPPED Phase 15 backtest
    the column was 0/625 populated — the score was effectively dead.

    New implementation cascades through 3 sources:
      1. eps_revision_proxy        (AV estimates — primary, sparse)
      2. eps_growth_yoy             (computed from EPS history — 419/625)
      3. eps_cagr_1y                (1-year EPS trend — 406/625)

    The cascade lets the score fire on ~67% of universe instead of 0%.
    Captures "earnings improving" as a proxy for "analysts revising up"
    when AV estimates are missing.

    Returns score [0.0, 1.0]:
      - 1.0 at +20% revision/growth
      - 0.5 at +10%
      - 0.0 at <= 0%
    """
    d = df.copy() if df is not None else pd.DataFrame()
    if d.empty:
        d["eps_revision_score"] = pd.Series(dtype=float)
        return d
    # Cascade through 3 sources, taking first non-NaN value per row.
    revision = numeric_series_or_default(d, "eps_revision_proxy", np.nan)
    eps_growth = numeric_series_or_default(d, "eps_growth_yoy", np.nan)
    eps_cagr_1y = numeric_series_or_default(d, "eps_cagr_1y", np.nan)
    effective = revision.where(revision.notna(), eps_growth)
    effective = effective.where(effective.notna(), eps_cagr_1y).fillna(0.0)
    # Map to [0, 1]: 0% -> 0, +10% -> 0.5, +20% -> 1.0
    score = (effective / 0.20).clip(lower=0.0, upper=1.0).fillna(0.0)
    d["eps_revision_score"] = score
    return d


# =====================================================================
# Phase 17 v3 Layer 1 (2026-04-30): 5-state market regime classifier.
# Discrete label on top of existing market_regime_score / vix_z_63d /
# spy_above_ma200 / spy_ret_3m so downstream sleeve weight + tactical
# allocation logic can branch on a clean state instead of a continuous
# blend. Used by L2/L7/L8 to swap policy candidates by regime.
#
# States (ordered):
#   deep_bear    SPY < MA200 AND spy_ret_3m < -10% AND vix_z_63d > 2.0
#   bear         SPY < MA200 OR (vix_z_63d > 1.0 AND spy_ret_3m < -3%)
#   neutral      everything else
#   bull         SPY > MA200 AND vix_z_63d < 0 AND spy_ret_3m > 5%
#   strong_bull  SPY > MA200 AND vix_z_63d < -0.5 AND spy_ret_3m > 10%
#                AND market_breadth_above_ma200 > 0.6
#
# Emits two columns per row:
#   regime_state            string (one of 5 above)
#   regime_state_score      int  -2/-1/0/+1/+2  (numeric for ML)
# =====================================================================

PHASE17_REGIME_STATE_COLUMNS = [
    "regime_state",
    "regime_state_score",
]

_REGIME_STATE_NUMERIC = {
    "deep_bear": -2,
    "bear": -1,
    "neutral": 0,
    "bull": 1,
    "strong_bull": 2,
}


def compute_regime_state_classifier(df: pd.DataFrame) -> pd.DataFrame:
    """Phase 17 v3 L1 — discrete 5-state regime label per row.

    Pure transform. Reads existing macro columns; if any are missing,
    uses neutral defaults (vix_z=0, spy_above_ma200=1, spy_ret_3m=0,
    breadth=0.5) so the function always emits both columns.
    """
    d = df.copy() if df is not None else pd.DataFrame()
    if d.empty:
        d["regime_state"] = pd.Series(dtype=object)
        d["regime_state_score"] = pd.Series(dtype=int)
        return d

    spy_above = numeric_series_or_default(d, "spy_above_ma200", 1.0).astype(float)
    vix_z = numeric_series_or_default(d, "vix_z_63d", 0.0).astype(float)
    spy_3m = numeric_series_or_default(d, "spy_ret_3m", 0.0).astype(float)
    breadth = numeric_series_or_default(d, "market_breadth_above_ma200", 0.5).astype(float)

    # Order matters: evaluate strongest conditions first, fall through
    # to milder ones, default neutral.
    deep_bear = (spy_above < 0.5) & (spy_3m < -0.10) & (vix_z > 2.0)
    bear = (spy_above < 0.5) | ((vix_z > 1.0) & (spy_3m < -0.03))
    bull = (spy_above >= 0.5) & (vix_z < 0.0) & (spy_3m > 0.05)
    strong_bull = (
        (spy_above >= 0.5)
        & (vix_z < -0.5)
        & (spy_3m > 0.10)
        & (breadth > 0.6)
    )

    label = pd.Series("neutral", index=d.index, dtype=object)
    # Apply in increasing severity so later assignments override
    label = label.mask(bear, "bear")
    label = label.mask(deep_bear, "deep_bear")
    label = label.mask(bull & ~bear, "bull")
    label = label.mask(strong_bull & ~bear, "strong_bull")

    d["regime_state"] = label
    d["regime_state_score"] = label.map(_REGIME_STATE_NUMERIC).fillna(0).astype(int)
    return d


# =====================================================================
# Phase 17 v3 Layer 8 (2026-04-30): ETF leadership-aware adaptive cap.
# Reads cloud_results/etf_leadership/latest.json (written by
# tools/etf_leadership_snapshot.py daily). Returns a sector-cap multiplier
# in [0.5, 2.0] -- relax when leading sector ETF is hot, tighten when
# lagging. Falls through to 1.0 (neutral) if file missing.
# =====================================================================

# Map GICS sector label -> sector ETF ticker (must match SECTOR_ETFS in
# tools/etf_leadership_snapshot.py).
_SECTOR_TO_ETF = {
    "technology": "XLK",
    "information technology": "XLK",
    "financials": "XLF",
    "energy": "XLE",
    "health care": "XLV",
    "healthcare": "XLV",
    "consumer discretionary": "XLY",
    "industrials": "XLI",
    "materials": "XLB",
    "consumer staples": "XLP",
    "utilities": "XLU",
    "real estate": "XLRE",
    "communication services": "XLC",
    "communications": "XLC",
}

_ETF_LEADER_CACHE: dict = {}
_ETF_LEADER_CACHE_PATH: Optional[str] = None


def _load_etf_leader_state() -> dict:
    """Read cloud_results/etf_leadership/latest.json once (cached)."""
    global _ETF_LEADER_CACHE, _ETF_LEADER_CACHE_PATH
    if _ETF_LEADER_CACHE:
        return _ETF_LEADER_CACHE
    path = Path("cloud_results/etf_leadership/latest.json")
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
        _ETF_LEADER_CACHE = data.get("sector_states", {}) or {}
        _ETF_LEADER_CACHE_PATH = str(path)
    except Exception:
        _ETF_LEADER_CACHE = {}
    return _ETF_LEADER_CACHE


def etf_leader_state_for_sector(sector: str) -> str:
    """Return the latest ETF state for a GICS sector ('hot', 'warm',
    'neutral', 'lagging', 'capitulating', 'unknown'). Defaults to 'unknown'
    when ETF leadership snapshot hasn't been generated yet."""
    if not sector:
        return "unknown"
    states = _load_etf_leader_state()
    if not states:
        return "unknown"
    label = _SECTOR_TO_ETF.get(str(sector).strip().lower())
    if label is None:
        return "unknown"
    # states map is keyed by friendly label (eg 'tech' for XLK), built in
    # etf_leadership_snapshot.py via SECTOR_ETFS dict. Reverse-map ticker -> friendly.
    from tools.etf_leadership_snapshot import SECTOR_ETFS  # type: ignore
    friendly = SECTOR_ETFS.get(label, label.lower())
    return str(states.get(friendly, "unknown"))


def adaptive_sector_cap_multiplier(sector: str, default: float = 1.0) -> float:
    """Phase 17 v3 L8 -- adjust per-sector position cap based on ETF
    leadership state. Hot leader -> 1.5x cap (let winners run). Lagging
    -> 0.7x. Capitulating -> 0.5x.

    Returns multiplier as a float; caller multiplies by base sector_cap.
    """
    state = etf_leader_state_for_sector(sector)
    return {
        "hot": 1.50,
        "warm": 1.20,
        "neutral": 1.00,
        "lagging": 0.70,
        "capitulating": 0.50,
        "unknown": float(default),
    }.get(state, float(default))


# =====================================================================
# Phase 18c (2026-04-30): auto feature-gate application.
# Reads research/auto_feature_gates.yaml (drafted by
# tools/feature_gate_proposal.py from Phase 18b insights, gated by
# human PR review). Provides:
#   * load_auto_feature_gates() -> dict of normalized gate rules
#   * apply_signal_regime_gate(value, signal, regime) -> float
# Engine code that wants to honor gates calls apply_* on each signal
# value. The gates auto-expire after `expires_at` -- post-expiry the
# loader returns no rules so engine reverts to ungated behavior.
# =====================================================================

_AUTO_GATES_CACHE: Optional[dict] = None
_AUTO_GATES_PATH = Path("research/auto_feature_gates.yaml")


def _parse_simple_yaml(text: str) -> dict:
    """Minimal YAML parser sufficient for auto_feature_gates.yaml.

    Avoids a hard dependency on pyyaml so the engine can import even in
    environments where yaml isn't installed (eg minimal smoke harness).
    Falls back to pyyaml if available for robustness.
    """
    try:
        import yaml  # type: ignore
        return yaml.safe_load(text) or {}
    except ImportError:
        pass

    out: dict = {"gates": []}
    current_gate: Optional[dict] = None
    in_signature = False
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        # top-level scalar (generated_at / expires_at / n_proposals)
        stripped = line.lstrip()
        indent = len(line) - len(stripped)
        if indent == 0 and ":" in stripped and not stripped.startswith("-"):
            key, _, val = stripped.partition(":")
            val = val.strip().strip("'\"")
            if key == "gates":
                continue
            out[key] = val
            continue
        # gate list item start
        if stripped.startswith("- kind:"):
            current_gate = {"kind": stripped.split(":", 1)[1].strip()}
            out["gates"].append(current_gate)
            in_signature = False
            continue
        if current_gate is None:
            continue
        if "feature_signature_z:" in stripped:
            current_gate["feature_signature_z"] = {}
            in_signature = True
            continue
        if in_signature and indent >= 6 and ":" in stripped:
            k, _, v = stripped.partition(":")
            try:
                current_gate["feature_signature_z"][k.strip()] = float(v.strip())
            except ValueError:
                in_signature = False
        if not in_signature and ":" in stripped and not stripped.startswith("-"):
            k, _, v = stripped.partition(":")
            v = v.strip().strip("'\"")
            try:
                current_gate[k.strip()] = float(v)
            except ValueError:
                current_gate[k.strip()] = v
            in_signature = False
    return out


def load_auto_feature_gates(force_reload: bool = False) -> dict:
    """Load + cache the auto_feature_gates.yaml. Returns a dict with
    keys:
        gates_by_signal_regime: {(signal, regime): factor}
        pattern_blocks:         list of dicts (cluster_id, signature, ...)
        expired:                bool (true if past expires_at)
    """
    global _AUTO_GATES_CACHE
    if _AUTO_GATES_CACHE is not None and not force_reload:
        return _AUTO_GATES_CACHE
    out = {
        "gates_by_signal_regime": {},
        "pattern_blocks": [],
        "expired": False,
        "generated_at": None,
    }
    if not _AUTO_GATES_PATH.exists():
        _AUTO_GATES_CACHE = out
        return out
    try:
        text = _AUTO_GATES_PATH.read_text()
        parsed = _parse_simple_yaml(text)
    except Exception:
        _AUTO_GATES_CACHE = out
        return out

    out["generated_at"] = parsed.get("generated_at")
    expires_at = str(parsed.get("expires_at", ""))
    if expires_at:
        try:
            exp_dt = datetime.fromisoformat(expires_at)
            now = datetime.now(timezone.utc).replace(tzinfo=None) if exp_dt.tzinfo is None else datetime.now(timezone.utc)
            out["expired"] = now > exp_dt
        except Exception:
            out["expired"] = False

    if out["expired"]:
        _AUTO_GATES_CACHE = out
        return out

    for g in parsed.get("gates", []) or []:
        kind = str(g.get("kind", ""))
        if kind in ("signal_regime_disable", "signal_regime_amplify"):
            sig = str(g.get("signal", ""))
            reg = str(g.get("regime", ""))
            try:
                factor = float(g.get("factor", 1.0))
            except (TypeError, ValueError):
                factor = 1.0
            if sig and reg:
                out["gates_by_signal_regime"][(sig, reg)] = factor
        elif kind == "pattern_block":
            out["pattern_blocks"].append({
                "cluster_id": g.get("cluster_id"),
                "signature": g.get("feature_signature_z", {}),
                "win_rate": g.get("win_rate"),
                "n": g.get("n"),
            })
    _AUTO_GATES_CACHE = out
    return out


def apply_signal_regime_gate(
    value: float,
    signal: str,
    regime: str,
) -> float:
    """Multiply a raw signal value by its gate factor (1.0 if no gate
    matches). Pure lookup; no side effects.

    Engine call sites:
        gated = apply_signal_regime_gate(value, "rs_acceleration_score", regime)
    """
    if value is None or not signal or not regime:
        return value
    gates = load_auto_feature_gates()
    factor = gates.get("gates_by_signal_regime", {}).get((str(signal), str(regime)), 1.0)
    if factor == 1.0:
        return value
    try:
        return float(value) * float(factor)
    except (TypeError, ValueError):
        return value


def apply_signal_regime_gate_series(
    series: pd.Series,
    signal: str,
    regimes: pd.Series,
) -> pd.Series:
    """Vectorized variant -- multiply each row's value by the gate factor
    for that row's regime. NaN-safe."""
    if series is None or len(series) == 0:
        return series
    gates = load_auto_feature_gates()
    by_sr = gates.get("gates_by_signal_regime", {})
    if not by_sr:
        return series
    factors = pd.Series(1.0, index=series.index)
    if regimes is None or len(regimes) == 0:
        return series
    aligned_regimes = regimes.reindex(series.index).astype(str).fillna("")
    for (sig, reg), factor in by_sr.items():
        if sig != signal:
            continue
        mask = aligned_regimes == reg
        factors = factors.where(~mask, factor)
    return pd.to_numeric(series, errors="coerce") * factors


# Pattern block tolerance — distance threshold between row's z-scored
# signal vector and the cluster centroid, normalized by signature size.
# 0.6 is roughly "row is within 0.6 std of centroid on each top-3
# signal" -- conservative so we don't over-block. Tunable.
PATTERN_BLOCK_DISTANCE_TOL = 0.6
# Score-multiplier penalty applied to flagged rows. 0.0 = full block;
# 0.5 = halve the score (let it survive but unlikely to be picked).
PATTERN_BLOCK_SCORE_PENALTY = 0.0


def _row_matches_pattern_signature(
    row: pd.Series,
    signature: dict,
    z_lookup: dict,
    tol: float = PATTERN_BLOCK_DISTANCE_TOL,
) -> bool:
    """Test if a row's signal values (after cross-sectional z-scoring
    via z_lookup) lie within `tol` of every signature dimension."""
    if not signature or not z_lookup:
        return False
    n = 0
    for sig_name, target_z in signature.items():
        if sig_name not in z_lookup:
            return False
        try:
            actual = float(z_lookup[sig_name].get(row.name, 0.0))
        except (TypeError, ValueError):
            return False
        try:
            target = float(target_z)
        except (TypeError, ValueError):
            return False
        if abs(actual - target) > tol:
            return False
        n += 1
    return n > 0


def apply_phase18c_gates_to_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Walk all Phase 14 + Phase 17 signal columns and apply auto gates
    based on each row's regime_state. Pure transform; idempotent.

    Called once at the end of the feature pipeline (after all
    compute_* functions and after compute_regime_state_classifier).
    Returns the same DataFrame with gated values in place. Adds two
    audit columns:
        applied_gates_count   how many signal x regime gates fired
        pattern_blocked       1 if row matched a pattern_block centroid
    """
    if df is None or df.empty:
        return df
    gates = load_auto_feature_gates()
    by_sr = gates.get("gates_by_signal_regime", {})
    pattern_blocks = gates.get("pattern_blocks", []) or []
    if (not by_sr and not pattern_blocks) or "regime_state" not in df.columns:
        if "applied_gates_count" not in df.columns:
            df["applied_gates_count"] = 0
        if "pattern_blocked" not in df.columns:
            df["pattern_blocked"] = 0
        return df
    out = df.copy()
    regimes = out["regime_state"].astype(str).fillna("")
    fire_count = pd.Series(0, index=out.index)

    # 1. Signal x regime gates (existing behavior)
    signals_to_check = [s for s in {sig for (sig, _) in by_sr.keys()} if s in out.columns]
    for sig in signals_to_check:
        out[sig] = apply_signal_regime_gate_series(out[sig], sig, regimes)
        for (gate_sig, gate_reg), factor in by_sr.items():
            if gate_sig != sig or factor == 1.0:
                continue
            mask = regimes == gate_reg
            fire_count = fire_count + mask.astype(int)
    out["applied_gates_count"] = fire_count.astype(int)

    # 2. Pattern block matching (Phase 18c-followup, 2026-04-30).
    # For each pattern_block, compute cross-sectional z of every signature
    # signal (within this rebalance batch -- approximated globally if
    # rebalance_date column missing). Match rows whose every signature
    # signal is within tol of the centroid. Flag + apply score penalty.
    pattern_blocked = pd.Series(0, index=out.index)
    if pattern_blocks:
        # Collect all unique signature signals
        all_sig_names: set[str] = set()
        for pb in pattern_blocks:
            all_sig_names.update((pb.get("signature") or {}).keys())
        # Per-rebalance z-score lookup for these signals (or global if no
        # rebalance_date). Stored as {signal_name: {index: z_value}}.
        z_lookup: dict[str, dict] = {}
        date_grouper = "rebalance_date" if "rebalance_date" in out.columns else None
        for sig_name in all_sig_names:
            if sig_name not in out.columns:
                z_lookup[sig_name] = {}
                continue
            col = pd.to_numeric(out[sig_name], errors="coerce")
            if date_grouper:
                z = col.groupby(out[date_grouper], group_keys=False).transform(
                    lambda s: (s - s.mean()) / s.std(ddof=0) if s.std(ddof=0) > 0 else s * 0.0
                )
            else:
                std = col.std(ddof=0)
                z = (col - col.mean()) / std if std > 0 else col * 0.0
            z_lookup[sig_name] = z.to_dict()

        for pb in pattern_blocks:
            sig = pb.get("signature") or {}
            if not sig:
                continue
            mask = out.apply(
                lambda row, sig=sig: _row_matches_pattern_signature(row, sig, z_lookup),
                axis=1,
            )
            pattern_blocked = pattern_blocked + mask.astype(int)
        # Apply score penalty if score column exists. Multiplier 0 = block
        # outright; tunable via PATTERN_BLOCK_SCORE_PENALTY.
        if "score" in out.columns:
            blocked_mask = pattern_blocked > 0
            if blocked_mask.any():
                out.loc[blocked_mask, "score"] = (
                    pd.to_numeric(out.loc[blocked_mask, "score"], errors="coerce")
                    * PATTERN_BLOCK_SCORE_PENALTY
                )
    out["pattern_blocked"] = pattern_blocked.clip(upper=1).astype(int)
    return out


def tactical_allocation_for_regime(
    regime_state: str,
    cfg: Optional[EngineConfig] = None,
) -> float:
    """Phase 17 v3 L7 — return tactical sleeve allocation pct for a given
    regime_state. Reads `cfg.tactical_sleeve_allocation_by_regime` map;
    falls back to `cfg.tactical_sleeve_allocation_default` (0.0) for
    unknown states. Pure lookup — no side effects.

    Used by:
      * r1000_tactical_backtest.py to scale weekly position sizes.
      * Future main pipeline integration when tactical sleeve becomes
        a first-class portfolio component.
    """
    if cfg is None:
        # Default mapping if no cfg supplied (off-regime safe).
        defaults = {
            "deep_bear": 0.0,
            "bear": 0.0,
            "neutral": 0.0,
            "bull": 0.05,
            "strong_bull": 0.10,
        }
        return float(defaults.get(str(regime_state), 0.0))
    mapping = getattr(cfg, "tactical_sleeve_allocation_by_regime", None) or {}
    if not isinstance(mapping, dict):
        return float(getattr(cfg, "tactical_sleeve_allocation_default", 0.0))
    val = mapping.get(str(regime_state), getattr(cfg, "tactical_sleeve_allocation_default", 0.0))
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0


# =====================================================================
# Phase 17 v3 Layer 11 (2026-04-29): Explosive likelihood scoring.
# Inference for the dual entry/exit XGBoost models trained by
# tools/train_explosion_classifier.py on the historical event database
# produced by tools/build_explosive_pattern_db.py.
#
# Emits 3 columns per ticker:
#   explosion_entry_score    max of P(entry) at -12/-6/-3 mo horizons
#   explosion_exit_score     max of P(exit) at peak/+3/+6 mo horizons
#   explosion_net_score      entry - exit (net signal; >0 = buy, <0 = exit)
#
# If models are missing OR xgboost not installed OR feature inputs are
# absent, all three columns fall back to 0.0 — keep_cols whitelist
# survives, walk-forward training silently picks up zero contribution.
# =====================================================================

PHASE17_EXPLOSION_COLUMNS = [
    "explosion_entry_score",
    "explosion_exit_score",
    "explosion_net_score",
]

_EXPLOSION_MODEL_CACHE: dict = {}

# Mapping: trainer feature name -> (column candidates in feature_store, default)
_EXPLOSION_FEATURE_MAP = [
    ("mom_1m",                  ["mom_1m"],                                  0.0),
    ("mom_3m",                  ["mom_3m"],                                  0.0),
    ("mom_6m",                  ["mom_6m"],                                  0.0),
    ("mom_12m",                 ["mom_12m"],                                 0.0),
    ("vol_30d",                 ["volatility_30d", "atr14_pct"],             0.20),
    ("vol_90d",                 ["volatility_90d", "atr14_pct"],             0.25),
    ("max_dd_90d",              ["max_drawdown_90d", "max_dd_90d"],          0.0),
    ("rs_vs_spy_3m",            ["rs_benchmark_3m"],                         0.0),
    ("rs_vs_spy_6m",            ["rs_benchmark_6m"],                         0.0),
    ("rsi_14",                  ["rsi14"],                                   50.0),
    ("price_vs_sma_50",         ["price_vs_sma_50", "near_52w_high_pct"],    0.0),
    ("price_vs_sma_200",        ["price_vs_sma_200", "ma200_slope_1m"],      0.0),
    ("volume_surge",            ["volume_surge_30_180", "breakout_volume_z"], 1.0),
    ("dollar_vol_avg_20d_log",  ["dollar_vol_avg_20d_log"],                  0.0),
    ("mcap_proxy_log",          ["log_mktcap", "mcap_proxy_log"],            0.0),
]


def _load_explosion_models() -> dict:
    """Lazy-load XGBoost JSON boosters from outputs/explosive_pattern_db/models/.

    Returns dict {target_name: booster} or {} if anything fails.
    Cached after first successful load.
    """
    if _EXPLOSION_MODEL_CACHE:
        return _EXPLOSION_MODEL_CACHE
    try:
        import xgboost as xgb
    except ImportError:
        return {}
    model_dir = Path("outputs/explosive_pattern_db/models")
    if not model_dir.exists():
        return {}
    targets = [
        "entry_12mo", "entry_6mo", "entry_3mo",
        "exit_at_peak", "exit_post_peak_3mo", "exit_post_peak_6mo",
    ]
    out: dict = {}
    for tgt in targets:
        p = model_dir / f"{tgt}.json"
        if not p.exists():
            continue
        try:
            booster = xgb.XGBClassifier()
            booster.load_model(str(p))
            out[tgt] = booster
        except Exception:
            continue
    if out:
        _EXPLOSION_MODEL_CACHE.update(out)
    return out


def _build_explosion_feature_matrix(df: pd.DataFrame) -> Optional[np.ndarray]:
    """Assemble the 15-column feature matrix in trainer order.

    For each (trainer_name, candidates, default), pick the first candidate
    present in df; fill NaN with the default. Special-case mcap_proxy_log:
    if log_mktcap missing but mktcap present, compute log1p(mktcap).
    """
    if df is None or df.empty:
        return None
    cols: list[np.ndarray] = []
    for trainer_name, candidates, default in _EXPLOSION_FEATURE_MAP:
        s: Optional[pd.Series] = None
        for c in candidates:
            if c in df.columns:
                s = pd.to_numeric(df[c], errors="coerce")
                break
        if s is None and trainer_name == "mcap_proxy_log" and "mktcap" in df.columns:
            mc = pd.to_numeric(df["mktcap"], errors="coerce").clip(lower=0)
            s = np.log1p(mc)
        if s is None:
            s = pd.Series(default, index=df.index, dtype=float)
        cols.append(s.fillna(default).to_numpy(dtype=float))
    return np.column_stack(cols)


def compute_explosion_likelihood_score(df: pd.DataFrame, cfg: Optional[EngineConfig] = None) -> pd.DataFrame:
    """Phase 17 v3 L11 — score explosion entry / exit probabilities.

    Loads the 6 XGBoost classifiers trained on historical sustained
    explosions (+150% to +800% in 6mo, mcap >= $300M, sustained at
    T+24mo). Emits 3 ML-friendly columns. Falls through to zeros if
    models or features are absent — engine continues without error.
    """
    d = df.copy() if df is not None else pd.DataFrame()
    for col in PHASE17_EXPLOSION_COLUMNS:
        d[col] = 0.0

    if d.empty or not phase_is_enabled("phase17_explosion", default=True):
        return d

    models = _load_explosion_models()
    if not models:
        return d

    X = _build_explosion_feature_matrix(d)
    if X is None or len(X) == 0:
        return d

    entry_targets = ["entry_12mo", "entry_6mo", "entry_3mo"]
    exit_targets = ["exit_at_peak", "exit_post_peak_3mo", "exit_post_peak_6mo"]

    entry_probs: list[np.ndarray] = []
    exit_probs: list[np.ndarray] = []
    for tgt in entry_targets:
        if tgt in models:
            try:
                entry_probs.append(models[tgt].predict_proba(X)[:, 1])
            except Exception:
                continue
    for tgt in exit_targets:
        if tgt in models:
            try:
                exit_probs.append(models[tgt].predict_proba(X)[:, 1])
            except Exception:
                continue

    if entry_probs:
        d["explosion_entry_score"] = np.maximum.reduce(entry_probs)
    if exit_probs:
        d["explosion_exit_score"] = np.maximum.reduce(exit_probs)
    d["explosion_net_score"] = (
        d["explosion_entry_score"] - d["explosion_exit_score"]
    ).clip(lower=-1.0, upper=1.0)
    return d


def compute_theme_phase_features(df: pd.DataFrame) -> pd.DataFrame:
    """Wrap r1000_themes.attach_per_ticker_theme_features for production engine.

    Adds theme_phase_multiplier_primary + theme_phase_multiplier_max columns
    (numeric, ML-friendly) to the input df. Falls through to neutral=1.00 if
    themes.yaml unavailable or no overlap.

    Calls into r1000_themes.{load_themes, compute_theme_aggregates,
    attach_per_ticker_theme_features}.
    """
    d = df.copy() if df is not None else pd.DataFrame()
    policy_string_defaults = {
        "theme_horizon_primary": "unknown",
        "theme_holding_profile_primary": "neutral",
    }
    policy_numeric_defaults = {
        "theme_event_risk_sensitivity_primary": 0.35,
        "theme_event_risk_sensitivity_max": 0.35,
        "theme_structural_growth_primary": 0.35,
        "theme_structural_growth_max": 0.35,
        "theme_target_hold_months_primary": 12.0,
        "theme_max_hold_months_primary": 36.0,
        "theme_short_cycle_flag_primary": 0.0,
        "theme_short_cycle_flag_max": 0.0,
    }
    def _fill_theme_defaults(frame: pd.DataFrame) -> pd.DataFrame:
        for col, default in policy_string_defaults.items():
            if col not in frame.columns:
                frame[col] = default
            frame[col] = frame[col].fillna(default).astype(str)
        for col, default in policy_numeric_defaults.items():
            if col not in frame.columns:
                frame[col] = default
            frame[col] = pd.to_numeric(frame[col], errors="coerce").fillna(default)
        return frame
    if d.empty or "ticker" not in d.columns:
        d["theme_phase_multiplier_primary"] = 1.0
        d["theme_phase_multiplier_max"] = 1.0
        return _fill_theme_defaults(d)
    try:
        from r1000_themes import (
            attach_per_ticker_theme_features,
            compute_theme_aggregates,
            load_themes,
            THEME_PHASE_MULTIPLIER,
        )
    except Exception:
        d["theme_phase_multiplier_primary"] = 1.0
        d["theme_phase_multiplier_max"] = 1.0
        return _fill_theme_defaults(d)
    themes = load_themes()
    if not themes:
        d["theme_phase_multiplier_primary"] = 1.0
        d["theme_phase_multiplier_max"] = 1.0
        return _fill_theme_defaults(d)
    # Run aggregation per rebalance_date if present (cross-sectional within each date)
    if "rebalance_date" in d.columns:
        out_chunks = []
        for date_val, chunk in d.groupby("rebalance_date", sort=False):
            agg = compute_theme_aggregates(chunk, themes)
            attached = attach_per_ticker_theme_features(chunk, themes, agg)
            out_chunks.append(attached)
        out = pd.concat(out_chunks, ignore_index=False) if out_chunks else d
    else:
        agg = compute_theme_aggregates(d, themes)
        out = attach_per_ticker_theme_features(d, themes, agg)
    # Ensure both columns exist with neutral default
    for col in ("theme_phase_multiplier_primary", "theme_phase_multiplier_max"):
        if col not in out.columns:
            out[col] = 1.0
        out[col] = pd.to_numeric(out[col], errors="coerce").fillna(1.0)
    return _fill_theme_defaults(out)
