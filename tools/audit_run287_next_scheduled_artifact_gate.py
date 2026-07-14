#!/usr/bin/env python3
"""Fail-closed audit of the next Run287 estimate and daily artifacts.

Every evidence path is explicit.  The auditor never discovers a "latest"
artifact, performs network work, runs a backtest/fullrun, or changes portfolio
state.  Missing evidence remains pending; evidence that exists but violates the
frozen contract is blocked.  A completed 1D outcome is diagnostic only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = "run287-next-scheduled-artifact-gate-v1"
CONTRACT_SCHEMA = "run287-next-scheduled-artifact-gate-contract-v1"
READY_STATUS = "READY_NEXT_SCHEDULED_EVIDENCE_REVIEW_ONLY"
PENDING_MISSING_STATUS = "PENDING_MISSING_ARTIFACT"
PENDING_1D_STATUS = "PENDING_1D_NOT_ELAPSED"
BLOCKED_STATUS = "BLOCKED_NEXT_SCHEDULED_ARTIFACT_CONTRACT"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_evidence(label: str, path: Path | None) -> tuple[dict[str, Any], dict[str, Any]]:
    audit: dict[str, Any] = {
        "label": label,
        "path": str(path) if path is not None else "",
        "exists": bool(path is not None and path.is_file()),
        "sha256": "",
        "bytes": 0,
        "parse_error": "",
    }
    if path is None or not path.is_file():
        return {}, audit
    audit["sha256"] = sha256_file(path)
    audit["bytes"] = path.stat().st_size
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        audit["parse_error"] = type(exc).__name__
        return {}, audit
    if not isinstance(payload, dict):
        audit["parse_error"] = "root_not_object"
        return {}, audit
    return payload, audit


def integer(value: Any, default: int = -1) -> int:
    if isinstance(value, bool):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def check_equal(failures: list[str], label: str, observed: Any, expected: Any) -> None:
    if observed != expected:
        failures.append(f"{label}:{observed!r}!={expected!r}")


def check_false(failures: list[str], label: str, payload: Mapping[str, Any], field: str) -> None:
    if payload.get(field) is not False:
        failures.append(f"{label}.{field}:not_false")


def check_true(failures: list[str], label: str, payload: Mapping[str, Any], field: str) -> None:
    if payload.get(field) is not True:
        failures.append(f"{label}.{field}:not_true")


def validate_estimate(
    payload: Mapping[str, Any],
    rules: Mapping[str, Any],
    expected_fetch_date: str,
) -> tuple[list[str], dict[str, Any]]:
    failures: list[str] = []
    check_equal(failures, "estimate.schema_version", payload.get("schema_version"), rules.get("manifest_schema_version"))
    check_equal(failures, "estimate.verdict", payload.get("verdict"), rules.get("required_verdict"))
    check_equal(failures, "estimate.fetch_date", str(payload.get("fetch_date") or ""), expected_fetch_date)
    check_equal(
        failures,
        "estimate.collection_queue_status",
        payload.get("collection_queue_status"),
        rules.get("required_collection_queue_status"),
    )
    count_fields = {
        "collection_queue_selected_ticker_count": "required_selected_ticker_count",
        "ticker_count_requested": "required_requested_ticker_count",
        "ticker_count_attempted": "required_attempted_ticker_count",
        "collection_universe_ticker_count": "required_universe_ticker_count",
        "collection_eligible_ticker_count": "required_eligible_ticker_count",
        "collection_non_equity_placeholder_ticker_count": "required_non_equity_placeholder_ticker_count",
    }
    for field, rule in count_fields.items():
        check_equal(failures, f"estimate.{field}", integer(payload.get(field)), integer(rules.get(rule)))

    ack = payload.get("collection_attempt_ack") or {}
    if not isinstance(ack, Mapping):
        failures.append("estimate.collection_attempt_ack:not_object")
        ack = {}
    check_equal(failures, "estimate.collection_attempt_ack.status", ack.get("status"), "acknowledged")
    required_ack = integer(rules.get("required_acknowledged_ticker_count"))
    check_equal(failures, "estimate.collection_attempt_ack.attempted", integer(ack.get("attempted_ticker_count")), required_ack)
    check_equal(failures, "estimate.collection_attempt_ack.acknowledged", integer(ack.get("acknowledged_ticker_count")), required_ack)
    check_equal(failures, "estimate.collection_attempt_ack.unacknowledged", ack.get("unacknowledged_tickers"), [])
    check_equal(
        failures,
        "estimate.missing_vendor_coverage_policy",
        payload.get("missing_vendor_coverage_policy"),
        rules.get("required_missing_coverage_policy"),
    )
    check_equal(
        failures,
        "estimate.entitlement_circuit_threshold",
        integer(payload.get("entitlement_circuit_threshold")),
        integer(rules.get("entitlement_circuit_threshold")),
    )

    circuit = payload.get("vendor_entitlement_circuit") or {}
    if not isinstance(circuit, Mapping) or not circuit:
        failures.append("estimate.vendor_entitlement_circuit:missing_or_invalid")
        circuit = {}
    allowed_codes = sorted(integer(value) for value in rules.get("entitlement_circuit_status_codes", []))
    observed_codes = sorted(integer(value) for value in circuit.get("circuit_status_codes", []))
    check_equal(failures, "estimate.circuit_status_codes", observed_codes, allowed_codes)
    check_equal(failures, "estimate.circuit.enabled", circuit.get("enabled"), True)
    check_equal(failures, "estimate.circuit.run_scoped", circuit.get("run_scoped"), True)
    check_equal(failures, "estimate.circuit.persistent_vendor_block_written", circuit.get("persistent_vendor_block_written"), False)
    forbidden = {integer(value) for value in rules.get("forbidden_circuit_status_codes", [])}
    vendors = circuit.get("vendors") or {}
    if not isinstance(vendors, Mapping):
        failures.append("estimate.circuit.vendors:not_object")
        vendors = {}
    invalid_trip_signatures: list[str] = []
    observed_tripped: list[str] = []
    for vendor, record in vendors.items():
        if not isinstance(record, Mapping):
            failures.append(f"estimate.circuit.vendor:{vendor}:not_object")
            continue
        if record.get("tripped") is not True:
            continue
        observed_tripped.append(str(vendor))
        signature = str(record.get("trip_signature") or "")
        status_code = integer(signature.split(":", 1)[0]) if signature else -1
        if status_code not in allowed_codes or status_code in forbidden:
            invalid_trip_signatures.append(f"{vendor}:{signature or 'missing'}")
    if invalid_trip_signatures:
        failures.append("estimate.invalid_entitlement_trip:" + ",".join(sorted(invalid_trip_signatures)))
    declared_tripped = sorted(str(value) for value in circuit.get("tripped_vendors", []))
    check_equal(failures, "estimate.circuit.tripped_vendors", declared_tripped, sorted(observed_tripped))
    check_equal(failures, "estimate.circuit.tripped_vendor_count", integer(circuit.get("tripped_vendor_count")), len(observed_tripped))

    secret_scan = payload.get("text_secret_scan") or {}
    check_equal(failures, "estimate.unmasked_secret_pattern_found", secret_scan.get("unmasked_secret_pattern_found"), False)
    check_true(failures, "estimate", payload, "research_only")
    check_true(failures, "estimate", payload, "forward_only")
    for field in ("backtest_acceptance_allowed", "production_activation_allowed", "live_trading_enabled", "fullrun_dispatched"):
        check_false(failures, "estimate", payload, field)

    diagnostics = {
        "fetch_date": str(payload.get("fetch_date") or ""),
        "collector_status": str(payload.get("collector_status") or ""),
        "selected_ticker_count": integer(payload.get("collection_queue_selected_ticker_count"), 0),
        "attempted_ticker_count": integer(payload.get("ticker_count_attempted"), 0),
        "acknowledged_ticker_count": integer(ack.get("acknowledged_ticker_count"), 0),
        "request_snapshot_rows": integer(payload.get("request_snapshot_rows"), 0),
        "request_has_forward_estimate_rows": integer(payload.get("request_has_forward_estimate_rows"), 0),
        "error_count": integer(payload.get("error_count"), 0),
        "error_budget_count": integer(payload.get("error_budget_count"), 0),
        "entitlement_error_warn_only_count": integer(payload.get("entitlement_error_warn_only_count"), 0),
        "entitlement_error_probe_count": integer(payload.get("entitlement_error_probe_count"), 0),
        "entitlement_circuit_tripped_vendors": list(circuit.get("tripped_vendors") or []),
        "estimated_estimate_http_requests_avoided": integer(circuit.get("estimated_estimate_http_requests_avoided"), 0),
        "coverage_positive_required": bool(rules.get("coverage_positive_required")),
        "missing_coverage_is_neutral": payload.get("missing_vendor_coverage_policy") == "neutral",
    }
    return failures, diagnostics


def safety_failures(label: str, payload: Mapping[str, Any], *, archive: bool = False) -> list[str]:
    failures: list[str] = []
    check_false(failures, label, payload, "backtest_executed")
    check_false(failures, label, payload, "fullrun_executed")
    check_false(failures, label, payload, "orders_generated")
    check_false(failures, label, payload, "live_trading_enabled")
    check_false(failures, label, payload, "production_activation_allowed")
    if archive:
        check_false(failures, label, payload, "target_books_mutated")
        check_false(failures, label, payload, "selector_weights_changed")
        check_false(failures, label, payload, "cash_policy_changed")
    else:
        if "target_books_mutated" in payload:
            check_false(failures, label, payload, "target_books_mutated")
        if "target_book_file_written" in payload:
            check_false(failures, label, payload, "target_book_file_written")
    return failures


def validate_daily(
    payloads: Mapping[str, Mapping[str, Any]],
    rules: Mapping[str, Any],
    expected_session_date: str,
) -> tuple[list[str], dict[str, Any]]:
    failures: list[str] = []
    session = payloads["market_session"]
    section = rules["market_session"]
    check_equal(failures, "market_session.schema_version", session.get("schema_version"), section.get("schema_version"))
    check_equal(failures, "market_session.status", session.get("status"), section.get("required_status"))
    check_equal(failures, "market_session.session_date", str(session.get("session_date") or ""), expected_session_date)
    check_true(failures, "market_session", session, "ready")

    coverage = payloads["close_coverage"]
    section = rules["close_coverage"]
    check_equal(failures, "close_coverage.schema_version", coverage.get("schema_version"), section.get("schema_version"))
    check_equal(failures, "close_coverage.status", coverage.get("status"), section.get("required_status"))
    check_equal(failures, "close_coverage.session_date", str(coverage.get("session_date") or ""), expected_session_date)
    check_true(failures, "close_coverage", coverage, "exact_close_coverage")
    check_false(failures, "close_coverage", coverage, "prior_session_fallback_allowed")
    check_equal(failures, "close_coverage.missing_ticker_count", integer(coverage.get("missing_ticker_count")), 0)
    check_equal(
        failures,
        "close_coverage.exact_vs_required",
        integer(coverage.get("exact_ticker_count")),
        integer(coverage.get("required_ticker_count")),
    )
    for index, row in enumerate(coverage.get("rows") or []):
        if not isinstance(row, Mapping):
            failures.append(f"close_coverage.rows[{index}]:not_object")
            continue
        if str(row.get("actual_price_date") or "") != expected_session_date or row.get("exact_close_present") is not True:
            failures.append(f"close_coverage.rows[{index}]:not_exact_expected_session")
    coverage_rows = coverage.get("rows") or []
    check_equal(failures, "close_coverage.row_count", len(coverage_rows), integer(coverage.get("required_ticker_count")))
    coverage_tickers = [str(row.get("ticker") or "") for row in coverage_rows if isinstance(row, Mapping)]
    check_equal(failures, "close_coverage.unique_ticker_count", len(set(coverage_tickers)), integer(coverage.get("required_ticker_count")))

    date_fields = {
        "exact_upstream": "valuation_price_cutoff_date",
        "exact_registry": "valuation_price_cutoff_date",
        "exact_producer": "valuation_price_cutoff_date",
        "decision_archive": "latest_as_of_date",
        "risk_outcome": "as_of_date",
    }
    for label, date_field in date_fields.items():
        payload = payloads[label]
        section = rules[label]
        check_equal(failures, f"{label}.schema_version", payload.get("schema_version"), section.get("schema_version"))
        if "allowed_statuses" in section:
            if payload.get("status") not in section.get("allowed_statuses", []):
                failures.append(f"{label}.status:{payload.get('status')!r}:not_allowed")
        else:
            check_equal(failures, f"{label}.status", payload.get("status"), section.get("required_status"))
        check_equal(failures, f"{label}.{date_field}", str(payload.get(date_field) or ""), expected_session_date)

    upstream = payloads["exact_upstream"]
    check_true(failures, "exact_upstream", upstream, "upstream_ready")
    check_true(failures, "exact_upstream", upstream, "research_only")
    check_false(failures, "exact_upstream", upstream, "historical_cagr_mdd_evidence_changed")
    stage_audit = upstream.get("stage_audit") or []
    if not isinstance(stage_audit, list) or not stage_audit:
        failures.append("exact_upstream.stage_audit:missing_or_invalid")
    else:
        for index, stage in enumerate(stage_audit):
            if not isinstance(stage, Mapping) or stage.get("failures") not in ([], None):
                failures.append(f"exact_upstream.stage_audit[{index}]:failure")
    if not isinstance(upstream.get("source_bundle"), Mapping):
        failures.append("exact_upstream.source_bundle:missing_or_invalid")
    failures.extend(safety_failures("exact_upstream", upstream))
    registry = payloads["exact_registry"]
    check_equal(failures, "exact_registry.contract_failures", registry.get("contract_failures"), [])
    check_true(failures, "exact_registry", registry, "research_only")
    failures.extend(safety_failures("exact_registry", registry))
    producer = payloads["exact_producer"]
    check_true(failures, "exact_producer", producer, "exact_packet_ready")
    check_equal(failures, "exact_producer.contract_failures", producer.get("contract_failures"), [])
    check_true(failures, "exact_producer", producer, "research_only")
    check_false(failures, "exact_producer", producer, "historical_cagr_mdd_evidence_changed")
    check_false(failures, "exact_producer", producer, "selector_weights_changed_by_producer")
    failures.extend(safety_failures("exact_producer", producer))
    decision = payloads["decision_archive"]
    check_true(failures, "decision_archive", decision, "archive_passed")
    check_equal(failures, "decision_archive.contract_failures", decision.get("contract_failures"), [])
    check_true(failures, "decision_archive", decision, "review_only")
    check_false(failures, "decision_archive", decision, "archive_may_promote")
    check_false(failures, "decision_archive", decision, "source_inputs_mutated")
    check_false(failures, "decision_archive", decision, "historical_cagr_mdd_evidence_changed")
    failures.extend(safety_failures("decision_archive", decision, archive=True))
    risk = payloads["risk_outcome"]
    check_equal(failures, "risk_outcome.blockers", risk.get("blockers"), [])
    check_true(failures, "risk_outcome", risk, "review_only")
    check_false(failures, "risk_outcome", risk, "historical_cagr_mdd_evidence_changed")
    failures.extend(safety_failures("risk_outcome", risk, archive=True))
    for field in ("stop_or_exit_rule_created", "threshold_tuning_allowed", "portfolio_transition_allowed", "mechanism_promotion_allowed"):
        check_false(failures, "risk_outcome", risk, field)

    one_day_counts = (risk.get("horizon_status_counts") or {}).get("1d") or {}
    completed_1d = integer(one_day_counts.get("completed"), 0)
    one_day_metrics = (risk.get("group_metrics") or {}).get("1d") or {}
    warning = one_day_metrics.get("warning") or {}
    normal = one_day_metrics.get("normal") or {}
    delta = one_day_metrics.get("warning_minus_normal") or {}
    mechanism_ready = risk.get("mechanism_review_ready") is True
    diagnostics = {
        "session_date": expected_session_date,
        "exact_close_ticker_count": integer(coverage.get("exact_ticker_count"), 0),
        "first_1d_available": completed_1d > 0,
        "completed_1d_count": completed_1d,
        "warning_1d_count": integer(warning.get("count"), 0),
        "normal_1d_count": integer(normal.get("count"), 0),
        "warning_minus_normal_1d": dict(delta) if isinstance(delta, Mapping) else {},
        "mechanism_review_ready": mechanism_ready,
        "mechanism_review_allowed": mechanism_ready,
        "mechanism_review_horizon": rules["risk_outcome"].get("mechanism_review_horizon"),
        "rule_change_allowed": False,
        "historical_ab_allowed": False,
    }
    return failures, diagnostics


def write_report(output_dir: Path, summary: Mapping[str, Any]) -> None:
    estimate = summary.get("estimate_gate") or {}
    daily = summary.get("daily_gate") or {}
    lines = [
        "# Run287 next scheduled artifact gate",
        "",
        f"- Status: `{summary['status']}`",
        f"- Expected estimate fetch date: `{summary['expected_estimate_fetch_date']}`",
        f"- Expected market session: `{summary['expected_session_date']}`",
        f"- Estimate selected/attempted/acknowledged: `{estimate.get('selected_ticker_count', 0)}` / `{estimate.get('attempted_ticker_count', 0)}` / `{estimate.get('acknowledged_ticker_count', 0)}`",
        f"- First 1D resolved rows: `{daily.get('completed_1d_count', 0)}`",
        f"- 1D warning/normal rows: `{daily.get('warning_1d_count', 0)}` / `{daily.get('normal_1d_count', 0)}`",
        f"- 63D mechanism review ready: `{str(daily.get('mechanism_review_ready', False)).lower()}`",
        "- A 1D result is diagnostic only; it cannot change a rule or open a historical A/B.",
        "- No latest-file discovery, network request, backtest, fullrun, order, book, weight, cash, production, or live-trading action was performed.",
    ]
    missing = summary.get("missing_artifacts") or []
    if missing:
        lines.extend(["", "## Missing evidence", ""] + [f"- `{item}`" for item in missing])
    failures = summary.get("contract_failures") or []
    if failures:
        lines.extend(["", "## Contract failures", ""] + [f"- `{item}`" for item in failures])
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def audit(
    *,
    contract_path: Path,
    expected_session_date: str,
    expected_estimate_fetch_date: str,
    estimate_manifest_path: Path | None,
    market_session_path: Path | None,
    close_coverage_path: Path | None,
    exact_upstream_status_path: Path | None,
    exact_registry_status_path: Path | None,
    exact_producer_status_path: Path | None,
    decision_archive_manifest_path: Path | None,
    risk_outcome_summary_path: Path | None,
    output_dir: Path,
    generated_at: str | None = None,
) -> dict[str, Any]:
    contract, contract_audit = load_evidence("contract", contract_path)
    if contract.get("schema_version") != CONTRACT_SCHEMA:
        raise ValueError("invalid scheduled artifact gate contract schema")
    paths = {
        "estimate_manifest": estimate_manifest_path,
        "market_session": market_session_path,
        "close_coverage": close_coverage_path,
        "exact_upstream": exact_upstream_status_path,
        "exact_registry": exact_registry_status_path,
        "exact_producer": exact_producer_status_path,
        "decision_archive": decision_archive_manifest_path,
        "risk_outcome": risk_outcome_summary_path,
    }
    payloads: dict[str, dict[str, Any]] = {}
    input_audit: dict[str, dict[str, Any]] = {"contract": contract_audit}
    missing: list[str] = []
    parse_failures: list[str] = []
    for label, path in paths.items():
        payload, record = load_evidence(label, path)
        payloads[label] = payload
        input_audit[label] = record
        if not record["exists"]:
            missing.append(label)
        elif record["parse_error"]:
            parse_failures.append(f"{label}.parse_error:{record['parse_error']}")

    failures = list(parse_failures)
    estimate_diagnostics: dict[str, Any] = {}
    daily_diagnostics: dict[str, Any] = {}
    if "estimate_manifest" not in missing and not input_audit["estimate_manifest"]["parse_error"]:
        found, estimate_diagnostics = validate_estimate(
            payloads["estimate_manifest"], contract["estimate_gate"], expected_estimate_fetch_date
        )
        failures.extend(found)
    daily_labels = {"market_session", "close_coverage", "exact_upstream", "exact_registry", "exact_producer", "decision_archive", "risk_outcome"}
    if not daily_labels.intersection(missing) and not any(input_audit[label]["parse_error"] for label in daily_labels):
        found, daily_diagnostics = validate_daily(payloads, contract["daily_gate"], expected_session_date)
        failures.extend(found)

    failures = sorted(set(failures))
    missing = sorted(set(missing))
    first_1d_available = bool(daily_diagnostics.get("first_1d_available"))
    if failures:
        status = BLOCKED_STATUS
    elif missing:
        status = PENDING_MISSING_STATUS
    elif not first_1d_available:
        status = PENDING_1D_STATUS
    else:
        status = READY_STATUS

    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated_at or utc_now(),
        "status": status,
        "expected_session_date": expected_session_date,
        "expected_estimate_fetch_date": expected_estimate_fetch_date,
        "estimate_gate": estimate_diagnostics,
        "daily_gate": daily_diagnostics,
        "missing_artifacts": missing,
        "contract_failures": failures,
        "input_audit": input_audit,
        "safety": contract["safety"],
        "research_only": True,
        "review_only": True,
        "network_requests_executed": 0,
        "backtest_executed": False,
        "fullrun_executed": False,
        "orders_generated": False,
        "target_books_mutated": False,
        "selector_weights_changed": False,
        "cash_policy_changed": False,
        "rule_change_allowed": False,
        "historical_ab_allowed": False,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "summary.json", summary)
    write_report(output_dir, summary)
    return summary


def optional_path(value: str) -> Path | None:
    return repo_path(value) if str(value).strip() else None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", default="docs/run287_next_scheduled_artifact_gate_contract.json")
    parser.add_argument("--expected-session-date", required=True)
    parser.add_argument("--expected-estimate-fetch-date", required=True)
    parser.add_argument("--estimate-manifest", default="")
    parser.add_argument("--market-session", default="")
    parser.add_argument("--close-coverage", default="")
    parser.add_argument("--exact-upstream-status", default="")
    parser.add_argument("--exact-registry-status", default="")
    parser.add_argument("--exact-producer-status", default="")
    parser.add_argument("--decision-archive-manifest", default="")
    parser.add_argument("--risk-outcome-summary", default="")
    parser.add_argument("--output-dir", default="outputs/run287_next_scheduled_artifact_gate")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = audit(
        contract_path=repo_path(args.contract),
        expected_session_date=args.expected_session_date,
        expected_estimate_fetch_date=args.expected_estimate_fetch_date,
        estimate_manifest_path=optional_path(args.estimate_manifest),
        market_session_path=optional_path(args.market_session),
        close_coverage_path=optional_path(args.close_coverage),
        exact_upstream_status_path=optional_path(args.exact_upstream_status),
        exact_registry_status_path=optional_path(args.exact_registry_status),
        exact_producer_status_path=optional_path(args.exact_producer_status),
        decision_archive_manifest_path=optional_path(args.decision_archive_manifest),
        risk_outcome_summary_path=optional_path(args.risk_outcome_summary),
        output_dir=repo_path(args.output_dir),
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 2 if result["status"] == BLOCKED_STATUS else 0


if __name__ == "__main__":
    raise SystemExit(main())
