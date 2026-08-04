#!/usr/bin/env python3
"""Build Top-7 manager discovery signals per (rebalance_date, ticker).

Walk-forward, PIT-clean aggregator. For each (rebalance_date d, ticker t) it
counts how many distinct top-ranked managers (from the 6-month-rolling cohort
study) bought t in 13F filings that became publicly available before d. The
cohorts themselves were selected only from labels with available_from < cohort
date (no lookahead, verified upstream in run_pit_top_manager_follow_study.py).

Inputs:
  --follow-events data_pit/sec/top_manager_13f_follow_events.parquet
      Pre-aggregated by run_pit_top_manager_follow_study.py. One row per
      (manager, ticker, 13F buy event) tagged with cohort_date + cohort_rank +
      cohort_rank_bucket ("top3"/"top7"/"top10") + available_from_ts.
  --candidate-book outputs/reports/candidate_replay_book.csv
      The candidate book whose rebalance dates we anchor on.

Output: data_pit/sec/top_manager_discovery_signals.parquet keyed
(rebalance_date, ticker) with:
  * top3_manager_count, top7_manager_count, top10_manager_count
      Distinct manager CIKs from each bucket that bought t with
      available_from_ts in (d - lookback, d].
  * top7_discovery_score      = log1p(top7_manager_count) / log1p(7)   in [0,1+]
  * top_manager_discovery_score = log1p(top10_manager_count) / log1p(10)
  * latest_top_manager_available_from   ISO timestamp of the freshest event

These two `*_score` columns are the exact names consumed by the
TOP7_MANAGER_DISCOVERY lane in r1000_candidate_lanes.py (lines 64-71). When the
sec_enriched candidate replay merges this parquet, the lane score finally turns
on.

Research-only. Reads only; never mutates.
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pandas_market_calendars as mcal


REPO_ROOT = Path(__file__).resolve().parent.parent


def decision_close_utc_naive(value: pd.Timestamp) -> pd.Timestamp:
    date = pd.Timestamp(value).normalize()
    schedule = mcal.get_calendar("NYSE").schedule(start_date=date, end_date=date)
    if len(schedule) != 1:
        raise ValueError(f"candidate rebalance date is not an NYSE session: {date.date()}")
    close = pd.Timestamp(schedule.iloc[0]["market_close"])
    close = close.tz_convert("UTC") if close.tzinfo else close.tz_localize("UTC")
    return close.tz_localize(None)


def repo_path(value: str | Path) -> Path:
    p = Path(value)
    return p if p.is_absolute() else REPO_ROOT / p


def load_follow_events(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_parquet(path)
    needed = {"ticker", "available_from_ts", "manager_cik", "cohort_rank_bucket"}
    missing = needed - set(df.columns)
    if missing:
        raise ValueError(f"follow_events missing columns: {sorted(missing)}")
    df["available_from_ts"] = pd.to_datetime(df["available_from_ts"], errors="coerce", utc=True).dt.tz_convert(None)
    df["ticker"] = df["ticker"].astype(str).str.upper().str.strip()
    df["manager_cik"] = df["manager_cik"].astype(str).str.strip()
    df["cohort_rank_bucket"] = df["cohort_rank_bucket"].astype(str)
    return df[df["available_from_ts"].notna() & df["ticker"].ne("") & df["manager_cik"].ne("")]


def load_candidate_dates(path: Path) -> list[pd.Timestamp]:
    df = pd.read_csv(path, usecols=["rebalance_date"], low_memory=False) if path.exists() else pd.DataFrame()
    if df.empty:
        return []
    dates = pd.to_datetime(df["rebalance_date"], errors="coerce").dropna().dt.normalize().unique()
    return sorted(pd.Timestamp(d) for d in dates)


def aggregate_per_date(events: pd.DataFrame, dates: list[pd.Timestamp], lookback_days: int) -> pd.DataFrame:
    if events.empty or not dates:
        return pd.DataFrame(columns=[
            "rebalance_date", "ticker",
            "top3_manager_count", "top7_manager_count", "top10_manager_count",
            "top7_discovery_score", "top_manager_discovery_score",
            "latest_top_manager_available_from",
        ])
    # top7 bucket includes ranks 4-7; top3 includes ranks 1-3; both are part of "top7-or-better".
    # For the count we want: top3 = bucket in {top3}; top7 = bucket in {top3, top7}; top10 = all.
    events = events.copy()
    events["_is_top3"] = events["cohort_rank_bucket"].eq("top3")
    events["_is_top7"] = events["cohort_rank_bucket"].isin({"top3", "top7"})
    events["_is_top10"] = events["cohort_rank_bucket"].isin({"top3", "top7", "top10"})
    out_rows: list[dict[str, Any]] = []
    lookback = pd.Timedelta(days=int(lookback_days))
    for d in dates:
        as_of = decision_close_utc_naive(pd.Timestamp(d))
        floor = as_of - lookback
        window = events[(events["available_from_ts"] > floor) & (events["available_from_ts"] <= as_of)]
        if window.empty:
            continue
        # Per ticker: distinct manager CIK counts in each bucket.
        grouped = window.groupby("ticker", sort=False)
        for ticker, g in grouped:
            top3 = int(g.loc[g["_is_top3"], "manager_cik"].nunique())
            top7 = int(g.loc[g["_is_top7"], "manager_cik"].nunique())
            top10 = int(g.loc[g["_is_top10"], "manager_cik"].nunique())
            if top10 == 0:
                continue
            latest = g["available_from_ts"].max()
            out_rows.append({
                "rebalance_date": pd.Timestamp(d).normalize(),
                "ticker": ticker,
                "top3_manager_count": top3,
                "top7_manager_count": top7,
                "top10_manager_count": top10,
                "top7_discovery_score": float(math.log1p(top7) / math.log1p(7.0)),
                "top_manager_discovery_score": float(math.log1p(top10) / math.log1p(10.0)),
                "latest_top_manager_available_from": latest.isoformat() if pd.notna(latest) else "",
            })
    if not out_rows:
        return pd.DataFrame(columns=[
            "rebalance_date", "ticker",
            "top3_manager_count", "top7_manager_count", "top10_manager_count",
            "top7_discovery_score", "top_manager_discovery_score",
            "latest_top_manager_available_from",
        ])
    return pd.DataFrame(out_rows).sort_values(["rebalance_date", "ticker"]).reset_index(drop=True)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--follow-events", default="data_pit/sec/top_manager_13f_follow_events.parquet")
    p.add_argument("--candidate-book", default="outputs/reports/candidate_replay_book.csv")
    p.add_argument("--output", default="data_pit/sec/top_manager_discovery_signals.parquet")
    p.add_argument("--lookback-days", type=int, default=252,
                   help="Discovery lookback window per rebalance date (default 252d=1y).")
    p.add_argument("--summary-output", default="outputs/top_manager_discovery_signals_summary.json")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    events_path = repo_path(args.follow_events)
    book_path = repo_path(args.candidate_book)
    out_path = repo_path(args.output)
    summary_path = repo_path(args.summary_output)

    events = load_follow_events(events_path)
    dates = load_candidate_dates(book_path)
    print(f"[top-manager-discovery] follow_events_rows={len(events)}  candidate_dates={len(dates)}  lookback_days={args.lookback_days}")

    signals = aggregate_per_date(events, dates, args.lookback_days)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    signals.to_parquet(out_path, index=False)

    summary = {
        "rows": int(len(signals)),
        "unique_tickers": int(signals["ticker"].nunique()) if not signals.empty else 0,
        "unique_dates": int(signals["rebalance_date"].nunique()) if not signals.empty else 0,
        "top7_score_mean": float(signals["top7_discovery_score"].mean()) if not signals.empty else 0.0,
        "top10_score_mean": float(signals["top_manager_discovery_score"].mean()) if not signals.empty else 0.0,
        "follow_events_rows": int(len(events)),
        "candidate_dates_count": int(len(dates)),
        "lookback_days": int(args.lookback_days),
        "output": str(out_path),
    }
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    import json as _json
    summary_path.write_text(_json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(f"[top-manager-discovery] wrote {out_path}  rows={summary['rows']}  tickers={summary['unique_tickers']}  dates={summary['unique_dates']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
