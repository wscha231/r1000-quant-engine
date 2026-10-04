#!/usr/bin/env python3
"""Smoke tests for self-correction queue closure."""
from __future__ import annotations

import json
import copy
import io
import contextlib
import unittest
from unittest.mock import patch
import sys
from argparse import Namespace
from pathlib import Path
from tempfile import TemporaryDirectory


REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tools.run_self_correction_queue_closure import run  # noqa: E402


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def queue_item(experiment_id: str, payload_hash: str) -> dict[str, object]:
    return {
        "experiment_id": experiment_id,
        "payload_hash": payload_hash,
        "source_leak": "concentrated:structural_underinvestment_bull",
        "source_run_id": "27516185696",
        "status": "queued",
        "production_mutation_allowed": False,
        "requires_user_approval": True,
    }


def test_queue_closure_maps_verifier_decisions_to_statuses() -> None:
    check = unittest.TestCase()
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        queue_path = root / "router_queue.json"
        verifier_path = root / "verifier_summary.json"
        out = root / "out"
        write_json(
            queue_path,
            {
                "schema_version": "self-correction-router-v1.1",
                "production_mutation_allowed": False,
                "queued_experiments": [
                    queue_item("conc_continuation_winner_relaxation", "payload-ready"),
                    queue_item("conc_bull_floor_stock_min", "payload-reject"),
                    queue_item("conc_reentry_quality", "payload-blocked"),
                    queue_item("conc_theme_leadership_boost", "payload-open"),
                ],
                "duplicate_suppressed_count": 1,
                "duplicate_suppressed": [{"experiment_id": "duplicate"}],
                "stale_payloads": [{"experiment_id": "stale_old", "status": "stale"}],
            },
        )
        write_json(
            verifier_path,
            {
                "schema_version": "ab-result-verifier-v1",
                "status": "review_candidate_ready",
                "production_activation_allowed": False,
                "dispatch_context": {"workflow_run_id": "123456"},
                "candidates": [
                    {
                        "experiment_id": "conc_continuation_winner_relaxation",
                        "payload_hash": "payload-ready",
                        "candidate_run": "run-ready",
                        "decision": "promote_candidate_review_only",
                        "review_valid_for_promotion": True,
                        "issues": [],
                        "cagr": 0.52,
                        "max_dd": -0.26,
                        "is_cagr": 0.31,
                    },
                    {
                        "experiment_id": "conc_bull_floor_stock_min",
                        "candidate_run": "run-rejected",
                        "decision": "reject_regression",
                        "review_valid_for_promotion": False,
                        "issues": ["is_cagr_delta_below_min:-1.0pp"],
                    },
                    {
                        "experiment_id": "conc_reentry_quality",
                        "payload_hash": "payload-blocked",
                        "candidate_run": "run-blocked",
                        "decision": "blocked_oos_lock",
                        "review_valid_for_promotion": False,
                        "issues": ["oos_is_cagr_ratio_above_lock"],
                    },
                ],
            },
        )
        payload = run(
            Namespace(
                queue_path=str(queue_path),
                verifier_summary=[str(verifier_path)],
                verifier_dir=[],
                output_dir=str(out),
            )
        )
        by_id = {item["experiment_id"]: item for item in payload["queue_state"]}
        check.assertEqual(by_id["conc_continuation_winner_relaxation"]["status"], "ready_for_human_review")
        check.assertEqual(by_id["conc_continuation_winner_relaxation"]["workflow_run_id"], "123456")
        check.assertEqual(by_id["conc_bull_floor_stock_min"]["status"], "rejected")
        check.assertEqual(by_id["conc_reentry_quality"]["status"], "measured")
        check.assertIs(by_id["conc_reentry_quality"]["requires_followup"], True)
        check.assertEqual(by_id["conc_theme_leadership_boost"]["status"], "queued")
        check.assertEqual(by_id["conc_theme_leadership_boost"]["closure_match_status"], "unmatched")
        for key, expected in {'matched_item_count': 3, 'ready_for_human_review_count': 1,
                              'rejected_count': 1, 'measured_count': 1,
                              'duplicate_suppressed_count': 1, 'stale_payload_count': 1}.items():
            check.assertEqual(payload[key], expected)
        check.assertIs(payload["production_mutation_allowed"], False)
        check.assertIs(payload["live_trading_allowed"], False)
        for name in ('summary.json', 'queue_state.jsonl', 'deduped_queue.json', 'stale_payloads.json', 'closure_report.md'):
            check.assertTrue((out / name).exists())


