#!/usr/bin/env python3
"""Evaluate Run287 multiple-testing evidence without changing the champion.

The gate consumes a complete parameter-trial ledger and a synchronized matrix
of daily after-cost excess returns versus the canonical champion.  It applies
Deflated Sharpe, CSCV/PBO, and a circular-block White Reality Check.  Missing,
partial, mutable, or non-preregistered evidence fails closed.

This tool never runs a backtest or fullrun and never mutates portfolio, target,
order, paper-ledger, production, or live-trading state.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import itertools
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
import pandas_market_calendars as mcal
from scipy.stats import kurtosis, norm, rankdata, skew


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONTRACT = ROOT / "docs" / "run287_multiple_testing_gate_contract.json"
DEFAULT_PROMOTION_STATE = ROOT / "data_static" / "run287_promotion_state.json"
GATE_SCHEMA = "run287-multiple-testing-gate-v1"
SOURCE_MANIFEST_SCHEMA = "run287-multiple-testing-source-manifest-v1"
LEDGER_SCHEMA = "run287-complete-experiment-ledger-v1"
PREREGISTRATION_SCHEMA = "run287-experiment-preregistration-v1"
EVALUATION_SNAPSHOT_SCHEMA = "run287-experiment-evaluation-snapshot-v1"
PROMOTION_STATE_SCHEMA = "run287-promotion-state-v1"
CANONICAL_DO_NOT_REPEAT_REGISTRY_PATH = (
    "docs/run287_do_not_repeat_registry.json"
)
CONTRACT_SCHEMA = "run287-multiple-testing-gate-contract-v1"
CONTRACT_VERSION = "2026-07-27.1"
EULER_MASCHERONI = 0.5772156649015329

CANONICAL_INPUT_CONTRACT = {
    "experiment_ledger_schema_version": LEDGER_SCHEMA,
    "preregistration_schema_version": PREREGISTRATION_SCHEMA,
    "evaluation_snapshot_schema_version": EVALUATION_SNAPSHOT_SCHEMA,
    "git_anchored_preregistration_required": True,
    "preregistration_commit_must_strictly_precede_evaluation_snapshot": True,
    "evaluation_snapshot_must_precede_or_equal_evaluation_head": True,
    "preregistered_trial_set_must_exactly_match_ledger": True,
    "canonical_promotion_state_champion_binding_required": True,
    "canonical_do_not_repeat_registry_path": (
        CANONICAL_DO_NOT_REPEAT_REGISTRY_PATH
    ),
    "canonical_registry_history_preservation_required": True,
    "return_matrix_format": "csv",
    "date_column": "date",
    "return_semantics": (
        "daily_arithmetic_excess_return_vs_canonical_champion_after_costs"
    ),
    "exact_return_column_set_required": True,
    "strictly_increasing_unique_dates_required": True,
    "exact_contiguous_nyse_sessions_required": True,
    "finite_complete_matrix_required": True,
    "ledger_binds_return_matrix_sha256": True,
    "costs_included_required": True,
    "complete_attempt_history_required": True,
    "exactly_one_causal_family_required": True,
    "all_performance_trials_preregistered": True,
    "selection_metric": "daily_sharpe",
    "selected_trial_must_be_reproducible": True,
    "parameter_set_hash": "sha256_of_canonical_json",
    "duplicate_parameter_sets_allowed": False,
    "equal_size_cscv_blocks_required": True,
}
CANONICAL_THRESHOLDS = {
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
CANONICAL_METHODOLOGY = {
    "preregistration": (
        "candidate identity, canonical champion, causal family, selection "
        "rule, complete trial parameter hashes, and canonical do-not-repeat "
        "registry history must be bound by a preregistration Git blob that "
        "strictly predates an exact evaluation-start snapshot"
    ),
    "deflated_sharpe": (
        "probabilistic Sharpe ratio against the expected maximum Sharpe "
        "across every recorded trial, adjusted for observed skewness and "
        "Pearson kurtosis"
    ),
    "pbo": (
        "combinatorially symmetric cross-validation over every 4-of-8 "
        "contiguous in-sample block combination; PBO is the fraction whose "
        "selected strategy has out-of-sample logit rank at or below zero"
    ),
    "white_reality_check": (
        "centered circular fixed-block bootstrap of the maximum mean daily "
        "excess return; every configured block length must pass"
    ),
    "multiple_testing_population": (
        "every completed performance trial in the complete experiment ledger"
    ),
    "missing_evidence_policy": "fail_closed_without_imputation",
}
CANONICAL_REFERENCES = {
    "deflated_sharpe": (
        "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551"
    ),
    "probability_of_backtest_overfitting": (
        "https://escholarship.org/uc/item/4w1110bb"
    ),
    "white_reality_check": (
        "https://doi.org/10.1111/1468-0262.00152"
    ),
}
CANONICAL_SAFETY = {
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
CANONICAL_PREREGISTRATION_SAFETY = {
    "research_only": True,
    "automatic_promotion_allowed": False,
    "champion_change_allowed": False,
    "fullrun_allowed": False,
    "production_activation_allowed": False,
    "live_trading_enabled": False,
}
CANONICAL_EVALUATION_SNAPSHOT_SAFETY = {
    "research_only": True,
    "results_present": False,
    "evaluation_starts_after_snapshot_commit": True,
    "automatic_promotion_allowed": False,
    "champion_change_allowed": False,
    "fullrun_allowed": False,
    "production_activation_allowed": False,
    "live_trading_enabled": False,
}
CSCV_COLUMNS = [
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
]


def canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_parameter_hash(value: dict[str, Any]) -> str:
    return sha256_bytes(canonical_json_bytes(value))


def safe_read(path: Path) -> tuple[bytes, str]:
    try:
        value = path.read_bytes()
    except OSError:
        return b"", ""
    return value, sha256_bytes(value)


def parse_json_bytes(value: bytes) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in pairs:
            if key in result:
                raise ValueError(f"duplicate_json_key:{key}")
            result[key] = item
        return result

    try:
        parsed = json.loads(
            value.decode("utf-8"),
            object_pairs_hook=reject_duplicates,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def display_float(value: float) -> str:
    return format(float(value), ".12g")


def unique_sorted(values: Iterable[str]) -> list[str]:
    return sorted({str(value) for value in values if str(value)})


def validate_contract(contract: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    if contract.get("schema_version") != CONTRACT_SCHEMA:
        blockers.append("contract_schema_invalid")
    if contract.get("contract_version") != CONTRACT_VERSION:
        blockers.append("contract_version_invalid")
    if contract.get("input_contract") != CANONICAL_INPUT_CONTRACT:
        blockers.append("contract_input_rules_not_canonical")
    if contract.get("thresholds") != CANONICAL_THRESHOLDS:
        blockers.append("contract_thresholds_not_canonical")
    if contract.get("safety") != CANONICAL_SAFETY:
        blockers.append("contract_safety_not_canonical")
    outputs = contract.get("outputs")
    if outputs != [
        "source_manifest.json",
        "multiple_testing_gate.json",
        "cscv_splits.csv",
        "white_reality_check.json",
        "report.md",
    ]:
        blockers.append("contract_outputs_not_canonical")
    if contract.get("methodology") != CANONICAL_METHODOLOGY:
        blockers.append("contract_methodology_not_canonical")
    if contract.get("references") != CANONICAL_REFERENCES:
        blockers.append("contract_references_not_canonical")
    return blockers


def valid_commit(value: Any) -> bool:
    return bool(re.fullmatch(r"[0-9a-f]{40}", str(value or "").lower()))


def validate_canonical_champion(
    ledger: dict[str, Any],
    promotion_state: dict[str, Any],
) -> tuple[list[str], dict[str, Any]]:
    blockers: list[str] = []
    if promotion_state.get("schema_version") != PROMOTION_STATE_SCHEMA:
        blockers.append("promotion_state_schema_invalid")
    canonical = promotion_state.get("canonical_champion")
    if not isinstance(canonical, dict):
        blockers.append("canonical_champion_missing")
        canonical = {}
    required_fields = {
        "policy_id",
        "source_commit",
        "metric_mode",
        "main_target_book_sha256",
        "concentrated_target_book_sha256",
        "account_namespace",
    }
    if set(canonical) != required_fields:
        blockers.append("canonical_champion_fields_invalid")
    if not valid_commit(canonical.get("source_commit")):
        blockers.append("canonical_champion_source_commit_invalid")
    for field in (
        "main_target_book_sha256",
        "concentrated_target_book_sha256",
    ):
        if not re.fullmatch(
            r"[0-9a-f]{64}",
            str(canonical.get(field) or "").lower(),
        ):
            blockers.append(f"canonical_champion_{field}_invalid")
    if ledger.get("canonical_champion") != canonical:
        blockers.append("ledger_canonical_champion_mismatch")
    if ledger.get("champion_id") != canonical.get("policy_id"):
        blockers.append("ledger_champion_id_mismatch")
    return unique_sorted(blockers), canonical


def validate_ledger(
    ledger: dict[str, Any],
) -> tuple[list[str], list[dict[str, Any]], dict[str, str]]:
    blockers: list[str] = []
    if ledger.get("schema_version") != LEDGER_SCHEMA:
        blockers.append("experiment_ledger_schema_invalid")
    candidate_id = str(ledger.get("candidate_id") or "").strip()
    champion_id = str(ledger.get("champion_id") or "").strip()
    family_id = str(ledger.get("causal_family_id") or "").strip()
    selected_trial_id = str(ledger.get("selected_trial_id") or "").strip()
    if not candidate_id:
        blockers.append("candidate_id_missing")
    if not champion_id:
        blockers.append("champion_id_missing")
    if candidate_id and champion_id and candidate_id == champion_id:
        blockers.append("candidate_id_equals_champion_id")
    if not family_id:
        blockers.append("causal_family_id_missing")
    if ledger.get("causal_challenger_count") != 1:
        blockers.append("causal_challenger_count_not_one")
    if ledger.get("complete_attempt_history") is not True:
        blockers.append("complete_attempt_history_not_proven")
    if ledger.get("preregistered") is not True:
        blockers.append("experiment_family_not_preregistered")
    if ledger.get("selection_metric") != "daily_sharpe":
        blockers.append("selection_metric_not_canonical")
    if (
        ledger.get("return_semantics")
        != CANONICAL_INPUT_CONTRACT["return_semantics"]
    ):
        blockers.append("return_semantics_not_canonical")
    if ledger.get("costs_included") is not True:
        blockers.append("after_cost_return_evidence_not_proven")
    if not selected_trial_id:
        blockers.append("selected_trial_id_missing")
    if not valid_commit(ledger.get("registration_commit_sha")):
        blockers.append("registration_commit_sha_invalid")

    raw_trials = ledger.get("trials")
    if not isinstance(raw_trials, list):
        blockers.append("trial_rows_missing")
        raw_trials = []
    if ledger.get("attempted_parameter_set_count") != len(raw_trials):
        blockers.append("attempted_parameter_set_count_mismatch")

    trials: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_columns: set[str] = set()
    seen_hashes: set[str] = set()
    return_columns: dict[str, str] = {}
    for index, raw in enumerate(raw_trials):
        label = f"trial_{index:04d}"
        if not isinstance(raw, dict):
            blockers.append(f"{label}:row_not_object")
            continue
        trial_id = str(raw.get("trial_id") or "").strip()
        return_column = str(raw.get("return_column") or "").strip()
        parameter_set = raw.get("parameter_set")
        parameter_hash = str(raw.get("parameter_set_sha256") or "").lower()
        if not trial_id or trial_id in seen_ids:
            blockers.append(f"{label}:trial_id_missing_or_duplicate")
        else:
            seen_ids.add(trial_id)
        if (
            not return_column
            or return_column == "date"
            or return_column in seen_columns
        ):
            blockers.append(f"{label}:return_column_missing_or_duplicate")
        else:
            seen_columns.add(return_column)
        if str(raw.get("causal_family_id") or "") != family_id:
            blockers.append(f"{label}:causal_family_mismatch")
        if raw.get("preregistered") is not True:
            blockers.append(f"{label}:not_preregistered")
        if raw.get("performance_evaluated") is not True:
            blockers.append(f"{label}:performance_evidence_incomplete")
        if raw.get("status") != "COMPLETED":
            blockers.append(f"{label}:status_not_completed")
        if not isinstance(parameter_set, dict) or not parameter_set:
            blockers.append(f"{label}:parameter_set_invalid")
        else:
            expected = canonical_parameter_hash(parameter_set)
            if parameter_hash != expected:
                blockers.append(f"{label}:parameter_set_sha256_mismatch")
            if parameter_hash in seen_hashes:
                blockers.append(f"{label}:duplicate_parameter_set")
            seen_hashes.add(parameter_hash)
        trials.append(
            {
                "trial_id": trial_id,
                "return_column": return_column,
                "parameter_set_sha256": parameter_hash,
            }
        )
        if trial_id and return_column:
            return_columns[trial_id] = return_column

    if selected_trial_id and selected_trial_id not in seen_ids:
        blockers.append("selected_trial_id_not_in_ledger")
    minimum = int(CANONICAL_THRESHOLDS["minimum_trials"])
    if len(trials) < minimum:
        blockers.append(f"minimum_trials_not_met:{len(trials)}<{minimum}")
    return unique_sorted(blockers), trials, return_columns


def git_blob(
    repository_root: Path,
    commit_sha: str,
    relative_path: str,
) -> bytes:
    process = subprocess.run(
        ["git", "show", f"{commit_sha}:{relative_path}"],
        cwd=repository_root,
        capture_output=True,
        check=False,
    )
    if process.returncode != 0:
        return b""
    return process.stdout


def validate_preregistration(
    repository_root: Path,
    ledger: dict[str, Any],
    trials: list[dict[str, Any]],
    *,
    promotion_state_sha256: str,
    canonical_champion: dict[str, Any],
) -> tuple[
    list[str],
    dict[str, Any],
    bytes,
    dict[str, Any],
    bytes,
    bytes,
    bytes,
    bytes,
]:
    blockers: list[str] = []
    repository_root = repository_root.resolve()
    registration_commit = str(
        ledger.get("registration_commit_sha") or ""
    ).lower()
    evaluation_commit = str(
        ledger.get("evaluation_commit_sha") or ""
    ).lower()
    preregistration_path = str(
        ledger.get("preregistration_path") or ""
    ).replace(
        "\\", "/"
    )
    evaluation_snapshot_path = str(
        ledger.get("evaluation_snapshot_path") or ""
    ).replace("\\", "/")

    def valid_repo_json_path(value: str) -> bool:
        parts = value.split("/") if value else []
        return bool(
            value
            and not value.startswith("/")
            and ":" not in value
            and all(part not in {"", ".", ".."} for part in parts)
            and value.endswith(".json")
        )

    if not valid_repo_json_path(preregistration_path):
        blockers.append("preregistration_path_invalid")
    if not valid_repo_json_path(evaluation_snapshot_path):
        blockers.append("evaluation_snapshot_path_invalid")
    if (
        preregistration_path
        and preregistration_path == evaluation_snapshot_path
    ):
        blockers.append("registration_and_evaluation_snapshot_path_collision")
    expected_preregistration_sha256 = str(
        ledger.get("preregistration_sha256") or ""
    ).lower()
    expected_evaluation_snapshot_sha256 = str(
        ledger.get("evaluation_snapshot_sha256") or ""
    ).lower()
    if not re.fullmatch(r"[0-9a-f]{64}", expected_preregistration_sha256):
        blockers.append("preregistration_sha256_invalid")
    if not re.fullmatch(
        r"[0-9a-f]{64}", expected_evaluation_snapshot_sha256
    ):
        blockers.append("evaluation_snapshot_sha256_invalid")
    if not valid_commit(registration_commit):
        blockers.append("registration_commit_sha_invalid")
    if not valid_commit(evaluation_commit):
        blockers.append("evaluation_commit_sha_invalid")

    head_sha = ""
    if not blockers:
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repository_root,
            capture_output=True,
            text=True,
            check=False,
        )
        head_sha = head.stdout.strip().lower() if head.returncode == 0 else ""
        if not valid_commit(head_sha):
            blockers.append("evaluation_repository_head_invalid")
        for label, commit in (
            ("registration", registration_commit),
            ("evaluation", evaluation_commit),
        ):
            exists = subprocess.run(
                ["git", "cat-file", "-e", f"{commit}^{{commit}}"],
                cwd=repository_root,
                capture_output=True,
                check=False,
            )
            if exists.returncode != 0:
                blockers.append(f"{label}_commit_unavailable")
        registration_ancestor = subprocess.run(
            [
                "git",
                "merge-base",
                "--is-ancestor",
                registration_commit,
                evaluation_commit,
            ],
            cwd=repository_root,
            capture_output=True,
            check=False,
        )
        if (
            registration_ancestor.returncode != 0
            or registration_commit == evaluation_commit
        ):
            blockers.append(
                "registration_commit_does_not_strictly_precede_evaluation"
            )
        evaluation_ancestor = subprocess.run(
            [
                "git",
                "merge-base",
                "--is-ancestor",
                evaluation_commit,
                "HEAD",
            ],
            cwd=repository_root,
            capture_output=True,
            check=False,
        )
        if evaluation_ancestor.returncode != 0:
            blockers.append("evaluation_commit_not_ancestor_of_head")

    preregistration_bytes = (
        git_blob(
            repository_root,
            registration_commit,
            preregistration_path,
        )
        if not blockers
        else b""
    )
    observed_preregistration_sha256 = (
        sha256_bytes(preregistration_bytes)
        if preregistration_bytes
        else ""
    )
    if not preregistration_bytes:
        blockers.append("preregistration_git_blob_missing")
    elif observed_preregistration_sha256 != expected_preregistration_sha256:
        blockers.append("preregistration_git_blob_sha256_mismatch")
    preregistration = parse_json_bytes(preregistration_bytes)
    if preregistration.get("schema_version") != PREREGISTRATION_SCHEMA:
        blockers.append("preregistration_schema_invalid")
    for field in ("candidate_id", "champion_id", "causal_family_id"):
        if preregistration.get(field) != ledger.get(field):
            blockers.append(f"preregistration_{field}_mismatch")
    if preregistration.get("causal_challenger_count") != 1:
        blockers.append("preregistration_causal_challenger_count_not_one")
    if preregistration.get("selection_metric") != "daily_sharpe":
        blockers.append("preregistration_selection_metric_invalid")
    if preregistration.get("registered_before_evaluation") is not True:
        blockers.append("preregistration_ordering_not_asserted")
    if not str(preregistration.get("hypothesis") or "").strip():
        blockers.append("preregistration_hypothesis_missing")
    if not str(preregistration.get("mechanism") or "").strip():
        blockers.append("preregistration_mechanism_missing")
    if preregistration.get("safety") != CANONICAL_PREREGISTRATION_SAFETY:
        blockers.append("preregistration_safety_invalid")
    if preregistration.get("canonical_champion") != canonical_champion:
        blockers.append("preregistration_canonical_champion_mismatch")

    expected_trial_hashes = {
        str(trial["trial_id"]): str(trial["parameter_set_sha256"])
        for trial in trials
    }
    if (
        preregistration.get("trial_parameter_set_sha256")
        != expected_trial_hashes
        or preregistration.get("preregistered_trial_count")
        != len(expected_trial_hashes)
    ):
        blockers.append("preregistered_trial_set_mismatch")

    registry_path = str(
        preregistration.get("do_not_repeat_registry_path") or ""
    ).replace("\\", "/")
    registry_expected_sha256 = str(
        preregistration.get("do_not_repeat_registry_sha256") or ""
    ).lower()
    registration_registry_bytes = b""
    if (
        registry_path != CANONICAL_DO_NOT_REPEAT_REGISTRY_PATH
        or not re.fullmatch(r"[0-9a-f]{64}", registry_expected_sha256)
    ):
        blockers.append("preregistration_do_not_repeat_registry_anchor_invalid")
    elif valid_commit(registration_commit):
        registration_registry_bytes = git_blob(
            repository_root,
            registration_commit,
            CANONICAL_DO_NOT_REPEAT_REGISTRY_PATH,
        )
        if (
            not registration_registry_bytes
            or sha256_bytes(registration_registry_bytes)
            != registry_expected_sha256
        ):
            blockers.append(
                "preregistration_do_not_repeat_registry_sha256_mismatch"
            )

    evaluation_snapshot_bytes = (
        git_blob(
            repository_root,
            evaluation_commit,
            evaluation_snapshot_path,
        )
        if valid_commit(evaluation_commit)
        and valid_repo_json_path(evaluation_snapshot_path)
        else b""
    )
    if not evaluation_snapshot_bytes:
        blockers.append("evaluation_snapshot_git_blob_missing")
    elif (
        sha256_bytes(evaluation_snapshot_bytes)
        != expected_evaluation_snapshot_sha256
    ):
        blockers.append("evaluation_snapshot_git_blob_sha256_mismatch")
    evaluation_snapshot = parse_json_bytes(evaluation_snapshot_bytes)
    if (
        evaluation_snapshot.get("schema_version")
        != EVALUATION_SNAPSHOT_SCHEMA
    ):
        blockers.append("evaluation_snapshot_schema_invalid")
    for field in ("candidate_id", "champion_id", "causal_family_id"):
        if evaluation_snapshot.get(field) != ledger.get(field):
            blockers.append(f"evaluation_snapshot_{field}_mismatch")
    if evaluation_snapshot.get("canonical_champion") != canonical_champion:
        blockers.append("evaluation_snapshot_canonical_champion_mismatch")
    if (
        evaluation_snapshot.get("promotion_state_sha256")
        != promotion_state_sha256
    ):
        blockers.append("evaluation_snapshot_promotion_state_sha256_mismatch")
    if evaluation_snapshot.get("selection_metric") != "daily_sharpe":
        blockers.append("evaluation_snapshot_selection_metric_invalid")
    if (
        evaluation_snapshot.get("trial_parameter_set_sha256")
        != expected_trial_hashes
        or evaluation_snapshot.get("evaluation_trial_count")
        != len(expected_trial_hashes)
    ):
        blockers.append("evaluation_snapshot_trial_set_mismatch")
    if evaluation_snapshot.get(
        "preregistration"
    ) != {
        "commit_sha": registration_commit,
        "path": preregistration_path,
        "sha256": expected_preregistration_sha256,
    }:
        blockers.append("evaluation_snapshot_preregistration_anchor_mismatch")
    if (
        evaluation_snapshot.get("safety")
        != CANONICAL_EVALUATION_SNAPSHOT_SAFETY
    ):
        blockers.append("evaluation_snapshot_safety_invalid")

    evaluation_registry_expected_sha256 = str(
        evaluation_snapshot.get(
            "canonical_do_not_repeat_registry_sha256"
        )
        or ""
    ).lower()
    evaluation_registry_bytes = (
        git_blob(
            repository_root,
            evaluation_commit,
            CANONICAL_DO_NOT_REPEAT_REGISTRY_PATH,
        )
        if valid_commit(evaluation_commit)
        else b""
    )
    if (
        not re.fullmatch(
            r"[0-9a-f]{64}", evaluation_registry_expected_sha256
        )
        or not evaluation_registry_bytes
        or sha256_bytes(evaluation_registry_bytes)
        != evaluation_registry_expected_sha256
    ):
        blockers.append("evaluation_snapshot_canonical_registry_mismatch")

    current_registry_path = (
        repository_root / CANONICAL_DO_NOT_REPEAT_REGISTRY_PATH
    )
    current_registry_bytes = b""
    if (
        not current_registry_path.is_file()
        or current_registry_path.is_symlink()
    ):
        blockers.append("canonical_do_not_repeat_registry_missing")
    else:
        current_registry_bytes = current_registry_path.read_bytes()

    registration_registry = parse_json_bytes(registration_registry_bytes)
    evaluation_registry = parse_json_bytes(evaluation_registry_bytes)
    current_registry = parse_json_bytes(current_registry_bytes)

    def registry_entries(
        payload: dict[str, Any],
        label: str,
    ) -> dict[str, dict[str, Any]]:
        if payload.get("schema_version") != "run287-do-not-repeat-registry-v1":
            blockers.append(f"{label}_registry_schema_invalid")
            return {}
        raw_entries = payload.get("entries")
        if not isinstance(raw_entries, list):
            blockers.append(f"{label}_registry_entries_invalid")
            return {}
        result: dict[str, dict[str, Any]] = {}
        for entry in raw_entries:
            entry_id = str(entry.get("id") or "") if isinstance(entry, dict) else ""
            if not entry_id or entry_id in result:
                blockers.append(f"{label}_registry_entry_id_invalid")
                continue
            result[entry_id] = entry
        return result

    registration_entries = registry_entries(
        registration_registry, "registration"
    )
    evaluation_entries = registry_entries(evaluation_registry, "evaluation")
    current_entries = registry_entries(current_registry, "current")
    for older_label, older, newer_label, newer in (
        (
            "registration",
            registration_entries,
            "evaluation",
            evaluation_entries,
        ),
        ("evaluation", evaluation_entries, "current", current_entries),
    ):
        changed = [
            entry_id
            for entry_id, entry in older.items()
            if newer.get(entry_id) != entry
        ]
        if changed:
            blockers.append(
                f"canonical_registry_history_not_preserved:"
                f"{older_label}_to_{newer_label}:"
                + ",".join(sorted(changed))
            )

    descriptor = preregistration.get("do_not_repeat_descriptor")
    if (
        preregistration.get("do_not_repeat_conflict_absent") is not True
        or not isinstance(descriptor, dict)
        or current_registry.get("schema_version")
        != "run287-do-not-repeat-registry-v1"
    ):
        blockers.append("preregistration_do_not_repeat_evidence_invalid")
    else:
        match_fields = current_registry.get(
            "match_fields",
            ["signal", "mechanism", "book", "window"],
        )
        if not isinstance(match_fields, list) or any(
            not descriptor.get(str(field)) for field in match_fields
        ):
            blockers.append("preregistration_do_not_repeat_descriptor_invalid")
        else:
            conflicts = [
                str(entry.get("id") or "unknown")
                for entry in current_registry.get("entries", [])
                if isinstance(entry, dict)
                and entry.get("blocked_reuse") is True
                and all(
                    str(entry.get(str(field)) or "")
                    == str(descriptor.get(str(field)) or "")
                    for field in match_fields
                )
            ]
            if conflicts:
                blockers.append(
                    "preregistration_do_not_repeat_conflict:"
                    + ",".join(sorted(conflicts))
                )
    return (
        unique_sorted(blockers),
        preregistration,
        preregistration_bytes,
        evaluation_snapshot,
        evaluation_snapshot_bytes,
        registration_registry_bytes,
        evaluation_registry_bytes,
        current_registry_bytes,
    )


def parse_return_matrix(
    value: bytes,
    trials: list[dict[str, Any]],
) -> tuple[list[str], pd.DatetimeIndex | None, np.ndarray | None]:
    blockers: list[str] = []
    if not value:
        return ["return_matrix_missing_or_unreadable"], None, None
    try:
        text = value.decode("utf-8-sig")
    except UnicodeDecodeError:
        return ["return_matrix_not_utf8"], None, None
    try:
        header = next(csv.reader(io.StringIO(text)))
    except (csv.Error, StopIteration):
        return ["return_matrix_header_invalid"], None, None
    if len(header) != len(set(header)):
        blockers.append("return_matrix_duplicate_columns")
    expected_columns = ["date"] + [
        str(trial["return_column"]) for trial in trials
    ]
    if set(header) != set(expected_columns) or len(header) != len(expected_columns):
        blockers.append("return_matrix_column_set_mismatch")
    if not header or header[0] != "date":
        blockers.append("return_matrix_date_column_not_first")
    if blockers:
        return unique_sorted(blockers), None, None

    try:
        frame = pd.read_csv(io.StringIO(text), dtype={"date": str})
    except Exception:
        return ["return_matrix_csv_invalid"], None, None
    if frame.empty:
        return ["return_matrix_empty"], None, None
    raw_dates = frame["date"].astype(str)
    if not raw_dates.map(
        lambda item: bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", item))
    ).all():
        blockers.append("return_matrix_date_format_invalid")
    parsed_dates = pd.to_datetime(raw_dates, format="%Y-%m-%d", errors="coerce")
    if parsed_dates.isna().any():
        blockers.append("return_matrix_date_invalid")
    elif parsed_dates.duplicated().any():
        blockers.append("return_matrix_duplicate_dates")
    elif not parsed_dates.is_monotonic_increasing:
        blockers.append("return_matrix_dates_not_strictly_increasing")
    else:
        expected_sessions = mcal.get_calendar("NYSE").schedule(
            start_date=parsed_dates.iloc[0].date(),
            end_date=parsed_dates.iloc[-1].date(),
        ).index.strftime("%Y-%m-%d").tolist()
        if raw_dates.tolist() != expected_sessions:
            blockers.append("return_matrix_not_exact_contiguous_nyse_sessions")

    ordered_columns = [str(trial["return_column"]) for trial in trials]
    numeric = frame[ordered_columns].apply(pd.to_numeric, errors="coerce")
    matrix = numeric.to_numpy(dtype=float)
    if not np.isfinite(matrix).all():
        blockers.append("return_matrix_nonfinite_or_missing")
    minimum = int(CANONICAL_THRESHOLDS["minimum_synchronous_observations"])
    if matrix.shape[0] < minimum:
        blockers.append(
            f"minimum_synchronous_observations_not_met:{matrix.shape[0]}<{minimum}"
        )
    if matrix.shape[1] != len(trials):
        blockers.append("return_matrix_trial_count_mismatch")
    block_count = int(CANONICAL_THRESHOLDS["cscv_contiguous_blocks"])
    if matrix.shape[0] % block_count:
        blockers.append(
            "cscv_observation_count_not_divisible_by_blocks:"
            f"{matrix.shape[0]}%{block_count}"
        )
    if matrix.shape[0] >= 2 and matrix.shape[1]:
        standard_deviations = np.std(matrix, axis=0, ddof=1)
        for trial, value_std in zip(trials, standard_deviations):
            if not math.isfinite(float(value_std)) or float(value_std) <= 0.0:
                blockers.append(
                    f"full_sample_zero_variance:{trial['trial_id']}"
                )
    return (
        unique_sorted(blockers),
        pd.DatetimeIndex(parsed_dates) if not parsed_dates.isna().any() else None,
        matrix if not blockers else None,
    )


def sharpe_vector(matrix: np.ndarray) -> np.ndarray:
    means = np.mean(matrix, axis=0)
    standard_deviations = np.std(matrix, axis=0, ddof=1)
    if (
        not np.isfinite(means).all()
        or not np.isfinite(standard_deviations).all()
        or np.any(standard_deviations <= 0.0)
    ):
        raise ValueError("subset_sharpe_undefined")
    return means / standard_deviations


def selected_trial(
    trial_ids: list[str],
    sharpes: np.ndarray,
) -> tuple[str, int]:
    ordered_indices = sorted(range(len(trial_ids)), key=lambda idx: trial_ids[idx])
    winner = max(ordered_indices, key=lambda idx: float(sharpes[idx]))
    return trial_ids[winner], winner


def deflated_sharpe(
    matrix: np.ndarray,
    trial_ids: list[str],
    candidate_index: int,
) -> dict[str, Any]:
    trial_sharpes = sharpe_vector(matrix)
    candidate_returns = matrix[:, candidate_index]
    candidate_sharpe = float(trial_sharpes[candidate_index])
    trial_sharpe_std = float(np.std(trial_sharpes, ddof=1))
    trial_count = matrix.shape[1]
    expected_maximum = trial_sharpe_std * (
        (1.0 - EULER_MASCHERONI) * norm.ppf(1.0 - 1.0 / trial_count)
        + EULER_MASCHERONI
        * norm.ppf(1.0 - 1.0 / (trial_count * math.e))
    )
    sample_skewness = float(skew(candidate_returns, bias=False))
    pearson_kurtosis = float(
        kurtosis(candidate_returns, fisher=False, bias=False)
    )
    radicand = (
        1.0
        - sample_skewness * candidate_sharpe
        + ((pearson_kurtosis - 1.0) / 4.0) * candidate_sharpe**2
    )
    if not math.isfinite(radicand) or radicand <= 0.0:
        raise ValueError("dsr_denominator_invalid")
    z_score = (
        (candidate_sharpe - expected_maximum)
        * math.sqrt(matrix.shape[0] - 1)
        / math.sqrt(radicand)
    )
    probability = float(norm.cdf(z_score))
    threshold = float(
        CANONICAL_THRESHOLDS["deflated_sharpe_probability_minimum"]
    )
    return {
        "status": "PASS" if probability >= threshold else "FAIL",
        "passed": probability >= threshold,
        "selected_trial_id": trial_ids[candidate_index],
        "daily_sharpe": candidate_sharpe,
        "annualized_sharpe": candidate_sharpe
        * math.sqrt(float(CANONICAL_THRESHOLDS["annualization_sessions"])),
        "trial_sharpe_standard_deviation": trial_sharpe_std,
        "expected_maximum_daily_sharpe": float(expected_maximum),
        "sample_skewness": sample_skewness,
        "sample_pearson_kurtosis": pearson_kurtosis,
        "z_score": float(z_score),
        "probability": probability,
        "minimum_probability": threshold,
        "trial_daily_sharpes": {
            trial_id: float(value)
            for trial_id, value in zip(trial_ids, trial_sharpes)
        },
    }


def cscv_pbo(
    matrix: np.ndarray,
    trial_ids: list[str],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    block_count = int(CANONICAL_THRESHOLDS["cscv_contiguous_blocks"])
    if block_count % 2:
        raise ValueError("cscv_block_count_not_even")
    blocks = [
        np.asarray(block, dtype=int)
        for block in np.array_split(np.arange(matrix.shape[0]), block_count)
    ]
    if any(len(block) < 2 for block in blocks):
        raise ValueError("cscv_block_too_short")
    rows: list[dict[str, Any]] = []
    half = block_count // 2
    for split_id, in_blocks_tuple in enumerate(
        itertools.combinations(range(block_count), half),
        start=1,
    ):
        in_blocks = set(in_blocks_tuple)
        out_blocks = set(range(block_count)) - in_blocks
        in_indices = np.concatenate([blocks[index] for index in sorted(in_blocks)])
        out_indices = np.concatenate(
            [blocks[index] for index in sorted(out_blocks)]
        )
        try:
            in_sharpes = sharpe_vector(matrix[in_indices, :])
            out_sharpes = sharpe_vector(matrix[out_indices, :])
        except ValueError as exc:
            raise ValueError(f"cscv_{exc}") from exc
        winner_id, winner_index = selected_trial(trial_ids, in_sharpes)
        ranks = rankdata(out_sharpes, method="average")
        selected_rank = float(ranks[winner_index])
        rank_fraction = selected_rank / (len(trial_ids) + 1.0)
        logit = math.log(rank_fraction / (1.0 - rank_fraction))
        rows.append(
            {
                "split_id": split_id,
                "in_sample_blocks": ",".join(
                    str(index) for index in sorted(in_blocks)
                ),
                "out_of_sample_blocks": ",".join(
                    str(index) for index in sorted(out_blocks)
                ),
                "selected_trial_id": winner_id,
                "in_sample_sharpe": float(in_sharpes[winner_index]),
                "selected_out_of_sample_sharpe": float(
                    out_sharpes[winner_index]
                ),
                "selected_out_of_sample_rank": selected_rank,
                "rank_fraction": float(rank_fraction),
                "logit": float(logit),
                "overfit": logit <= 0.0,
            }
        )
    pbo = sum(bool(row["overfit"]) for row in rows) / len(rows)
    threshold = float(
        CANONICAL_THRESHOLDS[
            "probability_of_backtest_overfitting_maximum"
        ]
    )
    return (
        {
            "status": "PASS" if pbo <= threshold else "FAIL",
            "passed": pbo <= threshold,
            "probability": float(pbo),
            "maximum_probability": threshold,
            "contiguous_block_count": block_count,
            "split_count": len(rows),
            "block_sizes": [len(block) for block in blocks],
            "overfit_split_count": sum(
                bool(row["overfit"]) for row in rows
            ),
        },
        rows,
    )


def circular_block_indices(
    rng: np.random.Generator,
    observation_count: int,
    block_length: int,
) -> np.ndarray:
    block_count = math.ceil(observation_count / block_length)
    starts = rng.integers(0, observation_count, size=block_count)
    offsets = np.arange(block_length, dtype=int)
    return ((starts[:, None] + offsets) % observation_count).reshape(-1)[
        :observation_count
    ]


def white_reality_check(
    matrix: np.ndarray,
    trial_ids: list[str],
) -> dict[str, Any]:
    observation_count = matrix.shape[0]
    means = np.mean(matrix, axis=0)
    observed_best_index = int(np.argmax(means))
    observed_statistic = float(
        math.sqrt(observation_count) * np.max(means)
    )
    centered = matrix - means
    repetitions = int(CANONICAL_THRESHOLDS["bootstrap_repetitions"])
    seed = int(CANONICAL_THRESHOLDS["bootstrap_random_seed"])
    maximum_p = float(
        CANONICAL_THRESHOLDS["white_reality_check_p_value_maximum"]
    )
    results: list[dict[str, Any]] = []
    for block_length_raw in CANONICAL_THRESHOLDS[
        "bootstrap_block_lengths"
    ]:
        block_length = int(block_length_raw)
        rng = np.random.default_rng(seed + block_length)
        exceedances = 0
        for _ in range(repetitions):
            indices = circular_block_indices(
                rng, observation_count, block_length
            )
            statistic = float(
                math.sqrt(observation_count)
                * np.max(np.mean(centered[indices, :], axis=0))
            )
            if statistic >= observed_statistic:
                exceedances += 1
        p_value = (exceedances + 1.0) / (repetitions + 1.0)
        results.append(
            {
                "block_length": block_length,
                "bootstrap_repetitions": repetitions,
                "random_seed": seed + block_length,
                "exceedance_count": exceedances,
                "p_value": float(p_value),
                "maximum_p_value": maximum_p,
                "passed": p_value <= maximum_p,
            }
        )
    passed = all(bool(row["passed"]) for row in results)
    return {
        "schema_version": "run287-white-reality-check-v1",
        "status": "PASS" if passed else "FAIL",
        "passed": passed,
        "null_hypothesis": (
            "no recorded trial has positive expected daily excess return "
            "versus the canonical champion"
        ),
        "observed_statistic": observed_statistic,
        "observed_best_trial_id": trial_ids[observed_best_index],
        "observed_best_mean_daily_excess_return": float(
            means[observed_best_index]
        ),
        "centering": "trial_mean_removed_before_resampling",
        "bootstrap": "circular_fixed_block",
        "all_block_lengths_must_pass": True,
        "results": results,
    }


def csv_bytes(rows: list[dict[str, Any]]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=CSCV_COLUMNS, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        rendered = dict(row)
        for field in (
            "in_sample_sharpe",
            "selected_out_of_sample_sharpe",
            "selected_out_of_sample_rank",
            "rank_fraction",
            "logit",
        ):
            rendered[field] = display_float(float(rendered[field]))
        rendered["overfit"] = str(bool(rendered["overfit"])).lower()
        writer.writerow(rendered)
    return output.getvalue().encode("utf-8")


def source_name(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.name


def blocked_statistic(name: str) -> dict[str, Any]:
    return {
        "status": "NOT_EVALUATED",
        "passed": False,
        "reason": f"{name}_requires_complete_valid_inputs",
    }


def render_report(gate: dict[str, Any]) -> str:
    sample = gate["sample"]
    lines = [
        "# Run287 multiple-testing gate",
        "",
        f"- Status: `{gate['status']}`",
        f"- Passed: `{str(gate['passed']).lower()}`",
        f"- Candidate: `{gate.get('candidate_id') or 'none'}`",
        f"- Selected trial: `{gate.get('selected_trial_id') or 'none'}`",
        f"- Trials / synchronous observations: `{sample['trial_count']} / {sample['observation_count']}`",
        f"- Deflated Sharpe: `{gate['deflated_sharpe']['status']}`",
        f"- PBO: `{gate['probability_of_backtest_overfitting']['status']}`",
        f"- White Reality Check: `{gate['white_reality_check']['status']}`",
        "",
        "## Blockers",
        "",
    ]
    blockers = gate.get("blockers") or []
    lines.extend(
        [f"- `{blocker}`" for blocker in blockers]
        if blockers
        else ["- None"]
    )
    lines.extend(
        [
            "",
            "This is a research-only statistical gate. It does not run a fullrun,",
            "change the champion, mutate portfolio state, generate orders, or enable",
            "production/live trading.",
            "",
        ]
    )
    return "\n".join(lines)


def publish_bundle(output_dir: Path, blobs: dict[str, bytes]) -> None:
    expected = set(blobs)
    output_dir = output_dir.resolve()
    if output_dir.exists():
        if not output_dir.is_dir() or output_dir.is_symlink():
            raise FileExistsError(f"output_bundle_not_plain_directory:{output_dir}")
        existing = {path.name for path in output_dir.iterdir()}
        if existing != expected:
            raise FileExistsError(f"output_bundle_file_set_conflict:{output_dir}")
        for name, value in blobs.items():
            path = output_dir / name
            if not path.is_file() or path.is_symlink() or path.read_bytes() != value:
                raise FileExistsError(f"output_bundle_content_conflict:{name}")
        return

    output_dir.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(
        tempfile.mkdtemp(
            prefix=f".{output_dir.name}.stage-",
            dir=str(output_dir.parent),
        )
    )
    try:
        for name, value in blobs.items():
            destination = stage / name
            destination.write_bytes(value)
        os.replace(stage, output_dir)
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def evaluate(
    *,
    contract_path: Path,
    experiment_ledger_path: Path,
    return_matrix_path: Path,
    output_dir: Path,
    repository_root: Path = ROOT,
    promotion_state_path: Path = DEFAULT_PROMOTION_STATE,
) -> dict[str, Any]:
    contract_bytes, contract_hash = safe_read(contract_path)
    ledger_bytes, ledger_hash = safe_read(experiment_ledger_path)
    returns_bytes, returns_hash = safe_read(return_matrix_path)
    promotion_state_bytes, promotion_state_hash = safe_read(
        promotion_state_path
    )
    contract = parse_json_bytes(contract_bytes)
    ledger = parse_json_bytes(ledger_bytes)
    promotion_state = parse_json_bytes(promotion_state_bytes)
    blockers: list[str] = []
    if not contract_bytes:
        blockers.append("contract_missing_or_unreadable")
    if not ledger_bytes:
        blockers.append("experiment_ledger_missing_or_unreadable")
    if not promotion_state_bytes:
        blockers.append("promotion_state_missing_or_unreadable")
    contract_blockers = validate_contract(contract)
    blockers.extend(contract_blockers)
    ledger_blockers, trials, return_columns = validate_ledger(ledger)
    blockers.extend(ledger_blockers)
    champion_blockers, canonical_champion = validate_canonical_champion(
        ledger,
        promotion_state,
    )
    blockers.extend(champion_blockers)
    (
        preregistration_blockers,
        preregistration,
        preregistration_bytes,
        evaluation_snapshot,
        evaluation_snapshot_bytes,
        registration_registry_bytes,
        evaluation_registry_bytes,
        current_registry_bytes,
    ) = validate_preregistration(
        repository_root,
        ledger,
        trials,
        promotion_state_sha256=promotion_state_hash,
        canonical_champion=canonical_champion,
    )
    blockers.extend(preregistration_blockers)
    if str(ledger.get("return_matrix_sha256") or "").lower() != returns_hash:
        blockers.append("experiment_ledger_return_matrix_sha256_mismatch")

    matrix_blockers, dates, matrix = parse_return_matrix(
        returns_bytes, trials
    )
    blockers.extend(matrix_blockers)
    trial_ids = [str(trial["trial_id"]) for trial in trials]
    selected_id = str(ledger.get("selected_trial_id") or "")
    candidate_id = str(ledger.get("candidate_id") or "")

    dsr_result = blocked_statistic("deflated_sharpe")
    pbo_result = blocked_statistic("pbo")
    white_result = blocked_statistic("white_reality_check")
    cscv_rows: list[dict[str, Any]] = []
    reproduced_selected = ""
    if not blockers and matrix is not None:
        try:
            full_sharpes = sharpe_vector(matrix)
            reproduced_selected, selected_index = selected_trial(
                trial_ids, full_sharpes
            )
            if selected_id != reproduced_selected:
                blockers.append(
                    "selected_trial_not_reproducible:"
                    f"{selected_id or 'missing'}!={reproduced_selected}"
                )
            else:
                dsr_result = deflated_sharpe(
                    matrix, trial_ids, selected_index
                )
                pbo_result, cscv_rows = cscv_pbo(matrix, trial_ids)
                white_result = white_reality_check(matrix, trial_ids)
        except (ValueError, FloatingPointError) as exc:
            blockers.append(f"statistical_evaluation_failed:{exc}")

    current_hashes = {
        "contract": sha256_file(contract_path)
        if contract_path.is_file()
        else "",
        "experiment_ledger": sha256_file(experiment_ledger_path)
        if experiment_ledger_path.is_file()
        else "",
        "promotion_state": sha256_file(promotion_state_path)
        if promotion_state_path.is_file()
        else "",
        "preregistration": sha256_bytes(
            git_blob(
                repository_root,
                str(ledger.get("registration_commit_sha") or ""),
                str(ledger.get("preregistration_path") or "").replace(
                    "\\", "/"
                ),
            )
        )
        if preregistration_bytes
        else "",
        "evaluation_snapshot": sha256_bytes(
            git_blob(
                repository_root,
                str(ledger.get("evaluation_commit_sha") or ""),
                str(
                    ledger.get("evaluation_snapshot_path") or ""
                ).replace("\\", "/"),
            )
        )
        if evaluation_snapshot_bytes
        else "",
        "registration_registry_snapshot": sha256_bytes(
            git_blob(
                repository_root,
                str(ledger.get("registration_commit_sha") or ""),
                CANONICAL_DO_NOT_REPEAT_REGISTRY_PATH,
            )
        )
        if registration_registry_bytes
        else "",
        "evaluation_registry_snapshot": sha256_bytes(
            git_blob(
                repository_root,
                str(ledger.get("evaluation_commit_sha") or ""),
                CANONICAL_DO_NOT_REPEAT_REGISTRY_PATH,
            )
        )
        if evaluation_registry_bytes
        else "",
        "canonical_do_not_repeat_registry": sha256_file(
            repository_root / CANONICAL_DO_NOT_REPEAT_REGISTRY_PATH
        )
        if (
            repository_root / CANONICAL_DO_NOT_REPEAT_REGISTRY_PATH
        ).is_file()
        else "",
        "return_matrix": sha256_file(return_matrix_path)
        if return_matrix_path.is_file()
        else "",
    }
    consumed_hashes = {
        "contract": contract_hash,
        "experiment_ledger": ledger_hash,
        "promotion_state": promotion_state_hash,
        "preregistration": sha256_bytes(preregistration_bytes)
        if preregistration_bytes
        else "",
        "evaluation_snapshot": sha256_bytes(evaluation_snapshot_bytes)
        if evaluation_snapshot_bytes
        else "",
        "registration_registry_snapshot": sha256_bytes(
            registration_registry_bytes
        )
        if registration_registry_bytes
        else "",
        "evaluation_registry_snapshot": sha256_bytes(
            evaluation_registry_bytes
        )
        if evaluation_registry_bytes
        else "",
        "canonical_do_not_repeat_registry": sha256_bytes(
            current_registry_bytes
        )
        if current_registry_bytes
        else "",
        "return_matrix": returns_hash,
    }
    if current_hashes != consumed_hashes:
        blockers.append("input_changed_during_evaluation")

    statistical_pass = bool(
        dsr_result.get("passed")
        and pbo_result.get("passed")
        and white_result.get("passed")
    )
    blockers = unique_sorted(blockers)
    passed = not blockers and statistical_pass
    if not dsr_result.get("passed") and dsr_result.get("status") != "NOT_EVALUATED":
        blockers.append("deflated_sharpe_threshold_not_met")
    if not pbo_result.get("passed") and pbo_result.get("status") != "NOT_EVALUATED":
        blockers.append("pbo_threshold_not_met")
    if not white_result.get("passed") and white_result.get("status") != "NOT_EVALUATED":
        blockers.append("white_reality_check_threshold_not_met")
    blockers = unique_sorted(blockers)
    input_set_sha256 = sha256_bytes(
        canonical_json_bytes(consumed_hashes)
    )
    source_manifest = {
        "schema_version": SOURCE_MANIFEST_SCHEMA,
        "contract_version": CONTRACT_VERSION,
        "candidate_id": candidate_id or None,
        "champion_id": str(ledger.get("champion_id") or "") or None,
        "causal_family_id": str(ledger.get("causal_family_id") or "") or None,
        "selected_trial_id": selected_id or None,
        "inputs": {
            "contract": {
                "path": source_name(contract_path),
                "sha256": contract_hash,
                "bytes": len(contract_bytes),
            },
            "experiment_ledger": {
                "path": source_name(experiment_ledger_path),
                "sha256": ledger_hash,
                "bytes": len(ledger_bytes),
            },
            "promotion_state": {
                "path": source_name(promotion_state_path),
                "sha256": promotion_state_hash,
                "bytes": len(promotion_state_bytes),
            },
            "preregistration": {
                "path": (
                    "git:"
                    + str(ledger.get("registration_commit_sha") or "")
                    + ":"
                    + str(ledger.get("preregistration_path") or "")
                ),
                "sha256": consumed_hashes["preregistration"],
                "bytes": len(preregistration_bytes),
            },
            "evaluation_snapshot": {
                "path": (
                    "git:"
                    + str(ledger.get("evaluation_commit_sha") or "")
                    + ":"
                    + str(ledger.get("evaluation_snapshot_path") or "")
                ),
                "sha256": consumed_hashes["evaluation_snapshot"],
                "bytes": len(evaluation_snapshot_bytes),
            },
            "registration_registry_snapshot": {
                "path": (
                    "git:"
                    + str(ledger.get("registration_commit_sha") or "")
                    + ":"
                    + CANONICAL_DO_NOT_REPEAT_REGISTRY_PATH
                ),
                "sha256": consumed_hashes[
                    "registration_registry_snapshot"
                ],
                "bytes": len(registration_registry_bytes),
            },
            "evaluation_registry_snapshot": {
                "path": (
                    "git:"
                    + str(ledger.get("evaluation_commit_sha") or "")
                    + ":"
                    + CANONICAL_DO_NOT_REPEAT_REGISTRY_PATH
                ),
                "sha256": consumed_hashes[
                    "evaluation_registry_snapshot"
                ],
                "bytes": len(evaluation_registry_bytes),
            },
            "canonical_do_not_repeat_registry": {
                "path": CANONICAL_DO_NOT_REPEAT_REGISTRY_PATH,
                "sha256": consumed_hashes[
                    "canonical_do_not_repeat_registry"
                ],
                "bytes": len(current_registry_bytes),
            },
            "return_matrix": {
                "path": source_name(return_matrix_path),
                "sha256": returns_hash,
                "bytes": len(returns_bytes),
            },
        },
        "input_set_sha256": input_set_sha256,
        "return_semantics": CANONICAL_INPUT_CONTRACT["return_semantics"],
        "wall_clock_fields_present": False,
    }
    source_manifest_bytes = canonical_json_bytes(source_manifest)
    source_manifest_sha256 = sha256_bytes(source_manifest_bytes)
    cscv_output_bytes = csv_bytes(cscv_rows)
    white_output_bytes = canonical_json_bytes(white_result)

    checks = {
        "contract_valid": not contract_blockers,
        "complete_experiment_ledger": not ledger_blockers,
        "canonical_champion_binding": not champion_blockers,
        "single_preregistered_causal_family": not any(
            "causal_" in blocker or "preregister" in blocker
            for blocker in ledger_blockers + preregistration_blockers
        ),
        "git_anchored_preregistration": not preregistration_blockers,
        "evaluation_snapshot_binding": not any(
            "evaluation_" in blocker
            or "registration_commit_does_not_strictly" in blocker
            for blocker in preregistration_blockers
        ),
        "canonical_registry_history": not any(
            "registry" in blocker for blocker in preregistration_blockers
        ),
        "minimum_trials": len(trials)
        >= int(CANONICAL_THRESHOLDS["minimum_trials"]),
        "synchronized_return_matrix": not matrix_blockers and matrix is not None,
        "minimum_synchronous_observations": bool(
            matrix is not None
            and matrix.shape[0]
            >= int(
                CANONICAL_THRESHOLDS[
                    "minimum_synchronous_observations"
                ]
            )
        ),
        "selected_trial_reproducible": bool(
            selected_id and selected_id == reproduced_selected
        ),
        "deflated_sharpe": bool(dsr_result.get("passed")),
        "probability_of_backtest_overfitting": bool(
            pbo_result.get("passed")
        ),
        "white_reality_check": bool(white_result.get("passed")),
        "inputs_immutable_during_evaluation": (
            current_hashes == consumed_hashes
        ),
    }
    gate = {
        "schema_version": GATE_SCHEMA,
        "contract_version": CONTRACT_VERSION,
        "status": "PASS" if passed else "BLOCKED",
        "passed": passed,
        "candidate_id": candidate_id or None,
        "champion_id": str(ledger.get("champion_id") or "") or None,
        "causal_family_id": str(ledger.get("causal_family_id") or "") or None,
        "selected_trial_id": selected_id or None,
        "reproduced_selected_trial_id": reproduced_selected or None,
        "canonical_champion": canonical_champion or None,
        "preregistration": {
            "registration_commit_sha": str(
                ledger.get("registration_commit_sha") or ""
            )
            or None,
            "path": str(ledger.get("preregistration_path") or "") or None,
            "sha256": consumed_hashes["preregistration"] or None,
            "registered_before_evaluation": (
                preregistration.get("registered_before_evaluation") is True
            ),
            "do_not_repeat_conflict_absent": (
                preregistration.get("do_not_repeat_conflict_absent") is True
            ),
        },
        "evaluation_snapshot": {
            "evaluation_commit_sha": str(
                ledger.get("evaluation_commit_sha") or ""
            )
            or None,
            "path": str(
                ledger.get("evaluation_snapshot_path") or ""
            )
            or None,
            "sha256": consumed_hashes["evaluation_snapshot"] or None,
            "registration_commit_sha": str(
                ledger.get("registration_commit_sha") or ""
            )
            or None,
            "promotion_state_sha256": promotion_state_hash or None,
            "results_present": (
                isinstance(evaluation_snapshot.get("safety"), dict)
                and evaluation_snapshot["safety"].get("results_present")
                is True
            ),
        },
        "source_manifest_sha256": source_manifest_sha256,
        "input_set_sha256": input_set_sha256,
        "artifact_hashes": {
            "source_manifest.json": source_manifest_sha256,
            "cscv_splits.csv": sha256_bytes(cscv_output_bytes),
            "white_reality_check.json": sha256_bytes(white_output_bytes),
        },
        "sample": {
            "trial_count": len(trials),
            "observation_count": int(matrix.shape[0])
            if matrix is not None
            else 0,
            "first_date": dates[0].date().isoformat()
            if dates is not None and len(dates)
            else None,
            "last_date": dates[-1].date().isoformat()
            if dates is not None and len(dates)
            else None,
            "return_columns": {
                key: return_columns[key] for key in sorted(return_columns)
            },
        },
        "thresholds": dict(CANONICAL_THRESHOLDS),
        "checks": checks,
        "blockers": blockers,
        "deflated_sharpe": dsr_result,
        "probability_of_backtest_overfitting": pbo_result,
        "white_reality_check": {
            "status": white_result.get("status"),
            "passed": bool(white_result.get("passed")),
            "artifact": "white_reality_check.json",
        },
        "safety": dict(CANONICAL_SAFETY),
        "automatic_promotion_performed": False,
        "champion_changed": False,
        "fullrun_executed": False,
    }
    report_output_bytes = render_report(gate).encode("utf-8")
    gate["artifact_hashes"]["report.md"] = sha256_bytes(
        report_output_bytes
    )

    publish_bundle(
        output_dir,
        {
            "source_manifest.json": source_manifest_bytes,
            "multiple_testing_gate.json": canonical_json_bytes(gate),
            "cscv_splits.csv": cscv_output_bytes,
            "white_reality_check.json": white_output_bytes,
            "report.md": report_output_bytes,
        },
    )
    return gate


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", default=str(DEFAULT_CONTRACT))
    parser.add_argument("--experiment-ledger", required=True)
    parser.add_argument("--return-matrix", required=True)
    parser.add_argument("--repository-root", default=str(ROOT))
    parser.add_argument(
        "--promotion-state",
        default=str(DEFAULT_PROMOTION_STATE),
    )
    parser.add_argument(
        "--output-dir",
        default="outputs/run287_multiple_testing_gate",
    )
    args = parser.parse_args()
    gate = evaluate(
        contract_path=Path(args.contract).resolve(),
        experiment_ledger_path=Path(args.experiment_ledger).resolve(),
        return_matrix_path=Path(args.return_matrix).resolve(),
        output_dir=Path(args.output_dir).resolve(),
        repository_root=Path(args.repository_root).resolve(),
        promotion_state_path=Path(args.promotion_state).resolve(),
    )
    print(
        json.dumps(
            {
                "status": gate["status"],
                "passed": gate["passed"],
                "candidate_id": gate["candidate_id"],
                "selected_trial_id": gate["selected_trial_id"],
                "blockers": gate["blockers"],
                "output_dir": str(Path(args.output_dir).resolve()),
                "champion_changed": False,
                "fullrun_executed": False,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
