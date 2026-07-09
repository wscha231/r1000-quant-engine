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
FINNHUB_BASE = "https://finnhub.io/api/v1"
ESTIMATE_ENDPOINTS = {"/stock/eps-estimate", "/stock/revenue-estimate"}


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
    return re.sub(r"([?&]token=)[^&\s]+", r"\1***", text)[:240]


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
        "fetch_source": "finnhub",
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
            confirmed = out["est_eps_revision_breadth"] > 0 and out["est_dispersion_change_30d"] <= 0
            out["estimate_revision_confirmed"] = int(confirmed)
            out["estimate_revision_replacement_gate_pass"] = int(confirmed)
            mult = 1.0 + max(-0.05, min(0.05, safe_float(out["est_eps_revision_breadth"], 0.0) * 0.05))
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
    keep_cols = ["ticker", *[c for c in PHASE18_ESTIMATE_REVISION_COLUMNS if c in latest.columns]]
    merged = out.merge(latest[keep_cols], on="ticker", how="left", suffixes=("", "_estimate_signal"))
    for col in PHASE18_ESTIMATE_REVISION_COLUMNS:
        signal_col = f"{col}_estimate_signal"
        if signal_col in merged.columns:
            merged[col] = pd.to_numeric(merged[signal_col], errors="coerce").fillna(0.0)
            merged = merged.drop(columns=[signal_col])
    breadth = pd.to_numeric(merged["est_eps_revision_breadth"], errors="coerce").fillna(0.0)
    dispersion_change = pd.to_numeric(merged["est_dispersion_change_30d"], errors="coerce").fillna(0.0)
    confirmed = (breadth > 0.0) & (dispersion_change <= 0.0)
    merged["estimate_revision_confirmed"] = confirmed.astype(int)
    merged["estimate_revision_replacement_gate_pass"] = confirmed.astype(int)
    multiplier = 1.0 + (breadth * multiplier_cap).clip(lower=-multiplier_cap, upper=multiplier_cap)
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


def fetch_json(session: requests.Session, endpoint: str, ticker: str, api_key: str, *, sleep_seconds: float) -> Any:
    url = f"{FINNHUB_BASE}{endpoint}"
    params = {"symbol": ticker, "token": api_key}
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
                "endpoint": endpoint,
                "status_code": status_code,
                "vendor_entitlement_blocked": bool(status_code in {401, 403} and endpoint in ESTIMATE_ENDPOINTS),
                "error": sanitize_error_message(exc),
            }
        )
        return None
    except Exception as exc:
        errors.append(
            {
                "ticker": ticker,
                "endpoint": endpoint,
                "status_code": 0,
                "vendor_entitlement_blocked": False,
                "error": sanitize_error_message(exc),
            }
        )
        return None


def vendor_estimate_access_from_errors(errors: list[dict[str, Any]]) -> bool:
    return not any(bool(e.get("vendor_entitlement_blocked")) for e in errors)


