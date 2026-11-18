"""Actual paired-codec integration, deterministic as-of views and failed attempts."""
import copy
from datetime import timedelta
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools import a4_data_center as d,a4_primary_sources as p,collect_a4_primary_data as c
from tools import a4_index_direction as index
from tools.macro_history_sources import encoded,digest
from tools.macro_research_checkpoint import LocalTransport
from tests.a4_primary_sources_smoke import NOW,archive,nyfed,retained_credit_input


def fetch(url,*args):
    feed=next(k for k,v in p.FEEDS.items() if v[0]==url)
    return nyfed(feed) if feed in {'sofr','tgcr','effr'} else archive(feed)


def capture(root,*,now=NOW,fetcher=fetch,transport=None,native=None):
    with patch.object(p,'now',return_value=now):
        c.collect(root,code_sha='a'*40,fetcher=fetcher,transport=transport,existing_input_root=native)
    return dict(root=str(root),execution_sha256=digest((root/'execution.json').read_bytes()))


def index_fixture(access,expires_at='2026-12-01T00:00:00Z'):
    access.mkdir()
    evidence={}
    for name in ('fred','sp500','nasdaq100'):
        raw=f'synthetic test permission {name}'.encode()
        (access/(name+'-permission.txt')).write_bytes(raw)
        evidence[name]=digest(raw)
    policy=encoded(dict(schema=index.POLICY,available_at='2026-10-01T00:00:00Z',
        expires_at=expires_at,purpose='PRIVATE_DESCRIPTIVE_RESEARCH',
        permissions=['KEYLESS_SCHEDULED_FRED_CSV','PRIVATE_DRIVE_RAW_AND_REPORT'],evidence_sha256=evidence))
    (access/'policy.json').write_bytes(policy)
    session=d.market.current_session(NOW)
    rows={series:f'DATE,{series}\n{session},{100+i}\n'.encode() for i,series in enumerate(index.SERIES)}
    return policy,rows


