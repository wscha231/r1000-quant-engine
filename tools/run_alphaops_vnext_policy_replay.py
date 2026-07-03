#!/usr/bin/env python3
"""Build AlphaOps vNext production target books from historical candidates.

This is the production bridge for the lane/leader/crisis research work.  It
does not place live trades.  In ``replace_operating`` mode it replaces the
official broker-ledger target books so the subsequent broker replay and
``user_current`` report reflect vNext from the first historical rebalance date.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from r1000_candidate_lanes import lane_feature_mapping_payload, score_candidate_lanes  # noqa: E402
from r1000_helpers import phase_is_enabled  # noqa: E402
from r1000_market_leader_engine import BENCHMARKS, classify_leader_state, classify_leader_tier, safe_float  # noqa: E402
from r1000_market_leader_engine import (  # noqa: E402
    MarketLeaderVariant,
    RISK_MODE_BENCHMARK_GUARD,
    apply_benchmark_risk_overlay,
    compute_sector_leadership_score,
    compute_smart_money_confirmation_score,
)
from tools.concentrated_score_sizing_reweight import (  # noqa: E402
    CAP_MODES as CONCENTRATED_SCORE_SIZING_CAP_MODES,
    DEFAULT_BLEND as DEFAULT_CONCENTRATED_SCORE_SIZING_BLEND,
    DEFAULT_CAP_MODE as DEFAULT_CONCENTRATED_SCORE_SIZING_CAP_MODE,
    DEFAULT_RANK_POWER as DEFAULT_CONCENTRATED_SCORE_SIZING_RANK_POWER,
    DEFAULT_SIGNAL as DEFAULT_CONCENTRATED_SCORE_SIZING_SIGNAL,
    DEFAULT_SINGLE_CAP as DEFAULT_CONCENTRATED_SCORE_SIZING_SINGLE_CAP,
    reweight_concentrated_records,
)
from tools.ai_capex_taxonomy import enrich_frame as enrich_ai_capex_frame  # noqa: E402
from tools.run_broker_ledger_replay import DISABLE_CONCENTRATED_CHAMPION_FILTERS, replay as broker_replay  # noqa: E402
from tools.run_integrated_theme_leader_crisis_replay import (  # noqa: E402
    CRISIS_HYSTERESIS,
    CRISIS_SETTINGS,
    build_daily_crisis_state,
    crisis_state_audit,
    defense_multiplier,
)
from tools.run_market_leader_challenger import normalize_candidate_frame, read_table, resolve_candidate_book  # noqa: E402
from tools.run_neutral_regime_churn_filter import apply_churn_filter, compute_swap_counts  # noqa: E402
from tools.run_user_current_report import build_report as build_user_current_report  # noqa: E402
from tools.run_weekly_evaluation import load_price_series, price_on_or_before, px_cache_name  # noqa: E402


DEFAULT_LATEST_RUN = "outputs"
DEFAULT_OUTPUT_DIR = "outputs/alphaops_vnext"
CASH_TICKERS = {"CASH", "__CASH__"}
CORE_BENCHMARKS = ("SPY", "QQQ")
SEMIS_BENCHMARKS = ("SMH", "SOXX")
DEFAULT_REGIME_CAPACITY_MULTIPLIERS = {
    "main": {
        "exceptional_bull": 1.0,
        "strong_bull": 1.0,
        "bull": 1.0,
        "neutral": 1.0,
        "bear": 1.0,
        "deep_bear": 1.0,
        "unknown": 1.0,
    },
    "concentrated": {
        "exceptional_bull": 1.0,
        "strong_bull": 1.0,
        "bull": 1.0,
        "neutral": 0.95,
        "bear": 0.50,
        "deep_bear": 0.25,
        "unknown": 1.0,
    },
}
# P0a bull-regime stock-weight floor (IS-attribution leak fix). The
# 27498401423 IS attribution tagged concentrated 2021 + 2023 as
# `structural_underinvestment_bull`: 5/5 names selected but only ~57%/54%
# stock weight in 58%/46% bull regimes, dragging IS-CAGR to ~21%. The
# regime_capacity overlay was a one-way door (only dampened in bear). This
# makes it two-way: in confirmed bull regimes, scale thinned weights UP to a
# floor via capped water-filling. Default OFF (env BULL_FLOOR or
# PHASE_REGIME_CAPACITY_BULL_FLOOR_ENABLED) so it is A/B-measurable by the
# performance ledger before promotion.
BULL_REGIME_STATES = {"bull", "strong_bull", "exceptional_bull"}
DEFAULT_REGIME_CAPACITY_BULL_FLOOR = {
    "main": 0.90,
    "concentrated": 0.85,
}
# Per-name ceiling used when no explicit effective_single_weight_cap column
# is present on the book, so water-filling never over-concentrates a name.
DEFAULT_BULL_FLOOR_SINGLE_CAP = {
    "main": 0.15,
    "concentrated": 0.30,
}
REGIME_CAPACITY_BULL_FLOOR_ENV = {
    "main": "R1000_MAIN_GROSS_CAP_FLOOR",
    "concentrated": "R1000_CONC_GROSS_CAP_FLOOR",
}


def regime_capacity_bull_floor(portfolio_kind: str) -> tuple[float, str]:
    """Return the env-overridable bull stock floor for one portfolio."""
    default = float(DEFAULT_REGIME_CAPACITY_BULL_FLOOR.get(portfolio_kind, 0.90))
    env_key = REGIME_CAPACITY_BULL_FLOOR_ENV.get(portfolio_kind, "")
    raw = os.environ.get(env_key) if env_key else None
    if raw is None or str(raw).strip() == "":
        return default, "default"
    value = safe_float(raw, default)
    if not math.isfinite(value):
        return default, f"invalid_env:{env_key}"
    return float(max(0.0, min(1.0, value))), f"env:{env_key}"


def capped_proportional_fill(
    weights: list[float], target_total: float, ceilings: list[float]
) -> list[float]:
    """Scale `weights` up proportionally to reach `target_total` without any
    element exceeding its ceiling (iterative water-filling).

    Used to lift a thinned bull-regime book to the stock-weight floor while
    respecting per-name caps. If the ceilings cannot reach target_total, fills
    every name to its ceiling and returns the (lower) achievable total.
    """
    w = [max(0.0, float(x)) for x in weights]
    cap = [max(0.0, float(c)) for c in ceilings]
    n = len(w)
    if n == 0:
        return w
    target = min(float(target_total), sum(cap))
    cur = sum(w)
    if cur <= 1e-12 or target <= cur + 1e-12:
        return w
    locked = [False] * n
    out = list(w)
    # iterate: distribute the remaining deficit proportionally to the
    # unlocked names' current weight, clamp any that hit their ceiling, repeat.
    for _ in range(n + 2):
        deficit = target - sum(out)
        if deficit <= 1e-12:
            break
        unlocked_base = sum(out[i] for i in range(n) if not locked[i])
        if unlocked_base <= 1e-12:
            break
        any_locked_this_pass = False
        for i in range(n):
            if locked[i]:
                continue
            add = deficit * (out[i] / unlocked_base)
            if out[i] + add >= cap[i] - 1e-12:
                out[i] = cap[i]
                locked[i] = True
                any_locked_this_pass = True
            else:
                out[i] = out[i] + add
        if not any_locked_this_pass:
            break
    return out


WINDOWS = {
    "1w": ("days", 5),
    "2w": ("days", 10),
    "1m": ("months", 1),
    "3m": ("months", 3),
    "6m": ("months", 6),
}
MAIN_VARIANTS = (12, 15, 18)
CONCENTRATED_VARIANTS = (3, 5)
DEFAULT_MAIN_TARGET_N = 15
DEFAULT_CONCENTRATED_TARGET_N = 5
CONCENTRATED_RISK_STATE_NEW_ENTRY_CAP = 0.20
CONCENTRATED_RISK_STATE_CAP_STATES = {"WATCH", "DEFENSE_REVIEW"}
CONCENTRATED_HOLD_DECAY_CAP = 0.04
LEADERSHIP_PERSISTENCE_HOLD_MIN_PRIOR_WEIGHT = 0.02
LEADERSHIP_PERSISTENCE_HOLD_MIN_GAP = 0.22
LEADERSHIP_PERSISTENCE_HOLD_SIGMA_MULTIPLIER = 1.10
LEADERSHIP_PERSISTENCE_HOLD_SIGMA_MULTIPLIER_ENV = "PHASE_LEADERSHIP_PERSISTENCE_HOLD_SIGMA_MULTIPLIER"
LEADERSHIP_PERSISTENCE_MAIN_TIERS = {"DUAL_LEADER", "SECTOR_LEADER"}
LEADERSHIP_PERSISTENCE_CONCENTRATED_TIERS = {"DUAL_LEADER"}
CONCENTRATED_WATCH_UNCONFIRMED_HIGH_VOL_NEW_ENTRY_CAP = 0.12
CONCENTRATED_WATCH_UNCONFIRMED_HIGH_VOL_ATR_THRESHOLD = 0.06
CONCENTRATED_WATCH_UNCONFIRMED_CONFIRMATION_THRESHOLD = 0.50
CONCENTRATED_UNCONFIRMED_HIGH_VOL_NEW_ENTRY_CAP = 0.12
CONCENTRATED_UNCONFIRMED_HIGH_VOL_ATR_THRESHOLD = 0.06
CONCENTRATED_UNCONFIRMED_QUALITY_BULL_NEW_ENTRY_CAP = 0.03
CONCENTRATED_UNCONFIRMED_QUALITY_BULL_CONFIRMATION_THRESHOLD = 0.50
CONCENTRATED_UNCONFIRMED_QUALITY_BULL_EXEMPT_SCORE_THRESHOLD = 4.90
CONCENTRATED_UNCONFIRMED_QUALITY_BULL_EXEMPT_SEC_THRESHOLD = 0.20
CONCENTRATED_UNCONFIRMED_QUALITY_BULL_EXEMPT_ATR_MAX = 0.03
CONCENTRATED_UNCONFIRMED_QUALITY_BULL_EXEMPT_RS_1M_MIN = 0.20
CONCENTRATED_WATCH_UNCONFIRMED_ML_NEW_ENTRY_CAP = 0.08
CONCENTRATED_WATCH_UNCONFIRMED_ML_CONFIRMATION_THRESHOLD = 0.50
CONCENTRATED_WATCH_DAMAGED_WEAK_ML_CAP = 0.08
CONCENTRATED_WATCH_DAMAGED_WEAK_ML_CONFIRMATION_THRESHOLD = 0.50
CONCENTRATED_WATCH_DAMAGED_WEAK_ML_BREAKOUT_THRESHOLD = 0.60
CONCENTRATED_WATCH_DAMAGED_WEAK_ML_TICKER_RET_1M_THRESHOLD = 0.05
CONCENTRATED_GREEN_BULL_QQQ_DOWN_NEW_ENTRY_CAP = 0.08
CONCENTRATED_GREEN_BULL_QQQ_DOWN_THRESHOLD = 0.0
CONCENTRATED_GREEN_CONSUMER_OVERHEAT_NEW_ENTRY_CAP = 0.08
CONCENTRATED_GREEN_CONSUMER_OVERHEAT_RS_1M_THRESHOLD = 0.25
CONCENTRATED_GREEN_CONFIRMED_ML_WEAK_RS_NEW_ENTRY_CAP = 0.12
CONCENTRATED_GREEN_CONFIRMED_ML_WEAK_RS_1M_THRESHOLD = 0.12
CONCENTRATED_GREEN_CONFIRMED_ML_CONFIRMATION_THRESHOLD = 1.0
CONCENTRATED_GREEN_CONFIRMED_ML_EXEMPT_SCORE_THRESHOLD = 5.0
CONCENTRATED_GREEN_CONFIRMED_ML_EXEMPT_SEC_THRESHOLD = 0.30
CONCENTRATED_GREEN_CONFIRMED_ML_EXEMPT_ATR_MAX = 0.04
CONCENTRATED_GREEN_CONFIRMED_ML_EXEMPT_RS_1M_MIN = 0.05
CONCENTRATED_HIGH_VOL_WEAK_TIMING_NEW_ENTRY_CAP = 0.08
CONCENTRATED_HIGH_VOL_WEAK_TIMING_ATR_THRESHOLD = 0.05
CONCENTRATED_HIGH_VOL_WEAK_TIMING_CONFIRMATION_THRESHOLD = 0.50
CONCENTRATED_HIGH_VOL_WEAK_TIMING_RS_1M_THRESHOLD = 0.05
CONCENTRATED_GREEN_NEUTRAL_CYCLICAL_HIGH_VOL_NEW_ENTRY_CAP = 0.06
CONCENTRATED_GREEN_NEUTRAL_CYCLICAL_HIGH_VOL_ATR_THRESHOLD = 0.06
CONCENTRATED_GREEN_NEUTRAL_CYCLICAL_HIGH_VOL_SECTORS = {"Energy", "Materials"}
CONCENTRATED_DEFENSE_NEUTRAL_QUALITY_NEW_ENTRY_CAP = 0.12
MAIN_HIGH_VOL_NEW_ENTRY_CAP = 0.08
MAIN_HIGH_VOL_NEW_ENTRY_ATR_THRESHOLD = 0.06
MAIN_HIGH_VOL_NEW_ENTRY_LANES = {"MARKET_LEADER"}
MAIN_HIGH_VOL_EXEMPT_SCORE_THRESHOLD = 4.80
MAIN_HIGH_VOL_EXEMPT_SEC_THRESHOLD = 0.20
MAIN_HIGH_VOL_EXEMPT_ATR_MAX = 0.08
MAIN_HIGH_VOL_EXEMPT_RS_1M_MIN = 0.45
MAIN_WATCH_UNCONFIRMED_ML_NEW_ENTRY_CAP = 0.04
MAIN_WATCH_UNCONFIRMED_ML_CONFIRMATION_THRESHOLD = 0.50
MAIN_NEUTRAL_CHURN_FILTER_SWAP_THRESHOLD = 2
MAIN_NEUTRAL_CHURN_FILTER_WINDOW_MONTHS = 6
MAIN_NEUTRAL_CHURN_FILTER_TARGET_REGIMES = ("neutral",)
NEUTRAL_METALS_NEW_ENTRY_BLOCK_SECTOR = "Materials"
NEUTRAL_METALS_NEW_ENTRY_BLOCK_INDUSTRY_TERMS = ("metals", "mining")
NEUTRAL_METALS_NEW_ENTRY_BLOCK_LANES = ("MARKET_LEADER",)
NEUTRAL_METALS_NEW_ENTRY_BLOCK_REGIMES = ("neutral",)
NEUTRAL_METALS_NEW_ENTRY_BLOCK_STYLE_REGIME = "quality_compounder"
MAIN_DEFENSE_REVIEW_TURNAROUND_NEW_ENTRY_BLOCK_LANE = "QUALITY_COMPOUNDER"
MAIN_DEFENSE_REVIEW_TURNAROUND_NEW_ENTRY_BLOCK_STYLE = "turnaround_accumulation"
MAIN_DEFENSE_REVIEW_TURNAROUND_NEW_ENTRY_BLOCK_REGIME = "neutral"
MAIN_DEFENSE_REVIEW_TURNAROUND_NEW_ENTRY_BLOCK_CRISIS = "DEFENSE_REVIEW"
MAIN_DEFENSE_REVIEW_BALANCED_NEW_ENTRY_BLOCK_LANE = "QUALITY_COMPOUNDER"
MAIN_DEFENSE_REVIEW_BALANCED_NEW_ENTRY_BLOCK_STYLE = "balanced"
MAIN_DEFENSE_REVIEW_BALANCED_NEW_ENTRY_BLOCK_REGIME = "neutral"
MAIN_DEFENSE_REVIEW_BALANCED_NEW_ENTRY_BLOCK_CRISIS = "DEFENSE_REVIEW"
MAIN_DEFENSE_REVIEW_BALANCED_NEW_ENTRY_BLOCK_BREAKOUT_THRESHOLD = 0.50
CONCENTRATED_GREEN_BENCHMARK_RISK_CYCLICAL_NEW_ENTRY_BLOCK_MIN_WEIGHT = 0.04
CONCENTRATED_GREEN_BENCHMARK_RISK_CYCLICAL_NEW_ENTRY_BLOCK_BENCHMARK_RISK_THRESHOLD = 0.70
CONCENTRATED_GREEN_BENCHMARK_RISK_CYCLICAL_NEW_ENTRY_BLOCK_ATR_THRESHOLD = 0.10
CONCENTRATED_GREEN_BENCHMARK_RISK_CYCLICAL_NEW_ENTRY_BLOCK_BREAKOUT_THRESHOLD = 0.40
CONCENTRATED_GREEN_BENCHMARK_RISK_CYCLICAL_NEW_ENTRY_BLOCK_SECTORS = {"Energy", "Materials"}
CONCENTRATED_SCORE_SIZING_REWEIGHT_SIGNAL = DEFAULT_CONCENTRATED_SCORE_SIZING_SIGNAL
CONCENTRATED_SCORE_SIZING_REWEIGHT_BLEND = DEFAULT_CONCENTRATED_SCORE_SIZING_BLEND
CONCENTRATED_SCORE_SIZING_REWEIGHT_RANK_POWER = DEFAULT_CONCENTRATED_SCORE_SIZING_RANK_POWER
CONCENTRATED_SCORE_SIZING_REWEIGHT_CAP_MODE = DEFAULT_CONCENTRATED_SCORE_SIZING_CAP_MODE
CONCENTRATED_SCORE_SIZING_REWEIGHT_SINGLE_CAP = DEFAULT_CONCENTRATED_SCORE_SIZING_SINGLE_CAP
CONCENTRATED_REPLACEMENT_QUALITY_RANK_MAX = 15
CONCENTRATED_REPLACEMENT_QUALITY_REVENUE_GROWTH_MIN = 0.10
CONCENTRATED_REPLACEMENT_QUALITY_MAX_SWAPS_PER_DATE = 1
CONCENTRATED_REPLACEMENT_QUALITY_SCORE_COLUMNS = [
    "relative_strength_composite",
    "oneil_leadership_score",
    "rs_acceleration_score",
    "industry_group_strength_score",
    "etf_theme_leadership_score",
    "theme_leadership_score",
    "score",
    "score_total",
    "concentrated_score",
]
CONCENTRATED_REPLACEMENT_QUALITY_REVENUE_COLUMNS = [
    "revenue_growth",
    "sales_growth_yoy",
    "revenue_growth_yoy",
    "revenue_growth_final",
]
CONCENTRATED_REPLACEMENT_QUALITY_REJECTION_REASONS = {
    "hold_replace_threshold_not_met",
    "leadership_persistence_hold_threshold_not_met",
    "concentrated_emerging_or_top7_seat_cap",
}
AI_CAPEX_MOMENTUM_TILT_STRENGTH = 0.15
MAIN_FAST_CRASH_HEDGE_TICKER = "SH"
MAIN_FAST_CRASH_HEDGE_BENCHMARK = "SPY"
MAIN_FAST_CRASH_HEDGE_WEIGHT = 0.075
MAIN_FAST_CRASH_RISK_BUFFER_WEIGHT = 0.005
MAIN_FAST_CRASH_HEDGE_5D_DROP = -0.05
MAIN_FAST_CRASH_HEDGE_10D_DROP = -0.08
CONCENTRATED_CASHFUNDED_EARLY_ENTRY_SIGNAL = "future_winner_scout_score"
CONCENTRATED_CASHFUNDED_EARLY_ENTRY_ADD_WEIGHT = 0.058
CONCENTRATED_CASHFUNDED_EARLY_ENTRY_MIN_BREAKOUT_QUALITY = 0.50
FORBIDDEN_EARLY_ENTRY_SIGNAL_EXACT = {
    "period_forward_return",
    "forward_return",
    "forward_return_coverage_score",
    "future_return",
    "future_63d_return",
    "future_126d_return",
    "next_63d_return",
    "next_126d_return",
    "audit_forward_return",
    "audit_forward_63d_excess",
    "audit_forward_126d_excess",
    "forward_63d_excess",
    "forward_126d_excess",
}
FORBIDDEN_EARLY_ENTRY_SIGNAL_PATTERNS = (
    "period_forward",
    "forward_return",
    "future_return",
    "audit_forward",
    "forward_excess",
    "future_excess",
    "next_63d_return",
    "next_126d_return",
)
MAIN_GREEN_BULL_LOW_CONFIRM_HIGH_VOL_NEW_ENTRY_CAP = 0.05
MAIN_GREEN_BULL_LOW_CONFIRM_HIGH_VOL_ATR_THRESHOLD = 0.06
MAIN_GREEN_BULL_LOW_CONFIRM_CONFIRMATION_THRESHOLD = 0.50
MAIN_BALANCED_BULL_QQQ_DAMAGE_LOW_CONFIRM_LEADER_CAP = 0.0
MAIN_BALANCED_BULL_QQQ_DAMAGE_MIN_WEIGHT = 0.04
MAIN_BALANCED_BULL_QQQ_DAMAGE_CONFIRMATION_THRESHOLD = 0.50
MAIN_BALANCED_BULL_QQQ_DAMAGE_SECTORS = {"Industrials", "Information Technology"}
MAIN_BALANCED_NEUTRAL_SOFT_QQQ_DAMAGE_WEAK_LEADER_CAP = 0.04
MAIN_BALANCED_NEUTRAL_SOFT_QQQ_DAMAGE_MIN_WEIGHT = 0.08
MAIN_BALANCED_NEUTRAL_SOFT_QQQ_DAMAGE_SPY_MAX_RETURN = 0.03
MAIN_BALANCED_NEUTRAL_SOFT_QQQ_DAMAGE_CONFIRMATION_THRESHOLD = 0.50
MAIN_BALANCED_NEUTRAL_SOFT_QQQ_DAMAGE_BREAKOUT_QUALITY_THRESHOLD = 0.60
MAIN_QUALITY_BULL_LOW_CONFIRM_NEW_ENTRY_CAP = 0.01
MAIN_QUALITY_BULL_LOW_CONFIRM_CONFIRMATION_THRESHOLD = 0.75
MAIN_GREEN_NEUTRAL_CYCLICAL_HIGH_VOL_NEW_ENTRY_CAP = 0.01
MAIN_GREEN_NEUTRAL_CYCLICAL_HIGH_VOL_ATR_THRESHOLD = 0.06
MAIN_GREEN_NEUTRAL_CYCLICAL_HIGH_VOL_SECTORS = {"Energy", "Materials"}
MAIN_QUALITY_HOLD_WEAK_TIMING_CAP = 0.01
MAIN_QUALITY_HOLD_CONFIRMATION_THRESHOLD = 0.75
MAIN_QUALITY_HOLD_RS_1M_THRESHOLD = 0.10


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def file_sha256(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_meta(path: Path) -> dict[str, Any]:
    return {
        "path": str(path),
        "exists": bool(path.exists()),
        "bytes": int(path.stat().st_size) if path.exists() and path.is_file() else 0,
        "sha256": file_sha256(path),
    }


def write_csv(path: Path, frame: pd.DataFrame) -> pd.DataFrame:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)
    return frame


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def clean_ticker(value: Any) -> str:
    text = str(value or "").upper().strip()
    return "" if text in {"", "NAN", "NONE"} else text


def date_text(value: Any) -> str:
    dt = pd.to_datetime(value, errors="coerce")
    return "" if pd.isna(dt) else pd.Timestamp(dt).date().isoformat()


def numeric(frame: pd.DataFrame, col: str, default: float = 0.0) -> pd.Series:
    if col not in frame.columns:
        return pd.Series(default, index=frame.index, dtype=float)
    return pd.to_numeric(frame[col], errors="coerce").fillna(default)


def robust_z(values: pd.Series) -> pd.Series:
    x = pd.to_numeric(values, errors="coerce").replace([np.inf, -np.inf], np.nan)
    if not x.notna().any():
        return pd.Series(0.0, index=values.index, dtype=float)
    med = float(x.median(skipna=True))
    mad = float((x - med).abs().median(skipna=True))
    if math.isfinite(mad) and mad > 1e-12:
        return ((x - med) / (1.4826 * mad)).fillna(0.0).clip(-6, 6)
    std = float(x.std(skipna=True, ddof=0))
    denom = std if math.isfinite(std) and std > 1e-12 else 1.0
    return ((x - med) / denom).fillna(0.0).clip(-6, 6)


def price_return_window(px: pd.DataFrame, as_of_date: Any, mode: str, amount: int) -> tuple[float, bool]:
    if px.empty:
        return 0.0, False
    end_dt, end_px = price_on_or_before(px, as_of_date, "close")
    if end_dt is None or end_px is None:
        return 0.0, False
    if mode == "days":
        start_target = pd.Timestamp(end_dt) - pd.Timedelta(days=int(amount))
    else:
        start_target = pd.Timestamp(end_dt) - pd.DateOffset(months=int(amount))
    start_dt, start_px = price_on_or_before(px, start_target, "close")
    if start_dt is None or start_px is None or start_px <= 0:
        return 0.0, False
    return float(end_px / start_px - 1.0), True


def price_map(price_cache: Path, candidate: pd.DataFrame) -> dict[str, pd.DataFrame]:
    tickers = {clean_ticker(x) for x in candidate.get("ticker", pd.Series(dtype=str)).dropna().unique()}
    tickers.update(BENCHMARKS)
    tickers = {t for t in tickers if t and t not in CASH_TICKERS}
    return {ticker: load_price_series(price_cache, ticker) for ticker in sorted(tickers)}


def enrich_relative_strength(candidate: pd.DataFrame, price_cache: Path) -> pd.DataFrame:
    if candidate.empty:
        return candidate
    prices = price_map(price_cache, candidate)
    rows: list[pd.DataFrame] = []
    for raw_dt, month in candidate.groupby("rebalance_date", sort=True):
        dt = pd.Timestamp(raw_dt).normalize()
        d = month.copy()
        benchmark_returns: dict[tuple[str, str], tuple[float, bool]] = {}
        for bench in BENCHMARKS:
            px = prices.get(bench, pd.DataFrame())
            for label, (mode, amount) in WINDOWS.items():
                benchmark_returns[(bench, label)] = price_return_window(px, dt, mode, amount)
        for label, (mode, amount) in WINDOWS.items():
            ticker_returns: list[float] = []
            coverage: list[bool] = []
            for ticker in d["ticker"].map(clean_ticker):
                ret, ok = price_return_window(prices.get(ticker, pd.DataFrame()), dt, mode, amount)
                fallback_cols = [f"mom_{label}", f"ret_{label}", f"ticker_ret_{label}"]
                if not ok:
                    fallback = next((safe_float(d.loc[d["ticker"].map(clean_ticker).eq(ticker), col].iloc[0]) for col in fallback_cols if col in d.columns), 0.0)
                    ret = fallback
                ticker_returns.append(ret)
                coverage.append(ok)
            d[f"ticker_ret_{label}"] = ticker_returns
            d[f"rs_price_coverage_{label}"] = coverage
            for bench in BENCHMARKS:
                bench_ret, _bench_ok = benchmark_returns[(bench, label)]
                d[f"rs_{bench.lower()}_{label}"] = d[f"ticker_ret_{label}"] - float(bench_ret)
            core_cols = [f"rs_{bench.lower()}_{label}" for bench in CORE_BENCHMARKS if f"rs_{bench.lower()}_{label}" in d.columns]
            semis_cols = [f"rs_{bench.lower()}_{label}" for bench in SEMIS_BENCHMARKS if f"rs_{bench.lower()}_{label}" in d.columns]
            if core_cols:
                d[f"rs_benchmark_{label}"] = d[core_cols].mean(axis=1)
            if semis_cols:
                d[f"rs_semis_{label}"] = d[semis_cols].mean(axis=1)
        d["rs_price_coverage_flag"] = d[[f"rs_price_coverage_{label}" for label in WINDOWS]].any(axis=1)
        d["rs_benchmark_source"] = "price_cache_or_candidate_fallback"
        rows.append(d)
    return pd.concat(rows, ignore_index=True) if rows else candidate


def enforce_pit_available(candidate: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Zero evidence fields whose availability is after the signal date."""

    if candidate.empty:
        return candidate, pd.DataFrame()
    d = candidate.copy()
    if "rebalance_date" not in d.columns:
        return d, pd.DataFrame()
    signal_dt = pd.to_datetime(d["rebalance_date"], errors="coerce", utc=True).dt.tz_convert(None).dt.normalize()
    availability_cols = sorted(
        {
            col
            for col in d.columns
            if col in {"available_from", "latest_available_from", "evidence_available_from"}
            or col.endswith("_available_from")
        }
    )
    if not availability_cols:
        d["pit_evidence_blocked"] = False
        return d, pd.DataFrame()
    blocked = pd.Series(False, index=d.index)
    for col in availability_cols:
        available = pd.to_datetime(d[col], errors="coerce", utc=True).dt.tz_convert(None).dt.normalize()
        blocked = blocked | (available.notna() & signal_dt.notna() & available.gt(signal_dt))
    evidence_cols = [
        col
        for col in d.columns
        if col.startswith(("sec_", "etf_", "top7_", "post_disclosure_"))
        or col in {"issuer_float_impact_score", "top_manager_discovery_score"}
    ]
    for col in evidence_cols:
        if pd.api.types.is_bool_dtype(d[col]):
            d.loc[blocked, col] = False
        elif pd.api.types.is_numeric_dtype(d[col]):
            d.loc[blocked, col] = 0.0
        else:
            d.loc[blocked, col] = ""
    d["pit_evidence_blocked"] = blocked
    d["pit_evidence_block_reason"] = np.where(blocked, "evidence_available_after_rebalance_date", "")
    audit_cols = ["rebalance_date", "ticker", *availability_cols, "pit_evidence_blocked", "pit_evidence_block_reason"]
    return d, d.loc[blocked, [col for col in audit_cols if col in d.columns]].copy()


