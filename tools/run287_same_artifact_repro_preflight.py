#!/usr/bin/env python3
"""Preflight exact same-artifact reproduction for run287 target books.

This Phase 0/R1 diagnostic is intentionally read-only with respect to strategy
state. It does not dispatch a fullrun, download market data, regenerate target
books, tune thresholds, or promote a policy. It checks whether the runner input
artifacts recorded in the official vNext target-generation manifest are
available locally with matching hashes.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_RUN_ROOT = "cloud_results/full_rebuild/20260705_28725350727_global_alpha_universe"
DEFAULT_RUNNER_MANIFEST = DEFAULT_RUN_ROOT + "/alphaops_vnext/target_generation_input_manifest.json"
DEFAULT_OFFICIAL_ARTIFACT_ROOT = (
    r"H:\codex\tmp_r1000_grossfloor_20260625\outputs\run_28725350727_official_broker_artifact"
)
DEFAULT_LOCAL_FULL_CACHE = (
    r"H:\codex\tmp_r1000_grossfloor_20260625\outputs\run287_price_cache_full_candidate\cache_prices"
)
DEFAULT_OUTPUT_DIR = "outputs/run287_same_artifact_repro_preflight"


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def path_ref(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return str(path)


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def sha256_file(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def file_size(path: Path) -> int:
    if not path.exists() or not path.is_file():
        return 0
    return int(path.stat().st_size)


def nested(payload: dict[str, Any], *keys: str) -> Any:
    cur: Any = payload
    for key in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def git_commit_available(sha: str) -> bool:
    if not sha:
        return False
    result = subprocess.run(
        ["git", "cat-file", "-e", f"{sha}^{{commit}}"],
        cwd=REPO_ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


def count_price_files(path: Path) -> int:
    if not path.exists() or not path.is_dir():
        return 0
    return sum(1 for child in path.iterdir() if child.is_file() and child.suffix.lower() in {".csv", ".parquet"})


def availability_row(
    *,
    artifact: str,
    path: Path,
    expected_sha: str = "",
    expected_bytes: int | None = None,
    required: bool = True,
    note: str = "",
) -> dict[str, Any]:
    actual_sha = sha256_file(path)
    exists = path.exists()
    sha_matches = bool(expected_sha and actual_sha == expected_sha)
    bytes_matches = expected_bytes is None or file_size(path) == int(expected_bytes)
    status = "available_match" if exists and (not expected_sha or sha_matches) and bytes_matches else "available_mismatch"
    if not exists:
        status = "missing_required" if required else "missing_optional"
    return {
        "artifact": artifact,
        "path": path_ref(path),
        "required": bool(required),
        "exists": bool(exists),
        "expected_sha256": expected_sha,
        "actual_sha256": actual_sha,
        "sha256_matches": bool(sha_matches) if expected_sha else "",
        "expected_bytes": "" if expected_bytes is None else int(expected_bytes),
        "actual_bytes": file_size(path),
        "bytes_matches": bool(bytes_matches),
        "status": status,
        "note": note,
    }


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "artifact",
        "path",
        "required",
        "exists",
        "expected_sha256",
        "actual_sha256",
        "sha256_matches",
        "expected_bytes",
        "actual_bytes",
        "bytes_matches",
        "status",
        "note",
    ]
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def write_report(path: Path, payload: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    blockers = payload.get("blockers") or []
    lines = [
        "# Run287 Same-Artifact Reproduction Preflight",
        "",
        f"Status: `{payload['status']}`",
        "",
        "This is a research-only preflight. It did not dispatch a fullrun, download market data, regenerate target books, tune thresholds, or promote production.",
        "",
        "## Verdict",
        "",
        f"- exact_reproduction_ready: `{str(payload['exact_reproduction_ready']).lower()}`",
        f"- approximate_reproduction_available: `{str(payload['approximate_reproduction_available']).lower()}`",
        f"- runner_fidelity_status: `{payload['runner_fidelity_status']}`",
        f"- blocker_count: `{len(blockers)}`",
        "",
        "## Blockers",
        "",
    ]
    if blockers:
        lines.extend(f"- `{item}`" for item in blockers)
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            "## Input Availability",
            "",
            "| Artifact | Status | SHA match | Path |",
            "| --- | --- | --- | --- |",
        ]
    )
    for row in rows:
        lines.append(
            f"| `{row['artifact']}` | `{row['status']}` | `{row['sha256_matches']}` | `{row['path']}` |"
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "The frozen policy env and candidate book can be checked separately, but exact runner reproduction requires the byte-identical runner price files and long-crisis feature file recorded in the target-generation manifest. If either is absent, regenerated target-book attribution remains blocked or must carry `runner_fidelity_status=same_artifact_repro_blocked`.",
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def run(args: argparse.Namespace) -> dict[str, Any]:
    runner_manifest_path = repo_path(args.runner_manifest)
    official_root = repo_path(args.official_artifact_root)
    local_cache = repo_path(args.local_full_candidate_cache)
    output_dir = repo_path(args.output_dir)
    manifest = read_json(runner_manifest_path)

    candidate_meta = nested(manifest, "candidate_book") or {}
    price_manifest_meta = nested(manifest, "price_cache", "manifest") or {}
    features_meta = nested(manifest, "macro_crisis_inputs", "long_crisis_features") or {}
    thresholds_meta = nested(manifest, "macro_crisis_inputs", "long_crisis_thresholds") or {}
    code_meta = nested(manifest, "code") or {}

    candidate_book = official_root / "outputs" / "sec_enriched_candidate_replay" / "candidate_replay_book_sec_enriched.csv"
    official_price_manifest = official_root / "cache_prices" / "replay_price_cache_manifest.json"
    local_price_manifest = local_cache / "replay_price_cache_manifest.json"
    expected_features = official_root / "data_pit" / "macro" / "long_crisis_daily_features.parquet"
    packaged_post_vnext_features = official_root / "outputs" / "crisis_signals" / "daily_features.parquet"
    thresholds = official_root / "outputs" / "long_crisis_learning" / "best_thresholds.json"

    rows = [
        availability_row(
            artifact="runner_manifest",
            path=runner_manifest_path,
            required=True,
            note="committed or downloaded target-generation manifest",
        ),
        availability_row(
            artifact="candidate_book",
            path=candidate_book,
            expected_sha=str(candidate_meta.get("sha256") or ""),
            expected_bytes=int(candidate_meta.get("bytes") or 0) or None,
            required=True,
            note="SEC-enriched candidate book used by vNext",
        ),
        availability_row(
            artifact="official_price_cache_manifest",
            path=official_price_manifest,
            expected_sha=str(price_manifest_meta.get("sha256") or ""),
            expected_bytes=int(price_manifest_meta.get("bytes") or 0) or None,
            required=True,
            note="manifest is packaged, but price files may be excluded",
        ),
        availability_row(
            artifact="local_full_candidate_price_manifest",
            path=local_price_manifest,
            expected_sha=str(price_manifest_meta.get("sha256") or ""),
            expected_bytes=int(price_manifest_meta.get("bytes") or 0) or None,
            required=False,
            note="local complete candidate cache; acceptable only for approximate repro if sha differs",
        ),
        availability_row(
            artifact="runner_long_crisis_features_expected_path",
            path=expected_features,
            expected_sha=str(features_meta.get("sha256") or ""),
            expected_bytes=int(features_meta.get("bytes") or 0) or None,
            required=True,
            note="default path consumed by run_alphaops_vnext_policy_replay.py",
        ),
        availability_row(
            artifact="packaged_post_vnext_crisis_features",
            path=packaged_post_vnext_features,
            expected_sha=str(features_meta.get("sha256") or ""),
            expected_bytes=int(features_meta.get("bytes") or 0) or None,
            required=False,
            note="packaged outputs/crisis_signals file; not the manifest-recorded long-crisis input if sha differs",
        ),
        availability_row(
            artifact="long_crisis_thresholds",
            path=thresholds,
            expected_sha=str(thresholds_meta.get("sha256") or ""),
            expected_bytes=int(thresholds_meta.get("bytes") or 0) or None,
            required=True,
            note="threshold JSON used by vNext",
        ),
    ]

    required_missing_or_mismatch = [
        row["artifact"]
        for row in rows
        if row["required"] and row["status"] != "available_match"
    ]
    expected_price_csv_count = int(nested(manifest, "price_cache", "required_price_file_count") or 0)
    official_price_file_count = count_price_files(official_root / "cache_prices")
    local_price_file_count = count_price_files(local_cache)

    blockers: list[str] = []
    if "official_price_cache_manifest" in required_missing_or_mismatch:
        blockers.append("runner_price_cache_manifest_missing_or_mismatch")
    if official_price_file_count < expected_price_csv_count:
        blockers.append("runner_price_file_artifacts_missing")
    if "runner_long_crisis_features_expected_path" in required_missing_or_mismatch:
        blockers.append("runner_long_crisis_features_missing_or_mismatch")
    if not git_commit_available(str(code_meta.get("github_sha") or "")):
        blockers.append("runner_code_commit_unavailable")

    candidate_exact = next(row for row in rows if row["artifact"] == "candidate_book")["status"] == "available_match"
    thresholds_exact = next(row for row in rows if row["artifact"] == "long_crisis_thresholds")["status"] == "available_match"
    local_cache_complete = local_price_file_count >= expected_price_csv_count and local_price_file_count > 0
    packaged_features_exists = packaged_post_vnext_features.exists()
    exact_ready = not blockers and candidate_exact and thresholds_exact
    approximate_available = bool(candidate_exact and thresholds_exact and local_cache_complete and packaged_features_exists)

    payload = {
        "schema_version": "run287-same-artifact-repro-preflight-v1",
        "status": "blocked_exact_reproduction" if not exact_ready else "ready_for_exact_reproduction",
        "research_only": True,
        "fullrun_dispatched": False,
        "market_data_downloaded": False,
        "target_book_regenerated": False,
        "threshold_tuning_performed": False,
        "new_alpha_hook_added": False,
        "production_promotion_allowed": False,
        "exact_reproduction_ready": bool(exact_ready),
        "approximate_reproduction_available": bool(approximate_available),
        "runner_fidelity_status": "same_artifact_repro_blocked" if not exact_ready else "same_artifact_repro_ready",
        "runner_manifest": path_ref(runner_manifest_path),
        "official_artifact_root": path_ref(official_root),
        "local_full_candidate_cache": path_ref(local_cache),
        "runner_code_sha": str(code_meta.get("github_sha") or ""),
        "runner_code_ref": str(code_meta.get("github_ref") or ""),
        "runner_code_commit_available": git_commit_available(str(code_meta.get("github_sha") or "")),
        "expected_price_file_count": expected_price_csv_count,
        "official_artifact_price_file_count": official_price_file_count,
        "local_full_candidate_price_file_count": local_price_file_count,
        "blockers": blockers,
        "required_missing_or_mismatch": required_missing_or_mismatch,
        "artifacts": {
            "summary": path_ref(output_dir / "summary.json"),
            "input_availability": path_ref(output_dir / "input_availability.csv"),
            "report": path_ref(output_dir / "report.md"),
        },
    }

    write_json(output_dir / "summary.json", payload)
    write_csv(output_dir / "input_availability.csv", rows)
    write_report(output_dir / "report.md", payload, rows)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runner-manifest", default=DEFAULT_RUNNER_MANIFEST)
    parser.add_argument("--official-artifact-root", default=DEFAULT_OFFICIAL_ARTIFACT_ROOT)
    parser.add_argument("--local-full-candidate-cache", default=DEFAULT_LOCAL_FULL_CACHE)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> int:
    payload = run(parse_args())
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
