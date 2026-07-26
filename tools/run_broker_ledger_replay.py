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
from tools.execution_cost_model import (
    EXECUTION_COST_MODE_FIXED,
    EXECUTION_COST_MODE_SPREAD_ADV_IMPACT,
    ExecutionCostConfig,
    ExecutionCostModel,
    summarize_execution_costs,
)
from tools.reserve_asset_policy import (
    BLOCKED_SHORT_HISTORY,
    BROKER_CASH_OR_MMF,
    DGS3MO_CARRY,
    RESERVE_MODES,
    RESERVE_REASONS,
    RESERVE_REASON_SOURCE_HASH_FIELD,
    ReserveAssetPolicy,
    account_reserve_reason_reconciliation,
    apply_reserve_asset_to_targets,
    assert_no_double_count,
    reserve_history_status,
    resolve_reserve_asset_policy,
)


CASH_TICKERS = {"CASH", "__CASH__"}
DEFAULT_OUT_DIR = "outputs/broker_replay"
CASH_CARRY_MODE_NONE = "none"
CASH_CARRY_MODE_RISK_FREE = "risk_free_rate"
DEFAULT_CASH_RATE_SOURCE = "DGS3MO"
DEFAULT_CASH_RATE_LAG_DAYS = 1
DEFAULT_CASH_CARRY_HAIRCUT_BPS = 50.0
DEFAULT_CASH_CARRY_DAY_COUNT = 365
DEFAULT_CASH_CARRY_CALENDAR_TICKERS = ("SPY", "QQQ")
DEFAULT_CONCENTRATED_CHAMPION_FILTERS = {
    "target_stock_names": "3",
    "weighting_mode": "score_power",
    "active_rebalance_interval_months": "1",
}
REPLAY_GENERATED_ARTIFACTS = (
    "equity_curve.csv",
    "trades.csv",
    "holdings_daily.csv",
    "holdings_weekly.csv",
    "cash_ledger.csv",
    "target_vs_actual_weights.csv",
    "partial_resize_decisions.csv",
    "positions_latest.csv",
    "account_state_latest.json",
    "metrics.json",
    "replay_report.md",
    "target_fill_coverage.csv",
)
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
            *RESERVE_REASONS,
            RESERVE_REASON_SOURCE_HASH_FIELD,
        ]
        if c in d.columns
    ]
    d = d[keep].copy()
    if RESERVE_REASON_SOURCE_HASH_FIELD in d.columns:
        for rebalance_date, part in d.groupby("rebalance_date", dropna=False):
            embedded_hashes = {
                str(value).strip().lower()
                for value in part[RESERVE_REASON_SOURCE_HASH_FIELD].tolist()
                if str(value).strip().lower() not in {"", "nan", "none"}
            }
            if len(embedded_hashes) > 1:
                raise ValueError(
                    "conflicting Reserve reason source hashes for "
                    f"{pd.Timestamp(rebalance_date).date().isoformat()}: "
                    f"{sorted(embedded_hashes)}"
                )
    d = d.groupby(["rebalance_date", "ticker"], as_index=False).agg(
        {
            "weight": "sum",
            **({"Name": "last"} if "Name" in d.columns else {}),
            **({"sector": "last"} if "sector" in d.columns else {}),
            **({"portfolio_sleeve_label": "last"} if "portfolio_sleeve_label" in d.columns else {}),
            **({"portfolio_selection_path": "last"} if "portfolio_selection_path" in d.columns else {}),
            **({"concentrated_selection_source": "last"} if "concentrated_selection_source" in d.columns else {}),
            **({"portfolio_defensive_rotation_action": "last"} if "portfolio_defensive_rotation_action" in d.columns else {}),
            **{reason: "sum" for reason in RESERVE_REASONS if reason in d.columns},
            **(
                {RESERVE_REASON_SOURCE_HASH_FIELD: "last"}
                if RESERVE_REASON_SOURCE_HASH_FIELD in d.columns
                else {}
            ),
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
    evidence_end_date: Any = None,
) -> dict[pd.Timestamp, pd.Timestamp]:
    dates = sorted(pd.to_datetime(targets["rebalance_date"], errors="coerce").dropna().unique())
    clamp = pd.to_datetime(evidence_end_date, errors="coerce")
    clamp = pd.Timestamp(clamp).normalize() if not pd.isna(clamp) else None
    out: dict[pd.Timestamp, pd.Timestamp] = {}
    for i, raw_dt in enumerate(dates):
        dt = pd.Timestamp(raw_dt).normalize()
        if clamp is not None and dt > clamp:
            continue
        if i + 1 < len(dates):
            period_end = pd.Timestamp(dates[i + 1]).normalize()
            out[dt] = min(period_end, clamp) if clamp is not None else period_end
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
            period_end = max(latest)
            out[dt] = min(period_end, clamp) if clamp is not None else period_end
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


def build_target_fill_coverage(
    targets: pd.DataFrame,
    prices: dict[str, pd.DataFrame],
    *,
    fill_mode: str,
    max_fill_lag_days: int,
    evidence_end_date: pd.Timestamp | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Audit every transition fill against its actual execution calendar.

    The replay mutates a portfolio synchronously at each signal.  A ticker that
    fills later than the rest of that transition would therefore introduce a
    future price into an earlier account state.  Every replay mode fails closed
    instead of publishing such an asynchronously executed portfolio.  Removed
    target names are included because they require liquidation fills.
    """

    rows: list[dict[str, Any]] = []
    previous_tickers: set[str] = set()
    normalized_evidence_end = (
        pd.Timestamp(evidence_end_date).normalize()
        if evidence_end_date is not None
        else None
    )
    normalized_targets = targets.copy()
    normalized_targets["ticker"] = (
        normalized_targets["ticker"].astype(str).str.upper().str.strip()
    )
    for raw_signal_date in sorted(normalized_targets["rebalance_date"].unique()):
        signal_date = pd.Timestamp(raw_signal_date).normalize()
        current_tickers = {
            str(value).upper()
            for value in normalized_targets.loc[
                normalized_targets["rebalance_date"].eq(raw_signal_date),
                "ticker",
            ]
            if str(value).upper() not in CASH_TICKERS
        }
        transition_tickers = sorted(current_tickers | previous_tickers)
        signal_rows: list[dict[str, Any]] = []
        for ticker in transition_tickers:
            actual_dt, price = fill_price(
                prices,
                ticker,
                signal_date,
                fill_mode,
                max_fill_lag_days,
            )
            normalized_fill = (
                pd.Timestamp(actual_dt).normalize()
                if actual_dt is not None
                else None
            )
            earliest_possible_fill = signal_date
            if fill_mode in {"next_close", "next_open"}:
                earliest_possible_fill += pd.Timedelta(days=1)
            pending_after_evidence = bool(
                normalized_evidence_end is not None
                and (
                    normalized_fill > normalized_evidence_end
                    if normalized_fill is not None
                    else earliest_possible_fill > normalized_evidence_end
                )
            )
            required_for_replay = not pending_after_evidence
            within_evidence = bool(
                normalized_fill is not None
                and (
                    normalized_evidence_end is None
                    or normalized_fill <= normalized_evidence_end
                )
            )
            fillable = bool(
                within_evidence
                and price is not None
                and math.isfinite(float(price))
                and float(price) > 0.0
            )
            signal_rows.append(
                {
                    "signal_date": signal_date.date().isoformat(),
                    "ticker": ticker,
                    "transition_action": (
                        "target_exit"
                        if ticker not in current_tickers
                        else (
                            "target_entry"
                            if ticker not in previous_tickers
                            else "target_rebalance_or_hold"
                        )
                    ),
                    "actual_fill_date": (
                        normalized_fill.date().isoformat()
                        if normalized_fill is not None
                        else ""
                    ),
                    "fill_mode": fill_mode,
                    "max_fill_lag_days": int(max_fill_lag_days),
                    "required_for_replay": required_for_replay,
                    "fillable": fillable,
                    "reason": (
                        ""
                        if fillable
                        else (
                            "fill_after_evidence_end"
                            if pending_after_evidence
                            else "no_fill_within_lag"
                        )
                    ),
                }
            )
        required_signal_rows = [
            row for row in signal_rows if bool(row["required_for_replay"])
        ]
        distinct_fill_dates = {
            str(row["actual_fill_date"])
            for row in required_signal_rows
            if row["fillable"] and row["actual_fill_date"]
        }
        chronology_safe = bool(
            not required_signal_rows
            or (
                all(bool(row["fillable"]) for row in required_signal_rows)
                and len(distinct_fill_dates) == 1
            )
        )
        for row in signal_rows:
            row["signal_fill_date_count"] = len(distinct_fill_dates)
            row["chronology_safe"] = chronology_safe
            if (
                row["required_for_replay"]
                and row["fillable"]
                and len(distinct_fill_dates) > 1
                and not row["reason"]
            ):
                row["reason"] = "asynchronous_transition_fill"
        rows.extend(signal_rows)
        previous_tickers = current_tickers
    frame = pd.DataFrame(
        rows,
        columns=[
            "signal_date",
            "ticker",
            "transition_action",
            "actual_fill_date",
            "fill_mode",
            "max_fill_lag_days",
            "required_for_replay",
            "fillable",
            "signal_fill_date_count",
            "chronology_safe",
            "reason",
        ],
    )
    required = (
        frame.loc[frame["required_for_replay"].astype(bool)].copy()
        if not frame.empty
        else frame.copy()
    )
    pending = (
        frame.loc[~frame["required_for_replay"].astype(bool)].copy()
        if not frame.empty
        else frame.copy()
    )
    missing = (
        required.loc[
            ~required["fillable"].astype(bool),
            ["signal_date", "ticker", "transition_action", "reason"],
        ]
        .to_dict("records")
        if not required.empty
        else []
    )
    asynchronous = (
        required.loc[
            required["signal_fill_date_count"].gt(1),
            ["signal_date", "ticker", "transition_action", "actual_fill_date"],
        ]
        .to_dict("records")
        if not required.empty
        else []
    )
    pending_fills = (
        pending.loc[
            :,
            [
                "signal_date",
                "ticker",
                "transition_action",
                "actual_fill_date",
                "reason",
            ],
        ].to_dict("records")
        if not pending.empty
        else []
    )
    asynchronous_signals = sorted(
        {str(row["signal_date"]) for row in asynchronous}
    )
    audited_count = int(len(frame))
    required_count = int(len(required))
    pending_count = int(len(pending))
    has_replayable_transition = bool(required_count > 0)
    is_cash_only_book = bool(audited_count == 0)
    summary = {
        "audited_target_fill_count": audited_count,
        "audited_transition_fill_count": audited_count,
        "required_target_fill_count": required_count,
        "required_transition_fill_count": required_count,
        "pending_target_fill_count": pending_count,
        "pending_transition_fill_count": pending_count,
        "fillable_target_count": int(required["fillable"].astype(bool).sum())
        if not required.empty
        else 0,
        "missing_target_fill_count": int(len(missing)),
        "missing_transition_fill_count": int(len(missing)),
        "chronology_safe": bool(
            is_cash_only_book
            or (
                has_replayable_transition
                and required["chronology_safe"].astype(bool).all()
            )
        ),
        "asynchronous_signal_count": int(len(asynchronous_signals)),
        "asynchronous_signals": asynchronous_signals[:100],
        "asynchronous_transition_fills": asynchronous[:100],
        "coverage_complete": bool(
            is_cash_only_book
            or (
                has_replayable_transition
                and not missing
                and not asynchronous_signals
            )
        ),
        "pending_target_fills": pending_fills[:100],
        "pending_transition_fills": pending_fills[:100],
        "missing_target_fills": missing[:100],
        "missing_transition_fills": missing[:100],
    }
    return frame, summary


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
    cash_rate_future_use_count: int = 0


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
    prior_date = pd.Timestamp(state.last_cash_accrual_date).normalize()
    days = max(0, (date - prior_date).days)
    haircut = max(float(cash_carry_config.haircut_bps), 0.0) / 10000.0
    credit = 0.0
    latest_rate: dict[str, Any] | None = None
    latest_net_annual = 0.0
    # Forward-fill only from information available on each accrued calendar
    # day.  A rate first published on Monday is never applied backward to the
    # preceding weekend.
    for accrual_date in pd.date_range(prior_date + pd.Timedelta(days=1), date, freq="D"):
        rate = lookup_cash_rate(cash_rate_table, pd.Timestamp(accrual_date))
        raw_rate_pct = safe_float(rate.get("rate_pct")) if rate else 0.0
        gross_annual = max(raw_rate_pct / 100.0, 0.0)
        net_annual = max(gross_annual - haircut, 0.0)
        daily_credit = max(float(state.cash), 0.0) * net_annual / max(float(cash_carry_config.day_count), 1.0)
        if daily_credit > 0:
            state.cash += float(daily_credit)
            state.cash_interest_accrued += float(daily_credit)
            credit += float(daily_credit)
        if rate:
            available = pd.Timestamp(rate.get("available_from")).normalize()
            if available > pd.Timestamp(accrual_date).normalize():
                state.cash_rate_future_use_count += 1
            latest_rate = rate
            latest_net_annual = net_annual
    state.last_cash_accrual_date = date
    return {
        "cash_interest_daily": float(credit),
        "cash_interest_accrued_to_date": float(state.cash_interest_accrued),
        "cash_rate_used": safe_float(latest_rate.get("rate_pct")) if latest_rate else np.nan,
        "cash_rate_available_from": latest_rate.get("available_from") if latest_rate else "",
        "cash_rate_source": latest_rate.get("rate_source") if latest_rate else str(cash_carry_config.rate_source).upper(),
        "cash_rate_date": latest_rate.get("rate_date") if latest_rate else "",
        "cash_net_annual_rate": float(latest_net_annual),
        "cash_interest_days": int(days),
        "cash_rate_future_use_count": int(state.cash_rate_future_use_count),
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
    fill_date: Any = None,
    execution_cost_model: ExecutionCostModel | None = None,
) -> dict[str, Any] | None:
    if price <= 0 or desired_qty <= 1e-12:
        return None
    qty = math.floor(desired_qty) if integer_shares else desired_qty
    if qty <= 1e-12:
        return None

    cost_audit: dict[str, Any] = {}
    if execution_cost_model is None:
        fee_rate = float(cost_bps) / 10000.0
    else:
        quote = execution_cost_model.quote(
            ticker=ticker,
            side=side,
            fill_date=fill_date,
            gross_value=float(qty * price),
            fixed_cost_bps=cost_bps,
        )
        fee_rate = float(quote.total_cost_bps) / 10000.0

    if side == "BUY":
        if execution_cost_model is None:
            max_affordable = state.cash / (price * (1.0 + fee_rate))
            qty = min(qty, math.floor(max_affordable) if integer_shares else max_affordable)
        else:
            # Impact is monotone in order size. Solve against the original
            # desired upper bound so a high first quote cannot permanently
            # lock the order at an unnecessarily small quantity.
            desired_cap = float(qty)

            def affordable(candidate_qty: float) -> bool:
                if candidate_qty <= 0.0:
                    return True
                candidate_quote = execution_cost_model.quote(
                    ticker=ticker,
                    side=side,
                    fill_date=fill_date,
                    gross_value=float(candidate_qty * price),
                    fixed_cost_bps=cost_bps,
                )
                candidate_fee_rate = (
                    float(candidate_quote.total_cost_bps) / 10000.0
                )
                required_cash = (
                    float(candidate_qty)
                    * float(price)
                    * (1.0 + candidate_fee_rate)
                )
                return required_cash <= float(state.cash) + 1e-9

            if integer_shares:
                low = 0
                high = max(0, int(math.floor(desired_cap)))
                while low < high:
                    middle = (low + high + 1) // 2
                    if affordable(float(middle)):
                        low = middle
                    else:
                        high = middle - 1
                qty = float(low)
            else:
                low = 0.0
                high = desired_cap
                for _ in range(60):
                    middle = (low + high) / 2.0
                    if affordable(middle):
                        low = middle
                    else:
                        high = middle
                qty = low
        if qty <= 1e-12:
            return None
        if execution_cost_model is not None:
            quote = execution_cost_model.quote(
                ticker=ticker,
                side=side,
                fill_date=fill_date,
                gross_value=float(qty * price),
                fixed_cost_bps=cost_bps,
            )
            fee_rate = float(quote.total_cost_bps) / 10000.0
            cost_audit = quote.audit()
        if not math.isfinite(fee_rate) or fee_rate >= 1.0:
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
        if execution_cost_model is not None:
            quote = execution_cost_model.quote(
                ticker=ticker,
                side=side,
                fill_date=fill_date,
                gross_value=float(qty * price),
                fixed_cost_bps=cost_bps,
            )
            fee_rate = float(quote.total_cost_bps) / 10000.0
            cost_audit = quote.audit()
        if not math.isfinite(fee_rate) or fee_rate >= 1.0:
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
    order = {
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
    if execution_cost_model is not None:
        order.update(
            {
                "execution_cost_mode": execution_cost_model.config.mode,
                "cost_data_status": cost_audit.get("status", "blocked"),
                **{
                    key: value
                    for key, value in cost_audit.items()
                    if key != "status"
                },
            }
        )
    return order


def redact_execution_performance(
    metrics: dict[str, Any],
    *,
    reason: str,
) -> dict[str, Any]:
    """Keep cost/coverage audit evidence while removing blocked performance."""

    audit_fields = (
        "portfolio_kind",
        "fill_mode",
        "price_mode",
        "integer_shares",
        "cost_bps_per_side",
        "target_book",
        "target_book_filter",
        "target_book_filter_source",
        "target_book_filter_warning",
        "price_cache",
        "stock_evidence_end_date",
        "max_fill_lag_days",
        "execution_cost_mode",
        "execution_cost_schema_version",
        "execution_cost_config",
        "execution_cost_summary",
        "capacity_scenarios",
        "execution_cost_coverage_complete",
        "target_fill_coverage",
        "paper_slippage_issues",
        "trade_count",
        "total_fees_usd",
        "gross_traded_usd",
    )
    payload = {
        key: metrics[key]
        for key in audit_fields
        if key in metrics
    }
    payload.update(
        {
            "status": "blocked",
            "reason": reason,
            "metric_mode": "DO_NOT_USE",
            "performance_fields_redacted": True,
            "research_only": True,
            "production_activation_allowed": False,
            "valid_for_production": False,
        }
    )
    return payload


def calc_metrics(
    equity_curve: pd.DataFrame,
    trades: pd.DataFrame,
    starting_capital: float,
    *,
    date_range: tuple[str, str] | tuple[str, None] | None = None,
    label: str = "full",
    cash_carry_mode: str = CASH_CARRY_MODE_NONE,
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
    return {
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
) -> dict[str, Any]:
    """Compute metrics over the full window plus IS/OOS slices.

    IS ends one day before oos_start; OOS runs oos_start..oos_end (or to the
    final equity_curve date). A second, earlier OOS window (oos2) is computed
    when oos2_start is given. The two OOS windows must not overlap.
    """
    full = calc_metrics(equity_curve, trades, starting_capital, label="full", cash_carry_mode=cash_carry_mode)
    splits: dict[str, dict[str, Any]] = {"full": full}
    oos_lo = pd.to_datetime(oos_start, errors="coerce") if oos_start else pd.NaT
    oos2_lo = pd.to_datetime(oos2_start, errors="coerce") if oos2_start else pd.NaT
    effective_oos2_end = oos2_end
    if pd.notna(oos_lo) and pd.notna(oos2_lo):
        if effective_oos2_end is None:
            effective_oos2_end = (oos_lo - pd.Timedelta(days=1)).date().isoformat()
        oos2_hi = pd.to_datetime(effective_oos2_end, errors="coerce")
        if pd.isna(oos2_hi):
            raise ValueError(f"Invalid oos2_end: {effective_oos2_end!r}")
        if oos2_lo > oos2_hi:
            raise ValueError(
                f"Invalid OOS2 window: start {oos2_start} is after end {effective_oos2_end}"
            )
        if oos2_hi >= oos_lo:
            raise ValueError(
                "OOS windows must be disjoint: "
                f"oos2={oos2_start}..{effective_oos2_end}, oos={oos_start}..{oos_end or 'latest'}"
            )
    if oos_start:
        if pd.notna(oos_lo):
            is_hi = (oos_lo - pd.Timedelta(days=1)).date().isoformat()
            splits["is"] = calc_metrics(
                equity_curve, trades, starting_capital,
                date_range=(None, is_hi), label="is", cash_carry_mode=cash_carry_mode,
            )
            splits["oos"] = calc_metrics(
                equity_curve, trades, starting_capital,
                date_range=(oos_start, oos_end), label="oos", cash_carry_mode=cash_carry_mode,
            )
    if oos2_start:
        splits["oos2"] = calc_metrics(
            equity_curve, trades, starting_capital,
            date_range=(oos2_start, effective_oos2_end), label="oos2", cash_carry_mode=cash_carry_mode,
        )
    return {
        "full": splits.get("full", {}),
        "is": splits.get("is"),
        "oos": splits.get("oos"),
        "oos2": splits.get("oos2"),
        "oos_start": oos_start,
        "oos_end": oos_end,
        "oos2_start": oos2_start,
        "oos2_end": effective_oos2_end,
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
    reserve_policy_payload = metrics.get("reserve_asset_policy") or {}
    reserve_ticker = str(reserve_policy_payload.get("asset_ticker") or "")
    reserve_tradeable = bool(reserve_policy_payload.get("tradeable"))
    rows: list[dict[str, Any]] = []
    for ticker in sorted(state.shares.keys()):
        qty = float(state.shares.get(ticker, 0.0))
        if abs(qty) <= 1e-12:
            continue
        px = price_at_or_before(prices, ticker, as_of_date)
        market_value = float(values.get(ticker, 0.0))
        basis = float(state.cost_basis.get(ticker, np.nan))
        position_row = {
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
        if reserve_policy_payload:
            position_row["reserve_asset"] = bool(reserve_tradeable and ticker == reserve_ticker)
        rows.append(position_row)
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
        "position_count_total": int(len(rows)),
        "equity_position_count": int(
            sum(1 for row in rows if not bool(row.get("reserve_asset")))
        ),
        "reserve_position_count": int(
            sum(1 for row in rows if bool(row.get("reserve_asset")))
        ),
        "fill_mode": fill_mode,
        "cost_bps_per_side": float(cost_bps),
        "integer_shares": bool(integer_shares),
        "metrics": metrics,
        "realized_pnl_by_ticker": {str(k): float(v) for k, v in sorted(state.realized_pnl.items())},
        "total_realized_pnl_usd": float(sum(state.realized_pnl.values())),
        "total_fees_usd": total_fees,
        "positions": rows,
    }
    if reserve_policy_payload:
        reserve_asset_value = float(values.get(reserve_ticker, 0.0)) if reserve_tradeable else 0.0
        reserve_value = float(state.cash) + reserve_asset_value
        target_reconciliation = metrics.get("reserve_reason_reconciliation") or {
            "reserve_weight": reserve_value / equity if equity > 0 else 0.0,
            "reason_weights": {reason: 0.0 for reason in RESERVE_REASONS},
            "mode": reserve_policy_payload.get("mode"),
            "asset_ticker": reserve_ticker,
        }
        actual_reconciliation = account_reserve_reason_reconciliation(
            target_reconciliation,
            actual_reserve_weight=reserve_value / equity if equity > 0 else 0.0,
        )
        account.update(
            {
                "stock_value_usd": float(
                    sum(
                        value
                        for ticker, value in values.items()
                        if not (reserve_tradeable and ticker == reserve_ticker)
                    )
                ),
                "position_count": int(
                    sum(
                        1
                        for row in rows
                        if not bool(row.get("reserve_asset"))
                    )
                ),
                "position_count_total": int(len(rows)),
                "equity_position_count": int(
                    sum(1 for row in rows if not bool(row.get("reserve_asset")))
                ),
                "reserve_position_count": int(
                    sum(1 for row in rows if bool(row.get("reserve_asset")))
                ),
                "reserve_asset_policy": reserve_policy_payload,
                "reserve_asset_value_usd": reserve_asset_value,
                "reserve_value_usd": reserve_value,
                "reserve_weight": float(reserve_value / equity) if equity > 0 else np.nan,
                "target_reserve_reason_reconciliation": target_reconciliation,
                "reserve_reason_reconciliation": actual_reconciliation,
                RESERVE_REASON_SOURCE_HASH_FIELD: actual_reconciliation[
                    RESERVE_REASON_SOURCE_HASH_FIELD
                ],
                **{
                    reason: float(actual_reconciliation["reason_weights"][reason])
                    for reason in RESERVE_REASONS
                },
            }
        )
    if str(metrics.get("cash_carry_mode") or CASH_CARRY_MODE_NONE) != CASH_CARRY_MODE_NONE:
        account.update(
            {
                "cash_carry_mode": metrics.get("cash_carry_mode"),
                "cash_interest_accrued_usd": float(state.cash_interest_accrued),
                "cash_carry_research_only": True,
            }
        )
    if metrics.get("execution_cost_mode"):
        account.update(
            {
                "execution_cost_mode": metrics.get("execution_cost_mode"),
                "execution_cost_schema_version": metrics.get(
                    "execution_cost_schema_version"
                ),
                "execution_cost_coverage_complete": metrics.get(
                    "execution_cost_coverage_complete"
                ),
                "execution_cost_research_only": True,
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
    reserve_asset_policy: ReserveAssetPolicy | None = None,
    reserve_mode: str | None = None,
    partial_resize_two_signal_confirmation: bool = False,
    evidence_end_date: Any = None,
    execution_cost_config: ExecutionCostConfig | None = None,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    execution_cost_config = execution_cost_config or ExecutionCostConfig()
    # A blocked rerun must never inherit performance-bearing files from any
    # prior successful replay, including the fixed-bps control.
    for artifact_name in REPLAY_GENERATED_ARTIFACTS:
        artifact_path = output_dir / artifact_name
        if artifact_path.is_file():
            artifact_path.unlink()
    cash_carry_config = cash_carry_config or resolve_cash_carry_config()
    reserve_explicit = reserve_asset_policy is not None or bool(str(reserve_mode or "").strip())
    if reserve_asset_policy is None:
        compatibility_mode = (
            DGS3MO_CARRY
            if cash_carry_enabled(cash_carry_config)
            else BROKER_CASH_OR_MMF
        )
        reserve_asset_policy = resolve_reserve_asset_policy(
            reserve_mode or compatibility_mode,
            context="current_paper",
        )
    if reserve_asset_policy.cash_interest_enabled and not cash_carry_enabled(cash_carry_config):
        cash_carry_config = CashCarryConfig(
            mode=CASH_CARRY_MODE_RISK_FREE,
            rate_source=cash_carry_config.rate_source,
            rate_lag_days=cash_carry_config.rate_lag_days,
            haircut_bps=cash_carry_config.haircut_bps,
            day_count=cash_carry_config.day_count,
            rate_path=cash_carry_config.rate_path,
        )
    carry_enabled = reserve_asset_policy.cash_interest_enabled
    assert_no_double_count(
        reserve_asset_policy,
        cash_interest_enabled=carry_enabled,
    )
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
    evidence_end = pd.to_datetime(evidence_end_date, errors="coerce")
    evidence_end = (
        pd.Timestamp(evidence_end).normalize() if not pd.isna(evidence_end) else None
    )
    if evidence_end is not None and not targets.empty:
        targets = targets.loc[targets["rebalance_date"] <= evidence_end].copy()
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

    targets, reserve_reason_audit = apply_reserve_asset_to_targets(
        targets,
        policy=reserve_asset_policy,
        weight_col="weight",
        date_col="rebalance_date",
    )

    tickers = sorted({str(x).upper() for x in targets["ticker"].unique() if str(x).upper() not in CASH_TICKERS})
    if execution_cost_config.enabled:
        prices = {
            ticker: load_price_series(
                price_cache,
                ticker,
                include_liquidity=True,
            )
            for ticker in tickers
        }
    else:
        prices = {ticker: load_price_series(price_cache, ticker) for ticker in tickers}
    prices = {ticker: px for ticker, px in prices.items() if not px.empty}
    execution_cost_model = (
        ExecutionCostModel(prices, execution_cost_config)
        if execution_cost_config.enabled
        else None
    )
    if reserve_asset_policy.tradeable:
        stock_prices = [
            px
            for ticker, px in prices.items()
            if ticker != reserve_asset_policy.asset_ticker and not px.empty
        ]
        required_start = pd.Timestamp(targets["rebalance_date"].min()).normalize()
        required_end = max(
            (pd.Timestamp(px.index.max()).normalize() for px in stock_prices),
            default=pd.Timestamp(targets["rebalance_date"].max()).normalize(),
        )
        if evidence_end is not None:
            required_end = min(required_end, evidence_end)
        history = reserve_history_status(
            prices.get(reserve_asset_policy.asset_ticker, pd.DataFrame()),
            policy=reserve_asset_policy,
            required_start=required_start,
            required_end=required_end,
            max_fill_lag_days=max_fill_lag_days,
        )
        if history.get("status") == BLOCKED_SHORT_HISTORY:
            payload = {
                "status": BLOCKED_SHORT_HISTORY,
                "reason": "tradeable Reserve adjusted-close history does not cover the stock book",
                "target_book": str(target_book),
                "price_cache": str(price_cache),
                "reserve_asset_policy": reserve_asset_policy.audit(),
                "reserve_history": history,
                "metric_mode": "DO_NOT_USE",
                "valid_for_production": False,
                "research_only": True,
            }
            (output_dir / "metrics.json").write_text(
                json.dumps(payload, indent=2),
                encoding="utf-8",
            )
            return payload
    target_fill_frame, target_fill_coverage = build_target_fill_coverage(
        targets,
        prices,
        fill_mode=fill_mode,
        max_fill_lag_days=max_fill_lag_days,
        evidence_end_date=evidence_end,
    )
    target_fill_frame.to_csv(
        output_dir / "target_fill_coverage.csv",
        index=False,
    )
    if target_fill_coverage.get("coverage_complete") is not True:
        payload = {
            "status": "blocked",
            "reason": "target_fill_coverage_incomplete",
            "metric_mode": "DO_NOT_USE",
            "portfolio_kind": portfolio_kind,
            "target_book": str(target_book),
            "target_book_filter": champion_filters,
            "target_book_filter_source": champion_filter_source,
            "target_book_filter_warning": champion_filter_warning,
            "price_cache": str(price_cache),
            "fill_mode": fill_mode,
            "max_fill_lag_days": int(max_fill_lag_days),
            "execution_cost_mode": execution_cost_config.mode,
            "execution_cost_config": execution_cost_config.audit(),
            "target_fill_coverage": target_fill_coverage,
            "performance_fields_redacted": True,
            "research_only": True,
            "production_activation_allowed": False,
            "valid_for_production": False,
        }
        (output_dir / "metrics.json").write_text(
            json.dumps(payload, indent=2, default=str),
            encoding="utf-8",
        )
        (output_dir / "replay_report.md").write_text(
            render_report(payload),
            encoding="utf-8",
        )
        return payload
    if execution_cost_model is not None:
        invalid_paper_slippage = execution_cost_model.paper_slippage_issues(
            fixed_cost_bps=cost_bps,
        )
        if invalid_paper_slippage:
            payload = {
                "status": "blocked",
                "reason": "paper_slippage_out_of_bounds",
                "metric_mode": "DO_NOT_USE",
                "portfolio_kind": portfolio_kind,
                "target_book": str(target_book),
                "target_book_filter": champion_filters,
                "target_book_filter_source": champion_filter_source,
                "target_book_filter_warning": champion_filter_warning,
                "price_cache": str(price_cache),
                "fill_mode": fill_mode,
                "max_fill_lag_days": int(max_fill_lag_days),
                "execution_cost_mode": execution_cost_config.mode,
                "execution_cost_config": execution_cost_config.audit(),
                "target_fill_coverage": target_fill_coverage,
                "paper_slippage_issues": invalid_paper_slippage[:100],
                "performance_fields_redacted": True,
                "research_only": True,
                "production_activation_allowed": False,
                "valid_for_production": False,
            }
            (output_dir / "metrics.json").write_text(
                json.dumps(payload, indent=2, default=str),
                encoding="utf-8",
            )
            (output_dir / "replay_report.md").write_text(
                render_report(payload),
                encoding="utf-8",
            )
            return payload
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
            }
            (output_dir / "metrics.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
            return payload
    periods = target_period_ends(
        targets,
        price_cache,
        calendar_prices if carry_enabled else None,
        evidence_end,
    )
    state = LedgerState(cash=float(starting_capital))
    trade_rows: list[dict[str, Any]] = []
    equity_rows: list[dict[str, Any]] = []
    holdings_rows: list[dict[str, Any]] = []
    cash_rows: list[dict[str, Any]] = []
    target_vs_actual_rows: list[dict[str, Any]] = []
    partial_resize_rows: list[dict[str, Any]] = []
    pending_partial_resizes: dict[str, dict[str, Any]] = {}
    previous_target_gross: float | None = None

    for signal_index, signal_dt in enumerate(sorted(periods.keys())):
        target = targets[targets["rebalance_date"].eq(signal_dt)].copy()
        if target.empty:
            continue
        target_weights = {
            str(row.ticker).upper(): safe_float(row.weight)
            for row in target.itertuples(index=False)
            if str(row.ticker).upper() not in CASH_TICKERS
        }
        target_gross = float(
            sum(
                max(0.0, weight)
                for ticker, weight in target_weights.items()
                if ticker != reserve_asset_policy.asset_ticker
            )
        )
        risk_gross_reduction = bool(
            previous_target_gross is not None
            and target_gross < float(previous_target_gross) - 1e-12
        )
        previous_target_gross = target_gross
        fill_dt_by_ticker: dict[str, pd.Timestamp] = {}
        fill_px_by_ticker: dict[str, float] = {}
        for ticker in sorted(set(target["ticker"].astype(str).str.upper()) | set(state.shares.keys())):
            if ticker in CASH_TICKERS:
                continue
            actual_dt, px = fill_price(prices, ticker, signal_dt, fill_mode, max_fill_lag_days)
            normalized_fill = (
                pd.Timestamp(actual_dt).normalize() if actual_dt is not None else None
            )
            if (
                normalized_fill is not None
                and px is not None
                and (evidence_end is None or normalized_fill <= evidence_end)
            ):
                fill_dt_by_ticker[ticker] = normalized_fill
                fill_px_by_ticker[ticker] = float(px)
        if not fill_dt_by_ticker:
            if not carry_enabled:
                continue
            fill_dt = calendar_fill_date(calendar_prices, signal_dt, fill_mode, max_fill_lag_days)
            if fill_dt is None or (
                evidence_end is not None and pd.Timestamp(fill_dt).normalize() > evidence_end
            ):
                continue
        else:
            fill_dt = min(fill_dt_by_ticker.values())
        if carry_enabled:
            accrue_cash_interest(
                state=state,
                mark_date=fill_dt,
                cash_carry_config=cash_carry_config,
                cash_rate_table=cash_rate_table,
            )
        current_equity, current_values = account_equity(state, prices, fill_dt)
        for ticker in sorted(set(state.shares.keys()) - set(target_weights.keys())):
            px = fill_px_by_ticker.get(ticker)
            if px is None:
                continue
            ticker_fill_dt = fill_dt_by_ticker.get(ticker, fill_dt)
            pending_partial_resizes.pop(ticker, None)
            order = execute_order(
                state=state,
                ticker=ticker,
                side="SELL",
                desired_qty=float(state.shares.get(ticker, 0.0)),
                price=px,
                cost_bps=cost_bps,
                integer_shares=integer_shares,
                fill_date=ticker_fill_dt,
                execution_cost_model=execution_cost_model,
            )
            if order:
                order.update({"date": ticker_fill_dt.date().isoformat(), "signal_date": signal_dt.date().isoformat(), "reason": "target_exit", "fill_mode": fill_mode})
                trade_rows.append(order)
                if partial_resize_two_signal_confirmation:
                    partial_resize_rows.append(
                        {
                            "date": ticker_fill_dt.date().isoformat(),
                            "signal_date": signal_dt.date().isoformat(),
                            "ticker": ticker,
                            "action": "execute",
                            "reason": "target_exit_immediate",
                            "side": "SELL",
                            "target_weight": 0.0,
                            "current_weight": np.nan,
                            "diff_value_usd": float(order.get("gross_value", 0.0)) * -1.0,
                            "risk_gross_reduction": risk_gross_reduction,
                        }
                    )
        current_equity, current_values = account_equity(state, prices, fill_dt)
        adjustments: list[
            tuple[str, float, float, float, float, str, pd.Timestamp]
        ] = []
        observed_partial_resize_tickers: set[str] = set()
        for ticker, target_weight in target_weights.items():
            px = fill_px_by_ticker.get(ticker)
            if px is None:
                continue
            ticker_fill_dt = fill_dt_by_ticker.get(ticker, fill_dt)
            current_qty = float(state.shares.get(ticker, 0.0))
            current_value = current_qty * px
            target_value = max(0.0, float(target_weight) * current_equity)
            diff_value = target_value - current_value
            if abs(diff_value) < max(25.0, current_equity * 0.0005):
                continue
            reason = "target_rebalance"
            if partial_resize_two_signal_confirmation:
                side = "BUY" if diff_value > 0 else "SELL"
                current_weight = float(current_value / current_equity) if current_equity > 0 else 0.0
                if current_qty <= 1e-12:
                    pending_partial_resizes.pop(ticker, None)
                    reason = "target_entry_immediate"
                    partial_resize_rows.append(
                        {
                            "date": ticker_fill_dt.date().isoformat(),
                            "signal_date": signal_dt.date().isoformat(),
                            "ticker": ticker,
                            "action": "execute",
                            "reason": reason,
                            "side": side,
                            "target_weight": float(target_weight),
                            "current_weight": current_weight,
                            "diff_value_usd": float(diff_value),
                            "risk_gross_reduction": risk_gross_reduction,
                        }
                    )
                elif side == "SELL" and risk_gross_reduction:
                    pending_partial_resizes.pop(ticker, None)
                    reason = "partial_resize_risk_cut_immediate"
                    partial_resize_rows.append(
                        {
                            "date": ticker_fill_dt.date().isoformat(),
                            "signal_date": signal_dt.date().isoformat(),
                            "ticker": ticker,
                            "action": "execute",
                            "reason": reason,
                            "side": side,
                            "target_weight": float(target_weight),
                            "current_weight": current_weight,
                            "diff_value_usd": float(diff_value),
                            "risk_gross_reduction": True,
                        }
                    )
                else:
                    observed_partial_resize_tickers.add(ticker)
                    pending = pending_partial_resizes.get(ticker)
                    confirmed = bool(
                        pending
                        and pending.get("side") == side
                        and int(pending.get("signal_index", -2)) == signal_index - 1
                    )
                    if not confirmed:
                        pending_partial_resizes[ticker] = {
                            "side": side,
                            "signal_index": signal_index,
                            "signal_date": signal_dt.date().isoformat(),
                        }
                        partial_resize_rows.append(
                            {
                                "date": ticker_fill_dt.date().isoformat(),
                                "signal_date": signal_dt.date().isoformat(),
                                "ticker": ticker,
                                "action": "defer",
                                "reason": "partial_resize_first_signal",
                                "side": side,
                                "target_weight": float(target_weight),
                                "current_weight": current_weight,
                                "diff_value_usd": float(diff_value),
                                "risk_gross_reduction": risk_gross_reduction,
                            }
                        )
                        continue
                    pending_partial_resizes.pop(ticker, None)
                    reason = "partial_resize_second_signal_confirmed"
                    partial_resize_rows.append(
                        {
                            "date": ticker_fill_dt.date().isoformat(),
                            "signal_date": signal_dt.date().isoformat(),
                            "ticker": ticker,
                            "action": "execute",
                            "reason": reason,
                            "side": side,
                            "target_weight": float(target_weight),
                            "current_weight": current_weight,
                            "diff_value_usd": float(diff_value),
                            "risk_gross_reduction": risk_gross_reduction,
                        }
                    )
            adjustments.append(
                (
                    ticker,
                    float(target_weight),
                    float(diff_value),
                    float(px),
                    float(current_value),
                    reason,
                    ticker_fill_dt,
                )
            )
        if partial_resize_two_signal_confirmation:
            stale_pending = [
                ticker
                for ticker, pending in pending_partial_resizes.items()
                if int(pending.get("signal_index", -2)) < signal_index
                and ticker not in observed_partial_resize_tickers
            ]
            for ticker in stale_pending:
                pending_partial_resizes.pop(ticker, None)
        adjustments = sorted(adjustments, key=lambda row: (row[2] > 0, abs(row[2])))
        for (
            ticker,
            target_weight,
            diff_value,
            px,
            _current_value,
            reason,
            ticker_fill_dt,
        ) in adjustments:
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
                fill_date=ticker_fill_dt,
                execution_cost_model=execution_cost_model,
            )
            if order:
                order.update({"date": ticker_fill_dt.date().isoformat(), "signal_date": signal_dt.date().isoformat(), "reason": reason, "target_weight": target_weight, "fill_mode": fill_mode})
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
        cash_row = {
            "date": fill_dt.date().isoformat(),
            "cash_usd": float(state.cash),
            "equity_usd": float(equity_after),
            "cash_weight": float(state.cash / equity_after) if equity_after > 0 else np.nan,
        }
        if reserve_explicit:
            reserve_asset_value = float(values_after.get(reserve_asset_policy.asset_ticker, 0.0)) if reserve_asset_policy.tradeable else 0.0
            reserve_value = float(state.cash) + reserve_asset_value
            cash_row.update(
                {
                    "reserve_asset_value_usd": reserve_asset_value,
                    "reserve_value_usd": reserve_value,
                    "reserve_weight": float(reserve_value / equity_after) if equity_after > 0 else np.nan,
                    "reserve_asset_mode": reserve_asset_policy.mode,
                }
            )
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
                "position_count_total": int(
                    sum(1 for qty in state.shares.values() if abs(qty) > 1e-12)
                ),
                "equity_position_count": int(
                    sum(
                        1
                        for ticker, qty in state.shares.items()
                        if abs(qty) > 1e-12
                        and not (
                            reserve_explicit
                            and reserve_asset_policy.tradeable
                            and ticker == reserve_asset_policy.asset_ticker
                        )
                    )
                ),
                "reserve_position_count": int(
                    sum(
                        1
                        for ticker, qty in state.shares.items()
                        if abs(qty) > 1e-12
                        and reserve_explicit
                        and reserve_asset_policy.tradeable
                        and ticker == reserve_asset_policy.asset_ticker
                    )
                ),
                "fill_mode": fill_mode,
            }
            if reserve_explicit:
                reserve_asset_value = float(values.get(reserve_asset_policy.asset_ticker, 0.0)) if reserve_asset_policy.tradeable else 0.0
                reserve_value = float(state.cash) + reserve_asset_value
                equity_row.update(
                    {
                        "stock_value_usd": float(
                            sum(
                                value
                                for ticker, value in values.items()
                                if ticker != reserve_asset_policy.asset_ticker
                            )
                        ),
                        "reserve_asset_value_usd": reserve_asset_value,
                        "reserve_value_usd": reserve_value,
                        "reserve_weight": float(reserve_value / equity) if equity > 0 else np.nan,
                        "reserve_asset_mode": reserve_asset_policy.mode,
                        "position_count": int(
                            sum(
                                1
                                for ticker, qty in state.shares.items()
                                if abs(qty) > 1e-12 and ticker != reserve_asset_policy.asset_ticker
                            )
                        ),
                        "position_count_total": int(
                            sum(1 for qty in state.shares.values() if abs(qty) > 1e-12)
                        ),
                        "equity_position_count": int(
                            sum(
                                1
                                for ticker, qty in state.shares.items()
                                if abs(qty) > 1e-12
                                and ticker != reserve_asset_policy.asset_ticker
                            )
                        ),
                        "reserve_position_count": int(
                            sum(
                                1
                                for ticker, qty in state.shares.items()
                                if abs(qty) > 1e-12
                                and ticker == reserve_asset_policy.asset_ticker
                            )
                        ),
                    }
                )
            if carry_enabled:
                equity_row.update(cash_interest_fields)
            equity_rows.append(equity_row)
            for ticker, value in values.items():
                px = price_at_or_before(prices, ticker, date)
                holding_row = {
                        "date": pd.Timestamp(date).date().isoformat(),
                        "ticker": ticker,
                        "shares": float(state.shares.get(ticker, 0.0)),
                        "price": px if px is not None else np.nan,
                        "market_value_usd": float(value),
                        "weight": float(value / equity) if equity > 0 else np.nan,
                        "cost_basis": float(state.cost_basis.get(ticker, np.nan)),
                        "unrealized_pnl_usd": float(value - state.shares.get(ticker, 0.0) * state.cost_basis.get(ticker, 0.0)),
                    }
                if reserve_explicit:
                    holding_row["reserve_asset"] = bool(ticker == reserve_asset_policy.asset_ticker)
                holdings_rows.append(holding_row)

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
    trades_df = pd.DataFrame(trade_rows)
    holdings_df = pd.DataFrame(holdings_rows)
    cash_df = pd.DataFrame(cash_rows)
    target_vs_actual_df = pd.DataFrame(target_vs_actual_rows)
    partial_resize_df = pd.DataFrame(partial_resize_rows)
    metrics = calc_metrics(equity_df, trades_df, starting_capital, cash_carry_mode=cash_carry_config.mode)
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
            "valid_for_production": bool(
                metrics.get("status") == "completed"
                and fill_mode == "next_close"
                and integer_shares
                and not carry_enabled
                and not partial_resize_two_signal_confirmation
                and not reserve_explicit
                and not execution_cost_config.enabled
            ),
            "stock_evidence_end_date": (
                evidence_end.date().isoformat() if evidence_end is not None else ""
            ),
            "max_fill_lag_days": int(max_fill_lag_days),
            "target_fill_coverage": target_fill_coverage,
            **weight_diag,
        }
    )
    if execution_cost_config.enabled:
        execution_summary = summarize_execution_costs(
            trades_df,
            starting_capital=starting_capital,
            config=execution_cost_config,
        )
        coverage_complete = bool(execution_summary.get("coverage_complete"))
        metrics.update(
            {
                "execution_cost_mode": execution_cost_config.mode,
                "execution_cost_schema_version": execution_summary.get("schema_version"),
                "execution_cost_config": execution_cost_config.audit(),
                "execution_cost_summary": execution_summary,
                "capacity_scenarios": execution_summary.get("capacity_scenarios", []),
                "execution_cost_coverage_complete": coverage_complete,
                "target_fill_coverage": target_fill_coverage,
                "research_only": True,
                "production_activation_allowed": False,
                "valid_for_production": False,
            }
        )
        if (
            execution_cost_config.require_complete_liquidity_coverage
            and not coverage_complete
        ):
            metrics.update(
                {
                    "status": "blocked",
                    "reason": "execution_cost_liquidity_coverage_incomplete",
                    "metric_mode": "DO_NOT_USE",
                }
            )
        else:
            metrics["metric_mode"] = (
                str(metrics.get("metric_mode") or "broker_ledger")
                + "_execution_cost_capacity"
            )
        for window in (metrics.get("windows") or {}).values():
            if not isinstance(window, dict) or "metric_mode" not in window:
                continue
            window["execution_cost_mode"] = execution_cost_config.mode
            window["metric_mode"] = (
                str(window.get("metric_mode") or "broker_ledger")
                + "_execution_cost_capacity"
                if coverage_complete
                else "DO_NOT_USE"
            )
    if reserve_explicit:
        reserve_trades = (
            trades_df.loc[trades_df.get("ticker", pd.Series(dtype=str)).astype(str).eq(reserve_asset_policy.asset_ticker)]
            if not trades_df.empty
            else pd.DataFrame()
        )
        latest_reserve = float(pd.to_numeric(equity_df.get("reserve_weight"), errors="coerce").dropna().iloc[-1])
        average_reserve = float(pd.to_numeric(equity_df.get("reserve_weight"), errors="coerce").dropna().mean())
        reason_records = reserve_reason_audit.to_dict("records")
        latest_reason = reason_records[-1] if reason_records else {}
        metrics.update(
            {
                "reserve_asset_policy": reserve_asset_policy.audit(),
                "reserve_asset_mode": reserve_asset_policy.mode,
                "reserve_asset_ticker": reserve_asset_policy.asset_ticker,
                "reserve_price_mode": "adjusted_close_total_return" if reserve_asset_policy.tradeable else "cash_ledger",
                "reserve_cash_interest_enabled": bool(carry_enabled),
                "reserve_distribution_separately_credited": False,
                "reserve_double_count_check": "PASS",
                "average_reserve_weight": average_reserve,
                "latest_reserve_weight": latest_reserve,
                "reserve_trade_count": int(len(reserve_trades)),
                "reserve_turnover_usd": float(pd.to_numeric(reserve_trades.get("gross_value", pd.Series(dtype=float)), errors="coerce").fillna(0.0).sum()),
                "reserve_fees_usd": float(pd.to_numeric(reserve_trades.get("fee_usd", pd.Series(dtype=float)), errors="coerce").fillna(0.0).sum()),
                "reserve_reason_reconciliation": latest_reason,
                RESERVE_REASON_SOURCE_HASH_FIELD: latest_reason.get(
                    RESERVE_REASON_SOURCE_HASH_FIELD, ""
                ),
                "reserve_reason_reconciled_all_dates": bool(
                    reserve_reason_audit.get("reconciled", pd.Series(dtype=bool)).fillna(False).all()
                ),
                "production_activation_allowed": False,
                "research_only": True,
            }
        )
    if partial_resize_two_signal_confirmation:
        reason_counts = (
            partial_resize_df["reason"].value_counts().to_dict()
            if not partial_resize_df.empty and "reason" in partial_resize_df.columns
            else {}
        )
        metrics.update(
            {
                "candidate_id": f"{portfolio_kind}_partial_resize_two_signal_confirmation",
                "execution_policy": "partial_resize_two_signal_confirmation",
                "research_only": True,
                "production_activation_allowed": False,
                "partial_resize_decision_count": int(len(partial_resize_df)),
                "partial_resize_deferred_count": int(reason_counts.get("partial_resize_first_signal", 0)),
                "partial_resize_confirmed_count": int(reason_counts.get("partial_resize_second_signal_confirmed", 0)),
                "risk_cut_immediate_count": int(reason_counts.get("partial_resize_risk_cut_immediate", 0)),
                "target_entry_immediate_count": int(reason_counts.get("target_entry_immediate", 0)),
                "target_exit_immediate_count": int(reason_counts.get("target_exit_immediate", 0)),
                "pending_partial_resize_count": int(len(pending_partial_resizes)),
                "promotion_note": "Research-only single-mechanism execution arm; entries, full exits, and target-gross risk cuts remain immediate.",
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
                "cash_rate_future_use_count": int(state.cash_rate_future_use_count),
                "cash_carry_calendar_tickers": list(calendar_prices.keys()),
            }
        )

    redact_dynamic_performance = bool(
        execution_cost_config.enabled
        and execution_cost_config.require_complete_liquidity_coverage
        and metrics.get("status") != "completed"
    )
    if redact_dynamic_performance:
        blocked_reason = str(
            metrics.get("reason")
            or "execution_cost_liquidity_coverage_incomplete"
        )
        redacted_metrics = redact_execution_performance(
            metrics,
            reason=blocked_reason,
        )
        trades_df.to_csv(output_dir / "trades.csv", index=False)
        for artifact_name in (
            "equity_curve.csv",
            "holdings_daily.csv",
            "holdings_weekly.csv",
            "cash_ledger.csv",
            "target_vs_actual_weights.csv",
            "partial_resize_decisions.csv",
            "positions_latest.csv",
            "account_state_latest.json",
        ):
            artifact_path = output_dir / artifact_name
            if artifact_path.is_file():
                artifact_path.unlink()
        (output_dir / "metrics.json").write_text(
            json.dumps(redacted_metrics, indent=2, default=str),
            encoding="utf-8",
        )
        (output_dir / "replay_report.md").write_text(
            render_report(redacted_metrics),
            encoding="utf-8",
        )
        return redacted_metrics

    if reserve_explicit:
        reserve_reason_audit.to_json(
            output_dir / "reserve_reason_audit.json",
            orient="records",
            indent=2,
            date_format="iso",
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
    if partial_resize_two_signal_confirmation:
        partial_resize_df.to_csv(output_dir / "partial_resize_decisions.csv", index=False)
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
        return (
            "# Broker Ledger Replay\n\n"
            "Status: blocked\n\n"
            f"Reason: {metrics.get('reason', 'unknown')}\n\n"
            "Performance metrics: unavailable because this replay failed closed.\n"
        )
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
    if metrics.get("execution_cost_mode"):
        execution_summary = metrics.get("execution_cost_summary") or {}
        lines.extend(
            [
                f"- Execution cost mode: `{metrics.get('execution_cost_mode')}`",
                f"- Liquidity coverage: {safe_float(execution_summary.get('coverage_rate')):.2%}",
                f"- P95 ADV participation: {safe_float(execution_summary.get('p95_participation_rate')):.4%}",
                "",
                "Spread/ADV/impact metrics are research-only and cannot replace champion evidence automatically.",
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
    parser.add_argument(
        "--execution-cost-mode",
        choices=[EXECUTION_COST_MODE_FIXED, EXECUTION_COST_MODE_SPREAD_ADV_IMPACT],
        default=EXECUTION_COST_MODE_FIXED,
        help="Opt-in research cost model. The fixed_bps default preserves champion replay parity.",
    )
    parser.add_argument("--execution-cost-lookback-sessions", type=int, default=20)
    parser.add_argument("--execution-cost-min-history-sessions", type=int, default=12)
    parser.add_argument("--execution-impact-coefficient", type=float, default=0.50)
    parser.add_argument("--execution-min-half-spread-bps", type=float, default=1.0)
    parser.add_argument("--execution-max-half-spread-bps", type=float, default=100.0)
    parser.add_argument("--execution-max-impact-bps", type=float, default=500.0)
    parser.add_argument(
        "--execution-capacity-participation-rates",
        nargs="+",
        type=float,
        default=list((0.001, 0.005, 0.010)),
        help="ADV participation ceilings used for capacity reporting.",
    )
    parser.add_argument(
        "--paper-slippage-path",
        default="",
        help="Optional CSV/parquet with date, ticker, side, and observed_slippage_bps.",
    )
    parser.add_argument(
        "--allow-incomplete-execution-cost-coverage",
        action="store_true",
        help="Research diagnostics only; default dynamic-cost replay fails closed on any uncovered trade.",
    )
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
    parser.add_argument(
        "--oos2-end",
        default=None,
        help="ISO date; secondary OOS window end. Defaults to the day before the selected primary OOS start.",
    )
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
    parser.add_argument(
        "--reserve-mode",
        choices=list(RESERVE_MODES),
        default="",
        help="Canonical ReserveAssetPolicy mode. Empty preserves legacy zero-yield replay parity.",
    )
    parser.add_argument(
        "--partial-resize-two-signal-confirmation",
        action="store_true",
        help="Research-only: defer held-name partial resizes until the same direction repeats at the next decision; entries, exits, and target-gross risk cuts remain immediate.",
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
    oos2_end = _resolve_oos(args.oos2_end, "R1000_OOS2_END", "") if oos2_start else None
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
        oos2_end=oos2_end,
        cash_carry_config=resolve_cash_carry_config(
            mode=args.cash_carry_mode,
            rate_source=args.cash_rate_source,
            rate_lag_days=args.cash_rate_lag_days,
            haircut_bps=args.cash_carry_haircut_bps,
            day_count=args.cash_carry_day_count,
            rate_path=args.cash_rate_path,
        ),
        reserve_mode=args.reserve_mode or None,
        partial_resize_two_signal_confirmation=bool(args.partial_resize_two_signal_confirmation),
        execution_cost_config=ExecutionCostConfig(
            mode=args.execution_cost_mode,
            lookback_sessions=int(args.execution_cost_lookback_sessions),
            min_history_sessions=int(args.execution_cost_min_history_sessions),
            impact_coefficient=float(args.execution_impact_coefficient),
            minimum_half_spread_bps=float(args.execution_min_half_spread_bps),
            maximum_half_spread_bps=float(args.execution_max_half_spread_bps),
            maximum_market_impact_bps=float(args.execution_max_impact_bps),
            capacity_participation_rates=tuple(
                float(value) for value in args.execution_capacity_participation_rates
            ),
            paper_slippage_path=(
                repo_path(args.paper_slippage_path)
                if str(args.paper_slippage_path or "").strip()
                else None
            ),
            require_complete_liquidity_coverage=not bool(
                args.allow_incomplete_execution_cost_coverage
            ),
        ),
    )
    print(json.dumps(payload, indent=2, default=str))
    return 0 if payload.get("status") == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
