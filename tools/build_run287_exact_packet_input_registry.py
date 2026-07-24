#!/usr/bin/env python3
"""Build the hash-pinned, same-close input registry for Run287 packets.

The builder consumes one explicit source bundle.  It never discovers a
"latest" manifest, performs no network requests, and does not run selectors,
backtests, target-book generation, or trading code.  Missing or changed inputs
fail closed.  Successful registries are immutable by valuation date.
"""
from __future__ import annotations

import argparse
import hashlib
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
from tools.run287_code_identity import (
    code_identity_failures,
    current_code_identity,
)


SCHEMA_VERSION = "run287-exact-packet-input-registry-builder-v1"
SOURCE_BUNDLE_SCHEMA = "run287-exact-packet-input-source-bundle-v1"
SOURCE_BUNDLE_STATUS = "READY_EXACT_PACKET_INPUT_SOURCE_PATHS_REVIEW_ONLY"
UPSTREAM_SCHEMA = "run287-exact-packet-upstream-orchestrator-v3"
UPSTREAM_READY_STATUSES = {
    "READY_EXACT_PACKET_UPSTREAM_SOURCE_BUNDLE_REVIEW_ONLY",
    "READY_EXISTING_EXACT_PACKET_UPSTREAM_SOURCE_BUNDLE_REVIEW_ONLY",
}
READY_STATUS = "READY_EXACT_PACKET_INPUTS_REVIEW_ONLY"
REUSED_STATUS = "READY_EXISTING_EXACT_PACKET_INPUTS_REVIEW_ONLY"
SKIPPED_STATUS = "SKIPPED_NO_EXACT_PACKET_INPUT_SOURCE_BUNDLE"
BLOCKED_STATUS = "BLOCKED_EXACT_PACKET_INPUT_REGISTRY"

