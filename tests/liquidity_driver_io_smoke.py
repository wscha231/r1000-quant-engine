"""Offline IO/adapter tests; fake transport is NOT a real Drive validation."""
from __future__ import annotations
import copy
import gzip
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from liquidity_driver_context_smoke import fixture, run, ASOF, SHA
from tools.liquidity_driver_context import ContractError, INPUT_SCHEMA, encoded
from tools.liquidity_driver_io import (from_verified_lake, parse_json,
    publish_diagnostic, sha, stage_liquidity_sources, write_once)


class FakeLake:
    def __init__(self):
        self.parent = 'a'*64; self.pending = {}; self.writes = []; self.blocked_keys = []
        self.catalog = {'datasets': {}}
        self.raw = gzip.compress(b'synthetic-provider-response', mtime=0)
        self.raw_id = sha(self.raw)
        self.receipt = dict(commit_sha256=self.parent, catalog_sha256='b'*64,
            execution_receipt_sha256='c'*64, eligible_for_selector=False,
            study_recomputed_from_drive=True, quality_status='PARTIAL')
        ds = fixture()['datasets']['SOFR']
        self.rows = copy.deepcopy(ds['rows'])
        for row in self.rows:
            del row['retrieved_at']; del row['available_at']
        self.catalog['datasets']['current/SOFR'] = dict(series='SOFR', frequency='daily',
            unit='percent', evidence='current_only', status='COLLECTED',
            raw_objects=[self.raw_id], normalized='d'*64, retrieved_at=ASOF)
    def verified_execution(self): return self.receipt
    def read_hash(self, group, identity): return encoded({'catalog': 'b'*64})
    def get_bytes(self, identity): return self.raw
    def get_records(self, key): return self.rows
    def dataset(self, key, pages, rows, metadata): self.writes.append((key, metadata))
    def blocked(self, key, exc): self.blocked_keys.append(key)