class SummaryReadBudgetTests(unittest.TestCase):
    def setUp(self):
        from tools import run_self_correction_queue_closure as closure
        self.closure = closure
        self.temp = TemporaryDirectory(prefix='r1000-summary-budget-')
        self.addCleanup(self.temp.cleanup)
        self.area = Path(self.temp.name)
        self.cap = closure.result_verifier.MAX_REPORT_BYTES

    def payload(self, family):
        payload = {'status': 'review_candidate_ready', 'candidates': [
            {'experiment_id': 'bounded-summary', 'payload_hash': 'fixed-contract',
             'decision': 'promote_candidate_review_only'}]}
        if family == 'legacy_v1': payload['schema_version'] = 'ab-result-verifier-v1'
        if family == 'current_v2':
            payload.update(schema_version=self.closure.result_verifier.COMPARISON_SUMMARY_SCHEMA,
                           comparison_publication={'schema': self.closure.result_verifier.PUBLICATION_SCHEMA,
                                                   'generation': 'a' * 32}, current_receipt=True)
        if family == 'historical_optin': payload['comparison_admission'] = {'status': 'BYTE_COMPARABLE_RESEARCH_ONLY'}
        return payload

    def consume(self, path, key):
        queue = self.area / (key + '-queue.json')
        write_json(queue, {'queued_experiments': [queue_item('bounded-summary', 'fixed-contract')]})
        with contextlib.redirect_stdout(io.StringIO()):
            return run(Namespace(queue_path=str(queue), verifier_summary=[str(path)], verifier_dir=[],
                                 output_dir=str(self.area / (key + '-closure'))))

    def test_every_oversized_summary_is_rejected_before_read_or_json_decode(self):
        import os
        families = ('legacy_no_version', 'legacy_v1', 'current_v2', 'historical_optin', 'malformed')
        for family in families:
            for size in (self.cap + 1, self.cap + 65536, self.cap * 2):
                for dirname in ('ordinary', 'with spaces'):
                    with self.subTest(family=family, size=size, directory=dirname):
                        path = self.area / dirname / 'summary.json'; path.parent.mkdir(exist_ok=True)
                        raw = b'{' if family == 'malformed' else json.dumps(self.payload(family)).encode('utf-8')
                        path.write_bytes(raw + b' ' * (size - len(raw)))
                        original_read, original_loads, original_stat = os.read, json.loads, os.fstat
                        with patch.object(self.closure.os, 'read', wraps=original_read) as read, \
                             patch.object(self.closure.json, 'loads', wraps=original_loads) as loads, \
                             patch.object(self.closure.os, 'fstat', wraps=original_stat) as fstat:
                            self.assertEqual(self.closure.read_verifier_summary(path), {})
                        self.assertEqual(fstat.call_count, 1, 'actual initial descriptor size check was not reached')
                        read.assert_not_called()
                        loads.assert_not_called()
                        with patch.object(self.closure.os, 'read', wraps=original_read) as read:
                            self.assertEqual(self.closure.load_verifier_summaries([str(path)], []), [])
                        read.assert_not_called()
                        result = self.consume(path, str((family, size, dirname)))
                        self.assertEqual(result['matched_item_count'], 0)
                        self.assertEqual(result['ready_for_human_review_count'], 0)
                        self.assertEqual(result['queue_state'][0]['status'], 'queued')

    def test_legacy_small_and_exact_cap_summaries_retain_queue_transition_parity(self):
        import os
        for family in ('legacy_no_version', 'legacy_v1'):
            expected = self.payload(family); raw = json.dumps(expected).encode('utf-8')
            for size in (len(raw), self.cap - 1, self.cap):
                for dirname in ('ordinary', 'with spaces'):
                    with self.subTest(family=family, size=size, directory=dirname):
                        path = self.area / dirname / 'summary.json'; path.parent.mkdir(exist_ok=True)
                        path.write_bytes(raw + b' ' * (size - len(raw)))
                        original_read = os.read
                        with patch.object(self.closure.os, 'read', wraps=original_read) as read:
                            self.assertEqual(self.closure.read_verifier_summary(path), expected)
                        self.assertGreater(read.call_count, 0, 'bounded positive read was not reached')
                        self.assertEqual(sum(call.args[1] for call in read.call_args_list), size)
                        result = self.consume(path, str((family, size, dirname)))
                        self.assertEqual(result['matched_item_count'], 1)
                        self.assertEqual(result['ready_for_human_review_count'], 1)
                        self.assertEqual(result['queue_state'][0]['status'], 'ready_for_human_review')


