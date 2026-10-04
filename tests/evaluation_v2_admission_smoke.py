import copy
from contextlib import contextmanager
import importlib
import json
import os
import posixpath
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


@contextmanager
def patch_publication_phase(owner, attribute, hook):
    # ReportDirectory checks callable identity before using POSIX dir_fd.
    # A fixture hook inherits only its saved original's actual capability.
    original = getattr(owner, attribute)
    capabilities = os.supports_dir_fd
    with patch.object(owner, attribute, new=hook):
        if owner is os and original in capabilities:
            with patch.object(os, 'supports_dir_fd', new=capabilities | {hook}):
                yield
        else:
            yield

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

    def test_raced_growth_never_reads_beyond_blob_or_remaining_total_budget(self):
        for blob,total,prior,initial,grown in ((2,100,0,2,3),(10,5,3,2,50),(10,4,3,1,50)):
            with self.subTest(blob=blob,total=total,prior=prior):
                artifact=self.root/'artifact';artifact.write_bytes(b'a'*initial)
                (self.root/'prior').write_bytes(b'p'*prior)
                resolver=m.BoundedArtifactResolver(self.root)
                requests=[];returned=[];observed=[];original=m.os.read
                with patch.object(m,'MAX_BLOB_BYTES',blob),patch.object(m,'MAX_TOTAL_BYTES',total):
                    if prior:resolver('prior')
                    def grow(fd,count):
                        if not requests:artifact.write_bytes(b'x'*grown)
                        observed.append(resolver.returned_bytes);requests.append(count)
                        part=original(fd,count);returned.append(len(part));return part
                    with patch.object(m.os,'read',side_effect=grow),self.assertRaises(m.AdmissionError):
                        resolver('artifact')
                consumed=0
                for request,actual,counter in zip(requests,returned,observed):
                    self.assertLessEqual(request,min(blob-consumed,total-prior-consumed))
                    self.assertEqual(counter,prior+consumed)
                    consumed+=actual
                self.assertLessEqual(consumed,blob)
                self.assertLessEqual(resolver.returned_bytes,total)
                self.assertEqual(resolver.returned_bytes,prior+sum(returned))
                self.assertNotIn('artifact',resolver.cache)

    def test_zero_and_exact_budget_files_have_no_sentinel_or_post_limit_read(self):
        for blob,total,prior,size in ((0,0,0,0),(5,0,0,0),(2,2,0,2),(4,6,2,4)):
            with self.subTest(blob=blob,total=total,prior=prior,size=size):
                (self.root/'artifact').write_bytes(b'a'*size)
                (self.root/'prior').write_bytes(b'p'*prior)
                resolver=m.BoundedArtifactResolver(self.root);requests=[];actual=[];original=m.os.read
                with patch.object(m,'MAX_BLOB_BYTES',blob),patch.object(m,'MAX_TOTAL_BYTES',total):
                    if prior:resolver('prior')
                    def read(fd,count):
                        requests.append(count);part=original(fd,count);actual.append(len(part));return part
                    with patch.object(m.os,'read',side_effect=read):
                        self.assertEqual(resolver('artifact'),b'a'*size)
                        count=len(requests)
                        self.assertEqual(resolver('artifact'),b'a'*size)
                        self.assertEqual(len(requests),count,'cached bytes were re-read')
                consumed=0
                for request,returned in zip(requests,actual):
                    self.assertGreater(request,0)
                    self.assertLessEqual(request,min(blob-consumed,total-prior-consumed))
                    consumed+=returned
                if not size:self.assertEqual(requests,[])
                self.assertEqual(resolver.returned_bytes,prior+size)

    def test_short_reads_charge_each_return_before_the_next_read(self):
        (self.root/'artifact').write_bytes(b'abcdef')
        (self.root/'prior').write_bytes(b'123')
        resolver=m.BoundedArtifactResolver(self.root);original=m.os.read
        requests=[];returned=[];counters=[]
        with patch.object(m,'MAX_BLOB_BYTES',6),patch.object(m,'MAX_TOTAL_BYTES',9):
            resolver('prior')
            def short(fd,count):
                counters.append(resolver.returned_bytes);requests.append(count)
                part=original(fd,min(count,2));returned.append(len(part));return part
            with patch.object(m.os,'read',side_effect=short):
                self.assertEqual(resolver('artifact'),b'abcdef')
        consumed=0
        for request,actual,counter in zip(requests,returned,counters):
            self.assertLessEqual(request,6-consumed)
            self.assertEqual(counter,3+consumed)
            consumed+=actual
        self.assertEqual(resolver.returned_bytes,9)

    def test_partial_read_error_is_charged_redacted_and_consumes_retry_allowance(self):
        (self.root/'artifact').write_bytes(b'abcdef')
        (self.root/'retry').write_bytes(b'1234')
        resolver=m.BoundedArtifactResolver(self.root);original=m.os.read;calls=[]
        def fail_after_short_read(fd,count):
            calls.append(count)
            if len(calls)>1:raise OSError('private-token-must-not-appear')
            return original(fd,min(count,2))
        with patch.object(m,'MAX_BLOB_BYTES',6),patch.object(m,'MAX_TOTAL_BYTES',6):
            with patch.object(m.os,'read',side_effect=fail_after_short_read),self.assertRaises(m.AdmissionError) as caught:
                resolver('artifact')
            self.assertEqual(str(caught.exception),'ARTIFACT_UNAVAILABLE')
            self.assertEqual(resolver.returned_bytes,2)
            self.assertEqual(resolver.cache,{})
            with patch.object(m.os,'read',side_effect=AssertionError('budget must block before read')):
                with self.assertRaisesRegex(m.AdmissionError,'TOTAL_BYTE_BUDGET'):resolver('artifact')
            self.assertEqual(resolver('retry'),b'1234')
            self.assertEqual(resolver.returned_bytes,6)

    def test_zero_allowance_rejects_nonempty_files_before_open_and_early_eof_charges_zero(self):
        (self.root/'artifact').write_bytes(b'a')
        for blob,total,reason in ((0,5,'ARTIFACT_BYTE_BUDGET'),(1,0,'TOTAL_BYTE_BUDGET')):
            with self.subTest(blob=blob,total=total):
                resolver=m.BoundedArtifactResolver(self.root)
                with patch.object(m,'MAX_BLOB_BYTES',blob),patch.object(m,'MAX_TOTAL_BYTES',total),\
                     patch.object(m.os,'open',side_effect=AssertionError('must not open')):
                    with self.assertRaisesRegex(m.AdmissionError,reason):resolver('artifact')
                self.assertEqual(resolver.returned_bytes,0)
        resolver=m.BoundedArtifactResolver(self.root)
        with patch.object(m.os,'read',return_value=b''),self.assertRaisesRegex(m.AdmissionError,'ARTIFACT_CHANGED'):
            resolver('artifact')
        self.assertEqual(resolver.returned_bytes,0)
        self.assertEqual(resolver.cache,{})


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


    def assert_bounded_no_publication(self,payload,root,before,reason='OUTPUT_ADMISSION_PATH_OVERLAP'):
        self.assertEqual(payload['status'],'blocked_comparison_admission')
        self.assertEqual(payload['comparison_admission']['reason'],reason)
        self.assertEqual(payload['baseline'],{})
        self.assertEqual(payload['candidates'],[])
        self.assertEqual(payload['candidate_count'],0)
        self.assertEqual(payload['review_valid_candidate_count'],0)
        for name in verifier.COMPARISON_AUTHORITY_FIELDS:
            if name!='unverified_domains':self.assertIs(payload[name],False)
        self.assertEqual(self.census(root),before)

    def late_alias(self,args,root,kind):
        output=Path(args.output_dir)
        if kind=='directory':
            output.symlink_to(root,target_is_directory=True)
        elif kind=='junction':
            result=subprocess.run(['cmd','/c','mklink','/J',str(output),str(root)],capture_output=True)
            self.assertEqual(result.returncode,0,'owned junction fixture unavailable')
        else:
            output.mkdir()
            target=output/kind.split(':')[1]
            if kind.startswith('hardlink:'):os.link(root/'cost_contract',target)
            else:target.symlink_to(root/'cost_contract')

    def test_late_geometry_after_legacy_collection_returns_empty_bounded_payload(self):
        kinds=['directory',*[f'{kind}:{name}' for kind in ('symlink','hardlink')
                               for name in ('summary.json','candidate_verdicts.csv','report.md')]]
        if os.name=='nt':kinds.append('junction')
        for index,kind in enumerate(kinds):
            with self.subTest(kind=kind):
                self.fixture=ComparisonPrecheckTests();self.fixture.setUp()
                root,args=self.bundle('late-legacy'+str(index));args.output_dir=str(self.area/('late-report'+str(index)))
                before=self.census(root);reads=[]
                def collect(*values):
                    if not reads:self.late_alias(args,root,kind)
                    reads.append(values);return {}
                with patch.object(verifier,'collect_evidence',side_effect=collect),\
                     patch.object(verifier,'write_json',side_effect=AssertionError('unsafe output write')),\
                     patch.object(verifier,'write_csv',side_effect=AssertionError('unsafe output write')):
                    payload=verifier.run(args)
                self.assertEqual(len(reads),2)
                self.assert_bounded_no_publication(payload,root,before)

    def test_late_geometry_on_initially_blocked_publication_returns_bounded_payload(self):
        for index,state in enumerate(('wrong_pin','half_options','zero_candidate','multi_candidate')):
            with self.subTest(state=state):
                self.fixture=ComparisonPrecheckTests();self.fixture.setUp()
                root,args=self.bundle('late-blocked'+str(index));args.output_dir=str(self.area/('late-blocked-report'+str(index)))
                if state=='wrong_pin':args.expected_context_sha256='0'*64
                elif state=='half_options':args.comparison_challenger_arm=None
                elif state=='zero_candidate':args.candidate_run=[]
                else:args.candidate_run=['one','two']
                before=self.census(root);original=verifier.publish_report
                def publish(values,payload):
                    self.late_alias(values,root,'directory');return original(values,payload)
                with patch.object(verifier,'publish_report',side_effect=publish),\
                     patch.object(verifier,'collect_evidence',side_effect=AssertionError('blocked legacy read')),\
                     patch.object(verifier,'write_json',side_effect=AssertionError('unsafe output write')):
                    payload=verifier.run(args)
                self.assert_bounded_no_publication(payload,root,before)

    def test_late_invalid_geometry_is_redacted_in_direct_api_and_cli_still_exits_two(self):
        for index,mode in enumerate(('api','cli')):
            self.fixture=ComparisonPrecheckTests();self.fixture.setUp()
            root,args=self.bundle('late-invalid'+str(index));before=self.census(root)
            original=verifier.publish_report
            def publish(values,payload):
                values.output_dir=[];return original(values,payload)
            with patch.object(verifier,'publish_report',side_effect=publish),\
                 patch.object(verifier,'collect_evidence',return_value={}),\
                 patch.object(verifier,'write_json',side_effect=AssertionError('unsafe output write')):
                if mode=='api':
                    payload=verifier.run(args)
                    self.assert_bounded_no_publication(payload,root,before,'OUTPUT_ADMISSION_PATH_INVALID')
                else:
                    with patch.object(verifier,'parse_args',return_value=args):self.assertEqual(verifier.main([]),2)
                    self.assertEqual(self.census(root),before)

    def test_standalone_publish_guard_rejects_actual_alias_without_writing(self):
        root,args=self.bundle();before=self.census(root)
        self.late_alias(args,root,'directory')
        with patch.object(verifier,'write_json',side_effect=AssertionError('unsafe output write')):
            with self.assertRaisesRegex(m.AdmissionError,'OUTPUT_ADMISSION_PATH_OVERLAP'):
                verifier.publish_report(args,{'candidates':[]})
        self.assertEqual(self.census(root),before)

    def test_case_preserving_posix_geometry_simulation_uses_physical_ancestors(self):
        # Portable simulation, not a macOS execution claim. Real stat IDs are
        # supplied for case aliases while resolve/normcase retain POSIX spelling.
        index=0;original_stat=Path.stat
        for shape in ('equal','missing_child','existing_child','ancestor'):
            for state in ('valid','wrong_pin','half_options','zero_candidate','multi_candidate'):
                with self.subTest(shape=shape,state=state):
                    self.fixture=ComparisonPrecheckTests();self.fixture.setUp()
                    root,args=self.bundle('Bundle'+str(index));index+=1
                    if shape=='existing_child':(root/'existing').mkdir()
                    alias=root.with_name(root.name.swapcase())
                    source_prefix,target_prefix=str(alias),str(root)
                    if shape=='equal':output=alias
                    elif shape=='missing_child':output=alias/'missing'/'report'
                    elif shape=='existing_child':output=alias/'existing'/'missing'
                    else:
                        output=self.area.with_name(self.area.name.swapcase())
                        source_prefix,target_prefix=str(output),str(self.area)
                    args.output_dir=str(output)
                    if state=='wrong_pin':args.expected_context_sha256='0'*64
                    elif state=='half_options':args.comparison_challenger_arm=None
                    elif state=='zero_candidate':args.candidate_run=[]
                    elif state=='multi_candidate':args.candidate_run=['one','two']
                    def physical_stat(path,*a,**kw):
                        value=str(path)
                        if value==source_prefix or value.startswith(source_prefix+os.sep):
                            path=Path(target_prefix+value[len(source_prefix):])
                        return original_stat(path,*a,**kw)
                    def lexical_common(paths):
                        return posixpath.commonpath([str(p).replace('\\','/') for p in paths])
                    with patch.object(Path,'resolve',lambda path,strict=False:path.absolute()),\
                         patch.object(Path,'stat',physical_stat),\
                         patch.object(verifier.os.path,'normcase',lambda value:value),\
                         patch.object(verifier.os.path,'commonpath',lexical_common):
                        self.assertEqual(verifier.comparison_output_error(args),'OUTPUT_ADMISSION_PATH_OVERLAP')
                        self.check_unsafe(args,root)

    def test_disjoint_missing_output_shared_parent_is_not_physical_overlap(self):
        root,args=self.bundle();args.output_dir=str(self.area/'missing-disjoint'/'nested-report')
        before=self.census(root)
        with patch.object(verifier,'collect_evidence',return_value={}):payload=verifier.run(args)
        self.assertEqual(payload['comparison_admission']['status'],'BYTE_COMPARABLE_RESEARCH_ONLY')
        self.assertTrue((Path(args.output_dir)/'summary.json').is_file())
        self.assertEqual(self.census(root),before)
        self.assertFalse(payload['economic_comparison_ready'])

    def test_physical_identity_observation_errors_are_redacted_before_any_reads(self):
        root,args=self.bundle();original=Path.stat
        def unavailable(path,*a,**kw):
            if path==root:raise OSError('private-token-must-not-appear')
            return original(path,*a,**kw)
        with patch.object(Path,'stat',unavailable),\
             patch.object(m.BoundedArtifactResolver,'__call__',side_effect=AssertionError('must not read')),\
             patch.object(verifier,'collect_evidence',side_effect=AssertionError('must not read')),\
             patch.object(verifier,'write_json',side_effect=AssertionError('must not publish')):
            payload=verifier.run(args)
        self.assertEqual(payload['comparison_admission']['reason'],'OUTPUT_ADMISSION_PATH_INVALID')
        self.assertEqual(payload['candidates'],[])


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


class AnchoredPublicationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = ImmutableBundleLifecycleTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.area = self.fixture.area

    def invocation(self, label, leaf='summary.json', blocked=False):
        from ab_result_verifier_smoke import seed_run
        self.fixture.fixture = ComparisonPrecheckTests()
        self.fixture.fixture.setUp()
        root, args = self.fixture.bundle(label, collision=leaf)
        for role, cagr, is_cagr in (('baseline', .51, .30), ('candidate', .52, .31)):
            path = self.area / (label + '-' + role)
            seed_run(path, cagr=cagr, max_dd=-.24, is_cagr=is_cagr, years=8.10,
                     target_pass=True, strengthened_pass=True)
            setattr(args, 'baseline_run' if role == 'baseline' else 'candidate_run',
                    str(path) if role == 'baseline' else [str(path)])
        args.output_dir = str(self.area / (label + '-report'))
        if blocked: args.expected_context_sha256 = '0' * 64
        return root, args

    def call(self, args, cli=False):
        import contextlib
        import io
        with contextlib.redirect_stdout(io.StringIO()):
            if not cli: return verifier.run(args)
            values = ['--baseline-run', args.baseline_run, '--output-dir', args.output_dir]
            for candidate in args.candidate_run: values += ['--candidate-run', candidate]
            for name in verifier.COMPARISON_OPTIONS:
                value = getattr(args, name, None)
                if value is not None: values += ['--' + name.replace('_', '-'), value]
            return verifier.main(values)

    def assert_bounded(self, result, current_receipt=False):
        self.assertEqual(result['status'], 'blocked_comparison_admission')
        self.assertEqual(result['candidates'], [])
        self.assertEqual(result['candidate_count'], 0)
        self.assertIs(result['current_receipt'], current_receipt)
        for key in verifier.COMPARISON_AUTHORITY_FIELDS:
            if key != 'unverified_domains': self.assertIs(result[key], False)
        self.assertNotIn('private-token', json.dumps(result))

    def test_after_geometry_directory_aliases_preserve_every_input(self):
        for leaf in ('summary.json', 'candidate_verdicts.csv', 'report.md'):
            for blocked in (False, True):
                for missing in (False, True):
                    for cli in (False, True):
                        with self.subTest(leaf=leaf, blocked=blocked, missing=missing, cli=cli):
                            label = 'geometry-' + str((leaf, blocked, missing, cli))
                            root, args = self.invocation(label, leaf, blocked)
                            output = Path(args.output_dir)
                            if not missing: output.mkdir()
                            before = self.fixture.census(root); original = verifier.comparison_output_error
                            active = False; fired = False
                            old_publish = verifier.publish_report
                            def publish(values, payload):
                                nonlocal active
                                active = True
                                return old_publish(values, payload)
                            def geometry(values):
                                nonlocal fired
                                result = original(values)
                                if active and not fired:
                                    fired = True
                                    if output.exists(): output.rename(output.with_name(output.name + '-parked'))
                                    output.symlink_to(root, target_is_directory=True)
                                return result
                            with patch.object(verifier, 'publish_report', side_effect=publish), \
                                 patch.object(verifier, 'comparison_output_error', side_effect=geometry):
                                result = self.call(args, cli)
                            self.assertTrue(fired)
                            self.assertEqual(self.fixture.census(root), before)
                            if cli: self.assertEqual(result, 2)
                            else: self.assert_bounded(result)

    def test_after_geometry_leaf_symlink_and_hardlink_substitutions_do_not_truncate_inputs(self):
        for leaf in ('summary.json', 'candidate_verdicts.csv', 'report.md'):
            for blocked in (False, True):
                for link in ('symlink', 'hardlink'):
                    with self.subTest(leaf=leaf, blocked=blocked, link=link):
                        root, args = self.invocation('leaf-' + str((leaf, blocked, link)), leaf, blocked)
                        output = Path(args.output_dir); output.mkdir()
                        before = self.fixture.census(root); original = verifier.comparison_output_error
                        old_publish = verifier.publish_report; active = False; fired = False
                        def publish(values, payload):
                            nonlocal active
                            active = True
                            return old_publish(values, payload)
                        def geometry(values):
                            nonlocal fired
                            result = original(values)
                            if active and not fired:
                                fired = True
                                if link == 'symlink': (output / leaf).symlink_to(root / leaf)
                                else: os.link(root / leaf, output / leaf)
                            return result
                        with patch.object(verifier, 'publish_report', side_effect=publish), \
                             patch.object(verifier, 'comparison_output_error', side_effect=geometry):
                            result = self.call(args)
                        self.assertTrue(fired, 'leaf substitution phase not reached')
                        self.assertEqual(self.fixture.census(root), before)
                        self.assert_bounded(result)

    def test_partial_zero_and_multiple_candidate_blocked_publications_are_also_anchored(self):
        for state in ('partial', 'zero', 'multiple'):
            for leaf in verifier.REPORT_LEAVES:
                for cli in (False, True) if state != 'zero' else (False,):
                    with self.subTest(state=state, leaf=leaf, cli=cli):
                        root, args = self.invocation('options-' + str((state, leaf, cli)), leaf)
                        if state == 'partial': args.comparison_challenger_arm = None
                        elif state == 'zero': args.candidate_run = []
                        else: args.candidate_run += ['unread-second-candidate']
                        output = Path(args.output_dir); before = self.fixture.census(root); active = fired = False
                        old_publish = verifier.publish_report; original = verifier.comparison_output_error
                        def publish(values, payload):
                            nonlocal active
                            active = True
                            return old_publish(values, payload)
                        def geometry(values):
                            nonlocal fired
                            result = original(values)
                            if active and not fired:
                                fired = True; output.symlink_to(root, target_is_directory=True)
                            return result
                        with patch.object(verifier, 'publish_report', side_effect=publish), \
                             patch.object(verifier, 'comparison_output_error', side_effect=geometry), \
                             patch.object(verifier, 'collect_evidence', side_effect=AssertionError('blocked options reached legacy reads')):
                            result = self.call(args, cli)
                        self.assertTrue(fired, 'initially blocked publication phase not reached')
                        self.assertEqual(self.fixture.census(root), before)
                        if cli: self.assertEqual(result, 2)
                        else: self.assert_bounded(result)

    def test_after_geometry_ancestor_symlink_and_native_junction_aliases_are_bounded(self):
        import subprocess
        for kind in ('symlink', 'junction') if os.name == 'nt' else ('symlink',):
            for leaf in verifier.REPORT_LEAVES:
                for blocked in (False, True):
                    for missing in (False, True):
                        for cli in (False, True):
                            with self.subTest(kind=kind, leaf=leaf, blocked=blocked, missing=missing, cli=cli):
                                root, args = self.invocation('ancestor-' + str((kind, leaf, blocked, missing, cli)), leaf, blocked)
                                parent = self.area / (root.name + '-parent'); parent.mkdir()
                                output = parent / root.name; args.output_dir = str(output)
                                if not missing: output.mkdir()
                                before = self.fixture.census(root); fired = active = False
                                old_publish = verifier.publish_report; original = verifier.comparison_output_error
                                def publish(values, payload):
                                    nonlocal active
                                    active = True
                                    return old_publish(values, payload)
                                def geometry(values):
                                    nonlocal fired
                                    result = original(values)
                                    if active and not fired:
                                        fired = True; parent.rename(parent.with_name(parent.name + '-parked'))
                                        if kind == 'symlink': parent.symlink_to(root.parent, target_is_directory=True)
                                        else:
                                            process = subprocess.run(['cmd', '/c', 'mklink', '/J', str(parent), str(root.parent)],
                                                                     capture_output=True)
                                            self.assertEqual(process.returncode, 0, 'native junction setup failed')
                                    return result
                                with patch.object(verifier, 'publish_report', side_effect=publish), \
                                     patch.object(verifier, 'comparison_output_error', side_effect=geometry):
                                    result = self.call(args, cli)
                                self.assertTrue(fired, 'ancestor substitution phase not reached')
                                self.assertEqual(self.fixture.census(root), before)
                                if cli: self.assertEqual(result, 2)
                                else: self.assert_bounded(result)

    def test_short_write_then_error_and_each_replace_error_are_bounded_and_clean_owned_outputs(self):
        for phase in ('short_write_error', 'replace1', 'replace2', 'replace3'):
            for blocked in (False, True):
                with self.subTest(phase=phase, blocked=blocked):
                    root, args = self.invocation('io-' + str((phase, blocked)), blocked=blocked)
                    output = Path(args.output_dir); output.mkdir()
                    for leaf in ('summary.json', 'candidate_verdicts.csv', 'report.md'): (output / leaf).write_text('stale')
                    (output / 'caller').write_text('caller')
                    archive = output / 'archive'; archive.mkdir(); (archive / 'summary.json').write_text('archive')
                    before = self.fixture.census(root); calls = 0
                    original = os.write if phase == 'short_write_error' else verifier.ReportDirectory.replace
                    def fail(*values, **kwargs):
                        nonlocal calls
                        calls += 1
                        if phase == 'short_write_error':
                            if calls == 1: return original(values[0], values[1][:3])
                            raise OSError('private-token')
                        if calls == int(phase[-1]): raise OSError('private-token')
                        return original(*values, **kwargs)
                    owner, attribute = (os, 'write') if phase == 'short_write_error' else (verifier.ReportDirectory, 'replace')
                    with patch.object(owner, attribute, new=fail):
                        result = self.call(args)
                    self.assertGreaterEqual(calls, 2 if phase == 'short_write_error' else int(phase[-1]), 'publication phase not reached')
                    self.assert_bounded(result)
                    self.assertEqual(self.fixture.census(root), before)
                    self.assertEqual((output / 'caller').read_text(), 'caller')
                    self.assertEqual((archive / 'summary.json').read_text(), 'archive')
                    if os.name == 'nt':
                        self.assertFalse(any((output / leaf).exists() for leaf in verifier.REPORT_LEAVES))
                        self.assertFalse(any(p.name.startswith('.ab-report-') for p in output.iterdir()))
                    else:
                        self.assertEqual(result['comparison_admission']['reason'], 'OUTPUT_PUBLICATION_CLEANUP_INCOMPLETE')

    def test_zero_native_write_is_bounded_and_does_not_leave_partial_receipts(self):
        root, args = self.invocation('zero-write')
        before = self.fixture.census(root)
        with patch.object(os, 'write', return_value=0): result = self.call(args)
        self.assert_bounded(result)
        self.assertEqual(self.fixture.census(root), before)

    def test_anchored_directory_and_ancestor_swaps_reach_mkdir_write_and_each_commit(self):
        phases = ('mkdir', 'write1', 'write2', 'write3', 'before1', 'before2', 'before3', 'after1', 'after2')
        for phase in phases:
            for ancestor in (False, True):
                for blocked in (False, True):
                    for cli in (False, True):
                        with self.subTest(phase=phase, ancestor=ancestor, blocked=blocked, cli=cli):
                            root, args = self.invocation('anchored-' + str((phase, ancestor, blocked, cli)), blocked=blocked)
                            parent = self.area / (root.name + '-parent'); parent.mkdir()
                            output = parent / root.name; args.output_dir = str(output)
                            if phase != 'mkdir': output.mkdir()
                            before = self.fixture.census(root); fired = refused = False; calls = 0
                            def swap():
                                nonlocal fired, refused
                                fired = True; source = parent if ancestor or phase == 'mkdir' else output
                                try: source.rename(source.with_name(source.name + '-parked'))
                                except OSError as exc:
                                    self.assertEqual(os.name, 'nt')
                                    self.assertEqual(exc.winerror, 32, 'directory lock did not refuse replacement')
                                    refused = True; return
                                source.symlink_to(root.parent if source == parent else root, target_is_directory=True)
                            if phase == 'mkdir':
                                owner, attribute = os, 'mkdir'; original = os.mkdir
                                def hook(*values, **kwargs):
                                    if not fired and (Path(values[0]) == output if os.name == 'nt' else values[0] == output.name):
                                        swap()
                                    return original(*values, **kwargs)
                            elif phase.startswith('write'):
                                owner, attribute = os, 'write'; original = os.write
                                def hook(*values, **kwargs):
                                    nonlocal calls
                                    calls += 1
                                    if calls == int(phase[-1]): swap()
                                    return original(*values, **kwargs)
                            else:
                                owner, attribute = verifier.ReportDirectory, 'replace'; original = owner.replace
                                def hook(*values, **kwargs):
                                    nonlocal calls
                                    calls += 1
                                    if phase.startswith('before') and calls == int(phase[-1]): swap()
                                    result = original(*values, **kwargs)
                                    if phase.startswith('after') and calls == int(phase[-1]): swap()
                                    return result
                            with patch_publication_phase(owner, attribute, hook): result = self.call(args, cli)
                            self.assertTrue(fired, 'anchored publication phase not reached')
                            self.assertEqual(self.fixture.census(root), before)
                            if refused:
                                if cli: self.assertEqual(result, 2 if blocked else 0)
                                else: self.assertEqual(result['status'], 'blocked_comparison_admission' if blocked else 'review_candidate_ready')
                                for leaf in verifier.REPORT_LEAVES: self.assertTrue((output / leaf).is_file())
                            else:
                                if cli: self.assertEqual(result, 2)
                                else: self.assert_bounded(result)

    def test_publication_phase_hook_inherits_only_saved_capability_and_restores_state(self):
        original = os.mkdir; capabilities = os.supports_dir_fd
        # These registry fixtures test hook metadata on every platform; they do
        # not claim that Windows implements POSIX descriptor-relative mkdir.
        for supported in (False, True):
            for fail in (False, True):
                with self.subTest(supported=supported, fail=fail):
                    fixture_capabilities = capabilities | {original} if supported else capabilities - {original}
                    output = self.area / ('ordinary' if not supported else 'directory with spaces')
                    output = output.with_name(output.name + str(fail))
                    calls = []
                    def hook(*values, **kwargs):
                        calls.append((values, kwargs))
                        return original(*values, **kwargs)
                    with patch.object(os, 'supports_dir_fd', new=fixture_capabilities):
                        try:
                            with patch_publication_phase(os, 'mkdir', hook):
                                self.assertIs(os.mkdir, hook)
                                self.assertEqual(hook in os.supports_dir_fd, supported)
                                self.assertEqual(os.supports_dir_fd, fixture_capabilities | ({hook} if supported else set()))
                                os.mkdir(str(output), mode=0o700)
                                if fail: raise RuntimeError('fixture-only failure')
                        except RuntimeError as exc:
                            self.assertTrue(fail)
                            self.assertEqual(str(exc), 'fixture-only failure')
                        self.assertIs(os.mkdir, original)
                        self.assertIs(os.supports_dir_fd, fixture_capabilities)
                    self.assertIs(os.supports_dir_fd, capabilities)
                    self.assertEqual(calls, [((str(output),), {'mode': 0o700})])
                    self.assertTrue(output.is_dir())

    @unittest.skipUnless(os.name == 'posix', 'actual POSIX capability guard and dir_fd mkdir; Linux CI required')
    def test_posix_mkdir_hook_preserves_guard_and_native_ordinary_and_spaced_paths(self):
        original = os.mkdir; capabilities = os.supports_dir_fd
        self.assertIn(original, capabilities)
        for name in ('ordinary-native', 'native directory with spaces'):
            with self.subTest(name=name):
                output = self.area / name; calls = []
                def hook(*values, **kwargs):
                    calls.append((values, kwargs))
                    self.assertEqual(values, (name,))
                    self.assertIn('dir_fd', kwargs)
                    self.assertIsInstance(kwargs['dir_fd'], int)
                    self.assertEqual(verifier.publication_identity(os.fstat(kwargs['dir_fd'])),
                                     verifier.publication_identity(self.area.stat()))
                    return original(*values, **kwargs)
                with patch_publication_phase(os, 'mkdir', hook):
                    directory = verifier.ReportDirectory(output, create=True)
                    try: directory.guard()
                    finally: directory.close()
                self.assertEqual(len(calls), 1, 'native dir_fd mkdir phase not reached')
                self.assertTrue(output.is_dir())
                self.assertIs(os.mkdir, original)
                self.assertIs(os.supports_dir_fd, capabilities)
        calls = []
        def unsupported(*values, **kwargs):
            calls.append((values, kwargs))
            return original(*values, **kwargs)
        output = self.area / 'unsupported directory with spaces'
        with patch.object(os, 'supports_dir_fd', new=capabilities - {original}):
            with patch_publication_phase(os, 'mkdir', unsupported):
                self.assertNotIn(unsupported, os.supports_dir_fd)
                with self.assertRaises(m.AdmissionError) as raised:
                    verifier.ReportDirectory(output, create=True)
                self.assertEqual(str(raised.exception), 'OUTPUT_PUBLICATION_ANCHOR_UNAVAILABLE')
        self.assertEqual(calls, [])
        self.assertFalse(output.exists())
        self.assertIs(os.mkdir, original)
        self.assertIs(os.supports_dir_fd, capabilities)

    def test_each_late_leaf_alias_preserves_input_and_never_truncates_an_existing_inode(self):
        for leaf in verifier.REPORT_LEAVES:
            for link in ('symlink', 'hardlink'):
                for phase in ('stage_write', 'commit'):
                    for blocked in (False, True):
                        for cli in (False, True):
                            with self.subTest(leaf=leaf, link=link, phase=phase, blocked=blocked, cli=cli):
                                root, args = self.invocation('lateleaf-' + str((leaf, link, phase, blocked, cli)), leaf, blocked)
                                output = Path(args.output_dir); output.mkdir()
                                before = self.fixture.census(root); fired = False
                                def substitute():
                                    nonlocal fired
                                    fired = True
                                    if link == 'symlink': (output / leaf).symlink_to(root / leaf)
                                    else: os.link(root / leaf, output / leaf)
                                if phase == 'stage_write':
                                    owner, attribute = os, 'write'; original = os.write
                                    def hook(*values, **kwargs):
                                        if not fired: substitute()
                                        return original(*values, **kwargs)
                                else:
                                    owner, attribute = verifier.ReportDirectory, 'replace'; original = owner.replace
                                    def hook(*values, **kwargs):
                                        if values[2] == leaf and not fired: substitute()
                                        return original(*values, **kwargs)
                                with patch.object(owner, attribute, new=hook): result = self.call(args, cli)
                                self.assertTrue(fired, 'late leaf substitution phase not reached')
                                self.assertEqual(self.fixture.census(root), before)
                                # POSIX replacement unlinks the local link; Windows
                                # refuses the new occupied name. Neither follows it.
                                if os.name == 'nt' or phase == 'stage_write':
                                    if cli: self.assertEqual(result, 2)
                                    else: self.assert_bounded(result)
                                else:
                                    if cli: self.assertEqual(result, 2 if blocked else 0)
                                    else: self.assertEqual(result['status'], 'blocked_comparison_admission' if blocked else 'review_candidate_ready')

    def test_partial_failure_retains_foreign_temp_occupant_or_native_lock_refuses_the_swap(self):
        for blocked in (False, True):
            root, args = self.invocation('temp-occupant-' + str(blocked), blocked=blocked)
            output = Path(args.output_dir); output.mkdir()
            before = self.fixture.census(root); fired = refused = False; source = None
            original = os.write
            def hook(descriptor, raw):
                nonlocal fired, refused, source
                if not fired:
                    fired = True; source = next(output.glob('.ab-report-*.tmp'))
                    try: source.rename(output / 'parked-original-temp')
                    except OSError as exc:
                        self.assertEqual(os.name, 'nt'); self.assertEqual(exc.winerror, 32)
                        refused = True
                    else: source.write_bytes(b'foreign-temp-occupant')
                    original(descriptor, raw[:3]); raise OSError('private-token')
                return original(descriptor, raw)
            with patch.object(os, 'write', new=hook): result = self.call(args)
            self.assertTrue(fired, 'held temp cleanup phase not reached')
            self.assert_bounded(result); self.assertEqual(self.fixture.census(root), before)
            if refused: self.assertFalse(source.exists())
            else:
                self.assertEqual(source.read_bytes(), b'foreign-temp-occupant')
                self.assertEqual(result['comparison_admission']['reason'], 'OUTPUT_PUBLICATION_CLEANUP_INCOMPLETE')

    @unittest.skipUnless(os.name == 'nt', 'native Windows CREATE_NEW/handle deletion contract')
    def test_checked_leaf_deletion_does_not_retry_against_raced_create_new_occupant(self):
        for leaf in verifier.REPORT_LEAVES:
            for blocked in (False, True):
                for cli in (False, True):
                    with self.subTest(leaf=leaf, blocked=blocked, cli=cli):
                        root, args = self.invocation('create-new-' + str((leaf, blocked, cli)), leaf, blocked)
                        output = Path(args.output_dir); output.mkdir(); (output / leaf).write_bytes(b'old-owned-report')
                        before = self.fixture.census(root); fired = False; calls = 0
                        original = verifier.ReportDirectory.create_exclusive_leaf
                        def hook(directory, name):
                            nonlocal fired, calls
                            if name == leaf:
                                calls += 1
                                if not fired:
                                    fired = True; (output / leaf).write_bytes(b'foreign-final-occupant')
                            return original(directory, name)
                        with patch.object(verifier.ReportDirectory, 'create_exclusive_leaf', new=hook): result = self.call(args, cli)
                        self.assertTrue(fired, 'CREATE_NEW race phase not reached'); self.assertEqual(calls, 1)
                        self.assertEqual((output / leaf).read_bytes(), b'foreign-final-occupant')
                        self.assertEqual(self.fixture.census(root), before)
                        if cli: self.assertEqual(result, 2)
                        else: self.assert_bounded(result)

    def test_summary_is_installed_last_and_retained_prior_summary_is_not_a_new_receipt(self):
        for failure in (0, 1, 2, 3):
            root, args = self.invocation('marker-' + str(failure))
            output = Path(args.output_dir); output.mkdir()
            prior = b'{"status":"retained_previous_invocation"}'
            (output / 'summary.json').write_bytes(prior)
            order = []; original = verifier.ReportDirectory.replace
            def hook(*values, **kwargs):
                order.append(values[2])
                if len(order) == failure: raise OSError('private-token')
                return original(*values, **kwargs)
            with patch.object(verifier.ReportDirectory, 'replace', new=hook): result = self.call(args)
            self.assertEqual(order, list(('candidate_verdicts.csv', 'report.md', 'summary.json')[:failure or 3]))
            if failure:
                self.assert_bounded(result)
                if os.name == 'nt': self.assertFalse((output / 'summary.json').exists())
                else: self.assertEqual((output / 'summary.json').read_bytes(), prior)
            else:
                self.assertEqual(result['status'], 'review_candidate_ready')
                self.assertEqual(json.loads((output / 'summary.json').read_bytes())['status'], result['status'])

    def test_each_stage_and_native_final_write_sync_and_read_error_is_bounded(self):
        phases = [f'stage{n}' for n in (1, 2, 3)]
        if os.name == 'nt': phases += [f'final{n}' for n in (1, 2, 3)]
        for phase in phases:
            operations = ('write', 'fsync', 'invalid_write') + (('read',) if phase.startswith('final') else ())
            for operation in operations:
                for blocked in (False, True):
                    with self.subTest(phase=phase, operation=operation, blocked=blocked):
                        root, args = self.invocation('leaf-io-' + str((phase, operation, blocked)), blocked=blocked)
                        output = Path(args.output_dir); output.mkdir()
                        (output / 'caller').write_bytes(b'caller')
                        before = self.fixture.census(root); descriptors = {}; count = {'stage': 0, 'final': 0}; fired = False
                        original_temp = verifier.ReportDirectory.create_temp
                        original_final = verifier.ReportDirectory.create_exclusive_leaf
                        def temp(directory, name):
                            descriptor = original_temp(directory, name); count['stage'] += 1
                            descriptors[descriptor] = 'stage' + str(count['stage']); return descriptor
                        def final(directory, name):
                            descriptor = original_final(directory, name)
                            if name in verifier.REPORT_LEAVES:
                                count['final'] += 1; descriptors[descriptor] = 'final' + str(count['final'])
                            return descriptor
                        attribute = 'write' if operation == 'invalid_write' else operation
                        original = getattr(os, attribute)
                        def io_hook(descriptor, *values):
                            nonlocal fired
                            matches = descriptors.get(descriptor) == phase
                            # The Windows copy reads the original stage descriptor.
                            if operation == 'read': matches = count['final'] == int(phase[-1])
                            if matches:
                                fired = True
                                if operation == 'invalid_write': return len(values[0]) + 1
                                raise OSError('private-token')
                            return original(descriptor, *values)
                        with patch.object(verifier.ReportDirectory, 'create_temp', new=temp), \
                             patch.object(verifier.ReportDirectory, 'create_exclusive_leaf', new=final), \
                             patch.object(os, attribute, new=io_hook): result = self.call(args)
                        self.assertTrue(fired, 'specific staged/final I/O phase not reached')
                        self.assert_bounded(result); self.assertEqual(self.fixture.census(root), before)
                        self.assertEqual((output / 'caller').read_bytes(), b'caller')
                        self.assertFalse((output / 'summary.json').exists(), 'partial invocation installed a success marker')
                        if os.name == 'nt':
                            self.assertFalse(any((output / leaf).exists() for leaf in verifier.REPORT_LEAVES))
                            self.assertFalse(any(p.name.startswith('.ab-report-') for p in output.iterdir()))
                        else: self.assertEqual(result['comparison_admission']['reason'], 'OUTPUT_PUBLICATION_CLEANUP_INCOMPLETE')

    @unittest.skipUnless(os.name == 'nt', 'native Windows exclusive final handle contract')
    def test_final_handle_denies_leaf_rename_before_each_actual_write_and_cleanup(self):
        for leaf in verifier.REPORT_LEAVES:
            for blocked in (False, True):
                for cli in (False, True):
                    with self.subTest(leaf=leaf, blocked=blocked, cli=cli):
                        root, args = self.invocation('final-lock-' + str((leaf, blocked, cli)), leaf, blocked)
                        output = Path(args.output_dir); before = self.fixture.census(root)
                        target = None; fired = False; original_create = verifier.ReportDirectory.create_exclusive_leaf
                        def create(directory, name):
                            nonlocal target
                            descriptor = original_create(directory, name)
                            if name == leaf: target = descriptor
                            return descriptor
                        original_write = os.write
                        def write(descriptor, raw):
                            nonlocal fired
                            if descriptor == target:
                                fired = True
                                with self.assertRaises(OSError) as captured: (output / leaf).rename(output / 'raced-final')
                                self.assertEqual(captured.exception.winerror, 32)
                                original_write(descriptor, raw[:3]); raise OSError('private-token')
                            return original_write(descriptor, raw)
                        with patch.object(verifier.ReportDirectory, 'create_exclusive_leaf', new=create), \
                             patch.object(os, 'write', new=write): result = self.call(args, cli)
                        self.assertTrue(fired, 'actual final handle write/cleanup phase not reached')
                        self.assertEqual(self.fixture.census(root), before)
                        self.assertFalse((output / 'raced-final').exists())
                        self.assertFalse(any((output / name).exists() for name in verifier.REPORT_LEAVES))
                        self.assertFalse(any(p.name.startswith('.ab-report-') for p in output.iterdir()))
                        if cli: self.assertEqual(result, 2)
                        else: self.assert_bounded(result)

    def test_disjoint_existing_and_missing_outputs_publish_all_three_reports(self):
        for blocked in (False, True):
            for existing in (False, True):
                with self.subTest(blocked=blocked, existing=existing):
                    root, args = self.invocation('positive-' + str((blocked, existing)), blocked=blocked)
                    output = Path(args.output_dir)
                    if existing: output.mkdir(); (output / 'caller').write_text('caller')
                    before = self.fixture.census(root); result = self.call(args)
                    self.assertEqual(self.fixture.census(root), before)
                    self.assertEqual(result['status'], 'blocked_comparison_admission' if blocked else 'review_candidate_ready')
                    for leaf in ('summary.json', 'candidate_verdicts.csv', 'report.md'): self.assertTrue((output / leaf).is_file())
                    if existing: self.assertEqual((output / 'caller').read_text(), 'caller')
                    self.assertFalse(any(p.name.startswith('.ab-report-') for p in output.iterdir()))
                    # Prove native parent/leaf handles were released, rather
                    # than depending on interpreter teardown or fixture GC.
                    output.rename(output.with_name(output.name + '-released'))
                    root.rename(root.with_name(root.name + '-released'))

    def test_legacy_without_options_keeps_existing_path_writer_behavior(self):
        root, args = self.invocation('legacy')
        for name in verifier.COMPARISON_OPTIONS: setattr(args, name, None)
        with patch.object(os, 'write', side_effect=AssertionError('native opt-in writer must not run')):
            result = self.call(args)
        self.assertEqual(result['status'], 'review_candidate_ready')
        self.assertNotIn('comparison_admission', result)

    def test_stdout_failures_do_not_destroy_valid_receipts_or_escape_blocked_api_cli(self):
        for state in ('valid', 'wrong_pin', 'partial', 'unsafe', 'publication_error'):
            for error in (BrokenPipeError, OSError):
                for cli in (False, True):
                    with self.subTest(state=state, error=error.__name__, cli=cli):
                        root, args = self.invocation('stdout-' + str((state, error.__name__, cli)), blocked=state == 'wrong_pin')
                        if state == 'partial': args.comparison_challenger_arm = None
                        elif state == 'unsafe': args.output_dir = str(root)
                        before = self.fixture.census(root)
                        with patch('builtins.print', side_effect=error('private-token')) as telemetry:
                            if state == 'publication_error':
                                with patch.object(os, 'write', side_effect=OSError('private-token')): result = self.call(args, cli)
                            else: result = self.call(args, cli)
                        self.assertTrue(telemetry.called, 'telemetry failure phase not reached')
                        self.assertEqual(self.fixture.census(root), before)
                        if state == 'valid':
                            if cli: self.assertEqual(result, 0)
                            else: self.assertEqual(result['status'], 'review_candidate_ready')
                            output = Path(args.output_dir)
                            for leaf in verifier.REPORT_LEAVES: self.assertTrue((output / leaf).is_file())
                            self.assertEqual(json.loads((output / 'summary.json').read_bytes())['status'], 'review_candidate_ready')
                        else:
                            if cli: self.assertEqual(result, 2)
                            else: self.assert_bounded(result, current_receipt=state in ('wrong_pin', 'partial'))

    def test_actual_cli_closed_stdout_pipe_preserves_success_and_blocked_exit_codes(self):
        for blocked in (False, True):
            root, args = self.invocation('native-stdout-pipe-' + str(blocked), blocked=blocked)
            before = self.fixture.census(root)
            command = [sys.executable] + (['-O'] if sys.flags.optimize else [])
            command += [str(ROOT/'tools/run_ab_result_verifier.py'), '--baseline-run', args.baseline_run,
                        '--candidate-run', args.candidate_run[0], '--output-dir', args.output_dir]
            for name in verifier.COMPARISON_OPTIONS:
                command += ['--' + name.replace('_','-'), getattr(args,name)]
            environment = os.environ.copy(); environment.pop('PYTHONUNBUFFERED',None)
            process = subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=environment)
            process.stdout.close(); process.stdout = None
            _, error = process.communicate(timeout=45)
            self.assertEqual(process.returncode, 2 if blocked else 0, error.decode(errors='replace'))
            self.assertNotIn(b'Exception ignored',error)
            self.assertEqual(self.fixture.census(root),before)
            receipt=json.loads((Path(args.output_dir)/'summary.json').read_bytes())
            self.assertTrue(receipt['current_receipt'])
            self.assertEqual(receipt['status'],'blocked_comparison_admission' if blocked else 'review_candidate_ready')

    def test_closed_and_failed_redirected_stdout_remain_caller_owned(self):
        import contextlib
        import io
        class FailedOutput(io.StringIO):
            def write(self, value): raise OSError('private-token')
        for closed in (False, True):
            for blocked in (False, True):
                root,args=self.invocation('caller-stdout-'+str((closed,blocked)),blocked=blocked)
                before=self.fixture.census(root); stream=io.StringIO() if closed else FailedOutput()
                if closed:stream.close()
                with contextlib.redirect_stdout(stream):result=verifier.run(args)
                self.assertEqual(stream.closed,closed,'caller stdout ownership changed')
                self.assertEqual(result['status'],'blocked_comparison_admission' if blocked else 'review_candidate_ready')
                self.assertTrue(result['current_receipt'])
                self.assertEqual(self.fixture.census(root),before)
                stream.close()

    @unittest.skipUnless(os.name == 'posix', 'actual POSIX dir_fd source substitution; Linux CI required')
    def test_posix_each_source_name_and_same_inode_byte_swap_before_replace_is_rejected(self):
        for leaf in verifier.REPORT_LEAVES:
            for mutation in ('source_name', 'same_inode_bytes'):
                for blocked in (False, True):
                    for cli in (False, True):
                        with self.subTest(leaf=leaf, mutation=mutation, blocked=blocked, cli=cli):
                            root, args = self.invocation('source-swap-' + str((leaf, mutation, blocked, cli)), blocked=blocked)
                            output = Path(args.output_dir); before = self.fixture.census(root)
                            fired = False; foreign = None; original = os.replace
                            def replace(source, destination, **kwargs):
                                nonlocal fired, foreign
                                if destination == leaf and not fired:
                                    fired = True; path = output / source
                                    identity = verifier.publication_identity(path.stat())
                                    raw = path.read_bytes(); foreign = bytes([raw[0] ^ 1]) + raw[1:]
                                    if mutation == 'source_name': path.rename(output / 'parked-original-stage')
                                    path.write_bytes(foreign)
                                    changed = verifier.publication_identity(path.stat())
                                    self.assertEqual(identity == changed, mutation == 'same_inode_bytes')
                                return original(source, destination, **kwargs)
                            with patch.object(os, 'replace', new=replace): result = self.call(args, cli)
                            self.assertTrue(fired, 'source swap after source check and before rename not reached')
                            self.assertEqual((output / leaf).read_bytes(), foreign, 'foreign bytes were deleted or overwritten in cleanup')
                            self.assertEqual(self.fixture.census(root), before)
                            if cli: self.assertEqual(result, 2)
                            else:
                                self.assert_bounded(result)
                                self.assertEqual(result['comparison_admission']['reason'], 'OUTPUT_PUBLICATION_CLEANUP_INCOMPLETE')

    @unittest.skipUnless(os.name == 'nt', 'actual Windows stage handles deny source rename/write')
    def test_native_windows_stage_name_and_same_inode_write_attempts_are_refused(self):
        for leaf in verifier.REPORT_LEAVES:
            for mutation in ('source_name', 'same_inode_bytes'):
                for blocked in (False, True):
                    for cli in (False, True):
                        with self.subTest(leaf=leaf, mutation=mutation, blocked=blocked, cli=cli):
                            root, args = self.invocation('locked-source-' + str((leaf, mutation, blocked, cli)), blocked=blocked)
                            output = Path(args.output_dir); before = self.fixture.census(root); fired = False
                            original = verifier.ReportDirectory.replace
                            def replace(directory, source, destination):
                                nonlocal fired
                                if destination == leaf and not fired:
                                    fired = True; path = output / source
                                    with self.assertRaises(OSError) as captured:
                                        if mutation == 'source_name': path.rename(output / 'parked-original-stage')
                                        else: path.write_bytes(b'foreign-stage-bytes')
                                    if mutation == 'source_name': self.assertEqual(captured.exception.winerror, 32)
                                    else:
                                        # CRT fopen reports EACCES without winerror;
                                        # independently require native sharing denial.
                                        import ctypes
                                        self.assertEqual(captured.exception.errno, 13)
                                        handle = directory.kernel.CreateFileW(str(path), 0x40000000, 7, None, 3, 0x00200000, None)
                                        if handle != ctypes.c_void_p(-1).value: directory.kernel.CloseHandle(handle)
                                        self.assertEqual(handle, ctypes.c_void_p(-1).value)
                                        self.assertEqual(ctypes.get_last_error(), 32, 'native stage write access was not denied')
                                return original(directory, source, destination)
                            with patch.object(verifier.ReportDirectory, 'replace', new=replace): result = self.call(args, cli)
                            self.assertTrue(fired, 'held source-name/content mutation phase not reached')
                            self.assertEqual(self.fixture.census(root), before)
                            if cli: self.assertEqual(result, 2 if blocked else 0)
                            else: self.assertEqual(result['status'], 'blocked_comparison_admission' if blocked else 'review_candidate_ready')
                            self.assertFalse((output / 'parked-original-stage').exists())
                            for name in verifier.REPORT_LEAVES: self.assertTrue((output / name).is_file())

    def test_held_inode_content_verification_detects_same_size_owned_write_mutation(self):
        for leaf in verifier.REPORT_LEAVES:
            for blocked in (False, True):
                for cli in (False, True):
                    with self.subTest(leaf=leaf, blocked=blocked, cli=cli):
                        root, args = self.invocation('content-verify-' + str((leaf, blocked, cli)), blocked=blocked)
                        before = self.fixture.census(root); fired = False
                        original = verifier.ReportDirectory.verify_installed
                        def verify(directory, name, size, digest):
                            nonlocal fired
                            if name == leaf and not fired:
                                fired = True; descriptor = directory.owned_descriptors[name]
                                before_stat = os.fstat(descriptor)
                                os.lseek(descriptor, 0, os.SEEK_SET); byte = os.read(descriptor, 1)
                                os.lseek(descriptor, 0, os.SEEK_SET); os.write(descriptor, bytes([byte[0] ^ 1]))
                                after_stat = os.fstat(descriptor)
                                self.assertEqual(verifier.publication_identity(before_stat), verifier.publication_identity(after_stat))
                                self.assertEqual(before_stat.st_size, after_stat.st_size)
                            return original(directory, name, size, digest)
                        with patch.object(verifier.ReportDirectory, 'verify_installed', new=verify): result = self.call(args, cli)
                        self.assertTrue(fired, 'installed same-inode content check not reached')
                        self.assertEqual(self.fixture.census(root), before)
                        if cli: self.assertEqual(result, 2)
                        else: self.assert_bounded(result)

    @unittest.skipUnless(os.name == 'nt', 'actual Windows post-copy held-temp cleanup')
    def test_each_post_copy_temp_deletion_error_is_bounded_and_cleans_owned_inodes(self):
        for leaf in verifier.REPORT_LEAVES:
            for blocked in (False, True):
                for cli in (False, True):
                    with self.subTest(leaf=leaf, blocked=blocked, cli=cli):
                        root, args = self.invocation('post-copy-delete-' + str((leaf, blocked, cli)), blocked=blocked)
                        output = Path(args.output_dir); before = self.fixture.census(root)
                        active = None; fired = False; original_replace = verifier.ReportDirectory.replace
                        original_unlink = verifier.ReportDirectory.unlink_owned
                        def replace(*values):
                            nonlocal active
                            active = values[2]; return original_replace(*values)
                        def unlink(directory, name):
                            nonlocal fired
                            if active == leaf and name.startswith('.ab-report-') and not fired:
                                fired = True; raise OSError('private-token')
                            return original_unlink(directory, name)
                        with patch.object(verifier.ReportDirectory,'replace',new=replace), \
                             patch.object(verifier.ReportDirectory,'unlink_owned',new=unlink): result = self.call(args,cli)
                        self.assertTrue(fired, 'post-copy cleanup after full final write was not reached')
                        self.assertEqual(self.fixture.census(root),before)
                        self.assertFalse(any((output/name).exists() for name in verifier.REPORT_LEAVES))
                        self.assertFalse(any(p.name.startswith('.ab-report-') for p in output.iterdir()))
                        if cli: self.assertEqual(result,2)
                        else: self.assert_bounded(result)


def suite():
    return unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromTestCase(cls)
                              for cls in (ComparisonPrecheckTests,BoundedResolverTests,ImmutableBundleLifecycleTests,NativeIntegrationTests,AnchoredPublicationTests))

def main():
    return 0 if unittest.TextTestRunner(verbosity=2).run(suite()).wasSuccessful() else 1

if __name__=='__main__':raise SystemExit(main())
