#!/usr/bin/env python3
"""Build a PIT-safe, proposal-only OHLCV location and timing challenger.

The challenger describes where held and proposed securities sit inside fixed
multi-horizon ranges and Fibonacci coordinates.  It also records volume,
realized volatility, SPY/QQQ location, and VIX context.  It never writes target
books, changes selector weights, creates orders, changes cash, or promotes a
policy.  Current observations are labelled for later forward resolution.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.build_run287_holding_risk_watch import (  # noqa: E402
    canonical_hash,
    clean_ticker,
    read_json,
    sha256_file,
    write_json,
)
from tools.run_weekly_evaluation import px_cache_name  # noqa: E402


SCHEMA_VERSION = "run287-ohlcv-location-timing-challenger-v1"
READY_STATUS = "READY_OHLCV_LOCATION_TIMING_FORWARD_REVIEW_ONLY"
READY_INSUFFICIENT_STATUS = (
    "READY_OHLCV_LOCATION_TIMING_FORWARD_REVIEW_ONLY_WITH_DATA_INSUFFICIENT"
)
BLOCKED_STATUS = "BLOCKED_OHLCV_LOCATION_TIMING_CHALLENGER"
DATA_OUTPUT_NAMES = (
    "ohlcv_location_timing.csv",
    "fibonacci_levels.csv",
    "benchmark_location.csv",
    "forward_observations.jsonl",
    "price_source_audit.csv",
    "report.md",
)
PRODUCER_READY_STATUSES = {
    "READY_EXACT_SELECTOR_RISK_PACKET_REVIEW_ONLY",
    "READY_EXISTING_EXACT_SELECTOR_RISK_PACKET_REVIEW_ONLY",
}


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def git_head() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True, timeout=10
        ).strip()
    except Exception:
        return ""


def fingerprint(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.resolve()) if path.exists() else str(path),
        "exists": bool(path.is_file()),
        "bytes": int(path.stat().st_size) if path.is_file() else 0,
        "sha256": sha256_file(path) if path.is_file() else "",
    }


def finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def json_clean(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): json_clean(nested) for key, nested in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_clean(nested) for nested in value]
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return finite(value)
    if pd.isna(value):
        return None
    return value


def resolve_fingerprint(record: Mapping[str, Any], label: str) -> tuple[Path, dict[str, Any]]:
    path = Path(str(record.get("path") or ""))
    audit = fingerprint(path)
    expected = str(record.get("sha256") or "").lower()
    audit.update(
        label=label,
        expected_sha256=expected,
        hash_matches=bool(expected and audit.get("sha256") == expected),
    )
    if audit["exists"] is not True or audit["hash_matches"] is not True:
        raise ValueError(f"fingerprint mismatch:{label}")
    return path, audit


def resolve_manifest_output(
    manifest_path: Path,
    manifest: Mapping[str, Any],
    key: str,
) -> tuple[Path, dict[str, Any]]:
    record = (manifest.get("outputs") or {}).get(key) or {}
    raw_path = str(record.get("path") or "")
    path = Path(raw_path)
    if raw_path and not path.is_absolute():
        path = manifest_path.parent / path
    audit = fingerprint(path)
    expected = str(record.get("sha256") or "").lower()
    audit.update(
        label=key,
        expected_sha256=expected,
        hash_matches=bool(expected and audit.get("sha256") == expected),
    )
    if audit["exists"] is not True or audit["hash_matches"] is not True:
        raise ValueError(f"manifest output mismatch:{key}")
    return path, audit


def clean_raw_price(frame: pd.DataFrame) -> pd.DataFrame:
    work = frame.copy()
    if isinstance(work.columns, pd.MultiIndex):
        work.columns = work.columns.get_level_values(0)
    columns = {str(column).strip().lower(): column for column in work.columns}
    date_column = columns.get("date")
    raw_dates = work.pop(date_column) if date_column is not None else work.index
    dates = pd.to_datetime(raw_dates, errors="coerce", utc=True)
    work.index = pd.DatetimeIndex(dates).tz_convert(None).normalize()
    work = work[work.index.notna()].sort_index().groupby(level=0).last()
    return work


def adjusted_ohlcv(frame: pd.DataFrame, cutoff: pd.Timestamp) -> pd.DataFrame:
    """Return split/dividend-consistent OHLC and provider share volume."""
    raw = clean_raw_price(frame)
    raw = raw.loc[raw.index <= cutoff].copy()
    columns = {str(column).strip().lower(): column for column in raw.columns}
    raw_close_column = columns.get("close")
    adjusted_close_column = columns.get("adj close") or raw_close_column
    required = {"open", "high", "low", "close", "volume"}
    if (
        raw_close_column is None
        or adjusted_close_column is None
        or not required.issubset(columns)
    ):
        return pd.DataFrame()
    raw_close = pd.to_numeric(raw[raw_close_column], errors="coerce")
    close = pd.to_numeric(raw[adjusted_close_column], errors="coerce")
    adjustment = close / raw_close.replace(0.0, np.nan)
    adjustment = adjustment.replace([np.inf, -np.inf], np.nan).fillna(1.0)
    out = pd.DataFrame(index=raw.index)
    for source, target in (
        ("open", "open"),
        ("high", "high"),
        ("low", "low"),
        ("close", "raw_close"),
    ):
        column = columns.get(source)
        if column is not None:
            values = pd.to_numeric(raw[column], errors="coerce")
            out[target] = values if target == "raw_close" else values * adjustment
    out["close"] = close
    volume_column = columns.get("volume")
    out["volume"] = pd.to_numeric(raw[volume_column], errors="coerce")
    out["dollar_volume"] = out["raw_close"] * out["volume"]
    finite_fields = np.isfinite(
        out[["open", "high", "low", "close", "raw_close", "volume"]]
        .to_numpy(dtype=float)
    ).all(axis=1)
    valid = (
        pd.Series(finite_fields, index=out.index)
        & out["close"].gt(0)
        & out["raw_close"].gt(0)
        & out["open"].gt(0)
        & out["high"].gt(0)
        & out["low"].gt(0)
        & out["high"].ge(out[["open", "close"]].max(axis=1))
        & out["low"].le(out[["open", "close", "high"]].min(axis=1))
        & out["volume"].ge(0)
    )
    return out.loc[valid].sort_index()


def merge_frozen_and_provider(
    base_raw: pd.DataFrame,
    provider_raw: pd.DataFrame,
    cutoff: pd.Timestamp,
    *,
    minimum_overlap: int,
    maximum_relative_error: float,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Splice a frozen history to a verified current provider snapshot."""
    raw_base = clean_raw_price(base_raw)
    raw_provider = clean_raw_price(provider_raw)
    base_future = int((raw_base.index > cutoff).sum())
    provider_future = int((raw_provider.index > cutoff).sum())
    base = raw_base.loc[raw_base.index <= cutoff].copy()
    provider = raw_provider.loc[raw_provider.index <= cutoff].copy()
    common = base.index.intersection(provider.index)
    base_columns = {str(column).strip().lower(): column for column in base.columns}
    provider_columns = {
        str(column).strip().lower(): column for column in provider.columns
    }
    base_close = pd.to_numeric(
        base.get(base_columns.get("close")), errors="coerce"
    ).reindex(common)
    provider_close = pd.to_numeric(
        provider.get(provider_columns.get("close")), errors="coerce"
    ).reindex(common)
    relative = (
        (base_close - provider_close).abs()
        / provider_close.abs().replace(0.0, np.nan)
    ).replace([np.inf, -np.inf], np.nan).dropna()
    maximum_error = float(relative.max()) if not relative.empty else math.inf
    audit = {
        "base_future_rows_excluded": base_future,
        "provider_future_rows_excluded": provider_future,
        "provider_overlap_count": int(len(relative)),
        "provider_overlap_max_relative_error": maximum_error,
        "minimum_overlap_required": int(minimum_overlap),
        "maximum_relative_error_allowed": float(maximum_relative_error),
    }
    if len(relative) < minimum_overlap:
        audit["failure"] = f"overlap_underpowered:{len(relative)}<{minimum_overlap}"
        return pd.DataFrame(), audit
    if not math.isfinite(maximum_error) or maximum_error > maximum_relative_error:
        audit["failure"] = (
            f"raw_close_overlap_mismatch:{maximum_error}>{maximum_relative_error}"
        )
        return pd.DataFrame(), audit

    adjustment_rebase_factor = 1.0
    adjusted_relative = pd.Series(dtype=float)
    base_adjusted_column = base_columns.get("adj close")
    provider_adjusted_column = provider_columns.get("adj close")
    if (
        base_adjusted_column is not None
        and provider_adjusted_column is not None
        and len(common)
    ):
        base_adjusted = pd.to_numeric(
            base[base_adjusted_column], errors="coerce"
        ).reindex(common)
        provider_adjusted = pd.to_numeric(
            provider[provider_adjusted_column], errors="coerce"
        ).reindex(common)
        adjusted_relative = (
            (base_adjusted - provider_adjusted).abs()
            / provider_adjusted.abs().replace(0.0, np.nan)
        ).replace([np.inf, -np.inf], np.nan).dropna()
        valid_rebase = (
            provider_adjusted / base_adjusted.replace(0.0, np.nan)
        ).replace([np.inf, -np.inf], np.nan).dropna()
        if valid_rebase.empty:
            audit["failure"] = "adjustment_rebase_unavailable"
            return pd.DataFrame(), audit
        adjustment_rebase_factor = float(valid_rebase.iloc[0])

    earliest_provider = provider.index.min()
    older = base.loc[base.index < earliest_provider].copy()
    if base_adjusted_column is not None:
        older[base_adjusted_column] = (
            pd.to_numeric(older[base_adjusted_column], errors="coerce")
            * adjustment_rebase_factor
        )
    combined = pd.concat([older, provider]).sort_index().groupby(level=0).last()
    adjusted = adjusted_ohlcv(combined, cutoff)
    audit.update(
        provider_adjusted_overlap_max_relative_error=(
            float(adjusted_relative.max())
            if not adjusted_relative.empty
            else 0.0
        ),
        historical_adjustment_rebase_factor=adjustment_rebase_factor,
        row_count=int(len(adjusted)),
        date_min=(
            adjusted.index.min().date().isoformat() if not adjusted.empty else ""
        ),
        date_max=(
            adjusted.index.max().date().isoformat() if not adjusted.empty else ""
        ),
        exact_close=bool(
            not adjusted.empty and pd.Timestamp(adjusted.index[-1]) == cutoff
        ),
    )
    return adjusted, audit


