import copy
import importlib
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tools import run_ab_result_verifier as verifier
try:
    from research import evaluation_v2_admission as m
except ImportError:
    m = None

class ComparisonPrecheckTests(unittest.TestCase):
    def setUp(self):
        global m
        if m is None:
            m = importlib.import_module('research.evaluation_v2_admission')
        self.blobs={role: ('synthetic-'+role).encode() for role in m.SHARED_ROLES}
        self.blobs.update(control=b'fixed-old-policy', challenger=b'new-policy-not-promoted')
        def ref(key): return {'artifact_id':key, 'sha256':m.digest(self.blobs[key])}
        self.ref=ref
        self.context={'schema':m.SCHEMA,'window_start':'2020-01-02','window_end':'2020-02-03',
                      'base_currency':'USD','initial_capital':100000,
                      'official_metric_mode':'broker_ledger_next_close','data_scope':'SYNTHETIC',
                      'shared_refs':{role:ref(role) for role in m.SHARED_ROLES}}
        self.blobs['context']=m.canonical(self.context)
        self.left={'schema':m.SCHEMA,'role':'CONTROL','context_ref':ref('context'),'strategy_ref':ref('control')}
        self.right={'schema':m.SCHEMA,'role':'CHALLENGER','context_ref':ref('context'),'strategy_ref':ref('challenger')}
        self.pin=m.digest(self.blobs['context'])
    def run_pair(self, resolver=None):
        return m.compare_environment(self.left,self.right,expected_context_sha256=self.pin,
                                     artifact_resolver=resolver or self.blobs.__getitem__)
    def rebind_context(self):
        self.blobs['context']=m.canonical(self.context);self.pin=m.digest(self.blobs['context'])
        self.left['context_ref']=self.ref('context');self.right['context_ref']=self.ref('context')
    def test_same_environment_different_strategies_allowed(self):
        self.assertEqual(self.run_pair()['status'],'BYTE_COMPARABLE_RESEARCH_ONLY')
    def test_no_economic_authority(self):
        r=self.run_pair()
        for key in ('g0_certified','economic_comparison_ready','champion_promotion_allowed',
                    'public_publication_allowed','fullrun_allowed','target_paper_broker_mutation_allowed'):
            self.assertIs(r[key],False)
    def test_not_mutating_inputs(self):
        before=copy.deepcopy((self.left,self.right,self.context,self.blobs));self.run_pair()
        self.assertEqual(before,(self.left,self.right,self.context,self.blobs))
    def test_deterministic(self): self.assertEqual(self.run_pair(),self.run_pair())
    def test_common_artifacts_resolve_once(self):
        calls=[]
        self.run_pair(lambda k:(calls.append(k),self.blobs[k])[1])
        self.assertEqual(len(calls),len(set(calls)))
    def test_context_pin_required(self):
        with self.assertRaisesRegex(m.AdmissionError,'EXPECTED_CONTEXT'):
            m.compare_environment(self.left,self.right,expected_context_sha256='',artifact_resolver=self.blobs.__getitem__)
    def test_changed_context_rejected(self):
        self.right['context_ref']['sha256']='0'*64
        with self.assertRaisesRegex(m.AdmissionError,'CONTEXT_PIN'):self.run_pair()
    def test_shared_byte_tamper_rejected(self):
        self.blobs['cost_contract']+=b'tamper'
        with self.assertRaisesRegex(m.AdmissionError,'HASH_MISMATCH'):self.run_pair()
    def test_missing_artifact_not_zero(self):
        del self.blobs['risk_free']
        with self.assertRaisesRegex(m.AdmissionError,'ARTIFACT_UNAVAILABLE'):self.run_pair()
    def test_provider_exception_redacted(self):
        def broken(_):raise RuntimeError('secret-token-DO-NOT-LEAK')
        with self.assertRaises(m.AdmissionError) as caught:self.run_pair(broken)
        self.assertNotIn('secret',str(caught.exception))
    def test_foreign_admission_error_is_not_trusted_reason_text(self):
        def broken(_):raise m.AdmissionError('private-token-DO-NOT-LEAK')
        with self.assertRaisesRegex(m.AdmissionError,'ARTIFACT_UNAVAILABLE') as caught:self.run_pair(broken)
        self.assertNotIn('private',str(caught.exception))
    def test_unknown_authority_field_rejected(self):
        self.left['orders_allowed']=True
        with self.assertRaisesRegex(m.AdmissionError,'ARM_FIELDS'):self.run_pair()
    def test_roles_not_interchangeable(self):
        self.right['role']='CONTROL'
        with self.assertRaisesRegex(m.AdmissionError,'ARM_ROLE'):self.run_pair()
    def test_bool_capital_rejected(self):
        self.context['initial_capital']=True;self.rebind_context()
        with self.assertRaisesRegex(m.AdmissionError,'INITIAL_CAPITAL'):self.run_pair()
    def test_negative_capital_rejected(self):
        self.context['initial_capital']=-1;self.rebind_context()
        with self.assertRaisesRegex(m.AdmissionError,'INITIAL_CAPITAL'):self.run_pair()
    def test_huge_capital_rejected(self):
        self.context['initial_capital']=10**1000;self.rebind_context()
        with self.assertRaisesRegex(m.AdmissionError,'INITIAL_CAPITAL'):self.run_pair()
    def test_next_open_not_silent_official_change(self):
        self.context['official_metric_mode']='broker_ledger_next_open';self.rebind_context()
        with self.assertRaisesRegex(m.AdmissionError,'OFFICIAL_MODE'):self.run_pair()
    def test_missing_shared_role_rejected(self):
        del self.context['shared_refs']['calendar'];self.rebind_context()
        with self.assertRaisesRegex(m.AdmissionError,'SHARED_ROLES'):self.run_pair()
    def test_unknown_shared_role_rejected(self):
        self.context['shared_refs']['target_book']=self.ref('control');self.rebind_context()
        with self.assertRaisesRegex(m.AdmissionError,'SHARED_ROLES'):self.run_pair()
    def test_window_order_rejected(self):
        self.context['window_end']=self.context['window_start'];self.rebind_context()
        with self.assertRaisesRegex(m.AdmissionError,'WINDOW_ORDER'):self.run_pair()
    def test_invalid_calendar_date_rejected(self):
        self.context['window_start']='2020-02-31';self.rebind_context()
        with self.assertRaisesRegex(m.AdmissionError,'WINDOW_DATE'):self.run_pair()
    def test_unknown_data_scope_rejected(self):
        self.context['data_scope']=['TRUE_FORWARD'];self.rebind_context()
        with self.assertRaisesRegex(m.AdmissionError,'DATA_SCOPE'):self.run_pair()
    def test_non_bytes_resolver_rejected(self):
        with self.assertRaisesRegex(m.AdmissionError,'ARTIFACT_TYPE'):self.run_pair(lambda k:self.blobs[k].decode())
    def test_reference_unknown_fields_rejected(self):
        self.right['strategy_ref']['approved']=True
        with self.assertRaisesRegex(m.AdmissionError,'REFERENCE_FIELDS'):self.run_pair()
    def test_same_artifact_id_conflict_rejected(self):
        self.right['strategy_ref']['artifact_id']='control'
        with self.assertRaisesRegex(m.AdmissionError,'ARTIFACT_ID_CONFLICT'):self.run_pair()
    def test_duplicate_json_key(self):
        with self.assertRaisesRegex(m.AdmissionError,'DUPLICATE_JSON_KEY'):m.strict_json(b'{"x":1,"x":2}')
    def test_json_nan_and_overflow(self):
        for text in (b'{"x":NaN}',b'{"x":Infinity}',b'{"x":1e999}'):
            with self.subTest(text=text),self.assertRaisesRegex(m.AdmissionError,'NONFINITE'):m.strict_json(text)
    def test_json_depth(self):
        raw=b'{"x":'+b'['*40+b'0'+b']'*40+b'}'
        with self.assertRaisesRegex(m.AdmissionError,'JSON_DEPTH'):m.strict_json(raw)
    def test_json_node_budget(self):
        with patch.object(m,'MAX_NODES',3),self.assertRaisesRegex(m.AdmissionError,'NODE_BUDGET'):
            m.strict_json(b'{"x":[1,2,3]}')
    def test_single_blob_budget(self):
        with patch.object(m,'MAX_BLOB_BYTES',1),self.assertRaisesRegex(m.AdmissionError,'ARTIFACT_BYTE_BUDGET'):
            self.run_pair()
    def test_total_budget_and_failed_bytes_charged(self):
        snap=m._Snapshot(lambda _k:b'abcd')
        with patch.object(m,'MAX_TOTAL_BYTES',8):
            for i in range(2):
                with self.assertRaisesRegex(m.AdmissionError,'HASH_MISMATCH'):
                    snap.read({'artifact_id':str(i),'sha256':'0'*64})
            self.assertEqual(snap.returned_bytes,8)
            with self.assertRaisesRegex(m.AdmissionError,'TOTAL_BYTE_BUDGET'):
                snap.read({'artifact_id':'3','sha256':'0'*64})
    def test_module_performs_no_file_network_calls(self):
        with (patch('builtins.open',side_effect=AssertionError('file access forbidden')),
              patch('socket.socket',side_effect=AssertionError('network forbidden'))):
            self.assertEqual(self.run_pair()['data_scope'],'SYNTHETIC')

    def test_v1_schema_and_thirteen_role_context_rejected(self):
        self.context['schema']='r1000-evaluation-v2-comparison-precheck-v1'
        for role in ('pit_availability','reference_initial_capital','decision_clock_schema'):
            del self.context['shared_refs'][role]
        self.rebind_context()
        with self.assertRaisesRegex(m.AdmissionError,'SCHEMA'):self.run_pair()

    def test_all_sixteen_shared_roles_are_individually_required(self):
        self.assertEqual(len(m.SHARED_ROLES),16)
        original=copy.deepcopy(self.context['shared_refs'])
        for role in sorted(original):
            with self.subTest(role=role):
                self.context['shared_refs']=copy.deepcopy(original)
                del self.context['shared_refs'][role]
                self.rebind_context()
                with self.assertRaisesRegex(m.AdmissionError,'SHARED_ROLES'):self.run_pair()

    def test_flat_reference_ids_reject_paths_and_windows_aliases(self):
        for artifact_id in ('../cost','sub/cost','sub\\cost','C:cost','C:/cost',
                            '.', '..', 'cost.', 'CON', 'con.json', 'NUL', 'COM1', 'LPT9.txt',
                            '', True, 1, ['cost'], 'cost\x00', 'cost:stream'):
            with self.subTest(artifact_id=artifact_id):
                self.left['strategy_ref']['artifact_id']=artifact_id
                with self.assertRaisesRegex(m.AdmissionError,'ARTIFACT_ID'):self.run_pair()


