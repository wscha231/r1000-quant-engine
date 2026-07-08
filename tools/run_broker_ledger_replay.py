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
import os
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
CASH_CARRY_MODE_NONE = "none"
CASH_CARRY_MODE_RISK_FREE = "risk_free_rate"
DEFAULT_CASH_RATE_SOURCE = "DGS3MO"
DEFAULT_CASH_RATE_LAG_DAYS = 1
DEFAULT_CASH_CARRY_HAIRCUT_BPS = 50.0
DEFAULT_CASH_CARRY_DAY_COUNT = 365
DEFAULT_CASH_CARRY_CALENDAR_TICKERS = ("SPY", "QQQ")
DEFAULT_BENCHMARK_TICKER = "SPY"
BENCHMARK_METRIC_MODE = "etf_adjusted_close_total_return_proxy"
MISSION_TARGETS = {
    "main": {"cagr_min": 0.35, "max_dd_floor": -0.25},
    "concentrated": {"cagr_min": 0.50, "max_dd_floor": -0.25},
}
DEFAULT_CONCENTRATED_CHAMPION_FILTERS = {
    "target_stock_names": "3",
    "weighting_mode": "score_power",
    "active_rebalance_interval_months": "1",
}
CONCENTRATED_CHAMPION_FILTERS = DEFAULT_CONCENTRATED_CHAMPION_FILTERS
DISABLE_CONCENTRATED_CHAMPION_FILTERS = {"__disable_concentrated_champion_filter__": "true"}


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


def max_drawdown(values: pd.Series) -> float:
    vals = pd.to_numeric(values, errors="coerce").dropna()
    if vals.empty:
        return 0.0
    dd = vals / vals.cummax() - 1.0
    return float(dd.min())


def compounded_return(returns: pd.Series) -> float | None:
    rs = pd.to_numeric(returns, errors="coerce").dropna()
    if rs.empty:
        return None
    return float((1.0 + rs).prod() - 1.0)


def env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on", "enabled"}


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
    if not raw_targets.empty:
        production_policy = raw_targets.get("production_policy")
        target_source = raw_targets.get("operating_target_source")
        is_alphaops_vnext = False
        if production_policy is not None:
            is_alphaops_vnext = is_alphaops_vnext or production_policy.astype(str).eq("alphaops_vnext_production").any()
        if target_source is not None:
            is_alphaops_vnext = is_alphaops_vnext or target_source.astype(str).eq("alphaops_vnext_policy_replay").any()
        if is_alphaops_vnext:
            return {}, "alphaops_vnext_policy_target_book", "legacy concentrated champion filter disabled for AlphaOps vNext production target book"
    if explicit_filters is not None:
        disable = str(explicit_filters.get("__disable_concentrated_champion_filter__") or "").strip().lower()
        if disable in {"1", "true", "yes", "disable", "disabled"}:
            return {}, "disabled_explicit", "concentrated champion filter disabled by caller"
        filters = {str(k): filter_value(v) for k, v in explicit_filters.items() if filter_value(v)}
        filters = {k: v for k, v in filters.items() if not k.startswith("__")}
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


@dataclass(frozen=True)
class CashCarryConfig:
    """Research-only cash interest accounting configuration.

    This is deliberately separate from the official broker-ledger metric. The
    default ``mode=none`` must preserve the historical replay schema and
    metrics exactly.
    """

    mode: str = CASH_CARRY_MODE_NONE
    rate_source: str = DEFAULT_CASH_RATE_SOURCE
    rate_lag_days: int = DEFAULT_CASH_RATE_LAG_DAYS
    haircut_bps: float = DEFAULT_CASH_CARRY_HAIRCUT_BPS
    day_count: int = DEFAULT_CASH_CARRY_DAY_COUNT
    rate_path: Path | None = None


def cash_carry_enabled(config: CashCarryConfig | None) -> bool:
    return bool(config and str(config.mode).strip().lower() == CASH_CARRY_MODE_RISK_FREE)


def resolve_cash_carry_config(
    *,
    mode: str | None = None,
    rate_source: str | None = None,
    rate_lag_days: int | None = None,
    haircut_bps: float | None = None,
    day_count: int | None = None,
    rate_path: str | Path | None = None,
) -> CashCarryConfig:
    env_enabled = env_flag("R1000_BROKER_CASH_CARRY_ENABLED", False)
    resolved_mode = (mode or "").strip().lower()
    if not resolved_mode:
        resolved_mode = CASH_CARRY_MODE_RISK_FREE if env_enabled else CASH_CARRY_MODE_NONE
    source = (rate_source or os.environ.get("R1000_BROKER_CASH_RATE_SOURCE") or DEFAULT_CASH_RATE_SOURCE).strip()
    env_lag = os.environ.get("R1000_BROKER_CASH_RATE_LAG_DAYS")
    env_haircut = os.environ.get("R1000_BROKER_CASH_CARRY_HAIRCUT_BPS")
    env_day_count = os.environ.get("R1000_BROKER_CASH_CARRY_DAY_COUNT")
    env_path = os.environ.get("R1000_BROKER_CASH_RATE_PATH")
    return CashCarryConfig(
        mode=resolved_mode,
        rate_source=source or DEFAULT_CASH_RATE_SOURCE,
        rate_lag_days=int(rate_lag_days if rate_lag_days is not None else safe_float(env_lag, DEFAULT_CASH_RATE_LAG_DAYS)),
        haircut_bps=float(haircut_bps if haircut_bps is not None else safe_float(env_haircut, DEFAULT_CASH_CARRY_HAIRCUT_BPS)),
        day_count=max(1, int(day_count if day_count is not None else safe_float(env_day_count, DEFAULT_CASH_CARRY_DAY_COUNT))),
        rate_path=repo_path(rate_path or env_path) if (rate_path or env_path) else None,
    )


def _cash_rate_cache_candidates(config: CashCarryConfig, price_cache: Path) -> list[Path]:
    if config.rate_path:
        return [config.rate_path]
    source = str(config.rate_source or DEFAULT_CASH_RATE_SOURCE).strip()
    series_id = source.upper()
    key = source.lower()
    names = [
        f"fred_{key}_{series_id}.parquet",
        f"fred_{series_id.lower()}_{series_id}.parquet",
        f"fred_{key}_{series_id}.csv",
        f"fred_{series_id.lower()}_{series_id}.csv",
    ]
    roots = [
        REPO_ROOT / "cache_macro",
        price_cache.parent / "cache_macro",
        Path.cwd() / "cache_macro",
    ]
    out: list[Path] = []
    for root in roots:
        for name in names:
            out.append(root / name)
    return out


