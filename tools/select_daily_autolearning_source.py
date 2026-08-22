#!/usr/bin/env python3
"""Select a provenance-locked Daily AutoLearning input or fail closed.

The daily scan is not allowed to treat a checked-in directory as "latest".
This gate verifies the directory's own manifests, hashes, source workflow run,
upstream artifact inventory, completed NYSE session, and chronological paper
cursor before any learning or historical replay can start.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import subprocess
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "daily-autolearning-source-selection-v1"
UPSTREAM_WORKFLOWS = {
    "model": "full_rebuild_manual.yml",
    "prices_macro": "free_data_daily_update.yml",
    "fundamentals_readiness": "data_readiness_preflight.yml",
    "sec_13f": "sec_13f_quarterly_refresh.yml",
    "sec_form4": "sec_form4_daily_refresh.yml",
    "earnings_estimates": "earnings_estimates_daily.yml",
}
LAYER_WORKFLOW_KEYS = {
    "prices": "prices_macro",
    "macro": "prices_macro",
    "fundamentals": "fundamentals_readiness",
    "form4": "sec_form4",
    "13f": "sec_13f",
}
STRICT_SESSION_LAYERS = {"prices", "macro"}
ACCEPTED_CURSOR_RE = re.compile(
    r"^accepted-paper-catchup-(\d{4}-\d{2}-\d{2})-(\d+)$"
)


def read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha256(payload: Any) -> str:
    raw = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def normalize_digest(value: Any) -> str:
    text = str(value or "").strip().lower()
    return text.removeprefix("sha256:")


def parse_iso_date(value: Any) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def actual_manifest_path(candidate: Path, recorded: str) -> Path:
    normalized = str(recorded or "").replace("\\", "/")
    if "/outputs/" in normalized:
        return candidate / normalized.split("/outputs/", 1)[1]
    if "/cache_prices/" in normalized:
        return candidate / "manifests" / Path(normalized).name
    return candidate / Path(normalized).name


def ticker_universe_hash(scored_path: Path) -> tuple[str, int]:
    tickers: set[str] = set()
    with scored_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or "ticker" not in reader.fieldnames:
            raise ValueError("scored_latest.csv must contain ticker")
        for row in reader:
            ticker = str(row.get("ticker") or "").strip().upper()
            if ticker:
                tickers.add(ticker)
    canonical = "\n".join(sorted(tickers)) + "\n"
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest(), len(tickers)


def github_get(repo: str, path: str, token: str) -> Any:
    url = f"https://api.github.com/repos/{repo}/{path.lstrip('/')}"
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "r1000-daily-autolearning-source-gate",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def compact_artifact(item: dict[str, Any]) -> dict[str, Any]:
    workflow_run = item.get("workflow_run") or {}
    return {
        "id": int(item.get("id") or 0),
        "name": str(item.get("name") or ""),
        "digest": str(item.get("digest") or ""),
        "expired": bool(item.get("expired", False)),
        "created_at": str(item.get("created_at") or ""),
        "updated_at": str(item.get("updated_at") or ""),
        "run_id": int(workflow_run.get("id") or 0),
        "head_sha": str(workflow_run.get("head_sha") or ""),
        "head_branch": str(workflow_run.get("head_branch") or ""),
    }


def artifacts_for_run(repo: str, run_id: int, token: str) -> list[dict[str, Any]]:
    payload = github_get(repo, f"actions/runs/{run_id}/artifacts?per_page=100", token)
    return [compact_artifact(item) for item in payload.get("artifacts", [])]


def compact_run(
    repo: str,
    run: dict[str, Any],
    token: str,
) -> dict[str, Any]:
    run_id = int(run.get("id") or run.get("databaseId") or 0)
    artifacts = artifacts_for_run(repo, run_id, token) if run_id else []
    return {
        "run_id": run_id,
        "workflow_id": int(run.get("workflow_id") or 0),
        "workflow_path": str(run.get("path") or ""),
        "head_sha": str(run.get("head_sha") or run.get("headSha") or ""),
        "head_branch": str(run.get("head_branch") or run.get("headBranch") or ""),
        "event": str(run.get("event") or ""),
        "status": str(run.get("status") or ""),
        "conclusion": str(run.get("conclusion") or ""),
        "created_at": str(run.get("created_at") or run.get("createdAt") or ""),
        "updated_at": str(run.get("updated_at") or run.get("updatedAt") or ""),
        "html_url": str(run.get("html_url") or run.get("url") or ""),
        "artifacts": artifacts,
    }


def discover_accepted_cursor(repo: str, token: str) -> list[dict[str, Any]]:
    accepted: list[dict[str, Any]] = []
    for page in range(1, 21):
        payload = github_get(
            repo,
            f"actions/artifacts?per_page=100&page={page}",
            token,
        )
        rows = payload.get("artifacts", [])
        if not rows:
            break
        for row in rows:
            if ACCEPTED_CURSOR_RE.match(str(row.get("name") or "")):
                accepted.append(compact_artifact(row))
        if accepted:
            break
    if accepted:
        newest = max(accepted, key=lambda item: str(item.get("name") or ""))
        run_id = int(newest.get("run_id") or 0)
        if run_id:
            run = github_get(repo, f"actions/runs/{run_id}", token)
            newest["workflow_conclusion"] = str(run.get("conclusion") or "")
            newest["workflow_path"] = str(run.get("path") or "")
    return accepted


def discover_inventory(repo: str, source_run_id: int, token: str) -> dict[str, Any]:
    source = github_get(repo, f"actions/runs/{source_run_id}", token)
    workflows: dict[str, Any] = {}
    for key, workflow in UPSTREAM_WORKFLOWS.items():
        encoded = urllib.parse.quote(workflow, safe="")
        payload = github_get(
            repo,
            f"actions/workflows/{encoded}/runs?branch=master&status=success&per_page=1",
            token,
        )
        rows = payload.get("workflow_runs", [])
        workflows[key] = compact_run(repo, rows[0], token) if rows else {}
    return {
        "source_run": compact_run(repo, source, token),
        "workflow_runs": workflows,
        "accepted_artifacts": discover_accepted_cursor(repo, token),
    }


def compact_inventory(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize a fixture or previously captured inventory."""
    if "source_run" not in payload:
        raise ValueError("inventory must contain source_run")
    return {
        "source_run": dict(payload.get("source_run") or {}),
        "workflow_runs": {
            str(key): dict(value or {})
            for key, value in dict(payload.get("workflow_runs") or {}).items()
        },
        "accepted_artifacts": [
            dict(item) for item in list(payload.get("accepted_artifacts") or [])
        ],
    }


