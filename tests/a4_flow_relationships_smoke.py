"""Synthetic invariants only: no provider, actual financial fit or Drive write."""
import copy
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import unittest
from unittest.mock import patch
import numpy as np
import pandas as pd
from tools import a4_flow_relationships as f

def row(key,date,value):
    specs={'frb:'+k:v for k,v in f.primary.semantic_register().items()}
    specs.update({'nyfed:'+k:f.liquidity.SERIES[k] for k in ('SOFR','TGCR','EFFR')})
    sid,spec=next((sid,s) for sid,s in specs.items() if s[0]==key)
    return dict(logical_id=key,source_id=sid,observation_date=str(date),value=value,
        unit=spec[1],frequency=spec[2],measurement_basis=spec[3],seasonal_basis=spec[4],
        available_at='2024-01-01T00:00:00+00:00',collected_at='2024-01-01T00:00:00+00:00',original_sha256='a'*64)
class FlowTests(unittest.TestCase):
    def setUp(self):
        dates=pd.bdate_range('2019-01-01',periods=1200)
        values=100*np.exp(np.arange(1200)*.0002+.02*np.sin(np.arange(1200)*.13))
        self.prices={'SPY':pd.Series(values,index=dates),'QQQ':pd.Series(values**1.1,index=dates)}
        self.rows=[row('deposits_all',x.date(),100+i+i*i*.01) for i,x in enumerate(pd.date_range('2020-01-01',periods=80,freq='7D'))]
    def describe(self,rows=None,prices=None):return f.describe(self.rows if rows is None else rows,self.prices if prices is None else prices,cutoff='2024-02-01T12:00:00+00:00')
    def test_complete_fixed_population_and_no_fit_or_admission(self):
        with patch('numpy.linalg.solve',side_effect=AssertionError('FIT_FORBIDDEN')):
            out=self.describe()
        self.assertEqual(len(f.BALANCES+f.RATES),24);self.assertEqual(len(set(f.BALANCES+f.RATES)),24)
        self.assertEqual(len(out['results']),448);self.assertEqual(out['specification']['declared_coefficients'],896)
        self.assertEqual(out['actual_base_series'],1);self.assertEqual(len(out['missing_base_series']),23)
        for k in f.SAFETY:self.assertFalse(out[k])
        self.assertFalse(out['observation_date_is_release_date']);self.assertFalse(out['cross_feature_ranking_validated'])
    def test_amount_units_and_basis_point_conversion(self):
        rows=[row('deposits_all','2020-01-01',100),row('deposits_all','2020-01-08',101),
              row('fed_assets','2020-01-01',100),row('fed_assets','2020-01-08',101),
              row('sofr','2020-01-08',5.3),row('iorb','2020-01-08',5.2)]
        state,_=f._visible(rows,f.primary.clock('2024-02-01T12:00:00Z'));x=f._features(state)
        self.assertEqual(x['change:deposits_all'][0][1],1e9)
        self.assertEqual(x['change:fed_assets'][0][1],1e6)
        self.assertAlmostEqual(x['spread:sofr_minus_iorb'][0][1],10)
        self.assertEqual(x['spread:sofr_minus_tgcr'],[])
    def test_weekly_gaps_never_bridge_or_daily_repeat(self):
        a=row('deposits_all','2020-01-01',100);b=row('deposits_all','2020-01-15',102)
        state,_=f._visible([a,b],f.primary.clock('2024-02-01T12:00:00Z'))
        self.assertEqual(f._features(state)['change:deposits_all'],[])
        out=self.describe();one=next(x for x in out['results'] if x['feature']=='change:deposits_all' and x['horizon_sessions']==1 and x['target']=='SPY')
        self.assertEqual(one['native_feature_observations'],79);self.assertLessEqual(one['pairs'],79)
    def test_future_capture_and_future_prices_preserve_earlier_results(self):
        future=row('deposits_all','2024-02-02',1e5);future.update(available_at='2025-01-01T00:00:00Z',collected_at='2025-01-01T00:00:00Z')
        prices={k:pd.concat([v,pd.Series([999.],index=pd.DatetimeIndex(['2025-01-02']))]) for k,v in self.prices.items()}
        a=self.describe();b=self.describe(self.rows+[future],prices)
        self.assertEqual(a,b)
    def test_missing_price_invalidates_complete_outcome_path(self):
        bad={k:v.copy() for k,v in self.prices.items()};bad['SPY'].iloc[300]=np.nan
        full=self.describe();gap=self.describe(prices=bad)
        key=lambda x:x['feature']=='change:deposits_all' and x['target']=='SPY' and x['horizon_sessions']==21
        a=next(x for x in full['results'] if key(x));b=next(x for x in gap['results'] if key(x))
        self.assertLess(b['pairs'],a['pairs']);self.assertEqual(len(bad['SPY']),1200)
    def test_constant_changes_do_not_create_level_trend_correlation(self):
        rows=[row('deposits_all',x.date(),100+i) for i,x in enumerate(pd.date_range('2020-01-01',periods=80,freq='7D'))]
        out=self.describe(rows);one=next(x for x in out['results'] if x['feature']=='change:deposits_all' and x['target']=='SPY' and x['horizon_sessions']==1)
        self.assertGreater(one['pairs'],30);self.assertIsNone(one['pearson']);self.assertIsNone(one['spearman'])
    def test_refuse_duplicate_unit_nonfinite_and_target_mismatch(self):
        for mutate in ('duplicate','unit','value','source'):
            rows=copy.deepcopy(self.rows)
            if mutate=='duplicate':rows.append(rows[0].copy())
            if mutate=='unit':rows[0]['unit']='millions_usd'
            if mutate=='value':rows[0]['value']=float('inf')
            if mutate=='source':rows[0]['source_id']='unverified:DEPOSITS'
            with self.subTest(mutate=mutate),self.assertRaises(ValueError):self.describe(rows)
        for prices in ({'SPY':self.prices['SPY']},{'SPY':self.prices['SPY'],'QQQ':self.prices['QQQ'].iloc[::-1]}):
            with self.assertRaises(ValueError):self.describe(prices=prices)
    def test_exact_same_input_reuse_and_long_horizon_insufficiency(self):
        a=self.describe();b=self.describe(list(reversed(self.rows)))
        self.assertEqual(a,b)
        long=next(x for x in a['results'] if x['feature']=='change:deposits_all' and x['target']=='SPY' and x['horizon_sessions']==504)
        self.assertEqual(long['statistical_evidence'],'INSUFFICIENT_EVIDENCE');self.assertNotIn('p_value',long)
    def test_pre_price_history_never_maps_to_first_price_anchor(self):
        old=[row('deposits_all','1999-01-06',1),row('deposits_all','1999-01-13',10000)]
        out=self.describe(old+self.rows);plain=self.describe()
        for a,b in zip(out['results'],plain['results']):
            self.assertEqual((a['pairs'],a['pearson'],a['spearman']),(b['pairs'],b['pearson'],b['spearman']))
            if a['first'] is not None:self.assertGreaterEqual(a['first'],'2019-01-01')

