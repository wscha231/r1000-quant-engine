"""H2 manager-skill scoring from reviewed post-disclosure clone evidence."""
from __future__ import annotations

from dataclasses import asdict
from datetime import date
from math import isfinite
from typing import Iterable, Mapping

from tools.sec_13f_manager_contract import (
    COMPONENT_WEIGHTS, IntegrityError, Policy, digest, instant, month_tenure,
    number, quarter_end, required_text, verified,
)

def nav_metrics(points: Iterable[Mapping], expected_closes: Iterable[str],
                cutoff: str, *, provenance: Mapping) -> dict:
    """Metrics of a supplied NET clone NAV series, not a price backtest.

    Expected closes must come from a verified exchange calendar. Missing points
    block rather than being forward-filled. This does not certify provenance.
    """
    verified(provenance, 'costs_included', 'total_return_benchmark',
             'calendar_verified', 'nav_is_total_return_index')
    for key in ('source_evidence_id', 'cost_model_id', 'calendar_id', 'benchmark_id'):
        required_text(provenance, key)
    if provenance.get('series_kind') != 'POST_DISCLOSURE_CLONE_NET':
        raise IntegrityError('not_clone_net_nav')
    cut = instant(cutoff)
    expected = [instant(x) for x in expected_closes if instant(x) <= cut]
    if len(set(expected)) != len(expected) or expected != sorted(expected) or len(expected) < 2:
        raise IntegrityError('calendar_order_or_length_invalid')
    available = {}
    for p in points:
        close = instant(required_text(p, 'close_at'))
        known = instant(required_text(p, 'available_at'))
        if known < close:
            raise IntegrityError('nav_known_before_close')
        if close > cut or known > cut:
            continue
        if close in available:
            raise IntegrityError('duplicate_nav_point')
        if number(p.get('net_nav')) <= 0 or number(p.get('benchmark_nav')) <= 0:
            raise IntegrityError('positive_nav_required')
        available[close] = p
    if sorted(available) != expected:
        raise IntegrityError('nav_calendar_coverage_mismatch')
    values = [float(available[t]['net_nav']) for t in expected]
    benchmarks = [float(available[t]['benchmark_nav']) for t in expected]
    elapsed = (expected[-1] - expected[0]).total_seconds() / (365.25 * 86400)
    strategy_cagr = (values[-1] / values[0]) ** (1 / elapsed) - 1
    benchmark_cagr = (benchmarks[-1] / benchmarks[0]) ** (1 / elapsed) - 1
    peak = values[0]
    peak_at = expected[0]
    max_drawdown, longest_underwater_days = 0., 0
    underwater = False
    for t, value in zip(expected, values):
        if value >= peak:
            if underwater:
                longest_underwater_days = max(longest_underwater_days, (t - peak_at).days)
            peak, peak_at = value, t
            underwater = False
        else:
            underwater = True
            max_drawdown = min(max_drawdown, value / peak - 1)
            longest_underwater_days = max(longest_underwater_days, (t - peak_at).days)
    output = {
        'series_kind': 'POST_DISCLOSURE_CLONE_NET',
        'net_cagr': strategy_cagr, 'benchmark_cagr': benchmark_cagr,
        'cagr_difference_not_risk_adjusted_alpha': strategy_cagr - benchmark_cagr,
        'max_drawdown': max_drawdown,
        'longest_underwater_calendar_days': longest_underwater_days,
        'session_count': len(values), 'span_years': elapsed,
        'evidence_hash': digest({'points': list(available.values()), 'provenance': dict(provenance)}),
        'production_promotion_allowed': False,
    }
    if not all(isfinite(output[k]) for k in ('net_cagr', 'benchmark_cagr', 'max_drawdown')):
        raise IntegrityError('metric_overflow')
    return output


