"""Archive original SPY and QQQ bar versions for private A4 research."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import os
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import pandas_market_calendars as mcal

from tools import alpaca_sip_private_backfill_v1 as private
from tools.a4_a1_price_monitor import read_ref
from tools.free_market_context import utc
from tools.twelve_private_capture import OwnerDrive, Refused, decode, digest, encoded, http, require

SYMBOLS = ('SPY', 'QQQ')
LISTINGS = {'SPY': {'ARCX'}, 'QQQ': {'XNAS', 'XNGS'}}
MAX_RAW = 512 * 1024
LOOKBACK_SESSIONS = 5
ID = re.compile('[A-Za-z0-9_.:/-]{1,100}')


def session_window(now):
    local_day = now.astimezone(ZoneInfo('America/New_York')).date()
    schedule = mcal.get_calendar('NYSE').schedule(local_day-timedelta(days=20), local_day)
    if schedule.empty or schedule.index[-1].date() != local_day or now < schedule.market_close.iloc[-1]:
        return {}
    return {day.date().isoformat(): close.to_pydatetime()
            for day, close in schedule.market_close.iloc[-LOOKBACK_SESSIONS:].items()}


def query_for(sessions, now):
    return {'symbols': ','.join(SYMBOLS), 'from': next(iter(sessions)), 'to': next(reversed(sessions)),
            'as_of': now.isoformat(), 'adjustment': 'raw', 'revisions': 'all', 'limit': '100'}


def fetch(query, key):
    return http('https://api.ohlc.io/v1/eod?' + urlencode(query),
                headers={'Authorization': 'Bearer '+key, 'Accept': 'application/json'},
                limit=MAX_RAW, credentials=(key,))


def validate_response(raw, sessions, cutoff):
    doc = decode(raw)
    require(type(doc) is dict and type(doc.get('data')) is list and type(doc.get('meta')) is dict,
            'A4_OHLC_RESPONSE')
    meta = doc['meta']
    require(not meta.get('errors') and not doc.get('next_cursor') and not meta.get('next_cursor')
            and utc(meta['as_of']) == cutoff and len(doc['data']) <= 100, 'A4_OHLC_REPLY_SCOPE')
    revisions = {symbol:{} for symbol in SYMBOLS}
    instruments = {}
    seen = set()
    for row in doc['data']:
        listed_symbol, day = row['symbol'], row['date']
        mic = row['exchange_mic']
        require(isinstance(listed_symbol, str), 'A4_OHLC_BAR_IDENTITY')
        qualifier, separator, symbol = listed_symbol.rpartition(':')
        identity = row['instrument_id']
        require(symbol in LISTINGS and mic in LISTINGS[symbol]
                and (not separator or qualifier == mic) and day in sessions
                and type(identity) is str and ID.fullmatch(identity)
                and instruments.setdefault(symbol, identity) == identity
                and row['currency_code']=='USD' and row['adjustment']=='raw'
                and row.get('factor_set_version') is None, 'A4_OHLC_BAR_IDENTITY')
        revision, published = row['revision_id'], utc(row['published_at'])
        require(type(revision) is str and ID.fullmatch(revision) and (symbol, revision) not in seen
                and sessions[day] <= published <= cutoff, 'A4_OHLC_PUBLICATION')
        seen.add((symbol, revision))
        close = row['close']
        if close is not None:
            require(type(close) is str and re.fullmatch(r'[0-9]{1,12}(?:\.[0-9]{1,12})?', close)
                    and Decimal(close) > 0, 'A4_OHLC_CLOSE')
        versions = revisions[symbol].setdefault(day, [])
        versions.append(dict(revision_id=revision, published_at=published.isoformat(), close=close))

    for days in revisions.values():
        for versions in days.values():
            versions.sort(key=lambda row: row['published_at'])
            clocks = [row['published_at'] for row in versions]
            require(len(set(clocks)) == len(clocks), 'A4_OHLC_CONFLICTING_PUBLICATION')
    require(len(set(instruments.values())) == len(instruments), 'A4_OHLC_INSTRUMENT_SCOPE')
    return revisions, instruments


def capture(drive, scope, sessions, *, key, cutoff, read_clock, run_id, attempt, code_sha, provider=fetch):
    require(type(scope) is dict and set(scope)=={'root_folder','capture_folder','rights'}
            and scope['root_folder']==drive.root_id, 'A4_OHLC_OWNER_SCOPE')
    require(bool(key) and 0 < len(key) <= 256, 'A4_OHLC_KEY_REQUIRED')
    folder = scope['capture_folder']
    drive.check(folder, drive.root_id)
    rights = read_ref(drive, folder, scope['rights'], 65536)
    query = query_for(sessions, cutoff)
    raw = provider(query, key)
    collected = read_clock()
    require(cutoff <= collected and 0 < len(raw) <= MAX_RAW, 'A4_OHLC_CAPTURE_CLOCK')
    revisions, instruments = validate_response(raw, sessions, cutoff)
    session = next(reversed(sessions))
    latest = {symbol: max((day for day,rows in days.items() if rows[-1]['close'] is not None), default=None)
              for symbol,days in revisions.items()}
    common = max((day for day in sessions
                  if all(revisions[symbol].get(day) and revisions[symbol][day][-1]['close'] is not None
                         for symbol in SYMBOLS)), default=None)
    first_close_by_cutoff = {symbol: next((row['published_at'] for row in revisions[symbol].get(session, [])
                                          if row['close'] is not None), None) for symbol in SYMBOLS}
    positions = {day:i for i,day in enumerate(sessions)}
    lag = {symbol:positions[session]-positions[day] if day is not None else None
           for symbol,day in latest.items()}
    lagging = [symbol for symbol, day in latest.items()
               if any(other is not None and (day is None or other>day) for other in latest.values())]
    summary = dict(expected_session=session, latest_session_by_symbol=latest, common_session=common,
                   lag_sessions=lag, lagging_symbols=lagging,
                   first_close_published_by_symbol=first_close_by_cutoff,
                   data_status='CURRENT_COMMON_SESSION' if common==session else
                               'NO_COMMON_SESSION' if common is None else
                               'ONE_SIDE_DELAYED' if lagging else 'DELAYED_COMMON_SESSION')
    reference = private.persist_object(drive, folder, raw, '.json')
    manifest = dict(schema='a4-ohlc-private-capture-v1', authority='PERSONAL_RESEARCH_ONLY',
                    captured_at=collected.isoformat(), query=query, instrument_ids=instruments,
                    originals=reference, rights_sha256=digest(rights), revisions=revisions,
                    return_basis='RAW_AS_TRADED_USD', learning_admitted=False, **summary)
    manifest_raw = encoded(manifest)
    stored = private.persist_object(drive, folder, manifest_raw, '.json')
    require(read_ref(drive, folder, reference, MAX_RAW) == raw
            and read_ref(drive, folder, stored, MAX_RAW) == manifest_raw, 'A4_OHLC_DURABLE_READBACK')
    return dict(schema='a4-ohlc-public-receipt-v1', status='PRIVATE_ARCHIVE_READBACK_VERIFIED',
                run_id=run_id, attempt=attempt, code_sha=code_sha, original_sha256=reference['sha256'],
                manifest_sha256=stored['sha256'], **summary)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--receipt', type=Path, required=True)
    args = parser.parse_args()
    try:
        now = datetime.now(timezone.utc)
        sessions = session_window(now)
        if not sessions:
            result = dict(schema='a4-ohlc-public-receipt-v1', status='SKIPPED_NO_COMPLETED_SESSION_TODAY')
        else:
            key = os.environ.get('A4_OHLC_API_KEY','')
            require(bool(key) and len(key)<=256, 'A4_OHLC_KEY_REQUIRED')
            scope = decode(os.environ['A4_OHLC_SCOPE'].encode())
            with TemporaryDirectory(prefix='a4-ohlc-') as temp:
                drive = OwnerDrive(scope['root_folder'], temp)
                result = capture(drive, scope, sessions, key=key,
                    cutoff=now, read_clock=lambda: datetime.now(timezone.utc), run_id=os.environ['GITHUB_RUN_ID'],
                    attempt=os.environ['GITHUB_RUN_ATTEMPT'], code_sha=os.environ['GITHUB_SHA'])
        args.receipt.write_bytes(encoded(result))
        print(encoded(result).decode().strip())
    except (Refused, ValueError, OSError, KeyError, TypeError, OverflowError, InvalidOperation) as exc:
        reason = str(exc)
        if not isinstance(exc, Refused) or not re.fullmatch(r'[A-Z0-9_]{2,80}', reason):
            reason = 'A4_OHLC_CAPTURE_BLOCKED'
        raise SystemExit(reason) from None


if __name__ == '__main__':
    main()
