"""Helper to load Finnhub consolidated features by ticker.

Used by scanner.py and daily_review.py for fundamental gate application.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Optional

if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd

from aggressive.agg_config import load_agg_config


def load_finnhub_features_dict(
    max_age_hours: float = 168.0,    # 7 days
    state_dir: Optional[Path] = None,
) -> dict[str, dict]:
    """Load consolidated Finnhub features keyed by ticker.

    Returns empty dict if parquet/csv missing or too old.
    """
    if state_dir is None:
        cfg = load_agg_config()
        state_dir = cfg.state_dir / "finnhub"

    parquet_path = state_dir / "r1000_features.parquet"
    csv_path = state_dir / "r1000_features.csv"

    df = pd.DataFrame()
    if parquet_path.exists():
        age = (time.time() - parquet_path.stat().st_mtime) / 3600
        if age > max_age_hours:
            return {}
        try:
            df = pd.read_parquet(parquet_path)
        except Exception:
            df = pd.DataFrame()
    if df.empty and csv_path.exists():
        try:
            df = pd.read_csv(csv_path)
        except Exception:
            df = pd.DataFrame()

    if df.empty or "ticker" not in df.columns:
        return {}

    # Build dict
    df["ticker"] = df["ticker"].astype(str).str.upper().str.strip()
    out: dict[str, dict] = {}
    for _, row in df.iterrows():
        ticker = row["ticker"]
        # Convert row to plain dict, drop NaN values for cleanliness
        row_dict = {}
        for k, v in row.items():
            if pd.isna(v):
                continue
            # Numpy scalars -> Python
            if hasattr(v, "item"):
                v = v.item()
            row_dict[k] = v
        out[ticker] = row_dict
    return out


def load_finnhub_live_from_cache_dir(
    cache_dir: Optional[Path] = None,
    tickers: Optional[list[str]] = None,
) -> dict[str, dict]:
    """Alternative loader - reads per-ticker JSONs directly from cache.

    Useful during collection-in-progress when consolidated parquet is stale.
    """
    if cache_dir is None:
        cfg = load_agg_config()
        cache_dir = cfg.cache_dir / "finnhub"

    out: dict[str, dict] = {}
    endpoints_to_scan = ["stock_metric", "stock_recommendation",
                          "stock_insider_sentiment", "stock_insider_transactions",
                          "stock_earnings", "calendar_earnings"]

    # Get union of all tickers across endpoint dirs
    all_tickers: set[str] = set()
    for ep in endpoints_to_scan:
        ep_dir = cache_dir / ep
        if not ep_dir.exists():
            continue
        for f in ep_dir.iterdir():
            if f.suffix == ".json":
                t = f.stem.upper()
                all_tickers.add(t)

    if tickers:
        all_tickers &= {t.upper() for t in tickers}

    # For each ticker, try to load metric (most important)
    from aggressive.finnhub_client import (
        compute_insider_cluster_score,
        compute_mspr_latest,
        compute_recommendation_trend,
        compute_earnings_event_features,
    )

    for ticker in all_tickers:
        row = {"ticker": ticker}
        # Load metric
        metric_path = cache_dir / "stock_metric" / f"{ticker}.json"
        if metric_path.exists():
            try:
                metric = json.loads(metric_path.read_text(encoding="utf-8"))
                m = metric.get("metric", {}) if isinstance(metric, dict) else {}
                pe = m.get("peExclExtraTTM")
                g5 = m.get("epsGrowth5Y")
                gq = m.get("epsGrowthQuarterlyYoy")
                row["fh_peExclExtra_ttm"] = pe
                row["fh_epsGrowth5Y"] = g5
                row["fh_epsGrowth3Y"] = m.get("epsGrowth3Y")
                row["fh_epsGrowthQuarterlyYoy"] = gq
                row["fh_revenueGrowthQuarterlyYoy"] = m.get("revenueGrowthQuarterlyYoy")
                row["fh_roe_ttm"] = m.get("roeTTM")
                row["fh_operatingMargin_ttm"] = m.get("operatingMarginTTM")
                if pe and g5 and g5 > 0:
                    row["fh_peg_5y"] = float(pe) / float(g5)
                if pe and gq and gq > 0:
                    row["fh_peg_quarterly"] = float(pe) / float(gq)
            except Exception:
                pass

        # Insider transactions
        ins_path = cache_dir / "stock_insider_transactions" / f"{ticker}.json"
        if ins_path.exists():
            try:
                data = json.loads(ins_path.read_text(encoding="utf-8"))
                txs = data.get("data", []) if isinstance(data, dict) else []
                cluster = compute_insider_cluster_score(txs, days=30)
                row["fh_insider_cluster_30d_score"] = cluster["cluster_score"]
                row["fh_insider_n_buyers_30d"] = cluster["n_buyers_recent"]
                row["fh_insider_buy_value_30d"] = cluster["total_value_usd"]
            except Exception:
                pass

        # Insider sentiment
        sen_path = cache_dir / "stock_insider_sentiment" / f"{ticker}.json"
        if sen_path.exists():
            try:
                data = json.loads(sen_path.read_text(encoding="utf-8"))
                lst = data.get("data", []) if isinstance(data, dict) else []
                mspr = compute_mspr_latest(lst)
                row["fh_mspr_latest"] = mspr["mspr_latest"]
                row["fh_mspr_3m_avg"] = mspr["mspr_3m_avg"]
            except Exception:
                pass

        # Recommendations
        rec_path = cache_dir / "stock_recommendation" / f"{ticker}.json"
        if rec_path.exists():
            try:
                recs = json.loads(rec_path.read_text(encoding="utf-8"))
                trend = compute_recommendation_trend(recs if isinstance(recs, list) else [])
                for k, v in trend.items():
                    row[f"fh_rec_{k.replace('analyst_', '')}"] = v
            except Exception:
                pass

        # Earnings calendar
        cal_path = cache_dir / "calendar_earnings" / f"{ticker}.json"
        surp_path = cache_dir / "stock_earnings" / f"{ticker}.json"
        try:
            cal = []
            surp = []
            if cal_path.exists():
                cd = json.loads(cal_path.read_text(encoding="utf-8"))
                cal = cd.get("earningsCalendar", []) if isinstance(cd, dict) else []
            if surp_path.exists():
                surp = json.loads(surp_path.read_text(encoding="utf-8"))
                if not isinstance(surp, list):
                    surp = []
            feat = compute_earnings_event_features(cal, surp)
            for k, v in feat.items():
                row[f"fh_{k}"] = v
        except Exception:
            pass

        out[ticker] = row

    return out


if __name__ == "__main__":
    print("Loading from parquet:")
    d = load_finnhub_features_dict()
    print(f"  {len(d)} tickers")
    if d:
        sample = next(iter(d.values()))
        print(f"  sample keys: {list(sample.keys())[:10]}")

    print("\nLoading from cache dir directly:")
    d2 = load_finnhub_live_from_cache_dir()
    print(f"  {len(d2)} tickers")
    if d2:
        sample = next(iter(d2.values()))
        print(f"  sample keys: {list(sample.keys())[:10]}")
