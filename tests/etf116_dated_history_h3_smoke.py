"""Discriminating history/private-view contracts; all market rows are synthetic."""
import copy
from datetime import datetime, timezone
import json
import io
import os
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest
import zipfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import etf116_dated_history_h3 as history
from tools import etf116_private_history_view_h3 as view
from tools import etf116_private_sheet_probe_h2 as probe
from tests import etf116_delta_regression as delta_fixture
from tests.etf116_private_sheet_probe_h2_smoke import DriveFixture, ENV

FROZEN = ROOT / 'research/etf116_v1/frozen_tickers.txt'
FOLDER = 'HISTORY_FOLDER_FIXTURE'
EVALUATION = datetime(2026, 10, 24, tzinfo=timezone.utc)
REAL_WORKFLOW_BYTES = view._workflow_bytes


class ArchiveFixture(DriveFixture):
    root_id = probe.PRIVATE_ROOT

    def __init__(self):
        super().__init__()
        self.objects = {}
        self.extensions = {}
        self.incomplete = False
        self.archive_posts = 0
        self.unknown_archive = False
        self.pending_archive = None
        self.fail_view_after_apply = False

    def check(self, target, parent=None, folder=True):
        if target == probe.PRIVATE_SHEET:
            return super().check(target, parent, folder)
        if target == FOLDER and parent == probe.PRIVATE_ROOT and folder:
            return {}
        if target in self.objects and parent == FOLDER and not folder:
            return {}
        raise ValueError('UNEXPECTED_ARCHIVE_TARGET')

    def request(self, url, **kwargs):
        if 'www.googleapis.com/drive/v3/files?' in url:
            from urllib.parse import parse_qs, urlparse
            query = parse_qs(urlparse(url).query)['q'][0]
            files = [{'id': k, 'name': history.raw_hash(v) + self.extensions[k]}
                     for k, v in self.objects.items() if history.raw_hash(v) in query]
            return json.dumps({'files': files, 'incompleteSearch': self.incomplete}).encode()
        if url.endswith(':batchUpdate'):
            title = json.loads(kwargs['body'])['requests'][0]['addSheet']['properties']['title']
            old = self.fail_after_apply
            self.fail_after_apply = self.fail_view_after_apply and title.startswith('ETF116_RESEARCH_')
            try:
                return super().request(url, **kwargs)
            finally:
                self.fail_after_apply = old
        return super().request(url, **kwargs)

    def read(self, file_id, limit=None):
        return self.objects[file_id]

    def write(self, folder, raw, extension):
        self.check(folder, self.root_id)
        self.archive_posts += 1
        key = 'FIXTURE_OBJECT_' + str(self.archive_posts)
        if self.unknown_archive:
            self.pending_archive = (key, raw, extension)
            raise ValueError('UNKNOWN_ARCHIVE_CREATE')
        self.objects[key] = raw
        self.extensions[key] = extension
        return {'file_id': key, 'sha256': history.raw_hash(raw), 'bytes': len(raw)}