def collect_live_snapshot(
    tickers: list[str],
    *,
    api_key: str,
    fetch_date: pd.Timestamp,
    sleep_seconds: float,
    max_errors: int,
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    session = requests.Session()
    for ticker in tickers:
        eps = fetch_json_optional(
            session, "/stock/eps-estimate", ticker, api_key, sleep_seconds=sleep_seconds, errors=errors
        )
        rev = fetch_json_optional(
            session, "/stock/revenue-estimate", ticker, api_key, sleep_seconds=sleep_seconds, errors=errors
        )
        earnings = fetch_json_optional(
            session, "/stock/earnings", ticker, api_key, sleep_seconds=sleep_seconds, errors=errors
        )
        rec = fetch_json_optional(
            session, "/stock/recommendation", ticker, api_key, sleep_seconds=sleep_seconds, errors=errors
        )
        if any(payload is not None for payload in [eps, rev, earnings, rec]):
            rows.append(
                parse_snapshot_row(
                    ticker,
                    fetch_date=fetch_date,
                    eps_payload=eps or {},
                    revenue_payload=rev or {},
                    earnings_payload=earnings or [],
                    recommendation_payload=rec or [],
                    eps_estimate_access=eps is not None,
                    revenue_estimate_access=rev is not None,
                )
            )
        if max_errors and len(errors) >= max_errors:
            break
    return pd.DataFrame(rows), errors


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tickers", default="")
    parser.add_argument("--universe-file", default="")
    parser.add_argument("--ticker-limit", type=int, default=0)
    parser.add_argument("--api-key", default=os.environ.get("FINNHUB_API_KEY", ""))
    parser.add_argument("--snapshot-dir", default=DEFAULT_SNAPSHOT_DIR)
    parser.add_argument("--signals-output", default=DEFAULT_SIGNALS)
    parser.add_argument("--summary", default=DEFAULT_SUMMARY)
    parser.add_argument("--fetch-date", default=datetime.now(timezone.utc).date().isoformat())
    parser.add_argument("--sleep-seconds", type=float, default=1.1)
    parser.add_argument("--max-errors", type=int, default=25)
    parser.add_argument("--fixture-dir", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    fetch_date = pd.Timestamp(args.fetch_date).normalize()
    snapshot_dir = repo_path(args.snapshot_dir)
    signals_output = repo_path(args.signals_output)
    summary_path = repo_path(args.summary)
    tickers = parse_tickers(args.tickers, args.universe_file or None, args.ticker_limit)
    if not tickers:
        payload = {
            "schema_version": SCHEMA_VERSION,
            "generated_at_utc": utc_now(),
            "status": "blocked",
            "reason": "no_tickers",
            "research_only": True,
            "forward_only": True,
        }
        write_json(summary_path, payload)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 2
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    errors: list[dict[str, Any]] = []
    if args.fixture_dir:
        fixture_dir = repo_path(args.fixture_dir)
        rows = []
        for ticker in tickers:
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
        if not args.api_key:
            payload = {
                "schema_version": SCHEMA_VERSION,
                "generated_at_utc": utc_now(),
                "status": "blocked",
                "reason": "missing_finnhub_api_key",
                "research_only": True,
                "forward_only": True,
            }
            write_json(summary_path, payload)
            print(json.dumps(payload, indent=2, sort_keys=True))
            return 2
        snapshot, errors = collect_live_snapshot(
            tickers,
            api_key=args.api_key,
            fetch_date=fetch_date,
            sleep_seconds=args.sleep_seconds,
            max_errors=args.max_errors,
        )
    vendor_estimate_access = vendor_estimate_access_from_errors(errors)
    if snapshot.empty:
        status = "blocked_vendor_entitlement" if not vendor_estimate_access else "blocked_partial_coverage"
        reason = "finnhub_estimate_endpoint_forbidden" if not vendor_estimate_access else "no_snapshot_rows"
        payload = {
            "schema_version": SCHEMA_VERSION,
            "generated_at_utc": utc_now(),
            "status": status,
            "reason": reason,
            "ticker_count_requested": len(tickers),
            "error_count": len(errors),
            "errors": errors[:10],
            "vendor_estimate_access": vendor_estimate_access,
            "backtest_acceptance_allowed": False,
            "production_activation_allowed": False,
            "live_trading_enabled": False,
            "research_only": True,
            "forward_only": True,
        }
        write_json(summary_path, payload)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0 if not vendor_estimate_access else 2
    snapshot_path = snapshot_dir / f"estimates_{fetch_date.strftime('%Y%m%d')}.parquet"
    snapshot.to_parquet(snapshot_path, index=False)
    history = load_snapshot_history(snapshot_dir)
    signals, feature_summary = compute_estimate_revision_features(history, as_of_date=fetch_date.date().isoformat())
    if not signals.empty:
        signals_output.parent.mkdir(parents=True, exist_ok=True)
        signals.to_parquet(signals_output, index=False)
    coverage_ratio = len(snapshot) / max(1, len(tickers))
    status = (
        "completed"
        if coverage_ratio >= 0.8 and vendor_estimate_access
        else "blocked_vendor_entitlement"
        if not vendor_estimate_access
        else "blocked_partial_coverage"
    )
    reason = ""
    if status == "blocked_vendor_entitlement":
        reason = "finnhub_estimate_endpoint_forbidden"
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
        "snapshot_rows": int(len(snapshot)),
        "coverage_ratio": coverage_ratio,
        "vendor_estimate_access": vendor_estimate_access,
        "has_forward_estimate_rows": int(snapshot["has_forward_estimate"].sum()) if "has_forward_estimate" in snapshot.columns else 0,
        "snapshot_path": str(snapshot_path),
        "signals_output": str(signals_output),
        "feature_summary": feature_summary,
        "error_count": len(errors),
        "errors": errors[:10],
    }
    write_json(summary_path, payload)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
