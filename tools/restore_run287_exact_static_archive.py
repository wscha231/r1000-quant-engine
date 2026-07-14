#!/usr/bin/env python3
"""Safely restore a verified Run287 exact-static ZIP into the repository."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import zipfile
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.build_run287_exact_static_archive import (  # noqa: E402
    MANIFEST_NAME,
    READY_STATUS as ARCHIVE_READY_STATUS,
    SCHEMA_VERSION as ARCHIVE_SCHEMA_VERSION,
)
from tools.run_run287_exact_packet_producer import (  # noqa: E402
    fingerprint,
    sha256_file,
    write_json,
)


SCHEMA_VERSION = "run287-exact-static-archive-restore-v1"
READY_STATUS = "READY_RUN287_EXACT_STATIC_ARCHIVE_RESTORED_REVIEW_ONLY"
BLOCKED_STATUS = "BLOCKED_RUN287_EXACT_STATIC_ARCHIVE_RESTORE"


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def safe_relative(value: str) -> Path:
    path = Path(value)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise ValueError(f"unsafe archive path: {value}")
    return path


def build(args: argparse.Namespace) -> dict[str, Any]:
    started = time.perf_counter()
    archive_path = Path(args.archive).resolve()
    output = Path(args.output).resolve()
    destination_root = Path(args.destination_root).resolve()
    failures: list[str] = []
    actual_archive_hash = sha256_file(archive_path) if archive_path.is_file() else ""
    expected_archive_hash = str(args.expected_archive_sha256 or "").lower()
    if not archive_path.is_file():
        failures.append("archive_missing")
    elif expected_archive_hash and actual_archive_hash != expected_archive_hash:
        failures.append("archive_hash_mismatch")
    file_bytes: dict[str, bytes] = {}
    manifest: dict[str, Any] = {}
    if not failures:
        try:
            with zipfile.ZipFile(archive_path) as archive:
                names = archive.namelist()
                if len(names) != len(set(names)):
                    failures.append("duplicate_archive_member")
                manifest = json.loads(archive.read(MANIFEST_NAME).decode("utf-8"))
                expected_names = {str(item.get("path") or "") for item in manifest.get("files") or []}
                if set(names) != expected_names | {MANIFEST_NAME}:
                    failures.append("archive_member_set_mismatch")
                for record in manifest.get("files") or []:
                    name = str(record.get("path") or "")
                    safe_relative(name)
                    raw = archive.read(name)
                    if len(raw) != int(record.get("bytes") or -1):
                        failures.append(f"member_size:{name}")
                    if sha256_bytes(raw) != str(record.get("sha256") or ""):
                        failures.append(f"member_hash:{name}")
                    file_bytes[name] = raw
        except Exception as exc:
            failures.append(f"archive_read:{type(exc).__name__}")
    if manifest:
        if manifest.get("schema_version") != ARCHIVE_SCHEMA_VERSION:
            failures.append("manifest_schema")
        if manifest.get("status") != ARCHIVE_READY_STATUS:
            failures.append("manifest_status")
        if int(manifest.get("price_map_source_count") or -1) != 363:
            failures.append("price_map_source_count")
        if int(manifest.get("file_count") or -1) != len(file_bytes):
            failures.append("file_count")

    reused = 0
    pending: list[tuple[Path, bytes]] = []
    if not failures:
        for name, raw in file_bytes.items():
            destination = destination_root / safe_relative(name)
            if destination.is_file():
                if sha256_file(destination) != sha256_bytes(raw):
                    failures.append(f"destination_collision:{name}")
                else:
                    reused += 1
            else:
                pending.append((destination, raw))
    if failures:
        payload = {
            "schema_version": SCHEMA_VERSION,
            "status": BLOCKED_STATUS,
            "contract_failures": failures,
            "archive": fingerprint(archive_path),
            "files_written": 0,
            "files_reused": reused,
            "network_requests_executed": 0,
            "fullrun_executed": False,
            "orders_generated": False,
            "target_books_mutated": False,
            "production_activation_allowed": False,
            "live_trading_enabled": False,
            "elapsed_seconds": time.perf_counter() - started,
        }
        write_json(output, payload)
        return payload

    for destination, raw in pending:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(raw)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "status": READY_STATUS,
        "archive": fingerprint(archive_path),
        "files_written": len(pending),
        "files_reused": reused,
        "verified_file_count": len(file_bytes),
        "price_map_source_count": int(manifest.get("price_map_source_count") or 0),
        "network_requests_executed": 0,
        "backtest_executed": False,
        "fullrun_executed": False,
        "orders_generated": False,
        "target_books_mutated": False,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
        "elapsed_seconds": time.perf_counter() - started,
    }
    write_json(output, payload)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True)
    parser.add_argument("--expected-archive-sha256", default="")
    parser.add_argument("--destination-root", default=str(REPO_ROOT))
    parser.add_argument("--output", required=True)
    return parser.parse_args()


def main() -> int:
    payload = build(parse_args())
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0 if payload.get("status") == READY_STATUS else 2


if __name__ == "__main__":
    raise SystemExit(main())
