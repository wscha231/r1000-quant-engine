#!/usr/bin/env python3
"""Create account-ledger order previews from a target portfolio.

This is the bridge between historical broker-ledger replay and paper/live
operation. It consumes an account_state_latest.json file, reads a target
portfolio CSV, marks current holdings with cached prices, and writes a
sell-first/buy-second order preview. It does not place orders.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.run_broker_ledger_replay import CASH_TICKERS, repo_path, safe_float
from tools.run_weekly_evaluation import load_price_series, price_on_or_before


DEFAULT_OUTPUT_DIR = "outputs/account_ledger_preview"


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


def normalize_ticker(value: Any) -> str:
    ticker = str(value or "").upper().strip()
    if not ticker or ticker == "NAN":
        return ""
    return ticker


def normalize_target(frame: pd.DataFrame, portfolio_kind: str, target_date: str = "") -> pd.DataFrame:
    if frame.empty or "ticker" not in frame.columns:
        return pd.DataFrame(columns=["ticker", "target_weight"])
    d = frame.copy()
    if "rebalance_date" in d.columns:
        d["rebalance_date"] = pd.to_datetime(d["rebalance_date"], errors="coerce").dt.normalize()
        if target_date:
            dt = pd.Timestamp(target_date).normalize()
            exact = d[d["rebalance_date"].eq(dt)].copy()
            if not exact.empty:
                d = exact
            else:
                prior = d[d["rebalance_date"].le(dt)].copy()
                d = prior[prior["rebalance_date"].eq(prior["rebalance_date"].max())].copy() if not prior.empty else d
        elif d["rebalance_date"].notna().any():
            d = d[d["rebalance_date"].eq(d["rebalance_date"].max())].copy()
    if portfolio_kind == "concentrated" and "target_stock_names" in d.columns:
        non_cash = d[~d["ticker"].astype(str).str.upper().eq("CASH")].copy()
        counts = non_cash["target_stock_names"].astype(str).str.strip()
        counts = counts[~counts.str.lower().isin({"", "nan", "none"})]
        if not counts.empty and counts.nunique() > 1:
            preferred_n = counts.value_counts().index[0]
            d = d[d["target_stock_names"].astype(str).str.strip().eq(preferred_n)].copy()
    weight_col = "target_weight" if "target_weight" in d.columns else "weight"
    if weight_col not in d.columns:
        weight_col = "proposed_weight" if "proposed_weight" in d.columns else ""
    if not weight_col:
        return pd.DataFrame(columns=["ticker", "target_weight"])
    d["ticker"] = d["ticker"].map(normalize_ticker)
    d["target_weight"] = pd.to_numeric(d[weight_col], errors="coerce").fillna(0.0)
    d = d[(d["ticker"] != "") & (d["target_weight"] > 1e-12)].copy()
    keep = ["ticker", "target_weight"] + [
        col
        for col in ["Name", "sector", "portfolio_sleeve_label", "portfolio_selection_path", "raw_score"]
        if col in d.columns
    ]
    out = d[keep].copy()
    out = out.groupby("ticker", as_index=False).agg(
        {
            "target_weight": "sum",
            **({"Name": "last"} if "Name" in out.columns else {}),
            **({"sector": "last"} if "sector" in out.columns else {}),
            **({"portfolio_sleeve_label": "last"} if "portfolio_sleeve_label" in out.columns else {}),
            **({"portfolio_selection_path": "last"} if "portfolio_selection_path" in out.columns else {}),
            **({"raw_score": "last"} if "raw_score" in out.columns else {}),
        }
    )
    return out.sort_values("target_weight", ascending=False).reset_index(drop=True)


def load_positions(account_state: dict[str, Any]) -> pd.DataFrame:
    rows = account_state.get("positions") or []
    if not isinstance(rows, list):
        rows = []
    out = pd.DataFrame(rows)
    if out.empty:
        return pd.DataFrame(columns=["ticker", "shares", "cost_basis"])
    out["ticker"] = out["ticker"].map(normalize_ticker)
    out["shares"] = pd.to_numeric(out.get("shares", 0.0), errors="coerce").fillna(0.0)
    out["cost_basis"] = pd.to_numeric(out.get("cost_basis", np.nan), errors="coerce")
    return out[(out["ticker"] != "") & (out["shares"].abs() > 1e-12)].copy()


def latest_price(price_cache: Path, ticker: str, as_of_date: pd.Timestamp) -> tuple[pd.Timestamp | None, float | None]:
    px = load_price_series(price_cache, ticker)
    if px.empty:
        return None, None
    actual, value = price_on_or_before(px, as_of_date, "close")
    if actual is None or value is None:
        return None, None
    return pd.Timestamp(actual).normalize(), float(value)


def infer_as_of_date(
    *,
    explicit_as_of_date: str,
    account_state: dict[str, Any],
    positions: pd.DataFrame,
    target: pd.DataFrame,
    price_cache: Path,
) -> pd.Timestamp:
    if explicit_as_of_date:
        return pd.Timestamp(explicit_as_of_date).normalize()
    fallback = pd.Timestamp(account_state.get("as_of_date") or pd.Timestamp.utcnow().date()).normalize()
    tickers: set[str] = set()
    if not positions.empty and "ticker" in positions.columns:
        tickers.update(positions["ticker"].astype(str).str.upper())
    if not target.empty and "ticker" in target.columns:
        tickers.update(target["ticker"].astype(str).str.upper())
    latest_dates: list[pd.Timestamp] = []
    for ticker in sorted(t for t in tickers if t and t not in CASH_TICKERS):
        px = load_price_series(price_cache, ticker)
        if px.empty:
            continue
        latest_dates.append(pd.Timestamp(px.index.max()).normalize())
    if latest_dates:
        return max(latest_dates)
    return fallback


def current_account_view(
    *,
    account_state: dict[str, Any],
    positions: pd.DataFrame,
    price_cache: Path,
    as_of_date: pd.Timestamp,
) -> tuple[pd.DataFrame, float, float]:
    rows: list[dict[str, Any]] = []
    cash = safe_float(account_state.get("cash_usd"), 0.0)
    stock_value = 0.0
    for row in positions.itertuples(index=False):
        ticker = str(row.ticker)
        price_dt, price = latest_price(price_cache, ticker, as_of_date)
        if price is None:
            price = safe_float(getattr(row, "price", np.nan), safe_float(row.cost_basis, 0.0))
        value = float(row.shares) * float(price)
        stock_value += value
        rows.append(
            {
                "ticker": ticker,
                "shares": float(row.shares),
                "price": float(price),
                "price_date": price_dt.date().isoformat() if price_dt is not None else "",
                "market_value_usd": value,
                "cost_basis": safe_float(row.cost_basis, np.nan),
            }
        )
    equity = cash + stock_value
    frame = pd.DataFrame(rows)
    if not frame.empty:
        frame["current_weight"] = frame["market_value_usd"] / max(equity, 1e-12)
    return frame, float(equity), float(cash)


def add_zero_position_target_prices(
    *,
    current: pd.DataFrame,
    target: pd.DataFrame,
    price_cache: Path,
    as_of_date: pd.Timestamp,
) -> pd.DataFrame:
    existing = set(current["ticker"].astype(str)) if not current.empty and "ticker" in current.columns else set()
    rows: list[dict[str, Any]] = []
    for ticker in target.get("ticker", pd.Series(dtype=object)).astype(str).str.upper().unique():
        if ticker in existing or ticker in CASH_TICKERS:
            continue
        price_dt, price = latest_price(price_cache, ticker, as_of_date)
        if price is None or price <= 0:
            continue
        rows.append(
            {
                "ticker": ticker,
                "shares": 0.0,
                "price": float(price),
                "price_date": price_dt.date().isoformat() if price_dt is not None else "",
                "market_value_usd": 0.0,
                "cost_basis": np.nan,
                "current_weight": 0.0,
            }
        )
    if not rows:
        return current
    return pd.concat([current, pd.DataFrame(rows)], ignore_index=True)


def build_orders(
    *,
    current: pd.DataFrame,
    target: pd.DataFrame,
    portfolio_kind: str,
    as_of_date: pd.Timestamp,
    equity: float,
    cash: float,
    cost_bps: float,
    integer_shares: bool,
    min_trade_usd: float,
    limit_margin_pct: float,
) -> pd.DataFrame:
    current_map = {
        str(row.ticker): row
        for row in current.itertuples(index=False)
        if str(row.ticker).upper() not in CASH_TICKERS
    }
    target_map = {
        str(row.ticker): float(row.target_weight)
        for row in target.itertuples(index=False)
        if str(row.ticker).upper() not in CASH_TICKERS
    }
    rows: list[dict[str, Any]] = []
    fee_rate = float(cost_bps) / 10000.0
    for ticker in sorted(set(current_map) | set(target_map)):
        cur = current_map.get(ticker)
        target_weight = float(target_map.get(ticker, 0.0))
        current_shares = float(getattr(cur, "shares", 0.0)) if cur is not None else 0.0
        price = safe_float(getattr(cur, "price", np.nan), np.nan) if cur is not None else np.nan
        if not np.isfinite(price) or price <= 0:
            continue
        current_value = current_shares * price
        target_value = max(0.0, target_weight * equity)
        diff_value = target_value - current_value
        if abs(diff_value) < max(float(min_trade_usd), equity * 0.0005):
            continue
        side = "BUY" if diff_value > 0 else "SELL"
        desired_qty = abs(diff_value) / price
        if integer_shares:
            desired_qty = math.floor(desired_qty)
        if desired_qty <= 0:
            continue
        gross = desired_qty * price
        fee = gross * fee_rate
        limit_px = price * (1.0 + limit_margin_pct / 100.0) if side == "BUY" else price * (1.0 - limit_margin_pct / 100.0)
        rows.append(
            {
                "ticker": ticker,
                "side": side,
                "quantity": float(desired_qty),
                "reference_price": float(price),
                "limit_price": float(limit_px),
                "gross_value_usd": float(gross),
                "estimated_fee_usd": float(fee),
                "cash_impact_usd": float(-(gross + fee) if side == "BUY" else gross - fee),
                "current_shares": current_shares,
                "current_weight": float(current_value / max(equity, 1e-12)),
                "target_weight": target_weight,
                "target_value_usd": float(target_value),
                "current_value_usd": float(current_value),
                "trade_value_delta_usd": float(diff_value),
                "order_type": "limit",
                "time_in_force": "day",
                "reason": "target_rebalance",
            }
        )
    orders = pd.DataFrame(rows)
    if orders.empty:
        return orders
    # Sells first free cash; buys largest dollar value first after sells.
    orders["_sort_side"] = orders["side"].map({"SELL": 0, "BUY": 1}).fillna(2)
    orders = orders.sort_values(["_sort_side", "gross_value_usd"], ascending=[True, False]).drop(columns=["_sort_side"])
    running_cash = float(cash)
    accepted: list[dict[str, Any]] = []
    for row in orders.to_dict("records"):
        if row["side"] == "BUY" and running_cash + row["cash_impact_usd"] < -1e-6:
            affordable_qty = math.floor(max(running_cash, 0.0) / (row["reference_price"] * (1.0 + fee_rate))) if integer_shares else max(running_cash, 0.0) / (row["reference_price"] * (1.0 + fee_rate))
            if affordable_qty <= 0:
                row["status"] = "blocked_insufficient_cash"
                row["quantity"] = 0.0
                row["gross_value_usd"] = 0.0
                row["estimated_fee_usd"] = 0.0
                row["cash_impact_usd"] = 0.0
            else:
                row["status"] = "cash_scaled"
                row["quantity"] = float(affordable_qty)
                row["gross_value_usd"] = float(affordable_qty * row["reference_price"])
                row["estimated_fee_usd"] = float(row["gross_value_usd"] * fee_rate)
                row["cash_impact_usd"] = float(-(row["gross_value_usd"] + row["estimated_fee_usd"]))
        else:
            row["status"] = "ready"
        running_cash += float(row["cash_impact_usd"])
        row["estimated_cash_after_usd"] = float(running_cash)
        accepted.append(row)
    out = pd.DataFrame(accepted)
    out = attach_client_order_ids(out, portfolio_kind=portfolio_kind, as_of_date=as_of_date)
    return out


def build_projected_positions_after_orders(
    *,
    current: pd.DataFrame,
    orders: pd.DataFrame,
    starting_cash: float,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Project account weights after applying the preview orders.

    This is not a fill ledger and does not mutate the historical replay. It is
    a user-facing bridge that answers: if the ready preview orders were filled
    at their reference prices, what would the account roughly look like?
    """
    lots: dict[str, dict[str, float]] = {}
    if not current.empty:
        for row in current.to_dict("records"):
            ticker = normalize_ticker(row.get("ticker"))
            if not ticker or ticker in CASH_TICKERS:
                continue
            price = safe_float(row.get("price"), np.nan)
            if not np.isfinite(price) or price <= 0:
                continue
            lots[ticker] = {
                "shares": safe_float(row.get("shares"), 0.0),
                "price": price,
            }
    projected_cash = float(starting_cash)
    if not orders.empty:
        for row in orders.to_dict("records"):
            status = str(row.get("status") or "")
            qty = safe_float(row.get("quantity"), 0.0)
            if qty <= 0 or status.startswith("blocked"):
                continue
            ticker = normalize_ticker(row.get("ticker"))
            if not ticker or ticker in CASH_TICKERS:
                continue
            price = safe_float(row.get("reference_price"), np.nan)
            if not np.isfinite(price) or price <= 0:
                continue
            lot = lots.setdefault(ticker, {"shares": 0.0, "price": price})
            lot["price"] = price
            side = str(row.get("side") or "").upper()
            if side == "BUY":
                lot["shares"] = safe_float(lot.get("shares"), 0.0) + qty
            elif side == "SELL":
                lot["shares"] = max(0.0, safe_float(lot.get("shares"), 0.0) - qty)
            projected_cash += safe_float(row.get("cash_impact_usd"), 0.0)

    rows: list[dict[str, Any]] = []
    stock_value = 0.0
    for ticker, lot in sorted(lots.items()):
        shares = safe_float(lot.get("shares"), 0.0)
        if shares <= 1e-12:
            continue
        price = safe_float(lot.get("price"), np.nan)
        market_value = shares * price
        stock_value += market_value
        rows.append(
            {
                "row_type": "equity",
                "ticker": ticker,
                "projected_shares": shares,
                "reference_price": price,
                "projected_market_value_usd": market_value,
            }
        )
    projected_equity = stock_value + projected_cash
    if projected_equity > 0:
        for row in rows:
            row["projected_weight"] = safe_float(row.get("projected_market_value_usd"), 0.0) / projected_equity
        rows.append(
            {
                "row_type": "cash",
                "ticker": "CASH",
                "projected_shares": 0.0,
                "reference_price": 1.0,
                "projected_market_value_usd": projected_cash,
                "projected_weight": projected_cash / projected_equity,
            }
        )
    frame = pd.DataFrame(rows)
    if not frame.empty:
        frame = frame.sort_values(["row_type", "projected_weight"], ascending=[False, False]).reset_index(drop=True)
    metrics = {
        "projected_equity_usd": float(projected_equity),
        "projected_cash_usd": float(projected_cash),
        "projected_cash_weight": float(projected_cash / projected_equity) if projected_equity > 0 else np.nan,
        "projected_stock_value_usd": float(stock_value),
        "projected_position_count": int(sum(1 for row in rows if row.get("row_type") == "equity")),
    }
    return frame, metrics


