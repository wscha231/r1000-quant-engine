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


def truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y"}


def latest_non_empty(values: list[str]) -> str:
    non_empty = sorted({str(v) for v in values if str(v or "").strip()})
    return non_empty[-1] if non_empty else ""


def load_macro_policy_latest(latest_run: Path) -> dict[str, Any]:
    summary = read_json(latest_run / "macro_policy_engine" / "summary.json")
    latest = summary.get("latest") if isinstance(summary, dict) else {}
    return dict(latest) if isinstance(latest, dict) else {}


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


def aggregate_orders_by_portfolio(latest_run: Path) -> dict[tuple[str, str], dict[str, Any]]:
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for portfolio in PORTFOLIOS:
        frame = read_csv(latest_run / "account_ledger_preview" / portfolio / "orders_preview.csv")
        if frame.empty or "ticker" not in frame.columns:
            continue
        frame = frame.copy()
        frame["ticker"] = frame["ticker"].map(normalize_ticker)
        for col in ["quantity", "gross_value_usd"]:
            if col not in frame.columns:
                frame[col] = 0.0
            frame[col] = pd.to_numeric(frame[col], errors="coerce").fillna(0.0)
        for col in ["side", "status"]:
            if col not in frame.columns:
                frame[col] = ""
            frame[col] = frame[col].astype(str)
        for ticker, group in frame.groupby("ticker"):
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
            out[(portfolio, str(ticker))] = {
                "suggested_action": action,
                "suggested_quantity_delta": qty_delta,
                "preview_trade_value_delta_usd": signed_gross,
                "preview_order_count": int(len(group)),
                "preview_order_status": ",".join(statuses),
            }
    return out


def load_portfolio_targets(latest_run: Path) -> dict[tuple[str, str], dict[str, Any]]:
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for portfolio in PORTFOLIOS:
        frame = read_csv(latest_run / "account_ledger_preview" / portfolio / "target_weights.csv")
        if frame.empty or "ticker" not in frame.columns:
            continue
        frame = frame.copy()
        frame["ticker"] = frame["ticker"].map(normalize_ticker)
        if "target_weight" not in frame.columns:
            frame["target_weight"] = 0.0
        frame["target_weight"] = pd.to_numeric(frame["target_weight"], errors="coerce").fillna(0.0)
        grouped = frame.groupby("ticker", as_index=False).agg({"target_weight": "sum"})
        for row in grouped.to_dict("records"):
            ticker = normalize_ticker(row.get("ticker"))
            if ticker:
                out[(portfolio, ticker)] = {"target_portfolio_weight": clean_float(row.get("target_weight"))}
    return out


def load_open_lot_summary(latest_run: Path) -> dict[tuple[str, str], dict[str, Any]]:
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for portfolio in PORTFOLIOS:
        frame = read_csv(latest_run / "broker_trade_journal" / portfolio / "open_positions.csv")
        if frame.empty or "ticker" not in frame.columns:
            continue
        frame = frame.copy()
        frame["ticker"] = frame["ticker"].map(normalize_ticker)
        for col in [
            "quantity_open",
            "entry_price",
            "entry_target_weight",
            "entry_monster_early_score",
            "entry_stale_mega_leader_score",
            "entry_risk_entry_block_score",
        ]:
            if col not in frame.columns:
                frame[col] = 0.0
            frame[col] = pd.to_numeric(frame[col], errors="coerce").fillna(0.0)
        for ticker, group in frame.groupby("ticker"):
            qty = float(group["quantity_open"].sum())
            weighted_entry = 0.0
            if abs(qty) > 1e-12:
                weighted_entry = float((group["quantity_open"] * group["entry_price"]).sum() / qty)
            entry_dates = sorted({str(x) for x in group.get("entry_date", pd.Series(dtype=str)) if str(x).strip()})
            signal_dates = sorted({str(x) for x in group.get("entry_signal_date", pd.Series(dtype=str)) if str(x).strip()})
            reasons = sorted({str(x) for x in group.get("entry_reason", pd.Series(dtype=str)) if str(x).strip()})
            sleeves = sorted({str(x) for x in group.get("entry_sleeve", pd.Series(dtype=str)) if str(x).strip()})
            out[(portfolio, str(ticker))] = {
                "first_entry_date": entry_dates[0] if entry_dates else "",
                "latest_entry_date": entry_dates[-1] if entry_dates else "",
                "first_signal_date": signal_dates[0] if signal_dates else "",
                "latest_signal_date": signal_dates[-1] if signal_dates else "",
                "open_lot_count": int(len(group)),
                "open_lot_quantity": qty,
                "avg_entry_price": weighted_entry,
                "entry_reasons": ",".join(reasons),
                "entry_sleeves": ",".join(sleeves),
                "entry_target_weight_max": float(group["entry_target_weight"].max()) if not group.empty else 0.0,
                "entry_monster_early_score_max": float(group["entry_monster_early_score"].max()) if not group.empty else 0.0,
                "entry_stale_mega_leader_score_max": float(group["entry_stale_mega_leader_score"].max()) if not group.empty else 0.0,
                "entry_risk_entry_block_score_max": float(group["entry_risk_entry_block_score"].max()) if not group.empty else 0.0,
            }
    return out


