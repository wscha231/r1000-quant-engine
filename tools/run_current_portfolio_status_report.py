#!/usr/bin/env python3
"""Mark current broker-ledger holdings to a requested latest close and report.

This is a reporting sidecar. It does not rebuild signals, change targets, or
submit simulated trades. It extends the existing broker-ledger equity curve from
the last replay date by holding the current shares constant and marking them to
market with fetched closes.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


PORTFOLIOS = ("main", "concentrated")
HORIZONS: list[tuple[str, pd.DateOffset | None]] = [
    ("1M", pd.DateOffset(months=1)),
    ("3M", pd.DateOffset(months=3)),
    ("6M", pd.DateOffset(months=6)),
    ("1Y", pd.DateOffset(years=1)),
    ("2Y", pd.DateOffset(years=2)),
    ("FULL", None),
]


@dataclass(frozen=True)
class PortfolioExtension:
    portfolio: str
    requested_as_of_date: str
    evaluated_as_of_date: str
    source_last_date: str
    extension_rows: int
    missing_tickers: list[str]
    carried_forward_tickers: list[str]
    equity_curve: pd.DataFrame
    holdings_latest: pd.DataFrame
    target_latest: pd.DataFrame
    projected_latest: pd.DataFrame
    transition_latest: pd.DataFrame
    scorecard: pd.DataFrame


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


def clean_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        out = float(value)
        return out if math.isfinite(out) else default
    except (TypeError, ValueError):
        return default


def clean_ticker(value: Any) -> str:
    text = str(value or "").upper().strip()
    return "" if text in {"", "NAN", "NONE"} else text


def default_requested_as_of() -> str:
    # The app timezone is Asia/Seoul. In normal morning/daytime use, yesterday
    # KST is the latest completed US close. Weekend/holiday gaps are handled by
    # selecting the latest available fetched close on or before this date.
    return (date.today() - timedelta(days=1)).isoformat()


def yf_ticker(ticker: str) -> str:
    # Yahoo Finance uses BRK-B style symbols where most pipeline data uses BRK.B.
    return ticker.replace(".", "-")


def fetch_yfinance_closes(tickers: list[str], start_date: str, end_date: str) -> dict[str, pd.Series]:
    if not tickers:
        return {}
    try:
        import yfinance as yf
    except ImportError:
        return {}

    start = pd.Timestamp(start_date).date().isoformat()
    end = (pd.Timestamp(end_date) + pd.Timedelta(days=1)).date().isoformat()
    out: dict[str, pd.Series] = {}
    for ticker in sorted(set(tickers)):
        try:
            hist = yf.Ticker(yf_ticker(ticker)).history(start=start, end=end, auto_adjust=True)
        except Exception:
            hist = pd.DataFrame()
        if hist.empty or "Close" not in hist.columns:
            continue
        closes = pd.to_numeric(hist["Close"], errors="coerce").dropna()
        if closes.empty:
            continue
        closes.index = pd.to_datetime(closes.index).tz_localize(None).normalize()
        closes = closes[closes.index <= pd.Timestamp(end_date)]
        if closes.empty:
            continue
        closes.name = ticker
        out[ticker] = closes
    return out


def max_drawdown(equity: pd.Series) -> float:
    if equity.empty:
        return 0.0
    dd = equity / equity.cummax() - 1.0
    return float(dd.min())


def drawdown_details(window: pd.DataFrame) -> dict[str, Any]:
    if window.empty or "date" not in window.columns or "equity_usd" not in window.columns:
        return {
            "max_dd": 0.0,
            "max_dd_peak_date": "",
            "max_dd_trough_date": "",
            "max_dd_peak_equity_usd": np.nan,
            "max_dd_trough_equity_usd": np.nan,
        }
    d = window.copy()
    d["date"] = pd.to_datetime(d["date"], errors="coerce")
    d["equity_usd"] = pd.to_numeric(d["equity_usd"], errors="coerce")
    d = d.dropna(subset=["date", "equity_usd"]).sort_values("date").reset_index(drop=True)
    if d.empty:
        return {
            "max_dd": 0.0,
            "max_dd_peak_date": "",
            "max_dd_trough_date": "",
            "max_dd_peak_equity_usd": np.nan,
            "max_dd_trough_equity_usd": np.nan,
        }
    running_peak = d["equity_usd"].cummax()
    drawdown = d["equity_usd"] / running_peak - 1.0
    trough_pos = int(drawdown.idxmin())
    peak_pos = int(d.loc[:trough_pos, "equity_usd"].idxmax())
    return {
        "max_dd": float(drawdown.iloc[trough_pos]),
        "max_dd_peak_date": pd.Timestamp(d.loc[peak_pos, "date"]).date().isoformat(),
        "max_dd_trough_date": pd.Timestamp(d.loc[trough_pos, "date"]).date().isoformat(),
        "max_dd_peak_equity_usd": clean_float(d.loc[peak_pos, "equity_usd"], np.nan),
        "max_dd_trough_equity_usd": clean_float(d.loc[trough_pos, "equity_usd"], np.nan),
    }


def scorecard_for_horizon(
    equity_curve: pd.DataFrame,
    trades: pd.DataFrame,
    label: str,
    offset: pd.DateOffset | None,
) -> dict[str, Any]:
    if equity_curve.empty:
        return {"horizon": label, "status": "missing"}
    d = equity_curve.copy()
    d["date"] = pd.to_datetime(d["date"], errors="coerce")
    d["equity_usd"] = pd.to_numeric(d["equity_usd"], errors="coerce")
    d = d.dropna(subset=["date", "equity_usd"]).sort_values("date")
    if len(d) < 2:
        return {"horizon": label, "status": "missing"}

    end = pd.Timestamp(d["date"].max())
    if offset is None:
        window = d.copy()
    else:
        start_cut = end - offset
        window = d[d["date"] >= start_cut].copy()
        if len(window) < 2:
            window = d.copy()

    start_date = pd.Timestamp(window["date"].iloc[0])
    end_date = pd.Timestamp(window["date"].iloc[-1])
    years = max((end_date - start_date).days / 365.25, 1 / 252)
    start_eq = clean_float(window["equity_usd"].iloc[0])
    end_eq = clean_float(window["equity_usd"].iloc[-1])
    period_return = end_eq / max(start_eq, 1e-12) - 1.0
    cagr = (end_eq / max(start_eq, 1e-12)) ** (1.0 / years) - 1.0
    returns = window["equity_usd"].pct_change().dropna()
    vol = float(returns.std(ddof=0) * math.sqrt(252.0)) if not returns.empty else 0.0
    sharpe = float((returns.mean() * 252.0) / (vol + 1e-12)) if not returns.empty else 0.0

    td = trades.copy()
    if not td.empty and "date" in td.columns:
        td["date"] = pd.to_datetime(td["date"], errors="coerce")
        td = td[(td["date"] >= start_date) & (td["date"] <= end_date)].copy()
    gross_traded = (
        float(pd.to_numeric(td.get("gross_value", pd.Series(dtype=float)), errors="coerce").fillna(0.0).sum())
        if not td.empty
        else 0.0
    )
    fees = (
        float(pd.to_numeric(td.get("fee_usd", pd.Series(dtype=float)), errors="coerce").fillna(0.0).sum())
        if not td.empty
        else 0.0
    )
    avg_equity = clean_float(window["equity_usd"].mean(), 0.0)
    dd = drawdown_details(window)
    return {
        "horizon": label,
        "status": "completed",
        "start_date": start_date.date().isoformat(),
        "end_date": end_date.date().isoformat(),
        "trading_days": int(len(window)),
        "period_return": float(period_return),
        "cagr": float(cagr),
        "max_dd": dd["max_dd"],
        "max_dd_peak_date": dd["max_dd_peak_date"],
        "max_dd_trough_date": dd["max_dd_trough_date"],
        "max_dd_peak_equity_usd": dd["max_dd_peak_equity_usd"],
        "max_dd_trough_equity_usd": dd["max_dd_trough_equity_usd"],
        "sharpe": sharpe,
        "start_equity_usd": start_eq,
        "end_equity_usd": end_eq,
        "avg_cash_weight": clean_float(
            pd.to_numeric(window.get("cash_weight", pd.Series(dtype=float)), errors="coerce").mean(),
            np.nan,
        ),
        "end_cash_weight": clean_float(window.get("cash_weight", pd.Series([np.nan])).iloc[-1], np.nan),
        "trade_count": int(len(td)),
        "gross_traded_usd": gross_traded,
        "fees_usd": fees,
        "turnover": gross_traded / max(avg_equity, 1e-12),
    }


def build_scorecard(equity_curve: pd.DataFrame, trades: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame([scorecard_for_horizon(equity_curve, trades, label, offset) for label, offset in HORIZONS])


def latest_source_date(equity_curve: pd.DataFrame, positions: pd.DataFrame) -> pd.Timestamp:
    dates: list[pd.Timestamp] = []
    if not equity_curve.empty and "date" in equity_curve.columns:
        parsed = pd.to_datetime(equity_curve["date"], errors="coerce").dropna()
        if not parsed.empty:
            dates.append(pd.Timestamp(parsed.max()).normalize())
    if not positions.empty and "as_of_date" in positions.columns:
        parsed = pd.to_datetime(positions["as_of_date"], errors="coerce").dropna()
        if not parsed.empty:
            dates.append(pd.Timestamp(parsed.max()).normalize())
    if not dates:
        raise ValueError("Could not determine broker-ledger source date")
    return max(dates)


def build_price_panel(
    positions: pd.DataFrame,
    price_history: dict[str, pd.Series],
    source_date: pd.Timestamp,
    requested_as_of: pd.Timestamp,
) -> tuple[pd.DataFrame, list[str], list[str]]:
    tickers = [clean_ticker(t) for t in positions.get("ticker", pd.Series(dtype=str)).tolist()]
    tickers = [t for t in tickers if t]
    dates = sorted(
        {
            pd.Timestamp(dt).normalize()
            for series in price_history.values()
            for dt in series.index
            if source_date < pd.Timestamp(dt).normalize() <= requested_as_of
        }
    )
    missing: list[str] = []
    carried: list[str] = []
    panel = pd.DataFrame(index=pd.DatetimeIndex(dates, name="date"))
    last_prices = {
        clean_ticker(row.get("ticker")): clean_float(row.get("price"), np.nan)
        for row in positions.to_dict("records")
    }
    for ticker in tickers:
        series = price_history.get(ticker, pd.Series(dtype=float)).copy()
        if series.empty:
            missing.append(ticker)
            if not panel.empty:
                panel[ticker] = last_prices.get(ticker, np.nan)
            continue
        series.index = pd.to_datetime(series.index).tz_localize(None).normalize()
        series = series[(series.index > source_date) & (series.index <= requested_as_of)]
        if series.empty:
            carried.append(ticker)
            if not panel.empty:
                panel[ticker] = last_prices.get(ticker, np.nan)
            continue
        if panel.empty:
            panel = pd.DataFrame(index=series.index)
            panel.index.name = "date"
        panel[ticker] = series.reindex(panel.index).ffill()
        first_valid = panel[ticker].first_valid_index()
        if first_valid is not None and first_valid != panel.index[0]:
            panel.loc[panel.index < first_valid, ticker] = last_prices.get(ticker, np.nan)
        panel[ticker] = panel[ticker].ffill().fillna(last_prices.get(ticker, np.nan))
    return panel.sort_index(), sorted(missing), sorted(carried)


def latest_price_from_history(
    ticker: str,
    price_history: dict[str, pd.Series],
    requested_as_of: pd.Timestamp,
    fallback: float = np.nan,
) -> tuple[float, str]:
    ticker = clean_ticker(ticker)
    series = price_history.get(ticker, pd.Series(dtype=float)).copy()
    if series.empty:
        return clean_float(fallback, np.nan), ""
    series.index = pd.to_datetime(series.index).tz_localize(None).normalize()
    series = series[series.index <= requested_as_of]
    series = pd.to_numeric(series, errors="coerce").dropna()
    if series.empty:
        return clean_float(fallback, np.nan), ""
    return clean_float(series.iloc[-1], np.nan), pd.Timestamp(series.index[-1]).date().isoformat()


def target_file_for_portfolio(portfolio: str) -> str:
    return "concentrated_portfolio_latest.csv" if portfolio == "concentrated" else "portfolio_latest.csv"


def build_target_latest(
    latest_run: Path,
    portfolio: str,
    evaluated_as_of: str,
    equity_usd: float,
    price_history: dict[str, pd.Series],
) -> pd.DataFrame:
    target = read_csv(latest_run / target_file_for_portfolio(portfolio))
    if target.empty or "ticker" not in target.columns:
        return pd.DataFrame()
    requested_as_of = pd.Timestamp(evaluated_as_of)
    rows: list[dict[str, Any]] = []
    for raw in target.to_dict("records"):
        ticker = clean_ticker(raw.get("ticker"))
        if not ticker:
            continue
        target_weight = clean_float(raw.get("weight"), 0.0)
        fallback_price = clean_float(
            raw.get("reference_price", raw.get("current_price_live", raw.get("price", np.nan))),
            np.nan,
        )
        price, price_date = latest_price_from_history(ticker, price_history, requested_as_of, fallback_price)
        target_value = equity_usd * target_weight
        rows.append(
            {
                "portfolio": portfolio,
                "date": evaluated_as_of,
                "ticker": ticker,
                "target_weight": target_weight,
                "target_market_value_usd": target_value,
                "estimated_target_shares": target_value / price if math.isfinite(price) and price > 0 else np.nan,
                "latest_price": price,
                "latest_price_date": price_date,
                "rank": raw.get("rank", ""),
                "name": raw.get("Name", raw.get("name", "")),
                "sector": raw.get("sector", ""),
                "score_total": clean_float(raw.get("score_total"), np.nan),
                "score": clean_float(raw.get("score"), np.nan),
                "selection_source": raw.get("concentrated_selection_source", raw.get("portfolio_sleeve_label", "")),
            }
        )
    total_weight = sum(clean_float(row["target_weight"]) for row in rows)
    cash_weight = max(0.0, 1.0 - total_weight)
    if cash_weight > 1e-9:
        rows.append(
            {
                "portfolio": portfolio,
                "date": evaluated_as_of,
                "ticker": "CASH",
                "target_weight": cash_weight,
                "target_market_value_usd": equity_usd * cash_weight,
                "estimated_target_shares": 0.0,
                "latest_price": 1.0,
                "latest_price_date": evaluated_as_of,
                "rank": "",
                "name": "Cash",
                "sector": "Cash",
                "score_total": np.nan,
                "score": np.nan,
                "selection_source": "cash",
            }
        )
    out = pd.DataFrame(rows)
    if not out.empty:
        out = out.sort_values("target_weight", ascending=False).reset_index(drop=True)
    return out


def build_projected_latest(
    latest_run: Path,
    portfolio: str,
    evaluated_as_of: str,
    price_history: dict[str, pd.Series],
) -> pd.DataFrame:
    projected = read_csv(latest_run / "account_ledger_preview" / portfolio / "projected_positions_after_orders.csv")
    metrics = read_json(latest_run / "account_ledger_preview" / portfolio / "preview_metrics.json")
    if projected.empty or "ticker" not in projected.columns:
        return pd.DataFrame()
    requested_as_of = pd.Timestamp(evaluated_as_of)
    rows: list[dict[str, Any]] = []
    for raw in projected.to_dict("records"):
        ticker = clean_ticker(raw.get("ticker"))
        if not ticker:
            continue
        row_type = str(raw.get("row_type") or "").lower()
        shares = clean_float(raw.get("projected_shares"), 0.0)
        fallback_price = clean_float(raw.get("reference_price"), 1.0 if ticker == "CASH" else np.nan)
        price, price_date = latest_price_from_history(ticker, price_history, requested_as_of, fallback_price)
        if ticker == "CASH" or row_type == "cash":
            market_value = clean_float(raw.get("projected_market_value_usd"), 0.0)
            price = 1.0
            price_date = evaluated_as_of
        else:
            market_value = shares * price if math.isfinite(price) else clean_float(raw.get("projected_market_value_usd"), 0.0)
        rows.append(
            {
                "portfolio": portfolio,
                "date": evaluated_as_of,
                "row_type": "cash" if ticker == "CASH" or row_type == "cash" else "equity",
                "ticker": ticker,
                "projected_shares": shares,
                "latest_price": price,
                "latest_price_date": price_date,
                "projected_market_value_usd": market_value,
                "source_projected_weight": clean_float(raw.get("projected_weight"), 0.0),
            }
        )
    total_equity = sum(clean_float(row["projected_market_value_usd"]) for row in rows)
    if not any(row["ticker"] == "CASH" for row in rows):
        cash = clean_float(metrics.get("projected_cash_usd"), 0.0)
        if cash > 1e-9:
            rows.append(
                {
                    "portfolio": portfolio,
                    "date": evaluated_as_of,
                    "row_type": "cash",
                    "ticker": "CASH",
                    "projected_shares": 0.0,
                    "latest_price": 1.0,
                    "latest_price_date": evaluated_as_of,
                    "projected_market_value_usd": cash,
                    "source_projected_weight": clean_float(metrics.get("projected_cash_weight"), 0.0),
                }
            )
            total_equity += cash
    for row in rows:
        row["projected_weight_mark_to_market"] = clean_float(row["projected_market_value_usd"]) / max(total_equity, 1e-12)
    out = pd.DataFrame(rows)
    if not out.empty:
        out = out.sort_values("projected_weight_mark_to_market", ascending=False).reset_index(drop=True)
    return out


def build_transition_latest(
    portfolio: str,
    evaluated_as_of: str,
    current: pd.DataFrame,
    target: pd.DataFrame,
    projected: pd.DataFrame,
    latest_run: Path,
) -> pd.DataFrame:
    current_map = {
        clean_ticker(row.get("ticker")): row
        for row in current.to_dict("records")
        if clean_ticker(row.get("ticker"))
    }
    target_map = {
        clean_ticker(row.get("ticker")): row
        for row in target.to_dict("records")
        if clean_ticker(row.get("ticker"))
    }
    projected_map = {
        clean_ticker(row.get("ticker")): row
        for row in projected.to_dict("records")
        if clean_ticker(row.get("ticker"))
    }
    orders = read_csv(latest_run / "account_ledger_preview" / portfolio / "orders_preview.csv")
    order_map = {
        clean_ticker(row.get("ticker")): row
        for row in orders.to_dict("records")
        if clean_ticker(row.get("ticker"))
    } if not orders.empty else {}
    rows: list[dict[str, Any]] = []
    for ticker in sorted(set(current_map) | set(target_map) | set(projected_map) | set(order_map)):
        cur = current_map.get(ticker, {})
        tgt = target_map.get(ticker, {})
        proj = projected_map.get(ticker, {})
        order = order_map.get(ticker, {})
        current_weight = clean_float(cur.get("weight"), 0.0)
        target_weight = clean_float(tgt.get("target_weight"), clean_float(order.get("target_weight"), 0.0))
        projected_weight = clean_float(proj.get("projected_weight_mark_to_market"), 0.0)
        if ticker == "CASH" and not order:
            side = "HOLD_CASH"
        elif order:
            side = str(order.get("side") or "HOLD")
        elif target_weight > current_weight + 1e-6:
            side = "BUY"
        elif current_weight > target_weight + 1e-6:
            side = "SELL"
        else:
            side = "HOLD"
        rows.append(
            {
                "portfolio": portfolio,
                "date": evaluated_as_of,
                "ticker": ticker,
                "current_weight": current_weight,
                "target_weight": target_weight,
                "projected_weight_mark_to_market": projected_weight,
                "current_market_value_usd": clean_float(cur.get("market_value_usd"), 0.0),
                "target_market_value_usd": clean_float(tgt.get("target_market_value_usd"), 0.0),
                "projected_market_value_usd": clean_float(proj.get("projected_market_value_usd"), 0.0),
                "current_shares": clean_float(cur.get("shares"), 0.0),
                "projected_shares": clean_float(proj.get("projected_shares"), 0.0),
                "order_side": side,
                "order_quantity": clean_float(order.get("quantity"), 0.0),
                "trade_value_delta_usd": clean_float(order.get("trade_value_delta_usd"), 0.0),
                "order_status": str(order.get("status") or ""),
                "transition_delta_weight": target_weight - current_weight,
            }
        )
    out = pd.DataFrame(rows)
    if not out.empty:
        out["_sort_abs_delta"] = out["transition_delta_weight"].abs()
        out = out.sort_values(["_sort_abs_delta", "target_weight", "current_weight"], ascending=False).drop(columns=["_sort_abs_delta"]).reset_index(drop=True)
    return out


def extend_portfolio(
    latest_run: Path,
    portfolio: str,
    requested_as_of_date: str,
    price_history: dict[str, pd.Series],
) -> PortfolioExtension:
    broker_dir = latest_run / "broker_replay" / portfolio
    equity = read_csv(broker_dir / "equity_curve.csv")
    positions = read_csv(broker_dir / "positions_latest.csv")
    trades = read_csv(broker_dir / "trades.csv")
    if equity.empty or positions.empty:
        raise ValueError(f"{portfolio}: missing broker replay equity or positions")

    equity = equity.copy()
    equity["date"] = pd.to_datetime(equity["date"], errors="coerce")
    equity = equity.dropna(subset=["date"]).sort_values("date")
    positions = positions.copy()
    positions["ticker"] = positions["ticker"].map(clean_ticker)
    for col in ["shares", "price", "market_value_usd", "weight", "cost_basis"]:
        if col in positions.columns:
            positions[col] = pd.to_numeric(positions[col], errors="coerce").fillna(0.0)

    source_date = latest_source_date(equity, positions)
    requested_as_of = pd.Timestamp(requested_as_of_date).normalize()
    if requested_as_of <= source_date:
        panel = pd.DataFrame()
        missing: list[str] = []
        carried: list[str] = []
    else:
        panel, missing, carried = build_price_panel(positions, price_history, source_date, requested_as_of)

    extended_rows: list[dict[str, Any]] = []
    extended_holdings_rows: list[dict[str, Any]] = []
    last_equity = equity.iloc[-1].to_dict()
    cash_usd = clean_float(last_equity.get("cash_usd"), 0.0)
    cost_basis_by_ticker = {row["ticker"]: clean_float(row.get("cost_basis"), 0.0) for row in positions.to_dict("records")}
    shares_by_ticker = {row["ticker"]: clean_float(row.get("shares"), 0.0) for row in positions.to_dict("records")}

    for dt, row in panel.iterrows():
        values = {
            ticker: clean_float(shares_by_ticker.get(ticker), 0.0) * clean_float(row.get(ticker), np.nan)
            for ticker in shares_by_ticker
        }
        stock_value = float(sum(v for v in values.values() if math.isfinite(v)))
        total_equity = cash_usd + stock_value
        cash_weight = cash_usd / max(total_equity, 1e-12)
        extended_rows.append(
            {
                "date": pd.Timestamp(dt).date().isoformat(),
                "equity_usd": total_equity,
                "cash_usd": cash_usd,
                "cash_weight": cash_weight,
                "stock_value_usd": stock_value,
                "position_count": int(sum(1 for v in values.values() if v > 1e-9)),
                "fill_mode": "next_close_mark_to_market_extension",
            }
        )
        for ticker, value in values.items():
            price = clean_float(row.get(ticker), np.nan)
            shares = clean_float(shares_by_ticker.get(ticker), 0.0)
            extended_holdings_rows.append(
                {
                    "date": pd.Timestamp(dt).date().isoformat(),
                    "ticker": ticker,
                    "shares": shares,
                    "price": price,
                    "market_value_usd": value,
                    "weight": value / max(total_equity, 1e-12),
                    "cost_basis": cost_basis_by_ticker.get(ticker, np.nan),
                    "unrealized_pnl_usd": (price - cost_basis_by_ticker.get(ticker, np.nan)) * shares
                    if math.isfinite(price)
                    else np.nan,
                }
            )

    extended_curve = pd.concat([equity, pd.DataFrame(extended_rows)], ignore_index=True)
    extended_curve["date"] = pd.to_datetime(extended_curve["date"], errors="coerce")
    extended_curve = extended_curve.dropna(subset=["date"]).drop_duplicates("date", keep="last").sort_values("date")
    evaluated_as_of = pd.Timestamp(extended_curve["date"].max()).date().isoformat()
    if extended_holdings_rows:
        holdings_latest = pd.DataFrame(extended_holdings_rows)
        holdings_latest = holdings_latest[holdings_latest["date"].eq(evaluated_as_of)].copy()
    else:
        holdings_latest = positions.copy()
        holdings_latest["date"] = source_date.date().isoformat()
        holdings_latest = holdings_latest.rename(
            columns={
                "as_of_date": "date",
                "price": "price",
                "weight": "weight",
            }
        )
    latest_cash = clean_float(extended_curve["cash_usd"].iloc[-1], 0.0)
    latest_equity = clean_float(extended_curve["equity_usd"].iloc[-1], 0.0)
    cash_row = {
        "date": evaluated_as_of,
        "ticker": "CASH",
        "shares": 0.0,
        "price": 1.0,
        "market_value_usd": latest_cash,
        "weight": latest_cash / max(latest_equity, 1e-12),
        "cost_basis": 1.0,
        "unrealized_pnl_usd": 0.0,
    }
    holdings_latest = pd.concat([holdings_latest, pd.DataFrame([cash_row])], ignore_index=True)
    holdings_latest["portfolio"] = portfolio
    holdings_latest = holdings_latest.sort_values("weight", ascending=False).reset_index(drop=True)

    target_latest = build_target_latest(
        latest_run,
        portfolio,
        evaluated_as_of,
        latest_equity,
        price_history,
    )
    projected_latest = build_projected_latest(latest_run, portfolio, evaluated_as_of, price_history)
    transition_latest = build_transition_latest(
        portfolio,
        evaluated_as_of,
        holdings_latest,
        target_latest,
        projected_latest,
        latest_run,
    )

    scorecard = build_scorecard(extended_curve, trades)
    return PortfolioExtension(
        portfolio=portfolio,
        requested_as_of_date=requested_as_of.date().isoformat(),
        evaluated_as_of_date=evaluated_as_of,
        source_last_date=source_date.date().isoformat(),
        extension_rows=int(len(extended_rows)),
        missing_tickers=missing,
        carried_forward_tickers=carried,
        equity_curve=extended_curve,
        holdings_latest=holdings_latest,
        target_latest=target_latest,
        projected_latest=projected_latest,
        transition_latest=transition_latest,
        scorecard=scorecard,
    )


def pct(value: Any) -> str:
    return f"{clean_float(value):.2%}"


def money(value: Any) -> str:
    return f"{clean_float(value):,.0f}"


def render_report(summary: dict[str, Any], extensions: dict[str, PortfolioExtension]) -> str:
    lines = [
        "# Current Portfolio Status",
        "",
        f"- Generated at UTC: `{summary['generated_at_utc']}`",
        f"- Requested as-of close: `{summary['requested_as_of_date']}`",
        f"- Evaluation mode: `{summary['evaluation_mode']}`",
        f"- Latest source broker replay date before extension: `{summary['max_source_last_date']}`",
        "",
        "This report is a broker-ledger current-holdings mark-to-market extension. It holds existing shares constant after the source replay date and does not add new recommendations, trades, or production score changes.",
        "",
        "## Portfolio Summary",
        "",
        "| Portfolio | Evaluated Date | Equity | Current Cash | Target Cash | Projected Cash | Positions | Source Last Date | Added Trading Days | Missing Prices |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | ---: | --- |",
    ]
    for portfolio, ext in extensions.items():
        last = ext.equity_curve.iloc[-1]
        equity_rows = ext.holdings_latest[~ext.holdings_latest["ticker"].eq("CASH")]
        target_cash = 1.0 - clean_float(ext.target_latest.get("target_weight", pd.Series(dtype=float)).sum(), 0.0)
        projected_cash = clean_float(
            ext.projected_latest.loc[ext.projected_latest["ticker"].eq("CASH"), "projected_weight_mark_to_market"].sum()
            if not ext.projected_latest.empty and "ticker" in ext.projected_latest.columns
            else np.nan,
            np.nan,
        )
        lines.append(
            f"| {portfolio} | {ext.evaluated_as_of_date} | ${money(last.get('equity_usd'))} | {pct(last.get('cash_weight'))} | {pct(max(0.0, target_cash))} | {pct(projected_cash)} | {len(equity_rows)} | {ext.source_last_date} | {ext.extension_rows} | {', '.join(ext.missing_tickers) or '-'} |"
        )

    lines += [
        "",
        "## Performance Windows",
        "",
        "| Portfolio | Horizon | Start | End | Return | CAGR | MaxDD | MDD Peak | MDD Trough | Sharpe | Turnover | Trades | Cash End |",
        "| --- | --- | --- | --- | ---: | ---: | ---: | --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for portfolio, ext in extensions.items():
        for row in ext.scorecard.to_dict("records"):
            if row.get("status") != "completed":
                continue
            lines.append(
                "| {portfolio} | {horizon} | {start} | {end} | {ret} | {cagr} | {mdd} | {peak} | {trough} | {sharpe:.3f} | {turnover:.2f}x | {trades} | {cash} |".format(
                    portfolio=portfolio,
                    horizon=row.get("horizon"),
                    start=row.get("start_date", ""),
                    end=row.get("end_date", ""),
                    ret=pct(row.get("period_return")),
                    cagr=pct(row.get("cagr")),
                    mdd=pct(row.get("max_dd")),
                    peak=row.get("max_dd_peak_date", ""),
                    trough=row.get("max_dd_trough_date", ""),
                    sharpe=clean_float(row.get("sharpe")),
                    turnover=clean_float(row.get("turnover")),
                    trades=int(clean_float(row.get("trade_count"))),
                    cash=pct(row.get("end_cash_weight")),
                )
            )

    for portfolio, ext in extensions.items():
        target_cash = 1.0 - clean_float(ext.target_latest.get("target_weight", pd.Series(dtype=float)).sum(), 0.0)
        projected_cash = clean_float(
            ext.projected_latest.loc[ext.projected_latest["ticker"].eq("CASH"), "projected_weight_mark_to_market"].sum()
            if not ext.projected_latest.empty and "ticker" in ext.projected_latest.columns
            else np.nan,
            np.nan,
        )
        lines += [
            "",
            f"## {portfolio.title()} Transition Summary",
            "",
            f"- Current cash weight: `{pct(ext.equity_curve.iloc[-1].get('cash_weight'))}`",
            f"- Target cash weight: `{pct(max(0.0, target_cash))}`",
            f"- Projected-after-orders cash weight: `{pct(projected_cash)}`",
            "",
            "| Ticker | Current Wt | Target Wt | Projected Wt | Action | Trade Delta | Current Value | Projected Value |",
            "| --- | ---: | ---: | ---: | --- | ---: | ---: | ---: |",
        ]
        for row in ext.transition_latest.head(30).to_dict("records"):
            lines.append(
                "| {ticker} | {cur} | {tgt} | {proj} | {side} | ${delta} | ${cur_val} | ${proj_val} |".format(
                    ticker=row.get("ticker"),
                    cur=pct(row.get("current_weight")),
                    tgt=pct(row.get("target_weight")),
                    proj=pct(row.get("projected_weight_mark_to_market")),
                    side=row.get("order_side", ""),
                    delta=money(row.get("trade_value_delta_usd")),
                    cur_val=money(row.get("current_market_value_usd")),
                    proj_val=money(row.get("projected_market_value_usd")),
                )
            )

        lines += [
            "",
            f"## {portfolio.title()} Target Holdings",
            "",
            "| Ticker | Target Weight | Target Value | Latest Price | Source | Score |",
            "| --- | ---: | ---: | ---: | --- | ---: |",
        ]
        for row in ext.target_latest.head(30).to_dict("records"):
            lines.append(
                f"| {row.get('ticker')} | {pct(row.get('target_weight'))} | ${money(row.get('target_market_value_usd'))} | {clean_float(row.get('latest_price')):,.2f} | {row.get('selection_source', '')} | {clean_float(row.get('score_total'), np.nan):.3f} |"
            )

        lines += [
            "",
            f"## {portfolio.title()} Projected After Orders",
            "",
            "| Ticker | Projected Weight | Projected Value | Projected Shares | Latest Price |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
        for row in ext.projected_latest.head(30).to_dict("records"):
            lines.append(
                f"| {row.get('ticker')} | {pct(row.get('projected_weight_mark_to_market'))} | ${money(row.get('projected_market_value_usd'))} | {clean_float(row.get('projected_shares')):,.2f} | {clean_float(row.get('latest_price')):,.2f} |"
            )

    for portfolio, ext in extensions.items():
        lines += [
            "",
            f"## {portfolio.title()} Current Holdings",
            "",
            "| Ticker | Weight | Market Value | Shares | Price | Unrealized PnL |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
        for row in ext.holdings_latest.head(50).to_dict("records"):
            lines.append(
                f"| {row.get('ticker')} | {pct(row.get('weight'))} | ${money(row.get('market_value_usd'))} | {clean_float(row.get('shares')):,.2f} | {clean_float(row.get('price')):,.2f} | ${money(row.get('unrealized_pnl_usd'))} |"
            )
    lines.append("")
    return "\n".join(lines)


def build_report(
    args: argparse.Namespace,
    price_loader: Callable[[list[str], str, str], dict[str, pd.Series]] | None = None,
) -> dict[str, Any]:
    latest_run = repo_path(args.latest_run)
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    requested_as_of = args.as_of_date or default_requested_as_of()
    price_loader = price_loader or fetch_yfinance_closes

    all_tickers: list[str] = []
    source_dates: list[str] = []
    for portfolio in PORTFOLIOS:
        positions = read_csv(latest_run / "broker_replay" / portfolio / "positions_latest.csv")
        equity = read_csv(latest_run / "broker_replay" / portfolio / "equity_curve.csv")
        if positions.empty or equity.empty:
            continue
        source_dt = latest_source_date(equity, positions)
        source_dates.append(source_dt.date().isoformat())
        all_tickers.extend(clean_ticker(t) for t in positions.get("ticker", pd.Series(dtype=str)).tolist())
        target = read_csv(latest_run / target_file_for_portfolio(portfolio))
        if not target.empty:
            all_tickers.extend(clean_ticker(t) for t in target.get("ticker", pd.Series(dtype=str)).tolist())
        projected = read_csv(latest_run / "account_ledger_preview" / portfolio / "projected_positions_after_orders.csv")
        if not projected.empty:
            all_tickers.extend(clean_ticker(t) for t in projected.get("ticker", pd.Series(dtype=str)).tolist())

    if not source_dates:
        raise ValueError("No broker replay positions/equity found")
    start_date = min(source_dates)
    price_history = (
        {}
        if args.no_yfinance
        else price_loader(sorted(set(t for t in all_tickers if t and t != "CASH")), start_date, requested_as_of)
    )

    extensions: dict[str, PortfolioExtension] = {}
    for portfolio in PORTFOLIOS:
        ext = extend_portfolio(latest_run, portfolio, requested_as_of, price_history)
        extensions[portfolio] = ext
        pdir = output_dir / portfolio
        pdir.mkdir(parents=True, exist_ok=True)
        ext.equity_curve.to_csv(pdir / "equity_curve_mark_to_market.csv", index=False)
        ext.holdings_latest.to_csv(pdir / "current_holdings_latest.csv", index=False)
        ext.target_latest.to_csv(pdir / "target_holdings_latest.csv", index=False)
        ext.projected_latest.to_csv(pdir / "projected_after_orders_latest.csv", index=False)
        ext.transition_latest.to_csv(pdir / "current_target_projected_transition.csv", index=False)
        ext.scorecard.to_csv(pdir / "performance_scorecard.csv", index=False)
        ext.holdings_latest.to_csv(output_dir / f"{portfolio}_current_holdings_latest.csv", index=False)
        ext.target_latest.to_csv(output_dir / f"{portfolio}_target_holdings_latest.csv", index=False)
        ext.projected_latest.to_csv(output_dir / f"{portfolio}_projected_after_orders_latest.csv", index=False)
        ext.transition_latest.to_csv(output_dir / f"{portfolio}_current_target_projected_transition.csv", index=False)

    combined_scorecard = pd.concat(
        [ext.scorecard.assign(portfolio=portfolio) for portfolio, ext in extensions.items()],
        ignore_index=True,
    )
    combined_scorecard.to_csv(output_dir / "performance_windows.csv", index=False)
    combined_holdings = pd.concat([ext.holdings_latest for ext in extensions.values()], ignore_index=True)
    combined_holdings.to_csv(output_dir / "current_holdings_all.csv", index=False)
    combined_targets = pd.concat([ext.target_latest for ext in extensions.values()], ignore_index=True)
    combined_targets.to_csv(output_dir / "target_holdings_all.csv", index=False)
    combined_projected = pd.concat([ext.projected_latest for ext in extensions.values()], ignore_index=True)
    combined_projected.to_csv(output_dir / "projected_after_orders_all.csv", index=False)
    combined_transition = pd.concat([ext.transition_latest for ext in extensions.values()], ignore_index=True)
    combined_transition.to_csv(output_dir / "current_target_projected_transition_all.csv", index=False)

    summary = {
        "status": "completed",
        "schema_version": "current-portfolio-status-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "latest_run": str(latest_run),
        "output_dir": str(output_dir),
        "requested_as_of_date": requested_as_of,
        "max_source_last_date": max(ext.source_last_date for ext in extensions.values()),
        "evaluation_mode": "current_holdings_mark_to_market_no_new_trades",
        "price_source": "yfinance_auto_adjusted_close" if not args.no_yfinance else "carry_forward_only",
        "portfolios": {
            portfolio: {
                "source_last_date": ext.source_last_date,
                "evaluated_as_of_date": ext.evaluated_as_of_date,
                "extension_rows": ext.extension_rows,
                "missing_tickers": ext.missing_tickers,
                "carried_forward_tickers": ext.carried_forward_tickers,
                "current_holdings_csv": str(output_dir / portfolio / "current_holdings_latest.csv"),
                "target_holdings_csv": str(output_dir / portfolio / "target_holdings_latest.csv"),
                "projected_after_orders_csv": str(output_dir / portfolio / "projected_after_orders_latest.csv"),
                "transition_csv": str(output_dir / portfolio / "current_target_projected_transition.csv"),
                "performance_scorecard_csv": str(output_dir / portfolio / "performance_scorecard.csv"),
                "equity_curve_csv": str(output_dir / portfolio / "equity_curve_mark_to_market.csv"),
            }
            for portfolio, ext in extensions.items()
        },
    }
    write_json(output_dir / "summary.json", summary)
    (output_dir / "report.md").write_text(render_report(summary, extensions), encoding="utf-8")
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default="cloud_results/full_rebuild/latest_global_alpha_universe")
    parser.add_argument("--output-dir", default="outputs/current_portfolio_status")
    parser.add_argument("--as-of-date", default="")
    parser.add_argument("--no-yfinance", action="store_true", help="Do not fetch prices; carry source prices forward.")
    return parser.parse_args()


def main() -> int:
    payload = build_report(parse_args())
    print(json.dumps({"status": payload["status"], "requested_as_of_date": payload["requested_as_of_date"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
