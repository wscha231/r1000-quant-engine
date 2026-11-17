"""Synthetic failover proofs: no provider requests, Drive writes or fitting."""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import pandas as pd
from tools import a4_flow_price_inputs as p, a4_price_fallback as f
from tests.a4_flow_relationships_smoke import MemoryArchive


class FallbackTests(unittest.TestCase):
    def setUp(self):
        self.now='2026-11-17T13:00:00Z';self.session='2026-11-16';self.calls=[]
        self.clock=patch.object(p.primary,'now',return_value=self.now);self.clock.start()
        self.market=patch.object(p.market,'current_session',return_value=self.session);self.market.start()
        self.addCleanup(self.clock.stop);self.addCleanup(self.market.stop)
        dates=pd.bdate_range('2016-01-04',self.session)
        self.frames={s:pd.DataFrame({'Open':100.,'High':102.,'Low':99.,'Close':101.,'Volume':1000.},index=dates) for s in p.TARGETS}
        self.policy=dict(schema='a4-flow-test-policy-v2',purpose=p.PURPOSE,
            available_at='2026-11-17T00:00:00Z',expires_at='2026-11-24T00:00:00Z',
            targets=list(p.TARGETS),price_start='2016-01-01',maximum_batch_calls_per_attempt=3,
            maximum_attempts_per_session=1,price_column='Close',currency_expectation='USD',
            source_quality='UNQUALIFIED_DATAFRAME_SNAPSHOT',supplier_training_permission_granted=False,
            research_folder_ID='test-folder',provider_private_use_and_storage_rights='UNVERIFIED',
            producer_sha256=p.producer_pins(2),model_fits_allowed=0,portfolio_changes_allowed=False,
            providers=[self.descriptor('yfinance'),self.descriptor('alpaca_sip'),self.descriptor('twelve_data')])

    def descriptor(self,name):
        row=dict(id=name,private_noncommercial_test_authorized=True,use_scope_sha256='a'*64,
                 maximum_requests=1 if name=='yfinance' else 2)
        if name=='alpaca_sip':row['noncommercial_terms_acknowledged']=True
        if name=='twelve_data':row['mic_by_target']={'SPY':'ARCX','QQQ':'XNGS'}
        return row

    def raw(self):
        raw=p.encoded(self.policy);return raw,p.digest(raw)

    def good(self,name):
        def adapter(targets,start,end,descriptor,capture,clock):
            self.calls.append(name)
            if descriptor['id']=='alpaca_sip':
                bars={s:[dict(t=str(day.date())+'T05:00:00Z',o=100,h=102,l=99,c=101,v=1000)
                         for day in frame.index] for s,frame in self.frames.items()}
                capture(lambda:p.encoded(dict(bars=bars,next_page_token=None)),())
            if descriptor['id']=='twelve_data':
                for s,frame in self.frames.items():
                    data=dict(meta=dict(symbol=s,currency='USD',interval='1day',mic_code=descriptor['mic_by_target'][s]),
                        values=[dict(datetime=str(d.date()),open='100',high='102',low='99',close='101',volume='1000') for d in frame.index])
                    capture(lambda:p.encoded(data),())
            return copy.deepcopy(self.frames)
        return adapter

    def bad(self,name,reason='NETWORK'):
        def adapter(*args):self.calls.append(name);raise f.Unavailable(reason)
        return adapter

    def collect(self,adapters,audit=None):
        raw,pin=self.raw();return p.collect(raw,pin,cutoff=self.now,adapters=adapters,audit=audit)

    def test_real_yfinance_empty_normalizer_falls_through_and_logs_shape(self):
        fake=types.SimpleNamespace(__version__='synthetic',download=lambda *a,**k:pd.DataFrame())
        with patch.dict(sys.modules,{'yfinance':fake}),patch('numpy.linalg.solve',side_effect=AssertionError('FIT')):
            snapshot,view=self.collect(dict(yfinance=f.fetch_yfinance,alpaca_sip=self.good('alpaca'),twelve_data=self.good('unused')))
        self.assertEqual(self.calls,['alpaca']);self.assertEqual(view['selected_provider'],'alpaca_sip')
        attempt=view['provider_attempts'][0]
        self.assertEqual(attempt['reason'],'FRAME');self.assertEqual(attempt['structure']['SPY']['shape'],[0,0])
        self.assertEqual([r['status'] for r in view['provider_attempts']],['REJECTED','SELECTED'])
        p.verify_snapshot(view,p.encoded(snapshot))

    def test_partial_primary_never_supplies_one_half_of_fallback_pair(self):
        def partial(*args):
            self.calls.append('partial');frames=copy.deepcopy(self.frames);frames['SPY']['Close']=200.;frames['QQQ']=frames['QQQ'].iloc[:-1];return frames
        snapshot,view=self.collect(dict(yfinance=partial,alpaca_sip=self.good('complete'),twelve_data=self.good('unused')))
        self.assertEqual(view['targets']['SPY'][-1][1],101.)
        self.assertEqual(view['targets']['QQQ'][-1][1],101.)
        self.assertEqual(self.calls,['partial','complete'])

    def test_all_three_fail_once_and_record_explicit_reasons(self):
        audits=[]
        with self.assertRaisesRegex(ValueError,'ALL_PRICE_PROVIDERS_UNAVAILABLE'):
            self.collect({name:self.bad(name) for name in f.PROVIDERS},lambda e:audits.append(copy.deepcopy(e)))
        self.assertEqual(self.calls,['yfinance','alpaca_sip','twelve_data'])
        self.assertEqual(len(audits[-1]['attempts']),3)
        self.assertTrue(all(a['status']=='REJECTED' and a['reason']=='NETWORK' for a in audits[-1]['attempts']))

    def test_invalid_scope_or_duplicate_provider_makes_no_calls(self):
        cases=[]
        a=copy.deepcopy(self.policy);a['providers'][1]=copy.deepcopy(a['providers'][0]);cases.append(a)
        a=copy.deepcopy(self.policy);a['providers'][0]['private_noncommercial_test_authorized']=False;cases.append(a)
        a=copy.deepcopy(self.policy);a['providers'][0]['maximum_requests']=20;cases.append(a)
        a=copy.deepcopy(self.policy);a['providers'][0]['unexpected_secret']='not-allowed';cases.append(a)
        original=self.policy
        for candidate in cases:
            self.policy=candidate
            with self.assertRaises(ValueError):self.collect({name:self.good(name) for name in f.PROVIDERS})
        self.policy=original;self.assertEqual(self.calls,[])

    def test_expiry_during_primary_is_integrity_stop_without_second_provider(self):
        def expires(*args):
            self.calls.append('late');p.primary.now.return_value='2026-11-25T00:00:00Z';return self.frames
        with self.assertRaises(f.IntegrityError):
            self.collect(dict(yfinance=expires,alpaca_sip=self.good('forbidden'),twelve_data=self.good('forbidden')))
        self.assertEqual(self.calls,['late'])

    def test_credential_echo_stops_chain_without_retaining_secret(self):
        audits=[]
        def echo(targets,start,end,descriptor,capture,clock):
            self.calls.append('echo');capture(lambda:b'{"x":"synthetic-private-key"}',('synthetic-private-key',))
        with self.assertRaises(f.IntegrityError):
            self.collect(dict(yfinance=echo,alpaca_sip=self.good('forbidden'),twelve_data=self.good('forbidden')),
                         lambda e:audits.append(copy.deepcopy(e)))
        self.assertEqual(self.calls,['echo']);self.assertEqual(audits[-1]['responses'],{})
        self.assertNotIn('synthetic-private-key',json.dumps(audits))

    def test_requests_are_counted_before_failure_no_refund_or_loop(self):
        def exhaust(targets,start,end,descriptor,capture,clock):
            for _ in range(3):capture(lambda:b'{"bars":{}}',())
        snapshot,view=self.collect(dict(yfinance=self.bad('first'),alpaca_sip=exhaust,twelve_data=self.good('last')))
        self.assertEqual(view['provider_attempts'][1]['requests'],2)
        self.assertEqual(view['provider_attempts'][1]['reason'],'REQUEST_BUDGET')
        self.assertEqual(view['selected_provider'],'twelve_data')

    def test_stale_july_prices_never_become_current_fallback(self):
        def stale(*args):return {s:frame.loc[:'2026-07-02'] for s,frame in self.frames.items()}
        with self.assertRaises(ValueError):self.collect({name:stale for name in f.PROVIDERS})

    def test_structure_diagnostics_do_not_echo_arbitrary_column_names(self):
        frame=pd.DataFrame({'private-token-do-not-echo':[1]})
        result=f.structure({'SPY':frame})
        self.assertNotIn('private-token',json.dumps(result));self.assertEqual(result['SPY']['columns'],['OTHER'])

    def test_alpaca_reuses_existing_request_parser_and_replays_original(self):
        from tools import alpaca_sip_private_backfill_v1 as source
        self.policy['providers']=[self.descriptor('alpaca_sip'),self.descriptor('yfinance')]
        self.policy['maximum_batch_calls_per_attempt']=2
        bars={s:[dict(t=str(day.date())+'T05:00:00Z',o=100,h=102,l=99,c=101,v=1000) for day in frame.index]
              for s,frame in self.frames.items()}
        response=p.encoded(dict(bars=bars,next_page_token=None))
        with patch.dict(os.environ,ALPACA_API_KEY='test-key',ALPACA_API_SECRET='test-secret'),patch.object(source,'http',return_value=response) as http,patch.object(source.time,'sleep'):
            snapshot,view=self.collect(dict(alpaca_sip=f.fetch_alpaca,yfinance=self.good('unused')))
        self.assertEqual(http.call_count,1);self.assertTrue(view['raw_http_originals_available'])
        p.verify_snapshot(view,p.encoded(snapshot))
        tampered=copy.deepcopy(snapshot);tampered['frames']['SPY']['values'][0][3]=999.
        changed=copy.deepcopy(view);changed['targets']['SPY'][0][1]=999.;changed['snapshot_sha256']=p.digest(p.encoded(tampered))
        with self.assertRaisesRegex(ValueError,'RAW_NORMALIZATION_REPLAY'):p.verify_snapshot(changed,p.encoded(tampered))

    def test_alpaca_future_end_is_skipped_before_credentials_or_http(self):
        descriptor=self.descriptor('alpaca_sip');called=[]
        with self.assertRaisesRegex(ValueError,'END_DELAY_NOT_ELAPSED'):
            f.fetch_alpaca(list(p.TARGETS),'2016-01-01','2026-11-18',descriptor,
                          lambda *a:called.append(1),lambda:self.now)
        self.assertEqual(called,[])

    def test_sparse_endpoints_and_short_history_cannot_pass_as_full_history(self):
        def sparse(*args):return {s:frame.iloc[[0,-1]] for s,frame in self.frames.items()}
        audits=[]
        with self.assertRaisesRegex(ValueError,'ALL_PRICE_PROVIDERS_UNAVAILABLE'):
            self.collect({name:sparse for name in f.PROVIDERS},lambda e:audits.append(copy.deepcopy(e)))
        self.assertTrue(all(a['reason']=='HISTORY_COVERAGE' for a in audits[-1]['attempts']))

    def test_missing_early_closes_or_pre_range_sentinel_do_not_prove_start(self):
        def missing(*args):
            frames=copy.deepcopy(self.frames)
            for frame in frames.values():frame.loc[:'2017-12-31','Close']=float('nan')
            return frames
        def sentinel(*args):
            return {s:pd.concat([frame.iloc[:1].set_axis(pd.to_datetime(['2015-12-31'])),
                                 frame.loc['2018-01-01':]]) for s,frame in self.frames.items()}
        for bad in (missing,sentinel):
            self.calls=[]
            snapshot,view=self.collect(dict(yfinance=bad,alpaca_sip=self.good('full-history'),twelve_data=self.good('forbidden')))
            self.assertEqual(view['provider_attempts'][0]['reason'],'HISTORY_START')
            self.assertEqual(view['selected_provider'],'alpaca_sip');self.assertEqual(self.calls,['full-history'])
            p.verify_snapshot(view,p.encoded(snapshot))

    def test_session_roll_during_normalization_or_evidence_replay_stops_chain(self):
        original=p._collect_single;verify=p.verify_snapshot
        def normalized(*args,**kwargs):
            result=original(*args,**kwargs);p.market.current_session.return_value='2026-11-17';return result
        def replayed(*args,**kwargs):
            result=verify(*args,**kwargs);p.market.current_session.return_value='2026-11-17';return result
        for name,implementation in (('_collect_single',normalized),('verify_snapshot',replayed)):
            p.market.current_session.return_value=self.session;self.calls=[]
            with patch.object(p,name,side_effect=implementation),self.assertRaises(f.IntegrityError):
                self.collect({provider:self.good(provider) for provider in f.PROVIDERS})
            self.assertEqual(self.calls,['yfinance'])

    def test_session_roll_during_remote_receipt_never_writes_completion_marker(self):
        raw,pin=self.raw();remote=MemoryArchive();write=remote.write
        def rolls(path,body):
            write(path,body)
            if b'"schema":"a4-flow-test-price-execution-v1"' in body:
                p.market.current_session.return_value='2026-11-17'
        remote.write=rolls
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'attempt'
            with self.assertRaisesRegex(ValueError,'SESSION_ROLLED'):
                p.stage(raw,pin,cutoff=self.now,output_root=root,transport=remote,
                        adapters={name:self.good(name) for name in f.PROVIDERS})
            self.assertFalse((root/'durable-completion.json').exists());self.assertTrue((root/'failure.json').is_file())

    def test_twelve_uses_existing_http_and_replays_both_raw_bodies(self):
        from tools import twelve_private_capture as source
        self.policy['providers']=[self.descriptor('twelve_data'),self.descriptor('yfinance')]
        self.policy['maximum_batch_calls_per_attempt']=2
        def http(url,**kwargs):
            from urllib.parse import parse_qs,urlsplit
            query=parse_qs(urlsplit(url).query);target=query['symbol'][0]
            self.assertEqual(query['end_date'],[self.session]);self.assertEqual(query['adjust'],['none'])
            self.assertNotIn('apikey',query)
            return p.encoded(dict(meta=dict(symbol=target,currency='USD',interval='1day',mic_code=self.policy['providers'][0]['mic_by_target'][target]),
                values=[dict(datetime=str(d.date()),open='100',high='102',low='99',close='101',volume='1000') for d in self.frames[target].index]))
        with patch.dict(os.environ,TWELVE_API_KEY='test-key'),patch.object(source,'http',side_effect=http) as get,patch.object(f.time,'sleep'):
            snapshot,view=self.collect(dict(twelve_data=f.fetch_twelve,yfinance=self.good('unused')))
        self.assertEqual(get.call_count,2);self.assertEqual(len(snapshot['provider_evidence']['responses']),2)
        p.verify_snapshot(view,p.encoded(snapshot))
        snapshot['provider_evidence']['responses'][next(iter(snapshot['provider_evidence']['responses']))]+=' '
        view['snapshot_sha256']=p.digest(p.encoded(snapshot))
        with self.assertRaisesRegex(ValueError,'RESPONSE_HASH'):p.verify_snapshot(view,p.encoded(snapshot))

    def test_pair_policy_relabelled_after_capture_is_rejected(self):
        snapshot,view=self.collect({name:self.good(name) for name in f.PROVIDERS})
        changed=copy.deepcopy(self.policy);changed['providers'][0]['use_scope_sha256']='b'*64
        with self.assertRaisesRegex(ValueError,'VIEW_PROVIDER_POLICY'):p.verify_policy_view(changed,view)

    def test_v2_data_center_replays_selected_provider_and_binds_policy(self):
        from tools import a4_data_center as center
        from tests.a4_data_center_smoke import capture
        from tests.a4_primary_sources_smoke import NOW
        p.primary.now.return_value=NOW;p.market.current_session.return_value='2026-11-06'
        self.session='2026-11-06';self.now=NOW
        self.frames={s:frame.loc[:self.session] for s,frame in self.frames.items()}
        self.policy.update(available_at='2026-11-07T00:00:00Z',expires_at='2026-12-07T00:00:00Z')
        raw,pin=self.raw()
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);spec=capture(root/'macro');policies=root/'policy';policies.mkdir()
            (policies/'flow-research-policy.json').write_bytes(raw)
            p.stage(raw,pin,cutoff=NOW,output_root=root/'prices',
                adapters=dict(yfinance=self.bad('first'),alpaca_sip=self.good('second'),twelve_data=self.good('unused')))
            catalog,_=center.build([spec],cutoff=NOW,output_dir=root/'index',flow_policy_root=policies,
                flow_policy_sha256=pin,flow_price_root=root/'prices')
            flow=catalog['flow_relationships'];self.assertEqual(flow['status'],'CURRENT_VINTAGE_DESCRIPTIVE_ONLY')
            self.assertEqual(flow['price_selected_provider'],'alpaca_sip');self.assertTrue(flow['raw_http_originals_available'])
            self.assertEqual(len(flow['results']),448);self.assertFalse(catalog['training_admitted'])
            self.assertFalse(catalog['source_admitted']);self.assertEqual(catalog['current_diagnosis']['status'],'DATA_BLOCKED')
            changed=copy.deepcopy(self.policy);changed['providers'][1]['use_scope_sha256']='b'*64
            changed_raw=p.encoded(changed);changed_pin=p.digest(changed_raw)
            (policies/'flow-research-policy.json').write_bytes(changed_raw)
            rejected,_=center.build([spec],cutoff=NOW,output_dir=root/'relabel',flow_policy_root=policies,
                flow_policy_sha256=changed_pin,flow_price_root=root/'prices')
            self.assertEqual(rejected['flow_relationships']['status'],'BLOCKED')

    def test_http_original_is_not_required_or_fabricated_for_yahoo_selection(self):
        self.policy['providers']=[self.descriptor('alpaca_sip'),self.descriptor('yfinance')]
        self.policy['maximum_batch_calls_per_attempt']=2
        snapshot,view=self.collect(dict(alpaca_sip=self.bad('unavailable','ENTITLEMENT'),yfinance=self.good('selected')))
        p.verify_snapshot(view,p.encoded(snapshot))
        self.assertFalse(view['raw_http_originals_available']);self.assertFalse(view['training_admitted'])
        self.assertEqual(view['provider_attempts'][0]['reason'],'ENTITLEMENT')
        self.assertEqual(view['provider_attempts'][1]['backend_HTTP_count'],'UNKNOWN')

    def test_durable_chain_reuse_and_failed_claim_remain_one_session_attempt(self):
        raw,pin=self.raw();remote=MemoryArchive()
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            view=p.stage(raw,pin,cutoff=self.now,output_root=root/'ok',transport=remote,
                         adapters={name:self.good(name) for name in f.PROVIDERS})
            self.assertTrue((root/'ok/durable-completion.json').is_file())
            before=len(self.calls)
            p.stage(raw,pin,cutoff=self.now,output_root=root/'reuse',transport=remote,previous=view,
                    adapters={name:self.good(name) for name in f.PROVIDERS})
            self.assertEqual(len(self.calls),before)
            with self.assertRaisesRegex(ValueError,'SESSION_ALREADY_CONSUMED'):
                p.stage(raw,pin,cutoff=self.now,output_root=root/'duplicate',transport=remote,
                        adapters={name:self.good(name) for name in f.PROVIDERS})

    def test_failed_chain_evidence_is_stored_and_read_back_without_success_marker(self):
        raw,pin=self.raw();remote=MemoryArchive()
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'fail'
            with self.assertRaises(ValueError):p.stage(raw,pin,cutoff=self.now,output_root=root,transport=remote,
                adapters={name:self.bad(name) for name in f.PROVIDERS})
            evidence=(root/'provider-evidence.json').read_bytes();failure=json.loads((root/'failure.json').read_bytes())
            self.assertEqual(failure['provider_evidence_sha256'],p.digest(evidence))
            self.assertEqual(remote.objects[p.primary.PREFIX+'/objects/'+p.digest(evidence)],evidence)
            self.assertFalse((root/'durable-completion.json').exists())


if __name__=='__main__':unittest.main()
