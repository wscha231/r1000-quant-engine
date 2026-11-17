"""Finite, opt-in price failover using existing provider adapters. No fitting."""
from __future__ import annotations

from datetime import timedelta
import math
import os
import re
import time

import pandas as pd
from tools.macro_history_sources import digest, encoded

PROVIDERS = ('alpaca_sip', 'yfinance', 'twelve_data')
PIN_PATHS = ('tools/a4_price_fallback.py', 'tools/alpaca_sip_private_backfill_v1.py',
             'tools/twelve_private_capture.py')
MAX_EVIDENCE_BYTES = 8 * 1024**2
MAX_RESPONSE_BYTES = 2 * 1024**2
MAX_REQUESTS_PER_PROVIDER = 2
DATA_CODES = frozenset(('FRAME', 'INDEX', 'LATEST_SESSION_CLOSE', 'FRAME_COLUMNS',
                       'FRAME_FINITE', 'RETURNED_TARGETS', 'EXACT_SESSION_CLOSE',
                       'VALUE', 'DATE_GRID', 'HISTORY_START', 'HISTORY_COVERAGE'))
SAFE_FAILURES = frozenset(('AUTH', 'ENTITLEMENT', 'PERMISSION', 'RATE_LIMIT', 'NETWORK',
    'HTTP_ERROR', 'RESPONSE_SIZE', 'BARS_SCHEMA', 'BAR_VALUE', 'BAR_TIMESTAMP',
    'BAR_RANGE', 'DUPLICATE_SESSION', 'PAGE_BUDGET', 'PAGE_TOKEN', 'UNKNOWN_SYMBOL',
    'PROVIDER_SHAPE', 'PROVIDER_ERROR', 'IDENTITY', 'CREDENTIALS_NOT_CONFIGURED',
    'OWNER_ACK_REQUIRED', 'END_DELAY_NOT_ELAPSED', 'REQUEST_BUDGET'))


class Unavailable(ValueError):
    """Fixed, nonsecret reason that may advance to a different source."""


class IntegrityError(ValueError):
    """An integrity/policy failure must stop the chain."""


def need(ok, code):
    if not ok:
        raise Unavailable(code)


def policy_check(policy):
    rows = policy.get('providers')
    need(type(rows) is list and 2 <= len(rows) <= 3, 'PROVIDER_POLICY')
    ids = [r.get('id') for r in rows if type(r) is dict]
    need(len(ids) == len(rows) == len(set(ids)) and all(x in PROVIDERS for x in ids), 'PROVIDER_POLICY')
    need(type(policy.get('maximum_batch_calls_per_attempt')) is int
         and policy['maximum_batch_calls_per_attempt'] == len(rows), 'PROVIDER_POLICY')
    for row in rows:
        fields={'id','private_noncommercial_test_authorized','use_scope_sha256','maximum_requests'}
        fields|={'mic_by_target'} if row['id']=='twelve_data' else ({'noncommercial_terms_acknowledged'} if row['id']=='alpaca_sip' else set())
        need(set(row)==fields,'PROVIDER_POLICY')
        need(row.get('private_noncommercial_test_authorized') is True
             and type(row.get('use_scope_sha256')) is str
             and re.fullmatch('[a-f0-9]{64}', row['use_scope_sha256'])
             and type(row.get('maximum_requests')) is int
             and row['maximum_requests'] == (1 if row['id'] == 'yfinance' else 2), 'PROVIDER_POLICY')
        if row['id']=='alpaca_sip':
            need(row.get('noncommercial_terms_acknowledged') is True,'PROVIDER_POLICY')
        if row['id'] == 'twelve_data':
            mic = row.get('mic_by_target')
            need(type(mic) is dict and set(mic) == {'SPY', 'QQQ'}
                 and all(type(x) is str and re.fullmatch('[A-Z0-9]{4}', x) for x in mic.values()), 'PROVIDER_POLICY')
    return rows


def structure(frames):
    """Value-free diagnostics; never echo arbitrary labels or exception bodies."""
    out = {}
    for symbol in ('SPY', 'QQQ'):
        frame = frames.get(symbol) if type(frames) is dict else None
        if not isinstance(frame, pd.DataFrame):
            out[symbol] = dict(type='NOT_DATAFRAME', shape=None, columns=None, index=None)
            continue
        allowed = {'Open', 'High', 'Low', 'Close', 'Adj Close', 'Volume'}
        labels = [x if type(x) is str and x in allowed else 'OTHER' for x in list(frame.columns)[:12]]
        out[symbol] = dict(type='DATAFRAME', shape=list(frame.shape), columns=labels,
                           index='DATETIME' if isinstance(frame.index, pd.DatetimeIndex) else 'OTHER')
    return out


