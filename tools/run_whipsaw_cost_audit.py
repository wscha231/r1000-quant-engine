#!/usr/bin/env python3
"""Audit same-ticker sell-then-rebuy whipsaw costs from broker trades.

This is a research-only diagnostic.  It reads an existing broker-ledger
``trades.csv`` and quantifies cases where the system sold a ticker and later
rebought it at a higher price.  It does not use the result for live ranking,
does not mutate target books, and does not dispatch any workflow.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEFAULT_LATEST_RUN = "outputs"
DEFAULT_OUTPUT_DIR = "outputs/whipsaw_cost_audit"
CASH_TICKERS = {"CASH", "__CASH__"}
SCHEMA_VERSION = "whipsaw-cost-audit-v1"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        out = float(value)
        return out if math.isfinite(out) else default
    except (TypeError, ValueError):
        return default


def clean_ticker(value: Any) -> str:
    return str(value or "").upper().strip()


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, low_memory=False)


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def load_portfolio_metrics(latest_run: Path, portfolio: str) -> tuple[dict[str, Any], str]:
    broker_metrics = read_json(latest_run / "broker_replay" / portfolio / "metrics.json")
    if broker_metrics.get("cagr") is not None or broker_metrics.get("ending_capital_usd") is not None:
        return broker_metrics, str(latest_run / "broker_replay" / portfolio / "metrics.json")
    official = read_json(latest_run / "account_evaluation" / "official_metrics.json")
    portfolio_metrics = ((official.get("portfolios") or {}).get(portfolio) or {}) if official else {}
    if portfolio_metrics:
        return portfolio_metrics, str(latest_run / "account_evaluation" / "official_metrics.json")
    return broker_metrics, str(latest_run / "broker_replay" / portfolio / "metrics.json")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def normalize_trades(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame()
    required = {"ticker", "side", "quantity", "fill_price", "date"}
    missing = required - set(trades.columns)
    if missing:
        raise ValueError(f"trades.csv missing required columns: {sorted(missing)}")
    d = trades.copy()
    d["ticker"] = d["ticker"].map(clean_ticker)
    d["side"] = d["side"].astype(str).str.upper().str.strip()
    d["quantity"] = pd.to_numeric(d["quantity"], errors="coerce").fillna(0.0).abs()
    d["fill_price"] = pd.to_numeric(d["fill_price"], errors="coerce")
    d["fee_usd"] = pd.to_numeric(d.get("fee_usd", 0.0), errors="coerce").fillna(0.0)
    d["date"] = pd.to_datetime(d["date"], errors="coerce").dt.normalize()
    d["signal_date"] = pd.to_datetime(d.get("signal_date", d["date"]), errors="coerce").dt.normalize()
    d = d[d["date"].notna()]
    d = d[(d["ticker"] != "") & (~d["ticker"].isin(CASH_TICKERS))]
    d = d[d["side"].isin({"BUY", "SELL"})]
    d = d[d["quantity"].gt(0) & d["fill_price"].gt(0)]
    return d.sort_values(["ticker", "date", "side"]).reset_index(drop=True)


def whipsaw_events(trades: pd.DataFrame, *, max_rebuy_days: int) -> pd.DataFrame:
    d = normalize_trades(trades)
    rows: list[dict[str, Any]] = []
    if d.empty:
        return pd.DataFrame(rows)
    for ticker, group in d.groupby("ticker", sort=True):
        ordered = group.sort_values(["date", "side"]).reset_index(drop=True)
        sells = ordered[ordered["side"].eq("SELL")]
        buys = ordered[ordered["side"].eq("BUY")]
        for _, sell in sells.iterrows():
            later = buys[buys["date"].gt(sell["date"])]
            if later.empty:
                continue
            buy = later.iloc[0]
            days = int((pd.Timestamp(buy["date"]) - pd.Timestamp(sell["date"])).days)
            if days < 0 or days > int(max_rebuy_days):
                continue
            matched_qty = min(safe_float(sell.get("quantity")), safe_float(buy.get("quantity")))
            sell_price = safe_float(sell.get("fill_price"))
            buy_price = safe_float(buy.get("fill_price"))
            price_return = (buy_price / sell_price - 1.0) if sell_price > 0 else 0.0
            missed_cost = max(0.0, buy_price - sell_price) * matched_qty
            avoided_loss = max(0.0, sell_price - buy_price) * matched_qty
            rows.append(
                {
                    "ticker": ticker,
                    "sell_date": pd.Timestamp(sell["date"]).date().isoformat(),
                    "buy_date": pd.Timestamp(buy["date"]).date().isoformat(),
                    "sell_signal_date": pd.Timestamp(sell.get("signal_date")).date().isoformat() if pd.notna(sell.get("signal_date")) else "",
                    "buy_signal_date": pd.Timestamp(buy.get("signal_date")).date().isoformat() if pd.notna(buy.get("signal_date")) else "",
                    "days_to_rebuy": days,
                    "sell_quantity": safe_float(sell.get("quantity")),
                    "buy_quantity": safe_float(buy.get("quantity")),
                    "matched_quantity": matched_qty,
                    "sell_price": sell_price,
                    "buy_price": buy_price,
                    "price_return_while_out": price_return,
                    "missed_reentry_cost_usd": missed_cost,
                    "avoided_loss_usd": avoided_loss,
                    "sell_fee_usd": safe_float(sell.get("fee_usd")),
                    "buy_fee_usd": safe_float(buy.get("fee_usd")),
                    "sell_reason": str(sell.get("reason") or ""),
                    "buy_reason": str(buy.get("reason") or ""),
                    "whipsaw_positive": bool(missed_cost > 0),
                }
            )
    return pd.DataFrame(rows).sort_values(["missed_reentry_cost_usd", "price_return_while_out"], ascending=[False, False]).reset_index(drop=True)


def summarize(events: pd.DataFrame, *, metrics: dict[str, Any], portfolio: str, max_rebuy_days: int) -> dict[str, Any]:
    ending_equity = safe_float(metrics.get("ending_capital_usd"), 0.0)
    total_cost = float(pd.to_numeric(events.get("missed_reentry_cost_usd", pd.Series(dtype=float)), errors="coerce").fillna(0.0).sum()) if not events.empty else 0.0
    total_avoided = float(pd.to_numeric(events.get("avoided_loss_usd", pd.Series(dtype=float)), errors="coerce").fillna(0.0).sum()) if not events.empty else 0.0
    positive = events[events.get("whipsaw_positive", pd.Series(dtype=bool)).astype(bool)] if not events.empty else pd.DataFrame()
    by_ticker = []
    if not events.empty:
        grouped = events.groupby("ticker", as_index=False).agg(
            event_count=("ticker", "size"),
            missed_reentry_cost_usd=("missed_reentry_cost_usd", "sum"),
            avoided_loss_usd=("avoided_loss_usd", "sum"),
            mean_price_return_while_out=("price_return_while_out", "mean"),
            max_price_return_while_out=("price_return_while_out", "max"),
        )
        grouped = grouped.sort_values("missed_reentry_cost_usd", ascending=False)
        by_ticker = grouped.head(20).to_dict("records")
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_now(),
        "portfolio": portfolio,
        "max_rebuy_days": int(max_rebuy_days),
        "status": "completed",
        "research_only": True,
        "production_activation_allowed": False,
        "event_count": int(len(events)),
        "positive_whipsaw_count": int(len(positive)),
        "negative_or_beneficial_count": int(len(events) - len(positive)),
        "positive_whipsaw_rate": float(len(positive) / len(events)) if len(events) else 0.0,
        "total_missed_reentry_cost_usd": total_cost,
        "total_avoided_loss_usd": total_avoided,
        "net_whipsaw_cost_usd": total_cost - total_avoided,
        "net_whipsaw_cost_pct_of_ending_equity": float((total_cost - total_avoided) / ending_equity) if ending_equity > 0 else None,
        "mean_price_return_while_out": float(pd.to_numeric(events.get("price_return_while_out", pd.Series(dtype=float)), errors="coerce").mean()) if not events.empty else None,
        "median_price_return_while_out": float(pd.to_numeric(events.get("price_return_while_out", pd.Series(dtype=float)), errors="coerce").median()) if not events.empty else None,
        "top_tickers_by_missed_cost": by_ticker,
        "metric_mode": metrics.get("metric_mode") or metrics.get("official_metric_mode", ""),
        "source_broker_cagr": metrics.get("cagr"),
        "source_broker_max_dd": metrics.get("max_dd"),
        "next_action": "design_specific_whipsaw_hold_hook" if total_cost > total_avoided and len(positive) >= 10 else "report_only",
    }


def render_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Whipsaw Cost Audit",
        "",
        "Research-only diagnostic of same-ticker sell-then-rebuy events from broker-ledger trades.",
        "",
        f"- portfolio: `{payload.get('portfolio')}`",
        f"- max_rebuy_days: `{payload.get('max_rebuy_days')}`",
        f"- event_count: `{payload.get('event_count')}`",
        f"- positive_whipsaw_count: `{payload.get('positive_whipsaw_count')}`",
        f"- positive_whipsaw_rate: `{payload.get('positive_whipsaw_rate', 0.0):.2%}`",
        f"- total_missed_reentry_cost_usd: `${payload.get('total_missed_reentry_cost_usd', 0.0):,.2f}`",
        f"- total_avoided_loss_usd: `${payload.get('total_avoided_loss_usd', 0.0):,.2f}`",
        f"- net_whipsaw_cost_usd: `${payload.get('net_whipsaw_cost_usd', 0.0):,.2f}`",
        f"- next_action: `{payload.get('next_action')}`",
        "",
        "## Top Tickers",
        "",
    ]
    for row in payload.get("top_tickers_by_missed_cost", [])[:10]:
        lines.append(
            f"- `{row.get('ticker')}`: events `{row.get('event_count')}`, "
            f"missed `${safe_float(row.get('missed_reentry_cost_usd')):,.2f}`, "
            f"avoided `${safe_float(row.get('avoided_loss_usd')):,.2f}`, "
            f"mean return while out `{safe_float(row.get('mean_price_return_while_out')):.2%}`"
        )
    lines.extend(
        [
            "",
            "## Guardrails",
            "",
            "- This is not a trading signal.",
            "- It uses realized buy/sell paths as an audit label only.",
            "- Any policy hook must be default-OFF, PIT-only, and broker-ledger A/B measured before fullrun.",
        ]
    )
    return "\n".join(lines) + "\n"


def run(args: argparse.Namespace) -> dict[str, Any]:
    latest_run = repo_path(args.latest_run)
    output_dir = repo_path(args.output_dir)
    portfolio = str(args.portfolio).lower().strip()
    trades_path = repo_path(args.trades) if args.trades else latest_run / "broker_replay" / portfolio / "trades.csv"
    trades = read_csv(trades_path)
    metrics, metrics_path = load_portfolio_metrics(latest_run, portfolio)
    events = whipsaw_events(trades, max_rebuy_days=int(args.max_rebuy_days))
    payload = summarize(events, metrics=metrics, portfolio=portfolio, max_rebuy_days=int(args.max_rebuy_days))
    payload["inputs"] = {"trades": str(trades_path), "metrics": str(metrics_path)}
    output_dir.mkdir(parents=True, exist_ok=True)
    events.to_csv(output_dir / "whipsaw_events.csv", index=False)
    write_json(output_dir / "summary.json", payload)
    write_text(output_dir / "report.md", render_report(payload))
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default=DEFAULT_LATEST_RUN)
    parser.add_argument("--trades", default="")
    parser.add_argument("--portfolio", choices=["main", "concentrated"], default="concentrated")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--max-rebuy-days", type=int, default=252)
    return parser.parse_args()


def main() -> None:
    payload = run(parse_args())
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
