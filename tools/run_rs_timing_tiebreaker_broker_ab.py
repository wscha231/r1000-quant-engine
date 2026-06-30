#!/usr/bin/env python3
"""Broker A/B for RS timing tie-breakers on cash-funded early entries.

Research-only. This tool does not run the full AlphaOps policy replay and does
not change production target books. It takes an already generated concentrated
target book, removes cash-funded early-entry rows that fail a PIT relative
strength timing rule, returns that weight to cash on the same rebalance date,
and replays the resulting book through the broker ledger.

Forward returns are not used. The `rs2w_is_median` threshold is learned only
from the IS window before `--oos-start` and then frozen for the whole replay.
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.run_alphaops_vnext_policy_replay import price_return_window  # noqa: E402
from tools.run_weekly_evaluation import load_price_series  # noqa: E402


CASH_TICKERS = {"CASH", "__CASH__"}
EARLY_ENTRY_COL = "concentrated_cashfunded_early_entry_applied"
DEFAULT_OUTPUT_DIR = "outputs/rs_timing_tiebreaker_broker_ab"
DEFAULT_ARMS = ("baseline", "rs2w_positive", "rs2w_is_median")


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except Exception:
        return default
    return out if math.isfinite(out) else default


def truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame()


def load_prices(price_cache: Path, tickers: set[str]) -> dict[str, pd.DataFrame]:
    return {ticker: load_price_series(price_cache, ticker) for ticker in sorted(tickers) if ticker and ticker not in CASH_TICKERS}


def rs_benchmark_2w(prices: dict[str, pd.DataFrame], ticker: str, dt: pd.Timestamp) -> tuple[float, bool]:
    ticker_ret, ticker_ok = price_return_window(prices.get(ticker, pd.DataFrame()), dt, "days", 10)
    bench_vals: list[float] = []
    for bench in ("SPY", "QQQ"):
        bench_ret, bench_ok = price_return_window(prices.get(bench, pd.DataFrame()), dt, "days", 10)
        if bench_ok:
            bench_vals.append(float(ticker_ret) - float(bench_ret))
    if not ticker_ok or not bench_vals:
        return 0.0, False
    return float(sum(bench_vals) / len(bench_vals)), True


def annotate_2w_rs(book: pd.DataFrame, price_cache: Path) -> pd.DataFrame:
    d = book.copy()
    d["__row_id"] = range(len(d))
    d["rebalance_date"] = pd.to_datetime(d["rebalance_date"], errors="coerce").dt.tz_localize(None).dt.normalize()
    d["ticker"] = d["ticker"].astype(str).str.upper().str.strip()
    tickers = set(d["ticker"].dropna().astype(str))
    tickers.update({"SPY", "QQQ"})
    prices = load_prices(price_cache, tickers)
    values: list[float] = []
    coverage: list[bool] = []
    for rec in d.to_dict("records"):
        ticker = str(rec.get("ticker") or "").upper().strip()
        if ticker in CASH_TICKERS:
            values.append(0.0)
            coverage.append(False)
            continue
        dt = pd.Timestamp(rec.get("rebalance_date")).normalize()
        rs, ok = rs_benchmark_2w(prices, ticker, dt)
        values.append(rs)
        coverage.append(ok)
    d["rs_benchmark_2w_tiebreaker"] = values
    d["rs_benchmark_2w_tiebreaker_coverage"] = coverage
    return d


def applied_mask(book: pd.DataFrame) -> pd.Series:
    if EARLY_ENTRY_COL not in book.columns:
        return pd.Series(False, index=book.index)
    return book[EARLY_ENTRY_COL].map(truthy)


def learn_is_threshold(book: pd.DataFrame, *, oos_start: str) -> float | None:
    mask = applied_mask(book)
    is_rows = book[mask & pd.to_datetime(book["rebalance_date"], errors="coerce").lt(pd.Timestamp(oos_start))].copy()
    vals = pd.to_numeric(is_rows.get("rs_benchmark_2w_tiebreaker"), errors="coerce").dropna()
    if vals.empty:
        return None
    return float(vals.quantile(0.50))


def ensure_cash_row(rows: list[dict[str, Any]], template: dict[str, Any], amount: float) -> None:
    if amount <= 1e-12:
        return
    for row in rows:
        if str(row.get("ticker") or "").upper().strip() in CASH_TICKERS:
            row["weight"] = safe_float(row.get("weight")) + amount
            row["target_weight"] = safe_float(row.get("target_weight"), safe_float(row.get("weight"))) + amount
            row["rs_timing_tiebreaker_cash_restored"] = safe_float(row.get("rs_timing_tiebreaker_cash_restored")) + amount
            return
    cash = dict(template)
    cash["ticker"] = "CASH"
    cash["Name"] = "Cash"
    cash["sector"] = "Cash"
    cash["primary_lane"] = "CASH"
    cash["weight"] = amount
    cash["target_weight"] = amount
    cash["selection_reason"] = "cash_from_rs_timing_tiebreaker_filter"
    cash["rs_timing_tiebreaker_cash_restored"] = amount
    rows.append(cash)


def build_arm_book(book: pd.DataFrame, *, arm: str, threshold: float | None) -> tuple[pd.DataFrame, pd.DataFrame]:
    d = book.copy()
    d["weight"] = pd.to_numeric(d.get("weight"), errors="coerce").fillna(0.0)
    if "target_weight" in d.columns:
        d["target_weight"] = pd.to_numeric(d.get("target_weight"), errors="coerce").fillna(d["weight"])
    else:
        d["target_weight"] = d["weight"]

    records: list[dict[str, Any]] = []
    telemetry: list[dict[str, Any]] = []
    for dt, group in d.groupby("rebalance_date", sort=True):
        out_rows: list[dict[str, Any]] = []
        removed_weight = 0.0
        kept_count = 0
        removed_count = 0
        for rec in group.to_dict("records"):
            ticker = str(rec.get("ticker") or "").upper().strip()
            is_entry = truthy(rec.get(EARLY_ENTRY_COL))
            keep = True
            reason = "not_early_entry"
            if is_entry and ticker not in CASH_TICKERS and arm != "baseline":
                rs = safe_float(rec.get("rs_benchmark_2w_tiebreaker"))
                covered = truthy(rec.get("rs_benchmark_2w_tiebreaker_coverage"))
                if arm == "rs2w_positive":
                    keep = covered and rs > 0.0
                    reason = "rs2w_positive_pass" if keep else "rs2w_positive_filter"
                elif arm == "rs2w_is_median":
                    keep = threshold is not None and covered and rs >= float(threshold)
                    reason = "rs2w_is_median_pass" if keep else "rs2w_is_median_filter"
                else:
                    reason = "unknown_arm"
            if keep:
                rec["rs_timing_tiebreaker_status"] = "kept" if is_entry else "not_applicable"
                rec["rs_timing_tiebreaker_reason"] = reason
                out_rows.append(rec)
                if is_entry and ticker not in CASH_TICKERS:
                    kept_count += 1
            else:
                removed_weight += safe_float(rec.get("weight"))
                removed_count += 1
                telemetry.append(
                    {
                        "arm": arm,
                        "rebalance_date": pd.Timestamp(dt).date().isoformat(),
                        "ticker": ticker,
                        "action": "removed_to_cash",
                        "weight": safe_float(rec.get("weight")),
                        "rs_benchmark_2w": safe_float(rec.get("rs_benchmark_2w_tiebreaker")),
                        "threshold": threshold,
                        "reason": reason,
                    }
                )
        template = group.iloc[0].to_dict() if not group.empty else {}
        ensure_cash_row(out_rows, template, removed_weight)
        telemetry.append(
            {
                "arm": arm,
                "rebalance_date": pd.Timestamp(dt).date().isoformat(),
                "ticker": "__DATE_SUMMARY__",
                "action": "date_summary",
                "removed_weight": removed_weight,
                "kept_early_entry_count": kept_count,
                "removed_early_entry_count": removed_count,
                "threshold": threshold,
            }
        )
        records.extend(out_rows)
    out = pd.DataFrame(records)
    for col in ["__row_id"]:
        if col in out.columns:
            out = out.drop(columns=[col])
    return out, pd.DataFrame(telemetry)


def run_broker_replay(
    *,
    target_book: Path,
    price_cache: Path,
    output_dir: Path,
    cost_bps: float,
    max_fill_lag_days: int,
    starting_capital: float,
) -> dict[str, Any]:
    cmd = [
        sys.executable,
        str(REPO_ROOT / "tools" / "run_broker_ledger_replay.py"),
        "--target-book",
        str(target_book),
        "--price-cache",
        str(price_cache),
        "--portfolio-kind",
        "concentrated",
        "--output-dir",
        str(output_dir),
        "--fill-mode",
        "next_close",
        "--cost-bps",
        str(cost_bps),
        "--max-fill-lag-days",
        str(max_fill_lag_days),
        "--starting-capital",
        str(starting_capital),
        "--disable-concentrated-champion-filter",
    ]
    subprocess.run(cmd, cwd=REPO_ROOT, check=True)
    path = output_dir / "metrics.json"
    if not path.exists():
        return {"status": "missing_metrics", "broker_metrics_path": str(path)}
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["broker_metrics_path"] = str(path)
    return payload


def metric_row(arm: str, metrics: dict[str, Any], telemetry: pd.DataFrame, target_book: Path) -> dict[str, Any]:
    removed = telemetry[telemetry.get("action", pd.Series(dtype=str)).astype(str).eq("removed_to_cash")] if not telemetry.empty else pd.DataFrame()
    return {
        "arm": arm,
        "status": metrics.get("status", ""),
        "metric_mode": metrics.get("metric_mode", ""),
        "cagr": safe_float(metrics.get("cagr")),
        "max_dd": safe_float(metrics.get("max_dd")),
        "sharpe": safe_float(metrics.get("sharpe")),
        "years": safe_float(metrics.get("years")),
        "start_date": metrics.get("start_date", ""),
        "end_date": metrics.get("end_date", ""),
        "avg_cash_weight": safe_float(metrics.get("avg_cash_weight")),
        "trade_count": int(safe_float(metrics.get("trade_count"))),
        "removed_early_entry_count": int(len(removed)),
        "removed_weight_sum": float(pd.to_numeric(removed.get("weight", pd.Series(dtype=float)), errors="coerce").fillna(0.0).sum()) if not removed.empty else 0.0,
        "target_book_path": str(target_book),
        "broker_metrics_path": str(metrics.get("broker_metrics_path", "")),
    }


def add_deltas(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    base = next((row for row in rows if row["arm"] == "baseline"), None)
    if not base:
        return rows
    for row in rows:
        row["delta_cagr"] = safe_float(row.get("cagr")) - safe_float(base.get("cagr"))
        row["delta_max_dd"] = safe_float(row.get("max_dd")) - safe_float(base.get("max_dd"))
        row["delta_sharpe"] = safe_float(row.get("sharpe")) - safe_float(base.get("sharpe"))
        row["delta_avg_cash_weight"] = safe_float(row.get("avg_cash_weight")) - safe_float(base.get("avg_cash_weight"))
    return rows


def choose_verdict(rows: list[dict[str, Any]]) -> str:
    candidates = [
        row
        for row in rows
        if row.get("arm") != "baseline"
        and row.get("status") == "completed"
        and safe_float(row.get("delta_cagr")) >= 0.005
        and safe_float(row.get("delta_max_dd")) >= -0.0025
    ]
    if candidates:
        return "research_pass_design_default_off_rs_timing_tiebreaker"
    if any(row.get("arm") != "baseline" and int(row.get("removed_early_entry_count") or 0) > 0 for row in rows):
        return "reject_no_broker_edge_keep_telemetry"
    return "blocked_no_tiebreaker_applied"


def render_report(summary: dict[str, Any], table: pd.DataFrame) -> str:
    lines = ["# RS Timing Tie-Breaker Broker A/B", ""]
    lines.append(f"- verdict: `{summary.get('verdict')}`")
    lines.append(f"- audit_only: `{str(summary.get('audit_only')).lower()}`")
    lines.append(f"- production_mutation_allowed: `{str(summary.get('production_mutation_allowed')).lower()}`")
    lines.append(f"- IS threshold: `{summary.get('rs2w_is_median_threshold')}`")
    lines.append("")
    lines.append("| arm | CAGR | MaxDD | Sharpe | delta CAGR | delta MaxDD | removed entries |")
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: |")
    for row in table.to_dict("records"):
        lines.append(
            f"| {row.get('arm')} | {safe_float(row.get('cagr')):.2%} | {safe_float(row.get('max_dd')):.2%} | "
            f"{safe_float(row.get('sharpe')):.3f} | {safe_float(row.get('delta_cagr')):.2%} | "
            f"{safe_float(row.get('delta_max_dd')):.2%} | {int(safe_float(row.get('removed_early_entry_count')))} |"
        )
    lines.append("")
    lines.append("This is a research-only broker A/B. It does not authorize direct 2w RS scoring or production promotion.")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-book", required=True)
    parser.add_argument("--price-cache", required=True)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--oos-start", default="2024-06-03")
    parser.add_argument("--cost-bps", type=float, default=25.0)
    parser.add_argument("--max-fill-lag-days", type=int, default=7)
    parser.add_argument("--starting-capital", type=float, default=100000.0)
    args = parser.parse_args()

    target_book = Path(args.target_book)
    price_cache = Path(args.price_cache)
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)

    raw = read_csv(target_book)
    if raw.empty:
        summary = {"status": "blocked", "reason": "missing_or_empty_target_book", "target_book": str(target_book)}
        (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        return 2
    if "portfolio_kind" in raw.columns:
        raw = raw[raw["portfolio_kind"].astype(str).str.lower().eq("concentrated")].copy()
    annotated = annotate_2w_rs(raw, price_cache)
    threshold = learn_is_threshold(annotated, oos_start=args.oos_start)
    rows: list[dict[str, Any]] = []
    for arm in DEFAULT_ARMS:
        arm_dir = out / arm
        arm_dir.mkdir(parents=True, exist_ok=True)
        arm_book, telemetry = build_arm_book(annotated, arm=arm, threshold=threshold)
        arm_book_path = arm_dir / "target_book.csv"
        telemetry_path = arm_dir / "telemetry.csv"
        arm_book.to_csv(arm_book_path, index=False)
        telemetry.to_csv(telemetry_path, index=False)
        metrics = run_broker_replay(
            target_book=arm_book_path,
            price_cache=price_cache,
            output_dir=arm_dir / "broker",
            cost_bps=float(args.cost_bps),
            max_fill_lag_days=int(args.max_fill_lag_days),
            starting_capital=float(args.starting_capital),
        )
        rows.append(metric_row(arm, metrics, telemetry, arm_book_path))
    rows = add_deltas(rows)
    table = pd.DataFrame(rows)
    summary = {
        "schema_version": "rs-timing-tiebreaker-broker-ab-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "completed",
        "verdict": choose_verdict(rows),
        "audit_only": True,
        "production_mutation_allowed": False,
        "score_mutation_allowed": False,
        "target_book": str(target_book),
        "price_cache": str(price_cache),
        "rs2w_is_median_threshold": threshold,
        "arms": rows,
    }
    table.to_csv(out / "arm_metrics.csv", index=False)
    (out / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (out / "report.md").write_text(render_report(summary, table), encoding="utf-8")
    print(render_report(summary, table))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
