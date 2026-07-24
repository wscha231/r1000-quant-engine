#!/usr/bin/env python3
"""Validate and quarantine a manifest-free Run287 paper snapshot.

This tool is intentionally read-only with respect to the supplied snapshot.
It emits a provenance record only after the complete legacy tree passes the
economic-state and safety validation implemented by the paper ledger.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd
import pandas_market_calendars as mcal

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.run_daily_simulated_fill_ledger import (
    LEGACY_SCHEMA_PROFILES,
    LEGACY_SCHEMA_PROFILE_V1_ZERO_EVENT,
    canonical_hash,
    directory_hashes,
    validate_legacy_root_snapshot,
)


def prepare_migration(
    *,
    state_dir: str | Path,
    requested_as_of_date: str,
    expected_source_tree_sha256: str,
    source_artifact_run_id: str = "",
    source_artifact_id: str = "",
    source_artifact_digest: str = "",
) -> dict[str, Any]:
    root = Path(state_dir).resolve()
    requested = pd.to_datetime(requested_as_of_date, errors="coerce")
    if pd.isna(requested):
        raise ValueError("--requested-as-of-date must be a valid date")
    requested = pd.Timestamp(requested).tz_localize(None).normalize()
    requested_schedule = mcal.get_calendar("NYSE").schedule(
        start_date=requested.date(),
        end_date=requested.date(),
    )
    if requested_schedule.empty:
        raise ValueError("--requested-as-of-date must be an NYSE session")
    if not root.is_dir() or root.is_symlink():
        raise ValueError("--state-dir must be a regular directory")
    if (root / "snapshot_integrity.json").exists():
        raise ValueError("legacy migration accepts only a manifest-free snapshot")

    summary, profile = validate_legacy_root_snapshot(root)
    if profile not in LEGACY_SCHEMA_PROFILES:
        raise ValueError(f"unsupported legacy schema profile:{profile}")
    legacy_date = pd.to_datetime(summary.get("as_of_date"), errors="coerce")
    if pd.isna(legacy_date):
        raise ValueError("legacy snapshot has no valid as-of date")
    legacy_date = pd.Timestamp(legacy_date).tz_localize(None).normalize()
    legacy_schedule = mcal.get_calendar("NYSE").schedule(
        start_date=legacy_date.date(),
        end_date=legacy_date.date(),
    )
    if legacy_schedule.empty or legacy_date > requested:
        raise ValueError(
            "legacy snapshot must end on an NYSE session at or before the requested session"
        )
    if (
        profile == LEGACY_SCHEMA_PROFILE_V1_ZERO_EVENT
        and legacy_date != requested
    ):
        raise ValueError(
            "legacy v1 zero-event migration requires the exact accepted "
            "session before chronological catch-up"
        )

    files = directory_hashes(root)
    if not files:
        raise ValueError("legacy snapshot contains no files")
    observed_tree_sha256 = canonical_hash(files)
    expected_tree_sha256 = str(expected_source_tree_sha256 or "").strip().lower()
    if (
        len(expected_tree_sha256) != 64
        or any(
            character not in "0123456789abcdef"
            for character in expected_tree_sha256
        )
    ):
        raise ValueError(
            "--expected-source-tree-sha256 must be an operator-pinned SHA-256"
        )
    if observed_tree_sha256 != expected_tree_sha256:
        raise ValueError(
            "legacy snapshot does not match the operator-pinned cross-source tree"
        )
    artifact_digest = str(source_artifact_digest or "").strip().lower()
    artifact_run_id = str(source_artifact_run_id or "").strip()
    artifact_id = str(source_artifact_id or "").strip()
    if (
        not artifact_run_id.isdigit()
        or artifact_run_id.startswith("0")
        or not artifact_id.isdigit()
        or artifact_id.startswith("0")
    ):
        raise ValueError(
            "legacy migration requires positive numeric source artifact ids"
        )
    if (
        not artifact_digest.startswith("sha256:")
        or len(artifact_digest) != 71
        or any(
            character not in "0123456789abcdef"
            for character in artifact_digest.removeprefix("sha256:")
        )
    ):
        raise ValueError("--source-artifact-digest must use sha256:<64 hex>")
    return {
        "schema_version": "run287-legacy-drive-paper-migration-v1",
        "status": "PENDING_SEMANTIC_ATTESTATION",
        "source": "GITHUB_ACTIONS_ARTIFACT_TREE_SHA256_PIN",
        "source_artifact_run_id": artifact_run_id,
        "source_artifact_id": artifact_id,
        "source_artifact_digest": artifact_digest,
        "legacy_as_of_date": legacy_date.date().isoformat(),
        "requested_as_of_date": requested.date().isoformat(),
        "legacy_schema_profile": profile,
        "remote_snapshot_integrity_present": False,
        "verified_cross_source_anchor_present": True,
        "legacy_semantic_attestation_required": True,
        "accepted_for_use": False,
        "review_only": True,
        "live_trading_enabled": False,
        "production_mutation_allowed": False,
        "remote_tree_file_count": len(files),
        "expected_source_tree_sha256": expected_tree_sha256,
        "remote_tree_sha256": observed_tree_sha256,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", required=True)
    parser.add_argument("--requested-as-of-date", required=True)
    parser.add_argument("--expected-source-tree-sha256", required=True)
    parser.add_argument("--source-artifact-run-id", required=True)
    parser.add_argument("--source-artifact-id", required=True)
    parser.add_argument("--source-artifact-digest", required=True)
    parser.add_argument("--output", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = prepare_migration(
        state_dir=args.state_dir,
        requested_as_of_date=args.requested_as_of_date,
        expected_source_tree_sha256=args.expected_source_tree_sha256,
        source_artifact_run_id=args.source_artifact_run_id,
        source_artifact_id=args.source_artifact_id,
        source_artifact_digest=args.source_artifact_digest,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
