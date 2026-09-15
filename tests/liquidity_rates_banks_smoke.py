from __future__ import annotations
import copy
from datetime import date, timedelta
import hashlib
import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.liquidity_rates_banks import *
AT='2026-09-15T20:00:00Z'; SHA='bcb14c06613e34420ce7988e5bb1ac5547b22b57'

def rows(sid, days, a, b, frequency):
    out=[]
    for i,d in enumerate(days):
        v=a+(b-a)*(i/(len(days)-1) if len(days)>1 else 0)
        out.append(dict(series=sid,observation_date=d.isoformat(),value=v,
            available_at=AT,retrieved_at=AT,evidence='current_only'))
    raw=json.dumps(out,sort_keys=True).encode();h=hashlib.sha256(raw).hexdigest()
    unit=SOURCES[sid][0]
    return dict(unit=unit,frequency=frequency,status='COLLECTED',raw_sha256=[h],rows=out)

def fixture():
    p=dict(schema=INPUT_SCHEMA,datasets={})
    daily=[date(2026,9,15)-timedelta(days=i) for i in reversed(range(120))]
    sofr=[d for d in daily if d.weekday()<5]
    iorb=daily
    weekly=[date(2026,9,9)-timedelta(days=7*i) for i in reversed(range(20))]
    quarter=[date(2026,4,1),date(2026,7,1)]
    p['datasets']['SOFR']=rows('SOFR',sofr,3.6,3.6,'daily')
    p['datasets']['IORB']=rows('IORB',iorb,3.65,3.65,'daily_7day')
    p['datasets']['WLCFLPCL']=rows('WLCFLPCL',weekly,5000,5800,'weekly')
    p['datasets']['TOTCI']=rows('TOTCI',weekly,2800,2960,'weekly')
    p['datasets']['DPSACBW027SBOG']=rows('DPSACBW027SBOG',weekly,19000,19500,'weekly')
    p['datasets']['DRTSCILM']=rows('DRTSCILM',quarter,5,0,'quarterly')
    p['datasets']['DRSDCILM']=rows('DRSDCILM',quarter,5,16,'quarterly')
    return p

def run(p=None,**kw): return evaluate(p or fixture(),as_of=kw.pop('as_of',AT),source_commit=SHA,**kw)

