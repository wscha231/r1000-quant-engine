"""Closed RTDSM extension: offline supplied originals, no collection or admission."""
from __future__ import annotations
from collections import deque
from datetime import date,datetime
import gzip,io,re,zipfile,zlib
from pathlib import Path
from zoneinfo import ZoneInfo
from tools import a4_rtdsm_sources as legacy
from tools import a4_primary_sources as p
from tools.macro_history_sources import digest,encoded,exclusive
from tools.macro_research_checkpoint import LocalTransport
SCHEMA='a4-rtdsm-extension-bundle-v1'
MAX_RAW=legacy.MAX_RAW
MAX_EXPANDED=legacy.MAX_EXPANDED
MAX_CELLS=legacy.MAX_CELLS
MAX_DECODED=32*1024**2
TAIL_MONTHS=24
BASE=legacy.BASE
RIGHTS_URI=legacy.RIGHTS_URI
MAIN=legacy.MAIN
RELS=legacy.RELS
SAFETY=dict(legacy.SAFETY)
LOADED_NORMALIZER_SHA256=digest(Path(__file__).read_bytes())
LOADED_SHARED_CODEC_SHA256=digest(Path(p.__file__).read_bytes())
LOADED_LEGACY_CODEC_SHA256=digest(Path(legacy.__file__).read_bytes())
_xml=legacy._xml
_cells=legacy._cells
ET=legacy.ET
stat=legacy.stat
FEEDS={
 'rtdsm_ext_pcpix':('PCPIX','pcpixMvMd.xlsx','C6DFB09386E1C79B336AB19F748ADB82','PCPIX/Specific_Documentation_PCPIX.pdf','8a0f66481b817cae89944bfc5873fd0c1fae26104f72e16ed6c93d7fede43577'),
 'rtdsm_ext_ipt':('IPT','iptMvMd.xlsx','71A0CD9AD2C8828F0B041196CBFB7E5E','documentation/doc_ip.pdf','dc263f7a4a53ae1c9181f24e5a9cb5c50384daddab11fedc4a9ea4394bb4ce3e'),
 'rtdsm_ext_cut':('CUT','cutMvMd.xlsx','1E6353AB812003BAFD29709637CDABD5','documentation/doc_capu.pdf','35579984026e1e0c58ca72ed82040fee54c4496d50068e21a295f90de260f066'),
}
FIRST_VINTAGE={'PCPIX':date(1998,11,1),'IPT':date(1962,11,1),'CUT':date(1983,7,1)}

def register():
 return {'PCPIX':('core_cpi','index','monthly','PERIOD_OBSERVATION','SA','INFLATION',90),
         'IPT':('industrial_production','index','monthly','PERIOD_OBSERVATION','SA','GROWTH',90),
         'CUT':('capacity_utilization','percent','monthly','PERIOD_OBSERVATION','SA','GROWTH',90)}

def vintage_boundary(label,alias):
 p.check(alias in register(),'RTDSM_EXTENSION_ALIAS')
 match=re.fullmatch(re.escape(alias)+r'([0-9]{2})M([0-9]{1,2})',label)
 p.check(match is not None,'RTDSM_EXTENSION_MONTHLY_VINTAGE')
 year,month=int(match[1]),int(match[2]);year=2000+year if year<=35 else 1900+year
 p.check(1962<=year<=2035 and 1<=month<=12,'RTDSM_EXTENSION_VINTAGE_RANGE')
 vintage=date(year,month,1)
 p.check(FIRST_VINTAGE[alias]<=vintage,'RTDSM_EXTENSION_BEFORE_SOURCE_START')
 expected=date(year-int(month==1),12 if month==1 else month-1,1)
 bound=date(year+int(month==12),1 if month==12 else month+1,1)
 clock=datetime.combine(bound,datetime.min.time(),ZoneInfo('America/New_York')).isoformat()
 return vintage,expected,clock,'CONSERVATIVE_VINTAGE_MONTH_END_BOUND','monthly'

def _normalized_lines(rows):
 total=0
 for line in p._normalized_lines(rows):
  total+=len(line);p.check(total<=MAX_DECODED,'RTDSM_EXTENSION_DECODED_BUDGET')
  yield line


def source_uri(feed):
    p.check(feed in FEEDS, 'RTDSM_FEED')
    _, name, tag, _, _ = FEEDS[feed]
    return BASE+'xlsx/'+name+'?hash='+tag+'&sc_lang=en'

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
                    p.check(value is None or (0 <= value <= 100 if alias == 'CUT' else value > 0), 'RTDSM_VALUE')
                    history.append((observed.isoformat(), value))
        p.check(headers and retained and all(h and headers[c][2] in grid and
            h[-1][0] == headers[c][2].isoformat() for c, h in retained.items()), 'RTDSM_VINTAGE_REFERENCE_GRID')
    return alias, headers, retained

