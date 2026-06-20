#!/usr/bin/env python3
"""Measure rolling calendar-year CAGR credibility for broker-ledger replays.

This is a measurement-only audit. It reads the existing broker-ledger replay
equity curve and re-segments that same trained run into calendar-year windows.
It is NOT walk-forward retrain CAGR; no model is re-trained per window.

The sidecar writes summaries under outputs/cagr_walkforward; it does not mutate
target books, strategy settings, cash policy, promotion state, or live trading.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from r1000_helpers import compute_cagr_safe

DEFAULT_OUTPUT_DIR = "outputs/cagr_walkforward"
PORTFOLIOS = ("main", "concentrated")
SCHEMA_VERSION = "cagr-walkforward-v4"
FULL_YEAR_MIN_YEARS = 0.95
VERDICT_INSUFFICIENT = "insufficient_data"
VERDICT_SINGLE_OOS_UNAVAILABLE = "single_oos_unavailable"
VERDICT_CONSISTENT = "single_oos_consistent_with_rolling_avg"
VERDICT_MODERATE = "single_oos_moderately_above_rolling_avg"
VERDICT_INFLATED = "single_oos_inflated_vs_rolling_avg"


def repo_path(path_like: str | Path) -> Path:
    path = Path(path_like)
    return path if path.is_absolute() else REPO_ROOT / path


def resolve_run_root(path: Path) -> Path:
    """Accept either artifact root or artifact_root/outputs."""
    if (path / "broker_replay").exists() or (path / "account_evaluation").exists():
        return path
    if (path / "outputs" / "broker_replay").exists() or (path / "outputs" / "account_evaluation").exists():
        return path / "outputs"
    return path


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None or value == "":
            return default
        out = float(value)
        if not math.isfinite(out):
            return default
        return out
    except (TypeError, ValueError):
        return default


def first_present(row: pd.Series, candidates: tuple[str, ...]) -> Any:
    for name in candidates:
        if name in row.index:
            return row[name]
    return None


def read_equity_curve(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=["date", "equity"])
    try:
        raw = pd.read_csv(path, low_memory=False)
    except Exception:
        return pd.DataFrame(columns=["date", "equity"])
    if raw.empty:
        return pd.DataFrame(columns=["date", "equity"])

    lower_to_original = {str(col).strip().lower(): col for col in raw.columns}
    date_col = next((lower_to_original[col] for col in ("date", "as_of_date", "timestamp") if col in lower_to_original), None)
    equity_col = next(
        (
            lower_to_original[col]
            for col in ("equity", "equity_usd", "account_value", "portfolio_value", "value")
            if col in lower_to_original
        ),
        None,
    )
    if date_col is None or equity_col is None:
        return pd.DataFrame(columns=["date", "equity"])

    out = pd.DataFrame(
        {
            "date": pd.to_datetime(raw[date_col], errors="coerce").dt.normalize(),
            "equity": pd.to_numeric(raw[equity_col], errors="coerce"),
        }
    )
    out = out.dropna(subset=["date", "equity"]).sort_values("date").drop_duplicates("date", keep="last")
    return out.reset_index(drop=True)


def nested_get(mapping: dict[str, Any], path: tuple[str, ...]) -> Any:
    cur: Any = mapping
    for key in path:
        if not isinstance(cur, dict) or key not in cur:
            return None
        cur = cur[key]
    return cur


def metric_mode(metrics: dict[str, Any]) -> str:
    return str(metrics.get("metric_mode") or metrics.get("official_metric_mode") or "broker_ledger_next_close")


def extract_single_oos_cagr(metrics: dict[str, Any]) -> float | None:
    """Return a metrics-reported single-window OOS CAGR, or None if absent."""
    direct_candidates = (
        metrics.get("single_oos_cagr"),
        metrics.get("oos_cagr"),
        metrics.get("oos_broker_cagr"),
        nested_get(metrics, ("windows", "oos", "cagr")),
        nested_get(metrics, ("windows", "OOS", "cagr")),
        nested_get(metrics, ("window_metrics", "oos", "cagr")),
        nested_get(metrics, ("is_oos", "oos_cagr")),
    )
    for value in direct_candidates:
        parsed = safe_float(value)
        if parsed is not None:
            return parsed
    return None


def equity_endpoint(frame: pd.DataFrame, year: int, *, start: bool) -> tuple[pd.Timestamp | None, float | None]:
    if frame.empty or "date" not in frame.columns or "equity" not in frame.columns:
        return None, None
    window = frame.loc[frame["date"].dt.year.eq(year)]
    if window.empty:
        return None, None
    row = window.iloc[0 if start else -1]
    return pd.Timestamp(first_present(row, ("date",))), safe_float(first_present(row, ("equity",)))


def max_drawdown(frame: pd.DataFrame) -> float | None:
    if frame.empty or "equity" not in frame.columns:
        return None
    equity = pd.to_numeric(frame["equity"], errors="coerce").dropna()
    if equity.empty:
        return None
    running_peak = equity.cummax()
    drawdowns = equity / running_peak - 1.0
    out = float(drawdowns.min())
    return out if math.isfinite(out) else None


def observed_years(frame: pd.DataFrame) -> list[int]:
    if frame.empty or "date" not in frame.columns:
        return []
    dates = pd.to_datetime(frame["date"], errors="coerce").dropna()
    if dates.empty:
        return []
    return list(range(int(dates.min().year), int(dates.max().year) + 1))


def yearly_window(frame: pd.DataFrame, year: int) -> dict[str, Any]:
    start_date, start_equity = equity_endpoint(frame, year, start=True)
    end_date, end_equity = equity_endpoint(frame, year, start=False)
    window = frame.loc[frame["date"].dt.year.eq(year)] if not frame.empty and "date" in frame.columns else pd.DataFrame()
    base = {
        "year": int(year),
        "start_date": None if start_date is None else start_date.date().isoformat(),
        "end_date": None if end_date is None else end_date.date().isoformat(),
        "days": None,
        "years": None,
        "start_equity": start_equity,
        "end_equity": end_equity,
        "actual_return": None,
        "cagr": None,
        "max_drawdown": max_drawdown(window),
        "status": VERDICT_INSUFFICIENT,
        "partial": True,
        "included_in_average": False,
    }
    if start_date is None or end_date is None or start_equity is None or end_equity is None:
        return base
    days = int((end_date - start_date).days)
    years = days / 365.25 if days > 0 else 0.0
    cagr = compute_cagr_safe(start_equity, end_equity, years)
    base.update(
        {
            "days": days,
            "years": years,
            "actual_return": (end_equity / start_equity - 1.0) if start_equity else None,
            "cagr": cagr,
            "status": "completed" if cagr is not None else VERDICT_INSUFFICIENT,
            "partial": bool(years < FULL_YEAR_MIN_YEARS),
            "included_in_average": bool(years >= FULL_YEAR_MIN_YEARS),
        }
    )
    return base


def arithmetic_mean(values: list[float]) -> float | None:
    return float(sum(values) / len(values)) if values else None


def geometric_mean(values: list[float]) -> float | None:
    if not values or any(value <= -1.0 for value in values):
        return None
    product = 1.0
    for value in values:
        product *= 1.0 + value
    out = product ** (1.0 / len(values)) - 1.0
    return out if math.isfinite(out) else None


def weighted_arithmetic_mean(rows: list[dict[str, Any]]) -> float | None:
    weighted_sum = 0.0
    total_weight = 0.0
    for row in rows:
        cagr = safe_float(row.get("cagr"))
        years = safe_float(row.get("years"))
        if cagr is None or years is None or years <= 0.0:
            continue
        weighted_sum += cagr * years
        total_weight += years
    if total_weight <= 0.0:
        return None
    out = weighted_sum / total_weight
    return out if math.isfinite(out) else None


def weighted_geometric_cagr(rows: list[dict[str, Any]]) -> float | None:
    compounded = 1.0
    total_years = 0.0
    for row in rows:
        actual_return = safe_float(row.get("actual_return"))
        years = safe_float(row.get("years"))
        if actual_return is None or years is None or years <= 0.0:
            continue
        if actual_return <= -1.0:
            return None
        compounded *= 1.0 + actual_return
        total_years += years
    if total_years <= 0.0:
        return None
    out = compounded ** (1.0 / total_years) - 1.0
    return out if math.isfinite(out) else None


def worst_drawdown(values: list[float]) -> float | None:
    cleaned = [value for value in values if math.isfinite(value)]
    return min(cleaned) if cleaned else None


def classify_verdict(single_oos_cagr: float | None, walk_forward_avg: float | None) -> tuple[str, float | None]:
    if walk_forward_avg is None or walk_forward_avg <= 0.0:
        return VERDICT_INSUFFICIENT, None
    if single_oos_cagr is None:
        return VERDICT_SINGLE_OOS_UNAVAILABLE, None
    ratio = single_oos_cagr / walk_forward_avg
    if not math.isfinite(ratio):
        return VERDICT_INSUFFICIENT, None
    if ratio <= 1.25:
        return VERDICT_CONSISTENT, ratio
    if ratio <= 2.0:
        return VERDICT_MODERATE, ratio
    return VERDICT_INFLATED, ratio


def full_cagr_from_curve(frame: pd.DataFrame) -> float | None:
    if len(frame) < 2:
        return None
    first = frame.iloc[0]
    last = frame.iloc[-1]
    start_date = pd.Timestamp(first["date"])
    end_date = pd.Timestamp(last["date"])
    years = int((end_date - start_date).days) / 365.25
    return compute_cagr_safe(first["equity"], last["equity"], years)


def extract_full_max_drawdown(metrics: dict[str, Any], curve: pd.DataFrame) -> float | None:
    for key in ("max_drawdown", "max_dd", "mdd", "max_drawdown_pct"):
        parsed = safe_float(metrics.get(key))
        if parsed is not None:
            return parsed
    return max_drawdown(curve)


def portfolio_summary(run_root: Path, portfolio: str) -> dict[str, Any]:
    metrics_path = run_root / "broker_replay" / portfolio / "metrics.json"
    curve_path = run_root / "broker_replay" / portfolio / "equity_curve.csv"
    metrics = read_json(metrics_path)
    curve = read_equity_curve(curve_path)

    windows = [yearly_window(curve, year) for year in observed_years(curve)]
    full_year_cagrs = [
        safe_float(row.get("cagr"))
        for row in windows
        if row.get("included_in_average") and safe_float(row.get("cagr")) is not None
    ]
    full_year_cagrs = [value for value in full_year_cagrs if value is not None]
    full_year_mdds = [
        safe_float(row.get("max_drawdown"))
        for row in windows
        if row.get("included_in_average") and safe_float(row.get("max_drawdown")) is not None
    ]
    full_year_mdds = [value for value in full_year_mdds if value is not None]
    partial_year_cagrs = [
        {"year": int(row.get("year")), "cagr": safe_float(row.get("cagr"))}
        for row in windows
        if row.get("partial") and safe_float(row.get("cagr")) is not None
    ]
    partial_year_mdds = [
        {"year": int(row.get("year")), "max_drawdown": safe_float(row.get("max_drawdown"))}
        for row in windows
        if row.get("partial") and safe_float(row.get("max_drawdown")) is not None
    ]
    weighted_rows = [
        row
        for row in windows
        if safe_float(row.get("cagr")) is not None
        and safe_float(row.get("years")) is not None
    ]

    walk_avg = arithmetic_mean(full_year_cagrs)
    walk_geo = geometric_mean(full_year_cagrs)
    partial_weighted_avg = weighted_arithmetic_mean(weighted_rows)
    partial_weighted_geo = weighted_geometric_cagr(weighted_rows)
    single_oos = extract_single_oos_cagr(metrics)
    single_oos_source = "metrics" if single_oos is not None else "unavailable"
    verdict, inflation = classify_verdict(single_oos, walk_avg)
    partial_weighted_verdict, partial_weighted_inflation = classify_verdict(single_oos, partial_weighted_avg)
    full_cagr = safe_float(metrics.get("cagr"), default=full_cagr_from_curve(curve))
    full_mdd = extract_full_max_drawdown(metrics, curve)

    return {
        "schema_version": SCHEMA_VERSION,
        "portfolio": portfolio,
        "metric_mode": metric_mode(metrics),
        "run_root": str(run_root),
        "metrics_path": str(metrics_path),
        "equity_curve_path": str(curve_path),
        "full_cagr": full_cagr,
        "full_max_drawdown": full_mdd,
        "single_oos_cagr": single_oos,
        "single_oos_cagr_source": single_oos_source,
        "walk_forward_cagr_avg": walk_avg,
        "walk_forward_cagr_geomean": walk_geo,
        "partial_year_day_weighted_cagr_avg": partial_weighted_avg,
        "partial_year_day_weighted_cagr_geomean": partial_weighted_geo,
        "partial_year_day_weighted_inflation_indicator": partial_weighted_inflation,
        "partial_year_day_weighted_verdict": partial_weighted_verdict,
        "partial_year_day_weighted_note": "Includes completed full-year windows plus partial years weighted by observed years/days; reference only until partial years complete.",
        "worst_full_year_max_drawdown": worst_drawdown(full_year_mdds),
        "partial_year_max_drawdowns_for_reference_only": partial_year_mdds,
        "mdd_note": "MDD is path-based. It is reported for each full/partial window and for the full broker-ledger path; it is not day-weight averaged.",
        "inflation_indicator": inflation,
        "window_count": len(windows),
        "completed_full_year_count": len(full_year_cagrs),
        "completed_partial_year_count": len(partial_year_cagrs),
        "partial_year_cagrs_for_reference_only": partial_year_cagrs,
        "full_years_in_average": [int(row.get("year")) for row in windows if row.get("included_in_average")],
        "partial_years_for_reference_only": [int(row.get("year")) for row in windows if row.get("partial") and safe_float(row.get("cagr")) is not None],
        "windows": windows,
        "verdict": verdict,
    }


def report_line(summary: dict[str, Any]) -> str:
    def pct(value: Any) -> str:
        parsed = safe_float(value)
        return "n/a" if parsed is None else f"{parsed * 100:.2f}%"

    inflation = safe_float(summary.get("inflation_indicator"))
    inflation_text = "n/a" if inflation is None else f"{inflation:.2f}x"
    weighted = safe_float(summary.get("partial_year_day_weighted_cagr_avg"))
    weighted_text = "n/a" if weighted is None else f"{weighted * 100:.2f}%"
    return (
        f"| {summary['portfolio']} | {pct(summary.get('full_cagr'))} | "
        f"{pct(summary.get('full_max_drawdown'))} | "
        f"{pct(summary.get('single_oos_cagr'))} | {pct(summary.get('walk_forward_cagr_avg'))} | "
        f"{pct(summary.get('worst_full_year_max_drawdown'))} | "
        f"{weighted_text} | {inflation_text} | {summary.get('verdict')} |"
    )


def write_report(path: Path, summaries: dict[str, dict[str, Any]]) -> None:
    lines = [
        "# CAGR Walk-Forward Credibility",
        "",
        "Rolling calendar-year CAGR stability over the same trained broker-ledger equity curve.",
        "",
        "| Portfolio | Full CAGR | Full MDD | Single OOS CAGR | Rolling full-year avg | Worst full-year MDD | Day-weighted incl partial | Inflation | Verdict |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    lines.extend(report_line(summaries[portfolio]) for portfolio in PORTFOLIOS)
    lines.extend(
        [
            "",
            "Inputs are broker_replay/<portfolio>/equity_curve.csv and metrics.json.",
            "Rolling windows are derived from the observed broker-ledger equity-curve date range.",
            "The rolling full-year average excludes partial start/end years; the day-weighted reference includes every observed full/partial window by observed years/days.",
            "MDD is path-based, so partial-year MDD is reported per window and full-run MDD remains the broker-ledger path MDD; MDD is not day-weight averaged.",
            "This is NOT walk-forward retrain CAGR; no model is re-trained per window.",
            "This report does not alter selection, scoring, target books, cash policy, or promotion state.",
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def run(latest_run: str | Path, output_dir: str | Path = DEFAULT_OUTPUT_DIR) -> dict[str, Any]:
    run_root = resolve_run_root(repo_path(latest_run))
    out_dir = repo_path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    summaries = {portfolio: portfolio_summary(run_root, portfolio) for portfolio in PORTFOLIOS}
    for portfolio, payload in summaries.items():
        write_json(out_dir / f"{portfolio}_summary.json", payload)
    write_report(out_dir / "report.md", summaries)

    return {
        "schema_version": SCHEMA_VERSION,
        "run_root": str(run_root),
        "output_dir": str(out_dir),
        "summaries": summaries,
        "report_path": str(out_dir / "report.md"),
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default="outputs", help="Artifact root or artifact_root/outputs directory.")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR, help="Directory for walk-forward outputs.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    payload = run(args.latest_run, args.output_dir)
    print(json.dumps({"output_dir": payload["output_dir"], "report_path": payload["report_path"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
