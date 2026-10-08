#!/usr/bin/env python3
"""Frozen-reader contracts. All generated prices are synthetic, not admission."""
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.long_history_lake import Lake, LocalTransport, PREFIX, packed
from tools.macro_history_sources import digest, encoded
from tools.research_data_access import (
    ContractError, PRICE_COLUMNS, PREFIX_V1, REGISTRY, ResearchDataReader, pinned_lake,
)

DECISION = '2026-10-08T07:30:00Z'
SESSIONS = ['2026-07-01', '2026-07-02', '2026-07-06']


def instrument(ticker):
    return dict(instrument_id='FIXTURE:US:' + ticker, ticker=ticker, market='US',
        mic='XNAS' if ticker == 'QQQ' else 'XNYS', timezone='America/New_York',
        calendar='FIXTURE_CALENDAR', currency='USD', adjustment_basis='SPLIT_ADJUSTED')


def prices(ticker='SPY'):
    return [dict(instrument_id=instrument(ticker)['instrument_id'], ticker=ticker,
        session_date=s, available_from=s + 'T21:00:00Z',
        open=100.0, high=102.0, low=99.0, close=101.0, volume=10.0) for s in SESSIONS]


class ReaderTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.transport = LocalTransport(self.root / 'archive')
        self.reader = ResearchDataReader(self.transport)
        self.manifest = dict(schema='research-data-generation-v1',
            eligible_for_selector=False, created_at='2026-10-07T23:00:00Z',
            source_run_id='FIXTURE_RESEARCH_ONLY', datasets=[dict(dataset_id='ds.us.prices.daily',
                schema='price-daily-v1', source=dict(provider='synthetic_contract_fixture',
                    license='FIXTURE_ONLY', access_policy='LOCAL_TEST_ONLY', classification='CONTRACT_FIXTURE',
                    admission_state='RESEARCH_BYTES_ONLY', eligible_purposes=['discovery', 'research'],
                    pit_status='PIT_PROXY', corporate_action_status='VERIFIED', lifecycle_status='VERIFIED',
                    producer_code_sha='1' * 40, producer_config_sha256='2' * 64,
                    source_receipt_sha256='3' * 64, raw_source_sha256=['4' * 64],
                    available_from='2026-10-07T21:00:00Z', collected_at='2026-10-07T22:00:00Z',
                    expires_at='2026-10-09T00:00:00Z'), files=[])])
        self.add_file(prices())
        self.add_file(prices('QQQ'))

    @property
    def spec(self):
        return self.manifest['datasets'][0]

    def add_file(self, rows, *, format_name='jsonl', raw=None, identity=None):
        raw = raw if raw is not None else b''.join(encoded(r) for r in rows)
        h = digest(raw)
        item = dict(storage='archive', format=format_name, sha256=h, bytes=len(raw), rows=len(rows),
            start=rows[0]['session_date'], end=rows[-1]['session_date'], columns=dict(PRICE_COLUMNS),
            instrument=identity or instrument(rows[0]['ticker']))
        self.spec['files'].append(item)
        self.transport.write(f'{PREFIX_V1}/objects/{h}', raw)
        return item

    def generation(self):
        raw = encoded(self.manifest)
        generation = digest(raw)
        self.transport.write(f'{PREFIX_V1}/generations/{generation}', raw)
        return generation

    def read(self, generation=None, **kwargs):
        options = dict(decision_time=DECISION, purpose='research',
            instrument_ids=['FIXTURE:US:SPY', 'FIXTURE:US:QQQ'], required_start=SESSIONS[0],
            required_end=SESSIONS[-1], minimum_rows=3, required_sessions=SESSIONS, consumer_id='analysis')
        options.update(kwargs)
        return self.reader.read('ds.us.prices.daily', generation or self.generation(), **options)

    def replace_spy(self, rows, **kwargs):
        self.spec['files'] = self.spec['files'][1:]
        return self.add_file(rows, **kwargs)

    def blocked(self, code, **kwargs):
        with self.assertRaisesRegex(ContractError, code):
            self.read(**kwargs)

    def test_two_independent_consumers_same_generation_and_bytes(self):
        generation = self.generation()
        with patch.object(self.transport, 'write', side_effect=AssertionError('SOURCE_WRITE')), \
             patch('tools.long_history_lake.get_public', side_effect=AssertionError('PROVIDER_REFRESH')), \
             patch('tools.long_history_lake.fetch_fred_retry', side_effect=AssertionError('PROVIDER_REFRESH')):
            # Different instances and different computations, with fresh archive reads.
            a = self.read(generation, consumer_id='feature_builder', restore_to=self.root / 'features')
            self.reader = ResearchDataReader(self.transport)
            b = self.read(generation, consumer_id='coverage_auditor', restore_to=self.root / 'coverage')
            mean_close = sum(r['close'] for r in a.rows) / len(a.rows)
            by_security = {i: sum(r['instrument_id'] == i for r in b.rows)
                           for i in ['FIXTURE:US:SPY', 'FIXTURE:US:QQQ']}
        self.assertEqual(mean_close, 101.0)
        self.assertEqual(set(by_security.values()), {3})
        self.assertEqual(a.files, b.files)
        for key in ('data_generation_id', 'manifest_sha256', 'file_sha256', 'row_set_sha256'):
            self.assertEqual(a.receipt[key], b.receipt[key])
        self.assertFalse(a.receipt['eligible_for_economics'])
        self.assertFalse(a.receipt['eligible_for_selector'])
        self.assertEqual(a.receipt['provider_refresh_count'], 0)
        self.assertTrue(a.receipt['requested_session_coverage_verified'])
        self.assertFalse(a.receipt['calendar_source_verified'])

    def test_bld_three_rows_cannot_meet_two_hundred(self):
        self.add_file(prices('BLD'))
        self.blocked('SHORT_HISTORY', instrument_ids=['FIXTURE:US:BLD'], minimum_rows=200)

    def test_spy_and_qqq_stale_end_are_not_current(self):
        for iid in ('FIXTURE:US:SPY', 'FIXTURE:US:QQQ'):
            with self.subTest(iid=iid):
                self.blocked('MISSING_PERIOD', instrument_ids=[iid], required_end='2026-10-07')

    def test_boolean_price_is_not_one(self):
        rows = prices(); rows[0]['close'] = True
        self.replace_spy(rows)
        self.blocked('INVALID_PRICE_VALUE')

    def test_oversized_json_integers_use_finite_refusal_code(self):
        for field in ('open', 'high', 'low', 'close', 'volume'):
            with self.subTest(field=field):
                rows = prices(); rows[0][field] = 10 ** 1000
                self.replace_spy(rows)
                self.blocked('INVALID_PRICE_VALUE')

    def test_missing_prices_do_not_become_zero(self):
        rows = prices(); rows[0]['close'] = None
        self.replace_spy(rows)
        self.blocked('INVALID_PRICE_VALUE')

    def test_nan_199_of_200_is_not_valid_history(self):
        rows = [dict(prices()[0], close=float('nan')) for _ in range(199)] + [prices()[0]]
        raw = b''.join((json.dumps(r) + '\n').encode() for r in rows)
        self.replace_spy(rows, raw=raw)
        self.blocked('NONFINITE_VALUE')

    def test_two_hundred_duplicate_dates_fail(self):
        self.replace_spy([prices()[0]] * 200)
        self.blocked('DUPLICATE_SESSION')

    def test_missing_internal_session_with_correct_bounds_fails(self):
        rows = prices(); rows.pop(1)
        self.replace_spy(rows)
        self.blocked('MISSING_SESSION', minimum_rows=2)

    def test_future_available_from_fails_before_any_slice(self):
        rows = prices(); rows[0]['available_from'] = '2026-10-09T00:00:00Z'
        self.replace_spy(rows)
        self.blocked('FUTURE_AVAILABLE_FROM')

    def test_future_collection_clock(self):
        self.spec['source']['collected_at'] = '2026-10-09T00:00:00Z'
        self.blocked('FUTURE_SOURCE')

    def test_future_generation_clock(self):
        self.manifest['created_at'] = '2026-10-09T00:00:00Z'
        self.blocked('FUTURE_GENERATION')

    def test_naive_availability_cannot_use_mtime(self):
        self.spec['source']['available_from'] = '2026-10-07'
        self.blocked('INVALID_AVAILABILITY')

    def test_invalid_or_unknown_timezone_offsets_fail_closed(self):
        for offset in ('+00:60', '-00:60', '+24:00', '-24:00', '+01:99', '-00:00'):
            with self.subTest(offset=offset, clock='source'):
                self.spec['source']['available_from'] = '2026-10-07T21:00:00' + offset
                self.blocked('INVALID_AVAILABILITY')
            self.spec['source']['available_from'] = '2026-10-07T21:00:00Z'
            with self.subTest(offset=offset, clock='row'):
                rows = prices(); rows[0]['available_from'] = SESSIONS[0] + 'T21:00:00' + offset
                self.replace_spy(rows)
                self.blocked('INVALID_AVAILABILITY')
            self.replace_spy(prices())

    def test_valid_explicit_timezone_offsets_preserve_availability(self):
        self.spec['source']['available_from'] = '2026-10-07T17:00:00-04:00'
        rows = prices(); rows[0]['available_from'] = SESSIONS[0] + 'T17:00:00-04:00'
        self.replace_spy(rows)
        self.assertEqual(len(self.read().rows), 6)

    def test_expired_generation_is_blocked(self):
        self.spec['source']['expires_at'] = '2026-10-08T00:00:00Z'
        self.blocked('STALE_GENERATION')

    def test_hash_tampering_fails(self):
        h = self.spec['files'][0]['sha256']
        (self.root / 'archive' / PREFIX_V1 / 'objects' / h).write_bytes(b'changed')
        self.blocked('HASH_MISMATCH')

    def test_manifest_tampering_fails(self):
        generation = self.generation()
        (self.root / 'archive' / PREFIX_V1 / 'generations' / generation).write_bytes(b'{}')
        self.blocked('HASH_MISMATCH', generation=generation)

    def test_missing_archive_cannot_fallback_to_verified_local_cache(self):
        generation = self.generation()
        result = self.read(generation, restore_to=self.root / 'cache_prices')
        (self.root / 'archive' / PREFIX_V1 / 'objects' / result.files[0][0]).unlink()
        self.blocked('ARCHIVE_UNAVAILABLE', generation=generation, restore_to=self.root / 'cache_prices')

    def test_wrong_generation_cannot_fallback_to_latest(self):
        self.generation()
        self.blocked('ARCHIVE_UNAVAILABLE', generation='f' * 64)

    def test_latest_is_not_a_generation_id(self):
        self.blocked('INVALID_SHA256', generation='latest')

    def test_schema_omission(self):
        self.spec['files'][0]['columns'].pop('available_from')
        self.blocked('FILE_SCHEMA')

    def test_file_row_and_byte_counts(self):
        for key, value, code in [('rows', 5, 'ROW_COUNT'), ('bytes', 1, 'FILE_BYTES')]:
            original = self.spec['files'][0][key]
            self.spec['files'][0][key] = value
            self.blocked(code)
            self.spec['files'][0][key] = original

    def test_file_period_mismatch(self):
        self.spec['files'][0]['end'] = '2026-07-07'
        self.blocked('FILE_PERIOD')

    def test_ticker_identity_mismatch(self):
        self.spec['files'][0]['instrument']['ticker'] = 'BLD'
        self.blocked('ROW_IDENTITY')

    def test_market_symbol_collision(self):
        rows = prices()
        for r in rows:
            r['instrument_id'] = 'FIXTURE:US:ANOTHER_SPY'
        ident = dict(instrument('SPY'), instrument_id='FIXTURE:US:ANOTHER_SPY')
        self.add_file(rows, identity=ident)
        self.blocked('SYMBOL_COLLISION')

    def test_changed_adjustment_basis_on_same_identity(self):
        rows = [dict(prices()[0], session_date='2026-06-30', available_from='2026-06-30T21:00:00Z')]
        self.add_file(rows, identity=dict(instrument('SPY'), adjustment_basis='RAW'))
        self.blocked('IDENTITY_DRIFT')

    def test_missing_lifecycle_pit_or_license(self):
        for field in ('lifecycle_status', 'pit_status', 'license'):
            original = self.spec['source'][field]
            self.spec['source'][field] = 'UNKNOWN'
            with self.assertRaises(ContractError):
                self.read()
            self.spec['source'][field] = original

    def test_fixture_and_pit_proxy_cannot_train_or_backtest(self):
        self.spec['source']['eligible_purposes'] += ['training', 'backtest']
        self.blocked('PIT_NOT_VERIFIED', purpose='training')
        self.blocked('PIT_NOT_VERIFIED', purpose='backtest')

    def test_eligible_purposes_reject_unhashable_and_nonstring_members(self):
        invalid = (
            'research', {'research': True}, ['research', {}],
            ['research', ['discovery']], ['research', True],
            ['research', 12], ['research', None], ['research', 1.5],
        )
        for value in invalid:
            with self.subTest(value=repr(value)):
                self.spec['source']['eligible_purposes'] = value
                self.blocked('PURPOSE_NOT_LICENSED')

    def test_eligible_purposes_duplicate_and_valid_unique(self):
        self.spec['source']['eligible_purposes'] = ['research', 'research']
        self.blocked('DUPLICATE_PURPOSE')
        self.spec['source']['eligible_purposes'] = ['research', 'discovery']
        self.assertEqual(len(self.read().rows), 6)

    def test_undeclared_instrument_and_purpose(self):
        self.blocked('MISSING_INSTRUMENT', instrument_ids=['FIXTURE:US:BLD'])
        self.spec['source']['eligible_purposes'] = ['discovery']
        self.blocked('PURPOSE_NOT_LICENSED')

    def test_mixed_unrequested_bad_file_is_not_silently_dropped(self):
        rows = prices('BLD'); rows[0]['close'] = None
        self.add_file(rows)
        self.blocked('INVALID_PRICE_VALUE', instrument_ids=['FIXTURE:US:SPY'])

    def test_gzip_jsonl_roundtrip(self):
        self.replace_spy(prices(), raw=packed(b''.join(encoded(r) for r in prices())), format_name='gzip_jsonl')
        self.assertEqual(len(self.read().rows), 6)

    def test_high_compression_multifile_generation_decompressed_limit(self):
        # Every file is individually valid; the sum of expanded bytes is not.
        self.spec['files'] = []
        expanded = []
        for ticker in ('SPY', 'QQQ'):
            raw = b''.join(encoded(row) for row in prices(ticker))
            expanded.append(raw)
            compressed = packed(raw)
            self.assertLess(len(compressed), len(raw))
            self.add_file(prices(ticker), raw=compressed, format_name='gzip_jsonl')
        cap = sum(map(len, expanded)) - 1
        self.assertLess(max(map(len, expanded)), cap)
        with patch('tools.research_data_access.MAX_GENERATION_DECOMPRESSED_BYTES', cap):
            self.blocked('BLOCKED_GENERATION_DECOMPRESSED_BYTES')
        self.assertEqual(len(self.read().rows), 6)

    def test_high_compression_multifile_generation_rows_limit(self):
        self.spec['files'] = []
        for ticker in ('SPY', 'QQQ'):
            raw = b''.join(encoded(row) for row in prices(ticker))
            self.add_file(prices(ticker), raw=packed(raw), format_name='gzip_jsonl')
        # 3 rows per file; 6 in one generation exceeds the test cap of 5.
        with patch('tools.research_data_access.MAX_GENERATION_ROWS', 5):
            self.blocked('BLOCKED_GENERATION_ROWS')
        self.assertEqual(len(self.read().rows), 6)

    def test_actual_rows_budget_checks_even_when_manifest_understates_rows(self):
        self.spec['files'] = []
        item = self.add_file(prices() * 3)
        item['rows'] = 3  # Declared 3, actually 9; block during parse.
        with patch('tools.research_data_access.MAX_GENERATION_ROWS', 5):
            self.blocked('BLOCKED_GENERATION_ROWS',
                         instrument_ids=['FIXTURE:US:SPY'], minimum_rows=1)

    def test_parquet_roundtrip_or_explicit_dependency_refusal(self):
        if importlib.util.find_spec('pyarrow') is None:
            self.replace_spy(prices(), raw=b'PAR1synthetic-unreadablePAR1', format_name='parquet')
            self.blocked('PARQUET_ENGINE_UNAVAILABLE')
            return
        import pyarrow as pa
        import pyarrow.parquet as pq
        schema = pa.schema([(k, pa.string() if not t.endswith('number') else pa.float64())
                            for k, t in PRICE_COLUMNS.items()])
        table = pa.Table.from_pylist(prices(), schema=schema)
        output = io.BytesIO(); pq.write_table(table, output)
        self.replace_spy(prices(), raw=output.getvalue(), format_name='parquet')
        self.assertEqual(len(self.read().rows), 6)

    def test_registry_has_zero_admitted_generations(self):
        registry = json.loads(REGISTRY.read_bytes())
        self.assertEqual(registry['admitted_frozen_generations'], [])
        self.assertIs(registry['source_manifest_complete'], False)

    def test_schema_and_discovery_map_match_native_contract(self):
        schema = json.loads((ROOT / 'docs/research_dataset_generation_v1.schema.json').read_bytes())
        item = schema['properties']['datasets']['items']['properties']['files']['items']['properties']
        self.assertEqual(item['columns']['const'], PRICE_COLUMNS)
        index = json.loads((ROOT / 'docs/research_data_access.json').read_bytes())
        self.assertEqual(index['frozen_generation_reader']['reader'], 'tools/research_data_access.py')
        self.assertEqual(index['frozen_generation_reader']['admitted_frozen_generations'], 0)

    def test_other_market_cannot_enter_us_dataset(self):
        self.spec['files'][0]['instrument']['market'] = 'KR'
        self.blocked('DATASET_MARKET')

    def lake_fixture(self):
        lake = Lake(self.transport, self.root / 'producer-fixture')
        raw = b''.join(encoded(r) for r in prices())
        lake.dataset('prices/SPY', [b'synthetic-price-source'], prices(), dict(rows=3, evidence='FIXTURE'))
        publication = lake.publish('fixture_one', {})
        quality_raw = encoded(dict(schema='long-history-quality-v1', status='PARTIAL', eligible_for_selector=False))
        quality_sha = digest(quality_raw)
        self.transport.write(f'{PREFIX}/reports/{quality_sha}', quality_raw)
        receipt_raw = encoded(dict(schema='long-history-execution-v1', run_id='fixture_one',
            commit_sha256=publication['commit_sha256'], catalog_sha256=publication['catalog_sha256'],
            reports={'quality.json': quality_sha}, consumer_rows=3,
            study_recomputed_from_drive=False, quality_status='PARTIAL', eligible_for_selector=False))
        receipt_sha = digest(receipt_raw)
        self.transport.write(f'{PREFIX}/executions/{receipt_sha}', receipt_raw)
        binding = dict(commit_sha256=publication['commit_sha256'],
            catalog_sha256=publication['catalog_sha256'], execution_receipt_sha256=receipt_sha)
        return lake, binding, raw

    def test_explicit_old_lake_generation_after_new_commit(self):
        lake, binding, _ = self.lake_fixture()
        updated = Lake(self.transport, self.root / 'next-producer')
        updated.dataset('prices/SPY', [b'synthetic-new-source'], [dict(prices()[0], close=102.0)], dict(rows=1))
        updated.publish('fixture_two', {})
        pinned = pinned_lake(self.transport, self.root / 'old-reader', **binding)
        self.assertEqual(pinned.get_records('prices/SPY'), prices())
        self.assertEqual(Lake(self.transport, self.root / 'legacy-reader').get_records('prices/SPY')[0]['close'], 102.0)
        with self.assertRaisesRegex(ContractError, 'READ_ONLY'):
            pinned.publish('forbidden', {})

    def test_lake_bound_reader_preserves_exact_object_bytes(self):
        lake, binding, raw = self.lake_fixture()
        self.spec['files'] = []
        item = self.add_file(prices(), raw=packed(raw), format_name='gzip_jsonl')
        item.update(storage='lake', lake_key='prices/SPY')
        self.spec['lake_binding'] = binding
        result = self.read(instrument_ids=['FIXTURE:US:SPY'], restore_to=self.root / 'restore')
        self.assertEqual(result.files[0][1], lake.get_bytes(item['sha256']))
        self.assertEqual(result.rows, tuple(prices()))

    def test_lake_receipt_missing_or_corrupt_cannot_pass(self):
        _, binding, _ = self.lake_fixture()
        (self.root / 'archive' / PREFIX / 'executions' / binding['execution_receipt_sha256']).unlink()
        with self.assertRaisesRegex(ContractError, 'LAKE_VERIFICATION_FAILED'):
            pinned_lake(self.transport, self.root / 'reader', **binding)

    def test_later_unrelated_lake_fork_does_not_choose_latest(self):
        _, binding, _ = self.lake_fixture()
        self.transport.write(f'{PREFIX}/commits/' + 'f' * 64, b'unrelated invalid latest')
        pinned = pinned_lake(self.transport, self.root / 'pinned', **binding)
        self.assertEqual(pinned.parent, binding['commit_sha256'])


if __name__ == '__main__':
    unittest.main()