def failure_code(exc):
    if isinstance(exc, IntegrityError):
        raise exc
    message = str(exc)
    if message == 'CREDENTIAL_ECHO':
        raise IntegrityError('CREDENTIAL_ECHO') from None
    prefix = 'A4_FLOW_PRICE_'
    if isinstance(exc, ValueError) and message.startswith(prefix):
        code = message[len(prefix):]
        if code in DATA_CODES:
            return code
        raise IntegrityError('PRICE_POLICY_OR_IMPLEMENTATION_CHANGED') from None
    if message in SAFE_FAILURES or isinstance(exc,Unavailable) and message in DATA_CODES:
        return message
    return 'PROVIDER_UNAVAILABLE'


def fetch_alpaca(targets, start, end, descriptor, capture, clock):
    from tools import alpaca_sip_private_backfill_v1 as source
    from tools import a4_primary_sources as primary
    # Preserve the existing delayed inclusive-end contract, before credentials.
    due = primary.clock(end + 'T00:00:00Z') + timedelta(minutes=15)
    need(primary.clock(clock()) >= due, 'END_DELAY_NOT_ELAPSED')
    need(descriptor.get('noncommercial_terms_acknowledged') is True, 'OWNER_ACK_REQUIRED')
    key, secret = os.environ.get('ALPACA_API_KEY', '').strip(), os.environ.get('ALPACA_API_SECRET', '').strip()
    need(key and secret, 'CREDENTIALS_NOT_CONFIGURED')
    def get(url, **kwargs):
        return capture(lambda: source.http(url, **{**kwargs, 'limit': MAX_RESPONSE_BYTES}), (key, secret))
    _, grouped, _ = source.request_pages(targets, 'raw', start, end, key, secret, get=get)
    frames = {}
    for target in targets:
        rows = source.normalize(grouped[target], target, 'raw', start, end)
        frames[target] = pd.DataFrame({col: [float(r[field]) for r in rows]
            for col, field in (('Open', 'open'), ('High', 'high'), ('Low', 'low'), ('Close', 'close'), ('Volume', 'volume'))},
            index=pd.to_datetime([r['date'] for r in rows]))
    return frames


def twelve_frames(payloads, descriptor, start, end):
    frames = {}
    for target in ('SPY', 'QQQ'):
        data = payloads[target];meta = data.get('meta', {})
        need(meta.get('symbol') == target and meta.get('currency') == 'USD'
             and meta.get('interval') == '1day' and meta.get('mic_code') == descriptor['mic_by_target'][target], 'IDENTITY')
        rows = data.get('values');need(type(rows) is list and 2 <= len(rows) <= 5000, 'PROVIDER_SHAPE')
        dates, values = [], []
        for row in rows:
            need(type(row) is dict and set(row) == {'datetime', 'open', 'high', 'low', 'close', 'volume'}, 'PROVIDER_SHAPE')
            day = row['datetime'];need(type(day) is str and re.fullmatch(r'\d{4}-\d{2}-\d{2}', day)
                                      and start <= day < end, 'BAR_RANGE')
            numbers = [float(row[k]) for k in ('open', 'high', 'low', 'close', 'volume')]
            o, h, l, c, v = numbers
            need(all(math.isfinite(x) for x in numbers) and min(o, h, l, c) > 0
                 and l <= min(o, c) <= max(o, c) <= h and v >= 0, 'BAR_VALUE')
            dates.append(day);values.append(numbers)
        need(len(set(dates)) == len(dates), 'DUPLICATE_SESSION')
        frames[target] = pd.DataFrame(values, index=pd.to_datetime(dates),
            columns=['Open', 'High', 'Low', 'Close', 'Volume']).sort_index()
    return frames