def load_cash_rate_series(config: CashCarryConfig, price_cache: Path) -> pd.DataFrame:
    """Load a PIT cash-rate table from the existing FRED cache convention.

    FRED rates are percentages. ``available_from`` is rate date plus a business
    day lag, so same-day observations are never silently used before release.
    """

    if not cash_carry_enabled(config):
        return pd.DataFrame()
    selected_path = next((path for path in _cash_rate_cache_candidates(config, price_cache) if path.exists()), None)
    if selected_path is None:
        return pd.DataFrame()
    try:
        raw = pd.read_parquet(selected_path) if selected_path.suffix.lower() == ".parquet" else pd.read_csv(selected_path)
    except Exception:
        return pd.DataFrame()
    if raw.empty:
        return pd.DataFrame()
    cols = {str(c).strip().lower(): c for c in raw.columns}
    date_col = cols.get("date") or cols.get("rate_date") or raw.columns[0]
    value_col = cols.get("value") or cols.get("rate_pct") or cols.get(str(config.rate_source).lower())
    if value_col is None and len(raw.columns) > 1:
        value_col = raw.columns[1]
    if value_col is None:
        return pd.DataFrame()
    rate_dates = pd.to_datetime(raw[date_col], errors="coerce", utc=True)
    out = pd.DataFrame(
        {
            "rate_date": rate_dates.dt.tz_convert(None).dt.normalize(),
            "rate_pct": pd.to_numeric(raw[value_col], errors="coerce"),
        }
    ).dropna(subset=["rate_date", "rate_pct"])
    if out.empty:
        return pd.DataFrame()
    out = out.sort_values("rate_date").drop_duplicates("rate_date", keep="last")
    out["available_from"] = out["rate_date"] + pd.offsets.BDay(max(0, int(config.rate_lag_days)))
    out["rate_source"] = str(config.rate_source or DEFAULT_CASH_RATE_SOURCE).upper()
    return out.sort_values("available_from").reset_index(drop=True)


def lookup_cash_rate(rate_table: pd.DataFrame, as_of_date: pd.Timestamp) -> dict[str, Any] | None:
    if rate_table.empty or "available_from" not in rate_table.columns:
        return None
    as_of = pd.Timestamp(as_of_date).normalize()
    d = rate_table[pd.to_datetime(rate_table["available_from"], errors="coerce") <= as_of]
    if d.empty:
        return None
    row = d.iloc[-1]
    return {
        "rate_pct": safe_float(row.get("rate_pct")),
        "rate_date": pd.Timestamp(row.get("rate_date")).date().isoformat() if pd.notna(row.get("rate_date")) else None,
        "available_from": pd.Timestamp(row.get("available_from")).date().isoformat() if pd.notna(row.get("available_from")) else None,
        "rate_source": str(row.get("rate_source") or ""),
    }


def filter_concentrated_champion(
    frame: pd.DataFrame,
    portfolio_kind: str,
    champion_filters: dict[str, Any] | None = None,
) -> pd.DataFrame:
    if portfolio_kind != "concentrated" or frame.empty:
        return frame
    out = frame.copy()
    filters = DEFAULT_CONCENTRATED_CHAMPION_FILTERS if champion_filters is None else champion_filters
    if not filters:
        return out
    for col, expected_raw in filters.items():
        if str(col).startswith("__"):
            continue
        if col not in out.columns:
            continue
        expected = filter_value(expected_raw)
        if not expected:
            continue
        values = out[col].map(filter_value)
        mask = values.eq(expected)
        if mask.any():
            out = out[mask].copy()
    return out


def normalize_targets(
    frame: pd.DataFrame,
    portfolio_kind: str,
    champion_filters: dict[str, Any] | None = None,
    *,
    disable_champion_filter: bool = False,
) -> pd.DataFrame:
    if frame.empty or "rebalance_date" not in frame.columns or "ticker" not in frame.columns or "weight" not in frame.columns:
        return pd.DataFrame()
    if disable_champion_filter:
        d = frame.copy()
    else:
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


def target_period_ends(
    targets: pd.DataFrame,
    price_cache: Path,
    calendar_prices: dict[str, pd.DataFrame] | None = None,
    replay_end_date: str | pd.Timestamp | None = None,
    clamp_state: dict[str, Any] | None = None,
) -> dict[pd.Timestamp, pd.Timestamp]:
    dates = sorted(pd.to_datetime(targets["rebalance_date"], errors="coerce").dropna().unique())
    replay_end = pd.to_datetime(replay_end_date, errors="coerce") if replay_end_date else pd.NaT
    replay_end = pd.Timestamp(replay_end).normalize() if pd.notna(replay_end) else None
    out: dict[pd.Timestamp, pd.Timestamp] = {}
    clamped = False
    for i, raw_dt in enumerate(dates):
        dt = pd.Timestamp(raw_dt).normalize()
        if i + 1 < len(dates):
            end_dt = pd.Timestamp(dates[i + 1]).normalize()
            if replay_end is not None and end_dt > replay_end:
                end_dt = replay_end
                clamped = True
            out[dt] = end_dt
            continue
        latest: list[pd.Timestamp] = []
        for ticker in targets.loc[targets["rebalance_date"].eq(dt), "ticker"].astype(str).str.upper().unique():
            if ticker in CASH_TICKERS:
                continue
            px = load_price_series(price_cache, ticker)
            if not px.empty:
                latest.append(pd.Timestamp(px.index.max()).normalize())
        if not latest and calendar_prices:
            for px in calendar_prices.values():
                if not px.empty:
                    latest.append(pd.Timestamp(px.index.max()).normalize())
        if latest:
            end_dt = max(latest)
            if replay_end is not None and end_dt > replay_end:
                end_dt = replay_end
                clamped = True
            out[dt] = end_dt
    if clamp_state is not None:
        clamp_state["replay_end_date_clamped"] = bool(clamped)
    return out


