#!/usr/bin/env python3
"""Deterministic H1 admission regressions; no vendor/network/economic runs."""
from __future__ import annotations
import copy
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import pandas as pd
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import earnings_consensus_h1 as h1
from tools import collect_earnings_estimates_finnhub as c
from tools.run_free_data_selection_overlay import build_overlay


def estimate(value=1.0, period="2026-12-31", **overrides):
    return dict(period=period, avg=value, high=1.4, low=0.8, numberAnalysts=5,
                issuer_id="CIK:1", security_id="FIGI:AAA", period_type="ANNUAL",
                accounting_basis="GAAP", currency="USD", share_or_ADR_unit="DILUTED_COMMON_SHARE", **overrides)


def snapshot(time="2026-04-01T18:00:00Z", value=1.0, period="2026-12-31", ticker="AAA", **kwargs):
    args = dict(fetch_date=pd.Timestamp(time[:10]), eps_payload={"data": [estimate(value, period)]},
                revenue_payload={"data": [estimate(100.0, period)]}, earnings_payload=[],
                recommendation_payload=[dict(strongBuy=4,buy=3,sell=1,strongSell=0)],
                observed_at=time, collected_at=time)
    args.update(kwargs)
    return c.parse_snapshot_row(ticker, **args)


def features(rows):
    return c.compute_estimate_revision_features(pd.DataFrame(rows))[0]


def legacy_snapshot():
    # Complete pre-V2 parse_snapshot_row() output on master e97a8509, including
    # its original zero-filled economics and empty optional date strings.
    return dict(ticker='LEG', as_of_date='2026-04-01', available_from='2026-04-01',
                fetch_source='finnhub', eps_estimate_access=True,
                revenue_estimate_access=True, vendor_estimate_access=True,
                has_forward_estimate=0, est_eps_fy1=0.0, est_eps_fy2=0.0,
                est_rev_fy1=0.0, n_analysts=0, est_dispersion=0.0,
                actual_eps_last=0.0, actual_report_date='', earnings_surprise_last=0.0,
                surprise_streak=0, recommendation_period='', recommendation_bull_count=0,
                recommendation_bear_count=0, est_eps_revision_breadth=0.0)


