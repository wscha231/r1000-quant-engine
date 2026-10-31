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

    def test_fred_missing_dates_survive_parser(self):
        from tools.long_history_lake import parse_graph,fred_missing
        rows,missing=parse_graph(b'observation_date,UNRATE\n2025-09-01,4.4\n2025-10-01,.\n2025-11-01,4.5\n',
            'UNRATE','2025-01-01','2025-12-31','2026-09-12T00:00:00+00:00')
        result=fred_missing(rows,missing)
        self.assertEqual(result['missing_values'],1)
        self.assertEqual(result['missing_observation_dates'],['2025-10-01'])

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



def load_tests(loader, tests, pattern):
    # Keep the existing registered Tier-1 entry; avoid the shared runner/P0 lane.
    from research_data_access_smoke import ReaderTest
    tests.addTests(loader.loadTestsFromTestCase(ReaderTest))
    from a1_reader_generation_binding_smoke import BindingTest
    tests.addTests(loader.loadTestsFromTestCase(BindingTest))
    return tests


if __name__=='__main__': unittest.main()
