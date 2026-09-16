"""H2 buffered manager cohort proposal policy; proposals only, never trades."""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from typing import Iterable, Mapping

from tools.sec_13f_manager_contract import (
    COMPONENT_WEIGHTS, IntegrityError, Policy, digest, instant, month_tenure,
    number, prior_quarter, quarter_end, required_text, verified,
)
from tools.sec_13f_manager_scoring import nav_metrics, score_managers, source_influence

def _halfyear(dt: datetime) -> str:
    return f'{dt.year}-H{1 if dt.month <= 6 else 2}'


def propose_cohort(scored: Mapping, active_members: Iterable[Mapping],
                   quarterly_history: Iterable[Mapping], decisions: Iterable[Mapping],
                   *, review_kind: str, history_complete: bool,
                   decision_ledger_complete: bool, policy: Policy = Policy()) -> dict:
    """Proposals only; maximum replacements is cumulative across a halfyear.

    Missing history/ledger blocks regular changes, not source-integrity alerts.
    Approval and mutation of the active roster remain a different subsystem.
    Decisions are a reconciled one-state-per-ID view. status_effective_at is
    the current state's effective time, not the proposal creation time.
    """
    if review_kind not in {'MONTHLY', 'QUARTERLY', 'SEMIANNUAL', 'INITIAL_SHADOW'}:
        raise IntegrityError('review_kind_invalid')
    cutoff = required_text(scored, 'cutoff')
    cut = instant(cutoff)
    active = {}
    quarantines = []
    for original in active_members:
        m = dict(original)
        mid = required_text(m, 'economic_manager_id')
        if mid in active:
            raise IntegrityError('duplicate_active_economic_manager')
        month_tenure(required_text(m, 'entered_at_date'), cut.date().isoformat())
        if instant(required_text(m, 'membership_known_at')) > cut:
            raise IntegrityError('future_active_membership')
        active[mid] = m
        if m.get('critical_event') is True or m.get('data_valid') is False:
            quarantines.append({'economic_manager_id': mid, 'action': 'QUARANTINE_SOURCE_REVIEW',
                                'automatic_stock_sale_allowed': False})
    if len(active) > policy.target_seats:
        raise IntegrityError('active_cohort_exceeds_seat_limit')
    base = {
        'review_kind': review_kind, 'cutoff': cutoff,
        'proposals': [], 'source_reviews': quarantines,
        'active_roster_changed': False, 'automatic_stock_sale_allowed': False,
        'production_promotion_allowed': False, 'research_only': True,
        'config_hash': digest(asdict(policy)),
    }
    if review_kind in {'MONTHLY', 'QUARTERLY'}:
        return dict(base, status='MONITOR_ONLY')
    if review_kind == 'SEMIANNUAL' and cut.month not in (6, 12):
        return dict(base, status='OUTSIDE_REGULAR_REVIEW_WINDOW')
    if not scored.get('population_complete'):
        return dict(base, status='BLOCKED_INCOMPLETE_MANAGER_POPULATION')
    if history_complete is not True or decision_ledger_complete is not True:
        return dict(base, status='BLOCKED_MISSING_HISTORY_OR_LEDGER')
    if scored.get('config_hash') != digest({'policy': asdict(policy), 'components': COMPONENT_WEIGHTS}):
        raise IntegrityError('score_policy_config_mismatch')
    ranking = scored.get('ranking', [])
    if len(ranking) + len(scored.get('known_ineligible', {})) != scored.get('expected_population_size') or len(ranking) != scored.get('rank_population_size'):
        raise IntegrityError('rank_population_size_mismatch')
    previous_score, expected_rank = None, 0
    periods = set()
    for ordinal, row in enumerate(ranking, 1):
        score = float(number(row.get('score')))
        if score > 100 or (previous_score is not None and score > previous_score):
            raise IntegrityError('ranking_not_sorted_or_score_invalid')
        if previous_score is None or score != previous_score:
            expected_rank = ordinal
        if row.get('rank') != expected_rank:
            raise IntegrityError('rank_inconsistent_with_scores')
        previous_score = score
        period = required_text(row, 'review_period')
        if quarter_end(period) >= cut.date():
            raise IntegrityError('future_rank_review_period')
        periods.add(period)
        number(row.get('net_excess_12m'), nonnegative=False)
        number(row.get('net_excess_24m'), nonnegative=False)
    if len(periods) != 1:
        raise IntegrityError('ranking_mixed_review_periods')
    indexed = {r['economic_manager_id']: r for r in ranking}
    if len(indexed) != len(ranking):
        raise IntegrityError('duplicate_ranked_manager')
    if review_kind == 'INITIAL_SHADOW' and active:
        raise IntegrityError('initial_shadow_requires_empty_active_cohort')
    histories = {}
    for h in quarterly_history:
        mid = required_text(h, 'economic_manager_id')
        period = required_text(h, 'review_period')
        quarter_end(period)
        known = instant(required_text(h, 'available_at'))
        if known > cut:
            continue
        required_text(h, 'evidence_id')
        verified(h, 'pit_validated')
        if h.get('config_hash') != scored['config_hash']:
            raise IntegrityError('historical_review_config_mismatch')
        historical_cutoff = instant(required_text(h, 'decision_cutoff'))
        if known > historical_cutoff or historical_cutoff >= cut or quarter_end(period) >= historical_cutoff.date():
            raise IntegrityError('historical_review_not_available_at_its_cutoff')
        rank = h.get('rank')
        if isinstance(rank, bool) or not isinstance(rank, int) or rank <= 0:
            raise IntegrityError('historical_rank_invalid')
        key = mid, period
        if key in histories and digest(histories[key]) != digest(dict(h)):
            raise IntegrityError('conflicting_quarterly_review')
        histories[key] = dict(h)
    used_replacements = 0
    pending_replacements = 0
    reserved_incoming, reserved_outgoing, reserved_includes = set(), set(), set()
    ledger = {}
    for original in decisions:
        d = dict(original)
        event_id = required_text(d, 'decision_id')
        if event_id in ledger:
            if digest(ledger[event_id]) != digest(d):
                raise IntegrityError('conflicting_decision_ledger_entry')
            continue
        when = instant(required_text(d, 'decided_at'))
        if when > cut:
            continue
        effective = instant(required_text(d, 'status_effective_at'))
        if effective < when or effective > cut:
            raise IntegrityError('ledger_status_not_available_at_cutoff')
        if d.get('status') not in {'APPROVED', 'APPLIED', 'REJECTED', 'PROPOSED'}:
            raise IntegrityError('decision_status_invalid')
        if d.get('action') not in {'INCLUDE', 'REPLACE'}:
            raise IntegrityError('decision_action_invalid')
        incoming = required_text(d, 'incoming_manager')
        outgoing = d.get('outgoing_manager')
        if d['action'] == 'REPLACE' and (not isinstance(outgoing, str) or not outgoing or outgoing == incoming):
            raise IntegrityError('replacement_ledger_pair_invalid')
        ledger[event_id] = d
        if d['status'] in {'PROPOSED', 'APPROVED'}:
            # Pending reviews reserve sources/seats until explicitly resolved.
            if incoming in reserved_incoming or (outgoing and outgoing in reserved_outgoing):
                raise IntegrityError('conflicting_pending_manager_changes')
            reserved_incoming.add(incoming)
            if outgoing:
                reserved_outgoing.add(outgoing)
            if d['action'] == 'INCLUDE' and incoming not in active:
                reserved_includes.add(incoming)
        if d['action'] == 'REPLACE':
            if d['status'] == 'PROPOSED' or (d['status'] == 'APPROVED' and _halfyear(effective) != _halfyear(cut)):
                # Carry-over unresolved proposals/approvals reserve this half's
                # budget too; they must not become extra later applications.
                pending_replacements += 1
            if d['status'] in {'APPROVED', 'APPLIED'} and _halfyear(effective) == _halfyear(cut):
                used_replacements += 1
    remaining = max(0, policy.replacements_per_halfyear - used_replacements - pending_replacements)
    entrants = [r for r in ranking if r['economic_manager_id'] not in active and r['economic_manager_id'] not in reserved_incoming and r['rank'] <= policy.entry_rank and r['score'] >= policy.entry_score]
    proposals = []
    available_seats = max(0, policy.target_seats - len(active) - len(reserved_includes))
    for entrant in entrants[:available_seats]:
        proposals.append({'action': 'INCLUDE', 'incoming_manager': entrant['economic_manager_id'],
                          'outgoing_manager': None, 'reason': 'QUALIFIED_VACANT_SEAT'})
    consumed = {p['incoming_manager'] for p in proposals}
    exits = []
    for mid, member in active.items():
        row = indexed.get(mid)
        if mid in reserved_outgoing or row is None or member.get('critical_event') is True or member.get('data_valid') is not True:
            continue
        previous = histories.get((mid, prior_quarter(row['review_period'])))
        if (month_tenure(member['entered_at_date'], cut.date().isoformat()) >= policy.minimum_tenure_months
                and row['rank'] > policy.exit_rank
                and previous is not None and previous['rank'] > policy.exit_rank
                and row['net_excess_12m'] < 0 and row['net_excess_24m'] < 0):
            exits.append(row)
    exits.sort(key=lambda x: (x['score'], x['economic_manager_id']))
    for outgoing in exits:
        if remaining <= 0:
            break
        chosen = next((r for r in entrants if r['economic_manager_id'] not in consumed
                       and r['score'] - outgoing['score'] >= policy.replacement_gap), None)
        if chosen is None:
            continue
        proposals.append({'action': 'REPLACE', 'incoming_manager': chosen['economic_manager_id'],
                          'outgoing_manager': outgoing['economic_manager_id'],
                          'reason': 'TWO_CONSECUTIVE_QUARTERS_AND_12M_24M_WEAKNESS',
                          'score_gap': chosen['score'] - outgoing['score']})
        consumed.add(chosen['economic_manager_id'])
        remaining -= 1
    for p in proposals:
        # Stable under an identical rerun. New evidence hashes create a new review.
        p['proposal_id'] = digest({'proposal': p, 'review_window': _halfyear(cut), 'config_hash': base['config_hash'],
                                   'score_input_hash': scored['input_hash']})
        p['requires_independent_approval'] = True
    return dict(base, status='PROPOSALS_ONLY' if proposals else 'NO_QUALIFIED_CHANGE',
                proposals=proposals, replacements_already_used=used_replacements,
                pending_replacements_reserved=pending_replacements,
                halfyear_replacement_budget_remaining=remaining)

