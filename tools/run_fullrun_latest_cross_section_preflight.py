#!/usr/bin/env python3
"""Fail-loud preflight for a fullrun's latest accepted-close cross-section.

This verifies research outputs only.  It does not execute the daily selector,
mutate accepted paper state, run a broker ledger, promote a challenger, or
enable production/live trading.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from datetime import timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import pandas_market_calendars as mcal

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.run_weekly_evaluation import load_price_series  # noqa: E402


SCHEMA_VERSION = "run287-fullrun-latest-cross-section-preflight-v3"
CASH_TICKERS = {"CASH", "USD", "__CASH__", "BIL", "SHV", "SGOV"}
INVALID_TICKERS = {"", "N/A", "NA", "NAN", "NONE", "NULL", "UNKNOWN"}


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def sha256(path: Path) -> str:
    if not path.is_file():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_csv(path: Path) -> pd.DataFrame:
    if not path.is_file() or path.stat().st_size == 0:
        return pd.DataFrame()
    try:
        return pd.read_csv(path, low_memory=False)
    except Exception:
        return pd.DataFrame()


def bool_series(values: pd.Series) -> pd.Series:
    if values.dtype == bool:
        return values.fillna(False)
    return values.astype(str).str.strip().str.lower().isin({"1", "true", "yes"})


def ticker_series(values: pd.Series) -> pd.Series:
    return values.fillna("").astype(str).str.upper().str.strip()


def date_series(frame: pd.DataFrame) -> pd.Series:
    for column in ("rebalance_date", "feature_date", "as_of_date", "date", "Date"):
        if column in frame.columns:
            return pd.to_datetime(frame[column], errors="coerce").dt.normalize()
    return pd.Series(pd.NaT, index=frame.index, dtype="datetime64[ns]")


def actual_close(valuation_date: str) -> pd.Timestamp:
    date = pd.Timestamp(valuation_date).normalize()
    schedule = mcal.get_calendar("NYSE").schedule(start_date=date, end_date=date)
    if len(schedule) != 1:
        raise ValueError(f"valuation date is not an NYSE session: {valuation_date}")
    close = pd.Timestamp(schedule.iloc[0]["market_close"])
    return close.tz_convert("UTC") if close.tzinfo else close.tz_localize("UTC")


def is_month_end_session(valuation_date: str) -> bool:
    date = pd.Timestamp(valuation_date).normalize()
    schedule = mcal.get_calendar("NYSE").schedule(
        start_date=date + timedelta(days=1), end_date=date + timedelta(days=10)
    )
    if schedule.empty:
        raise ValueError("unable to resolve the next NYSE session")
    next_session = pd.Timestamp(schedule.index[0]).tz_localize(None)
    return next_session.month != date.month


def provenance_failures(
    frame: pd.DataFrame,
    *,
    label: str,
    valuation_date: str,
    close: pd.Timestamp,
    decision_time: pd.Timestamp,
) -> list[str]:
    failures: list[str] = []
    required = {"ticker", "valuation_price_cutoff_date", "feature_available_from"}
    missing = sorted(required - set(frame.columns))
    if missing:
        return [f"{label}_missing_columns:{','.join(missing)}"]
    valuation = pd.to_datetime(frame["valuation_price_cutoff_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    if not valuation.eq(valuation_date).all():
        failures.append(f"{label}_valuation_date_mismatch_rows:{int((~valuation.eq(valuation_date)).sum())}")
    available = pd.to_datetime(frame["feature_available_from"], errors="coerce", utc=True)
    if available.isna().any():
        failures.append(f"{label}_feature_available_from_missing_rows:{int(available.isna().sum())}")
    exact = available.eq(close)
    if not exact.all():
        failures.append(f"{label}_feature_available_from_close_mismatch_rows:{int((~exact).sum())}")
    future = available.gt(decision_time)
    if future.any():
        failures.append(f"{label}_feature_available_after_decision_rows:{int(future.sum())}")
    return failures


def build(args: argparse.Namespace) -> dict[str, Any]:
    latest_run = repo_path(args.latest_run)
    price_cache = repo_path(args.price_cache)
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    valuation_date = pd.Timestamp(args.valuation_date).date().isoformat()
    close = actual_close(valuation_date)
    raw_decision_time = str(args.decision_time_utc or "").strip()
    if not raw_decision_time:
        raise ValueError("decision_time_utc is required and cannot be blank")
    decision_time = pd.to_datetime(raw_decision_time, errors="raise", utc=True)
    if pd.isna(decision_time):
        raise ValueError("decision_time_utc must resolve to a finite timestamp")
    decision_time = pd.Timestamp(decision_time)
    failures: list[str] = []
    if decision_time < close:
        failures.append("decision_time_precedes_session_close")

    paths = {
        "scored_latest": latest_run / "scored_latest.csv",
        "candidate_replay_book": latest_run / "reports" / "candidate_replay_book.csv",
        "main_target_proposal": latest_run / "portfolio_latest.csv",
        "concentrated_target_proposal": latest_run / "concentrated_portfolio_latest.csv",
    }
    frames = {label: read_csv(path) for label, path in paths.items()}
    for label, frame in frames.items():
        if frame.empty:
            failures.append(f"missing_or_empty:{label}")

    scored = frames["scored_latest"].copy()
    if not scored.empty:
        scored_dates = date_series(scored).dt.strftime("%Y-%m-%d")
        if not scored_dates.eq(valuation_date).all():
            failures.append(f"scored_latest_session_mismatch_rows:{int((~scored_dates.eq(valuation_date)).sum())}")
        if len(scored) < int(args.min_scored_rows):
            failures.append(f"scored_latest_below_minimum:{len(scored)}<{int(args.min_scored_rows)}")
        failures.extend(
            provenance_failures(
                scored,
                label="scored_latest",
                valuation_date=valuation_date,
                close=close,
                decision_time=decision_time,
            )
        )

    candidate = frames["candidate_replay_book"].copy()
    candidate_latest = pd.DataFrame()
    if not candidate.empty:
        candidate_dates = date_series(candidate)
        expected = pd.Timestamp(valuation_date)
        candidate_latest = candidate.loc[candidate_dates.eq(expected)].copy()
        if candidate_latest.empty or candidate_dates.max() != expected:
            failures.append("candidate_replay_book_latest_session_mismatch")
        else:
            failures.extend(
                provenance_failures(
                    candidate_latest,
                    label="candidate_replay_book_latest",
                    valuation_date=valuation_date,
                    close=close,
                    decision_time=decision_time,
                )
            )

    eligible = scored.copy()
    if not eligible.empty:
        if "ranking_eligible" not in eligible.columns:
            failures.append("scored_latest_missing_columns:ranking_eligible")
            eligible = eligible.iloc[0:0].copy()
        else:
            eligible = eligible.loc[bool_series(eligible["ranking_eligible"])].copy()
    if "ticker" in eligible.columns:
        eligible["ticker"] = ticker_series(eligible["ticker"])
        invalid_eligible = eligible["ticker"].isin(INVALID_TICKERS)
        if invalid_eligible.any():
            failures.append(f"invalid_eligible_tickers:{int(invalid_eligible.sum())}")
        eligible = eligible.loc[~eligible["ticker"].isin(CASH_TICKERS)].copy()
        duplicate_count = int(eligible["ticker"].duplicated().sum())
        if duplicate_count:
            failures.append(f"duplicate_eligible_tickers:{duplicate_count}")
    else:
        failures.append("scored_latest_missing_columns:ticker")

    candidate_tickers: set[str] = set()
    if "ticker" in candidate_latest.columns:
        candidate_latest["ticker"] = ticker_series(candidate_latest["ticker"])
        invalid_candidate = candidate_latest["ticker"].isin(INVALID_TICKERS)
        if invalid_candidate.any():
            failures.append(
                f"candidate_replay_book_latest_invalid_tickers:{int(invalid_candidate.sum())}"
            )
        duplicate_candidate = int(candidate_latest["ticker"].duplicated().sum())
        if duplicate_candidate:
            failures.append(
                f"candidate_replay_book_latest_duplicate_tickers:{duplicate_candidate}"
            )
        candidate_tickers = set(candidate_latest["ticker"])
    else:
        failures.append("candidate_replay_book_latest_missing_columns:ticker")
    eligible_tickers = set(eligible.get("ticker", pd.Series(dtype=str)))
    missing_candidate_tickers = sorted(eligible_tickers - candidate_tickers)
    if missing_candidate_tickers:
        failures.append(f"eligible_tickers_missing_from_candidate_book:{len(missing_candidate_tickers)}")

    price_rows: list[dict[str, Any]] = []
    for ticker in sorted(eligible_tickers):
        prices = load_price_series(price_cache, ticker)
        exact_date = pd.Timestamp(valuation_date)
        close_value: float | None = None
        if (
            not prices.empty
            and "close" in prices.columns
            and exact_date in prices.index
        ):
            raw_close = prices.loc[exact_date, "close"]
            raw_values = (
                raw_close
                if isinstance(raw_close, pd.Series)
                else pd.Series([raw_close])
            )
            numeric_values = pd.to_numeric(raw_values, errors="coerce")
            valid_values = numeric_values[
                numeric_values.notna()
                & numeric_values.map(
                    lambda value: math.isfinite(float(value)) and float(value) > 0.0
                )
            ]
            if not valid_values.empty:
                close_value = float(valid_values.iloc[-1])
        has_close = close_value is not None
        latest_date = prices.index.max().date().isoformat() if not prices.empty else ""
        price_rows.append(
            {
                "ticker": ticker,
                "exact_close_available": bool(has_close),
                "exact_close_value": close_value,
                "latest_cached_date": latest_date,
            }
        )
    missing_exact_close = [row["ticker"] for row in price_rows if not row["exact_close_available"]]
    if missing_exact_close:
        failures.append(f"eligible_ticker_exact_close_missing:{len(missing_exact_close)}")
    exact_close_tickers = {
        str(row["ticker"])
        for row in price_rows
        if bool(row["exact_close_available"])
    }

    proposal_ready: dict[str, bool] = {}
    proposal_audits: dict[str, dict[str, Any]] = {}
    for label in ("main_target_proposal", "concentrated_target_proposal"):
        frame = frames[label].copy()
        proposal_failures: list[str] = []
        dates = date_series(frame).dt.strftime("%Y-%m-%d") if not frame.empty else pd.Series(dtype=str)
        if frame.empty or not dates.eq(valuation_date).all():
            proposal_failures.append(f"{label}_session_mismatch")
        if not frame.empty:
            proposal_failures.extend(
                provenance_failures(
                    frame,
                    label=label,
                    valuation_date=valuation_date,
                    close=close,
                    decision_time=decision_time,
                )
            )

        proposal_tickers: set[str] = set()
        invalid_tickers: list[str] = []
        duplicate_tickers: list[str] = []
        unexpected_tickers: list[str] = []
        proposal_missing_exact_close: list[str] = []
        if "ticker" not in frame.columns:
            proposal_failures.append(f"{label}_missing_columns:ticker")
        else:
            frame["ticker"] = ticker_series(frame["ticker"])
            invalid_tickers = sorted(
                set(frame.loc[frame["ticker"].isin(INVALID_TICKERS), "ticker"])
            )
            if invalid_tickers:
                proposal_failures.append(
                    f"{label}_invalid_ticker_rows:{int(frame['ticker'].isin(INVALID_TICKERS).sum())}"
                )
            stock_tickers = frame.loc[
                ~frame["ticker"].isin(CASH_TICKERS | INVALID_TICKERS), "ticker"
            ]
            duplicate_tickers = sorted(
                set(stock_tickers.loc[stock_tickers.duplicated(keep=False)])
            )
            if duplicate_tickers:
                proposal_failures.append(
                    f"{label}_duplicate_tickers:{len(duplicate_tickers)}"
                )
            proposal_tickers = set(stock_tickers)
            if not proposal_tickers:
                proposal_failures.append(f"{label}_no_equity_tickers")
            unexpected_tickers = sorted(proposal_tickers - eligible_tickers)
            if unexpected_tickers:
                proposal_failures.append(
                    f"{label}_ineligible_or_unexpected_tickers:{len(unexpected_tickers)}"
                )
            proposal_missing_exact_close = sorted(
                proposal_tickers - exact_close_tickers
            )
            if proposal_missing_exact_close:
                proposal_failures.append(
                    f"{label}_exact_close_missing:{len(proposal_missing_exact_close)}"
                )

        failures.extend(proposal_failures)
        proposal_ready[label] = not proposal_failures
        proposal_audits[label] = {
            "ready": proposal_ready[label],
            "equity_ticker_count": len(proposal_tickers),
            "invalid_tickers": invalid_tickers,
            "duplicate_tickers": duplicate_tickers,
            "ineligible_or_unexpected_tickers": unexpected_tickers,
            "missing_exact_close_tickers": proposal_missing_exact_close,
            "contract_failures": sorted(set(proposal_failures)),
        }

    monthly_due = is_month_end_session(valuation_date)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "status": "READY_FULLRUN_LATEST_CROSS_SECTION" if not failures else "BLOCKED_FULLRUN_LATEST_CROSS_SECTION",
        "ready": not failures,
        "contract_failures": sorted(set(failures)),
        "valuation_price_cutoff_date": valuation_date,
        "market_close_utc": close.isoformat(),
        "decision_time_utc": decision_time.isoformat(),
        "monthly_rebalance_due": monthly_due,
        "current_fullrun_cross_section_recomputed": not failures,
        "current_fullrun_target_proposals_recomputed": bool(not failures and all(proposal_ready.values())),
        "same_close_daily_selector_recomputed": False,
        "accepted_paper_state_mutated": False,
        "broker_ledger_executed": False,
        "research_only": True,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
        "automatic_promotion_allowed": False,
        "coverage": {
            "scored_row_count": int(len(scored)),
            "eligible_ticker_count": int(len(eligible_tickers)),
            "candidate_latest_row_count": int(len(candidate_latest)),
            "candidate_missing_eligible_ticker_count": int(len(missing_candidate_tickers)),
            "exact_close_available_count": int(len(price_rows) - len(missing_exact_close)),
            "exact_close_missing_count": int(len(missing_exact_close)),
            "exact_close_coverage_ratio": float(
                (len(price_rows) - len(missing_exact_close)) / len(price_rows)
            ) if price_rows else 0.0,
        },
        "artifacts": {
            label: {
                "path": str(path),
                "sha256": sha256(path),
                "row_count": int(len(frames[label])),
            }
            for label, path in paths.items()
        },
        "target_proposal_audits": proposal_audits,
        "missing_candidate_tickers": missing_candidate_tickers,
        "missing_exact_close_tickers": missing_exact_close,
    }
    pd.DataFrame(price_rows).to_csv(output_dir / "ticker_exact_close_audit.csv", index=False)
    (output_dir / "summary.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default="outputs")
    parser.add_argument("--price-cache", default="cache_prices")
    parser.add_argument("--valuation-date", required=True)
    parser.add_argument("--decision-time-utc", required=True)
    parser.add_argument("--output-dir", default="outputs/fullrun_latest_cross_section_preflight")
    parser.add_argument("--min-scored-rows", type=int, default=400)
    parser.add_argument("--strict", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = build(args)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 2 if args.strict and not payload["ready"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