def git_is_ancestor(older_sha: str, current_sha: str) -> bool | None:
    if not older_sha or not current_sha:
        return None
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", older_sha, current_sha],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return True
    if result.returncode == 1:
        return False
    return None


def next_nyse_session(processed_through: str) -> str:
    parsed = parse_iso_date(processed_through)
    if parsed is None:
        return ""
    try:
        import pandas as pd
        import pandas_market_calendars as mcal
    except Exception:
        return ""
    start = pd.Timestamp(parsed) + pd.Timedelta(days=1)
    schedule = mcal.get_calendar("NYSE").schedule(
        start_date=start.date(),
        end_date=(start + pd.Timedelta(days=14)).date(),
    )
    if schedule.empty:
        return ""
    return pd.Timestamp(schedule.index[0]).date().isoformat()


def selected_cursor(artifacts: list[dict[str, Any]]) -> dict[str, Any]:
    candidates: list[tuple[str, dict[str, Any]]] = []
    for artifact in artifacts:
        match = ACCEPTED_CURSOR_RE.match(str(artifact.get("name") or ""))
        if not match or bool(artifact.get("expired", False)):
            continue
        if str(artifact.get("head_branch") or "master") != "master":
            continue
        if str(artifact.get("workflow_conclusion") or "") != "success":
            continue
        candidates.append((match.group(1), artifact))
    if not candidates:
        return {
            "status": "MISSING_ACCEPTED_CURSOR",
            "processed_through_date": "",
            "earliest_unprocessed_session": "",
            "artifact": {},
        }
    processed, artifact = max(candidates, key=lambda item: item[0])
    return {
        "status": "VERIFIED_FROM_ACCEPTED_ARTIFACT_NAME",
        "processed_through_date": processed,
        "earliest_unprocessed_session": next_nyse_session(processed),
        "artifact": artifact,
    }