class DatedHistoryTests(unittest.TestCase):
    @unittest.skipIf(sys.flags.optimize, 'Optimized suite launcher runs only in normal mode')
    def test_native_h2_h3_optimized_child_suites(self):
        # Already registered with the ETF child suite; use real modules/locks/calendar.
        result = subprocess.run([sys.executable, '-O', '-m', 'unittest',
            'tests.etf116_private_sheet_probe_h2_smoke',
            'tests.etf116_dated_history_h3_smoke'], cwd=ROOT,
            capture_output=True, text=True, timeout=300)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        print('ETF116_NATIVE_H2_H3_OPTIMIZED_CHILD: ' + result.stderr.strip())

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.source = self.base / 'input.json'
        self.store = self.base / 'history'
        self.packet = {'schema': 'etf116-metrics-candidate-input-v1',
                       'scope_sha256': history.EXPECTED_UNIVERSE_SHA256,
                       'session': '2026-10-16', 'decision_at_utc': '2026-10-18T14:00:00Z',
                       'verified_nyse_sessions': ['2026-10-15', '2026-10-16'],
                       'source_candidate_rows': {}}

    def append(self):
        self.source.write_bytes(history.encoded(self.packet))
        return history.append_history(self.source, FROZEN, self.store,
                                      now=datetime(2026, 10, 23, tzinfo=timezone.utc))

    def test_reuses_existing_calculator_and_exact_input_bytes(self):
        with patch.object(history, 'calculate', wraps=history.calculate) as calc:
            result = self.append()
        self.assertEqual(calc.call_count, 1)
        record = result['snapshot']
        self.assertEqual(len(record['ticker_results']), 116)
        self.assertEqual(record['source_input_bytes_sha256'], history.raw_hash(self.source.read_bytes()))
        self.assertEqual((self.store / 'objects' / (record['source_input_bytes_sha256'] + '.json')).read_bytes(),
                         self.source.read_bytes())
        self.assertTrue(all(record[k] is False for k in history.FALSE_FLAGS))
        self.assertIsNone(record['ticker_results']['SPY']['daily_return'])

    def test_identical_day_is_read_only_and_does_not_recalculate(self):
        first = self.append()
        before = (self.store / '2026-10-16.json').read_bytes()
        with patch.object(history, 'calculate', side_effect=AssertionError('REPEATED_CALCULATION')):
            second = self.append()
        self.assertEqual(second['state'], 'IDENTICAL_HISTORY_READ_ONLY')
        self.assertEqual(first['snapshot'], second['snapshot'])
        self.assertEqual((self.store / '2026-10-16.json').read_bytes(), before)

    def test_changed_same_day_and_changed_code_cannot_overwrite(self):
        first = self.append()
        self.packet['risk_free_rows'] = []
        with self.assertRaisesRegex(ValueError, 'SAME_SESSION_CONFLICT'):
            self.append()
        del self.packet['risk_free_rows']
        with patch.object(history, 'code_hash', return_value='b' * 64):
            with self.assertRaisesRegex(ValueError, 'SAME_SESSION_CONFLICT'):
                self.append()
        self.assertEqual(history.strict_json((self.store / '2026-10-16.json').read_bytes()), first['snapshot'])

    def test_calendar_code_or_runtime_change_conflicts_with_same_day(self):
        self.append()
        actual = Path.read_bytes
        def changed(path):
            raw = actual(path)
            return raw + b'\n# CONTRACT_FIXTURE_CALENDAR_CHANGE\n' if path.name == 'r1000_legacy_input_guard.py' else raw
        with patch.object(Path, 'read_bytes', changed):
            with self.assertRaisesRegex(ValueError, 'SAME_SESSION_CONFLICT'):
                self.append()
        with patch.object(history, 'version', return_value='CONTRACT_FIXTURE_CHANGED_VERSION'):
            with self.assertRaisesRegex(ValueError, 'SAME_SESSION_CONFLICT'):
                self.append()

    def test_two_synthetic_sessions_append_in_calendar_order(self):
        first = self.append()['snapshot']
        self.packet.update(session='2026-10-19', decision_at_utc='2026-10-20T00:00:00Z')
        self.packet['verified_nyse_sessions'].append('2026-10-19')
        second = self.append()['snapshot']
        self.assertEqual(second['previous_snapshot_sha256'], first['snapshot_sha256'])
        self.assertTrue((self.store / '2026-10-16.json').exists())
        self.assertTrue((self.store / '2026-10-19.json').exists())

    def test_missing_session_and_backward_append_refuse(self):
        self.append()
        self.packet.update(session='2026-10-20', decision_at_utc='2026-10-21T00:00:00Z')
        self.packet['verified_nyse_sessions'] += ['2026-10-19', '2026-10-20']
        with self.assertRaisesRegex(ValueError, 'MISSING_NYSE_SESSION'):
            self.append()
        self.packet['session'] = '2026-10-14'
        self.packet['verified_nyse_sessions'] = ['2026-10-14']
        with self.assertRaisesRegex(ValueError, 'BACKWARD_SESSION'):
            self.append()

    def test_duplicate_nonfinite_json_and_symlink_inputs_refuse(self):
        for raw in (b'{"session":1,"session":2}', b'{"value":NaN}'):
            self.source.write_bytes(raw)
            with self.assertRaises(ValueError):
                history.append_history(self.source, FROZEN, self.store)
        link = self.base / 'link.json'
        link.symlink_to(self.source)
        with self.assertRaises(OSError):
            history.append_history(link, FROZEN, self.store)

    def assert_cli_input_refusal(self, source):
        output = self.base / 'view-plan.json'
        flags = ['-O'] if sys.flags.optimize else []
        commands = [
            [sys.executable, *flags, str(ROOT/'tools/etf116_dated_history_h3.py'),
             '--input',str(source),'--frozen',str(FROZEN),'--history-dir',str(self.store)],
            [sys.executable, *flags, str(ROOT/'tools/etf116_private_history_view_h3.py'),
             '--snapshot',str(source),'--output',str(output)]]
        for cmd in commands:
            result = subprocess.run(cmd, capture_output=True, timeout=5)
            self.assertEqual(result.returncode, 2)
            self.assertNotIn(b'Traceback', result.stderr)
        self.assertFalse(output.exists())
        self.assertFalse(self.store.exists())

    def test_deep_json_refuses_before_output_or_history_reservation(self):
        self.source.write_bytes(b'['*10000+b'0'+b']'*10000)
        with self.assertRaisesRegex(history.RefuseInput, 'HISTORY_JSON_RECURSION'):
            history.strict_json(self.source.read_bytes())
        self.assert_cli_input_refusal(self.source)

    def test_fifo_refuses_without_waiting_for_a_writer(self):
        fifo = self.base / 'input.fifo'
        os.mkfifo(fifo)
        self.assert_cli_input_refusal(fifo)

    def test_prior_snapshot_or_source_tamper_blocks_reuse(self):
        record = self.append()['snapshot']
        object_path = self.store / 'objects' / (record['source_input_bytes_sha256'] + '.json')
        original = object_path.read_bytes()
        object_path.write_bytes(b'tampered')
        with self.assertRaisesRegex(ValueError, 'SOURCE_HASH'):
            self.append()
        object_path.write_bytes(original)
        path = self.store / '2026-10-16.json'
        record['computed_at_utc'] = 'changed'
        path.write_bytes(history.encoded(record))
        with self.assertRaisesRegex(ValueError, 'HISTORY_HASH'):
            self.append()

    def test_computed_clock_cannot_precede_input_decision(self):
        self.source.write_bytes(history.encoded(self.packet))
        with self.assertRaisesRegex(ValueError, 'COMPUTED_BEFORE_DECISION'):
            history.append_history(self.source, FROZEN, self.store,
                                   now=datetime(2026, 10, 17, tzinfo=timezone.utc))
        self.assertFalse((self.store / '2026-10-16.json').exists())

    def test_future_session_cannot_poison_chronological_history(self):
        self.packet['session'] = '2026-10-26'
        self.packet['verified_nyse_sessions'] = ['2026-10-26']
        with self.assertRaisesRegex(ValueError, 'HISTORY_SESSION_AFTER_DECISION'):
            self.append()
        self.assertFalse(self.store.exists())
        self.packet['session'] = '2026-10-16'
        self.packet['verified_nyse_sessions'] = ['2026-10-15', '2026-10-16']
        self.assertEqual(self.append()['state'], 'APPENDED_RESEARCH_HISTORY')

    def test_empty_preclose_packet_cannot_reserve_a_date(self):
        self.packet['decision_at_utc'] = '2026-10-16T19:00:00Z'
        with self.assertRaisesRegex(ValueError, 'OFFLINE_DECISION_BEFORE_SESSION_CLOSE'):
            self.append()
        self.assertFalse(self.store.exists())
        self.packet['decision_at_utc'] = '2026-10-16T20:30:00Z'
        self.assertEqual(self.append()['state'], 'APPENDED_RESEARCH_HISTORY')

    def test_hash_valid_but_inconsistent_stored_clock_refuses(self):
        record = self.append()['snapshot']
        record['decision_at_utc'] = '2026-10-14T00:00:00+00:00'
        record['snapshot_sha256'] = history.canonical_hash({k: v for k, v in record.items()
                                                         if k != 'snapshot_sha256'})
        (self.store / '2026-10-16.json').write_bytes(history.encoded(record))
        with self.assertRaisesRegex(ValueError, 'HISTORY_STORED_CLOCK'):
            self.append()

    def test_stored_computed_clock_cannot_exceed_trusted_replay_time(self):
        self.append()
        before = (self.store/'2026-10-16.json').read_bytes()
        with self.assertRaisesRegex(ValueError, 'COMPUTED_AFTER_EVALUATION'):
            history.append_history(self.source, FROZEN, self.store,
                                   now=datetime(2026,10,22,tzinfo=timezone.utc))
        self.assertEqual((self.store/'2026-10-16.json').read_bytes(), before)

    def test_projection_preserves_real_calculator_outputs_and_null_rf(self):
        fixture = delta_fixture.DeltaRegression(methodName='runTest')
        fixture.setUp()
        self.packet['verified_nyse_sessions'] = fixture.sessions
        self.packet['source_candidate_rows'] = {'GARP': fixture.rows, 'SPY': fixture.series('SPY')}
        expected = fixture.compute(benchmark_rows=fixture.series('SPY'))
        result = self.append()['snapshot']['ticker_results']['GARP']
        self.assertEqual(result['horizons'], expected['horizons'])
        self.assertEqual(result['daily_return'], expected['daily_returns'][-1])
        self.assertNotIn('daily_returns', result)
        self.assertIsNone(result['horizons']['12']['risk']['sharpe'])
        self.assertGreater(result['horizons']['12']['risk']['ann_volatility'], 0)
        self.assertAlmostEqual(result['horizons']['12']['log_relative_rs_spy'], 0)


