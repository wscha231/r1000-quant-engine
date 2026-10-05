"""FREE_FIRST_C1 author regressions; synthetic fixtures, no native/A6 claim."""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools import candidate_reassessment_bridge as b
T0='2026-10-01T12:00:00Z'; T1='2026-10-02T12:00:00Z'; NOW='2026-10-02T13:00:00Z'
EXP='2026-10-05T12:00:00Z'
A='0000320193-26-000001'; B='0000320193-26-000002'
CIK='0000320193'; ISSUER='SEC:0000320193'
CONTRACT={'code_sha':'a'*40,'config_sha256':'b'*64,'model_version':'synthetic-review-only',
          'parameters_sha256':'c'*64,'dependency_sha256':'d'*64}

def payload():
 return {'cik':320193,'filings':{'recent':{'accessionNumber':[A], 'form':['10-Q'],
  'filingDate':['2026-10-01'],'reportDate':['2026-09-30'],
  'acceptanceDateTime':['2026-10-01T11:00:00Z'],'primaryDocument':['example-20260930.htm'],
  'items':['']}}}
def call(p=None,**kw):
 raw=json.dumps(payload() if p is None else p,separators=(',',':')).encode()
 args=dict(expected_sha256=hashlib.sha256(raw).hexdigest(),expected_cik=CIK,
  issuer_id=ISSUER,accessions=[A],observed_at=T0,collected_at=T0,cutoff=T1)
 args.update(kw);return b.sec_submission_filing_rows(raw,**args)
def index(edges=None):
 return b.exposure_index(candidates=[{'asset_id':'XAAA','issuer_id':ISSUER},
     {'asset_id':'XBBB','issuer_id':'SEC:0000000002'}],edges=edges or [],available_at=T0,expires_at=EXP)
def row(family='ACTUAL',entity='XAAA',value=10,status='OBSERVED',clock=T1):
 return dict(family=family,provider='synthetic_free_fixture',entity_kind='SECURITY',entity_id=entity,
   metric=family+'_VALUE',fiscal_period='2026-09-30' if family=='ACTUAL' else None,
   observation_period='2026-10-01',identity={'unit':'SYNTHETIC'},values={'value':value},
   status=status,available_at=clock,collected_at=clock,revision_id='v1',source_sha256='e'*64,causal_event_id=None)
def snap(rows,clock=T1,expiry=EXP):
 return b.snapshot(rows,scope_id='free-core-synthetic-scope',cutoff=clock,expires_at=expiry)
def run(rows=None,previous=None,**kw):
 args=dict(now=NOW,contract_identity=CONTRACT,
   previous_profile_id=b.FREE_FIRST_PROFILE if previous is not None else None,
   previous_contract_identity=CONTRACT,previous_index_sha256=index()['content_sha256'])
 args.update(kw)
 return b.free_first_review_plan(previous,snap(rows or []),index(),**args)
def for_asset(bundle,a='XAAA'):
 return next(r for r in bundle['per_asset'] if r['asset_id']==a)

