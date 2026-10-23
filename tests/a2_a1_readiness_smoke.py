"""Synthetic lookup/binding tests; actual three-name observation is separate."""
import argparse
import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parent.parent
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from tools import run_a2_a1_readiness as live
from tools import run_agent_board as board
import a2_a1_ohlcv_handoff_v1_smoke as price_fixture
import system_state_materializer_smoke as state_fixture
h=live.h


def fixture():
    at=datetime.now(timezone.utc).isoformat()
    values={}
    def put(value):
        raw=h.canonical(value);sha=h.digest(raw);values['B'+sha]=raw
        return dict(path='artifacts/'+sha,sha256=sha)
    original=put({'original':'CONTRACT_FIXTURE'})
    event=dict(event_id='E1',ticker='MU',available_at=at)
    er=put(event)
    receipt=put(dict(event_scope={'E1':{}}))
    a2=put(dict(input={'events':[dict(event_id='E1',verification_level='V0')]}))
    a3=put(dict(event_id='E1',asset_id='US:MU:COMMON',issuer_id='CIK:0000723125',
        raw_sha256=original['sha256'],source_receipt_sha256=receipt['sha256']))
    reg=put(dict(schema='candidate-registry-filing-request-v1',request_id='REQUEST',
        event_refs=[er],a2_intake_ref=a2,a3_filing_review_refs=[a3],
        asset_id='US:MU:COMMON',issuer_id='CIK:0000723125',status='RESEARCH_PENDING'))
    bridge=put({'proposal':True})
    values['REGISTRY']=h.canonical(dict(schema='sec-research-request-store-v1',requests={
        'REQUEST':dict(request_id='REQUEST',created_at=at,registry_ref=reg,
            source_receipt_ref=receipt,events_sha256=h.digest(json.dumps([event],sort_keys=True,
                separators=(',',':')).encode()),raw_refs=[original],bridge_ref=bridge)}))
    values['CAPTURE']=h.canonical(dict(prepared_at_utc=at,count=1,
        rows=[[1,'MU','Fixture','Alpaca',1,0,'scope','unknown','unknown','REF']]))
    values['CP']=h.canonical(dict(schema='alpaca-private-sip-history-v1',
        source='ALPACA_STOCK_BARS_V2_HISTORICAL_SIP',state='PRIVATE_RESEARCH_ONLY',
        source_admission=False,pit_verified=False,completed=['MU','BFA'],examined=['MU','BFA'],
        held=[],start='2016-01-04',end='2026-10-14'))
    value=dict(schema=live.SCHEMA,as_of=at,subjects=[dict(country='US',ticker='MU',
        security_id='US:MU:COMMON',issuer_id='CIK:0000723125')],registry_manifest_id='REGISTRY',
        capture_inventory_id='CAPTURE',checkpoint_ids=['CP'],ohlcv_inventory_id=None,
        artifacts={k:{'sha256':h.digest(v)} for k,v in values.items()})
    return value,values


def run(value,values):return live.lookup(value,h.MemoryArtifacts(values),cutoff=value['as_of'])


