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
from contextlib import contextmanager
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


SCHEMA_VERSION = "free-data-forward-paper-ledger-v2"
LEGACY_SCHEMA_VERSION = "free-data-forward-paper-ledger-v1"
OBSERVATION_IDENTITY_VERSION = "decision-date-ticker-v2"
SIGNAL_SNAPSHOT_SCHEMA_VERSION = "free-data-selection-signal-snapshot-v2"
COHORT_CONTRACT_SCHEMA_VERSION = "free-data-forward-paper-cohorts-v1"
HORIZONS = (21, 63, 126)
BENCHMARK_DEFAULT = "SPY"
EVENT_LOG_NAME = "ledger_events.jsonl"
COHORT_TOP_N = 30
CONTROL_RANK_START = 31
CONTROL_RANK_END = 60
BOOTSTRAP_REPLICATIONS = 2_000
REVIEW_THRESHOLDS = {
    "distinct_true_forward_tickers": 50,
    "resolved_outcomes": 200,
    "decision_week_blocks_21d": 12,
    "decision_week_blocks_63d": 8,
    "max_drawdown_degradation": 0.02,
}

SIGNAL_SNAPSHOT_COLUMNS = (
    "free_data_selection_rank",
    "free_data_base_selection_rank",
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


def load_nyse_schedule(start_date: pd.Timestamp, end_date: pd.Timestamp) -> pd.DataFrame | None:
    """Return normalized session dates and their actual UTC close timestamps."""
    if mcal is None:
        return None
    try:
        schedule = mcal.get_calendar("NYSE").schedule(
            start_date=pd.Timestamp(start_date).date().isoformat(),
            end_date=pd.Timestamp(end_date).date().isoformat(),
        )
    except Exception:
        return None
    if schedule.empty or "market_close" not in schedule.columns:
        return None
    out = schedule[["market_close"]].copy()
    index = pd.DatetimeIndex(pd.to_datetime(out.index, errors="coerce"))
    if index.tz is not None:
        index = index.tz_localize(None)
    out.index = index.normalize()
    out["market_close"] = pd.to_datetime(out["market_close"], errors="coerce", utc=True)
    return out[out.index.notna() & out["market_close"].notna()].sort_index()


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


def _finite_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def cohort_membership(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Derive fixed paper cohorts without treating missing evidence as positive."""
    overlay_rank = _finite_number(snapshot.get("free_data_selection_rank"))
    base_rank = _finite_number(snapshot.get("free_data_base_selection_rank"))
    # Legacy v1 observations did not persist the contemporaneous base rank.
    # Their already-recorded cohort membership remains readable, but new v2
    # captures are fail-closed below unless the new field is present.
    if base_rank is None:
        base_rank = _finite_number(snapshot.get("prior_free_data_selection_rank"))
    base_top30 = base_rank is not None and 1 <= base_rank <= COHORT_TOP_N
    overlay_top30 = overlay_rank is not None and 1 <= overlay_rank <= COHORT_TOP_N
    matched_control = overlay_rank is not None and CONTROL_RANK_START <= overlay_rank <= CONTROL_RANK_END
    has_forward = (_finite_number(snapshot.get("has_forward_estimate")) or 0.0) > 0.0
    true_forward = bool(
        has_forward
        and _truthy(snapshot.get("free_data_forward_estimate_evidence_present"))
        and _truthy(snapshot.get("estimate_revision_confirmed"))
    )
    memberships = [
        name
        for name, member in (
            ("base_top30", base_top30),
            ("overlay_top30", overlay_top30),
            ("matched_control_ranks31_60", matched_control),
        )
        if member
    ]
    return {
        "base_top30_member": base_top30,
        "overlay_top30_member": overlay_top30,
        "matched_control_member": matched_control,
        "true_forward_signal": true_forward,
        "forward_arm_member": bool(overlay_top30 and true_forward),
        "forward_signal_state": "true_forward" if true_forward else "neutral_missing_or_unconfirmed",
        "cohort_memberships": memberships,
    }


def persisted_observation_membership(observation: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any]:
    fields = (
        "base_top30_member",
        "overlay_top30_member",
        "matched_control_member",
        "true_forward_signal",
        "forward_arm_member",
        "forward_signal_state",
        "cohort_memberships",
    )
    if observation.get("schema_version") == SCHEMA_VERSION and all(field in observation for field in fields):
        memberships = observation.get("cohort_memberships")
        return {
            "base_top30_member": _truthy(observation.get("base_top30_member")),
            "overlay_top30_member": _truthy(observation.get("overlay_top30_member")),
            "matched_control_member": _truthy(observation.get("matched_control_member")),
            "true_forward_signal": _truthy(observation.get("true_forward_signal")),
            "forward_arm_member": _truthy(observation.get("forward_arm_member")),
            "forward_signal_state": str(observation.get("forward_signal_state") or "neutral_missing_or_unconfirmed"),
            "cohort_memberships": list(memberships) if isinstance(memberships, list) else [],
        }
    return cohort_membership(snapshot)


def select_cohort_candidates(candidates: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Keep the fixed base/overlay/control union; never promote missing signal rows."""
    audit: dict[str, Any] = {
        "source_ranked_rows": int(len(candidates)),
        "cohort_rows": 0,
        "cohort_counts": {
            "base_top30": 0,
            "overlay_top30": 0,
            "matched_control_ranks31_60": 0,
            "true_forward_signal": 0,
            "forward_arm": 0,
        },
        "missing_forward_evidence_policy": "neutral",
        "cohort_contract_schema_version": COHORT_CONTRACT_SCHEMA_VERSION,
    }
    if candidates.empty:
        return candidates.copy(), audit
    annotated = candidates.copy()
    memberships = annotated.apply(lambda row: cohort_membership(signal_snapshot(row)), axis=1)
    for column in (
        "base_top30_member",
        "overlay_top30_member",
        "matched_control_member",
        "true_forward_signal",
        "forward_arm_member",
    ):
        annotated[column] = memberships.map(lambda item: bool(item[column]))
    keep = annotated[["base_top30_member", "overlay_top30_member", "matched_control_member"]].any(axis=1)
    selected = annotated.loc[keep].copy()
    audit["cohort_rows"] = int(len(selected))
    audit["cohort_counts"] = {
        "base_top30": int(selected["base_top30_member"].sum()),
        "overlay_top30": int(selected["overlay_top30_member"].sum()),
        "matched_control_ranks31_60": int(selected["matched_control_member"].sum()),
        "true_forward_signal": int(selected["true_forward_signal"].sum()),
        "forward_arm": int(selected["forward_arm_member"].sum()),
    }
    return selected.drop(
        columns=[
            "base_top30_member",
            "overlay_top30_member",
            "matched_control_member",
            "true_forward_signal",
            "forward_arm_member",
        ]
    ), audit


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
    membership = cohort_membership(snapshot)
    snapshot_json = _canonical_json(snapshot)
    snapshot_sha256 = _sha256_text(snapshot_json)
    # One immutable observation per decision date and ticker.  Snapshot hashes
    # remain evidence, but must not create duplicate statistical observations.
    observation_key = f"{SCHEMA_VERSION}|{decision_date.date().isoformat()}|{ticker}"
    observation_id = _sha256_text(observation_key)[:24]
    return {
        "schema_version": SCHEMA_VERSION,
        "event_id": _sha256_text(f"signal_observed|{observation_id}"),
        "event_type": "signal_observed",
        "recorded_at_utc": recorded_at_utc,
        "observation_id": observation_id,
        "observation_identity_version": OBSERVATION_IDENTITY_VERSION,
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
        "cohort_contract_schema_version": COHORT_CONTRACT_SCHEMA_VERSION,
        **membership,
        "labels": [
            "forward_signal_observed",
            "paper_ledger_candidate",
            "not_backtest_acceptance",
            *[f"cohort_{name}" for name in membership["cohort_memberships"]],
            *(["true_forward_signal"] if membership["true_forward_signal"] else ["forward_signal_neutral"]),
        ],
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
    full_ranked_universe: bool,
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
    expected_candidates_hash_field = "ranked_universe_sha256" if full_ranked_universe else "selected_candidates_sha256"
    expected_candidates_hash = str(overlay_summary.get(expected_candidates_hash_field) or "")
    actual_candidates_hash = sha256_file(candidates_path) if candidates_path.is_file() else ""
    if not expected_candidates_hash:
        audit["blockers"].append(f"overlay_{expected_candidates_hash_field}_missing")
    elif expected_candidates_hash != actual_candidates_hash:
        audit["blockers"].append(f"overlay_{expected_candidates_hash_field}_mismatch")
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

    candidates_hash = actual_candidates_hash
    summary_hash = sha256_file(summary_path)
    existing_ids = {str(event.get("event_id")) for event in existing_events}
    existing_observations = [event for event in existing_events if event.get("event_type") == "signal_observed"]
    existing_by_decision_ticker = {
        (str(event.get("decision_date") or ""), normalize_ticker(event.get("ticker"))): event
        for event in existing_observations
    }
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
    novel: list[dict[str, Any]] = []
    conflicts: list[str] = []
    duplicates = 0
    for event in proposed:
        immutable_key = (str(event.get("decision_date") or ""), normalize_ticker(event.get("ticker")))
        prior = existing_by_decision_ticker.get(immutable_key)
        if prior is not None:
            if str(prior.get("signal_snapshot_sha256") or "") == str(event.get("signal_snapshot_sha256") or ""):
                duplicates += 1
            else:
                conflicts.append(f"{immutable_key[0]}:{immutable_key[1]}")
            continue
        if event["event_id"] in existing_ids:
            duplicates += 1
            continue
        novel.append(event)
    audit["duplicate_observation_rows"] = duplicates
    if conflicts:
        audit["blockers"].append(
            "immutable_decision_ticker_snapshot_conflict:" + ",".join(sorted(conflicts)[:20])
        )
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
    market_closes: pd.Series | None,
    *,
    as_of_date: pd.Timestamp,
    recorded_at_utc: str,
) -> tuple[dict[str, Any] | None, str]:
    if market_sessions is None or market_closes is None:
        return None, "pending_exchange_calendar_unavailable"
    if benchmark_basis != "adjusted_close":
        return None, "pending_benchmark_total_return_proxy_unavailable"
    if ticker_basis != "adjusted_close":
        return None, "pending_ticker_adjusted_price_unavailable"
    decision = pd.Timestamp(observation["decision_date"]).normalize()
    source_observed = _utc_timestamp(observation.get("source_observed_at_utc"))
    session_closes = market_closes.reindex(market_sessions)
    eligible = market_sessions[
        (market_sessions > decision)
        & (market_sessions <= as_of_date)
        & session_closes.gt(source_observed).to_numpy()
    ]
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
        "reference_rule": "first_NYSE_close_after_both_decision_date_and_source_observed_at_utc_with_exact_adjusted_closes",
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
    market_closes: pd.Series | None,
    *,
    as_of_date: pd.Timestamp,
    recorded_at_utc: str,
) -> tuple[dict[str, Any] | None, str]:
    if market_sessions is None or market_closes is None:
        return None, "pending_exchange_calendar_unavailable"
    reference_date = pd.Timestamp(reference["next_close_date"]).normalize()
    decision = pd.Timestamp(observation["decision_date"]).normalize()
    source_observed = _utc_timestamp(observation.get("source_observed_at_utc"))
    session_closes = market_closes.reindex(market_sessions)
    expected_reference_dates = market_sessions[
        (market_sessions > decision) & session_closes.gt(source_observed).to_numpy()
    ]
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
    market_schedule = (
        load_nyse_schedule(pd.Timestamp(valid_decision_dates.min()), as_of_date)
        if len(valid_decision_dates)
        else pd.DataFrame(columns=["market_close"])
    )
    market_sessions = None if market_schedule is None else pd.DatetimeIndex(market_schedule.index)
    market_closes = None if market_schedule is None else market_schedule["market_close"]
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
                market_closes,
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
                market_closes,
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
        membership = persisted_observation_membership(observation, snapshot)
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
            "base_top30_member": membership["base_top30_member"],
            "overlay_top30_member": membership["overlay_top30_member"],
            "matched_control_member": membership["matched_control_member"],
            "true_forward_signal": membership["true_forward_signal"],
            "forward_arm_member": membership["forward_arm_member"],
            "forward_signal_state": membership["forward_signal_state"],
            "cohort_memberships": ",".join(membership["cohort_memberships"]),
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


def _cohort_mask(status: pd.DataFrame, column: str) -> pd.Series:
    if column not in status.columns:
        return pd.Series(False, index=status.index, dtype=bool)
    return status[column].map(_truthy).astype(bool)


def _completed_cohort(status: pd.DataFrame, cohort_column: str, horizon: int) -> pd.DataFrame:
    if status.empty:
        return status.copy()
    outcome_status = f"outcome_{horizon}d_status"
    if outcome_status not in status.columns:
        return status.iloc[0:0].copy()
    return status.loc[_cohort_mask(status, cohort_column) & status[outcome_status].eq("completed")].copy()


def _week_block_outcome_metrics(frame: pd.DataFrame, horizon: int) -> dict[str, Any]:
    excess_column = f"outcome_{horizon}d_excess_total_return"
    drawdown_column = f"outcome_{horizon}d_ticker_max_drawdown"
    if frame.empty or excess_column not in frame.columns:
        return {
            "completed_count": 0,
            "decision_week_block_count": 0,
            "mean_spy_excess_return": None,
            "median_spy_excess_return": None,
            "week_block_bootstrap_mean_lower_95": None,
            "mean_ticker_max_drawdown": None,
        }
    work = frame[["decision_date", excess_column, drawdown_column]].copy()
    work["decision_date"] = pd.to_datetime(work["decision_date"], errors="coerce")
    work["excess"] = pd.to_numeric(work[excess_column], errors="coerce")
    work["drawdown"] = pd.to_numeric(work[drawdown_column], errors="coerce")
    work = work[work["decision_date"].notna() & work["excess"].notna() & np.isfinite(work["excess"])].copy()
    if work.empty:
        return {
            "completed_count": 0,
            "decision_week_block_count": 0,
            "mean_spy_excess_return": None,
            "median_spy_excess_return": None,
            "week_block_bootstrap_mean_lower_95": None,
            "mean_ticker_max_drawdown": None,
        }
    work["decision_week"] = work["decision_date"].dt.to_period("W-SUN").astype(str)
    week_means = work.groupby("decision_week", sort=True)["excess"].mean().to_numpy(dtype=float)
    bootstrap_lower: float | None = None
    if len(week_means):
        seed = int(_sha256_text(f"forward-paper-week-bootstrap|{horizon}")[:8], 16)
        rng = np.random.default_rng(seed)
        sampled = rng.choice(
            week_means,
            size=(BOOTSTRAP_REPLICATIONS, len(week_means)),
            replace=True,
        )
        bootstrap_lower = float(np.quantile(sampled.mean(axis=1), 0.025))
    finite_drawdown = work["drawdown"].dropna()
    finite_drawdown = finite_drawdown[np.isfinite(finite_drawdown)]
    return {
        "completed_count": int(len(work)),
        "decision_week_block_count": int(len(week_means)),
        "mean_spy_excess_return": float(work["excess"].mean()),
        "median_spy_excess_return": float(work["excess"].median()),
        "week_block_bootstrap_mean_lower_95": bootstrap_lower,
        "mean_ticker_max_drawdown": float(finite_drawdown.mean()) if len(finite_drawdown) else None,
    }


def _paired_week_drawdown_metrics(
    forward: pd.DataFrame,
    control: pd.DataFrame,
    horizon: int,
) -> dict[str, Any]:
    """Compare drawdown only within decision weeks represented by both arms."""
    column = f"outcome_{horizon}d_ticker_max_drawdown"

    def weekly(frame: pd.DataFrame, label: str) -> pd.DataFrame:
        if frame.empty or column not in frame.columns:
            return pd.DataFrame(columns=["decision_week", label])
        work = frame[["decision_date", column]].copy()
        work["decision_date"] = pd.to_datetime(work["decision_date"], errors="coerce")
        work[label] = pd.to_numeric(work[column], errors="coerce")
        work = work[
            work["decision_date"].notna() & work[label].notna() & np.isfinite(work[label])
        ].copy()
        if work.empty:
            return pd.DataFrame(columns=["decision_week", label])
        work["decision_week"] = work["decision_date"].dt.to_period("W-SUN").astype(str)
        return work.groupby("decision_week", as_index=False, sort=True)[label].mean()

    paired = weekly(forward, "forward_drawdown").merge(
        weekly(control, "control_drawdown"), on="decision_week", how="inner", validate="one_to_one"
    )
    if paired.empty:
        return {
            "paired_decision_week_block_count": 0,
            "mean_paired_week_drawdown_degradation": None,
            "max_paired_week_drawdown_degradation": None,
        }
    # Drawdowns are negative.  control - forward is positive only when the
    # forward arm is worse within the same decision week.
    degradation = paired["control_drawdown"] - paired["forward_drawdown"]
    return {
        "paired_decision_week_block_count": int(len(paired)),
        "mean_paired_week_drawdown_degradation": float(degradation.mean()),
        "max_paired_week_drawdown_degradation": float(degradation.max()),
    }


def build_review_readiness(status: pd.DataFrame) -> dict[str, Any]:
    """Build deterministic, paper-only readiness gates for the true-forward arm."""
    cohort_columns = {
        "base_top30": "base_top30_member",
        "overlay_top30": "overlay_top30_member",
        "matched_control_ranks31_60": "matched_control_member",
        "true_forward_arm": "forward_arm_member",
    }
    cohort_metrics: dict[str, Any] = {}
    for cohort_name, cohort_column in cohort_columns.items():
        cohort_metrics[cohort_name] = {
            f"{horizon}d": _week_block_outcome_metrics(
                _completed_cohort(status, cohort_column, horizon), horizon
            )
            for horizon in HORIZONS
        }

    true_forward_mask = _cohort_mask(status, "true_forward_signal") if not status.empty else pd.Series(dtype=bool)
    forward_arm_mask = _cohort_mask(status, "forward_arm_member") if not status.empty else pd.Series(dtype=bool)
    observed_true_forward_tickers = (
        int(status.loc[true_forward_mask, "ticker"].astype(str).nunique()) if not status.empty else 0
    )
    distinct_true_forward_tickers = (
        int(status.loc[forward_arm_mask, "ticker"].astype(str).nunique()) if not status.empty else 0
    )
    resolved_horizon_rows = sum(
        int(
            (
                forward_arm_mask
                & status[f"outcome_{horizon}d_status"].eq("completed")
            ).sum()
        )
        for horizon in HORIZONS
    ) if not status.empty else 0
    resolved_primary_63d_observations = 0
    if not status.empty and "outcome_63d_status" in status.columns:
        primary = status.loc[
            forward_arm_mask & status["outcome_63d_status"].eq("completed"),
            ["decision_date", "ticker"],
        ].drop_duplicates()
        resolved_primary_63d_observations = int(len(primary))
    resolved_observations = 0
    if not status.empty:
        any_completed = pd.Series(False, index=status.index, dtype=bool)
        for horizon in HORIZONS:
            any_completed |= status[f"outcome_{horizon}d_status"].eq("completed")
        resolved_observations = int((forward_arm_mask & any_completed).sum())

    forward_metrics = cohort_metrics["true_forward_arm"]
    control_metrics = cohort_metrics["matched_control_ranks31_60"]
    drawdown_degradation: dict[str, float | None] = {}
    paired_drawdown_metrics: dict[str, dict[str, Any]] = {}
    for horizon in (21, 63):
        paired = _paired_week_drawdown_metrics(
            _completed_cohort(status, "forward_arm_member", horizon),
            _completed_cohort(status, "matched_control_member", horizon),
            horizon,
        )
        paired_drawdown_metrics[f"{horizon}d"] = paired
        drawdown_degradation[f"{horizon}d"] = paired["mean_paired_week_drawdown_degradation"]

    def check(actual: Any, required: str, passed: bool) -> dict[str, Any]:
        return {"actual": actual, "required": required, "passed": bool(passed)}

    sample_checks = {
        "distinct_true_forward_tickers": check(
            distinct_true_forward_tickers,
            f">={REVIEW_THRESHOLDS['distinct_true_forward_tickers']}",
            distinct_true_forward_tickers >= REVIEW_THRESHOLDS["distinct_true_forward_tickers"],
        ),
        "resolved_outcomes": check(
            resolved_primary_63d_observations,
            f">={REVIEW_THRESHOLDS['resolved_outcomes']} unique completed 63D decision-ticker observations",
            resolved_primary_63d_observations >= REVIEW_THRESHOLDS["resolved_outcomes"],
        ),
        "decision_week_blocks_21d": check(
            forward_metrics["21d"]["decision_week_block_count"],
            f">={REVIEW_THRESHOLDS['decision_week_blocks_21d']}",
            forward_metrics["21d"]["decision_week_block_count"] >= REVIEW_THRESHOLDS["decision_week_blocks_21d"],
        ),
        "decision_week_blocks_63d": check(
            forward_metrics["63d"]["decision_week_block_count"],
            f">={REVIEW_THRESHOLDS['decision_week_blocks_63d']}",
            forward_metrics["63d"]["decision_week_block_count"] >= REVIEW_THRESHOLDS["decision_week_blocks_63d"],
        ),
        "matched_control_decision_week_blocks_21d": check(
            control_metrics["21d"]["decision_week_block_count"],
            f">={REVIEW_THRESHOLDS['decision_week_blocks_21d']}",
            control_metrics["21d"]["decision_week_block_count"] >= REVIEW_THRESHOLDS["decision_week_blocks_21d"],
        ),
        "matched_control_decision_week_blocks_63d": check(
            control_metrics["63d"]["decision_week_block_count"],
            f">={REVIEW_THRESHOLDS['decision_week_blocks_63d']}",
            control_metrics["63d"]["decision_week_block_count"] >= REVIEW_THRESHOLDS["decision_week_blocks_63d"],
        ),
        "paired_drawdown_decision_week_blocks_21d": check(
            paired_drawdown_metrics["21d"]["paired_decision_week_block_count"],
            f">={REVIEW_THRESHOLDS['decision_week_blocks_21d']}",
            paired_drawdown_metrics["21d"]["paired_decision_week_block_count"] >= REVIEW_THRESHOLDS["decision_week_blocks_21d"],
        ),
        "paired_drawdown_decision_week_blocks_63d": check(
            paired_drawdown_metrics["63d"]["paired_decision_week_block_count"],
            f">={REVIEW_THRESHOLDS['decision_week_blocks_63d']}",
            paired_drawdown_metrics["63d"]["paired_decision_week_block_count"] >= REVIEW_THRESHOLDS["decision_week_blocks_63d"],
        ),
    }
    evidence_checks: dict[str, dict[str, Any]] = {}
    for horizon in (21, 63):
        metrics = forward_metrics[f"{horizon}d"]
        mean_value = metrics["mean_spy_excess_return"]
        median_value = metrics["median_spy_excess_return"]
        lower_value = metrics["week_block_bootstrap_mean_lower_95"]
        degradation = drawdown_degradation[f"{horizon}d"]
        evidence_checks[f"mean_spy_excess_positive_{horizon}d"] = check(
            mean_value, ">0", mean_value is not None and mean_value > 0.0
        )
        evidence_checks[f"median_spy_excess_positive_{horizon}d"] = check(
            median_value, ">0", median_value is not None and median_value > 0.0
        )
        evidence_checks[f"week_block_bootstrap_lower_nonnegative_{horizon}d"] = check(
            lower_value, ">=0", lower_value is not None and lower_value >= 0.0
        )
        evidence_checks[f"drawdown_degradation_at_most_2pp_{horizon}d"] = check(
            degradation,
            f"<={REVIEW_THRESHOLDS['max_drawdown_degradation']}",
            degradation is not None and degradation <= REVIEW_THRESHOLDS["max_drawdown_degradation"],
        )
    direction_126d = forward_metrics["126d"]["mean_spy_excess_return"]
    evidence_checks["mean_spy_excess_direction_positive_126d"] = check(
        direction_126d, ">0", direction_126d is not None and direction_126d > 0.0
    )

    sample_ready = all(item["passed"] for item in sample_checks.values())
    evidence_ready = all(item["passed"] for item in evidence_checks.values())
    readiness_status = (
        "REVIEW_READY_PAPER_ONLY"
        if sample_ready and evidence_ready
        else ("EVIDENCE_GATE_FAILED" if sample_ready else "UNDERPOWERED")
    )
    return {
        "status": readiness_status,
        "review_ready": bool(sample_ready and evidence_ready),
        "paper_only": True,
        "valid_for_historical_backtest_acceptance": False,
        "distinct_true_forward_ticker_count": distinct_true_forward_tickers,
        "observed_true_forward_ticker_count_all_cohorts": observed_true_forward_tickers,
        "resolved_outcome_count": int(resolved_primary_63d_observations),
        "resolved_observation_count": int(resolved_observations),
        "resolved_horizon_row_count_diagnostic": int(resolved_horizon_rows),
        "resolved_outcome_definition": "unique completed 63D true-forward-arm decision-date/ticker observations",
        "drawdown_degradation_vs_matched_control": drawdown_degradation,
        "paired_week_drawdown_metrics": paired_drawdown_metrics,
        "sample_checks": sample_checks,
        "evidence_checks": evidence_checks,
        "cohort_metrics": cohort_metrics,
        "bootstrap": {
            "unit": "decision_week",
            "statistic": "mean of decision-week mean SPY excess returns",
            "replications": BOOTSTRAP_REPLICATIONS,
            "confidence": 0.95,
            "deterministic_seed": True,
        },
    }


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
        "observation_identity_version": OBSERVATION_IDENTITY_VERSION,
        "observation_identity": "sha256(schema_version|decision_date|ticker)",
        "legacy_observation_identity": "v1 sha256(schema_version|decision_date|ticker|signal_snapshot_sha256) remains readable",
        "legacy_schema_version": LEGACY_SCHEMA_VERSION,
        "signal_snapshot_schema_version": SIGNAL_SNAPSHOT_SCHEMA_VERSION,
        "signal_snapshot_columns": list(SIGNAL_SNAPSHOT_COLUMNS),
        "cohort_contract": {
            "schema_version": COHORT_CONTRACT_SCHEMA_VERSION,
            "source": "full contemporaneous ranked universe when available",
            "base_top30": "free_data_base_selection_rank between 1 and 30 inclusive",
            "overlay_top30": "free_data_selection_rank between 1 and 30 inclusive",
            "matched_control_ranks31_60": "free_data_selection_rank between 31 and 60 inclusive",
            "observation_universe": "union of base_top30, overlay_top30, and matched_control_ranks31_60",
            "migration_policy": (
                "preserve pre-contract observations exactly; do not overwrite or augment an existing "
                "decision-date/ticker snapshot; complete 30/30/30 capture starts on the next distinct decision date"
            ),
            "true_forward_signal": (
                "has_forward_estimate > 0 and free_data_forward_estimate_evidence_present and "
                "estimate_revision_confirmed"
            ),
            "forward_arm": "overlay_top30 and true_forward_signal",
            "missing_forward_evidence_policy": "neutral_missing_or_unconfirmed",
        },
        "review_readiness_contract": {
            "thresholds": REVIEW_THRESHOLDS,
            "resolved_outcome_definition": (
                "unique completed 63D true-forward-arm decision-date/ticker observations"
            ),
            "week_block_bootstrap_replications": BOOTSTRAP_REPLICATIONS,
            "week_block_bootstrap_statistic": "mean of decision-week mean SPY excess returns",
            "required_21d_and_63d": (
                "mean and median SPY excess > 0, week-block bootstrap lower 95% >= 0, "
                "paired decision-week mean drawdown degradation vs ranks31-60 control <= 0.02"
            ),
            "required_126d": "mean SPY excess return > 0",
            "paper_only": True,
        },
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
    review_readiness = build_review_readiness(status)
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
        "review_readiness": review_readiness,
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
        f"- review readiness: `{(summary.get('review_readiness') or {}).get('status', 'UNDERPOWERED')}`",
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
        "## Paper review gate",
        "",
        f"- Distinct true-forward tickers: `{(summary.get('review_readiness') or {}).get('distinct_true_forward_ticker_count', 0)}` / `{REVIEW_THRESHOLDS['distinct_true_forward_tickers']}`",
        f"- Resolved primary 63D decision-ticker outcomes: `{(summary.get('review_readiness') or {}).get('resolved_outcome_count', 0)}` / `{REVIEW_THRESHOLDS['resolved_outcomes']}`",
        f"- 21D decision-week blocks: `{((((summary.get('review_readiness') or {}).get('cohort_metrics') or {}).get('true_forward_arm') or {}).get('21d') or {}).get('decision_week_block_count', 0)}` / `{REVIEW_THRESHOLDS['decision_week_blocks_21d']}`",
        f"- 63D decision-week blocks: `{((((summary.get('review_readiness') or {}).get('cohort_metrics') or {}).get('true_forward_arm') or {}).get('63d') or {}).get('decision_week_block_count', 0)}` / `{REVIEW_THRESHOLDS['decision_week_blocks_63d']}`",
        "- The forward arm contains only overlay-top-30 rows with confirmed true-forward evidence; missing evidence is neutral.",
        "- REVIEW_READY_PAPER_ONLY is never historical backtest acceptance or production promotion.",
        "",
        "## Contract",
        "",
        "- The JSONL event log is append-only; derived status files may be rebuilt.",
        "- Signals are captured only from a contemporaneously timestamped latest overlay artifact.",
        "- A novel signal is accepted only on its source-observation UTC date or the following UTC date.",
        "- A novel decision date older than the latest recorded decision date is blocked.",
        "- Entry is the first NYSE session strictly after the decision date, with exact ticker and SPY adjusted closes.",
        "- 21D/63D/126D outcomes use exact NYSE sessions and SPY adjusted close as a total-return proxy.",
        "- Each new decision date is accepted only when a full ranked universe supplies exactly base top 30, overlay top 30, and overlay ranks 31-60 control cohorts.",
        "- Pre-contract observations are preserved without retroactive cohort augmentation; the complete v2 cohort starts on the next distinct decision date.",
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


def _run_unlocked(args: argparse.Namespace, *, now_utc: str | None = None) -> dict[str, Any]:
    recorded_at_utc = now_utc or utc_now()
    recorded_at = _utc_timestamp(recorded_at_utc)
    as_of_date = pd.Timestamp(args.as_of_date).normalize() if args.as_of_date else recorded_at.tz_localize(None).normalize()
    if as_of_date > recorded_at.tz_localize(None).normalize():
        raise ValueError("as_of_date cannot be later than the ledger run date")

    candidates_path = repo_path(args.candidates)
    summary_path = repo_path(args.overlay_summary) if args.overlay_summary else candidates_path.parent / "summary.json"
    ranked_universe_arg = str(getattr(args, "ranked_universe", "") or "").strip()
    default_ranked_universe = candidates_path.parent / "ranked_universe.csv"
    ranked_universe_path = (
        repo_path(ranked_universe_arg)
        if ranked_universe_arg
        else (default_ranked_universe if default_ranked_universe.exists() else candidates_path)
    )
    full_ranked_universe = bool(
        ranked_universe_path.is_file()
        and (bool(ranked_universe_arg) or default_ranked_universe.exists())
    )
    allow_incomplete_test_capture = bool(getattr(args, "_test_allow_incomplete_cohorts", False))
    price_cache = repo_path(args.price_cache)
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    event_log = output_dir / EVENT_LOG_NAME

    source_candidates = read_candidates(ranked_universe_path)
    candidates, cohort_audit = select_cohort_candidates(source_candidates)
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
    required_counts = {
        "base_top30": COHORT_TOP_N,
        "overlay_top30": COHORT_TOP_N,
        "matched_control_ranks31_60": CONTROL_RANK_END - CONTROL_RANK_START + 1,
    }
    observed_counts = cohort_audit.get("cohort_counts") or {}
    cohort_capture_blockers: list[str] = []
    if not full_ranked_universe:
        cohort_capture_blockers.append("full_ranked_universe_required_for_new_decision")
    if "free_data_base_selection_rank" not in source_candidates.columns:
        cohort_capture_blockers.append("contemporaneous_base_selection_rank_required")
    for name, expected in required_counts.items():
        actual = int(observed_counts.get(name, 0) or 0)
        if actual != expected:
            cohort_capture_blockers.append(f"incomplete_fixed_cohort:{name}:{actual}!={expected}")
    if cohort_capture_blockers and not allow_incomplete_test_capture:
        observation_events = []
        capture_audit = {
            "candidate_rows": int(len(candidates)),
            "new_observation_rows": 0,
            "duplicate_observation_rows": 0,
            "blocked_observation_rows": int(len(candidates)),
            "blockers": cohort_capture_blockers,
            "outcome_refresh_allowed_for_existing_observations": True,
        }
    else:
        observation_events, capture_audit = build_observation_events(
            candidates,
            overlay_summary,
            existing_events,
            recorded_at_utc=recorded_at.isoformat().replace("+00:00", "Z"),
            candidates_path=ranked_universe_path,
            summary_path=summary_path,
            benchmark=normalize_ticker(args.benchmark) or BENCHMARK_DEFAULT,
            full_ranked_universe=full_ranked_universe,
        )
        if allow_incomplete_test_capture and cohort_capture_blockers:
            capture_audit["test_only_incomplete_cohort_bypass"] = cohort_capture_blockers
    capture_audit["cohort_capture"] = {
        **cohort_audit,
        "source_ranked_universe_path": str(ranked_universe_path),
        "source_mode": "full_ranked_universe" if full_ranked_universe else "candidate_file_fallback",
        "required_exact_cohort_counts": required_counts,
        "complete_fixed_cohorts": not cohort_capture_blockers,
    }
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


@contextmanager
def exclusive_ledger_lock(output_dir: Path):
    """Serialize read/append cycles so two writers cannot duplicate events."""
    output_dir.mkdir(parents=True, exist_ok=True)
    lock_path = output_dir / ".forward_paper_ledger.lock"
    try:
        descriptor = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise RuntimeError(f"forward paper ledger is already locked: {lock_path}") from exc
    try:
        os.write(descriptor, f"pid={os.getpid()} utc={utc_now()}\n".encode("utf-8"))
        os.fsync(descriptor)
        yield
    finally:
        os.close(descriptor)
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


def run(args: argparse.Namespace, *, now_utc: str | None = None) -> dict[str, Any]:
    output_dir = repo_path(args.output_dir)
    with exclusive_ledger_lock(output_dir):
        return _run_unlocked(args, now_utc=now_utc)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", default="outputs/free_data_selection_overlay/selected_candidates.csv")
    parser.add_argument(
        "--ranked-universe",
        default="",
        help="Full contemporaneous ranked universe; defaults to ranked_universe.csv beside --candidates when present.",
    )
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
