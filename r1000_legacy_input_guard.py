"""Admission checks for legacy current-score/target consumers.

These checks reject bad inputs; passing them does not certify source provenance,
PIT history, valuation, a target book, or permission to trade. No file mtime or
job timestamp substitutes for a row's observation date.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import math
import hashlib
import io
import os
import tempfile
from contextvars import ContextVar
from functools import wraps

import pandas as pd


class InputIntegrityError(ValueError):
    pass


def _utc(value):
    try:
        stamp = pd.Timestamp(value)
    except (ValueError, TypeError, OverflowError):
        raise InputIntegrityError('invalid_available_time') from None
    if pd.isna(stamp) or stamp.tzinfo is None:
        raise InputIntegrityError('aware_available_time_required')
    return stamp.tz_convert('UTC')


def latest_completed_close(now=None):
    import pandas_market_calendars as mcal
    now = _utc(now if now is not None else datetime.now(timezone.utc))
    schedule = mcal.get_calendar('NYSE').schedule(
        start_date=(now - timedelta(days=21)).date(), end_date=now.date())
    closed = schedule.loc[schedule['market_close'] <= now]
    if closed.empty:
        raise InputIntegrityError('completed_nyse_session_unavailable')
    return closed.index[-1].date().isoformat(), closed['market_close'].iloc[-1], now


def _finite(value):
    if isinstance(value, bool) or type(value).__name__ == 'bool_':
        return False
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError, OverflowError):
        return False


def validate_current_frame(frame, *, kind='scores', now=None):
    """Return a validated copy or reject the entire packet, never drop holdings."""
    if kind not in ('scores', 'targets'):
        raise InputIntegrityError('invalid_input_kind')
    if frame.empty or 'ticker' not in frame or frame['ticker'].isna().any():
        raise InputIntegrityError('missing_ticker_identity')
    result = frame.copy()
    result['ticker'] = result['ticker'].astype(str).str.strip().str.upper()
    if (result['ticker'].duplicated().any()
            or not result['ticker'].str.fullmatch(r'[A-Z][A-Z0-9.-]{0,14}').all()):
        raise InputIntegrityError('invalid_or_duplicate_ticker')
    session, close, decision = latest_completed_close(now)
    # Require both a score/target observation date AND the pricing date.
    date_columns = ('score_as_of', 'score_date', 'rebalance_date', 'feature_date') if kind == 'scores' else (
        'target_as_of', 'target_date', 'rebalance_date')
    present = [name for name in date_columns if name in result]
    if not present or 'valuation_price_cutoff_date' not in result:
        raise InputIntegrityError('observation_and_price_dates_required')
    for name in [*present, 'valuation_price_cutoff_date']:
        # Date columns are date labels, not timestamps or integer nanoseconds.
        dates = result[name].astype(str)
        if not dates.eq(session).all():
            raise InputIntegrityError('stale_future_or_conflicting_date:' + name)
    if 'feature_available_from' not in result:
        raise InputIntegrityError('feature_available_from_required')
    available = result['feature_available_from'].map(_utc)
    if ((available < close) | (available > decision)).any():
        raise InputIntegrityError('feature_not_available_for_current_close')
    if kind == 'scores':
        if 'score_available_from' not in result:
            raise InputIntegrityError('score_available_from_required')
        score_available = result['score_available_from'].map(_utc)
        if ((score_available < close) | (score_available > decision)
                | (score_available < available)).any():
            raise InputIntegrityError('score_not_available_for_current_close')
    for name in ('ranking_eligible', 'model_eligible', 'decision_ranking_allowed'):
        if name in result and not result[name].map(lambda v: str(v).strip().lower() == 'true').all():
            raise InputIntegrityError('upstream_ineligible:' + name)
    if 'valuation_approved' in result and not result['valuation_approved'].map(
            lambda v: str(v).strip().lower() == 'true').all():
        raise InputIntegrityError('valuation_unapproved')
    if 'corporate_action_quarantine' in result and not result['corporate_action_quarantine'].map(
            lambda v: str(v).strip().lower() == 'false').all():
        raise InputIntegrityError('corporate_action_quarantined')
    if 'score_source' in result:
        source = result['score_source'].astype(str).str.strip().str.lower()
        if source.str.contains('synthetic|unscored|unverified', regex=True).any() or source.isin(['', 'none', 'nan']).any():
            raise InputIntegrityError('unverified_or_synthetic_score')
    if kind == 'scores':
        prices = [c for c in ('px', 'current_price_live') if c in result]
        if not prices:
            raise InputIntegrityError('current_price_required')
        for name in prices:
            if not result[name].map(lambda v: _finite(v) and float(v) > 0).all():
                raise InputIntegrityError('invalid_current_price:' + name)
        if len(prices) == 2 and not result[prices[0]].astype(float).eq(result[prices[1]].astype(float)).all():
            raise InputIntegrityError('conflicting_current_prices')
        scores = [c for c in ('score', 'score_total', 'model_score', 'score_model_core') if c in result]
        if not scores:
            raise InputIntegrityError('model_score_required')
        for name in scores:
            if not result[name].map(_finite).all():
                raise InputIntegrityError('nonfinite_model_score:' + name)
    else:
        if 'target_available_from' not in result:
            raise InputIntegrityError('target_available_from_required')
        target_available = result['target_available_from'].map(_utc)
        if ((target_available < available) | (target_available > decision)).any():
            raise InputIntegrityError('target_not_available_for_current_close')
        if 'score_available_from' in result:
            source_available = result['score_available_from'].map(_utc)
            if (target_available < source_available).any():
                raise InputIntegrityError('target_predates_source_score')
        if 'execution_reference_price' not in result:
            raise InputIntegrityError('execution_reference_price_required')
        prices = [c for c in ('execution_reference_price', 'px', 'current_price_live') if c in result]
        for name in prices:
            if not result[name].map(lambda v: _finite(v) and float(v) > 0).all():
                raise InputIntegrityError('invalid_target_price:' + name)
            if not result[name].astype(float).eq(result['execution_reference_price'].astype(float)).all():
                raise InputIntegrityError('conflicting_target_prices')
        weights = [c for c in ('weight', 'proposed_weight') if c in result]
        if not weights:
            raise InputIntegrityError('target_weight_required')
        for name in weights:
            if not result[name].map(_finite).all():
                raise InputIntegrityError('invalid_target_weight')
            values = result[name].astype(float)
            if (values < 0).any() or values.sum() <= 0 or values.sum() > 1.000001:
                raise InputIntegrityError('invalid_target_weight')
        if len(weights) == 2 and not result[weights[0]].astype(float).eq(result[weights[1]].astype(float)).all():
            raise InputIntegrityError('conflicting_target_weights')
    return result


def read_csv_packet(path, *, receipt_policy='required'):
    """Read hash-bound bytes; historical transport does not certify freshness.

    Legacy mode is for direct producers without bridge receipts. It cannot
    exempt a named or marked bridge output, and any existing receipt is binding.
    """
    if receipt_policy not in ('required', 'legacy_source'):
        raise InputIntegrityError('invalid_receipt_policy')
    path = Path(path)
    coverage_path = Path(str(path) + '.coverage.json')
    receipt = coverage_path.read_bytes() if coverage_path.exists() else None
    raw = path.read_bytes()
    frame = pd.read_csv(io.BytesIO(raw))
    is_bridge = (path.name == 'scored_unified.csv' or
                 ('input_packet_kind' in frame and frame['input_packet_kind'].isin(
                     ['unified_bridge_v1', 'advisor_target_v1', 'pipeline_target_v1']).any()))
    if receipt is None and (receipt_policy == 'required' or is_bridge):
        raise InputIntegrityError('coverage_receipt_required')
    if receipt is not None:
        try:
            coverage = json.loads(receipt)
        except (ValueError, OSError):
            raise InputIntegrityError('invalid_coverage_receipt') from None
        if not isinstance(coverage, dict) or coverage.get('status') not in ('LEGACY_COMPATIBILITY_ONLY',):
            raise InputIntegrityError('blocked_coverage_receipt')
        if coverage.get('compatible_sha256') != hashlib.sha256(raw).hexdigest():
            raise InputIntegrityError('coverage_output_hash_mismatch')
    if (coverage_path.read_bytes() if coverage_path.exists() else None) != receipt:
        raise InputIntegrityError('coverage_changed_during_read')
    return frame, raw, receipt


def load_current_csv(path, *, kind='scores', now=None, receipt_policy='required'):
    frame, _, _ = read_csv_packet(path, receipt_policy=receipt_policy)
    return validate_current_frame(frame, kind=kind, now=now)


def _atomic_packet_bytes(path, raw):
    path = Path(path)
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise InputIntegrityError('symlink_output')
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def copy_bridge_packet(source, destination):
    """Transport immutable bytes, publishing the success receipt last."""
    source, destination = Path(source), Path(destination)
    if source.resolve() == destination.resolve():
        raise InputIntegrityError('same_packet_destination')
    receipt_path = Path(str(destination) + '.coverage.json')
    _atomic_packet_bytes(receipt_path, b'{"status":"BLOCKED_COPY_IN_PROGRESS"}')
    _, raw, receipt = read_csv_packet(source)
    _atomic_packet_bytes(destination, raw)
    _atomic_packet_bytes(receipt_path, receipt)
    read_csv_packet(destination)


def begin_target_build(path):
    """Revoke retained proposals before any source load or ranking can fail."""
    _atomic_packet_bytes(Path(str(path) + '.coverage.json'),
                         b'{"status":"BLOCKED_TARGET_BUILD_IN_PROGRESS"}')


PIPELINE_TARGET_NAMES = ('portfolio_latest.csv', 'concentrated_portfolio_latest.csv')
_target_builds = ContextVar('target_builds', default=None)


def protect_target_build(resolve_output_directory):
    """Revoke at entry and publish only files written by a successful outer build."""
    def decorate(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            root = Path(resolve_output_directory(*args, **kwargs)).resolve()
            active = _target_builds.get() or {}
            if root in active:
                return function(*args, **kwargs)
            paths = [root / name for name in PIPELINE_TARGET_NAMES]
            for path in paths:
                begin_target_build(path)
            written = set()
            token = _target_builds.set({**active, root: written})
            try:
                result = function(*args, **kwargs)
                for path in written:
                    raw = path.read_bytes()
                    frame = pd.read_csv(io.BytesIO(raw))
                    receipt = {'status': 'BLOCKED_EMPTY_TARGET' if frame.empty else 'LEGACY_COMPATIBILITY_ONLY',
                               'investment_approved': False, 'compatible_sha256': hashlib.sha256(raw).hexdigest()}
                    _atomic_packet_bytes(Path(str(path) + '.coverage.json'), json.dumps(receipt).encode())
                return result
            except BaseException:
                for path in paths:
                    begin_target_build(path)
                raise
            finally:
                _target_builds.reset(token)
        return wrapped
    return decorate


def write_pipeline_target(frame, path):
    """Write a newly generated target inside its protected build transaction."""
    path = Path(path).resolve()
    active = _target_builds.get() or {}
    if path.parent not in active or path.name not in PIPELINE_TARGET_NAMES:
        raise InputIntegrityError('target_build_transaction_required')
    result = frame.copy()
    result['input_packet_kind'] = 'pipeline_target_v1'
    _atomic_packet_bytes(path, result.to_csv(index=False).encode('utf-8'))
    active[path.parent].add(path)


def stamp_target_generation(frame, *, now=None):
    """Stamp newly produced latest targets, preserving observation dates/cost basis.

    Historical research exports retain historical cutoffs and are still rejected
    by current consumers. This helper does not approve or refresh input data.
    """
    result = frame.copy()
    result['target_available_from'] = _utc(now if now is not None else datetime.now(timezone.utc)).isoformat()
    price = next((c for c in ('px', 'current_price_live') if c in result), None)
    result['execution_reference_price'] = result[price] if price else float('nan')
    return result


def write_advisor_targets(targets, scored, path, *, now=None):
    """Carry admitted input provenance into a newly generated proposal.

    The generation timestamp is new; score/price/feature observations are copied
    unchanged. Unknown candidate provenance blocks rather than inventing dates.
    """
    path = Path(path)
    receipt_path = Path(str(path) + '.coverage.json')
    begin_target_build(path)
    decision = _utc(now if now is not None else datetime.now(timezone.utc))
    source = validate_current_frame(scored, now=decision).set_index('ticker')
    result = targets.copy()
    if result.empty or 'ticker' not in result:
        raise InputIntegrityError('missing_target_identity')
    result['ticker'] = result['ticker'].astype(str).str.strip().str.upper()
    if not result['ticker'].isin(source.index).all():
        raise InputIntegrityError('target_source_provenance_missing')
    for name in ('valuation_price_cutoff_date', 'feature_available_from', 'score_available_from'):
        result[name] = result['ticker'].map(source[name])
    price = 'px' if 'px' in source else 'current_price_live'
    result['execution_reference_price'] = result['ticker'].map(source[price])
    result['target_as_of'] = result['valuation_price_cutoff_date']
    result['target_available_from'] = decision.isoformat()
    result['input_packet_kind'] = 'advisor_target_v1'
    result = validate_current_frame(result, kind='targets', now=decision)
    raw = result.to_csv(index=False).encode('utf-8')
    _atomic_packet_bytes(path, raw)
    receipt = {'status': 'LEGACY_COMPATIBILITY_ONLY', 'investment_approved': False,
               'compatible_sha256': hashlib.sha256(raw).hexdigest()}
    _atomic_packet_bytes(receipt_path, json.dumps(receipt).encode('utf-8'))
    return result