class SecAdapterTests(unittest.TestCase):
 def test_metadata_not_actual(self):
  r=call()[0];self.assertEqual(r['family'],'FILING');self.assertIsNone(r['values']['actual_financial_values'])
 def test_no_guidance(self):self.assertIsNone(call()[0]['values']['guidance_values'])
 def test_acceptance_not_publication(self):self.assertIsNone(call()[0]['values']['provider_published_at'])
 def test_available_not_backdated(self):self.assertEqual(b.stamp(call()[0]['available_at']),b.stamp(T0))
 def test_cik_source_string(self):p=payload();p['cik']=CIK;self.assertEqual(call(p)[0]['identity']['cik'],CIK)
 def test_wrong_cik(self):
  p=payload();p['cik']=42
  with self.assertRaisesRegex(b.ReassessmentError,'CIK_MISMATCH'):call(p)
 def test_bool_cik(self):
  p=payload();p['cik']=True
  with self.assertRaises(b.ReassessmentError):call(p)
 def test_zero_cik(self):
  p=payload();p['cik']=0
  with self.assertRaises(b.ReassessmentError):call(p)
 def test_bad_expected_cik(self):
  with self.assertRaises(b.ReassessmentError):call(expected_cik='320193')
 def test_hash_mismatch(self):
  with self.assertRaisesRegex(b.ReassessmentError,'RAW_HASH'):call(expected_sha256='0'*64)
 def test_duplicate_json(self):
  raw=b'{"cik":1,"cik":2}'
  with self.assertRaisesRegex(b.ReassessmentError,'DUPLICATE_JSON'):
   b.sec_submission_filing_rows(raw,expected_sha256=hashlib.sha256(raw).hexdigest(),expected_cik=CIK,
     issuer_id=ISSUER,accessions=[A],observed_at=T0,collected_at=T0,cutoff=T1)
 def test_columns_length(self):
  p=payload();p['filings']['recent']['form']=[]
  with self.assertRaises(b.ReassessmentError):call(p)
 def test_missing_acceptance_column(self):
  p=payload();del p['filings']['recent']['acceptanceDateTime']
  with self.assertRaises(b.ReassessmentError):call(p)
 def test_missing_accession_needs_history_resolver(self):
  with self.assertRaisesRegex(b.ReassessmentError,'ACCESSION_NOT_IN_RECENT'):call(accessions=[B])
 def test_duplicate_selection(self):
  with self.assertRaises(b.ReassessmentError):call(accessions=[A,A])
 def test_empty_selection_not_noop_proof(self):
  with self.assertRaises(b.ReassessmentError):call(accessions=[])
 def test_bad_accession(self):
  with self.assertRaises(b.ReassessmentError):call(accessions=['AAPL'])
 def test_duplicate_source(self):
  p=payload();r=p['filings']['recent']
  for k in r:r[k]*=2
  with self.assertRaisesRegex(b.ReassessmentError,'DUPLICATE_SOURCE'):call(p)
 def test_future_acceptance(self):
  p=payload();p['filings']['recent']['acceptanceDateTime']=[T1]
  with self.assertRaisesRegex(b.ReassessmentError,'FUTURE_ACCEPTANCE'):call(p)
 def test_naive_acceptance(self):
  p=payload();p['filings']['recent']['acceptanceDateTime']=['2026-10-01T11:00:00']
  with self.assertRaisesRegex(b.ReassessmentError,'EXACT_TIMESTAMP'):call(p)
 def test_after_cutoff_collection(self):
  with self.assertRaisesRegex(b.ReassessmentError,'COLLECTION_CLOCK'):call(cutoff='2026-09-30T12:00:00Z')
 def test_observed_after_collected(self):
  with self.assertRaises(b.ReassessmentError):call(observed_at=T1)
 def test_future_report_date(self):
  p=payload();p['filings']['recent']['reportDate']=['2026-12-31']
  with self.assertRaises(b.ReassessmentError):call(p)
 def test_blank_report_not_inferred(self):
  p=payload();p['filings']['recent']['reportDate']=[''];self.assertIsNone(call(p)[0]['fiscal_period'])
 def test_8k_202_still_metadata(self):
  p=payload();p['filings']['recent']['form']=['8-K'];p['filings']['recent']['items']=['2.02,9.01']
  r=call(p)[0];self.assertEqual(r['family'],'FILING');self.assertFalse(r['values']['company_fundamentals_verified'])
 def test_form4_not_earnings(self):
  p=payload();p['filings']['recent']['form']=['4']
  with self.assertRaisesRegex(b.ReassessmentError,'UNSUPPORTED_SEC_FORM'):call(p)
 def test_document_traversal(self):
  p=payload();p['filings']['recent']['primaryDocument']=['../bad.htm']
  with self.assertRaises(b.ReassessmentError):call(p)
 def test_items_optional(self):
  p=payload();del p['filings']['recent']['items'];self.assertEqual(call(p)[0]['values']['items'],'')
 def test_items_mismatch(self):
  p=payload();p['filings']['recent']['items']=[]
  with self.assertRaises(b.ReassessmentError):call(p)
 def test_issuer_mapping_not_guessed(self):self.assertEqual(call(issuer_id='supplied:issuer')[0]['entity_id'],'supplied:issuer')
 def test_timezone_same_semantics(self):
  p=payload();p['filings']['recent']['acceptanceDateTime']=['2026-10-01T20:00:00+09:00']
  self.assertEqual(b.semantic(call(p)[0]),b.semantic(call()[0]))
 def test_extra_unrequested_form_allowed(self):
  p=payload();r=p['filings']['recent']
  for k,v in {'accessionNumber':B,'form':'4','filingDate':'2026-10-01','reportDate':'',
     'acceptanceDateTime':'2026-10-01T10:00:00Z','primaryDocument':'other.xml','items':''}.items():r[k].append(v)
  self.assertEqual(len(call(p)),1)
 def test_nonfinite_payload(self):
  p=payload();p['bad']=float('inf')
  with self.assertRaises(b.ReassessmentError):call(p)
 def test_input_not_mutated(self):
  p=payload();old=copy.deepcopy(p);call(p);self.assertEqual(p,old)