DYNAMIC_OUTPUTS: dict[str, tuple[str, ...]] = {
    "decision_manifest": ("selection_context",),
    "score_stack_manifest": ("ticker_order_score_stack",),
    "crisis_manifest": ("current_crisis_state",),
    "price_manifest": ("provider_price_overlap.parquet", "scored_latest.csv"),
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

LINEAGE_EDGES: tuple[tuple[str, str, str], ...] = (
    ("decision_manifest", "scored_latest_manifest", "price_manifest"),
    ("decision_manifest", "macro_manifest", "macro_manifest"),
    ("score_stack_manifest", "decision_frame_manifest", "decision_manifest"),
    ("crisis_manifest", "macro_manifest", "macro_manifest"),
    ("soxx_manifest", "crisis_manifest", "crisis_manifest"),
)
SCORER_PREFLIGHT_INPUT_LABELS = (
    "universe",
    "base_selection_context",
    "base_score_stack",
    "model_classification",
    "model_regression",
    "model_bundle",
    "model_meta",
    "scored_oos",
    "security_lifecycle_events",
)


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def source_path(bundle_path: Path, record: Any) -> Path:
    raw = record.get("path") if isinstance(record, Mapping) else record
    return resolve_portable_path(str(raw or ""), owner=bundle_path)


def source_record_audit(
    bundle_path: Path,
    record: Any,
    label: str,
    failures: list[str],
) -> tuple[Path, dict[str, Any]]:
    if not isinstance(record, Mapping):
        failures.append(f"source_bundle_record_schema:{label}")
        record = {}
    raw_path = str(record.get("path") or "")
    expected_sha = str(record.get("sha256") or "").lower()
    if not raw_path:
        failures.append(f"source_bundle_record_path:{label}")
    if (
        len(expected_sha) != 64
        or any(character not in "0123456789abcdef" for character in expected_sha)
    ):
        failures.append(f"source_bundle_record_sha256:{label}")
    path = source_path(bundle_path, record)
    audit = fingerprint(path)
    audit.update(
        expected_sha256=expected_sha,
        hash_matches=bool(expected_sha and audit.get("sha256") == expected_sha),
    )
    if audit["hash_matches"] is not True:
        failures.append(f"source_bundle_input_hash:{label}")
    return path, audit


def validate_lineage(
    manifests: Mapping[str, Mapping[str, Any]],
    sources: Mapping[str, Mapping[str, Any]],
    failures: list[str],
) -> dict[str, Any]:
    """Bind every downstream manifest to the exact upstream bundle member."""
    audit: dict[str, Any] = {}
    for owner_label, input_key, expected_label in LINEAGE_EDGES:
        record = (
            (manifests.get(owner_label) or {}).get("source_inputs") or {}
        ).get(input_key)
        actual_sha = (
            str(record.get("sha256") or "").strip().lower()
            if isinstance(record, Mapping)
            else ""
        )
        expected_sha = str(
            (sources.get(expected_label) or {}).get("sha256") or ""
        ).strip().lower()
        matches = bool(
            len(actual_sha) == 64
            and len(expected_sha) == 64
            and actual_sha == expected_sha
        )
        edge = f"{owner_label}:{input_key}:{expected_label}"
        audit[edge] = {
            "owner_manifest": owner_label,
            "source_input": input_key,
            "expected_bundle_input": expected_label,
            "actual_sha256": actual_sha,
            "expected_sha256": expected_sha,
            "matches": matches,
        }
        if not matches:
            failures.append(f"manifest_lineage:{edge}")
    return audit


def valid_sha256(value: Any) -> bool:
    digest = str(value or "").strip().lower()
    return bool(
        len(digest) == 64
        and all(character in "0123456789abcdef" for character in digest)
    )


def price_cache_contract_sha256(inputs: Mapping[str, Any]) -> str:
    semantic: list[dict[str, Any]] = []
    for ticker, raw_record in sorted(
        inputs.items(), key=lambda item: str(item[0])
    ):
        record = raw_record if isinstance(raw_record, Mapping) else {}
        try:
            byte_count = int(record.get("bytes") or 0)
        except (TypeError, ValueError):
            byte_count = -1
        semantic.append(
            {
                "ticker": str(ticker),
                "exists": record.get("exists") is True,
                "bytes": byte_count,
                "sha256": str(record.get("sha256") or ""),
            }
        )
    return hashlib.sha256(
        json.dumps(
            semantic, sort_keys=True, separators=(",", ":"), default=str
        ).encode("utf-8")
    ).hexdigest()


def price_cache_record_semantic(record: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize cache fingerprints across producers, including absent files."""

    try:
        byte_count = int(record.get("bytes") or 0)
    except (TypeError, ValueError):
        byte_count = -1
    return {
        "exists": record.get("exists") is True,
        "bytes": byte_count,
        "sha256": str(record.get("sha256") or "").strip().lower(),
    }


def ticker_set_sha256(values: Mapping[str, Any]) -> str:
    tickers = sorted({str(value).strip().upper() for value in values if str(value).strip()})
    payload = ("\n".join(tickers) + ("\n" if tickers else "")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def validate_scorer_preflight_binding(
    *,
    upstream: Mapping[str, Any],
    upstream_status_path: Path,
    price_manifest: Mapping[str, Any],
    sources: dict[str, Any],
    failures: list[str],
) -> dict[str, Any]:
    """Bind the price scorer to this attempt's preflight files and membership."""

    audit: dict[str, Any] = {"input_anchors": {}, "ticker_identity": {}}
    preflight = upstream.get("preflight") or {}
    upstream_inputs = preflight.get("input_audit") or {}
    price_inputs = price_manifest.get("source_inputs") or {}
    if not isinstance(upstream_inputs, Mapping):
        failures.append("upstream_preflight_input_audit_schema")
        upstream_inputs = {}
    if not isinstance(price_inputs, Mapping):
        failures.append("price_manifest_source_inputs_schema")
        price_inputs = {}

    for label in SCORER_PREFLIGHT_INPUT_LABELS:
        expected_record = upstream_inputs.get(label) or {}
        expected_sha = str(expected_record.get("sha256") or "").strip().lower()
        declared_expected_sha = str(
            expected_record.get("expected_sha256") or ""
        ).strip().lower()
        preflight_valid = bool(
            isinstance(expected_record, Mapping)
            and valid_sha256(expected_sha)
            and declared_expected_sha == expected_sha
            and expected_record.get("hash_matches") is True
        )
        raw_path = str(expected_record.get("path") or "")
        current_path = resolve_portable_path(raw_path, owner=upstream_status_path)
        current = fingerprint(current_path)
        current["expected_sha256"] = expected_sha
        current["hash_matches"] = bool(
            preflight_valid and current.get("sha256") == expected_sha
        )
        sources[f"upstream_preflight_input:{label}"] = current

        price_record = price_inputs.get(label) or {}
        price_sha = (
            str(price_record.get("sha256") or "").strip().lower()
            if isinstance(price_record, Mapping)
            else ""
        )
        price_expected_sha = (
            str(price_record.get("expected_sha256") or "").strip().lower()
            if isinstance(price_record, Mapping)
            else ""
        )
        price_valid = bool(
            isinstance(price_record, Mapping)
            and price_record.get("hash_matches") is True
            and price_sha == expected_sha
            and price_expected_sha == expected_sha
        )
        matches = bool(preflight_valid and current["hash_matches"] and price_valid)
        audit["input_anchors"][label] = {
            "upstream_preflight_sha256": expected_sha,
            "upstream_preflight_valid": preflight_valid,
            "current_sha256": current.get("sha256"),
            "current_hash_matches": current["hash_matches"],
            "price_manifest_sha256": price_sha,
            "price_manifest_expected_sha256": price_expected_sha,
            "price_manifest_hash_matches": (
                price_record.get("hash_matches")
                if isinstance(price_record, Mapping)
                else False
            ),
            "matches": matches,
        }
        if not preflight_valid:
            failures.append(f"upstream_preflight_input_invalid:{label}")
        if current["hash_matches"] is not True:
            failures.append(f"upstream_preflight_input_hash:{label}")
        if not price_valid:
            failures.append(f"price_manifest_preflight_input:{label}")

    upstream_identity = preflight.get("ticker_identity") or {}
    price_identity = price_manifest.get("ticker_identity") or {}
    if not isinstance(upstream_identity, Mapping):
        failures.append("upstream_preflight_ticker_identity_schema")
        upstream_identity = {}
    if not isinstance(price_identity, Mapping):
        failures.append("price_manifest_ticker_identity_schema")
        price_identity = {}
    identity_specs = (
        (
            "universe",
            "universe_count",
            "universe_ticker_set_sha256",
        ),
        (
            "pre_lifecycle_context",
            "pre_lifecycle_context_count",
            "pre_lifecycle_ticker_set_sha256",
        ),
        (
            "post_lifecycle_context",
            "post_lifecycle_context_count",
            "post_lifecycle_ticker_set_sha256",
        ),
    )
    for label, count_key, sha_key in identity_specs:
        price_record = price_identity.get(label) or {}
        try:
            upstream_count = int(upstream_identity.get(count_key))
        except (TypeError, ValueError):
            upstream_count = -1
        upstream_sha = str(upstream_identity.get(sha_key) or "").strip().lower()
        try:
            price_expected_count = int(price_record.get("expected_count"))
            price_actual_count = int(price_record.get("actual_count"))
        except (AttributeError, TypeError, ValueError):
            price_expected_count = -1
            price_actual_count = -1
        matches = bool(
            isinstance(price_record, Mapping)
            and upstream_count > 0
            and valid_sha256(upstream_sha)
            and price_record.get("matches") is True
            and price_expected_count == upstream_count
            and price_actual_count == upstream_count
            and str(
                price_record.get("expected_ticker_set_sha256") or ""
            ).strip().lower()
            == upstream_sha
            and str(
                price_record.get("actual_ticker_set_sha256") or ""
            ).strip().lower()
            == upstream_sha
        )
        audit["ticker_identity"][label] = {
            "upstream_count": upstream_count,
            "upstream_ticker_set_sha256": upstream_sha,
            "price_manifest": dict(price_record)
            if isinstance(price_record, Mapping)
            else {},
            "matches": matches,
        }
        if not matches:
            failures.append(f"price_manifest_ticker_identity:{label}")

    upstream_cache = preflight.get("price_cache_input_audit") or {}
    price_cache = price_manifest.get("price_cache_inputs") or {}
    upstream_cache_inputs = upstream_cache.get("inputs") or {}
    price_cache_inputs = price_cache.get("inputs") or {}
    cache_schema_valid = bool(
        isinstance(upstream_cache, Mapping)
        and isinstance(price_cache, Mapping)
        and isinstance(upstream_cache_inputs, Mapping)
        and isinstance(price_cache_inputs, Mapping)
        and upstream_cache.get("schema_version")
        == "run287-price-cache-input-audit-v1"
        and price_cache.get("schema_version")
        == "run287-price-cache-input-audit-v1"
    )
    upstream_contract_sha = str(
        upstream_cache.get("contract_sha256") or ""
    ).strip().lower()
    price_contract_sha = str(
        price_cache.get("contract_sha256") or ""
    ).strip().lower()
    upstream_contract_valid = bool(
        cache_schema_valid
        and valid_sha256(upstream_contract_sha)
        and upstream_contract_sha
        == price_cache_contract_sha256(upstream_cache_inputs)
    )
    price_contract_valid = bool(
        cache_schema_valid
        and valid_sha256(price_contract_sha)
        and price_contract_sha == price_cache_contract_sha256(price_cache_inputs)
    )
    cache_records_structurally_valid = bool(
        cache_schema_valid
        and all(
            isinstance(record, Mapping)
            for record in upstream_cache_inputs.values()
        )
        and all(
            isinstance(record, Mapping)
            for record in price_cache_inputs.values()
        )
    )
    cache_records_match = bool(
        cache_schema_valid
        and cache_records_structurally_valid
        and set(upstream_cache_inputs) == set(price_cache_inputs)
    )
    cache_input_audit: dict[str, Any] = {}
    if cache_records_match:
        for ticker in sorted(upstream_cache_inputs):
            expected_record = upstream_cache_inputs.get(ticker) or {}
            price_record = price_cache_inputs.get(ticker) or {}
            current_path = resolve_portable_path(
                str(expected_record.get("path") or ""),
                owner=upstream_status_path,
            )
            current = fingerprint(current_path)
            fields_match = (
                price_cache_record_semantic(price_record)
                == price_cache_record_semantic(expected_record)
            )
            current_matches = (
                price_cache_record_semantic(current)
                == price_cache_record_semantic(expected_record)
            )
            sources[f"upstream_price_cache_input:{ticker}"] = current
            cache_input_audit[str(ticker)] = {
                "preflight_price_manifest_match": fields_match,
                "current_preflight_match": current_matches,
            }
            if not fields_match:
                failures.append(f"price_manifest_price_cache_input:{ticker}")
            if not current_matches:
                failures.append(f"upstream_price_cache_input_hash:{ticker}")
    try:
        upstream_cache_count = int(upstream_cache.get("ticker_count"))
        price_cache_count = int(price_cache.get("ticker_count"))
    except (AttributeError, TypeError, ValueError):
        upstream_cache_count = -1
        price_cache_count = -1
    upstream_cache_ticker_sha = str(
        upstream_cache.get("ticker_set_sha256") or ""
    ).strip().lower()
    price_cache_ticker_sha = str(
        price_cache.get("ticker_set_sha256") or ""
    ).strip().lower()
    computed_cache_ticker_sha = (
        ticker_set_sha256(upstream_cache_inputs)
        if isinstance(upstream_cache_inputs, Mapping)
        else ""
    )
    cache_matches = bool(
        upstream_contract_valid
        and price_contract_valid
        and upstream_contract_sha == price_contract_sha
        and cache_records_match
        and upstream_cache_count == price_cache_count
        and upstream_cache_count == len(upstream_cache_inputs)
        and valid_sha256(upstream_cache_ticker_sha)
        and upstream_cache_ticker_sha == price_cache_ticker_sha
        and upstream_cache_ticker_sha == computed_cache_ticker_sha
        and not any(
            not record["preflight_price_manifest_match"]
            or not record["current_preflight_match"]
            for record in cache_input_audit.values()
        )
    )
    audit["price_cache_inputs"] = {
        "upstream_contract_sha256": upstream_contract_sha,
        "price_manifest_contract_sha256": price_contract_sha,
        "upstream_contract_valid": upstream_contract_valid,
        "price_manifest_contract_valid": price_contract_valid,
        "ticker_count": len(upstream_cache_inputs)
        if isinstance(upstream_cache_inputs, Mapping)
        else 0,
        "records_match": cache_records_match,
        "inputs": cache_input_audit,
        "matches": cache_matches,
    }
    if not cache_schema_valid:
        failures.append("price_cache_input_audit_schema")
    if not upstream_contract_valid:
        failures.append("upstream_price_cache_contract")
    if not price_contract_valid:
        failures.append("price_manifest_price_cache_contract")
    if not cache_records_match:
        failures.append("price_cache_input_ticker_set")
    if not cache_matches:
        failures.append("price_cache_preflight_binding")
    return audit


def changed_input_failures(sources: Mapping[str, Mapping[str, Any]]) -> list[str]:
    """Rehash every path-bearing source immediately before publication."""
    failures: list[str] = []
    for label, prior in sources.items():
        raw_path = str((prior or {}).get("path") or "")
        if not raw_path:
            continue
        current = fingerprint(Path(raw_path))
        if any(
            current.get(field) != prior.get(field)
            for field in ("exists", "bytes", "sha256")
        ):
            failures.append(f"input_changed_before_registry_publish:{label}")
    return failures


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

    write_json(dated, registry)
    write_json(current, registry)
    return READY_STATUS, dated


def build(args: argparse.Namespace) -> dict[str, Any]:
    started = time.perf_counter()
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "status.json").unlink(missing_ok=True)
    valuation_date = pd.Timestamp(args.valuation_date).date().isoformat()
    bundle_path = repo_path(args.source_bundle)
    upstream_status_path = repo_path(args.upstream_status)
    contract_path = repo_path(args.producer_contract)
    sources: dict[str, Any] = {
        "producer_contract": fingerprint(contract_path),
        "upstream_status": fingerprint(upstream_status_path),
    }

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
    try:
        bundle = read_json(bundle_path)
    except Exception as exc:
        failures.append(f"source_bundle_read:{type(exc).__name__}")
        bundle = {}
    try:
        contract = read_json(contract_path)
    except Exception as exc:
        failures.append(f"producer_contract_read:{type(exc).__name__}")
        contract = {}
    try:
        current_identity = current_code_identity()
    except Exception as exc:
        current_identity = {}
        failures.append(f"code_identity_current:{type(exc).__name__}")
    sources["source_bundle"] = fingerprint(bundle_path)
    if not upstream_status_path.is_file():
        failures.append("upstream_status_missing")
        upstream = {}
    else:
        try:
            upstream = read_json(upstream_status_path)
        except Exception as exc:
            failures.append(f"upstream_status_read:{type(exc).__name__}")
            upstream = {}
    if upstream.get("schema_version") != UPSTREAM_SCHEMA:
        failures.append("upstream_status_schema")
    if (
        upstream.get("status") not in UPSTREAM_READY_STATUSES
        or upstream.get("upstream_ready") is not True
    ):
        failures.append("upstream_status_not_ready")
    if str(upstream.get("valuation_price_cutoff_date") or "") != valuation_date:
        failures.append("upstream_status_date")
    upstream_bundle = upstream.get("source_bundle") or {}
    upstream_bundle_path = resolve_portable_path(
        str(upstream_bundle.get("path") or ""),
        owner=upstream_status_path,
    )
    upstream_bundle_audit = fingerprint(upstream_bundle_path)
    sources["upstream_source_bundle"] = upstream_bundle_audit
    try:
        same_bundle_path = upstream_bundle_path.resolve() == bundle_path.resolve()
    except OSError:
        same_bundle_path = False
    if (
        not same_bundle_path
        or upstream_bundle_audit.get("sha256")
        != str(upstream_bundle.get("sha256") or "").lower()
        or upstream_bundle_audit.get("sha256")
        != sources["source_bundle"].get("sha256")
    ):
        failures.append("upstream_source_bundle_mismatch")
    if bundle.get("schema_version") != SOURCE_BUNDLE_SCHEMA:
        failures.append("source_bundle_schema")
    if bundle.get("status") != SOURCE_BUNDLE_STATUS:
        failures.append("source_bundle_status")
    if str(bundle.get("valuation_price_cutoff_date") or "") != valuation_date:
        failures.append("source_bundle_date")
    if contract.get("schema_version") != "run287-exact-packet-producer-contract-v1":
        failures.append("producer_contract_schema")
    bundle_code_identity = bundle.get("code_identity")
    upstream_preflight = upstream.get("preflight") or {}
    if not isinstance(upstream_preflight, Mapping):
        failures.append("upstream_preflight_schema")
        upstream_preflight = {}
    upstream_code_identity = upstream_preflight.get("code_identity")
    code_identity_audit = {
        "current": current_identity,
        "source_bundle": bundle_code_identity,
        "upstream": upstream_code_identity,
    }
    failures.extend(
        code_identity_failures(
            bundle_code_identity,
            current=current_identity,
            prefix="source_bundle_code_identity",
        )
    )
    failures.extend(
        code_identity_failures(
            upstream_code_identity,
            current=current_identity,
            prefix="upstream_code_identity",
        )
    )
    if bundle_code_identity != upstream_code_identity:
        failures.append("upstream_source_bundle_code_identity_mismatch")

    records = bundle.get("inputs") or {}
    if not isinstance(records, Mapping):
        failures.append("source_bundle_inputs_schema")
        records = {}
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
    dynamic_manifests: dict[str, dict[str, Any]] = {}
    output_audit: dict[str, Any] = {}
    for label, requirement in (contract.get("required_dynamic_inputs") or {}).items():
        path, audit = source_record_audit(
            bundle_path,
            records.get(label),
            label,
            failures,
        )
        sources[label] = audit
        if not path.is_file():
            failures.append(f"input_missing:{label}")
            continue
        try:
            manifest = read_json(path)
        except Exception as exc:
            failures.append(f"input_read:{label}:{type(exc).__name__}")
            continue
        dynamic_manifests[label] = manifest
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
        path, audit = source_record_audit(
            bundle_path,
            records.get(label),
            label,
            failures,
        )
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

    output_audit["manifest_lineage"] = validate_lineage(
        dynamic_manifests, sources, failures
    )
    output_audit["scorer_preflight_binding"] = (
        validate_scorer_preflight_binding(
            upstream=upstream,
            upstream_status_path=upstream_status_path,
            price_manifest=dynamic_manifests.get("price_manifest") or {},
            sources=sources,
            failures=failures,
        )
    )
    output_audit["code_identity"] = code_identity_audit
    failures.extend(changed_input_failures(sources))
    try:
        failures.extend(
            code_identity_failures(
                bundle_code_identity,
                current=current_code_identity(),
                prefix="code_identity_before_registry_publish",
            )
        )
    except Exception as exc:
        failures.append(
            f"code_identity_before_registry_publish:{type(exc).__name__}"
        )
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
        "code_identity": bundle_code_identity,
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
    parser.add_argument("--upstream-status", required=True)
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
