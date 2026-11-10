#!/usr/bin/env python3
"""Fault-injection regressions for durable history; synthetic data is not coverage."""
import copy
from datetime import datetime,timezone
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.long_history_lake import Lake,LocalTransport,SourceHTTPError,sec_rows,fact_coverage,issuer_queue,encoded,digest,materialize,wb_rows,PREFIX


def source():
    base=dict(start='2016-01-01',end='2016-12-31',filed='2017-02-01',accn='0000000001-17-000001',form='10-K',val=100)
    amendment=dict(base,filed='2018-01-01',accn='0000000001-18-000001',form='10-K/A',val=90)
    return dict(cik=1,facts={'us-gaap':{'Revenues':{'units':{'USD':[base,amendment]}}}})


class HistoryTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name); self.t=LocalTransport(self.root/'remote')
        self.lake=Lake(self.t,self.root/'first')

    def put(self,lake=None,value=100):
        lake=lake or self.lake
        lake.dataset('sec/0000000001',[b'original'],[dict(end='2016-12-31',filed='2017-02-01',value=value,concept='Revenue',unit='USD')],
            dict(evidence='SEC_FILED_DATE_CURRENT_ARCHIVE_NOT_CERTIFIED_PIT',rows=1))


    def test_phase_progress_is_paired_bounded_and_uses_monotonic_elapsed(self):
        import io
        from contextlib import redirect_stdout
        from tools.long_history_lake import _history_phase
        stream=io.StringIO()
        with patch('tools.long_history_lake.time.monotonic_ns',side_effect=[1000000000,1025000000]), redirect_stdout(stream):
            with _history_phase('COMMIT_INVENTORY') as counts:
                counts['commits']=3
        events=[json.loads(line.split(' ',1)[1]) for line in stream.getvalue().splitlines()]
        self.assertEqual([e['state'] for e in events],['BEGIN','END'])
        self.assertEqual(events[0]['phase_id'],events[1]['phase_id'])
        self.assertEqual(events[1]['elapsed_ms'],25)
        self.assertEqual(events[1]['commits'],3)

    def test_phase_refuses_unknown_fields_and_never_prints_secret_exception(self):
        import io
        from contextlib import redirect_stdout
        from tools.long_history_lake import _history_phase
        secret='https://private.invalid/object?token=PUBLIC_SENTINEL_SECRET'
        stream=io.StringIO()
        failure=KeyboardInterrupt(secret)
        with redirect_stdout(stream):
            with self.assertRaises(KeyboardInterrupt) as caught:
                with _history_phase('STUDY'):
                    raise failure
            self.assertIs(caught.exception,failure)
            for kwargs in ({'stage':secret},{'stage':'STUDY','remote':secret},
                           {'stage':'STUDY','rows':True},{'stage':'STUDY','commit_sha256':secret}):
                entered=False
                with _history_phase(**kwargs):
                    entered=True
                self.assertTrue(entered, 'telemetry is not an authorization gate')
        self.assertNotIn(secret,stream.getvalue())
        events=[json.loads(line.split(' ',1)[1]) for line in stream.getvalue().splitlines()]
        self.assertEqual([e['state'] for e in events],['BEGIN','ERROR'])

    def test_phase_after_commit_write_is_not_postcommit_or_execution_success(self):
        import io
        from contextlib import redirect_stdout
        stream=io.StringIO()
        self.put()
        real_write=self.t.write
        def write(path,raw):
            real_write(path,raw)
            if '/commits/' in path:
                self.t.read=lambda name: (_ for _ in ()).throw(OSError('PUBLIC_SENTINEL_SECRET'))
        with patch.object(self.t,'write',side_effect=write),redirect_stdout(stream):
            with self.assertRaisesRegex(OSError,'PUBLIC_SENTINEL_SECRET'):
                self.lake.publish('interrupted',{})
        events=[json.loads(line.split(' ',1)[1]) for line in stream.getvalue().splitlines()
                if line.startswith('LONG_HISTORY_PHASE ')]
        pairs=[(e['stage'],e['state']) for e in events]
        self.assertIn(('COMMIT_WRITE','END'),pairs)
        self.assertIn(('POST_COMMIT_RESTORE','ERROR'),pairs)
        self.assertNotIn(('POST_COMMIT_RESTORE','END'),pairs)
        self.assertEqual(len(self.t.names(PREFIX+'/commits')),1)
        self.assertEqual(self.t.names(PREFIX+'/executions'),[])
        self.assertNotIn('PUBLIC_SENTINEL_SECRET',stream.getvalue())

    def test_phase_failure_to_emit_error_keeps_original_operation_failure(self):
        from tools.long_history_lake import _history_phase
        failure=ValueError('original_failure')
        with patch('builtins.print',side_effect=[None,OSError('PUBLIC_SENTINEL_SECRET')]):
            with self.assertRaises(ValueError) as caught:
                with _history_phase('STUDY'):
                    raise failure
        self.assertIs(caught.exception,failure)


    def test_phase_sink_failures_preserve_body_result_and_original_failure(self):
        from tools.long_history_lake import _history_phase
        for state in ('BEGIN','END','ERROR'):
            for error in (ValueError,TypeError,RuntimeError,BrokenPipeError):
                with self.subTest(state=state,error=error):
                    entered=[]
                    original=ValueError('operation_failure')
                    def sink(line,*args,**kwargs):
                        if line.startswith('LONG_HISTORY_PHASE ') and json.loads(line.split(' ',1)[1])['state']==state:
                            raise error('PUBLIC_SENTINEL_SECRET')
                    with patch('builtins.print',side_effect=sink):
                        if state=='ERROR':
                            with self.assertRaises(ValueError) as caught:
                                with _history_phase('STUDY'):
                                    entered.append(1)
                                    raise original
                            self.assertIs(caught.exception,original)
                        else:
                            with _history_phase('STUDY'):
                                entered.append(1)
                    self.assertEqual(entered,[1])

    def test_phase_build_and_serialization_failure_remain_nonblocking(self):
        import io
        from contextlib import redirect_stdout
        from tools.long_history_lake import _history_phase
        for target in ('json.dumps','time.monotonic_ns'):
            stream=io.StringIO()
            with self.subTest(target=target),redirect_stdout(stream), \
                 patch('tools.long_history_lake.'+target,side_effect=ValueError('PUBLIC_SENTINEL_SECRET')):
                entered=False
                with _history_phase('STUDY'):
                    entered=True
                self.assertTrue(entered)
            self.assertNotIn('PUBLIC_SENTINEL_SECRET',stream.getvalue())

    def test_phase_cancellation_and_deadline_during_emit_propagate(self):
        from tools.long_history_lake import _history_phase
        from tools.twelve_private_capture import Refused
        for state in ('BEGIN','END','ERROR'):
            for kind in (KeyboardInterrupt,SystemExit,GeneratorExit,TimeoutError,InterruptedError,Refused):
                with self.subTest(state=state,kind=kind):
                    failure=kind('CAMPAIGN_DEADLINE' if kind is Refused else 'PUBLIC_CANCEL_SENTINEL')
                    original=ValueError('operation_failure')
                    entered=[]
                    def sink(line,*args,**kwargs):
                        if line.startswith('LONG_HISTORY_PHASE ') and json.loads(line.split(' ',1)[1])['state']==state:
                            raise failure
                    with patch('builtins.print',side_effect=sink):
                        with self.assertRaises(BaseException) as caught:
                            with _history_phase('STUDY'):
                                entered.append(1)
                                if state=='ERROR':
                                    raise original
                    self.assertIs(caught.exception,failure)
                    self.assertEqual(entered,[] if state=='BEGIN' else [1])
                    if state=='ERROR':
                        self.assertIs(failure.__context__,original)

    def test_phase_commit_end_sink_failure_still_runs_postcommit_verification(self):
        import io
        from contextlib import redirect_stdout
        self.put()
        output=io.StringIO()
        real_print=print
        def sink(line,*args,**kwargs):
            if isinstance(line,str) and line.startswith('LONG_HISTORY_PHASE '):
                event=json.loads(line.split(' ',1)[1])
                if event['stage']=='COMMIT_WRITE' and event['state']=='END':
                    raise BrokenPipeError('PUBLIC_SENTINEL_SECRET')
            real_print(line,*args,**kwargs)
        with redirect_stdout(output),patch('builtins.print',side_effect=sink), \
             patch.object(self.lake,'restore_catalog',wraps=self.lake.restore_catalog) as restored:
            result=self.lake.publish('one',{})
        self.assertEqual(restored.call_count,3)
        self.assertEqual(result['commit_sha256'],self.lake.restore_catalog()[0])
        self.assertEqual(self.t.names(PREFIX+'/executions'),[])
        self.assertNotIn('PUBLIC_SENTINEL_SECRET',output.getvalue())
        events=[json.loads(line.split(' ',1)[1]) for line in output.getvalue().splitlines()
                if line.startswith('LONG_HISTORY_PHASE ')]
        self.assertIn(('POST_COMMIT_RESTORE','END'),[(e['stage'],e['state']) for e in events])

    @unittest.skipUnless(hasattr(__import__('signal'),'setitimer'),'POSIX timer required')
    def test_phase_real_posix_deadline_interrupts_logger_before_body(self):
        import signal
        import time
        from tools.long_history_lake import _history_phase
        from tools.twelve_private_capture import Refused
        self.assertEqual(signal.getitimer(signal.ITIMER_REAL)[0],0)
        previous=signal.getsignal(signal.SIGALRM)
        failure=Refused('CAMPAIGN_DEADLINE')
        entered=[]
        sink_entered=[]
        def deadline(*unused):
            raise failure
        def sink(line,*args,**kwargs):
            sink_entered.append(True)
            signal.setitimer(signal.ITIMER_REAL,0.01)
            time.sleep(1)
            self.fail('actual POSIX deadline did not interrupt the sink')
        try:
            signal.signal(signal.SIGALRM,deadline)
            with patch('builtins.print',side_effect=sink):
                with self.assertRaises(Refused) as caught:
                    with _history_phase('STUDY'):
                        entered.append(True)
            self.assertIs(caught.exception,failure)
            self.assertEqual(entered,[])
            self.assertEqual(sink_entered,[True])
        finally:
            signal.setitimer(signal.ITIMER_REAL,0)
            signal.signal(signal.SIGALRM,previous)
        self.assertEqual(signal.getitimer(signal.ITIMER_REAL)[0],0)
        self.assertEqual(signal.getsignal(signal.SIGALRM),previous)

    def phase_main_probe(self,stage=None,state='BEGIN',failure=None,study_failure=None,
                         real_signal=False):
        """Run real main/publication against synthetic local bytes only."""
        import io
        import signal
        import time
        from contextlib import redirect_stdout
        from datetime import date as RealDate
        from tools import long_history_lake as history
        local=tempfile.TemporaryDirectory(dir=self.root)
        self.addCleanup(local.cleanup)
        root=Path(local.name)
        class TraceTransport(LocalTransport):
            def __init__(self,path):
                super().__init__(path)
                self.trace=[]
            def path(self,suffix):
                return suffix
            def call(self,verb,path):
                if verb!='mkdir':
                    raise AssertionError('unexpected synthetic transport verb')
                (self.root/path).mkdir(parents=True,exist_ok=True)
            def read(self,path):
                raw=super().read(path)
                self.trace.append(('READ',path,len(raw),digest(raw)))
                return raw
            def write(self,path,raw):
                super().write(path,raw)
                self.trace.append(('WRITE',path,len(raw),digest(raw)))
        transport=TraceTransport(root/'remote')
        class FixedDate(RealDate):
            @classmethod
            def today(cls):
                return cls(2026,10,28)
        def collect(lake,*unused):
            lake.dataset('current/SYNTHETIC',[b'local fixture'],
                [dict(observation_date='2026-10-27',value=1,series='SYNTHETIC')],
                dict(evidence='SYNTHETIC_RESEARCH_NOT_PIT',rows=1))
        def study(*unused):
            if study_failure is not None:
                raise study_failure
            return dict(tests_declared=1),dict(eligible_for_selector=False)
        output=io.StringIO()
        real_print=print
        triggered=[]
        def sink(line,*args,**kwargs):
            if isinstance(line,str) and line.startswith('LONG_HISTORY_PHASE '):
                event=json.loads(line.split(' ',1)[1])
                if event['stage']==stage and event['state']==state and not triggered:
                    triggered.append(True)
                    if real_signal:
                        signal.setitimer(signal.ITIMER_REAL,0.01)
                        time.sleep(1)
                        raise AssertionError('real POSIX signal did not reach main')
                    raise failure
            real_print(line,*args,**kwargs)
        previous=None
        if real_signal:
            self.assertEqual(signal.getitimer(signal.ITIMER_REAL)[0],0)
            previous=signal.getsignal(signal.SIGALRM)
            def interrupt(*unused):
                raise failure
            signal.signal(signal.SIGALRM,interrupt)
        result=None; error=None
        argv=['long_history_lake','--remote','SYNTHETIC_LOCAL_ONLY','--workspace',str(root/'work'),
              '--cohort',str(root/'unused-cohort'),'--run-id','synthetic-main',
              '--report-dir',str(root/'reports')]
        try:
            with redirect_stdout(output),patch('builtins.print',side_effect=sink), \
                 patch.object(history,'RcloneTransport',return_value=transport), \
                 patch.object(history,'collect_macros',side_effect=collect), \
                 patch.object(history,'collect_financials',return_value=None), \
                 patch.object(history,'registry',return_value={'series':[]}), \
                 patch.object(history,'analyze_restored',side_effect=study), \
                 patch.object(history,'utc_now',return_value='2026-10-28T20:00:00+00:00'), \
                 patch.object(history,'date',FixedDate), \
                 patch.dict('os.environ',{'GITHUB_SHA':'1'*40}),patch.object(sys,'argv',argv):
                try:
                    result=history.main()
                except BaseException as exc:
                    error=exc
        finally:
            if real_signal:
                signal.setitimer(signal.ITIMER_REAL,0)
                signal.signal(signal.SIGALRM,previous)
                self.assertEqual(signal.getitimer(signal.ITIMER_REAL)[0],0)
                self.assertEqual(signal.getsignal(signal.SIGALRM),previous)
        executions=transport.names(PREFIX+'/executions')
        return dict(result=result,error=error,triggered=triggered,trace=transport.trace,
            commits=len(transport.names(PREFIX+'/commits')),
            report_writes=sum(e[0]=='WRITE' and '/reports/' in e[1] for e in transport.trace),
            execution_writes=len(executions),output=output.getvalue(),
            receipt=json.loads(transport.read(PREFIX+'/executions/'+executions[0])) if executions else None)

    def test_main_phase_cancellation_never_publishes_reports_or_execution(self):
        from tools.twelve_private_capture import Refused
        for stage in ('STUDY','LOCAL_STUDY_REPORTS'):
            for state in ('BEGIN','END'):
                for kind in (Refused,TimeoutError,InterruptedError):
                    with self.subTest(stage=stage,state=state,kind=kind):
                        failure=kind('CAMPAIGN_DEADLINE')
                        result=self.phase_main_probe(stage,state,failure)
                        self.assertIs(result['error'],failure)
                        self.assertEqual(result['triggered'],[True])
                        self.assertEqual(result['commits'],1)
                        self.assertEqual(result['report_writes'],0)
                        self.assertEqual(result['execution_writes'],0)

    def test_main_study_body_deadline_also_preserves_original_exception(self):
        from tools.twelve_private_capture import Refused
        for kind in (Refused,TimeoutError,InterruptedError):
            with self.subTest(kind=kind):
                failure=kind('CAMPAIGN_DEADLINE')
                result=self.phase_main_probe(study_failure=failure)
                self.assertIs(result['error'],failure)
                self.assertEqual(result['report_writes'],0)
                self.assertEqual(result['execution_writes'],0)

    def test_main_ordinary_study_failure_keeps_partial_receipt_behavior(self):
        for kind in (ValueError,KeyError,TypeError,OSError):
            with self.subTest(kind=kind):
                result=self.phase_main_probe(study_failure=kind('synthetic_study_blocked'))
                self.assertIsNone(result['error'])
                self.assertEqual(result['result'],2)
                self.assertEqual(result['report_writes'],1)
                self.assertEqual(result['execution_writes'],1)
                self.assertFalse(result['receipt']['study_recomputed_from_drive'])
                self.assertFalse(result['receipt']['eligible_for_selector'])

    def test_main_ordinary_logger_failure_preserves_normal_publication_io(self):
        baseline=self.phase_main_probe()
        self.assertIsNone(baseline['error'])
        self.assertEqual(baseline['result'],0)
        for stage in ('STUDY','LOCAL_STUDY_REPORTS'):
            for state in ('BEGIN','END'):
                for kind in (ValueError,BrokenPipeError):
                    with self.subTest(stage=stage,state=state,kind=kind):
                        result=self.phase_main_probe(stage,state,kind('PUBLIC_PRIVATE_SENTINEL'))
                        self.assertIsNone(result['error'])
                        self.assertEqual(result['result'],0)
                        self.assertEqual(result['trace'],baseline['trace'])
                        self.assertNotIn('PUBLIC_PRIVATE_SENTINEL',result['output'])

    @unittest.skipUnless(hasattr(__import__('signal'),'setitimer'),'POSIX timer required')
    def test_main_real_posix_phase_deadline_stops_before_report_publication(self):
        from tools.twelve_private_capture import Refused
        for stage in ('STUDY','LOCAL_STUDY_REPORTS'):
            for kind in (Refused,TimeoutError,InterruptedError):
                with self.subTest(stage=stage,kind=kind):
                    failure=kind('CAMPAIGN_DEADLINE')
                    result=self.phase_main_probe(stage,'BEGIN',failure,real_signal=True)
                    self.assertIs(result['error'],failure)
                    self.assertEqual(result['triggered'],[True])
                    self.assertEqual(result['commits'],1)
                    self.assertEqual(result['report_writes'],0)
                    self.assertEqual(result['execution_writes'],0)

    def test_a4_missing_four_flow_through_existing_lake_without_alias_or_history_rewrite(self):
        from tools.long_history_lake import collect_macros, registry
        wanted = {'BAMLC0A0CM', 'DGS3MO', 'WDTGAL', 'RRPTSYD'}
        specs = [row for row in registry()['series'] if row['id'] in wanted]
        self.assertEqual(len(specs), 4)
        self.put(); first = self.lake.publish('before-four', {})
        next_lake = Lake(self.t, self.root/'with-four')
        calls = []
        def held(sid, start, through, mode):
            calls.append((sid, mode))
            return ([('observation_date,'+sid+'\n2026-10-21,1.25\n').encode()],
                    '2026-10-27T07:00:00+00:00')
        with patch('tools.long_history_lake.registry', return_value={'series': specs}), \
             patch('tools.long_history_lake.WB_INDICATORS', ()), \
             patch('tools.long_history_lake.fetch_fred_retry', side_effect=held):
            collect_macros(next_lake, '2026-10-01', '2026-10-26')
        self.assertEqual(set(calls), {(sid, 'current') for sid in wanted})
        for spec in specs:
            entry = next_lake.catalog['datasets']['current/'+spec['id']]
            self.assertEqual(entry['unit'], spec['unit'])
            self.assertEqual(entry['frequency'], spec['frequency'])
            self.assertEqual(entry['evidence'], 'current_only')
            self.assertEqual(entry['first_available_at'], '2026-10-27T07:00:00+00:00')
        next_lake.publish('after-four', {})
        restored = Lake(self.t, self.root/'read-four')
        for sid in wanted:
            self.assertEqual(restored.get_records('current/'+sid)[0]['value'], 1.25)
        original = json.loads(restored.read_hash('catalogs', first['catalog_sha256']))
        self.assertEqual(set(original['datasets']), {'sec/0000000001'})
        self.assertEqual(restored.get_records('sec/0000000001')[0]['value'], 100)

    def test_roundtrip_and_version_preservation(self):
        self.put(); first=self.lake.publish('one',{})
        next_lake=Lake(self.t,self.root/'second'); self.put(next_lake,90)
        second=next_lake.publish('two',{})
        self.assertNotEqual(first['catalog_sha256'],second['catalog_sha256'])
        self.assertEqual(next_lake.get_records('sec/0000000001')[0]['value'],90)
        old=json.loads(next_lake.read_hash('catalogs',first['catalog_sha256']))
        self.assertIn(old['datasets']['sec/0000000001']['normalized'],next_lake.catalog['locations'])
        self.assertFalse(second['remote_verified'])

    def test_unchanged_objects_not_uploaded_again(self):
        self.put(); self.lake.publish('one',{})
        after=Lake(self.t,self.root/'second'); self.put(after)
        self.assertFalse(after.pending)
        self.assertEqual(after.publish('two',{})['new_packs'],0)

    def execution(self,publication,**changes):
        quality=encoded(dict(schema='long-history-quality-v1',status='PARTIAL',eligible_for_selector=False))
        quality_sha=digest(quality)
        self.t.write(f'{PREFIX}/reports/{quality_sha}',quality)
        receipt=dict(schema='long-history-execution-v1',run_id='one',
            commit_sha256=publication['commit_sha256'],catalog_sha256=publication['catalog_sha256'],
            reports={'quality.json':quality_sha},consumer_rows=1,
            study_recomputed_from_drive=False,quality_status='PARTIAL',eligible_for_selector=False)
        receipt.update(changes)
        raw=encoded(receipt); sha=digest(raw)
        self.t.write(f'{PREFIX}/executions/{sha}',raw)
        return sha,quality_sha

    def test_storage_only_commit_cannot_supply_shared_execution(self):
        self.put(); self.lake.publish('one',{})
        reader=Lake(self.t,self.root/'reader')
        with self.assertRaisesRegex(ValueError,'execution_receipt_missing_or_ambiguous'):
            reader.verified_execution()

    def finalization_source(self):
        from tools import long_history_lake as history
        self.lake.dataset('current/UNRATE',[b'original-current-source'],
            [dict(series='UNRATE',observation_date='2026-09-01',value=4.2,
                  evidence='current_only',published_at=None,vintage_date=None)],
            dict(series='UNRATE',evidence='current_only',rows=1,
                 retrieved_at='2026-11-07T00:00:00+00:00',latest='2026-09-01'))
        config=dict(macro_start='1996-01-01',through='2026-11-07')
        with patch.dict('os.environ',{'GITHUB_SHA':'a'*40}):
            return self.lake.publish('history-100-1',config)

    def run_finalization(self, source_result, name='finalize', *, study=None, pins=None):
        import io
        from contextlib import redirect_stdout
        from tools import long_history_lake as history
        pins=pins or (source_result['commit_sha256'],source_result['catalog_sha256'],'a'*40)
        workspace=self.root/name
        reports=workspace/'reports'
        argv=['long_history_lake','--remote','SYNTHETIC_LOCAL_ONLY','--workspace',str(workspace/'read'),
              '--cohort',str(workspace/'missing-cohort'),'--run-id','history-200-1',
              '--report-dir',str(reports),'--finalize-commit-sha256',pins[0],
              '--finalize-catalog-sha256',pins[1],'--source-head-sha',pins[2]]
        quality=dict(schema='long-history-quality-v1',status='COLLECTED_NOT_PIT_CERTIFIED',
                     eligible_for_selector=False,financial_issuers=0,financial_fact_rows=0)
        study=study or (lambda *a: (dict(tests_declared=1),dict(eligible_for_selector=False)))
        output=io.StringIO()
        with redirect_stdout(output),patch.object(sys,'argv',argv), \
             patch.object(history,'RcloneTransport',return_value=self.t), \
             patch.object(self.t,'call',create=True),patch.object(self.t,'path',side_effect=lambda x:x,create=True), \
             patch.object(history,'diagnostics',return_value=quality), \
             patch.object(history,'analyze_restored',side_effect=study) as analyzed, \
             patch.object(history,'collect_macros',side_effect=AssertionError('collection forbidden')) as macros, \
             patch.object(history,'collect_financials',side_effect=AssertionError('collection forbidden')) as financials, \
             patch.object(history.Lake,'publish',side_effect=AssertionError('new commit forbidden')), \
             patch.dict('os.environ',{'GITHUB_SHA':'b'*40,'GITHUB_RUN_ID':'200','GITHUB_RUN_ATTEMPT':'1'}):
            result=history.main()
        macros.assert_not_called();financials.assert_not_called()
        return result,reports,analyzed.call_count,output.getvalue()

    def test_finalization_pins_are_all_or_none_before_source_access(self):
        from tools import long_history_lake as history
        self.assertFalse(history.finalization_mode('','',''))
        self.assertTrue(history.finalization_mode('a'*64,'b'*64,'c'*40))
        for pins in (('a'*64,'',''),('','b'*64,''),('','','c'*40),
                     ('A'*64,'b'*64,'c'*40),('a'*64,'b'*63,'c'*40),
                     ('a'*64,'b'*64,'private-secret')):
            with self.subTest(pins=pins),self.assertRaisesRegex(ValueError,'^finalization_pins_required$'):
                history.finalization_mode(*pins)
        argv=['history','--remote','unused','--workspace',str(self.root/'unused'),
              '--cohort','unused','--run-id','history-200-1','--report-dir',str(self.root/'reports'),
              '--source-head-sha','c'*40]
        with patch.object(sys,'argv',argv),patch.object(history,'RcloneTransport') as transport:
            with self.assertRaisesRegex(ValueError,'^finalization_pins_required$'):
                history.main()
            transport.assert_not_called()

    def test_finalization_reads_existing_generation_and_records_separate_actual_runner(self):
        source_result=self.finalization_source()
        before_commits=self.t.names(PREFIX+'/commits')
        before_packs={n:self.t.read(PREFIX+'/packs/'+n) for n in self.t.names(PREFIX+'/packs')}
        result,reports,studies,output=self.run_finalization(source_result)
        self.assertEqual(result,0);self.assertEqual(studies,1)
        self.assertEqual(self.t.names(PREFIX+'/commits'),before_commits)
        self.assertEqual({n:self.t.read(PREFIX+'/packs/'+n) for n in before_packs},before_packs)
        readback=Lake(self.t,self.root/'finalized-readback').verified_execution()
        self.assertEqual(readback['run_id'],'history-100-1')
        self.assertTrue(readback['study_recomputed_from_drive'])
        self.assertEqual(readback['consumer_rows'],1)
        self.assertEqual(readback['recovery']['source_head_sha'],'a'*40)
        self.assertEqual(readback['recovery']['finalizer_head_sha'],'b'*40)
        self.assertEqual(readback['recovery']['finalization_run_id'],'history-200-1')
        self.assertEqual(readback['recovery']['provider_requests_executed'],0)
        self.assertEqual(readback['recovery']['new_data_commits'],0)
        self.assertFalse(readback['eligible_for_selector'])
        publication=json.loads((reports/'publication.json').read_bytes())
        self.assertEqual(publication['execution_receipt_sha256'],readback['execution_receipt_sha256'])
        self.assertIn('FINALIZATION_RECHECK',output)
        self.assertNotIn('MACRO_COLLECTION',output)

    def test_finalization_repeat_reuses_one_receipt_and_retains_existing_identity(self):
        source_result=self.finalization_source()
        self.run_finalization(source_result)
        receipts=self.t.names(PREFIX+'/executions')
        reports=self.t.names(PREFIX+'/reports')
        result,out,studies,_=self.run_finalization(source_result,'repeat')
        self.assertEqual((result,studies),(0,0))
        self.assertEqual(self.t.names(PREFIX+'/executions'),receipts)
        self.assertEqual(self.t.names(PREFIX+'/reports'),reports)
        self.assertEqual(json.loads((out/'publication.json').read_bytes())['status'],'ALREADY_FINALIZED')

    def test_finalization_wrong_generation_catalog_source_code_or_corrupt_pack_stops(self):
        source_result=self.finalization_source()
        good=(source_result['commit_sha256'],source_result['catalog_sha256'],'a'*40)
        for offset,pins in enumerate((('c'*64,good[1],good[2]),(good[0],'d'*64,good[2]),(good[0],good[1],'e'*40))):
            with self.subTest(pins=pins),self.assertRaisesRegex(ValueError,'finalization_.*mismatch'):
                self.run_finalization(source_result,'mismatch-'+str(offset),pins=pins)
        pack=self.t.names(PREFIX+'/packs')[0]
        self.t.read=lambda name: b'corrupt' if name==PREFIX+'/packs/'+pack else self.t.__class__.read(self.t,name)
        with self.assertRaisesRegex(ValueError,'remote_hash'):
            self.run_finalization(source_result,'corrupt')
        self.assertEqual(self.t.names(PREFIX+'/executions'),[])
        self.assertEqual(self.t.names(PREFIX+'/reports'),[])

    def test_finalization_study_failure_or_cancellation_never_publishes_execution(self):
        from tools.twelve_private_capture import Refused
        source_result=self.finalization_source()
        for offset,failure in enumerate((ValueError('PUBLIC_PRIVATE_SENTINEL'),Refused('CAMPAIGN_DEADLINE'),
                                         TimeoutError('CAMPAIGN_DEADLINE'),InterruptedError('CAMPAIGN_DEADLINE'))):
            def study(*unused):raise failure
            with self.subTest(kind=type(failure)),self.assertRaises(ValueError if type(failure) is ValueError else type(failure)):
                self.run_finalization(source_result,'study-'+str(offset),study=study)
            self.assertEqual(self.t.names(PREFIX+'/executions'),[])
            self.assertEqual(self.t.names(PREFIX+'/reports'),[])

    def test_finalization_recheck_refuses_another_writer_before_reports(self):
        from tools import long_history_lake as history
        source_result=self.finalization_source()
        publish=history.Lake.publish
        def study(*unused):
            other=history.Lake(self.t,self.root/'other-writer')
            other.dataset('current/OTHER',[b'other'],[dict(value=1)],dict(evidence='current_only',rows=1))
            publish(other,'history-300-1',dict(macro_start='1996-01-01',through='2026-11-07'))
            return dict(tests_declared=1),dict(eligible_for_selector=False)
        with self.assertRaisesRegex(ValueError,'finalization_head_changed'):
            self.run_finalization(source_result,study=study)
        self.assertEqual(self.t.names(PREFIX+'/executions'),[])
        self.assertEqual(self.t.names(PREFIX+'/reports'),[])

    def test_finalization_ambiguous_execution_is_never_missing(self):
        source_result=self.finalization_source()
        self.run_finalization(source_result)
        name=self.t.names(PREFIX+'/executions')[0]
        duplicate=json.loads(self.t.read(PREFIX+'/executions/'+name));duplicate['created_at']='2026-11-07T12:00:00Z'
        raw=encoded(duplicate);self.t.write(PREFIX+'/executions/'+digest(raw),raw)
        with self.assertRaisesRegex(ValueError,'execution_receipt_missing_or_ambiguous'):
            self.run_finalization(source_result,'ambiguous')
        self.assertEqual(len(self.t.names(PREFIX+'/executions')),2)

    def test_finalization_workflow_uses_existing_serial_writer_and_omits_collection_credentials(self):
        import yaml
        workflow=yaml.safe_load((ROOT/'.github/workflows/long_history_research.yml').read_text())
        job=workflow['jobs']['history'];self.assertEqual(job['concurrency']['group'],'durable-long-history-single-writer')
        self.assertEqual(job['timeout-minutes'],120)
        steps=job['steps'];guard=next(s for s in steps if s.get('name')=='Validate pinned finalization inputs before Source access')
        configure=next(s for s in steps if s.get('name')=='Configure isolated history namespace')
        self.assertLess(steps.index(guard),steps.index(configure))
        finalize=next(s for s in steps if s.get('name')=='Finalize one pinned stored generation without collection')
        self.assertEqual(finalize['if'],"${{ inputs.finalize_commit_sha256 != '' }}")
        self.assertNotIn('FRED_API_KEY',finalize.get('env',{}))
        self.assertIn('--source-head-sha',finalize['run'])
        for step in steps:
            if step.get('name')=='Restore durable cohort if already archived':
                self.assertEqual(step['if'],'${{ !inputs.finalize_commit_sha256 && !inputs.scoped_alfred_request_json }}')
            if step.get('name')=='Collect full history, persist changes, verify clean consumption':
                self.assertEqual(step['if'],'${{ !inputs.finalize_commit_sha256 }}')

    def test_execution_requires_matching_catalog_and_latest_commit(self):
        self.put(); published=self.lake.publish('one',{})
        self.execution(published,catalog_sha256='0'*64)
        reader=Lake(self.t,self.root/'reader')
        with self.assertRaisesRegex(ValueError,'execution_catalog_mismatch'):
            reader.verified_execution()
        other=Lake(self.t,self.root/'next'); self.put(other,90); other.publish('two',{})
        reader=Lake(self.t,self.root/'latest')
        with self.assertRaisesRegex(ValueError,'execution_receipt_missing_or_ambiguous'):
            reader.verified_execution()

    def test_execution_exposes_partial_and_checks_remote_receipt_and_reports(self):
        self.put(); published=self.lake.publish('one',{})
        sha,quality_sha=self.execution(published)
        reader=Lake(self.t,self.root/'reader')
        receipt=reader.verified_execution()
        self.assertEqual(receipt['execution_receipt_sha256'],sha)
        self.assertEqual(receipt['quality_status'],'PARTIAL')
        self.assertFalse(receipt['study_recomputed_from_drive'])
        report_path=self.root/'remote'/PREFIX/'reports'/quality_sha
        original=report_path.read_bytes(); report_path.write_bytes(b'corrupt')
        with self.assertRaisesRegex(ValueError,'remote_hash'): reader.verified_execution()
        report_path.write_bytes(original)
        (self.root/'remote'/PREFIX/'executions'/sha).write_bytes(b'corrupt')
        with self.assertRaisesRegex(ValueError,'remote_hash'): reader.verified_execution()

    def test_stale_writer_cannot_advance(self):
        other=Lake(self.t,self.root/'second')
        self.put(); self.lake.publish('one',{})
        self.put(other)
        with self.assertRaisesRegex(ValueError,'stale_writer'): other.publish('two',{})

    def test_corruption_stops_clean_consumer(self):
        self.put(); self.lake.publish('one',{})
        pack=next((self.root/'remote'/PREFIX/'packs').iterdir()); pack.write_bytes(b'bad')
        with self.assertRaisesRegex(ValueError,'remote_hash'): Lake(self.t,self.root/'clean')

    def test_failed_readback_no_catalog_commit(self):
        self.put()
        original=self.t.read
        def broken(path):
            if '/packs/' in path: return b'corrupt'
            return original(path)
        self.t.read=broken
        with self.assertRaisesRegex(ValueError,'remote_hash'): self.lake.publish('one',{})
        self.assertEqual(self.t.names(PREFIX+'/commits'),[])

    def test_failure_preserves_prior_but_consumer_blocks(self):
        self.put(); self.lake.publish('one',{})
        other=Lake(self.t,self.root/'second'); other.blocked('sec/0000000001',ValueError('HTTP_429'))
        self.assertEqual(other.catalog['datasets']['sec/0000000001']['status'],'STALE_RETAINED')
        other.publish('two',{})
        with self.assertRaisesRegex(ValueError,'stale_dataset'):
            materialize(other,self.root/'x.sqlite',['sec/0000000001'],'2026-09-12')

    def test_amendments_and_filed_cutoff(self):
        early,_=sec_rows(encoded(source()),'0000000001','2016-01-01','2017-12-31')
        later,_=sec_rows(encoded(source()),'0000000001','2016-01-01','2026-09-12')
        self.assertEqual([r['value'] for r in early],[100])
        self.assertEqual([r['value'] for r in later],[100,90])
        self.assertEqual(later[0]['duration_days'],366)

    def test_identity_conflict_fails(self):
        src=source(); values=src['facts']['us-gaap']['Revenues']['units']['USD']
        values.append(dict(values[0],val=1))
        with self.assertRaisesRegex(ValueError,'conflicting_fact_version'):
            sec_rows(encoded(src),'0000000001','2016-01-01','2026-09-12')
        with self.assertRaisesRegex(ValueError,'issuer_identity'):
            sec_rows(encoded(source()),'0000000002','2016-01-01','2026-09-12')

    def test_no_manufactured_ten_years(self):
        rows,_=sec_rows(encoded(source()),'0000000001','2016-01-01','2026-09-12')
        c=fact_coverage(rows,'2016-01-01','2026-09-12')
        self.assertEqual(c['years_with_any_facts'],[2016])
        self.assertEqual(len(c['missing_years']),9)
        self.assertEqual(c['statement_completeness'],'NOT_CERTIFIED')

    def test_ytd_quarter_and_currency_remain_distinct(self):
        src=source(); units=src['facts']['us-gaap']['Revenues']['units']
        units['EUR']=[dict(units['USD'][0])]
        units['USD'].append(dict(units['USD'][0],start='2016-10-01',val=30))
        rows,_=sec_rows(encoded(src),'0000000001','2016-01-01','2026-09-12')
        self.assertEqual(len(rows),4)
        self.assertEqual({r['unit'] for r in rows},{'USD','EUR'})
        self.assertIn(92,{r['duration_days'] for r in rows})

    def test_whole_cohort_and_missing_mapping(self):
        members=[dict(ticker='A'+str(i)) for i in range(1000)]
        mapping={str(i):dict(ticker='A'+str(i),cik_str=i+1) for i in range(999)}
        groups,missing,resolution=issuer_queue(members,mapping)
        self.assertEqual(len(groups),999); self.assertEqual(len(missing),1)
        self.assertTrue(resolution[-1]['lifecycle_review_required'])
        with self.assertRaisesRegex(ValueError,'cik_identity'):
            issuer_queue(members,{'0':dict(ticker='A0',cik_str=0)})
        with self.assertRaisesRegex(ValueError,'cohort_below_1000'): issuer_queue(members[:2],mapping)

    def test_history_mapping_is_role_bound_and_never_current_eligibility(self):
        from tools.long_history_lake import prior_sec_mapping,verified_cohort_source
        members=[dict(ticker='A'+str(i)) for i in range(1000)]
        cohort=encoded(dict(candidate_count=1000,as_of='2026-09-12',rows=members))
        prior=encoded({'0':dict(ticker='A999',cik_str=1000)})
        self.lake.dataset('universe/cohort',[cohort,prior],members,dict(
            evidence='CURRENT_COHORT_NOT_HISTORICAL_MEMBERSHIP',requested_securities=1000))
        entry=self.lake.catalog['datasets']['universe/cohort']
        cohort_sha,mapping_sha=entry['raw_objects']
        entry.update(source_role_contract_version='cohort-sec-mapping-v1',
            cohort_source_object_sha256=cohort_sha,sec_ticker_mapping_object_sha256=mapping_sha,
            sec_ticker_mapping_source_sha256=digest(prior),
            sec_ticker_mapping_retrieved_at='2026-09-12T00:00:00+00:00')
        with patch('tools.long_history_lake.COHORT_SHA',digest(cohort)):
            entry['raw_objects']=[mapping_sha,cohort_sha]
            self.assertEqual(verified_cohort_source(self.lake)[0],cohort)
            mapping=prior_sec_mapping(self.lake)
            self.assertIsNotNone(mapping)
            current={'0':dict(ticker='A0',cik_str=1)}
            groups,missing,resolution=issuer_queue(members,current,mapping)
            self.assertEqual(groups['0000001000'],['A999'])
            self.assertEqual(resolution[-1]['identity_status'],
                             'PRIOR_SEC_MAPPING_RETAINED_LIFECYCLE_REVIEW')
            self.assertFalse(resolution[-1]['current_mapping_present'])
            self.assertTrue(resolution[-1]['lifecycle_review_required'])
            self.assertEqual(len(missing),998)
            entry.pop('sec_ticker_mapping_object_sha256')
            with self.assertRaisesRegex(ValueError,'cohort_source_role'):
                prior_sec_mapping(self.lake)
            entry.pop('source_role_contract_version')
            self.lake.catalog['code_sha']='f'*40
            with self.assertRaisesRegex(ValueError,'cohort_legacy_producer'):
                prior_sec_mapping(self.lake)
            entry['raw_objects']=[cohort_sha,mapping_sha]
            self.lake.catalog['code_sha']='4f8ecd3186539e84d4243d01b98f29e87e902337'
            self.assertIsNotNone(prior_sec_mapping(self.lake))
            entry['raw_objects']=[mapping_sha,cohort_sha]
            with self.assertRaisesRegex(ValueError,'durable_cohort_identity'):
                prior_sec_mapping(self.lake)

    def test_missing_persisted_history_mapping_aborts_without_replacing_provenance(self):
        from tools.long_history_lake import collect_financials,packed,prior_sec_mapping
        members=[dict(ticker='A'+str(i)) for i in range(1000)]
        cohort=self.root/'cohort.json'
        cohort.write_bytes(encoded(dict(candidate_count=1000,as_of='2026-09-12',rows=members)))
        mapping=encoded({'0':dict(ticker='A0',cik_str=1)})
        lost='f'*64
        self.lake.dataset('universe/cohort',[cohort.read_bytes(),mapping],members,dict(
            evidence='CURRENT_COHORT_NOT_HISTORICAL_MEMBERSHIP',requested_securities=1000,
            source_role_contract_version='cohort-sec-mapping-v1',
            cohort_source_object_sha256=digest(packed(cohort.read_bytes())),
            sec_ticker_mapping_object_sha256=digest(packed(mapping)),
            sec_ticker_mapping_source_sha256=digest(mapping),
            sec_ticker_mapping_retrieved_at='2026-09-12T00:00:00+00:00',
            historical_sec_mapping_object_sha256s=[lost]))
        original=copy.deepcopy(self.lake.catalog['datasets']['universe/cohort'])
        with patch('tools.long_history_lake.COHORT_SHA',digest(cohort.read_bytes())):
            with self.assertRaises(KeyError): prior_sec_mapping(self.lake)
            with patch('tools.long_history_lake.get_public',return_value=(mapping,{})):
                with self.assertRaises(KeyError):
                    collect_financials(self.lake,cohort,'2016-01-01','2026-09-12')
        self.assertEqual(self.lake.catalog['datasets']['universe/cohort'],original)

    def test_history_mapping_survives_a_missing_current_mapping_generation(self):
        from tools.long_history_lake import packed,prior_sec_mapping
        members=[dict(ticker='A'+str(i)) for i in range(1000)]
        cohort=encoded(dict(candidate_count=1000,as_of='2026-09-12',rows=members))
        first=encoded({'0':dict(ticker='A999',cik_str=1000)})
        later=encoded({'0':dict(ticker='A0',cik_str=1)})
        def save(lake,mapping,sources=None):
            metadata=dict(evidence='CURRENT_COHORT_NOT_HISTORICAL_MEMBERSHIP',
                requested_securities=1000,source_role_contract_version='cohort-sec-mapping-v1',
                cohort_source_object_sha256=digest(packed(cohort)),
                sec_ticker_mapping_object_sha256=digest(packed(mapping)),
                sec_ticker_mapping_source_sha256=digest(mapping),
                sec_ticker_mapping_retrieved_at='2026-09-12T00:00:00+00:00')
            if sources is not None: metadata['historical_sec_mapping_object_sha256s']=sources
            lake.dataset('universe/cohort',[cohort,mapping],members,metadata)
        with patch('tools.long_history_lake.COHORT_SHA',digest(cohort)):
            save(self.lake,first); self.lake.publish('one',{})
            second=Lake(self.t,self.root/'second')
            save(second,later); second.publish('two',{})
            third=Lake(self.t,self.root/'third')
            mapping,sources=prior_sec_mapping(third,with_sources=True)
            self.assertIn(digest(packed(first)),sources)
            self.assertEqual(issuer_queue(members,json.loads(later),mapping)[2][-1]
                             ['identity_status'],'PRIOR_SEC_MAPPING_RETAINED_LIFECYCLE_REVIEW')
            save(third,later,sources); third.publish('three',{})
            fourth=Lake(self.t,self.root/'fourth')
            mapping,continued=prior_sec_mapping(fourth,with_sources=True)
            self.assertIn(digest(packed(first)),continued)
            self.assertEqual(issuer_queue(members,json.loads(later),mapping)[2][-1]
                             ['identity_status'],'PRIOR_SEC_MAPPING_RETAINED_LIFECYCLE_REVIEW')

    def test_changed_cik_retains_both_sources_and_blocks_lifecycle_certification(self):
        from tools.long_history_lake import collect_financials,diagnostics
        members=[dict(ticker='A'+str(i)) for i in range(1000)]
        cohort=self.root/'cohort.json'
        cohort.write_bytes(encoded(dict(candidate_count=1000,as_of='2026-09-12',rows=members)))
        current={'0':dict(ticker='A0',cik_str=1)}
        prior={'0':dict(ticker='A0',cik_str=2)}
        groups,missing,resolution=issuer_queue(members,current,prior)
        self.assertEqual(groups,{'0000000001':['A0'],'0000000002':['A0']})
        self.assertEqual(len(missing),999)
        self.assertEqual(resolution[0]['identity_status'],'CURRENT_SEC_MAPPING_WITH_HISTORY_CONFLICT')
        self.assertEqual(resolution[0]['history_retained_ciks'],['0000000002'])
        self.assertTrue(resolution[0]['lifecycle_review_required'])
        def fetch(url,conditional=None):
            if url.endswith('company_tickers.json'): return encoded(current),{}
            cik=int(url.rsplit('CIK',1)[1].split('.')[0])
            data=source(); data['cik']=cik
            return encoded(data),{}
        with patch('tools.long_history_lake.COHORT_SHA',digest(cohort.read_bytes())), \
             patch('tools.long_history_lake.prior_sec_mapping',return_value=(prior,[])), \
             patch('tools.long_history_lake.get_public',side_effect=fetch):
            result=collect_financials(self.lake,cohort,'2016-01-01','2026-09-12')
        self.assertEqual(result['mapped_issuers'],1)
        self.assertEqual(result['history_retained_issuer_count'],1)
        self.assertEqual(result['collection_issuer_count'],2)
        self.assertEqual(result['lifecycle_review_count'],1000)
        self.assertEqual(self.lake.catalog['datasets']['sec/0000000001']['status'],'COLLECTED')
        self.assertEqual(self.lake.catalog['datasets']['sec/0000000002']['status'],'COLLECTED')
        report=diagnostics(self.lake)
        self.assertEqual(report['status'],'PARTIAL_COVERAGE')
        self.assertFalse(report['eligible_for_selector'])
        self.assertEqual(report['history_retained_issuer_count'],1)

        # Both verified historical issuers must remain collectible when the
        # ticker later disappears from the current SEC mapping entirely.
        earlier={'0':dict(ticker='A0',cik_str=1),'1':dict(ticker='A0',cik_str=2)}
        unrelated={'0':dict(ticker='UNRELATED',cik_str=3)}
        groups,missing,resolution=issuer_queue(members,unrelated,earlier)
        self.assertEqual(groups,{'0000000001':['A0'],'0000000002':['A0']})
        self.assertEqual(missing[0]['reason'],'CIK_HISTORICAL_AMBIGUOUS')
        self.assertIsNone(resolution[0]['cik'])
        self.assertEqual(resolution[0]['history_retained_ciks'],['0000000001','0000000002'])
        self.assertTrue(resolution[0]['lifecycle_review_required'])
        later=Lake(self.t,self.root/'later')
        def later_fetch(url,conditional=None):
            if url.endswith('company_tickers.json'): return encoded(unrelated),{}
            return fetch(url,conditional)
        with patch('tools.long_history_lake.COHORT_SHA',digest(cohort.read_bytes())), \
             patch('tools.long_history_lake.prior_sec_mapping',return_value=(earlier,[])), \
             patch('tools.long_history_lake.get_public',side_effect=later_fetch):
            result=collect_financials(later,cohort,'2016-01-01','2026-09-12')
        self.assertEqual(result['mapped_issuers'],0)
        self.assertEqual(result['history_retained_issuer_count'],2)
        self.assertEqual(result['collection_issuer_count'],2)
        self.assertEqual(result['lifecycle_review_count'],1000)
        self.assertEqual(later.catalog['datasets']['sec/0000000001']['status'],'COLLECTED')
        self.assertEqual(later.catalog['datasets']['sec/0000000002']['status'],'COLLECTED')
        report=diagnostics(later)
        self.assertEqual(report['status'],'PARTIAL_COVERAGE')
        self.assertFalse(report['eligible_for_selector'])
        self.assertEqual(report['current_mapped_issuer_count'],0)
        self.assertEqual(report['history_retained_issuer_count'],2)

        # Conflicting current rows cannot erase the verified historical queue.
        conflicting={'0':dict(ticker='A0',cik_str=3),'1':dict(ticker='A0',cik_str=4)}
        groups,missing,resolution=issuer_queue(members,conflicting,earlier)
        self.assertEqual(groups,{'0000000001':['A0'],'0000000002':['A0']})
        self.assertEqual(missing[0]['current_ciks'],['0000000003','0000000004'])
        self.assertEqual(resolution[0]['history_retained_ciks'],['0000000001','0000000002'])
        self.assertTrue(resolution[0]['current_mapping_present'])
        self.assertTrue(resolution[0]['lifecycle_review_required'])
        ambiguous=Lake(self.t,self.root/'ambiguous')
        def ambiguous_fetch(url,conditional=None):
            if url.endswith('company_tickers.json'): return encoded(conflicting),{}
            return fetch(url,conditional)
        with patch('tools.long_history_lake.COHORT_SHA',digest(cohort.read_bytes())), \
             patch('tools.long_history_lake.prior_sec_mapping',return_value=(earlier,[])), \
             patch('tools.long_history_lake.get_public',side_effect=ambiguous_fetch):
            result=collect_financials(ambiguous,cohort,'2016-01-01','2026-09-12')
        self.assertEqual(result['mapped_issuers'],0)
        self.assertEqual(result['history_retained_issuer_count'],2)
        self.assertEqual(result['collection_issuer_count'],2)
        self.assertEqual(ambiguous.catalog['datasets']['sec/0000000001']['status'],'COLLECTED')
        self.assertEqual(ambiguous.catalog['datasets']['sec/0000000002']['status'],'COLLECTED')
        self.assertEqual(diagnostics(ambiguous)['status'],'PARTIAL_COVERAGE')

    def test_companyfacts_404_archives_official_role_but_never_facts(self):
        from tools.long_history_lake import collect_financials,diagnostics
        members=[dict(ticker='A'+str(i)) for i in range(1000)]
        cohort=self.root/'cohort.json'
        cohort.write_bytes(encoded(dict(candidate_count=1000,as_of='2026-09-12',rows=members)))
        current=encoded({'0':dict(ticker='A0',cik_str=1)})
        resolution=[dict(ticker='A0',cik='0000000001',identity_status='CURRENT_SEC_MAPPING',
                         lifecycle_review_required=False)]
        submissions=encoded(dict(cik=1,filings=dict(recent=dict(
            form=['10-K','13F-HR'],accessionNumber=['0000000001-26-000001','0000000001-26-000002']))))
        with patch('tools.long_history_lake.COHORT_SHA',digest(cohort.read_bytes())), \
             patch('tools.long_history_lake.issuer_queue',return_value=({'0000000001':['A0']},[],resolution)), \
             patch('tools.long_history_lake.get_public',side_effect=[(current,{}),SourceHTTPError(404),
                 (submissions,{})]):
            collect_financials(self.lake,cohort,'2016-01-01','2026-09-12')
        key='sec/0000000001'; entry=self.lake.catalog['datasets'][key]
        self.assertEqual(entry['status'],'COVERAGE_GAP')
        self.assertEqual(entry['coverage_gap_reason'],
                         'SEC_COMPANYFACTS_UNAVAILABLE_ISSUER_FILINGS_PRESENT')
        self.assertEqual(entry['submissions_source_sha256'],digest(submissions))
        self.assertEqual(entry['issuer_accessions'],['0000000001-26-000001'])
        self.assertIsNone(entry['normalized'])
        with self.assertRaisesRegex(ValueError,'stale_dataset'): self.lake.get_records(key)
        with self.assertRaisesRegex(ValueError,'stale_dataset'):
            materialize(self.lake,self.root/'gap.sqlite',[key],'2026-09-12')
        report=diagnostics(self.lake)
        self.assertEqual(report['status'],'PARTIAL_COVERAGE')
        self.assertFalse(report['eligible_for_selector'])
        self.assertIn(key,report['provider_coverage_gaps'])
        self.lake.publish('gap',{})
        restored=Lake(self.t,self.root/'restored')
        self.assertEqual(restored.catalog['datasets'][key]['submissions_source_sha256'],digest(submissions))

    def test_companyfacts_404_without_valid_submissions_stays_blocked(self):
        from tools.long_history_lake import collect_financials
        members=[dict(ticker='A'+str(i)) for i in range(1000)]
        cohort=self.root/'cohort.json'
        cohort.write_bytes(encoded(dict(candidate_count=1000,as_of='2026-09-12',rows=members)))
        resolution=[dict(ticker='A0',cik='0000000001',identity_status='CURRENT_SEC_MAPPING',
                         lifecycle_review_required=False)]
        with patch('tools.long_history_lake.COHORT_SHA',digest(cohort.read_bytes())), \
             patch('tools.long_history_lake.issuer_queue',return_value=({'0000000001':['A0']},[],resolution)), \
             patch('tools.long_history_lake.get_public',side_effect=[(b'{}',{}),SourceHTTPError(404),
                 (encoded(dict(cik=2,filings=dict(recent=dict(form=['10-K'])))),{})]):
            collect_financials(self.lake,cohort,'2016-01-01','2026-09-12')
        entry=self.lake.catalog['datasets']['sec/0000000001']
        self.assertEqual(entry['status'],'BLOCKED')
        self.assertIsNone(entry.get('normalized'))

    def test_ownership_only_submissions_do_not_prove_fundamental_issuer_role(self):
        from tools.long_history_lake import sec_submissions_profile
        raw=encoded(dict(cik=1,filings=dict(recent=dict(form=['13F-HR','4'],
            accessionNumber=['0000000001-26-000001','0000000001-26-000002']))))
        profile=sec_submissions_profile(raw,'0000000001')
        self.assertFalse(profile['has_fundamental_issuer_role'])
        self.assertEqual(profile['issuer_accessions'],[])
        with self.assertRaisesRegex(ValueError,'sec_submissions_identity'):
            sec_submissions_profile(raw,'0000000002')
        with self.assertRaisesRegex(ValueError,'sec_submissions_accessions'):
            sec_submissions_profile(encoded(dict(cik=1,filings=dict(recent=dict(form=['10-K'])))),
                                    '0000000001')

    def test_schema_and_window_changes_invalidate_http_validators(self):
        from tools.long_history_lake import sec_conditional,extraction_identity
        old=dict(start='2016-01-01',through='2026-09-12',http={'etag':'v1'},extraction_sha256=extraction_identity(),deferred_until=None)
        self.assertEqual(sec_conditional(old,old['start'],old['through']),old['http'])
        with patch('tools.long_history_lake.FORMS',{'10-K'}):
            self.assertIsNone(sec_conditional(old,old['start'],old['through']))
        self.assertEqual(sec_conditional(old,old['start'],'2026-09-13'),old['http'])
        self.assertIsNone(sec_conditional(old,old['start'],'2026-09-11'))
        self.assertIsNone(sec_conditional(dict(old,extraction_sha256='old'),old['start'],old['through']))

    def test_deferred_financial_period_invalidates_reuse_when_due(self):
        from tools.long_history_lake import sec_future_boundary,sec_conditional,extraction_identity
        boundary=sec_future_boundary(encoded(source()),'2017-12-31')
        self.assertEqual(boundary,'2018-01-01')
        old=dict(start='2016-01-01',through='2017-12-31',http={'etag':'v1'},extraction_sha256=extraction_identity(),deferred_until=boundary)
        self.assertIsNone(sec_conditional(old,old['start'],'2018-01-01'))

    def test_old_catalog_corruption_is_not_hidden_by_valid_tip(self):
        self.put(); first=self.lake.publish('one',{})
        other=Lake(self.t,self.root/'second'); self.put(other,90); other.publish('two',{})
        (self.root/'remote'/PREFIX/'catalogs'/first['catalog_sha256']).write_bytes(b'bad')
        with self.assertRaisesRegex(ValueError,'remote_hash'): Lake(self.t,self.root/'third')

    def test_preserves_fiscal_contexts(self):
        src=source(); values=src['facts']['us-gaap']['Revenues']['units']['USD']
        values.append(dict(values[0],fy=2017,fp='FY',frame='CY2016'))
        rows,_=sec_rows(encoded(src),'0000000001','2016-01-01','2026-09-12')
        self.assertEqual(len(rows),3)
        self.assertEqual(sum(r['frame']=='CY2016' for r in rows),1)

    def test_unmapped_security_keeps_cycle_partial(self):
        from tools.long_history_lake import diagnostics
        self.lake.catalog['datasets']['universe/cohort']=dict(status='COLLECTED',active_issuer_keys=[],missing=[dict(ticker='HOLX')])
        self.assertEqual(diagnostics(self.lake)['status'],'PARTIAL_COVERAGE')

    def test_country_year_missing_coverage(self):
        from tools.long_history_lake import wb_coverage
        rows=[dict(country='USA',observation_date='2024-01-01',value=3),dict(country='USA',observation_date='2025-01-01',value=None)]
        with patch('tools.long_history_lake.COUNTRIES',('USA',)):
            result=wb_coverage(rows,'2024-01-01','2025-12-31')
        self.assertEqual(result['missing_values'],1)
        self.assertEqual(result['missing_country_years'],[dict(country='USA',year=2025)])
        self.assertEqual(result['country_coverage']['USA']['latest'],'2024-01-01')

    def test_worldbank_coverage_counts_omitted_countries_and_boundary_years(self):
        from tools.long_history_lake import wb_coverage
        rows=[dict(country='USA',observation_date='2024-01-01',value=3),
              dict(country='USA',observation_date='2025-01-01',value=None),
              dict(country='CHN',observation_date='2024-01-01',value=2)]
        result=wb_coverage(rows,'2024-01-01','2026-09-12')
        self.assertEqual(result['expected_country_years'],15)
        self.assertEqual(result['missing_values'],13)
        self.assertEqual(len(result['omitted_country_years']),12)
        self.assertEqual(result['country_coverage']['USA']['missing_years'],[2025,2026])
        self.assertEqual(result['country_coverage']['KOR']['missing_years'],[2024,2025,2026])
        self.assertEqual(result['country_coverage']['KOR']['nonmissing'],0)
        self.assertIsNone(result['country_coverage']['KOR']['earliest'])

    def test_secret_job_is_default_branch_only(self):
        workflow=(ROOT/'.github/workflows/long_history_research.yml').read_text()
        self.assertIn("branches: ['master']",workflow)
        self.assertIn("&& github.ref == 'refs/heads/master'",workflow)
        self.assertNotIn('codex/durable-long-history-20260912',workflow)

    def test_code_push_does_not_launch_history_producer(self):
        import re
        workflow=(ROOT/'.github/workflows/long_history_research.yml').read_text()
        guards=re.findall(r'^    if: (.+)$',workflow,re.MULTILINE)
        self.assertEqual(guards,[
            "github.repository == 'wscha231/r1000-quant-engine' && "
            "github.ref == 'refs/heads/master' && github.event_name != 'push'"])
        self.assertIn('  workflow_dispatch:',workflow)
        self.assertIn('  schedule:',workflow)
        self.assertIn('    - cron: \'37 6 * * 2-6\'',workflow)
        self.assertIn('  group: durable-long-history-single-writer',workflow)
        self.assertIn('  cancel-in-progress: false',workflow)

    def test_skipped_code_push_never_joins_history_writer_queue(self):
        import yaml
        workflow=yaml.load((ROOT/'.github/workflows/long_history_research.yml').read_text(),Loader=yaml.BaseLoader)
        self.assertNotIn('concurrency',workflow)
        self.assertEqual(set(workflow['jobs']),{'history'})
        producer=workflow['jobs']['history']
        self.assertEqual(producer['concurrency'],{
            'group':'durable-long-history-single-writer','cancel-in-progress':'false'})
        self.assertEqual(producer['if'],
            "github.repository == 'wscha231/r1000-quant-engine' && "
            "github.ref == 'refs/heads/master' && github.event_name != 'push'")
        self.assertEqual(workflow['on']['push']['branches'],['master'])
        self.assertEqual(workflow['on']['schedule'],[{'cron':'37 6 * * 2-6'}])
        self.assertIn('workflow_dispatch',workflow['on'])
        self.assertEqual(workflow['permissions'],{'contents':'read','actions':'read'})

    def test_fixed_transport_categories_survive_history_error_sanitization(self):
        from tools.macro_research_checkpoint import transport_failure, is_safe_transport_failure
        from tools.long_history_lake import safe_error
        examples = (
            ('RATE_LIMIT', b'userRateLimitExceeded'),
            ('DOWNLOAD_QUOTA', b'downloadQuotaExceeded'),
            ('STORAGE_QUOTA', b'storageQuotaExceeded'),
            ('AUTHENTICATION_INVALID_GRANT', b'invalid_grant'),
            ('AUTHENTICATION_INVALID_CLIENT', b'invalid_client'),
            ('AUTHENTICATION_UNAUTHORIZED_CLIENT', b'unauthorized_client'),
            ('AUTHENTICATION_INVALID_SCOPE', b'invalid_scope'),
            ('AUTHENTICATION', b'error 401'), ('PERMISSION', b'forbidden'),
            ('QUOTA', b'quota'), ('DOWNLOAD_RESTRICTED', b'abusive'),
            ('NOT_DOWNLOADABLE', b'not a file'), ('TIMEOUT', b'deadline exceeded'),
            ('NOT_FOUND', b'not found'), ('UNCLASSIFIED', b'no classified term'),
        )
        for category, body in examples:
            for verb in ('mkdir', 'cat', 'lsjson', 'copy', 'copyto', 'unknown-command'):
                for status in (0, 1, 3, -9, -(2**31), 2**32 - 1):
                    with self.subTest(category=category, verb=verb, status=status):
                        code = transport_failure(body, verb, status)
                        expected_verb = 'command' if verb == 'unknown-command' else verb
                        self.assertEqual(code, 'research_transport_failed:' + expected_verb +
                                         ':exit_' + str(status) + ':' + category)
                        self.assertTrue(is_safe_transport_failure(code))
                        self.assertEqual(safe_error(ValueError(code)), code)

    def test_transport_error_validator_refuses_spoofed_private_or_unbounded_text(self):
        from tools.macro_research_checkpoint import is_safe_transport_failure
        from tools.long_history_lake import safe_error
        code = 'research_transport_failed:cat:exit_1:RATE_LIMIT'
        invalid = (
            'https://private.invalid/?token=SYNTHETIC_SECRET', '/tmp/private/object',
            'Authorization: Bearer SYNTHETIC_SECRET', 'arbitrary diagnostic text',
            'prefix_' + code, code + ':suffix', code + ' ', code + '\n', code + '\r\n',
            code + '\x00', code.replace('cat:', 'cat/path:'), code.replace('cat:', 'http:'),
            code.replace('cat:', 'CAT:'), code.replace('cat:', ':'),
            code.replace('research_transport_failed:', 'research_transport_failed_extra:'),
            code.replace('RATE_LIMIT', 'FAKE_CATEGORY'), code.replace('RATE_LIMIT', 'RATE_LIMIT_SECRET'),
            code.replace('RATE_LIMIT', 'rate_limit'), code.replace('RATE_LIMIT', 'RATE%5FLIMIT'),
            code.replace('exit_1', 'exit_+1'), code.replace('exit_1', 'exit_01'),
            code.replace('exit_1', 'exit_-0'), code.replace('exit_1', 'exit_1.0'),
            code.replace('exit_1', 'exit_True'), code.replace('exit_1', 'exit_4294967296'),
            code.replace('exit_1', 'exit_-2147483649'), code.replace('exit_1', 'exit_' + '9'*10000),
            code.replace('cat:', 'cat:private:'), '\n' + code,
        )
        for index, text in enumerate(invalid):
            with self.subTest(index=index):
                self.assertFalse(is_safe_transport_failure(text))
                self.assertEqual(safe_error(ValueError(text)), 'SOURCE_OR_CONTRACT_ERROR')
        for value in (None, 1, True, code.encode(), [], {}):
            self.assertFalse(is_safe_transport_failure(value))
        self.assertFalse(is_safe_transport_failure('legacy_contract_code'))
        self.assertEqual(safe_error(ValueError('legacy_contract_code')), 'legacy_contract_code')

    def test_transport_error_keeps_existing_typed_exception_and_blocked_policy(self):
        from urllib.error import HTTPError, URLError
        from tools.long_history_lake import safe_error
        code = 'research_transport_failed:cat:exit_3:NOT_FOUND'
        self.assertEqual(safe_error(HTTPError('https://private.invalid', 403, code, {}, None)), 'HTTP_403')
        self.assertEqual(safe_error(TimeoutError(code)), 'TRANSPORT_TIMEOUT')
        self.assertEqual(safe_error(URLError(code)), 'TRANSPORT_ERROR')
        self.assertEqual(safe_error(OSError(code)), 'TRANSPORT_ERROR')
        self.assertEqual(safe_error(ValueError('a'*90)), 'a'*90)
        self.assertEqual(safe_error(ValueError('a'*91)), 'SOURCE_OR_CONTRACT_ERROR')
        self.lake.blocked('current/SYNTHETIC', ValueError(code))
        record = self.lake.catalog['datasets']['current/SYNTHETIC']
        self.assertEqual(record['last_failure'], code)
        self.assertEqual(record['status'], 'BLOCKED')

    def test_transport_call_to_history_preserves_only_fixed_code(self):
        import io
        import os
        import subprocess
        from contextlib import redirect_stdout, redirect_stderr
        from tools import macro_research_checkpoint as checkpoint
        from tools.long_history_lake import safe_error
        transport = object.__new__(checkpoint.RcloneTransport)
        transport.binary = 'rclone-synthetic'
        failure = subprocess.CompletedProcess([], 1, b'',
            b'invalid_grant userRateLimitExceeded https://private.invalid/?token=SYNTHETIC_SECRET')
        output = io.StringIO()
        with patch.dict(os.environ, {'MACRO_RCLONE_CONFIG': 'SYNTHETIC_CONFIG'}, clear=True), \
             patch.object(checkpoint.subprocess, 'run', return_value=failure) as call, \
             redirect_stdout(output), redirect_stderr(output):
            with self.assertRaises(ValueError) as caught:
                transport.call('cat', 'gdrive:synthetic')
            code = safe_error(caught.exception)
        call.assert_called_once()
        self.assertEqual(code, 'research_transport_failed:cat:exit_1:RATE_LIMIT')
        self.assertEqual(str(caught.exception), code)
        self.assertNotIn('SYNTHETIC_SECRET', output.getvalue() + code)
        self.assertNotIn('private.invalid', output.getvalue() + code)

    def test_transient_fred_retry_and_secret_safe_failure(self):
        from urllib.error import URLError,HTTPError
        from tools.long_history_lake import fetch_fred_retry,safe_error
        expected=([b'data'],'2026-09-12T00:00:00+00:00')
        with patch('tools.long_history_lake.fetch_fred',side_effect=[URLError('api_key=private'),expected]) as fetch,patch('tools.long_history_lake.time.sleep'):
            self.assertEqual(fetch_fred_retry('NFCI','1996-01-01','2026-09-12','alfred'),expected)
            self.assertEqual(fetch.call_count,2)
        self.assertEqual(safe_error(HTTPError('https://example.com/?api_key=private',403,'private',{},None)),'HTTP_403')
        with patch('tools.long_history_lake.fetch_fred',side_effect=URLError('api_key=private')) as fetch,patch('tools.long_history_lake.time.sleep'):
            with self.assertRaisesRegex(ValueError,'^TRANSPORT_ERROR$'):
                fetch_fred_retry('NFCI','1996-01-01','2026-09-12','alfred')
            self.assertEqual(fetch.call_count,3)

    def test_source_contract_errors_are_not_retried(self):
        from tools.long_history_lake import fetch_fred_retry
        with patch('tools.long_history_lake.fetch_fred',side_effect=ValueError('alfred_count')) as fetch:
            with self.assertRaisesRegex(ValueError,'alfred_count'):
                fetch_fred_retry('NFCI','1996-01-01','2026-09-12','alfred')
            self.assertEqual(fetch.call_count,1)

    def test_current_api_auth_failure_has_no_retry_or_secret_in_report(self):
        from urllib.error import HTTPError
        from tools import long_history_lake as history
        from tools import macro_history_sources as fred
        key = 'fixture-secret'
        error = HTTPError('https://example.com/?api_key='+key, 403, key, {}, None)
        with patch.dict('os.environ', {'FRED_API_KEY': key}), \
             patch.object(fred, 'request_bytes', side_effect=error) as request, \
             patch.object(history.time, 'sleep') as sleep:
            with self.assertRaisesRegex(ValueError, '^HTTP_403$') as caught:
                history.fetch_fred_retry('UNRATE','2020-01-01','2020-03-31','current')
            request.assert_called_once()
            sleep.assert_not_called()
        self.assertNotIn(key, repr(caught.exception))

    def test_fred_missing_dates_survive_parser(self):
        from tools.long_history_lake import parse_current,fred_missing
        rows,missing=parse_current([b'observation_date,UNRATE\n2025-09-01,4.4\n2025-10-01,.\n2025-11-01,4.5\n'],
            'UNRATE','2025-01-01','2025-12-31','2026-09-12T00:00:00+00:00')
        result=fred_missing(rows,missing)
        self.assertEqual(result['missing_values'],1)
        self.assertEqual(result['missing_observation_dates'],['2025-10-01'])

    def test_current_api_raw_bytes_survive_lake_collection_and_study_restore(self):
        from tools import long_history_lake as history
        from tools import macro_history_sources as fred
        start, through, vintage = '2020-01-01', '2020-03-31', '2026-09-12'
        retrieved = vintage + 'T12:00:00Z'
        current = encoded(dict(file_type='json', units='lin', output_type=1, offset=0,
            limit=fred.CURRENT_API_ROW_LIMIT, count=2, observation_start=start,
            observation_end=through, realtime_start=vintage, realtime_end=vintage,
            observations=[dict(date=day, value=value, realtime_start=vintage, realtime_end=vintage)
                for day, value in ((start, '3.5'), ('2020-02-01', '.'))]))
        archive = encoded(dict(units='lin', output_type=1, count=1, offset=0,
            observations=[dict(date=start, value='3.0', realtime_start='2020-02-07', realtime_end='9999-12-31')]))
        ids = ('UNRATE', 'PAYEMS', 'CPIAUCSL')
        specs = [s for s in history.registry()['series'] if s['id'] in ids]
        config = dict(registry_sha256=digest(encoded(history.registry())))
        with patch.object(history, 'registry', return_value={'series': specs}), \
             patch.object(history, 'WB_INDICATORS', ()), \
             patch.object(history, 'fetch_fred_retry',
                          side_effect=lambda sid, first, last, mode: ([current if mode == 'current' else archive], retrieved)):
            history.collect_macros(self.lake, start, through)
        self.lake.publish('current-api', config)
        restored = Lake(self.t, self.root/'current-api-restore')
        entry = restored.catalog['datasets']['current/UNRATE']
        self.assertEqual(entry['status'], 'COLLECTED')
        self.assertEqual(entry['missing_observation_dates'], ['2020-02-01'])
        self.assertEqual(history.unpacked(restored.get_bytes(entry['raw_objects'][0])), current)

        def inspect_study(store, path, cutoff, archive_paths):
            receipt, rows = fred.load_bundle(store, path)
            self.assertEqual(receipt['sources'][0]['raw_sha256'], [digest(current)])
            self.assertEqual(rows['UNRATE'][0]['available_at'], retrieved)
            self.assertEqual(rows['UNRATE'][0]['evidence'], 'current_only')
            self.assertIsNone(rows['UNRATE'][0]['vintage_date'])
            _, archives = fred.load_bundle(store, archive_paths[0])
            self.assertEqual(archives['UNRATE'][0]['evidence'], 'alfred_date_archive')
            return {}

        with patch('tools.macro_research_cycle.CURRENT', ['UNRATE']), \
             patch('tools.macro_technical_study.study', side_effect=inspect_study) as study, \
             patch('tools.macro_research_cycle.engine_context', return_value={}):
            history.analyze_restored(restored, self.root/'study', start, through)
        study.assert_called_once()

    def test_current_mapping_excludes_retained_old_issuer(self):
        from tools.long_history_lake import diagnostics
        self.put()
        self.lake.catalog['datasets']['sec/0000000002']=dict(status='BLOCKED',rows=0)
        self.lake.catalog['datasets']['universe/cohort']=dict(status='COLLECTED',active_issuer_keys=['sec/0000000001'])
        report=diagnostics(self.lake)
        self.assertEqual(report['financial_issuers'],1)
        self.assertEqual(report['archived_inactive_issuers'],1)
        self.assertEqual(report['status_counts']['BLOCKED'],0)
        self.assertIn('sec/0000000002',self.lake.catalog['datasets'])

    def test_retains_rolling_prefix_not_interior_gap(self):
        from tools.long_history_lake import retain_price_prefix
        old=[dict(observation_date='2016-01-0'+str(i),value=i,evidence='current_only') for i in range(1,6)]
        new=[dict(observation_date='2016-01-0'+str(i),value=i*10,evidence='current_only') for i in (3,5)]
        rows,n=retain_price_prefix(old,new,'2026-09-11T00:00:00+00:00')
        self.assertEqual(n,2)
        self.assertEqual([r['value'] for r in rows],[1,2,30,50])
        self.assertEqual(rows[0]['source_retrieved_at'],'2026-09-11T00:00:00+00:00')

    def test_rolling_collection_preserves_old_gaps_and_new_window_boundary(self):
        from tools.long_history_lake import collect_macros,registry
        spec=next(s for s in registry()['series'] if s['id']=='SP500')
        old=b'observation_date,SP500\n2020-01-01,10\n2020-01-02,.\n2020-01-03,30\n2020-01-04,40\n'
        new=b'observation_date,SP500\n2020-01-03,.\n2020-01-04,41\n'
        filled=b'observation_date,SP500\n2020-01-03,31\n2020-01-04,42\n'
        with patch('tools.long_history_lake.registry',return_value={'series':[spec]}), \
             patch('tools.long_history_lake.WB_INDICATORS',()), \
             patch('tools.long_history_lake.fetch_fred_retry') as fetch:
            fetch.return_value=([old],'2026-09-10T00:00:00+00:00')
            collect_macros(self.lake,'1996-01-01','2026-09-10')
            self.lake.publish('first',{})
            reader=Lake(self.t,self.root/'rolling')
            fetch.return_value=([new],'2026-09-11T00:00:00+00:00')
            collect_macros(reader,'1996-01-01','2026-09-11')
            entry=reader.catalog['datasets']['current/SP500']
            self.assertEqual(entry['status'],'COLLECTED')
            self.assertEqual(entry['missing_observation_dates'],['2020-01-02','2020-01-03'])
            self.assertEqual(entry['missing_values'],2)
            self.assertEqual([r['value'] for r in reader.get_records('current/SP500')],[10,41])
            self.assertTrue(entry['retained_source_objects'])
            reader.publish('second',{})
            last=Lake(self.t,self.root/'filled')
            fetch.return_value=([filled],'2026-09-12T00:00:00+00:00')
            collect_macros(last,'1996-01-01','2026-09-12')
            self.assertEqual(last.catalog['datasets']['current/SP500']['missing_observation_dates'],['2020-01-02'])
            self.assertEqual(last.catalog['datasets']['current/SP500']['missing_values'],1)

    def test_stale_price_prefix_recovers_without_consumer_admission(self):
        from tools.long_history_lake import collect_macros,registry
        spec=next(s for s in registry()['series'] if s['id']=='SP500')
        self.lake.dataset('current/SP500',[b'old'],[
            dict(observation_date='2020-01-01',value=10,evidence='current_only')],
            dict(evidence='current_only',retrieved_at='2026-09-10T00:00:00+00:00'))
        self.lake.publish('one',{})
        failed=Lake(self.t,self.root/'failed')
        failed.blocked('current/SP500',ValueError('TRANSPORT_ERROR'))
        failed.publish('two',{})
        recovered=Lake(self.t,self.root/'recovered')
        with self.assertRaisesRegex(ValueError,'stale_dataset'):
            recovered.get_records('current/SP500')
        with patch('tools.long_history_lake.registry',return_value={'series':[spec]}), \
             patch('tools.long_history_lake.WB_INDICATORS',()), \
             patch('tools.long_history_lake.fetch_fred_retry',return_value=(
                 [b'observation_date,SP500\n2020-01-03,30\n'],'2026-09-12T00:00:00+00:00')):
            collect_macros(recovered,'2020-01-01','2026-09-12')
        self.assertEqual(recovered.catalog['datasets']['current/SP500']['status'],'COLLECTED')
        self.assertEqual([r['value'] for r in recovered.get_records('current/SP500')],[10,30])

    def test_sql_cutoff(self):
        self.put(); self.lake.publish('one',{})
        reader=Lake(self.t,self.root/'consumer')
        count=materialize(reader,self.root/'x.sqlite',['sec/0000000001'],'2016-12-31')
        self.assertEqual(count,0)

    def test_materialize_releases_real_connection_on_all_failure_phases(self):
        self.put()
        original_catalog=copy.deepcopy(self.lake.catalog)
        key='sec/0000000001'
        actual_connect=sqlite3.connect
        failures=(
            ('stale',ValueError,'stale_dataset'),
            ('current',ValueError,'current_vintage_historical_cutoff_forbidden'),
            ('generation',KeyError,'generation'),
            ('dataset',KeyError,'missing'),
            ('read',ValueError,'object_hash'),
            ('json',TypeError,'not JSON serializable'),
            ('create_records',sqlite3.OperationalError,'injected_sql_failure'),
            ('insert_provenance',sqlite3.OperationalError,'injected_sql_failure'),
            ('insert_records',sqlite3.OperationalError,'injected_sql_failure'),
            ('create_index',sqlite3.OperationalError,'injected_sql_failure'),
            ('transaction_exit',sqlite3.OperationalError,'injected_transaction_exit'),
        )
        for failure,exception,reason in failures:
            with self.subTest(failure=failure):
                self.lake.catalog=copy.deepcopy(original_catalog)
                keys=[key];cutoff='2026-09-12'
                if failure=='stale': self.lake.catalog['datasets'][key]['status']='STALE_RETAINED'
                elif failure=='current':
                    self.lake.catalog['datasets'][key].update(evidence='current_only',retrieved_at='2026-09-12T00:00:00Z')
                    cutoff='2016-12-31'
                elif failure=='generation': del self.lake.catalog['generation']
                elif failure=='dataset': keys=['missing']
                opened=[]
                class FaultConnection(sqlite3.Connection):
                    def execute(connection,sql,*args):
                        prefixes={'create_records':'create table records',
                                  'insert_provenance':'insert into provenance',
                                  'insert_records':'insert into records','create_index':'create index'}
                        if failure in prefixes and sql.startswith(prefixes[failure]):
                            raise sqlite3.OperationalError('injected_sql_failure')
                        return super().execute(sql,*args)
                    def __exit__(connection,kind,value,traceback):
                        if failure=='transaction_exit' and kind is None:
                            raise sqlite3.OperationalError('injected_transaction_exit')
                        return super().__exit__(kind,value,traceback)
                def connect(*args,**kwargs):
                    connection=actual_connect(*args,factory=FaultConnection,**kwargs)
                    opened.append(connection)  # Keep it alive: GC cannot release the handle for us.
                    self.addCleanup(connection.close)
                    return connection
                actual_records=self.lake.get_records
                def records(dataset):
                    if failure=='read': raise ValueError('object_hash')
                    if failure=='json': return [dict(end='2016-12-31',value=1,unserializable=object())]
                    return actual_records(dataset)
                database=self.root/(failure+'.sqlite')
                with patch('tools.long_history_lake.sqlite3.connect',connect),patch.object(self.lake,'get_records',records):
                    with self.assertRaisesRegex(exception,reason):
                        materialize(self.lake,database,keys,cutoff)
                self.assertEqual(len(opened),1)
                with self.assertRaisesRegex(sqlite3.ProgrammingError,'closed database'):
                    opened[0].execute('select 1')
                # Same-process reopen/rename must work while the original
                # connection object remains strongly referenced. No GC call.
                reopened=actual_connect(database)
                try:
                    self.assertEqual(reopened.execute('select 1').fetchone(),(1,))
                    if failure in ('create_index','transaction_exit'):
                        self.assertEqual(reopened.execute('select count(*) from records').fetchone(),(0,))
                        self.assertEqual(reopened.execute('select count(*) from provenance').fetchone(),(0,))
                finally: reopened.close()
                retained=database.with_suffix('.retained.sqlite')
                database.rename(retained)
                self.assertTrue(retained.is_file())
                self.assertFalse(database.exists())

    def test_materialize_clean_success_commits_and_releases_connection(self):
        self.put()
        database=self.root/'clean.sqlite'
        opened=[];actual_connect=sqlite3.connect
        def connect(*args,**kwargs):
            connection=actual_connect(*args,**kwargs)
            opened.append(connection);self.addCleanup(connection.close)
            return connection
        with patch('tools.long_history_lake.sqlite3.connect',connect):
            count=materialize(self.lake,database,['sec/0000000001'],'2026-09-12')
        self.assertEqual(count,1)
        self.assertEqual(len(opened),1)
        with self.assertRaisesRegex(sqlite3.ProgrammingError,'closed database'):
            opened[0].execute('select 1')
        reopened=actual_connect(database)
        try:
            self.assertEqual(reopened.execute('select value from records').fetchall(),[(100.0,)])
            self.assertEqual(reopened.execute('select * from provenance').fetchall(),
                             [(self.lake.catalog['generation'],'2026-09-12',0)])
            self.assertEqual(reopened.execute("select name from sqlite_master where type='index'").fetchall(),[('lookup',)])
        finally: reopened.close()
        retained=database.with_suffix('.retained.sqlite');database.rename(retained)
        self.assertTrue(retained.is_file())

    def test_materialize_existing_destination_rejects_before_connect(self):
        database=self.root/'existing.sqlite';database.write_bytes(b'preserved prior cache')
        with patch('tools.long_history_lake.sqlite3.connect') as connect:
            with self.assertRaisesRegex(ValueError,'database_already_exists'):
                materialize(self.lake,database,[],'2026-09-12')
        connect.assert_not_called()
        self.assertEqual(database.read_bytes(),b'preserved prior cache')

    def test_current_vintage_cannot_be_backdated(self):
        self.lake.dataset('current/UNRATE',[b'raw'],[dict(observation_date='2000-01-01',value=4)],
            dict(evidence='current_only',retrieved_at='2026-09-12T00:00:00+00:00'))
        with self.assertRaisesRegex(ValueError,'current_vintage_historical_cutoff_forbidden'):
            materialize(self.lake,self.root/'x.sqlite',['current/UNRATE'],'2016-12-31')

    def test_worldbank_identity_and_partial_pages(self):
        payload=[dict(pages=1,total=1),[dict(indicator=dict(id='SP.POP.TOTL'),countryiso3code='USA',date='2000',value=100)]]
        rows=wb_rows(encoded(payload),'SP.POP.TOTL','1996-01-01','2026-09-12','2026-09-12T00:00:00+00:00')
        self.assertEqual(rows[0]['evidence'],'current_only')
        payload[0]['pages']=2
        with self.assertRaisesRegex(ValueError,'worldbank_pagination'):
            wb_rows(encoded(payload),'SP.POP.TOTL','1996-01-01','2026-09-12','2026-09-12T00:00:00+00:00')


    def append_catalog_for_fault(self,catalog,parent):
        """Inject a hash-valid successor with broken dependencies, without publishing."""
        catalog=copy.deepcopy(catalog)
        catalog['generation']+=1
        raw=encoded(catalog); catalog_sha=digest(raw)
        self.t.write(PREFIX+'/catalogs/'+catalog_sha,raw)
        commit=encoded(dict(schema='long-history-commit-v1',parent=parent,
            catalog=catalog_sha,generation=catalog['generation']))
        self.t.write(PREFIX+'/commits/'+digest(commit),commit)

    def alternate_pack(self,names_and_bytes):
        import io
        import warnings
        import zipfile
        output=io.BytesIO()
        with warnings.catch_warnings():
            warnings.simplefilter('ignore',UserWarning)
            with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_STORED) as archive:
                for name,raw in names_and_bytes: archive.writestr(name,raw)
        raw=output.getvalue(); sha=digest(raw)
        self.t.write(PREFIX+'/packs/'+sha,raw)
        return sha

    def test_missing_active_pack_blocks_restore(self):
        self.put(); self.lake.publish('one',{})
        next((self.root/'remote'/PREFIX/'packs').iterdir()).unlink()
        with self.assertRaisesRegex(ValueError,'checkpoint_object_size'):
            Lake(self.t,self.root/'empty-cache')

    def test_old_pack_missing_cannot_hide_behind_empty_tip(self):
        self.put(); first=self.lake.publish('one',{})
        old_pack=next((self.root/'remote'/PREFIX/'packs').iterdir())
        latest=copy.deepcopy(self.lake.catalog)
        latest['datasets']={}; latest['locations']={}
        self.append_catalog_for_fault(latest,first['commit_sha256'])
        old_pack.unlink()
        with self.assertRaisesRegex(ValueError,'checkpoint_object_size'):
            Lake(self.t,self.root/'empty-cache')

    def test_valid_pack_hash_with_missing_object_is_rejected(self):
        self.put(); first=self.lake.publish('one',{})
        latest=copy.deepcopy(self.lake.catalog)
        obj=latest['datasets']['sec/0000000001']['normalized']
        latest['locations'][obj]=self.alternate_pack([(digest(b'other'),b'other')])
        self.append_catalog_for_fault(latest,first['commit_sha256'])
        with self.assertRaisesRegex(ValueError,'pack_dependency'):
            Lake(self.t,self.root/'empty-cache')

    def test_valid_pack_hash_with_wrong_object_bytes_is_rejected(self):
        self.put(); first=self.lake.publish('one',{})
        latest=copy.deepcopy(self.lake.catalog)
        obj=latest['datasets']['sec/0000000001']['normalized']
        latest['locations'][obj]=self.alternate_pack([(obj,b'wrong-content')])
        self.append_catalog_for_fault(latest,first['commit_sha256'])
        with self.assertRaisesRegex(ValueError,'pack_object_hash'):
            Lake(self.t,self.root/'empty-cache')

    def test_duplicate_pack_members_are_rejected(self):
        self.put(); first=self.lake.publish('one',{})
        latest=copy.deepcopy(self.lake.catalog)
        obj=latest['datasets']['sec/0000000001']['normalized']
        raw=self.lake.get_bytes(obj)
        latest['locations'][obj]=self.alternate_pack([(obj,raw),(obj,raw)])
        self.append_catalog_for_fault(latest,first['commit_sha256'])
        with self.assertRaisesRegex(ValueError,'pack_inventory'):
            Lake(self.t,self.root/'empty-cache')

    def test_warm_disk_and_memory_cache_do_not_hide_remote_corruption(self):
        self.put(); self.lake.publish('one',{})
        reader=Lake(self.t,self.root/'consumer')
        self.assertEqual(reader.get_records('sec/0000000001')[0]['value'],100)
        next((self.root/'remote'/PREFIX/'packs').iterdir()).write_bytes(b'bad')
        before=self.t.names(PREFIX+'/commits')
        with self.assertRaisesRegex(ValueError,'remote_hash'): reader.publish('two',{})
        self.assertEqual(self.t.names(PREFIX+'/commits'),before)
        with self.assertRaisesRegex(ValueError,'remote_hash'):
            Lake(self.t,self.root/'consumer')

    def test_sec_304_cannot_publish_after_prior_pack_disappears(self):
        from tools.long_history_lake import collect_financials,extraction_identity
        self.put()
        self.lake.catalog['datasets']['sec/0000000001'].update(
            start='2016-01-01',through='2026-09-12',years_with_any_facts=[2016],
            http={'etag':'v1'},extraction_sha256=extraction_identity(),deferred_until=None)
        self.lake.publish('one',{})
        reader=Lake(self.t,self.root/'collector')
        cohort=self.root/'cohort.json'
        cohort.write_bytes(encoded(dict(candidate_count=1,as_of='2026-09-12',rows=[dict(ticker='A')])))
        before=self.t.names(PREFIX+'/commits')
        next((self.root/'remote'/PREFIX/'packs').iterdir()).unlink()
        with patch('tools.long_history_lake.COHORT_SHA',digest(cohort.read_bytes())), \
             patch('tools.long_history_lake.issuer_queue',return_value=({'0000000001':['A']},[],[
                 dict(ticker='A',cik='0000000001',identity_status='CURRENT_SEC_MAPPING',
                      lifecycle_review_required=False)])), \
             patch('tools.long_history_lake.get_public',side_effect=[(b'{}',{}),(None,{'etag':'v1'})]) as fetch:
            collect_financials(reader,cohort,'2016-01-01','2026-09-12')
            self.assertEqual(fetch.call_args.args[1],{'etag':'v1'})
        self.assertEqual(reader.catalog['datasets']['sec/0000000001']['status'],'UNCHANGED')
        with self.assertRaisesRegex(ValueError,'checkpoint_object_size'): reader.publish('two',{})
        self.assertEqual(self.t.names(PREFIX+'/commits'),before)

    def test_shared_packs_are_read_once_per_restore(self):
        from collections import Counter
        self.put(); self.lake.publish('one',{})
        next_lake=Lake(self.t,self.root/'second')
        self.put(next_lake,90); next_lake.publish('two',{})
        expected=set(next_lake.catalog['locations'].values())
        with patch.object(self.t,'read',wraps=self.t.read) as read:
            Lake(self.t,self.root/'clean')
        counts=Counter(c.args[0].rsplit('/',1)[1] for c in read.call_args_list if '/packs/' in c.args[0])
        self.assertEqual(dict(counts),dict.fromkeys(expected,1))

    def pack_dependencies(self,count):
        result={}
        for i in range(count):
            body=('synthetic-pack-object-'+str(i)).encode()
            obj=digest(body);pack=self.alternate_pack([(obj,body)])
            result[pack]={obj}
        return result

    def batch_transport(self,fault=None):
        from tools.macro_research_checkpoint import RcloneTransport
        remote=RcloneTransport.__new__(RcloneTransport)
        remote.root='gdrive:'
        remote.calls=[];remote.stages=[];remote.inventories=[];remote.completed=[]
        remote.read=self.t.read
        def names(prefix):
            remote.inventories.append(prefix)
            return self.t.names(prefix)
        def call(*args):
            self.assertEqual(args[0:2],('copy','gdrive:'+PREFIX+'/packs'))
            stage=Path(args[2]);remote.stages.append(stage)
            self.assertEqual(list(stage.iterdir()),[])
            listing=Path(args[args.index('--files-from-raw')+1])
            hashes=listing.read_text('ascii').splitlines()
            self.assertEqual(hashes,sorted(set(hashes)))
            self.assertLessEqual(len(hashes),4)
            self.assertIn('--immutable',args);self.assertIn('--checksum',args)
            for key,value in [('--transfers','4'),('--checkers','4'),
                              ('--max-transfer','80M'),('--cutoff-mode','HARD')]:
                self.assertEqual(args[args.index(key)+1],value)
            remote.calls.append(tuple(hashes))
            for sha in reversed(hashes):
                (stage/sha).write_bytes(self.t.read(PREFIX+'/packs/'+sha))
                remote.completed.append(sha)
            if fault:fault(stage,hashes)
            return b''
        remote.names=names;remote.call=call
        return remote

    def test_pack_batch_zero_one_four_five_nine_preserves_fresh_hash_reads(self):
        for count in (0,1,4,5,9):
            with self.subTest(count=count):
                dependencies=self.pack_dependencies(count)
                transport=self.batch_transport();self.lake.transport=transport
                self.lake.verify_pack_dependencies(dependencies)
                self.assertEqual(len(transport.calls),(count+3)//4)
                self.assertEqual(transport.inventories,([PREFIX+'/packs'] if count else []))
                self.assertEqual([sha for group in transport.calls for sha in group],sorted(dependencies))
                self.assertEqual(transport.completed,
                                 [sha for group in transport.calls for sha in reversed(group)])
                self.assertTrue(all(not p.exists() for p in transport.stages))

    def test_pack_batch_and_legacy_restore_same_multi_generation_catalog(self):
        self.put();self.lake.publish('one',{})
        second=Lake(self.t,self.root/'second');self.put(second,90);second.publish('two',{})
        class Legacy:
            remote_verified=False
            def names(_,prefix):return self.t.names(prefix)
            def read(_,path):return self.t.read(path)
        legacy=Lake(Legacy(),self.root/'legacy')
        transport=self.batch_transport();batched=Lake(transport,self.root/'batched')
        self.assertEqual(legacy.parent,batched.parent)
        self.assertEqual(legacy.catalog,batched.catalog)
        self.assertEqual(legacy.get_records('sec/0000000001'),batched.get_records('sec/0000000001'))
        self.assertFalse(any('pack-cache' in str(p) for p in transport.stages))

    def test_pack_batch_invalid_names_and_missing_duplicate_inventory_stop_before_copy(self):
        transport=self.batch_transport()
        for hashes in ([],['../bad'],['a'*64]*2,['g'*64],['a'*64]*5):
            with self.subTest(hashes=hashes),self.assertRaisesRegex(ValueError,'pack_batch_names'):
                with transport.read_pack_batch(hashes,{}):pass
        self.assertEqual(transport.calls,[])
        dependencies=self.pack_dependencies(1);self.lake.transport=transport
        for inventory in ([],list(dependencies)*2):
            with patch.object(transport,'names',return_value=inventory),self.assertRaises(ValueError):
                self.lake.verify_pack_dependencies(dependencies)
        self.assertEqual(transport.calls,[])

    def test_pack_batch_staged_missing_extra_directory_zero_and_oversize_refuse(self):
        from tools import macro_research_checkpoint as checkpoint
        dependencies=self.pack_dependencies(1)
        def fault(kind):
            def change(stage,names):
                p=stage/names[0]
                if kind=='missing':p.unlink()
                elif kind=='extra':(stage/('f'*64)).write_bytes(b'extra')
                elif kind=='directory':p.unlink();p.mkdir()
                elif kind=='zero':p.write_bytes(b'')
                else:
                    with p.open('r+b') as handle:handle.truncate(checkpoint.MAX_OBJECT+1)
            return change
        for kind in ('missing','extra','directory','zero','oversize'):
            with self.subTest(kind=kind):
                transport=self.batch_transport(fault(kind));self.lake.transport=transport
                with self.assertRaises(ValueError):self.lake.verify_pack_dependencies(dependencies)
                self.assertEqual(len(transport.calls),1)
                self.assertTrue(all(not p.exists() for p in transport.stages))
                observation=self.lake.pack_batch_observations[-1]
                self.assertEqual(observation['subprocess_attempts'],1)
                self.assertIsNone(observation['wire_bytes'])
                self.assertGreater(observation['reserved_bytes'],0)

    def test_pack_batch_symlink_guard_and_group_overflow_before_loading(self):
        from tools import macro_research_checkpoint as checkpoint
        dependencies=self.pack_dependencies(1);name=next(iter(dependencies))
        transport=self.batch_transport();self.lake.transport=transport
        original=Path.is_symlink
        with patch.object(Path,'is_symlink',lambda p:
                (p.name==name and p.parent.parent.name.startswith('history-pack-batch-')) or original(p)):
            with self.assertRaisesRegex(ValueError,'pack_batch_file'):
                self.lake.verify_pack_dependencies(dependencies)
        self.assertTrue(all(not p.exists() for p in transport.stages))
        transport=self.batch_transport();self.lake.transport=transport
        with patch.object(checkpoint,'PACK_BATCH_BYTES',1):
            with self.assertRaisesRegex(ValueError,'pack_batch_size'):
                self.lake.verify_pack_dependencies(dependencies)

    def test_pack_batch_corruption_keeps_remote_hash_refusal_and_no_fallback(self):
        dependencies=self.pack_dependencies(1)
        def corrupt(stage,names):(stage/names[0]).write_bytes(b'corrupt')
        transport=self.batch_transport(corrupt);self.lake.transport=transport
        with patch.object(transport,'read',wraps=transport.read) as legacy:
            with self.assertRaisesRegex(ValueError,'remote_hash'):
                self.lake.verify_pack_dependencies(dependencies)
            legacy.assert_not_called()
        self.assertEqual(len(transport.calls),1)
        self.assertTrue(all(not p.exists() for p in transport.stages))

    def test_pack_batch_valid_hash_does_not_bypass_zip_member_and_crc_checks(self):
        import io
        import zipfile
        obj=digest(b'expected')
        missing=self.alternate_pack([(digest(b'other'),b'other')])
        wrong=self.alternate_pack([(obj,b'wrong')])
        duplicate=self.alternate_pack([(obj,b'expected'),(obj,b'expected')])
        invalid=b'not a zip';invalid_hash=digest(invalid)
        self.t.write(PREFIX+'/packs/'+invalid_hash,invalid)
        output=io.BytesIO()
        with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_STORED) as archive:
            archive.writestr(obj,b'expected')
        crc_broken=output.getvalue().replace(b'expected',b'tampered',1)
        crc_hash=digest(crc_broken);self.t.write(PREFIX+'/packs/'+crc_hash,crc_broken)
        for pack,error in ((missing,'pack_dependency'),(wrong,'pack_object_hash'),
                           (duplicate,'pack_inventory'),(invalid_hash,'File is not a zip file'),
                           (crc_hash,'Bad CRC')):
            with self.subTest(error=error):
                transport=self.batch_transport();self.lake.transport=transport
                with self.assertRaisesRegex((ValueError,zipfile.BadZipFile),error):
                    self.lake.verify_pack_dependencies({pack:{obj}})
                self.assertEqual(len(transport.calls),1)
                self.assertTrue(all(not p.exists() for p in transport.stages))

    def test_pack_batch_partial_failure_timeout_cancel_keep_attempt_cost_and_cleanup(self):
        from tools.twelve_private_capture import Refused
        dependencies=self.pack_dependencies(4)
        for exc in (ValueError('research_transport_failed:copy:exit_1:RATE_LIMIT'),
                    TimeoutError('synthetic'),InterruptedError('synthetic'),Refused('synthetic')):
            with self.subTest(exception=type(exc).__name__):
                def fail(stage,names):
                    for name in names[1:]:(stage/name).unlink()
                    raise exc
                transport=self.batch_transport(fail);self.lake.transport=transport
                with self.assertRaises(type(exc)) as caught:self.lake.verify_pack_dependencies(dependencies)
                self.assertIs(caught.exception,exc)
                self.assertEqual(len(transport.calls),1)
                self.assertTrue(all(not p.exists() for p in transport.stages))
                observation=self.lake.pack_batch_observations[-1]
                self.assertGreater(observation['staged_bytes'],0)
                self.assertIsNone(observation['wire_bytes'])
                self.assertEqual(observation['subprocess_attempts'],1)
                self.assertEqual(observation['reserved_bytes'],80*1024*1024)

    def test_pack_batch_cleanup_error_does_not_replace_cancellation(self):
        from tools import macro_research_checkpoint as checkpoint
        from tools.twelve_private_capture import Refused
        dependencies=self.pack_dependencies(1);exc=Refused('original')
        def fail(stage,names):raise exc
        transport=self.batch_transport(fail);self.lake.transport=transport
        original=tempfile.TemporaryDirectory
        class CleanupFailure:
            def __init__(_,**kwargs):_.real=original(**kwargs);_.name=_.real.name
            def cleanup(_):_.real.cleanup();raise OSError('synthetic cleanup')
        with patch.object(checkpoint.tempfile,'TemporaryDirectory',CleanupFailure):
            with self.assertRaises(Refused) as caught:self.lake.verify_pack_dependencies(dependencies)
        self.assertIs(caught.exception,exc)
        self.assertTrue(self.lake.pack_batch_observations[-1]['cleanup_failed'])
        self.assertTrue(all(not p.exists() for p in transport.stages))

    def test_pack_batch_each_boundary_is_fresh_and_does_not_seed_consumption_cache(self):
        dependencies=self.pack_dependencies(1);transport=self.batch_transport();self.lake.transport=transport
        self.lake.verify_pack_dependencies(dependencies);self.lake.verify_pack_dependencies(dependencies)
        self.assertEqual(len(transport.calls),2)
        self.assertEqual(len(set(transport.stages)),2)
        self.assertEqual(transport.inventories,[PREFIX+'/packs']*2)
        self.assertFalse((self.lake.workspace/'pack-cache').exists())
        for pack in dependencies:(self.root/'remote'/PREFIX/'packs'/pack).unlink()
        with self.assertRaises(ValueError):self.lake.verify_pack_dependencies(dependencies)
        self.assertEqual(len(transport.calls),2)

    def test_push_filters_cover_all_consumed_source_paths(self):
        import re
        workflow=(ROOT/'.github/workflows/long_history_research.yml').read_text()
        push=workflow.split('  push:',1)[1].split('  workflow_dispatch:',1)[0]
        paths=set(re.findall(r"^      - '([^']+)'$",push,re.MULTILINE))
        checkout=set(re.findall(r'^            /(.+)$',workflow,re.MULTILINE))
        self.assertFalse(checkout-paths,'Unchecked dependency changes: '+repr(sorted(checkout-paths)))
        self.assertIn('raw,_,_=verified_cohort_source(lake)',workflow)
        self.assertNotIn("old['raw_objects'][0]",workflow)


    def test_sparse_registered_suites_have_complete_isolated_imports(self):
        import os
        import re
        import shutil
        import subprocess
        import textwrap
        workflow=(ROOT/'.github/workflows/long_history_research.yml').read_text()
        paths=re.findall(r'^            /(.+)$',workflow,re.MULTILINE)
        self.assertTrue(paths)
        self.assertEqual(len(paths),len(set(paths)))
        child=textwrap.dedent('''
            import importlib,io,json,pathlib,sys,unittest
            root=pathlib.Path(sys.argv[1]).resolve()
            sys.path[:0]=[str(root/'tests'),str(root)]
            def leaves(suite):
                for test in suite:
                    if isinstance(test,unittest.TestSuite): yield from leaves(test)
                    else: yield test
            counts={}
            for name in ('long_history_lake_smoke','macro_technical_evidence_smoke','macro_research_cycle_smoke'):
                module=importlib.import_module(name)
                cases=list(leaves(unittest.defaultTestLoader.loadTestsFromModule(module)))
                errors=[str(test._exception) for test in cases if isinstance(test,unittest.loader._FailedTest)]
                if errors: raise RuntimeError('sparse_suite_load_failed:'+repr(errors))
                counts[name]=len(cases)
                if name=='long_history_lake_smoke':
                    classes={type(test).__module__+'.'+type(test).__name__ for test in cases}
                    required={'research_data_access_smoke.ReaderTest','a1_reader_generation_binding_smoke.BindingTest'}
                    if not required<=classes: raise RuntimeError('registered_reader_binding_missing')
            # Imports cannot prove dependencies read only when a test executes.
            # Run the real registered case, including its DEFAULT_TESTS AST read.
            binding=importlib.import_module('a1_reader_generation_binding_smoke')
            deferred=unittest.TestSuite([binding.BindingTest(
                'test_registered_lake_loads_reader_and_source_suites_without_duplicate_entries')])
            output=io.StringIO()
            checked=unittest.TextTestRunner(stream=output,verbosity=2).run(deferred)
            if checked.testsRun!=1 or not checked.wasSuccessful():
                raise RuntimeError('sparse_deferred_registry_read_failed:'+output.getvalue())
            for name,module in tuple(sys.modules.items()):
                if name.startswith('tools.') or name.endswith('_smoke'):
                    origin=getattr(module,'__file__',None)
                    if origin and not pathlib.Path(origin).resolve().is_relative_to(root):
                        raise RuntimeError('full_checkout_fallback:'+name)
            print(json.dumps(counts,sort_keys=True))
        ''')
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            baseline=root/'complete';baseline.mkdir()
            for name in paths:
                self.assertRegex(name,r'^[A-Za-z0-9_./-]+$')
                self.assertNotIn('..',Path(name).parts)
                source_path=ROOT/name
                self.assertTrue(source_path.is_file(),name)
                target=baseline/name;target.parent.mkdir(parents=True,exist_ok=True)
                target.write_bytes(source_path.read_bytes())
            guard=root/'guard';guard.mkdir()
            (guard/'sitecustomize.py').write_text(
                'import socket\nfrom pathlib import Path\n'
                'def denied(*args,**kwargs):\n'
                '    Path(__file__).with_name("network-attempt.log").write_text("blocked\\n")\n'
                '    raise RuntimeError("SPARSE_LOAD_NETWORK_FORBIDDEN")\n'
                'socket.socket.connect=denied\nsocket.socket.connect_ex=denied\n'
                'socket.create_connection=denied\n')
            env=os.environ.copy()
            for name in tuple(env):
                if re.search(r'TOKEN|SECRET|PASSWORD|CREDENTIAL|API_KEY|ACCESS_KEY|SERVICE_ACCOUNT|RCLONE|DRIVE|ALPACA|FRED',name,re.I):
                    env.pop(name)
            env.update(PYTHONPATH=str(guard),PYTHONDONTWRITEBYTECODE='1',
                OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',MKL_NUM_THREADS='1',NUMEXPR_NUM_THREADS='1')
            flags=['-O'] if sys.flags.optimize else []
            def load(where):
                result=subprocess.run([sys.executable,*flags,'-B','-c',child,str(where)],
                    cwd=where,env=env,capture_output=True,text=True,timeout=60)
                self.assertLessEqual(len(result.stdout)+len(result.stderr),32768)
                self.assertFalse((guard/'network-attempt.log').exists())
                return result
            positive=load(baseline)
            self.assertEqual(positive.returncode,0,positive.stderr)
            self.assertEqual(set(json.loads(positive.stdout)),
                {'long_history_lake_smoke','macro_technical_evidence_smoke','macro_research_cycle_smoke'})
            # Module import alone cannot prove deferred runtime file reads.
            # Execute the actual portable macro suite in the declared checkout.
            macro_command=[sys.executable,*flags,'-B','tests/macro_technical_evidence_smoke.py']
            macro=subprocess.run(macro_command,cwd=baseline,env=env,
                                 capture_output=True,text=True,timeout=60)
            self.assertLessEqual(len(macro.stdout)+len(macro.stderr),32768)
            self.assertFalse((guard/'network-attempt.log').exists())
            self.assertEqual(macro.returncode,0,macro.stdout+macro.stderr)
            self.assertEqual([int(n) for n in re.findall(r'Ran (\d+) tests?',macro.stderr)],
                             [json.loads(positive.stdout)['macro_technical_evidence_smoke']])
            missing_contract=root/'missing-a4-contract';shutil.copytree(baseline,missing_contract)
            (missing_contract/'docs/run287_chameleon_macro_inputs_contract.json').unlink()
            refused=subprocess.run(macro_command,cwd=missing_contract,env=env,
                                   capture_output=True,text=True,timeout=60)
            self.assertNotEqual(refused.returncode,0)
            self.assertIn('run287_chameleon_macro_inputs_contract.json',refused.stderr)
            self.assertFalse((guard/'network-attempt.log').exists())
            if os.name=='posix':
                import atexit
                completed=subprocess.run([sys.executable,*flags,'-B','tests/macro_research_cycle_smoke.py'],
                    cwd=baseline,env=env,capture_output=True,text=True,timeout=60)
                self.assertLessEqual(len(completed.stdout)+len(completed.stderr),32768)
                self.assertFalse((guard/'network-attempt.log').exists())
                self.assertEqual(completed.returncode,0,completed.stdout+completed.stderr)
                expected=json.loads(positive.stdout)['macro_research_cycle_smoke']
                ran=re.findall(r'Ran (\d+) tests?',completed.stderr)
                self.assertEqual([int(value) for value in ran],[expected])
                self.assertNotIn('skipped=',completed.stderr)
                # The existing CI runner retains each smoke's last stdout line.
                atexit.register(print,'LONG_HISTORY_ISOLATED_POSIX_MACRO_CYCLE_PASS tests='+str(expected)+
                    ' optimize='+str(sys.flags.optimize)+' sparse_paths='+str(len(paths))+
                    ' network_attempts=0',flush=True)
            for omitted,module in (
                ('tests/a1_reader_generation_binding_smoke.py','a1_reader_generation_binding_smoke'),
                ('tools/twelve_private_capture.py','twelve_private_capture'),
                ('tools/run_pr_validation.py','run_pr_validation'),
            ):
                with self.subTest(omitted=omitted):
                    case=root/module;shutil.copytree(baseline,case)
                    (case/omitted).unlink()
                    failure=load(case)
                    self.assertNotEqual(failure.returncode,0)
                    self.assertIn(module,failure.stderr)
            trigger=root/'missing-push-path';shutil.copytree(baseline,trigger)
            config=trigger/'.github/workflows/long_history_research.yml'
            needle="      - 'tools/twelve_private_capture.py'\n"
            self.assertEqual(workflow.count(needle),1)
            config.write_text(workflow.replace(needle,''))
            with patch(__name__+'.ROOT',trigger):
                with self.assertRaisesRegex(AssertionError,'Unchecked dependency changes'):
                    self.test_push_filters_cover_all_consumed_source_paths()



class ScopedAlfredTest(unittest.TestCase):
    """Offline scoped-source and causal date-vintage boundaries."""
    def setUp(self):
        import io
        from contextlib import redirect_stdout
        from tools import long_history_lake as h
        self.h=h
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name); self.transport=LocalTransport(self.root/'remote')
        self.output=io.StringIO()
        with redirect_stdout(self.output):
            lake=Lake(self.transport,self.root/'initial')
            for sid in ('M2SL','WALCL','CPIAUCSL','UNRATE'):
                lake.dataset('alfred/'+sid,[b'original-'+sid.encode()],
                    [self.row('2021-01-05',10,series=sid)],
                    dict(rows=1,evidence='alfred_date_archive',requested_through='2021-01-15'))
            lake.dataset('current/SP500',[b'price'],[dict(value=1)],dict(rows=1,evidence='current_only'))
            lake.dataset('sec/0000000001',[b'financial'],[dict(value=2)],dict(rows=1))
            lake.publish('old',dict(macro_start='2020-01-01',financial_start='2016-01-01',
                through='2021-01-15',registry_sha256=digest(encoded(h.registry()))))
            self.lake=Lake(self.transport,self.root/'restored')
        self.before=copy.deepcopy(self.lake.catalog['datasets'])

    @staticmethod
    def row(vintage,value,end='9999-12-31',observed='2020-12-01',series='DGS10'):
        from datetime import date,timedelta
        from zoneinfo import ZoneInfo
        day=date.fromisoformat(vintage)
        available=datetime.combine(day+timedelta(days=1),datetime.min.time(),
            ZoneInfo('America/New_York')).astimezone(timezone.utc)
        return dict(series=series,observation_date=observed,vintage_date=vintage,
            realtime_end=end,available_at=available.isoformat(),published_at=None,
            evidence='alfred_date_archive',value=value)

    def request(self,ids=None):
        ids=ids or ['DGS10']
        return dict(schema='long-history-scoped-alfred-v1',request_id='synthetic-only',
            mode='alfred_missing_only',series=ids,observation_start='2020-01-01',through='2021-01-15',
            expected_parent=self.lake.parent,expected_catalog=digest(encoded(self.lake.before)),
            registry_sha256=digest((ROOT/'docs/macro_indicator_registry.json').read_bytes()),
            budget=dict(provider_gets=20*len(ids),provider_bytes=20*(16*1024*1024+1)*len(ids),pages_per_series=20))

    def fetch(self,sid,start,through,mode):
        self.assertEqual(mode,'alfred')
        raw=encoded(dict(units='lin',output_type=1,offset=0,count=1,observations=[
            dict(date='2020-12-01',realtime_start='2021-01-05',realtime_end='9999-12-31',value='3')]))
        return [raw],'2021-01-16T12:00:00+00:00'

    def test_exact_three_metadata_and_old_registry_entries_preserved(self):
        specs={s['id']:s for s in self.h.registry()['series']}
        self.assertEqual(len(specs),37)
        for sid in ('CPILFESL','PPIFDG','SAHMREALTIME'):
            self.assertEqual(specs[sid]['collection_scope'],'scoped_alfred_only')
            self.assertEqual(specs[sid]['frequency'],'monthly')
            self.assertEqual(specs[sid]['initial_inference'],'SHADOW_ONLY')
            self.assertEqual(specs[sid]['raw_redistribution'],'source_terms_review_required')
        self.assertEqual(specs['PPIFDG']['seasonal_adjustment'],'Not Seasonally Adjusted')
        self.assertEqual(specs['SAHMREALTIME']['unit'],'percentage_points')

    def test_manifest_hash_duplicate_unknown_mode_budget_and_window_refused_before_fetch(self):
        raw=encoded(self.request())
        with patch.object(self.h,'fetch_fred',side_effect=AssertionError('network forbidden')) as fetch:
            self.assertEqual(self.h.scoped_alfred_request(raw,digest(raw)),self.request())
            with self.assertRaisesRegex(ValueError,'scoped_request_hash'):
                self.h.scoped_alfred_request(raw,'0'*64)
            duplicate=raw.rstrip()[:-1]+b',"mode":"alfred_missing_only"}'
            with self.assertRaisesRegex(ValueError,'duplicate_key'):
                self.h.scoped_alfred_request(duplicate,digest(duplicate))
            cases=[('mode','current'),('series',['UNKNOWN']),('series',['M2SL']),
                ('series',['DGS10','DGS10']),('through','9999-01-01'),('expected_parent',None),
                ('registry_sha256','0'*64),('extra','not allowed')]
            for key,value in cases:
                request=self.request(); request[key]=value
                with self.subTest(key=key,value=value),self.assertRaises(ValueError):
                    self.h.collect_scoped_alfred(self.lake,request)
            for key,value in [('provider_gets',19),('provider_bytes',335544320),
                              ('pages_per_series',1),('provider_gets',True)]:
                request=self.request(); request['budget'][key]=value
                with self.subTest(budget=key),self.assertRaises(ValueError):
                    self.h.collect_scoped_alfred(self.lake,request)
            fetch.assert_not_called()

    def test_missing_only_fetches_exact_alfred_and_preserves_all_old_entries(self):
        from contextlib import redirect_stdout
        with redirect_stdout(self.output),patch.object(self.h,'fetch_fred',side_effect=self.fetch) as fetch, \
             patch.object(self.h,'collect_financials',side_effect=AssertionError('SEC forbidden')), \
             patch.object(self.h,'get_public',side_effect=AssertionError('public fetch forbidden')):
            meter=self.h.collect_scoped_alfred(self.lake,self.request(['CPILFESL','PPIFDG','SAHMREALTIME']))
            self.assertEqual([c.args[0] for c in fetch.call_args_list],['CPILFESL','PPIFDG','SAHMREALTIME'])
            self.assertTrue(all(c.args[-1]=='alfred' for c in fetch.call_args_list))
            self.assertEqual(meter['returned_pages'],3)
            self.assertEqual(meter['reserved_provider_gets'],60)
            self.assertEqual(meter['reserved_provider_bytes'],60*(16*1024*1024+1))
            for key,value in self.before.items():
                self.assertEqual(self.lake.catalog['datasets'][key],value)
            parent=self.lake.parent
            result=self.lake.publish('scoped',dict(self.lake.before['config'],scoped=True))
            commit=json.loads(self.lake.read_hash('commits',result['commit_sha256']))
            self.assertEqual(commit['parent'],parent)
            restored=Lake(self.transport,self.root/'consumer')
            for key,value in self.before.items():
                self.assertEqual(restored.catalog['datasets'][key],value)
            self.assertEqual(restored.get_records('alfred/PPIFDG')[0]['value'],3)
            with self.assertRaisesRegex(ValueError,'execution_receipt_missing'):
                restored.verified_execution()

    def test_parent_catalog_and_existing_key_refuse_before_provider(self):
        from contextlib import redirect_stdout
        with patch.object(self.h,'fetch_fred',side_effect=AssertionError('forbidden')) as fetch:
            for key in ('expected_parent','expected_catalog'):
                request=self.request();request[key]='0'*64
                with self.assertRaisesRegex(ValueError,'scoped_parent_mismatch'):
                    self.h.collect_scoped_alfred(self.lake,request)
            with redirect_stdout(self.output):
                self.lake.dataset('alfred/DGS10',[b'held'],[self.row('2021-01-05',1)],dict(rows=1))
                self.lake.publish('held',self.lake.before['config'])
                self.lake=Lake(self.transport,self.root/'held-consumer')
            request=self.request()
            with self.assertRaisesRegex(ValueError,'already_present'):
                self.h.collect_scoped_alfred(self.lake,request)
            fetch.assert_not_called()

    def test_remote_stale_parent_refuses_before_provider(self):
        from contextlib import redirect_stdout
        request=self.request()
        with redirect_stdout(self.output):
            peer=Lake(self.transport,self.root/'peer')
            peer.publish('peer',self.lake.before['config'])
            with patch.object(self.h,'fetch_fred') as fetch:
                with self.assertRaisesRegex(ValueError,'scoped_parent_mismatch'):
                    self.h.collect_scoped_alfred(self.lake,request)
                fetch.assert_not_called()

    def test_provider_error_429_page_and_parser_failures_never_publish_or_retry(self):
        from contextlib import redirect_stdout
        from urllib.error import HTTPError
        secret='https://invalid.test/?api_key=PRIVATE_SENTINEL'
        errors=[HTTPError(secret,429,secret,None,None),OSError(secret)]
        for error in errors:
            with self.subTest(error=type(error).__name__),redirect_stdout(self.output), \
                 patch.object(self.h,'fetch_fred',side_effect=error) as fetch:
                with self.assertRaisesRegex(ValueError,'scoped_alfred_collection_blocked'):
                    self.h.collect_scoped_alfred(self.lake,self.request())
                self.assertEqual(fetch.call_count,1)
                self.assertEqual(len(self.transport.names(PREFIX+'/commits')),1)
                self.assertEqual(self.lake.catalog['datasets'],self.before)
        self.assertNotIn('PRIVATE_SENTINEL',self.output.getvalue())
        self.assertIn('reserved_provider_gets',self.output.getvalue())
        for pages in ([b'{}']*21,[b'{}']):
            with self.subTest(pages=len(pages)),redirect_stdout(self.output), \
                 patch.object(self.h,'fetch_fred',return_value=(pages,'2021-01-16T00:00:00Z')):
                with self.assertRaisesRegex(ValueError,'scoped_alfred_collection_blocked'):
                    self.h.collect_scoped_alfred(self.lake,self.request())
                self.assertEqual(len(self.transport.names(PREFIX+'/commits')),1)

    def test_cancellation_keeps_full_reservation_and_propagates(self):
        from contextlib import redirect_stdout
        for error in (TimeoutError('deadline'),InterruptedError('cancel'),self.h.Refused('CAMPAIGN_DEADLINE')):
            with self.subTest(error=type(error).__name__),redirect_stdout(self.output), \
                 patch.object(self.h,'fetch_fred',side_effect=error):
                with self.assertRaises(type(error)):
                    self.h.collect_scoped_alfred(self.lake,self.request())
        self.assertEqual(len(self.transport.names(PREFIX+'/commits')),1)

    def test_default_full_collection_keeps_original_series_and_archive_set(self):
        with patch.object(self.h,'fetch_fred_retry',side_effect=ValueError('synthetic')) as fetch, \
             patch.object(self.h,'get_public',side_effect=ValueError('synthetic')):
            self.h.collect_macros(self.lake,'2020-01-01','2021-01-15')
        self.assertEqual({c.args[0] for c in fetch.call_args_list if c.args[-1]=='alfred'},set(self.h.ARCHIVES))
        current={c.args[0] for c in fetch.call_args_list if c.args[-1]=='current'}
        self.assertEqual(len(current),34)
        self.assertFalse(current & {'CPILFESL','PPIFDG','SAHMREALTIME'})

    def test_future_revision_shortened_end_cannot_erase_earlier_feature(self):
        old=self.row('2021-01-05',10)
        amended=dict(old,realtime_end='2021-01-07')
        future=self.row('2021-01-08',20)
        for cutoff in ('2021-01-06T05:00:00Z','2021-01-08T17:00:00Z'):
            before=self.h.project_alfred_versions([old],cutoff,'2021-01-15')
            after=self.h.project_alfred_versions([amended,future],cutoff,'2021-01-15')
            self.assertEqual(before['records'],after['records'])
            self.assertEqual(after['records'][0]['value'],10)
        eligible=self.h.project_alfred_versions([amended,future],'2021-01-09T05:00:00Z','2021-01-15')
        self.assertEqual(eligible['records'][0]['value'],20)
        self.assertFalse(eligible['historical_pit_certified'])

    def test_each_historical_feature_row_uses_its_own_cutoff_without_provider(self):
        rows=[self.row('2021-01-05',10,end='2021-01-07'),self.row('2021-01-08',20)]
        cutoffs=['2021-01-06T05:00:00Z','2021-01-08T17:00:00Z','2021-01-09T05:00:00Z']
        with patch.object(self.h,'fetch_fred',side_effect=AssertionError('no provider')) as fetch:
            features=[self.h.project_alfred_versions(rows,d,'2021-01-15')['records'][0]['value'] for d in cutoffs]
            self.assertEqual(features,[10,10,20])
            fetch.assert_not_called()
        # A single latest projection would broadcast20 into both earlier rows.
        self.assertNotEqual(features,[features[-1]]*len(features))

    def test_withdrawal_preserved_only_at_conservative_successor_boundary(self):
        rows=[self.row('2021-01-05',10,end='2021-01-07'),self.row('2021-01-08',None)]
        before=self.h.project_alfred_versions(rows,'2021-01-09T04:59:59Z','2021-01-15')
        after=self.h.project_alfred_versions(rows,'2021-01-09T05:00:00Z','2021-01-15')
        self.assertEqual(before['records'][0]['value'],10)
        self.assertIsNone(after['records'][0]['value'])

    def test_new_york_midnight_dst_and_strict_prior_day(self):
        for vintage,boundary,before in [('2021-03-13','2021-03-14T05:00:00Z','2021-03-14T04:59:59Z'),
                ('2021-03-14','2021-03-15T04:00:00Z','2021-03-15T03:59:59Z'),
                ('2021-11-06','2021-11-07T04:00:00Z','2021-11-07T03:59:59Z'),
                ('2021-11-07','2021-11-08T05:00:00Z','2021-11-08T04:59:59Z')]:
            rows=[self.row(vintage,1)]
            with self.subTest(vintage=vintage):
                self.assertEqual(self.h.project_alfred_versions(rows,before,'2021-11-09')['records'],[])
                self.assertEqual(len(self.h.project_alfred_versions(rows,boundary,'2021-11-09')['records']),1)

    def test_later_created_sahm_history_is_not_published_before_first_vintage(self):
        row=self.row('2019-10-01',0.1,observed='2000-01-01',series='SAHMREALTIME')
        result=self.h.project_alfred_versions([row],'2016-01-01T21:00:00Z','2021-01-15')
        self.assertEqual(result['status'],'NO_ELIGIBLE_VINTAGE')
        self.assertEqual(result['records'],[])

    def test_unknown_clocks_missing_values_and_incomplete_archives_refused(self):
        row=self.row('2021-01-05',1)
        for change in ({'available_at':'2021-01-05T12:00:00Z'}, {'published_at':'2021-01-05T12:00:00Z'},
                       {'evidence':'current_only'}, {'value':float('nan')}, {'value':True}):
            with self.subTest(change=change),self.assertRaises(ValueError):
                self.h.project_alfred_versions([dict(row,**change)],'2021-01-09T05:00:00Z','2021-01-15')
        missing=dict(row); missing.pop('value')
        with self.assertRaises(ValueError):
            self.h.project_alfred_versions([missing],'2021-01-09T05:00:00Z','2021-01-15')
        with self.assertRaisesRegex(ValueError,'incomplete_asof'):
            self.h.project_alfred_versions([row],'2021-01-09T05:00:00Z','2021-01-07')
        with self.assertRaisesRegex(ValueError,'decision_clock'):
            self.h.project_alfred_versions([row],'2021-01-09','2021-01-15')
        with self.assertRaisesRegex(ValueError,'duplicate_vintage'):
            self.h.project_alfred_versions([row,row],'2021-01-09T05:00:00Z','2021-01-15')

    def test_lake_projection_requires_actual_execution_and_correct_series(self):
        with self.assertRaisesRegex(ValueError,'execution_receipt_missing'):
            self.h.project_alfred_asof(self.lake,'M2SL','2021-01-09T05:00:00Z')
        with patch.object(self.lake,'verified_execution',return_value={'execution_receipt_sha256':'a'*64,
                'study_recomputed_from_drive':False}):
            with self.assertRaisesRegex(ValueError,'alfred_execution_incomplete'):
                self.h.project_alfred_asof(self.lake,'M2SL','2021-01-09T05:00:00Z')
        with patch.object(self.lake,'verified_execution',return_value={'execution_receipt_sha256':'a'*64,
                'study_recomputed_from_drive':True}):
            result=self.h.project_alfred_asof(self.lake,'M2SL','2021-01-09T05:00:00Z')
            self.assertEqual(result['source_commit'],self.lake.parent)
            self.assertEqual(result['records'][0]['series'],'M2SL')
            self.assertFalse(result['historical_pit_certified'])
            with patch.object(self.lake,'get_records',return_value=[self.row('2021-01-05',1)]):
                with self.assertRaisesRegex(ValueError,'alfred_archive_series'):
                    self.h.project_alfred_asof(self.lake,'M2SL','2021-01-09T05:00:00Z')

    def test_old_bundle_remains_readable_with_its_original_registry_snapshot(self):
        from tools import macro_history_sources as m
        legacy=copy.deepcopy(m.registry())
        legacy['series']=[s for s in legacy['series'] if s.get('collection_scope')!='scoped_alfred_only']
        original=encoded(legacy)
        path=self.root/'original-registry.json'; path.write_bytes(original)
        store=self.root/'bundle'
        with patch.object(m,'REGISTRY',path):
            receipt,receipt_path=m.collect(store,['M2SL'],'2020-01-01','2021-01-15','alfred',self.fetch)
        self.assertEqual(receipt['registry_sha256'],digest(original))
        _,rows=m.load_bundle(store,receipt_path,registry_raw=original)
        self.assertEqual(rows['M2SL'][0]['value'],3)
        with self.assertRaisesRegex(ValueError,'registry_changed'):
            m.load_bundle(store,receipt_path)

    def test_invalid_cli_scope_refused_before_transport_or_reports(self):
        request=self.root/'invalid.json';request.write_bytes(b'{}')
        args=['long_history_lake','--remote','synthetic','--workspace',str(self.root/'cli'),
            '--cohort','unused','--run-id','synthetic','--report-dir',str(self.root/'reports'),
            '--scoped-alfred-request',str(request),'--scoped-alfred-request-sha256','0'*64]
        with patch.object(sys,'argv',args),patch.object(self.h,'RcloneTransport') as transport:
            with self.assertRaisesRegex(ValueError,'scoped_request_hash'):
                self.h.main()
            transport.assert_not_called()
        self.assertFalse((self.root/'reports').exists())

    def test_scoped_cli_reuses_real_publish_without_full_collector(self):
        from contextlib import redirect_stdout
        request=self.root/'request.json';raw=encoded(self.request());request.write_bytes(raw)
        args=['long_history_lake','--remote','synthetic','--workspace',str(self.root/'cli'),
            '--cohort','unused-do-not-open','--run-id','scoped-cli','--report-dir',str(self.root/'reports'),
            '--scoped-alfred-request',str(request),'--scoped-alfred-request-sha256',digest(raw)]
        with redirect_stdout(self.output),patch.object(sys,'argv',args), \
             patch.object(self.h,'RcloneTransport',return_value=self.transport), \
             patch.object(self.transport,'call',create=True),patch.object(self.transport,'path',create=True), \
             patch.object(self.h,'fetch_fred',side_effect=self.fetch), \
             patch.object(self.h,'collect_macros',side_effect=AssertionError('broad collection forbidden')), \
             patch.object(self.h,'collect_financials',side_effect=AssertionError('SEC forbidden')), \
             patch.object(self.h,'complete_consumer',return_value=0) as complete:
            self.assertEqual(self.h.main(),0)
            complete.assert_called_once()
            self.assertEqual(complete.call_args.kwargs['through'],'2021-01-15')
            restored=Lake(self.transport,self.root/'cli-consumer')
        self.assertIn('alfred/DGS10',restored.catalog['datasets'])
        self.assertEqual(restored.catalog['config']['scoped_alfred_request_sha256'],digest(raw))
        for key,value in self.before.items():
            self.assertEqual(restored.catalog['datasets'][key],value)


