"""r1000_per_position_replay - Per-position L1 risk-sensing backtest.

User mandate: validate that Layer 1 stops (O'Neil -8%, trailing -15%, RS break)
actually improve risk-adjusted returns. Layer 2 alone (DD breaker) was shown
not enough; need per-position simulation.

Method:
  For each historical holding period (rebalance_date, ticker, weight):
    1. Load daily prices from production cache (cache_prices/<sha1>.parquet)
    2. Walk day-by-day from entry to next rebalance:
       - Track peak price since entry
       - If price drops -15% from peak → exit at that day's close
       - If price drops -8% within first 30 days → exit (O'Neil hard)
    3. Compute adjusted return: (exit_price - entry_price) / entry_price
       If exit early, remaining days earn 0 (cash)
  Aggregate weighted into monthly portfolio return.
  Compare original (no stops) vs L1-stopped (with stops).

Targets:
  - jeongseok v1 (production holdings_history): test on real 84mo
  - concentrated 3-name (concentrated_strategy_holdings): test on 83mo

Output: outputs/strategy_backtest/per_position_replay.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))

from r1000_risk_sensing import RiskConfig


PRICE_CACHE_DIR = Path(r"G:/내 드라이브/r1000_top30_institutional/cache_prices")


def px_cache_path(ticker: str) -> Path:
    h = hashlib.sha1(ticker.encode("utf-8")).hexdigest()[:16]
    return PRICE_CACHE_DIR / f"{h}.parquet"


def load_bars(ticker: str) -> pd.DataFrame | None:
    p = px_cache_path(ticker)
    if not p.exists():
        return None
    try:
        df = pd.read_parquet(p)
    except Exception:
        return None
    df.index = pd.to_datetime(df.index).tz_localize(None)
    if "Open" not in df.columns or "Close" not in df.columns:
        return None
    return df.sort_index()


def adjusted_open_close(hist: pd.DataFrame) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Return (adj_open, adj_close, adj_low) split-adjusted."""
    o = pd.to_numeric(hist["Open"], errors="coerce").astype(float)
    c = pd.to_numeric(hist["Close"], errors="coerce").astype(float)
    low = pd.to_numeric(hist.get("Low", c), errors="coerce").astype(float)
    if "Adj Close" in hist.columns:
        adj_close = pd.to_numeric(hist["Adj Close"], errors="coerce").astype(float)
        factor = adj_close / c.replace(0, np.nan)
    else:
        adj_close = c
        factor = pd.Series(1.0, index=o.index)
    return (o * factor).fillna(method="ffill"), adj_close.fillna(method="ffill"), (low * factor).fillna(method="ffill")


def simulate_position(
    ticker: str,
    entry_date: pd.Timestamp,
    exit_date: pd.Timestamp,
    cfg: RiskConfig,
    bars: pd.DataFrame | None = None,
) -> dict:
    """Simulate one position with L1 stops applied.

    Returns:
      {
        "ticker": str,
        "entry_date", "exit_date_actual",
        "entry_price", "exit_price",
        "ret_original": forward open-to-open return (no stop),
        "ret_with_l1": return with L1 stops applied,
        "stop_triggered": str | None,
        "days_held_actual": int,
      }
    """
    if bars is None:
        bars = load_bars(ticker)
    if bars is None or bars.empty:
        return None
    op, cl, low = adjusted_open_close(bars)

    # Get entry price = next trading day's open after entry_date
    entry_idx = op.index.searchsorted(entry_date, side="left")
    if entry_idx >= len(op):
        return None
    entry_actual = op.index[entry_idx]
    entry_price = float(op.iloc[entry_idx])
    if entry_price <= 0 or not np.isfinite(entry_price):
        return None

    # Get original exit price (no stops) at exit_date open
    exit_idx_orig = op.index.searchsorted(exit_date, side="left")
    if exit_idx_orig >= len(op):
        exit_idx_orig = len(op) - 1
    exit_price_orig = float(op.iloc[exit_idx_orig])
    ret_original = exit_price_orig / entry_price - 1.0

    # Walk day-by-day from entry to exit, applying L1 stops
    walk = cl.iloc[entry_idx:exit_idx_orig + 1]
    walk_low = low.iloc[entry_idx:exit_idx_orig + 1]

    peak = entry_price
    stop_triggered = None
    exit_price = exit_price_orig
    exit_date_actual = op.index[exit_idx_orig]
    days_held = 0

    for i, dt in enumerate(walk.index):
        days_held = i
        c_today = float(walk.iloc[i])
        l_today = float(walk_low.iloc[i])
        peak = max(peak, c_today)

        # 1a: O'Neil hard stop within first 30d
        if days_held <= cfg.oneill_grace_days:
            ret_from_entry = l_today / entry_price - 1.0
            if ret_from_entry <= cfg.oneill_hard_stop_pct:
                stop_triggered = "oneill_hard_stop"
                # Assume fill at the threshold price (conservative)
                exit_price = entry_price * (1.0 + cfg.oneill_hard_stop_pct)
                exit_date_actual = dt
                break

        # 1b: Trailing stop from peak
        if peak > 0:
            dd_from_peak = l_today / peak - 1.0
            if dd_from_peak <= cfg.trailing_stop_pct:
                stop_triggered = "trailing_stop"
                # Assume fill at trailing threshold price
                exit_price = peak * (1.0 + cfg.trailing_stop_pct)
                exit_date_actual = dt
                break

    ret_with_l1 = exit_price / entry_price - 1.0

    return {
        "ticker": ticker,
        "entry_date": str(entry_actual.date()),
        "exit_date_actual": str(exit_date_actual.date()),
        "exit_date_orig": str(op.index[exit_idx_orig].date()),
        "entry_price": entry_price,
        "exit_price_orig": exit_price_orig,
        "exit_price_actual": exit_price,
        "ret_original": ret_original,
        "ret_with_l1": ret_with_l1,
        "stop_triggered": stop_triggered,
        "days_held_actual": days_held,
        "days_held_orig": int(exit_idx_orig - entry_idx),
    }