def choose_source_artifact(
    source_run: dict[str, Any],
    source_run_id: str,
) -> dict[str, Any]:
    artifacts = list(source_run.get("artifacts") or [])
    preferred = [
        item
        for item in artifacts
        if source_run_id in str(item.get("name") or "")
        and "official" in str(item.get("name") or "").lower()
        and not bool(item.get("expired", False))
    ]
    return dict(preferred[0] if preferred else artifacts[0] if artifacts else {})


def blocker(code: str, detail: str) -> dict[str, str]:
    return {"code": code, "detail": detail}


def input_contracts(
    snapshot: dict[str, Any],
    readiness: dict[str, Any],
    universe: dict[str, Any],
    actual_files: dict[str, dict[str, Any]],
    source: dict[str, Any],
    upstream: dict[str, Any],
    universe_hash: str,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    source_artifact = source.get("artifact") or {}
    for row in list(snapshot.get("watermarks") or []):
        layer = str(row.get("layer") or "")
        if layer not in {"prices", "macro", "fundamentals", "form4", "13f"}:
            continue
        stats = dict(row.get("stats") or {})
        workflow_key = LAYER_WORKFLOW_KEYS[layer]
        latest = dict(upstream.get(workflow_key) or {})
        latest_artifacts = list(latest.get("artifacts") or [])
        latest_artifact = latest_artifacts[0] if latest_artifacts else {}
        result.append(
            {
                "layer": layer,
                "as_of": str(row.get("latest_asof") or ""),
                "available_from": str(stats.get("modified_utc") or ""),
                "cadence_days": row.get("cadence_days"),
                "candidate_data_sha256": str(stats.get("sha256") or ""),
                "candidate_code_sha": str(source.get("commit_sha") or ""),
                "candidate_source_run_id": str(source.get("run_id") or ""),
                "candidate_source_artifact_digest": str(
                    source_artifact.get("digest") or ""
                ),
                "latest_success_run_id": latest.get("run_id"),
                "latest_success_code_sha": str(latest.get("head_sha") or ""),
                "latest_success_available_from": str(latest.get("updated_at") or ""),
                "latest_success_artifact_id": latest_artifact.get("id"),
                "latest_success_artifact_digest": str(
                    latest_artifact.get("digest") or ""
                ),
                "latest_success_as_of": "NOT_EXPOSED_BY_GITHUB_METADATA",
                "status": str(row.get("status") or "missing"),
            }
        )

    scored = actual_files.get("scored_latest.csv") or {}
    generated = str(snapshot.get("generated_at_utc") or "")
    scored_meta = dict(universe.get("scored_latest") or {})
    result.extend(
        [
            {
                "layer": "model_scores",
                "as_of": str(scored_meta.get("max_date") or ""),
                "available_from": generated,
                "candidate_data_sha256": str(scored.get("sha256") or ""),
                "candidate_code_sha": str(source.get("commit_sha") or ""),
                "candidate_source_run_id": str(source.get("run_id") or ""),
                "candidate_source_artifact_digest": str(
                    source_artifact.get("digest") or ""
                ),
                "status": "present" if scored.get("exists") else "missing",
            },
            {
                "layer": "universe",
                "as_of": str(scored_meta.get("max_date") or ""),
                "available_from": str(universe.get("generated_at_utc") or generated),
                "candidate_data_sha256": universe_hash,
                "candidate_code_sha": str(source.get("commit_sha") or ""),
                "candidate_source_run_id": str(source.get("run_id") or ""),
                "candidate_source_artifact_digest": str(
                    source_artifact.get("digest") or ""
                ),
                "source": str(universe.get("primary_universe_source") or ""),
                "fallback_used": bool(universe.get("fallback_used", False)),
                "status": str(universe.get("status") or "missing"),
            },
        ]
    )
    return result


def evaluate(args: argparse.Namespace) -> dict[str, Any]:
    candidate = Path(args.candidate_run).resolve()
    snapshot_path = candidate / "data_freshness_contract" / "data_snapshot_manifest.json"
    readiness_path = candidate / "data_readiness" / "summary.json"
    universe_path = candidate / "universe_health" / "summary.json"
    patch_path = candidate / "patch_application_manifest.json"
    scored_path = candidate / "scored_latest.csv"

    snapshot = read_json(snapshot_path)
    readiness = read_json(readiness_path)
    universe = read_json(universe_path)
    patch_manifest = read_json(patch_path)
    source_run_id = str(
        snapshot.get("source_run_id")
        or patch_manifest.get("run_id")
        or patch_manifest.get("artifact_id")
        or ""
    )
    source_commit_sha = str(
        snapshot.get("source_commit_sha")
        or patch_manifest.get("commit_sha")
        or patch_manifest.get("head_sha")
        or ""
    )

    if args.github_inventory:
        inventory = compact_inventory(read_json(Path(args.github_inventory)))
    else:
        token = str(args.github_token or os.environ.get("GITHUB_TOKEN") or "")
        if not token:
            raise ValueError("GITHUB_TOKEN or --github-inventory is required")
        if not source_run_id.isdigit():
            raise ValueError("candidate source_run_id is missing or invalid")
        inventory = discover_inventory(
            args.github_repository,
            int(source_run_id),
            token,
        )

    source_run = dict(inventory.get("source_run") or {})
    source_artifact = choose_source_artifact(source_run, source_run_id)
    source = {
        "run_id": source_run_id,
        "commit_sha": source_commit_sha,
        "artifact_name_declared": str(snapshot.get("source_artifact_name") or ""),
        "run": source_run,
        "artifact": source_artifact,
    }

    actual_files: dict[str, dict[str, Any]] = {}
    recorded_mismatches: list[dict[str, Any]] = []
    for record in list(snapshot.get("files") or []):
        actual_path = actual_manifest_path(candidate, str(record.get("path") or ""))
        relative = (
            actual_path.relative_to(candidate).as_posix()
            if actual_path.is_relative_to(candidate)
            else str(actual_path)
        )
        exists = actual_path.is_file()
        actual_hash = sha256_file(actual_path) if exists else ""
        expected_hash = normalize_digest(record.get("sha256"))
        actual_files[relative] = {
            "exists": exists,
            "bytes": actual_path.stat().st_size if exists else 0,
            "sha256": actual_hash,
            "recorded_sha256": expected_hash,
        }
        if not exists or not expected_hash or expected_hash != actual_hash:
            recorded_mismatches.append(
                {
                    "path": relative,
                    "reason": (
                        "missing_file"
                        if not exists
                        else "missing_recorded_sha256"
                        if not expected_hash
                        else "sha256_mismatch"
                    ),
                    "recorded_sha256": expected_hash,
                    "actual_sha256": actual_hash,
                }
            )

    if "scored_latest.csv" not in actual_files:
        actual_files["scored_latest.csv"] = {
            "exists": scored_path.is_file(),
            "bytes": scored_path.stat().st_size if scored_path.is_file() else 0,
            "sha256": sha256_file(scored_path) if scored_path.is_file() else "",
            "recorded_sha256": "",
        }
    universe_hash, ticker_count = (
        ticker_universe_hash(scored_path) if scored_path.is_file() else ("", 0)
    )
    contracts = input_contracts(
        snapshot,
        readiness,
        universe,
        actual_files,
        source,
        dict(inventory.get("workflow_runs") or {}),
        universe_hash,
    )
    cursor = selected_cursor(list(inventory.get("accepted_artifacts") or []))
    lineage = git_is_ancestor(source_commit_sha, args.current_code_sha)

    blockers: list[dict[str, str]] = []
    if str(source_run.get("conclusion") or "") != "success":
        blockers.append(
            blocker(
                "SOURCE_RUN_NOT_SUCCESSFUL",
                f"candidate source run {source_run_id} concluded "
                f"{source_run.get('conclusion') or 'unknown'}",
            )
        )
    if not source_artifact or bool(source_artifact.get("expired", False)):
        blockers.append(
            blocker("SOURCE_ARTIFACT_UNAVAILABLE", "exact source artifact is unavailable")
        )
    if not normalize_digest(source_artifact.get("digest")):
        blockers.append(
            blocker("SOURCE_ARTIFACT_DIGEST_MISSING", "source artifact has no API digest")
        )
    if (
        str(source.get("artifact_name_declared") or "")
        != str(source_artifact.get("name") or "")
    ):
        blockers.append(
            blocker(
                "SOURCE_ARTIFACT_NAME_MISMATCH",
                "declared source artifact name does not equal the API artifact name",
            )
        )
    if lineage is not True:
        blockers.append(
            blocker(
                "SOURCE_CODE_LINEAGE_UNVERIFIED",
                "candidate source commit is not a verified ancestor of current code",
            )
        )
    if recorded_mismatches:
        blockers.append(
            blocker(
                "CANDIDATE_BUNDLE_HASH_MISMATCH",
                f"{len(recorded_mismatches)} recorded file identities are missing or unequal",
            )
        )

    expected_date = parse_iso_date(args.expected_session_date)
    for contract in contracts:
        layer = str(contract.get("layer") or "")
        as_of = parse_iso_date(contract.get("as_of"))
        if expected_date is None:
            blockers.append(
                blocker("EXPECTED_SESSION_MISSING", "completed NYSE session is missing")
            )
            break
        if as_of is None:
            blockers.append(
                blocker("INPUT_AS_OF_MISSING", f"{layer} has no parseable as_of")
            )
            continue
        if layer in STRICT_SESSION_LAYERS and as_of != expected_date:
            blockers.append(
                blocker(
                    "INPUT_SESSION_MISMATCH",
                    f"{layer} as_of {as_of.isoformat()} != {expected_date.isoformat()}",
                )
            )
        cadence = contract.get("cadence_days")
        if cadence not in (None, "") and (expected_date - as_of).days > int(cadence):
            blockers.append(
                blocker(
                    "INPUT_STALE",
                    f"{layer} is {(expected_date - as_of).days} days old; cadence={cadence}",
                )
            )

    if readiness.get("ready_for_policy_replay") is not True:
        blockers.append(
            blocker(
                "POLICY_REPLAY_NOT_READY",
                "candidate readiness does not permit policy replay",
            )
        )
    if cursor.get("status") != "VERIFIED_FROM_ACCEPTED_ARTIFACT_NAME":
        blockers.append(
            blocker("ACCEPTED_CURSOR_MISSING", "accepted chronological cursor is unavailable")
        )
    elif not cursor.get("earliest_unprocessed_session"):
        blockers.append(
            blocker(
                "NEXT_SESSION_UNRESOLVED",
                "NYSE calendar could not resolve the earliest unprocessed session",
            )
        )
    elif cursor.get("earliest_unprocessed_session") != args.expected_session_date:
        blockers.append(
            blocker(
                "CHRONOLOGICAL_GAP",
                "earliest unprocessed session "
                f"{cursor.get('earliest_unprocessed_session')} must be handled before "
                f"{args.expected_session_date}",
            )
        )

    candidate_generated = str(snapshot.get("generated_at_utc") or "")
    for key, latest in sorted(dict(inventory.get("workflow_runs") or {}).items()):
        if not latest:
            blockers.append(
                blocker("UPSTREAM_SUCCESS_MISSING", f"{key} has no successful run")
            )
            continue
        latest_artifacts = list(latest.get("artifacts") or [])
        if not latest_artifacts or not normalize_digest(
            latest_artifacts[0].get("digest")
        ):
            blockers.append(
                blocker(
                    "UPSTREAM_ARTIFACT_DIGEST_MISSING",
                    f"{key} latest successful run has no exact artifact digest",
                )
            )
        if str(latest.get("updated_at") or "") > candidate_generated:
            blockers.append(
                blocker(
                    "NEWER_UPSTREAM_NOT_BOUND",
                    f"{key} run {latest.get('run_id')} is newer than the candidate bundle",
                )
            )

    blockers = sorted(
        {canonical_sha256(item): item for item in blockers}.values(),
        key=lambda item: (item["code"], item["detail"]),
    )
    actual_identity = {
        key: value.get("sha256", "") for key, value in sorted(actual_files.items())
    }
    bundle_identity = {
        "source_run_id": source_run_id,
        "source_commit_sha": source_commit_sha,
        "source_artifact_digest": normalize_digest(source_artifact.get("digest")),
        "data_snapshot_manifest_sha256": sha256_file(snapshot_path),
        "patch_application_manifest_sha256": sha256_file(patch_path),
        "data_readiness_sha256": sha256_file(readiness_path),
        "universe_health_sha256": sha256_file(universe_path),
        "files": actual_identity,
        "universe_sha256": universe_hash,
    }
    ready = not blockers
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "status": "READY_TRUSTED_CURRENT_BUNDLE" if ready else "BLOCKED_STALE_OR_MIXED_INPUT",
        "ready_for_diagnostics": ready,
        "checked_at_utc": str(args.checked_at_utc or ""),
        "expected_session_date": str(args.expected_session_date or ""),
        "current_code_sha": str(args.current_code_sha or ""),
        "candidate_root": str(args.candidate_run),
        "candidate_identity": {
            **bundle_identity,
            "bundle_sha256": canonical_sha256(bundle_identity),
            "ticker_count": ticker_count,
            "source_run": source_run,
            "source_artifact": source_artifact,
            "source_code_ancestor_of_current": lineage,
        },
        "input_contracts": contracts,
        "latest_successful_upstreams": inventory.get("workflow_runs") or {},
        "chronological_cursor": cursor,
        "manifest_file_mismatches": recorded_mismatches,
        "blockers": blockers,
        "safety": {
            "learning_executed": False,
            "backtest_executed": False,
            "target_books_mutated": False,
            "orders_generated": False,
            "paper_account_mutated": False,
            "outcome_ledger_mutated": False,
            "promotion_allowed": False,
            "live_trading_enabled": False,
        },
    }
    semantic = dict(payload)
    semantic.pop("checked_at_utc", None)
    payload["semantic_sha256"] = canonical_sha256(semantic)
    return payload


