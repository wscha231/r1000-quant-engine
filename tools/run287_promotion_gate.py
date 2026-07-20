#!/usr/bin/env python3
"""Canonical Run287 promotion and rollback governance primitives."""
from __future__ import annotations

import hashlib
import json
import math
import csv
import copy
from datetime import date
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONTRACT = ROOT / "data_static" / "run287_promotion_gate_contract.json"
DEFAULT_STATE = ROOT / "data_static" / "run287_promotion_state.json"
DEFAULT_EVIDENCE = ROOT / "data_static" / "run287_promotion_evidence_current.json"
STATE_SCHEMA = "run287-promotion-state-v1"
GATE_SCHEMA = "run287-promotion-gate-v1"
ACCOUNT_CONTRACT_FIELDS = (
    "data_contract_sha256",
    "close_contract_sha256",
    "cost_contract_sha256",
    "reserve_contract_sha256",
    "lifecycle_contract_sha256",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha256(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object required: {path}")
    return payload


def _integer(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a nonnegative integer")
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a nonnegative integer") from exc
    if number < 0 or (isinstance(value, float) and not math.isclose(value, number)):
        raise ValueError(f"{field} must be a nonnegative integer")
    return number


def validate_contract(contract: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if contract.get("schema_version") != "run287-promotion-gate-contract-v1":
        errors.append("contract_schema_invalid")
    states = contract.get("states")
    if not isinstance(states, list) or len(states) != 6 or len(set(states)) != 6:
        errors.append("contract_states_invalid")
    rules = contract.get("rules") or {}
    if rules.get("automatic_forward_transition_allowed") is not False:
        errors.append("automatic_forward_transition_must_be_false")
    if rules.get("automatic_production_activation_allowed") is not False:
        errors.append("automatic_production_activation_must_be_false")
    for key, value in (contract.get("forward_thresholds") or {}).items():
        try:
            if _integer(value, key) <= 0:
                errors.append(f"threshold_not_positive:{key}")
        except ValueError:
            errors.append(f"threshold_invalid:{key}")
    return errors


def validate_state(state: dict[str, Any], contract: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if state.get("schema_version") != STATE_SCHEMA:
        errors.append("state_schema_invalid")
    if state.get("promotion_state") not in set(contract.get("states") or []):
        errors.append("promotion_state_invalid")
    champion = state.get("canonical_champion")
    if not isinstance(champion, dict) or not champion.get("policy_id") or not champion.get("account_namespace"):
        errors.append("canonical_champion_invalid")
    if state.get("production_activation_allowed") is not False:
        errors.append("canonical_state_production_activation_not_false")
    if state.get("live_trading_enabled") is not False:
        errors.append("canonical_state_live_trading_not_false")
    if state.get("automatic_transition_allowed") is not False:
        errors.append("canonical_state_automatic_transition_not_false")
    approval = state.get("user_approval")
    if not isinstance(approval, dict) or not isinstance(approval.get("granted"), bool):
        errors.append("user_approval_record_invalid")
    return errors


def validate_account_pair(evidence: dict[str, Any]) -> dict[str, Any]:
    accounts = evidence.get("accounts") or {}
    champion = accounts.get("champion")
    challenger = accounts.get("challenger")
    issues: list[str] = []
    if not isinstance(champion, dict):
        issues.append("champion_account_missing")
    if challenger is None:
        return {
            "status": "NO_OFFICIAL_CHALLENGER",
            "valid": False,
            "paired_decision_date_count": 0,
            "issues": issues or ["official_challenger_missing"],
            "champion": champion,
            "challenger": None,
            "contract_match": {},
        }
    if not isinstance(challenger, dict):
        issues.append("challenger_account_invalid")
        challenger = {}
    if isinstance(champion, dict):
        if champion.get("account_id") == challenger.get("account_id"):
            issues.append("champion_challenger_account_id_collision")
        if champion.get("ledger_root") == challenger.get("ledger_root"):
            issues.append("champion_challenger_ledger_root_collision")
    contract_match: dict[str, bool] = {}
    for field in ACCOUNT_CONTRACT_FIELDS:
        left = champion.get(field) if isinstance(champion, dict) else None
        right = challenger.get(field)
        contract_match[field] = bool(left) and left == right
        if not contract_match[field]:
            issues.append(f"paired_contract_mismatch:{field}")
    paired = _integer(accounts.get("paired_decision_date_count", 0), "paired_decision_date_count")
    if paired <= 0:
        issues.append("paired_decision_dates_missing")
    return {
        "status": "PAIRED_COMPARISON_READY" if not issues else "PAIRED_COMPARISON_BLOCKED",
        "valid": not issues,
        "paired_decision_date_count": paired,
        "issues": sorted(set(issues)),
        "champion": champion,
        "challenger": challenger,
        "contract_match": contract_match,
    }


def _csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def overlay_latest_run_evidence(base: dict[str, Any], latest_run: Path) -> dict[str, Any]:
    """Overlay only directly verifiable forward observations from a restored run.

    Missing runtime fields never manufacture a pass.  The tracked preregistered
    packet supplies fixed thresholds and unresolved defaults; this overlay can
    add observations or trigger rollback, but cannot modify historical gates.
    """
    evidence = copy.deepcopy(base)
    paper_root = latest_run / "daily_simulated_fill_ledger"
    if not paper_root.is_dir():
        return evidence
    forward = evidence.setdefault("forward_paper", {})
    observed_files: dict[str, str] = {}
    session_sets: list[set[str]] = []
    negative_cash = 0
    duplicate_ids = 0
    duplicate_fills = 0
    same_day_fills = 0
    reseeds = 0
    manifest_counts = {
        field: 0 for field in (
            "account_reseed_count",
            "duplicate_fill_count",
            "duplicate_client_order_id_count",
            "same_day_fill_count",
            "future_close_count",
            "stale_substituted_close_count",
            "hash_chain_break_count",
            "negative_cash_count",
            "lifecycle_silent_deletion_count",
        )
    }
    for portfolio in ("main", "concentrated"):
        equity_path = paper_root / portfolio / "equity_curve.csv"
        fill_path = paper_root / portfolio / "fills.csv"
        manifest_path = paper_root / portfolio / "manifest.json"
        rows = _csv_rows(equity_path)
        dates = {str(row.get("date") or "") for row in rows if row.get("date")}
        session_sets.append(dates)
        negative_cash += sum(float(row.get("cash_usd") or 0) < -1e-8 for row in rows)
        fills = _csv_rows(fill_path)
        ids = [str(row.get("client_order_id") or "") for row in fills if row.get("client_order_id")]
        duplicate_ids += max(0, len(ids) - len(set(ids)))
        fill_keys = [json.dumps(row, sort_keys=True, separators=(",", ":")) for row in fills]
        duplicate_fills += max(0, len(fill_keys) - len(set(fill_keys)))
        same_day_fills += sum(
            bool(row.get("signal_date")) and row.get("signal_date") == row.get("date") for row in fills
        )
        if manifest_path.is_file():
            manifest = read_json(manifest_path)
            if manifest.get("result_status") == "GENESIS" and len(dates) > 1:
                reseeds += 1
            integrity = manifest.get("integrity") or {}
            for field in manifest_counts:
                if field in integrity or field in manifest:
                    manifest_counts[field] += _integer(
                        integrity.get(field, manifest.get(field, 0)), field
                    )
        for path in (equity_path, fill_path, manifest_path):
            if path.is_file():
                observed_files[path.relative_to(latest_run).as_posix()] = sha256_file(path)
    common_sessions = set.intersection(*session_sets) if session_sets else set()
    forward["completed_market_sessions"] = len(common_sessions)
    weeks = set()
    for value in common_sessions:
        try:
            parsed = date.fromisoformat(value)
        except ValueError:
            continue
        iso = parsed.isocalendar()
        weeks.add(f"{iso.year:04d}-W{iso.week:02d}")
    forward["distinct_decision_weeks"] = len(weeks)
    observed_counts = {
        "negative_cash_count": negative_cash,
        "duplicate_client_order_id_count": duplicate_ids,
        "duplicate_fill_count": duplicate_fills,
        "same_day_fill_count": same_day_fills,
        "account_reseed_count": reseeds,
    }
    summary_path = paper_root / "summary.json"
    summary = read_json(summary_path) if summary_path.is_file() else {}
    if summary_path.is_file():
        observed_files[summary_path.relative_to(latest_run).as_posix()] = sha256_file(summary_path)
    summary_integrity = summary.get("integrity") or {}
    for field in manifest_counts:
        if field in summary_integrity or field in summary:
            observed_counts[field] = _integer(
                summary_integrity.get(field, summary.get(field, 0)), field
            )
        elif manifest_counts[field] > 0:
            observed_counts[field] = manifest_counts[field]
    forward.update(observed_counts)

    integrity_path = paper_root / "snapshot_integrity.json"
    if integrity_path.is_file():
        observed_files[integrity_path.relative_to(latest_run).as_posix()] = sha256_file(integrity_path)
        try:
            try:
                from tools.run287_paper_ledger_integrity import verify_integrity_manifest
            except ModuleNotFoundError:
                from run287_paper_ledger_integrity import verify_integrity_manifest
            verify_integrity_manifest(paper_root, require=True)
            forward["hash_chain_break_count"] = 0
        except Exception as exc:
            evidence.setdefault("rollback", {})["integrity_error"] = True
            evidence.setdefault("runtime_limitations", []).append(f"paper_snapshot_integrity_failed:{exc}")
    elif evidence.get("candidate_id"):
        evidence.setdefault("rollback", {})["integrity_error"] = True
        evidence.setdefault("runtime_limitations", []).append("paper_snapshot_integrity_missing_for_challenger")

    outcome_path = latest_run / "run287_risk_outcome_archive" / "summary.json"
    if outcome_path.is_file():
        observed_files[outcome_path.relative_to(latest_run).as_posix()] = sha256_file(outcome_path)
        outcome = read_json(outcome_path)
        forward["distinct_decision_weeks"] = max(
            _integer(forward.get("distinct_decision_weeks", 0), "distinct_decision_weeks"),
            _integer(outcome.get("distinct_decision_week_count", 0), "distinct_decision_week_count"),
        )
        mechanism = outcome.get("mechanism_review_gate") or {}
        resolved_63d = sum(
            _integer(mechanism.get(field, 0), field)
            for field in ("normal_63d_count", "warning_63d_count")
        )
        forward["resolved_63d_outcomes"] = max(
            _integer(forward.get("resolved_63d_outcomes", 0), "resolved_63d_outcomes"),
            resolved_63d,
        )
    evidence["latest_run_observation"] = {
        "latest_run": str(latest_run),
        "observed_file_hashes": observed_files,
        "completed_market_sessions": len(common_sessions),
        "distinct_decision_weeks": len(weeks),
    }
    return evidence


def _transition_request(
    current: str,
    maximum: str,
    requested: str | None,
    contract: dict[str, Any],
    approval: dict[str, Any] | None,
    evidence_sha256: str,
) -> dict[str, Any]:
    if not requested:
        return {
            "requested_state": None,
            "status": "NO_TRANSITION_REQUESTED",
            "canonical_state_changed": False,
        }
    states = list(contract["states"])
    forward = states[:-1]
    problems: list[str] = []
    if requested not in forward:
        problems.append("requested_state_invalid_or_rollback_only")
    elif current not in forward:
        problems.append("current_state_not_forward_transitionable")
    else:
        if forward.index(requested) != forward.index(current) + 1:
            problems.append("only_adjacent_forward_transition_allowed")
        if forward.index(requested) > forward.index(maximum):
            problems.append("evidence_gate_not_met")
    if not isinstance(approval, dict) or approval.get("approved") is not True:
        problems.append("explicit_transition_authorization_missing")
    else:
        for field in ("approved_by", "approved_at_utc", "approved_scope", "evidence_sha256"):
            if not approval.get(field):
                problems.append(f"transition_authorization_missing:{field}")
        if approval.get("requested_state") != requested:
            problems.append("transition_authorization_state_mismatch")
        if approval.get("evidence_sha256") != evidence_sha256:
            problems.append("transition_authorization_evidence_hash_mismatch")
    return {
        "requested_state": requested,
        "status": "REVIEWED_STATE_CHANGE_PR_REQUIRED" if not problems else "TRANSITION_REQUEST_BLOCKED",
        "canonical_state_changed": False,
        "problems": sorted(set(problems)),
        "note": "This tool never mutates the canonical state; an independently reviewed state-pointer change is required.",
    }


def evaluate_gate(
    contract: dict[str, Any],
    state: dict[str, Any],
    evidence: dict[str, Any],
    *,
    source_hashes: dict[str, str] | None = None,
    requested_state: str | None = None,
    transition_authorization: dict[str, Any] | None = None,
) -> dict[str, Any]:
    contract_errors = validate_contract(contract)
    state_errors = validate_state(state, contract) if not contract_errors else ["state_not_evaluated"]
    historical = evidence.get("historical") or {}
    historical_checks = {
        field: historical.get(field) is True
        for field in contract.get("required_historical_checks") or []
    }
    historical_blockers = sorted(field for field, passed in historical_checks.items() if not passed)
    historical_pass = bool(historical_checks) and not historical_blockers

    account_pair = validate_account_pair(evidence)
    account_integrity_issues = [
        issue for issue in account_pair["issues"]
        if "collision" in issue or "mismatch" in issue
    ]

    forward = evidence.get("forward_paper") or {}
    thresholds = contract.get("forward_thresholds") or {}
    zero_checks: dict[str, bool] = {}
    for field in contract.get("required_zero_integrity_fields") or []:
        zero_checks[field] = _integer(forward.get(field, 0), field) == 0
    sample_checks = {
        "completed_market_sessions": _integer(forward.get("completed_market_sessions", 0), "completed_market_sessions")
        >= _integer(thresholds.get("minimum_completed_market_sessions"), "minimum_completed_market_sessions"),
        "distinct_decision_weeks": _integer(forward.get("distinct_decision_weeks", 0), "distinct_decision_weeks")
        >= _integer(thresholds.get("minimum_distinct_decision_weeks"), "minimum_distinct_decision_weeks"),
        "resolved_21d_outcomes": _integer(forward.get("resolved_21d_outcomes", 0), "resolved_21d_outcomes")
        >= _integer(thresholds.get("minimum_resolved_21d_outcomes"), "minimum_resolved_21d_outcomes"),
        "resolved_63d_outcomes": _integer(forward.get("resolved_63d_outcomes", 0), "resolved_63d_outcomes")
        >= _integer(thresholds.get("minimum_resolved_63d_outcomes"), "minimum_resolved_63d_outcomes"),
        "resolved_126d_outcomes": _integer(forward.get("resolved_126d_outcomes", 0), "resolved_126d_outcomes")
        >= _integer(thresholds.get("minimum_resolved_126d_outcomes"), "minimum_resolved_126d_outcomes"),
    }
    evaluability = {
        field: forward.get(field) is True
        for field in ("selection_evaluable", "exit_evaluable", "defense_evaluable", "reentry_evaluable")
    }
    forward_blockers = sorted(
        [f"integrity:{key}" for key, passed in zero_checks.items() if not passed]
        + [f"sample:{key}" for key, passed in sample_checks.items() if not passed]
        + [f"evaluation:{key}" for key, passed in evaluability.items() if not passed]
    )
    forward_ready = not forward_blockers and account_pair["valid"]
    outcome_63d_status = "AVAILABLE" if sample_checks["resolved_63d_outcomes"] else "UNDERPOWERED"

    if historical_pass:
        if account_pair["valid"]:
            maximum = "FORWARD_PAPER_REVIEW_READY" if forward_ready else "FORWARD_PAPER_VALIDATING"
        else:
            maximum = "SHADOW_OPERATION_READY"
    else:
        maximum = "RESEARCH_ONLY"

    rollback = evidence.get("rollback") or {}
    active_rollbacks = sorted(
        field for field in contract.get("rollback_triggers") or [] if rollback.get(field) is True
    )
    active_rollbacks.extend(
        f"forward_integrity:{field}" for field, passed in zero_checks.items() if not passed
    )
    active_rollbacks.extend(f"account_integrity:{item}" for item in account_integrity_issues)
    if contract_errors:
        active_rollbacks.extend(f"contract:{item}" for item in contract_errors)
    if state_errors:
        active_rollbacks.extend(f"state:{item}" for item in state_errors)
    current = str(state.get("promotion_state") or "RESEARCH_ONLY")
    if current not in {"RESEARCH_ONLY", "BLOCKED_OR_ROLLED_BACK"} and not historical_pass:
        active_rollbacks.append("advanced_state_historical_gate_regression")
    active_rollbacks = sorted(set(active_rollbacks))
    effective = "BLOCKED_OR_ROLLED_BACK" if active_rollbacks else current

    hashes = source_hashes or {}
    transition = _transition_request(
        current,
        maximum,
        requested_state,
        contract,
        transition_authorization,
        hashes.get("evidence_sha256", ""),
    )
    state_unchanged = effective == current
    limitations = list(historical.get("limitations") or [])
    limitations.extend(
        ["63-session outcome evidence is UNDERPOWERED until the fixed minimum is actually resolved."]
        if outcome_63d_status == "UNDERPOWERED" else []
    )
    return {
        "schema_version": GATE_SCHEMA,
        "contract_version": contract.get("contract_version"),
        "source_hashes": hashes,
        "canonical_promotion_state": current,
        "effective_promotion_state": effective,
        "maximum_evidence_supported_state": maximum,
        "canonical_state_unchanged": state_unchanged,
        "automatic_forward_transition_performed": False,
        "automatic_production_activation_performed": False,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
        "user_approval": state.get("user_approval"),
        "historical_gate": {
            "status": "PASS" if historical_pass else "BLOCKED",
            "passed": historical_pass,
            "checks": historical_checks,
            "blockers": historical_blockers,
        },
        "champion_challenger": account_pair,
        "forward_paper_gate": {
            "status": "REVIEW_READY" if forward_ready else "UNDERPOWERED",
            "review_ready": forward_ready,
            "thresholds": thresholds,
            "actuals": {
                "completed_market_sessions": _integer(forward.get("completed_market_sessions", 0), "completed_market_sessions"),
                "distinct_decision_weeks": _integer(forward.get("distinct_decision_weeks", 0), "distinct_decision_weeks"),
                "resolved_21d_outcomes": _integer(forward.get("resolved_21d_outcomes", 0), "resolved_21d_outcomes"),
                "resolved_63d_outcomes": _integer(forward.get("resolved_63d_outcomes", 0), "resolved_63d_outcomes"),
                "resolved_126d_outcomes": _integer(forward.get("resolved_126d_outcomes", 0), "resolved_126d_outcomes"),
            },
            "zero_integrity_checks": zero_checks,
            "sample_checks": sample_checks,
            "evaluability_checks": evaluability,
            "resolved_63d_status": outcome_63d_status,
            "blockers": forward_blockers,
        },
        "rollback": {
            "triggered": bool(active_rollbacks),
            "triggers": active_rollbacks,
            "canonical_champion_preserved": True,
            "paper_history_preserved": True,
            "policy_pointer_action": "RESTORE_CANONICAL_CHAMPION" if active_rollbacks else "NO_CHANGE",
            "code_rollback_performed": False,
            "code_rollback_review_required": bool(active_rollbacks),
        },
        "transition_request": transition,
        "unresolved_data_limitations": sorted(set(str(value) for value in limitations if value)),
        "fullrun_executed": False,
    }


def gate_for_consumer(source_root: Path | None = None, explicit: Path | None = None) -> dict[str, Any]:
    candidates: list[Path] = []
    if explicit is not None:
        candidates.append(explicit)
    if source_root is not None:
        candidates.extend(
            [
                source_root / "run287_promotion_gate" / "promotion_gate.json",
                source_root / "outputs" / "run287_promotion_gate" / "promotion_gate.json",
            ]
        )
    candidates.append(DEFAULT_STATE)
    for path in candidates:
        if not path.is_file():
            continue
        payload = read_json(path)
        if payload.get("schema_version") == GATE_SCHEMA:
            state = payload.get("effective_promotion_state")
            if state:
                return {
                    "promotion_state": state,
                    "canonical_promotion_state": payload.get("canonical_promotion_state"),
                    "source_path": str(path),
                    "source_sha256": sha256_file(path),
                    "production_activation_allowed": False,
                    "live_trading_enabled": False,
                    "rollback_triggered": bool((payload.get("rollback") or {}).get("triggered")),
                }
        if payload.get("schema_version") == STATE_SCHEMA:
            return {
                "promotion_state": payload.get("promotion_state"),
                "canonical_promotion_state": payload.get("promotion_state"),
                "source_path": str(path),
                "source_sha256": sha256_file(path),
                "production_activation_allowed": False,
                "live_trading_enabled": False,
                "rollback_triggered": payload.get("promotion_state") == "BLOCKED_OR_ROLLED_BACK",
            }
    raise FileNotFoundError("canonical Run287 promotion state is unavailable")