class FreeFirstTests(unittest.TestCase):
 def test_empty_not_false_completion(self):
  r=run();self.assertFalse(r['full_universe_complete']);self.assertEqual(for_asset(r)['capabilities']['actuals_review']['status'],'INPUT_GAP')
 def test_calendar_not_selected(self):self.assertEqual(run()['calendar_status'],'NOT_SELECTED_UNPURCHASED')
 def test_null_consensus_not_zero(self):
  r=run([row()]);self.assertIsNone(r['consensus_estimate']);self.assertIsNone(r['consensus_revision']);self.assertIsNone(r['consensus_surprise'])
 def test_calendar_rows_rejected_not_silently_removed(self):
  r=row();r['provider']='eodhd_calendar'
  with self.assertRaisesRegex(b.ReassessmentError,'NOT_SELECTED'):run([r])
 def test_consensus_from_other_vendor_not_actuals(self):
  with self.assertRaises(b.ReassessmentError):run([row('CONSENSUS')])
 def test_no_profile_downgrade(self):
  with self.assertRaisesRegex(b.ReassessmentError,'PROFILE_CHANGED'):run([row()],snap([],T0),previous_profile_id='requires-consensus')
 def test_no_previous_profile_inferred(self):
  with self.assertRaises(b.ReassessmentError):run([],snap([],T0),previous_profile_id=None)
 def test_joint_same_asset(self):self.assertEqual(for_asset(run([row(),row('PRICE')]))['capabilities']['actuals_price_joint_review']['status'],'INPUTS_PRESENT_REVIEW_ONLY')
 def test_no_cross_asset_union(self):
  r=run([row(),row('PRICE','XBBB')])
  self.assertEqual(for_asset(r)['capabilities']['actuals_price_joint_review']['status'],'INPUT_GAP')
 def test_actuals_failure_not_zero(self):
  r=run([row(value=None,status='FAILED'),row('PRICE')]);self.assertIn('ACTUAL',for_asset(r)['capabilities']['actuals_review']['missing_families'])
 def test_failure_routes_a6(self):self.assertIn('A6',run([row(status='FAILED')])['a0_parameter_proposals'])
 def test_same_input_no_new_intent(self):
  prev=snap([row(clock=T0)],T0)
  self.assertEqual(run([row()],prev)['review_plan']['status'],'NO_NEW_REVIEW_INTENT')
 def test_new_value_reassessment(self):
  prev=snap([row(clock=T0)],T0);r=run([row(value=12)],prev)
  self.assertIn('A3',r['a0_parameter_proposals']);self.assertEqual(r['review_plan']['events'][0]['reason'],'VALUE_OR_STATUS_CHANGED')
 def test_missing_source_no_fallback(self):
  prev=snap([row(clock=T0)],T0);r=run([],prev)
  self.assertEqual(r['review_plan']['events'][0]['reason'],'MISSING_FROM_COMPLETE_SCOPE')
 def test_metadata_has_no_joint_actuals(self):
  r=run(call()+[row('PRICE')]);self.assertEqual(for_asset(r)['capabilities']['actuals_review']['status'],'INPUT_GAP')
 def test_metadata_not_immediate_a5(self):self.assertNotIn('A5',run(call())['a0_parameter_proposals'])
 def test_metadata_to_extraction_review(self):
  r=run(call());scope=r['a0_parameter_proposals']['A3']['candidate_reassessment']['scope']
  self.assertIn('ACTUALS_EXTRACTION_REVIEW',scope['asset_slices']['XAAA']);self.assertNotIn('EXPECTED_RETURN',scope['slices'])
 def test_metadata_does_not_label_thesis_broken(self):
  r=run(call());self.assertFalse(r['economic_admission']);self.assertFalse(r['orders_allowed'])
 def test_all_authorities_closed(self):
  r=run([row(),row('PRICE')]);self.assertTrue(all(r[k] is False for k in b.CLOSED));self.assertTrue(r['model_requirements_unchanged'])
 def test_issuer_routes_only_mapped(self):self.assertEqual(run(call())['review_plan']['invalidations'][0]['asset_id'],'XAAA')
 def test_no_request_or_secret_read(self):
  with patch('os.getenv',side_effect=AssertionError('secret access')),patch('socket.socket.connect',side_effect=AssertionError('network')):
   r=run(call());self.assertEqual((r['provider_http_requests'],r['secret_reads']),(0,0))
 def test_expired_input_no_present_capability(self):
  i=index();i=b.exposure_index(candidates=i['candidates'],edges=[],available_at=T0,expires_at='2026-11-01T00:00:00Z')
  r=b.free_first_review_plan(None,snap([row()],expiry='2026-10-02T12:30:00Z'),i,now=NOW,contract_identity=CONTRACT)
  self.assertEqual(for_asset(r)['capabilities']['actuals_review']['status'],'INPUT_GAP')
 def test_tamper_rejected(self):
  s=snap([row()]);s['rows'][0]['values']['value']=999
  with self.assertRaisesRegex(b.ReassessmentError,'CONTENT_HASH'):
   b.free_first_review_plan(None,s,index(),now=NOW,contract_identity=CONTRACT)
 def test_grouped_role_requests(self):
  r=run([row(),row('PRICE'),row('ACTUAL','XBBB')]);intents=r['review_plan']['review_intents']
  self.assertEqual(len(intents),len({x['agent'] for x in intents}))
 def test_unchanged_rediscovery_raw_hash_no_new_economic_event(self):
  r0=call();p=payload();p['name']='Extra metadata';r1=call(p,observed_at=T1,collected_at=T1)
  self.assertEqual(run(r1,snap(r0,T0))['review_plan']['status'],'NO_NEW_REVIEW_INTENT')
 def test_isolated_standard_library_only(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);(root/'tools').mkdir();shutil.copyfile(Path(b.__file__),root/'tools/candidate_reassessment_bridge.py')
   code="""import sys,importlib.abc
class Block(importlib.abc.MetaPathFinder):
 def find_spec(self,n,path=None,target=None):
  if any(x in n for x in ('eodhd','chameleon','earnings_consensus','requests','pandas')):raise AssertionError(n)
sys.meta_path.insert(0,Block())
from tools import candidate_reassessment_bridge as b
s=b.snapshot([],scope_id='empty',cutoff='2026-10-02T00:00:00Z',expires_at='2026-10-03T00:00:00Z')
i=b.exposure_index(candidates=[],edges=[],available_at='2026-10-02T00:00:00Z',expires_at='2026-10-03T00:00:00Z')
c={'code_sha':'a'*40,'config_sha256':'b'*64,'model_version':'none','parameters_sha256':'c'*64,'dependency_sha256':'d'*64}
r=b.free_first_review_plan(None,s,i,now='2026-10-02T00:00:00Z',contract_identity=c)
assert r['provider_http_requests']==0 and r['consensus_estimate'] is None
print('ISOLATED_FREE_FIRST_PASS')
"""
   result=subprocess.run([sys.executable,'-c',code],cwd=root,capture_output=True,text=True,timeout=20)
   self.assertEqual(result.returncode,0,result.stderr);self.assertIn('ISOLATED_FREE_FIRST_PASS',result.stdout)



