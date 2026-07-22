"""Shared PIT-safe crisis state engine for live monitoring and replay.

The live daily monitor uses the latest observable row only. Historical replay
uses the same long-crisis gate and hysteresis on each as-of date, then feeds the
result into research-only target-book mutation.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from r1000_long_crisis_liquidity import cash_raise_decision
from tools.run287_crisis_policy import (
    CANONICAL_STATES,
    FUTURE_LABEL_COLUMNS,
    STATE_RANK,
    adapt_crisis_state,
    availability_records,
    component_availability,
    strip_future_labels,
    stronger_state as canonical_stronger_state,
    transition_state,
)

try:  # Imported lazily enough to keep the engine usable from tests.
    from tools.run_weekly_evaluation import load_price_series, px_cache_name
except Exception:  # pragma: no cover - fallback for direct module reuse.
    load_price_series = None  # type: ignore[assignment]

    def px_cache_name(ticker: str) -> str:  # type: ignore[no-redef]
        return f"{ticker.upper()}.parquet"


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def read_table(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        if path.suffix.lower() == ".parquet":
            return pd.read_parquet(path)
        return pd.read_csv(path, low_memory=False)
    except Exception:
        return pd.DataFrame()


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
        return out if pd.notna(out) else default
    except Exception:
        return default


def observable_feature_frame(features_path: Path) -> pd.DataFrame:
    """Load crisis features and remove future labels before any decision."""
    features = read_table(features_path)
    if features.empty:
        return pd.DataFrame()
    d = features.copy()
    date_col = None
    for candidate in ("date", "Date", "as_of_date"):
        if candidate in d.columns:
            date_col = candidate
            break
    if date_col is not None:
        idx = pd.to_datetime(d.pop(date_col), errors="coerce")
    else:
        idx = pd.to_datetime(d.index, errors="coerce")
    d.index = idx
    d = d[~d.index.isna()].sort_index()
    if d.empty:
        return pd.DataFrame()
    out = strip_future_labels(d)
    out.index = pd.DatetimeIndex(out.index).tz_localize(None).normalize()
    return out[~out.index.duplicated(keep="last")].sort_index()


def latest_observable_long_crisis_row(features_path: Path) -> tuple[pd.Timestamp | None, pd.Series]:
    d = observable_feature_frame(features_path)
    if d.empty:
        return None, pd.Series(dtype=float)
    row = d.iloc[-1].copy()
    return pd.Timestamp(d.index[-1]).normalize(), row


def load_long_crisis_thresholds(path: Path) -> dict[str, Any]:
    payload = read_json(path)
    governor = payload.get("governor_thresholds") if isinstance(payload.get("governor_thresholds"), dict) else {}
    cash_gate = payload.get("cash_hard_gate") if isinstance(payload.get("cash_hard_gate"), dict) else {}
    return {
        "low": safe_float(governor.get("low"), 0.35),
        "mid": safe_float(governor.get("mid"), 0.55),
        "high": safe_float(governor.get("high"), 0.75),
        "liquidity_gate": safe_float(cash_gate.get("liquidity_gate"), 0.35),
        "trend_gate": safe_float(cash_gate.get("trend_gate"), 0.35),
        "credit_gate": safe_float(cash_gate.get("credit_gate"), 0.55),
        "source": str(path) if path.exists() else "default_thresholds",
    }


def infer_long_crisis_state_from_row(
    row: pd.Series,
    thresholds: dict[str, Any],
    *,
    asof_date: pd.Timestamp | None = None,
    features_path: Path | None = None,
    thresholds_path: Path | None = None,
    allow_crisis_defense: bool = False,
) -> tuple[str, list[str], dict[str, Any]]:
    if row.empty:
        return "DEGRADED_DATA", [], {
            "available": False,
            "features": str(features_path or ""),
            "thresholds": str(thresholds_path or ""),
            "reason": "missing_long_crisis_features",
        }

    crisis_score = safe_float(row.get("crisis_score"), 0.0)
    decision = cash_raise_decision(
        row,
        crisis_score,
        mid_threshold=float(thresholds["mid"]),
        liquidity_gate=float(thresholds["liquidity_gate"]),
        trend_gate=float(thresholds["trend_gate"]),
        credit_gate=float(thresholds["credit_gate"]),
    )
    low = float(thresholds["low"])
    mid = float(thresholds["mid"])
    high = float(thresholds["high"])
    if (
        allow_crisis_defense
        and crisis_score >= high
        and decision.allowed
        and decision.reason == "systemic_confirmation_pass"
    ):
        state = "CRISIS"
    elif crisis_score >= mid and decision.allowed and decision.reason == "systemic_confirmation_pass":
        state = "DEFENSE"
    elif crisis_score >= low:
        state = "WATCH"
    else:
        state = "GREEN"

    latest_date = pd.Timestamp(asof_date).normalize() if asof_date is not None else None
    availability = component_availability(
        row.to_dict(),
        decision_time=latest_date,
        available_from=latest_date,
    )
    canonical_input_fields = sorted(
        {
            field
            for item in availability
            for field in (
                item.source_field,
                "qqq_ma200" if item.component == "qqq_trend" else "",
            )
            if field and field in row.index
        }
    )
    meta = {
        "available": True,
        "features": str(features_path or ""),
        "thresholds": str(thresholds_path or ""),
        "threshold_source": thresholds["source"],
        "latest_date": latest_date.date().isoformat() if latest_date is not None else "",
        "crisis_score": crisis_score,
        "low_threshold": low,
        "mid_threshold": mid,
        "high_threshold": high,
        "liquidity_confirmation_score": safe_float(row.get("liquidity_confirmation_score"), 0.0),
        "market_trend_damage_score": safe_float(row.get("market_trend_damage_score"), 0.0),
        "credit_stress_score": safe_float(row.get("credit_stress_score"), 0.0),
        "cash_gate_allowed": bool(decision.allowed),
        "cash_gate_reason": decision.reason,
        "observable_field_count": int(len(row.index)),
        "future_labels_excluded": True,
        "component_availability": availability_records(availability),
        "canonical_state_inputs": {
            field: safe_float(row.get(field), 0.0) for field in canonical_input_fields
        },
        "missing_components": [
            item.component for item in availability if not item.available or not item.fresh
        ],
        "missing_critical_components": [
            item.component
            for item in availability
            if item.critical and (not item.available or not item.fresh)
        ],
        "state": state,
    }
    reasons = [
        "long-crisis learned "
        f"state={state} score={crisis_score:.3f} date={meta['latest_date']} cash_gate={decision.reason}"
    ]
    return state, reasons, meta


def infer_latest_long_crisis_state(features_path: Path, thresholds_path: Path) -> tuple[str, list[str], dict[str, Any]]:
    latest_date, row = latest_observable_long_crisis_row(features_path)
    if latest_date is None or row.empty:
        return "DEGRADED_DATA", [], {
            "available": False,
            "features": str(features_path),
            "thresholds": str(thresholds_path),
            "reason": "missing_long_crisis_features",
        }
    return infer_long_crisis_state_from_row(
        row,
        load_long_crisis_thresholds(thresholds_path),
        asof_date=latest_date,
        features_path=features_path,
        thresholds_path=thresholds_path,
        allow_crisis_defense=False,
    )


def apply_hysteresis(
    raw_state: str,
    history: dict[str, Any],
    *,
    values: dict[str, Any] | pd.Series | None = None,
    availability: list[Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    prev = adapt_crisis_state(history.get("state") or "GREEN")
    streak_state = str(history.get("raw_state") or "")
    streak = int(safe_float(history.get("raw_state_streak"), 0))
    canonical_raw = adapt_crisis_state(raw_state)
    canonical_streak_state = adapt_crisis_state(streak_state) if streak_state else ""
    streak = streak + 1 if canonical_raw == canonical_streak_state else 1
    observed = dict(values) if values is not None else {}
    component_rows = availability or component_availability(observed)
    decision = transition_state(
        raw_state=canonical_raw,
        prior_state=prev,
        raw_state_streak=streak,
        values=observed,
        availability=component_rows,
    )
    state = decision.state

    next_history = {
        "state": state,
        "raw_state": canonical_raw,
        "raw_state_streak": streak,
        "reentry_score": decision.reentry_score,
        "reentry_multiplier": decision.reentry_multiplier,
        "transition_reason": decision.transition_reason,
        "missing_components": list(decision.missing_components),
        "missing_critical_components": list(decision.missing_critical_components),
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    return state, next_history


def price_frame(cache: Path, ticker: str) -> pd.DataFrame:
    if load_price_series is not None:
        px = load_price_series(cache, ticker)
    else:
        path = cache / px_cache_name(ticker)
        px = read_table(path)
        if "date" in px.columns:
            px = px.set_index("date")
    if px.empty:
        return pd.DataFrame()
    d = px.copy()
    d.index = pd.to_datetime(d.index, errors="coerce")
    d = d[~d.index.isna()].sort_index()
    d.index = pd.DatetimeIndex(d.index).tz_localize(None).normalize()
    if "close" not in d.columns:
        for col in ("Adj Close", "Close"):
            if col in d.columns:
                d["close"] = pd.to_numeric(d[col], errors="coerce")
                break
    return d.dropna(subset=["close"]) if "close" in d.columns else pd.DataFrame()


def price_raw_state(price_cache: Path, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    spy = price_frame(price_cache, "SPY")
    if spy.empty:
        dates = pd.bdate_range(start, end)
        return pd.DataFrame(
            {
                "date": dates,
                "price_state": "GREEN",
                "price_crisis_score": 0.0,
                "price_trigger": "missing_spy_price",
            }
        )
    spy = spy[(spy.index >= start.normalize()) & (spy.index <= end.normalize())].copy()
    if spy.empty:
        dates = pd.bdate_range(start, end)
        return pd.DataFrame(
            {
                "date": dates,
                "price_state": "GREEN",
                "price_crisis_score": 0.0,
                "price_trigger": "missing_spy_price_range",
            }
        )
    close = pd.to_numeric(spy["close"], errors="coerce")
    peak = close.cummax()
    drawdown = close / peak - 1.0
    ma20 = close.rolling(20, min_periods=5).mean()
    ma50 = close.rolling(50, min_periods=10).mean()
    ret5 = close.pct_change(5)
    rows: list[dict[str, Any]] = []
    for dt, dd in drawdown.items():
        px = float(close.loc[dt])
        above20 = bool(px >= float(ma20.loc[dt])) if pd.notna(ma20.loc[dt]) else True
        above50 = bool(px >= float(ma50.loc[dt])) if pd.notna(ma50.loc[dt]) else True
        r5 = safe_float(ret5.loc[dt], 0.0)
        if dd <= -0.20 or r5 <= -0.12:
            state = "CRISIS"
            trigger = "shock_crash_or_drawdown_below_20pct"
        elif dd <= -0.12 or (dd <= -0.08 and not above50):
            state = "DEFENSE"
            trigger = "drawdown_or_ma50_damage"
        elif dd <= -0.06 or not above20:
            state = "WATCH"
            trigger = "pullback_or_ma20_damage"
        else:
            state = "GREEN"
            trigger = "risk_on"
        rows.append(
            {
                "date": pd.Timestamp(dt).normalize(),
                "price_state": state,
                "price_crisis_score": max(0.0, min(1.0, -safe_float(dd) * 2.0)),
                "price_trigger": trigger,
                "spy_drawdown": safe_float(dd),
                "spy_ret_5d": r5,
                "spy_above_ma20": above20,
                "spy_above_ma50": above50,
            }
        )
    return pd.DataFrame(rows)


def stronger_state(a: str, b: str) -> str:
    return canonical_stronger_state(a, b)


def build_historical_daily_crisis_state(
    price_cache: Path,
    start: pd.Timestamp,
    end: pd.Timestamp,
    *,
    long_crisis_features: Path | None = None,
    long_crisis_thresholds: Path | None = None,
) -> pd.DataFrame:
    """Build PIT historical crisis/reentry states for target-book replay."""
    start = pd.Timestamp(start).normalize()
    end = pd.Timestamp(end).normalize()
    price = price_raw_state(price_cache, start, end)
    dates = pd.bdate_range(start, end)
    base = pd.DataFrame({"date": dates})
    base["date"] = pd.to_datetime(base["date"]).dt.normalize()
    price["date"] = pd.to_datetime(price["date"]).dt.normalize()
    base = base.merge(price, on="date", how="left")
    for col, value in {"price_state": "GREEN", "price_trigger": "missing_price_state"}.items():
        base[col] = base[col].fillna(value)
    base["price_crisis_score"] = pd.to_numeric(base["price_crisis_score"], errors="coerce").fillna(0.0)

    long_df = observable_feature_frame(long_crisis_features) if long_crisis_features else pd.DataFrame()
    thresholds = load_long_crisis_thresholds(long_crisis_thresholds or Path(""))
    long_records: list[dict[str, Any]] = []
    for dt in base["date"]:
        row = pd.Series(dtype=float)
        long_asof: pd.Timestamp | None = None
        if not long_df.empty:
            eligible = long_df[long_df.index <= pd.Timestamp(dt)]
            if not eligible.empty:
                long_asof = pd.Timestamp(eligible.index[-1]).normalize()
                row = eligible.iloc[-1].copy()
        long_state, _reasons, meta = infer_long_crisis_state_from_row(
            row,
            thresholds,
            asof_date=long_asof,
            features_path=long_crisis_features,
            thresholds_path=long_crisis_thresholds,
            allow_crisis_defense=True,
        )
        long_records.append(
            {
                "date": pd.Timestamp(dt).normalize(),
                "long_crisis_state": long_state,
                "long_crisis_score": safe_float(meta.get("crisis_score"), 0.0),
                "cash_gate_reason": meta.get("cash_gate_reason") or meta.get("reason") or "",
                "cash_gate_allowed": bool(meta.get("cash_gate_allowed", False)),
                "liquidity_confirmation_score": safe_float(meta.get("liquidity_confirmation_score"), 0.0),
                "market_trend_damage_score": safe_float(meta.get("market_trend_damage_score"), 0.0),
                "credit_stress_score": safe_float(meta.get("credit_stress_score"), 0.0),
                "volatility_stress_score": safe_float(row.get("volatility_stress_score"), 0.0),
                "rate_shock_score": safe_float(row.get("rate_shock_score"), 0.0),
                "qqq_close": safe_float(row.get("qqq_close"), float("nan")),
                "qqq_ma200": safe_float(row.get("qqq_ma200"), float("nan")),
                "qqq_below_ma200": safe_float(row.get("qqq_below_ma200"), float("nan")),
                "vix_zscore_252d": safe_float(row.get("vix_zscore_252d"), float("nan")),
                "hy_oas_zscore_252d": safe_float(row.get("hy_oas_zscore_252d"), float("nan")),
                "market_breadth_above_ma200": safe_float(
                    row.get("market_breadth_above_ma200"), float("nan")
                ),
                "market_sector_participation": safe_float(
                    row.get("market_sector_participation"), float("nan")
                ),
                "market_leadership_narrowing": safe_float(
                    row.get("market_leadership_narrowing"), float("nan")
                ),
                "long_crisis_feature_date": meta.get("latest_date") or "",
                "future_labels_excluded": True,
            }
        )
    long_state_df = pd.DataFrame(long_records)
    out = base.merge(long_state_df, on="date", how="left")

    history: dict[str, Any] = {"state": "GREEN", "raw_state": "", "raw_state_streak": 0}
    rows: list[dict[str, Any]] = []
    for rec in out.to_dict("records"):
        price_state = str(rec.get("price_state") or "GREEN")
        long_state = str(rec.get("long_crisis_state") or "GREEN")
        raw_state = stronger_state(price_state, long_state)
        available_from = rec.get("long_crisis_feature_date") or rec.get("date")
        availability = component_availability(
            rec,
            decision_time=rec.get("date"),
            available_from=available_from,
        )
        state, history = apply_hysteresis(
            raw_state,
            history,
            values=rec,
            availability=availability,
        )
        stage = state if state.startswith("REENTRY_STAGE_") else ""
        trigger = (
            str(history.get("transition_reason") or "")
            if stage
            else str(rec.get("price_trigger") or rec.get("cash_gate_reason") or raw_state)
        )
        rows.append(
            {
                **rec,
                "raw_state": raw_state,
                "crisis_state": state,
                "crisis_score": max(safe_float(rec.get("price_crisis_score")), safe_float(rec.get("long_crisis_score"))),
                "reentry_stage": stage,
                "reentry_trigger": trigger,
                "reentry_score": safe_float(history.get("reentry_score"), 0.0),
                "reentry_multiplier": safe_float(history.get("reentry_multiplier"), 1.0),
                "component_availability": json.dumps(
                    availability_records(availability), sort_keys=True
                ),
                "missing_components": "|".join(history.get("missing_components") or []),
                "missing_critical_components": "|".join(
                    history.get("missing_critical_components") or []
                ),
                "state_source": "long_crisis" if STATE_RANK.get(long_state, 0) > STATE_RANK.get(price_state, 0) else "price_or_combined",
            }
        )
    return pd.DataFrame(rows)