def load_broker_cash(latest_run: Path) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for portfolio in PORTFOLIOS:
        frame = read_csv(latest_run / "broker_replay" / portfolio / "equity_curve.csv")
        if frame.empty:
            continue
        row = frame.iloc[-1].to_dict()
        out[portfolio] = {
            "as_of_date": str(row.get("date") or ""),
            "cash_usd": clean_float(row.get("cash_usd")),
            "cash_weight": clean_float(row.get("cash_weight")),
            "equity_usd": clean_float(row.get("equity_usd")),
        }
    return out


def holding_days(as_of_date: str, first_entry_date: str) -> int | str:
    if not as_of_date or not first_entry_date:
        return ""
    start = pd.to_datetime(first_entry_date, errors="coerce")
    end = pd.to_datetime(as_of_date, errors="coerce")
    if pd.isna(start) or pd.isna(end):
        return ""
    return int((end - start).days)


def operating_review_decision(preview_action: str, monster_recommendation: str, monster_stage: str) -> tuple[str, str]:
    preview = str(preview_action or "HOLD").upper()
    recommendation = str(monster_recommendation or "").lower()
    stage = str(monster_stage or "").lower()
    if "defend_or_hold_monster" in recommendation:
        if preview == "BUY":
            return "SCALE_OR_HOLD_MONSTER_REVIEW", "Monster bridge says defend/hold and target preview wants more; scale only after gates remain valid."
        return "HOLD_MONSTER_REVIEW", "Monster bridge says defend/hold; do not sell only because a target book rotated."
    if "hold_target" in recommendation and preview == "SELL":
        return "HOLD_OR_TRIM_REVIEW", "Target changed but monster bridge still marks the name as a hold target."
    if "review_trim_or_replace" in recommendation or "review_rotation" in recommendation:
        return "ROTATION_REVIEW", "Candidate should be reviewed for trim or replacement before acting."
    if preview == "BUY":
        if "monster" in stage or "monster" in recommendation:
            return "SCALE_MONSTER_REVIEW", "Potential monster add; scale only after market and risk gates remain valid."
        return "BUY_REVIEW", "Target preview wants more exposure; validate against portfolio and market gates."
    if preview == "SELL":
        return "EXIT_REVIEW", "Target preview wants lower exposure; validate stale-leader, hard-stop, and distribution evidence."
    if preview == "MIXED_REVIEW":
        return "MIXED_REVIEW", "Main and concentrated instructions conflict or offset; review at combined-account level."
    return "HOLD", "No preview order or no material target gap."


