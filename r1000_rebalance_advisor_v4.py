"""r1000_rebalance_advisor_v4 - ML-primary rebalance advisor.

User mandate (2026-04-25):
  Backtest proved ML predictor delivers +75.7% alpha vs SPY (CAGR 76.3%
  vs SPY 21.5%, Sharpe 2.14). Integrate as PRIMARY signal in advisor.

v4 Algorithm:
  1. Load unified scored CSV (1012 R1000 names: 610 real + 402 synthetic)
  2. Run ML predictor -> rank by predicted_r3m_pct
  3. Quality filter: 정석 score >= 1.0 AND market_cap >= $5B
  4. Take top 30 by predicted_r3m
  5. Apply tier caps (top 3 -> 18%, 4-6 -> 12%, 7-12 -> 8%)
  6. Sort by predicted_r3m desc -> assign weights
  7. Compute diff vs current portfolio

Output: outputs_advisor_v4/new_top12_proposed.csv

This is the production advisor. F. integration of backtested ML model.
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent))

import numpy as np
import pandas as pd

from r1000_ml_predictor import load_artifacts


TARGET_N_POSITIONS = 12
TIER_CAPS = [
    (3, 0.18),
    (6, 0.12),
    (999, 0.08),
]


@dataclass
class V4Pick:
    ticker: str
    name: str
    sector: str
    rank: int
    predicted_r3m_pct: float
    decile: int
    confidence_band: str
    quality_score: float
    proposed_weight: float
    current_weight: float
    target_dollars: float
    target_shares: float
    entry_price: float
    action: str
    warnings: list[str] = field(default_factory=list)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--scored-csv", default=r"G:/내 드라이브/r1000_top30_institutional/outputs/scored_unified.csv")
    p.add_argument("--portfolio-csv", default=r"G:/내 드라이브/r1000_top30_institutional/outputs/portfolio_latest.csv")
    p.add_argument("--feature-store", default=r"G:/내 드라이브/r1000_top30_institutional/feature_store/feature_store_latest.parquet")
    p.add_argument("--model-dir", default="outputs/discovered_rules/model")
    p.add_argument("--capital", type=float, default=100_000.0,
                   help="paper trading capital ($)")
    p.add_argument("--output-dir", default="outputs_advisor_v4")
    args = p.parse_args()

    print("=" * 70)
    print(f"r1000 Advisor v4 (ML-Primary) - {datetime.now():%Y-%m-%d %H:%M}")
    print("=" * 70)

    # Load unified scored
    scored = pd.read_csv(args.scored_csv)
    print(f"[load] unified scored: {len(scored)} rows")

    # Load current portfolio
    portfolio = pd.read_csv(args.portfolio_csv)
    current_weights = {}
    for _, r in portfolio.iterrows():
        current_weights[str(r["ticker"]).upper()] = float(r.get("weight") or 0.0)
    print(f"[load] current portfolio: {len(portfolio)}")

    # Load feature_store and ML model
    fs = pd.read_parquet(args.feature_store)
    fs["rebalance_date"] = pd.to_datetime(fs["rebalance_date"])
    latest_date = fs["rebalance_date"].max()
    fs_latest = fs[fs["rebalance_date"] == latest_date].copy()
    print(f"[ml] snapshot date: {latest_date.date()}, rows: {len(fs_latest)}")

    booster, features, medians = load_artifacts(Path(args.model_dir))
    X = fs_latest[features].copy()
    for c in features:
        X[c] = X[c].fillna(medians.get(c, 0.0))
    fs_latest["pred_r3m"] = booster.predict(X.values) * 100.0
    fs_latest["decile"] = pd.qcut(
        fs_latest["pred_r3m"], 10, labels=False, duplicates="drop")

    # Merge with unified scored (for quality + sector + name)
    merged = fs_latest[["ticker", "pred_r3m", "decile"]].merge(
        scored[["ticker", "score", "Name", "sector", "current_price_live", "market_cap_live"]],
        on="ticker", how="left",
    )

    # Quality filter
    merged["score"] = pd.to_numeric(merged["score"], errors="coerce").fillna(0)
    merged["market_cap_live"] = pd.to_numeric(merged["market_cap_live"], errors="coerce")
    candidates = merged[
        (merged["score"] >= 1.0) &
        ((merged["market_cap_live"] >= 5e9) | merged["market_cap_live"].isna())
    ].copy()
    print(f"[filter] quality + mcap pass: {len(candidates)}")

    # Sort by predicted_r3m desc
    candidates = candidates.sort_values("pred_r3m", ascending=False).reset_index(drop=True)

    # Pick top N with tier caps
    picks: list[V4Pick] = []
    for i, row in candidates.head(TARGET_N_POSITIONS * 2).iterrows():
        if len(picks) >= TARGET_N_POSITIONS:
            break
        rank = len(picks) + 1
        tier_cap = 0.08
        for n_up, cap in TIER_CAPS:
            if rank <= n_up:
                tier_cap = cap
                break
        ticker = str(row["ticker"]).upper()
        cw = current_weights.get(ticker, 0.0)
        action = ("BUY" if cw == 0
                   else "ADD" if tier_cap > cw * 1.1
                   else "TRIM" if tier_cap < cw * 0.9
                   else "HOLD")
        target_dollars = args.capital * tier_cap
        price = float(row.get("current_price_live") or 0.0)
        shares = target_dollars / price if price > 0 else 0
        # Confidence band
        pred = float(row["pred_r3m"])
        if pred > 5: band = "bullish"
        elif pred > 0: band = "neutral"
        else: band = "bearish"
        picks.append(V4Pick(
            ticker=ticker,
            name=str(row.get("Name", ""))[:30],
            sector=str(row.get("sector", "")),
            rank=rank,
            predicted_r3m_pct=pred,
            decile=int(row.get("decile") or 0),
            confidence_band=band,
            quality_score=float(row.get("score", 0)),
            proposed_weight=tier_cap,
            current_weight=cw,
            target_dollars=target_dollars,
            target_shares=shares,
            entry_price=price,
            action=action,
        ))

    # Normalize to 100%
    total_w = sum(p.proposed_weight for p in picks)
    if total_w > 1.0:
        scale = 1.0 / total_w
        for p in picks:
            p.proposed_weight *= scale
            p.target_dollars = args.capital * p.proposed_weight
            p.target_shares = p.target_dollars / p.entry_price if p.entry_price > 0 else 0

    # Save
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    df_picks = pd.DataFrame([asdict(p) for p in picks])
    df_picks.to_csv(out_dir / "new_top12_proposed.csv", index=False)

    # Transparency: show prediction distribution
    pred_min = fs_latest["pred_r3m"].min()
    pred_max = fs_latest["pred_r3m"].max()
    pred_med = fs_latest["pred_r3m"].median()
    print()
    print(f"ML Prediction Distribution (this snapshot):")
    print(f"  range: {pred_min:.2f}% ~ {pred_max:.2f}%, median: {pred_med:.2f}%")
    if (pred_max - pred_min) < 1.5:
        print("  [WARN] narrow prediction spread = low model confidence on this snapshot")
        print("  [WARN] Consider running v3 hybrid + manual review instead.")

    # Print report
    print()
    print("=" * 100)
    print(f"V4 ML-PRIMARY PORTFOLIO - {datetime.now():%Y-%m-%d %H:%M}")
    print(f"Capital: ${args.capital:,.0f}")
    print("=" * 100)
    print()
    print(f"{'Rank':<5} {'Ticker':<6} {'Weight':>7} {'$':>10} {'Shares':>9} "
          f"{'Pred 3m':>9} {'Decile':>7} {'Quality':>8} {'Action':<6} {'Sector':<22}")
    print("-" * 110)
    for p in picks:
        print(f"{p.rank:<5} {p.ticker:<6} {p.proposed_weight*100:>6.2f}% "
              f"${p.target_dollars:>9,.0f} {p.target_shares:>9.2f} "
              f"{p.predicted_r3m_pct:>+8.2f}% {p.decile:>7} "
              f"{p.quality_score:>7.2f} {p.action:<6} {p.sector[:22]:<22}")

    total_weight = sum(p.proposed_weight for p in picks)
    total_dollars = sum(p.target_dollars for p in picks)
    print("-" * 110)
    print(f"TOTAL: {total_weight*100:.1f}% / ${total_dollars:,.0f}")

    # Diff vs current
    old_tickers = {t for t, w in current_weights.items() if w > 0 and t != "CASH"}
    new_tickers = {p.ticker for p in picks}
    print()
    print("DIFF vs current portfolio:")
    print(f"  EXIT ({len(old_tickers - new_tickers)}): {sorted(old_tickers - new_tickers)}")
    print(f"  ADD  ({len(new_tickers - old_tickers)}): {sorted(new_tickers - old_tickers)}")
    print(f"  HOLD ({len(old_tickers & new_tickers)}): {sorted(old_tickers & new_tickers)}")

    print(f"\n[save] {out_dir}/new_top12_proposed.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
