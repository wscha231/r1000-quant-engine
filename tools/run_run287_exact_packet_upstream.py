#!/usr/bin/env python3
"""Run the bounded same-close upstream chain for one Run287 risk packet.

Only the allowlisted current-decision research producers are invoked.  The
chain has explicit paths and request ceilings, writes into a unique append-only
attempt directory, and publishes a source bundle only after every stage is
READY for the same completed close.  It never calls fullrun, a backtest,
target-book generation, order code, a premium provider, or live trading.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd
import pandas_market_calendars as mcal


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.build_run287_exact_packet_source_bundle import (  # noqa: E402
    READY_STATUS as BUNDLE_READY_STATUS,
    REUSED_STATUS as BUNDLE_REUSED_STATUS,
    build_from_records as publish_bundle,
    parse_input_records,
)
from tools.run_run287_exact_packet_producer import (  # noqa: E402
    fingerprint,
    read_json,
    resolve_portable_path,
    sha256_file,
    write_json,
)
from tools.run_run287_scored_latest_refresh import (  # noqa: E402
    PREFLIGHT_INPUT_LABELS as SCORER_PREFLIGHT_INPUT_LABELS,
    build_price_cache_input_audit,
    changed_price_cache_inputs,
    normalize_ticker,
)
from tools.run_data_freshness_contract import (  # noqa: E402
    core_candidate_ticker_set_sha256,
)
from tools.security_lifecycle import (  # noqa: E402
    filter_terminal_tickers,
    resolve_security_lifecycle,
)
from tools.run287_code_identity import (  # noqa: E402
    code_identity_failures,
    current_code_identity,
)


SCHEMA_VERSION = "run287-exact-packet-upstream-orchestrator-v3"
PLAN_SCHEMA = "run287-exact-packet-upstream-plan-v1"
PLAN_STATUS = "READY_BOUNDED_EXACT_PACKET_UPSTREAM_PLAN_REVIEW_ONLY"
READY_STATUS = "READY_EXACT_PACKET_UPSTREAM_SOURCE_BUNDLE_REVIEW_ONLY"
REUSED_STATUS = "READY_EXISTING_EXACT_PACKET_UPSTREAM_SOURCE_BUNDLE_REVIEW_ONLY"
PREFLIGHT_STATUS = "READY_EXACT_PACKET_UPSTREAM_PREFLIGHT_REVIEW_ONLY"
SKIPPED_STATUS = "SKIPPED_EXACT_PACKET_UPSTREAM_PREREQUISITES"
BLOCKED_STATUS = "BLOCKED_EXACT_PACKET_UPSTREAM"

ALLOWED_TOOLS = {
    "tools/run_run287_scored_latest_refresh.py",
    "tools/build_run287_macro_sidecar.py",
    "tools/build_run287_benchmark_event_sidecar.py",
    "tools/collect_run287_recent_sec_delta.py",
    "tools/fetch_run287_recent_companyfacts.py",
    "tools/build_run287_current_decision_frame.py",
    "tools/run_run287_current_decision_score_only.py",
    "tools/run_run287_current_decision_score_stack_audit.py",
    "tools/build_run287_current_crisis_state_sidecar.py",
    "tools/recover_run287_selector_benchmark_price.py",
}


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def clean_attempt_id(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value).strip()).strip("-.")
    if not cleaned or len(cleaned) > 96:
        raise ValueError("--attempt-id must contain 1-96 safe characters")
    return cleaned


def utc_timestamp(value: str) -> pd.Timestamp:
    stamp = pd.Timestamp(value) if value else pd.Timestamp.now(tz="UTC")
    if stamp.tzinfo is None:
        stamp = stamp.tz_localize("UTC")
    return stamp.tz_convert("UTC")


def nyse_sec_index_dates(valuation_date: str, count: int = 2) -> list[str]:
    valuation = pd.Timestamp(valuation_date).normalize()
    calendar = mcal.get_calendar("NYSE")
    schedule = calendar.schedule(
        start_date=(valuation - pd.Timedelta(days=14)).date(),
        end_date=valuation.date(),
    )
    labels = [pd.Timestamp(value).date() for value in schedule.index]
    labels = [value for value in labels if value <= valuation.date()]
    if not labels or labels[-1] != valuation.date():
        raise ValueError(f"valuation date is not an NYSE session: {valuation_date}")
    return [value.strftime("%Y%m%d") for value in labels[-int(count) :]]


def base_payload(status: str, valuation_date: str, started: float) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "valuation_price_cutoff_date": valuation_date,
        "upstream_ready": status in {READY_STATUS, REUSED_STATUS},
        "research_only": True,
        "network_requests_executed": 0,
        "backtest_executed": False,
        "fullrun_executed": False,
        "orders_generated": False,
        "target_books_mutated": False,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
        "elapsed_seconds": time.perf_counter() - started,
    }


def plan_paths(
    plan: Mapping[str, Any], overrides: Mapping[str, str]
) -> tuple[dict[str, Path], dict[str, Any], list[str]]:
    paths: dict[str, Path] = {}
    audits: dict[str, Any] = {}
    failures: list[str] = []
    records = plan.get("paths") or {}
    unknown = sorted(set(overrides).difference(records))
    if unknown:
        failures.append(f"unknown_path_overrides:{','.join(unknown)}")
    for label, record in records.items():
        raw = overrides.get(label) or str((record or {}).get("path") or "")
        # Plan paths are an explicit contract.  A relative plan path therefore
        # means REPO_ROOT/path and must win over portable anchor recovery.  The
        # latter is only a fallback for restored legacy absolute paths.
        configured = repo_path(raw)
        path = (
            configured.resolve()
            if raw and configured.exists()
            else resolve_portable_path(
                raw, owner=repo_path("docs/run287_exact_packet_upstream_plan.json")
            )
        )
        if not path.is_absolute():
            path = repo_path(path)
        paths[label] = path
        audit = fingerprint(path)
        expected = str((record or {}).get("sha256") or "").lower()
        if expected:
            audit["expected_sha256"] = expected
            audit["hash_matches"] = audit.get("sha256") == expected
        audits[label] = audit
        if not path.is_file():
            failures.append(f"missing_path:{label}")
        elif expected and audit.get("sha256") != expected:
            failures.append(f"path_hash:{label}")
    return paths, audits, failures


def valid_sha256(value: Any) -> bool:
    digest = str(value or "").strip().lower()
    return bool(
        len(digest) == 64
        and all(character in "0123456789abcdef" for character in digest)
    )


def preflight_ticker_identity(
    *,
    paths: Mapping[str, Path],
    valuation_date: str,
    decision_time: pd.Timestamp,
    expected_context_count: int,
) -> tuple[dict[str, Any], list[str], list[str]]:
    """Freeze universe membership before any network-backed stage starts."""

    failures: list[str] = []
    identity: dict[str, Any] = {}
    post_tickers: list[str] = []
    try:
        universe = pd.read_csv(
            paths["universe"], dtype={"ticker": str}, low_memory=False
        )
        if "ticker" not in universe:
            raise ValueError("universe_ticker_column_missing")
        universe_tickers = [
            normalize_ticker(value) for value in universe["ticker"].tolist()
        ]
        if (
            not universe_tickers
            or not all(universe_tickers)
            or len(set(universe_tickers)) != len(universe_tickers)
        ):
            raise ValueError("universe_ticker_identity_invalid")
        identity["universe_count"] = len(universe_tickers)
        identity["universe_ticker_set_sha256"] = (
            core_candidate_ticker_set_sha256(universe_tickers)
        )
    except Exception as exc:
        failures.append(f"ticker_identity:universe:{type(exc).__name__}:{exc}")
        universe_tickers = []

    try:
        base = pd.read_parquet(paths["base_selection_context"])
        if "ticker" not in base:
            raise ValueError("base_selection_context_ticker_column_missing")
        base["ticker"] = base["ticker"].map(normalize_ticker)
        pre_tickers = base["ticker"].tolist()
        if (
            not pre_tickers
            or not all(pre_tickers)
            or len(set(pre_tickers)) != len(pre_tickers)
        ):
            raise ValueError("base_selection_context_ticker_identity_invalid")
        if expected_context_count <= 0 or len(pre_tickers) != expected_context_count:
            raise ValueError(
                f"base_selection_context_count:{len(pre_tickers)}"
                f"!={expected_context_count}"
            )
        lifecycle = resolve_security_lifecycle(
            paths["security_lifecycle_events"],
            session_date=pd.Timestamp(valuation_date),
            decision_time_utc=decision_time,
            active_tickers=set(pre_tickers),
        )
        post = filter_terminal_tickers(base, lifecycle)
        post_tickers = post["ticker"].tolist()
        if not post_tickers or len(set(post_tickers)) != len(post_tickers):
            raise ValueError("post_lifecycle_ticker_identity_invalid")
        identity.update(
            {
                "pre_lifecycle_context_count": len(pre_tickers),
                "pre_lifecycle_ticker_set_sha256": (
                    core_candidate_ticker_set_sha256(pre_tickers)
                ),
                "post_lifecycle_context_count": len(post_tickers),
                "post_lifecycle_ticker_set_sha256": (
                    core_candidate_ticker_set_sha256(post_tickers)
                ),
                "lifecycle_snapshot_sha256": lifecycle.snapshot_hash,
            }
        )
    except Exception as exc:
        failures.append(
            f"ticker_identity:base_selection_context:{type(exc).__name__}:{exc}"
        )
    return identity, failures, post_tickers


def changed_preflight_input_failures(
    input_audit: Mapping[str, Mapping[str, Any]],
    plan_audit: Mapping[str, Any] | None = None,
) -> list[str]:
    """Rehash all plan inputs before source-bundle readiness is published."""

    failures: list[str] = []
    audits: dict[str, Mapping[str, Any]] = dict(input_audit)
    if plan_audit is not None:
        audits["plan"] = plan_audit
    for label, prior in audits.items():
        raw_path = str((prior or {}).get("path") or "")
        if not raw_path:
            failures.append(f"preflight_input_path_missing:{label}")
            continue
        current = fingerprint(Path(raw_path))
        if any(
            current.get(field) != prior.get(field)
            for field in ("exists", "bytes", "sha256")
        ):
            failures.append(f"preflight_input_changed:{label}")
    return failures


def changed_code_identity_failures(
    frozen_identity: Mapping[str, Any],
) -> list[str]:
    """Reject a commit/workflow/builder change during the current attempt."""

    try:
        current_identity = current_code_identity()
    except Exception as exc:
        return [f"code_identity_current:{type(exc).__name__}"]
    return code_identity_failures(
        frozen_identity,
        current=current_identity,
        prefix="code_identity",
    )


def existing_bundle_records(
    source_bundle_output: str | Path, valuation_date: str
) -> tuple[Path, dict[str, str]] | None:
    """Return the exact dated bundle records for a zero-network retry."""
    dated = (
        repo_path(source_bundle_output)
        / "by_date"
        / valuation_date
        / "source_bundle.json"
    )
    if not dated.is_file():
        return None
    payload = read_json(dated)
    if str(payload.get("valuation_price_cutoff_date") or "") != valuation_date:
        raise ValueError("existing source-bundle date mismatch")
    inputs = payload.get("inputs") or {}
    if not isinstance(inputs, Mapping) or not inputs:
        raise ValueError("existing source-bundle inputs missing")
    records: dict[str, str] = {}
    for label, record in inputs.items():
        raw = str((record or {}).get("path") or "")
        if not raw:
            raise ValueError(f"existing source-bundle path missing: {label}")
        records[str(label)] = raw
    return dated, records


def validate_plan(plan: Mapping[str, Any]) -> list[str]:
    failures: list[str] = []
    if plan.get("schema_version") != PLAN_SCHEMA:
        failures.append("plan_schema")
    if plan.get("status") != PLAN_STATUS:
        failures.append("plan_status")
    safety = plan.get("safety") or {}
    if safety.get("research_only") is not True:
        failures.append("safety_research_only")
    for key in (
        "backtest_allowed",
        "fullrun_allowed",
        "orders_allowed",
        "target_book_write_allowed",
        "production_activation_allowed",
        "live_trading_allowed",
        "premium_provider_allowed",
    ):
        if safety.get(key) is not False:
            failures.append(f"safety:{key}")
    return failures


def manifest_request_count(payload: Mapping[str, Any]) -> int:
    for key in (
        "network_requests_executed",
        "network_download_batch_count",
    ):
        value = pd.to_numeric(pd.Series([payload.get(key)]), errors="coerce").iloc[0]
        if pd.notna(value):
            return int(value)
    return 0


def run_stage(
    *,
    name: str,
    command: Sequence[str],
    manifest_path: Path,
    expected_status: str,
    expected_date_field: str,
    valuation_date: str,
    attempt_root: Path,
    timeout_seconds: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    tool = str(command[1]).replace("\\", "/") if len(command) > 1 else ""
    if tool not in ALLOWED_TOOLS:
        raise ValueError(f"tool is not allowlisted: {tool}")
    forbidden_flags = {
        "--fullrun",
        "--backtest",
        "--live-trading",
        "--production",
        "--generate-orders",
    }
    if any(str(value).lower() in forbidden_flags for value in command[2:]):
        raise ValueError(f"forbidden command flag in {name}")
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            list(command),
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=int(timeout_seconds),
            check=False,
            env=os.environ.copy(),
        )
        return_code = int(completed.returncode)
        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
    except subprocess.TimeoutExpired as exc:
        return_code = 124
        stdout = str(exc.stdout or "")
        stderr = str(exc.stderr or "") + "\nstage_timeout"
    log_path = attempt_root / "logs" / f"{name}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(stdout + ("\n" if stdout and stderr else "") + stderr, encoding="utf-8")

    manifest: dict[str, Any] = {}
    failures: list[str] = []
    if return_code != 0:
        failures.append(f"exit_code:{return_code}")
    if not manifest_path.is_file():
        failures.append("manifest_missing")
    else:
        try:
            manifest = read_json(manifest_path)
        except Exception as exc:
            failures.append(f"manifest_read:{type(exc).__name__}")
    if manifest:
        if manifest.get("status") != expected_status:
            failures.append(f"status:{manifest.get('status')}")
        if expected_date_field and str(manifest.get(expected_date_field) or "") != valuation_date:
            failures.append(
                f"date:{manifest.get(expected_date_field)}!={valuation_date}"
            )
        for flag in (
            "backtest_executed",
            "fullrun_executed",
            "orders_generated",
            "target_books_mutated",
            "production_activation_allowed",
            "live_trading_enabled",
        ):
            if flag in manifest and manifest.get(flag) is not False:
                failures.append(f"unsafe_flag:{flag}")
    audit = {
        "name": name,
        "tool": tool,
        "return_code": return_code,
        "status": manifest.get("status") if manifest else "",
        "manifest": fingerprint(manifest_path),
        "log": fingerprint(log_path),
        "network_requests_executed": manifest_request_count(manifest),
        "elapsed_seconds": time.perf_counter() - started,
        "failures": failures,
    }
    return manifest, audit


def build(args: argparse.Namespace) -> dict[str, Any]:
    started = time.perf_counter()
    valuation_date = pd.Timestamp(args.valuation_date).date().isoformat()
    decision_time = utc_timestamp(args.decision_time_utc)
    attempt_id = clean_attempt_id(args.attempt_id)
    output_root = repo_path(args.output_root)
    attempt_root = output_root / "attempts" / attempt_id
    if attempt_root.exists():
        raise FileExistsError(f"attempt directory already exists: {attempt_root}")
    attempt_root.mkdir(parents=True)
    plan_path = repo_path(args.plan)
    plan = read_json(plan_path)
    overrides = parse_input_records(args.path_override)
    directory_overrides = parse_input_records(args.directory_override)
    paths, input_audit, failures = plan_paths(plan, overrides)
    failures = validate_plan(plan) + failures
    try:
        code_identity = current_code_identity()
        failures.extend(
            code_identity_failures(
                code_identity,
                current=code_identity,
                prefix="code_identity",
            )
        )
    except Exception as exc:
        code_identity = {}
        failures.append(f"code_identity_current:{type(exc).__name__}")
    directories = plan.get("directories") or {}
    unknown_directory_overrides = sorted(
        set(directory_overrides).difference({"price_cache", "model_root", "source_macro_dirs"})
    )
    if unknown_directory_overrides:
        failures.append(
            f"unknown_directory_overrides:{','.join(unknown_directory_overrides)}"
        )
    directory_audit: dict[str, Any] = {}
    price_cache = repo_path(
        directory_overrides.get("price_cache")
        or str(directories.get("price_cache") or "")
    )
    model_root = repo_path(
        directory_overrides.get("model_root")
        or str(directories.get("model_root") or "")
    )
    macro_dir_values = directory_overrides.get("source_macro_dirs")
    macro_dirs = [
        repo_path(value)
        for value in (
            macro_dir_values.split(os.pathsep)
            if macro_dir_values
            else directories.get("source_macro_dirs") or []
        )
    ]
    for label, path in {
        "price_cache": price_cache,
        "model_root": model_root,
        **{f"source_macro_dir_{index}": path for index, path in enumerate(macro_dirs)},
    }.items():
        exists = path.is_dir()
        directory_audit[label] = {"path": str(path), "exists": exists}
        if label in {"price_cache", "model_root"} and not exists:
            failures.append(f"missing_directory:{label}")

    runtime = plan.get("runtime") or {}
    budgets = plan.get("network_budgets") or {}
    expected_context = int(runtime.get("expected_context_count") or 0)
    universe_rows = 0
    if paths.get("universe") and paths["universe"].is_file():
        try:
            universe_rows = int(
                len(pd.read_csv(paths["universe"], low_memory=False))
            )
            estimated_batches = int(
                math.ceil(universe_rows / int(runtime.get("price_batch_size") or 40))
            )
            if estimated_batches > int(
                budgets.get("scored_latest_provider_batches") or 0
            ):
                failures.append("scored_latest_batch_budget")
        except Exception as exc:
            estimated_batches = 0
            failures.append(f"universe_read:{type(exc).__name__}")
    else:
        estimated_batches = 0

    for label in SCORER_PREFLIGHT_INPUT_LABELS:
        audit = input_audit.get(label) or {}
        expected_sha = str(audit.get("expected_sha256") or "").lower()
        if not valid_sha256(expected_sha):
            failures.append(f"scorer_preflight_expected_sha256:{label}")
        elif (
            audit.get("hash_matches") is not True
            or audit.get("sha256") != expected_sha
        ):
            failures.append(f"scorer_preflight_hash:{label}")
    (
        ticker_identity,
        ticker_identity_failures,
        preflight_post_lifecycle_tickers,
    ) = preflight_ticker_identity(
        paths=paths,
        valuation_date=valuation_date,
        decision_time=decision_time,
        expected_context_count=expected_context,
    )
    failures.extend(ticker_identity_failures)
    price_cache_input_audit = (
        build_price_cache_input_audit(
            preflight_post_lifecycle_tickers, price_cache
        )
        if preflight_post_lifecycle_tickers
        else {}
    )
    if not price_cache_input_audit:
        failures.append("price_cache_input_audit_missing")

    sec_user_agent = str(os.environ.get("SEC_USER_AGENT") or "").strip()
    if args.allow_network and (not sec_user_agent or "@" not in sec_user_agent):
        failures.append("sec_user_agent_missing")

    preflight = {
        "plan": fingerprint(plan_path),
        "code_identity": code_identity,
        "input_audit": input_audit,
        "directory_audit": directory_audit,
        "universe_rows": universe_rows,
        "ticker_identity": ticker_identity,
        "price_cache_input_audit": price_cache_input_audit,
        "estimated_scored_latest_provider_batches": estimated_batches,
        "decision_time_utc": decision_time.isoformat(),
        "sec_user_agent_configured": bool(sec_user_agent and "@" in sec_user_agent),
    }
    if failures:
        payload = base_payload(SKIPPED_STATUS, valuation_date, started)
        payload["skip_reasons"] = failures
        payload["preflight"] = preflight
        write_json(attempt_root / "status.json", payload)
        return payload
    if args.preflight_only or not args.allow_network:
        payload = base_payload(PREFLIGHT_STATUS, valuation_date, started)
        payload["preflight"] = preflight
        payload["network_execution_authorized"] = False
        write_json(attempt_root / "status.json", payload)
        return payload

    # A workflow retry for a close that already has a validated immutable
    # bundle must not repeat any provider call. Revalidate every referenced
    # manifest/file through the normal publisher and reuse only an exact match.
    try:
        existing = existing_bundle_records(args.source_bundle_output, valuation_date)
    except Exception as exc:
        return finish_blocked(
            attempt_root,
            valuation_date,
            started,
            preflight,
            [
                {
                    "name": "existing_source_bundle",
                    "failures": [f"read:{type(exc).__name__}"],
                    "network_requests_executed": 0,
                }
            ],
        )
    if existing is not None:
        dated, records = existing
        input_changes = [
            *changed_code_identity_failures(code_identity),
            *changed_preflight_input_failures(
                input_audit, preflight.get("plan") or {}
            ),
            *changed_price_cache_inputs(
                price_cache_input_audit,
                failure_prefix="preflight_price_cache_changed",
            ),
        ]
        if input_changes:
            return finish_blocked(
                attempt_root,
                valuation_date,
                started,
                preflight,
                [
                    {
                        "name": "preflight_input_rehash",
                        "failures": input_changes,
                        "network_requests_executed": 0,
                    }
                ],
            )
        reused = publish_bundle(
            valuation_date=valuation_date,
            input_records=records,
            producer_contract=args.producer_contract,
            output_dir=args.source_bundle_output,
            expected_code_identity=code_identity,
        )
        if reused.get("status") != BUNDLE_REUSED_STATUS:
            return finish_blocked(
                attempt_root,
                valuation_date,
                started,
                preflight,
                [
                    {
                        "name": "existing_source_bundle",
                        "failures": [str(reused.get("status") or "invalid")],
                        "network_requests_executed": 0,
                    }
                ],
            )
        input_changes = [
            *changed_code_identity_failures(code_identity),
            *changed_preflight_input_failures(
                input_audit, preflight.get("plan") or {}
            ),
            *changed_price_cache_inputs(
                price_cache_input_audit,
                failure_prefix="preflight_price_cache_changed",
            ),
        ]
        if input_changes:
            return finish_blocked(
                attempt_root,
                valuation_date,
                started,
                preflight,
                [
                    {
                        "name": "preflight_input_rehash",
                        "failures": input_changes,
                        "network_requests_executed": 0,
                    }
                ],
            )
        payload = base_payload(REUSED_STATUS, valuation_date, started)
        payload["preflight"] = preflight
        payload["stage_audit"] = [
            {
                "name": "existing_source_bundle",
                "status": BUNDLE_REUSED_STATUS,
                "manifest": fingerprint(dated),
                "network_requests_executed": 0,
                "failures": [],
            }
        ]
        payload["source_bundle"] = reused.get("current_source_bundle")
        payload["network_execution_authorized"] = False
        payload["historical_cagr_mdd_evidence_changed"] = False
        write_json(attempt_root / "status.json", payload)
        return payload

    timeout_seconds = int(runtime.get("stage_timeout_seconds") or 900)
    python = sys.executable
    stage_audits: list[dict[str, Any]] = []
    manifests: dict[str, Path] = {}

    def execute(
        name: str,
        tool: str,
        values: Sequence[str],
        output_dir: Path,
        expected_status: str,
        date_field: str,
    ) -> dict[str, Any] | None:
        manifest_path = output_dir / "manifest.json"
        manifest, audit = run_stage(
            name=name,
            command=[python, tool, *map(str, values)],
            manifest_path=manifest_path,
            expected_status=expected_status,
            expected_date_field=date_field,
            valuation_date=valuation_date,
            attempt_root=attempt_root,
            timeout_seconds=timeout_seconds,
        )
        stage_audits.append(audit)
        manifests[name] = manifest_path
        if audit["failures"]:
            return None
        recorded = sum(int(item["network_requests_executed"]) for item in stage_audits)
        if recorded > int(budgets.get("maximum_total_recorded_requests") or 0):
            audit["failures"].append("total_network_request_budget")
            return None
        return manifest

    scored_dir = attempt_root / "scored_latest"
    scorer_expected_hash_args: list[str] = []
    for label in SCORER_PREFLIGHT_INPUT_LABELS:
        scorer_expected_hash_args.extend(
            [
                "--expected-input-sha256",
                f"{label}={input_audit[label]['expected_sha256']}",
            ]
        )
    scored_values = [
        "--session-date", valuation_date,
        "--decision-time-utc", decision_time.isoformat(),
        "--universe", str(paths["universe"]),
        "--expected-universe-count", str(ticker_identity["universe_count"]),
        "--expected-universe-ticker-set-sha256",
        str(ticker_identity["universe_ticker_set_sha256"]),
        "--base-selection-context", str(paths["base_selection_context"]),
        "--expected-pre-lifecycle-context-count", str(
            ticker_identity["pre_lifecycle_context_count"]
        ),
        "--expected-pre-lifecycle-ticker-set-sha256",
        str(ticker_identity["pre_lifecycle_ticker_set_sha256"]),
        "--expected-post-lifecycle-context-count", str(
            ticker_identity["post_lifecycle_context_count"]
        ),
        "--expected-post-lifecycle-ticker-set-sha256",
        str(ticker_identity["post_lifecycle_ticker_set_sha256"]),
        "--expected-price-cache-contract-sha256",
        str(price_cache_input_audit["contract_sha256"]),
        "--base-score-stack", str(paths["base_score_stack"]),
        "--price-cache", str(price_cache),
        "--model-root", str(model_root),
        "--model-classification", str(paths["model_classification"]),
        "--model-regression", str(paths["model_regression"]),
        "--model-bundle", str(paths["model_bundle"]),
        "--model-meta", str(paths["model_meta"]),
        "--scored-oos", str(paths["scored_oos"]),
        "--batch-size", str(runtime.get("price_batch_size") or 40),
        "--security-lifecycle-events", str(paths["security_lifecycle_events"]),
        "--output-dir", str(scored_dir),
        "--canonical-output", str(scored_dir / "canonical_scored_latest.csv"),
        "--allow-network-refresh",
        *scorer_expected_hash_args,
    ]
    scored = execute(
        "scored_latest",
        "tools/run_run287_scored_latest_refresh.py",
        scored_values,
        scored_dir,
        "READY_RESEARCH_SCORED_LATEST",
        "session_date",
    )
    if scored is None:
        return finish_blocked(attempt_root, valuation_date, started, preflight, stage_audits)

    macro_dir = attempt_root / "macro"
    macro_values = [
        "--snapshot-manifest", str(manifests["scored_latest"]),
        "--technical-pilot-manifest", str(manifests["scored_latest"]),
        "--valuation-close-date", valuation_date,
        "--decision-time-utc", decision_time.isoformat(),
        "--source-price-cache", str(price_cache),
        "--source-macro-dirs", *[str(path) for path in macro_dirs],
        "--max-network-requests", str(budgets.get("macro") or 24),
        "--output-dir", str(macro_dir),
    ]
    macro = execute(
        "macro", "tools/build_run287_macro_sidecar.py", macro_values, macro_dir,
        "READY_CONSERVATIVE_MACRO_SIDECAR", "valuation_close_date",
    )
    if macro is None:
        return finish_blocked(attempt_root, valuation_date, started, preflight, stage_audits)

    benchmark_dir = attempt_root / "benchmark_event"
    benchmark = execute(
        "benchmark_event", "tools/build_run287_benchmark_event_sidecar.py",
        [
            "--macro-manifest", str(manifests["macro"]),
            "--benchmark-source", str(paths["benchmark_seed"]),
            "--decision-time-utc", decision_time.isoformat(),
            "--max-network-requests", str(budgets.get("benchmark") or 1),
            "--output-dir", str(benchmark_dir),
        ],
        benchmark_dir, "READY_CONSERVATIVE_BENCHMARK_EVENT_SIDECAR", "valuation_close_date",
    )
    if benchmark is None:
        return finish_blocked(attempt_root, valuation_date, started, preflight, stage_audits)

    sec_dir = attempt_root / "recent_sec"
    sec_dates = ",".join(nyse_sec_index_dates(valuation_date))
    sec = execute(
        "recent_sec", "tools/collect_run287_recent_sec_delta.py",
        [
            "--universe-file", str(scored_dir / "scored_latest.csv"),
            "--company-tickers", str(paths["company_tickers"]),
            "--identity-index", str(paths["sec_identity_index"]),
            "--dates", sec_dates,
            "--valuation-close-date", valuation_date,
            "--decision-time-utc", decision_time.isoformat(),
            "--max-network-requests", str(budgets.get("recent_sec") or 64),
            "--output-dir", str(sec_dir),
        ],
        sec_dir, "READY_RECENT_SEC_ACCEPTED_DELTA", "valuation_price_cutoff_date",
    )
    if sec is None:
        return finish_blocked(attempt_root, valuation_date, started, preflight, stage_audits)

    companyfacts_dir = attempt_root / "recent_companyfacts"
    companyfacts = execute(
        "recent_companyfacts", "tools/fetch_run287_recent_companyfacts.py",
        [
            "--delta-manifest", str(manifests["recent_sec"]),
            "--canonical-index", str(paths["sec_identity_index"]),
            "--decision-time-utc", decision_time.isoformat(),
            "--max-network-requests", str(budgets.get("companyfacts") or 8),
            "--output-dir", str(companyfacts_dir),
        ],
        companyfacts_dir, "READY_RECENT_COMPANYFACTS_DELTA", "",
    )
    if companyfacts is None:
        return finish_blocked(attempt_root, valuation_date, started, preflight, stage_audits)

    decision_dir = attempt_root / "decision_frame"
    decision = execute(
        "decision_frame", "tools/build_run287_current_decision_frame.py",
        [
            "--scored-latest-manifest", str(manifests["scored_latest"]),
            "--macro-manifest", str(manifests["macro"]),
            "--benchmark-manifest", str(manifests["benchmark_event"]),
            "--sec-delta-manifest", str(manifests["recent_sec"]),
            "--companyfacts-manifest", str(manifests["recent_companyfacts"]),
            "--valuation-close-date", valuation_date,
            "--decision-time-utc", decision_time.isoformat(),
            "--output-dir", str(decision_dir),
        ],
        decision_dir, "READY_COMPLETE_CURRENT_DECISION_FRAME", "valuation_price_cutoff_date",
    )
    if decision is None:
        return finish_blocked(attempt_root, valuation_date, started, preflight, stage_audits)

    decision_hash = sha256_file(manifests["decision_frame"])
    coverage = decision.get("coverage") or {}
    context_count = int(coverage.get("decision_ticker_count") or expected_context)
    feature_count = int(
        coverage.get("model_feature_count")
        or runtime.get("expected_model_feature_count")
        or 0
    )
    score_only_dir = attempt_root / "score_only"
    score_only = execute(
        "score_only", "tools/run_run287_current_decision_score_only.py",
        [
            "--decision-frame-manifest", str(manifests["decision_frame"]),
            "--expected-decision-frame-sha256", decision_hash,
            "--valuation-date", valuation_date,
            "--expected-context-count", str(context_count),
            "--expected-model-feature-count", str(feature_count),
            "--output-dir", str(score_only_dir),
        ],
        score_only_dir, "READY_CURRENT_DECISION_SCORE_ONLY_NONRANKING", "valuation_price_cutoff_date",
    )
    if score_only is None:
        return finish_blocked(attempt_root, valuation_date, started, preflight, stage_audits)

    score_stack_dir = attempt_root / "score_stack"
    score_stack = execute(
        "score_stack", "tools/run_run287_current_decision_score_stack_audit.py",
        [
            "--decision-frame-manifest", str(manifests["decision_frame"]),
            "--expected-decision-frame-sha256", decision_hash,
            "--score-only-manifest", str(manifests["score_only"]),
            "--expected-score-only-sha256", sha256_file(manifests["score_only"]),
            "--frozen-score-stack-manifest", str(paths["frozen_score_stack_manifest"]),
            "--expected-frozen-score-stack-sha256", str(input_audit["frozen_score_stack_manifest"]["sha256"]),
            "--valuation-date", valuation_date,
            "--expected-context-count", str(context_count),
            "--expected-model-feature-count", str(feature_count),
            "--output-dir", str(score_stack_dir),
        ],
        score_stack_dir,
        "READY_CURRENT_DECISION_SCORE_STACK_ELIGIBILITY_AUDIT_NONRANKING",
        "valuation_price_cutoff_date",
    )
    if score_stack is None:
        return finish_blocked(attempt_root, valuation_date, started, preflight, stage_audits)

    crisis_dir = attempt_root / "crisis"
    crisis = execute(
        "crisis", "tools/build_run287_current_crisis_state_sidecar.py",
        [
            "--selector-contract-manifest", str(paths["selector_contract_manifest"]),
            "--expected-selector-contract-sha256", str(input_audit["selector_contract_manifest"]["sha256"]),
            "--pinned-import-manifest", str(paths["pinned_import_manifest"]),
            "--expected-pinned-import-sha256", str(input_audit["pinned_import_manifest"]["sha256"]),
            "--macro-manifest", str(manifests["macro"]),
            "--expected-macro-sha256", sha256_file(manifests["macro"]),
            "--official-daily-crisis-state", str(paths["official_daily_crisis_state"]),
            "--expected-daily-crisis-sha256", str(input_audit["official_daily_crisis_state"]["sha256"]),
            "--official-thresholds", str(paths["official_crisis_thresholds"]),
            "--expected-thresholds-sha256", str(input_audit["official_crisis_thresholds"]["sha256"]),
            "--cache-prices", str(macro_dir / "inputs" / "isolated_engine" / "cache_prices"),
            "--cache-macro", str(macro_dir / "inputs" / "isolated_engine" / "cache_macro"),
            "--expected-price-file-count", str(runtime.get("expected_macro_price_file_count") or 9),
            "--expected-macro-file-count", str(runtime.get("expected_macro_file_count") or 14),
            "--expected-policy-commit", str(runtime.get("expected_policy_commit") or ""),
            "--valuation-date", valuation_date,
            "--output-dir", str(crisis_dir),
        ],
        crisis_dir, "READY_CURRENT_CRISIS_STATE_NONSELECTING", "valuation_price_cutoff_date",
    )
    if crisis is None:
        return finish_blocked(attempt_root, valuation_date, started, preflight, stage_audits)

    soxx_dir = attempt_root / "selector_benchmark"
    soxx = execute(
        "selector_benchmark", "tools/recover_run287_selector_benchmark_price.py",
        [
            "--crisis-manifest", str(manifests["crisis"]),
            "--expected-crisis-sha256", sha256_file(manifests["crisis"]),
            "--source-cache", str(price_cache),
            "--valuation-date", valuation_date,
            "--output-dir", str(soxx_dir),
        ],
        soxx_dir, "READY_SELECTOR_BENCHMARK_PRICE_NONSELECTING", "valuation_price_cutoff_date",
    )
    if soxx is None:
        return finish_blocked(attempt_root, valuation_date, started, preflight, stage_audits)

    bundle_inputs = {
        "decision_manifest": manifests["decision_frame"],
        "score_stack_manifest": manifests["score_stack"],
        "crisis_manifest": manifests["crisis"],
        "price_manifest": manifests["scored_latest"],
        "macro_manifest": manifests["macro"],
        "soxx_manifest": manifests["selector_benchmark"],
        "concentrated_prior_book": paths["concentrated_prior_book"],
        "main_prior_book": paths["main_prior_book"],
        "pinned_import_manifest": paths["pinned_import_manifest"],
        "price_map_manifest": paths["price_map_manifest"],
        "selector_contract_manifest": paths["selector_contract_manifest"],
        "target_generation_manifest": paths["target_generation_manifest"],
    }
    input_changes = [
        *changed_code_identity_failures(code_identity),
        *changed_preflight_input_failures(
            input_audit, preflight.get("plan") or {}
        ),
        *changed_price_cache_inputs(
            price_cache_input_audit,
            failure_prefix="preflight_price_cache_changed",
        ),
    ]
    if input_changes:
        stage_audits.append(
            {
                "name": "preflight_input_rehash",
                "failures": input_changes,
                "network_requests_executed": 0,
            }
        )
        return finish_blocked(
            attempt_root, valuation_date, started, preflight, stage_audits
        )
    bundle = publish_bundle(
        valuation_date=valuation_date,
        input_records=bundle_inputs,
        producer_contract=args.producer_contract,
        output_dir=args.source_bundle_output,
        expected_code_identity=code_identity,
    )
    if bundle.get("status") not in {BUNDLE_READY_STATUS, BUNDLE_REUSED_STATUS}:
        stage_audits.append({"name": "source_bundle", "failures": [str(bundle.get("status"))]})
        return finish_blocked(attempt_root, valuation_date, started, preflight, stage_audits)
    input_changes = [
        *changed_code_identity_failures(code_identity),
        *changed_preflight_input_failures(
            input_audit, preflight.get("plan") or {}
        ),
        *changed_price_cache_inputs(
            price_cache_input_audit,
            failure_prefix="preflight_price_cache_changed",
        ),
    ]
    if input_changes:
        stage_audits.append(
            {
                "name": "preflight_input_rehash",
                "failures": input_changes,
                "network_requests_executed": 0,
            }
        )
        return finish_blocked(
            attempt_root, valuation_date, started, preflight, stage_audits
        )

    payload = base_payload(READY_STATUS, valuation_date, started)
    payload["preflight"] = preflight
    payload["stage_audit"] = stage_audits
    payload["network_requests_executed"] = sum(
        int(item.get("network_requests_executed") or 0) for item in stage_audits
    )
    payload["source_bundle"] = bundle.get("current_source_bundle")
    payload["historical_cagr_mdd_evidence_changed"] = False
    write_json(attempt_root / "status.json", payload)
    return payload


def finish_blocked(
    attempt_root: Path,
    valuation_date: str,
    started: float,
    preflight: Mapping[str, Any],
    stage_audits: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    payload = base_payload(BLOCKED_STATUS, valuation_date, started)
    payload["preflight"] = dict(preflight)
    payload["stage_audit"] = list(stage_audits)
    payload["network_requests_executed"] = sum(
        int(item.get("network_requests_executed") or 0) for item in stage_audits
    )
    payload["failed_stage"] = next(
        (str(item.get("name")) for item in reversed(stage_audits) if item.get("failures")),
        "unknown",
    )
    write_json(attempt_root / "status.json", payload)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--valuation-date", required=True)
    parser.add_argument("--decision-time-utc", default="")
    parser.add_argument("--attempt-id", required=True)
    parser.add_argument(
        "--plan", default="docs/run287_exact_packet_upstream_plan.json"
    )
    parser.add_argument(
        "--path-override", action="append", default=[], metavar="LABEL=PATH"
    )
    parser.add_argument(
        "--directory-override",
        action="append",
        default=[],
        metavar="LABEL=PATH",
        help="Override price_cache/model_root or source_macro_dirs (OS path separator list).",
    )
    parser.add_argument("--allow-network", action="store_true")
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument(
        "--producer-contract",
        default="docs/run287_exact_packet_producer_contract.json",
    )
    parser.add_argument(
        "--output-root", default="outputs/run287_exact_packet_upstream"
    )
    parser.add_argument(
        "--source-bundle-output",
        default="outputs/run287_exact_packet_input_sources",
    )
    return parser.parse_args()


def main() -> int:
    payload = build(parse_args())
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return (
        0
        if payload.get("status") in {READY_STATUS, REUSED_STATUS, PREFLIGHT_STATUS}
        else 2
    )


if __name__ == "__main__":
    raise SystemExit(main())
