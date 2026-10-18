"""Discriminating regressions for Hosted review5563925645; all data synthetic."""
import copy
from pathlib import Path
import sys
import unittest
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


if __name__ == '__main__':
    unittest.main()
