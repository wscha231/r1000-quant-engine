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

    Phase 15-A (2026-04-28): adds 50-day volume ratio and quality flag to
    distinguish institutional accumulation breakouts from low-volume drifts.
    Low-volume breakouts get a 30% score haircut and a warning in the
    trade_card; the fire gate requires either a 2x 20d volume surge OR a
    1.5x 50d volume average — but not pure-price-only breakouts.
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
    v50 = sma(v, 50)

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
    # Phase 15-A: 50d ratio is a softer floor — quality breakouts should run
    # at least 1.5x the 50d average even if today's specific candle isn't 2x.
    vol_50d_ratio = float(v.iloc[-1]) / float(v50.iloc[-1] + 1e-9)
    quality_volume = vol_50d_ratio >= 1.5

    # 10-day price strength (breakout confirmation)
    ret_10d = pct_change(c, 10)
    strong_10d = ret_10d > 5.0

    checks = {
        "ma_aligned_bullish": bool(ma_aligned),
        "ma200_rising": bool(ma200_rising),
        "near_52w_high": bool(near_high),
        "volume_surge_2x": bool(vol_surge),
        "strong_10d_return": bool(strong_10d),
        "quality_volume_50d": bool(quality_volume),
    }
    metrics = {
        "price": price_latest,
        "price_52w_high": price_52w_high,
        "range52_pct": range52 * 100.0,
        "ma200_slope_pct_per_bar": float(ma200_slope),
        "volume_ratio_20d": float(v.iloc[-1]) / float(v20.iloc[-1] + 1e-9),
        "volume_ratio_50d": vol_50d_ratio,
        "ret_10d_pct": ret_10d,
    }

    n_passed = sum(checks.values())
    # Phase 15-A: fire gate now requires BOTH structure and volume — at least
    # ONE of (2x 20d surge / 1.5x 50d average). Pure-price breakouts (near_high
    # only) without ANY volume support no longer fire — they were the low-
    # quality breakouts the user flagged (SNDK loose-base example).
    has_volume_support = checks["volume_surge_2x"] or checks["quality_volume_50d"]
    fired = (
        checks["ma_aligned_bullish"]
        and checks["ma200_rising"]
        and checks["near_52w_high"]
        and has_volume_support
    )
    score_base = (n_passed / 6.0) * 100.0 if fired else (n_passed / 6.0) * 40.0
    # Score haircut for breakouts that fire on volume_surge_2x but lack the
    # 1.5x 50d average (single-day spike vs sustained accumulation).
    if fired and checks["volume_surge_2x"] and not checks["quality_volume_50d"]:
        score_base *= 0.70
    score = score_base

    rationale = (
        f"Range52={range52*100:.0f}%, MA200 slope={ma200_slope:+.3f}%/bar, "
        f"vol={metrics['volume_ratio_20d']:.1f}x20d / {vol_50d_ratio:.1f}x50d, "
        f"10d={ret_10d:+.1f}% [{n_passed}/6 checks]"
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


# --- Tier 5: Stage 1->2 Turnaround (Weinstein) -----------------------------

def tier5_stage_transition(
    df: pd.DataFrame,
    spy_df: Optional[pd.DataFrame] = None,
) -> TierSignal:
    """Detect Stage 1 -> Stage 2 turnaround: low-risk early entry.

    User insight (2026-04-24): "저점에서 장기 상승전환하는 주식을 사면
    마음 편하게 오래 가져갈 수 있다."

    This complements Tier 1 (which catches stocks at 52w high - chase phase).
    Tier 5 catches stocks turning UP from a long downtrend - safer early entry.

    Criteria (Weinstein 4-stage):
      1. Stage 4 history: 100+ days below MA200 in past year
      2. Recent MA200 cross: closed above MA200 within last 30 days
      3. MA200 slope flip: was negative 60 days ago, now flat/positive
      4. Off the lows: 30%+ recovery from 52-week low
      5. RS turning up: 3m RS > 6m RS
      6. Volume confirm: up-day volume > down-day volume (60d)
      7. Room to run: still 15-30% below 52w high (NOT extended)
    """
    if len(df) < 252:
        return TierSignal(5, "Stage 1->2 Turnaround", False, 0.0,
                          rationale="insufficient history (need 252+ days)")

    c = df["close"]
    v = df["volume"]
    ma200 = sma(c, 200)
    price_latest = float(c.iloc[-1])
    high_52w = float(c.tail(252).max())
    low_52w = float(c.tail(252).min())

    # 1. Stage 4 history: count days below MA200 in last 252
    last_year_close = c.tail(252).values
    last_year_ma200 = ma200.tail(252).values
    days_below = int(np.sum(last_year_close < last_year_ma200 * 0.98))   # 2% margin
    stage4_history = days_below >= 100

    # 2. Recent MA200 cross
    last_30 = c.tail(30).values
    last_30_ma = ma200.tail(30).values
    crossed_above = bool(np.any(last_30 > last_30_ma))     # crossed at any point in 30d
    currently_above = price_latest > float(ma200.iloc[-1])

    # 3. MA200 slope shift
    if len(ma200) >= 80:
        slope_current = slope_pct(ma200, 30)
        slope_60d_ago = slope_pct(ma200.iloc[:-60], 30) if len(ma200) >= 90 else slope_current
        slope_flipped = slope_60d_ago < -0.01 and slope_current > -0.01    # negative -> non-negative
    else:
        slope_flipped = False
        slope_current = 0.0
        slope_60d_ago = 0.0

    # 4. Off the lows (30%+ recovery)
    pct_off_low = (price_latest / low_52w - 1.0) * 100.0
    off_lows = pct_off_low >= 30.0

    # 5. RS turning up (3m vs 6m)
    rs_turning = False
    rs_3m = float("nan")
    rs_6m = float("nan")
    if spy_df is not None and not spy_df.empty:
        aligned = pd.concat(
            [c.rename("tkr"), spy_df["close"].rename("spy")],
            axis=1, join="inner",
        ).dropna()
        if len(aligned) >= 127:
            rs_line = aligned["tkr"] / aligned["spy"]
            if len(rs_line) >= 64:
                rs_3m = (rs_line.iloc[-1] / rs_line.iloc[-64] - 1.0) * 100.0
            if len(rs_line) >= 127:
                rs_6m = (rs_line.iloc[-1] / rs_line.iloc[-127] - 1.0) * 100.0
            if not pd.isna(rs_3m) and not pd.isna(rs_6m):
                rs_turning = rs_3m > rs_6m and rs_3m > -10.0

    # 6. Volume confirmation: up-day vol > down-day vol over 60d
    if len(df) >= 60:
        recent = df.tail(60)
        up_mask = recent["close"] > recent["close"].shift(1)
        up_vol = float(recent.loc[up_mask, "volume"].mean()) if up_mask.any() else 0.0
        down_vol = float(recent.loc[~up_mask, "volume"].mean()) if (~up_mask).any() else 1.0
        vol_confirm = up_vol > down_vol * 1.05
    else:
        vol_confirm = False
        up_vol = down_vol = 0.0

    # 7. Room to run (NOT at top — distinguishes from T1)
    pct_off_high = (price_latest / high_52w - 1.0) * 100.0   # negative if below high
    room_to_run = -30.0 < pct_off_high < -3.0    # 3-30% below high = sweet spot

    # Score (weighted)
    points = 0.0
    if stage4_history: points += 30.0
    if crossed_above and currently_above: points += 20.0
    if slope_flipped: points += 20.0
    if off_lows: points += 15.0
    if rs_turning: points += 10.0
    if vol_confirm: points += 5.0
    # Room-to-run is filter, not bonus

    # Fire condition: all major checks + room-to-run
    fired = (
        stage4_history and currently_above and (slope_flipped or off_lows)
        and rs_turning and room_to_run
    )

    checks = {
        "stage4_history_100d": bool(stage4_history),
        "currently_above_ma200": bool(currently_above),
        "ma200_slope_flipped": bool(slope_flipped),
        "off_lows_30pct": bool(off_lows),
        "rs_turning_up": bool(rs_turning),
        "volume_confirms": bool(vol_confirm),
        "room_to_run": bool(room_to_run),
    }
    metrics = {
        "days_below_ma200": float(days_below),
        "pct_off_52w_low": pct_off_low,
        "pct_off_52w_high": pct_off_high,
        "ma200_slope_now": slope_current,
        "ma200_slope_60d_ago": slope_60d_ago,
        "rs_3m_pct": rs_3m,
        "rs_6m_pct": rs_6m,
    }

    n_passed = sum(checks.values())
    score = points if fired else points * 0.5

    rationale = (
        f"days<MA200={days_below}, off_low=+{pct_off_low:.0f}%, "
        f"off_high={pct_off_high:+.0f}%, slope: {slope_60d_ago:.2f}->{slope_current:.2f}, "
        f"rs3m={rs_3m:+.0f}% rs6m={rs_6m:+.0f}%, [{n_passed}/7 checks]"
    )
    return TierSignal(5, "Stage 1->2 Turnaround", fired, score, checks, metrics, rationale)


# Data-driven tier weights from backtest (2026-04-25)
# 90d forward alpha vs SPY measured on 2023-2025 R1000 sample (n=1955 records).
# T1 (-2.52% alpha) and T2 (-0.42%) heavily discounted.
# T3 (+36.20% rare but powerful) and T4 (+10.34%) boosted.
TIER_ALPHA_WEIGHTS_90D = {
    1: 0.40,    # T1 Stage 2 Breakout: NEGATIVE alpha - chase 52w high underperforms
    2: 0.70,    # T2 VCP Breakout: weak alpha
    3: 1.50,    # T3 Earnings Gap: huge alpha when fires (rare event)
    4: 1.30,    # T4 RS Acceleration: workhorse positive alpha
    5: 1.10,    # T5 Turnaround: mild positive alpha
}


def evaluate_ticker(
    ticker: str,
    df: pd.DataFrame,
    spy_df: Optional[pd.DataFrame] = None,
) -> TechnicalSignalResult:
    """Run all five tiers + apply data-driven alpha weights to pick best.

    composite_score = max(tier.score * TIER_ALPHA_WEIGHTS[tier]) across all tiers.
    Best tier = the one whose weighted score wins (no longer just raw max).
    """
    t1 = tier1_stage2_breakout(df)
    t2 = tier2_vcp_breakout(df)
    t3 = tier3_earnings_gap(df)
    t4 = tier4_rs_acceleration(df, spy_df)
    t5 = tier5_stage_transition(df, spy_df)
    tiers = [t1, t2, t3, t4, t5]

    fired = [t for t in tiers if t.fired]
    # Weight-adjusted score for tier ranking
    weighted = [(t, t.score * TIER_ALPHA_WEIGHTS_90D.get(t.tier, 1.0)) for t in tiers]
    best, best_weighted_score = max(weighted, key=lambda x: x[1])
    composite = best_weighted_score

    return TechnicalSignalResult(
        ticker=ticker,
        fired_any=len(fired) > 0,
        best_tier=best.tier,
        best_score=best.score,           # raw score for transparency
        composite_score=composite,        # weight-adjusted (used by advisor)
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
