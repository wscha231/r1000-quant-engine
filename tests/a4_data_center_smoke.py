"""Actual paired-codec integration, deterministic as-of views and failed attempts."""
import copy
from datetime import timedelta
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from tools import a4_data_center as d,a4_primary_sources as p,collect_a4_primary_data as c
from tools.macro_history_sources import encoded,digest
from tools.macro_research_checkpoint import LocalTransport
from tests.a4_primary_sources_smoke import NOW,archive,nyfed


def fetch(url,*args):
    feed=next(k for k,v in p.FEEDS.items() if v[0]==url)
    return nyfed(feed) if feed in {'sofr','tgcr','effr'} else archive(feed)


def capture(root,*,now=NOW,fetcher=fetch,transport=None,native=None):
    with patch.object(p,'now',return_value=now):
        c.collect(root,code_sha='a'*40,fetcher=fetcher,transport=transport,existing_input_root=native)
    return dict(root=str(root),execution_sha256=digest((root/'execution.json').read_bytes()))


class DataCenterTests(unittest.TestCase):
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
            with self.assertRaises(ValueError):d.build([spec],cutoff=NOW,output_dir=root/'view',transport=FailReceipt())
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

    def test_native_original_is_archived_and_remote_reference_replays_without_an_original_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);native=root/'native';native.mkdir();body=b'[]';sha=digest(body)
            request=dict(schema=d.market.REQUEST_SCHEMA_V2,market='US',session=d.market.current_session(NOW),available_at=NOW,
                expires_at=(p.clock(NOW)+timedelta(days=1)).isoformat(),inputs=[dict(kind='risk_context',path='context.json',
                sha256=sha,status='COLLECTED',collected_at=NOW)])
            raw=encoded(request);(native/'request.json').write_bytes(raw);(native/'request.sha256').write_text(digest(raw))
            (native/'context.json').write_bytes(body)
            remote=LocalTransport(root/'remote');spec=capture(root/'capture',transport=remote,native=native)
            a,ar=d.build([spec],cutoff=NOW,output_dir=root/'one',transport=remote)
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


if __name__=='__main__':unittest.main()
