"""Offline Stage3 fixtures; these are not real company/source or capture proofs."""
from __future__ import annotations
import argparse
import copy
import gzip
import json
from pathlib import Path
import sys
import tempfile
import unittest
import io
import zipfile
from unittest import mock

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'research'));sys.path.insert(0,str(ROOT/'tests'))
import a2_a1_discovery_gate_v1_smoke as discovery_fixture
from research import a2_a1_ohlcv_handoff_v1 as handoff
from tools import alpaca_sip_private_backfill_v1 as source
from tools import run_agent_board as board
from tools import materialize_system_state as materializer
import system_state_materializer_smoke as state_fixtures

h=handoff.h
DAYS=['2016-01-04','2016-01-05','2016-01-06','2016-01-07']


def archive(days, *, bad_open=False, start='2016-01-04', end='2016-01-09'):
    bars=[dict(t=d+'T05:00:00Z',o=10,h=12,l=9,c=11,v=100) for d in days]
    normalized=[]
    for adjustment in ('raw','split'):
        normalized += source.normalize(bars,'S0',adjustment,start,end)
    raw_bars=copy.deepcopy(bars)
    if bad_open and raw_bars:del raw_bars[0]['o']
    payload=source.encoded(dict(bars={'S0':raw_bars},next_page_token=None))
    sha=h.digest(payload);name=sha+'.json'
    pages=[dict(member=name,sha256=sha,bytes=len(payload),page=0,symbols=['S0'],adjustment=a)
           for a in ('raw','split')]
    meta=dict(schema=source.SCHEMA,source=source.SOURCE,symbols=['S0'],
        collected=['S0'] if days else [],no_bars=[] if days else ['S0'],start=start,
        end=end,asof=source.mapping_asof(end),seed_sha256='a'*64,source_sha='b'*40,
        pages=pages,raw_adjustments=['raw','split'],historical_identity_verified=False,
        pit_verified=False,source_admission=False,commercial_use_authorized=False)
    raw=source.zip_bytes({name:payload,'capture.json':source.encoded(meta)})
    norm=gzip.compress(b''.join(source.encoded(x) for x in normalized),mtime=0)
    receipt={k:v for k,v in meta.items() if k!='raw_adjustments'}
    receipt.update(scope='PRIVATE_RESEARCH_ONLY',pages=2,rows=len(normalized),readback_verified=True,
        raw_object={'sha256':h.digest(raw)},normalized_object={'sha256':h.digest(norm)})
    return raw,norm,h.canonical(receipt)


def fixture(days=DAYS, *, state='AVAILABLE', country='US', cutoff=discovery_fixture.CUTOFF, bad_open=False):
    events,context,memory=discovery_fixture.bundle(country)
    # A current A0 fixture can refresh its explicit metadata without inventing
    # historical publication: source graph/original publication bytes stay fixed.
    from datetime import timedelta
    expiry=(h.stamp(cutoff)+timedelta(days=1)).isoformat()
    events[0]['expires_at']=expiry
    context['identities'][0]['evidence_ref']['expires_at']=expiry
    memory['EVENTS']=h.canonical(dict(schema_version='a2-event-handoff-v1',as_of=cutoff,
        events=events,research_only=True,authority=h.closed()))
    memory['CONTEXT']=h.canonical(context)
    sid=context['identities'][0]['security_id']
    memory['CATALOG']=h.canonical(dict(schema='a1-ohlcv-catalog-snapshot-v1',as_of=cutoff,
        securities=[dict(security_id=sid,state=state,receipt_ids=['RECEIPT'] if state=='AVAILABLE' else [])]))
    memory['CALENDAR']=h.canonical(dict(schema='a1-ohlcv-session-calendar-v1',country=country,
        covered_start='2016-01-04',covered_end_exclusive='2016-01-08',as_of=cutoff,
        source_url='https://example.test/calendar',sessions=[dict(date=d,close_at=d+'T21:00:00Z') for d in DAYS]))
    memory['POLICY']=h.canonical(dict(schema='a1-ohlcv-request-policy-v1',campaign_key='SYNTHETIC_ONLY',
        provider=source.SOURCE if country=='US' else 'KR_PYKRX_EXISTING_CLIENT',
        feed='sip' if country=='US' else 'KRX',authorization_sha256=None,
        usage_evidence_sha256=None,scope_start='2016-01-04',scope_end_exclusive='2016-01-08',
        remaining_provider_gets=20))
    if state=='AVAILABLE':memory['RAW'],memory['NORM'],memory['RECEIPT']=archive(days,bad_open=bad_open)
    refs={aid:{'sha256':h.digest(raw)} for aid,raw in memory.items()}
    inventory=dict(schema=handoff.SCHEMA,events_id='EVENTS',context_id='CONTEXT',catalog_id='CATALOG',
        targets=[dict(security_id=sid,start='2016-01-04',end_exclusive='2016-01-08',
                      calendar_id='CALENDAR',policy_id='POLICY')],prior_requests_id=None,artifacts=refs)
    return inventory,memory


