"""Technical Early Entry Signals for Aggressive engine.

Four-tier detection system that answers the user's question:
  "차트분석 기술적분석만으로 가능할려나?" (Can we do it with just technicals?)

Answer: YES for early-rise detection, with fundamentals as minimum quality gate.

Tier 1 — Stage 2 Breakout (Weinstein):
    - Price > SMA30 > SMA50 > SMA200 (all MAs aligned bullish)
    - SMA200 slope positive (30-day regression)
    - Close in top 5% of 52-week range (near new highs)
    - Volume ≥ 2x 20-day average on the breakout day
    - Intended signal horizon: multi-month hold (Stage 2 can last months)

Tier 2 — VCP Base Breakout (Minervini / CANSLIM):
    - 6-12 week base formed (price within 20% range)
    - Volatility contraction: ATR trending down during base
    - Pivot breakout: close > base_high * 1.005
    - Volume surge ≥ 1.5x on breakout
    - Intended signal horizon: 2-6 week swing

Tier 3 — Post-Earnings Gap (technical-only PEAD):
    - Gap-up ≥ 5% (open > prev_close * 1.05)
    - Close in top 20% of the gap-day range (close strong)
    - Volume ≥ 3x 20-day average (institutional participation)
    - No gap fill in following 3 days
    - Intended signal horizon: 1-4 week drift

Tier 4 — RS Acceleration (Relative Strength surge):
    - 20d price change > 15% (absolute)
    - RS line (ticker/SPY) at 20-day high
    - 5d return > 5%
    - Rising on rising volume (OBV up)
    - Intended signal horizon: 1-3 month momentum phase

Each tier returns a score 0-100. Composite is the MAX across tiers
(we want the strongest single signal, not an average that dilutes).

This module operates on pandas DataFrames produced by data_alpaca.py.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd


# --- Helper indicators ------------------------------------------------------

def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=max(5, n // 4)).mean()


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    """Average True Range."""
    h = df["high"]; l = df["low"]; c = df["close"]
    pc = c.shift(1)
    tr = pd.concat([(h - l), (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    return tr.rolling(n, min_periods=max(5, n // 4)).mean()


def slope_pct(s: pd.Series, n: int) -> float:
    """Linear regression slope over last n bars, expressed as % per bar."""
    tail = s.tail(n).dropna()
    if len(tail) < max(5, n // 2):
        return float("nan")
    x = np.arange(len(tail), dtype=float)
    y = tail.values.astype(float)
    coef = np.polyfit(x, y, 1)[0]
    mean = float(np.mean(y))
    return (coef / mean) * 100.0 if mean else 0.0


def obv(df: pd.DataFrame) -> pd.Series:
    """On-Balance Volume."""
    direction = np.sign(df["close"].diff().fillna(0.0))
    return (direction * df["volume"]).cumsum()


def pct_change(s: pd.Series, n: int) -> float:
    """Percent change over last n bars."""
    if len(s) < n + 1:
        return float("nan")
    return (s.iloc[-1] / s.iloc[-1 - n] - 1.0) * 100.0


# --- Tier result dataclass -------------------------------------------------

@dataclass
class TierSignal:
    """Result of one tier's evaluation for one ticker."""
    tier: int
    name: str
    fired: bool
    score: float                     # 0-100
    checks: dict[str, bool] = field(default_factory=dict)
    metrics: dict[str, float] = field(default_factory=dict)
    rationale: str = ""


# --- Tier 1: Stage 2 Breakout ----------------------------------------------

