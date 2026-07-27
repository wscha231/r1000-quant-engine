#!/usr/bin/env python3
"""Canonical Run287 promotion and rollback governance primitives."""
from __future__ import annotations

import hashlib
import json
import math
import csv
import copy
import tempfile
from collections import Counter
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
PORTFOLIOS = ("main", "concentrated")
RISK_OUTCOME_SCHEMA = "run287-risk-outcome-archive-v1"
RISK_OUTCOME_READY_STATUS = "READY_RISK_OUTCOME_ARCHIVE_REVIEW_ONLY"
RISK_OUTCOME_PARENT_ANCHOR_SCHEMA = "run287-risk-outcome-parent-anchor-v1"
RISK_OUTCOME_CHAIN_SCHEMA = "run287-risk-outcome-chain-v1"
RISK_OUTCOME_PARENT_STATUSES = frozenset(
    {"GENESIS_EMPTY", "VERIFIED_EMPTY_PARENT", "VERIFIED_PARENT"}
)
RISK_OUTCOME_PARENT_ACCEPTANCE_STATUSES = frozenset(
    {"NO_PRIOR_STATE", "VERIFIED_ACCEPTED_HEAD", "QUARANTINED_LEGACY"}
)
RISK_OUTCOME_ACCEPTED_MANIFEST_SCHEMA = (
    "run287-accepted-publication-manifest-v1"
)
RISK_OUTCOME_ACCEPTED_MANIFEST_READY_STATUS = (
    "READY_ACCEPTED_PUBLICATION_REVIEW_ONLY"
)
RISK_OUTCOME_CONTRACT = ROOT / "docs" / "run287_risk_outcome_archive_contract.json"
DECISION_ARCHIVE_CONTRACT = (
    ROOT / "docs" / "run287_decision_observation_archive_contract.json"
)
DECISION_ARCHIVE_CONTRACT_SHA256 = (
    "7cb0bd4a86493ae861f32338f13ff17fbf3997fc23657381d79005b750cfbdc2"
)
RISK_OUTCOME_CONTRACT_SHA256 = (
    "cc15a0a79968723ad0bdeef34a56b2c47e547dc8e9d469dfe9d3cfbc53986103"
)
SCORECARD_SCHEMA = "run287-operating-scorecard-v1"
SCORECARD_TRUST_BASIS = "runtime-source-sha256-and-paper-directory-manifest-v1"
SCORECARD_SOURCE_REGISTRY = ROOT / "docs" / "run287_operating_scorecard_sources.json"
SCORECARD_SOURCE_REGISTRY_SHA256 = (
    "07b76f7980904ad7c3609176ff35369708bd636f5ce70d0776bd50e389da1801"
)
MULTIPLE_TESTING_GATE_SCHEMA = "run287-multiple-testing-gate-v1"
MULTIPLE_TESTING_SOURCE_MANIFEST_SCHEMA = (
    "run287-multiple-testing-source-manifest-v1"
)
MULTIPLE_TESTING_CONTRACT_VERSION = "2026-07-27.2"
MULTIPLE_TESTING_REQUIRED_CHECKS = (
    "contract_valid",
    "complete_experiment_ledger",
    "canonical_champion_binding",
    "one_active_causal_challenger",
    "complete_cross_family_multiplicity_population",
    "git_anchored_preregistration",
    "evaluation_snapshot_binding",
    "canonical_registry_history",
    "minimum_trials",
    "synchronized_return_matrix",
    "minimum_synchronous_observations",
    "selected_trial_reproducible",
    "deflated_sharpe",
    "probability_of_backtest_overfitting",
    "white_reality_check",
    "inputs_immutable_during_evaluation",
)
MULTIPLE_TESTING_THRESHOLDS = {
    "minimum_trials": 5,
    "minimum_synchronous_observations": 504,
    "cscv_contiguous_blocks": 8,
    "deflated_sharpe_probability_minimum": 0.95,
    "probability_of_backtest_overfitting_maximum": 0.20,
    "white_reality_check_p_value_maximum": 0.10,
    "bootstrap_repetitions": 2000,
    "bootstrap_block_lengths": [5, 21, 63],
    "bootstrap_random_seed": 28720260727,
    "annualization_sessions": 252,
}
MULTIPLE_TESTING_MINIMUM_PRIOR_PERFORMANCE_TRIALS = 1
MULTIPLE_TESTING_SAFETY = {
    "research_only": True,
    "automatic_promotion_allowed": False,
    "champion_change_allowed": False,
    "portfolio_mutation_allowed": False,
    "target_books_mutated": False,
    "operating_ledger_mutated": False,
    "orders_generated": False,
    "fullrun_executed_by_gate": False,
    "production_activation_allowed": False,
    "live_trading_enabled": False,
}
RUNTIME_COUNT_FIELDS = (
    "completed_market_sessions",
    "distinct_decision_weeks",
    "resolved_21d_outcomes",
    "resolved_63d_outcomes",
    "resolved_126d_outcomes",
)
RUNTIME_EVALUABILITY_FIELDS = (
    "selection_evaluable",
    "exit_evaluable",
    "defense_evaluable",
    "reentry_evaluable",
)
RUNTIME_INTEGRITY_FIELDS = (
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
RUNTIME_DIRECT_INTEGRITY_FIELDS = (
    "account_reseed_count",
    "duplicate_fill_count",
    "duplicate_client_order_id_count",
    "same_day_fill_count",
    "negative_cash_count",
)
CANONICAL_STATES = (
    "RESEARCH_ONLY",
    "SHADOW_OPERATION_READY",
    "FORWARD_PAPER_VALIDATING",
    "FORWARD_PAPER_REVIEW_READY",
    "PRODUCTION_CANDIDATE_USER_APPROVAL_REQUIRED",
    "BLOCKED_OR_ROLLED_BACK",
)
CANONICAL_FORWARD_THRESHOLDS = {
    "minimum_completed_market_sessions": 60,
    "minimum_distinct_decision_weeks": 12,
    "minimum_resolved_21d_outcomes": 200,
    "minimum_resolved_63d_outcomes": 100,
    "minimum_resolved_126d_outcomes": 50,
}
CANONICAL_HISTORICAL_CHECKS = (
    "canonical_control_exact_parity",
    "pit_no_lookahead",
    "full_pass",
    "oos_pass",
    "oos2_pass",
    "embargo_126_pass",
    "cost_25bps_pass",
    "cost_50bps_pass",
    "cost_100bps_pass",
    "stress_episodes_pass",
    "ticker_sector_era_concentration_pass",
    "multiple_testing_pass",
    "scorecard_trusted",
    "lifecycle_delisted_handling_pass",
    "do_not_repeat_conflict_absent",
)
CANONICAL_ROLLBACK_TRIGGERS = (
    "integrity_error",
    "target_order_provenance_unknown",
    "oos_or_forward_structural_degradation",
    "stress_mdd_degradation",
    "reentry_cash_trap_limit_breach",
    "turnover_fees_consume_expected_alpha",
    "data_coverage_semantic_change",
    "model_head_zero_constant_or_drift_failure",
    "lifecycle_handling_failure",
)
CANONICAL_RULES = {
    "automatic_forward_transition_allowed": False,
    "automatic_production_activation_allowed": False,
    "automatic_safe_rollback_allowed": True,
    "one_official_challenger_at_a_time": True,
    "champion_and_challenger_ledgers_must_be_distinct": True,
    "paired_decision_dates_required": True,
    "lower_signal_frequency_extends_observation_period": True,
    "lower_signal_frequency_lowers_thresholds": False,
    "forward_overwrites_historical_acceptance": False,
    "paper_history_preserved_on_rollback": True,
}
RISK_OUTCOME_HORIZONS = (1, 5, 21, 63, 126)
PROMOTION_OUTCOME_HORIZONS = (21, 63, 126)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha256(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def strict_json_object(
    payload: str | bytes,
    *,
    label: str,
) -> dict[str, Any]:
    def object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"{label}:duplicate_json_key:{key}")
            result[key] = value
        return result

    try:
        decoded = json.loads(payload, object_pairs_hook=object_pairs)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label}:invalid_json") from exc
    if not isinstance(decoded, dict):
        raise ValueError(f"JSON object required: {label}")
    return decoded


def read_json(path: Path) -> dict[str, Any]:
    return strict_json_object(
        path.read_text(encoding="utf-8"),
        label=str(path),
    )


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
    if contract.get("contract_version") != "2026-07-27.1":
        errors.append("contract_version_invalid")
    states = contract.get("states")
    if states != list(CANONICAL_STATES):
        errors.append("contract_states_not_canonical")
    if contract.get("forward_thresholds") != CANONICAL_FORWARD_THRESHOLDS:
        errors.append("contract_forward_thresholds_not_canonical")
    if contract.get("required_zero_integrity_fields") != list(
        RUNTIME_INTEGRITY_FIELDS
    ):
        errors.append("contract_zero_integrity_fields_not_canonical")
    if contract.get("required_historical_checks") != list(
        CANONICAL_HISTORICAL_CHECKS
    ):
        errors.append("contract_historical_checks_not_canonical")
    if contract.get("rollback_triggers") != list(CANONICAL_ROLLBACK_TRIGGERS):
        errors.append("contract_rollback_triggers_not_canonical")
    rules = contract.get("rules") or {}
    if rules != CANONICAL_RULES:
        errors.append("contract_rules_not_canonical")
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
    runtime_pair_verified = accounts.get("runtime_pair_verified") is True
    issues: list[str] = []
    if not isinstance(champion, dict):
        issues.append("champion_account_missing")
    if challenger is None:
        return {
            "status": "NO_OFFICIAL_CHALLENGER",
            "valid": False,
            "paired_decision_date_count": 0,
            "runtime_pair_verified": runtime_pair_verified,
            "issues": issues or ["official_challenger_missing"],
            "champion": champion,
            "challenger": None,
            "contract_match": {},
        }
    if not isinstance(challenger, dict):
        issues.append("challenger_account_invalid")
        challenger = {}
    if not runtime_pair_verified:
        issues.append("runtime_champion_challenger_pair_unverified")
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
        "runtime_pair_verified": runtime_pair_verified,
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


def _jsonl_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, raw in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not raw.strip():
            continue
        payload = strict_json_object(
            raw,
            label=f"{path}:{line_number}",
        )
        rows.append(payload)
    return rows


def _valid_sha256(value: Any) -> bool:
    text = str(value or "")
    return len(text) == 64 and all(char in "0123456789abcdef" for char in text.lower())


def _valid_commit_sha(value: Any) -> bool:
    text = str(value or "")
    return len(text) == 40 and all(
        char in "0123456789abcdef" for char in text.lower()
    )


def _verify_attested_file(
    *,
    path: Path,
    expected_sha256: Any,
    latest_run: Path,
    observed_files: dict[str, str],
    label: str,
) -> None:
    if not path.is_file():
        raise ValueError(f"{label}_missing")
    expected = str(expected_sha256 or "")
    if not _valid_sha256(expected):
        raise ValueError(f"{label}_sha256_invalid")
    actual = sha256_file(path)
    if actual != expected:
        raise ValueError(f"{label}_sha256_mismatch")
    try:
        key = path.relative_to(latest_run).as_posix()
    except ValueError:
        key = f"repo:{path.relative_to(ROOT).as_posix()}"
    observed_files[key] = actual


def _require_false_flags(
    payload: dict[str, Any], fields: tuple[str, ...], label: str
) -> None:
    for field in fields:
        if payload.get(field) is not False:
            raise ValueError(f"{label}_unsafe_flag:{field}")


