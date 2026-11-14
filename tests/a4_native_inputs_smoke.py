"""Synthetic handoff cases; no supplier permission or real-source admission."""
from __future__ import annotations
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import yaml

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'tests'))
from tools import prepare_a4_native_inputs as handoff
from tools.macro_history_sources import digest,encoded
import run287_chameleon_macro_risk_smoke as fixture
from tests.a4_primary_sources_smoke import retained_credit_input

NOW='2026-11-12T10:00:00Z'
DAY='2026-11-11'


class NativeHandoffTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        schedule=fixture.mcal.get_calendar('NYSE').schedule(start_date='2025-06-01',end_date=DAY)
        dates=fixture.pd.DatetimeIndex(schedule.index[-300:])
        calendar=fixture.calendar_fixture(dates).to_csv(index=False).encode()
        lineage=dict(schema_version='run287-chameleon-source-lineage-v1',
            contract_semantic_sha256=handoff.producer.CANONICAL_CONTRACT_SEMANTIC_SHA256,
            requested_as_of=DAY,resolved_as_of=DAY,calendar_sha256=digest(calendar),
            truth_class='FREE_PROXY',historical_ab_allowed=False,sources=[])
        raw_lineage=encoded(lineage)
        tables={name:builder(dates,calendar_hash=digest(calendar))
            for name,builder in [('metrics',fixture.metric_fixture),('context',fixture.context_fixture)]}
        for frame in tables.values():
            frame['truth_class']='FREE_PROXY'
            frame['source_sha256']=digest(raw_lineage)
            frame['source_kind']='SYNTHETIC_FREE_PROXY_FIXTURE'
        cls.bodies=dict(calendar=calendar,source_lineage=raw_lineage,source_audit=b'name,status\nsynthetic,ready\n',
            **{k:v.to_csv(index=False).encode() for k,v in tables.items()})
        cls.manifest=dict(schema_version=handoff.producer.SCHEMA_VERSION,status=handoff.producer.READY_STATUS,
            git_head='a'*40,builder_sha256=digest(Path(handoff.producer.__file__).read_bytes()),
            contract_semantic_sha256=handoff.producer.CANONICAL_CONTRACT_SEMANTIC_SHA256,
            requested_as_of=DAY,resolved_as_of=DAY,truth_class='FREE_PROXY',historical_ab_allowed=False,
            outputs={k:dict(path='/original/linux/archive/'+spec[0],sha256=digest(cls.bodies[k]))
                for k,spec in handoff.FILES.items()},**handoff.producer.SAFETY)

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.source=self.root/'source';self.source.mkdir()
        self.dest=self.root/'prepared';self.packet=copy.deepcopy(self.manifest)
        for key,(name,_,_) in handoff.FILES.items():(self.source/name).write_bytes(self.bodies[key])

    def pin(self):
        raw=encoded(self.packet);(self.source/'manifest.json').write_bytes(raw);return digest(raw)

    def run_prepare(self,**kw):
        return handoff.prepare(self.source,self.pin(),cutoff=NOW,output_dir=kw.pop('output_dir',self.dest),**kw)

    def replace(self,key,body):
        (self.source/handoff.FILES[key][0]).write_bytes(body)
        self.packet['outputs'][key]['sha256']=digest(body)

    def test_same_packet_reuses_exact_bytes_and_existing_a4_loader(self):
        first=self.run_prepare();before={str(p):p.read_bytes() for p in self.dest.rglob('*') if p.is_file()}
        self.assertEqual(first,self.run_prepare())
        self.assertEqual(before,{str(p):p.read_bytes() for p in self.dest.rglob('*') if p.is_file()})
        report=handoff.market.load_report(self.dest/'request.json',self.dest,first['request_sha256'],cutoff=NOW)
        self.assertEqual(report['market_assessment']['status'],'READY_RESEARCH_ONLY')
        self.assertEqual(first['native_ready_axes'],10)
        for key in handoff.SAFETY:self.assertEqual(first[key],handoff.SAFETY[key])
        self.assertFalse(first['source_originals_independently_replayed'])
        self.assertTrue(first['upstream_rights_review_required'])

    def test_manifest_pin_and_changed_member_fail_before_writes(self):
        pin=self.pin()
        with self.assertRaisesRegex(ValueError,'MANIFEST_HASH'):
            handoff.prepare(self.source,'b'*64,cutoff=NOW,output_dir=self.dest)
        (self.source/'input_metrics.csv').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'OUTPUT_HASH'):
            handoff.prepare(self.source,pin,cutoff=NOW,output_dir=self.dest)
        self.assertFalse(self.dest.exists())

    def test_separately_pinned_current_credit_originals_keep_original_specs_and_clocks(self):
        credit_root=self.root/'credit';request,bodies=retained_credit_input(credit_root,now=NOW)
        pin=digest((credit_root/'request.json').read_bytes())
        result=self.run_prepare(current_credit_input_root=credit_root,current_credit_request_sha256=pin)
        prepared=json.loads((self.dest/'request.json').read_bytes())
        selected=[s for s in prepared['inputs'] if handoff.collector.credit_source_input(s)]
        self.assertEqual(len(selected),2);self.assertEqual(result['current_credit_request_sha256'],pin)
        for original in request['inputs'][1:3]:
            spec=next(s for s in selected if s['sha256']==original['sha256'])
            self.assertEqual({k:v for k,v in spec.items() if k!='path'},
                {k:v for k,v in original.items() if k!='path'})
            self.assertEqual((self.dest/spec['path']).read_bytes(),bodies[original['path']])
        report=handoff.market.load_report(self.dest/'request.json',self.dest,result['request_sha256'],cutoff=NOW)
        self.assertEqual(report['status'],'READY_RESEARCH_ONLY')
        self.assertEqual(report['macro_direction_inputs']['hy_oas']['value'],3.2)
        self.assertEqual(result['native_ready_axes'],10)
        self.assertFalse(result['supplier_rights_certified']);self.assertFalse(result['training_allowed'])

    def test_configured_credit_requires_both_arguments_and_independent_request_pin(self):
        credit_root=self.root/'credit';retained_credit_input(credit_root,now=NOW)
        with self.assertRaisesRegex(ValueError,'CREDIT_ARGUMENT_PAIR'):
            self.run_prepare(current_credit_input_root=credit_root)
        raw=(credit_root/'request.json').read_bytes()
        with self.assertRaises(ValueError):
            self.run_prepare(current_credit_input_root=credit_root,current_credit_request_sha256='f'*64)
        self.assertFalse(self.dest.exists());self.assertEqual((credit_root/'request.json').read_bytes(),raw)

    def test_corrupt_or_stale_current_credit_cannot_emit_a_request(self):
        credit_root=self.root/'credit';request,bodies=retained_credit_input(credit_root,now=NOW)
        pin=digest((credit_root/'request.json').read_bytes());(credit_root/'hy.csv').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'CREDIT_ORIGINAL_HASH'):
            self.run_prepare(current_credit_input_root=credit_root,current_credit_request_sha256=pin)
        stale=b'DATE,BAMLH0A0HYM2\n2026-10-01,3.2\n';(credit_root/'hy.csv').write_bytes(stale)
        request['inputs'][1]['sha256']=digest(stale);(credit_root/'request.json').write_bytes(encoded(request))
        with self.assertRaisesRegex(ValueError,'CREDIT_NOT_CURRENT'):
            self.run_prepare(current_credit_input_root=credit_root,
                current_credit_request_sha256=digest((credit_root/'request.json').read_bytes()))
        self.assertFalse(self.dest.exists())

    def test_credit_changed_during_native_replay_is_refused_before_publication(self):
        credit_root=self.root/'credit';retained_credit_input(credit_root,now=NOW)
        pin=digest((credit_root/'request.json').read_bytes());original=handoff.market.native_risk
        def changed(*args,**kwargs):
            result=original(*args,**kwargs);(credit_root/'ig.csv').write_bytes(b'changed');return result
        with patch.object(handoff.market,'native_risk',side_effect=changed),self.assertRaisesRegex(ValueError,'CREDIT_CHANGED'):
            self.run_prepare(current_credit_input_root=credit_root,current_credit_request_sha256=pin)
        self.assertFalse(self.dest.exists())

    def test_old_session_and_unready_producer_never_renew(self):
        for change in [dict(requested_as_of='2026-11-10'),dict(status='BLOCKED'),dict(orders_generated=True),
                       dict(truth_class='PIT_VERIFIED'),dict(builder_sha256='b'*64),dict(ledger_mutated=0)]:
            self.packet=copy.deepcopy(self.manifest);self.packet.update(change)
            with self.subTest(change=change),self.assertRaises(ValueError):self.run_prepare()
        self.assertFalse(self.dest.exists())

    def test_wrong_manifest_shape_is_a_finite_refusal(self):
        for payload in ([], {'outputs':[]}):
            raw=encoded(payload);(self.source/'manifest.json').write_bytes(raw)
            with self.subTest(payload=payload),self.assertRaisesRegex(ValueError,'MANIFEST_SCHEMA'):
                handoff.prepare(self.source,digest(raw),cutoff=NOW,output_dir=self.dest)
        self.assertFalse(self.dest.exists())

    def test_calendar_artifact_hash_and_mapping_remain_mandatory(self):
        raw=self.bodies['calendar'].replace(b'2026-11-11',b'2026-11-10')
        self.replace('calendar',raw)
        with self.assertRaises(ValueError):self.run_prepare()
        self.assertFalse(self.dest.exists())

    def test_future_row_clock_fails_original_native_validator(self):
        frame=handoff.market.clock.table(self.bodies['metrics'])
        frame.loc[frame.index[-1],'available_from']='2026-11-12T10:00:01Z'
        self.replace('metrics',frame.to_csv(index=False).encode())
        with self.assertRaisesRegex(ValueError,'future_available_from'):self.run_prepare()
        self.assertFalse(self.dest.exists())

    def test_missing_required_credit_does_not_emit_partial_request(self):
        frame=handoff.market.clock.table(self.bodies['metrics'])
        self.replace('metrics',frame[frame.axis!='credit'].to_csv(index=False).encode())
        with self.assertRaisesRegex(ValueError,'TEN_AXIS_NOT_READY'):self.run_prepare()
        credit_root=self.root/'credit';retained_credit_input(credit_root,now=NOW)
        with self.assertRaisesRegex(ValueError,'TEN_AXIS_NOT_READY'):
            self.run_prepare(current_credit_input_root=credit_root,
                current_credit_request_sha256=digest((credit_root/'request.json').read_bytes()))
        self.assertFalse(self.dest.exists())

    def test_source_lineage_and_truth_cannot_be_relabelled(self):
        frame=handoff.market.clock.table(self.bodies['metrics'])
        for column,value in [('source_sha256','c'*64),('truth_class','PIT_VERIFIED')]:
            changed=frame.copy();changed.loc[0,column]=value
            self.replace('metrics',changed.to_csv(index=False).encode())
            with self.subTest(column=column),self.assertRaisesRegex(ValueError,'ROW_LINEAGE_OR_TRUTH'):self.run_prepare()

    def test_source_change_during_native_replay_is_refused(self):
        original=handoff.market.native_risk
        def changed(*args,**kw):
            result=original(*args,**kw)
            (self.source/'source_audit.csv').write_bytes(b'changed')
            return result
        with patch.object(handoff.market,'native_risk',changed),self.assertRaisesRegex(ValueError,'SOURCE_CHANGED'):
            self.run_prepare()
        self.assertFalse(self.dest.exists())

    def test_destination_conflict_checked_before_any_object_write(self):
        self.dest.mkdir();(self.dest/'request.json').write_bytes(b'unrelated')
        with self.assertRaisesRegex(ValueError,'DESTINATION_CONFLICT'):self.run_prepare()
        self.assertEqual([p.name for p in self.dest.iterdir()],['request.json'])

    def test_input_output_overlap_refused(self):
        with self.assertRaisesRegex(ValueError,'PATH_OVERLAP'):self.run_prepare(output_dir=self.source/'output')

    def test_interruption_before_receipt_has_no_commit_marker_and_resumes(self):
        original=handoff.exclusive
        def interrupted(path,body):
            if Path(path).name=='native-preparation.json':raise OSError('synthetic interruption')
            return original(path,body)
        with patch.object(handoff,'exclusive',interrupted),self.assertRaises(OSError):self.run_prepare()
        self.assertFalse((self.dest/'request.sha256').exists())
        self.run_prepare()
        self.assertTrue((self.dest/'native-preparation.json').exists())
        self.assertTrue((self.dest/'request.sha256').exists())

    def test_runtime_identity_change_before_publication_refused(self):
        current=handoff.market.implementation_identity(); changed=dict(current,synthetic='a'*64)
        with patch.object(handoff.market,'implementation_identity',side_effect=[current,changed]),\
             self.assertRaisesRegex(ValueError,'CODE_CHANGED'):self.run_prepare()
        self.assertFalse(self.dest.exists())

    def test_hosted_attempt_root_and_native_failure_gate_in_real_shell(self):
        workflow=yaml.safe_load((ROOT/'.github/workflows/daily_crisis_monitor.yml').read_text())
        steps=workflow['jobs']['monitor']['steps']
        step=next(s for s in steps if s.get('id')=='a4_native_prepare')
        self.assertIn('A4_NATIVE_SOURCE_MANIFEST_SHA256',step['if'])
        self.assertTrue(step['continue-on-error'])
        self.assertLess(step['run'].index('A4_NATIVE_INPUT_ROOT='),step['run'].index('python tools/prepare_'))
        collect=next(s for s in steps if s.get('id')=='a4_primary_collect')
        self.assertIn('${A4_NATIVE_INPUT_ROOT:-outputs/market_analysis_inputs}',collect['run'])
        for name in ('Run daily crisis monitor','Upload daily crisis artifact','Sync daily crisis status to Google Drive'):
            guarded=next(s for s in steps if s.get('name')==name)
            self.assertIn("steps.a4_native_prepare.outcome == 'success'",guarded['if'])
        bash=str(Path(os.environ.get('ProgramFiles','C:/Program Files'))/'Git/bin/bash.exe') if os.name=='nt' else shutil.which('bash')
        self.assertTrue(bash and Path(bash).is_file())
        baseline=dict(os.environ,RESEARCH_ENABLED='false',PRIMARY_ENABLED='true',FINANCING_ENABLED='false',
            PRIMARY_CONFIG='success',PRIMARY='success',DATA_CENTER='success',NATIVE_PIN='',CREDIT_PIN='',NATIVE='failure')
        cases=[({},True),({'NATIVE_PIN':'a'*64,'NATIVE':'success'},True)]
        cases += [({'NATIVE_PIN':'a'*64,'CREDIT_PIN':'b'*64,'NATIVE':'success'},True),
                  ({'CREDIT_PIN':'b'*64,'NATIVE':'success'},False)]
        cases += [({'NATIVE_PIN':'a'*64,'NATIVE':state},False) for state in ('failure','skipped','cancelled')]
        cases += [({'NATIVE_PIN':'a'*64,'NATIVE':'success','PRIMARY_ENABLED':'false'},False)]
        for fields,passed in cases:
            with self.subTest(fields=fields):
                result=subprocess.run([bash,'-c',steps[-1]['run']],env=dict(baseline,**fields),capture_output=True,timeout=10)
                self.assertEqual(result.returncode==0,passed)

    def test_hosted_credit_arguments_are_default_off_and_separately_pinned_in_decoded_shell(self):
        workflow=yaml.safe_load((ROOT/'.github/workflows/daily_crisis_monitor.yml').read_text())
        step=next(s for s in workflow['jobs']['monitor']['steps'] if s.get('id')=='a4_native_prepare')
        bash=str(Path(os.environ.get('ProgramFiles','C:/Program Files'))/'Git/bin/bash.exe') if os.name=='nt' else shutil.which('bash')
        script=step['run'].replace('${{ github.run_id }}','witness').replace('${{ github.run_attempt }}','1')
        script='python() { printf "%s\\n" "$@" > "$ARG_FILE"; }\n'+script
        for i,pin in enumerate(('', 'b'*64)):
            with self.subTest(credit_configured=bool(pin)):
                work=self.root/str(i);work.mkdir();args=work/'args.txt';envfile=work/'environment.txt'
                env=dict(os.environ,NATIVE_MANIFEST_SHA256='a'*64,CURRENT_CREDIT_REQUEST_SHA256=pin,
                    ARG_FILE=args.as_posix(),GITHUB_ENV=envfile.as_posix())
                result=subprocess.run([bash,'-c',script],cwd=work,env=env,capture_output=True,timeout=10)
                self.assertEqual(result.returncode,0,result.stderr.decode(errors='replace'))
                tokens=args.read_text().splitlines()
                if pin:
                    self.assertEqual(tokens[tokens.index('--current-credit-input-root')+1],
                        'outputs/market_analysis_inputs/current_credit')
                    self.assertEqual(tokens[tokens.index('--current-credit-request-sha256')+1],pin)
                else:self.assertNotIn('--current-credit-input-root',tokens)
                self.assertIn('A4_NATIVE_INPUT_ROOT=outputs/a4_native_preparation/witness-1',envfile.read_text())


if __name__=='__main__':unittest.main()