def replay_holdings(
    holdings_df: pd.DataFrame,
    cfg: RiskConfig,
    verbose: bool = True,
) -> pd.DataFrame:
    """Replay all holdings with L1 stops. Returns row-by-row results."""
    holdings_df = holdings_df.copy()
    holdings_df["rebalance_date"] = pd.to_datetime(holdings_df["rebalance_date"])
    rebal_dates = sorted(holdings_df["rebalance_date"].unique())

    results = []
    bars_cache = {}
    n_total = len(holdings_df)
    for i, row in enumerate(holdings_df.itertuples(index=False), 1):
        if verbose and i % 100 == 0:
            print(f"  {i}/{n_total}...")
        ticker = str(row.ticker).upper()
        entry_dt = pd.Timestamp(row.rebalance_date)
        # Find next rebalance for this ticker
        future = [d for d in rebal_dates if d > entry_dt]
        exit_dt = future[0] if future else entry_dt + pd.Timedelta(days=30)

        # Cache bars
        if ticker not in bars_cache:
            bars_cache[ticker] = load_bars(ticker)
        bars = bars_cache[ticker]

        sim = simulate_position(ticker, entry_dt, exit_dt, cfg, bars)
        if sim is None:
            continue

        sim["rebalance_date"] = str(entry_dt.date())
        sim["weight"] = float(row.weight)
        results.append(sim)

    return pd.DataFrame(results)


def aggregate_monthly(positions: pd.DataFrame, cost_per_side_bps: float = 25.0) -> pd.DataFrame:
    """Aggregate per-position results into monthly portfolio returns."""
    cost = cost_per_side_bps / 10000  # one-side
    rt_cost = cost * 2  # roundtrip

    rows = []
    for date, grp in positions.groupby("rebalance_date"):
        wsum = grp["weight"].sum()
        if wsum <= 0:
            continue
        # Weighted returns
        wret_orig = (grp["weight"] * grp["ret_original"]).sum()
        wret_l1 = (grp["weight"] * grp["ret_with_l1"]).sum()
        # Cost: assume monthly rebalance turnover ~1.0
        net_orig = wret_orig - rt_cost
        net_l1 = wret_l1 - rt_cost
        # Stop count
        n_stops = (grp["stop_triggered"].notna()).sum()
        rows.append({
            "rebalance_date": date,
            "n_positions": len(grp),
            "n_stops": int(n_stops),
            "weight_sum": float(wsum),
            "ret_original": float(wret_orig),
            "ret_with_l1": float(wret_l1),
            "net_original": float(net_orig),
            "net_with_l1": float(net_l1),
        })
    return pd.DataFrame(rows).sort_values("rebalance_date")