def _canonical_json_bytes_with_newline(payload: Any) -> bytes:
    return (
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _finite_float(value: Any, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label}_not_numeric") from exc
    if not math.isfinite(result):
        raise ValueError(f"{label}_not_finite")
    return result


def _verify_fingerprint_record(
    *,
    record: Any,
    path: Path,
    label: str,
    latest_run: Path,
    observed_files: dict[str, str],
) -> None:
    if not isinstance(record, dict):
        raise ValueError(f"{label}_fingerprint_missing")
    raw_path = str(record.get("path") or "")
    if not raw_path or Path(raw_path).name != path.name:
        raise ValueError(f"{label}_fingerprint_path_mismatch")
    if record.get("exists") is not True:
        raise ValueError(f"{label}_fingerprint_exists_not_true")
    if not path.is_file():
        raise ValueError(f"{label}_missing")
    if _integer(record.get("bytes"), f"{label}.bytes") != path.stat().st_size:
        raise ValueError(f"{label}_fingerprint_bytes_mismatch")
    _verify_attested_file(
        path=path,
        expected_sha256=record.get("sha256"),
        latest_run=latest_run,
        observed_files=observed_files,
        label=label,
    )


def _validate_decision_archive(
    *,
    archive: Path,
    manifest: dict[str, Any],
    paper_date: date,
    latest_run: Path,
    observed_files: dict[str, str],
) -> tuple[list[dict[str, Any]], tuple[Path, ...]]:
    if (
        manifest.get("schema_version")
        != "run287-decision-observation-archive-v1"
        or manifest.get("status")
        != "READY_DECISION_OBSERVATION_ARCHIVE_REVIEW_ONLY"
        or manifest.get("archive_passed") is not True
        or manifest.get("contract_failures") != []
        or manifest.get("review_only") is not True
        or manifest.get("source_inputs_mutated") is not False
        or manifest.get("archive_may_promote") is not False
    ):
        raise ValueError("runtime_risk_outcome_decision_archive_not_ready")
    _require_false_flags(
        manifest,
        (
            "orders_generated",
            "target_books_mutated",
            "selector_weights_changed",
            "cash_policy_changed",
            "backtest_executed",
            "fullrun_executed",
            "production_activation_allowed",
            "live_trading_enabled",
        ),
        "runtime_risk_outcome_decision_archive",
    )
    interpretation = manifest.get("interpretation") or {}
    if (
        interpretation.get("portfolio_transition_allowed") is not False
        or interpretation.get("historical_cagr_mdd_evidence_changed") is not False
    ):
        raise ValueError("runtime_risk_outcome_decision_archive_interpretation_unsafe")

    paths = {
        "decision": archive / "decision_history.jsonl",
        "scenario": archive / "scenario_history.jsonl",
        "position": archive / "position_history.jsonl",
        "candidate_risk": archive / "candidate_risk_history.jsonl",
    }
    rows = {kind: _jsonl_rows(path) for kind, path in paths.items()}
    outputs = manifest.get("outputs") or {}
    history_counts = manifest.get("history_counts") or {}
    for kind, path in paths.items():
        _verify_fingerprint_record(
            record=outputs.get(f"{kind}_history"),
            path=path,
            label=f"risk_outcome_decision_archive_{kind}_history",
            latest_run=latest_run,
            observed_files=observed_files,
        )
        if _integer(
            history_counts.get(kind), f"decision_archive.history_counts.{kind}"
        ) != len(rows[kind]):
            raise ValueError(
                f"runtime_risk_outcome_decision_archive_history_count_mismatch:{kind}"
            )
    if not rows["decision"]:
        raise ValueError("runtime_risk_outcome_decision_archive_empty")

    try:
        import pandas_market_calendars as mcal
        try:
            from tools.archive_run287_decision_observation import (
                canonical_hash as archive_canonical_hash,
                canonical_tracked_contract_sha256,
                event_id as archive_event_id,
            )
            from tools.resolve_run287_risk_outcomes import build_observations
        except ModuleNotFoundError:
            from archive_run287_decision_observation import (
                canonical_hash as archive_canonical_hash,
                canonical_tracked_contract_sha256,
                event_id as archive_event_id,
            )
            from resolve_run287_risk_outcomes import build_observations
    except ImportError as exc:
        raise ValueError("runtime_risk_outcome_archive_validator_unavailable") from exc

    contract_payload = read_json(DECISION_ARCHIVE_CONTRACT)
    source_contract = (manifest.get("source_inputs") or {}).get(
        "archive_contract"
    ) or {}
    contract_sha256 = canonical_tracked_contract_sha256(
        DECISION_ARCHIVE_CONTRACT,
        contract_payload,
        DECISION_ARCHIVE_CONTRACT_SHA256,
    )
    if (
        contract_sha256 != DECISION_ARCHIVE_CONTRACT_SHA256
        or str(source_contract.get("sha256") or "")
        != DECISION_ARCHIVE_CONTRACT_SHA256
    ):
        raise ValueError("runtime_risk_outcome_decision_archive_contract_mismatch")

    all_event_ids: list[str] = []
    all_dates: list[date] = []
    for kind, history in rows.items():
        expected_record_kind = {
            "decision": "decision_close",
            "scenario": "selector_scenario",
            "position": "selector_position",
            "candidate_risk": "candidate_risk",
        }[kind]
        for row in history:
            if (
                row.get("schema_version")
                != "run287-decision-observation-archive-v1"
                or row.get("record_kind") != expected_record_kind
                or row.get("review_only") is not True
                or row.get("archive_contract_sha256") != contract_sha256
            ):
                raise ValueError(
                    f"runtime_risk_outcome_decision_archive_row_invalid:{kind}"
                )
            _require_false_flags(
                row,
                (
                    "portfolio_transition_allowed",
                    "orders_generated",
                    "target_books_mutated",
                    "historical_cagr_mdd_evidence_changed",
                    "production_activation_allowed",
                    "live_trading_enabled",
                ),
                f"runtime_risk_outcome_decision_archive_row:{kind}",
            )
            row_date = date.fromisoformat(str(row.get("as_of_date") or ""))
            if row_date > paper_date:
                raise ValueError(
                    "runtime_risk_outcome_decision_archive_from_future"
                )
            iso = row_date.isocalendar()
            if str(row.get("iso_decision_week") or "") != (
                f"{iso.year:04d}-W{iso.week:02d}"
            ):
                raise ValueError(
                    f"runtime_risk_outcome_decision_archive_week_mismatch:{kind}"
                )
            all_dates.append(row_date)
            event = str(row.get("event_id") or "")
            if not _valid_sha256(event):
                raise ValueError(
                    f"runtime_risk_outcome_decision_archive_event_id_invalid:{kind}"
                )
            all_event_ids.append(event)
    if len(all_event_ids) != len(set(all_event_ids)):
        raise ValueError("runtime_risk_outcome_decision_archive_event_id_duplicate")

    decision_dates = sorted(
        {str(row.get("as_of_date") or "") for row in rows["decision"]}
    )
    if any(
        str(row.get("as_of_date") or "") not in set(decision_dates)
        for kind in ("scenario", "position", "candidate_risk")
        for row in rows[kind]
    ):
        raise ValueError(
            "runtime_risk_outcome_decision_archive_orphan_child_date"
        )
    decision_weeks = sorted(
        {
            f"{date.fromisoformat(value).isocalendar().year:04d}-W"
            f"{date.fromisoformat(value).isocalendar().week:02d}"
            for value in decision_dates
        }
    )
    manifest_dates = manifest.get("decision_dates")
    manifest_weeks = manifest.get("decision_weeks")
    if (
        manifest_dates != decision_dates
        or manifest_weeks != decision_weeks
        or _integer(
            manifest.get("distinct_decision_date_count"),
            "decision_archive.distinct_decision_date_count",
        )
        != len(decision_dates)
        or _integer(
            manifest.get("distinct_decision_week_count"),
            "decision_archive.distinct_decision_week_count",
        )
        != len(decision_weeks)
        or str(manifest.get("latest_as_of_date") or "")
        != decision_dates[-1]
    ):
        raise ValueError("runtime_risk_outcome_decision_archive_index_mismatch")
    children_by_date = {
        kind: {
            value: [
                row
                for row in rows[kind]
                if str(row.get("as_of_date") or "") == value
            ]
            for value in decision_dates
        }
        for kind in ("scenario", "position", "candidate_risk")
    }
    decisions_by_date: dict[str, list[dict[str, Any]]] = {
        value: [
            row
            for row in rows["decision"]
            if str(row.get("as_of_date") or "") == value
        ]
        for value in decision_dates
    }
    contract_policy_commit = str(
        (contract_payload.get("frozen_identity") or {}).get(
            "pinned_policy_commit"
        )
        or ""
    )
    for kind, history in rows.items():
        for row in history:
            dimensions = {
                "selector_scenario": {
                    "portfolio_kind": row.get("portfolio_kind"),
                    "scenario": row.get("scenario"),
                },
                "selector_position": {
                    "portfolio_kind": row.get("portfolio_kind"),
                    "scenario": row.get("scenario"),
                    "ticker": row.get("ticker"),
                },
                "candidate_risk": {"ticker": row.get("ticker")},
                "decision_close": {},
            }[str(row["record_kind"])]
            if row.get("event_id") != archive_event_id(
                str(row["record_kind"]),
                str(row["as_of_date"]),
                dimensions,
            ):
                raise ValueError(
                    f"runtime_risk_outcome_decision_archive_event_id_mismatch:{kind}"
                )
            if str(row.get("pinned_policy_commit") or "") != contract_policy_commit:
                raise ValueError(
                    f"runtime_risk_outcome_decision_archive_policy_mismatch:{kind}"
                )
    for decision_date in decision_dates:
        decision_rows = decisions_by_date[decision_date]
        if len(decision_rows) != 1:
            raise ValueError(
                "runtime_risk_outcome_decision_archive_decision_cardinality"
            )
        decision_row = decision_rows[0]
        scenario_rows = sorted(
            children_by_date["scenario"][decision_date],
            key=lambda row: (
                str(row.get("portfolio_kind") or ""),
                str(row.get("scenario") or ""),
            ),
        )
        position_rows = sorted(
            children_by_date["position"][decision_date],
            key=lambda row: (
                str(row.get("portfolio_kind") or ""),
                str(row.get("scenario") or ""),
                str(row.get("ticker") or ""),
            ),
        )
        candidate_rows = sorted(
            children_by_date["candidate_risk"][decision_date],
            key=lambda row: str(row.get("ticker") or ""),
        )
        candidate_states = Counter(
            str(row.get("risk_state") or "") for row in candidate_rows
        )
        expected_counts = {
            "scenario_count": len(scenario_rows),
            "position_row_count": len(position_rows),
            "candidate_count": len(candidate_rows),
            "alert_count": candidate_states.get("ALERT", 0),
            "watch_count": candidate_states.get("WATCH", 0),
            "data_insufficient_count": candidate_states.get(
                "DATA_INSUFFICIENT", 0
            ),
            "normal_count": candidate_states.get("NORMAL", 0),
        }
        for field, expected in expected_counts.items():
            if _integer(
                decision_row.get(field),
                f"decision_archive.{decision_date}.{field}",
            ) != expected:
                raise ValueError(
                    f"runtime_risk_outcome_decision_archive_aggregate_mismatch:{field}"
                )
        expected_hashes = {
            "scenario_set_sha256": archive_canonical_hash(
                {"rows": scenario_rows}
            ),
            "position_set_sha256": archive_canonical_hash(
                {"rows": position_rows}
            ),
            "candidate_risk_set_sha256": archive_canonical_hash(
                {"rows": candidate_rows}
            ),
        }
        for field, expected in expected_hashes.items():
            if decision_row.get(field) != expected:
                raise ValueError(
                    f"runtime_risk_outcome_decision_archive_set_hash_mismatch:{field}"
                )
    for row in rows["decision"]:
        expected_event = archive_event_id(
            "decision_close", str(row["as_of_date"]), {}
        )
        if row.get("event_id") != expected_event:
            raise ValueError(
                "runtime_risk_outcome_decision_archive_decision_event_id_mismatch"
            )

    schedule = mcal.get_calendar("NYSE").schedule(
        start_date=min(all_dates), end_date=max(all_dates)
    )
    nyse_dates = {stamp.date() for stamp in schedule.index}
    if any(row_date not in nyse_dates for row_date in all_dates):
        raise ValueError("runtime_risk_outcome_decision_archive_non_nyse_date")

    observations, failures = build_observations(
        rows["candidate_risk"], rows["position"]
    )
    if failures:
        raise ValueError(
            "runtime_risk_outcome_decision_archive_observation_failure:"
            + ",".join(failures)
        )
    if not observations:
        raise ValueError("runtime_risk_outcome_decision_archive_observations_empty")
    return observations, tuple(paths.values())


def _same_scalar(left: Any, right: Any) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        return left is right
    if left is None or right is None:
        return left is right
    if isinstance(left, (int, float)) or isinstance(right, (int, float)):
        try:
            return math.isclose(
                float(left), float(right), rel_tol=1e-10, abs_tol=1e-12
            )
        except (TypeError, ValueError):
            return False
    return left == right


def _require_event_matches(
    actual: dict[str, Any], expected: dict[str, Any], label: str
) -> None:
    if set(actual) != set(expected):
        missing = sorted(set(expected) - set(actual))
        extra = sorted(set(actual) - set(expected))
        raise ValueError(f"{label}_field_set_mismatch:missing={missing}:extra={extra}")
    for field, expected_value in expected.items():
        actual_value = actual.get(field)
        if isinstance(expected_value, (dict, list)):
            if canonical_sha256(actual_value) != canonical_sha256(expected_value):
                raise ValueError(f"{label}_field_mismatch:{field}")
        elif not _same_scalar(actual_value, expected_value):
            raise ValueError(f"{label}_field_mismatch:{field}")


def _validated_risk_outcome_parent_prefix(
    *,
    outcome: dict[str, Any],
    event_log_path: Path,
    anchor_path: Path,
    expected_anchor_sha256: str,
    latest_run: Path,
    observed_files: dict[str, str],
) -> dict[str, int | str]:
    if not anchor_path.is_file():
        raise ValueError("runtime_risk_outcome_parent_anchor_missing")
    anchor_sha256 = sha256_file(anchor_path)
    if (
        not _valid_sha256(expected_anchor_sha256)
        or anchor_sha256 != expected_anchor_sha256
    ):
        raise ValueError("runtime_risk_outcome_parent_anchor_hash_mismatch")
    observed_files[
        anchor_path.relative_to(latest_run).as_posix()
    ] = anchor_sha256
    anchor = read_json(anchor_path)
    status = str(anchor.get("status") or "")
    if (
        anchor.get("schema_version") != RISK_OUTCOME_PARENT_ANCHOR_SCHEMA
        or status not in RISK_OUTCOME_PARENT_STATUSES
        or anchor.get("review_only") is not True
    ):
        raise ValueError("runtime_risk_outcome_parent_anchor_contract_invalid")
    _require_false_flags(
        anchor,
        (
            "mechanism_promotion_allowed",
            "threshold_tuning_allowed",
            "stop_or_exit_rule_created",
            "selector_weights_changed",
            "cash_policy_changed",
            "portfolio_transition_allowed",
            "orders_generated",
            "target_books_mutated",
            "historical_cagr_mdd_evidence_changed",
            "backtest_executed",
            "fullrun_executed",
            "production_activation_allowed",
            "live_trading_enabled",
        ),
        "runtime_risk_outcome_parent_anchor",
    )
    parent_summary_sha256 = str(
        anchor.get("parent_summary_sha256") or ""
    )
    parent_summary_bytes = _integer(
        anchor.get("parent_summary_bytes", 0),
        "risk_outcome.parent_anchor.parent_summary_bytes",
    )
    parent_event_sha256 = str(
        anchor.get("parent_event_log_sha256") or ""
    )
    parent_event_bytes = _integer(
        anchor.get("parent_event_log_bytes", 0),
        "risk_outcome.parent_anchor.parent_event_log_bytes",
    )
    parent_event_count = _integer(
        anchor.get("parent_event_count", 0),
        "risk_outcome.parent_anchor.parent_event_count",
    )
    quarantined_count = _integer(
        anchor.get("carried_quarantined_prefix_event_count", 0),
        "risk_outcome.parent_anchor.carried_quarantined_prefix_event_count",
    )
    parent_as_of_date = str(anchor.get("parent_as_of_date") or "")
    parent_acceptance_status = str(
        anchor.get("parent_acceptance_status") or ""
    )
    parent_accepted_manifest_sha256 = str(
        anchor.get("parent_accepted_manifest_sha256") or ""
    )
    parent_accepted_manifest_bytes = _integer(
        anchor.get("parent_accepted_manifest_bytes", 0),
        "risk_outcome.parent_anchor.parent_accepted_manifest_bytes",
    )
    parent_accepted_manifest_as_of_date = str(
        anchor.get("parent_accepted_manifest_as_of_date") or ""
    )
    if (
        parent_summary_bytes < 0
        or parent_event_bytes < 0
        or parent_event_count < 0
        or quarantined_count < 0
        or parent_accepted_manifest_bytes < 0
        or quarantined_count > parent_event_count
        or not _valid_sha256(parent_event_sha256)
        or (
            parent_acceptance_status
            not in RISK_OUTCOME_PARENT_ACCEPTANCE_STATUSES
        )
        or (
            status == "VERIFIED_PARENT"
            and (
                not _valid_sha256(parent_summary_sha256)
                or parent_summary_bytes <= 0
                or parent_event_bytes <= 0
                or parent_event_count <= 0
                or not parent_as_of_date
            )
        )
        or (
            status == "VERIFIED_EMPTY_PARENT"
            and (
                not _valid_sha256(parent_summary_sha256)
                or parent_summary_bytes <= 0
                or parent_event_bytes != 0
                or parent_event_count != 0
                or parent_event_sha256 != hashlib.sha256(b"").hexdigest()
                or not parent_as_of_date
            )
        )
    ):
        raise ValueError("runtime_risk_outcome_parent_anchor_fields_invalid")
    accepted_manifest_empty = (
        not parent_accepted_manifest_sha256
        and parent_accepted_manifest_bytes == 0
        and not parent_accepted_manifest_as_of_date
    )
    if status == "GENESIS_EMPTY":
        if (
            parent_summary_sha256
            or parent_summary_bytes
            or parent_event_bytes
            or parent_event_count
            or parent_as_of_date
            or parent_event_sha256 != hashlib.sha256(b"").hexdigest()
            or quarantined_count
            or parent_acceptance_status != "NO_PRIOR_STATE"
            or not accepted_manifest_empty
        ):
            raise ValueError(
                "runtime_risk_outcome_parent_anchor_genesis_invalid"
            )
    elif parent_acceptance_status == "QUARANTINED_LEGACY":
        if (
            not accepted_manifest_empty
            or quarantined_count != parent_event_count
        ):
            raise ValueError(
                "runtime_risk_outcome_parent_legacy_quarantine_invalid"
            )
    elif parent_acceptance_status == "VERIFIED_ACCEPTED_HEAD":
        if (
            not _valid_sha256(parent_accepted_manifest_sha256)
            or parent_accepted_manifest_bytes <= 0
            or parent_accepted_manifest_as_of_date != parent_as_of_date
        ):
            raise ValueError(
                "runtime_risk_outcome_parent_accepted_head_invalid"
            )
        parent_manifest_path = (
            latest_run
            / "run287_risk_outcome_parent_accepted"
            / "manifest.json"
        )
        if (
            not parent_manifest_path.is_file()
            or parent_manifest_path.stat().st_size
            != parent_accepted_manifest_bytes
            or sha256_file(parent_manifest_path)
            != parent_accepted_manifest_sha256
        ):
            raise ValueError(
                "runtime_risk_outcome_parent_accepted_manifest_mismatch"
            )
        parent_manifest = read_json(parent_manifest_path)
        parent_manifest_chain = parent_manifest.get("outcome_chain")
        parent_manifest_files = parent_manifest.get("files")
        parent_summary_record = (
            parent_manifest_files.get("risk_outcome_summary")
            if isinstance(parent_manifest_files, dict)
            else None
        )
        parent_event_record = (
            parent_manifest_files.get("risk_outcome_event_log")
            if isinstance(parent_manifest_files, dict)
            else None
        )
        if (
            parent_manifest.get("schema_version")
            != RISK_OUTCOME_ACCEPTED_MANIFEST_SCHEMA
            or parent_manifest.get("status")
            != RISK_OUTCOME_ACCEPTED_MANIFEST_READY_STATUS
            or parent_manifest.get("review_only") is not True
            or str(parent_manifest.get("as_of_date") or "")
            != parent_as_of_date
            or not isinstance(parent_manifest_chain, dict)
            or parent_manifest_chain.get("current_event_log_sha256")
            != parent_event_sha256
            or parent_manifest_chain.get("current_event_log_bytes")
            != parent_event_bytes
            or parent_manifest_chain.get("current_event_count")
            != parent_event_count
            or not isinstance(parent_summary_record, dict)
            or parent_summary_record.get("path")
            != "run287_risk_outcome_archive/summary.json"
            or parent_summary_record.get("sha256")
            != parent_summary_sha256
            or (
                parent_event_count > 0
                and (
                    not isinstance(parent_event_record, dict)
                    or parent_event_record.get("path")
                    != (
                        "run287_risk_outcome_archive/"
                        "risk_outcome_events.jsonl"
                    )
                    or parent_event_record.get("sha256")
                    != parent_event_sha256
                )
            )
        ):
            raise ValueError(
                "runtime_risk_outcome_parent_accepted_manifest_invalid"
            )
        observed_files[
            parent_manifest_path.relative_to(latest_run).as_posix()
        ] = parent_accepted_manifest_sha256
    else:
        raise ValueError(
            "runtime_risk_outcome_parent_acceptance_status_invalid"
        )

    chain = outcome.get("outcome_chain")
    if (
        not isinstance(chain, dict)
        or chain.get("schema_version") != RISK_OUTCOME_CHAIN_SCHEMA
        or chain.get("status") != "VERIFIED_APPEND_ONLY"
        or chain.get("parent_anchor_sha256") != anchor_sha256
        or chain.get("parent_anchor_status") != status
        or chain.get("exact_parent_prefix_verified") is not True
        or chain.get("append_only_verified") is not True
    ):
        raise ValueError("runtime_risk_outcome_chain_contract_invalid")
    comparable_parent_fields = (
        "parent_summary_sha256",
        "parent_summary_bytes",
        "parent_event_log_sha256",
        "parent_event_log_bytes",
        "parent_event_count",
        "parent_as_of_date",
        "carried_quarantined_prefix_event_count",
        "parent_acceptance_status",
        "parent_accepted_manifest_sha256",
        "parent_accepted_manifest_bytes",
        "parent_accepted_manifest_as_of_date",
    )
    if any(
        chain.get(field) != anchor.get(field)
        for field in comparable_parent_fields
    ):
        raise ValueError("runtime_risk_outcome_chain_parent_mismatch")

    raw = event_log_path.read_bytes()
    current_count = len(_jsonl_rows(event_log_path))
    current_sha256 = hashlib.sha256(raw).hexdigest()
    if (
        chain.get("current_event_log_sha256") != current_sha256
        or _integer(
            chain.get("current_event_log_bytes"),
            "risk_outcome.chain.current_event_log_bytes",
        )
        != len(raw)
        or _integer(
            chain.get("current_event_count"),
            "risk_outcome.chain.current_event_count",
        )
        != current_count
        or str(chain.get("current_as_of_date") or "")
        != str(outcome.get("as_of_date") or "")
        or parent_event_bytes > len(raw)
        or parent_event_count > current_count
    ):
        raise ValueError("runtime_risk_outcome_chain_current_mismatch")
    prefix = raw[:parent_event_bytes]
    if (
        hashlib.sha256(prefix).hexdigest() != parent_event_sha256
        or (parent_event_bytes > 0 and not prefix.endswith(b"\n"))
        or prefix.count(b"\n") != parent_event_count
    ):
        raise ValueError("runtime_risk_outcome_event_prefix_rewrite")
    trusted_event_count = current_count - quarantined_count
    if (
        trusted_event_count < 0
        or _integer(
            chain.get("trusted_event_count"),
            "risk_outcome.chain.trusted_event_count",
        )
        != trusted_event_count
    ):
        raise ValueError("runtime_risk_outcome_chain_trusted_count_mismatch")
    if sha256_file(anchor_path) != anchor_sha256:
        raise ValueError(
            "runtime_risk_outcome_parent_anchor_changed_during_validation"
        )
    return {
        "parent_anchor_status": status,
        "parent_event_count": parent_event_count,
        "quarantined_prefix_event_count": quarantined_count,
        "trusted_event_count": trusted_event_count,
        "parent_acceptance_status": parent_acceptance_status,
    }


def _validated_risk_outcome_counts(
    *,
    outcome: dict[str, Any],
    latest_run: Path,
    paper_as_of_date: str,
    observed_files: dict[str, str],
    expected_summary_sha256: str,
    expected_parent_anchor_sha256: str,
) -> dict[str, Any]:
    if outcome.get("schema_version") != RISK_OUTCOME_SCHEMA:
        raise ValueError("runtime_risk_outcome_schema_invalid")
    if outcome.get("status") != RISK_OUTCOME_READY_STATUS:
        raise ValueError("runtime_risk_outcome_summary_not_ready")
    if outcome.get("blockers") != []:
        raise ValueError("runtime_risk_outcome_blockers_present")
    if str(outcome.get("as_of_date") or "") != paper_as_of_date:
        raise ValueError("runtime_risk_outcome_as_of_date_mismatch")
    if outcome.get("review_only") is not True:
        raise ValueError("runtime_risk_outcome_not_review_only")
    _require_false_flags(
        outcome,
        (
            "mechanism_promotion_allowed",
            "portfolio_transition_allowed",
            "orders_generated",
            "target_books_mutated",
            "historical_cagr_mdd_evidence_changed",
            "backtest_executed",
            "fullrun_executed",
            "production_activation_allowed",
            "live_trading_enabled",
        ),
        "runtime_risk_outcome",
    )
    if (
        outcome.get("threshold_tuning_allowed") is not False
        or outcome.get("stop_or_exit_rule_created") is not False
        or outcome.get("selector_weights_changed") is not False
        or outcome.get("cash_policy_changed") is not False
    ):
        raise ValueError("runtime_risk_outcome_governance_flags_invalid")

    archive = latest_run / "run287_decision_observation_archive"
    outcome_root = latest_run / "run287_risk_outcome_archive"
    price_cache = latest_run / "run287_risk_outcome_price_cache"
    source_inputs = outcome.get("source_inputs") or {}
    output_hashes = outcome.get("outputs") or {}
    attested_paths = (
        (
            archive / "manifest.json",
            source_inputs.get("decision_archive_manifest_sha256"),
            "risk_outcome_decision_archive_manifest",
        ),
        (
            archive / "candidate_risk_history.jsonl",
            source_inputs.get("candidate_risk_history_sha256"),
            "risk_outcome_candidate_history",
        ),
        (
            archive / "position_history.jsonl",
            source_inputs.get("position_history_sha256"),
            "risk_outcome_position_history",
        ),
        (
            outcome_root / "risk_outcome_events.jsonl",
            output_hashes.get("event_log_sha256"),
            "risk_outcome_event_log",
        ),
        (
            outcome_root / "current_status.csv",
            output_hashes.get("current_status_sha256"),
            "risk_outcome_current_status",
        ),
        (
            outcome_root / "price_universe.csv",
            output_hashes.get("price_universe_sha256"),
            "risk_outcome_price_universe",
        ),
        )
    for path, expected, label in attested_paths:
        _verify_attested_file(
            path=path,
            expected_sha256=expected,
            latest_run=latest_run,
            observed_files=observed_files,
            label=label,
        )
    try:
        try:
            from tools.archive_run287_decision_observation import (
                canonical_tracked_contract_sha256,
            )
        except ModuleNotFoundError:
            from archive_run287_decision_observation import (
                canonical_tracked_contract_sha256,
            )
    except ImportError as exc:
        raise ValueError("runtime_risk_outcome_contract_validator_unavailable") from exc
    risk_contract_sha256 = canonical_tracked_contract_sha256(
        RISK_OUTCOME_CONTRACT,
        read_json(RISK_OUTCOME_CONTRACT),
        RISK_OUTCOME_CONTRACT_SHA256,
    )
    if (
        risk_contract_sha256 != RISK_OUTCOME_CONTRACT_SHA256
        or str(source_inputs.get("contract_sha256") or "")
        != RISK_OUTCOME_CONTRACT_SHA256
    ):
        raise ValueError("runtime_risk_outcome_contract_mismatch")
    observed_files[
        f"repo:{RISK_OUTCOME_CONTRACT.relative_to(ROOT).as_posix()}"
    ] = sha256_file(RISK_OUTCOME_CONTRACT)
    price_cache_manifest_path = (
        price_cache / "replay_price_cache_manifest.json"
    )
    expected_price_cache_manifest_sha256 = str(
        source_inputs.get("price_cache_manifest_sha256") or ""
    )
    _verify_attested_file(
        path=price_cache_manifest_path,
        expected_sha256=expected_price_cache_manifest_sha256,
        latest_run=latest_run,
        observed_files=observed_files,
        label="risk_outcome_price_cache_manifest",
    )
    price_cache_manifest = read_json(price_cache_manifest_path)
    if (
        price_cache_manifest.get("schema_version")
        != "run287-replay-price-cache-manifest-v2"
        or price_cache_manifest.get("review_only") is not True
        or price_cache_manifest.get("production_mutation_allowed") is not False
        or price_cache_manifest.get("live_trading_enabled") is not False
        or not isinstance(price_cache_manifest.get("cache_files"), dict)
        or not isinstance(price_cache_manifest.get("book_inputs"), list)
    ):
        raise ValueError("runtime_risk_outcome_price_cache_manifest_invalid")
    universe_path = outcome_root / "price_universe.csv"
    bound_universe_inputs = [
        record
        for record in price_cache_manifest["book_inputs"]
        if isinstance(record, dict)
        and Path(str(record.get("path") or "")).resolve()
        == universe_path.resolve()
    ]
    if (
        len(bound_universe_inputs) != 1
        or bound_universe_inputs[0].get("sha256")
        != output_hashes.get("price_universe_sha256")
        or _integer(
            bound_universe_inputs[0].get("bytes"),
            "risk_outcome.price_cache_manifest.price_universe.bytes",
        )
        != universe_path.stat().st_size
    ):
        raise ValueError(
            "runtime_risk_outcome_price_cache_universe_binding_mismatch"
        )
    decision_manifest = read_json(archive / "manifest.json")
    paper_date = date.fromisoformat(paper_as_of_date)
    observations, archive_history_paths = _validate_decision_archive(
        archive=archive,
        manifest=decision_manifest,
        paper_date=paper_date,
        latest_run=latest_run,
        observed_files=observed_files,
    )

    status_rows = _csv_rows(outcome_root / "current_status.csv")
    if not status_rows:
        raise ValueError("runtime_risk_outcome_current_status_empty")
    observation_ids = [str(row.get("observation_id") or "") for row in status_rows]
    if any(not value for value in observation_ids) or len(observation_ids) != len(set(observation_ids)):
        raise ValueError("runtime_risk_outcome_observation_ids_invalid")
    events = _jsonl_rows(outcome_root / "risk_outcome_events.jsonl")
    event_ids = [str(event.get("event_id") or "") for event in events]
    if any(not value for value in event_ids) or len(event_ids) != len(set(event_ids)):
        raise ValueError("runtime_risk_outcome_event_ids_invalid")
    event_positions = {
        event_id: index for index, event_id in enumerate(event_ids)
    }
    for event in events:
        if event.get("event_type") not in {
            "risk_signal_observed",
            "forward_outcome_observed",
        }:
            raise ValueError("runtime_risk_outcome_event_type_invalid")
        if event.get("schema_version") != RISK_OUTCOME_SCHEMA:
            raise ValueError("runtime_risk_outcome_event_schema_invalid")
        if event.get("review_only") is not True:
            raise ValueError("runtime_risk_outcome_event_not_review_only")
        _require_false_flags(
            event,
            (
                "portfolio_transition_allowed",
                "orders_generated",
                "target_books_mutated",
                "historical_cagr_mdd_evidence_changed",
                "production_activation_allowed",
                "live_trading_enabled",
            ),
            "runtime_risk_outcome_event",
        )
    signals = {
        str(event.get("observation_id") or ""): event
        for event in events
        if event.get("event_type") == "risk_signal_observed"
    }
    outcomes = {
        (
            str(event.get("observation_id") or ""),
            _integer(event.get("horizon_trading_days"), "horizon_trading_days"),
        ): event
        for event in events
        if event.get("event_type") == "forward_outcome_observed"
    }
    outcome_event_count = sum(
        event.get("event_type") == "forward_outcome_observed" for event in events
    )
    if len(outcomes) != outcome_event_count:
        raise ValueError("runtime_risk_outcome_duplicate_outcome_event")
    expected_observations = {
        str(observation["observation_id"]): observation
        for observation in observations
    }
    if (
        set(observation_ids) != set(signals)
        or set(signals) != set(expected_observations)
    ):
        raise ValueError("runtime_risk_outcome_status_signal_set_mismatch")

    try:
        import pandas as pd
        import pandas_market_calendars as mcal
        try:
            from tools.resolve_run287_risk_outcomes import (
                load_cached_prices,
                outcome_event,
                sha256_text,
            )
            from tools.run_free_data_forward_paper_ledger import load_nyse_sessions
            from tools.run_weekly_evaluation import px_cache_name
        except ModuleNotFoundError:
            from resolve_run287_risk_outcomes import (
                load_cached_prices,
                outcome_event,
                sha256_text,
            )
            from run_free_data_forward_paper_ledger import load_nyse_sessions
            from run_weekly_evaluation import px_cache_name
    except ImportError as exc:
        raise ValueError("runtime_risk_outcome_semantic_validator_unavailable") from exc

    weeks: set[str] = set()
    promotion_eligible_signal_ids: set[str] = set()
    promotion_eligible_weeks: set[str] = set()
    completed: dict[int, int] = {}
    status_by_id = {str(row["observation_id"]): row for row in status_rows}
    cache_files: dict[str, Path] = {}
    cache_frames: dict[str, tuple[Any, str, str]] = {}
    calendar = mcal.get_calendar("NYSE")

    def prices(ticker: str) -> tuple[Any, str, str]:
        if ticker not in cache_frames:
            path = price_cache / px_cache_name(ticker)
            if not path.is_file():
                raise ValueError(
                    f"runtime_risk_outcome_price_cache_missing:{ticker}"
                )
            actual_hash = sha256_file(path)
            cache_record = (
                price_cache_manifest.get("cache_files") or {}
            ).get(ticker)
            if (
                not isinstance(cache_record, dict)
                or cache_record.get("file") != path.name
                or cache_record.get("sha256") != actual_hash
                or _integer(
                    cache_record.get("bytes"),
                    f"risk_outcome.price_cache_manifest.{ticker}.bytes",
                )
                != path.stat().st_size
            ):
                raise ValueError(
                    f"runtime_risk_outcome_price_cache_manifest_mismatch:{ticker}"
                )
            frame, basis = load_cached_prices(price_cache, ticker)
            if basis != "adjusted_close" or frame.empty:
                raise ValueError(
                    f"runtime_risk_outcome_price_cache_basis_invalid:{ticker}"
                )
            cache_files[ticker] = path
            cache_frames[ticker] = (frame, basis, actual_hash)
            observed_files[path.relative_to(latest_run).as_posix()] = actual_hash
        return cache_frames[ticker]

    sessions = load_nyse_sessions(
        pd.Timestamp(
            min(
                date.fromisoformat(str(row["decision_date"]))
                for row in observations
            )
        ),
        pd.Timestamp(paper_date),
    )
    if sessions is None or len(sessions) == 0:
        raise ValueError("runtime_risk_outcome_nyse_calendar_unavailable")

    signal_required_fields = (
        "family",
        "decision_date",
        "ticker",
        "risk_state",
        "advisory_action",
        "reason_codes",
        "observation_id",
        "signal_snapshot_sha256",
        "source_record_event_ids",
    )
    signal_optional_fields = (
        "portfolio_kind",
        "history_observations",
        "signal_return_1d",
        "signal_spy_excess_return_1d",
        "signal_return_21d",
        "signal_spy_excess_return_21d",
        "signal_drawdown_63d",
        "proposed_entries",
        "marked_weight",
        "official_prior_weight",
        "scenario_keys",
    )
    for observation_id, observation in expected_observations.items():
        signal = signals[observation_id]
        if signal.get("threshold_tuning_allowed") is not False:
            raise ValueError("runtime_risk_outcome_signal_threshold_tuning_not_false")
        expected_event_id = sha256_text(
            f"{RISK_OUTCOME_SCHEMA}|risk_signal_observed|{observation_id}"
        )
        if (
            signal.get("event_id") != expected_event_id
            or signal.get("benchmark_ticker") != "SPY"
        ):
            raise ValueError("runtime_risk_outcome_signal_identity_invalid")
        for field in signal_required_fields:
            if field not in signal or not _same_scalar(
                signal.get(field), observation.get(field)
            ):
                if isinstance(observation.get(field), (dict, list)) and (
                    canonical_sha256(signal.get(field))
                    == canonical_sha256(observation.get(field))
                ):
                    continue
                raise ValueError(
                    f"runtime_risk_outcome_signal_archive_mismatch:{field}"
                )
        for field in signal_optional_fields:
            if field in observation and (
                canonical_sha256(signal.get(field))
                != canonical_sha256(observation.get(field))
                if isinstance(observation.get(field), (dict, list))
                else not _same_scalar(signal.get(field), observation.get(field))
            ):
                raise ValueError(
                    f"runtime_risk_outcome_signal_archive_mismatch:{field}"
                )
        try:
            signal_recorded_at = pd.Timestamp(
                str(signal.get("recorded_at_utc") or "")
            )
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "runtime_risk_outcome_signal_recorded_at_invalid"
            ) from exc
        if signal_recorded_at.tzinfo is None:
            raise ValueError(
                "runtime_risk_outcome_signal_recorded_at_not_utc"
            )
        signal_decision_date = date.fromisoformat(
            str(signal.get("decision_date") or "")
        )
        signal_schedule = calendar.schedule(
            start_date=signal_decision_date,
            end_date=signal_decision_date + 14 * date.resolution,
        )
        if (
            signal_schedule.empty
            or signal_schedule.index[0].date() != signal_decision_date
        ):
            raise ValueError(
                "runtime_risk_outcome_signal_decision_not_nyse_session"
            )
        signal_recorded_utc = signal_recorded_at.tz_convert("UTC")
        decision_close = signal_schedule.iloc[0]["market_close"].tz_convert(
            "UTC"
        )
        if signal_recorded_utc < decision_close:
            raise ValueError(
                "runtime_risk_outcome_signal_recorded_before_decision_close"
            )
        if (
            len(signal_schedule) >= 2
            and signal_recorded_utc
            <= signal_schedule.iloc[1]["market_close"].tz_convert("UTC")
        ):
            promotion_eligible_signal_ids.add(observation_id)
            promotion_eligible_weeks.add(
                str(signal.get("iso_decision_week") or "")
            )
        row = status_by_id[observation_id]
        for field in (
            "decision_date",
            "family",
            "portfolio_kind",
            "ticker",
            "risk_state",
            "advisory_action",
            "reason_codes",
            "signal_snapshot_sha256",
        ):
            if str(row.get(field) or "") != str(signal.get(field) or ""):
                raise ValueError(
                    f"runtime_risk_outcome_signal_status_mismatch:{field}"
                )

    for row in status_rows:
        decision_date = date.fromisoformat(str(row.get("decision_date") or ""))
        if decision_date > paper_date:
            raise ValueError("runtime_risk_outcome_future_decision_date")
        iso = decision_date.isocalendar()
        expected_week = f"{iso.year:04d}-W{iso.week:02d}"
        if str(row.get("iso_decision_week") or "") != expected_week:
            raise ValueError("runtime_risk_outcome_decision_week_mismatch")
        signal = signals[str(row["observation_id"])]
        if (
            str(signal.get("decision_date") or "") != decision_date.isoformat()
            or str(signal.get("iso_decision_week") or "") != expected_week
        ):
            raise ValueError("runtime_risk_outcome_signal_status_mismatch")
        weeks.add(expected_week)
    for key, event in outcomes.items():
        observation_id, horizon = key
        if observation_id not in signals or horizon not in RISK_OUTCOME_HORIZONS:
            raise ValueError("runtime_risk_outcome_outcome_identity_invalid")
        signal = signals[observation_id]
        evaluated = date.fromisoformat(
            str(event.get("evaluated_as_of_date") or "")
        )
        if evaluated > paper_date:
            raise ValueError(
                f"runtime_risk_outcome_future_evaluation_date:{horizon}d"
            )
        try:
            recorded_at = pd.Timestamp(
                str(event.get("recorded_at_utc") or "")
            )
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"runtime_risk_outcome_recorded_at_invalid:{horizon}d"
            ) from exc
        if recorded_at.tzinfo is None:
            raise ValueError(
                f"runtime_risk_outcome_recorded_at_not_utc:{horizon}d"
            )
        evaluated_schedule = calendar.schedule(
            start_date=evaluated,
            end_date=evaluated,
        )
        if (
            evaluated_schedule.empty
            or recorded_at.tz_convert("UTC")
            < evaluated_schedule.iloc[0]["market_close"].tz_convert("UTC")
        ):
            raise ValueError(
                f"runtime_risk_outcome_recorded_before_completed_close:{horizon}d"
            )
        ticker = str(signal.get("ticker") or "")
        benchmark = str(signal.get("benchmark_ticker") or "")
        ticker_frame, _ticker_basis, ticker_hash = prices(ticker)
        benchmark_frame, _benchmark_basis, benchmark_hash = prices(benchmark)
        expected_event, expected_status = outcome_event(
            signal,
            horizon,
            ticker_frame,
            benchmark_frame,
            sessions,
            as_of_date=pd.Timestamp(evaluated),
            recorded_at=str(event.get("recorded_at_utc") or ""),
            ticker_hash=ticker_hash,
            benchmark_hash=benchmark_hash,
        )
        if expected_event is None or expected_status != "completed":
            raise ValueError(
                f"runtime_risk_outcome_completed_event_not_reproducible:{horizon}d"
            )
        for field in (
            "ticker_price_cache_sha256",
            "benchmark_price_cache_sha256",
        ):
            if not _valid_sha256(event.get(field)):
                raise ValueError(
                    f"runtime_risk_outcome_completed_event_cache_hash_invalid:"
                    f"{horizon}d:{field}"
                )
            # The parquet may grow after this append-only event completes.
            # Its creation-time full-file hash remains lineage metadata; the
            # immutable exact close path below is the durable replay identity.
            expected_event[field] = event[field]
        evidence_basis = str(
            event.get("price_evidence_hash_basis") or ""
        )
        if evidence_basis == "":
            # Backward-compatible replay for already accepted v1 events. Their
            # economics are still recomputed from the exact NYSE close path;
            # only the later-added path-hash fields are absent.
            for field in (
                "price_evidence_hash_basis",
                "ticker_price_path_sha256",
                "benchmark_price_path_sha256",
            ):
                expected_event.pop(field, None)
        elif evidence_basis != "exact_nyse_close_path_v1":
            raise ValueError(
                f"runtime_risk_outcome_price_evidence_basis_invalid:{horizon}d"
            )
        _require_event_matches(
            event,
            expected_event,
            f"runtime_risk_outcome_completed_event:{horizon}d",
        )

    parent_prefix = _validated_risk_outcome_parent_prefix(
        outcome=outcome,
        event_log_path=outcome_root / "risk_outcome_events.jsonl",
        anchor_path=(
            latest_run
            / "run287_risk_outcome_parent_anchor"
            / "anchor.json"
        ),
        expected_anchor_sha256=expected_parent_anchor_sha256,
        latest_run=latest_run,
        observed_files=observed_files,
    )
    quarantine_count = int(
        parent_prefix["quarantined_prefix_event_count"]
    )
    trusted_signal_ids = {
        observation_id
        for observation_id, signal in signals.items()
        if event_positions[str(signal["event_id"])] >= quarantine_count
    }
    promotion_eligible_signal_ids.intersection_update(trusted_signal_ids)
    promotion_eligible_weeks = {
        str(signals[observation_id].get("iso_decision_week") or "")
        for observation_id in promotion_eligible_signal_ids
    }

    for horizon in RISK_OUTCOME_HORIZONS:
        field = f"outcome_{horizon}d_status"
        if field not in status_rows[0]:
            raise ValueError(f"runtime_risk_outcome_status_column_missing:{field}")
        actual_counts = Counter(str(row.get(field) or "") for row in status_rows)
        if any(not key for key in actual_counts):
            raise ValueError(f"runtime_risk_outcome_blank_status:{horizon}d")
        summary_counts = (outcome.get("horizon_status_counts") or {}).get(f"{horizon}d")
        if not isinstance(summary_counts, dict):
            raise ValueError(f"runtime_risk_outcome_summary_counts_missing:{horizon}d")
        normalized_summary = {
            str(key): _integer(value, f"{horizon}d.{key}")
            for key, value in summary_counts.items()
        }
        if dict(actual_counts) != normalized_summary:
            raise ValueError(f"runtime_risk_outcome_summary_counts_mismatch:{horizon}d")
        for row in status_rows:
            key = (str(row["observation_id"]), horizon)
            completed_status = str(row.get(field) or "") == "completed"
            if completed_status != (key in outcomes):
                raise ValueError(
                    f"runtime_risk_outcome_event_status_mismatch:{horizon}d"
                )
            signal = signals[key[0]]
            if key in outcomes:
                event = outcomes[key]
                outcome_date = date.fromisoformat(
                    str(event.get("outcome_date") or "")
                )
                if (
                    outcome_date > paper_date
                    or str(row.get(f"outcome_{horizon}d_outcome_date") or "")
                    != outcome_date.isoformat()
                ):
                    raise ValueError(
                        f"runtime_risk_outcome_status_outcome_date_mismatch:{horizon}d"
                    )
            else:
                ticker_frame, _ticker_basis, ticker_hash = prices(
                    str(signal.get("ticker") or "")
                )
                benchmark_frame, _benchmark_basis, benchmark_hash = prices(
                    str(signal.get("benchmark_ticker") or "")
                )
                missing_event, pending_status = outcome_event(
                    signal,
                    horizon,
                    ticker_frame,
                    benchmark_frame,
                    sessions,
                    as_of_date=pd.Timestamp(paper_date),
                    recorded_at="recompute",
                    ticker_hash=ticker_hash,
                    benchmark_hash=benchmark_hash,
                )
                if missing_event is not None or str(row.get(field) or "") != pending_status:
                    raise ValueError(
                        f"runtime_risk_outcome_pending_status_mismatch:{horizon}d"
                    )
        completed[horizon] = 0
        for row in status_rows:
            observation_id = str(row.get("observation_id") or "")
            key = (observation_id, horizon)
            if (
                str(row.get(field) or "") == "completed"
                and observation_id in promotion_eligible_signal_ids
                and event_positions[str(outcomes[key]["event_id"])]
                >= quarantine_count
            ):
                completed[horizon] += 1
    if _integer(
        outcome.get("distinct_decision_week_count", 0),
        "distinct_decision_week_count",
    ) != len(weeks):
        raise ValueError("runtime_risk_outcome_summary_decision_weeks_mismatch")
    if _integer(
        outcome.get("signal_observation_count"),
        "risk_outcome.signal_observation_count",
    ) != len(signals):
        raise ValueError("runtime_risk_outcome_signal_count_mismatch")
    if _integer(
        outcome.get("forward_outcome_event_count"),
        "risk_outcome.forward_outcome_event_count",
    ) != len(outcomes):
        raise ValueError("runtime_risk_outcome_event_count_mismatch")

    universe_rows = _csv_rows(outcome_root / "price_universe.csv")
    universe_tickers = [str(row.get("ticker") or "") for row in universe_rows]
    replay_tickers = {
        str(row.get("ticker") or "")
        for row in status_rows
    }
    expected_universe = replay_tickers | {"SPY"}
    if (
        any(not ticker for ticker in universe_tickers)
        or len(universe_tickers) != len(set(universe_tickers))
        or set(universe_tickers) != expected_universe
        or _integer(
            outcome.get("price_universe_unique_ticker_count"),
            "risk_outcome.price_universe_unique_ticker_count",
        )
        != len(expected_universe)
    ):
        raise ValueError("runtime_risk_outcome_price_universe_semantic_mismatch")

    for path, expected, label in attested_paths:
        _verify_attested_file(
            path=path,
            expected_sha256=expected,
            latest_run=latest_run,
            observed_files=observed_files,
            label=f"{label}_rebound",
        )
    for path in archive_history_paths:
        record = (decision_manifest.get("outputs") or {}).get(
            f"{path.stem.removesuffix('_history')}_history"
        )
        _verify_fingerprint_record(
            record=record,
            path=path,
            label=f"risk_outcome_decision_archive_{path.stem}_rebound",
            latest_run=latest_run,
            observed_files=observed_files,
        )
    for ticker, path in cache_files.items():
        if sha256_file(path) != cache_frames[ticker][2]:
            raise ValueError(
                f"runtime_risk_outcome_price_cache_changed_during_validation:{ticker}"
            )
    if (
        sha256_file(price_cache_manifest_path)
        != expected_price_cache_manifest_sha256
    ):
        raise ValueError(
            "runtime_risk_outcome_price_cache_manifest_changed_during_validation"
        )
    summary_path = outcome_root / "summary.json"
    if (
        not _valid_sha256(expected_summary_sha256)
        or sha256_file(summary_path) != expected_summary_sha256
    ):
        raise ValueError("runtime_risk_outcome_summary_changed_during_validation")
    return {
        "distinct_decision_weeks": len(promotion_eligible_weeks),
        "promotion_eligible_signal_count":
            len(promotion_eligible_signal_ids),
        "quarantined_signal_observation_count":
            len(signals) - len(trusted_signal_ids),
        "promotion_ineligible_late_signal_count":
            len(trusted_signal_ids) - len(promotion_eligible_signal_ids),
        "parent_acceptance_status":
            parent_prefix["parent_acceptance_status"],
        **{
            f"resolved_{horizon}d_outcomes": completed[horizon]
            for horizon in PROMOTION_OUTCOME_HORIZONS
        },
    }


