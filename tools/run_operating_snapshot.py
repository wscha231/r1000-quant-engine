#!/usr/bin/env python3
"""Build a canonical operating snapshot from account preview artifacts.

This tool does not place orders. It merges the account-ledger preview,
orchestrator unified target, safety audit, and live risk-control status into
one operator-facing snapshot so downstream agents do not confuse raw target
recommendations with the current operating book.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.run_broker_ledger_replay import CASH_TICKERS, repo_path, safe_float


DEFAULT_OUTPUT_DIR = "outputs/operating_snapshot"
PORTFOLIOS = ("main", "concentrated")
MISSING_BROKER_CHECKS = {
    "broker_snapshot_required",
    "broker_snapshot_not_supplied",
}


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def normalize_ticker(value: Any) -> str:
    ticker = str(value or "").upper().strip()
    return "" if ticker in {"", "NAN"} else ticker


def clean_float(value: Any) -> float:
    out = safe_float(value, 0.0)
    return float(out) if math.isfinite(float(out)) else 0.0


def latest_non_empty(values: list[str]) -> str:
    non_empty = sorted({str(v) for v in values if str(v or "").strip()})
    return non_empty[-1] if non_empty else ""


def detect_account_source(preview_metrics: dict[str, dict[str, Any]]) -> tuple[str, str]:
    paths = [str(payload.get("account_state") or "") for payload in preview_metrics.values()]
    if not paths:
        return "missing_account_preview", "No account-ledger preview metrics were found."
    if all("broker_replay" in path.replace("\\", "/") for path in paths if path):
        return (
            "simulated_broker_replay",
            "Current holdings come from broker replay account_state_latest.json, not a live broker account snapshot.",
        )
    return "account_state_file", "Current holdings come from supplied account_state files."


def load_unified_target(latest_run: Path) -> tuple[pd.DataFrame, str, dict[str, Any]]:
    csv_path = latest_run / "orchestrator" / "unified_target_latest.csv"
    json_path = latest_run / "orchestrator" / "unified_target_latest.json"
    frame = read_csv(csv_path)
    payload = read_json(json_path)
    if not frame.empty and "ticker" in frame.columns:
        out = frame.copy()
        out["ticker"] = out["ticker"].map(normalize_ticker)
        weight_col = "target_weight" if "target_weight" in out.columns else "weight"
        if weight_col not in out.columns:
            return pd.DataFrame(), "", payload
        out["target_weight"] = pd.to_numeric(out[weight_col], errors="coerce").fillna(0.0)
        if "row_type" not in out.columns:
            out["row_type"] = out["ticker"].apply(lambda x: "cash" if x in CASH_TICKERS else "equity")
        return out[["ticker", "target_weight", "row_type"]].copy(), str(csv_path), payload

    weights = payload.get("unified_weights") or {}
    rows = [
        {"ticker": normalize_ticker(ticker), "target_weight": clean_float(weight), "row_type": "equity"}
        for ticker, weight in weights.items()
    ]
    rows.append({"ticker": "CASH", "target_weight": clean_float(payload.get("cash_target")), "row_type": "cash"})
    return pd.DataFrame(rows), str(json_path) if payload else "", payload


def load_preview_metrics(latest_run: Path) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for portfolio in PORTFOLIOS:
        payload = read_json(latest_run / "account_ledger_preview" / portfolio / "preview_metrics.json")
        if payload:
            out[portfolio] = payload
    return out


def load_current_positions(latest_run: Path, preview_metrics: dict[str, dict[str, Any]]) -> tuple[pd.DataFrame, float, float]:
    rows: list[pd.DataFrame] = []
    total_equity = 0.0
    total_cash = 0.0
    for portfolio in PORTFOLIOS:
        preview_dir = latest_run / "account_ledger_preview" / portfolio
        metrics = preview_metrics.get(portfolio) or {}
        total_equity += clean_float(metrics.get("equity_usd"))
        total_cash += clean_float(metrics.get("cash_usd"))
        frame = read_csv(preview_dir / "positions_current.csv")
        if frame.empty:
            continue
        frame = frame.copy()
        frame["portfolio"] = portfolio
        frame["ticker"] = frame.get("ticker", pd.Series(dtype=str)).map(normalize_ticker)
        for col in ["shares", "price", "market_value_usd", "cost_basis"]:
            if col not in frame.columns:
                frame[col] = 0.0
            frame[col] = pd.to_numeric(frame[col], errors="coerce").fillna(0.0)
        rows.append(frame)
    current = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()
    if total_equity <= 0.0 and not current.empty:
        total_equity = float(current["market_value_usd"].sum() + total_cash)
    return current, float(total_equity), float(total_cash)


def fallback_preview_target(latest_run: Path, preview_metrics: dict[str, dict[str, Any]], total_equity: float) -> tuple[pd.DataFrame, str]:
    rows: list[dict[str, Any]] = []
    for portfolio in PORTFOLIOS:
        equity = clean_float((preview_metrics.get(portfolio) or {}).get("equity_usd"))
        frame = read_csv(latest_run / "account_ledger_preview" / portfolio / "target_weights.csv")
        if frame.empty or "ticker" not in frame.columns:
            continue
        frame = frame.copy()
        frame["ticker"] = frame["ticker"].map(normalize_ticker)
        if "target_weight" not in frame.columns:
            frame["target_weight"] = 0.0
        frame["target_weight"] = pd.to_numeric(frame["target_weight"], errors="coerce").fillna(0.0)
        for row in frame.to_dict("records"):
            ticker = normalize_ticker(row.get("ticker"))
            if not ticker:
                continue
            target_value = clean_float(row.get("target_weight")) * equity
            rows.append({"ticker": ticker, "target_value_usd": target_value})
    if not rows or total_equity <= 0.0:
        return pd.DataFrame(), ""
    out = pd.DataFrame(rows).groupby("ticker", as_index=False)["target_value_usd"].sum()
    out["target_weight"] = out["target_value_usd"] / total_equity
    out["row_type"] = out["ticker"].apply(lambda x: "cash" if x in CASH_TICKERS else "equity")
    return out[["ticker", "target_weight", "row_type"]], "account_ledger_preview/*/target_weights.csv"


def aggregate_current(current: pd.DataFrame, total_equity: float) -> dict[str, dict[str, Any]]:
    if current.empty:
        return {}
    current = current[current["ticker"].astype(str).str.strip() != ""].copy()
    out: dict[str, dict[str, Any]] = {}
    for ticker, group in current.groupby("ticker"):
        shares = float(group["shares"].sum())
        value = float(group["market_value_usd"].sum())
        nonzero_prices = group["price"].replace(0.0, pd.NA).dropna()
        if abs(shares) > 1e-12:
            price = value / shares
        elif not nonzero_prices.empty:
            price = clean_float(nonzero_prices.iloc[0])
        else:
            price = 0.0
        portfolios = ",".join(sorted(set(group["portfolio"].astype(str))))
        out[str(ticker)] = {
            "current_shares": shares,
            "current_price": price,
            "current_value_usd": value,
            "current_weight": value / total_equity if total_equity > 0.0 else 0.0,
            "portfolio_sources": portfolios,
        }
    return out


def aggregate_target(target: pd.DataFrame) -> dict[str, dict[str, Any]]:
    if target.empty or "ticker" not in target.columns:
        return {}
    frame = target.copy()
    frame["ticker"] = frame["ticker"].map(normalize_ticker)
    if "target_weight" not in frame.columns:
        frame["target_weight"] = 0.0
    frame["target_weight"] = pd.to_numeric(frame["target_weight"], errors="coerce").fillna(0.0)
    if "row_type" not in frame.columns:
        frame["row_type"] = frame["ticker"].apply(lambda x: "cash" if x in CASH_TICKERS else "equity")
    grouped = frame.groupby("ticker", as_index=False).agg({"target_weight": "sum", "row_type": "last"})
    return {
        str(row.ticker): {"target_weight": float(row.target_weight), "row_type": str(row.row_type)}
        for row in grouped.itertuples(index=False)
        if str(row.ticker)
    }


def aggregate_orders(latest_run: Path) -> dict[str, dict[str, Any]]:
    rows: list[pd.DataFrame] = []
    for portfolio in PORTFOLIOS:
        frame = read_csv(latest_run / "account_ledger_preview" / portfolio / "orders_preview.csv")
        if frame.empty:
            continue
        frame = frame.copy()
        frame["portfolio"] = portfolio
        frame["ticker"] = frame.get("ticker", pd.Series(dtype=str)).map(normalize_ticker)
        for col in ["quantity", "gross_value_usd", "trade_value_delta_usd"]:
            if col not in frame.columns:
                frame[col] = 0.0
            frame[col] = pd.to_numeric(frame[col], errors="coerce").fillna(0.0)
        for col in ["side", "status"]:
            if col not in frame.columns:
                frame[col] = ""
            frame[col] = frame[col].astype(str)
        rows.append(frame)
    orders = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()
    if orders.empty:
        return {}
    out: dict[str, dict[str, Any]] = {}
    for ticker, group in orders.groupby("ticker"):
        sides = sorted({str(x).upper() for x in group["side"] if str(x).strip()})
        statuses = sorted({str(x) for x in group["status"] if str(x).strip()})
        qty_delta = 0.0
        signed_gross = 0.0
        for row in group.to_dict("records"):
            side = str(row.get("side", "")).upper()
            sign = 1.0 if side == "BUY" else -1.0 if side == "SELL" else 0.0
            qty_delta += sign * clean_float(row.get("quantity"))
            signed_gross += sign * clean_float(row.get("gross_value_usd"))
        action = "HOLD"
        if len(sides) > 1:
            action = "MIXED_REVIEW"
        elif sides:
            action = sides[0]
        out[str(ticker)] = {
            "suggested_action": action,
            "suggested_quantity_delta": qty_delta,
            "preview_trade_value_delta_usd": signed_gross,
            "preview_order_count": int(len(group)),
            "preview_order_status": ",".join(statuses),
            "order_portfolio_sources": ",".join(sorted(set(group["portfolio"].astype(str)))),
        }
    return out


def load_control_status(latest_run: Path) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    risk = read_json(latest_run / "live_trading_risk_controls" / "risk_controls_summary.json")
    safety = read_json(latest_run / "live_trading_safety" / "safety_audit_summary.json")
    issues: list[dict[str, Any]] = []
    for row in risk.get("issues") or []:
        item = dict(row)
        item["source"] = "live_trading_risk_controls"
        issues.append(item)
    for row in safety.get("issues") or []:
        item = dict(row)
        item["source"] = "live_trading_safety"
        issues.append(item)
    return risk, safety, issues


def approval_status(*, risk: dict[str, Any], safety: dict[str, Any], issues: list[dict[str, Any]]) -> tuple[str, str]:
    check_ids = {str(row.get("check_id") or "") for row in issues}
    account_mode = str(risk.get("account_mode") or "live").lower() if risk else "missing"
    if check_ids & MISSING_BROKER_CHECKS and account_mode != "simulated":
        return "blocked_missing_broker_snapshot", "Live broker/account/open-order snapshot was not reconciled."
    if risk and risk.get("status") != "pass":
        return "blocked_by_risk_controls", "Live trading risk controls did not pass."
    if safety and safety.get("status") != "pass":
        return "blocked_by_safety_audit", "Live trading safety audit did not pass."
    if not risk:
        return "review_missing_risk_controls", "Risk controls summary is missing."
    if not safety:
        return "review_missing_safety_audit", "Safety audit summary is missing."
    if account_mode == "simulated":
        return "simulation_ready_preview_only", "Simulated broker-ledger account mode is active; this is a paper/live-like replay, not a real broker account."
    return "review_ready_preview_only", "Preview artifacts are internally reviewable but still do not place orders."


def load_monster_recommendations(latest_run: Path) -> dict[str, dict[str, Any]]:
    frame = read_csv(latest_run / "monster_recommendations" / "unified_recommendations.csv")
    if frame.empty or "ticker" not in frame.columns:
        return {}
    frame = frame.copy()
    frame["ticker"] = frame["ticker"].map(normalize_ticker)
    out: dict[str, dict[str, Any]] = {}
    for ticker, group in frame.groupby("ticker"):
        actions = sorted({str(x) for x in group.get("monster_recommendation", pd.Series(dtype=str)) if str(x).strip()})
        stages = sorted({str(x) for x in group.get("monster_stage", pd.Series(dtype=str)) if str(x).strip()})
        reasons = sorted({str(x) for x in group.get("monster_reason", pd.Series(dtype=str)) if str(x).strip()})
        portfolios = sorted({str(x) for x in group.get("portfolio", pd.Series(dtype=str)) if str(x).strip()})
        priority = pd.to_numeric(group.get("monster_priority_score", pd.Series(dtype=float)), errors="coerce").fillna(0.0)
        out[str(ticker)] = {
            "monster_recommendation": ",".join(actions),
            "monster_stage": ",".join(stages),
            "monster_reason": "; ".join(reasons[:3]),
            "monster_portfolios": ",".join(portfolios),
            "monster_priority_score": float(priority.max()) if not priority.empty else 0.0,
        }
    return out


def build_snapshot(args: argparse.Namespace) -> dict[str, Any]:
    latest_run = repo_path(args.latest_run)
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    preview_metrics = load_preview_metrics(latest_run)
    current, total_equity, total_cash = load_current_positions(latest_run, preview_metrics)
    account_source, account_source_note = detect_account_source(preview_metrics)
    target, target_source, orchestrator_payload = load_unified_target(latest_run)
    if target.empty:
        target, target_source = fallback_preview_target(latest_run, preview_metrics, total_equity)
    current_map = aggregate_current(current, total_equity)
    target_map = aggregate_target(target)
    order_map = aggregate_orders(latest_run)
    monster_map = load_monster_recommendations(latest_run)
    risk, safety, issues = load_control_status(latest_run)
    approval, approval_note = approval_status(risk=risk, safety=safety, issues=issues)

    as_of_dates = [str((payload or {}).get("as_of_date") or "") for payload in preview_metrics.values()]
    as_of_date = args.as_of_date or latest_non_empty(as_of_dates)
    macro_state = str(orchestrator_payload.get("regime_state") or orchestrator_payload.get("macro_state") or "")
    all_tickers = sorted(set(current_map) | set(target_map) | set(order_map) | set(monster_map))
    if "CASH" not in all_tickers:
        all_tickers.append("CASH")

    rows: list[dict[str, Any]] = []
    for ticker in all_tickers:
        row_type = "cash" if ticker in CASH_TICKERS else str((target_map.get(ticker) or {}).get("row_type") or "equity")
        cur = current_map.get(ticker, {})
        target_info = target_map.get(ticker, {})
        order = order_map.get(ticker, {})
        monster = monster_map.get(ticker, {})
        current_value = clean_float(cur.get("current_value_usd"))
        current_shares = clean_float(cur.get("current_shares"))
        current_price = clean_float(cur.get("current_price"))
        current_weight = clean_float(cur.get("current_weight"))
        if row_type == "cash":
            current_value = total_cash
            current_shares = 0.0
            current_price = 1.0
            current_weight = total_cash / total_equity if total_equity > 0.0 else 0.0
        target_weight = clean_float(target_info.get("target_weight"))
        target_value = target_weight * total_equity
        delta_value = target_value - current_value
        suggested_action = str(order.get("suggested_action") or "HOLD")
        if row_type == "cash":
            if abs(delta_value) <= max(total_equity * 0.0005, 25.0):
                suggested_action = "HOLD"
            elif delta_value > 0:
                suggested_action = "RESERVE_CASH"
            else:
                suggested_action = "DEPLOY_CASH"
        block_reason = approval_note if approval.startswith("blocked") else ""
        if str(order.get("preview_order_status", "")).startswith("blocked"):
            block_reason = "Preview order is blocked: " + str(order.get("preview_order_status"))
        rows.append(
            {
                "as_of_date": as_of_date,
                "account_source": account_source,
                "approval_status": approval,
                "row_type": row_type,
                "ticker": ticker,
                "current_shares": current_shares,
                "current_price": current_price,
                "current_value_usd": current_value,
                "current_weight": current_weight,
                "target_weight": target_weight,
                "target_value_usd": target_value,
                "delta_weight": target_weight - current_weight,
                "delta_value_usd": delta_value,
                "suggested_action": suggested_action,
                "suggested_quantity_delta": clean_float(order.get("suggested_quantity_delta")),
                "preview_trade_value_delta_usd": clean_float(order.get("preview_trade_value_delta_usd")),
                "preview_order_count": int(order.get("preview_order_count") or 0),
                "preview_order_status": str(order.get("preview_order_status") or ""),
                "monster_recommendation": str(monster.get("monster_recommendation") or ""),
                "monster_stage": str(monster.get("monster_stage") or ""),
                "monster_priority_score": clean_float(monster.get("monster_priority_score")),
                "monster_reason": str(monster.get("monster_reason") or ""),
                "portfolio_sources": str(cur.get("portfolio_sources") or order.get("order_portfolio_sources") or ""),
                "source_current": "account_ledger_preview/*/positions_current.csv",
                "source_target": target_source,
                "risk_state": macro_state,
                "block_reason": block_reason,
            }
        )

    frame = pd.DataFrame(rows)
    if not frame.empty:
        frame = frame.sort_values(["row_type", "target_weight", "current_weight"], ascending=[True, False, False])
    csv_path = output_dir / "operating_snapshot_latest.csv"
    frame.to_csv(csv_path, index=False)

    error_count = sum(1 for row in issues if str(row.get("severity")) == "error")
    warning_count = sum(1 for row in issues if str(row.get("severity")) == "warning")
    payload = {
        "status": "blocked" if approval.startswith("blocked") else "simulation" if approval.startswith("simulation") else "review",
        "schema_version": "operating-snapshot-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "latest_run": str(latest_run),
        "as_of_date": as_of_date,
        "account_source": account_source,
        "account_source_note": account_source_note,
        "target_source": target_source,
        "approval_status": approval,
        "approval_note": approval_note,
        "risk_controls_status": risk.get("status", "missing") if risk else "missing",
        "safety_audit_status": safety.get("status", "missing") if safety else "missing",
        "total_equity_usd": float(total_equity),
        "cash_usd": float(total_cash),
        "current_cash_weight": float(total_cash / total_equity) if total_equity > 0.0 else 0.0,
        "target_cash_weight": float((target_map.get("CASH") or {}).get("target_weight") or 0.0),
        "row_count": int(len(frame)),
        "equity_row_count": int((frame.get("row_type", pd.Series(dtype=str)) == "equity").sum()) if not frame.empty else 0,
        "preview_order_count": int(frame.get("preview_order_count", pd.Series(dtype=float)).sum()) if not frame.empty else 0,
        "monster_recommendation_count": int((frame.get("monster_recommendation", pd.Series(dtype=str)).astype(str).str.strip() != "").sum()) if not frame.empty else 0,
        "issue_count": int(len(issues)),
        "error_count": int(error_count),
        "warning_count": int(warning_count),
        "issues": issues,
        "outputs": {
            "csv": str(csv_path),
            "json": str(output_dir / "operating_snapshot_latest.json"),
            "report": str(output_dir / "operating_snapshot_report.md"),
        },
    }
    write_json(output_dir / "operating_snapshot_latest.json", payload)
    (output_dir / "operating_snapshot_report.md").write_text(render_report(payload), encoding="utf-8")
    return payload


def render_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Operating Snapshot",
        "",
        f"- Status: `{payload.get('status')}`",
        f"- Approval: `{payload.get('approval_status')}`",
        f"- Account source: `{payload.get('account_source')}`",
        f"- Target source: `{payload.get('target_source')}`",
        f"- As-of date: `{payload.get('as_of_date')}`",
        f"- Total equity: ${clean_float(payload.get('total_equity_usd')):,.2f}",
        f"- Current cash: {clean_float(payload.get('current_cash_weight')):.2%}",
        f"- Target cash: {clean_float(payload.get('target_cash_weight')):.2%}",
        f"- Preview orders represented: {payload.get('preview_order_count')}",
        "",
        "This file is the canonical operator snapshot. Raw portfolio_latest files are model targets, not account holdings.",
        "",
    ]
    if payload.get("approval_note"):
        lines.extend(["## Approval Note", "", str(payload["approval_note"]), ""])
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default="outputs")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--as-of-date", default="")
    return parser.parse_args()


def main() -> int:
    payload = build_snapshot(parse_args())
    print(json.dumps({"status": payload["status"], "approval_status": payload["approval_status"], "row_count": payload["row_count"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