class Tests(unittest.TestCase):
    def test_latest_sofr_matches_iorb_even_when_iorb_has_weekend(self):
        r=run();self.assertTrue(r['funding_pair']['latest_pair_confirmed']);self.assertEqual(r['funding_state'],'STABLE')
    def test_stale_pair_is_not_new_stability(self):
        p=fixture();r=copy.deepcopy(p['datasets']['SOFR']['rows'][-1]);r.update(observation_date='2026-09-16',available_at='2026-09-16T20:00:00Z',retrieved_at='2026-09-16T20:00:00Z');p['datasets']['SOFR']['rows'].append(r)
        x=run(p,as_of='2026-09-16T20:00:00Z');self.assertFalse(x['funding_pair']['latest_pair_confirmed']);self.assertEqual(x['funding_state'],'UNKNOWN')
    def test_matched_rate_shock_is_stress(self):
        p=fixture()
        for sid,val in [('SOFR',4.8),('IORB',3.65)]:
            r=copy.deepcopy(p['datasets'][sid]['rows'][-1]);r.update(observation_date='2026-09-16',value=val,available_at='2026-09-16T20:00:00Z',retrieved_at='2026-09-16T20:00:00Z');p['datasets'][sid]['rows'].append(r)
        self.assertEqual(run(p,as_of='2026-09-16T20:00:00Z')['funding_state'],'STRESS')
    def test_primary_credit_level_can_trigger_stress(self):
        p=fixture();p['datasets']['WLCFLPCL']['rows'][-1]['value']=60000
        self.assertIn('PRIMARY_CREDIT_LEVEL',run(p)['funding_stress_reasons'])
    def test_bank_expansion_requires_all_four_conditions(self):
        self.assertEqual(run()['bank_credit_state'],'EXPANSION_EVIDENCE')
    def test_bank_contraction(self):
        p=fixture();p['datasets']['TOTCI']['rows'][-1]['value']=2500;p['datasets']['DRSDCILM']['rows'][-1]['value']=-10;p['datasets']['DRTSCILM']['rows'][-1]['value']=30
        self.assertEqual(run(p)['bank_credit_state'],'CONTRACTION_EVIDENCE')
    def test_structural_break_invalidates_simple_growth(self):
        p=fixture();p['datasets']['TOTCI']['rows'][-2]['structural_break']=True
        self.assertIsNone(run(p)['features']['ci_growth_13w_pct'])
    def test_missing_deposit_data_degrades_without_order(self):
        p=fixture();del p['datasets']['DPSACBW027SBOG'];r=run(p)
        self.assertEqual(r['quality_status'],'DEGRADED');self.assertFalse(r['orders_allowed'])
    def test_current_history_cannot_be_backdated(self):
        p=fixture();p['datasets']['SOFR']['rows'][-1]['available_at']='2026-09-01T00:00:00Z'
        self.assertEqual(run(p)['source_quality']['SOFR']['status'],'INVALID_SOURCE')
    def test_non_session_requires_verified_calendar(self):
        p=fixture();ds=p['datasets']['SOFR'];row=dict(series='SOFR',observation_date='2026-09-13',value=None,available_at=AT,retrieved_at=AT,evidence='current_only',observation_status='NON_SESSION');ds['rows'].append(row)
        self.assertEqual(run(p)['source_quality']['SOFR']['status'],'INVALID_SOURCE')
    def test_verified_non_session_is_ignored(self):
        p=fixture();ds=p['datasets']['SOFR'];raw=b'calendar';h=hashlib.sha256(raw).hexdigest();ds['raw_sha256'].append(h)
        ds['calendar_evidence']=[dict(series='SOFR',observation_date='2026-09-13',state='NON_SESSION',calendar_id='synthetic',available_at='2026-09-01T00:00:00Z',published_at='2026-09-01T00:00:00Z',raw_sha256=h,source_uri='https://example.invalid/calendar')]
        ds['rows'].append(dict(series='SOFR',observation_date='2026-09-13',value=None,available_at=AT,retrieved_at=AT,evidence='current_only',observation_status='NON_SESSION'))
        self.assertEqual(run(p)['source_quality']['SOFR']['status'],'OK')
    def test_null_missing_is_not_zero(self):
        p=fixture();p['datasets']['SOFR']['rows'][-1].update(value=None,observation_status='MISSING')
        self.assertEqual(run(p)['source_quality']['SOFR']['status'],'MISSING_OBSERVATION')
    def test_repeat_same_dates_is_not_new_confirmation(self):
        prior=run();r=run(prior=prior);self.assertFalse(r['new_rates_banks_confirmation'])
    def test_new_matched_pair_can_be_new_confirmation(self):
        p=fixture();prior=run(p)
        for sid,val in [('SOFR',3.6),('IORB',3.65)]:
            r=copy.deepcopy(p['datasets'][sid]['rows'][-1]);r.update(observation_date='2026-09-16',value=val,available_at='2026-09-16T20:00:00Z',retrieved_at='2026-09-16T20:00:00Z');p['datasets'][sid]['rows'].append(r)
        self.assertTrue(run(p,as_of='2026-09-16T20:00:00Z',prior=prior)['new_rates_banks_confirmation'])
    def test_unit_mismatch_quarantines_source(self):
        p=fixture();p['datasets']['TOTCI']['unit']='USD_MILLIONS';self.assertEqual(run(p)['source_quality']['TOTCI']['status'],'INVALID_SOURCE')
    def test_nonfinite_rejected(self):
        p=fixture();p['datasets']['SOFR']['rows'][-1]['value']=float('nan')
        with self.assertRaises(ValueError): run(p)
    def test_future_prior_blocked(self):
        prior=run();prior['as_of']='2026-09-17T00:00:00Z'
        with self.assertRaises(ContractError):run(prior=prior)
    def test_attach_preserves_canonical(self):
        base={'state':'CRISIS','cash_weight':.5,'kill_switch':True};out=attach_readonly(base,run());self.assertEqual({k:out[k] for k in base},base);self.assertNotIn('rates_banks_context',base)
    def test_outputs_have_no_mutation_authority(self):
        r=run()
        for k in ('eligible_for_selector','target_mutation_allowed','orders_allowed','canonical_regime_mutation_allowed'):self.assertIs(r[k],False)
    def test_deterministic(self): self.assertEqual(run(),run())

if __name__=='__main__': unittest.main()