def evidence_support_score(frame: pd.DataFrame) -> pd.Series:
    """Positive-only support from PIT-safe SEC/ETF evidence, never a standalone buy rule."""

    support_cols = [
        "evidence_fusion_score",
        "smart_money_shadow_score",
        "smart_money_convergence_bonus",
        "sec_combined_evidence_score",
        "leader_onset_sec_v3_score",
        "institutional_evidence_score",
        "sec_13f_smart_money_score",
        "sec_13f_accumulation_score",
        "sec_form4_score",
        "etf_theme_leadership_score",
        "etf_holdings_score",
    ]
    pieces = [robust_z(numeric(frame, col)).clip(lower=0.0, upper=3.0) for col in support_cols if col in frame.columns]
    if not pieces:
        return pd.Series(0.0, index=frame.index)
    return pd.concat(pieces, axis=1).max(axis=1).fillna(0.0)


def alphaops_score(frame: pd.DataFrame) -> pd.Series:
    return (
        pd.to_numeric(frame.get("lane_confidence", 0.0), errors="coerce").fillna(0.0)
        + 0.18 * robust_z(numeric(frame, "market_leader_lane_score")).clip(lower=0.0)
        + 0.12 * robust_z(numeric(frame, "valuation_support_score")).clip(lower=0.0)
        + 0.12 * robust_z(numeric(frame, "rs_benchmark_1w")).clip(lower=0.0)
        + 0.10 * robust_z(numeric(frame, "rs_semis_3m")).clip(lower=0.0)
        + 0.08 * pd.to_numeric(frame.get("top7_support_boost", 0.0), errors="coerce").fillna(0.0)
        + 0.06 * numeric(frame, "evidence_support_score").clip(lower=0.0, upper=3.0)
    )


def concentrated_allowed_leader_tiers() -> set[str]:
    raw = os.environ.get("ALPHAOPS_CONCENTRATED_LEADER_ALLOWED_TIERS", "DUAL_LEADER")
    allowed = {part.strip() for part in str(raw).split(",") if part.strip()}
    return allowed or {"DUAL_LEADER"}


def leadership_mask(frame: pd.DataFrame) -> pd.Series:
    return (
        numeric(frame, "rs_spy_3m").gt(0.0)
        & numeric(frame, "rs_qqq_3m").gt(0.0)
        & (numeric(frame, "rs_spy_6m").gt(0.0) | numeric(frame, "rs_qqq_6m").gt(0.0))
    )


def recompute_lane_selection(frame: pd.DataFrame) -> pd.DataFrame:
    d = frame.copy()
    lane_cols = {
        "QUALITY_COMPOUNDER": "quality_compounder_lane_score",
        "MARKET_LEADER": "market_leader_lane_score",
        "EMERGING_TENBAGGER": "emerging_tenbagger_lane_score",
        "TOP7_MANAGER_DISCOVERY": "top7_manager_discovery_lane_score",
        "CYCLICAL_RECOVERY": "cyclical_recovery_lane_score",
        "CRISIS_BENEFICIARY": "crisis_beneficiary_lane_score",
    }
    scores = pd.DataFrame(
        {lane: pd.to_numeric(d.get(col, 0.0), errors="coerce").fillna(-999.0) for lane, col in lane_cols.items()},
        index=d.index,
    )
    if "top7_standalone_blocked" in d.columns:
        scores.loc[d["top7_standalone_blocked"].fillna(False).astype(bool), "TOP7_MANAGER_DISCOVERY"] = -999.0
    boost = pd.to_numeric(d.get("top7_support_boost", 0.0), errors="coerce").fillna(0.0)
    for lane in ["QUALITY_COMPOUNDER", "MARKET_LEADER", "EMERGING_TENBAGGER", "CYCLICAL_RECOVERY"]:
        scores[lane] = scores[lane] + 0.08 * boost
    d["primary_lane"] = scores.idxmax(axis=1)
    d["lane_confidence"] = scores.max(axis=1).replace(-999.0, 0.0).clip(lower=0.0)
    secondaries: list[str] = []
    for idx, row in scores.iterrows():
        secondaries.append(",".join([lane for lane, score in row.items() if score > 0.25 and lane != d.at[idx, "primary_lane"]]))
    d["secondary_lanes"] = secondaries
    d["lane_reason"] = d["primary_lane"].astype(str) + "_score_selected"
    return d