def score_managers(records: Iterable[Mapping], *, cutoff: str,
                   expected_manager_ids: Iterable[str], policy: Policy = Policy()) -> dict:
    """Cross-sectional scores of reviewed component values; no fabricated alpha.

    Each component must be oriented HIGHER_IS_BETTER by a separately reviewed
    estimator. Correlation- and overlap-adjusted effective event counts are
    supplied by that estimator; raw row counts are never used as substitutes.
    """
    expected = list(expected_manager_ids)
    if not expected or len(set(expected)) != len(expected) or any(not isinstance(x, str) or not x for x in expected):
        raise IntegrityError('expected_manager_population_invalid')
    cut = instant(cutoff)
    by_id = {}
    for original in records:
        row = dict(original)
        manager = required_text(row, 'economic_manager_id')
        if manager not in expected or manager in by_id:
            raise IntegrityError('unexpected_or_duplicate_manager_evidence')
        by_id[manager] = row
    blocked, ready = {}, {}
    for manager in sorted(expected):
        r = by_id.get(manager)
        if r is None:
            blocked[manager] = 'MISSING_CLONE_EVIDENCE'
            continue
        try:
            verified(r, 'pit_validated', 'costs_validated', 'outcome_overlap_adjusted',
                     'population_membership_pit_validated')
            if r.get('series_kind') != 'POST_DISCLOSURE_CLONE_NET':
                raise IntegrityError('legacy_candidate_alpha_is_not_clone_alpha')
            if instant(required_text(r, 'available_at')) > cut:
                raise IntegrityError('future_manager_evidence')
            required_text(r, 'benchmark_id')
            required_text(r, 'component_method_id')
            required_text(r, 'sample_evidence_id')
            period = required_text(r, 'review_period')
            quarter_end(period)
            if date.fromisoformat(period) >= cut.date():
                raise IntegrityError('review_period_not_matured')
            quarters = r.get('matured_quarters')
            events = r.get('effective_independent_events')
            if any(isinstance(x, bool) or not isinstance(x, int) for x in (quarters, events)):
                raise IntegrityError('sample_counts_invalid')
            if quarters < policy.minimum_matured_quarters or events < policy.minimum_independent_events:
                raise IntegrityError('INSUFFICIENT_EFFECTIVE_SAMPLE')
            for months in (12, 24):
                number(r.get(f'net_excess_{months}m'), nonnegative=False)
                window = r.get('relative_windows', {}).get(str(months), {})
                begin = instant(required_text(window, 'window_start_at'))
                end = instant(required_text(window, 'window_end_at'))
                known = instant(required_text(window, 'available_at'))
                required_text(window, 'evidence_id')
                if not begin < end <= known <= cut or month_tenure(begin.date().isoformat(), end.date().isoformat()) < months:
                    raise IntegrityError('relative_return_window_incomplete_or_future')
                if window.get('basis') != 'NET_CLONE_MINUS_BENCHMARK_TOTAL_RETURN':
                    raise IntegrityError('relative_return_basis_invalid')
            components = r.get('components')
            if not isinstance(components, dict) or set(components) != set(COMPONENT_WEIGHTS):
                raise IntegrityError('all_five_components_required')
            for name, component in components.items():
                number(component.get('value'), nonnegative=False)
                if component.get('orientation') != 'HIGHER_IS_BETTER':
                    raise IntegrityError('component_orientation_invalid')
                required_text(component, 'evidence_id')
                start = instant(required_text(component, 'window_start_at'))
                end = instant(required_text(component, 'window_end_at'))
                known = instant(required_text(component, 'available_at'))
                if not start < end <= known <= cut:
                    raise IntegrityError('component_window_or_availability_invalid')
                if name == 'clone_excess_36m' and month_tenure(start.date().isoformat(), end.date().isoformat()) < 36:
                    raise IntegrityError('36m_component_history_incomplete')
            ready[manager] = r
        except (IntegrityError, TypeError, KeyError) as exc:
            blocked[manager] = str(exc)
    comparison_contracts = {(r['benchmark_id'], r['component_method_id'], r['review_period']) for r in ready.values()}
    if len(comparison_contracts) > 1:
        raise IntegrityError('incomparable_manager_scorecards')
    ids = sorted(ready)
    scores = []
    for manager in ids:
        raw = 0.
        percentiles = {}
        for name, weight in COMPONENT_WEIGHTS.items():
            value = float(ready[manager]['components'][name]['value'])
            others = [float(ready[x]['components'][name]['value']) for x in ids if x != manager]
            percentile = 50. if not others else 100. * (sum(x < value for x in others) + .5 * sum(x == value for x in others)) / len(others)
            percentiles[name] = percentile
            raw += weight * percentile
        count = ready[manager]['effective_independent_events']
        shrinkage = count / (count + policy.shrinkage_prior_events)
        score = 50. + shrinkage * (raw - 50.)
        scores.append({
            'economic_manager_id': manager, 'score': score,
            'unshrunk_score': raw, 'shrinkage': shrinkage,
            'component_percentiles': percentiles, 'review_period': ready[manager]['review_period'],
            'net_excess_12m': float(ready[manager]['net_excess_12m']),
            'net_excess_24m': float(ready[manager]['net_excess_24m']),
            'cluster_id': required_text(ready[manager], 'cluster_id'),
            'research_only': True,
        })
    scores.sort(key=lambda x: (-x['score'], x['economic_manager_id']))
    # Competition ranks: ties receive equal ranks; alphabetical tie order is not skill.
    prior_score, rank = None, 0
    for index, row in enumerate(scores, 1):
        if prior_score is None or row['score'] != prior_score:
            rank = index
        row['rank'] = rank
        prior_score = row['score']
    known_ineligible = {mid: reason for mid, reason in blocked.items()
                        if reason in {'INSUFFICIENT_EFFECTIVE_SAMPLE', '36m_component_history_incomplete'}}
    population_complete = len(by_id) == len(expected) and len(blocked) == len(known_ineligible)
    return {
        'status': 'READY_FOR_RESEARCH_REVIEW' if population_complete and scores else 'INCOMPLETE_MANAGER_EVIDENCE',
        'population_complete': population_complete,
        'known_ineligible': known_ineligible,
        'rank_population_size': len(scores), 'expected_population_size': len(expected),
        'ranking': scores, 'blocked': blocked, 'cutoff': cutoff,
        'input_hash': digest({'records': [by_id[x] for x in sorted(by_id)], 'expected': sorted(expected)}),
        'config_hash': digest({'policy': asdict(policy), 'components': COMPONENT_WEIGHTS}),
        'production_promotion_allowed': False,
    }




