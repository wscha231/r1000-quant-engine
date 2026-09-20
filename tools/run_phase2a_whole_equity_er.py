#!/usr/bin/env python3
"""Bind a verified whole-US-equity cohort to the existing Run287 ER outputs.

This is a fail-closed Phase 2A adapter. It does not train a model, create a
ranking, change a target book, place orders, mutate a ledger, or synthesize a
12-month expected return. Rows that fail identity / availability / corporate-
action / ADR-share-basis checks remain present with expected-return fields null.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any, Iterable, Mapping

SCHEMA_VERSION = "phase2a-whole-equity-er-a3-v1"
CONTRACT_SCHEMA = "phase2a-whole-equity-er-contract-v1"
READY_CHALLENGER_STATUS = "READY_EXPECTED_RETURN_FORWARD_REVIEW_ONLY"
EXPECTED_FAMILY_ID = "future_expected_excess_return_multihorizon_v1"
EXPECTED_ER_CONTRACT_SHA256 = "ef61acafc2c42b86d75d85becea816a4bca8e05fbbc392e77fa92b075c728b63"
RUN287_SCHEMA_VERSION = "run287-expected-return-challenger-v1"
FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
OVERALL_READY = "READY_WHOLE_EQUITY_ER_1_3_6M"
OVERALL_PARTIAL = "PARTIAL_BLOCKED_WHOLE_EQUITY_ER"
ROW_READY = "READY_ER_1_3_6M_RESEARCH_ONLY"
ROW_PARTIAL = "PARTIAL_ER_HORIZON_BLOCKED_RESEARCH_ONLY"
ROW_BLOCKED = "BLOCKED_A1_OR_ER_EVIDENCE"
HORIZON_BLOCKED = "BLOCKED_HORIZON_ER_EVIDENCE"
TWELVE_MONTH_BLOCKER = "BLOCKED_MODEL_NOT_VALIDATED"
HORIZONS: dict[str, int] = {"1m": 21, "3m": 63, "6m": 126}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
FORBIDDEN_PROPOSAL_RE = re.compile(r"(^|_)(realized|label|target|outcome)(_|$)|^y_", re.IGNORECASE)
CANONICAL_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/+-]*$")
CANONICAL_TICKER_RE = re.compile(r"^[A-Z0-9][A-Z0-9.-]*$")
ACCEPTED_CORPORATE_ACTION_BASES = {
    "SPLIT_AND_DIVIDEND_ADJUSTED_TOTAL_RETURN",
    "SPLIT_DIVIDEND_ADJUSTED_TOTAL_RETURN",
}
ACCEPTED_INSTRUMENTS = {"COMMON", "ADR"}


def reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise ValueError(f"duplicate_json_key:{key}")
        out[key] = value
    return out


def read_json(path: Path) -> Any:
    return json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=reject_duplicate_json_keys,
    )


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json_sha256(path: Path) -> str:
    return sha256_bytes(canonical_bytes(read_json(path)))


def fingerprint(path: Path) -> dict[str, Any]:
    return {
        "path": path.as_posix(),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def utc(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"missing_timestamp:{field}")
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError(f"naive_timestamp:{field}")
    return stamp.astimezone(timezone.utc)


def session_date(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"missing_session_date:{field}")
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"invalid_session_date:{field}") from exc
    return stamp.date().isoformat()


def finite(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def canonical_id(value: Any, field: str) -> str:
    if not isinstance(value, str) or value != value.strip() or not CANONICAL_ID_RE.fullmatch(value):
        raise ValueError(f"invalid_identity:{field}")
    return value


def canonical_ticker(value: Any) -> str:
    if not isinstance(value, str) or value != value.strip() or not CANONICAL_TICKER_RE.fullmatch(value):
        raise ValueError("invalid_identity:ticker")
    return value


def load_contract(path: Path) -> dict[str, Any]:
    value = read_json(path)
    if not isinstance(value, dict) or value.get("schema_version") != CONTRACT_SCHEMA:
        raise ValueError("phase2a_contract_schema_mismatch")
    if value.get("expected_return_family_id") != EXPECTED_FAMILY_ID:
        raise ValueError("phase2a_contract_family_mismatch")
    if value.get("12m_policy") != TWELVE_MONTH_BLOCKER:
        raise ValueError("phase2a_contract_12m_policy_mismatch")
    return value


def load_cohort(path: Path) -> dict[str, Any]:
    value = read_json(path)
    if not isinstance(value, dict):
        raise ValueError("cohort_not_object")
    if value.get("status") != "ADMITTED_RESEARCH_ONLY":
        raise ValueError("cohort_not_admitted")
    if value.get("runtime_executed") is not True:
        raise ValueError("cohort_runtime_not_executed")
    if value.get("company_evaluator_executed") not in (False, None):
        raise ValueError("cohort_unexpected_company_evaluator_authority")
    decision_at = utc(value.get("decision_at"), "cohort.decision_at")
    expected_session = value.get("expected_session")
    if not isinstance(expected_session, str) or len(expected_session) != 10:
        raise ValueError("cohort_expected_session_invalid")
    if decision_at.date().isoformat() != expected_session:
        raise ValueError("cohort_decision_session_mismatch")
    inventory = value.get("evaluation_inventory")
    queue = (value.get("data_queue_preview") or {}).get("items")
    if not isinstance(inventory, list) or not inventory:
        raise ValueError("cohort_evaluation_inventory_missing")
    if not isinstance(queue, list) or not queue:
        raise ValueError("cohort_queue_missing")
    inventory_ids = [canonical_id(row.get("security_id"), "security_id") for row in inventory]
    queue_ids = [canonical_id(row.get("security_id"), "security_id") for row in queue]
    if len(inventory_ids) != len(set(inventory_ids)):
        raise ValueError("cohort_duplicate_security_id")
    if len(queue_ids) != len(set(queue_ids)):
        raise ValueError("cohort_duplicate_queue_security_id")
    if set(inventory_ids) != set(queue_ids):
        raise ValueError("cohort_inventory_queue_identity_mismatch")
    return value


def load_identity_registry(path: Path) -> dict[str, dict[str, Any]]:
    value = read_json(path)
    rows = value.get("securities") if isinstance(value, dict) else value
    if not isinstance(rows, list) or not rows:
        raise ValueError("identity_registry_missing_rows")
    by_id: dict[str, dict[str, Any]] = {}
    seen_tickers: dict[str, str] = {}
    for raw in rows:
        if not isinstance(raw, dict):
            raise ValueError("identity_registry_row_not_object")
        security_id = canonical_id(raw.get("security_id"), "security_id")
        ticker = canonical_ticker(raw.get("ticker"))
        if security_id in by_id:
            raise ValueError("identity_registry_duplicate_security_id")
        if ticker in seen_tickers and seen_tickers[ticker] != security_id:
            raise ValueError("identity_registry_ticker_not_one_to_one")
        seen_tickers[ticker] = security_id
        by_id[security_id] = raw
    return by_id


def identity_blockers(row: Mapping[str, Any], decision_at: datetime) -> list[str]:
    blockers: list[str] = []
    try:
        canonical_id(row.get("security_id"), "security_id")
        canonical_id(row.get("issuer_id"), "issuer_id")
        canonical_ticker(row.get("ticker"))
    except ValueError as exc:
        blockers.append(str(exc))
    if row.get("identity_verified") is not True:
        blockers.append("security_identity_unverified")
    if row.get("research_eligible") is not True:
        blockers.append("research_eligibility_unverified")
    instrument = row.get("instrument")
    if instrument not in ACCEPTED_INSTRUMENTS:
        blockers.append("unsupported_or_missing_share_basis")
    try:
        if utc(row.get("available_at"), "identity.available_at") > decision_at:
            blockers.append("future_identity_availability")
    except ValueError as exc:
        blockers.append(str(exc))
    corporate_basis = row.get("corporate_action_basis")
    if row.get("corporate_action_verified") is not True or corporate_basis not in ACCEPTED_CORPORATE_ACTION_BASES:
        blockers.append("corporate_action_basis_unverified")
    if instrument == "ADR":
        adr_ratio = finite(row.get("adr_ratio"))
        if row.get("adr_share_basis_verified") is not True or adr_ratio is None or adr_ratio <= 0.0:
            blockers.append("adr_share_basis_unverified")
        if not isinstance(row.get("underlying_currency"), str) or not row.get("underlying_currency"):
            blockers.append("adr_underlying_currency_unverified")
    return sorted(set(blockers))


def read_csv_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError("proposal_header_missing")
        fields = list(reader.fieldnames)
        if len(fields) != len(set(fields)):
            raise ValueError("proposal_duplicate_columns")
        rows = list(reader)
    return fields, rows


def verify_er_evidence(
    proposal_path: Path,
    summary_path: Path,
    manifest_path: Path,
    contract_path: Path,
    decision_session: str,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    summary = read_json(summary_path)
    manifest = read_json(manifest_path)
    if not isinstance(summary, dict) or summary.get("status") != READY_CHALLENGER_STATUS:
        raise ValueError("er_summary_not_ready")
    if summary.get("schema_version") != RUN287_SCHEMA_VERSION:
        raise ValueError("er_summary_schema_mismatch")
    if summary.get("family_id") != EXPECTED_FAMILY_ID:
        raise ValueError("er_summary_family_mismatch")
    if summary.get("historical_model_fit_executed") is not True:
        raise ValueError("er_summary_historical_fit_not_executed")
    if summary.get("historical_backtest_executed") is not False:
        raise ValueError("er_summary_backtest_authority_mismatch")
    if not isinstance(manifest, dict) or manifest.get("status") != READY_CHALLENGER_STATUS:
        raise ValueError("er_manifest_not_ready")
    if manifest.get("schema_version") != RUN287_SCHEMA_VERSION:
        raise ValueError("er_manifest_schema_mismatch")
    if manifest.get("historical_fit_executed") is not True:
        raise ValueError("er_historical_fit_not_executed")
    if manifest.get("historical_backtest_executed") is not False:
        raise ValueError("er_manifest_backtest_authority_mismatch")
    producer_sha = str(manifest.get("git_commit_sha") or "").lower()
    if not FULL_SHA_RE.fullmatch(producer_sha):
        raise ValueError("er_manifest_producer_git_sha_invalid")
    utc(manifest.get("created_at_utc"), "er_manifest.created_at_utc")
    contract_doc = read_json(contract_path)
    contract_hash = sha256_bytes(canonical_bytes(contract_doc))
    if contract_hash != EXPECTED_ER_CONTRACT_SHA256:
        raise ValueError("er_contract_not_canonical_run287_contract")
    if manifest.get("contract_sha256") != contract_hash:
        raise ValueError("er_contract_hash_mismatch")
    inputs = manifest.get("inputs")
    if not isinstance(inputs, dict):
        raise ValueError("er_manifest_inputs_missing")
    canonical_u0 = inputs.get("u0_canonical_artifact")
    if not isinstance(canonical_u0, dict):
        raise ValueError("er_manifest_u0_canonical_artifact_missing")
    if not FULL_SHA_RE.fullmatch(str(canonical_u0.get("head_sha") or "").lower()):
        raise ValueError("er_manifest_u0_head_sha_invalid")
    if type(canonical_u0.get("artifact_id")) is not int or canonical_u0["artifact_id"] <= 0:
        raise ValueError("er_manifest_u0_artifact_id_invalid")
    if type(canonical_u0.get("workflow_run_id")) is not int or canonical_u0["workflow_run_id"] <= 0:
        raise ValueError("er_manifest_u0_workflow_run_id_invalid")
    historical_gate = contract_doc.get("historical_gate") if isinstance(contract_doc, dict) else None
    expected_workflow = historical_gate.get("accepted_workflow_path") if isinstance(historical_gate, dict) else None
    if not isinstance(expected_workflow, str) or canonical_u0.get("workflow_path") != expected_workflow:
        raise ValueError("er_manifest_u0_workflow_path_mismatch")
    digest = str(canonical_u0.get("artifact_digest") or "")
    if not digest.startswith("sha256:") or not SHA256_RE.fullmatch(digest[7:]):
        raise ValueError("er_manifest_u0_artifact_digest_invalid")
    contract_input = inputs.get("contract")
    if not isinstance(contract_input, dict) or contract_input.get("sha256") != sha256_file(contract_path):
        raise ValueError("er_manifest_contract_input_hash_mismatch")
    if contract_input.get("exists") is not True or int(contract_input.get("bytes") or 0) != contract_path.stat().st_size:
        raise ValueError("er_manifest_contract_input_size_mismatch")
    feature_store = inputs.get("feature_store")
    if not isinstance(feature_store, dict) or not SHA256_RE.fullmatch(str(feature_store.get("sha256") or "")):
        raise ValueError("er_manifest_feature_store_identity_invalid")
    if feature_store.get("exists") is not True or int(feature_store.get("bytes") or 0) <= 0:
        raise ValueError("er_manifest_feature_store_not_verified")
    outputs = manifest.get("outputs")
    if not isinstance(outputs, dict):
        raise ValueError("er_manifest_outputs_missing")
    proposal_ref = outputs.get("latest_expected_return_proposal.csv")
    if not isinstance(proposal_ref, dict) or proposal_ref.get("sha256") != sha256_file(proposal_path):
        raise ValueError("er_proposal_hash_mismatch")
    if int(proposal_ref.get("bytes") or -1) != proposal_path.stat().st_size:
        raise ValueError("er_proposal_size_mismatch")
    summary_ref = outputs.get("summary.json")
    if not isinstance(summary_ref, dict) or summary_ref.get("sha256") != sha256_file(summary_path):
        raise ValueError("er_summary_hash_mismatch")
    if int(summary_ref.get("bytes") or -1) != summary_path.stat().st_size:
        raise ValueError("er_summary_size_mismatch")
    fields, rows = read_csv_rows(proposal_path)
    forbidden = sorted(field for field in fields if FORBIDDEN_PROPOSAL_RE.search(field))
    if forbidden:
        raise ValueError("proposal_contains_forward_or_label_columns:" + ",".join(forbidden))
    required = {"feature_date", "ticker"}
    for name, days in HORIZONS.items():
        required.update(
            {
                f"expected_absolute_{days}d",
                f"expected_benchmark_excess_{days}d",
                f"expected_alpha_{days}d",
                f"downside_probability_{days}d",
                f"feature_coverage_{days}d",
                f"model_disagreement_{days}d",
            }
        )
    missing = sorted(required - set(fields))
    if missing:
        raise ValueError("proposal_missing_required_columns:" + ",".join(missing))
    tickers: set[str] = set()
    for row in rows:
        ticker = canonical_ticker(row.get("ticker"))
        if ticker in tickers:
            raise ValueError("proposal_duplicate_ticker")
        tickers.add(ticker)
        if session_date(row.get("feature_date"), "proposal.feature_date") != decision_session:
            raise ValueError("proposal_stale_or_future_decision_date")
    if session_date(summary.get("latest_decision_date"), "summary.latest_decision_date") != decision_session:
        raise ValueError("er_summary_decision_date_mismatch")
    if summary.get("latest_candidate_count") != len(rows):
        raise ValueError("er_summary_candidate_count_mismatch")
    return manifest, rows


def null_horizon() -> dict[str, Any]:
    return {
        "expected_return": None,
        "benchmark_expected_return": None,
        "expected_alpha": None,
        "downside_probability": None,
        "expected_drawdown": None,
        "signal_confidence": None,
        "model_disagreement": None,
        "feature_coverage": None,
        "status": HORIZON_BLOCKED,
    }


def horizon_from_proposal(row: Mapping[str, str], days: int) -> tuple[dict[str, Any], list[str]]:
    blockers: list[str] = []
    absolute = finite(row.get(f"expected_absolute_{days}d"))
    benchmark_excess = finite(row.get(f"expected_benchmark_excess_{days}d"))
    alpha = finite(row.get(f"expected_alpha_{days}d"))
    downside = finite(row.get(f"downside_probability_{days}d"))
    coverage = finite(row.get(f"feature_coverage_{days}d"))
    disagreement = finite(row.get(f"model_disagreement_{days}d"))
    values = {
        "expected_return": absolute,
        "expected_alpha": alpha,
        "downside_probability": downside,
        "feature_coverage": coverage,
        "model_disagreement": disagreement,
    }
    for key, value in values.items():
        if value is None:
            blockers.append(f"missing_or_nonfinite_{key}_{days}d")
    if benchmark_excess is None:
        blockers.append(f"missing_or_nonfinite_benchmark_excess_{days}d")
    if downside is not None and not 0.0 <= downside <= 1.0:
        blockers.append(f"downside_probability_out_of_range_{days}d")
    if coverage is not None and not 0.0 <= coverage <= 1.0:
        blockers.append(f"feature_coverage_out_of_range_{days}d")
    if blockers:
        return null_horizon(), sorted(set(blockers))
    benchmark_expected = absolute - benchmark_excess
    return {
        "expected_return": absolute,
        "benchmark_expected_return": benchmark_expected,
        "benchmark_expected_return_basis": "IMPLIED_ABSOLUTE_MINUS_BENCHMARK_EXCESS",
        "expected_alpha": alpha,
        "downside_probability": downside,
        "expected_drawdown": None,
        "signal_confidence": None,
        "model_disagreement": disagreement,
        "feature_coverage": coverage,
        "status": "VALIDATED_EXISTING_CHALLENGER_OUTPUT",
    }, []


def build_output(
    cohort: Mapping[str, Any],
    registry: Mapping[str, Mapping[str, Any]],
    proposal_rows: Iterable[Mapping[str, str]],
    evidence: Mapping[str, Any],
) -> dict[str, Any]:
    decision_at = utc(cohort.get("decision_at"), "cohort.decision_at")
    decision_session = str(cohort["expected_session"])
    queue = (cohort.get("data_queue_preview") or {}).get("items") or []
    queue_by_id = {str(row["security_id"]): row for row in queue}
    cohort_ids = [str(row["security_id"]) for row in cohort["evaluation_inventory"]]
    proposal_by_ticker = {str(row["ticker"]): row for row in proposal_rows}

    rows: list[dict[str, Any]] = []
    evaluated = 0
    partially_evaluated = 0
    blocked = 0
    for security_id in cohort_ids:
        queue_row = queue_by_id[security_id]
        ticker = canonical_ticker(queue_row.get("ticker"))
        identity = registry.get(security_id)
        row_blockers: list[str] = []
        if identity is None:
            row_blockers.append("security_identity_registry_missing")
        else:
            if identity.get("ticker") != ticker:
                row_blockers.append("security_identity_ticker_mismatch")
            row_blockers.extend(identity_blockers(identity, decision_at))
        proposal = proposal_by_ticker.get(ticker)
        if proposal is None:
            row_blockers.append("expected_return_row_missing")
        horizons: dict[str, Any] = {}
        horizon_blockers: list[str] = []
        if not row_blockers and proposal is not None:
            for name, days in HORIZONS.items():
                horizon, current_blockers = horizon_from_proposal(proposal, days)
                horizons[name] = horizon
                horizon_blockers.extend(current_blockers)
        else:
            horizons = {name: null_horizon() for name in HORIZONS}
        row_blockers = sorted(set(row_blockers))
        horizon_blockers = sorted(set(horizon_blockers))
        if row_blockers:
            blocked += 1
            # A1 or row-evidence failures invalidate all horizons for the security.
            horizons = {name: null_horizon() for name in HORIZONS}
            row_status = ROW_BLOCKED
            blockers = row_blockers
        elif horizon_blockers:
            partially_evaluated += 1
            # Preserve independently validated horizons; null only the invalid horizon.
            row_status = ROW_PARTIAL
            blockers = horizon_blockers
        else:
            evaluated += 1
            row_status = ROW_READY
            blockers = []
        rows.append(
            {
                "security_id": security_id,
                "ticker": ticker,
                "issuer_id": identity.get("issuer_id") if identity else None,
                "instrument": identity.get("instrument") if identity else None,
                "status": row_status,
                "expected_return_1m": horizons["1m"]["expected_return"],
                "expected_return_3m": horizons["3m"]["expected_return"],
                "expected_return_6m": horizons["6m"]["expected_return"],
                "expected_return_12m": None,
                "benchmark_expected_return_1m": horizons["1m"].get("benchmark_expected_return"),
                "benchmark_expected_return_3m": horizons["3m"].get("benchmark_expected_return"),
                "benchmark_expected_return_6m": horizons["6m"].get("benchmark_expected_return"),
                "benchmark_expected_return_12m": None,
                "expected_alpha_1m": horizons["1m"]["expected_alpha"],
                "expected_alpha_3m": horizons["3m"]["expected_alpha"],
                "expected_alpha_6m": horizons["6m"]["expected_alpha"],
                "expected_alpha_12m": None,
                "downside_probability_1m": horizons["1m"]["downside_probability"],
                "downside_probability_3m": horizons["3m"]["downside_probability"],
                "downside_probability_6m": horizons["6m"]["downside_probability"],
                "downside_probability_12m": None,
                "expected_drawdown": None,
                "signal_confidence": None,
                "thesis_confidence": None,
                "valuation_status": None,
                "thesis_status": None,
                "horizon_status": {
                    "1m": horizons["1m"]["status"],
                    "3m": horizons["3m"]["status"],
                    "6m": horizons["6m"]["status"],
                    "12m": TWELVE_MONTH_BLOCKER,
                },
                "blockers": blockers
                + [
                    TWELVE_MONTH_BLOCKER,
                    "expected_drawdown_not_validated",
                    "signal_confidence_not_calibrated",
                    "fundamental_thesis_layer_not_integrated",
                ],
            }
        )

    whole_ready = (
        blocked == 0
        and partially_evaluated == 0
        and evaluated == len(cohort_ids)
        and len(cohort_ids) > 0
    )
    output: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "status": OVERALL_READY if whole_ready else OVERALL_PARTIAL,
        "research_only": True,
        "decision_session": decision_session,
        "decision_at": cohort["decision_at"],
        "expected_return_family_id": EXPECTED_FAMILY_ID,
        "requested_security_count": len(cohort_ids),
        "evaluated_security_count": evaluated,
        "partially_evaluated_security_count": partially_evaluated,
        "blocked_security_count": blocked,
        "not_ready_security_count": blocked + partially_evaluated,
        "whole_equity_er_ready_1_3_6m": whole_ready,
        "expected_return_12m_status": TWELVE_MONTH_BLOCKER,
        "global_ranking_ready": False,
        "a5_execution_allowed": False,
        "target_authority": False,
        "order_authority": False,
        "portfolio_mutation_allowed": False,
        "automatic_promotion_allowed": False,
        "rows": rows,
        "evidence": dict(evidence),
    }
    output["artifact_sha256"] = sha256_bytes(canonical_bytes(output))
    return output


def run(args: argparse.Namespace) -> dict[str, Any]:
    contract_path = Path(args.contract)
    cohort_path = Path(args.cohort)
    registry_path = Path(args.identity_registry)
    proposal_path = Path(args.er_proposal)
    summary_path = Path(args.er_summary)
    manifest_path = Path(args.er_source_manifest)
    er_contract_path = Path(args.er_contract)
    output_path = Path(args.output)

    contract = load_contract(contract_path)
    cohort = load_cohort(cohort_path)
    registry = load_identity_registry(registry_path)
    manifest, proposal_rows = verify_er_evidence(
        proposal_path,
        summary_path,
        manifest_path,
        er_contract_path,
        str(cohort["expected_session"]),
    )
    expected_ids = {str(row["security_id"]) for row in cohort["evaluation_inventory"]}
    if not expected_ids.issubset(registry):
        missing = sorted(expected_ids - set(registry))
        raise ValueError("identity_registry_missing_cohort_ids:" + ",".join(missing[:20]))

    evidence = {
        "phase2a_contract": fingerprint(contract_path),
        "cohort": fingerprint(cohort_path),
        "identity_registry": fingerprint(registry_path),
        "er_proposal": fingerprint(proposal_path),
        "er_summary": fingerprint(summary_path),
        "er_source_manifest": fingerprint(manifest_path),
        "er_contract": fingerprint(er_contract_path),
        "er_contract_sha256_from_manifest": manifest.get("contract_sha256"),
        "er_model_family": EXPECTED_FAMILY_ID,
        "er_horizons_nyse_sessions": HORIZONS,
        "phase2a_policy_sha256": sha256_bytes(canonical_bytes(contract)),
    }
    output = build_output(cohort, registry, proposal_rows, evidence)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(output, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return output


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", default="docs/phase2a_whole_equity_er_contract.json")
    parser.add_argument("--cohort", required=True)
    parser.add_argument("--identity-registry", required=True)
    parser.add_argument("--er-proposal", required=True)
    parser.add_argument("--er-summary", required=True)
    parser.add_argument("--er-source-manifest", required=True)
    parser.add_argument("--er-contract", default="docs/run287_expected_return_challenger_contract.json")
    parser.add_argument("--output", required=True)
    return parser.parse_args()


def main() -> int:
    try:
        result = run(parse_args())
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "BLOCKED_PHASE2A_INPUT", "reason": str(exc)}, sort_keys=True))
        return 2
    print(
        json.dumps(
            {
                "status": result["status"],
                "requested_security_count": result["requested_security_count"],
                "evaluated_security_count": result["evaluated_security_count"],
                "blocked_security_count": result["blocked_security_count"],
                "whole_equity_er_ready_1_3_6m": result["whole_equity_er_ready_1_3_6m"],
                "expected_return_12m_status": result["expected_return_12m_status"],
            },
            sort_keys=True,
        )
    )
    return 0 if result["whole_equity_er_ready_1_3_6m"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
