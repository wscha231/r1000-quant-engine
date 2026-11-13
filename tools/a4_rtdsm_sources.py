"""Philadelphia Fed dated-vintage research, never an exact release-time feed.

Offline original replay shares A4's immutable archive and bounded Reader. A
vintage boundary is a conservative research availability bound, not a claimed
publication timestamp, Source admission or permission to train on prices.
"""
from __future__ import annotations

from collections import deque
from datetime import date, datetime
import gzip
import io
from pathlib import Path
import re
import stat
import xml.etree.ElementTree as ET
import zipfile
import zlib
from zoneinfo import ZoneInfo

from tools import a4_primary_sources as p
from tools.macro_history_sources import digest, encoded, exclusive
from tools.macro_research_checkpoint import LocalTransport

SCHEMA = 'a4-rtdsm-vintage-bundle-v1'
MAX_RAW = 8 * 1024**2
MAX_EXPANDED = 64 * 1024**2
MAX_CELLS = 1_000_000
TAIL_MONTHS = 24
BASE = 'https://www.philadelphiafed.org/-/media/FRBP/Assets/Surveys-And-Data/real-time-data/data-files/'
RIGHTS_URI = 'https://www.philadelphiafed.org/about-us/privacy-notice'
FEEDS = {
    'rtdsm_employ': ('EMPLOY', 'employMvMd.xlsx', 'A6D136FEA6973CAB4E1B80A58725AFC1',
        'EMPLOY/specific_documentation_employ.pdf', '75f5435121701d0c8731d27a165e214bb0f37ddde52b869fc8bc9e5117fef139'),
    'rtdsm_pcpi': ('PCPI', 'pcpiMvMd.xlsx', 'E41A743DC6423F950B10C3DE7A4F674D',
        'PCPI/Specific_Documentation_PCPI.pdf', 'e843206d329ff0913580f5fe2161089a593b1b4cd4f0612dbaa852b2dc67acde'),
    'rtdsm_ruc': ('RUC', 'rucQvMd.xlsx', 'A96BC0C2253B04EAEB8C4DC42D4F5CBA',
        'RUC/specific_documentation_RUC.pdf', 'e8121b567946d81e7a9e439ed37f8369548d0ecfa5bcf4986b51877420f4c721'),
}
MAIN = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
RELS = 'http://schemas.openxmlformats.org/package/2006/relationships'
SAFETY = dict(source_admitted=False, historical_pit_certified=False, training_admitted=False,
    automatic_promotion_allowed=False, accepted_state_written=False, orders_generated=False)
LOADED_NORMALIZER_SHA256 = digest(Path(__file__).read_bytes())
LOADED_SHARED_CODEC_SHA256 = digest(Path(p.__file__).read_bytes())


def register():
    return {
        'EMPLOY': ('payrolls', 'thousands_persons', 'monthly', 'PERIOD_OBSERVATION', 'SA', 'GROWTH', 90),
        'PCPI': ('cpi', 'index', 'monthly', 'PERIOD_OBSERVATION', 'SA', 'INFLATION', 90),
        'RUC': ('unemployment', 'percent', 'monthly', 'PERIOD_OBSERVATION', 'SA', 'GROWTH', 150),
    }


def source_uri(feed):
    p.check(feed in FEEDS, 'RTDSM_FEED')
    _, name, tag, _, _ = FEEDS[feed]
    return BASE+'xlsx/'+name+'?hash='+tag+'&sc_lang=en'


def vintage_boundary(label, alias):
    """No guessed first-Friday or 08:30 release clock; preserve source precision."""
    m = re.fullmatch(re.escape(alias)+r'([0-9]{2})([MQ])([0-9]{1,2})', label)
    p.check(m is not None, 'RTDSM_VINTAGE_LABEL')
    yy, kind, period = int(m[1]), m[2], int(m[3])
    year = 2000+yy if yy <= 35 else 1900+yy
    p.check(1964 <= year <= 2035 and kind == ('Q' if alias == 'RUC' else 'M'), 'RTDSM_VINTAGE_FREQUENCY')
    if kind == 'M':
        p.check(1 <= period <= 12, 'RTDSM_VINTAGE_PERIOD')
        month = period
        bound = date(year+int(month == 12), 1 if month == 12 else month+1, 1)
        basis = 'CONSERVATIVE_VINTAGE_MONTH_END_BOUND'
    else:
        p.check(1 <= period <= 4, 'RTDSM_VINTAGE_PERIOD')
        month = period*3-1
        bound = date(year, month, 16)  # documented Feb/May/Aug/Nov15, after that day
        basis = 'CONSERVATIVE_DOCUMENTED_VINTAGE_DAY_END_BOUND'
    expected = date(year-int(month == 1), 12 if month == 1 else month-1, 1)
    clock = datetime.combine(bound, datetime.min.time(), ZoneInfo('America/New_York')).isoformat()
    return date(year, month, 1), expected, clock, basis, ('quarterly' if kind == 'Q' else 'monthly')


