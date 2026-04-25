"""r1000_insider_analyst_impact - Empirical analysis of insider + analyst signals.

User mandate (2026-04-25):
  "내부자 펀드 매수 이런 것도 가능한가? 매수 매도 후 몇 개월 후 몇 % 확률로
   오르거나 내리거나. 애널리스트 의견 및 변동 목표주가 영향도 분석해보자."

Loads Finnhub cache (insider transactions + recommendation trends) plus
Alpaca bars to compute forward returns for each signal event. Outputs
statistical probability tables.

Outputs:
  outputs/insider_analyst_impact/insider_returns.csv
  outputs/insider_analyst_impact/analyst_returns.csv
  outputs/insider_analyst_impact/combined_returns.csv
  outputs/insider_analyst_impact/summary.txt
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent))

import numpy as np
import pandas as pd

from aggressive.data_alpaca import fetch_daily_bars, fetch_spy_benchmark


# ---------------------------------------------------------------------------
# Helpers: forward return calculation
# ---------------------------------------------------------------------------

def fwd_return_pct(close: pd.Series, base_date: pd.Timestamp, days: int) -> Optional[float]:
    """Pct return from base_date close to base_date+days close. None if missing."""
    try:
        idx = close.index
        if hasattr(idx, "tz") and idx.tz is not None:
            base_date = pd.Timestamp(base_date).tz_localize(idx.tz) if pd.Timestamp(base_date).tzinfo is None else pd.Timestamp(base_date).tz_convert(idx.tz)
        else:
            base_date = pd.Timestamp(base_date).tz_localize(None) if hasattr(pd.Timestamp(base_date), "tz_localize") else base_date
        loc = idx.searchsorted(base_date)
        if loc == 0:
            return None
        loc -= 1
        if loc + days >= len(close):
            return None
        p0 = float(close.iloc[loc])
        p1 = float(close.iloc[loc + days])
        if p0 <= 0:
            return None
        return (p1 / p0 - 1.0) * 100.0
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Insider analysis
# ---------------------------------------------------------------------------

def collect_insider_events(cache_dir: Path, verbose: bool = True) -> list[dict]:
    """Read all per-ticker insider JSONs and emit individual transaction events.

    Each event row:
      ticker, date, code (P/S/M), shares, price, value, name
    """
    insider_dir = cache_dir / "stock_insider-transactions"
    if not insider_dir.exists():
        return []

    events = []
    files = list(insider_dir.glob("*.json"))
    if verbose:
        print(f"[insider] reading {len(files)} ticker files...")
    for i, f in enumerate(files, 1):
        if verbose and i % 200 == 0:
            print(f"  {i}/{len(files)}...")
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            txs = data.get("data", []) or []
            ticker = data.get("symbol") or f.stem.upper()
            for t in txs:
                date_str = t.get("transactionDate")
                code = t.get("transactionCode", "")
                shares = float(t.get("change") or 0.0)
                price = float(t.get("transactionPrice") or 0.0)
                if not date_str or shares == 0 or price == 0:
                    continue
                events.append({
                    "ticker": ticker,
                    "date": pd.to_datetime(date_str),
                    "code": code,
                    "shares": shares,
                    "price": price,
                    "value_usd": abs(shares) * price,
                    "name": t.get("name", ""),
                })
        except Exception:
            continue
    return events


def aggregate_insider_clusters(events: list[dict], window_days: int = 30) -> list[dict]:
    """Group insider events into clusters per ticker per window."""
    df = pd.DataFrame(events)
    if df.empty:
        return []
    # Only keep P (purchase) and S (sale) — exclude options M/F/A
    df = df[df["code"].isin(["P", "S"])].copy()
    df = df.sort_values(["ticker", "date"])

    clusters = []
    for ticker, group in df.groupby("ticker"):
        group = group.sort_values("date").reset_index(drop=True)
        # Sliding window aggregation
        i = 0
        while i < len(group):
            base_date = group.iloc[i]["date"]
            window = group[
                (group["date"] >= base_date) &
                (group["date"] <= base_date + pd.Timedelta(days=window_days))
            ]
            buys = window[window["code"] == "P"]
            sells = window[window["code"] == "S"]
            n_buyers = buys["name"].nunique()
            n_sellers = sells["name"].nunique()
            if len(buys) > 0 or len(sells) > 0:
                clusters.append({
                    "ticker": ticker,
                    "cluster_start": base_date,
                    "n_buy_txs": len(buys),
                    "n_sell_txs": len(sells),
                    "n_buyers_unique": int(n_buyers),
                    "n_sellers_unique": int(n_sellers),
                    "buy_value_usd": float(buys["value_usd"].sum()),
                    "sell_value_usd": float(sells["value_usd"].sum()),
                    "net_value_usd": float(buys["value_usd"].sum() - sells["value_usd"].sum()),
                })
            # Skip past the end of this window to avoid duplicate clusters
            window_end_date = base_date + pd.Timedelta(days=window_days)
            next_idx = group[group["date"] > window_end_date].index.min()
            if pd.isna(next_idx):
                break
            i = next_idx
    return clusters


def compute_insider_forward_returns(
    clusters: list[dict],
    horizons: list[int] = [21, 63, 126],   # ~1m, 3m, 6m trading days
    verbose: bool = True,
) -> pd.DataFrame:
    """For each cluster, compute forward returns at multiple horizons."""
    if not clusters:
        return pd.DataFrame()
    # Group by ticker for efficient bar fetching
    by_ticker = defaultdict(list)
    for c in clusters:
        by_ticker[c["ticker"]].append(c)

    rows = []
    for i, (ticker, ticker_clusters) in enumerate(by_ticker.items(), 1):
        if verbose and i % 50 == 0:
            print(f"  insider fwd: {i}/{len(by_ticker)} tickers...")
        df = fetch_daily_bars(ticker, days=400)
        if df.empty or len(df) < 200:
            continue
        close = df["close"]
        for c in ticker_clusters:
            row = {**c}
            for h in horizons:
                row[f"fwd_{h}d_pct"] = fwd_return_pct(close, c["cluster_start"], h)
            rows.append(row)
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Analyst analysis
# ---------------------------------------------------------------------------

def collect_analyst_events(cache_dir: Path, verbose: bool = True) -> list[dict]:
    """Read recommendation trends and detect upgrade/downgrade waves.

    Each row in /stock/recommendation is a monthly snapshot
    {strongBuy, buy, hold, sell, strongSell, period}.
    Detect MoM changes:
      - upgrade_wave: total bull (sBuy+buy) increased by 2+
      - downgrade_wave: total bull decreased by 2+
    """
    rec_dir = cache_dir / "stock_recommendation"
    if not rec_dir.exists():
        return []
    files = list(rec_dir.glob("*.json"))
    if verbose:
        print(f"[analyst] reading {len(files)} ticker files...")

    events = []
    for i, f in enumerate(files, 1):
        if verbose and i % 200 == 0:
            print(f"  {i}/{len(files)}...")
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if not isinstance(data, list):
                continue
            ticker = f.stem.upper()
            sorted_data = sorted(data, key=lambda d: str(d.get("period", "")))
            for j in range(1, len(sorted_data)):
                prev = sorted_data[j - 1]
                curr = sorted_data[j]
                prev_bull = int(prev.get("strongBuy") or 0) + int(prev.get("buy") or 0)
                curr_bull = int(curr.get("strongBuy") or 0) + int(curr.get("buy") or 0)
                prev_bear = int(prev.get("sell") or 0) + int(prev.get("strongSell") or 0)
                curr_bear = int(curr.get("sell") or 0) + int(curr.get("strongSell") or 0)
                bull_delta = curr_bull - prev_bull
                bear_delta = curr_bear - prev_bear
                events.append({
                    "ticker": ticker,
                    "date": pd.to_datetime(curr.get("period")),
                    "bull_count": curr_bull,
                    "bear_count": curr_bear,
                    "bull_delta": bull_delta,
                    "bear_delta": bear_delta,
                    "event_type": (
                        "upgrade_wave_3" if bull_delta >= 3 else
                        "upgrade_wave_2" if bull_delta == 2 else
                        "upgrade_1" if bull_delta == 1 else
                        "downgrade_wave_3" if bull_delta <= -3 else
                        "downgrade_wave_2" if bull_delta == -2 else
                        "downgrade_1" if bull_delta == -1 else
                        "no_change"
                    ),
                })
        except Exception:
            continue
    return events


def compute_analyst_forward_returns(
    events: list[dict],
    horizons: list[int] = [21, 63, 126],
    verbose: bool = True,
) -> pd.DataFrame:
    if not events:
        return pd.DataFrame()
    by_ticker = defaultdict(list)
    for e in events:
        by_ticker[e["ticker"]].append(e)

    rows = []
    for i, (ticker, ticker_events) in enumerate(by_ticker.items(), 1):
        if verbose and i % 50 == 0:
            print(f"  analyst fwd: {i}/{len(by_ticker)} tickers...")
        df = fetch_daily_bars(ticker, days=400)
        if df.empty or len(df) < 200:
            continue
        close = df["close"]
        for e in ticker_events:
            row = {**e}
            for h in horizons:
                row[f"fwd_{h}d_pct"] = fwd_return_pct(close, e["date"], h)
            rows.append(row)
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Statistical summaries
# ---------------------------------------------------------------------------

def summarize_insider(df: pd.DataFrame) -> pd.DataFrame:
    """Stratify insider clusters and compute hit rates."""
    if df.empty:
        return pd.DataFrame()

    # Bucket by cluster type
    def bucket(r):
        if r["n_buyers_unique"] >= 3:
            return f"BUY_cluster_3+_${int(r['buy_value_usd']/1e6) if r['buy_value_usd'] else 0}M"
        if r["n_buyers_unique"] == 2:
            return "BUY_2_buyers"
        if r["n_buyers_unique"] == 1 and r["buy_value_usd"] >= 100_000:
            return "BUY_1_buyer_100k+"
        if r["n_sellers_unique"] >= 3:
            return "SELL_cluster_3+"
        if r["n_sellers_unique"] == 1 and r["sell_value_usd"] >= 1_000_000:
            return "SELL_1_1M+"
        return "OTHER"

    df = df.copy()
    df["bucket_simple"] = df.apply(
        lambda r:
            "BUY_cluster_3+" if r["n_buyers_unique"] >= 3 else
            "BUY_cluster_2" if r["n_buyers_unique"] == 2 else
            "BUY_single_large" if r["n_buyers_unique"] == 1 and r["buy_value_usd"] >= 100_000 else
            "BUY_single_small" if r["n_buyers_unique"] == 1 else
            "SELL_cluster_3+" if r["n_sellers_unique"] >= 3 else
            "SELL_cluster_2" if r["n_sellers_unique"] == 2 else
            "SELL_single_large" if r["n_sellers_unique"] == 1 and r["sell_value_usd"] >= 1_000_000 else
            "SELL_single_small" if r["n_sellers_unique"] == 1 else
            "OTHER", axis=1,
    )

    summary = []
    for bucket, group in df.groupby("bucket_simple"):
        for col in ["fwd_21d_pct", "fwd_63d_pct", "fwd_126d_pct"]:
            valid = group[col].dropna()
            if len(valid) < 10:
                continue
            summary.append({
                "bucket": bucket,
                "horizon": col.replace("fwd_", "").replace("_pct", ""),
                "n": len(valid),
                "avg_pct": float(valid.mean()),
                "median_pct": float(valid.median()),
                "hit_positive": float((valid > 0).mean()),
                "hit_5pct_up": float((valid > 5).mean()),
                "hit_10pct_up": float((valid > 10).mean()),
                "hit_5pct_down": float((valid < -5).mean()),
                "hit_10pct_down": float((valid < -10).mean()),
                "p25": float(valid.quantile(0.25)),
                "p75": float(valid.quantile(0.75)),
            })
    return pd.DataFrame(summary).sort_values(["bucket", "horizon"])


def summarize_analyst(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    summary = []
    for event_type, group in df.groupby("event_type"):
        if event_type == "no_change":
            continue
        for col in ["fwd_21d_pct", "fwd_63d_pct", "fwd_126d_pct"]:
            valid = group[col].dropna()
            if len(valid) < 10:
                continue
            summary.append({
                "event_type": event_type,
                "horizon": col.replace("fwd_", "").replace("_pct", ""),
                "n": len(valid),
                "avg_pct": float(valid.mean()),
                "median_pct": float(valid.median()),
                "hit_positive": float((valid > 0).mean()),
                "hit_5pct_up": float((valid > 5).mean()),
                "hit_10pct_up": float((valid > 10).mean()),
                "hit_5pct_down": float((valid < -5).mean()),
                "p25": float(valid.quantile(0.25)),
                "p75": float(valid.quantile(0.75)),
            })
    return pd.DataFrame(summary).sort_values(["event_type", "horizon"])


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--cache-dir", type=str,
                   default="aggressive/cache/finnhub")
    p.add_argument("--output-dir", type=str,
                   default="outputs/insider_analyst_impact")
    args = p.parse_args()

    print("=" * 72)
    print(f"r1000 Insider + Analyst Impact Analyzer - {datetime.now():%Y-%m-%d %H:%M}")
    print("=" * 72)

    cache_dir = Path(args.cache_dir)
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # PHASE 1A: Insider events
    print("\n[1A] Insider transactions analysis...")
    events = collect_insider_events(cache_dir, verbose=True)
    print(f"     total raw events: {len(events)}")
    clusters = aggregate_insider_clusters(events, window_days=30)
    print(f"     clusters (30-day windows): {len(clusters)}")
    insider_df = compute_insider_forward_returns(clusters)
    print(f"     forward returns computed: {len(insider_df)}")
    if not insider_df.empty:
        insider_df.to_csv(out_dir / "insider_clusters_with_returns.csv", index=False)

    insider_summary = summarize_insider(insider_df)
    print("\n=== INSIDER IMPACT SUMMARY ===")
    if not insider_summary.empty:
        insider_summary.to_csv(out_dir / "insider_summary.csv", index=False)
        pd.set_option("display.width", 220)
        print(insider_summary.to_string(index=False))

    # PHASE 1B: Analyst events
    print("\n[1B] Analyst recommendation analysis...")
    a_events = collect_analyst_events(cache_dir, verbose=True)
    print(f"     total events: {len(a_events)}")
    analyst_df = compute_analyst_forward_returns(a_events)
    print(f"     forward returns computed: {len(analyst_df)}")
    if not analyst_df.empty:
        analyst_df.to_csv(out_dir / "analyst_events_with_returns.csv", index=False)

    analyst_summary = summarize_analyst(analyst_df)
    print("\n=== ANALYST IMPACT SUMMARY ===")
    if not analyst_summary.empty:
        analyst_summary.to_csv(out_dir / "analyst_summary.csv", index=False)
        print(analyst_summary.to_string(index=False))

    # Save manifest
    manifest = {
        "timestamp": datetime.now().isoformat(),
        "n_insider_events": len(events),
        "n_insider_clusters": len(clusters),
        "n_analyst_events": len(a_events),
        "horizons_days": [21, 63, 126],
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")

    print()
    print(f"[save] all outputs in {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
