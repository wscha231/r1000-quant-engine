#!/usr/bin/env python3
"""Collect forward-only Finnhub estimate snapshots and build PIT signals.

This tool starts a point-in-time archive from the day it is run. It must not be
used to backfill historical estimate revisions from a current snapshot.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from r1000_config import PHASE18_ESTIMATE_REVISION_COLUMNS  # noqa: E402

SCHEMA_VERSION = "forward-earnings-estimates-v1"
DEFAULT_SNAPSHOT_DIR = "data_pit/events/earnings_estimates"
DEFAULT_SIGNALS = "data_pit/events/earnings_revision_signals.parquet"
DEFAULT_SUMMARY = "outputs/earnings_estimates_daily/summary.json"
DEFAULT_VENDOR_ORDER = "fmp,finnhub"
FINNHUB_BASE = "https://finnhub.io/api/v1"
ALPHAVANTAGE_BASE = "https://www.alphavantage.co/query"
FMP_BASE = "https://financialmodelingprep.com"
ESTIMATE_ENDPOINTS = {"/stock/eps-estimate", "/stock/revenue-estimate"}
DEFAULT_ENTITLEMENT_CIRCUIT_THRESHOLD = 3
GLOBAL_ENTITLEMENT_CIRCUIT_STATUS_CODES = {401, 403}
ESTIMATE_REQUESTS_PER_VENDOR_TICKER = {
    "alphavantage": 1,
    "fmp": 1,
    "finnhub": 2,
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
        return out if pd.notna(out) else default
    except (TypeError, ValueError):
        return default


def pct_change(current: float, previous: float) -> float:
    if previous == 0 or pd.isna(previous) or pd.isna(current):
        return 0.0
    return float((current - previous) / abs(previous))


def finite_or_zero(value: float) -> float:
    return float(value) if pd.notna(value) else 0.0


def sanitize_error_message(value: Any) -> str:
    """Remove API tokens from persisted error strings.

    GitHub masks secrets in logs, but artifacts and Google Drive syncs preserve
    file contents. Never write vendor keys into summary JSON or collector logs.
    """
    text = str(value)
    text = re.sub(r"([?&]token=)[^&\s]+", r"\1***", text)
    text = re.sub(r"([?&]apikey=)[^&\s]+", r"\1***", text)
    text = re.sub(r"(?i)(api key as\s+)[A-Za-z0-9._-]+", r"\1***", text)
    text = re.sub(r"(?i)(api key[:=]\s*)[A-Za-z0-9._-]+", r"\1***", text)
    return text[:240]


def clean_vendor_order(value: str | None) -> list[str]:
    raw = value or DEFAULT_VENDOR_ORDER
    out = []
    for item in raw.split(","):
        vendor = item.strip().lower().replace("_", "")
        if vendor in {"av", "alpha", "alphavantage"}:
            vendor = "alphavantage"
        if vendor in {"financialmodelingprep"}:
            vendor = "fmp"
        if vendor in {"finnhub", "alphavantage", "fmp"} and vendor not in out:
            out.append(vendor)
    return out or clean_vendor_order(DEFAULT_VENDOR_ORDER)


def first_present(row: dict[str, Any], names: list[str], default: Any = None) -> Any:
    lowered = {str(k).lower(): v for k, v in row.items()}
    for name in names:
        if name in row and row.get(name) not in [None, ""]:
            return row.get(name)
        lname = name.lower()
        if lname in lowered and lowered[lname] not in [None, ""]:
            return lowered[lname]
    return default


def parse_tickers(values: str | None, universe_file: str | None = None, limit: int = 0) -> list[str]:
    tickers: list[str] = []
    if values:
        tickers.extend([x.strip().upper() for x in values.split(",") if x.strip()])
    if universe_file:
        path = repo_path(universe_file)
        if path.exists():
            with path.open(newline="", encoding="utf-8") as handle:
                reader = csv.DictReader(handle)
                field = "ticker" if "ticker" in (reader.fieldnames or []) else (reader.fieldnames or [""])[0]
                for row in reader:
                    ticker = str(row.get(field, "")).strip().upper()
                    if ticker:
                        tickers.append(ticker)
    deduped = list(dict.fromkeys(tickers))
    return deduped[:limit] if limit and limit > 0 else deduped


def latest_estimate_record(payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict):
        data = payload.get("data", payload.get("estimate", []))
    else:
        data = payload
    if not isinstance(data, list):
        return {}
    rows = [x for x in data if isinstance(x, dict)]
    if not rows:
        return {}
    return sorted(rows, key=lambda x: str(x.get("period") or x.get("date") or x.get("fiscalDateEnding") or ""))[-1]


def first_two_estimates(payload: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    if isinstance(payload, dict):
        data = payload.get("data", payload.get("estimate", []))
    else:
        data = payload
    rows = [x for x in data if isinstance(x, dict)] if isinstance(data, list) else []
    rows = sorted(rows, key=lambda x: str(x.get("period") or x.get("date") or x.get("fiscalDateEnding") or ""))
    if not rows:
        return {}, {}
    if len(rows) == 1:
        return rows[0], {}
    return rows[0], rows[1]


def latest_earnings_record(payload: Any) -> tuple[dict[str, Any], int]:
    rows = [x for x in payload if isinstance(x, dict)] if isinstance(payload, list) else []
    rows = sorted(rows, key=lambda x: str(x.get("period") or ""))
    latest = rows[-1] if rows else {}
    streak = 0
    sign = 0
    for row in reversed(rows):
        surprise = safe_float(row.get("surprise") if "surprise" in row else row.get("surprisePercent"), 0.0)
        current_sign = 1 if surprise > 0 else -1 if surprise < 0 else 0
        if current_sign == 0:
            break
        if sign == 0:
            sign = current_sign
        if current_sign != sign:
            break
        streak += current_sign
    return latest, streak


def latest_recommendation_record(payload: Any) -> dict[str, Any]:
    rows = [x for x in payload if isinstance(x, dict)] if isinstance(payload, list) else []
    if not rows:
        return {}
    return sorted(rows, key=lambda x: str(x.get("period") or ""))[-1]


def alphavantage_to_payloads(payload: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    """Normalize Alpha Vantage EARNINGS_ESTIMATES into Finnhub-like payloads."""
    if not isinstance(payload, dict):
        return {}, {}
    if payload.get("Error Message") or payload.get("Information") or payload.get("Note"):
        return {}, {}
    annual = payload.get("annualEarningsEstimates") or payload.get("annualReports") or []
    rows = [x for x in annual if isinstance(x, dict)] if isinstance(annual, list) else []
    rows = sorted(rows, key=lambda x: str(first_present(x, ["fiscalDateEnding", "period", "date"], "")))
    if not rows:
        quarterly = payload.get("quarterlyEarningsEstimates") or payload.get("quarterlyReports") or []
        rows = [x for x in quarterly if isinstance(x, dict)] if isinstance(quarterly, list) else []
        rows = sorted(rows, key=lambda x: str(first_present(x, ["fiscalDateEnding", "period", "date"], "")))
    eps_rows: list[dict[str, Any]] = []
    rev_rows: list[dict[str, Any]] = []
    for row in rows[:2]:
        period = str(first_present(row, ["fiscalDateEnding", "period", "date"], ""))
        eps_rows.append(
            {
                "period": period,
                "avg": first_present(
                    row,
                    [
                        "epsEstimateAverage",
                        "epsEstimatedAverage",
                        "estimatedEPSAvg",
                        "estimatedEpsAvg",
                        "estimateAverage",
                    ],
                ),
                "high": first_present(row, ["epsEstimateHigh", "estimatedEPSHigh", "estimatedEpsHigh", "estimateHigh"]),
                "low": first_present(row, ["epsEstimateLow", "estimatedEPSLow", "estimatedEpsLow", "estimateLow"]),
                "numberAnalysts": first_present(
                    row,
                    ["epsEstimateAnalystCount", "epsEstimateNumberOfAnalysts", "numberAnalystsEstimatedEps", "analystCount"],
                    0,
                ),
            }
        )
        rev_rows.append(
            {
                "period": period,
                "avg": first_present(
                    row,
                    [
                        "revenueEstimateAverage",
                        "revenueEstimatedAverage",
                        "estimatedRevenueAvg",
                        "estimatedRevenueAverage",
                    ],
                ),
                "high": first_present(row, ["revenueEstimateHigh", "estimatedRevenueHigh"]),
                "low": first_present(row, ["revenueEstimateLow", "estimatedRevenueLow"]),
                "numberAnalysts": first_present(
                    row,
                    [
                        "revenueEstimateAnalystCount",
                        "revenueEstimateNumberOfAnalysts",
                        "numberAnalystsEstimatedRevenue",
                        "analystCount",
                    ],
                    0,
                ),
            }
        )
    eps_rows = [x for x in eps_rows if x.get("avg") not in [None, ""]]
    rev_rows = [x for x in rev_rows if x.get("avg") not in [None, ""]]
    return {"data": eps_rows}, {"data": rev_rows}


def fmp_to_payloads(payload: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    """Normalize FMP stable analyst-estimates responses into Finnhub-like payloads."""
    if isinstance(payload, dict) and isinstance(payload.get("data"), list):
        data = payload.get("data")
    else:
        data = payload
    rows = [x for x in data if isinstance(x, dict)] if isinstance(data, list) else []
    rows = sorted(rows, key=lambda x: str(first_present(x, ["date", "fiscalDateEnding", "period"], "")))
    eps_rows: list[dict[str, Any]] = []
    rev_rows: list[dict[str, Any]] = []
    for row in rows[:2]:
        period = str(first_present(row, ["date", "fiscalDateEnding", "period"], ""))
        eps_rows.append(
            {
                "period": period,
                "avg": first_present(
                    row,
                    [
                        "estimatedEpsAvg",
                        "estimatedEPSAvg",
                        "estimatedEpsAverage",
                        "epsAvg",
                        "epsAverage",
                    ],
                ),
                "high": first_present(row, ["estimatedEpsHigh", "estimatedEPSHigh", "epsHigh"]),
                "low": first_present(row, ["estimatedEpsLow", "estimatedEPSLow", "epsLow"]),
                "numberAnalysts": first_present(
                    row,
                    ["numberAnalystsEstimatedEps", "numberAnalystEstimatedEps", "numberAnalysts", "analystCount"],
                    0,
                ),
            }
        )
        rev_rows.append(
            {
                "period": period,
                "avg": first_present(
                    row,
                    [
                        "estimatedRevenueAvg",
                        "estimatedRevenueAverage",
                        "revenueAvg",
                        "revenueAverage",
                    ],
                ),
                "high": first_present(row, ["estimatedRevenueHigh", "revenueHigh"]),
                "low": first_present(row, ["estimatedRevenueLow", "revenueLow"]),
                "numberAnalysts": first_present(
                    row,
                    [
                        "numberAnalystsEstimatedRevenue",
                        "numberAnalystEstimatedRevenue",
                        "numberAnalysts",
                        "analystCount",
                    ],
                    0,
                ),
            }
        )
    eps_rows = [x for x in eps_rows if x.get("avg") not in [None, ""]]
    rev_rows = [x for x in rev_rows if x.get("avg") not in [None, ""]]
    return {"data": eps_rows}, {"data": rev_rows}


def parse_snapshot_row(
    ticker: str,
    *,
    fetch_date: pd.Timestamp,
    eps_payload: Any,
    revenue_payload: Any,
    earnings_payload: Any,
    recommendation_payload: Any,
    eps_estimate_access: bool = True,
    revenue_estimate_access: bool = True,
    fetch_source: str = "finnhub",
) -> dict[str, Any]:
    eps1, eps2 = first_two_estimates(eps_payload)
    rev1 = latest_estimate_record(revenue_payload)
    earnings, surprise_streak = latest_earnings_record(earnings_payload)
    rec = latest_recommendation_record(recommendation_payload)
    eps_avg = safe_float(eps1.get("avg"), float("nan"))
    eps_high = safe_float(eps1.get("high"), float("nan"))
    eps_low = safe_float(eps1.get("low"), float("nan"))
    est_dispersion = pct_change(eps_high, eps_low) if pd.notna(eps_high) and pd.notna(eps_low) and eps_low != 0 else 0.0
    strong_buy = int(safe_float(rec.get("strongBuy"), 0.0))
    buy = int(safe_float(rec.get("buy"), 0.0))
    sell = int(safe_float(rec.get("sell"), 0.0))
    strong_sell = int(safe_float(rec.get("strongSell"), 0.0))
    bull = strong_buy + buy
    bear = sell + strong_sell
    denom = bull + bear
    return {
        "ticker": ticker.upper(),
        "as_of_date": fetch_date.date().isoformat(),
        "available_from": fetch_date.date().isoformat(),
        "fetch_source": fetch_source,
        "eps_estimate_access": bool(eps_estimate_access),
        "revenue_estimate_access": bool(revenue_estimate_access),
        "vendor_estimate_access": bool(eps_estimate_access and revenue_estimate_access),
        "has_forward_estimate": int(bool(eps1 or rev1)),
        "est_eps_fy1": finite_or_zero(eps_avg),
        "est_eps_fy2": finite_or_zero(safe_float(eps2.get("avg"), float("nan"))),
        "est_rev_fy1": finite_or_zero(safe_float(rev1.get("avg"), float("nan"))),
        "n_analysts": int(max(safe_float(eps1.get("numberAnalysts"), 0.0), safe_float(rev1.get("numberAnalysts"), 0.0))),
        "est_dispersion": finite_or_zero(est_dispersion),
        "actual_eps_last": finite_or_zero(safe_float(earnings.get("actual"), float("nan"))),
        "actual_report_date": str(earnings.get("period") or ""),
        "earnings_surprise_last": finite_or_zero(safe_float(earnings.get("surprisePercent", earnings.get("surprise")), 0.0)),
        "surprise_streak": int(surprise_streak),
        "recommendation_period": str(rec.get("period") or ""),
        "recommendation_bull_count": bull,
        "recommendation_bear_count": bear,
        "est_eps_revision_breadth": float((bull - bear) / denom) if denom else 0.0,
    }


def prior_value(group: pd.DataFrame, idx: int, column: str, days: int) -> float:
    current = group.loc[idx, "as_of_date"]
    cutoff = current - pd.Timedelta(days=days)
    prior = group[(group["as_of_date"] <= cutoff) & (group.index < idx)]
    if prior.empty:
        return float("nan")
    return safe_float(prior.iloc[-1].get(column), float("nan"))


def compute_estimate_revision_features(snapshots: pd.DataFrame, *, as_of_date: str | None = None) -> tuple[pd.DataFrame, dict[str, Any]]:
    if snapshots.empty:
        return pd.DataFrame(), {"status": "blocked", "reason": "no_snapshot_rows"}
    d = snapshots.copy()
    required = {"ticker", "as_of_date", "available_from"}
    missing = sorted(required - set(d.columns))
    if missing:
        return pd.DataFrame(), {"status": "blocked", "reason": f"missing_required_columns:{','.join(missing)}"}
    d["ticker"] = d["ticker"].astype(str).str.upper().str.strip()
    d["as_of_date"] = pd.to_datetime(d["as_of_date"], errors="coerce").dt.normalize()
    d["available_from"] = pd.to_datetime(d["available_from"], errors="coerce").dt.normalize()
    if as_of_date:
        as_of = pd.Timestamp(as_of_date).normalize()
        d = d[d["available_from"] <= as_of]
    for col in [
        "est_eps_fy1",
        "est_eps_fy2",
        "est_rev_fy1",
        "est_dispersion",
        "earnings_surprise_last",
        "est_eps_revision_breadth",
        "surprise_streak",
        "has_forward_estimate",
    ]:
        if col not in d.columns:
            d[col] = 0.0
        d[col] = pd.to_numeric(d[col], errors="coerce").fillna(0.0)
    d = d[d["ticker"].ne("") & d["as_of_date"].notna() & d["available_from"].notna()]
    d = d.sort_values(["ticker", "as_of_date"]).reset_index(drop=True)
    rows: list[dict[str, Any]] = []
    for _, group in d.groupby("ticker", sort=False):
        group = group.reset_index(drop=True)
        for idx, row in group.iterrows():
            eps = safe_float(row.get("est_eps_fy1"), float("nan"))
            rev = safe_float(row.get("est_rev_fy1"), float("nan"))
            dispersion = safe_float(row.get("est_dispersion"), 0.0)
            prior_eps_30 = prior_value(group, idx, "est_eps_fy1", 30)
            prior_eps_90 = prior_value(group, idx, "est_eps_fy1", 90)
            prior_rev_30 = prior_value(group, idx, "est_rev_fy1", 30)
            prior_dispersion_30 = prior_value(group, idx, "est_dispersion", 30)
            out = row.to_dict()
            out.update(
                {
                    "est_eps_revision_30d": pct_change(eps, prior_eps_30),
                    "est_eps_revision_90d": pct_change(eps, prior_eps_90),
                    "est_rev_revision_30d": pct_change(rev, prior_rev_30),
                    "est_dispersion_change_30d": dispersion - prior_dispersion_30 if pd.notna(prior_dispersion_30) else 0.0,
                }
            )
            has_forward_estimate = safe_float(out.get("has_forward_estimate"), 0.0) > 0
            confirmed = (
                has_forward_estimate
                and out["est_eps_revision_breadth"] > 0
                and out["est_dispersion_change_30d"] <= 0
            )
            out["estimate_revision_confirmed"] = int(confirmed)
            out["estimate_revision_replacement_gate_pass"] = int(confirmed)
            mult = 1.0
            if has_forward_estimate:
                mult += max(-0.05, min(0.05, safe_float(out["est_eps_revision_breadth"], 0.0) * 0.05))
            out["estimate_revision_future_winner_multiplier"] = float(mult)
            rows.append(out)
    out_df = pd.DataFrame(rows)
    for col in PHASE18_ESTIMATE_REVISION_COLUMNS:
        if col not in out_df.columns:
            out_df[col] = 0.0
    summary = {
        "status": "completed",
        "input_rows": int(len(snapshots)),
        "output_rows": int(len(out_df)),
        "ticker_count": int(out_df["ticker"].nunique()) if not out_df.empty else 0,
        "coverage_ratio": float(out_df["ticker"].nunique() / max(1, snapshots["ticker"].nunique())) if "ticker" in snapshots.columns else 0.0,
        "available_from_is_fetch_date": bool((out_df["available_from"] == out_df["as_of_date"]).all()) if not out_df.empty else True,
        "forward_only": True,
        "backtest_acceptance_allowed": False,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
    }
    return out_df, summary


def latest_signal_by_ticker(signals: pd.DataFrame, *, decision_date: str | pd.Timestamp) -> pd.DataFrame:
    if signals.empty:
        return pd.DataFrame(columns=["ticker", *PHASE18_ESTIMATE_REVISION_COLUMNS])
    d = signals.copy()
    if "available_from" not in d.columns or "ticker" not in d.columns:
        return pd.DataFrame(columns=["ticker", *PHASE18_ESTIMATE_REVISION_COLUMNS])
    d["ticker"] = d["ticker"].astype(str).str.upper().str.strip()
    d["available_from"] = pd.to_datetime(d["available_from"], errors="coerce").dt.normalize()
    cutoff = pd.Timestamp(decision_date).normalize()
    d = d[d["ticker"].ne("") & d["available_from"].notna() & (d["available_from"] <= cutoff)]
    if d.empty:
        return pd.DataFrame(columns=["ticker", *PHASE18_ESTIMATE_REVISION_COLUMNS])
    return d.sort_values(["ticker", "available_from"]).groupby("ticker", as_index=False).tail(1)


def apply_estimate_revision_confirmation(
    scored: pd.DataFrame,
    signals: pd.DataFrame,
    *,
    decision_date: str | pd.Timestamp,
    enabled: bool = False,
    future_winner_score_col: str = "portfolio_future_winner_engine_score",
    multiplier_cap: float = 0.05,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Attach forward-only estimate confirmation to a latest scored frame.

    This helper is intentionally default-OFF. It is suitable for latest-month
    operating scoring, not historical feature-store construction.
    """
    out = scored.copy()
    for col in PHASE18_ESTIMATE_REVISION_COLUMNS:
        if col not in out.columns:
            out[col] = 0.0
    summary = {
        "enabled": bool(enabled),
        "decision_date": str(pd.Timestamp(decision_date).date()),
        "selection_change_count": 0,
        "matched_signal_rows": 0,
        "historical_backtest_allowed": False,
        "default_off": True,
    }
    if not enabled or out.empty:
        return out, summary
    if "ticker" not in out.columns:
        summary["reason"] = "missing_ticker_column"
        return out, summary
    latest = latest_signal_by_ticker(signals, decision_date=decision_date)
    if latest.empty:
        summary["reason"] = "no_available_signals"
        return out, summary
    keep_cols = [
        "ticker",
        *[c for c in PHASE18_ESTIMATE_REVISION_COLUMNS if c in latest.columns],
        *[c for c in ["has_forward_estimate"] if c in latest.columns],
    ]
    merged = out.merge(latest[keep_cols], on="ticker", how="left", suffixes=("", "_estimate_signal"))
    for col in PHASE18_ESTIMATE_REVISION_COLUMNS:
        signal_col = f"{col}_estimate_signal"
        if signal_col in merged.columns:
            merged[col] = pd.to_numeric(merged[signal_col], errors="coerce").fillna(0.0)
            merged = merged.drop(columns=[signal_col])
    breadth = pd.to_numeric(merged["est_eps_revision_breadth"], errors="coerce").fillna(0.0)
    dispersion_change = pd.to_numeric(merged["est_dispersion_change_30d"], errors="coerce").fillna(0.0)
    if "has_forward_estimate" in merged.columns:
        has_forward_estimate = pd.to_numeric(merged["has_forward_estimate"], errors="coerce").fillna(0.0).gt(0.0)
    else:
        has_forward_estimate = pd.Series(True, index=merged.index)
    confirmed = has_forward_estimate & (breadth > 0.0) & (dispersion_change <= 0.0)
    merged["estimate_revision_confirmed"] = confirmed.astype(int)
    merged["estimate_revision_replacement_gate_pass"] = confirmed.astype(int)
    multiplier = 1.0 + (breadth.where(has_forward_estimate, 0.0) * multiplier_cap).clip(
        lower=-multiplier_cap,
        upper=multiplier_cap,
    )
    merged["estimate_revision_future_winner_multiplier"] = multiplier
    changed = int(confirmed.sum())
    if future_winner_score_col in merged.columns:
        before = pd.to_numeric(merged[future_winner_score_col], errors="coerce").fillna(0.0)
        merged[future_winner_score_col] = before * multiplier
    summary.update(
        {
            "selection_change_count": changed,
            "matched_signal_rows": int(merged["est_eps_fy1"].fillna(0).ne(0).sum()),
            "confirmed_rows": changed,
        }
    )
    return merged, summary