def attach_client_order_ids(orders: pd.DataFrame, *, portfolio_kind: str, as_of_date: pd.Timestamp) -> pd.DataFrame:
    """Attach deterministic idempotency keys to preview orders."""
    if orders.empty:
        return orders
    out = orders.copy()
    as_of = pd.Timestamp(as_of_date).date().isoformat()
    ids: list[str] = []
    keys: list[str] = []
    for row in out.to_dict("records"):
        basis = {
            "schema": "r1000-order-preview-v1",
            "portfolio_kind": str(portfolio_kind),
            "as_of_date": as_of,
            "ticker": str(row.get("ticker", "")).upper().strip(),
            "side": str(row.get("side", "")).upper().strip(),
            "quantity": round(safe_float(row.get("quantity"), 0.0), 8),
            "limit_price": round(safe_float(row.get("limit_price"), 0.0), 6),
            "target_weight": round(safe_float(row.get("target_weight"), 0.0), 8),
            "current_shares": round(safe_float(row.get("current_shares"), 0.0), 8),
            "status": str(row.get("status", "")),
        }
        key = json.dumps(basis, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        ticker = str(row.get("ticker", "")).upper().strip().replace(".", "")
        side = str(row.get("side", "")).upper().strip()[:1]
        prefix = "M" if portfolio_kind == "main" else "C"
        ids.append(f"r1k-{prefix}-{as_of.replace('-', '')}-{side}-{ticker[:8]}-{digest[:12]}")
        keys.append(digest)
    out["client_order_id"] = ids
    out["idempotency_key"] = keys
    return out


def render_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Account Ledger Order Preview",
        "",
        f"- Portfolio: `{payload.get('portfolio_kind')}`",
        f"- Semantics: `{payload.get('preview_semantics')}`",
        f"- Account source: `{payload.get('account_source_kind')}`",
        f"- Target source: `{payload.get('target_source_kind')}`",
        f"- As-of date: `{payload.get('as_of_date')}`",
        f"- Equity: ${safe_float(payload.get('equity_usd')):,.2f}",
        f"- Cash: ${safe_float(payload.get('cash_usd')):,.2f} ({safe_float(payload.get('cash_weight')):.2%})",
        f"- Target cash weight: {safe_float(payload.get('target_cash_weight')):.2%}",
        f"- Projected cash after preview orders: ${safe_float(payload.get('projected_cash_usd')):,.2f} ({safe_float(payload.get('projected_cash_weight')):.2%})",
        f"- Orders: {int(safe_float(payload.get('order_count')))}",
        f"- Buys: ${safe_float(payload.get('buy_gross_usd')):,.2f}",
        f"- Sells: ${safe_float(payload.get('sell_gross_usd')):,.2f}",
        f"- Estimated fees: ${safe_float(payload.get('estimated_fee_usd')):,.2f}",
        "",
        "This is an order preview only. It does not place broker orders.",
        "",
    ]
    return "\n".join(lines)


