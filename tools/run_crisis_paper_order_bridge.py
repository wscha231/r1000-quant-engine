#!/usr/bin/env python3
"""Convert daily crisis paper actions into approval-required order previews.

This bridge is paper-only. It does not place broker orders, does not mutate the
operating target books, and does not override the daily monitor's
auto_trade_allowed=false contract.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.run_account_order_preview import normalize_target, run as run_order_preview  # noqa: E402


PORTFOLIOS = ("main", "concentrated")
ALLOWED_ACTION_TYPES = {"raise_cash", "trim_position", "block_new_buys", "reentry_watch", "no_op"}


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path, low_memory=False)
    except Exception:
        return pd.DataFrame()


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
        return out if pd.notna(out) else default
    except Exception:
        return default


def action_plan(monitor: dict[str, Any]) -> dict[str, Any]:
    actions = [a for a in monitor.get("paper_action_candidates") or [] if str(a.get("action_type")) in ALLOWED_ACTION_TYPES]
    raise_cash_targets = [safe_float(a.get("target_cash_weight"), 0.0) for a in actions if a.get("action_type") == "raise_cash"]
    trim_tickers = {
        str(a.get("ticker") or "").upper().strip(): safe_float(a.get("current_weight"), 0.0)
        for a in actions
        if a.get("action_type") == "trim_position" and str(a.get("ticker") or "").strip()
    }
    return {
        "state": monitor.get("state"),
        "raw_state": monitor.get("raw_state"),
        "auto_trade_allowed": bool(monitor.get("auto_trade_allowed")),
        "paper_actions_only": bool(monitor.get("paper_actions_only", True)),
        "actions": actions,
        "action_types": sorted({str(a.get("action_type")) for a in actions}),
        "target_cash_weight": max(raise_cash_targets) if raise_cash_targets else None,
        "block_new_buys": any(a.get("action_type") == "block_new_buys" for a in actions),
        "trim_tickers": trim_tickers,
    }


def derive_target_book(source: pd.DataFrame, portfolio: str, plan: dict[str, Any]) -> pd.DataFrame:
    target = normalize_target(source, portfolio)
    if target.empty:
        return target
    out = target.copy()
    out["ticker"] = out["ticker"].astype(str).str.upper().str.strip()
    out["target_weight"] = pd.to_numeric(out["target_weight"], errors="coerce").fillna(0.0)
    cash_weight = 0.0
    trim_tickers = plan.get("trim_tickers") or {}
    for ticker, current_weight in trim_tickers.items():
        if not ticker:
            continue
        mask = out["ticker"].eq(ticker)
        if not mask.any():
            continue
        old = float(out.loc[mask, "target_weight"].sum())
        new = min(old, max(0.0, current_weight * 0.50))
        out.loc[mask, "target_weight"] = new
        cash_weight += max(0.0, old - new)
    existing_cash = out["ticker"].eq("CASH")
    requested_cash = plan.get("target_cash_weight")
    if requested_cash is not None:
        requested_cash = max(0.0, min(0.95, safe_float(requested_cash, 0.0)))
        existing_cash_weight = float(out.loc[existing_cash, "target_weight"].sum()) if existing_cash.any() else 0.0
        cash_weight = max(cash_weight, requested_cash, existing_cash_weight)
        stock_sum = float(out.loc[~existing_cash, "target_weight"].sum())
        target_stock = max(0.0, 1.0 - cash_weight)
        if stock_sum > 0:
            out.loc[~existing_cash, "target_weight"] *= target_stock / stock_sum
    if existing_cash.any():
        out.loc[existing_cash, "target_weight"] = max(float(out.loc[existing_cash, "target_weight"].sum()), cash_weight)
    elif cash_weight > 0:
        out = pd.concat([out, pd.DataFrame([{"ticker": "CASH", "target_weight": cash_weight}])], ignore_index=True)
    out["bridge_reason"] = ",".join(plan.get("action_types") or [])
    return out.sort_values("target_weight", ascending=False).reset_index(drop=True)


def held_tickers(account_state: dict[str, Any]) -> set[str]:
    rows = account_state.get("positions") or []
    out: set[str] = set()
    if isinstance(rows, list):
        for row in rows:
            ticker = str((row or {}).get("ticker") or "").upper().strip()
            if ticker and safe_float((row or {}).get("shares"), 0.0) > 0:
                out.add(ticker)
    return out


class PreviewArgs:
    pass


def run_preview_for_portfolio(
    *,
    latest_run: Path,
    price_cache: Path,
    output_dir: Path,
    portfolio: str,
    plan: dict[str, Any],
    cost_bps: float,
) -> dict[str, Any]:
    target_source = latest_run / "reports" / f"operating_{portfolio}_target_book.csv"
    account_state_path = latest_run / "broker_replay" / portfolio / "account_state_latest.json"
    portfolio_out = output_dir / portfolio
    portfolio_out.mkdir(parents=True, exist_ok=True)
    target = derive_target_book(read_csv(target_source), portfolio, plan)
    derived_target = portfolio_out / "paper_action_target_book.csv"
    target.to_csv(derived_target, index=False)

    args = PreviewArgs()
    args.account_state = str(account_state_path)
    args.target = str(derived_target)
    args.price_cache = str(price_cache)
    args.portfolio_kind = portfolio
    args.output_dir = str(portfolio_out / "account_order_preview")
    args.as_of_date = ""
    args.target_date = ""
    args.cost_bps = float(cost_bps)
    args.limit_margin_pct = 0.25
    args.min_trade_usd = 25.0
    args.fractional_shares = False
    payload = run_order_preview(args)

    orders_path = portfolio_out / "account_order_preview" / "orders_preview.csv"
    orders = read_csv(orders_path)
    account = read_json(account_state_path)
    existing = held_tickers(account)
    if not orders.empty:
        orders["auto_trade_allowed"] = False
        orders["paper_only"] = True
        orders["approval_required"] = True
        orders["crisis_state"] = str(plan.get("state") or "")
        orders["paper_action_types"] = ",".join(plan.get("action_types") or [])
        orders["approval_status"] = "pending_user_approval"
        if plan.get("block_new_buys"):
            new_buy = orders["side"].astype(str).str.upper().eq("BUY") & ~orders["ticker"].astype(str).str.upper().isin(existing)
            orders.loc[new_buy, "status"] = "blocked_new_buy_pending_approval"
            orders.loc[new_buy, "approval_status"] = "blocked_new_buy_pending_user_approval"
    orders.to_csv(portfolio_out / "paper_orders_preview.csv", index=False)
    summary = {
        "portfolio": portfolio,
        "status": payload.get("status"),
        "auto_trade_allowed": False,
        "paper_only": True,
        "approval_required": True,
        "paper_action_types": plan.get("action_types") or [],
        "target_cash_weight": plan.get("target_cash_weight"),
        "derived_target": str(derived_target),
        "order_count": int(len(orders)),
        "blocked_new_buy_count": int((orders.get("status", pd.Series(dtype=str)).astype(str) == "blocked_new_buy_pending_approval").sum()) if not orders.empty else 0,
        "preview_metrics": payload,
    }
    write_json(portfolio_out / "summary.json", summary)
    return summary


def render_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Crisis Paper Order Bridge",
        "",
        "- auto_trade_allowed: `false`",
        "- paper_only: `true`",
        "- approval_required: `true`",
        f"- monitor_state: `{payload.get('monitor_state')}`",
        f"- action_types: `{','.join(payload.get('paper_action_types') or [])}`",
        "",
        "| Portfolio | Status | Orders | Blocked New Buys | Target Cash |",
        "| --- | --- | ---: | ---: | ---: |",
    ]
    for row in payload.get("portfolios") or []:
        target_cash = row.get("target_cash_weight")
        target_cash_s = "" if target_cash is None else f"{safe_float(target_cash):.2%}"
        lines.append(
            f"| {row.get('portfolio')} | {row.get('status')} | {row.get('order_count')} | {row.get('blocked_new_buy_count')} | {target_cash_s} |"
        )
    lines.append("")
    return "\n".join(lines)


def run(args: argparse.Namespace) -> dict[str, Any]:
    latest_run = repo_path(args.latest_run)
    price_cache = repo_path(args.price_cache)
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    monitor = read_json(latest_run / "daily_crisis_monitor" / "summary.json")
    plan = action_plan(monitor)
    portfolio_summaries = [
        run_preview_for_portfolio(
            latest_run=latest_run,
            price_cache=price_cache,
            output_dir=output_dir,
            portfolio=portfolio,
            plan=plan,
            cost_bps=float(args.cost_bps),
        )
        for portfolio in PORTFOLIOS
    ]
    payload = {
        "schema_version": "crisis-paper-order-bridge-v1",
        "status": "completed" if monitor else "missing_monitor",
        "auto_trade_allowed": False,
        "paper_only": True,
        "approval_required": True,
        "monitor_state": plan.get("state"),
        "monitor_raw_state": plan.get("raw_state"),
        "paper_action_types": plan.get("action_types") or [],
        "portfolios": portfolio_summaries,
    }
    write_json(output_dir / "summary.json", payload)
    (output_dir / "summary.md").write_text(render_report(payload), encoding="utf-8")
    print(json.dumps({"status": payload["status"], "portfolios": len(portfolio_summaries)}, indent=2))
    return payload


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default="outputs")
    parser.add_argument("--price-cache", default="cache_prices")
    parser.add_argument("--output-dir", default="outputs/crisis_paper_order_bridge")
    parser.add_argument("--cost-bps", type=float, default=25.0)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    run(parse_args(argv))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