def tier1_stage2_breakout(df: pd.DataFrame) -> TierSignal:
    """Weinstein Stage 2 breakout detection.

    Signal fires when a stock transitions from Stage 1 accumulation to Stage 2 markup.
    """
    if len(df) < 210:
        return TierSignal(1, "Stage 2 Breakout", False, 0.0,
                          rationale="insufficient history")

    c = df["close"]
    v = df["volume"]
    ma30 = sma(c, 30)
    ma50 = sma(c, 50)
    ma200 = sma(c, 200)
    v20 = sma(v, 20)

    price_latest = float(c.iloc[-1])
    price_52w_high = float(c.tail(252).max())
    price_52w_low = float(c.tail(252).min())

    # Position in 52-week range (1.0 = at high, 0.0 = at low)
    range52 = (price_latest - price_52w_low) / (price_52w_high - price_52w_low + 1e-9)

    # Checks
    ma_aligned = price_latest > ma30.iloc[-1] > ma50.iloc[-1] > ma200.iloc[-1]
    ma200_slope = slope_pct(ma200, 30)
    ma200_rising = ma200_slope > 0.02   # ~0.5%/month
    near_high = range52 >= 0.95          # in top 5% of 52w range
    vol_surge = float(v.iloc[-1]) >= 2.0 * float(v20.iloc[-1])

    # 10-day price strength (breakout confirmation)
    ret_10d = pct_change(c, 10)
    strong_10d = ret_10d > 5.0

    checks = {
        "ma_aligned_bullish": bool(ma_aligned),
        "ma200_rising": bool(ma200_rising),
        "near_52w_high": bool(near_high),
        "volume_surge_2x": bool(vol_surge),
        "strong_10d_return": bool(strong_10d),
    }
    metrics = {
        "price": price_latest,
        "price_52w_high": price_52w_high,
        "range52_pct": range52 * 100.0,
        "ma200_slope_pct_per_bar": float(ma200_slope),
        "volume_ratio_20d": float(v.iloc[-1]) / float(v20.iloc[-1] + 1e-9),
        "ret_10d_pct": ret_10d,
    }

    n_passed = sum(checks.values())
    # Require ma_aligned + ma200_rising + (near_high OR vol_surge) as minimum
    fired = checks["ma_aligned_bullish"] and checks["ma200_rising"] and (
        checks["near_52w_high"] or checks["volume_surge_2x"]
    )
    score = (n_passed / 5.0) * 100.0 if fired else (n_passed / 5.0) * 40.0

    rationale = (
        f"Range52={range52*100:.0f}%, MA200 slope={ma200_slope:+.3f}%/bar, "
        f"vol={metrics['volume_ratio_20d']:.1f}x, 10d={ret_10d:+.1f}% "
        f"[{n_passed}/5 checks]"
    )

    return TierSignal(1, "Stage 2 Breakout", fired, score, checks, metrics, rationale)


# --- Tier 2: VCP Base Breakout ---------------------------------------------

def tier2_vcp_breakout(df: pd.DataFrame) -> TierSignal:
    """Minervini VCP (Volatility Contraction Pattern) base breakout.

    Looks for 6-12 week base with declining ATR, then pivot breakout.
    """
    if len(df) < 70:
        return TierSignal(2, "VCP Breakout", False, 0.0,
                          rationale="insufficient history")

    c = df["close"]
    v = df["volume"]
    atr14 = atr(df, 14)
    v20 = sma(v, 20)

    # Define base: last 8 weeks (≈40 bars)
    base = c.tail(40).iloc[:-1]        # exclude latest bar (the potential pivot)
    base_high = float(base.max())
    base_low = float(base.min())
    base_range_pct = (base_high - base_low) / base_low * 100.0

    price_latest = float(c.iloc[-1])

    # ATR contraction: compare early-base ATR to late-base ATR
    atr_early = float(atr14.iloc[-40:-20].mean())
    atr_late = float(atr14.iloc[-20:-1].mean())
    atr_contracting = atr_late < atr_early * 0.85   # 15% decline

    # Pivot breakout
    pivot_target = base_high * 1.005
    pivot_break = price_latest > pivot_target
    pivot_break_clean = price_latest > base_high * 1.015  # > 1.5% above

    # Volume surge on breakout
    vol_surge = float(v.iloc[-1]) >= 1.5 * float(v20.iloc[-1])

    # Base quality: range < 25% (tight base)
    tight_base = base_range_pct < 25.0

    # Base age (look for 6-12 week formation)
    # Find last bar that was > base_high (i.e. when did the base start?)
    over_high = c.tail(80).iloc[:-40] > base_high
    base_age_weeks = 40 // 5  # we just look at the 8w window for now

    checks = {
        "pivot_breakout": bool(pivot_break),
        "clean_breakout": bool(pivot_break_clean),
        "atr_contracting": bool(atr_contracting),
        "volume_surge_1.5x": bool(vol_surge),
        "tight_base_lt25pct": bool(tight_base),
    }
    metrics = {
        "base_high": base_high,
        "base_low": base_low,
        "base_range_pct": base_range_pct,
        "pivot_target": pivot_target,
        "price": price_latest,
        "breakout_margin_pct": (price_latest / base_high - 1.0) * 100.0,
        "atr_ratio": atr_late / (atr_early + 1e-9),
        "volume_ratio_20d": float(v.iloc[-1]) / float(v20.iloc[-1] + 1e-9),
    }

    n_passed = sum(checks.values())
    fired = checks["pivot_breakout"] and checks["atr_contracting"] and (
        checks["volume_surge_1.5x"] or checks["clean_breakout"]
    )
    score = (n_passed / 5.0) * 100.0 if fired else (n_passed / 5.0) * 40.0

    rationale = (
        f"Base={base_range_pct:.1f}% range, ATR ratio={metrics['atr_ratio']:.2f}, "
        f"breakout margin={metrics['breakout_margin_pct']:+.2f}%, "
        f"vol={metrics['volume_ratio_20d']:.1f}x [{n_passed}/5]"
    )

    return TierSignal(2, "VCP Breakout", fired, score, checks, metrics, rationale)


