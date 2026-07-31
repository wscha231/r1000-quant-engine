#!/usr/bin/env python3
"""Persist exact-close OHLCV pattern observations and forward outcomes.

This is a research-only sidecar.  It records descriptive return-transition
fingerprints and resolves them only from an exact archived NYSE target session.
It cannot write portfolio targets, orders, cash, or champion state.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
import time
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd
import pandas_market_calendars as mcal


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.build_run287_holding_risk_watch import (  # noqa: E402
    sha256_file,
)


SCHEMA_VERSION = "run287-ohlcv-pattern-memory-v1"
READY_STATUS = "READY_OHLCV_PATTERN_MEMORY_RESEARCH_ONLY"
BLOCKED_STATUS = "BLOCKED_OHLCV_PATTERN_MEMORY"
OBSERVATION_SCHEMA_VERSION = "run287-ohlcv-pattern-observation-v1"
OUTCOME_SCHEMA_VERSION = "run287-ohlcv-pattern-outcome-v1"

FEATURE_FIELDS = (
    "prior_return_1d",
    "return_1d",
    "return_2d",
    "return_transition_signature",
    "prior_down_current_up",
    "prior_loss_recovery_fraction",
    "gap_return",
    "intraday_return",
    "close_location_in_bar",
    "true_range_atr14",
    "prior_true_range_atr14",
    "atr14_pct",
    "realized_vol_20d",
    "realized_vol_63d",
    "realized_vol_ratio_20d_63d",
    "realized_vol_20d_past_percentile",
    "volume_z_20d_past_only",
    "volume_ratio_20d_past_only",
    "return_5d",
    "return_21d",
    "return_63d",
    "return_126d",
    "return_252d",
    "above_ma20",
    "above_ma50",
    "above_ma200",
    "location_state",
    "range_position_21d",
    "range_position_63d",
    "range_position_126d",
    "range_position_252d",
    "vix_level",
    "vix_return_1d",
    "vix_z_63d",
    "vix_past_percentile",
    "market_risk_off_confirmed",
    "index_damage_confirmed",
    "is_held",
    "is_current_selector",
    "is_proposed_entry",
    "portfolios",
    "marked_weight_max",
    "advisory_weight_max",
    "shadow_action",
    "shadow_reason_codes",
    "data_reason",
)


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def json_clean(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): json_clean(nested) for key, nested in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_clean(nested) for nested in value]
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return finite(value)
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return None
    return value


def canonical_hash(value: Any) -> str:
    payload = json.dumps(
        json_clean(value),
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def fingerprint(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.resolve()) if path.exists() else str(path),
        "exists": path.is_file(),
        "bytes": int(path.stat().st_size) if path.is_file() else 0,
        "sha256": sha256_file(path) if path.is_file() else "",
    }


def git_head() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            text=True,
            timeout=10,
        ).strip()
    except Exception:
        return ""


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object required:{path}")
    return payload


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    staged = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with staged.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(staged, path)
    finally:
        staged.unlink(missing_ok=True)


def atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    atomic_write_text(
        path,
        json.dumps(
            json_clean(dict(payload)),
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n",
    )


def resolve_output(
    summary_path: Path,
    summary: Mapping[str, Any],
    key: str,
) -> tuple[Path, dict[str, Any]]:
    record = (summary.get("outputs") or {}).get(key) or {}
    raw = str(record.get("path") or "")
    path = Path(raw)
    if raw and not path.is_absolute():
        path = summary_path.parent / path
    audit = fingerprint(path)
    expected = str(record.get("sha256") or "").lower()
    audit.update(expected_sha256=expected, hash_matches=audit["sha256"] == expected)
    if not expected or audit["exists"] is not True or audit["hash_matches"] is not True:
        raise ValueError(f"source output fingerprint mismatch:{key}")
    return path, audit


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line_number, raw in enumerate(
        path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        if not raw.strip():
            continue
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError(f"JSONL object required:{path}:{line_number}")
        rows.append(payload)
    return rows


def event_without_chain(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        str(key): value
        for key, value in row.items()
        if key not in {"previous_event_hash", "event_hash"}
    }


def validate_chain(
    rows: Iterable[Mapping[str, Any]],
    *,
    expected_schema: str,
    contract_sha256: str,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], str]:
    accepted: list[dict[str, Any]] = []
    identities: dict[str, dict[str, Any]] = {}
    previous = ""
    for index, raw in enumerate(rows):
        row = dict(raw)
        if str(row.get("schema_version") or "") != expected_schema:
            raise ValueError(f"archive schema drift:{index}")
        if str(row.get("memory_contract_sha256") or "") != contract_sha256:
            raise ValueError(f"archive contract drift:{index}")
        identity = str(row.get("event_id") or "")
        if not identity or identity in identities:
            raise ValueError(f"archive event identity invalid:{index}")
        if str(row.get("previous_event_hash") or "") != previous:
            raise ValueError(f"archive chain parent mismatch:{index}")
        expected_hash = canonical_hash(
            {**event_without_chain(row), "previous_event_hash": previous}
        )
        if str(row.get("event_hash") or "") != expected_hash:
            raise ValueError(f"archive event hash mismatch:{index}")
        accepted.append(row)
        identities[identity] = row
        previous = expected_hash
    return accepted, identities, previous


def attach_chain(
    row: Mapping[str, Any],
    previous_event_hash: str,
) -> dict[str, Any]:
    payload = {
        **json_clean(dict(row)),
        "previous_event_hash": previous_event_hash,
    }
    payload["event_hash"] = canonical_hash(payload)
    return payload


def append_rows(path: Path, rows: Iterable[Mapping[str, Any]]) -> int:
    payloads = list(rows)
    if not payloads:
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        for payload in payloads:
            handle.write(
                json.dumps(
                    json_clean(dict(payload)),
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                )
                + "\n"
            )
        handle.flush()
        os.fsync(handle.fileno())
    return len(payloads)


@lru_cache(maxsize=None)
def exact_target_session(origin: str, horizon: int) -> str:
    start = pd.Timestamp(origin)
    schedule = mcal.get_calendar("NYSE").schedule(
        start_date=start.date().isoformat(),
        end_date=(start + pd.Timedelta(days=400)).date().isoformat(),
    )
    sessions = [
        pd.Timestamp(value).date().isoformat()
        for value in schedule.index
        if pd.Timestamp(value).date().isoformat() > origin
    ]
    if len(sessions) < horizon:
        raise ValueError(f"NYSE horizon unavailable:{origin}:{horizon}")
    return sessions[horizon - 1]


def source_observations(
    *,
    valuation_date: str,
    summary: Mapping[str, Any],
    security_rows: list[Mapping[str, Any]],
    benchmark_rows: list[Mapping[str, Any]],
    contract_sha256: str,
    source_summary_sha256: str,
    source_observations_sha256: str,
    source_benchmark_sha256: str,
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    allowed_patterns = {
        "DOWN_TO_UP_REVERSAL",
        "UP_TO_DOWN_REVERSAL",
        "CONTINUED_DOWN",
        "CONTINUED_UP",
        "FLAT_OR_INSUFFICIENT",
    }
    common = {
        "schema_version": OBSERVATION_SCHEMA_VERSION,
        "event_type": "OBSERVATION",
        "as_of_date": valuation_date,
        "available_from": summary.get("available_from"),
        "observation_accepted_at_utc": (
            (summary.get("forward_observation_window") or {}).get(
                "observation_accepted_at_utc"
            )
        ),
        "memory_contract_sha256": contract_sha256,
        "source_summary_sha256": source_summary_sha256,
        "source_observations_sha256": source_observations_sha256,
        "source_benchmark_sha256": source_benchmark_sha256,
        "research_only": True,
        "portfolio_transition_allowed": False,
        "orders_generated": False,
        "target_books_mutated": False,
        "champion_changed": False,
    }
    for source_kind, rows in (
        ("SECURITY", security_rows),
        ("BENCHMARK", benchmark_rows),
    ):
        for raw in rows:
            clean = json_clean(dict(raw))
            ticker = str(clean.get("ticker") or "").strip().upper()
            if not ticker:
                raise ValueError(f"source ticker missing:{source_kind}")
            row_date = str(clean.get("as_of_date") or valuation_date)
            if row_date != valuation_date:
                raise ValueError(f"source row date mismatch:{source_kind}:{ticker}")
            close = finite(clean.get("close"))
            pattern = str(
                clean.get("return_transition_signature")
                or "FLAT_OR_INSUFFICIENT"
            )
            if pattern not in allowed_patterns:
                raise ValueError(
                    f"source pattern invalid:{source_kind}:{ticker}:{pattern}"
                )
            payload = {
                **common,
                "source_kind": source_kind,
                "ticker": ticker,
                "observed_close": close,
                "data_ready": bool(
                    close is not None and not str(clean.get("data_reason") or "")
                ),
                "source_payload_sha256": canonical_hash(clean),
                **{
                    field: clean.get(field)
                    for field in FEATURE_FIELDS
                    if field in clean
                },
                "return_transition_signature": pattern,
            }
            payload["event_id"] = canonical_hash(
                {
                    "schema_version": OBSERVATION_SCHEMA_VERSION,
                    "source_kind": source_kind,
                    "ticker": ticker,
                    "as_of_date": valuation_date,
                    "memory_contract_sha256": contract_sha256,
                }
            )
            output.append(payload)
    ordered = sorted(
        output,
        key=lambda row: (str(row["source_kind"]), str(row["ticker"])),
    )
    identities = [str(row["event_id"]) for row in ordered]
    if len(identities) != len(set(identities)):
        raise ValueError("duplicate source observation identity")
    benchmark_tickers = {
        str(row["ticker"])
        for row in ordered
        if row["source_kind"] == "BENCHMARK"
    }
    if not {"SPY", "QQQ"}.issubset(benchmark_tickers):
        raise ValueError("required benchmark observation missing")
    return ordered


def merge_new_events(
    *,
    existing: list[dict[str, Any]],
    identities: Mapping[str, Mapping[str, Any]],
    proposed: Iterable[Mapping[str, Any]],
    previous_hash: str,
) -> tuple[list[dict[str, Any]], str]:
    new_rows: list[dict[str, Any]] = []
    chain_head = previous_hash
    seen = set(identities)
    for raw in proposed:
        payload = json_clean(dict(raw))
        identity = str(payload.get("event_id") or "")
        prior = identities.get(identity)
        if prior is not None:
            if canonical_hash(event_without_chain(prior)) != canonical_hash(payload):
                raise ValueError(f"same identity payload changed:{identity}")
            continue
        if not identity or identity in seen:
            raise ValueError(f"duplicate proposed event identity:{identity}")
        chained = attach_chain(payload, chain_head)
        new_rows.append(chained)
        chain_head = str(chained["event_hash"])
        seen.add(identity)
    return new_rows, chain_head


def proposed_outcomes(
    *,
    observations: Iterable[Mapping[str, Any]],
    existing_outcome_ids: set[str],
    as_of_date: str,
    horizons: Iterable[int],
    contract_sha256: str,
) -> tuple[list[dict[str, Any]], int]:
    rows = list(observations)
    exact: dict[tuple[str, str, str], Mapping[str, Any]] = {
        (
            str(row.get("source_kind") or ""),
            str(row.get("ticker") or ""),
            str(row.get("as_of_date") or ""),
        ): row
        for row in rows
    }
    proposed: list[dict[str, Any]] = []
    missing_exact = 0
    for observation in rows:
        origin = str(observation.get("as_of_date") or "")
        origin_close = finite(observation.get("observed_close"))
        if not origin or origin_close in (None, 0.0):
            continue
        for horizon_value in horizons:
            horizon = int(horizon_value)
            target_date = exact_target_session(origin, horizon)
            if target_date > as_of_date:
                continue
            identity = canonical_hash(
                {
                    "schema_version": OUTCOME_SCHEMA_VERSION,
                    "observation_event_id": observation["event_id"],
                    "horizon_nyse_sessions": horizon,
                    "target_session_date": target_date,
                    "memory_contract_sha256": contract_sha256,
                }
            )
            if identity in existing_outcome_ids:
                continue
            key = (
                str(observation.get("source_kind") or ""),
                str(observation.get("ticker") or ""),
                target_date,
            )
            target = exact.get(key)
            target_close = finite((target or {}).get("observed_close"))
            if target_close is None:
                missing_exact += 1
                continue
            forward_return = target_close / float(origin_close) - 1.0
            benchmark_return = None
            excess_spy = None
            if str(observation.get("source_kind")) == "SECURITY":
                benchmark_origin = exact.get(("BENCHMARK", "SPY", origin))
                benchmark_target = exact.get(("BENCHMARK", "SPY", target_date))
                benchmark_origin_close = finite(
                    (benchmark_origin or {}).get("observed_close")
                )
                benchmark_target_close = finite(
                    (benchmark_target or {}).get("observed_close")
                )
                if (
                    benchmark_origin_close not in (None, 0.0)
                    and benchmark_target_close is not None
                ):
                    benchmark_return = (
                        benchmark_target_close / float(benchmark_origin_close) - 1.0
                    )
                    excess_spy = forward_return - benchmark_return
            proposed.append(
                {
                    "schema_version": OUTCOME_SCHEMA_VERSION,
                    "event_type": "OUTCOME",
                    "event_id": identity,
                    "observation_event_id": observation["event_id"],
                    "source_kind": observation.get("source_kind"),
                    "ticker": observation.get("ticker"),
                    "pattern_signature": observation.get(
                        "return_transition_signature"
                    ),
                    "origin_session_date": origin,
                    "target_session_date": target_date,
                    "horizon_nyse_sessions": horizon,
                    "origin_close": origin_close,
                    "target_close": target_close,
                    "forward_return": forward_return,
                    "spy_forward_return": benchmark_return,
                    "excess_return_vs_spy": excess_spy,
                    "recorded_during_session": as_of_date,
                    "resolution_policy": "EXACT_ARCHIVED_NYSE_TARGET_SESSION_ONLY",
                    "memory_contract_sha256": contract_sha256,
                    "research_only": True,
                    "portfolio_transition_allowed": False,
                    "orders_generated": False,
                    "target_books_mutated": False,
                    "champion_changed": False,
                }
            )
    return sorted(
        proposed,
        key=lambda row: (
            str(row["target_session_date"]),
            str(row["source_kind"]),
            str(row["ticker"]),
            int(row["horizon_nyse_sessions"]),
        ),
    ), missing_exact


def aggregate_outcomes(
    observations: Iterable[Mapping[str, Any]],
    outcomes: Iterable[Mapping[str, Any]],
    minimum_resolved: int,
    minimum_resolution_coverage: float,
    as_of_date: str,
    horizons: Iterable[int],
) -> list[dict[str, Any]]:
    observation_rows = list(observations)
    outcome_rows = list(outcomes)
    observation_map = {
        str(row.get("event_id") or ""): row for row in observation_rows
    }
    grouped: dict[tuple[str, str, int], list[Mapping[str, Any]]] = defaultdict(list)
    for outcome in outcome_rows:
        observation = observation_map.get(
            str(outcome.get("observation_event_id") or "")
        ) or {}
        key = (
            str(observation.get("source_kind") or outcome.get("source_kind") or ""),
            str(
                observation.get("return_transition_signature")
                or outcome.get("pattern_signature")
                or ""
            ),
            int(outcome.get("horizon_nyse_sessions") or 0),
        )
        grouped[key].append(outcome)
    matured: dict[tuple[str, str, int], int] = defaultdict(int)
    for observation in observation_rows:
        origin = str(observation.get("as_of_date") or "")
        if not origin or finite(observation.get("observed_close")) in (None, 0.0):
            continue
        for horizon_value in horizons:
            horizon = int(horizon_value)
            if exact_target_session(origin, horizon) <= as_of_date:
                key = (
                    str(observation.get("source_kind") or ""),
                    str(
                        observation.get("return_transition_signature")
                        or "FLAT_OR_INSUFFICIENT"
                    ),
                    horizon,
                )
                matured[key] += 1
    aggregates: list[dict[str, Any]] = []
    for source_kind, pattern, horizon in sorted(set(grouped) | set(matured)):
        rows = grouped.get((source_kind, pattern, horizon), [])
        count = len(rows)
        matured_count = int(matured.get((source_kind, pattern, horizon), 0))
        missing_count = max(0, matured_count - count)
        resolution_coverage = (
            count / matured_count if matured_count > 0 else 0.0
        )
        statistics_ready = bool(
            count >= minimum_resolved
            and resolution_coverage >= minimum_resolution_coverage
        )
        result: dict[str, Any] = {
            "source_kind": source_kind,
            "pattern_signature": pattern,
            "horizon_nyse_sessions": horizon,
            "matured_observation_count": matured_count,
            "resolved_observation_count": count,
            "missing_exact_outcome_count": missing_count,
            "resolution_coverage": resolution_coverage,
            "minimum_resolution_coverage": minimum_resolution_coverage,
            "minimum_required": minimum_resolved,
            "underpowered": not statistics_ready,
            "directional_statistics_published": statistics_ready,
        }
        if statistics_ready:
            returns = np.asarray(
                [float(row["forward_return"]) for row in rows],
                dtype=float,
            )
            excess = [
                float(value)
                for value in (
                    row.get("excess_return_vs_spy") for row in rows
                )
                if finite(value) is not None
            ]
            result["directional_statistics"] = {
                "mean_forward_return": float(returns.mean()),
                "median_forward_return": float(np.median(returns)),
                "positive_return_rate": float((returns > 0.0).mean()),
                "mean_excess_return_vs_spy": (
                    float(np.mean(excess)) if excess else None
                ),
            }
        aggregates.append(result)
    return aggregates


def render_report(summary: Mapping[str, Any]) -> str:
    lines = [
        "# Run287 OHLCV shock/rebound pattern memory",
        "",
        f"- status: `{summary.get('status')}`",
        f"- accepted through: `{summary.get('accepted_through')}`",
        f"- observation events: `{summary.get('observation_event_count')}`",
        f"- resolved outcome events: `{summary.get('resolved_outcome_event_count')}`",
        f"- completed sessions / decision weeks: `{summary.get('completed_sessions')}` / `{summary.get('decision_weeks')}`",
        f"- proposal eligible: `{summary.get('proposal_eligible')}`",
        "- append-only forward research only; no target, order, cash, champion, production, or live mutation",
        "- one rebound is a descriptive fingerprint, never automatic evidence of trend repair",
        "",
        "| Source | Pattern | Horizon | Matured | Resolved | Missing | Coverage | Minimum | Underpowered |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in summary.get("aggregates") or []:
        lines.append(
            f"| {row.get('source_kind')} | `{row.get('pattern_signature')}` | "
            f"{row.get('horizon_nyse_sessions')} | "
            f"{row.get('matured_observation_count')} | "
            f"{row.get('resolved_observation_count')} | "
            f"{row.get('missing_exact_outcome_count')} | "
            f"{float(row.get('resolution_coverage') or 0.0):.1%} | "
            f"{row.get('minimum_required')} | "
            f"`{row.get('underpowered')}` |"
        )
    lines.append("")
    return "\n".join(lines)


def blocked(
    output_dir: Path,
    failures: list[str],
    sources: Mapping[str, Any],
    started: float,
) -> dict[str, Any]:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "status": BLOCKED_STATUS,
        "contract_failures": failures,
        "research_only": True,
        "portfolio_transition_allowed": False,
        "orders_generated": False,
        "target_books_mutated": False,
        "cash_policy_changed": False,
        "champion_changed": False,
        "backtest_executed": False,
        "fullrun_executed": False,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
        "source_inputs": dict(sources),
        "performance": {"elapsed_seconds": time.perf_counter() - started},
        "code": {"git_head": git_head(), "builder": fingerprint(Path(__file__))},
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(output_dir / "last_attempt.json", payload)
    return payload


def build(args: argparse.Namespace) -> dict[str, Any]:
    started = time.perf_counter()
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    sources: dict[str, Any] = {}
    try:
        contract_path = repo_path(args.contract)
        contract = read_json(contract_path)
        sources["contract"] = fingerprint(contract_path)
        if contract.get("schema_version") != "run287-ohlcv-pattern-memory-contract-v1":
            raise ValueError("memory contract schema")
        contract_sha256 = str(sources["contract"]["sha256"])

        summary_path = repo_path(args.timing_summary)
        summary = read_json(summary_path)
        sources["timing_summary"] = fingerprint(summary_path)
        source_contract = contract["source_contract"]
        if summary.get("schema_version") != source_contract["schema_version"]:
            raise ValueError("timing summary schema")
        if summary.get("status") not in set(source_contract["ready_statuses"]):
            raise ValueError(f"timing summary not READY:{summary.get('status')}")
        if str(summary.get("as_of_date") or "") != args.valuation_date:
            raise ValueError("timing summary valuation date")
        for key in (
            "portfolio_transition_allowed",
            "orders_generated",
            "target_books_mutated",
            "selector_weights_changed",
            "cash_policy_changed",
            "champion_changed",
            "backtest_executed",
            "fullrun_executed",
            "production_activation_allowed",
            "live_trading_enabled",
        ):
            if summary.get(key) is not False:
                raise ValueError(f"unsafe timing summary:{key}")

        observations_path, sources["timing_observations"] = resolve_output(
            summary_path,
            summary,
            "forward_observations",
        )
        benchmark_path, sources["timing_benchmark"] = resolve_output(
            summary_path,
            summary,
            "benchmark_location",
        )
        security_rows = read_jsonl(observations_path)
        benchmark_rows = pd.read_csv(benchmark_path, low_memory=False).to_dict(
            "records"
        )
        proposed_observations = source_observations(
            valuation_date=args.valuation_date,
            summary=summary,
            security_rows=security_rows,
            benchmark_rows=benchmark_rows,
            contract_sha256=contract_sha256,
            source_summary_sha256=str(sources["timing_summary"]["sha256"]),
            source_observations_sha256=str(
                sources["timing_observations"]["sha256"]
            ),
            source_benchmark_sha256=str(sources["timing_benchmark"]["sha256"]),
        )

        observations_archive = output_dir / "observations.jsonl"
        outcomes_archive = output_dir / "outcomes.jsonl"
        existing_observations, observation_ids, observation_head = validate_chain(
            read_jsonl(observations_archive),
            expected_schema=OBSERVATION_SCHEMA_VERSION,
            contract_sha256=contract_sha256,
        )
        existing_outcomes, outcome_ids, outcome_head = validate_chain(
            read_jsonl(outcomes_archive),
            expected_schema=OUTCOME_SCHEMA_VERSION,
            contract_sha256=contract_sha256,
        )
        existing_dates = [
            str(row.get("as_of_date") or "")
            for row in existing_observations
            if row.get("as_of_date")
        ]
        if existing_dates and args.valuation_date < max(existing_dates):
            raise ValueError(
                f"out-of-order observation:{args.valuation_date}<{max(existing_dates)}"
            )
        new_observations, observation_head = merge_new_events(
            existing=existing_observations,
            identities=observation_ids,
            proposed=proposed_observations,
            previous_hash=observation_head,
        )
        all_observations = [*existing_observations, *new_observations]
        proposed_resolutions, missing_exact = proposed_outcomes(
            observations=all_observations,
            existing_outcome_ids=set(outcome_ids),
            as_of_date=args.valuation_date,
            horizons=contract["forward_learning"][
                "outcome_horizons_nyse_sessions"
            ],
            contract_sha256=contract_sha256,
        )
        new_outcomes, outcome_head = merge_new_events(
            existing=existing_outcomes,
            identities=outcome_ids,
            proposed=proposed_resolutions,
            previous_hash=outcome_head,
        )

        for label in ("timing_summary", "timing_observations", "timing_benchmark"):
            path = Path(str(sources[label]["path"]))
            if sha256_file(path) != str(sources[label]["sha256"]):
                raise ValueError(f"source changed before append:{label}")

        appended_observations = append_rows(
            observations_archive,
            new_observations,
        )
        appended_outcomes = append_rows(outcomes_archive, new_outcomes)
        all_outcomes = [*existing_outcomes, *new_outcomes]
        minimum = int(
            contract["forward_learning"][
                "minimum_resolved_observations_per_pattern_horizon"
            ]
        )
        minimum_resolution_coverage = float(
            contract["forward_learning"][
                "minimum_resolution_coverage_for_directional_statistics"
            ]
        )
        aggregates = aggregate_outcomes(
            all_observations,
            all_outcomes,
            minimum,
            minimum_resolution_coverage,
            args.valuation_date,
            contract["forward_learning"][
                "outcome_horizons_nyse_sessions"
            ],
        )
        sessions = sorted(
            {
                str(row.get("as_of_date"))
                for row in all_observations
                if row.get("as_of_date")
            }
        )
        weeks = sorted(
            {
                f"{pd.Timestamp(value).isocalendar().year}-W{pd.Timestamp(value).isocalendar().week:02d}"
                for value in sessions
            }
        )
        minimum_sessions = int(
            contract["forward_learning"][
                "minimum_completed_sessions_before_proposal"
            ]
        )
        minimum_weeks = int(
            contract["forward_learning"][
                "minimum_decision_weeks_before_proposal"
            ]
        )
        powered = any(
            row.get("directional_statistics_published") is True
            for row in aggregates
        )
        payload = {
            "schema_version": SCHEMA_VERSION,
            "status": READY_STATUS,
            "contract_failures": [],
            "accepted_through": max(sessions) if sessions else "",
            "observation_event_count": len(all_observations),
            "resolved_outcome_event_count": len(all_outcomes),
            "appended_observation_count": appended_observations,
            "appended_outcome_count": appended_outcomes,
            "exact_target_observation_missing_count": missing_exact,
            "completed_sessions": len(sessions),
            "decision_weeks": len(weeks),
            "minimum_completed_sessions_before_proposal": minimum_sessions,
            "minimum_decision_weeks_before_proposal": minimum_weeks,
            "minimum_resolved_per_pattern_horizon": minimum,
            "minimum_resolution_coverage_for_directional_statistics": (
                minimum_resolution_coverage
            ),
            "proposal_eligible": bool(
                len(sessions) >= minimum_sessions
                and len(weeks) >= minimum_weeks
                and powered
            ),
            "aggregates": aggregates,
            "observation_chain_head": observation_head,
            "outcome_chain_head": outcome_head,
            "research_only": True,
            "forward_observation_only": True,
            "advisory_only": True,
            "automatic_model_update_allowed": False,
            "automatic_champion_promotion_allowed": False,
            "portfolio_transition_allowed": False,
            "orders_generated": False,
            "target_books_mutated": False,
            "selector_weights_changed": False,
            "cash_policy_changed": False,
            "champion_changed": False,
            "historical_cagr_mdd_evidence_changed": False,
            "backtest_executed": False,
            "fullrun_executed": False,
            "production_activation_allowed": False,
            "live_trading_enabled": False,
            "memory_contract_sha256": contract_sha256,
            "source_inputs": sources,
            "outputs": {
                "observations": fingerprint(observations_archive),
                "outcomes": fingerprint(outcomes_archive),
            },
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "performance": {"elapsed_seconds": time.perf_counter() - started},
            "code": {"git_head": git_head(), "builder": fingerprint(Path(__file__))},
        }
        report_path = output_dir / "report.md"
        atomic_write_text(
            report_path,
            render_report(payload),
        )
        payload["outputs"]["report"] = fingerprint(report_path)
        # summary.json is the READY marker and is committed only after the
        # append-only chains and human-readable report are durable.
        atomic_write_json(output_dir / "summary.json", payload)
        atomic_write_json(
            output_dir / "last_attempt.json",
            {
                "schema_version": SCHEMA_VERSION,
                "status": READY_STATUS,
                "accepted_through": payload["accepted_through"],
                "summary_sha256": sha256_file(output_dir / "summary.json"),
            },
        )
        return payload
    except Exception as exc:
        return blocked(
            output_dir,
            [f"{type(exc).__name__}:{exc}"],
            sources,
            started,
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--timing-summary",
        required=True,
    )
    parser.add_argument(
        "--contract",
        default="docs/run287_ohlcv_pattern_memory_contract.json",
    )
    parser.add_argument("--valuation-date", required=True)
    parser.add_argument(
        "--output-dir",
        default=(
            "outputs/run287_decision_observation_archive/"
            "ohlcv_pattern_memory"
        ),
    )
    return parser.parse_args()


def main() -> int:
    payload = build(parse_args())
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload.get("status") == READY_STATUS else 2


if __name__ == "__main__":
    raise SystemExit(main())