def normalize(raw, feed, *, collected_at, start='1998-11-01', through=None, capture_ref=None):
    p.check(digest(Path(__file__).read_bytes()) == LOADED_NORMALIZER_SHA256 and
        digest(Path(p.__file__).read_bytes()) == LOADED_SHARED_CODEC_SHA256 and digest(Path(legacy.__file__).read_bytes()) == LOADED_LEGACY_CODEC_SHA256, 'RTDSM_LOADED_CODE_CHANGED')
    p.check(feed in FEEDS and type(raw) is bytes and 0 < len(raw) <= MAX_RAW, 'RTDSM_ORIGINAL_BUDGET')
    collected = p.clock(collected_at); first = p.day(start); last = p.day(through) if through else collected.date()
    p.check(date(1962, 1, 1) <= first <= last <= collected.date(), 'RTDSM_VINTAGE_WINDOW')
    if capture_ref is not None:
        p.check(type(capture_ref) is dict and set(capture_ref) == {'source_uri','original_sha256','original_bytes','request_started_at','body_completed_at','http_status'}, 'RTDSM_EXTENSION_CAPTURE_REFERENCE')
        p.check(capture_ref['source_uri'] == source_uri(feed) and capture_ref['original_sha256'] == digest(raw) and capture_ref['original_bytes'] == len(raw) and type(capture_ref['original_bytes']) is int and capture_ref['http_status'] == 200, 'RTDSM_EXTENSION_CAPTURE_IDENTITY')
        p.check(p.clock(capture_ref['request_started_at']) <= p.clock(capture_ref['body_completed_at']) == collected, 'RTDSM_EXTENSION_CAPTURE_CLOCK')
    try: alias, headers, histories = _matrix(raw, feed, first, last, collected)
    except (zipfile.BadZipFile, ET.ParseError, RuntimeError, OverflowError):
        raise ValueError('RTDSM_ORIGINAL_INVALID') from None
    rows = []; spec = register()[alias]; original = digest(raw)
    for col, history in histories.items():
        label, vintage, _, available, basis, frequency = headers[col]
        for observed, value in history:
            rows.append(dict(source_id='rtdsm-ext:'+alias, logical_id=spec[0], dependency_group='G17' if alias in {'IPT','CUT'} else 'CPI', independent_signal_counted=False, value_basis='NATIVE_VINTAGE_SPECIFIC_BASE' if spec[1]=='index' else 'PERCENTAGE_POINTS', observation_date=observed,
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
        capture_ref=capture_ref, capture_clock_precision='BODY_COMPLETION_CALLER_REFERENCE' if capture_ref else 'CALLER_SUPPLIED_OFFLINE_CLOCK',
        collected_at=collected_at, requested_start=start, requested_through=last.isoformat(),
        source_uri=source_uri(feed), dependency_group='G17' if alias in {'IPT','CUT'} else 'CPI', value_basis='NATIVE_VINTAGE_SPECIFIC_BASE' if spec[1]=='index' else 'PERCENTAGE_POINTS', documentation_uri=BASE+FEEDS[feed][3], documentation_sha256=FEEDS[feed][4],
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
        normalizer_sha256=LOADED_NORMALIZER_SHA256, shared_codec_sha256=LOADED_SHARED_CODEC_SHA256,legacy_codec_sha256=LOADED_LEGACY_CODEC_SHA256)

def store_capture(root, raw, feed, *, documentation_raw, rights_raw, **window):
    rows, receipt = normalize(raw, feed, **window)
    p.check(type(documentation_raw) is bytes and digest(documentation_raw) == receipt['documentation_sha256'], 'RTDSM_DOCUMENTATION_PIN')
    p.check(type(rights_raw) is bytes and 0 < len(rights_raw) <= 256*1024, 'RTDSM_RIGHTS_NOTICE_BUDGET')
    buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=buffer, mode='wb', filename='', mtime=0, compresslevel=6) as stream:
        for line in _normalized_lines(rows): stream.write(line)
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
        start=manifest['requested_start'], through=manifest['requested_through'], capture_ref=manifest['capture_ref'])
    p.check(digest(documentation) == receipt['documentation_sha256'] and
        encoded(_manifest(receipt, normalized, rights)) == raw, 'RTDSM_NORMALIZATION_REPLAY')
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(normalized), mode='rb') as stream:
            for line in _normalized_lines(rows): p.check(stream.readline(p.MAX_LINE_BYTES+1) == line, 'RTDSM_NORMALIZATION_REPLAY')
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