def _validate_verified_paper_snapshot(
    paper_root: Path,
    verified_manifest: dict[str, Any],
) -> dict[str, int]:
    paper_as_of = date.fromisoformat(str(verified_manifest.get("as_of_date") or ""))
    try:
        import pandas as pd
        import pandas_market_calendars as mcal
        try:
            from tools.run_daily_simulated_fill_ledger import (
                preview_identity,
                validate_restored_snapshot,
                verify_accepted_publication,
            )
        except ModuleNotFoundError:
            from run_daily_simulated_fill_ledger import (
                preview_identity,
                validate_restored_snapshot,
                verify_accepted_publication,
            )
    except ImportError as exc:
        raise ValueError("runtime_paper_semantic_validator_unavailable") from exc
    calendar = mcal.get_calendar("NYSE")
    expected_date = paper_as_of.isoformat()
    summary = read_json(paper_root / "summary.json")
    if (
        summary.get("schema_version")
        != "daily-simulated-fill-ledger-summary-v1"
        or summary.get("status") != "completed"
        or str(summary.get("as_of_date") or "") != expected_date
        or summary.get("review_only") is not True
        or summary.get("simulated") is not True
        or summary.get("live_trading_enabled") is not False
        or summary.get("production_mutation_allowed") is not False
        or summary.get("historical_cagr_mdd_replacement_allowed") is not False
    ):
        raise ValueError("runtime_paper_summary_contract_invalid")
    accepted = verify_accepted_publication(
        paper_root, paper_root.parent / "account_ledger_preview"
    )
    if (
        accepted.get("schema_version")
        != "run287-paper-accepted-publication-v1"
        or accepted.get("status") != "ACCEPTED_ATOMIC_PUBLICATION"
        or str(accepted.get("as_of_date") or "") != expected_date
        or accepted.get("transaction_mode") not in {"MARK_ONLY", "SELECTED_TARGET"}
        or accepted.get("review_only") is not True
        or accepted.get("live_trading_enabled") is not False
        or accepted.get("production_mutation_allowed") is not False
    ):
        raise ValueError("runtime_paper_accepted_publication_invalid")

    derived = {
        "future_close_count": 0,
        "stale_substituted_close_count": 0,
    }
    for portfolio in PORTFOLIOS:
        directory = paper_root / portfolio
        account_path = directory / "account_state_latest.json"
        if not account_path.is_file():
            raise ValueError(f"runtime_paper_account_missing:{portfolio}")
        validate_restored_snapshot(directory, portfolio)
        manifest = read_json(directory / "manifest.json")
        account = read_json(account_path)
        meta = read_json(directory / "state_meta.json")
        for payload, label in (
            (manifest, "manifest"),
            (account, "account"),
            (meta, "state_meta"),
        ):
            if str(payload.get("as_of_date") or "") != expected_date:
                raise ValueError(f"runtime_paper_as_of_mismatch:{portfolio}:{label}")
        if (
            manifest.get("schema_version")
            != "daily-simulated-fill-ledger-manifest-v2"
            or manifest.get("portfolio_kind") != portfolio
            or manifest.get("fill_mode") != "next_close"
            or manifest.get("integer_shares") is not True
            or not math.isclose(
                float(manifest.get("cost_bps_per_side")), 25.0, abs_tol=1e-9
            )
            or _integer(
                manifest.get("max_fill_lag_days"),
                f"paper.{portfolio}.max_fill_lag_days",
            )
            != 7
            or manifest.get("review_only") is not True
            or manifest.get("simulated") is not True
            or manifest.get("live_trading_enabled") is not False
            or manifest.get("production_mutation_allowed") is not False
            or manifest.get("historical_cagr_mdd_replacement_allowed") is not False
            or manifest.get("security_lifecycle_schema_version")
            != "run287-security-lifecycle-v1"
        ):
            raise ValueError(f"runtime_paper_manifest_contract_invalid:{portfolio}")
        for field in (
            "target_hash",
            "target_sha256",
            "source_target_sha256",
            "seed_account_sha256",
            "security_lifecycle_source_sha256",
            "security_lifecycle_snapshot_hash",
        ):
            if not _valid_sha256(manifest.get(field)):
                raise ValueError(
                    f"runtime_paper_manifest_hash_invalid:{portfolio}:{field}"
                )
        bootstrap_path = (
            paper_root / "bootstrap" / f"{portfolio}_account.json"
        )
        if (
            not bootstrap_path.is_file()
            or sha256_file(bootstrap_path)
            != manifest.get("seed_account_sha256")
        ):
            raise ValueError(
                f"runtime_paper_seed_account_binding_invalid:{portfolio}"
            )
        bootstrap = read_json(bootstrap_path)
        seed_as_of_date = str(account.get("seed_as_of_date") or "")
        if (
            not seed_as_of_date
            or str(bootstrap.get("as_of_date") or "") != seed_as_of_date
        ):
            raise ValueError(
                f"runtime_paper_seed_account_date_mismatch:{portfolio}"
            )
        accepted_row = (accepted.get("portfolios") or {}).get(portfolio) or {}
        latest_run = paper_root.parent.resolve()

        def accepted_path(value: Any, label: str) -> Path:
            raw = str(value or "")
            if not raw:
                raise ValueError(
                    f"runtime_paper_accepted_path_missing:{portfolio}:{label}"
                )
            candidate = Path(raw)
            resolved = (
                candidate if candidate.is_absolute() else ROOT / candidate
            ).resolve()
            try:
                resolved.relative_to(latest_run)
            except ValueError as exc:
                raise ValueError(
                    f"runtime_paper_accepted_path_outside_latest_run:{portfolio}:{label}"
                ) from exc
            return resolved

        source_target = accepted_path(
            accepted_row.get("source_target_path"), "source_target"
        )
        published_target = accepted_path(
            accepted_row.get("published_target_path"), "published_target"
        )
        expected_published = (
            latest_run
            / "reports"
            / f"operating_{portfolio}_target_book.csv"
        ).resolve()
        if published_target != expected_published:
            raise ValueError(
                f"runtime_paper_published_target_path_mismatch:{portfolio}"
            )
        for path, field in (
            (source_target, "source_target_sha256"),
            (published_target, "published_target_sha256"),
            (account_path, "account_state_sha256"),
            (directory / "manifest.json", "ledger_manifest_sha256"),
        ):
            if (
                not path.is_file()
                or not _valid_sha256(accepted_row.get(field))
                or sha256_file(path) != accepted_row.get(field)
            ):
                raise ValueError(
                    f"runtime_paper_accepted_hash_mismatch:{portfolio}:{field}"
                )
        if (
            accepted_row.get("source_target_sha256")
            != accepted_row.get("published_target_sha256")
        ):
            raise ValueError(
                f"runtime_paper_source_published_target_mismatch:{portfolio}"
            )
        if (
            manifest.get("target_sha256")
            != accepted_row.get("published_target_sha256")
            or manifest.get("source_target_sha256")
            != accepted_row.get("source_target_sha256")
        ):
            raise ValueError(
                f"runtime_paper_manifest_publication_target_mismatch:{portfolio}"
            )
        preview_dir = latest_run / "account_ledger_preview" / portfolio
        preview_manifest = read_json(preview_dir / "order_batch_manifest.json")
        preview_mode = str(preview_manifest.get("preview_mode") or "")
        if (
            preview_manifest.get("schema_version")
            != "account-ledger-preview-order-batch-v2"
            or preview_manifest.get("portfolio_kind") != portfolio
            or str(preview_manifest.get("as_of_date") or "") != expected_date
            or preview_mode not in {"NO_NEW_ORDER", "EXECUTABLE_CANDIDATE"}
            or preview_manifest.get("live_trading_enabled") is not False
            or preview_manifest.get("production_mutation_allowed") is not False
            or accepted_row.get("preview_mode_at_acceptance") != preview_mode
        ):
            raise ValueError(f"runtime_paper_preview_contract_invalid:{portfolio}")
        expected_preview_identity = preview_identity(
            preview_dir=preview_dir,
            account_path=account_path,
            effective_target_path=directory / "effective_target_latest.csv",
            source_target_path=source_target,
            portfolio=portfolio,
            as_of_date=pd.Timestamp(paper_as_of),
            preview_mode=preview_mode,
        )
        for field, value in expected_preview_identity.items():
            if not _same_scalar(preview_manifest.get(field), value):
                raise ValueError(
                    f"runtime_paper_preview_identity_mismatch:{portfolio}:{field}"
                )
        if (
            accepted_row.get("preview_identity_at_acceptance")
            != expected_preview_identity["preview_identity_hash"]
        ):
            raise ValueError(f"runtime_paper_preview_acceptance_mismatch:{portfolio}")
        if (
            account.get("schema_version") != "daily-simulated-account-v1"
            or account.get("portfolio_kind") != portfolio
            or account.get("fill_mode") != "next_close"
            or account.get("integer_shares") is not True
            or not math.isclose(
                float(account.get("cost_bps_per_side")), 25.0, abs_tol=1e-9
            )
            or account.get("review_only") is not True
            or account.get("simulated_broker_ledger") is not True
            or account.get("live_trading_enabled") is not False
            or account.get("production_mutation_allowed") is not False
            or account.get("human_approval_required_for_live_orders") is not True
            or account.get("seed_account_sha256")
            != manifest.get("seed_account_sha256")
        ):
            raise ValueError(f"runtime_paper_account_contract_invalid:{portfolio}")
        if (
            meta.get("schema_version")
            != "daily-simulated-fill-ledger-state-v2"
            or meta.get("portfolio_kind") != portfolio
            or meta.get("review_only") is not True
            or meta.get("live_trading_enabled") is not False
            or meta.get("production_mutation_allowed") is not False
            or meta.get("security_lifecycle_snapshot_hash")
            != manifest.get("security_lifecycle_snapshot_hash")
        ):
            raise ValueError(f"runtime_paper_state_meta_contract_invalid:{portfolio}")
        if canonical_sha256((summary.get("portfolios") or {}).get(portfolio)) != (
            canonical_sha256(manifest)
        ):
            raise ValueError(f"runtime_paper_summary_manifest_mismatch:{portfolio}")
        equity_rows = _csv_rows(directory / "equity_curve.csv")
        if not equity_rows:
            raise ValueError(f"runtime_paper_equity_curve_empty:{portfolio}")
        equity_dates = [
            date.fromisoformat(str(row.get("date") or "")) for row in equity_rows
        ]
        if (
            len(equity_dates) != len(set(equity_dates))
            or equity_dates != sorted(equity_dates)
            or equity_dates[0].isoformat() != seed_as_of_date
            or equity_dates[-1] != paper_as_of
        ):
            raise ValueError(f"runtime_paper_duplicate_equity_date:{portfolio}")
        schedule = calendar.schedule(
            start_date=min(equity_dates),
            end_date=paper_as_of,
        )
        nyse_ordered = [stamp.date() for stamp in schedule.index]
        nyse_dates = set(nyse_ordered)
        # The ledger records completed paper marks, not an inferred synthetic
        # mark for every exchange session.  A failed/skipped daily workflow may
        # therefore leave legitimate gaps; each persisted row must still be a
        # unique ordered NYSE session and the final row must be the accepted
        # paper as-of date.
        for row, row_date in zip(equity_rows, equity_dates):
            if row_date > paper_as_of:
                raise ValueError(f"runtime_paper_future_equity_date:{portfolio}")
            if row_date not in nyse_dates:
                raise ValueError(f"runtime_paper_non_nyse_equity_date:{portfolio}")
            for field in ("cash_usd", "equity_usd"):
                value = float(row.get(field))
                if not math.isfinite(value):
                    raise ValueError(
                        f"runtime_paper_nonfinite_equity_value:{portfolio}:{field}"
                    )
        last_equity = equity_rows[-1]
        for field in ("cash_usd", "equity_usd", "stock_value_usd"):
            if field in last_equity and not math.isclose(
                float(last_equity[field]),
                float(account.get(field)),
                rel_tol=1e-9,
                abs_tol=1e-6,
            ):
                raise ValueError(
                    f"runtime_paper_account_equity_curve_mismatch:{portfolio}:{field}"
                )
        for name in ("fills.csv", "rejections.csv", "pending_orders.csv"):
            for row in _csv_rows(directory / name):
                if name != "pending_orders.csv" and (
                    row.get("review_only") not in ("True", "true", "1", True)
                    or str(row.get("portfolio_kind") or "").lower()
                    != portfolio
                    or row.get("simulated")
                    not in ("True", "true", "1", True)
                    or row.get("live_trading_enabled")
                    not in ("False", "false", "0", False)
                    or row.get("production_mutation_allowed")
                    not in ("False", "false", "0", False)
                ):
                    raise ValueError(
                        f"runtime_paper_event_safety_invalid:{portfolio}:{name}"
                    )
                if name == "fills.csv" and row.get("event_type") not in {
                    "FILL",
                    "LIFECYCLE_SETTLEMENT",
                }:
                    raise ValueError(
                        f"runtime_paper_fill_event_type_invalid:{portfolio}"
                    )
                if (
                    name == "rejections.csv"
                    and row.get("event_type") != "REJECTION"
                ):
                    raise ValueError(
                        f"runtime_paper_rejection_event_type_invalid:{portfolio}"
                    )
                for field in ("date", "signal_date"):
                    raw = str(row.get(field) or "")
                    if raw and pd.Timestamp(raw).date() > paper_as_of:
                        derived["future_close_count"] += 1
                if name != "pending_orders.csv":
                    event_date_raw = str(row.get("date") or "")
                    signal_date_raw = str(row.get("signal_date") or "")
                    if not event_date_raw or not signal_date_raw:
                        raise ValueError(
                            f"runtime_paper_event_date_missing:{portfolio}:{name}"
                        )
                    event_date = pd.Timestamp(event_date_raw).date()
                    signal_event_date = pd.Timestamp(signal_date_raw).date()
                    if signal_event_date > event_date:
                        raise ValueError(
                            f"runtime_paper_event_chronology_invalid:{portfolio}:{name}"
                        )
                    event_schedule = calendar.schedule(
                        start_date=event_date,
                        end_date=event_date,
                    )
                    if event_schedule.empty:
                        raise ValueError(
                            f"runtime_paper_event_non_nyse_date:{portfolio}:{name}"
                        )
                if (
                    name == "fills.csv"
                    and str(row.get("event_type") or "") == "FILL"
                ):
                    if str(row.get("fill_mode") or "") != "next_close":
                        raise ValueError(
                            f"runtime_paper_fill_mode_invalid:{portfolio}"
                        )
                    if (
                        str(row.get("record_type") or "")
                        != "FORWARD_PAPER"
                        or not math.isclose(
                            float(row.get("cost_bps_per_side")),
                            25.0,
                            abs_tol=1e-9,
                        )
                    ):
                        raise ValueError(
                            f"runtime_paper_fill_contract_invalid:{portfolio}"
                        )
                    signal_date = pd.Timestamp(
                        str(row.get("signal_date") or "")
                    ).date()
                    fill_date = pd.Timestamp(
                        str(row.get("date") or "")
                    ).date()
                    next_schedule = calendar.schedule(
                        start_date=signal_date + date.resolution,
                        end_date=signal_date + 14 * date.resolution,
                    )
                    expected_fills = [
                        stamp.date() for stamp in next_schedule.index
                    ]
                    if not expected_fills or fill_date != expected_fills[0]:
                        derived["stale_substituted_close_count"] += 1
                elif (
                    name == "fills.csv"
                    and str(row.get("fill_mode") or "")
                    != "verified_lifecycle_proceeds"
                ):
                    raise ValueError(
                        f"runtime_paper_lifecycle_fill_mode_invalid:{portfolio}"
                    )
                elif (
                    name == "fills.csv"
                    and (
                        str(row.get("record_type") or "")
                        != "FORWARD_PAPER_LIFECYCLE"
                        or not math.isclose(
                            float(row.get("cost_bps_per_side")),
                            0.0,
                            abs_tol=1e-9,
                        )
                    )
                ):
                    raise ValueError(
                        f"runtime_paper_lifecycle_fill_contract_invalid:{portfolio}"
                    )
                elif (
                    name == "rejections.csv"
                    and str(row.get("fill_mode") or "")
                    not in {"next_close", "lifecycle_cancel"}
                ):
                    raise ValueError(
                        f"runtime_paper_rejection_fill_mode_invalid:{portfolio}"
                    )
    return derived


