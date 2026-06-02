#!/usr/bin/env python3
"""Build event-driven target books from monthly/operating target books.

This is the first bridge from monthly research targets to account-like daily
operation. It does not rescore the whole universe every day. Instead, it starts
from the existing main/concentrated target books and injects observable
daily/weekly event rows when a held position hits risk or stale-leader rules.

The output can be replayed by `run_broker_ledger_replay.py`, so CAGR/Sharpe/MDD
are measured with shares, cash, fees, fills, and daily equity rather than
weight-level proxy math.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.run_broker_ledger_replay import (  # noqa: E402
    CASH_TICKERS,
    filter_concentrated_champion,
    resolve_concentrated_champion_filters,
    safe_float,
)
from tools.run_position_risk_weekly_validation import simulate_position  # noqa: E402
from tools.run_weekly_evaluation import load_price_series  # noqa: E402


DEFAULT_OUTPUT_DIR = "outputs/event_target_books"
DEFAULT_REPORTS_DIR = "outputs/reports"
CASH_FLOORS_BY_STATE: dict[str, dict[str, float]] = {
    "main": {
        "GREEN": 0.03,
        "WATCH": 0.08,
        "DEFENSE_REVIEW": 0.25,
        "CRISIS_DEFENSE": 0.45,
        "REENTRY_READY": 0.20,
    },
    "concentrated": {
        "GREEN": 0.05,
        "WATCH": 0.12,
        "DEFENSE_REVIEW": 0.35,
        "CRISIS_DEFENSE": 0.60,
        "REENTRY_READY": 0.25,
    },
}
DEFAULT_CLUSTER_CAPS: dict[str, dict[str, float]] = {
    "main": {"single_name": 0.12, "industry_group": 0.35, "sector": 0.55},
    "concentrated": {"single_name": 0.25, "industry_group": 0.40, "sector": 0.55},
}
DEFENSE_STATES = {"DEFENSE_REVIEW", "CRISIS_DEFENSE"}


def repo_path(path_like: str | Path) -> Path:
    path = Path(path_like)
    return path if path.is_absolute() else REPO_ROOT / path


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path, low_memory=False)
    except Exception:
        return pd.DataFrame()


def load_daily_crisis_states(path: Path) -> pd.DataFrame:
    frame = read_csv(path)
    if frame.empty:
        return pd.DataFrame(columns=["date", "crisis_state"])
    d = frame.copy()
    date_col = "date" if "date" in d.columns else "rebalance_date" if "rebalance_date" in d.columns else ""
    if not date_col or "crisis_state" not in d.columns:
        return pd.DataFrame(columns=["date", "crisis_state"])
    d["date"] = pd.to_datetime(d[date_col], errors="coerce").dt.normalize()
    d["crisis_state"] = d["crisis_state"].astype(str).str.upper().str.strip().replace({"": "GREEN"})
    keep = [c for c in ["date", "crisis_state", "raw_state", "crisis_score", "reentry_stage", "state_source"] if c in d.columns]
    return d.dropna(subset=["date"])[keep].sort_values("date").drop_duplicates("date", keep="last").reset_index(drop=True)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def date_text(value: Any) -> str:
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return ""
    return pd.Timestamp(parsed).date().isoformat()


def normalize_targets(frame: pd.DataFrame, portfolio_kind: str, target_book: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    if frame.empty or "rebalance_date" not in frame.columns or "ticker" not in frame.columns or "weight" not in frame.columns:
        return pd.DataFrame(), {"target_book_filter": {}, "target_book_filter_source": "not_applicable", "target_book_filter_warning": ""}
    raw = frame.copy()
    filters, source, warning = resolve_concentrated_champion_filters(
        target_book=target_book,
        raw_targets=raw,
        portfolio_kind=portfolio_kind,
        explicit_filters=None,
    )
    d = filter_concentrated_champion(raw, portfolio_kind, filters).copy()
    d["rebalance_date"] = pd.to_datetime(d["rebalance_date"], errors="coerce").dt.normalize()
    d["ticker"] = d["ticker"].astype(str).str.upper().str.strip()
    d["weight"] = pd.to_numeric(d["weight"], errors="coerce").fillna(0.0)
    d = d.dropna(subset=["rebalance_date"])
    d = d[(d["ticker"] != "") & (d["weight"] > 1e-12)].copy()
    if d.empty:
        return d, {"target_book_filter": filters, "target_book_filter_source": source, "target_book_filter_warning": warning}
    return d.sort_values(["rebalance_date", "ticker"]).reset_index(drop=True), {
        "target_book_filter": filters,
        "target_book_filter_source": source,
        "target_book_filter_warning": warning,
    }


def latest_period_end(targets: pd.DataFrame, prices: dict[str, pd.DataFrame], dt: pd.Timestamp, idx: int, dates: list[pd.Timestamp]) -> pd.Timestamp | None:
    if idx + 1 < len(dates):
        return pd.Timestamp(dates[idx + 1]).normalize()
    period = targets[targets["rebalance_date"].eq(dt)]
    latest: list[pd.Timestamp] = []
    for ticker in period["ticker"].astype(str).str.upper().unique():
        if ticker in CASH_TICKERS:
            continue
        px = prices.get(ticker, pd.DataFrame())
        if not px.empty:
            latest.append(pd.Timestamp(px.index.max()).normalize())
    return max(latest) if latest else None


def original_template_by_ticker(period: pd.DataFrame) -> dict[str, dict[str, Any]]:
    templates: dict[str, dict[str, Any]] = {}
    for row in period.to_dict("records"):
        ticker = str(row.get("ticker") or "").upper()
        if not ticker:
            continue
        templates[ticker] = row
    return templates


def cap_group_key(templates: dict[str, dict[str, Any]], ticker: str, column: str) -> str:
    text = str(templates.get(ticker, {}).get(column) or "").strip()
    if not text or text.lower() in {"nan", "none", "unknown"}:
        return f"__{ticker}"
    return text


def apply_cluster_caps(
    weights: dict[str, float],
    templates: dict[str, dict[str, Any]],
    caps: dict[str, float],
) -> tuple[dict[str, float], list[dict[str, Any]]]:
    out = {ticker: max(0.0, safe_float(weight)) for ticker, weight in weights.items() if safe_float(weight) > 1e-12}
    events: list[dict[str, Any]] = []
    single_cap = float(caps.get("single_name", 1.0))
    if 0.0 < single_cap < 1.0:
        for ticker, weight in list(out.items()):
            if weight <= single_cap + 1e-12:
                continue
            out[ticker] = single_cap
            events.append(
                {
                    "cap_type": "single_name",
                    "cap_key": ticker,
                    "cap": single_cap,
                    "weight_before": float(weight),
                    "weight_after": float(single_cap),
                    "cash_added": float(weight - single_cap),
                }
            )
    for column in ("industry_group", "sector"):
        cap = float(caps.get(column, 1.0))
        if not (0.0 < cap < 1.0):
            continue
        totals: dict[str, float] = defaultdict(float)
        members: dict[str, list[str]] = defaultdict(list)
        for ticker, weight in out.items():
            key = cap_group_key(templates, ticker, column)
            totals[key] += weight
            members[key].append(ticker)
        for key, total in totals.items():
            if key.startswith("__") or total <= cap + 1e-12:
                continue
            scale = cap / max(total, 1e-12)
            for ticker in members[key]:
                out[ticker] = out[ticker] * scale
            events.append(
                {
                    "cap_type": column,
                    "cap_key": key,
                    "cap": cap,
                    "weight_before": float(total),
                    "weight_after": float(cap),
                    "cash_added": float(total - cap),
                }
            )
    return out, events


def snapshot_rows(
    *,
    snapshot_date: pd.Timestamp,
    weights: dict[str, float],
    templates: dict[str, dict[str, Any]],
    portfolio_kind: str,
    event_kind: str,
    event_reason: str,
    event_source_tickers: list[str],
    cluster_caps: dict[str, float] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, float], list[dict[str, Any]]]:
    capped_weights, cap_events = apply_cluster_caps(weights, templates, cluster_caps or {})
    cap_reason = ";".join(
        f"{event['cap_type']}:{event['cap_key']}->{safe_float(event['cap']):.2f}"
        for event in cap_events
    )
    rows: list[dict[str, Any]] = []
    stock_sum = 0.0
    for ticker, weight in sorted(capped_weights.items()):
        if ticker in CASH_TICKERS or weight <= 1e-12:
            continue
        base = dict(templates.get(ticker, {}))
        base["rebalance_date"] = snapshot_date.date().isoformat()
        base["ticker"] = ticker
        base["weight"] = float(weight)
        base["portfolio_kind"] = portfolio_kind
        base["event_target_book"] = True
        base["event_kind"] = event_kind
        base["event_reason"] = event_reason
        base["event_source_tickers"] = ",".join(event_source_tickers)
        base["cluster_cap_applied"] = bool(cap_events)
        base["cluster_cap_reason"] = cap_reason
        rows.append(base)
        stock_sum += float(weight)
    cash_weight = max(0.0, 1.0 - stock_sum)
    if cash_weight > 1e-8:
        rows.append(
            {
                "rebalance_date": snapshot_date.date().isoformat(),
                "ticker": "CASH",
                "weight": float(cash_weight),
                "portfolio_kind": portfolio_kind,
                "event_target_book": True,
                "event_kind": event_kind,
                "event_reason": event_reason,
                "event_source_tickers": ",".join(event_source_tickers),
                "cluster_cap_applied": bool(cap_events),
                "cluster_cap_reason": cap_reason,
            }
        )
    return rows, capped_weights, cap_events


def period_base_weights(period: pd.DataFrame) -> dict[str, float]:
    out: dict[str, float] = {}
    for row in period.to_dict("records"):
        ticker = str(row.get("ticker") or "").upper().strip()
        if not ticker or ticker in CASH_TICKERS:
            continue
        out[ticker] = out.get(ticker, 0.0) + max(0.0, safe_float(row.get("weight"), 0.0))
    stock_sum = sum(out.values())
    if stock_sum > 1.0 + 1e-9:
        scale = 1.0 / stock_sum
        out = {ticker: weight * scale for ticker, weight in out.items()}
    return out


def cash_floor_for_state(portfolio_kind: str, state: Any) -> float:
    floors = CASH_FLOORS_BY_STATE.get(portfolio_kind, CASH_FLOORS_BY_STATE["main"])
    key = str(state or "GREEN").upper().strip()
    return float(floors.get(key, floors["GREEN"]))


def risk_cash_update(
    *,
    portfolio_kind: str,
    state: Any,
    event_date: pd.Timestamp,
    current_risk_cash: float,
    last_defense_date: pd.Timestamp | None,
    reentry_delay_days: int,
    release_step: float,
) -> tuple[float, pd.Timestamp | None, str]:
    state_key = str(state or "GREEN").upper().strip()
    floor = cash_floor_for_state(portfolio_kind, state_key)
    current = float(np.clip(current_risk_cash, 0.0, 0.98))
    if state_key in DEFENSE_STATES:
        last_defense_date = pd.Timestamp(event_date).normalize()
    if floor > current:
        return float(floor), last_defense_date, f"raise_to_{state_key.lower()}_floor"
    if current > floor:
        if last_defense_date is not None:
            days_since_defense = (pd.Timestamp(event_date).normalize() - pd.Timestamp(last_defense_date).normalize()).days
            if days_since_defense < int(reentry_delay_days):
                return current, last_defense_date, "hold_cash_during_reentry_delay"
        return float(max(floor, current - float(release_step))), last_defense_date, "staged_cash_release"
    return current, last_defense_date, "cash_floor_unchanged"


def set_cash_level(weights: dict[str, float], target_cash: float) -> dict[str, float]:
    stock_total = float(sum(max(0.0, safe_float(weight)) for weight in weights.values()))
    target_stock = float(np.clip(1.0 - float(target_cash), 0.0, 1.0))
    if stock_total <= 1e-12 or target_stock <= 1e-12:
        return {}
    scale = target_stock / stock_total
    return {ticker: max(0.0, safe_float(weight) * scale) for ticker, weight in weights.items() if safe_float(weight) > 1e-12}


def price_dict_for_targets(price_cache: Path, targets: pd.DataFrame, benchmark_ticker: str) -> dict[str, pd.DataFrame]:
    tickers = sorted({str(x).upper() for x in targets["ticker"].unique() if str(x).upper() not in CASH_TICKERS})
    prices = {ticker: load_price_series(price_cache, ticker) for ticker in tickers + [benchmark_ticker.upper()]}
    return {ticker: frame for ticker, frame in prices.items() if not frame.empty}


def build_event_book(
    *,
    target_book: Path,
    price_cache: Path,
    portfolio_kind: str,
    benchmark_ticker: str,
    crisis_state_path: Path,
    enable_daily_crisis_cash_overlay: bool,
    reentry_delay_days: int,
    crisis_release_step: float,
    crisis_change_band: float,
    cluster_caps: dict[str, float],
    hard_stop: float,
    trailing_stop: float,
    trailing_activation: float,
    relative_trim_threshold: float,
    relative_exit_threshold: float,
    trim_weight: float,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    raw = read_csv(target_book)
    targets, filter_meta = normalize_targets(raw, portfolio_kind, target_book)
    if targets.empty:
        return pd.DataFrame(), pd.DataFrame(), {
            "status": "blocked",
            "reason": "target book is empty or invalid",
            "target_book": str(target_book),
            **filter_meta,
        }
    prices = price_dict_for_targets(price_cache, targets, benchmark_ticker)
    if not prices:
        return pd.DataFrame(), pd.DataFrame(), {
            "status": "blocked",
            "reason": "price cache has no usable target prices",
            "target_book": str(target_book),
            **filter_meta,
        }

    dates = [pd.Timestamp(x).normalize() for x in sorted(targets["rebalance_date"].dropna().unique())]
    crisis = load_daily_crisis_states(crisis_state_path)
    rows: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    event_rows_by_date: dict[pd.Timestamp, list[dict[str, Any]]] = defaultdict(list)
    event_count = 0
    daily_crisis_event_count = 0
    cluster_cap_event_count = 0
    trim_count = 0
    exit_count = 0
    missing_price_count = 0
    skipped_same_or_after_count = 0
    risk_cash_target = cash_floor_for_state(portfolio_kind, "GREEN")
    last_defense_date: pd.Timestamp | None = None

    for idx, dt in enumerate(dates):
        period = targets[targets["rebalance_date"].eq(dt)].copy()
        if period.empty:
            continue
        end_dt = latest_period_end(targets, prices, dt, idx, dates)
        if end_dt is None or end_dt <= dt:
            continue
        templates = original_template_by_ticker(period)
        current_weights = period_base_weights(period)
        if enable_daily_crisis_cash_overlay and not crisis.empty:
            crisis_to_dt = crisis[crisis["date"].le(dt)]
            if not crisis_to_dt.empty:
                state_at_dt = str(crisis_to_dt.iloc[-1].get("crisis_state") or "GREEN")
                risk_cash_target, last_defense_date, _risk_reason = risk_cash_update(
                    portfolio_kind=portfolio_kind,
                    state=state_at_dt,
                    event_date=dt,
                    current_risk_cash=risk_cash_target,
                    last_defense_date=last_defense_date,
                    reentry_delay_days=reentry_delay_days,
                    release_step=crisis_release_step,
                )
        current_weights = set_cash_level(current_weights, max(0.0, risk_cash_target))
        snapshot, current_weights, cap_events = snapshot_rows(
            snapshot_date=dt,
            weights=current_weights,
            templates=templates,
            portfolio_kind=portfolio_kind,
            event_kind="scheduled_rebalance",
            event_reason="base_target_book",
            event_source_tickers=[],
            cluster_caps=cluster_caps,
        )
        rows.extend(snapshot)
        cluster_cap_event_count += len(cap_events)
        action_records: list[dict[str, Any]] = []
        if enable_daily_crisis_cash_overlay and not crisis.empty:
            crisis_window = crisis[(crisis["date"].gt(dt)) & (crisis["date"].lt(end_dt))].copy()
            for crisis_row in crisis_window.to_dict("records"):
                action_records.append(
                    {
                        "action_date": pd.Timestamp(crisis_row["date"]).normalize(),
                        "ticker": "CASH",
                        "action_type": "daily_crisis_cash",
                        "action": "daily_crisis_cash_review",
                        "reason": str(crisis_row.get("crisis_state") or "GREEN"),
                        "crisis_state": str(crisis_row.get("crisis_state") or "GREEN"),
                        "crisis_score": crisis_row.get("crisis_score", ""),
                    }
                )
        for row in period.to_dict("records"):
            ticker = str(row.get("ticker") or "").upper().strip()
            if not ticker or ticker in CASH_TICKERS:
                continue
            result, actions = simulate_position(
                row,
                prices.get(ticker, pd.DataFrame()),
                prices.get(benchmark_ticker.upper(), pd.DataFrame()),
                dt + pd.Timedelta(days=1),
                end_dt,
                hard_stop=hard_stop,
                trailing_stop=trailing_stop,
                trailing_activation=trailing_activation,
                relative_trim_threshold=relative_trim_threshold,
                relative_exit_threshold=relative_exit_threshold,
                trim_weight=trim_weight,
            )
            if str(result.get("exit_action") or "") == "missing_price_hold_cash_proxy":
                missing_price_count += 1
            for action in actions:
                action_dt = pd.to_datetime(action.get("action_date"), errors="coerce")
                if pd.isna(action_dt):
                    continue
                action_dt = pd.Timestamp(action_dt).normalize()
                if action_dt <= dt or action_dt >= end_dt:
                    skipped_same_or_after_count += 1
                    continue
                active_after = float(np.clip(safe_float(action.get("active_multiplier_after"), 1.0), 0.0, 1.0))
                action_name = str(action.get("action") or "")
                action_records.append(
                    {
                        "action_date": action_dt,
                        "action_type": "position_event",
                        "ticker": ticker,
                        "action": action_name,
                        "reason": action.get("reason", ""),
                        "active_multiplier_after": active_after,
                        "original_weight": safe_float(row.get("weight"), 0.0),
                        "new_weight": safe_float(row.get("weight"), 0.0) * active_after,
                        "price_return": action.get("price_return", ""),
                        "benchmark_return": action.get("benchmark_return", ""),
                        "relative_return": action.get("relative_return", ""),
                        "action_price": action.get("action_price", ""),
                    }
                )
        for action in sorted(action_records, key=lambda item: (item["action_date"], item.get("action_type") != "daily_crisis_cash", item["ticker"], item["action"])):
            action_dt = pd.Timestamp(action["action_date"]).normalize()
            if str(action.get("action_type") or "") == "daily_crisis_cash":
                prior_risk_cash = risk_cash_target
                risk_cash_target, last_defense_date, risk_reason = risk_cash_update(
                    portfolio_kind=portfolio_kind,
                    state=action.get("crisis_state"),
                    event_date=action_dt,
                    current_risk_cash=risk_cash_target,
                    last_defense_date=last_defense_date,
                    reentry_delay_days=reentry_delay_days,
                    release_step=crisis_release_step,
                )
                if abs(risk_cash_target - prior_risk_cash) < float(crisis_change_band):
                    continue
                current_weights = set_cash_level(current_weights, risk_cash_target)
                event_count += 1
                daily_crisis_event_count += 1
                event_rows_by_date[action_dt].append(action)
                snapshot, current_weights, cap_events = snapshot_rows(
                    snapshot_date=action_dt,
                    weights=current_weights,
                    templates=templates,
                    portfolio_kind=portfolio_kind,
                    event_kind="daily_crisis_cash_overlay",
                    event_reason=risk_reason,
                    event_source_tickers=["CASH"],
                    cluster_caps=cluster_caps,
                )
                cluster_cap_event_count += len(cap_events)
                events.append(
                    {
                        "portfolio_kind": portfolio_kind,
                        "base_rebalance_date": dt.date().isoformat(),
                        "period_end_date": end_dt.date().isoformat(),
                        "action_date": action_dt.date().isoformat(),
                        "ticker": "CASH",
                        "action": "daily_crisis_cash_raise" if risk_cash_target > prior_risk_cash else "daily_crisis_cash_release",
                        "reason": risk_reason,
                        "crisis_state": action.get("crisis_state"),
                        "crisis_score": action.get("crisis_score", ""),
                        "prior_cash_target": float(prior_risk_cash),
                        "target_cash": float(risk_cash_target),
                        "cash_weight_after": max(0.0, 1.0 - sum(current_weights.values())),
                    }
                )
                rows = [
                    row
                    for row in rows
                    if not (
                        str(row.get("rebalance_date")) == action_dt.date().isoformat()
                        and str(row.get("event_kind")) != "scheduled_rebalance"
                    )
                ]
                rows.extend(snapshot)
                continue
            ticker = str(action["ticker"])
            current_weights[ticker] = max(0.0, safe_float(action.get("new_weight"), 0.0))
            if current_weights[ticker] <= 1e-12:
                current_weights.pop(ticker, None)
            event_count += 1
            if "trim" in str(action.get("action") or ""):
                trim_count += 1
            if "exit" in str(action.get("action") or ""):
                exit_count += 1
            event_rows_by_date[action_dt].append(action)
            events.append(
                {
                    "portfolio_kind": portfolio_kind,
                    "base_rebalance_date": dt.date().isoformat(),
                    "period_end_date": end_dt.date().isoformat(),
                    "action_date": action_dt.date().isoformat(),
                    "ticker": ticker,
                    "action": action.get("action"),
                    "reason": action.get("reason"),
                    "original_weight": action.get("original_weight"),
                    "new_weight": current_weights.get(ticker, 0.0),
                    "cash_weight_after": max(0.0, 1.0 - sum(current_weights.values())),
                    "price_return": action.get("price_return"),
                    "benchmark_return": action.get("benchmark_return"),
                    "relative_return": action.get("relative_return"),
                    "action_price": action.get("action_price"),
                }
            )
            same_day = event_rows_by_date[action_dt]
            rows = [
                row
                for row in rows
                if not (
                    str(row.get("rebalance_date")) == action_dt.date().isoformat()
                    and str(row.get("event_kind")) != "scheduled_rebalance"
                )
            ]
            snapshot, current_weights, cap_events = snapshot_rows(
                snapshot_date=action_dt,
                weights=current_weights,
                templates=templates,
                portfolio_kind=portfolio_kind,
                event_kind="event_overlay",
                event_reason=";".join(sorted({str(item.get("action")) for item in same_day})),
                event_source_tickers=sorted({str(item.get("ticker")) for item in same_day}),
                cluster_caps=cluster_caps,
            )
            rows.extend(snapshot)
            cluster_cap_event_count += len(cap_events)

    out = pd.DataFrame(rows)
    if not out.empty:
        out["rebalance_date"] = pd.to_datetime(out["rebalance_date"], errors="coerce").dt.date.astype(str)
        out["weight"] = pd.to_numeric(out["weight"], errors="coerce").fillna(0.0)
        out = out[(out["ticker"].astype(str).str.upper().str.strip() != "") & (out["weight"] > 1e-12)].copy()
        out = out.sort_values(["rebalance_date", "ticker"]).reset_index(drop=True)
    events_df = pd.DataFrame(events)
    summary = {
        "status": "completed" if not out.empty else "blocked",
        "portfolio_kind": portfolio_kind,
        "target_book": str(target_book),
        "price_cache": str(price_cache),
        "benchmark_ticker": benchmark_ticker.upper(),
        "data_mode": "target_book_plus_daily_price_event_overlay",
        "research_only": True,
        "production_activation_allowed": False,
        "valid_for_production": False,
        "promotion_note": "Event target book encodes observable daily/weekly exits, trims, daily crisis cash, staged re-entry, and cluster caps from existing target holdings. It does not create new daily alpha entries.",
        "base_decision_count": int(len(dates)),
        "output_row_count": int(len(out)),
        "event_count": int(event_count),
        "daily_crisis_cash_overlay_enabled": bool(enable_daily_crisis_cash_overlay),
        "daily_crisis_event_count": int(daily_crisis_event_count),
        "daily_crisis_state_path": str(crisis_state_path),
        "reentry_delay_days": int(reentry_delay_days),
        "crisis_release_step": float(crisis_release_step),
        "crisis_change_band": float(crisis_change_band),
        "cluster_caps": cluster_caps,
        "cluster_cap_event_count": int(cluster_cap_event_count),
        "exit_count": int(exit_count),
        "trim_count": int(trim_count),
        "missing_price_count": int(missing_price_count),
        "skipped_same_or_after_count": int(skipped_same_or_after_count),
        "hard_stop": hard_stop,
        "trailing_stop": trailing_stop,
        "trailing_activation": trailing_activation,
        "relative_trim_threshold": relative_trim_threshold,
        "relative_exit_threshold": relative_exit_threshold,
        "trim_weight": trim_weight,
        **filter_meta,
    }
    return out, events_df, summary


def render_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Event Target Books",
        "",
        "Research-only bridge from monthly/operating targets to daily event-aware broker replay.",
        "",
        "| Portfolio | Status | Rows | Events | Exits | Trims |",
        "| --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for row in payload.get("books", []):
        lines.append(
            "| {portfolio} | {status} | {rows} | {events} | {exits} | {trims} |".format(
                portfolio=row.get("portfolio_kind"),
                status=row.get("status"),
                rows=row.get("output_row_count"),
                events=row.get("event_count"),
                exits=row.get("exit_count"),
                trims=row.get("trim_count"),
            )
        )
    lines.extend(
        [
            "",
            "These books can be replayed by the broker-ledger engine. They are not a daily alpha rescore yet; new daily entries require historical daily/weekly scored snapshots.",
            "",
        ]
    )
    return "\n".join(lines)


def build(args: argparse.Namespace) -> dict[str, Any]:
    latest_run = repo_path(args.latest_run)
    price_cache = repo_path(args.price_cache)
    output_dir = repo_path(args.output_dir)
    reports_dir = repo_path(args.reports_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)

    specs = [
        ("main", latest_run / "reports" / "operating_main_target_book.csv"),
        ("concentrated", latest_run / "reports" / "operating_concentrated_target_book.csv"),
    ]
    summaries: list[dict[str, Any]] = []
    outputs: dict[str, str] = {}
    for portfolio_kind, default_path in specs:
        target_book = repo_path(getattr(args, f"{portfolio_kind}_target_book")) if getattr(args, f"{portfolio_kind}_target_book") else default_path
        cluster_caps = {
            "single_name": float(getattr(args, f"{portfolio_kind}_single_name_cap")),
            "industry_group": float(getattr(args, f"{portfolio_kind}_industry_group_cap")),
            "sector": float(getattr(args, f"{portfolio_kind}_sector_cap")),
        }
        crisis_state_path = repo_path(args.crisis_state_csv) if args.crisis_state_csv else latest_run / "alphaops_vnext" / "daily_crisis_state.csv"
        book, events, summary = build_event_book(
            target_book=target_book,
            price_cache=price_cache,
            portfolio_kind=portfolio_kind,
            benchmark_ticker=args.benchmark_ticker,
            crisis_state_path=crisis_state_path,
            enable_daily_crisis_cash_overlay=not bool(args.disable_daily_crisis_cash_overlay),
            reentry_delay_days=args.reentry_delay_days,
            crisis_release_step=args.crisis_release_step,
            crisis_change_band=args.crisis_change_band,
            cluster_caps=cluster_caps,
            hard_stop=args.hard_stop,
            trailing_stop=args.trailing_stop,
            trailing_activation=args.trailing_activation,
            relative_trim_threshold=args.relative_trim_threshold,
            relative_exit_threshold=args.relative_exit_threshold,
            trim_weight=args.trim_weight,
        )
        book_path = reports_dir / f"event_{portfolio_kind}_target_book.csv"
        events_path = output_dir / f"{portfolio_kind}_events.csv"
        if not book.empty:
            book.to_csv(book_path, index=False)
        else:
            pd.DataFrame(columns=["rebalance_date", "ticker", "weight"]).to_csv(book_path, index=False)
        events.to_csv(events_path, index=False)
        summary["event_target_book_path"] = str(book_path)
        summary["events_path"] = str(events_path)
        summaries.append(summary)
        outputs[f"{portfolio_kind}_event_target_book"] = str(book_path)
        outputs[f"{portfolio_kind}_events"] = str(events_path)

    payload = {
        "schema_version": "event-target-books-v1",
        "generated_at_utc": now_utc(),
        "status": "completed" if all(row.get("status") == "completed" for row in summaries) else "partial",
        "latest_run": str(latest_run),
        "price_cache": str(price_cache),
        "books": summaries,
        "outputs": {
            **outputs,
            "summary_json": str(output_dir / "summary.json"),
            "report_md": str(output_dir / "report.md"),
        },
    }
    write_json(output_dir / "summary.json", payload)
    write_text(output_dir / "report.md", render_report(payload))
    print(json.dumps(payload, indent=2, default=str))
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default="outputs")
    parser.add_argument("--price-cache", default="cache_prices")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--reports-dir", default=DEFAULT_REPORTS_DIR)
    parser.add_argument("--main-target-book", default="")
    parser.add_argument("--concentrated-target-book", default="")
    parser.add_argument("--benchmark-ticker", default="SPY")
    parser.add_argument("--crisis-state-csv", default="")
    parser.add_argument("--disable-daily-crisis-cash-overlay", action="store_true")
    parser.add_argument("--reentry-delay-days", type=int, default=10)
    parser.add_argument("--crisis-release-step", type=float, default=0.10)
    parser.add_argument("--crisis-change-band", type=float, default=0.03)
    parser.add_argument("--main-single-name-cap", type=float, default=DEFAULT_CLUSTER_CAPS["main"]["single_name"])
    parser.add_argument("--main-industry-group-cap", type=float, default=DEFAULT_CLUSTER_CAPS["main"]["industry_group"])
    parser.add_argument("--main-sector-cap", type=float, default=DEFAULT_CLUSTER_CAPS["main"]["sector"])
    parser.add_argument("--concentrated-single-name-cap", type=float, default=DEFAULT_CLUSTER_CAPS["concentrated"]["single_name"])
    parser.add_argument("--concentrated-industry-group-cap", type=float, default=DEFAULT_CLUSTER_CAPS["concentrated"]["industry_group"])
    parser.add_argument("--concentrated-sector-cap", type=float, default=DEFAULT_CLUSTER_CAPS["concentrated"]["sector"])
    parser.add_argument("--hard-stop", type=float, default=-0.08)
    parser.add_argument("--trailing-stop", type=float, default=-0.15)
    parser.add_argument("--trailing-activation", type=float, default=0.15)
    parser.add_argument("--relative-trim-threshold", type=float, default=-0.06)
    parser.add_argument("--relative-exit-threshold", type=float, default=-0.12)
    parser.add_argument("--trim-weight", type=float, default=0.50)
    return parser.parse_args()


def main() -> int:
    payload = build(parse_args())
    return 0 if payload.get("status") in {"completed", "partial"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