def cash_policy_review_decision(
    *,
    current_cash_weight: float,
    target_cash_weight: float,
    macro_policy: dict[str, Any],
) -> tuple[str, str, str]:
    floor = clean_float(macro_policy.get("recommended_cash_floor"))
    risk_state = str(macro_policy.get("macro_risk_state") or "").lower()
    cash_gate = str(macro_policy.get("cash_raise_gate") or "")
    confirmed_raise = truthy(macro_policy.get("confirmed_cash_raise"))
    confirmations = clean_float(macro_policy.get("cash_raise_confirmation_count"))
    gap = float(target_cash_weight) - float(current_cash_weight)
    if abs(gap) <= 0.005:
        return "HOLD", "Combined cash is already close to target.", "cash_close_to_target"
    if gap < 0:
        return "DEPLOY_CASH_REVIEW", "Combined cash is above target; review deploy candidates before acting.", "cash_above_target"
    if target_cash_weight >= floor + 0.10 and not confirmed_raise and confirmations < 2 and risk_state in {"", "green", "recovery"}:
        reason = (
            "Combined cash target is materially above the macro floor without confirmed cash-raise evidence; "
            "review before reserving more cash."
        )
        return "CASH_POLICY_REVIEW", reason, "target_cash_above_macro_floor_without_confirmation"
    if cash_gate:
        return "RESERVE_CASH", f"Combined cash is below target under macro gate `{cash_gate}`.", "below_combined_cash_target"
    return "RESERVE_CASH", "Combined cash is below target.", "below_combined_cash_target"


CURRENT_ONLY_COLUMNS = [
    "as_of_date",
    "snapshot_semantics",
    "portfolio_kind",
    "row_type",
    "ticker",
    "current_shares",
    "current_price",
    "current_value_usd",
    "current_weight",
    "cost_basis",
    "unrealized_pnl_usd",
    "realized_pnl_usd",
    "first_entry_date",
    "latest_entry_date",
    "holding_days",
    "open_lot_count",
    "open_lot_quantity",
    "avg_entry_price",
    "entry_reasons",
    "entry_sleeves",
    "daily_review_action",
    "daily_review_reason",
    "monster_recommendation",
    "monster_stage",
    "monster_priority_score",
    "monster_reason",
    "risk_state",
    "account_source",
    "approval_status",
]


DELTA_REVIEW_COLUMNS = [
    "as_of_date",
    "portfolio_kind",
    "row_type",
    "ticker",
    "current_weight",
    "target_portfolio_weight",
    "target_combined_weight",
    "delta_portfolio_weight",
    "preview_action",
    "review_action",
    "review_reason",
    "review_quantity_delta",
    "review_trade_value_delta_usd",
    "review_order_count",
    "review_order_status",
    "cash_policy_flag",
    "macro_recommended_cash_floor",
    "macro_cash_raise_gate",
    "macro_cash_raise_confirmation_count",
]


