from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from research.moat_bottleneck_diagnostic_v1 import BARRIERS, MoatDiagnosticError, evaluate

ASOF = "2026-10-12T21:00:00Z"
CUTOFF = "2026-10-13T12:00:00Z"


class Fixture:
    def __init__(self):
        self.raw: dict[tuple[str, str], bytes] = {}

    def add(self, artifact: str, payload: bytes) -> str:
        digest = hashlib.sha256(payload).hexdigest()
        self.raw[(artifact, digest)] = payload
        return digest

    def resolver(self, artifact: str, digest: str) -> bytes:
        return self.raw[(artifact, digest)]

    def make(self) -> dict:
        moat = {
            "schema": "moat-quality-v2-result",
            "status": "COMPLETE_RESEARCH_REVIEW",
            "asset_id": "US:MU", "issuer_id": "CIK:0000723125",
            "as_of": "2026-10-09T20:00:00Z",
            "reviewed_at": "2026-10-10T04:00:00Z",
            "packet_sha256": "a" * 64, "moat_quality_score": 0.64,
            "selector_eligible": False, "portfolio_weight_effect": 0.0,
            "orders_allowed": False, "oos_validated": False,
            "production_authority": False,
        }
        sha = self.add("MOAT_RESULT", json.dumps(moat).encode())
        evidence = []
        for n in range(6):
            eid = f"E{n}"
            evidence.append({
                "evidence_id": eid,
                "asset_id": "US:MU", "issuer_id": "CIK:0000723125",
                "observed_at": "2026-08-01T00:00:00Z",
                "published_at": "2026-08-02T00:00:00Z",
                "available_at": "2026-08-03T00:00:00Z",
                "collected_at": "2026-08-04T00:00:00Z",
                "verified_at": "2026-09-01T00:00:00Z",
                "valid_through": "2027-10-01T00:00:00Z",
                "direction": "SUPPORT" if n < 4 else "CHALLENGE",
                "source_affiliation": "INDEPENDENT",
                "independence_group": f"GROUP{n}",
                "artifact_id": f"RAW{n}",
                "sha256": self.add(f"RAW{n}", f"synthetic study source {n}".encode()),
                "claim": f"Fixture evidence {n}",
            })
        barriers = {}
        for i, name in enumerate(BARRIERS):
            barriers[name] = {
                "state": "EVIDENCED", "mechanism": f"Reviewed causal hypothesis for {name}",
                "counter_thesis": "A rival can substitute with later technology",
                "invalidation_conditions": ["Independent evidence reverses"],
                "evidence_ids": [f"E{i}"],
            }
        metrics = [
            {"name": "demand_growth_yoy_pct", "value": 25.0,
             "period_end": "2026-06-30", "basis": "same annual scope", "evidence_id": "E0"},
            {"name": "capacity_growth_yoy_pct", "value": 35.0,
             "period_end": "2026-06-30", "basis": "same annual scope", "evidence_id": "E1"},
            {"name": "roic_pct", "value": 16.2,
             "period_end": "2026-06-30", "basis": "same issuer economic model", "evidence_id": "E2"},
            {"name": "wacc_pct", "value": 11.4,
             "period_end": "2026-06-30", "basis": "same issuer economic model", "evidence_id": "E3"},
        ]
        return {
            "schema": "moat-bottleneck-causal-diagnostic-v1",
            "review_status": "RESEARCH_REVIEWED",
            "asset_id": "US:MU", "issuer_id": "CIK:0000723125",
            "as_of": ASOF, "reviewed_at": "2026-10-13T06:00:00Z",
            "moat_result_ref": {
                "artifact_id": "MOAT_RESULT", "sha256": sha,
                "available_at": "2026-10-10T08:00:00Z",
                "collected_at": "2026-10-11T00:00:00Z",
            },
            "evidence": evidence, "barriers": barriers, "metrics": metrics,
        }


