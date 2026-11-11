"""Bounded FRB-original capture and normalization for A4 research.

Current SDMX histories retain revisions, not historical publication evidence.
This producer has no FRED dependency, trading authority or training admission.
Authentication and durable transports are supplied by the existing caller.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import gzip
import io
import json
from pathlib import Path
import re
import stat
import sys
import zlib
from urllib.request import Request, build_opener
import xml.etree.ElementTree as ET
import zipfile

from tools.macro_history_sources import NoRedirect, digest, encoded, exclusive
from tools import free_market_context as f
from tools.research_data_access import clock, day, read_object

MAX_ORIGINAL = 18 * 1024**2
MAX_EXPANDED = 220 * 1024**2
MAX_TOTAL = 256 * 1024**2
MAX_ROWS = 150000
MAX_SERIES = 10000
MAX_NORMALIZED_BYTES = 128 * 1024**2
MAX_LINE_BYTES = 64 * 1024
PREFIX = 'shared-research-v1/macro-primary'
FEEDS = {
    'h41': ('https://www.federalreserve.gov/releases/h41/data/FRB_h41_xml.zip', 'H41_data.xml', 'H41_struct.xml'),
    'h8': ('https://www.federalreserve.gov/releases/h8/data/FRB_h8_xml.zip', 'H8_data.xml', 'H8_struct.xml'),
    'prates': ('https://www.federalreserve.gov/releases/prates/data/FRB_PRATES_xml.zip', 'PRATES_data.xml', 'PRATES_struct.xml'),
    'sofr': ('https://markets.newyorkfed.org/api/rates/secured/sofr/last/30.json', None, None),
    'tgcr': ('https://markets.newyorkfed.org/api/rates/secured/tgcr/last/30.json', None, None),
    'effr': ('https://markets.newyorkfed.org/api/rates/unsecured/effr/last/30.json', None, None),
}
RIGHTS_URI = 'https://www.federalreserve.gov/disclaimer.htm'
SCHEMA = 'a4-primary-source-bundle-v1'
NYFED_NOTICE = (
    'The SOFR, TGCR and EFFR data are subject to the Terms of Use posted at newyorkfed.org. '
    'The New York Fed is not responsible for publication of these reference rate data by R1000 research, '
    'does not sanction or endorse any particular republication, and has no liability for your use. '
    'R1000 research is not affiliated with the New York Fed. The New York Fed does not sanction, '
    'endorse, or recommend any products or services offered by R1000 research. '
    'SOFR data are calculated using data provided under a license granted to the New York Fed by '
    'DTCC Solutions LLC, an affiliate of The Depository Trust & Clearing Corporation. '
    'DTCC Solutions LLC, its affiliates, and their data suppliers have no liability for this material. '
    'Derived calculations are R1000 research modifications, not New York Fed publications.'
)


def notices():
    return ['Source: Board of Governors of the Federal Reserve System; https://www.federalreserve.gov/disclaimer.htm',
            NYFED_NOTICE+' https://www.newyorkfed.org/privacy/termsofuse']
# Compatibility aliases identify the existing A4 semantic register. Provider
# and native_series_id always identify the actual Board original, never FRED.
H41 = {
    'RESPPA_N.WW': ('WALCL', 'fed_assets', 'L', 'TA', 'WEDNESDAY_LEVEL'),
    'RESH4R_XAW_N.WW': ('WRESBAL', 'reserves_week_average', 'A', 'RBFRB', 'WEEK_AVERAGE'),
    'RESPPLLDT_XAW_N.WW': ('WTREGEN', 'tga_week_average', 'A', 'DEPUSTG', 'WEEK_AVERAGE'),
    'RESPPLLDT_N.WW': ('WDTGAL', 'tga_wednesday', 'L', 'DEPUSTG', 'WEDNESDAY_LEVEL'),
    'RESPPLLR_XAW_N.WW': ('H41_RRP_TOTAL_AVG', 'rrp_total_week_average', 'A', 'RRP', 'WEEK_AVERAGE'),
    'RESPPLLRF_XAW_N.WW': ('H41_RRP_FOREIGN_AVG', 'rrp_foreign_week_average', 'A', 'RRPF', 'WEEK_AVERAGE'),
    'RESPPLLRD_XAW_N.WW': ('H41_RRP_OTHER_AVG', 'rrp_other_week_average', 'A', 'RRPO', 'WEEK_AVERAGE'),
}
H8 = {
    ('1058', 'CB'): ('DPSACBW027SBOG', 'deposits_all'),
    ('1058', 'DM'): ('DPSDCBW027SBOG', 'deposits_domestic'),
    ('1058', 'LG'): ('DPSLCBW027SBOG', 'deposits_large'),
    ('1058', 'SM'): ('DPSSCBW027SBOG', 'deposits_small'),
    ('1020', 'CB'): ('TOTLL', 'loans_all'),
    ('1023', 'CB'): ('TOTCI', 'commercial_industrial_loans'),
    ('1048', 'CB'): ('CASACBW027SBOG', 'cash_assets_all'),
    ('1151', 'CB'): ('TLAACBW027SBOG', 'bank_assets_all'),
}
for _item, _metric in (('1020', 'loans'), ('1023', 'commercial_industrial_loans'),
                       ('1048', 'cash_assets'), ('1151', 'bank_assets')):
    for _bg, _scope in (('DM', 'domestic'), ('LG', 'large'), ('SM', 'small')):
        H8[(_item, _bg)] = ('H8_' + _item + '_' + _bg, _metric + '_' + _scope)


def check(condition, code):
    f.require(condition, code)


def now():
    return datetime.now(timezone.utc).isoformat()


class SafeXML:
    """Charge actual decompression and reject DTD/entity declarations in-stream."""
    def __init__(self, stream, limit):
        self.stream, self.remaining, self.tail = stream, limit, b''

    def read(self, size=-1):
        size = min(65536 if size < 0 else size, self.remaining + 1)
        raw = self.stream.read(size)
        check(len(raw) <= self.remaining, 'PRIMARY_XML_BYTE_BUDGET')
        self.remaining -= len(raw)
        scan = self.tail + raw.upper()
        check(b'\0' not in raw and b'<!DOCTYPE' not in scan and b'<!ENTITY' not in scan, 'PRIMARY_XML_DECLARATION')
        self.tail = scan[-16:]
        return raw


def _local(tag):
    return tag.rsplit('}', 1)[-1]


def _identity(feed, attrs):
    name = attrs.get('SERIES_NAME')
    if feed == 'h41' and name in H41:
        alias, logical, kind, component, basis = H41[name]
        check(attrs.get('SERIESTYPE') == kind and attrs.get('COMPONENT') == component
              and attrs.get('DISTRIBUTION') == 'TOT', 'PRIMARY_SERIES_IDENTITY')
        info = alias, logical, 'millions_usd', 'weekly', basis, 'NSA', 'LIQUIDITY', 14, Decimal(1)
    elif feed == 'h8' and (attrs.get('ITEM'), attrs.get('BG')) in H8:
        if attrs.get('FREQ') != '19' or attrs.get('SA') != 'SA' or attrs.get('H8_UNITS') != 'LEVEL':
            return None
        alias, logical = H8[(attrs['ITEM'], attrs['BG'])]
        expected = 'B' + attrs['ITEM'] + 'N' + attrs['BG'] + 'A'
        check(name == expected, 'PRIMARY_SERIES_IDENTITY')
        info = alias, logical, 'billions_usd', 'weekly', 'WEDNESDAY_LEVEL', 'SA', 'BANK_CREDIT', 16, Decimal(1000)
    elif feed == 'prates' and name == 'RESBM_N.D':
        check(attrs.get('FREQ') == '8' and attrs.get('UNIT') == 'Percent'
              and attrs.get('UNIT_MULT') == '1' and attrs.get('CURRENCY') == 'NA', 'PRIMARY_SERIES_IDENTITY')
        return ('IORB', 'iorb', 'percent', 'daily', 'ADMINISTERED_RATE', 'NSA', 'FUNDING', 5, Decimal(1))
    else:
        return None
    check(attrs.get('FREQ') == '19' and attrs.get('UNIT') == 'Currency'
          and attrs.get('UNIT_MULT') == '1000000' and attrs.get('CURRENCY') == 'USD', 'PRIMARY_SERIES_UNITS')
    return info


def semantic_register():
    result = {'IORB': ('iorb', 'percent', 'daily', 'ADMINISTERED_RATE', 'NSA', 'FUNDING', 5)}
    for _, (alias, logical, _, _, basis) in H41.items():
        result[alias] = (logical, 'millions_usd', 'weekly', basis, 'NSA', 'LIQUIDITY', 14)
    for alias, logical in H8.values():
        result[alias] = (logical, 'billions_usd', 'weekly', 'WEDNESDAY_LEVEL', 'SA', 'BANK_CREDIT', 16)
    return result


def normalize(raw, feed, *, collected_at, start='1996-01-01', through=None):
    check(feed in FEEDS and type(raw) is bytes and 0 < len(raw) <= MAX_ORIGINAL, 'PRIMARY_ARCHIVE_SCOPE')
    collected = clock(collected_at)
    start_day = day(start)
    through_day = day(through) if through is not None else collected.date()
    check(start_day <= through_day <= collected.date(), 'PRIMARY_OBSERVATION_WINDOW')
    if feed in {'sofr', 'tgcr', 'effr'}:
        from tools.a4_liquidity_analysis import parse_original
        rows = parse_original(raw, dict(source_id='nyfed:'+feed.upper(), collected_at=collected_at))
        rows = [r for r in rows if start_day <= day(r['observation_date']) <= through_day]
        check(bool(rows), 'PRIMARY_REQUIRED_SERIES_MISSING')
        return rows, dict(feed=feed, original_sha256=digest(raw), normalized_sha256=digest(encoded(rows)),
            original_bytes=len(raw), decoded_xml_bytes=0, observations=len(rows), series=[feed.upper()],
            first_observation=rows[0]['observation_date'], last_observation=rows[-1]['observation_date'],
            requested_start=start, requested_through=through_day.isoformat(), collected_at=collected_at,
            source_uri=FEEDS[feed][0], rights_uri='https://www.newyorkfed.org/privacy/termsofuse',
            provider='FEDERAL_RESERVE_BANK_OF_NEW_YORK', historical_pit_certified=False,
            training_admitted=False, source_admitted=False)
    output, seen_series, inspected, expanded, retained = [], set(), 0, 0, len(raw)
    original_sha = digest(raw)
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            members = archive.infolist()
            names = [x.filename for x in members]
            check(0 < len(members) <= 8 and len(set(names)) == len(names), 'PRIMARY_ARCHIVE_INVENTORY')
            check(all(re.fullmatch(r'[A-Za-z0-9_]+\.(xml|xsd)', x.filename)
                      and not stat.S_ISLNK(x.external_attr >> 16) and not x.flag_bits & 1
                      and 0 < x.file_size <= MAX_EXPANDED for x in members), 'PRIMARY_ARCHIVE_INVENTORY')
            check(sum(x.file_size for x in members) <= MAX_EXPANDED, 'PRIMARY_XML_BYTE_BUDGET')
            _, data_name, structure_name = FEEDS[feed]
            check(data_name in names and structure_name in names, 'PRIMARY_ARCHIVE_IDENTITY')
            with archive.open(data_name) as stream:
                reader = SafeXML(stream, MAX_EXPANDED)
                stack, identity, series, last_day, nodes = [], None, None, None, 0
                for event, element in ET.iterparse(reader, events=('start', 'end')):
                    tag = _local(element.tag)
                    if event == 'start':
                        stack.append(element); nodes += 1
                        check(len(stack) <= 12 and nodes <= 2000000, 'PRIMARY_XML_NODE_BUDGET')
                        if tag != 'Series':
                            continue
                        check(series is None, 'PRIMARY_NESTED_SERIES')
                        series = element
                        inspected += 1
                        check(inspected <= MAX_SERIES, 'PRIMARY_SERIES_BUDGET')
                        identity = _identity(feed, element.attrib)
                        last_day = None
                        if identity is None:
                            continue
                        alias, logical, unit, frequency, basis, seasonal, family, age, divisor = identity
                        check(alias not in seen_series, 'PRIMARY_DUPLICATE_SERIES')
                        seen_series.add(alias)
                    else:
                        if tag == 'Obs' and identity is not None:
                            check(len(stack) >= 2 and stack[-2] is series, 'PRIMARY_OBSERVATION_PARENT')
                            observed = day(element.get('TIME_PERIOD'))
                            check(last_day is None or last_day < observed, 'PRIMARY_OBSERVATION_ORDER')
                            last_day = observed
                        if tag == 'Obs' and identity is not None and start_day <= observed <= through_day:
                            value = None
                            status = element.get('OBS_STATUS')
                            check(status in {'A', 'NA', 'ND', 'NC', 'E', 'P'}, 'PRIMARY_OBSERVATION_STATUS')
                            text = element.get('OBS_VALUE')
                            if status in {'A', 'E', 'P'} and text not in (None, '', 'ND', 'NA', 'NC'):
                                try:
                                    amount = Decimal(text) / divisor
                                except InvalidOperation:
                                    raise ValueError('PRIMARY_OBSERVATION_VALUE') from None
                                check(amount.is_finite() and amount >= 0, 'PRIMARY_OBSERVATION_VALUE')
                                value = float(amount)
                                f.number(value)
                            row = dict(source_id='frb:' + alias, logical_id=logical,
                                native_series_id=series.get('SERIES_NAME'), native_observation_status=status,
                                observation_date=observed.isoformat(), value=value, unit=unit,
                                frequency=frequency, measurement_basis=basis, seasonal_basis=seasonal,
                                family=family, max_age_days=age, original_sha256=original_sha,
                                collected_at=collected_at, available_at=collected_at, published_at=None,
                                truth_class='PRIMARY_CURRENT_VINTAGE', historical_pit_certified=False,
                                native_unit_multiplier=series.get('UNIT_MULT'),
                                bank_aggregation=series.get('BG'))
                            retained += 128 + sys.getsizeof(row) + sum(sys.getsizeof(k)+sys.getsizeof(v) for k,v in row.items())
                            check(retained <= MAX_TOTAL, 'PRIMARY_RETAINED_BYTE_BUDGET')
                            output.append(row)
                            check(len(output) <= MAX_ROWS, 'PRIMARY_ROW_BUDGET')
                        if tag == 'Series':
                            identity, series = None, None
                        if tag in {'Obs', 'Series'}:
                            element.clear()
                            if len(stack) > 1:
                                stack[-2].remove(element)
                        stack.pop()
                expanded += MAX_EXPANDED - reader.remaining
    except (zipfile.BadZipFile, ET.ParseError, RuntimeError):
        raise ValueError('PRIMARY_ARCHIVE_INVALID') from None
    expected = set(H41[x][0] for x in H41) if feed == 'h41' else set(x[0] for x in H8.values()) if feed == 'h8' else {'IORB'}
    check(seen_series == expected and {r['source_id'][4:] for r in output} == expected, 'PRIMARY_REQUIRED_SERIES_MISSING')
    output.sort(key=lambda r: (r['source_id'], r['observation_date']))
    normalized_sha = digest(encoded(output))
    for row in output:
        row['normalized_sha256'] = normalized_sha
    return output, dict(feed=feed, original_sha256=original_sha, normalized_sha256=normalized_sha,
        original_bytes=len(raw), decoded_xml_bytes=expanded, observations=len(output),
        series=sorted(seen_series), first_observation=min(r['observation_date'] for r in output),
        last_observation=max(r['observation_date'] for r in output), requested_start=start,
        requested_through=through_day.isoformat(), collected_at=collected_at,
        source_uri=FEEDS[feed][0], rights_uri=RIGHTS_URI, provider='FEDERAL_RESERVE_BOARD',
        historical_pit_certified=False, training_admitted=False, source_admitted=False)


def capture(feed, *, fetcher=None):
    """One fixed-origin GET. No redirect, credentials, arbitrary URL or retry."""
    check(feed in FEEDS, 'PRIMARY_FEED')
    if fetcher is not None:
        raw = fetcher(FEEDS[feed][0], MAX_ORIGINAL)
    else:
        with build_opener(NoRedirect()).open(Request(FEEDS[feed][0], headers={
                'User-Agent': 'r1000-primary-macro-research/1.0',
                'Accept': 'application/json' if feed in {'sofr', 'tgcr', 'effr'} else
                          'application/x-zip-compressed, application/zip, application/octet-stream'}), timeout=30) as response:
            check(response.status == 200, 'PRIMARY_HTTP_STATUS')
            raw = response.read(MAX_ORIGINAL + 1)
    check(type(raw) is bytes and 0 < len(raw) <= MAX_ORIGINAL, 'PRIMARY_ORIGINAL_BYTE_BUDGET')
    return raw, now()


def _normalized_lines(rows):
    total = 0
    for row in rows:
        line = encoded(row); total += len(line)
        check(len(line) <= MAX_LINE_BYTES and total <= MAX_NORMALIZED_BYTES, 'PRIMARY_NORMALIZED_DECODED_BUDGET')
        yield line


def _capture_manifest(receipt, normalized):
    manifest = dict(schema=SCHEMA, **receipt, source_notices=notices(), normalizer_sha256=digest(Path(__file__).read_bytes()),
                    normalized_object_sha256=digest(normalized), normalized_object_bytes=len(normalized),
                    fullrun_executed=False, accepted_state_written=False)
    return manifest


def prepare(raw, feed, *, collected_at, start='1996-01-01', through=None):
    rows, receipt = normalize(raw, feed, collected_at=collected_at, start=start, through=through)
    buffer = io.BytesIO()
    # GzipFile fixes the OS header byte across Python3.12/3.14. Reader replay
    # compares canonical decompressed rows, not a recompressed zlib encoding.
    with gzip.GzipFile(fileobj=buffer, mode='wb', filename='', mtime=0, compresslevel=6) as stream:
        for line in _normalized_lines(rows): stream.write(line)
    normalized = buffer.getvalue()
    check(len(normalized) <= MAX_ORIGINAL, 'PRIMARY_NORMALIZED_BYTE_BUDGET')
    manifest = _capture_manifest(receipt, normalized)
    manifest_raw = encoded(manifest)
    files = {f'objects/{digest(raw)}': raw, f'objects/{digest(normalized)}': normalized,
             f'generations/{digest(manifest_raw)}.json': manifest_raw}
    return rows, manifest, files


def store_capture(root, raw, feed, *, collected_at, start='1996-01-01', through=None):
    """Content-addressed, create-only local preparation before durable transfer."""
    _, manifest, files = prepare(raw, feed, collected_at=collected_at, start=start, through=through)
    root = Path(root)
    check(not any(p.is_symlink() for p in (root, *root.parents)), 'PRIMARY_OUTPUT_SYMLINK')
    for name, body in files.items():
        path = root / name
        check(not any(p.is_symlink() for p in (path, *path.parents)), 'PRIMARY_OUTPUT_SYMLINK')
        check(not path.exists() or _bounded(path, MAX_ORIGINAL) == body, 'PRIMARY_OUTPUT_CONFLICT')
    for name, body in files.items():
        path = root / name
        if not path.exists():
            exclusive(path, body)
        check(_bounded(path, MAX_ORIGINAL) == body, 'PRIMARY_OUTPUT_READBACK')
    return dict(manifest=manifest, generation_sha256=digest(encoded(manifest)), files=sorted(files))


def _bounded(path, limit):
    from tools.market_analysis_engine import bounded
    return bounded(path, limit)


def read_generation(transport, generation_sha256, *, cutoff):
    """Shared Reader byte checks plus original re-normalization; research only.

    A capture manifest is not a Lake execution receipt, source admission, a
    historical PIT binding or an accepted model. No latest-head fallback.
    """
    check(type(generation_sha256) is str and re.fullmatch('[a-f0-9]{64}', generation_sha256), 'PRIMARY_GENERATION_PIN')
    raw_manifest = read_object(transport, PREFIX+'/generations/'+generation_sha256+'.json', generation_sha256, 65536)
    manifest = f.strict_json(raw_manifest)
    check(type(manifest) is dict and manifest.get('schema') == SCHEMA, 'PRIMARY_GENERATION_SCHEMA')
    check(clock(manifest['collected_at']) <= clock(cutoff), 'PRIMARY_FUTURE_CAPTURE')
    original = read_object(transport, PREFIX+'/objects/'+manifest['original_sha256'], manifest['original_sha256'], MAX_ORIGINAL)
    normalized = read_object(transport, PREFIX+'/objects/'+manifest['normalized_object_sha256'], manifest['normalized_object_sha256'], MAX_ORIGINAL)
    rows, receipt = normalize(original, manifest['feed'], collected_at=manifest['collected_at'],
                              start=manifest['requested_start'], through=manifest['requested_through'])
    replay = _capture_manifest(receipt, normalized)
    check(replay == manifest and encoded(replay) == raw_manifest, 'PRIMARY_NORMALIZATION_REPLAY')
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(normalized), mode='rb') as stream:
            for expected in _normalized_lines(rows):
                check(stream.readline(MAX_LINE_BYTES+1) == expected, 'PRIMARY_NORMALIZATION_REPLAY')
            check(stream.read(1) == b'', 'PRIMARY_NORMALIZATION_REPLAY')
    except (OSError, EOFError, zlib.error):
        raise ValueError('PRIMARY_NORMALIZATION_REPLAY') from None
    return rows, manifest


def publish_capture(transport, root, generation_sha256, *, cutoff):
    """Publish data before manifest, reread every original and normalized byte."""
    from tools.macro_research_checkpoint import LocalTransport
    class PreparedTransport(LocalTransport):
        def read(self, path):
            check(path.startswith(PREFIX+'/'), 'PRIMARY_PREPARED_PATH')
            return super().read(path[len(PREFIX)+1:])
    local = PreparedTransport(root)
    _, manifest = read_generation(local, generation_sha256, cutoff=cutoff)
    names = ['objects/'+manifest['original_sha256'], 'objects/'+manifest['normalized_object_sha256'],
             'generations/'+generation_sha256+'.json']
    for name in names:
        body = _bounded(Path(root)/name, MAX_ORIGINAL)
        transport.write(PREFIX+'/'+name, body)
        check(read_object(transport, PREFIX+'/'+name, digest(body), MAX_ORIGINAL) == body, 'PRIMARY_DURABLE_READBACK')
    rows, checked = read_generation(transport, generation_sha256, cutoff=cutoff)
    return dict(generation_sha256=generation_sha256, observations=len(rows),
                original_sha256=checked['original_sha256'], original_bytes=checked['original_bytes'],
                transport_readback_verified=transport.remote_verified is True,
                source_admitted=False, historical_pit_certified=False, training_admitted=False)
