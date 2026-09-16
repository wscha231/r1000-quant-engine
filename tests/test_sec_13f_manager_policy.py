import unittest
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from copy import deepcopy
from datetime import datetime, timezone
from tools.sec_13f_manager_policy import IntegrityError
from tools.sec_13f_manager_policy import (
    Policy, score_managers, propose_cohort, source_influence, nav_metrics, month_tenure,
)
from sec_13f_manager_policy_fixture import CUT, metric_records, active_members, histories, ledger_decision


def score(records=None, cutoff=CUT):
    records = metric_records() if records is None else records
    return score_managers(records, cutoff=cutoff,
                          expected_manager_ids=[f'SYNTHETIC_M{i:02}' for i in range(1, 21)])


def propose(s=None, active=None, history=None, ledger=None, **overrides):
    args = {'review_kind': 'SEMIANNUAL', 'history_complete': True, 'decision_ledger_complete': True}
    args.update(overrides)
    return propose_cohort(score() if s is None else s,
                          active_members() if active is None else active,
                          histories() if history is None else history,
                          [] if ledger is None else ledger, **args)


class ManagerPolicyTests(unittest.TestCase):
    def test_full_population_ranked_before_top_ten(self):
        s = score()
        self.assertEqual(len(s['ranking']), 20)
        self.assertEqual(s['ranking'][-1]['rank'], 20)

    def test_missing_manager_is_missing_not_zero_return(self):
        s = score(metric_records()[:-1])
        self.assertFalse(s['population_complete'])
        self.assertEqual(s['blocked']['SYNTHETIC_M20'], 'MISSING_CLONE_EVIDENCE')

    def test_missing_manager_population_blocks_changes(self):
        result = propose(score(metric_records()[:-1]))
        self.assertEqual(result['status'], 'BLOCKED_INCOMPLETE_MANAGER_POPULATION')
        self.assertEqual(result['proposals'], [])

    def test_legacy_candidate_alpha_cannot_be_substituted(self):
        rows = metric_records(); rows[0]['series_kind'] = 'CANDIDATE_REPLAY_ALPHA'
        s = score(rows)
        self.assertIn('legacy_candidate_alpha', s['blocked']['SYNTHETIC_M01'])

    def test_effective_samples_not_raw_repeated_rows(self):
        rows = metric_records(); rows[0]['effective_independent_events'] = 2
        s = score(rows)
        self.assertEqual(s['blocked']['SYNTHETIC_M01'], 'INSUFFICIENT_EFFECTIVE_SAMPLE')

    def test_aum_or_seed_priority_cannot_change_score(self):
        rows = metric_records()
        for r in rows: r.update(aum_13f_usd=1e15, seed_priority=1)
        a, b = score(), score(rows)
        self.assertEqual([(r['economic_manager_id'], r['score']) for r in a['ranking']],
                         [(r['economic_manager_id'], r['score']) for r in b['ranking']])

    def test_future_component_excluded(self):
        rows = metric_records(); rows[0]['components']['clone_excess_36m']['available_at'] = '2027-01-01T00:00:00Z'
        self.assertIn('SYNTHETIC_M01', score(rows)['blocked'])

    def test_short_history_cannot_be_labeled_36m(self):
        rows = metric_records(); rows[0]['components']['clone_excess_36m']['window_start_at'] = '2026-01-01T00:00:00Z'
        self.assertEqual(score(rows)['blocked']['SYNTHETIC_M01'], '36m_component_history_incomplete')

    def test_different_benchmarks_not_ranked_together(self):
        rows = metric_records(); rows[0]['benchmark_id'] = 'OTHER_BENCHMARK'
        with self.assertRaisesRegex(IntegrityError, 'incomparable'): score(rows)

    def test_duplicate_manager_evidence_blocked(self):
        rows = metric_records(); rows.append(deepcopy(rows[0]))
        with self.assertRaises(IntegrityError): score(rows)

    def test_tied_performance_neutral_score_and_equal_rank(self):
        rows = metric_records()
        for r in rows:
            for component in r['components'].values(): component['value'] = 1
        s = score(rows)
        self.assertTrue(all(r['score'] == 50 and r['rank'] == 1 for r in s['ranking']))

    def test_monotone_transform_preserves_component_ranks(self):
        rows = metric_records()
        for r in rows:
            for c in r['components'].values(): c['value'] = c['value'] * 100 + 35
        self.assertEqual(score(rows)['ranking'], score()['ranking'])

    def test_monthly_does_not_replace(self):
        r = propose(review_kind='MONTHLY')
        self.assertEqual(r['status'], 'MONITOR_ONLY')
        self.assertEqual(r['proposals'], [])

    def test_quarterly_does_not_replace(self):
        self.assertEqual(propose(review_kind='QUARTERLY')['proposals'], [])

    def test_semiannual_no_more_than_two_normal_replacements(self):
        r = propose()
        self.assertEqual(sum(p['action'] == 'REPLACE' for p in r['proposals']), 2)
        self.assertEqual(len({p['incoming_manager'] for p in r['proposals']}), 2)
        self.assertFalse(r['active_roster_changed'])
        self.assertFalse(r['automatic_stock_sale_allowed'])

    def test_semiannual_outside_window_no_changes(self):
        self.assertEqual(propose(score(cutoff='2026-11-25T00:00:00Z'))['status'], 'OUTSIDE_REGULAR_REVIEW_WINDOW')

    def test_replacement_budget_cumulative_across_reruns(self):
        r = propose(ledger=[ledger_decision(1), ledger_decision(2)])
        self.assertEqual(r['proposals'], [])
        self.assertEqual(r['replacements_already_used'], 2)

    def test_duplicate_ledger_record_not_counted_twice(self):
        d = ledger_decision()
        r = propose(ledger=[d, deepcopy(d)])
        self.assertEqual(r['replacements_already_used'], 1)
        self.assertEqual(sum(p['action'] == 'REPLACE' for p in r['proposals']), 1)

    def test_pending_proposals_reserve_capacity(self):
        r = propose(ledger=[ledger_decision(1, status='PROPOSED'), ledger_decision(2, status='PROPOSED')])
        self.assertEqual(r['proposals'], [])
        self.assertEqual(r['pending_replacements_reserved'], 2)

    def test_previous_halfyear_does_not_use_current_budget(self):
        r = propose(ledger=[ledger_decision(1, decided='2026-06-05T00:00:00Z')])
        self.assertEqual(r['replacements_already_used'], 0)
        self.assertEqual(len(r['proposals']), 2)

    def test_conflicting_ledger_state_requires_reconciliation(self):
        a, b = ledger_decision(), ledger_decision(status='APPROVED')
        with self.assertRaisesRegex(IntegrityError, 'conflicting_decision'): propose(ledger=[a, b])

    def test_two_copies_of_same_quarter_not_two_bad_quarters(self):
        hs = histories()
        for h in hs: h['review_period'] = '2026-03-31'
        r = propose(history=hs + deepcopy(hs))
        self.assertEqual(r['proposals'], [])

    def test_future_historical_rank_not_used(self):
        hs = histories()
        for h in hs: h['available_at'] = '2027-01-01T00:00:00Z'
        self.assertEqual(propose(history=hs)['proposals'], [])

    def test_prior_rank_reconstructed_after_its_cutoff_blocked(self):
        hs = histories(); hs[0]['available_at'] = '2026-11-01T00:00:00Z'
        with self.assertRaisesRegex(IntegrityError, 'historical_review_not_available'): propose(history=hs)

    def test_short_tenure_prevents_performance_churn(self):
        a = active_members()
        for m in a: m['entered_at_date'] = '2026-06-05'
        self.assertEqual(propose(active=a)['proposals'], [])

    def test_twelve_month_negative_but_twentyfour_positive_no_exit(self):
        rows = metric_records()
        for r in rows: r['net_excess_24m'] = .03
        self.assertEqual(propose(score(rows))['proposals'], [])

    def test_critical_event_quarantines_source_not_stock(self):
        a = active_members(); a[0]['critical_event'] = True
        r = propose(active=a, review_kind='MONTHLY')
        self.assertEqual(r['source_reviews'][0]['action'], 'QUARANTINE_SOURCE_REVIEW')
        self.assertFalse(r['source_reviews'][0]['automatic_stock_sale_allowed'])

    def test_missing_ledger_blocks_even_good_candidates(self):
        self.assertEqual(propose(decision_ledger_complete=False)['status'], 'BLOCKED_MISSING_HISTORY_OR_LEDGER')

    def test_duplicate_active_economic_manager_blocked(self):
        a = active_members(); a[0] = a[1]
        with self.assertRaises(IntegrityError): propose(active=a)

    def test_initial_shadow_does_not_fill_unqualified_seats(self):
        rows = metric_records()
        for r in rows:
            for c in r['components'].values(): c['value'] = 1
        self.assertEqual(propose(score(rows), active=[], review_kind='INITIAL_SHADOW')['proposals'], [])

    def test_initial_shadow_only_qualified_sources(self):
        r = propose(active=[], review_kind='INITIAL_SHADOW')
        self.assertGreater(len(r['proposals']), 0)
        self.assertLess(len(r['proposals']), 10)
        self.assertTrue(all(p['action'] == 'INCLUDE' for p in r['proposals']))

    def test_identical_rerun_is_deterministic(self):
        self.assertEqual(propose(), propose())

    def test_score_config_mismatch_cannot_select(self):
        s = score(); s['config_hash'] = 'bad'
        with self.assertRaises(IntegrityError): propose(s)

    def test_invalid_manual_rank_rejected(self):
        s = score(); s['ranking'][0]['rank'] = 7
        with self.assertRaises(IntegrityError): propose(s)

    def test_source_caps_not_renormalized_over_limit(self):
        s = score()['ranking']
        for r in s: r['cluster_id'] = 'ONE_CLUSTER'
        result = source_influence(s)
        self.assertLessEqual(sum(result['weights'].values()), .35 + 1e-12)
        self.assertLessEqual(max(result['weights'].values()), .15)
        self.assertGreaterEqual(result['unallocated_influence'], .65 - 1e-12)
        self.assertFalse(result['weights_are_broker_allocations'])

    def test_source_influence_zero_scores_remain_unallocated(self):
        s = score()['ranking']
        for r in s: r['score'] = 0
        self.assertEqual(source_influence(s)['unallocated_influence'], 1)

    def test_missing_cluster_does_not_assume_independence(self):
        s = score()['ranking']; del s[0]['cluster_id']
        with self.assertRaises(IntegrityError): source_influence(s)

    def test_policy_invalid_thresholds_rejected(self):
        with self.assertRaises(IntegrityError): Policy(replacements_per_halfyear=0)

    def test_tenure_uses_completed_months(self):
        self.assertEqual(month_tenure('2025-12-06', '2026-12-05'), 11)
        self.assertEqual(month_tenure('2025-12-05', '2026-12-05'), 12)

    def test_known_sparse_manager_is_ineligible_not_missing_population(self):
        rows = metric_records(); rows[0]['effective_independent_events'] = 2
        s = score(rows)
        self.assertTrue(s['population_complete'])
        self.assertEqual(len(s['ranking']), 19)
        self.assertIn('SYNTHETIC_M01', s['known_ineligible'])

    def test_missing_relative_window_not_known_short_history(self):
        rows = metric_records(); del rows[0]['relative_windows']['24']
        self.assertFalse(score(rows)['population_complete'])

    def test_twentyfour_month_window_must_be_full_length(self):
        rows = metric_records()
        rows[0]['relative_windows']['24']['window_start_at'] = '2025-09-30T20:00:00Z'
        self.assertFalse(score(rows)['population_complete'])

    def test_36m_leap_year_window_cannot_pass_one_day_short(self):
        rows = metric_records()
        c = rows[0]['components']['clone_excess_36m']
        c['window_start_at'] = '2023-10-01T20:00:00Z'
        self.assertEqual(score(rows)['blocked']['SYNTHETIC_M01'], '36m_component_history_incomplete')

    def test_same_evidence_next_day_same_proposal_ids(self):
        a, b = propose(), propose(score(cutoff='2026-12-06T00:00:00Z'))
        self.assertEqual([x['proposal_id'] for x in a['proposals']], [x['proposal_id'] for x in b['proposals']])

    def test_old_proposal_applied_this_half_counts_current_budget(self):
        d = ledger_decision(decided='2026-06-05T00:00:00Z')
        d['status_effective_at'] = '2026-12-01T00:00:00Z'
        self.assertEqual(propose(ledger=[d])['replacements_already_used'], 1)

    def test_carryover_pending_approval_reserves_current_budget(self):
        d = ledger_decision(status='APPROVED', decided='2026-06-05T00:00:00Z')
        r = propose(ledger=[d])
        self.assertEqual(r['pending_replacements_reserved'], 1)
        self.assertEqual(len(r['proposals']), 1)

    def test_future_ledger_status_is_not_backdated(self):
        d = ledger_decision(); d['status_effective_at'] = '2027-01-01T00:00:00Z'
        with self.assertRaisesRegex(IntegrityError, 'ledger_status'): propose(ledger=[d])

    def test_missing_ledger_status_clock_blocks(self):
        d = ledger_decision(); del d['status_effective_at']
        with self.assertRaises(IntegrityError): propose(ledger=[d])