class IOTests(unittest.TestCase):
    def test_lake_receipt_availability_rehydration(self):
        lake = FakeLake(); packet = from_verified_lake(lake)
        row = packet['datasets']['SOFR']['rows'][-1]
        self.assertEqual(row['available_at'], ASOF)
        self.assertEqual(row['retrieved_at'], ASOF)
        self.assertEqual(len(packet['missing_sources']), 16)
        self.assertEqual(lake.writes, [])

    def test_lake_incomplete_execution_fails(self):
        lake = FakeLake(); lake.receipt['study_recomputed_from_drive'] = False
        with self.assertRaises(ContractError): from_verified_lake(lake)

    def test_receipt_mismatch_fails(self):
        lake = FakeLake(); lake.receipt['catalog_sha256'] = 'e'*64
        with self.assertRaises(ContractError): from_verified_lake(lake)

    def test_pending_unpublished_lake_fails(self):
        lake = FakeLake(); lake.pending = {'something': 'unpublished'}
        with self.assertRaises(ContractError): from_verified_lake(lake)

    def test_corrupt_raw_hash_fails(self):
        lake = FakeLake(); lake.raw = gzip.compress(b'changed')
        with self.assertRaises(ContractError): from_verified_lake(lake)

    def test_lake_unit_mismatch_fails(self):
        lake = FakeLake(); lake.catalog['datasets']['current/SOFR']['unit'] = 'millions_usd'
        with self.assertRaises(ContractError): from_verified_lake(lake)

    def test_stale_dataset_not_older_success(self):
        lake = FakeLake(); lake.catalog['datasets']['current/SOFR']['status'] = 'STALE_RETAINED'
        packet = from_verified_lake(lake)
        self.assertNotIn('SOFR', packet['datasets'])
        self.assertEqual(len(packet['missing_sources']), 17)

    def test_alfred_does_not_fall_back_to_current(self):
        packet = from_verified_lake(FakeLake(), mode='alfred')
        self.assertEqual(packet['datasets'], {})

    def test_missing_rows_restored_as_null(self):
        lake = FakeLake()
        lake.catalog['datasets']['current/SOFR']['missing_observation_dates'] = ['2026-09-12']
        packet = from_verified_lake(lake)
        self.assertIsNone(packet['datasets']['SOFR']['rows'][-1]['value'])

    def test_bank_callback_stages_only_no_publish(self):
        lake = FakeLake()
        fake = types.ModuleType('tools.macro_history_sources')
        fake.fetch = lambda sid, start, end, mode: ([b'synthetic'], ASOF)
        fake.parse_graph = lambda raw, sid, start, end, at: ([dict(series=sid,
            observation_date='2026-09-09', value=1., available_at=at,
            retrieved_at=at, evidence='current_only')], [])
        with patch.dict(sys.modules, {'tools.macro_history_sources': fake}):
            r = stage_liquidity_sources(lake, '2025-01-01', '2026-09-14')
        self.assertEqual(len(lake.writes), 6)
        self.assertFalse(r['published'])
        self.assertIn('current/TOTCI', [k for k, _ in lake.writes])
        self.assertNotIn('current/BUSLOANS', [k for k, _ in lake.writes])

    def test_callback_errors_redacted_not_published(self):
        lake = FakeLake(); fake = types.ModuleType('tools.macro_history_sources')
        def fail(*_): raise ValueError('private-api-key-must-not-appear')
        fake.fetch = fail; fake.parse_graph = fail
        with patch.dict(sys.modules, {'tools.macro_history_sources': fake}):
            r = stage_liquidity_sources(lake, '2025-01-01', '2026-09-14')
        self.assertEqual(len(lake.blocked_keys), 6)
        self.assertEqual(lake.writes, [])
        self.assertNotIn('private-api-key', json.dumps(r))

    def test_manifest_last_and_repeat_identical(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); r = run(); first = publish_diagnostic(root, r)
            second = publish_diagnostic(root, r)
            self.assertEqual(first, second)
            folder = root / first['context_sha256']
            for name, digest in first['members'].items():
                self.assertEqual(sha((folder/name).read_bytes()), digest)
            self.assertFalse(first['accepted_state'])
            self.assertFalse((root/'latest.json').exists())

    def test_write_failure_has_no_manifest(self):
        def fail(path, raw):
            if path.name == 'report.md': raise OSError('synthetic failure')
            write_once(path, raw)
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(OSError): publish_diagnostic(Path(tmp), run(), writer=fail)
            self.assertEqual(list(Path(tmp).rglob('manifest.json')), [])

    def test_corrupt_readback_has_no_manifest(self):
        def corrupt(path, raw): write_once(path, b'wrong')
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ContractError): publish_diagnostic(Path(tmp), run(), writer=corrupt)
            self.assertEqual(list(Path(tmp).rglob('manifest.json')), [])

    def test_immutable_conflict_and_symlink_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)/'object'; write_once(target, b'old')
            with self.assertRaises(ContractError): write_once(target, b'new')
            link = Path(tmp)/'alias'; link.symlink_to(target)
            with self.assertRaises(ContractError): write_once(link, b'old')

    def test_duplicate_json_and_nonfinite_fail(self):
        for raw in (b'{"value":1,"value":2}', b'{"value":NaN}', b'{"value":Infinity}'):
            with self.assertRaises(ContractError): parse_json(raw)

    def test_cli_end_to_end_and_hash_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); input_path = root/'input.json'; input_path.write_bytes(encoded(fixture()))
            cmd = [sys.executable, str(ROOT/'tools/liquidity_driver_io.py'), '--input', str(input_path),
                '--as-of', ASOF, '--source-commit', SHA, '--output-dir', str(root/'out')]
            proc = subprocess.run(cmd, text=True, capture_output=True)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertTrue(json.loads(proc.stdout)['fixture_only'])
            proc = subprocess.run(cmd+['--expected-input-sha256', '0'*64], text=True, capture_output=True)
            self.assertEqual(proc.returncode, 3)

    def test_cli_missing_data_not_success_green(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); src = root/'missing.json'
            src.write_bytes(encoded(dict(schema=INPUT_SCHEMA, datasets={})))
            cmd = [sys.executable, str(ROOT/'tools/liquidity_driver_io.py'), '--input', str(src),
                '--as-of', ASOF, '--source-commit', SHA, '--output-dir', str(root/'out')]
            proc = subprocess.run(cmd, text=True, capture_output=True)
            self.assertEqual(proc.returncode, 2)
            self.assertEqual(json.loads(proc.stdout)['quality'], 'DEGRADED')


if __name__ == '__main__':
    unittest.main()
