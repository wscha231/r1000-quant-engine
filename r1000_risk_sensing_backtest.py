"""r1000_risk_sensing_backtest - Backtest the unified risk-sensing system.

Apply 4-layer risk-sensing rules to historical equity_curve data and measure
the improvement: does Sharpe go up? Does MaxDD shrink?

Methodology:
  1. Start with the production equity_curve.csv (84 months, jeongseok v1)
     OR concentrated_strategy_monthly.csv (target_n=3 champion, 83 months)
  2. Simulate rolling drawdown circuit breaker (Layer 2)
  3. Compare: original vs risk-sensed
     - CAGR (small expected drop)
     - Sharpe (expected up)
     - MaxDD (expected smaller in magnitude)
     - Calmar (expected significant up)

This is a SIMPLIFIED Layer 2 only test. Layers 1, 3, 4 require per-position
state which the equity_curve doesn't have. Full backtest = future work
(needs portfolio_holdings_history.parquet replay).

Output: outputs/strategy_backtest/risk_sensing_compare.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))

from r1000_risk_sensing import RiskConfig


def cagr(rets: np.ndarray) -> float:
    if len(rets) == 0:
        return float("nan")
    eq = (1.0 + rets).cumprod()
    years = len(rets) / 12.0
    return float(eq[-1] ** (1.0 / years) - 1.0) if years > 0 else float("nan")


def sharpe(rets: np.ndarray) -> float:
    if len(rets) == 0 or rets.std() == 0:
        return 0.0
    return float((rets.mean() * 12) / (rets.std() * np.sqrt(12)))


def max_dd(rets: np.ndarray) -> float:
    if len(rets) == 0:
        return 0.0
    eq = (1.0 + rets).cumprod()
    peak = np.maximum.accumulate(eq)
    return float((eq / peak - 1.0).min())


def apply_dd_circuit_breaker(
    rets: np.ndarray, bench: np.ndarray, cfg: RiskConfig,
) -> np.ndarray:
    """Apply Layer 2 (DD circuit breaker) to historical returns.

    At each month-start, compute trailing portfolio DD. If DD breaches threshold,
    reduce strategy exposure to (1 - cash_target). Cash earns 0% (conservative).
    Once DD recovers above -10%, restore full exposure next month.

    Returns: adjusted monthly returns.
    """
    out = np.zeros_like(rets, dtype=float)
    eq = 1.0
    peak = 1.0
    cash_weight = 0.0  # current cash buffer

    for i, r in enumerate(rets):
        # Adjusted return = (1 - cash_weight) * strategy_return + cash_weight * 0
        adj_r = (1.0 - cash_weight) * r
        out[i] = adj_r

        # Update equity
        eq *= (1.0 + adj_r)
        peak = max(peak, eq)
        dd = eq / peak - 1.0

        # Decide cash for NEXT month based on current DD
        if dd <= cfg.dd_level3_threshold:
            cash_weight = cfg.dd_level3_cash
        elif dd <= cfg.dd_level2_threshold:
            cash_weight = cfg.dd_level2_cash
        elif dd <= cfg.dd_level1_threshold:
            cash_weight = cfg.dd_level1_cash
        elif dd > -0.05:  # Recovered above -5%, restore full exposure
            cash_weight = 0.0
        # else hold current cash_weight (between -10% and -5% = neutral zone)

    return out


def simulate_strategy(name: str, rets: np.ndarray, bench: np.ndarray,
                     cfg: RiskConfig, label: str = "") -> dict:
    """Compute metrics for a return series."""
    return {
        "name": name + (f" ({label})" if label else ""),
        "n_months": int(len(rets)),
        "cagr_pct": float(cagr(rets) * 100),
        "sharpe": float(sharpe(rets)),
        "max_dd_pct": float(max_dd(rets) * 100),
        "calmar": float(cagr(rets) / abs(max_dd(rets))) if max_dd(rets) < 0 else float("nan"),
        "vol_ann_pct": float(rets.std() * np.sqrt(12) * 100),
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--equity-curve",
        default=r"G:/내 드라이브/r1000_top30_institutional/outputs/equity_curve.csv",
        help="path to production equity_curve.csv (jeongseok v1)",
    )
    p.add_argument(
        "--concentrated-monthly",
        default=r"G:/내 드라이브/r1000_top30_institutional/outputs/reports/concentrated_strategy_monthly.csv",
        help="path to concentrated_strategy_monthly.csv (champion config)",
    )
    p.add_argument(
        "--output",
        default="outputs/strategy_backtest/risk_sensing_compare.json",
    )
    args = p.parse_args()

    cfg = RiskConfig()
    print("=" * 70)
    print("Risk Sensing Backtest (Layer 2: DD circuit breaker)")
    print("=" * 70)
    print(f"\nDD thresholds:")
    print(f"  Level 1: {cfg.dd_level1_threshold*100:.0f}% -> {cfg.dd_level1_cash*100:.0f}% cash")
    print(f"  Level 2: {cfg.dd_level2_threshold*100:.0f}% -> {cfg.dd_level2_cash*100:.0f}% cash")
    print(f"  Level 3: {cfg.dd_level3_threshold*100:.0f}% -> {cfg.dd_level3_cash*100:.0f}% cash")

    results = {}

    # === Jeongseok v1 ===
    ec = pd.read_csv(args.equity_curve)
    ec["rebalance_date"] = pd.to_datetime(ec["rebalance_date"])
    ec = ec.sort_values("rebalance_date").drop_duplicates("rebalance_date")
    js_rets = ec["net_return"].values.astype(float)
    js_bench = ec["bench_return"].values.astype(float)

    js_orig = simulate_strategy("jeongseok_v1", js_rets, js_bench, cfg, "original")
    js_rs_rets = apply_dd_circuit_breaker(js_rets, js_bench, cfg)
    js_rs = simulate_strategy("jeongseok_v1", js_rs_rets, js_bench, cfg, "+ risk sensing L2")

    results["jeongseok_v1"] = {"original": js_orig, "with_risk_sensing": js_rs}

    print("\n" + "=" * 70)
    print("정석 v1 (12-20 names, 83 months)")
    print("=" * 70)
    print(f"  {'Metric':<14} {'Original':>12} {'+ Risk L2':>12} {'Delta':>10}")
    for k in ["cagr_pct", "sharpe", "max_dd_pct", "calmar", "vol_ann_pct"]:
        v0 = js_orig[k]
        v1 = js_rs[k]
        d = v1 - v0
        sign = "+" if d > 0 else ""
        print(f"  {k:<14} {v0:>12.2f} {v1:>12.2f} {sign}{d:>9.2f}")

    # === Concentrated 3-name ===
    cm = pd.read_csv(args.concentrated_monthly)
    cm = cm[
        (cm["target_n"] == 3)
        & (cm["weighting_mode"] == "score_power")
        & (cm["active_rebalance_interval_months"] == 1)
    ].copy()
    cm = cm.sort_values("rebalance_date").drop_duplicates("rebalance_date")
    co_rets = cm["net_return"].values.astype(float)
    co_bench = cm["bench_return"].values.astype(float)

    co_orig = simulate_strategy("concentrated_3", co_rets, co_bench, cfg, "original")
    co_rs_rets = apply_dd_circuit_breaker(co_rets, co_bench, cfg)
    co_rs = simulate_strategy("concentrated_3", co_rs_rets, co_bench, cfg, "+ risk sensing L2")

    results["concentrated_3"] = {"original": co_orig, "with_risk_sensing": co_rs}

    print("\n" + "=" * 70)
    print("Concentrated 3-name (83 months)")
    print("=" * 70)
    print(f"  {'Metric':<14} {'Original':>12} {'+ Risk L2':>12} {'Delta':>10}")
    for k in ["cagr_pct", "sharpe", "max_dd_pct", "calmar", "vol_ann_pct"]:
        v0 = co_orig[k]
        v1 = co_rs[k]
        d = v1 - v0
        sign = "+" if d > 0 else ""
        print(f"  {k:<14} {v0:>12.2f} {v1:>12.2f} {sign}{d:>9.2f}")

    # === Save ===
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    print(f"\n[save] {args.output}")

    print("\n" + "=" * 70)
    print("Summary: '손실은 작게, 익절은 크게' validation")
    print("=" * 70)
    print(f"  jeongseok v1: MaxDD {js_orig['max_dd_pct']:.1f}% -> {js_rs['max_dd_pct']:.1f}%, "
          f"Sharpe {js_orig['sharpe']:.2f} -> {js_rs['sharpe']:.2f}")
    print(f"  concentrated: MaxDD {co_orig['max_dd_pct']:.1f}% -> {co_rs['max_dd_pct']:.1f}%, "
          f"Sharpe {co_orig['sharpe']:.2f} -> {co_rs['sharpe']:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
