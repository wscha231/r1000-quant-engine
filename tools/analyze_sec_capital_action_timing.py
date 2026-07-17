#!/usr/bin/env python3
"""Diagnose pre-pricing and delayed returns around SEC capital-action filings.

The input is the frozen exact-accepted capital-allocation event sidecar.  This
tool is descriptive only: it does not change the event classification or
authorize a portfolio arm.  A Companyfacts filing can repeat an action first
announced elsewhere, so the output explicitly does not claim first disclosure.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import tools.run_sec_capital_allocation_event as capital  # noqa: E402
import tools.run_sec_filing_quality_event as quality  # noqa: E402


PRE_HORIZONS = (5, 21, 63)
POST_HORIZONS = (1, 5, 21, 63, 126, 252, 504)


def _return_between(series: pd.Series, dates: list[pd.Timestamp], start: int, end: int) -> float:
    if start < 0 or end >= len(dates) or start >= end:
        return np.nan
    start_date, end_date = dates[start], dates[end]
    if start_date not in series.index or end_date not in series.index:
        return np.nan
    first, last = float(series.loc[start_date]), float(series.loc[end_date])
    return float(last / first - 1.0) if np.isfinite(first) and np.isfinite(last) and first > 0 else np.nan


def build_timing_rows(events: pd.DataFrame, prices: pd.DataFrame) -> pd.DataFrame:
    required = {"ticker", "accepted_at", "available_from", "sec_capital_allocation_event"}
    missing = required - set(events.columns)
    if missing:
        raise quality.DataContractError(f"event sidecar missing columns: {sorted(missing)}")
    adjusted = prices[["ticker", "date", "adjusted_close"]].copy()
    adjusted["date"] = pd.to_datetime(adjusted["date"], errors="coerce").dt.normalize()
    groups = {
        ticker: frame.set_index("date")["adjusted_close"].sort_index()
        for ticker, frame in adjusted.groupby("ticker", sort=False)
    }
    spy = groups.get("SPY")
    if spy is None or spy.empty:
        raise quality.DataContractError("SPY adjusted-close history is required")
    close_map = quality.nyse_market_close_map(list(spy.index) + events["accepted_at"].tolist())
    sessions = sorted((pd.Timestamp(date).normalize(), close) for date, close in close_map.items())
    dates = [date for date, _ in sessions]
    close_ns = np.asarray([int(close.value) for _, close in sessions], dtype=np.int64)

    rows: list[dict[str, Any]] = []
    for event in events.itertuples(index=False):
        row = event._asdict()
        accepted = quality.parse_utc(row["accepted_at"])
        ticker = str(row["ticker"]).upper()
        stock = groups.get(ticker)
        row["anchor_date"] = ""
        row["entry_date"] = ""
        for horizon in PRE_HORIZONS:
            row[f"pre_{horizon}d_return"] = np.nan
            row[f"pre_{horizon}d_spy_excess"] = np.nan
        for label in ("reaction",):
            row[f"{label}_return"] = np.nan
            row[f"{label}_spy_excess"] = np.nan
        for horizon in POST_HORIZONS:
            row[f"post_{horizon}d_return"] = np.nan
            row[f"post_{horizon}d_spy_excess"] = np.nan
        if stock is not None and pd.notna(accepted):
            anchor = int(np.searchsorted(close_ns, int(accepted.value), side="right") - 1)
            entry = int(np.searchsorted(close_ns, int(accepted.value), side="right"))
            if anchor >= 0 and entry < len(dates):
                row["anchor_date"] = dates[anchor].date().isoformat()
                row["entry_date"] = dates[entry].date().isoformat()
                reaction = _return_between(stock, dates, anchor, entry)
                spy_reaction = _return_between(spy, dates, anchor, entry)
                row["reaction_return"] = reaction
                row["reaction_spy_excess"] = reaction - spy_reaction if np.isfinite(reaction) and np.isfinite(spy_reaction) else np.nan
                for horizon in PRE_HORIZONS:
                    stock_return = _return_between(stock, dates, anchor - horizon, anchor)
                    spy_return = _return_between(spy, dates, anchor - horizon, anchor)
                    row[f"pre_{horizon}d_return"] = stock_return
                    row[f"pre_{horizon}d_spy_excess"] = stock_return - spy_return if np.isfinite(stock_return) and np.isfinite(spy_return) else np.nan
                for horizon in POST_HORIZONS:
                    stock_return = _return_between(stock, dates, entry, entry + horizon)
                    spy_return = _return_between(spy, dates, entry, entry + horizon)
                    row[f"post_{horizon}d_return"] = stock_return
                    row[f"post_{horizon}d_spy_excess"] = stock_return - spy_return if np.isfinite(stock_return) and np.isfinite(spy_return) else np.nan
        rows.append(row)
    result = pd.DataFrame(rows)
    accepted = pd.to_datetime(result["accepted_at"], errors="coerce", utc=True)
    result["segment_full"] = True
    result["segment_oos2"] = accepted.ge(quality.parse_utc(capital.OOS2_START))
    result["segment_oos"] = accepted.ge(quality.parse_utc(capital.OOS_START))
    result["first_disclosure_clean"] = False
    result["timing_caveat"] = "Companyfacts filing may repeat an action announced or executed before accepted_at"
    return result


def _metric(frame: pd.DataFrame, column: str) -> dict[str, Any]:
    positive = pd.to_numeric(frame.loc[frame["sec_capital_allocation_event"].eq("positive"), column], errors="coerce").dropna()
    negative = pd.to_numeric(frame.loc[frame["sec_capital_allocation_event"].eq("negative"), column], errors="coerce").dropna()
    return {
        "positive_count": int(len(positive)),
        "negative_count": int(len(negative)),
        "positive_mean": float(positive.mean()) if not positive.empty else None,
        "negative_mean": float(negative.mean()) if not negative.empty else None,
        "positive_median": float(positive.median()) if not positive.empty else None,
        "negative_median": float(negative.median()) if not negative.empty else None,
        "positive_minus_negative_mean": float(positive.mean() - negative.mean()) if not positive.empty and not negative.empty else None,
    }


def summarize(rows: pd.DataFrame) -> dict[str, Any]:
    metrics: dict[str, Any] = {}
    columns = [*(f"pre_{h}d_spy_excess" for h in PRE_HORIZONS), "reaction_spy_excess", *(f"post_{h}d_spy_excess" for h in POST_HORIZONS)]
    for segment in ("full", "oos2", "oos"):
        scoped = rows[rows[f"segment_{segment}"]].copy()
        metrics[segment] = {column: _metric(scoped, column) for column in columns}
    pre = metrics["oos"]["pre_21d_spy_excess"]
    reaction = metrics["oos"]["reaction_spy_excess"]
    post = metrics["oos"]["post_63d_spy_excess"]
    positive_prepriced_pattern = bool(
        pre["positive_mean"] is not None
        and post["positive_mean"] is not None
        and pre["positive_mean"] > 0
        and post["positive_mean"] < 0
    )
    return {
        "status": "DESCRIPTIVE_ONLY",
        "event_count": int(len(rows)),
        "first_disclosure_clean": False,
        "portfolio_signal_authorized": False,
        "positive_prepriced_pattern_oos": positive_prepriced_pattern,
        "oos_positive_pre21_mean": pre["positive_mean"],
        "oos_positive_reaction_mean": reaction["positive_mean"],
        "oos_positive_post63_mean": post["positive_mean"],
        "metrics": metrics,
        "interpretation_rule": "pre-event strength plus post-event weakness is consistent with pre-pricing but does not prove first disclosure",
        "research_only": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", default="outputs/sec_capital_allocation_event_20260717/sec_capital_allocation_events.parquet")
    parser.add_argument("--prices", default=r"H:\codex\tmp_r1000_grossfloor_20260625\outputs\run287_price_cache_full_candidate\cache_prices")
    parser.add_argument("--output-dir", default="outputs/sec_capital_allocation_timing_20260717")
    args = parser.parse_args()
    events_path = quality.repo_path(args.events)
    events = quality.read_table(events_path)
    prices = capital.load_price_cache(args.prices, sorted(set(events["ticker"]) | {"SPY"}))
    rows = build_timing_rows(events, prices)
    summary = summarize(rows)
    output = quality.repo_path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    rows_path = output / "event_timing_rows.parquet"
    csv_path = output / "event_timing_rows.csv"
    summary_path = output / "summary.json"
    rows.to_parquet(rows_path, index=False)
    rows.to_csv(csv_path, index=False)
    summary.update(
        {
            "input_events_sha256": quality.sha256_file(events_path),
            "producer_sha256": quality.sha256_file(Path(__file__)),
            "paths": {"rows": str(rows_path), "rows_csv": str(csv_path), "summary": str(summary_path)},
        }
    )
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