def apply_cycle_leadership_mask_to_lanes(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    d = frame.copy()
    mask = leadership_mask(d)
    d["cycle_leadership_mask_pass"] = mask.astype(bool)
    if "cyclical_recovery_lane_score" in d.columns:
        d["cyclical_recovery_lane_score_leader_masked"] = pd.to_numeric(
            d["cyclical_recovery_lane_score"], errors="coerce"
        ).fillna(0.0).where(mask, 0.0)
        d["cyclical_recovery_lane_score"] = d["cyclical_recovery_lane_score_leader_masked"]
        d = recompute_lane_selection(d)
    return d


def apply_concentrated_leader_gate_annotations(month: pd.DataFrame, portfolio_kind: str, target_n: int) -> pd.DataFrame:
    if month.empty or portfolio_kind != "concentrated":
        return month
    d = month.copy()
    if "leader_tier" not in d.columns:
        d["leader_tier"] = d.apply(classify_leader_tier, axis=1)
    allowed = concentrated_allowed_leader_tiers()
    leader_pass = d["leader_tier"].astype(str).isin(allowed)
    enabled = phase_is_enabled("leader_gate", default=False)
    min_pool = max(1, min(int(target_n), 3))
    relaxed = bool(enabled and int(leader_pass.sum()) < min_pool)
    d["concentrated_leader_gate_enabled"] = bool(enabled)
    d["concentrated_leader_gate_allowed_tiers"] = ",".join(sorted(allowed))
    d["concentrated_leader_gate_pass"] = leader_pass.astype(bool)
    d["concentrated_leader_gate_relaxed"] = relaxed
    return d


def add_concentrated_replacement_quality_features(frame: pd.DataFrame) -> pd.DataFrame:
    """Add PIT-only features used by the default-OFF replacement-quality hook.

    The feature recipe mirrors the stock-selection audit's ex-ante leader rank,
    but it is computed directly from the decision-date candidate rows. It does
    not read missed-leader artifacts or any forward-return labels.
    """
    if frame.empty:
        return frame
    d = frame.copy()
    if "revenue_growth" not in d.columns:
        revenue = pd.Series(float("nan"), index=d.index, dtype=float)
        for col in CONCENTRATED_REPLACEMENT_QUALITY_REVENUE_COLUMNS:
            if col not in d.columns:
                continue
            values = pd.to_numeric(d[col], errors="coerce")
            revenue = revenue.where(revenue.notna(), values)
        d["revenue_growth"] = revenue.fillna(0.0)

    rank_pieces: list[pd.Series] = []
    for col in CONCENTRATED_REPLACEMENT_QUALITY_SCORE_COLUMNS:
        if col not in d.columns:
            continue
        values = pd.to_numeric(d[col], errors="coerce")
        if values.notna().sum() <= 1:
            continue
        rank_pieces.append(values.rank(pct=True, ascending=True).fillna(0.0))
    if rank_pieces:
        d["replacement_quality_leader_score_ex_ante"] = pd.concat(rank_pieces, axis=1).mean(axis=1).fillna(0.0)
        d["leader_rank_ex_ante"] = (
            d["replacement_quality_leader_score_ex_ante"].rank(ascending=False, method="min").astype(int)
        )
        d["replacement_quality_leader_rank_components"] = ",".join(
            col for col in CONCENTRATED_REPLACEMENT_QUALITY_SCORE_COLUMNS if col in d.columns
        )
    else:
        d["replacement_quality_leader_score_ex_ante"] = 0.0
        d["leader_rank_ex_ante"] = len(d) + 1
        d["replacement_quality_leader_rank_components"] = ""
    return d


def score_month(month: pd.DataFrame) -> pd.DataFrame:
    d = score_candidate_lanes(month.copy())
    if "sector_leadership_score" not in d.columns:
        d = compute_sector_leadership_score(d)
    if "smart_money_evidence_confidence" not in d.columns:
        d = compute_smart_money_confirmation_score(d)
    if phase_is_enabled("cycle_leadership_mask", default=False):
        d = apply_cycle_leadership_mask_to_lanes(d)
    d["evidence_support_score"] = evidence_support_score(d)
    d["alphaops_vnext_score"] = alphaops_score(d)
    d["dual_leader_gate"] = (
        numeric(d, "rs_spy_3m").gt(0.0)
        & numeric(d, "rs_qqq_3m").gt(0.0)
        & (numeric(d, "rs_spy_6m").gt(0.0) | numeric(d, "rs_qqq_6m").gt(0.0))
    )
    if "leader_tier" not in d.columns:
        d["leader_tier"] = d.apply(classify_leader_tier, axis=1)
    d["negative_fcf_risk_cap"] = numeric(d, "emerging_tenbagger_risk_cap", 1.0)
    d = add_concentrated_replacement_quality_features(d)
    return d


def first_text(row: dict[str, Any] | pd.Series, columns: tuple[str, ...], default: str = "unknown") -> str:
    for col in columns:
        value = str(row.get(col) or "").strip()
        if value and value.lower() not in {"nan", "none"}:
            return value
    return default


def shakeout_guard_prod_enabled() -> bool:
    return bool(phase_is_enabled("shakeout_guard_prod", default=False))


def shakeout_guard_warning_suppress_enabled() -> bool:
    return bool(phase_is_enabled("shakeout_guard_warning_suppress", default=False))


def concentrated_score_sizing_reweight_enabled() -> bool:
    return bool(phase_is_enabled("concentrated_score_sizing_reweight", default=False))


def concentrated_score_sizing_signal() -> str:
    raw = os.environ.get("R1000_CONC_SCORE_SIZING_SIGNAL", "").strip()
    return raw or CONCENTRATED_SCORE_SIZING_REWEIGHT_SIGNAL


def concentrated_score_sizing_blend() -> float:
    raw = os.environ.get("R1000_CONC_SCORE_SIZING_BLEND", "")
    value = safe_float(raw, CONCENTRATED_SCORE_SIZING_REWEIGHT_BLEND)
    return float(max(0.0, min(1.0, value)))


def concentrated_score_sizing_rank_power() -> float:
    raw = os.environ.get("R1000_CONC_SCORE_SIZING_RANK_POWER", "")
    value = safe_float(raw, CONCENTRATED_SCORE_SIZING_REWEIGHT_RANK_POWER)
    return float(max(0.0, value))


def concentrated_score_sizing_cap_mode() -> str:
    raw = os.environ.get("R1000_CONC_SCORE_SIZING_CAP_MODE", "").strip()
    if raw and raw in CONCENTRATED_SCORE_SIZING_CAP_MODES:
        return raw
    return CONCENTRATED_SCORE_SIZING_REWEIGHT_CAP_MODE


def concentrated_score_sizing_single_cap() -> float:
    raw = os.environ.get("R1000_CONC_SCORE_SIZING_SINGLE_CAP", "")
    value = safe_float(raw, CONCENTRATED_SCORE_SIZING_REWEIGHT_SINGLE_CAP)
    return float(max(0.0, value))


def concentrated_replacement_quality_enabled() -> bool:
    return bool(phase_is_enabled("concentrated_replacement_quality", default=False))


def concentrated_replacement_quality_rank_max() -> int:
    raw = os.environ.get("R1000_CONC_REPLACEMENT_QUALITY_RANK_MAX", "")
    value = int(max(1, safe_float(raw, CONCENTRATED_REPLACEMENT_QUALITY_RANK_MAX)))
    return value


def concentrated_replacement_quality_revenue_growth_min() -> float:
    raw = os.environ.get("R1000_CONC_REPLACEMENT_QUALITY_MIN_REVENUE_GROWTH", "")
    value = safe_float(raw, CONCENTRATED_REPLACEMENT_QUALITY_REVENUE_GROWTH_MIN)
    return float(max(-1.0, value))


def concentrated_replacement_quality_max_swaps_per_date() -> int:
    raw = os.environ.get("R1000_CONC_REPLACEMENT_QUALITY_MAX_SWAPS_PER_DATE", "")
    value = int(max(0, safe_float(raw, CONCENTRATED_REPLACEMENT_QUALITY_MAX_SWAPS_PER_DATE)))
    return value


def ai_capex_momentum_tilt_enabled() -> bool:
    return bool(phase_is_enabled("ai_capex_momentum_tilt", default=False))


def ai_capex_momentum_tilt_strength() -> float:
    raw = os.environ.get("R1000_MAIN_AI_CAPEX_TILT_STRENGTH", "")
    value = safe_float(raw, AI_CAPEX_MOMENTUM_TILT_STRENGTH)
    return float(max(0.0, min(1.0, value)))


def main_fast_crash_hedge_enabled() -> bool:
    return bool(phase_is_enabled("main_fast_crash_hedge", default=False))


def main_fast_crash_hedge_ticker() -> str:
    return clean_ticker(os.environ.get("R1000_MAIN_FAST_CRASH_HEDGE_TICKER", MAIN_FAST_CRASH_HEDGE_TICKER))


def main_fast_crash_hedge_benchmark() -> str:
    return clean_ticker(os.environ.get("R1000_MAIN_FAST_CRASH_HEDGE_BENCHMARK", MAIN_FAST_CRASH_HEDGE_BENCHMARK))


def main_fast_crash_hedge_weight() -> float:
    raw = os.environ.get("R1000_MAIN_FAST_CRASH_HEDGE_WEIGHT", "")
    value = safe_float(raw, MAIN_FAST_CRASH_HEDGE_WEIGHT)
    return float(max(0.0, min(0.25, value)))


def main_fast_crash_risk_buffer_weight() -> float:
    raw = os.environ.get("R1000_MAIN_FAST_CRASH_RISK_BUFFER_WEIGHT", "")
    value = safe_float(raw, MAIN_FAST_CRASH_RISK_BUFFER_WEIGHT)
    return float(max(0.0, min(0.05, value)))


def concentrated_cashfunded_early_entry_enabled() -> bool:
    return bool(phase_is_enabled("concentrated_cashfunded_early_entry", default=False))


def concentrated_cashfunded_early_entry_signal() -> str:
    raw = os.environ.get("R1000_CONC_CASHFUNDED_EARLY_ENTRY_SIGNAL", "").strip()
    return raw or CONCENTRATED_CASHFUNDED_EARLY_ENTRY_SIGNAL


def concentrated_cashfunded_early_entry_add_weight() -> float:
    raw = os.environ.get("R1000_CONC_CASHFUNDED_EARLY_ENTRY_ADD_WEIGHT", "")
    value = safe_float(raw, CONCENTRATED_CASHFUNDED_EARLY_ENTRY_ADD_WEIGHT)
    return float(max(0.0, min(0.30, value)))


def concentrated_cashfunded_early_entry_min_breakout_quality() -> float:
    raw = os.environ.get("R1000_CONC_CASHFUNDED_EARLY_ENTRY_MIN_BREAKOUT_QUALITY", "")
    value = safe_float(raw, CONCENTRATED_CASHFUNDED_EARLY_ENTRY_MIN_BREAKOUT_QUALITY)
    return float(max(0.0, min(1.0, value)))


def concentrated_cashfunded_early_entry_allow_crisis_deployment() -> bool:
    raw = os.environ.get("R1000_CONC_CASHFUNDED_EARLY_ENTRY_ALLOW_CRISIS", "").strip().lower()
    return raw in {"1", "true", "yes", "on", "enabled"}


def validate_cashfunded_early_entry_signal(signal: str) -> None:
    name = str(signal or "").strip().lower()
    if not name:
        raise ValueError("cash-funded early-entry signal is blank")
    if name in FORBIDDEN_EARLY_ENTRY_SIGNAL_EXACT or any(
        pattern in name for pattern in FORBIDDEN_EARLY_ENTRY_SIGNAL_PATTERNS
    ):
        raise ValueError(f"cash-funded early-entry cannot use forward-return/audit-label signal: {signal}")


@dataclass(frozen=True)
class ShakeoutGuardDecision:
    enabled: bool
    evaluated: bool
    protected: bool
    applied: bool
    block_reason: str
    classifier_state: str
    classifier_reason: str
    fallback_source: str


def _is_present(value: Any) -> bool:
    try:
        missing = bool(pd.isna(value))
    except (TypeError, ValueError):
        missing = False
    blank_text = isinstance(value, str) and value.strip().lower() in {"", "nan", "none"}
    return not missing and not blank_text


def leader_state_row_with_fallbacks(row: dict[str, Any]) -> tuple[pd.Series, str]:
    state_row = dict(row)
    sources: list[str] = []
    for suffix in ("1m", "3m", "6m"):
        qqq_col = f"rs_qqq_{suffix}"
        value = state_row.get(qqq_col)
        if _is_present(value):
            sources.append("qqq_native")
            continue
        benchmark_value = state_row.get(f"rs_benchmark_{suffix}")
        if _is_present(benchmark_value):
            state_row[qqq_col] = benchmark_value
            sources.append("benchmark_fallback")
            continue
        spy_value = state_row.get(f"rs_spy_{suffix}")
        if _is_present(spy_value):
            state_row[qqq_col] = spy_value
            sources.append("spy_fallback")
            continue
        state_row[qqq_col] = 0.0
        sources.append("zero_fallback")
    if "zero_fallback" in sources:
        fallback_source = "zero_fallback"
    elif "spy_fallback" in sources:
        fallback_source = "spy_fallback"
    elif "benchmark_fallback" in sources:
        fallback_source = "benchmark_fallback"
    else:
        fallback_source = "qqq_native"
    return pd.Series(state_row), fallback_source


def crisis_state_blocks_shakeout_guard(row: dict[str, Any]) -> tuple[bool, str]:
    crisis_state = str(row.get("crisis_state") or "").strip().upper()
    if not crisis_state:
        return False, ""
    if crisis_state == "WATCH" or "CRISIS" in crisis_state or "DEFENSE" in crisis_state:
        return True, crisis_state
    return False, ""


def shakeout_guard_prod_decision(row: dict[str, Any], *, applied: bool = False) -> ShakeoutGuardDecision:
    """Protect only intact leaders from transient TRIM/WARNING state changes."""
    enabled = shakeout_guard_prod_enabled()
    if not enabled:
        return ShakeoutGuardDecision(enabled=False, evaluated=False, protected=False, applied=False, block_reason="disabled", classifier_state="", classifier_reason="", fallback_source="")
    ticker = clean_ticker(row.get("ticker"))
    if not ticker or ticker in CASH_TICKERS:
        return ShakeoutGuardDecision(enabled=True, evaluated=False, protected=False, applied=False, block_reason="cash_or_invalid", classifier_state="", classifier_reason="", fallback_source="")
    if not bool(row.get("shakeout_guard_prior_holding")):
        return ShakeoutGuardDecision(enabled=True, evaluated=False, protected=False, applied=False, block_reason="not_prior_holding", classifier_state="", classifier_reason="", fallback_source="")
    leader_tier = str(row.get("leader_tier") or "").upper()
    if leader_tier not in {"DUAL_LEADER", "SECTOR_LEADER"}:
        return ShakeoutGuardDecision(enabled=True, evaluated=False, protected=False, applied=False, block_reason=f"leader_tier_not_protected:{leader_tier or 'unknown'}", classifier_state="", classifier_reason="", fallback_source="")
    if safe_float(row.get("price_above_ma200"), 1.0) < 0.5:
        return ShakeoutGuardDecision(enabled=True, evaluated=False, protected=False, applied=False, block_reason="below_ma200", classifier_state="", classifier_reason="", fallback_source="")
    benchmark_3m = safe_float(row.get("rs_benchmark_3m"), safe_float(row.get("rs_qqq_3m"), 0.0))
    if benchmark_3m < 0.0:
        return ShakeoutGuardDecision(enabled=True, evaluated=False, protected=False, applied=False, block_reason="medium_relative_strength_negative", classifier_state="", classifier_reason="", fallback_source="")
    if max(safe_float(row.get("systemic_crisis_score")), safe_float(row.get("macro_risk_off_score"))) >= 0.65:
        return ShakeoutGuardDecision(enabled=True, evaluated=False, protected=False, applied=False, block_reason="macro_crisis_blocked", classifier_state="", classifier_reason="", fallback_source="")
    crisis_blocked, crisis_state = crisis_state_blocks_shakeout_guard(row)
    if crisis_blocked:
        return ShakeoutGuardDecision(enabled=True, evaluated=False, protected=False, applied=False, block_reason=f"crisis_state_blocked:{crisis_state}", classifier_state="", classifier_reason="", fallback_source="")
    leader_row, fallback_source = leader_state_row_with_fallbacks(row)
    state, reason = classify_leader_state(leader_row)
    if state == "SHAKEOUT_GUARD":
        return ShakeoutGuardDecision(enabled=True, evaluated=True, protected=True, applied=bool(applied), block_reason="applied" if applied else "", classifier_state=state, classifier_reason=reason, fallback_source=fallback_source)
    return ShakeoutGuardDecision(enabled=True, evaluated=True, protected=False, applied=False, block_reason=f"classifier_not_shakeout:{state}:{reason}", classifier_state=state, classifier_reason=reason, fallback_source=fallback_source)


def shakeout_guard_prod_telemetry(row: dict[str, Any], state_reason: str) -> dict[str, Any]:
    applied = str(state_reason).startswith("shakeout_guard_prod_suppressed_")
    decision = shakeout_guard_prod_decision(row, applied=applied)
    return {
        "shakeout_guard_prod_enabled": bool(decision.enabled),
        "shakeout_guard_prod_evaluated": bool(decision.evaluated),
        "shakeout_guard_prod_applied": bool(decision.applied),
        "shakeout_guard_prod_block_reason": decision.block_reason,
        "shakeout_guard_prod_classifier_state": decision.classifier_state,
        "shakeout_guard_prod_classifier_reason": decision.classifier_reason,
        "shakeout_guard_prod_fallback_source": decision.fallback_source,
        "shakeout_guard_prod_reason": state_reason if applied else "",
    }


def holding_state(row: dict[str, Any], score_median: float, score_sigma: float) -> tuple[str, str]:
    lane = str(row.get("primary_lane") or "")
    score = safe_float(row.get("alphaops_vnext_score"))
    hard_reject = str(row.get("emerging_tenbagger_hard_reject_reason") or "")
    price_alive = safe_float(row.get("price_above_ma200"), 1.0) + safe_float(row.get("price_above_ma50"), 1.0)
    if hard_reject or bool(row.get("top7_standalone_blocked")):
        return "EXIT", hard_reject or "top7_support_without_confirmation"
    if price_alive <= 0.0:
        return "EXIT", "price_trend_not_alive"
    shakeout_decision = shakeout_guard_prod_decision(row)
    if score < score_median - max(score_sigma, 0.25):
        if shakeout_decision.protected:
            return "HOLD", f"shakeout_guard_prod_suppressed_trim:{shakeout_decision.classifier_reason}"
        return "TRIM", "score_below_monthly_peer_band"
    if numeric(pd.DataFrame([row]), "rs_benchmark_1w").iloc[0] < 0 and numeric(pd.DataFrame([row]), "rs_benchmark_3m").iloc[0] < 0:
        if shakeout_guard_warning_suppress_enabled() and shakeout_decision.protected:
            return "HOLD", f"shakeout_guard_prod_suppressed_warning:{shakeout_decision.classifier_reason}"
        return "WARNING", "short_and_medium_relative_strength_negative"
    if lane == "EMERGING_TENBAGGER" and safe_float(row.get("negative_fcf_risk_cap"), 1.0) < 0.75:
        return "WARNING", "emerging_negative_fcf_or_dilution_risk_cap"
    return "HOLD", "vnext_score_and_risk_intact"


def leadership_persistence_hold_enabled() -> bool:
    return bool(phase_is_enabled("leadership_persistence_hold", default=False))


def leadership_persistence_hold_sigma_multiplier() -> float:
    raw = os.environ.get(LEADERSHIP_PERSISTENCE_HOLD_SIGMA_MULTIPLIER_ENV)
    value = safe_float(raw, LEADERSHIP_PERSISTENCE_HOLD_SIGMA_MULTIPLIER)
    if value <= 0:
        return float(LEADERSHIP_PERSISTENCE_HOLD_SIGMA_MULTIPLIER)
    return float(value)


def leadership_persistence_allowed_tiers(portfolio_kind: str) -> set[str]:
    if portfolio_kind == "concentrated":
        return set(LEADERSHIP_PERSISTENCE_CONCENTRATED_TIERS)
    return set(LEADERSHIP_PERSISTENCE_MAIN_TIERS)


def leadership_persistence_hold_protected(
    row: dict[str, Any],
    *,
    portfolio_kind: str,
) -> tuple[bool, str]:
    """Return whether a prior holding is a healthy leader worth extra patience.

    This is PIT-only: it uses the current rebalance row and prior weight already
    known to the policy replay.  It does not inspect forward returns.
    """
    ticker = clean_ticker(row.get("ticker"))
    if not ticker or ticker in CASH_TICKERS:
        return False, "cash_or_invalid"
    if str(row.get("holding_state") or "").upper() != "HOLD":
        return False, "not_healthy_hold"
    if str(row.get("hold_replace_decision") or "").lower() != "keep_prior_holding":
        return False, "not_prior_keep"
    if safe_float(row.get("prior_weight")) < LEADERSHIP_PERSISTENCE_HOLD_MIN_PRIOR_WEIGHT:
        return False, "prior_weight_below_floor"
    leader_tier = str(row.get("leader_tier") or "").upper()
    if leader_tier not in leadership_persistence_allowed_tiers(portfolio_kind):
        return False, f"leader_tier_not_protected:{leader_tier or 'unknown'}"
    if str(row.get("emerging_tenbagger_hard_reject_reason") or "") or bool(row.get("top7_standalone_blocked")):
        return False, "hard_reject_or_top7_standalone"
    if safe_float(row.get("price_above_ma200"), 1.0) + safe_float(row.get("price_above_ma50"), 1.0) <= 0.0:
        return False, "price_trend_not_alive"
    return True, "healthy_prior_leader"


def replacement_gap_for_weakest(
    weakest: dict[str, Any],
    *,
    portfolio_kind: str,
    threshold_normal: float,
    threshold_broken: float,
    score_sigma: float,
) -> tuple[float, str, bool]:
    weak_state = str(weakest.get("holding_state") or "").upper()
    if weak_state in {"WARNING", "TRIM"}:
        return float(threshold_broken), "broken_or_warning_holding", False
    if leadership_persistence_hold_enabled():
        protected, reason = leadership_persistence_hold_protected(weakest, portfolio_kind=portfolio_kind)
        if protected:
            gap = max(
                float(threshold_normal),
                LEADERSHIP_PERSISTENCE_HOLD_MIN_GAP,
                leadership_persistence_hold_sigma_multiplier() * max(float(score_sigma), 0.20),
            )
            return float(gap), reason, True
        return float(threshold_normal), reason, False
    return float(threshold_normal), "standard_hold_replace_threshold", False


def crisis_state_for_date(crisis_states: pd.DataFrame, dt: pd.Timestamp) -> dict[str, Any]:
    if crisis_states.empty or "date" not in crisis_states.columns:
        return {"crisis_state": "GREEN", "crisis_overlay_status": "missing"}
    d = crisis_states.copy()
    d["date"] = pd.to_datetime(d["date"], errors="coerce").dt.normalize()
    eligible = d[d["date"].le(dt.normalize())]
    if eligible.empty:
        return {"crisis_state": "GREEN", "crisis_overlay_status": "before_first_state"}
    row = eligible.sort_values("date").iloc[-1].to_dict()
    row["crisis_overlay_status"] = "applied"
    return row


def crisis_cash_target(state: str, portfolio_kind: str) -> float:
    base = float(CRISIS_SETTINGS.get(state, CRISIS_SETTINGS["GREEN"]).get("cash", 0.03))
    if portfolio_kind == "concentrated" and state == "CRISIS_DEFENSE":
        return max(base, 0.35)
    return min(max(base, 0.0), 0.50)


def crisis_new_buy_allowed(rec: dict[str, Any], state: str) -> tuple[bool, str]:
    setting = CRISIS_SETTINGS.get(state, CRISIS_SETTINGS["GREEN"])
    lane = str(rec.get("primary_lane") or "MARKET_LEADER")
    allowed_by_lane = setting.get("new_buy_allowed", {})
    allowed = bool(allowed_by_lane.get(lane, True))
    if allowed:
        return True, ""
    return False, f"crisis_new_buy_blocked_for_lane:{state}:{lane}"


def apply_crisis_lane_policy(month: pd.DataFrame, crisis_row: dict[str, Any], portfolio_kind: str) -> pd.DataFrame:
    if month.empty:
        return month
    state = str(crisis_row.get("crisis_state") or "GREEN")
    d = month.copy()
    multipliers: list[float] = []
    cut_scores: list[float] = []
    cut_reasons: list[str] = []
    buy_flags: list[bool] = []
    buy_reasons: list[str] = []
    for rec in d.to_dict("records"):
        lane = str(rec.get("primary_lane") or "MARKET_LEADER")
        mult, cut_score, cut_reason = defense_multiplier(rec, lane, state, portfolio_kind)
        allowed, reason = crisis_new_buy_allowed(rec, state)
        multipliers.append(float(mult))
        cut_scores.append(float(cut_score))
        cut_reasons.append(str(cut_reason))
        buy_flags.append(bool(allowed))
        buy_reasons.append(str(reason))
    d["crisis_state"] = state
    d["crisis_lane_weight_multiplier"] = multipliers
    d["crisis_defense_cut_score"] = cut_scores
    d["crisis_defense_cut_reason"] = cut_reasons
    d["crisis_new_buy_allowed"] = buy_flags
    d["crisis_new_buy_block_reason"] = buy_reasons
    d["alphaops_vnext_weight_score"] = (
        pd.to_numeric(d["alphaops_vnext_score"], errors="coerce").fillna(0.0)
        * pd.to_numeric(d["crisis_lane_weight_multiplier"], errors="coerce").fillna(1.0)
    )
    return d


def allowed_candidate(rec: dict[str, Any], portfolio_kind: str, emerging_count: int, *, is_new_buy: bool = False) -> tuple[bool, str]:
    ticker = clean_ticker(rec.get("ticker"))
    if not ticker or ticker in CASH_TICKERS:
        return False, "invalid_ticker"
    if str(rec.get("emerging_tenbagger_hard_reject_reason") or ""):
        return False, str(rec.get("emerging_tenbagger_hard_reject_reason"))
    if bool(rec.get("pit_evidence_blocked")) and max(
        safe_float(rec.get("rs_benchmark_1w")),
        safe_float(rec.get("rs_benchmark_3m")),
        safe_float(rec.get("rs_benchmark_6m")),
        safe_float(rec.get("theme_phase_multiplier_primary")),
        safe_float(rec.get("relative_strength_composite")),
    ) <= 0.05:
        return False, "pit_future_evidence_blocked_without_independent_confirmation"
    if bool(rec.get("top7_standalone_blocked")):
        return False, "top7_support_without_price_or_theme_confirmation"
    if is_new_buy and not bool(rec.get("crisis_new_buy_allowed", True)):
        return False, str(rec.get("crisis_new_buy_block_reason") or "crisis_new_buy_blocked_for_lane")
    lane = str(rec.get("primary_lane") or "")
    if portfolio_kind == "concentrated":
        if (
            bool(rec.get("concentrated_leader_gate_enabled", False))
            and not bool(rec.get("concentrated_leader_gate_relaxed", False))
            and not bool(rec.get("concentrated_leader_gate_pass", False))
        ):
            return False, f"concentrated_leader_gate:{rec.get('leader_tier') or 'unknown'}"
        if lane in {"EMERGING_TENBAGGER", "TOP7_MANAGER_DISCOVERY"}:
            if emerging_count >= 1:
                return False, "concentrated_emerging_or_top7_seat_cap"
        elif not bool(rec.get("dual_leader_gate")):
            return False, "concentrated_requires_dual_leader"
    return True, ""


def cap_group_key(row: dict[str, Any], kind: str) -> str:
    if kind == "theme":
        return first_text(row, ("leader_broad_theme", "theme_horizon_primary", "theme_phase_primary", "industry_group", "sector"))
    return first_text(row, ("leader_subindustry", "subindustry", "sub_industry", "industry_group", "industry", "sector"))


def target_caps(portfolio_kind: str) -> dict[str, float]:
    if portfolio_kind == "concentrated":
        return {"single": 0.30, "subindustry": 0.70, "theme": 1.0}
    return {"single": 0.12, "subindustry": 0.40, "theme": 0.60}


def risk_variant(portfolio_kind: str, target_n: int) -> MarketLeaderVariant:
    caps = target_caps(portfolio_kind)
    return MarketLeaderVariant(
        portfolio_kind=portfolio_kind,
        variant_id=f"alphaops_vnext_{portfolio_kind}_N{target_n}_benchmark_guard",
        target_n=int(target_n),
        single_cap=float(caps["single"]),
        subindustry_cap=float(caps["subindustry"]),
        theme_cap=float(caps["theme"]),
        risk_mode=RISK_MODE_BENCHMARK_GUARD,
    )


def assign_weights(selected: list[dict[str, Any]], portfolio_kind: str, cash_target: float) -> list[dict[str, Any]]:
    if not selected:
        return []
    caps = target_caps(portfolio_kind)
    gross = min(max(1.0 - cash_target, 0.0), 1.0)
    scores = pd.Series([safe_float(row.get("alphaops_vnext_weight_score"), safe_float(row.get("alphaops_vnext_score"))) for row in selected], dtype=float)
    raw = (scores - float(scores.min()) + 0.25).clip(lower=1e-6) ** 2
    raw = raw / max(float(raw.sum()), 1e-12) * gross
    weights = {clean_ticker(row.get("ticker")): min(float(raw.iloc[i]), caps["single"]) for i, row in enumerate(selected)}
    for _ in range(6):
        sub_totals: dict[str, float] = {}
        theme_totals: dict[str, float] = {}
        for row in selected:
            ticker = clean_ticker(row.get("ticker"))
            sub_totals[cap_group_key(row, "subindustry")] = sub_totals.get(cap_group_key(row, "subindustry"), 0.0) + weights.get(ticker, 0.0)
            theme_totals[cap_group_key(row, "theme")] = theme_totals.get(cap_group_key(row, "theme"), 0.0) + weights.get(ticker, 0.0)
        changed = False
        for row in selected:
            ticker = clean_ticker(row.get("ticker"))
            sub = cap_group_key(row, "subindustry")
            theme = cap_group_key(row, "theme")
            cap = min(caps["single"], max(0.0, weights[ticker] + caps["subindustry"] - sub_totals[sub]), max(0.0, weights[ticker] + caps["theme"] - theme_totals[theme]))
            if weights[ticker] > cap + 1e-12:
                weights[ticker] = cap
                changed = True
        residual = gross - sum(weights.values())
        if residual <= 1e-8:
            break
        rooms: list[tuple[str, float]] = []
        sub_totals = {}
        theme_totals = {}
        for row in selected:
            ticker = clean_ticker(row.get("ticker"))
            sub_totals[cap_group_key(row, "subindustry")] = sub_totals.get(cap_group_key(row, "subindustry"), 0.0) + weights.get(ticker, 0.0)
            theme_totals[cap_group_key(row, "theme")] = theme_totals.get(cap_group_key(row, "theme"), 0.0) + weights.get(ticker, 0.0)
        for row in selected:
            ticker = clean_ticker(row.get("ticker"))
            sub = cap_group_key(row, "subindustry")
            theme = cap_group_key(row, "theme")
            room = min(caps["single"] - weights[ticker], caps["subindustry"] - sub_totals[sub], caps["theme"] - theme_totals[theme])
            if room > 1e-9:
                rooms.append((ticker, room))
        if not rooms or not changed and residual < 1e-6:
            break
        add_each = residual / max(len(rooms), 1)
        for ticker, room in rooms:
            weights[ticker] += min(room, add_each)
    out: list[dict[str, Any]] = []
    for row in selected:
        ticker = clean_ticker(row.get("ticker"))
        weight = max(0.0, weights.get(ticker, 0.0))
        if weight <= 1e-12:
            continue
        item = dict(row)
        item["weight"] = weight
        item["target_weight"] = weight
        item["effective_single_weight_cap"] = caps["single"]
        item["subindustry_cap"] = caps["subindustry"]
        item["theme_cap"] = caps["theme"]
        item["weighting_score"] = safe_float(item.get("alphaops_vnext_weight_score"), safe_float(item.get("alphaops_vnext_score")))
        out.append(item)
    return out


def apply_vnext_benchmark_guard(
    weighted: list[dict[str, Any]],
    *,
    portfolio_kind: str,
    target_n: int,
    prices: dict[str, pd.DataFrame],
    rebalance_date: pd.Timestamp,
) -> list[dict[str, Any]]:
    if not weighted:
        return weighted
    frame = pd.DataFrame(weighted)
    if frame.empty:
        return weighted
    guarded = apply_benchmark_risk_overlay(
        frame,
        risk_variant(portfolio_kind, target_n),
        prices,
        rebalance_date,
    )
    if guarded.empty:
        return weighted
    guarded["benchmark_guard_overlay_status"] = "applied"
    return guarded.to_dict("records")


def apply_concentrated_risk_state_new_entry_cap(
    weighted: list[dict[str, Any]],
    portfolio_kind: str,
) -> list[dict[str, Any]]:
    if portfolio_kind != "concentrated" or not weighted:
        return weighted
    capped: list[dict[str, Any]] = []
    for rec in weighted:
        item = dict(rec)
        ticker = clean_ticker(item.get("ticker"))
        state = str(item.get("crisis_state") or "").upper()
        holding_state_text = str(item.get("holding_state") or "").upper()
        replace_decision = str(item.get("hold_replace_decision") or "")
        is_new_entry = holding_state_text == "NEW" or replace_decision == "new_entry"
        weight = safe_float(item.get("weight"))
        if (
            ticker not in CASH_TICKERS
            and state in CONCENTRATED_RISK_STATE_CAP_STATES
            and is_new_entry
            and weight > CONCENTRATED_RISK_STATE_NEW_ENTRY_CAP
        ):
            item["pre_risk_state_new_entry_cap_weight"] = weight
            item["weight"] = CONCENTRATED_RISK_STATE_NEW_ENTRY_CAP
            item["target_weight"] = CONCENTRATED_RISK_STATE_NEW_ENTRY_CAP
            item["risk_state_new_entry_cap"] = CONCENTRATED_RISK_STATE_NEW_ENTRY_CAP
            item["risk_state_new_entry_cap_status"] = "applied"
            item["selection_reason"] = str(item.get("selection_reason") or item.get("primary_lane") or "alphaops_vnext_score") + "|risk_state_new_entry_cap"
        else:
            item["risk_state_new_entry_cap_status"] = "not_applicable"
        capped.append(item)
    return capped


def apply_main_high_volatility_new_entry_cap(
    weighted: list[dict[str, Any]],
    portfolio_kind: str,
) -> list[dict[str, Any]]:
    if portfolio_kind != "main" or not weighted:
        return weighted
    capped: list[dict[str, Any]] = []
    for rec in weighted:
        item = dict(rec)
        ticker = clean_ticker(item.get("ticker"))
        lane = str(item.get("primary_lane") or "").upper()
        holding_state_text = str(item.get("holding_state") or "").upper()
        replace_decision = str(item.get("hold_replace_decision") or "")
        is_new_entry = holding_state_text == "NEW" or replace_decision == "new_entry"
        weight = safe_float(item.get("weight"))
        atr14 = safe_float(item.get("atr14_pct"))
        crisis_state = str(item.get("crisis_state") or "").upper()
        style_regime = str(item.get("market_style_regime_label") or "")
        confirmation = safe_float(item.get("selection_confirmation_score"), 0.0)
        score = max(safe_float(item.get("alphaops_vnext_score")), safe_float(item.get("score")))
        sec_evidence = safe_float(item.get("sec_combined_evidence_score"))
        rs_benchmark_1m = safe_float(item.get("rs_benchmark_1m"), -1.0)
        high_conviction_stable_leader = (
            crisis_state == "GREEN"
            and style_regime == "quality_compounder"
            and confirmation >= 1.0
            and score >= MAIN_HIGH_VOL_EXEMPT_SCORE_THRESHOLD
            and sec_evidence >= MAIN_HIGH_VOL_EXEMPT_SEC_THRESHOLD
            and atr14 <= MAIN_HIGH_VOL_EXEMPT_ATR_MAX
            and rs_benchmark_1m >= MAIN_HIGH_VOL_EXEMPT_RS_1M_MIN
        )
        should_cap = (
            ticker not in CASH_TICKERS
            and lane in MAIN_HIGH_VOL_NEW_ENTRY_LANES
            and is_new_entry
            and atr14 >= MAIN_HIGH_VOL_NEW_ENTRY_ATR_THRESHOLD
            and weight > MAIN_HIGH_VOL_NEW_ENTRY_CAP
        )
        if should_cap and not high_conviction_stable_leader:
            item["pre_main_high_vol_new_entry_cap_weight"] = weight
            item["weight"] = MAIN_HIGH_VOL_NEW_ENTRY_CAP
            item["target_weight"] = MAIN_HIGH_VOL_NEW_ENTRY_CAP
            item["main_high_vol_new_entry_cap"] = MAIN_HIGH_VOL_NEW_ENTRY_CAP
            item["main_high_vol_new_entry_cap_status"] = "applied"
            item["selection_reason"] = (
                str(item.get("selection_reason") or item.get("primary_lane") or "alphaops_vnext_score")
                + "|main_high_vol_new_entry_cap"
            )
        elif should_cap and high_conviction_stable_leader:
            item["main_high_vol_new_entry_cap_status"] = "exempt_high_conviction_stable_leader"
        else:
            item["main_high_vol_new_entry_cap_status"] = "not_applicable"
        capped.append(item)
    return capped


def apply_main_watch_unconfirmed_market_leader_new_entry_cap(
    weighted: list[dict[str, Any]],
    portfolio_kind: str,
) -> list[dict[str, Any]]:
    if portfolio_kind != "main" or not weighted:
        return weighted
    capped: list[dict[str, Any]] = []
    for rec in weighted:
        item = dict(rec)
        ticker = clean_ticker(item.get("ticker"))
        lane = str(item.get("primary_lane") or "").upper()
        holding_state_text = str(item.get("holding_state") or "").upper()
        replace_decision = str(item.get("hold_replace_decision") or "")
        is_new_entry = holding_state_text == "NEW" or replace_decision == "new_entry"
        crisis_state = str(item.get("crisis_state") or "").upper()
        style_regime = str(item.get("market_style_regime_label") or "")
        capacity_regime = str(item.get("regime_capacity_regime") or item.get("regime_state") or "")
        confirmation = safe_float(item.get("selection_confirmation_score"), 1.0)
        weight = safe_float(item.get("weight"))
        if (
            ticker not in CASH_TICKERS
            and lane in MAIN_HIGH_VOL_NEW_ENTRY_LANES
            and is_new_entry
            and crisis_state in CONCENTRATED_RISK_STATE_CAP_STATES
            and style_regime == "quality_compounder"
            and capacity_regime == "neutral"
            and confirmation < MAIN_WATCH_UNCONFIRMED_ML_CONFIRMATION_THRESHOLD
            and weight > MAIN_WATCH_UNCONFIRMED_ML_NEW_ENTRY_CAP
        ):
            item["pre_main_watch_unconfirmed_ml_new_entry_cap_weight"] = weight
            item["weight"] = MAIN_WATCH_UNCONFIRMED_ML_NEW_ENTRY_CAP
            item["target_weight"] = MAIN_WATCH_UNCONFIRMED_ML_NEW_ENTRY_CAP
            item["main_watch_unconfirmed_ml_new_entry_cap"] = MAIN_WATCH_UNCONFIRMED_ML_NEW_ENTRY_CAP
            item["main_watch_unconfirmed_ml_new_entry_cap_status"] = "applied"
            item["selection_reason"] = (
                str(item.get("selection_reason") or item.get("primary_lane") or "alphaops_vnext_score")
                + "|main_watch_unconfirmed_ml_new_entry_cap"
            )
        else:
            item["main_watch_unconfirmed_ml_new_entry_cap_status"] = "not_applicable"
        capped.append(item)
    return capped


def apply_main_green_bull_low_confirm_high_vol_new_entry_cap(
    weighted: list[dict[str, Any]],
    portfolio_kind: str,
) -> list[dict[str, Any]]:
    if portfolio_kind != "main" or not weighted:
        return weighted
    capped: list[dict[str, Any]] = []
    for rec in weighted:
        item = dict(rec)
        ticker = clean_ticker(item.get("ticker"))
        lane = str(item.get("primary_lane") or "").upper()
        holding_state_text = str(item.get("holding_state") or "").upper()
        replace_decision = str(item.get("hold_replace_decision") or "")
        is_new_entry = holding_state_text == "NEW" or replace_decision == "new_entry"
        crisis_state = str(item.get("crisis_state") or "").upper()
        capacity_regime = str(item.get("regime_capacity_regime") or item.get("regime_state") or "")
        confirmation = safe_float(item.get("selection_confirmation_score"), 1.0)
        atr14 = safe_float(item.get("atr14_pct"))
        weight = safe_float(item.get("weight"))
        if (
            ticker not in CASH_TICKERS
            and lane == "MARKET_LEADER"
            and is_new_entry
            and crisis_state == "GREEN"
            and capacity_regime == "bull"
            and confirmation < MAIN_GREEN_BULL_LOW_CONFIRM_CONFIRMATION_THRESHOLD
            and atr14 >= MAIN_GREEN_BULL_LOW_CONFIRM_HIGH_VOL_ATR_THRESHOLD
            and weight > MAIN_GREEN_BULL_LOW_CONFIRM_HIGH_VOL_NEW_ENTRY_CAP
        ):
            item["pre_main_green_bull_low_confirm_high_vol_new_entry_cap_weight"] = weight
            item["weight"] = MAIN_GREEN_BULL_LOW_CONFIRM_HIGH_VOL_NEW_ENTRY_CAP
            item["target_weight"] = MAIN_GREEN_BULL_LOW_CONFIRM_HIGH_VOL_NEW_ENTRY_CAP
            item["main_green_bull_low_confirm_high_vol_new_entry_cap"] = (
                MAIN_GREEN_BULL_LOW_CONFIRM_HIGH_VOL_NEW_ENTRY_CAP
            )
            item["main_green_bull_low_confirm_high_vol_new_entry_cap_status"] = "applied"
            item["selection_reason"] = (
                str(item.get("selection_reason") or item.get("primary_lane") or "alphaops_vnext_score")
                + "|main_green_bull_low_confirm_high_vol_new_entry_cap"
            )
        else:
            item["main_green_bull_low_confirm_high_vol_new_entry_cap_status"] = "not_applicable"
        capped.append(item)
    return capped


def apply_main_balanced_bull_qqq_damage_low_confirm_leader_cap(
    weighted: list[dict[str, Any]],
    portfolio_kind: str,
) -> list[dict[str, Any]]:
    if portfolio_kind != "main" or not weighted:
        return weighted
    capped: list[dict[str, Any]] = []
    for rec in weighted:
        item = dict(rec)
        ticker = clean_ticker(item.get("ticker"))
        lane = str(item.get("primary_lane") or "").upper()
        holding_state_text = str(item.get("holding_state") or "").upper()
        replace_decision = str(item.get("hold_replace_decision") or "")
        is_position = holding_state_text in {"NEW", "HOLD"} or replace_decision in {
            "new_entry",
            "keep_prior_holding",
        }
        crisis_state = str(item.get("crisis_state") or "").upper()
        style_regime = str(item.get("market_style_regime_label") or "")
        capacity_regime = str(item.get("regime_capacity_regime") or item.get("regime_state") or "")
        sector = str(item.get("sector") or "")
        confirmation = safe_float(item.get("selection_confirmation_score"), 1.0)
        volatility_contraction = safe_float(item.get("volatility_contraction_score"))
        spy_1m_return = safe_float(item.get("spy_1m_return"), math.nan)
        qqq_1m_return = safe_float(item.get("qqq_1m_return"), math.nan)
        weight = safe_float(item.get("weight"))
        if (
            ticker not in CASH_TICKERS
            and lane == "MARKET_LEADER"
            and is_position
            and crisis_state == "GREEN"
            and style_regime == "balanced"
            and capacity_regime == "bull"
            and sector in MAIN_BALANCED_BULL_QQQ_DAMAGE_SECTORS
            and confirmation < MAIN_BALANCED_BULL_QQQ_DAMAGE_CONFIRMATION_THRESHOLD
            and volatility_contraction < 0.0
            and math.isfinite(spy_1m_return)
            and math.isfinite(qqq_1m_return)
            and qqq_1m_return < spy_1m_return
            and weight > MAIN_BALANCED_BULL_QQQ_DAMAGE_MIN_WEIGHT
            and weight > MAIN_BALANCED_BULL_QQQ_DAMAGE_LOW_CONFIRM_LEADER_CAP
        ):
            item["pre_main_balanced_bull_qqq_damage_low_confirm_leader_cap_weight"] = weight
            item["weight"] = MAIN_BALANCED_BULL_QQQ_DAMAGE_LOW_CONFIRM_LEADER_CAP
            item["target_weight"] = MAIN_BALANCED_BULL_QQQ_DAMAGE_LOW_CONFIRM_LEADER_CAP
            item["main_balanced_bull_qqq_damage_low_confirm_leader_cap"] = (
                MAIN_BALANCED_BULL_QQQ_DAMAGE_LOW_CONFIRM_LEADER_CAP
            )
            item["main_balanced_bull_qqq_damage_low_confirm_leader_cap_status"] = "applied"
            item["selection_reason"] = (
                str(item.get("selection_reason") or item.get("primary_lane") or "alphaops_vnext_score")
                + "|main_balanced_bull_qqq_damage_low_confirm_leader_cap"
            )
        else:
            item["main_balanced_bull_qqq_damage_low_confirm_leader_cap_status"] = "not_applicable"
        capped.append(item)
    return capped


def apply_main_balanced_neutral_soft_qqq_damage_weak_leader_cap(
    weighted: list[dict[str, Any]],
    portfolio_kind: str,
) -> list[dict[str, Any]]:
    if portfolio_kind != "main" or not weighted:
        return weighted
    capped: list[dict[str, Any]] = []
    for rec in weighted:
        item = dict(rec)
        ticker = clean_ticker(item.get("ticker"))
        lane = str(item.get("primary_lane") or "").upper()
        holding_state_text = str(item.get("holding_state") or "").upper()
        replace_decision = str(item.get("hold_replace_decision") or "")
        is_position = holding_state_text in {"NEW", "HOLD"} or replace_decision in {
            "new_entry",
            "keep_prior_holding",
        }
        crisis_state = str(item.get("crisis_state") or "").upper()
        style_regime = str(item.get("market_style_regime_label") or "")
        capacity_regime = str(item.get("regime_capacity_regime") or item.get("regime_state") or "")
        confirmation = safe_float(item.get("selection_confirmation_score"), 1.0)
        breakout_quality = safe_float(item.get("breakout_setup_quality_score"), 1.0)
        spy_1m_return = safe_float(item.get("spy_1m_return"), math.nan)
        qqq_1m_return = safe_float(item.get("qqq_1m_return"), math.nan)
        weight = safe_float(item.get("weight"))
        weak_quality = (
            confirmation < MAIN_BALANCED_NEUTRAL_SOFT_QQQ_DAMAGE_CONFIRMATION_THRESHOLD
            or breakout_quality < MAIN_BALANCED_NEUTRAL_SOFT_QQQ_DAMAGE_BREAKOUT_QUALITY_THRESHOLD
        )
        soft_q_damage = (
            math.isfinite(spy_1m_return)
            and math.isfinite(qqq_1m_return)
            and qqq_1m_return > 0.0
            and qqq_1m_return < spy_1m_return
            and spy_1m_return < MAIN_BALANCED_NEUTRAL_SOFT_QQQ_DAMAGE_SPY_MAX_RETURN
        )
        if (
            ticker not in CASH_TICKERS
            and lane == "MARKET_LEADER"
            and is_position
            and crisis_state == "GREEN"
            and style_regime == "balanced"
            and capacity_regime == "neutral"
            and weak_quality
            and soft_q_damage
            and weight > MAIN_BALANCED_NEUTRAL_SOFT_QQQ_DAMAGE_MIN_WEIGHT
            and weight > MAIN_BALANCED_NEUTRAL_SOFT_QQQ_DAMAGE_WEAK_LEADER_CAP
        ):
            item["pre_main_balanced_neutral_soft_qqq_damage_weak_leader_cap_weight"] = weight
            item["weight"] = MAIN_BALANCED_NEUTRAL_SOFT_QQQ_DAMAGE_WEAK_LEADER_CAP
            item["target_weight"] = MAIN_BALANCED_NEUTRAL_SOFT_QQQ_DAMAGE_WEAK_LEADER_CAP
            item["main_balanced_neutral_soft_qqq_damage_weak_leader_cap"] = (
                MAIN_BALANCED_NEUTRAL_SOFT_QQQ_DAMAGE_WEAK_LEADER_CAP
            )
            item["main_balanced_neutral_soft_qqq_damage_weak_leader_cap_status"] = "applied"
            item["selection_reason"] = (
                str(item.get("selection_reason") or item.get("primary_lane") or "alphaops_vnext_score")
                + "|main_balanced_neutral_soft_qqq_damage_weak_leader_cap"
            )
        else:
            item["main_balanced_neutral_soft_qqq_damage_weak_leader_cap_status"] = "not_applicable"
        capped.append(item)
    return capped


def apply_main_quality_bull_low_confirm_new_entry_cap(
    weighted: list[dict[str, Any]],
    portfolio_kind: str,
) -> list[dict[str, Any]]:
    if portfolio_kind != "main" or not weighted:
        return weighted
    capped: list[dict[str, Any]] = []
    for rec in weighted:
        item = dict(rec)
        ticker = clean_ticker(item.get("ticker"))
        holding_state_text = str(item.get("holding_state") or "").upper()
        replace_decision = str(item.get("hold_replace_decision") or "")
        is_new_entry = holding_state_text == "NEW" or replace_decision == "new_entry"
        crisis_state = str(item.get("crisis_state") or "").upper()
        style_regime = str(item.get("market_style_regime_label") or "")
        capacity_regime = str(item.get("regime_capacity_regime") or item.get("regime_state") or "")
        confirmation = safe_float(item.get("selection_confirmation_score"), 1.0)
        weight = safe_float(item.get("weight"))
        if (
            ticker not in CASH_TICKERS
            and is_new_entry
            and crisis_state == "GREEN"
            and style_regime == "quality_compounder"
            and capacity_regime == "bull"
            and confirmation < MAIN_QUALITY_BULL_LOW_CONFIRM_CONFIRMATION_THRESHOLD
            and weight > MAIN_QUALITY_BULL_LOW_CONFIRM_NEW_ENTRY_CAP
        ):
            item["pre_main_quality_bull_low_confirm_new_entry_cap_weight"] = weight
            item["weight"] = MAIN_QUALITY_BULL_LOW_CONFIRM_NEW_ENTRY_CAP
            item["target_weight"] = MAIN_QUALITY_BULL_LOW_CONFIRM_NEW_ENTRY_CAP
            item["main_quality_bull_low_confirm_new_entry_cap"] = (
                MAIN_QUALITY_BULL_LOW_CONFIRM_NEW_ENTRY_CAP
            )
            item["main_quality_bull_low_confirm_new_entry_cap_status"] = "applied"
            item["selection_reason"] = (
                str(item.get("selection_reason") or item.get("primary_lane") or "alphaops_vnext_score")
                + "|main_quality_bull_low_confirm_new_entry_cap"
            )
        else:
            item["main_quality_bull_low_confirm_new_entry_cap_status"] = "not_applicable"
        capped.append(item)
    return capped


def apply_main_green_neutral_cyclical_high_vol_new_entry_cap(
    weighted: list[dict[str, Any]],
    portfolio_kind: str,
) -> list[dict[str, Any]]:
    if portfolio_kind != "main" or not weighted:
        return weighted
    capped: list[dict[str, Any]] = []
    for rec in weighted:
        item = dict(rec)
        ticker = clean_ticker(item.get("ticker"))
        lane = str(item.get("primary_lane") or "").upper()
        holding_state_text = str(item.get("holding_state") or "").upper()
        replace_decision = str(item.get("hold_replace_decision") or "")
        is_new_entry = holding_state_text == "NEW" or replace_decision == "new_entry"
        crisis_state = str(item.get("crisis_state") or "").upper()
        capacity_regime = str(item.get("regime_capacity_regime") or item.get("regime_state") or "")
        sector = str(item.get("sector") or "")
        atr14 = safe_float(item.get("atr14_pct"))
        weight = safe_float(item.get("weight"))
        if (
            ticker not in CASH_TICKERS
            and lane == "MARKET_LEADER"
            and is_new_entry
            and crisis_state == "GREEN"
            and capacity_regime == "neutral"
            and sector in MAIN_GREEN_NEUTRAL_CYCLICAL_HIGH_VOL_SECTORS
            and atr14 >= MAIN_GREEN_NEUTRAL_CYCLICAL_HIGH_VOL_ATR_THRESHOLD
            and weight > MAIN_GREEN_NEUTRAL_CYCLICAL_HIGH_VOL_NEW_ENTRY_CAP
        ):
            item["pre_main_green_neutral_cyclical_high_vol_new_entry_cap_weight"] = weight
            item["weight"] = MAIN_GREEN_NEUTRAL_CYCLICAL_HIGH_VOL_NEW_ENTRY_CAP
            item["target_weight"] = MAIN_GREEN_NEUTRAL_CYCLICAL_HIGH_VOL_NEW_ENTRY_CAP
            item["main_green_neutral_cyclical_high_vol_new_entry_cap"] = (
                MAIN_GREEN_NEUTRAL_CYCLICAL_HIGH_VOL_NEW_ENTRY_CAP
            )
            item["main_green_neutral_cyclical_high_vol_new_entry_cap_status"] = "applied"
            item["selection_reason"] = (
                str(item.get("selection_reason") or item.get("primary_lane") or "alphaops_vnext_score")
                + "|main_green_neutral_cyclical_high_vol_new_entry_cap"
            )
        else:
            item["main_green_neutral_cyclical_high_vol_new_entry_cap_status"] = "not_applicable"
        capped.append(item)
    return capped


def apply_main_quality_hold_weak_timing_trim(
    weighted: list[dict[str, Any]],
    portfolio_kind: str,
) -> list[dict[str, Any]]:
    if portfolio_kind != "main" or not weighted:
        return weighted
    trimmed: list[dict[str, Any]] = []
    for rec in weighted:
        item = dict(rec)
        ticker = clean_ticker(item.get("ticker"))
        holding_state_text = str(item.get("holding_state") or "").upper()
        replace_decision = str(item.get("hold_replace_decision") or "")
        is_hold = holding_state_text == "HOLD" or replace_decision == "keep_prior_holding"
        style_regime = str(item.get("market_style_regime_label") or "")
        capacity_regime = str(item.get("regime_capacity_regime") or item.get("regime_state") or "")
        confirmation = safe_float(item.get("selection_confirmation_score"), 1.0)
        rs_benchmark_1m = safe_float(item.get("rs_benchmark_1m"), 1.0)
        weak_timing = (
            confirmation < MAIN_QUALITY_HOLD_CONFIRMATION_THRESHOLD
            or rs_benchmark_1m < MAIN_QUALITY_HOLD_RS_1M_THRESHOLD
        )
        weight = safe_float(item.get("weight"))
        if (
            ticker not in CASH_TICKERS
            and is_hold
            and style_regime == "quality_compounder"
            and capacity_regime == "bull"
            and weak_timing
            and weight > MAIN_QUALITY_HOLD_WEAK_TIMING_CAP
        ):
            item["pre_main_quality_hold_weak_timing_trim_weight"] = weight
            item["weight"] = MAIN_QUALITY_HOLD_WEAK_TIMING_CAP
            item["target_weight"] = MAIN_QUALITY_HOLD_WEAK_TIMING_CAP
            item["main_quality_hold_weak_timing_trim_cap"] = MAIN_QUALITY_HOLD_WEAK_TIMING_CAP
            item["main_quality_hold_weak_timing_trim_status"] = "applied"
            item["selection_reason"] = (
                str(item.get("selection_reason") or item.get("primary_lane") or "alphaops_vnext_score")
                + "|main_quality_hold_weak_timing_trim"
            )
        else:
            item["main_quality_hold_weak_timing_trim_status"] = "not_applicable"
        trimmed.append(item)
    return trimmed


def apply_concentrated_hold_decay_trim(
    weighted: list[dict[str, Any]],
    portfolio_kind: str,
) -> list[dict[str, Any]]:
    if portfolio_kind != "concentrated" or not weighted:
        return weighted
    trimmed: list[dict[str, Any]] = []
    for rec in weighted:
        item = dict(rec)
        ticker = clean_ticker(item.get("ticker"))
        holding_state_text = str(item.get("holding_state") or "").upper()
        replace_decision = str(item.get("hold_replace_decision") or "")
        is_hold = holding_state_text == "HOLD" or replace_decision == "keep_prior_holding"
        ticker_ret_1m = safe_float(item.get("ticker_ret_1m"))
        rs_benchmark_1m = safe_float(item.get("rs_benchmark_1m"))
        is_decay = ticker_ret_1m < 0.0 or rs_benchmark_1m < 0.0
        weight = safe_float(item.get("weight"))
        if ticker not in CASH_TICKERS and is_hold and is_decay and weight > CONCENTRATED_HOLD_DECAY_CAP:
            item["pre_concentrated_hold_decay_trim_weight"] = weight
            item["weight"] = CONCENTRATED_HOLD_DECAY_CAP
            item["target_weight"] = CONCENTRATED_HOLD_DECAY_CAP
            item["concentrated_hold_decay_trim_cap"] = CONCENTRATED_HOLD_DECAY_CAP
            item["concentrated_hold_decay_trim_status"] = "applied"
            item["selection_reason"] = (
                str(item.get("selection_reason") or item.get("primary_lane") or "alphaops_vnext_score")
                + "|concentrated_hold_decay_trim"
            )
        else:
            item["concentrated_hold_decay_trim_status"] = "not_applicable"
        trimmed.append(item)
    return trimmed


def apply_concentrated_watch_unconfirmed_high_vol_new_entry_cap(
    weighted: list[dict[str, Any]],
    portfolio_kind: str,
) -> list[dict[str, Any]]:
    if portfolio_kind != "concentrated" or not weighted:
        return weighted
    capped: list[dict[str, Any]] = []
    for rec in weighted:
        item = dict(rec)
        ticker = clean_ticker(item.get("ticker"))
        holding_state_text = str(item.get("holding_state") or "").upper()
        replace_decision = str(item.get("hold_replace_decision") or "")
        is_new_entry = holding_state_text == "NEW" or replace_decision == "new_entry"
        crisis_state = str(item.get("crisis_state") or "").upper()
        style_regime = str(item.get("market_style_regime_label") or "")
        capacity_regime = str(item.get("regime_capacity_regime") or item.get("regime_state") or "")
        confirmation = safe_float(item.get("selection_confirmation_score"), 1.0)
        atr14 = safe_float(item.get("atr14_pct"))
        weight = safe_float(item.get("weight"))
        if (
            ticker not in CASH_TICKERS
            and is_new_entry
            and crisis_state in CONCENTRATED_RISK_STATE_CAP_STATES
            and style_regime == "quality_compounder"
            and capacity_regime == "neutral"
            and confirmation < CONCENTRATED_WATCH_UNCONFIRMED_CONFIRMATION_THRESHOLD
            and atr14 >= CONCENTRATED_WATCH_UNCONFIRMED_HIGH_VOL_ATR_THRESHOLD
            and weight > CONCENTRATED_WATCH_UNCONFIRMED_HIGH_VOL_NEW_ENTRY_CAP
        ):
            item["pre_concentrated_watch_unconfirmed_high_vol_new_entry_cap_weight"] = weight
            item["weight"] = CONCENTRATED_WATCH_UNCONFIRMED_HIGH_VOL_NEW_ENTRY_CAP
            item["target_weight"] = CONCENTRATED_WATCH_UNCONFIRMED_HIGH_VOL_NEW_ENTRY_CAP
            item["concentrated_watch_unconfirmed_high_vol_new_entry_cap"] = CONCENTRATED_WATCH_UNCONFIRMED_HIGH_VOL_NEW_ENTRY_CAP
            item["concentrated_watch_unconfirmed_high_vol_new_entry_cap_status"] = "applied"
            item["selection_reason"] = (
                str(item.get("selection_reason") or item.get("primary_lane") or "alphaops_vnext_score")
                + "|concentrated_watch_unconfirmed_high_vol_new_entry_cap"
            )
        else:
            item["concentrated_watch_unconfirmed_high_vol_new_entry_cap_status"] = "not_applicable"
        capped.append(item)
    return capped


def apply_concentrated_watch_unconfirmed_market_leader_new_entry_cap(
    weighted: list[dict[str, Any]],
    portfolio_kind: str,
) -> list[dict[str, Any]]:
    if portfolio_kind != "concentrated" or not weighted:
        return weighted
    capped: list[dict[str, Any]] = []
    for rec in weighted:
        item = dict(rec)
        ticker = clean_ticker(item.get("ticker"))
        lane = str(item.get("primary_lane") or "").upper()
        holding_state_text = str(item.get("holding_state") or "").upper()
        replace_decision = str(item.get("hold_replace_decision") or "")
        is_new_entry = holding_state_text == "NEW" or replace_decision == "new_entry"
        crisis_state = str(item.get("crisis_state") or "").upper()
        style_regime = str(item.get("market_style_regime_label") or "")
        capacity_regime = str(item.get("regime_capacity_regime") or item.get("regime_state") or "")
        confirmation = safe_float(item.get("selection_confirmation_score"), 1.0)
        weight = safe_float(item.get("weight"))
        if (
            ticker not in CASH_TICKERS
            and lane == "MARKET_LEADER"
            and is_new_entry
            and crisis_state in CONCENTRATED_RISK_STATE_CAP_STATES
            and style_regime == "quality_compounder"
            and capacity_regime == "neutral"
            and confirmation < CONCENTRATED_WATCH_UNCONFIRMED_ML_CONFIRMATION_THRESHOLD
            and weight > CONCENTRATED_WATCH_UNCONFIRMED_ML_NEW_ENTRY_CAP
        ):
            item["pre_concentrated_watch_unconfirmed_ml_new_entry_cap_weight"] = weight
            item["weight"] = CONCENTRATED_WATCH_UNCONFIRMED_ML_NEW_ENTRY_CAP
            item["target_weight"] = CONCENTRATED_WATCH_UNCONFIRMED_ML_NEW_ENTRY_CAP
            item["concentrated_watch_unconfirmed_ml_new_entry_cap"] = CONCENTRATED_WATCH_UNCONFIRMED_ML_NEW_ENTRY_CAP
            item["concentrated_watch_unconfirmed_ml_new_entry_cap_status"] = "applied"
            item["selection_reason"] = (
                str(item.get("selection_reason") or item.get("primary_lane") or "alphaops_vnext_score")
                + "|concentrated_watch_unconfirmed_ml_new_entry_cap"
            )
        else:
            item["concentrated_watch_unconfirmed_ml_new_entry_cap_status"] = "not_applicable"
        capped.append(item)
    return capped


def apply_concentrated_watch_damaged_weak_market_leader_cap(
    weighted: list[dict[str, Any]],
    portfolio_kind: str,
) -> list[dict[str, Any]]:
    if portfolio_kind != "concentrated" or not weighted:
        return weighted
    capped: list[dict[str, Any]] = []
    for rec in weighted:
        item = dict(rec)
        ticker = clean_ticker(item.get("ticker"))
        lane = str(item.get("primary_lane") or "").upper()
        crisis_state = str(item.get("crisis_state") or "").upper()
        confirmation = safe_float(item.get("selection_confirmation_score"), 1.0)
        breakout_quality = safe_float(item.get("breakout_setup_quality_score"), 1.0)
        qqq_1m_return = safe_float(item.get("qqq_1m_return"), 0.0)
        spy_1m_return = safe_float(item.get("spy_1m_return"), 0.0)
        ticker_ret_1m = safe_float(item.get("ticker_ret_1m"), 1.0)
        weak_quality = (
            confirmation < CONCENTRATED_WATCH_DAMAGED_WEAK_ML_CONFIRMATION_THRESHOLD
            or breakout_quality < CONCENTRATED_WATCH_DAMAGED_WEAK_ML_BREAKOUT_THRESHOLD
        )
        market_or_timing_damage = (
            qqq_1m_return < spy_1m_return
            or ticker_ret_1m < CONCENTRATED_WATCH_DAMAGED_WEAK_ML_TICKER_RET_1M_THRESHOLD
        )
        weight = safe_float(item.get("weight"))
        if (
            ticker not in CASH_TICKERS
            and lane == "MARKET_LEADER"
            and crisis_state in CONCENTRATED_RISK_STATE_CAP_STATES
            and weak_quality
            and market_or_timing_damage
            and weight > CONCENTRATED_WATCH_DAMAGED_WEAK_ML_CAP
        ):
            item["pre_concentrated_watch_damaged_weak_ml_cap_weight"] = weight
            item["weight"] = CONCENTRATED_WATCH_DAMAGED_WEAK_ML_CAP
            item["target_weight"] = CONCENTRATED_WATCH_DAMAGED_WEAK_ML_CAP
            item["concentrated_watch_damaged_weak_ml_cap"] = CONCENTRATED_WATCH_DAMAGED_WEAK_ML_CAP
            item["concentrated_watch_damaged_weak_ml_cap_status"] = "applied"
            item["selection_reason"] = (
                str(item.get("selection_reason") or item.get("primary_lane") or "alphaops_vnext_score")
                + "|concentrated_watch_damaged_weak_ml_cap"
            )
        else:
            item["concentrated_watch_damaged_weak_ml_cap_status"] = "not_applicable"
        capped.append(item)
    return capped


def apply_concentrated_green_bull_qqq_down_new_entry_cap(
    weighted: list[dict[str, Any]],
    portfolio_kind: str,
) -> list[dict[str, Any]]:
    if portfolio_kind != "concentrated" or not weighted:
        return weighted
    capped: list[dict[str, Any]] = []
    for rec in weighted:
        item = dict(rec)
        ticker = clean_ticker(item.get("ticker"))
        lane = str(item.get("primary_lane") or "").upper()
        holding_state_text = str(item.get("holding_state") or "").upper()
        replace_decision = str(item.get("hold_replace_decision") or "")
        is_new_entry = holding_state_text == "NEW" or replace_decision == "new_entry"
        crisis_state = str(item.get("crisis_state") or "").upper()
        capacity_regime = str(item.get("regime_capacity_regime") or item.get("regime_state") or "")
        qqq_1m_return = safe_float(item.get("qqq_1m_return"), 0.0)
        weight = safe_float(item.get("weight"))
        if (
            ticker not in CASH_TICKERS
            and lane == "MARKET_LEADER"
            and is_new_entry
            and crisis_state == "GREEN"
            and capacity_regime == "bull"
            and qqq_1m_return < CONCENTRATED_GREEN_BULL_QQQ_DOWN_THRESHOLD
            and weight > CONCENTRATED_GREEN_BULL_QQQ_DOWN_NEW_ENTRY_CAP
        ):
            item["pre_concentrated_green_bull_qqq_down_new_entry_cap_weight"] = weight
            item["weight"] = CONCENTRATED_GREEN_BULL_QQQ_DOWN_NEW_ENTRY_CAP
            item["target_weight"] = CONCENTRATED_GREEN_BULL_QQQ_DOWN_NEW_ENTRY_CAP
            item["concentrated_green_bull_qqq_down_new_entry_cap"] = (
                CONCENTRATED_GREEN_BULL_QQQ_DOWN_NEW_ENTRY_CAP
            )
            item["concentrated_green_bull_qqq_down_new_entry_cap_status"] = "applied"
            item["selection_reason"] = (
                str(item.get("selection_reason") or item.get("primary_lane") or "alphaops_vnext_score")
                + "|concentrated_green_bull_qqq_down_new_entry_cap"
            )
        else:
            item["concentrated_green_bull_qqq_down_new_entry_cap_status"] = "not_applicable"
        capped.append(item)
    return capped


def apply_concentrated_green_consumer_overheat_new_entry_cap(
    weighted: list[dict[str, Any]],
    portfolio_kind: str,
) -> list[dict[str, Any]]:
    if portfolio_kind != "concentrated" or not weighted:
        return weighted
    capped: list[dict[str, Any]] = []
    for rec in weighted:
        item = dict(rec)
        ticker = clean_ticker(item.get("ticker"))
        lane = str(item.get("primary_lane") or "").upper()
        holding_state_text = str(item.get("holding_state") or "").upper()
        replace_decision = str(item.get("hold_replace_decision") or "")
        is_new_entry = holding_state_text == "NEW" or replace_decision == "new_entry"
        crisis_state = str(item.get("crisis_state") or "").upper()
        sector = str(item.get("sector") or "")
        rs_benchmark_1m = safe_float(item.get("rs_benchmark_1m"), 0.0)
        weight = safe_float(item.get("weight"))
        if (
            ticker not in CASH_TICKERS
            and lane == "MARKET_LEADER"
            and is_new_entry
            and crisis_state == "GREEN"
            and sector == "Consumer Discretionary"
            and rs_benchmark_1m > CONCENTRATED_GREEN_CONSUMER_OVERHEAT_RS_1M_THRESHOLD
            and weight > CONCENTRATED_GREEN_CONSUMER_OVERHEAT_NEW_ENTRY_CAP
        ):
            item["pre_concentrated_green_consumer_overheat_new_entry_cap_weight"] = weight
            item["weight"] = CONCENTRATED_GREEN_CONSUMER_OVERHEAT_NEW_ENTRY_CAP
            item["target_weight"] = CONCENTRATED_GREEN_CONSUMER_OVERHEAT_NEW_ENTRY_CAP
            item["concentrated_green_consumer_overheat_new_entry_cap"] = (
                CONCENTRATED_GREEN_CONSUMER_OVERHEAT_NEW_ENTRY_CAP
            )
            item["concentrated_green_consumer_overheat_new_entry_cap_status"] = "applied"
            item["selection_reason"] = (
                str(item.get("selection_reason") or item.get("primary_lane") or "alphaops_vnext_score")
                + "|concentrated_green_consumer_overheat_new_entry_cap"
            )
        else:
            item["concentrated_green_consumer_overheat_new_entry_cap_status"] = "not_applicable"
        capped.append(item)
    return capped


def apply_concentrated_green_confirmed_market_leader_weak_rs_new_entry_cap(
    weighted: list[dict[str, Any]],
    portfolio_kind: str,
) -> list[dict[str, Any]]:
    if portfolio_kind != "concentrated" or not weighted:
        return weighted
    capped: list[dict[str, Any]] = []
    for rec in weighted:
        item = dict(rec)
        ticker = clean_ticker(item.get("ticker"))
        lane = str(item.get("primary_lane") or "").upper()
        holding_state_text = str(item.get("holding_state") or "").upper()
        replace_decision = str(item.get("hold_replace_decision") or "")
        is_new_entry = holding_state_text == "NEW" or replace_decision == "new_entry"
        crisis_state = str(item.get("crisis_state") or "").upper()
        confirmation = safe_float(item.get("selection_confirmation_score"), 0.0)
        rs_benchmark_1m = safe_float(item.get("rs_benchmark_1m"), 1.0)
        score = safe_float(item.get("score"))
        sec_evidence = safe_float(item.get("sec_combined_evidence_score"))
        atr14 = safe_float(item.get("atr14_pct"))
        weight = safe_float(item.get("weight"))
        high_conviction_stable_leader = (
            score >= CONCENTRATED_GREEN_CONFIRMED_ML_EXEMPT_SCORE_THRESHOLD
            and sec_evidence >= CONCENTRATED_GREEN_CONFIRMED_ML_EXEMPT_SEC_THRESHOLD
            and atr14 <= CONCENTRATED_GREEN_CONFIRMED_ML_EXEMPT_ATR_MAX
            and rs_benchmark_1m >= CONCENTRATED_GREEN_CONFIRMED_ML_EXEMPT_RS_1M_MIN
        )
        if (
            ticker not in CASH_TICKERS
            and lane == "MARKET_LEADER"
            and is_new_entry
            and crisis_state == "GREEN"
            and confirmation >= CONCENTRATED_GREEN_CONFIRMED_ML_CONFIRMATION_THRESHOLD
            and rs_benchmark_1m < CONCENTRATED_GREEN_CONFIRMED_ML_WEAK_RS_1M_THRESHOLD
            and not high_conviction_stable_leader
            and weight > CONCENTRATED_GREEN_CONFIRMED_ML_WEAK_RS_NEW_ENTRY_CAP
        ):
            item["pre_concentrated_green_confirmed_ml_weak_rs_new_entry_cap_weight"] = weight
            item["weight"] = CONCENTRATED_GREEN_CONFIRMED_ML_WEAK_RS_NEW_ENTRY_CAP
            item["target_weight"] = CONCENTRATED_GREEN_CONFIRMED_ML_WEAK_RS_NEW_ENTRY_CAP
            item["concentrated_green_confirmed_ml_weak_rs_new_entry_cap"] = (
                CONCENTRATED_GREEN_CONFIRMED_ML_WEAK_RS_NEW_ENTRY_CAP
            )
            item["concentrated_green_confirmed_ml_weak_rs_new_entry_cap_status"] = "applied"
            item["selection_reason"] = (
                str(item.get("selection_reason") or item.get("primary_lane") or "alphaops_vnext_score")
                + "|concentrated_green_confirmed_ml_weak_rs_new_entry_cap"
            )
        elif high_conviction_stable_leader:
            item["concentrated_green_confirmed_ml_weak_rs_new_entry_cap_status"] = (
                "exempt_high_conviction_stable_leader"
            )
        else:
            item["concentrated_green_confirmed_ml_weak_rs_new_entry_cap_status"] = "not_applicable"
        capped.append(item)
    return capped


def apply_concentrated_high_vol_weak_timing_new_entry_cap(
    weighted: list[dict[str, Any]],
    portfolio_kind: str,
) -> list[dict[str, Any]]:
    if portfolio_kind != "concentrated" or not weighted:
        return weighted
    capped: list[dict[str, Any]] = []
    for rec in weighted:
        item = dict(rec)
        ticker = clean_ticker(item.get("ticker"))
        lane = str(item.get("primary_lane") or "").upper()
        holding_state_text = str(item.get("holding_state") or "").upper()
        replace_decision = str(item.get("hold_replace_decision") or "")
        is_new_entry = holding_state_text == "NEW" or replace_decision == "new_entry"
        confirmation = safe_float(item.get("selection_confirmation_score"), 1.0)
        rs_benchmark_1m = safe_float(item.get("rs_benchmark_1m"), 1.0)
        atr14 = safe_float(item.get("atr14_pct"))
        weak_timing = (
            confirmation < CONCENTRATED_HIGH_VOL_WEAK_TIMING_CONFIRMATION_THRESHOLD
            or rs_benchmark_1m < CONCENTRATED_HIGH_VOL_WEAK_TIMING_RS_1M_THRESHOLD
        )
        weight = safe_float(item.get("weight"))
        if (
            ticker not in CASH_TICKERS
            and lane == "MARKET_LEADER"
            and is_new_entry
            and atr14 >= CONCENTRATED_HIGH_VOL_WEAK_TIMING_ATR_THRESHOLD
            and weak_timing
            and weight > CONCENTRATED_HIGH_VOL_WEAK_TIMING_NEW_ENTRY_CAP
        ):
            item["pre_concentrated_high_vol_weak_timing_new_entry_cap_weight"] = weight
            item["weight"] = CONCENTRATED_HIGH_VOL_WEAK_TIMING_NEW_ENTRY_CAP
            item["target_weight"] = CONCENTRATED_HIGH_VOL_WEAK_TIMING_NEW_ENTRY_CAP
            item["concentrated_high_vol_weak_timing_new_entry_cap"] = (
                CONCENTRATED_HIGH_VOL_WEAK_TIMING_NEW_ENTRY_CAP
            )
            item["concentrated_high_vol_weak_timing_new_entry_cap_status"] = "applied"
            item["selection_reason"] = (
                str(item.get("selection_reason") or item.get("primary_lane") or "alphaops_vnext_score")
                + "|concentrated_high_vol_weak_timing_new_entry_cap"
            )
        else:
            item["concentrated_high_vol_weak_timing_new_entry_cap_status"] = "not_applicable"
        capped.append(item)
    return capped


def apply_concentrated_green_neutral_cyclical_high_vol_new_entry_cap(
    weighted: list[dict[str, Any]],
    portfolio_kind: str,
) -> list[dict[str, Any]]:
    if portfolio_kind != "concentrated" or not weighted:
        return weighted
    capped: list[dict[str, Any]] = []
    for rec in weighted:
        item = dict(rec)
        ticker = clean_ticker(item.get("ticker"))
        lane = str(item.get("primary_lane") or "").upper()
        holding_state_text = str(item.get("holding_state") or "").upper()
        replace_decision = str(item.get("hold_replace_decision") or "")
        is_new_entry = holding_state_text == "NEW" or replace_decision == "new_entry"
        crisis_state = str(item.get("crisis_state") or "").upper()
        capacity_regime = str(item.get("regime_capacity_regime") or item.get("regime_state") or "")
        sector = str(item.get("sector") or "")
        atr14 = safe_float(item.get("atr14_pct"))
        weight = safe_float(item.get("weight"))
        if (
            ticker not in CASH_TICKERS
            and lane == "MARKET_LEADER"
            and is_new_entry
            and crisis_state == "GREEN"
            and capacity_regime == "neutral"
            and sector in CONCENTRATED_GREEN_NEUTRAL_CYCLICAL_HIGH_VOL_SECTORS
            and atr14 >= CONCENTRATED_GREEN_NEUTRAL_CYCLICAL_HIGH_VOL_ATR_THRESHOLD
            and weight > CONCENTRATED_GREEN_NEUTRAL_CYCLICAL_HIGH_VOL_NEW_ENTRY_CAP
        ):
            item["pre_concentrated_green_neutral_cyclical_high_vol_new_entry_cap_weight"] = weight
            item["weight"] = CONCENTRATED_GREEN_NEUTRAL_CYCLICAL_HIGH_VOL_NEW_ENTRY_CAP
            item["target_weight"] = CONCENTRATED_GREEN_NEUTRAL_CYCLICAL_HIGH_VOL_NEW_ENTRY_CAP
            item["concentrated_green_neutral_cyclical_high_vol_new_entry_cap"] = (
                CONCENTRATED_GREEN_NEUTRAL_CYCLICAL_HIGH_VOL_NEW_ENTRY_CAP
            )
            item["concentrated_green_neutral_cyclical_high_vol_new_entry_cap_status"] = "applied"
            item["selection_reason"] = (
                str(item.get("selection_reason") or item.get("primary_lane") or "alphaops_vnext_score")
                + "|concentrated_green_neutral_cyclical_high_vol_new_entry_cap"
            )
        else:
            item["concentrated_green_neutral_cyclical_high_vol_new_entry_cap_status"] = "not_applicable"
        capped.append(item)
    return capped


def apply_concentrated_defense_neutral_quality_new_entry_cap(
    weighted: list[dict[str, Any]],
    portfolio_kind: str,
) -> list[dict[str, Any]]:
    if portfolio_kind != "concentrated" or not weighted:
        return weighted
    capped: list[dict[str, Any]] = []
    for rec in weighted:
        item = dict(rec)
        ticker = clean_ticker(item.get("ticker"))
        lane = str(item.get("primary_lane") or "").upper()
        holding_state_text = str(item.get("holding_state") or "").upper()
        replace_decision = str(item.get("hold_replace_decision") or "")
        is_new_entry = holding_state_text == "NEW" or replace_decision == "new_entry"
        crisis_state = str(item.get("crisis_state") or "").upper()
        capacity_regime = str(item.get("regime_capacity_regime") or item.get("regime_state") or "")
        weight = safe_float(item.get("weight"))
        if (
            ticker not in CASH_TICKERS
            and lane == "QUALITY_COMPOUNDER"
            and is_new_entry
            and crisis_state == "DEFENSE_REVIEW"
            and capacity_regime == "neutral"
            and weight > CONCENTRATED_DEFENSE_NEUTRAL_QUALITY_NEW_ENTRY_CAP
        ):
            item["pre_concentrated_defense_neutral_quality_new_entry_cap_weight"] = weight
            item["weight"] = CONCENTRATED_DEFENSE_NEUTRAL_QUALITY_NEW_ENTRY_CAP
            item["target_weight"] = CONCENTRATED_DEFENSE_NEUTRAL_QUALITY_NEW_ENTRY_CAP
            item["concentrated_defense_neutral_quality_new_entry_cap"] = (
                CONCENTRATED_DEFENSE_NEUTRAL_QUALITY_NEW_ENTRY_CAP
            )
            item["concentrated_defense_neutral_quality_new_entry_cap_status"] = "applied"
            item["selection_reason"] = (
                str(item.get("selection_reason") or item.get("primary_lane") or "alphaops_vnext_score")
                + "|concentrated_defense_neutral_quality_new_entry_cap"
            )
        else:
            item["concentrated_defense_neutral_quality_new_entry_cap_status"] = "not_applicable"
        capped.append(item)
    return capped


def apply_concentrated_unconfirmed_quality_bull_new_entry_cap(
    weighted: list[dict[str, Any]],
    portfolio_kind: str,
) -> list[dict[str, Any]]:
    if portfolio_kind != "concentrated" or not weighted:
        return weighted
    capped: list[dict[str, Any]] = []
    for rec in weighted:
        item = dict(rec)
        ticker = clean_ticker(item.get("ticker"))
        holding_state_text = str(item.get("holding_state") or "").upper()
        replace_decision = str(item.get("hold_replace_decision") or "")
        is_new_entry = holding_state_text == "NEW" or replace_decision == "new_entry"
        style_regime = str(item.get("market_style_regime_label") or "")
        capacity_regime = str(item.get("regime_capacity_regime") or item.get("regime_state") or "")
        confirmation = safe_float(item.get("selection_confirmation_score"), 1.0)
        weight = safe_float(item.get("weight"))
        score = max(safe_float(item.get("alphaops_vnext_score")), safe_float(item.get("score")))
        sec_evidence = safe_float(item.get("sec_combined_evidence_score"))
        atr14 = safe_float(item.get("atr14_pct"), 999.0)
        rs_benchmark_1m = safe_float(item.get("rs_benchmark_1m"), -1.0)
        high_conviction_stable_leader = (
            score >= CONCENTRATED_UNCONFIRMED_QUALITY_BULL_EXEMPT_SCORE_THRESHOLD
            and sec_evidence >= CONCENTRATED_UNCONFIRMED_QUALITY_BULL_EXEMPT_SEC_THRESHOLD
            and atr14 <= CONCENTRATED_UNCONFIRMED_QUALITY_BULL_EXEMPT_ATR_MAX
            and rs_benchmark_1m >= CONCENTRATED_UNCONFIRMED_QUALITY_BULL_EXEMPT_RS_1M_MIN
        )
        should_cap = (
            ticker not in CASH_TICKERS
            and is_new_entry
            and style_regime == "quality_compounder"
            and capacity_regime == "bull"
            and confirmation < CONCENTRATED_UNCONFIRMED_QUALITY_BULL_CONFIRMATION_THRESHOLD
            and weight > CONCENTRATED_UNCONFIRMED_QUALITY_BULL_NEW_ENTRY_CAP
        )
        if should_cap and not high_conviction_stable_leader:
            item["pre_concentrated_unconfirmed_quality_bull_new_entry_cap_weight"] = weight
            item["weight"] = CONCENTRATED_UNCONFIRMED_QUALITY_BULL_NEW_ENTRY_CAP
            item["target_weight"] = CONCENTRATED_UNCONFIRMED_QUALITY_BULL_NEW_ENTRY_CAP
            item["concentrated_unconfirmed_quality_bull_new_entry_cap"] = CONCENTRATED_UNCONFIRMED_QUALITY_BULL_NEW_ENTRY_CAP
            item["concentrated_unconfirmed_quality_bull_new_entry_cap_status"] = "applied"
            item["selection_reason"] = (
                str(item.get("selection_reason") or item.get("primary_lane") or "alphaops_vnext_score")
                + "|concentrated_unconfirmed_quality_bull_new_entry_cap"
            )
        elif should_cap and high_conviction_stable_leader:
            item["concentrated_unconfirmed_quality_bull_new_entry_cap_status"] = (
                "exempt_high_conviction_stable_leader"
            )
        else:
            item["concentrated_unconfirmed_quality_bull_new_entry_cap_status"] = "not_applicable"
        capped.append(item)
    return capped


def apply_concentrated_unconfirmed_high_vol_new_entry_cap(
    weighted: list[dict[str, Any]],
    portfolio_kind: str,
) -> list[dict[str, Any]]:
    if portfolio_kind != "concentrated" or not weighted:
        return weighted
    capped: list[dict[str, Any]] = []
    for rec in weighted:
        item = dict(rec)
        ticker = clean_ticker(item.get("ticker"))
        lane = str(item.get("primary_lane") or "").upper()
        crisis_state = str(item.get("crisis_state") or "").upper()
        holding_state_text = str(item.get("holding_state") or "").upper()
        replace_decision = str(item.get("hold_replace_decision") or "")
        is_new_entry = holding_state_text == "NEW" or replace_decision == "new_entry"
        atr14 = safe_float(item.get("atr14_pct"))
        confirmation = safe_float(item.get("selection_confirmation_score"), 1.0)
        weight = safe_float(item.get("weight"))
        if (
            ticker not in CASH_TICKERS
            and lane == "MARKET_LEADER"
            and crisis_state == "GREEN"
            and is_new_entry
            and atr14 >= CONCENTRATED_UNCONFIRMED_HIGH_VOL_ATR_THRESHOLD
            and confirmation < 1.0
            and weight > CONCENTRATED_UNCONFIRMED_HIGH_VOL_NEW_ENTRY_CAP
        ):
            item["pre_concentrated_unconfirmed_high_vol_new_entry_cap_weight"] = weight
            item["weight"] = CONCENTRATED_UNCONFIRMED_HIGH_VOL_NEW_ENTRY_CAP
            item["target_weight"] = CONCENTRATED_UNCONFIRMED_HIGH_VOL_NEW_ENTRY_CAP
            item["concentrated_unconfirmed_high_vol_new_entry_cap"] = CONCENTRATED_UNCONFIRMED_HIGH_VOL_NEW_ENTRY_CAP
            item["concentrated_unconfirmed_high_vol_new_entry_cap_status"] = "applied"
            item["selection_reason"] = (
                str(item.get("selection_reason") or item.get("primary_lane") or "alphaops_vnext_score")
                + "|concentrated_unconfirmed_high_vol_new_entry_cap"
            )
        else:
            item["concentrated_unconfirmed_high_vol_new_entry_cap_status"] = "not_applicable"
        capped.append(item)
    return capped


def apply_concentrated_score_sizing_reweight(
    weighted: list[dict[str, Any]],
    portfolio_kind: str,
) -> list[dict[str, Any]]:
    """Research-only score-family sizing tilt for concentrated books.

    This implements the #191 cheap-screen candidate as a default-OFF policy
    hook. It keeps the selected names and gross stock exposure unchanged, then
    blends final post-cap weights toward rank-power allocation by
    alphaops_vnext_score. It intentionally does not touch cash. Any post-tilt
    single-name cap breach is reported as telemetry for broker A/B review.
    """
    if portfolio_kind != "concentrated" or not weighted:
        return weighted
    if not concentrated_score_sizing_reweight_enabled():
        return weighted
    out, telemetry = reweight_concentrated_records(
        weighted,
        signal=concentrated_score_sizing_signal(),
        blend=concentrated_score_sizing_blend(),
        rank_power=concentrated_score_sizing_rank_power(),
        cap_mode=concentrated_score_sizing_cap_mode(),
        single_cap=concentrated_score_sizing_single_cap(),
    )
    if telemetry.get("status") != "applied":
        return weighted
    for item in out:
        item["selection_reason"] = (
            str(item.get("selection_reason") or item.get("primary_lane") or "alphaops_vnext_score")
            + "|concentrated_score_sizing_reweight"
        )
    return out


def apply_concentrated_replacement_quality_swap(
    weighted: list[dict[str, Any]],
    month_records: list[dict[str, Any]],
    portfolio_kind: str,
    month_rejections: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Default-OFF Concentrated slot swap for high-quality missed leaders.

    This is the policy-path implementation of the P4 fixed-book
    counterfactual's strongest rule: leader_rank_ex_ante <= 15 and
    revenue_growth >= 10%. It keeps stock gross and cash unchanged by replacing
    at most one existing non-cash slot with the candidate at the donor slot's
    weight. The hook is research-only until broker replay validates it.
    """
    if portfolio_kind != "concentrated" or not weighted:
        return weighted
    if not concentrated_replacement_quality_enabled():
        return weighted

    rank_max = concentrated_replacement_quality_rank_max()
    revenue_min = concentrated_replacement_quality_revenue_growth_min()
    max_swaps = concentrated_replacement_quality_max_swaps_per_date()
    out = [dict(row) for row in weighted]
    stock_gross_before = float(sum(safe_float(row.get("weight")) for row in out))
    cash_before = max(0.0, 1.0 - stock_gross_before)
    rule_label = f"rank_top{rank_max}_and_revenue_ge{int(round(revenue_min * 100))}"
    for row in out:
        row["concentrated_replacement_quality_enabled"] = True
        row["concentrated_replacement_quality_applied"] = False
        row["concentrated_replacement_quality_status"] = "existing_position_unchanged"
        row["concentrated_replacement_quality_rule"] = rule_label
        row["concentrated_replacement_quality_rank_max"] = rank_max
        row["concentrated_replacement_quality_revenue_growth_min"] = revenue_min
        row["concentrated_replacement_quality_cash_before"] = cash_before
        row["concentrated_replacement_quality_stock_gross_before"] = stock_gross_before
    if max_swaps <= 0:
        for row in out:
            row["concentrated_replacement_quality_status"] = "blocked_zero_max_swaps"
        return out

    held = {clean_ticker(row.get("ticker")) for row in out if clean_ticker(row.get("ticker")) not in CASH_TICKERS}
    emerging_count = sum(
        1 for row in out if str(row.get("primary_lane") or "") in {"EMERGING_TENBAGGER", "TOP7_MANAGER_DISCOVERY"}
    )
    eligible_rejection_by_ticker: dict[str, dict[str, Any]] = {}
    for rej in month_rejections or []:
        ticker = clean_ticker(rej.get("ticker"))
        reason = str(rej.get("rejection_reason") or "")
        if ticker and reason in CONCENTRATED_REPLACEMENT_QUALITY_REJECTION_REASONS:
            eligible_rejection_by_ticker[ticker] = dict(rej)
    if not eligible_rejection_by_ticker:
        for row in out:
            row["concentrated_replacement_quality_status"] = "blocked_no_cap_replacement_miss"
        return out

    candidates: list[dict[str, Any]] = []
    for rec in month_records:
        ticker = clean_ticker(rec.get("ticker"))
        if not ticker or ticker in CASH_TICKERS or ticker in held:
            continue
        rejection = eligible_rejection_by_ticker.get(ticker)
        if not rejection:
            continue
        rank_value = safe_float(rec.get("leader_rank_ex_ante"), float("inf"))
        revenue_growth = safe_float(rec.get("revenue_growth"), float("-inf"))
        if rank_value > rank_max or revenue_growth < revenue_min:
            continue
        ok, _reason = allowed_candidate(rec, portfolio_kind, emerging_count, is_new_buy=True)
        if not ok:
            continue
        candidate = dict(rec)
        candidate["_replacement_quality_rejection_reason"] = str(rejection.get("rejection_reason") or "")
        candidate["_replacement_quality_rejection_weakest"] = clean_ticker(rejection.get("replacement_test_weakest_ticker"))
        candidate["_replacement_quality_sort_key"] = (
            safe_float(candidate.get("leader_rank_ex_ante"), float("inf")),
            -safe_float(candidate.get("rs_spy_3m"), safe_float(candidate.get("rs_benchmark_3m"))),
            -safe_float(candidate.get("revenue_growth")),
            -safe_float(candidate.get("liquidity_score")),
            ticker,
        )
        candidates.append(candidate)
    if not candidates:
        for row in out:
            row["concentrated_replacement_quality_status"] = "blocked_no_eligible_candidate"
        return out

    donor_indices = [
        idx for idx, row in enumerate(out) if clean_ticker(row.get("ticker")) and clean_ticker(row.get("ticker")) not in CASH_TICKERS
    ]
    if not donor_indices:
        for row in out:
            row["concentrated_replacement_quality_status"] = "blocked_no_donor"
        return out

    candidates.sort(key=lambda row: row["_replacement_quality_sort_key"])
    swaps = 0
    used_candidates: set[str] = set()
    while swaps < max_swaps and candidates and donor_indices:
        donor_idx = min(
            donor_indices,
            key=lambda idx: (
                safe_float(out[idx].get("alphaops_vnext_score")),
                safe_float(out[idx].get("weight")),
                clean_ticker(out[idx].get("ticker")),
            ),
        )
        donor = out[donor_idx]
        chosen = None
        for candidate in candidates:
            ticker = clean_ticker(candidate.get("ticker"))
            if ticker and ticker not in used_candidates:
                chosen = candidate
                break
        if chosen is None:
            break
        donor_ticker = clean_ticker(donor.get("ticker"))
        chosen_ticker = clean_ticker(chosen.get("ticker"))
        weight = safe_float(donor.get("weight"), safe_float(donor.get("target_weight")))
        entry = dict(chosen)
        entry.pop("_replacement_quality_sort_key", None)
        rejection_reason = str(entry.pop("_replacement_quality_rejection_reason", "") or "")
        rejection_weakest = clean_ticker(entry.pop("_replacement_quality_rejection_weakest", ""))
        entry["ticker"] = chosen_ticker
        entry["weight"] = weight
        entry["target_weight"] = weight
        entry["holding_state"] = "NEW"
        entry["holding_state_reason"] = "concentrated_replacement_quality_candidate"
        entry["hold_replace_decision"] = "concentrated_replacement_quality_swap"
        entry["prior_weight"] = 0.0
        entry["concentrated_replacement_quality_enabled"] = True
        entry["concentrated_replacement_quality_applied"] = True
        entry["concentrated_replacement_quality_status"] = "applied"
        entry["concentrated_replacement_quality_rule"] = rule_label
        entry["concentrated_replacement_quality_rank_max"] = rank_max
        entry["concentrated_replacement_quality_revenue_growth_min"] = revenue_min
        entry["concentrated_replacement_quality_removed_ticker"] = donor_ticker
        entry["concentrated_replacement_quality_added_ticker"] = chosen_ticker
        entry["concentrated_replacement_quality_source_rejection_reason"] = rejection_reason
        entry["concentrated_replacement_quality_rejection_weakest_ticker"] = rejection_weakest
        entry["concentrated_replacement_quality_replacement_weight"] = weight
        entry["concentrated_replacement_quality_leader_rank_ex_ante"] = safe_float(chosen.get("leader_rank_ex_ante"))
        entry["concentrated_replacement_quality_revenue_growth"] = safe_float(chosen.get("revenue_growth"))
        entry["concentrated_replacement_quality_rs_spy_3m"] = safe_float(
            chosen.get("rs_spy_3m"), safe_float(chosen.get("rs_benchmark_3m"))
        )
        entry["concentrated_replacement_quality_cash_before"] = cash_before
        entry["concentrated_replacement_quality_stock_gross_before"] = stock_gross_before
        entry["selection_reason"] = (
            str(chosen.get("selection_reason") or chosen.get("primary_lane") or "alphaops_vnext_score")
            + f"|concentrated_replacement_quality_swap:{rule_label}:replaced_{donor_ticker}"
        )
        out[donor_idx] = entry
        donor_indices.remove(donor_idx)
        used_candidates.add(chosen_ticker)
        held.add(chosen_ticker)
        swaps += 1

    stock_gross_after = float(sum(safe_float(row.get("weight")) for row in out))
    cash_after = max(0.0, 1.0 - stock_gross_after)
    for row in out:
        row["concentrated_replacement_quality_swap_count"] = swaps
        row["concentrated_replacement_quality_cash_after"] = cash_after
        row["concentrated_replacement_quality_stock_gross_after"] = stock_gross_after
        row["concentrated_replacement_quality_cash_preserved"] = abs(cash_after - cash_before) <= 1e-9
        row["concentrated_replacement_quality_stock_gross_preserved"] = (
            abs(stock_gross_after - stock_gross_before) <= 1e-9
        )
        if swaps <= 0:
            row["concentrated_replacement_quality_status"] = "blocked_no_swap"
    return out


def apply_main_ai_capex_momentum_tilt(
    weighted: list[dict[str, Any]],
    portfolio_kind: str,
) -> list[dict[str, Any]]:
    """Default-OFF Main-only tilt toward existing AI bottleneck momentum names.

    This mirrors the cheap broker A/B arm that passed for Main and failed for
    Concentrated. It preserves the selected ticker set and stock gross, does
    not require earnings confirmation, and never applies to Concentrated.
    """

    if portfolio_kind != "main" or not weighted:
        return weighted
    if not ai_capex_momentum_tilt_enabled():
        return weighted

    frame = pd.DataFrame([dict(row) for row in weighted])
    if frame.empty or "ticker" not in frame.columns:
        return weighted
    enriched = enrich_ai_capex_frame(frame)
    if "rs_benchmark_3m" in enriched.columns:
        rs_raw = enriched["rs_benchmark_3m"]
    elif "rs_spy_3m" in enriched.columns:
        rs_raw = enriched["rs_spy_3m"]
    else:
        rs_raw = pd.Series(0.0, index=enriched.index)
    rs_3m = pd.to_numeric(rs_raw, errors="coerce").fillna(0.0)
    momentum_rank = rs_3m.rank(pct=True).fillna(0.5)
    eligible = (
        enriched["ai_capex_value_chain_bucket"].astype(str).ne("AI_OTHER")
        & (pd.to_numeric(enriched["ai_capex_bottleneck_score"], errors="coerce").fillna(0.0) >= 0.5)
        & ((rs_3m > 0.0) | (momentum_rank >= 0.6))
    )
    if int(eligible.sum()) <= 0:
        return weighted

    before = [max(0.0, safe_float(row.get("target_weight"), safe_float(row.get("weight")))) for row in weighted]
    stock_gross = float(sum(before))
    if stock_gross <= 1e-12:
        return weighted
    strength = ai_capex_momentum_tilt_strength()
    raw = [weight * (1.0 + strength if bool(flag) else 1.0) for weight, flag in zip(before, eligible.tolist())]
    raw_sum = float(sum(raw))
    if raw_sum <= 1e-12:
        return weighted
    scaled = [weight * stock_gross / raw_sum for weight in raw]
    ceilings = [
        max(0.0, safe_float(row.get("effective_single_weight_cap"), target_caps("main")["single"]))
        for row in weighted
    ]
    after = capped_proportional_fill(scaled, stock_gross, ceilings)
    if abs(sum(after) - stock_gross) > 1e-8:
        return weighted
    if sum(abs(a - b) for a, b in zip(after, before)) <= 1e-12:
        return weighted

    out: list[dict[str, Any]] = []
    for idx, row in enumerate(weighted):
        item = dict(row)
        item["pre_main_ai_capex_momentum_tilt_weight"] = before[idx]
        item["main_ai_capex_momentum_tilt_weight"] = after[idx]
        item["main_ai_capex_momentum_tilt_delta"] = after[idx] - before[idx]
        item["main_ai_capex_momentum_tilt_enabled"] = True
        item["main_ai_capex_momentum_tilt_applied"] = bool(eligible.iloc[idx])
        item["main_ai_capex_momentum_tilt_strength"] = strength
        item["ai_capex_value_chain_bucket"] = enriched.iloc[idx].get("ai_capex_value_chain_bucket")
        item["ai_capex_bottleneck_score"] = safe_float(enriched.iloc[idx].get("ai_capex_bottleneck_score"))
        item["weight"] = after[idx]
        item["target_weight"] = after[idx]
        if bool(eligible.iloc[idx]):
            item["selection_reason"] = (
                str(item.get("selection_reason") or item.get("primary_lane") or "alphaops_vnext_score")
                + "|main_ai_capex_momentum_tilt"
            )
        out.append(item)
    return out


def apply_concentrated_cashfunded_early_entry(
    weighted: list[dict[str, Any]],
    month_records: list[dict[str, Any]],
    portfolio_kind: str,
) -> list[dict[str, Any]]:
    """Add one small Concentrated early-entry position funded only from cash.

    Default OFF. The hook preserves all existing selected names and weights.
    When enabled it uses a PIT candidate score to pick the highest-ranked
    unheld candidate, then deploys at most the configured add weight and never
    more than available cash.
    """
    if portfolio_kind != "concentrated" or not weighted:
        return weighted
    if not concentrated_cashfunded_early_entry_enabled():
        return weighted
    signal = concentrated_cashfunded_early_entry_signal()
    validate_cashfunded_early_entry_signal(signal)
    add_weight = concentrated_cashfunded_early_entry_add_weight()
    min_breakout = concentrated_cashfunded_early_entry_min_breakout_quality()
    allow_crisis = concentrated_cashfunded_early_entry_allow_crisis_deployment()
    out = [dict(row) for row in weighted]
    held = {clean_ticker(row.get("ticker")) for row in out if clean_ticker(row.get("ticker")) not in CASH_TICKERS}
    cash_before = max(0.0, 1.0 - sum(safe_float(row.get("weight")) for row in out))
    for row in out:
        row["concentrated_cashfunded_early_entry_enabled"] = True
        row["concentrated_cashfunded_early_entry_applied"] = False
        row["concentrated_cashfunded_early_entry_status"] = "existing_position_unchanged"
        row["concentrated_cashfunded_early_entry_signal"] = signal
        row["concentrated_cashfunded_early_entry_add_weight"] = add_weight
        row["concentrated_cashfunded_early_entry_min_breakout_quality"] = min_breakout
        row["concentrated_cashfunded_early_entry_cash_before"] = cash_before
    if cash_before <= 1e-12 or add_weight <= 1e-12:
        for row in out:
            row["concentrated_cashfunded_early_entry_status"] = "blocked_no_cash"
        return out
    candidates: list[dict[str, Any]] = []
    for rec in month_records:
        ticker = clean_ticker(rec.get("ticker"))
        if not ticker or ticker in CASH_TICKERS or ticker in held:
            continue
        if signal not in rec or pd.isna(rec.get(signal)):
            continue
        if not allow_crisis and "crisis_state" in rec:
            crisis_state = str(rec.get("crisis_state") or "").upper()
            if "CRISIS" in crisis_state or "DEFENSE" in crisis_state:
                continue
        candidate = dict(rec)
        candidate["_cashfunded_signal_value"] = safe_float(rec.get(signal))
        candidates.append(candidate)
    if not candidates:
        for row in out:
            row["concentrated_cashfunded_early_entry_status"] = "blocked_no_unheld_candidate"
        return out
    chosen = max(candidates, key=lambda row: safe_float(row.get("_cashfunded_signal_value")))
    chosen_breakout = safe_float(chosen.get("breakout_setup_quality_score"))
    if chosen_breakout < min_breakout:
        for row in out:
            row["concentrated_cashfunded_early_entry_status"] = "blocked_top_candidate_low_breakout_quality"
            row["concentrated_cashfunded_early_entry_top_candidate"] = clean_ticker(chosen.get("ticker"))
            row["concentrated_cashfunded_early_entry_top_breakout_quality"] = chosen_breakout
        return out
    inject = min(add_weight, cash_before)
    entry = dict(chosen)
    entry.pop("_cashfunded_signal_value", None)
    entry["ticker"] = clean_ticker(chosen.get("ticker"))
    entry["weight"] = inject
    entry["target_weight"] = inject
    entry["holding_state"] = "NEW"
    entry["holding_state_reason"] = "cashfunded_early_entry_candidate"
    entry["hold_replace_decision"] = "cashfunded_early_entry"
    entry["prior_weight"] = 0.0
    entry["concentrated_cashfunded_early_entry_enabled"] = True
    entry["concentrated_cashfunded_early_entry_applied"] = True
    entry["concentrated_cashfunded_early_entry_status"] = "applied"
    entry["concentrated_cashfunded_early_entry_signal"] = signal
    entry["concentrated_cashfunded_early_entry_signal_value"] = safe_float(chosen.get(signal))
    entry["concentrated_cashfunded_early_entry_add_weight"] = add_weight
    entry["concentrated_cashfunded_early_entry_min_breakout_quality"] = min_breakout
    entry["concentrated_cashfunded_early_entry_breakout_quality"] = safe_float(
        chosen.get("breakout_setup_quality_score")
    )
    entry["concentrated_cashfunded_early_entry_added_weight"] = inject
    entry["concentrated_cashfunded_early_entry_cash_before"] = cash_before
    entry["concentrated_cashfunded_early_entry_non_sticky"] = True
    entry["selection_reason"] = (
        str(chosen.get("selection_reason") or chosen.get("primary_lane") or "alphaops_vnext_score")
        + f"|concentrated_cashfunded_early_entry:{signal}:{inject:.4f}"
    )
    out.append(entry)
    return out


def row_for_target(rec: dict[str, Any], dt: pd.Timestamp, portfolio_kind: str, variant_id: str, target_n: int, crisis_row: dict[str, Any]) -> dict[str, Any]:
    ticker = clean_ticker(rec.get("ticker"))
    return {
        **rec,
        "rebalance_date": dt.date().isoformat(),
        "ticker": ticker,
        "weight": safe_float(rec.get("weight")),
        "target_weight": safe_float(rec.get("target_weight"), safe_float(rec.get("weight"))),
        "portfolio_kind": portfolio_kind,
        "variant_id": variant_id,
        "target_n": int(target_n),
        "target_stock_names": int(target_n),
        "weighting_mode": "alphaops_vnext_score_power",
        "active_rebalance_interval_months": 1,
        "operating_target_source": "alphaops_vnext_policy_replay",
        "operating_decision_semantics": "historical_vnext_policy_from_candidate_replay_book",
        "decision_frequency": "monthly_replay_plus_crisis_hysteresis",
        "production_policy": "alphaops_vnext_production",
        "selection_reason": str(rec.get("selection_reason") or rec.get("primary_lane") or "alphaops_vnext_score"),
        "crisis_state": str(crisis_row.get("crisis_state") or "GREEN"),
        "crisis_overlay_status": str(crisis_row.get("crisis_overlay_status") or "applied"),
        "crisis_hysteresis_minimum_action_gap_days": CRISIS_HYSTERESIS["minimum_action_gap_days"],
        "current_holdings_source": "alphaops_vnext_policy_target_book",
    }


def build_variant_book(
    candidate: pd.DataFrame,
    *,
    portfolio_kind: str,
    target_n: int,
    crisis_states: pd.DataFrame,
    prices: dict[str, pd.DataFrame],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    variant_id = f"alphaops_vnext_{portfolio_kind}_N{target_n}"
    rows: list[dict[str, Any]] = []
    lane_rows: list[dict[str, Any]] = []
    rejects: list[dict[str, Any]] = []
    exposure_rows: list[dict[str, Any]] = []
    prev: dict[str, dict[str, Any]] = {}
    for raw_dt in sorted(pd.to_datetime(candidate["rebalance_date"], errors="coerce").dropna().unique()):
        dt = pd.Timestamp(raw_dt).normalize()
        month = score_month(candidate[candidate["rebalance_date"].eq(dt)].copy())
        if month.empty:
            continue
        crisis_row = crisis_state_for_date(crisis_states, dt)
        month = apply_crisis_lane_policy(month, crisis_row, portfolio_kind)
        month = apply_concentrated_leader_gate_annotations(month, portfolio_kind, target_n)
        score_sigma = float(pd.to_numeric(month["alphaops_vnext_score"], errors="coerce").std(ddof=0) or 0.0)
        score_median = float(pd.to_numeric(month["alphaops_vnext_score"], errors="coerce").median() or 0.0)
        month_records = month.to_dict("records")
        lane_rows.extend([{**rec, "rebalance_date": dt.date().isoformat()} for rec in month_records])
        by_ticker = {clean_ticker(rec.get("ticker")): rec for rec in month_records}
        month_reject_start = len(rejects)
        selected: list[dict[str, Any]] = []
        selected_tickers: set[str] = set()
        emerging_count = 0
        for ticker, old in sorted(prev.items(), key=lambda item: -safe_float(item[1].get("weight"))):
            rec = by_ticker.get(ticker)
            if not rec:
                continue
            rec_for_state = dict(rec)
            rec_for_state["shakeout_guard_prior_holding"] = True
            state, state_reason = holding_state(rec_for_state, score_median, score_sigma)
            if state == "EXIT":
                rejects.append({"rebalance_date": dt.date().isoformat(), "ticker": ticker, "portfolio_kind": portfolio_kind, "variant_id": variant_id, "rejection_reason": state_reason, "prior_holding": True})
                continue
            ok, reason = allowed_candidate(rec, portfolio_kind, emerging_count, is_new_buy=False)
            if not ok:
                rejects.append({"rebalance_date": dt.date().isoformat(), "ticker": ticker, "portfolio_kind": portfolio_kind, "variant_id": variant_id, "rejection_reason": reason, "prior_holding": True})
                continue
            out = dict(rec)
            out["holding_state"] = state
            out["hold_replace_decision"] = "keep_prior_holding"
            out["holding_state_reason"] = state_reason
            out.update(shakeout_guard_prod_telemetry(rec_for_state, state_reason))
            out["prior_weight"] = safe_float(old.get("weight"))
            out["leadership_persistence_hold_enabled"] = bool(leadership_persistence_hold_enabled())
            protected, protection_reason = leadership_persistence_hold_protected(
                out,
                portfolio_kind=portfolio_kind,
            )
            out["leadership_persistence_hold_protected"] = bool(
                leadership_persistence_hold_enabled() and protected
            )
            out["leadership_persistence_hold_reason"] = protection_reason
            selected.append(out)
            selected_tickers.add(ticker)
            if str(rec.get("primary_lane")) in {"EMERGING_TENBAGGER", "TOP7_MANAGER_DISCOVERY"}:
                emerging_count += 1
            if len(selected) >= target_n:
                break
        ranked = sorted(month_records, key=lambda rec: safe_float(rec.get("alphaops_vnext_weight_score"), safe_float(rec.get("alphaops_vnext_score"))), reverse=True)
        threshold_normal = max(0.15, 0.75 * max(score_sigma, 0.20))
        threshold_broken = max(0.08, 0.35 * max(score_sigma, 0.20))
        for rec in ranked:
            ticker = clean_ticker(rec.get("ticker"))
            if not ticker or ticker in selected_tickers:
                continue
            ok, reason = allowed_candidate(rec, portfolio_kind, emerging_count, is_new_buy=True)
            if not ok:
                rejects.append({"rebalance_date": dt.date().isoformat(), "ticker": ticker, "portfolio_kind": portfolio_kind, "variant_id": variant_id, "rejection_reason": reason, "prior_holding": False})
                continue
            out = dict(rec)
            out["holding_state"] = "NEW"
            out["holding_state_reason"] = "new_candidate_cleared_vnext_gates"
            out["hold_replace_threshold_sigma"] = threshold_normal
            out["hold_replace_broken_threshold_sigma"] = threshold_broken
            out["hold_replace_decision"] = "new_entry"
            if len(selected) < target_n:
                selected.append(out)
                selected_tickers.add(ticker)
                if str(rec.get("primary_lane")) in {"EMERGING_TENBAGGER", "TOP7_MANAGER_DISCOVERY"}:
                    emerging_count += 1
                continue
            weakest_idx = min(range(len(selected)), key=lambda i: safe_float(selected[i].get("alphaops_vnext_score")))
            weakest = selected[weakest_idx]
            required_gap, gap_reason, persistence_applied = replacement_gap_for_weakest(
                weakest,
                portfolio_kind=portfolio_kind,
                threshold_normal=threshold_normal,
                threshold_broken=threshold_broken,
                score_sigma=score_sigma,
            )
            out["hold_replace_required_gap"] = required_gap
            out["hold_replace_required_gap_reason"] = gap_reason
            out["leadership_persistence_hold_applied_to_replacement_test"] = bool(persistence_applied)
            out["replacement_test_weakest_ticker"] = clean_ticker(weakest.get("ticker"))
            out["replacement_test_weakest_score"] = safe_float(weakest.get("alphaops_vnext_score"))
            if safe_float(rec.get("alphaops_vnext_score")) >= safe_float(weakest.get("alphaops_vnext_score")) + required_gap:
                rejects.append({
                    "rebalance_date": dt.date().isoformat(),
                    "ticker": clean_ticker(weakest.get("ticker")),
                    "portfolio_kind": portfolio_kind,
                    "variant_id": variant_id,
                    "rejection_reason": "replaced_by_higher_vnext_score",
                    "replacement_ticker": ticker,
                    "prior_holding": clean_ticker(weakest.get("ticker")) in prev,
                    "hold_replace_required_gap": required_gap,
                    "hold_replace_required_gap_reason": gap_reason,
                    "leadership_persistence_hold_applied": bool(persistence_applied),
                })
                selected_tickers.discard(clean_ticker(weakest.get("ticker")))
                selected[weakest_idx] = out
                selected_tickers.add(ticker)
            else:
                rejects.append({
                    "rebalance_date": dt.date().isoformat(),
                    "ticker": ticker,
                    "portfolio_kind": portfolio_kind,
                    "variant_id": variant_id,
                    "rejection_reason": (
                        "leadership_persistence_hold_threshold_not_met"
                        if persistence_applied
                        else "hold_replace_threshold_not_met"
                    ),
                    "prior_holding": False,
                    "replacement_test_weakest_ticker": clean_ticker(weakest.get("ticker")),
                    "replacement_test_weakest_score": safe_float(weakest.get("alphaops_vnext_score")),
                    "candidate_score": safe_float(rec.get("alphaops_vnext_score")),
                    "hold_replace_required_gap": required_gap,
                    "hold_replace_required_gap_reason": gap_reason,
                    "leadership_persistence_hold_applied": bool(persistence_applied),
                })
        cash_target = crisis_cash_target(str(crisis_row.get("crisis_state") or "GREEN"), portfolio_kind)
        weighted = assign_weights(selected, portfolio_kind, cash_target)
        weighted = apply_vnext_benchmark_guard(
            weighted,
            portfolio_kind=portfolio_kind,
            target_n=target_n,
            prices=prices,
            rebalance_date=dt,
        )
        weighted = apply_concentrated_risk_state_new_entry_cap(weighted, portfolio_kind)
        weighted = apply_main_high_volatility_new_entry_cap(weighted, portfolio_kind)
        weighted = apply_main_watch_unconfirmed_market_leader_new_entry_cap(weighted, portfolio_kind)
        weighted = apply_main_green_bull_low_confirm_high_vol_new_entry_cap(weighted, portfolio_kind)
        weighted = apply_main_balanced_bull_qqq_damage_low_confirm_leader_cap(weighted, portfolio_kind)
        weighted = apply_main_balanced_neutral_soft_qqq_damage_weak_leader_cap(weighted, portfolio_kind)
        weighted = apply_main_quality_bull_low_confirm_new_entry_cap(weighted, portfolio_kind)
        weighted = apply_main_green_neutral_cyclical_high_vol_new_entry_cap(weighted, portfolio_kind)
        weighted = apply_main_quality_hold_weak_timing_trim(weighted, portfolio_kind)
        weighted = apply_concentrated_hold_decay_trim(weighted, portfolio_kind)
        weighted = apply_concentrated_watch_unconfirmed_high_vol_new_entry_cap(weighted, portfolio_kind)
        weighted = apply_concentrated_watch_unconfirmed_market_leader_new_entry_cap(weighted, portfolio_kind)
        weighted = apply_concentrated_watch_damaged_weak_market_leader_cap(weighted, portfolio_kind)
        weighted = apply_concentrated_green_bull_qqq_down_new_entry_cap(weighted, portfolio_kind)
        weighted = apply_concentrated_green_consumer_overheat_new_entry_cap(weighted, portfolio_kind)
        weighted = apply_concentrated_green_confirmed_market_leader_weak_rs_new_entry_cap(weighted, portfolio_kind)
        weighted = apply_concentrated_green_neutral_cyclical_high_vol_new_entry_cap(weighted, portfolio_kind)
        weighted = apply_concentrated_defense_neutral_quality_new_entry_cap(weighted, portfolio_kind)
        weighted = apply_concentrated_unconfirmed_quality_bull_new_entry_cap(weighted, portfolio_kind)
        weighted = apply_concentrated_unconfirmed_high_vol_new_entry_cap(weighted, portfolio_kind)
        weighted = apply_concentrated_high_vol_weak_timing_new_entry_cap(weighted, portfolio_kind)
        weighted = apply_main_ai_capex_momentum_tilt(weighted, portfolio_kind)
        weighted = apply_concentrated_score_sizing_reweight(weighted, portfolio_kind)
        weighted = apply_concentrated_replacement_quality_swap(
            weighted,
            month_records,
            portfolio_kind,
            rejects[month_reject_start:],
        )
        weighted = apply_concentrated_cashfunded_early_entry(weighted, month_records, portfolio_kind)
        prev = {
            clean_ticker(row.get("ticker")): row
            for row in weighted
            if not bool(row.get("concentrated_cashfunded_early_entry_non_sticky"))
        }
        lane_totals: dict[str, float] = {}
        for rec in weighted:
            lane = str(rec.get("primary_lane") or "")
            lane_totals[lane] = lane_totals.get(lane, 0.0) + safe_float(rec.get("weight"))
            rows.append(row_for_target(rec, dt, portfolio_kind, variant_id, target_n, crisis_row))
        invested = sum(safe_float(rec.get("weight")) for rec in weighted)
        cash_weight = max(0.0, 1.0 - invested)
        if cash_weight > 1e-8:
            rows.append(
                {
                    "rebalance_date": dt.date().isoformat(),
                    "ticker": "CASH",
                    "Name": "Cash",
                    "sector": "Cash",
                    "weight": cash_weight,
                    "target_weight": cash_weight,
                    "portfolio_kind": portfolio_kind,
                    "variant_id": variant_id,
                    "target_n": int(target_n),
                    "target_stock_names": int(target_n),
                    "weighting_mode": "alphaops_vnext_score_power",
                    "primary_lane": "CASH",
                    "operating_target_source": "alphaops_vnext_policy_replay",
                    "production_policy": "alphaops_vnext_production",
                    "selection_reason": "cash_from_crisis_overlay_or_position_caps",
                    "crisis_state": str(crisis_row.get("crisis_state") or "GREEN"),
                    "crisis_overlay_status": str(crisis_row.get("crisis_overlay_status") or "applied"),
                    "current_holdings_source": "alphaops_vnext_policy_target_book",
                }
            )
        exposure_rows.append(
            {
                "rebalance_date": dt.date().isoformat(),
                "portfolio_kind": portfolio_kind,
                "variant_id": variant_id,
                "cash_weight": cash_weight,
                "effective_stock_count": int(len(weighted)),
                **lane_totals,
            }
        )
    target = pd.DataFrame(rows)
    if not target.empty:
        target["rebalance_date"] = pd.to_datetime(target["rebalance_date"], errors="coerce").dt.date.astype(str)
        target = target.sort_values(["rebalance_date", "weight"], ascending=[True, False]).reset_index(drop=True)
    return target, pd.DataFrame(lane_rows), pd.DataFrame(rejects), pd.DataFrame(exposure_rows)


def copy_operating_books(latest_run: Path, main_book: pd.DataFrame, concentrated_book: pd.DataFrame) -> dict[str, str]:
    reports = latest_run / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    main_path = reports / "operating_main_target_book.csv"
    concentrated_path = reports / "operating_concentrated_target_book.csv"
    write_csv(main_path, main_book)
    write_csv(concentrated_path, concentrated_book)
    return {"main": str(main_path), "concentrated": str(concentrated_path)}


def latest_price_close_date(price_cache: Path, tickers: list[str]) -> pd.Timestamp | None:
    dates: list[pd.Timestamp] = []
    cleaned = {clean_ticker(t) for t in tickers}
    for ticker in sorted(t for t in cleaned if t and t not in CASH_TICKERS):
        px = load_price_series(price_cache, ticker)
        if px.empty:
            continue
        dates.append(pd.Timestamp(px.index.max()).normalize())
    return min(dates) if dates else None


def latest_book_date(book: pd.DataFrame) -> pd.Timestamp | None:
    if book.empty or "rebalance_date" not in book.columns:
        return None
    dates = pd.to_datetime(book["rebalance_date"], errors="coerce").dropna()
    return pd.Timestamp(dates.max()).normalize() if not dates.empty else None


TARGET_GENERATION_ENV_KEYS = [
    "PHASE_MAIN_FAST_CRASH_HEDGE_ENABLED",
    "PHASE_AI_CAPEX_MOMENTUM_TILT_ENABLED",
    "PHASE_CONCENTRATED_REPLACEMENT_QUALITY_ENABLED",
    "PHASE_CONCENTRATED_CASHFUNDED_EARLY_ENTRY_ENABLED",
    "PHASE_REGIME_CAPACITY_BULL_FLOOR_ENABLED",
    "R1000_CONC_GROSS_CAP_FLOOR",
    "R1000_CONC_SCORE_SIZING_SIGNAL",
    "R1000_CONC_SCORE_SIZING_BLEND",
    "R1000_CONC_SCORE_SIZING_RANK_POWER",
    "R1000_CONC_SCORE_SIZING_CAP_MODE",
    "R1000_CONC_SCORE_SIZING_SINGLE_CAP",
    "R1000_CONC_REPLACEMENT_QUALITY_RANK_MAX",
    "R1000_CONC_REPLACEMENT_QUALITY_MIN_REVENUE_GROWTH",
    "R1000_CONC_REPLACEMENT_QUALITY_MAX_SWAPS_PER_DATE",
    "R1000_MAIN_AI_CAPEX_TILT_STRENGTH",
    "R1000_MAIN_FAST_CRASH_HEDGE_TICKER",
    "R1000_MAIN_FAST_CRASH_HEDGE_BENCHMARK",
    "R1000_MAIN_FAST_CRASH_HEDGE_WEIGHT",
    "R1000_MAIN_FAST_CRASH_RISK_BUFFER_WEIGHT",
    "R1000_CONC_CASHFUNDED_EARLY_ENTRY_SIGNAL",
    "R1000_CONC_CASHFUNDED_EARLY_ENTRY_ADD_WEIGHT",
    "R1000_CONC_CASHFUNDED_EARLY_ENTRY_MIN_BREAKOUT_QUALITY",
    "R1000_CONC_CASHFUNDED_EARLY_ENTRY_ALLOW_CRISIS",
]


def target_generation_input_manifest(
    *,
    latest_run: Path,
    output_dir: Path,
    candidate_book: Path,
    candidate_source_mode: str,
    candidate: pd.DataFrame,
    price_cache: Path,
    long_crisis_features: Path,
    long_crisis_thresholds: Path,
    operating_append_end_date: pd.Timestamp | None,
) -> dict[str, Any]:
    tickers = sorted(
        {
            clean_ticker(t)
            for t in candidate.get("ticker", pd.Series(dtype=str)).astype(str).tolist()
            if clean_ticker(t) and clean_ticker(t) not in CASH_TICKERS
        }
    )
    required_files = [price_cache / px_cache_name(ticker) for ticker in tickers]
    existing = [path for path in required_files if path.exists()]
    missing = [tickers[idx] for idx, path in enumerate(required_files) if not path.exists()]
    manifest_path = price_cache / "replay_price_cache_manifest.json"
    payload = {
        "schema_version": "alphaops-vnext-target-generation-input-manifest-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "research_only": True,
        "latest_run": str(latest_run),
        "output_dir": str(output_dir),
        "candidate_book": file_meta(candidate_book),
        "candidate_source_mode": candidate_source_mode,
        "candidate_row_count": int(len(candidate)),
        "candidate_rebalance_date_min": date_text(pd.to_datetime(candidate.get("rebalance_date"), errors="coerce").min()),
        "candidate_rebalance_date_max": date_text(pd.to_datetime(candidate.get("rebalance_date"), errors="coerce").max()),
        "price_cache": {
            "path": str(price_cache),
            "manifest": file_meta(manifest_path),
            "required_ticker_count": int(len(tickers)),
            "required_price_file_count": int(len(required_files)),
            "existing_price_file_count": int(len(existing)),
            "missing_price_file_count": int(len(missing)),
            "missing_ticker_sample": missing[:25],
        },
        "macro_crisis_inputs": {
            "long_crisis_features": file_meta(long_crisis_features),
            "long_crisis_thresholds": file_meta(long_crisis_thresholds),
        },
        "env": {key: os.environ.get(key, "") for key in TARGET_GENERATION_ENV_KEYS},
        "code": {
            "github_sha": os.environ.get("GITHUB_SHA", ""),
            "github_ref": os.environ.get("GITHUB_REF", ""),
        },
        "operating_append_end_date": date_text(operating_append_end_date),
    }
    return payload


def append_latest_operating_decision(
    book: pd.DataFrame,
    *,
    price_cache: Path,
    portfolio_kind: str,
    variant_key: str,
    operating_append_end_date: pd.Timestamp | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    if book.empty:
        return book, {
            "portfolio": portfolio_kind,
            "variant_key": variant_key,
            "latest_target_appended": False,
            "append_reason": "target book empty",
        }
    history_max = latest_book_date(book)
    latest_slice = book[pd.to_datetime(book["rebalance_date"], errors="coerce").dt.normalize().eq(history_max)].copy()
    price_close = latest_price_close_date(price_cache, latest_slice["ticker"].astype(str).tolist()) if not latest_slice.empty else None
    append_close = price_close
    append_clamped = False
    if append_close is not None and operating_append_end_date is not None:
        limit = pd.Timestamp(operating_append_end_date).normalize()
        if append_close > limit:
            append_close = limit
            append_clamped = True
    appended = False
    append_reason = "latest close unavailable"
    out = book.copy()
    if history_max is not None and append_close is not None:
        if pd.Timestamp(append_close).normalize() > pd.Timestamp(history_max).normalize():
            latest_rows = latest_slice.copy()
            latest_rows["rebalance_date"] = pd.Timestamp(append_close).date().isoformat()
            latest_rows["operating_appended"] = True
            latest_rows["operating_signal_source_date"] = pd.Timestamp(history_max).date().isoformat()
            latest_rows["operating_latest_price_date"] = pd.Timestamp(append_close).date().isoformat()
            latest_rows["operating_unclamped_latest_price_date"] = date_text(price_close)
            latest_rows["decision_frequency"] = "monthly_replay_plus_latest_close_hold_forward"
            latest_rows["operating_decision_semantics"] = "latest_close_hold_forward_from_vnext_policy"
            if "selection_reason" in latest_rows.columns:
                latest_rows["selection_reason"] = latest_rows["selection_reason"].astype(str) + "|hold_forward_to_latest_close"
            else:
                latest_rows["selection_reason"] = "alphaops_vnext_score|hold_forward_to_latest_close"
            out = pd.concat([out, latest_rows], ignore_index=True)
            appended = True
            append_reason = "latest vNext target held forward to latest observable close"
            if append_clamped:
                append_reason = "latest vNext target held forward to operating append end date"
        else:
            append_reason = "latest price close is not newer than vNext policy book"
    if "operating_appended" not in out.columns:
        out["operating_appended"] = False
    if "operating_signal_source_date" not in out.columns:
        out["operating_signal_source_date"] = ""
    if "operating_latest_price_date" not in out.columns:
        out["operating_latest_price_date"] = ""
    if "operating_unclamped_latest_price_date" not in out.columns:
        out["operating_unclamped_latest_price_date"] = ""
    if not out.empty:
        out["rebalance_date"] = pd.to_datetime(out["rebalance_date"], errors="coerce").dt.date.astype(str)
        out = out.sort_values(["rebalance_date", "weight"], ascending=[True, False]).reset_index(drop=True)
    output_max = latest_book_date(out)
    current = bool(append_close is not None and output_max is not None and output_max >= append_close)
    return out, {
        "portfolio": portfolio_kind,
        "variant_key": variant_key,
        "history_max_rebalance_date": date_text(history_max),
        "latest_price_close_date": date_text(price_close),
        "operating_append_end_date": date_text(operating_append_end_date),
        "operating_append_clamped": bool(append_clamped),
        "operating_signal_date": date_text(append_close if append_close is not None else history_max),
        "output_max_rebalance_date": date_text(output_max),
        "latest_target_appended": bool(appended),
        "operating_book_current": bool(current),
        "append_reason": append_reason,
        "decision_frequency": "monthly_replay_plus_latest_close_hold_forward",
        "history_row_count": int(len(book)),
        "output_row_count": int(len(out)),
    }


def dominant_text(values: pd.Series, default: str = "unknown") -> str:
    if values is None or values.empty:
        return default
    s = values.dropna().astype(str).str.strip().str.lower()
    s = s[(s != "") & (s != "nan") & (s != "none")]
    if s.empty:
        return default
    mode = s.mode()
    return default if mode.empty else str(mode.iloc[0])


def capacity_cash_row(date: pd.Timestamp, portfolio_kind: str, cash_weight: float, template: pd.Series | None) -> dict[str, Any]:
    row = dict(template.to_dict()) if template is not None else {}
    row.update(
        {
            "rebalance_date": pd.Timestamp(date).date().isoformat(),
            "ticker": "CASH",
            "Name": "Cash",
            "sector": "Cash",
            "weight": float(max(0.0, cash_weight)),
            "target_weight": float(max(0.0, cash_weight)),
            "portfolio_kind": portfolio_kind,
            "primary_lane": "CASH",
            "selection_reason": "cash_from_vnext_regime_capacity_overlay",
            "operating_target_source": "alphaops_vnext_policy_replay",
            "production_policy": "alphaops_vnext_production",
            "current_holdings_source": "alphaops_vnext_policy_target_book",
        }
    )
    return row


def rebuild_cash_rows(book: pd.DataFrame, portfolio_kind: str, selection_reason: str) -> pd.DataFrame:
    if book.empty or "rebalance_date" not in book.columns or "ticker" not in book.columns:
        return book
    out = book.copy()
    out["rebalance_date"] = pd.to_datetime(out["rebalance_date"], errors="coerce")
    out = out.dropna(subset=["rebalance_date"])
    out["ticker"] = out["ticker"].astype(str).str.upper().str.strip()
    out["weight"] = pd.to_numeric(out.get("weight", 0.0), errors="coerce").fillna(0.0)
    if "target_weight" in out.columns:
        out["target_weight"] = pd.to_numeric(out["target_weight"], errors="coerce").fillna(out["weight"])
    else:
        out["target_weight"] = out["weight"]
    rebuilt: list[pd.DataFrame] = []
    for raw_dt in sorted(out["rebalance_date"].dropna().unique()):
        dt = pd.Timestamp(raw_dt).normalize()
        day = out[out["rebalance_date"].dt.normalize().eq(dt)].copy()
        stock_mask = ~day["ticker"].isin(CASH_TICKERS)
        stock_weight = float(day.loc[stock_mask, "weight"].sum())
        cash_weight = max(0.0, 1.0 - stock_weight)
        cash_mask = day["ticker"].isin(CASH_TICKERS)
        if cash_mask.any():
            first_cash_idx = day.index[cash_mask][0]
            day.loc[cash_mask, ["weight", "target_weight"]] = 0.0
            day.loc[first_cash_idx, "weight"] = cash_weight
            day.loc[first_cash_idx, "target_weight"] = cash_weight
            if "selection_reason" in day.columns:
                day.loc[first_cash_idx, "selection_reason"] = selection_reason
        elif cash_weight > 1e-10:
            template = day.iloc[0] if not day.empty else None
            cash = capacity_cash_row(dt, portfolio_kind, cash_weight, template)
            cash["selection_reason"] = selection_reason
            day = pd.concat([day, pd.DataFrame([cash])], ignore_index=True)
        rebuilt.append(day)
    result = pd.concat(rebuilt, ignore_index=True) if rebuilt else out
    result["rebalance_date"] = pd.to_datetime(result["rebalance_date"], errors="coerce").dt.date.astype(str)
    return result.sort_values(["rebalance_date", "weight"], ascending=[True, False]).reset_index(drop=True)


def apply_main_neutral_regime_churn_filter(
    book: pd.DataFrame,
    portfolio_kind: str,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    if portfolio_kind != "main":
        return book, {
            "status": "skipped",
            "reason": "main_only_filter",
            "portfolio": portfolio_kind,
            "schema_version": "alphaops-vnext-main-neutral-churn-filter-v1",
        }
    if book.empty:
        return book, {
            "status": "skipped",
            "reason": "empty_book",
            "portfolio": portfolio_kind,
            "schema_version": "alphaops-vnext-main-neutral-churn-filter-v1",
        }
    required = {"rebalance_date", "ticker", "weight", "regime_state"}
    missing = sorted(required - set(book.columns))
    if missing:
        return book, {
            "status": "blocked",
            "reason": "missing_required_columns",
            "missing_columns": missing,
            "portfolio": portfolio_kind,
            "schema_version": "alphaops-vnext-main-neutral-churn-filter-v1",
        }
    working = book.copy()
    working["rebalance_date"] = pd.to_datetime(working["rebalance_date"], errors="coerce")
    working = working.dropna(subset=["rebalance_date"])
    working["ticker"] = working["ticker"].astype(str).str.upper().str.strip()
    cash_rows = working[working["ticker"].isin(CASH_TICKERS)].copy()
    stock_rows = working[~working["ticker"].isin(CASH_TICKERS)].copy()
    swap_counts = compute_swap_counts(stock_rows, MAIN_NEUTRAL_CHURN_FILTER_WINDOW_MONTHS)
    filtered_stock, decisions = apply_churn_filter(
        stock_rows,
        swap_counts,
        swap_threshold=MAIN_NEUTRAL_CHURN_FILTER_SWAP_THRESHOLD,
        target_regimes=MAIN_NEUTRAL_CHURN_FILTER_TARGET_REGIMES,
    )
    filtered = pd.concat([filtered_stock, cash_rows], ignore_index=True) if not cash_rows.empty else filtered_stock
    filtered = rebuild_cash_rows(
        filtered,
        portfolio_kind,
        "cash_from_main_neutral_churn_filter",
    )
    blocked = [d for d in decisions if d.get("action") == "blocked_entry"]
    top_blocked = Counter(str(d.get("ticker") or "").upper() for d in blocked if d.get("ticker"))
    payload = {
        "schema_version": "alphaops-vnext-main-neutral-churn-filter-v1",
        "status": "completed",
        "portfolio": portfolio_kind,
        "swap_threshold": MAIN_NEUTRAL_CHURN_FILTER_SWAP_THRESHOLD,
        "window_months": MAIN_NEUTRAL_CHURN_FILTER_WINDOW_MONTHS,
        "target_regimes": list(MAIN_NEUTRAL_CHURN_FILTER_TARGET_REGIMES),
        "input_row_count": int(len(book)),
        "output_row_count": int(len(filtered)),
        "stock_rows_removed": int(len(stock_rows) - len(filtered_stock)),
        "neutral_entries_blocked": int(len(blocked)),
        "weight_dropped_total": float(sum(safe_float(d.get("weight_dropped")) for d in blocked)),
        "top_blocked_tickers": [{"ticker": t, "count": c} for t, c in top_blocked.most_common(15)],
        "blocked_entries_sample": blocked[:30],
        "cash_rebuilt_explicitly": True,
        "research_only": False,
        "production_activation_allowed": True,
    }
    return filtered, payload


def apply_neutral_metals_new_entry_block(
    book: pd.DataFrame,
    portfolio_kind: str,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    schema_version = "alphaops-vnext-neutral-metals-new-entry-block-v1"
    if portfolio_kind not in {"main", "concentrated"}:
        return book, {
            "status": "skipped",
            "reason": "unsupported_portfolio",
            "portfolio": portfolio_kind,
            "schema_version": schema_version,
        }
    if book.empty:
        return book, {
            "status": "skipped",
            "reason": "empty_book",
            "portfolio": portfolio_kind,
            "schema_version": schema_version,
        }
    required = {
        "rebalance_date",
        "ticker",
        "weight",
        "sector",
        "industry_group",
        "primary_lane",
        "market_style_regime_label",
        "regime_state",
        "prior_weight",
        "holding_state",
        "hold_replace_decision",
    }
    missing = sorted(required - set(book.columns))
    if missing:
        return book, {
            "status": "blocked",
            "reason": "missing_required_columns",
            "missing_columns": missing,
            "portfolio": portfolio_kind,
            "schema_version": schema_version,
        }

    working = book.copy()
    working["rebalance_date"] = pd.to_datetime(working["rebalance_date"], errors="coerce")
    working = working.dropna(subset=["rebalance_date"])
    working["ticker"] = working["ticker"].map(clean_ticker)
    working["weight"] = pd.to_numeric(working["weight"], errors="coerce").fillna(0.0)
    working["target_weight"] = pd.to_numeric(working.get("target_weight", working["weight"]), errors="coerce").fillna(
        working["weight"]
    )

    ticker = working["ticker"]
    sector = working["sector"].astype(str).str.strip()
    industry = working["industry_group"].astype(str).str.lower()
    lane = working["primary_lane"].astype(str).str.upper().str.strip()
    style = working["market_style_regime_label"].astype(str).str.strip().str.lower()
    regime = working["regime_state"].astype(str).str.strip().str.lower()
    holding = working["holding_state"].astype(str).str.upper().str.strip()
    decision = working["hold_replace_decision"].astype(str).str.lower().str.strip()
    prior_weight = pd.to_numeric(working["prior_weight"], errors="coerce").fillna(0.0)

    explicit_hold = holding.isin({"HOLD", "KEEP", "PRIOR"}) | decision.isin(
        {"keep_prior", "keep_prior_holding", "hold", "held"}
    )
    is_new_entry = (~explicit_hold) & (
        holding.eq("NEW") | decision.eq("new_entry") | prior_weight.le(1e-12)
    )
    industry_match = pd.Series(False, index=working.index)
    for term in NEUTRAL_METALS_NEW_ENTRY_BLOCK_INDUSTRY_TERMS:
        industry_match = industry_match | industry.str.contains(term, na=False)
    block_mask = (
        ~ticker.isin(CASH_TICKERS)
        & sector.eq(NEUTRAL_METALS_NEW_ENTRY_BLOCK_SECTOR)
        & industry_match
        & lane.isin(NEUTRAL_METALS_NEW_ENTRY_BLOCK_LANES)
        & style.eq(NEUTRAL_METALS_NEW_ENTRY_BLOCK_STYLE_REGIME)
        & regime.isin(NEUTRAL_METALS_NEW_ENTRY_BLOCK_REGIMES)
        & is_new_entry
    )

    blocked_rows = working.loc[block_mask].copy()
    kept = working.loc[~block_mask].copy()
    filtered = rebuild_cash_rows(
        kept,
        portfolio_kind,
        "cash_from_neutral_metals_new_entry_block",
    )
    top_blocked = Counter(blocked_rows["ticker"].astype(str).str.upper()) if not blocked_rows.empty else Counter()
    blocked_sample = []
    for _, row in blocked_rows.head(30).iterrows():
        blocked_sample.append(
            {
                "rebalance_date": date_text(row.get("rebalance_date")),
                "ticker": clean_ticker(row.get("ticker")),
                "weight_dropped": safe_float(row.get("weight")),
                "sector": str(row.get("sector") or ""),
                "industry_group": str(row.get("industry_group") or ""),
                "primary_lane": str(row.get("primary_lane") or ""),
                "market_style_regime_label": str(row.get("market_style_regime_label") or ""),
                "regime_state": str(row.get("regime_state") or ""),
                "holding_state": str(row.get("holding_state") or ""),
                "hold_replace_decision": str(row.get("hold_replace_decision") or ""),
                "prior_weight": safe_float(row.get("prior_weight")),
            }
        )
    payload = {
        "schema_version": schema_version,
        "status": "completed",
        "portfolio": portfolio_kind,
        "sector": NEUTRAL_METALS_NEW_ENTRY_BLOCK_SECTOR,
        "industry_terms": list(NEUTRAL_METALS_NEW_ENTRY_BLOCK_INDUSTRY_TERMS),
        "lanes": list(NEUTRAL_METALS_NEW_ENTRY_BLOCK_LANES),
        "target_regimes": list(NEUTRAL_METALS_NEW_ENTRY_BLOCK_REGIMES),
        "style_regime": NEUTRAL_METALS_NEW_ENTRY_BLOCK_STYLE_REGIME,
        "input_row_count": int(len(book)),
        "output_row_count": int(len(filtered)),
        "stock_rows_removed": int(len(blocked_rows)),
        "blocked_new_entries": int(len(blocked_rows)),
        "weight_dropped_total": float(blocked_rows["weight"].sum()) if not blocked_rows.empty else 0.0,
        "top_blocked_tickers": [{"ticker": t, "count": c} for t, c in top_blocked.most_common(15)],
        "blocked_entries_sample": blocked_sample,
        "cash_rebuilt_explicitly": True,
        "research_only": False,
        "production_activation_allowed": True,
    }
    return filtered, payload


def apply_main_defense_review_turnaround_new_entry_block(
    book: pd.DataFrame,
    portfolio_kind: str,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    schema_version = "alphaops-vnext-main-defense-review-turnaround-new-entry-block-v1"
    if portfolio_kind != "main":
        return book, {
            "status": "skipped",
            "reason": "main_only_filter",
            "portfolio": portfolio_kind,
            "schema_version": schema_version,
        }
    if book.empty:
        return book, {
            "status": "skipped",
            "reason": "empty_book",
            "portfolio": portfolio_kind,
            "schema_version": schema_version,
        }
    required = {
        "rebalance_date",
        "ticker",
        "weight",
        "primary_lane",
        "market_style_regime_label",
        "regime_state",
        "crisis_state",
        "prior_weight",
        "holding_state",
        "hold_replace_decision",
    }
    missing = sorted(required - set(book.columns))
    if missing:
        return book, {
            "status": "blocked",
            "reason": "missing_required_columns",
            "missing_columns": missing,
            "portfolio": portfolio_kind,
            "schema_version": schema_version,
        }

    working = book.copy()
    working["rebalance_date"] = pd.to_datetime(working["rebalance_date"], errors="coerce")
    working = working.dropna(subset=["rebalance_date"])
    working["ticker"] = working["ticker"].map(clean_ticker)
    working["weight"] = pd.to_numeric(working["weight"], errors="coerce").fillna(0.0)
    working["target_weight"] = pd.to_numeric(working.get("target_weight", working["weight"]), errors="coerce").fillna(
        working["weight"]
    )

    ticker = working["ticker"]
    lane = working["primary_lane"].astype(str).str.upper().str.strip()
    style = working["market_style_regime_label"].astype(str).str.strip().str.lower()
    regime = working["regime_state"].astype(str).str.strip().str.lower()
    crisis = working["crisis_state"].astype(str).str.upper().str.strip()
    holding = working["holding_state"].astype(str).str.upper().str.strip()
    decision = working["hold_replace_decision"].astype(str).str.lower().str.strip()
    prior_weight = pd.to_numeric(working["prior_weight"], errors="coerce").fillna(0.0)

    explicit_hold = holding.isin({"HOLD", "KEEP", "PRIOR"}) | decision.isin(
        {"keep_prior", "keep_prior_holding", "hold", "held"}
    )
    is_new_entry = (~explicit_hold) & (
        holding.eq("NEW") | decision.eq("new_entry") | prior_weight.le(1e-12)
    )
    block_mask = (
        ~ticker.isin(CASH_TICKERS)
        & lane.eq(MAIN_DEFENSE_REVIEW_TURNAROUND_NEW_ENTRY_BLOCK_LANE)
        & style.eq(MAIN_DEFENSE_REVIEW_TURNAROUND_NEW_ENTRY_BLOCK_STYLE)
        & regime.eq(MAIN_DEFENSE_REVIEW_TURNAROUND_NEW_ENTRY_BLOCK_REGIME)
        & crisis.eq(MAIN_DEFENSE_REVIEW_TURNAROUND_NEW_ENTRY_BLOCK_CRISIS)
        & is_new_entry
    )

    blocked_rows = working.loc[block_mask].copy()
    kept = working.loc[~block_mask].copy()
    filtered = rebuild_cash_rows(
        kept,
        portfolio_kind,
        "cash_from_main_defense_review_turnaround_new_entry_block",
    )
    top_blocked = Counter(blocked_rows["ticker"].astype(str).str.upper()) if not blocked_rows.empty else Counter()
    blocked_sample = []
    for _, row in blocked_rows.head(30).iterrows():
        blocked_sample.append(
            {
                "rebalance_date": date_text(row.get("rebalance_date")),
                "ticker": clean_ticker(row.get("ticker")),
                "weight_dropped": safe_float(row.get("weight")),
                "sector": str(row.get("sector") or ""),
                "industry_group": str(row.get("industry_group") or ""),
                "primary_lane": str(row.get("primary_lane") or ""),
                "market_style_regime_label": str(row.get("market_style_regime_label") or ""),
                "regime_state": str(row.get("regime_state") or ""),
                "crisis_state": str(row.get("crisis_state") or ""),
                "holding_state": str(row.get("holding_state") or ""),
                "hold_replace_decision": str(row.get("hold_replace_decision") or ""),
                "prior_weight": safe_float(row.get("prior_weight")),
            }
        )
    payload = {
        "schema_version": schema_version,
        "status": "completed",
        "portfolio": portfolio_kind,
        "lane": MAIN_DEFENSE_REVIEW_TURNAROUND_NEW_ENTRY_BLOCK_LANE,
        "style_regime": MAIN_DEFENSE_REVIEW_TURNAROUND_NEW_ENTRY_BLOCK_STYLE,
        "regime_state": MAIN_DEFENSE_REVIEW_TURNAROUND_NEW_ENTRY_BLOCK_REGIME,
        "crisis_state": MAIN_DEFENSE_REVIEW_TURNAROUND_NEW_ENTRY_BLOCK_CRISIS,
        "input_row_count": int(len(book)),
        "output_row_count": int(len(filtered)),
        "stock_rows_removed": int(len(blocked_rows)),
        "blocked_new_entries": int(len(blocked_rows)),
        "weight_dropped_total": float(blocked_rows["weight"].sum()) if not blocked_rows.empty else 0.0,
        "top_blocked_tickers": [{"ticker": t, "count": c} for t, c in top_blocked.most_common(15)],
        "blocked_entries_sample": blocked_sample,
        "cash_rebuilt_explicitly": True,
        "research_only": False,
        "production_activation_allowed": True,
    }
    return filtered, payload


def apply_main_defense_review_balanced_new_entry_block(
    book: pd.DataFrame,
    portfolio_kind: str,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    schema_version = "alphaops-vnext-main-defense-review-balanced-new-entry-block-v1"
    if portfolio_kind != "main":
        return book, {
            "status": "skipped",
            "reason": "main_only_filter",
            "portfolio": portfolio_kind,
            "schema_version": schema_version,
        }
    if book.empty:
        return book, {
            "status": "skipped",
            "reason": "empty_book",
            "portfolio": portfolio_kind,
            "schema_version": schema_version,
        }
    required = {
        "rebalance_date",
        "ticker",
        "weight",
        "primary_lane",
        "market_style_regime_label",
        "regime_state",
        "crisis_state",
        "breakout_setup_quality_score",
        "prior_weight",
        "holding_state",
        "hold_replace_decision",
    }
    missing = sorted(required - set(book.columns))
    if missing:
        return book, {
            "status": "blocked",
            "reason": "missing_required_columns",
            "missing_columns": missing,
            "portfolio": portfolio_kind,
            "schema_version": schema_version,
        }

    working = book.copy()
    working["rebalance_date"] = pd.to_datetime(working["rebalance_date"], errors="coerce")
    working = working.dropna(subset=["rebalance_date"])
    working["ticker"] = working["ticker"].map(clean_ticker)
    working["weight"] = pd.to_numeric(working["weight"], errors="coerce").fillna(0.0)
    working["target_weight"] = pd.to_numeric(working.get("target_weight", working["weight"]), errors="coerce").fillna(
        working["weight"]
    )

    ticker = working["ticker"]
    lane = working["primary_lane"].astype(str).str.upper().str.strip()
    style = working["market_style_regime_label"].astype(str).str.strip().str.lower()
    regime = working["regime_state"].astype(str).str.strip().str.lower()
    crisis = working["crisis_state"].astype(str).str.upper().str.strip()
    breakout = pd.to_numeric(working["breakout_setup_quality_score"], errors="coerce").fillna(1.0)
    holding = working["holding_state"].astype(str).str.upper().str.strip()
    decision = working["hold_replace_decision"].astype(str).str.lower().str.strip()
    prior_weight = pd.to_numeric(working["prior_weight"], errors="coerce").fillna(0.0)

    explicit_hold = holding.isin({"HOLD", "KEEP", "PRIOR", "WARNING"}) | decision.isin(
        {"keep_prior", "keep_prior_holding", "hold", "held"}
    )
    is_new_entry = (~explicit_hold) & (
        holding.eq("NEW") | decision.eq("new_entry") | prior_weight.le(1e-12)
    )
    block_mask = (
        ~ticker.isin(CASH_TICKERS)
        & lane.eq(MAIN_DEFENSE_REVIEW_BALANCED_NEW_ENTRY_BLOCK_LANE)
        & style.eq(MAIN_DEFENSE_REVIEW_BALANCED_NEW_ENTRY_BLOCK_STYLE)
        & regime.eq(MAIN_DEFENSE_REVIEW_BALANCED_NEW_ENTRY_BLOCK_REGIME)
        & crisis.eq(MAIN_DEFENSE_REVIEW_BALANCED_NEW_ENTRY_BLOCK_CRISIS)
        & breakout.lt(MAIN_DEFENSE_REVIEW_BALANCED_NEW_ENTRY_BLOCK_BREAKOUT_THRESHOLD)
        & is_new_entry
    )

    blocked_rows = working.loc[block_mask].copy()
    kept = working.loc[~block_mask].copy()
    filtered = rebuild_cash_rows(
        kept,
        portfolio_kind,
        "cash_from_main_defense_review_balanced_new_entry_block",
    )
    top_blocked = Counter(blocked_rows["ticker"].astype(str).str.upper()) if not blocked_rows.empty else Counter()
    blocked_sample = []
    for _, row in blocked_rows.head(30).iterrows():
        blocked_sample.append(
            {
                "rebalance_date": date_text(row.get("rebalance_date")),
                "ticker": clean_ticker(row.get("ticker")),
                "weight_dropped": safe_float(row.get("weight")),
                "sector": str(row.get("sector") or ""),
                "industry_group": str(row.get("industry_group") or ""),
                "primary_lane": str(row.get("primary_lane") or ""),
                "market_style_regime_label": str(row.get("market_style_regime_label") or ""),
                "regime_state": str(row.get("regime_state") or ""),
                "crisis_state": str(row.get("crisis_state") or ""),
                "breakout_setup_quality_score": safe_float(row.get("breakout_setup_quality_score")),
                "holding_state": str(row.get("holding_state") or ""),
                "hold_replace_decision": str(row.get("hold_replace_decision") or ""),
                "prior_weight": safe_float(row.get("prior_weight")),
            }
        )
    payload = {
        "schema_version": schema_version,
        "status": "completed",
        "portfolio": portfolio_kind,
        "lane": MAIN_DEFENSE_REVIEW_BALANCED_NEW_ENTRY_BLOCK_LANE,
        "style_regime": MAIN_DEFENSE_REVIEW_BALANCED_NEW_ENTRY_BLOCK_STYLE,
        "regime_state": MAIN_DEFENSE_REVIEW_BALANCED_NEW_ENTRY_BLOCK_REGIME,
        "crisis_state": MAIN_DEFENSE_REVIEW_BALANCED_NEW_ENTRY_BLOCK_CRISIS,
        "breakout_threshold": MAIN_DEFENSE_REVIEW_BALANCED_NEW_ENTRY_BLOCK_BREAKOUT_THRESHOLD,
        "input_row_count": int(len(book)),
        "output_row_count": int(len(filtered)),
        "stock_rows_removed": int(len(blocked_rows)),
        "blocked_new_entries": int(len(blocked_rows)),
        "weight_dropped_total": float(blocked_rows["weight"].sum()) if not blocked_rows.empty else 0.0,
        "top_blocked_tickers": [{"ticker": t, "count": c} for t, c in top_blocked.most_common(15)],
        "blocked_entries_sample": blocked_sample,
        "cash_rebuilt_explicitly": True,
        "research_only": False,
        "production_activation_allowed": True,
    }
    return filtered, payload


def apply_concentrated_green_benchmark_risk_cyclical_new_entry_block(
    book: pd.DataFrame,
    portfolio_kind: str,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    schema_version = "alphaops-vnext-concentrated-green-benchmark-risk-cyclical-new-entry-block-v1"
    if portfolio_kind != "concentrated":
        return book, {
            "status": "skipped",
            "reason": "concentrated_only_filter",
            "portfolio": portfolio_kind,
            "schema_version": schema_version,
        }
    if book.empty:
        return book, {
            "status": "skipped",
            "reason": "empty_book",
            "portfolio": portfolio_kind,
            "schema_version": schema_version,
        }
    required = {
        "rebalance_date",
        "ticker",
        "weight",
        "sector",
        "primary_lane",
        "market_style_regime_label",
        "regime_state",
        "crisis_state",
        "benchmark_risk_score",
        "atr14_pct",
        "breakout_setup_quality_score",
        "prior_weight",
        "holding_state",
        "hold_replace_decision",
    }
    missing = sorted(required - set(book.columns))
    if missing:
        return book, {
            "status": "blocked",
            "reason": "missing_required_columns",
            "missing_columns": missing,
            "portfolio": portfolio_kind,
            "schema_version": schema_version,
        }

    working = book.copy()
    working["rebalance_date"] = pd.to_datetime(working["rebalance_date"], errors="coerce")
    working = working.dropna(subset=["rebalance_date"])
    working["ticker"] = working["ticker"].map(clean_ticker)
    working["weight"] = pd.to_numeric(working["weight"], errors="coerce").fillna(0.0)
    working["target_weight"] = pd.to_numeric(working.get("target_weight", working["weight"]), errors="coerce").fillna(
        working["weight"]
    )

    ticker = working["ticker"]
    sector = working["sector"].astype(str).str.strip()
    lane = working["primary_lane"].astype(str).str.upper().str.strip()
    style = working["market_style_regime_label"].astype(str).str.strip().str.lower()
    regime = working["regime_state"].astype(str).str.strip().str.lower()
    crisis = working["crisis_state"].astype(str).str.upper().str.strip()
    holding = working["holding_state"].astype(str).str.upper().str.strip()
    decision = working["hold_replace_decision"].astype(str).str.lower().str.strip()
    prior_weight = pd.to_numeric(working["prior_weight"], errors="coerce").fillna(0.0)
    benchmark_risk = pd.to_numeric(working["benchmark_risk_score"], errors="coerce").fillna(0.0)
    atr14 = pd.to_numeric(working["atr14_pct"], errors="coerce").fillna(0.0)
    breakout = pd.to_numeric(working["breakout_setup_quality_score"], errors="coerce").fillna(1.0)

    explicit_hold = holding.isin({"HOLD", "KEEP", "PRIOR"}) | decision.isin(
        {"keep_prior", "keep_prior_holding", "hold", "held"}
    )
    is_new_entry = (~explicit_hold) & (
        holding.eq("NEW") | decision.eq("new_entry") | prior_weight.le(1e-12)
    )
    block_mask = (
        ~ticker.isin(CASH_TICKERS)
        & sector.isin(CONCENTRATED_GREEN_BENCHMARK_RISK_CYCLICAL_NEW_ENTRY_BLOCK_SECTORS)
        & lane.eq("MARKET_LEADER")
        & style.eq("quality_compounder")
        & regime.eq("neutral")
        & crisis.eq("GREEN")
        & is_new_entry
        & working["weight"].ge(CONCENTRATED_GREEN_BENCHMARK_RISK_CYCLICAL_NEW_ENTRY_BLOCK_MIN_WEIGHT)
        & benchmark_risk.ge(CONCENTRATED_GREEN_BENCHMARK_RISK_CYCLICAL_NEW_ENTRY_BLOCK_BENCHMARK_RISK_THRESHOLD)
        & atr14.ge(CONCENTRATED_GREEN_BENCHMARK_RISK_CYCLICAL_NEW_ENTRY_BLOCK_ATR_THRESHOLD)
        & breakout.lt(CONCENTRATED_GREEN_BENCHMARK_RISK_CYCLICAL_NEW_ENTRY_BLOCK_BREAKOUT_THRESHOLD)
    )

    blocked_rows = working.loc[block_mask].copy()
    kept = working.loc[~block_mask].copy()
    filtered = rebuild_cash_rows(
        kept,
        portfolio_kind,
        "cash_from_concentrated_green_benchmark_risk_cyclical_new_entry_block",
    )
    top_blocked = Counter(blocked_rows["ticker"].astype(str).str.upper()) if not blocked_rows.empty else Counter()
    blocked_sample = []
    for _, row in blocked_rows.head(30).iterrows():
        blocked_sample.append(
            {
                "rebalance_date": date_text(row.get("rebalance_date")),
                "ticker": clean_ticker(row.get("ticker")),
                "weight_dropped": safe_float(row.get("weight")),
                "sector": str(row.get("sector") or ""),
                "industry_group": str(row.get("industry_group") or ""),
                "primary_lane": str(row.get("primary_lane") or ""),
                "market_style_regime_label": str(row.get("market_style_regime_label") or ""),
                "regime_state": str(row.get("regime_state") or ""),
                "crisis_state": str(row.get("crisis_state") or ""),
                "benchmark_risk_score": safe_float(row.get("benchmark_risk_score")),
                "atr14_pct": safe_float(row.get("atr14_pct")),
                "breakout_setup_quality_score": safe_float(row.get("breakout_setup_quality_score")),
                "holding_state": str(row.get("holding_state") or ""),
                "hold_replace_decision": str(row.get("hold_replace_decision") or ""),
                "prior_weight": safe_float(row.get("prior_weight")),
            }
        )
    payload = {
        "schema_version": schema_version,
        "status": "completed",
        "portfolio": portfolio_kind,
        "min_weight": CONCENTRATED_GREEN_BENCHMARK_RISK_CYCLICAL_NEW_ENTRY_BLOCK_MIN_WEIGHT,
        "benchmark_risk_threshold": CONCENTRATED_GREEN_BENCHMARK_RISK_CYCLICAL_NEW_ENTRY_BLOCK_BENCHMARK_RISK_THRESHOLD,
        "atr_threshold": CONCENTRATED_GREEN_BENCHMARK_RISK_CYCLICAL_NEW_ENTRY_BLOCK_ATR_THRESHOLD,
        "breakout_threshold": CONCENTRATED_GREEN_BENCHMARK_RISK_CYCLICAL_NEW_ENTRY_BLOCK_BREAKOUT_THRESHOLD,
        "sectors": sorted(CONCENTRATED_GREEN_BENCHMARK_RISK_CYCLICAL_NEW_ENTRY_BLOCK_SECTORS),
        "input_row_count": int(len(book)),
        "output_row_count": int(len(filtered)),
        "stock_rows_removed": int(len(blocked_rows)),
        "blocked_new_entries": int(len(blocked_rows)),
        "weight_dropped_total": float(blocked_rows["weight"].sum()) if not blocked_rows.empty else 0.0,
        "top_blocked_tickers": [{"ticker": t, "count": c} for t, c in top_blocked.most_common(15)],
        "blocked_entries_sample": blocked_sample,
        "cash_rebuilt_explicitly": True,
        "research_only": False,
        "production_activation_allowed": True,
    }
    return filtered, payload


def main_fast_crash_price_features(px: pd.DataFrame, dt: pd.Timestamp) -> dict[str, Any]:
    if px.empty:
        return {"coverage": False}
    idx = pd.DatetimeIndex(px.index)
    pos = int(idx.searchsorted(pd.Timestamp(dt).normalize(), side="right")) - 1
    if pos < 0:
        return {"coverage": False}
    close = pd.to_numeric(px["close"], errors="coerce")
    cur = safe_float(close.iloc[pos], 0.0)
    if cur <= 0:
        return {"coverage": False}
    start_5 = close.iloc[pos - 5] if pos >= 5 else float("nan")
    start_10 = close.iloc[pos - 10] if pos >= 10 else float("nan")
    ret_5d = float(cur / start_5 - 1.0) if safe_float(start_5) > 0 else 0.0
    ret_10d = float(cur / start_10 - 1.0) if safe_float(start_10) > 0 else 0.0
    return {
        "coverage": True,
        "close": cur,
        "ret_5d": ret_5d,
        "ret_10d": ret_10d,
    }


def apply_main_fast_crash_hedge(
    book: pd.DataFrame,
    portfolio_kind: str,
    *,
    price_cache: Path,
) -> tuple[pd.DataFrame, dict[str, Any], pd.DataFrame]:
    schema_version = "alphaops-vnext-main-fast-crash-hedge-v1"
    if portfolio_kind != "main":
        return book, {
            "schema_version": schema_version,
            "status": "skipped",
            "reason": "main_only",
            "portfolio": portfolio_kind,
        }, pd.DataFrame()
    if not main_fast_crash_hedge_enabled():
        return book, {
            "schema_version": schema_version,
            "status": "disabled",
            "portfolio": portfolio_kind,
        }, pd.DataFrame()
    if book.empty or "rebalance_date" not in book.columns or "ticker" not in book.columns or "weight" not in book.columns:
        return book, {
            "schema_version": schema_version,
            "status": "blocked",
            "reason": "empty_or_missing_required_columns",
            "portfolio": portfolio_kind,
        }, pd.DataFrame()

    hedge_ticker = main_fast_crash_hedge_ticker()
    benchmark_ticker = main_fast_crash_hedge_benchmark()
    hedge_weight = main_fast_crash_hedge_weight()
    risk_buffer_weight = main_fast_crash_risk_buffer_weight()
    if not hedge_ticker or hedge_ticker in CASH_TICKERS or hedge_weight <= 1e-12:
        return book, {
            "schema_version": schema_version,
            "status": "blocked",
            "reason": "invalid_hedge_config",
            "portfolio": portfolio_kind,
            "hedge_ticker": hedge_ticker,
            "hedge_weight": hedge_weight,
        }, pd.DataFrame()

    hedge_px = load_price_series(price_cache, hedge_ticker)
    benchmark_px = load_price_series(price_cache, benchmark_ticker)
    if hedge_px.empty or benchmark_px.empty:
        return book, {
            "schema_version": schema_version,
            "status": "blocked",
            "reason": "missing_hedge_or_benchmark_price",
            "portfolio": portfolio_kind,
            "hedge_ticker": hedge_ticker,
            "benchmark_ticker": benchmark_ticker,
            "hedge_price_rows": int(len(hedge_px)),
            "benchmark_price_rows": int(len(benchmark_px)),
        }, pd.DataFrame()

    working = book.copy()
    working["rebalance_date"] = pd.to_datetime(working["rebalance_date"], errors="coerce")
    working = working.dropna(subset=["rebalance_date"])
    working["ticker"] = working["ticker"].map(clean_ticker)
    working["weight"] = pd.to_numeric(working["weight"], errors="coerce").fillna(0.0)
    if "target_weight" in working.columns:
        working["target_weight"] = pd.to_numeric(working["target_weight"], errors="coerce").fillna(working["weight"])
    else:
        working["target_weight"] = working["weight"]

    rebuilt: list[pd.DataFrame] = []
    action_rows: list[dict[str, Any]] = []
    for raw_dt in sorted(working["rebalance_date"].dropna().unique()):
        dt = pd.Timestamp(raw_dt).normalize()
        day = working[working["rebalance_date"].eq(raw_dt)].copy()
        features = main_fast_crash_price_features(benchmark_px, dt)
        ret_5d = safe_float(features.get("ret_5d"))
        ret_10d = safe_float(features.get("ret_10d"))
        signal = bool(features.get("coverage") and (ret_5d <= MAIN_FAST_CRASH_HEDGE_5D_DROP or ret_10d <= MAIN_FAST_CRASH_HEDGE_10D_DROP))
        day["main_fast_crash_hedge_enabled"] = True
        day["main_fast_crash_hedge_signal"] = bool(signal)
        day["main_fast_crash_hedge_ticker"] = hedge_ticker
        day["main_fast_crash_hedge_weight"] = 0.0
        day["main_fast_crash_risk_buffer_weight"] = 0.0
        day["main_fast_crash_hedge_benchmark_ret_5d"] = ret_5d
        day["main_fast_crash_hedge_benchmark_ret_10d"] = ret_10d
        stock_mask = ~day["ticker"].isin(CASH_TICKERS | {hedge_ticker})
        hedge_existing_mask = day["ticker"].eq(hedge_ticker)
        if hedge_existing_mask.any():
            day = day.loc[~hedge_existing_mask].copy()
            stock_mask = ~day["ticker"].isin(CASH_TICKERS | {hedge_ticker})
        pre_stock = float(day.loc[stock_mask, "weight"].sum())
        hedge_w = min(hedge_weight, max(0.0, pre_stock)) if signal else 0.0
        risk_buffer_w = min(risk_buffer_weight, max(0.0, pre_stock - hedge_w)) if risk_buffer_weight > 1e-12 else 0.0
        total_funded_w = min(pre_stock, hedge_w + risk_buffer_w)
        if total_funded_w > 1e-12 and pre_stock > 1e-12:
            scale = max(0.0, (pre_stock - total_funded_w) / pre_stock)
            day.loc[stock_mask, "weight"] = day.loc[stock_mask, "weight"] * scale
            day.loc[stock_mask, "target_weight"] = day.loc[stock_mask, "target_weight"] * scale
            if "selection_reason" in day.columns:
                reason_suffix = "|main_fast_crash_hedge_funded" if hedge_w > 1e-12 else "|main_fast_crash_risk_buffer"
                day.loc[stock_mask, "selection_reason"] = day.loc[stock_mask, "selection_reason"].astype(str) + reason_suffix
            day.loc[stock_mask, "main_fast_crash_risk_buffer_weight"] = risk_buffer_w
        if signal and hedge_w > 1e-12 and pre_stock > 1e-12:
            template = day.iloc[0] if not day.empty else pd.Series(dtype=object)
            hedge_row = dict(template.to_dict())
            hedge_row.update(
                {
                    "rebalance_date": dt.date().isoformat(),
                    "ticker": hedge_ticker,
                    "Name": f"{hedge_ticker} hedge",
                    "sector": "Hedge",
                    "industry_group": "Inverse ETF Hedge",
                    "weight": hedge_w,
                    "target_weight": hedge_w,
                    "portfolio_kind": portfolio_kind,
                    "primary_lane": "HEDGE",
                    "holding_state": "HEDGE",
                    "hold_replace_decision": "main_fast_crash_hedge",
                    "selection_reason": "main_fast_crash_hedge_funded_overlay",
                    "main_fast_crash_hedge_enabled": True,
                    "main_fast_crash_hedge_signal": True,
                    "main_fast_crash_hedge_ticker": hedge_ticker,
                    "main_fast_crash_hedge_weight": hedge_w,
                    "main_fast_crash_risk_buffer_weight": risk_buffer_w,
                    "main_fast_crash_hedge_benchmark_ret_5d": ret_5d,
                    "main_fast_crash_hedge_benchmark_ret_10d": ret_10d,
                    "production_policy": "alphaops_vnext_production",
                    "current_holdings_source": "alphaops_vnext_policy_target_book",
                }
            )
            day = pd.concat([day, pd.DataFrame([hedge_row])], ignore_index=True)
        post_stock = float(day.loc[~day["ticker"].isin(CASH_TICKERS | {hedge_ticker}), "weight"].sum())
        cash_weight = max(0.0, 1.0 - float(day.loc[~day["ticker"].isin(CASH_TICKERS), "weight"].sum()))
        cash_mask = day["ticker"].isin(CASH_TICKERS)
        if cash_mask.any():
            first_cash_idx = day.index[cash_mask][0]
            day.loc[cash_mask, ["weight", "target_weight"]] = 0.0
            day.loc[first_cash_idx, "weight"] = cash_weight
            day.loc[first_cash_idx, "target_weight"] = cash_weight
            if "selection_reason" in day.columns:
                day.loc[first_cash_idx, "selection_reason"] = "cash_from_main_fast_crash_hedge"
        elif cash_weight > 1e-10:
            template = day.iloc[0] if not day.empty else None
            cash = capacity_cash_row(dt, portfolio_kind, cash_weight, template)
            cash["selection_reason"] = "cash_from_main_fast_crash_hedge"
            day = pd.concat([day, pd.DataFrame([cash])], ignore_index=True)
        total_weight = float(day["weight"].sum())
        action_rows.append(
            {
                "rebalance_date": dt.date().isoformat(),
                "portfolio_kind": portfolio_kind,
                "hedge_ticker": hedge_ticker,
                "benchmark_ticker": benchmark_ticker,
                "signal": bool(signal),
                "hedge_weight": hedge_w,
                "risk_buffer_weight": risk_buffer_w,
                "total_funded_weight": total_funded_w,
                "pre_stock_weight": pre_stock,
                "post_stock_weight": post_stock,
                "cash_weight": cash_weight,
                "total_weight": total_weight,
                "benchmark_ret_5d": ret_5d,
                "benchmark_ret_10d": ret_10d,
            }
        )
        rebuilt.append(day)

    result = pd.concat(rebuilt, ignore_index=True) if rebuilt else working
    result["rebalance_date"] = pd.to_datetime(result["rebalance_date"], errors="coerce").dt.date.astype(str)
    result = result.sort_values(["rebalance_date", "weight"], ascending=[True, False]).reset_index(drop=True)
    actions = pd.DataFrame(action_rows)
    hedge_dates = int(pd.to_numeric(actions.get("hedge_weight", pd.Series(dtype=float)), errors="coerce").gt(0.0).sum()) if not actions.empty else 0
    summary = {
        "schema_version": schema_version,
        "status": "completed",
        "portfolio": portfolio_kind,
        "hedge_ticker": hedge_ticker,
        "benchmark_ticker": benchmark_ticker,
        "hedge_weight": hedge_weight,
        "risk_buffer_weight": risk_buffer_weight,
        "ret_5d_threshold": MAIN_FAST_CRASH_HEDGE_5D_DROP,
        "ret_10d_threshold": MAIN_FAST_CRASH_HEDGE_10D_DROP,
        "rebalance_dates_total": int(len(actions)),
        "hedge_dates": hedge_dates,
        "avg_hedge_weight": float(pd.to_numeric(actions.get("hedge_weight", pd.Series(dtype=float)), errors="coerce").mean()) if not actions.empty else 0.0,
        "max_hedge_weight": float(pd.to_numeric(actions.get("hedge_weight", pd.Series(dtype=float)), errors="coerce").max()) if not actions.empty else 0.0,
        "funded_by_pro_rata_long_reduction": True,
        "total_gross_leq_one": bool((pd.to_numeric(actions.get("total_weight", pd.Series(dtype=float)), errors="coerce").fillna(0.0) <= 1.000001).all()) if not actions.empty else True,
        "research_only": True,
        "production_activation_allowed": False,
    }
    return result, summary, actions


def apply_regime_capacity_overlay(
    book: pd.DataFrame,
    *,
    portfolio_kind: str,
) -> tuple[pd.DataFrame, dict[str, Any], pd.DataFrame]:
    """Apply broker-fillable capacity dampening to vNext production books.

    This promotes the historically useful regime-capacity sidecar into the
    vNext target book itself, but only for regimes configured below 1.0. The
    current default is intentionally asymmetric: main keeps its higher-CAGR
    exposure profile, while concentrated cuts gross exposure during confirmed
    bear/deep_bear months.
    """

    if book.empty or "rebalance_date" not in book.columns or "weight" not in book.columns:
        summary = {
            "portfolio": portfolio_kind,
            "status": "blocked",
            "reason": "empty_or_missing_required_columns",
            "multipliers": DEFAULT_REGIME_CAPACITY_MULTIPLIERS.get(portfolio_kind, {}),
            "rebalance_dates_total": 0,
            "rebalance_dates_dampened": 0,
        }
        return book, summary, pd.DataFrame()
    multipliers = DEFAULT_REGIME_CAPACITY_MULTIPLIERS.get(portfolio_kind, DEFAULT_REGIME_CAPACITY_MULTIPLIERS["main"])
    bull_floor_enabled = bool(
        phase_is_enabled("regime_capacity_bull_floor", default=False)
        or phase_is_enabled("bull_floor", default=False)
    )
    bull_floor, bull_floor_source = regime_capacity_bull_floor(portfolio_kind)
    bull_single_cap = float(DEFAULT_BULL_FLOOR_SINGLE_CAP.get(portfolio_kind, 0.20))
    bull_floor_dates = 0
    out = book.copy()
    out["rebalance_date"] = pd.to_datetime(out["rebalance_date"], errors="coerce")
    out = out.dropna(subset=["rebalance_date"])
    out["ticker"] = out["ticker"].map(clean_ticker)
    out["weight"] = pd.to_numeric(out["weight"], errors="coerce").fillna(0.0)
    if "target_weight" in out.columns:
        out["target_weight"] = pd.to_numeric(out["target_weight"], errors="coerce").fillna(out["weight"])
    else:
        out["target_weight"] = out["weight"]
    audit_rows: list[dict[str, Any]] = []
    rebuilt: list[pd.DataFrame] = []
    for raw_dt in sorted(out["rebalance_date"].dropna().unique()):
        dt = pd.Timestamp(raw_dt).normalize()
        day = out[out["rebalance_date"].eq(raw_dt)].copy()
        regime = dominant_text(day["regime_state"]) if "regime_state" in day.columns else "unknown"
        factor = float(multipliers.get(regime, 1.0))
        stock_mask = ~day["ticker"].isin(CASH_TICKERS)
        pre_stock = float(day.loc[stock_mask, "weight"].sum())
        bull_floor_applied = False
        if factor < 1.0 - 1e-12:
            day.loc[stock_mask, "weight"] = day.loc[stock_mask, "weight"] * factor
            day.loc[stock_mask, "target_weight"] = day.loc[stock_mask, "target_weight"] * factor
            day.loc[stock_mask, "selection_reason"] = (
                day.loc[stock_mask, "selection_reason"].astype(str) + "|regime_capacity_dampened"
                if "selection_reason" in day.columns
                else "regime_capacity_dampened"
            )
        elif bull_floor_enabled and regime in BULL_REGIME_STATES and pre_stock > 1e-9 and pre_stock < bull_floor - 1e-9:
            # Two-way door: lift a thinned bull-regime book to the floor via
            # capped water-filling (P0a IS-underinvestment fix). Respect the
            # per-name effective_single_weight_cap when present.
            idx = list(day.index[stock_mask])
            weights = [float(day.at[i, "weight"]) for i in idx]
            if "effective_single_weight_cap" in day.columns:
                ceilings = [
                    float(safe_float(day.at[i, "effective_single_weight_cap"], bull_single_cap) or bull_single_cap)
                    for i in idx
                ]
            else:
                ceilings = [bull_single_cap] * len(idx)
            lifted = capped_proportional_fill(weights, bull_floor, ceilings)
            for i, new_w in zip(idx, lifted):
                day.at[i, "weight"] = new_w
                if "target_weight" in day.columns:
                    day.at[i, "target_weight"] = new_w
            if "selection_reason" in day.columns:
                day.loc[stock_mask, "selection_reason"] = (
                    day.loc[stock_mask, "selection_reason"].astype(str) + "|regime_capacity_bull_floor_lifted"
                )
            bull_floor_applied = True
        post_stock = float(day.loc[stock_mask, "weight"].sum())
        cash_weight = max(0.0, 1.0 - post_stock)
        cash_mask = day["ticker"].isin(CASH_TICKERS)
        if cash_mask.any():
            first_cash_idx = day.index[cash_mask][0]
            day.loc[cash_mask, ["weight", "target_weight"]] = 0.0
            day.loc[first_cash_idx, "weight"] = cash_weight
            day.loc[first_cash_idx, "target_weight"] = cash_weight
            if "selection_reason" in day.columns:
                day.loc[first_cash_idx, "selection_reason"] = "cash_from_vnext_regime_capacity_overlay"
        elif cash_weight > 1e-10:
            template = day.iloc[0] if not day.empty else None
            day = pd.concat([day, pd.DataFrame([capacity_cash_row(dt, portfolio_kind, cash_weight, template)])], ignore_index=True)
        day["regime_capacity_overlay_status"] = "applied"
        day["regime_capacity_regime"] = regime
        day["regime_capacity_multiplier"] = factor
        day["regime_capacity_cash_target"] = cash_weight
        day["regime_capacity_policy"] = "alphaops_vnext_concentrated_bear_capacity" if portfolio_kind == "concentrated" else "alphaops_vnext_main_cap_only"
        day["regime_capacity_bull_floor_applied"] = bool(bull_floor_applied)
        if bull_floor_applied:
            bull_floor_dates += 1
        rebuilt.append(day)
        audit_rows.append(
            {
                "rebalance_date": dt.date().isoformat(),
                "portfolio_kind": portfolio_kind,
                "regime": regime,
                "multiplier": factor,
                "pre_stock_weight": pre_stock,
                "post_stock_weight": post_stock,
                "cash_weight": cash_weight,
                "bull_floor_applied": bool(bull_floor_applied),
                "rows_affected": int(stock_mask.sum() if (factor < 1.0 - 1e-12 or bull_floor_applied) else 0),
            }
        )
    result = pd.concat(rebuilt, ignore_index=True) if rebuilt else out
    result["rebalance_date"] = pd.to_datetime(result["rebalance_date"], errors="coerce").dt.date.astype(str)
    result = result.sort_values(["rebalance_date", "weight"], ascending=[True, False]).reset_index(drop=True)
    audit = pd.DataFrame(audit_rows)
    summary = {
        "portfolio": portfolio_kind,
        "status": "completed",
        "multipliers": multipliers,
        "rebalance_dates_total": int(len(audit)),
        "rebalance_dates_dampened": int((pd.to_numeric(audit.get("multiplier", pd.Series(dtype=float)), errors="coerce") < 1.0).sum()) if not audit.empty else 0,
        "bull_floor_enabled": bool(bull_floor_enabled),
        "bull_floor": bull_floor,
        "bull_floor_source": bull_floor_source,
        "rebalance_dates_bull_floor_lifted": int(bull_floor_dates),
        "avg_cash_weight": float(pd.to_numeric(audit.get("cash_weight", pd.Series(dtype=float)), errors="coerce").mean()) if not audit.empty else 0.0,
        "max_cash_weight": float(pd.to_numeric(audit.get("cash_weight", pd.Series(dtype=float)), errors="coerce").max()) if not audit.empty else 0.0,
    }
    return result, summary, audit


def write_operating_summary(latest_run: Path, output_dir: Path, summaries: dict[str, dict[str, Any]]) -> None:
    reports = latest_run / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    books: list[dict[str, Any]] = []
    for portfolio, filename in (
        ("main", "operating_main_target_book.csv"),
        ("concentrated", "operating_concentrated_target_book.csv"),
    ):
        row = dict(summaries.get(portfolio, {}))
        path = reports / filename
        row.update(
            {
                "portfolio": portfolio,
                "history_path": str(output_dir / f"official_{portfolio}_target_book.csv"),
                "latest_target_path": str(output_dir / "selected_latest.csv"),
                "output_name": filename,
                "output_path": str(path),
                "latest_target_row_count": int(csv_row_count(path, row.get("output_max_rebalance_date"))),
                "freshness_error": ""
                if row.get("operating_book_current")
                else "operating target book does not reach latest observable close",
            }
        )
        books.append(row)
    payload = {
        "schema_version": "operating-target-books-summary-vnext-v1",
        "status": "completed",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "latest_run": str(latest_run),
        "price_cache": "",
        "books": books,
        "blocked_books": [row["portfolio"] for row in books if not row.get("operating_book_current")],
        "blocked_reason": "one_or_more_vnext_operating_books_are_stale"
        if any(not row.get("operating_book_current") for row in books)
        else "",
        "outputs": {
            "main_operating_target_book": str(reports / "operating_main_target_book.csv"),
            "concentrated_operating_target_book": str(reports / "operating_concentrated_target_book.csv"),
            "summary_json": str(reports / "operating_target_books_summary.json"),
            "report_md": str(reports / "operating_target_books_report.md"),
        },
    }
    write_json(reports / "operating_target_books_summary.json", payload)
    lines = [
        "# Operating Target Books",
        "",
        "AlphaOps vNext production books are held forward to the latest observable close when the latest policy rebalance is older than the broker replay end date.",
        "",
        "| Portfolio | Rows | Policy max | Latest close | Output max | Appended | Current |",
        "| --- | ---: | --- | --- | --- | ---: | ---: |",
    ]
    for row in books:
        lines.append(
            "| {portfolio} | {rows} | {history} | {close} | {output} | {appended} | {current} |".format(
                portfolio=row.get("portfolio"),
                rows=row.get("output_row_count"),
                history=row.get("history_max_rebalance_date") or "",
                close=row.get("latest_price_close_date") or "",
                output=row.get("output_max_rebalance_date") or "",
                appended=str(row.get("latest_target_appended")).lower(),
                current=str(row.get("operating_book_current")).lower(),
            )
        )
    write_text(reports / "operating_target_books_report.md", "\n".join(lines) + "\n")


def csv_row_count(path: Path, rebalance_date: Any = None) -> int:
    if not path.exists():
        return 0
    try:
        frame = pd.read_csv(path, usecols=lambda col: col in {"rebalance_date"})
    except Exception:
        return 0
    if rebalance_date:
        return int(pd.to_datetime(frame["rebalance_date"], errors="coerce").dt.date.astype(str).eq(str(rebalance_date)).sum())
    return int(len(frame))


def run_broker_replays(args: argparse.Namespace, latest_run: Path) -> dict[str, Any]:
    price_cache = repo_path(args.price_cache)
    metrics: dict[str, Any] = {}
    specs = [
        ("main", latest_run / "reports" / "operating_main_target_book.csv", latest_run / "broker_replay" / "main", None),
        ("concentrated", latest_run / "reports" / "operating_concentrated_target_book.csv", latest_run / "broker_replay" / "concentrated", DISABLE_CONCENTRATED_CHAMPION_FILTERS.copy()),
    ]
    for portfolio_kind, target_book, output_dir, filters in specs:
        metrics[portfolio_kind] = broker_replay(
            target_book=target_book,
            price_cache=price_cache,
            output_dir=output_dir,
            portfolio_kind=portfolio_kind,
            fill_mode="next_close",
            cost_bps=float(args.cost_bps),
            integer_shares=True,
            max_fill_lag_days=int(args.max_fill_lag_days),
            concentrated_champion_filters=filters,
        )
    return metrics


def build(args: argparse.Namespace) -> dict[str, Any]:
    latest_run = repo_path(args.latest_run)
    output_dir = repo_path(args.output_dir)
    price_cache = repo_path(args.price_cache)
    operating_append_end_date = pd.to_datetime(getattr(args, "operating_append_end_date", None), errors="coerce")
    if pd.isna(operating_append_end_date):
        operating_append_end_date = None
    else:
        operating_append_end_date = pd.Timestamp(operating_append_end_date).normalize()
    output_dir.mkdir(parents=True, exist_ok=True)
    candidate_book, source_mode = resolve_candidate_book(latest_run, args.candidate_book)
    candidate = normalize_candidate_frame(read_table(candidate_book))
    if candidate.empty or source_mode == "latest_only_blocked":
        payload = {
            "schema_version": "alphaops-vnext-production-replay-v1",
            "status": "blocked",
            "reason": "historical candidate_replay_book.csv is required",
            "candidate_book": str(candidate_book),
            "candidate_source_mode": source_mode,
            "production_policy": "alphaops_vnext_production",
            "production_applied": False,
            "sidecar_only": False,
        }
        write_json(output_dir / "summary.json", payload)
        return payload

    candidate, pit_audit = enforce_pit_available(candidate)
    write_csv(output_dir / "pit_evidence_audit.csv", pit_audit)
    long_crisis_features = repo_path(args.long_crisis_features)
    long_crisis_thresholds = repo_path(args.long_crisis_thresholds)
    write_json(
        output_dir / "target_generation_input_manifest.json",
        target_generation_input_manifest(
            latest_run=latest_run,
            output_dir=output_dir,
            candidate_book=candidate_book,
            candidate_source_mode=source_mode,
            candidate=candidate,
            price_cache=price_cache,
            long_crisis_features=long_crisis_features,
            long_crisis_thresholds=long_crisis_thresholds,
            operating_append_end_date=operating_append_end_date,
        ),
    )
    candidate = enrich_relative_strength(candidate, price_cache)
    prices = price_map(price_cache, candidate)
    dates = pd.to_datetime(candidate["rebalance_date"], errors="coerce").dropna()
    crisis_states = build_daily_crisis_state(
        price_cache,
        pd.Timestamp(dates.min()),
        pd.Timestamp(dates.max()),
        long_crisis_features=long_crisis_features,
        long_crisis_thresholds=long_crisis_thresholds,
    )
    crisis_audit, crisis_window_report, crisis_audit_payload = crisis_state_audit(crisis_states)
    if bool(crisis_audit_payload.get("daily_crisis_state_all_green")) and bool(crisis_audit_payload.get("missing_data_only_trigger")):
        crisis_states = pd.DataFrame()
        crisis_status = "skipped_missing_crisis_inputs"
    else:
        crisis_status = "applied"
    write_csv(output_dir / "daily_crisis_state.csv", crisis_states)
    write_csv(output_dir / "crisis_state_audit.csv", crisis_audit)
    write_csv(output_dir / "crisis_window_detection_report.csv", crisis_window_report)
    write_json(output_dir / "lane_feature_mapping.json", lane_feature_mapping_payload())
    write_json(output_dir / "crisis_hysteresis_config.json", CRISIS_HYSTERESIS)

    variants: dict[str, pd.DataFrame] = {}
    lane_frames: list[pd.DataFrame] = []
    reject_frames: list[pd.DataFrame] = []
    exposure_frames: list[pd.DataFrame] = []
    portfolios = ["main", "concentrated"] if args.portfolio_kind == "both" else [args.portfolio_kind]
    for portfolio_kind in portfolios:
        target_ns = MAIN_VARIANTS if portfolio_kind == "main" else CONCENTRATED_VARIANTS
        for target_n in target_ns:
            target, lanes, rejected, exposure = build_variant_book(
                candidate,
                portfolio_kind=portfolio_kind,
                target_n=int(target_n),
                crisis_states=crisis_states,
                prices=prices,
            )
            key = f"{portfolio_kind}_N{target_n}"
            variants[key] = target
            if not lanes.empty:
                lanes["variant_id"] = key
                lane_frames.append(lanes)
            if not rejected.empty:
                reject_frames.append(rejected)
            if not exposure.empty:
                exposure_frames.append(exposure)

    operating_append_summaries: dict[str, dict[str, Any]] = {}
    regime_capacity_summaries: dict[str, dict[str, Any]] = {}
    regime_capacity_audits: list[pd.DataFrame] = []
    for key, book in list(variants.items()):
        portfolio_kind = "concentrated" if key.startswith("concentrated_") else "main"
        current_book, append_summary = append_latest_operating_decision(
            book,
            price_cache=price_cache,
            portfolio_kind=portfolio_kind,
            variant_key=key,
            operating_append_end_date=operating_append_end_date,
        )
        current_book, capacity_summary, capacity_audit = apply_regime_capacity_overlay(
            current_book,
            portfolio_kind=portfolio_kind,
        )
        capacity_summary["variant_key"] = key
        append_summary["regime_capacity_overlay"] = capacity_summary
        variants[key] = current_book
        operating_append_summaries[key] = append_summary
        regime_capacity_summaries[key] = capacity_summary
        if not capacity_audit.empty:
            capacity_audit["variant_key"] = key
            regime_capacity_audits.append(capacity_audit)
        write_csv(output_dir / "variants" / f"{key}_target_book.csv", current_book)

    main_key = f"main_N{int(args.main_target_n)}"
    concentrated_key = f"concentrated_N{int(args.concentrated_target_n)}"
    main_book = variants.get(main_key, pd.DataFrame()) if "main" in portfolios else pd.DataFrame()
    concentrated_book = variants.get(concentrated_key, pd.DataFrame()) if "concentrated" in portfolios else pd.DataFrame()
    main_churn_filter_summary: dict[str, Any] = {}
    neutral_metals_block_summaries: dict[str, dict[str, Any]] = {}
    main_defense_review_turnaround_block_summary: dict[str, Any] = {}
    main_defense_review_balanced_block_summary: dict[str, Any] = {}
    concentrated_green_benchmark_risk_block_summary: dict[str, Any] = {}
    main_fast_crash_hedge_summary: dict[str, Any] = {}
    main_fast_crash_hedge_actions = pd.DataFrame()
    if not main_book.empty:
        main_book, main_churn_filter_summary = apply_main_neutral_regime_churn_filter(main_book, "main")
        main_book, neutral_metals_block_summaries["main"] = apply_neutral_metals_new_entry_block(main_book, "main")
        main_book, main_defense_review_turnaround_block_summary = (
            apply_main_defense_review_turnaround_new_entry_block(
                main_book,
                "main",
            )
        )
        main_book, main_defense_review_balanced_block_summary = (
            apply_main_defense_review_balanced_new_entry_block(
                main_book,
                "main",
            )
        )
        main_book, main_fast_crash_hedge_summary, main_fast_crash_hedge_actions = apply_main_fast_crash_hedge(
            main_book,
            "main",
            price_cache=price_cache,
        )
        variants[main_key] = main_book
        operating_append_summaries.setdefault(main_key, {})["main_neutral_churn_filter"] = main_churn_filter_summary
        operating_append_summaries[main_key]["neutral_metals_new_entry_block"] = neutral_metals_block_summaries["main"]
        operating_append_summaries[main_key]["main_defense_review_turnaround_new_entry_block"] = (
            main_defense_review_turnaround_block_summary
        )
        operating_append_summaries[main_key]["main_defense_review_balanced_new_entry_block"] = (
            main_defense_review_balanced_block_summary
        )
        operating_append_summaries[main_key]["main_fast_crash_hedge"] = main_fast_crash_hedge_summary
        operating_append_summaries[main_key]["output_row_count"] = int(len(main_book))
        write_csv(output_dir / "variants" / f"{main_key}_target_book.csv", main_book)
    if not concentrated_book.empty:
        concentrated_book, neutral_metals_block_summaries["concentrated"] = apply_neutral_metals_new_entry_block(
            concentrated_book,
            "concentrated",
        )
        concentrated_book, concentrated_green_benchmark_risk_block_summary = (
            apply_concentrated_green_benchmark_risk_cyclical_new_entry_block(
                concentrated_book,
                "concentrated",
            )
        )
        variants[concentrated_key] = concentrated_book
        operating_append_summaries.setdefault(concentrated_key, {})["neutral_metals_new_entry_block"] = (
            neutral_metals_block_summaries["concentrated"]
        )
        operating_append_summaries[concentrated_key]["concentrated_green_benchmark_risk_cyclical_new_entry_block"] = (
            concentrated_green_benchmark_risk_block_summary
        )
        operating_append_summaries[concentrated_key]["output_row_count"] = int(len(concentrated_book))
        write_csv(output_dir / "variants" / f"{concentrated_key}_target_book.csv", concentrated_book)
    write_json(output_dir / "main_neutral_churn_filter.json", main_churn_filter_summary)
    write_json(output_dir / "neutral_metals_new_entry_block.json", neutral_metals_block_summaries)
    write_json(
        output_dir / "main_defense_review_turnaround_new_entry_block.json",
        main_defense_review_turnaround_block_summary,
    )
    write_json(
        output_dir / "main_defense_review_balanced_new_entry_block.json",
        main_defense_review_balanced_block_summary,
    )
    write_json(output_dir / "main_fast_crash_hedge.json", main_fast_crash_hedge_summary)
    write_csv(output_dir / "main_fast_crash_hedge_actions.csv", main_fast_crash_hedge_actions)
    write_json(
        output_dir / "concentrated_green_benchmark_risk_cyclical_new_entry_block.json",
        concentrated_green_benchmark_risk_block_summary,
    )
    write_csv(output_dir / "official_main_target_book.csv", main_book)
    write_csv(output_dir / "official_concentrated_target_book.csv", concentrated_book)
    lane_history = pd.concat(lane_frames, ignore_index=True) if lane_frames else pd.DataFrame()
    rejected = pd.concat(reject_frames, ignore_index=True) if reject_frames else pd.DataFrame()
    exposure = pd.concat(exposure_frames, ignore_index=True) if exposure_frames else pd.DataFrame()
    write_csv(output_dir / "lane_scores_history.csv", lane_history)
    write_csv(output_dir / "rejected_by_reason.csv", rejected)
    write_csv(output_dir / "lane_exposure_by_month.csv", exposure)
    write_csv(
        output_dir / "regime_capacity_overlay_audit.csv",
        pd.concat(regime_capacity_audits, ignore_index=True) if regime_capacity_audits else pd.DataFrame(),
    )
    latest_rows = []
    for key, book in variants.items():
        if book.empty:
            continue
        d = book.copy()
        d["rebalance_date"] = pd.to_datetime(d["rebalance_date"], errors="coerce")
        latest_dt = d["rebalance_date"].max()
        latest_rows.append(d[d["rebalance_date"].eq(latest_dt)].assign(variant_key=key))
    write_csv(output_dir / "selected_latest.csv", pd.concat(latest_rows, ignore_index=True) if latest_rows else pd.DataFrame())

    copied: dict[str, str] = {}
    production_applied = False
    if args.production_output_mode == "replace_operating":
        copied = copy_operating_books(latest_run, main_book, concentrated_book)
        write_operating_summary(
            latest_run,
            output_dir,
            {
                "main": operating_append_summaries.get(main_key, {}),
                "concentrated": operating_append_summaries.get(concentrated_key, {}),
            },
        )
        production_applied = True
    broker_metrics = {} if args.skip_broker_replay else run_broker_replays(args, latest_run)
    activation = {
        "schema_version": "alphaops-vnext-production-activation-v1",
        "status": "applied" if production_applied else "shadow_only",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "production_policy": "alphaops_vnext_production",
        "production_output_mode": args.production_output_mode,
        "current_holdings_source": "alphaops_vnext_policy_target_book" if production_applied else "alphaops_vnext_shadow_target_book",
        "production_applied": bool(production_applied),
        "sidecar_only": False,
        "sidecar_applied_to_production": bool(production_applied),
        "official_target_books": copied,
        "candidate_book": str(candidate_book),
        "candidate_source_mode": source_mode,
        "first_rebalance_date": date_text(dates.min()),
        "last_rebalance_date": date_text(dates.max()),
        "last_operating_signal_date": max(
            (
                str(row.get("output_max_rebalance_date") or "")
                for row in (operating_append_summaries.get(main_key, {}), operating_append_summaries.get(concentrated_key, {}))
            ),
            default="",
        ),
        "crisis_overlay_status": crisis_status,
        "regime_capacity_overlay": {
            "status": "applied",
            "summaries": regime_capacity_summaries,
            "audit_path": str(output_dir / "regime_capacity_overlay_audit.csv"),
        },
        "main_neutral_churn_filter": main_churn_filter_summary,
        "neutral_metals_new_entry_block": neutral_metals_block_summaries,
        "main_defense_review_turnaround_new_entry_block": main_defense_review_turnaround_block_summary,
        "main_defense_review_balanced_new_entry_block": main_defense_review_balanced_block_summary,
        "concentrated_green_benchmark_risk_cyclical_new_entry_block": (
            concentrated_green_benchmark_risk_block_summary
        ),
    }
    write_json(output_dir / "production_activation.json", activation)
    if production_applied:
        write_json(latest_run / "promotion_review" / "alphaops_vnext_production_activation.json", activation)
    if args.run_current_report:
        build_user_current_report(
            argparse.Namespace(
                latest_run=str(latest_run),
                price_cache=str(price_cache),
                output_dir=str(latest_run / "user_current"),
                strict=False,
            )
        )
    payload = {
        "schema_version": "alphaops-vnext-production-replay-v1",
        "status": "completed",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "candidate_book": str(candidate_book),
        "candidate_source_mode": source_mode,
        "rebalance_date_count": int(dates.nunique()),
        "production_policy": "alphaops_vnext_production",
        "production_output_mode": args.production_output_mode,
        "production_applied": bool(production_applied),
        "sidecar_only": False,
        "sidecar_applied_to_production": bool(production_applied),
        "current_holdings_source": activation["current_holdings_source"],
        "main_target_n": int(args.main_target_n),
        "concentrated_target_n": int(args.concentrated_target_n),
        "main_rows": int(len(main_book)),
        "concentrated_rows": int(len(concentrated_book)),
        "operating_append_summaries": operating_append_summaries,
        "lane_score_rows": int(len(lane_history)),
        "rejected_rows": int(len(rejected)),
        "pit_evidence_blocked_rows": int(len(pit_audit)),
        "crisis_overlay_status": crisis_status,
        "regime_capacity_overlay": {
            "status": "applied",
            "summaries": regime_capacity_summaries,
            "audit_path": str(output_dir / "regime_capacity_overlay_audit.csv"),
        },
        "main_neutral_churn_filter": main_churn_filter_summary,
        "neutral_metals_new_entry_block": neutral_metals_block_summaries,
        "main_defense_review_turnaround_new_entry_block": main_defense_review_turnaround_block_summary,
        "main_defense_review_balanced_new_entry_block": main_defense_review_balanced_block_summary,
        "concentrated_green_benchmark_risk_cyclical_new_entry_block": (
            concentrated_green_benchmark_risk_block_summary
        ),
        "broker_replay_ran": not bool(args.skip_broker_replay),
        "broker_metrics": broker_metrics,
        "official_target_books": copied,
        "outputs": {
            "summary_json": str(output_dir / "summary.json"),
            "production_activation_json": str(output_dir / "production_activation.json"),
            "official_main_target_book": str(output_dir / "official_main_target_book.csv"),
            "official_concentrated_target_book": str(output_dir / "official_concentrated_target_book.csv"),
        },
    }
    write_json(output_dir / "summary.json", payload)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default=DEFAULT_LATEST_RUN)
    parser.add_argument("--candidate-book", default=None)
    parser.add_argument("--price-cache", default="cache_prices")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--portfolio-kind", choices=["main", "concentrated", "both"], default="both")
    parser.add_argument("--main-target-n", type=int, choices=MAIN_VARIANTS, default=DEFAULT_MAIN_TARGET_N)
    parser.add_argument("--concentrated-target-n", type=int, choices=CONCENTRATED_VARIANTS, default=DEFAULT_CONCENTRATED_TARGET_N)
    parser.add_argument("--production-output-mode", choices=["replace_operating", "shadow_only"], default="replace_operating")
    parser.add_argument("--skip-broker-replay", action="store_true")
    parser.add_argument("--run-current-report", action="store_true")
    parser.add_argument("--cost-bps", type=float, default=25.0)
    parser.add_argument("--max-fill-lag-days", type=int, default=7)
    parser.add_argument(
        "--operating-append-end-date",
        default=None,
        help=(
            "Optional research/audit clamp for hold-forward operating decisions. "
            "By default operating books append to the latest observable close."
        ),
    )
    parser.add_argument("--long-crisis-features", default="data_pit/macro/long_crisis_daily_features.parquet")
    parser.add_argument("--long-crisis-thresholds", default="outputs/long_crisis_learning/best_thresholds.json")
    return parser.parse_args()


def main() -> int:
    payload = build(parse_args())
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0 if payload.get("status") == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
