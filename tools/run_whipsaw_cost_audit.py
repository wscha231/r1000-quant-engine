#!/usr/bin/env python3
"""Measure whipsaw sell/rebuy cost from broker-ledger trades.

This research-only sidecar looks for cases where a portfolio sells or trims a
ticker, then buys the same ticker back within a short lookback window at a
higher price. The output is a conservative ceiling on what a future
hold-extension hook could recover; it does not mutate targets, scores, cash, or
live trading.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

SCHEMA_VERSION = "whipsaw-cost-audit-v1"
DEFAULT_OUTPUT_DIR = "outputs/whipsaw_cost_audit"
DEFAULT_LOOKBACK_MONTHS = 3
MATERIAL_DRAG_PP = 3.0
MINOR_DRAG_PP = 1.0
MIN_EVENTS = 5
OOS_START = pd.Timestamp("2024-06-03")
CASH_TICKERS = {"CASH", "__CASH__"}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [json_safe(v) for v in value]
    if isinstance(value, tuple):
        return [json_safe(v) for v in value]
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(json_safe(payload), indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        out = float(value)
        if not math.isfinite(out):
            return default
        return out
    except (TypeError, ValueError):
        return default


def clean_ticker(value: Any) -> str:
    return str(value or "").upper().strip()


def load_trades(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    d = pd.read_csv(path, low_memory=False)
    required = {"ticker", "side", "quantity", "fill_price", "gross_value", "date"}
    if d.empty or not required.issubset(d.columns):
        return pd.DataFrame()
    d = d.copy()
    d["ticker"] = d["ticker"].map(clean_ticker)
    d["side"] = d["side"].astype(str).str.upper().str.strip()
    d["date"] = pd.to_datetime(d["date"], errors="coerce").dt.normalize()
    for col in ["quantity", "fill_price", "gross_value", "fee_usd", "target_weight"]:
        if col in d.columns:
            d[col] = pd.to_numeric(d[col], errors="coerce")
    d = d[d["date"].notna()]
    d = d[~d["ticker"].isin(CASH_TICKERS)]
    d = d[d["quantity"].fillna(0.0).abs() > 0.0]
    d = d[d["fill_price"].fillna(0.0) > 0.0]
    return d.sort_values(["ticker", "date", "side"]).reset_index(drop=True)


def load_equity(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=["date", "equity_usd"])
    d = pd.read_csv(path, low_memory=False)
    if d.empty or "date" not in d.columns or "equity_usd" not in d.columns:
        return pd.DataFrame(columns=["date", "equity_usd"])
    d = d.copy()
    d["date"] = pd.to_datetime(d["date"], errors="coerce").dt.normalize()
    d["equity_usd"] = pd.to_numeric(d["equity_usd"], errors="coerce")
    d = d[d["date"].notna() & d["equity_usd"].notna()]
    return d.sort_values("date").reset_index(drop=True)


def equity_lookup(equity: pd.DataFrame) -> dict[pd.Timestamp, float]:
    if equity.empty:
        return {}
    return {pd.Timestamp(row["date"]).normalize(): float(row["equity_usd"]) for _, row in equity.iterrows()}


def infer_years(equity: pd.DataFrame, default: float = 7.0) -> float:
    if equity.empty:
        return default
    start = pd.to_datetime(equity["date"], errors="coerce").min()
    end = pd.to_datetime(equity["date"], errors="coerce").max()
    if pd.isna(start) or pd.isna(end) or end <= start:
        return default
    return max(float((end - start).days) / 365.25, 1e-9)


def side_value(row: pd.Series, column: str, default: str = "") -> str:
    value = row.get(column, default)
    if value is None:
        return default
    try:
        if pd.isna(value):
            return default
    except TypeError:
        pass
    return str(value)


def match_whipsaw_events(
    trades: pd.DataFrame,
    equity: pd.DataFrame,
    *,
    portfolio: str,
    lookback_months: int,
) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame()
    lookback_days = int(lookback_months * 31)
    eq = equity_lookup(equity)
    rows: list[dict[str, Any]] = []
    pending: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for _, row in trades.sort_values(["date", "ticker"]).iterrows():
        ticker = clean_ticker(row.get("ticker"))
        side = side_value(row, "side").upper()
        date = pd.Timestamp(row.get("date")).normalize()
        qty = abs(safe_float(row.get("quantity")))
        price = safe_float(row.get("fill_price"))
        gross = abs(safe_float(row.get("gross_value"), qty * price))
        if not ticker or qty <= 0.0 or price <= 0.0:
            continue
        if side == "SELL":
            equity_usd = eq.get(date)
            if equity_usd is None or equity_usd <= 0.0:
                # Fall back to a local scale. This keeps tests and partial
                # artifacts usable while making the source explicit.
                equity_usd = gross
                equity_source = "gross_value_fallback"
            else:
                equity_source = "equity_curve"
            pending[ticker].append(
                {
                    "remaining_qty": qty,
                    "original_qty": qty,
                    "sell_date": date,
                    "sell_price": price,
                    "sell_gross_value": gross,
                    "equity_usd_at_sell": float(equity_usd),
                    "equity_source": equity_source,
                    "sell_reason": side_value(row, "reason"),
                    "sell_target_weight": safe_float(row.get("target_weight"), math.nan),
                }
            )
            continue
        if side != "BUY":
            continue

        buy_remaining = qty
        kept: list[dict[str, Any]] = []
        for sell in pending.get(ticker, []):
            if buy_remaining <= 0.0:
                kept.append(sell)
                continue
            gap_days = int((date - sell["sell_date"]).days)
            if gap_days <= 0:
                kept.append(sell)
                continue
            if gap_days > lookback_days:
                continue
            matched_qty = min(float(sell["remaining_qty"]), buy_remaining)
            if matched_qty <= 0.0:
                kept.append(sell)
                continue
            buy_remaining -= matched_qty
            sell["remaining_qty"] = float(sell["remaining_qty"]) - matched_qty
            sell_value = matched_qty * float(sell["sell_price"])
            sold_weight = sell_value / max(float(sell["equity_usd_at_sell"]), 1e-12)
            rebuy_premium = price / max(float(sell["sell_price"]), 1e-12) - 1.0
            rows.append(
                {
                    "portfolio": portfolio,
                    "ticker": ticker,
                    "sell_date": sell["sell_date"].date().isoformat(),
                    "rebuy_date": date.date().isoformat(),
                    "sell_price": float(sell["sell_price"]),
                    "rebuy_price": price,
                    "matched_quantity": matched_qty,
                    "sold_weight": sold_weight,
                    "rebuy_premium": rebuy_premium,
                    "weighted_drag_return": sold_weight * rebuy_premium,
                    "positive_rebuy_premium": bool(rebuy_premium > 0.0),
                    "gap_days": gap_days,
                    "sell_reason": sell.get("sell_reason", ""),
                    "rebuy_reason": side_value(row, "reason"),
                    "sell_target_weight": sell.get("sell_target_weight"),
                    "rebuy_target_weight": safe_float(row.get("target_weight"), math.nan),
                    "equity_usd_at_sell": float(sell["equity_usd_at_sell"]),
                    "equity_source": sell.get("equity_source", ""),
                }
            )
            if sell["remaining_qty"] > 1e-9:
                kept.append(sell)
        pending[ticker] = kept
    return pd.DataFrame(rows)


def verdict(event_count: int, recoverable_ceiling_full_pp: float) -> str:
    if event_count < MIN_EVENTS:
        return "insufficient_events"
    if recoverable_ceiling_full_pp >= MATERIAL_DRAG_PP:
        return "whipsaw_drag_material"
    if recoverable_ceiling_full_pp >= MINOR_DRAG_PP:
        return "whipsaw_drag_minor"
    return "insufficient_events"


def summarize(events: pd.DataFrame, *, portfolio: str, years: float, lookback_months: int) -> dict[str, Any]:
    if events.empty:
        return {
            "schema_version": SCHEMA_VERSION,
            "portfolio": portfolio,
            "metric_mode": "broker_ledger_next_close",
            "lookback_months_for_rebuy": lookback_months,
            "whipsaw_event_count": 0,
            "median_rebuy_premium": 0.0,
            "positive_premium_share": 0.0,
            "estimated_signed_drag_pp_full": 0.0,
            "estimated_drag_pp_full": 0.0,
            "estimated_drag_pp_oos": 0.0,
            "recoverable_ceiling_full_pp": 0.0,
            "years": years,
            "top_events": [],
            "verdict": "insufficient_events",
        }
    d = events.copy()
    d["sell_date_ts"] = pd.to_datetime(d["sell_date"], errors="coerce").dt.normalize()
    weighted = pd.to_numeric(d["weighted_drag_return"], errors="coerce").fillna(0.0)
    positive_weighted = weighted.clip(lower=0.0)
    oos_weighted = weighted[d["sell_date_ts"].ge(OOS_START)].clip(lower=0.0)
    recoverable = float(positive_weighted.sum() / max(years, 1e-12) * 100.0)
    signed = float(weighted.sum() / max(years, 1e-12) * 100.0)
    oos = float(oos_weighted.sum() / max(years, 1e-12) * 100.0)
    top = (
        d.assign(abs_weighted_drag=weighted.abs())
        .sort_values("weighted_drag_return", ascending=False)
        .head(20)
        .drop(columns=["sell_date_ts", "abs_weighted_drag"], errors="ignore")
        .to_dict(orient="records")
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "portfolio": portfolio,
        "metric_mode": "broker_ledger_next_close",
        "lookback_months_for_rebuy": lookback_months,
        "whipsaw_event_count": int(len(d)),
        "median_rebuy_premium": float(pd.to_numeric(d["rebuy_premium"], errors="coerce").median()),
        "positive_premium_share": float(pd.Series(d["positive_rebuy_premium"]).astype(bool).mean()),
        "estimated_signed_drag_pp_full": signed,
        "estimated_drag_pp_full": recoverable,
        "estimated_drag_pp_oos": oos,
        "recoverable_ceiling_full_pp": recoverable,
        "years": years,
        "top_events": top,
        "verdict": verdict(int(len(d)), recoverable),
    }


def build_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Whipsaw Cost Audit",
        "",
        "Research-only estimate of sell-then-rebuy drag from broker-ledger trades.",
        "",
        f"- schema_version: `{payload['schema_version']}`",
        f"- generated_at_utc: `{payload['generated_at_utc']}`",
        f"- latest_run: `{payload['latest_run']}`",
        f"- lookback_months_for_rebuy: `{payload['lookback_months_for_rebuy']}`",
        "",
        "| portfolio | events | positive rebuy share | median rebuy premium | recoverable ceiling pp/yr | signed drag pp/yr | verdict |",
        "| --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for item in payload.get("portfolios", []):
        lines.append(
            "| {portfolio} | {events} | {share:.2%} | {premium:.2%} | {ceiling:.2f} | {signed:.2f} | `{verdict}` |".format(
                portfolio=item.get("portfolio"),
                events=int(item.get("whipsaw_event_count", 0)),
                share=safe_float(item.get("positive_premium_share")),
                premium=safe_float(item.get("median_rebuy_premium")),
                ceiling=safe_float(item.get("recoverable_ceiling_full_pp")),
                signed=safe_float(item.get("estimated_signed_drag_pp_full")),
                verdict=item.get("verdict", ""),
            )
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- `recoverable ceiling` is not a realized improvement. It is the upper bound that a later default-OFF hold hook can try to recover.",
            "- Negative or cheap rebuy events are not counted in the recoverable ceiling, but remain in `estimated_signed_drag_pp_full`.",
            "- Forward returns are not used here; this audit only uses executed broker trade prices and equity weights.",
            "- Production promotion remains blocked unless separate evidence gates pass.",
            "",
            "## Top positive events",
            "",
        ]
    )
    for item in payload.get("portfolios", []):
        lines.append(f"### {item.get('portfolio')}")
        lines.append("")
        lines.append("| ticker | sell date | rebuy date | sell | rebuy | premium | sold weight | gap days |")
        lines.append("| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |")
        for event in item.get("top_events", [])[:10]:
            lines.append(
                "| {ticker} | {sell_date} | {rebuy_date} | {sell_price:.2f} | {rebuy_price:.2f} | {premium:.2%} | {weight:.2%} | {gap} |".format(
                    ticker=event.get("ticker", ""),
                    sell_date=event.get("sell_date", ""),
                    rebuy_date=event.get("rebuy_date", ""),
                    sell_price=safe_float(event.get("sell_price")),
                    rebuy_price=safe_float(event.get("rebuy_price")),
                    premium=safe_float(event.get("rebuy_premium")),
                    weight=safe_float(event.get("sold_weight")),
                    gap=int(safe_float(event.get("gap_days"))),
                )
            )
        lines.append("")
    return "\n".join(lines)


def audit_portfolio(latest_run: Path, portfolio: str, lookback_months: int) -> tuple[pd.DataFrame, dict[str, Any]]:
    broker_dir = latest_run / "broker_replay" / portfolio
    trades = load_trades(broker_dir / "trades.csv")
    equity = load_equity(broker_dir / "equity_curve.csv")
    years = infer_years(equity)
    events = match_whipsaw_events(trades, equity, portfolio=portfolio, lookback_months=lookback_months)
    summary = summarize(events, portfolio=portfolio, years=years, lookback_months=lookback_months)
    summary["trades_source"] = str(broker_dir / "trades.csv")
    summary["equity_curve_source"] = str(broker_dir / "equity_curve.csv")
    return events, summary


def run(args: argparse.Namespace) -> dict[str, Any]:
    latest_run = repo_path(args.latest_run)
    output_dir = repo_path(args.output_dir)
    lookback_months = int(args.lookback_months)
    output_dir.mkdir(parents=True, exist_ok=True)

    portfolio_payloads: list[dict[str, Any]] = []
    for portfolio in ["main", "concentrated"]:
        events, summary = audit_portfolio(latest_run, portfolio, lookback_months)
        if not events.empty:
            events.to_csv(output_dir / f"{portfolio}_events.csv", index=False)
        else:
            pd.DataFrame().to_csv(output_dir / f"{portfolio}_events.csv", index=False)
        write_json(output_dir / f"{portfolio}_summary.json", summary)
        portfolio_payloads.append(summary)

    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_now(),
        "latest_run": str(latest_run),
        "lookback_months_for_rebuy": lookback_months,
        "research_only": True,
        "production_mutation_allowed": False,
        "live_trading_enabled": False,
        "broker_replay_executed": False,
        "portfolios": portfolio_payloads,
        "next_action": (
            "design_default_off_hold_hook"
            if any(item.get("verdict") == "whipsaw_drag_material" for item in portfolio_payloads)
            else "do_not_design_hold_hook_from_whipsaw_alone"
        ),
    }
    write_json(output_dir / "summary.json", payload)
    (output_dir / "report.md").write_text(build_report(payload), encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default="outputs")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--lookback-months", type=int, default=DEFAULT_LOOKBACK_MONTHS)
    args = parser.parse_args()
    payload = run(args)
    print(
        json.dumps(
            json_safe(
                {
                "status": "completed",
                "next_action": payload.get("next_action"),
                "portfolios": [
                    {
                        "portfolio": item.get("portfolio"),
                        "events": item.get("whipsaw_event_count"),
                        "recoverable_ceiling_full_pp": item.get("recoverable_ceiling_full_pp"),
                        "verdict": item.get("verdict"),
                    }
                    for item in payload.get("portfolios", [])
                ],
                }
            ),
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
