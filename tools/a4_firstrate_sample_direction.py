"""Read two public FirstRate sample ZIPs into memory for an A4 direction check."""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timedelta
from io import BytesIO, StringIO
import math
import os
from urllib.request import Request, build_opener
from zipfile import BadZipFile, ZipFile
from zlib import error as ZlibError

from tools import a4_index_direction as index
from tools.macro_history_sources import NoRedirect, digest, stamp, utc_now

TICKERS = {'SP500': 'SPX', 'NASDAQ100': 'NDX'}
SAMPLES = 'https://frd001.s3.us-east-2.amazonaws.com/frd_sample_index_{}.zip'
MAX_ARCHIVE = 6_000_000
MAX_DAILY = 128 * 1024
ATTRIBUTION = 'FirstRate Data public evaluation samples'


def download(url):
    request = Request(url, headers={'User-Agent': 'A4-public-sample-evaluation/1.0', 'Accept': 'application/zip'})
    with build_opener(NoRedirect()).open(request, timeout=20) as response:
        index.require(response.status == 200, 'SAMPLE_HTTP_STATUS')
        return response.read(MAX_ARCHIVE + 1)


def parse_sample(archive, ticker, sessions):
    index.require(type(archive) is bytes and 0 < len(archive) <= MAX_ARCHIVE, 'SAMPLE_ARCHIVE_SIZE')
    with ZipFile(BytesIO(archive)) as zipper:
        members = zipper.infolist()
        daily = [item for item in members if item.filename == f'{ticker}_1day_sample.csv']
        index.require(len(members) <= 32 and len(daily) == 1 and
                      0 < daily[0].file_size <= MAX_DAILY, 'SAMPLE_DAILY_MEMBER')
        with zipper.open(daily[0]) as source:
            raw = source.read(MAX_DAILY + 1)
        index.require(len(raw) == daily[0].file_size, 'SAMPLE_DAILY_SIZE')

    prices = {}
    columns = ('open', 'high', 'low', 'close')
    for line, row in enumerate(csv.reader(StringIO(raw.decode('utf-8-sig')), strict=True)):
        index.require(len(row) == 5 and line <= 64, 'SAMPLE_ROW_SHAPE')
        if line == 0 and row[0].strip().lower() in {'date', 'timestamp', 'datetime'}:
            index.require(tuple(field.strip().lower() for field in row[1:]) == columns, 'SAMPLE_HEADER')
            continue
        day = datetime.fromisoformat(row[0].strip()).date().isoformat()
        index.require(day in sessions and day not in prices, 'SAMPLE_CLOSE_SESSION')
        close = float(row[4])
        index.require(math.isfinite(close) and close > 0, 'SAMPLE_CLOSE_VALUE')
        prices[day] = close
    index.require(bool(prices), 'SAMPLE_EMPTY')
    return prices


def check(*, scheduled=False, fetch=download, now=utc_now):
    started_at = now()
    start, expected = index.window(started_at)
    if scheduled:
        # The UTC cron runs the morning after the intended US session.
        target = (stamp(started_at).date() - timedelta(days=1)).isoformat()
        if target != expected:
            status = 'SKIPPED_NON_TRADING_DAY' if target > expected else 'SKIPPED_SESSION_ADVANCED'
            return dict(status=status, expected_session=target, common_session=None, provider_checks=0)

    schedule = index.market.clock.mcal.get_calendar('NYSE').schedule(start, expected)
    sessions = {session.date().isoformat() for session in schedule.index}
    captures = {}
    for series, ticker in TICKERS.items():
        url = SAMPLES.format(ticker)
        try:
            archive = fetch(url)
            observed_at = now()
            prices = parse_sample(archive, ticker, sessions)
        except (OSError, ValueError, BadZipFile, csv.Error, RuntimeError, ZlibError):
            captures[series] = None
        else:
            captures[series] = (prices, observed_at, digest(archive), url)

    cutoff = now()
    if index.window(cutoff)[1] != expected:
        return dict(status='SESSION_ROLLED', expected_session=expected, common_session=None, provider_checks=2)
    report = index.describe_closes(captures, cutoff=cutoff, attribution=ATTRIBUTION)
    report['provider_checks'] = len(TICKERS)
    return report


def render(report):
    lines = [
        '# A4 FirstRate public sample direction',
        '',
        'Source: [FirstRate Data public evaluation samples](https://firstratedata.com/free-intraday-data)',
        f"- Status: `{report['status']}`",
        f"- Expected NYSE session: {report['expected_session']}",
        f"- Last common session: {report['common_session'] or 'unavailable'}",
        f"- Public sample requests: {report['provider_checks']}",
    ]
    for series, source in report.get('series', {}).items():
        latest = source['latest_session'] or 'unavailable'
        lag = source['lag_sessions']
        lag_text = 'unavailable' if lag is None else str(lag)
        lines.append(f"- {TICKERS[series]}: `{source['status']}` / latest {latest} / lag {lag_text} sessions")

    if report['status'] == 'CURRENT_COMMON_SESSION':
        lines += ['', '| Trading sessions | SPX | NDX | Joint direction |', '| ---: | --- | --- | --- |']
        for row in report['horizons']:
            if row['status'] == 'OBSERVED':
                sides = row['per_index_direction']
                lines.append(f"| {row['sessions']} | {sides['SP500']} | {sides['NASDAQ100']} | {row['direction']} |")
            else:
                lines.append(f"| {row['sessions']} | | | INCOMPLETE_WINDOW |")
    return '\n'.join(lines) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scheduled', action='store_true')
    report = check(scheduled=parser.parse_args().scheduled)
    summary = render(report)
    print(summary, end='')
    if path := os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(path, 'a', encoding='utf-8') as output:
            output.write(summary)
    return 2 if report['status'] in {'NO_COMMON_SESSION', 'SKIPPED_SESSION_ADVANCED', 'SESSION_ROLLED'} else 0


if __name__ == '__main__':
    raise SystemExit(main())
