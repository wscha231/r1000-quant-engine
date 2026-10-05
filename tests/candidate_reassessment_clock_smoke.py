"""Row-clock regressions across unavailable/expired free-source observations.

Synthetic boundary tests only; no provider calls or economic execution.
"""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import candidate_reassessment_bridge as b

T0 = "2026-10-01T12:00:00Z"
T1 = "2026-10-02T12:00:00Z"
T2 = "2026-10-03T12:00:00Z"
LIVE_NOW = "2026-10-03T13:00:00Z"
EXPIRED_NOW = "2026-10-05T12:00:00Z"
EXPIRY = "2026-10-05T12:00:00Z"
INDEX_EXPIRY = "2026-10-06T12:00:00Z"
STATES = (
    "OBSERVED", "MISSING", "STALE", "FAILED",
    "UNKNOWN_IDENTITY", "UNKNOWN_PUBLICATION",
)
FAMILIES = ("ACTUAL", "MACRO", "OPTIONS", "SENTIMENT", "POSITIONING")
CONTRACT = {
    "code_sha": "a" * 40, "config_sha256": "b" * 64,
    "model_version": "synthetic-clock-review-only",
    "parameters_sha256": "c" * 64, "dependency_sha256": "d" * 64,
}


def row(*, family="ACTUAL", status="OBSERVED", available=T1,
        collected=T1, provider="synthetic_clock_fixture"):
    security = family == "ACTUAL"
    return {
        "family": family, "provider": provider,
        "entity_kind": "SECURITY" if security else "MACRO_SERIES",
        "entity_id": "XAAA" if security else "SYNTHETIC_CONTEXT",
        "metric": family + "_VALUE",
        "fiscal_period": "2026-09-30" if security else None,
        "observation_period": "2026-10-01",
        "identity": {"unit": "SYNTHETIC"}, "values": {"value": 10},
        "status": status, "available_at": available, "collected_at": collected,
        "revision_id": "v1", "source_sha256": "e" * 64,
        "causal_event_id": None,
    }


def index():
    return b.exposure_index(
        candidates=[{"asset_id": "XAAA", "issuer_id": "SEC:0000000001"},
                    {"asset_id": "XBBB", "issuer_id": "SEC:0000000002"}],
        edges=[{"entity_kind": "MACRO_SERIES", "entity_id": "SYNTHETIC_CONTEXT",
                "asset_id": "XAAA", "channels": ["RISK", "TIMING"],
                "evidence_sha256": "f" * 64, "available_at": T0}],
        available_at=T0, expires_at=INDEX_EXPIRY,
    )


def invoke(previous_rows, current_rows, *, api="free_first", now=LIVE_NOW):
    prior = None if previous_rows is None else b.snapshot(
        previous_rows, scope_id="synthetic-clock-complete-scope",
        cutoff=T1, expires_at=EXPIRY,
    )
    current = b.snapshot(
        current_rows, scope_id="synthetic-clock-complete-scope",
        cutoff=T2, expires_at=EXPIRY,
    )
    idx = index()
    kwargs = {"now": now, "contract_identity": CONTRACT,
              "previous_contract_identity": CONTRACT,
              "previous_index_sha256": idx["content_sha256"]}
    if api == "free_first":
        return b.free_first_review_plan(
            prior, current, idx,
            previous_profile_id=None if prior is None else b.FREE_FIRST_PROFILE,
            **kwargs,
        )["review_plan"]
    return b.plan_reassessment(prior, current, idx, **kwargs)


class ClockRegressionTests(unittest.TestCase):
    def test_backward_clocks_rejected_before_status_and_expiry(self):
        clocks = ((T0, T1), (T1, T0), (T0, T0))
        for family in FAMILIES:
            for state in STATES:
                for available, collected in clocks:
                    for now in (LIVE_NOW, EXPIRED_NOW):
                        for api in ("generic", "free_first"):
                            with self.subTest(family=family, state=state,
                                              available=available, collected=collected,
                                              expired=now == EXPIRED_NOW, api=api):
                                with self.assertRaisesRegex(b.ReassessmentError,
                                                            "^ROW_TIME_REGRESSION$"):
                                    invoke([row(family=family)],
                                           [row(family=family, status=state,
                                                available=available, collected=collected)],
                                           api=api, now=now)

    def test_monotone_unavailable_and_expired_rows_still_request_repair(self):
        for family in FAMILIES:
            for state in STATES:
                for available, collected in ((T1, T1), (T1, T2), (T2, T2)):
                    for now in (LIVE_NOW, EXPIRED_NOW):
                        for api in ("generic", "free_first"):
                            with self.subTest(family=family, state=state,
                                              available=available, collected=collected,
                                              expired=now == EXPIRED_NOW, api=api):
                                plan = invoke([row(family=family)],
                                              [row(family=family, status=state,
                                                   available=available, collected=collected)],
                                              api=api, now=now)
                                for name, value in b.CLOSED.items():
                                    self.assertEqual(plan[name], value)
                                if now == EXPIRED_NOW or state != "OBSERVED":
                                    reasons = {event["reason"] for event in plan["events"]}
                                    expected = ("SOURCE_EXPIRED" if now == EXPIRED_NOW
                                                else "SOURCE_" + state)
                                    self.assertIn(expected, reasons)
                                    self.assertTrue(plan["invalidations"])

    def test_equivalent_timezone_instants_remain_monotone(self):
        for state in STATES:
            for api in ("generic", "free_first"):
                with self.subTest(state=state, api=api):
                    plan = invoke([row()], [row(status=state,
                                  available="2026-10-02T21:00:00+09:00",
                                  collected="2026-10-02T08:00:00-04:00")], api=api)
                    self.assertFalse(plan["economic_admission"])

    def test_first_unavailable_observation_needs_no_previous_clock(self):
        for state in STATES[1:]:
            for api in ("generic", "free_first"):
                with self.subTest(state=state, api=api):
                    plan = invoke(None, [row(status=state, available=T0,
                                             collected=T0)], api=api)
                    self.assertIn("SOURCE_" + state,
                                  {event["reason"] for event in plan["events"]})
                    self.assertFalse(plan["economic_admission"])

    def test_new_provider_identity_is_not_compared_to_old_provider_clock(self):
        for state in STATES:
            for api in ("generic", "free_first"):
                with self.subTest(state=state, api=api):
                    plan = invoke([row()], [row(status=state, available=T0,
                                               collected=T0,
                                               provider="different_synthetic_provider")],
                                  api=api)
                    self.assertIn("MISSING_FROM_COMPLETE_SCOPE",
                                  {event["reason"] for event in plan["events"]})
                    self.assertFalse(plan["economic_admission"])

    def test_complete_scope_removal_still_requests_source_repair(self):
        for api in ("generic", "free_first"):
            with self.subTest(api=api):
                plan = invoke([row()], [], api=api)
                self.assertEqual({event["reason"] for event in plan["events"]},
                                 {"MISSING_FROM_COMPLETE_SCOPE"})
                self.assertFalse(plan["economic_admission"])


if __name__ == "__main__":
    unittest.main()
