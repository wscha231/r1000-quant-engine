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



class ContractIdentityBoundaryTests(unittest.TestCase):
    # Independent expected computation slices; P0 source authentication remains a separate gate.
    required_slices = {'EARNINGS', 'CASHFLOW', 'VALUATION', 'EXPECTED_RETURN', 'RS_PATH',
                       'TIMING', 'RISK_CONTEXT', 'THESIS_RISK', 'COMPETITIVE_POSITION',
                       'FULL_EARNINGS_THESIS_REVIEW', 'FILING_CONTENT_REVIEW', 'ACTUALS_EXTRACTION_REVIEW'}

    def make_plan(self, *, api='generic', field=None, index_changed=False, unknown_prior=False,
                  current_rows=None, prior_rows=None):
        rows = [row()] if prior_rows is None else prior_rows
        prior = b.snapshot(rows, scope_id='contract-boundary', cutoff=T1, expires_at=EXPIRY)
        current = b.snapshot(rows if current_rows is None else current_rows, scope_id='contract-boundary',
                             cutoff=T2, expires_at=EXPIRY)
        idx = index(); contract = b.clean(CONTRACT)
        if field is not None:
            contract[field] = 'new-model' if field == 'model_version' else ('9'*40 if field=='code_sha' else '9'*64)
        before = b.digest([prior,current,idx,contract])
        kwargs = {'now':LIVE_NOW, 'contract_identity':contract,
                  'previous_contract_identity':None if unknown_prior else CONTRACT,
                  'previous_index_sha256':'8'*64 if index_changed else idx['content_sha256']}
        if api=='generic': result = b.plan_reassessment(prior,current,idx,**kwargs)
        else:
            result = b.free_first_review_plan(prior,current,idx,previous_profile_id=b.FREE_FIRST_PROFILE,**kwargs)['review_plan']
        if before != b.digest([prior,current,idx,contract]):
            raise RuntimeError('Caller input mutation')
        return result

    def assert_full(self, result):
        expected_assets = {'XAAA','XBBB'}
        self.assertEqual({row['asset_id'] for row in result['invalidations']}, expected_assets)
        a3 = next(intent for intent in result['review_intents'] if intent['agent']=='A3')
        self.assertEqual(set(a3['asset_slices']), expected_assets)
        for invalidation in result['invalidations']:
            self.assertTrue(self.required_slices <= set(invalidation['slices']), invalidation)
            self.assertTrue(self.required_slices <= set(a3['asset_slices'][invalidation['asset_id']]))
        for key,value in b.CLOSED.items(): self.assertEqual(result[key],value)
        self.assertEqual(len(result['review_intents']),len({intent['agent'] for intent in result['review_intents']}))
        b.a0_parameter_proposals(result)

    def test_every_generic_contract_field_change_requires_full_candidate_reassessment(self):
        for api in ('generic','free_first'):
            for field in ('code_sha','config_sha256','model_version','parameters_sha256','dependency_sha256'):
                with self.subTest(api=api,field=field): self.assert_full(self.make_plan(api=api,field=field))

    def test_unknown_prior_contract_and_unscoped_index_change_do_not_reuse_thesis_slices(self):
        for api in ('generic','free_first'):
            for change in ('unknown_prior','index_changed'):
                with self.subTest(api=api,change=change): self.assert_full(self.make_plan(api=api,**{change:True}))

    def test_unchanged_contract_and_narrow_price_event_remain_selective(self):
        for api in ('generic','free_first'):
            with self.subTest(api=api):
                unchanged = self.make_plan(api=api)
                self.assertEqual(unchanged['status'],'NO_NEW_REVIEW_INTENT')
                self.assertEqual(unchanged['invalidations'],[])
                prior = row(family='PRICE'); prior.update(entity_kind='SECURITY',entity_id='XAAA')
                current = b.clean(prior);current['values']={'value':11};current['available_at']=T2;current['collected_at']=T2
                selective = self.make_plan(api=api,prior_rows=[prior],current_rows=[current])
                self.assertEqual(selective['invalidations'][0]['slices'],['EXPECTED_RETURN','RS_PATH','TIMING','VALUATION'])
                for key,value in b.CLOSED.items():self.assertEqual(selective[key],value)

    def test_contract_change_without_observation_rows_still_revokes_current_candidates(self):
        for api in ('generic','free_first'):
            with self.subTest(api=api):
                self.assert_full(self.make_plan(api=api,field='model_version',prior_rows=[],current_rows=[]))


class SecAccessionSubmissionBoundaryTests(unittest.TestCase):
    def test_third_party_submitter_prefix_keeps_issuer_binding_and_existing_guards(self):
        import hashlib
        import json
        # Official issuer/accession pair; other values/clocks are a constructed
        # metadata fixture, not downloaded submissions or authenticated PIT.
        cik='0002063196'; accession='0001193125-26-255439'
        payload={'cik':2063196,'filings':{'recent':{
            'accessionNumber':[accession],'form':['8-K'],'filingDate':['2026-06-03'],
            'reportDate':['2026-06-03'],'acceptanceDateTime':['2026-06-03T20:00:00Z'],
            'primaryDocument':['synthetic-agent-filed.htm'],'items':['2.02']}}}
        raw=json.dumps(payload,separators=(',',':')).encode()
        options={'expected_sha256':hashlib.sha256(raw).hexdigest(),'expected_cik':cik,
                 'issuer_id':'SEC:'+cik,'accessions':[accession],
                 'observed_at':T0,'collected_at':T1,'cutoff':T2}
        rows=b.sec_submission_filing_rows(raw,**options)
        self.assertNotEqual(accession[:10],cik)
        self.assertEqual(rows[0]['identity']['cik'],cik)
        self.assertEqual(rows[0]['identity']['accession_number'],accession)
        self.assertEqual(rows[0]['entity_id'],'SEC:'+cik)
        self.assertIsNone(rows[0]['values']['actual_financial_values'])
        self.assertIsNone(rows[0]['values']['guidance_values'])
        self.assertIsNone(rows[0]['values']['provider_published_at'])
        self.assertEqual(b.stamp(rows[0]['available_at']),b.stamp(T1))
        snap=b.snapshot(rows,scope_id='agent-filing-metadata',cutoff=T2,expires_at=EXPIRY)
        self.assertFalse(snap['source_authenticated'])
        for changed,reason in (({'expected_cik':'0000000001'},'CIK_MISMATCH'),
                               ({'expected_sha256':'0'*64},'RAW_HASH'),
                               ({'accessions':['0001193125-26-255440']},'ACCESSION_NOT_IN_RECENT')):
            with self.subTest(reason=reason),self.assertRaisesRegex(b.ReassessmentError,reason):
                b.sec_submission_filing_rows(raw,**{**options,**changed})

if __name__ == "__main__":
    unittest.main()
