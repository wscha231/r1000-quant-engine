"""Synthetic diagnostic fixtures; no actual Source/PIT/admission claims.

Run: python -B tests/research_risk_connection_smoke.py
and: python -B -O tests/research_risk_connection_smoke.py
"""
from __future__ import annotations

import copy
import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import candidate_reassessment_bridge as b
from tools import chameleon_market_context_v2 as c
from tools import research_risk_connection as connection
from tools import run287_hold_exit_policy as hp

CUTOFF = "2026-10-18T00:00:00Z"
EXPIRES = "2026-10-19T00:00:00Z"


def candidate_record():
    return dict(ticker="XAAA", alphaops_vnext_score=1.0, rs_benchmark_1w=-0.02,
                rs_benchmark_3m=0.30, price_above_ma50=0.0, price_above_ma200=1.0,
                leader_tier="DUAL_LEADER", rs_sector_3m=0.10,
                industry_group_strength_score=0.20, portfolio_risk_entry_block_score=0.10,
                portfolio_stale_mega_leader_score=0.0, emerging_tenbagger_hard_reject_reason="",
                top7_standalone_blocked=False, pit_evidence_blocked=False,
                primary_lane="MARKET_LEADER", sector="Tech", industry_group="Tech Group")


def request_fixture():
    raw = b"observation_date,DGS10\n2026-10-15,4.0\n2026-10-16,4.1\n"
    rows = c.macro_source_rows(raw, source_id="fred:DGS10", collected_at=CUTOFF, cutoff=CUTOFF)
    context = c.build_context(macro_rows=rows, public_rows=[], price_rows=[], calendar_result=None,
                              security_map=None, security_map_available_at=None,
                              cutoff=CUTOFF, expected_session="2026-10-16")
    index = b.exposure_index(candidates=[{"asset_id": "XAAA", "issuer_id": "ISSUER_XAAA"}],
                             edges=[dict(entity_kind="MACRO_SERIES", entity_id="yield_10y", asset_id="XAAA",
                                         channels=["RISK"], evidence_sha256="a" * 64, available_at=CUTOFF)],
                             available_at=CUTOFF, expires_at=EXPIRES)
    position = dict(ticker="XAAA", weight=0.2, sector="Tech", industry_group="Tech Group")
    return dict(macro_context=context, observed_at=CUTOFF,
                reassessment=dict(scope_id="synthetic-complete-macro-scope", expires_at=EXPIRES,
                                  index=index, contract_identity=dict(code_sha="35b36d289dbae9104042c2158532466076844f9b",
                                  config_sha256="b" * 64, model_version="existing-policy-diagnostic",
                                  parameters_sha256="c" * 64, dependency_sha256="d" * 64)),
                hold_policy=dict(portfolio="main", available_at=CUTOFF,
                                 incumbent=dict(record=candidate_record(), score_median=0.5, score_sigma=0.2,
                                                rs_percentile=0.95, lifecycle_terminal=False),
                                 challenger=dict(record=candidate_record(), lifecycle_terminal=False),
                                 concentration=dict(control_rows=[position], proposed_rows=[copy.deepcopy(position)])),
                company_research={"asset_id": "XAAA", "status": "PARTIAL_RESEARCH", "research_asset": {"moat": "retained"}})


