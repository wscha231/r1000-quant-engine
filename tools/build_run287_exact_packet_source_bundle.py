#!/usr/bin/env python3
"""Publish one immutable explicit-path source bundle for a Run287 packet.

The publisher performs no discovery and no upstream work.  Every one of the
twelve paths must be supplied explicitly.  Dynamic manifests are checked for
their exact valuation date, READY status, required hashed output, and research
safety flags.  Fixed inputs must match the hashes in the frozen packet
contract.  Missing inputs skip safely; invalid inputs block.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.build_run287_exact_packet_input_registry import (  # noqa: E402
    DYNAMIC_OUTPUTS,
    FALSE_IF_PRESENT,
    SOURCE_BUNDLE_SCHEMA,
    SOURCE_BUNDLE_STATUS,
)
from tools.run_run287_exact_packet_producer import (  # noqa: E402
    fingerprint,
    manifest_output,
    read_json,
    resolve_portable_path,
    write_json,
)


SCHEMA_VERSION = "run287-exact-packet-source-bundle-publisher-v1"
READY_STATUS = "READY_EXACT_PACKET_INPUT_SOURCE_BUNDLE_REVIEW_ONLY"
REUSED_STATUS = "READY_EXISTING_EXACT_PACKET_INPUT_SOURCE_BUNDLE_REVIEW_ONLY"
SKIPPED_STATUS = "SKIPPED_INCOMPLETE_EXACT_PACKET_UPSTREAM_INPUTS"
BLOCKED_STATUS = "BLOCKED_EXACT_PACKET_INPUT_SOURCE_BUNDLE"


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def valid_sha256(value: Any) -> bool:
    text = str(value or "").strip().lower()
    return len(text) == 64 and all(character in "0123456789abcdef" for character in text)


def parse_input_records(values: Sequence[str]) -> dict[str, str]:
    records: dict[str, str] = {}
    for value in values:
        label, separator, raw = str(value).partition("=")
        label = label.strip()
        raw = raw.strip()
        if not separator or not label or not raw:
            raise ValueError(f"--input must be LABEL=PATH: {value!r}")
        if label in records:
            raise ValueError(f"duplicate input label: {label}")
        records[label] = raw
    return records


def base_payload(status: str, valuation_date: str, started: float) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "valuation_price_cutoff_date": valuation_date,
        "source_bundle_ready": status in {READY_STATUS, REUSED_STATUS},
        "research_only": True,
        "network_requests_executed": 0,
        "backtest_executed": False,
        "fullrun_executed": False,
        "orders_generated": False,
        "target_books_mutated": False,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
        "elapsed_seconds": time.perf_counter() - started,
    }


def immutable_publish(
    output_dir: Path,
    valuation_date: str,
    bundle: Mapping[str, Any],
    failures: list[str],
) -> tuple[str, Path | None]:
    dated = output_dir / "by_date" / valuation_date / "source_bundle.json"
    current = output_dir / "source_bundle.json"
    serialized = json.dumps(bundle, indent=2, sort_keys=True, default=str) + "\n"

    if dated.is_file():
        if dated.read_text(encoding="utf-8") != serialized:
            failures.append("immutable_date_collision")
            return BLOCKED_STATUS, None
        if current.is_file():
            current_payload = read_json(current)
            current_date = str(current_payload.get("valuation_price_cutoff_date") or "")
            if current_date > valuation_date:
                failures.append("current_bundle_is_newer")
                return BLOCKED_STATUS, None
            if current_date == valuation_date and current.read_text(encoding="utf-8") != serialized:
                failures.append("current_bundle_collision")
                return BLOCKED_STATUS, None
        write_json(current, bundle)
        return REUSED_STATUS, dated

    if current.is_file():
        current_payload = read_json(current)
        current_date = str(current_payload.get("valuation_price_cutoff_date") or "")
        if current_date >= valuation_date:
            failures.append(
                "current_bundle_collision"
                if current_date == valuation_date
                else "current_bundle_is_newer"
            )
            return BLOCKED_STATUS, None

    dated.parent.mkdir(parents=True, exist_ok=True)
    dated.write_text(serialized, encoding="utf-8")
    current.write_text(serialized, encoding="utf-8")
    return READY_STATUS, dated


def build_from_records(
    *,
    valuation_date: str,
    input_records: Mapping[str, str | Path],
    producer_contract: str | Path,
    output_dir: str | Path,
) -> dict[str, Any]:
    started = time.perf_counter()
    valuation_date = pd.Timestamp(valuation_date).date().isoformat()
    contract_path = repo_path(producer_contract)
    destination = repo_path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    contract = read_json(contract_path)
    dynamic = contract.get("required_dynamic_inputs") or {}
    fixed = contract.get("required_fixed_inputs") or {}
    expected_labels = set(dynamic) | set(fixed)
    supplied_labels = set(input_records)
    failures: list[str] = []
    missing_labels = sorted(expected_labels.difference(supplied_labels))
    extra_labels = sorted(supplied_labels.difference(expected_labels))
    if missing_labels:
        failures.append(f"missing_labels:{','.join(missing_labels)}")
    if extra_labels:
        failures.append(f"extra_labels:{','.join(extra_labels)}")

    resolved: dict[str, Path] = {}
    audits: dict[str, Any] = {}
    missing_files: list[str] = []
    for label in sorted(expected_labels.intersection(supplied_labels)):
        path = resolve_portable_path(str(input_records[label]), owner=contract_path)
        if not path.is_absolute():
            path = repo_path(path)
        resolved[label] = path
        audits[label] = fingerprint(path)
        if not path.is_file():
            missing_files.append(label)

    if missing_labels or missing_files:
        payload = base_payload(SKIPPED_STATUS, valuation_date, started)
        payload["skip_reasons"] = failures + [
            f"missing_files:{','.join(sorted(missing_files))}"
        ]
        payload["input_audit"] = audits
        write_json(destination / "status.json", payload)
        return payload

    for label, requirement in dynamic.items():
        path = resolved[label]
        manifest = read_json(path)
        if manifest.get("status") != requirement.get("status"):
            failures.append(f"input_status:{label}")
        date_field = str(requirement.get("date_field") or "")
        if str(manifest.get(date_field) or "") != valuation_date:
            failures.append(f"input_date:{label}")
        for flag in FALSE_IF_PRESENT:
            if flag in manifest and manifest.get(flag) is not False:
                failures.append(f"unsafe_flag:{label}:{flag}")
        for key in DYNAMIC_OUTPUTS[label]:
            _, output = manifest_output(path, manifest, key)
            if output.get("hash_matches") is not True:
                failures.append(f"manifest_output:{label}:{key}")
        if label == "price_manifest":
            lifecycle = manifest.get("security_lifecycle") or {}
            lifecycle_source = (manifest.get("source_inputs") or {}).get(
                "security_lifecycle_events"
            ) or {}
            source_hash = str(lifecycle.get("source_sha256") or "")
            snapshot_hash = str(lifecycle.get("snapshot_hash") or "")
            recorded_hash = str(lifecycle_source.get("sha256") or "")
            if not valid_sha256(source_hash):
                failures.append("price_manifest_lifecycle_source_hash")
            if not valid_sha256(snapshot_hash):
                failures.append("price_manifest_lifecycle_snapshot_hash")
            if source_hash != recorded_hash:
                failures.append("price_manifest_lifecycle_source_identity")
            lifecycle_path_raw = str(lifecycle_source.get("path") or "")
            if not lifecycle_path_raw:
                failures.append("price_manifest_lifecycle_source_path")
            else:
                lifecycle_path = resolve_portable_path(lifecycle_path_raw, owner=path)
                if not lifecycle_path.is_absolute():
                    lifecycle_path = repo_path(lifecycle_path)
                if not lifecycle_path.is_file() or fingerprint(lifecycle_path).get("sha256") != source_hash:
                    failures.append("price_manifest_lifecycle_source_file")

    for label, expected_hash in fixed.items():
        if str(audits[label].get("sha256") or "").lower() != str(expected_hash).lower():
            failures.append(f"fixed_input:{label}")

    if failures:
        payload = base_payload(BLOCKED_STATUS, valuation_date, started)
        payload["contract_failures"] = failures
        payload["input_audit"] = audits
        write_json(destination / "status.json", payload)
        return payload

    bundle = {
        "schema_version": SOURCE_BUNDLE_SCHEMA,
        "status": SOURCE_BUNDLE_STATUS,
        "valuation_price_cutoff_date": valuation_date,
        "research_only": True,
        "network_requests_executed": 0,
        "backtest_executed": False,
        "fullrun_executed": False,
        "orders_generated": False,
        "target_books_mutated": False,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
        "inputs": {
            label: {
                "path": str(resolved[label].resolve()),
                "sha256": str(audits[label].get("sha256") or ""),
            }
            for label in sorted(expected_labels)
        },
    }
    status, dated = immutable_publish(destination, valuation_date, bundle, failures)
    payload = base_payload(status, valuation_date, started)
    payload["contract_failures"] = failures
    payload["input_audit"] = audits
    if dated is not None:
        payload["dated_source_bundle"] = fingerprint(dated)
        payload["current_source_bundle"] = fingerprint(destination / "source_bundle.json")
    write_json(destination / "status.json", payload)
    return payload


def build(args: argparse.Namespace) -> dict[str, Any]:
    return build_from_records(
        valuation_date=args.valuation_date,
        input_records=parse_input_records(args.input),
        producer_contract=args.producer_contract,
        output_dir=args.output_dir,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--valuation-date", required=True)
    parser.add_argument(
        "--input",
        action="append",
        default=[],
        metavar="LABEL=PATH",
        help="Repeat exactly twelve times; no glob or latest discovery is allowed.",
    )
    parser.add_argument(
        "--producer-contract",
        default="docs/run287_exact_packet_producer_contract.json",
    )
    parser.add_argument(
        "--output-dir", default="outputs/run287_exact_packet_input_sources"
    )
    return parser.parse_args()


def main() -> int:
    payload = build(parse_args())
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 2 if payload.get("status") == BLOCKED_STATUS else 0


if __name__ == "__main__":
    raise SystemExit(main())