class DataCenterTests(unittest.TestCase):
    def test_fred_index_direction_respects_common_sessions_and_preserves_gaps(self):
        cutoff='2026-11-18T04:11:00Z'
        sp=b'observation_date,SP500\n2026-11-12,100\n2026-11-13,102\n2026-11-16,101\n2026-11-17,.\n'
        nd=b'DATE,NASDAQ100\n2026-11-12,200\n2026-11-13,202\n2026-11-16,203\n2026-11-17,210\n'
        paired={'SP500':(sp,cutoff),'NASDAQ100':(nd,cutoff)}
        result=index.describe(paired,cutoff=cutoff)
        self.assertEqual(result['status'],'DELAYED_COMMON_SESSION')
        self.assertEqual(result['expected_session'],'2026-11-17')
        self.assertEqual(result['common_session'],'2026-11-16')
        self.assertEqual(result['series']['SP500']['lag_sessions'],1)
        self.assertEqual(result['series']['NASDAQ100']['lag_sessions'],0)
        self.assertEqual(result['horizons'][0]['direction'],'MIXED')
        self.assertEqual(result['horizons'][0]['from_session'],'2026-11-13')
        self.assertAlmostEqual(result['horizons'][0]['price_returns']['NASDAQ100'],203/202-1)
        gap=dict(paired,SP500=(sp.replace(b'2026-11-13,102\n',b''),cutoff))
        self.assertEqual(index.describe(gap,cutoff=cutoff)['horizons'][0]['status'],'INCOMPLETE_WINDOW')
        absent=index.describe(dict(paired,NASDAQ100=None),cutoff=cutoff)
        self.assertEqual(absent['status'],'NO_COMMON_SESSION')
        self.assertFalse(absent['horizons'])
        with self.assertRaisesRegex(ValueError,'INDEX_CAPTURE_CLOCK'):
            index.describe(dict(paired,SP500=(sp,'2026-11-18T04:12:00Z')),cutoff=cutoff)
        with self.assertRaisesRegex(ValueError,'duplicate_or_future_observation'):
            index.describe(dict(paired,SP500=(sp+b'2026-11-18,105\n',cutoff)),cutoff=cutoff)

    def test_fred_index_hosted_capture_and_private_catalog_require_bound_permission(self):
        import yaml
        workflow=yaml.safe_load((Path(d.__file__).parents[1]/'.github/workflows/daily_crisis_monitor.yml').read_text())
        step=next(item for item in workflow['jobs']['monitor']['steps'] if item.get('id')=='a4_data_center')
        self.assertIn('A4_INDEX_DIRECTION_POLICY_SHA256',step['env'])
        self.assertIn('a4_index_direction.collect_approved(index_root,index_policy)',step['run'])
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            access=root/'permissions'
            body,rows=index_fixture(access)

            def fake_get(url):
                self.assertNotIn('api_key',url)
                return next(content for series,content in rows.items() if 'id='+series+'&' in url)

            with patch.object(index.fred,'utc_now',return_value=NOW), patch.object(index.fred,'request_bytes',side_effect=fake_get) as fetch_index:
                with self.assertRaisesRegex(ValueError,'INDEX_POLICY_HASH'):
                    index.collect_approved(access,'0'*64)
                fetch_index.assert_not_called()
                inputs=index.collect_approved(access,digest(body))
                self.assertEqual(fetch_index.call_count,2)

            transport=LocalTransport(root/'private')
            spec=capture(root/'capture')
            with patch.object(p,'now',return_value=NOW):
                catalog,receipt=d.build([spec],cutoff=NOW,output_dir=root/'view',transport=transport,
                    code_sha='a'*40,index_captures=inputs,index_policy_root=access,index_policy_sha256=digest(body))
            self.assertEqual(catalog['index_direction']['status'],'CURRENT_COMMON_SESSION')
            self.assertEqual(catalog['current_diagnosis']['status'],'DATA_BLOCKED')
            self.assertFalse(catalog['index_direction']['training_admitted'])
            self.assertEqual(transport.read(p.PREFIX+'/catalogs/'+receipt['catalog_sha256']+'.json'),encoded(catalog))
            execution_sha=digest(encoded(receipt))
            proof=json.loads(transport.read(p.PREFIX+'/index-verifications/'+execution_sha+'.json'))
            self.assertEqual(proof,dict(schema=index.VERIFICATION,execution_sha256=execution_sha,
                session=catalog['index_direction']['expected_session'],verified_at=NOW))
            for raw in [body,*rows.values()]:
                self.assertEqual(transport.read(p.PREFIX+'/objects/'+digest(raw)),raw)
            modified=d.index_identity()
            modified[Path(index.__file__).name]='0'*64
            with patch.object(d,'index_identity',return_value=modified),self.assertRaisesRegex(ValueError,'DATA_CENTER_INDEX_DIRECTION_CODE_CHANGED'):
                d.build([spec],cutoff=NOW,output_dir=root/'changed',index_captures=inputs,
                    index_policy_root=access,index_policy_sha256=digest(body))
            self.assertFalse((root/'changed').exists())
            (access/'sp500-permission.txt').write_bytes(b'changed')
            refused,_=d.build([spec],cutoff=NOW,output_dir=root/'refused',index_captures=inputs,
                index_policy_root=access,index_policy_sha256=digest(body))
            self.assertEqual(refused['index_direction']['status'],'BLOCKED')

    def test_fred_index_publication_stops_at_rights_and_session_boundaries(self):
        expired='2026-11-07T10:00:01+00:00'
        new_session='2026-11-09T21:16:00+00:00'
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            spec=capture(root/'capture')
            for boundary,when in (('policy_write',expired),('policy_write',new_session),
                                  ('catalog_read',new_session),('execution_read',new_session)):
                with self.subTest(boundary=boundary,when=when):
                    attempt=root/(boundary+'-'+when[:10])
                    attempt.mkdir()
                    access=attempt/'permissions'
                    policy,rows=index_fixture(access,expires_at=expired if when==expired else '2026-12-01T00:00:00Z')
                    inputs={series:(raw,NOW) for series,raw in rows.items()}
                    instant=NOW

                    class Rollover(LocalTransport):
                        remote_verified=True

                        def write(self,path,raw):
                            nonlocal instant
                            super().write(path,raw)
                            if boundary=='policy_write' and raw==policy:
                                instant=when

                        def read(self,path):
                            nonlocal instant
                            raw=super().read(path)
                            if (boundary=='catalog_read' and '/catalogs/' in path or
                                boundary=='execution_read' and '/index-executions/' in path):
                                instant=when
                            return raw

                    remote=Rollover(attempt/'remote')
                    with patch.object(p,'now',side_effect=lambda:instant),self.assertRaisesRegex(ValueError,
                        'DATA_CENTER_(PUBLICATION_FAILED|EXECUTION_READBACK_FAILED)'):
                        d.build([spec],cutoff=NOW,output_dir=attempt/'view',transport=remote,code_sha='a'*40,
                            index_captures=inputs,index_policy_root=access,index_policy_sha256=digest(policy))
                    if boundary=='policy_write':
                        self.assertEqual(remote.names(p.PREFIX+'/objects'),[digest(policy)])
                        self.assertFalse(remote.names(p.PREFIX+'/catalogs'))
                    self.assertEqual(len(remote.names(p.PREFIX+'/index-executions')),int(boundary=='execution_read'))
                    self.assertFalse(remote.names(p.PREFIX+'/index-verifications'))
                    self.assertFalse((attempt/'view/execution.json').exists())
                    failure=json.loads((attempt/'view/publication_failed.json').read_bytes())
                    self.assertEqual(failure['stage'],'EXECUTION_RECEIPT' if boundary=='execution_read' else 'CATALOG_OR_REPORT')

    def test_existing_core_originals_are_joined_without_admission_or_provider_calls(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);spec=capture(root/'capture')
            with patch.object(p,'capture',side_effect=AssertionError('provider called')):
                catalog,receipt=d.build([spec],cutoff=NOW,output_dir=root/'view')
            self.assertEqual(len(catalog['selected_sources']),6)
            self.assertTrue(all(s['status']=='VERIFIED_BYTES_ONLY' for s in catalog['selected_sources'].values()))
            self.assertEqual(catalog['current_diagnosis']['status'],'DATA_BLOCKED')
            self.assertEqual(catalog['historical_evaluation']['status'],'BLOCKED')
            self.assertEqual(catalog['future_view']['status'],'SCENARIO_CONTEXT_ONLY')
            self.assertFalse(catalog['future_view']['forecasts_calibrated'])
            self.assertFalse(catalog['source_admitted']);self.assertFalse(catalog['training_admitted'])
            self.assertEqual(catalog['provider_requests_executed'],0)
            self.assertEqual(len(catalog['learning']['missing_targets']),14)
            self.assertEqual(receipt['status'],'LOCAL_RESEARCH_INDEX_COMPLETE')

    def test_same_inputs_and_equivalent_utc_cutoff_reuse_catalog_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);spec=capture(root/'capture')
            a,ar=d.build([spec],cutoff=NOW,output_dir=root/'one')
            b,br=d.build([spec],cutoff=NOW.replace('+00:00','Z'),output_dir=root/'two')
            self.assertEqual(ar['catalog_sha256'],br['catalog_sha256']);self.assertEqual(a,b)

    def test_future_capture_addition_does_not_change_prior_view(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);old=capture(root/'old')
            future=capture(root/'future',now=(p.clock(NOW)+timedelta(hours=1)).isoformat())
            a,ar=d.build([old],cutoff=NOW,output_dir=root/'one')
            b,br=d.build([old,future],cutoff=NOW,output_dir=root/'two')
            self.assertEqual(ar['catalog_sha256'],br['catalog_sha256']);self.assertEqual(a,b)
            audit=json.loads((root/'two/audit.json').read_bytes())
            self.assertEqual(audit['excluded_attempts'][0]['status'],'EXCLUDED_FUTURE_ATTEMPT')

    def test_latest_failed_capture_is_not_replaced_by_old_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);old=capture(root/'old');later=(p.clock(NOW)+timedelta(hours=1)).isoformat()
            def failure(url,*args):
                if url==p.FEEDS['h8'][0]:raise HTTPError(url,503,'unavailable',{},None)
                return fetch(url,*args)
            new=capture(root/'new',now=later,fetcher=failure)
            catalog,_=d.build([old,new],cutoff=later,output_dir=root/'view')
            self.assertEqual(catalog['selected_sources']['h8']['status'],'BLOCKED')
            self.assertEqual(catalog['selected_sources']['h8']['execution_sha256'],new['execution_sha256'])
            self.assertEqual(catalog['current_diagnosis']['report_mode'],'BLOCKED_LOCAL_DIAGNOSTIC_ONLY')

    def test_tampered_original_blocks_its_latest_feed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);spec=capture(root/'capture');execution=json.loads((root/'capture/execution.json').read_bytes())
            meta=json.loads((root/'capture/archive/generations'/f"{execution['generation_sha256s'][0]}.json").read_bytes())
            (root/'capture/archive/objects'/meta['original_sha256']).write_bytes(b'changed')
            catalog,_=d.build([spec],cutoff=NOW,output_dir=root/'view')
            self.assertEqual(catalog['selected_sources']['sofr']['status'],'BLOCKED')
            self.assertEqual(catalog['current_diagnosis']['status'],'DATA_BLOCKED')

    def test_version_inventory_replays_only_latest_originals_without_duplicate_samples(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);old=capture(root/'old');later=(p.clock(NOW)+timedelta(hours=1)).isoformat()
            new=capture(root/'new',now=later)
            with patch.object(p,'read_generation',wraps=p.read_generation) as read:
                catalog,_=d.build([new,old],cutoff=later,output_dir=root/'view')
            # Six paired source reads. The A4 analysis re-normalizes inputs,
            # but does not call this archive-reader boundary again.
            self.assertEqual(read.call_count,6)
            self.assertEqual(sum(s['status']=='ARCHIVED_METADATA_ONLY' for s in catalog['sources']),6)
            self.assertTrue(all(s['execution_sha256']==new['execution_sha256'] for s in catalog['selected_sources'].values()))

    def test_late_publication_of_old_capture_does_not_displace_fresher_observations(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);old=capture(root/'old');later=(p.clock(NOW)+timedelta(hours=1)).isoformat()
            new=capture(root/'new',now=later)
            raw=json.loads((root/'old/execution.json').read_bytes())
            raw['completed_at']=(p.clock(NOW)+timedelta(hours=2)).isoformat()
            body=encoded(raw);(root/'old/execution.json').write_bytes(body);old['execution_sha256']=digest(body)
            catalog,_=d.build([old,new],cutoff=raw['completed_at'],output_dir=root/'view')
            self.assertTrue(all(s['execution_sha256']==new['execution_sha256'] for s in catalog['selected_sources'].values()))

    def test_monetary_units_scopes_and_weekly_grain_remain_native(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);spec=capture(root/'capture');catalog,_=d.build([spec],cutoff=NOW,output_dir=root/'view')
            h8=catalog['selected_sources']['h8']['series'];h41=catalog['selected_sources']['h41']['series']
            self.assertEqual(len(h8),20)
            deposits=next(r for r in h8 if r['series']=='deposits_all')
            reserves=next(r for r in h41 if r['series']=='reserves_week_average')
            self.assertEqual(deposits['native_frequency'],'weekly');self.assertEqual(deposits['observations'],1)
            self.assertEqual(deposits['latest']['unit'],'billions_usd');self.assertEqual(deposits['latest']['bank_aggregation'],'CB')
            self.assertEqual(reserves['latest']['unit'],'millions_usd')
            self.assertEqual(reserves['latest']['measurement_basis'],'WEEK_AVERAGE')
            self.assertEqual(reserves['historical_use'],'FORWARD_CAPTURE_ONLY')

    def test_old_request_is_not_used_as_a_current_native_operand(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);spec=capture(root/'capture')
            catalog,_=d.build([spec],cutoff=(p.clock(NOW)+timedelta(days=4)).isoformat(),output_dir=root/'view')
            self.assertEqual(catalog['current_diagnosis']['status'],'DATA_BLOCKED')
            req=json.loads((root/'view/inputs/request.json').read_bytes())
            self.assertFalse(any(s['kind'].startswith('risk_') for s in req['inputs']))

    def test_unreviewed_learning_policy_does_not_read_a_payload(self):
        with patch.object(d.cycle,'load_learning',side_effect=AssertionError('unreviewed original read')):
            value=d.learning_readiness('/unused/private',None,NOW)
        self.assertEqual(value['status'],'BLOCKED');self.assertFalse(value['model_fit_performed'])

    def test_focused_benchmark_readiness_uses_actual_session_records(self):
        from tests.a4_macro_learning_smoke import fixture
        payload,policy,resolve=fixture()
        payload['prices']['QQQ']=copy.deepcopy(payload['prices']['SPY'])
        binding=next(iter(policy['source_bindings'].values()))
        binding['source_ids'].append('price:QQQ')
        policy['input_pins']=[d.digest(d.encoded(payload))]
        with patch.object(d.cycle,'load_learning',return_value=(payload,policy,resolve)):
            out=d.learning_readiness('/synthetic',d.digest(d.encoded(policy)),payload['cutoff'])
        self.assertEqual(out['status'],'PARTIAL_VALIDATED_INPUTS')
        self.assertEqual(out['benchmark_research_status'],'VALIDATED_BENCHMARK_INPUTS_NOT_EXECUTED')
        self.assertEqual(out['missing_benchmark_targets'],[])
        self.assertEqual(len(out['missing_targets']),12)
        self.assertEqual(out['target_prices']['QQQ']['valid_prices'],len(payload['sessions']))
        self.assertFalse(out['model_fit_performed'])
        for row in payload['prices']['QQQ']:row['value']=None
        policy['input_pins']=[d.digest(d.encoded(payload))]
        with patch.object(d.cycle,'load_learning',return_value=(payload,policy,resolve)):
            out=d.learning_readiness('/synthetic',d.digest(d.encoded(policy)),payload['cutoff'])
        self.assertEqual(out['benchmark_research_status'],'BLOCKED')
        self.assertEqual(out['missing_benchmark_targets'],['QQQ'])
        self.assertEqual(out['target_prices']['QQQ']['valid_prices'],0)

    def test_bad_benchmark_price_basis_does_not_open_focused_readiness(self):
        from tests.a4_macro_learning_smoke import fixture
        payload,policy,resolve=fixture()
        for row in payload['prices']['SPY']:row['return_basis']='RAW_UNADJUSTED'
        policy['input_pins']=[d.digest(d.encoded(payload))]
        with patch.object(d.cycle,'load_learning',return_value=(payload,policy,resolve)):
            out=d.learning_readiness('/synthetic',d.digest(d.encoded(policy)),payload['cutoff'])
        self.assertEqual(out['status'],'BLOCKED')
        self.assertEqual(out['benchmark_research_status'],'BLOCKED')

    def test_policy_expiry_at_execution_blocks_old_benchmark_inputs(self):
        from tests.a4_macro_learning_smoke import fixture
        payload,policy,resolve=fixture()
        policy['expires_at']=(p.clock(payload['cutoff'])+timedelta(minutes=10)).isoformat()
        cutoff=(p.clock(payload['cutoff'])+timedelta(minutes=20)).isoformat()
        with patch.object(d.cycle,'load_learning',return_value=(payload,policy,resolve)):
            out=d.learning_readiness('/synthetic',d.digest(d.encoded(policy)),cutoff)
        self.assertEqual(out['status'],'BLOCKED')
        self.assertEqual(out['benchmark_research_status'],'BLOCKED')
        self.assertEqual(out['target_prices'],{})

    def test_duplicate_wrong_pin_existing_output_and_overlapping_root_refuse(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);spec=capture(root/'capture')
            for specs,out in [([spec,spec],root/'duplicate'),
                ([dict(spec,execution_sha256='0'*64)],root/'wrong'),([spec],root/'capture'),([spec],root/'capture/inside')]:
                with self.assertRaises(ValueError):d.build(specs,cutoff=NOW,output_dir=out)

    def test_read_budget_is_shared_across_source_readers(self):
        budget={'bytes':0}
        class T:
            def read(self,path):return b'1234'
        a=d.OriginalReader(T(),budget=budget);b=d.OriginalReader(T(),budget=budget)
        with patch.object(d,'MAX_BYTES',7):
            a.read(p.PREFIX+'/objects/'+'a'*64)
            with self.assertRaises(ValueError):b.read(p.PREFIX+'/objects/'+'b'*64)
        with self.assertRaises(ValueError):a.read(p.PREFIX+'/objects/../secrets')

    def test_publication_receipt_failure_leaves_a_separate_failure_witness(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);remote=LocalTransport(root/'remote');spec=capture(root/'capture',transport=remote)
            class FailReceipt:
                remote_verified=True
                def read(self,path):return remote.read(path)
                def write(self,path,raw):
                    if '/index-executions/' in path:raise ValueError('synthetic')
                    remote.write(path,raw)
            with self.assertRaises(ValueError):d.build([spec],cutoff=NOW,output_dir=root/'view',transport=FailReceipt(),code_sha='b'*40)
            failure=json.loads((root/'view/publication_failed.json').read_bytes())
            self.assertEqual(failure['stage'],'EXECUTION_RECEIPT')

    def test_legacy_metadata_does_not_admit_originals_or_repair_a_missing_execution(self):
        catalog=dict(schema='long-history-catalog-v1',generation=1,datasets={'current/UNRATE':{'status':'COLLECTED'}},
            eligible_for_selector=False,locations={})
        catalog_raw=encoded(catalog);commit=dict(schema='long-history-commit-v1',generation=1,parent=None,
            catalog=digest(catalog_raw),created_at=NOW,run_id='fixture')
        commit_raw=encoded(commit);sha=digest(commit_raw)
        class Metadata:
            def names(self,path):return [sha] if path.endswith('/commits') else []
            def read(self,path):return commit_raw if '/commits/' in path else catalog_raw
        value=d.lake_metadata(Metadata(),NOW)
        self.assertEqual(value['status'],'METADATA_ONLY');self.assertEqual(value['matching_execution_metadata'],[])
        self.assertFalse(value['execution_verified']);self.assertFalse(value['original_packs_verified'])
        self.assertFalse(value['training_admitted'])

    def test_legacy_fork_or_quota_does_not_fall_back_to_a_previous_catalog(self):
        class Broken:
            def names(self,path):raise ValueError('quota')
        self.assertEqual(d.lake_metadata(Broken(),NOW)['status'],'METADATA_BLOCKED')

    def test_future_legacy_commit_and_receipts_do_not_change_a_prior_view(self):
        with tempfile.TemporaryDirectory() as tmp:
            remote=LocalTransport(Path(tmp)/'remote')
            def put(folder,value):
                raw=encoded(value);sha=digest(raw);remote.write('long-history-v1/'+folder+'/'+sha,raw);return sha
            catalog=put('catalogs',dict(schema='long-history-catalog-v1',generation=1,
                datasets={'current/UNRATE':{'status':'COLLECTED'}},eligible_for_selector=False,locations={}))
            commit=put('commits',dict(schema='long-history-commit-v1',generation=1,parent=None,
                catalog=catalog,created_at=NOW,run_id='fixture'))
            receipt=put('executions',dict(schema='long-history-execution-v1',commit_sha256=commit,created_at=NOW))
            a=d.lake_metadata(remote,NOW)
            later=(p.clock(NOW)+timedelta(hours=1)).isoformat()
            # The future catalog need not be readable to reproduce the earlier view.
            future_catalog='f'*64
            future_commit=put('commits',dict(schema='long-history-commit-v1',generation=2,parent=commit,
                catalog=future_catalog,created_at=later,run_id='future'))
            put('executions',dict(schema='long-history-execution-v1',commit_sha256=future_commit,created_at=later))
            put('executions',dict(schema='long-history-execution-v1',commit_sha256=commit,created_at=later))
            b=d.lake_metadata(remote,NOW)
            self.assertEqual(a,b)
            self.assertEqual(b['matching_execution_metadata'],[receipt])
            self.assertEqual(b['generation'],1)
            self.assertEqual(d.lake_metadata(remote,later)['status'],'METADATA_BLOCKED')

    def test_matching_legacy_receipt_with_missing_clock_is_not_admitted_as_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            remote=LocalTransport(Path(tmp)/'remote')
            catalog=encoded(dict(schema='long-history-catalog-v1',generation=1,
                datasets={},eligible_for_selector=False,locations={}))
            csha=digest(catalog);remote.write('long-history-v1/catalogs/'+csha,catalog)
            commit=encoded(dict(schema='long-history-commit-v1',generation=1,parent=None,
                catalog=csha,created_at=NOW,run_id='fixture'))
            sha=digest(commit);remote.write('long-history-v1/commits/'+sha,commit)
            receipt=encoded(dict(commit_sha256=sha));remote.write('long-history-v1/executions/'+digest(receipt),receipt)
            self.assertEqual(d.lake_metadata(remote,NOW)['status'],'METADATA_BLOCKED')

    def test_native_original_is_archived_and_remote_reference_replays_without_an_original_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);native=root/'native';native.mkdir();body=b'[]';sha=digest(body)
            request=dict(schema=d.market.REQUEST_SCHEMA_V2,market='US',session=d.market.current_session(NOW),available_at=NOW,
                expires_at=(p.clock(NOW)+timedelta(days=1)).isoformat(),inputs=[dict(kind='risk_context',path='context.json',
                sha256=sha,status='COLLECTED',collected_at=NOW)])
            raw=encoded(request);(native/'request.json').write_bytes(raw);(native/'request.sha256').write_text(digest(raw))
            (native/'context.json').write_bytes(body)
            remote=LocalTransport(root/'remote');spec=capture(root/'capture',transport=remote,native=native)
            a,ar=d.build([spec],cutoff=NOW,output_dir=root/'one',transport=remote,code_sha='b'*40)
            self.assertEqual(remote.read(p.PREFIX+'/objects/'+sha),body)
            sparse=d.restore_reference(remote,spec['execution_sha256'],root/'reference',cutoff=NOW)
            self.assertFalse((root/'reference/archive').exists())
            b,br=d.build([sparse],cutoff=NOW,output_dir=root/'two',source_transport=remote)
            self.assertEqual(ar['catalog_sha256'],br['catalog_sha256']);self.assertEqual(a,b)
            self.assertEqual(b['native_input_state']['status'],'ORIGINAL_HASHES_VERIFIED')

    def test_rebound_native_request_is_not_authorized_by_its_self_computed_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);remote=LocalTransport(root/'remote');spec=capture(root/'capture',transport=remote)
            path=root/'capture/inputs/request.json';request=json.loads(path.read_bytes())
            body=b'[]';sha=digest(body);request['inputs'].append(dict(kind='risk_context',path='context.json',
                sha256=sha,status='COLLECTED',collected_at=NOW))
            path.write_bytes(encoded(request));(root/'capture/inputs/context.json').write_bytes(body)
            catalog,_=d.build([spec],cutoff=NOW,output_dir=root/'view')
            self.assertEqual(catalog['native_input_state']['status'],'BLOCKED')
            result=json.loads((root/'view/inputs/request.json').read_bytes())
            self.assertFalse(any(r['kind']=='risk_context' for r in result['inputs']))

    def test_credit_originals_survive_collection_index_publication_and_cold_restore(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);request,bodies=retained_credit_input(root/'native');remote=LocalTransport(root/'remote')
            spec=capture(root/'capture',transport=remote,native=root/'native')
            a,ar=d.build([spec],cutoff=NOW,output_dir=root/'one',transport=remote,code_sha='b'*40)
            for original in request['inputs'][1:3]:
                self.assertEqual(remote.read(p.PREFIX+'/objects/'+original['sha256']),bodies[original['path']])
            sparse=d.restore_reference(remote,spec['execution_sha256'],root/'reference',cutoff=NOW)
            with patch.object(p,'capture',side_effect=AssertionError('provider called')):
                b,br=d.build([sparse],cutoff=NOW,output_dir=root/'two',source_transport=remote)
            self.assertEqual(a,b);self.assertEqual(ar['catalog_sha256'],br['catalog_sha256'])
            self.assertEqual(b['native_input_state']['operands'],1)
            self.assertEqual(b['native_input_state']['credit_originals'],2)
            report=json.loads((root/'two/market_analysis.json').read_bytes())
            self.assertEqual(report['macro_direction_inputs']['hy_oas']['value'],3.2)
            self.assertEqual(report['macro_direction_inputs']['ig_oas']['available_at'],NOW)
            self.assertEqual(report['status'],'DATA_BLOCKED')
            self.assertFalse(br['model_fit_performed']);self.assertFalse(br['training_admitted'])

    def test_changed_newest_credit_original_never_falls_back_to_an_older_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);_,bodies=retained_credit_input(root/'native');remote=LocalTransport(root/'remote')
            first=capture(root/'first',transport=remote,native=root/'native')
            later=(p.clock(NOW)+timedelta(minutes=1)).isoformat()
            second=capture(root/'second',now=later,transport=remote,native=root/'native')
            (root/'second/inputs/native'/digest(bodies['hy.csv'])).write_bytes(b'tampered')
            catalog,_=d.build([first,second],cutoff=later,output_dir=root/'view')
            self.assertEqual(catalog['native_input_state']['status'],'BLOCKED')
            self.assertEqual(catalog['native_input_state']['credit_originals'],0)
            request=json.loads((root/'view/inputs/request.json').read_bytes())
            self.assertFalse(any(c.retained_source_input(s) for s in request['inputs']))

    def test_legacy_v1_core_receipt_is_read_without_rewriting_its_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);spec=capture(root/'capture');path=root/'capture/execution.json';value=json.loads(path.read_bytes())
            for key in ('requested_feeds','economic_inputs_enabled','financing_inputs_enabled'):value.pop(key,None)
            raw=encoded(value);path.write_bytes(raw);spec['execution_sha256']=digest(raw)
            catalog,_=d.build([spec],cutoff=NOW,output_dir=root/'view')
            self.assertTrue(catalog['attempts'][0]['legacy_core_profile_inferred'])
            self.assertEqual(set(catalog['selected_sources']),set(c.FEED_ORDER))
            self.assertEqual(digest(path.read_bytes()),spec['execution_sha256'])
            value['generation_sha256s'].append('0'*64);value['originals']=7
            raw=encoded(value);path.write_bytes(raw);spec['execution_sha256']=digest(raw)
            with self.assertRaises(ValueError):d.build([spec],cutoff=NOW,output_dir=root/'extended')

    def test_failed_remote_attempt_does_not_require_unpublished_generation_objects(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);remote=LocalTransport(root/'remote')
            def failure(url,*args):
                if url==p.FEEDS['h8'][0]:raise HTTPError(url,503,'unavailable',{},None)
                return fetch(url,*args)
            spec=capture(root/'capture',transport=remote,fetcher=failure)
            catalog,receipt=d.build([spec],cutoff=NOW,output_dir=root/'view',transport=remote,code_sha='b'*40)
            self.assertFalse(receipt['selected_core_verified']);self.assertEqual(receipt['analysis_publication'],[])
            self.assertTrue(all(s['status']=='BLOCKED' for s in catalog['selected_sources'].values()))

    def test_changed_code_or_locator_during_build_fails_before_catalog_publication(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);spec=capture(root/'capture');before=d.index_identity();after=dict(before)
            after['research_data_access.json']='0'*64
            with patch.object(d,'index_identity',side_effect=[before,after]),self.assertRaises(ValueError):
                d.build([spec],cutoff=NOW,output_dir=root/'view')
            self.assertFalse((root/'view/catalog.json').exists())

    def test_descriptive_history_keeps_exact_weekly_changes_and_is_not_predictive(self):
        rows=[]
        for i in range(5):
            date=(p.day('2026-09-02')+timedelta(weeks=i)).isoformat()
            for key,value in [('tga_week_average',i*i),('reserves_week_average',100-2*i*i)]:
                rows.append(dict(logical_id=key,observation_date=date,value=value,available_at=NOW,
                    frequency='weekly',unit='millions_usd',measurement_basis='WEEK_AVERAGE',seasonal_basis='NSA'))
        result=d.describe_weekly_history(rows,'h41',NOW)[0]
        self.assertEqual(result['paired_changes'],4);self.assertAlmostEqual(result['pearson_correlation'],-1)
        self.assertFalse(result['historical_decision_tested']);self.assertFalse(result['predictive_evidence'])
        future=dict(rows[-1],observation_date='2026-12-02',available_at='2026-12-03T00:00:00Z',value=999)
        self.assertEqual(d.describe_weekly_history(rows+[future],'h41',NOW)[0],result)
        missing=[r for r in rows if r['observation_date']!='2026-09-16']
        self.assertEqual(d.describe_weekly_history(missing,'h41',NOW)[0]['paired_changes'],2)

    def test_description_refuses_duplicate_vintages_and_does_not_fill_constant_correlation(self):
        rows=[]
        for i in range(5):
            for key,value in [('deposits_all',100+i),('loans_all',100+i*i),('cash_assets_all',50)]:
                rows.append(dict(logical_id=key,observation_date=(p.day('2026-09-02')+timedelta(weeks=i)).isoformat(),
                    value=value,available_at=NOW,frequency='weekly',unit='billions_usd',
                    measurement_basis='WEDNESDAY_LEVEL',seasonal_basis='SA',bank_aggregation='CB'))
        result=d.describe_weekly_history(rows,'h8',NOW)
        self.assertTrue(all(r['pearson_correlation'] is None for r in result))
        with self.assertRaises(ValueError):d.describe_weekly_history(rows+[dict(rows[0])],'h8',NOW)


if __name__=='__main__':unittest.main()
