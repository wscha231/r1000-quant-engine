"""Offline original-bound official release parser candidate; no collection/admission."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from html.parser import HTMLParser
import hashlib
import json
import math
import re
SCOPES = {'Assets and Liabilities of Commercial Banks in the United States': 'all', 'Assets and Liabilities of Domestically Chartered Commercial Banks in the United States': 'domestic', 'Assets and Liabilities of Large Domestically Chartered Commercial Banks in the United States': 'large', 'Assets and Liabilities of Small Domestically Chartered Commercial Banks in the United States': 'small'}
FIELDS = {'Deposits': 'deposits', 'Loans and leases in bank credit': 'loans', 'Commercial and industrial loans': 'commercial_industrial_loans', 'Cash assets': 'cash_assets', 'Total assets': 'total_assets'}
MONTHS = {name: n for n, name in enumerate(('Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'), 1)}
MAX_BYTES = 2 * 1024 * 1024

def require(ok, reason):
    if not ok:
        raise ValueError('A4_ARCHIVE_' + reason)

def clean(text):
    return ' '.join(text.split())

class Document(HTMLParser):
    """Bounded text/table extraction; no script, URL loading or HTML execution."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables = []
        self.table = None
        self.row = None
        self.cell = None
        self.outside = []
        self.pre = []
        self.in_pre = False
        self.skip = []
        self.sup = 0
        self.cells = 0
        self.elements = 0
        self.visible = []
        self.text_nodes = 0
        self.text_chars = 0

    def handle_starttag(self, tag, attrs):
        self.elements += 1
        require(self.elements <= 100000, 'NODE_BUDGET')
        if tag in ('script', 'style') or (tag == 'a' and dict(attrs).get('class') == 'foot'):
            self.skip.append(tag)
            return
        if self.skip:
            return
        if tag == 'sup':
            self.sup += 1
        if tag == 'pre':
            self.in_pre = True
            self.pre.append([])
        if tag == 'table':
            require(self.table is None, 'NESTED_TABLE')
            require(len(self.tables) < 64, 'TABLE_BUDGET')
            self.table = dict(attrs=dict(attrs), rows=[], context=clean(' '.join(self.outside)))
            self.tables.append(self.table)
            self.outside = []
        if tag == 'tr' and self.table is not None:
            require(self.row is None, 'NESTED_ROW')
            self.row = []
            self.table['rows'].append(self.row)
        if tag in ('td', 'th') and self.table is not None:
            require(self.row is not None and self.cell is None, 'CELL_STRUCTURE')
            self.cells += 1
            require(self.cells <= 30000, 'CELL_BUDGET')
            self.cell = dict(attrs=dict(attrs), chunks=[])
            self.row.append(self.cell)

    def handle_data(self, data):
        if self.skip or self.sup:
            return
        self.text_nodes += 1
        self.text_chars += len(data)
        require(self.text_nodes <= 100000 and self.text_chars <= MAX_BYTES, 'TEXT_BUDGET')
        self.visible.append(data)
        if self.in_pre:
            self.pre[-1].append(data)
        if self.cell is not None:
            self.cell['chunks'].append(data)
        elif self.table is None:
            self.outside.append(data)

    def handle_endtag(self, tag):
        if self.skip:
            if tag == self.skip[-1]:
                self.skip.pop()
            return
        if tag == 'sup':
            self.sup = max(0, self.sup - 1)
        if tag == 'pre':
            self.in_pre = False
        if tag in ('td', 'th'):
            self.cell = None
        if tag == 'tr':
            self.row = None
        if tag == 'table':
            self.table = None

def cell_text(cell):
    return clean(' '.join(cell['chunks']))

def number(text):
    text = clean(text)
    require(len(text) <= 64, 'NUMBER_LENGTH')
    if text in ('.', '..', '...', '--', 'n.a.', 'N/A', 'ND'):
        return None
    require(re.fullmatch('[+-]?(?:\\d{1,3}(?:,\\d{3})+|\\d+)(?:\\.\\d+)?', text) is not None, 'NUMBER')
    value = float(Decimal(text.replace(',', '')))
    require(math.isfinite(value), 'NUMBER_FINITE')
    return value