def _xml(archive, name, limit=2*1024**2):
    with archive.open(name) as stream:
        return ET.parse(p.SafeXML(stream, limit)).getroot()


def _column(ref, row):
    m = re.fullmatch(r'([A-Z]{1,3})([1-9][0-9]{0,3})', ref or '')
    p.check(m is not None and int(m[2]) == row, 'RTDSM_CELL_REFERENCE')
    n = 0
    for c in m[1]: n = n*26+ord(c)-64
    p.check(n <= 1024, 'RTDSM_COLUMN_BUDGET')
    return n


def _cells(row, strings, number):
    result = {}; last = 0
    for cell in row:
        p.check(cell.tag == '{'+MAIN+'}c' and cell.find('{'+MAIN+'}f') is None, 'RTDSM_FORMULA_OR_CELL')
        col = _column(cell.get('r'), number)
        p.check(col > last, 'RTDSM_CELL_ORDER'); last = col
        value = cell.find('{'+MAIN+'}v'); text = '' if value is None else value.text or ''
        kind = cell.get('t')
        p.check(kind in {None, 'n', 's', 'e'} and len(text) <= 128, 'RTDSM_CELL_TYPE')
        if kind == 's':
            p.check(text.isdigit() and int(text) < len(strings), 'RTDSM_SHARED_STRING_REFERENCE')
            text = strings[int(text)]
        if kind == 'e': p.check(text == '#N/A', 'RTDSM_CELL_ERROR')
        result[col] = text
    return result