def mark_dates_for_period(
    tickers: set[str],
    prices: dict[str, pd.DataFrame],
    start_dt: pd.Timestamp,
    end_dt: pd.Timestamp,
    calendar_prices: dict[str, pd.DataFrame] | None = None,
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
    for px in (calendar_prices or {}).values():
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


def calendar_fill_date(
    calendar_prices: dict[str, pd.DataFrame],
    signal_date: pd.Timestamp,
    fill_mode: str,
    max_fill_lag_days: int,
) -> pd.Timestamp | None:
    target_date = pd.Timestamp(signal_date)
    if fill_mode in {"next_close", "next_open"}:
        target_date = target_date + pd.Timedelta(days=1)
    candidates: list[pd.Timestamp] = []
    for px in calendar_prices.values():
        actual_dt, _value = price_on_or_after(px, target_date, "close")
        if actual_dt is None:
            continue
        actual = pd.Timestamp(actual_dt).normalize()
        if (actual - pd.Timestamp(target_date).normalize()).days <= int(max_fill_lag_days):
            candidates.append(actual)
    return min(candidates) if candidates else None


@dataclass
class LedgerState:
    cash: float
    shares: dict[str, float] = field(default_factory=dict)
    cost_basis: dict[str, float] = field(default_factory=dict)
    realized_pnl: dict[str, float] = field(default_factory=dict)
    cash_interest_accrued: float = 0.0
    last_cash_accrual_date: pd.Timestamp | None = None


def accrue_cash_interest(
    *,
    state: LedgerState,
    mark_date: pd.Timestamp,
    cash_carry_config: CashCarryConfig,
    cash_rate_table: pd.DataFrame,
) -> dict[str, Any]:
    if not cash_carry_enabled(cash_carry_config):
        return {}
    date = pd.Timestamp(mark_date).normalize()
    if state.last_cash_accrual_date is None:
        state.last_cash_accrual_date = date
        rate = lookup_cash_rate(cash_rate_table, date)
        return {
            "cash_interest_daily": 0.0,
            "cash_interest_accrued_to_date": float(state.cash_interest_accrued),
            "cash_rate_used": safe_float(rate.get("rate_pct")) if rate else np.nan,
            "cash_rate_available_from": rate.get("available_from") if rate else "",
            "cash_rate_source": rate.get("rate_source") if rate else str(cash_carry_config.rate_source).upper(),
            "cash_rate_date": rate.get("rate_date") if rate else "",
            "cash_net_annual_rate": np.nan,
            "cash_interest_days": 0,
        }
    days = max(0, (date - pd.Timestamp(state.last_cash_accrual_date).normalize()).days)
    rate = lookup_cash_rate(cash_rate_table, date)
    raw_rate_pct = safe_float(rate.get("rate_pct")) if rate else 0.0
    gross_annual = max(raw_rate_pct / 100.0, 0.0)
    haircut = max(float(cash_carry_config.haircut_bps), 0.0) / 10000.0
    net_annual = max(gross_annual - haircut, 0.0)
    credit = max(float(state.cash), 0.0) * net_annual * (days / max(float(cash_carry_config.day_count), 1.0))
    if credit > 0:
        state.cash += float(credit)
        state.cash_interest_accrued += float(credit)
    state.last_cash_accrual_date = date
    return {
        "cash_interest_daily": float(credit),
        "cash_interest_accrued_to_date": float(state.cash_interest_accrued),
        "cash_rate_used": raw_rate_pct if rate else np.nan,
        "cash_rate_available_from": rate.get("available_from") if rate else "",
        "cash_rate_source": rate.get("rate_source") if rate else str(cash_carry_config.rate_source).upper(),
        "cash_rate_date": rate.get("rate_date") if rate else "",
        "cash_net_annual_rate": float(net_annual),
        "cash_interest_days": int(days),
    }


def account_equity(state: LedgerState, prices: dict[str, pd.DataFrame], date: pd.Timestamp) -> tuple[float, dict[str, float]]:
    values: dict[str, float] = {}
    equity = float(state.cash)
    for ticker, qty in list(state.shares.items()):
        if abs(qty) <= 1e-12:
            continue
        px = price_at_or_before(prices, ticker, date)
        if px is None or px <= 0:
            px = safe_float(state.cost_basis.get(ticker), 0.0)
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
    *,
    date_range: tuple[str, str] | tuple[str, None] | None = None,
    label: str = "full",
    cash_carry_mode: str = CASH_CARRY_MODE_NONE,
    benchmark_prices: pd.DataFrame | None = None,
    benchmark_ticker: str = DEFAULT_BENCHMARK_TICKER,
) -> dict[str, Any]:
    if equity_curve.empty:
        return {"status": "blocked", "reason": "empty equity curve", "label": label}
    eq_series = pd.to_numeric(equity_curve["equity_usd"], errors="coerce")
    date_series = pd.to_datetime(equity_curve["date"], errors="coerce")
    frame = pd.DataFrame({"date": date_series, "eq": eq_series}).dropna()
    trades_frame = trades.copy()
    if not trades_frame.empty and "date" in trades_frame.columns:
        trades_frame = trades_frame.assign(date=pd.to_datetime(trades_frame["date"], errors="coerce"))
    # Date-range slice. For non-full windows, anchor starting_capital to the
    # equity value at the first in-range row so CAGR/total_return reflect the
    # subwindow, not the original $100k.
    if date_range is not None:
        lo_raw, hi_raw = date_range
        lo = pd.to_datetime(lo_raw, errors="coerce") if lo_raw else None
        hi = pd.to_datetime(hi_raw, errors="coerce") if hi_raw else None
        if lo is not None:
            frame = frame[frame["date"] >= lo]
        if hi is not None:
            frame = frame[frame["date"] <= hi]
        if frame.empty:
            return {
                "status": "blocked",
                "reason": f"empty equity curve for date_range={date_range}",
                "label": label,
                "date_range": [str(lo_raw) if lo_raw else None, str(hi_raw) if hi_raw else None],
            }
        starting_capital = float(frame["eq"].iloc[0])
        if not trades_frame.empty and "date" in trades_frame.columns:
            if lo is not None:
                trades_frame = trades_frame[trades_frame["date"] >= lo]
            if hi is not None:
                trades_frame = trades_frame[trades_frame["date"] <= hi]
    eq = frame["eq"].reset_index(drop=True)
    dates = frame["date"].reset_index(drop=True)
    if eq.empty or dates.empty:
        return {"status": "blocked", "reason": "empty equity values", "label": label}
    returns = eq.pct_change().dropna()
    years = max((dates.max() - dates.min()).days / 365.25, len(returns) / 252.0, 1e-6)
    cagr = float((eq.iloc[-1] / max(starting_capital, 1e-12)) ** (1.0 / years) - 1.0)
    drawdown = eq / eq.cummax() - 1.0
    trough_pos = int(drawdown.values.argmin()) if not drawdown.empty else 0
    peak_pos = int(eq.iloc[: trough_pos + 1].values.argmax()) if not eq.empty else 0
    vol = float(returns.std(ddof=0) * math.sqrt(252.0)) if not returns.empty else 0.0
    sharpe = float((returns.mean() * 252.0) / (vol + 1e-12)) if not returns.empty else 0.0
    fees = float(pd.to_numeric(trades_frame.get("fee_usd", pd.Series(dtype=float)), errors="coerce").fillna(0.0).sum()) if not trades_frame.empty else 0.0
    gross_traded = float(pd.to_numeric(trades_frame.get("gross_value", pd.Series(dtype=float)), errors="coerce").fillna(0.0).sum()) if not trades_frame.empty else 0.0
    cash_weight_series = pd.to_numeric(equity_curve.get("cash_weight", pd.Series(dtype=float)), errors="coerce")
    cash_usd_series = pd.to_numeric(equity_curve.get("cash_usd", pd.Series(dtype=float)), errors="coerce")
    if date_range is not None and not equity_curve.empty:
        eq_dates = pd.to_datetime(equity_curve.get("date"), errors="coerce")
        in_range = pd.Series(True, index=equity_curve.index)
        if date_range[0]:
            in_range &= eq_dates >= pd.to_datetime(date_range[0], errors="coerce")
        if date_range[1]:
            in_range &= eq_dates <= pd.to_datetime(date_range[1], errors="coerce")
        cash_weight_series = cash_weight_series[in_range]
        cash_usd_series = cash_usd_series[in_range]
    base_metric_mode = "broker_ledger_next_close" if str(equity_curve.get("fill_mode", pd.Series([""])).iloc[0]) == "next_close" else "broker_ledger"
    metric_mode = f"{base_metric_mode}_cash_carry" if str(cash_carry_mode).lower() != CASH_CARRY_MODE_NONE else base_metric_mode
    payload = {
        "status": "completed",
        "label": label,
        "date_range": [str(date_range[0]) if date_range and date_range[0] else None,
                       str(date_range[1]) if date_range and date_range[1] else None] if date_range else None,
        "metric_mode": metric_mode,
        "start_date": dates.min().date().isoformat(),
        "end_date": dates.max().date().isoformat(),
        "days": int(len(eq)),
        "years": float(years),
        "starting_capital_usd": float(starting_capital),
        "ending_capital_usd": float(eq.iloc[-1]),
        "total_return": float(eq.iloc[-1] / max(starting_capital, 1e-12) - 1.0),
        "cagr": cagr,
        "sharpe": sharpe,
        "max_dd": float(drawdown.min()),
        "max_dd_peak_date": dates.iloc[peak_pos].date().isoformat() if len(dates) else None,
        "max_dd_trough_date": dates.iloc[trough_pos].date().isoformat() if len(dates) else None,
        "max_dd_peak_equity_usd": float(eq.iloc[peak_pos]) if len(eq) else None,
        "max_dd_trough_equity_usd": float(eq.iloc[trough_pos]) if len(eq) else None,
        "avg_cash_weight": float(cash_weight_series.mean()) if not cash_weight_series.empty else 0.0,
        "min_cash_usd": float(cash_usd_series.min()) if not cash_usd_series.empty else 0.0,
        "trade_count": int(len(trades_frame)),
        "total_fees_usd": fees,
        "gross_traded_usd": gross_traded,
    }
    payload.update(
        benchmark_relative_metrics(
            benchmark_prices=benchmark_prices,
            benchmark_ticker=benchmark_ticker,
            start_date=dates.min(),
            end_date=dates.max(),
            strategy_dates=dates,
            strategy_equity=eq,
            strategy_total_return=payload["total_return"],
            strategy_cagr=cagr,
            strategy_max_dd=payload["max_dd"],
        )
    )
    return payload