def read_document(raw, expected_sha256):
    require(type(raw) is bytes and 0 < len(raw) <= MAX_BYTES, 'BYTE_BUDGET')
    require(type(expected_sha256) is str and hashlib.sha256(raw).hexdigest() == expected_sha256, 'ORIGINAL_HASH')
    doc = Document()
    doc.feed(raw.decode('utf-8-sig'))
    doc.close()
    require(doc.table is None and (not doc.skip), 'UNCLOSED_DOCUMENT')
    return doc

def release_identity(raw, ref, official_dates):
    require(type(ref) is dict and ref['release_date'] in official_dates, 'OFFICIAL_DATE_INDEX')
    release = datetime.strptime(ref['release_date'], '%Y%m%d').date()
    require(ref['feed'] in ('h8', 'h41') and ref['url'] == 'https://www.federalreserve.gov/releases/' + ref['feed'] + '/' + ref['release_date'] + '/', 'SOURCE_IDENTITY')
    collected = datetime.fromisoformat(ref['collected_at'])
    require(collected.tzinfo is not None and collected.utcoffset() is not None, 'COLLECTION_TIMEZONE')
    require(collected.astimezone(timezone.utc).date() >= release, 'COLLECTION_BEFORE_RELEASE')
    doc = read_document(raw, ref['sha256'])
    visible = clean(' '.join(doc.visible))
    date_text = release.strftime('%B') + ' ' + str(release.day) + ', ' + str(release.year)
    require(re.search(re.escape(release.strftime('%B')) + ' 0?' + str(release.day) + ', ' + str(release.year), visible[:30000]) is not None, 'DOCUMENT_RELEASE_DATE')
    return (doc, release)

def week_date(text, release):
    match = re.fullmatch('([A-Z][a-z]{2}) (\\d{1,2})', text)
    require(match is not None and match[1] in MONTHS, 'WEEK_HEADER')
    month, day = (MONTHS[match[1]], int(match[2]))
    year = release.year - (month > release.month)
    result = date(year, month, day)
    require(0 <= (release - result).days <= 45 and result.weekday() == 2, 'WEEK_DATE')
    return result

def observation(ref, release, logical, observed, value, unit, scope, basis, seasonal, locator):
    return dict(logical_id=logical, source_id='frb-archive:' + ref['feed'] + ':' + logical, observation_date=observed.isoformat(), value=value, unit=unit, frequency='weekly', scope=scope, balance_basis=basis, seasonal_adjustment=seasonal, release_date=release.isoformat(), vintage_date=release.isoformat(), published_at=None, available_at=(datetime.combine(release + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=5)).isoformat(), availability_policy='NEXT_CIVIL_DAY_05_UTC_CONSERVATIVE_RESEARCH_ASSUMPTION', collected_at=ref['collected_at'], original_sha256=ref['sha256'], original_url=ref['url'], locator=locator, methodology_notes_sha256=ref['sha256'], classification_break_adjusted=False, historical_use='DATE_ARCHIVE_RESEARCH_ONLY', historical_pit_certified=False, source_admitted=False, training_admitted=False)

def amount_units(text):
    return {unit.lower() for unit in re.findall(r'\b(Thousands|Millions|Billions|Trillions) of dollars\b', text, re.I)}

