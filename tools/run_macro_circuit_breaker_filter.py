#!/usr/bin/env python3
"""SPY 200-day MA macro circuit breaker filter for operating target books.

Iteration 2 of the overnight attribution loop. Targets the high-severity
F1_mdd_dominated_by_unrealized_holdings_concentrated finding from the
attribution analysis: 97.8% of the concentrated MDD (2020-02-19 to
2020-03-16, -36.74%) was unrealized loss on still-held positions.
Iteration 1 (neutral-regime churn filter) was reverted as a directional
miss; it cost 1.4pp CAGR while making MaxDD marginally worse.

Hypothesis (winners-safe by construction):
    When SPY closes below its 200-day moving average for 3+ consecutive
    days, the market is in a confirmed bearish regime. Mebane Faber
    (2007) and decades of subsequent literature show this regime
    indicator catches major drawdowns (2000, 2008, 2020, 2022) without
    triggering on individual-stock shakeouts. While the indicator says
    "crisis on", multiply every non-cash position weight by halve_factor
    (default 0.5) in the operating target book. When SPY closes back
    above its 200-day MA for 3+ consecutive days, restore full weights.

Why this is winners-safe:
    NVDA / SMCI / MU style single-name shakeouts do NOT move SPY's
    200-day MA. The filter triggers only on broad market regime.
    During a confirmed crisis the engine holds the same names — just
    at half the weight. When the regime ends, full weights resume.
    No mechanical -X% per-position stop. No re-entry lottery.

Outputs (parallel to existing operating books):
    outputs/reports/operating_<kind>_target_book_macro_filtered.csv
    outputs/macro_circuit_filter/<kind>/diagnostics.json

The downstream broker-ledger replay runs against both the original and
filtered books so the attribution tool can measure the delta.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.run_weekly_evaluation import load_price_series  # noqa: E402

CASH_TICKERS = {"CASH", "__CASH__"}
DEFAULT_MA_WINDOW = 200
DEFAULT_CONFIRM_DAYS = 3
DEFAULT_HALVE_FACTOR = 0.5
DEFAULT_SPY_TICKERS = ("SPY", "^GSPC", "^SPX")


def repo_path(path_like: str | Path) -> Path:
    path = Path(path_like)
    return path if path.is_absolute() else REPO_ROOT / path


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def load_spy_prices(price_cache: Path, candidates: tuple[str, ...] = DEFAULT_SPY_TICKERS) -> tuple[pd.DataFrame, str]:
    for ticker in candidates:
        series = load_price_series(price_cache, ticker)
        if not series.empty:
            return series, ticker
    return pd.DataFrame(), ""


def compute_crisis_series(
    spy_prices: pd.DataFrame,
    *,
    ma_window: int = DEFAULT_MA_WINDOW,
    confirm_days: int = DEFAULT_CONFIRM_DAYS,
) -> pd.Series:
    """Compute a date-indexed boolean Series: True when crisis-on.

    Crisis-on state machine:
        IDLE -> CRISIS:
            SPY closed below its `ma_window`-day moving average for
            `confirm_days` consecutive trading days.
        CRISIS -> IDLE:
            SPY closed above its `ma_window`-day moving average for
            `confirm_days` consecutive trading days.

    The state is sticky between confirmations to avoid whipsaw on
    single-day crosses.
    """
    if spy_prices.empty or "close" not in spy_prices.columns:
        return pd.Series(dtype=bool)
    idx = pd.DatetimeIndex(spy_prices.index).tz_localize(None).normalize()
    close = pd.to_numeric(spy_prices["close"], errors="coerce")
    df = pd.DataFrame({"close": close.values}, index=idx).dropna().sort_index()
    if df.empty:
        return pd.Series(dtype=bool)
    df["ma"] = df["close"].rolling(int(ma_window), min_periods=int(ma_window)).mean()
    df["below"] = df["close"] < df["ma"]
    state = False
    streak_below = 0
    streak_above = 0
    out: list[bool] = []
    for is_below_raw, ma in zip(df["below"].values, df["ma"].values):
        # Before MA is defined, no crisis state.
        if not np.isfinite(ma):
            streak_below = 0
            streak_above = 0
            out.append(False)
            continue
        if bool(is_below_raw):
            streak_below += 1
            streak_above = 0
            if not state and streak_below >= int(confirm_days):
                state = True
        else:
            streak_above += 1
            streak_below = 0
            if state and streak_above >= int(confirm_days):
                state = False
        out.append(state)
    return pd.Series(out, index=df.index, dtype=bool)


def crisis_at(crisis_series: pd.Series, date: pd.Timestamp) -> bool:
    """Look up crisis status at or before the given date. Defaults to
    False if the series predates the date or is empty.
    """
    if crisis_series.empty:
        return False
    idx = crisis_series.index
    pos = idx.searchsorted(pd.Timestamp(date), side="right") - 1
    if pos < 0:
        return False
    return bool(crisis_series.iloc[pos])


def apply_filter(
    book: pd.DataFrame,
    crisis_series: pd.Series,
    *,
    halve_factor: float = DEFAULT_HALVE_FACTOR,
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    if book.empty or "rebalance_date" not in book.columns or "weight" not in book.columns:
        return book, []
    out = book.copy()
    out["rebalance_date"] = pd.to_datetime(out["rebalance_date"], errors="coerce")
    out = out.dropna(subset=["rebalance_date"])
    out["ticker"] = out["ticker"].astype(str).str.upper().str.strip()
    decisions: list[dict[str, Any]] = []
    for date in sorted(out["rebalance_date"].unique()):
        in_crisis = crisis_at(crisis_series, pd.Timestamp(date))
        if not in_crisis:
            decisions.append({
                "rebalance_date": pd.Timestamp(date).date().isoformat(),
                "in_crisis": False,
                "halve_factor": 1.0,
                "rows_affected": 0,
            })
            continue
        mask = (out["rebalance_date"] == date) & (~out["ticker"].isin(CASH_TICKERS))
        rows_affected = int(mask.sum())
        out.loc[mask, "weight"] = out.loc[mask, "weight"] * float(halve_factor)
        decisions.append({
            "rebalance_date": pd.Timestamp(date).date().isoformat(),
            "in_crisis": True,
            "halve_factor": float(halve_factor),
            "rows_affected": rows_affected,
        })
    return out, decisions


def run(
    *,
    input_book: Path,
    output_book: Path,
    diagnostics_path: Path,
    price_cache: Path,
    ma_window: int = DEFAULT_MA_WINDOW,
    confirm_days: int = DEFAULT_CONFIRM_DAYS,
    halve_factor: float = DEFAULT_HALVE_FACTOR,
    spy_candidates: tuple[str, ...] = DEFAULT_SPY_TICKERS,
) -> dict[str, Any]:
    if not input_book.exists():
        payload = {
            "status": "blocked",
            "reason": f"input book not found: {input_book}",
            "input_book": str(input_book),
        }
        write_json(diagnostics_path, payload)
        return payload
    book = pd.read_csv(input_book, low_memory=False)
    if book.empty:
        payload = {"status": "blocked", "reason": "empty input book", "input_book": str(input_book)}
        write_json(diagnostics_path, payload)
        return payload
    spy_prices, spy_ticker_used = load_spy_prices(price_cache, spy_candidates)
    if spy_prices.empty:
        payload = {
            "status": "blocked",
            "reason": f"SPY price series not found in price cache; tried {list(spy_candidates)}",
            "price_cache": str(price_cache),
        }
        write_json(diagnostics_path, payload)
        return payload
    crisis_series = compute_crisis_series(spy_prices, ma_window=ma_window, confirm_days=confirm_days)
    filtered, decisions = apply_filter(book, crisis_series, halve_factor=halve_factor)
    output_book.parent.mkdir(parents=True, exist_ok=True)
    out_for_csv = filtered.copy()
    if "rebalance_date" in out_for_csv.columns:
        out_for_csv["rebalance_date"] = pd.to_datetime(out_for_csv["rebalance_date"], errors="coerce").dt.date.astype(str)
    out_for_csv.to_csv(output_book, index=False)
    n_crisis_dates = sum(1 for d in decisions if d.get("in_crisis"))
    n_total_dates = len(decisions)
    weight_dropped = float(
        book["weight"].astype(float).sum() - filtered["weight"].astype(float).sum()
    )
    crisis_windows = _summarize_crisis_windows(crisis_series)
    payload = {
        "status": "completed",
        "schema_version": "macro-circuit-breaker-filter-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "input_book": str(input_book),
        "output_book": str(output_book),
        "price_cache": str(price_cache),
        "spy_ticker_used": spy_ticker_used,
        "ma_window": int(ma_window),
        "confirm_days": int(confirm_days),
        "halve_factor": float(halve_factor),
        "rebalance_dates_total": n_total_dates,
        "rebalance_dates_in_crisis": n_crisis_dates,
        "crisis_share": float(n_crisis_dates / n_total_dates) if n_total_dates else 0.0,
        "weight_dropped_total": weight_dropped,
        "crisis_windows_sample": crisis_windows[:20],
        "decisions_sample": decisions[:30],
        "research_only": True,
        "production_activation_allowed": False,
    }
    write_json(diagnostics_path, payload)
    return payload


def _summarize_crisis_windows(crisis_series: pd.Series) -> list[dict[str, Any]]:
    """Return contiguous (start, end, duration_days) crisis windows."""
    if crisis_series.empty:
        return []
    windows: list[dict[str, Any]] = []
    in_window = False
    start: pd.Timestamp | None = None
    last: pd.Timestamp | None = None
    for date, is_crisis in crisis_series.items():
        if bool(is_crisis):
            if not in_window:
                start = pd.Timestamp(date)
                in_window = True
            last = pd.Timestamp(date)
        else:
            if in_window:
                windows.append({
                    "start": start.date().isoformat() if start else None,
                    "end": last.date().isoformat() if last else None,
                    "duration_days": int((last - start).days + 1) if (start and last) else 0,
                })
                in_window = False
                start = None
                last = None
    if in_window and start and last:
        windows.append({
            "start": start.date().isoformat(),
            "end": last.date().isoformat(),
            "duration_days": int((last - start).days + 1),
        })
    return windows


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-book", required=True)
    parser.add_argument("--output-book", required=True)
    parser.add_argument("--diagnostics", required=True)
    parser.add_argument("--price-cache", default="cache_prices")
    parser.add_argument("--ma-window", type=int, default=DEFAULT_MA_WINDOW)
    parser.add_argument("--confirm-days", type=int, default=DEFAULT_CONFIRM_DAYS)
    parser.add_argument("--halve-factor", type=float, default=DEFAULT_HALVE_FACTOR)
    parser.add_argument("--spy-candidates", nargs="+", default=list(DEFAULT_SPY_TICKERS))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = run(
        input_book=repo_path(args.input_book),
        output_book=repo_path(args.output_book),
        diagnostics_path=repo_path(args.diagnostics),
        price_cache=repo_path(args.price_cache),
        ma_window=args.ma_window,
        confirm_days=args.confirm_days,
        halve_factor=args.halve_factor,
        spy_candidates=tuple(args.spy_candidates),
    )
    print(json.dumps({k: v for k, v in payload.items() if k != "decisions_sample"}, indent=2, default=str))
    return 0 if payload.get("status") == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
