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
    SKIPPED_STATUS,
    build,
)


DATE = "2026-07-13"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def record(path: Path) -> dict[str, str]:
    return {"path": str(path), "sha256": sha(path)}


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
                "outputs": {output_key: record(output)},
            },
        )
        paths[label] = manifest
        paths[f"{label}:output"] = output
        dynamic_contract[label] = {"status": status, "date_field": date_field}

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
    write_json(
        bundle,
        {
            "schema_version": "run287-exact-packet-input-source-bundle-v1",
            "status": "READY_EXACT_PACKET_INPUT_SOURCE_PATHS_REVIEW_ONLY",
            "valuation_price_cutoff_date": DATE,
            "inputs": {
                label: {"path": str(paths[label])}
                for label in (*dynamic_specs, *fixed_labels, "price_map_manifest")
            },
        },
    )
    paths["source_bundle"] = bundle
    args = argparse.Namespace(
        source_bundle=str(bundle),
        valuation_date=DATE,
        producer_contract=str(contract),
        output_dir=str(root / "registry"),
        allow_missing=False,
    )
    return args, paths


def run() -> None:
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
        assert "immutable_date_collision" in collision["contract_failures"]

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