class NetNavTests(unittest.TestCase):
    def setUp(self):
        self.closes = ['2026-01-02T21:00:00Z', '2026-01-05T21:00:00Z', '2026-01-06T21:00:00Z']
        self.points = [{'close_at': t, 'available_at': t, 'net_nav': n, 'benchmark_nav': 100}
                       for t, n in zip(self.closes, (100, 80, 100))]
        self.provenance = {'series_kind': 'POST_DISCLOSURE_CLONE_NET', 'costs_included': True,
                           'total_return_benchmark': True, 'calendar_verified': True,
                           'nav_is_total_return_index': True, 'source_evidence_id': 'SYNTHETIC',
                           'cost_model_id': 'SYNTHETIC', 'calendar_id': 'SYNTHETIC', 'benchmark_id': 'SYNTHETIC'}

    def metric(self, points=None, closes=None):
        return nav_metrics(self.points if points is None else points,
                           self.closes if closes is None else closes, CUT, provenance=self.provenance)

    def test_drawdown_uses_initial_high_watermark(self):
        m = self.metric()
        self.assertAlmostEqual(m['max_drawdown'], -.20)
        self.assertEqual(m['longest_underwater_calendar_days'], 4)

    def test_all_rising_path_zero_underwater_time(self):
        for p, n in zip(self.points, (100, 101, 102)): p['net_nav'] = n
        self.assertEqual(self.metric()['longest_underwater_calendar_days'], 0)

    def test_missing_session_not_forward_filled(self):
        with self.assertRaises(IntegrityError): self.metric(points=self.points[:-1])

    def test_net_cost_provenance_required(self):
        self.provenance['costs_included'] = False
        with self.assertRaises(IntegrityError): self.metric()

    def test_duplicate_nav_timestamp_rejected(self):
        with self.assertRaises(IntegrityError): self.metric(points=self.points + [self.points[0]])

    def test_future_available_point_is_not_a_known_label(self):
        self.points[-1]['available_at'] = '2027-01-01T00:00:00Z'
        with self.assertRaises(IntegrityError): self.metric()

    def test_zero_nav_blocks_instead_of_nan_cagr(self):
        self.points[-1]['net_nav'] = 0
        with self.assertRaises(IntegrityError): self.metric()

    def test_input_not_mutated(self):
        original = deepcopy(self.points)
        self.metric()
        self.assertEqual(original, self.points)


if __name__ == '__main__': unittest.main()
