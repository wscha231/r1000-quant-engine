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
from tools.run287_code_identity import (  # noqa: E402
    current_code_identity,
    identity_sha256,
)


DATE = "2026-07-13"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def record(path: Path) -> dict[str, str]:
    return {"path": str(path), "sha256": sha(path)}


def generated_record(path: Path) -> dict[str, object]:
    return producer.fingerprint(path)


def write_benchmark(path: Path, close: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {"Close": [close - 2.0, close - 1.0, close]},
        index=pd.to_datetime(["2026-07-09", "2026-07-10", DATE]),
    ).to_parquet(path)


def output_manifest(
    path: Path,
    *,
    status: str,
    date_field: str,
    output_key: str,
    output_path: Path,
    coverage: dict | None = None,
    additional_outputs: dict[str, Path] | None = None,
) -> None:
    outputs = {output_key: record(output_path)}
    outputs.update(
        {
            key: record(additional_path)
            for key, additional_path in (additional_outputs or {}).items()
        }
    )
    write_json(
        path,
        {
            "status": status,
            date_field: DATE,
            "coverage": coverage or {},
            "outputs": outputs,
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
    scored_latest = artifacts / "scored_latest.csv"
    pd.DataFrame({"ticker": ["AAA"], "score_total": [1.0]}).to_csv(
        scored_latest,
        index=False,
    )
    price = inputs / "price.json"
    output_manifest(
        price,
        status="READY_RESEARCH_SCORED_LATEST",
        date_field="session_date",
        output_key="provider_price_overlap.parquet",
        output_path=provider,
        additional_outputs={"scored_latest.csv": scored_latest},
    )

    benchmark_rows: list[dict[str, object]] = []
    for ticker, close in (("SPY", 600.0), ("QQQ", 550.0), ("SMH", 300.0)):
        benchmark = artifacts / "cache" / producer.px_cache_name(ticker)
        write_benchmark(benchmark, close)
        benchmark_rows.append(
            {
                "ticker": ticker,
                "status": "ready",
                "row_count": 3,
                "date_min": "2026-07-09",
                "date_max": DATE,
                "isolated_path": str(benchmark),
                "isolated_sha256": sha(benchmark),
            }
        )
    market_audit = artifacts / "market_audit.csv"
    pd.DataFrame(benchmark_rows).to_csv(market_audit, index=False)
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
            "producer_contract_sha256": sha(contract),
            "code_identity": current_code_identity(),
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
        macro_cache = Path(selector_args.macro_price_cache)
        assert {path.name for path in macro_cache.iterdir()} == {
            producer.px_cache_name(ticker)
            for ticker in producer.SELECTOR_MACRO_BENCHMARKS
        }
        for ticker in producer.SELECTOR_MACRO_BENCHMARKS:
            frame = pd.read_parquet(macro_cache / producer.px_cache_name(ticker))
            assert pd.Timestamp(frame.index.max()).date().isoformat() == DATE
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
        generated_outputs: dict[str, dict[str, object]] = {}
        for key, filename in producer.SELECTOR_OUTPUT_FILES.items():
            path = output / filename
            if key != "marked_official_advisory_comparison":
                pd.DataFrame({"value": [key]}).to_csv(path, index=False)
            generated_outputs[key] = generated_record(path)
        payload = {
            "schema_version": producer.SELECTOR_SCHEMA_VERSION,
            "status": "READY_CURRENT_SELECTOR_NO_WRITE_REVIEW_REQUIRED",
            "valuation_price_cutoff_date": DATE,
            "selector_no_write_passed": True,
            "contract_failures": [],
            "scenario_summary": {"main:strict_registered_current": {}},
            "source_inputs": {
                "holding_watch_summary": record(
                    Path(selector_args.holding_watch_summary)
                ),
                "holding_watch_csv": record(Path(selector_args.holding_watch_csv)),
            },
            "outputs": generated_outputs,
        }
        write_json(output / "manifest.json", payload)
        return payload

    def fake_risk(risk_args: argparse.Namespace) -> dict:
        calls["risk"] += 1
        macro_manifest_path = Path(risk_args.macro_manifest)
        macro_manifest = json.loads(
            macro_manifest_path.read_text(encoding="utf-8")
        )
        market_record = macro_manifest["outputs"]["market_component_audit"]
        market_path = producer.resolve_portable_path(
            str(market_record["path"]),
            owner=macro_manifest_path,
        )
        assert sha(market_path) == market_record["sha256"]
        market = pd.read_csv(market_path, low_memory=False)
        macro_cache = Path(risk_args.macro_price_cache)
        for ticker in producer.SELECTOR_MACRO_BENCHMARKS:
            row = market.loc[market["ticker"].astype(str).str.upper().eq(ticker)]
            assert len(row) == 1
            isolated = Path(str(row.iloc[0]["isolated_path"]))
            assert isolated.resolve() == (
                macro_cache / producer.px_cache_name(ticker)
            ).resolve()
            assert sha(isolated) == str(row.iloc[0]["isolated_sha256"])
        output = Path(risk_args.output_dir)
        output.mkdir(parents=True)
        risk_rows = output / producer.RISK_OUTPUT_FILES["candidate_risk_watch"]
        pd.DataFrame(
            [{"ticker": "AAA", "risk_state": "NORMAL"}]
        ).to_csv(risk_rows, index=False)
        price_audit = output / producer.RISK_OUTPUT_FILES["price_source_audit"]
        pd.DataFrame([{"ticker": "AAA", "status": "ready"}]).to_csv(
            price_audit,
            index=False,
        )
        risk_history = output / producer.RISK_OUTPUT_FILES["risk_history"]
        risk_history.write_text(
            json.dumps({"ticker": "AAA", "as_of_date": DATE}) + "\n",
            encoding="utf-8",
        )
        payload = {
            "schema_version": producer.RISK_SCHEMA_VERSION,
            "status": "READY_CANDIDATE_RISK_REVIEW_ONLY",
            "as_of_date": DATE,
            "candidate_risk_watch_passed": True,
            "contract_failures": [],
            "candidate_count": 1,
            "candidate_tickers": ["AAA"],
            "outputs": {
                "candidate_risk_watch": generated_record(risk_rows),
                "price_source_audit": generated_record(price_audit),
                "risk_history": generated_record(risk_history),
            },
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
        assert (
            first["source_inputs"]["macro_benchmark_price_cache"]["passed"] is True
        )
        assert (
            first["source_inputs"]["macro_benchmark_price_cache"][
                "pre_publish_rehash"
            ]["passed"]
            is True
        )
        assert first["outputs"]["macro_benchmark_cache_audit"]["exists"] is True
        assert (
            len(first["packet_input_identity"]["identity_sha256"]) == 64
        )
        assert set(first["generated_output_audit"]["selector"]["outputs"]) == set(
            producer.SELECTOR_OUTPUT_FILES
        )
        assert set(
            first["generated_output_audit"]["candidate_risk"]["outputs"]
        ) == set(producer.RISK_OUTPUT_FILES)
        assert all(
            row["hash_matches"] is True
            for group in first["generated_output_audit"].values()
            for row in group["outputs"].values()
        )
        assert calls == {"selector": 1, "risk": 1}

        previous_status = root / "previous_status_for_reuse.json"
        (Path(args.output_dir) / "status.json").replace(previous_status)
        args.previous_status = str(previous_status)
        second = producer.build(args)
        assert second["status"] == producer.REUSED_STATUS
        assert calls == {"selector": 1, "risk": 1}
        assert (Path(args.output_dir) / "status.json").is_file()
        previous_status.unlink()
        args.previous_status = ""

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


def test_reuse_blocks_changed_holding_watch_identity() -> None:
    scratch = ROOT / "_tmp_tests"
    scratch.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="exact_packet_holding_", dir=scratch) as temp:
        root = Path(temp)
        args, calls = fixture(root)
        first = producer.build(args)
        assert first["status"] == producer.READY_STATUS
        previous_status = root / "previous_status_for_reuse.json"
        (Path(args.output_dir) / "status.json").replace(previous_status)
        args.previous_status = str(previous_status)

        holding_csv = Path(args.holding_watch_csv)
        holding_csv.write_bytes(holding_csv.read_bytes() + b"\n")
        holding_summary = json.loads(
            Path(args.holding_watch_summary).read_text(encoding="utf-8")
        )
        holding_summary["output_hashes"]["holding_risk_watch_sha256"] = sha(
            holding_csv
        )
        write_json(Path(args.holding_watch_summary), holding_summary)

        blocked = producer.build(args)
        assert blocked["status"] == producer.BLOCKED_STATUS
        assert "existing_packet_input_identity" in blocked["contract_failures"]
        assert calls == {"selector": 1, "risk": 1}


def test_fresh_blocks_generated_output_mutation_before_ready() -> None:
    scratch = ROOT / "_tmp_tests"
    scratch.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="exact_packet_generated_race_", dir=scratch
    ) as temp:
        root = Path(temp)
        args, calls = fixture(root)
        original_risk = producer.build_candidate_risk

        def mutating_risk(risk_args: argparse.Namespace) -> dict:
            payload = original_risk(risk_args)
            comparison = (
                Path(args.packet_root)
                / f"run287_current_selector_no_write_exact_close_{DATE.replace('-', '')}"
                / producer.SELECTOR_OUTPUT_FILES[
                    "marked_official_advisory_comparison"
                ]
            )
            comparison.write_bytes(comparison.read_bytes() + b"\n")
            return payload

        producer.build_candidate_risk = mutating_risk
        blocked = producer.build(args)
        assert blocked["status"] == producer.BLOCKED_STATUS, blocked
        assert any(
            "marked_official_advisory_comparison" in failure
            and "generated_packet_changed_after_risk" in failure
            for failure in blocked["contract_failures"]
        ), blocked["contract_failures"]
        assert calls == {"selector": 1, "risk": 1}


def test_reuse_blocks_generated_selector_and_risk_output_mutation() -> None:
    scratch = ROOT / "_tmp_tests"
    scratch.mkdir(exist_ok=True)
    cases = {
        "selector_comparison": (
            "run287_current_selector_no_write_exact_close_20260713",
            producer.SELECTOR_OUTPUT_FILES[
                "marked_official_advisory_comparison"
            ],
            "selector_manifest:output_",
        ),
        "risk_history": (
            "run287_candidate_risk_watch_exact_close_20260713",
            producer.RISK_OUTPUT_FILES["risk_history"],
            "candidate_risk_summary:output_",
        ),
    }
    with tempfile.TemporaryDirectory(
        prefix="exact_packet_generated_reuse_", dir=scratch
    ) as temp:
        root = Path(temp)
        for case, (directory, filename, expected_prefix) in cases.items():
            case_root = root / case
            args, calls = fixture(case_root)
            first = producer.build(args)
            assert first["status"] == producer.READY_STATUS, first
            previous_status = case_root / "previous_status_for_reuse.json"
            (Path(args.output_dir) / "status.json").replace(previous_status)
            args.previous_status = str(previous_status)
            target = Path(args.packet_root) / directory / filename
            target.write_bytes(target.read_bytes() + b"tampered")

            blocked = producer.build(args)
            assert blocked["status"] == producer.BLOCKED_STATUS, blocked
            assert any(
                failure.startswith(
                    f"existing_generated_packet:{expected_prefix}"
                )
                for failure in blocked["contract_failures"]
            ), blocked["contract_failures"]
            assert calls == {"selector": 1, "risk": 1}


def test_fresh_blocks_generated_output_escape_and_extra_key() -> None:
    scratch = ROOT / "_tmp_tests"
    scratch.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="exact_packet_generated_contract_", dir=scratch
    ) as temp:
        root = Path(temp)
        for case in ("path_escape", "extra_key"):
            case_root = root / case
            args, calls = fixture(case_root)
            original_selector = producer.build_selector

            def invalid_selector(
                selector_args: argparse.Namespace,
                *,
                mutation: str = case,
            ) -> dict:
                payload = original_selector(selector_args)
                manifest_path = Path(selector_args.output_dir) / "manifest.json"
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                comparison_key = "marked_official_advisory_comparison"
                if mutation == "path_escape":
                    escaped = case_root / "escaped_comparison.csv"
                    source = Path(
                        manifest["outputs"][comparison_key]["path"]
                    )
                    escaped.write_bytes(source.read_bytes())
                    manifest["outputs"][comparison_key] = generated_record(escaped)
                else:
                    extra = Path(selector_args.output_dir) / "unexpected.csv"
                    extra.write_text("value\nunexpected\n", encoding="utf-8")
                    manifest["outputs"]["unexpected"] = generated_record(extra)
                write_json(manifest_path, manifest)
                return manifest

            producer.build_selector = invalid_selector
            blocked = producer.build(args)
            assert blocked["status"] == producer.BLOCKED_STATUS, blocked
            expected = (
                "selector_manifest:output_path:"
                if case == "path_escape"
                else "selector_manifest:outputs_extra:"
            )
            assert any(
                expected in failure for failure in blocked["contract_failures"]
            ), blocked["contract_failures"]
            assert calls == {"selector": 1, "risk": 0}


