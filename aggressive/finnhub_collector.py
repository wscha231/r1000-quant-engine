"""Finnhub R1000 batch collector.

Fetches all useful endpoints for the full R1000 universe and consolidates
into a single feature DataFrame per ticker, saved as parquet. This parquet
is consumed by both aggressive engine and 정석 engine.

Schedules (via Windows Task Scheduler or manual):
  - collect_weekly()  :  Mondays 23:30 KST
                         [metric, recommendations, peers, earnings_surprises]
                         ~17-35 min for 1008 tickers
  - collect_daily()   :  Every day 00:00 KST
                         [insider_transactions, insider_sentiment,
                          earnings_calendar]
                         ~17-25 min for 1008 tickers

Output: aggressive/state/finnhub/r1000_features.parquet (consolidated)
        aggressive/cache/finnhub/{endpoint}/{ticker}.json (per-ticker cache)

Rate limit: 60 calls/min -> ~17 min per full-universe endpoint.
Total daily refresh: ~35 min.
Total weekly refresh: ~70 min.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd

from aggressive.agg_config import load_agg_config
from aggressive.finnhub_client import (
    FinnhubClient,
    compute_earnings_event_features,
    compute_insider_cluster_score,
    compute_mspr_latest,
    compute_recommendation_trend,
)
from aggressive.universe import load_universe


# ---------------------------------------------------------------------------

def _collect_for_ticker(
    client: FinnhubClient,
    ticker: str,
    endpoints: set[str],
    force_refresh: bool = False,
) -> dict:
    """Collect all requested endpoints for one ticker. Returns flat feature row."""
    out: dict = {"ticker": ticker, "collected_at": datetime.utcnow().isoformat()}

    if "metric" in endpoints:
        m = client.metric(ticker, force_refresh=force_refresh)
        # Flatten useful metric keys
        useful = [
            "peExclExtraTTM", "peBasicExclExtraTTM", "peNormalizedAnnual",
            "pbAnnual", "psAnnual", "pfcfShareTTM",
            "epsGrowth5Y", "epsGrowth3Y", "epsGrowthQuarterlyYoy",
            "epsGrowthTTMYoy",
            "revenueGrowthQuarterlyYoy", "revenueGrowth5Y",
            "revenueGrowthTTMYoy",
            "roeTTM", "roaeTTM", "netMarginTTM", "grossMarginTTM",
            "operatingMarginTTM", "operatingMargin5Y",
            "currentRatioAnnual", "quickRatioAnnual",
            "totalDebt/totalEquityAnnual", "longTermDebt/equityAnnual",
            "beta", "52WeekHigh", "52WeekLow",
            "dividendYieldIndicatedAnnual",
            "payoutRatioAnnual",
            "10DayAverageTradingVolume",
            "bookValuePerShareAnnual",
        ]
        for k in useful:
            v = m.get(k)
            # Sanitize key for column name
            col = "fh_" + k.replace("/", "_over_").replace("Annual", "").replace("TTM", "_ttm")
            out[col] = v if v is not None else None

        # Derived: true forward PEG
        pe = m.get("peExclExtraTTM")
        g5 = m.get("epsGrowth5Y")
        gq = m.get("epsGrowthQuarterlyYoy")
        try:
            if pe and g5 and g5 > 0:
                out["fh_peg_5y"] = float(pe) / float(g5)
        except Exception:
            out["fh_peg_5y"] = None
        try:
            if pe and gq and gq > 0:
                out["fh_peg_quarterly"] = float(pe) / float(gq)
        except Exception:
            out["fh_peg_quarterly"] = None

    if "recommendations" in endpoints:
        recs = client.recommendations(ticker, force_refresh=force_refresh)
        trend = compute_recommendation_trend(recs)
        for k, v in trend.items():
            out[f"fh_rec_{k.replace('analyst_', '')}"] = v

    if "insider_transactions" in endpoints:
        txs = client.insider_transactions(ticker, days=90,
                                            force_refresh=force_refresh)
        cluster_30 = compute_insider_cluster_score(txs, days=30)
        cluster_90 = compute_insider_cluster_score(txs, days=90)
        out["fh_insider_cluster_30d_score"] = cluster_30["cluster_score"]
        out["fh_insider_n_buyers_30d"] = cluster_30["n_buyers_recent"]
        out["fh_insider_buy_value_30d"] = cluster_30["total_value_usd"]
        out["fh_insider_net_shares_30d"] = cluster_30["net_shares"]
        out["fh_insider_n_sales_30d"] = cluster_30["n_sales_recent"]
        out["fh_insider_n_buyers_90d"] = cluster_90["n_buyers_recent"]

    if "insider_sentiment" in endpoints:
        sent = client.insider_sentiment(ticker, months=12,
                                           force_refresh=force_refresh)
        mspr = compute_mspr_latest(sent)
        out["fh_mspr_latest"] = mspr["mspr_latest"]
        out["fh_mspr_3m_avg"] = mspr["mspr_3m_avg"]
        out["fh_mspr_latest_period"] = mspr["mspr_latest_period"]

    if "earnings" in endpoints:
        cal = client.earnings_calendar_for_ticker(ticker, days_ahead=90,
                                                    force_refresh=force_refresh)
        surp = client.earnings_surprises(ticker,
                                            force_refresh=force_refresh)
        feat = compute_earnings_event_features(cal, surp)
        for k, v in feat.items():
            out[f"fh_{k}"] = v

    return out


# ---------------------------------------------------------------------------

WEEKLY_ENDPOINTS = {"metric", "recommendations"}
DAILY_ENDPOINTS = {"insider_transactions", "insider_sentiment", "earnings"}
FULL_ENDPOINTS = WEEKLY_ENDPOINTS | DAILY_ENDPOINTS


def collect_r1000(
    endpoints: Optional[set[str]] = None,
    max_tickers: Optional[int] = None,
    universe_source: str = "r1000",
    force_refresh: bool = False,
    verbose: bool = True,
) -> pd.DataFrame:
    """Collect Finnhub data for the full R1000 universe. Returns DataFrame."""
    endpoints = endpoints or FULL_ENDPOINTS

    cfg = load_agg_config()
    tickers, umeta = load_universe(universe_source)
    if not tickers:
        raise RuntimeError("Empty universe")
    if max_tickers:
        tickers = tickers[:max_tickers]

    if verbose:
        print(f"[collect] universe {len(tickers)} tickers "
              f"(source={umeta.get('source_used')})")
        print(f"[collect] endpoints: {sorted(endpoints)}")
        print(f"[collect] force_refresh={force_refresh}")

    client = FinnhubClient()
    rows: list[dict] = []
    t0 = time.monotonic()

    # Checkpoint setup (save partial parquet every 100 tickers)
    checkpoint_every = 100
    out_dir_early = cfg.state_dir / "finnhub"
    out_dir_early.mkdir(parents=True, exist_ok=True)
    checkpoint_file = out_dir_early / "r1000_features_partial.parquet"

    for i, ticker in enumerate(tickers, 1):
        if verbose and (i % 50 == 0 or i == 1):
            elapsed = time.monotonic() - t0
            rate = i / max(elapsed, 0.001)
            eta_sec = (len(tickers) - i) / max(rate, 0.001)
            print(f"[collect] {i}/{len(tickers)} ({rate:.1f}/s, "
                  f"ETA {eta_sec/60:.1f}min)  {ticker}")
        try:
            row = _collect_for_ticker(client, ticker, endpoints,
                                        force_refresh=force_refresh)
            rows.append(row)
        except Exception as e:
            print(f"[collect] {ticker} failed: {e}")
            rows.append({"ticker": ticker, "_error": str(e)})
        # Checkpoint
        if i % checkpoint_every == 0:
            try:
                pd.DataFrame(rows).to_parquet(checkpoint_file)
                if verbose:
                    print(f"[collect] checkpoint saved at {i}/{len(tickers)}")
            except Exception:
                pass

    df = pd.DataFrame(rows)
    elapsed = time.monotonic() - t0

    # Save consolidated parquet
    out_dir = cfg.state_dir / "finnhub"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "r1000_features.parquet"
    try:
        df.to_parquet(out_file)
    except Exception as e:
        # parquet may fail on mixed types; fall back to CSV
        print(f"[collect] parquet write failed ({e}), writing CSV")
        out_file = out_dir / "r1000_features.csv"
        df.to_csv(out_file, index=False)

    ts_file = out_dir / f"r1000_features_{datetime.now():%Y%m%d_%H%M%S}.parquet"
    try:
        df.to_parquet(ts_file)
    except Exception:
        pass

    if verbose:
        print(f"[collect] done in {elapsed/60:.1f}min, saved {out_file}")
        print(f"[collect] columns: {len(df.columns)}, rows: {len(df)}")

    return df


# --- CLI -------------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=["weekly", "daily", "full"],
                   default="full", help="which endpoint set to collect")
    p.add_argument("--max", type=int, default=None,
                   help="limit tickers (for testing)")
    p.add_argument("--universe", choices=["r1000", "themes"],
                   default="r1000")
    p.add_argument("--force-refresh", action="store_true",
                   help="bypass cache TTL")
    args = p.parse_args()

    endpoints_map = {
        "weekly": WEEKLY_ENDPOINTS,
        "daily": DAILY_ENDPOINTS,
        "full": FULL_ENDPOINTS,
    }
    endpoints = endpoints_map[args.mode]

    df = collect_r1000(
        endpoints=endpoints,
        max_tickers=args.max,
        universe_source=args.universe,
        force_refresh=args.force_refresh,
    )

    print()
    print("=" * 70)
    print("Collection Summary")
    print("=" * 70)
    print(f"Rows: {len(df)}")
    print(f"Cols: {len(df.columns)}")
    # Show non-null coverage for key columns
    key_cols = [c for c in df.columns
                if any(k in c for k in
                       ["peg", "mspr", "insider_cluster",
                        "days_to_next", "bull_ratio"])]
    for c in key_cols:
        if c in df.columns:
            pct = df[c].notna().sum() / max(len(df), 1) * 100
            print(f"  {c:<45} {pct:.0f}% populated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
