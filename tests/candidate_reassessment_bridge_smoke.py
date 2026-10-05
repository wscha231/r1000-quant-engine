"""Author regression tests; synthetic evidence, no market/CI/A6 certification."""
import copy
from datetime import datetime,timedelta,timezone
import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT)]
from tools import candidate_reassessment_bridge as b

T='2026-10-04T12:00:00Z'; LATER='2026-10-04T13:00:00Z'; EXP='2026-10-05T12:00:00Z'
H='a'*64
CONTRACT=dict(code_sha='b'*40,config_sha256='c'*64,model_version='research-only-v1',parameters_sha256='d'*64,dependency_sha256='e'*64)

def row(**kw):
 d=dict(family='CONSENSUS',provider='test',entity_kind='SECURITY',entity_id='AAA',metric='EPS',
        fiscal_period='2026-12-31',observation_period='2026-10-04',identity={'basis':'ADJUSTED','unit':'USD_PER_SHARE'},
        values={'value':10.0},status='OBSERVED',available_at=T,collected_at=T,revision_id='v1',source_sha256=H,causal_event_id=None)
 d.update(kw);return d

def snap(rows=None,**kw):
 args=dict(scope_id='SYNTHETIC_US_SCOPE',cutoff=T,expires_at=EXP);args.update(kw)
 return b.snapshot([row()] if rows is None else rows,**args)

def idx(edges=None):
 return b.exposure_index(candidates=[{'asset_id':'AAA','issuer_id':'CIK1'},{'asset_id':'BBB','issuer_id':'CIK1'},{'asset_id':'CCC','issuer_id':'CIK2'}],
         edges=edges or [],available_at=T,expires_at=EXP)

def edge(entity='yield_10y',asset='AAA',channels=None):
 return dict(entity_kind='MACRO_SERIES',entity_id=entity,asset_id=asset,channels=channels or ['VALUATION'],evidence_sha256=H,available_at=T)

def plan(a=None,c=None,i=None,**kw):
 i=i or idx()
 # Changed synthetic responses are observed in the next hourly test interval.
 if a is not None and c is not None and a!=c and a['cutoff']==c['cutoff']==T:
  rows=[{**r,'available_at':LATER,'collected_at':LATER} for r in c['rows']]
  c=snap(rows,scope_id=c['scope_id'],cutoff=LATER,expires_at=c['expires_at'])
  kw.setdefault('now',LATER)
 args=dict(now=T,contract_identity=CONTRACT,previous_contract_identity=CONTRACT,
                       previous_index_sha256=i['content_sha256']);args.update(kw)
 return b.plan_reassessment(a,c or snap(),i,**args)

def intent(p,agent):return next((r for r in p['review_intents'] if r['agent']==agent),None)

