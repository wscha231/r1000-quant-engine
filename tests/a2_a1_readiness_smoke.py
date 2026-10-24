"""Synthetic lookup/binding tests; actual three-name observation is separate."""
import argparse
import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

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
    def test_supported_capture_and_checkpoint_decode_above_default1000(self):
        for aid,counts in (('CAPTURE',(1000,1001,4000)),('CP',(1000,1001,1500))):
            for count in counts:
                with self.subTest(aid=aid,count=count):
                    value,values=fixture();data=h.decode(values[aid])
                    if aid=='CAPTURE':
                        data.update(count=count,rows=[[0,'T'+str(i),0,0,0,0,0,0,0,0] for i in range(count)])
                    else:
                        data.update(completed=['T'+str(i) for i in range(count)],
                                    examined=['T'+str(i) for i in range(count)],held=[])
                    values[aid]=h.canonical(data);value['artifacts'][aid]['sha256']=h.digest(values[aid])
                    result=run(value,values)
                    self.assertFalse(result['readiness_observations'][0]['data_ready'])
                    self.assertEqual(result['requests'],[])
        # No artifact-specific path changes the shared decoder default.
        with self.assertRaisesRegex(ValueError,'ENTRY_BUDGET'):
            h.decode(h.canonical({'unrelated':list(range(1001))}))

    def test_capture_checkpoint_entry_limits_keep_other_resource_guards(self):
        cases=(('CAPTURE','entries',10001,'ENTRY_BUDGET'),
               ('CP','entries',1501,'ENTRY_BUDGET'),
               ('CAPTURE','tokens',10000,'TOKEN_BUDGET'),
               ('CAPTURE','boundary_shape',10000,'LOOKUP_CAPTURE_DUPLICATE'),
               ('CAPTURE','depth',0,'DEPTH_BUDGET'),
               ('CAPTURE','duplicate',2,'LOOKUP_CAPTURE_DUPLICATE'),
               ('CP','duplicate',2,'LOOKUP_CHECKPOINT_SYMBOLS'))
        for aid,kind,count,reason in cases:
            with self.subTest(aid=aid,kind=kind):
                value,values=fixture();data=h.decode(values[aid])
                if aid=='CAPTURE':
                    rows=([[] for _ in range(count)] if kind in {'entries','boundary_shape'} else
                          [[0,'T'+str(i),0,0,0,0,0,0,0,0] for i in range(count)])
                    if kind=='depth':
                        rows=0
                        for _ in range(h.MAX_DEPTH+1):rows=[rows]
                    if kind=='duplicate':rows[1][1]=rows[0][1]
                    data.update(count=count,rows=rows)
                else:
                    symbols=['T'+str(i) for i in range(count)]
                    if kind=='duplicate':symbols[1]=symbols[0]
                    data.update(completed=[],examined=symbols,held=[])
                values[aid]=h.canonical(data);value['artifacts'][aid]['sha256']=h.digest(values[aid])
                with self.assertRaisesRegex(ValueError,reason):run(value,values)
        value,values=fixture();values['CAPTURE']=b' '*(h.MAX_BYTES+1)
        value['artifacts']['CAPTURE']['sha256']=h.digest(values['CAPTURE'])
        with self.assertRaisesRegex(ValueError,'ARTIFACT_BYTES'):run(value,values)

    def test_prior_output_hardlinks_cannot_prevent_refresh_invalidation(self):
        for name in ('source_inventory.json','readiness_report.json','request_fragment.json',
                     live.REFRESH_MARKER+'.tmp'):
            for malformed in (False,True):
                with self.subTest(name=name,malformed=malformed),tempfile.TemporaryDirectory() as tmp:
                    root=Path(tmp);subject=root/'subjects.json'
                    subject.write_bytes(h.canonical({'subjects':fixture()[0]['subjects']}))
                    out=root/'lookup';args=argparse.Namespace(subjects=str(subject),registry_root=None,
                        capture_inventory=None,checkpoint=[],ohlcv_inventory=None,output_dir=str(out))
                    live.snapshot(args)
                    prior={out/n:(out/n).read_bytes() for n in
                        ('source_inventory.json','readiness_report.json','request_fragment.json')}
                    if not (out/name).exists():(out/name).write_bytes(b'unknown temporary source')
                    alias=root/'original';alias.hardlink_to(out/name);original=alias.read_bytes()
                    if malformed:
                        inventory=root/'inventory.json';inventory.write_bytes(b'{')
                        args.ohlcv_inventory=str(inventory)
                    with self.assertRaises(ValueError):live.snapshot(args)
                    self.assertEqual(prior,{p:p.read_bytes() for p in prior})
                    self.assertEqual(alias.read_bytes(),original)
                    self.assertTrue((out/live.REFRESH_MARKER).exists())
                    with self.assertRaisesRegex(ValueError,'LOOKUP_REFRESH_BLOCKED'):
                        live.connect(out,root/'canonical.json',root/'sources',root/'board')
                    self.assertEqual(board.read_json(root/'board/agent_task_queue.json'),[])

    def test_failed_inventory_refresh_blocks_stale_connect_without_deleting_old_bytes(self):
        for failure in ('missing','oversized','malformed'):
            with self.subTest(failure=failure),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);src=root/'source';src.mkdir();at=datetime.now(timezone.utc)
                inner,values=price_fixture.fixture(cutoff=at.isoformat())
                for i,(aid,raw) in enumerate(values.items()):
                    path=src/('input'+str(i));path.write_bytes(raw)
                    inner['artifacts'][aid]=dict(path=path.name,sha256=h.digest(raw),
                        observed_at=(at-timedelta(minutes=3)).isoformat(),
                        available_at=(at-timedelta(minutes=2)).isoformat(),
                        collected_at=(at-timedelta(minutes=1)).isoformat(),
                        expires_at=(at+timedelta(minutes=30)).isoformat(),status='VERIFIED')
                inv=src/'inventory.json';original=h.canonical(inner);inv.write_bytes(original)
                subjects=root/'subjects.json';subjects.write_bytes(h.canonical({'subjects':fixture()[0]['subjects']}))
                out=root/'lookup';args=argparse.Namespace(subjects=str(subjects),registry_root=None,
                    capture_inventory=None,checkpoint=[],ohlcv_inventory=str(inv),output_dir=str(out))
                self.assertEqual(live.snapshot(args)['requests'][0]['action'],'REUSE_EXISTING')
                prior={out/name:(out/name).read_bytes() for name in
                    ('source_inventory.json','readiness_report.json','request_fragment.json')}
                if failure=='missing':inv.unlink()
                else:inv.write_bytes(b' '*(h.MAX_BYTES+1) if failure=='oversized' else b'{')
                with self.assertRaises((ValueError,OSError)):live.snapshot(args)
                self.assertEqual(prior,{p:p.read_bytes() for p in prior})
                self.assertTrue((out/live.REFRESH_MARKER).exists())
                with self.assertRaisesRegex(ValueError,'LOOKUP_REFRESH_BLOCKED'):
                    live.connect(out,root/'canonical.json',src,root/'board')
                self.assertEqual(board.read_json(root/'board/agent_task_queue.json'),[])
                inv.write_bytes(original)
                self.assertEqual(live.snapshot(args)['requests'][0]['action'],'REUSE_EXISTING')
                self.assertFalse((out/live.REFRESH_MARKER).exists())

    def test_unknown_or_hardlinked_refresh_marker_preserves_input_and_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);subject=root/'subjects.json'
            subject.write_bytes(h.canonical({'subjects':fixture()[0]['subjects']}))
            out=root/'lookup';args=argparse.Namespace(subjects=str(subject),registry_root=None,
                capture_inventory=None,checkpoint=[],ohlcv_inventory=None,output_dir=str(out))
            live.snapshot(args)
            original=b'original source, not an owned marker'
            marker=out/live.REFRESH_MARKER;marker.write_bytes(original)
            prior=(out/'request_fragment.json').read_bytes()
            with self.assertRaisesRegex(ValueError,'LOOKUP_REFRESH_MARKER_CONFLICT'):live.snapshot(args)
            self.assertEqual(marker.read_bytes(),original)
            self.assertEqual((out/'request_fragment.json').read_bytes(),prior)
            marker.unlink();source=root/'original';source.write_bytes(original);marker.hardlink_to(source)
            with self.assertRaisesRegex(ValueError,'LOOKUP_OUTPUT_HARDLINK'):live.snapshot(args)
            self.assertEqual(source.read_bytes(),original)
            with self.assertRaisesRegex(ValueError,'LOOKUP_REFRESH_BLOCKED'):
                live.connect(out,root/'canonical.json',root/'sources',root/'board')

    def test_external_inventory_child_alias_refuses_before_revoking_original(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);out=root/'out';out.mkdir()
            original=b'original input and previous report'
            child=out/'readiness_report.json';child.write_bytes(original)
            inventory=root/'inventory.json'
            inventory.write_bytes(h.canonical({'artifacts':{'CHILD':{
                'path':'out/readiness_report.json','sha256':h.digest(original)}}}))
            subject=root/'subjects.json';subject.write_bytes(h.canonical({'subjects':fixture()[0]['subjects']}))
            args=argparse.Namespace(subjects=str(subject),registry_root=None,capture_inventory=None,
                checkpoint=[],ohlcv_inventory=str(inventory),output_dir=str(out))
            before={p:p.read_bytes() for p in (child,inventory,subject)}
            with self.assertRaisesRegex(ValueError,'LOOKUP_OUTPUT_SCOPE'):
                live.snapshot(args)
            self.assertEqual(before,{p:p.read_bytes() for p in before})

    def nested_connect_fixture(self, root, owner):
        subject=root/'subjects.json'
        subject.write_bytes(h.canonical({'subjects':[dict(country='US',ticker='RNG',
            security_id=None,issuer_id=None)]}))
        live.snapshot(argparse.Namespace(subjects=str(subject),registry_root=None,
            capture_inventory=None,checkpoint=[],ohlcv_inventory=None,output_dir=str(root/'lookup')))
        owner.now=datetime.now(timezone.utc);owner.manifest['observed_at']=owner.at(0)
        for role in ('code','control'):
            obj=owner.payload(role);obj['observed_at']=owner.at(0);owner.put(role,obj)
        def put(path,value,collected):
            target=owner.root/path;target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes(h.canonical(value))
            return dict(path=path,sha256=board.file_hash(target),observed_at=owner.at(-8),
                available_at=owner.at(-7),collected_at=owner.at(collected),
                expires_at=owner.at(30),status='VERIFIED')
        leaf=put('proof/leaf.json',{'fixture':'original'},-4)
        nested=put('proof/nested.json',{'schema_version':'qa-review-bundle-v2','artifacts':{'leaf':leaf}},-3)
        code={k:v for k,v in owner.manifest['sources']['code'][0].items() if k!='identity'}
        bundle=put('proof/review.json',{'schema_version':'qa-review-bundle-v2',
            'artifacts':{'nested':nested,'shared_code':code}},-2)
        owner.manifest['requests']=[dict(agent='A6',inputs={'review_bundle':bundle},
            parameters={},model={'name':'fixture','version':'v1'})]
        intake=owner.root/'intake.json'
        def refresh():
            # Rebind only enclosing fixture hashes after a deliberate child mutation.
            (owner.root/nested['path']).write_bytes(h.canonical({'schema_version':'qa-review-bundle-v2',
                'artifacts':{'leaf':leaf}}))
            nested['sha256']=board.file_hash(owner.root/nested['path'])
            (owner.root/bundle['path']).write_bytes(h.canonical({'schema_version':'qa-review-bundle-v2',
                'artifacts':{'nested':nested,'shared_code':code}}))
            bundle['sha256']=board.file_hash(owner.root/bundle['path'])
            intake.write_bytes(h.canonical(owner.manifest))
        refresh()
        return intake,leaf,nested,bundle,refresh

    def test_connect_preserves_nested_A6_bundle_bytes_paths_and_ready_status(self):
        owner=state_fixture.StateTests('test_current_identity_and_semantic_determinism');owner.setUp()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);intake,leaf,nested,bundle,_=self.nested_connect_fixture(root,owner)
                before={p:p.read_bytes() for p in owner.root.rglob('*') if p.is_file()}
                live.connect(root/'lookup',intake,owner.root,root/'out')
                tasks=board.read_json(root/'out/agent_task_queue.json')
                qa=next(t for t in tasks if t['agent']=='A6')
                self.assertEqual(qa['status'],'READY')
                self.assertFalse(qa['authority']['execute'])
                self.assertEqual(qa['inputs']['review_bundle'],bundle)
                transported=board.read_json(root/'out/intake.json')
                evidence=next((root/'out/evidence').iterdir())
                for ref in (leaf,nested,bundle):
                    self.assertEqual((evidence/ref['path']).read_bytes(),before[owner.root/ref['path']])
                self.assertEqual(transported['requests'][0]['inputs']['review_bundle'],bundle)
                self.assertEqual(before,{p:p.read_bytes() for p in before})
        finally:owner.tearDown();owner.tmp.cleanup()

    def test_connect_rechecks_invalidation_before_evidence_publication(self):
        owner=state_fixture.StateTests('test_current_identity_and_semantic_determinism');owner.setUp()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);intake,*_=self.nested_connect_fixture(root,owner)
                read=live.read_bytes;calls=[]
                def invalidate(path,**kwargs):
                    if not calls:
                        calls.append(path);live.block_refresh(root/'lookup')
                    return read(path,**kwargs)
                with mock.patch.object(live,'read_bytes',side_effect=invalidate):
                    with self.assertRaisesRegex(ValueError,'LOOKUP_REFRESH_BLOCKED'):
                        live.connect(root/'lookup',intake,owner.root,root/'out')
                self.assertEqual(board.read_json(root/'out/agent_task_queue.json'),[])
                self.assertEqual([p for p in (root/'out/evidence').rglob('*') if p.is_file()],[])
        finally:owner.tearDown();owner.tmp.cleanup()

    def test_nested_A6_missing_tampered_traversal_and_collision_fail_closed(self):
        for failure in ('missing','tampered','traversal','collision','prefix','metadata','clock','oversize'):
            with self.subTest(failure=failure):
                owner=state_fixture.StateTests('test_current_identity_and_semantic_determinism');owner.setUp()
                try:
                    with tempfile.TemporaryDirectory() as tmp:
                        root=Path(tmp);intake,leaf,nested,bundle,refresh=self.nested_connect_fixture(root,owner)
                        if failure=='missing':(owner.root/leaf['path']).unlink()
                        elif failure=='tampered':(owner.root/leaf['path']).write_bytes(b'tampered')
                        elif failure=='traversal':leaf['path']='../outside.json';refresh()
                        elif failure=='collision':
                            leaf['path']='source_inventory.json'
                            (owner.root/leaf['path']).write_bytes(h.canonical({'other':'bytes'}))
                            leaf['sha256']=board.file_hash(owner.root/leaf['path']);refresh()
                        elif failure=='prefix':
                            leaf['path']='source_inventory.json/child'
                            target=owner.root/leaf['path'];target.parent.mkdir()
                            target.write_bytes(h.canonical({'other':'bytes'}))
                            leaf['sha256']=board.file_hash(target);refresh()
                        elif failure=='metadata':
                            node=board.read_json(owner.root/bundle['path'])
                            node['artifacts']['shared_code']['collected_at']=owner.at(-4)
                            (owner.root/bundle['path']).write_bytes(h.canonical(node))
                            bundle['sha256']=board.file_hash(owner.root/bundle['path'])
                            intake.write_bytes(h.canonical(owner.manifest))
                        elif failure=='oversize':
                            target=owner.root/leaf['path'];target.write_bytes(b'x'*(h.MAX_BYTES+1))
                            leaf['sha256']=board.file_hash(target);refresh()
                        else:leaf['collected_at']=owner.at(-1);refresh()
                        before={p:p.read_bytes() for p in owner.root.rglob('*') if p.is_file()}
                        with self.assertRaises((ValueError,OSError)):
                            live.connect(root/'lookup',intake,owner.root,root/'out')
                        self.assertEqual(board.read_json(root/'out/agent_task_queue.json'),[])
                        self.assertEqual(board.read_json(root/'out/manifest.json')['status'],'BLOCKED')
                        self.assertEqual([p for p in (root/'out/evidence').rglob('*') if p.is_file()],[])
                        self.assertEqual(before,{p:p.read_bytes() for p in before})
                finally:owner.tearDown();owner.tmp.cleanup()

    def test_nested_A6_closure_byte_count_and_depth_limits_are_retained(self):
        for failure in ('bytes','count','depth'):
            with self.subTest(failure=failure):
                owner=state_fixture.StateTests('test_current_identity_and_semantic_determinism');owner.setUp()
                try:
                    with tempfile.TemporaryDirectory() as tmp:
                        root=Path(tmp);intake,leaf,nested,bundle,refresh=self.nested_connect_fixture(root,owner)
                        if failure=='count':
                            raw=h.canonical({'schema_version':'qa-review-bundle-v2',
                                'artifacts':{str(i):leaf for i in range(129)}})
                            (owner.root/bundle['path']).write_bytes(raw);bundle['sha256']=h.digest(raw)
                            intake.write_bytes(h.canonical(owner.manifest))
                        elif failure=='depth':
                            link=leaf
                            for i in range(33):
                                raw=h.canonical({'schema_version':'qa-review-bundle-v2','artifacts':{'link':link}})
                                name='deep/'+str(i)+'.json';target=owner.root/name
                                target.parent.mkdir(exist_ok=True);target.write_bytes(raw)
                                link={**leaf,'path':name,'sha256':h.digest(raw)}
                            raw=h.canonical({'schema_version':'qa-review-bundle-v2','artifacts':{'link':link}})
                            (owner.root/bundle['path']).write_bytes(raw);bundle['sha256']=h.digest(raw)
                            intake.write_bytes(h.canonical(owner.manifest))
                        read=live.read_bytes
                        calls=[]
                        def track(path,**kwargs):
                            calls.append(kwargs.get('limit'))
                            return read(path,**kwargs)
                        with mock.patch.object(h,'MAX_TOTAL_BYTES',1 if failure=='bytes' else h.MAX_TOTAL_BYTES), \
                             mock.patch.object(live,'read_bytes',side_effect=track):
                            with self.assertRaisesRegex(ValueError,'LOOKUP_BIND_|LOOKUP_FILE_BUDGET'):
                                live.connect(root/'lookup',intake,owner.root,root/'out')
                        if failure=='count':self.assertEqual(len(calls),128)
                        if failure=='bytes':self.assertEqual(calls,[1])
                        self.assertEqual(board.read_json(root/'out/agent_task_queue.json'),[])
                finally:owner.tearDown();owner.tmp.cleanup()

    def test_remaining_byte_budget_caps_the_actual_file_read(self):
        stream=mock.MagicMock();stream.__enter__.return_value=stream
        stream.read.return_value=b'123'
        with mock.patch.object(Path,'open',return_value=stream):
            with self.assertRaisesRegex(ValueError,'LOOKUP_FILE_BUDGET'):
                live.read_bytes('synthetic',limit=2)
        stream.read.assert_called_once_with(3)

    def test_stage3_transport_snapshot_does_not_reopen_unbounded_hash_reader(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);src=root/'source';src.mkdir();at=datetime.now(timezone.utc)
            inner,values=price_fixture.fixture(cutoff=at.isoformat())
            for i,(aid,raw) in enumerate(values.items()):
                path=src/('input'+str(i));path.write_bytes(raw)
                inner['artifacts'][aid]=dict(path=path.name,sha256=h.digest(raw),
                    observed_at=(at-timedelta(minutes=3)).isoformat(),
                    available_at=(at-timedelta(minutes=2)).isoformat(),
                    collected_at=(at-timedelta(minutes=1)).isoformat(),
                    expires_at=(at+timedelta(minutes=30)).isoformat(),status='VERIFIED')
            inv=src/'inventory.json';inv.write_bytes(h.canonical(inner))
            subjects=root/'subjects.json';subjects.write_bytes(h.canonical({'subjects':fixture()[0]['subjects']}))
            args=argparse.Namespace(subjects=str(subjects),registry_root=None,capture_inventory=None,
                checkpoint=[],ohlcv_inventory=str(inv),output_dir=str(root/'out'))
            with mock.patch.object(board,'verify_artifact',side_effect=AssertionError('unbounded reread')):
                report=live.snapshot(args)
            self.assertEqual(report['event_connection'],'STAGE3_VALIDATOR')
            self.assertEqual(report['requests'][0]['action'],'REUSE_EXISTING')
    def test_existing_cache_hardlink_never_overwrites_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'source';source.write_bytes(b'original')
            alias=root/'cache';alias.hardlink_to(source)
            with self.assertRaisesRegex(ValueError,'LOOKUP_IMMUTABLE_CONFLICT'):
                live.immutable_bytes(alias,b'replacement')
            self.assertEqual(source.read_bytes(),b'original')
            live.immutable_bytes(alias,b'original')
            self.assertEqual(source.read_bytes(),b'original')
            out=root/'output';out.mkdir()
            (out/'manifest.json.tmp').hardlink_to(source)
            with self.assertRaisesRegex(ValueError,'LOOKUP_OUTPUT_HARDLINK'):live.safe_output(out)
            self.assertEqual(source.read_bytes(),b'original')

    def test_ChatGPT_claimed_V2_never_becomes_validated_event_or_A3(self):
        value,values=fixture()
        item=dict(reported_at_text='2026-10-21 19:02 KST (CLAIMED)',
            source_excerpt='A2_EVENT_HANDOFF V2:3 NEW_CANDIDATE (CONTRACT_FIXTURE)',
            source_links=['https://example.test/original'],claimed_event_count=3)
        export=dict(schema='chatgpt-a2-observed-reports-v1',
            source_url='https://chatgpt.com/share/00000000-0000-0000-0000-000000000000',
            observed_at=value['as_of'],extraction='USER_EXPORTED_TEXT',reports=[item,item])
        values['CHATGPT_REPORT']=h.canonical(export)
        value['artifacts']['CHATGPT_REPORT']={'sha256':h.digest(values['CHATGPT_REPORT'])}
        value['chatgpt_report_id']='CHATGPT_REPORT'
        result=run(value,values)
        self.assertEqual(len(result['chatgpt_report_intake']),1)
        self.assertEqual(result['chatgpt_report_intake'][0]['status'],'UNADMITTED')
        self.assertIsNone(result['chatgpt_report_intake'][0]['original_public_available_at'])
        self.assertEqual(result['automatic_chatgpt_delivery'],'NOT_CONNECTED')
        self.assertEqual(result['requests'],[])

    def test_nonsealed_callback_is_rejected_before_any_read(self):
        value,values=fixture()
        class Untrusted:
            calls=0
            def read(self,aid,digest):
                self.calls+=1
                return values[aid]
        reader=Untrusted()
        with self.assertRaises(ValueError):live.lookup(value,reader,cutoff=value['as_of'])
        self.assertEqual(reader.calls,0)

    def test_explicit_input_output_aliases_reject_before_revocation(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'out';out.mkdir()
            subjects=out/'source_inventory.json';subjects.write_bytes(b'original-subjects')
            args=argparse.Namespace(subjects=str(subjects),registry_root=None,
                capture_inventory=None,checkpoint=[],ohlcv_inventory=None,output_dir=str(out))
            with self.assertRaisesRegex(ValueError,'LOOKUP_OUTPUT_SCOPE'):live.snapshot(args)
            self.assertEqual(subjects.read_bytes(),b'original-subjects')
            canonical=out/'manifest.json';canonical.write_bytes(b'original-canonical')
            with self.assertRaisesRegex(ValueError,'LOOKUP_OUTPUT_SCOPE'):
                live.connect(Path(tmp)/'lookup',canonical,Path(tmp)/'sources',out)
            self.assertEqual(canonical.read_bytes(),b'original-canonical')

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
        value['subjects'][0].update(security_id=None,issuer_id='CIK:0000000001')
        with self.assertRaisesRegex(ValueError,'LOOKUP_SUBJECT_IDENTITY_CONFLICT'):run(value,values)

    def test_A3_declared_state_is_preserved_not_invented_from_record_presence(self):
        result=run(*fixture())
        self.assertEqual(result['readiness_observations'][0]['research_requests'][0]['a3_declared_states'],['UNKNOWN'])
        self.assertFalse(result['readiness_observations'][0]['consumer_eligible'])

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
