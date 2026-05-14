#!/usr/bin/env python3
"""Replay target portfolios through a simple broker-style ledger.

This is stricter than the engine's weight-level monthly backtest. It converts a
target book into actual orders, fills them at observable adjusted prices, tracks
shares and cash, and computes metrics from account equity.

Default mode is deliberately conservative:

- signal dated T is assumed known after T close
- fills use the next available trading day's adjusted close
- integer shares are used by default
- no negative cash and no leverage
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.run_weekly_evaluation import load_price_series, px_cache_name, price_on_or_after, price_on_or_before


CASH_TICKERS = {"CASH", "__CASH__"}
DEFAULT_OUT_DIR = "outputs/broker_replay"
DEFAULT_CONCENTRATED_CHAMPION_FILTERS = {
    "target_stock_names": "3",
    "weighting_mode": "score_power",
    "active_rebalance_interval_months": "1",
}
CONCENTRATED_CHAMPION_FILTERS = DEFAULT_CONCENTRATED_CHAMPION_FILTERS


def repo_path(path_like: str | Path) -> Path:
    path = Path(path_like)
    return path if path.is_absolute() else REPO_ROOT / path


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


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame()


def filter_value(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    try:
        number = float(text)
        if math.isfinite(number) and abs(number - round(number)) < 1e-9:
            return str(int(round(number)))
    except (TypeError, ValueError):
        pass
    return text


def comparison_path_for_target_book(target_book: Path) -> Path:
    return target_book.parent / "concentrated_strategy_comparison.csv"


def resolve_concentrated_champion_filters(
    *,
    target_book: Path,
    raw_targets: pd.DataFrame,
    portfolio_kind: str,
    explicit_filters: dict[str, Any] | None = None,
) -> tuple[dict[str, str], str, str]:
    if portfolio_kind != "concentrated":
        return {}, "not_applicable", ""
    if explicit_filters:
        filters = {str(k): filter_value(v) for k, v in explicit_filters.items() if filter_value(v)}
        if filters:
            return filters, "explicit", ""

    comparison_path = comparison_path_for_target_book(target_book)
    comparison = read_csv(comparison_path)
    if not comparison.empty:
        d = comparison.copy()
        if "portfolio_mode" in d.columns:
            d = d[d["portfolio_mode"].astype(str).eq("concentrated_alpha")].copy()
        for col in ["target_stock_names", "strategy_cagr", "sharpe", "max_dd"]:
            if col not in d.columns:
                d[col] = np.nan
            d[col] = pd.to_numeric(d[col], errors="coerce")
        d = d[
            d["target_stock_names"].notna()
            & d["strategy_cagr"].notna()
            & d["sharpe"].notna()
            & d["max_dd"].notna()
        ].copy()
        if not d.empty:
            row = d.iloc[0].to_dict()
            filters = {
                "target_stock_names": filter_value(row.get("target_stock_names")),
                "weighting_mode": filter_value(row.get("weighting_mode") or "score_power"),
                "active_rebalance_interval_months": filter_value(row.get("rebalance_interval_months") or 1),
            }
            filters = {k: v for k, v in filters.items() if v}
            missing_cols = [col for col in filters if col not in raw_targets.columns]
            if missing_cols:
                warning = "comparison champion could not be fully applied; missing target-book columns: " + ",".join(missing_cols)
                return DEFAULT_CONCENTRATED_CHAMPION_FILTERS.copy(), "default_static", warning
            return filters, str(comparison_path), ""

    return (
        DEFAULT_CONCENTRATED_CHAMPION_FILTERS.copy(),
        "default_static",
        f"champion comparison artifact missing or invalid: {comparison_path}",
    )


def filter_concentrated_champion(
    frame: pd.DataFrame,
    portfolio_kind: str,
    champion_filters: dict[str, Any] | None = None,
    preserve_tail_row: bool = True,
) -> pd.DataFrame:
    """F13 (2026-05-14): preserve_tail_row defaults TRUE. The champion filter
    historically dropped the latest-recommendation row when its champion
    metadata (target_stock_names / weighting_mode / etc.) differed from the
    historical-strategy params. Symptom in run 25860138864: Concentrated
    operating_target_book had a 2026-05-13 row with target_stock_names=3 /
    weighting_mode=winner_take_all, while the champion filter required N=2 /
    conviction_curve, so the 5/13 row was silently dropped and F4 tail-row
    same_close fallback never had a chance to fire.

    With preserve_tail_row=True, the row(s) with the maximum rebalance_date
    in the frame are kept regardless of metadata mismatch. Historical rows
    still go through the filter normally. Set False to recover the previous
    behavior (legacy strict filter).
    """
    if portfolio_kind != "concentrated" or frame.empty:
        return frame
    out = frame.copy()
    filters = champion_filters or DEFAULT_CONCENTRATED_CHAMPION_FILTERS
    # F13 (2026-05-14): remember the original tail date so we can detect
    # whether the post-filter result accidentally dropped ALL tail rows.
    original_tail_date: pd.Timestamp | None = None
    original_tail_rows: pd.DataFrame | None = None
    distinct_dates = 0
    if preserve_tail_row and "rebalance_date" in out.columns:
        rd = pd.to_datetime(out["rebalance_date"], errors="coerce")
        if rd.notna().any():
            distinct_dates = int(rd.dt.normalize().nunique())
            if distinct_dates >= 2:
                # Only meaningful to "preserve the tail row" when there are
                # multiple distinct rebalance dates -- otherwise every row
                # IS a tail row and the filter must apply normally.
                original_tail_date = rd.max()
                original_tail_rows = frame.loc[rd == original_tail_date].copy()
    for col, expected_raw in filters.items():
        if col not in out.columns:
            continue
        expected = filter_value(expected_raw)
        if not expected:
            continue
        values = out[col].map(filter_value)
        mask = values.eq(expected)
        if mask.any():
            out = out[mask].copy()
    # F13: if all tail-date rows were dropped by the champion filter, splice
    # them back in. Symptom this fixes: Concentrated 2026-05-13 row carries
    # winner_take_all/N=3 metadata while champion filter wants conviction_curve
    # /N=2 -- without this carve-out, the 5/13 latest-recommendation row gets
    # silently dropped, F4 tail-row fallback never fires, operating account
    # stays frozen at the prior historical rebalance.
    if (
        original_tail_date is not None
        and original_tail_rows is not None
        and not original_tail_rows.empty
        and "rebalance_date" in out.columns
    ):
        rd_post = pd.to_datetime(out["rebalance_date"], errors="coerce")
        post_has_tail = bool((rd_post == original_tail_date).any())
        if not post_has_tail:
            out = pd.concat([out, original_tail_rows], ignore_index=True)
    return out


def normalize_targets(
    frame: pd.DataFrame,
    portfolio_kind: str,
    champion_filters: dict[str, Any] | None = None,
) -> pd.DataFrame:
    if frame.empty or "rebalance_date" not in frame.columns or "ticker" not in frame.columns or "weight" not in frame.columns:
        return pd.DataFrame()
    d = filter_concentrated_champion(frame.copy(), portfolio_kind, champion_filters)
    d["rebalance_date"] = pd.to_datetime(d["rebalance_date"], errors="coerce").dt.normalize()
    d["ticker"] = d["ticker"].astype(str).str.upper().str.strip()
    d["weight"] = pd.to_numeric(d["weight"], errors="coerce").fillna(0.0)
    d = d.dropna(subset=["rebalance_date"])
    d = d[(d["ticker"] != "") & (d["weight"] > 1e-12)]
    keep = [
        c
        for c in [
            "rebalance_date",
            "ticker",
            "weight",
            "Name",
            "sector",
            "portfolio_sleeve_label",
            "portfolio_selection_path",
            "concentrated_selection_source",
            "portfolio_defensive_rotation_action",
        ]
        if c in d.columns
    ]
    d = d[keep].copy()
    d = d.groupby(["rebalance_date", "ticker"], as_index=False).agg(
        {
            "weight": "sum",
            **({"Name": "last"} if "Name" in d.columns else {}),
            **({"sector": "last"} if "sector" in d.columns else {}),
            **({"portfolio_sleeve_label": "last"} if "portfolio_sleeve_label" in d.columns else {}),
            **({"portfolio_selection_path": "last"} if "portfolio_selection_path" in d.columns else {}),
            **({"concentrated_selection_source": "last"} if "concentrated_selection_source" in d.columns else {}),
            **({"portfolio_defensive_rotation_action": "last"} if "portfolio_defensive_rotation_action" in d.columns else {}),
        }
    )
    return d.sort_values(["rebalance_date", "weight"], ascending=[True, False]).reset_index(drop=True)


def weight_book_diagnostics(targets: pd.DataFrame, max_reasonable_weight_sum: float) -> dict[str, Any]:
    if targets.empty:
        return {"max_total_weight": None, "invalid_weight_date_count": 0, "invalid_weight_dates": []}
    rows: list[dict[str, Any]] = []
    for dt, period in targets.groupby("rebalance_date"):
        stock_weight = float(period.loc[~period["ticker"].isin(CASH_TICKERS), "weight"].sum())
        cash_weight = float(period.loc[period["ticker"].isin(CASH_TICKERS), "weight"].sum())
        rows.append(
            {
                "rebalance_date": pd.Timestamp(dt).date().isoformat(),
                "stock_weight": stock_weight,
                "cash_weight": cash_weight,
                "total_weight": stock_weight + cash_weight,
            }
        )
    invalid = [row for row in rows if row["total_weight"] > max_reasonable_weight_sum]
    return {
        "max_total_weight": max((row["total_weight"] for row in rows), default=None),
        "max_stock_weight": max((row["stock_weight"] for row in rows), default=None),
        "invalid_weight_date_count": len(invalid),
        "invalid_weight_dates": invalid[:10],
    }


def target_period_ends(targets: pd.DataFrame, price_cache: Path) -> dict[pd.Timestamp, pd.Timestamp]:
    dates = sorted(pd.to_datetime(targets["rebalance_date"], errors="coerce").dropna().unique())
    out: dict[pd.Timestamp, pd.Timestamp] = {}
    for i, raw_dt in enumerate(dates):
        dt = pd.Timestamp(raw_dt).normalize()
        if i + 1 < len(dates):
            out[dt] = pd.Timestamp(dates[i + 1]).normalize()
            continue
        latest: list[pd.Timestamp] = []
        for ticker in targets.loc[targets["rebalance_date"].eq(dt), "ticker"].astype(str).str.upper().unique():
            if ticker in CASH_TICKERS:
                continue
            px = load_price_series(price_cache, ticker)
            if not px.empty:
                latest.append(pd.Timestamp(px.index.max()).normalize())
        if latest:
            out[dt] = max(latest)
    return out


def mark_dates_for_period(
    tickers: set[str],
    prices: dict[str, pd.DataFrame],
    start_dt: pd.Timestamp,
    end_dt: pd.Timestamp,
) -> list[pd.Timestamp]:
    dates: set[pd.Timestamp] = set()
    for ticker in tickers:
        if ticker in CASH_TICKERS:
            continue
        px = prices.get(ticker, pd.DataFrame())
        if px.empty:
            continue
        idx = pd.DatetimeIndex(px.index).tz_localize(None)
        for raw in idx[(idx >= start_dt) & (idx <= end_dt)]:
            dates.add(pd.Timestamp(raw).normalize())
    return sorted(dates)


def price_at_or_before(prices: dict[str, pd.DataFrame], ticker: str, date: pd.Timestamp) -> float | None:
    actual, value = price_on_or_before(prices.get(ticker, pd.DataFrame()), date, "close")
    if actual is None or value is None:
        return None
    return float(value)


def fill_price(
    prices: dict[str, pd.DataFrame],
    ticker: str,
    signal_date: pd.Timestamp,
    fill_mode: str,
    max_fill_lag_days: int,
) -> tuple[pd.Timestamp | None, float | None]:
    column = "close"
    if fill_mode == "next_open":
        column = "open"
    elif fill_mode not in {"next_close", "same_close"}:
        raise ValueError(f"unsupported fill_mode={fill_mode}")
    target_date = pd.Timestamp(signal_date)
    if fill_mode in {"next_close", "next_open"}:
        target_date = target_date + pd.Timedelta(days=1)
    actual_dt, px = price_on_or_after(prices.get(ticker, pd.DataFrame()), target_date, column)
    if actual_dt is None or px is None:
        return None, None
    if (pd.Timestamp(actual_dt).normalize() - pd.Timestamp(target_date).normalize()).days > int(max_fill_lag_days):
        return None, None
    return actual_dt, px


@dataclass
class LedgerState:
    cash: float
    shares: dict[str, float] = field(default_factory=dict)
    cost_basis: dict[str, float] = field(default_factory=dict)
    realized_pnl: dict[str, float] = field(default_factory=dict)


def account_equity(
    state: LedgerState,
    prices: dict[str, pd.DataFrame],
    date: pd.Timestamp,
    delisted_recovery_rate: float = 0.0,
    delisted_log: list[dict[str, Any]] | None = None,
) -> tuple[float, dict[str, float]]:
    """Mark-to-market the LedgerState at `date`.

    2026-05-14 hard-gate fix (broker_accounting_audit.delisted_cost_basis_fallback_eliminated):
    when `price_at_or_before` returns None / <=0 / NaN (ticker has no usable
    cache data on-or-before `date` -- typically a delisted-to-zero / fire-sale
    bankruptcy / cache gap), DO NOT fall back to `state.cost_basis`. Falling
    back to cost basis silently held dead positions at their original purchase
    value, understating MaxDD over multi-year windows.

    New behavior:
      px = qty * (last_known_close OR delisted_recovery_rate * cost_basis)
    Default delisted_recovery_rate = 0.0 -> a dead position contributes $0 to
    equity (the honest accounting for delisting/bankruptcy). The position
    stays in state.shares so downstream diagnostics can see it, but it does
    NOT prop up account_equity.

    `delisted_log` (optional) captures per-ticker zero-marks for diagnostics;
    callers should pass a list to collect events.
    """
    values: dict[str, float] = {}
    equity = float(state.cash)
    for ticker, qty in list(state.shares.items()):
        if abs(qty) <= 1e-12:
            continue
        px = price_at_or_before(prices, ticker, date)
        marked_via = "last_close"
        if px is None or px <= 0:
            cost = safe_float(state.cost_basis.get(ticker), 0.0)
            px = float(delisted_recovery_rate) * cost
            marked_via = "delisted_zero_mark" if delisted_recovery_rate == 0.0 else "delisted_partial_recovery"
            if delisted_log is not None:
                delisted_log.append({
                    "as_of_date": pd.Timestamp(date).date().isoformat(),
                    "ticker": ticker,
                    "qty": float(qty),
                    "cost_basis_per_share": float(cost),
                    "recovery_rate": float(delisted_recovery_rate),
                    "marked_price": float(px),
                    "marked_via": marked_via,
                })
        value = float(qty) * float(px)
        values[ticker] = value
        equity += value
    return equity, values


def execute_order(
    *,
    state: LedgerState,
    ticker: str,
    side: str,
    desired_qty: float,
    price: float,
    cost_bps: float,
    integer_shares: bool,
) -> dict[str, Any] | None:
    if price <= 0 or desired_qty <= 1e-12:
        return None
    qty = math.floor(desired_qty) if integer_shares else desired_qty
    if qty <= 1e-12:
        return None
    fee_rate = float(cost_bps) / 10000.0
    if side == "BUY":
        max_affordable = state.cash / (price * (1.0 + fee_rate))
        qty = min(qty, math.floor(max_affordable) if integer_shares else max_affordable)
        if qty <= 1e-12:
            return None
        gross = qty * price
        fee = gross * fee_rate
        state.cash -= gross + fee
        old_qty = float(state.shares.get(ticker, 0.0))
        old_basis = float(state.cost_basis.get(ticker, price))
        new_qty = old_qty + qty
        state.shares[ticker] = new_qty
        state.cost_basis[ticker] = ((old_qty * old_basis) + gross) / max(new_qty, 1e-12)
        cash_delta = -(gross + fee)
    else:
        held = float(state.shares.get(ticker, 0.0))
        qty = min(qty, held)
        if qty <= 1e-12:
            return None
        gross = qty * price
        fee = gross * fee_rate
        basis = float(state.cost_basis.get(ticker, price))
        state.cash += gross - fee
        state.shares[ticker] = max(0.0, held - qty)
        state.realized_pnl[ticker] = float(state.realized_pnl.get(ticker, 0.0)) + (price - basis) * qty - fee
        if state.shares[ticker] <= 1e-12:
            state.shares.pop(ticker, None)
            state.cost_basis.pop(ticker, None)
        cash_delta = gross - fee
    return {
        "ticker": ticker,
        "side": side,
        "quantity": float(qty),
        "fill_price": float(price),
        "gross_value": float(qty * price),
        "fee_usd": float(qty * price * fee_rate),
        "cash_delta": float(cash_delta),
        "cash_after": float(state.cash),
        "shares_after": float(state.shares.get(ticker, 0.0)),
    }


def calc_metrics(
    equity_curve: pd.DataFrame,
    trades: pd.DataFrame,
    starting_capital: float,
    risk_free_annual: float = 0.025,
) -> dict[str, Any]:
    if equity_curve.empty:
        return {"status": "blocked", "reason": "empty equity curve"}
    eq = pd.to_numeric(equity_curve["equity_usd"], errors="coerce").dropna()
    dates = pd.to_datetime(equity_curve["date"], errors="coerce").dropna()
    if eq.empty or dates.empty:
        return {"status": "blocked", "reason": "empty equity values"}
    returns = eq.pct_change().dropna()
    years = max((dates.max() - dates.min()).days / 365.25, len(returns) / 252.0, 1e-6)
    cagr = float((eq.iloc[-1] / max(starting_capital, 1e-12)) ** (1.0 / years) - 1.0)
    drawdown = eq / eq.cummax() - 1.0
    trough_pos = int(drawdown.argmin()) if not drawdown.empty else 0
    peak_pos = int(eq.iloc[: trough_pos + 1].argmax()) if not eq.empty else 0
    vol = float(returns.std(ddof=0) * math.sqrt(252.0)) if not returns.empty else 0.0
    # 2026-05-14 soft-gate fix (broker_accounting_audit.sharpe_uses_excess_return):
    # subtract a constant annual risk-free rate from the strategy's annualized
    # return before dividing by vol. Default 2.5% reflects the 2019-2026 average
    # T-bill yield; callers can override via `risk_free_annual`. Previously this
    # used risk_free=0 implicitly, overstating Sharpe by ~0.20-0.30.
    rf_annual = float(risk_free_annual)
    ann_return = float(returns.mean() * 252.0) if not returns.empty else 0.0
    sharpe = float((ann_return - rf_annual) / (vol + 1e-12)) if not returns.empty else 0.0
    fees = float(pd.to_numeric(trades.get("fee_usd", pd.Series(dtype=float)), errors="coerce").fillna(0.0).sum()) if not trades.empty else 0.0
    gross_traded = float(pd.to_numeric(trades.get("gross_value", pd.Series(dtype=float)), errors="coerce").fillna(0.0).sum()) if not trades.empty else 0.0
    return {
        "status": "completed",
        "metric_mode": "broker_ledger_next_close" if str(equity_curve.get("fill_mode", pd.Series([""])).iloc[0]) == "next_close" else "broker_ledger",
        "start_date": dates.min().date().isoformat(),
        "end_date": dates.max().date().isoformat(),
        "days": int(len(eq)),
        "years": float(years),
        "starting_capital_usd": float(starting_capital),
        "ending_capital_usd": float(eq.iloc[-1]),
        "total_return": float(eq.iloc[-1] / max(starting_capital, 1e-12) - 1.0),
        "cagr": cagr,
        "sharpe": sharpe,
        "sharpe_risk_free_annual": rf_annual,
        "max_dd": float(drawdown.min()),
        "max_dd_peak_date": dates.iloc[peak_pos].date().isoformat() if len(dates) else None,
        "max_dd_trough_date": dates.iloc[trough_pos].date().isoformat() if len(dates) else None,
        "max_dd_peak_equity_usd": float(eq.iloc[peak_pos]) if len(eq) else None,
        "max_dd_trough_equity_usd": float(eq.iloc[trough_pos]) if len(eq) else None,
        "avg_cash_weight": float(pd.to_numeric(equity_curve.get("cash_weight", pd.Series(dtype=float)), errors="coerce").mean()),
        "min_cash_usd": float(pd.to_numeric(equity_curve.get("cash_usd", pd.Series(dtype=float)), errors="coerce").min()),
        "trade_count": int(len(trades)),
        "total_fees_usd": fees,
        "gross_traded_usd": gross_traded,
    }


def latest_account_state(
    *,
    state: LedgerState,
    prices: dict[str, pd.DataFrame],
    as_of_date: pd.Timestamp,
    metrics: dict[str, Any],
    trades: pd.DataFrame,
    portfolio_kind: str,
    starting_capital: float,
    fill_mode: str,
    cost_bps: float,
    integer_shares: bool,
) -> tuple[dict[str, Any], pd.DataFrame]:
    equity, values = account_equity(state, prices, as_of_date)
    rows: list[dict[str, Any]] = []
    for ticker in sorted(state.shares.keys()):
        qty = float(state.shares.get(ticker, 0.0))
        if abs(qty) <= 1e-12:
            continue
        px = price_at_or_before(prices, ticker, as_of_date)
        market_value = float(values.get(ticker, 0.0))
        basis = float(state.cost_basis.get(ticker, np.nan))
        rows.append(
            {
                "as_of_date": pd.Timestamp(as_of_date).date().isoformat(),
                "ticker": ticker,
                "shares": qty,
                "price": px if px is not None else np.nan,
                "market_value_usd": market_value,
                "weight": float(market_value / equity) if equity > 0 else np.nan,
                "cost_basis": basis,
                "unrealized_pnl_usd": float(market_value - qty * basis) if np.isfinite(basis) else np.nan,
                "realized_pnl_usd": float(state.realized_pnl.get(ticker, 0.0)),
            }
        )
    positions = pd.DataFrame(rows)
    total_fees = (
        float(pd.to_numeric(trades.get("fee_usd", pd.Series(dtype=float)), errors="coerce").fillna(0.0).sum())
        if not trades.empty
        else 0.0
    )
    account = {
        "schema_version": "account-ledger-v1",
        "portfolio_kind": portfolio_kind,
        "as_of_date": pd.Timestamp(as_of_date).date().isoformat(),
        "starting_capital_usd": float(starting_capital),
        "equity_usd": float(equity),
        "cash_usd": float(state.cash),
        "cash_weight": float(state.cash / equity) if equity > 0 else np.nan,
        "stock_value_usd": float(sum(values.values())),
        "position_count": int(len(rows)),
        "fill_mode": fill_mode,
        "cost_bps_per_side": float(cost_bps),
        "integer_shares": bool(integer_shares),
        "metrics": metrics,
        "realized_pnl_by_ticker": {str(k): float(v) for k, v in sorted(state.realized_pnl.items())},
        "total_realized_pnl_usd": float(sum(state.realized_pnl.values())),
        "total_fees_usd": total_fees,
        "positions": rows,
    }
    return account, positions


def replay(
    *,
    target_book: Path,
    price_cache: Path,
    output_dir: Path,
    portfolio_kind: str,
    starting_capital: float = 100000.0,
    fill_mode: str = "next_close",
    cost_bps: float = 25.0,
    integer_shares: bool = True,
    max_reasonable_weight_sum: float = 1.05,
    max_fill_lag_days: int = 7,
    concentrated_champion_filters: dict[str, Any] | None = None,
    tail_row_fill_fallback_same_close: bool = False,
) -> dict[str, Any]:
    """Run a broker-ledger replay.

    2026-05-14 F4: `tail_row_fill_fallback_same_close` (default False) makes
    the LAST signal_date in the target book retry with `same_close` fill mode
    when `next_close` / `next_open` returns no price (typical scenario: the
    latest recommendation lands on the same date as the most recent cache
    close, so there is no `next_close` available yet). Historical rows
    continue to use the requested fill_mode; only the tail row is allowed
    the fallback. This closes the "33 pending orders" gap visible in
    user_portfolio_reports without changing historical metric semantics.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    raw = read_csv(target_book)
    champion_filters, champion_filter_source, champion_filter_warning = resolve_concentrated_champion_filters(
        target_book=target_book,
        raw_targets=raw,
        portfolio_kind=portfolio_kind,
        explicit_filters=concentrated_champion_filters,
    )
    targets = normalize_targets(raw, portfolio_kind, champion_filters)
    if targets.empty:
        payload = {
            "status": "blocked",
            "reason": "target book is empty or invalid",
            "target_book": str(target_book),
            "target_book_filter": champion_filters,
            "target_book_filter_source": champion_filter_source,
            "target_book_filter_warning": champion_filter_warning,
        }
        (output_dir / "metrics.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return payload
    weight_diag = weight_book_diagnostics(targets, max_reasonable_weight_sum)
    if int(weight_diag.get("invalid_weight_date_count") or 0) > 0:
        payload = {
            "status": "blocked",
            "reason": "target weight sum exceeds maximum reasonable exposure",
            "target_book": str(target_book),
            "research_only": True,
            "valid_for_production": False,
            "target_book_filter": champion_filters,
            "target_book_filter_source": champion_filter_source,
            "target_book_filter_warning": champion_filter_warning,
            **weight_diag,
        }
        (output_dir / "metrics.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return payload

    tickers = sorted({str(x).upper() for x in targets["ticker"].unique() if str(x).upper() not in CASH_TICKERS})
    prices = {ticker: load_price_series(price_cache, ticker) for ticker in tickers}
    prices = {ticker: px for ticker, px in prices.items() if not px.empty}
    periods = target_period_ends(targets, price_cache)
    state = LedgerState(cash=float(starting_capital))
    trade_rows: list[dict[str, Any]] = []
    equity_rows: list[dict[str, Any]] = []
    holdings_rows: list[dict[str, Any]] = []
    cash_rows: list[dict[str, Any]] = []
    target_vs_actual_rows: list[dict[str, Any]] = []

    sorted_signal_dts = sorted(periods.keys())
    tail_signal_dt = sorted_signal_dts[-1] if sorted_signal_dts else None
    tail_fallback_activated_signal_dt: pd.Timestamp | None = None
    for signal_dt in sorted_signal_dts:
        target = targets[targets["rebalance_date"].eq(signal_dt)].copy()
        if target.empty:
            continue
        # Tail-row fallback (2026-05-14 F4): if the requested fill_mode is
        # next_close / next_open and we're processing the LAST signal_dt,
        # try the requested mode first; if all tickers come back unfillable
        # (typical when latest cache close == signal_dt and there is no
        # next_close yet), retry with same_close on the same signal_dt.
        effective_fill_mode = fill_mode
        fill_dt_by_ticker: dict[str, pd.Timestamp] = {}
        fill_px_by_ticker: dict[str, float] = {}
        for ticker in sorted(set(target["ticker"].astype(str).str.upper()) | set(state.shares.keys())):
            if ticker in CASH_TICKERS:
                continue
            actual_dt, px = fill_price(prices, ticker, signal_dt, effective_fill_mode, max_fill_lag_days)
            if actual_dt is not None and px is not None:
                fill_dt_by_ticker[ticker] = pd.Timestamp(actual_dt).normalize()
                fill_px_by_ticker[ticker] = float(px)
        # If tail row produced zero fills under next_close, retry with
        # same_close. Diagnostic stamped on the trade rows so downstream
        # reports can flag the synthetic-fill semantics.
        tail_fallback_used = False
        if (
            tail_row_fill_fallback_same_close
            and tail_signal_dt is not None
            and pd.Timestamp(signal_dt) == pd.Timestamp(tail_signal_dt)
            and not fill_dt_by_ticker
            and fill_mode in {"next_close", "next_open"}
        ):
            effective_fill_mode = "same_close"
            for ticker in sorted(set(target["ticker"].astype(str).str.upper()) | set(state.shares.keys())):
                if ticker in CASH_TICKERS:
                    continue
                actual_dt, px = fill_price(prices, ticker, signal_dt, effective_fill_mode, max_fill_lag_days)
                if actual_dt is not None and px is not None:
                    fill_dt_by_ticker[ticker] = pd.Timestamp(actual_dt).normalize()
                    fill_px_by_ticker[ticker] = float(px)
            if fill_dt_by_ticker:
                tail_fallback_used = True
                tail_fallback_activated_signal_dt = pd.Timestamp(signal_dt)
        if not fill_dt_by_ticker:
            continue
        fill_dt = min(fill_dt_by_ticker.values())
        current_equity, current_values = account_equity(state, prices, fill_dt)
        target_weights = {
            str(row.ticker).upper(): safe_float(row.weight)
            for row in target.itertuples(index=False)
            if str(row.ticker).upper() not in CASH_TICKERS
        }
        for ticker in sorted(set(state.shares.keys()) - set(target_weights.keys())):
            px = fill_px_by_ticker.get(ticker)
            if px is None:
                continue
            order = execute_order(
                state=state,
                ticker=ticker,
                side="SELL",
                desired_qty=float(state.shares.get(ticker, 0.0)),
                price=px,
                cost_bps=cost_bps,
                integer_shares=integer_shares,
            )
            if order:
                order.update({"date": fill_dt.date().isoformat(), "signal_date": signal_dt.date().isoformat(), "reason": "target_exit", "fill_mode": fill_mode})
                trade_rows.append(order)
        current_equity, current_values = account_equity(state, prices, fill_dt)
        adjustments: list[tuple[str, float, float, float, float]] = []
        for ticker, target_weight in target_weights.items():
            px = fill_px_by_ticker.get(ticker)
            if px is None:
                continue
            current_qty = float(state.shares.get(ticker, 0.0))
            current_value = current_qty * px
            target_value = max(0.0, float(target_weight) * current_equity)
            diff_value = target_value - current_value
            if abs(diff_value) < max(25.0, current_equity * 0.0005):
                continue
            adjustments.append((ticker, float(target_weight), float(diff_value), float(px), float(current_value)))
        adjustments = sorted(adjustments, key=lambda row: (row[2] > 0, abs(row[2])))
        for ticker, target_weight, diff_value, px, _current_value in adjustments:
            side = "BUY" if diff_value > 0 else "SELL"
            qty = abs(diff_value) / px
            order = execute_order(
                state=state,
                ticker=ticker,
                side=side,
                desired_qty=qty,
                price=px,
                cost_bps=cost_bps,
                integer_shares=integer_shares,
            )
            if order:
                order.update({"date": fill_dt.date().isoformat(), "signal_date": signal_dt.date().isoformat(), "reason": "target_rebalance", "target_weight": target_weight, "fill_mode": fill_mode})
                trade_rows.append(order)
        equity_after, values_after = account_equity(state, prices, fill_dt)
        for ticker, target_weight in target_weights.items():
            px = price_at_or_before(prices, ticker, fill_dt)
            actual_value = values_after.get(ticker, 0.0)
            target_vs_actual_rows.append(
                {
                    "date": fill_dt.date().isoformat(),
                    "signal_date": signal_dt.date().isoformat(),
                    "ticker": ticker,
                    "target_weight": float(target_weight),
                    "actual_weight": float(actual_value / equity_after) if equity_after > 0 else 0.0,
                    "shares": float(state.shares.get(ticker, 0.0)),
                    "price": px if px is not None else np.nan,
                }
            )
        cash_rows.append({"date": fill_dt.date().isoformat(), "cash_usd": float(state.cash), "equity_usd": float(equity_after), "cash_weight": float(state.cash / equity_after) if equity_after > 0 else np.nan})

        period_end = periods.get(signal_dt, fill_dt)
        active_tickers = set(state.shares.keys()) | set(target_weights.keys())
        period_marks = mark_dates_for_period(active_tickers, prices, fill_dt, period_end)
        if not period_marks:
            period_marks = [fill_dt]
        for date in period_marks:
            equity, values = account_equity(state, prices, date)
            cash_weight = float(state.cash / equity) if equity > 0 else np.nan
            equity_rows.append(
                {
                    "date": pd.Timestamp(date).date().isoformat(),
                    "equity_usd": float(equity),
                    "cash_usd": float(state.cash),
                    "cash_weight": cash_weight,
                    "stock_value_usd": float(sum(values.values())),
                    "position_count": int(sum(1 for qty in state.shares.values() if abs(qty) > 1e-12)),
                    "fill_mode": fill_mode,
                }
            )
            for ticker, value in values.items():
                px = price_at_or_before(prices, ticker, date)
                holdings_rows.append(
                    {
                        "date": pd.Timestamp(date).date().isoformat(),
                        "ticker": ticker,
                        "shares": float(state.shares.get(ticker, 0.0)),
                        "price": px if px is not None else np.nan,
                        "market_value_usd": float(value),
                        "weight": float(value / equity) if equity > 0 else np.nan,
                        "cost_basis": float(state.cost_basis.get(ticker, np.nan)),
                        "unrealized_pnl_usd": float(value - state.shares.get(ticker, 0.0) * state.cost_basis.get(ticker, 0.0)),
                    }
                )

    equity_df = pd.DataFrame(equity_rows).drop_duplicates("date", keep="last").sort_values("date")
    trades_df = pd.DataFrame(trade_rows)
    holdings_df = pd.DataFrame(holdings_rows)
    cash_df = pd.DataFrame(cash_rows)
    target_vs_actual_df = pd.DataFrame(target_vs_actual_rows)
    metrics = calc_metrics(equity_df, trades_df, starting_capital)
    metrics.update(
        {
            "portfolio_kind": portfolio_kind,
            "fill_mode": fill_mode,
            "price_mode": "adjusted_close",
            "integer_shares": bool(integer_shares),
            "cost_bps_per_side": float(cost_bps),
            "target_book": str(target_book),
            "target_book_filter": champion_filters,
            "target_book_filter_source": champion_filter_source,
            "target_book_filter_warning": champion_filter_warning,
            "price_cache": str(price_cache),
            "valid_for_production": bool(metrics.get("status") == "completed" and fill_mode == "next_close" and integer_shares),
            "max_fill_lag_days": int(max_fill_lag_days),
            "tail_row_fill_fallback_same_close_enabled": bool(tail_row_fill_fallback_same_close),
            "tail_row_fill_fallback_activated_at": (
                str(pd.Timestamp(tail_fallback_activated_signal_dt).date())
                if tail_fallback_activated_signal_dt is not None
                else None
            ),
            **weight_diag,
        }
    )

    equity_df.to_csv(output_dir / "equity_curve.csv", index=False)
    trades_df.to_csv(output_dir / "trades.csv", index=False)
    holdings_df.to_csv(output_dir / "holdings_daily.csv", index=False)
    if not holdings_df.empty:
        weekly = holdings_df.copy()
        weekly["date"] = pd.to_datetime(weekly["date"], errors="coerce")
        weekly = weekly.dropna(subset=["date"])
        weekly["week_end_date"] = weekly["date"].dt.to_period("W-FRI").dt.end_time.dt.normalize()
        weekly = weekly.sort_values("date").drop_duplicates(["week_end_date", "ticker"], keep="last")
        weekly.to_csv(output_dir / "holdings_weekly.csv", index=False)
    cash_df.to_csv(output_dir / "cash_ledger.csv", index=False)
    target_vs_actual_df.to_csv(output_dir / "target_vs_actual_weights.csv", index=False)
    if not equity_df.empty:
        latest_date = pd.Timestamp(pd.to_datetime(equity_df["date"], errors="coerce").dropna().max()).normalize()
        account_state, latest_positions = latest_account_state(
            state=state,
            prices=prices,
            as_of_date=latest_date,
            metrics=metrics,
            trades=trades_df,
            portfolio_kind=portfolio_kind,
            starting_capital=starting_capital,
            fill_mode=fill_mode,
            cost_bps=cost_bps,
            integer_shares=integer_shares,
        )
        latest_positions.to_csv(output_dir / "positions_latest.csv", index=False)
        (output_dir / "account_state_latest.json").write_text(
            json.dumps(account_state, indent=2, default=str),
            encoding="utf-8",
        )
    (output_dir / "metrics.json").write_text(json.dumps(metrics, indent=2, default=str), encoding="utf-8")
    (output_dir / "replay_report.md").write_text(render_report(metrics), encoding="utf-8")
    return metrics


def render_report(metrics: dict[str, Any]) -> str:
    if metrics.get("status") != "completed":
        return "# Broker Ledger Replay\n\nStatus: blocked\n\nReason: " + str(metrics.get("reason", "unknown")) + "\n"
    return "\n".join(
        [
            "# Broker Ledger Replay",
            "",
            f"- Portfolio: `{metrics.get('portfolio_kind')}`",
            f"- Metric mode: `{metrics.get('metric_mode')}`",
            f"- Fill mode: `{metrics.get('fill_mode')}`",
            f"- Price mode: `{metrics.get('price_mode')}`",
            f"- Integer shares: `{metrics.get('integer_shares')}`",
            f"- CAGR: {safe_float(metrics.get('cagr')):.2%}",
            f"- Sharpe: {safe_float(metrics.get('sharpe')):.3f}",
            f"- MaxDD: {safe_float(metrics.get('max_dd')):.2%}",
            f"- Ending capital: ${safe_float(metrics.get('ending_capital_usd')):,.2f}",
            f"- Trade count: {int(safe_float(metrics.get('trade_count')))}",
            f"- Total fees: ${safe_float(metrics.get('total_fees_usd')):,.2f}",
            "",
            "This replay uses account cash and shares. It is stricter than target-weight metrics.",
            "",
        ]
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-book", required=True)
    parser.add_argument("--price-cache", default="cache_prices")
    parser.add_argument("--output-dir", default=DEFAULT_OUT_DIR)
    parser.add_argument("--portfolio-kind", choices=["main", "concentrated"], default="main")
    parser.add_argument("--starting-capital", type=float, default=100000.0)
    parser.add_argument("--fill-mode", choices=["next_close", "next_open", "same_close"], default="next_close")
    parser.add_argument("--cost-bps", type=float, default=25.0)
    parser.add_argument("--fractional-shares", action="store_true")
    parser.add_argument("--max-reasonable-weight-sum", type=float, default=1.05)
    parser.add_argument("--max-fill-lag-days", type=int, default=7)
    parser.add_argument(
        "--tail-row-fill-fallback-same-close",
        action="store_true",
        help=(
            "F4 (2026-05-14): when the LAST signal_date in target_book "
            "cannot fill under next_close/next_open (typically because the "
            "latest cache close IS the signal_date), retry that single row "
            "with same_close. Closes the 'N pending orders' gap between "
            "recommendation and operating account. Historical rows still "
            "use the requested fill_mode."
        ),
    )
    parser.add_argument("--concentrated-target-stock-n", type=int, default=0)
    parser.add_argument("--concentrated-weighting-mode", default="")
    parser.add_argument("--concentrated-rebalance-interval-months", type=int, default=0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = replay(
        target_book=repo_path(args.target_book),
        price_cache=repo_path(args.price_cache),
        output_dir=repo_path(args.output_dir),
        portfolio_kind=args.portfolio_kind,
        starting_capital=args.starting_capital,
        fill_mode=args.fill_mode,
        cost_bps=args.cost_bps,
        integer_shares=not bool(args.fractional_shares),
        max_reasonable_weight_sum=args.max_reasonable_weight_sum,
        max_fill_lag_days=args.max_fill_lag_days,
        tail_row_fill_fallback_same_close=bool(args.tail_row_fill_fallback_same_close),
        concentrated_champion_filters={
            key: value
            for key, value in {
                "target_stock_names": args.concentrated_target_stock_n or None,
                "weighting_mode": args.concentrated_weighting_mode or None,
                "active_rebalance_interval_months": args.concentrated_rebalance_interval_months or None,
            }.items()
            if value is not None
        },
    )
    print(json.dumps(payload, indent=2, default=str))
    return 0 if payload.get("status") == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
