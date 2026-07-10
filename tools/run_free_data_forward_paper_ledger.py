#!/usr/bin/env python3
"""Maintain a forward-only paper ledger for the free-data selection overlay.

The source of truth is an append-only JSONL event log.  Signal observations,
next-close references, and elapsed forward outcomes are separate immutable
events; ``current_status.csv`` is only a rebuildable view of those events.

This tool is deliberately research-only.  It does not fetch prices, mutate a
target book, dispatch a fullrun, backfill signals for dates before they were
observed, or enable production/live trading.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

try:
    import pandas_market_calendars as mcal
except ImportError:  # pragma: no cover - workflow dependency, fail closed below
    mcal = None


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.run_weekly_evaluation import load_price_series, px_cache_name  # noqa: E402


SCHEMA_VERSION = "free-data-forward-paper-ledger-v1"
SIGNAL_SNAPSHOT_SCHEMA_VERSION = "free-data-selection-signal-snapshot-v2"
HORIZONS = (21, 63, 126)
BENCHMARK_DEFAULT = "SPY"
EVENT_LOG_NAME = "ledger_events.jsonl"

SIGNAL_SNAPSHOT_COLUMNS = (
    "free_data_selection_rank",
    "prior_free_data_selection_rank",
    "free_data_selection_rank_delta_vs_prior",
    "free_data_selection_score",
    "free_data_base_rank_score",
    "free_data_base_weighted_component",
    "free_data_forward_weighted_component",
    "free_data_recent_actual_weighted_component",
    "free_data_lifecycle_penalty_component",
    "free_data_forward_estimate_score",
    "free_data_forward_estimate_score_before_coverage_gate",
    "free_data_recent_actual_score",
    "free_data_earnings_calendar_actual_score",
    "free_data_auxiliary_actual_score",
    "free_data_evidence_coverage_count",
    "free_data_signal_snapshot_present",
    "free_data_forward_estimate_evidence_present",
    "free_data_recommendation_evidence_present",
    "free_data_auxiliary_actual_evidence_present",
    "free_data_earnings_calendar_evidence_present",
    "free_data_lifecycle_evidence_present",
    "free_data_lifecycle_ok",
    "free_data_lifecycle_risk",
    "free_data_selection_label",
    "fetch_source",
    "eps_estimate_access",
    "revenue_estimate_access",
    "vendor_estimate_access",
    "estimate_revision_confirmed",
    "estimate_revision_replacement_gate_pass",
    "estimate_revision_future_winner_multiplier",
    "est_eps_revision_breadth",
    "est_eps_revision_30d",
    "est_eps_revision_90d",
    "est_dispersion_change_30d",
    "earnings_surprise_last",
    "surprise_streak",
    "recommendation_period",
    "recommendation_bull_count",
    "recommendation_bear_count",
    "has_forward_estimate",
    "estimated_eps",
    "actual_eps",
)


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_nyse_sessions(start_date: pd.Timestamp, end_date: pd.Timestamp) -> pd.DatetimeIndex | None:
    """Return the authoritative NYSE session dates, or ``None`` if unavailable."""
    if mcal is None:
        return None
    try:
        schedule = mcal.get_calendar("NYSE").schedule(
            start_date=pd.Timestamp(start_date).date().isoformat(),
            end_date=pd.Timestamp(end_date).date().isoformat(),
        )
    except Exception:
        return None
    sessions = pd.DatetimeIndex(pd.to_datetime(schedule.index, errors="coerce"))
    if sessions.tz is not None:
        sessions = sessions.tz_localize(None)
    return sessions[sessions.notna()].normalize().sort_values().drop_duplicates()


def normalize_ticker(value: Any) -> str:
    ticker = str(value or "").upper().strip().replace(".", "-")
    return "" if ticker in {"", "NAN", "NONE", "CASH", "__CASH__"} else ticker


def _utc_timestamp(value: Any) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def _json_scalar(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (np.integer, int)) and not isinstance(value, bool):
        return int(value)
    if isinstance(value, (np.floating, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, pd.Timestamp):
        return value.isoformat() if pd.notna(value) else None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return str(value) if not isinstance(value, (str, dict, list)) else value


def _truthy(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    try:
        return bool(value) if not pd.isna(value) else False
    except (TypeError, ValueError):
        return False


def _canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def read_candidates(path: Path) -> pd.DataFrame:
    if not path.exists() or not path.is_file():
        return pd.DataFrame()
    try:
        frame = pd.read_parquet(path) if path.suffix.lower() == ".parquet" else pd.read_csv(path, low_memory=False)
    except Exception:
        return pd.DataFrame()
    if frame.empty or "ticker" not in frame.columns:
        return pd.DataFrame()
    out = frame.copy()
    out["ticker"] = out["ticker"].map(normalize_ticker)
    out = out[out["ticker"].ne("")].copy()
    if "free_data_selection_rank" in out.columns:
        out["_rank_sort"] = pd.to_numeric(out["free_data_selection_rank"], errors="coerce")
        out = out.sort_values(["_rank_sort", "ticker"], na_position="last", kind="stable")
    else:
        out = out.sort_values("ticker", kind="stable")
    return out.drop_duplicates("ticker", keep="first").drop(columns=["_rank_sort"], errors="ignore")


def read_events(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            event = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSONL at {path}:{line_number}: {exc}") from exc
        event_id = str(event.get("event_id") or "")
        if not event_id:
            raise ValueError(f"missing event_id at {path}:{line_number}")
        if event_id in seen:
            raise ValueError(f"duplicate event_id {event_id} at {path}:{line_number}")
        seen.add(event_id)
        rows.append(event)
    return rows


def append_events(path: Path, events: list[dict[str, Any]]) -> None:
    """Append new immutable events without ever rewriting existing bytes."""
    if not events:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    needs_leading_newline = path.exists() and path.stat().st_size > 0
    if needs_leading_newline:
        with path.open("rb") as check:
            check.seek(-1, os.SEEK_END)
            needs_leading_newline = check.read(1) != b"\n"
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        if needs_leading_newline:
            handle.write("\n")
        for event in events:
            handle.write(_canonical_json(event) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def signal_snapshot(row: pd.Series) -> dict[str, Any]:
    return {column: _json_scalar(row.get(column)) for column in SIGNAL_SNAPSHOT_COLUMNS if column in row.index}


def _observation_event(
    row: pd.Series,
    *,
    decision_date: pd.Timestamp,
    source_observed_at_utc: str,
    recorded_at_utc: str,
    candidates_path: Path,
    candidates_sha256: str,
    summary_path: Path,
    summary_sha256: str,
    benchmark: str,
) -> dict[str, Any]:
    ticker = normalize_ticker(row.get("ticker"))
    snapshot = signal_snapshot(row)
    snapshot_json = _canonical_json(snapshot)
    snapshot_sha256 = _sha256_text(snapshot_json)
    observation_key = f"{SCHEMA_VERSION}|{decision_date.date().isoformat()}|{ticker}|{snapshot_sha256}"
    observation_id = _sha256_text(observation_key)[:24]
    return {
        "schema_version": SCHEMA_VERSION,
        "event_id": _sha256_text(f"signal_observed|{observation_id}"),
        "event_type": "signal_observed",
        "recorded_at_utc": recorded_at_utc,
        "observation_id": observation_id,
        "decision_date": decision_date.date().isoformat(),
        "ticker": ticker,
        "source_observed_at_utc": source_observed_at_utc,
        "source_candidates_path": str(candidates_path),
        "source_candidates_sha256": candidates_sha256,
        "source_summary_path": str(summary_path),
        "source_summary_sha256": summary_sha256,
        "signal_snapshot_schema_version": SIGNAL_SNAPSHOT_SCHEMA_VERSION,
        "signal_snapshot_sha256": snapshot_sha256,
        "signal_snapshot": snapshot,
        "benchmark_ticker": benchmark,
        "labels": ["forward_signal_observed", "paper_ledger_candidate", "not_backtest_acceptance"],
        "forward_only": True,
        "pre_observation_signal_backfill_allowed": False,
        "historical_backtest_acceptance_allowed": False,
        "valid_for_backtest": False,
        "production_promotion_allowed": False,
        "valid_for_production": False,
        "live_trading_enabled": False,
        "target_books_mutated": False,
        "fullrun_dispatched": False,
    }


def build_observation_events(
    candidates: pd.DataFrame,
    overlay_summary: dict[str, Any],
    existing_events: list[dict[str, Any]],
    *,
    recorded_at_utc: str,
    candidates_path: Path,
    summary_path: Path,
    benchmark: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    audit: dict[str, Any] = {
        "candidate_rows": int(len(candidates)),
        "new_observation_rows": 0,
        "duplicate_observation_rows": 0,
        "blocked_observation_rows": 0,
        "blockers": [],
    }
    if candidates.empty:
        audit["blockers"].append("empty_or_unreadable_candidates")
        return [], audit
    required_candidate_columns = {
        "ticker",
        "free_data_selection_rank",
        "free_data_selection_score",
        "free_data_selection_label",
    }
    missing_candidate_columns = sorted(required_candidate_columns - set(candidates.columns))
    if missing_candidate_columns:
        audit["blockers"].append("missing_candidate_signal_columns:" + ",".join(missing_candidate_columns))
    if overlay_summary.get("status") != "completed":
        audit["blockers"].append("overlay_summary_not_completed")
    if overlay_summary.get("production_promotion_allowed") is not False:
        audit["blockers"].append("overlay_production_flag_not_false")
    if overlay_summary.get("historical_backtest_acceptance_allowed") is not False:
        audit["blockers"].append("overlay_backtest_flag_not_false")
    for flag in ("production_promotion_allowed", "historical_backtest_acceptance_allowed"):
        if flag in candidates.columns and candidates[flag].map(_truthy).any():
            audit["blockers"].append(f"candidate_{flag}_contains_true")
    decision_raw = overlay_summary.get("decision_date")
    observed_raw = overlay_summary.get("generated_at_utc")
    try:
        decision_date = pd.Timestamp(decision_raw).normalize()
    except Exception:
        audit["blockers"].append("missing_or_invalid_overlay_decision_date")
        return [], audit
    try:
        source_observed = _utc_timestamp(observed_raw)
        recorded_at = _utc_timestamp(recorded_at_utc)
    except Exception:
        audit["blockers"].append("missing_or_invalid_overlay_generated_at_utc")
        return [], audit
    source_lag_days = (source_observed.date() - decision_date.date()).days
    if source_lag_days not in (0, 1):
        audit["blockers"].append("decision_date_not_contemporaneous_with_source_observation")
    if source_observed > recorded_at + pd.Timedelta(minutes=5):
        audit["blockers"].append("source_observation_timestamp_is_in_future")
    if any(audit["blockers"]):
        audit["blocked_observation_rows"] = int(len(candidates))
        return [], audit

    candidates_hash = sha256_file(candidates_path)
    summary_hash = sha256_file(summary_path)
    existing_ids = {str(event.get("event_id")) for event in existing_events}
    existing_observations = [event for event in existing_events if event.get("event_type") == "signal_observed"]
    existing_dates = pd.to_datetime(
        [event.get("decision_date") for event in existing_observations], errors="coerce"
    )
    latest_existing = existing_dates.max() if len(existing_dates) and existing_dates.notna().any() else pd.NaT
    proposed = [
        _observation_event(
            row,
            decision_date=decision_date,
            source_observed_at_utc=source_observed.isoformat().replace("+00:00", "Z"),
            recorded_at_utc=recorded_at.isoformat().replace("+00:00", "Z"),
            candidates_path=candidates_path,
            candidates_sha256=candidates_hash,
            summary_path=summary_path,
            summary_sha256=summary_hash,
            benchmark=benchmark,
        )
        for _, row in candidates.iterrows()
    ]
    novel = [event for event in proposed if event["event_id"] not in existing_ids]
    audit["duplicate_observation_rows"] = len(proposed) - len(novel)
    receipt_lag_days = (recorded_at.date() - source_observed.date()).days
    if novel:
        audit["source_receipt_lag_days"] = receipt_lag_days
        if receipt_lag_days not in (0, 1):
            audit["blockers"].append("source_observation_not_contemporaneous_with_ledger_receipt")
    if novel and pd.notna(latest_existing) and decision_date < pd.Timestamp(latest_existing).normalize():
        audit["blockers"].append("pre_observation_signal_backfill_blocked_by_monotonic_decision_date")
    if audit["blockers"]:
        audit["blocked_observation_rows"] = int(len(novel))
        return [], audit
    audit["new_observation_rows"] = int(len(novel))
    audit["decision_date"] = decision_date.date().isoformat()
    audit["source_observed_at_utc"] = source_observed.isoformat().replace("+00:00", "Z")
    return novel, audit


def load_cached_prices(price_cache: Path, ticker: str) -> tuple[pd.DataFrame, str]:
    """Reuse the repository cache loader and report whether Adj Close existed."""
    cache_path = price_cache / px_cache_name(ticker)
    if not cache_path.exists():
        return pd.DataFrame(), "unavailable"
    basis = "unavailable"
    try:
        raw = pd.read_parquet(cache_path)
        columns = raw.columns.get_level_values(0) if isinstance(raw.columns, pd.MultiIndex) else raw.columns
        basis = "adjusted_close" if "Adj Close" in columns else ("close_only" if "Close" in columns else "unavailable")
    except Exception:
        return pd.DataFrame(), "unavailable"
    frame = load_price_series(price_cache, ticker)
    if frame.empty or "close" not in frame.columns:
        return pd.DataFrame(), basis
    out = frame[["close"]].copy()
    out.index = pd.DatetimeIndex(pd.to_datetime(out.index, errors="coerce")).tz_localize(None).normalize()
    out["close"] = pd.to_numeric(out["close"], errors="coerce")
    out = out[out.index.notna() & out["close"].gt(0) & np.isfinite(out["close"])].copy()
    out = out[~out.index.duplicated(keep="last")].sort_index()
    return out, basis


def _exact_price(frame: pd.DataFrame, date: pd.Timestamp) -> float | None:
    if frame.empty or date not in frame.index:
        return None
    value = frame.loc[date, "close"]
    if isinstance(value, pd.Series):
        value = value.iloc[-1]
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def _reference_candidate(
    observation: dict[str, Any],
    ticker_prices: pd.DataFrame,
    ticker_basis: str,
    benchmark_prices: pd.DataFrame,
    benchmark_basis: str,
    market_sessions: pd.DatetimeIndex | None,
    *,
    as_of_date: pd.Timestamp,
    recorded_at_utc: str,
) -> tuple[dict[str, Any] | None, str]:
    if market_sessions is None:
        return None, "pending_exchange_calendar_unavailable"
    if benchmark_basis != "adjusted_close":
        return None, "pending_benchmark_total_return_proxy_unavailable"
    if ticker_basis != "adjusted_close":
        return None, "pending_ticker_adjusted_price_unavailable"
    decision = pd.Timestamp(observation["decision_date"]).normalize()
    eligible = market_sessions[(market_sessions > decision) & (market_sessions <= as_of_date)]
    if len(eligible) == 0:
        return None, "pending_next_close_not_elapsed"
    reference_date = pd.Timestamp(eligible[0]).normalize()
    ticker_price = _exact_price(ticker_prices, reference_date)
    benchmark_price = _exact_price(benchmark_prices, reference_date)
    if benchmark_price is None:
        return None, "pending_benchmark_reference_price_unavailable"
    if ticker_price is None:
        return None, "pending_ticker_reference_price_unavailable"
    observation_id = str(observation["observation_id"])
    event = {
        "schema_version": SCHEMA_VERSION,
        "event_id": _sha256_text(f"next_close_reference_observed|{observation_id}"),
        "event_type": "next_close_reference_observed",
        "recorded_at_utc": recorded_at_utc,
        "observation_id": observation_id,
        "decision_date": observation["decision_date"],
        "ticker": observation["ticker"],
        "benchmark_ticker": observation["benchmark_ticker"],
        "next_close_date": reference_date.date().isoformat(),
        "ticker_next_close_price": ticker_price,
        "benchmark_next_close_price": benchmark_price,
        "ticker_price_basis": ticker_basis,
        "benchmark_price_basis": benchmark_basis,
        "benchmark_total_return_proxy": True,
        "reference_rule": "first_NYSE_session_strictly_after_decision_date_with_exact_adjusted_closes",
        "historical_backtest_acceptance_allowed": False,
        "valid_for_backtest": False,
        "production_promotion_allowed": False,
        "valid_for_production": False,
    }
    return event, "reference_observed"


def _max_drawdown(values: pd.Series) -> float:
    numeric = pd.to_numeric(values, errors="coerce").astype(float)
    drawdown = numeric / numeric.cummax() - 1.0
    return float(drawdown.min())


def _outcome_candidate(
    observation: dict[str, Any],
    reference: dict[str, Any],
    horizon: int,
    ticker_prices: pd.DataFrame,
    benchmark_prices: pd.DataFrame,
    market_sessions: pd.DatetimeIndex | None,
    *,
    as_of_date: pd.Timestamp,
    recorded_at_utc: str,
) -> tuple[dict[str, Any] | None, str]:
    if market_sessions is None:
        return None, "pending_exchange_calendar_unavailable"
    reference_date = pd.Timestamp(reference["next_close_date"]).normalize()
    decision = pd.Timestamp(observation["decision_date"]).normalize()
    expected_reference_dates = market_sessions[market_sessions > decision]
    if len(expected_reference_dates) == 0 or reference_date != pd.Timestamp(expected_reference_dates[0]).normalize():
        return None, "pending_reference_session_mismatch"
    elapsed_sessions = market_sessions[(market_sessions >= reference_date) & (market_sessions <= as_of_date)]
    if len(elapsed_sessions) <= horizon:
        return None, "pending_not_elapsed"
    window_dates = pd.DatetimeIndex(elapsed_sessions[: horizon + 1])
    outcome_date = pd.Timestamp(window_dates[-1]).normalize()
    ticker_window = ticker_prices.reindex(window_dates)["close"] if not ticker_prices.empty else pd.Series(dtype=float)
    benchmark_window = benchmark_prices.reindex(window_dates)["close"]
    if len(ticker_window) != horizon + 1 or ticker_window.isna().any() or (~np.isfinite(ticker_window)).any():
        return None, "pending_ticker_price_path_unavailable"
    if benchmark_window.isna().any() or (~np.isfinite(benchmark_window)).any():
        return None, "pending_benchmark_price_path_unavailable"
    ticker_start = float(ticker_window.iloc[0])
    ticker_end = float(ticker_window.iloc[-1])
    benchmark_start = float(benchmark_window.iloc[0])
    benchmark_end = float(benchmark_window.iloc[-1])
    ticker_return = ticker_end / ticker_start - 1.0
    benchmark_return = benchmark_end / benchmark_start - 1.0
    observation_id = str(observation["observation_id"])
    event = {
        "schema_version": SCHEMA_VERSION,
        "event_id": _sha256_text(f"forward_outcome_observed|{observation_id}|{horizon}"),
        "event_type": "forward_outcome_observed",
        "recorded_at_utc": recorded_at_utc,
        "evaluated_as_of_date": as_of_date.date().isoformat(),
        "observation_id": observation_id,
        "decision_date": observation["decision_date"],
        "ticker": observation["ticker"],
        "benchmark_ticker": observation["benchmark_ticker"],
        "horizon_trading_days": int(horizon),
        "next_close_date": reference["next_close_date"],
        "outcome_date": outcome_date.date().isoformat(),
        "ticker_outcome_price": ticker_end,
        "benchmark_outcome_price": benchmark_end,
        "ticker_total_return": ticker_return,
        "benchmark_total_return": benchmark_return,
        "excess_total_return": ticker_return - benchmark_return,
        "ticker_max_drawdown": _max_drawdown(ticker_window),
        "benchmark_max_drawdown": _max_drawdown(benchmark_window),
        "price_basis": "adjusted_close",
        "benchmark_total_return_proxy": True,
        "outcome_status": "completed",
        "historical_backtest_acceptance_allowed": False,
        "valid_for_backtest": False,
        "production_promotion_allowed": False,
        "valid_for_production": False,
    }
    return event, "completed"


def evaluate_observations(
    events: list[dict[str, Any]],
    *,
    price_cache: Path,
    as_of_date: pd.Timestamp,
    recorded_at_utc: str,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    observations = [event for event in events if event.get("event_type") == "signal_observed"]
    decision_dates = pd.to_datetime(
        [event.get("decision_date") for event in observations], errors="coerce"
    )
    valid_decision_dates = decision_dates[decision_dates.notna()]
    market_sessions = (
        load_nyse_sessions(pd.Timestamp(valid_decision_dates.min()), as_of_date)
        if len(valid_decision_dates)
        else pd.DatetimeIndex([])
    )
    references = {
        str(event["observation_id"]): event
        for event in events
        if event.get("event_type") == "next_close_reference_observed"
    }
    outcomes = {
        (str(event["observation_id"]), int(event["horizon_trading_days"])): event
        for event in events
        if event.get("event_type") == "forward_outcome_observed"
    }
    existing_ids = {str(event["event_id"]) for event in events}
    price_frames: dict[str, tuple[pd.DataFrame, str]] = {}

    def prices(ticker: str) -> tuple[pd.DataFrame, str]:
        if ticker not in price_frames:
            frame, basis = load_cached_prices(price_cache, ticker)
            clipped = frame.copy() if frame.empty else frame[frame.index <= as_of_date].copy()
            price_frames[ticker] = (clipped, basis)
        return price_frames[ticker]

    new_events: list[dict[str, Any]] = []
    evaluations: dict[str, dict[str, Any]] = {}
    for observation in observations:
        observation_id = str(observation["observation_id"])
        ticker_frame, ticker_basis = prices(str(observation["ticker"]))
        benchmark_frame, benchmark_basis = prices(str(observation["benchmark_ticker"]))
        reference = references.get(observation_id)
        if reference is None:
            reference, reference_status = _reference_candidate(
                observation,
                ticker_frame,
                ticker_basis,
                benchmark_frame,
                benchmark_basis,
                market_sessions,
                as_of_date=as_of_date,
                recorded_at_utc=recorded_at_utc,
            )
            if reference is not None and reference["event_id"] not in existing_ids:
                new_events.append(reference)
                existing_ids.add(reference["event_id"])
        else:
            reference_status = "reference_observed"
        evaluation: dict[str, Any] = {
            "reference_status": reference_status,
            "ticker_price_basis": ticker_basis,
            "benchmark_price_basis": benchmark_basis,
        }
        for horizon in HORIZONS:
            persisted = outcomes.get((observation_id, horizon))
            if persisted is not None:
                evaluation[f"outcome_{horizon}d_status"] = "completed"
                continue
            if reference is None:
                evaluation[f"outcome_{horizon}d_status"] = "pending_reference"
                continue
            outcome, status = _outcome_candidate(
                observation,
                reference,
                horizon,
                ticker_frame,
                benchmark_frame,
                market_sessions,
                as_of_date=as_of_date,
                recorded_at_utc=recorded_at_utc,
            )
            evaluation[f"outcome_{horizon}d_status"] = status
            if outcome is not None and outcome["event_id"] not in existing_ids:
                new_events.append(outcome)
                existing_ids.add(outcome["event_id"])
        evaluations[observation_id] = evaluation
    return new_events, evaluations


def build_current_status(
    events: list[dict[str, Any]], evaluations: dict[str, dict[str, Any]]
) -> pd.DataFrame:
    observations = [event for event in events if event.get("event_type") == "signal_observed"]
    references = {
        str(event["observation_id"]): event
        for event in events
        if event.get("event_type") == "next_close_reference_observed"
    }
    outcomes = {
        (str(event["observation_id"]), int(event["horizon_trading_days"])): event
        for event in events
        if event.get("event_type") == "forward_outcome_observed"
    }
    rows: list[dict[str, Any]] = []
    for observation in observations:
        observation_id = str(observation["observation_id"])
        snapshot = observation.get("signal_snapshot") or {}
        reference = references.get(observation_id) or {}
        evaluation = evaluations.get(observation_id) or {}
        row: dict[str, Any] = {
            "observation_id": observation_id,
            "decision_date": observation.get("decision_date"),
            "ticker": observation.get("ticker"),
            "source_observed_at_utc": observation.get("source_observed_at_utc"),
            "ledger_recorded_at_utc": observation.get("recorded_at_utc"),
            "signal_snapshot_sha256": observation.get("signal_snapshot_sha256"),
            "free_data_selection_rank": snapshot.get("free_data_selection_rank"),
            "free_data_selection_score": snapshot.get("free_data_selection_score"),
            "free_data_base_rank_score": snapshot.get("free_data_base_rank_score"),
            "free_data_forward_estimate_score": snapshot.get("free_data_forward_estimate_score"),
            "free_data_recent_actual_score": snapshot.get("free_data_recent_actual_score"),
            "free_data_evidence_coverage_count": snapshot.get("free_data_evidence_coverage_count"),
            "has_forward_estimate": snapshot.get("has_forward_estimate"),
            "labels": ",".join(observation.get("labels") or []),
            "benchmark_ticker": observation.get("benchmark_ticker"),
            "reference_status": "reference_observed" if reference else evaluation.get("reference_status", "pending_reference"),
            "next_close_date": reference.get("next_close_date"),
            "ticker_next_close_price": reference.get("ticker_next_close_price"),
            "benchmark_next_close_price": reference.get("benchmark_next_close_price"),
            "ticker_price_basis": reference.get("ticker_price_basis") or evaluation.get("ticker_price_basis"),
            "benchmark_price_basis": reference.get("benchmark_price_basis") or evaluation.get("benchmark_price_basis"),
            "benchmark_total_return_proxy": bool(reference.get("benchmark_total_return_proxy", False)),
            "forward_only": True,
            "pre_observation_signal_backfill_allowed": False,
            "historical_backtest_acceptance_allowed": False,
            "valid_for_backtest": False,
            "production_promotion_allowed": False,
            "valid_for_production": False,
            "live_trading_enabled": False,
        }
        for horizon in HORIZONS:
            outcome = outcomes.get((observation_id, horizon)) or {}
            prefix = f"outcome_{horizon}d"
            row[f"{prefix}_status"] = "completed" if outcome else evaluation.get(f"{prefix}_status", "pending_reference")
            row[f"{prefix}_date"] = outcome.get("outcome_date")
            row[f"{prefix}_ticker_total_return"] = outcome.get("ticker_total_return")
            row[f"{prefix}_benchmark_total_return"] = outcome.get("benchmark_total_return")
            row[f"{prefix}_excess_total_return"] = outcome.get("excess_total_return")
            row[f"{prefix}_ticker_max_drawdown"] = outcome.get("ticker_max_drawdown")
        rows.append(row)
    if not rows:
        return pd.DataFrame()
    status = pd.DataFrame(rows)
    status["_decision_sort"] = pd.to_datetime(status["decision_date"], errors="coerce")
    status["_rank_sort"] = pd.to_numeric(status["free_data_selection_rank"], errors="coerce")
    return status.sort_values(["_decision_sort", "_rank_sort", "ticker"], kind="stable").drop(
        columns=["_decision_sort", "_rank_sort"]
    ).reset_index(drop=True)


def schema_payload() -> dict[str, Any]:
    outcome_fields = {
        f"{horizon}d": {
            "trading_days_after_next_close": horizon,
            "fields": [
                "outcome_date",
                "ticker_total_return",
                "benchmark_total_return",
                "excess_total_return",
                "ticker_max_drawdown",
                "benchmark_max_drawdown",
            ],
        }
        for horizon in HORIZONS
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "event_log": EVENT_LOG_NAME,
        "event_log_format": "newline-delimited JSON",
        "event_log_append_only": True,
        "event_types": ["signal_observed", "next_close_reference_observed", "forward_outcome_observed"],
        "observation_identity": "sha256(schema_version|decision_date|ticker|signal_snapshot_sha256)",
        "signal_snapshot_schema_version": SIGNAL_SNAPSHOT_SCHEMA_VERSION,
        "signal_snapshot_columns": list(SIGNAL_SNAPSHOT_COLUMNS),
        "reference_rule": "first NYSE session strictly after decision_date; ticker and SPY must have exact adjusted closes",
        "price_basis_required": "adjusted close; SPY adjusted close is the total-return proxy",
        "outcomes": outcome_fields,
        "missing_price_policy": "pending on any exact NYSE-session price gap; never forward-fill, backfill, or shift",
        "first_observation_receipt_rule": "source observation UTC date must be the ledger receipt UTC date or previous UTC date",
        "pre_observation_signal_backfill_allowed": False,
        "historical_backtest_acceptance_allowed": False,
        "valid_for_backtest": False,
        "production_promotion_allowed": False,
        "valid_for_production": False,
        "live_trading_enabled": False,
        "target_books_mutated": False,
        "fullrun_dispatched": False,
    }


def build_summary(
    events: list[dict[str, Any]],
    status: pd.DataFrame,
    capture_audit: dict[str, Any],
    *,
    generated_at_utc: str,
    as_of_date: pd.Timestamp,
    appended_events: list[dict[str, Any]],
    output_dir: Path,
) -> dict[str, Any]:
    observations = [event for event in events if event.get("event_type") == "signal_observed"]
    event_counts = Counter(str(event.get("event_type")) for event in events)
    appended_counts = Counter(str(event.get("event_type")) for event in appended_events)
    coverage: dict[str, Any] = {
        "observation_count": len(observations),
        "unique_ticker_count": len({event.get("ticker") for event in observations}),
        "decision_date_count": len({event.get("decision_date") for event in observations}),
    }
    if status.empty:
        coverage["reference_status_counts"] = {}
        coverage["horizons"] = {f"{horizon}d": {"status_counts": {}, "completed_ratio": 0.0} for horizon in HORIZONS}
    else:
        coverage["reference_status_counts"] = {
            str(key): int(value) for key, value in status["reference_status"].value_counts(dropna=False).items()
        }
        coverage["horizons"] = {}
        for horizon in HORIZONS:
            column = f"outcome_{horizon}d_status"
            counts = {str(key): int(value) for key, value in status[column].value_counts(dropna=False).items()}
            coverage["horizons"][f"{horizon}d"] = {
                "status_counts": counts,
                "completed_ratio": round(counts.get("completed", 0) / max(len(status), 1), 6),
            }
    blocked = bool(capture_audit.get("blockers")) and not observations
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated_at_utc,
        "as_of_date": as_of_date.date().isoformat(),
        "status": "blocked_no_observations" if blocked else ("forward_paper_tracking_active" if observations else "idle_no_observations"),
        "ledger_mode": "append_only_event_log",
        "event_log": str(output_dir / EVENT_LOG_NAME),
        "current_status_csv": str(output_dir / "current_status.csv"),
        "schema_json": str(output_dir / "schema.json"),
        "event_counts": dict(event_counts),
        "appended_event_counts": dict(appended_counts),
        "capture_audit": capture_audit,
        "coverage": coverage,
        "benchmark_ticker": str(status["benchmark_ticker"].iloc[0]) if not status.empty else BENCHMARK_DEFAULT,
        "benchmark_proxy": "SPY adjusted-close total-return proxy",
        "missing_prices_and_unelapsed_outcomes_remain_pending": True,
        "pre_observation_signal_backfill_allowed": False,
        "historical_backtest_acceptance_allowed": False,
        "valid_for_backtest": False,
        "production_promotion_allowed": False,
        "valid_for_production": False,
        "live_trading_enabled": False,
        "target_books_mutated": False,
        "fullrun_dispatched": False,
    }


def render_report(summary: dict[str, Any]) -> str:
    coverage = summary.get("coverage") or {}
    lines = [
        "# Free Data Forward Paper Ledger",
        "",
        f"- status: `{summary.get('status')}`",
        f"- generated_at_utc: `{summary.get('generated_at_utc')}`",
        f"- as_of_date: `{summary.get('as_of_date')}`",
        f"- observations: `{coverage.get('observation_count', 0)}`",
        f"- unique tickers: `{coverage.get('unique_ticker_count', 0)}`",
        f"- reference statuses: `{json.dumps(coverage.get('reference_status_counts') or {}, sort_keys=True)}`",
        "",
        "## Outcome coverage",
        "",
        "| horizon | completed ratio | status counts |",
        "|---:|---:|---|",
    ]
    for horizon in HORIZONS:
        item = (coverage.get("horizons") or {}).get(f"{horizon}d") or {}
        lines.append(
            f"| {horizon}D | {float(item.get('completed_ratio') or 0.0):.2%} | "
            f"`{json.dumps(item.get('status_counts') or {}, sort_keys=True)}` |"
        )
    lines += [
        "",
        "## Contract",
        "",
        "- The JSONL event log is append-only; derived status files may be rebuilt.",
        "- Signals are captured only from a contemporaneously timestamped latest overlay artifact.",
        "- A novel signal is accepted only on its source-observation UTC date or the following UTC date.",
        "- A novel decision date older than the latest recorded decision date is blocked.",
        "- Entry is the first NYSE session strictly after the decision date, with exact ticker and SPY adjusted closes.",
        "- 21D/63D/126D outcomes use exact NYSE sessions and SPY adjusted close as a total-return proxy.",
        "- Any exchange-calendar price gap remains pending; no forward-fill or later-close substitution is used.",
        "- Labels: `forward_signal_observed`, `paper_ledger_candidate`, `not_backtest_acceptance`.",
        "- Historical backtest acceptance, production promotion, live trading, target-book mutation, and fullrun dispatch are all false.",
    ]
    blockers = (summary.get("capture_audit") or {}).get("blockers") or []
    if blockers:
        lines += ["", "## Capture blockers", ""] + [f"- `{item}`" for item in blockers]
    return "\n".join(lines) + "\n"


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def run(args: argparse.Namespace, *, now_utc: str | None = None) -> dict[str, Any]:
    recorded_at_utc = now_utc or utc_now()
    recorded_at = _utc_timestamp(recorded_at_utc)
    as_of_date = pd.Timestamp(args.as_of_date).normalize() if args.as_of_date else recorded_at.tz_localize(None).normalize()
    if as_of_date > recorded_at.tz_localize(None).normalize():
        raise ValueError("as_of_date cannot be later than the ledger run date")

    candidates_path = repo_path(args.candidates)
    summary_path = repo_path(args.overlay_summary) if args.overlay_summary else candidates_path.parent / "summary.json"
    price_cache = repo_path(args.price_cache)
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    event_log = output_dir / EVENT_LOG_NAME

    candidates = read_candidates(candidates_path)
    overlay_summary = read_json(summary_path)
    existing_events = read_events(event_log)
    persisted_market_dates = pd.to_datetime(
        [
            event.get("outcome_date") or event.get("next_close_date")
            for event in existing_events
            if event.get("outcome_date") or event.get("next_close_date")
        ],
        errors="coerce",
    )
    if len(persisted_market_dates) and persisted_market_dates.notna().any():
        latest_persisted_market_date = pd.Timestamp(persisted_market_dates.max()).normalize()
        if as_of_date < latest_persisted_market_date:
            raise ValueError(
                "as_of_date cannot precede an already persisted reference or outcome date in the append-only ledger"
            )
    observation_events, capture_audit = build_observation_events(
        candidates,
        overlay_summary,
        existing_events,
        recorded_at_utc=recorded_at.isoformat().replace("+00:00", "Z"),
        candidates_path=candidates_path,
        summary_path=summary_path,
        benchmark=normalize_ticker(args.benchmark) or BENCHMARK_DEFAULT,
    )
    append_events(event_log, observation_events)
    events_after_capture = existing_events + observation_events
    outcome_events, evaluations = evaluate_observations(
        events_after_capture,
        price_cache=price_cache,
        as_of_date=as_of_date,
        recorded_at_utc=recorded_at.isoformat().replace("+00:00", "Z"),
    )
    append_events(event_log, outcome_events)
    all_events = events_after_capture + outcome_events
    status = build_current_status(all_events, evaluations)
    status.to_csv(output_dir / "current_status.csv", index=False)
    write_json(output_dir / "schema.json", schema_payload())
    summary = build_summary(
        all_events,
        status,
        capture_audit,
        generated_at_utc=recorded_at.isoformat().replace("+00:00", "Z"),
        as_of_date=as_of_date,
        appended_events=observation_events + outcome_events,
        output_dir=output_dir,
    )
    write_json(output_dir / "summary.json", summary)
    (output_dir / "report.md").write_text(render_report(summary), encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", default="outputs/free_data_selection_overlay/selected_candidates.csv")
    parser.add_argument("--overlay-summary", default="")
    parser.add_argument("--price-cache", default="cache_prices")
    parser.add_argument("--output-dir", default="outputs/free_data_forward_paper_ledger")
    parser.add_argument("--benchmark", default=BENCHMARK_DEFAULT)
    parser.add_argument("--as-of-date", default="")
    return parser.parse_args(argv)


def main() -> int:
    summary = run(parse_args())
    return 2 if summary.get("status") == "blocked_no_observations" else 0


if __name__ == "__main__":
    raise SystemExit(main())