class BoundedResolverTests(unittest.TestCase):
    def setUp(self):
        global m
        if m is None:m=importlib.import_module('research.evaluation_v2_admission')
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)/'bundle';self.root.mkdir()
        (self.root/'artifact').write_bytes(b'actual bytes')

    def test_reads_only_actual_bounded_regular_file_bytes(self):
        resolver=m.BoundedArtifactResolver(self.root)
        self.assertEqual(resolver('artifact'),b'actual bytes')
        with self.assertRaisesRegex(m.AdmissionError,'ARTIFACT_ID'):resolver('../outside')

    def test_missing_directory_and_non_file_are_bounded_errors(self):
        for root in (self.root/'missing', self.root/'artifact', True, None):
            with self.subTest(root=root),self.assertRaises(m.AdmissionError):m.BoundedArtifactResolver(root)
        (self.root/'directory').mkdir()
        for artifact in ('missing','directory'):
            with self.subTest(artifact=artifact),self.assertRaises(m.AdmissionError):m.BoundedArtifactResolver(self.root)(artifact)

    def test_oversize_file_rejected_before_bytes_are_read(self):
        resolver=m.BoundedArtifactResolver(self.root)
        with patch.object(m,'MAX_BLOB_BYTES',2),patch.object(m.os,'read',side_effect=AssertionError('must not read')):
            with self.assertRaisesRegex(m.AdmissionError,'ARTIFACT_BYTE_BUDGET'):resolver('artifact')

    def test_native_total_budget_includes_arm_declaration_reads(self):
        resolver=m.BoundedArtifactResolver(self.root)
        with patch.object(m,'MAX_TOTAL_BYTES',5):
            with self.assertRaisesRegex(m.AdmissionError,'TOTAL_BYTE_BUDGET'):resolver('artifact')

    def test_os_exception_payload_is_redacted(self):
        resolver=m.BoundedArtifactResolver(self.root)
        with patch.object(m.os,'open',side_effect=OSError('private-token-do-not-leak')):
            with self.assertRaises(m.AdmissionError) as caught:resolver('artifact')
        self.assertNotIn('private',str(caught.exception))

    def test_descriptor_identity_change_rejected_before_read(self):
        resolver=m.BoundedArtifactResolver(self.root)
        outside=Path(self.tmp.name)/'outside';outside.write_bytes(b'private bytes')
        fd=os.open(outside,os.O_RDONLY)
        with patch.object(m.os,'open',return_value=fd),patch.object(m.os,'read',side_effect=AssertionError('must not read')):
            with self.assertRaisesRegex(m.AdmissionError,'ARTIFACT_CHANGED'):resolver('artifact')

    @unittest.skipUnless(os.name=='posix' and hasattr(os,'mkfifo'),'POSIX FIFO race boundary')
    def test_regular_to_fifo_open_race_is_nonblocking_and_rejected(self):
        resolver=m.BoundedArtifactResolver(self.root)
        original=m.os.open
        def replace_before_open(path,flags):
            Path(path).unlink();os.mkfifo(path)
            return original(path,flags)
        with patch.object(m.os,'open',side_effect=replace_before_open),\
             patch.object(m.os,'read',side_effect=AssertionError('must not read')):
            with self.assertRaisesRegex(m.AdmissionError,'ARTIFACT_CHANGED'):resolver('artifact')

    def test_leaf_and_root_symlink_escape_rejected(self):
        outside=Path(self.tmp.name)/'outside';outside.write_bytes(b'private bytes')
        alias=Path(self.tmp.name)/'alias'
        try:
            (self.root/'link').symlink_to(outside)
            alias.symlink_to(self.root,target_is_directory=True)
        except OSError as exc:
            self.skipTest('Host cannot create symlink fixtures: '+type(exc).__name__)
        with self.assertRaises(m.AdmissionError):m.BoundedArtifactResolver(self.root)('link')
        with self.assertRaises(m.AdmissionError):m.BoundedArtifactResolver(alias)

    def test_root_replacement_after_snapshot_creation_is_rejected(self):
        resolver=m.BoundedArtifactResolver(self.root)
        self.root.rename(self.root.with_name('old_bundle'))
        self.root.mkdir();(self.root/'artifact').write_bytes(b'other bytes')
        with self.assertRaisesRegex(m.AdmissionError,'ARTIFACT_ROOT_CHANGED'):resolver('artifact')

    def test_reparse_leaf_is_rejected_before_open(self):
        resolver=m.BoundedArtifactResolver(self.root)
        observed=(self.root/'artifact').lstat()
        fake=SimpleNamespace(st_mode=observed.st_mode,st_file_attributes=0x400)
        original=Path.lstat
        with patch.object(Path,'lstat',lambda path:fake if path==self.root/'artifact' else original(path)),\
             patch.object(m.os,'open',side_effect=AssertionError('must not open')):
            with self.assertRaisesRegex(m.AdmissionError,'ARTIFACT_FILE_TYPE'):resolver('artifact')

    def test_mutation_during_read_is_rejected_without_returning_bytes(self):
        resolver=m.BoundedArtifactResolver(self.root)
        original=m.os.read;changed=False
        def mutate(fd,count):
            nonlocal changed
            if not changed:
                changed=True
                (self.root/'artifact').write_bytes(b'changed longer bytes')
            return original(fd,count)
        with patch.object(m.os,'read',side_effect=mutate):
            with self.assertRaisesRegex(m.AdmissionError,'ARTIFACT_CHANGED'):resolver('artifact')
        self.assertEqual(resolver.cache,{})

    def test_symlink_in_parent_component_is_rejected(self):
        alias=Path(self.tmp.name)/'parent_alias'
        try:alias.symlink_to(self.root.parent,target_is_directory=True)
        except OSError as exc:self.skipTest('Host cannot create symlink fixtures: '+type(exc).__name__)
        with self.assertRaisesRegex(m.AdmissionError,'ARTIFACT_ROOT_INVALID'):
            m.BoundedArtifactResolver(alias/'bundle')


class ImmutableBundleLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.area=Path(self.tmp.name)
        self.fixture=ComparisonPrecheckTests();self.fixture.setUp()

    def bundle(self, name='bundle', *, shared_strategy=False, aliased_role=False, collision=None):
        f=self.fixture
        if collision:
            f.blobs[collision]=f.blobs.pop('control')
            f.left['strategy_ref']=f.ref(collision)
        if shared_strategy:f.right['strategy_ref']=dict(f.left['strategy_ref'])
        if aliased_role:
            f.context['shared_refs']['calendar']=dict(f.left['strategy_ref']);f.rebind_context()
        root=self.area/name;root.mkdir()
        for key,value in f.blobs.items():(root/key).write_bytes(value)
        (root/'control.arm').write_bytes(m.canonical(f.left))
        (root/'challenger.arm').write_bytes(m.canonical(f.right))
        args=verifier.parse_args(['--baseline-run','unused-baseline','--candidate-run','unused-candidate',
                                 '--output-dir',str(self.area/'outside-report')])
        args.comparison_admission_root=str(root);args.comparison_control_arm='control.arm'
        args.comparison_challenger_arm='challenger.arm';args.expected_context_sha256=f.pin
        return root,args

    @staticmethod
    def census(root):
        return {str(p.relative_to(root)):p.read_bytes() if p.is_file() else None for p in root.rglob('*')}

    def check_unsafe(self, args, root):
        before=self.census(root)
        reads=[];legacy=[];original=m.BoundedArtifactResolver.__call__
        def read(resolver,key):reads.append(key);return original(resolver,key)
        with patch.object(m.BoundedArtifactResolver,'__call__',read),\
             patch.object(verifier,'collect_evidence',side_effect=lambda *a:(legacy.append(a),{})[1]):
            payload=verifier.run(args)
        self.assertEqual(self.census(root),before,'input bundle changed')
        self.assertEqual(reads,[],'admission bytes read before unsafe-output rejection')
        self.assertEqual(legacy,[],'legacy bytes read before unsafe-output rejection')
        self.assertEqual(payload['status'],'blocked_comparison_admission')
        self.assertEqual(payload['comparison_admission']['reason'],'OUTPUT_ADMISSION_PATH_OVERLAP')
        self.assertFalse(payload['economic_comparison_ready'])

    def test_equal_child_ancestor_and_case_geometry_blocks_all_option_states_before_reads(self):
        root,args=self.bundle()
        outputs=[root,root/'new-report',root/'new-report'/'nested',root/'existing'/'..',self.area]
        if os.name=='nt':outputs.append(Path(str(root).swapcase()))
        for output in outputs:
            for state in ('valid','wrong_pin','half_options','zero_candidate','multi_candidate'):
                with self.subTest(output=output,state=state):
                    changed=copy.copy(args);changed.output_dir=str(output)
                    if state=='wrong_pin':changed.expected_context_sha256='0'*64
                    elif state=='half_options':changed.comparison_challenger_arm=None
                    elif state=='zero_candidate':changed.candidate_run=[]
                    elif state=='multi_candidate':changed.candidate_run=['one','two']
                    self.check_unsafe(changed,root)

    def test_each_report_filename_can_be_pinned_without_being_overwritten(self):
        for i,name in enumerate(('summary.json','candidate_verdicts.csv','report.md')):
            with self.subTest(name=name):
                self.fixture=ComparisonPrecheckTests();self.fixture.setUp()
                root,args=self.bundle('collision'+str(i),collision=name)
                args.output_dir=str(root);self.check_unsafe(args,root)

    def test_actual_symlink_output_alias_and_child_preserve_bundle(self):
        root,args=self.bundle();alias=self.area/'output-alias'
        try:alias.symlink_to(root,target_is_directory=True)
        except OSError as exc:self.skipTest('Host cannot create directory symlink: '+type(exc).__name__)
        self.assertEqual(alias.resolve(),root.resolve())
        for output in (alias,alias/'child'):
            changed=copy.copy(args);changed.output_dir=str(output);self.check_unsafe(changed,root)

    @unittest.skipUnless(os.name=='nt','Windows directory junction geometry')
    def test_actual_windows_junction_output_alias_blocks_partial_and_pin_errors(self):
        root,args=self.bundle();alias=self.area/'output-junction'
        self.assertTrue(root.resolve().is_relative_to(self.area.resolve()))
        result=subprocess.run(['cmd','/c','mklink','/J',str(alias),str(root)],capture_output=True)
        if result.returncode:self.skipTest('Host cannot create owned directory junction')
        self.assertEqual(alias.resolve(),root.resolve())
        for output in (alias,alias/'child'):
            for state in ('valid','wrong_pin','half_options'):
                with self.subTest(output=output,state=state):
                    changed=copy.copy(args);changed.output_dir=str(output)
                    if state=='wrong_pin':changed.expected_context_sha256='0'*64
                    elif state=='half_options':changed.comparison_challenger_arm=None
                    self.check_unsafe(changed,root)

    def test_unsafe_cli_returns_two_without_publishing_or_replacing_inputs(self):
        root,args=self.bundle(collision='summary.json');before=self.census(root)
        command=[sys.executable,*(['-O'] if not __debug__ else []),str(ROOT/'tools/run_ab_result_verifier.py'),
                 '--baseline-run',args.baseline_run,'--candidate-run',args.candidate_run[0],
                 '--output-dir',str(root),'--comparison-admission-root',str(root),
                 '--comparison-control-arm',args.comparison_control_arm,
                 '--comparison-challenger-arm',args.comparison_challenger_arm,
                 '--expected-context-sha256',args.expected_context_sha256]
        result=subprocess.run(command,capture_output=True,text=True,encoding='utf-8')
        self.assertEqual(result.returncode,2,result.stderr)
        self.assertEqual(self.census(root),before)
        self.assertNotIn('private',result.stderr)

    def test_outside_report_leaf_symlink_and_hardlink_cannot_alias_bundle_artifact(self):
        root,args=self.bundle()
        output=Path(args.output_dir);output.mkdir()
        for i,kind in enumerate(('symlink','hardlink')):
            for name in ('summary.json','candidate_verdicts.csv','report.md'):
                with self.subTest(kind=kind,name=name):
                    destination=output/name
                    try:
                        if kind=='symlink':destination.symlink_to(root/'cost_contract')
                        else:os.link(root/'cost_contract',destination)
                    except OSError as exc:self.skipTest('Host cannot create owned file alias: '+type(exc).__name__)
                    try:self.check_unsafe(args,root)
                    finally:destination.unlink()

    def test_last_distinct_strategy_read_revalidates_previously_read_leaf_identity(self):
        for kind in ('replace','append','missing'):
            with self.subTest(kind=kind):
                self.fixture=ComparisonPrecheckTests();self.fixture.setUp()
                root,args=self.bundle('final-leaf-'+kind)
                original=m._Snapshot.read;changed=[]
                def read(snapshot,ref):
                    value=original(snapshot,ref)
                    if ref['artifact_id']=='challenger' and not changed:
                        path=root/'cost_contract'
                        if kind=='replace':
                            path.rename(root/'old-cost');path.write_bytes(self.fixture.blobs['cost_contract'])
                        elif kind=='append':
                            with path.open('ab') as stream:stream.write(b'x')
                        else:path.unlink()
                        changed.append(True)
                    return value
                with patch.object(m._Snapshot,'read',read):result=verifier.comparison_precheck(args)
                self.assertTrue(changed);self.assertEqual(result['status'],'BLOCKED')
                self.assertIn(result['reason'],('ARTIFACT_CHANGED','ARTIFACT_UNAVAILABLE'))

    def test_real_root_replacement_on_shared_and_last_distinct_strategy_tails_blocks(self):
        for shared,trigger in ((True,'control'),(False,'control'),(False,'challenger')):
            with self.subTest(shared=shared,trigger=trigger):
                self.fixture=ComparisonPrecheckTests();self.fixture.setUp()
                root,args=self.bundle('tail'+str(shared)+trigger,shared_strategy=shared)
                original=m._Snapshot.read;changed=[]
                def read(snapshot,ref):
                    value=original(snapshot,ref)
                    if ref['artifact_id']==trigger and not changed:
                        prior=root.stat().st_ino;root.rename(root.with_name(root.name+'-retired'));root.mkdir()
                        self.assertNotEqual(root.stat().st_ino,prior);changed.append(True)
                    return value
                with patch.object(m._Snapshot,'read',read):result=verifier.comparison_precheck(args)
                self.assertTrue(changed)
                self.assertEqual(result['status'],'BLOCKED')
                self.assertEqual(result['reason'],'ARTIFACT_ROOT_CHANGED')

    def test_final_cached_leaf_snapshot_detects_replace_append_truncate_missing_and_link(self):
        for kind in ('replace','append','truncate','missing','symlink'):
            with self.subTest(kind=kind):
                self.fixture=ComparisonPrecheckTests();self.fixture.setUp()
                root,args=self.bundle('leaf-'+kind,shared_strategy=True)
                original=m._Snapshot.read;changed=[]
                def read(snapshot,ref):
                    value=original(snapshot,ref)
                    if ref['artifact_id']=='control' and not changed:
                        path=root/'cost_contract'
                        if kind=='replace':
                            path.rename(root/'old-cost');path.write_bytes(self.fixture.blobs['cost_contract'])
                        elif kind=='append':
                            with path.open('ab') as stream:stream.write(b'x')
                        elif kind=='truncate':path.write_bytes(b'')
                        elif kind=='missing':path.unlink()
                        else:
                            path.unlink()
                            try:path.symlink_to(root/'control')
                            except OSError as exc:self.skipTest('Host cannot create leaf symlink: '+type(exc).__name__)
                        changed.append(True)
                    return value
                with patch.object(m._Snapshot,'read',read):result=verifier.comparison_precheck(args)
                self.assertTrue(changed)
                self.assertEqual(result['status'],'BLOCKED')
                self.assertIn(result['reason'],('ARTIFACT_CHANGED','ARTIFACT_UNAVAILABLE','ARTIFACT_FILE_TYPE'))

    def test_native_cached_direct_reads_revalidate_root_and_leaf_without_recharging(self):
        root,args=self.bundle();resolver=m.BoundedArtifactResolver(root)
        first=resolver('context');total=resolver.returned_bytes
        self.assertEqual(resolver('context'),first);self.assertEqual(resolver.returned_bytes,total)
        (root/'context').write_bytes(first+b'changed')
        with self.assertRaises(m.AdmissionError):resolver('context')
        root.rename(self.area/'retired');root.mkdir()
        with self.assertRaisesRegex(m.AdmissionError,'ARTIFACT_ROOT_CHANGED'):resolver('context')

    def test_native_totals_include_arms_and_deduplicate_shared_role_and_strategy_ids(self):
        for shared in (False,True):
            for alias in (False,True):
                with self.subTest(shared=shared,alias=alias):
                    self.fixture=ComparisonPrecheckTests();self.fixture.setUp()
                    root,args=self.bundle('counts'+str(shared)+str(alias),shared_strategy=shared,aliased_role=alias)
                    observed=[];original=m.BoundedArtifactResolver.__call__
                    def read(resolver,key):
                        value=original(resolver,key);observed.append((key,len(value),resolver.returned_bytes));return value
                    with patch.object(m.BoundedArtifactResolver,'__call__',read):result=verifier.comparison_precheck(args)
                    self.assertEqual(result['status'],'BYTE_COMPARABLE_RESEARCH_ONLY')
                    unique={key:size for key,size,total in observed}
                    self.assertEqual(result['resolved_artifacts'],len(unique))
                    self.assertEqual(result['resolved_bytes'],sum(unique.values()))
                    self.assertEqual(result['resolved_bytes'],observed[-1][2])

    def test_native_preloaded_arm_budget_and_foreign_inmemory_counts_remain_distinct(self):
        root,args=self.bundle();f=self.fixture
        calls=[]
        result=m.compare_environment(f.left,f.right,expected_context_sha256=f.pin,
                                     artifact_resolver=lambda key:(calls.append(key),f.blobs[key])[1])
        self.assertEqual(result['resolved_artifacts'],len(set(calls)))
        self.assertEqual(result['resolved_bytes'],sum(len(f.blobs[key]) for key in set(calls)))
        self.assertNotIn('control.arm',calls)
        resolver=m.BoundedArtifactResolver(root)
        left=m.strict_json(resolver('control.arm'));right=m.strict_json(resolver('challenger.arm'))
        native=m.compare_environment(left,right,expected_context_sha256=f.pin,artifact_resolver=resolver)
        self.assertEqual(native['resolved_artifacts'],result['resolved_artifacts']+2)
        self.assertEqual(native['resolved_bytes'],result['resolved_bytes']+len(m.canonical(f.left))+len(m.canonical(f.right)))
        with patch.object(m,'MAX_TOTAL_BYTES',native['resolved_bytes']-1):
            blocked=verifier.comparison_precheck(args)
        self.assertEqual(blocked['reason'],'TOTAL_BYTE_BUDGET')


class NativeIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        fixtures=runpy.run_path(str(ROOT/'tests'/'ab_result_verifier_smoke.py'))
        self.baseline,self.candidate=self.root/'baseline',self.root/'candidate'
        for location, cagr, is_cagr in ((self.baseline,.51,.30),(self.candidate,.52,.31)):
            fixtures['seed_run'](location,cagr=cagr,max_dd=-.24,is_cagr=is_cagr,
                                 years=8.10,target_pass=True,strengthened_pass=True)
        self.args=fixtures['args'](self.baseline,[self.candidate],self.root/'out')

    def options(self, **changes):
        values=dict(comparison_admission_root=str(self.root/'bundle'),
                    comparison_control_arm='control.arm.json',
                    comparison_challenger_arm='challenger.arm.json',
                    expected_context_sha256='0'*64)
        values.update(changes)
        for key,value in values.items():setattr(self.args,key,value)

    def test_partial_options_block_before_legacy_reads(self):
        for missing in verifier.COMPARISON_OPTIONS:
            with self.subTest(missing=missing):
                self.options(**{missing:None})
                with patch.object(verifier,'collect_evidence',side_effect=AssertionError('legacy read forbidden')):
                    result=verifier.run(self.args)
                self.assertEqual(result['status'],'blocked_comparison_admission')
                self.assertEqual(result['comparison_admission']['reason'],'ADMISSION_OPTIONS_INCOMPLETE')

    def test_multiple_candidates_block_before_legacy_reads(self):
        self.options()
        for candidates in ([],[str(self.candidate)]*2,None,True,'candidate'):
            with self.subTest(candidates=candidates):
                self.args.candidate_run=candidates
                with patch.object(verifier,'collect_evidence',side_effect=AssertionError('legacy read forbidden')):
                    result=verifier.run(self.args)
                self.assertEqual(result['comparison_admission']['reason'],'COMPARISON_SINGLE_CANDIDATE_REQUIRED')

    def test_malformed_pins_and_root_block_before_legacy_reads(self):
        for pin,reason in (('', 'EXPECTED_CONTEXT_HASH_REQUIRED'),(True,'EXPECTED_CONTEXT_HASH_REQUIRED'),
                           ('A'*64,'EXPECTED_CONTEXT_HASH_REQUIRED'),('0'*64,'ARTIFACT_ROOT_INVALID')):
            with self.subTest(pin=pin):
                self.options(expected_context_sha256=pin)
                with patch.object(verifier,'collect_evidence',side_effect=AssertionError('legacy read forbidden')):
                    result=verifier.run(self.args)
                self.assertEqual(result['comparison_admission']['reason'],reason)
                self.assertNotIn('private',json.dumps(result))
                for key in ('g0_certified','economic_comparison_ready','fullrun_allowed',
                            'champion_promotion_allowed','target_paper_broker_mutation_allowed'):
                    self.assertIs(result[key],False)

    def seed_bundle(self):
        fixture=ComparisonPrecheckTests();fixture.setUp()
        bundle=self.root/'bundle';bundle.mkdir()
        for key,raw in fixture.blobs.items():(bundle/key).write_bytes(raw)
        (bundle/'control.arm.json').write_bytes(m.canonical(fixture.left))
        (bundle/'challenger.arm.json').write_bytes(m.canonical(fixture.right))
        self.options(expected_context_sha256=fixture.pin)
        return fixture,bundle

    def test_default_behavior_has_no_admission_and_remains_review_only(self):
        result=verifier.run(self.args)
        self.assertEqual(result['status'],'review_candidate_ready')
        self.assertNotIn('comparison_admission',result)
        self.assertFalse(result['production_activation_allowed'])

    def test_matching_bytes_keep_all_unverified_authority_false(self):
        fixture,bundle=self.seed_bundle()
        result=verifier.run(self.args)
        admitted=result['comparison_admission']
        self.assertEqual(admitted['status'],'BYTE_COMPARABLE_RESEARCH_ONLY')
        self.assertEqual(admitted['unverified_domains'],list(m.UNVERIFIED))
        self.assertEqual(len(admitted['shared_roles_verified']),16)
        self.assertNotEqual(admitted['strategy_refs']['control'],admitted['strategy_refs']['challenger'])
        for key in ('g0_certified','economic_comparison_ready','champion_promotion_allowed',
                    'public_publication_allowed','fullrun_allowed','target_paper_broker_mutation_allowed'):
            self.assertIs(result[key],False)
        self.assertEqual(result['status'],'review_candidate_ready')

    def test_pin_mismatch_and_tamper_are_bounded_not_legacy_fallback(self):
        fixture,bundle=self.seed_bundle()
        for case,reason in (('pin','CONTEXT_PIN_MISMATCH'),('tamper','ARTIFACT_HASH_MISMATCH'),
                            ('duplicate','DUPLICATE_JSON_KEY')):
            with self.subTest(case=case):
                self.args.expected_context_sha256='0'*64 if case=='pin' else fixture.pin
                (bundle/'cost_contract').write_bytes(fixture.blobs['cost_contract']+ (b'tamper' if case=='tamper' else b''))
                (bundle/'control.arm.json').write_bytes(b'{"private":"secret","private":2}' if case=='duplicate' else m.canonical(fixture.left))
                with patch.object(verifier,'collect_evidence',side_effect=AssertionError('legacy read forbidden')):
                    result=verifier.run(self.args)
                self.assertEqual(result['comparison_admission']['reason'],reason)
                self.assertNotIn('secret',json.dumps(result))

    def test_native_context_budget_reasons_are_preserved(self):
        self.seed_bundle()
        for limit,name,reason in ((512,'MAX_BLOB_BYTES','ARTIFACT_BYTE_BUDGET'),
                                   (2700,'MAX_TOTAL_BYTES','TOTAL_BYTE_BUDGET')):
            with self.subTest(limit=limit),patch.object(m,name,limit),\
                 patch.object(verifier,'collect_evidence',side_effect=AssertionError('legacy read forbidden')):
                result=verifier.run(self.args)
                self.assertEqual(result['comparison_admission']['reason'],reason)

    def test_matching_admission_does_not_override_existing_window_gate(self):
        self.seed_bundle()
        fixtures=runpy.run_path(str(ROOT/'tests'/'ab_result_verifier_smoke.py'))
        fixtures['seed_run'](self.candidate,cagr=.52,max_dd=-.24,is_cagr=.31,
                             years=7.,trading_days=1764,target_pass=True,strengthened_pass=True,
                             valid_for_production=False)
        result=verifier.run(self.args)
        self.assertEqual(result['comparison_admission']['status'],'BYTE_COMPARABLE_RESEARCH_ONLY')
        self.assertEqual(result['candidates'][0]['decision'],'invalid_window')
        self.assertFalse(result['candidates'][0]['review_valid_for_promotion'])
        self.assertFalse(result['economic_comparison_ready'])

    def test_legacy_window_claim_is_not_certified_by_byte_admission(self):
        fixtures=runpy.run_path(str(ROOT/'tests'/'ab_result_verifier_smoke.py'))
        fixtures['seed_run'](self.candidate,cagr=.52,max_dd=-.24,is_cagr=.31,
                             years=7.,trading_days=1764,target_pass=True,strengthened_pass=True)
        legacy=verifier.run(self.args)
        self.seed_bundle()
        result=verifier.run(self.args)
        self.assertEqual(result['candidates'][0]['decision'],legacy['candidates'][0]['decision'])
        self.assertFalse(result['economic_comparison_ready'])
        self.assertFalse(result['g0_certified'])
        self.assertIn('EXECUTED_CODE_VS_DECLARED_CODE',result['unverified_domains'])

    def test_cli_malformed_and_valid_inputs_in_both_runtime_modes(self):
        fixture,bundle=self.seed_bundle()
        cmd=[sys.executable,*(['-O'] if not __debug__ else []),str(ROOT/'tools'/'run_ab_result_verifier.py'),
             '--baseline-run',str(self.baseline),'--candidate-run',str(self.candidate),
             '--output-dir',str(self.root/'cli-out'),'--comparison-admission-root',str(bundle),
             '--comparison-control-arm','control.arm.json','--comparison-challenger-arm','challenger.arm.json',
             '--expected-context-sha256',fixture.pin]
        good=subprocess.run(cmd,capture_output=True,text=True,encoding='utf-8')
        self.assertEqual(good.returncode,0,good.stderr)
        payload=json.loads((self.root/'cli-out'/'summary.json').read_text())
        self.assertEqual(payload['comparison_admission']['status'],'BYTE_COMPARABLE_RESEARCH_ONLY')
        bad=subprocess.run(cmd[:-1]+['0'*64],capture_output=True,text=True,encoding='utf-8')
        self.assertEqual(bad.returncode,2,bad.stderr)
        payload=json.loads((self.root/'cli-out'/'summary.json').read_text())
        self.assertEqual(payload['comparison_admission']['reason'],'CONTEXT_PIN_MISMATCH')
        self.assertEqual(payload['candidates'],[])


def suite():
    return unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromTestCase(cls)
                              for cls in (ComparisonPrecheckTests,BoundedResolverTests,ImmutableBundleLifecycleTests,NativeIntegrationTests))

def main():
    return 0 if unittest.TextTestRunner(verbosity=2).run(suite()).wasSuccessful() else 1

if __name__=='__main__':raise SystemExit(main())