def _validate_runtime_scorecard(
    *,
    scorecard: dict[str, Any],
    scorecard_path: Path,
    scorecard_sha256: str,
    latest_run: Path,
    verified_paper_manifest: dict[str, Any],
    integrity_path: Path,
    observed_files: dict[str, str],
) -> None:
    try:
        try:
            from tools.archive_run287_decision_observation import (
                canonical_tracked_contract_sha256,
            )
            from tools.build_run287_operating_scorecard import build_scorecard
        except ModuleNotFoundError:
            from archive_run287_decision_observation import (
                canonical_tracked_contract_sha256,
            )
            from build_run287_operating_scorecard import build_scorecard
    except ImportError as exc:
        raise ValueError("runtime_scorecard_rebuilder_unavailable") from exc
    if (
        scorecard.get("schema_version") != SCORECARD_SCHEMA
        or scorecard.get("scorecard_trust_basis") != SCORECARD_TRUST_BASIS
        or scorecard.get("scorecard_trusted") is not True
        or scorecard.get("scorecard_trust_blockers") != []
        or scorecard.get("integrity_errors") != []
        or scorecard.get("private_review_only") is not True
        or scorecard.get("historical_acceptance_overwritten_by_forward")
        is not False
        or scorecard.get("source_artifacts_copied") is not False
        or scorecard.get("fullrun_executed") is not False
    ):
        raise ValueError("runtime_scorecard_contract_invalid")
    _require_false_flags(
        scorecard,
        (
            "public_deployment_allowed",
            "production_activation_allowed",
            "live_trading_enabled",
        ),
        "runtime_scorecard",
    )
    registry = read_json(SCORECARD_SOURCE_REGISTRY)
    canonical_registry_sha256 = canonical_tracked_contract_sha256(
        SCORECARD_SOURCE_REGISTRY,
        registry,
        SCORECARD_SOURCE_REGISTRY_SHA256,
    )
    raw_registry_sha256 = sha256_file(SCORECARD_SOURCE_REGISTRY)
    if (
        registry.get("schema_version")
        != "run287-operating-scorecard-source-registry-v1"
        or canonical_registry_sha256 != SCORECARD_SOURCE_REGISTRY_SHA256
        or scorecard.get("metric_definition_version")
        != registry.get("metric_definition_version")
        or scorecard.get("scorecard_as_of_date")
        != registry.get("scorecard_as_of_date")
        or scorecard.get("source_registry_sha256")
        not in {SCORECARD_SOURCE_REGISTRY_SHA256, raw_registry_sha256}
    ):
        raise ValueError("runtime_scorecard_registry_mismatch")

    trust = scorecard.get("runtime_trust_manifest") or {}
    paper_trust = trust.get("paper_snapshot") or {}
    source_bundle = trust.get("source_bundle") or {}
    bundle_spec = registry.get("canonical_source_bundle_manifest") or {}
    bundle_path = ROOT / str(bundle_spec.get("path") or "")
    managed_source_count = sum(
        spec.get("required") is True
        and str(spec.get("disposition") or "") == "ABSORBED_SOURCE"
        for spec in registry.get("sources") or []
    )
    if (
        trust.get("trusted_boolean_fields_ignored") is not True
        or source_bundle.get("status") != "VERIFIED"
        or source_bundle.get("sha256") != bundle_spec.get("expected_sha256")
        or not bundle_path.is_file()
        or source_bundle.get("sha256") != sha256_file(bundle_path)
        or _integer(
            source_bundle.get("source_count"), "scorecard.source_bundle.source_count"
        )
        != managed_source_count
        or _integer(
            source_bundle.get("verified_source_count"),
            "scorecard.source_bundle.verified_source_count",
        )
        != managed_source_count
        or paper_trust.get("status") != "VERIFIED"
        or paper_trust.get("manifest_sha256") != sha256_file(integrity_path)
        or paper_trust.get("snapshot_hash")
        != verified_paper_manifest.get("snapshot_hash")
    ):
        raise ValueError("runtime_scorecard_runtime_trust_mismatch")

    source_records = scorecard.get("sources")
    if not isinstance(source_records, list):
        raise ValueError("runtime_scorecard_sources_invalid")
    by_id = {
        str(record.get("source_id") or ""): record
        for record in source_records
        if isinstance(record, dict)
    }
    specs = {
        str(spec.get("id") or ""): spec
        for spec in registry.get("sources") or []
        if isinstance(spec, dict)
    }
    if set(by_id) != set(specs) or len(source_records) != len(specs):
        raise ValueError("runtime_scorecard_source_set_mismatch")
    for source_id, spec in specs.items():
        record = by_id[source_id]
        raw_spec_path = str(spec.get("path") or "")
        if raw_spec_path.startswith("outputs/"):
            actual_path = latest_run / raw_spec_path.removeprefix("outputs/")
        else:
            actual_path = ROOT / raw_spec_path
        actual_sha256 = sha256_file(actual_path) if actual_path.is_file() else None
        expected_sha256 = spec.get("expected_sha256")
        expected_status = (
            "VERIFIED"
            if actual_path.is_file()
            and (not expected_sha256 or expected_sha256 == actual_sha256)
            else "UNAVAILABLE"
            if not actual_path.is_file()
            else "INTEGRITY_ERROR"
        )
        if (
            record.get("source_id") != source_id
            or record.get("evidence_class") != spec.get("evidence_class")
            or record.get("section") != spec.get("section")
            or record.get("as_of_date") != spec.get("as_of_date")
            or record.get("metric_mode") != spec.get("metric_mode")
            or record.get("required") is not bool(spec.get("required"))
            or record.get("disposition")
            != spec.get("disposition", "SOURCE")
            or record.get("expected_sha256") != expected_sha256
            or record.get("sha256") != actual_sha256
            or record.get("status") != expected_status
        ):
            raise ValueError(f"runtime_scorecard_source_mismatch:{source_id}")
        if spec.get("required") is True and expected_status != "VERIFIED":
            raise ValueError(f"runtime_scorecard_required_source_unverified:{source_id}")
        if source_id in {"current_paper_summary", "current_paper_integrity"} and (
            expected_status != "VERIFIED"
        ):
            raise ValueError(f"runtime_scorecard_paper_source_unverified:{source_id}")
        if actual_path.is_file():
            try:
                key = actual_path.relative_to(latest_run).as_posix()
            except ValueError:
                key = f"repo:{actual_path.relative_to(ROOT).as_posix()}"
            observed_files[key] = str(actual_sha256)

    lanes = scorecard.get("trust_lanes") or {}
    lane_errors = scorecard.get("integrity_errors_by_lane") or {}
    evidence_status = scorecard.get("evidence_status") or {}
    for lane in ("historical", "current_paper_execution", "true_forward"):
        row = lanes.get(lane) or {}
        if (
            row.get("trusted") is not True
            or row.get("integrity_errors") != []
            or lane_errors.get(lane) != []
            or str(evidence_status.get(lane) or "") in {"", "NOT_TRUSTED", "UNAVAILABLE"}
        ):
            raise ValueError(f"runtime_scorecard_lane_untrusted:{lane}")
    if (
        scorecard.get("headline_performance_trust") != "TRUSTED"
        or not isinstance(scorecard.get("headline_performance"), dict)
        or not scorecard.get("headline_performance")
    ):
        raise ValueError("runtime_scorecard_headline_untrusted")
    for name, headline in scorecard["headline_performance"].items():
        if not isinstance(headline, dict) or headline.get("trust") != "TRUSTED":
            raise ValueError(f"runtime_scorecard_headline_invalid:{name}")
        provenance = headline.get("provenance") or {}
        source_id = str(headline.get("source_id") or "")
        record = by_id.get(source_id)
        if (
            not record
            or provenance.get("source_sha256") != record.get("sha256")
            or provenance.get("source_path") != record.get("path")
            or provenance.get("as_of_date") != record.get("as_of_date")
            or provenance.get("metric_mode") != record.get("metric_mode")
        ):
            raise ValueError(f"runtime_scorecard_headline_provenance_invalid:{name}")
    promotion = scorecard.get("promotion_governance") or {}
    if (
        promotion.get("production_activation_allowed") is not False
        or promotion.get("live_trading_enabled") is not False
    ):
        raise ValueError("runtime_scorecard_promotion_governance_unsafe")

    metrics = scorecard.get("metrics")
    if not isinstance(metrics, list) or not metrics:
        raise ValueError("runtime_scorecard_metrics_missing")
    metric_keys: list[tuple[str, str, str]] = []
    for metric in metrics:
        if not isinstance(metric, dict):
            raise ValueError("runtime_scorecard_metric_invalid")
        key = (
            str(metric.get("section") or ""),
            str(metric.get("metric_id") or ""),
            str(metric.get("portfolio") or ""),
        )
        if not key[0] or not key[1]:
            raise ValueError("runtime_scorecard_metric_identity_invalid")
        metric_keys.append(key)
        provenance = metric.get("provenance") or {}
        source_id = str(provenance.get("source_id") or "")
        record = by_id.get(source_id)
        if (
            not record
            or provenance.get("source_sha256") != record.get("sha256")
            or provenance.get("source_path") != record.get("path")
            or provenance.get("as_of_date") != record.get("as_of_date")
            or provenance.get("metric_mode") != record.get("metric_mode")
            or metric.get("status") == "INTEGRITY_ERROR"
        ):
            raise ValueError(
                f"runtime_scorecard_metric_provenance_invalid:{key[1]}"
            )
    if len(metric_keys) != len(set(metric_keys)):
        raise ValueError("runtime_scorecard_metric_identity_duplicate")
    runtime_registry = copy.deepcopy(registry)
    for spec in runtime_registry.get("sources") or []:
        raw_path = str(spec.get("path") or "")
        if raw_path.startswith("outputs/"):
            spec["path"] = str(
                latest_run / raw_path.removeprefix("outputs/")
            )
    rebuilt = build_scorecard(
        runtime_registry,
        source_registry_path=SCORECARD_SOURCE_REGISTRY,
        promotion_state_path=DEFAULT_STATE,
    )
    comparable_actual = {
        key: value for key, value in scorecard.items() if key != "generated_at_utc"
    }
    comparable_rebuilt = {
        key: value for key, value in rebuilt.items() if key != "generated_at_utc"
    }
    if canonical_sha256(comparable_actual) != canonical_sha256(
        comparable_rebuilt
    ):
        raise ValueError("runtime_scorecard_rebuild_mismatch")
    if sha256_file(scorecard_path) != scorecard_sha256:
        raise ValueError("runtime_scorecard_changed_during_validation")


