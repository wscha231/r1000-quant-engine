"""r1000_strategy_backtester - Walk-forward portfolio backtest comparing strategies.

User mandate (2026-04-25):
  "현재기준 앞으로 오를 종목을 고르는거다 이미 다오른걸 고르는게 아니고
   그렇게 진행하고 있는거지? 이전 평가하는 모델과 비교 백테스트 후 분석."

Compares 5 strategies on the same out-of-sample period (2024-04 to 2026-04):
  A. SPY buy-hold benchmark
  B. Old: top 12 by 정석 model_score (existing baseline)
  C. ML: top 12 by predicted_r3m (LightGBM, our new model)
  D. T5: top 12 turnaround (forward-looking, low-base entries)
  E. Hybrid: ML decile 9 ∩ T5 candidates (combined signals)

Methodology (PIT discipline):
  - Each month-end, strategies pick 12 names using ONLY data available
    up to that date.
  - Hold 1 month at equal weight (1/12 each).
  - Rebalance monthly. Track NAV.
  - Report CAGR, Sharpe, MaxDD, monthly hit rate.

Output:
  outputs/strategy_backtest/strategy_returns.csv
  outputs/strategy_backtest/strategy_summary.csv
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent))

import numpy as np
import pandas as pd

from aggressive.data_alpaca import fetch_daily_bars, fetch_spy_benchmark


# --- Helpers ---------------------------------------------------------------

def get_rebalance_dates(start: str, end: str) -> list[pd.Timestamp]:
    return list(pd.date_range(start, end, freq="ME"))


def fetch_close_at(close_series: pd.Series, date: pd.Timestamp) -> Optional[float]:
    if close_series.empty:
        return None
    idx = close_series.index
    if hasattr(idx, "tz") and idx.tz is not None:
        if pd.Timestamp(date).tzinfo is None:
            date = pd.Timestamp(date).tz_localize(idx.tz)
    pos = idx.searchsorted(date, side="right") - 1
    if pos < 0:
        return None
    return float(close_series.iloc[pos])


def monthly_return_for_basket(
    tickers: list[str],
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
    bar_cache: dict[str, pd.DataFrame],
) -> tuple[float, int]:
    """Equal-weight basket return between start and end. Returns (ret_pct, n_valid)."""
    rets = []
    for t in tickers:
        df = bar_cache.get(t)
        if df is None or df.empty:
            continue
        p_start = fetch_close_at(df["close"], start_date)
        p_end = fetch_close_at(df["close"], end_date)
        if p_start is None or p_end is None or p_start <= 0:
            continue
        rets.append((p_end / p_start - 1.0) * 100.0)
    if not rets:
        return 0.0, 0
    return float(np.mean(rets)), len(rets)


# --- Strategies ------------------------------------------------------------

def strategy_old_model(
    scored_oos: pd.DataFrame, date: pd.Timestamp, top_n: int = 12,
) -> list[str]:
    """Top 12 by 정석 score from scored_oos panel."""
    if "score" not in scored_oos.columns:
        return []
    snap = scored_oos[scored_oos["rebalance_date"] == date]
    if snap.empty:
        # Try nearest available date (within 60 days)
        all_dates = scored_oos["rebalance_date"].unique()
        diffs = [(d, abs((pd.Timestamp(d) - date).days)) for d in all_dates]
        valid = [(d, x) for d, x in diffs if x <= 60]
        if not valid:
            return []
        nearest = min(valid, key=lambda v: v[1])[0]
        snap = scored_oos[scored_oos["rebalance_date"] == nearest]
    snap = snap.dropna(subset=["score"])
    snap = snap[pd.to_numeric(snap["score"], errors="coerce") > 0]
    return snap.nlargest(top_n, "score")["ticker"].tolist()


def strategy_ml_predict(
    feature_store: pd.DataFrame, date: pd.Timestamp, model, features, medians,
    top_n: int = 12,
) -> list[str]:
    """Top 12 by ML predicted r_3m."""
    snap = feature_store[feature_store["rebalance_date"] == date].copy()
    if snap.empty:
        return []
    X = snap[features].copy()
    for c in features:
        X[c] = X[c].fillna(medians.get(c, 0.0))
    preds = model.predict(X.values)
    snap["pred"] = preds
    return snap.nlargest(top_n, "pred")["ticker"].tolist()


def strategy_t5_turnaround(
    universe: list[str], date: pd.Timestamp, bar_cache: dict[str, pd.DataFrame],
    spy_full: pd.DataFrame, top_n: int = 12,
) -> list[str]:
    """Top 12 T5 turnaround scores at this date."""
    from aggressive.signals_technical import tier5_stage_transition
    cutoff = date
    spy_close = spy_full["close"]
    candidates = []
    for t in universe:
        df = bar_cache.get(t)
        if df is None or df.empty:
            continue
        idx = df.index
        if hasattr(idx, "tz") and idx.tz is not None and pd.Timestamp(cutoff).tzinfo is None:
            cutoff_tz = pd.Timestamp(cutoff).tz_localize(idx.tz)
        else:
            cutoff_tz = cutoff
        past = df[df.index <= cutoff_tz]
        if len(past) < 252:
            continue
        try:
            spy_past = spy_full[spy_full.index <= cutoff_tz]
            if len(spy_past) < 252:
                continue
            t5 = tier5_stage_transition(past, spy_past)
            if t5.score > 0:
                candidates.append((t, t5.score))
        except Exception:
            continue
    candidates.sort(key=lambda x: x[1], reverse=True)
    return [t for t, _ in candidates[:top_n]]


# --- Main backtest ---------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--feature-store",
                   default=r"G:/내 드라이브/r1000_top30_institutional/feature_store/feature_store_latest.parquet")
    p.add_argument("--model-dir", default="outputs/discovered_rules/model")
    p.add_argument("--start", default="2019-04-30",
                   help="backtest start (default: 2019-04 = 84-month walk-forward)")
    p.add_argument("--end", default="2026-03-31")
    p.add_argument("--top-n", type=int, default=12)
    p.add_argument("--max-tickers", type=int, default=400,
                   help="universe cap to control runtime (T5 needs all bars)")
    p.add_argument("--bar-days", type=int, default=3000,
                   help="fetch_daily_bars days (default 3000 = 8 years, supports 2019-")
    p.add_argument("--output-dir", default="outputs/strategy_backtest")
    args = p.parse_args()

    print("=" * 75)
    print(f"r1000 Strategy Backtester - {datetime.now():%Y-%m-%d %H:%M}")
    print(f"Period: {args.start} to {args.end}, top_n={args.top_n}")
    print("=" * 75)

    # Load feature store + scored_oos
    df = pd.read_parquet(args.feature_store)
    df["rebalance_date"] = pd.to_datetime(df["rebalance_date"])
    print(f"[load] feature_store: {len(df)} rows")

    scored_oos_path = Path(args.feature_store).parent / "scored_oos_latest.parquet"
    if scored_oos_path.exists():
        scored_oos = pd.read_parquet(scored_oos_path)
        scored_oos["rebalance_date"] = pd.to_datetime(scored_oos["rebalance_date"])
        print(f"[load] scored_oos: {len(scored_oos)} rows")
    else:
        scored_oos = pd.DataFrame()
        print("[load] scored_oos not available - OLD strategy will be empty")

    # Universe: tickers in feature_store
    universe = sorted(df["ticker"].dropna().unique().tolist())[:args.max_tickers]
    print(f"[universe] {len(universe)} tickers (capped)")

    # Pre-fetch bars for all
    print(f"[bars] fetching daily bars for {len(universe)} tickers + SPY...")
    bar_cache = {}
    for i, t in enumerate(universe, 1):
        if i % 100 == 0:
            print(f"  {i}/{len(universe)}...")
        bars = fetch_daily_bars(t, days=args.bar_days)
        if not bars.empty:
            bar_cache[t] = bars
    spy_full = fetch_spy_benchmark(days=args.bar_days)
    print(f"[bars] cached {len(bar_cache)} tickers")

    # Load ML model
    import lightgbm as lgb
    model_path = Path(args.model_dir) / "lgbm_r3m.txt"
    if not model_path.exists():
        print(f"FAIL: model not at {model_path}. Run pattern_miner first.")
        return 1
    booster = lgb.Booster(model_file=str(model_path))
    features = pd.read_csv(Path(args.model_dir) / "features.csv")["feature"].tolist()
    medians_df = pd.read_csv(Path(args.model_dir) / "feature_medians.csv", index_col=0)
    medians = medians_df.iloc[:, 0]
    print(f"[ml] loaded model, {len(features)} features")

    # Rebalance dates
    dates = get_rebalance_dates(args.start, args.end)
    print(f"[backtest] {len(dates)} month-ends")

    # Walk-forward
    nav = {
        "SPY": [1.0],
        "OLD_정석": [1.0],
        "ML_pred": [1.0],
        "T5_turn": [1.0],
        "Hybrid": [1.0],
    }
    monthly_returns = []

    for i in range(len(dates) - 1):
        date = dates[i]
        next_date = dates[i + 1]
        print(f"\n[{date.date()}] -> [{next_date.date()}]")

        # Restrict feature_store to PIT (only this date snapshot)
        snap = df[df["rebalance_date"] == date]
        if snap.empty:
            print(f"  no feature snapshot, skipping")
            continue

        # SPY benchmark
        spy_ret, _ = monthly_return_for_basket(
            ["SPY"], date, next_date, {"SPY": spy_full})
        nav["SPY"].append(nav["SPY"][-1] * (1 + spy_ret / 100))

        # Old 정석
        picks_old = strategy_old_model(scored_oos, date, top_n=args.top_n)
        old_ret, n_old = monthly_return_for_basket(picks_old, date, next_date, bar_cache)
        nav["OLD_정석"].append(nav["OLD_정석"][-1] * (1 + old_ret / 100))

        # ML predict
        picks_ml = strategy_ml_predict(df, date, booster, features, medians, top_n=args.top_n)
        ml_ret, n_ml = monthly_return_for_basket(picks_ml, date, next_date, bar_cache)
        nav["ML_pred"].append(nav["ML_pred"][-1] * (1 + ml_ret / 100))

        # T5
        picks_t5 = strategy_t5_turnaround(
            list(bar_cache.keys()), date, bar_cache, spy_full, top_n=args.top_n)
        t5_ret, n_t5 = monthly_return_for_basket(picks_t5, date, next_date, bar_cache)
        nav["T5_turn"].append(nav["T5_turn"][-1] * (1 + t5_ret / 100))

        # Hybrid: ML top 30 ∩ T5 (or fallback to ML)
        ml30 = strategy_ml_predict(df, date, booster, features, medians, top_n=30)
        t5_set = set(picks_t5)
        hybrid_picks = [t for t in ml30 if t in t5_set][:args.top_n]
        if len(hybrid_picks) < 5:
            hybrid_picks = picks_ml    # fallback
        h_ret, n_h = monthly_return_for_basket(hybrid_picks, date, next_date, bar_cache)
        nav["Hybrid"].append(nav["Hybrid"][-1] * (1 + h_ret / 100))

        monthly_returns.append({
            "date": date.date(),
            "SPY_ret_pct": spy_ret,
            "OLD_정석_ret_pct": old_ret,
            "ML_pred_ret_pct": ml_ret,
            "T5_turn_ret_pct": t5_ret,
            "Hybrid_ret_pct": h_ret,
            "n_old_valid": n_old, "n_ml_valid": n_ml,
            "n_t5_valid": n_t5, "n_hybrid_valid": n_h,
        })
        print(f"  SPY={spy_ret:+5.2f}%  OLD={old_ret:+5.2f}%  "
              f"ML={ml_ret:+5.2f}%  T5={t5_ret:+5.2f}%  HYB={h_ret:+5.2f}%")

    # Save outputs
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    monthly_df = pd.DataFrame(monthly_returns)
    monthly_df.to_csv(out_dir / "strategy_returns.csv", index=False)

    # Summary stats
    n_months = len(monthly_returns)
    summary = []
    for strat in ["SPY", "OLD_정석", "ML_pred", "T5_turn", "Hybrid"]:
        nav_series = pd.Series(nav[strat])
        rets = nav_series.pct_change().dropna() * 100
        if len(rets) == 0:
            continue
        total_ret = (nav_series.iloc[-1] - 1) * 100
        cagr = ((nav_series.iloc[-1]) ** (12 / n_months) - 1) * 100
        sharpe = rets.mean() / rets.std() * np.sqrt(12) if rets.std() > 0 else 0
        max_dd = (nav_series / nav_series.cummax() - 1).min() * 100
        hit_rate = (rets > 0).mean() * 100
        summary.append({
            "strategy": strat,
            "total_return_pct": total_ret,
            "cagr_pct": cagr,
            "sharpe": sharpe,
            "max_drawdown_pct": max_dd,
            "monthly_hit_rate_pct": hit_rate,
            "n_months": n_months,
        })
    summary_df = pd.DataFrame(summary)
    summary_df.to_csv(out_dir / "strategy_summary.csv", index=False)

    print()
    print("=" * 75)
    print("STRATEGY COMPARISON SUMMARY")
    print("=" * 75)
    print(summary_df.to_string(index=False))

    # Excess return vs SPY
    spy_total = next(s["total_return_pct"] for s in summary if s["strategy"] == "SPY")
    print()
    print("Alpha vs SPY:")
    for s in summary:
        if s["strategy"] != "SPY":
            print(f"  {s['strategy']:<12} alpha = {s['total_return_pct'] - spy_total:+.2f}% "
                  f"(CAGR {s['cagr_pct']:+.2f}%, Sharpe {s['sharpe']:.2f})")

    return 0


if __name__ == "__main__":
    sys.exit(main())