# --- Tier 3: Post-Earnings Gap ---------------------------------------------

def tier3_earnings_gap(df: pd.DataFrame, lookback_days: int = 5) -> TierSignal:
    """Post-earnings gap-up followed by strong close and no fade.

    Pure-technical PEAD — no earnings calendar required; detects the gap itself.
    Scans the last `lookback_days` for a qualifying gap event.
    """
    if len(df) < 30:
        return TierSignal(3, "Earnings Gap", False, 0.0,
                          rationale="insufficient history")

    o = df["open"]; h = df["high"]; l = df["low"]; c = df["close"]; v = df["volume"]
    v20 = sma(v, 20)
    pc = c.shift(1)

    # Find gap-up day in last lookback_days
    gap_pct = (o / pc - 1.0) * 100.0
    best_idx = None
    best_gap_pct = 0.0
    for i in range(max(0, len(df) - lookback_days), len(df)):
        if gap_pct.iloc[i] >= 5.0 and gap_pct.iloc[i] > best_gap_pct:
            best_gap_pct = float(gap_pct.iloc[i])
            best_idx = i

    if best_idx is None:
        return TierSignal(3, "Earnings Gap", False, 0.0,
                          checks={"gap_up_5pct": False},
                          rationale="no gap-up ≥5% in lookback window")

    # Close strength on gap day (top 20% of range)
    rng = h.iloc[best_idx] - l.iloc[best_idx]
    close_pos = (c.iloc[best_idx] - l.iloc[best_idx]) / (rng + 1e-9)
    close_strong = close_pos >= 0.80

    # Volume surge on gap day
    vol_ratio = float(v.iloc[best_idx]) / float(v20.iloc[best_idx] + 1e-9)
    vol_surge = vol_ratio >= 3.0

    # No gap fill after: has price stayed above gap day's open?
    bars_since = len(df) - 1 - best_idx
    post_close = c.iloc[best_idx + 1:].min() if bars_since > 0 else c.iloc[best_idx]
    no_gap_fill = post_close >= o.iloc[best_idx] * 0.98   # within 2% of gap open

    # Follow-through: close above gap day high within 3 days
    follow_through = False
    if bars_since >= 1:
        follow_through = bool((c.iloc[best_idx + 1: best_idx + 4] > h.iloc[best_idx]).any())

    checks = {
        "gap_up_5pct": True,
        "close_strong_top20pct": bool(close_strong),
        "volume_3x_surge": bool(vol_surge),
        "no_gap_fill": bool(no_gap_fill),
        "follow_through_3d": bool(follow_through),
    }
    metrics = {
        "gap_pct": best_gap_pct,
        "close_position_in_range": float(close_pos),
        "volume_ratio_20d": vol_ratio,
        "bars_since_gap": float(bars_since),
    }

    n_passed = sum(checks.values())
    fired = checks["gap_up_5pct"] and checks["close_strong_top20pct"] and checks["no_gap_fill"]
    score = (n_passed / 5.0) * 100.0 if fired else (n_passed / 5.0) * 40.0

    rationale = (
        f"Gap={best_gap_pct:+.1f}%, close_pos={close_pos:.2f}, "
        f"vol={vol_ratio:.1f}x, {bars_since}d since gap [{n_passed}/5]"
    )

    return TierSignal(3, "Earnings Gap", fired, score, checks, metrics, rationale)


# --- Tier 4: RS Acceleration -----------------------------------------------