def plan(inventory,memory,cutoff=discovery_fixture.CUTOFF):
    return handoff.build_plan(inventory,h.MemoryArtifacts(memory),cutoff=cutoff)


def put(inventory,memory,aid,value):
    memory[aid]=h.canonical(value)
    inventory['artifacts'][aid]={'sha256':h.digest(memory[aid])}


class OHLCVHandoffTests(unittest.TestCase):
    def test_no_data_target_ignores_archived_bars_before_and_after_window(self):
        for days in (['2016-01-04'],['2016-01-08'],['2016-01-04','2016-01-08']):
            with self.subTest(days=days):
                inventory,memory=fixture(days)
                inventory['targets'][0]['start']='2016-01-05'
                for aid,raw in zip(('EMPTY_RAW','EMPTY_NORM','EMPTY_RECEIPT'),
                                   archive([],start='2016-01-05',end='2016-01-08')):
                    memory[aid]=raw;inventory['artifacts'][aid]={'sha256':h.digest(raw)}
                catalog=h.decode(memory['CATALOG'])
                catalog['securities'][0]['receipt_ids']=['EMPTY_RECEIPT']
                put(inventory,memory,'CATALOG',catalog)
                self.assertEqual(plan(inventory,memory)['coverage_results'][0]['coverage_action'],'NO_DATA')
                catalog['securities'][0]['receipt_ids'].append('RECEIPT')
                put(inventory,memory,'CATALOG',catalog)
                result=plan(inventory,memory)
                self.assertEqual(result['coverage_results'][0]['coverage_action'],'NO_DATA')
                self.assertEqual(len(result['coverage_results'][0]['receipt_sha256s']),2)
                self.assertEqual(result['requests'],[])
                self.assertEqual(result['dispatch_count'],0)
                self.assertFalse(any(result['authority'].values()))

    def test_in_window_bar_conflicting_with_no_data_still_refuses(self):
        inventory,memory=fixture(['2016-01-04','2016-01-05'])
        inventory['targets'][0]['start']='2016-01-05'
        for aid,raw in zip(('EMPTY_RAW','EMPTY_NORM','EMPTY_RECEIPT'),
                           archive([],start='2016-01-05',end='2016-01-08')):
            memory[aid]=raw;inventory['artifacts'][aid]={'sha256':h.digest(raw)}
        catalog=h.decode(memory['CATALOG']);catalog['securities'][0]['receipt_ids'].append('EMPTY_RECEIPT')
        put(inventory,memory,'CATALOG',catalog)
        result=plan(inventory,memory)
        self.assertEqual(result['coverage_results'][0]['status'],'BLOCKED')
        self.assertIn('PRICE_NO_DATA_CONFLICT',result['coverage_results'][0]['blockers'])
        self.assertEqual(result['requests'],[])

    def test_three_coverage_actions_with_original_archive_verifier(self):
        for days,state,expected in ((DAYS,'AVAILABLE','REUSE_EXISTING'),
            (DAYS[:2],'AVAILABLE','INCREMENTAL_ONLY'),([], 'NOT_STORED','BACKFILL_REQUIRED')):
            with self.subTest(expected=expected):
                result=plan(*fixture(days,state=state))
                self.assertEqual(result['coverage_results'][0]['coverage_action'],expected)
                request=result['requests'][0]
                self.assertEqual(request['schema'],'A2_TO_A1_OHLCV_REQUEST')
                self.assertFalse(request['ready_for_collection'])
                self.assertFalse(any(request['authority'].values()))
                self.assertEqual(result['dispatch_count'],0)

    def test_incremental_range_has_no_earlier_fetch(self):
        result=plan(*fixture(DAYS[:2]))
        self.assertEqual(result['requests'][0]['missing_ranges'],
            [dict(start='2016-01-06',end_exclusive='2016-01-08')])

    def test_internal_gap_is_backfill_not_recent_only(self):
        result=plan(*fixture([DAYS[0],DAYS[2],DAYS[3]]))
        self.assertEqual(result['requests'][0]['action'],'BACKFILL_REQUIRED')
        self.assertEqual(result['requests'][0]['missing_ranges'],
            [dict(start='2016-01-05',end_exclusive='2016-01-06')])

    def test_unknown_not_absence_and_KR_cache_not_raw_proof(self):
        for args,reason in ((dict(state='UNKNOWN'),'COVERAGE_UNKNOWN'),
                           (dict(country='KR'),'COVERAGE_ADAPTER_NOT_VERIFIED')):
            result=plan(*fixture(**args))
            self.assertEqual(result['requests'],[])
            self.assertIn(reason,result['coverage_results'][0]['blockers'])
        result=plan(*fixture(country='KR',state='NOT_STORED'))
        self.assertEqual(result['requests'][0]['identity']['ticker'],'005930')
        self.assertFalse(result['requests'][0]['ready_for_collection'])

    def test_verified_no_bars_is_no_data_without_repeat_request(self):
        result=plan(*fixture([]))
        self.assertEqual(result['requests'],[])
        self.assertEqual(result['coverage_results'][0]['coverage_action'],'NO_DATA')

    def test_future_receipt_and_conflicting_no_data_block(self):
        inventory,memory=fixture()
        with zipfile.ZipFile(io.BytesIO(memory['RAW'])) as pack:
            files={name:pack.read(name) for name in pack.namelist()}
        meta=source.decode(files['capture.json']);meta.update(end='2027-01-01',asof='2026-12-31')
        files['capture.json']=source.encoded(meta)
        raw=source.zip_bytes(files)
        receipt=h.decode(memory['RECEIPT']);receipt.update(end=meta['end'],asof=meta['asof'])
        receipt['raw_object']['sha256']=h.digest(raw)
        source.verify_archived_group(raw,memory['NORM'],receipt)
        memory['RAW']=raw;inventory['artifacts']['RAW']={'sha256':h.digest(raw)}
        put(inventory,memory,'RECEIPT',receipt)
        result=plan(inventory,memory)
        self.assertEqual(result['requests'],[])
        self.assertIn('PRICE_RECEIPT_CLOCK',result['coverage_results'][0]['blockers'])
        inventory,memory=fixture()
        for aid,raw in zip(('EMPTY_RAW','EMPTY_NORM','EMPTY_RECEIPT'),archive([])):
            memory[aid]=raw;inventory['artifacts'][aid]={'sha256':h.digest(raw)}
        catalog=h.decode(memory['CATALOG'])
        catalog['securities'][0]['receipt_ids'].append('EMPTY_RECEIPT')
        put(inventory,memory,'CATALOG',catalog)
        result=plan(inventory,memory)
        self.assertEqual(result['requests'],[])
        self.assertIn('PRICE_NO_DATA_CONFLICT',result['coverage_results'][0]['blockers'])

    def test_missing_Open_never_uses_Close_and_tamper_blocks(self):
        result=plan(*fixture(bad_open=True))
        self.assertEqual(result['requests'],[])
        self.assertIn('PRICE_ARCHIVE_REFUSED',result['coverage_results'][0]['blockers'])
        inventory,memory=fixture();memory['NORM']+=b'tamper'
        self.assertEqual(plan(inventory,memory)['requests'],[])

    def test_v0_and_wrong_ticker_cannot_generate_requests(self):
        for field,value in (('verification_level','V0'),('tickers',['WRONG'])):
            inventory,memory=fixture();events=h.decode(memory['EVENTS']);events['events'][0][field]=value
            put(inventory,memory,'EVENTS',events)
            result=plan(inventory,memory)
            self.assertEqual(result['requests'],[])
            self.assertEqual(result['discovery_other_events'][0]['status'],'BLOCKED')

    def test_calendar_conflict_future_and_duplicate_block(self):
        for change in ('country','future','duplicate','window','missing_session','pre_observation'):
            inventory,memory=fixture();value=h.decode(memory['CALENDAR'])
            if change=='country':value['country']='KR'
            if change=='future':value['sessions'][0]['close_at']='2027-01-01T21:00:00Z'
            if change=='duplicate':value['sessions'].append(copy.deepcopy(value['sessions'][0]))
            if change=='window':value['covered_start']='2016-01-05'
            if change=='missing_session':value['sessions'].pop(1)
            if change=='pre_observation':value['as_of']='2010-01-01T00:00:00Z'
            put(inventory,memory,'CALENDAR',value)
            self.assertEqual(plan(inventory,memory)['requests'],[])

    def test_future_target_cannot_be_filled_by_an_incomplete_past_calendar(self):
        inventory,memory=fixture(state='NOT_STORED')
        inventory['targets'][0]['end_exclusive']='2099-01-01'
        self.assertIn('REQUEST_WINDOW',plan(inventory,memory)['coverage_results'][0]['blockers'])

    def test_exact_ten_year_default_clamps_to_listing(self):
        inventory,memory=fixture(state='NOT_STORED')
        inventory['targets'][0]['start']=None
        context=h.decode(memory['CONTEXT']);identity=context['identities'][0]
        identity['valid_from']='2016-01-05T00:00:00Z'
        proof=h.decode(memory['IDENTITY']);proof['valid_from']=identity['valid_from']
        put(inventory,memory,'IDENTITY',proof)
        identity['evidence_ref']['sha256']=h.digest(memory['IDENTITY'])
        put(inventory,memory,'CONTEXT',context)
        result=plan(inventory,memory)
        self.assertEqual(result['requests'][0]['start'],'2016-01-05')

    def test_prior_request_blocks_duplicate_complete_and_uncertain_retries(self):
        for status in ('PENDING','RUNNING','COMPLETE','FAILED','UNKNOWN'):
            inventory,memory=fixture(DAYS[:2]);first=plan(inventory,memory)['requests'][0]
            put(inventory,memory,'PRIOR',dict(schema='a0-ohlcv-request-snapshot-v1',
                as_of=discovery_fixture.CUTOFF,requests=[dict(request_id=first['request_id'],status=status)]))
            inventory['prior_requests_id']='PRIOR'
            result=plan(inventory,memory)
            self.assertEqual(result['requests'],[])
            self.assertIn('PRIOR_REQUEST_'+status+'_RECONCILE_REQUIRED',result['coverage_results'][0]['blockers'])
            self.assertEqual(result['coverage_results'][0]['coverage_action'],'INCREMENTAL_ONLY')

    def test_budget_is_not_authorization_and_bool_budget_refuses(self):
        for remaining in (0,True):
            inventory,memory=fixture(DAYS[:2]);value=h.decode(memory['POLICY'])
            value['remaining_provider_gets']=remaining;put(inventory,memory,'POLICY',value)
            result=plan(inventory,memory)
            if remaining is True:self.assertEqual(result['requests'],[])
            else:self.assertIn('PROVIDER_BUDGET_INSUFFICIENT_LOWER_BOUND',result['requests'][0]['blockers'])
        inventory,memory=fixture(DAYS[:2]);first=plan(inventory,memory)['requests'][0]
        value=h.decode(memory['POLICY']);value['remaining_provider_gets']=19
        put(inventory,memory,'POLICY',value)
        self.assertEqual(first['request_id'],plan(inventory,memory)['requests'][0]['request_id'])

    def test_same_security_events_coalesce_and_receipt_flags_cannot_fake_rows(self):
        inventory,memory=fixture();value=h.decode(memory['EVENTS'])
        event=copy.deepcopy(value['events'][0]);event['event_id']='SECOND:EVENT';event['event_family']='GUIDANCE'
        value['events'].append(event);put(inventory,memory,'EVENTS',value)
        context=h.decode(memory['CONTEXT']);origin=copy.deepcopy(context['origins'][0]);origin['event_id']='SECOND:EVENT'
        context['origins'].append(origin);put(inventory,memory,'CONTEXT',context)
        self.assertEqual(len(plan(inventory,memory)['requests']),1)
        receipt=h.decode(memory['RECEIPT']);receipt['rows']+=1
        put(inventory,memory,'RECEIPT',receipt)
        self.assertEqual(plan(inventory,memory)['requests'],[])


