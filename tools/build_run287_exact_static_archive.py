#!/usr/bin/env python3
"""Build the hash-indexed static archive required by Run287 exact packets.

This is a one-time export utility.  It copies no source file and performs no
network request.  The output ZIP contains only the frozen selector anchors,
their exact 363 price-map files, and the four official Run287 policy files.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import zipfile
from pathlib import Path
from typing import Any, Mapping

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.run_run287_exact_packet_producer import (  # noqa: E402
    fingerprint,
    read_json,
    resolve_portable_path,
    sha256_file,
    write_json,
)


SCHEMA_VERSION = "run287-exact-static-archive-v1"
READY_STATUS = "READY_RUN287_EXACT_STATIC_ARCHIVE_REVIEW_ONLY"
MANIFEST_NAME = "run287_exact_static_archive_manifest.json"

STATIC_PLAN_LABELS = (
    "universe",
    "base_selection_context",
    "base_score_stack",
    "frozen_score_stack_manifest",
    "benchmark_seed",
    "selector_contract_manifest",
    "pinned_import_manifest",
    "price_map_manifest",
)
OFFICIAL_FILES = {
    "official_main_target_book.csv": "3e863068e118af3f832b9490defc38baa9f4b0718e024e2870f44bd27a979f22",
    "official_concentrated_target_book.csv": "3fa0f6fa0aa41aa3ec830f476dae5e94882527a7f520531b80390bfbddb26a78",
    "target_generation_input_manifest.json": "7451166d8132c7e3fbd3eb75f7ecdd095e86e482b9202c2e0e0a2b1189ba6ff7",
    "daily_crisis_state.csv": "9516ea00fa9580aef9aa3d41c01d4b48f3ad1b14650dffdd500fa3ee5bf67a31",
}


def repo_relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError as exc:
        raise ValueError(f"static source must stay inside repository: {path}") from exc


def add_file(files: dict[str, Path], archive_path: str, source: Path) -> None:
    archive_path = Path(archive_path).as_posix().lstrip("/")
    if ".." in Path(archive_path).parts or not archive_path:
        raise ValueError(f"unsafe archive path: {archive_path}")
    if not source.is_file():
        raise FileNotFoundError(source)
    prior = files.get(archive_path)
    if prior is not None and prior.resolve() != source.resolve():
        raise ValueError(f"archive path collision: {archive_path}")
    files[archive_path] = source


def add_directory(files: dict[str, Path], directory: Path) -> None:
    if not directory.is_dir():
        raise FileNotFoundError(directory)
    for source in sorted(path for path in directory.rglob("*") if path.is_file()):
        add_file(files, repo_relative(source), source)


def export_source(raw: str, owner: Path) -> Path:
    source = resolve_portable_path(raw, owner=owner)
    if source.exists():
        return source
    parts = Path(raw.replace("\\", "/")).parts
    if parts and parts[0] == "run287_research_static":
        fallback = REPO_ROOT.joinpath(*parts[1:])
        if fallback.exists():
            return fallback.resolve()
    return source


def build(args: argparse.Namespace) -> dict[str, Any]:
    started = time.perf_counter()
    output = Path(args.output).resolve()
    status_output = Path(args.status_output).resolve()
    if output.exists():
        raise FileExistsError(f"archive already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    plan_path = Path(args.plan).resolve()
    plan = read_json(plan_path)
    files: dict[str, Path] = {}
    plan_records = plan.get("paths") or {}
    for label in STATIC_PLAN_LABELS:
        record = plan_records.get(label) or {}
        source = export_source(str(record.get("path") or ""), plan_path)
        expected = str(record.get("sha256") or "").lower()
        if not source.is_file() or sha256_file(source) != expected:
            raise ValueError(f"plan input mismatch: {label}")
        # Include the complete small anchor directory when its manifest owns
        # additional frozen files; otherwise include only the explicit file.
        if source.name == "manifest.json" and source.parent.name.startswith("run287_"):
            add_directory(files, source.parent)
        else:
            add_file(files, repo_relative(source), source)

    price_map_manifest = export_source(
        str((plan_records.get("price_map_manifest") or {}).get("path") or ""),
        plan_path,
    )
    price_map = read_json(price_map_manifest)
    csv_record = (price_map.get("outputs") or {}).get("selector_price_map") or {}
    price_csv = resolve_portable_path(str(csv_record.get("path") or ""), owner=price_map_manifest)
    if not price_csv.is_file() or sha256_file(price_csv) != str(csv_record.get("sha256") or ""):
        raise ValueError("selector price-map output mismatch")
    frame = pd.read_csv(price_csv, low_memory=False)
    if len(frame) != 363 or not {"path", "sha256"}.issubset(frame.columns):
        raise ValueError("selector price-map must contain the frozen 363 files")
    for index, row in frame.iterrows():
        source = resolve_portable_path(str(row.get("path") or ""), owner=price_csv)
        if not source.is_file() or sha256_file(source) != str(row.get("sha256") or ""):
            raise ValueError(f"selector price source mismatch: {index}")
        add_file(files, repo_relative(source), source)

    official_root = Path(args.official_artifact_root).resolve() / "outputs" / "alphaops_vnext"
    for name, expected in OFFICIAL_FILES.items():
        source = official_root / name
        if not source.is_file() or sha256_file(source) != expected:
            raise ValueError(f"official static input mismatch: {name}")
        add_file(
            files,
            f"run287_static_anchor/outputs/alphaops_vnext/{name}",
            source,
        )

    file_records = [
        {
            "path": archive_path,
            "bytes": int(source.stat().st_size),
            "sha256": sha256_file(source),
        }
        for archive_path, source in sorted(files.items())
    ]
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "status": READY_STATUS,
        "research_only": True,
        "file_count": len(file_records),
        "total_uncompressed_bytes": sum(item["bytes"] for item in file_records),
        "price_map_source_count": int(len(frame)),
        "files": file_records,
        "network_requests_executed": 0,
        "backtest_executed": False,
        "fullrun_executed": False,
        "orders_generated": False,
        "target_books_mutated": False,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
    }
    manifest_bytes = (
        json.dumps(manifest, indent=2, sort_keys=True, default=str) + "\n"
    ).encode("utf-8")
    with zipfile.ZipFile(
        output, mode="x", compression=zipfile.ZIP_DEFLATED, compresslevel=6
    ) as archive:
        for archive_path, source in sorted(files.items()):
            info = zipfile.ZipInfo(archive_path, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, source.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=6)
        info = zipfile.ZipInfo(MANIFEST_NAME, date_time=(1980, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o100644 << 16
        archive.writestr(info, manifest_bytes, compress_type=zipfile.ZIP_DEFLATED, compresslevel=6)
    payload = {
        **manifest,
        "archive": fingerprint(output),
        "elapsed_seconds": time.perf_counter() - started,
    }
    write_json(status_output, payload)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--plan", default="docs/run287_exact_packet_upstream_plan.json"
    )
    parser.add_argument(
        "--official-artifact-root",
        default=r"H:\codex\tmp_r1000_grossfloor_20260625\outputs\run_28725350727_official_broker_artifact",
    )
    parser.add_argument("--output", required=True)
    parser.add_argument("--status-output", required=True)
    return parser.parse_args()


def main() -> int:
    payload = build(parse_args())
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