class MoatCausalSmoke(unittest.TestCase):
    def setUp(self):
        self.fx = Fixture()
        self.packet = self.fx.make()

    def run_model(self, packet=None, cutoff=CUTOFF):
        return evaluate(self.packet if packet is None else packet, cutoff, self.fx.resolver)

    def fail(self, mutation, expected):
        p = copy.deepcopy(self.packet)
        mutation(p)
        with self.assertRaisesRegex(MoatDiagnosticError, expected):
            self.run_model(p)

    def test_scoped_complete_research_math_only(self):
        x = self.run_model()
        self.assertEqual(x["status"], "CAUSAL_DIAGNOSTIC_RESEARCH_ONLY")
        self.assertEqual(x["capacity_minus_demand_growth_pp"], 10)
        self.assertAlmostEqual(x["roic_minus_wacc_pp"], 4.8)
        self.assertEqual(x["moat_v2_score_unchanged"], 0.64)
        self.assertEqual(x["raw_artifact_count"], 7)
        self.assertIsNone(x.get("expected_alpha"))

    def test_explicit_zero_authority(self):
        x = self.run_model()
        for flag in ("source_authenticated", "historical_pit_certified", "oos_validated",
                     "selector_eligible", "er_eligible", "orders_allowed", "target_book_write_allowed"):
            self.assertIs(x[flag], False)
        self.assertEqual(x["portfolio_weight_effect"], 0)

    def test_determinism_and_no_input_mutation(self):
        original = copy.deepcopy(self.packet)
        self.assertEqual(self.run_model(), self.run_model())
        self.assertEqual(self.packet, original)

    def test_moat_subject_mismatch(self):
        self.fail(lambda p: p.update(issuer_id="CIK:OTHER"), "moat_subject_mismatch")

    def test_moat_hash_tamper(self):
        p = self.packet
        self.fx.raw[("MOAT_RESULT", p["moat_result_ref"]["sha256"])] = b"tamper"
        with self.assertRaisesRegex(MoatDiagnosticError, "raw_hash_mismatch"):
            self.run_model()

    def test_moat_future_reference_refused(self):
        self.fail(lambda p: p["moat_result_ref"].update(available_at="2026-11-01T00:00:00Z"),
                  "moat_future_or_clock")

    def test_future_cutoff(self):
        with self.assertRaisesRegex(MoatDiagnosticError, "future_review"):
            self.run_model(cutoff="2026-10-12T23:00:00Z")

    def test_future_evidence(self):
        self.fail(lambda p: p["evidence"][0].update(available_at="2027-01-01T00:00:00Z"),
                  "evidence_temporal_order")

    def test_expired_evidence(self):
        self.fail(lambda p: p["evidence"][0].update(valid_through="2026-10-11T00:00:00Z"),
                  "evidence_temporal_order")

    def test_duplicate_evidence(self):
        self.fail(lambda p: p["evidence"][1].update(evidence_id="E0"), "duplicate_evidence_id")

    def test_incomplete_source(self):
        self.fail(lambda p: p["evidence"].pop(0), "barrier_evidence_refs")

    def test_issuer_only_positive_not_admitted(self):
        self.fail(lambda p: p["evidence"][0].update(source_affiliation="ISSUER"),
                  "barrier_independent_support")

    def test_contested_requires_challenge(self):
        self.fail(lambda p: p["barriers"][BARRIERS[0]].update(state="CONTESTED"),
                  "barrier_two_sided_evidence")
        p = copy.deepcopy(self.packet)
        p["barriers"][BARRIERS[0]].update(state="CONTESTED", evidence_ids=["E0", "E4"])
        self.assertEqual(self.run_model(p)["barriers"][BARRIERS[0]]["state"], "CONTESTED")

    def test_unknown_cannot_claim_evidence(self):
        self.fail(lambda p: p["barriers"][BARRIERS[0]].update(state="UNKNOWN"),
                  "barrier_unknown_must_not_cite")
        p = copy.deepcopy(self.packet)
        p["barriers"][BARRIERS[0]].update(state="UNKNOWN", evidence_ids=[])
        self.assertEqual(self.run_model(p)["barriers"][BARRIERS[0]]["state"], "UNKNOWN")

    def test_missing_metric_returns_null_not_zero(self):
        p = copy.deepcopy(self.packet)
        p["metrics"] = [x for x in p["metrics"] if x["name"] != "wacc_pct"]
        out = self.run_model(p)
        self.assertIsNone(out["roic_minus_wacc_pp"])
        self.assertEqual(out["economic_spread_comparison_status"], "MISSING_INPUT")

    def test_mismatched_period_or_basis_refuses_arithmetic(self):
        p = copy.deepcopy(self.packet)
        p["metrics"][1]["period_end"] = "2026-03-31"
        out = self.run_model(p)
        self.assertIsNone(out["capacity_minus_demand_growth_pp"])
        self.assertEqual(out["capacity_demand_comparison_status"], "INCOMPARABLE_PERIOD_OR_BASIS")

    def test_boolean_nan_inf_metric_refused(self):
        for bad in (True, float("nan"), float("inf"), "1"):
            with self.subTest(bad=str(bad)):
                self.fail(lambda p: p["metrics"][0].update(value=bad), "metric_value")

    def test_metric_future_period_refused(self):
        self.fail(lambda p: p["metrics"][0].update(period_end="2027-01-01"),
                  "future_metric_period")

    def test_market_score_not_reweighted(self):
        p = copy.deepcopy(self.packet)
        p["barriers"][BARRIERS[0]]["state"] = "UNKNOWN"
        p["barriers"][BARRIERS[0]]["evidence_ids"] = []
        self.assertEqual(self.run_model(p)["moat_v2_score_unchanged"], 0.64)
        self.assertNotEqual(self.run_model()["packet_sha256"], self.run_model(p)["packet_sha256"])

    def test_double_artifact_identity_rejected(self):
        p = copy.deepcopy(self.packet)
        raw0 = p["evidence"][0]
        # The first alias resolves, but conflicts with RAW1's independent bytes.
        self.fx.raw[("RAW1", raw0["sha256"])] = self.fx.raw[("RAW0", raw0["sha256"])]
        raw0["artifact_id"] = "RAW1"
        with self.assertRaisesRegex(MoatDiagnosticError, "artifact_identity_conflict"):
            self.run_model(p)

    def test_raw_provider_failure_is_finite_and_redacted(self):
        self.fx.raw.clear()
        with self.assertRaisesRegex(MoatDiagnosticError, "raw_evidence_unavailable"):
            self.run_model()

    def test_unknown_dimensions_refused(self):
        self.fail(lambda p: p["barriers"].pop(BARRIERS[-1]), "barrier_set")

    def test_no_raw_evidence_unknown_only(self):
        p = copy.deepcopy(self.packet)
        p["evidence"] = []
        p["metrics"] = []
        for x in p["barriers"].values():
            x.update(state="UNKNOWN", evidence_ids=[])
        out = self.run_model(p)
        self.assertIsNone(out["capacity_minus_demand_growth_pp"])
        self.assertIsNone(out["roic_minus_wacc_pp"])
        self.assertFalse(out["oos_validated"])


if __name__ == "__main__":
    unittest.main()
