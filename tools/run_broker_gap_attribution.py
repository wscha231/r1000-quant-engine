#!/usr/bin/env python3
"""Explain why monthly/proxy portfolio metrics differ from broker-ledger metrics.

This sidecar is diagnostic only. It intentionally reads the monthly target
book's `weighted_forward_return` when available so we can compare the legacy
research accounting path to the stricter account-ledger path. It must never be
used as a production signal.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.run_broker_ledger_replay import CONCENTRATED_CHAMPION_FILTERS, normalize_targets, read_csv


DEFAULT_OUTPUT_DIR = "outputs/broker_gap_attribution"


def repo_path(path_like: str | Path) -> Path:
    path = Path(path_like)
    return path if path.is_absolute() else REPO_ROOT / path


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


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def pct(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:.2%}"


def max_drawdown(equity: pd.Series) -> float | None:
    s = pd.to_numeric(equity, errors="coerce").dropna()
    if s.empty:
        return None
    return float((s / s.cummax() - 1.0).min())


def cagr(equity: pd.Series, dates: pd.Series) -> float | None:
    s = pd.to_numeric(equity, errors="coerce").dropna()
    if len(s) < 2:
        return None
    dt = pd.to_datetime(dates, errors="coerce").dropna()
    if len(dt) < 2:
        return None
    years = (dt.iloc[-1] - dt.iloc[0]).days / 365.25
    if years <= 0 or s.iloc[0] <= 0:
        return None
    return float((s.iloc[-1] / s.iloc[0]) ** (1.0 / years) - 1.0)


def target_forward_stats(target_book: Path, portfolio_kind: str) -> tuple[dict[str, Any], pd.DataFrame]:
    raw = read_csv(target_book)
    targets = normalize_targets(raw, portfolio_kind)
    if raw.empty or targets.empty or "weighted_forward_return" not in raw.columns:
        return {"status": "missing_forward_target_book", "target_book": str(target_book)}, pd.DataFrame()
    raw = raw.copy()
    if portfolio_kind == "concentrated":
        for col, expected in CONCENTRATED_CHAMPION_FILTERS.items():
            if col not in raw.columns:
                continue
            mask = raw[col].astype(str).str.strip().eq(expected)
            if mask.any():
                raw = raw[mask].copy()
        targets_key = targets[["rebalance_date", "ticker"]].copy()
        targets_key["rebalance_date"] = pd.to_datetime(targets_key["rebalance_date"], errors="coerce").dt.normalize()
        raw["rebalance_date"] = pd.to_datetime(raw["rebalance_date"], errors="coerce").dt.normalize()
        raw["ticker"] = raw["ticker"].astype(str).str.upper().str.strip()
        raw = raw.merge(targets_key.drop_duplicates(), on=["rebalance_date", "ticker"], how="inner")
    raw["rebalance_date"] = pd.to_datetime(raw["rebalance_date"], errors="coerce").dt.normalize()
    raw["weight"] = pd.to_numeric(raw.get("weight"), errors="coerce").fillna(0.0)
    raw["weighted_forward_return"] = pd.to_numeric(raw.get("weighted_forward_return"), errors="coerce").fillna(0.0)
    raw = raw.dropna(subset=["rebalance_date"])
    monthly = (
        raw.groupby("rebalance_date", as_index=False)
        .agg(
            implied_return=("weighted_forward_return", "sum"),
            target_weight_sum=("weight", "sum"),
            names=("ticker", "nunique"),
        )
        .sort_values("rebalance_date")
    )
    monthly["implied_equity"] = (1.0 + monthly["implied_return"]).cumprod() * 100000.0
    prev: dict[str, float] = {}
    turnover_rows: list[dict[str, Any]] = []
    for dt, group in targets.groupby("rebalance_date"):
        cur = {str(row.ticker).upper(): float(row.weight) for row in group.itertuples(index=False)}
        tickers = set(cur) | set(prev)
        target_turnover = sum(abs(cur.get(ticker, 0.0) - prev.get(ticker, 0.0)) for ticker in tickers) / 2.0
        jaccard = None
        if prev:
            jaccard = len(set(cur) & set(prev)) / max(1, len(set(cur) | set(prev)))
        turnover_rows.append(
            {
                "rebalance_date": pd.Timestamp(dt).date().isoformat(),
                "target_turnover": target_turnover,
                "name_jaccard": jaccard,
            }
        )
        prev = cur
    turnover = pd.DataFrame(turnover_rows)
    if not turnover.empty:
        turnover["rebalance_date"] = pd.to_datetime(turnover["rebalance_date"], errors="coerce")
        monthly = monthly.merge(turnover, on="rebalance_date", how="left")
    summary = {
        "status": "completed",
        "metric_mode": "monthly_weighted_forward_return_diagnostic",
        "uses_forward_returns": True,
        "target_book": str(target_book),
        "legacy_implied_cagr": cagr(monthly["implied_equity"], monthly["rebalance_date"]),
        "legacy_implied_max_dd": max_drawdown(monthly["implied_equity"]),
        "avg_target_weight_sum": safe_float(monthly["target_weight_sum"].mean()),
        "avg_names": safe_float(monthly["names"].mean()),
        "avg_target_turnover": safe_float(monthly.get("target_turnover", pd.Series(dtype=float)).iloc[1:].mean()),
        "avg_name_jaccard": safe_float(monthly.get("name_jaccard", pd.Series(dtype=float)).mean()),
    }
    return summary, monthly


def broker_stats(broker_dir: Path) -> tuple[dict[str, Any], pd.DataFrame]:
    metrics = read_json(broker_dir / "metrics.json")
    equity = read_csv(broker_dir / "equity_curve.csv")
    trades = read_csv(broker_dir / "trades.csv")
    if equity.empty or "equity_usd" not in equity.columns:
        return {"status": "missing_broker_equity", "broker_dir": str(broker_dir), **metrics}, pd.DataFrame()
    equity["date"] = pd.to_datetime(equity["date"], errors="coerce")
    equity = equity.dropna(subset=["date"]).sort_values("date")
    month_end = equity.set_index("date")["equity_usd"].resample("ME").last().dropna()
    month_end_dates = pd.Series(month_end.index)
    summary = {
        "status": metrics.get("status", "completed"),
        "metric_mode": metrics.get("metric_mode"),
        "broker_cagr": safe_float(metrics.get("cagr")),
        "broker_max_dd_daily": safe_float(metrics.get("max_dd")),
        "broker_max_dd_month_end": max_drawdown(month_end),
        "broker_sharpe": safe_float(metrics.get("sharpe")),
        "avg_cash_weight": safe_float(metrics.get("avg_cash_weight")),
        "trade_count": int(safe_float(metrics.get("trade_count"), 0) or 0),
        "total_fees_usd": safe_float(metrics.get("total_fees_usd")),
        "gross_traded_usd": safe_float(metrics.get("gross_traded_usd")),
        "gross_traded_on_starting_capital": None,
        "start_date": metrics.get("start_date"),
        "end_date": metrics.get("end_date"),
    }
    if summary["gross_traded_usd"] is not None:
        summary["gross_traded_on_starting_capital"] = float(summary["gross_traded_usd"]) / 100000.0
    monthly = pd.DataFrame(
        {
            "rebalance_date": month_end_dates.dt.normalize(),
            "broker_month_end_equity": month_end.values,
            "broker_month_end_return": month_end.pct_change().fillna(0.0).values,
        }
    )
    if not trades.empty:
        trades["date"] = pd.to_datetime(trades.get("date"), errors="coerce")
        trade_month = trades.dropna(subset=["date"]).copy()
        if not trade_month.empty:
            trade_month["rebalance_date"] = trade_month["date"].dt.to_period("M").dt.to_timestamp("M").dt.normalize()
            agg = (
                trade_month.groupby("rebalance_date", as_index=False)
                .agg(
                    broker_trade_count=("ticker", "size"),
                    broker_fees_usd=("fee_usd", "sum"),
                    broker_gross_traded_usd=("gross_value", "sum"),
                )
            )
            monthly = monthly.merge(agg, on="rebalance_date", how="left")
    return summary, monthly


def portfolio_attribution(latest_run: Path, portfolio_kind: str) -> tuple[dict[str, Any], pd.DataFrame]:
    target_book = latest_run / "reports" / ("main_monthly_weights.csv" if portfolio_kind == "main" else "concentrated_strategy_holdings.csv")
    broker_dir = latest_run / "broker_replay" / portfolio_kind
    target, target_monthly = target_forward_stats(target_book, portfolio_kind)
    broker, broker_monthly = broker_stats(broker_dir)
    monthly = pd.DataFrame()
    if not target_monthly.empty and not broker_monthly.empty:
        target_monthly = target_monthly.copy()
        target_monthly["rebalance_date"] = pd.to_datetime(target_monthly["rebalance_date"], errors="coerce").dt.to_period("M").dt.to_timestamp("M").dt.normalize()
        monthly = target_monthly.merge(broker_monthly, on="rebalance_date", how="outer").sort_values("rebalance_date")
        monthly["return_gap"] = pd.to_numeric(monthly.get("implied_return"), errors="coerce") - pd.to_numeric(monthly.get("broker_month_end_return"), errors="coerce")
    summary = {
        "portfolio": portfolio_kind,
        "target_forward": target,
        "broker_ledger": broker,
        "cagr_gap_pp": None,
        "daily_vs_month_end_dd_gap_pp": None,
        "diagnosis": [],
    }
    target_cagr = safe_float(target.get("legacy_implied_cagr"))
    broker_cagr = safe_float(broker.get("broker_cagr"))
    if target_cagr is not None and broker_cagr is not None:
        summary["cagr_gap_pp"] = round((target_cagr - broker_cagr) * 100.0, 4)
    broker_daily_dd = safe_float(broker.get("broker_max_dd_daily"))
    broker_month_dd = safe_float(broker.get("broker_max_dd_month_end"))
    if broker_daily_dd is not None and broker_month_dd is not None:
        summary["daily_vs_month_end_dd_gap_pp"] = round((broker_month_dd - broker_daily_dd) * 100.0, 4)
    if safe_float(target.get("avg_target_turnover"), 0.0) and float(target.get("avg_target_turnover")) > 0.35:
        summary["diagnosis"].append("high monthly target turnover creates execution cost and churn drag")
    broker_daily_for_diag = safe_float(broker.get("broker_max_dd_daily"))
    target_dd_for_diag = safe_float(target.get("legacy_implied_max_dd"))
    if broker_daily_for_diag is not None and target_dd_for_diag is not None:
        if broker_daily_for_diag < target_dd_for_diag - 0.10:
            summary["diagnosis"].append("monthly/proxy drawdown understates intramonth account drawdown")
    if safe_float(broker.get("avg_cash_weight"), 0.0) and float(broker["avg_cash_weight"]) > 0.05:
        summary["diagnosis"].append("cash/rounding/unfilled exposure drag is material")
    if safe_float(broker.get("total_fees_usd"), 0.0) and float(broker["total_fees_usd"]) > 10000:
        summary["diagnosis"].append("fees are material under realistic turnover")
    if not summary["diagnosis"]:
        summary["diagnosis"].append("no single dominant attribution detected")
    return summary, monthly


def render_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Broker Gap Attribution",
        "",
        "Diagnostic comparison of monthly/proxy accounting versus broker-ledger account replay.",
        "",
        "Important: target-book forward returns are used only for attribution. They are not production signals.",
        "",
        "| Portfolio | Legacy/Proxy CAGR | Broker CAGR | CAGR Gap | Legacy/Proxy MaxDD | Broker Daily MaxDD | Broker Month-End MaxDD | Avg Target Turnover | Trades | Fees | Diagnosis |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for portfolio in ["main", "concentrated"]:
        row = payload.get(portfolio, {})
        target = row.get("target_forward", {})
        broker = row.get("broker_ledger", {})
        lines.append(
            "| {portfolio} | {legacy_cagr} | {broker_cagr} | {gap} | {legacy_dd} | {broker_dd} | {broker_month_dd} | {turnover} | {trades} | {fees} | {diagnosis} |".format(
                portfolio=portfolio,
                legacy_cagr=pct(safe_float(target.get("legacy_implied_cagr"))),
                broker_cagr=pct(safe_float(broker.get("broker_cagr"))),
                gap="" if row.get("cagr_gap_pp") is None else f"{row['cagr_gap_pp']:.2f}pp",
                legacy_dd=pct(safe_float(target.get("legacy_implied_max_dd"))),
                broker_dd=pct(safe_float(broker.get("broker_max_dd_daily"))),
                broker_month_dd=pct(safe_float(broker.get("broker_max_dd_month_end"))),
                turnover=pct(safe_float(target.get("avg_target_turnover"))),
                trades=broker.get("trade_count", ""),
                fees="" if broker.get("total_fees_usd") is None else f"${float(broker['total_fees_usd']):,.0f}",
                diagnosis="; ".join(row.get("diagnosis", [])),
            )
        )
    lines.extend(
        [
            "",
            "## Readout",
            "",
            "- If broker daily MaxDD is much worse than legacy/proxy MaxDD, monthly accounting was hiding intramonth losses.",
            "- If target turnover and fees are high, the strategy must be redesigned around account-aware holding, staging, and replacement rules.",
            "- A proxy target pass is not promotion evidence until the broker-ledger path also passes.",
            "",
        ]
    )
    return "\n".join(lines)


def run(latest_run: Path, output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {"latest_run": str(latest_run), "metric_mode": "broker_gap_attribution"}
    monthly_frames: list[pd.DataFrame] = []
    for portfolio in ["main", "concentrated"]:
        summary, monthly = portfolio_attribution(latest_run, portfolio)
        payload[portfolio] = summary
        if not monthly.empty:
            monthly = monthly.copy()
            monthly.insert(0, "portfolio", portfolio)
            monthly_frames.append(monthly)
    if monthly_frames:
        pd.concat(monthly_frames, ignore_index=True).to_csv(output_dir / "monthly_gap_attribution.csv", index=False)
    write_json(output_dir / "gap_attribution_summary.json", payload)
    (output_dir / "gap_attribution_report.md").write_text(render_report(payload), encoding="utf-8")
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default="outputs")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = run(repo_path(args.latest_run), repo_path(args.output_dir))
    print(json.dumps({k: payload[k] for k in ["main", "concentrated"] if k in payload}, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