class AdmissionTests(unittest.TestCase):
    def setUp(self):
        clock = patch.object(c, 'utc_now', return_value='2026-07-01T18:00:00Z')
        clock.start()
        self.addCleanup(clock.stop)

    def test_version_integrity_precedes_every_consumer_clock(self):
        before = snapshot('2026-04-01T18:00:00Z', 1)
        after = snapshot('2026-05-02T18:00:00Z', 2)
        args = dict(event_available_at='2026-07-01T20:00:00Z',
                    identity=json.loads(before['eps_fy1_identity']), fetch_source='finnhub')
        for field in ('observed_at', 'collected_at', 'first_seen_at',
                      'strategy_available_at', 'provider_published_at'):
            # Only the chosen clock puts this otherwise pre-event row after
            # the event. Tampering it must not turn it into frozen evidence.
            late = {**before, field: '2026-07-01T21:00:00Z'}
            late['snapshot_version_id'] = h1.snapshot_digest(late)
            bad = {**late, field: '2026-07-01T19:00:00Z'}
            self.assertFalse(h1.persisted_v2_snapshot_is_valid(bad), field)
            with patch.object(h1, 'availability', side_effect=AssertionError('clock read before version')):
                self.assertIsNone(h1.frozen_pre_event_consensus([bad], **args), field)
                self.assertIsNone(h1.same_period_revision(after, bad), field)
                self.assertIsNone(h1.same_period_revision(bad, before), field)
            for rows in ([before, bad], [bad, before]):
                self.assertIsNone(h1.frozen_pre_event_consensus(rows, **args), field)
            with patch.object(c, 'availability', side_effect=AssertionError('clock read before version')):
                self.assertTrue(features([bad]).empty, field)
                self.assertTrue(c.latest_signal_by_ticker(pd.DataFrame([bad]),
                                decision_date=args['event_available_at']).empty, field)
            with tempfile.TemporaryDirectory() as temp:
                path = Path(temp) / 'estimates_20260401.parquet'
                pd.DataFrame([bad]).to_parquet(path)
                historical = c.load_snapshot_history(Path(temp))
                self.assertTrue(c.compute_estimate_revision_features(historical)[0].empty, field)
            signals = features([before])
            signals.loc[0, field] = '2026-07-01T19:00:00Z'
            self.assertTrue(c.latest_signal_by_ticker(signals,
                            decision_date=args['event_available_at']).empty, field)
        self.assertEqual(h1.frozen_pre_event_consensus([before], **args)['value'], 1)
        self.assertEqual(h1.same_period_revision(after, before), 1)
        self.assertEqual(features([before, after]).iloc[-1].est_eps_revision_30d, 1)
        self.assertFalse(c.latest_signal_by_ticker(features([before, after]),
                         decision_date=args['event_available_at']).empty)

    def test_malformed_persisted_inputs_fail_without_consumer_exceptions(self):
        valid = snapshot()
        args = dict(event_available_at='2026-07-01T20:00:00Z',
                    identity=json.loads(valid['eps_fy1_identity']), fetch_source='finnhub')
        for bad in (True, [], 'row', 123, None, {},
                    {**valid, 'consensus_observations_json': '['},
                    {**valid, 'snapshot_version_id': '0' * 64}):
            self.assertFalse(h1.persisted_v2_snapshot_is_valid(bad))
            self.assertIsNone(h1.frozen_pre_event_consensus([bad], **args))
            self.assertIsNone(h1.same_period_revision(valid, bad))
            self.assertIsNone(h1.same_period_revision(bad, valid))

    def test_nonfinite_identity_scalars_never_become_economic_identity(self):
        fields = ('currency', 'security_id', 'issuer_id', 'accounting_basis',
                  'period_type', 'share_or_ADR_unit')
        for field in fields:
            for value in (float('inf'), float('-inf'), float('nan')):
                item = estimate(); item[field] = value
                old = snapshot(eps_payload={'data': [item]}, revenue_payload={})
                item = {**item, 'avg': 2}
                new = snapshot('2026-05-02T18:00:00Z', eps_payload={'data': [item]}, revenue_payload={})
                self.assertIsNone(h1.text_value(value))
                self.assertNotEqual(old['identity_status'], 'VERIFIED', field)
                self.assertNotEqual(new['identity_status'], 'VERIFIED', field)
                self.assertIsNone(h1.same_period_revision(new, old), field)
                identity = json.loads(old['consensus_observations_json'])[0]['identity']
                self.assertFalse(h1.identity_complete(identity), field)
                self.assertIsNone(h1.frozen_pre_event_consensus([old, new],
                    event_available_at='2026-07-01T20:00:00Z', identity=identity,
                    fetch_source='finnhub'), field)
        for value, expected in ((1, '1'), (1.5, '1.5'), (' USD ', 'USD')):
            self.assertEqual(h1.text_value(value), expected)
        self.assertEqual(snapshot()['identity_status'], 'VERIFIED')

    def test_legacy_requires_complete_producer_columns_and_types(self):
        legacy = legacy_snapshot()
        self.assertEqual(set(legacy), c.LEGACY_REQUIRED_COLUMNS)
        self.assertEqual(set(c.LEGACY_FIELD_TYPE_CONTRACT), set(legacy))
        self.assertEqual(c.classify_persisted_archive_row(legacy), 'VERIFIED_LEGACY')
        sparse = {k: legacy[k] for k in ('ticker', 'as_of_date', 'available_from')}
        invalid_rows = [sparse]
        invalid_rows.extend({k: v for k, v in legacy.items() if k != missing} for missing in legacy)
        for field in legacy:
            invalid_rows.extend({**legacy, field: value} for value in ([], {'bad': 'shape'}, None))
        invalid_rows.extend({**legacy, field: value} for field, value in (
            ('eps_estimate_access', 1), ('has_forward_estimate', True),
            ('has_forward_estimate', 2), ('n_analysts', 1.5),
            ('est_eps_fy1', '1.2'), ('est_eps_fy1', float('inf')),
            ('est_eps_fy1', True), ('as_of_date', '2026-02-30'),
            ('actual_report_date', 'yesterday'), ('recommendation_period', '2026-07'),
            ('fetch_source', ''), ('ticker', '')))
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'day.parquet'
            current = pd.DataFrame([snapshot()])
            for bad in invalid_rows:
                self.assertEqual(c.classify_persisted_archive_row(bad), 'INVALID_OR_UNKNOWN_SCHEMA', bad)
                # Real malformed storage is rejected before any archive write.
                pd.DataFrame([bad]).to_parquet(path)
                stored = path.read_bytes()
                with self.assertRaisesRegex(ValueError, 'invalid_or_unknown_existing'):
                    c.merge_same_day_snapshot(path, current)
                self.assertEqual(path.read_bytes(), stored)
            # Integral floats are the same legacy integers after Parquet union.
            legacy['n_analysts'] = 0.0
            union = {**legacy, **{k: None for k in snapshot() if k not in legacy}}
            self.assertEqual(c.classify_persisted_archive_row(union), 'VERIFIED_LEGACY')
            pd.DataFrame([union]).to_parquet(path)
            mixed, _ = c.merge_same_day_snapshot(path, current)
            mixed.to_parquet(path)
            repeated, _ = c.merge_same_day_snapshot(path, current)
            pd.testing.assert_frame_equal(mixed.reset_index(drop=True), repeated.reset_index(drop=True),
                                          check_dtype=False)

    def test_causal_event_equivalent_formats_dedupe(self):
        keys = [h1.causal_event_id(issuer, period, timestamp)
                for issuer, period, timestamp in [
                    ('CIK:1', '2026-06-30', '2026-07-01T20:00:00Z'),
                    (' CIK:1 ', '20260630', '2026-07-01T16:00:00-04:00'),
                    ('CIK:1', '2026-W27-2', '2026-07-01T20:00:00+00:00')]]
        self.assertEqual(len(set(keys)), 1)
        self.assertEqual(len(h1.dedupe_causal_events([
            dict(causal_event_id=k, causal_link_verified=True, kind=str(i))
            for i, k in enumerate(keys)])), 1)

    def test_consensus_hash_mismatch_blocks_both_consumers(self):
        before = snapshot(); after = snapshot('2026-05-02T18:00:00Z', 2)
        identity = json.loads(before['eps_fy1_identity'])
        bad = copy.deepcopy(before)
        records = json.loads(bad['consensus_observations_json'])
        records[0]['value'] = 999
        bad['consensus_observations_json'] = json.dumps(records)
        self.assertEqual(h1.consensus_records(bad), [])
        self.assertIsNone(h1.same_period_revision(after, bad))
        bad_current = copy.deepcopy(after)
        bad_current['consensus_observations_json'] = bad['consensus_observations_json']
        self.assertIsNone(h1.same_period_revision(bad_current, before))
        self.assertIsNone(h1.frozen_pre_event_consensus([bad], event_available_at='2026-05-03T20:00:00Z', identity=identity, fetch_source='finnhub'))
        self.assertIsNone(h1.frozen_pre_event_consensus([before, bad_current], event_available_at='2026-05-03T20:00:00Z', identity=identity, fetch_source='finnhub'))
        tampered_view = copy.deepcopy(after); tampered_view['est_eps_fy1'] = 999
        self.assertIsNone(h1.same_period_revision(tampered_view, before))

    def test_unknown_publication_post_event_collection_cannot_invalidate(self):
        before = snapshot('2026-07-01T18:00:00Z', 1)
        identity = json.loads(before['eps_fy1_identity'])
        unknown = snapshot('2026-07-01T19:59:00Z', None,
                           collected_at='2026-07-01T20:01:00Z', provider_published_at='2026-07-01')
        args = dict(event_available_at='2026-07-01T20:00:00Z', identity=identity, fetch_source='finnhub')
        self.assertEqual(h1.frozen_pre_event_consensus([before, unknown], **args)['value'], 1)
        unknown['collected_at'] = '2026-07-01T19:59:59Z'
        unknown['snapshot_version_id'] = h1.snapshot_digest(unknown)
        self.assertIsNone(h1.frozen_pre_event_consensus([before, unknown], **args))
        for key in ('first_seen_at', 'strategy_available_at', 'provider_published_at'):
            delayed = {**unknown, key: '2026-07-01T20:01:00Z'}
            delayed['snapshot_version_id'] = h1.snapshot_digest(delayed)
            self.assertEqual(h1.frozen_pre_event_consensus([before, delayed], **args)['value'], 1)

    def test_unknown_publication_only_blocks_current_or_newer_vintage(self):
        old_unknown = snapshot('2026-07-01T18:00:00Z', None, provider_published_at='2026-07-01')
        verified = snapshot('2026-07-01T19:00:00Z', 2)
        new_unknown = snapshot('2026-07-01T19:30:00Z', None, provider_published_at='2026-07-01')
        equal_unknown = snapshot('2026-07-01T19:00:00Z', None, provider_published_at='2026-07-01')
        post_event = snapshot('2026-07-01T19:30:00Z', None,
                              collected_at='2026-07-01T20:01:00Z', provider_published_at='2026-07-01')
        args = dict(event_available_at='2026-07-01T20:00:00Z',
                    identity=json.loads(verified['eps_fy1_identity']), fetch_source='finnhub')
        for rows in ([old_unknown, verified], [verified, old_unknown],
                     [old_unknown, verified, post_event]):
            self.assertEqual(h1.frozen_pre_event_consensus(rows, **args)['value'], 2)
        for unknown in (new_unknown, equal_unknown):
            for rows in ([verified, unknown], [unknown, verified]):
                self.assertIsNone(h1.frozen_pre_event_consensus(rows, **args))

    def test_malformed_identity_types_fail_closed(self):
        before = snapshot()
        for field, invalid in [('currency', True), ('security_id', ['ABC']),
                               ('issuer_id', {}), ('share_or_ADR_unit', ['ADR'])]:
            item = estimate(1.2)
            item[field] = invalid
            row = snapshot('2026-05-02T18:00:00Z', eps_payload={'data': [item]}, revenue_payload={})
            self.assertNotEqual(row['identity_status'], 'VERIFIED', field)
            self.assertIsNone(h1.same_period_revision(row, before), field)
            self.assertIsNone(h1.frozen_pre_event_consensus(
                [row], event_available_at='2026-05-03T20:00:00Z',
                identity=json.loads(before['eps_fy1_identity']), fetch_source='finnhub'), field)
            self.assertFalse(h1.identity_complete({**json.loads(before['eps_fy1_identity']), field: invalid}))
        self.assertEqual(snapshot()['identity_status'], 'VERIFIED')

    def test_malformed_top_level_identity_never_raises_or_admits(self):
        before = snapshot()
        canonical = json.loads(before['eps_fy1_identity'])
        after = snapshot('2026-05-02T18:00:00Z', 2)
        for invalid in (True, False, [], ['ABC'], 'ABC', 123, {}):
            self.assertFalse(h1.identity_complete(invalid))
            self.assertIsNone(h1.frozen_pre_event_consensus(
                [before], event_available_at='2026-05-03T20:00:00Z',
                identity=invalid, fetch_source='finnhub'))
            self.assertIsNone(h1.earnings_surprise(
                2, {'identity': invalid}, identity=invalid,
                announcement_at='2026-05-03T20:00:00Z'))
            malformed = {**after, 'eps_fy1_identity': invalid}
            self.assertIsNone(h1.same_period_revision(malformed, before))
        self.assertIsNone(h1.same_period_revision({**after, 'eps_fy1_identity': '[invalid'}, before))
        self.assertTrue(h1.identity_complete(canonical))
        self.assertEqual(h1.frozen_pre_event_consensus(
            [before], event_available_at='2026-05-03T20:00:00Z',
            identity=canonical, fetch_source='finnhub')['value'], 1)
        self.assertAlmostEqual(h1.same_period_revision(after, before), 1)

    def test_stripped_v2_markers_cannot_downgrade_to_legacy(self):
        original = snapshot()
        current = pd.DataFrame([snapshot('2026-04-01T19:00:00Z', 2)])
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'day.parquet'
            for stripped in (('source_contract',), ('snapshot_version_id',),
                             ('source_contract', 'snapshot_version_id')):
                corrupt = copy.deepcopy(original)
                for key in stripped:
                    corrupt.pop(key)
                self.assertEqual(c.classify_persisted_archive_row(corrupt), 'V2_REQUIRES_VALIDATION')
                pd.DataFrame([corrupt]).to_parquet(path)
                stored = path.read_bytes()
                with self.assertRaisesRegex(ValueError, 'invalid_existing_v2'):
                    c.merge_same_day_snapshot(path, current)
                self.assertEqual(path.read_bytes(), stored)
            corrupt = copy.deepcopy(original)
            corrupt['source_contract'] = None
            corrupt['snapshot_version_id'] = None
            records = json.loads(corrupt['consensus_observations_json'])
            records[0]['value'] = 999
            corrupt['consensus_observations_json'] = json.dumps(records)
            pd.DataFrame([corrupt]).to_parquet(path)
            with self.assertRaisesRegex(ValueError, 'invalid_existing_v2'):
                c.merge_same_day_snapshot(path, current)
            legacy = legacy_snapshot()
            self.assertEqual(c.classify_persisted_archive_row(legacy), 'VERIFIED_LEGACY')
            pd.DataFrame([legacy]).to_parquet(path)
            mixed, _ = c.merge_same_day_snapshot(path, pd.DataFrame([original]))
            self.assertEqual(set(mixed['ticker']), {'LEG', 'AAA'})
            mixed.to_parquet(path)
            repeated, _ = c.merge_same_day_snapshot(path, pd.DataFrame([original]))
            self.assertEqual(len(repeated), 2)
            self.assertEqual(mixed['snapshot_version_id'].fillna('').tolist(),
                             repeated['snapshot_version_id'].fillna('').tolist())

    def test_positive_legacy_classification_rejects_remaining_v2_or_unknown_fields(self):
        v2 = snapshot()
        legacy = legacy_snapshot()
        self.assertEqual(c.classify_persisted_archive_row(legacy), 'VERIFIED_LEGACY')
        base, parsed, live = h1.snapshot_field_profiles()
        v2_distinct = (base | parsed | live) - c.LEGACY_ARCHIVE_FIELDS
        self.assertTrue({'observed_at', 'collected_at', 'first_seen_at',
                         'strategy_available_at', 'eps_fy1_status'} <= v2_distinct)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'day.parquet'
            for marker in ('observed_at', 'collected_at', 'first_seen_at',
                           'strategy_available_at', 'eps_fy1_status'):
                thin = {k: None for k in v2}
                thin.update({k: v2[k] for k in ('ticker', 'as_of_date', 'available_from', marker)})
                self.assertEqual(c.classify_persisted_archive_row(thin), 'V2_REQUIRES_VALIDATION')
                pd.DataFrame([thin]).to_parquet(path)
                before = path.read_bytes()
                with self.assertRaisesRegex(ValueError, 'invalid_existing_v2'):
                    c.merge_same_day_snapshot(path, pd.DataFrame([v2]))
                self.assertEqual(path.read_bytes(), before, marker)
            unknown = {**legacy, 'future_v3_provenance': 'unverified'}
            self.assertEqual(c.classify_persisted_archive_row(unknown), 'INVALID_OR_UNKNOWN_SCHEMA')
            pd.DataFrame([unknown]).to_parquet(path)
            before = path.read_bytes()
            with self.assertRaisesRegex(ValueError, 'invalid_or_unknown_existing_estimate_archive_schema'):
                c.merge_same_day_snapshot(path, pd.DataFrame([v2]))
            self.assertEqual(path.read_bytes(), before)
            legacy_union = {**legacy, **{key: None for key in v2_distinct}}
            self.assertEqual(c.classify_persisted_archive_row(legacy_union), 'VERIFIED_LEGACY')
            pd.DataFrame([legacy_union]).to_parquet(path)
            mixed, _ = c.merge_same_day_snapshot(path, pd.DataFrame([v2]))
            self.assertEqual(set(mixed['ticker']), {'LEG', 'AAA'})
            mixed.to_parquet(path)
            again, _ = c.merge_same_day_snapshot(path, pd.DataFrame([v2]))
            self.assertEqual(len(again), 2)
            self.assertEqual(mixed['snapshot_version_id'].fillna('').tolist(),
                             again['snapshot_version_id'].fillna('').tolist())

    def test_persisted_v2_row_integrity_before_same_day_merge(self):
        original = snapshot(value=None)
        correction = snapshot('2026-04-01T19:00:00Z', 2)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'day.parquet'
            pd.DataFrame([original]).to_parquet(path)
            h1.validate_persisted_snapshot(pd.read_parquet(path).to_dict('records')[0])
            for mutation in ('records', 'source_hash', 'version', 'contract'):
                corrupt = copy.deepcopy(original)
                if mutation == 'records':
                    records = json.loads(corrupt['consensus_observations_json'])
                    records[0]['value'] = 900
                    corrupt['consensus_observations_json'] = json.dumps(records)
                elif mutation == 'source_hash':
                    corrupt['source_payload_sha256'] = '0' * 64
                elif mutation == 'version':
                    corrupt['est_eps_fy1'] = 900
                else:
                    corrupt['source_contract'] = 'unsupported-contract'
                pd.DataFrame([corrupt]).to_parquet(path)
                with self.assertRaisesRegex(ValueError, 'invalid_existing_v2'):
                    c.merge_same_day_snapshot(path, pd.DataFrame([correction]))
            pd.DataFrame([original]).to_parquet(path)
            merged, _ = c.merge_same_day_snapshot(path, pd.DataFrame([correction]))
            self.assertEqual(len(merged), 2)
            merged.to_parquet(path)
            repeat, _ = c.merge_same_day_snapshot(path, pd.DataFrame([correction]))
            self.assertEqual(len(repeat), 2)
            self.assertEqual(merged['snapshot_version_id'].tolist(), repeat['snapshot_version_id'].tolist())
            # A legacy row can widen the Parquet schema; its null columns on
            # V2 rows must not become part of the original version payload.
            legacy = legacy_snapshot()
            pd.DataFrame([legacy]).to_parquet(path)
            mixed, _ = c.merge_same_day_snapshot(path, pd.DataFrame([original]))
            mixed.to_parquet(path)
            repeated, _ = c.merge_same_day_snapshot(path, pd.DataFrame([original]))
            self.assertEqual(len(repeated), 2)
            tampered = repeated.copy()
            tampered.loc[tampered['ticker'] == 'AAA', 'legacy_only'] = 'injected'
            tampered.to_parquet(path)
            with self.assertRaisesRegex(ValueError, 'invalid_existing_v2'):
                c.merge_same_day_snapshot(path, pd.DataFrame([correction]))

    def test_vendor_access_is_independent_of_estimate_value(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for eps_access, revenue_access, errors in (
                (True, True, []), (True, False, [{'ticker': 'AAA', 'vendor': 'finnhub',
                    'endpoint': '/stock/revenue-estimate', 'vendor_entitlement_blocked': True,
                    'status_code': 403}]), (False, False, [{'ticker': 'AAA', 'vendor': 'finnhub',
                    'endpoint': '/stock/eps-estimate', 'vendor_entitlement_blocked': True,
                    'status_code': 403}])):
                row = snapshot('2026-07-01T18:00:00Z', None, eps_payload={'data': [estimate(None)]},
                               revenue_payload={'data': [estimate(None)]},
                               eps_estimate_access=eps_access, revenue_estimate_access=revenue_access)
                with patch.object(c, 'collect_live_snapshot', return_value=(pd.DataFrame([row]), errors)), \
                     patch.object(sys, 'argv', ['collector', '--tickers', 'AAA', '--api-key', 'fixture',
                         '--fetch-date', '2026-07-01', '--snapshot-dir', str(root / 'snapshots'),
                         '--signals-output', str(root / 'signals.parquet'), '--summary', str(root / 'summary.json')]), \
                     contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(c.main(), 0)
                payload = json.loads((root / 'summary.json').read_text())
                self.assertEqual(payload['vendor_estimate_access'], eps_access and revenue_access)
                self.assertEqual(payload['eps_estimate_access_rows'], int(eps_access))
                self.assertEqual(payload['revenue_estimate_access_rows'], int(revenue_access))
                self.assertEqual(payload['estimate_value_rows'], 0)
                self.assertEqual(payload['status'], 'blocked_partial_coverage' if eps_access else 'blocked_vendor_entitlement')
                self.assertEqual(payload['vendor_access_rows'], int(eps_access and revenue_access))

    def test_live_collection_stops_at_utc_rollover(self):
        clocks = ['2026-07-01T23:59:59Z'] * 2 + ['2026-07-02T00:00:00Z'] * 2
        with patch.object(c, 'utc_now', side_effect=clocks), patch.object(
                c, 'fetch_estimate_payloads_by_order', return_value=({}, {}, 'fmp', True, True, True)) as fetch:
            with self.assertRaisesRegex(ValueError, 'collection_utc_day_rollover'):
                c.collect_live_snapshot(['AAA', 'BBB'], finnhub_api_key='', alphavantage_api_key='',
                    fmp_api_key='fixture', vendor_order=['fmp'], fetch_date=pd.Timestamp('2026-07-01'),
                    sleep_seconds=0, max_errors=10)
            self.assertEqual(fetch.call_count, 1)

    def test_recommendation_is_not_breadth(self):
        row = snapshot()
        self.assertEqual(row['analyst_recommendation_balance'], .75)
        self.assertIsNone(row['est_eps_revision_breadth'])
        self.assertIsNone(features([row]).iloc[0]['est_eps_revision_breadth'])

    def test_missing_not_zero(self):
        row = snapshot(eps_payload={"data": [estimate(None)]}, revenue_payload={})
        self.assertIsNone(row['est_eps_fy1'])
        self.assertEqual(row['eps_fy1_status'], 'MISSING')
        self.assertEqual(row['rev_fy1_status'], 'NO_COVERAGE')
        self.assertIsNone(snapshot(recommendation_payload=[])['analyst_recommendation_balance'])

    def test_same_period_revision_eps_and_revenue(self):
        rows = [snapshot(), snapshot('2026-05-02T18:00:00Z', 1.2,
                                    revenue_payload={"data": [estimate(110)]})]
        last = features(rows).iloc[-1]
        self.assertAlmostEqual(last.est_eps_revision_30d, .2)
        self.assertAlmostEqual(last.est_rev_revision_30d, .1)

    def test_fy_roll_is_not_revision(self):
        last = features([snapshot(),snapshot('2026-05-02T18:00:00Z',2,'2027-12-31')]).iloc[-1]
        self.assertTrue(pd.isna(last.est_eps_revision_30d))

    def test_fy_view_can_match_prior_fy2_only_same_identity(self):
        before = snapshot(eps_payload={"data":[estimate(1),estimate(2,'2027-12-31')]})
        after = snapshot('2026-05-02T18:00:00Z',2.2,'2027-12-31')
        self.assertAlmostEqual(h1.same_period_revision(after,before),.1)
        self.assertEqual(json.loads(after['eps_fy1_identity'])['fiscal_period_end'],'2027-12-31')

    def test_currency_unit_security_and_basis_block(self):
        before=snapshot()
        for key,value in [('currency','EUR'),('share_or_ADR_unit','ADR_2_COMMON'),('security_id','FIGI:OTHER'),('issuer_id','CIK:2'),('accounting_basis','NON_GAAP'),('period_type','QUARTERLY')]:
            item=estimate(1.2); item[key]=value
            after=snapshot('2026-05-02T18:00:00Z',eps_payload={'data':[item]})
            self.assertIsNone(h1.same_period_revision(after,before),key)

    def test_after_close_and_utc_offsets(self):
        row=snapshot('2026-07-01T16:01:00-04:00')
        self.assertTrue(c.latest_signal_by_ticker(features([row]),decision_date='2026-07-01T20:00:00Z').empty)
        self.assertFalse(c.latest_signal_by_ticker(features([row]),decision_date='2026-07-02T20:00:00Z').empty)
        self.assertTrue(c.latest_signal_by_ticker(features([row]),decision_date='2026-07-01').empty)

    def test_no_snapshot_historical_backfill(self):
        row=snapshot('2026-07-02T21:00:00Z',fetch_date=pd.Timestamp('2000-01-01'))
        self.assertEqual(row['as_of_date'],'2026-07-02')
        self.assertTrue(c.compute_estimate_revision_features(pd.DataFrame([row]),as_of_date='2000-01-01')[0].empty)
        with patch.object(sys,'argv',['collector','--fetch-date','2000-01-01']):
            with self.assertRaisesRegex(ValueError,'backfill'): c.main()

    def test_frozen_pre_announcement(self):
        before=snapshot('2026-07-01T19:59:00Z',1)
        simultaneous=snapshot('2026-07-01T20:00:00Z',3)
        after=snapshot('2026-07-01T20:01:00Z',9)
        identity=json.loads(before['eps_fy1_identity'])
        frozen=h1.frozen_pre_event_consensus([before,simultaneous,after],event_available_at='2026-07-01T20:00:00Z',identity=identity,fetch_source='finnhub')
        self.assertEqual(frozen['value'],1)
        self.assertAlmostEqual(h1.earnings_surprise(1.5,frozen,identity=identity,announcement_at='2026-07-01T20:00:00Z'),.5)
        self.assertIsNone(h1.earnings_surprise(1.5,frozen,identity={**identity,'currency':'EUR'},announcement_at='2026-07-01T20:00:00Z'))
        self.assertIsNone(snapshot(earnings_payload=[{'period':'2026-06-30','surprisePercent':99}])['earnings_surprise_last'])

    def test_provider_corrections_preserve_versions(self):
        before=snapshot('2026-07-01T19:00:00Z',1)
        correction=snapshot('2026-07-01T21:00:00Z',2,provider_published_at='2026-06-01T00:00:00Z')
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'estimates.parquet'; pd.DataFrame([before]).to_parquet(p)
            merged,_=c.merge_same_day_snapshot(p,pd.DataFrame([correction]))
            self.assertEqual(len(merged),2)
            self.assertEqual(c.latest_signal_by_ticker(merged,decision_date='2026-07-01T20:00:00Z').iloc[0].est_eps_fy1,1)
            self.assertNotEqual(before['snapshot_version_id'],correction['snapshot_version_id'])

    def test_causal_event_dedupe(self):
        key=h1.causal_event_id('CIK:1','2026-06-30','2026-07-01T20:00:00Z')
        rows=[dict(causal_event_id=key,causal_link_verified=True,kind=k) for k in ['surprise','revision','rating','target_price','news']]
        self.assertEqual(len(h1.dedupe_causal_events(rows+rows)),1)
        self.assertEqual(len(h1.dedupe_causal_events(rows)[0]['reactions']),5)
        self.assertEqual(h1.dedupe_causal_events([dict(causal_event_id=key)]),[])

    def test_provider_missing_preserves_attempted_candidate(self):
        with patch.object(c,'fetch_estimate_payloads_by_order',return_value=({}, {}, 'fmp', True, True, True)):
            rows,_,attempted,_=c.collect_live_snapshot(['AAA','BBB'],finnhub_api_key='',alphavantage_api_key='',fmp_api_key='fixture',vendor_order=['fmp'],fetch_date=pd.Timestamp('2026-07-01'),sleep_seconds=0,max_errors=10)
        self.assertEqual(rows.ticker.tolist(),['AAA','BBB'])
        self.assertEqual(attempted,['AAA','BBB'])
        self.assertEqual(rows.provider_coverage_status.tolist(),['NO_COVERAGE','NO_COVERAGE'])

    def test_partial_update_equals_full_recompute(self):
        rows=[snapshot(ticker='AAA'),snapshot(ticker='BBB'),snapshot('2026-05-02T18:00:00Z',1.2),snapshot('2026-05-02T18:00:00Z',1.3,ticker='BBB')]
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'day.parquet'; pd.DataFrame(rows[:3]).to_parquet(p)
            merged,_=c.merge_same_day_snapshot(p,pd.DataFrame(rows[3:]))
            expected=features(rows).sort_values(['ticker','available_from']).reset_index(drop=True)
            actual=features(merged.to_dict('records')).sort_values(['ticker','available_from']).reset_index(drop=True)
            pd.testing.assert_frame_equal(actual,expected,check_like=True)

    def test_explicit_zero_remains_zero(self):
        row=snapshot(value=0)
        self.assertEqual(row['est_eps_fy1'],0)
        self.assertEqual(row['eps_fy1_status'],'EXPLICIT_ZERO')
        self.assertEqual(h1.same_period_revision(snapshot('2026-05-02T18:00:00Z',0),snapshot()),-1)
        self.assertIsNone(h1.same_period_revision(snapshot('2026-05-02T18:00:00Z',1),row))

    def test_null_survives_storage_and_compute(self):
        row=snapshot(value=None)
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'test.parquet'; pd.DataFrame([row]).to_parquet(p)
            out=features(pd.read_parquet(p).to_dict('records'))
            self.assertTrue(pd.isna(out.iloc[0].est_eps_fy1))
            self.assertTrue(pd.isna(out.iloc[0].est_eps_revision_30d))
        for value in [None,'',float('nan'),float('inf'),True]: self.assertIsNone(h1.optional_float(value))

    def test_incomplete_identity_and_date_only_are_not_admitted(self):
        after=snapshot('2026-05-02T18:00:00Z',eps_payload={'data':[{'period':'2026','avg':2}]})
        self.assertIsNone(h1.same_period_revision(after,snapshot()))
        self.assertIsNone(h1.iso_utc('2026-07-01'))
        self.assertIsNone(h1.iso_utc('2026-07-01T20:00:00'))
        self.assertTrue(features([{'ticker':'AAA','available_from':'2026-07-01','est_eps_fy1':1}]).empty)

    def test_vendor_switch_not_revision(self):
        self.assertIsNone(h1.same_period_revision(snapshot('2026-05-02T18:00:00Z',2,fetch_source='fmp'),snapshot()))

    def test_revenue_fy1_is_first_not_last(self):
        row=snapshot(revenue_payload={'data':[estimate(100),estimate(200,'2027-12-31')]})
        self.assertEqual(row['est_rev_fy1'],100)
        self.assertEqual(row['rev_fy1_period_end'],'2026-12-31')

    def test_h2_consumers_stay_inactive(self):
        signals=features([snapshot(),snapshot('2026-05-02T18:00:00Z',2)])
        scored=pd.DataFrame([{'ticker':'AAA','score':.7,'portfolio_future_winner_engine_score':1},{'ticker':'BBB','score':.8,'portfolio_future_winner_engine_score':2}])
        out,summary=c.apply_estimate_revision_confirmation(scored,signals,decision_date='2026-05-03',enabled=True)
        self.assertEqual(out.portfolio_future_winner_engine_score.tolist(),[1,2])
        args=dict(decision_date=pd.Timestamp('2026-05-03'),listing=pd.DataFrame(),earnings_calendar=pd.DataFrame(),top_n=2)
        baseline,_=build_overlay(scored,signals=pd.DataFrame(),**args)
        result,_=build_overlay(scored,signals=signals,**args)
        pd.testing.assert_frame_equal(baseline,result)

    def test_availability_uses_latest_required_timestamp(self):
        row=snapshot('2026-07-01T18:00:00Z',collected_at='2026-07-02T18:00:00Z',first_seen_at='2026-06-01T18:00:00Z')
        self.assertEqual(row['strategy_available_at'],'2026-07-02T18:00:00Z')

    def test_missing_latest_does_not_fall_back_to_old_known(self):
        rows=[snapshot(),snapshot('2026-04-02T18:00:00Z',None),snapshot('2026-05-03T18:00:00Z',2)]
        self.assertTrue(pd.isna(features(rows).iloc[-1].est_eps_revision_30d))

    def test_conflicting_same_time_is_unknown(self):
        before=snapshot(); conflict=snapshot(value=3); after=snapshot('2026-05-02T18:00:00Z',2)
        self.assertTrue(pd.isna(features([before,conflict,after]).iloc[-1].est_eps_revision_30d))

    def test_frozen_latest_missing_or_absent_is_not_backfilled(self):
        before=snapshot('2026-07-01T18:00:00Z',1)
        identity=json.loads(before['eps_fy1_identity'])
        for latest in [snapshot('2026-07-01T19:00:00Z',None), snapshot('2026-07-01T19:00:00Z',eps_payload={},revenue_payload={})]:
            self.assertIsNone(h1.frozen_pre_event_consensus([before,latest],event_available_at='2026-07-01T20:00:00Z',identity=identity,fetch_source='finnhub'))

    def test_current_conflict_rejects_both_orders(self):
        before=snapshot(); a=snapshot('2026-05-02T18:00:00Z',2); b=snapshot('2026-05-02T18:00:00Z',3)
        for rows in ([before,a,b],[before,b,a]):
            result=features(rows)
            self.assertTrue(result.iloc[-2:].est_eps_revision_30d.isna().all())
            self.assertTrue(c.latest_signal_by_ticker(result,decision_date='2026-05-03').empty)

    def test_forward_view_preserves_history_and_sorts_canonical_period(self):
        items=[]
        for year in [2027,2020,2026,2021]:
            item=estimate(year, f'{year}-12-31'); item['fiscal_period_end']=item.pop('period'); items.append(item)
        row=snapshot('2026-07-01T18:00:00Z',eps_payload={'data':items})
        self.assertEqual(row['est_eps_fy1'],2026)
        self.assertEqual(row['est_eps_fy2'],2027)
        self.assertEqual(len(h1.consensus_records(row)),5)
        self.assertEqual(snapshot('2026-07-01T18:00:00Z',eps_payload={'data':[estimate(1,'2020-12-31')]},revenue_payload={})['has_forward_estimate'],0)

    def test_missing_publication_precision_preserved_and_blocked(self):
        row=snapshot(provider_published_at='2027-01-01')
        self.assertEqual(row['publication_status'],'UNKNOWN_PUBLICATION_PRECISION')
        self.assertIn('2027-01-01',row['provider_published_at_raw'])
        self.assertIsNone(row['strategy_available_at'])
        self.assertTrue(features([row]).empty)

    def test_live_endpoint_status_separates_failures(self):
        def fetch(_session,endpoint,ticker,_key,*,errors,**_):
            if endpoint=='/stock/eps-estimate':
                errors.append(dict(ticker=ticker,vendor='finnhub',endpoint=endpoint,status_code=500,vendor_entitlement_blocked=False))
                return None
            if endpoint=='/stock/revenue-estimate': return {'data':[estimate(100)]}
            return []
        args=dict(finnhub_api_key='fixture',alphavantage_api_key='',fmp_api_key='',vendor_order=['finnhub'],fetch_date=pd.Timestamp('2026-07-01'),sleep_seconds=0,max_errors=10)
        with patch.object(c,'fetch_json_optional',side_effect=fetch), patch.object(c,'utc_now',return_value='2026-07-01T18:00:00Z'):
            rows,_,_,_=c.collect_live_snapshot(['AAA'],**args)
        row=rows.iloc[0]
        self.assertEqual(row.eps_fy1_status,'FETCH_FAILED')
        self.assertEqual(row.rev_fy1_status,'OBSERVED')
        self.assertEqual(row.provider_coverage_status,'PARTIAL')
        def rec_failed(_session,endpoint,ticker,_key,*,errors,**_):
            if endpoint=='/stock/recommendation':
                errors.append(dict(ticker=ticker,vendor='finnhub',endpoint=endpoint,status_code=500,vendor_entitlement_blocked=False))
                return None
            return {'data':[]} if endpoint in c.ESTIMATE_ENDPOINTS else []
        with patch.object(c,'fetch_json_optional',side_effect=rec_failed):
            rows,_,_,_=c.collect_live_snapshot(['AAA'],**args)
        self.assertEqual(rows.iloc[0].provider_coverage_status,'NO_COVERAGE')
        self.assertEqual(rows.iloc[0].recommendation_fetch_status,'FETCH_FAILED')

    def test_vendor_normalization_retains_missing_and_zero(self):
        eps,_=c.fmp_to_payloads([dict(date='2026-12-31',epsAvg=None),dict(date='2027-12-31',epsAvg=0)])
        self.assertEqual(len(eps['data']),2)
        self.assertIsNone(eps['data'][0]['avg'])
        self.assertEqual(eps['data'][1]['avg'],0)
        self.assertEqual(eps['data'][1]['period_type'],'ANNUAL')

    def test_failed_live_refresh_invalidates_frozen_provider(self):
        before=snapshot('2026-07-01T18:00:00Z',1)
        def failed(_session,endpoint,ticker,_key,*,errors,**_):
            errors.append(dict(ticker=ticker,vendor='finnhub',endpoint=endpoint,status_code=500,vendor_entitlement_blocked=False))
            return None
        with patch.object(c,'fetch_json_optional',side_effect=failed),patch.object(c,'utc_now',return_value='2026-07-01T19:00:00Z'):
            rows,_,_,_=c.collect_live_snapshot(['AAA'],finnhub_api_key='fixture',alphavantage_api_key='',fmp_api_key='',vendor_order=['finnhub'],fetch_date=pd.Timestamp('2026-07-01'),sleep_seconds=0,max_errors=10)
        failed_row=rows.iloc[0].to_dict()
        self.assertEqual(failed_row['fetch_source'],'')
        self.assertEqual(failed_row['attempted_estimate_providers_json'],'["finnhub"]')
        self.assertIsNone(h1.frozen_pre_event_consensus([before,failed_row],event_available_at='2026-07-01T20:00:00Z',identity=json.loads(before['eps_fy1_identity']),fetch_source='finnhub'))

if __name__=='__main__': unittest.main()
