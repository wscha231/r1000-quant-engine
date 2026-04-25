"""r1000_bootstrap_ci - Bootstrap confidence intervals for backtest CAGR/Sharpe.

User concern (2026-04-25):
  "33% CAGR이 진짜인가? 단일 측정 신뢰 못함."

Method:
  Block bootstrap (3-month blocks, preserves autocorrelation) on the 84 monthly
  net returns. 10,000 resamples -> 95% CI for CAGR, Sharpe, MaxDD.

This is the proper way to assess robustness of a single walk-forward run:
  - Original 33% CAGR could be lucky vs unlucky monthly sequence
  - Bootstrap CI tells us "if we re-ran with similar regime distribution,
    what range would CAGR fall in 95% of the time"

Output:
  outputs/strategy_backtest/bootstrap_ci.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd


def cagr_from_returns(rets: np.ndarray) -> float:
    """Compute annualized CAGR from monthly net returns."""
    eq = (1.0 + rets).cumprod()
    n = len(rets)
    years = n / 12.0
    if years <= 0 or eq[-1] <= 0:
        return float("nan")
    return float(eq[-1] ** (1.0 / years) - 1.0)


def sharpe_from_returns(rets: np.ndarray) -> float:
    if rets.std() == 0:
        return 0.0
    return float((rets.mean() * 12) / (rets.std() * np.sqrt(12)))


def max_dd_from_returns(rets: np.ndarray) -> float:
    eq = (1.0 + rets).cumprod()
    peak = np.maximum.accumulate(eq)
    dd = eq / peak - 1.0
    return float(dd.min())


def block_bootstrap_resample(
    rets: np.ndarray, block_size: int, rng: np.random.Generator,
) -> np.ndarray:
    """Sample with replacement of contiguous blocks of `block_size` months."""
    n = len(rets)
    n_blocks = int(np.ceil(n / block_size))
    out = []
    for _ in range(n_blocks):
        start = rng.integers(0, n - block_size + 1)
        out.append(rets[start:start + block_size])
    return np.concatenate(out)[:n]


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--monthly-csv",
        default=r"G:/내 드라이브/r1000_top30_institutional/outputs/reports/concentrated_strategy_monthly.csv",
    )
    p.add_argument("--target-n", type=int, default=3,
                   help="filter to target_stock_names=N (default: 3 = champion)")
    p.add_argument("--weighting", default="score_power",
                   help="filter to weighting_mode (default: score_power)")
    p.add_argument("--rebalance-int", type=int, default=1,
                   help="filter to active_rebalance_interval_months (default: 1)")
    p.add_argument("--n-bootstrap", type=int, default=10000)
    p.add_argument("--block-size", type=int, default=3,
                   help="bootstrap block size in months (3 preserves autocorr)")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--output",
                   default="outputs/strategy_backtest/bootstrap_ci.json")
    args = p.parse_args()

    print("=" * 70)
    print("Bootstrap CI for backtest metrics")
    print("=" * 70)

    monthly = pd.read_csv(args.monthly_csv)
    print(f"[load] {len(monthly)} rows total")

    # Filter to the champion config
    f = monthly[
        (monthly["target_n"] == args.target_n)
        & (monthly["weighting_mode"] == args.weighting)
        & (monthly["active_rebalance_interval_months"] == args.rebalance_int)
    ].copy()
    f = f.sort_values("rebalance_date").drop_duplicates(subset=["rebalance_date"])
    print(f"[filter] {len(f)} months for target_n={args.target_n}, "
          f"weighting={args.weighting}, rebal={args.rebalance_int}mo")

    if len(f) < 24:
        print(f"FAIL: too few months ({len(f)})")
        return 1

    rets = f["net_return"].values.astype(float)
    bench = f["bench_return"].values.astype(float)

    # Original metrics
    orig_cagr = cagr_from_returns(rets)
    orig_sharpe = sharpe_from_returns(rets)
    orig_mdd = max_dd_from_returns(rets)
    orig_bench_cagr = cagr_from_returns(bench)
    orig_excess = orig_cagr - orig_bench_cagr

    print(f"\n[original metrics over {len(rets)} months]")
    print(f"  Strategy CAGR:  {orig_cagr*100:.2f}%")
    print(f"  Bench CAGR:     {orig_bench_cagr*100:.2f}%")
    print(f"  Excess CAGR:    {orig_excess*100:+.2f}pp")
    print(f"  Sharpe:         {orig_sharpe:.2f}")
    print(f"  Max Drawdown:   {orig_mdd*100:.2f}%")

    # Bootstrap
    print(f"\n[bootstrap] {args.n_bootstrap} block-resamples, block_size={args.block_size}m")
    rng = np.random.default_rng(args.seed)
    boot_cagrs, boot_sharpes, boot_mdds, boot_excesses = [], [], [], []
    for _ in range(args.n_bootstrap):
        idx_resample = block_bootstrap_resample(
            np.arange(len(rets)), args.block_size, rng,
        )
        r_b = rets[idx_resample]
        b_b = bench[idx_resample]
        boot_cagrs.append(cagr_from_returns(r_b))
        boot_sharpes.append(sharpe_from_returns(r_b))
        boot_mdds.append(max_dd_from_returns(r_b))
        boot_excesses.append(cagr_from_returns(r_b) - cagr_from_returns(b_b))

    boot_cagrs = np.array(boot_cagrs)
    boot_sharpes = np.array(boot_sharpes)
    boot_mdds = np.array(boot_mdds)
    boot_excesses = np.array(boot_excesses)

    def ci(x: np.ndarray, level: float = 0.95) -> tuple[float, float]:
        lo = np.percentile(x, (1 - level) / 2 * 100)
        hi = np.percentile(x, (1 - (1 - level) / 2) * 100)
        return float(lo), float(hi)

    cagr_lo, cagr_hi = ci(boot_cagrs)
    sharpe_lo, sharpe_hi = ci(boot_sharpes)
    mdd_lo, mdd_hi = ci(boot_mdds)
    excess_lo, excess_hi = ci(boot_excesses)

    print()
    print("=" * 70)
    print(f"95% CONFIDENCE INTERVALS (bootstrap n={args.n_bootstrap})")
    print("=" * 70)
    print(f"  CAGR:    {orig_cagr*100:.2f}%  CI [{cagr_lo*100:.2f}% .. {cagr_hi*100:.2f}%]")
    print(f"  Excess:  {orig_excess*100:+.2f}pp  CI [{excess_lo*100:+.2f}pp .. {excess_hi*100:+.2f}pp]")
    print(f"  Sharpe:  {orig_sharpe:.2f}  CI [{sharpe_lo:.2f} .. {sharpe_hi:.2f}]")
    print(f"  MaxDD:   {orig_mdd*100:.2f}%  CI [{mdd_hi*100:.2f}% .. {mdd_lo*100:.2f}%]")
    print()
    p_excess_pos = float((boot_excesses > 0).mean())
    p_cagr_above_15 = float((boot_cagrs > 0.15).mean())
    p_cagr_above_20 = float((boot_cagrs > 0.20).mean())
    p_cagr_above_25 = float((boot_cagrs > 0.25).mean())
    print(f"  P(excess > 0):       {p_excess_pos*100:.1f}%")
    print(f"  P(CAGR > 15%):       {p_cagr_above_15*100:.1f}%")
    print(f"  P(CAGR > 20%):       {p_cagr_above_20*100:.1f}%")
    print(f"  P(CAGR > 25%):       {p_cagr_above_25*100:.1f}%")

    out = {
        "config": {
            "target_n": args.target_n,
            "weighting": args.weighting,
            "rebal_interval_mo": args.rebalance_int,
            "n_months": len(rets),
            "n_bootstrap": args.n_bootstrap,
            "block_size_mo": args.block_size,
        },
        "original": {
            "cagr": orig_cagr,
            "bench_cagr": orig_bench_cagr,
            "excess_cagr": orig_excess,
            "sharpe": orig_sharpe,
            "max_dd": orig_mdd,
        },
        "ci_95": {
            "cagr": [cagr_lo, cagr_hi],
            "excess_cagr": [excess_lo, excess_hi],
            "sharpe": [sharpe_lo, sharpe_hi],
            "max_dd": [mdd_lo, mdd_hi],
        },
        "tail_probabilities": {
            "p_excess_positive": p_excess_pos,
            "p_cagr_above_15": p_cagr_above_15,
            "p_cagr_above_20": p_cagr_above_20,
            "p_cagr_above_25": p_cagr_above_25,
        },
    }
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    print(f"\n[save] {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