def h8(raw, ref, official_dates):
    doc, release = release_identity(raw, ref, official_dates)
    require(ref['feed'] == 'h8', 'FEED')
    out = []
    seen = set()
    tables_used = 0
    for table in doc.tables:
        title = table['attrs'].get('summary', table['attrs'].get('title', ''))
        title = re.sub('^Table \\d+\\. ', '', title)
        if title not in SCOPES:
            continue
        context = table['context']
        settings = set(re.findall(r'\b(Not seasonally adjusted|Seasonally adjusted)\b', context, re.I))
        settings = {setting.lower() for setting in settings}
        require(len(settings) == 1, 'SEASONAL_AMBIGUITY')
        units = amount_units(context)
        require(units == {'billions'}, 'H8_UNIT')
        if settings == {'not seasonally adjusted'}:
            continue
        scope = SCOPES[title]
        headers = {}
        for row in table['rows']:
            for cell in row:
                label = cell_text(cell)
                if re.fullmatch('[A-Z][a-z]{2} \\d{1,2}', label):
                    header = cell['attrs'].get('id')
                    require(header is not None and header not in headers, 'WEEK_ID')
                    headers[header] = week_date(label, release)
        require(len(headers) == 4 and len(set(headers.values())) == 4, 'WEEK_COVERAGE')
        tables_used += 1
        for row in table['rows']:
            if len(row) < 3:
                continue
            label = cell_text(row[1])
            if label not in FIELDS:
                continue
            field = FIELDS[label]
            values = {}
            for cell in row[2:]:
                matches = set(cell['attrs'].get('headers', '').split()) & set(headers)
                if not matches:
                    continue
                require(len(matches) == 1, 'WEEK_CELL_ID')
                header = next(iter(matches))
                require(header not in values, 'DUPLICATE_WEEK')
                values[header] = number(cell_text(cell))
            require(set(values) == set(headers), 'ROW_COVERAGE')
            for header, value in values.items():
                key = (field, scope, headers[header])
                require(key not in seen, 'DUPLICATE_OBSERVATION')
                seen.add(key)
                out.append(observation(ref, release, field + '_' + scope, headers[header], value, 'USD_BILLIONS', scope, 'WEDNESDAY_LEVEL', 'SA', table['attrs'].get('id', title) + ':' + label + ':' + header))
    require(len(out) == 80 and len({o['logical_id'] for o in out}) == 20, 'EXPECTED_BANK_COVERAGE')
    reconciliation = []
    for field in FIELDS.values():
        for day in sorted({o['observation_date'] for o in out}):
            vals = {o['scope']: o['value'] for o in out if o['logical_id'].startswith(field + '_') and o['observation_date'] == day}
            if any((vals.get(s) is None for s in ('domestic', 'large', 'small'))):
                continue
            gap = vals['large'] + vals['small'] - vals['domestic']
            require(abs(gap) <= 0.151, 'DOMESTIC_COMPONENT_SUM')
            reconciliation.append(dict(field=field, date=day, large_plus_small_minus_domestic=round(gap, 6)))
    return dict(schema='a4-archived-h8-candidate-v1', observations=out, reconciliation=reconciliation, tables_used=tables_used, rights_source='https://www.federalreserve.gov/disclaimer.htm', rights_scope='BOARD_PRODUCED_STATISTICAL_TEXT_ONLY', model_fits=0)
DATE_TEXT = '[A-Z][a-z]{2} \\d{1,2}, \\d{4}'

def h41_date(text):
    require(re.fullmatch(DATE_TEXT, text) is not None, 'H41_DATE_FORMAT')
    return datetime.strptime(text, '%b %d, %Y').date()

def h41_unit(text):
    require(amount_units(text) == {'millions'}, 'H41_UNIT')

def rrp_transition(label, parent, pairs, values):
    if parent == 'RRP_COMPLETE':
        require(label not in ('Others', 'Foreign official and international accounts'), 'RRP_DUPLICATE_CHILD')
        parent = None
    if label == 'Reverse repurchase agreements':
        require(parent is None and 'rrp_other' not in pairs, 'RRP_UNFINISHED_OR_DUPLICATE')
        return 'RRP_EXPECT_FOREIGN'
    if parent == 'RRP_EXPECT_FOREIGN':
        require(label == 'Foreign official and international accounts', 'RRP_SEQUENCE')
        return 'RRP_EXPECT_OTHERS'
    if parent == 'RRP_EXPECT_OTHERS':
        require(label == 'Others' and 'rrp_other' not in pairs, 'RRP_DUPLICATE_OR_SEQUENCE')
        pairs['rrp_other'] = values
        return 'RRP_COMPLETE'
    return parent

def text_columns(line):
    """Linear bounded splitting; padded numeric columns never backtrack."""
    parts = re.split(r' {2,}', line.strip())
    joined = []
    pending_sign = None
    for part in parts:
        if pending_sign is not None:
            joined.append(pending_sign + part)
            pending_sign = None
        elif part in ('+', '-'):
            pending_sign = part
        else:
            joined.append(part)
    if pending_sign is not None:
        return []
    return joined