def overlay_multiple_testing_evidence(
    base: dict[str, Any],
    gate_path: Path,
    *,
    expected_gate_sha256: str,
    contract_path: Path,
    experiment_ledger_path: Path,
    return_matrix_path: Path,
    promotion_state_snapshot_path: Path,
    repository_root: Path,
    current_promotion_state: dict[str, Any],
) -> dict[str, Any]:
    """Overlay one exact, reviewed, fail-closed multiple-testing result.

    The tracked evidence bit is never trusted directly.  The caller must pin the
    exact gate SHA, and the complete five-file bundle is revalidated before the
    runtime-owned ``multiple_testing_pass`` check can become true.
    """
    evidence = copy.deepcopy(base)
    historical = evidence.setdefault("historical", {})
    historical["multiple_testing_pass"] = False
    expected = str(expected_gate_sha256 or "").strip().lower()
    if not _valid_sha256(expected):
        raise ValueError("multiple_testing_gate_expected_sha256_invalid")
    gate_path = gate_path.resolve()
    if not gate_path.is_file() or gate_path.is_symlink():
        raise ValueError("multiple_testing_gate_missing_or_not_plain_file")
    actual_gate_sha256 = sha256_file(gate_path)
    if actual_gate_sha256 != expected:
        raise ValueError("multiple_testing_gate_sha256_mismatch")

    bundle = gate_path.parent
    expected_files = {
        "source_manifest.json",
        "multiple_testing_gate.json",
        "cscv_splits.csv",
        "white_reality_check.json",
        "report.md",
    }
    if bundle.is_symlink() or {
        path.name for path in bundle.iterdir()
    } != expected_files:
        raise ValueError("multiple_testing_bundle_file_set_invalid")
    for name in expected_files:
        path = bundle / name
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"multiple_testing_bundle_file_invalid:{name}")

    gate = read_json(gate_path)
    if gate.get("schema_version") != MULTIPLE_TESTING_GATE_SCHEMA:
        raise ValueError("multiple_testing_gate_schema_invalid")
    if gate.get("contract_version") != MULTIPLE_TESTING_CONTRACT_VERSION:
        raise ValueError("multiple_testing_gate_contract_version_invalid")
    if gate.get("status") != "PASS" or gate.get("passed") is not True:
        raise ValueError("multiple_testing_gate_not_passed")
    candidate_id = str(gate.get("candidate_id") or "")
    if not candidate_id or candidate_id != str(evidence.get("candidate_id") or ""):
        raise ValueError("multiple_testing_gate_candidate_mismatch")
    if current_promotion_state.get("schema_version") != STATE_SCHEMA:
        raise ValueError("multiple_testing_current_promotion_state_invalid")
    current_canonical_champion = current_promotion_state.get(
        "canonical_champion"
    )
    if (
        not isinstance(current_canonical_champion, dict)
        or gate.get("canonical_champion") != current_canonical_champion
        or gate.get("champion_id")
        != current_canonical_champion.get("policy_id")
    ):
        raise ValueError("multiple_testing_gate_canonical_champion_mismatch")
    selected_trial_id = str(gate.get("selected_trial_id") or "")
    if (
        not selected_trial_id
        or gate.get("reproduced_selected_trial_id") != selected_trial_id
    ):
        raise ValueError("multiple_testing_gate_selected_trial_invalid")
    advanced_state = (
        current_promotion_state.get("promotion_state") != "RESEARCH_ONLY"
    )
    official_challenger = current_promotion_state.get(
        "official_challenger"
    )
    if advanced_state:
        required_official_identity = {
            "candidate_id": candidate_id,
            "causal_family_id": gate.get("causal_family_id"),
            "selected_trial_id": selected_trial_id,
            "multiple_testing_gate_sha256": actual_gate_sha256,
        }
        if (
            not isinstance(official_challenger, dict)
            or any(
                not isinstance(official_challenger.get(field), str)
                or not official_challenger[field]
                for field in required_official_identity
            )
            or any(
                official_challenger.get(field) != expected_value
                for field, expected_value
                in required_official_identity.items()
            )
        ):
            raise ValueError(
                "multiple_testing_gate_official_challenger_mismatch"
            )
    if gate.get("thresholds") != MULTIPLE_TESTING_THRESHOLDS:
        raise ValueError("multiple_testing_gate_thresholds_invalid")
    checks = gate.get("checks")
    if (
        not isinstance(checks, dict)
        or set(checks) != set(MULTIPLE_TESTING_REQUIRED_CHECKS)
        or any(checks.get(field) is not True for field in MULTIPLE_TESTING_REQUIRED_CHECKS)
    ):
        raise ValueError("multiple_testing_gate_checks_invalid")
    if gate.get("blockers") != []:
        raise ValueError("multiple_testing_gate_blockers_not_empty")
    if gate.get("safety") != MULTIPLE_TESTING_SAFETY:
        raise ValueError("multiple_testing_gate_safety_invalid")
    _require_false_flags(
        gate,
        (
            "automatic_promotion_performed",
            "champion_changed",
            "fullrun_executed",
        ),
        "multiple_testing_gate",
    )
    preregistration = gate.get("preregistration")
    if (
        not isinstance(preregistration, dict)
        or not _valid_commit_sha(
            preregistration.get("registration_commit_sha")
        )
        or not str(preregistration.get("path") or "").endswith(".json")
        or not _valid_sha256(preregistration.get("sha256"))
        or preregistration.get("registered_before_evaluation") is not True
        or preregistration.get("do_not_repeat_conflict_absent") is not True
    ):
        raise ValueError("multiple_testing_gate_preregistration_invalid")
    evaluation_snapshot = gate.get("evaluation_snapshot")
    if (
        not isinstance(evaluation_snapshot, dict)
        or not _valid_commit_sha(
            evaluation_snapshot.get("evaluation_commit_sha")
        )
        or not str(evaluation_snapshot.get("path") or "").endswith(".json")
        or not _valid_sha256(evaluation_snapshot.get("sha256"))
        or evaluation_snapshot.get("registration_commit_sha")
        != preregistration.get("registration_commit_sha")
        or not _valid_sha256(
            evaluation_snapshot.get("promotion_state_sha256")
        )
        or evaluation_snapshot.get("results_present") is not False
    ):
        raise ValueError("multiple_testing_gate_evaluation_snapshot_invalid")

    sample = gate.get("sample")
    if not isinstance(sample, dict):
        raise ValueError("multiple_testing_gate_sample_missing")
    trial_count = _integer(sample.get("trial_count"), "multiple_testing_trial_count")
    observation_count = _integer(
        sample.get("observation_count"),
        "multiple_testing_observation_count",
    )
    if trial_count < MULTIPLE_TESTING_THRESHOLDS["minimum_trials"]:
        raise ValueError("multiple_testing_gate_trial_count_under_threshold")
    active_trial_count = _integer(
        sample.get("active_trial_count"),
        "multiple_testing_active_trial_count",
    )
    prior_trial_count = _integer(
        sample.get("prior_performance_evaluated_trial_count"),
        "multiple_testing_prior_trial_count",
    )
    family_count = _integer(
        sample.get("performance_evaluated_family_count"),
        "multiple_testing_family_count",
    )
    if (
        active_trial_count <= 0
        or prior_trial_count
        < MULTIPLE_TESTING_MINIMUM_PRIOR_PERFORMANCE_TRIALS
        or active_trial_count + prior_trial_count != trial_count
        or family_count < 2
    ):
        raise ValueError(
            "multiple_testing_gate_cross_family_population_invalid"
        )
    if (
        observation_count
        < MULTIPLE_TESTING_THRESHOLDS["minimum_synchronous_observations"]
        or observation_count
        % MULTIPLE_TESTING_THRESHOLDS["cscv_contiguous_blocks"]
    ):
        raise ValueError("multiple_testing_gate_observation_count_invalid")
    if not sample.get("first_date") or not sample.get("last_date"):
        raise ValueError("multiple_testing_gate_date_range_missing")

    deflated = gate.get("deflated_sharpe")
    if (
        not isinstance(deflated, dict)
        or deflated.get("status") != "PASS"
        or deflated.get("passed") is not True
        or deflated.get("minimum_probability")
        != MULTIPLE_TESTING_THRESHOLDS[
            "deflated_sharpe_probability_minimum"
        ]
    ):
        raise ValueError("multiple_testing_gate_dsr_not_passed")
    if deflated.get("selected_trial_id") != selected_trial_id:
        raise ValueError("multiple_testing_gate_dsr_trial_mismatch")
    dsr_probability = _finite_float(
        deflated.get("probability"),
        "multiple_testing_gate_dsr_probability",
    )
    if not (
        MULTIPLE_TESTING_THRESHOLDS[
            "deflated_sharpe_probability_minimum"
        ]
        <= dsr_probability
        <= 1.0
    ):
        raise ValueError("multiple_testing_gate_dsr_probability_invalid")

    pbo = gate.get("probability_of_backtest_overfitting")
    if (
        not isinstance(pbo, dict)
        or pbo.get("status") != "PASS"
        or pbo.get("passed") is not True
        or pbo.get("maximum_probability")
        != MULTIPLE_TESTING_THRESHOLDS[
            "probability_of_backtest_overfitting_maximum"
        ]
    ):
        raise ValueError("multiple_testing_gate_pbo_not_passed")
    pbo_probability = _finite_float(
        pbo.get("probability"),
        "multiple_testing_gate_pbo_probability",
    )
    if not (
        0.0
        <= pbo_probability
        <= MULTIPLE_TESTING_THRESHOLDS[
            "probability_of_backtest_overfitting_maximum"
        ]
    ):
        raise ValueError("multiple_testing_gate_pbo_probability_invalid")
    if _integer(pbo.get("split_count"), "multiple_testing_pbo_split_count") != 70:
        raise ValueError("multiple_testing_gate_pbo_split_count_invalid")
    block_sizes = pbo.get("block_sizes")
    if (
        not isinstance(block_sizes, list)
        or len(block_sizes)
        != MULTIPLE_TESTING_THRESHOLDS["cscv_contiguous_blocks"]
        or any(
            _integer(value, "multiple_testing_cscv_block_size")
            != observation_count
            // MULTIPLE_TESTING_THRESHOLDS["cscv_contiguous_blocks"]
            for value in block_sizes
        )
    ):
        raise ValueError("multiple_testing_gate_cscv_block_sizes_invalid")

    artifact_hashes = gate.get("artifact_hashes")
    if (
        not isinstance(artifact_hashes, dict)
        or set(artifact_hashes)
        != {
            "source_manifest.json",
            "cscv_splits.csv",
            "white_reality_check.json",
            "report.md",
        }
    ):
        raise ValueError("multiple_testing_gate_artifact_hashes_invalid")
    observed_hashes: dict[str, str] = {
        "multiple_testing_gate.json": actual_gate_sha256
    }
    for name, expected_artifact_sha256 in artifact_hashes.items():
        if not _valid_sha256(expected_artifact_sha256):
            raise ValueError(f"multiple_testing_artifact_sha256_invalid:{name}")
        observed = sha256_file(bundle / name)
        if observed != str(expected_artifact_sha256).lower():
            raise ValueError(f"multiple_testing_artifact_sha256_mismatch:{name}")
        observed_hashes[name] = observed
    if gate.get("source_manifest_sha256") != observed_hashes["source_manifest.json"]:
        raise ValueError("multiple_testing_source_manifest_anchor_mismatch")

    source_manifest = read_json(bundle / "source_manifest.json")
    if (
        source_manifest.get("schema_version")
        != MULTIPLE_TESTING_SOURCE_MANIFEST_SCHEMA
        or source_manifest.get("contract_version")
        != MULTIPLE_TESTING_CONTRACT_VERSION
    ):
        raise ValueError("multiple_testing_source_manifest_schema_invalid")
    if (
        source_manifest.get("candidate_id") != candidate_id
        or source_manifest.get("champion_id") != gate.get("champion_id")
        or source_manifest.get("selected_trial_id") != selected_trial_id
        or source_manifest.get("causal_family_id") != gate.get("causal_family_id")
    ):
        raise ValueError("multiple_testing_source_manifest_identity_mismatch")
    if source_manifest.get("return_semantics") != (
        "daily_arithmetic_excess_return_vs_canonical_champion_after_costs"
    ):
        raise ValueError("multiple_testing_source_manifest_return_semantics_invalid")
    if source_manifest.get("wall_clock_fields_present") is not False:
        raise ValueError("multiple_testing_source_manifest_wall_clock_invalid")
    inputs = source_manifest.get("inputs")
    if not isinstance(inputs, dict) or set(inputs) != {
        "contract",
        "experiment_ledger",
        "promotion_state",
        "preregistration",
        "evaluation_snapshot",
        "registration_registry_snapshot",
        "evaluation_registry_snapshot",
        "return_matrix",
    }:
        raise ValueError("multiple_testing_source_manifest_inputs_invalid")
    input_hashes: dict[str, str] = {}
    for input_id, record in inputs.items():
        if (
            not isinstance(record, dict)
            or not record.get("path")
            or not _valid_sha256(record.get("sha256"))
            or _integer(record.get("bytes"), f"multiple_testing_input_bytes:{input_id}")
            <= 0
        ):
            raise ValueError(f"multiple_testing_source_input_invalid:{input_id}")
        input_hashes[input_id] = str(record["sha256"]).lower()
    computed_input_set_sha256 = hashlib.sha256(
        _canonical_json_bytes_with_newline(input_hashes)
    ).hexdigest()
    if (
        source_manifest.get("input_set_sha256") != computed_input_set_sha256
        or gate.get("input_set_sha256") != computed_input_set_sha256
    ):
        raise ValueError("multiple_testing_input_set_sha256_mismatch")

    supplied_inputs = {
        "contract": contract_path.resolve(),
        "experiment_ledger": experiment_ledger_path.resolve(),
        "promotion_state": promotion_state_snapshot_path.resolve(),
        "return_matrix": return_matrix_path.resolve(),
    }
    for input_id, path in supplied_inputs.items():
        if not path.is_file() or path.is_symlink():
            raise ValueError(
                f"multiple_testing_recompute_input_invalid:{input_id}"
            )
        if sha256_file(path) != input_hashes[input_id]:
            raise ValueError(
                f"multiple_testing_recompute_input_sha256_mismatch:{input_id}"
            )

    try:
        from run_run287_multiple_testing_gate import (
            evaluate as recompute_multiple_testing_gate,
        )
    except ModuleNotFoundError as exc:
        raise ValueError(
            "multiple_testing_recompute_module_unavailable"
        ) from exc
    with tempfile.TemporaryDirectory() as temporary:
        recomputed_output = (
            Path(temporary) / "run287_multiple_testing_gate"
        )
        recomputed = recompute_multiple_testing_gate(
            contract_path=supplied_inputs["contract"],
            experiment_ledger_path=supplied_inputs["experiment_ledger"],
            return_matrix_path=supplied_inputs["return_matrix"],
            promotion_state_path=supplied_inputs["promotion_state"],
            repository_root=repository_root.resolve(),
            output_dir=recomputed_output,
        )
        if recomputed.get("passed") is not True:
            raise ValueError("multiple_testing_recompute_not_passed")
        for name in expected_files:
            if (recomputed_output / name).read_bytes() != (
                bundle / name
            ).read_bytes():
                raise ValueError(
                    f"multiple_testing_recompute_bundle_mismatch:{name}"
                )

    cscv_path = bundle / "cscv_splits.csv"
    with cscv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        expected_cscv_columns = {
            "split_id",
            "in_sample_blocks",
            "out_of_sample_blocks",
            "selected_trial_id",
            "in_sample_sharpe",
            "selected_out_of_sample_sharpe",
            "selected_out_of_sample_rank",
            "rank_fraction",
            "logit",
            "overfit",
        }
        if set(reader.fieldnames or []) != expected_cscv_columns:
            raise ValueError("multiple_testing_cscv_columns_invalid")
        cscv_rows = list(reader)
    if (
        len(cscv_rows) != 70
        or {
            _integer(row.get("split_id"), "multiple_testing_cscv_split_id")
            for row in cscv_rows
        }
        != set(range(1, 71))
        or any(row.get("overfit") not in {"true", "false"} for row in cscv_rows)
    ):
        raise ValueError("multiple_testing_cscv_rows_invalid")
    observed_overfit_count = sum(
        row.get("overfit") == "true" for row in cscv_rows
    )
    if (
        _integer(
            pbo.get("overfit_split_count"),
            "multiple_testing_pbo_overfit_split_count",
        )
        != observed_overfit_count
        or not math.isclose(
            pbo_probability,
            observed_overfit_count / 70.0,
            rel_tol=0.0,
            abs_tol=1e-15,
        )
    ):
        raise ValueError("multiple_testing_pbo_split_summary_mismatch")

    white_summary = gate.get("white_reality_check")
    white = read_json(bundle / "white_reality_check.json")
    if (
        not isinstance(white_summary, dict)
        or white_summary.get("status") != "PASS"
        or white_summary.get("passed") is not True
        or white_summary.get("artifact") != "white_reality_check.json"
        or white.get("schema_version") != "run287-white-reality-check-v1"
        or white.get("status") != "PASS"
        or white.get("passed") is not True
        or white.get("all_block_lengths_must_pass") is not True
    ):
        raise ValueError("multiple_testing_white_reality_check_invalid")
    white_results = white.get("results")
    expected_block_lengths = MULTIPLE_TESTING_THRESHOLDS[
        "bootstrap_block_lengths"
    ]
    if not isinstance(white_results, list) or [
        row.get("block_length") if isinstance(row, dict) else None
        for row in white_results
    ] != expected_block_lengths:
        raise ValueError("multiple_testing_white_block_lengths_invalid")
    for row in white_results:
        block_length = _integer(
            row.get("block_length"),
            "multiple_testing_white_block_length",
        )
        p_value = _finite_float(
            row.get("p_value"),
            "multiple_testing_white_p_value",
        )
        exceedance_count = _integer(
            row.get("exceedance_count"),
            "multiple_testing_white_exceedance_count",
        )
        if (
            row.get("passed") is not True
            or _integer(
                row.get("bootstrap_repetitions"),
                "multiple_testing_white_repetitions",
            )
            != MULTIPLE_TESTING_THRESHOLDS["bootstrap_repetitions"]
            or _integer(
                row.get("random_seed"),
                "multiple_testing_white_random_seed",
            )
            != MULTIPLE_TESTING_THRESHOLDS["bootstrap_random_seed"]
            + block_length
            or exceedance_count
            > MULTIPLE_TESTING_THRESHOLDS["bootstrap_repetitions"]
            or not math.isclose(
                p_value,
                (exceedance_count + 1.0)
                / (
                    MULTIPLE_TESTING_THRESHOLDS[
                        "bootstrap_repetitions"
                    ]
                    + 1.0
                ),
                rel_tol=0.0,
                abs_tol=1e-15,
            )
            or not (
                0.0
                <= p_value
                <= MULTIPLE_TESTING_THRESHOLDS[
                    "white_reality_check_p_value_maximum"
                ]
            )
        ):
            raise ValueError("multiple_testing_white_result_invalid")

    for name, observed in observed_hashes.items():
        if sha256_file(bundle / name) != observed:
            raise ValueError(f"multiple_testing_artifact_changed_during_validation:{name}")
    if sha256_file(gate_path) != expected:
        raise ValueError("multiple_testing_gate_changed_during_validation")

    historical["multiple_testing_pass"] = True
    limitation = (
        "No runtime-verified multiple-testing gate evidence is available."
    )
    limitations = [
        str(value)
        for value in historical.get("limitations") or []
        if str(value) != limitation
    ]
    historical["limitations"] = limitations
    evidence["multiple_testing_gate_observation"] = {
        "candidate_id": candidate_id,
        "selected_trial_id": selected_trial_id,
        "causal_family_id": gate.get("causal_family_id"),
        "gate_sha256": actual_gate_sha256,
        "artifact_hashes": {
            key: observed_hashes[key] for key in sorted(observed_hashes)
        },
        "input_set_sha256": computed_input_set_sha256,
        "automatic_promotion_performed": False,
        "champion_changed": False,
        "fullrun_executed": False,
    }
    return evidence


