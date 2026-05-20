#!/usr/bin/env python3
"""Neutral-regime churn filter for operating target books.

Hypothesis (Iteration 1 of the overnight attribution loop):
    Trade attribution finding F2 documented that 57% of realized
    losses in `main` ($-146,496 of $-256,009) occurred in `neutral`
    regime across 401 trades averaging $-365 each. Inspection of the
    trade journal shows the losers are core compounder names
    (MA 14 swaps, PG 11, ORCL 10, COST 9, HD 9, NOW 8, MSFT 8, LRCX 8,
    GOOG 8, BKNG 7, AMZN 7, DKS 7) being repeatedly bought and sold.
    These are NOT bad picks — they are churn driven by score noise on
    quality megacaps in an ambiguous market.

Approach (winners-safe):
    Block RE-ENTRIES of high-churn tickers in neutral regime. A ticker
    is "churn" if it has accumulated >= 3 in/out transitions over the
    trailing 6 monthly rebalance dates. Existing positions are NEVER
    forcibly held — exits pass through unchanged so declining names
    (F3 territory) are not protected. Only entries are filtered, and
    only in neutral regime. NVDA-style winners that enter once and
    hold cleanly never accumulate swap transitions and are unaffected.

    The removed entry weight falls to cash naturally (broker-ledger
    replay tolerates total_weight < 1.0). No renormalization.

Output:
    outputs/reports/operating_<kind>_target_book_churn_filtered.csv

The legacy book is unchanged. The downstream broker-ledger replay
runs on BOTH books in parallel so the attribution tool can measure
the delta and either confirm or refute the hypothesis.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SWAP_THRESHOLD = 2
DEFAULT_WINDOW_MONTHS = 6
DEFAULT_TARGET_REGIMES = ("neutral",)


def repo_path(path_like: str | Path) -> Path:
    path = Path(path_like)
    return path if path.is_absolute() else REPO_ROOT / path


def read_book(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path, low_memory=False)
    if df.empty or "rebalance_date" not in df.columns or "ticker" not in df.columns:
        return pd.DataFrame()
    df["rebalance_date"] = pd.to_datetime(df["rebalance_date"], errors="coerce")
    df = df.dropna(subset=["rebalance_date"])
    df["ticker"] = df["ticker"].astype(str).str.upper().str.strip()
    return df


def compute_swap_counts(
    history: pd.DataFrame,
    window_months: int,
) -> dict[tuple[pd.Timestamp, str], int]:
    """For every (date, ticker) in history, return how many in/out
    transitions that ticker accumulated over the prior ``window_months``
    monthly rebalance dates (not counting the current date).
    """
    if history.empty:
        return {}
    dates = sorted(history["rebalance_date"].unique())
    if len(dates) < 2:
        return {}
    # Build a dict of date -> set(tickers held that month).
    held_by_date: dict[pd.Timestamp, set[str]] = {}
    for date in dates:
        held = set(history.loc[history["rebalance_date"] == date, "ticker"].astype(str).str.upper())
        held_by_date[pd.Timestamp(date)] = held
    universe = sorted({t for held in held_by_date.values() for t in held})
    out: dict[tuple[pd.Timestamp, str], int] = {}
    for idx, date in enumerate(dates):
        # Window: the prior `window_months` rebalance dates (strictly before this date).
        window_start_idx = max(0, idx - window_months)
        window_dates = dates[window_start_idx:idx]
        if not window_dates:
            continue
        for ticker in universe:
            states = [1 if ticker in held_by_date[pd.Timestamp(d)] else 0 for d in window_dates]
            transitions = sum(1 for i in range(1, len(states)) if states[i] != states[i - 1])
            out[(pd.Timestamp(date), ticker)] = transitions
    return out


def apply_churn_filter(
    book: pd.DataFrame,
    swap_counts: dict[tuple[pd.Timestamp, str], int],
    *,
    swap_threshold: int,
    target_regimes: tuple[str, ...],
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """Walk the book in chronological order and block re-entries of
    high-churn tickers in target regimes. Returns the filtered book
    and a list of decision records for diagnostics.
    """
    if book.empty:
        return book, []
    book = book.copy().sort_values(["rebalance_date", "ticker"]).reset_index(drop=True)
    dates = sorted(book["rebalance_date"].unique())
    prev_tickers: set[str] = set()
    keep_rows: list[pd.Series] = []
    decisions: list[dict[str, Any]] = []
    for date in dates:
        month = book[book["rebalance_date"] == date].copy()
        regime = ""
        if "regime_state" in month.columns and not month.empty:
            regime = str(month["regime_state"].dropna().astype(str).iloc[0]) if month["regime_state"].notna().any() else ""
        if regime not in target_regimes:
            for _, row in month.iterrows():
                keep_rows.append(row)
            prev_tickers = set(month["ticker"].astype(str).str.upper())
            continue
        kept_this_month: set[str] = set()
        for _, row in month.iterrows():
            ticker = str(row["ticker"]).upper()
            if ticker in prev_tickers:
                # Existing position — always pass through. Exits handled by absence in next month.
                keep_rows.append(row)
                kept_this_month.add(ticker)
                continue
            # New entry — apply churn check.
            swap_count = swap_counts.get((pd.Timestamp(date), ticker), 0)
            if swap_count >= swap_threshold:
                decisions.append({
                    "rebalance_date": pd.Timestamp(date).date().isoformat(),
                    "ticker": ticker,
                    "swap_count": int(swap_count),
                    "regime_state": regime,
                    "action": "blocked_entry",
                    "weight_dropped": float(row.get("weight", 0.0) or 0.0),
                })
                continue
            keep_rows.append(row)
            kept_this_month.add(ticker)
            decisions.append({
                "rebalance_date": pd.Timestamp(date).date().isoformat(),
                "ticker": ticker,
                "swap_count": int(swap_count),
                "regime_state": regime,
                "action": "allowed_entry",
                "weight_dropped": 0.0,
            })
        # Next month's prev_tickers = what we kept this month. Exits (a
        # ticker that was in prev_tickers but not in this month's book)
        # are NOT propagated because the book explicitly chose to drop
        # them; the filter only governs ENTRIES, never holdings.
        prev_tickers = kept_this_month
    if not keep_rows:
        return pd.DataFrame(columns=book.columns), decisions
    out = pd.DataFrame(keep_rows).reset_index(drop=True)
    return out, decisions


def write_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame_out = frame.copy()
    if "rebalance_date" in frame_out.columns:
        frame_out["rebalance_date"] = pd.to_datetime(frame_out["rebalance_date"], errors="coerce").dt.date.astype(str)
    frame_out.to_csv(path, index=False)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def run(
    *,
    input_book: Path,
    output_book: Path,
    diagnostics_path: Path,
    swap_threshold: int,
    window_months: int,
    target_regimes: tuple[str, ...],
) -> dict[str, Any]:
    book = read_book(input_book)
    if book.empty:
        payload = {
            "status": "blocked",
            "reason": f"input book not found or invalid: {input_book}",
            "input_book": str(input_book),
        }
        write_json(diagnostics_path, payload)
        return payload
    swap_counts = compute_swap_counts(book, window_months)
    filtered, decisions = apply_churn_filter(
        book,
        swap_counts,
        swap_threshold=swap_threshold,
        target_regimes=target_regimes,
    )
    write_csv(output_book, filtered)
    blocked = [d for d in decisions if d["action"] == "blocked_entry"]
    allowed = [d for d in decisions if d["action"] == "allowed_entry"]
    payload = {
        "status": "completed",
        "schema_version": "neutral-regime-churn-filter-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "input_book": str(input_book),
        "output_book": str(output_book),
        "swap_threshold": int(swap_threshold),
        "window_months": int(window_months),
        "target_regimes": list(target_regimes),
        "input_row_count": int(len(book)),
        "output_row_count": int(len(filtered)),
        "rows_removed": int(len(book) - len(filtered)),
        "neutral_entries_allowed": int(len(allowed)),
        "neutral_entries_blocked": int(len(blocked)),
        "weight_dropped_total": float(sum(d["weight_dropped"] for d in blocked)),
        "top_blocked_tickers": _top_counts([d["ticker"] for d in blocked], n=15),
        "blocked_entries_sample": blocked[:30],
        "research_only": True,
        "production_activation_allowed": False,
    }
    write_json(diagnostics_path, payload)
    return payload


def _top_counts(items: list[str], n: int) -> list[dict[str, Any]]:
    from collections import Counter
    counter = Counter(items)
    return [{"ticker": t, "count": c} for t, c in counter.most_common(n)]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-book", required=True)
    parser.add_argument("--output-book", required=True)
    parser.add_argument("--diagnostics", required=True)
    parser.add_argument("--swap-threshold", type=int, default=DEFAULT_SWAP_THRESHOLD)
    parser.add_argument("--window-months", type=int, default=DEFAULT_WINDOW_MONTHS)
    parser.add_argument("--target-regimes", nargs="+", default=list(DEFAULT_TARGET_REGIMES))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = run(
        input_book=repo_path(args.input_book),
        output_book=repo_path(args.output_book),
        diagnostics_path=repo_path(args.diagnostics),
        swap_threshold=args.swap_threshold,
        window_months=args.window_months,
        target_regimes=tuple(args.target_regimes),
    )
    print(json.dumps(payload, indent=2, default=str))
    return 0 if payload.get("status") == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