def test_registry_must_bind_exact_producer_contract() -> None:
    scratch = ROOT / "_tmp_tests"
    scratch.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="exact_packet_contract_", dir=scratch) as temp:
        root = Path(temp)
        for case, replacement, expected_failure in (
            (
                "missing",
                None,
                "producer_contract_sha256_missing_or_invalid",
            ),
            (
                "mismatch",
                "0" * 64,
                "producer_contract_sha256_mismatch",
            ),
        ):
            case_root = root / case
            args, calls = fixture(case_root)
            registry_path = Path(args.input_registry)
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            if replacement is None:
                registry.pop("producer_contract_sha256", None)
            else:
                registry["producer_contract_sha256"] = replacement
            write_json(registry_path, registry)
            blocked = producer.build(args)
            assert blocked["status"] == producer.BLOCKED_STATUS
            assert expected_failure in blocked["contract_failures"]
            assert calls == {"selector": 0, "risk": 0}


def test_registry_must_bind_current_code_identity() -> None:
    scratch = ROOT / "_tmp_tests"
    scratch.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="exact_packet_code_identity_", dir=scratch
    ) as temp:
        root = Path(temp)
        args, calls = fixture(root)
        registry_path = Path(args.input_registry)
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        changed = registry["code_identity"]
        changed["source_commit_sha"] = "f" * 40
        changed["source_tree_sha"] = "e" * 40
        changed["identity_sha256"] = identity_sha256(changed)
        write_json(registry_path, registry)
        blocked = producer.build(args)
        assert blocked["status"] == producer.BLOCKED_STATUS, blocked
        assert (
            "input_registry_code_identity:current_mismatch"
            in blocked["contract_failures"]
        )
        assert calls == {"selector": 0, "risk": 0}


