#!/usr/bin/env python3
"""Audit whether 2-week relative strength improves early-entry timing.

Read-only sidecar. It does not change AlphaOps scores, target books, cash,
weights, live trading, or production gates. Forward returns are audit labels
only and are never written back into a policy input.
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

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.run_alphaops_vnext_policy_replay import price_return_window  # noqa: E402
from tools.run_weekly_evaluation import load_price_series, price_on_or_after, price_on_or_before  # noqa: E402


CASH_TICKERS = {"CASH", "__CASH__"}
WINDOWS: dict[str, tuple[str, int]] = {
    "1w": ("days", 5),
    "2w": ("days", 10),
    "1m": ("months", 1),
    "3m": ("months", 3),
}
DEFAULT_BENCHMARKS = ("SPY", "QQQ")
DEFAULT_HORIZONS = (63, 126)
MIN_OBS = 8
MIN_OOS_OBS = 3
MIN_EDGE_PP = 0.005


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except Exception:
        return default
    return out if math.isfinite(out) else default


def truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    return text in {"1", "true", "yes", "y", "on"}


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame()


def price_returns(prices: dict[str, pd.DataFrame], ticker: str, dt: pd.Timestamp) -> dict[str, Any]:
    px = prices.get(ticker, pd.DataFrame())
    out: dict[str, Any] = {}
    for label, (mode, amount) in WINDOWS.items():
        ret, ok = price_return_window(px, dt, mode, amount)
        out[f"ticker_ret_{label}"] = ret
        out[f"rs_price_coverage_{label}"] = bool(ok)
    return out


def benchmark_returns(prices: dict[str, pd.DataFrame], dt: pd.Timestamp, benchmarks: tuple[str, ...]) -> dict[str, float]:
    out: dict[str, float] = {}
    for bench in benchmarks:
        px = prices.get(bench, pd.DataFrame())
        for label, (mode, amount) in WINDOWS.items():
            ret, _ok = price_return_window(px, dt, mode, amount)
            out[f"{bench.lower()}_{label}"] = ret
    return out


def forward_return(px: pd.DataFrame, start_date: pd.Timestamp, horizon_days: int) -> tuple[float, bool]:
    if px.empty:
        return 0.0, False
    start_dt, start_px = price_on_or_after(px, start_date, "close")
    if start_dt is None or start_px is None or start_px <= 0:
        return 0.0, False
    end_target = pd.Timestamp(start_dt) + pd.Timedelta(days=int(horizon_days))
    end_dt, end_px = price_on_or_before(px, end_target, "close")
    if end_dt is None or end_px is None or end_px <= 0 or pd.Timestamp(end_dt) <= pd.Timestamp(start_dt):
        return 0.0, False
    return float(end_px / start_px - 1.0), True


def load_prices(price_cache: Path, tickers: set[str]) -> dict[str, pd.DataFrame]:
    return {ticker: load_price_series(price_cache, ticker) for ticker in sorted(tickers) if ticker and ticker not in CASH_TICKERS}


def prepare_rows(
    target_book: Path,
    price_cache: Path,
    *,
    portfolio: str,
    benchmarks: tuple[str, ...],
) -> pd.DataFrame:
    raw = read_csv(target_book)
    if raw.empty or "rebalance_date" not in raw.columns or "ticker" not in raw.columns:
        return pd.DataFrame()
    d = raw.copy()
    if "portfolio_kind" in d.columns:
        d = d[d["portfolio_kind"].astype(str).str.lower().eq(portfolio.lower())].copy()
    d["ticker"] = d["ticker"].astype(str).str.upper().str.strip()
    d["rebalance_date"] = pd.to_datetime(d["rebalance_date"], errors="coerce").dt.tz_localize(None).dt.normalize()
    d = d.dropna(subset=["rebalance_date"])
    d = d[~d["ticker"].isin(CASH_TICKERS)].copy()

    applied_col = "concentrated_cashfunded_early_entry_applied"
    if applied_col in d.columns:
        d = d[d[applied_col].map(truthy)].copy()
    elif "weight" in d.columns:
        # Fallback for synthetic tests or future variants: audit positive-weight
        # rows, but mark the source explicitly.
        d = d[pd.to_numeric(d["weight"], errors="coerce").fillna(0.0) > 0].copy()
        d["rs_2w_screen_population_fallback"] = "positive_weight_rows"
    if d.empty:
        return pd.DataFrame()

    tickers = set(d["ticker"].dropna().astype(str))
    tickers.update(benchmarks)
    prices = load_prices(price_cache, tickers)
    rows: list[dict[str, Any]] = []
    for rec in d.to_dict("records"):
        ticker = str(rec.get("ticker", "")).upper().strip()
        dt = pd.Timestamp(rec.get("rebalance_date")).normalize()
        out = dict(rec)
        ticker_rets = price_returns(prices, ticker, dt)
        bench_rets = benchmark_returns(prices, dt, benchmarks)
        out.update(ticker_rets)
        for label in WINDOWS:
            rs_values = []
            for bench in benchmarks:
                bench_ret = safe_float(bench_rets.get(f"{bench.lower()}_{label}"), 0.0)
                rs = safe_float(ticker_rets.get(f"ticker_ret_{label}"), 0.0) - bench_ret
                out[f"rs_{bench.lower()}_{label}"] = rs
                rs_values.append(rs)
            out[f"rs_benchmark_{label}"] = float(np.mean(rs_values)) if rs_values else 0.0
        for horizon in DEFAULT_HORIZONS:
            tr, tok = forward_return(prices.get(ticker, pd.DataFrame()), dt, horizon)
            bench_fwds = []
            for bench in benchmarks:
                br, bok = forward_return(prices.get(bench, pd.DataFrame()), dt, horizon)
                if bok:
                    bench_fwds.append(br)
            bret = float(np.mean(bench_fwds)) if bench_fwds else 0.0
            out[f"forward_{horizon}d_return_audit_only"] = tr
            out[f"forward_{horizon}d_excess_audit_only"] = tr - bret
            out[f"forward_{horizon}d_coverage"] = bool(tok and bench_fwds)
        rows.append(out)
    return pd.DataFrame(rows)


def split_stats(frame: pd.DataFrame, mask: pd.Series, *, oos_start: pd.Timestamp, label: str) -> dict[str, Any]:
    subset = frame[mask].copy()
    if subset.empty:
        return {
            "label": label,
            "rows": 0,
            "oos_rows": 0,
            "mean_126d_excess": None,
            "hit_rate_126d": None,
            "oos_mean_126d_excess": None,
            "oos_hit_rate_126d": None,
            "mean_63d_excess": None,
        }
    f126 = pd.to_numeric(subset.get("forward_126d_excess_audit_only"), errors="coerce")
    f63 = pd.to_numeric(subset.get("forward_63d_excess_audit_only"), errors="coerce")
    oos = subset[pd.to_datetime(subset["rebalance_date"], errors="coerce") >= oos_start].copy()
    o126 = pd.to_numeric(oos.get("forward_126d_excess_audit_only"), errors="coerce")
    return {
        "label": label,
        "rows": int(len(subset)),
        "oos_rows": int(len(oos)),
        "mean_126d_excess": float(f126.mean()) if f126.notna().any() else None,
        "hit_rate_126d": float((f126 > 0).mean()) if f126.notna().any() else None,
        "oos_mean_126d_excess": float(o126.mean()) if o126.notna().any() else None,
        "oos_hit_rate_126d": float((o126 > 0).mean()) if o126.notna().any() else None,
        "mean_63d_excess": float(f63.mean()) if f63.notna().any() else None,
    }


def evaluate(frame: pd.DataFrame, *, oos_start: str) -> tuple[dict[str, Any], pd.DataFrame]:
    if frame.empty:
        return {
            "status": "blocked_no_rows",
            "verdict": "keep_telemetry_only",
            "reason": "no early-entry/applied rows to audit",
            "windows": {},
        }, pd.DataFrame()

    oos_ts = pd.Timestamp(oos_start)
    stats: list[dict[str, Any]] = [split_stats(frame, pd.Series(True, index=frame.index), oos_start=oos_ts, label="all_applied")]
    for label in WINDOWS:
        rs = pd.to_numeric(frame.get(f"rs_benchmark_{label}"), errors="coerce").fillna(0.0)
        stats.append(split_stats(frame, rs > 0.0, oos_start=oos_ts, label=f"{label}_rs_positive"))
        if len(frame) >= 4:
            cutoff = float(rs.quantile(0.50))
            stats.append(split_stats(frame, rs >= cutoff, oos_start=oos_ts, label=f"{label}_rs_top_half"))
    table = pd.DataFrame(stats)
    base = table[table["label"].eq("all_applied")].iloc[0].to_dict()
    two = table[table["label"].eq("2w_rs_positive")]
    two_row = two.iloc[0].to_dict() if not two.empty else {}
    other = table[
        table["label"].isin(["1w_rs_positive", "1m_rs_positive", "3m_rs_positive"])
    ].copy()
    other_best = None
    if not other.empty:
        other["mean_for_rank"] = pd.to_numeric(other["mean_126d_excess"], errors="coerce").fillna(-999.0)
        other_best = other.sort_values("mean_for_rank", ascending=False).iloc[0].to_dict()

    two_mean = two_row.get("mean_126d_excess")
    base_mean = base.get("mean_126d_excess")
    two_oos = two_row.get("oos_mean_126d_excess")
    other_mean = other_best.get("mean_126d_excess") if other_best else None
    pass_screen = (
        int(two_row.get("rows") or 0) >= MIN_OBS
        and int(two_row.get("oos_rows") or 0) >= MIN_OOS_OBS
        and two_mean is not None
        and base_mean is not None
        and two_oos is not None
        and two_mean >= base_mean + MIN_EDGE_PP
        and (other_mean is None or two_mean >= safe_float(other_mean) - 1e-12)
        and two_oos >= -MIN_EDGE_PP
    )
    if pass_screen:
        verdict = "screen_pass_design_default_off_2w_rs_gate"
    else:
        verdict = "keep_2w_rs_telemetry_only"
    summary = {
        "schema_version": "rs-2w-entry-timing-screen-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "completed",
        "verdict": verdict,
        "audit_only": True,
        "policy_mutation_allowed": False,
        "score_mutation_allowed": False,
        "min_obs": MIN_OBS,
        "min_oos_obs": MIN_OOS_OBS,
        "min_edge_pp": MIN_EDGE_PP,
        "total_rows": int(len(frame)),
        "base_mean_126d_excess": base_mean,
        "two_week_positive": two_row,
        "best_other_positive_window": other_best,
        "windows": {str(row["label"]): row for row in table.to_dict("records")},
    }
    return summary, table


def render_report(summary: dict[str, Any], table: pd.DataFrame) -> str:
    lines = ["# RS 2W Entry Timing Screen", ""]
    lines.append(f"- verdict: `{summary.get('verdict')}`")
    lines.append(f"- total_rows: `{summary.get('total_rows')}`")
    lines.append("- audit_only: `true`")
    lines.append("- score_mutation_allowed: `false`")
    lines.append("")
    lines.append("## Window Comparison")
    lines.append("")
    lines.append("| bucket | rows | OOS rows | mean 126d excess | hit rate | OOS mean 126d excess |")
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: |")
    for row in table.to_dict("records"):
        def pct(value: Any) -> str:
            if value is None or (isinstance(value, float) and not math.isfinite(value)):
                return ""
            return f"{float(value):.2%}"
        lines.append(
            f"| {row.get('label')} | {int(row.get('rows') or 0)} | {int(row.get('oos_rows') or 0)} | "
            f"{pct(row.get('mean_126d_excess'))} | {pct(row.get('hit_rate_126d'))} | {pct(row.get('oos_mean_126d_excess'))} |"
        )
    lines.append("")
    lines.append("Forward returns are audit labels only. This report does not justify production promotion or direct score mutation.")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-book", required=True)
    parser.add_argument("--price-cache", required=True)
    parser.add_argument("--output-dir", default="outputs/rs_2w_entry_timing_screen")
    parser.add_argument("--portfolio", default="concentrated")
    parser.add_argument("--benchmarks", default="SPY,QQQ")
    parser.add_argument("--oos-start", default="2024-06-03")
    args = parser.parse_args()

    benchmarks = tuple(x.strip().upper() for x in str(args.benchmarks).split(",") if x.strip())
    frame = prepare_rows(
        Path(args.target_book),
        Path(args.price_cache),
        portfolio=args.portfolio,
        benchmarks=benchmarks or DEFAULT_BENCHMARKS,
    )
    summary, table = evaluate(frame, oos_start=args.oos_start)

    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    frame.to_csv(out / "audited_rows.csv", index=False)
    table.to_csv(out / "window_summary.csv", index=False)
    (out / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (out / "report.md").write_text(render_report(summary, table), encoding="utf-8")
    print(render_report(summary, table))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