def select_existing_columns(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    out = frame.copy() if isinstance(frame, pd.DataFrame) else pd.DataFrame()
    for col in columns:
        if col not in out.columns:
            out[col] = ""
    return out[columns].copy()


def write_current_operating_exports(frame: pd.DataFrame, output_dir: Path) -> dict[str, Any]:
    source = frame.copy() if isinstance(frame, pd.DataFrame) else pd.DataFrame()
    if not source.empty:
        source = source.rename(
            columns={
                "review_action": "daily_review_action",
                "review_reason": "daily_review_reason",
            }
        )
    current = select_existing_columns(source, CURRENT_ONLY_COLUMNS)
    combined_path = output_dir / "current_operating_holdings_latest.csv"
    main_path = output_dir / "current_operating_holdings_main_latest.csv"
    concentrated_path = output_dir / "current_operating_holdings_concentrated_latest.csv"
    current.to_csv(combined_path, index=False)
    current[current["portfolio_kind"].astype(str).eq("main")].to_csv(main_path, index=False)
    current[current["portfolio_kind"].astype(str).eq("concentrated")].to_csv(concentrated_path, index=False)

    deltas = select_existing_columns(frame, DELTA_REVIEW_COLUMNS)
    delta_path = output_dir / "proposed_target_deltas_latest.csv"
    deltas.to_csv(delta_path, index=False)
    return {
        "current_operating_holdings_csv": str(combined_path),
        "current_operating_holdings_main_csv": str(main_path),
        "current_operating_holdings_concentrated_csv": str(concentrated_path),
        "proposed_target_deltas_csv": str(delta_path),
        "current_operating_row_count": int(len(current)),
        "proposed_target_delta_row_count": int(len(deltas)),
    }


def write_current_portfolio_snapshot(
    *,
    latest_run: Path,
    output_dir: Path,
    target_map: dict[str, dict[str, Any]],
    monster_map: dict[str, dict[str, Any]],
    approval: str,
    account_source: str,
    macro_state: str,
    total_equity: float,
    total_cash: float,
    macro_policy: dict[str, Any],
) -> dict[str, Any]:
    portfolio_targets = load_portfolio_targets(latest_run)
    portfolio_orders = aggregate_orders_by_portfolio(latest_run)
    lots = load_open_lot_summary(latest_run)
    cash = load_broker_cash(latest_run)
    rows: list[dict[str, Any]] = []
    portfolio_counts: dict[str, int] = {}
    as_of_dates: list[str] = []
    combined_current_cash_weight = float(total_cash / total_equity) if total_equity > 0.0 else 0.0
    combined_target_cash_weight = clean_float((target_map.get("CASH") or {}).get("target_weight"))
    cash_review_action, cash_review_reason, cash_policy_flag = cash_policy_review_decision(
        current_cash_weight=combined_current_cash_weight,
        target_cash_weight=combined_target_cash_weight,
        macro_policy=macro_policy,
    )

    for portfolio in PORTFOLIOS:
        positions = read_csv(latest_run / "broker_replay" / portfolio / "positions_latest.csv")
        if positions.empty or "ticker" not in positions.columns:
            continue
        positions = positions.copy()
        positions["ticker"] = positions["ticker"].map(normalize_ticker)
        for col in ["shares", "price", "market_value_usd", "weight", "cost_basis", "unrealized_pnl_usd", "realized_pnl_usd"]:
            if col not in positions.columns:
                positions[col] = 0.0
            positions[col] = pd.to_numeric(positions[col], errors="coerce").fillna(0.0)
        portfolio_counts[portfolio] = int(len(positions))
        for row in positions.to_dict("records"):
            ticker = normalize_ticker(row.get("ticker"))
            if not ticker:
                continue
            lot = lots.get((portfolio, ticker), {})
            target = portfolio_targets.get((portfolio, ticker), {})
            order = portfolio_orders.get((portfolio, ticker), {})
            monster = monster_map.get(ticker, {})
            as_of_date = str(row.get("as_of_date") or cash.get(portfolio, {}).get("as_of_date") or "")
            if as_of_date:
                as_of_dates.append(as_of_date)
            target_combined_weight = clean_float((target_map.get(ticker) or {}).get("target_weight"))
            current_weight = clean_float(row.get("weight"))
            target_portfolio_weight = clean_float(target.get("target_portfolio_weight"))
            preview_action = str(order.get("suggested_action") or "HOLD")
            operating_action, operating_reason = operating_review_decision(
                preview_action,
                str(monster.get("monster_recommendation") or ""),
                str(monster.get("monster_stage") or ""),
            )
            rows.append(
                {
                    "as_of_date": as_of_date,
                    "snapshot_semantics": "current_broker_ledger_mark_to_market",
                    "portfolio_kind": portfolio,
                    "row_type": "equity",
                    "ticker": ticker,
                    "current_shares": clean_float(row.get("shares")),
                    "current_price": clean_float(row.get("price")),
                    "current_value_usd": clean_float(row.get("market_value_usd")),
                    "current_weight": current_weight,
                    "cost_basis": clean_float(row.get("cost_basis")),
                    "unrealized_pnl_usd": clean_float(row.get("unrealized_pnl_usd")),
                    "realized_pnl_usd": clean_float(row.get("realized_pnl_usd")),
                    "first_entry_date": str(lot.get("first_entry_date") or ""),
                    "latest_entry_date": str(lot.get("latest_entry_date") or ""),
                    "holding_days": holding_days(as_of_date, str(lot.get("first_entry_date") or "")),
                    "open_lot_count": int(lot.get("open_lot_count") or 0),
                    "open_lot_quantity": clean_float(lot.get("open_lot_quantity")),
                    "avg_entry_price": clean_float(lot.get("avg_entry_price")),
                    "entry_reasons": str(lot.get("entry_reasons") or ""),
                    "entry_sleeves": str(lot.get("entry_sleeves") or ""),
                    "target_portfolio_weight": target_portfolio_weight,
                    "target_combined_weight": target_combined_weight,
                    "delta_portfolio_weight": target_portfolio_weight - current_weight,
                    "preview_action": preview_action,
                    "review_action": operating_action,
                    "review_reason": operating_reason,
                    "review_quantity_delta": clean_float(order.get("suggested_quantity_delta")),
                    "review_trade_value_delta_usd": clean_float(order.get("preview_trade_value_delta_usd")),
                    "review_order_count": int(order.get("preview_order_count") or 0),
                    "review_order_status": str(order.get("preview_order_status") or ""),
                    "monster_recommendation": str(monster.get("monster_recommendation") or ""),
                    "monster_stage": str(monster.get("monster_stage") or ""),
                    "monster_priority_score": clean_float(monster.get("monster_priority_score")),
                    "monster_reason": str(monster.get("monster_reason") or ""),
                    "entry_monster_early_score_max": clean_float(lot.get("entry_monster_early_score_max")),
                    "entry_stale_mega_leader_score_max": clean_float(lot.get("entry_stale_mega_leader_score_max")),
                    "entry_risk_entry_block_score_max": clean_float(lot.get("entry_risk_entry_block_score_max")),
                    "account_source": account_source,
                    "approval_status": approval,
                    "risk_state": macro_state,
                    "combined_current_cash_weight": combined_current_cash_weight,
                    "combined_target_cash_weight": combined_target_cash_weight,
                    "combined_cash_gap_weight": combined_target_cash_weight - combined_current_cash_weight,
                    "macro_recommended_cash_floor": clean_float(macro_policy.get("recommended_cash_floor")),
                    "macro_cash_raise_gate": str(macro_policy.get("cash_raise_gate") or ""),
                    "macro_cash_raise_confirmation_count": clean_float(macro_policy.get("cash_raise_confirmation_count")),
                    "cash_policy_flag": "",
                }
            )

    for portfolio, row in cash.items():
        as_of_date = str(row.get("as_of_date") or "")
        if as_of_date:
            as_of_dates.append(as_of_date)
        rows.append(
            {
                "as_of_date": as_of_date,
                "snapshot_semantics": "current_broker_ledger_mark_to_market",
                "portfolio_kind": portfolio,
                "row_type": "cash",
                "ticker": "CASH",
                "current_shares": 0.0,
                "current_price": 1.0,
                "current_value_usd": clean_float(row.get("cash_usd")),
                "current_weight": clean_float(row.get("cash_weight")),
                "cost_basis": 1.0,
                "unrealized_pnl_usd": 0.0,
                "realized_pnl_usd": 0.0,
                "first_entry_date": "",
                "latest_entry_date": "",
                "holding_days": "",
                "open_lot_count": 0,
                "open_lot_quantity": 0.0,
                "avg_entry_price": 0.0,
                "entry_reasons": "",
                "entry_sleeves": "",
                "target_portfolio_weight": 0.0,
                "target_combined_weight": combined_target_cash_weight,
                "delta_portfolio_weight": "",
                "preview_action": cash_review_action,
                "review_action": cash_review_action,
                "review_reason": cash_review_reason,
                "review_quantity_delta": 0.0,
                "review_trade_value_delta_usd": 0.0,
                "review_order_count": 0,
                "review_order_status": "",
                "monster_recommendation": "",
                "monster_stage": "",
                "monster_priority_score": 0.0,
                "monster_reason": "",
                "entry_monster_early_score_max": 0.0,
                "entry_stale_mega_leader_score_max": 0.0,
                "entry_risk_entry_block_score_max": 0.0,
                "account_source": account_source,
                "approval_status": approval,
                "risk_state": macro_state,
                "combined_current_cash_weight": combined_current_cash_weight,
                "combined_target_cash_weight": combined_target_cash_weight,
                "combined_cash_gap_weight": combined_target_cash_weight - combined_current_cash_weight,
                "macro_recommended_cash_floor": clean_float(macro_policy.get("recommended_cash_floor")),
                "macro_cash_raise_gate": str(macro_policy.get("cash_raise_gate") or ""),
                "macro_cash_raise_confirmation_count": clean_float(macro_policy.get("cash_raise_confirmation_count")),
                "cash_policy_flag": cash_policy_flag,
            }
        )

    frame = pd.DataFrame(rows)
    if not frame.empty:
        frame["_row_type_rank"] = frame["row_type"].map({"equity": 0, "cash": 1}).fillna(2)
        frame = frame.sort_values(["portfolio_kind", "_row_type_rank", "current_weight"], ascending=[True, True, False])
        frame = frame.drop(columns=["_row_type_rank"])
    csv_path = output_dir / "current_portfolio_snapshot_latest.csv"
    frame.to_csv(csv_path, index=False)
    current_export_outputs = write_current_operating_exports(frame, output_dir)
    summary = {
        "status": "completed" if rows else "missing_positions",
        "schema_version": "current-portfolio-snapshot-v2",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "latest_run": str(latest_run),
        "as_of_date": latest_non_empty(as_of_dates),
        "snapshot_semantics": "current_broker_ledger_mark_to_market",
        "primary_user_view": "current_operating_holdings_latest.csv",
        "portfolio_position_counts": portfolio_counts,
        "row_count": int(len(frame)),
        "cash_row_count": int((frame.get("row_type", pd.Series(dtype=str)) == "cash").sum()) if not frame.empty else 0,
        "monster_recommendation_count": int((frame.get("monster_recommendation", pd.Series(dtype=str)).astype(str).str.strip() != "").sum()) if not frame.empty else 0,
        "combined_current_cash_weight": combined_current_cash_weight,
        "combined_target_cash_weight": combined_target_cash_weight,
        "combined_cash_gap_weight": combined_target_cash_weight - combined_current_cash_weight,
        "cash_policy_review_action": cash_review_action,
        "cash_policy_flag": cash_policy_flag,
        "macro_recommended_cash_floor": clean_float(macro_policy.get("recommended_cash_floor")),
        "macro_cash_raise_gate": str(macro_policy.get("cash_raise_gate") or ""),
        "macro_cash_raise_confirmation_count": clean_float(macro_policy.get("cash_raise_confirmation_count")),
        "outputs": {
            "csv": str(csv_path),
            "json": str(output_dir / "current_portfolio_snapshot_summary.json"),
            "report": str(output_dir / "current_portfolio_snapshot_report.md"),
            **current_export_outputs,
        },
        "notes": [
            "This is the current simulated broker-ledger account state marked to the latest available close.",
            "current_operating_holdings_latest.csv is the primary current-only user view.",
            "proposed_target_deltas_latest.csv is the separate recommendation/review delta view.",
            "portfolio_latest.csv and concentrated_portfolio_latest.csv remain target recommendation books, not current holdings snapshots.",
            "Account-ledger preview target_weights are preferred over orchestrator unified target when computing operating cash/target deltas because they match the visible order preview.",
            "Review actions are suggestions from the order preview; this tool does not place orders.",
            "Cash policy fields are combined-account policy context, not duplicated per-portfolio cash targets.",
        ],
    }
    write_json(output_dir / "current_portfolio_snapshot_summary.json", summary)
    (output_dir / "current_portfolio_snapshot_report.md").write_text(render_current_snapshot_report(summary), encoding="utf-8")
    return summary


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
    unified_target, unified_target_source, orchestrator_payload = load_unified_target(latest_run)
    preview_target, preview_target_source = fallback_preview_target(latest_run, preview_metrics, total_equity)
    if not preview_target.empty:
        target = preview_target
        target_source = preview_target_source
        target_precedence = "account_ledger_preview_target_weights"
    elif not unified_target.empty:
        target = unified_target
        target_source = unified_target_source
        target_precedence = "orchestrator_unified_target"
    else:
        target = pd.DataFrame()
        target_source = ""
        target_precedence = "missing"
    current_map = aggregate_current(current, total_equity)
    target_map = aggregate_target(target)
    order_map = aggregate_orders(latest_run)
    monster_map = load_monster_recommendations(latest_run)
    macro_policy = load_macro_policy_latest(latest_run)
    risk, safety, issues = load_control_status(latest_run)
    approval, approval_note = approval_status(risk=risk, safety=safety, issues=issues)

    as_of_dates = [str((payload or {}).get("as_of_date") or "") for payload in preview_metrics.values()]
    as_of_date = args.as_of_date or latest_non_empty(as_of_dates)
    macro_state = str(
        macro_policy.get("macro_risk_state")
        or orchestrator_payload.get("regime_state")
        or orchestrator_payload.get("macro_state")
        or ""
    )
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
    current_snapshot = write_current_portfolio_snapshot(
        latest_run=latest_run,
        output_dir=output_dir,
        target_map=target_map,
        monster_map=monster_map,
        approval=approval,
        account_source=account_source,
        macro_state=macro_state,
        total_equity=total_equity,
        total_cash=total_cash,
        macro_policy=macro_policy,
    )

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
        "target_precedence": target_precedence,
        "orchestrator_target_source": unified_target_source,
        "approval_status": approval,
        "approval_note": approval_note,
        "risk_controls_status": risk.get("status", "missing") if risk else "missing",
        "safety_audit_status": safety.get("status", "missing") if safety else "missing",
        "total_equity_usd": float(total_equity),
        "cash_usd": float(total_cash),
        "current_cash_weight": float(total_cash / total_equity) if total_equity > 0.0 else 0.0,
        "target_cash_weight": float((target_map.get("CASH") or {}).get("target_weight") or 0.0),
        "macro_recommended_cash_floor": clean_float(macro_policy.get("recommended_cash_floor")),
        "macro_cash_raise_gate": str(macro_policy.get("cash_raise_gate") or ""),
        "macro_cash_raise_confirmation_count": clean_float(macro_policy.get("cash_raise_confirmation_count")),
        "cash_policy_review_action": current_snapshot.get("cash_policy_review_action"),
        "cash_policy_flag": current_snapshot.get("cash_policy_flag"),
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
            "current_portfolio_snapshot_csv": str(output_dir / "current_portfolio_snapshot_latest.csv"),
            "current_portfolio_snapshot_json": str(output_dir / "current_portfolio_snapshot_summary.json"),
            "current_portfolio_snapshot_report": str(output_dir / "current_portfolio_snapshot_report.md"),
        },
        "current_portfolio_snapshot": current_snapshot,
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
        f"- Cash policy review: `{payload.get('cash_policy_review_action', '')}`",
        f"- Preview orders represented: {payload.get('preview_order_count')}",
        "",
        "This file is the canonical operator snapshot. Raw portfolio_latest files are model targets, not account holdings.",
        "",
    ]
    if payload.get("approval_note"):
        lines.extend(["## Approval Note", "", str(payload["approval_note"]), ""])
    return "\n".join(lines)