def benchmark_relative_metrics(
    *,
    benchmark_prices: pd.DataFrame | None,
    benchmark_ticker: str,
    start_date: Any,
    end_date: Any,
    strategy_dates: pd.Series,
    strategy_equity: pd.Series,
    strategy_total_return: float,
    strategy_cagr: float,
    strategy_max_dd: float,
) -> dict[str, Any]:
    ticker = str(benchmark_ticker or "").strip().upper()
    base = {
        "benchmark_ticker": ticker,
        "benchmark_metric_mode": BENCHMARK_METRIC_MODE,
        "benchmark_status": "unavailable",
    }
    if not ticker:
        base["benchmark_status"] = "disabled"
        return base
    if benchmark_prices is None or benchmark_prices.empty or "close" not in benchmark_prices.columns:
        return base
    start_ts = pd.to_datetime(start_date, errors="coerce")
    end_ts = pd.to_datetime(end_date, errors="coerce")
    if pd.isna(start_ts) or pd.isna(end_ts):
        return base
    actual_start, start_px = price_on_or_after(benchmark_prices, start_ts, "close")
    actual_end, end_px = price_on_or_before(benchmark_prices, end_ts, "close")
    if actual_start is None or actual_end is None or start_px is None or end_px is None or actual_end <= actual_start:
        return base
    years = max((pd.Timestamp(actual_end).normalize() - pd.Timestamp(actual_start).normalize()).days / 365.25, 1e-6)
    total_return = float(end_px / max(float(start_px), 1e-12) - 1.0)
    cagr = float((end_px / max(float(start_px), 1e-12)) ** (1.0 / years) - 1.0)
    base.update(
        {
            "benchmark_status": "completed",
            "benchmark_role": "canonical_research_reporting",
            "benchmark_relative_reporting_only": True,
            "benchmark_relative_gate_input": False,
            "benchmark_relative_public_claim_allowed": False,
            "benchmark_start_date": pd.Timestamp(actual_start).date().isoformat(),
            "benchmark_end_date": pd.Timestamp(actual_end).date().isoformat(),
            "benchmark_start_price": float(start_px),
            "benchmark_end_price": float(end_px),
            "benchmark_total_return": total_return,
            "benchmark_cagr": cagr,
            "excess_total_return_vs_benchmark": float(strategy_total_return - total_return),
            "excess_cagr_vs_benchmark": float(strategy_cagr - cagr),
        }
    )
    risk = benchmark_relative_risk_metrics(
        benchmark_prices=benchmark_prices,
        start_date=actual_start,
        end_date=actual_end,
        strategy_dates=strategy_dates,
        strategy_equity=strategy_equity,
        strategy_max_dd=strategy_max_dd,
    )
    base.update(risk)
    return base


def benchmark_relative_risk_metrics(
    *,
    benchmark_prices: pd.DataFrame,
    start_date: Any,
    end_date: Any,
    strategy_dates: pd.Series,
    strategy_equity: pd.Series,
    strategy_max_dd: float,
) -> dict[str, Any]:
    base: dict[str, Any] = {
        "benchmark_relative_risk_status": "unavailable",
    }
    if benchmark_prices.empty or "close" not in benchmark_prices.columns:
        return base
    strat = pd.DataFrame(
        {
            "date": pd.to_datetime(strategy_dates, errors="coerce"),
            "strategy_equity": pd.to_numeric(strategy_equity, errors="coerce"),
        }
    ).dropna()
    if strat.empty:
        return base
    strat["date"] = strat["date"].dt.normalize()
    strat = strat.drop_duplicates("date", keep="last").set_index("date").sort_index()
    bench = benchmark_prices[["close"]].copy()
    bench.index = pd.to_datetime(bench.index, errors="coerce")
    bench = bench[bench.index.notna()].copy()
    bench.index = bench.index.normalize()
    bench = bench.dropna().sort_index()
    bench = bench[~bench.index.duplicated(keep="last")]
    start_ts = pd.Timestamp(start_date).normalize()
    end_ts = pd.Timestamp(end_date).normalize()
    bench = bench[(bench.index >= start_ts) & (bench.index <= end_ts)].rename(columns={"close": "benchmark_close"})
    aligned = strat.join(bench, how="inner").dropna()
    if len(aligned) < 3:
        return base
    strategy_returns = aligned["strategy_equity"].pct_change().dropna()
    benchmark_returns = aligned["benchmark_close"].pct_change().dropna()
    common = pd.concat(
        [strategy_returns.rename("strategy"), benchmark_returns.rename("benchmark")],
        axis=1,
        join="inner",
    ).dropna()
    if common.empty:
        return base
    bench_var = float(common["benchmark"].var(ddof=0))
    beta = float(common["strategy"].cov(common["benchmark"]) / bench_var) if bench_var > 1e-18 else None
    excess_returns = common["strategy"] - common["benchmark"]
    tracking_error = float(excess_returns.std(ddof=0) * math.sqrt(252.0)) if len(excess_returns) > 1 else 0.0
    info_ratio = float((excess_returns.mean() * 252.0) / (tracking_error + 1e-12)) if tracking_error > 0 else None
    beta_alpha = None
    if beta is not None:
        beta_alpha = float((common["strategy"].mean() - beta * common["benchmark"].mean()) * 252.0)
    down_mask = common["benchmark"] < 0
    up_mask = common["benchmark"] > 0
    down_bench = compounded_return(common.loc[down_mask, "benchmark"])
    down_strategy = compounded_return(common.loc[down_mask, "strategy"])
    up_bench = compounded_return(common.loc[up_mask, "benchmark"])
    up_strategy = compounded_return(common.loc[up_mask, "strategy"])
    down_capture = (
        float(down_strategy / down_bench)
        if down_strategy is not None and down_bench is not None and abs(down_bench) > 1e-12
        else None
    )
    up_capture = (
        float(up_strategy / up_bench)
        if up_strategy is not None and up_bench is not None and abs(up_bench) > 1e-12
        else None
    )
    benchmark_dd = max_drawdown(aligned["benchmark_close"])
    base.update(
        {
            "benchmark_relative_risk_status": "completed",
            "benchmark_aligned_observation_count": int(len(aligned)),
            "benchmark_return_observation_count": int(len(common)),
            "benchmark_max_dd": benchmark_dd,
            "relative_max_dd_vs_benchmark": float(strategy_max_dd - benchmark_dd),
            "tracking_error_vs_benchmark": tracking_error,
            "information_ratio_vs_benchmark": info_ratio,
            "beta_vs_benchmark": beta,
            "beta_adjusted_alpha_annualized": beta_alpha,
            "down_capture_vs_benchmark": down_capture,
            "up_capture_vs_benchmark": up_capture,
        }
    )
    return base