def metrics(rets: np.ndarray) -> dict:
    if len(rets) == 0:
        return {}
    eq = (1.0 + rets).cumprod()
    n = len(rets)
    years = n / 12.0
    cagr_v = float(eq[-1] ** (1.0 / years) - 1.0) if years > 0 else float("nan")
    sharpe_v = float((rets.mean() * 12) / (rets.std() * np.sqrt(12))) if rets.std() > 0 else 0.0
    dd = eq / np.maximum.accumulate(eq) - 1.0
    mdd = float(dd.min())
    return {
        "cagr_pct": cagr_v * 100,
        "sharpe": sharpe_v,
        "max_dd_pct": mdd * 100,
        "calmar": cagr_v / abs(mdd) if mdd < 0 else float("nan"),
        "vol_ann_pct": float(rets.std() * np.sqrt(12)) * 100,
        "n_months": n,
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--concentrated-holdings",
        default=r"G:/내 드라이브/r1000_top30_institutional/outputs/reports/concentrated_strategy_holdings.csv",
    )
    p.add_argument("--target-n", type=int, default=3)
    p.add_argument("--weighting", default="score_power")
    p.add_argument("--rebal-int", type=int, default=1)
    p.add_argument(
        "--output",
        default="outputs/strategy_backtest/per_position_replay.json",
    )
    args = p.parse_args()

    cfg = RiskConfig()
    print("=" * 70)
    print("Per-Position L1 Replay Backtest")
    print("=" * 70)
    print(f"  oneill_hard_stop:  {cfg.oneill_hard_stop_pct*100:+.0f}% (within {cfg.oneill_grace_days}d)")
    print(f"  trailing_stop:     {cfg.trailing_stop_pct*100:+.0f}% from peak")

    # Load concentrated 3-name holdings
    h = pd.read_csv(args.concentrated_holdings)
    h_sub = h[
        (h["target_n"] == args.target_n)
        & (h["weighting_mode"] == args.weighting)
        & (h["active_rebalance_interval_months"] == args.rebal_int)
    ].copy()
    print(f"\n[load] concentrated holdings: {len(h_sub)} rows "
          f"(target_n={args.target_n}, weighting={args.weighting}, rebal={args.rebal_int}mo)")

    # Replay
    print("\n[replay] simulating per-position L1 stops...")
    pos = replay_holdings(h_sub, cfg)
    print(f"[replay] simulated {len(pos)} positions, "
          f"{(pos['stop_triggered'].notna()).sum()} stops triggered")

    # Stop type breakdown
    stop_counts = pos["stop_triggered"].value_counts(dropna=False)
    print("\nStop type breakdown:")
    for k, v in stop_counts.items():
        print(f"  {str(k):<22} {v}")

    # Aggregate
    monthly = aggregate_monthly(pos)
    print(f"\n[aggregate] {len(monthly)} months")

    # Metrics comparison
    rets_orig = monthly["net_original"].values
    rets_l1 = monthly["net_with_l1"].values

    m_orig = metrics(rets_orig)
    m_l1 = metrics(rets_l1)

    print("\n" + "=" * 70)
    print("Concentrated 3-name: Original (no stops) vs + Layer 1 stops")
    print("=" * 70)
    print(f"  {'Metric':<14} {'Original':>12} {'+ L1 stops':>12} {'Delta':>10}")
    for k in ["cagr_pct", "sharpe", "max_dd_pct", "calmar", "vol_ann_pct"]:
        v0 = m_orig.get(k, float("nan"))
        v1 = m_l1.get(k, float("nan"))
        d = v1 - v0
        sign = "+" if d > 0 else ""
        print(f"  {k:<14} {v0:>12.2f} {v1:>12.2f} {sign}{d:>9.2f}")

    # Per-position summary
    pct_stopped = (pos["stop_triggered"].notna()).mean() * 100
    avg_ret_orig = pos["ret_original"].mean() * 100
    avg_ret_l1 = pos["ret_with_l1"].mean() * 100
    avg_loss_orig = pos[pos["ret_original"] < 0]["ret_original"].mean() * 100
    avg_loss_l1 = pos[pos["ret_with_l1"] < 0]["ret_with_l1"].mean() * 100

    print()
    print(f"Position-level stats (n={len(pos)}):")
    print(f"  Stopped:               {pct_stopped:.1f}%")
    print(f"  Avg position return:   orig={avg_ret_orig:+.2f}% / L1={avg_ret_l1:+.2f}%")
    print(f"  Avg LOSS magnitude:    orig={avg_loss_orig:+.2f}% / L1={avg_loss_l1:+.2f}%")

    # Save
    out = {
        "config": {
            "oneill_hard_stop_pct": cfg.oneill_hard_stop_pct,
            "trailing_stop_pct": cfg.trailing_stop_pct,
            "target_n": args.target_n,
            "weighting": args.weighting,
            "rebal_int": args.rebal_int,
        },
        "n_positions_simulated": int(len(pos)),
        "n_stops_triggered": int((pos["stop_triggered"].notna()).sum()),
        "stop_breakdown": {str(k): int(v) for k, v in stop_counts.items()},
        "concentrated_3": {"original": m_orig, "with_l1_stops": m_l1},
    }
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    print(f"\n[save] {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