def fetch_twelve(targets, start, end, descriptor, capture, clock):
    from tools import twelve_private_capture as source
    key = os.environ.get('TWELVE_API_KEY', '').strip()
    need(key, 'CREDENTIALS_NOT_CONFIGURED')
    payloads = {}
    for target in targets:
        query = dict(symbol=target, mic_code=descriptor['mic_by_target'][target], interval='1day',
                     start_date=start, end_date=(pd.Timestamp(end).date()-timedelta(days=1)).isoformat(),
                     outputsize=5000, order='asc', adjust='none')
        # Existing authenticated no-redirect/no-retry HTTP path; no key in URL.
        from urllib.parse import urlencode
        time.sleep(10)
        raw = capture(lambda: source.http('https://api.twelvedata.com/time_series?' + urlencode(query),
            headers={'Authorization': 'apikey ' + key, 'Accept': 'application/json'},
            credentials=(key,), limit=MAX_RESPONSE_BYTES), (key,))
        data = source.credential_safe_json(raw, (key,))
        if data.get('status') == 'error':
            raise Unavailable({401:'AUTH',402:'ENTITLEMENT',403:'PERMISSION',429:'RATE_LIMIT'}.get(data.get('code'), 'PROVIDER_ERROR'))
        payloads[target] = data
    return twelve_frames(payloads, descriptor, start, end)


def fetch_yfinance(targets, start, end, descriptor, capture, clock):
    from tools import build_replay_price_cache as source
    frames, _ = source.download_yfinance(targets, start, end)
    return frames


ADAPTERS = dict(alpaca_sip=fetch_alpaca, yfinance=fetch_yfinance, twelve_data=fetch_twelve)


def collect(policy, *, session, build, check_policy, clock, audit=None, adapters=None):
    """Select one complete provider pair; do not splice prices or repeat providers."""
    from tools import twelve_private_capture as safe
    descriptors = policy_check(policy)
    adapters = ADAPTERS if adapters is None else adapters
    attempts, responses = [], {}
    end = (pd.Timestamp(session).date() + timedelta(days=1)).isoformat()
    def emit():
        evidence = dict(schema='a4-price-provider-evidence-v2', attempts=attempts, responses=responses)
        if len(encoded(evidence)) > MAX_EVIDENCE_BYTES:
            raise IntegrityError('PROVIDER_EVIDENCE_SIZE')
        if audit is not None:
            audit(evidence)
        return evidence
    for descriptor in descriptors:
        check_policy()
        provider = descriptor['id']
        attempt = dict(provider=provider, status='STARTED', started_at=clock(), requests=0,
                       backend_HTTP_count='UNKNOWN' if provider == 'yfinance' else 0, response_sha256s=[])
        attempts.append(attempt);emit()
        def capture(operation, credentials):
            check_policy()
            if attempt['requests'] >= descriptor['maximum_requests']:
                raise Unavailable('REQUEST_BUDGET')
            attempt['requests'] += 1
            if type(attempt['backend_HTTP_count']) is int:
                attempt['backend_HTTP_count'] += 1
            raw = operation()
            if type(raw) is not bytes or not 0 < len(raw) <= MAX_RESPONSE_BYTES:
                raise Unavailable('RESPONSE_SIZE')
            safe.credential_safe_json(raw, credentials)
            pin = digest(raw);responses[pin] = raw.decode('utf-8');attempt['response_sha256s'].append(pin)
            emit();check_policy()
            return raw
        try:
            adapter = adapters[provider]
            frames = adapter(['SPY', 'QQQ'], policy['price_start'], end, descriptor, capture, clock)
            attempt['structure'] = structure(frames)
            check_policy()
            snapshot, view = build(frames)
            need(all(frame.index[0].date().isoformat() <= '2016-01-11' for frame in frames.values()), 'HISTORY_START')
            # A pair of endpoints is not a decade of history. This is a lower
            # coverage guard, not a complete exchange-calendar certification.
            need(all(sum(row[1] is not None for row in rows)>=2000 for rows in view['targets'].values()),'HISTORY_COVERAGE')
            attempt.update(status='SELECTED', completed_at=clock());evidence = emit()
            snapshot.update(schema='a4-collector-dataframe-snapshot-v2', provider=provider,
                provider_evidence=evidence, provider_descriptor=descriptor,
                collection_started_at=attempt['started_at'],
                request_start=policy['price_start'],request_end_exclusive=end,
                raw_http_originals_available=bool(attempt['response_sha256s']))
            view.update(schema='a4-flow-test-price-view-v2', selected_provider=provider,
                provider_attempts=attempts, approved_provider_ids=[x['id'] for x in descriptors],
                collector_batch_calls=len(attempts),
                selected_descriptor_sha256=digest(encoded(descriptor)),
                raw_http_originals_available=snapshot['raw_http_originals_available'],
                basis='VENDOR_RAW_CLOSE_CURRENT_VINTAGE_UNQUALIFIED', snapshot_sha256=digest(encoded(snapshot)))
            if len(encoded(snapshot)) > MAX_EVIDENCE_BYTES:
                raise IntegrityError('SNAPSHOT_SIZE')
            return snapshot, view
        except Exception as exc:
            attempt.update(status='REJECTED', completed_at=clock())
            try:
                attempt['reason'] = failure_code(exc)
            except IntegrityError:
                attempt['reason'] = 'INTEGRITY_OR_POLICY_STOP';emit();raise
            emit()
    raise Unavailable('ALL_PRICE_PROVIDERS_UNAVAILABLE')