class PrivateViewTests(unittest.TestCase):
    def setUp(self):
        DatedHistoryTests.setUp(self)
        mock = patch.object(view, '_workflow_bytes', return_value=(ROOT / view.WORKFLOW).read_bytes())
        mock.start()
        self.addCleanup(mock.stop)
    append = DatedHistoryTests.append

    def setup_view(self):
        snapshot = self.append()['snapshot']
        drive = ArchiveFixture()
        binding = probe.actions_binding(ENV)
        proof = probe.run_probe(drive, binding)
        drive.calls.clear()
        ref = 'refs/heads/task/fixture'
        env = dict(ENV, ETF116_PRIVATE_METRICS_AUTHORIZED='true', RUNNER_TEMP=str(self.base),
                   GITHUB_REF=ref, GITHUB_WORKFLOW_REF=probe.REPOSITORY+'/'+view.WORKFLOW+'@'+ref,
                   GITHUB_WORKFLOW_SHA=ENV['GITHUB_SHA'], GITHUB_JOB=view.JOB)
        return snapshot, drive, proof, env

    def publish(self, snapshot, drive, proof, env):
        return view.publish_private(drive, snapshot, self.source.read_bytes(), proof, FOLDER, env,
                                    evaluation_time=EVALUATION)

    def test_plan_has_116_by_8_dated_literal_rows_and_no_authority(self):
        plan = view.view_plan(self.append()['snapshot'], evaluation_time=EVALUATION)
        self.assertEqual(len(plan['values']), 929)
        self.assertEqual(len(plan['values'][0]), 20)
        self.assertTrue(all(isinstance(v, str) for row in plan['values'] for v in row))
        self.assertEqual(plan['values'][1][3], 'NULL')
        self.assertFalse(plan['automatic_refresh_enabled'])
        self.assertFalse(plan['allowed_for_original_sheet'])

    def test_malformed_rehashed_projection_is_sanitized_before_output(self):
        from contextlib import redirect_stdout
        original = self.append()['snapshot']
        for change in ('missing_daily','bad_daily','bad_risk','bad_tickers'):
            forged = copy.deepcopy(original)
            result = forged['ticker_results'][next(iter(forged['ticker_results']))]
            if change == 'missing_daily': del result['daily_return']
            if change == 'bad_daily': result['daily_return'] = {'bad':1}
            if change == 'bad_risk': result['horizons']['12']['risk'] = []
            if change == 'bad_tickers': forged['ticker_results'] = None
            forged['snapshot_sha256'] = history.canonical_hash({k:v for k,v in forged.items()
                                                               if k != 'snapshot_sha256'})
            snapshot_path, output = self.base/'forged.json',self.base/'output.json'
            snapshot_path.write_bytes(history.encoded(forged))
            argv = ['view','--snapshot',str(snapshot_path),'--output',str(output)]
            with self.subTest(change=change), patch.object(sys,'argv',argv), \
                    patch.object(view,'datetime') as clock, redirect_stdout(io.StringIO()) as stdout:
                clock.now.return_value = EVALUATION
                self.assertEqual(view.main(), 2)
            self.assertIn('BLOCKED_PRIVATE_HISTORY_INPUT', stdout.getvalue())
            self.assertFalse(output.exists())

    def test_private_view_retains_benchmark_refusal_and_window_anchor(self):
        fixture = delta_fixture.DeltaRegression(methodName='runTest')
        fixture.setUp()
        self.packet['verified_nyse_sessions'] = fixture.sessions
        spy = fixture.series('SPY')
        for row in spy:
            row['basis'] = 'MARKET_TR_INDEX'
        self.packet['source_candidate_rows'] = {'GARP': fixture.rows, 'SPY': spy}
        plan = view.view_plan(self.append()['snapshot'], evaluation_time=EVALUATION)
        rows = [dict(zip(plan['values'][0], row)) for row in plan['values'][1:]]
        target = next(r for r in rows if r['ticker'] == 'GARP' and r['months'] == '12')
        self.assertEqual(target['benchmark_status'], 'BENCHMARK_BASIS_MISMATCH')
        self.assertEqual(target['anchor_session'], '2025-10-16')
        self.assertEqual(target['log_relative_rs_spy'], 'NULL')

    def test_archive_readback_and_private_tab_repeat_is_get_only(self):
        snapshot, drive, proof, env = self.setup_view()
        receipt = self.publish(snapshot, drive, proof, env)
        self.assertEqual(drive.archive_posts, 2)
        self.assertEqual(receipt['state'], 'PRIVATE_VIEW_READBACK_VERIFIED')
        drive.calls.clear()
        again = self.publish(snapshot, drive, proof, env)
        self.assertEqual(drive.archive_posts, 2)
        self.assertEqual(again['state'], 'IDENTICAL_PRIVATE_VIEW_READ_ONLY')
        self.assertFalse(any(k.get('method') == 'POST' for _, k in drive.calls))
        self.assertFalse(receipt['source_admission'])
        self.assertFalse(receipt['original_research_sheet_updated'])

    def test_trusted_replay_clock_reaches_source_and_existing_calculator(self):
        self.packet.update(session='2026-10-20',decision_at_utc='2026-10-21T00:00:00Z')
        self.packet['verified_nyse_sessions'] += ['2026-10-19','2026-10-20']
        snapshot, drive, proof, env = self.setup_view()
        with patch.object(history,'calculate',wraps=history.calculate) as calc:
            result = self.publish(snapshot,drive,proof,env)
        self.assertEqual(result['state'],'PRIVATE_VIEW_READBACK_VERIFIED')
        self.assertEqual(calc.call_count,1)
        self.assertEqual(calc.call_args.kwargs['evaluation_time'],EVALUATION)
        self.assertEqual(result['evaluated_at_utc'],EVALUATION.isoformat())
        self.assertFalse(result['source_admission'])

    def test_missing_or_blocked_real_proof_never_creates_a_tab(self):
        snapshot, drive, proof, env = self.setup_view()
        sid, _, _ = probe.run_target(proof['binding'])
        del drive.tabs[sid]
        with self.assertRaisesRegex(ValueError, 'PROBE_READBACK'):
            self.publish(snapshot, drive, proof, env)
        self.assertEqual(drive.archive_posts, 0)
        self.assertFalse(any(k.get('method') == 'POST' for _, k in drive.calls))
        proof['state'] = 'BLOCKED'
        with self.assertRaisesRegex(ValueError, 'PRIVATE_ACTIONS_PROOF_REQUIRED'):
            self.publish(snapshot, drive, proof, env)

    def test_wrong_principal_proof_or_source_binding_blocks_all_writes(self):
        snapshot, drive, proof, env = self.setup_view()
        proof['principal_sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'PRIVATE_ACTIONS_PROOF_REQUIRED'):
            self.publish(snapshot, drive, proof, env)
        self.assertEqual(drive.archive_posts, 0)
        self.source.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'HISTORY_SOURCE_HASH'):
            self.publish(snapshot, drive, proof, env)

    def test_rehashed_snapshot_cannot_change_its_source_session(self):
        snapshot, drive, proof, env = self.setup_view()
        snapshot['session'] = '2026-10-15'
        snapshot['snapshot_sha256'] = history.canonical_hash({k: v for k, v in snapshot.items()
                                                            if k != 'snapshot_sha256'})
        with self.assertRaisesRegex(ValueError, 'HISTORY_SOURCE_CLOCK_BINDING'):
            self.publish(snapshot, drive, proof, env)
        self.assertEqual(drive.calls, [])
        self.assertEqual(drive.archive_posts, 0)

    def test_rehashed_metrics_and_candidate_receipt_refuse_before_remote_calls(self):
        snapshot, drive, proof, env = self.setup_view()
        for change, reason in [('cagr','CALCULATED_METRICS_MISMATCH'),
                               ('receipt','CANDIDATE_RECEIPT_MISMATCH'),
                               ('calculator','CALCULATOR_CHANGED')]:
            forged = copy.deepcopy(snapshot)
            if change == 'cagr':
                forged['ticker_results'][next(iter(forged['ticker_results']))]['horizons']['12']['cagr'] = .123
            else:
                forged['candidate_receipt_sha256' if change == 'receipt' else 'calculator_sha256'] = '0'*64
            forged['snapshot_sha256'] = history.canonical_hash({k:v for k,v in forged.items()
                                                               if k != 'snapshot_sha256'})
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, reason):
                self.publish(forged, drive, proof, env)
            self.assertEqual(drive.calls, [])
            self.assertEqual(drive.archive_posts, 0)

    def test_publication_rejects_future_computed_and_decision_clocks(self):
        original, drive, proof, env = self.setup_view()
        for decision in (original['decision_at_utc'],'2026-10-26T00:00:00+00:00'):
            forged = copy.deepcopy(original)
            forged['decision_at_utc'] = decision
            forged['computed_at_utc'] = '2026-10-27T00:00:00+00:00'
            forged['snapshot_sha256'] = history.canonical_hash({k:v for k,v in forged.items()
                                                               if k != 'snapshot_sha256'})
            with self.subTest(decision=decision), self.assertRaisesRegex(ValueError, 'COMPUTED_AFTER_EVALUATION'):
                self.publish(forged, drive, proof, env)
            self.assertEqual(drive.calls, [])
            self.assertEqual(drive.archive_posts, 0)

    def test_untrusted_snapshot_or_env_cannot_override_default_current_clock(self):
        snapshot, drive, proof, env = self.setup_view()
        snapshot.update(computed_at_utc='2099-01-01T00:00:00+00:00',
                        evaluation_time='2099-01-02T00:00:00+00:00')
        snapshot['snapshot_sha256'] = history.canonical_hash({k:v for k,v in snapshot.items()
                                                             if k != 'snapshot_sha256'})
        env['ETF116_EVALUATION_TIME'] = '2099-01-02T00:00:00Z'
        with self.assertRaisesRegex(ValueError, 'COMPUTED_AFTER_EVALUATION'):
            view.view_plan(snapshot)
        with self.assertRaisesRegex(ValueError, 'COMPUTED_AFTER_EVALUATION'):
            view.publish_private(drive,snapshot,self.source.read_bytes(),proof,FOLDER,env)
        self.assertEqual(drive.calls, [])
        self.assertEqual(drive.archive_posts, 0)

    def test_large_input_bytes_use_lossless_deterministic_bounded_archive(self):
        # Capacity fixture only, not actual116 market-history or rights proof.
        raw = b'CONTRACT_FIXTURE_CAPACITY_ONLY\n' * 900000
        path = self.base / 'capacity.json'
        path.write_bytes(raw)
        self.assertEqual(history.read_bytes(path), raw)
        archived = view.source_archive_bytes(raw)
        self.assertEqual(archived, view.source_archive_bytes(raw))
        self.assertLess(len(archived), view.MAX_ARCHIVE_BYTES)
        with zipfile.ZipFile(io.BytesIO(archived)) as archive:
            self.assertIsNone(archive.testzip())
            self.assertEqual(archive.namelist(), ['candidate-input.json'])
            self.assertEqual(archive.read('candidate-input.json'), raw)

    def test_explicit_current_head_authorization_required(self):
        snapshot, drive, proof, env = self.setup_view()
        for bad in (dict(env, ETF116_PRIVATE_METRICS_AUTHORIZED='false'),
                    dict(env, ETF116_EXPECTED_CODE_SHA='b' * 40)):
            with self.assertRaises(ValueError):
                self.publish(snapshot, drive, proof, bad)
        self.assertEqual(drive.calls, [])

    def test_incomplete_archive_inventory_refuses_before_create(self):
        snapshot, drive, proof, env = self.setup_view()
        drive.incomplete = True
        with self.assertRaisesRegex(ValueError, 'PRIVATE_ARCHIVE_AMBIGUOUS'):
            self.publish(snapshot, drive, proof, env)
        self.assertEqual(drive.archive_posts, 0)

    def test_ambiguous_tab_create_is_not_retried_or_cleaned_up(self):
        snapshot, drive, proof, env = self.setup_view()
        drive.fail_view_after_apply = True
        with self.assertRaisesRegex(ValueError, 'AMBIGUOUS_BATCH_RESULT'):
            self.publish(snapshot, drive, proof, env)
        self.assertEqual(sum(k.get('method') == 'POST' for _, k in drive.calls), 3)
        drive.fail_view_after_apply = False
        drive.calls.clear()
        result = self.publish(snapshot, drive, proof, env)
        self.assertEqual(result['state'], 'IDENTICAL_PRIVATE_VIEW_READ_ONLY')
        self.assertFalse(any(k.get('method') == 'POST' for _, k in drive.calls))

    def test_view_and_cell_budget_refuse_before_archiving(self):
        for full_cells in (False, True):
            snapshot, drive, proof, env = self.setup_view()
            for i in range(1 if full_cells else view.MAX_PRIVATE_VIEWS):
                drive.tabs[100000+i] = {'sheetId':100000+i,'title':'ETF116_RESEARCH_FIXTURE_'+str(i),
                    'gridProperties':{'rowCount':view.MAX_PRIVATE_CELLS if full_cells else 929,
                                      'columnCount':20}}
            with self.assertRaisesRegex(ValueError, 'PRIVATE_VIEW_ROTATION_REQUIRED'):
                self.publish(snapshot, drive, proof, env)
            self.assertEqual(drive.archive_posts, 0)
            self.assertFalse(any(k.get('method') == 'POST' for _, k in drive.calls))

    def test_existing_exact_view_uses_no_new_budget_or_create(self):
        snapshot, drive, proof, env = self.setup_view()
        self.publish(snapshot, drive, proof, env)
        for i in range(view.MAX_PRIVATE_VIEWS):
            drive.tabs[100000+i]={'sheetId':100000+i,'title':'ETF116_RESEARCH_FIXTURE_'+str(i),
                                 'gridProperties':{'rowCount':929,'columnCount':20}}
        drive.calls.clear()
        self.assertEqual(self.publish(snapshot, drive, proof, env)['state'], 'IDENTICAL_PRIVATE_VIEW_READ_ONLY')
        self.assertEqual(drive.archive_posts, 2)
        self.assertFalse(any(k.get('method') == 'POST' for _, k in drive.calls))

    def test_same_runner_overlap_refuses_before_any_remote_call(self):
        snapshot, drive, proof, env = self.setup_view()
        with view.private_publish_lock(env):
            with self.assertRaisesRegex(ValueError, 'PRIVATE_PUBLISH_BUSY'):
                self.publish(snapshot, drive, proof, env)
        self.assertEqual(drive.calls, [])
        self.assertEqual(drive.archive_posts, 0)

    def test_wrong_workflow_job_or_concurrency_refuses(self):
        snapshot, drive, proof, env = self.setup_view()
        for key in ('GITHUB_WORKFLOW_REF','GITHUB_WORKFLOW_SHA','GITHUB_JOB'):
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.publish(snapshot, drive, proof, dict(env, **{key:'WRONG'}))
        with patch.object(view, '_workflow_bytes', return_value=b'jobs:\n  etf116_private_sheet_probe:\n    concurrency:\n      group: WRONG\n      cancel-in-progress: false\n'):
            with self.assertRaisesRegex(ValueError, 'PRIVATE_SERIALIZED_JOB_REQUIRED'):
                self.publish(snapshot, drive, proof, env)
        self.assertEqual(drive.calls, [])

    def test_workflow_contract_requires_committed_local_byte_equality(self):
        with patch.object(view.subprocess, 'check_output', side_effect=['a'*40, b'DIFFERENT']):
            with self.assertRaisesRegex(ValueError, 'PRIVATE_SERIALIZED_JOB_REQUIRED'):
                REAL_WORKFLOW_BYTES('a'*40)

    def test_dirty_history_validator_also_blocks_exact_head_execution(self):
        def dirty_any_tracked(cmd, **kwargs):
            if cmd[-4:] == ['diff','--quiet','HEAD','--']:
                raise view.subprocess.CalledProcessError(1, cmd)
            return 0
        with patch.object(view.subprocess, 'check_output', side_effect=[
                'a'*40, (ROOT / view.WORKFLOW).read_bytes()]), \
                patch.object(view.subprocess, 'check_call', side_effect=dirty_any_tracked):
            with self.assertRaises(view.subprocess.CalledProcessError):
                REAL_WORKFLOW_BYTES('a'*40)

    def test_unknown_archive_create_is_durably_reserved_no_second_post(self):
        snapshot, drive, proof, env = self.setup_view()
        drive.unknown_archive = True
        with self.assertRaisesRegex(ValueError, 'UNKNOWN_ARCHIVE_CREATE'):
            self.publish(snapshot, drive, proof, env)
        self.assertEqual(drive.archive_posts, 1)
        drive.calls.clear()
        with self.assertRaisesRegex(ValueError, 'PRIVATE_ARCHIVE_MANUAL_RECONCILIATION_REQUIRED'):
            self.publish(snapshot, drive, proof, env)
        self.assertEqual(drive.archive_posts, 1)
        self.assertFalse(any(k.get('method') == 'POST' for _, k in drive.calls))
        # Manual reconciliation observes the old CREATE's actual bytes/ID.
        newer = dict(env, GITHUB_RUN_ID='12346')
        with self.assertRaises(ValueError):
            self.publish(snapshot, drive, proof, newer)
        self.assertEqual(drive.archive_posts, 1)
        self.assertFalse(any(k.get('method') == 'POST' for _, k in drive.calls))
        key, raw, extension = drive.pending_archive
        drive.objects[key], drive.extensions[key] = raw, extension
        drive.unknown_archive = False
        self.assertEqual(self.publish(snapshot, drive, proof, env)['state'], 'PRIVATE_VIEW_READBACK_VERIFIED')
        self.assertEqual(drive.archive_posts, 2)


if __name__ == '__main__':
    unittest.main()
