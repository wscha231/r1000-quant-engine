#!/usr/bin/env python3
"""Smoke checks for the fail-closed Run287 next-single-A/B audit."""
from __future__ import annotations

import importlib.util
import json
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "audit_run287_next_single_ab_readiness.py"
SPEC = importlib.util.spec_from_file_location("audit_run287_next_single_ab_readiness", MODULE_PATH)
assert SPEC and SPEC.loader
MOD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MOD)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def fixture(td: str) -> dict[str, Path]:
    root = Path(td)
    artifacts = []
    hash_checks = {}
    for name in ["raw", "candidate", "selector", "input_manifest", "crisis", "thresholds"]:
        path = root / f"{name}.bin"
        path.write_bytes(f"fixture-{name}".encode())
        artifact_id = {
            "raw": "raw_candidate_replay_book",
            "candidate": "candidate_replay_book",
            "selector": "selector_metadata",
            "input_manifest": "target_generation_input_manifest",
            "crisis": "long_crisis_features",
            "thresholds": "long_crisis_thresholds",
        }[name]
        artifacts.append({"id": artifact_id, "path": str(path), "expected_sha256": MOD.sha256_file(path)})
        hash_checks[artifact_id] = True

    contract = {
        "schema_version": "run287-next-single-ab-readiness-contract-v1",
        "generated_substrate": {
            "official_source_run_id": "28725350727",
            "require_core_ready": True,
            "require_parity_ready": True,
            "require_generated_book_ready": True,
            "local_artifacts": artifacts,
        },
        "terminal_source_lanes": {
            "sec_filing_quality_event": {"required_verdict": "REJECT_SOURCE_SCREEN"},
            "sec_management_guidance_scout": {"required_status": "CLOSED_SOURCE_PRECISION_OR_RECALL_GATE"},
        },
        "external_pit_lane": {
            "source_data_ready_status": "READY_FOR_SOURCE_SCREEN",
            "source_screen_pass_verdict": "PASS_SOURCE_SCREEN",
            "fixed_book_pass_verdict": "PASS_FIXED_BOOK",
            "candidate_arms_field": "candidate_arms",
            "maximum_eligible_arms": 1,
            "candidate_arm_required_fields": ["arm_id", "signal", "mechanism", "book", "window", "preregistered"],
        },
        "forward_risk_lane": {"mechanism_review_ready_field": "mechanism_review_ready"},
        "safety": {
            "research_only": True,
            "portfolio_mutation_allowed": False,
            "target_books_mutated": False,
            "selector_weights_changed": False,
            "cash_policy_changed": False,
            "orders_generated": False,
            "fullrun_allowed": False,
            "production_activation_allowed": False,
            "live_trading_enabled": False,
        },
    }
    freeze = {
        "gates": {
            "core_substrate": {"ready": True},
            "parity": {"ready": True},
            "generated_book_substrate": {
                "ready": True,
                "official_source_run_id": "28725350727",
                "hash_checks": hash_checks,
            },
        }
    }
    paths = {
        "contract": root / "contract.json",
        "freeze": root / "freeze.json",
        "sec_filing": root / "sec_filing.json",
        "sec_guidance": root / "sec_guidance.json",
        "source_gate": root / "source_gate.json",
        "source_screen": root / "source_screen.json",
        "fixed_book": root / "fixed_book.json",
        "risk": root / "risk.json",
        "registry": root / "registry.json",
        "output": root / "output",
    }
    write_json(paths["contract"], contract)
    write_json(paths["freeze"], freeze)
    write_json(paths["sec_filing"], {"verdict": "REJECT_SOURCE_SCREEN"})
    write_json(paths["sec_guidance"], {"status": "CLOSED_SOURCE_PRECISION_OR_RECALL_GATE"})
    write_json(paths["registry"], {"match_fields": ["signal", "mechanism", "book", "window"], "entries": []})
    return paths


def run(paths: dict[str, Path], *, include_external: bool = False, include_fixed: bool = False) -> dict[str, Any]:
    return MOD.audit(
        contract_path=paths["contract"],
        freeze_path=paths["freeze"],
        sec_filing_path=paths["sec_filing"],
        sec_guidance_path=paths["sec_guidance"],
        source_gate_path=paths["source_gate"] if include_external else None,
        source_screen_path=paths["source_screen"] if include_external else None,
        fixed_book_path=paths["fixed_book"] if include_fixed else None,
        risk_outcome_path=paths["risk"] if paths["risk"].exists() else None,
        do_not_repeat_path=paths["registry"],
        output_dir=paths["output"],
        generated_at="2026-07-15T00:00:00Z",
    )


def arm(arm_id: str = "pit_revision_main_v1") -> dict[str, Any]:
    return {
        "arm_id": arm_id,
        "signal": "pit_estimate_revision",
        "mechanism": "negative_veto",
        "book": "run287_fixed_main",
        "window": "2019-06-03_2026-07-10",
        "preregistered": True,
    }


def test_missing_external_evidence_blocks_but_substrate_is_ready() -> None:
    with tempfile.TemporaryDirectory() as td:
        paths = fixture(td)
        result = run(paths)
        assert result["status"] == "BLOCKED_NO_ELIGIBLE_SINGLE_AB"
        assert result["generated_substrate"]["ready"] is True
        assert result["next_single_ab_gate_open"] is False
        assert result["selected_arm"] is None
        assert result["terminal_source_lanes"]["lanes"]["sec_filing_quality_event"]["portfolio_ab_allowed"] is False
        assert result["safety"]["fullrun_allowed"] is False


