#!/usr/bin/env python3
"""Stress-window attribution for Main MDD repair research.

This is narrower than the broad crash-fragility screen. It asks whether a small
set of PIT-observable predicates explains the actual stress-window losses. The
output is diagnostic only; it must not be used as a live ranking signal.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.run_main_crash_fragility_screen import (  # noqa: E402
    build_feature_rows,
    clean_ticker,
    normalize_crisis_state,
    normalize_target_book,
    price_at_or_after,
    read_csv,
    repo_path,
    safe_float,
    write_json,
)
from tools.run_weekly_evaluation import load_price_series  # noqa: E402

SCHEMA_VERSION = "main-stress-window-attribution-v1"
DEFAULT_STRESS_WINDOWS = "2020-02-19:2020-03-18,2025-02-18:2025-04-04"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def pct(value: Any) -> str:
    try:
        out = float(value)
        return f"{out:.2%}" if math.isfinite(out) else ""
    except (TypeError, ValueError):
        return ""


def parse_windows(raw: str) -> list[dict[str, str]]:
    windows: list[dict[str, str]] = []
    for idx, chunk in enumerate(str(raw or "").split(","), start=1):
        if ":" not in chunk:
            continue
        peak, trough = [part.strip() for part in chunk.split(":", 1)]
        if not peak or not trough:
            continue
        windows.append({"window_id": f"w{idx}", "peak_date": peak, "trough_date": trough})
    return windows


def stress_return_to_trough(price_cache: Path, ticker: str, decision_date: pd.Timestamp, trough_date: pd.Timestamp) -> float:
    px = load_price_series(price_cache, ticker)
    if px.empty:
        return float("nan")
    start_dt, start_px = price_at_or_after(px, decision_date + pd.Timedelta(days=1))
    trough_dt, trough_px = price_at_or_after(px, trough_date)
    if start_px is None or trough_px is None or start_px <= 0:
        return float("nan")
    if start_dt is None or trough_dt is None or pd.Timestamp(start_dt) > pd.Timestamp(trough_dt):
        return float("nan")
    return float(trough_px / start_px - 1.0)


def stress_rows(features: pd.DataFrame, price_cache: Path, windows: list[dict[str, str]], lookback_days: int) -> pd.DataFrame:
    if features.empty:
        return pd.DataFrame()
    d = features.copy()
    d["rebalance_ts"] = pd.to_datetime(d["rebalance_date"], errors="coerce").dt.normalize()
    rows: list[dict[str, Any]] = []
    for window in windows:
        peak = pd.to_datetime(window["peak_date"], errors="coerce")
        trough = pd.to_datetime(window["trough_date"], errors="coerce")
        if pd.isna(peak) or pd.isna(trough):
            continue
        lo = peak - pd.Timedelta(days=lookback_days)
        period = d[(d["rebalance_ts"] >= lo) & (d["rebalance_ts"] <= trough)].copy()
        for rec in period.to_dict(orient="records"):
            ticker = clean_ticker(rec.get("ticker"))
            ret = stress_return_to_trough(price_cache, ticker, pd.Timestamp(rec["rebalance_ts"]), trough)
            target_weight = safe_float(rec.get("target_weight"))
            item = dict(rec)
            item.update(
                {
                    "window_id": window["window_id"],
                    "peak_date": window["peak_date"],
                    "trough_date": window["trough_date"],
                    "stress_return_to_trough": ret,
                    "weighted_stress_loss": target_weight * min(0.0, ret) if math.isfinite(ret) else np.nan,
                    "days_from_rebalance_to_peak": int((peak - pd.Timestamp(rec["rebalance_ts"])).days),
                }
            )
            rows.append(item)
    return pd.DataFrame(rows)


def add_predicates(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    d = frame.copy()
    for col in [
        "trailing_volatility_63d",
        "ma200_distance",
        "ma50_distance",
        "rs_benchmark_3m",
        "cluster_weight",
        "target_weight",
    ]:
        d[col] = pd.to_numeric(d.get(col, np.nan), errors="coerce")
    vol_q = d["trailing_volatility_63d"].quantile(0.80)
    ext_q = d["ma200_distance"].quantile(0.80)
    cluster_q = d["cluster_weight"].quantile(0.80)
    weight_q = d["target_weight"].quantile(0.80)
    d["predicate_vol_top20"] = d["trailing_volatility_63d"] >= vol_q
    d["predicate_extension_top20"] = d["ma200_distance"] >= ext_q
    d["predicate_cluster_top20"] = d["cluster_weight"] >= cluster_q
    d["predicate_weight_top20"] = d["target_weight"] >= weight_q
    d["predicate_rs3m_negative"] = d["rs_benchmark_3m"] < 0
    d["predicate_below_ma200"] = (d["ma200_distance"] < 0) | (pd.to_numeric(d.get("price_above_ma200", np.nan), errors="coerce") <= 0.5)
    d["predicate_weak_market_state"] = d["crisis_state"].astype(str).isin(["WATCH", "DEFENSE_REVIEW", "CRISIS_DEFENSE"])
    d["predicate_high_vol_extension"] = d["predicate_vol_top20"] & d["predicate_extension_top20"]
    d["predicate_cluster_high_vol"] = d["predicate_cluster_top20"] & d["predicate_vol_top20"]
    d["predicate_large_weight_high_vol"] = d["predicate_weight_top20"] & d["predicate_vol_top20"]
    d["predicate_weak_state_high_vol"] = d["predicate_weak_market_state"] & d["predicate_vol_top20"]
    return d


def predicate_report(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()
    d = add_predicates(frame)
    predicate_cols = [col for col in d.columns if col.startswith("predicate_")]
    total_loss = abs(float(pd.to_numeric(d["weighted_stress_loss"], errors="coerce").fillna(0.0).sum()))
    rows: list[dict[str, Any]] = []
    for col in predicate_cols:
        mask = d[col].astype(bool)
        group = d[mask].copy()
        other = d[~mask].copy()
        if group.empty:
            continue
        loss = abs(float(pd.to_numeric(group["weighted_stress_loss"], errors="coerce").fillna(0.0).sum()))
        other_loss = abs(float(pd.to_numeric(other["weighted_stress_loss"], errors="coerce").fillna(0.0).sum())) if not other.empty else 0.0
        rows.append(
            {
                "predicate": col.replace("predicate_", ""),
                "rows": int(len(group)),
                "window_count": int(group["window_id"].nunique()),
                "ticker_count": int(group["ticker"].nunique()),
                "avg_target_weight": float(pd.to_numeric(group["target_weight"], errors="coerce").mean()),
                "avg_stress_return_to_trough": float(pd.to_numeric(group["stress_return_to_trough"], errors="coerce").mean()),
                "avg_weighted_stress_loss": float(pd.to_numeric(group["weighted_stress_loss"], errors="coerce").mean()),
                "loss_share": float(loss / total_loss) if total_loss > 0 else 0.0,
                "other_avg_stress_return_to_trough": float(pd.to_numeric(other["stress_return_to_trough"], errors="coerce").mean()) if not other.empty else np.nan,
                "other_loss_share": float(other_loss / total_loss) if total_loss > 0 else 0.0,
            }
        )
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    return out.sort_values(["loss_share", "avg_weighted_stress_loss"], ascending=[False, True]).reset_index(drop=True)


def verdict(report: pd.DataFrame, stress: pd.DataFrame, min_windows: int) -> dict[str, Any]:
    if report.empty or stress.empty:
        return {"screen_pass": False, "verdict": "blocked_empty_stress_attribution"}
    candidates = report[
        (pd.to_numeric(report["window_count"], errors="coerce") >= min_windows)
        & (pd.to_numeric(report["rows"], errors="coerce") >= 10)
        & (pd.to_numeric(report["loss_share"], errors="coerce") >= 0.30)
        & (pd.to_numeric(report["avg_stress_return_to_trough"], errors="coerce") <= -0.08)
    ].copy()
    if candidates.empty:
        return {
            "screen_pass": False,
            "verdict": "screen_reject_no_recurring_stress_predicate",
            "top_predicate": str(report.iloc[0].get("predicate")),
            "top_predicate_loss_share": safe_float(report.iloc[0].get("loss_share")),
        }
    top = candidates.iloc[0].to_dict()
    return {
        "screen_pass": True,
        "verdict": "screen_pass_design_default_off_stress_hook",
        "top_predicate": str(top.get("predicate")),
        "top_predicate_loss_share": safe_float(top.get("loss_share")),
        "top_predicate_rows": int(top.get("rows") or 0),
        "top_predicate_window_count": int(top.get("window_count") or 0),
    }


def render_report(summary: dict[str, Any], report: pd.DataFrame) -> str:
    lines = [
        "# Main Stress Window Attribution",
        "",
        f"- verdict: `{summary.get('verdict')}`",
        f"- screen_pass: `{summary.get('screen_pass')}`",
        f"- stress rows: `{summary.get('stress_rows')}`",
        f"- window count: `{summary.get('window_count')}`",
        "",
        "## Predicate Report",
        "",
        "| predicate | rows | windows | tickers | avg stress return | loss share | other avg stress return |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in report.head(20).to_dict(orient="records"):
        lines.append(
            "| {predicate} | {rows} | {window_count} | {ticker_count} | {ret} | {loss} | {other} |".format(
                predicate=row.get("predicate"),
                rows=int(row.get("rows") or 0),
                window_count=int(row.get("window_count") or 0),
                ticker_count=int(row.get("ticker_count") or 0),
                ret=pct(row.get("avg_stress_return_to_trough")),
                loss=pct(row.get("loss_share")),
                other=pct(row.get("other_avg_stress_return_to_trough")),
            )
        )
    lines.extend(
        [
            "",
            "Forward stress-window returns are audit labels only. No production policy",
            "or live ranking signal is created by this report.",
            "",
        ]
    )
    return "\n".join(lines)


def run(
    *,
    target_book: Path,
    price_cache: Path,
    crisis_state: Path,
    output_dir: Path,
    stress_windows: str = DEFAULT_STRESS_WINDOWS,
    lookback_days: int = 45,
    min_windows: int = 2,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    targets = normalize_target_book(read_csv(target_book))
    crisis = normalize_crisis_state(read_csv(crisis_state))
    features = build_feature_rows(targets, price_cache, crisis)
    windows = parse_windows(stress_windows)
    stress = stress_rows(features, price_cache, windows, lookback_days)
    stress = add_predicates(stress)
    report = predicate_report(stress)
    result = verdict(report, stress, min_windows=min_windows)
    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_now(),
        "research_only": True,
        "production_activation_allowed": False,
        "target_book": str(target_book),
        "price_cache": str(price_cache),
        "crisis_state": str(crisis_state),
        "stress_windows": windows,
        "lookback_days": int(lookback_days),
        "min_windows": int(min_windows),
        "feature_rows": int(len(features)),
        "stress_rows": int(len(stress)),
        "window_count": int(stress["window_id"].nunique()) if not stress.empty else 0,
        "ticker_count": int(stress["ticker"].nunique()) if not stress.empty else 0,
        **result,
    }
    stress.to_csv(output_dir / "stress_window_rows.csv", index=False)
    report.to_csv(output_dir / "predicate_report.csv", index=False)
    write_json(output_dir / "summary.json", summary)
    (output_dir / "report.md").write_text(render_report(summary, report), encoding="utf-8")
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-book", default="outputs/alphaops_vnext/official_main_target_book.csv")
    parser.add_argument("--price-cache", default="cache_prices")
    parser.add_argument("--crisis-state", default="outputs/alphaops_vnext/daily_crisis_state.csv")
    parser.add_argument("--output-dir", default="outputs/main_stress_window_attribution")
    parser.add_argument("--stress-windows", default=DEFAULT_STRESS_WINDOWS)
    parser.add_argument("--lookback-days", type=int, default=45)
    parser.add_argument("--min-windows", type=int, default=2)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = run(
        target_book=repo_path(args.target_book),
        price_cache=repo_path(args.price_cache),
        crisis_state=repo_path(args.crisis_state),
        output_dir=repo_path(args.output_dir),
        stress_windows=args.stress_windows,
        lookback_days=args.lookback_days,
        min_windows=args.min_windows,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