def mission_contract_fields(metrics: dict[str, Any], portfolio_kind: str) -> dict[str, Any]:
    target = MISSION_TARGETS.get(str(portfolio_kind).lower())
    if not target:
        return {
            "absolute_mission_status": "not_configured",
            "absolute_mission_pass": False,
            "benchmark_relative_can_override_absolute_mission": False,
        }
    cagr = safe_float(metrics.get("cagr"), default=float("nan"))
    max_dd = safe_float(metrics.get("max_dd"), default=float("nan"))
    cagr_pass = math.isfinite(cagr) and cagr >= float(target["cagr_min"])
    max_dd_pass = math.isfinite(max_dd) and max_dd >= float(target["max_dd_floor"])
    return {
        "absolute_mission_status": "completed",
        "absolute_mission_cagr_threshold": float(target["cagr_min"]),
        "absolute_mission_max_dd_floor": float(target["max_dd_floor"]),
        "absolute_mission_cagr_pass": bool(cagr_pass),
        "absolute_mission_max_dd_pass": bool(max_dd_pass),
        "absolute_mission_pass": bool(cagr_pass and max_dd_pass),
        "benchmark_relative_can_override_absolute_mission": False,
    }


# Stage 0 OOS lock — default windows. R1000_OOS_START / R1000_OOS2_START env
# overrides apply when the CLI flag is omitted.
DEFAULT_OOS_START = "2024-07-01"
DEFAULT_OOS2_START = "2023-01-01"