class BoardOHLCVTests(unittest.TestCase):
    def setUp(self):
        self.owner=state_fixtures.StateTests('test_current_identity_and_semantic_determinism');self.owner.setUp()
        self.addCleanup(self.owner.tearDown)
        self.addCleanup(self.owner.tmp.cleanup)
        self.cutoff=self.owner.at(-1)
        inventory,memory=fixture(DAYS[:2],cutoff=self.cutoff)
        refs={}
        for i,(aid,raw) in enumerate(memory.items()):
            p=self.owner.root/('input_'+str(i));p.write_bytes(raw)
            refs[aid]=dict(path=p.name,sha256=h.digest(raw),observed_at=self.owner.at(-30),
                available_at=self.owner.at(-20),collected_at=self.owner.at(-5),
                expires_at=self.owner.at(30),status='VERIFIED')
        inventory['artifacts']=refs
        p=self.owner.root/'source_inventory.json';p.write_bytes(h.canonical(inventory))
        self.request=dict(agent='A1',inputs={'source_inventory':dict(path=p.name,
            sha256=board.file_hash(p),observed_at=self.owner.at(-30),available_at=self.owner.at(-20),
            collected_at=self.owner.at(-5),expires_at=self.owner.at(30),status='VERIFIED')},
            model={'name':'SYNTHETIC','version':'v1'},parameters={})
        self.owner.manifest['requests']=[self.request]

    def tasks(self):
        state=self.owner.state()
        return board.build_tasks(state,self.owner.root,board.contracts(),self.owner.now,
            self.owner.sha,self.owner.config,canonical_inputs=self.owner.manifest,evidence_root=self.owner.root)

    def test_real_public_builder_routes_inside_existing_packet_without_cycle(self):
        packet=self.tasks()[0]
        payload=packet['identity']['parameters'][handoff.PARAMETER]
        self.assertEqual(payload['requests'][0]['action'],'INCREMENTAL_ONLY')
        self.assertEqual(packet['agent'],'A1');self.assertEqual(packet['dependencies'],[])
        self.assertFalse(packet['dispatch_eligible'])
        self.assertEqual(packet['task_key'],board.digest({'agent':'A1',**packet['identity']}))

    def test_forged_reserved_parameter_stale_and_changed_child_reject(self):
        self.request['parameters'][handoff.PARAMETER]={'fake':True}
        with self.assertRaises(ValueError):self.tasks()
        self.request['parameters'].clear()
        inventory=board.read_json(self.owner.root/'source_inventory.json')
        child=self.owner.root/inventory['artifacts']['RAW']['path']
        child.write_bytes(child.read_bytes()+b'x')
        with self.assertRaises(ValueError):self.tasks()

    def test_child_byte_limit_precedes_hashing_or_full_read(self):
        inventory=board.read_json(self.owner.root/'source_inventory.json')
        child=self.owner.root/inventory['artifacts']['RAW']['path']
        with child.open('wb') as stream:
            stream.truncate(h.MAX_BYTES+1)
        # Direct helper exercises the new protocol boundary; public builder
        # state materialization remains separately tested above.
        with mock.patch.object(board,'file_hash',side_effect=AssertionError('unbounded hash')):
            with self.assertRaisesRegex(board.ContractError,'ohlcv_artifact_bytes'):
                board.ohlcv_parameters(self.request,self.owner.root,
                    h.stamp(self.cutoff),self.owner.now)

    def test_existing_queue_manifest_publication_and_failure_revocation(self):
        root=self.owner.root
        (root/'state.json').write_text(json.dumps(self.owner.state()))
        (root/'intake.json').write_text(json.dumps(self.owner.manifest))
        args=argparse.Namespace(latest_run=str(root),output_dir=str(root/'board'),run_url='',max_tasks=0,
            canonical_inputs=str(root/'intake.json'),evidence_root=str(root),system_state=str(root/'state.json'))
        manifest=board.run(args)
        self.assertEqual(manifest['status'],'PROPOSAL_ONLY')
        queue=board.read_json(root/'board/agent_task_queue.json')
        self.assertEqual(len(queue),1)
        self.assertIn(handoff.PARAMETER,queue[0]['identity']['parameters'])
        for name,sha in manifest['members'].items():self.assertEqual(board.file_hash(root/'board'/name),sha)
        (root/'source_inventory.json').write_bytes(b'changed')
        self.assertEqual(board.run(args)['status'],'BLOCKED')
        rejected=board.read_json(root/'board/agent_task_queue.json')
        self.assertEqual(rejected[0]['status'],'BLOCKED')
        self.assertNotIn(handoff.PARAMETER,rejected[0]['identity']['parameters'])
        self.assertFalse(rejected[0]['dispatch_eligible'])


if __name__=='__main__':unittest.main(verbosity=2)