class BridgeTests(unittest.TestCase):
 def test_same_input_no_review(self):
  s=snap();self.assertEqual(plan(s,s)['review_intents'],[])
 def test_transport_only_no_review(self):
  a=snap();c=snap([row(source_sha256='f'*64,collected_at=LATER,available_at=LATER)],cutoff=LATER)
  self.assertEqual(plan(a,c,now=LATER)['status'],'NO_NEW_REVIEW_INTENT')
 def test_daily_same_consensus_no_new_ai_work(self):
  a=snap();nt='2026-10-05T11:00:00Z';c=snap([row(observation_period='2026-10-05',available_at=nt,collected_at=nt)],cutoff=nt,expires_at='2026-10-06T12:00:00Z')
  self.assertEqual(plan(a,c,now=nt)['events'],[])
 def test_eps_change_selective(self):
  p=plan(snap(),snap([row(values={'value':8.0})]));self.assertEqual(intent(p,'A3')['asset_ids'],['AAA']);self.assertIn('EXPECTED_RETURN',intent(p,'A3')['slices'])
 def test_actual_triggers_full_thesis(self):
  p=plan(None,snap([row(family='ACTUAL')]));self.assertIn('FULL_EARNINGS_THESIS_REVIEW',intent(p,'A3')['slices'])
 def test_guidance_no_forced_trade(self):
  p=plan(None,snap([row(family='GUIDANCE')]));self.assertFalse(p['orders_allowed']);self.assertFalse(intent(p,'A5')['execute'])
 def test_actual_issuer_maps_share_classes(self):
  p=plan(None,snap([row(family='ACTUAL',entity_kind='ISSUER',entity_id='CIK1')]))
  self.assertEqual(intent(p,'A3')['asset_ids'],['AAA','BBB'])
 def test_new_candidate_not_dropped(self):
  p=plan(None,snap([row(entity_id='NEW')]))
  self.assertIn('IDENTITY_DISCOVERY_NO_EXCLUSION',intent(p,'A2')['slices']);self.assertTrue(p['unmapped_event_ids'])
 def test_macro_cashflow_map(self):
  r=row(family='MACRO',entity_kind='MACRO_SERIES',entity_id='yield_10y',fiscal_period=None)
  p=plan(None,snap([r]),idx([edge(channels=['CASHFLOW','VALUATION'])]))
  self.assertTrue(intent(p,'A4')['global_review']);self.assertEqual(intent(p,'A3')['asset_ids'],['AAA']);self.assertIn('CASHFLOW',intent(p,'A3')['slices'])
 def test_macro_no_map_no_fabricated_company_er(self):
  p=plan(None,snap([row(family='MACRO',entity_kind='MACRO_SERIES',entity_id='yield_10y')]))
  self.assertIsNone(intent(p,'A3'));self.assertIn('EXPOSURE_MAP_REVIEW',intent(p,'A4')['slices']);self.assertTrue(intent(p,'A5')['global_review'])
 def test_regime_does_not_change_cashflow(self):
  r=row(family='REGIME',entity_kind='MACRO_SERIES',entity_id='yield_10y')
  p=plan(None,snap([r]),idx([edge(channels=['CASHFLOW'])]));self.assertNotIn('CASHFLOW',intent(p,'A3')['slices'])
 def test_option_context_not_valuation(self):
  r=row(family='OPTIONS',entity_kind='MACRO_SERIES',entity_id='yield_10y')
  p=plan(None,snap([r]),idx([edge()]));self.assertEqual(set(intent(p,'A3')['slices']),{'RISK_CONTEXT','TIMING'})
 def test_price_preserves_company_research(self):
  p=plan(None,snap([row(family='PRICE')]));self.assertIn('RS_PATH',intent(p,'A3')['slices']);self.assertNotIn('CASHFLOW',intent(p,'A3')['slices'])
 def test_same_value_new_macro_period_review(self):
  r=row(family='MACRO',entity_kind='MACRO_SERIES',entity_id='yield_10y',observation_period='2026-10-02')
  p=plan(snap([r]),snap([{**r,'observation_period':'2026-10-03'}]),idx([edge()]));self.assertEqual(p['events'][0]['reason'],'NEW_OBSERVATION')
 def test_revision_even_same_value(self):
  p=plan(snap(),snap([row(revision_id='v2')]));self.assertEqual(p['events'][0]['reason'],'CORRECTION')
 def test_zero_and_missing_different(self):
  p=plan(snap([row(values={'value':0.0})]),snap([row(values={'value':None},status='MISSING')]))
  self.assertIsNone(intent(p,'A3'));self.assertEqual(p['invalidations'][0]['status'],'DATA_REPAIR_REQUIRED')
 def test_negative_eps_no_percentage_fabrication(self):
  p=plan(snap([row(values={'value':-2})]),snap([row(values={'value':-1})]));self.assertFalse(p['er_calculated'])
 def test_missing_from_scope_not_hold(self):
  p=plan(snap(),snap([]));self.assertEqual(p['events'][0]['reason'],'MISSING_FROM_COMPLETE_SCOPE');self.assertIsNone(intent(p,'A5'))
 def test_expiry_unchanged_does_not_skip(self):
  s=snap(expires_at=LATER);p=plan(s,s,now=LATER)
  self.assertEqual(p['events'][0]['reason'],'SOURCE_EXPIRED');self.assertIsNone(intent(p,'A3'))
 def test_failure_blocks_economic_review(self):
  p=plan(snap(),snap([row(status='FAILED')]))
  self.assertIsNone(intent(p,'A3'));self.assertIsNotNone(intent(p,'A6'))
 def test_fiscal_roll_not_revision(self):
  p=plan(snap(),snap([row(fiscal_period='2027-12-31')]))
  self.assertNotIn('VALUE_OR_STATUS_CHANGED',[e['reason'] for e in p['events']])
 def test_provider_change_not_revision(self):
  p=plan(snap(),snap([row(provider='other')]))
  self.assertNotIn('VALUE_OR_STATUS_CHANGED',[e['reason'] for e in p['events']])
 def test_identity_conflict_not_cross_join(self):
  p=plan(snap(),snap([row(identity={'basis':'GAAP','unit':'EUR'})]))
  self.assertNotIn('VALUE_OR_STATUS_CHANGED',[e['reason'] for e in p['events']])
 def test_macro_observation_regression_repair(self):
  r=row(family='MACRO');p=plan(snap([r]),snap([{**r,'observation_period':'2026-10-02'}]));self.assertEqual(p['events'][0]['reason'],'OBSERVATION_REGRESSION')
 def test_future_cutoff_rejected(self):
  with self.assertRaises(b.ReassessmentError):plan(None,snap(cutoff=LATER))
 def test_future_row_rejected(self):
  with self.assertRaises(b.ReassessmentError):snap([row(available_at=LATER)])
 def test_naive_time_rejected(self):
  with self.assertRaises(b.ReassessmentError):snap(cutoff='2026-10-04T12:00:00')
 def test_same_time_conflicting_vintage_rejected(self):
  a=snap();i=idx()
  for equivalent_time in (T,'2026-10-04T12:00:00+00:00','2026-10-04T21:00:00+09:00'):
   c=snap([row(values={'value':8},available_at=equivalent_time,collected_at=equivalent_time)])
   with self.subTest(equivalent_time=equivalent_time), self.assertRaises(b.ReassessmentError):
    b.plan_reassessment(a,c,i,now=T,contract_identity=CONTRACT,previous_contract_identity=CONTRACT,previous_index_sha256=i['content_sha256'])
 def test_row_collection_regression_rejected(self):
  a=snap([row(collected_at=LATER,available_at=LATER)],cutoff=LATER)
  c=snap([row(values={'value':8})],cutoff=LATER);i=idx()
  with self.assertRaises(b.ReassessmentError):b.plan_reassessment(a,c,i,now=LATER,contract_identity=CONTRACT,previous_contract_identity=CONTRACT,previous_index_sha256=i['content_sha256'])
 def test_forged_hash_rejected(self):
  s=snap();s['rows'][0]['values']['value']=11
  with self.assertRaises(b.ReassessmentError):plan(None,s)
 def test_duplicate_row_rejected(self):
  with self.assertRaises(b.ReassessmentError):snap([row(),row()])
 def test_changed_scope_reaudit(self):
  with self.assertRaises(b.ReassessmentError):plan(snap(),snap(scope_id='different'))
 def test_contract_change_invalidation(self):
  s=snap();p=plan(s,s,previous_contract_identity={**CONTRACT,'model_version':'other'})
  self.assertEqual(intent(p,'A3')['asset_ids'],['AAA','BBB','CCC'])
 def test_index_change_invalidation(self):
  s=snap();p=plan(s,s,previous_index_sha256='f'*64);self.assertEqual(len(p['invalidations']),3)
 def test_missing_previous_identity_never_skip(self):
  s=snap();p=plan(s,s,previous_contract_identity=None);self.assertTrue(p['events'])
 def test_reversed_input_order_equal(self):
  a=snap([row(),row(entity_id='BBB')]);c=snap(list(reversed(a['rows'])))
  self.assertEqual(a,c);self.assertEqual(plan(None,a),plan(None,c))
 def test_deterministic_repeated_plan(self):self.assertEqual(plan(),plan())
 def test_input_not_mutated(self):
  a=snap();i=idx();before=copy.deepcopy((a,i));plan(a,a,i);self.assertEqual(before,(a,i))
 def test_max_one_request_per_agent(self):
  p=plan(None,snap([row(),row(entity_id='BBB')]))
  self.assertEqual(len(p['review_intents']),len({r['agent'] for r in p['review_intents']}))
 def test_simultaneous_earnings_and_macro_coalesced(self):
  rows=[row(),row(family='MACRO',entity_kind='MACRO_SERIES',entity_id='yield_10y',fiscal_period=None)]
  p=plan(None,snap(rows),idx([edge()]));a3=intent(p,'A3')
  self.assertEqual(a3['asset_ids'],['AAA']);self.assertEqual(len(a3['event_ids']),2)
  self.assertEqual(sum(r['agent']=='A3' for r in p['review_intents']),1)
  mixed=plan(None,snap([row(),row(family='PRICE',entity_id='CCC')]))
  scopes=intent(mixed,'A3')['asset_slices']
  self.assertIn('CASHFLOW',scopes['AAA']);self.assertNotIn('CASHFLOW',scopes['CCC'])
  self.assertIn('RS_PATH',scopes['CCC']);self.assertNotIn('RS_PATH',scopes['AAA'])
 def test_forged_intent_authority_rejected(self):
  p=plan();p['review_intents'][0]['execute']=True;p=b.seal({k:v for k,v in p.items() if k!='content_sha256'})
  with self.assertRaises(b.ReassessmentError):b.a0_parameter_proposals(p)
 def test_all_authority_closed(self):
  p=plan();self.assertTrue(all(p[k] is False for k in b.CLOSED))
 def test_a0_proposal_not_receipt(self):
  p=plan();out=b.a0_parameter_proposals(p)
  self.assertEqual(out['A3']['candidate_reassessment']['plan_sha256'],p['content_sha256'])
  self.assertNotIn('completed_tasks',out)
 def test_a0_cannot_promote_boolean(self):
  p=plan();p['execute']=True;p=b.seal({k:v for k,v in p.items() if k!='content_sha256'})
  with self.assertRaises(b.ReassessmentError):b.a0_parameter_proposals(p)
 def test_due_catalyst_even_unchanged(self):
  s=snap();p=plan(s,s,due_events=[due('CATALYST_DUE')]);self.assertTrue(p['events'])
 def test_outcome_matured_only_a8(self):
  s=snap();p=plan(s,s,due_events=[due('OUTCOME_MATURED')]);self.assertEqual([r['agent'] for r in p['review_intents']],['A8'])
 def test_future_outcome_rejected(self):
  with self.assertRaises(b.ReassessmentError):plan(due_events=[{**due('OUTCOME_MATURED'),'due_at':LATER}])
 def test_hard_risk_not_waiting_on_stale_price(self):
  p=plan(None,snap([row(status='STALE')]),due_events=[due('HARD_RISK_REVIEW')])
  self.assertIn('P0_VERIFICATION_NO_RS_WAIT',intent(p,'A6')['slices'])
 def test_duplicate_due_rejected(self):
  d=due('CATALYST_DUE')
  with self.assertRaises(b.ReassessmentError):plan(due_events=[d,d])
 def test_nan_rejected(self):
  with self.assertRaises(b.ReassessmentError):snap([row(values={'value':float('nan')})])
 def test_unknown_channels_rejected(self):
  with self.assertRaises(b.ReassessmentError):idx([edge(channels=['BUY'])])
 def test_future_index_edge_rejected(self):
  with self.assertRaises(b.ReassessmentError):idx([{**edge(),'available_at':LATER}])
 def test_duplicate_index_asset_rejected(self):
  with self.assertRaises(b.ReassessmentError):b.exposure_index(candidates=[{'asset_id':'A','issuer_id':'I'}]*2,edges=[],available_at=T,expires_at=EXP)
 def test_index_expiry_rejected(self):
  with self.assertRaises(b.ReassessmentError):plan(now=EXP)
 def test_no_source_hash_inference(self):
  with self.assertRaises(b.ReassessmentError):snap([row(source_sha256=None)])
 def test_payload_depth_bounded(self):
  d={};ptr=d
  for _ in range(26):ptr['a']={};ptr=ptr['a']
  with self.assertRaises(b.ReassessmentError):b.clean(d)

