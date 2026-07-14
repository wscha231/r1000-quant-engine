#!/usr/bin/env python3
"""Smoke checks for the bounded Run287 exact packet producer."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import run_run287_exact_packet_producer as producer  # noqa: E402


DATE = "2026-07-13"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def record(path: Path) -> dict[str, str]:
    return {"path": str(path), "sha256": sha(path)}


def output_manifest(
    path: Path,
    *,
    status: str,
    date_field: str,
    output_key: str,
    output_path: Path,
    coverage: dict | None = None,
) -> None:
    write_json(
        path,
        {
            "status": status,
            date_field: DATE,
            "coverage": coverage or {},
            "outputs": {output_key: record(output_path)},
        },
    )


def fixture(root: Path) -> tuple[argparse.Namespace, dict[str, int]]:
    inputs = root / "inputs"
    inputs.mkdir(parents=True)
    artifacts = root / "artifacts"
    artifacts.mkdir()

    selection_context = artifacts / "selection_context.parquet"
    pd.DataFrame({"ticker": ["AAA"]}).to_parquet(selection_context)
    decision = inputs / "decision.json"
    output_manifest(
        decision,
        status="READY_COMPLETE_CURRENT_DECISION_FRAME",
        date_field="valuation_price_cutoff_date",
        output_key="selection_context",
        output_path=selection_context,
        coverage={"decision_ticker_count": 1},
    )

    score_csv = artifacts / "score.csv"
    pd.DataFrame({"ticker": ["AAA"]}).to_csv(score_csv, index=False)
    score = inputs / "score.json"
    output_manifest(
        score,
        status="READY_CURRENT_DECISION_SCORE_STACK_ELIGIBILITY_AUDIT_NONRANKING",
        date_field="valuation_price_cutoff_date",
        output_key="ticker_order_score_stack",
        output_path=score_csv,
        coverage={"registered_eligible_ticker_count": 1},
    )

    crisis_csv = artifacts / "crisis.csv"
    pd.DataFrame({"date": [DATE], "state": ["GREEN"]}).to_csv(crisis_csv, index=False)
    crisis = inputs / "crisis.json"
    output_manifest(
        crisis,
        status="READY_CURRENT_CRISIS_STATE_NONSELECTING",
        date_field="valuation_price_cutoff_date",
        output_key="current_crisis_state",
        output_path=crisis_csv,
    )

    provider = artifacts / "provider.parquet"
    pd.DataFrame({"ticker": ["AAA"], "Date": [DATE], "Close": [100.0]}).to_parquet(provider)
    price = inputs / "price.json"
    output_manifest(
        price,
        status="READY_RESEARCH_SCORED_LATEST",
        date_field="session_date",
        output_key="provider_price_overlap.parquet",
        output_path=provider,
    )

    spy = artifacts / "cache" / "spy.parquet"
    spy.parent.mkdir()
    spy.write_bytes(b"spy-price")
    market_audit = artifacts / "market_audit.csv"
    pd.DataFrame(
        [{"ticker": "SPY", "isolated_path": str(spy), "isolated_sha256": sha(spy)}]
    ).to_csv(market_audit, index=False)
    macro = inputs / "macro.json"
    output_manifest(
        macro,
        status="READY_CONSERVATIVE_MACRO_SIDECAR",
        date_field="valuation_close_date",
        output_key="market_component_audit",
        output_path=market_audit,
    )

    soxx_file = artifacts / "soxx.parquet"
    soxx_file.write_bytes(b"soxx-price")
    soxx = inputs / "soxx.json"
    output_manifest(
        soxx,
        status="READY_SELECTOR_BENCHMARK_PRICE_NONSELECTING",
        date_field="valuation_price_cutoff_date",
        output_key="price_file",
        output_path=soxx_file,
    )

    map_source = artifacts / "aaa.parquet"
    map_source.write_bytes(b"aaa-price")
    map_csv = artifacts / "selector_price_map.csv"
    pd.DataFrame(
        [{"ticker": "AAA", "path": str(map_source), "sha256": sha(map_source)}]
    ).to_csv(map_csv, index=False)
    price_map = inputs / "price_map.json"
    write_json(
        price_map,
        {
            "status": "READY_CURRENT_SELECTOR_PRICE_MAP_NONSELECTING",
            "outputs": {"selector_price_map": record(map_csv)},
        },
    )

    fixed: dict[str, Path] = {}
    for name in (
        "selector_contract_manifest",
        "pinned_import_manifest",
        "target_generation_manifest",
        "main_prior_book",
        "concentrated_prior_book",
    ):
        path = inputs / name
        path.write_text(name + "\n", encoding="utf-8")
        fixed[name] = path
    fixed["price_map_manifest"] = price_map

    base_contract = inputs / "base_contract.json"
    candidate_contract = inputs / "candidate_contract.json"
    base_contract.write_text("base\n", encoding="utf-8")
    candidate_contract.write_text("candidate\n", encoding="utf-8")
    contract = root / "contract.json"
    write_json(
        contract,
        {
            "schema_version": "run287-exact-packet-producer-contract-v1",
            "input_registry_schema_version": "run287-exact-packet-input-registry-v1",
            "required_dynamic_inputs": {
                "decision_manifest": {"status": "READY_COMPLETE_CURRENT_DECISION_FRAME", "date_field": "valuation_price_cutoff_date"},
                "score_stack_manifest": {"status": "READY_CURRENT_DECISION_SCORE_STACK_ELIGIBILITY_AUDIT_NONRANKING", "date_field": "valuation_price_cutoff_date"},
                "crisis_manifest": {"status": "READY_CURRENT_CRISIS_STATE_NONSELECTING", "date_field": "valuation_price_cutoff_date"},
                "price_manifest": {"status": "READY_RESEARCH_SCORED_LATEST", "date_field": "session_date"},
                "macro_manifest": {"status": "READY_CONSERVATIVE_MACRO_SIDECAR", "date_field": "valuation_close_date"},
                "soxx_manifest": {"status": "READY_SELECTOR_BENCHMARK_PRICE_NONSELECTING", "date_field": "valuation_price_cutoff_date"},
            },
            "required_fixed_inputs": {name: sha(path) for name, path in fixed.items()},
            "tracked_contracts": {
                "holding_risk_contract": sha(base_contract),
                "candidate_risk_contract": sha(candidate_contract),
            },
            "pinned_policy_commit": "test-policy",
        },
    )

    registry_inputs = {
        "decision_manifest": record(decision),
        "score_stack_manifest": record(score),
        "crisis_manifest": record(crisis),
        "price_manifest": record(price),
        "macro_manifest": record(macro),
        "soxx_manifest": record(soxx),
        **{name: record(path) for name, path in fixed.items()},
    }
    registry = root / "registry.json"
    write_json(
        registry,
        {
            "schema_version": "run287-exact-packet-input-registry-v1",
            "status": "READY_EXACT_PACKET_INPUTS_REVIEW_ONLY",
            "valuation_price_cutoff_date": DATE,
            "inputs": registry_inputs,
        },
    )

    holding_csv = root / "holding.csv"
    pd.DataFrame({"ticker": ["OLD"]}).to_csv(holding_csv, index=False)
    holding_summary = root / "holding.json"
    write_json(
        holding_summary,
        {
            "status": "READY_REVIEW_ONLY",
            "as_of_date": DATE,
            "output_hashes": {"holding_risk_watch_sha256": sha(holding_csv)},
        },
    )
    args = argparse.Namespace(
        input_registry=str(registry),
        valuation_date=DATE,
        holding_watch_summary=str(holding_summary),
        holding_watch_csv=str(holding_csv),
        contract=str(contract),
        base_contract=str(base_contract),
        candidate_contract=str(candidate_contract),
        output_dir=str(root / "producer"),
        packet_root=str(root / "packets"),
        allow_missing=False,
    )
    calls = {"selector": 0, "risk": 0}

    def fake_selector(selector_args: argparse.Namespace) -> dict:
        calls["selector"] += 1
        output = Path(selector_args.output_dir)
        output.mkdir(parents=True)
        comparison = output / "marked_official_advisory_comparison.csv"
        pd.DataFrame(
            [
                {
                    "ticker": "AAA",
                    "advisory_weight": 0.1,
                    "marked_weight": 0.0,
                    "delta_vs_marked": 0.1,
                    "scenario": "strict_registered_current",
                    "portfolio_kind": "main",
                }
            ]
        ).to_csv(comparison, index=False)
        payload = {
            "status": "READY_CURRENT_SELECTOR_NO_WRITE_REVIEW_REQUIRED",
            "valuation_price_cutoff_date": DATE,
            "selector_no_write_passed": True,
            "scenario_summary": {"main:strict_registered_current": {}},
            "outputs": {"marked_official_advisory_comparison": record(comparison)},
        }
        write_json(output / "manifest.json", payload)
        return payload

    def fake_risk(risk_args: argparse.Namespace) -> dict:
        calls["risk"] += 1
        output = Path(risk_args.output_dir)
        output.mkdir(parents=True)
        payload = {
            "status": "READY_CANDIDATE_RISK_REVIEW_ONLY",
            "as_of_date": DATE,
            "candidate_risk_watch_passed": True,
            "candidate_count": 1,
            "candidate_tickers": ["AAA"],
        }
        write_json(output / "summary.json", payload)
        return payload

    producer.build_selector = fake_selector
    producer.build_candidate_risk = fake_risk
    return args, calls


def test_ready_reuse_skip_and_stale_block() -> None:
    scratch = ROOT / "_tmp_tests"
    scratch.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="exact_packet_", dir=scratch) as temp:
        root = Path(temp)
        args, calls = fixture(root)
        first = producer.build(args)
        assert first["status"] == producer.READY_STATUS
        assert first["exact_packet_ready"] is True
        assert first["candidate_count"] == 1
        assert first["network_requests_executed"] == 0
        assert first["orders_generated"] is False
        assert calls == {"selector": 1, "risk": 1}

        second = producer.build(args)
        assert second["status"] == producer.REUSED_STATUS
        assert calls == {"selector": 1, "risk": 1}

        missing = argparse.Namespace(**vars(args))
        missing.input_registry = str(root / "missing.json")
        missing.output_dir = str(root / "missing_producer")
        missing.allow_missing = True
        skipped = producer.build(missing)
        assert skipped["status"] == producer.SKIPPED_STATUS
        assert skipped["exact_packet_ready"] is False

        stale_root = root / "stale"
        shutil.copytree(root / "inputs", stale_root / "inputs")
        stale_registry = json.loads(Path(args.input_registry).read_text(encoding="utf-8"))
        stale_registry["valuation_price_cutoff_date"] = "2026-07-10"
        stale_path = stale_root / "registry.json"
        write_json(stale_path, stale_registry)
        stale = argparse.Namespace(**vars(args))
        stale.input_registry = str(stale_path)
        stale.output_dir = str(stale_root / "producer")
        stale.packet_root = str(stale_root / "packets")
        blocked = producer.build(stale)
        assert blocked["status"] == producer.BLOCKED_STATUS
        assert "input_registry_date" in blocked["contract_failures"]


def main() -> None:
    test_ready_reuse_skip_and_stale_block()
    print("run287_exact_packet_producer_smoke: PASS")


if __name__ == "__main__":
    main()
