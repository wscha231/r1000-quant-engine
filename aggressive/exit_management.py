"""Exit Management for Aggressive engine - Phase B4.

For positions already held (in Alpaca or manually tracked), continuously
evaluates six exit signals and returns an ExitDecision per position.

Exit checks (in priority order):
  1. HARD_STOP: entry -8% (O'Neil hard rule, never negotiable)
  2. TRAILING_STOP: peak * (1 - trail_pct), phase-dependent:
       early phase:    -10% (loose — let winners breathe)
       maturing phase: -7%  (tighten)
       peaking phase:  -5%  (quick to lock in)
  3. STAGE_3_TOP: climactic action:
       - Upper Bollinger touch (20, 2.0) AND
       - RSI(14) > 80 AND
       - Volume > 2x 20d avg
       - All three = distribution likely
  4. MA50_BREAK: close < MA50 on volume > 1.5x avg
  5. RS_BREAK: ticker RS 20d vs SPY drops into bottom-30% of theme
  6. TRIM_LEVELS: +20% -> trim 33%, +40% -> trim 50% (gains banking)

Actions returned:
  HOLD           no concerning signal
  WATCH          one minor signal; monitor
  TRIM_33        lock in 1/3 at profit target
  TRIM_50        lock in 1/2 at extended profit
  SELL_ALL       stop triggered or Stage 3 top
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd

from aggressive.signals_technical import atr, sma


# --- Trailing stop by phase -----------------------------------------------

TRAILING_STOP_BY_PHASE = {
    "early":    0.10,   # -10% from peak (room to breathe)
    "maturing": 0.07,   # -7%
    "peaking":  0.05,   # -5% (quick to lock)
    "ending":   0.03,   # -3% (exit immediately on any weakness)
    "dead":     0.02,   # effectively force-sell
    "unknown":  0.08,   # conservative default
}

HARD_STOP_FROM_ENTRY = 0.08           # O'Neil 8% rule
TRIM_LEVEL_1_PCT = 0.20               # first trim at +20%
TRIM_LEVEL_2_PCT = 0.40               # second trim at +40%


# --- Position + decision dataclasses --------------------------------------

@dataclass
class PositionSnapshot:
    """Input: what we hold."""
    ticker: str
    entry_price: float
    entry_date: str                   # "YYYY-MM-DD"
    qty: float
    theme_phase: str = "unknown"
    peak_price: Optional[float] = None      # if tracked externally; else computed
    trim_level_hit: int = 0                  # 0, 1, or 2 (how many trims already)


@dataclass
class ExitDecision:
    """Output: what to do."""
    ticker: str
    action: str = "HOLD"              # HOLD / WATCH / TRIM_33 / TRIM_50 / SELL_ALL
    urgency: str = "info"             # info / warning / critical
    current_price: float = 0.0
    entry_price: float = 0.0
    peak_price: float = 0.0
    pnl_pct: float = 0.0
    drawdown_from_peak_pct: float = 0.0
    stop_level_current: float = 0.0
    signals_fired: list[str] = field(default_factory=list)
    rationale: str = ""


# --- Individual check functions -------------------------------------------

def check_hard_stop(pos: PositionSnapshot, current_price: float) -> Optional[str]:
    """-8% hard rule from entry. Returns reason or None."""
    if current_price <= pos.entry_price * (1.0 - HARD_STOP_FROM_ENTRY):
        loss_pct = (current_price / pos.entry_price - 1.0) * 100.0
        return f"HARD_STOP: {loss_pct:+.1f}% from entry (O'Neil 8% rule)"
    return None


def check_trailing_stop(
    pos: PositionSnapshot,
    current_price: float,
    peak_price: float,
) -> tuple[Optional[str], float]:
    """Phase-aware trailing stop. Returns (reason, stop_level)."""
    trail_pct = TRAILING_STOP_BY_PHASE.get(pos.theme_phase, 0.08)
    stop_level = peak_price * (1.0 - trail_pct)
    if current_price <= stop_level and peak_price > pos.entry_price * 1.05:
        # Only fire if we had meaningful gain (peak > entry+5%)
        dd_pct = (current_price / peak_price - 1.0) * 100.0
        return (
            f"TRAILING_STOP: {dd_pct:+.1f}% from peak (${peak_price:.2f}) "
            f"[{pos.theme_phase} phase, -{trail_pct*100:.0f}% trail]",
            stop_level,
        )
    return None, stop_level


def check_stage3_top(df: pd.DataFrame) -> Optional[str]:
    """Climactic distribution: upper BB + RSI>80 + volume surge."""
    if len(df) < 25:
        return None
    c = df["close"]
    v = df["volume"]
    ma20 = sma(c, 20)
    std20 = c.rolling(20, min_periods=10).std()
    upper_bb = ma20 + 2.0 * std20

    # RSI(14)
    delta = c.diff()
    gain = delta.where(delta > 0, 0.0).rolling(14, min_periods=7).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(14, min_periods=7).mean()
    rs = gain / (loss + 1e-9)
    rsi = 100.0 - 100.0 / (1.0 + rs)

    latest_close = float(c.iloc[-1])
    bb_touch = latest_close >= float(upper_bb.iloc[-1]) * 0.995
    high_rsi = float(rsi.iloc[-1]) > 78.0
    v20 = float(sma(v, 20).iloc[-1])
    vol_surge = float(v.iloc[-1]) > 2.0 * v20

    if bb_touch and high_rsi and vol_surge:
        return (
            f"STAGE_3_TOP: upper BB + RSI {rsi.iloc[-1]:.0f} + "
            f"vol {v.iloc[-1]/v20:.1f}x (climactic action)"
        )
    return None


def check_ma50_break(df: pd.DataFrame) -> Optional[str]:
    """Close below MA50 on high volume."""
    if len(df) < 55:
        return None
    c = df["close"]
    v = df["volume"]
    ma50 = sma(c, 50)
    v20 = float(sma(v, 20).iloc[-1])
    latest_close = float(c.iloc[-1])
    latest_ma50 = float(ma50.iloc[-1])
    vol_ratio = float(v.iloc[-1]) / (v20 + 1e-9)

    # Must have broken BELOW MA50 (prev was above) and volume > 1.3x
    if len(ma50) >= 2:
        prev_close = float(c.iloc[-2])
        prev_ma50 = float(ma50.iloc[-2])
        just_broke = prev_close > prev_ma50 and latest_close < latest_ma50
    else:
        just_broke = False

    if just_broke and vol_ratio > 1.3:
        return (
            f"MA50_BREAK: close ${latest_close:.2f} below MA50 ${latest_ma50:.2f} "
            f"on vol {vol_ratio:.1f}x"
        )
    # Or sustained below MA50 for 3+ days
    if latest_close < latest_ma50 * 0.98 and len(c) >= 3:
        recent = c.iloc[-3:]
        if (recent < ma50.iloc[-3:]).all():
            return (
                f"MA50_BREAK: 3d sustained below MA50 ${latest_ma50:.2f} "
                f"(close ${latest_close:.2f})"
            )
    return None


def check_rs_break(
    df: pd.DataFrame,
    spy_df: pd.DataFrame,
) -> Optional[str]:
    """Ticker RS line vs SPY breaks down (RS 20d below -5%)."""
    if df.empty or spy_df.empty or len(df) < 25 or len(spy_df) < 25:
        return None
    aligned = pd.concat(
        [df["close"].rename("tkr"), spy_df["close"].rename("spy")],
        axis=1, join="inner",
    ).dropna()
    if len(aligned) < 25:
        return None
    rs = aligned["tkr"] / aligned["spy"]
    # 20-day RS return
    if len(rs) >= 21:
        rs_20d = (rs.iloc[-1] / rs.iloc[-21] - 1.0) * 100.0
        if rs_20d < -5.0:
            return f"RS_BREAK: 20d RS vs SPY {rs_20d:+.1f}% (underperforming)"
    return None


def check_trim_level(
    pos: PositionSnapshot, current_price: float
) -> Optional[tuple[str, str]]:
    """Gain-based scale-out. Returns (action, reason) or None."""
    pnl_pct = (current_price / pos.entry_price - 1.0)
    if pos.trim_level_hit == 0 and pnl_pct >= TRIM_LEVEL_1_PCT:
        return ("TRIM_33", f"TRIM_LEVEL_1: +{pnl_pct*100:.1f}% gain, lock 1/3")
    if pos.trim_level_hit == 1 and pnl_pct >= TRIM_LEVEL_2_PCT:
        return ("TRIM_50", f"TRIM_LEVEL_2: +{pnl_pct*100:.1f}% gain, lock 1/2 of remainder")
    return None


# --- Combined evaluator ----------------------------------------------------

def evaluate_position(
    pos: PositionSnapshot,
    df: pd.DataFrame,
    spy_df: Optional[pd.DataFrame] = None,
) -> ExitDecision:
    """Run all exit checks on one position. Returns prioritized decision."""
    if df.empty:
        return ExitDecision(
            ticker=pos.ticker,
            action="HOLD",
            rationale="no price data available",
        )

    current_price = float(df["close"].iloc[-1])
    # Compute peak price if not provided
    peak_price = pos.peak_price or float(df["close"].max())
    pnl_pct = (current_price / pos.entry_price - 1.0) * 100.0
    dd_from_peak = (current_price / peak_price - 1.0) * 100.0

    decision = ExitDecision(
        ticker=pos.ticker,
        action="HOLD",
        current_price=current_price,
        entry_price=pos.entry_price,
        peak_price=peak_price,
        pnl_pct=pnl_pct,
        drawdown_from_peak_pct=dd_from_peak,
    )

    # Run all checks (priority order matters for action override)
    reasons: list[str] = []

    # 1. Hard stop - overrides everything
    hard = check_hard_stop(pos, current_price)
    if hard:
        reasons.append(hard)
        decision.action = "SELL_ALL"
        decision.urgency = "critical"

    # 2. Trailing stop
    trail_reason, stop_level = check_trailing_stop(pos, current_price, peak_price)
    decision.stop_level_current = stop_level
    if trail_reason and decision.action != "SELL_ALL":
        reasons.append(trail_reason)
        decision.action = "SELL_ALL"
        decision.urgency = "critical"

    # 3. Stage 3 top
    stage3 = check_stage3_top(df)
    if stage3:
        reasons.append(stage3)
        if decision.action == "HOLD":
            decision.action = "TRIM_50"    # lock half, watch rest
            decision.urgency = "warning"

    # 4. MA50 break
    ma50 = check_ma50_break(df)
    if ma50:
        reasons.append(ma50)
        if decision.action == "HOLD":
            decision.action = "WATCH"
            decision.urgency = "warning"

    # 5. RS break
    if spy_df is not None and not spy_df.empty:
        rs_reason = check_rs_break(df, spy_df)
        if rs_reason:
            reasons.append(rs_reason)
            if decision.action == "HOLD":
                decision.action = "WATCH"
                decision.urgency = "warning"

    # 6. Trim levels (additive, only if no stop)
    if decision.action in ("HOLD", "WATCH"):
        trim = check_trim_level(pos, current_price)
        if trim:
            trim_action, trim_reason = trim
            reasons.append(trim_reason)
            decision.action = trim_action
            decision.urgency = "info"

    decision.signals_fired = reasons

    # Build rationale
    trail_pct = TRAILING_STOP_BY_PHASE.get(pos.theme_phase, 0.08) * 100.0
    decision.rationale = (
        f"{pos.ticker} entry ${pos.entry_price:.2f} -> now ${current_price:.2f} "
        f"(P/L {pnl_pct:+.1f}%, peak ${peak_price:.2f} "
        f"dd {dd_from_peak:+.1f}%, trail -{trail_pct:.0f}%) | action={decision.action}"
    )
    if reasons:
        decision.rationale += "\n  signals: " + "; ".join(reasons)

    return decision


# --- Display helpers -------------------------------------------------------

def format_decision_brief(dec: ExitDecision) -> str:
    """One-line summary."""
    icon = {
        "HOLD": "[HOLD]",
        "WATCH": "[WATCH]",
        "TRIM_33": "[TRIM33]",
        "TRIM_50": "[TRIM50]",
        "SELL_ALL": "[SELL]",
    }.get(dec.action, "[?]")
    return (
        f"{icon} {dec.ticker:<6} ${dec.current_price:>7.2f} "
        f"PnL {dec.pnl_pct:+6.1f}% pk${dec.peak_price:>7.2f} "
        f"dd {dec.drawdown_from_peak_pct:+5.1f}% "
        f"stop${dec.stop_level_current:>7.2f}"
    )


def format_decision_full(dec: ExitDecision) -> str:
    lines = [
        f"=== {dec.ticker} POSITION REVIEW ===",
        f"Action:        {dec.action}  [{dec.urgency.upper()}]",
        f"Current:       ${dec.current_price:.2f}",
        f"Entry:         ${dec.entry_price:.2f}",
        f"P/L:           {dec.pnl_pct:+.2f}%",
        f"Peak:          ${dec.peak_price:.2f}",
        f"DD from peak:  {dec.drawdown_from_peak_pct:+.2f}%",
        f"Trailing stop: ${dec.stop_level_current:.2f}",
    ]
    if dec.signals_fired:
        lines.append("Signals:")
        for s in dec.signals_fired:
            lines.append(f"  - {s}")
    return "\n".join(lines)


# --- Smoke test ------------------------------------------------------------

if __name__ == "__main__":
    from aggressive.data_alpaca import fetch_daily_bars, fetch_spy_benchmark

    print("=" * 78)
    print("Exit Management - Smoke Test")
    print("=" * 78)

    spy = fetch_spy_benchmark(days=260)

    # Simulate holding positions at various entry points
    test_positions = [
        # Recent strong winners (likely HOLD or trim)
        PositionSnapshot("AMD",  entry_price=150.0, entry_date="2026-01-15",
                         qty=100, theme_phase="peaking"),
        PositionSnapshot("AVGO", entry_price=300.0, entry_date="2026-01-15",
                         qty=50, theme_phase="peaking"),
        PositionSnapshot("WDC",  entry_price=280.0, entry_date="2026-03-01",
                         qty=100, theme_phase="peaking"),
        # A hypothetical underwater position
        PositionSnapshot("BKNG", entry_price=5500.0, entry_date="2026-01-15",
                         qty=10, theme_phase="dead"),
        # A maturing winner near breakout
        PositionSnapshot("CSCO", entry_price=75.0, entry_date="2026-02-01",
                         qty=500, theme_phase="early"),
        PositionSnapshot("TXN",  entry_price=210.0, entry_date="2026-02-01",
                         qty=100, theme_phase="maturing"),
    ]

    print()
    for pos in test_positions:
        df = fetch_daily_bars(pos.ticker, days=260)
        if df.empty:
            print(f"{pos.ticker}: NO DATA")
            continue
        dec = evaluate_position(pos, df, spy)
        print(format_decision_brief(dec))

    # Show full detail for one
    print()
    print("--- Full decision example (WDC) ---")
    pos = test_positions[2]
    df = fetch_daily_bars(pos.ticker, days=260)
    dec = evaluate_position(pos, df, spy)
    print(format_decision_full(dec))

    print()
    print("PASS")