def load_tests(loader, tests, pattern):
    # Keep the existing registered Tier-1 entry; avoid the shared runner/P0 lane.
    from research_model_inputs_smoke import ModelInputsTest
    tests.addTests(loader.loadTestsFromTestCase(ModelInputsTest))
    from research_data_access_smoke import ReaderTest
    tests.addTests(loader.loadTestsFromTestCase(ReaderTest))
    from a1_reader_generation_binding_smoke import BindingTest
    tests.addTests(loader.loadTestsFromTestCase(BindingTest))
    return tests


class HybridHistoryTest(unittest.TestCase):
    """Synthetic contracts and immutable LocalTransport; no real Source inputs."""
    def setUp(self):
        from tools import long_history_lake as h
        self.h=h
        self.tmp=self.enterContext(tempfile.TemporaryDirectory())
        self.root=Path(self.tmp); self.t=LocalTransport(self.root/'remote')
        self.now=datetime(2026,10,24,0,30,tzinfo=timezone.utc)
        self.enterContext(patch.object(h,'utc_now',return_value=self.now.isoformat()))
        self.enterContext(patch.dict('os.environ',{'GITHUB_SHA':'a'*40}))
        self.members=[dict(ticker='AAPL'),dict(ticker='MSFT')]+[dict(ticker='S'+str(i)) for i in range(998)]
        self.cohort=encoded(dict(candidate_count=len(self.members),as_of='2026-10-01',rows=self.members))
        self.enterContext(patch.object(h,'COHORT_SHA',digest(self.cohort)))
        self.mapping=encoded({str(i):dict(ticker=row['ticker'],cik_str=1 if i==0 else 2)
                              for i,row in enumerate(self.members)})
        lake=Lake(self.t,self.root/'first')
        lake.dataset('universe/cohort',[self.cohort,self.mapping],self.members,dict(
            evidence='CURRENT_COHORT_NOT_HISTORICAL_MEMBERSHIP',rows=1000,requested_securities=1000,
            cohort_source_object_sha256=digest(h.packed(self.cohort)),
            sec_ticker_mapping_object_sha256=digest(h.packed(self.mapping)),
            sec_ticker_mapping_source_sha256=digest(self.mapping),
            sec_ticker_mapping_retrieved_at='2026-10-01T00:00:00Z',
            source_role_contract_version='cohort-sec-mapping-v1',
            historical_sec_mapping_object_sha256s=[digest(h.packed(self.mapping))],
            collection_issuer_keys=['sec/0000000001','sec/0000000002'],
            current_mapping_issuer_keys=['sec/0000000001','sec/0000000002'],
            history_retained_issuer_keys=[],missing=[],lifecycle_review_count=0))
        for cik in (1,2):
            body=source(); body['cik']=cik; raw=encoded(body)
            rows,rejected=h.sec_rows(raw,str(cik).zfill(10),'2016-01-01','2026-10-22')
            lake.dataset('sec/'+str(cik).zfill(10),[raw],rows,dict(cik=str(cik).zfill(10),
                tickers=['AAPL' if cik==1 else 'MSFT'],start='2016-01-01',through='2026-10-22',
                http=dict(etag='fixture',last_modified=None),deferred_until=None,
                extraction_sha256=h.extraction_identity(),retrieved_at='2026-10-01T00:00:00Z',
                evidence='SEC_FILED_DATE_CURRENT_ARCHIVE_NOT_CERTIFIED_PIT',rejected_rows=rejected,
                **h.fact_coverage(rows,'2016-01-01','2026-10-22')))
        for prefix,ids in (('current',[s['id'] for s in h.registry()['series']
                                      if s.get('collection_scope')!='scoped_alfred_only']),
                           ('alfred',h.ARCHIVES),('worldbank',h.WB_INDICATORS)):
            for sid in ids:
                row=dict(series=sid,observation_date='2026-10-22',value=1.0)
                lake.dataset(prefix+'/'+sid,[encoded(dict(fixture=prefix,series=sid))],[row],dict(
                    rows=1,earliest='2026-10-22',latest='2026-10-22',retrieved_at='2026-10-01T00:00:00Z',
                    evidence='alfred_date_archive' if prefix=='alfred' else 'current_only'))
        self.config=dict(macro_start='1996-01-01',financial_start='2016-01-01',through='2026-10-22',
            cohort_sha256=h.COHORT_SHA,archives=list(h.ARCHIVES),countries=list(h.COUNTRIES),
            worldbank_indicators=list(h.WB_INDICATORS),registry_sha256=digest(encoded(h.registry())))
        result=lake.publish('synthetic_hybrid_baseline',self.config)
        self.lake=Lake(self.t,self.root/'reader')
        self.baseline=dict(commit=result['commit_sha256'],catalog=result['catalog_sha256'],
                           execution=self.receipt(self.lake,result))

    def receipt(self,lake,result,summary=None):
        q=self.h.diagnostics(lake)
        if summary is not None:
            q.update(status='PARTIAL_COVERAGE',cycle_scope=summary)
        qraw=encoded(q); qsha=digest(qraw); self.t.write(PREFIX+'/reports/'+qsha,qraw)
        e=dict(schema='long-history-execution-v1',run_id=lake.catalog['run_id'],
            created_at=self.now.isoformat(),catalog_sha256=result['catalog_sha256'],
            commit_sha256=result['commit_sha256'],reports={'quality.json':qsha},
            consumer_rows=0,study_recomputed_from_drive=True,quality_status=q['status'],eligible_for_selector=False)
        if summary is not None: e['cycle_scope']=summary
        raw=encoded(e); sha=digest(raw); self.t.write(PREFIX+'/executions/'+sha,raw)
        return sha

    def request(self,mode='HYBRID_DAILY'):
        return dict(schema='long-history-hybrid-v1',request_id='synthetic-hybrid-only',mode=mode,
            purpose='PRIVATE_NONCOMMERCIAL_RESEARCH',code_sha='a'*40,
            registry_sha256=digest(encoded(self.h.registry())),roster_sha256='b'*64,
            cohort_sha256=self.h.COHORT_SHA,mapping_object_sha256=digest(self.h.packed(self.mapping)),
            mapping_source_sha256=digest(self.mapping),focus_pairs=[dict(ticker='AAPL',cik='0000000001')],
            baseline=dict(self.baseline),macro_start='1996-01-01',financial_start='2016-01-01',
            through='2026-10-23',decision_at=self.now.isoformat(),available_at='2026-10-23T20:01:00Z',
            not_before='2026-10-23T00:00:00Z',expires_at='2026-10-25T00:00:00Z',
            weekly=None if mode=='HYBRID_DAILY' else dict(week_start='2026-10-19',session='2026-10-23'),
            rights_sha256=dict(fred='c'*64,sec='d'*64,worldbank='e'*64),
            budget=dict(provider_gets=2000,provider_bytes=100*1024**3,transport_calls=2000,
                transport_reserved_bytes=100*1024**3,write_bytes=1024**3,active_seconds=7200,
                max_chain_commits=32,max_issuers=10))

    def scope(self,r=None,request_hash=None):
        r=self.request() if r is None else r
        raw=encoded(r); sha=digest(raw) if request_hash is None else request_hash
        self.h.hybrid_request(raw,sha,r['mode'],now=self.now)
        budget=self.h.HybridBudget(r,live_transport=False)
        return self.h.prepare_hybrid_scope(self.lake,r,sha,budget,dict(fixture_only=True))

    def run_daily(self,scope):
        def fetch(sid,start,through,mode):
            return [encoded(dict(fixture_only=True,series=sid))],self.now.isoformat()
        def rows(pages,sid,start,through,retrieved):
            return [dict(series=sid,observation_date=through,value=2.0)],[]
        with patch.object(self.h,'fetch_fred_retry',side_effect=fetch), \
             patch.object(self.h,'parse_current',side_effect=rows), \
             patch.object(self.h,'get_public',side_effect=lambda url,conditional=None:(None,conditional)):
            self.h.collect_macros(self.lake,'1996-01-01','2026-10-23',_hybrid=scope)
            self.h.collect_financials(self.lake,'unused','2016-01-01','2026-10-23',_hybrid=scope)

    def test_request_rejects_missing_unknown_duplicate_future_and_insufficient_scope(self):
        for key,bad,reason in (('purpose','TRAINING','hybrid_request_fields'),
                ('code_sha','f'*40,'NEEDS_REBIND'),('expires_at','2026-10-23T00:00:00Z','hybrid_window'),
                ('through','2026-10-22','hybrid_daily_session')):
            r=self.request(); r[key]=bad; raw=encoded(r)
            with self.subTest(key=key),self.assertRaisesRegex(ValueError,reason):
                self.h.hybrid_request(raw,digest(raw),r['mode'],now=self.now)
        r=self.request(); r['focus_pairs']*=2
        with self.assertRaisesRegex(ValueError,'hybrid_focus_duplicate'): self.scope(r)
        r=self.request(); r['budget']['provider_gets']=1
        with self.assertRaisesRegex(ValueError,'hybrid_provider_budget_preflight'): self.scope(r)

    def test_focus_ciK_proof_and_ambiguous_mapping_fail_before_provider(self):
        r=self.request(); r['focus_pairs'][0]['cik']='0000000002'
        with patch.object(self.h,'get_public',side_effect=AssertionError('provider')):
            with self.assertRaisesRegex(ValueError,'hybrid_ticker_cik_proof'): self.scope(r)
        original=self.h.sec_ticker_lookup
        with patch.object(self.h,'sec_ticker_lookup',side_effect=lambda m:dict(original(m),AAPL={'0000000001','0000000002'})):
            with self.assertRaisesRegex(ValueError,'hybrid_ticker_cik_proof'): self.scope()

    def test_existing_ticker_class_normalization_keeps_unique_issuer_proof(self):
        r=self.request(); r['focus_pairs']=[dict(ticker='AAP.L',cik='0000000001')]
        original=self.h.sec_ticker_lookup
        with patch.object(self.h,'verified_cohort_source',return_value=(
                encoded(dict(candidate_count=1000,rows=[dict(ticker='AAP-L')]+self.members[1:])),
                r['mapping_object_sha256'],json.loads(self.mapping))), \
             patch.object(self.h,'sec_ticker_lookup',side_effect=lambda m:dict(original(m),**{'AAP-L':{'0000000001'}})):
            scope=self.scope(r)
        self.assertEqual(scope['selected'],{'0000000001'})

    def test_daily_sec_queries_only_focus_and_preserves_unchecked_whole_entry(self):
        scope=self.scope(); before=copy.deepcopy(self.lake.catalog['datasets'])
        urls=[]
        def public(url,conditional=None):
            urls.append(url); self.assertEqual(conditional.get('etag'),'fixture')
            return None,conditional
        with patch.object(self.h,'get_public',side_effect=public):
            self.h.collect_financials(self.lake,'unused',scope['request']['financial_start'],
                                     scope['request']['through'],_hybrid=scope)
        self.assertEqual(urls,['https://data.sec.gov/api/xbrl/companyfacts/CIK0000000001.json'])
        self.assertEqual(self.lake.catalog['datasets']['sec/0000000001']['status'],'UNCHANGED')
        self.assertEqual(self.lake.catalog['datasets']['sec/0000000002'],before['sec/0000000002'])
        self.assertEqual(self.lake.catalog['datasets']['universe/cohort'],before['universe/cohort'])

    def test_daily_macro_checks_current34_only_and_keeps_vintage_worldbank_clocks(self):
        scope=self.scope(); before=copy.deepcopy(self.lake.catalog['datasets']); calls=[]
        def fetch(sid,start,through,mode):
            calls.append((mode,sid)); return [encoded(dict(sid=sid))],self.now.isoformat()
        def current(pages,sid,*args):
            return [dict(series=sid,observation_date='2026-10-22',value=2.0)],[]
        with patch.object(self.h,'fetch_fred_retry',side_effect=fetch), \
             patch.object(self.h,'parse_current',side_effect=current), \
             patch.object(self.h,'get_public',side_effect=AssertionError('worldbank')):
            self.h.collect_macros(self.lake,'1996-01-01','2026-10-23',_hybrid=scope)
        self.assertEqual(len(calls),34); self.assertEqual({mode for mode,_ in calls},{'current'})
        for key in before:
            if key.startswith(('alfred/','worldbank/')): self.assertEqual(self.lake.catalog['datasets'][key],before[key])

    def test_weekly_scope_selects_full_original_groups_and_due_archives(self):
        scope=self.scope(self.request('HYBRID_WEEKLY'))
        self.assertEqual(scope['selected'],{'0000000001','0000000002'})
        self.assertEqual(len([k for k in scope['checked_keys'] if k.startswith('alfred/')]),12)
        self.assertEqual(len([k for k in scope['checked_keys'] if k.startswith('worldbank/')]),4)

    def test_rolling_current_parent_uses_exact_verified_descendant_and_refuses_replay(self):
        scope=self.scope(); self.run_daily(scope); summary=self.h.finish_hybrid_cycle(self.lake,scope)
        config=dict(self.config,hybrid_refresh=scope['detail'])
        result=self.lake.publish('synthetic_hybrid_child',config)
        self.lake=Lake(self.t,self.root/'second'); self.receipt(self.lake,result,summary)
        with self.assertRaisesRegex(ValueError,'hybrid_request_already_executed'): self.scope()
        r=self.request(); r['request_id']='synthetic-next-approved-request'
        next_scope=self.scope(r)
        self.assertEqual(next_scope['resolved_parent'],result['commit_sha256'])
        self.assertEqual(next_scope['descendants_verified'],1)
        r['roster_sha256']='f'*64
        with self.assertRaisesRegex(ValueError,'NEEDS_REBIND'): self.scope(r)

    def test_foreign_legacy_descendant_requires_rebind_not_fallback(self):
        result=self.lake.publish('synthetic_foreign_child',self.config)
        self.lake=Lake(self.t,self.root/'foreign'); self.receipt(self.lake,result)
        with self.assertRaisesRegex(ValueError,'NEEDS_REBIND'): self.scope()

    def test_cycle_report_separates_inventory_and_unchecked_without_clock_renewal(self):
        scope=self.scope(); before=copy.deepcopy(self.lake.catalog['datasets'])
        self.run_daily(scope)
        selected=self.lake.catalog['datasets']['sec/0000000001']
        selected.update(status='COLLECTED',retrieved_at=self.now.isoformat())
        summary=self.h.finish_hybrid_cycle(self.lake,scope)
        self.assertFalse(summary['full_universe_current'])
        self.assertEqual(summary['retained_NOT_DUE'],16)
        self.assertEqual(selected['status'],'UNCHANGED')
        self.assertEqual(selected['retrieved_at'],before['sec/0000000001']['retrieved_at'])
        self.lake.catalog['datasets']['sec/0000000002']['checked_at']='forged'
        with self.assertRaisesRegex(ValueError,'hybrid_unchecked_dataset_changed'):
            self.h.finish_hybrid_cycle(self.lake,scope)

    def test_declaring_scope_without_actual_attempts_cannot_be_current(self):
        scope=self.scope()
        with self.assertRaisesRegex(ValueError,'hybrid_incomplete_request_scope'):
            self.h.finish_hybrid_cycle(self.lake,scope)

    def test_cycle_execution_receipt_binds_scope_and_SQL_excludes_not_due_inputs(self):
        scope=self.scope(); self.run_daily(scope); summary=self.h.finish_hybrid_cycle(self.lake,scope)
        report=self.h.diagnostics(self.lake)
        report.update(status='PARTIAL_COVERAGE',cycle_scope=summary)
        result=self.lake.publish('synthetic_scope_sql',dict(self.config,hybrid_refresh=scope['detail']))
        consumer=Lake(self.t,self.root/'sql-consumer')
        reports=self.root/'sql-reports'; reports.mkdir(); (reports/'quality.json').write_bytes(encoded(report))
        with patch.object(self.h,'materialize',return_value=34) as sql, \
             patch.object(self.h,'analyze_restored',return_value=(dict(tests_declared=[]),{})):
            code=self.h.complete_consumer(consumer,result,reports,self.root/'sql',run_id='synthetic_scope_sql',
                macro_start='1996-01-01',through='2026-10-23',report=report,cycle=scope)
        self.assertEqual(code,0)
        self.assertTrue(all(k.startswith('current/') for k in sql.call_args.args[2]))
        receipt=consumer.verified_execution()
        self.assertEqual(receipt['cycle_scope'],summary)
        self.assertFalse(receipt['cycle_scope']['full_universe_current'])

    def test_broken_old_pack_blocks_even_small_focus_before_provider(self):
        pack=self.t.names(PREFIX+'/packs')[0]
        (self.t.root/PREFIX/'packs'/pack).unlink()
        with patch.object(self.h,'get_public',side_effect=AssertionError('provider')):
            with self.assertRaises((ValueError,OSError)): self.scope()

    def test_budget_reservations_fail_before_call_and_never_refund(self):
        r=self.request(); r['budget']['transport_calls']=1
        b=self.h.HybridBudget(r,live_transport=False)
        t=self.h.HybridTransport.__new__(self.h.HybridTransport); t.hybrid_budget=b
        with patch.object(self.h.RcloneTransport,'call',return_value=b'{}') as call:
            self.assertEqual(t.call('cat','fixture'),b'{}')
            with self.assertRaisesRegex(ValueError,'hybrid_budget_exhausted'): t.call('cat','again')
            self.assertEqual(call.call_count,1)
        self.assertEqual(b.used['transport_calls'],1)
        self.assertIsNone(b.summary()['actual_Drive_API_requests'])
        with self.assertRaisesRegex(ValueError,'hybrid_existing_root_required'): t.call('mkdir','new')

    def test_owner_exact_request_and_history_replay_are_independent_of_body_flags(self):
        r=self.request(); sha=digest(encoded(r))
        record=dict(schema='long-history-hybrid-owner-v1',request_sha256=sha,
            producer_code_sha=r['code_sha'],purpose=r['purpose'],rights_sha256=r['rights_sha256'],
            expires_at=r['expires_at'])
        comment=dict(id=1,author_association='OWNER',user=dict(type='User'),
            created_at='2026-10-23T22:00:00Z',updated_at='2026-10-23T22:00:00Z',
            issue_url='https://api.github.com/repos/wscha231/r1000-quant-engine/issues/448',
            body=self.h.HYBRID_OWNER_TAG+json.dumps(record))
        ctx=dict(GITHUB_REPOSITORY='wscha231/r1000-quant-engine',GITHUB_REF='refs/heads/master',
                 GITHUB_RUN_ID='77',GITHUB_RUN_ATTEMPT='1',GITHUB_SHA='a'*40)
        runs=[dict(id=77,display_title='history-HYBRID_DAILY-'+sha,run_attempt=1,head_sha='a'*40)]
        def gh(path):
            return comment if '/issues/comments/' in path else dict(total_count=len(runs),workflow_runs=runs)
        ref='https://github.com/wscha231/r1000-quant-engine/issues/448#issuecomment-1'
        self.assertEqual(self.h.authorize_hybrid(r,sha,ref,gh=gh,context=ctx)['run_id'],77)
        runs.append(dict(runs[0],id=76))
        with self.assertRaisesRegex(ValueError,'hybrid_request_replay_or_unknown'):
            self.h.authorize_hybrid(r,sha,ref,gh=gh,context=ctx)
        runs.pop(); comment['author_association']='CONTRIBUTOR'
        with self.assertRaisesRegex(ValueError,'hybrid_owner_approval'):
            self.h.authorize_hybrid(r,sha,ref,gh=gh,context=ctx)

    def test_missing_optin_cli_request_never_constructs_transport_or_collects_all(self):
        args=['lake','--remote','unused','--workspace',str(self.root/'cli'),'--cohort','unused',
              '--run-id','fixture','--report-dir',str(self.root/'reports'),'--hybrid-mode','HYBRID_DAILY']
        with patch.object(sys,'argv',args), patch.object(self.h,'HybridTransport') as transport, \
             patch.object(self.h,'collect_financials') as collect:
            with self.assertRaisesRegex(ValueError,'hybrid_explicit_inputs_required'): self.h.main()
        transport.assert_not_called(); collect.assert_not_called()