def overlay_latest_run_evidence(
    base: dict[str, Any],
    latest_run: Path,
    *,
    expected_risk_outcome_parent_anchor_sha256: str = "",
) -> dict[str, Any]:
    """Overlay only directly verifiable forward observations from a restored run.

    Missing runtime fields never manufacture a pass.  The tracked preregistered
    packet supplies fixed thresholds and unresolved defaults.  Runtime evidence
    may replace only the explicitly runtime-owned ``scorecard_trusted`` check
    and forward counts; every other historical gate remains preregistered.
    """
    evidence = copy.deepcopy(base)
    evidence.setdefault("historical", {})["scorecard_trusted"] = False
    forward = evidence.setdefault("forward_paper", {})
    for field in RUNTIME_COUNT_FIELDS:
        forward[field] = 0
    for field in RUNTIME_EVALUABILITY_FIELDS:
        forward[field] = False
    # A missing runtime measurement must fail the zero-integrity gate.  A
    # hash-bound observation below may mark the field VERIFIED, including when
    # its measured count is zero.
    for field in RUNTIME_INTEGRITY_FIELDS:
        forward[field] = 0
    forward["integrity_availability"] = {
        field: "UNAVAILABLE" for field in RUNTIME_INTEGRITY_FIELDS
    }
    accounts = evidence.setdefault("accounts", {})
    accounts["paired_decision_date_count"] = 0
    accounts["runtime_pair_verified"] = False
    evidence.setdefault("runtime_limitations", []).append(
        "runtime_official_challenger_and_evaluability_not_verified"
    )
    paper_root = latest_run / "daily_simulated_fill_ledger"
    if not paper_root.is_dir():
        evidence.setdefault("runtime_limitations", []).append(
            "runtime_paper_snapshot_missing"
        )
        return evidence
    observed_files: dict[str, str] = {}
    raw_session_sets: list[set[str]] = []
    equity_rows_by_portfolio: dict[str, list[dict[str, Any]]] = {}
    negative_cash = 0
    duplicate_ids = 0
    all_resolved_client_ids: list[str] = []
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
    manifest_count_occurrences = {field: 0 for field in manifest_counts}
    for portfolio in PORTFOLIOS:
        equity_path = paper_root / portfolio / "equity_curve.csv"
        fill_path = paper_root / portfolio / "fills.csv"
        rejection_path = paper_root / portfolio / "rejections.csv"
        manifest_path = paper_root / portfolio / "manifest.json"
        rows = _csv_rows(equity_path)
        equity_rows_by_portfolio[portfolio] = rows
        dates = {str(row.get("date") or "") for row in rows if row.get("date")}
        raw_session_sets.append(dates)
        negative_cash += sum(float(row.get("cash_usd") or 0) < -1e-8 for row in rows)
        fills = _csv_rows(fill_path)
        rejections = _csv_rows(rejection_path)
        ids = [
            str(row.get("client_order_id") or "")
            for row in fills + rejections
            if row.get("client_order_id")
        ]
        all_resolved_client_ids.extend(ids)
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
                    manifest_count_occurrences[field] += 1
                    manifest_counts[field] += _integer(
                        integrity.get(field, manifest.get(field, 0)), field
                    )
        for path in (equity_path, fill_path, manifest_path):
            if path.is_file():
                observed_files[path.relative_to(latest_run).as_posix()] = sha256_file(path)
    duplicate_ids = max(
        0, len(all_resolved_client_ids) - len(set(all_resolved_client_ids))
    )
    raw_common_sessions = (
        set.intersection(*raw_session_sets)
        if raw_session_sets
        else set()
    )
    common_sessions: set[str] = set()
    weeks: set[str] = set()
    replay_sessions: set[str] = set()
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
    summary_reported_counts = {
        field: _integer(
            summary_integrity.get(field, summary.get(field)),
            f"paper_summary.{field}",
        )
        for field in manifest_counts
        if field in summary_integrity or field in summary
    }

    integrity_path = paper_root / "snapshot_integrity.json"
    verified_paper_manifest: dict[str, Any] | None = None
    if integrity_path.is_file():
        observed_files[integrity_path.relative_to(latest_run).as_posix()] = sha256_file(integrity_path)
        try:
            try:
                from tools.run287_paper_ledger_integrity import (
                    verified_replay_price_evidence_sessions,
                    verify_integrity_manifest,
                )
            except ModuleNotFoundError:
                from run287_paper_ledger_integrity import (
                    verified_replay_price_evidence_sessions,
                    verify_integrity_manifest,
                )
            candidate_manifest = verify_integrity_manifest(paper_root, require=True)
            derived_integrity = _validate_verified_paper_snapshot(
                paper_root, candidate_manifest
            )
            replay_sessions = set(
                verified_replay_price_evidence_sessions(paper_root)
            )
            eligible_session_sets = [
                {
                    str(row.get("date") or "")
                    for row in equity_rows_by_portfolio[portfolio]
                    if str(row.get("record_type") or "")
                    == "FORWARD_MARK"
                    and str(row.get("date") or "")
                    not in replay_sessions
                }
                for portfolio in PORTFOLIOS
            ]
            common_sessions = (
                set.intersection(*eligible_session_sets)
                if eligible_session_sets
                else set()
            )
            for value in common_sessions:
                parsed = date.fromisoformat(value)
                iso = parsed.isocalendar()
                weeks.add(f"{iso.year:04d}-W{iso.week:02d}")
            rebound_manifest = verify_integrity_manifest(paper_root, require=True)
            if rebound_manifest != candidate_manifest:
                raise ValueError("runtime_paper_snapshot_changed_during_validation")
            verified_paper_manifest = candidate_manifest
            forward["completed_market_sessions"] = len(common_sessions)
            observed_counts.update(derived_integrity)
            observed_counts["hash_chain_break_count"] = 0
            for field in RUNTIME_INTEGRITY_FIELDS:
                if 0 < manifest_count_occurrences[field] < len(PORTFOLIOS):
                    raise ValueError(
                        f"runtime_integrity_manifest_partial_reporting:{field}"
                    )
                manifest_complete = (
                    manifest_count_occurrences[field] == len(PORTFOLIOS)
                )
                if (
                    manifest_complete
                    and field in summary_reported_counts
                    and manifest_counts[field] != summary_reported_counts[field]
                ):
                    raise ValueError(
                        f"runtime_integrity_manifest_summary_mismatch:{field}"
                    )
                reported_values = []
                if manifest_complete:
                    reported_values.append(manifest_counts[field])
                if field in summary_reported_counts:
                    reported_values.append(summary_reported_counts[field])
                if field in observed_counts:
                    if any(
                        value != observed_counts[field]
                        for value in reported_values
                    ):
                        raise ValueError(
                            f"runtime_integrity_reported_observed_mismatch:{field}"
                        )
                    forward[field] = observed_counts[field]
                    forward["integrity_availability"][field] = "VERIFIED"
                else:
                    evidence.setdefault("runtime_limitations", []).append(
                        f"runtime_integrity_measurement_unavailable:{field}"
                    )
        except Exception as exc:
            evidence.setdefault("rollback", {})["integrity_error"] = True
            evidence.setdefault("runtime_limitations", []).append(f"paper_snapshot_integrity_failed:{exc}")
    elif evidence.get("candidate_id"):
        evidence.setdefault("rollback", {})["integrity_error"] = True
        evidence.setdefault("runtime_limitations", []).append("paper_snapshot_integrity_missing_for_challenger")

    scorecard_path = latest_run / "run287_operating_scorecard" / "operating_scorecard.json"
    if scorecard_path.is_file():
        scorecard_sha256 = sha256_file(scorecard_path)
        observed_files[scorecard_path.relative_to(latest_run).as_posix()] = scorecard_sha256
        scorecard = read_json(scorecard_path)
        try:
            if not verified_paper_manifest:
                raise ValueError("runtime_scorecard_paper_snapshot_unverified")
            _validate_runtime_scorecard(
                scorecard=scorecard,
                scorecard_path=scorecard_path,
                scorecard_sha256=scorecard_sha256,
                latest_run=latest_run,
                verified_paper_manifest=verified_paper_manifest,
                integrity_path=integrity_path,
                observed_files=observed_files,
            )
            evidence["historical"]["scorecard_trusted"] = True
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            evidence.setdefault("runtime_limitations", []).append(
                f"runtime_scorecard_validation_failed:{exc}"
            )
    else:
        evidence.setdefault("runtime_limitations", []).append(
            "runtime_scorecard_missing"
        )

    outcome_path = latest_run / "run287_risk_outcome_archive" / "summary.json"
    if outcome_path.is_file():
        outcome_summary_sha256 = sha256_file(outcome_path)
        observed_files[
            outcome_path.relative_to(latest_run).as_posix()
        ] = outcome_summary_sha256
        outcome = read_json(outcome_path)
        try:
            if not verified_paper_manifest:
                raise ValueError("runtime_risk_outcome_paper_snapshot_unverified")
            parent_anchor_path = (
                latest_run
                / "run287_risk_outcome_parent_anchor"
                / "anchor.json"
            )
            outcome_counts = _validated_risk_outcome_counts(
                outcome=outcome,
                latest_run=latest_run,
                paper_as_of_date=str(verified_paper_manifest.get("as_of_date") or ""),
                observed_files=observed_files,
                expected_summary_sha256=outcome_summary_sha256,
                expected_parent_anchor_sha256=(
                    expected_risk_outcome_parent_anchor_sha256
                    or (
                        sha256_file(parent_anchor_path)
                        if parent_anchor_path.is_file()
                        else ""
                    )
                ),
            )
            forward.update(outcome_counts)
            quarantined_signal_count = int(
                outcome_counts.get(
                    "quarantined_signal_observation_count", 0
                )
            )
            if quarantined_signal_count:
                evidence.setdefault("runtime_limitations", []).append(
                    "runtime_risk_outcome_quarantined_signal_observations:"
                    f"{quarantined_signal_count}"
                )
            if (
                outcome_counts.get("parent_acceptance_status")
                == "QUARANTINED_LEGACY"
            ):
                evidence.setdefault("runtime_limitations", []).append(
                    "runtime_risk_outcome_parent_legacy_quarantined"
                )
            late_signal_count = int(
                outcome_counts.get(
                    "promotion_ineligible_late_signal_count", 0
                )
            )
            if late_signal_count:
                evidence.setdefault("runtime_limitations", []).append(
                    "runtime_risk_outcome_late_signal_backfill_excluded:"
                    f"{late_signal_count}"
                )
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            if any(
                token in str(exc)
                for token in (
                    "runtime_risk_outcome_parent_anchor",
                    "runtime_risk_outcome_parent_",
                    "runtime_risk_outcome_chain_",
                    "runtime_risk_outcome_event_prefix_rewrite",
                )
            ):
                evidence.setdefault("rollback", {})["integrity_error"] = True
            evidence.setdefault("runtime_limitations", []).append(
                f"runtime_risk_outcome_validation_failed:{exc}"
            )
    else:
        evidence.setdefault("runtime_limitations", []).append(
            "runtime_risk_outcome_summary_missing"
        )
    evidence["latest_run_observation"] = {
        "latest_run": str(latest_run),
        "observed_file_hashes": observed_files,
        "completed_market_sessions": len(common_sessions),
        "distinct_decision_weeks": len(weeks),
        "raw_common_equity_dates": len(raw_common_sessions),
        "replay_sessions_excluded": len(
            raw_common_sessions & replay_sessions
        ),
        "non_forward_equity_dates_excluded": len(
            raw_common_sessions
            - common_sessions
            - replay_sessions
        ),
        "session_eligibility_rule": (
            "PAIRED_FORWARD_MARK_AND_NOT_DURABLE_REPLAY_SESSION"
        ),
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
    gate_contract = contract
    if contract_errors:
        gate_contract = {
            **contract,
            "states": list(CANONICAL_STATES),
            "forward_thresholds": copy.deepcopy(CANONICAL_FORWARD_THRESHOLDS),
            "required_zero_integrity_fields": list(RUNTIME_INTEGRITY_FIELDS),
            "required_historical_checks": list(CANONICAL_HISTORICAL_CHECKS),
            "rollback_triggers": list(CANONICAL_ROLLBACK_TRIGGERS),
            "rules": copy.deepcopy(CANONICAL_RULES),
        }
    state_errors = (
        validate_state(state, gate_contract)
        if not contract_errors
        else ["state_not_evaluated"]
    )
    historical = evidence.get("historical") or {}
    historical_checks = {
        field: historical.get(field) is True
        for field in gate_contract.get("required_historical_checks") or []
    }
    historical_blockers = sorted(field for field, passed in historical_checks.items() if not passed)
    historical_pass = bool(historical_checks) and not historical_blockers

    account_pair = validate_account_pair(evidence)
    account_integrity_issues = [
        issue for issue in account_pair["issues"]
        if "collision" in issue or "mismatch" in issue
    ]

    forward = evidence.get("forward_paper") or {}
    thresholds = gate_contract.get("forward_thresholds") or {}
    integrity_availability = forward.get("integrity_availability") or {}
    zero_checks: dict[str, bool] = {}
    measured_integrity: dict[str, int] = {}
    for field in gate_contract.get("required_zero_integrity_fields") or []:
        measured_integrity[field] = _integer(forward.get(field, 0), field)
        zero_checks[field] = (
            integrity_availability.get(field) == "VERIFIED"
            and measured_integrity[field] == 0
        )
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
            maximum = (
                "PRODUCTION_CANDIDATE_USER_APPROVAL_REQUIRED"
                if forward_ready
                else "FORWARD_PAPER_VALIDATING"
            )
        else:
            maximum = "SHADOW_OPERATION_READY"
    else:
        maximum = "RESEARCH_ONLY"

    rollback = evidence.get("rollback") or {}
    active_rollbacks = sorted(
        field
        for field in gate_contract.get("rollback_triggers") or []
        if rollback.get(field) is True
    )
    active_rollbacks.extend(
        f"forward_integrity:{field}"
        for field, value in measured_integrity.items()
        if integrity_availability.get(field) == "VERIFIED" and value > 0
    )
    active_rollbacks.extend(f"account_integrity:{item}" for item in account_integrity_issues)
    if contract_errors:
        active_rollbacks.extend(f"contract:{item}" for item in contract_errors)
    if state_errors:
        active_rollbacks.extend(f"state:{item}" for item in state_errors)
    current = str(state.get("promotion_state") or "RESEARCH_ONLY")
    if current not in {"RESEARCH_ONLY", "BLOCKED_OR_ROLLED_BACK"} and not historical_pass:
        active_rollbacks.append("advanced_state_historical_gate_regression")
    forward_states = list(CANONICAL_STATES[:-1])
    if (
        current in forward_states
        and maximum in forward_states
        and forward_states.index(current) > forward_states.index(maximum)
    ):
        active_rollbacks.append("advanced_state_evidence_gate_regression")
    active_rollbacks = sorted(set(active_rollbacks))
    effective = "BLOCKED_OR_ROLLED_BACK" if active_rollbacks else current

    hashes = source_hashes or {}
    transition = _transition_request(
        current,
        maximum,
        requested_state,
        gate_contract,
        transition_authorization,
        hashes.get("evidence_sha256", ""),
    )
    state_unchanged = effective == current
    limitations = list(historical.get("limitations") or [])
    limitations.extend(
        ["63-session outcome evidence is UNDERPOWERED until the fixed minimum is actually resolved."]
        if outcome_63d_status == "UNDERPOWERED" else []
    )
    runtime_limitations = sorted(
        {
            str(value)
            for value in evidence.get("runtime_limitations") or []
            if str(value)
        }
    )
    latest_run_observation = evidence.get("latest_run_observation") or {}
    runtime_observed_file_hashes = latest_run_observation.get(
        "observed_file_hashes"
    ) or {}
    if not isinstance(runtime_observed_file_hashes, dict):
        runtime_observed_file_hashes = {}
    return {
        "schema_version": GATE_SCHEMA,
        "contract_version": contract.get("contract_version"),
        "source_hashes": hashes,
        "runtime_evidence_limitations": runtime_limitations,
        "runtime_observed_file_hashes": {
            str(path): str(digest)
            for path, digest in sorted(runtime_observed_file_hashes.items())
        },
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
            "integrity_availability": {
                field: str(integrity_availability.get(field) or "UNAVAILABLE")
                for field in zero_checks
            },
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