def run(args: argparse.Namespace) -> dict[str, Any]:
    account_path = repo_path(args.account_state)
    target_path = repo_path(args.target)
    price_cache = repo_path(args.price_cache)
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    account = read_json(account_path)
    if not account:
        payload = {"status": "blocked", "reason": "missing account state", "account_state": str(account_path)}
        (output_dir / "preview_metrics.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return payload
    positions = load_positions(account)
    target = normalize_target(read_csv(target_path), args.portfolio_kind, args.target_date)
    account_source_kind = "simulated_broker_replay" if "broker_replay" in str(account_path).replace("\\", "/") else "account_state_file"
    target_source_kind = "unified_target" if "unified_target" in target_path.name else "sleeve_model_target"
    as_of = infer_as_of_date(
        explicit_as_of_date=args.as_of_date,
        account_state=account,
        positions=positions,
        target=target,
        price_cache=price_cache,
    )
    current, equity, cash = current_account_view(account_state=account, positions=positions, price_cache=price_cache, as_of_date=as_of)
    current = add_zero_position_target_prices(
        current=current,
        target=target,
        price_cache=price_cache,
        as_of_date=as_of,
    )
    orders = build_orders(
        current=current,
        target=target,
        portfolio_kind=args.portfolio_kind,
        as_of_date=as_of,
        equity=equity,
        cash=cash,
        cost_bps=args.cost_bps,
        integer_shares=not bool(args.fractional_shares),
        min_trade_usd=args.min_trade_usd,
        limit_margin_pct=args.limit_margin_pct,
    )
    current.to_csv(output_dir / "positions_current.csv", index=False)
    target.to_csv(output_dir / "target_weights.csv", index=False)
    orders.to_csv(output_dir / "orders_preview.csv", index=False)
    projected, projected_metrics = build_projected_positions_after_orders(
        current=current,
        orders=orders,
        starting_cash=cash,
    )
    projected.to_csv(output_dir / "projected_positions_after_orders.csv", index=False)
    manifest_payload = {
        "schema_version": "account-ledger-preview-order-batch-v1",
        "portfolio_kind": args.portfolio_kind,
        "as_of_date": as_of.date().isoformat(),
        "order_count": int(len(orders)),
        "ready_order_count": int((orders.get("status", pd.Series(dtype=str)) == "ready").sum()) if not orders.empty else 0,
        "client_order_ids": orders.get("client_order_id", pd.Series(dtype=str)).astype(str).tolist() if not orders.empty else [],
    }
    manifest_payload["order_batch_id"] = hashlib.sha256(
        json.dumps(manifest_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    (output_dir / "order_batch_manifest.json").write_text(
        json.dumps(manifest_payload, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )
    buy_gross = float(orders.loc[orders.get("side", pd.Series(dtype=str)).eq("BUY"), "gross_value_usd"].sum()) if not orders.empty else 0.0
    sell_gross = float(orders.loc[orders.get("side", pd.Series(dtype=str)).eq("SELL"), "gross_value_usd"].sum()) if not orders.empty else 0.0
    fees = float(pd.to_numeric(orders.get("estimated_fee_usd", pd.Series(dtype=float)), errors="coerce").fillna(0.0).sum()) if not orders.empty else 0.0
    target_stock_weight = float(pd.to_numeric(target.get("target_weight", pd.Series(dtype=float)), errors="coerce").fillna(0.0).sum()) if not target.empty else 0.0
    target_cash_weight = max(0.0, 1.0 - target_stock_weight)
    if abs(target_cash_weight) < 1e-9:
        target_cash_weight = 0.0
    payload = {
        "status": "completed",
        "schema_version": "account-ledger-preview-v1",
        "portfolio_kind": args.portfolio_kind,
        "preview_semantics": "order_preview_not_operating_snapshot",
        "account_source_kind": account_source_kind,
        "target_source_kind": target_source_kind,
        "account_state": str(account_path),
        "account_state_as_of_date": str(account.get("as_of_date") or ""),
        "target": str(target_path),
        "price_cache": str(price_cache),
        "as_of_date": as_of.date().isoformat(),
        "equity_usd": float(equity),
        "cash_usd": float(cash),
        "cash_weight": float(cash / equity) if equity > 0 else np.nan,
        "target_cash_weight": float(target_cash_weight),
        **projected_metrics,
        "position_count": int(len(current)),
        "target_count": int(len(target[target["ticker"].astype(str).str.upper() != "CASH"])) if not target.empty else 0,
        "order_count": int(len(orders)),
        "buy_count": int((orders.get("side", pd.Series(dtype=str)) == "BUY").sum()) if not orders.empty else 0,
        "sell_count": int((orders.get("side", pd.Series(dtype=str)) == "SELL").sum()) if not orders.empty else 0,
        "buy_gross_usd": buy_gross,
        "sell_gross_usd": sell_gross,
        "estimated_fee_usd": fees,
        "cost_bps_per_side": float(args.cost_bps),
        "integer_shares": not bool(args.fractional_shares),
        "limit_margin_pct": float(args.limit_margin_pct),
        "min_trade_usd": float(args.min_trade_usd),
        "ready_order_count": int((orders.get("status", pd.Series(dtype=str)) == "ready").sum()) if not orders.empty else 0,
        "blocked_order_count": int(orders.get("status", pd.Series(dtype=str)).astype(str).str.startswith("blocked").sum()) if not orders.empty else 0,
        "order_batch_id": manifest_payload["order_batch_id"],
    }
    (output_dir / "preview_metrics.json").write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    (output_dir / "preview_report.md").write_text(render_report(payload), encoding="utf-8")
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--account-state", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--price-cache", default="cache_prices")
    parser.add_argument("--portfolio-kind", choices=["main", "concentrated"], default="main")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--as-of-date", default="")
    parser.add_argument("--target-date", default="")
    parser.add_argument("--cost-bps", type=float, default=25.0)
    parser.add_argument("--limit-margin-pct", type=float, default=0.25)
    parser.add_argument("--min-trade-usd", type=float, default=25.0)
    parser.add_argument("--fractional-shares", action="store_true")
    return parser.parse_args()


def main() -> int:
    payload = run(parse_args())
    print(json.dumps(payload, indent=2, default=str))
    return 0 if payload.get("status") == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
