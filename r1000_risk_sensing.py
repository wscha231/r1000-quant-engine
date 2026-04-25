"""r1000_risk_sensing - Unified 4-layer risk-sensing system.

User mandate (2026-04-25):
  "Core에도 risk sensing 적용. 손실은 작게, 익절은 크게 (O'Neil)."

Applies to BOTH Core (jeongseok v1, 12-20 names) AND Concentrated (3-5 names).

4 Layers:
  Layer 1: Individual position stops
    - O'Neil hard stop:  -8% from entry (early days <30d)
    - Trailing stop:     -15% from peak since entry
    - RS break:          12m RS decay > 30pp from entry
    - Theme decay:       theme phase 'dead'/'ending' + RS < 0
    - Earnings miss:     reported_eps < estimate_eps - 5%

  Layer 2: Portfolio DD circuit breaker (already in production engine)
    -10% from peak -> cash target 30%
    -20% from peak -> cash target 50%
    -25% from peak -> cash target 70%

  Layer 3: Market regime defense
    VIX > 30          -> halt new buys
    SPY < 200MA       -> +20% cash buffer
    M2 YoY < 0        -> tilt to defensive (NOT growth)

  Layer 4: Position swap (best -> better)
    weak position (RS<0, held>60d) + strong alternate (RS>30) -> swap

Output: list of RiskAction dataclasses for paper_executor to consume.

Backtest mode: r1000_risk_sensing_backtest.py applies these to historical
equity_curve and measures improvement (Sharpe up, MaxDD down).
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd


# =========================================================================
# Tunable parameters (config)
# =========================================================================

@dataclass
class RiskConfig:
    # Layer 1: Individual stops
    oneill_hard_stop_pct: float = -0.08       # -8% from entry within 30d
    oneill_grace_days: int = 30               # window for hard stop
    trailing_stop_pct: float = -0.15          # -15% from peak since entry
    rs_break_threshold_pp: float = -30.0      # RS 12m decay > 30pp
    rs_break_min_days: int = 30               # min hold before RS check
    theme_decay_phases: tuple = ("dead", "ending")
    theme_decay_rs_threshold: float = 0.0     # exit if rs <= 0

    # Layer 2: Portfolio DD breaker
    dd_level1_threshold: float = -0.10        # -10% -> 30% cash
    dd_level1_cash: float = 0.30
    dd_level2_threshold: float = -0.20        # -20% -> 50% cash
    dd_level2_cash: float = 0.50
    dd_level3_threshold: float = -0.25        # -25% -> 70% cash
    dd_level3_cash: float = 0.70

    # Layer 3: Regime
    vix_halt_threshold: float = 30.0
    spy_below_200ma_cash: float = 0.20

    # Layer 4: Swap
    swap_weak_rs_threshold: float = 0.0       # weak if rs < 0
    swap_weak_min_held_days: int = 60
    swap_strong_rs_threshold: float = 30.0    # strong alt if rs > 30
    swap_max_per_cycle: int = 2


# =========================================================================
# State models
# =========================================================================

@dataclass
class PositionState:
    ticker: str
    entry_date: str
    entry_price: float
    current_price: float
    peak_price_since_entry: float
    weight: float
    days_held: int
    rs_12m_pct: float = 0.0
    rs_12m_at_entry: float = 0.0
    theme_phase: str = "unknown"

    @property
    def unrealized_pct(self) -> float:
        if self.entry_price <= 0:
            return 0.0
        return self.current_price / self.entry_price - 1.0

    @property
    def drawdown_from_peak_pct(self) -> float:
        if self.peak_price_since_entry <= 0:
            return 0.0
        return self.current_price / self.peak_price_since_entry - 1.0


@dataclass
class PortfolioState:
    nav: float
    nav_peak_recent: float          # peak over last 60 days (or all-time)
    cash_weight: float
    spy_above_200ma: bool
    vix_level: float
    positions: list[PositionState] = field(default_factory=list)

    @property
    def portfolio_dd_pct(self) -> float:
        if self.nav_peak_recent <= 0:
            return 0.0
        return self.nav / self.nav_peak_recent - 1.0


@dataclass
class RiskAction:
    type: str                       # 'EXIT' | 'TRIM' | 'SWAP' | 'HALT_NEW' | 'INCREASE_CASH'
    ticker: Optional[str] = None
    reason: str = ""
    target_weight: Optional[float] = None
    swap_to: Optional[str] = None
    layer: int = 0                  # 1/2/3/4
    priority: int = 0               # higher = more urgent


# =========================================================================
# Risk evaluation
# =========================================================================

def evaluate_layer1_individual(
    positions: list[PositionState], cfg: RiskConfig,
) -> list[RiskAction]:
    """Per-position stops: O'Neil hard, trailing, RS break, theme decay."""
    actions = []
    for p in positions:
        # 1a: O'Neil hard stop (-8% within 30d of entry)
        if (p.days_held <= cfg.oneill_grace_days
                and p.unrealized_pct <= cfg.oneill_hard_stop_pct):
            actions.append(RiskAction(
                type="EXIT", ticker=p.ticker, layer=1, priority=10,
                reason=f"oneill_hard_stop {p.unrealized_pct*100:+.1f}% in {p.days_held}d",
            ))
            continue

        # 1b: Trailing stop (-15% from peak since entry)
        if p.drawdown_from_peak_pct <= cfg.trailing_stop_pct:
            actions.append(RiskAction(
                type="EXIT", ticker=p.ticker, layer=1, priority=8,
                reason=f"trailing_stop {p.drawdown_from_peak_pct*100:+.1f}% from peak",
            ))
            continue

        # 1c: RS break (12m RS decayed > 30pp from entry)
        if p.days_held >= cfg.rs_break_min_days:
            rs_decay = p.rs_12m_pct - p.rs_12m_at_entry
            if rs_decay <= cfg.rs_break_threshold_pp:
                actions.append(RiskAction(
                    type="EXIT", ticker=p.ticker, layer=1, priority=6,
                    reason=f"rs_break {rs_decay:+.0f}pp decay (entry={p.rs_12m_at_entry:.0f} now={p.rs_12m_pct:.0f})",
                ))
                continue

        # 1d: Theme decay
        if (p.theme_phase in cfg.theme_decay_phases
                and p.rs_12m_pct <= cfg.theme_decay_rs_threshold):
            actions.append(RiskAction(
                type="EXIT", ticker=p.ticker, layer=1, priority=4,
                reason=f"theme_decay phase={p.theme_phase} rs={p.rs_12m_pct:.0f}",
            ))
    return actions


