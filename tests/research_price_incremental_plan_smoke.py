"""Synthetic supplied bytes, real intake API; no Source/PIT admission."""
from __future__ import annotations
import copy
import hashlib
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import research_price_incremental_plan as h
from research import a2_research_intake_v1 as intake

CUTOFF = '2026-10-19T20:30:00Z'
NOW = '2026-10-19T20:20:00Z'
FRIDAY = '2026-10-16T20:20:00Z'
EXPIRY = '2026-10-21T00:00:00Z'


def clocks(t):
    return dict.fromkeys(h.CLOCK, t)


class Fixture:
    def __init__(self):
        self.blobs = {}
        self.identity = dict(security_id='US:SEC1', issuer_id='CIK:0001', provider_security_id='PROVIDER:SEC1',
                             mic='XNYS', calendar_id='CAL:NYSE', country='US', currency='USD')
        self.scope = dict(identity=self.identity, provider='SUPPLIED_VENDOR', feed='SUPPLIED_FEED', adjustment='raw',
                          window={'start': '2026-10-16', 'end_exclusive': '2026-10-20'})
        self.cal = dict(schema='supplied-price-session-calendar-v1', mic='XNYS', calendar_id='CAL:NYSE',
                        country='US', currency='USD', coverage=copy.deepcopy(self.scope['window']),
                        sessions=[dict(session='2026-10-16', close_at='2026-10-16T20:00:00Z'),
                                  dict(session='2026-10-19', close_at='2026-10-19T20:00:00Z')],
                        **clocks('2026-10-01T00:00:00Z'))
        self.subject = dict(request_id='R1', **self.scope, calendar_sha256=self.put(self.cal),
                            prior_sha256=None, current_sha256=None, failure_sha256=None, delta=None)

    def put(self, value):
        raw = intake.canonical(value); sha = hashlib.sha256(raw).hexdigest()
        self.blobs['SHA256:' + sha] = raw
        return sha

    def price(self, days=('2026-10-16', '2026-10-19'), *, last=102, observed=NOW, expiry=EXPIRY):
        return dict(schema='supplied-daily-close-inventory-v1', **copy.deepcopy(self.scope), **clocks(observed),
                    expires_at=expiry, bars=[dict(session=d, close=100 if i == 0 else last,
                        **clocks(FRIDAY if d == '2026-10-16' else observed)) for i, d in enumerate(days)])

    def context(self, price, **changes):
        out = dict(security_id=self.identity['security_id'], issuer_id=self.identity['issuer_id'],
                   fingerprints={k: 'a' * 64 for k in intake.FINGERPRINTS}, expires_at=price['expires_at'],
                   exceptions={k: False for k in intake.EXCEPTIONS}, research_reuse_ready=True, affected_pillars=[])
        out['fingerprints']['market_price'] = h.price_fingerprint(price)
        out.update(changes)
        return out

    def bind(self, current=None, prior=None, current_context=None, prior_context=None):
        self.subject['current_sha256'] = None if current is None else self.put(current)
        self.subject['prior_sha256'] = None if prior is None else self.put(prior)
        if current_context is not None:
            self.subject['delta'] = dict(current_sha256=self.put(current_context),
                previous_sha256=None if prior_context is None else self.put(prior_context))

    def run(self, cutoff=CUTOFF, subjects=None, inventory_time=NOW):
        raw = intake.canonical(dict(schema='supplied-price-incremental-inventory-v1', **clocks(inventory_time),
                                    subjects=subjects or [self.subject]))
        return h.plan_incremental(raw, intake.digest(raw), artifact_resolver=intake.MemoryArtifacts(self.blobs), cutoff=cutoff)


