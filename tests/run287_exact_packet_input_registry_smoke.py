#!/usr/bin/env python3
"""Smoke tests for the Run287 exact packet input-registry builder."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.build_run287_exact_packet_input_registry import (  # noqa: E402
    BLOCKED_STATUS,
    READY_STATUS,
    REUSED_STATUS,
    SCORER_PREFLIGHT_INPUT_LABELS,
    SKIPPED_STATUS,
    build,
    price_cache_contract_sha256,
    validate_scorer_preflight_binding,
)
from tools.run287_code_identity import current_code_identity, identity_sha256


DATE = "2026-07-13"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def record(path: Path) -> dict[str, str]:
    return {"path": str(path), "sha256": sha(path)}


def audited_record(path: Path) -> dict[str, object]:
    digest = sha(path)
    return {
        "path": str(path),
        "exists": True,
        "bytes": path.stat().st_size,
        "sha256": digest,
        "expected_sha256": digest,
        "hash_matches": True,
    }


def fixture(root: Path) -> tuple[argparse.Namespace, dict[str, Path]]:
    inputs = root / "inputs"
    inputs.mkdir(parents=True)
    dynamic_specs = {
        "decision_manifest": (
            "READY_COMPLETE_CURRENT_DECISION_FRAME",
            "valuation_price_cutoff_date",
            "selection_context",
        ),
        "score_stack_manifest": (
            "READY_CURRENT_DECISION_SCORE_STACK_ELIGIBILITY_AUDIT_NONRANKING",
            "valuation_price_cutoff_date",
            "ticker_order_score_stack",
        ),
        "crisis_manifest": (
            "READY_CURRENT_CRISIS_STATE_NONSELECTING",
            "valuation_price_cutoff_date",
            "current_crisis_state",
        ),
        "price_manifest": (
            "READY_RESEARCH_SCORED_LATEST",
            "session_date",
            "provider_price_overlap.parquet",
        ),
        "macro_manifest": (
            "READY_CONSERVATIVE_MACRO_SIDECAR",
            "valuation_close_date",
            "market_component_audit",
        ),
        "soxx_manifest": (
            "READY_SELECTOR_BENCHMARK_PRICE_NONSELECTING",
            "valuation_price_cutoff_date",
            "price_file",
        ),
    }
    paths: dict[str, Path] = {}
    dynamic_contract: dict[str, dict[str, str]] = {}
    for label, (status, date_field, output_key) in dynamic_specs.items():
        output = inputs / f"{label}.csv"
        output.write_text(f"ticker,value\nAAA,{label}\n", encoding="utf-8")
        outputs = {output_key: record(output)}
        if label == "price_manifest":
            scored_latest = inputs / "scored_latest.csv"
            scored_latest.write_text(
                "ticker,score_total\nAAA,1.0\n",
                encoding="utf-8",
            )
            outputs["scored_latest.csv"] = record(scored_latest)
            paths[f"{label}:scored_latest"] = scored_latest
        manifest = inputs / f"{label}.json"
        write_json(
            manifest,
            {
                "status": status,
                date_field: DATE,
                "research_only": True,
                "source_inputs_mutated": False,
                "target_books_mutated": False,
                "backtest_executed": False,
                "fullrun_executed": False,
                "live_trading_enabled": False,
                "outputs": outputs,
            },
        )
        paths[label] = manifest
        paths[f"{label}:output"] = output
        dynamic_contract[label] = {"status": status, "date_field": date_field}

    preflight_inputs: dict[str, dict[str, object]] = {}
    for label in SCORER_PREFLIGHT_INPUT_LABELS:
        anchor = inputs / f"preflight_{label}"
        anchor.write_text(
            "ticker\nAAA\n"
            if label in {"universe", "base_selection_context"}
            else f"{label}:frozen\n",
            encoding="utf-8",
        )
        paths[f"preflight:{label}"] = anchor
        preflight_inputs[label] = audited_record(anchor)
    ticker_set_sha = hashlib.sha256(b"AAA\n").hexdigest()
    ticker_identity = {
        "universe_count": 1,
        "universe_ticker_set_sha256": ticker_set_sha,
        "pre_lifecycle_context_count": 1,
        "pre_lifecycle_ticker_set_sha256": ticker_set_sha,
        "post_lifecycle_context_count": 1,
        "post_lifecycle_ticker_set_sha256": ticker_set_sha,
    }
    price_cache_file = inputs / "preflight_price_AAA.parquet"
    price_cache_file.write_bytes(b"historical-price-cache")
    paths["preflight:price_cache:AAA"] = price_cache_file
    price_cache_inputs = {"AAA": audited_record(price_cache_file)}
    price_cache_input_audit = {
        "schema_version": "run287-price-cache-input-audit-v1",
        "ticker_count": 1,
        "ticker_set_sha256": ticker_set_sha,
        "contract_sha256": price_cache_contract_sha256(price_cache_inputs),
        "inputs": price_cache_inputs,
    }
    price_manifest = json.loads(
        paths["price_manifest"].read_text(encoding="utf-8")
    )
    price_manifest["schema_version"] = "run287-scored-latest-refresh-v4"
    price_manifest["source_inputs"] = {
        label: dict(value) for label, value in preflight_inputs.items()
    }
    price_manifest["ticker_identity"] = {
        "universe": {
            "expected_count": 1,
            "actual_count": 1,
            "unique_count": 1,
            "expected_ticker_set_sha256": ticker_set_sha,
            "actual_ticker_set_sha256": ticker_set_sha,
            "matches": True,
        },
        "pre_lifecycle_context": {
            "expected_count": 1,
            "actual_count": 1,
            "unique_count": 1,
            "expected_ticker_set_sha256": ticker_set_sha,
            "actual_ticker_set_sha256": ticker_set_sha,
            "matches": True,
        },
        "post_lifecycle_context": {
            "expected_count": 1,
            "actual_count": 1,
            "unique_count": 1,
            "expected_ticker_set_sha256": ticker_set_sha,
            "actual_ticker_set_sha256": ticker_set_sha,
            "matches": True,
        },
    }
    price_manifest["price_cache_inputs"] = price_cache_input_audit
    write_json(paths["price_manifest"], price_manifest)

    lineage = (
        ("decision_manifest", "scored_latest_manifest", "price_manifest"),
        ("decision_manifest", "macro_manifest", "macro_manifest"),
        ("crisis_manifest", "macro_manifest", "macro_manifest"),
        ("score_stack_manifest", "decision_frame_manifest", "decision_manifest"),
        ("soxx_manifest", "crisis_manifest", "crisis_manifest"),
    )
    for owner, input_key, upstream in lineage:
        manifest = json.loads(paths[owner].read_text(encoding="utf-8"))
        manifest.setdefault("source_inputs", {})[input_key] = record(paths[upstream])
        write_json(paths[owner], manifest)

    price_source = inputs / "aaa.parquet"
    price_source.write_bytes(b"test-price")
    price_map_csv = inputs / "selector_price_map.csv"
    pd.DataFrame(
        [{"ticker": "AAA", "path": str(price_source), "sha256": sha(price_source)}]
    ).to_csv(price_map_csv, index=False)
    price_map_manifest = inputs / "price_map_manifest.json"
    write_json(
        price_map_manifest,
        {
            "status": "READY_CURRENT_SELECTOR_PRICE_MAP_NONSELECTING",
            "outputs": {"selector_price_map": record(price_map_csv)},
        },
    )
    paths["price_map_manifest"] = price_map_manifest

    fixed_labels = (
        "selector_contract_manifest",
        "pinned_import_manifest",
        "target_generation_manifest",
        "main_prior_book",
        "concentrated_prior_book",
    )
    for label in fixed_labels:
        path = inputs / label
        path.write_text(label + "\n", encoding="utf-8")
        paths[label] = path

    fixed_contract = {
        label: sha(paths[label]) for label in (*fixed_labels, "price_map_manifest")
    }
    contract = root / "producer_contract.json"
    write_json(
        contract,
        {
            "schema_version": "run287-exact-packet-producer-contract-v1",
            "input_registry_schema_version": "run287-exact-packet-input-registry-v1",
            "required_dynamic_inputs": dynamic_contract,
            "required_fixed_inputs": fixed_contract,
        },
    )
    paths["producer_contract"] = contract

    bundle = root / "source_bundle.json"
    code_identity = current_code_identity()
    write_json(
        bundle,
        {
            "schema_version": "run287-exact-packet-input-source-bundle-v1",
            "status": "READY_EXACT_PACKET_INPUT_SOURCE_PATHS_REVIEW_ONLY",
            "valuation_price_cutoff_date": DATE,
            "code_identity": code_identity,
            "inputs": {
                label: record(paths[label])
                for label in (*dynamic_specs, *fixed_labels, "price_map_manifest")
            },
        },
    )
    paths["source_bundle"] = bundle
    upstream_status = root / "upstream_status.json"
    write_json(
        upstream_status,
        {
            "schema_version": "run287-exact-packet-upstream-orchestrator-v3",
            "status": "READY_EXACT_PACKET_UPSTREAM_SOURCE_BUNDLE_REVIEW_ONLY",
            "valuation_price_cutoff_date": DATE,
            "upstream_ready": True,
            "source_bundle": record(bundle),
            "preflight": {
                "code_identity": code_identity,
                "input_audit": preflight_inputs,
                "ticker_identity": ticker_identity,
                "price_cache_input_audit": price_cache_input_audit,
            },
        },
    )
    paths["upstream_status"] = upstream_status
    args = argparse.Namespace(
        source_bundle=str(bundle),
        upstream_status=str(upstream_status),
        valuation_date=DATE,
        producer_contract=str(contract),
        output_dir=str(root / "registry"),
        allow_missing=False,
    )
    return args, paths


def run() -> None:
    with tempfile.TemporaryDirectory() as temp:
        args, paths = fixture(Path(temp))
        upstream = json.loads(
            paths["upstream_status"].read_text(encoding="utf-8")
        )
        price_manifest = json.loads(
            paths["price_manifest"].read_text(encoding="utf-8")
        )
        missing_path = Path(temp) / "inputs" / "not-yet-downloaded.parquet"
        missing_record = {
            "path": str(missing_path),
            "exists": False,
            "bytes": 0,
            "sha256": None,
        }
        missing_inputs = {"AAA": missing_record}
        missing_audit = {
            "schema_version": "run287-price-cache-input-audit-v1",
            "ticker_count": 1,
            "ticker_set_sha256": hashlib.sha256(b"AAA\n").hexdigest(),
            "contract_sha256": price_cache_contract_sha256(missing_inputs),
            "inputs": missing_inputs,
        }
        upstream["preflight"]["price_cache_input_audit"] = missing_audit
        price_manifest["price_cache_inputs"] = missing_audit
        failures: list[str] = []
        audit = validate_scorer_preflight_binding(
            upstream=upstream,
            upstream_status_path=paths["upstream_status"],
            price_manifest=price_manifest,
            sources={},
            failures=failures,
        )
        assert failures == [], failures
        assert audit["price_cache_inputs"]["matches"] is True

    with tempfile.TemporaryDirectory() as temp:
        args, paths = fixture(Path(temp))
        ready = build(args)
        assert ready["status"] == READY_STATUS, ready
        assert ready["registry_ready"] is True
        assert ready["network_requests_executed"] == 0
        registry = Path(args.output_dir) / "registry.json"
        dated = Path(args.output_dir) / "by_date" / DATE / "registry.json"
        assert registry.read_bytes() == dated.read_bytes()
        payload = json.loads(registry.read_text(encoding="utf-8"))
        assert set(payload["inputs"]) == {
            "decision_manifest",
            "score_stack_manifest",
            "crisis_manifest",
            "price_manifest",
            "macro_manifest",
            "soxx_manifest",
            "selector_contract_manifest",
            "pinned_import_manifest",
            "target_generation_manifest",
            "main_prior_book",
            "concentrated_prior_book",
            "price_map_manifest",
        }

        reused = build(args)
        assert reused["status"] == REUSED_STATUS, reused
        assert registry.read_bytes() == dated.read_bytes()

        decision_output = paths["decision_manifest:output"]
        decision_output.write_text("ticker,value\nAAA,changed\n", encoding="utf-8")
        decision = json.loads(paths["decision_manifest"].read_text(encoding="utf-8"))
        decision["outputs"]["selection_context"] = record(decision_output)
        write_json(paths["decision_manifest"], decision)
        collision = build(args)
        assert collision["status"] == BLOCKED_STATUS, collision
        assert (
            "source_bundle_input_hash:decision_manifest"
            in collision["contract_failures"]
        )
        bundle = json.loads(paths["source_bundle"].read_text(encoding="utf-8"))
        bundle["inputs"]["decision_manifest"] = record(paths["decision_manifest"])
        score_stack = json.loads(
            paths["score_stack_manifest"].read_text(encoding="utf-8")
        )
        score_stack["source_inputs"]["decision_frame_manifest"] = record(
            paths["decision_manifest"]
        )
        write_json(paths["score_stack_manifest"], score_stack)
        bundle["inputs"]["score_stack_manifest"] = record(
            paths["score_stack_manifest"]
        )
        write_json(paths["source_bundle"], bundle)
        upstream = json.loads(paths["upstream_status"].read_text(encoding="utf-8"))
        upstream["source_bundle"] = record(paths["source_bundle"])
        write_json(paths["upstream_status"], upstream)
        collision = build(args)
        assert collision["status"] == BLOCKED_STATUS, collision
        assert "immutable_date_collision" in collision["contract_failures"]

    with tempfile.TemporaryDirectory() as temp:
        args, paths = fixture(Path(temp))
        upstream = json.loads(
            paths["upstream_status"].read_text(encoding="utf-8")
        )
        changed = json.loads(
            json.dumps(upstream["preflight"]["code_identity"])
        )
        changed["source_commit_sha"] = "f" * 40
        changed["source_tree_sha"] = "e" * 40
        changed["identity_sha256"] = identity_sha256(changed)
        upstream["preflight"]["code_identity"] = changed
        write_json(paths["upstream_status"], upstream)
        blocked = build(args)
        assert blocked["status"] == BLOCKED_STATUS, blocked
        assert (
            "upstream_code_identity:current_mismatch"
            in blocked["contract_failures"]
        )
        assert (
            "upstream_source_bundle_code_identity_mismatch"
            in blocked["contract_failures"]
        )

    with tempfile.TemporaryDirectory() as temp:
        args, paths = fixture(Path(temp))
        decision_output = paths["decision_manifest:output"]
        decision_output.write_text("ticker,value\nAAA,changed\n", encoding="utf-8")
        decision = json.loads(paths["decision_manifest"].read_text(encoding="utf-8"))
        decision["outputs"]["selection_context"] = record(decision_output)
        write_json(paths["decision_manifest"], decision)
        blocked = build(args)
        assert blocked["status"] == BLOCKED_STATUS, blocked
        assert (
            "source_bundle_input_hash:decision_manifest"
            in blocked["contract_failures"]
        )
        assert not (Path(args.output_dir) / "registry.json").exists()

    with tempfile.TemporaryDirectory() as temp:
        args, paths = fixture(Path(temp))
        upstream = json.loads(paths["upstream_status"].read_text(encoding="utf-8"))
        upstream["status"] = "BLOCKED_EXACT_PACKET_UPSTREAM"
        upstream["upstream_ready"] = False
        write_json(paths["upstream_status"], upstream)
        blocked = build(args)
        assert blocked["status"] == BLOCKED_STATUS, blocked
        assert "upstream_status_not_ready" in blocked["contract_failures"]
        assert not (Path(args.output_dir) / "registry.json").exists()

    with tempfile.TemporaryDirectory() as temp:
        args, paths = fixture(Path(temp))
        # Same row count and byte length, different membership after preflight.
        paths["preflight:base_selection_context"].write_text(
            "ticker\nBBB\n", encoding="utf-8"
        )
        blocked = build(args)
        assert blocked["status"] == BLOCKED_STATUS, blocked
        assert (
            "upstream_preflight_input_hash:base_selection_context"
            in blocked["contract_failures"]
        )
        assert not (Path(args.output_dir) / "registry.json").exists()

    with tempfile.TemporaryDirectory() as temp:
        args, paths = fixture(Path(temp))
        paths["preflight:model_meta"].write_text(
            "model_meta:changed\n", encoding="utf-8"
        )
        blocked = build(args)
        assert blocked["status"] == BLOCKED_STATUS, blocked
        assert (
            "upstream_preflight_input_hash:model_meta"
            in blocked["contract_failures"]
        )
        assert not (Path(args.output_dir) / "registry.json").exists()

    with tempfile.TemporaryDirectory() as temp:
        args, paths = fixture(Path(temp))
        paths["preflight:price_cache:AAA"].write_bytes(
            b"historical-price-cache-mutated"
        )
        blocked = build(args)
        assert blocked["status"] == BLOCKED_STATUS, blocked
        assert (
            "upstream_price_cache_input_hash:AAA"
            in blocked["contract_failures"]
        )
        assert not (Path(args.output_dir) / "registry.json").exists()

    with tempfile.TemporaryDirectory() as temp:
        args, paths = fixture(Path(temp))
        price_manifest = json.loads(
            paths["price_manifest"].read_text(encoding="utf-8")
        )
        substituted_sha = hashlib.sha256(b"BBB\n").hexdigest()
        forged_base = price_manifest["source_inputs"][
            "base_selection_context"
        ]
        forged_base["sha256"] = substituted_sha
        forged_base["expected_sha256"] = substituted_sha
        forged_base["hash_matches"] = True
        ticker_identity = price_manifest["ticker_identity"][
            "pre_lifecycle_context"
        ]
        ticker_identity["expected_ticker_set_sha256"] = substituted_sha
        ticker_identity["actual_ticker_set_sha256"] = substituted_sha
        ticker_identity["matches"] = True
        write_json(paths["price_manifest"], price_manifest)
        bundle = json.loads(paths["source_bundle"].read_text(encoding="utf-8"))
        bundle["inputs"]["price_manifest"] = record(paths["price_manifest"])
        write_json(paths["source_bundle"], bundle)
        upstream = json.loads(
            paths["upstream_status"].read_text(encoding="utf-8")
        )
        upstream["source_bundle"] = record(paths["source_bundle"])
        write_json(paths["upstream_status"], upstream)
        blocked = build(args)
        assert blocked["status"] == BLOCKED_STATUS, blocked
        assert (
            "price_manifest_preflight_input:base_selection_context"
            in blocked["contract_failures"]
        )
        assert (
            "price_manifest_ticker_identity:pre_lifecycle_context"
            in blocked["contract_failures"]
        )

    with tempfile.TemporaryDirectory() as temp:
        args, paths = fixture(Path(temp))
        price_manifest = json.loads(paths["price_manifest"].read_text(encoding="utf-8"))
        price_manifest["attempt_identity"] = "different-self-consistent-attempt"
        write_json(paths["price_manifest"], price_manifest)
        bundle = json.loads(paths["source_bundle"].read_text(encoding="utf-8"))
        bundle["inputs"]["price_manifest"] = record(paths["price_manifest"])
        write_json(paths["source_bundle"], bundle)
        upstream = json.loads(paths["upstream_status"].read_text(encoding="utf-8"))
        upstream["source_bundle"] = record(paths["source_bundle"])
        write_json(paths["upstream_status"], upstream)
        blocked = build(args)
        assert blocked["status"] == BLOCKED_STATUS, blocked
        assert (
            "manifest_lineage:decision_manifest:scored_latest_manifest:price_manifest"
            in blocked["contract_failures"]
        )

    with tempfile.TemporaryDirectory() as temp:
        args, paths = fixture(Path(temp))
        paths["macro_manifest:output"].write_text("corrupt\n", encoding="utf-8")
        blocked = build(args)
        assert blocked["status"] == BLOCKED_STATUS, blocked
        assert any(x.startswith("manifest_output:macro_manifest") for x in blocked["contract_failures"])

    with tempfile.TemporaryDirectory() as temp:
        args, paths = fixture(Path(temp))
        manifest = json.loads(paths["crisis_manifest"].read_text(encoding="utf-8"))
        manifest["target_books_mutated"] = True
        write_json(paths["crisis_manifest"], manifest)
        blocked = build(args)
        assert blocked["status"] == BLOCKED_STATUS, blocked
        assert "unsafe_flag:crisis_manifest:target_books_mutated" in blocked["contract_failures"]

    with tempfile.TemporaryDirectory() as temp:
        args, paths = fixture(Path(temp))
        bundle = json.loads(paths["source_bundle"].read_text(encoding="utf-8"))
        bundle["valuation_price_cutoff_date"] = "2026-07-10"
        write_json(paths["source_bundle"], bundle)
        blocked = build(args)
        assert blocked["status"] == BLOCKED_STATUS, blocked
        assert "source_bundle_date" in blocked["contract_failures"]

    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        args = argparse.Namespace(
            source_bundle=str(root / "missing.json"),
            upstream_status=str(root / "missing-upstream.json"),
            valuation_date=DATE,
            producer_contract=str(root / "contract.json"),
            output_dir=str(root / "registry"),
            allow_missing=True,
        )
        skipped = build(args)
        assert skipped["status"] == SKIPPED_STATUS, skipped
        assert skipped["registry_ready"] is False


if __name__ == "__main__":
    run()
    print("run287_exact_packet_input_registry_smoke: PASS")
