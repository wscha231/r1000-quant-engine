#!/usr/bin/env python3
"""Run the bounded Run287 P6 candidate-gate and score-stability audit.

The tool separates decision-time diagnostics from outcome labels.  Selection
axes, ranks, completeness, and rejection reasons are finalized first.  Forward
returns are then attached only to the measurement copy.  It never writes an
operating target, runs fullrun, enables production, or trades.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from r1000_candidate_lanes import materialize_sector_relative_strength  # noqa: E402
from tools.run_weekly_evaluation import load_price_series  # noqa: E402


SCHEMA_VERSION = "run287-candidate-gate-stability-audit-v1"
ACTIVE_HEADS = (
    "pred_lin_ret",
    "pred_lin_p",
    "pred_future_winner_ret",
    "pred_future_winner_p",
    "pred_cat_ret",
    "pred_cat_p",
)
HORIZONS = (21, 63, 126, 252)
OOS_WINDOWS = {"full": "2019-01-01", "oos2": "2023-01-01", "oos": "2024-07-01"}
CASH_TICKERS = {"CASH", "__CASH__"}
REJECTION_TAXONOMY = (
    "SELECTED",
    "CANDIDATE_GATE",
    "DATA_INCOMPLETENESS",
    "RISK_STATE_OR_CASH",
    "NAME_OR_SECTOR_CAPACITY",
    "TREND_OR_RS_FAILURE",
    "VALUATION_OR_THESIS_FAILURE",
)
CRITICAL_FIELDS = (
    "alphaops_vnext_score",
    "mom_3m",
    "rs_benchmark_3m",
    "rs_sector_3m",
    "price_above_ma200",
    "dollar_vol_20d",
    "industry_group_strength_score",
    "sector_adjusted_quality_score",
    "capital_efficiency_score",
    "fundamental_reliability_score",
)
AXIS_FEATURES: dict[str, tuple[str, ...]] = {
    "quality_balance_sheet": (
        "sector_adjusted_quality_score", "capital_efficiency_score",
        "long_hold_compounder_score", "fundamental_reliability_score",
    ),
    "growth_acceleration": (
        "sales_growth_yoy", "eps_growth_yoy", "op_income_growth_yoy",
        "ocf_growth_yoy", "rev_growth_accel_4q", "gross_margins",
        "operating_margins",
    ),
    "estimate_guidance_pit": (
        "eps_revision_score", "revision_score", "actual_results_score",
        "event_reaction_score",
    ),
    "price_volume_rs": (
        "mom_1m", "mom_3m", "mom_6m", "relative_strength_composite",
        "rs_benchmark_3m", "price_above_ma50", "price_above_ma200",
        "dollar_vol_20d",
    ),
    "industry_theme_leadership": (
        "rs_sector_3m", "industry_group_strength_score",
        "oneil_leadership_score", "etf_theme_leadership_score",
    ),
    "valuation_expectation_risk": (
        "valuation_support_score", "risk_penalty", "overheat_penalty",
        "stage2_overext_penalty",
    ),
    "liquidity_lifecycle_data_risk": (
        "dollar_vol_20d", "portfolio_risk_entry_block_score",
        "portfolio_stale_mega_leader_score", "live_event_risk_score",
        "atr14_pct",
    ),
}


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def write_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, lineterminator="\n")


def clean_ticker(value: Any) -> str:
    text = str(value or "").upper().strip()
    return "" if text in {"", "NAN", "NONE"} else text


def boolish(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y"}


def finite(value: Any, default: float = math.nan) -> float:
    try:
        out = float(value)
        return out if math.isfinite(out) else default
    except (TypeError, ValueError):
        return default


def normalize_candidates(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    required = {"rebalance_date", "ticker", "sector", "mom_3m", "alphaops_vnext_score"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError("candidate cache missing:" + ",".join(sorted(missing)))
    out = frame.copy()
    out["rebalance_date"] = pd.to_datetime(out["rebalance_date"], errors="coerce").dt.normalize()
    out["ticker"] = out["ticker"].map(clean_ticker)
    if out["rebalance_date"].isna().any() or out["ticker"].eq("").any():
        raise ValueError("candidate cache has invalid date/ticker")
    duplicate_rows = int(out.duplicated(["rebalance_date", "ticker"], keep=False).sum())
    conflict_columns: list[str] = []
    if duplicate_rows:
        for column in set(CRITICAL_FIELDS) & set(out.columns):
            values = out.groupby(["rebalance_date", "ticker"], sort=False)[column].nunique(dropna=False)
            if bool(values.gt(1).any()):
                conflict_columns.append(column)
    if conflict_columns:
        raise ValueError("candidate duplicate conflicts:" + ",".join(sorted(conflict_columns)))
    out = out.drop_duplicates(["rebalance_date", "ticker"], keep="first")
    return out.sort_values(["rebalance_date", "ticker"]).reset_index(drop=True), {
        "input_rows": int(len(frame)),
        "deduplicated_rows": int(len(out)),
        "duplicate_rows": duplicate_rows,
        "duplicate_conflict_columns": conflict_columns,
    }


def repair_sector_rs(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    before = pd.to_numeric(
        frame.get("rs_sector_3m", pd.Series(np.nan, index=frame.index)),
        errors="coerce",
    )
    preserved = before.copy()
    repaired = materialize_sector_relative_strength(
        frame,
        periods=(("mom_3m", "rs_sector_3m"),),
        fill_missing_only=True,
    )
    after = pd.to_numeric(repaired["rs_sector_3m"], errors="coerce")
    finite_before = before.notna()
    preservation_error = (
        float((after[finite_before] - preserved[finite_before]).abs().max())
        if finite_before.any() else 0.0
    )
    audit = {
        "definition": "mom_3m_minus_same_rebalance_date_sector_mean",
        "coverage_before": float(finite_before.mean()),
        "coverage_after": float(after.notna().mean()),
        "coverage_increase_pp": float((after.notna().mean() - finite_before.mean()) * 100.0),
        "filled_cell_count": int((~finite_before & after.notna()).sum()),
        "existing_finite_cell_count": int(finite_before.sum()),
        "existing_finite_max_absolute_error": preservation_error,
        "existing_finite_preserved": preservation_error <= 1e-15,
        "used_forward_return": False,
    }
    return repaired, audit


def robust_z_by_date(frame: pd.DataFrame, column: str) -> pd.Series:
    values = pd.to_numeric(frame.get(column), errors="coerce")
    def transform(group: pd.Series) -> pd.Series:
        finite_values = group.dropna()
        if finite_values.empty:
            return pd.Series(np.nan, index=group.index)
        median = float(finite_values.median())
        mad = float((finite_values - median).abs().median())
        scale = 1.4826 * mad
        if scale <= 1e-12:
            scale = float(finite_values.std(ddof=0))
        if scale <= 1e-12:
            return pd.Series(0.0, index=group.index)
        return ((group - median) / scale).clip(-4.0, 4.0)
    return values.groupby(frame["rebalance_date"], sort=False).transform(transform)


def candidate_decomposition(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame[["rebalance_date", "ticker", "sector", "alphaops_vnext_score"]].copy()
    all_axis_fields = sorted({column for columns in AXIS_FEATURES.values() for column in columns})
    numeric = frame.reindex(columns=all_axis_fields).apply(pd.to_numeric, errors="coerce")
    out["neutralized_feature_count"] = numeric.isna().sum(axis=1).astype(int)
    missing = frame.reindex(columns=CRITICAL_FIELDS).apply(pd.to_numeric, errors="coerce").isna()
    out["critical_missing_fields"] = missing.apply(
        lambda row: "|".join(column for column, value in row.items() if bool(value)), axis=1
    )
    out["critical_data_complete"] = out["critical_missing_fields"].eq("")
    out["data_complete"] = (
        out["critical_data_complete"] & out["neutralized_feature_count"].eq(0)
    )
    for axis, columns in AXIS_FEATURES.items():
        available = [column for column in columns if column in frame]
        zparts = [robust_z_by_date(frame, column) for column in available]
        out[f"axis_{axis}"] = pd.concat(zparts, axis=1).mean(axis=1, skipna=True) if zparts else np.nan
        out[f"axis_{axis}_coverage"] = (
            frame.reindex(columns=available).apply(pd.to_numeric, errors="coerce").notna().mean(axis=1)
            if available else 0.0
        )
    out["estimate_guidance_history_scope"] = "PIT_FEATURES_ONLY_FORWARD_SNAPSHOTS_EXCLUDED"
    out["used_forward_return_for_selection"] = False
    return out


def prediction_head_audit(current: pd.DataFrame, reference: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    collisions = sorted(
        column for column in current.columns
        if str(column).startswith("pred_") and re.search(r"(_x|_y|\.1)$", str(column))
    )
    rows: list[dict[str, Any]] = []
    for head in ACTIVE_HEADS:
        values = pd.to_numeric(current.get(head), errors="coerce")
        finite_values = values[np.isfinite(values)]
        row: dict[str, Any] = {
            "prediction_head": head,
            "row_count": int(len(current)),
            "finite_count": int(len(finite_values)),
            "coverage": float(len(finite_values) / len(current)) if len(current) else 0.0,
            "nonzero_count": int(finite_values.abs().gt(1e-12).sum()),
            "unique_count": int(finite_values.nunique()),
            "mean": float(finite_values.mean()) if len(finite_values) else None,
            "standard_deviation": float(finite_values.std(ddof=0)) if len(finite_values) else None,
        }
        row["finite_nonzero_nonconstant_pass"] = bool(
            len(finite_values) == len(current)
            and row["nonzero_count"] > 0
            and row["unique_count"] > 1
            and finite(row["standard_deviation"], 0.0) > 1e-12
        )
        if head in reference.columns:
            lhs = current[["ticker", head]].copy()
            rhs = reference[["ticker", head]].copy()
            lhs["ticker"] = lhs["ticker"].map(clean_ticker)
            rhs["ticker"] = rhs["ticker"].map(clean_ticker)
            joined = lhs.merge(rhs, on="ticker", suffixes=("_current", "_reference"))
            a = pd.to_numeric(joined[f"{head}_current"], errors="coerce")
            b = pd.to_numeric(joined[f"{head}_reference"], errors="coerce")
            row["reference_common_ticker_count"] = int(len(joined))
            ref_std = float(b.std(ddof=0)) if len(joined) else 0.0
            reference_active = bool(
                len(joined) > 2 and b.notna().all()
                and b.nunique() > 1 and ref_std > 1e-12
            )
            row["reference_status"] = "ACTIVE" if reference_active else "INACTIVE_CONSTANT_REFERENCE"
            row["reference_spearman"] = float(a.rank().corr(b.rank())) if reference_active else None
            row["standardized_mean_drift"] = float(abs(a.mean() - b.mean()) / ref_std) if reference_active else None
        else:
            row["reference_common_ticker_count"] = 0
            row["reference_status"] = "MISSING_HEAD_IN_REFERENCE"
            row["reference_spearman"] = None
            row["standardized_mean_drift"] = None
        rows.append(row)
    audit = pd.DataFrame(rows)
    summary = {
        "active_head_count": int(audit["finite_nonzero_nonconstant_pass"].sum()),
        "required_head_count": len(ACTIVE_HEADS),
        "all_heads_pass": bool(audit["finite_nonzero_nonconstant_pass"].all()),
        "stale_suffix_collision_columns": collisions,
        "stale_suffix_collision_count": len(collisions),
        "silent_zero_fallback_detected": bool(audit["nonzero_count"].eq(0).any()),
        "distribution_drift_status": (
            "READY" if audit["reference_status"].eq("ACTIVE").all()
            else "UNDERPOWERED_NO_PRIOR_ACTIVE_SIX_HEAD_SNAPSHOT"
        ),
        "active_reference_head_count": int(audit["reference_status"].eq("ACTIVE").sum()),
    }
    return audit, summary


def rank_stability(frame: pd.DataFrame) -> pd.DataFrame:
    ranked: dict[pd.Timestamp, pd.DataFrame] = {}
    for day, group in frame.groupby("rebalance_date", sort=True):
        item = group[["ticker", "alphaops_vnext_score"]].copy()
        item["rank"] = pd.to_numeric(item["alphaops_vnext_score"], errors="coerce").rank(
            method="first", ascending=False
        )
        ranked[pd.Timestamp(day)] = item
    rows: list[dict[str, Any]] = []
    days = sorted(ranked)
    for previous, current in zip(days, days[1:]):
        lhs, rhs = ranked[previous], ranked[current]
        joined = lhs.merge(rhs, on="ticker", suffixes=("_previous", "_current"))
        record = {
            "previous_date": previous.date().isoformat(),
            "current_date": current.date().isoformat(),
            "common_ticker_count": int(len(joined)),
            "score_spearman": float(joined["alphaops_vnext_score_previous"].rank().corr(joined["alphaops_vnext_score_current"].rank())) if len(joined) > 2 else None,
            "rank_spearman": float(joined["rank_previous"].corr(joined["rank_current"])) if len(joined) > 2 else None,
        }
        for topk in (10, 30):
            prior_set = set(lhs.nsmallest(topk, "rank")["ticker"])
            current_set = set(rhs.nsmallest(topk, "rank")["ticker"])
            overlap = len(prior_set & current_set) / max(topk, 1)
            record[f"top_{topk}_overlap"] = overlap
            record[f"top_{topk}_turnover"] = 1.0 - overlap
        rows.append(record)
    return pd.DataFrame(rows)


def forward_return_table(frame: pd.DataFrame, price_cache: Path) -> pd.DataFrame:
    dates = sorted(pd.to_datetime(frame["rebalance_date"], errors="coerce").dropna().unique())
    benchmarks: dict[str, dict[pd.Timestamp, float | None]] = {}
    for benchmark in ("SPY", "QQQ"):
        px = load_price_series(price_cache, benchmark)
        benchmarks[benchmark] = {}
        for raw_day in dates:
            day = pd.Timestamp(raw_day)
            idx = pd.DatetimeIndex(px.index)
            start = int(idx.searchsorted(day + pd.Timedelta(days=1), side="left")) if len(idx) else 0
            for horizon in HORIZONS:
                key = pd.Timestamp(day), horizon
                end = start + horizon
                value = None
                if start < len(idx) and end < len(idx):
                    p0, p1 = finite(px["close"].iloc[start]), finite(px["close"].iloc[end])
                    if p0 > 0 and p1 > 0:
                        value = p1 / p0 - 1.0
                benchmarks[benchmark][key] = value
    rows: list[dict[str, Any]] = []
    for ticker, group in frame.groupby("ticker", sort=True):
        px = load_price_series(price_cache, ticker)
        idx = pd.DatetimeIndex(px.index)
        for row in group.itertuples(index=False):
            day = pd.Timestamp(row.rebalance_date)
            start = int(idx.searchsorted(day + pd.Timedelta(days=1), side="left")) if len(idx) else 0
            record = {
                "rebalance_date": day.date().isoformat(),
                "ticker": ticker,
                "sector": str(getattr(row, "sector", "") or ""),
            }
            for horizon in HORIZONS:
                end = start + horizon
                value = math.nan
                if start < len(idx) and end < len(idx):
                    p0, p1 = finite(px["close"].iloc[start]), finite(px["close"].iloc[end])
                    if p0 > 0 and p1 > 0:
                        value = p1 / p0 - 1.0
                record[f"return_{horizon}d"] = value
                spy = benchmarks["SPY"].get((day, horizon))
                qqq = benchmarks["QQQ"].get((day, horizon))
                record[f"spy_excess_{horizon}d"] = value - spy if math.isfinite(value) and spy is not None else math.nan
                record[f"qqq_excess_{horizon}d"] = value - qqq if math.isfinite(value) and qqq is not None else math.nan
            rows.append(record)
    out = pd.DataFrame(rows)
    out["rebalance_date"] = pd.to_datetime(out["rebalance_date"], errors="coerce").dt.normalize()
    for horizon in HORIZONS:
        sector_mean = out.groupby(["rebalance_date", "sector"])[f"return_{horizon}d"].transform("mean")
        out[f"sector_neutral_excess_{horizon}d"] = out[f"return_{horizon}d"] - sector_mean
    return out


def normalize_book(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, low_memory=False)
    frame["rebalance_date"] = pd.to_datetime(frame["rebalance_date"], errors="coerce").dt.normalize()
    frame["ticker"] = frame["ticker"].map(clean_ticker)
    return frame[~frame["ticker"].isin(CASH_TICKERS)].drop_duplicates(["rebalance_date", "ticker"])


def selected_and_rank_matched(
    candidates: pd.DataFrame,
    books: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for portfolio, book in books.items():
        for day, selected_rows in book.groupby("rebalance_date", sort=True):
            universe = candidates[candidates["rebalance_date"].eq(day)].copy()
            if universe.empty:
                continue
            universe["score_rank"] = pd.to_numeric(
                universe["alphaops_vnext_score"], errors="coerce"
            ).rank(method="first", ascending=False)
            selected_set = set(selected_rows["ticker"]) & set(universe["ticker"])
            pool = universe[~universe["ticker"].isin(selected_set)].sort_values(["score_rank", "ticker"])
            used: set[str] = set()
            for ticker in sorted(selected_set):
                selected = universe[universe["ticker"].eq(ticker)].iloc[0]
                available = pool[~pool["ticker"].isin(used)].copy()
                if available.empty:
                    continue
                available["rank_distance"] = (available["score_rank"] - selected["score_rank"]).abs()
                control = available.sort_values(["rank_distance", "score_rank", "ticker"]).iloc[0]
                used.add(str(control["ticker"]))
                for cohort, row in (("selected", selected), ("rank_matched_control", control)):
                    rows.append({
                        "portfolio": portfolio,
                        "rebalance_date": pd.Timestamp(day),
                        "cohort": cohort,
                        "ticker": str(row["ticker"]),
                        "sector": str(row.get("sector") or ""),
                        "score_rank": float(row["score_rank"]),
                        "matched_pair": ticker,
                    })
    return pd.DataFrame(rows)


def cohort_metrics(labeled: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    group_columns = [column for column in ("portfolio", "cohort") if column in labeled]
    if not group_columns:
        return pd.DataFrame()
    for keys, group in labeled.groupby(group_columns, dropna=False):
        keys = keys if isinstance(keys, tuple) else (keys,)
        base = dict(zip(group_columns, keys))
        for horizon in HORIZONS:
            returns = pd.to_numeric(group[f"return_{horizon}d"], errors="coerce")
            row = {
                **base,
                "horizon_sessions": horizon,
                "resolved_count": int(returns.notna().sum()),
                "mean_return": float(returns.mean()) if returns.notna().any() else None,
                "median_return": float(returns.median()) if returns.notna().any() else None,
            }
            for benchmark in ("spy", "qqq", "sector_neutral"):
                values = pd.to_numeric(group[f"{benchmark}_excess_{horizon}d"], errors="coerce")
                row[f"mean_{benchmark}_excess"] = float(values.mean()) if values.notna().any() else None
            rows.append(row)
    return pd.DataFrame(rows)


def windowed_cohort_metrics(labeled: pd.DataFrame) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for window_name, start in OOS_WINDOWS.items():
        subset = labeled[
            pd.to_datetime(labeled["rebalance_date"], errors="coerce").ge(pd.Timestamp(start))
        ].copy()
        metrics = cohort_metrics(subset)
        if not metrics.empty:
            metrics.insert(0, "window", window_name)
            frames.append(metrics)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def map_rejection_reason(reason: Any) -> str:
    text = str(reason or "").strip().lower()
    if not text:
        return "NAME_OR_SECTOR_CAPACITY"
    if "missing" in text or "not_in_current" in text or "data" in text:
        return "DATA_INCOMPLETENESS"
    if "crisis" in text or "risk" in text or "cash" in text:
        return "RISK_STATE_OR_CASH"
    if "trend" in text or "price" in text or "relative" in text or "ma200" in text:
        return "TREND_OR_RS_FAILURE"
    if "cap" in text or "replace" in text or "threshold_not_met" in text:
        return "NAME_OR_SECTOR_CAPACITY"
    if "valuation" in text or "thesis" in text or "hard_reject" in text or "stale" in text:
        return "VALUATION_OR_THESIS_FAILURE"
    return "CANDIDATE_GATE"


def rejection_outcomes(
    rejections: pd.DataFrame,
    labels: pd.DataFrame,
    *,
    variants: dict[str, str],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows: list[pd.DataFrame] = []
    for portfolio, variant in variants.items():
        subset = rejections[rejections["variant_id"].astype(str).eq(variant)].copy()
        subset["portfolio"] = portfolio
        rows.append(subset)
    out = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()
    out["rebalance_date"] = pd.to_datetime(out["rebalance_date"], errors="coerce").dt.normalize()
    out["ticker"] = out["ticker"].map(clean_ticker)
    out["rejection_taxonomy"] = out["rejection_reason"].map(map_rejection_reason)
    out = out.merge(labels, on=["rebalance_date", "ticker"], how="left")
    metrics = []
    for (portfolio, taxonomy), group in out.groupby(["portfolio", "rejection_taxonomy"]):
        for horizon in HORIZONS:
            values = pd.to_numeric(group[f"return_{horizon}d"], errors="coerce")
            metrics.append({
                "portfolio": portfolio,
                "rejection_taxonomy": taxonomy,
                "horizon_sessions": horizon,
                "event_count": int(len(group)),
                "resolved_count": int(values.notna().sum()),
                "mean_return": float(values.mean()) if values.notna().any() else None,
                "median_return": float(values.median()) if values.notna().any() else None,
            })
    return out, pd.DataFrame(metrics)


def ic_metrics(candidates: pd.DataFrame, labels: pd.DataFrame) -> pd.DataFrame:
    merged = candidates[["rebalance_date", "ticker", "alphaops_vnext_score"]].merge(
        labels, on=["rebalance_date", "ticker"], how="left"
    )
    rows: list[dict[str, Any]] = []
    for window, start in OOS_WINDOWS.items():
        subset = merged[merged["rebalance_date"].ge(pd.Timestamp(start))]
        for horizon in HORIZONS:
            daily_ic: list[float] = []
            daily_hit: list[float] = []
            for _, group in subset.groupby("rebalance_date"):
                x = pd.to_numeric(group["alphaops_vnext_score"], errors="coerce")
                y = pd.to_numeric(group[f"return_{horizon}d"], errors="coerce")
                valid = x.notna() & y.notna()
                if valid.sum() < 20:
                    continue
                correlation = x[valid].rank().corr(y[valid].rank())
                if pd.notna(correlation):
                    daily_ic.append(float(correlation))
                    top = y[valid][x[valid].rank(pct=True).ge(0.8)]
                    daily_hit.append(float(top.mean() > y[valid].median()))
            rows.append({
                "window": window,
                "horizon_sessions": horizon,
                "decision_count": len(daily_ic),
                "mean_spearman_ic": float(np.mean(daily_ic)) if daily_ic else None,
                "positive_ic_hit_rate": float(np.mean(np.asarray(daily_ic) > 0)) if daily_ic else None,
                "top_quintile_hit_rate": float(np.mean(daily_hit)) if daily_hit else None,
            })
    return pd.DataFrame(rows)


def completeness_metrics(decomposition: pd.DataFrame, labels: pd.DataFrame) -> pd.DataFrame:
    merged = decomposition[["rebalance_date", "ticker", "data_complete", "neutralized_feature_count"]].merge(
        labels, on=["rebalance_date", "ticker"], how="left"
    )
    merged["cohort"] = np.where(merged["data_complete"], "data_complete", "neutralized")
    return windowed_cohort_metrics(merged)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-artifact", required=True)
    parser.add_argument("--scored-candidate-cache", required=True)
    parser.add_argument("--main-target-book", required=True)
    parser.add_argument("--concentrated-target-book", required=True)
    parser.add_argument("--rejections", required=True)
    parser.add_argument("--current-score-stack", required=True)
    parser.add_argument("--reference-score-stack", required=True)
    parser.add_argument("--price-cache", required=True)
    parser.add_argument("--output-dir", required=True)
    return parser.parse_args()


def run(args: argparse.Namespace) -> dict[str, Any]:
    inputs = {
        name: repo_path(value) for name, value in {
            "candidate_artifact": args.candidate_artifact,
            "scored_candidate_cache": args.scored_candidate_cache,
            "main_target_book": args.main_target_book,
            "concentrated_target_book": args.concentrated_target_book,
            "rejections": args.rejections,
            "current_score_stack": args.current_score_stack,
            "reference_score_stack": args.reference_score_stack,
        }.items()
    }
    if any(not path.is_file() for path in inputs.values()):
        missing = [name for name, path in inputs.items() if not path.is_file()]
        raise FileNotFoundError("missing inputs:" + ",".join(missing))
    price_cache = repo_path(args.price_cache)
    output_dir = repo_path(args.output_dir)
    if output_dir.exists():
        raise FileExistsError(f"append-only output exists:{output_dir}")
    output_dir.mkdir(parents=True)

    raw_artifact = pd.read_csv(inputs["candidate_artifact"], low_memory=False)
    repaired_artifact, artifact_repair = repair_sector_rs(raw_artifact)
    repaired_artifact_path = output_dir / "candidate_artifact_sector_rs_repaired.csv"
    write_csv(repaired_artifact_path, repaired_artifact)

    scored_raw = pd.read_csv(inputs["scored_candidate_cache"], low_memory=False)
    scored, candidate_contract = normalize_candidates(scored_raw)
    scored, scored_repair = repair_sector_rs(scored)
    decomposition = candidate_decomposition(scored)
    forbidden_decision_columns = [
        column for column in decomposition.columns
        if str(column).lower() in {"period_forward_return", "forward_return"}
        or str(column).lower().startswith("return_fwd_")
    ]
    if forbidden_decision_columns:
        raise ValueError("forward label entered decision decomposition")

    current = pd.read_csv(inputs["current_score_stack"], low_memory=False)
    reference = pd.read_csv(inputs["reference_score_stack"], low_memory=False)
    head_rows, head_summary = prediction_head_audit(current, reference)
    if not head_summary["all_heads_pass"] or head_summary["stale_suffix_collision_count"]:
        raise ValueError("prediction head integrity failed")

    stability = rank_stability(scored)
    labels = forward_return_table(scored, price_cache)
    books = {
        "main": normalize_book(inputs["main_target_book"]),
        "concentrated": normalize_book(inputs["concentrated_target_book"]),
    }
    selected_pairs = selected_and_rank_matched(scored, books)
    selected_labeled = selected_pairs.merge(
        labels, on=["rebalance_date", "ticker", "sector"], how="left"
    )
    selection_metrics = windowed_cohort_metrics(selected_labeled)
    rejections = pd.read_csv(inputs["rejections"], low_memory=False)
    rejection_rows, rejection_metrics = rejection_outcomes(
        rejections,
        labels,
        variants={
            "main": "alphaops_vnext_main_N15",
            "concentrated": "alphaops_vnext_concentrated_N5",
        },
    )
    ic = ic_metrics(scored, labels)
    completeness = completeness_metrics(decomposition, labels)

    sector_etf_status = "BLOCKED_MISSING_PINNED_SECTOR_ETF_CACHE"
    output_frames = {
        "candidate_selection_decomposition": decomposition,
        "prediction_head_activity_and_drift": head_rows,
        "rank_stability": stability,
        "forward_outcomes_measurement_only": labels,
        "selected_vs_rank_matched_rows": selected_labeled,
        "selected_vs_rank_matched_metrics": selection_metrics,
        "rejection_reason_rows": rejection_rows,
        "rejection_reason_outcomes": rejection_metrics,
        "oos_ic_hit_rate": ic,
        "data_completeness_outcomes": completeness,
    }
    output_records: dict[str, Any] = {}
    for name, frame in output_frames.items():
        path = output_dir / f"{name}.csv"
        write_csv(path, frame)
        output_records[name] = {
            "path": str(path), "sha256": file_sha256(path), "row_count": int(len(frame))
        }

    selected_metric_pivot = selection_metrics.pivot_table(
        index=["window", "portfolio", "horizon_sessions"], columns="cohort", values="mean_return"
    ).reset_index() if not selection_metrics.empty else pd.DataFrame()
    if not selected_metric_pivot.empty and {"selected", "rank_matched_control"}.issubset(selected_metric_pivot):
        selected_metric_pivot["selected_minus_control"] = (
            selected_metric_pivot["selected"] - selected_metric_pivot["rank_matched_control"]
        )
    payload = {
        "schema_version": SCHEMA_VERSION,
        "status": "READY_P6_DIAGNOSTIC",
        "input_hashes": {name: file_sha256(path) for name, path in inputs.items()},
        "candidate_contract": candidate_contract,
        "sector_rs_repair": {"artifact": artifact_repair, "scored_cache": scored_repair},
        "prediction_heads": head_summary,
        "rank_stability": {
            "pair_count": int(len(stability)),
            "mean_score_spearman": float(pd.to_numeric(stability.get("score_spearman"), errors="coerce").mean()),
            "mean_top_10_overlap": float(pd.to_numeric(stability.get("top_10_overlap"), errors="coerce").mean()),
            "mean_top_30_overlap": float(pd.to_numeric(stability.get("top_30_overlap"), errors="coerce").mean()),
        },
        "selection_quality_delta": selected_metric_pivot.to_dict("records"),
        "sector_etf_excess_status": sector_etf_status,
        "sector_neutral_excess_computed": True,
        "rejection_taxonomy": list(REJECTION_TAXONOMY),
        "future_return_columns_physically_excluded_from_decision_decomposition": True,
        "used_forward_return_for_selection": False,
        "single_remediation": "canonical_rs_sector_3m_materialization",
        "gate_relaxation_count": 0,
        "threshold_grid_executed": False,
        "repaired_candidate_artifact": {
            "path": str(repaired_artifact_path),
            "sha256": file_sha256(repaired_artifact_path),
            "row_count": int(len(repaired_artifact)),
        },
        "outputs": output_records,
        "fullrun_executed": False,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
        "pit_universe_label_clean": False,
    }
    write_json(output_dir / "summary.json", payload)
    return payload


def main() -> int:
    payload = run(parse_args())
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
