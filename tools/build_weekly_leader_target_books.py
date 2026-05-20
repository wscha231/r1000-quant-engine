#!/usr/bin/env python3
"""Build weekly leader-entry target books from PIT monthly candidates.

This is the first historical "new leader entry" bridge for the broker ledger.
It uses the point-in-time monthly candidate replay book as the eligible universe,
then computes price/volume features only from bars available at each weekly
signal date. The output is a research-only target book that can be replayed by
`run_broker_ledger_replay.py`.

It intentionally avoids forward-label columns such as `r_1m`,
`period_forward_return`, and `y_blend` during selection.
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

from tools.run_broker_ledger_replay import (  # noqa: E402
    CASH_TICKERS,
    filter_concentrated_champion,
    resolve_concentrated_champion_filters,
    safe_float,
)
from tools.run_weekly_evaluation import load_price_series, price_on_or_before  # noqa: E402


DEFAULT_LATEST_RUN = "outputs"
DEFAULT_OUTPUT_DIR = "outputs/weekly_leader_snapshots"
DEFAULT_REPORTS_DIR = "outputs/reports"
EXPERIMENT_ID = "weekly_leader_entry_target_books"
FORWARD_LABEL_COLUMNS = {
    "r_1m",
    "y_blend",
    "period_forward_return",
    "weighted_forward_return",
    "pred_forward_return",
}


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


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def normalize_book(frame: pd.DataFrame, portfolio_kind: str, target_book: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
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
    return d.sort_values(["rebalance_date", "ticker"]).reset_index(drop=True), {
        "target_book_filter": filters,
        "target_book_filter_source": source,
        "target_book_filter_warning": warning,
    }


def normalize_candidate_book(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty or "rebalance_date" not in frame.columns or "ticker" not in frame.columns:
        return pd.DataFrame()
    d = frame.copy()
    d["rebalance_date"] = pd.to_datetime(d["rebalance_date"], errors="coerce").dt.normalize()
    d["ticker"] = d["ticker"].astype(str).str.upper().str.strip()
    d = d.dropna(subset=["rebalance_date"])
    d = d[(d["ticker"] != "") & (~d["ticker"].isin(CASH_TICKERS))].copy()
    return d.sort_values(["rebalance_date", "ticker"]).reset_index(drop=True)


def numeric(frame: pd.DataFrame, col: str, default: float = 0.0) -> pd.Series:
    if col not in frame.columns:
        return pd.Series(default, index=frame.index, dtype=float)
    return pd.to_numeric(frame[col], errors="coerce").fillna(default)


def first_numeric(row: dict[str, Any], cols: tuple[str, ...], default: float = 0.0) -> float:
    for col in cols:
        value = safe_float(row.get(col), math.nan)
        if math.isfinite(value):
            return value
    return default


def robust_z(values: pd.Series) -> pd.Series:
    x = pd.to_numeric(values, errors="coerce").replace([np.inf, -np.inf], np.nan)
    if not x.notna().any():
        return pd.Series(0.0, index=values.index, dtype=float)
    med = float(x.median(skipna=True))
    mad = float((x - med).abs().median(skipna=True))
    if not math.isfinite(mad) or mad <= 1e-12:
        std = float(x.std(skipna=True, ddof=0))
        denom = std if std > 1e-12 else 1.0
        return ((x - med) / denom).fillna(0.0).clip(-6, 6)
    return ((x - med) / (1.4826 * mad)).fillna(0.0).clip(-6, 6)


def price_return(px: pd.DataFrame, as_of: pd.Timestamp, lookback_days: int) -> float:
    actual, close_now = price_on_or_before(px, as_of, "close")
    if actual is None or close_now is None:
        return math.nan
    prev_dt = pd.Timestamp(actual).normalize() - pd.Timedelta(days=int(lookback_days))
    _, close_prev = price_on_or_before(px, prev_dt, "close")
    if close_prev is None or close_prev <= 0:
        return math.nan
    return float(close_now / close_prev - 1.0)


def price_features(px: pd.DataFrame, benchmark_px: pd.DataFrame, as_of: pd.Timestamp) -> dict[str, float]:
    actual, close_now = price_on_or_before(px, as_of, "close")
    if actual is None or close_now is None or close_now <= 0:
        return {}
    hist = px.loc[pd.DatetimeIndex(px.index) <= pd.Timestamp(actual)]
    if hist.empty:
        return {}
    close = pd.to_numeric(hist["close"], errors="coerce").dropna()
    if close.empty:
        return {}
    high_252 = float(close.tail(252).max())
    low_252 = float(close.tail(252).min())
    ma50 = float(close.tail(50).mean()) if len(close) >= 20 else math.nan
    ma200 = float(close.tail(200).mean()) if len(close) >= 60 else math.nan
    ret_1w = price_return(px, actual, 7)
    ret_4w = price_return(px, actual, 28)
    ret_13w = price_return(px, actual, 91)
    ret_26w = price_return(px, actual, 182)
    ret_52w = price_return(px, actual, 364)
    bench_4w = price_return(benchmark_px, actual, 28)
    bench_13w = price_return(benchmark_px, actual, 91)
    volume = pd.Series(dtype=float)
    if "volume" in hist.columns:
        volume = pd.to_numeric(hist["volume"], errors="coerce").dropna()
    dollar_vol_20d = float((close.tail(20).mean() if len(close) else 0.0) * (volume.tail(20).mean() if not volume.empty else 0.0))
    vol_ratio = 0.0
    if not volume.empty and len(volume) >= 60:
        base = float(volume.tail(60).mean())
        vol_ratio = float(volume.tail(20).mean() / base - 1.0) if base > 0 else 0.0
    return {
        # weekly_signal_date is the *intended* week_dt the caller wants
        # to evaluate at. It must NOT be back-shifted to the last actual
        # trading day (`actual`) — back-shifting let the W-FRI loop emit
        # signals on dates that coincided with monthly rebalance dates
        # (e.g. 2021-01-01 NYSE-closed -> 2020-12-31), which collided
        # with scheduled_rebalance rows in build_target_book_for_portfolio
        # and produced double-counted weights that the broker-ledger
        # replay rejected with max_total_weight=2.0.
        "weekly_signal_date": pd.Timestamp(as_of).date().isoformat(),
        "weekly_signal_actual_close_date": pd.Timestamp(actual).date().isoformat(),
        "weekly_close": float(close_now),
        "weekly_ret_1w": ret_1w,
        "weekly_ret_4w": ret_4w,
        "weekly_ret_13w": ret_13w,
        "weekly_ret_26w": ret_26w,
        "weekly_ret_52w": ret_52w,
        "weekly_rs_4w": ret_4w - bench_4w if math.isfinite(ret_4w) and math.isfinite(bench_4w) else math.nan,
        "weekly_rs_13w": ret_13w - bench_13w if math.isfinite(ret_13w) and math.isfinite(bench_13w) else math.nan,
        "weekly_near_52w_high_pct": float(close_now / high_252 - 1.0) if high_252 > 0 else math.nan,
        "weekly_drawdown_52w": float(close_now / high_252 - 1.0) if high_252 > 0 else math.nan,
        "weekly_range_position_52w": float((close_now - low_252) / max(high_252 - low_252, 1e-12)) if high_252 > low_252 else 0.0,
        "weekly_above_ma50": 1.0 if math.isfinite(ma50) and close_now >= ma50 else 0.0,
        "weekly_above_ma200": 1.0 if math.isfinite(ma200) and close_now >= ma200 else 0.0,
        "weekly_dollar_vol_20d": dollar_vol_20d,
        "weekly_volume_ratio_20v60": vol_ratio,
    }


def score_candidates(candidates: pd.DataFrame) -> pd.DataFrame:
    if candidates.empty:
        return candidates
    d = candidates.copy()
    d["monthly_model_score"] = numeric(d, "score")
    d["monthly_monster_score"] = numeric(d, "portfolio_monster_early_score")
    d["monthly_dynamic_leader_score"] = numeric(d, "h6_dynamic_leader_score")
    d["monthly_breakout_score"] = numeric(d, "breakout_setup_quality_score")
    d["monthly_industry_strength"] = numeric(d, "industry_group_strength_score")
    d["monthly_future_winner_score"] = numeric(d, "future_winner_scout_score")
    d["monthly_entry_quality"] = numeric(d, "entry_quality_score")
    d["monthly_stale_penalty"] = numeric(d, "portfolio_stale_mega_leader_score")
    d["monthly_risk_stack"] = pd.concat(
        [
            numeric(d, "risk_penalty"),
            numeric(d, "stage2_overext_penalty"),
            numeric(d, "overheat_penalty"),
            numeric(d, "explosion_exit_score"),
            numeric(d, "live_event_risk_score"),
        ],
        axis=1,
    ).max(axis=1).fillna(0.0)
    d["weekly_leader_score"] = (
        0.20 * robust_z(numeric(d, "weekly_ret_4w", math.nan))
        + 0.14 * robust_z(numeric(d, "weekly_ret_13w", math.nan))
        + 0.10 * robust_z(numeric(d, "weekly_ret_26w", math.nan))
        + 0.14 * robust_z(numeric(d, "weekly_rs_4w", math.nan))
        + 0.10 * robust_z(numeric(d, "weekly_rs_13w", math.nan))
        + 0.08 * robust_z(numeric(d, "weekly_volume_ratio_20v60", math.nan))
        + 0.08 * robust_z(np.log1p(numeric(d, "weekly_dollar_vol_20d").clip(lower=0.0)))
        + 0.09 * robust_z(d["monthly_monster_score"])
        + 0.06 * robust_z(d["monthly_dynamic_leader_score"])
        + 0.05 * robust_z(d["monthly_breakout_score"])
        + 0.04 * robust_z(d["monthly_industry_strength"])
        + 0.04 * robust_z(d["monthly_future_winner_score"])
        + 0.03 * d["weekly_above_ma50"].clip(0, 1)
        + 0.03 * d["weekly_above_ma200"].clip(0, 1)
        - 0.12 * d["monthly_risk_stack"].clip(lower=0.0)
        - 0.05 * d["monthly_stale_penalty"].clip(lower=0.0)
    )
    return d.sort_values("weekly_leader_score", ascending=False).reset_index(drop=True)


def period_end_dates(dates: list[pd.Timestamp], candidate_prices: dict[str, pd.DataFrame], period: pd.DataFrame, idx: int, dt: pd.Timestamp) -> pd.Timestamp | None:
    if idx + 1 < len(dates):
        return pd.Timestamp(dates[idx + 1]).normalize()
    latest: list[pd.Timestamp] = []
    for ticker in period["ticker"].astype(str).str.upper().unique():
        px = candidate_prices.get(ticker, pd.DataFrame())
        if not px.empty:
            latest.append(pd.Timestamp(px.index.max()).normalize())
    return max(latest) if latest else None


def weekly_signal_dates(start: pd.Timestamp, end: pd.Timestamp) -> list[pd.Timestamp]:
    if end <= start:
        return []
    dates = [pd.Timestamp(x).normalize() for x in pd.date_range(start=start + pd.Timedelta(days=1), end=end - pd.Timedelta(days=1), freq="W-FRI")]
    if not dates and (end - start).days >= 7:
        dates = [start + pd.Timedelta(days=7)]
    return dates


def base_weights_for_date(base_book: pd.DataFrame, dt: pd.Timestamp) -> tuple[dict[str, float], dict[str, dict[str, Any]]]:
    eligible = base_book[base_book["rebalance_date"].le(dt)].copy()
    if eligible.empty:
        return {}, {}
    latest_dt = eligible["rebalance_date"].max()
    period = eligible[eligible["rebalance_date"].eq(latest_dt)].copy()
    weights: dict[str, float] = {}
    templates: dict[str, dict[str, Any]] = {}
    for row in period.to_dict("records"):
        ticker = str(row.get("ticker") or "").upper().strip()
        if not ticker:
            continue
        templates[ticker] = row
        if ticker in CASH_TICKERS:
            continue
        weights[ticker] = weights.get(ticker, 0.0) + max(0.0, safe_float(row.get("weight"), 0.0))
    total = sum(weights.values())
    if total > 1.0:
        weights = {ticker: weight / total for ticker, weight in weights.items()}
    return weights, templates


def capacity_for_regime(portfolio_kind: str, regime: str) -> float:
    regime = str(regime or "neutral").lower()
    if portfolio_kind == "concentrated":
        return {
            "exceptional_bull": 1.0,
            "strong_bull": 1.0,
            "bull": 0.90,
            "neutral": 0.70,
            "bear": 0.25,
            "deep_bear": 0.0,
        }.get(regime, 0.50)
    return {
        "exceptional_bull": 0.35,
        "strong_bull": 0.33,
        "bull": 0.30,
        "neutral": 0.20,
        "bear": 0.08,
        "deep_bear": 0.0,
    }.get(regime, 0.15)


def score_power_weights(frame: pd.DataFrame, score_col: str, total_weight: float, single_cap: float) -> dict[str, float]:
    if frame.empty or total_weight <= 0:
        return {}
    scores = pd.to_numeric(frame[score_col], errors="coerce").fillna(0.0)
    min_score = float(scores.min()) if not scores.empty else 0.0
    raw: dict[str, float] = {}
    for row, score in zip(frame.to_dict("records"), scores, strict=False):
        ticker = str(row.get("ticker") or "").upper().strip()
        if not ticker:
            continue
        raw[ticker] = max(float(score) - min_score + 0.25, 1e-6) ** 2
    total = sum(raw.values())
    if total <= 0:
        return {}
    weights = {ticker: total_weight * value / total for ticker, value in raw.items()}
    cap = max(0.0, min(float(single_cap), 1.0))
    overflow = 0.0
    uncapped: list[str] = []
    for ticker, weight in list(weights.items()):
        if weight > cap:
            overflow += weight - cap
            weights[ticker] = cap
        else:
            uncapped.append(ticker)
    if overflow > 1e-12 and uncapped:
        uncapped_total = sum(weights[ticker] for ticker in uncapped)
        for ticker in uncapped:
            weights[ticker] += overflow * weights[ticker] / max(uncapped_total, 1e-12)
            weights[ticker] = min(weights[ticker], cap)
    return {ticker: weight for ticker, weight in weights.items() if weight > 1e-12}


def combine_base_and_leaders(
    base_weights: dict[str, float],
    leader_weights: dict[str, float],
    *,
    single_cap: float,
) -> dict[str, float]:
    leader_sum = min(sum(leader_weights.values()), 1.0)
    remaining = max(0.0, 1.0 - leader_sum)
    base_sum = sum(base_weights.values())
    combined: dict[str, float] = {}
    if base_sum > 0 and remaining > 0:
        for ticker, weight in base_weights.items():
            combined[ticker] = combined.get(ticker, 0.0) + remaining * weight / base_sum
    for ticker, weight in leader_weights.items():
        combined[ticker] = combined.get(ticker, 0.0) + weight
    cap = max(0.0, min(float(single_cap), 1.0))
    combined = {ticker: min(weight, cap) for ticker, weight in combined.items() if weight > 1e-12}
    total = sum(combined.values())
    if total > 1.0:
        combined = {ticker: weight / total for ticker, weight in combined.items()}
    return combined


def snapshot_rows(
    *,
    snapshot_date: pd.Timestamp,
    weights: dict[str, float],
    templates: dict[str, dict[str, Any]],
    selected: pd.DataFrame,
    portfolio_kind: str,
    event_kind: str,
    event_reason: str,
) -> list[dict[str, Any]]:
    selected_lookup = {str(row.get("ticker") or "").upper(): row for row in selected.to_dict("records")} if not selected.empty else {}
    rows: list[dict[str, Any]] = []
    stock_sum = 0.0
    for ticker, weight in sorted(weights.items()):
        if ticker in CASH_TICKERS or weight <= 1e-12:
            continue
        base = dict(templates.get(ticker, {}))
        leader = selected_lookup.get(ticker, {})
        base.update({f"weekly_{key}": value for key, value in leader.items() if key.startswith("weekly_") or key in {"weekly_leader_score", "leader_rank"}})
        base["rebalance_date"] = snapshot_date.date().isoformat()
        base["ticker"] = ticker
        base["weight"] = float(weight)
        base["portfolio_kind"] = portfolio_kind
        base["weekly_leader_target_book"] = True
        base["event_kind"] = event_kind
        base["event_reason"] = event_reason
        base["leader_entry_selected"] = ticker in selected_lookup
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
                "weekly_leader_target_book": True,
                "event_kind": event_kind,
                "event_reason": event_reason,
                "leader_entry_selected": False,
            }
        )
    return rows


def build_weekly_snapshots(
    *,
    candidates: pd.DataFrame,
    price_cache: Path,
    benchmark_ticker: str,
    min_mcap: float,
    min_dollar_vol: float,
    min_price: float,
    snapshot_top_k: int,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    dates = [pd.Timestamp(x).normalize() for x in sorted(candidates["rebalance_date"].dropna().unique())]
    tickers = sorted(set(candidates["ticker"].astype(str).str.upper()))
    prices = {ticker: load_price_series(price_cache, ticker) for ticker in tickers}
    prices = {ticker: frame for ticker, frame in prices.items() if not frame.empty}
    benchmark_px = load_price_series(price_cache, benchmark_ticker)
    rows: list[dict[str, Any]] = []
    scanned_weeks = 0
    missing_price_rows = 0
    for idx, dt in enumerate(dates):
        period = candidates[candidates["rebalance_date"].eq(dt)].copy()
        if period.empty:
            continue
        end_dt = period_end_dates(dates, prices, period, idx, dt)
        if end_dt is None:
            continue
        for week_dt in weekly_signal_dates(dt, end_dt):
            feature_rows: list[dict[str, Any]] = []
            for row in period.to_dict("records"):
                ticker = str(row.get("ticker") or "").upper().strip()
                px = prices.get(ticker, pd.DataFrame())
                feats = price_features(px, benchmark_px, week_dt)
                if not feats:
                    missing_price_rows += 1
                    continue
                if safe_float(feats.get("weekly_dollar_vol_20d"), 0.0) <= 0:
                    feats["weekly_dollar_vol_20d"] = first_numeric(row, ("dollar_vol_20d", "daily_dollar_vol", "pre_run_daily_dollar_vol_usd"), 0.0)
                market_cap = first_numeric(row, ("market_cap_live", "mktcap", "market_cap_current"), 0.0)
                base_px = first_numeric(row, ("current_price_live", "px", "price_current"), feats.get("weekly_close", 0.0))
                if market_cap > 0 and base_px > 0 and feats.get("weekly_close", 0.0) > 0:
                    market_cap = market_cap * feats["weekly_close"] / base_px
                if (
                    market_cap < float(min_mcap)
                    or feats.get("weekly_dollar_vol_20d", 0.0) < float(min_dollar_vol)
                    or feats.get("weekly_close", 0.0) < float(min_price)
                ):
                    continue
                merged = dict(row)
                merged.update(feats)
                merged["market_cap_weekly"] = market_cap
                feature_rows.append(merged)
            if not feature_rows:
                continue
            scored = score_candidates(pd.DataFrame(feature_rows))
            scored = scored.head(int(snapshot_top_k)).copy()
            scored["leader_rank"] = range(1, len(scored) + 1)
            scored["candidate_rebalance_date"] = dt.date().isoformat()
            scanned_weeks += 1
            rows.extend(scored.to_dict("records"))
    out = pd.DataFrame(rows)
    if not out.empty:
        out = out.sort_values(["weekly_signal_date", "leader_rank"]).reset_index(drop=True)
    return out, {
        "candidate_months": len(dates),
        "price_ticker_count": len(prices),
        "weekly_snapshot_count": int(scanned_weeks),
        "weekly_snapshot_row_count": int(len(out)),
        "missing_price_rows": int(missing_price_rows),
    }


def build_target_book_for_portfolio(
    *,
    base_book: pd.DataFrame,
    base_meta: dict[str, Any],
    weekly_snapshots: pd.DataFrame,
    portfolio_kind: str,
    top_n: int,
    min_score_quantile: float,
    single_cap: float,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    if base_book.empty:
        return pd.DataFrame(), pd.DataFrame(), {"status": "blocked", "reason": "base target book empty", **base_meta}
    rows: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    for dt, period in base_book.groupby("rebalance_date", sort=True):
        base_weights, templates = base_weights_for_date(base_book, pd.Timestamp(dt))
        rows.extend(
            snapshot_rows(
                snapshot_date=pd.Timestamp(dt),
                weights=base_weights,
                templates=templates,
                selected=pd.DataFrame(),
                portfolio_kind=portfolio_kind,
                event_kind="scheduled_rebalance",
                event_reason="base_target_book",
            )
        )
    if weekly_snapshots.empty:
        return pd.DataFrame(rows), pd.DataFrame(events), {"status": "completed", "weekly_entry_count": 0, **base_meta}
    all_scores = pd.to_numeric(weekly_snapshots["weekly_leader_score"], errors="coerce").dropna()
    score_floor = float(all_scores.quantile(float(min_score_quantile))) if not all_scores.empty else -math.inf
    for week_dt_text, week in weekly_snapshots.groupby("weekly_signal_date", sort=True):
        week_dt = pd.Timestamp(week_dt_text).normalize()
        selected = week[pd.to_numeric(week["weekly_leader_score"], errors="coerce").fillna(-math.inf) >= score_floor].head(int(top_n)).copy()
        if selected.empty:
            continue
        regime = str(selected.iloc[0].get("regime_state") or "neutral")
        capacity = capacity_for_regime(portfolio_kind, regime)
        if capacity <= 1e-12:
            continue
        leader_weights = score_power_weights(selected, "weekly_leader_score", capacity, single_cap)
        if not leader_weights:
            continue
        base_weights, templates = base_weights_for_date(base_book, week_dt)
        combined = combine_base_and_leaders(base_weights, leader_weights, single_cap=single_cap)
        # Defensive dedup. When a weekly_leader_entry fires on a date
        # that already has scheduled_rebalance rows from the base loop
        # (e.g. price_on_or_before would have collided with a monthly
        # boundary before the as_of fix), the broker-ledger replay sees
        # both row sets and sums weights to 2.0 -> hard block. Drop both
        # event kinds for the target date so the new combined rows are
        # the single source of truth.
        rows = [
            row
            for row in rows
            if not (
                str(row.get("rebalance_date")) == week_dt.date().isoformat()
                and str(row.get("event_kind")) in {"weekly_leader_entry", "scheduled_rebalance"}
            )
        ]
        rows.extend(
            snapshot_rows(
                snapshot_date=week_dt,
                weights=combined,
                templates=templates,
                selected=selected,
                portfolio_kind=portfolio_kind,
                event_kind="weekly_leader_entry",
                event_reason=f"top_{top_n}_weekly_leader_score",
            )
        )
        for rank, row in enumerate(selected.to_dict("records"), start=1):
            ticker = str(row.get("ticker") or "").upper()
            events.append(
                {
                    "portfolio_kind": portfolio_kind,
                    "weekly_signal_date": week_dt.date().isoformat(),
                    "ticker": ticker,
                    "leader_rank": rank,
                    "target_weight_after": combined.get(ticker, 0.0),
                    "leader_overlay_weight": leader_weights.get(ticker, 0.0),
                    "weekly_leader_score": row.get("weekly_leader_score"),
                    "weekly_ret_4w": row.get("weekly_ret_4w"),
                    "weekly_rs_4w": row.get("weekly_rs_4w"),
                    "weekly_dollar_vol_20d": row.get("weekly_dollar_vol_20d"),
                    "regime_state": regime,
                }
            )
    out = pd.DataFrame(rows)
    if not out.empty:
        out["rebalance_date"] = pd.to_datetime(out["rebalance_date"], errors="coerce").dt.date.astype(str)
        out["weight"] = pd.to_numeric(out["weight"], errors="coerce").fillna(0.0)
        out = out[(out["ticker"].astype(str).str.upper().str.strip() != "") & (out["weight"] > 1e-12)].copy()
        out = out.sort_values(["rebalance_date", "ticker"]).reset_index(drop=True)
    events_df = pd.DataFrame(events)
    return out, events_df, {
        "status": "completed" if not out.empty else "blocked",
        "weekly_entry_count": int(len(events_df)),
        "weekly_signal_count": int(events_df["weekly_signal_date"].nunique()) if not events_df.empty else 0,
        "top_n": int(top_n),
        "min_score_quantile": float(min_score_quantile),
        "single_cap": float(single_cap),
        **base_meta,
    }


def render_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Weekly Leader Entry Target Books",
        "",
        "Research-only weekly entry challenger. Monthly candidate rows define the PIT eligible universe; daily price cache defines weekly leadership signals.",
        "",
        "| Portfolio | Status | Target Rows | Weekly Entries | Weekly Signals |",
        "| --- | --- | ---: | ---: | ---: |",
    ]
    for row in payload.get("books", []):
        lines.append(
            "| {portfolio} | {status} | {rows} | {entries} | {signals} |".format(
                portfolio=row.get("portfolio_kind"),
                status=row.get("status"),
                rows=row.get("target_row_count"),
                entries=row.get("weekly_entry_count"),
                signals=row.get("weekly_signal_count"),
            )
        )
    lines.extend(
        [
            "",
            "Forward-label columns are excluded from selection. This is not production-active; promotion requires broker-ledger target pass, stress windows, and cost sensitivity.",
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
    candidate_path = repo_path(args.candidate_book) if args.candidate_book else latest_run / "reports" / "candidate_replay_book.csv"
    candidates = normalize_candidate_book(read_csv(candidate_path))
    if candidates.empty:
        payload = {
            "schema_version": "weekly-leader-target-books-v1",
            "generated_at_utc": now_utc(),
            "experiment_id": EXPERIMENT_ID,
            "status": "blocked",
            "reason": "candidate replay book missing or empty",
            "candidate_book": str(candidate_path),
            "research_only": True,
            "production_activation_allowed": False,
            "valid_for_production": False,
        }
        write_json(output_dir / "summary.json", payload)
        write_text(output_dir / "report.md", render_report(payload))
        return payload
    weekly_snapshots, snapshot_summary = build_weekly_snapshots(
        candidates=candidates,
        price_cache=price_cache,
        benchmark_ticker=args.benchmark_ticker,
        min_mcap=args.min_mcap,
        min_dollar_vol=args.min_dollar_vol,
        min_price=args.min_price,
        snapshot_top_k=args.snapshot_top_k,
    )
    weekly_snapshots.to_csv(output_dir / "weekly_leader_snapshots.csv", index=False)
    books: list[dict[str, Any]] = []
    outputs: dict[str, str] = {"weekly_leader_snapshots": str(output_dir / "weekly_leader_snapshots.csv")}
    main_default = latest_run / "reports" / "operating_main_target_book.csv"
    if not main_default.exists():
        main_default = latest_run / "reports" / "main_monthly_weights.csv"
    concentrated_default = latest_run / "reports" / "operating_concentrated_target_book.csv"
    if not concentrated_default.exists():
        concentrated_default = latest_run / "reports" / "concentrated_strategy_holdings.csv"
    specs = [
        ("main", main_default, args.main_top_n, args.main_single_cap),
        ("concentrated", concentrated_default, args.concentrated_top_n, args.concentrated_single_cap),
    ]
    for portfolio_kind, default_book, top_n, single_cap in specs:
        target_book = repo_path(getattr(args, f"{portfolio_kind}_target_book")) if getattr(args, f"{portfolio_kind}_target_book") else default_book
        base_book, base_meta = normalize_book(read_csv(target_book), portfolio_kind, target_book)
        book, events, summary = build_target_book_for_portfolio(
            base_book=base_book,
            base_meta=base_meta,
            weekly_snapshots=weekly_snapshots,
            portfolio_kind=portfolio_kind,
            top_n=top_n,
            min_score_quantile=args.min_score_quantile,
            single_cap=single_cap,
        )
        book_path = reports_dir / f"weekly_leader_{portfolio_kind}_target_book.csv"
        events_path = output_dir / f"{portfolio_kind}_entries.csv"
        if not book.empty:
            book.to_csv(book_path, index=False)
        else:
            pd.DataFrame(columns=["rebalance_date", "ticker", "weight"]).to_csv(book_path, index=False)
        events.to_csv(events_path, index=False)
        summary.update(
            {
                "portfolio_kind": portfolio_kind,
                "target_book": str(target_book),
                "weekly_leader_target_book": str(book_path),
                "weekly_entries_path": str(events_path),
                "target_row_count": int(len(book)),
                "research_only": True,
                "production_activation_allowed": False,
                "valid_for_production": False,
            }
        )
        books.append(summary)
        outputs[f"{portfolio_kind}_target_book"] = str(book_path)
        outputs[f"{portfolio_kind}_entries"] = str(events_path)
    payload = {
        "schema_version": "weekly-leader-target-books-v1",
        "generated_at_utc": now_utc(),
        "experiment_id": EXPERIMENT_ID,
        "status": "completed" if all(row.get("status") == "completed" for row in books) else "partial",
        "candidate_book": str(candidate_path),
        "price_cache": str(price_cache),
        "benchmark_ticker": args.benchmark_ticker.upper(),
        "data_mode": "monthly_candidate_book_plus_weekly_price_snapshot",
        "research_only": True,
        "production_activation_allowed": False,
        "valid_for_production": False,
        "leakage_guard_excluded_columns": sorted(FORWARD_LABEL_COLUMNS),
        "snapshot_summary": snapshot_summary,
        "books": books,
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
    parser.add_argument("--latest-run", default=DEFAULT_LATEST_RUN)
    parser.add_argument("--candidate-book", default="")
    parser.add_argument("--price-cache", default="cache_prices")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--reports-dir", default=DEFAULT_REPORTS_DIR)
    parser.add_argument("--main-target-book", default="")
    parser.add_argument("--concentrated-target-book", default="")
    parser.add_argument("--benchmark-ticker", default="SPY")
    parser.add_argument("--min-mcap", type=float, default=5_000_000_000)
    parser.add_argument("--min-dollar-vol", type=float, default=20_000_000)
    parser.add_argument("--min-price", type=float, default=10.0)
    parser.add_argument("--snapshot-top-k", type=int, default=25)
    parser.add_argument("--main-top-n", type=int, default=3)
    parser.add_argument("--concentrated-top-n", type=int, default=3)
    parser.add_argument("--main-single-cap", type=float, default=0.33)
    parser.add_argument("--concentrated-single-cap", type=float, default=0.50)
    parser.add_argument("--min-score-quantile", type=float, default=0.80)
    return parser.parse_args()


def main() -> int:
    payload = build(parse_args())
    return 0 if payload.get("status") in {"completed", "partial"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