def render_report(payload: dict[str, Any]) -> str:
    cursor = dict(payload.get("chronological_cursor") or {})
    lines = [
        "# Daily AutoLearning source selection",
        "",
        f"- Status: `{payload['status']}`",
        f"- Expected completed NYSE session: `{payload['expected_session_date'] or 'missing'}`",
        f"- Processed through: `{cursor.get('processed_through_date') or 'missing'}`",
        f"- Earliest unprocessed session: `{cursor.get('earliest_unprocessed_session') or 'missing'}`",
        f"- Semantic input/result SHA-256: `{payload['semantic_sha256']}`",
        "",
        "## Input contracts",
        "",
        "| Layer | as_of | available_from | data SHA-256 | source run |",
        "|---|---|---|---|---|",
    ]
    for row in payload.get("input_contracts", []):
        lines.append(
            "| {layer} | {as_of} | {available} | {sha} | {run} |".format(
                layer=row.get("layer") or "",
                as_of=row.get("as_of") or "missing",
                available=row.get("available_from") or "missing",
                sha=row.get("candidate_data_sha256") or "missing",
                run=row.get("candidate_source_run_id") or "missing",
            )
        )
    lines.extend(["", "## Blockers", ""])
    if payload.get("blockers"):
        for row in payload["blockers"]:
            lines.append(f"- `{row['code']}`: {row['detail']}")
    else:
        lines.append("- None")
    lines.extend(
        [
            "",
            "## Safety result",
            "",
            "No learning, backtest, target-book write, order generation, paper-account write,",
            "outcome-ledger write, promotion, or live-trading action was performed by this gate.",
            "",
        ]
    )
    return "\n".join(lines)


