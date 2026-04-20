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

import re
from typing import Any, Optional

import numpy as np
import pandas as pd

from r1000_helpers import (
    alpha_vantage_pause_seconds,
    cache_live_file,
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
    FUND_TTM_FALLBACK_COLUMNS,
    MACRO_REGIME_COLUMNS,
    MARKET_ADAPTATION_COLUMNS,
    MOAT_PROXY_COLUMNS,
    PHASE5_LEADER_LAGGARD_COLUMNS,
    PHASE9_C3_TURNAROUND_COLUMNS,
    REGIME_ROTATION_COLUMNS,
    SAGE_SECTOR_MAP,
    YF_INDUSTRY_TO_GICS_GROUP,
    YF_QUARTERLY_COL_MAP,
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
    if col not in df.columns:
        return pd.Series(pd.NaT, index=df.index, dtype="datetime64[ns]")
    return pd.to_datetime(df[col], errors="coerce")


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

    d["forward_pe_final"] = numeric_series_or_default(d, "av_forward_pe", np.nan)
    d["forward_pe_final"] = d["forward_pe_final"].fillna(numeric_series_or_default(d, "forward_pe", np.nan))
    d["forward_pe_final"] = d["forward_pe_final"].fillna(
        (1.0 / numeric_series_or_default(d, "ep_ttm", np.nan)).where(
            numeric_series_or_default(d, "ep_ttm", np.nan) > 0
        )
    )
    d["ev_to_ebitda_final"] = numeric_series_or_default(d, "av_ev_to_ebitda", np.nan)

    d["peg_final"] = numeric_series_or_default(d, "av_peg_ratio", np.nan)
    d["peg_final"] = d["peg_final"].fillna(numeric_series_or_default(d, "peg_ratio", np.nan))

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
