#!/usr/bin/env python3
"""Verify a tracked, hash-approved Run287 fullrun source manifest.

The manifest freezes dispatch parameters and the hashes of review-selected
tracked inputs.  The workflow-supplied manifest hash plus approved Git commit
bind the review to an immutable code/input identity without putting the commit
SHA inside the manifest (which would create a self-referential hash cycle).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_VERSION = "run287-fullrun-approved-source-manifest-v1"
READY_STATUS = "APPROVED_FULLRUN_SOURCE_MANIFEST_READY"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_blob_bytes(relative: str) -> bytes:
    """Return the exact committed bytes, independent of checkout EOL rules."""
    return subprocess.check_output(
        ["git", "show", f"HEAD:{relative}"], cwd=REPO_ROOT
    )


def git_blob_sha256(relative: str) -> str:
    return hashlib.sha256(git_blob_bytes(relative)).hexdigest()


def worktree_matches_head(relative: str) -> bool:
    result = subprocess.run(
        ["git", "diff", "--quiet", "HEAD", "--", relative],
        cwd=REPO_ROOT,
        check=False,
    )
    return result.returncode == 0


def bool_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    normalized = str(value or "").strip().lower()
    if normalized in {"1", "true", "yes"}:
        return True
    if normalized in {"0", "false", "no"}:
        return False
    raise ValueError(f"invalid boolean: {value!r}")


def canonical_timestamp(value: Any) -> str:
    parsed = datetime.fromisoformat(str(value or "").strip().replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include an explicit UTC offset")
    return parsed.astimezone(timezone.utc).isoformat()


def canonical_experiment_env(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return {str(key): value[key] for key in sorted(value)}
    raw = str(value or "").strip()
    if not raw:
        return {}
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("experiment_env_json must decode to an object")
    return {str(key): parsed[key] for key in sorted(parsed)}


def safe_repo_file(path_value: Any) -> tuple[Path, str]:
    relative = Path(str(path_value or "").strip())
    if not str(relative) or relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"unsafe repo-relative path: {path_value!r}")
    candidate = REPO_ROOT / relative
    if candidate.is_symlink():
        raise ValueError(f"symlink is not allowed: {relative.as_posix()}")
    resolved = candidate.resolve(strict=True)
    resolved.relative_to(REPO_ROOT.resolve())
    if not resolved.is_file():
        raise ValueError(f"not a regular file: {relative.as_posix()}")
    tracked = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "--", relative.as_posix()],
        cwd=REPO_ROOT,
        text=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if tracked.returncode != 0:
        raise ValueError(f"file is not tracked by Git: {relative.as_posix()}")
    return resolved, relative.as_posix()


def git_head() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True
    ).strip()


def expected_scope(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "universe_mode": str(args.universe_mode),
        "backtest_years": int(args.backtest_years),
        "pit_universe_label_clean": bool_value(args.pit_universe_label_clean),
        "skip_collector": bool_value(args.skip_collector),
        "fast_mode": bool_value(args.fast_mode),
        "leader_rescue_mode": str(args.leader_rescue_mode),
        "sidecar_profile": str(args.sidecar_profile),
        "artifact_profile": str(args.artifact_profile),
        "gdrive_sync_mode": str(args.gdrive_sync_mode),
        "portfolio_policy": str(args.portfolio_policy),
        "approved_target_policy_path": str(args.approved_target_policy_path),
        "decision_time_utc": canonical_timestamp(args.decision_time_utc),
        "experiment_env": canonical_experiment_env(args.experiment_env_json),
    }


def verify(args: argparse.Namespace) -> dict[str, Any]:
    failures: list[str] = []
    input_audits: dict[str, Any] = {}
    try:
        manifest_path, manifest_relative = safe_repo_file(args.manifest)
    except Exception as exc:
        manifest_path = REPO_ROOT / str(args.manifest)
        manifest_relative = str(args.manifest)
        failures.append(f"manifest_path_invalid:{exc}")

    actual_manifest_hash = (
        git_blob_sha256(manifest_relative) if manifest_path.is_file() else ""
    )
    expected_manifest_hash = str(args.expected_sha256 or "").strip().lower()
    if actual_manifest_hash != expected_manifest_hash:
        failures.append("manifest_sha256_mismatch")
    if manifest_path.is_file() and not worktree_matches_head(manifest_relative):
        failures.append("manifest_worktree_modified")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):
            raise ValueError("root must be an object")
    except Exception as exc:
        manifest = {}
        failures.append(f"manifest_json_invalid:{exc}")

    actual_head = git_head()
    expected_head = str(args.expected_commit_sha or "").strip().lower()
    if actual_head != expected_head:
        failures.append("approved_commit_sha_mismatch")
    if manifest.get("schema_version") != SCHEMA_VERSION:
        failures.append("manifest_schema_mismatch")
    if manifest.get("status") != READY_STATUS:
        failures.append("manifest_status_not_ready")
    if manifest.get("research_only") is not True:
        failures.append("manifest_research_only_not_true")
    if manifest.get("production_activation_allowed") is not False:
        failures.append("manifest_production_activation_not_false")
    if manifest.get("live_trading_enabled") is not False:
        failures.append("manifest_live_trading_not_false")

    try:
        expected = expected_scope(args)
    except Exception as exc:
        expected = {}
        failures.append(f"dispatch_scope_invalid:{exc}")
    actual_scope = manifest.get("approval_scope")
    if not isinstance(actual_scope, dict):
        actual_scope = {}
        failures.append("approval_scope_missing")
    else:
        actual_scope = dict(actual_scope)
        try:
            actual_scope["backtest_years"] = int(actual_scope.get("backtest_years"))
            for key in ("pit_universe_label_clean", "skip_collector", "fast_mode"):
                actual_scope[key] = bool_value(actual_scope.get(key))
            actual_scope["decision_time_utc"] = canonical_timestamp(
                actual_scope.get("decision_time_utc")
            )
            actual_scope["experiment_env"] = canonical_experiment_env(
                actual_scope.get("experiment_env")
            )
        except Exception as exc:
            failures.append(f"approval_scope_invalid:{exc}")
    if expected and actual_scope != expected:
        failures.append("approval_scope_mismatch")

    resolved_session_date = str(args.resolved_session_date or "").strip()
    if resolved_session_date and str(manifest.get("resolved_session_date") or "") != resolved_session_date:
        failures.append("resolved_session_date_mismatch")

    tracked_inputs = manifest.get("tracked_inputs")
    if not isinstance(tracked_inputs, dict) or not tracked_inputs:
        failures.append("tracked_inputs_missing_or_empty")
        tracked_inputs = {}
    for label, record in sorted(tracked_inputs.items()):
        if not isinstance(record, dict):
            failures.append(f"tracked_input_record_invalid:{label}")
            continue
        try:
            path, relative = safe_repo_file(record.get("path"))
            if relative == manifest_relative:
                raise ValueError("manifest cannot hash itself")
            actual_hash = git_blob_sha256(relative)
            worktree_hash = sha256(path)
            expected_hash = str(record.get("sha256") or "").strip().lower()
            matched = bool(expected_hash and actual_hash == expected_hash)
            worktree_clean = worktree_matches_head(relative)
            input_audits[str(label)] = {
                "path": relative,
                "sha256": actual_hash,
                "git_blob_sha256": actual_hash,
                "worktree_sha256": worktree_hash,
                "hash_basis": "git_blob_bytes",
                "worktree_matches_head": worktree_clean,
                "expected_sha256": expected_hash,
                "hash_matches": matched,
            }
            if not matched:
                failures.append(f"tracked_input_hash_mismatch:{label}")
            if not worktree_clean:
                failures.append(f"tracked_input_worktree_modified:{label}")
        except Exception as exc:
            failures.append(f"tracked_input_invalid:{label}:{exc}")

    payload = {
        "schema_version": "run287-fullrun-source-manifest-verification-v1",
        "status": "READY_APPROVED_FULLRUN_SOURCE_MANIFEST" if not failures else "BLOCKED_APPROVED_FULLRUN_SOURCE_MANIFEST",
        "ready": not failures,
        "contract_failures": sorted(set(failures)),
        "manifest": {
            "path": manifest_relative,
            "sha256": actual_manifest_hash,
            "expected_sha256": expected_manifest_hash,
            "hash_basis": "git_blob_bytes",
        },
        "code_identity": {
            "git_head": actual_head,
            "approved_commit_sha": expected_head,
        },
        "approval_scope": actual_scope,
        "expected_approval_scope": expected,
        "resolved_session_date": resolved_session_date or None,
        "tracked_inputs": input_audits,
        "research_only": True,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
        "automatic_promotion_allowed": False,
    }
    output = Path(args.output)
    if not output.is_absolute():
        output = REPO_ROOT / output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--expected-commit-sha", required=True)
    parser.add_argument("--universe-mode", required=True)
    parser.add_argument("--backtest-years", required=True)
    parser.add_argument("--pit-universe-label-clean", required=True)
    parser.add_argument("--skip-collector", required=True)
    parser.add_argument("--fast-mode", required=True)
    parser.add_argument("--leader-rescue-mode", required=True)
    parser.add_argument("--sidecar-profile", required=True)
    parser.add_argument("--artifact-profile", required=True)
    parser.add_argument("--gdrive-sync-mode", required=True)
    parser.add_argument("--portfolio-policy", required=True)
    parser.add_argument("--approved-target-policy-path", required=True)
    parser.add_argument("--decision-time-utc", required=True)
    parser.add_argument("--experiment-env-json", default="")
    parser.add_argument("--resolved-session-date", default="")
    parser.add_argument("--output", required=True)
    return parser.parse_args()


def main() -> int:
    payload = verify(parse_args())
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload["ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
