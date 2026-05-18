#!/usr/bin/env python3
"""Explain concentrated proxy-to-broker conversion gaps.

Research-only sidecar. It compares the best non-production concentrated proxy
candidate from goal search with the official concentrated broker-ledger replay
and decomposes the gap into trade count, fees, cash exposure, and rough exit
timing diagnostics. It intentionally ignores candidate forward labels.
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LATEST_RUN = "outputs"
DEFAULT_OUTPUT_DIR = "outputs/concentrated_proxy_to_broker_reconciliation"


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path, low_memory=False)
    except Exception:
        return pd.DataFrame()


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


def safe_float(value: Any, default: float = math.nan) -> float:
    try:
        if value is None or value == "":
            return default
        out = float(value)
    except Exception:
        return default
    return out if math.isfinite(out) else default


def best_concentrated_proxy(goal_summary: dict[str, Any]) -> dict[str, Any]:
    candidates = []
    for key in ["best_concentrated", "concentrated_candidates"]:
        value = goal_summary.get(key)
        if isinstance(value, dict):
            candidates.append(value)
        elif isinstance(value, list):
            candidates.extend([item for item in value if isinstance(item, dict)])
    proxies = [
        item for item in candidates
        if str(item.get("portfolio", "concentrated")) == "concentrated"
        and not bool(item.get("valid_for_production", False))
        and safe_float(item.get("cagr"), -999.0) > -100.0
    ]
    if not proxies:
        return {}
    return sorted(proxies, key=lambda item: safe_float(item.get("cagr"), -999.0), reverse=True)[0]


def trade_path_summary(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty or "ticker" not in trades.columns:
        return pd.DataFrame()
    d = trades.copy()
    d["ticker"] = d["ticker"].astype(str).str.upper().str.strip()
    d["side"] = d.get("side", "").astype(str).str.upper()
    d["date"] = pd.to_datetime(d.get("date", ""), errors="coerce")
    for col in ["gross_value", "fee_usd", "cash_delta", "quantity"]:
        if col in d.columns:
            d[col] = pd.to_numeric(d[col], errors="coerce").fillna(0.0)
        else:
            d[col] = 0.0
    rows: list[dict[str, Any]] = []
    for ticker, group in d[d["ticker"].ne("")].groupby("ticker", sort=False):
        buys = group[group["side"].eq("BUY")]
        sells = group[group["side"].eq("SELL")]
        rows.append(
            {
                "ticker": ticker,
                "buy_count": int(len(buys)),
                "sell_count": int(len(sells)),
                "first_buy_date": pd.Timestamp(buys["date"].min()).date().isoformat() if not buys.empty and buys["date"].notna().any() else "",
                "last_sell_date": pd.Timestamp(sells["date"].max()).date().isoformat() if not sells.empty and sells["date"].notna().any() else "",
                "gross_buy_usd": float(buys["gross_value"].sum()),
                "gross_sell_usd": float(sells["gross_value"].sum()),
                "fees_usd": float(group["fee_usd"].sum()),
                "net_cash_delta_usd": float(group["cash_delta"].sum()),
                "open_status": "open_or_partial" if float(group["quantity"].where(group["side"].eq("BUY"), -group["quantity"]).sum()) > 0 else "closed_or_flat",
            }
        )
    return pd.DataFrame(rows).sort_values("gross_buy_usd", ascending=False)


def exit_timing_diff(latest_run: Path, trades: pd.DataFrame) -> pd.DataFrame:
    action_paths = [
        latest_run / "broker_position_risk_replay" / "concentrated" / "risk_actions.csv",
        latest_run / "broker_execution_policy_replay" / "concentrated" / "risk_actions.csv",
        latest_run / "concentrated_position_risk_replay" / "defensive_holdings.csv",
    ]
    actions = pd.DataFrame()
    for path in action_paths:
        candidate = read_csv(path)
        if not candidate.empty and "ticker" in candidate.columns:
            actions = candidate
            break
    if actions.empty or trades.empty:
        return pd.DataFrame(columns=["ticker", "action_date", "first_sell_after_action", "sell_lag_days", "action_source"])
    a = actions.copy()
    a["ticker"] = a["ticker"].astype(str).str.upper().str.strip()
    date_col = next((col for col in ["date", "action_date", "rebalance_date"] if col in a.columns), "")
    if not date_col:
        return pd.DataFrame(columns=["ticker", "action_date", "first_sell_after_action", "sell_lag_days", "action_source"])
    a["action_date"] = pd.to_datetime(a[date_col], errors="coerce").dt.normalize()
    t = trades.copy()
    t["ticker"] = t["ticker"].astype(str).str.upper().str.strip()
    t["side"] = t.get("side", "").astype(str).str.upper()
    t["date"] = pd.to_datetime(t.get("date", ""), errors="coerce").dt.normalize()
    sells = t[t["side"].eq("SELL") & t["date"].notna()].copy()
    rows: list[dict[str, Any]] = []
    for row in a[a["action_date"].notna()].itertuples(index=False):
        ticker = str(getattr(row, "ticker"))
        action_dt = pd.Timestamp(getattr(row, "action_date"))
        future = sells[sells["ticker"].eq(ticker) & sells["date"].ge(action_dt)]
        first_sell = pd.NaT if future.empty else future["date"].min()
        rows.append(
            {
                "ticker": ticker,
                "action_date": action_dt.date().isoformat(),
                "first_sell_after_action": pd.Timestamp(first_sell).date().isoformat() if pd.notna(first_sell) else "",
                "sell_lag_days": int((pd.Timestamp(first_sell) - action_dt).days) if pd.notna(first_sell) else math.nan,
                "action_source": str(action_paths[0]),
            }
        )
    return pd.DataFrame(rows)


def cash_drag_windows(equity: pd.DataFrame, threshold: float = 0.15) -> pd.DataFrame:
    if equity.empty or "date" not in equity.columns:
        return pd.DataFrame()
    d = equity.copy()
    d["date"] = pd.to_datetime(d["date"], errors="coerce").dt.normalize()
    if "cash_weight" not in d.columns:
        if {"cash_usd", "equity_usd"}.issubset(d.columns):
            d["cash_weight"] = pd.to_numeric(d["cash_usd"], errors="coerce") / pd.to_numeric(d["equity_usd"], errors="coerce")
        else:
            return pd.DataFrame()
    d["cash_weight"] = pd.to_numeric(d["cash_weight"], errors="coerce")
    d["equity_usd"] = pd.to_numeric(d.get("equity_usd", math.nan), errors="coerce")
    d = d[d["date"].notna() & d["cash_weight"].ge(threshold)].copy()
    if d.empty:
        return pd.DataFrame(columns=["date", "cash_weight", "equity_usd"])
    return d[["date", "cash_weight", "equity_usd"]].assign(date=lambda x: x["date"].dt.date.astype(str)).head(250)


def render_report(summary: dict[str, Any]) -> str:
    proxy = summary.get("proxy_candidate", {}) or {}
    official = summary.get("official_metrics", {}) or {}
    return "\n".join(
        [
            "# Concentrated Proxy-to-Broker Reconciliation",
            "",
            "Research-only conversion-gap report. Proxy candidates remain non-production evidence.",
            "",
            f"- status: `{summary.get('status')}`",
            f"- proxy candidate: `{proxy.get('candidate_id', '')}`",
            f"- proxy CAGR: {safe_float(proxy.get('cagr')):.2%}" if math.isfinite(safe_float(proxy.get("cagr"))) else "- proxy CAGR: n/a",
            f"- official CAGR: {safe_float(official.get('cagr')):.2%}" if math.isfinite(safe_float(official.get("cagr"))) else "- official CAGR: n/a",
            f"- CAGR gap: {safe_float(summary.get('cagr_gap')):.2%}" if math.isfinite(safe_float(summary.get("cagr_gap"))) else "- CAGR gap: n/a",
            f"- official MaxDD: {safe_float(official.get('max_dd')):.2%}" if math.isfinite(safe_float(official.get("max_dd"))) else "- official MaxDD: n/a",
            f"- trade count: {official.get('trade_count')}",
            f"- fees: ${safe_float(official.get('total_fees_usd'), 0.0):,.0f}",
            "",
            "## Outputs",
            "",
            "- `conversion_gap_summary.json`",
            "- `trade_path_diff.csv`",
            "- `exit_timing_diff.csv`",
            "- `missed_upside_after_cash.csv`",
            "",
        ]
    )


def run(latest_run: str | Path = DEFAULT_LATEST_RUN, output_dir: str | Path = DEFAULT_OUTPUT_DIR) -> dict[str, Any]:
    latest = repo_path(latest_run)
    out = repo_path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    goal = read_json(latest / "portfolio_goal_search" / "goal_search_summary.json")
    proxy = best_concentrated_proxy(goal)
    official = read_json(latest / "broker_replay" / "concentrated" / "metrics.json")
    trades = read_csv(latest / "broker_replay" / "concentrated" / "trades.csv")
    equity = read_csv(latest / "broker_replay" / "concentrated" / "equity_curve.csv")

    trade_path = trade_path_summary(trades)
    exits = exit_timing_diff(latest, trades)
    cash_windows = cash_drag_windows(equity)
    trade_path.to_csv(out / "trade_path_diff.csv", index=False)
    exits.to_csv(out / "exit_timing_diff.csv", index=False)
    cash_windows.to_csv(out / "missed_upside_after_cash.csv", index=False)

    proxy_cagr = safe_float(proxy.get("cagr"))
    official_cagr = safe_float(official.get("cagr"))
    proxy_dd = safe_float(proxy.get("max_dd"))
    official_dd = safe_float(official.get("max_dd"))
    status = "completed" if proxy and official else "blocked_missing_proxy_or_broker_metrics"
    summary = {
        "status": status,
        "schema_version": "concentrated-proxy-to-broker-reconciliation-v1",
        "research_only": True,
        "production_activation_allowed": False,
        "uses_forward_labels_for_selection": False,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "latest_run": str(latest),
        "proxy_candidate": {
            "candidate_id": proxy.get("candidate_id", ""),
            "source": proxy.get("source", ""),
            "cagr": proxy_cagr,
            "max_dd": proxy_dd,
            "sharpe": safe_float(proxy.get("sharpe")),
            "valid_for_production": bool(proxy.get("valid_for_production", False)),
        },
        "official_metrics": {
            "candidate_id": "concentrated_broker_ledger_replay",
            "cagr": official_cagr,
            "max_dd": official_dd,
            "sharpe": safe_float(official.get("sharpe")),
            "trade_count": safe_float(official.get("trade_count")),
            "total_fees_usd": safe_float(official.get("total_fees_usd")),
            "avg_cash_weight": safe_float(official.get("avg_cash_weight")),
            "valid_for_production": bool(official.get("valid_for_production", False)),
        },
        "cagr_gap": proxy_cagr - official_cagr if math.isfinite(proxy_cagr) and math.isfinite(official_cagr) else math.nan,
        "max_dd_gap": proxy_dd - official_dd if math.isfinite(proxy_dd) and math.isfinite(official_dd) else math.nan,
        "trade_path_rows": int(len(trade_path)),
        "exit_timing_rows": int(len(exits)),
        "high_cash_rows": int(len(cash_windows)),
        "source_files": {
            "goal_search_summary": str(latest / "portfolio_goal_search" / "goal_search_summary.json"),
            "broker_metrics": str(latest / "broker_replay" / "concentrated" / "metrics.json"),
            "broker_trades": str(latest / "broker_replay" / "concentrated" / "trades.csv"),
            "broker_equity_curve": str(latest / "broker_replay" / "concentrated" / "equity_curve.csv"),
        },
    }
    write_json(out / "conversion_gap_summary.json", summary)
    (out / "report.md").write_text(render_report(summary), encoding="utf-8")
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default=DEFAULT_LATEST_RUN)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = run(args.latest_run, args.output_dir)
    print(json.dumps({"status": payload.get("status"), "cagr_gap": payload.get("cagr_gap")}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