def _matrix(raw, feed, first, last, collected):
    alias = FEEDS[feed][0]; retained = {}; headers = {}; grid = set(); previous = None
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        members = archive.infolist(); names = [m.filename for m in members]
        allowed = r'(\[Content_Types\]\.xml|_rels/\.rels|docProps/[A-Za-z]+\.xml|xl/(workbook\.xml|sharedStrings\.xml|styles\.xml|_rels/workbook\.xml\.rels|theme/theme1\.xml|worksheets/sheet1\.xml|worksheets/_rels/sheet1\.xml\.rels))'
        p.check(0 < len(members) <= 16 and len(names) == len(set(names)) and
            all(re.fullmatch(allowed, m.filename) and not m.flag_bits & 1 and not stat.S_ISLNK(m.external_attr >> 16)
                and 0 < m.file_size <= MAX_EXPANDED for m in members) and
            sum(m.file_size for m in members) <= MAX_EXPANDED, 'RTDSM_ZIP_INVENTORY')
        p.check({'xl/workbook.xml', 'xl/sharedStrings.xml', 'xl/worksheets/sheet1.xml',
            'xl/_rels/workbook.xml.rels'} <= set(names), 'RTDSM_REQUIRED_PARTS')
        for name in names:
            if name.endswith('.rels'):
                rel = _xml(archive, name)
                p.check(rel.tag == '{'+RELS+'}Relationships' and
                    all(e.get('TargetMode') in {None, 'Internal'} and not (e.get('Target') or '').startswith(('/', '..', 'http', '\\'))
                        for e in rel), 'RTDSM_EXTERNAL_RELATIONSHIP')
        book = _xml(archive, 'xl/workbook.xml')
        sheets = list(book.iter('{'+MAIN+'}sheet'))
        p.check(len(sheets) == 1 and sheets[0].get('name') == alias.lower()
            and sheets[0].get('state', 'visible') == 'visible', 'RTDSM_SHEET_IDENTITY')
        rid = sheets[0].get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id')
        links = [e for e in _xml(archive, 'xl/_rels/workbook.xml.rels') if e.get('Id') == rid]
        p.check(len(links) == 1 and links[0].get('Target') == 'worksheets/sheet1.xml', 'RTDSM_SHEET_RELATIONSHIP')
        shared = _xml(archive, 'xl/sharedStrings.xml')
        strings = [''.join(e.itertext()) for e in shared]
        p.check(shared.tag == '{'+MAIN+'}sst' and len(strings) <= 10000 and
            all(len(s) <= 128 for s in strings), 'RTDSM_STRING_BUDGET')
        count = 0; row_number = 0; nodes = 0; stack = []; sheet_data = 0
        with archive.open('xl/worksheets/sheet1.xml') as stream:
            for event, row in ET.iterparse(p.SafeXML(stream, MAX_EXPANDED), events=('start','end')):
                if event == 'start':
                    stack.append(row.tag); nodes += 1
                    p.check(len(stack) <= 12 and nodes <= 3_000_000, 'RTDSM_XML_NODE_BUDGET')
                    if len(stack) == 1: p.check(row.tag == '{'+MAIN+'}worksheet', 'RTDSM_WORKSHEET_ROOT')
                    if row.tag == '{'+MAIN+'}sheetData':
                        sheet_data += 1
                        p.check(len(stack) == 2 and sheet_data == 1, 'RTDSM_SHEET_DATA_PARENT')
                    continue
                parent = stack[-2] if len(stack) > 1 else None; stack.pop()
                if row.tag != '{'+MAIN+'}row': continue
                p.check(parent == '{'+MAIN+'}sheetData', 'RTDSM_ROW_PARENT')
                number = int(row.get('r', '0'))
                p.check(row_number < number <= 2000, 'RTDSM_ROW_ORDER'); row_number = number
                count += len(row); p.check(count <= MAX_CELLS, 'RTDSM_CELL_BUDGET')
                cells = _cells(row, strings, number); row.clear()
                if not cells: continue  # published files contain one empty formatting row
                if not headers:
                    p.check(number == 1 and cells.get(1) == 'DATE' and len(cells) >= 2, 'RTDSM_HEADER')
                    labels = list(cells.values())[1:]
                    p.check(list(cells) == list(range(1, len(cells)+1)) and len(labels) == len(set(labels)), 'RTDSM_HEADER_COLUMNS')
                    prior = None
                    for col, label in list(cells.items())[1:]:
                        vintage, expected, available, basis, frequency = vintage_boundary(label, alias)
                        p.check(prior is None or prior < vintage, 'RTDSM_VINTAGE_ORDER'); prior = vintage
                        headers[col] = (label, vintage, expected, available, basis, frequency)
                        if first <= vintage <= last and p.clock(available) <= collected:
                            retained[col] = deque(maxlen=TAIL_MONTHS)
                    continue
                text = cells.get(1, '')
                p.check(re.fullmatch(r'[0-9]{4}:(0[1-9]|1[0-2])', text) is not None, 'RTDSM_OBSERVATION_PERIOD')
                observed = date(int(text[:4]), int(text[-2:]), 1)
                p.check(previous is None or observed == date(previous.year+int(previous.month == 12),
                    1 if previous.month == 12 else previous.month+1, 1), 'RTDSM_OBSERVATION_GRID')
                previous = observed; grid.add(observed)
                p.check(set(cells) <= {1, *headers}, 'RTDSM_UNREGISTERED_COLUMN')
                for col, history in retained.items():
                    if observed > headers[col][2]: continue
                    text = cells.get(col, '')
                    value = None if text in {'', '#N/A', 'NA'} else p.f.number(text)
                    p.check(value is None or (0 <= value <= 100 if alias == 'RUC' else value > 0), 'RTDSM_VALUE')
                    history.append((observed.isoformat(), value))
        p.check(headers and retained and all(h and headers[c][2] in grid and
            h[-1][0] == headers[c][2].isoformat() for c, h in retained.items()), 'RTDSM_VINTAGE_REFERENCE_GRID')
    return alias, headers, retained


