"""Research-only Market Leader Concentration Engine helpers.

This module intentionally does not mutate production scores, feature-store
columns, or target-book defaults. It builds point-in-time monthly target books
from historical candidate rows, then callers can replay those books through the
broker-ledger next-close engine.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from tools.run_weekly_evaluation import load_price_series, price_on_or_before


CASH_TICKER = "CASH"
BENCHMARKS = ("SPY", "QQQ")
LOOKBACK_MONTHS = (1, 3, 6, 12)
MAIN_ALLOWED_TIERS = {"DUAL_LEADER", "SECTOR_LEADER"}
CONCENTRATED_ALLOWED_TIERS = {"DUAL_LEADER"}
NEW_ENTRY_ALLOWED_STATES = {"HOLD", "SHAKEOUT_GUARD"}
PREVIOUS_HOLD_ALLOWED_STATES = {"HOLD", "SHAKEOUT_GUARD", "WARNING"}
RISK_MODE_NONE = "none"
RISK_MODE_BENCHMARK_GUARD = "benchmark_guard"


@dataclass(frozen=True)
class MarketLeaderVariant:
    """Portfolio construction settings for one monthly target-book grid row."""

    portfolio_kind: str
    variant_id: str
    target_n: int
    single_cap: float
    subindustry_cap: float
    theme_cap: float
    risk_mode: str = RISK_MODE_NONE


def default_variants() -> list[MarketLeaderVariant]:
    out: list[MarketLeaderVariant] = []
    for n in (12, 15, 18):
        for single_cap in (0.12, 0.15):
            for sub_cap in (0.40, 0.50):
                for theme_cap in (0.60, 0.70):
                    base_id = f"main_N{n}_cap{int(single_cap*100)}_sub{int(sub_cap*100)}_theme{int(theme_cap*100)}"
                    out.append(
                        MarketLeaderVariant(
                            portfolio_kind="main",
                            variant_id=base_id,
                            target_n=n,
                            single_cap=single_cap,
                            subindustry_cap=sub_cap,
                            theme_cap=theme_cap,
                        )
                    )
                    if n in (15, 18):
                        out.append(
                            MarketLeaderVariant(
                                portfolio_kind="main",
                                variant_id=f"{base_id}_risk",
                                target_n=n,
                                single_cap=single_cap,
                                subindustry_cap=sub_cap,
                                theme_cap=theme_cap,
                                risk_mode=RISK_MODE_BENCHMARK_GUARD,
                            )
                        )
    for n in (3, 5):
        single_caps = (0.40, 0.45) if n == 3 else (0.30, 0.35)
        for single_cap in single_caps:
            for sub_cap in (0.70, 0.80):
                base_id = f"concentrated_N{n}_cap{int(single_cap*100)}_sub{int(sub_cap*100)}"
                out.append(
                    MarketLeaderVariant(
                        portfolio_kind="concentrated",
                        variant_id=base_id,
                        target_n=n,
                        single_cap=single_cap,
                        subindustry_cap=sub_cap,
                        theme_cap=1.0,
                    )
                )
                out.append(
                    MarketLeaderVariant(
                        portfolio_kind="concentrated",
                        variant_id=f"{base_id}_risk",
                        target_n=n,
                        single_cap=single_cap,
                        subindustry_cap=sub_cap,
                        theme_cap=1.0,
                        risk_mode=RISK_MODE_BENCHMARK_GUARD,
                    )
                )
    return out


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


def numeric(frame: pd.DataFrame, col: str, default: float = 0.0) -> pd.Series:
    if col not in frame.columns:
        return pd.Series(default, index=frame.index, dtype=float)
    return pd.to_numeric(frame[col], errors="coerce").fillna(default)


def first_numeric(frame: pd.DataFrame, cols: tuple[str, ...], default: float = 0.0) -> pd.Series:
    pieces = [pd.to_numeric(frame[col], errors="coerce") for col in cols if col in frame.columns]
    if not pieces:
        return pd.Series(default, index=frame.index, dtype=float)
    return pd.concat(pieces, axis=1).bfill(axis=1).iloc[:, 0].fillna(default)


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


def load_prices(price_cache: Path, tickers: set[str]) -> dict[str, pd.DataFrame]:
    return {ticker: load_price_series(price_cache, ticker) for ticker in sorted(tickers)}


def price_return(prices: dict[str, pd.DataFrame], ticker: str, as_of_date: Any, months: int) -> tuple[float, bool]:
    px = prices.get(str(ticker).upper(), pd.DataFrame())
    if px.empty:
        return 0.0, False
    end_dt, end_px = price_on_or_before(px, as_of_date, "close")
    if end_dt is None or end_px is None:
        return 0.0, False
    start_target = pd.Timestamp(end_dt) - pd.DateOffset(months=int(months))
    start_dt, start_px = price_on_or_before(px, start_target, "close")
    if start_dt is None or start_px is None or start_px <= 0:
        return 0.0, False
    return float(end_px / start_px - 1.0), True


def _price_frame_for_ma(px: pd.DataFrame) -> pd.DataFrame:
    if px.empty:
        return pd.DataFrame()
    d = px.copy()
    if "date" in d.columns:
        d["date"] = pd.to_datetime(d["date"], errors="coerce")
    else:
        d["date"] = pd.to_datetime(d.index, errors="coerce")
    close_col = next((col for col in ("close", "Close", "Adj Close", "adj_close", "AdjClose") if col in d.columns), "")
    if not close_col:
        numeric_cols = [col for col in d.columns if col != "date" and pd.api.types.is_numeric_dtype(d[col])]
        close_col = numeric_cols[0] if numeric_cols else ""
    if not close_col:
        return pd.DataFrame()
    d["close_for_ma"] = pd.to_numeric(d[close_col], errors="coerce")
    d = d.dropna(subset=["date", "close_for_ma"]).sort_values("date")
    return d[["date", "close_for_ma"]]


def ma_ratio(prices: dict[str, pd.DataFrame], ticker: str, as_of_date: Any, window: int) -> tuple[float, bool]:
    px = prices.get(str(ticker).upper(), pd.DataFrame())
    if px.empty:
        return 1.0, False
    end_dt, end_px = price_on_or_before(px, as_of_date, "close")
    if end_dt is None or end_px is None or end_px <= 0:
        return 1.0, False
    d = _price_frame_for_ma(px)
    if d.empty:
        return 1.0, False
    part = d[d["date"].le(pd.Timestamp(end_dt))].tail(int(window))
    min_rows = max(20, int(window) // 2)
    if len(part) < min_rows:
        return 1.0, False
    avg = float(part["close_for_ma"].mean())
    if not math.isfinite(avg) or avg <= 0:
        return 1.0, False
    return float(end_px / avg), True


def benchmark_guard_signal(
    prices: dict[str, pd.DataFrame],
    rebalance_date: Any,
    portfolio_kind: str,
) -> dict[str, Any]:
    """Point-in-time SPY/QQQ gross exposure governor for research sidecars."""

    spy_1m, _ = price_return(prices, "SPY", rebalance_date, 1)
    qqq_1m, _ = price_return(prices, "QQQ", rebalance_date, 1)
    spy_3m, _ = price_return(prices, "SPY", rebalance_date, 3)
    qqq_3m, _ = price_return(prices, "QQQ", rebalance_date, 3)
    spy_ma50, _ = ma_ratio(prices, "SPY", rebalance_date, 50)
    qqq_ma50, _ = ma_ratio(prices, "QQQ", rebalance_date, 50)
    spy_ma200, _ = ma_ratio(prices, "SPY", rebalance_date, 200)
    qqq_ma200, _ = ma_ratio(prices, "QQQ", rebalance_date, 200)

    risk_score = 0
    reasons: list[str] = []
    checks = [
        (spy_1m < -0.06, "spy_1m_down_gt_6pct"),
        (qqq_1m < -0.08, "qqq_1m_down_gt_8pct"),
        (spy_3m < 0 and qqq_3m < 0, "both_3m_negative"),
        (spy_ma50 < 1 and qqq_ma50 < 1, "both_below_ma50"),
        (spy_ma200 < 1, "spy_below_ma200"),
        (qqq_ma200 < 1, "qqq_below_ma200"),
        (spy_3m < -0.10 and qqq_3m < -0.10, "both_3m_down_gt_10pct"),
    ]
    for passed, reason in checks:
        if passed:
            risk_score += 1
            reasons.append(reason)

    if risk_score >= 5:
        gross = 0.35 if portfolio_kind == "main" else 0.25
        regime = "crisis_defense"
    elif risk_score >= 4:
        gross = 0.50 if portfolio_kind == "main" else 0.35
        regime = "risk_off"
    elif risk_score >= 3:
        gross = 0.70 if portfolio_kind == "main" else 0.55
        regime = "caution"
    elif risk_score >= 2:
        gross = 0.85 if portfolio_kind == "main" else 0.70
        regime = "early_warning"
    else:
        gross = 1.0
        regime = "risk_on"

    return {
        "market_regime": regime,
        "gross_exposure_cap": gross,
        "risk_overlay_reason": ",".join(reasons) if reasons else "risk_on",
        "benchmark_risk_score": risk_score,
        "spy_1m_return": spy_1m,
        "qqq_1m_return": qqq_1m,
        "spy_3m_return": spy_3m,
        "qqq_3m_return": qqq_3m,
        "spy_ma50_ratio": spy_ma50,
        "qqq_ma50_ratio": qqq_ma50,
        "spy_ma200_ratio": spy_ma200,
        "qqq_ma200_ratio": qqq_ma200,
    }


def add_benchmark_relative_returns(
    frame: pd.DataFrame,
    prices: dict[str, pd.DataFrame],
    rebalance_date: Any,
) -> pd.DataFrame:
    d = frame.copy()
    d["ticker"] = d["ticker"].astype(str).str.upper().str.strip()
    bench_returns: dict[tuple[str, int], tuple[float, bool]] = {}
    for bench in BENCHMARKS:
        for months in LOOKBACK_MONTHS:
            bench_returns[(bench, months)] = price_return(prices, bench, rebalance_date, months)

    coverage_flags: list[str] = []
    for months in LOOKBACK_MONTHS:
        raw_vals: list[float] = []
        raw_ok: list[bool] = []
        for ticker in d["ticker"].tolist():
            ret, ok = price_return(prices, ticker, rebalance_date, months)
            if not ok:
                fallback = first_numeric(d.loc[d["ticker"].eq(ticker)], (f"mom_{months}m", f"ret_{months}m"), 0.0)
                ret = float(fallback.iloc[0]) if not fallback.empty else 0.0
            raw_vals.append(ret)
            raw_ok.append(ok)
        d[f"ticker_ret_{months}m"] = raw_vals
        for bench in BENCHMARKS:
            bench_ret, bench_ok = bench_returns[(bench, months)]
            fallback_col = f"bench_ret_{months}m" if bench == "SPY" else f"qqq_ret_{months}m"
            if not bench_ok and fallback_col in d.columns:
                bench_series = numeric(d, fallback_col)
                d[f"rs_{bench.lower()}_{months}m"] = d[f"ticker_ret_{months}m"] - bench_series
            else:
                d[f"rs_{bench.lower()}_{months}m"] = d[f"ticker_ret_{months}m"] - float(bench_ret)
        coverage_flags.append(f"{months}m")
        d[f"rs_price_coverage_{months}m"] = raw_ok
    d["rs_benchmark_source"] = "price_cache_or_candidate_fallback"
    d["rs_price_coverage_flag"] = d[[f"rs_price_coverage_{m}m" for m in LOOKBACK_MONTHS]].all(axis=1)
    return d


def compute_market_leader_tape_score(frame: pd.DataFrame) -> pd.DataFrame:
    d = frame.copy()
    d["market_leader_tape_score"] = (
        0.25 * robust_z(numeric(d, "rs_spy_1m"))
        + 0.20 * robust_z(numeric(d, "rs_qqq_1m"))
        + 0.25 * robust_z(numeric(d, "rs_spy_3m"))
        + 0.20 * robust_z(numeric(d, "rs_qqq_3m"))
        + 0.10 * robust_z(numeric(d, "rs_qqq_6m"))
    )
    return d


def compute_sector_leadership_score(frame: pd.DataFrame) -> pd.DataFrame:
    d = frame.copy()
    d["sector_leadership_score"] = (
        0.30 * robust_z(first_numeric(d, ("industry_group_strength_score", "sector_leader_score")))
        + 0.25 * robust_z(first_numeric(d, ("industry_within_leader_rank", "within_sector_leader_score")))
        + 0.20 * robust_z(first_numeric(d, ("oneil_leadership_score", "relative_strength_composite")))
        + 0.15 * robust_z(first_numeric(d, ("sub_industry_rs_score", "rs_sector_composite")))
        + 0.10 * robust_z(first_numeric(d, ("industry_leader_gap", "leader_emergence_score")))
    )
    return d


def compute_smart_money_confirmation_score(frame: pd.DataFrame) -> pd.DataFrame:
    d = frame.copy()
    weights = {
        "sec_form4_cluster_buy_score": 0.30,
        "sec_form4_ceo_cfo_buy_score": 0.20,
        "sec_13f_smart_money_score": 0.20,
        "sec_13f_new_position_score": 0.15,
        "etf_holdings_score_shadow": 0.15,
    }
    weighted = pd.Series(0.0, index=d.index, dtype=float)
    coverage = pd.Series(0.0, index=d.index, dtype=float)
    for col, weight in weights.items():
        if col not in d.columns:
            continue
        raw = pd.to_numeric(d[col], errors="coerce")
        mask = raw.notna()
        weighted = weighted.add(raw.fillna(0.0) * weight, fill_value=0.0)
        coverage = coverage.add(mask.astype(float) * weight, fill_value=0.0)
    d["smart_money_confirmation_score"] = weighted
    d["smart_money_evidence_confidence"] = coverage.clip(0.0, 1.0)
    d["smart_money_confirmation_boost"] = robust_z(weighted).clip(lower=0.0)
    return d


def compute_leader_chase_risk_score(frame: pd.DataFrame) -> pd.DataFrame:
    d = frame.copy()
    dist_ma50 = first_numeric(d, ("distance_from_ma50", "dist_ma50", "breakout_distance_63d"), 0.0).clip(lower=0.0)
    atr = first_numeric(d, ("atr14_pct", "vol_252d"), 0.0).clip(lower=0.0)
    d["leader_chase_risk_score"] = (
        0.35 * first_numeric(d, ("short_extension_risk_penalty", "overheat_penalty"), 0.0).clip(lower=0.0)
        + 0.25 * first_numeric(d, ("stage2_overext_penalty", "explosion_exit_score"), 0.0).clip(lower=0.0)
        + 0.20 * robust_z(atr).clip(lower=0.0)
        + 0.20 * robust_z(dist_ma50).clip(lower=0.0)
    )
    return d


def compute_liquidity_capacity_score(frame: pd.DataFrame) -> pd.DataFrame:
    d = frame.copy()
    dollar_vol = first_numeric(d, ("dollar_vol_20d", "avg_dollar_vol_20d"), 0.0).clip(lower=0.0)
    mcap = first_numeric(d, ("market_cap_live", "mktcap", "market_cap"), 0.0).clip(lower=0.0)
    vol = first_numeric(d, ("atr14_pct", "vol_252d"), 0.0).clip(lower=0.0)
    d["dollar_vol_current"] = dollar_vol
    d["market_cap_current"] = mcap
    d["liquidity_capacity_score"] = (
        0.45 * robust_z(np.log1p(dollar_vol))
        + 0.35 * robust_z(np.log1p(mcap))
        - 0.20 * robust_z(vol).clip(lower=0.0)
    )
    cap = pd.Series(1.0, index=d.index, dtype=float)
    cap = cap.mask(dollar_vol.lt(5_000_000), 0.02)
    cap = cap.mask(dollar_vol.ge(5_000_000) & dollar_vol.lt(20_000_000), 0.05)
    cap = cap.mask(mcap.gt(0) & mcap.lt(2_000_000_000), np.minimum(cap, 0.05))
    cap = cap.mask(mcap.ge(2_000_000_000) & mcap.lt(5_000_000_000), np.minimum(cap, 0.10))
    d["liquidity_capacity_weight_cap"] = cap.clip(0.0, 1.0)
    return d


def compute_leader_selection_score(frame: pd.DataFrame) -> pd.DataFrame:
    d = frame.copy()
    d["future_winner_confirmation_score"] = first_numeric(
        d,
        (
            "future_winner_confirmation_score",
            "portfolio_future_winner_engine_score",
            "future_winner_scout_score",
            "h6_dynamic_leader_score",
            "dynamic_leader_score",
            "score",
        ),
        0.0,
    )
    d["quality_growth_score"] = first_numeric(
        d,
        ("quality_growth_score", "growth_onset_composite", "anticipatory_growth_score", "sector_adjusted_quality_score"),
        0.0,
    )
    d["entry_quality_score"] = first_numeric(
        d,
        ("entry_quality_score", "breakout_setup_quality_score", "minervini_momentum_alive_score"),
        0.0,
    )
    d["main_leader_score"] = (
        0.28 * d["market_leader_tape_score"]
        + 0.22 * d["sector_leadership_score"]
        + 0.25 * robust_z(d["future_winner_confirmation_score"])
        + 0.08 * d["smart_money_confirmation_boost"]
        + 0.09 * robust_z(d["quality_growth_score"])
        + 0.05 * robust_z(d["entry_quality_score"])
        + 0.03 * d["liquidity_capacity_score"]
        - 0.08 * d["leader_chase_risk_score"].clip(lower=0.0)
    )
    d["concentrated_leader_score"] = (
        0.32 * d["market_leader_tape_score"]
        + 0.23 * d["sector_leadership_score"]
        + 0.20 * robust_z(d["future_winner_confirmation_score"])
        + 0.12 * d["smart_money_confirmation_boost"]
        + 0.05 * robust_z(d["quality_growth_score"])
        + 0.05 * robust_z(d["entry_quality_score"])
        + 0.03 * d["liquidity_capacity_score"]
        - 0.12 * d["leader_chase_risk_score"].clip(lower=0.0)
    )
    return d


def classify_leader_tier(row: pd.Series) -> str:
    rs_spy_1m = safe_float(row.get("rs_spy_1m"))
    rs_qqq_1m = safe_float(row.get("rs_qqq_1m"))
    rs_spy_3m = safe_float(row.get("rs_spy_3m"))
    rs_qqq_3m = safe_float(row.get("rs_qqq_3m"))
    rs_spy_6m = safe_float(row.get("rs_spy_6m"))
    rs_qqq_6m = safe_float(row.get("rs_qqq_6m"))
    sector = safe_float(row.get("sector_leadership_score"))
    if rs_spy_3m > 0 and rs_qqq_3m > 0 and (rs_spy_6m > 0 or rs_qqq_6m > 0):
        return "DUAL_LEADER"
    if rs_spy_3m > 0 and sector > 0:
        return "SECTOR_LEADER"
    if max(rs_spy_1m, rs_qqq_1m) > 0 and max(rs_spy_3m, rs_qqq_3m) <= 0:
        return "EMERGING_LEADER"
    return "LAGGING"


def classify_leader_state(row: pd.Series, prior_warning_streak: int = 0, prior_exit_streak: int = 0) -> tuple[str, str]:
    rs_qqq_1m = safe_float(row.get("rs_qqq_1m"))
    rs_qqq_3m = safe_float(row.get("rs_qqq_3m"))
    rs_qqq_6m = safe_float(row.get("rs_qqq_6m"))
    sector = safe_float(row.get("sector_leadership_score"))
    above50 = safe_float(row.get("price_above_ma50"), 1.0) >= 0.5
    above200 = safe_float(row.get("price_above_ma200"), 1.0) >= 0.5
    confidence = safe_float(row.get("smart_money_evidence_confidence"))
    crisis = max(safe_float(row.get("systemic_crisis_score")), safe_float(row.get("macro_risk_off_score"))) >= 0.65
    leadership_intact = sector > 0 and above200
    one_month_wobble_only = rs_qqq_1m < 0 <= rs_qqq_3m
    if rs_qqq_6m > 0 and leadership_intact and confidence >= 0.25 and one_month_wobble_only and not crisis:
        return "SHAKEOUT_GUARD", "6m_excess_and_leadership_intact"
    exit_raw = rs_qqq_1m < 0 and rs_qqq_3m < 0 and sector <= 0 and (not above50 or not above200)
    if exit_raw and (prior_warning_streak >= 1 or prior_exit_streak >= 1 or crisis):
        return "EXIT_REPLACE", "repeated_relative_break_or_crisis"
    warning_raw = rs_qqq_1m < 0 or not above50 or sector <= 0
    if exit_raw or warning_raw:
        return "WARNING", "relative_weakness_no_add" if prior_warning_streak < 1 else "second_warning_trim_review"
    return "HOLD", "leader_intact"


def infer_subindustry(row: pd.Series) -> str:
    for col in ("subindustry", "sub_industry", "industry", "industry_group", "sector"):
        value = str(row.get(col) or "").strip()
        if value and value.lower() != "nan":
            return value
    return "unknown"


def infer_broad_theme(row: pd.Series) -> str:
    for col in ("leadership_theme", "theme_horizon_primary", "industry_group", "sector"):
        value = str(row.get(col) or "").strip()
        if value and value.lower() != "nan":
            return value
    return infer_subindustry(row)


def score_market_leaders(month: pd.DataFrame, prices: dict[str, pd.DataFrame], rebalance_date: Any) -> pd.DataFrame:
    d = month.copy()
    d["ticker"] = d["ticker"].astype(str).str.upper().str.strip()
    d = add_benchmark_relative_returns(d, prices, rebalance_date)
    d = compute_market_leader_tape_score(d)
    d = compute_sector_leadership_score(d)
    d = compute_smart_money_confirmation_score(d)
    d = compute_leader_chase_risk_score(d)
    d = compute_liquidity_capacity_score(d)
    d = compute_leader_selection_score(d)
    d["leader_tier"] = d.apply(classify_leader_tier, axis=1)
    d["leader_subindustry"] = d.apply(infer_subindustry, axis=1)
    d["leader_broad_theme"] = d.apply(infer_broad_theme, axis=1)
    return d


def apply_state_history(scored: pd.DataFrame, state_by_ticker: dict[str, dict[str, int]]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for _, row in scored.iterrows():
        ticker = str(row.get("ticker") or "").upper()
        prior = state_by_ticker.get(ticker, {"warning_streak": 0, "exit_streak": 0})
        state, reason = classify_leader_state(
            row,
            prior_warning_streak=int(prior.get("warning_streak", 0)),
            prior_exit_streak=int(prior.get("exit_streak", 0)),
        )
        warning_streak = int(prior.get("warning_streak", 0)) + 1 if state == "WARNING" else 0
        exit_streak = int(prior.get("exit_streak", 0)) + 1 if state == "EXIT_REPLACE" else 0
        state_by_ticker[ticker] = {"warning_streak": warning_streak, "exit_streak": exit_streak}
        out = row.to_dict()
        out.update(
            {
                "leader_state": state,
                "leader_state_reason": reason,
                "warning_streak": warning_streak,
                "exit_streak": exit_streak,
                "shakeout_guard_active": state == "SHAKEOUT_GUARD",
            }
        )
        rows.append(out)
    return pd.DataFrame(rows)


def allowed_tiers(portfolio_kind: str) -> set[str]:
    return CONCENTRATED_ALLOWED_TIERS if portfolio_kind == "concentrated" else MAIN_ALLOWED_TIERS


def _score_col(portfolio_kind: str) -> str:
    return "concentrated_leader_score" if portfolio_kind == "concentrated" else "main_leader_score"


def _selection_reason(row: pd.Series, portfolio_kind: str) -> str:
    bits = [str(row.get("leader_tier") or "")]
    if safe_float(row.get("was_prev_holding")) > 0:
        bits.append("previous_holding_priority")
    if str(row.get("leader_state") or "") == "WARNING":
        bits.append("warning_hold_no_add" if safe_float(row.get("warning_streak")) < 2 else "second_warning_trim_review")
    if safe_float(row.get("smart_money_evidence_confidence")) > 0:
        bits.append("confirmed_by_evidence")
    if safe_float(row.get("leader_chase_risk_score")) > 0.75:
        bits.append("entry_scaled_for_chase_risk")
    if safe_float(row.get("gross_exposure_cap"), 1.0) < 0.999:
        bits.append("benchmark_risk_gross_cap")
    if portfolio_kind == "concentrated":
        bits.append("strict_dual_benchmark")
    return ",".join([b for b in bits if b])


def _raw_weights(candidates: pd.DataFrame, score_col: str) -> dict[str, float]:
    if candidates.empty:
        return {}
    scores = pd.to_numeric(candidates[score_col], errors="coerce").fillna(0.0)
    shifted = (scores - float(scores.min()) + 0.25).clip(lower=1e-6)
    raw = shifted * shifted
    total = float(raw.sum())
    if total <= 0:
        equal = 1.0 / max(len(candidates), 1)
        return {str(row.ticker).upper(): equal for row in candidates.itertuples(index=False)}
    return {str(ticker).upper(): float(value / total) for ticker, value in zip(candidates["ticker"], raw)}


def select_market_leader_targets(
    scored: pd.DataFrame,
    variant: MarketLeaderVariant,
    prev_holdings: dict[str, float] | None = None,
) -> pd.DataFrame:
    if scored.empty:
        return pd.DataFrame()
    score_col = _score_col(variant.portfolio_kind)
    allowed = allowed_tiers(variant.portfolio_kind)
    prev_holdings = {str(k).upper(): float(v) for k, v in (prev_holdings or {}).items() if str(k).upper() != CASH_TICKER}
    if "leader_state" not in scored.columns:
        scored = scored.copy()
        scored["leader_state"] = "HOLD"
    work = scored.copy()
    work["was_prev_holding"] = work["ticker"].astype(str).str.upper().isin(prev_holdings).astype(float)
    base_gate = (
        work["leader_tier"].isin(allowed)
        & pd.to_numeric(work["liquidity_capacity_weight_cap"], errors="coerce").gt(0)
    )
    prev_candidates = work[
        base_gate
        & work["ticker"].astype(str).str.upper().isin(prev_holdings)
        & work["leader_state"].astype(str).isin(PREVIOUS_HOLD_ALLOWED_STATES)
    ].copy()
    new_candidates = work[
        base_gate
        & ~work["ticker"].astype(str).str.upper().isin(prev_holdings)
        & work["leader_state"].astype(str).isin(NEW_ENTRY_ALLOWED_STATES)
    ].copy()
    pool_limit = max(int(variant.target_n) * 4, int(variant.target_n))
    prev_candidates = prev_candidates.sort_values(score_col, ascending=False)
    new_candidates = new_candidates.sort_values(score_col, ascending=False).head(pool_limit)
    candidates = pd.concat([prev_candidates, new_candidates], ignore_index=True)
    candidates = candidates.drop_duplicates("ticker", keep="first").head(pool_limit).copy()
    if candidates.empty:
        return pd.DataFrame()
    raw = _raw_weights(candidates, score_col)
    selected_rows: list[dict[str, Any]] = []
    weights: dict[str, float] = {}
    sub_totals: dict[str, float] = {}
    theme_totals: dict[str, float] = {}
    for _, row in candidates.iterrows():
        if len(selected_rows) >= int(variant.target_n):
            break
        ticker = str(row.get("ticker") or "").upper()
        sub = str(row.get("leader_subindustry") or "unknown")
        theme = str(row.get("leader_broad_theme") or sub)
        state = str(row.get("leader_state") or "HOLD")
        state_scale = 0.50 if state == "WARNING" and safe_float(row.get("warning_streak")) >= 2 else 1.0
        chase = safe_float(row.get("leader_chase_risk_score"))
        was_prev = safe_float(row.get("was_prev_holding")) > 0
        if chase >= 1.50:
            chase_scale = 0.75 if was_prev else 0.55
        elif chase >= 0.75:
            chase_scale = 0.90 if was_prev else 0.70
        else:
            chase_scale = 1.0
        cap = min(
            float(variant.single_cap),
            safe_float(row.get("liquidity_capacity_weight_cap"), 1.0),
            max(0.0, float(variant.subindustry_cap) - sub_totals.get(sub, 0.0)),
            max(0.0, float(variant.theme_cap) - theme_totals.get(theme, 0.0)),
        ) * state_scale * chase_scale
        weight = min(raw.get(ticker, 0.0), cap)
        if weight <= 1e-9:
            continue
        weights[ticker] = weight
        sub_totals[sub] = sub_totals.get(sub, 0.0) + weight
        theme_totals[theme] = theme_totals.get(theme, 0.0) + weight
        out = row.to_dict()
        out["chase_risk_weight_scale"] = chase_scale
        out["effective_single_weight_cap"] = cap
        out["weight"] = weight
        out["target_weight"] = weight
        out["selection_reason"] = _selection_reason(row, variant.portfolio_kind)
        out["residual_cash_reason"] = ""
        selected_rows.append(out)

    # Recycle residual cash into selected names where caps allow; otherwise the
    # target book carries explicit CASH and broker replay naturally leaves it.
    for _ in range(5):
        total = sum(weights.values())
        residual = 1.0 - total
        if residual <= 1e-6 or not selected_rows:
            break
        moved = 0.0
        for out in selected_rows:
            ticker = str(out.get("ticker") or "").upper()
            sub = str(out.get("leader_subindustry") or "unknown")
            theme = str(out.get("leader_broad_theme") or sub)
            room = min(
                safe_float(out.get("effective_single_weight_cap"), variant.single_cap) - weights.get(ticker, 0.0),
                safe_float(out.get("liquidity_capacity_weight_cap"), 1.0) - weights.get(ticker, 0.0),
                float(variant.subindustry_cap) - sub_totals.get(sub, 0.0),
                float(variant.theme_cap) - theme_totals.get(theme, 0.0),
            )
            add = min(max(room, 0.0), residual / max(len(selected_rows), 1))
            if add <= 1e-9:
                continue
            weights[ticker] += add
            out["weight"] = weights[ticker]
            out["target_weight"] = weights[ticker]
            sub_totals[sub] = sub_totals.get(sub, 0.0) + add
            theme_totals[theme] = theme_totals.get(theme, 0.0) + add
            residual -= add
            moved += add
        if moved <= 1e-9:
            break

    selected = pd.DataFrame(selected_rows)
    if not selected.empty:
        selected["weight"] = selected["ticker"].astype(str).str.upper().map(weights).fillna(0.0)
        selected["target_weight"] = selected["weight"]
        invested = float(selected["weight"].sum())
        residual_reason = ""
        if len(selected) < int(variant.target_n):
            residual_reason = "candidate_pool_or_caps_exhausted"
        elif invested < 0.999:
            residual_reason = "position_caps_or_liquidity_caps_left_cash"
        selected["residual_cash_reason"] = residual_reason
    return selected.sort_values("weight", ascending=False).reset_index(drop=True)


def apply_benchmark_risk_overlay(
    selection: pd.DataFrame,
    variant: MarketLeaderVariant,
    prices: dict[str, pd.DataFrame],
    rebalance_date: Any,
) -> pd.DataFrame:
    if selection.empty:
        return selection
    d = selection.copy()
    if variant.risk_mode != RISK_MODE_BENCHMARK_GUARD:
        signal = {
            "market_regime": "risk_on",
            "gross_exposure_cap": 1.0,
            "risk_overlay_reason": "risk_mode_none",
            "benchmark_risk_score": 0,
        }
    else:
        signal = benchmark_guard_signal(prices, rebalance_date, variant.portfolio_kind)
    gross = safe_float(signal.get("gross_exposure_cap"), 1.0)
    gross = min(max(gross, 0.0), 1.0)
    d["risk_mode"] = variant.risk_mode
    for key, value in signal.items():
        d[key] = value
    if gross < 0.999:
        d["weight"] = pd.to_numeric(d["weight"], errors="coerce").fillna(0.0) * gross
        d["target_weight"] = d["weight"]
        reason = str(signal.get("risk_overlay_reason") or "benchmark_risk_gross_cap")
        if "selection_reason" in d.columns:
            d["selection_reason"] = d["selection_reason"].astype(str) + ",benchmark_risk_gross_cap"
        if "residual_cash_reason" in d.columns:
            d["residual_cash_reason"] = d["residual_cash_reason"].where(
                d["residual_cash_reason"].astype(str).str.len().gt(0),
                f"benchmark_risk_overlay:{reason}",
            )
    return d


def rejection_reason(row: pd.Series, selected_tickers: set[str], variant: MarketLeaderVariant, selected: pd.DataFrame) -> str:
    ticker = str(row.get("ticker") or "").upper()
    if ticker in selected_tickers:
        return "selected"
    if str(row.get("leader_tier")) not in allowed_tiers(variant.portfolio_kind):
        return "failed_dual_benchmark" if variant.portfolio_kind == "concentrated" else "failed_leader_tier_gate"
    if str(row.get("leader_state")) == "EXIT_REPLACE":
        return "exit_replace_state"
    if str(row.get("leader_state")) == "WARNING" and safe_float(row.get("was_prev_holding")) <= 0:
        return "warning_no_new_add"
    if safe_float(row.get("liquidity_capacity_weight_cap")) <= 0:
        return "liquidity_too_low"
    if not selected.empty:
        sub = str(row.get("leader_subindustry") or "")
        theme = str(row.get("leader_broad_theme") or "")
        if sub and float(selected.loc[selected["leader_subindustry"].astype(str).eq(sub), "weight"].sum()) >= float(variant.subindustry_cap) - 1e-9:
            return "same_subindustry_cap"
        if theme and float(selected.loc[selected["leader_broad_theme"].astype(str).eq(theme), "weight"].sum()) >= float(variant.theme_cap) - 1e-9:
            return "same_theme_cap"
    return "not_top_n"


def target_book_columns() -> list[str]:
    return [
        "rebalance_date",
        "ticker",
        "Name",
        "sector",
        "weight",
        "target_weight",
        "leader_selection_score",
        "leader_tier",
        "leader_state",
        "warning_streak",
        "exit_streak",
        "market_leader_tape_score",
        "sector_leadership_score",
        "future_winner_confirmation_score",
        "smart_money_confirmation_score",
        "smart_money_confirmation_boost",
        "smart_money_evidence_confidence",
        "leader_chase_risk_score",
        "chase_risk_weight_scale",
        "effective_single_weight_cap",
        "liquidity_capacity_score",
        "liquidity_capacity_weight_cap",
        "risk_mode",
        "market_regime",
        "gross_exposure_cap",
        "risk_overlay_reason",
        "benchmark_risk_score",
        "selection_reason",
        "residual_cash_reason",
        "was_prev_holding",
        "holding_months",
        "portfolio_kind",
        "variant_id",
        "target_n",
        "target_stock_names",
        "weighting_mode",
        "active_rebalance_interval_months",
        "single_cap",
        "subindustry_cap",
        "theme_cap",
        "rs_spy_1m",
        "rs_spy_3m",
        "rs_spy_6m",
        "rs_qqq_1m",
        "rs_qqq_3m",
        "rs_qqq_6m",
        "rs_price_coverage_flag",
    ]


def target_rows_from_selection(selection: pd.DataFrame, variant: MarketLeaderVariant, rebalance_date: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    score_col = _score_col(variant.portfolio_kind)
    for _, row in selection.iterrows():
        out = {col: row.get(col, "") for col in target_book_columns()}
        out.update(
            {
                "rebalance_date": pd.Timestamp(rebalance_date).date().isoformat(),
                "ticker": str(row.get("ticker") or "").upper(),
                "weight": safe_float(row.get("weight")),
                "target_weight": safe_float(row.get("target_weight")),
                "leader_selection_score": safe_float(row.get(score_col)),
                "portfolio_kind": variant.portfolio_kind,
                "variant_id": variant.variant_id,
                "target_n": variant.target_n,
                "target_stock_names": variant.target_n,
                "weighting_mode": "market_leader_score_power",
                "active_rebalance_interval_months": 1,
                "single_cap": variant.single_cap,
                "subindustry_cap": variant.subindustry_cap,
                "theme_cap": variant.theme_cap,
                "risk_mode": variant.risk_mode,
            }
        )
        rows.append(out)
    invested = sum(safe_float(row.get("weight")) for row in rows)
    if invested < 0.999:
        rows.append(
            {
                "rebalance_date": pd.Timestamp(rebalance_date).date().isoformat(),
                "ticker": CASH_TICKER,
                "Name": "Cash",
                "sector": "Cash",
                "weight": max(0.0, 1.0 - invested),
                "target_weight": max(0.0, 1.0 - invested),
                "leader_selection_score": 0.0,
                "leader_tier": "CASH",
                "leader_state": "CASH",
                "portfolio_kind": variant.portfolio_kind,
                "variant_id": variant.variant_id,
                "target_n": variant.target_n,
                "target_stock_names": variant.target_n,
                "weighting_mode": "market_leader_score_power",
                "active_rebalance_interval_months": 1,
                "single_cap": variant.single_cap,
                "subindustry_cap": variant.subindustry_cap,
                "theme_cap": variant.theme_cap,
                "risk_mode": variant.risk_mode,
                "market_regime": "cash",
                "gross_exposure_cap": 0.0,
                "risk_overlay_reason": str(rows[0].get("risk_overlay_reason") or "") if rows else "",
                "benchmark_risk_score": safe_float(rows[0].get("benchmark_risk_score"), 0.0) if rows else 0.0,
                "selection_reason": "residual_cash_from_caps",
                "residual_cash_reason": str(rows[0].get("residual_cash_reason") or "position_caps_or_liquidity_caps_left_cash") if rows else "no_selected_leaders",
            }
        )
    return rows