class AutoHybridTest(unittest.TestCase):
    setUp=HybridHistoryTest.setUp
    receipt=HybridHistoryTest.receipt
    request=HybridHistoryTest.request
    run_daily=HybridHistoryTest.run_daily

    def profile(self):
        r=self.request()
        for k in ('request_id','weekly','through','decision_at','budget'):
            r.pop(k)
        r.update(schema='long-history-hybrid-auto-v1',profile_id='synthetic-auto',mode='HYBRID_AUTO',
            expires_at='2026-11-02T12:00:00Z',repository_id=123,workflow_id=456,
            workflow_path=self.h.AUTO_WORKFLOW,first_run_number=10,last_run_number=20,
            provider_scope=dict(sec=True,fred=True,worldbank=True),
            code_pins={p:digest((ROOT/p).read_bytes().replace(b'\r\n',b'\n')) for p in self.h.AUTO_PINS},
            per_run_allowance=copy.deepcopy(self.request()['budget']))
        r['total_reservation']={k:11*r['per_run_allowance'][k] for k in self.h.AUTO_RESOURCES}
        r['opening_floor']={k:7 for k in self.h.AUTO_RESOURCES}
        return r

    def live(self,p,number=10):
        sha=digest(encoded(p)); repo='wscha231/r1000-quant-engine'
        context=dict(GITHUB_REPOSITORY=repo,GITHUB_REPOSITORY_ID='123',GITHUB_REF='refs/heads/master',
            GITHUB_RUN_ID='77',GITHUB_RUN_ATTEMPT='1',GITHUB_RUN_NUMBER=str(number),GITHUB_SHA='a'*40,
            GITHUB_EVENT_NAME='schedule',GITHUB_JOB='history',GITHUB_ACTIONS='true',
            GITHUB_WORKFLOW_REF=repo+'/'+self.h.AUTO_WORKFLOW+'@refs/heads/master',GITHUB_WORKFLOW_SHA='a'*40)
        run=dict(id=77,run_number=number,run_attempt=1,workflow_id=456,path=self.h.AUTO_WORKFLOW,
            repository=dict(id=123,full_name=repo),head_repository=dict(id=123,full_name=repo),
            head_sha='a'*40,head_branch='master',event='schedule',created_at='2026-10-24T00:01:00Z')
        record=dict(schema='long-history-auto-owner-v1',profile_sha256=sha,
            code_pins_sha256=digest(encoded(p['code_pins'])),purpose=p['purpose'],
            rights_sha256=p['rights_sha256'],expires_at=p['expires_at'])
        comment=dict(id=1,author_association='OWNER',user=dict(type='User'),
            created_at='2026-10-23T22:00:00Z',updated_at='2026-10-23T22:00:00Z',
            issue_url='https://api.github.com/repos/'+repo+'/issues/448',
            body=self.h.AUTO_OWNER_TAG+json.dumps(record))
        def gh(path):
            if '/actions/runs/' in path:return run
            if '/actions/workflows/' in path:return dict(id=456,path=self.h.AUTO_WORKFLOW,state='active')
            if '/issues/comments/' in path:return comment
            if '/compare/' in path:return dict(status='ahead',merge_base_commit=dict(sha=p['code_sha']))
            if '/contents/' in path:
                import base64
                relative=path.split('/contents/',1)[1].split('?',1)[0]
                return dict(type='file',encoding='base64',content=base64.b64encode(
                    (ROOT/relative).read_bytes().replace(b'\r\n',b'\n')).decode())
            raise AssertionError('Unexpected GitHub path')
        return sha,context,run,comment,gh

    def authorize(self,p=None,number=10):
        p=self.profile() if p is None else p
        sha,ctx,run,c,gh=self.live(p,number)
        return self.h.authorize_auto(p,sha,
            'https://github.com/wscha231/r1000-quant-engine/issues/448#issuecomment-1',gh=gh,context=ctx)

    def test_failed_deleted_skipped_slots_all_charge_without_history_listing(self):
        p=self.profile(); per=p['per_run_allowance']['provider_gets']
        # No run history is supplied: failed N, deleted N, or unrelated/skip gap
        # all consume precisely the same monotonic worst-case allocation.
        for number,multiple in ((10,1),(11,2),(12,3),(15,6)):
            a=self.authorize(p,number)['reservation']
            self.assertEqual(a['reserved_allowance']['provider_gets'],multiple*per)
            self.assertEqual(a['cumulative_with_opening_floor']['provider_gets'],7+multiple*per)
        with self.assertRaisesRegex(ValueError,'outside_original_allocation'):self.authorize(p,21)
        with self.assertRaisesRegex(ValueError,'outside_original_allocation'):self.authorize(p,9)

    def test_original_profile_window_and_exact_total_not_reissued(self):
        p=self.profile(); raw=encoded(p)
        self.assertEqual(self.h.auto_profile(raw,digest(raw),now=self.now),p)
        for key,bad,reason in (('expires_at','2026-12-24T00:00:00Z','original_window'),
            ('first_run_number',True,'counter_identity'),('workflow_path','other.yml','counter_identity')):
            badp=copy.deepcopy(p); badp[key]=bad; raw=encoded(badp)
            with self.subTest(key=key),self.assertRaisesRegex(ValueError,reason):
                self.h.auto_profile(raw,digest(raw),now=self.now)
        p['total_reservation']['provider_gets']+=1; raw=encoded(p)
        with self.assertRaisesRegex(ValueError,'total_not_full_slots'):
            self.h.auto_profile(raw,digest(raw),now=self.now)
        with self.assertRaisesRegex(ValueError,'original_profile_hash'):
            self.h.auto_profile(raw,'0'*64,now=self.now)

    def test_rest_context_attempt_id_path_drift_refuse_before_source(self):
        p=self.profile()
        for field,bad in (('run_attempt',2),('workflow_id',999),('path','different.yml'),
                          ('head_sha','b'*40),('event','push'),('head_branch','other')):
            sha,ctx,run,c,gh=self.live(p);run[field]=bad
            with self.subTest(field=field),patch.object(self.h,'HybridTransport') as remote, \
                 patch.object(self.h,'get_public') as source:
                with self.assertRaisesRegex(ValueError,'rest_run_mismatch'):
                    self.h.authorize_auto(p,sha,
                        'https://github.com/wscha231/r1000-quant-engine/issues/448#issuecomment-1',gh=gh,context=ctx)
                remote.assert_not_called();source.assert_not_called()
        sha,ctx,run,c,gh=self.live(p);ctx['GITHUB_RUN_ATTEMPT']='2'
        with self.assertRaisesRegex(ValueError,'live_identity'):
            self.h.authorize_auto(p,sha,'unused',gh=gh,context=ctx)

    def test_same_attempt_second_invocation_refused_even_with_identical_bytes(self):
        a=self.authorize()
        with patch.dict('os.environ',RUNNER_TEMP=str(self.root)),patch.object(self.h,'HybridTransport') as source:
            self.h.claim_auto_invocation(a)
            with self.assertRaisesRegex(ValueError,'already_invoked'):self.h.claim_auto_invocation(a)
            source.assert_not_called()
        self.assertTrue((self.root/'history-auto-77-1.entry').is_file())

    def test_unchanged_profile_next_trading_day_then_weekend_and_unrelated_head(self):
        p=self.profile();sha=digest(encoded(p)); reservations=[]
        for clock,mode,session in (('2026-10-27T00:30:00Z','HYBRID_DAILY','2026-10-26'),
                                   ('2026-10-31T06:37:00Z','HYBRID_WEEKLY','2026-10-30')):
            now=self.h.hybrid_clock(clock)
            with patch.object(self.h,'utc_now',return_value=clock):
                self.h.auto_profile(encoded(p),sha,now=now)
                r=self.h.auto_request(p,sha,now=now,run=dict(run_number=11))
            self.assertEqual((r['mode'],r['through']),(mode,session))
            self.assertEqual(r['_auto']['original_expires_at'],p['expires_at'])
            self.assertEqual(r['decision_at'],now.isoformat());reservations.append(r)
        self.assertEqual(self.h.hybrid_continuation_identity(reservations[0]),
                         self.h.hybrid_continuation_identity(reservations[1]))
        _,ctx,_,_,gh=self.live(p);ctx['GITHUB_SHA']='b'*40
        self.h.verify_auto_code(p,ctx,gh)  # Relevant bytes unchanged; ancestor retained.
        p['code_pins']['tools/long_history_lake.py']='f'*64
        with self.assertRaisesRegex(ValueError,'deployed_code_changed'):
            self.h.verify_auto_code(p,ctx,gh)

    def test_partial_latest_blocks_despite_available_slots(self):
        p=self.profile();sha=digest(encoded(p));r=self.h.auto_request(p,sha,now=self.now)
        self.authorize(p)
        actual=self.lake.verified_execution
        with patch.object(self.lake,'verified_execution',side_effect=lambda **kw:
                dict(actual(**kw),quality_status='PARTIAL')), \
             patch.object(self.h,'get_public') as provider:
            with self.assertRaisesRegex(ValueError,'parent_execution_incomplete'):
                self.h.prepare_hybrid_scope(self.lake,r,digest(encoded(r)),
                    self.h.HybridBudget(r,live_transport=False),{})
            provider.assert_not_called()

    def test_same_profile_can_continue_verified_daily_to_weekly_without_rebinding(self):
        p=self.profile();sha=digest(encoded(p))
        # First synthetic approved run uses the fixed Friday scope, then the
        # same original profile selects the next week's true terminal session.
        r=self.request();r['_auto']=dict(profile_sha256=sha)
        scope=self.h.prepare_hybrid_scope(self.lake,r,digest(encoded(r)),
            self.h.HybridBudget(r,live_transport=False),{})
        self.run_daily(scope);summary=self.h.finish_hybrid_cycle(self.lake,scope)
        result=self.lake.publish('synthetic-auto-10',dict(self.config,hybrid_refresh=scope['detail']))
        self.lake=Lake(self.t,self.root/'auto-next');self.receipt(self.lake,result,summary)
        with patch.object(self.h,'utc_now',return_value='2026-10-31T06:37:00Z'):
            r=self.h.auto_request(p,sha,run=dict(run_number=11))
            scope=self.h.prepare_hybrid_scope(self.lake,r,digest(encoded(r)),
                self.h.HybridBudget(r,live_transport=False),{})
        self.assertEqual(scope['descendants_verified'],1)
        self.assertEqual(scope['selected'],{'0000000001','0000000002'})

    def test_pinned_workflow_still_requires_one_job_no_matrix_and_one_collect_call(self):
        import yaml
        p=self.profile();_,ctx,_,_,gh=self.live(p)
        original=yaml.safe_load((ROOT/self.h.AUTO_WORKFLOW).read_text())
        for kind in ('matrix','extra_job','duplicate_call'):
            w=copy.deepcopy(original)
            if kind=='matrix':w['jobs']['history']['strategy']={'matrix':{'copy':[1,2]}}
            elif kind=='extra_job':w['jobs']['other']=copy.deepcopy(w['jobs']['history'])
            else:
                step=next(s for s in w['jobs']['history']['steps'] if
                    s.get('name')=='Collect full history, persist changes, verify clean consumption')
                step['run']+='\npython tools/long_history_lake.py --unexpected-second-call\n'
            with self.subTest(kind=kind),patch.object(yaml,'safe_load',return_value=w):
                with self.assertRaisesRegex(ValueError,'auto_one_fixed_job|auto_no_matrix|auto_one_collector'):
                    self.h.verify_auto_code(p,ctx,gh)

    def test_actual_auto_entry_failure_then_duplicate_then_next_slot_keep_reservations(self):
        from types import SimpleNamespace
        p=self.profile();sha=digest(encoded(p));a=self.authorize(p)
        b=copy.deepcopy(a);b['run'].update(id=78,run_number=11)
        b['reservation']=self.h.auto_slot_reservation(p,11)
        original_budget=self.h.HybridBudget
        r=self.h.auto_request(p,sha,now=self.now)
        with patch.dict('os.environ',RUNNER_TEMP=str(self.root)), \
             patch.object(self.h,'HybridBudget',side_effect=lambda r:original_budget(r,live_transport=False)), \
             patch.object(self.h,'authorize_auto',side_effect=[a,a,b]), \
             patch.object(self.h,'HybridTransport',side_effect=ValueError('SYNTHETIC_RESTORE_FAILURE')) as transport:
            for index,run_id,reason in ((0,77,'SYNTHETIC_RESTORE_FAILURE'),
                                       (1,77,'already_invoked'),(2,78,'SYNTHETIC_RESTORE_FAILURE')):
                args=SimpleNamespace(report_dir=str(self.root/('attempt-'+str(index))),
                    hybrid_approval_reference='fixture',run_id='history-'+str(run_id)+'-1',remote='fixture')
                with self.subTest(index=index),self.assertRaisesRegex(ValueError,reason):
                    self.h.run_hybrid(args,r,sha,auto=(p,sha))
            self.assertEqual(transport.call_count,2)
        self.assertEqual(b['reservation']['reserved_allowance']['provider_gets'],
                         2*a['reservation']['reserved_allowance']['provider_gets'])
        self.assertTrue((self.root/'history-auto-77-1.entry').exists())
        self.assertTrue((self.root/'history-auto-78-1.entry').exists())

    def test_transport_retry_uses_same_meter_and_no_refund(self):
        r=self.request();r['budget']['transport_calls']=2
        budget=self.h.HybridBudget(r,live_transport=False)
        transport=self.h.HybridTransport.__new__(self.h.HybridTransport);transport.hybrid_budget=budget
        with patch.object(self.h.RcloneTransport,'call',side_effect=ValueError('research_transport:RATE_LIMIT')) as call, \
             patch('tools.macro_research_checkpoint.time.sleep'):
            with self.assertRaisesRegex(ValueError,'hybrid_budget_exhausted'):
                transport.read_call('cat','synthetic')
        self.assertEqual(call.call_count,2)
        self.assertEqual(budget.used['transport_calls'],2)

    def test_provider_scope_requires_disabled_null_and_active_real_evidence_hash(self):
        for scope,rights in ((dict(sec=True,fred=False,worldbank=False),self.request()['rights_sha256']),
            (dict(sec=True,fred=True,worldbank=True),dict(sec='d'*64,fred=None,worldbank='e'*64)),
            (dict(sec=False,fred=False,worldbank=False),dict(sec=None,fred=None,worldbank=None))):
            p=self.profile();p.update(provider_scope=scope,rights_sha256=rights);raw=encoded(p)
            with self.assertRaisesRegex(ValueError,'rights_evidence_required|explicit_provider_scope'):
                self.h.auto_profile(raw,digest(raw),now=self.now)
        r=self.request();r['rights_sha256']['fred']=None;raw=encoded(r)
        with self.assertRaisesRegex(ValueError,'rights_evidence_required'):
            self.h.hybrid_request(raw,digest(raw),r['mode'],now=self.now)

    def test_auto_reserves_whole_job_and_rerun_skips_before_checkout(self):
        import yaml
        p=self.profile();p['per_run_allowance']['active_seconds']=480
        p['total_reservation']['active_seconds']=11*480;raw=encoded(p)
        with self.assertRaisesRegex(ValueError,'auto_per_run_allowance'):
            self.h.auto_profile(raw,digest(raw),now=self.now)
        workflow=yaml.safe_load((ROOT/self.h.AUTO_WORKFLOW).read_bytes())
        job=workflow['jobs']['history']
        self.assertEqual(job['timeout-minutes'],120)
        self.assertIn("((inputs.hybrid_refresh_mode || vars.LONG_HISTORY_REFRESH_MODE || 'LEGACY') != 'HYBRID_AUTO' || github.run_attempt == 1)",job['if'])
        self.assertNotIn('env.',job['if'])

    def test_sec_only_excludes_fred_worldbank_preserves_clocks_and_readbacks_without_macro(self):
        p=self.profile();p['provider_scope']=dict(sec=True,fred=False,worldbank=False)
        p['rights_sha256'].update(fred=None,worldbank=None)
        p['per_run_allowance']['provider_gets']=6;p['total_reservation']['provider_gets']=66
        sha=digest(encoded(p));self.h.auto_profile(encoded(p),sha,now=self.now)
        r=self.h.auto_request(p,sha,now=self.now,run=dict(id=77,run_number=10))
        scope=self.h.prepare_hybrid_scope(self.lake,r,digest(encoded(r)),
            self.h.HybridBudget(r,live_transport=False),{})
        self.assertEqual(scope['provider_reservation_plan']['gets'],6)
        self.assertEqual(scope['checked_keys'],{'sec/0000000001'})
        before=copy.deepcopy(self.lake.catalog['datasets'])
        with patch.object(self.h,'fetch_fred_retry',side_effect=AssertionError('FRED_FORBIDDEN')), \
             patch.object(self.h,'get_public',return_value=(None,dict(etag='fixture'))) as public:
            self.h.collect_macros(self.lake,r['macro_start'],r['through'],_hybrid=scope)
            self.h.collect_financials(self.lake,'unused',r['financial_start'],r['through'],_hybrid=scope)
        self.assertEqual(public.call_count,1)
        for key,entry in before.items():
            if key.startswith(('current/','alfred/','worldbank/')):
                self.assertEqual(self.lake.catalog['datasets'][key],entry)
        summary=self.h.finish_hybrid_cycle(self.lake,scope)
        self.assertTrue(summary['requested_cycle_complete']);self.assertFalse(summary['data_ready'])
        self.assertFalse(summary['macro_regime_ready']);self.assertFalse(summary['whole_macro_complete'])
        self.assertEqual(len(summary['provider_exclusions']),50)
        result=self.lake.publish('synthetic-sec-only-10',dict(self.config,hybrid_refresh=scope['detail']))
        consumer=Lake(self.t,self.root/'sec-consumer');reports=self.root/'sec-reports';reports.mkdir()
        report=self.h.diagnostics(consumer);report.update(status='PARTIAL_COVERAGE',cycle_scope=summary)
        (reports/'quality.json').write_bytes(encoded(report))
        with patch.object(self.h,'analyze_restored',side_effect=AssertionError('FRED_STUDY_FORBIDDEN')) as study, \
             patch.object(self.h,'materialize',side_effect=AssertionError('NO_MACRO_SQL')):
            code=self.h.complete_consumer(consumer,result,reports,self.root/'sec',run_id='synthetic-sec-only-10',
                macro_start=r['macro_start'],through=r['through'],report=report,cycle=scope)
        study.assert_not_called();self.assertEqual(code,0)
        receipt=consumer.verified_execution();self.assertFalse(receipt['study_recomputed_from_drive'])
        self.assertEqual(len(receipt['source_cycle_readback']['checked']),1)
        self.assertFalse((reports/'macro-evaluation.json').exists())
        r=self.h.auto_request(p,sha,now=self.now,run=dict(id=78,run_number=11))
        scope2=self.h.prepare_hybrid_scope(consumer,r,digest(encoded(r)),
            self.h.HybridBudget(r,live_transport=False),{})
        self.assertEqual(scope2['descendants_verified'],1)

    def test_weekly_worldbank_scope_skips_sec_fred_and_does_not_certify_failed_cycle(self):
        p=self.profile();p['provider_scope']=dict(sec=False,fred=False,worldbank=True)
        p['rights_sha256'].update(sec=None,fred=None);sha=digest(encoded(p))
        clock='2026-10-31T06:37:00Z'
        with patch.object(self.h,'utc_now',return_value=clock):
            self.h.auto_profile(encoded(p),sha)
            r=self.h.auto_request(p,sha)
            scope=self.h.prepare_hybrid_scope(self.lake,r,digest(encoded(r)),
                self.h.HybridBudget(r,live_transport=False),{})
            self.assertEqual(scope['provider_reservation_plan']['gets'],12)
            self.assertEqual(len(scope['checked_keys']),4)
            before=copy.deepcopy(self.lake.catalog['datasets']['sec/0000000001'])
            with patch.object(self.h,'fetch_fred_retry',side_effect=AssertionError('FRED_FORBIDDEN')), \
                 patch.object(self.h,'get_public',side_effect=ValueError('SYNTHETIC_WB_FAILURE')) as public:
                self.h.collect_financials(self.lake,'unused',r['financial_start'],r['through'],_hybrid=scope)
                self.h.collect_macros(self.lake,r['macro_start'],r['through'],_hybrid=scope)
            self.assertEqual(public.call_count,4)
            self.assertEqual(self.lake.catalog['datasets']['sec/0000000001'],before)
            summary=self.h.finish_hybrid_cycle(self.lake,scope)
            self.assertFalse(summary['requested_cycle_complete']);self.assertFalse(summary['data_ready'])


if __name__=='__main__': unittest.main()