def render_current_snapshot_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Current Portfolio Snapshot",
        "",
        f"- Status: `{payload.get('status')}`",
        f"- As-of date: `{payload.get('as_of_date')}`",
        f"- Semantics: `{payload.get('snapshot_semantics')}`",
        f"- Rows: {payload.get('row_count')}",
        f"- Cash rows: {payload.get('cash_row_count')}",
        f"- Monster recommendation rows: {payload.get('monster_recommendation_count')}",
        f"- Combined current cash: {clean_float(payload.get('combined_current_cash_weight')):.2%}",
        f"- Combined target cash: {clean_float(payload.get('combined_target_cash_weight')):.2%}",
        f"- Cash policy review: `{payload.get('cash_policy_review_action', '')}`",
        f"- Primary user view: `{payload.get('primary_user_view', '')}`",
        "",
        "This file answers what the simulated broker-ledger portfolios currently hold after historical trades and latest close mark-to-market.",
        "It is different from `portfolio_latest.csv` and `concentrated_portfolio_latest.csv`, which are target recommendation books.",
        "Use `proposed_target_deltas_latest.csv` only for review actions and target drift, not as current holdings.",
        "Cash policy fields are combined-account context; they are not separate per-portfolio target cash weights.",
        "",
    ]
    counts = payload.get("portfolio_position_counts") or {}
    if counts:
        lines.extend(["## Portfolio Rows", ""])
        for portfolio, count in sorted(counts.items()):
            lines.append(f"- {portfolio}: {count} equity positions")
        lines.append("")
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
