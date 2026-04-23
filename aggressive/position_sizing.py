"""Position Sizing for Aggressive engine - Phase B5.

Completely universe-agnostic: sizes based on signal strength + volatility +
theme phase + existing portfolio, NOT on specific tickers.

User constraint (2026-04-23): "하드코딩 금지. 순수하게 종목을 찾아내는 시스템."
This module contains ZERO hardcoded tickers.

Approach - modified Kelly + phase + risk parity:
  1. Base weight from final_score tier:
       score >= 100:  33%  (high conviction - top 3 of concentrated portfolio)
       score  80-99:  25%
       score  60-79:  15%
       score  < 60:   skip (below scanner min threshold anyway)

  2. Theme phase adjustment:
       early phase:    x1.20  (highest conviction - catch early)
       maturing:       x1.00  (neutral - normal size)
       peaking:        x0.70  (reduce - late entry)
       unknown:        x0.90  (slight discount - no theme context yet)
       ending/dead:    x0.00  (already disqualified upstream)

  3. Volatility cap (risk parity):
       Max position stake = (risk_budget_usd) / (stop_distance_pct)
       e.g. $2000 risk budget / 7% stop = $28,571 max position

  4. Portfolio diversification:
       - no more than N concentrated positions (cfg.portfolio_n = 3)
       - max 40% per position hard cap (cfg.max_position_weight = 0.50 config default)
       - min 5% per position (below this, not worth the transaction friction)

  5. Regime cash buffer:
       bull:          cash 0-5%
       balanced:      cash 15%
       bear:          cash 50%
       regime turn:   cash 100%

Output: SizedOrder per candidate with:
    - target_dollars, target_shares, target_weight_pct
    - entry_price_used (buy_zone midpoint)
    - stop_dollars (risk $ at stop)
    - rationale
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

from aggressive.agg_config import AggressiveConfig, load_agg_config
from aggressive.entry_precision import TradeCard
from aggressive.scanner import ScannerCandidate


# --- Tunable constants (not ticker-specific) -------------------------------

SCORE_TIER_BASE_WEIGHT = {
    # (min_score_inclusive, base_weight)
    100.0: 0.33,
    80.0:  0.25,
    60.0:  0.15,
    0.0:   0.00,
}

PHASE_ADJUSTMENT = {
    "early":    1.20,
    "maturing": 1.00,
    "peaking":  0.70,
    "unknown":  0.90,    # unknown = emerging-theme candidate, slight discount
    "ending":   0.00,
    "dead":     0.00,
}

RISK_BUDGET_PCT = 0.02    # 2% of capital risked per trade (conservative Kelly)
MIN_POSITION_WEIGHT = 0.05   # below 5%, not worth trading
MAX_POSITION_WEIGHT = 0.40   # hard cap, never > 40% per name
MAX_CONCENTRATED_POSITIONS = 3


# --- Regime cash target ----------------------------------------------------

REGIME_CASH_TARGETS = {
    "bull_strong": 0.00,
    "bull":        0.05,
    "balanced":    0.15,
    "bear":        0.50,
    "regime_turn": 1.00,
}


# --- Dataclasses -----------------------------------------------------------

@dataclass
class SizedOrder:
    """Complete order specification."""
    ticker: str
    target_dollars: float
    target_shares: float
    target_weight_pct: float
    entry_price: float
    stop_price: float
    risk_dollars: float
    risk_pct_of_capital: float
    phase: str
    phase_multiplier: float
    base_weight: float
    was_capped: bool = False         # hit volatility or hard cap
    rationale: str = ""


@dataclass
class SizingPlan:
    """Full plan - orders + diversification meta."""
    capital_usd: float
    regime: str
    cash_target_pct: float
    investable_dollars: float
    orders: list[SizedOrder] = field(default_factory=list)
    total_invested_dollars: float = 0.0
    total_invested_pct: float = 0.0
    summary: str = ""


# --- Helpers ---------------------------------------------------------------

def _base_weight_from_score(score: float) -> float:
    """Step function: score tier -> base weight."""
    for threshold in sorted(SCORE_TIER_BASE_WEIGHT.keys(), reverse=True):
        if score >= threshold:
            return SCORE_TIER_BASE_WEIGHT[threshold]
    return 0.0


def _volatility_cap(
    capital: float,
    stop_distance_pct: float,
    risk_budget_pct: float = RISK_BUDGET_PCT,
) -> float:
    """Max position $ such that loss-to-stop = risk_budget of capital."""
    if stop_distance_pct <= 0:
        return capital * MAX_POSITION_WEIGHT
    risk_dollars = capital * risk_budget_pct
    max_dollars = risk_dollars / stop_distance_pct
    return min(max_dollars, capital * MAX_POSITION_WEIGHT)


# --- Core sizing -----------------------------------------------------------

def size_single_candidate(
    cand: ScannerCandidate,
    capital_usd: float,
    risk_budget_pct: float = RISK_BUDGET_PCT,
    cfg: Optional[AggressiveConfig] = None,
) -> Optional[SizedOrder]:
    """Compute SizedOrder for one candidate.

    Returns None if:
      - candidate disqualified
      - no trade card
      - trade card status not READY
      - resulting weight below MIN_POSITION_WEIGHT
    """
    if cand.disqualified:
        return None
    if cand.trade_card is None:
        return None
    if cand.trade_card.entry_status != "READY":
        return None

    card = cand.trade_card
    entry_price = (card.buy_zone_low + card.buy_zone_high) / 2.0
    stop_price = card.stop_loss
    stop_distance_pct = (entry_price - stop_price) / entry_price
    if stop_distance_pct <= 0:
        return None

    # Base weight from score
    base_weight = _base_weight_from_score(cand.final_score)
    if base_weight == 0.0:
        return None

    # Phase adjustment
    phase_mult = PHASE_ADJUSTMENT.get(cand.theme_phase, 0.90)
    adjusted_weight = base_weight * phase_mult

    # Apply caps
    notional_by_weight = capital_usd * adjusted_weight
    notional_by_vol = _volatility_cap(capital_usd, stop_distance_pct, risk_budget_pct)
    notional = min(notional_by_weight, notional_by_vol)
    was_capped = notional_by_vol < notional_by_weight

    # Min position check
    final_weight = notional / capital_usd
    if final_weight < MIN_POSITION_WEIGHT:
        return None

    shares = notional / entry_price
    risk_dollars = shares * (entry_price - stop_price)

    rationale = (
        f"score={cand.final_score:.0f} -> base={base_weight*100:.0f}% "
        f"x phase_mult({cand.theme_phase})={phase_mult:.2f} "
        f"= {adjusted_weight*100:.0f}% target"
    )
    if was_capped:
        rationale += f" | capped by vol (stop {stop_distance_pct*100:.1f}%)"
    rationale += f" | final {final_weight*100:.1f}% = ${notional:,.0f}"

    return SizedOrder(
        ticker=cand.ticker,
        target_dollars=notional,
        target_shares=shares,
        target_weight_pct=final_weight,
        entry_price=entry_price,
        stop_price=stop_price,
        risk_dollars=risk_dollars,
        risk_pct_of_capital=risk_dollars / capital_usd,
        phase=cand.theme_phase,
        phase_multiplier=phase_mult,
        base_weight=base_weight,
        was_capped=was_capped,
        rationale=rationale,
    )


def build_sizing_plan(
    candidates: list[ScannerCandidate],
    capital_usd: float,
    regime: str = "balanced",
    max_positions: int = MAX_CONCENTRATED_POSITIONS,
    risk_budget_pct: float = RISK_BUDGET_PCT,
) -> SizingPlan:
    """Build complete sizing plan from scanner candidates.

    Algorithm:
      1. Apply regime cash target to get investable capital
      2. Sort candidates by final_score descending
      3. Size each until max_positions filled
      4. Total check: if sum > investable, scale down proportionally
    """
    cash_target = REGIME_CASH_TARGETS.get(regime, 0.15)
    investable = capital_usd * (1.0 - cash_target)

    # Sort descending by final_score (already sorted from scanner, but be safe)
    ranked = sorted(candidates, key=lambda c: c.final_score, reverse=True)

    orders: list[SizedOrder] = []
    for cand in ranked:
        if len(orders) >= max_positions:
            break
        order = size_single_candidate(
            cand, capital_usd, risk_budget_pct=risk_budget_pct
        )
        if order:
            orders.append(order)

    # Global check: if sum > investable, pro-rata scale down
    total_notional = sum(o.target_dollars for o in orders)
    if total_notional > investable and orders:
        scale = investable / total_notional
        for o in orders:
            o.target_dollars *= scale
            o.target_shares = o.target_dollars / o.entry_price
            o.target_weight_pct = o.target_dollars / capital_usd
            o.risk_dollars = o.target_shares * (o.entry_price - o.stop_price)
            o.risk_pct_of_capital = o.risk_dollars / capital_usd
            o.rationale += f" | pro-rata scaled {scale:.2f}"
        total_notional = sum(o.target_dollars for o in orders)

    summary = (
        f"regime={regime} cash_tgt={cash_target*100:.0f}% "
        f"positions={len(orders)}/{max_positions} "
        f"invested=${total_notional:,.0f} "
        f"({total_notional/capital_usd*100:.1f}% of ${capital_usd:,.0f})"
    )

    return SizingPlan(
        capital_usd=capital_usd,
        regime=regime,
        cash_target_pct=cash_target,
        investable_dollars=investable,
        orders=orders,
        total_invested_dollars=total_notional,
        total_invested_pct=total_notional / capital_usd if capital_usd else 0.0,
        summary=summary,
    )


# --- Display ---------------------------------------------------------------

def format_plan(plan: SizingPlan) -> str:
    lines = [
        "=" * 78,
        f"SIZING PLAN",
        "=" * 78,
        f"Capital:        ${plan.capital_usd:,.0f}",
        f"Regime:         {plan.regime}  (cash target {plan.cash_target_pct*100:.0f}%)",
        f"Investable:     ${plan.investable_dollars:,.0f}",
        f"Orders:         {len(plan.orders)}",
        f"Total invested: ${plan.total_invested_dollars:,.0f} "
        f"({plan.total_invested_pct*100:.1f}%)",
        "",
    ]
    if plan.orders:
        lines.append(
            f"{'Ticker':<6} {'$Target':>10} {'Shares':>8} {'Weight':>7} "
            f"{'Entry':>8} {'Stop':>8} {'Risk$':>8} {'Phase':<9}"
        )
        lines.append("-" * 78)
        for o in plan.orders:
            lines.append(
                f"{o.ticker:<6} ${o.target_dollars:>9,.0f} "
                f"{o.target_shares:>8.2f} {o.target_weight_pct*100:>6.1f}% "
                f"${o.entry_price:>7.2f} ${o.stop_price:>7.2f} "
                f"${o.risk_dollars:>7,.0f} {o.phase:<9}"
            )
        lines.append("")
        lines.append("Rationale:")
        for o in plan.orders:
            lines.append(f"  {o.ticker}: {o.rationale}")
    else:
        lines.append("(no qualifying orders)")
    return "\n".join(lines)


# --- Smoke test ------------------------------------------------------------

if __name__ == "__main__":
    from aggressive.scanner import scan

    print("=" * 78)
    print("Position Sizing - Smoke Test")
    print("=" * 78)

    candidates = scan(
        universe_source="themes",          # use themes.yaml for quick smoke
        min_tech_score=60,
        top_n=20,
        verbose=True,
    )

    # Test multiple regimes
    for regime in ["bull", "balanced", "bear"]:
        print(f"\n--- Regime: {regime.upper()} ---")
        plan = build_sizing_plan(
            candidates,
            capital_usd=100_000.0,
            regime=regime,
            max_positions=3,
        )
        print(format_plan(plan))

    print()
    print("PASS")