class PriceTests(unittest.TestCase):
    def setUp(self):
        from tools import a4_flow_price_inputs as prices
        from tools.macro_history_sources import encoded,digest
        self.p=prices;self.encoded=encoded;self.digest=digest
        self.now='2026-11-17T13:00:00+00:00';self.session='2026-11-16'
        self.clock=patch.object(prices.primary,'now',return_value=self.now);self.clock.start()
        self.market=patch.object(prices.market,'current_session',return_value=self.session);self.market.start()
        self.policy=dict(schema='a4-flow-test-policy-v1',purpose=prices.PURPOSE,available_at='2026-11-17T00:00:00Z',expires_at='2026-12-17T00:00:00Z',
            targets=['SPY','QQQ'],price_start='2016-01-01',maximum_batch_calls_per_attempt=1,maximum_attempts_per_session=1,
            price_column='Close',currency_expectation='USD',source_quality='UNQUALIFIED_DATAFRAME_SNAPSHOT',
            supplier_training_permission_granted=False,research_folder_ID='test-folder',
            provider_private_use_and_storage_rights='UNVERIFIED',producer_sha256=prices.producer_pins(),model_fits_allowed=0,portfolio_changes_allowed=False)
        self.calls=[]
    def tearDown(self):self.market.stop();self.clock.stop()
    def policy_bytes(self):
        raw=self.encoded(self.policy);return raw,self.digest(raw)
    def download(self,*args):
        self.calls.append(args);idx=pd.bdate_range('2025-01-01',self.session)
        return {t:pd.DataFrame({'Close':100+np.arange(len(idx))*.05},index=idx) for t in ('SPY','QQQ')},{}
    def test_one_existing_collector_batch_and_snapshot_replay(self):
        raw,pin=self.policy_bytes();snapshot,view=self.p.collect(raw,pin,cutoff=self.now,download=self.download)
        self.assertEqual(len(self.calls),1);self.assertEqual(self.calls[0][0],['SPY','QQQ'])
        self.p.verify_snapshot(view,self.encoded(snapshot));series=self.p.price_series(view,policy_sha256=pin,cutoff=self.now)
        self.assertEqual(str(series['SPY'].index[-1].date()),self.session)
        self.assertFalse(view['provider_currency_verified']);self.assertFalse(view['raw_http_originals_available']);self.assertFalse(view['training_admitted'])
    def test_invalid_policy_never_calls_provider(self):
        for key,value in [('expires_at','2026-11-01T00:00:00Z'),('targets',['SPY']),('maximum_batch_calls_per_attempt',True),
                          ('supplier_training_permission_granted',True),('price_column','Adj Close'),('model_fits_allowed',1)]:
            original=self.policy.copy();self.policy[key]=value;raw,pin=self.policy_bytes()
            with self.subTest(key=key),self.assertRaises(ValueError):self.p.collect(raw,pin,cutoff=self.now,download=self.download)
            self.policy=original
        self.assertEqual(self.calls,[])
    def test_missing_latest_close_and_normalization_tamper_refuse(self):
        raw,pin=self.policy_bytes()
        def missing(*args):
            frames,audit=self.download(*args);frames['QQQ']=frames['QQQ'].iloc[:-1];return frames,audit
        with self.assertRaisesRegex(ValueError,'LATEST_SESSION_CLOSE'):self.p.collect(raw,pin,cutoff=self.now,download=missing)
        snapshot,view=self.p.collect(raw,pin,cutoff=self.now,download=self.download)
        changed=copy.deepcopy(view);changed['targets']['SPY'][0][1]+=1
        with self.assertRaisesRegex(ValueError,'NORMALIZATION_REPLAY'):self.p.verify_snapshot(changed,self.encoded(snapshot))
        changed=copy.deepcopy(view);changed['targets']['SPY'][-1][1]=None
        with self.assertRaisesRegex(ValueError,'EXACT_SESSION_CLOSE'):self.p.price_series(changed,policy_sha256=pin,cutoff=self.now)
    def test_session_claim_survives_failure_without_provider_retry(self):
        import tempfile
        class Memory:
            remote_verified=False
            def __init__(self):self.objects={}
            def names(self,prefix):return [p.rsplit('/',1)[-1] for p in self.objects if p.startswith(prefix+'/')]
            def write(self,path,raw):
                if path in self.objects and self.objects[path]!=raw:raise ValueError('immutable')
                self.objects[path]=raw
        remote=Memory();calls=[]
        def failure(*args):calls.append(1);raise RuntimeError('provider unavailable')
        raw,pin=self.policy_bytes()
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            with self.assertRaises(RuntimeError):self.p.stage(raw,pin,cutoff=self.now,output_root=root/'first',transport=remote,download=failure)
            self.assertTrue((root/'first/session-consumed.json').is_file());self.assertTrue((root/'first/failure.json').is_file())
            with self.assertRaisesRegex(ValueError,'SESSION_ALREADY_CONSUMED'):self.p.stage(raw,pin,cutoff=self.now,output_root=root/'second',transport=remote,download=failure)
        self.assertEqual(calls,[1])
    def test_discovery_and_readback_share_command_byte_and_expiry_caps(self):
        from tools.macro_research_checkpoint import RcloneTransport
        raw,pin=self.policy_bytes()
        listing=self.encoded([dict(Name='scheduled',IsDir=True,ID='test-folder')])
        calls=[]
        def fake(transport,*args):
            calls.append(args);return listing if args[0]=='lsjson' else b'xx'
        with patch.object(RcloneTransport,'call',fake):
            remote=self.p.bounded_transport('gdrive:r1000_top30_institutional/research/macro_technical_evidence/v1/scheduled',raw,pin)
            self.assertEqual(remote.commands,1)
            with patch.object(self.p,'MAX_TRANSPORT_COMMANDS',2):
                remote.call('cat','gdrive:'+self.p.primary.PREFIX+'/objects/'+'a'*64)
                with self.assertRaisesRegex(ValueError,'TRANSPORT_BUDGET'):remote.call('cat','gdrive:'+self.p.primary.PREFIX+'/objects/'+'a'*64)
            self.assertEqual(len(calls),2)
            with patch.object(self.p,'MAX_TRANSPORT_BYTES',remote.read_bytes+1),self.assertRaisesRegex(ValueError,'TRANSPORT_BYTE_BUDGET'):
                remote.call('cat','gdrive:'+self.p.primary.PREFIX+'/objects/'+'a'*64)
            before=len(calls)
            with self.assertRaisesRegex(ValueError,'TRANSPORT_OPERATION'):remote.call('mkdir','unused')
            with self.assertRaisesRegex(ValueError,'TRANSPORT_NAMESPACE'):remote.call('cat','gdrive:unrelated/objects/'+'a'*64)
            self.assertEqual(len(calls),before)
            with patch.object(self.p.primary,'now',return_value='2026-12-18T00:00:00Z'),self.assertRaisesRegex(ValueError,'POLICY_CLOCK'):
                remote.call('cat','gdrive:'+self.p.primary.PREFIX+'/objects/'+'a'*64)
            self.assertEqual(len(calls),before)
            remote.deadline=-1
            with self.assertRaisesRegex(ValueError,'TRANSPORT_BUDGET'):remote.call('cat','gdrive:'+self.p.primary.PREFIX+'/objects/'+'a'*64)
            self.assertEqual(len(calls),before)

    def test_wrong_folder_remote_or_missing_namespace_never_creates_archive(self):
        from tools.macro_research_checkpoint import RcloneTransport
        raw,pin=self.policy_bytes();calls=[]
        def listing(transport,*args):
            calls.append(args);return self.encoded([dict(Name='scheduled',IsDir=True,ID='different-folder')])
        remote='gdrive:r1000_top30_institutional/research/macro_technical_evidence/v1/scheduled'
        with patch.object(RcloneTransport,'call',listing):
            with self.assertRaisesRegex(ValueError,'TRANSPORT_FOLDER_ID'):self.p.bounded_transport(remote,raw,pin)
            self.assertEqual(len(calls),1)
            with self.assertRaisesRegex(ValueError,'TRANSPORT_REMOTE'):self.p.bounded_transport('gdrive:unrelated',raw,pin)
            self.assertEqual(len(calls),1)
        with patch.object(RcloneTransport,'call',return_value=b'[]') as fake:
            with self.assertRaisesRegex(ValueError,'TRANSPORT_OPERATION'):self.p.bounded_transport(remote,raw,pin)
            self.assertEqual(fake.call_count,1)  # Discovery only; mkdir refused before delegation.

    def test_same_session_cache_reuses_without_collection(self):
        import tempfile
        raw,pin=self.policy_bytes();snapshot,view=self.p.collect(raw,pin,cutoff=self.now,download=self.download)
        with tempfile.TemporaryDirectory() as temp:
            reused=self.p.stage(raw,pin,cutoff=self.now,output_root=Path(temp)/'reuse',previous=view,
                download=lambda *a:(_ for _ in ()).throw(AssertionError('RECOLLECTION')))
        self.assertEqual(reused,view)
    def test_long_approval_window_never_makes_old_daily_prices_current(self):
        raw,pin=self.policy_bytes();_,view=self.p.collect(raw,pin,cutoff=self.now,download=self.download)
        self.p.price_series(view,policy_sha256=pin,cutoff=self.now,expected_session=self.session)
        with self.assertRaisesRegex(ValueError,'SESSION_NOT_CURRENT'):
            self.p.price_series(view,policy_sha256=pin,cutoff=self.now,expected_session='2026-11-17')

    def test_existing_scheduler_requires_policy_and_failure_metadata_is_public_safe(self):
        import yaml
        from tools import a4_public_receipts as public
        root=Path(__file__).resolve().parents[1]
        workflow=yaml.safe_load((root/'.github/workflows/daily_crisis_monitor.yml').read_text())
        steps=workflow['jobs']['monitor']['steps']
        prepare=next(s for s in steps if s.get('id')=='a4_flow_prices')
        self.assertIn("vars.A4_FLOW_RESEARCH_POLICY_SHA256 != ''",prepare['if'])
        self.assertIn("steps.a4_primary_collect.outcome == 'success'",prepare['if'])
        self.assertIn('--execute --publish',prepare['run'])
        self.assertEqual(prepare['timeout-minutes'],12)
        self.assertIn('timeout --signal=TERM --kill-after=10s 12m',prepare['run'])
        center=next(s for s in steps if s.get('id')=='a4_data_center')
        self.assertIn('A4_FLOW_RESEARCH_POLICY_SHA256',center['env'])
        self.assertIn("catalog['flow_relationships']['status']",center['run'])
        self.assertIn('failure.json',public.FILES['flow'][1])
        metadata=next(s for s in steps if s.get('id')=='a4_public_receipts')
        self.assertIn('A4_PUBLIC_FLOW',metadata['env'])

    def test_loaded_producer_change_refuses_before_collection(self):
        raw,pin=self.policy_bytes();changed=self.p.producer_pins();changed['market_analysis_engine.py']='0'*64
        with patch.object(self.p,'_file_pins',return_value=changed),self.assertRaisesRegex(ValueError,'LOADED_PRODUCER_CHANGED'):
            self.p.collect(raw,pin,cutoff=self.now,download=self.download)
        self.assertEqual(self.calls,[])

    def test_data_center_embeds_private_association_without_learning_admission(self):
        import tempfile
        from tools import a4_data_center as center
        from tests.a4_data_center_smoke import capture
        from tests.a4_primary_sources_smoke import NOW
        self.clock.stop();self.clock=patch.object(self.p.primary,'now',return_value=NOW);self.clock.start()
        self.market.stop();self.market=patch.object(self.p.market,'current_session',return_value='2026-11-06');self.market.start()
        self.session='2026-11-06';self.policy.update(available_at='2026-11-07T00:00:00Z',expires_at='2026-12-07T00:00:00Z')
        raw,pin=self.policy_bytes()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);spec=capture(root/'macro');policy_root=root/'policy';policy_root.mkdir()
            (policy_root/'flow-research-policy.json').write_bytes(raw)
            self.p.stage(raw,pin,cutoff=NOW,output_root=root/'prices',download=self.download)
            catalog,receipt=center.build([spec],cutoff=NOW,output_dir=root/'index',flow_policy_root=policy_root,
                flow_policy_sha256=pin,flow_price_root=root/'prices')
            self.assertEqual(catalog['flow_relationships']['status'],'CURRENT_VINTAGE_DESCRIPTIVE_ONLY')
            self.assertEqual(len(catalog['flow_relationships']['results']),448)
            self.assertFalse(catalog['training_admitted']);self.assertFalse(catalog['source_admitted'])
            self.assertEqual(catalog['current_diagnosis']['status'],'DATA_BLOCKED')
            (root/'prices/price-view.json').write_bytes(b'changed')
            catalog,_=center.build([spec],cutoff=NOW,output_dir=root/'changed',flow_policy_root=policy_root,
                flow_policy_sha256=pin,flow_price_root=root/'prices')
            self.assertEqual(catalog['flow_relationships']['status'],'BLOCKED')

if __name__=='__main__':unittest.main()