def load_snapshot_history(snapshot_dir: Path) -> pd.DataFrame:
    frames = []
    for path in sorted(snapshot_dir.glob("estimates_*.parquet")):
        frames.append(pd.read_parquet(path))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def acknowledge_collection_attempts(
    checkpoint_path: Path,
    queue_path: Path,
    attempted_tickers: list[str],
    *,
    attempted_at_utc: str,
) -> dict[str, Any]:
    """Acknowledge only tickers the collector actually reached.

    The queue planner records a proposed batch but deliberately leaves the
    durable rotation counters unchanged.  This acknowledgement runs only after
    the collector returns, so a missing key, runner failure, or max-error break
    cannot make an unattempted tail look serviced.
    """
    attempted = list(dict.fromkeys(str(t).upper().strip() for t in attempted_tickers if str(t).strip()))
    result: dict[str, Any] = {
        "status": "disabled",
        "attempted_ticker_count": len(attempted),
        "acknowledged_ticker_count": 0,
        "unacknowledged_tickers": attempted,
    }
    if not checkpoint_path or not str(checkpoint_path) or not queue_path or not str(queue_path):
        return result
    if not checkpoint_path.exists() or not queue_path.exists():
        result["status"] = "checkpoint_or_queue_missing"
        return result
    try:
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        with queue_path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            fieldnames = list(reader.fieldnames or [])
            queue_rows = list(reader)
    except (OSError, json.JSONDecodeError, csv.Error) as exc:
        result.update({"status": "invalid_checkpoint_or_queue", "error": sanitize_error_message(exc)})
        return result
    states = checkpoint.get("ticker_states") if isinstance(checkpoint, dict) else None
    if not isinstance(states, list) or not fieldnames:
        result["status"] = "invalid_checkpoint_or_queue"
        return result
    selected = {
        str(row.get("ticker") or "").upper().strip()
        for row in queue_rows
        if _truthy(row.get("selected"))
    }
    acknowledged = [ticker for ticker in attempted if ticker in selected]
    acknowledged_set = set(acknowledged)
    for row in states:
        ticker = str(row.get("ticker") or "").upper().strip()
        if ticker in acknowledged_set:
            row["last_selected_at_utc"] = attempted_at_utc
            row["selection_count"] = int(row.get("selection_count") or 0) + 1
    for row in queue_rows:
        ticker = str(row.get("ticker") or "").upper().strip()
        if ticker in acknowledged_set:
            row["last_selected_at_utc"] = attempted_at_utc
            row["selection_count"] = str(int(row.get("selection_count") or 0) + 1)
    result.update(
        {
            "status": "acknowledged",
            "acknowledged_ticker_count": len(acknowledged),
            "unacknowledged_tickers": [ticker for ticker in attempted if ticker not in acknowledged_set],
        }
    )
    checkpoint["updated_at_utc"] = attempted_at_utc
    checkpoint["last_collection_attempt_ack"] = result
    checkpoint_tmp = checkpoint_path.with_suffix(checkpoint_path.suffix + ".tmp")
    checkpoint_tmp.write_text(
        json.dumps(checkpoint, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    os.replace(checkpoint_tmp, checkpoint_path)
    queue_tmp = queue_path.with_suffix(queue_path.suffix + ".tmp")
    with queue_tmp.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(queue_rows)
    os.replace(queue_tmp, queue_path)
    return result


def merge_same_day_snapshot(existing_path: Path, current: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Merge same-date archive rows instead of shrinking a durable snapshot.

    Manual smokes, broad catch-ups, and scheduled incremental runs can all share
    a fetch date. The durable `estimates_YYYYMMDD.parquet` file should be the
    union of that day's collected tickers, with later rows replacing earlier
    rows for the same ticker.
    """
    info: dict[str, Any] = {
        "same_day_snapshot_merged": False,
        "same_day_existing_rows": 0,
        "same_day_current_rows": int(len(current)),
        "same_day_merged_rows": int(len(current)),
    }
    if current.empty or not existing_path.exists():
        return current, info
    try:
        existing = pd.read_parquet(existing_path)
    except Exception:
        return current, info
    if existing.empty:
        return current, info
    info["same_day_existing_rows"] = int(len(existing))
    combined = pd.concat([existing, current], ignore_index=True, sort=False)
    if "ticker" in combined.columns:
        combined["_ticker_norm"] = combined["ticker"].astype(str).str.upper().str.strip()
        sort_cols = ["_ticker_norm"]
        if "available_from" in combined.columns:
            combined["_available_from_ts"] = pd.to_datetime(combined["available_from"], errors="coerce")
            sort_cols.append("_available_from_ts")
        combined = combined.sort_values(sort_cols, kind="stable")
        combined = combined.drop_duplicates("_ticker_norm", keep="last")
        combined = combined.drop(columns=[c for c in ["_ticker_norm", "_available_from_ts"] if c in combined.columns])
        if "ticker" in combined.columns:
            combined = combined.sort_values("ticker", kind="stable").reset_index(drop=True)
    info["same_day_snapshot_merged"] = True
    info["same_day_merged_rows"] = int(len(combined))
    return combined, info


def fetch_json(session: requests.Session, endpoint: str, ticker: str, api_key: str, *, sleep_seconds: float) -> Any:
    url = f"{FINNHUB_BASE}{endpoint}"
    params = {"symbol": ticker, "token": api_key}
    response = session.get(url, params=params, timeout=20)
    if sleep_seconds:
        time.sleep(sleep_seconds)
    response.raise_for_status()
    return response.json()


def fetch_url_json(
    session: requests.Session,
    url: str,
    params: dict[str, Any],
    *,
    sleep_seconds: float,
) -> Any:
    response = session.get(url, params=params, timeout=20)
    if sleep_seconds:
        time.sleep(sleep_seconds)
    response.raise_for_status()
    return response.json()


def fetch_json_optional(
    session: requests.Session,
    endpoint: str,
    ticker: str,
    api_key: str,
    *,
    sleep_seconds: float,
    errors: list[dict[str, Any]],
) -> Any | None:
    try:
        return fetch_json(session, endpoint, ticker, api_key, sleep_seconds=sleep_seconds)
    except requests.HTTPError as exc:
        status_code = int(exc.response.status_code) if exc.response is not None else 0
        errors.append(
            {
                "ticker": ticker,
                "vendor": "finnhub",
                "endpoint": endpoint,
                "status_code": status_code,
                "vendor_entitlement_blocked": bool(status_code in {401, 402, 403} and endpoint in ESTIMATE_ENDPOINTS),
                "error": sanitize_error_message(exc),
            }
        )
        return None
    except Exception as exc:
        errors.append(
            {
                "ticker": ticker,
                "vendor": "finnhub",
                "endpoint": endpoint,
                "status_code": 0,
                "vendor_entitlement_blocked": False,
                "error": sanitize_error_message(exc),
            }
        )
        return None


def vendor_estimate_access_from_errors(errors: list[dict[str, Any]]) -> bool:
    return not any(bool(e.get("vendor_entitlement_blocked")) for e in errors)


def estimate_vendor_blocked_by_errors(errors: list[dict[str, Any]]) -> bool:
    return any(bool(e.get("vendor_entitlement_blocked")) for e in errors)


def _new_vendor_entitlement_circuit(vendor: str, threshold: int) -> dict[str, Any]:
    return {
        "vendor": vendor,
        "run_scoped": True,
        "threshold_distinct_tickers": max(0, int(threshold)),
        "estimate_request_ticker_count": 0,
        "accessible_response_ticker_count": 0,
        "estimate_data_ticker_count": 0,
        "entitlement_failure_ticker_count": 0,
        "entitlement_failure_signatures": {},
        "tripped": False,
        "tripped_at_ticker": "",
        "trip_signature": "",
        "skipped_ticker_count": 0,
        "estimated_http_requests_avoided": 0,
    }


def _error_vendor(error: dict[str, Any]) -> str:
    vendor = str(error.get("vendor") or "").strip().lower()
    if vendor:
        return vendor
    return "finnhub" if str(error.get("endpoint") or "") in ESTIMATE_ENDPOINTS else ""


def _record_vendor_entitlement_result(
    circuits: dict[str, dict[str, Any]],
    *,
    vendor: str,
    ticker: str,
    new_errors: list[dict[str, Any]],
    accessible_response: bool,
    has_estimate_data: bool,
    threshold: int,
) -> None:
    circuit = circuits.setdefault(vendor, _new_vendor_entitlement_circuit(vendor, threshold))
    circuit["estimate_request_ticker_count"] += 1
    if accessible_response:
        circuit["accessible_response_ticker_count"] += 1
    if has_estimate_data:
        circuit["estimate_data_ticker_count"] += 1

    entitlement_errors = [
        error
        for error in new_errors
        if _error_vendor(error) == vendor
        and bool(error.get("vendor_entitlement_blocked"))
        and int(error.get("status_code") or 0) in GLOBAL_ENTITLEMENT_CIRCUIT_STATUS_CODES
    ]
    if not entitlement_errors or accessible_response:
        return

    failure_tickers: set[str] = set()
    signatures = circuit["entitlement_failure_signatures"]
    for error in entitlement_errors:
        endpoint = str(error.get("endpoint") or "unknown")
        status_code = int(error.get("status_code") or 0)
        signature = f"{status_code}:{endpoint}"
        signature_tickers = signatures.setdefault(signature, [])
        if ticker not in signature_tickers:
            signature_tickers.append(ticker)
        failure_tickers.add(ticker)
    circuit["entitlement_failure_ticker_count"] += len(failure_tickers)

    if circuit["tripped"] or threshold <= 0 or circuit["accessible_response_ticker_count"] > 0:
        return
    for signature, signature_tickers in signatures.items():
        if len(signature_tickers) >= threshold:
            circuit["tripped"] = True
            circuit["tripped_at_ticker"] = ticker
            circuit["trip_signature"] = signature
            return


def _skip_tripped_vendor(circuit: dict[str, Any]) -> None:
    circuit["skipped_ticker_count"] += 1
    avoided = ESTIMATE_REQUESTS_PER_VENDOR_TICKER.get(str(circuit.get("vendor") or ""), 1)
    circuit["estimated_http_requests_avoided"] += avoided


def summarize_vendor_entitlement_circuits(
    circuits: dict[str, dict[str, Any]],
    *,
    stopped_unattempted_ticker_count: int = 0,
    stop_reason: str = "",
) -> dict[str, Any]:
    vendors = {vendor: dict(circuit) for vendor, circuit in sorted(circuits.items())}
    tripped_vendors = [vendor for vendor, circuit in vendors.items() if bool(circuit.get("tripped"))]
    avoided = sum(int(circuit.get("estimated_http_requests_avoided") or 0) for circuit in vendors.values())
    if stopped_unattempted_ticker_count > 0:
        avoided += stopped_unattempted_ticker_count * sum(
            ESTIMATE_REQUESTS_PER_VENDOR_TICKER.get(vendor, 1) for vendor in tripped_vendors
        )
    return {
        "enabled": any(int(circuit.get("threshold_distinct_tickers") or 0) > 0 for circuit in vendors.values()),
        "run_scoped": True,
        "persistent_vendor_block_written": False,
        "circuit_status_codes": sorted(GLOBAL_ENTITLEMENT_CIRCUIT_STATUS_CODES),
        "tripped_vendor_count": len(tripped_vendors),
        "tripped_vendors": tripped_vendors,
        "estimated_estimate_http_requests_avoided": avoided,
        "stopped_unattempted_ticker_count": int(stopped_unattempted_ticker_count),
        "stop_reason": stop_reason,
        "vendors": vendors,
    }


def collection_error_budget(
    errors: list[dict[str, Any]],
    circuits: dict[str, dict[str, Any]],
) -> dict[str, int]:
    """Keep symbol-level entitlement misses from exhausting the safety cap.

    HTTP 402 is retained as a coverage warning because the observed FMP run
    returned estimates for some symbols while returning 402 for others. A
    vendor that has returned any accessible response is likewise demonstrably
    not globally blocked. 401/403 probes count against the cap only after the
    repeated-signature circuit has actually tripped.
    """
    budget_count = 0
    warn_only_count = 0
    probe_count = 0
    for error in errors:
        vendor = _error_vendor(error)
        circuit = circuits.get(vendor, {})
        partial_access_confirmed = int(circuit.get("accessible_response_ticker_count") or 0) > 0
        entitlement_blocked = bool(error.get("vendor_entitlement_blocked"))
        status_code = int(error.get("status_code") or 0)
        if entitlement_blocked and (status_code == 402 or partial_access_confirmed):
            warn_only_count += 1
            continue
        if (
            entitlement_blocked
            and status_code in GLOBAL_ENTITLEMENT_CIRCUIT_STATUS_CODES
            and not bool(circuit.get("tripped"))
        ):
            probe_count += 1
            continue
        budget_count += 1
    return {
        "raw_error_count": len(errors),
        "error_budget_count": budget_count,
        "entitlement_error_warn_only_count": warn_only_count,
        "entitlement_error_probe_count": probe_count,
    }


def fetch_alphavantage_payloads(
    session: requests.Session,
    ticker: str,
    api_key: str,
    *,
    sleep_seconds: float,
    errors: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        payload = fetch_url_json(
            session,
            ALPHAVANTAGE_BASE,
            {"function": "EARNINGS_ESTIMATES", "symbol": ticker, "apikey": api_key},
            sleep_seconds=sleep_seconds,
        )
        eps, rev = alphavantage_to_payloads(payload)
        if not (eps.get("data") or rev.get("data")):
            info = payload.get("Information") or payload.get("Note") or payload.get("Error Message") if isinstance(payload, dict) else ""
            if info:
                errors.append(
                    {
                        "ticker": ticker,
                        "vendor": "alphavantage",
                        "endpoint": "EARNINGS_ESTIMATES",
                        "status_code": 200,
                        "vendor_entitlement_blocked": False,
                        "error": sanitize_error_message(info),
                    }
                )
        return eps, rev
    except requests.HTTPError as exc:
        status_code = int(exc.response.status_code) if exc.response is not None else 0
        errors.append(
            {
                "ticker": ticker,
                "vendor": "alphavantage",
                "endpoint": "EARNINGS_ESTIMATES",
                "status_code": status_code,
                "vendor_entitlement_blocked": bool(status_code in {401, 402, 403}),
                "error": sanitize_error_message(exc),
            }
        )
    except Exception as exc:
        errors.append(
            {
                "ticker": ticker,
                "vendor": "alphavantage",
                "endpoint": "EARNINGS_ESTIMATES",
                "status_code": 0,
                "vendor_entitlement_blocked": False,
                "error": sanitize_error_message(exc),
            }
        )
    return {}, {}


def fetch_fmp_payloads(
    session: requests.Session,
    ticker: str,
    api_key: str,
    *,
    sleep_seconds: float,
    errors: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        payload = fetch_url_json(
            session,
            f"{FMP_BASE}/stable/analyst-estimates",
            {"symbol": ticker, "period": "annual", "page": 0, "limit": 10, "apikey": api_key},
            sleep_seconds=sleep_seconds,
        )
        eps, rev = fmp_to_payloads(payload)
        return eps, rev
    except requests.HTTPError as exc:
        status_code = int(exc.response.status_code) if exc.response is not None else 0
        errors.append(
            {
                "ticker": ticker,
                "vendor": "fmp",
                "endpoint": "/stable/analyst-estimates",
                "status_code": status_code,
                "vendor_entitlement_blocked": bool(status_code in {401, 402, 403}),
                "error": sanitize_error_message(exc),
            }
        )
    except Exception as exc:
        errors.append(
            {
                "ticker": ticker,
                "vendor": "fmp",
                "endpoint": "/stable/analyst-estimates",
                "status_code": 0,
                "vendor_entitlement_blocked": False,
                "error": sanitize_error_message(exc),
            }
        )
    return {}, {}


def fetch_estimate_payloads_by_order(
    session: requests.Session,
    ticker: str,
    *,
    finnhub_api_key: str,
    alphavantage_api_key: str,
    fmp_api_key: str,
    vendor_order: list[str],
    sleep_seconds: float,
    errors: list[dict[str, Any]],
    vendor_entitlement_circuits: dict[str, dict[str, Any]] | None = None,
    entitlement_circuit_threshold: int = DEFAULT_ENTITLEMENT_CIRCUIT_THRESHOLD,
) -> tuple[dict[str, Any], dict[str, Any], str, bool, bool, bool]:
    circuits = vendor_entitlement_circuits if vendor_entitlement_circuits is not None else {}
    any_request_attempted = False
    for vendor in vendor_order:
        circuit = circuits.get(vendor)
        if circuit and bool(circuit.get("tripped")):
            _skip_tripped_vendor(circuit)
            continue
        before_error_count = len(errors)
        if vendor == "alphavantage" and alphavantage_api_key:
            any_request_attempted = True
            eps, rev = fetch_alphavantage_payloads(
                session, ticker, alphavantage_api_key, sleep_seconds=sleep_seconds, errors=errors
            )
            new_errors = errors[before_error_count:]
            accessible = not any(
                _error_vendor(error) == vendor
                and (int(error.get("status_code") or 0) == 0 or int(error.get("status_code") or 0) >= 400)
                for error in new_errors
            )
            _record_vendor_entitlement_result(
                circuits,
                vendor=vendor,
                ticker=ticker,
                new_errors=new_errors,
                accessible_response=accessible,
                has_estimate_data=bool(eps.get("data") or rev.get("data")),
                threshold=entitlement_circuit_threshold,
            )
            if eps.get("data") or rev.get("data"):
                return eps, rev, "alphavantage", bool(eps.get("data")), bool(rev.get("data")), any_request_attempted
        elif vendor == "fmp" and fmp_api_key:
            any_request_attempted = True
            eps, rev = fetch_fmp_payloads(session, ticker, fmp_api_key, sleep_seconds=sleep_seconds, errors=errors)
            new_errors = errors[before_error_count:]
            accessible = not any(
                _error_vendor(error) == vendor
                and (int(error.get("status_code") or 0) == 0 or int(error.get("status_code") or 0) >= 400)
                for error in new_errors
            )
            _record_vendor_entitlement_result(
                circuits,
                vendor=vendor,
                ticker=ticker,
                new_errors=new_errors,
                accessible_response=accessible,
                has_estimate_data=bool(eps.get("data") or rev.get("data")),
                threshold=entitlement_circuit_threshold,
            )
            if eps.get("data") or rev.get("data"):
                return eps, rev, "fmp", bool(eps.get("data")), bool(rev.get("data")), any_request_attempted
        elif vendor == "finnhub" and finnhub_api_key:
            any_request_attempted = True
            eps = fetch_json_optional(
                session, "/stock/eps-estimate", ticker, finnhub_api_key, sleep_seconds=sleep_seconds, errors=errors
            )
            rev = fetch_json_optional(
                session, "/stock/revenue-estimate", ticker, finnhub_api_key, sleep_seconds=sleep_seconds, errors=errors
            )
            new_errors = errors[before_error_count:]
            accessible = eps is not None or rev is not None
            _record_vendor_entitlement_result(
                circuits,
                vendor=vendor,
                ticker=ticker,
                new_errors=new_errors,
                accessible_response=accessible,
                has_estimate_data=bool((eps or {}).get("data") or (rev or {}).get("data")),
                threshold=entitlement_circuit_threshold,
            )
            if eps is not None or rev is not None:
                return eps or {}, rev or {}, "finnhub", eps is not None, rev is not None, any_request_attempted
    return {}, {}, "", False, False, any_request_attempted


def collect_live_snapshot(
    tickers: list[str],
    *,
    finnhub_api_key: str,
    alphavantage_api_key: str,
    fmp_api_key: str,
    vendor_order: list[str],
    fetch_date: pd.Timestamp,
    sleep_seconds: float,
    max_errors: int,
    entitlement_circuit_threshold: int = DEFAULT_ENTITLEMENT_CIRCUIT_THRESHOLD,
) -> tuple[pd.DataFrame, list[dict[str, Any]], list[str], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    attempted_tickers: list[str] = []
    vendor_entitlement_circuits: dict[str, dict[str, Any]] = {}
    stop_reason = ""
    session = requests.Session()
    for ticker in tickers:
        eps, rev, estimate_source, eps_access, rev_access, estimate_request_attempted = fetch_estimate_payloads_by_order(
            session,
            ticker,
            finnhub_api_key=finnhub_api_key,
            alphavantage_api_key=alphavantage_api_key,
            fmp_api_key=fmp_api_key,
            vendor_order=vendor_order,
            sleep_seconds=sleep_seconds,
            errors=errors,
            vendor_entitlement_circuits=vendor_entitlement_circuits,
            entitlement_circuit_threshold=entitlement_circuit_threshold,
        )
        optional_finnhub_request_attempted = bool(finnhub_api_key)
        earnings = fetch_json_optional(
            session, "/stock/earnings", ticker, finnhub_api_key, sleep_seconds=sleep_seconds, errors=errors
        ) if finnhub_api_key else None
        rec = fetch_json_optional(
            session, "/stock/recommendation", ticker, finnhub_api_key, sleep_seconds=sleep_seconds, errors=errors
        ) if finnhub_api_key else None
        if estimate_request_attempted or optional_finnhub_request_attempted:
            attempted_tickers.append(ticker)
        else:
            stop_reason = "no_enabled_vendor_request_after_entitlement_circuit"
            break
        if any(payload is not None and payload != {} for payload in [eps, rev, earnings, rec]):
            fetch_source = estimate_source or ("finnhub" if any(payload is not None for payload in [earnings, rec]) else "")
            rows.append(
                parse_snapshot_row(
                    ticker,
                    fetch_date=fetch_date,
                    eps_payload=eps or {},
                    revenue_payload=rev or {},
                    earnings_payload=earnings or [],
                    recommendation_payload=rec or [],
                    eps_estimate_access=eps_access,
                    revenue_estimate_access=rev_access,
                    fetch_source=fetch_source,
                )
            )
        error_budget = collection_error_budget(errors, vendor_entitlement_circuits)
        if max_errors and error_budget["error_budget_count"] >= max_errors:
            stop_reason = "max_errors_reached"
            break
    diagnostics = summarize_vendor_entitlement_circuits(
        vendor_entitlement_circuits,
        stopped_unattempted_ticker_count=max(0, len(tickers) - len(attempted_tickers)),
        stop_reason=stop_reason,
    )
    diagnostics["error_budget"] = collection_error_budget(errors, vendor_entitlement_circuits)
    return pd.DataFrame(rows), errors, attempted_tickers, diagnostics


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tickers", default="")
    parser.add_argument("--universe-file", default="")
    parser.add_argument("--ticker-limit", type=int, default=0)
    parser.add_argument("--api-key", default=os.environ.get("FINNHUB_API_KEY", ""))
    parser.add_argument("--alphavantage-api-key", default=os.environ.get("ALPHAVANTAGE_API_KEY", ""))
    parser.add_argument("--fmp-api-key", default=os.environ.get("FMP_API_KEY", ""))
    parser.add_argument("--vendor-order", default=os.environ.get("ESTIMATE_VENDOR_ORDER", DEFAULT_VENDOR_ORDER))
    parser.add_argument("--snapshot-dir", default=DEFAULT_SNAPSHOT_DIR)
    parser.add_argument("--signals-output", default=DEFAULT_SIGNALS)
    parser.add_argument("--summary", default=DEFAULT_SUMMARY)
    parser.add_argument("--fetch-date", default=datetime.now(timezone.utc).date().isoformat())
    parser.add_argument("--sleep-seconds", type=float, default=1.1)
    parser.add_argument("--max-errors", type=int, default=100)
    parser.add_argument(
        "--entitlement-circuit-threshold",
        type=int,
        default=DEFAULT_ENTITLEMENT_CIRCUIT_THRESHOLD,
        help="Trip a run-scoped vendor circuit after this many distinct tickers share one 401/403 signature; 0 disables.",
    )
    parser.add_argument("--fixture-dir", default="")
    parser.add_argument("--collection-checkpoint", default="")
    parser.add_argument("--collection-queue", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    fetch_date = pd.Timestamp(args.fetch_date).normalize()
    snapshot_dir = repo_path(args.snapshot_dir)
    signals_output = repo_path(args.signals_output)
    summary_path = repo_path(args.summary)
    checkpoint_path = repo_path(args.collection_checkpoint) if args.collection_checkpoint else Path()
    queue_path = repo_path(args.collection_queue) if args.collection_queue else Path()
    tickers = parse_tickers(args.tickers, args.universe_file or None, args.ticker_limit)
    if not tickers:
        payload = {
            "schema_version": SCHEMA_VERSION,
            "generated_at_utc": utc_now(),
            "status": "blocked",
            "reason": "no_tickers",
            "research_only": True,
            "forward_only": True,
            "max_errors": args.max_errors,
            "entitlement_circuit_threshold": args.entitlement_circuit_threshold,
        }
        write_json(summary_path, payload)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 2
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    errors: list[dict[str, Any]] = []
    attempted_tickers: list[str] = []
    vendor_entitlement_circuit = summarize_vendor_entitlement_circuits({})
    if args.fixture_dir:
        fixture_dir = repo_path(args.fixture_dir)
        rows = []
        for ticker in tickers:
            attempted_tickers.append(ticker)
            with (fixture_dir / f"{ticker.upper()}_eps.json").open(encoding="utf-8") as handle:
                eps = json.load(handle)
            with (fixture_dir / f"{ticker.upper()}_revenue.json").open(encoding="utf-8") as handle:
                rev = json.load(handle)
            with (fixture_dir / f"{ticker.upper()}_earnings.json").open(encoding="utf-8") as handle:
                earnings = json.load(handle)
            with (fixture_dir / f"{ticker.upper()}_recommendation.json").open(encoding="utf-8") as handle:
                rec = json.load(handle)
            rows.append(
                parse_snapshot_row(
                    ticker,
                    fetch_date=fetch_date,
                    eps_payload=eps,
                    revenue_payload=rev,
                    earnings_payload=earnings,
                    recommendation_payload=rec,
                )
            )
        snapshot = pd.DataFrame(rows)
    else:
        vendor_order = clean_vendor_order(args.vendor_order)
        if not any([args.api_key, args.alphavantage_api_key, args.fmp_api_key]):
            payload = {
                "schema_version": SCHEMA_VERSION,
                "generated_at_utc": utc_now(),
                "status": "blocked",
                "reason": "missing_estimate_vendor_api_key",
                "research_only": True,
                "forward_only": True,
                "vendor_order": vendor_order,
                "max_errors": args.max_errors,
                "entitlement_circuit_threshold": args.entitlement_circuit_threshold,
            }
            write_json(summary_path, payload)
            print(json.dumps(payload, indent=2, sort_keys=True))
            return 2
        collected = collect_live_snapshot(
            tickers,
            finnhub_api_key=args.api_key,
            alphavantage_api_key=args.alphavantage_api_key,
            fmp_api_key=args.fmp_api_key,
            vendor_order=vendor_order,
            fetch_date=fetch_date,
            sleep_seconds=args.sleep_seconds,
            max_errors=args.max_errors,
            entitlement_circuit_threshold=args.entitlement_circuit_threshold,
        )
        if len(collected) == 4:
            snapshot, errors, attempted_tickers, vendor_entitlement_circuit = collected
        elif len(collected) == 3:
            snapshot, errors, attempted_tickers = collected
        else:  # Backward-compatible with test doubles written for the older API.
            snapshot, errors = collected  # type: ignore[misc]
            attempted_tickers = list(tickers)
    attempt_ack = acknowledge_collection_attempts(
        checkpoint_path,
        queue_path,
        attempted_tickers,
        attempted_at_utc=utc_now(),
    ) if args.collection_checkpoint and args.collection_queue else {
        "status": "disabled",
        "attempted_ticker_count": len(attempted_tickers),
        "acknowledged_ticker_count": 0,
        "unacknowledged_tickers": [],
    }
    error_budget = vendor_entitlement_circuit.get("error_budget") or collection_error_budget(errors, {})
    vendor_order = clean_vendor_order(args.vendor_order)
    vendor_blocked_errors = estimate_vendor_blocked_by_errors(errors)
    vendor_estimate_access = vendor_estimate_access_from_errors(errors)
    if snapshot.empty:
        status = "blocked_vendor_entitlement" if not vendor_estimate_access else "blocked_partial_coverage"
        reason = "estimate_vendor_endpoint_forbidden_or_payment_required" if not vendor_estimate_access else "no_snapshot_rows"
        payload = {
            "schema_version": SCHEMA_VERSION,
            "generated_at_utc": utc_now(),
            "status": status,
            "reason": reason,
            "ticker_count_requested": len(tickers),
            "ticker_count_attempted": len(attempted_tickers),
            "collection_attempt_ack": attempt_ack,
            "error_count": len(errors),
            "error_budget_count": error_budget["error_budget_count"],
            "entitlement_error_warn_only_count": error_budget["entitlement_error_warn_only_count"],
            "entitlement_error_probe_count": error_budget["entitlement_error_probe_count"],
            "errors": errors[:10],
            "vendor_estimate_access": vendor_estimate_access,
            "vendor_blocked_errors": vendor_blocked_errors,
            "backtest_acceptance_allowed": False,
            "production_activation_allowed": False,
            "live_trading_enabled": False,
            "research_only": True,
            "forward_only": True,
            "vendor_order": vendor_order,
            "max_errors": args.max_errors,
            "entitlement_circuit_threshold": args.entitlement_circuit_threshold,
            "vendor_entitlement_circuit": vendor_entitlement_circuit,
        }
        write_json(summary_path, payload)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0 if not vendor_estimate_access else 2
    current_snapshot = snapshot.copy()
    snapshot_path = snapshot_dir / f"estimates_{fetch_date.strftime('%Y%m%d')}.parquet"
    snapshot, same_day_merge = merge_same_day_snapshot(snapshot_path, current_snapshot)
    snapshot.to_parquet(snapshot_path, index=False)
    history = load_snapshot_history(snapshot_dir)
    signals, feature_summary = compute_estimate_revision_features(history, as_of_date=fetch_date.date().isoformat())
    if not signals.empty:
        signals_output.parent.mkdir(parents=True, exist_ok=True)
        signals.to_parquet(signals_output, index=False)
    coverage_ratio = len(current_snapshot) / max(1, len(tickers))
    request_has_forward_estimate_rows = (
        int(pd.to_numeric(current_snapshot["has_forward_estimate"], errors="coerce").fillna(0).sum())
        if "has_forward_estimate" in current_snapshot.columns
        else 0
    )
    estimate_coverage_ratio = request_has_forward_estimate_rows / max(1, len(tickers))
    has_forward_estimate_rows = (
        int(pd.to_numeric(snapshot["has_forward_estimate"], errors="coerce").fillna(0).sum())
        if "has_forward_estimate" in snapshot.columns
        else 0
    )
    stored_estimate_coverage_ratio = has_forward_estimate_rows / max(1, len(snapshot))
    vendor_estimate_access = request_has_forward_estimate_rows > 0
    status = (
        "completed"
        if estimate_coverage_ratio >= 0.8
        else "blocked_vendor_entitlement"
        if request_has_forward_estimate_rows == 0 and vendor_blocked_errors
        else "blocked_partial_coverage"
    )
    reason = ""
    if status == "completed" and errors:
        reason = "partial_vendor_errors_warn_only"
    elif status == "blocked_vendor_entitlement":
        reason = "estimate_vendor_endpoint_forbidden_or_payment_required"
    elif status == "blocked_partial_coverage":
        reason = "coverage_below_80pct_warn_only"
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_now(),
        "status": status,
        "reason": reason,
        "research_only": True,
        "forward_only": True,
        "backtest_acceptance_allowed": False,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
        "ticker_count_requested": len(tickers),
        "ticker_count_attempted": len(attempted_tickers),
        "collection_attempt_ack": attempt_ack,
        "request_snapshot_rows": int(len(current_snapshot)),
        "request_has_forward_estimate_rows": request_has_forward_estimate_rows,
        "request_estimate_coverage_ratio": estimate_coverage_ratio,
        "snapshot_rows": int(len(snapshot)),
        "stored_estimate_coverage_ratio": stored_estimate_coverage_ratio,
        **same_day_merge,
        "coverage_ratio": coverage_ratio,
        "estimate_coverage_ratio": estimate_coverage_ratio,
        "vendor_estimate_access": vendor_estimate_access,
        "vendor_blocked_errors": vendor_blocked_errors,
        "vendor_order": vendor_order,
        "max_errors": args.max_errors,
        "entitlement_circuit_threshold": args.entitlement_circuit_threshold,
        "vendor_entitlement_circuit": vendor_entitlement_circuit,
        "fetch_sources": sorted(snapshot["fetch_source"].dropna().astype(str).unique().tolist()) if "fetch_source" in snapshot.columns else [],
        "has_forward_estimate_rows": has_forward_estimate_rows,
        "snapshot_path": str(snapshot_path),
        "signals_output": str(signals_output),
        "feature_summary": feature_summary,
        "error_count": len(errors),
        "error_budget_count": error_budget["error_budget_count"],
        "entitlement_error_warn_only_count": error_budget["entitlement_error_warn_only_count"],
        "entitlement_error_probe_count": error_budget["entitlement_error_probe_count"],
        "errors": errors[:10],
    }
    write_json(summary_path, payload)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