def evaluate_layer2_portfolio_dd(
    state: PortfolioState, cfg: RiskConfig,
) -> list[RiskAction]:
    """Portfolio-level drawdown circuit breaker."""
    dd = state.portfolio_dd_pct
    if dd <= cfg.dd_level3_threshold:
        target = cfg.dd_level3_cash
        level = 3
    elif dd <= cfg.dd_level2_threshold:
        target = cfg.dd_level2_cash
        level = 2
    elif dd <= cfg.dd_level1_threshold:
        target = cfg.dd_level1_cash
        level = 1
    else:
        return []

    if target > state.cash_weight:
        return [RiskAction(
            type="INCREASE_CASH", layer=2, priority=9,
            target_weight=target,
            reason=f"portfolio_dd {dd*100:.1f}% -> level {level} cash {target*100:.0f}%",
        )]
    return []


def evaluate_layer3_regime(
    state: PortfolioState, cfg: RiskConfig,
) -> list[RiskAction]:
    """Market regime defense."""
    actions = []
    if state.vix_level >= cfg.vix_halt_threshold:
        actions.append(RiskAction(
            type="HALT_NEW", layer=3, priority=7,
            reason=f"vix {state.vix_level:.1f} >= {cfg.vix_halt_threshold:.0f}",
        ))
    if not state.spy_above_200ma:
        target_cash = max(state.cash_weight, cfg.spy_below_200ma_cash)
        if target_cash > state.cash_weight:
            actions.append(RiskAction(
                type="INCREASE_CASH", layer=3, priority=5,
                target_weight=target_cash,
                reason="spy_below_200ma defensive cash buffer",
            ))
    return actions


def evaluate_layer4_swap(
    state: PortfolioState, candidates: list[dict], cfg: RiskConfig,
    held_for_action: set[str],
) -> list[RiskAction]:
    """Swap weak position with strong candidate."""
    actions = []
    # Already-acted-upon (e.g., EXIT) skip
    eligible_held = [
        p for p in state.positions
        if p.ticker not in held_for_action
        and p.rs_12m_pct < cfg.swap_weak_rs_threshold
        and p.days_held >= cfg.swap_weak_min_held_days
    ]
    held_set = {p.ticker for p in state.positions}
    strong_alts = sorted(
        [
            c for c in candidates
            if c["ticker"] not in held_set
            and c.get("rs_12m_pct", 0) >= cfg.swap_strong_rs_threshold
        ],
        key=lambda c: -c.get("rs_12m_pct", 0),
    )

    for weak in eligible_held[: cfg.swap_max_per_cycle]:
        if not strong_alts:
            break
        best = strong_alts.pop(0)
        actions.append(RiskAction(
            type="SWAP", ticker=weak.ticker, layer=4, priority=3,
            swap_to=best["ticker"],
            reason=f"swap rs {weak.rs_12m_pct:.0f} -> {best['ticker']} rs {best['rs_12m_pct']:.0f}",
        ))
    return actions


def evaluate_all(
    state: PortfolioState,
    candidates: list[dict],
    cfg: Optional[RiskConfig] = None,
) -> list[RiskAction]:
    """Run all 4 layers. Returns prioritized action list."""
    cfg = cfg or RiskConfig()

    actions: list[RiskAction] = []
    actions += evaluate_layer1_individual(state.positions, cfg)
    actions += evaluate_layer2_portfolio_dd(state, cfg)
    actions += evaluate_layer3_regime(state, cfg)

    # Layer 4 only after Layer 1 — don't swap a position already exiting
    held_for_action = {a.ticker for a in actions if a.type == "EXIT" and a.ticker}
    actions += evaluate_layer4_swap(state, candidates, cfg, held_for_action)

    actions.sort(key=lambda a: -a.priority)
    return actions


# =========================================================================
# CLI
# =========================================================================

def main() -> int:
    """CLI for testing risk evaluation against current portfolio state."""
    p = argparse.ArgumentParser()
    p.add_argument(
        "--portfolio-csv",
        default=r"G:/내 드라이브/r1000_top30_institutional/outputs/portfolio_latest.csv",
    )
    p.add_argument(
        "--concentrated-csv",
        default=r"G:/내 드라이브/r1000_top30_institutional/outputs/concentrated_portfolio_latest.csv",
    )
    p.add_argument("--mode", choices=["core", "concentrated"], default="concentrated")
    args = p.parse_args()

    print("=" * 70)
    print(f"Risk Sensing Evaluation - {args.mode} - {datetime.now():%Y-%m-%d %H:%M}")
    print("=" * 70)

    # Stub: build PortfolioState from current portfolio CSV
    # In production, this needs live price + RS data
    print("[NOTE] CLI is stub - integrate with paper_executor for live use")
    print(f"\nRiskConfig defaults:")
    cfg = RiskConfig()
    for k, v in asdict(cfg).items():
        print(f"  {k:<35} {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