class PriceIncrementalTests(unittest.TestCase):
    def test_missing_only_and_original_bytes_reused(self):
        f = Fixture(); p = f.price(('2026-10-16',), observed=FRIDAY); f.bind(p)
        before = copy.deepcopy(f.blobs); r = f.run()['rows'][0]
        self.assertEqual(r['status'], 'STALE')
        self.assertEqual(r['reusable_sessions'], ['2026-10-16'])
        self.assertEqual(r['collection_plan']['sessions'], ['2026-10-19'])
        self.assertEqual(f.blobs, before)
        self.assertFalse(r['collection_plan']['execute'])

    def test_weekend_and_holiday_never_inferred(self):
        f = Fixture(); f.scope['window'] = dict(start='2026-07-02', end_exclusive='2026-07-07')
        f.subject['window'] = copy.deepcopy(f.scope['window']); f.cal['coverage'] = copy.deepcopy(f.scope['window'])
        f.cal['sessions'] = [dict(session='2026-07-02', close_at='2026-07-02T20:00:00Z'),
                             dict(session='2026-07-06', close_at='2026-07-06T20:00:00Z')]
        f.subject['calendar_sha256'] = f.put(f.cal)
        r = f.run()['rows'][0]
        self.assertEqual(r['missing_sessions'], ['2026-07-02', '2026-07-06'])
        self.assertEqual(r['status'], 'MISSING')

    def test_pre_close_and_availability_cutoff(self):
        f = Fixture(); f.bind(f.price(('2026-10-16',), observed=FRIDAY))
        r = f.run('2026-10-19T19:59:00Z', inventory_time=FRIDAY)['rows'][0]
        self.assertEqual(r['status'], 'FRESH'); self.assertEqual(r['missing_sessions'], [])
        p = f.price(); p['bars'][-1]['available_at'] = '2026-10-19T20:31:00Z'; f.bind(p)
        self.assertEqual(f.run()['rows'][0]['status'], 'CONFLICTING')
        p = f.price(); p['bars'][-1].update(clocks('2026-10-19T19:59:00Z')); f.bind(p)
        self.assertEqual(f.run()['rows'][0]['reason'], 'PRICE_CLOSE_CLOCK')

    def test_supplied_early_close(self):
        f = Fixture(); f.cal['sessions'][-1]['close_at'] = '2026-10-19T17:00:00Z'
        f.subject['calendar_sha256'] = f.put(f.cal)
        r = f.run('2026-10-19T17:01:00Z', inventory_time='2026-10-19T17:00:30Z')['rows'][0]
        self.assertEqual(r['missing_sessions'], ['2026-10-16', '2026-10-19'])

    def test_identity_feed_adjustment_window_mismatch(self):
        for key, change in [('identity', {**Fixture().identity, 'mic': 'XNAS'}), ('provider', 'OTHER'),
                            ('feed', 'OTHER'), ('adjustment', 'split'),
                            ('window', dict(start='2026-10-15', end_exclusive='2026-10-20'))]:
            with self.subTest(key=key):
                f = Fixture(); p = f.price(); p[key] = change; f.bind(p)
                self.assertEqual(f.run()['rows'][0]['status'], 'CONFLICTING')
        f = Fixture(); f.subject['identity']['calendar_id'] = 'OTHER'
        self.assertEqual(f.run()['rows'][0]['reason'], 'CALENDAR_IDENTITY')

    def test_missing_identity_calendar_and_bad_hash_block_independently(self):
        for change in ('identity', 'calendar', 'hash'):
            f = Fixture()
            if change == 'identity': f.subject['identity']['security_id'] = None
            elif change == 'calendar': f.blobs.clear()
            else: f.subject['calendar_sha256'] = None
            good = Fixture(); good.subject['request_id'] = 'GOOD'; good.bind(good.price())
            good.identity['security_id'] = 'US:INDEPENDENT'
            good.identity['issuer_id'] = 'CIK:0003'
            good.identity['provider_security_id'] = 'PROVIDER:INDEPENDENT'
            good.bind(good.price())
            f.blobs.update(good.blobs)
            if change == 'calendar': f.subject['calendar_sha256'] = 'f' * 64
            rows = f.run(subjects=[f.subject, good.subject])['rows']
            self.assertEqual(rows[0]['status'], 'BLOCKED'); self.assertEqual(rows[1]['status'], 'FRESH')

    def test_stale_AVB_and_failed_BLD_not_fresh(self):
        f = Fixture(); f.subject['request_id'] = 'AVB_AUDIT_SHAPE'
        f.bind(f.price(('2026-10-16',), observed=FRIDAY))
        b = Fixture(); b.subject['request_id'] = 'BLD_AUDIT_SHAPE'
        b.identity['security_id'] = 'US:SEC2'; b.identity['issuer_id'] = 'CIK:0002'; b.identity['provider_security_id'] = 'PROVIDER:SEC2'
        b.subject['failure_sha256'] = b.put(dict(schema='supplied-price-source-failure-v1', **b.scope, **clocks(NOW)))
        f.blobs.update(b.blobs)
        rows = f.run(subjects=[f.subject, b.subject])['rows']
        self.assertEqual([r['status'] for r in rows], ['STALE', 'BLOCKED'])
        self.assertEqual(rows[1]['reason'], 'SOURCE_FAILURE')
        self.assertEqual(len(rows[1]['missing_sessions']), 2)

    def test_real_delta_api_price_only(self):
        f = Fixture(); prior = f.price(last=101, observed='2026-10-19T20:10:00Z'); current = f.price(last=102)
        f.bind(current, prior, f.context(current), f.context(prior))
        with patch.object(intake, 'plan_delta', wraps=intake.plan_delta) as api:
            out = f.run(); r = out['rows'][0]['delta']['result']
        self.assertEqual(api.call_count, 1)
        self.assertEqual(r['changed'], ['market_price']); self.assertEqual(r['refresh'], ['ER', 'market', 'valuation'])
        self.assertFalse(r['execution_permitted']); self.assertIsNone(out['validated_er'])
        self.assertFalse(any(out['authority'].values()))

    def test_same_hash_and_exception_review(self):
        for exception in (None, *intake.EXCEPTIONS):
            f = Fixture(); p = f.price(); a = f.context(p); b = copy.deepcopy(a)
            if exception: b['exceptions'][exception] = True
            f.bind(p, p, b, a); r = f.run()['rows'][0]['delta']['result']
            self.assertEqual(r['plan'], 'REFRESH_REQUIRED' if exception else 'SKIP_UNCHANGED')
            self.assertNotIn('full_a3_review', r['refresh'])

    def test_expired_identical_price_requires_review(self):
        f = Fixture(); p = f.price(expiry='2026-10-19T20:25:00Z'); c = f.context(p)
        f.bind(p, p, c, c); r = f.run()['rows'][0]
        self.assertEqual(r['status'], 'STALE'); self.assertEqual(r['missing_sessions'], [])
        self.assertIn('expiry', r['delta']['result']['exceptions'])

    def test_failure_exception_preserved_and_identity_malformed_not_promoted(self):
        f = Fixture(); p = f.price(); c = f.context(p); now = copy.deepcopy(c); now['exceptions']['source_failure'] = True
        f.bind(p, p, now, c)
        f.subject['failure_sha256'] = f.put(dict(schema='supplied-price-source-failure-v1', **f.scope, **clocks(NOW)))
        r = f.run()['rows'][0]
        self.assertEqual(r['status'], 'BLOCKED'); self.assertIn('source_failure', r['delta']['result']['exceptions'])
        f.bind(p, p, c, c)
        self.assertEqual(f.run()['rows'][0]['delta']['reason'], 'DELTA_FAILURE_EXCEPTION')

    def test_invalid_prices_never_reach_delta(self):
        for bad in (0, -1, True, '102'):
            f = Fixture(); p = f.price(); p['bars'][-1]['close'] = bad; f.bind(p)
            with patch.object(intake, 'plan_delta', side_effect=AssertionError('invalid price reached API')):
                r = f.run()['rows'][0]
            self.assertEqual(r['status'], 'CONFLICTING'); self.assertIsNone(r['delta']['result'])

    def test_wrong_delta_hash_and_nonprice_change_refused(self):
        for mode in ('hash', 'scope', 'context'):
            f = Fixture(); p = f.price(); a = f.context(p); b = copy.deepcopy(a)
            if mode == 'hash': b['fingerprints']['market_price'] = 'b' * 64
            elif mode == 'scope': b['fingerprints']['industry'] = 'b' * 64
            else: b['fingerprints'] = []
            f.bind(p, p, b, a); r = f.run()['rows'][0]
            self.assertEqual(r['delta']['status'], 'BLOCKED'); self.assertIsNone(r['delta']['result'])

    def test_inventory_and_duplicate_refusals(self):
        f = Fixture(); memory = intake.MemoryArtifacts(f.blobs)
        with self.assertRaises(h.PricePlanError): h.plan_incremental(b'{}', 'a' * 64, artifact_resolver=memory, cutoff=CUTOFF)
        with self.assertRaises(h.PricePlanError): f.run(subjects=[f.subject, f.subject])
        p = f.price(); p['bars'].append(copy.deepcopy(p['bars'][-1])); f.bind(p)
        self.assertEqual(f.run()['rows'][0]['reason'], 'DUPLICATE_OR_UNORDERED_SESSION')

    def test_prior_after_clock_regression_and_same_vintage_conflict(self):
        for mode in ('envelope', 'row', 'same_vintage'):
            f = Fixture(); before = f.price(); after = f.price()
            if mode == 'envelope': after.update(clocks('2026-10-19T20:10:00Z')); after['bars'][-1].update(clocks('2026-10-19T20:10:00Z'))
            elif mode == 'row': after['bars'][-1].update(clocks('2026-10-19T20:10:00Z'))
            else: after['bars'][-1]['close'] = 103
            f.bind(after, before, f.context(after), f.context(before))
            with patch.object(intake, 'plan_delta', side_effect=AssertionError('invalid transition reached API')):
                row = f.run()['rows'][0]
            self.assertEqual(row['status'], 'CONFLICTING')
            self.assertEqual(row['reason'], 'CONFLICTING_PRICE_VINTAGE' if mode == 'same_vintage' else 'PRICE_TIME_REGRESSION')

    def test_prior_original_rows_not_recollected_for_partial_current(self):
        f = Fixture(); before = f.price(('2026-10-16',), observed=FRIDAY); current = f.price(('2026-10-19',))
        f.bind(current, before)
        with patch.object(intake, 'plan_delta', side_effect=AssertionError('partial current delta consumed')):
            row = f.run()['rows'][0]
        self.assertEqual(row['status'], 'FRESH')
        self.assertEqual(row['missing_sessions'], [])
        self.assertEqual(row['reusable_sources'], {'2026-10-16': f.subject['prior_sha256'], '2026-10-19': f.subject['current_sha256']})
        self.assertEqual(row['delta']['reason'], 'CURRENT_PRICE_SNAPSHOT_INCOMPLETE_FOR_DELTA')
        self.assertFalse(row['collection_plan']['execute'])
        f.subject['current_sha256'] = None
        row = f.run()['rows'][0]
        self.assertEqual(row['missing_sessions'], ['2026-10-19'])
        self.assertEqual(row['reusable_sessions'], ['2026-10-16'])


    def test_numeric_equal_closes_skip_actual_delta(self):
        for reverse in (False, True):
            f = Fixture(); prior = f.price(); current = f.price()
            for bar in prior['bars']: bar['close'] = 100.0 if reverse else 100
            for bar in current['bars']: bar['close'] = 100 if reverse else 100.0
            self.assertNotEqual(intake.canonical(prior), intake.canonical(current))
            self.assertEqual(h.price_fingerprint(prior), h.price_fingerprint(current))
            f.bind(current, prior, f.context(current), f.context(prior))
            with patch.object(intake, 'plan_delta', wraps=intake.plan_delta) as api:
                result = f.run()['rows'][0]['delta']['result']
            self.assertEqual(api.call_count, 1)
            self.assertEqual(result['plan'], 'SKIP_UNCHANGED')
            self.assertEqual(result['changed'], [])
            self.assertEqual(result['refresh'], [])

    def test_numeric_hash_preserves_large_integer_and_small_float_precision(self):
        def fingerprint(close):
            f = Fixture(); value = f.price()
            value['bars'][-1]['close'] = close
            return h.price_fingerprint(value)
        self.assertEqual(fingerprint(9007199254740992), fingerprint(9007199254740992.0))
        self.assertNotEqual(fingerprint(9007199254740993), fingerprint(9007199254740992.0))
        self.assertNotEqual(fingerprint(0.1), fingerprint(0.10000000000000002))
        self.assertNotEqual(fingerprint(1e-320), fingerprint(2e-320))

if __name__ == '__main__':
    unittest.main()