def past_percentile(series: pd.Series, minimum: int = 60) -> tuple[float | None, int]:
    clean = pd.to_numeric(series.iloc[:-1], errors="coerce").dropna()
    current = finite(series.iloc[-1]) if len(series) else None
    if current is None or len(clean) < minimum:
        return None, int(len(clean))
    return float((clean <= current).mean()), int(len(clean))


def fixed_window_features(
    ticker: str,
    px: pd.DataFrame,
    asof: pd.Timestamp,
    contract: Mapping[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    row: dict[str, Any] = {
        "ticker": ticker,
        "price_exact_asof": bool(
            not px.empty and pd.Timestamp(px.index[-1]).normalize() == asof
        ),
        "history_observations": int(len(px)),
        "data_reason": "",
    }
    level_rows: list[dict[str, Any]] = []
    minimum_history = int(contract["price_contract"]["minimum_history_rows"])
    if px.empty or row["price_exact_asof"] is not True:
        row["data_reason"] = "exact_close_missing"
        return row, level_rows
    if len(px) < minimum_history:
        row["data_reason"] = f"history_underpowered:{len(px)}<{minimum_history}"
        return row, level_rows

    close = px["close"]
    high = px["high"]
    low = px["low"]
    volume = px["volume"]
    returns = close.pct_change()
    previous_close = close.shift(1)
    true_range = pd.concat(
        [
            high - low,
            (high - previous_close).abs(),
            (low - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr14 = true_range.rolling(14, min_periods=14).mean()
    current_close = float(close.iloc[-1])
    current_atr = finite(atr14.iloc[-1])
    prior_volume = volume.shift(1).rolling(20, min_periods=20)
    volume_mean20 = prior_volume.mean()
    volume_std20 = prior_volume.std(ddof=0).replace(0.0, np.nan)
    volume_z20 = (volume - volume_mean20) / volume_std20
    close_location = (
        (close - low) / (high - low).replace(0.0, np.nan)
    ).clip(0.0, 1.0)
    gap = px["open"] / previous_close - 1.0
    intraday_return = close / px["open"] - 1.0
    realized20 = returns.rolling(20, min_periods=20).std(ddof=0) * math.sqrt(252)
    realized63 = returns.rolling(63, min_periods=63).std(ddof=0) * math.sqrt(252)
    realized_ratio = realized20 / realized63.replace(0.0, np.nan)
    vol_percentile, vol_history = past_percentile(realized20, minimum=60)

    row.update(
        close=current_close,
        open=finite(px["open"].iloc[-1]),
        high=finite(high.iloc[-1]),
        low=finite(low.iloc[-1]),
        volume=finite(volume.iloc[-1]),
        dollar_volume=finite(px["dollar_volume"].iloc[-1]),
        return_1d=finite(returns.iloc[-1]),
        gap_return=finite(gap.iloc[-1]),
        intraday_return=finite(intraday_return.iloc[-1]),
        close_location_in_bar=finite(close_location.iloc[-1]),
        atr14=finite(atr14.iloc[-1]),
        atr14_pct=(
            None if current_atr is None else current_atr / current_close
        ),
        realized_vol_20d=finite(realized20.iloc[-1]),
        realized_vol_63d=finite(realized63.iloc[-1]),
        realized_vol_ratio_20d_63d=finite(realized_ratio.iloc[-1]),
        realized_vol_20d_past_percentile=vol_percentile,
        realized_vol_percentile_history=vol_history,
        volume_z_20d_past_only=finite(volume_z20.iloc[-1]),
        volume_ratio_20d_past_only=(
            None
            if finite(volume_mean20.iloc[-1]) in (None, 0.0)
            else finite(volume.iloc[-1]) / float(volume_mean20.iloc[-1])
        ),
    )
    for horizon in contract["return_horizons_trading_days"]:
        horizon = int(horizon)
        row[f"return_{horizon}d"] = (
            finite(close.iloc[-1] / close.iloc[-1 - horizon] - 1.0)
            if len(close) > horizon
            else None
        )

    ma20 = close.rolling(20, min_periods=20).mean()
    ma50 = close.rolling(50, min_periods=50).mean()
    ma200 = close.rolling(200, min_periods=200).mean()
    row.update(
        ma20=finite(ma20.iloc[-1]),
        ma50=finite(ma50.iloc[-1]),
        ma200=finite(ma200.iloc[-1]),
        above_ma20=bool(current_close >= ma20.iloc[-1]) if pd.notna(ma20.iloc[-1]) else None,
        above_ma50=bool(current_close >= ma50.iloc[-1]) if pd.notna(ma50.iloc[-1]) else None,
        above_ma200=bool(current_close >= ma200.iloc[-1]) if pd.notna(ma200.iloc[-1]) else None,
        ma20_slope_5d=(
            finite(ma20.iloc[-1] / ma20.iloc[-6] - 1.0)
            if len(ma20.dropna()) >= 6
            else None
        ),
        accumulation_day=bool(
            finite(returns.iloc[-1]) is not None
            and float(returns.iloc[-1]) > 0
            and finite(volume_z20.iloc[-1]) is not None
            and float(volume_z20.iloc[-1]) >= 0
            and finite(close_location.iloc[-1]) is not None
            and float(close_location.iloc[-1]) >= 0.65
        ),
        distribution_day=bool(
            finite(returns.iloc[-1]) is not None
            and float(returns.iloc[-1]) < 0
            and finite(volume_z20.iloc[-1]) is not None
            and float(volume_z20.iloc[-1]) >= 0
            and finite(close_location.iloc[-1]) is not None
            and float(close_location.iloc[-1]) <= 0.35
        ),
    )

    fib_ratios = [float(value) for value in contract["fibonacci"]["ratios"]]
    low_votes = 0
    high_votes = 0
    fib_votes = 0
    breakout_votes = 0
    for lookback in contract["location_lookbacks_trading_days"]:
        lookback = int(lookback)
        if len(px) < lookback:
            continue
        sample = px.iloc[-lookback:]
        range_high = float(sample["high"].max())
        range_low = float(sample["low"].min())
        width = range_high - range_low
        position = (
            (current_close - range_low) / width if width > 0 else None
        )
        low_date = pd.Timestamp(sample["low"].idxmin())
        high_date = pd.Timestamp(sample["high"].idxmax())
        anchors_ambiguous = bool(high_date == low_date)
        direction = (
            "AMBIGUOUS"
            if anchors_ambiguous
            else "UP_SWING"
            if high_date > low_date
            else "DOWN_SWING"
        )
        prior_high = finite(px["high"].iloc[-lookback:-1].max())
        breakout = bool(prior_high is not None and current_close > prior_high)
        distance_low = current_close - range_low
        distance_high = range_high - current_close
        atr_scale = current_atr or 0.0
        near_low_threshold = max(
            float(contract["classification"]["near_range_atr"]) * atr_scale,
            float(contract["classification"]["near_range_pct"]) * current_close,
        )
        near_low = bool(
            position is not None
            and (
                position <= float(contract["classification"]["low_position_max"])
                or distance_low <= near_low_threshold
            )
        )
        near_high = bool(
            position is not None
            and (
                position >= float(contract["classification"]["high_position_min"])
                or distance_high <= near_low_threshold
            )
        )
        nearest_ratio: float | None = None
        nearest_price: float | None = None
        nearest_distance = math.inf
        for ratio in fib_ratios:
            level = (
                None
                if anchors_ambiguous
                else range_high - width * ratio
                if direction == "UP_SWING"
                else range_low + width * ratio
            )
            distance = (
                math.inf if level is None else abs(current_close - level)
            )
            level_rows.append(
                {
                    "schema_version": SCHEMA_VERSION,
                    "as_of_date": asof.date().isoformat(),
                    "ticker": ticker,
                    "lookback_trading_days": lookback,
                    "swing_direction": direction,
                    "anchor_low_date": low_date.date().isoformat(),
                    "anchor_low_price": range_low,
                    "anchor_high_date": high_date.date().isoformat(),
                    "anchor_high_price": range_high,
                    "fibonacci_ratio": ratio,
                    "fibonacci_price": level,
                    "close_distance_pct": (
                        None if level in (None, 0.0) else current_close / level - 1.0
                    ),
                    "selected_after_outcome": False,
                }
            )
            if level is not None and distance < nearest_distance:
                nearest_ratio = ratio
                nearest_price = level
                nearest_distance = distance
        fib_threshold = max(
            float(contract["classification"]["fib_zone_atr"]) * atr_scale,
            float(contract["classification"]["fib_zone_pct"]) * current_close,
        )
        fib_near = bool(
            not anchors_ambiguous and nearest_distance <= fib_threshold
        )
        row.update(
            {
                f"range_{lookback}d_low": range_low,
                f"range_{lookback}d_high": range_high,
                f"range_{lookback}d_position": position,
                f"distance_to_{lookback}d_low_pct": current_close / range_low - 1.0,
                f"distance_to_{lookback}d_high_pct": current_close / range_high - 1.0,
                f"nearest_fib_{lookback}d_ratio": nearest_ratio,
                f"nearest_fib_{lookback}d_price": nearest_price,
                f"nearest_fib_{lookback}d_distance_pct": (
                    current_close / nearest_price - 1.0
                    if nearest_price not in (None, 0.0)
                    else None
                ),
                f"near_range_low_{lookback}d": near_low,
                f"near_range_high_{lookback}d": near_high,
                f"near_fibonacci_{lookback}d": fib_near,
                f"breakout_extension_{lookback}d": breakout,
            }
        )
        low_votes += int(near_low)
        high_votes += int(near_high)
        fib_votes += int(fib_near)
        breakout_votes += int(breakout)

    row.update(
        near_low_consensus_count=low_votes,
        near_high_consensus_count=high_votes,
        near_fibonacci_consensus_count=fib_votes,
        breakout_consensus_count=breakout_votes,
    )
    if breakout_votes >= 2:
        label = "BREAKOUT_EXTENSION"
    elif low_votes >= 2:
        label = "NEAR_RANGE_LOW"
    elif high_votes >= 2:
        label = "NEAR_RANGE_HIGH"
    elif fib_votes >= 2:
        label = "FIBONACCI_ZONE"
    else:
        label = "MID_RANGE"
    row["location_state"] = label
    return row, level_rows


def vix_context(macro: pd.DataFrame, asof: pd.Timestamp) -> dict[str, Any]:
    if macro.empty:
        return {
            "vix_data_ready": False,
            "vix_data_reason": "macro_table_empty",
        }
    work = macro.copy()
    date_column = "macro_date" if "macro_date" in work else "date"
    dates = pd.to_datetime(work.get(date_column), errors="coerce", utc=True)
    work.index = pd.DatetimeIndex(dates).tz_convert(None).normalize()
    future_rows = int((work.index > asof).sum())
    work = work.loc[work.index.notna() & (work.index <= asof)].sort_index()
    value_column = (
        "vix_level"
        if "vix_level" in work
        else "value"
        if "value" in work
        else ""
    )
    if work.empty or not value_column:
        return {
            "vix_data_ready": False,
            "vix_data_reason": "vix_level_missing",
        }
    numeric = pd.to_numeric(work[value_column], errors="coerce")
    latest_value = finite(numeric.iloc[-1]) if len(numeric) else None
    if latest_value is None or latest_value <= 0:
        return {
            "vix_data_ready": False,
            "vix_data_reason": "latest_vix_observation_nonfinite_or_nonpositive",
            "vix_observation_date": work.index[-1].date().isoformat(),
            "vix_future_rows_excluded": future_rows,
        }
    valid = numeric.map(
        lambda value: finite(value) is not None and float(value) > 0
    )
    vix = numeric.loc[valid]
    if vix.empty:
        return {
            "vix_data_ready": False,
            "vix_data_reason": "vix_level_empty",
        }
    trailing = vix.tail(63)
    trailing_std = float(trailing.std(ddof=0)) if len(trailing) >= 20 else 0.0
    z_value = (
        float((trailing.iloc[-1] - trailing.mean()) / trailing_std)
        if trailing_std > 0
        else None
    )
    percentile, history = past_percentile(vix, minimum=60)
    age_days = int((asof - vix.index[-1]).days)
    return {
        "vix_data_ready": True,
        "vix_data_reason": "",
        "vix_observation_date": vix.index[-1].date().isoformat(),
        "vix_future_rows_excluded": future_rows,
        "vix_invalid_observations_excluded": int((~valid).sum()),
        "vix_observation_age_calendar_days": age_days,
        "vix_observation_exact_asof": bool(vix.index[-1] == asof),
        "vix_level": finite(vix.iloc[-1]),
        "vix_change_1d_points": (
            finite(vix.iloc[-1] - vix.iloc[-2]) if len(vix) >= 2 else None
        ),
        "vix_change_5d_points": (
            finite(vix.iloc[-1] - vix.iloc[-6]) if len(vix) >= 6 else None
        ),
        "vix_return_1d": (
            finite(vix.iloc[-1] / vix.iloc[-2] - 1.0)
            if len(vix) >= 2 and vix.iloc[-2] != 0
            else None
        ),
        "vix_z_63d": z_value,
        "vix_past_percentile": percentile,
        "vix_percentile_history": history,
    }


def role_table(
    holding: pd.DataFrame,
    comparison: pd.DataFrame,
) -> pd.DataFrame:
    roles: dict[str, dict[str, Any]] = {}
    for record in holding.to_dict("records"):
        ticker = clean_ticker(record.get("ticker"))
        if not ticker:
            continue
        entry = roles.setdefault(
            ticker,
            {
                "ticker": ticker,
                "is_held": False,
                "is_current_selector": False,
                "is_proposed_entry": False,
                "portfolios": set(),
                "holding_risk_states": set(),
                "marked_weight_max": 0.0,
                "advisory_weight_max": 0.0,
            },
        )
        entry["is_held"] = True
        entry["portfolios"].add(str(record.get("portfolio_kind") or ""))
        entry["holding_risk_states"].add(str(record.get("risk_state") or ""))

    if not comparison.empty:
        work = comparison.copy()
        work["ticker"] = work["ticker"].map(clean_ticker)
        for column in ("marked_weight", "advisory_weight"):
            raw = (
                work[column]
                if column in work
                else pd.Series(0.0, index=work.index)
            )
            work[column] = pd.to_numeric(raw, errors="coerce").fillna(0.0)
        for ticker, group in work.groupby("ticker", sort=True):
            if not ticker:
                continue
            marked = float(group["marked_weight"].max())
            advisory = float(group["advisory_weight"].max())
            if marked <= 0 and advisory <= 0:
                continue
            entry = roles.setdefault(
                ticker,
                {
                    "ticker": ticker,
                    "is_held": False,
                    "is_current_selector": False,
                    "is_proposed_entry": False,
                    "portfolios": set(),
                    "holding_risk_states": set(),
                    "marked_weight_max": 0.0,
                    "advisory_weight_max": 0.0,
                },
            )
            entry["is_current_selector"] = bool(
                entry["is_current_selector"] or marked > 0
            )
            entry["is_proposed_entry"] = bool(
                entry["is_proposed_entry"] or (advisory > 0 and marked <= 0)
            )
            entry["marked_weight_max"] = max(entry["marked_weight_max"], marked)
            entry["advisory_weight_max"] = max(
                entry["advisory_weight_max"], advisory
            )
            if "portfolio_kind" in group:
                entry["portfolios"].update(
                    str(value) for value in group["portfolio_kind"].dropna()
                )

    rows: list[dict[str, Any]] = []
    for entry in roles.values():
        rows.append(
            {
                **entry,
                "portfolios": "|".join(sorted(value for value in entry["portfolios"] if value)),
                "holding_risk_states": "|".join(
                    sorted(
                        value
                        for value in entry["holding_risk_states"]
                        if value
                    )
                ),
            }
        )
    return pd.DataFrame(rows).sort_values("ticker").reset_index(drop=True)


def latest_available_from(*values: Any) -> str:
    parsed = pd.to_datetime(
        pd.Series(
            [value for value in values if str(value or "").strip()],
            dtype="object",
        ),
        errors="coerce",
        utc=True,
    ).dropna()
    if parsed.empty:
        return ""
    return pd.Timestamp(parsed.max()).isoformat()


def forward_observation_window(
    valuation: pd.Timestamp,
    available_from: str,
    accepted_at_utc: str,
    contract: Mapping[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    forward = contract["forward_learning"]
    launch = pd.to_datetime(
        forward.get("accepted_forward_launch_anchor_utc"),
        errors="coerce",
        utc=True,
    )
    available = pd.to_datetime(available_from, errors="coerce", utc=True)
    accepted = pd.to_datetime(accepted_at_utc, errors="coerce", utc=True)
    failures: list[str] = []
    if pd.isna(launch):
        failures.append("forward_launch_anchor_invalid")
    if pd.isna(available):
        failures.append("available_from_invalid")
    if pd.isna(accepted):
        failures.append("observation_accepted_at_invalid")
    if failures:
        return {}, failures

    valuation_date = valuation.date()
    nyse_close_local = datetime(
        valuation_date.year,
        valuation_date.month,
        valuation_date.day,
        16,
        0,
        tzinfo=ZoneInfo("America/New_York"),
    )
    close = pd.Timestamp(nyse_close_local).tz_convert("UTC")
    launch = pd.Timestamp(launch)
    available = pd.Timestamp(available)
    accepted = pd.Timestamp(accepted)
    acceptance_delay_hours = (accepted - close).total_seconds() / 3600.0
    input_delay_hours = (available - close).total_seconds() / 3600.0
    acceptance_lag_hours = (accepted - available).total_seconds() / 3600.0

    if close < launch:
        failures.append("valuation_before_forward_launch_anchor")
    if accepted < launch:
        failures.append("acceptance_before_forward_launch_anchor")
    if acceptance_delay_hours < 0:
        failures.append("observation_accepted_before_nyse_close")
    if acceptance_delay_hours > float(
        forward["maximum_acceptance_delay_hours_after_nyse_close"]
    ):
        failures.append("observation_acceptance_delayed")
    if input_delay_hours < 0:
        failures.append("latest_input_available_before_nyse_close")
    if input_delay_hours > float(
        forward["maximum_latest_input_delay_hours_after_nyse_close"]
    ):
        failures.append("latest_input_availability_delayed")
    if acceptance_lag_hours < 0:
        failures.append("available_from_after_observation_acceptance")
    if acceptance_lag_hours > float(
        forward["maximum_acceptance_lag_hours_after_latest_input"]
    ):
        failures.append("observation_acceptance_stale_after_latest_input")
    return {
        "accepted_forward_launch_anchor_utc": launch.isoformat(),
        "nyse_close_utc": close.isoformat(),
        "latest_input_available_from_utc": available.isoformat(),
        "observation_accepted_at_utc": accepted.isoformat(),
        "acceptance_delay_hours_after_nyse_close": acceptance_delay_hours,
        "latest_input_delay_hours_after_nyse_close": input_delay_hours,
        "acceptance_lag_hours_after_latest_input": acceptance_lag_hours,
        "historical_replay_materialized": False,
    }, failures


def market_context(
    benchmark_features: Mapping[str, Mapping[str, Any]],
    vix: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    spy = benchmark_features.get("SPY") or {}
    qqq = benchmark_features.get("QQQ") or {}
    benchmark_context_complete = bool(
        spy.get("price_exact_asof") is True
        and qqq.get("price_exact_asof") is True
        and not str(spy.get("data_reason") or "")
        and not str(qqq.get("data_reason") or "")
    )
    both_below_50 = bool(
        spy.get("above_ma50") is False and qqq.get("above_ma50") is False
    )
    both_negative_21d = bool(
        finite(spy.get("return_21d")) is not None
        and finite(qqq.get("return_21d")) is not None
        and float(spy["return_21d"])
        <= float(contract["classification"]["market_damage_return_21d"])
        and float(qqq["return_21d"])
        <= float(contract["classification"]["market_damage_return_21d"])
    )
    vix_stress = bool(
        vix.get("vix_data_ready") is True
        and (
            (
                finite(vix.get("vix_z_63d")) is not None
                and float(vix["vix_z_63d"])
                >= float(contract["classification"]["vix_stress_z"])
            )
            or (
                finite(vix.get("vix_level")) is not None
                and float(vix["vix_level"])
                >= float(contract["classification"]["vix_stress_level"])
            )
        )
    )
    index_damage = bool(both_below_50 and both_negative_21d)
    risk_off = bool(index_damage or (both_below_50 and vix_stress))
    return {
        "spy_qqq_both_below_ma50": both_below_50,
        "spy_qqq_both_negative_21d": both_negative_21d,
        "index_damage_confirmed": index_damage,
        "vix_stress": vix_stress,
        "market_risk_off_confirmed": risk_off,
        "benchmark_context_complete": benchmark_context_complete,
        "vix_only_signal_allowed": False,
    }


def classify_shadow_action(
    row: Mapping[str, Any],
    market: Mapping[str, Any],
) -> tuple[str, str]:
    if row.get("data_reason"):
        return "DATA_INSUFFICIENT_REVIEW", str(row["data_reason"])
    holding_risk = str(row.get("holding_risk_states") or "")
    ret21 = finite(row.get("return_21d"))
    stock_breakdown = bool(
        row.get("above_ma20") is False
        and row.get("above_ma50") is False
        and ret21 is not None
        and ret21 < 0
        and (
            row.get("distribution_day") is True
            or int(row.get("near_low_consensus_count") or 0) >= 2
        )
    )
    support_reversal = bool(
        (
            int(row.get("near_low_consensus_count") or 0) >= 2
            or int(row.get("near_fibonacci_consensus_count") or 0) >= 2
        )
        and row.get("accumulation_day") is True
        and row.get("above_ma50") is True
    )
    high_reversal = bool(
        int(row.get("near_high_consensus_count") or 0) >= 2
        and row.get("distribution_day") is True
        and row.get("above_ma20") is False
    )
    market_risk_off = bool(market.get("market_risk_off_confirmed"))
    reasons = [
        name
        for name, active in (
            ("stock_breakdown", stock_breakdown),
            ("support_reversal", support_reversal),
            ("high_reversal", high_reversal),
            ("market_risk_off_confirmed", market_risk_off),
            ("holding_risk_alert", "ALERT" in holding_risk),
        )
        if active
    ]
    if row.get("is_held"):
        if stock_breakdown and market_risk_off and "ALERT" in holding_risk:
            return "EXIT_REVIEW", "|".join(reasons)
        if high_reversal or (stock_breakdown and market_risk_off):
            return "TRIM_REVIEW", "|".join(reasons)
        return "HOLD_REVIEW", "|".join(reasons or ["no_confirmed_exit"])
    if row.get("is_proposed_entry"):
        if market.get("benchmark_context_complete") is not True:
            return "DATA_INSUFFICIENT_REVIEW", "benchmark_context_incomplete"
        if stock_breakdown and market_risk_off:
            return "BLOCK_ENTRY_REVIEW", "|".join(reasons)
        if support_reversal and not market_risk_off:
            return "ENTRY_CONFIRM_REVIEW", "|".join(reasons)
        if int(row.get("near_high_consensus_count") or 0) >= 2:
            return "WAIT_PULLBACK_REVIEW", "near_high_without_entry_confirmation"
        return "MONITOR_ENTRY_REVIEW", "|".join(reasons or ["no_confirmed_entry"])
    return "MONITOR_REVIEW", "|".join(reasons or ["observation_only"])


def blocked(
    output_dir: Path,
    failures: list[str],
    audits: Mapping[str, Any],
    started: float,
) -> dict[str, Any]:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "status": BLOCKED_STATUS,
        "contract_failures": failures,
        "research_only": True,
        "forward_observation_only": True,
        "advisory_only": True,
        "portfolio_transition_allowed": False,
        "orders_generated": False,
        "target_books_mutated": False,
        "selector_weights_changed": False,
        "cash_policy_changed": False,
        "champion_changed": False,
        "backtest_executed": False,
        "fullrun_executed": False,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
        "source_inputs": dict(audits),
        "performance": {"elapsed_seconds": time.perf_counter() - started},
        "code": {"git_head": git_head(), "builder": fingerprint(Path(__file__))},
    }
    write_json(output_dir / "summary.json", payload)
    return payload


def clear_run_local_outputs(output_dir: Path, *, include_summary: bool) -> None:
    names = [*DATA_OUTPUT_NAMES]
    if include_summary:
        names.append("summary.json")
    for name in names:
        (output_dir / name).unlink(missing_ok=True)
    for temporary in output_dir.glob(".*.tmp"):
        if temporary.is_file():
            temporary.unlink(missing_ok=True)


def changed_input_failures(
    audits: Mapping[str, Any],
    price_records: pd.DataFrame,
    source_hashes: Mapping[str, str],
) -> list[str]:
    failures: list[str] = []
    for ticker, prior_hash in source_hashes.items():
        record = price_records.loc[ticker]
        if sha256_file(Path(str(record.get("path") or ""))) != prior_hash:
            failures.append(f"price_source_changed:{ticker}")
    for label, audit in audits.items():
        if isinstance(audit, Mapping) and audit.get("exists") is True:
            path = Path(str(audit.get("path") or ""))
            if sha256_file(path) != str(audit.get("sha256") or ""):
                failures.append(f"source_changed:{label}")
    return failures


def render_report(summary: Mapping[str, Any], rows: pd.DataFrame) -> str:
    lines = [
        "# Run287 OHLCV location timing challenger",
        "",
        f"- status: `{summary.get('status')}`",
        f"- as-of close: `{summary.get('as_of_date')}`",
        f"- securities / insufficient: `{summary.get('security_count')}` / `{summary.get('data_insufficient_count')}`",
        f"- market risk-off confirmed: `{summary.get('market_context', {}).get('market_risk_off_confirmed')}`",
        "- forward research and human review only; no target, cash, order, champion, production, or live mutation",
        "- Fibonacci levels are fixed descriptive coordinates, not standalone alpha evidence",
        "- VIX alone cannot produce a stock action",
        "",
        "| Ticker | Role | Location | 1D | 21D | Vol z | RV pct | Shadow action | Reasons |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for row in rows.to_dict("records"):
        def pct(value: Any) -> str:
            number = finite(value)
            return "" if number is None else f"{number:.2%}"

        def number(value: Any) -> str:
            parsed = finite(value)
            return "" if parsed is None else f"{parsed:.2f}"

        role = (
            "held"
            if row.get("is_held")
            else "proposed"
            if row.get("is_proposed_entry")
            else "current-selector"
            if row.get("is_current_selector")
            else "observe"
        )
        lines.append(
            f"| {row.get('ticker', '')} | {role} | `{row.get('location_state', '')}` | "
            f"{pct(row.get('return_1d'))} | {pct(row.get('return_21d'))} | "
            f"{number(row.get('volume_z_20d_past_only'))} | "
            f"{pct(row.get('realized_vol_20d_past_percentile'))} | "
            f"`{row.get('shadow_action', '')}` | {row.get('shadow_reason_codes', '')} |"
        )
    lines.extend(
        [
            "",
            "Actions are unresolved challenger labels. They cannot be consumed by the selector or broker ledger until the forward and promotion contracts are satisfied.",
            "",
        ]
    )
    return "\n".join(lines)


def build(args: argparse.Namespace) -> dict[str, Any]:
    started = time.perf_counter()
    accepted_at_utc = str(
        getattr(args, "observation_accepted_at_utc", "")
        or datetime.now(timezone.utc).isoformat()
    )
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    clear_run_local_outputs(output_dir, include_summary=True)
    producer_path = repo_path(args.producer_status)
    holding_path = repo_path(args.holding_watch)
    contract_path = repo_path(args.contract)
    audits: dict[str, Any] = {
        "producer_status": fingerprint(producer_path),
        "holding_watch": fingerprint(holding_path),
        "contract": fingerprint(contract_path),
    }
    failures: list[str] = []
    if not all(path.is_file() for path in (producer_path, holding_path, contract_path)):
        failures.append("required_input_missing")
        return blocked(output_dir, failures, audits, started)

    producer = read_json(producer_path)
    contract = read_json(contract_path)
    if producer.get("status") not in PRODUCER_READY_STATUSES:
        failures.append(f"producer_status:{producer.get('status')}")
    if contract.get("schema_version") != SCHEMA_VERSION:
        failures.append("contract_schema")
    if str(producer.get("valuation_price_cutoff_date") or "") != args.valuation_date:
        failures.append("producer_valuation_date")
    source_inputs = producer.get("source_inputs") or {}
    expected_holding = source_inputs.get("holding_watch_csv") or {}
    if expected_holding.get("sha256") != audits["holding_watch"].get("sha256"):
        failures.append("holding_watch_not_producer_input")
    if failures:
        return blocked(output_dir, failures, audits, started)

    try:
        price_map_manifest_path, audits["price_map_manifest"] = resolve_fingerprint(
            source_inputs.get("portable:price_map_manifest") or {},
            "price_map_manifest",
        )
        price_manifest_path, audits["price_manifest"] = resolve_fingerprint(
            source_inputs.get("portable:price_manifest") or {},
            "price_manifest",
        )
        macro_manifest_path, audits["macro_manifest"] = resolve_fingerprint(
            source_inputs.get("portable:macro_manifest") or {},
            "macro_manifest",
        )
        selector_manifest_path, audits["selector_manifest"] = resolve_fingerprint(
            producer.get("selector_manifest") or {},
            "selector_manifest",
        )
        macro_cache_audit_path, audits["macro_cache_audit"] = (
            resolve_fingerprint(
                (producer.get("outputs") or {}).get(
                    "macro_benchmark_cache_audit"
                )
                or {},
                "macro_cache_audit",
            )
        )
        price_map_manifest = read_json(price_map_manifest_path)
        price_manifest = read_json(price_manifest_path)
        macro_manifest = read_json(macro_manifest_path)
        selector_manifest = read_json(selector_manifest_path)
        macro_cache_audit = read_json(macro_cache_audit_path)
        price_map_path, audits["selector_price_map"] = resolve_manifest_output(
            price_map_manifest_path, price_map_manifest, "selector_price_map"
        )
        provider_path, audits["provider_price_overlap"] = resolve_manifest_output(
            price_manifest_path,
            price_manifest,
            "provider_price_overlap.parquet",
        )
        comparison_path, audits["selector_comparison"] = resolve_manifest_output(
            selector_manifest_path,
            selector_manifest,
            "marked_official_advisory_comparison",
        )
        fred_audit_path, audits["fred_component_audit"] = resolve_manifest_output(
            macro_manifest_path,
            macro_manifest,
            "fred_component_audit",
        )
    except Exception as exc:
        failures.append(f"input_contract:{type(exc).__name__}:{exc}")
        return blocked(output_dir, failures, audits, started)

    valuation = pd.Timestamp(args.valuation_date).normalize()
    holding = pd.read_csv(holding_path, low_memory=False)
    comparison = pd.read_csv(comparison_path, low_memory=False)
    roles = role_table(holding, comparison)
    if roles.empty:
        failures.append("empty_decision_security_set")
        return blocked(output_dir, failures, audits, started)

    price_map = pd.read_csv(price_map_path, low_memory=False)
    price_map["ticker"] = price_map["ticker"].map(clean_ticker)
    if price_map["ticker"].duplicated().any():
        failures.append("duplicate_price_map_ticker")
        return blocked(output_dir, failures, audits, started)
    price_records = price_map.set_index("ticker", drop=False)
    provider = pd.read_parquet(provider_path)
    if "ticker" not in provider:
        failures.append("provider_missing_ticker")
        return blocked(output_dir, failures, audits, started)
    provider["ticker"] = provider["ticker"].map(clean_ticker)

    benchmark_cache = Path(str(macro_cache_audit.get("isolated_cache") or ""))
    benchmark_features: dict[str, dict[str, Any]] = {}
    fib_rows: list[dict[str, Any]] = []
    for ticker in ("SPY", "QQQ"):
        entry = (macro_cache_audit.get("tickers") or {}).get(ticker) or {}
        isolated = entry.get("isolated") or {}
        path, audit = resolve_fingerprint(isolated, f"benchmark:{ticker}")
        audits[f"benchmark:{ticker}"] = audit
        expected_path = benchmark_cache / px_cache_name(ticker)
        if path.resolve() != expected_path.resolve():
            failures.append(f"benchmark_cache_path:{ticker}")
            continue
        raw = pd.read_parquet(path)
        px = adjusted_ohlcv(raw, valuation)
        feature, levels = fixed_window_features(
            ticker, px, valuation, contract
        )
        benchmark_features[ticker] = feature
        fib_rows.extend(levels)
    if failures:
        return blocked(output_dir, failures, audits, started)

    fred_audit = pd.read_csv(fred_audit_path, low_memory=False)
    if "name" not in fred_audit:
        failures.append("fred_component_audit_missing_name")
        return blocked(output_dir, failures, audits, started)
    vix_rows = fred_audit.loc[
        fred_audit["name"].astype(str).str.strip().str.lower().eq("vix")
    ]
    if len(vix_rows) != 1:
        failures.append(f"fred_vix_row_count:{len(vix_rows)}")
        return blocked(output_dir, failures, audits, started)
    vix_record = vix_rows.iloc[0]
    if str(vix_record.get("status") or "") != "ready":
        failures.append(f"fred_vix_status:{vix_record.get('status')}")
        return blocked(output_dir, failures, audits, started)
    vix_path = Path(str(vix_record.get("isolated_path") or ""))
    vix_expected_hash = str(vix_record.get("isolated_sha256") or "").lower()
    vix_audit = fingerprint(vix_path)
    vix_audit.update(
        label="vix_series",
        expected_sha256=vix_expected_hash,
        hash_matches=bool(
            vix_expected_hash and vix_audit.get("sha256") == vix_expected_hash
        ),
        latest_usable_observation_date=str(
            vix_record.get("latest_usable_observation_date") or ""
        ),
        latest_usable_available_from=str(
            vix_record.get("latest_usable_available_from") or ""
        ),
        availability_conservative=True,
        vintage_clean=False,
    )
    audits["vix_series"] = vix_audit
    if vix_audit["exists"] is not True or vix_audit["hash_matches"] is not True:
        failures.append("vix_series_hash")
        return blocked(output_dir, failures, audits, started)
    vix_frame = pd.read_parquet(vix_path)
    vix = vix_context(vix_frame, valuation)
    expected_vix_date = str(
        vix_record.get("latest_usable_observation_date") or ""
    )
    if (
        vix.get("vix_data_ready") is True
        and expected_vix_date
        and vix.get("vix_observation_date") != expected_vix_date
    ):
        failures.append(
            "vix_observation_date:"
            f"{vix.get('vix_observation_date')}!={expected_vix_date}"
        )
        return blocked(output_dir, failures, audits, started)
    vix_age = int(vix.get("vix_observation_age_calendar_days") or 0)
    if (
        vix.get("vix_data_ready") is True
        and vix_age > int(contract["price_contract"]["maximum_vix_staleness_calendar_days"])
    ):
        vix["vix_data_ready"] = False
        vix["vix_data_reason"] = f"vix_stale:{vix_age}"
    market = market_context(benchmark_features, vix, contract)
    holding_availability = (
        holding["available_from"].tolist()
        if "available_from" in holding
        else []
    )
    available_from = latest_available_from(
        selector_manifest.get("selector_decision_time_utc"),
        price_manifest.get("score_available_from"),
        macro_manifest.get("macro_available_from"),
        vix_record.get("latest_usable_available_from"),
        *holding_availability,
    )
    if not available_from:
        failures.append("available_from_missing")
        return blocked(output_dir, failures, audits, started)
    forward_window, forward_failures = forward_observation_window(
        valuation,
        available_from,
        accepted_at_utc,
        contract,
    )
    failures.extend(forward_failures)
    if failures:
        return blocked(output_dir, sorted(set(failures)), audits, started)
    rows: list[dict[str, Any]] = []
    price_audit_rows: list[dict[str, Any]] = []
    source_hashes: dict[str, str] = {}
    minimum_overlap = int(contract["price_contract"]["minimum_overlap_rows"])
    maximum_error = float(
        contract["price_contract"]["maximum_overlap_relative_error"]
    )
    for role in roles.to_dict("records"):
        ticker = clean_ticker(role["ticker"])
        feature: dict[str, Any]
        levels: list[dict[str, Any]]
        if ticker not in price_records.index:
            feature = {
                "ticker": ticker,
                "price_exact_asof": False,
                "history_observations": 0,
                "data_reason": "price_map_missing",
            }
            levels = []
            price_audit = {"ticker": ticker, "failure": "price_map_missing"}
        else:
            record = price_records.loc[ticker]
            source_path = Path(str(record.get("path") or ""))
            expected_hash = str(record.get("sha256") or "").lower()
            actual_hash = sha256_file(source_path) if source_path.is_file() else ""
            source_hashes[ticker] = actual_hash
            if not expected_hash or actual_hash != expected_hash:
                failures.append(f"price_source_hash:{ticker}")
                continue
            base_raw = pd.read_parquet(source_path)
            provider_raw = provider.loc[provider["ticker"].eq(ticker)].copy()
            px, price_audit = merge_frozen_and_provider(
                base_raw,
                provider_raw,
                valuation,
                minimum_overlap=minimum_overlap,
                maximum_relative_error=maximum_error,
            )
            price_audit.update(
                ticker=ticker,
                source_path=str(source_path),
                source_sha256=actual_hash,
            )
            feature, levels = fixed_window_features(
                ticker, px, valuation, contract
            )
            if price_audit.get("failure") and not feature.get("data_reason"):
                feature["data_reason"] = str(price_audit["failure"])
        fib_rows.extend(levels)
        combined = {
            "schema_version": SCHEMA_VERSION,
            "as_of_date": args.valuation_date,
            "available_from": available_from,
            "observation_accepted_at_utc": forward_window[
                "observation_accepted_at_utc"
            ],
            **role,
            **feature,
            **vix,
            **market,
            "forward_outcome_status": "UNRESOLVED",
            "forward_outcome_horizons_trading_days": "|".join(
                str(value)
                for value in contract["forward_learning"][
                    "outcome_horizons_trading_days"
                ]
            ),
            "fibonacci_is_standalone_alpha_evidence": False,
            "vix_is_standalone_stock_action_evidence": False,
            "near_high_is_standalone_sell_evidence": False,
            "near_low_is_standalone_buy_evidence": False,
            "portfolio_transition_allowed": False,
            "orders_generated": False,
            "target_books_mutated": False,
            "selector_weights_changed": False,
            "cash_policy_changed": False,
            "champion_changed": False,
            "production_activation_allowed": False,
            "live_trading_enabled": False,
        }
        action, reasons = classify_shadow_action(combined, market)
        combined["shadow_action"] = action
        combined["shadow_reason_codes"] = reasons
        combined["event_id"] = canonical_hash(
            {
                "schema_version": SCHEMA_VERSION,
                "family_id": contract["research_registration"]["family_id"],
                "ticker": ticker,
                "as_of_date": args.valuation_date,
            }
        )
        rows.append(combined)
        price_audit_rows.append(price_audit)
    if failures:
        return blocked(output_dir, failures, audits, started)

    current = pd.DataFrame(rows).sort_values("ticker").reset_index(drop=True)
    levels_frame = pd.DataFrame(fib_rows)
    benchmark_frame = pd.DataFrame(
        [{**{"ticker": ticker}, **feature, **vix, **market}
         for ticker, feature in benchmark_features.items()]
    ).sort_values("ticker")
    # Rehash every source after evaluation. A mutable input invalidates READY.
    failures.extend(changed_input_failures(audits, price_records, source_hashes))
    if failures:
        return blocked(output_dir, failures, audits, started)

    destination_paths = {
        "current": output_dir / "ohlcv_location_timing.csv",
        "levels": output_dir / "fibonacci_levels.csv",
        "benchmark": output_dir / "benchmark_location.csv",
        "observations": output_dir / "forward_observations.jsonl",
        "price_audit": output_dir / "price_source_audit.csv",
    }
    token = uuid.uuid4().hex
    staged_paths = {
        key: path.with_name(f".{path.name}.{token}.tmp")
        for key, path in destination_paths.items()
    }
    try:
        current.to_csv(staged_paths["current"], index=False)
        levels_frame.to_csv(staged_paths["levels"], index=False)
        benchmark_frame.to_csv(staged_paths["benchmark"], index=False)
        pd.DataFrame(price_audit_rows).to_csv(
            staged_paths["price_audit"], index=False
        )
        staged_paths["observations"].write_text(
            "".join(
                json.dumps(
                    json_clean(record),
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                )
                + "\n"
                for record in current.to_dict("records")
            ),
            encoding="utf-8",
        )
        failures.extend(
            changed_input_failures(audits, price_records, source_hashes)
        )
        if failures:
            clear_run_local_outputs(output_dir, include_summary=False)
            return blocked(output_dir, sorted(set(failures)), audits, started)
        for key, destination in destination_paths.items():
            os.replace(staged_paths[key], destination)
        failures.extend(
            changed_input_failures(audits, price_records, source_hashes)
        )
        if failures:
            clear_run_local_outputs(output_dir, include_summary=False)
            return blocked(output_dir, sorted(set(failures)), audits, started)
    except Exception as exc:
        clear_run_local_outputs(output_dir, include_summary=False)
        failures.append(f"output_publish:{type(exc).__name__}:{exc}")
        return blocked(output_dir, sorted(set(failures)), audits, started)
    finally:
        for staged in staged_paths.values():
            staged.unlink(missing_ok=True)
    current_path = destination_paths["current"]
    levels_path = destination_paths["levels"]
    benchmark_path = destination_paths["benchmark"]
    observation_path = destination_paths["observations"]
    price_audit_path = destination_paths["price_audit"]
    insufficient = int(current["data_reason"].fillna("").astype(str).ne("").sum())
    benchmark_insufficient = sum(
        bool(feature.get("data_reason"))
        for feature in benchmark_features.values()
    )
    context_insufficient = int(vix.get("vix_data_ready") is not True)
    total_insufficient = insufficient + benchmark_insufficient + context_insufficient
    status = READY_INSUFFICIENT_STATUS if total_insufficient else READY_STATUS
    payload = {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "contract_failures": [],
        "as_of_date": args.valuation_date,
        "available_from": available_from,
        "forward_observation_window": forward_window,
        "security_count": int(len(current)),
        "held_security_count": int(current["is_held"].fillna(False).sum()),
        "current_selector_security_count": int(
            current["is_current_selector"].fillna(False).sum()
        ),
        "proposed_entry_count": int(
            current["is_proposed_entry"].fillna(False).sum()
        ),
        "data_insufficient_count": insufficient,
        "benchmark_data_insufficient_count": benchmark_insufficient,
        "vix_data_insufficient_count": context_insufficient,
        "shadow_action_counts": {
            str(key): int(value)
            for key, value in current["shadow_action"].value_counts().items()
        },
        "market_context": {**vix, **market},
        "research_registration": contract["research_registration"],
        "learning": {
            **contract["forward_learning"],
            "observation_count": int(len(current)),
            "resolved_outcome_count": 0,
            "promotion_evidence": False,
        },
        "interpretation": {
            "fibonacci_is_descriptive_coordinate_only": True,
            "vix_only_signal_allowed": False,
            "normal_state_is_not_alpha_evidence": True,
            "shadow_action_may_authorize_trade": False,
        },
        "research_only": True,
        "forward_observation_only": True,
        "advisory_only": True,
        "portfolio_transition_allowed": False,
        "orders_generated": False,
        "target_books_mutated": False,
        "selector_weights_changed": False,
        "cash_policy_changed": False,
        "champion_changed": False,
        "historical_cagr_mdd_evidence_changed": False,
        "backtest_executed": False,
        "fullrun_executed": False,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
        "source_inputs": audits,
        "outputs": {
            "ohlcv_location_timing": fingerprint(current_path),
            "fibonacci_levels": fingerprint(levels_path),
            "benchmark_location": fingerprint(benchmark_path),
            "forward_observations": fingerprint(observation_path),
            "price_source_audit": fingerprint(price_audit_path),
        },
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "performance": {"elapsed_seconds": time.perf_counter() - started},
        "code": {"git_head": git_head(), "builder": fingerprint(Path(__file__))},
    }
    report_path = output_dir / "report.md"
    staged_report = report_path.with_name(
        f".{report_path.name}.{uuid.uuid4().hex}.tmp"
    )
    try:
        staged_report.write_text(
            render_report(payload, current), encoding="utf-8"
        )
        failures.extend(
            changed_input_failures(audits, price_records, source_hashes)
        )
        if failures:
            clear_run_local_outputs(output_dir, include_summary=True)
            return blocked(
                output_dir, sorted(set(failures)), audits, started
            )
        os.replace(staged_report, report_path)
        # summary.json is the READY commit marker and is written last, only
        # after every data/report artifact is durable.
        write_json(output_dir / "summary.json", payload)
    except Exception as exc:
        clear_run_local_outputs(output_dir, include_summary=True)
        failures.append(f"ready_finalize:{type(exc).__name__}:{exc}")
        return blocked(output_dir, sorted(set(failures)), audits, started)
    finally:
        staged_report.unlink(missing_ok=True)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--producer-status",
        default="outputs/run287_exact_packet_producer/status.json",
    )
    parser.add_argument(
        "--holding-watch",
        default="outputs/holding_risk_watch/holding_risk_watch.csv",
    )
    parser.add_argument(
        "--contract",
        default="docs/run287_ohlcv_location_timing_challenger_contract.json",
    )
    parser.add_argument("--valuation-date", required=True)
    parser.add_argument(
        "--observation-accepted-at-utc",
        default="",
        help=(
            "UTC time at which this same-close observation is accepted; "
            "defaults to current UTC and must satisfy the forward-only window"
        ),
    )
    parser.add_argument(
        "--output-dir",
        default="outputs/run287_ohlcv_location_timing_challenger",
    )
    return parser.parse_args()


def main() -> int:
    payload = build(parse_args())
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0 if str(payload.get("status") or "").startswith("READY_") else 2


if __name__ == "__main__":
    raise SystemExit(main())