def test_qqq_and_smh_hash_tampering_blocks() -> None:
    scratch = ROOT / "_tmp_tests"
    scratch.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="exact_packet_bench_", dir=scratch) as temp:
        root = Path(temp)
        for ticker, close in (("QQQ", 777.0), ("SMH", 444.0)):
            case_root = root / ticker.lower()
            args, calls = fixture(case_root)
            benchmark = (
                case_root
                / "artifacts"
                / "cache"
                / producer.px_cache_name(ticker)
            )
            write_benchmark(benchmark, close)
            blocked = producer.build(args)
            assert blocked["status"] == producer.BLOCKED_STATUS
            assert (
                f"macro_benchmark_cache:{ticker}:source_hash"
                in blocked["contract_failures"]
            )
            assert blocked["outputs"]["macro_benchmark_cache_audit"]["exists"] is True
            assert calls == {"selector": 0, "risk": 0}


def test_macro_benchmark_pre_publish_rehash_blocks_mutation() -> None:
    scratch = ROOT / "_tmp_tests"
    scratch.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="exact_packet_rehash_", dir=scratch) as temp:
        root = Path(temp)
        args, calls = fixture(root)
        original_selector = producer.build_selector
        qqq_source = (
            root / "artifacts" / "cache" / producer.px_cache_name("QQQ")
        )

        def mutating_selector(selector_args: argparse.Namespace) -> dict:
            payload = original_selector(selector_args)
            write_benchmark(qqq_source, 999.0)
            return payload

        producer.build_selector = mutating_selector
        blocked = producer.build(args)
        assert blocked["status"] == producer.BLOCKED_STATUS
        assert (
            "macro_benchmark_cache_rehash:QQQ:source_changed"
            in blocked["contract_failures"]
        )
        assert calls == {"selector": 1, "risk": 1}


