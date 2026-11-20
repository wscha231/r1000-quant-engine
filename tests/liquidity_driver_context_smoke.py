"""Synthetic contract regressions, NOT historical returns or live evidence."""
from __future__ import annotations
import copy
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.liquidity_driver_context import (INPUT_SCHEMA, SOURCES, ContractError,
    ResearchConfig, attach_to_canonical, evaluate, feature_view, select_series, stamp)

SHA = 'bcb14c06613e34420ce7988e5bb1ac5547b22b57'
ASOF = '2026-09-14T20:00:00+00:00'


def fixture():
    packet = dict(schema=INPUT_SCHEMA, fixture_only=True, datasets={}, policy_events=[])
    ranges = {
        'WALCL': (7000000, 6800000), 'WRESBAL': (3000000, 3000000),
        'WTREGEN': (900000, 800000), 'RRPONTSYD': (.02, 0.),
        'WLCFLPCL': (1000, 1000), 'SOFR': (4., 4.), 'IORB': (4., 4.),
        'TOTCI': (2700, 2900), 'DPSACBW027SBOG': (17000, 18000),
        'DRTSCILM': (-5, -5), 'DRSDCILM': (10, 10),
        'BAMLH0A0HYM2': (3.5, 3.), 'DGS10': (4.2, 3.9),
        'T10YIE': (2.5, 2.2), 'BREADTH_ABOVE_200D': (35, 65),
        'M2SL': (21000, 22000), 'CPIAUCSL': (100, 102)}
    for sid, (unit, frequency, _, _) in SOURCES.items():
        if frequency == 'monthly':
            days = [date(2026, m, 1) for m in range(2, 9)]
        elif frequency == 'quarterly':
            days = [date(2026, 4, 1), date(2026, 7, 1)]
        else:
            step = 1 if frequency == 'daily' else 7
            days = [date(2026, 9, 11) - timedelta(days=step*i)
                    for i in reversed(range(121 if step == 1 else 19))]
        a, b = ranges[sid]
        values = [a + (b-a)*i/(len(days)-1) for i in range(len(days))]
        if sid == 'CPIAUCSL':
            values = [100, 100.4, 100.8, 101.2, 101.35, 101.5, 101.65]
        rows = [dict(series=sid, observation_date=d.isoformat(), value=value,
                    evidence='current_only', available_at=ASOF, retrieved_at=ASOF,
                    published_at=None, vintage_date=None)
                for d, value in zip(days, values)]
        raw = json.dumps(rows, sort_keys=True).encode()
        packet['datasets'][sid] = dict(unit=unit, frequency=frequency,
            status='COLLECTED', rows=rows, raw_sha256=[hashlib.sha256(raw).hexdigest()])
    return packet


def run(packet=None, **kwargs):
    return evaluate(packet or fixture(), as_of=kwargs.pop('as_of', ASOF),
                    source_commit=SHA, **kwargs)


def slope(packet, sid, first, last):
    rows = packet['datasets'][sid]['rows']
    for i, row in enumerate(rows):
        row['value'] = first + (last-first)*i/(len(rows)-1)


