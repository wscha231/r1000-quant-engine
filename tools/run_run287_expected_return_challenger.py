#!/usr/bin/env python3
"""Train a PIT-purged, proposal-only Run287 expected-return challenger.

The real historical path is fail-closed behind canonical U0-v3 acceptance.
This program never writes target books, creates orders, changes cash, mutates an
operating ledger, promotes a challenger, or runs a full rebuild.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import os
import re
import subprocess
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd
import pandas_market_calendars as mcal
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.preprocessing import StandardScaler


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = "run287-expected-return-challenger-v1"
READY_STATUS = "READY_EXPECTED_RETURN_FORWARD_REVIEW_ONLY"
BLOCKED_STATUS = "BLOCKED_EXPECTED_RETURN_CHALLENGER"
TARGET_KINDS = ("absolute", "benchmark_excess", "sector_neutral")
HORIZONS = (21, 63, 126)
EXPECTED_CONTRACT_SHA256 = (
    "ef61acafc2c42b86d75d85becea816a4bca8e05fbbc392e77fa92b075c728b63"
)
FORBIDDEN_FEATURE_RE = re.compile(
    r"(^|_)(future|forward|label|target|outcome)(_|$)|"
    r"^r_(1m|3m|6m|12m|24m|36m)$|^bench_(r|ret)_",
    re.IGNORECASE,
)
NYSE = mcal.get_calendar("NYSE")
FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
REPOSITORY = "wscha231/r1000-quant-engine"


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise ValueError(f"duplicate JSON key:{key}")
        out[key] = value
    return out


def read_json(path: Path) -> Any:
    return json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=reject_duplicate_json_keys,
    )


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def git_blob_bytes(commit_sha: str, path: str) -> bytes:
    commit_sha = str(commit_sha or "").lower()
    if not FULL_SHA_RE.fullmatch(commit_sha):
        raise ValueError("Git JSON blob commit identity is invalid")
    if not path or path.startswith(("/", "\\")) or ".." in Path(path).parts:
        raise ValueError("Git JSON blob path is invalid")
    return subprocess.check_output(
        ["git", "show", f"{commit_sha}:{path}"],
        cwd=REPO_ROOT,
        timeout=30,
        stderr=subprocess.DEVNULL,
    )


def git_blob_sha256(commit_sha: str, path: str) -> str:
    return hashlib.sha256(git_blob_bytes(commit_sha, path)).hexdigest()


def git_json_blob_canonical_sha256(commit_sha: str, path: str) -> str:
    raw = git_blob_bytes(commit_sha, path)
    value = json.loads(
        raw.decode("utf-8"), object_pairs_hook=reject_duplicate_json_keys
    )
    return canonical_sha256(value)


def repository_namespace_payload(
    branches: Any,
    pull_requests: Any,
    *,
    live_api_shape: bool,
) -> dict[str, Any]:
    if not isinstance(branches, list) or not isinstance(pull_requests, list):
        raise ValueError("repository namespace collections are missing")
    branch_rows: list[dict[str, Any]] = []
    branch_names: set[str] = set()
    for row in branches:
        if not isinstance(row, dict):
            raise ValueError("repository branch namespace row is malformed")
        name = str(row.get("name") or "")
        head_sha = str(
            ((row.get("commit") or {}).get("sha"))
            if live_api_shape and isinstance(row.get("commit"), dict)
            else row.get("head_sha") or ""
        ).lower()
        if not name or name in branch_names or not FULL_SHA_RE.fullmatch(head_sha):
            raise ValueError("repository branch namespace identity is invalid")
        branch_names.add(name)
        branch_rows.append({"name": name, "head_sha": head_sha})
    pr_rows: list[dict[str, Any]] = []
    pr_numbers: set[int] = set()
    for row in pull_requests:
        if not isinstance(row, dict):
            raise ValueError("repository pull-request namespace row is malformed")
        number = row.get("number")
        if live_api_shape:
            head = row.get("head") if isinstance(row.get("head"), dict) else {}
            base = row.get("base") if isinstance(row.get("base"), dict) else {}
            head_branch = str(head.get("ref") or "")
            head_sha = str(head.get("sha") or "").lower()
            base_sha = str(base.get("sha") or "").lower()
            updated_at = str(row.get("updated_at") or "")
        else:
            head_branch = str(row.get("head_branch") or "")
            head_sha = str(row.get("head_sha") or "").lower()
            base_sha = str(row.get("base_sha") or "").lower()
            updated_at = str(row.get("updated_at") or "")
        if (
            type(number) is not int
            or number <= 0
            or number in pr_numbers
            or not FULL_SHA_RE.fullmatch(head_sha)
            or not FULL_SHA_RE.fullmatch(base_sha)
            or not head_branch
            or not updated_at
        ):
            raise ValueError("repository pull-request namespace identity is invalid")
        pr_numbers.add(number)
        pr_rows.append(
            {
                "number": number,
                "head_branch": head_branch,
                "head_sha": head_sha,
                "base_sha": base_sha,
                "updated_at": updated_at,
            }
        )
    return {
        "branches": sorted(branch_rows, key=lambda row: row["name"]),
        "pull_requests": sorted(pr_rows, key=lambda row: row["number"]),
    }


def source_repository_namespace(source_census: Mapping[str, Any]) -> dict[str, Any]:
    return repository_namespace_payload(
        source_census.get("branches"),
        source_census.get("pull_requests"),
        live_api_shape=False,
    )


def gh_paginated_collection(endpoint: str) -> list[dict[str, Any]]:
    raw = subprocess.check_output(
        ["gh", "api", "--paginate", "--slurp", endpoint],
        cwd=REPO_ROOT,
        timeout=60,
    )
    payload = json.loads(
        raw.decode("utf-8"), object_pairs_hook=reject_duplicate_json_keys
    )
    if not isinstance(payload, list):
        raise ValueError("GitHub namespace response is not a list")
    pages = payload if all(isinstance(item, list) for item in payload) else [payload]
    rows = [item for page in pages for item in page]
    if any(not isinstance(item, dict) for item in rows):
        raise ValueError("GitHub namespace response contains a malformed row")
    return rows


def load_live_repository_namespace() -> dict[str, Any]:
    branches = gh_paginated_collection(
        f"repos/{REPOSITORY}/branches?per_page=100"
    )
    pull_requests = gh_paginated_collection(
        f"repos/{REPOSITORY}/pulls?state=all&per_page=100"
    )
    return repository_namespace_payload(
        branches, pull_requests, live_api_shape=True
    )


def git_is_ancestor(ancestor: str, descendant: str) -> bool:
    if not FULL_SHA_RE.fullmatch(ancestor) or not FULL_SHA_RE.fullmatch(descendant):
        return False
    try:
        result = subprocess.run(
            ["git", "merge-base", "--is-ancestor", ancestor, descendant],
            cwd=REPO_ROOT,
            timeout=10,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        return False
    return result.returncode == 0


def git_default_branch_sha() -> str:
    event_path = Path(str(os.environ.get("GITHUB_EVENT_PATH") or ""))
    if event_path.is_file():
        try:
            event = read_json(event_path)
            repository = ((event.get("repository") or {}).get("full_name"))
            pull_request = event.get("pull_request") or {}
            base = pull_request.get("base") or {}
            sha = str(base.get("sha") or "").lower()
            if (
                repository == REPOSITORY
                and base.get("ref") == "master"
                and FULL_SHA_RE.fullmatch(sha)
            ):
                return sha
        except Exception:
            pass
    for ref in ("refs/remotes/origin/master", "refs/heads/master"):
        try:
            sha = subprocess.check_output(
                ["git", "rev-parse", "--verify", ref],
                cwd=REPO_ROOT,
                text=True,
                timeout=10,
                stderr=subprocess.DEVNULL,
            ).strip().lower()
        except Exception:
            continue
        if FULL_SHA_RE.fullmatch(sha):
            return sha
    return ""


def load_canonical_u0_artifact(
    artifact_id: int,
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    if type(artifact_id) is not int or artifact_id <= 0:
        raise ValueError("invalid U0 accepted artifact id")
    gate = contract["historical_gate"]
    artifact_raw = subprocess.check_output(
        [
            "gh",
            "api",
            f"repos/{REPOSITORY}/actions/artifacts/{artifact_id}",
        ],
        cwd=REPO_ROOT,
        timeout=30,
    )
    artifact = json.loads(
        artifact_raw.decode("utf-8"),
        object_pairs_hook=reject_duplicate_json_keys,
    )
    workflow_run = artifact.get("workflow_run") or {}
    run_id = workflow_run.get("id")
    if type(run_id) is not int or run_id <= 0:
        raise ValueError("U0 artifact lacks workflow run identity")
    if (
        artifact.get("name") != gate["accepted_artifact_name"]
        or artifact.get("expired") is not False
    ):
        raise ValueError("U0 artifact identity is not accepted")
    run_raw = subprocess.check_output(
        ["gh", "api", f"repos/{REPOSITORY}/actions/runs/{run_id}"],
        cwd=REPO_ROOT,
        timeout=30,
    )
    run = json.loads(
        run_raw.decode("utf-8"),
        object_pairs_hook=reject_duplicate_json_keys,
    )
    if (
        run.get("id") != run_id
        or run.get("path") != gate["accepted_workflow_path"]
        or run.get("event") != "workflow_dispatch"
        or run.get("head_branch") != gate["default_branch"]
        or run.get("status") != "completed"
        or run.get("conclusion") != "success"
    ):
        raise ValueError("U0 artifact workflow run is not canonical")
    zip_bytes = subprocess.check_output(
        [
            "gh",
            "api",
            f"repos/{REPOSITORY}/actions/artifacts/{artifact_id}/zip",
        ],
        cwd=REPO_ROOT,
        timeout=60,
    )
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
        names = archive.namelist()
        source_census_name = gate["accepted_artifact_source_census_file"]
        census_name = gate["accepted_artifact_census_file"]
        evidence_name = gate["accepted_artifact_evidence_file"]
        if (
            names.count(source_census_name) != 1
            or names.count(census_name) != 1
            or names.count(evidence_name) != 1
        ):
            raise ValueError("U0 artifact canonical files are missing or duplicated")
        source_census = json.loads(
            archive.read(source_census_name).decode("utf-8"),
            object_pairs_hook=reject_duplicate_json_keys,
        )
        census = json.loads(
            archive.read(census_name).decode("utf-8"),
            object_pairs_hook=reject_duplicate_json_keys,
        )
        evidence = json.loads(
            archive.read(evidence_name).decode("utf-8"),
            object_pairs_hook=reject_duplicate_json_keys,
        )
    audit_sha = str(census.get("audit_default_branch_sha") or "").lower()
    if (
        str(run.get("head_sha") or "").lower() != audit_sha
        or str(workflow_run.get("head_sha") or "").lower() != audit_sha
        or workflow_run.get("head_branch") != gate["default_branch"]
    ):
        raise ValueError("U0 artifact is not bound to its audited master head")
    source_observed_at = str(source_census.get("generated_at_utc") or "")
    try:
        observed_at = datetime.fromisoformat(
            source_observed_at.replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise ValueError("U0 source census observation time is invalid") from exc
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("U0 source census observation time lacks a timezone")
    expected_namespace_sha256 = canonical_sha256(
        source_repository_namespace(source_census)
    )
    if (
        evidence.get("source_observed_at_utc") != source_observed_at
        or evidence.get("repository_namespace_sha256")
        != expected_namespace_sha256
    ):
        raise ValueError("U0 acceptance does not attest its source observation")
    live_namespace_sha256 = canonical_sha256(load_live_repository_namespace())
    if live_namespace_sha256 != expected_namespace_sha256:
        raise ValueError("U0 source census is stale for the live repository namespace")
    return {
        "verified": True,
        "artifact_id": artifact_id,
        "workflow_run_id": run_id,
        "workflow_path": run["path"],
        "head_sha": audit_sha,
        "artifact_digest": artifact.get("digest"),
        "source_observed_at_utc": source_observed_at,
        "repository_namespace_sha256": expected_namespace_sha256,
        "live_repository_namespace_sha256": live_namespace_sha256,
        "source_census": source_census,
        "census": census,
        "accepted_evidence": evidence,
    }


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
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return finite(value)
    if isinstance(value, (pd.Timestamp, datetime)):
        return pd.Timestamp(value).isoformat()
    if value is pd.NaT:
        return None
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            json_clean(value), indent=2, sort_keys=True, ensure_ascii=False
        )
        + "\n",
        encoding="utf-8",
    )


def validate_contract(contract: Any) -> dict[str, Any]:
    if not isinstance(contract, dict):
        raise ValueError("expected-return contract must be an object")
    if contract.get("schema_version") != (
        "run287-expected-return-challenger-contract-v1"
    ):
        raise ValueError("expected-return contract schema mismatch")
    if contract.get("family_id") != (
        "future_expected_excess_return_multihorizon_v1"
    ):
        raise ValueError("expected-return family identity mismatch")
    horizons = contract.get("horizons")
    features = contract.get("features")
    if not isinstance(horizons, dict) or set(horizons) != {
        "21",
        "63",
        "126",
    }:
        raise ValueError("expected-return horizons must be exactly 21/63/126")
    if not isinstance(features, dict) or set(features) != set(horizons):
        raise ValueError("expected-return feature groups mismatch")
    score_weight = 0.0
    for horizon in HORIZONS:
        spec = horizons[str(horizon)]
        names = features[str(horizon)]
        if not isinstance(spec, dict) or not isinstance(names, list) or not names:
            raise ValueError(f"invalid horizon contract:{horizon}")
        if len(names) != len(set(names)) or any(
            not isinstance(name, str) or not name for name in names
        ):
            raise ValueError(f"invalid feature whitelist:{horizon}")
        forbidden = sorted(name for name in names if FORBIDDEN_FEATURE_RE.search(name))
        if forbidden:
            raise ValueError("future/label columns in feature whitelist:" + ",".join(forbidden))
        for key in (
            "stock_return",
            "benchmark_return",
            "stock_label_end",
            "benchmark_label_end",
        ):
            if not isinstance(spec.get(key), str) or not spec[key]:
                raise ValueError(f"missing horizon label contract:{horizon}:{key}")
        score_weight += float(spec.get("score_weight") or 0.0)
    if abs(score_weight - 1.0) > 1e-12:
        raise ValueError("horizon score weights must sum to one")
    fixed_score_weights = {"21": 0.0, "63": 0.65, "126": 0.35}
    for horizon, expected_weight in fixed_score_weights.items():
        actual_weight = float(horizons[horizon].get("score_weight") or 0.0)
        if not math.isclose(actual_weight, expected_weight, rel_tol=0.0, abs_tol=1e-12):
            raise ValueError(
                f"fixed horizon score weight mismatch:{horizon}:"
                f"expected={expected_weight}:actual={actual_weight}"
            )
    purge_and_windows = contract.get("purge_and_windows") or {}
    embargo_sessions = purge_and_windows.get("embargo_nyse_sessions")
    if type(embargo_sessions) is not int or embargo_sessions != 126:
        raise ValueError("fixed NYSE-session embargo must equal 126")
    alpha_mix = (contract.get("target_contract") or {}).get(
        "benchmark_sector_mix"
    ) or {}
    for key, expected_weight in {
        "benchmark_excess": 0.7,
        "sector_neutral": 0.3,
    }.items():
        actual_weight = float(alpha_mix.get(key) or 0.0)
        if not math.isclose(actual_weight, expected_weight, rel_tol=0.0, abs_tol=1e-12):
            raise ValueError(
                f"fixed alpha target mix mismatch:{key}:"
                f"expected={expected_weight}:actual={actual_weight}"
            )
    model = contract.get("model") or {}
    if (
        model.get("parameter_tuning_allowed") is not False
        or float(model.get("long_history_weight") or 0.0)
        + float(model.get("recent_history_weight") or 0.0)
        != 1.0
    ):
        raise ValueError("fixed model blend contract mismatch")
    safety = contract.get("safety") or {}
    if safety.get("research_only") is not True or any(
        safety.get(key) is not False
        for key in (
            "automatic_promotion_allowed",
            "champion_change_allowed",
            "portfolio_mutation_allowed",
            "target_books_written",
            "orders_generated",
            "operating_ledger_mutated",
            "production_or_live_trading_enabled",
        )
    ):
        raise ValueError("expected-return safety contract mismatch")
    historical_gate = contract.get("historical_gate") or {}
    if (
        historical_gate.get("source_inventory_path")
        != "docs/run287_u0_experiment_inventory.json"
        or historical_gate.get("live_repository_namespace_match_required") is not True
    ):
        raise ValueError("expected-return U0 freshness contract mismatch")
    actual_contract_sha256 = canonical_sha256(contract)
    if actual_contract_sha256 != EXPECTED_CONTRACT_SHA256:
        raise ValueError(
            "expected-return contract hash mismatch:"
            f"expected={EXPECTED_CONTRACT_SHA256}:actual={actual_contract_sha256}"
        )
    return contract


def u0_gate(
    census: Any,
    accepted_evidence: Any,
    canonical_artifact: Any,
    contract: Mapping[str, Any],
) -> list[str]:
    blockers: list[str] = []
    gate = contract["historical_gate"]
    if not isinstance(census, dict):
        return ["u0_census_not_an_object"]
    if census.get("schema_version") != gate["u0_schema_version"]:
        blockers.append("u0_census_schema_mismatch")
    if census.get("repository") != gate["repository"]:
        blockers.append("u0_census_repository_mismatch")
    if census.get("audit_default_branch") != gate["default_branch"]:
        blockers.append("u0_census_default_branch_mismatch")
    if not isinstance(canonical_artifact, dict) or (
        canonical_artifact.get("verified") is not True
    ):
        canonical_artifact = {}
        blockers.append("u0_canonical_artifact_not_verified")
    if canonical_sha256(census) != canonical_sha256(
        canonical_artifact.get("census")
    ):
        blockers.append("u0_census_not_exact_canonical_artifact")
    if canonical_sha256(accepted_evidence) != canonical_sha256(
        canonical_artifact.get("accepted_evidence")
    ):
        blockers.append("u0_evidence_not_exact_canonical_artifact")
    canonical_source = canonical_artifact.get("source_census")
    if not isinstance(canonical_source, dict):
        canonical_source = {}
        blockers.append("u0_canonical_source_census_missing")
    if not isinstance(accepted_evidence, dict):
        accepted_evidence = {}
        blockers.append("u0_accepted_evidence_not_an_object")
    source_observed_at = str(canonical_source.get("generated_at_utc") or "")
    try:
        parsed_observed_at = datetime.fromisoformat(
            source_observed_at.replace("Z", "+00:00")
        )
        if parsed_observed_at.tzinfo is None or parsed_observed_at.utcoffset() is None:
            raise ValueError("timezone missing")
    except ValueError:
        blockers.append("u0_source_census_observation_time_invalid")
    try:
        repository_namespace_sha256 = canonical_sha256(
            source_repository_namespace(canonical_source)
        )
    except Exception:
        repository_namespace_sha256 = ""
        blockers.append("u0_source_census_repository_namespace_invalid")
    if accepted_evidence.get("source_observed_at_utc") != source_observed_at:
        blockers.append("u0_source_observation_not_exact_accepted_artifact")
    if accepted_evidence.get("repository_namespace_sha256") != (
        repository_namespace_sha256
    ):
        blockers.append("u0_repository_namespace_not_exact_accepted_artifact")
    if census.get("source_observed_at_utc") != source_observed_at:
        blockers.append("u0_recovery_source_observation_mismatch")
    if census.get("repository_namespace_sha256") != repository_namespace_sha256:
        blockers.append("u0_recovery_repository_namespace_mismatch")
    if (
        canonical_artifact.get("source_observed_at_utc") != source_observed_at
        or canonical_artifact.get("repository_namespace_sha256")
        != repository_namespace_sha256
        or canonical_artifact.get("live_repository_namespace_sha256")
        != repository_namespace_sha256
    ):
        blockers.append("u0_live_repository_namespace_not_current")
    if (
        accepted_evidence.get("schema_version")
        != gate["accepted_evidence_schema_version"]
    ):
        blockers.append("u0_accepted_evidence_schema_mismatch")
    if accepted_evidence.get("repository") != gate["repository"]:
        blockers.append("u0_accepted_evidence_repository_mismatch")
    if accepted_evidence.get("audit_default_branch") != gate["default_branch"]:
        blockers.append("u0_accepted_evidence_default_branch_mismatch")
    if (
        accepted_evidence.get("workflow_identity")
        != gate["accepted_evidence_workflow_identity"]
    ):
        blockers.append("u0_accepted_evidence_workflow_mismatch")
    if str(accepted_evidence.get("recovery_census_sha256") or "").lower() != (
        canonical_sha256(census)
    ):
        blockers.append("u0_census_not_exact_accepted_artifact")
    source_sha256 = canonical_sha256(canonical_source)
    if str(accepted_evidence.get("source_census_sha256") or "").lower() != (
        source_sha256
    ):
        blockers.append("u0_source_census_not_exact_accepted_artifact")
    if str(census.get("source_census_sha256") or "").lower() != source_sha256:
        blockers.append("u0_recovery_source_census_hash_mismatch")
    for evidence_key, gate_key in (
        ("recovery_contract_sha256", "accepted_u0_recovery_contract_sha256"),
        ("acceptance_contract_sha256", "accepted_u0_acceptance_contract_sha256"),
    ):
        if str(accepted_evidence.get(evidence_key) or "").lower() != str(
            gate.get(gate_key) or ""
        ).lower():
            blockers.append(f"u0_{evidence_key}_mismatch")
    if str(census.get("recovery_contract_sha256") or "").lower() != str(
        gate.get("accepted_u0_recovery_contract_sha256") or ""
    ).lower():
        blockers.append("u0_recovery_contract_hash_mismatch")
    if str(census.get("source_inventory_sha256") or "").lower() != str(
        accepted_evidence.get("source_inventory_sha256") or ""
    ).lower():
        blockers.append("u0_source_inventory_hash_mismatch")
    for key, value in (
        ("source_inventory_sha256", census.get("source_inventory_sha256")),
        ("source_census_sha256", census.get("source_census_sha256")),
        ("recovery_contract_sha256", census.get("recovery_contract_sha256")),
    ):
        if not SHA256_RE.fullmatch(str(value or "").lower()):
            blockers.append(f"u0_recovery_hash_invalid:{key}")
    audit_sha = str(census.get("audit_default_branch_sha") or "").lower()
    if str(accepted_evidence.get("audit_default_branch_sha") or "").lower() != audit_sha:
        blockers.append("u0_accepted_evidence_audit_sha_mismatch")
    current_sha = git_head().lower()
    accepted_default_sha = git_default_branch_sha()
    try:
        current_inventory_sha256 = git_json_blob_canonical_sha256(
            current_sha, gate["source_inventory_path"]
        )
        accepted_inventory_git_blob_sha256 = git_blob_sha256(
            audit_sha, gate["source_inventory_path"]
        )
        current_inventory_git_blob_sha256 = git_blob_sha256(
            current_sha, gate["source_inventory_path"]
        )
    except Exception:
        current_inventory_sha256 = ""
        accepted_inventory_git_blob_sha256 = ""
        current_inventory_git_blob_sha256 = ""
        blockers.append("u0_current_runner_inventory_git_blob_unreadable")
    accepted_inventory_sha256 = str(
        accepted_evidence.get("source_inventory_sha256") or ""
    ).lower()
    if (
        current_inventory_sha256 != accepted_inventory_sha256
        or str(census.get("source_inventory_sha256") or "").lower()
        != current_inventory_sha256
    ):
        blockers.append("u0_source_inventory_not_current_runner_git_blob")
    if current_inventory_git_blob_sha256 != accepted_inventory_git_blob_sha256:
        blockers.append("u0_source_inventory_git_blob_changed_since_acceptance")
    if not FULL_SHA_RE.fullmatch(audit_sha):
        blockers.append("u0_census_audit_sha_invalid")
    else:
        if audit_sha != accepted_default_sha:
            blockers.append("u0_census_audit_sha_not_current_default_branch")
        if not git_is_ancestor(audit_sha, current_sha):
            blockers.append("u0_census_audit_sha_not_ancestor_of_runner")
    if str(canonical_source.get("audit_default_branch_sha") or "").lower() != (
        audit_sha
    ):
        blockers.append("u0_source_census_audit_sha_mismatch")
    if canonical_source.get("schema_version") != "run287-u0-v2-github-census-v1":
        blockers.append("u0_source_census_schema_mismatch")
    source = canonical_source.get("source_contract")
    if not isinstance(source, dict):
        source = {}
        blockers.append("u0_source_census_contract_missing")
    for key in (
        "branch_payload_sha256",
        "pull_request_payload_sha256",
        "normalized_branch_rows_sha256",
        "normalized_pull_request_rows_sha256",
    ):
        if not SHA256_RE.fullmatch(str(source.get(key) or "").lower()):
            blockers.append(f"u0_source_census_hash_invalid:{key}")
    if (
        source.get("metadata_only") is not True
        or source.get("fullrun_executed") is not False
        or source.get("production_or_live_mutated") is not False
        or source.get("champion_changed") is not False
    ):
        blockers.append("u0_source_census_safety_mismatch")
    branches = canonical_source.get("branches")
    pull_requests = canonical_source.get("pull_requests")
    if not isinstance(branches, list) or not isinstance(pull_requests, list):
        blockers.append("u0_source_census_normalized_records_missing")
        branches = []
        pull_requests = []
    if canonical_sha256(branches) != source.get("normalized_branch_rows_sha256"):
        blockers.append("u0_source_census_normalized_branch_hash_mismatch")
    if canonical_sha256(pull_requests) != source.get(
        "normalized_pull_request_rows_sha256"
    ):
        blockers.append("u0_source_census_normalized_pr_hash_mismatch")
    master_rows = [
        row
        for row in branches
        if isinstance(row, dict) and row.get("name") == gate["default_branch"]
    ]
    if (
        len(master_rows) != 1
        or str(master_rows[0].get("head_sha") or "").lower() != audit_sha
        or master_rows[0].get("ancestry") != "IDENTICAL_TO_AUDIT_HEAD"
    ):
        blockers.append("u0_source_census_default_branch_record_mismatch")
    recovery_safety = census.get("safety")
    required_recovery_safety = {
        "metadata_only": True,
        "fullrun_allowed": False,
        "target_order_ledger_mutation_allowed": False,
        "production_or_live_trading_allowed": False,
        "automatic_promotion_allowed": False,
        "acceptance_gate_migration_allowed_by_this_contract": False,
    }
    if recovery_safety != required_recovery_safety:
        blockers.append("u0_recovery_safety_mismatch")
    summary = census.get("summary")
    if not isinstance(summary, dict):
        summary = {}
        blockers.append("u0_census_summary_missing")
    if summary.get("historical_experiment_census_complete") is not True:
        blockers.append("u0_historical_experiment_census_incomplete")
    if summary.get("historical_challenger_preregistration_ready") is not True:
        blockers.append("u0_historical_challenger_preregistration_not_ready")
    if summary.get("historical_challenger_allowed") is not False:
        blockers.append("u0_recovery_prematurely_authorized_challenger")
    if census.get("census_completion_blockers") != []:
        blockers.append("u0_census_completion_blockers_not_empty")
    if sorted(census.get("acceptance_migration_blockers") or []) != sorted(
        gate["required_recovery_migration_blockers"]
    ):
        blockers.append("u0_recovery_migration_blockers_mismatch")
    trial_floor = summary.get("conservative_historical_trial_count_lower_bound")
    if (
        type(trial_floor) is not int
        or trial_floor
        < gate["minimum_conservative_historical_trial_count_lower_bound"]
        or accepted_evidence.get(
            "conservative_historical_trial_count_lower_bound"
        )
        != trial_floor
    ):
        blockers.append("u0_conservative_historical_trial_floor_invalid")
    if (
        accepted_evidence.get("historical_experiment_census_complete") is not True
        or accepted_evidence.get(
            "historical_challenger_preregistration_ready"
        )
        is not True
        or accepted_evidence.get(
            "historical_challenger_research_fit_allowed"
        )
        is not True
        or accepted_evidence.get("historical_broker_backtest_allowed") is not False
        or accepted_evidence.get("legacy_result_promotion_allowed") is not False
        or accepted_evidence.get("promotion_blockers") != []
        or accepted_evidence.get("target_order_ledger_mutation_allowed") is not False
        or accepted_evidence.get("production_or_live_trading_allowed") is not False
        or accepted_evidence.get("automatic_promotion_allowed") is not False
        or accepted_evidence.get("fullrun_allowed") is not False
    ):
        blockers.append("u0_accepted_evidence_not_approved")
    return sorted(set(blockers))


def required_columns(contract: Mapping[str, Any]) -> list[str]:
    required = set(contract["data_policy"]["required_identity_columns"])
    for horizon in HORIZONS:
        spec = contract["horizons"][str(horizon)]
        if float(spec["score_weight"]) > 0.0:
            required.update(contract["features"][str(horizon)])
            required.update(
                spec[key]
                for key in (
                    "stock_return",
                    "benchmark_return",
                    "stock_label_end",
                    "benchmark_label_end",
                )
            )
    return sorted(required)


def input_readiness(frame: pd.DataFrame, contract: Mapping[str, Any]) -> list[str]:
    blockers: list[str] = []
    missing = sorted(set(required_columns(contract)) - set(frame.columns))
    if missing:
        blockers.append("feature_store_missing_required_columns:" + ",".join(missing))
    if frame.empty:
        return ["feature_store_empty"]
    feature_dates = (
        pd.to_datetime(frame["feature_date"], errors="coerce")
        if "feature_date" in frame.columns
        else pd.Series(pd.NaT, index=frame.index, dtype="datetime64[ns]")
    )
    for horizon in HORIZONS:
        spec = contract["horizons"][str(horizon)]
        if float(spec["score_weight"]) <= 0.0:
            continue
        for feature in contract["features"][str(horizon)]:
            if feature in frame.columns:
                numeric = pd.to_numeric(frame[feature], errors="coerce").replace(
                    [np.inf, -np.inf], np.nan
                )
                if numeric.notna().sum() == 0:
                    blockers.append(
                        f"selection_feature_unusable:{horizon}:{feature}"
                    )
                elif (
                    numeric.notna()
                    .groupby(feature_dates)
                    .sum()
                    .eq(0)
                    .any()
                ):
                    blockers.append(
                        f"selection_feature_unusable_on_decision_date:"
                        f"{horizon}:{feature}"
                    )
        for key in (
            "stock_return",
            "benchmark_return",
            "stock_label_end",
            "benchmark_label_end",
        ):
            column = spec[key]
            if column in frame.columns and frame[column].notna().sum() == 0:
                blockers.append(f"label_provenance_empty:{column}")
    return sorted(set(blockers))


def _rank_group(values: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    if numeric.notna().sum() < 2 or numeric.nunique(dropna=True) < 2:
        return pd.Series(0.5, index=values.index, dtype=float)
    return numeric.rank(pct=True, method="average").fillna(0.5).clip(0.0, 1.0)


def expected_nyse_label_ends(
    feature_dates: pd.Series, horizon: int
) -> pd.Series:
    dates = pd.to_datetime(feature_dates, errors="coerce").dt.normalize()
    out = pd.Series(pd.NaT, index=feature_dates.index, dtype="datetime64[ns]")
    valid_dates = dates.dropna().drop_duplicates().sort_values()
    if valid_dates.empty:
        return out
    sessions = NYSE.valid_days(
        start_date=valid_dates.min() - pd.Timedelta(days=7),
        end_date=valid_dates.max() + pd.Timedelta(days=max(60, horizon * 3)),
    ).tz_localize(None).normalize()
    mapping: dict[pd.Timestamp, pd.Timestamp] = {}
    for decision in valid_dates:
        future = sessions[sessions > decision]
        if len(future) > horizon:
            # Canonical labels enter on the first session after the decision
            # and measure `horizon` price intervals, ending at future[horizon].
            mapping[pd.Timestamp(decision)] = pd.Timestamp(future[horizon])
    return dates.map(mapping)


def prepare_frame(frame: pd.DataFrame, contract: Mapping[str, Any]) -> pd.DataFrame:
    blockers = input_readiness(frame, contract)
    if blockers:
        raise ValueError(";".join(blockers))
    out = frame.copy()
    out["feature_date"] = pd.to_datetime(out["feature_date"], errors="coerce").dt.normalize()
    out["rebalance_date"] = pd.to_datetime(out["rebalance_date"], errors="coerce").dt.normalize()
    if out[["feature_date", "rebalance_date"]].isna().any().any():
        raise ValueError("invalid feature or rebalance date")
    if not out["feature_date"].eq(out["rebalance_date"]).all():
        raise ValueError("feature_date and rebalance_date identity mismatch")
    if out["ticker"].isna().any():
        raise ValueError("null ticker in feature store")
    if out["sector"].isna().any():
        raise ValueError("null sector in feature store")
    out["ticker"] = out["ticker"].astype(str).str.strip().str.upper().str.replace(".", "-", regex=False)
    out["sector"] = out["sector"].astype(str).str.strip()
    if out["ticker"].eq("").any():
        raise ValueError("empty ticker in feature store")
    if out["sector"].eq("").any():
        raise ValueError("empty sector in feature store")
    benchmark_identity = out["benchmark_identity"].astype(str).str.strip().str.upper()
    benchmark_source = out["benchmark_source"].astype(str).str.strip().str.upper()
    expected_benchmark = str(contract["data_policy"]["canonical_benchmark"]).upper()
    expected_source = str(
        contract["data_policy"]["canonical_benchmark_source"]
    ).upper()
    if not benchmark_identity.eq(expected_benchmark).all():
        raise ValueError("benchmark identity provenance mismatch")
    if not benchmark_source.eq(expected_source).all():
        raise ValueError("benchmark source provenance mismatch")
    out["benchmark_identity"] = benchmark_identity
    out["benchmark_source"] = benchmark_source
    if out.duplicated(["feature_date", "ticker"]).any():
        raise ValueError("duplicate feature_date/ticker rows")

    all_features = sorted(
        name
        for name in {
            feature
            for horizon in HORIZONS
            for feature in contract["features"][str(horizon)]
        }
        if name in out.columns
        and pd.to_numeric(out[name], errors="coerce")
        .replace([np.inf, -np.inf], np.nan)
        .notna()
        .any()
    )
    for name in all_features:
        out[f"xrank__{name}"] = out.groupby("feature_date", group_keys=False)[name].transform(_rank_group)
    for horizon in HORIZONS:
        spec = contract["horizons"][str(horizon)]
        if float(spec["score_weight"]) <= 0.0:
            for key in ("stock_return", "benchmark_return"):
                if spec[key] not in out.columns:
                    out[spec[key]] = np.nan
            for key in ("stock_label_end", "benchmark_label_end"):
                if spec[key] not in out.columns:
                    out[spec[key]] = pd.NaT
        stock = pd.to_numeric(out[spec["stock_return"]], errors="coerce").replace(
            [np.inf, -np.inf], np.nan
        )
        benchmark = pd.to_numeric(
            out[spec["benchmark_return"]], errors="coerce"
        ).replace([np.inf, -np.inf], np.nan)
        stock_end = pd.to_datetime(out[spec["stock_label_end"]], errors="coerce").dt.normalize()
        benchmark_end = pd.to_datetime(out[spec["benchmark_label_end"]], errors="coerce").dt.normalize()
        if float(spec["score_weight"]) > 0.0:
            raw_columns = [
                out[spec["stock_return"]],
                out[spec["benchmark_return"]],
                out[spec["stock_label_end"]],
                out[spec["benchmark_label_end"]],
            ]
            raw_present = [
                column.notna() & column.astype(str).str.strip().ne("")
                for column in raw_columns
            ]
            parsed_present = [
                stock.notna(),
                benchmark.notna(),
                stock_end.notna(),
                benchmark_end.notna(),
            ]
            if any(
                raw.ne(parsed).any()
                for raw, parsed in zip(raw_present, parsed_present)
            ):
                raise ValueError(f"unparseable required label provenance:{horizon}")
            present_count = sum(mask.astype(int) for mask in parsed_present)
            if present_count.between(1, 3).any():
                raise ValueError(f"partial required label provenance:{horizon}")
        if benchmark.groupby(out["feature_date"]).nunique(dropna=True).gt(1).any():
            raise ValueError(f"benchmark return is not unique by decision:{horizon}")
        if benchmark_end.groupby(out["feature_date"]).nunique(dropna=True).gt(1).any():
            raise ValueError(f"benchmark label end is not unique by decision:{horizon}")
        complete = stock.notna() & benchmark.notna() & stock_end.notna() & benchmark_end.notna()
        if stock_end.loc[complete].ne(benchmark_end.loc[complete]).any():
            raise ValueError(f"stock/benchmark label end mismatch:{horizon}")
        if (
            stock_end.where(complete)
            .groupby(out["feature_date"])
            .nunique(dropna=True)
            .gt(1)
            .any()
        ):
            raise ValueError(f"mixed cross-sectional label end dates:{horizon}")
        expected_end = expected_nyse_label_ends(out["feature_date"], horizon)
        if stock_end.loc[complete].ne(expected_end.loc[complete]).any():
            raise ValueError(f"label end is not exact NYSE horizon:{horizon}")
        row_available = pd.concat([stock_end, benchmark_end], axis=1).max(axis=1).where(complete)
        # All cross-sectional targets for one decision mature together.
        available = row_available.groupby(out["feature_date"]).transform("max").where(complete)
        absolute = stock.where(complete)
        excess = (stock - benchmark).where(complete)
        sector_size = absolute.groupby(
            [out["feature_date"], out["sector"]]
        ).transform("count")
        sector_mean = absolute.groupby([out["feature_date"], out["sector"]]).transform("mean")
        sector_neutral = (absolute - sector_mean).where(
            complete
            & sector_size.ge(int(contract["target_contract"]["minimum_sector_cross_section"]))
        )
        out[f"label_available_at_{horizon}d"] = available
        out[f"y_absolute_{horizon}d"] = absolute
        out[f"y_benchmark_excess_{horizon}d"] = excess
        out[f"y_sector_neutral_{horizon}d"] = sector_neutral
        out[f"y_downside_{horizon}d"] = absolute.le(0.0).where(complete)
        feature_names = contract["features"][str(horizon)]
        available_features = [name for name in feature_names if name in out.columns]
        out[f"feature_coverage_{horizon}d"] = (
            out[available_features].notna().mean(axis=1)
            if len(available_features) == len(feature_names)
            else 0.0
        )
    return out.sort_values(["feature_date", "ticker"]).reset_index(drop=True)


def nyse_embargo_cutoffs(
    decision_dates: list[pd.Timestamp], embargo_sessions: int
) -> dict[pd.Timestamp, pd.Timestamp | None]:
    if not decision_dates:
        return {}
    start = min(decision_dates) - pd.Timedelta(days=max(730, embargo_sessions * 3))
    end = max(decision_dates) + pd.Timedelta(days=7)
    sessions = NYSE.valid_days(start_date=start, end_date=end).tz_localize(None).normalize()
    out: dict[pd.Timestamp, pd.Timestamp | None] = {}
    for raw_date in decision_dates:
        decision = pd.Timestamp(raw_date).normalize()
        prior = sessions[sessions < decision]
        out[decision] = (
            pd.Timestamp(prior[-embargo_sessions]).normalize()
            if len(prior) >= embargo_sessions
            else None
        )
    return out


def _standardize_fit(
    train_x: np.ndarray, test_x: np.ndarray
) -> tuple[np.ndarray, np.ndarray, StandardScaler]:
    scaler = StandardScaler()
    scaled_train = scaler.fit_transform(train_x)
    scaled_test = scaler.transform(test_x)
    return scaled_train, scaled_test, scaler


def fit_regression_pair(
    train: pd.DataFrame,
    recent: pd.DataFrame,
    test: pd.DataFrame,
    feature_columns: list[str],
    target_column: str,
    contract: Mapping[str, Any],
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]] | None:
    minimum_rows = int(contract["model"]["minimum_training_rows"])
    minimum_dates = int(contract["model"]["minimum_training_decision_dates"])
    train = train.dropna(subset=[target_column])
    recent = recent.dropna(subset=[target_column])
    if (
        len(train) < minimum_rows
        or len(recent) < minimum_rows
        or train["feature_date"].nunique() < minimum_dates
        or recent["feature_date"].nunique() < minimum_dates
    ):
        return None

    def one_fit(source: pd.DataFrame) -> tuple[np.ndarray, dict[str, Any]]:
        x = source[feature_columns].to_numpy(dtype=float)
        test_x = test[feature_columns].to_numpy(dtype=float)
        scaled_x, scaled_test, scaler = _standardize_fit(x, test_x)
        model = Ridge(
            alpha=float(contract["model"]["ridge_alpha"]),
            fit_intercept=True,
        )
        model.fit(scaled_x, source[target_column].to_numpy(dtype=float))
        return model.predict(scaled_test), {
            "intercept": float(model.intercept_),
            "coefficients": {
                feature_columns[index]: float(model.coef_[index])
                for index in range(len(feature_columns))
            },
            "scaler_mean": {
                feature_columns[index]: float(scaler.mean_[index])
                for index in range(len(feature_columns))
            },
            "scaler_scale": {
                feature_columns[index]: float(scaler.scale_[index])
                for index in range(len(feature_columns))
            },
            "training_rows": len(source),
            "training_dates": int(source["feature_date"].nunique()),
        }

    long_prediction, long_model = one_fit(train)
    recent_prediction, recent_model = one_fit(recent)
    long_weight = float(contract["model"]["long_history_weight"])
    recent_weight = float(contract["model"]["recent_history_weight"])
    blended = long_weight * long_prediction + recent_weight * recent_prediction
    return blended, np.abs(long_prediction - recent_prediction), {
        "long_history": long_model,
        "recent_36_month": recent_model,
    }


def fit_classifier_pair(
    train: pd.DataFrame,
    recent: pd.DataFrame,
    test: pd.DataFrame,
    feature_columns: list[str],
    target_column: str,
    contract: Mapping[str, Any],
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]] | None:
    minimum_rows = int(contract["model"]["minimum_training_rows"])
    minimum_dates = int(contract["model"]["minimum_training_decision_dates"])
    train = train.dropna(subset=[target_column]).copy()
    recent = recent.dropna(subset=[target_column]).copy()
    if (
        len(train) < minimum_rows
        or len(recent) < minimum_rows
        or train["feature_date"].nunique() < minimum_dates
        or recent["feature_date"].nunique() < minimum_dates
        or train[target_column].nunique() != 2
        or recent[target_column].nunique() != 2
    ):
        return None

    def one_fit(source: pd.DataFrame) -> tuple[np.ndarray, dict[str, Any]]:
        x = source[feature_columns].to_numpy(dtype=float)
        test_x = test[feature_columns].to_numpy(dtype=float)
        scaled_x, scaled_test, scaler = _standardize_fit(x, test_x)
        model = LogisticRegression(
            C=float(contract["model"]["logistic_c"]),
            class_weight="balanced",
            max_iter=1200,
            random_state=int(contract["model"]["random_seed"]),
        )
        model.fit(scaled_x, source[target_column].astype(int).to_numpy())
        return model.predict_proba(scaled_test)[:, 1], {
            "intercept": float(model.intercept_[0]),
            "coefficients": {
                feature_columns[index]: float(model.coef_[0, index])
                for index in range(len(feature_columns))
            },
            "scaler_mean": {
                feature_columns[index]: float(scaler.mean_[index])
                for index in range(len(feature_columns))
            },
            "scaler_scale": {
                feature_columns[index]: float(scaler.scale_[index])
                for index in range(len(feature_columns))
            },
            "training_rows": len(source),
            "training_dates": int(source["feature_date"].nunique()),
        }

    long_prediction, long_model = one_fit(train)
    recent_prediction, recent_model = one_fit(recent)
    long_weight = float(contract["model"]["long_history_weight"])
    recent_weight = float(contract["model"]["recent_history_weight"])
    blended = long_weight * long_prediction + recent_weight * recent_prediction
    return blended, np.abs(long_prediction - recent_prediction), {
        "long_history": long_model,
        "recent_36_month": recent_model,
    }


def walk_forward_predictions(
    prepared: pd.DataFrame,
    contract: Mapping[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    full_start = pd.Timestamp(contract["purge_and_windows"]["full_start"])
    dates = [
        pd.Timestamp(value).normalize()
        for value in sorted(prepared["feature_date"].dropna().unique())
        if pd.Timestamp(value) >= full_start
    ]
    embargo_sessions = int(contract["purge_and_windows"]["embargo_nyse_sessions"])
    cutoffs = nyse_embargo_cutoffs(dates, embargo_sessions)
    prediction_parts: list[pd.DataFrame] = []
    audit_rows: list[dict[str, Any]] = []
    latest_models: dict[str, Any] = {}
    latest_date = max(dates) if dates else None

    for decision in dates:
        test = prepared[prepared["feature_date"].eq(decision)].copy()
        cutoff = cutoffs.get(decision)
        if cutoff is None:
            for horizon in HORIZONS:
                audit_rows.append(
                    {
                        "decision_date": decision,
                        "horizon": horizon,
                        "status": "BLOCKED_EMBARGO_HISTORY",
                        "embargo_cutoff": None,
                        "training_rows": 0,
                    }
                )
            continue
        date_output = test[["feature_date", "rebalance_date", "ticker", "sector"]].copy()
        selection_horizons_ready = True
        selection_candidate_eligible = pd.Series(True, index=test.index, dtype=bool)
        decision_models: dict[str, Any] = {}
        for horizon in HORIZONS:
            selection_required = float(
                contract["horizons"][str(horizon)]["score_weight"]
            ) > 0.0
            scoring_sector_eligible = test.groupby("sector")["ticker"].transform(
                "size"
            ).ge(int(contract["target_contract"]["minimum_sector_cross_section"]))
            if selection_required:
                selection_candidate_eligible &= scoring_sector_eligible
            feature_columns = [
                f"xrank__{name}" for name in contract["features"][str(horizon)]
            ]
            available_col = f"label_available_at_{horizon}d"
            missing_feature_columns = [
                column for column in feature_columns if column not in prepared.columns
            ]
            if missing_feature_columns:
                if selection_required:
                    raise RuntimeError(
                        "required selection rank features missing:"
                        + ",".join(missing_feature_columns)
                    )
                audit_rows.append(
                    {
                        "decision_date": decision,
                        "horizon": horizon,
                        "status": "UNAVAILABLE_TIMING_ONLY_MISSING_FEATURES",
                        "embargo_cutoff": cutoff,
                        "training_rows": 0,
                        "missing_feature_columns": missing_feature_columns,
                        "scoring_sector_eligible_rows": int(scoring_sector_eligible.sum()),
                        "scoring_sector_ineligible_rows": int((~scoring_sector_eligible).sum()),
                    }
                )
                for column in (
                    "expected_absolute",
                    "expected_benchmark_excess",
                    "expected_sector_neutral",
                    "expected_alpha",
                    "downside_probability",
                    "model_disagreement",
                ):
                    date_output[f"{column}_{horizon}d"] = np.nan
                date_output[f"feature_coverage_{horizon}d"] = test[
                    f"feature_coverage_{horizon}d"
                ].to_numpy()
                for target_kind in TARGET_KINDS:
                    date_output[f"realized_{target_kind}_{horizon}d"] = test[
                        f"y_{target_kind}_{horizon}d"
                    ].to_numpy()
                date_output[f"realized_downside_{horizon}d"] = test[
                    f"y_downside_{horizon}d"
                ].to_numpy()
                date_output[f"label_available_at_{horizon}d"] = test[
                    available_col
                ].to_numpy()
                decision_models[str(horizon)] = {
                    "status": "UNAVAILABLE_TIMING_ONLY_MISSING_FEATURES",
                    "missing_feature_columns": missing_feature_columns,
                }
                continue
            eligible = prepared[
                prepared["feature_date"].le(cutoff)
                & prepared[available_col].notna()
                & prepared[available_col].lt(decision)
            ].copy()
            recent_start = decision - pd.DateOffset(
                months=int(contract["model"]["recent_history_months"])
            )
            recent = eligible[eligible["feature_date"].ge(recent_start)].copy()
            models: dict[str, Any] = {}
            target_results: dict[str, tuple[np.ndarray, np.ndarray, dict[str, Any]]] = {}
            horizon_ready = True
            for target_kind in TARGET_KINDS:
                target_column = f"y_{target_kind}_{horizon}d"
                fitted = fit_regression_pair(
                    eligible,
                    recent,
                    test,
                    feature_columns,
                    target_column,
                    contract,
                )
                if fitted is None:
                    horizon_ready = False
                    break
                target_results[target_kind] = fitted
                models[target_kind] = fitted[2]
            classifier = None
            if horizon_ready:
                classifier = fit_classifier_pair(
                    eligible,
                    recent,
                    test,
                    feature_columns,
                    f"y_downside_{horizon}d",
                    contract,
                )
                if classifier is None:
                    horizon_ready = False
            if not horizon_ready or classifier is None:
                audit_rows.append(
                    {
                        "decision_date": decision,
                        "horizon": horizon,
                        "status": (
                            "BLOCKED_INSUFFICIENT_TRAINING"
                            if selection_required
                            else "UNAVAILABLE_TIMING_ONLY_INSUFFICIENT_TRAINING"
                        ),
                        "embargo_cutoff": cutoff,
                        "training_rows": len(eligible),
                        "training_dates": int(eligible["feature_date"].nunique()),
                        "recent_training_rows": len(recent),
                        "max_training_feature_date": eligible["feature_date"].max() if not eligible.empty else None,
                        "max_label_available_at": eligible[available_col].max() if not eligible.empty else None,
                        "scoring_sector_eligible_rows": int(scoring_sector_eligible.sum()),
                        "scoring_sector_ineligible_rows": int((~scoring_sector_eligible).sum()),
                    }
                )
                if selection_required:
                    selection_horizons_ready = False
                    break
                for column in (
                    "expected_absolute",
                    "expected_benchmark_excess",
                    "expected_sector_neutral",
                    "expected_alpha",
                    "downside_probability",
                    "model_disagreement",
                ):
                    date_output[f"{column}_{horizon}d"] = np.nan
                date_output[f"feature_coverage_{horizon}d"] = test[
                    f"feature_coverage_{horizon}d"
                ].to_numpy()
                for target_kind in TARGET_KINDS:
                    date_output[f"realized_{target_kind}_{horizon}d"] = test[
                        f"y_{target_kind}_{horizon}d"
                    ].to_numpy()
                date_output[f"realized_downside_{horizon}d"] = test[
                    f"y_downside_{horizon}d"
                ].to_numpy()
                date_output[f"label_available_at_{horizon}d"] = test[
                    available_col
                ].to_numpy()
                decision_models[str(horizon)] = {
                    "status": "UNAVAILABLE_TIMING_ONLY_INSUFFICIENT_TRAINING",
                    "features": [
                        name.removeprefix("xrank__") for name in feature_columns
                    ],
                }
                continue
            benchmark_mix = float(
                contract["target_contract"]["benchmark_sector_mix"]["benchmark_excess"]
            )
            sector_mix = float(
                contract["target_contract"]["benchmark_sector_mix"]["sector_neutral"]
            )
            expected_alpha = (
                benchmark_mix * target_results["benchmark_excess"][0]
                + sector_mix * target_results["sector_neutral"][0]
            )
            disagreement = (
                benchmark_mix * target_results["benchmark_excess"][1]
                + sector_mix * target_results["sector_neutral"][1]
            )
            downside_probability = classifier[0]
            date_output[f"expected_absolute_{horizon}d"] = target_results["absolute"][0]
            date_output[f"expected_benchmark_excess_{horizon}d"] = target_results["benchmark_excess"][0]
            date_output[f"expected_sector_neutral_{horizon}d"] = target_results["sector_neutral"][0]
            date_output[f"expected_alpha_{horizon}d"] = expected_alpha
            date_output[f"downside_probability_{horizon}d"] = downside_probability
            date_output[f"model_disagreement_{horizon}d"] = disagreement
            date_output[f"feature_coverage_{horizon}d"] = test[f"feature_coverage_{horizon}d"].to_numpy()
            for target_kind in TARGET_KINDS:
                date_output[f"realized_{target_kind}_{horizon}d"] = test[f"y_{target_kind}_{horizon}d"].to_numpy()
            date_output[f"realized_downside_{horizon}d"] = test[f"y_downside_{horizon}d"].to_numpy()
            date_output[f"label_available_at_{horizon}d"] = test[available_col].to_numpy()
            models["downside"] = classifier[2]
            models["features"] = [
                name.removeprefix("xrank__") for name in feature_columns
            ]
            decision_models[str(horizon)] = models
            audit_rows.append(
                {
                    "decision_date": decision,
                    "horizon": horizon,
                    "status": "FIT_PIT_PURGED",
                    "embargo_cutoff": cutoff,
                    "training_rows": len(eligible),
                    "training_dates": int(eligible["feature_date"].nunique()),
                    "recent_training_rows": len(recent),
                    "recent_training_dates": int(recent["feature_date"].nunique()),
                    "max_training_feature_date": eligible["feature_date"].max(),
                    "max_label_available_at": eligible[available_col].max(),
                    "label_strictly_before_decision": bool(eligible[available_col].max() < decision),
                    "training_feature_on_or_before_embargo": bool(eligible["feature_date"].max() <= cutoff),
                    "feature_set_sha256": canonical_sha256(models["features"]),
                    "scoring_sector_eligible_rows": int(scoring_sector_eligible.sum()),
                    "scoring_sector_ineligible_rows": int((~scoring_sector_eligible).sum()),
                }
            )
        if not selection_horizons_ready:
            continue
        date_output = date_output.loc[selection_candidate_eligible].copy()
        if date_output.empty:
            audit_rows.append(
                {
                    "decision_date": decision,
                    "horizon": "selection",
                    "status": "BLOCKED_NO_SECTOR_NEUTRAL_ELIGIBLE_CANDIDATES",
                    "training_rows": 0,
                }
            )
            continue
        selection_horizons = [
            horizon
            for horizon in HORIZONS
            if float(contract["horizons"][str(horizon)]["score_weight"]) > 0.0
        ]
        horizon_alpha = sum(
            float(contract["horizons"][str(horizon)]["score_weight"])
            * date_output[f"expected_alpha_{horizon}d"]
            for horizon in selection_horizons
        )
        downside = sum(
            float(contract["horizons"][str(horizon)]["score_weight"])
            * date_output[f"downside_probability_{horizon}d"]
            for horizon in selection_horizons
        )
        disagreement = sum(
            float(contract["horizons"][str(horizon)]["score_weight"])
            * date_output[f"model_disagreement_{horizon}d"]
            for horizon in selection_horizons
        )
        date_output["expected_alpha_gross"] = horizon_alpha
        date_output["weighted_downside_probability"] = downside
        date_output["weighted_model_disagreement"] = disagreement
        date_output["entry_timing_score"] = (
            date_output["expected_alpha_21d"]
            - float(contract["score"]["downside_probability_penalty"])
            * date_output["downside_probability_21d"]
            - float(contract["score"]["long_recent_disagreement_penalty"])
            * date_output["model_disagreement_21d"]
        )
        date_output["expected_return_score"] = (
            horizon_alpha
            - float(contract["score"]["downside_probability_penalty"]) * downside
            - float(contract["score"]["long_recent_disagreement_penalty"]) * disagreement
        )
        date_output["expected_return_rank"] = date_output["expected_return_score"].rank(
            ascending=False, method="first"
        )
        date_output["research_only"] = True
        prediction_parts.append(date_output)
        if latest_date is not None and decision == latest_date:
            latest_models = {
                "decision_date": decision,
                "horizons": decision_models,
            }
    predictions = (
        pd.concat(prediction_parts, ignore_index=True)
        if prediction_parts
        else pd.DataFrame()
    )
    return predictions, pd.DataFrame(audit_rows), latest_models


def _metric_block(
    frame: pd.DataFrame,
    prediction_column: str,
    realized_column: str,
) -> dict[str, Any]:
    valid = frame.dropna(subset=[prediction_column, realized_column]).copy()
    if valid.empty:
        return {
            "rows": 0,
            "decision_dates": 0,
            "mean_monthly_spearman_ic": None,
            "positive_ic_share": None,
            "top_bottom_realized_spread": None,
            "rmse": None,
            "sign_hit_rate": None,
        }
    monthly_ic: list[float] = []
    spreads: list[float] = []
    for _, group in valid.groupby("feature_date"):
        if len(group) < 10 or group[prediction_column].nunique() < 2:
            continue
        ic = group[prediction_column].corr(group[realized_column], method="spearman")
        if pd.notna(ic):
            monthly_ic.append(float(ic))
        ranks = group[prediction_column].rank(pct=True, method="average")
        top = group.loc[ranks.ge(0.8), realized_column]
        bottom = group.loc[ranks.le(0.2), realized_column]
        if not top.empty and not bottom.empty:
            spreads.append(float(top.mean() - bottom.mean()))
    error = valid[prediction_column] - valid[realized_column]
    return {
        "rows": len(valid),
        "decision_dates": int(valid["feature_date"].nunique()),
        "mean_monthly_spearman_ic": float(np.mean(monthly_ic)) if monthly_ic else None,
        "positive_ic_share": float(np.mean(np.asarray(monthly_ic) > 0.0)) if monthly_ic else None,
        "top_bottom_realized_spread": float(np.mean(spreads)) if spreads else None,
        "rmse": float(np.sqrt(np.mean(np.square(error)))) if len(error) else None,
        "sign_hit_rate": float(
            np.mean(
                np.sign(valid[prediction_column].to_numpy())
                == np.sign(valid[realized_column].to_numpy())
            )
        ),
    }


def evaluate_predictions(
    predictions: pd.DataFrame, contract: Mapping[str, Any]
) -> dict[str, Any]:
    windows = {
        "full": (
            pd.Timestamp(contract["purge_and_windows"]["full_start"]),
            None,
        ),
        "oos2": (
            pd.Timestamp(contract["purge_and_windows"]["oos2_start"]),
            pd.Timestamp(contract["purge_and_windows"]["oos2_end"]),
        ),
        "oos": (
            pd.Timestamp(contract["purge_and_windows"]["oos_start"]),
            None,
        ),
    }
    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "metric_semantics": "cross_sectional_expected_return_diagnostics_not_portfolio_performance",
        "windows": {},
    }
    for name, (start, end) in windows.items():
        scoped = predictions[predictions["feature_date"].ge(start)].copy()
        if end is not None:
            scoped = scoped[scoped["feature_date"].le(end)].copy()
        horizon_rows: dict[str, Any] = {}
        for horizon in HORIZONS:
            horizon_rows[str(horizon)] = {
                target_kind: _metric_block(
                    scoped,
                    f"expected_{target_kind}_{horizon}d",
                    f"realized_{target_kind}_{horizon}d",
                )
                for target_kind in TARGET_KINDS
            }
            downside_valid = scoped.dropna(
                subset=[
                    f"downside_probability_{horizon}d",
                    f"realized_downside_{horizon}d",
                ]
            )
            horizon_rows[str(horizon)]["downside"] = {
                "rows": len(downside_valid),
                "brier_score": (
                    float(
                        np.mean(
                            np.square(
                                downside_valid[f"downside_probability_{horizon}d"].to_numpy(dtype=float)
                                - downside_valid[f"realized_downside_{horizon}d"].to_numpy(dtype=float)
                            )
                        )
                    )
                    if not downside_valid.empty
                    else None
                ),
            }
        result["windows"][name] = {
            "start": start,
            "end": end,
            "prediction_rows": len(scoped),
            "prediction_dates": int(scoped["feature_date"].nunique()),
            "horizons": horizon_rows,
            "composite_vs_realized_63d_benchmark_excess": _metric_block(
                scoped,
                "expected_return_score",
                "realized_benchmark_excess_63d",
            ),
        }
    return result


def public_latest_proposal(predictions: pd.DataFrame) -> pd.DataFrame:
    if predictions.empty:
        return pd.DataFrame(
            columns=[
                "feature_date",
                "ticker",
                "sector",
                "expected_return_score",
                "expected_return_rank",
                "expected_alpha_gross",
                "weighted_downside_probability",
                "weighted_model_disagreement",
                "research_only",
            ]
        )
    latest = predictions["feature_date"].max()
    forbidden = re.compile(r"^realized_|^label_available_at_|^y_")
    columns = [column for column in predictions.columns if not forbidden.search(column)]
    proposal = predictions.loc[predictions["feature_date"].eq(latest), columns].copy()
    return proposal.sort_values(
        ["expected_return_score", "ticker"], ascending=[False, True]
    ).reset_index(drop=True)


def blocked_artifacts(
    output_dir: Path,
    *,
    blockers: list[str],
    contract: Mapping[str, Any],
    inputs: Mapping[str, Any],
) -> dict[str, Any]:
    empty_predictions = pd.DataFrame()
    empty_predictions.to_csv(output_dir / "expected_return_predictions.csv", index=False)
    pd.DataFrame().to_csv(output_dir / "training_audit.csv", index=False)
    public_latest_proposal(empty_predictions).to_csv(
        output_dir / "latest_expected_return_proposal.csv", index=False
    )
    write_json(output_dir / "model_coefficients.json", {"status": BLOCKED_STATUS})
    write_json(
        output_dir / "expected_return_metrics.json",
        {
            "status": BLOCKED_STATUS,
            "metric_semantics": "not_computed",
            "blockers": blockers,
        },
    )
    summary = {
        "schema_version": SCHEMA_VERSION,
        "status": BLOCKED_STATUS,
        "family_id": contract["family_id"],
        "blockers": blockers,
        "historical_model_fit_executed": False,
        "historical_backtest_executed": False,
        "fullrun_executed": False,
        "target_books_written": False,
        "orders_generated": False,
        "portfolio_or_ledger_mutated": False,
        "automatic_promotion_allowed": False,
        "production_or_live_trading_enabled": False,
    }
    write_json(output_dir / "summary.json", summary)
    (output_dir / "report.md").write_text(
        "# Run287 expected-return challenger\n\n"
        f"Status: `{BLOCKED_STATUS}`\n\n"
        "Historical fit and backtest were not executed.\n\n"
        "## Blockers\n\n"
        + "\n".join(f"- `{item}`" for item in blockers)
        + "\n",
        encoding="utf-8",
    )
    write_json(
        output_dir / "source_manifest.json",
        {
            "schema_version": SCHEMA_VERSION,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "git_commit_sha": git_head(),
            "contract_sha256": canonical_sha256(contract),
            "inputs": inputs,
            "status": BLOCKED_STATUS,
            "historical_fit_executed": False,
        },
    )
    return summary


def run(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    contract_path = repo_path(args.contract)
    census_path = repo_path(args.u0_census)
    accepted_evidence_path = repo_path(
        getattr(args, "u0_accepted_evidence", "")
    )
    feature_store_path = repo_path(args.feature_store)
    contract = validate_contract(read_json(contract_path))
    inputs = {
        "contract": fingerprint(contract_path),
        "u0_census": fingerprint(census_path),
        "u0_accepted_evidence": fingerprint(accepted_evidence_path),
        "feature_store": fingerprint(feature_store_path),
    }
    blockers: list[str] = []
    census: Any = None
    accepted_evidence: Any = None
    canonical_artifact: Any = None
    if not census_path.is_file():
        blockers.append("u0_census_missing")
    else:
        try:
            census = read_json(census_path)
        except Exception as exc:
            blockers.append(f"u0_census_unreadable:{type(exc).__name__}")
    if not accepted_evidence_path.is_file():
        blockers.append("u0_accepted_evidence_missing")
    else:
        try:
            accepted_evidence = read_json(accepted_evidence_path)
        except Exception as exc:
            blockers.append(
                f"u0_accepted_evidence_unreadable:{type(exc).__name__}"
            )
    artifact_id = getattr(args, "u0_accepted_artifact_id", None)
    if type(artifact_id) is not int or artifact_id <= 0:
        blockers.append("u0_accepted_artifact_id_missing_or_invalid")
    else:
        try:
            canonical_artifact = load_canonical_u0_artifact(
                artifact_id, contract
            )
            inputs["u0_canonical_artifact"] = {
                key: canonical_artifact.get(key)
                for key in (
                    "artifact_id",
                    "workflow_run_id",
                    "workflow_path",
                    "head_sha",
                    "artifact_digest",
                )
            }
        except Exception as exc:
            blockers.append(
                f"u0_canonical_artifact_unverified:{type(exc).__name__}"
            )
    if census is not None and accepted_evidence is not None:
        blockers.extend(
            u0_gate(census, accepted_evidence, canonical_artifact, contract)
        )
    trial_floor = (
        (census.get("summary") or {}).get(
            "conservative_historical_trial_count_lower_bound"
        )
        if isinstance(census, dict)
        else None
    )
    inputs["u0_conservative_historical_trial_count_lower_bound"] = trial_floor
    frame = pd.DataFrame()
    if not feature_store_path.is_file():
        blockers.append("feature_store_missing")
    else:
        try:
            frame = pd.read_parquet(feature_store_path)
            blockers.extend(input_readiness(frame, contract))
        except Exception as exc:
            blockers.append(f"feature_store_unreadable:{type(exc).__name__}")
    blockers = sorted(set(blockers))
    if blockers:
        return blocked_artifacts(
            output_dir,
            blockers=blockers,
            contract=contract,
            inputs=inputs,
        )

    try:
        prepared = prepare_frame(frame, contract)
    except Exception as exc:
        detail = re.sub(r"[^A-Za-z0-9_.:,=-]+", "_", str(exc)).strip("_")
        return blocked_artifacts(
            output_dir,
            blockers=[
                f"feature_store_semantic_validation_failed:{type(exc).__name__}:"
                f"{detail[:240]}"
            ],
            contract=contract,
            inputs=inputs,
        )
    predictions, audit, latest_models = walk_forward_predictions(prepared, contract)
    if predictions.empty:
        return blocked_artifacts(
            output_dir,
            blockers=["no_pit_purged_walk_forward_predictions"],
            contract=contract,
            inputs=inputs,
        )
    latest_input_date = pd.Timestamp(prepared["feature_date"].max()).normalize()
    latest_scored_date = pd.Timestamp(predictions["feature_date"].max()).normalize()
    if latest_scored_date != latest_input_date:
        return blocked_artifacts(
            output_dir,
            blockers=[
                "latest_input_decision_not_scored:"
                f"input={latest_input_date.date()}:scored={latest_scored_date.date()}"
            ],
            contract=contract,
            inputs=inputs,
        )
    metrics = evaluate_predictions(predictions, contract)
    metrics["multiple_testing_context"] = {
        "conservative_historical_trial_count_lower_bound": trial_floor,
        "source": "canonical_u0_v3_accepted_evidence",
        "used_for_model_or_parameter_tuning": False,
        "required_for_later_dsr_pbo_spa_gate": True,
    }
    proposal = public_latest_proposal(predictions)
    predictions.to_csv(output_dir / "expected_return_predictions.csv", index=False)
    audit.to_csv(output_dir / "training_audit.csv", index=False)
    proposal.to_csv(output_dir / "latest_expected_return_proposal.csv", index=False)
    write_json(output_dir / "expected_return_metrics.json", metrics)
    write_json(output_dir / "model_coefficients.json", latest_models)
    summary = {
        "schema_version": SCHEMA_VERSION,
        "status": READY_STATUS,
        "family_id": contract["family_id"],
        "latest_decision_date": proposal["feature_date"].max() if not proposal.empty else None,
        "prediction_rows": len(predictions),
        "prediction_dates": int(predictions["feature_date"].nunique()),
        "latest_candidate_count": len(proposal),
        "conservative_historical_trial_count_lower_bound": trial_floor,
        "historical_model_fit_executed": True,
        "historical_backtest_executed": False,
        "broker_ledger_metrics_available": False,
        "fullrun_executed": False,
        "target_books_written": False,
        "orders_generated": False,
        "portfolio_or_ledger_mutated": False,
        "automatic_promotion_allowed": False,
        "production_or_live_trading_enabled": False,
    }
    write_json(output_dir / "summary.json", summary)
    (output_dir / "report.md").write_text(
        "# Run287 expected-return challenger\n\n"
        f"Status: `{READY_STATUS}`\n\n"
        f"Predictions: {len(predictions):,} rows across "
        f"{int(predictions['feature_date'].nunique())} decisions.\n\n"
        "These are cross-sectional research diagnostics, not after-cost portfolio performance. "
        "No target book, order, cash change, ledger mutation, fullrun, or promotion occurred.\n",
        encoding="utf-8",
    )
    output_fingerprints = {
        name: fingerprint(output_dir / name)
        for name in contract["outputs"]
        if name != "source_manifest.json" and (output_dir / name).is_file()
    }
    write_json(
        output_dir / "source_manifest.json",
        {
            "schema_version": SCHEMA_VERSION,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "git_commit_sha": git_head(),
            "contract_sha256": canonical_sha256(contract),
            "inputs": inputs,
            "outputs": output_fingerprints,
            "status": READY_STATUS,
            "conservative_historical_trial_count_lower_bound": trial_floor,
            "historical_fit_executed": True,
            "historical_backtest_executed": False,
        },
    )
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--contract",
        default="docs/run287_expected_return_challenger_contract.json",
    )
    parser.add_argument("--u0-census", required=True)
    parser.add_argument("--u0-accepted-evidence", required=True)
    parser.add_argument("--u0-accepted-artifact-id", required=True, type=int)
    parser.add_argument("--feature-store", required=True)
    parser.add_argument("--output-dir", required=True)
    return parser.parse_args()


def main() -> int:
    summary = run(parse_args())
    print(json.dumps(json_clean(summary), sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