def due(kind):return dict(event_id='synthetic-due',kind=kind,entity_kind='SECURITY',entity_id='AAA',due_at=T,evidence_sha256=H)

class ProducerIntegrationTests(unittest.TestCase):
 def test_calendar_actual_c1_h1_to_review(self):
  payload=calendar_payload(10)
  rows=b.calendar_rows(payload,['AAA.US'],observed_at=T,collected_at=T)
  s=snap(rows);changed=b.calendar_rows(calendar_payload(8),['AAA.US'],observed_at=T,collected_at=T)
  p=plan(s,snap(changed));self.assertIn('EARNINGS',intent(p,'A3')['slices'])
 def test_calendar_future_publication_not_backdated(self):
  payload=calendar_payload(10);payload['provider_published_at']=LATER
  rows=b.calendar_rows(payload,['AAA.US'],observed_at=T,collected_at=T)
  with self.assertRaises(b.ReassessmentError):snap(rows)
 def test_calendar_dateonly_publication_blocked(self):
  payload=calendar_payload(10);payload['provider_published_at']='2026-10-04'
  rows=b.calendar_rows(payload,['AAA.US'],observed_at=T,collected_at=T)
  self.assertEqual(rows[0]['status'],'UNKNOWN_PUBLICATION');self.assertIsNone(intent(plan(None,snap(rows)),'A3'))
 def test_calendar_empty_values_not_present(self):
  payload=calendar_payload(10);r=payload['trends'][0][0];r['earningsEstimateAvg']=None;r['revenueEstimateAvg']=None
  rows=b.calendar_rows(payload,['AAA.US'],observed_at=T,collected_at=T);self.assertEqual(rows[0]['status'],'MISSING')
 def test_calendar_version_correction_preserved(self):
  payload=calendar_payload(10);payload['trends'][0][0]['provider_version']='v2'
  rows=b.calendar_rows(payload,['AAA.US'],observed_at=T,collected_at=T);self.assertEqual(rows[0]['revision_id'],'v2')
 def test_calendar_unknown_identity_never_admitted(self):
  payload=calendar_payload(10)
  for k in ('issuer_id','security_id','accounting_basis','currency','share_or_ADR_unit'):payload['trends'][0][0].pop(k)
  rows=b.calendar_rows(payload,['AAA.US'],observed_at=T,collected_at=T)
  self.assertEqual(rows[0]['status'],'UNKNOWN_IDENTITY');self.assertIsNone(intent(plan(None,snap(rows)),'A3'))
 def test_chameleon_actual_contract_to_reassessment(self):
  from tools.chameleon_market_context_v2 import build_context,macro_source_rows
  a=macro_source_rows(b'DATE,DGS10\n2026-10-02,4.0\n',source_id='fred:DGS10',collected_at=T,cutoff=T)
  c=build_context(macro_rows=a,public_rows=[],price_rows=[],calendar_result=None,security_map=None,security_map_available_at=None,cutoff=T,expected_session='2026-10-02')
  rows=b.macro_rows_from_context(c,observed_at=T)
  p=plan(None,snap(rows),idx([edge()]));self.assertIsNotNone(intent(p,'A4'));self.assertIn('VALUATION',intent(p,'A3')['slices'])
 def test_chameleon_context_tamper_rejected(self):
  from tools.chameleon_market_context_v2 import build_context
  c=build_context(macro_rows=[],public_rows=[],price_rows=[],calendar_result=None,security_map=None,security_map_available_at=None,cutoff=T,expected_session='2026-10-02');c['regime']='RISK_ON'
  with self.assertRaises(ValueError):b.macro_rows_from_context(c,observed_at=T)

def calendar_payload(value):
 return {'type':'Trends','symbols':'AAA.US','trends':[[{'code':'AAA.US','date':'2026-12-31','period':'0y',
        'earningsEstimateAvg':value,'revenueEstimateAvg':1000,'earningsEstimateNumberOfAnalysts':5,
        'issuer_id':'CIK1','security_id':'AAA','accounting_basis':'ADJUSTED','currency':'USD','share_or_ADR_unit':'COMMON_SHARE'}]]}

if __name__=='__main__':unittest.main(verbosity=2)