def numeric_columns(parts):
    return all(len(part) <= 64 and re.fullmatch(r'[+-]?\s*[\d,]+', part) is not None for part in parts)

def h41(raw, ref, official_dates):
    doc, release = release_identity(raw, ref, official_dates)
    require(ref['feed'] == 'h41', 'FEED')
    out = []
    pairs = {}
    asset = None
    observed = None
    consolidated_days = []
    if doc.pre:
        require(len(doc.pre) == 1, 'PRE_COVERAGE')
        text = '\n'.join((line.rstrip() for line in ''.join(doc.pre[0]).splitlines() if line.strip()))
        first = text.split('\n2. ')[0]
        lines = first.splitlines()
        dates = []
        require(all((len(line) <= 4096 for line in text.splitlines())), 'H41_LINE_BUDGET')
        for n, line in enumerate(lines):
            if 'Averages of daily figures' not in line or 'Wednesday' not in line:
                continue
            h41_unit('\n'.join(lines[max(0, n - 2):n]))
            require(n + 2 < len(lines) and 'Week ended' in lines[n + 1] and ('Federal Reserve Banks' in lines[n + 2]), 'H41_TEXT_HEADER')
            wednesday = re.findall(DATE_TEXT, lines[n + 1])
            weekly = re.findall(DATE_TEXT, lines[n + 2])
            require(len(wednesday) == 1 and len(weekly) == 3 and (wednesday[0] == weekly[0]), 'H41_WEDNESDAY_WEEK_MISMATCH')
            dates.append(h41_date(weekly[0]))
        require(len(dates) == 2 and len(set(dates)) == 1, 'H41_HEADER_COVERAGE')
        observed = dates[0]
        rows = []
        critical = '^\\s*(Reverse repurchase agreements|Foreign official and international accounts|Others|U\\.S\\. Treasury, General Account|Reserve balances with Federal Reserve Banks)\\b'
        for line in lines:
            parts = text_columns(line)
            matched = len(parts) >= 5 and numeric_columns(parts[-4:])
            if re.search(critical, line):
                require(matched, 'H41_CRITICAL_ROW_FORMAT')
            if matched:
                rows.append((clean(re.sub('\\(\\d+\\)', '', ' '.join(parts[:-4]))), [number(parts[-4]), number(parts[-1])]))
        parent = None
        for label, values in rows:
            parent = rrp_transition(label, parent, pairs, values)
            if label == 'U.S. Treasury, General Account':
                require('tga' not in pairs, 'DUPLICATE_TGA')
                pairs['tga'] = values
            if label == 'Reserve balances with Federal Reserve Banks':
                require('reserves' not in pairs, 'DUPLICATE_RESERVES')
                pairs['reserves'] = values
        require(parent in (None, 'RRP_COMPLETE'), 'RRP_UNFINISHED')
        section = re.search('\\n[45]\\. Consolidated Statement of Condition[^\\n]*\\n.*?(?=\\n[56]\\. Statement of Condition|\\Z)', text, re.S)
        require(section is not None, 'H41_CONSOLIDATED_SECTION')
        asset_lines = section[0].splitlines()
        headers = [n for n, line in enumerate(asset_lines) if 'Assets, liabilities, and capital' in line and 'Eliminations' in line and ('Wednesday' in line) and ('Change since' in line)]
        require(1 <= len(headers) <= 2 and all((n + 1 < len(asset_lines) for n in headers)), 'H41_ASSET_COLUMN_MEANING')
        for n in headers:
            h41_unit('\n'.join(asset_lines[max(0, n - 3):n]))
            own_date = re.findall(DATE_TEXT, asset_lines[n + 1])
            require(len(own_date) == 1, 'H41_ASSET_DATE')
            consolidated_days.append(h41_date(own_date[0]))
        matches = []
        for line in asset_lines:
            if not line.startswith('Total assets '):
                continue
            parts = text_columns(line)
            require(len(parts) in (4, 5) and parts[0] == 'Total assets' and numeric_columns(parts[-3:]), 'H41_TOTAL_ASSETS_FORMAT')
            require(len(parts) == 4 or re.fullmatch(r'\([\d,]+\)', parts[1]) is not None, 'H41_ELIMINATION_FORMAT')
            matches.append(parts[-3:])
        require(len(matches) == 1, 'H41_TOTAL_ASSETS')
        asset = number(matches[0][0])
    else:
        for table in doc.tables:
            rows = [[cell_text(c) for c in row] for row in table['rows']]
            if not rows:
                continue
            header = ' '.join(rows[0])
            if 'Averages of daily figures' in header:
                h41_unit(table['context'])
                require(len(rows[0]) == 3 and rows[0][1] == 'Averages of daily figures', 'H41_AVERAGE_COLUMN_MEANING')
                require(re.fullmatch('Wednesday ' + DATE_TEXT, rows[0][2]) is not None, 'H41_WEDNESDAY_COLUMN_MEANING')
                require(len(rows) > 1 and rows[1] and (re.fullmatch('Week ended ' + DATE_TEXT, rows[1][0]) is not None), 'H41_WEEK_HEADER')
                weekly = h41_date(rows[1][0].removeprefix('Week ended '))
                wednesday = h41_date(rows[0][2].removeprefix('Wednesday '))
                require(weekly == wednesday, 'H41_WEDNESDAY_WEEK_MISMATCH')
                require(observed in (None, weekly), 'H41_MIXED_DATES')
                observed = weekly
                parent = None
                for row in rows:
                    if not row:
                        continue
                    label = re.sub(' \\d+$', '', row[0])
                    if len(row) != 5:
                        require(label not in ('Reverse repurchase agreements', 'Foreign official and international accounts', 'Others', 'U.S. Treasury, General Account', 'Reserve balances with Federal Reserve Banks'), 'H41_CRITICAL_ROW_FORMAT')
                        continue
                    values = [number(row[1]), number(row[4])] if label in ('Reverse repurchase agreements', 'Foreign official and international accounts', 'Others', 'U.S. Treasury, General Account', 'Reserve balances with Federal Reserve Banks') else None
                    parent = rrp_transition(label, parent, pairs, values)
                    if label in ('U.S. Treasury, General Account', 'Reserve balances with Federal Reserve Banks'):
                        key = 'tga' if label == 'U.S. Treasury, General Account' else 'reserves'
                        require(key not in pairs, 'H41_DUPLICATE')
                        pairs[key] = values
                require(parent in (None, 'RRP_COMPLETE'), 'RRP_UNFINISHED')
            if 'Eliminations from consolidation' in header:
                h41_unit(table['context'])
                require(len(rows[0]) == 4 and re.fullmatch('Wednesday ' + DATE_TEXT, rows[0][2]) is not None, 'H41_ASSET_COLUMN_MEANING')
                consolidated_days.append(h41_date(rows[0][2].removeprefix('Wednesday ')))
                matches = [r for r in rows if len(r) == 5 and r[0] == 'Total assets']
                if matches:
                    require(asset is None and len(matches) == 1, 'H41_TOTAL_ASSETS')
                    asset = number(matches[0][2])
    require(observed is not None and 0 < (release - observed).days <= 8 and (observed.weekday() == 2), 'H41_OBSERVATION_DATE')
    require(consolidated_days and all((day == observed for day in consolidated_days)), 'H41_CONSOLIDATED_DATE_MISMATCH')
    require(set(pairs) == {'rrp_other', 'tga', 'reserves'} and asset is not None, 'H41_COVERAGE')
    for key, values in pairs.items():
        for basis, value in zip(('WEEKLY_AVERAGE', 'WEDNESDAY_LEVEL'), values):
            out.append(observation(ref, release, key + '_' + basis.lower(), observed, value, 'USD_MILLIONS', 'FEDERAL_RESERVE', basis, 'NSA', 'Table1:' + key + ':' + basis))
    out.append(observation(ref, release, 'fed_assets_wednesday_level', observed, asset, 'USD_MILLIONS', 'CONSOLIDATED_FEDERAL_RESERVE', 'WEDNESDAY_LEVEL', 'NSA', 'Table5:Total assets'))
    return dict(schema='a4-archived-h41-candidate-v1', observations=out, model_fits=0)
