"""Native ETF adapter tests; all price rows are explicit contract fixtures."""
from __future__ import annotations

import copy
import csv
import hashlib
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests.etf116_delta_regression import DeltaRegression
from tests.etf116_hosted_p2_regression import HostedP2Regression
from tests.etf116_successor_review_smoke import SuccessorReviewTests
from tests import research_data_access_smoke as reader_fixtures
from tools.etf116_research_backend import (
    prepare_holdings, read_total_return_component, classify_spmo_nav_reference,
)
from tools.etf116_research_metrics_h1 import RefuseInput
from tools.etf116_research_metrics_h1 import validate_series
from tools.etf116_research_metrics_h1 import risk_metrics
from tools.etf116_existing_cron_planner_h1 import plan_existing_trigger
from tools.run_etf116_offline_research_h1 import run as run_metrics
from tools.etf116_eod_gate import EXPECTED_UNIVERSE_SHA256, validate_universe


class NativeETFIntegration(unittest.TestCase):
    def setUp(self):
        self.fixture = reader_fixtures.ReaderTest(methodName='runTest')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        source = self.fixture.spec['source']
        source['total_return_basis'] = 'NAV_TR_INDEX'
        source['total_return_methodology_sha256'] = '5' * 64
        for entry in self.fixture.spec['files']:
            entry['instrument']['adjustment_basis'] = 'TOTAL_RETURN'

    def read(self, generation=None):
        return read_total_return_component(self.fixture.reader,
            dataset_id='ds.us.prices.daily', generation=generation or self.fixture.generation(),
            ticker='SPY', instrument_id='FIXTURE:US:SPY',
            sessions=reader_fixtures.SESSIONS, decision_at=reader_fixtures.DECISION)

    def holdings(self):
        return [{'etf': f, 'ticker': f'A{i}', 'rank': i, 'weight_pct': 2.0,
                 'holdings_asof': '2026-10-16' if f == 'SPMO' else '2026-10-15',
                 'source_url': 'https://etfiq.com/funds/'+f.lower()+'/holdings/'}
                for f in ['GARP', 'QUAL', 'SPMO'] for i in range(1, 11)]

    def test_actual_merged_reader_consumed_with_original_hash_chain(self):
        generation = self.fixture.generation()
        with patch.object(self.fixture.transport, 'write', side_effect=AssertionError('WRITE')):
            result = self.read(generation)
        self.assertEqual(len(result['rows']), 3)
        receipt = result['reader_receipt']
        self.assertEqual(receipt['status'], 'VERIFIED_RESEARCH_BYTES')
        self.assertEqual(receipt['raw_source_sha256'], ['4' * 64])
        self.assertEqual(result['rows'][0]['source_sha256'], receipt['receipt_sha256'])
        self.assertEqual(result['source_reference_kind'], 'READER_RECEIPT_SHA256_NOT_PROVIDER_BYTES')
        self.assertFalse(result['a1_source_admitted'])
        self.assertFalse(result['economic_authority'])
        self.assertFalse(receipt['calendar_source_verified'])

    def test_reader_cannot_relabel_raw_close_as_total_return(self):
        self.fixture.spec['files'][0]['instrument']['adjustment_basis'] = 'RAW'
        with self.assertRaisesRegex(RefuseInput, 'TR_IDENTITY_OR_ADJUSTMENT_MISMATCH'):
            self.read()

    def test_missing_nav_market_declaration_refuses(self):
        self.fixture.spec['source'].pop('total_return_basis')
        with self.assertRaisesRegex(RefuseInput, 'EXPLICIT_DAILY_TR_BASIS_REQUIRED'):
            self.read()

    def test_reader_expired_generation_still_refuses(self):
        self.fixture.spec['source']['expires_at'] = '2026-10-08T00:00:00Z'
        with self.assertRaisesRegex(ValueError, 'STALE_GENERATION'):
            self.read()

    def test_reader_object_tampering_still_refuses(self):
        entry = self.fixture.spec['files'][0]
        (self.fixture.transport.root / ('shared-research-v1/objects/'+entry['sha256'])).write_bytes(b'tampered')
        with self.assertRaisesRegex(ValueError, 'HASH'):
            self.read()

    def test_existing_normalizer_used_without_inventing_publication_time(self):
        from tools.run_etf_holdings_refresh import normalize_holding_rows
        seed = [r['ticker'] for r in csv.DictReader(io.StringIO((ROOT/'data_static/iwb_holdings_seed.csv').read_text()))]
        with patch('tools.run_etf_holdings_refresh.normalize_holding_rows', wraps=normalize_holding_rows) as normalizer:
            result = prepare_holdings(self.holdings(), seed, decision_at='2026-10-18T14:00:00Z')
        self.assertEqual(normalizer.call_count, 3)
        self.assertEqual(result['holding_slots'], 30)
        self.assertEqual(len(result['normalized_holdings']), 30)
        self.assertTrue(all(r['available_from'] is None for r in result['normalized_holdings']))
        self.assertTrue(all(r['holding_weight'] == .02 for r in result['normalized_holdings']))
        self.assertFalse(result['universe_seed_modified'])
        self.assertFalse(result['canonical_registry_written'])

    def test_nav_reference_never_becomes_market_close_or_tr(self):
        row = {'date_nyse': '2026-10-16', 'issuer_nav_usd': '100.0',
               'source_basis': 'ISSUER_NAV', 'trade_close_eligible': 'FALSE'}
        result = classify_spmo_nav_reference([row])
        self.assertEqual(result['reference_rows'], 1)
        self.assertFalse(result['executable_market_price'])
        self.assertFalse(result['daily_total_return_verified'])
        self.assertFalse(result['sheet_publisher_allowed'])
        row['trade_close_eligible'] = 'TRUE'
        with self.assertRaisesRegex(RefuseInput, 'NAV_CANNOT_BE_TRADE_CLOSE'):
            classify_spmo_nav_reference([row])

    def test_frozen_116_and_fixed_1009_seeds_unchanged(self):
        frozen = ROOT/'research/etf116_v1/frozen_tickers.txt'
        symbols = validate_universe(frozen.read_text().splitlines())
        self.assertEqual(len(symbols), 116)
        self.assertEqual(hashlib.sha256('\n'.join(sorted(symbols)).encode()).hexdigest(), EXPECTED_UNIVERSE_SHA256)
        seed = list(csv.DictReader(io.StringIO((ROOT/'data_static/iwb_holdings_seed.csv').read_text())))
        self.assertEqual(len({r['ticker'] for r in seed}), 1009)

    def test_existing_schedule_weekly_plan_is_not_a_dispatch(self):
        result = plan_existing_trigger(session='2026-10-16', close_utc='2026-10-16T20:00:00Z',
            now_utc='2026-10-16T23:30:00Z', calendar_session_verified=True,
            provider_available_at_utc='2026-10-16T20:30:00Z',
            prior_eod_processed_session='2026-10-15', prior_holdings_refresh_session='2026-10-09',
            schedule_flag_enabled=True)
        self.assertTrue(result['price_refresh_due'])
        self.assertTrue(result['holdings_refresh_due'])
        self.assertFalse(result['dispatch_performed'])
        self.assertFalse(result['publish_enabled'])

    def test_future_observation_cannot_be_known_before_its_date(self):
        row = {'ticker':'SPY', 'date':'2026-10-16', 'basis':'NAV_TR_INDEX',
               'tr_index':100., 'source_sha256':'1'*64,
               'available_at_utc':'2026-10-15T21:00:00Z'}
        with self.assertRaisesRegex(RefuseInput,'SERIES_AVAILABLE_BEFORE_OBSERVATION'):
            validate_series([row], ['2026-10-16'],ticker='SPY',asof='2026-10-16',
                            decision_at='2026-10-18T14:00:00Z')

    def test_daily_return_rows_and_one_year_cagr_are_explicit(self):
        case = DeltaRegression(methodName='runTest')
        case.setUp()
        result = case.compute()
        self.assertEqual(len(result['daily_returns']), len(case.sessions)-1)
        self.assertEqual(result['blocked_daily_intervals'], 0)
        self.assertEqual(result['daily_returns'][0]['previous_session'], case.sessions[0])
        self.assertIsNotNone(result['horizons']['12']['cagr'])
        self.assertFalse(result['a1_source_admitted'])

    def test_backdated_rf_clock_blocks_ratios_and_preserves_volatility(self):
        rows = [{'observation_date':'2026-10-13', 'dgs3mo_pct':4.,
                 'available_at_utc':'2020-01-01T00:00:00Z'}]
        result = risk_metrics([100.,101.,100.5],['2026-10-14','2026-10-15','2026-10-16'],
                              rows,decision_at='2026-10-18T14:00:00Z')
        self.assertEqual(result['risk_free_status'],'BLOCKED_RF_AVAILABLE_BEFORE_OBSERVATION')
        self.assertIsNone(result['sharpe'])
        self.assertGreater(result['ann_volatility'],0)

    def test_preflight_cli_preserves_existing_output_bytes(self):
        from tools import etf116_eod_gate
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            frozen, packet, output = base/'frozen',base/'packet.json',base/'prior.json'
            frozen.write_text((ROOT/'research/etf116_v1/frozen_tickers.txt').read_text())
            packet.write_text('{}')
            output.write_bytes(b'PRESERVE_PRIOR_RECEIPT')
            argv = ['preflight','--frozen',str(frozen),'--packet',str(packet),'--output',str(output)]
            with patch.object(sys,'argv',argv), patch.object(etf116_eod_gate,'prepare',return_value={'state':'PREPARED_ONLY'}):
                with self.assertRaises(FileExistsError):
                    etf116_eod_gate.main()
            self.assertEqual(output.read_bytes(),b'PRESERVE_PRIOR_RECEIPT')

    def test_actual_absent_source_keeps_all_116_blocked(self):
        packet = {'schema': 'etf116-metrics-candidate-input-v1', 'scope_sha256': EXPECTED_UNIVERSE_SHA256,
                  'session': '2026-10-16', 'decision_at_utc': '2026-10-18T14:00:00Z',
                  'verified_nyse_sessions': ['2026-10-15', '2026-10-16'], 'source_candidate_rows': {}}
        with tempfile.TemporaryDirectory() as td:
            source, output = Path(td)/'in.json', Path(td)/'out.json'
            source.write_text(json.dumps(packet))
            result = run_metrics(source, ROOT/'research/etf116_v1/frozen_tickers.txt', output)
            payload = json.loads(output.read_text())
        self.assertEqual(result['blocked_tickers'], 116)
        self.assertFalse(payload['allowed_for_sheet_publisher'])
        self.assertFalse(payload['eligible_for_target'])


if __name__ == '__main__':
    unittest.main()
