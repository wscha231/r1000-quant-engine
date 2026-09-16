"""Synthetic H2 manager-skill fixtures only; no real performance."""
from tools.sec_13f_manager_policy import digest

CUT = '2026-12-05T00:00:00Z'

def metric_records(count=20):
    from tools.sec_13f_manager_policy import COMPONENT_WEIGHTS
    output = []
    for i in range(1, count + 1):
        mid = f'SYNTHETIC_M{i:02}'
        value = count - i + 1
        output.append({
            'economic_manager_id': mid, 'series_kind': 'POST_DISCLOSURE_CLONE_NET',
            'pit_validated': True, 'costs_validated': True,
            'outcome_overlap_adjusted': True, 'population_membership_pit_validated': True,
            'available_at': '2026-11-18T00:00:00Z',
            'benchmark_id': 'SYNTHETIC_SP500_TR', 'component_method_id': 'SYNTHETIC_TEST_METHOD',
            'sample_evidence_id': 'SYNTHETIC_EFFECTIVE_SAMPLE',
            'review_period': '2026-09-30', 'matured_quarters': 12,
            'effective_independent_events': 80,
            'net_excess_12m': -.04 if i > 10 else .04,
            'net_excess_24m': -.03 if i > 10 else .03,
            'relative_windows': {str(months): {
                'window_start_at': f'{2026 - months // 12}-09-30T20:00:00Z',
                'window_end_at': '2026-09-30T20:00:00Z', 'available_at': '2026-11-18T00:00:00Z',
                'evidence_id': 'SYNTHETIC_MATURED_RELATIVE_WINDOW',
                'basis': 'NET_CLONE_MINUS_BENCHMARK_TOTAL_RETURN'} for months in (12, 24)},
            'cluster_id': f'SYNTHETIC_CLUSTER_{i % 4}',
            'components': {name: {
                'value': value, 'orientation': 'HIGHER_IS_BETTER',
                'evidence_id': f'SYNTHETIC_{mid}_{name}',
                'window_start_at': '2023-09-29T20:00:00Z',
                'window_end_at': '2026-09-30T20:00:00Z',
                'available_at': '2026-11-18T00:00:00Z'} for name in COMPONENT_WEIGHTS},
        })
    return output


def active_members():
    return [{'economic_manager_id': f'SYNTHETIC_M{i:02}',
             'entered_at_date': '2025-06-05', 'membership_known_at': '2025-06-05T00:00:00Z',
             'data_valid': True, 'critical_event': False} for i in range(11, 21)]


def histories():
    from dataclasses import asdict
    from tools.sec_13f_manager_policy import Policy, COMPONENT_WEIGHTS
    config_hash = digest({'policy': asdict(Policy()), 'components': COMPONENT_WEIGHTS})
    return [{'economic_manager_id': f'SYNTHETIC_M{i:02}', 'review_period': '2026-06-30',
             'available_at': '2026-08-18T00:00:00Z', 'decision_cutoff': '2026-08-18T01:00:00Z',
             'pit_validated': True, 'rank': i, 'config_hash': config_hash,
             'evidence_id': 'SYNTHETIC_SAVED_QUARTER_REVIEW'} for i in range(11, 21)]


def ledger_decision(i=1, *, status='APPLIED', decided='2026-07-01T00:00:00Z'):
    return {'decision_id': f'synthetic:decision:{i}', 'decided_at': decided,
            'status_effective_at': decided,
            'action': 'REPLACE', 'status': status,
            'incoming_manager': f'SYNTHETIC_RESERVED_IN_{i}',
            'outgoing_manager': f'SYNTHETIC_RESERVED_OUT_{i}'}