def verify_evidence(snapshot):
    """Replay retained HTTP bodies for the selected adapter, without networking."""
    from tools.twelve_private_capture import decode
    evidence = snapshot.get('provider_evidence');need(type(evidence) is dict, 'PROVIDER_SHAPE')
    responses = evidence.get('responses');attempts = evidence.get('attempts')
    need(type(responses) is dict and type(attempts) is list and 1 <= len(attempts) <= 3, 'PROVIDER_SHAPE')
    ids = [x['provider'] for x in attempts]
    need(len(set(ids)) == len(ids) and all(x in PROVIDERS for x in ids), 'PROVIDER_SHAPE')
    need(all(a.get('status')=='REJECTED' for a in attempts[:-1]),'PROVIDER_SHAPE')
    referenced=[]
    for attempt in attempts:
        maximum=1 if attempt['provider']=='yfinance' else 2
        need(type(attempt.get('requests')) is int and 0<=attempt['requests']<=maximum
             and type(attempt.get('response_sha256s')) is list,'PROVIDER_SHAPE')
        referenced.extend(attempt['response_sha256s'])
    need(set(referenced)==set(responses) and len(referenced)<=6,'PROVIDER_SHAPE')
    for pin, body in responses.items():
        need(type(body) is str and digest(body.encode()) == pin, 'RESPONSE_HASH')
    chosen = [x for x in attempts if x['status'] == 'SELECTED']
    need(len(chosen) == 1 and chosen[0] is attempts[-1] and chosen[0]['provider'] == snapshot['provider'], 'PROVIDER_SHAPE')
    selected = chosen[0];pins = selected['response_sha256s']
    need(snapshot['raw_http_originals_available'] == bool(pins)
         and all(pin in responses for pin in pins), 'PROVIDER_SHAPE')
    provider=snapshot['provider']
    need(snapshot.get('provider_descriptor',{}).get('id')==provider,'PROVIDER_SHAPE')
    if provider=='yfinance':need(not pins,'PROVIDER_SHAPE')
    if provider!='yfinance':
        need(1<=len(pins)<=2,'PROVIDER_SHAPE')
        if provider=='alpaca_sip':
            from tools import alpaca_sip_private_backfill_v1 as alpaca
            grouped={target:[] for target in ('SPY','QQQ')}
            for pin in pins:
                payload=decode(responses[pin].encode())
                need(type(payload.get('bars')) is dict and set(payload['bars'])<=set(grouped),'BARS_SCHEMA')
                for target,rows in payload['bars'].items():grouped[target].extend(rows)
            rebuilt={target:[[r['date'],float(r['close'])] for r in alpaca.normalize(rows,target,'raw',
                snapshot['request_start'],snapshot['request_end_exclusive'])] for target,rows in grouped.items()}
        else:
            payloads={}
            for pin in pins:
                data=decode(responses[pin].encode());target=data.get('meta',{}).get('symbol')
                need(target in ('SPY','QQQ') and target not in payloads,'IDENTITY');payloads[target]=data
            need(set(payloads)=={'SPY','QQQ'},'PROVIDER_SHAPE')
            frames=twelve_frames(payloads,snapshot['provider_descriptor'],snapshot['request_start'],snapshot['request_end_exclusive'])
            rebuilt={target:[[d.date().isoformat(),float(v)] for d,v in frame['Close'].items()] for target,frame in frames.items()}
        for target,frame in snapshot['frames'].items():
            index=frame['columns'].index('Close')
            need([[d,row[index]] for d,row in zip(frame['dates'],frame['values'])]==rebuilt[target],'RAW_NORMALIZATION_REPLAY')
    return evidence
