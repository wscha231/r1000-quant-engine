"""Entry Precision for Aggressive engine - Phase B3.

Transforms a technical signal (from signals_technical.py) into a complete
TradeCard: pivot price, buy zone, stop loss, profit targets, R:R ratio,
and a max entry window.

Design principles (Minervini / O'Neil / Weinstein):
  1. Pivot = logical resistance that price must clear for buy to trigger.
     Typically the base high of the last N weeks.
  2. Buy zone = pivot to pivot + 0.5*ATR or +3%, whichever is smaller.
     Paying up more than 3-5% above pivot destroys risk/reward.
  3. Stop = max(swing_low, entry - 2*ATR, entry * 0.93).
     Never risk more than 7-8% per position (O'Neil hard rule).
  4. Targets at R:R 2 / 3 / 5. Scale out progressively.
  5. Max entry window: 5 trading days after pivot breakout.
     After that, base is too extended, abort.

Output: TradeCard dataclass suitable for:
  - Display in scanner report
  - Direct conversion to Alpaca LimitOrderRequest
  - Telegram alert formatting
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

from aggressive.signals_technical import atr, sma


# --- TradeCard dataclass ---------------------------------------------------

@dataclass
class TradeCard:
    """Complete trade plan for one entry signal.

    All prices in USD. Percentages as decimals (0.08 = 8%).
    """
    ticker: str
    side: str = "BUY"
    signal_tier: int = 0
    signal_name: str = ""

    # Entry
    pivot_price: float = 0.0
    buy_zone_low: float = 0.0
    buy_zone_high: float = 0.0

    # Risk
    stop_loss: float = 0.0
    risk_pct: float = 0.0           # (buy_zone_low - stop) / buy_zone_low

    # Targets (R:R 2 / 3 / 5)
    target_1: float = 0.0
    target_2: float = 0.0
    target_3: float = 0.0

    # Quality
    risk_reward_ratio: float = 0.0  # to target_2 (primary)
    base_length_days: int = 0
    base_tightness_pct: float = 0.0  # range / base_low
    current_price: float = 0.0
    extension_from_pivot_pct: float = 0.0  # >3% means already extended

    # Timing
    max_entry_window_days: int = 5
    entry_status: str = "READY"     # READY / EXTENDED / FAILED / EARLY

    # Rationale
    rationale: str = ""
    warnings: list[str] = field(default_factory=list)


# --- Pivot detection -------------------------------------------------------

def compute_pivot_price(
    df: pd.DataFrame,
    base_weeks: int = 8,
    buffer_pct: float = 0.005,
) -> tuple[float, int, float]:
    """Find the base pivot = recent N-week high.

    Returns (pivot_price, base_length_days, base_tightness_pct).

    base_length_days: actual count of bars in the base
    base_tightness_pct: (base_high - base_low) / base_low - smaller = tighter
    """
    if len(df) < base_weeks * 5 + 5:
        return 0.0, 0, 0.0

    base_len = base_weeks * 5
    # Exclude latest bar (it may BE the breakout bar)
    base_bars = df["close"].iloc[-base_len - 1 : -1]
    if base_bars.empty:
        return 0.0, 0, 0.0

    base_high = float(base_bars.max())
    base_low = float(base_bars.min())
    pivot = base_high * (1.0 + buffer_pct)
    tightness = (base_high - base_low) / (base_low + 1e-9) * 100.0
    return pivot, len(base_bars), tightness


# --- Stop loss -------------------------------------------------------------

def compute_stop_loss(
    df: pd.DataFrame,
    entry_price: float,
    atr_mult: float = 2.0,
    max_risk_pct: float = 0.08,
) -> tuple[float, list[str]]:
    """Compute stop loss using THREE methods and take the tightest (highest).

    Methods:
      A. ATR-based: entry - atr_mult * ATR(14)
      B. Swing low: min(low) of last 20 bars (if within max_risk_pct)
      C. Max risk: entry * (1 - max_risk_pct)

    Returns (stop_price, notes_list).
    """
    notes: list[str] = []
    if df.empty or len(df) < 20 or entry_price <= 0:
        return entry_price * (1.0 - max_risk_pct), ["insufficient data - max risk stop"]

    atr14 = atr(df, 14).iloc[-1]
    if pd.isna(atr14):
        atr14 = df["close"].iloc[-20:].std()

    # Method A
    atr_stop = entry_price - atr_mult * float(atr14)

    # Method B: swing low of last 20 bars
    swing_low = float(df["low"].iloc[-20:].min()) * 0.99   # 1% buffer below

    # Method C: O'Neil hard rule
    hard_stop = entry_price * (1.0 - max_risk_pct)

    # Pick the TIGHTEST (highest = smallest risk)
    candidates = [
        (atr_stop, f"ATR x {atr_mult}"),
        (swing_low, "swing low -1%"),
        (hard_stop, f"hard {max_risk_pct*100:.0f}%"),
    ]
    # Sort descending, pick highest that's still below entry
    candidates = [(s, name) for s, name in candidates if s < entry_price]
    if not candidates:
        return hard_stop, ["fallback hard stop"]
    stop, method = max(candidates, key=lambda x: x[0])
    notes.append(f"stop method: {method}")
    return stop, notes


# --- Targets ---------------------------------------------------------------

def compute_targets(
    entry: float,
    stop: float,
    rr_ratios: tuple[float, ...] = (2.0, 3.0, 5.0),
) -> list[float]:
    """Compute price targets at given risk:reward ratios.

    target_N = entry + (entry - stop) * rr_N
    """
    risk = entry - stop
    if risk <= 0:
        return [entry * (1.0 + r * 0.05) for r in rr_ratios]
    return [entry + risk * r for r in rr_ratios]


# --- Composite entry card --------------------------------------------------

def build_trade_card(
    ticker: str,
    df: pd.DataFrame,
    signal_tier: int = 0,
    signal_name: str = "",
    base_weeks: int = 8,
) -> TradeCard:
    """Build complete trade card from price data + signal metadata.

    Usage:
        from aggressive.signals_technical import evaluate_ticker
        res = evaluate_ticker("AMD", df, spy)
        card = build_trade_card("AMD", df, res.best_tier, res.tiers[0].name)
    """
    card = TradeCard(ticker=ticker, signal_tier=signal_tier, signal_name=signal_name)

    if df.empty or len(df) < 30:
        card.entry_status = "FAILED"
        card.warnings.append("insufficient price history")
        return card

    current_price = float(df["close"].iloc[-1])
    card.current_price = current_price

    # 1. Pivot + base
    pivot, base_len, tightness = compute_pivot_price(df, base_weeks=base_weeks)
    if pivot <= 0:
        card.entry_status = "FAILED"
        card.warnings.append("no base detected")
        return card
    card.pivot_price = pivot
    card.base_length_days = base_len
    card.base_tightness_pct = tightness

    # 2. Buy zone: pivot to pivot + min(3%, 0.5*ATR)
    atr14 = float(atr(df, 14).iloc[-1]) if len(df) >= 14 else 0.0
    atr_extension = pivot + 0.5 * atr14
    pct_extension = pivot * 1.03
    buy_zone_high = min(atr_extension, pct_extension)
    card.buy_zone_low = pivot
    card.buy_zone_high = buy_zone_high

    # 3. Determine entry status based on current price
    extension_pct = (current_price / pivot - 1.0) * 100.0
    card.extension_from_pivot_pct = extension_pct

    if current_price < pivot * 0.98:
        card.entry_status = "EARLY"
        card.warnings.append(f"price ${current_price:.2f} below pivot ${pivot:.2f}")
    elif current_price > pivot * 1.05:
        card.entry_status = "EXTENDED"
        card.warnings.append(f"price extended {extension_pct:.1f}% above pivot")
    else:
        card.entry_status = "READY"

    # 4. Stop loss - use midpoint of buy zone as reference entry
    ref_entry = (card.buy_zone_low + card.buy_zone_high) / 2.0
    stop, stop_notes = compute_stop_loss(df, ref_entry)
    card.stop_loss = stop
    card.risk_pct = (ref_entry - stop) / ref_entry

    # 5. Targets
    targets = compute_targets(ref_entry, stop, (2.0, 3.0, 5.0))
    card.target_1 = targets[0]
    card.target_2 = targets[1]
    card.target_3 = targets[2]
    card.risk_reward_ratio = (card.target_2 - ref_entry) / (ref_entry - stop + 1e-9)

    # 6. Base quality warnings
    if tightness > 35.0:
        card.warnings.append(f"loose base ({tightness:.0f}% range) - lower quality")
    if base_len < 30:
        card.warnings.append(f"short base ({base_len} days) - higher failure risk")
    if card.risk_pct > 0.08:
        card.warnings.append(f"wide stop ({card.risk_pct*100:.1f}%) - consider smaller size")

    # 7. Rationale
    card.rationale = (
        f"pivot=${pivot:.2f} (base {base_len}d, {tightness:.0f}% tight) | "
        f"buy ${card.buy_zone_low:.2f}-${card.buy_zone_high:.2f} | "
        f"stop ${stop:.2f} (-{card.risk_pct*100:.1f}%) | "
        f"targets ${targets[0]:.2f}/{targets[1]:.2f}/{targets[2]:.2f} | "
        f"R:R {card.risk_reward_ratio:.1f} | status={card.entry_status}"
    )

    return card


# --- Display helpers -------------------------------------------------------

def format_trade_card_brief(card: TradeCard) -> str:
    """One-line summary for scanner table output."""
    status_icon = {
        "READY": "[OK]",
        "EARLY": "[WAIT]",
        "EXTENDED": "[LATE]",
        "FAILED": "[X]",
    }.get(card.entry_status, "[?]")
    return (
        f"{status_icon} {card.ticker:<6} pvt=${card.pivot_price:.1f} "
        f"buy=${card.buy_zone_low:.1f}-{card.buy_zone_high:.1f} "
        f"stop=${card.stop_loss:.1f} (-{card.risk_pct*100:.0f}%) "
        f"t2=${card.target_2:.1f} R:R={card.risk_reward_ratio:.1f}"
    )


def format_trade_card_full(card: TradeCard) -> str:
    """Multi-line detailed card for Telegram or report."""
    lines = [
        f"=== {card.ticker} TRADE CARD ===",
        f"Signal:        T{card.signal_tier} {card.signal_name}",
        f"Status:        {card.entry_status}",
        f"Current:       ${card.current_price:.2f}",
        f"Pivot:         ${card.pivot_price:.2f}  (base {card.base_length_days}d, "
        f"{card.base_tightness_pct:.0f}% tight)",
        f"Buy Zone:      ${card.buy_zone_low:.2f} - ${card.buy_zone_high:.2f}",
        f"Stop Loss:     ${card.stop_loss:.2f}  (risk {card.risk_pct*100:.1f}%)",
        f"Target 1 (2R): ${card.target_1:.2f}",
        f"Target 2 (3R): ${card.target_2:.2f}  <-- primary",
        f"Target 3 (5R): ${card.target_3:.2f}",
        f"R:R to T2:     {card.risk_reward_ratio:.1f}x",
        f"Extension:     {card.extension_from_pivot_pct:+.1f}% from pivot",
    ]
    if card.warnings:
        lines.append("Warnings:")
        for w in card.warnings:
            lines.append(f"  - {w}")
    return "\n".join(lines)


# --- Smoke test ------------------------------------------------------------

if __name__ == "__main__":
    from aggressive.data_alpaca import fetch_daily_bars, fetch_spy_benchmark
    from aggressive.signals_technical import evaluate_ticker

    print("=" * 70)
    print("Entry Precision - Smoke Test")
    print("=" * 70)

    spy = fetch_spy_benchmark(days=260)
    test_tickers = ["AMD", "AVGO", "ETSY", "TXN", "CSCO", "MCHP", "WDC", "COHR"]

    print()
    for t in test_tickers:
        df = fetch_daily_bars(t, days=260)
        if df.empty:
            print(f"{t}: NO DATA")
            continue
        sig = evaluate_ticker(t, df, spy)
        best_tier_obj = max(sig.tiers, key=lambda x: x.score)
        card = build_trade_card(t, df, sig.best_tier, best_tier_obj.name)
        print(format_trade_card_brief(card))

    print()
    print("--- Full card example (AMD) ---")
    df = fetch_daily_bars("AMD", days=260)
    sig = evaluate_ticker("AMD", df, spy)
    best_tier_obj = max(sig.tiers, key=lambda x: x.score)
    card = build_trade_card("AMD", df, sig.best_tier, best_tier_obj.name)
    print(format_trade_card_full(card))
    print()
    print("PASS")