class SecFreeOptionalAbsentTests(unittest.TestCase):
 def test_nonempty_sec_review_and_selected_failure_without_optional_modules(self):
  raw=json.dumps(payload(),separators=(',',':')).encode()
  expected_hash=hashlib.sha256(raw).hexdigest()
  code="""import sys,importlib.abc,hashlib,json,os,socket
blocked=[]
class Block(importlib.abc.MetaPathFinder):
 def find_spec(self,name,path=None,target=None):
  if any(part in name.lower() for part in ('eodhd','calendar','chameleon','earnings_consensus','requests','pandas')):
   blocked.append('import:'+name);raise AssertionError('OPTIONAL_IMPORT_BLOCKED:'+name)
sys.meta_path.insert(0,Block())
def no_secret(*args,**kwargs):
 blocked.append('getenv');raise AssertionError('SECRET_READ_BLOCKED')
def no_network(*args,**kwargs):
 blocked.append('socket');raise AssertionError('NETWORK_BLOCKED')
os.getenv=no_secret
socket.socket.connect=no_network
socket.socket.connect_ex=no_network
socket.create_connection=no_network
socket.getaddrinfo=no_network
def require(condition,label):
 if not condition:raise AssertionError(label)
from tools import candidate_reassessment_bridge as b
raw=bytes.fromhex(RAW_HEX)
require(hashlib.sha256(raw).hexdigest()==EXPECTED_HASH,'fixture_raw_sha256')
rows=b.sec_submission_filing_rows(raw,expected_sha256=EXPECTED_HASH,expected_cik=CIK,
 issuer_id=ISSUER,accessions=[ACCESSION],observed_at=T0,collected_at=T0,cutoff=T1)
require(len(rows)==1,'one_selected_filing')
filing=rows[0]
require(filing['family']=='FILING' and filing['identity']['cik']==CIK and
 filing['identity']['accession_number']==ACCESSION and filing['source_sha256']==EXPECTED_HASH,'exact_filing_identity')
require(filing['values']['actual_financial_values'] is None and
 filing['values']['guidance_values'] is None and filing['values']['provider_published_at'] is None,'metadata_has_no_financial_or_publication_values')
require(filing['values']['source_observed_at']==b.stamp(T0).isoformat() and
 filing['values']['accepted_at']==b.stamp('2026-10-01T11:00:00Z').isoformat() and
 filing['available_at']==filing['collected_at']==b.stamp(T0).isoformat(),'distinct_source_and_event_clocks')
index=b.exposure_index(candidates=[{'asset_id':'XAAA','issuer_id':ISSUER},
 {'asset_id':'XBBB','issuer_id':'SEC:0000000002'}],edges=[],available_at=T0,expires_at=EXP)
current=b.snapshot(rows,scope_id='isolated-nonempty-sec',cutoff=T1,expires_at=EXP)
result=b.free_first_review_plan(None,current,index,now=NOW,contract_identity=CONTRACT)
scope=result['a0_parameter_proposals']['A3']['candidate_reassessment']['scope']
require({'FILING_CONTENT_REVIEW','ACTUALS_EXTRACTION_REVIEW'}<=set(scope['asset_slices']['XAAA']) and
 'EXPECTED_RETURN' not in scope['slices'],'metadata_routes_only_to_content_and_extraction_review')
require('A5' not in result['a0_parameter_proposals'],'no_metadata_A5')
require(all(result[name] is None for name in ('consensus_estimate','consensus_revision','consensus_surprise')),'null_consensus')
require(all(result[name] is False for name in b.CLOSED) and
 all(result['review_plan'][name] is False for name in b.CLOSED),'closed_authority')
require(result['calendar_status']=='NOT_SELECTED_UNPURCHASED' and
 result['provider_http_requests']==result['secret_reads']==0,'free_without_calendar_or_secrets')
require([item['asset_id'] for item in result['review_plan']['invalidations']]==['XAAA'],'issuer_mapping_does_not_spread')
capability=next(item for item in result['per_asset'] if item['asset_id']=='XAAA')['capabilities']
require(capability['filing_content_review']['status']=='INPUTS_PRESENT_REVIEW_ONLY' and
 capability['actuals_review']['status']=='INPUT_GAP','metadata_does_not_become_actuals')
previous=b.snapshot(rows,scope_id='isolated-nonempty-sec',cutoff=T0,expires_at=EXP)
failed=dict(filing,status='FAILED',available_at=T1,collected_at=T1)
failed_current=b.snapshot([failed],scope_id='isolated-nonempty-sec',cutoff=T1,expires_at=EXP)
repair=b.free_first_review_plan(previous,failed_current,index,now=NOW,contract_identity=CONTRACT,
 previous_profile_id=b.FREE_FIRST_PROFILE,previous_contract_identity=CONTRACT,
 previous_index_sha256=index['content_sha256'])
require(repair['review_plan']['events'][0]['reason']=='SOURCE_FAILED','selected_failure_is_not_filtered')
require(repair['review_plan']['invalidations'][0]['status']=='DATA_REPAIR_REQUIRED','selected_failure_repairs')
require('A6' in repair['a0_parameter_proposals'] and 'A5' not in repair['a0_parameter_proposals'] and
 'A3' not in repair['a0_parameter_proposals'],'failure_routes_to_source_review_without_promotion')
require(next(item for item in repair['per_asset'] if item['asset_id']=='XAAA')['capabilities']['filing_content_review']['status']=='INPUT_GAP','no_prior_positive_fallback')
require(all(repair[name] is False for name in b.CLOSED) and
 all(repair[name] is None for name in ('consensus_estimate','consensus_revision','consensus_surprise')),'repair_authority_and_consensus_remain_closed')
require(not blocked,'no_optional_import_secret_or_socket_attempt')
print(json.dumps({'marker':'ISOLATED_NONEMPTY_SEC_FREE_FIRST_PASS','raw_sha256':EXPECTED_HASH,
 'selected_accession':ACCESSION,'optimize':sys.flags.optimize,'observed_rows':len(rows),
 'source_failure_reason':repair['review_plan']['events'][0]['reason'],'blocked_optional_attempts':len(blocked)}))
"""
  constants={'RAW_HEX':raw.hex(),'EXPECTED_HASH':expected_hash,'CIK':CIK,'ISSUER':ISSUER,
             'ACCESSION':A,'T0':T0,'T1':T1,'NOW':NOW,'EXP':EXP,'CONTRACT':CONTRACT}
  prefix='\n'.join(name+'='+repr(value) for name,value in constants.items())+'\n'
  with tempfile.TemporaryDirectory() as directory:
   isolated=Path(directory);(isolated/'tools').mkdir()
   shutil.copyfile(Path(b.__file__),isolated/'tools/candidate_reassessment_bridge.py')
   argv=[sys.executable]+(['-O'] if sys.flags.optimize else [])+['-B','-c',prefix+code]
   child=subprocess.run(argv,cwd=isolated,capture_output=True,text=True,timeout=20)
  self.assertEqual(child.returncode,0,child.stderr)
  outcome=json.loads(child.stdout)
  self.assertEqual(outcome['marker'],'ISOLATED_NONEMPTY_SEC_FREE_FIRST_PASS')
  self.assertEqual(outcome['raw_sha256'],expected_hash)
  self.assertEqual(outcome['selected_accession'],A)
  self.assertEqual(outcome['optimize'],sys.flags.optimize)
  self.assertEqual(outcome['observed_rows'],1)
  self.assertEqual(outcome['source_failure_reason'],'SOURCE_FAILED')
  self.assertEqual(outcome['blocked_optional_attempts'],0)

if __name__=='__main__':unittest.main(verbosity=2)