def calc_metrics_with_oos(
    equity_curve: pd.DataFrame,
    trades: pd.DataFrame,
    starting_capital: float,
    *,
    oos_start: str | None = None,
    oos_end: str | None = None,
    oos2_start: str | None = None,
    oos2_end: str | None = None,
    cash_carry_mode: str = CASH_CARRY_MODE_NONE,
    benchmark_prices: pd.DataFrame | None = None,
    benchmark_ticker: str = DEFAULT_BENCHMARK_TICKER,
) -> dict[str, Any]:
    """Compute metrics over the full window plus IS/OOS slices.

    IS ends one day before oos_start; OOS runs oos_start..oos_end (or to the
    final equity_curve date). A second OOS window (oos2) is computed when
    oos2_start is given; it overlaps OOS by design (longer-horizon sanity).
    """
    full = calc_metrics(
        equity_curve,
        trades,
        starting_capital,
        label="full",
        cash_carry_mode=cash_carry_mode,
        benchmark_prices=benchmark_prices,
        benchmark_ticker=benchmark_ticker,
    )
    splits: dict[str, dict[str, Any]] = {"full": full}
    if oos_start:
        oos_lo = pd.to_datetime(oos_start, errors="coerce")
        if pd.notna(oos_lo):
            is_hi = (oos_lo - pd.Timedelta(days=1)).date().isoformat()
            splits["is"] = calc_metrics(
                equity_curve, trades, starting_capital,
                date_range=(None, is_hi), label="is", cash_carry_mode=cash_carry_mode,
                benchmark_prices=benchmark_prices, benchmark_ticker=benchmark_ticker,
            )
            splits["oos"] = calc_metrics(
                equity_curve, trades, starting_capital,
                date_range=(oos_start, oos_end), label="oos", cash_carry_mode=cash_carry_mode,
                benchmark_prices=benchmark_prices, benchmark_ticker=benchmark_ticker,
            )
    if oos2_start:
        splits["oos2"] = calc_metrics(
            equity_curve, trades, starting_capital,
            date_range=(oos2_start, oos2_end), label="oos2", cash_carry_mode=cash_carry_mode,
            benchmark_prices=benchmark_prices, benchmark_ticker=benchmark_ticker,
        )
    return {
        "full": splits.get("full", {}),
        "is": splits.get("is"),
        "oos": splits.get("oos"),
        "oos2": splits.get("oos2"),
        "oos_start": oos_start,
        "oos_end": oos_end,
        "oos2_start": oos2_start,
        "oos2_end": oos2_end,
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
    if str(metrics.get("cash_carry_mode") or CASH_CARRY_MODE_NONE) != CASH_CARRY_MODE_NONE:
        account.update(
            {
                "cash_carry_mode": metrics.get("cash_carry_mode"),
                "cash_interest_accrued_usd": float(state.cash_interest_accrued),
                "cash_carry_research_only": True,
            }
        )
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
    disable_concentrated_champion_filter: bool = False,
    oos_start: str | None = None,
    oos_end: str | None = None,
    oos2_start: str | None = None,
    oos2_end: str | None = None,
    cash_carry_config: CashCarryConfig | None = None,
    replay_end_date: str | None = None,
    official_baseline_end_date: str | None = None,
    benchmark_ticker: str = DEFAULT_BENCHMARK_TICKER,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    cash_carry_config = cash_carry_config or resolve_cash_carry_config()
    carry_enabled = cash_carry_enabled(cash_carry_config)
    requested_replay_end = pd.to_datetime(replay_end_date, errors="coerce") if replay_end_date else pd.NaT
    if replay_end_date and pd.isna(requested_replay_end):
        payload = {
            "status": "blocked",
            "reason": "invalid_replay_end_date",
            "target_book": str(target_book),
            "price_cache": str(price_cache),
            "requested_replay_end_date": str(replay_end_date),
            "official_baseline_end_date": str(official_baseline_end_date or replay_end_date or ""),
            "metric_mode": "DO_NOT_USE",
            "valid_for_production": False,
            "research_only": True,
        }
        (output_dir / "metrics.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return payload
    requested_replay_end_ts = pd.Timestamp(requested_replay_end).normalize() if pd.notna(requested_replay_end) else None
    requested_replay_end_text = requested_replay_end_ts.date().isoformat() if requested_replay_end_ts is not None else ""
    official_baseline_end_text = str(official_baseline_end_date or requested_replay_end_text or "")
    cash_rate_table = load_cash_rate_series(cash_carry_config, price_cache) if carry_enabled else pd.DataFrame()
    if carry_enabled and cash_rate_table.empty:
        payload = {
            "status": "blocked",
            "reason": "cash_rate_series_unavailable",
            "target_book": str(target_book),
            "price_cache": str(price_cache),
            "cash_carry_mode": cash_carry_config.mode,
            "cash_rate_source": cash_carry_config.rate_source,
            "cash_rate_path": str(cash_carry_config.rate_path) if cash_carry_config.rate_path else "",
            "requested_replay_end_date": requested_replay_end_text,
            "official_baseline_end_date": official_baseline_end_text,
            "metric_mode": "DO_NOT_USE",
            "valid_for_production": False,
            "research_only": True,
        }
        (output_dir / "metrics.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return payload
    raw = read_csv(target_book)
    if disable_concentrated_champion_filter:
        # Research books (e.g. Market Leader N3/N5 variants) carry their own
        # construction policy; coercing them through the production champion
        # filter (target_stock_names=3 etc.) would silently rewrite the book.
        champion_filters, champion_filter_source, champion_filter_warning = {}, "disabled_by_flag", ""
    else:
        champion_filters, champion_filter_source, champion_filter_warning = resolve_concentrated_champion_filters(
            target_book=target_book,
            raw_targets=raw,
            portfolio_kind=portfolio_kind,
            explicit_filters=concentrated_champion_filters,
        )
    targets = normalize_targets(
        raw,
        portfolio_kind,
        champion_filters,
        disable_champion_filter=disable_concentrated_champion_filter,
    )
    target_dates = pd.to_datetime(targets.get("rebalance_date", pd.Series(dtype=str)), errors="coerce").dropna()
    last_target_date = pd.Timestamp(target_dates.max()).normalize() if not target_dates.empty else None
    replay_end_filtered_target_row_count = 0
    replay_end_filtered_target_date_count = 0
    if requested_replay_end_ts is not None and last_target_date is not None and requested_replay_end_ts < last_target_date:
        parsed_dates = pd.to_datetime(targets["rebalance_date"], errors="coerce")
        future_mask = parsed_dates > requested_replay_end_ts
        replay_end_filtered_target_row_count = int(future_mask.sum())
        replay_end_filtered_target_date_count = int(parsed_dates[future_mask].dropna().dt.normalize().nunique())
        targets = targets.loc[~future_mask].copy()
        target_dates = pd.to_datetime(targets.get("rebalance_date", pd.Series(dtype=str)), errors="coerce").dropna()
        if targets.empty or target_dates.empty:
            payload = {
                "status": "blocked",
                "reason": "no_target_rebalance_on_or_before_replay_end_date",
                "target_book": str(target_book),
                "price_cache": str(price_cache),
                "last_target_rebalance_date": last_target_date.date().isoformat(),
                "requested_replay_end_date": requested_replay_end_text,
                "official_baseline_end_date": official_baseline_end_text,
                "replay_end_filtered_target_row_count": replay_end_filtered_target_row_count,
                "replay_end_filtered_target_date_count": replay_end_filtered_target_date_count,
                "metric_mode": "DO_NOT_USE",
                "valid_for_production": False,
                "research_only": True,
            }
            (output_dir / "metrics.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
            return payload
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
    benchmark_ticker = str(benchmark_ticker or "").strip().upper()
    benchmark_prices = load_price_series(price_cache, benchmark_ticker) if benchmark_ticker else pd.DataFrame()
    calendar_prices: dict[str, pd.DataFrame] = {}
    if carry_enabled:
        for ticker in DEFAULT_CASH_CARRY_CALENDAR_TICKERS:
            px = load_price_series(price_cache, ticker)
            if not px.empty:
                calendar_prices[ticker] = px
                break
        if not calendar_prices:
            payload = {
                "status": "blocked",
                "reason": "cash_carry_calendar_unavailable",
                "target_book": str(target_book),
                "price_cache": str(price_cache),
                "cash_carry_mode": cash_carry_config.mode,
                "cash_rate_source": cash_carry_config.rate_source,
                "required_calendar_tickers": list(DEFAULT_CASH_CARRY_CALENDAR_TICKERS),
                "metric_mode": "DO_NOT_USE",
                "valid_for_production": False,
                "research_only": True,
                "requested_replay_end_date": requested_replay_end_text,
                "official_baseline_end_date": official_baseline_end_text,
            }
            (output_dir / "metrics.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
            return payload
    clamp_state: dict[str, Any] = {}
    periods = target_period_ends(
        targets,
        price_cache,
        calendar_prices if carry_enabled else None,
        replay_end_date=requested_replay_end_ts,
        clamp_state=clamp_state,
    )
    state = LedgerState(cash=float(starting_capital))
    trade_rows: list[dict[str, Any]] = []
    equity_rows: list[dict[str, Any]] = []
    holdings_rows: list[dict[str, Any]] = []
    cash_rows: list[dict[str, Any]] = []
    target_vs_actual_rows: list[dict[str, Any]] = []
    replay_end_skipped_rebalance_count = 0
    replay_end_skipped_signal_dates: list[str] = []

    for signal_dt in sorted(periods.keys()):
        target = targets[targets["rebalance_date"].eq(signal_dt)].copy()
        if target.empty:
            continue
        fill_dt_by_ticker: dict[str, pd.Timestamp] = {}
        fill_px_by_ticker: dict[str, float] = {}
        for ticker in sorted(set(target["ticker"].astype(str).str.upper()) | set(state.shares.keys())):
            if ticker in CASH_TICKERS:
                continue
            actual_dt, px = fill_price(prices, ticker, signal_dt, fill_mode, max_fill_lag_days)
            if actual_dt is not None and px is not None:
                fill_dt_by_ticker[ticker] = pd.Timestamp(actual_dt).normalize()
                fill_px_by_ticker[ticker] = float(px)
        if not fill_dt_by_ticker:
            if not carry_enabled:
                continue
            fill_dt = calendar_fill_date(calendar_prices, signal_dt, fill_mode, max_fill_lag_days)
            if fill_dt is None:
                continue
        else:
            fill_dt = min(fill_dt_by_ticker.values())
        if requested_replay_end_ts is not None and fill_dt > requested_replay_end_ts:
            replay_end_skipped_rebalance_count += 1
            replay_end_skipped_signal_dates.append(signal_dt.date().isoformat())
            continue
        if carry_enabled:
            accrue_cash_interest(
                state=state,
                mark_date=fill_dt,
                cash_carry_config=cash_carry_config,
                cash_rate_table=cash_rate_table,
            )
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
        cash_row = {"date": fill_dt.date().isoformat(), "cash_usd": float(state.cash), "equity_usd": float(equity_after), "cash_weight": float(state.cash / equity_after) if equity_after > 0 else np.nan}
        if carry_enabled:
            cash_row["cash_interest_accrued_to_date"] = float(state.cash_interest_accrued)
        cash_rows.append(cash_row)

        period_end = periods.get(signal_dt, fill_dt)
        active_tickers = set(state.shares.keys()) | set(target_weights.keys())
        period_marks = mark_dates_for_period(active_tickers, prices, fill_dt, period_end, calendar_prices if carry_enabled else None)
        if not period_marks:
            period_marks = [fill_dt]
        for date in period_marks:
            cash_interest_fields: dict[str, Any] = {}
            if carry_enabled:
                cash_interest_fields = accrue_cash_interest(
                    state=state,
                    mark_date=date,
                    cash_carry_config=cash_carry_config,
                    cash_rate_table=cash_rate_table,
                )
            equity, values = account_equity(state, prices, date)
            cash_weight = float(state.cash / equity) if equity > 0 else np.nan
            equity_row = {
                "date": pd.Timestamp(date).date().isoformat(),
                "equity_usd": float(equity),
                "cash_usd": float(state.cash),
                "cash_weight": cash_weight,
                "stock_value_usd": float(sum(values.values())),
                "position_count": int(sum(1 for qty in state.shares.values() if abs(qty) > 1e-12)),
                "fill_mode": fill_mode,
            }
            if carry_enabled:
                equity_row.update(cash_interest_fields)
            equity_rows.append(equity_row)
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

    equity_df = pd.DataFrame(equity_rows)
    if equity_df.empty or "date" not in equity_df.columns:
        payload = {
            "status": "blocked",
            "reason": "no broker-fillable equity rows were produced; check price coverage and target dates",
            "target_book": str(target_book),
            "price_cache": str(price_cache),
            "target_book_filter": champion_filters,
            "target_book_filter_source": champion_filter_source,
            "target_book_filter_warning": champion_filter_warning,
            "metric_mode": "DO_NOT_USE",
            "valid_for_production": False,
            "research_only": True,
            **weight_diag,
        }
        (output_dir / "metrics.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return payload
    equity_df = equity_df.drop_duplicates("date", keep="last").sort_values("date")
    actual_equity_curve_end = pd.Timestamp(pd.to_datetime(equity_df["date"], errors="coerce").dropna().max()).normalize()
    actual_equity_curve_end_text = actual_equity_curve_end.date().isoformat()
    end_date_matches_official = bool(
        requested_replay_end_ts is None or actual_equity_curve_end == requested_replay_end_ts
    )
    if requested_replay_end_ts is not None and not end_date_matches_official:
        payload = {
            "status": "blocked",
            "reason": "replay_end_date_not_observed",
            "target_book": str(target_book),
            "price_cache": str(price_cache),
            "requested_replay_end_date": requested_replay_end_text,
            "actual_equity_curve_end_date": actual_equity_curve_end_text,
            "replay_end_date_clamped": bool(clamp_state.get("replay_end_date_clamped", False)),
            "replay_end_skipped_rebalance_count": int(replay_end_skipped_rebalance_count),
            "replay_end_skipped_signal_dates": replay_end_skipped_signal_dates,
            "replay_end_filtered_target_row_count": int(replay_end_filtered_target_row_count),
            "replay_end_filtered_target_date_count": int(replay_end_filtered_target_date_count),
            "official_baseline_end_date": official_baseline_end_text,
            "end_date_matches_official": False,
            "metric_mode": "DO_NOT_USE",
            "valid_for_production": False,
            "research_only": True,
            **weight_diag,
        }
        (output_dir / "metrics.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
        equity_df.to_csv(output_dir / "equity_curve.csv", index=False)
        return payload
    trades_df = pd.DataFrame(trade_rows)
    holdings_df = pd.DataFrame(holdings_rows)
    cash_df = pd.DataFrame(cash_rows)
    target_vs_actual_df = pd.DataFrame(target_vs_actual_rows)
    metrics = calc_metrics(
        equity_df,
        trades_df,
        starting_capital,
        cash_carry_mode=cash_carry_config.mode,
        benchmark_prices=benchmark_prices,
        benchmark_ticker=benchmark_ticker,
    )
    # Stage 0 OOS lock — IS/OOS slices computed alongside the full-window
    # metrics. Top-level fields are preserved so existing consumers
    # (portfolio_system_guard, run_local.py verdict) keep working; the windows
    # live under metrics["windows"].
    if oos_start or oos2_start:
        windows = calc_metrics_with_oos(
            equity_df, trades_df, starting_capital,
            oos_start=oos_start, oos_end=oos_end,
            oos2_start=oos2_start, oos2_end=oos2_end,
            cash_carry_mode=cash_carry_config.mode,
            benchmark_prices=benchmark_prices,
            benchmark_ticker=benchmark_ticker,
        )
        metrics["windows"] = windows
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
            "requested_replay_end_date": requested_replay_end_text,
            "actual_equity_curve_end_date": actual_equity_curve_end_text,
            "replay_end_date_clamped": bool(clamp_state.get("replay_end_date_clamped", False)),
            "replay_end_skipped_rebalance_count": int(replay_end_skipped_rebalance_count),
            "replay_end_skipped_signal_dates": replay_end_skipped_signal_dates,
            "replay_end_filtered_target_row_count": int(replay_end_filtered_target_row_count),
            "replay_end_filtered_target_date_count": int(replay_end_filtered_target_date_count),
            "official_baseline_end_date": official_baseline_end_text,
            "end_date_matches_official": end_date_matches_official,
            "valid_for_production": bool(metrics.get("status") == "completed" and fill_mode == "next_close" and integer_shares and not carry_enabled),
            "max_fill_lag_days": int(max_fill_lag_days),
            **weight_diag,
        }
    )
    metrics.update(mission_contract_fields(metrics, portfolio_kind))
    metrics.update(
        {
            "benchmark_relative_metric_scope": "diagnostic_reporting_only",
            "benchmark_relative_public_claim_allowed": False,
            "benchmark_relative_forbidden_label": "benchmark_relative_public_claim",
        }
    )
    if carry_enabled:
        metrics.update(
            {
                "cash_carry_mode": cash_carry_config.mode,
                "cash_carry_research_only": True,
                "production_activation_allowed": False,
                "cash_rate_source": str(cash_carry_config.rate_source).upper(),
                "cash_rate_lag_days": int(cash_carry_config.rate_lag_days),
                "cash_carry_haircut_bps": float(cash_carry_config.haircut_bps),
                "cash_carry_day_count": int(cash_carry_config.day_count),
                "cash_interest_accrued_usd": float(state.cash_interest_accrued),
                "cash_interest_accrued_pct_starting_capital": float(state.cash_interest_accrued / max(float(starting_capital), 1e-12)),
                "cash_carry_calendar_tickers": list(calendar_prices.keys()),
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
    benchmark_lines = [f"- Benchmark: `{metrics.get('benchmark_status', 'unavailable')}`"]
    if metrics.get("benchmark_status") == "completed":
        benchmark_lines = [
            f"- Benchmark ({metrics.get('benchmark_ticker', DEFAULT_BENCHMARK_TICKER)} {metrics.get('benchmark_metric_mode', BENCHMARK_METRIC_MODE)}): {safe_float(metrics.get('benchmark_cagr')):.2%}",
            f"- Excess CAGR vs benchmark: {safe_float(metrics.get('excess_cagr_vs_benchmark')):+.2%}",
        ]
        if metrics.get("benchmark_relative_risk_status") == "completed":
            benchmark_lines.extend(
                [
                    f"- Benchmark MaxDD: {safe_float(metrics.get('benchmark_max_dd')):.2%}",
                    f"- Relative MaxDD vs benchmark: {safe_float(metrics.get('relative_max_dd_vs_benchmark')):+.2%}",
                    f"- Down capture vs benchmark: {safe_float(metrics.get('down_capture_vs_benchmark')):.2f}",
                    f"- Beta-adjusted alpha annualized: {safe_float(metrics.get('beta_adjusted_alpha_annualized')):+.2%}",
                    f"- Information ratio vs benchmark: {safe_float(metrics.get('information_ratio_vs_benchmark')):.3f}",
                ]
            )
        benchmark_lines.append("- Benchmark-relative metrics are diagnostic reporting only and do not override the absolute mission contract.")
    mission_lines = []
    if metrics.get("absolute_mission_status") == "completed":
        mission_lines = [
            f"- Absolute mission pass: `{str(bool(metrics.get('absolute_mission_pass'))).lower()}`",
            f"- Absolute CAGR pass: `{str(bool(metrics.get('absolute_mission_cagr_pass'))).lower()}` "
            f"(threshold {safe_float(metrics.get('absolute_mission_cagr_threshold')):.2%})",
            f"- Absolute MaxDD pass: `{str(bool(metrics.get('absolute_mission_max_dd_pass'))).lower()}` "
            f"(floor {safe_float(metrics.get('absolute_mission_max_dd_floor')):.2%})",
        ]
    lines = [
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
            *mission_lines,
            *benchmark_lines,
            f"- Ending capital: ${safe_float(metrics.get('ending_capital_usd')):,.2f}",
            f"- Trade count: {int(safe_float(metrics.get('trade_count')))}",
            f"- Total fees: ${safe_float(metrics.get('total_fees_usd')):,.2f}",
    ]
    if str(metrics.get("cash_carry_mode") or CASH_CARRY_MODE_NONE) != CASH_CARRY_MODE_NONE:
        lines.extend(
            [
                f"- Cash carry mode: `{metrics.get('cash_carry_mode')}`",
                f"- Cash rate source: `{metrics.get('cash_rate_source')}`",
                f"- Cash interest accrued: ${safe_float(metrics.get('cash_interest_accrued_usd')):,.2f}",
                "",
                "Cash-carry metrics are research-only accounting adjustments and are not production promotion evidence.",
            ]
        )
    lines.extend(
        [
            "",
            "This replay uses account cash and shares. It is stricter than target-weight metrics.",
            "",
        ]
    )
    return "\n".join(lines)


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
    parser.add_argument("--concentrated-target-stock-n", type=int, default=0)
    parser.add_argument("--concentrated-weighting-mode", default="")
    parser.add_argument("--concentrated-rebalance-interval-months", type=int, default=0)
    parser.add_argument(
        "--disable-concentrated-champion-filter",
        action="store_true",
        help="Replay the target book exactly as written (no champion-policy coercion). For research books built with their own N/weighting policy.",
    )
    # Stage 0 OOS lock — empty string disables; env R1000_OOS_START / R1000_OOS2_START
    # supply the default when the flag is absent. Pass "" to opt out entirely.
    parser.add_argument(
        "--oos-start",
        default=None,
        help="ISO date; primary OOS window start. Empty string disables. Env R1000_OOS_START supplies the default.",
    )
    parser.add_argument("--oos-end", default=None, help="ISO date; primary OOS window end (optional).")
    parser.add_argument(
        "--oos2-start",
        default=None,
        help="ISO date; secondary OOS window start (longer-horizon sanity). Empty string disables. Env R1000_OOS2_START supplies the default.",
    )
    parser.add_argument("--oos2-end", default=None, help="ISO date; secondary OOS window end (optional).")
    parser.add_argument(
        "--cash-carry-mode",
        choices=[CASH_CARRY_MODE_NONE, CASH_CARRY_MODE_RISK_FREE],
        default=None,
        help="Research-only cash interest accounting mode. Env R1000_BROKER_CASH_CARRY_ENABLED=1 enables risk_free_rate when omitted.",
    )
    parser.add_argument("--cash-rate-source", default=None, help="FRED rate source id, default DGS3MO.")
    parser.add_argument("--cash-rate-path", default=None, help="Optional explicit cached rate CSV/parquet for tests or offline replay.")
    parser.add_argument("--cash-rate-lag-days", type=int, default=None, help="Business-day PIT lag before a FRED rate is usable; default 1.")
    parser.add_argument("--cash-carry-haircut-bps", type=float, default=None, help="Annual haircut subtracted from the raw cash rate; default 50bps.")
    parser.add_argument("--cash-carry-day-count", type=int, default=None, help="Day-count denominator for cash interest; default ACT/365.")
    parser.add_argument("--replay-end-date", default="", help="Optional ISO date that clamps the final replay mark date for apples-to-apples official-window tests.")
    parser.add_argument("--official-baseline-end-date", default="", help="Optional official baseline end date to report alongside replay-end-date.")
    parser.add_argument(
        "--benchmark-ticker",
        default=DEFAULT_BENCHMARK_TICKER,
        help="ETF benchmark ticker for adjusted-close total-return proxy metrics; empty string disables.",
    )
    return parser.parse_args()


def _resolve_oos(flag: str | None, env_name: str, default: str) -> str | None:
    if flag is None:
        return os.environ.get(env_name, default) or None
    return flag or None


def main() -> int:
    args = parse_args()
    explicit_filters = {
        key: value
        for key, value in {
            "target_stock_names": args.concentrated_target_stock_n or None,
            "weighting_mode": args.concentrated_weighting_mode or None,
            "active_rebalance_interval_months": args.concentrated_rebalance_interval_months or None,
        }.items()
        if value is not None
    }
    if args.disable_concentrated_champion_filter:
        explicit_filters = DISABLE_CONCENTRATED_CHAMPION_FILTERS.copy()
    oos_start = _resolve_oos(args.oos_start, "R1000_OOS_START", DEFAULT_OOS_START)
    oos2_start = _resolve_oos(args.oos2_start, "R1000_OOS2_START", DEFAULT_OOS2_START)
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
        disable_concentrated_champion_filter=bool(args.disable_concentrated_champion_filter),
        concentrated_champion_filters=explicit_filters if explicit_filters else None,
        oos_start=oos_start,
        oos_end=args.oos_end or None,
        oos2_start=oos2_start,
        oos2_end=args.oos2_end or None,
        replay_end_date=args.replay_end_date or None,
        official_baseline_end_date=args.official_baseline_end_date or args.replay_end_date or None,
        benchmark_ticker=args.benchmark_ticker,
        cash_carry_config=resolve_cash_carry_config(
            mode=args.cash_carry_mode,
            rate_source=args.cash_rate_source,
            rate_lag_days=args.cash_rate_lag_days,
            haircut_bps=args.cash_carry_haircut_bps,
            day_count=args.cash_carry_day_count,
            rate_path=args.cash_rate_path,
        ),
    )
    print(json.dumps(payload, indent=2, default=str))
    return 0 if payload.get("status") == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