class PublicationReceiptTests(unittest.TestCase):
    def setUp(self):
        from evaluation_v2_admission_smoke import AnchoredPublicationTests
        from tools import run_ab_result_verifier as verifier
        from tools import run_self_correction_queue_closure as closure
        self.verifier = verifier; self.closure = closure
        self.fixture = AnchoredPublicationTests(); self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.area = self.fixture.area
        self.sequence = 0

    def produce(self, *, default=False, blocked=False):
        self.sequence += 1
        root, args = self.fixture.invocation('receipt-' + str(self.sequence), blocked=blocked)
        args.experiment_id = 'synthetic-receipt'; args.payload_hash = 'fixed-contract'
        if default:
            for name in self.verifier.COMPARISON_OPTIONS: setattr(args, name, None)
        result = self.fixture.call(args)
        return root, args, result, Path(args.output_dir)

    def consume(self, output):
        queue = self.area / ('queue-' + str(self.sequence) + '.json')
        write_json(queue, {'queued_experiments': [queue_item('synthetic-receipt', 'fixed-contract')]})
        with contextlib.redirect_stdout(io.StringIO()):
            return run(Namespace(queue_path=str(queue), verifier_summary=[], verifier_dir=[str(output)],
                                 output_dir=str(self.area / ('closure-' + str(self.sequence)))))

    def assert_not_consumable(self, output):
        result = self.consume(output)
        self.assertEqual(result['matched_item_count'], 0)
        self.assertEqual(result['ready_for_human_review_count'], 0)
        self.assertEqual(result['queue_state'][0]['status'], 'queued')
        self.assertIs(result['production_mutation_allowed'], False)
        self.assertIs(result['live_trading_allowed'], False)

    def test_fresh_default_and_optin_producers_have_verified_receipts_and_ordinary_metric_parity(self):
        for default in (False, True):
            for blocked in (False, True) if not default else (False,):
                with self.subTest(default=default, blocked=blocked):
                    _, _, result, output = self.produce(default=default, blocked=blocked)
                    self.assertTrue(result['current_receipt'])
                    self.assertEqual(result['status'], 'blocked_comparison_admission' if blocked else 'review_candidate_ready')
                    if default: self.assertNotIn('comparison_admission', result)
                    summaries = self.closure.load_verifier_summaries([], [str(output)])
                    self.assertEqual(len(summaries), 1)
                    self.assertEqual(summaries[0]['candidates'], result['candidates'])
                    consumed = self.consume(output)
                    self.assertEqual(consumed['ready_for_human_review_count'], 0 if blocked else 1)
                    if not blocked:
                        row = result['candidates'][0]
                        self.assertEqual(row['cagr'], .52)
                        self.assertEqual(row['max_dd'], -.24)
                        self.assertEqual(row['is_cagr'], .31)
                    self.assertIs(consumed['production_mutation_allowed'], False)
                    self.assertIs(consumed['live_trading_allowed'], False)

    def test_current_witnessed_summaries_at_or_below_cap_retain_candidate_parity(self):
        import hashlib
        import os
        for default in (False, True):
            for size in (self.verifier.MAX_REPORT_BYTES - 1, self.verifier.MAX_REPORT_BYTES):
                with self.subTest(default=default, size=size):
                    _, _, result, output = self.produce(default=default)
                    path = output / 'summary.json'; raw = path.read_bytes()
                    self.assertLess(len(raw), size)
                    raw += b' ' * (size - len(raw)); path.write_bytes(raw)
                    witness_path = output / self.verifier.COMPLETION_LEAF
                    witness = json.loads(witness_path.read_bytes())
                    witness['reports']['summary.json'] = {'bytes': size, 'sha256': hashlib.sha256(raw).hexdigest()}
                    write_json(witness_path, witness)
                    original_read = os.read
                    with patch.object(self.closure.os, 'read', wraps=original_read) as read:
                        summaries = self.closure.load_verifier_summaries([], [str(output)])
                    self.assertGreater(read.call_count, 0, 'valid current summary read was not reached')
                    self.assertEqual(len(summaries), 1)
                    self.assertEqual(summaries[0]['candidates'], result['candidates'])
                    self.assertEqual(self.consume(output)['ready_for_human_review_count'], 1)

    def strip_publication_metadata(self, output, version):
        path = output / 'summary.json'; payload = json.loads(path.read_bytes())
        for name in ('comparison_publication', 'comparison_admission', 'current_receipt'): payload.pop(name, None)
        if version == 'plain_v1': payload['schema_version'] = 'ab-result-verifier-v1'
        else: payload.pop('schema_version', None)
        write_json(path, payload)
        return path

    def test_remaining_witness_blocks_plain_metadata_downgrade_in_reader_and_real_queue(self):
        import hashlib
        for version in ('plain_v1', 'no_version'):
            for state in ('valid', 'malformed', 'empty', 'partial', 'stale', 'matching_plain_hash'):
                with self.subTest(version=version, witness=state):
                    _, _, _, output = self.produce(default=True)
                    summary = self.strip_publication_metadata(output, version)
                    path = output / self.verifier.COMPLETION_LEAF
                    if state in ('malformed', 'empty', 'partial'):
                        path.write_bytes({'malformed': b'[]', 'empty': b'', 'partial': b'{'}[state])
                    elif state in ('stale', 'matching_plain_hash'):
                        witness = json.loads(path.read_bytes())
                        if state == 'stale': witness['generation'] = '0' * 32
                        else:
                            raw = summary.read_bytes()
                            witness['reports']['summary.json'] = {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
                        write_json(path, witness)
                    self.assertEqual(self.closure.load_verifier_summaries([], [str(output)]), [])
                    self.assert_not_consumable(output)

    def test_witness_entry_types_wrong_summary_name_and_denied_probe_cannot_be_legacy_absence(self):
        import os
        import subprocess
        states = ('wrong_summary_name', 'directory', 'symlink', 'dangling_symlink', 'hardlink',
                  'permission_error', 'io_error') + (('junction',) if os.name == 'nt' else ())
        for version in ('plain_v1', 'no_version'):
            for state in states:
                with self.subTest(version=version, witness=state):
                    _, _, _, output = self.produce(default=True)
                    summary = self.strip_publication_metadata(output, version)
                    marker = output / self.verifier.COMPLETION_LEAF
                    original_marker = marker.read_bytes(); target = self.area / ('marker-' + str(self.sequence))
                    target.write_bytes(original_marker)
                    if state == 'wrong_summary_name':
                        renamed = output / 'renamed-summary.json'; summary.rename(renamed)
                        queue = self.area / ('wrong-name-queue-' + str(self.sequence) + '.json')
                        write_json(queue, {'queued_experiments': [queue_item('synthetic-receipt', 'fixed-contract')]})
                        self.assertEqual(self.closure.load_verifier_summaries([str(renamed)], []), [])
                        with contextlib.redirect_stdout(io.StringIO()):
                            result = run(Namespace(queue_path=str(queue), verifier_summary=[str(renamed)], verifier_dir=[],
                                                   output_dir=str(self.area / ('wrong-name-closure-' + str(self.sequence)))))
                        self.assertEqual(result['matched_item_count'], 0)
                        self.assertEqual(result['ready_for_human_review_count'], 0)
                        self.assertEqual(result['queue_state'][0]['status'], 'queued')
                    elif state in ('directory', 'symlink', 'dangling_symlink', 'hardlink', 'junction'):
                        marker.unlink()
                        if state == 'directory': marker.mkdir()
                        elif state == 'hardlink': os.link(target, marker)
                        elif state == 'junction':
                            outside = self.area / ('junction-target-' + str(self.sequence)); outside.mkdir()
                            (outside / 'caller.txt').write_bytes(b'preserved-caller-bytes')
                            link = subprocess.run(['cmd', '/c', 'mklink', '/J', str(marker), str(outside)], capture_output=True)
                            self.assertEqual(link.returncode, 0, 'actual Windows witness junction creation failed')
                            self.assertTrue(marker.is_junction())
                        else:
                            if state == 'dangling_symlink': target.unlink()
                            os.symlink(target, marker)
                        self.assertEqual(self.closure.load_verifier_summaries([], [str(output)]), [])
                        self.assert_not_consumable(output)
                        if state in ('symlink', 'dangling_symlink'): self.assertTrue(marker.is_symlink())
                        elif state == 'directory': self.assertTrue(marker.is_dir())
                        elif state == 'junction':
                            self.assertTrue(marker.is_junction())
                            self.assertEqual((outside / 'caller.txt').read_bytes(), b'preserved-caller-bytes')
                        else: self.assertEqual(target.read_bytes(), original_marker)
                    else:
                        marker.unlink(); original_lstat = os.lstat; fired = []
                        def probe(path, *args, **kwargs):
                            if Path(path) == marker:
                                fired.append(True)
                                raise PermissionError('private-token') if state == 'permission_error' else OSError('private-token')
                            return original_lstat(path, *args, **kwargs)
                        with patch.object(self.closure.os, 'lstat', new=probe):
                            self.assertEqual(self.closure.load_verifier_summaries([], [str(output)]), [])
                            self.assert_not_consumable(output)
                        self.assertTrue(fired, 'witness-entry probe error was not reached')

    def test_observed_witness_or_parent_changes_during_legacy_classification_fail_closed(self):
        import os
        for version in ('plain_v1', 'no_version'):
            for phase in ('appears_after_absence', 'disappears_after_presence', 'replaced_after_presence', 'parent_probe_error'):
                for api in ('reader', 'queue'):
                    with self.subTest(version=version, phase=phase, api=api):
                        _, _, _, output = self.produce(default=True)
                        summary = self.strip_publication_metadata(output, version)
                        marker = output / self.verifier.COMPLETION_LEAF
                        if phase not in ('disappears_after_presence', 'replaced_after_presence'): marker.unlink()
                        original_lstat = os.lstat; original_stat = os.stat; fired = False
                        def probe(path, *args, **kwargs):
                            nonlocal fired
                            if Path(path) == marker and not fired:
                                try: observed = original_lstat(path, *args, **kwargs)
                                except FileNotFoundError:
                                    fired = True
                                    if phase == 'appears_after_absence': marker.write_bytes(b'{')
                                    raise
                                else:
                                    fired = True; marker.unlink()
                                    if phase == 'replaced_after_presence': marker.write_bytes(b'{')
                                    return observed
                            return original_lstat(path, *args, **kwargs)
                        def parent_stat(path, *args, **kwargs):
                            if Path(path) == output and fired and phase == 'parent_probe_error':
                                raise PermissionError('private-token')
                            return original_stat(path, *args, **kwargs)
                        with patch.object(self.closure.os, 'lstat', new=probe), patch.object(self.closure.os, 'stat', new=parent_stat):
                            if api == 'reader': self.assertEqual(self.closure.load_verifier_summaries([], [str(output)]), [])
                            else: self.assert_not_consumable(output)
                        self.assertTrue(fired, 'actual witness-entry race observation was not reached')
                        self.assertTrue(output.joinpath('summary.json').exists())

    @unittest.skipUnless(__import__('os').name == 'posix', 'actual parent move with open summary requires POSIX')
    def test_missing_or_replaced_parent_after_witness_absence_cannot_expose_legacy_rows(self):
        import os
        for version in ('plain_v1', 'no_version'):
            for replacement in (False, True):
                for api in ('reader', 'queue'):
                    with self.subTest(version=version, replacement=replacement, api=api):
                        _, _, _, output = self.produce(default=True)
                        summary = self.strip_publication_metadata(output, version); original_bytes = summary.read_bytes()
                        marker = output / self.verifier.COMPLETION_LEAF; marker.unlink()
                        original_lstat = os.lstat; fired = False; moved = False
                        parked = output.with_name(output.name + '-parked')
                        def probe(path, *args, **kwargs):
                            nonlocal fired, moved
                            if Path(path) == marker and not fired:
                                try: return original_lstat(path, *args, **kwargs)
                                except FileNotFoundError:
                                    fired = True; output.rename(parked); moved = True
                                    if replacement: output.mkdir()
                                    raise
                            return original_lstat(path, *args, **kwargs)
                        with patch.object(self.closure.os, 'lstat', new=probe):
                            if api == 'reader': self.assertEqual(self.closure.load_verifier_summaries([], [str(output)]), [])
                            else: self.assert_not_consumable(output)
                        self.assertTrue(fired and moved, 'actual parent rename did not complete after the absence probe')
                        self.assertEqual((parked / 'summary.json').read_bytes(), original_bytes)

    @unittest.skipUnless(hasattr(__import__('os'), 'mkfifo'), 'actual POSIX witness FIFO requires Linux')
    def test_fifo_witness_without_writer_is_bounded_and_cannot_downgrade_metadata(self):
        import subprocess
        command = '''
import contextlib,io,json,os,pathlib,sys
from unittest.mock import patch
sys.path.insert(0,sys.argv[1])
from self_correction_queue_closure_smoke import PublicationReceiptTests
t=PublicationReceiptTests();t.setUp()
try:
 for version in ('plain_v1','no_version'):
  _,_,_,output=t.produce(default=True);t.strip_publication_metadata(output,version)
  marker=output/t.verifier.COMPLETION_LEAF;marker.unlink();os.mkfifo(marker)
  original=os.lstat;fired=[]
  def probe(path,*args,**kwargs):
   value=original(path,*args,**kwargs)
   if pathlib.Path(path)==marker:fired.append(True)
   return value
  with patch.object(t.closure.os,'lstat',new=probe):
   t.assertEqual(t.closure.load_verifier_summaries([], [str(output)]),[])
   t.assert_not_consumable(output)
  t.assertTrue(fired,'FIFO witness probe was not reached')
 print('POSIX_FIFO_WITNESS_TWO_VERSIONS_PASS')
finally:t.doCleanups()
'''
        result = subprocess.run([sys.executable] + (['-O'] if sys.flags.optimize else []) +
                                ['-c', command, str(REPO / 'tests')], capture_output=True, timeout=8)
        self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8', errors='replace'))
        self.assertIn(b'POSIX_FIFO_WITNESS_TWO_VERSIONS_PASS', result.stdout)

    def test_missing_partial_stale_malformed_or_incomplete_witness_cannot_promote(self):
        for mutation in ('missing', 'empty', 'partial', 'array', 'wrong_schema', 'stale_generation',
                         'missing_report', 'extra_report', 'bool_size', 'wrong_size', 'wrong_hash',
                         'nonfinite', 'duplicate_generation'):
            with self.subTest(mutation=mutation):
                _, _, _, output = self.produce()
                path = output / self.verifier.COMPLETION_LEAF
                witness = json.loads(path.read_bytes())
                if mutation == 'missing': path.unlink()
                elif mutation in ('empty', 'partial', 'array', 'nonfinite', 'duplicate_generation'):
                    raw = {'empty': b'', 'partial': b'{', 'array': b'[]', 'nonfinite': b'{"generation":NaN}',
                           'duplicate_generation': b'{"generation":"a","generation":"b"}'}[mutation]
                    path.write_bytes(raw)
                else:
                    if mutation == 'wrong_schema': witness['schema'] = 'unknown'
                    elif mutation == 'stale_generation': witness['generation'] = '0' * 32
                    elif mutation == 'missing_report': del witness['reports']['report.md']
                    elif mutation == 'extra_report': witness['reports']['unexpected'] = {}
                    elif mutation == 'bool_size': witness['reports']['summary.json']['bytes'] = True
                    elif mutation == 'wrong_size': witness['reports']['summary.json']['bytes'] += 1
                    elif mutation == 'wrong_hash': witness['reports']['summary.json']['sha256'] = '0' * 64
                    write_json(path, witness)
                self.assert_not_consumable(output)

    def test_new_protocol_metadata_never_downgrades_to_historical_plain_summary(self):
        for mutation in ('protocol_missing', 'protocol_null', 'generation_missing', 'generation_null',
                         'generation_bool', 'generation_bad', 'version_missing', 'version_old', 'version_bad',
                         'current_missing', 'current_false', 'current_null', 'current_string',
                         'all_metadata_missing_except_new_version', 'old_optin_no_witness'):
            with self.subTest(mutation=mutation):
                _, _, _, output = self.produce()
                path = output / 'summary.json'; summary = json.loads(path.read_bytes())
                if mutation == 'protocol_missing': del summary['comparison_publication']
                elif mutation == 'protocol_null': summary['comparison_publication'] = None
                elif mutation.startswith('generation_'):
                    if mutation == 'generation_missing': del summary['comparison_publication']['generation']
                    else: summary['comparison_publication']['generation'] = {'generation_null': None, 'generation_bool': True, 'generation_bad': '../path'}[mutation]
                elif mutation == 'version_missing': del summary['schema_version']
                elif mutation in ('version_old', 'version_bad'): summary['schema_version'] = 'ab-result-verifier-v1' if mutation == 'version_old' else True
                elif mutation == 'current_missing': del summary['current_receipt']
                elif mutation.startswith('current_'): summary['current_receipt'] = {'current_false': False, 'current_null': None, 'current_string': 'true'}[mutation]
                elif mutation == 'all_metadata_missing_except_new_version':
                    for name in ('comparison_publication', 'comparison_admission', 'current_receipt'): summary.pop(name, None)
                else:
                    summary.pop('comparison_publication'); summary['schema_version'] = 'ab-result-verifier-v1'
                    (output / self.verifier.COMPLETION_LEAF).unlink()
                write_json(path, summary)
                self.assert_not_consumable(output)

    def test_every_report_hash_size_and_generation_is_bound_and_old_witness_cannot_cover_a_retry(self):
        for leaf in self.verifier.REPORT_LEAVES:
            _, _, _, output = self.produce()
            path = output / leaf; path.write_bytes(path.read_bytes() + b' ')
            self.assert_not_consumable(output)
        _, args, first, output = self.produce()
        prior = (output / self.verifier.COMPLETION_LEAF).read_bytes()
        second = self.fixture.call(args)
        self.assertNotEqual(first['comparison_publication']['generation'], second['comparison_publication']['generation'])
        (output / self.verifier.COMPLETION_LEAF).write_bytes(prior)
        self.assert_not_consumable(output)

    def test_candidate_expansion_uses_the_verified_raw_summary_not_a_later_read(self):
        _, _, result, output = self.produce()
        original = self.verifier.completed_comparison_summary; fired = False
        def validate(path, raw):
            nonlocal fired
            parsed = original(path, raw)
            replacement = copy.deepcopy(parsed); replacement['candidates'] = []
            write_json(path, replacement); fired = True
            return parsed
        with patch.object(self.verifier, 'completed_comparison_summary', new=validate):
            summaries = self.closure.load_verifier_summaries([], [str(output)])
        self.assertTrue(fired, 'postvalidation summary substitution was not reached')
        self.assertEqual(summaries[0]['candidates'], result['candidates'])

    def test_failed_final_source_check_retained_positive_summary_has_no_completion_witness_or_consumable_rows(self):
        for default in (False, True):
            for cli in (False, True):
                with self.subTest(default=default, cli=cli):
                    root, args = self.fixture.invocation('precommit-' + str((default, cli)))
                    args.experiment_id = 'synthetic-receipt'; args.payload_hash = 'fixed-contract'
                    if default:
                        for name in self.verifier.COMPARISON_OPTIONS: setattr(args, name, None)
                    before = self.fixture.fixture.census(root); summary_verified = False; fired = False
                    original_verify = self.verifier.ReportDirectory.verify_installed
                    original_guard = self.verifier.ReportDirectory.guard
                    original_unlink = self.verifier.ReportDirectory.unlink_owned
                    def verify(directory, name, size, digest):
                        nonlocal summary_verified
                        original_verify(directory, name, size, digest)
                        if name == 'summary.json': summary_verified = True
                    def guard(directory):
                        nonlocal fired
                        if summary_verified:
                            fired = True; raise self.verifier.comparison_admission.AdmissionError('OUTPUT_PUBLICATION_PATH_CHANGED')
                        return original_guard(directory)
                    def unlink(directory, name):
                        if fired: return False
                        return original_unlink(directory, name)
                    with patch.object(self.verifier.ReportDirectory, 'verify_installed', new=verify), \
                         patch.object(self.verifier.ReportDirectory, 'guard', new=guard), \
                         patch.object(self.verifier.ReportDirectory, 'unlink_owned', new=unlink):
                        result = self.fixture.call(args, cli)
                    self.assertTrue(summary_verified and fired, 'postsummary validation and unavailable cleanup were not reached')
                    if cli: self.assertEqual(result, 2)
                    else: self.fixture.assert_bounded(result)
                    output = Path(args.output_dir); self.sequence += 1
                    retained = json.loads((output / 'summary.json').read_bytes())
                    self.assertTrue(retained['current_receipt'])
                    self.assertEqual(retained['candidates'][0]['decision'], 'promote_candidate_review_only')
                    self.assertFalse((output / self.verifier.COMPLETION_LEAF).exists())
                    self.assert_not_consumable(output)
                    self.assertEqual(self.fixture.fixture.census(root), before)

    def test_witness_commit_delivery_errors_are_uncertain_not_explicit_data_rejection(self):
        for after in (False, True):
            for cli in (False, True):
                with self.subTest(after=after, cli=cli):
                    _, args = self.fixture.invocation('uncertain-' + str((after, cli)))
                    args.experiment_id = 'synthetic-receipt'; args.payload_hash = 'fixed-contract'
                    original = self.verifier.ReportDirectory.replace; fired = False
                    def replace(directory, source, destination):
                        nonlocal fired
                        if destination == self.verifier.COMPLETION_LEAF:
                            fired = True
                            if after: original(directory, source, destination)
                            raise OSError('private-token')
                        return original(directory, source, destination)
                    with patch.object(self.verifier.ReportDirectory, 'replace', new=replace): result = self.fixture.call(args, cli)
                    self.assertTrue(fired, 'final witness installation was not reached')
                    if cli: self.assertEqual(result, 2)
                    else:
                        self.assertEqual(result['status'], 'comparison_publication_uncertain')
                        self.assertIsNone(result['current_receipt'])
                        self.assertEqual(result['candidates'], [])
                        self.assertNotIn('private-token', json.dumps(result))
                    self.sequence += 1
                    consumed = self.consume(Path(args.output_dir))
                    self.assertEqual(consumed['ready_for_human_review_count'], 1 if after else 0)

    def test_witness_delivery_readback_failure_preserves_verified_files_and_classifies_uncertainty(self):
        for cli in (False, True):
            _, args = self.fixture.invocation('witness-readback-' + str(cli))
            args.experiment_id = 'synthetic-receipt'; args.payload_hash = 'fixed-contract'
            original = self.verifier.ReportDirectory.verify_installed; fired = False
            def verify(directory, name, size, digest):
                nonlocal fired
                if name == self.verifier.COMPLETION_LEAF:
                    original(directory, name, size, digest)
                    fired = True; raise OSError('private-token')
                return original(directory, name, size, digest)
            with patch.object(self.verifier.ReportDirectory, 'verify_installed', new=verify): result = self.fixture.call(args, cli)
            self.assertTrue(fired, 'installed witness delivery readback was not reached')
            if cli: self.assertEqual(result, 2)
            else:
                self.assertEqual(result['status'], 'comparison_publication_uncertain')
                self.assertIsNone(result['current_receipt'])
                self.assertEqual(result['candidates'], [])
            self.sequence += 1
            self.assertEqual(self.consume(Path(args.output_dir))['ready_for_human_review_count'], 1)

    def test_witness_foreign_links_and_actual_summary_change_during_validation_fail_closed(self):
        import os
        for mutation in ('witness_symlink', 'witness_hardlink', 'summary_change'):
            with self.subTest(mutation=mutation):
                _, _, _, output = self.produce()
                if mutation in ('witness_symlink', 'witness_hardlink'):
                    leaf = output / self.verifier.COMPLETION_LEAF
                    outside = self.area / ('outside-witness-' + str(self.sequence))
                    before = leaf.read_bytes()
                    if mutation == 'witness_symlink':
                        outside.write_bytes(before); leaf.unlink(); leaf.symlink_to(outside)
                    else: os.link(leaf, outside)
                    self.assert_not_consumable(output)
                    self.assertEqual(outside.read_bytes(), before)
                else:
                    original = self.verifier.completed_comparison_summary; fired = False
                    def change(path, raw):
                        nonlocal fired
                        replacement = json.loads(raw); replacement['candidates'] = []
                        write_json(path, replacement); fired = True
                        return original(path, raw)
                    with patch.object(self.verifier, 'completed_comparison_summary', new=change): self.assert_not_consumable(output)
                    self.assertTrue(fired, 'summary read-to-hash boundary was not reached')

    def test_postcommit_close_errors_are_reported_without_demoting_committed_receipt(self):
        import os
        for cli in (False, True):
            _, args = self.fixture.invocation('postcommit-close-' + str(cli))
            args.experiment_id = 'synthetic-receipt'; args.payload_hash = 'fixed-contract'
            original_verify = self.verifier.ReportDirectory.verify_installed
            original_close = os.close; committed = False; fired = False
            def verify(directory, name, size, digest):
                nonlocal committed
                original_verify(directory, name, size, digest)
                if name == self.verifier.COMPLETION_LEAF: committed = True
            def close(fd):
                nonlocal fired
                original_close(fd)
                if committed:
                    fired = True; raise OSError('private-token')
            transcript = io.StringIO()
            with patch.object(self.verifier.ReportDirectory, 'verify_installed', new=verify), \
                 patch.object(os, 'close', new=close), contextlib.redirect_stdout(transcript):
                # Call directly to retain the actual warning telemetry.
                if cli:
                    values = ['--baseline-run', args.baseline_run, '--candidate-run', args.candidate_run[0],
                              '--output-dir', args.output_dir, '--experiment-id', args.experiment_id,
                              '--payload-hash', args.payload_hash]
                    for name in self.verifier.COMPARISON_OPTIONS: values += ['--' + name.replace('_', '-'), getattr(args, name)]
                    result = self.verifier.main(values)
                else: result = self.verifier.run(args)
            self.assertTrue(committed and fired, 'native close after verified witness was not reached')
            self.assertIn('publication_resource_cleanup_warning', transcript.getvalue())
            self.assertNotIn('private-token', transcript.getvalue())
            if cli: self.assertEqual(result, 0)
            else:
                self.assertEqual(result['status'], 'review_candidate_ready')
                self.assertIs(result['current_receipt'], True)
            self.sequence += 1
            self.assertEqual(self.consume(Path(args.output_dir))['ready_for_human_review_count'], 1)

    @unittest.skipUnless(sys.platform == 'win32', 'actual Windows exclusive witness copy operations')
    def test_windows_witness_partial_copy_sync_and_owned_temp_cleanup_have_honest_uncertainty(self):
        import os
        for phase in ('short_write_error', 'fsync', 'temp_cleanup'):
            for cli in (False, True):
                with self.subTest(phase=phase, cli=cli):
                    _, args = self.fixture.invocation('witness-final-' + str((phase, cli)))
                    args.experiment_id = 'synthetic-receipt'; args.payload_hash = 'fixed-contract'
                    descriptor = None; active = False; fired = False; writes = 0
                    original_create = self.verifier.ReportDirectory.create_exclusive_leaf
                    original_write = os.write; original_sync = os.fsync
                    original_replace = self.verifier.ReportDirectory.replace
                    original_unlink = self.verifier.ReportDirectory.unlink_owned
                    def create(directory, name):
                        nonlocal descriptor
                        result = original_create(directory, name)
                        if name == self.verifier.COMPLETION_LEAF: descriptor = result
                        return result
                    def replace(directory, source, destination):
                        nonlocal active
                        active = destination == self.verifier.COMPLETION_LEAF
                        return original_replace(directory, source, destination)
                    def write(fd, raw):
                        nonlocal writes, fired
                        if fd == descriptor and phase == 'short_write_error':
                            writes += 1
                            if writes == 1: return original_write(fd, raw[:len(raw)//2])
                            fired = True; raise OSError('private-token')
                        return original_write(fd, raw)
                    def sync(fd):
                        nonlocal fired
                        if fd == descriptor and phase == 'fsync':
                            fired = True; raise OSError('private-token')
                        return original_sync(fd)
                    def unlink(directory, name):
                        nonlocal fired
                        if active and phase == 'temp_cleanup' and name.startswith('.ab-report-') and not fired:
                            fired = True; raise OSError('private-token')
                        return original_unlink(directory, name)
                    with patch.object(self.verifier.ReportDirectory, 'create_exclusive_leaf', new=create), \
                         patch.object(self.verifier.ReportDirectory, 'replace', new=replace), \
                         patch.object(self.verifier.ReportDirectory, 'unlink_owned', new=unlink), \
                         patch.object(os, 'write', new=write), patch.object(os, 'fsync', new=sync):
                        result = self.fixture.call(args, cli)
                    self.assertTrue(fired, 'specific final witness I/O phase was not reached')
                    if cli: self.assertEqual(result, 2)
                    else:
                        self.assertEqual(result['status'], 'comparison_publication_uncertain')
                        self.assertIsNone(result['current_receipt'])
                    self.sequence += 1
                    consumed = self.consume(Path(args.output_dir))
                    self.assertEqual(consumed['ready_for_human_review_count'], 0 if phase == 'short_write_error' else 1)


def main():
    suite = unittest.TestSuite([unittest.FunctionTestCase(test_queue_closure_maps_verifier_decisions_to_statuses),
                               unittest.defaultTestLoader.loadTestsFromTestCase(SummaryReadBudgetTests),
                               unittest.defaultTestLoader.loadTestsFromTestCase(PublicationReceiptTests)])
    return 0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