def test_reuse_revalidates_registered_outputs_and_price_map_sources() -> None:
    scratch = ROOT / "_tmp_tests"
    scratch.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="exact_packet_reuse_inputs_", dir=scratch) as temp:
        root = Path(temp)
        targets = {
            "decision_output": "selection_context.parquet",
            "price_map_source": "aaa.parquet",
            "soxx_output": "soxx.parquet",
        }
        for name, filename in targets.items():
            case_root = root / name
            args, calls = fixture(case_root)
            first = producer.build(args)
            assert first["status"] == producer.READY_STATUS
            target = case_root / "artifacts" / filename
            target.write_bytes(target.read_bytes() + b"tampered")
            blocked = producer.build(args)
            assert blocked["status"] == producer.BLOCKED_STATUS
            assert any(
                failure.startswith("portable_input:")
                for failure in blocked["contract_failures"]
            )
            assert calls == {"selector": 1, "risk": 1}


def test_non_macro_input_change_during_packet_build_blocks_ready() -> None:
    scratch = ROOT / "_tmp_tests"
    scratch.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="exact_packet_input_race_", dir=scratch) as temp:
        root = Path(temp)
        args, calls = fixture(root)
        original_selector = producer.build_selector
        selection_context = root / "artifacts" / "selection_context.parquet"

        def mutating_selector(selector_args: argparse.Namespace) -> dict:
            payload = original_selector(selector_args)
            selection_context.write_bytes(selection_context.read_bytes() + b"changed")
            return payload

        producer.build_selector = mutating_selector
        blocked = producer.build(args)
        assert blocked["status"] == producer.BLOCKED_STATUS
        assert any(
            failure.startswith("registered_input_revalidation:")
            for failure in blocked["contract_failures"]
        )
        assert calls == {"selector": 1, "risk": 1}