def tier4_rs_acceleration(
    df: pd.DataFrame,
    spy_df: Optional[pd.DataFrame] = None,
) -> TierSignal:
    """Relative Strength acceleration — early momentum phase detection.

    RS line (ticker_close / spy_close) making new 20-day highs while
    absolute price also surging on rising volume.
    """
    if len(df) < 30:
        return TierSignal(4, "RS Acceleration", False, 0.0,
                          rationale="insufficient history")

    c = df["close"]; v = df["volume"]
    ret_20d = pct_change(c, 20)
    ret_5d = pct_change(c, 5)

    # Absolute momentum checks
    strong_20d = ret_20d > 15.0
    strong_5d = ret_5d > 5.0

    # RS vs SPY
    rs_new_high_20d = False
    rs_slope = float("nan")
    rs_ret_20d = float("nan")
    if spy_df is not None and not spy_df.empty and len(spy_df) >= 30:
        # Align indices (outer join on dates, forward-fill any gaps)
        aligned = pd.concat(
            [c.rename("tkr"), spy_df["close"].rename("spy")],
            axis=1, join="inner"
        ).dropna()
        if len(aligned) >= 25:
            rs_line = aligned["tkr"] / aligned["spy"]
            rs_new_high_20d = float(rs_line.iloc[-1]) >= float(rs_line.tail(20).max()) * 0.998
            rs_slope = slope_pct(rs_line, 20)
            if len(aligned) >= 21:
                rs_ret_20d = (rs_line.iloc[-1] / rs_line.iloc[-21] - 1.0) * 100.0

    # OBV rising
    obv_series = obv(df)
    obv_slope = slope_pct(obv_series, 20)
    obv_rising = obv_slope > 0.5    # rising OBV

    checks = {
        "ret_20d_gt_15pct": bool(strong_20d),
        "ret_5d_gt_5pct": bool(strong_5d),
        "rs_line_new_high_20d": bool(rs_new_high_20d),
        "obv_rising": bool(obv_rising),
    }
    metrics = {
        "ret_20d_pct": ret_20d,
        "ret_5d_pct": ret_5d,
        "rs_ret_20d_pct": rs_ret_20d,
        "rs_slope": rs_slope,
        "obv_slope": obv_slope,
    }

    n_passed = sum(checks.values())
    fired = checks["ret_20d_gt_15pct"] and (
        checks["rs_line_new_high_20d"] or checks["ret_5d_gt_5pct"]
    )
    score = (n_passed / 4.0) * 100.0 if fired else (n_passed / 4.0) * 40.0

    rationale = (
        f"20d={ret_20d:+.1f}%, 5d={ret_5d:+.1f}%, "
        f"RS_20d={rs_ret_20d:+.1f}%, OBV slope={obv_slope:+.2f} "
        f"[{n_passed}/4]"
    )

    return TierSignal(4, "RS Acceleration", fired, score, checks, metrics, rationale)


# --- Composite -------------------------------------------------------------

@dataclass
class TechnicalSignalResult:
    """Combined result for one ticker across all four tiers."""
    ticker: str
    fired_any: bool
    best_tier: int
    best_score: float
    composite_score: float           # max of all tier scores
    tiers: list[TierSignal] = field(default_factory=list)


def evaluate_ticker(
    ticker: str,
    df: pd.DataFrame,
    spy_df: Optional[pd.DataFrame] = None,
) -> TechnicalSignalResult:
    """Run all four tiers on a single ticker and pick the strongest signal."""
    t1 = tier1_stage2_breakout(df)
    t2 = tier2_vcp_breakout(df)
    t3 = tier3_earnings_gap(df)
    t4 = tier4_rs_acceleration(df, spy_df)
    tiers = [t1, t2, t3, t4]

    fired = [t for t in tiers if t.fired]
    best = max(tiers, key=lambda t: t.score)
    composite = max(t.score for t in tiers)

    return TechnicalSignalResult(
        ticker=ticker,
        fired_any=len(fired) > 0,
        best_tier=best.tier,
        best_score=best.score,
        composite_score=composite,
        tiers=tiers,
    )


# --- Smoke test ------------------------------------------------------------

if __name__ == "__main__":
    from aggressive.data_alpaca import fetch_daily_bars, fetch_spy_benchmark

    print("=" * 60)
    print("Technical Signals - Smoke Test")
    print("=" * 60)

    spy = fetch_spy_benchmark(days=260)
    # test tickers: NVDA (expected momentum), WDC (memory leader), BKNG (travel, peaking)
    test_tickers = ["NVDA", "AMD", "AVGO", "WDC", "STX", "LITE", "COHR", "PLTR", "BKNG"]
    for t in test_tickers:
        df = fetch_daily_bars(t, days=260)
        if df.empty:
            print(f"{t}: NO DATA")
            continue
        res = evaluate_ticker(t, df, spy)
        marker = "FIRED" if res.fired_any else "     "
        print(f"\n{marker} {t:<6} best=T{res.best_tier} score={res.best_score:5.1f}  "
              f"composite={res.composite_score:5.1f}")
        for tier in res.tiers:
            icon = "*" if tier.fired else " "
            print(f"    {icon} T{tier.tier} {tier.name:<22} "
                  f"score={tier.score:5.1f}  {tier.rationale}")