class ReadinessTests(unittest.TestCase):
    def test_stored_record_and_capture_are_observed_without_admission(self):
        result=run(*fixture());row=result['readiness_observations'][0]
        self.assertEqual(row['registry_state'],'STORED_RESEARCH_REQUEST')
        self.assertEqual(row['price_state'],'CAPTURE_INDEX_MATCH_ONLY')
        self.assertEqual(row['research_requests'][0]['verification_levels'],['V0'])
        self.assertEqual(row['canonical_registry_state'],'NOT_VERIFIED')
        self.assertFalse(row['data_ready']);self.assertEqual(result['requests'],[])
        self.assertEqual(result['event_connection'],'EVENT_INPUT_MISSING')
        self.assertFalse(any(row['authority'].values()))

    def test_absent_is_inspected_scope_only_and_missing_is_unknown(self):
        value,values=fixture();value['subjects'][0].update(ticker='RNG',security_id=None,issuer_id=None)
        result=run(value,values)['readiness_observations'][0]
        self.assertEqual(result['registry_state'],'NOT_FOUND_IN_INSPECTED_STORE')
        self.assertEqual(result['price_state'],'NOT_FOUND_IN_INSPECTED_INDEX')
        self.assertEqual(result['collection_required'],'UNDETERMINED')
        value.update(registry_manifest_id=None,capture_inventory_id=None)
        self.assertEqual(run(value,values)['readiness_observations'][0]['registry_state'],'UNKNOWN')

    def test_ticker_is_not_identity_and_conflicting_keys_refuse(self):
        value,values=fixture();value['subjects'][0]['security_id']=None
        self.assertEqual(run(value,values)['readiness_observations'][0]['identity_match'],
            'TICKER_ONLY_NOT_VERIFIED')
        value['subjects'][0]['security_id']='US:MU:OTHER'
        with self.assertRaisesRegex(ValueError,'LOOKUP_SUBJECT_IDENTITY_CONFLICT'):run(value,values)

    def test_completed_checkpoint_does_not_prove_rows_and_KR_not_US(self):
        value,values=fixture();value['subjects'][0].update(ticker='BFA',security_id=None,issuer_id=None)
        row=run(value,values)['readiness_observations'][0]
        self.assertEqual(row['checkpoint_observations'][0]['state'],'COMPLETED_CLAIM_NO_ROW_PROOF')
        self.assertFalse(row['data_ready'])
        value['subjects'][0].update(country='KR',ticker='005930')
        self.assertEqual(run(value,values)['readiness_observations'][0]['checkpoint_observations'],[])

    def test_tamper_clock_and_subject_duplicates_fail(self):
        value,values=fixture();values['CAPTURE']+=b' '
        with self.assertRaises(ValueError):run(value,values)
        value,values=fixture();value['as_of']='2000-01-01T00:00:00Z'
        with self.assertRaises(ValueError):run(value,values)
        value,values=fixture();value['subjects']*=2
        with self.assertRaisesRegex(ValueError,'LOOKUP_SUBJECT_DUPLICATE'):run(value,values)

    def test_valid_stage3_input_remains_required_for_price_requests(self):
        value,values=fixture();inner,extra=price_fixture.fixture(cutoff=value['as_of'])
        values.update(extra);values['OHLCV']=h.canonical(inner)
        value['artifacts']={k:{'sha256':h.digest(v)} for k,v in values.items()}
        value['ohlcv_inventory_id']='OHLCV'
        result=run(value,values)
        self.assertEqual(result['requests'][0]['action'],'REUSE_EXISTING')
        self.assertFalse(result['requests'][0]['ready_for_collection'])
        # An outer stored request cannot raise the inner event's V0 level.
        events=h.decode(values['EVENTS']);events['events'][0]['verification_level']='V0'
        values['EVENTS']=h.canonical(events)
        inner['artifacts']['EVENTS']['sha256']=h.digest(values['EVENTS'])
        values['OHLCV']=h.canonical(inner)
        value['artifacts']={k:{'sha256':h.digest(v)} for k,v in values.items()}
        self.assertEqual(run(value,values)['requests'],[])

    def test_snapshot_reads_existing_store_does_not_write_it_and_revokes_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);store=root/'existing';store.mkdir();out=root/'observation'
            value,values=fixture()
            path=store/'control_plane/candidate_registry/filing_requests.json'
            path.parent.mkdir(parents=True);path.write_bytes(values['REGISTRY'])
            (store/'artifacts').mkdir()
            for aid,raw in values.items():
                if aid.startswith('B'):(store/'artifacts'/h.digest(raw)).write_bytes(raw)
            subjects=root/'subjects.json';subjects.write_bytes(h.canonical({'subjects':value['subjects']}))
            args=argparse.Namespace(subjects=str(subjects),registry_root=str(store),
                capture_inventory=None,checkpoint=[],ohlcv_inventory=None,output_dir=str(out))
            before={p.relative_to(store):p.read_bytes() for p in store.rglob('*') if p.is_file()}
            live.snapshot(args)
            self.assertTrue((out/'request_fragment.json').exists())
            self.assertEqual(before,{p.relative_to(store):p.read_bytes() for p in store.rglob('*') if p.is_file()})
            path.write_bytes(b'broken')
            with self.assertRaises(ValueError):live.snapshot(args)
            self.assertFalse((out/'request_fragment.json').exists())
            self.assertFalse((out/'readiness_report.json').exists())

    def test_existing_public_A0_gate_binds_lookup_and_blocks_missing_event(self):
        owner=state_fixture.StateTests('test_current_identity_and_semantic_determinism');owner.setUp()
        try:
            value,values=fixture();value['as_of']=owner.at(-1)
            # Synthetic request record must predate the fixture intake.
            store=h.decode(values['REGISTRY']);store['requests']['REQUEST']['created_at']=owner.at(-2)
            values['REGISTRY']=h.canonical(store)
            value['as_of']=owner.at(0)
            owner.manifest['observed_at']=owner.at(0)
            code=owner.payload('code');code['observed_at']=owner.at(0);owner.put('code',code)
            control=owner.payload('control');control['observed_at']=owner.at(0);owner.put('control',control)
            refs={}
            for i,(aid,raw) in enumerate(values.items()):
                path=owner.root/('lookup'+str(i));path.write_bytes(raw)
                refs[aid]=dict(path=path.name,sha256=h.digest(raw),observed_at=owner.at(-5),
                    available_at=owner.at(-4),collected_at=owner.at(-3),expires_at=owner.at(30),status='VERIFIED')
            value['artifacts']=refs
            path=owner.root/'lookup.json';path.write_bytes(h.canonical(value))
            request=dict(agent='A1',inputs={'source_inventory':dict(path=path.name,sha256=board.file_hash(path),
                observed_at=owner.at(-2),available_at=owner.at(-1),collected_at=owner.at(0),
                expires_at=owner.at(30),status='VERIFIED')},parameters={},model={'name':'fixture','version':'v1'})
            owner.manifest['requests']=[request]
            # Lookup generation happened after owner's clock construction.
            now=datetime.now(timezone.utc)
            owner.now=now
            value['as_of']=now.isoformat();path.write_bytes(h.canonical(value))
            request['inputs']['source_inventory']['sha256']=board.file_hash(path)
            # Use a fresh exact intake boundary without editing canonical gates.
            stamp=now.isoformat();owner.manifest['observed_at']=stamp
            for role in ('code','control'):
                data=owner.payload(role);data['observed_at']=stamp;owner.put(role,data)
            state=owner.state()
            tasks=board.build_tasks(state,owner.root,board.contracts(),now,owner.sha,owner.config,
                canonical_inputs=owner.manifest,evidence_root=owner.root)
            self.assertEqual(tasks[0]['status'],'BLOCKED')
            self.assertFalse(tasks[0]['dispatch_eligible'])
            payload=tasks[0]['identity']['parameters'][handoff_parameter()]
            self.assertEqual(payload['readiness_observations'][0]['registry_state'],'STORED_RESEARCH_REQUEST')
        finally:owner.tearDown();owner.tmp.cleanup()

    def test_connect_publishes_existing_queue_and_revokes_failed_refresh(self):
        owner=state_fixture.StateTests('test_current_identity_and_semantic_determinism');owner.setUp()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);subject=root/'subjects.json'
                subject.write_bytes(h.canonical({'subjects':[dict(country='US',ticker='RNG',
                    security_id=None,issuer_id=None)]}))
                args=argparse.Namespace(subjects=str(subject),registry_root=None,capture_inventory=None,
                    checkpoint=[],ohlcv_inventory=None,output_dir=str(root/'lookup'))
                live.snapshot(args)
                owner.now=datetime.now(timezone.utc);stamp=owner.at(0)
                owner.manifest['observed_at']=stamp
                for role in ('code','control'):
                    obj=owner.payload(role);obj['observed_at']=stamp;owner.put(role,obj)
                intake=owner.root/'intake.json';intake.write_text(json.dumps(owner.manifest))
                result=live.connect(root/'lookup',intake,owner.root,root/'board')
                self.assertEqual(result['status'],'BLOCKED')
                queue=board.read_json(root/'board/agent_task_queue.json')
                self.assertEqual(len(queue),1)
                self.assertIn(live.handoff.PARAMETER,queue[0]['identity']['parameters'])
                self.assertFalse(queue[0]['dispatch_eligible'])
                # A new failed connection cannot leave the last positive payload.
                (root/'lookup/source_inventory.json').write_bytes(b'bad')
                with self.assertRaises(ValueError):live.connect(root/'lookup',intake,owner.root,root/'board')
                self.assertEqual(board.read_json(root/'board/agent_task_queue.json'),[])
                self.assertEqual(board.read_json(root/'board/manifest.json')['status'],'BLOCKED')
        finally:owner.tearDown();owner.tmp.cleanup()


def handoff_parameter():return live.handoff.PARAMETER


if __name__=='__main__':unittest.main(verbosity=2)