def test_source_gate_alone_never_opens_ab() -> None:
    with tempfile.TemporaryDirectory() as td:
        paths = fixture(td)
        write_json(paths["source_gate"], {"status": "READY_FOR_SOURCE_SCREEN"})
        write_json(paths["source_screen"], {"verdict": "UNDERPOWERED", "candidate_arms": []})
        result = run(paths, include_external=True)
        assert result["next_single_ab_gate_open"] is False
        assert "external_pit_source_screen_not_passed" in result["historical_lane"]["blockers"]


def test_one_preregistered_source_screen_winner_opens_only_fixed_book_ab() -> None:
    with tempfile.TemporaryDirectory() as td:
        paths = fixture(td)
        write_json(paths["source_gate"], {"status": "READY_FOR_SOURCE_SCREEN"})
        write_json(paths["source_screen"], {"verdict": "PASS_SOURCE_SCREEN", "candidate_arms": [arm()]})
        result = run(paths, include_external=True)
        assert result["status"] == "READY_SINGLE_FIXED_BOOK_AB"
        assert result["historical_lane"]["fixed_book_ab_gate_open"] is True
        assert result["historical_lane"]["generated_book_ab_gate_open"] is False
        assert result["selected_arm"]["arm_id"] == "pit_revision_main_v1"


def test_fixed_book_pass_opens_only_matching_generated_book_ab() -> None:
    with tempfile.TemporaryDirectory() as td:
        paths = fixture(td)
        write_json(paths["source_gate"], {"status": "READY_FOR_SOURCE_SCREEN"})
        write_json(paths["source_screen"], {"verdict": "PASS_SOURCE_SCREEN", "candidate_arms": [arm()]})
        write_json(paths["fixed_book"], {"verdict": "PASS_FIXED_BOOK", "arm_id": "pit_revision_main_v1"})
        result = run(paths, include_external=True, include_fixed=True)
        assert result["status"] == "READY_SINGLE_GENERATED_BOOK_AB"
        assert result["historical_lane"]["fixed_book_ab_gate_open"] is False
        assert result["historical_lane"]["generated_book_ab_gate_open"] is True


def test_multiple_or_repeated_arms_fail_closed() -> None:
    with tempfile.TemporaryDirectory() as td:
        paths = fixture(td)
        write_json(paths["source_gate"], {"status": "READY_FOR_SOURCE_SCREEN"})
        write_json(paths["source_screen"], {"verdict": "PASS_SOURCE_SCREEN", "candidate_arms": [arm("a"), arm("b")]})
        result = run(paths, include_external=True)
        assert result["next_single_ab_gate_open"] is False
        assert any(value.startswith("multiple_eligible_arms") for value in result["historical_lane"]["blockers"])

    with tempfile.TemporaryDirectory() as td:
        paths = fixture(td)
        candidate = arm()
        write_json(paths["source_gate"], {"status": "READY_FOR_SOURCE_SCREEN"})
        write_json(paths["source_screen"], {"verdict": "PASS_SOURCE_SCREEN", "candidate_arms": [candidate]})
        write_json(paths["registry"], {
            "match_fields": ["signal", "mechanism", "book", "window"],
            "entries": [{**candidate, "id": "old_failure", "blocked_reuse": True}],
        })
        result = run(paths, include_external=True)
        assert result["next_single_ab_gate_open"] is False
        assert any(value.startswith("candidate_arm_do_not_repeat") for value in result["historical_lane"]["blockers"])


def test_forward_mechanism_review_never_becomes_historical_ab() -> None:
    with tempfile.TemporaryDirectory() as td:
        paths = fixture(td)
        write_json(paths["risk"], {"mechanism_review_ready": True})
        result = run(paths)
        assert result["status"] == "READY_FORWARD_MECHANISM_REVIEW_ONLY"
        assert result["forward_lane"]["mechanism_review_gate_open"] is True
        assert result["forward_lane"]["portfolio_ab_allowed"] is False
        assert result["next_single_ab_gate_open"] is False


def test_hash_mismatch_blocks_every_gate() -> None:
    with tempfile.TemporaryDirectory() as td:
        paths = fixture(td)
        contract = json.loads(paths["contract"].read_text(encoding="utf-8"))
        Path(contract["generated_substrate"]["local_artifacts"][0]["path"]).write_bytes(b"changed")
        write_json(paths["source_gate"], {"status": "READY_FOR_SOURCE_SCREEN"})
        write_json(paths["source_screen"], {"verdict": "PASS_SOURCE_SCREEN", "candidate_arms": [arm()]})
        result = run(paths, include_external=True)
        assert result["generated_substrate"]["ready"] is False
        assert result["next_single_ab_gate_open"] is False
        assert any(value.startswith("local_artifact_hash_mismatch") for value in result["generated_substrate"]["blockers"])


def main() -> int:
    test_missing_external_evidence_blocks_but_substrate_is_ready()
    test_source_gate_alone_never_opens_ab()
    test_one_preregistered_source_screen_winner_opens_only_fixed_book_ab()
    test_fixed_book_pass_opens_only_matching_generated_book_ab()
    test_multiple_or_repeated_arms_fail_closed()
    test_forward_mechanism_review_never_becomes_historical_ab()
    test_hash_mismatch_blocks_every_gate()
    print("run287_next_single_ab_readiness_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