def normalize(raw, feed, *, collected_at, start='1998-11-01', through=None):
    p.check(digest(Path(__file__).read_bytes()) == LOADED_NORMALIZER_SHA256 and
        digest(Path(p.__file__).read_bytes()) == LOADED_SHARED_CODEC_SHA256, 'RTDSM_LOADED_CODE_CHANGED')
    p.check(feed in FEEDS and type(raw) is bytes and 0 < len(raw) <= MAX_RAW, 'RTDSM_ORIGINAL_BUDGET')
    collected = p.clock(collected_at); first = p.day(start); last = p.day(through) if through else collected.date()
    p.check(date(1964, 1, 1) <= first <= last <= collected.date(), 'RTDSM_VINTAGE_WINDOW')
    try: alias, headers, histories = _matrix(raw, feed, first, last, collected)
    except (zipfile.BadZipFile, ET.ParseError, RuntimeError, OverflowError):
        raise ValueError('RTDSM_ORIGINAL_INVALID') from None
    rows = []; spec = register()[alias]; original = digest(raw)
    for col, history in histories.items():
        label, vintage, _, available, basis, frequency = headers[col]
        for observed, value in history:
            rows.append(dict(source_id='rtdsm:'+alias, logical_id=spec[0], observation_date=observed,
                value=value, unit=spec[1], frequency=spec[2], measurement_basis=spec[3], seasonal_basis=spec[4],
                family=spec[5], max_age_days=spec[6], original_sha256=original, collected_at=collected_at,
                available_at=available, published_at=None, vintage_label=label, vintage_reference_month=vintage.isoformat(),
                documented_vintage_date=date(vintage.year, vintage.month, 15).isoformat() if frequency == 'quarterly' else None,
                vintage_frequency=frequency, availability_basis=basis, documentation_sha256=FEEDS[feed][4],
                native_value_status='MISSING' if value is None else 'OBSERVED',
                truth_class='DATED_VINTAGE_RESEARCH_CONSERVATIVE_BOUND', historical_pit_certified=False))
    p.check(0 < len(rows) <= 30000, 'RTDSM_OBSERVATION_BUDGET')
    rows.sort(key=lambda r: (p.clock(r['available_at']), r['observation_date']))
    normalized_sha = digest(encoded(rows))
    for row in rows: row['normalized_sha256'] = normalized_sha
    receipt = dict(feed=feed, original_sha256=original, original_bytes=len(raw), normalized_sha256=normalized_sha,
        collected_at=collected_at, requested_start=start, requested_through=last.isoformat(),
        source_uri=source_uri(feed), documentation_uri=BASE+FEEDS[feed][3], documentation_sha256=FEEDS[feed][4],
        observations=len(rows), vintages=len(histories), retained_months_per_vintage=TAIL_MONTHS,
        first_vintage_month=min(r['vintage_reference_month'] for r in rows), last_vintage_month=max(r['vintage_reference_month'] for r in rows),
        first_observation=min(r['observation_date'] for r in rows), last_observation=max(r['observation_date'] for r in rows),
        first_available_at=rows[0]['available_at'], last_available_at=rows[-1]['available_at'],
        historical_use='DATE_ARCHIVE_RESEARCH_ONLY', publication_time_verified=False,
        caveat='Archive methodology and corrections are retained; bounds are not original release instants or first-release values.',
        attribution='Source: Federal Reserve Bank of Philadelphia RTDSM; research calculations and availability bounds are R1000 modifications.',
        **SAFETY)
    return rows, receipt


def _manifest(receipt, normalized, rights):
    return dict(receipt, schema=SCHEMA, normalized_object_sha256=digest(normalized),
        normalized_bytes=len(normalized), rights_notice_sha256=digest(rights), rights_uri=RIGHTS_URI,
        normalizer_sha256=LOADED_NORMALIZER_SHA256, shared_codec_sha256=LOADED_SHARED_CODEC_SHA256)


def store_capture(root, raw, feed, *, documentation_raw, rights_raw, **window):
    rows, receipt = normalize(raw, feed, **window)
    p.check(type(documentation_raw) is bytes and digest(documentation_raw) == receipt['documentation_sha256'], 'RTDSM_DOCUMENTATION_PIN')
    p.check(type(rights_raw) is bytes and 0 < len(rights_raw) <= 256*1024, 'RTDSM_RIGHTS_NOTICE_BUDGET')
    buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=buffer, mode='wb', filename='', mtime=0, compresslevel=6) as stream:
        for line in p._normalized_lines(rows): stream.write(line)
    normalized = buffer.getvalue(); p.check(len(normalized) <= MAX_RAW, 'RTDSM_NORMALIZED_BUDGET')
    manifest = _manifest(receipt, normalized, rights_raw); generation = digest(encoded(manifest))
    files = {'objects/'+digest(body): body for body in (raw, documentation_raw, rights_raw, normalized)}
    files['generations/'+generation+'.json'] = encoded(manifest)
    root = Path(root)
    p.check(not any(q.is_symlink() for q in (root, *root.parents)), 'RTDSM_OUTPUT_SYMLINK')
    for name, body in files.items():
        path = root/name
        p.check(not any(q.is_symlink() for q in (path, *path.parents)) and
            (not path.exists() or p._bounded(path, MAX_RAW) == body), 'RTDSM_OUTPUT_CONFLICT')
    for name, body in files.items():
        if not (root/name).exists(): exclusive(root/name, body)
    return dict(manifest=manifest, generation_sha256=generation)