class ConnectionTests(unittest.TestCase):
    def call(self, request=None, cutoff=CUTOFF):
        return connection.build_risk_connection(request_fixture() if request is None else request, cutoff=cutoff)

    def closed(self, result):
        for key in connection.AUTHORITY:
            self.assertIs(result[key], False, key)
        b.verify(result, connection.SCHEMA)

    def test_current_macro_executes_existing_functions_and_preserves_company(self):
        request = request_fixture()
        original = copy.deepcopy(request)
        result = self.call(request)
        self.assertEqual(result["status"], "RESEARCH_DIAGNOSTICS_ONLY")
        self.assertEqual(request, original)
        self.assertEqual(result["company_research"], original["company_research"])
        self.assertIsNot(result["company_research"], request["company_research"])
        calls = {row["function"] for row in result["call_trace"]}
        for module, function in ((c, "verify_context"), (b, "macro_rows_from_context"),
                                  (b, "plan_reassessment"), (b, "a0_parameter_proposals"),
                                  (hp, "incumbent_protection"), (hp, "challenger_eligible"),
                                  (hp, "concentration_not_worse")):
            self.assertIn(module.__name__ + "." + function, calls)
        for row in result["call_trace"]:
            self.assertEqual(len(row["input_sha256"]), 64)
            self.assertEqual(len(row["dependency_sha256"]), 64)
            self.assertEqual(row["status"], "RETURNED")
        self.closed(result)

    def test_existing_policy_output_parity(self):
        request = request_fixture()
        result = self.call(request)
        p = request["hold_policy"]
        incumbent = hp.incumbent_protection(**p["incumbent"], portfolio="main", policy=hp.LeadershipPersistencePolicy())
        challenger = hp.challenger_eligible(**p["challenger"], policy=hp.LeadershipPersistencePolicy())
        concentration = hp.concentration_not_worse(**p["concentration"], portfolio="main")
        for name, expected in (("incumbent", incumbent), ("challenger", challenger), ("concentration", concentration)):
            self.assertEqual(result["stages"][name]["result"]["existing_policy_result"], list(expected))

    def test_reassessment_output_parity_and_macro_risk_slice_only(self):
        request = request_fixture()
        result = self.call(request)["stages"]["reassessment"]["result"]
        p = request["reassessment"]
        rows = b.macro_rows_from_context(request["macro_context"], observed_at=CUTOFF)
        current = b.snapshot(rows, scope_id=p["scope_id"], cutoff=CUTOFF, expires_at=EXPIRES)
        plan = b.plan_reassessment(None, current, p["index"], now=CUTOFF, contract_identity=p["contract_identity"])
        self.assertEqual(result["snapshot"], current)
        self.assertEqual(result["plan"], plan)
        self.assertEqual(result["a0_parameter_proposals"], b.a0_parameter_proposals(plan))
        self.assertEqual(plan["invalidations"][0]["slices"], ["RISK_CONTEXT"])

    def test_normal_correction_and_short_rs_weakness_never_generate_sell(self):
        result = self.call()
        self.assertTrue(result["stages"]["incumbent"]["result"]["existing_policy_result"][0])
        self.assertNotIn("orders", result)
        self.assertNotIn("target_weights", result)
        self.closed(result)

    def test_missing_macro_retains_independent_policy_and_company(self):
        request = request_fixture()
        del request["macro_context"]
        result = self.call(request)
        self.assertEqual(result["stages"]["macro_context"]["status"], "BLOCKED")
        self.assertEqual(result["stages"]["reassessment"]["status"], "BLOCKED")
        self.assertEqual(result["stages"]["incumbent"]["status"], "DIAGNOSTIC_ONLY")
        self.assertEqual(result["company_research"], request["company_research"])
        self.closed(result)

    def test_missing_hold_input_keeps_macro_and_reassessment(self):
        request = request_fixture()
        del request["hold_policy"]
        result = self.call(request)
        self.assertEqual(result["stages"]["reassessment"]["status"], "DIAGNOSTIC_ONLY")
        self.assertEqual(result["stages"]["incumbent"]["status"], "BLOCKED")
        self.closed(result)

    def test_stale_current_context_blocks_freshness_and_requests_source_repair(self):
        request = request_fixture()
        request["reassessment"]["expires_at"] = "2026-11-01T00:00:00Z"
        request["reassessment"]["index"] = b.exposure_index(candidates=request["reassessment"]["index"]["candidates"],
                    edges=request["reassessment"]["index"]["edges"], available_at=CUTOFF, expires_at="2026-11-01T00:00:00Z")
        result = self.call(request, cutoff="2026-10-24T00:00:00Z")
        macro = result["stages"]["macro_context"]
        self.assertEqual(macro["status"], "BLOCKED")
        self.assertEqual(macro["result"]["rows"][0]["status"], "STALE")
        plan = result["stages"]["reassessment"]["result"]["plan"]
        self.assertEqual(plan["invalidations"][0]["status"], "DATA_REPAIR_REQUIRED")
        self.assertNotIn("A5", {item["agent"] for item in plan["review_intents"]})
        self.closed(result)

    def test_future_context_and_observed_time_rejected(self):
        for key in ("cutoff", "observed_at"):
            request = request_fixture()
            if key == "cutoff":
                request["macro_context"]["cutoff"] = EXPIRES
                request["macro_context"]["content_sha256"] = c.digest({k: v for k, v in request["macro_context"].items() if k != "content_sha256"})
            else:
                request[key] = EXPIRES
            self.assertEqual(self.call(request)["stages"]["macro_context"]["status"], "BLOCKED")

    def test_tampered_hash_rejected(self):
        request = request_fixture()
        request["macro_context"]["macro"]["yield_10y"]["value"] = 99
        result = self.call(request)
        self.assertEqual(result["stages"]["macro_context"]["reasons"], ["CONTEXT_HASH"])
        self.closed(result)

    def test_future_source_with_rebound_context_hash_rejected(self):
        request = request_fixture()
        context = request["macro_context"]
        context["macro"]["yield_10y"]["available_at"] = EXPIRES
        context["content_sha256"] = c.digest({k: v for k, v in context.items() if k != "content_sha256"})
        self.assertEqual(self.call(request)["stages"]["macro_context"]["reasons"], ["FUTURE_MACRO_EVIDENCE"])

    def test_unknown_never_becomes_green_or_permission(self):
        request = request_fixture()
        context = request["macro_context"]
        context["macro"]["yield_10y"]["status"] = "UNKNOWN"
        context["content_sha256"] = c.digest({k: v for k, v in context.items() if k != "content_sha256"})
        result = self.call(request)
        self.assertEqual(result["stages"]["macro_context"]["status"], "BLOCKED")
        self.closed(result)
        empty = self.call({})
        self.assertEqual(empty["status"], "BLOCKED")
        self.closed(empty)

    def test_unknown_risk_or_identity_does_not_default_to_clear(self):
        for field in ("pit_evidence_blocked", "top7_standalone_blocked", "sector", "primary_lane"):
            request = request_fixture()
            del request["hold_policy"]["challenger"]["record"][field]
            result = self.call(request)
            self.assertEqual(result["stages"]["challenger"]["status"], "BLOCKED")
            self.assertEqual(result["stages"]["incumbent"]["status"], "DIAGNOSTIC_ONLY")

    def test_frozen_policy_parameter_override_rejected(self):
        for target in ("root", "hold", "incumbent"):
            request = request_fixture()
            selected = request if target == "root" else request["hold_policy"] if target == "hold" else request["hold_policy"]["incumbent"]
            selected["risk_block_ceiling"] = 0.99
            result = self.call(request)
            self.assertEqual(result["stages"]["incumbent"]["status"], "BLOCKED")
            self.closed(result)

    def test_nonfinite_and_numeric_boolean_rejected(self):
        for value in (math.nan, math.inf, -math.inf, True):
            request = request_fixture()
            request["hold_policy"]["incumbent"]["score_sigma"] = value
            result = self.call(request)
            self.assertEqual(result["stages"]["incumbent"]["status"], "BLOCKED")
            self.closed(result)

    def test_future_policy_evidence_and_missing_exposure_rejected(self):
        request = request_fixture()
        request["hold_policy"]["available_at"] = EXPIRES
        self.assertEqual(self.call(request)["stages"]["incumbent"]["status"], "BLOCKED")
        request = request_fixture()
        request["hold_policy"]["concentration"]["proposed_rows"][0]["sector"] = "UNKNOWN"
        self.assertEqual(self.call(request)["stages"]["concentration"]["status"], "BLOCKED")

    def test_nonempty_evidence_and_lifecycle_boolean_required(self):
        request = request_fixture()
        request["hold_policy"]["challenger"]["lifecycle_terminal"] = "false"
        self.assertEqual(self.call(request)["stages"]["challenger"]["status"], "BLOCKED")
        request = request_fixture()
        request["hold_policy"]["concentration"]["control_rows"] = []
        self.assertEqual(self.call(request)["stages"]["concentration"]["status"], "BLOCKED")

    def test_no_automatic_sell_when_existing_policy_returns_not_protected(self):
        request = request_fixture()
        request["hold_policy"]["incumbent"]["record"]["rs_benchmark_3m"] = -0.1
        result = self.call(request)
        self.assertFalse(result["stages"]["incumbent"]["result"]["existing_policy_result"][0])
        self.closed(result)

    def test_repeat_is_deterministic_and_hash_bound(self):
        first, second = self.call(), self.call()
        self.assertEqual(first, second)
        second["company_research"]["status"] = "CHANGED"
        with self.assertRaises(b.ReassessmentError):
            b.verify(second, connection.SCHEMA)

    def test_invalid_policy_json_preserves_macro_and_company(self):
        request = request_fixture()
        request["hold_policy"]["incumbent"]["score_sigma"] = math.nan
        result = self.call(request)
        self.assertEqual(result["stages"]["incumbent"]["status"], "BLOCKED")
        self.assertEqual(result["stages"]["macro_context"]["status"], "DIAGNOSTIC_ONLY")
        self.assertEqual(result["company_research"], request["company_research"])
        self.closed(result)

    def test_invalid_cutoff_returns_bounded_closed_result(self):
        for cutoff in (None, 123, math.nan, "invalid", "x" * 5000):
            result = self.call({}, cutoff=cutoff)
            self.assertEqual(result["status"], "BLOCKED")
            self.assertIsNone(result["cutoff"])
            self.closed(result)

    def test_mixed_company_prior_scope_blocks_only_reassessment(self):
        request = request_fixture()
        rows = b.macro_rows_from_context(request["macro_context"], observed_at=CUTOFF)
        company_row = copy.deepcopy(rows[0])
        company_row.update(family="ACTUAL", entity_kind="SECURITY", entity_id="XAAA", metric="EPS",
                           fiscal_period="2026-06-30", values={"value": 2.0})
        p = request["reassessment"]
        p["previous_snapshot"] = b.snapshot(rows + [company_row], scope_id=p["scope_id"],
                                            cutoff=CUTOFF, expires_at=EXPIRES)
        result = self.call(request)
        self.assertEqual(result["stages"]["reassessment"]["status"], "BLOCKED")
        self.assertEqual(result["stages"]["reassessment"]["reasons"], ["PRIOR_SCOPE_NOT_MACRO_ONLY"])
        self.assertIsNone(result["stages"]["reassessment"]["result"])
        self.assertEqual(result["stages"]["macro_context"]["status"], "DIAGNOSTIC_ONLY")
        self.assertEqual(result["stages"]["incumbent"]["status"], "DIAGNOSTIC_ONLY")
        self.assertEqual(result["company_research"], request["company_research"])
        self.assertNotIn(b.__name__ + ".plan_reassessment", {row["function"] for row in result["call_trace"]})
        self.closed(result)

    def test_normal_macro_and_options_prior_scope_remains_accepted(self):
        request = request_fixture()
        macro_rows = c.macro_source_rows(b"observation_date,DGS10\n2026-10-16,4.1\n",
                                        source_id="fred:DGS10", collected_at=CUTOFF, cutoff=CUTOFF)
        macro_rows += c.macro_source_rows(b"observation_date,VIXCLS\n2026-10-16,20\n",
                                         source_id="fred:VIXCLS", collected_at=CUTOFF, cutoff=CUTOFF)
        request["macro_context"] = c.build_context(macro_rows=macro_rows, public_rows=[], price_rows=[],
                                      calendar_result=None, security_map=None, security_map_available_at=None,
                                      cutoff=CUTOFF, expected_session="2026-10-16")
        rows = b.macro_rows_from_context(request["macro_context"], observed_at=CUTOFF)
        self.assertEqual({row["family"] for row in rows}, {"MACRO", "OPTIONS"})
        p = request["reassessment"]
        p["previous_snapshot"] = b.snapshot(rows, scope_id=p["scope_id"], cutoff=CUTOFF, expires_at=EXPIRES)
        p["previous_contract_identity"] = p["contract_identity"]
        p["previous_index_sha256"] = p["index"]["content_sha256"]
        result = self.call(request)
        self.assertEqual(result["stages"]["reassessment"]["status"], "DIAGNOSTIC_ONLY")
        self.assertEqual(result["stages"]["reassessment"]["result"]["plan"]["invalidations"], [])
        self.closed(result)

    def test_macro_prior_seal_validation_is_preserved(self):
        request = request_fixture()
        rows = b.macro_rows_from_context(request["macro_context"], observed_at=CUTOFF)
        p = request["reassessment"]
        p["previous_snapshot"] = b.snapshot(rows, scope_id=p["scope_id"], cutoff=CUTOFF, expires_at=EXPIRES)
        p["previous_snapshot"]["rows"][0]["values"] = {"value": 99}
        result = self.call(request)
        self.assertEqual(result["stages"]["reassessment"]["reasons"], ["CONTENT_HASH"])
        self.assertEqual(result["company_research"], request["company_research"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
