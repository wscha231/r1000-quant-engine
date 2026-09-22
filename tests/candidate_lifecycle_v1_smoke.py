from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "research"))

from candidate_lifecycle_v1 import (
    CandidateLifecycleError,
    admit_event,
    build_a5_candidate_view,
    empty_candidate_registry,
    empty_event_registry,
    plan_delta_refresh,
    upsert_candidate,
    validate_event,
)

RAW: dict[tuple[str, str], bytes] = {}


def add(artifact_id: str, obj: dict) -> dict:
    raw = json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()
    sha = hashlib.sha256(raw).hexdigest()
    RAW[(artifact_id, sha)] = raw
    return {
        "artifact_id": artifact_id,
        "sha256": sha,
        "available_at": "2026-09-22T11:30:00Z",
    }


def resolver(artifact_id: str, sha: str) -> bytes:
    return RAW[(artifact_id, sha)]


def fingerprints(**changes: str) -> dict[str, str]:
    keys = [
        "source_graph_hash",
        "fundamental_hash",
        "methodology_hash",
        "market_price_hash",
        "earnings_consensus_hash",
        "regime_hash",
    ]
    base = {key: hashlib.sha256(key.encode()).hexdigest() for key in keys}
    for key, value in changes.items():
        base[key] = hashlib.sha256(value.encode()).hexdigest()
    return base


def event(*, tier="V2", materiality="MATERIAL", event_id="BABA-AI-20260922") -> dict:
    source_ref = None
    if tier != "V0":
        source_ref = add("SRC:BABA", {"schema": "a3-source-graph-v1", "review_status": "REVIEWED"})
    return {
        "schema": "a2-event-handoff-v1",
        "event_id": event_id,
        "event_family": "CHINA_AI_FULL_STACK_SELF_RELIANCE",
        "first_seen_at": "2026-09-22T10:00:00Z",
        "verified_at": "2026-09-22T12:00:00Z",
        "verification_tier": tier,
        "materiality": materiality,
        "asset_ids": ["US:BABA"],
        "theme_id": "CHINA_AI_FULL_STACK_SELF_RELIANCE",
        "affected_methodology": [
            "industry_structure_bottleneck",
            "moat_durability",
            "growth_runway_customer_product",
            "profitability_reinvestment_capital_efficiency",
            "valuation_margin_of_safety",
            "market_leadership_price_volume_rs",
            "catalyst_ownership_information_edge",
            "downside_balance_sheet_cycle_regime",
        ],
        "affected_moat": [
            "qualification_switching_cost",
            "market_structure_position",
            "replacement_difficulty",
            "next_generation_relevance",
        ],
        "assessment_score_effect": 0,
        "source_graph_ref": source_ref,
    }


def a3_result(er_ref: dict | None) -> dict:
    return {
        "schema": "a3-candidate-packet-v1-result",
        "status": "VALIDATED_ER_LINKED" if er_ref else "SCENARIO_RESEARCH_COMPLETE",
        "asset_id": "US:BABA",
        "issuer_id": "CIK:BABA",
        "benchmark_id": "US:SPY",
        "validated_er_sha256": None if er_ref is None else er_ref["sha256"],
        "validated_expected_return_available": er_ref is not None,
        "selector_eligible": False,
        "portfolio_weight_effect": 0.0,
        "target_book_write_allowed": False,
        "orders_allowed": False,
    }


def er() -> dict:
    value = {
        "asset_id": "US:BABA",
        "validation_status": "WALK_FORWARD_VALIDATED",
        "benchmark_id": "US:SPY",
        "net_of_costs": True,
        "unit": "RETURN_FRACTION",
        "signal_confidence": 0.78,
        "thesis_confidence": 0.72,
        "expected_drawdown": 0.26,
        "downside_probability": 0.31,
    }
    for h, ret in (("1m", 0.04), ("3m", 0.10), ("6m", 0.18), ("12m", 0.28)):
        value[f"expected_return_{h}"] = ret
        value[f"benchmark_expected_return_{h}"] = 0.03 if h == "1m" else 0.08
    return value