def write_github_output(payload: dict[str, Any]) -> None:
    output = os.environ.get("GITHUB_OUTPUT", "")
    if not output:
        return
    cursor = dict(payload.get("chronological_cursor") or {})
    rows = {
        "ready": "yes" if payload.get("ready_for_diagnostics") else "no",
        "status": str(payload.get("status") or ""),
        "semantic_sha256": str(payload.get("semantic_sha256") or ""),
        "processed_through_date": str(cursor.get("processed_through_date") or ""),
        "earliest_unprocessed_session": str(
            cursor.get("earliest_unprocessed_session") or ""
        ),
    }
    with Path(output).open("a", encoding="utf-8") as handle:
        for key, value in rows.items():
            handle.write(f"{key}={value}\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-run", required=True)
    parser.add_argument("--expected-session-date", required=True)
    parser.add_argument("--current-code-sha", required=True)
    parser.add_argument("--github-repository", default="wscha231/r1000-quant-engine")
    parser.add_argument("--github-token", default="")
    parser.add_argument("--github-inventory", default="")
    parser.add_argument("--checked-at-utc", default="")
    parser.add_argument(
        "--output-dir",
        default="outputs/daily_autolearning_source_selection",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = evaluate(args)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = output_dir / "summary.json"
    summary_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_dir / "report.md").write_text(render_report(payload), encoding="utf-8")
    write_github_output(payload)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