class LiquidityTests(unittest.TestCase):
    def test_fed_shrink_bank_expand_not_forced_cash(self):
        r = run()
        self.assertLess(r['features']['fed_assets_change_bn'], 0)
        self.assertEqual(r['dominant_driver_hypothesis'], 'BANK_CREDIT_SUPPORTED')
        self.assertFalse(r['cash_defense_review'])
        self.assertFalse(r['equity_reentry_review'])

    def test_fed_expand_during_crisis_not_risk_on(self):
        p = fixture()
        slope(p, 'WALCL', 6800000, 7200000)
        slope(p, 'SOFR', 5., 5.)
        slope(p, 'BAMLH0A0HYM2', 3, 7)
        r = run(p)
        self.assertEqual(r['dominant_driver_hypothesis'], 'STRESS_DOMINANT')
        self.assertTrue(r['cash_defense_review'])
        self.assertFalse(r['equity_reentry_review'])

    def test_rrp_near_zero_no_percentage_explosion(self):
        r = run()
        self.assertEqual(r['features']['rrp_buffer_to_reserves'], 0)
        self.assertLess(abs(r['features']['rrp_change_bn']), .1)
        self.assertNotIn('rrp_growth_pct', r['features'])

    def test_tga_missing_not_zero_or_green(self):
        p = fixture(); del p['datasets']['WTREGEN']
        r = run(p)
        self.assertEqual(r['axes']['treasury'], 'UNKNOWN')
        self.assertIsNone(r['features']['tga_change_bn'])
        self.assertEqual(r['quality_status'], 'PARTIAL')
        self.assertFalse(r['cash_defense_review'])

    def test_current_revised_history_cannot_be_backdated(self):
        p = fixture()
        for row in p['datasets']['SOFR']['rows']:
            row['available_at'] = '2026-08-01T00:00:00Z'
        r = run(p)
        self.assertEqual(r['source_quality']['SOFR']['status'], 'INVALID_SOURCE')
        self.assertFalse(r['equity_reentry_review'])

    def test_before_retrieval_has_no_current_observations(self):
        r = run(as_of='2026-09-14T19:00:00Z')
        self.assertEqual(r['quality_status'], 'DEGRADED')
        self.assertEqual(r['source_quality']['M2SL']['status'], 'NOT_AVAILABLE_AS_OF')

    def test_zero_is_value_but_null_is_withdrawal(self):
        p = fixture(); p['datasets']['SOFR']['rows'][-1]['value'] = None
        self.assertEqual(run(p)['source_quality']['SOFR']['status'], 'WITHDRAWN')
        self.assertEqual(run()['source_quality']['RRPONTSYD']['status'], 'OK')

    def test_identical_refresh_is_not_new_confirmation(self):
        first = run()
        p = fixture()
        for dataset in p['datasets'].values():
            for row in dataset['rows']:
                row['retrieved_at'] = row['available_at'] = '2026-09-14T21:00:00Z'
        second = run(p, as_of='2026-09-14T21:00:00Z', prior=first)
        self.assertEqual(second['recovery_observation_count'], 1)
        self.assertFalse(second['new_recovery_observation'])
        self.assertFalse(second['equity_reentry_review'])

    def test_new_daily_confirmation_with_same_sloos_allows_review(self):
        first = run(); p = fixture()
        for sid in ('SOFR', 'IORB', 'BAMLH0A0HYM2', 'BREADTH_ABOVE_200D'):
            row = copy.deepcopy(p['datasets'][sid]['rows'][-1])
            row.update(observation_date='2026-09-14',
                       available_at='2026-09-15T20:00:00Z', retrieved_at='2026-09-15T20:00:00Z')
            p['datasets'][sid]['rows'].append(row)
        r = run(p, as_of='2026-09-15T20:00:00Z', prior=first)
        self.assertTrue(r['equity_reentry_review'])
        self.assertEqual(r['recovery_observation_count'], 2)

    def test_missing_m2_does_not_block_independent_recovery(self):
        p = fixture(); del p['datasets']['M2SL']
        r = run(p)
        self.assertEqual(r['recovery_observation_count'], 1)
        self.assertEqual(r['quality_status'], 'PARTIAL')

    def test_missing_funding_blocks_reentry_not_forced_sale(self):
        p = fixture(); del p['datasets']['SOFR']
        r = run(p)
        self.assertEqual(r['quality_status'], 'DEGRADED')
        self.assertFalse(r['equity_reentry_review'])
        self.assertFalse(r['cash_defense_review'])

    def test_severe_funding_survives_missing_slow_data(self):
        p = fixture(); slope(p, 'SOFR', 5., 5.)
        del p['datasets']['M2SL']; del p['datasets']['WLCFLPCL']
        self.assertTrue(run(p)['cash_defense_review'])

    def test_price_alone_not_cash_trigger(self):
        p = fixture(); slope(p, 'BREADTH_ABOVE_200D', 45, 20)
        r = run(p)
        self.assertFalse(r['cash_defense_review'])
        self.assertEqual(r['cash_defense_evidence'], ['MARKET_BREADTH_DAMAGE'])

    def test_flagged_reclassification_not_organic_credit(self):
        p = fixture(); p['datasets']['TOTCI']['rows'][-2]['structural_break'] = True
        r = run(p)
        self.assertIsNone(r['features']['ci_growth_13w_pct'])
        self.assertEqual(r['axes']['bank_credit'], 'UNKNOWN')

    def test_inflation_risk_blocks_duration_not_all_equity(self):
        p = fixture(); slope(p, 'DGS10', 3, 7)
        r = run(p)
        self.assertTrue(r['duration_blocked'])
        self.assertFalse(r['duration_extension_review'])
        self.assertEqual(r['recovery_observation_count'], 1)

    def test_disinflation_credit_contraction_duration_review(self):
        p = fixture(); slope(p, 'TOTCI', 2900, 2500); slope(p, 'DRSDCILM', -10, -10)
        r = run(p)
        self.assertTrue(r['duration_extension_review'])
        self.assertFalse(r['duration_blocked'])

    def test_missing_cpi_month_blocks_duration(self):
        p = fixture(); del p['datasets']['CPIAUCSL']['rows'][2]
        r = run(p)
        self.assertEqual(r['axes']['inflation_duration'], 'UNKNOWN')
        self.assertTrue(r['duration_blocked'])

    def test_stale_observation_not_refreshed_by_download(self):
        p = fixture()
        p['datasets']['SOFR']['rows'] = p['datasets']['SOFR']['rows'][:3]
        self.assertEqual(run(p)['source_quality']['SOFR']['status'], 'STALE')

    def test_source_unit_and_frequency_checked(self):
        for field, value in [('unit', 'USD_BILLIONS'), ('frequency', 'monthly')]:
            p = fixture(); p['datasets']['SOFR'][field] = value
            self.assertEqual(run(p)['source_quality']['SOFR']['status'], 'INVALID_SOURCE')

    def test_nonfinite_boolean_and_duplicate_conflict_rejected(self):
        for bad in (float('nan'), float('inf')):
            p = fixture(); p['datasets']['SOFR']['rows'][-1]['value'] = bad
            with self.assertRaises((ContractError, ValueError)):
                run(p)  # Audit may reject early; canonical serialization also rejects NaN.
        p = fixture(); p['datasets']['SOFR']['rows'][-1]['value'] = True
        self.assertEqual(run(p)['source_quality']['SOFR']['status'], 'INVALID_SOURCE')
        p = fixture(); row = copy.deepcopy(p['datasets']['SOFR']['rows'][-1]); row['value'] = 100
        p['datasets']['SOFR']['rows'].append(row)
        self.assertEqual(run(p)['source_quality']['SOFR']['status'], 'INVALID_SOURCE')

    def test_source_sha_required_and_config_validated(self):
        with self.assertRaises(ContractError):
            evaluate(fixture(), as_of=ASOF, source_commit='latest')
        with self.assertRaises(ContractError):
            run(config=ResearchConfig(funding_stress_bp=100))

    def test_prior_future_and_changed_config_blocked(self):
        r = run(); r['as_of'] = '2026-09-15T20:00:00Z'
        with self.assertRaises(ContractError): run(prior=r)
        r = run(); r['config_hash'] = 'bad'
        with self.assertRaises(ContractError): run(prior=r)

    def test_policy_discussion_never_becomes_actual_money(self):
        p = fixture(); p['policy_events'] = [dict(policy_id='synthetic_lcr',
            stage='OFFICIAL_DISCUSSION', available_at=ASOF, published_at=ASOF,
            raw_sha256='a'*64, source_uri='https://example.invalid/synthetic')]
        r = run(p)
        self.assertIsNone(r['axes']['policy'][0]['actual_liquidity_amount'])
        self.assertEqual(r['cash_defense_review'], run()['cash_defense_review'])

    def test_final_rule_requires_effective_date(self):
        p = fixture(); p['policy_events'] = [dict(policy_id='synthetic',
            stage='FINAL_RULE', available_at=ASOF, published_at=ASOF,
            raw_sha256='a'*64, source_uri='https://example.invalid/synthetic')]
        self.assertEqual(run(p)['axes']['policy'][0]['stage'], 'FINAL_EFFECTIVE_DATE_UNKNOWN')
        p['policy_events'][0]['effective_at'] = '2027-01-01T00:00:00Z'
        self.assertEqual(run(p)['axes']['policy'][0]['stage'], 'FINAL_NOT_EFFECTIVE')

    def test_alfred_vintage_cannot_enter_before_next_ny_day(self):
        p = fixture(); ds = p['datasets']['SOFR']
        ds['rows'] = [dict(series='SOFR', observation_date='2026-09-10', value=4,
            vintage_date='2026-09-11', realtime_end='9999-12-31',
            retrieved_at=ASOF, available_at='2026-09-12T04:00:00Z', evidence='alfred_date_archive')]
        a = select_series(ds, 'SOFR', stamp('2026-09-11T20:00:00Z'))
        b = select_series(ds, 'SOFR', stamp(ASOF))
        self.assertEqual(a['status'], 'NOT_AVAILABLE_AS_OF')
        self.assertEqual(b['status'], 'OK')
        ds['rows'][0]['available_at'] = '2026-09-11T20:00:00Z'
        with self.assertRaises(ContractError): select_series(ds, 'SOFR', stamp(ASOF))

    def test_alfred_expired_vintage_without_successor_not_reused(self):
        ds = fixture()['datasets']['SOFR']
        ds['rows'] = [dict(series='SOFR', observation_date='2026-09-10', value=4,
            vintage_date='2026-09-11', realtime_end='2026-09-12',
            retrieved_at=ASOF, available_at='2026-09-12T04:00:00Z', evidence='alfred_date_archive')]
        self.assertEqual(select_series(ds, 'SOFR', stamp(ASOF))['status'], 'WITHDRAWN')

    def test_known_funding_stress_survives_missing_primary(self):
        p = fixture(); slope(p, 'SOFR', 4.5, 4.5)
        slope(p, 'BAMLH0A0HYM2', 3, 7); del p['datasets']['WLCFLPCL']
        self.assertTrue(run(p)['cash_defense_review'])

    def test_high_primary_credit_level_cannot_look_stable(self):
        p = fixture(); slope(p, 'WLCFLPCL', 100000, 100000)
        self.assertEqual(run(p)['axes']['central_bank_funding'], 'STRESS')

    def test_new_source_commit_cannot_reuse_old_confirmation(self):
        r = run(); r['source_commit'] = 'e'*40
        with self.assertRaises(ContractError): run(prior=r)

    def test_regressed_observation_cannot_reuse_confirmed_reentry(self):
        prior = run(); prior['recovery_observation_count'] = 2
        prior['confirmation_sessions']['SOFR'] = '2026-09-14'
        r = run(prior=prior)
        self.assertFalse(r['equity_reentry_review'])
        self.assertEqual(r['recovery_observation_count'], 0)

    def test_known_high_yield_spread_without_history_is_stress(self):
        p = fixture(); ds = p['datasets']['BAMLH0A0HYM2']
        ds['rows'] = ds['rows'][-1:]; ds['rows'][0]['value'] = 7
        self.assertEqual(run(p)['axes']['market_nonbank'], 'STRESS')

    def test_known_yield_shock_with_missing_cpi_blocks_duration(self):
        p = fixture(); slope(p, 'DGS10', 3, 7); del p['datasets']['CPIAUCSL']
        self.assertEqual(run(p)['axes']['inflation_duration'], 'DURATION_RISK')

    def test_growth_history_gap_not_shorter_return(self):
        p = fixture(); ds = p['datasets']['TOTCI']
        ds['rows'] = [ds['rows'][0], ds['rows'][-1]]
        self.assertIsNone(run(p)['features']['ci_growth_13w_pct'])

    def test_fixture_label_and_limitations_preserved(self):
        r = run()
        self.assertEqual(r['input_kind'], 'SYNTHETIC_FIXTURE')
        self.assertFalse(r['historical_pit_certified'])
        self.assertTrue(r['coverage_limits'])

    def test_overlapping_alfred_intervals_fail(self):
        ds = fixture()['datasets']['SOFR']
        row = dict(series='SOFR', observation_date='2026-09-09', value=4,
            vintage_date='2026-09-10', realtime_end='2026-09-13',
            retrieved_at=ASOF, available_at='2026-09-11T04:00:00Z', evidence='alfred_date_archive')
        ds['rows'] = [row, dict(row, vintage_date='2026-09-11', realtime_end='9999-12-31',
                               available_at='2026-09-12T04:00:00Z')]
        with self.assertRaises(ContractError): select_series(ds, 'SOFR', stamp(ASOF))

    def test_negative_money_stock_and_invalid_breadth_rejected(self):
        for sid, value in [('WTREGEN', -1), ('BREADTH_ABOVE_200D', 101)]:
            p = fixture(); p['datasets'][sid]['rows'][-1]['value'] = value
            self.assertEqual(run(p)['source_quality'][sid]['status'], 'INVALID_SOURCE')

    def test_canonical_governor_and_weights_unchanged(self):
        canonical = {'state': 'CRISIS', 'cash_weight': .5, 'kill_switch': True}
        result = attach_to_canonical(canonical, run())
        self.assertEqual({k: result[k] for k in canonical}, canonical)
        self.assertNotIn('liquidity_driver_context', canonical)
        self.assertFalse(result['liquidity_driver_context']['orders_allowed'])
        with self.assertRaises(ContractError): attach_to_canonical(result, run())

    def test_all_outputs_research_only_and_deterministic(self):
        a, b = run(), run()
        self.assertEqual(a, b)
        for field in ('orders_allowed', 'target_mutation_allowed', 'eligible_for_selector',
                      'canonical_regime_mutation_allowed', 'thresholds_validated_oos'):
            self.assertIs(a[field], False)


if __name__ == '__main__':
    unittest.main()