def candidate_record(a3_ref: dict, er_ref: dict | None, *, freshness="CURRENT") -> dict:
    return {
        "asset_id": "US:BABA",
        "issuer_id": "CIK:BABA",
        "market": "US",
        "currency": "USD",
        "security_type": "ADR",
        "current_a3_result_ref": a3_ref,
        "latest_market_snapshot_ref": add("MKT:BABA", {"asset_id": "US:BABA", "session": "2026-09-22"}),
        "latest_validated_er_ref": er_ref,
        "event_cohort_ids": ["COHORT:BABA-AI-20260922"],
        "thesis_status": "WATCH",
        "invalidation_conditions": ["V900 production or cloud monetization materially misses the reviewed thesis"],
        "freshness_state": freshness,
        "fingerprints": fingerprints(),
        "last_full_review_at": "2026-09-22T19:00:00Z",
        "last_delta_refresh_at": "2026-09-22T20:00:00Z",
        "data_gate_status": "PASS",
        "pit_gate_status": "PASS",
    }


class Tests(unittest.TestCase):
    def setUp(self):
        RAW.clear()

    def test_v0_is_discovery_only_and_zero_credit(self):
        out = validate_event(event(tier="V0", materiality="CRITICAL"), "2026-09-22T21:00:00Z")
        self.assertEqual(out["status"], "DISCOVERY_ONLY")
        self.assertFalse(out["a3_refresh_required"])
        self.assertEqual(out["assessment_score_effect"], 0)

    def test_material_v2_routes_to_a3_refresh(self):
        out = validate_event(event(), "2026-09-22T21:00:00Z")
        self.assertEqual(out["status"], "A3_REFRESH_CANDIDATE")
        self.assertTrue(out["a3_refresh_required"])

    def test_watch_tracks_without_a3_refresh(self):
        out = validate_event(event(materiality="WATCH"), "2026-09-22T21:00:00Z")
        self.assertEqual(out["status"], "TRACK")
        self.assertFalse(out["a3_refresh_required"])

    def test_event_registry_deduplicates_same_family_inside_24h(self):
        registry = empty_event_registry("2026-09-22T21:00:00Z")
        registry, first = admit_event(registry, event(), "2026-09-22T21:00:00Z")
        second_event = event(event_id="BABA-AI-20260922-B")
        second_event["first_seen_at"] = "2026-09-22T18:00:00Z"
        second_event["verified_at"] = "2026-09-22T19:00:00Z"
        registry, second = admit_event(registry, second_event, "2026-09-22T21:00:00Z")
        self.assertEqual(first["action"], "ADDED")
        self.assertEqual(second["action"], "DEDUP_UPDATED")
        self.assertEqual(len(registry["cohorts"]), 1)
        self.assertEqual(len(registry["cohorts"][0]["event_ids"]), 2)

    def test_skip_unchanged(self):
        fp = fingerprints()
        out = plan_delta_refresh(fp, fp)
        self.assertEqual(out["action"], "SKIP_UNCHANGED")

    def test_price_only_refreshes_valuation_and_er(self):
        previous = fingerprints()
        current = fingerprints(market_price_hash="new-price")
        out = plan_delta_refresh(previous, current)
        self.assertEqual(out["refresh"], ["MARKET_VALUATION", "ER"])

    def test_material_event_refreshes_only_affected_research(self):
        fp = fingerprints()
        normalized = validate_event(event(), "2026-09-22T21:00:00Z")
        out = plan_delta_refresh(fp, fp, event=normalized)
        self.assertEqual(out["action"], "AFFECTED_A3_REFRESH")
        self.assertIn("moat_durability", out["affected_methodology"])
        self.assertNotIn("FULL_A3_REVIEW", out["refresh"])

    def test_integrity_break_forces_full_a3(self):
        fp = fingerprints()
        out = plan_delta_refresh(fp, fp, integrity_break=True)
        self.assertEqual(out["action"], "FULL_A3_REFRESH")
        self.assertEqual(out["freshness_state"], "FULL_REFRESH_DUE")

    def test_candidate_registry_keeps_one_current_record_per_asset(self):
        er_ref = add("ER:BABA", er())
        a3_ref = add("A3:BABA", a3_result(er_ref))
        registry = empty_candidate_registry("2026-09-22T21:00:00Z")
        registry = upsert_candidate(registry, candidate_record(a3_ref, er_ref), "2026-09-22T21:00:00Z")
        updated = candidate_record(a3_ref, er_ref)
        updated["thesis_status"] = "INTACT"
        registry = upsert_candidate(registry, updated, "2026-09-22T21:30:00Z")
        self.assertEqual(len(registry["candidates"]), 1)
        self.assertEqual(registry["candidates"]["US:BABA"]["thesis_status"], "INTACT")

    def test_missing_validated_er_blocks_a5(self):
        a3_ref = add("A3:BABA", a3_result(None))
        registry = empty_candidate_registry("2026-09-22T21:00:00Z")
        registry = upsert_candidate(registry, candidate_record(a3_ref, None), "2026-09-22T21:00:00Z")
        view = build_a5_candidate_view(registry, "US:BABA", resolver)
        self.assertEqual(view["status"], "BLOCKED_RESEARCH_ONLY")
        self.assertIn("MISSING_VALIDATED_ER", view["blockers"])

    def test_validated_hash_bound_er_reaches_read_only_a5_view(self):
        er_ref = add("ER:BABA", er())
        a3_ref = add("A3:BABA", a3_result(er_ref))
        registry = empty_candidate_registry("2026-09-22T21:00:00Z")
        registry = upsert_candidate(registry, candidate_record(a3_ref, er_ref), "2026-09-22T21:00:00Z")
        view = build_a5_candidate_view(registry, "US:BABA", resolver)
        self.assertEqual(view["status"], "READY_RESEARCH_ONLY")
        self.assertAlmostEqual(view["validated_er"]["12m"]["expected_alpha"], 0.20)
        self.assertTrue(view["portfolio_proposal_allowed"])
        self.assertFalse(view["target_book_write_allowed"])
        self.assertFalse(view["orders_allowed"])

    def test_a5_rejects_er_not_bound_to_a3(self):
        er_ref = add("ER:BABA", er())
        a3 = a3_result(er_ref)
        a3["validated_er_sha256"] = "f" * 64
        a3_ref = add("A3:BABA", a3)
        registry = empty_candidate_registry("2026-09-22T21:00:00Z")
        registry = upsert_candidate(registry, candidate_record(a3_ref, er_ref), "2026-09-22T21:00:00Z")
        with self.assertRaisesRegex(CandidateLifecycleError, "a5_er_hash_not_bound_to_a3"):
            build_a5_candidate_view(registry, "US:BABA", resolver)

    def test_cli_is_network_free_and_exposes_four_commands(self):
        import subprocess
        proc = subprocess.run(
            [sys.executable, str(ROOT / "tools" / "run_candidate_lifecycle_v1.py"), "--help"],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        for token in ("admit-event", "plan-refresh", "upsert-candidate", "build-a5-view"):
            self.assertIn(token, proc.stdout)

    def test_contract_matches_safety_boundary(self):
        contract = json.loads((ROOT / "docs" / "candidate_lifecycle_v1_contract.json").read_text())
        self.assertFalse(contract["candidate_registry"]["buy_sell_rank_target_weight_fields_allowed"])
        self.assertEqual(contract["event_policy"]["same_subject_family_dedup_hours"], 24)
        self.assertFalse(contract["a5_consumer"]["may_recreate_methodology_or_moat"])
        self.assertFalse(contract["authority"]["target_book_write_allowed"])
        self.assertFalse(contract["authority"]["new_scheduler_added"])


if __name__ == "__main__":
    unittest.main()