def read_generation(transport, generation_sha256, *, cutoff):
    p.check(type(generation_sha256) is str and re.fullmatch('[a-f0-9]{64}', generation_sha256), 'RTDSM_GENERATION_PIN')
    raw = p.read_object(transport, p.PREFIX+'/generations/'+generation_sha256+'.json', generation_sha256, 65536)
    manifest = p.f.strict_json(raw)
    p.check(manifest.get('schema') == SCHEMA and manifest.get('feed') in FEEDS, 'RTDSM_GENERATION_SCHEMA')
    p.check(p.clock(manifest['collected_at']) <= p.clock(cutoff), 'RTDSM_FUTURE_CAPTURE')
    original = p.read_object(transport, p.PREFIX+'/objects/'+manifest['original_sha256'], manifest['original_sha256'], MAX_RAW)
    documentation = p.read_object(transport, p.PREFIX+'/objects/'+manifest['documentation_sha256'], manifest['documentation_sha256'], 1024*1024)
    rights = p.read_object(transport, p.PREFIX+'/objects/'+manifest['rights_notice_sha256'], manifest['rights_notice_sha256'], 256*1024)
    normalized = p.read_object(transport, p.PREFIX+'/objects/'+manifest['normalized_object_sha256'], manifest['normalized_object_sha256'], MAX_RAW)
    rows, receipt = normalize(original, manifest['feed'], collected_at=manifest['collected_at'],
        start=manifest['requested_start'], through=manifest['requested_through'])
    p.check(digest(documentation) == receipt['documentation_sha256'] and
        encoded(_manifest(receipt, normalized, rights)) == raw, 'RTDSM_NORMALIZATION_REPLAY')
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(normalized), mode='rb') as stream:
            for line in p._normalized_lines(rows): p.check(stream.readline(p.MAX_LINE_BYTES+1) == line, 'RTDSM_NORMALIZATION_REPLAY')
            p.check(stream.read(1) == b'', 'RTDSM_NORMALIZATION_REPLAY')
    except (OSError, EOFError, zlib.error): raise ValueError('RTDSM_NORMALIZATION_REPLAY') from None
    return rows, manifest


class PreparedReader(LocalTransport):
    def read(self, path):
        p.check(path.startswith(p.PREFIX+'/'), 'RTDSM_PREPARED_PATH')
        return super().read(path[len(p.PREFIX)+1:])


def publish_capture(transport, root, generation_sha256, *, cutoff):
    local = PreparedReader(root); _, manifest = read_generation(local, generation_sha256, cutoff=cutoff)
    hashes = [manifest[k] for k in ('original_sha256', 'documentation_sha256', 'rights_notice_sha256', 'normalized_object_sha256')]
    for name in ['objects/'+sha for sha in dict.fromkeys(hashes)]+['generations/'+generation_sha256+'.json']:
        body = p._bounded(Path(root)/name, MAX_RAW); transport.write(p.PREFIX+'/'+name, body)
        p.check(p.read_object(transport, p.PREFIX+'/'+name, digest(body), MAX_RAW) == body, 'RTDSM_DURABLE_READBACK')
    rows, _ = read_generation(transport, generation_sha256, cutoff=cutoff)
    return dict(generation_sha256=generation_sha256, observations=len(rows),
        transport_readback_verified=transport.remote_verified is True, **SAFETY)


def asof_rows(rows, cutoff):
    """Select one entire visible vintage per series; never fill from newer columns."""
    latest = {}; selected = []
    for row in rows:
        if p.clock(row['available_at']) <= p.clock(cutoff):
            latest[row['source_id']] = max(latest.get(row['source_id'], row['available_at']),
                row['available_at'], key=p.clock)
    for row in rows:
        if latest.get(row['source_id']) == row['available_at']: selected.append(row)
    return selected