def test_stale_ready_marker_removed_before_unhandled_input_error() -> None:
    scratch = ROOT / "_tmp_tests"
    scratch.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="exact_packet_marker_", dir=scratch) as temp:
        root = Path(temp)
        args, _calls = fixture(root)
        status_path = Path(args.output_dir) / "status.json"
        write_json(status_path, {"status": producer.READY_STATUS})
        invalid_registry = root / "invalid_registry.json"
        invalid_registry.write_text("{not-json\n", encoding="utf-8")
        args.input_registry = str(invalid_registry)
        try:
            producer.build(args)
        except json.JSONDecodeError:
            pass
        else:
            raise AssertionError("invalid registry must raise before a new marker is written")
        assert not status_path.exists()


def main() -> None:
    test_ready_reuse_skip_and_stale_block()
    test_reuse_blocks_changed_holding_watch_identity()
    test_fresh_blocks_generated_output_mutation_before_ready()
    test_reuse_blocks_generated_selector_and_risk_output_mutation()
    test_fresh_blocks_generated_output_escape_and_extra_key()
    test_registry_must_bind_exact_producer_contract()
    test_registry_must_bind_current_code_identity()
    test_qqq_and_smh_hash_tampering_blocks()
    test_macro_benchmark_pre_publish_rehash_blocks_mutation()
    test_reuse_revalidates_registered_outputs_and_price_map_sources()
    test_non_macro_input_change_during_packet_build_blocks_ready()
    test_stale_ready_marker_removed_before_unhandled_input_error()
    print("run287_exact_packet_producer_smoke: PASS")


if __name__ == "__main__":
    main()
