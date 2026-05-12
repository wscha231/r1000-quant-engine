#!/usr/bin/env python3
"""Build user-facing portfolio reports from targets and broker-ledger holdings.

This sidecar deliberately separates two concepts that were previously easy to
confuse:

- recommendation files: current target weights from the model, i.e. what the
  system would like to buy/hold from the latest close;
- current operating files: the simulated account's actual marked-to-market
  holdings after historical fills, cash, and share drift.
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

from tools.run_weekly_evaluation import load_price_series, price_on_or_before


PORTFOLIO_SPECS = {
    "main": {
        "target_file": "portfolio_latest.csv",
        "label": "Main",
    },
    "concentrated": {
        "target_file": "concentrated_portfolio_latest.csv",
        "label": "Concentrated",
    },
}

HORIZONS = [
    ("1M", pd.DateOffset(months=1)),
    ("3M", pd.DateOffset(months=3)),
    ("6M", pd.DateOffset(months=6)),
    ("1Y", pd.DateOffset(years=1)),
    ("2Y", pd.DateOffset(years=2)),
    ("3Y", pd.DateOffset(years=3)),
    ("5Y", pd.DateOffset(years=5)),
    ("FULL", None),
]

CASH_TICKERS = {"CASH", "__CASH__"}
DEFAULT_COLORS = [
    "#2563eb",
    "#16a34a",
    "#dc2626",
    "#9333ea",
    "#ea580c",
    "#0891b2",
    "#4f46e5",
    "#65a30d",
    "#be123c",
    "#0f766e",
    "#7c3aed",
    "#ca8a04",
]


def repo_path(path_like: str | Path) -> Path:
    path = Path(path_like)
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


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def clean_ticker(value: Any) -> str:
    ticker = str(value or "").upper().strip()
    return "" if ticker in {"", "NAN", "NONE"} else ticker


def clean_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        out = float(value)
        return out if math.isfinite(out) else default
    except (TypeError, ValueError):
        return default


def first_existing(row: dict[str, Any], names: list[str], default: Any = "") -> Any:
    for name in names:
        value = row.get(name)
        if value is None:
            continue
        if isinstance(value, float) and math.isnan(value):
            continue
        text = str(value).strip()
        if text and text.lower() != "nan":
            return value
    return default


def latest_as_of_date(latest_run: Path) -> str:
    candidates: list[str] = []
    for portfolio in PORTFOLIO_SPECS:
        state = read_json(latest_run / "broker_replay" / portfolio / "account_state_latest.json")
        if state.get("as_of_date"):
            candidates.append(str(state["as_of_date"]))
        metrics = read_json(latest_run / "broker_replay" / portfolio / "metrics.json")
        if metrics.get("end_date"):
            candidates.append(str(metrics["end_date"]))
        eq = read_csv(latest_run / "broker_replay" / portfolio / "equity_curve.csv")
        if not eq.empty and "date" in eq.columns:
            candidates.append(str(eq["date"].iloc[-1]))
    parsed = pd.to_datetime(pd.Series(candidates), errors="coerce").dropna()
    if parsed.empty:
        return ""
    return pd.Timestamp(parsed.max()).date().isoformat()


def latest_close_from_cache(price_cache: Path, ticker: str, as_of_date: str) -> tuple[float, str]:
    if not price_cache.exists():
        return np.nan, ""
    px = load_price_series(price_cache, ticker)
    if px.empty:
        return np.nan, ""
    if as_of_date:
        dt, value = price_on_or_before(px, as_of_date, "close")
    else:
        dt, value = pd.Timestamp(px.index.max()), clean_float(px["close"].iloc[-1], np.nan)
    if dt is None or value is None or not math.isfinite(float(value)) or float(value) <= 0:
        return np.nan, ""
    return float(value), pd.Timestamp(dt).date().isoformat()


def date_diff_days(start: Any, end: Any) -> int | None:
    a = pd.to_datetime(start, errors="coerce")
    b = pd.to_datetime(end, errors="coerce")
    if pd.isna(a) or pd.isna(b):
        return None
    return int((pd.Timestamp(b).normalize() - pd.Timestamp(a).normalize()).days)


def last_trade_date(latest_run: Path, portfolio: str) -> str:
    trades = read_csv(latest_run / "broker_replay" / portfolio / "trades.csv")
    if trades.empty or "date" not in trades.columns:
        return ""
    dates = pd.to_datetime(trades["date"], errors="coerce").dropna()
    if dates.empty:
        return ""
    return pd.Timestamp(dates.max()).date().isoformat()


def load_order_preview(latest_run: Path, portfolio: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    preview = read_csv(latest_run / "account_ledger_preview" / portfolio / "orders_preview.csv")
    metrics = read_json(latest_run / "account_ledger_preview" / portfolio / "preview_metrics.json")
    if preview.empty or "ticker" not in preview.columns:
        return pd.DataFrame(), metrics
    d = preview.copy()
    d["ticker"] = d["ticker"].map(clean_ticker)
    for col in [
        "quantity",
        "current_weight",
        "target_weight",
        "target_value_usd",
        "current_value_usd",
        "trade_value_delta_usd",
        "estimated_cash_after_usd",
    ]:
        if col in d.columns:
            d[col] = pd.to_numeric(d[col], errors="coerce")
    return d[d["ticker"].ne("")].copy(), metrics


def load_projected_after_order_weights(latest_run: Path, portfolio: str) -> dict[str, float]:
    frame = read_csv(latest_run / "account_ledger_preview" / portfolio / "projected_positions_after_orders.csv")
    if frame.empty or "ticker" not in frame.columns or "projected_weight" not in frame.columns:
        return {}
    d = frame.copy()
    d["ticker"] = d["ticker"].map(clean_ticker)
    d["projected_weight"] = pd.to_numeric(d["projected_weight"], errors="coerce").fillna(0.0)
    return {str(row.ticker): float(row.projected_weight) for row in d.itertuples(index=False) if str(row.ticker)}


def order_by_ticker(order_preview: pd.DataFrame) -> dict[str, dict[str, Any]]:
    if order_preview.empty or "ticker" not in order_preview.columns:
        return {}
    return {clean_ticker(row.get("ticker")): row for row in order_preview.to_dict("records")}


def compact_logic(row: dict[str, Any], portfolio: str) -> str:
    parts: list[str] = []
    if portfolio == "main":
        for col in [
            "portfolio_sleeve_label",
            "portfolio_selection_path",
            "dominant_archetype_label",
            "portfolio_defensive_rotation_action",
        ]:
            value = str(row.get(col, "") or "").strip()
            if value and value.lower() != "nan":
                parts.append(f"{col}={value}")
    else:
        for col in [
            "concentrated_selection_source",
            "concentrated_preferred_sleeve",
            "portfolio_sleeve_label",
            "portfolio_defensive_rotation_action",
            "theme_holding_profile_primary",
        ]:
            value = str(row.get(col, "") or "").strip()
            if value and value.lower() != "nan":
                parts.append(f"{col}={value}")
    if not parts:
        score = clean_float(row.get("score_total", row.get("score", row.get("concentrated_score", 0.0))))
        parts.append(f"model_score={score:.3f}")
    return "; ".join(parts[:5])


def normalize_recommendations(latest_run: Path, portfolio: str, as_of_date: str, price_cache: Path) -> pd.DataFrame:
    spec = PORTFOLIO_SPECS[portfolio]
    raw = read_csv(latest_run / spec["target_file"])
    if raw.empty or "ticker" not in raw.columns:
        return pd.DataFrame()
    order_preview, preview_metrics = load_order_preview(latest_run, portfolio)
    orders = order_by_ticker(order_preview)
    projected_weights = load_projected_after_order_weights(latest_run, portfolio)
    account_cash_weight = clean_float(preview_metrics.get("cash_weight"), np.nan)
    projected_cash_weight = clean_float(preview_metrics.get("projected_cash_weight"), np.nan)
    recommendation_date = str(preview_metrics.get("as_of_date") or as_of_date)
    d = raw.copy()
    d["ticker"] = d["ticker"].map(clean_ticker)
    weight_col = "weight" if "weight" in d.columns else "target_weight"
    if weight_col not in d.columns:
        d["weight"] = 0.0
    else:
        d["weight"] = pd.to_numeric(d[weight_col], errors="coerce").fillna(0.0)
    d = d[(d["ticker"] != "") & (~d["ticker"].isin(CASH_TICKERS)) & (d["weight"] > 1e-12)].copy()
    rows: list[dict[str, Any]] = []
    for i, row in enumerate(d.sort_values("weight", ascending=False).to_dict("records"), start=1):
        order = orders.get(clean_ticker(row.get("ticker")), {})
        cache_price, cache_price_date = latest_close_from_cache(price_cache, row["ticker"], as_of_date)
        fallback_price = clean_float(
            first_existing(
                row,
                ["reference_price", "current_price_live", "px", "entry_price", "open_px"],
                0.0,
            )
        )
        price = cache_price if math.isfinite(cache_price) and cache_price > 0 else fallback_price
        target_value = clean_float(row.get("weight")) * 100000.0
        est_shares = math.floor(target_value / price) if price > 0 else 0
        rows.append(
            {
                "recommendation_date": recommendation_date,
                "as_of_date": as_of_date,
                "recommended_next_review_date": first_existing(row, ["recommended_next_run_date", "next_scheduled_rebalance_date"], ""),
                "recommendation_semantics": "latest_close_target_recommendation_not_yet_filled",
                "portfolio_kind": portfolio,
                "rank": i,
                "ticker": row["ticker"],
                "company_name": first_existing(row, ["Name", "name", "company_name"], ""),
                "sector": first_existing(row, ["sector", "sage_sector"], ""),
                "recommended_weight": clean_float(row.get("weight")),
                "current_account_weight": clean_float(order.get("current_weight"), 0.0),
                "projected_account_weight_after_orders": projected_weights.get(row["ticker"], np.nan),
                "trade_action_from_current": str(order.get("side") or ("HOLD" if clean_float(order.get("current_weight"), 0.0) > 0 else "BUY")),
                "trade_value_delta_usd": clean_float(order.get("trade_value_delta_usd"), 0.0),
                "estimated_order_quantity": clean_float(order.get("quantity"), 0.0),
                "target_value_per_100k_usd": target_value,
                "reference_price": price if price > 0 else np.nan,
                "reference_price_date": cache_price_date or as_of_date,
                "reference_price_source": "price_cache_latest_close" if cache_price_date else "target_file_fallback",
                "estimated_shares_per_100k": est_shares,
                "suggested_action": "BUY_OR_HOLD_TO_TARGET",
                "buy_logic": compact_logic(row, portfolio),
                "score": clean_float(row.get("score_total", row.get("score", row.get("concentrated_score", 0.0)))),
                "monster_early_score": clean_float(row.get("portfolio_monster_early_score", row.get("entry_monster_early_score", 0.0))),
                "stale_leader_score": clean_float(row.get("portfolio_stale_mega_leader_score", row.get("entry_stale_mega_leader_score", 0.0))),
                "risk_entry_block_score": clean_float(row.get("portfolio_risk_entry_block_score", row.get("entry_risk_entry_block_score", 0.0))),
            }
        )
    out = pd.DataFrame(rows)
    stock_sum = float(out["recommended_weight"].sum()) if not out.empty else 0.0
    cash_weight = max(0.0, 1.0 - stock_sum)
    if abs(cash_weight) < 1e-9:
        cash_weight = 0.0
    out = pd.concat(
        [
            out,
            pd.DataFrame(
                [
                    {
                        "recommendation_date": recommendation_date,
                        "as_of_date": as_of_date,
                        "recommended_next_review_date": "",
                        "recommendation_semantics": "latest_close_target_recommendation_not_yet_filled",
                        "portfolio_kind": portfolio,
                        "rank": len(out) + 1,
                        "ticker": "CASH",
                        "company_name": "Cash reserve",
                        "sector": "Cash",
                        "recommended_weight": cash_weight,
                        "current_account_weight": account_cash_weight,
                        "projected_account_weight_after_orders": projected_weights.get("CASH", projected_cash_weight),
                        "trade_action_from_current": "DEPLOY_CASH" if clean_float(account_cash_weight, 0.0) > cash_weight else "RESERVE_CASH",
                        "trade_value_delta_usd": 0.0,
                        "estimated_order_quantity": 0.0,
                        "target_value_per_100k_usd": cash_weight * 100000.0,
                        "reference_price": 1.0,
                        "reference_price_date": as_of_date,
                        "reference_price_source": "cash",
                        "estimated_shares_per_100k": 0,
                        "suggested_action": "RESERVE_CASH" if cash_weight > 0 else "NO_CASH_TARGET",
                        "buy_logic": "residual cash after target stock weights",
                        "score": 0.0,
                        "monster_early_score": 0.0,
                        "stale_leader_score": 0.0,
                        "risk_entry_block_score": 0.0,
                    }
                ]
            ),
        ],
        ignore_index=True,
    )
    return out


def load_open_lots(latest_run: Path, portfolio: str) -> dict[str, dict[str, Any]]:
    frame = read_csv(latest_run / "broker_trade_journal" / portfolio / "open_positions.csv")
    if frame.empty or "ticker" not in frame.columns:
        return {}
    d = frame.copy()
    d["ticker"] = d["ticker"].map(clean_ticker)
    for col in ["quantity_open", "entry_price"]:
        if col not in d.columns:
            d[col] = 0.0
        d[col] = pd.to_numeric(d[col], errors="coerce").fillna(0.0)
    out: dict[str, dict[str, Any]] = {}
    for ticker, group in d.groupby("ticker"):
        qty = float(group["quantity_open"].sum())
        avg_entry = float((group["quantity_open"] * group["entry_price"]).sum() / qty) if abs(qty) > 1e-12 else 0.0
        entry_dates = sorted({str(x) for x in group.get("entry_date", pd.Series(dtype=str)) if str(x).strip()})
        signal_dates = sorted({str(x) for x in group.get("entry_signal_date", pd.Series(dtype=str)) if str(x).strip()})
        reasons = sorted({str(x) for x in group.get("entry_reason", pd.Series(dtype=str)) if str(x).strip()})
        sleeves = sorted({str(x) for x in group.get("entry_sleeve", pd.Series(dtype=str)) if str(x).strip()})
        out[str(ticker)] = {
            "entry_date": entry_dates[0] if entry_dates else "",
            "latest_entry_date": entry_dates[-1] if entry_dates else "",
            "entry_signal_date": signal_dates[0] if signal_dates else "",
            "avg_entry_price": avg_entry,
            "entry_reason": ",".join(reasons),
            "entry_sleeve": ",".join(sleeves),
            "open_lot_count": int(len(group)),
        }
    return out


def normalize_current_holdings(latest_run: Path, portfolio: str, as_of_date: str) -> pd.DataFrame:
    positions = read_csv(latest_run / "broker_replay" / portfolio / "positions_latest.csv")
    state = read_json(latest_run / "broker_replay" / portfolio / "account_state_latest.json")
    lots = load_open_lots(latest_run, portfolio)
    order_preview, preview_metrics = load_order_preview(latest_run, portfolio)
    orders = order_by_ticker(order_preview)
    projected_weights = load_projected_after_order_weights(latest_run, portfolio)
    trade_dt = last_trade_date(latest_run, portfolio)
    stale_days = date_diff_days(trade_dt, as_of_date)
    pending_order_count = int(clean_float(preview_metrics.get("order_count"), 0.0))
    rows: list[dict[str, Any]] = []
    if not positions.empty and "ticker" in positions.columns:
        for row in positions.to_dict("records"):
            ticker = clean_ticker(row.get("ticker"))
            if not ticker:
                continue
            lot = lots.get(ticker, {})
            order = orders.get(ticker, {})
            current_price = clean_float(row.get("price"), np.nan)
            avg_entry = clean_float(lot.get("avg_entry_price"), clean_float(row.get("cost_basis"), np.nan))
            return_since_entry = current_price / avg_entry - 1.0 if current_price > 0 and avg_entry > 0 else np.nan
            rows.append(
                {
                    "as_of_date": str(row.get("as_of_date") or as_of_date),
                    "recommendation_date": str(preview_metrics.get("as_of_date") or as_of_date),
                    "current_account_last_trade_date": trade_dt,
                    "current_account_stale_days": stale_days,
                    "pending_order_count_to_recommendation": pending_order_count,
                    "portfolio_kind": portfolio,
                    "row_type": "equity",
                    "ticker": ticker,
                    "shares": clean_float(row.get("shares")),
                    "current_price": current_price,
                    "market_value_usd": clean_float(row.get("market_value_usd")),
                    "current_weight": clean_float(row.get("weight")),
                    "recommended_target_weight": clean_float(order.get("target_weight"), 0.0),
                    "projected_weight_after_recommendation_orders": projected_weights.get(ticker, np.nan),
                    "recommended_trade_action": str(order.get("side") or "HOLD"),
                    "recommended_trade_quantity": clean_float(order.get("quantity"), 0.0),
                    "recommended_trade_value_delta_usd": clean_float(order.get("trade_value_delta_usd"), 0.0),
                    "cost_basis": clean_float(row.get("cost_basis"), np.nan),
                    "avg_entry_price": avg_entry,
                    "entry_date": lot.get("entry_date", ""),
                    "latest_entry_date": lot.get("latest_entry_date", ""),
                    "entry_signal_date": lot.get("entry_signal_date", ""),
                    "return_since_entry_pct": return_since_entry,
                    "unrealized_pnl_usd": clean_float(row.get("unrealized_pnl_usd"), np.nan),
                    "realized_pnl_usd": clean_float(row.get("realized_pnl_usd"), 0.0),
                    "entry_reason": lot.get("entry_reason", ""),
                    "entry_sleeve": lot.get("entry_sleeve", ""),
                    "open_lot_count": lot.get("open_lot_count", 0),
                }
            )
    equity = clean_float(state.get("equity_usd"))
    cash = clean_float(state.get("cash_usd"))
    if equity > 0:
        target_cash_weight = np.nan
        if not order_preview.empty:
            target_sum = float(
                pd.to_numeric(
                    order_preview.get("target_weight", pd.Series(dtype=float)),
                    errors="coerce",
                )
                .fillna(0.0)
                .sum()
            )
            target_cash_weight = max(0.0, 1.0 - target_sum)
            if abs(target_cash_weight) < 1e-9:
                target_cash_weight = 0.0
        rows.append(
            {
                "as_of_date": str(state.get("as_of_date") or as_of_date),
                "recommendation_date": str(preview_metrics.get("as_of_date") or as_of_date),
                "current_account_last_trade_date": trade_dt,
                "current_account_stale_days": stale_days,
                "pending_order_count_to_recommendation": pending_order_count,
                "portfolio_kind": portfolio,
                "row_type": "cash",
                "ticker": "CASH",
                "shares": 0.0,
                "current_price": 1.0,
                "market_value_usd": cash,
                "current_weight": cash / equity,
                "recommended_target_weight": target_cash_weight,
                "projected_weight_after_recommendation_orders": projected_weights.get("CASH", clean_float(preview_metrics.get("projected_cash_weight"), np.nan)),
                "recommended_trade_action": "DEPLOY_CASH" if pending_order_count > 0 else "HOLD_CASH",
                "recommended_trade_quantity": 0.0,
                "recommended_trade_value_delta_usd": 0.0,
                "cost_basis": 1.0,
                "avg_entry_price": 1.0,
                "entry_date": "",
                "latest_entry_date": "",
                "entry_signal_date": "",
                "return_since_entry_pct": 0.0,
                "unrealized_pnl_usd": 0.0,
                "realized_pnl_usd": 0.0,
                "entry_reason": "uninvested_cash",
                "entry_sleeve": "cash",
                "open_lot_count": 0,
            }
        )
    out = pd.DataFrame(rows)
    if not out.empty:
        out = out.sort_values(["row_type", "current_weight"], ascending=[False, False]).reset_index(drop=True)
    return out


def max_drawdown(values: pd.Series) -> float:
    if values.empty:
        return 0.0
    dd = values / values.cummax() - 1.0
    return float(dd.min())


def scorecard_for_horizon(
    equity: pd.DataFrame,
    trades: pd.DataFrame,
    label: str,
    offset: pd.DateOffset | None,
) -> dict[str, Any]:
    if equity.empty:
        return {"horizon": label, "status": "missing"}
    d = equity.copy()
    d["date"] = pd.to_datetime(d["date"], errors="coerce")
    d["equity_usd"] = pd.to_numeric(d["equity_usd"], errors="coerce")
    d = d.dropna(subset=["date", "equity_usd"]).sort_values("date")
    if d.empty:
        return {"horizon": label, "status": "missing"}
    end = pd.Timestamp(d["date"].max())
    if offset is not None:
        start_cut = end - offset
        window = d[d["date"] >= start_cut].copy()
        if len(window) < 2:
            window = d.copy()
    else:
        window = d.copy()
    start_date = pd.Timestamp(window["date"].iloc[0])
    end_date = pd.Timestamp(window["date"].iloc[-1])
    years = max((end_date - start_date).days / 365.25, 1 / 252)
    start_eq = float(window["equity_usd"].iloc[0])
    end_eq = float(window["equity_usd"].iloc[-1])
    period_return = end_eq / max(start_eq, 1e-12) - 1.0
    cagr = (end_eq / max(start_eq, 1e-12)) ** (1.0 / years) - 1.0 if years > 0 else 0.0
    returns = window["equity_usd"].pct_change().dropna()
    vol = float(returns.std(ddof=0) * math.sqrt(252.0)) if not returns.empty else 0.0
    sharpe = float((returns.mean() * 252.0) / (vol + 1e-12)) if not returns.empty else 0.0
    td = trades.copy()
    if not td.empty and "date" in td.columns:
        td["date"] = pd.to_datetime(td["date"], errors="coerce")
        td = td[(td["date"] >= start_date) & (td["date"] <= end_date)].copy()
    gross = float(pd.to_numeric(td.get("gross_value", pd.Series(dtype=float)), errors="coerce").fillna(0.0).sum()) if not td.empty else 0.0
    avg_equity = float(window["equity_usd"].mean())
    return {
        "horizon": label,
        "status": "completed",
        "start_date": start_date.date().isoformat(),
        "end_date": end_date.date().isoformat(),
        "days": int(len(window)),
        "period_return": float(period_return),
        "cagr": float(cagr),
        "sharpe": sharpe,
        "max_dd": max_drawdown(window["equity_usd"]),
        "start_equity_usd": start_eq,
        "end_equity_usd": end_eq,
        "avg_cash_weight": float(pd.to_numeric(window.get("cash_weight", pd.Series(dtype=float)), errors="coerce").mean()),
        "end_cash_weight": clean_float(window.get("cash_weight", pd.Series([np.nan])).iloc[-1], np.nan),
        "trade_count": int(len(td)),
        "gross_traded_usd": gross,
        "turnover_estimate": gross / max(avg_equity, 1e-12),
    }


def build_scorecard(latest_run: Path, portfolio: str) -> pd.DataFrame:
    equity = read_csv(latest_run / "broker_replay" / portfolio / "equity_curve.csv")
    trades = read_csv(latest_run / "broker_replay" / portfolio / "trades.csv")
    rows = [scorecard_for_horizon(equity, trades, label, offset) for label, offset in HORIZONS]
    metrics = read_json(latest_run / "broker_replay" / portfolio / "metrics.json")
    if metrics.get("status") == "completed":
        for row in rows:
            if row.get("horizon") != "FULL":
                continue
            row.update(
                {
                    "start_date": metrics.get("start_date", row.get("start_date", "")),
                    "end_date": metrics.get("end_date", row.get("end_date", "")),
                    "period_return": clean_float(metrics.get("total_return"), row.get("period_return", 0.0)),
                    "cagr": clean_float(metrics.get("cagr"), row.get("cagr", 0.0)),
                    "sharpe": clean_float(metrics.get("sharpe"), row.get("sharpe", 0.0)),
                    "max_dd": clean_float(metrics.get("max_dd"), row.get("max_dd", 0.0)),
                    "start_equity_usd": clean_float(metrics.get("starting_capital_usd"), row.get("start_equity_usd", 0.0)),
                    "end_equity_usd": clean_float(metrics.get("ending_capital_usd"), row.get("end_equity_usd", 0.0)),
                    "avg_cash_weight": clean_float(metrics.get("avg_cash_weight"), row.get("avg_cash_weight", 0.0)),
                    "trade_count": int(clean_float(metrics.get("trade_count"), row.get("trade_count", 0))),
                    "gross_traded_usd": clean_float(metrics.get("gross_traded_usd"), row.get("gross_traded_usd", 0.0)),
                }
            )
            avg_equity = clean_float(row.get("end_equity_usd"), 0.0)
            if avg_equity > 0:
                row["turnover_estimate"] = clean_float(row.get("gross_traded_usd"), 0.0) / avg_equity
            break
    return pd.DataFrame(rows)


def svg_escape(value: Any) -> str:
    return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def top_weight_rows(frame: pd.DataFrame, weight_col: str, ticker_col: str = "ticker", max_items: int = 10) -> list[tuple[str, float]]:
    if frame.empty or weight_col not in frame.columns or ticker_col not in frame.columns:
        return []
    d = frame.copy()
    d[ticker_col] = d[ticker_col].map(clean_ticker)
    d[weight_col] = pd.to_numeric(d[weight_col], errors="coerce").fillna(0.0)
    d = d[(d[ticker_col] != "") & (d[weight_col] > 1e-12)].sort_values(weight_col, ascending=False)
    rows = [(str(r[ticker_col]), float(r[weight_col])) for _, r in d.head(max_items).iterrows()]
    other = float(d.iloc[max_items:][weight_col].sum()) if len(d) > max_items else 0.0
    if other > 1e-12:
        rows.append(("OTHER", other))
    return rows


def polar_to_xy(cx: float, cy: float, r: float, angle: float) -> tuple[float, float]:
    return cx + r * math.cos(angle), cy + r * math.sin(angle)


def write_pie_svg(path: Path, rows: list[tuple[str, float]], title: str) -> None:
    total = sum(max(w, 0.0) for _, w in rows)
    width, height = 720, 420
    cx, cy, r = 210, 220, 135
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        f'<text x="24" y="34" font-family="Arial" font-size="22" font-weight="700" fill="#111827">{svg_escape(title)}</text>',
    ]
    if total <= 0:
        parts.append('<text x="24" y="80" font-family="Arial" font-size="16" fill="#6b7280">No weights available</text>')
    else:
        angle = -math.pi / 2
        for i, (ticker, weight) in enumerate(rows):
            frac = max(weight, 0.0) / total
            next_angle = angle + frac * math.tau
            x1, y1 = polar_to_xy(cx, cy, r, angle)
            x2, y2 = polar_to_xy(cx, cy, r, next_angle)
            large = 1 if frac > 0.5 else 0
            color = DEFAULT_COLORS[i % len(DEFAULT_COLORS)]
            parts.append(
                f'<path d="M {cx:.2f} {cy:.2f} L {x1:.2f} {y1:.2f} A {r:.2f} {r:.2f} 0 {large} 1 {x2:.2f} {y2:.2f} Z" fill="{color}" stroke="#ffffff" stroke-width="2"/>'
            )
            angle = next_angle
        y = 82
        for i, (ticker, weight) in enumerate(rows):
            color = DEFAULT_COLORS[i % len(DEFAULT_COLORS)]
            parts.append(f'<rect x="400" y="{y - 12}" width="14" height="14" fill="{color}"/>')
            parts.append(
                f'<text x="424" y="{y}" font-family="Arial" font-size="14" fill="#111827">{svg_escape(ticker)} {weight:.1%}</text>'
            )
            y += 24
    parts.append("</svg>")
    write_text(path, "\n".join(parts))


def write_bar_svg(path: Path, rows: list[tuple[str, float]], title: str) -> None:
    width = 760
    row_h = 30
    height = max(180, 70 + row_h * len(rows))
    max_w = max([w for _, w in rows], default=0.0)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        f'<text x="24" y="34" font-family="Arial" font-size="22" font-weight="700" fill="#111827">{svg_escape(title)}</text>',
    ]
    if max_w <= 0:
        parts.append('<text x="24" y="80" font-family="Arial" font-size="16" fill="#6b7280">No weights available</text>')
    else:
        for i, (ticker, weight) in enumerate(rows):
            y = 70 + i * row_h
            bar_w = 500 * weight / max_w
            color = DEFAULT_COLORS[i % len(DEFAULT_COLORS)]
            parts.append(f'<text x="24" y="{y + 16}" font-family="Arial" font-size="14" fill="#111827">{svg_escape(ticker)}</text>')
            parts.append(f'<rect x="120" y="{y}" width="{bar_w:.2f}" height="20" fill="{color}" rx="3"/>')
            parts.append(f'<text x="{130 + bar_w:.2f}" y="{y + 16}" font-family="Arial" font-size="14" fill="#111827">{weight:.1%}</text>')
    parts.append("</svg>")
    write_text(path, "\n".join(parts))


def render_portfolio_report(portfolio: str, rec: pd.DataFrame, current: pd.DataFrame, scorecard: pd.DataFrame) -> str:
    title = PORTFOLIO_SPECS[portfolio]["label"]
    rec_date = ""
    if not rec.empty and "recommendation_date" in rec.columns:
        rec_date = str(rec["recommendation_date"].dropna().iloc[0]) if rec["recommendation_date"].dropna().size else ""
    last_trade = ""
    stale_days = None
    pending_orders = None
    if not current.empty:
        if "current_account_last_trade_date" in current.columns and current["current_account_last_trade_date"].dropna().size:
            last_trade = str(current["current_account_last_trade_date"].dropna().iloc[0])
        if "current_account_stale_days" in current.columns and current["current_account_stale_days"].dropna().size:
            stale_days = int(clean_float(current["current_account_stale_days"].dropna().iloc[0]))
        if "pending_order_count_to_recommendation" in current.columns and current["pending_order_count_to_recommendation"].dropna().size:
            pending_orders = int(clean_float(current["pending_order_count_to_recommendation"].dropna().iloc[0]))
    lines = [
        f"# {title} Portfolio Report",
        "",
        "This report separates latest target recommendations from the current simulated operating account.",
        f"- Recommendation date: `{rec_date}`",
        f"- Current account last replay trade date: `{last_trade}`",
        f"- Current account stale days versus recommendation date: `{stale_days}`",
        f"- Pending orders needed to match recommendation: `{pending_orders}`",
        "",
        "## Performance Scorecard",
        "",
        "| Horizon | Return | CAGR | Sharpe | MaxDD | Turnover | Trades | End Cash |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in scorecard.to_dict("records"):
        if row.get("status") != "completed":
            continue
        lines.append(
            "| {horizon} | {ret:.2%} | {cagr:.2%} | {sharpe:.3f} | {mdd:.2%} | {turnover:.2f}x | {trades} | {cash:.2%} |".format(
                horizon=row.get("horizon"),
                ret=clean_float(row.get("period_return")),
                cagr=clean_float(row.get("cagr")),
                sharpe=clean_float(row.get("sharpe")),
                mdd=clean_float(row.get("max_dd")),
                turnover=clean_float(row.get("turnover_estimate")),
                trades=int(clean_float(row.get("trade_count"))),
                cash=clean_float(row.get("end_cash_weight")),
            )
        )
    lines += [
        "",
        "## Files",
        "",
        "- `recommendation_latest.csv`: latest target recommendation, formatted as what to buy/hold to target from the latest close.",
        "- `current_operating_holdings_latest.csv`: actual simulated broker-ledger holdings marked to market, including cash.",
        "- `performance_scorecard.csv`: broker-ledger performance by horizon.",
        "- `*_pie.svg` and `*_bar.svg`: visual weights for recommendation/current holdings.",
        "",
        "## Top Recommendations",
        "",
        "| Ticker | Weight | Current Weight | Action | Trade Delta | Price | Shares per $100k | Logic |",
        "| --- | ---: | ---: | --- | ---: | ---: | ---: | --- |",
    ]
    for row in rec.head(12).to_dict("records"):
        lines.append(
            f"| {row.get('ticker')} | {clean_float(row.get('recommended_weight')):.2%} | {clean_float(row.get('current_account_weight')):.2%} | {row.get('trade_action_from_current', '')} | {clean_float(row.get('trade_value_delta_usd')):,.0f} | {clean_float(row.get('reference_price')):.2f} | {int(clean_float(row.get('estimated_shares_per_100k')))} | {str(row.get('buy_logic', '')).replace('|', '/')} |"
        )
    lines += [
        "",
        "## Current Holdings",
        "",
        "| Ticker | Current Weight | Target Weight | Action | Trade Delta | Shares | Current Price | Entry Date | Entry Price | Return Since Entry | Entry Reason |",
        "| --- | ---: | ---: | --- | ---: | ---: | ---: | --- | ---: | ---: | --- |",
    ]
    for row in current.head(20).to_dict("records"):
        lines.append(
            f"| {row.get('ticker')} | {clean_float(row.get('current_weight')):.2%} | {clean_float(row.get('recommended_target_weight')):.2%} | {row.get('recommended_trade_action', '')} | {clean_float(row.get('recommended_trade_value_delta_usd')):,.0f} | {clean_float(row.get('shares')):.2f} | {clean_float(row.get('current_price')):.2f} | {row.get('entry_date', '')} | {clean_float(row.get('avg_entry_price')):.2f} | {clean_float(row.get('return_since_entry_pct')):.2%} | {str(row.get('entry_reason', '')).replace('|', '/')} |"
        )
    lines.append("")
    return "\n".join(lines)


def build_reports(args: argparse.Namespace) -> dict[str, Any]:
    latest_run = repo_path(args.latest_run)
    output_dir = repo_path(args.output_dir)
    price_cache = repo_path(args.price_cache)
    output_dir.mkdir(parents=True, exist_ok=True)
    as_of_date = args.as_of_date or latest_as_of_date(latest_run)
    portfolios: dict[str, Any] = {}

    for portfolio in PORTFOLIO_SPECS:
        pdir = output_dir / portfolio
        pdir.mkdir(parents=True, exist_ok=True)
        rec = normalize_recommendations(latest_run, portfolio, as_of_date, price_cache)
        current = normalize_current_holdings(latest_run, portfolio, as_of_date)
        scorecard = build_scorecard(latest_run, portfolio)

        rec_path = pdir / "recommendation_latest.csv"
        current_path = pdir / "current_operating_holdings_latest.csv"
        scorecard_path = pdir / "performance_scorecard.csv"
        rec.to_csv(rec_path, index=False)
        current.to_csv(current_path, index=False)
        scorecard.to_csv(scorecard_path, index=False)

        root_rec_path = output_dir / f"{portfolio}_recommendation_latest.csv"
        root_current_path = output_dir / f"{portfolio}_current_operating_holdings_latest.csv"
        rec.to_csv(root_rec_path, index=False)
        current.to_csv(root_current_path, index=False)

        write_pie_svg(
            pdir / "recommendation_weights_pie.svg",
            top_weight_rows(rec, "recommended_weight", max_items=10),
            f"{PORTFOLIO_SPECS[portfolio]['label']} Recommendation Weights",
        )
        write_bar_svg(
            pdir / "recommendation_weights_bar.svg",
            top_weight_rows(rec, "recommended_weight", max_items=15),
            f"{PORTFOLIO_SPECS[portfolio]['label']} Recommendation Weights",
        )
        write_pie_svg(
            pdir / "current_weights_pie.svg",
            top_weight_rows(current, "current_weight", max_items=10),
            f"{PORTFOLIO_SPECS[portfolio]['label']} Current Operating Weights",
        )
        write_bar_svg(
            pdir / "current_weights_bar.svg",
            top_weight_rows(current, "current_weight", max_items=15),
            f"{PORTFOLIO_SPECS[portfolio]['label']} Current Operating Weights",
        )
        write_text(pdir / "portfolio_report.md", render_portfolio_report(portfolio, rec, current, scorecard))

        full_row = {}
        if not scorecard.empty and "horizon" in scorecard.columns:
            full = scorecard[scorecard["horizon"].astype(str).eq("FULL")]
            if not full.empty:
                full_row = full.iloc[0].to_dict()
        portfolios[portfolio] = {
            "recommendation_rows": int(len(rec)),
            "current_rows": int(len(current)),
            "as_of_date": as_of_date,
            "recommendation_csv": str(rec_path),
            "current_operating_csv": str(current_path),
            "primary_recommendation_csv": str(root_rec_path),
            "primary_current_operating_csv": str(root_current_path),
            "performance_scorecard_csv": str(scorecard_path),
            "full_cagr": clean_float(full_row.get("cagr")) if full_row else None,
            "full_sharpe": clean_float(full_row.get("sharpe")) if full_row else None,
            "full_max_dd": clean_float(full_row.get("max_dd")) if full_row else None,
        }

    index_lines = [
        "# User Portfolio Reports",
        "",
        f"- Generated at UTC: `{datetime.now(timezone.utc).isoformat()}`",
        f"- As-of date: `{as_of_date}`",
        "",
        "| Portfolio | Recommendation Rows | Current Rows | Full CAGR | Sharpe | MaxDD |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for portfolio, payload in portfolios.items():
        index_lines.append(
            "| {portfolio} | {rec} | {cur} | {cagr:.2%} | {sharpe:.3f} | {mdd:.2%} |".format(
                portfolio=portfolio,
                rec=payload["recommendation_rows"],
                cur=payload["current_rows"],
                cagr=clean_float(payload.get("full_cagr")),
                sharpe=clean_float(payload.get("full_sharpe")),
                mdd=clean_float(payload.get("full_max_dd")),
            )
        )
    index_lines += [
        "",
        "Use `recommendation_latest.csv` as the latest target buy/hold sheet.",
        "Use `current_operating_holdings_latest.csv` as the actual simulated account holdings sheet.",
        "",
    ]
    write_text(output_dir / "index.md", "\n".join(index_lines))

    payload = {
        "status": "completed",
        "schema_version": "user-portfolio-reports-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "latest_run": str(latest_run),
        "price_cache": str(price_cache),
        "as_of_date": as_of_date,
        "portfolios": portfolios,
    }
    write_json(output_dir / "summary.json", payload)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default="outputs")
    parser.add_argument("--output-dir", default="outputs/user_portfolio_reports")
    parser.add_argument("--price-cache", default="cache_prices")
    parser.add_argument("--as-of-date", default="")
    return parser.parse_args()


def main() -> int:
    payload = build_reports(parse_args())
    print(json.dumps({"status": payload["status"], "as_of_date": payload.get("as_of_date")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
