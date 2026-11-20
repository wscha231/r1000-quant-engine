"""Externally pinned SEC reported-version research; no generation or admission."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import re
from types import MappingProxyType
from zoneinfo import ZoneInfo

from tools.research_data_access import (
    ContractError, ReadResult, check, clock, day, decode, digest, encoded, sha,
    _freeze, _json_retained_bytes, MAX_GENERATION_DECOMPRESSED_BYTES,
)

TAGS = ('EarningsPerShareDiluted', 'OperatingIncomeLoss',
        'RevenueFromContractWithCustomerExcludingAssessedTax')
V2_SCOPE = 'CURRENT_EDGAR_REPRESENTATIONS_CROSSCHECKED_WITH_HISTORICAL_FILING_HEADERS'
REVIEW_SCHEMA = 'independent-a1-sec-reported-version-date-review-v2'
META_LIMIT = 1024 * 1024
DOCUMENT_LIMIT = 8 * 1024 * 1024
NY = ZoneInfo('America/New_York')
SCRIPT = re.compile(
    rb'<script type="text/javascript"\s+src="/[a-zA-Z0-9/_=-]+"></script>'
    rb'(?=</body></html>\s*\Z)')


@dataclass(frozen=True)
class SECDateVersionResearchScope:
    """Caller-authenticated pins; never inferred from a manifest or reviewed flag."""
    evidence_sha256: str
    facts_sha256: str
    dissemination_sha256: str
    review_sha256: str
    allowed_requests: tuple  # exact (10-digit CIK, accession, UTC cutoff) tuples
    consumer_id: str


def _utc(value):
    check(type(value) is str and re.fullmatch(
        r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?Z', value),
        'SEC_VERSION_UTC_CUTOFF')
    return clock(value)


def _header_value(header, label):
    values = re.findall(rb'^\s*' + label + rb':\s*([^\r\n]+)', header, re.M)
    check(len(values) == 1, 'SEC_VERSION_HEADER')
    return values[0].decode('ascii').strip()


def _proofs(proof_objects, expected, remaining):
    check(type(proof_objects) is tuple and len(proof_objects) == len(expected) == 3,
          'SEC_VERSION_PROOFS')
    objects, total = {}, 0
    for item in proof_objects:
        check(type(item) is tuple and len(item) == 2, 'SEC_VERSION_PROOFS')
        key, raw = item
        sha(key)
        check(type(raw) is bytes and 0 < len(raw) <= DOCUMENT_LIMIT,
              'SEC_VERSION_RESOURCE')
        total += len(raw)
        check(total <= remaining, 'SEC_VERSION_RESOURCE')
        check(key not in objects and key in expected and digest(raw) == key,
              'SEC_VERSION_PROOF_HASH')
        objects[key] = raw
    check(set(objects) == expected, 'SEC_VERSION_PROOFS')
    return objects, total


def _expanded_qname(node, value):
    check(type(value) is str and value.count(':') == 1, 'SEC_VERSION_QNAME')
    prefix, local = value.split(':')
    check(re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.-]*', prefix) and
          re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.-]*', local) and
          node.nsmap.get(prefix), 'SEC_VERSION_QNAME')
    return node.nsmap[prefix], local


def _facts_from_primary(primary, rows, cik):
    # Caller pins have already authenticated these exact bytes. Bound native XML
    # retention conservatively and prohibit DTD/entity expansion before parsing.
    check(not re.search(rb'<!\s*(?:DOCTYPE|ENTITY)', primary, re.I) and
          b'\x00' not in primary, 'SEC_VERSION_XML')
    try:
        from lxml import etree
        tree = etree.fromstring(primary, etree.XMLParser(
            resolve_entities=False, no_network=True, huge_tree=False))
    except ImportError:
        raise ContractError('SEC_VERSION_XML_PARSER_UNAVAILABLE') from None
    except (ValueError, etree.XMLSyntaxError):
        raise ContractError('SEC_VERSION_XML') from None
    ns = {'ix': 'http://www.xbrl.org/2013/inlineXBRL',
          'x': 'http://www.xbrl.org/2003/instance'}
    context_nodes = tree.findall('.//x:context', ns)
    unit_nodes = tree.findall('.//x:unit', ns)
    contexts = {e.get('id'): e for e in context_nodes}
    units = {e.get('id'): e for e in unit_nodes}
    check(len(contexts) == len(context_nodes) and len(units) == len(unit_nodes),
          'SEC_VERSION_XML')
    check(re.fullmatch(r'https?://fasb.org/us-gaap/\d{4}-\d\d-\d\d',
                      tree.nsmap.get('us-gaap', '')), 'SEC_VERSION_XML')
    check(len(contexts) <= 10000 and len(units) <= 1000, 'SEC_VERSION_RESOURCE')
    expected = {r['tag']: r for r in rows}
    observed = {tag: set() for tag in TAGS}
    observed_contexts = {tag: set() for tag in TAGS}
    requested_contexts = {}
    for tag, row in expected.items():
        refs = row['context_refs']
        check(type(refs) is list and 0 < len(refs) <= 8 and
              all(type(ref) is str for ref in refs) and len(set(refs)) == len(refs),
              'SEC_VERSION_CONTEXT_SET')
        requested_contexts[tag] = set(refs)
    for node in tree.findall('.//ix:nonFraction', ns):
        tag = node.get('name', '')
        if not tag.startswith('us-gaap:') or tag.split(':')[-1] not in expected:
            continue
        tag = tag.split(':')[-1]
        row = expected[tag]
        ctx = contexts.get(node.get('contextRef'))
        if ctx is None or node.get('contextRef') not in row['context_refs']:
            continue
        check(_expanded_qname(node, node.get('name')) ==
              (tree.nsmap['us-gaap'], tag), 'SEC_VERSION_QNAME')
        check(len(node) == 0 and not any(k.rsplit('}', 1)[-1] in
              ('continuedAt', 'escape') for k in node.attrib), 'SEC_VERSION_INLINE_CONTENT')
        identifier = ctx.find('x:entity/x:identifier', ns)
        check(identifier is not None and identifier.get('scheme') == 'http://www.sec.gov/CIK',
              'SEC_VERSION_FACT_CONTEXT')
        check(ctx.findtext('x:entity/x:identifier', namespaces=ns) == cik and
              ctx.findtext('x:period/x:startDate', namespaces=ns) == row['start'] and
              ctx.findtext('x:period/x:endDate', namespaces=ns) == row['end'] and
              not ctx.findall('.//x:segment', ns) and not ctx.findall('.//x:scenario', ns),
              'SEC_VERSION_FACT_CONTEXT')
        unit = units.get(node.get('unitRef'))
        measure_nodes = [] if unit is None else unit.findall('.//x:measure', ns)
        measures = [_expanded_qname(m, m.text) for m in measure_nodes]
        usd = ('http://www.xbrl.org/2003/iso4217', 'USD')
        shares = ('http://www.xbrl.org/2003/instance', 'shares')
        required = [usd, shares] if tag == TAGS[0] else [usd]
        check(measures == required, 'SEC_VERSION_UNIT')
        if tag == TAGS[0]:
            numerator = unit.find('x:divide/x:unitNumerator/x:measure', ns)
            denominator = unit.find('x:divide/x:unitDenominator/x:measure', ns)
            check(numerator is not None and denominator is not None and
                  _expanded_qname(numerator, numerator.text) == usd and
                  _expanded_qname(denominator, denominator.text) == shares,
                  'SEC_VERSION_UNIT')
        else:
            check(unit.find('x:measure', ns) is not None and len(unit) == 1, 'SEC_VERSION_UNIT')
        transform = node.get('format')
        check(transform is None or _expanded_qname(node, transform) in {
            ('http://www.xbrl.org/inlineXBRL/transformation/2015-02-26', 'numdotdecimal'),
            ('http://www.xbrl.org/inlineXBRL/transformation/2020-02-12', 'num-dot-decimal')},
            'SEC_VERSION_FACT_FORMAT')
        check(node.get('sign', '') in ('', '-'), 'SEC_VERSION_FACT_FORMAT')
        value = (node.text or '').strip()
        check(re.fullmatch(r'(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?', value) is not None,
              'SEC_VERSION_FACT_FORMAT')
        scale = int(node.get('scale', '0'))
        check(-12 <= scale <= 12, 'SEC_VERSION_FACT_FORMAT')
        # Decimal.scaleb and unary negation apply ambient precision. Rebuild
        # the coefficient tuple so every original digit survives scaling.
        coefficient = Decimal(value.replace(',', ''))
        parts = coefficient.as_tuple()
        sign = 1 if node.get('sign') == '-' else parts.sign
        number = Decimal((sign, parts.digits, parts.exponent + scale))
        observed[tag].add(number)
        observed_contexts[tag].add(node.get('contextRef'))
    for tag, row in expected.items():
        check(observed_contexts[tag] == requested_contexts[tag], 'SEC_VERSION_CONTEXT_SET')
        check(observed[tag] == {Decimal(row['value'])}, 'SEC_VERSION_FACT_VALUE')


def _read(evidence_bytes, facts_bytes, dissemination_bytes, review_bytes, *,
          trusted_scope, proof_objects, issuer_cik, accession, decision_time,
          purpose, consumer_id):
    check(type(trusted_scope) is SECDateVersionResearchScope, 'SEC_VERSION_EXTERNAL_SCOPE')
    check(type(purpose) is str and purpose == 'research', 'SEC_VERSION_RESEARCH_ONLY')
    check(type(consumer_id) is str and consumer_id == trusted_scope.consumer_id and
          0 < len(consumer_id) <= 200, 'SEC_VERSION_CONSUMER')
    check(type(issuer_cik) is str and re.fullmatch(r'\d{10}', issuer_cik) and
          type(accession) is str and re.fullmatch(r'\d{10}-\d{2}-\d{6}', accession),
          'SEC_VERSION_IDENTITY')
    decision = _utc(decision_time)
    allowed = trusted_scope.allowed_requests
    check(type(allowed) is tuple and 0 < len(allowed) <= 23 and
          all(type(a) is tuple and len(a) == 3 and all(type(x) is str for x in a)
              for a in allowed) and len(set(allowed)) == len(allowed),
          'SEC_VERSION_EXTERNAL_SCOPE')
    check((issuer_cik, accession, decision_time) in allowed, 'SEC_VERSION_REQUEST_SCOPE')
    metadata, charge, all_objects = [], 0, {}
    for raw, pin in zip(
            (evidence_bytes, facts_bytes, dissemination_bytes, review_bytes),
            (trusted_scope.evidence_sha256, trusted_scope.facts_sha256,
             trusted_scope.dissemination_sha256, trusted_scope.review_sha256)):
        sha(pin)
        check(type(raw) is bytes and 0 < len(raw) <= META_LIMIT and digest(raw) == pin,
              'SEC_VERSION_METADATA_HASH')
        check(pin not in all_objects, 'SEC_VERSION_METADATA_HASH')
        charge += len(raw)
        item = decode(raw)
        charge += _json_retained_bytes(item, MAX_GENERATION_DECOMPRESSED_BYTES - charge)
        metadata.append(item)
        all_objects[pin] = raw
    evidence, facts, dissemination, review = metadata
    check(evidence.get('scope') == V2_SCOPE and
          evidence.get('official_reader_training_admission') is False and
          type(evidence.get('rows')) is list and 0 < len(evidence['rows']) <= 9,
          'SEC_VERSION_EVIDENCE')
    check(type(facts.get('rows')) is list and 0 < len(facts['rows']) <= 27 and
          type(dissemination.get('records')) is list and
          0 < len(dissemination['records']) <= 9, 'SEC_VERSION_EVIDENCE')
    check(review.get('schema') == REVIEW_SCHEMA and
          type(review.get('exact_decision_links')) is list and
          0 < len(review['exact_decision_links']) <= 23, 'SEC_VERSION_REVIEW')
    review_refs = review.get('input_refs')
    check(type(review_refs) is list and len(review_refs) <= 10, 'SEC_VERSION_REVIEW')
    ref_hashes = {r.get('sha256') for r in review_refs if type(r) is dict}
    check({trusted_scope.evidence_sha256, trusted_scope.facts_sha256,
           trusted_scope.dissemination_sha256} <= ref_hashes, 'SEC_VERSION_REVIEW')
    matches = [r for r in evidence['rows'] if r.get('accession') == accession]
    checks = [r for r in dissemination['records'] if r.get('accession') == accession]
    check(len(matches) == len(checks) == 1, 'SEC_VERSION_ACCESSION')
    version, public = matches[0], checks[0]
    check(public.get('ticker') == version.get('issuer'), 'SEC_VERSION_IDENTITY')
    links = [r for r in review['exact_decision_links']
             if r.get('accession') == accession and
             r.get('decision_date') == decision.date().isoformat() and
             r.get('issuer') == version.get('issuer')]
    check(len(links) == 1 and
          decision.date().isoformat() in version.get('linked_decisions_after_change', []),
          'SEC_VERSION_REVIEW')
    selected = [r for r in facts['rows'] if r.get('accession') == accession]
    check(len(selected) == 3 and {r.get('tag') for r in selected} == set(TAGS),
          'SEC_VERSION_ROWS')
    row_pointers = ['/rows/' + str(i) for i, r in enumerate(facts['rows'])
                    if r.get('accession') == accession]
    check(links[0].get('source_rows') == row_pointers, 'SEC_VERSION_ROWS')
    for row in selected:
        check(row.get('cik') == issuer_cik and row.get('ticker') == version['issuer'] and
              row.get('document_sha256') == version.get('standalone_sha256') and
              row.get('index_sha256') == public.get('index_sha256') and
              row.get('status') == 'ORIGINAL_AND_ARCHIVED_FACT_MATCH', 'SEC_VERSION_ROWS')
        check(row.get('unit') == ('USD/shares' if row['tag'] == TAGS[0] else 'USD') and
              type(row.get('value')) is str and Decimal(row['value']).is_finite(),
              'SEC_VERSION_UNIT')
        start, end = day(row.get('start')), day(row.get('end'))
        duration = (end - start).days + 1
        check(start <= end and
              ((row.get('duration') == 'QUARTER' and 75 <= duration <= 105) or
               (row.get('duration') == 'FISCAL_YEAR' and 350 <= duration <= 380)) and
              type(row.get('context_refs')) is list and
              0 < len(row['context_refs']) <= 8 and
              all(type(x) is str and len(x) <= 250 for x in row['context_refs']),
              'SEC_VERSION_PERIOD')
    check(len({(r['start'], r['end'], r['duration']) for r in selected}) == 1,
          'SEC_VERSION_PERIOD')
    expected = {sha(version.get('submission_prefix_sha256')),
                sha(version.get('standalone_sha256')), sha(public.get('index_sha256'))}
    objects, used = _proofs(proof_objects, expected,
                           MAX_GENERATION_DECOMPRESSED_BYTES - charge)
    charge += used
    primary = objects[version['standalone_sha256']]
    # Conservative tree/string allocation charge inside the unchanged reader cap.
    charge += 32 * len(primary)
    check(charge <= MAX_GENERATION_DECOMPRESSED_BYTES, 'SEC_VERSION_RESOURCE')
    submission = objects[version['submission_prefix_sha256']]
    header_parts = submission.split(b'</SEC-HEADER>')
    check(len(header_parts) == 2 and len(header_parts[0]) <= 32 * 1024,
          'SEC_VERSION_HEADER')
    header = header_parts[0]
    check(_header_value(header, b'ACCESSION NUMBER') == accession and
          _header_value(header, b'CENTRAL INDEX KEY') == issuer_cik and
          _header_value(header, b'CONFORMED SUBMISSION TYPE') in ('10-Q', '10-K'),
          'SEC_VERSION_IDENTITY')
    period = _header_value(header, b'CONFORMED PERIOD OF REPORT')
    check(all(r['end'].replace('-', '') == period for r in selected),
          'SEC_VERSION_PERIOD')
    changed = _header_value(header, b'DATE AS OF CHANGE')
    filed = _header_value(header, b'FILED AS OF DATE')
    check(re.fullmatch(r'\d{8}', changed) and re.fullmatch(r'\d{8}', filed) and
          changed == version.get('last_reported_change_date'), 'SEC_VERSION_CHANGE_DATE')
    changed_day, filed_day = (datetime.strptime(s, '%Y%m%d').date() for s in (changed, filed))
    acceptance = re.findall(rb'^<ACCEPTANCE-DATETIME>(\d{14})\s*$', header, re.M)
    check(len(acceptance) == 1, 'SEC_VERSION_HEADER')
    accepted = datetime.strptime(acceptance[0].decode(), '%Y%m%d%H%M%S').replace(tzinfo=NY)
    check(accepted.astimezone(timezone.utc) == clock(public.get('acceptance')),
          'SEC_VERSION_ACCEPTANCE')
    index_line = public.get('index_line')
    check(type(index_line) is list and len(index_line) == 5 and
          index_line[0] == str(int(issuer_cik)) and
          index_line[2] == _header_value(header, b'CONFORMED SUBMISSION TYPE') and
          index_line[3].replace('-', '') == filed and
          index_line[4] == f'edgar/data/{int(issuer_cik)}/{accession}.txt',
          'SEC_VERSION_INDEX')
    index_bytes = objects[public['index_sha256']]
    check(b'Daily Index of EDGAR Dissemination Feed' in index_bytes[:600] and
          [line.split('|') for line in index_bytes.decode('latin1').splitlines()
           if line.endswith('|' + index_line[4])] == [index_line], 'SEC_VERSION_INDEX')
    proxy = clock(public.get('conservative_evidence_clock'))
    check(proxy >= accepted and
          decision.astimezone(NY).date() >
          max(changed_day, filed_day, proxy.astimezone(NY).date()),
          'SEC_VERSION_SAME_DAY_OR_FUTURE')
    check(all(day(r['end']) <= filed_day for r in selected), 'SEC_VERSION_PERIOD')
    expected_url = (f'https://www.sec.gov/Archives/edgar/data/{int(issuer_cik)}/'
                    f'{accession.replace("-", "")}/{accession}.txt')
    expected_index_url = (f'https://www.sec.gov/Archives/edgar/daily-index/{filed_day.year}/'
                          f'QTR{(filed_day.month - 1) // 3 + 1}/master.{filed}.idx')
    check(version.get('source_url') == expected_url and
          public.get('index_url') == expected_index_url, 'SEC_VERSION_SOURCE_URI')
    body = header_parts[1]
    check(body.count(b'<DOCUMENT>') == 1 and body.count(b'</DOCUMENT>') == 1 and
          re.search(rb'^<SEQUENCE>1\r?$', body, re.M), 'SEC_VERSION_PRIMARY')
    filenames = re.findall(rb'^<FILENAME>([^\r\n]+)', body, re.M)
    check(len(filenames) == 1 and re.fullmatch(rb'[A-Za-z0-9._-]{1,120}', filenames[0]) and
          public.get('doc_url') == expected_url.rsplit('/', 1)[0] + '/' + filenames[0].decode(),
          'SEC_VERSION_SOURCE_URI')
    inner = re.findall(rb'^<XBRL>\r?\n(.*?)^</XBRL>\r?$', body, re.S | re.M)
    check(len(inner) == 1, 'SEC_VERSION_PRIMARY')
    member = inner[0]
    check(digest(member) == version.get('inner_primary_sha256'), 'SEC_VERSION_PRIMARY')
    cleaned, removed = SCRIPT.subn(b'', primary)
    check(primary == member or (removed == 1 and cleaned == member), 'SEC_VERSION_PRIMARY')
    _facts_from_primary(member, selected, issuer_cik)
    # Return only immutable facts and a new read receipt, never approval records.
    all_objects.update(objects)
    receipt = dict(
        schema='sec-filing-date-version-research-read-receipt-v1',
        status='VERIFIED_SEC_REPORTED_VERSION_DATE_RESEARCH',
        issuer_cik=issuer_cik, accession=accession, consumer_id=consumer_id,
        decision_time=decision_time, purpose='research', rows=len(selected),
        evidence_sha256=trusted_scope.evidence_sha256,
        external_review_sha256=trusted_scope.review_sha256,
        facts_sha256=trusted_scope.facts_sha256,
        source_submission_sha256=version['submission_prefix_sha256'],
        original_primary_sha256=version['standalone_sha256'],
        submission_primary_sha256=version['inner_primary_sha256'],
        reported_last_change_date=changed_day.isoformat(),
        dissemination_day=filed_day.isoformat(),
        availability_meaning='OFFICIAL_REPORTED_VERSION_AND_DAILY_DISSEMINATION_DATE',
        original_public_available_at=None, independent_contemporaneous_snapshot_verified=False,
        usage='SEC_DATE_VERSION_RESEARCH_ONLY', identity_scope='ISSUER_FINANCIAL_FACTS',
        data_generation_id=None,
        legacy_generation_relabelled=False, historical_pit=False, training_admitted=False,
        source_admitted=False, eligible_for_er=False, eligible_for_a5=False,
        eligible_for_selector=False, eligible_for_economics=False,
        qualified_market_join=False, provider_refresh_count=0,
        decoded_retained_bytes_charged=charge, row_set_sha256=digest(encoded(selected)))
    return ReadResult(tuple(_freeze(r) for r in selected),
                      tuple(sorted(all_objects.items())), _freeze(receipt), encoded(receipt))


def read_sec_filing_version(*args, **kwargs):
    """Finite refusal boundary for an opt-in public Reader method."""
    try:
        return _read(*args, **kwargs)
    except ContractError:
        raise
    except MemoryError:
        raise ContractError('SEC_VERSION_RESOURCE') from None
    except (ValueError, TypeError, KeyError, IndexError, AttributeError,
            OverflowError, UnicodeError, InvalidOperation):
        raise ContractError('SEC_VERSION_INVALID_PROOF') from None
