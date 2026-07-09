#!/usr/bin/env python3
"""Build a manifest and append-only index for earnings estimate archives."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = "earnings-estimate-archive-manifest-v1"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_record(path: Path) -> dict[str, Any]:
    record: dict[str, Any] = {
        "path": display_path(path),
        "exists": path.exists(),
    }
    if path.exists() and path.is_file():
        record.update(
            {
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    return record


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def latest_snapshot(snapshot_dir: Path, summary: dict[str, Any]) -> Path:
    summary_path = str(summary.get("snapshot_path") or "")
    if summary_path:
        path = repo_path(summary_path)
        if path.exists():
            return path
    candidates = sorted(snapshot_dir.glob("estimates_*.parquet"))
    return candidates[-1] if candidates else snapshot_dir / "estimates_missing.parquet"


def has_unmasked_secret_text(text: str) -> bool:
    patterns = [
        r"(?i)(?:apikey|token)=((?!\*\*\*)[A-Za-z0-9._-]{6,})",
        r"(?i)api key as\s+((?!\*\*\*)[A-Za-z0-9._-]{6,})",
        r"gh[opsu]_[A-Za-z0-9_]{12,}",
    ]
    return any(re.search(pattern, text) for pattern in patterns)


def scan_text_file(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {"path": display_path(path), "exists": path.exists(), "unmasked_secret_pattern_found": False}
    text = path.read_text(encoding="utf-8", errors="replace")
    return {
        "path": display_path(path),
        "exists": True,
        "unmasked_secret_pattern_found": has_unmasked_secret_text(text),
        "masked_url_credential_markers_present": bool(re.search(r"(?i)(apikey|token)=\*\*\*", text)),
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def append_index(index_path: Path, entry: dict[str, Any]) -> None:
    index_path.parent.mkdir(parents=True, exist_ok=True)
    key = (entry.get("run_id"), entry.get("run_attempt"), entry.get("fetch_date"))
    rows: list[dict[str, Any]] = []
    if index_path.exists():
        for line in index_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            row_key = (row.get("run_id"), row.get("run_attempt"), row.get("fetch_date"))
            if row_key != key:
                rows.append(row)
    rows.append(entry)
    index_path.write_text("\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n", encoding="utf-8")


def build_manifest(
    *,
    snapshot_dir: str,
    signals: str,
    summary: str,
    collector_log: str,
    manifest: str,
    index: str,
    run_id: str,
    run_attempt: str,
    head_sha: str,
    ref: str,
    workflow: str,
    artifact_name: str,
    shard_id: str = "",
    shard_file: str = "",
    shard_mode: str = "",
) -> dict[str, Any]:
    snapshot_dir_path = repo_path(snapshot_dir)
    signals_path = repo_path(signals)
    summary_path = repo_path(summary)
    collector_log_path = repo_path(collector_log)
    manifest_path = repo_path(manifest)
    index_path = repo_path(index)
    summary_payload = load_json(summary_path)
    snapshot_path = latest_snapshot(snapshot_dir_path, summary_payload)
    text_scans = [scan_text_file(summary_path), scan_text_file(collector_log_path)]
    unmasked_secret = any(scan.get("unmasked_secret_pattern_found") for scan in text_scans)
    fetch_date = str(summary_payload.get("feature_summary", {}).get("as_of_date") or "")
    if not fetch_date:
        snapshot_name = snapshot_path.stem
        if snapshot_name.startswith("estimates_") and len(snapshot_name) >= len("estimates_YYYYMMDD"):
            raw_date = snapshot_name.replace("estimates_", "")[:8]
            fetch_date = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:8]}"
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_now(),
        "research_only": True,
        "forward_only": True,
        "backtest_acceptance_allowed": False,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
        "fullrun_dispatched": False,
        "run_id": run_id,
        "run_attempt": run_attempt,
        "head_sha": head_sha,
        "ref": ref,
        "workflow": workflow,
        "artifact_name": artifact_name,
        "shard_id": shard_id,
        "shard_file": shard_file,
        "shard_mode": shard_mode,
        "fetch_date": fetch_date,
        "collector_status": summary_payload.get("status", "missing_summary"),
        "collector_reason": summary_payload.get("reason", ""),
        "ticker_count_requested": summary_payload.get("ticker_count_requested", 0),
        "request_snapshot_rows": summary_payload.get("request_snapshot_rows", summary_payload.get("snapshot_rows", 0)),
        "request_has_forward_estimate_rows": summary_payload.get(
            "request_has_forward_estimate_rows",
            summary_payload.get("has_forward_estimate_rows", 0),
        ),
        "request_estimate_coverage_ratio": summary_payload.get(
            "request_estimate_coverage_ratio",
            summary_payload.get("estimate_coverage_ratio", 0.0),
        ),
        "snapshot_rows": summary_payload.get("snapshot_rows", 0),
        "has_forward_estimate_rows": summary_payload.get("has_forward_estimate_rows", 0),
        "estimate_coverage_ratio": summary_payload.get("estimate_coverage_ratio", 0.0),
        "stored_estimate_coverage_ratio": summary_payload.get(
            "stored_estimate_coverage_ratio",
            summary_payload.get("estimate_coverage_ratio", 0.0),
        ),
        "same_day_snapshot_merged": summary_payload.get("same_day_snapshot_merged", False),
        "same_day_existing_rows": summary_payload.get("same_day_existing_rows", 0),
        "same_day_current_rows": summary_payload.get("same_day_current_rows", 0),
        "same_day_merged_rows": summary_payload.get("same_day_merged_rows", summary_payload.get("snapshot_rows", 0)),
        "coverage_ratio": summary_payload.get("coverage_ratio", 0.0),
        "fetch_sources": summary_payload.get("fetch_sources", []),
        "vendor_order": summary_payload.get("vendor_order", []),
        "collector_max_errors": summary_payload.get("max_errors", ""),
        "vendor_estimate_access": summary_payload.get("vendor_estimate_access", False),
        "vendor_blocked_errors": summary_payload.get("vendor_blocked_errors", False),
        "error_count": summary_payload.get("error_count", 0),
        "missing_vendor_coverage_policy": "neutral",
        "persistence": {
            "github_artifact_uploaded_by_workflow": True,
            "github_artifact_retention_days": 30,
            "gdrive_sync_attempted_by_workflow": True,
            "cache_saved_by_workflow": True,
            "index_path": display_path(index_path),
        },
        "files": {
            "snapshot": file_record(snapshot_path),
            "signals": file_record(signals_path),
            "summary": file_record(summary_path),
            "collector_log": file_record(collector_log_path),
        },
        "text_secret_scan": {
            "unmasked_secret_pattern_found": unmasked_secret,
            "scans": text_scans,
        },
        "verdict": "archive_manifest_written" if not unmasked_secret else "blocked_unmasked_secret_pattern",
    }
    write_json(manifest_path, payload)
    index_entry = {
        "schema_version": SCHEMA_VERSION,
        "indexed_at_utc": payload["generated_at_utc"],
        "run_id": run_id,
        "run_attempt": run_attempt,
        "head_sha": head_sha,
        "ref": ref,
        "workflow": workflow,
        "artifact_name": artifact_name,
        "shard_id": shard_id,
        "shard_file": shard_file,
        "shard_mode": shard_mode,
        "fetch_date": fetch_date,
        "collector_status": payload["collector_status"],
        "ticker_count_requested": payload["ticker_count_requested"],
        "request_snapshot_rows": payload["request_snapshot_rows"],
        "request_has_forward_estimate_rows": payload["request_has_forward_estimate_rows"],
        "snapshot_rows": payload["snapshot_rows"],
        "has_forward_estimate_rows": payload["has_forward_estimate_rows"],
        "estimate_coverage_ratio": payload["estimate_coverage_ratio"],
        "stored_estimate_coverage_ratio": payload["stored_estimate_coverage_ratio"],
        "same_day_snapshot_merged": payload["same_day_snapshot_merged"],
        "collector_max_errors": payload["collector_max_errors"],
        "snapshot_sha256": payload["files"]["snapshot"].get("sha256", ""),
        "signals_sha256": payload["files"]["signals"].get("sha256", ""),
        "manifest_path": display_path(manifest_path),
        "backtest_acceptance_allowed": False,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
    }
    append_index(index_path, index_entry)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-dir", default="data_pit/events/earnings_estimates")
    parser.add_argument("--signals", default="data_pit/events/earnings_revision_signals.parquet")
    parser.add_argument("--summary", default="outputs/earnings_estimates_daily/summary.json")
    parser.add_argument("--collector-log", default="outputs/earnings_estimates_daily/collector.log")
    parser.add_argument("--manifest", default="outputs/earnings_estimates_daily/archive_manifest.json")
    parser.add_argument("--index", default="data_pit/events/earnings_estimates/archive_index.jsonl")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--run-attempt", default="")
    parser.add_argument("--head-sha", default="")
    parser.add_argument("--ref", default="")
    parser.add_argument("--workflow", default="earnings_estimates_daily.yml")
    parser.add_argument("--artifact-name", default="")
    parser.add_argument("--shard-id", default="")
    parser.add_argument("--shard-file", default="")
    parser.add_argument("--shard-mode", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = build_manifest(
        snapshot_dir=args.snapshot_dir,
        signals=args.signals,
        summary=args.summary,
        collector_log=args.collector_log,
        manifest=args.manifest,
        index=args.index,
        run_id=args.run_id,
        run_attempt=args.run_attempt,
        head_sha=args.head_sha,
        ref=args.ref,
        workflow=args.workflow,
        artifact_name=args.artifact_name,
        shard_id=args.shard_id,
        shard_file=args.shard_file,
        shard_mode=args.shard_mode,
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 1 if payload["text_secret_scan"]["unmasked_secret_pattern_found"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
