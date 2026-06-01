#!/usr/bin/env python3
"""Research-only superperformance trade replay.

This sidecar turns leader-style buy/sell rules into dated target-book rows,
then replays those rows through the broker-ledger next-close engine. It is
intended to answer a narrow question: if Minervini/O'Neil/Darvas-inspired
setup, stop, and add/exit rules had been applied historically, would the
broker ledger have actually bought, sold, and improved outcomes?

It never mutates production target books or current holdings.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.run_broker_ledger_replay import DISABLE_CONCENTRATED_CHAMPION_FILTERS, replay as broker_replay
from tools.run_weekly_evaluation import px_cache_name


DEFAULT_OUTPUT_DIR = "outputs/superperformance_trader_replay"
BENCHMARKS = ("SPY", "QQQ")
CASH_TICKER = "CASH"


@dataclass
class PositionState:
    ticker: str
    weight: float
    entry_date: pd.Timestamp
    entry_price: float
    stop_price: float
    pivot_price: float
    setup_score: float
    holding_weeks: int = 0


PORTFOLIO_CONFIGS: dict[str, dict[str, float | int]] = {
    "main": {
        "max_positions": 16,
        "target_gross": 0.95,
        "single_cap": 0.10,
        "entry_weight": 0.055,
        "min_setup_score": 0.62,
        "min_add_gain": 0.05,
        "min_hold_weeks": 4,
        "max_adds_per_week": 3,
    },
    "concentrated": {
        "max_positions": 5,
        "target_gross": 0.98,
        "single_cap": 0.35,
        "entry_weight": 0.25,
        "min_setup_score": 0.70,
        "min_add_gain": 0.06,
        "min_hold_weeks": 3,
        "max_adds_per_week": 2,
    },
}


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def now_utc() -> str:
    return pd.Timestamp.utcnow().isoformat()


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        out = float(value)
        if math.isfinite(out):
            return out
    except (TypeError, ValueError):
        pass
    return default


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=json_default), encoding="utf-8")


def json_default(value: Any) -> Any:
    if isinstance(value, pd.Timestamp):
        return value.date().isoformat() if pd.notna(value) else None
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, Path):
        return str(value)
    return value


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame()


def load_price_frame(price_cache: Path, ticker: str) -> pd.DataFrame:
    path = price_cache / px_cache_name(ticker)
    if not path.exists():
        return pd.DataFrame()
    try:
        raw = pd.read_parquet(path)
    except Exception:
        return pd.DataFrame()
    if raw.empty:
        return pd.DataFrame()
    frame = raw.copy()
    if isinstance(frame.columns, pd.MultiIndex):
        frame.columns = frame.columns.get_level_values(0)
    if "date" in frame.columns:
        idx = pd.to_datetime(frame["date"], errors="coerce")
    else:
        idx = pd.to_datetime(frame.index, errors="coerce")
    frame.index = pd.DatetimeIndex(idx).tz_localize(None)
    frame = frame[frame.index.notna()].sort_index()
    close_col = next((col for col in ("Adj Close", "Close", "close", "adj_close") if col in frame.columns), "")
    if not close_col:
        return pd.DataFrame()
    out = pd.DataFrame(index=frame.index)
    out["close"] = pd.to_numeric(frame[close_col], errors="coerce")
    if "Volume" in frame.columns:
        out["volume"] = pd.to_numeric(frame["Volume"], errors="coerce")
    elif "volume" in frame.columns:
        out["volume"] = pd.to_numeric(frame["volume"], errors="coerce")
    else:
        out["volume"] = np.nan
    return out.dropna(subset=["close"])


def ret_n(frame: pd.DataFrame, periods: int) -> float:
    if frame.empty or len(frame) <= periods:
        return 0.0
    end = safe_float(frame["close"].iloc[-1], math.nan)
    start = safe_float(frame["close"].iloc[-periods - 1], math.nan)
    if not math.isfinite(end) or not math.isfinite(start) or start <= 0:
        return 0.0
    return float(end / start - 1.0)


def first_available(row: pd.Series, cols: tuple[str, ...], default: float = 0.0) -> float:
    for col in cols:
        if col in row.index:
            val = safe_float(row.get(col), math.nan)
            if math.isfinite(val):
                return val
    return default


def bounded_score(value: float) -> float:
    if not math.isfinite(value):
        return 0.0
    if 0.0 <= value <= 1.5:
        return max(0.0, min(1.0, value))
    return 1.0 / (1.0 + math.exp(-value))


def max_component(row: pd.Series, cols: tuple[str, ...], default: float = 0.0) -> float:
    vals = [safe_float(row.get(col), math.nan) for col in cols if col in row.index]
    vals = [val for val in vals if math.isfinite(val)]
    return max(vals) if vals else default


def row_available_from(row: pd.Series) -> pd.Timestamp | None:
    for col in (
        "available_from",
        "latest_available_from",
        "sec_available_from",
        "form4_available_from",
        "form4_latest_available_from",
        "institutional_13f_available_from",
        "13f_available_from",
        "etf_available_from",
        "top7_available_from",
    ):
        if col not in row.index:
            continue
        dt = pd.to_datetime(row.get(col), errors="coerce")
        if pd.notna(dt):
            return pd.Timestamp(dt).tz_localize(None) if getattr(dt, "tzinfo", None) is not None else pd.Timestamp(dt)
    return None


def pit_evidence_allowed(row: pd.Series, signal_date: pd.Timestamp) -> tuple[bool, str]:
    available = row_available_from(row)
    if available is None:
        return True, "candidate_book_pit_or_no_available_from"
    allowed = pd.Timestamp(available).normalize() <= pd.Timestamp(signal_date).normalize()
    return bool(allowed), "" if allowed else f"evidence_available_after_signal:{pd.Timestamp(available).date().isoformat()}"


def evidence_component(row: pd.Series, signal_date: pd.Timestamp) -> tuple[float, str]:
    allowed, reason = pit_evidence_allowed(row, signal_date)
    if not allowed:
        return 0.0, reason
    score = max_component(
        row,
        (
            "evidence_fusion_score",
            "smart_money_shadow_score",
            "smart_money_confirmation_score",
            "sec_combined_evidence_score",
            "institutional_evidence_score",
            "institutional_13f_score",
            "top7_discovery_score",
            "top7_13f_event_score",
            "early_evidence_score",
            "form4_cluster_buy_score",
            "sec_form4_cluster_buy_score",
            "etf_holdings_score",
            "etf_evidence_score",
        ),
        0.0,
    )
    confidence = max_component(
        row,
        (
            "evidence_confidence_score",
            "smart_money_evidence_confidence",
            "institutional_evidence_confidence_score",
            "etf_evidence_confidence",
        ),
        1.0 if score > 0 else 0.0,
    )
    return max(0.0, min(1.0, score * max(0.35, min(1.0, confidence)))), "pit_safe"


def monster_component(row: pd.Series) -> float:
    return max(0.0, min(1.0, max_component(
        row,
        (
            "portfolio_monster_early_score",
            "portfolio_future_winner_engine_score",
            "future_winner_scout_score",
            "future_winner_confirmation_score",
            "breakout_setup_quality_score",
            "post_breakout_hold_score",
            "h6_dynamic_leader_score",
            "leader_onset_score",
            "monster_lifecycle_score",
            "revenue_acceleration",
            "rev_growth_accel_4q",
            "profitability_inflection_score",
            "cashflow_inflection_under_loss_score",
        ),
        0.0,
    )))


def macro_risk_component(row: pd.Series) -> float:
    return max(0.0, min(1.0, max_component(
        row,
        (
            "macro_risk_score",
            "macro_policy_risk_score",
            "risk_penalty",
            "live_event_risk_score",
            "overheat_penalty",
            "stage2_overext_penalty",
            "explosion_exit_score",
            "distribution_risk_score",
            "leader_chase_risk_score",
        ),
        0.0,
    )))


def setup_features(
    *,
    row: pd.Series,
    price: pd.DataFrame,
    spy: pd.DataFrame,
    qqq: pd.DataFrame,
    signal_date: pd.Timestamp,
) -> dict[str, Any]:
    ticker = str(row.get("ticker") or "").upper().strip()
    px = price.loc[price.index <= signal_date].copy()
    spy_hist = spy.loc[spy.index <= signal_date].copy()
    qqq_hist = qqq.loc[qqq.index <= signal_date].copy()
    if px.empty:
        return {
            "ticker": ticker,
            "signal_date": signal_date.date().isoformat(),
            "eligible": False,
            "reject_reason": "missing_price_history",
        }
    close = safe_float(px["close"].iloc[-1], math.nan)
    ma50 = safe_float(px["close"].rolling(50).mean().iloc[-1], math.nan)
    ma150 = safe_float(px["close"].rolling(150).mean().iloc[-1], math.nan)
    ma200_series = px["close"].rolling(200).mean()
    ma200 = safe_float(ma200_series.iloc[-1], math.nan)
    ma200_prior = safe_float(ma200_series.iloc[-21], math.nan) if len(ma200_series) > 220 else math.nan
    high_52w = safe_float(px["close"].tail(252).max(), math.nan)
    low_52w = safe_float(px["close"].tail(252).min(), math.nan)
    range_10 = safe_float((px["close"].tail(10).max() - px["close"].tail(10).min()) / close, math.nan)
    range_20 = safe_float((px["close"].tail(20).max() - px["close"].tail(20).min()) / close, math.nan)
    range_60 = safe_float((px["close"].tail(60).max() - px["close"].tail(60).min()) / close, math.nan)
    avg_vol10 = safe_float(px["volume"].tail(10).mean(), math.nan)
    avg_vol50 = safe_float(px["volume"].tail(50).mean(), math.nan)
    today_vol = safe_float(px["volume"].iloc[-1], math.nan)
    volume_available = math.isfinite(today_vol) and math.isfinite(avg_vol50) and avg_vol50 > 0
    volume_expansion = bool(today_vol >= 1.4 * avg_vol50) if volume_available else True
    volume_dryup = bool(avg_vol10 <= avg_vol50) if math.isfinite(avg_vol10) and math.isfinite(avg_vol50) and avg_vol50 > 0 else True
    prior20 = px["close"].iloc[:-1].tail(20)
    pivot = safe_float(prior20.max(), math.nan) if not prior20.empty else math.nan
    box_low = safe_float(px["close"].tail(20).min(), math.nan)
    darvas_breakout = bool(math.isfinite(pivot) and close > pivot * 1.005 and volume_expansion)
    vcp_proxy = bool(
        math.isfinite(range_10)
        and math.isfinite(range_20)
        and math.isfinite(range_60)
        and range_20 <= 0.75 * range_60
        and range_10 <= 0.90 * range_20
        and volume_dryup
        and math.isfinite(pivot)
        and close > pivot * 1.002
    )
    stock_ret_63 = ret_n(px, 63)
    stock_ret_126 = ret_n(px, 126)
    rs_spy_13w = stock_ret_63 - ret_n(spy_hist, 63)
    rs_qqq_13w = stock_ret_63 - ret_n(qqq_hist, 63)
    rs_spy_26w = stock_ret_126 - ret_n(spy_hist, 126)
    rs_qqq_26w = stock_ret_126 - ret_n(qqq_hist, 126)
    rs_pass = bool(rs_spy_13w > 0.0 and rs_qqq_13w > 0.0 and (rs_spy_26w > -0.02 or rs_qqq_26w > -0.02))
    trend_template_pass = bool(
        math.isfinite(close)
        and math.isfinite(ma50)
        and math.isfinite(ma150)
        and math.isfinite(ma200)
        and close > ma50 > ma150 > ma200
        and ma150 > ma200
        and (not math.isfinite(ma200_prior) or ma200 >= ma200_prior)
        and (not math.isfinite(high_52w) or close >= 0.75 * high_52w)
        and (not math.isfinite(low_52w) or close >= 1.30 * low_52w)
    )
    leader_raw = first_available(
        row,
        (
            "leader_selection_score",
            "market_leader_tape_score",
            "oneil_leadership_score",
            "industry_group_strength_score",
            "sub_industry_rs_score",
            "score",
            "future_winner_confirmation_score",
        ),
        0.0,
    )
    leader_component = bounded_score(leader_raw)
    evidence_score, evidence_guard = evidence_component(row, signal_date)
    monster_score = monster_component(row)
    macro_risk = macro_risk_component(row)
    liquidity_component = bounded_score(first_available(row, ("liquidity_capacity_score", "dollar_vol_20d", "avg_dollar_volume_20d"), 0.5))
    if liquidity_component > 1.0:
        liquidity_component = 1.0
    rs_component = max(0.0, min(1.0, 0.5 + 2.0 * max(rs_spy_13w, rs_qqq_13w)))
    breakout_component = 1.0 if darvas_breakout or vcp_proxy else 0.0
    setup_score_raw = (
        0.22 * float(trend_template_pass)
        + 0.18 * rs_component
        + 0.18 * breakout_component
        + 0.08 * float(volume_expansion)
        + 0.16 * leader_component
        + 0.08 * evidence_score
        + 0.08 * monster_score
        + 0.05 * liquidity_component
        - 0.08 * macro_risk
    )
    setup_score = max(0.0, min(1.0, setup_score_raw))
    stop_floor = close * 0.92 if math.isfinite(close) else math.nan
    box_stop = box_low * 0.99 if math.isfinite(box_low) and box_low > 0 else math.nan
    stop_price = max(stop_floor, box_stop) if math.isfinite(stop_floor) and math.isfinite(box_stop) else stop_floor
    evidence_pit_safe = not evidence_guard.startswith("evidence_available_after_signal")
    eligible = bool(trend_template_pass and rs_pass and setup_score >= 0.62 and macro_risk < 0.85 and evidence_pit_safe and (darvas_breakout or vcp_proxy or breakout_component > 0))
    reject_reason = "" if eligible else ";".join(
        reason
        for reason, failed in [
            ("trend_template_fail", not trend_template_pass),
            ("relative_strength_fail", not rs_pass),
            ("no_breakout", not (darvas_breakout or vcp_proxy)),
            ("setup_score_low", setup_score < 0.62),
            ("macro_risk_block", macro_risk >= 0.85),
            ("evidence_pit_guard_block", evidence_guard.startswith("evidence_available_after_signal")),
        ]
        if failed
    )
    return {
        "signal_date": signal_date.date().isoformat(),
        "ticker": ticker,
        "close": close,
        "ma50": ma50,
        "ma150": ma150,
        "ma200": ma200,
        "ma200_rising": bool(not math.isfinite(ma200_prior) or ma200 >= ma200_prior),
        "high_52w": high_52w,
        "low_52w": low_52w,
        "trend_template_pass": trend_template_pass,
        "rs_spy_13w": rs_spy_13w,
        "rs_qqq_13w": rs_qqq_13w,
        "rs_spy_26w": rs_spy_26w,
        "rs_qqq_26w": rs_qqq_26w,
        "rs_pass": rs_pass,
        "pivot_price": pivot,
        "box_low": box_low,
        "darvas_breakout": darvas_breakout,
        "vcp_proxy_breakout": vcp_proxy,
        "range_10d": range_10,
        "range_20d": range_20,
        "range_60d": range_60,
        "volume_available": volume_available,
        "volume_expansion": volume_expansion,
        "volume_dryup": volume_dryup,
        "setup_score": setup_score,
        "setup_score_raw": setup_score_raw,
        "leader_component": leader_component,
        "evidence_component": evidence_score,
        "evidence_guard": evidence_guard,
        "monster_component": monster_score,
        "macro_risk_component": macro_risk,
        "liquidity_component": liquidity_component,
        "stop_price": stop_price,
        "stop_pct": float(close / stop_price - 1.0) if math.isfinite(close) and math.isfinite(stop_price) and stop_price > 0 else np.nan,
        "eligible": eligible,
        "reject_reason": reject_reason,
    }


def active_candidate_windows(candidate: pd.DataFrame) -> list[tuple[pd.Timestamp, pd.Timestamp, pd.DataFrame]]:
    dates = sorted(pd.to_datetime(candidate["rebalance_date"], errors="coerce").dropna().dt.normalize().unique())
    windows: list[tuple[pd.Timestamp, pd.Timestamp, pd.DataFrame]] = []
    for idx, raw_dt in enumerate(dates):
        start = pd.Timestamp(raw_dt).normalize()
        if idx + 1 < len(dates):
            end = pd.Timestamp(dates[idx + 1]).normalize() - pd.Timedelta(days=1)
        else:
            end = start + pd.DateOffset(months=1)
        month = candidate[pd.to_datetime(candidate["rebalance_date"], errors="coerce").dt.normalize().eq(start)].copy()
        windows.append((start, pd.Timestamp(end).normalize(), month))
    return windows


def weekly_dates(start: pd.Timestamp, end: pd.Timestamp) -> list[pd.Timestamp]:
    dates = [pd.Timestamp(start).normalize()]
    dates.extend(pd.Timestamp(x).normalize() for x in pd.date_range(start=start, end=end, freq="W-FRI"))
    if pd.Timestamp(end).normalize() not in dates:
        dates.append(pd.Timestamp(end).normalize())
    return sorted({x for x in dates if start <= x <= end})


def score_month_candidates(
    month: pd.DataFrame,
    prices: dict[str, pd.DataFrame],
    signal_date: pd.Timestamp,
) -> pd.DataFrame:
    spy = prices.get("SPY", pd.DataFrame())
    qqq = prices.get("QQQ", pd.DataFrame())
    rows: list[dict[str, Any]] = []
    for _, row in month.iterrows():
        ticker = str(row.get("ticker") or "").upper().strip()
        if not ticker or ticker == CASH_TICKER:
            continue
        feat = setup_features(row=row, price=prices.get(ticker, pd.DataFrame()), spy=spy, qqq=qqq, signal_date=signal_date)
        for col in ("Name", "sector", "industry_group", "subindustry"):
            if col in row.index:
                feat[col] = row.get(col)
        rows.append(feat)
    if not rows:
        return pd.DataFrame()
    out = pd.DataFrame(rows)
    return out.sort_values(["setup_score", "rs_qqq_13w", "rs_spy_13w"], ascending=[False, False, False]).reset_index(drop=True)


def exit_reason_for_position(pos: PositionState, feat: dict[str, Any], signal_date: pd.Timestamp) -> str:
    close = safe_float(feat.get("close"), math.nan)
    ma50 = safe_float(feat.get("ma50"), math.nan)
    ma200 = safe_float(feat.get("ma200"), math.nan)
    rs_qqq = safe_float(feat.get("rs_qqq_13w"), 0.0)
    if math.isfinite(close) and close <= float(pos.stop_price):
        return "stop_loss"
    if math.isfinite(close) and math.isfinite(ma200) and close < ma200:
        return "stage4_break_ma200"
    if math.isfinite(close) and math.isfinite(ma50) and close < ma50 and rs_qqq <= 0.0:
        return "rs_break_ma50"
    if (signal_date - pos.entry_date).days <= 21 and math.isfinite(close) and close < float(pos.pivot_price):
        return "failed_breakout"
    return ""


def allocate_weights(
    holdings: dict[str, PositionState],
    setup_lookup: dict[str, dict[str, Any]],
    portfolio_kind: str,
) -> dict[str, float]:
    cfg = PORTFOLIO_CONFIGS[portfolio_kind]
    if not holdings:
        return {}
    target_gross = float(cfg["target_gross"])
    cap = float(cfg["single_cap"])
    scores = {
        ticker: max(0.01, safe_float(setup_lookup.get(ticker, {}).get("setup_score"), pos.setup_score))
        for ticker, pos in holdings.items()
    }
    total = sum(scores.values()) or 1.0
    weights = {ticker: min(cap, target_gross * score / total) for ticker, score in scores.items()}
    # Recycle uncapped residual once so small books do not sit in excessive cash.
    for _ in range(2):
        used = sum(weights.values())
        residual = target_gross - used
        if residual <= 1e-6:
            break
        room = {ticker: max(0.0, cap - weight) for ticker, weight in weights.items()}
        room_total = sum(room.values())
        if room_total <= 1e-9:
            break
        for ticker in weights:
            weights[ticker] += residual * room[ticker] / room_total
    return {ticker: float(weight) for ticker, weight in weights.items() if weight > 1e-6}


def target_rows(
    *,
    signal_date: pd.Timestamp,
    weights: dict[str, float],
    setup_lookup: dict[str, dict[str, Any]],
    portfolio_kind: str,
    reason: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for ticker, weight in sorted(weights.items(), key=lambda item: item[1], reverse=True):
        feat = setup_lookup.get(ticker, {})
        rows.append(
            {
                "rebalance_date": signal_date.date().isoformat(),
                "ticker": ticker,
                "Name": feat.get("Name", ""),
                "sector": feat.get("sector", ""),
                "weight": float(weight),
                "target_weight": float(weight),
                "leader_selection_score": feat.get("setup_score", 0.0),
                "leader_tier": "SUPERPERFORMANCE_SETUP",
                "leader_state": "HOLD",
                "market_leader_tape_score": feat.get("setup_score", 0.0),
                "future_winner_confirmation_score": feat.get("monster_component", 0.0),
                "smart_money_confirmation_score": feat.get("evidence_component", 0.0),
                "leader_chase_risk_score": feat.get("macro_risk_component", 0.0),
                "rs_spy_3m": feat.get("rs_spy_13w", 0.0),
                "rs_qqq_3m": feat.get("rs_qqq_13w", 0.0),
                "selection_reason": reason,
                "portfolio_kind": portfolio_kind,
                "variant_id": f"superperformance_{portfolio_kind}",
                "target_n": int(PORTFOLIO_CONFIGS[portfolio_kind]["max_positions"]),
                "target_stock_names": int(PORTFOLIO_CONFIGS[portfolio_kind]["max_positions"]),
                "weighting_mode": "superperformance_setup_score",
                "active_rebalance_interval_months": 0,
            }
        )
    if sum(weights.values()) < 0.999:
        rows.append(
            {
                "rebalance_date": signal_date.date().isoformat(),
                "ticker": CASH_TICKER,
                "weight": max(0.0, 1.0 - sum(weights.values())),
                "target_weight": max(0.0, 1.0 - sum(weights.values())),
                "selection_reason": "residual_cash:" + reason,
                "portfolio_kind": portfolio_kind,
                "variant_id": f"superperformance_{portfolio_kind}",
            }
        )
    return rows


def build_trade_target_book(
    *,
    candidate: pd.DataFrame,
    prices: dict[str, pd.DataFrame],
    portfolio_kind: str,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    cfg = PORTFOLIO_CONFIGS[portfolio_kind]
    max_positions = int(cfg["max_positions"])
    min_score = float(cfg["min_setup_score"])
    min_add_gain = float(cfg["min_add_gain"])
    min_hold_weeks = int(cfg["min_hold_weeks"])
    max_adds_per_week = int(cfg["max_adds_per_week"])
    holdings: dict[str, PositionState] = {}
    target_book_rows: list[dict[str, Any]] = []
    signal_rows: list[dict[str, Any]] = []
    event_rows: list[dict[str, Any]] = []
    state_rows: list[dict[str, Any]] = []
    last_weights: dict[str, float] = {}

    for start, end, month in active_candidate_windows(candidate):
        for signal_date in weekly_dates(start, end):
            scored = score_month_candidates(month, prices, signal_date)
            if scored.empty:
                continue
            signal_rows.extend(scored.assign(portfolio_kind=portfolio_kind).to_dict("records"))
            setup_lookup = {str(row["ticker"]).upper(): row for row in scored.to_dict("records")}

            changed = False
            for ticker in list(holdings):
                pos = holdings[ticker]
                feat = setup_lookup.get(ticker)
                if feat is None:
                    feat = setup_features(
                        row=pd.Series({"ticker": ticker}),
                        price=prices.get(ticker, pd.DataFrame()),
                        spy=prices.get("SPY", pd.DataFrame()),
                        qqq=prices.get("QQQ", pd.DataFrame()),
                        signal_date=signal_date,
                    )
                    setup_lookup[ticker] = feat
                reason = exit_reason_for_position(pos, feat, signal_date)
                pos.holding_weeks += 1
                if reason and (pos.holding_weeks >= min_hold_weeks or reason in {"stop_loss", "stage4_break_ma200", "failed_breakout"}):
                    event_rows.append(
                        {
                            "portfolio_kind": portfolio_kind,
                            "date": signal_date.date().isoformat(),
                            "ticker": ticker,
                            "event": "FULL_EXIT",
                            "reason": reason,
                            "prior_weight": pos.weight,
                            "setup_score": feat.get("setup_score", pos.setup_score),
                            "evidence_component": feat.get("evidence_component"),
                            "monster_component": feat.get("monster_component"),
                            "macro_risk_component": feat.get("macro_risk_component"),
                        }
                    )
                    del holdings[ticker]
                    changed = True

            eligible = scored[(scored["eligible"].astype(bool)) & (pd.to_numeric(scored["setup_score"], errors="coerce") >= min_score)].copy()
            held = set(holdings)
            add_count = 0
            for _, row in eligible.iterrows():
                ticker = str(row.get("ticker") or "").upper()
                if ticker in held:
                    pos = holdings[ticker]
                    close = safe_float(row.get("close"), pos.entry_price)
                    if close >= pos.entry_price * (1.0 + min_add_gain) and pos.weight < float(cfg["single_cap"]) - 1e-6 and add_count < max_adds_per_week:
                        event_rows.append(
                            {
                                "portfolio_kind": portfolio_kind,
                                "date": signal_date.date().isoformat(),
                                "ticker": ticker,
                                "event": "PYRAMID_ADD",
                                "reason": "confirmed_gain_and_setup_intact",
                                "prior_weight": pos.weight,
                                "setup_score": row.get("setup_score"),
                                "evidence_component": row.get("evidence_component"),
                                "monster_component": row.get("monster_component"),
                                "macro_risk_component": row.get("macro_risk_component"),
                            }
                        )
                        add_count += 1
                        changed = True
                    continue
                if len(holdings) >= max_positions:
                    break
                holdings[ticker] = PositionState(
                    ticker=ticker,
                    weight=float(cfg["entry_weight"]),
                    entry_date=signal_date,
                    entry_price=safe_float(row.get("close"), 0.0),
                    stop_price=safe_float(row.get("stop_price"), 0.0),
                    pivot_price=safe_float(row.get("pivot_price"), safe_float(row.get("close"), 0.0)),
                    setup_score=safe_float(row.get("setup_score"), 0.0),
                )
                event_rows.append(
                    {
                        "portfolio_kind": portfolio_kind,
                        "date": signal_date.date().isoformat(),
                        "ticker": ticker,
                        "event": "ADD",
                        "reason": "trend_template_rs_breakout",
                        "prior_weight": 0.0,
                        "setup_score": row.get("setup_score"),
                        "evidence_component": row.get("evidence_component"),
                        "monster_component": row.get("monster_component"),
                        "macro_risk_component": row.get("macro_risk_component"),
                    }
                )
                changed = True

            if changed or (not last_weights and holdings):
                weights = allocate_weights(holdings, setup_lookup, portfolio_kind)
                for ticker, weight in weights.items():
                    if ticker in holdings:
                        holdings[ticker].weight = weight
                reason = "trade_event" if changed else "initial_target"
                target_book_rows.extend(
                    target_rows(signal_date=signal_date, weights=weights, setup_lookup=setup_lookup, portfolio_kind=portfolio_kind, reason=reason)
                )
                last_weights = dict(weights)
            else:
                weights = {ticker: float(last_weights.get(ticker, pos.weight)) for ticker, pos in holdings.items()}
                for ticker, weight in weights.items():
                    if ticker in holdings:
                        holdings[ticker].weight = weight
            for ticker, pos in holdings.items():
                feat = setup_lookup.get(ticker, {})
                state_rows.append(
                    {
                        "portfolio_kind": portfolio_kind,
                        "date": signal_date.date().isoformat(),
                        "ticker": ticker,
                        "weight": pos.weight,
                        "entry_date": pos.entry_date.date().isoformat(),
                        "entry_price": pos.entry_price,
                        "stop_price": pos.stop_price,
                        "setup_score": feat.get("setup_score", pos.setup_score),
                        "evidence_component": feat.get("evidence_component"),
                        "monster_component": feat.get("monster_component"),
                        "macro_risk_component": feat.get("macro_risk_component"),
                        "trend_template_pass": feat.get("trend_template_pass"),
                        "rs_qqq_13w": feat.get("rs_qqq_13w"),
                    }
                )

    target_book = pd.DataFrame(target_book_rows)
    signals = pd.DataFrame(signal_rows)
    events = pd.DataFrame(event_rows)
    states = pd.DataFrame(state_rows)
    if not target_book.empty:
        target_book = target_book.sort_values(["rebalance_date", "ticker"]).reset_index(drop=True)
    return target_book, signals, events, states


def render_report(summary: dict[str, Any]) -> str:
    lines = [
        "# Superperformance Trader Replay",
        "",
        "Research-only broker-ledger replay of dated trend-template, VCP/Darvas breakout, stop, and pyramid rules.",
        "",
        "| Portfolio | Status | CAGR | Max DD | Trades | Entry events | Exit events |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in summary.get("portfolios", []):
        metrics = row.get("metrics", {})
        lines.append(
            "| {portfolio} | {status} | {cagr:.2%} | {mdd:.2%} | {trades} | {entries} | {exits} |".format(
                portfolio=row.get("portfolio_kind"),
                status=metrics.get("status", row.get("status", "")),
                cagr=safe_float(metrics.get("cagr"), 0.0),
                mdd=safe_float(metrics.get("max_dd"), 0.0),
                trades=int(metrics.get("trade_count") or metrics.get("trades") or 0),
                entries=int(row.get("entry_event_count") or 0),
                exits=int(row.get("exit_event_count") or 0),
            )
        )
    lines.extend(
        [
            "",
            "Setup score combines price trend, relative strength, VCP/Darvas breakout, volume, leader scores, PIT-safe Form4/13F/ETF evidence, monster/future-winner signals, and macro/chase-risk penalties.",
            "",
            "This output does not alter production targets, current holdings, feature store, or live activation.",
            "",
        ]
    )
    return "\n".join(lines)


def run(args: argparse.Namespace) -> dict[str, Any]:
    latest_run = repo_path(args.latest_run)
    price_cache = repo_path(args.price_cache)
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    candidate_path = repo_path(args.candidate_book) if args.candidate_book else latest_run / "reports" / "candidate_replay_book.csv"
    candidate = read_csv(candidate_path)
    if candidate.empty or "rebalance_date" not in candidate.columns or "ticker" not in candidate.columns:
        payload = {
            "schema_version": "superperformance-trader-replay-v1",
            "generated_at_utc": now_utc(),
            "status": "blocked",
            "reason": "missing_candidate_replay_book",
            "candidate_book": str(candidate_path),
            "metric_mode": "DO_NOT_USE",
            "research_only": True,
            "production_activation_allowed": False,
        }
        write_json(output_dir / "summary.json", payload)
        return payload

    candidate = candidate.copy()
    candidate["rebalance_date"] = pd.to_datetime(candidate["rebalance_date"], errors="coerce").dt.normalize()
    candidate["ticker"] = candidate["ticker"].astype(str).str.upper().str.strip()
    candidate = candidate.dropna(subset=["rebalance_date"])
    candidate = candidate[candidate["ticker"].ne("")]
    tickers = sorted(set(candidate["ticker"].unique()) | set(BENCHMARKS))
    prices = {ticker: load_price_frame(price_cache, ticker) for ticker in tickers}
    readable = {ticker: not px.empty for ticker, px in prices.items()}
    missing = sorted([ticker for ticker, ok in readable.items() if not ok])
    if not readable.get("SPY") or not readable.get("QQQ"):
        payload = {
            "schema_version": "superperformance-trader-replay-v1",
            "generated_at_utc": now_utc(),
            "status": "blocked",
            "reason": "BENCHMARK_PRICE_MISSING",
            "missing_price_tickers": missing[:50],
            "candidate_book": str(candidate_path),
            "price_cache": str(price_cache),
            "metric_mode": "DO_NOT_USE",
            "research_only": True,
            "production_activation_allowed": False,
        }
        write_json(output_dir / "summary.json", payload)
        return payload

    portfolios: list[dict[str, Any]] = []
    all_signals: list[pd.DataFrame] = []
    all_events: list[pd.DataFrame] = []
    all_states: list[pd.DataFrame] = []
    for portfolio_kind in ("main", "concentrated"):
        target_book, signals, events, states = build_trade_target_book(candidate=candidate, prices=prices, portfolio_kind=portfolio_kind)
        target_path = output_dir / f"{portfolio_kind}_target_book.csv"
        broker_dir = output_dir / "broker_replay" / portfolio_kind
        if target_book.empty:
            pd.DataFrame(columns=["rebalance_date", "ticker", "weight"]).to_csv(target_path, index=False)
            metrics = {"status": "blocked", "metric_mode": "DO_NOT_USE", "reason": "no_trade_target_rows"}
        else:
            target_book.to_csv(target_path, index=False)
            metrics = broker_replay(
                target_book=target_path,
                price_cache=price_cache,
                output_dir=broker_dir,
                portfolio_kind=portfolio_kind,
                fill_mode="next_close",
                cost_bps=float(args.cost_bps),
                integer_shares=True,
                max_fill_lag_days=int(args.max_fill_lag_days),
                concentrated_champion_filters=DISABLE_CONCENTRATED_CHAMPION_FILTERS.copy()
                if portfolio_kind == "concentrated"
                else None,
            )
        entry_count = int((events.get("event", pd.Series(dtype=str)).astype(str).eq("ADD")).sum()) if not events.empty else 0
        exit_count = int((events.get("event", pd.Series(dtype=str)).astype(str).eq("FULL_EXIT")).sum()) if not events.empty else 0
        portfolios.append(
            {
                "portfolio_kind": portfolio_kind,
                "status": "completed" if metrics.get("status") == "completed" else "blocked",
                "target_book": str(target_path),
                "broker_replay_dir": str(broker_dir),
                "target_row_count": int(len(target_book)),
                "signal_row_count": int(len(signals)),
                "event_count": int(len(events)),
                "entry_event_count": entry_count,
                "exit_event_count": exit_count,
                "metrics": metrics,
            }
        )
        if not signals.empty:
            all_signals.append(signals)
        if not events.empty:
            all_events.append(events)
        if not states.empty:
            all_states.append(states)

    pd.concat(all_signals, ignore_index=True).to_csv(output_dir / "setup_signals.csv", index=False) if all_signals else pd.DataFrame().to_csv(output_dir / "setup_signals.csv", index=False)
    events_df = pd.concat(all_events, ignore_index=True) if all_events else pd.DataFrame()
    events_df.to_csv(output_dir / "entry_exit_events.csv", index=False)
    if not events_df.empty:
        events_df[events_df["event"].astype(str).eq("ADD")].to_csv(output_dir / "entry_events.csv", index=False)
        events_df[events_df["event"].astype(str).eq("FULL_EXIT")].to_csv(output_dir / "exit_events.csv", index=False)
    else:
        pd.DataFrame().to_csv(output_dir / "entry_events.csv", index=False)
        pd.DataFrame().to_csv(output_dir / "exit_events.csv", index=False)
    pd.concat(all_states, ignore_index=True).to_csv(output_dir / "position_state_history.csv", index=False) if all_states else pd.DataFrame().to_csv(output_dir / "position_state_history.csv", index=False)

    payload = {
        "schema_version": "superperformance-trader-replay-v1",
        "generated_at_utc": now_utc(),
        "status": "completed" if all(row.get("status") == "completed" for row in portfolios) else "partial",
        "candidate_book": str(candidate_path),
        "price_cache": str(price_cache),
        "missing_price_tickers": missing[:100],
        "research_only": True,
        "production_activation_allowed": False,
        "valid_for_production": False,
        "rule_family": "trend_template_vcp_darvas_pyramid_stops",
        "portfolios": portfolios,
        "outputs": {
            "setup_signals": str(output_dir / "setup_signals.csv"),
            "entry_events": str(output_dir / "entry_events.csv"),
            "exit_events": str(output_dir / "exit_events.csv"),
            "position_state_history": str(output_dir / "position_state_history.csv"),
            "main_target_book": str(output_dir / "main_target_book.csv"),
            "concentrated_target_book": str(output_dir / "concentrated_target_book.csv"),
        },
    }
    write_json(output_dir / "summary.json", payload)
    (output_dir / "superperformance_report.md").write_text(render_report(payload), encoding="utf-8")
    print(json.dumps(payload, indent=2, default=json_default))
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default="outputs")
    parser.add_argument("--price-cache", default="cache_prices")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--candidate-book", default="")
    parser.add_argument("--cost-bps", type=float, default=25.0)
    parser.add_argument("--max-fill-lag-days", type=int, default=7)
    return parser.parse_args()


def main() -> int:
    payload = run(parse_args())
    return 0 if payload.get("status") in {"completed", "partial"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
