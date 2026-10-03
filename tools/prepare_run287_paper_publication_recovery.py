#!/usr/bin/env python3
"""Prepare publication of the fixed, already committed July27 paper snapshot.

This wrapper calls the existing physical ledger/outcome verifiers. It never
executes a paper transaction, installs a head, writes Drive, or reuses the
original transaction's consumed authorization. Publishing is a separate,
fresh owner dispatch on the exact current master, in the durable environment.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from tools import run287_paper_ledger_integrity as paper
from tools import build_run287_risk_outcome_legacy_migration as outcome
from tools import verify_run287_catchup_scope_attestation as scope
from tools.build_run287_catchup_price_evidence import validate_github_compare_payload
from tools.check_run287_catchup_drive_readiness import (
    load_environment_contract, verify_environment_attestation,
    verify_environment_credential_binding,
)

WORKFLOW_PATH = ".github/workflows/run287_paper_publication_recovery.yml"
PUBLICATION_JOB_NAME = "publication_recovery"
ACCEPTED_ARTIFACT_STEP = "Upload accepted committed July27 publication recovery"
SCHEMA = "run287-committed-paper-publication-recovery-v1"
READY = "PREPARED_COMMITTED_PAPER_RECOVERY_REVIEW_ONLY"
PROFILE = {
    "session_date": "2026-07-27",
    "producer_sha": "30915e05c1ffe3cecd2c46b229af20844e514f3d",
    "producer_run": 37002957966,
    "producer_job": 110824620982,
    "capture_run": 36989287810,
    "capture_artifact": 11219955566,
    "capture_digest": "ded0c699a9b7001044f4e3b7ad35d888849b7bc6218623b2dc22f1cc3a348df0",
    "diagnostic_artifact": 11230121090,
    "diagnostic_digest": "7497839c1937ea6b52e291930904a918988fa96c7539ea5eb4f2fedc255a01e9",
    "consumed_scope_comment": 5951667349,
    "terminal": "761cf62e2e4b405d9a22d878b35dec38b95b10f17ccc12cdd4bdceb85d175b46",
    "manifest_sha256": "8e642b2f5724f46fc41b4146db4c77f0baaa9f57b8f99ba03d42ee5814f4f413",
    "payload_count": 270,
    "outcome_root": "c904e02c9dfd97f8de7880b24951cc969521211036dedc9bc6dbdfc37890bc90",
    "chain": [
        "f904fa6bd1d4280f688f99b4562837e48ad196942f75a3b9ad0b2aeb917709a3",
        "ccb295e4ede048458150a2b7396cf95e9079d1b2e8dc3506b4acc6ee48068185",
        "1a3e6be3e51ecf057a7c6b1b531fca5eeecbd50af29b67af81aadc3414ace417",
        "372fbfeaa50e80ec1fe365ada56e907c85f6a39413e1b64e62f60e0a4de3d420",
        "086904f693a94027fda661d0da8041744bb941ebb68cb7547fa5e737caee3b57",
        "65fa6f5b4b12729811b72a90661fc744320826dfe868ec6da2632768b1ec02a7",
        "761cf62e2e4b405d9a22d878b35dec38b95b10f17ccc12cdd4bdceb85d175b46",
    ],
}
INPUT_DIRECTORIES = ("paper_current", "paper_heads_current", "accepted", "legacy_current")
INPUT_KEYS = {"expected_master_sha", "allow_publication_recovery", "save_continuity_cache"}
RECEIPT_KEYS = {
    "schema_version", "status", "review_only", "session_date", "snapshot_hash",
    "original_producer", "recovery_verifier", "recovery_publisher", "publication_ready",
    "original_consumed_scope_reused", "historical_consumed_scope_comment",
    "new_orders_generated", "new_heads_created", "Drive_writes",
    "forward_promotion_eligible", "live_trading_enabled", "original_artifact_context",
}
ORIGINAL_CONTEXT = "RETAINED_DIAGNOSTIC_PLUS_COMMITTED_PHYSICAL_STATE; NOT_RECONSTRUCTED_NORMAL_PROMOTION"


def require(condition: Any, code: str) -> None:
    if not condition:
        raise ValueError("publication_recovery:" + code)


def read(path: Path) -> dict:
    raw = paper._read_regular_file_no_follow(path, label="recovery evidence")
    return paper._strict_json_object(raw, label=str(path))


def write(path: Path, payload: dict) -> None:
    paper.write_integrity_verifier_receipt(path, payload)


def tree(root: Path) -> dict:
    paper._require_no_symlink_components(root, label="recovery input root")
    require(root.is_dir(), "input_directory_missing")
    result = {}
    for path in sorted(root.rglob("*")):
        require(not path.is_symlink(), "input_symlink")
        if path.is_file():
            raw = paper._read_regular_file_no_follow(path, label="recovery input")
            result[path.relative_to(root).as_posix()] = {
                "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw),
            }
    return result


def exact_user(user: Any) -> bool:
    return isinstance(user, dict) and all(user.get(k) == v for k, v in {
        "login": scope.OWNER_LOGIN, "id": scope.OWNER_ID,
        "node_id": scope.OWNER_NODE_ID, "type": "User",
    }.items())


def boolean(value: Any) -> bool:
    require(type(value) is bool or value in ("true", "false"), "dispatch_boolean_invalid")
    return value is True or value == "true"


def validate_run_census_ids(runs: list, current: dict, *, code_prefix: str) -> set[int]:
    run_ids = set()
    for observed in runs:
        require(isinstance(observed, dict) and type(observed.get("id")) is int and observed["id"] > 0,
                code_prefix + "_run_identity")
        require(observed["id"] not in run_ids, code_prefix + "_run_duplicate")
        run_ids.add(observed["id"])
        if observed["id"] == current["id"]:
            for key in ("run_attempt", "event", "path", "head_branch", "head_sha", "status", "conclusion",
                        "created_at", "run_started_at"):
                if key in observed:
                    require(type(observed[key]) is type(current.get(key)) and observed[key] == current.get(key),
                            "current_recovery_census_metadata_conflict")
            for key in ("actor", "triggering_actor"):
                if key in observed:
                    require(exact_user(observed[key]), "current_recovery_census_metadata_conflict")
            for key in ("repository", "head_repository"):
                if key in observed:
                    obj = observed[key]
                    require(isinstance(obj, dict) and obj.get("full_name") == scope.REPOSITORY and
                            obj.get("id") == scope.REPOSITORY_ID and obj.get("node_id") == scope.REPOSITORY_NODE_ID and
                            exact_user(obj.get("owner")), "current_recovery_census_metadata_conflict")
    return run_ids


def prior_publication_step_state(previous: dict, jobs_payload: Any) -> str:
    require(isinstance(previous, dict) and type(previous.get("id")) is int and previous["id"] > 0 and
            type(previous.get("run_attempt")) is int and previous["run_attempt"] > 0,
            "prior_recovery_identity")
    require(isinstance(jobs_payload, dict), "prior_job_census_missing")
    jobs = jobs_payload.get("jobs")
    require(isinstance(jobs, list) and type(jobs_payload.get("total_count")) is int and
            jobs_payload["total_count"] == len(jobs), "prior_job_census_incomplete")
    job_ids = set()
    attempts = {}
    # A default-false dispatch skips the whole job but GitHub reports SUCCESS.
    # Only a complete, entirely skipped job census can distinguish that no-op
    # from an executed successful run whose upload evidence is absent.
    success_candidate = previous.get("status") == "completed" and previous.get("conclusion") == "success"
    entire_census_skipped = True
    for job in jobs:
        require(isinstance(job, dict) and type(job.get("id")) is int and job["id"] > 0 and
                type(job.get("run_id")) is int and job["run_id"] == previous["id"] and
                type(job.get("run_attempt")) is int and 1 <= job["run_attempt"] <= previous["run_attempt"],
                "prior_job_run_identity")
        require(job["id"] not in job_ids, "prior_job_identity_duplicate")
        job_ids.add(job["id"])
        steps = job.get("steps")
        require(isinstance(steps, list), "prior_job_steps_missing")
        require(all(isinstance(step, dict) for step in steps), "prior_job_step_invalid")
        matches = [step for step in steps if step.get("name") == ACCEPTED_ARTIFACT_STEP]
        whole_job_skipped = (job.get("status") == "completed" and job.get("conclusion") == "skipped" and
                             all(step.get("status") == "completed" and step.get("conclusion") == "skipped"
                                 for step in steps))
        entire_census_skipped = entire_census_skipped and whole_job_skipped
        if success_candidate and whole_job_skipped:
            # Empty steps are the job-level-if shape. Supplied skipped steps
            # still need unique identities, including on unrelated jobs.
            numbers = [step.get("number") for step in steps]
            require(all(type(number) is int and number > 0 for number in numbers) and
                    len(set(numbers)) == len(numbers), "prior_job_step_identity")
        if job.get("name") != PUBLICATION_JOB_NAME:
            require(not matches, "prior_publication_job_mismatch")
            continue
        require(job.get("status") == "completed", "prior_publication_job_incomplete")
        attempt = job["run_attempt"]
        require(attempt not in attempts, "prior_publication_attempt_duplicate")
        step_numbers = set()
        for step in steps:
            number = step.get("number")
            require(type(number) is int and number > 0 and number not in step_numbers,
                    "prior_job_step_identity")
            step_numbers.add(number)
        require(len(matches) <= 1, "prior_publication_step_duplicate")
        if success_candidate and whole_job_skipped:
            attempts[attempt] = "whole_job_skipped"
            continue
        require(matches, "prior_publication_step_missing")
        require(matches[0].get("status") == "completed", "prior_publication_step_incomplete")
        attempts[attempt] = matches[0].get("conclusion")
    # Unique identities in 1..N with cardinality N prove the complete census;
    # unrelated jobs may occur only in a subset of those attempts.
    require(len(attempts) == previous["run_attempt"], "prior_publication_attempt_census_incomplete")
    if any(value == "success" for value in attempts.values()):
        return "success"
    if success_candidate and entire_census_skipped:
        return "whole_run_skipped"
    require(all(value == "skipped" for value in attempts.values()),
            "prior_publication_side_effect_ambiguous")
    return "skipped"


def validate_publisher(evidence: Path, checkout_sha: str, *, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    repository = read(evidence / "repository.json")
    master = read(evidence / "master.json")
    run = read(evidence / "publisher_run.json")
    event = read(evidence / "event.json")
    require(repository.get("full_name") == scope.REPOSITORY and
            repository.get("id") == scope.REPOSITORY_ID and
            repository.get("node_id") == scope.REPOSITORY_NODE_ID and
            repository.get("default_branch") == "master" and
            exact_user(repository.get("owner")), "publisher_repository_identity")
    inputs = event.get("inputs")
    require(isinstance(inputs, dict) and set(inputs) == INPUT_KEYS, "dispatch_inputs_not_exact")
    require(boolean(inputs["allow_publication_recovery"]), "publication_not_authorized")
    cache = boolean(inputs["save_continuity_cache"])
    expected = inputs["expected_master_sha"]
    require(isinstance(expected, str) and scope.SHA_RE.fullmatch(expected) and
            expected == checkout_sha == master.get("object", {}).get("sha") and
            master.get("ref") == "refs/heads/master", "publisher_not_exact_current_master")
    require(type(run.get("id")) is int and run["id"] > 0 and
            run["id"] not in (PROFILE["producer_run"], PROFILE["capture_run"]) and
            run.get("run_attempt") == 1 and type(run.get("run_attempt")) is int and
            run.get("event") == "workflow_dispatch" and
            run.get("path") == WORKFLOW_PATH and run.get("head_branch") == "master" and
            run.get("head_sha") == expected and run.get("status") == "in_progress" and
            run.get("conclusion") is None and exact_user(run.get("actor")) and
            exact_user(run.get("triggering_actor")), "publisher_run_identity_or_authority")
    for key in ("repository", "head_repository"):
        obj = run.get(key, {})
        require(obj.get("full_name") == scope.REPOSITORY and
                obj.get("id") == scope.REPOSITORY_ID and
                obj.get("node_id") == scope.REPOSITORY_NODE_ID and
                exact_user(obj.get("owner")), "publisher_fork_or_repository")
    created = datetime.fromisoformat(run["created_at"].replace("Z", "+00:00"))
    started = datetime.fromisoformat(run["run_started_at"].replace("Z", "+00:00"))
    require(created.tzinfo is not None and started.tzinfo is not None and
            -60 <= (now - created).total_seconds() <= 3600 and
            created <= started <= now, "publisher_lease_expired_or_time_invalid")
    for status in ("in_progress", "queued", "waiting"):
        census = read(evidence / ("writers_" + status + ".json"))
        runs = census.get("workflow_runs")
        require(isinstance(runs, list) and type(census.get("total_count")) is int and
                census["total_count"] == len(runs), "writer_census_incomplete")
        validate_run_census_ids(runs, run, code_prefix="writer")
        require(all(isinstance(r, dict) and r.get("id") == run["id"] for r in runs), "conflicting_active_writer")
    prior = read(evidence / "prior_recoveries.json")
    runs = prior.get("workflow_runs")
    require(isinstance(runs, list) and type(prior.get("total_count")) is int and
            prior["total_count"] == len(runs), "prior_recovery_census_incomplete")
    run_ids = validate_run_census_ids(runs, run, code_prefix="prior_recovery")
    # The dedicated GET already proved this live publisher exists. An empty or
    # omitted-current listing cannot establish complete history for exclusion.
    require(run["id"] in run_ids, "prior_recovery_current_run_missing")
    artifacts = prior.get("artifacts")
    require(isinstance(artifacts, dict), "prior_artifact_census_missing")
    prior_jobs = prior.get("jobs")
    for previous in runs:
        if previous.get("id") == run["id"]:
            continue
        metadata = artifacts.get(str(previous.get("id")), {})
        require(isinstance(metadata, dict), "prior_artifact_census_incomplete")
        rows = metadata.get("artifacts")
        require(isinstance(rows, list) and type(metadata.get("total_count")) is int and
                metadata["total_count"] == len(rows), "prior_artifact_census_incomplete")
        require(all(isinstance(row, dict) for row in rows), "prior_artifact_census_invalid")
        name = f"accepted-paper-catchup-{PROFILE['session_date']}-{previous['id']}"
        if any(a.get("name") == name for a in rows):
            raise ValueError("publication_recovery:already_published_requires_separate_recovery")
        require(isinstance(prior_jobs, dict), "prior_job_census_missing")
        step_state = prior_publication_step_state(previous, prior_jobs.get(str(previous["id"])))
        if step_state == "success":
            raise ValueError("publication_recovery:already_published_requires_separate_recovery")
        if step_state == "whole_run_skipped":
            require(not rows, "prior_whole_run_skip_artifacts_present")
            continue
        require(previous.get("status") == "completed" and
                previous.get("conclusion") in ("failure", "cancelled"),
                "prior_retry_not_proven_prepublication")
    return {"source_sha": expected, "run_id": run["id"], "run_attempt": 1,
            "workflow_path": WORKFLOW_PATH, "authority": "FRESH_OWNER_MANUAL_DISPATCH",
            "save_continuity_cache": cache, "created_at": run["created_at"]}


def verify_environment() -> None:
    contract = load_environment_contract()
    attestation = os.environ.get("RUN287_DURABLE_ENVIRONMENT_ATTESTATION", "")
    credentials = {"GOOGLE_SERVICE_ACCOUNT_KEY": os.environ.get("GOOGLE_SERVICE_ACCOUNT_KEY", ""),
                   "RCLONE_CONFIG_GDRIVE": os.environ.get("RCLONE_CONFIG_GDRIVE", "")}
    require(verify_environment_attestation(contract=contract,
            environment_name=os.environ.get("RUN287_DURABLE_ENVIRONMENT_NAME", ""),
            attestation_value=attestation) and
            verify_environment_credential_binding(contract=contract,
            attestation_value=attestation, credentials=credentials), "durable_environment_binding")


def validate_original_evidence(evidence: Path, inputs: Path, *, profile: dict = PROFILE) -> None:
    run = read(evidence / "original_run.json")
    job = read(evidence / "original_job.json")
    require(run.get("id") == profile["producer_run"] and type(run.get("run_attempt")) is int and run.get("run_attempt") == 1 and
            run.get("head_sha") == profile["producer_sha"] and run.get("head_branch") == "master" and
            run.get("status") == "completed" and run.get("conclusion") == "cancelled" and
            run.get("workflow_id") == scope.WORKFLOW_ID and
            run.get("path") == scope.WORKFLOW_PATH and
            run.get("repository", {}).get("full_name") == scope.REPOSITORY and
            run.get("head_repository", {}).get("full_name") == scope.REPOSITORY, "original_producer_identity")
    require(job.get("id") == profile["producer_job"] and job.get("run_id") == profile["producer_run"] and
            job.get("conclusion") == "cancelled", "original_job_identity")
    steps = {step.get("name"): step.get("conclusion") for step in job.get("steps", [])}
    for name, expected in {
        "Run transactional paper ledger and same-close selector": "success",
        "Verify transactional forward paper snapshot": "success",
        "Persist validated forward paper ledger state": "cancelled",
        "Upload accepted chronological catch-up artifact": "skipped",
        "Save validated cross-mode paper continuity cache": "skipped",
    }.items():
        require(steps.get(name) == expected, "original_step_boundary_changed")
    capture = read(evidence / "capture_run.json")
    require(capture.get("id") == profile["capture_run"] and type(capture.get("run_attempt")) is int and capture.get("run_attempt") == 1 and
            capture.get("head_sha") == profile["producer_sha"] and capture.get("head_branch") == "master" and
            capture.get("status") == "completed" and capture.get("conclusion") == "success" and
            capture.get("workflow_id") == scope.WORKFLOW_ID and
            capture.get("path") == scope.WORKFLOW_PATH and
            capture.get("repository", {}).get("full_name") == scope.REPOSITORY and
            capture.get("head_repository", {}).get("full_name") == scope.REPOSITORY, "capture_run_identity")
    for label, run_id, name in [
        ("capture", profile["capture_run"], f"daily-operating-selection-refresh-{profile['capture_run']}"),
        ("diagnostic", profile["producer_run"], f"blocked-paper-catchup-{profile['session_date']}-{profile['producer_run']}"),
    ]:
        artifact = read(evidence / (label + "_artifact.json"))
        require(artifact.get("id") == profile[label + "_artifact"] and artifact.get("name") == name and
                artifact.get("expired") is False and
                artifact.get("digest") == "sha256:" + profile[label + "_digest"] and
                artifact.get("workflow_run", {}).get("id") == run_id and
                artifact.get("workflow_run", {}).get("head_sha") == profile["producer_sha"], label + "_artifact_identity")
        require(paper.file_hash(inputs / (label + ".zip")) == profile[label + "_digest"], label + "_zip_digest")


def verify_remote_inventories(root: Path, *, profile: dict = PROFILE) -> None:
    def array(path: Path) -> list:
        raw = paper._read_regular_file_no_follow(path, label="remote inventory")
        data = paper._strict_json_object(b'{"items":' + raw + b'}', label="remote inventory")["items"]
        require(isinstance(data, list), "remote_inventory_shape")
        return data
    def normalized(items: list) -> dict:
        result = {}
        for item in items:
            path = item.get("Path")
            require(isinstance(path, str) and path and not PurePosixPath(path).is_absolute()
                    and ".." not in PurePosixPath(path).parts and "\\" not in path and ":" not in path,
                    "remote_inventory_path")
            require(path not in result and type(item.get("IsDir")) is bool, "remote_inventory_duplicate_or_type")
            result[path] = {"directory": item["IsDir"], "bytes": item.get("Size") if not item["IsDir"] else None,
                            "hashes": item.get("Hashes") if not item["IsDir"] else None}
        return result
    for name in INPUT_DIRECTORIES:
        before = normalized(array(root / (name + ".before.json")))
        after = normalized(array(root / (name + ".after.json")))
        require(before == after, "remote_inventory_drift")
        if name in ("paper_heads_current", "accepted"):
            roots = {p for p, item in before.items() if "/" not in p and item["directory"]}
            expected = set(profile["chain"]) if name == "paper_heads_current" else {profile["outcome_root"]}
            require(roots == expected, "remote_head_directory_frontier")
        local = tree(root / name)
        files = {p: item for p, item in before.items() if not item["directory"]}
        require(set(files) == set(local), "remote_local_file_inventory_mismatch")
        for relative, item in files.items():
            raw = paper._read_regular_file_no_follow(root / name / relative, label="inventory input")
            require(type(item["bytes"]) is int and item["bytes"] == len(raw) and
                    isinstance(item["hashes"], dict) and item["hashes"], "remote_file_size_or_hash_missing")
            recognized = 0
            for algorithm, digest in item["hashes"].items():
                if algorithm in {"md5", "sha1", "sha256"}:
                    require(hashlib.new(algorithm, raw).hexdigest() == digest, "remote_local_checksum_mismatch")
                    recognized += 1
            require(recognized, "remote_checksum_algorithm_missing")


def unpack(archive: Path, destination: Path) -> None:
    require(not destination.exists(), "artifact_destination_exists")
    with zipfile.ZipFile(archive) as zipped:
        names = [item.filename for item in zipped.infolist()]
        require(len(names) == len(set(names)), "artifact_duplicate_member")
        require(sum(item.file_size for item in zipped.infolist()) <= 256 * 1024 * 1024,
                "artifact_expanded_size")
        for item in zipped.infolist():
            path = PurePosixPath(item.filename)
            require(not path.is_absolute() and ".." not in path.parts and
                    "\\" not in item.filename and ":" not in item.filename and
                    not stat.S_ISLNK(item.external_attr >> 16), "artifact_unsafe_path")
        destination.mkdir(parents=True)
        zipped.extractall(destination)


def verify_archive_tree(archive: Path, destination: Path) -> None:
    observed = tree(destination)
    with zipfile.ZipFile(archive) as zipped:
        members = [item for item in zipped.infolist() if not item.is_dir()]
        require(len(members) == len({item.filename for item in members}) and
                {item.filename for item in members} == set(observed), "original_archive_inventory_changed")
        for item in members:
            raw = zipped.read(item)
            require(observed[item.filename] == {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()},
                    "original_extracted_byte_changed")


def validate_physical(root: Path, *, profile: dict = PROFILE) -> dict:
    selection = paper.select_verified_immutable_paper_head(root / "paper_heads_current")
    require(selection["chain_snapshot_hashes"] == profile["chain"] and
            selection["terminal_snapshot_hash"] == profile["terminal"], "paper_frontier_prefix_or_fork")
    terminal = root / "paper_heads_current" / profile["terminal"]
    manifest = paper.verify_integrity_manifest(terminal, require=True)
    require(manifest["as_of_date"] == profile["session_date"] and
            manifest["file_count"] == profile["payload_count"] and
            paper.file_hash(terminal / paper.INTEGRITY_FILE) == profile["manifest_sha256"], "terminal_identity")
    require(tree(terminal) == tree(root / "paper_current"), "canonical_alias_drift")
    accepted_selection, accepted_manifest = outcome.accepted_chain(root)
    require(accepted_selection["accepted_head_count"] == 1 and
            accepted_selection["root_accepted_manifest_sha256"] == profile["outcome_root"], "outcome_frontier_drift")
    outcome.current_state(root, accepted_selection, accepted_manifest,
                          outcome.embedded_evidence(accepted_manifest))
    return selection


def prepare(inputs: Path, evidence: Path, output: Path, *, publisher: dict | None = None,
            profile: dict = PROFILE) -> dict:
    for path in (inputs, evidence):
        paper._require_no_symlink_components(path, label="recovery source")
    inputs, evidence, output = inputs.absolute(), evidence.absolute(), output.absolute()
    paper._require_output_outside_protected_evidence(output,
            protected_files=(), protected_roots=(inputs, evidence, ROOT), label="recovery output")
    paper._require_no_symlink_components(output, label="recovery output")
    require(not output.exists(), "output_exists")
    before = {name: tree(inputs / name) for name in INPUT_DIRECTORIES}
    validate_original_evidence(evidence, inputs, profile=profile)
    selection = validate_physical(inputs, profile=profile)
    output.mkdir(parents=True)
    original = output / "originals"
    original.mkdir()
    for label in ("capture", "diagnostic"):
        shutil.copyfile(inputs / (label + ".zip"), original / (label + ".zip"))
        unpack(original / (label + ".zip"), original / label)
    diagnostic = original / "diagnostic"
    consumption = read(diagnostic / "_temp/run287_durable_scope_consumption_record.json")
    require(consumption.get("status") == "CONSUMED_ONCE" and
            consumption.get("attestation_comment_id") == profile["consumed_scope_comment"] and
            consumption.get("workflow_run_id") == profile["producer_run"] and
            consumption.get("default_branch_sha") == profile["producer_sha"] and
            consumption.get("session_date") == profile["session_date"], "historical_consumption_binding")
    summaries = list(diagnostic.rglob("daily_operating_selection_refresh/summary.json"))
    require(len(summaries) == 1, "original_catchup_summary_missing_or_ambiguous")
    original_outputs = summaries[0].parent.parent
    summary = read(summaries[0])
    require(summary.get("source_commit_sha") == profile["producer_sha"] and
            summary.get("source_run_id") == str(profile["producer_run"]) and
            summary.get("paper_snapshot_hash") == profile["terminal"] and
            summary.get("paper_integrity_manifest_sha256") == profile["manifest_sha256"] and
            summary.get("market_session_date") == profile["session_date"] and
            summary.get("paper_catchup_mode") is True and summary.get("replay_only") is True and
            all(summary.get(k) is False for k in ("new_order_generation_allowed", "selection_allowed",
                    "same_close_selector_recomputed", "promotion_allowed", "forward_promotion_eligible",
                    "production_mutation_allowed", "live_trading_enabled")), "original_catchup_binding_or_safety")
    terminal = inputs / "paper_heads_current" / profile["terminal"]
    require(tree(original_outputs / "run287_catchup_price_cache") ==
            tree(terminal / "replay_price_evidence" / profile["session_date"]), "original_price_embedding_mismatch")
    require(tree(original_outputs / "run287_catchup_target_source" / profile["session_date"]) ==
            tree(terminal / "replay_target_source" / profile["session_date"]), "original_target_embedding_mismatch")
    shutil.copytree(original_outputs, output / "outputs")
    require(not (output / "outputs/daily_simulated_fill_ledger").exists() and
            not (output / "outputs/run287_paper_immutable_head_bundles").exists(), "diagnostic_may_not_supply_paper_state")
    shutil.copytree(terminal, output / "outputs/daily_simulated_fill_ledger")
    shutil.copytree(inputs / "paper_heads_current", output / "outputs/run287_paper_immutable_head_bundles")
    boundaries = output / "recovery_evidence/boundaries"
    for name in INPUT_DIRECTORIES:
        shutil.copytree(inputs / name, boundaries / name)
    shutil.copytree(evidence, output / "recovery_evidence/github")
    for name in INPUT_DIRECTORIES:
        before_inventory = inputs / (name + ".before.json")
        if before_inventory.exists():
            shutil.copyfile(before_inventory, output / "recovery_evidence" / before_inventory.name)
    selection_path = output / "recovery_evidence/selection.json"
    write(selection_path, selection)
    receipt = paper.build_integrity_verifier_receipt(terminal, immutable_head_selection=selection_path)
    write(output / "recovery_evidence/native_verifier.json", receipt)
    require(all(before[name] == tree(inputs / name) for name in before), "input_changed_during_preparation")
    manifest = {
        "schema_version": SCHEMA, "status": READY, "review_only": True,
        "session_date": profile["session_date"], "snapshot_hash": profile["terminal"],
        "original_producer": {"source_sha": profile["producer_sha"], "run_id": profile["producer_run"],
                              "run_attempt": 1, "conclusion": "cancelled"},
        "recovery_verifier": {
            "checkout_sha": subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "HEAD"]).decode().strip(),
            "preparer_sha256": paper.file_hash(Path(__file__)),
            "native_verifier_sha256": paper.file_hash(Path(paper.__file__)),
            "execution_kind": "PUBLICATION_RECOVERY_JOB" if publisher else "LOCAL_READ_ONLY_PREPARATION",
        },
        "recovery_publisher": publisher, "publication_ready": publisher is not None,
        "original_consumed_scope_reused": False,
        "historical_consumed_scope_comment": profile["consumed_scope_comment"],
        "new_orders_generated": 0, "new_heads_created": 0, "Drive_writes": 0,
        "forward_promotion_eligible": False, "live_trading_enabled": False,
        "original_artifact_context": ORIGINAL_CONTEXT,
    }
    write(output / "recovery_receipt.json", manifest)
    write(output / "INVENTORY.json", {"schema_version": SCHEMA, "files": tree(output)})
    return manifest


def verify_bundle(bundle: Path, evidence: Path, *, publisher: dict | None = None,
                  profile: dict = PROFILE) -> dict:
    expected = read(bundle / "INVENTORY.json")
    observed = tree(bundle)
    observed.pop("INVENTORY.json", None)
    require(expected.get("schema_version") == SCHEMA and expected.get("files") == observed,
            "bundle_inventory_changed")
    receipt = read(bundle / "recovery_receipt.json")
    require(set(receipt) == RECEIPT_KEYS and receipt.get("schema_version") == SCHEMA and receipt.get("status") == READY and
            receipt.get("review_only") is True and receipt.get("original_consumed_scope_reused") is False and
            receipt.get("historical_consumed_scope_comment") == profile["consumed_scope_comment"] and
            receipt.get("original_artifact_context") == ORIGINAL_CONTEXT and
            receipt.get("forward_promotion_eligible") is False and receipt.get("live_trading_enabled") is False and
            all(type(receipt.get(k)) is int and receipt[k] == 0 for k in
                ("new_orders_generated", "new_heads_created", "Drive_writes")) and
            receipt.get("session_date") == profile["session_date"] and
            receipt.get("snapshot_hash") == profile["terminal"] and
            receipt.get("original_producer") == {"source_sha": profile["producer_sha"],
                "run_id": profile["producer_run"], "run_attempt": 1, "conclusion": "cancelled"} and
            receipt.get("recovery_publisher") == publisher and
            receipt.get("publication_ready") is (publisher is not None), "bundle_producer_publisher_binding")
    verifier = receipt.get("recovery_verifier")
    require(isinstance(verifier, dict) and set(verifier) == {
                "checkout_sha", "preparer_sha256", "native_verifier_sha256", "execution_kind"} and
            isinstance(verifier.get("checkout_sha"), str) and scope.SHA_RE.fullmatch(verifier["checkout_sha"]) and
            verifier.get("preparer_sha256") == paper.file_hash(Path(__file__)) and
            verifier.get("native_verifier_sha256") == paper.file_hash(Path(paper.__file__)) and
            verifier.get("execution_kind") == ("PUBLICATION_RECOVERY_JOB" if publisher else "LOCAL_READ_ONLY_PREPARATION") and
            (publisher is None or verifier["checkout_sha"] == publisher["source_sha"]), "recovery_verifier_identity")
    selection = validate_physical(bundle / "recovery_evidence/boundaries", profile=profile)
    terminal = bundle / "recovery_evidence/boundaries/paper_current"
    require(tree(terminal) == tree(bundle / "outputs/daily_simulated_fill_ledger") and
            tree(bundle / "recovery_evidence/boundaries/paper_heads_current") ==
            tree(bundle / "outputs/run287_paper_immutable_head_bundles"), "bundle_cache_inputs_changed")
    validate_original_evidence(evidence, bundle / "originals", profile=profile)
    for label in ("capture", "diagnostic"):
        verify_archive_tree(bundle / "originals" / (label + ".zip"), bundle / "originals" / label)
    summaries = list((bundle / "originals/diagnostic").rglob("daily_operating_selection_refresh/summary.json"))
    require(len(summaries) == 1, "original_output_root_ambiguous")
    original_outputs = summaries[0].parent.parent
    expected_outputs = tree(original_outputs)
    for prefix, source in [("daily_simulated_fill_ledger", terminal),
            ("run287_paper_immutable_head_bundles", bundle / "recovery_evidence/boundaries/paper_heads_current")]:
        expected_outputs.update({prefix + "/" + relative: info for relative, info in tree(source).items()})
    require(tree(bundle / "outputs") == expected_outputs, "original_published_context_changed")
    return {"status": "VERIFIED_COMMITTED_PAPER_RECOVERY_BUNDLE", "publication_ready": publisher is not None,
            "snapshot_hash": selection["terminal_snapshot_hash"], "inventory_sha256": paper.file_hash(bundle / "INVENTORY.json"),
            "save_continuity_cache": bool(publisher and publisher["save_continuity_cache"])}


def collect(evidence: Path, event_file: Path, run_id: str, checkout_sha: str) -> None:
    paper._require_output_outside_protected_evidence(evidence,
            protected_files=(), protected_roots=(ROOT,), label="API evidence")
    require(scope.RUN_ID_RE.fullmatch(run_id), "publisher_run_id_invalid")
    require(scope.SHA_RE.fullmatch(checkout_sha), "publisher_sha_invalid")
    paper._require_no_symlink_components(evidence, label="API evidence")
    evidence.mkdir(parents=True, exist_ok=True)
    def get(endpoint: str) -> dict:
        result = subprocess.run(["gh", "api", "repos/" + scope.REPOSITORY + endpoint],
                                capture_output=True, check=True)
        return paper._strict_json_object(result.stdout, label="GitHub API")
    endpoints = {
        "repository": "", "master": "/git/ref/heads/master",
        "publisher_run": "/actions/runs/" + run_id,
        "original_run": f"/actions/runs/{PROFILE['producer_run']}",
        "original_job": f"/actions/jobs/{PROFILE['producer_job']}",
        "capture_run": f"/actions/runs/{PROFILE['capture_run']}",
        "capture_artifact": f"/actions/artifacts/{PROFILE['capture_artifact']}",
        "diagnostic_artifact": f"/actions/artifacts/{PROFILE['diagnostic_artifact']}",
        "compare": f"/compare/{PROFILE['producer_sha']}...{checkout_sha}",
    }
    for label, endpoint in endpoints.items():
        write(evidence / (label + ".json"), get(endpoint))
    for status in ("in_progress", "queued", "waiting"):
        write(evidence / ("writers_" + status + ".json"),
              get("/actions/runs?status=" + status + "&per_page=100"))
    prior = get("/actions/workflows/run287_paper_publication_recovery.yml/runs?per_page=100")
    prior["artifacts"] = {str(run["id"]): get(f"/actions/runs/{run['id']}/artifacts?per_page=100")
                           for run in prior["workflow_runs"] if str(run["id"]) != run_id}
    prior["jobs"] = {str(run["id"]): get(f"/actions/runs/{run['id']}/jobs?filter=all&per_page=100")
                      for run in prior["workflow_runs"] if str(run["id"]) != run_id}
    write(evidence / "prior_recoveries.json", prior)
    write(evidence / "event.json", read(event_file))
    validate_github_compare_payload(read(evidence / "compare.json"),
            source_sha=PROFILE["producer_sha"], current_sha=checkout_sha)


def readback(archive: Path, bundle: Path, digest: str, *, artifact: dict | None = None,
             publisher: dict | None = None) -> dict:
    expected = digest.removeprefix("sha256:")
    if artifact is not None:
        require(publisher is not None and artifact.get("expired") is False and
                artifact.get("digest") == "sha256:" + expected and
                artifact.get("workflow_run", {}).get("id") == publisher["run_id"] and
                artifact.get("workflow_run", {}).get("head_sha") == publisher["source_sha"] and
                artifact.get("name") == f"accepted-paper-catchup-{PROFILE['session_date']}-{publisher['run_id']}",
                "published_artifact_producer_identity")
    require(paper.valid_sha256(expected) and paper.file_hash(archive) == expected,
            "published_zip_digest")
    files = tree(bundle)
    with zipfile.ZipFile(archive) as zipped:
        members = [item for item in zipped.infolist() if not item.is_dir()]
        require(not any(stat.S_ISLNK(item.external_attr >> 16) for item in members), "published_symlink")
        require(len(members) == len({item.filename for item in members}) and
                {item.filename for item in members} == set(files), "published_zip_inventory")
        for item in members:
            raw = zipped.read(item)
            require(len(raw) == files[item.filename]["bytes"] and
                    hashlib.sha256(raw).hexdigest() == files[item.filename]["sha256"], "published_payload_checksum")
    return {"status": "PERSISTED_ARTIFACT_READBACK_VERIFIED" if artifact is not None else "VERIFIED_LOCAL_ARTIFACT_ZIP_CONTENTS", "zip_sha256": expected,
            "files_verified": len(files), "original_producer_conclusion": "cancelled"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("collect", "authorize", "prepare", "verify", "inventory", "readback"))
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--input-root", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--bundle-dir", type=Path)
    parser.add_argument("--authorize-publisher", action="store_true")
    parser.add_argument("--check-environment", action="store_true")
    parser.add_argument("--published-zip", type=Path)
    parser.add_argument("--published-digest")
    parser.add_argument("--published-artifact-metadata", type=Path)
    parser.add_argument("--published-artifact-id")
    args = parser.parse_args()
    try:
        publisher = None
        checkout_sha = subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "HEAD"]).decode().strip()
        if args.mode == "collect":
            collect(args.evidence_dir, Path(os.environ["GITHUB_EVENT_PATH"]),
                    os.environ["GITHUB_RUN_ID"], checkout_sha)
            result = {"status": "RECOVERY_API_EVIDENCE_COLLECTED"}
        elif args.mode == "inventory":
            require(args.input_root, "inventory_input_root_missing")
            verify_remote_inventories(args.input_root)
            result = {"status": "VERIFIED_CURRENT_REMOTE_INVENTORY_AND_LOCAL_BYTES"}
        elif args.mode == "readback":
            require(args.published_zip and args.published_digest and args.bundle_dir and
                    args.published_artifact_metadata and args.published_artifact_id, "readback_arguments")
            artifact = read(args.published_artifact_metadata)
            require(str(artifact.get("id")) == args.published_artifact_id, "published_artifact_id")
            publisher = read(args.bundle_dir / "recovery_receipt.json").get("recovery_publisher")
            result = readback(args.published_zip, args.bundle_dir, args.published_digest,
                    artifact=artifact, publisher=publisher)
        else:
            if args.authorize_publisher or args.mode == "authorize":
                publisher = validate_publisher(args.evidence_dir, checkout_sha)
                require(str(publisher["run_id"]) == os.environ.get("GITHUB_RUN_ID") and
                        os.environ.get("GITHUB_RUN_ATTEMPT") == "1" and
                        os.environ.get("GITHUB_SHA") == checkout_sha and
                        os.environ.get("GITHUB_REF") == "refs/heads/master" and
                        os.environ.get("GITHUB_JOB") == "publication_recovery", "publisher_not_current_runner")
                validate_github_compare_payload(read(args.evidence_dir / "compare.json"),
                        source_sha=PROFILE["producer_sha"], current_sha=checkout_sha)
            if args.authorize_publisher or args.check_environment:
                verify_environment()
            if args.mode == "authorize":
                result = {"status": "VERIFIED_FRESH_OWNER_PUBLICATION_DISPATCH", "publisher": publisher}
            elif args.mode == "prepare":
                require(args.input_root and args.output_dir, "prepare_arguments")
                result = prepare(args.input_root, args.evidence_dir, args.output_dir, publisher=publisher)
            else:
                require(args.bundle_dir, "verify_arguments")
                result = verify_bundle(args.bundle_dir, args.evidence_dir, publisher=publisher)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (ValueError, KeyError, TypeError, OSError, zipfile.BadZipFile, subprocess.CalledProcessError) as exc:
        print(json.dumps({"status": "BLOCKED_PUBLICATION_RECOVERY", "reason": str(exc)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
