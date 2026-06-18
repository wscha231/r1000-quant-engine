#!/usr/bin/env python3
"""Measure whether headline/OOS CAGR is inflated versus rolling yearly CAGR.

This is a measurement-only audit. It reads broker-ledger replay outputs and
writes summaries under outputs/cagr_walkforward; it does not mutate target
books, strategy settings, cash policy, or production gates.
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
SCHEMA_VERSION = "cagr-walkforward-v1"
WINDOW_YEARS = (2023, 2024, 2025, 2026)
VERDICT_INSUFFICIENT = "insufficient_data"
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


def extract_single_oos_cagr(metrics: dict[str, Any], fallback: float | None) -> float | None:
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
    return fallback


def equity_endpoint(frame: pd.DataFrame, year: int, *, start: bool) -> tuple[pd.Timestamp | None, float | None]:
    if frame.empty or "date" not in frame.columns or "equity" not in frame.columns:
        return None, None
    window = frame.loc[frame["date"].dt.year.eq(year)]
    if window.empty:
        return None, None
    row = window.iloc[0 if start else -1]
    return pd.Timestamp(first_present(row, ("date",))), safe_float(first_present(row, ("equity",)))


def yearly_window(frame: pd.DataFrame, year: int) -> dict[str, Any]:
    start_date, start_equity = equity_endpoint(frame, year, start=True)
    end_date, end_equity = equity_endpoint(frame, year, start=False)
    base = {
        "year": int(year),
        "start_date": None if start_date is None else start_date.date().isoformat(),
        "end_date": None if end_date is None else end_date.date().isoformat(),
        "days": None,
        "years": None,
        "start_equity": start_equity,
        "end_equity": end_equity,
        "cagr": None,
        "status": VERDICT_INSUFFICIENT,
        "partial": bool(year == 2026),
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
            "cagr": cagr,
            "status": "completed" if cagr is not None else VERDICT_INSUFFICIENT,
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


def classify_verdict(single_oos_cagr: float | None, walk_forward_avg: float | None) -> tuple[str, float | None]:
    if single_oos_cagr is None or walk_forward_avg is None or walk_forward_avg <= 0.0:
        return VERDICT_INSUFFICIENT, None
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


def portfolio_summary(run_root: Path, portfolio: str) -> dict[str, Any]:
    metrics_path = run_root / "broker_replay" / portfolio / "metrics.json"
    curve_path = run_root / "broker_replay" / portfolio / "equity_curve.csv"
    metrics = read_json(metrics_path)
    curve = read_equity_curve(curve_path)

    windows = [yearly_window(curve, year) for year in WINDOW_YEARS]
    valid_cagrs = [safe_float(row.get("cagr")) for row in windows]
    valid_cagrs = [value for value in valid_cagrs if value is not None]

    walk_avg = arithmetic_mean(valid_cagrs)
    walk_geo = geometric_mean(valid_cagrs)
    single_oos = extract_single_oos_cagr(metrics, fallback=valid_cagrs[-1] if valid_cagrs else None)
    verdict, inflation = classify_verdict(single_oos, walk_avg)
    full_cagr = safe_float(metrics.get("cagr"), default=full_cagr_from_curve(curve))

    return {
        "schema_version": SCHEMA_VERSION,
        "portfolio": portfolio,
        "metric_mode": metric_mode(metrics),
        "run_root": str(run_root),
        "metrics_path": str(metrics_path),
        "equity_curve_path": str(curve_path),
        "full_cagr": full_cagr,
        "single_oos_cagr": single_oos,
        "walk_forward_cagr_avg": walk_avg,
        "walk_forward_cagr_geomean": walk_geo,
        "inflation_indicator": inflation,
        "window_count": len(windows),
        "completed_window_count": len(valid_cagrs),
        "windows": windows,
        "verdict": verdict,
    }


def report_line(summary: dict[str, Any]) -> str:
    def pct(value: Any) -> str:
        parsed = safe_float(value)
        return "n/a" if parsed is None else f"{parsed * 100:.2f}%"

    inflation = safe_float(summary.get("inflation_indicator"))
    inflation_text = "n/a" if inflation is None else f"{inflation:.2f}x"
    return (
        f"| {summary['portfolio']} | {pct(summary.get('full_cagr'))} | "
        f"{pct(summary.get('single_oos_cagr'))} | {pct(summary.get('walk_forward_cagr_avg'))} | "
        f"{inflation_text} | {summary.get('verdict')} |"
    )


def write_report(path: Path, summaries: dict[str, dict[str, Any]]) -> None:
    lines = [
        "# CAGR Walk-Forward Credibility",
        "",
        "Measurement-only audit of broker-ledger CAGR stability across 2023, 2024, 2025, and 2026 partial windows.",
        "",
        "| Portfolio | Full CAGR | Single OOS CAGR | Walk-forward avg | Inflation | Verdict |",
        "| --- | ---: | ---: | ---: | ---: | --- |",
    ]
    lines.extend(report_line(summaries[portfolio]) for portfolio in PORTFOLIOS)
    lines.extend(
        [
            "",
            "Inputs are broker_replay/<portfolio>/equity_curve.csv and metrics.json.",
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
