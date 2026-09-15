"""Shared H2 13F manager-skill validation contract.

This layer consumes reviewed post-disclosure clone evidence. It never treats
AUM, manager fame, seed priority, or a 13F holding by itself as manager skill.
It emits monitor/replacement PROPOSALS only; no active roster, stock position,
order, target book, or production policy is mutated here.
"""
from __future__ import annotations

import calendar
import hashlib
import json
import math
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from math import isfinite
from typing import Any, Iterable, Mapping


class IntegrityError(ValueError):
    """Required manager-skill evidence is missing, inconsistent, or non-PIT."""


def digest(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(',', ':'),
                     ensure_ascii=False, allow_nan=False).encode('utf-8')
    return hashlib.sha256(raw).hexdigest()


def instant(value: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise IntegrityError('timestamp_missing')
    try:
        dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as exc:
        raise IntegrityError('timestamp_invalid') from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise IntegrityError('timezone_required')
    return dt.astimezone(timezone.utc)


def required_text(row: Mapping, key: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value.strip():
        raise IntegrityError(f'missing:{key}')
    return value.strip()


def verified(row: Mapping, *keys: str) -> None:
    for key in keys:
        if row.get(key) is not True:
            raise IntegrityError(f'not_verified:{key}')


def quarter_end(value: str) -> date:
    try:
        dt = date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise IntegrityError('quarter_end_invalid') from exc
    if dt.month not in (3, 6, 9, 12) or dt.day != calendar.monthrange(dt.year, dt.month)[1]:
        raise IntegrityError('quarter_end_required')
    return dt


def prior_quarter(value: str) -> str:
    dt = quarter_end(value)
    year, month = (dt.year - 1, 12) if dt.month == 3 else (dt.year, dt.month - 3)
    return date(year, month, calendar.monthrange(year, month)[1]).isoformat()


def number(value: Any, *, nonnegative: bool = True) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise IntegrityError('number_missing_or_boolean')
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise IntegrityError('number_invalid') from exc
    if not result.is_finite() or (nonnegative and result < 0):
        raise IntegrityError('number_not_finite_or_negative')
    if not math.isfinite(float(result)):
        raise IntegrityError('number_out_of_range')
    return result

VERSION = '13f-manager-skill-policy-v1'
COMPONENT_WEIGHTS = {
    'clone_excess_36m': .35,
    'downside_recovery': .20,
    'new_add_incremental_excess': .20,
    'delay_robustness': .15,
    'independent_information': .10,
}


@dataclass(frozen=True)
class Policy:
    target_seats: int = 10
    entry_rank: int = 10
    entry_score: float = 70.
    exit_rank: int = 15
    replacement_gap: float = 10.
    minimum_tenure_months: int = 12
    replacements_per_halfyear: int = 2
    minimum_matured_quarters: int = 8
    minimum_independent_events: int = 20
    shrinkage_prior_events: int = 20
    source_manager_cap: float = .15
    source_cluster_cap: float = .35

    def __post_init__(self) -> None:
        integer_fields = ('target_seats', 'entry_rank', 'exit_rank',
                          'minimum_tenure_months', 'replacements_per_halfyear',
                          'minimum_matured_quarters', 'minimum_independent_events',
                          'shrinkage_prior_events')
        for key in integer_fields:
            value = getattr(self, key)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise IntegrityError(f'policy_integer_invalid:{key}')
        for key in ('entry_score', 'replacement_gap'):
            value = getattr(self, key)
            if isinstance(value, bool) or not isfinite(value) or not 0 <= value <= 100:
                raise IntegrityError(f'policy_score_invalid:{key}')
        if self.exit_rank < self.entry_rank:
            raise IntegrityError('policy_exit_buffer_invalid')
        if not 0 < self.source_manager_cap <= self.source_cluster_cap <= 1:
            raise IntegrityError('policy_influence_caps_invalid')


def month_tenure(start: str, end: str) -> int:
    a, b = date.fromisoformat(start), date.fromisoformat(end)
    if a > b:
        raise IntegrityError('future_cohort_entry')
    return (b.year - a.year) * 12 + b.month - a.month - int(b.day < a.day)

