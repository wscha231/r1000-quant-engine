#!/usr/bin/env python3
"""Replay main-book cash deployment using monthly holdings.

This is a lightweight pre-fullrun diagnostic. It does not rebuild features or
models. It reads `reports/main_monthly_weights.csv`, caps each month's cash
weight, and redeploys excess cash into the already-selected stock book subject
to a single-name cap grid.

The goal is to answer one narrow question before a 4-hour rebuild:

    Is standing/residual cash likely helping drawdown enough to justify its
    CAGR drag?

Outputs are research-only and are not production activation evidence.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LATEST_RUN = REPO_ROOT / "cloud_results" / "full_rebuild" / "latest_global_alpha_universe"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "outputs" / "main_cash_drag_replay"
CASH_TICKER = "CASH"


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def safe_float(value: Any, default: float = float("nan")) -> float:
    try:
        if value is None or value == "":
            return default
        out = float(value)
    except Exception:
        return default
    return out if math.isfinite(out) else default


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def performance_metrics(monthly_returns: pd.Series) -> dict[str, float]:
    r = pd.to_numeric(monthly_returns, errors="coerce").dropna()
    if r.empty:
        return {"months": 0, "cagr": float("nan"), "sharpe": float("nan"), "max_dd": float("nan")}
    equity = (1.0 + r).cumprod()
    years = len(r) / 12.0
    cagr = float(equity.iloc[-1] ** (1.0 / years) - 1.0) if years > 0 and equity.iloc[-1] > 0 else float("nan")
    vol = float(r.std(ddof=0) * math.sqrt(12.0)) if len(r) > 1 else 0.0
    sharpe = float(r.mean() * 12.0 / vol) if vol > 1e-12 else float("nan")
    dd = equity / equity.cummax() - 1.0
    return {
        "months": int(len(r)),
        "cagr": cagr,
        "sharpe": sharpe,
        "max_dd": float(dd.min()),
        "terminal_multiple": float(equity.iloc[-1]),
        "avg_monthly_return": float(r.mean()),
        "vol_ann": vol,
    }


def redeploy_month(group: pd.DataFrame, cash_cap: float, single_name_cap: float) -> pd.DataFrame:
    g = group.copy()
    g["ticker"] = g["ticker"].astype(str).str.upper()
    g["weight"] = pd.to_numeric(g["weight"], errors="coerce").fillna(0.0).clip(lower=0.0)
    cash_mask = g["ticker"].eq(CASH_TICKER)
    cash_weight = float(g.loc[cash_mask, "weight"].sum())
    target_cash = min(cash_weight, float(cash_cap))
    release = max(0.0, cash_weight - target_cash)
    stock_mask = ~cash_mask
    if release > 1e-12 and bool(stock_mask.any()):
        stock_w = g.loc[stock_mask, "weight"].copy()
        cap = pd.Series(float(single_name_cap), index=stock_w.index)
        headroom = (cap - stock_w).clip(lower=0.0)
        total_headroom = float(headroom.sum())
        if total_headroom > 1e-12:
            add = min(release, total_headroom) * (headroom / total_headroom)
            g.loc[stock_mask, "weight"] = stock_w + add
            target_cash = cash_weight - float(add.sum())
    if bool(cash_mask.any()):
        g.loc[cash_mask, "weight"] = 0.0
        first_cash_idx = g.index[cash_mask][0]
        g.loc[first_cash_idx, "weight"] = target_cash
    elif target_cash > 1e-12:
        cash_row = {col: "" for col in g.columns}
        cash_row.update({"ticker": CASH_TICKER, "weight": target_cash, "period_forward_return": 0.0})
        g = pd.concat([g, pd.DataFrame([cash_row])], ignore_index=True)
    total = float(pd.to_numeric(g["weight"], errors="coerce").fillna(0.0).sum())
    if total > 1e-12 and abs(total - 1.0) > 1e-8:
        g["weight"] = pd.to_numeric(g["weight"], errors="coerce").fillna(0.0) / total
    return g


def monthly_return(group: pd.DataFrame) -> float:
    w = pd.to_numeric(group.get("weight"), errors="coerce").fillna(0.0)
    r = pd.to_numeric(group.get("period_forward_return"), errors="coerce").fillna(0.0)
    return float((w * r).sum())


def approx_turnover(weights_by_month: dict[str, dict[str, float]]) -> float:
    prev: dict[str, float] | None = None
    turns: list[float] = []
    for date in sorted(weights_by_month):
        cur = weights_by_month[date]
        if prev is not None:
            keys = set(prev) | set(cur)
            turns.append(0.5 * sum(abs(cur.get(k, 0.0) - prev.get(k, 0.0)) for k in keys))
        prev = cur
    return float(np.mean(turns)) if turns else float("nan")


def replay(df: pd.DataFrame, cash_caps: list[float], single_caps: list[float]) -> tuple[pd.DataFrame, dict[str, Any]]:
    required = {"rebalance_date", "ticker", "weight", "period_forward_return"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"main_monthly_weights.csv missing columns: {sorted(missing)}")
    d = df.copy()
    d["rebalance_date"] = pd.to_datetime(d["rebalance_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    d = d.dropna(subset=["rebalance_date", "ticker"])
    base_returns: list[dict[str, Any]] = []
    base_weights: dict[str, dict[str, float]] = {}
    for date, group in d.groupby("rebalance_date", sort=True):
        base_returns.append({"model": "base", "rebalance_date": date, "net_return": monthly_return(group)})
        base_weights[str(date)] = {
            str(row["ticker"]).upper(): safe_float(row["weight"], 0.0)
            for _, row in group.iterrows()
        }
    base_metrics = performance_metrics(pd.Series([row["net_return"] for row in base_returns]))
    base_metrics["avg_cash_weight"] = float(
        d.assign(ticker=d["ticker"].astype(str).str.upper())
        .loc[lambda x: x["ticker"].eq(CASH_TICKER)]
        .groupby("rebalance_date")["weight"]
        .sum()
        .mean()
    )
    base_metrics["avg_turnover_monthly"] = approx_turnover(base_weights)

    rows: list[dict[str, Any]] = []
    curve_rows: list[dict[str, Any]] = []
    for cash_cap in cash_caps:
        for single_cap in single_caps:
            returns: list[float] = []
            weights_by_month: dict[str, dict[str, float]] = {}
            cash_vals: list[float] = []
            for date, group in d.groupby("rebalance_date", sort=True):
                adj = redeploy_month(group, cash_cap=cash_cap, single_name_cap=single_cap)
                ret = monthly_return(adj)
                returns.append(ret)
                cash = float(adj.loc[adj["ticker"].astype(str).str.upper().eq(CASH_TICKER), "weight"].sum())
                cash_vals.append(cash)
                weights_by_month[str(date)] = {
                    str(row["ticker"]).upper(): safe_float(row["weight"], 0.0)
                    for _, row in adj.iterrows()
                }
                curve_rows.append({
                    "model": f"cash{cash_cap:.2f}_cap{single_cap:.2f}",
                    "rebalance_date": date,
                    "net_return": ret,
                    "cash_weight": cash,
                })
            metrics = performance_metrics(pd.Series(returns))
            metrics.update({
                "model": f"cash{cash_cap:.2f}_cap{single_cap:.2f}",
                "cash_cap": float(cash_cap),
                "single_name_cap": float(single_cap),
                "avg_cash_weight": float(np.mean(cash_vals)) if cash_vals else float("nan"),
                "avg_turnover_monthly": approx_turnover(weights_by_month),
                "delta_cagr_vs_base": safe_float(metrics.get("cagr")) - safe_float(base_metrics.get("cagr")),
                "delta_max_dd_vs_base": safe_float(metrics.get("max_dd")) - safe_float(base_metrics.get("max_dd")),
                "production_activation_allowed": False,
            })
            rows.append(metrics)
    grid = pd.DataFrame(rows).sort_values(["delta_cagr_vs_base", "sharpe"], ascending=[False, False])
    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "mode": "research_only",
        "production_activation_allowed": False,
        "base_metrics": base_metrics,
        "best_by_cagr": grid.head(1).to_dict("records")[0] if not grid.empty else {},
        "candidate_count": int(len(grid)),
        "note": "Uses existing monthly selected holdings only; it cannot discover missed tickers.",
    }
    return grid, {"summary": summary, "curve_rows": curve_rows}


def render_report(summary: dict[str, Any], grid: pd.DataFrame) -> str:
    base = summary.get("base_metrics") or {}
    best = summary.get("best_by_cagr") or {}

    def pct(value: Any) -> str:
        value = safe_float(value)
        return "NA" if not math.isfinite(value) else f"{value:.2%}"

    lines = [
        "# Main Cash Drag Replay",
        "",
        "Research-only pre-fullrun diagnostic. No production behavior is changed.",
        "",
        f"- base CAGR / Sharpe / MaxDD: {pct(base.get('cagr'))} / {base.get('sharpe')} / {pct(base.get('max_dd'))}",
        f"- base avg cash: {pct(base.get('avg_cash_weight'))}",
        f"- best model: `{best.get('model', 'NA')}`",
        f"- best CAGR / Sharpe / MaxDD: {pct(best.get('cagr'))} / {best.get('sharpe')} / {pct(best.get('max_dd'))}",
        f"- best avg cash: {pct(best.get('avg_cash_weight'))}",
        "",
        "## Top Grid Rows",
        "",
        "| model | CAGR | Sharpe | MaxDD | Avg Cash | Delta CAGR | Delta MaxDD |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for _, row in grid.head(12).iterrows():
        lines.append(
            f"| {row.get('model')} | {pct(row.get('cagr'))} | {safe_float(row.get('sharpe')):.3f} | "
            f"{pct(row.get('max_dd'))} | {pct(row.get('avg_cash_weight'))} | "
            f"{pct(row.get('delta_cagr_vs_base'))} | {pct(row.get('delta_max_dd_vs_base'))} |"
        )
    lines.extend([
        "",
        "## Limits",
        "",
        "- This replay reallocates only within already-selected monthly holdings.",
        "- It does not discover missed winners such as a future SNDK-like setup.",
        "- A full rebuild/challenger replay is still required before activation.",
        "",
    ])
    return "\n".join(lines)


def parse_grid(text: str) -> list[float]:
    return [float(x.strip()) for x in str(text).split(",") if x.strip()]


def run(args: argparse.Namespace) -> dict[str, Any]:
    latest_run = repo_path(args.latest_run)
    out_dir = repo_path(args.output_dir)
    source = latest_run / "reports" / "main_monthly_weights.csv"
    if not source.exists():
        raise SystemExit(f"ERROR: missing {source}")
    df = pd.read_csv(source)
    grid, payload = replay(df, parse_grid(args.cash_caps), parse_grid(args.single_name_caps))
    out_dir.mkdir(parents=True, exist_ok=True)
    grid.to_csv(out_dir / "cash_drag_grid.csv", index=False)
    pd.DataFrame(payload["curve_rows"]).to_csv(out_dir / "cash_drag_equity_inputs.csv", index=False)
    write_json(out_dir / "summary.json", payload["summary"])
    (out_dir / "cash_drag_replay_report.md").write_text(render_report(payload["summary"], grid), encoding="utf-8")
    return payload["summary"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--latest-run", default=str(DEFAULT_LATEST_RUN))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--cash-caps", default="0.00,0.03,0.05,0.08")
    parser.add_argument("--single-name-caps", default="0.18,0.22,0.25,0.33")
    return parser.parse_args()


def main() -> int:
    summary = run(parse_args())
    print(json.dumps({
        "production_activation_allowed": summary.get("production_activation_allowed"),
        "best_by_cagr": summary.get("best_by_cagr"),
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
