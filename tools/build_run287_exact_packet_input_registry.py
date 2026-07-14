#!/usr/bin/env python3
"""Build the hash-pinned, same-close input registry for Run287 packets.

The builder consumes one explicit source bundle.  It never discovers a
"latest" manifest, performs no network requests, and does not run selectors,
backtests, target-book generation, or trading code.  Missing or changed inputs
fail closed.  Successful registries are immutable by valuation date.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.run_run287_exact_packet_producer import (
    fingerprint,
    manifest_output,
    read_json,
    resolve_portable_path,
    sha256_file,
    write_json,
)


SCHEMA_VERSION = "run287-exact-packet-input-registry-builder-v1"
SOURCE_BUNDLE_SCHEMA = "run287-exact-packet-input-source-bundle-v1"
SOURCE_BUNDLE_STATUS = "READY_EXACT_PACKET_INPUT_SOURCE_PATHS_REVIEW_ONLY"
READY_STATUS = "READY_EXACT_PACKET_INPUTS_REVIEW_ONLY"
REUSED_STATUS = "READY_EXISTING_EXACT_PACKET_INPUTS_REVIEW_ONLY"
SKIPPED_STATUS = "SKIPPED_NO_EXACT_PACKET_INPUT_SOURCE_BUNDLE"
BLOCKED_STATUS = "BLOCKED_EXACT_PACKET_INPUT_REGISTRY"

DYNAMIC_OUTPUTS: dict[str, tuple[str, ...]] = {
    "decision_manifest": ("selection_context",),
    "score_stack_manifest": ("ticker_order_score_stack",),
    "crisis_manifest": ("current_crisis_state",),
    "price_manifest": ("provider_price_overlap.parquet",),
    "macro_manifest": ("market_component_audit",),
    "soxx_manifest": ("price_file",),
}

FALSE_IF_PRESENT = (
    "backtest_executed",
    "fullrun_executed",
    "live_trading_enabled",
    "orders_generated",
    "production_activation_allowed",
    "source_inputs_mutated",
    "target_books_mutated",
)


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def source_path(bundle_path: Path, record: Any) -> Path:
    raw = record.get("path") if isinstance(record, Mapping) else record
    return resolve_portable_path(str(raw or ""), owner=bundle_path)


def validate_manifest_outputs(
    label: str, path: Path, manifest: Mapping[str, Any], failures: list[str]
) -> dict[str, Any]:
    audit: dict[str, Any] = {}
    for key in DYNAMIC_OUTPUTS[label]:
        _, output = manifest_output(path, manifest, key)
        audit[key] = output
        if output.get("hash_matches") is not True:
            failures.append(f"manifest_output:{label}:{key}")
    return audit


def validate_price_map(
    path: Path, manifest: Mapping[str, Any], failures: list[str]
) -> dict[str, Any]:
    csv_path, output = manifest_output(path, manifest, "selector_price_map")
    audit: dict[str, Any] = {"selector_price_map": output}
    if output.get("hash_matches") is not True:
        failures.append("manifest_output:price_map_manifest:selector_price_map")
        return audit
    try:
        frame = pd.read_csv(csv_path, low_memory=False)
    except Exception as exc:
        failures.append(f"price_map_read:{type(exc).__name__}")
        return audit
    required = {"ticker", "path", "sha256"}
    missing = sorted(required.difference(frame.columns))
    if missing:
        failures.append(f"price_map_columns:{','.join(missing)}")
        return audit
    mismatches: list[str] = []
    for index, row in frame.iterrows():
        price_path = resolve_portable_path(str(row.get("path") or ""), owner=csv_path)
        expected = str(row.get("sha256") or "").lower()
        actual = sha256_file(price_path) if price_path.is_file() else ""
        if not expected or actual != expected:
            mismatches.append(f"{row.get('ticker')}:{index}")
    audit["price_source_count"] = int(len(frame))
    audit["price_source_mismatch_count"] = int(len(mismatches))
    if mismatches:
        failures.append(f"price_map_sources:{','.join(mismatches[:10])}")
    return audit


def base_payload(status: str, valuation_date: str, started: float) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "valuation_price_cutoff_date": valuation_date,
        "registry_ready": status in {READY_STATUS, REUSED_STATUS},
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


def finish(
    output_dir: Path,
    payload: dict[str, Any],
    *,
    failures: list[str] | None = None,
    sources: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    payload["contract_failures"] = list(failures or [])
    payload["source_inputs"] = dict(sources or {})
    write_json(output_dir / "status.json", payload)
    return payload


def immutable_publish(
    output_dir: Path,
    valuation_date: str,
    registry: Mapping[str, Any],
    failures: list[str],
) -> tuple[str, Path | None]:
    dated = output_dir / "by_date" / valuation_date / "registry.json"
    current = output_dir / "registry.json"
    serialized = json.dumps(registry, indent=2, sort_keys=True, default=str) + "\n"

    if dated.is_file():
        if dated.read_text(encoding="utf-8") != serialized:
            failures.append("immutable_date_collision")
            return BLOCKED_STATUS, None
        if current.is_file():
            current_payload = read_json(current)
            current_date = str(current_payload.get("valuation_price_cutoff_date") or "")
            if current_date > valuation_date:
                failures.append("current_registry_is_newer")
                return BLOCKED_STATUS, None
            if current_date == valuation_date and current.read_text(encoding="utf-8") != serialized:
                failures.append("current_registry_collision")
                return BLOCKED_STATUS, None
        write_json(current, registry)
        return REUSED_STATUS, dated

    if current.is_file():
        current_payload = read_json(current)
        current_date = str(current_payload.get("valuation_price_cutoff_date") or "")
        if current_date >= valuation_date:
            failures.append(
                "current_registry_collision" if current_date == valuation_date else "current_registry_is_newer"
            )
            return BLOCKED_STATUS, None

    dated.parent.mkdir(parents=True, exist_ok=True)
    dated.write_text(serialized, encoding="utf-8")
    current.write_text(serialized, encoding="utf-8")
    return READY_STATUS, dated


def build(args: argparse.Namespace) -> dict[str, Any]:
    started = time.perf_counter()
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    valuation_date = pd.Timestamp(args.valuation_date).date().isoformat()
    bundle_path = repo_path(args.source_bundle)
    contract_path = repo_path(args.producer_contract)
    sources: dict[str, Any] = {"producer_contract": fingerprint(contract_path)}

    if not bundle_path.is_file():
        payload = base_payload(SKIPPED_STATUS, valuation_date, started)
        payload["skip_reason"] = "source_bundle_missing"
        if args.allow_missing:
            return finish(output_dir, payload, sources=sources)
        payload["status"] = BLOCKED_STATUS
        return finish(
            output_dir, payload, failures=["source_bundle_missing"], sources=sources
        )

    failures: list[str] = []
    bundle = read_json(bundle_path)
    contract = read_json(contract_path)
    sources["source_bundle"] = fingerprint(bundle_path)
    if bundle.get("schema_version") != SOURCE_BUNDLE_SCHEMA:
        failures.append("source_bundle_schema")
    if bundle.get("status") != SOURCE_BUNDLE_STATUS:
        failures.append("source_bundle_status")
    if str(bundle.get("valuation_price_cutoff_date") or "") != valuation_date:
        failures.append("source_bundle_date")
    if contract.get("schema_version") != "run287-exact-packet-producer-contract-v1":
        failures.append("producer_contract_schema")

    records = bundle.get("inputs") or {}
    expected_labels = set(contract.get("required_dynamic_inputs") or {}) | set(
        contract.get("required_fixed_inputs") or {}
    )
    if set(records) != expected_labels:
        missing = sorted(expected_labels.difference(records))
        extra = sorted(set(records).difference(expected_labels))
        if missing:
            failures.append(f"source_bundle_missing_labels:{','.join(missing)}")
        if extra:
            failures.append(f"source_bundle_extra_labels:{','.join(extra)}")

    registry_inputs: dict[str, Any] = {}
    output_audit: dict[str, Any] = {}
    for label, requirement in (contract.get("required_dynamic_inputs") or {}).items():
        path = source_path(bundle_path, records.get(label) or {})
        audit = fingerprint(path)
        sources[label] = audit
        if not path.is_file():
            failures.append(f"input_missing:{label}")
            continue
        manifest = read_json(path)
        if manifest.get("status") != requirement.get("status"):
            failures.append(f"input_status:{label}")
        date_field = str(requirement.get("date_field") or "")
        if str(manifest.get(date_field) or "") != valuation_date:
            failures.append(f"input_date:{label}")
        for flag in FALSE_IF_PRESENT:
            if flag in manifest and manifest.get(flag) is not False:
                failures.append(f"unsafe_flag:{label}:{flag}")
        output_audit[label] = validate_manifest_outputs(label, path, manifest, failures)
        registry_inputs[label] = {
            "path": str(path.resolve()),
            "sha256": audit["sha256"],
        }

    for label, expected in (contract.get("required_fixed_inputs") or {}).items():
        path = source_path(bundle_path, records.get(label) or {})
        audit = fingerprint(path)
        sources[label] = audit
        if audit.get("sha256") != str(expected).lower():
            failures.append(f"fixed_input:{label}")
            continue
        registry_inputs[label] = {
            "path": str(path.resolve()),
            "sha256": audit["sha256"],
        }
        if label == "price_map_manifest":
            output_audit[label] = validate_price_map(path, read_json(path), failures)

    if failures:
        payload = base_payload(BLOCKED_STATUS, valuation_date, started)
        payload["output_audit"] = output_audit
        return finish(output_dir, payload, failures=failures, sources=sources)

    registry = {
        "schema_version": contract["input_registry_schema_version"],
        "status": READY_STATUS,
        "valuation_price_cutoff_date": valuation_date,
        "research_only": True,
        "network_requests_executed": 0,
        "backtest_executed": False,
        "fullrun_executed": False,
        "orders_generated": False,
        "target_books_mutated": False,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
        "producer_contract_sha256": sources["producer_contract"]["sha256"],
        "source_bundle_sha256": sources["source_bundle"]["sha256"],
        "inputs": registry_inputs,
    }
    status, dated = immutable_publish(
        output_dir, valuation_date, registry, failures
    )
    payload = base_payload(status, valuation_date, started)
    payload["output_audit"] = output_audit
    if dated is not None:
        payload["dated_registry"] = fingerprint(dated)
        payload["current_registry"] = fingerprint(output_dir / "registry.json")
    return finish(output_dir, payload, failures=failures, sources=sources)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-bundle", required=True)
    parser.add_argument("--valuation-date", required=True)
    parser.add_argument(
        "--producer-contract",
        default="docs/run287_exact_packet_producer_contract.json",
    )
    parser.add_argument(
        "--output-dir", default="outputs/run287_exact_packet_input_registry"
    )
    parser.add_argument("--allow-missing", action="store_true")
    return parser.parse_args()


def main() -> int:
    payload = build(parse_args())
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0 if payload["status"] != BLOCKED_STATUS else 2


if __name__ == "__main__":
    raise SystemExit(main())
