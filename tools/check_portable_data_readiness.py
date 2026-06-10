#!/usr/bin/env python3
"""Audit whether portable data needed by the project is present locally.

This check is intentionally lightweight. It does not validate every row for
point-in-time correctness; it tells an operator which durable folders/files are
present after moving to a new computer and which ones need restoration from
Google Drive, object storage, or a new rebuild.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = "outputs/portable_data_readiness.json"


@dataclass(frozen=True)
class PathSpec:
    path: str
    role: str
    required: bool
    restore_hint: str


SPECS = [
    PathSpec(
        "cloud_results/full_rebuild/latest_global_alpha_universe",
        "latest committed/synced full rebuild result mirror",
        True,
        "Run full_rebuild_manual.yml or restore the latest full_rebuild bundle from Drive/object storage.",
    ),
    PathSpec(
        "cloud_results/full_rebuild/latest_global_alpha_universe/operating_snapshot",
        "latest operating snapshot outputs",
        True,
        "Restore latest full rebuild or replay sidecar outputs.",
    ),
    PathSpec(
        "cloud_results/full_rebuild/latest_global_alpha_universe/broker_replay",
        "broker-ledger replay state and daily equity",
        True,
        "Restore latest full rebuild or replay sidecar outputs.",
    ),
    PathSpec(
        "cloud_results/full_rebuild/latest_global_alpha_universe/macro_policy_engine",
        "latest macro policy state",
        True,
        "Restore latest full rebuild outputs or rerun macro policy sidecar.",
    ),
    PathSpec(
        "data_raw",
        "durable raw data landing area",
        False,
        "Restore raw historical membership, vendor exports, and raw SEC/macro data here when available.",
    ),
    PathSpec(
        "data_pit",
        "durable point-in-time normalized datasets",
        False,
        "Restore PIT parquet datasets here; create this as daily-decision backtests mature.",
    ),
    PathSpec(
        "data_raw/free",
        "free-first raw data lake restored from Drive/object storage",
        False,
        "Restore free SEC, price, macro, and proxy universe raw snapshots here.",
    ),
    PathSpec(
        "data_raw/free/sec",
        "free SEC raw filings and bulk archives",
        False,
        "Restore SEC companyfacts/submissions snapshots from Drive or rebuild from SEC EDGAR.",
    ),
    PathSpec(
        "data_raw/free/prices",
        "free daily price raw provider snapshots",
        False,
        "Restore reconciled free price inputs from Drive or rebuild from configured free providers.",
    ),
    PathSpec(
        "data_raw/free/macro",
        "free official macro raw snapshots",
        False,
        "Restore FRED/BLS/BEA/Treasury snapshots from Drive or refresh from official APIs.",
    ),
    PathSpec(
        "data_raw/free/universe_proxy",
        "free approximate large-cap universe inputs",
        False,
        "Restore proxy universe snapshots; label related backtests as proxy/survivorship-risk.",
    ),
    PathSpec(
        "data_pit/free",
        "free-first normalized PIT/proxy parquet datasets",
        False,
        "Restore normalized free PIT datasets from Drive or run the free data normalization pipeline.",
    ),
    PathSpec(
        "data_pit/free/coverage_audit.json",
        "free data coverage and PIT/proxy label audit",
        False,
        "Generate after building normalized free data so backtests can report data quality explicitly.",
    ),
    PathSpec(
        "manifests/free_data",
        "small free data snapshot manifests",
        False,
        "Restore or commit small manifests that describe Drive snapshots, source ranges, PIT labels, and known gaps.",
    ),
    PathSpec(
        "cache_prices",
        "local replay price cache",
        False,
        "Restore from Drive/cache bundle or let replay/full rebuild regenerate it.",
    ),
    PathSpec(
        "outputs/companyfacts.zip",
        "SEC companyfacts bulk archive copy",
        False,
        "Restore from Drive or run tools/refresh_companyfacts_bulk.py.",
    ),
    PathSpec(
        "outputs/gdrive_sync_manifest.json",
        "last full rebuild Google Drive sync manifest",
        False,
        "Produced by GitHub full_rebuild_manual.yml when Drive sync is configured.",
    ),
    PathSpec(
        "outputs/replay_gdrive_manifest.json",
        "last replay sidecar Google Drive sync manifest",
        False,
        "Produced by GitHub alphaops_replay_sidecars_manual.yml when Drive sync is configured.",
    ),
]


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return str(path)


def dir_stats(path: Path) -> tuple[int, int]:
    if not path.exists():
        return 0, 0
    if path.is_file():
        return 1, path.stat().st_size
    count = 0
    size = 0
    for item in path.rglob("*"):
        if item.is_file():
            count += 1
            try:
                size += item.stat().st_size
            except OSError:
                pass
    return count, size


def audit_path(spec: PathSpec) -> dict[str, Any]:
    path = REPO_ROOT / spec.path
    exists = path.exists()
    file_count, size_bytes = dir_stats(path)
    status = "ok" if exists else "missing_required" if spec.required else "missing_optional"
    return {
        "path": spec.path,
        "role": spec.role,
        "required": spec.required,
        "exists": exists,
        "is_file": path.is_file(),
        "is_dir": path.is_dir(),
        "file_count": file_count,
        "size_bytes": size_bytes,
        "size_mb": round(size_bytes / 1024 / 1024, 3),
        "status": status,
        "restore_hint": "" if exists else spec.restore_hint,
    }


def build_payload(root: Path) -> dict[str, Any]:
    rows = [audit_path(spec) for spec in SPECS]
    missing_required = [row for row in rows if row["status"] == "missing_required"]
    missing_optional = [row for row in rows if row["status"] == "missing_optional"]
    return {
        "schema_version": "portable-data-readiness-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "repo_root": str(root.resolve()),
        "status": "ready_minimum" if not missing_required else "missing_required_data",
        "required_count": sum(1 for row in rows if row["required"]),
        "missing_required_count": len(missing_required),
        "missing_optional_count": len(missing_optional),
        "paths": rows,
        "notes": [
            "Minimum readiness means the latest cloud result mirror is present.",
            "Optional caches can be regenerated, but restoring them saves time.",
            "This audit does not prove point-in-time data correctness.",
        ],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--no-write", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = build_payload(REPO_ROOT)
    text = json.dumps(payload, indent=2, sort_keys=True)
    print(text)
    if not args.no_write:
        out = REPO_ROOT / args.output
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text + "\n", encoding="utf-8")
    return 0 if payload["status"] == "ready_minimum" else 1


if __name__ == "__main__":
    raise SystemExit(main())