def source_influence(scores: Iterable[Mapping], policy: Policy = Policy()) -> dict:
    """Conservative influence caps. Unallocated residual stays unallocated.

    These are information-source influence weights, NEVER stock/broker weights.
    Correlation cluster labels must be supplied by a reviewed exposure model.
    """
    rows = list(scores)
    by_id, total = {}, 0.
    for r in rows:
        mid = required_text(r, 'economic_manager_id')
        if mid in by_id:
            raise IntegrityError('duplicate_source_manager')
        cluster = required_text(r, 'cluster_id')
        raw = float(number(r.get('score')))
        if raw > 100:
            raise IntegrityError('source_score_out_of_range')
        by_id[mid] = (raw, cluster)
        total += raw
    weights = {mid: min(raw / total, policy.source_manager_cap) if total else 0.
               for mid, (raw, _) in by_id.items()}
    for cluster in sorted({x[1] for x in by_id.values()}):
        members = [mid for mid, (_, c) in by_id.items() if c == cluster]
        weight = sum(weights[mid] for mid in members)
        if weight > policy.source_cluster_cap:
            for mid in members:
                weights[mid] *= policy.source_cluster_cap / weight
    return {'weights': weights, 'unallocated_influence': max(0., 1. - sum(weights.values())),
            'weights_are_broker_allocations': False, 'research_only': True}
