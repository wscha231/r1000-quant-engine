"""Discriminating regressions for Hosted review5563925645; all data synthetic."""
import copy
import csv
import hashlib
import io
import json
import tempfile
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.etf116_research_metrics_h1 import riskfree_lag_series, risk_metrics, RefuseInput
from tools import etf116_eod_gate as gate


class HostedP2Regression(unittest.TestCase):
    def rf(self, date='2026-01-02', release='2026-01-10T10:00:00Z', rate=4.0):
        return {'observation_date': date, 'available_at_utc': release, 'dgs3mo_pct': rate}

    def test_later_review_does_not_backfill_late_rate(self):
        rows = [self.rf()]
        result = risk_metrics([100., 101., 100.5], ['2026-01-02','2026-01-05','2026-01-06'],
                              rows, decision_at='2026-01-20T12:00:00Z')
        self.assertEqual(result['risk_free_status'], 'BLOCKED_RF_NOT_AVAILABLE_FOR_RETURN_SESSION')
        self.assertIsNone(result['sharpe'])
        self.assertIsNone(result['sortino'])
        self.assertGreater(result['ann_volatility'], 0)

    def test_latest_available_prior_observation_is_selected(self):
        rows = [self.rf('2026-01-01','2026-01-01T22:00:00Z',2.), self.rf()]
        actual = riskfree_lag_series(['2026-01-02','2026-01-05','2026-01-06'], rows,
                                    decision_at='2026-01-20T12:00:00Z')
        expected = (1.02 ** (1 / 252)) - 1
        for value in actual:
            self.assertAlmostEqual(value, expected)

    def test_date_only_cutoff_refuses_intraday_release(self):
        rows = [self.rf('2026-01-02','2026-01-05T01:00:00Z')]
        with self.assertRaisesRegex(RefuseInput, 'RF_NOT_AVAILABLE_FOR_RETURN_SESSION'):
            riskfree_lag_series(['2026-01-02','2026-01-05'], rows,
                                decision_at='2026-01-20T12:00:00Z')

    def packet(self):
        frozen = gate.validate_universe((Path(__file__).resolve().parents[1] /
                                        'research/etf116_v1/frozen_tickers.txt').read_text().splitlines())
        return frozen, {'schema':gate.SCHEMA,'scope_sha256':gate.EXPECTED_UNIVERSE_SHA256,
            'session':'2026-10-16','official_nyse_close_utc':'2026-10-16T20:00:00Z',
            'run_at_utc':'2026-10-17T23:30:00Z','nyse_session_verified':True,
            'source_rights_verified':True,'private_sheet_write_tested':True,
            'a6_independent_pass':True,'rights_receipt_sha256':'1'*64,
            'source_id':'CONTRACT_FIXTURE_NOT_SOURCE_ADMISSION','tr_basis':'NAV_TR_INDEX',
            'rows':[{'ticker':t,'status':'BLOCKED','reason':'CONTRACT_FIXTURE_NO_TR',
                     'tr_index':None} for t in frozen]}

    def test_friday_session_rejects_saturday_close(self):
        frozen, packet = self.packet()
        packet['official_nyse_close_utc'] = '2026-10-17T20:00:00Z'
        with self.assertRaisesRegex(gate.GateError, 'SESSION_CLOSE_DATE_MISMATCH'):
            gate.prepare(packet, frozen)

    def test_valid_same_date_close_remains_prepared_disabled(self):
        frozen, packet = self.packet()
        result = gate.prepare(packet, frozen)
        self.assertEqual(result['state'], 'PREPARED_ONLY')
        self.assertFalse(result['publish_enabled'])
        self.assertEqual(result['blocked_count'], 116)

    def test_rights_change_is_not_idempotently_unchanged(self):
        frozen, packet = self.packet()
        first = gate.prepare(packet, frozen)
        changed = copy.deepcopy(packet)
        changed['rights_receipt_sha256'] = '2'*64
        second = gate.prepare(changed, frozen)
        self.assertNotEqual(first['input_digest'], second['input_digest'])
        self.assertEqual(second['rights_receipt_sha256'], '2'*64)
        with self.assertRaisesRegex(gate.GateError, 'SAME_SESSION_CONFLICT_BLOCKED'):
            gate.prepare(changed, frozen, first)

    def test_identical_packet_skip_retains_rights_provenance(self):
        frozen, packet = self.packet()
        first = gate.prepare(packet, frozen)
        second = gate.prepare(packet, frozen, first)
        self.assertEqual(second['state'], 'SKIP_UNCHANGED')
        self.assertEqual(first['rights_receipt_sha256'], packet['rights_receipt_sha256'])
        self.assertEqual(second['rights_receipt_sha256'], packet['rights_receipt_sha256'])
        self.assertFalse(second['publish_enabled'])

    def test_close_change_conflicts_and_is_retained(self):
        frozen, packet = self.packet()
        first = gate.prepare(packet, frozen)
        packet['official_nyse_close_utc'] = '2026-10-16T19:00:00Z'
        changed = gate.prepare(packet, frozen)
        self.assertNotEqual(first['input_digest'], changed['input_digest'])
        self.assertEqual(changed['official_nyse_close_utc'], '2026-10-16T19:00:00+00:00')
        with self.assertRaisesRegex(gate.GateError, 'SAME_SESSION_CONFLICT_BLOCKED'):
            gate.prepare(packet, frozen, first)

    def test_equivalent_close_instant_retained_on_skip(self):
        frozen, packet = self.packet()
        first = gate.prepare(packet, frozen)
        packet['official_nyse_close_utc'] = '2026-10-16T16:00:00-04:00'
        skipped = gate.prepare(packet, frozen, first)
        self.assertEqual(skipped['state'], 'SKIP_UNCHANGED')
        self.assertEqual(skipped['official_nyse_close_utc'], first['official_nyse_close_utc'])

    def test_offline_runner_exposes_all_supplied_nonlist_spy(self):
        from tests.etf116_delta_regression import DeltaRegression
        from tools.run_etf116_offline_research_h1 import run
        case=DeltaRegression(methodName='runTest');case.setUp()
        for malformed in (None, {}, 'BAD', 42):
            with self.subTest(malformed=malformed), tempfile.TemporaryDirectory() as td:
                source, output=Path(td)/'input.json',Path(td)/'output.json'
                source.write_text(json.dumps({'schema':'etf116-metrics-candidate-input-v1',
                    'scope_sha256':gate.EXPECTED_UNIVERSE_SHA256,'session':'2026-10-16',
                    'decision_at_utc':'2026-10-18T14:00:00Z',
                    'verified_nyse_sessions':case.sessions,
                    'source_candidate_rows':{'GARP':case.rows,'SPY':malformed}}))
                run(source,Path(__file__).resolve().parents[1]/'research/etf116_v1/frozen_tickers.txt',output)
                result=json.loads(output.read_text())['ticker_results']['GARP']['horizons']['12']
                self.assertEqual(result['benchmark_status'],'BLOCKED_OPTIONAL_BENCHMARK_SERIES_NOT_LIST')

    def seed(self):
        path=Path(__file__).resolve().parents[1]/'data_static/iwb_holdings_seed.csv'
        return [r['ticker'] for r in csv.DictReader(io.StringIO(path.read_text()))]

    def test_supplied_malformed_listing_map_never_becomes_absent(self):
        from tools.run_etf116_offline_research_h1 import run
        for malformed in (None, [], '', 0, False):
            with self.subTest(malformed=malformed), tempfile.TemporaryDirectory() as td:
                source,output=Path(td)/'input.json',Path(td)/'output.json'
                source.write_text(json.dumps({'schema':'etf116-metrics-candidate-input-v1',
                    'scope_sha256':gate.EXPECTED_UNIVERSE_SHA256,'session':'2026-10-16',
                    'decision_at_utc':'2026-10-18T14:00:00Z',
                    'verified_nyse_sessions':['2026-10-15','2026-10-16'],
                    'source_candidate_rows':{},'issuer_verified_exchange_listed_date':malformed}))
                with self.assertRaisesRegex(RefuseInput,'INCEPTION_MAP_INVALID'):
                    run(source,Path(__file__).resolve().parents[1]/'research/etf116_v1/frozen_tickers.txt',output)
                self.assertFalse(output.exists())

    def holdings(self):
        return [{'etf':f,'ticker':ticker,'rank':i,'weight_pct':1.,'holdings_asof':'2026-10-16',
                 'source_url':'https://example.test/CONTRACT_FIXTURE'}
                for f in ('GARP','QUAL','SPMO') for i,ticker in enumerate(self.seed()[:10],1)]

    def lookthrough(self, seed):
        from tools.etf_top3_holdings_overlay_h1 import build_lookthrough
        return build_lookthrough(self.holdings(),seed,reviewed_at_utc='2026-10-18T14:00:00Z')

    def test_empty_and_truncated_fixed_seed_refuse(self):
        from tools.etf_top3_holdings_overlay_h1 import OverlayError
        for seed in ([],self.seed()[:-1]):
            with self.subTest(count=len(seed)), self.assertRaisesRegex(OverlayError,'FROZEN_1009_SEED_IDENTITY'):
                self.lookthrough(seed)

    def test_same_count_seed_substitution_refuses(self):
        from tools.etf_top3_holdings_overlay_h1 import OverlayError
        seed=self.seed();seed[-1]='ZZZZZZ'
        with self.assertRaisesRegex(OverlayError,'FROZEN_1009_SEED_IDENTITY'):
            self.lookthrough(seed)

    def test_real_fixed_seed_identity_is_retained(self):
        from tools.etf_top3_holdings_overlay_h1 import FROZEN_SEED_SHA256
        result=self.lookthrough(self.seed())
        self.assertEqual(result['universe_seed_sha256'],FROZEN_SEED_SHA256)
        self.assertEqual(result['universe_seed_count'],1009)
        self.assertEqual(result['count_already_in_seed'],10)
        self.assertFalse(result['universe_seed_modified'])

    def test_csv_hash_binds_parsed_snapshot_despite_source_replacement(self):
        from tools import run_etf_top3_research_lookthrough_h1 as runner
        actual_prepare=runner.prepare_holdings
        text=io.StringIO(newline='');rows=self.holdings()
        writer=csv.DictWriter(text,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
        original=text.getvalue().encode()
        with tempfile.TemporaryDirectory() as td:
            source, output=Path(td)/'holdings.csv',Path(td)/'out.json';source.write_bytes(original)
            def replace_after_parse(*args,**kwargs):
                result=actual_prepare(*args,**kwargs)
                source.write_bytes(b'REPLACED_AFTER_PARSE')
                return result
            with patch.object(runner,'prepare_holdings',side_effect=replace_after_parse):
                runner.run(source,seed_symbols=self.seed(),observation_at='2026-10-18T14:00:00Z',output=output)
            receipt=json.loads(output.read_text())
            self.assertEqual(receipt['source_input_bytes_sha256'],hashlib.sha256(original).hexdigest())
            self.assertNotEqual(source.read_bytes(),original)


if __name__ == '__main__':
    unittest.main()
