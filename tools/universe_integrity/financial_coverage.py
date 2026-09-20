"""Whole-cohort SEC financial-change audit; not a selector or portfolio writer.

Reuse an identity-bound price cohort. Fetch once per CIK, retain every requested
security and report missing data rather than manufacture neutral observations.
Current-filed-date facts are NOT certified historical PIT or consensus estimates.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import csv
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import threading
import time
from datetime import date, datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

TAGS = {
    'revenue': ('RevenueFromContractWithCustomerExcludingAssessedTax', 'Revenues', 'SalesRevenueNet', 'Revenue'),
    'net_income': ('NetIncomeLoss', 'ProfitLoss'),
    'operating_income': ('OperatingIncomeLoss', 'ProfitLossFromOperatingActivities'),
    'cfo': ('NetCashProvidedByUsedInOperatingActivities', 'CashFlowsFromUsedInOperatingActivities'),
    'capex': ('PaymentsToAcquirePropertyPlantAndEquipment', 'PurchaseOfPropertyPlantAndEquipment'),
    'cash': ('CashAndCashEquivalentsAtCarryingValue', 'CashAndCashEquivalents'),
    'assets': ('Assets',),
    'equity': ('StockholdersEquity', 'Equity'),
}
ALLOWED_HOSTS = {'www.sec.gov', 'data.sec.gov', 'fred.stlouisfed.org'}
FORMS = {'10-Q', '10-K', '10-Q/A', '10-K/A', '20-F', '20-F/A', '40-F', '40-F/A', '6-K', '6-K/A'}
MACRO = ('DGS2', 'DGS10', 'DFII10', 'T10YIE', 'BAMLH0A0HYM2', 'VIXCLS', 'DCOILWTICO', 'DTWEXBGS')
_GATE = threading.Lock()
_LAST = 0.0


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def finite(value):
    return type(value) in (float, int) and math.isfinite(value)


def sec_symbol(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.\-]{0,14}', value):
        raise ValueError('invalid_security_symbol')
    return value.upper().replace('.', '-')


def issuer_queue(members, mapping):
    """No watchlist/first-N filter; share classes map to one issuer request."""
    symbols = [r['ticker'] for r in members]
    if len(symbols) != len(set(symbols)) or not symbols:
        raise ValueError('duplicate_or_empty_universe')
    lookup = {}
    for item in mapping.values():
        key = sec_symbol(item['ticker'])
        cik = str(item['cik_str']).zfill(10)
        if not re.fullmatch(r'\d{10}', cik):
            raise ValueError('invalid_cik')
        lookup.setdefault(key, set()).add(cik)
    groups, missing = {}, []
    for symbol in symbols:
        matches = lookup.get(sec_symbol(symbol), set())
        if len(matches) != 1:
            missing.append({'ticker': symbol, 'reason': 'CIK_MISSING' if not matches else 'CIK_AMBIGUOUS'})
        else:
            groups.setdefault(next(iter(matches)), []).append(symbol)
    return groups, missing


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError('redirect_blocked')


def get_public(url, root):
    """Bounded public GET; no credentials, response bodies or URLs in errors."""
    global _LAST
    parts = urlsplit(url)
    if parts.scheme != 'https' or parts.hostname not in ALLOWED_HOSTS or parts.username:
        raise ValueError('source_url')
    for attempt in range(3):
        if parts.hostname.endswith('sec.gov'):
            with _GATE:
                time.sleep(max(0.0, .26 - (time.monotonic() - _LAST)))
                _LAST = time.monotonic()
        try:
            req = Request(url, headers={'User-Agent': 'R1000Research andrewcha231@gmail.com', 'Accept': 'application/json,text/csv'})
            with build_opener(NoRedirect()).open(req, timeout=25) as response:
                raw = response.read(24 * 1024 * 1024 + 1)
            if not raw or len(raw) > 24 * 1024 * 1024:
                raise ValueError('response_size')
            digest = sha(raw)
            path = Path(root) / (digest + '.raw')
            if path.exists():
                if sha(path.read_bytes()) != digest:
                    raise ValueError('raw_corruption')
            else:
                try:
                    with path.open('xb') as handle:
                        handle.write(raw)
                except FileExistsError:
                    if sha(path.read_bytes()) != digest:
                        raise ValueError('raw_corruption')
                path.chmod(0o600)
            return raw, digest
        except HTTPError as exc:
            if exc.code in (429, 500, 502, 503, 504) and attempt < 2:
                time.sleep(2 ** attempt)
                continue
            raise ValueError('HTTP_' + str(exc.code)) from None
        except (URLError, TimeoutError, OSError):
            if attempt < 2:
                time.sleep(2 ** attempt)
                continue
            raise ValueError('TRANSPORT_ERROR') from None
    raise ValueError('REQUEST_EXHAUSTED')


def facts_for(payload, tags, cutoff):
    """Keep dimension identities; never select a later filing before cutoff."""
    out = []
    for namespace in ('us-gaap', 'ifrs-full'):
        for tag in tags:
            for unit, entries in payload.get('facts', {}).get(namespace, {}).get(tag, {}).get('units', {}).items():
                if not re.fullmatch('[A-Z]{3}', unit):
                    continue
                for r in entries:
                    if (r.get('form') not in FORMS or not finite(r.get('val')) or
                        not r.get('accn') or not r.get('filed') or not r.get('end')):
                        continue
                    if r['filed'] > cutoff or r['end'] > cutoff:
                        continue
                    try:
                        duration = (date.fromisoformat(r['end']) - date.fromisoformat(r['start'])).days if r.get('start') else None
                        date.fromisoformat(r['filed'])
                    except (ValueError, TypeError):
                        continue
                    if duration is not None and duration < 0:
                        continue
                    out.append({**{k: r.get(k) for k in ('start', 'end', 'filed', 'accn', 'val', 'form')},
                                'namespace': namespace, 'tag': tag, 'currency': unit, 'duration': duration})
    # This is a current-only view of immutable source versions, not a backdated panel.
    latest, versions = {}, {}
    for r in sorted(out, key=lambda x: (x['filed'], x['accn'])):
        identity = (r['namespace'], r['tag'], r['currency'], r['start'], r['end'])
        version = identity + (r['filed'], r['accn'])
        if version in versions and versions[version] != r['val']:
            raise ValueError('conflicting_fact_version')
        versions[version] = r['val']
        latest[identity] = r
    return list(latest.values())


def select_family(rows):
    # Avoid silently preferring USD when a foreign issuer reports a newer native currency.
    quarters = [r for r in rows if r['duration'] is not None and 70 <= r['duration'] <= 105]
    if not quarters:
        return None
    latest_end = max(r['end'] for r in quarters)
    candidates = [r for r in quarters if r['end'] == latest_end]
    currencies = {(r['namespace'], r['currency']) for r in candidates}
    if len(currencies) != 1:
        return None
    return max(candidates, key=lambda x: (x['filed'], -TAGS['revenue'].index(x['tag'])))


def annualized_flow(rows, namespace, currency):
    """Annual + fiscal YTD - comparable prior YTD; no quarterly forward fill."""
    choices = []
    for tag in sorted({r['tag'] for r in rows}):
        selected = [r for r in rows if (r['namespace'], r['currency'], r['tag']) == (namespace, currency, tag)]
        annuals = [r for r in selected if r['duration'] is not None and 330 <= r['duration'] <= 380]
        if not annuals:
            continue
        annual = max(annuals, key=lambda r: (r['end'], r['filed']))
        ytds = [r for r in selected if r['start'] and r['end'] > annual['end'] and
                (date.fromisoformat(r['start']) - date.fromisoformat(annual['end'])).days == 1 and
                r['duration'] is not None and 60 <= r['duration'] <= 310]
        parts, value, finish = [annual], annual['val'], annual['end']
        if ytds:
            ytd = max(ytds, key=lambda r: (r['end'], r['filed']))
            prior = [r for r in selected if r['start'] and r['end'] < annual['end'] and
                     abs((date.fromisoformat(ytd['end']) - date.fromisoformat(r['end'])).days - 365) <= 8 and
                     abs((date.fromisoformat(ytd['start']) - date.fromisoformat(r['start'])).days - 365) <= 8]
            if len(prior) != 1:
                continue
            parts = [annual, ytd, prior[0]]
            value = annual['val'] + ytd['val'] - prior[0]['val']
            finish = ytd['end']
        choices.append({'value': value, 'period_end': finish, 'currency': currency, 'tag': tag,
                        'latest_component_filed': max(r['filed'] for r in parts), 'components': parts})
    return max(choices, key=lambda r: (r['period_end'], r['latest_component_filed'])) if choices else None


def packet(payload, cutoff):
    rows = {name: facts_for(payload, tags, cutoff) for name, tags in TAGS.items()}
    anchor = select_family(rows['revenue'])
    result = {'current_quarter_usable': False, 'valuation_approved': False,
              'historical_pit_verified': False, 'consensus_estimates_available': False,
              'publication_precision': 'FILED_DATE_ONLY', 'reason': None}
    if not anchor:
        result['reason'] = 'QUARTER_OR_REPORTING_CURRENCY_UNRESOLVED'
        result['available_namespaces'] = sorted(payload.get('facts', {}))
        return result
    namespace, currency = anchor['namespace'], anchor['currency']
    end = anchor['end']
    age = (date.fromisoformat(cutoff) - date.fromisoformat(end)).days
    result.update(currency=currency, namespace=namespace, quarter_end=end, quarter_age_days=age,
                  revenue_quarter=anchor['val'], revenue_source=anchor)
    quarters = [r for r in rows['revenue'] if (r['namespace'], r['currency'], r['tag']) == (namespace, currency, anchor['tag'])
                and r['duration'] is not None and 70 <= r['duration'] <= 105]
    result['quarters_observed'] = len({r['end'] for r in quarters})
    prior = [r for r in quarters if abs((date.fromisoformat(end) - date.fromisoformat(r['end'])).days - 365) <= 8
             and abs(r['duration'] - anchor['duration']) <= 8]
    result['revenue_yoy'] = anchor['val'] / prior[0]['val'] - 1 if len(prior) == 1 and prior[0]['val'] > 0 else None
    prev = [r for r in quarters if 70 <= (date.fromisoformat(end) - date.fromisoformat(r['end'])).days <= 110]
    result['revenue_yoy_previous_quarter'] = None
    if len(prev) == 1:
        prev_prior = [r for r in quarters if abs((date.fromisoformat(prev[0]['end']) - date.fromisoformat(r['end'])).days - 365) <= 8]
        if len(prev_prior) == 1 and prev_prior[0]['val'] > 0:
            result['revenue_yoy_previous_quarter'] = prev[0]['val'] / prev_prior[0]['val'] - 1
    a, b = result['revenue_yoy'], result['revenue_yoy_previous_quarter']
    result['revenue_growth_acceleration_pp'] = 100 * (a - b) if a is not None and b is not None else None
    for field in ('net_income', 'operating_income'):
        same = [r for r in rows[field] if r['namespace'] == namespace and r['currency'] == currency
                and r['start'] == anchor['start'] and r['end'] == end]
        record = max(same, key=lambda r: r['filed']) if same else None
        result[field + '_quarter'] = record['val'] if record else None
        result[field + '_margin'] = record['val'] / anchor['val'] if record and anchor['val'] > 0 else None
        result[field + '_source'] = record
    flows = {field: annualized_flow(rows[field], namespace, currency)
             for field in ('revenue', 'net_income', 'cfo', 'capex')}
    # No fallback to an older annual value may impersonate the latest quarter TTM.
    result['ttm'] = {k: v if v and v['period_end'] == end else None for k, v in flows.items()}
    cfo, capex = result['ttm']['cfo'], result['ttm']['capex']
    result['fcf_ttm'] = cfo['value'] - capex['value'] if cfo and capex and capex['value'] >= 0 else None
    for field in ('cash', 'assets', 'equity'):
        same = [r for r in rows[field] if r['namespace'] == namespace and r['currency'] == currency and
                r['duration'] is None and r['end'] == end]
        result[field] = max(same, key=lambda r: r['filed']) if same else None
    result['current_quarter_usable'] = age <= 150 and result['net_income_quarter'] is not None
    result['reason'] = None if result['current_quarter_usable'] else 'STALE_OR_INCOMPLETE_QUARTER'
    return result


def macro_snapshot(root, cutoff):
    output = []
    for series in MACRO:
        try:
            url = 'https://fred.stlouisfed.org/graph/fredgraph.csv?' + urlencode({'id': series, 'cosd': '2026-07-01', 'coed': cutoff})
            raw, digest = get_public(url, root)
            data = list(csv.DictReader(io.StringIO(raw.decode('utf-8-sig'))))
            values = []
            for r in data:
                stamp = r.get('observation_date', r.get('DATE', ''))
                value = r.get(series)
                if stamp and stamp <= cutoff and value not in (None, '', '.'):
                    values.append((stamp, float(value)))
            if not values or not all(math.isfinite(v) for _, v in values):
                raise ValueError('macro_missing')
            values.sort()
            output.append({'series': series, 'status': 'OBSERVED', 'observation_date': values[-1][0],
                           'value': values[-1][1], 'raw_sha256': digest, 'source': 'https://fred.stlouisfed.org/series/' + series,
                           'vintage_verified': False, 'selection_weight': 0})
        except (ValueError, KeyError, TypeError):
            output.append({'series': series, 'status': 'UNAVAILABLE', 'value': None, 'selection_weight': 0})
    return output


def run(input_path, output, private_root, cutoff, expected_input_hash):
    raw = Path(input_path).read_bytes()
    if sha(raw) != expected_input_hash:
        raise ValueError('cohort_hash_mismatch')
    cohort = json.loads(raw)
    members = cohort['rows']
    if cohort['candidate_count'] != len(members) or len(members) < 1000:
        raise ValueError('cohort_coverage_floor')
    if cohort['as_of'] > cutoff:
        raise ValueError('future_cohort')
    output, private_root = Path(output), Path(private_root)
    for path in (output, private_root):
        if any(p.is_symlink() for p in (path, *path.parents)):
            raise ValueError('symlink_path')
        path.mkdir(parents=True, exist_ok=True)
    mapping_raw, mapping_hash = get_public('https://www.sec.gov/files/company_tickers.json', private_root)
    groups, missing = issuer_queue(members, json.loads(mapping_raw))
    rows = [{'ticker': r['ticker'], 'status': 'MISSING_IDENTITY', 'reason': r['reason']} for r in missing]
    def one(cik):
        try:
            source = 'https://data.sec.gov/api/xbrl/companyfacts/CIK' + cik + '.json'
            raw, digest = get_public(source, private_root)
            value = json.loads(raw)
            if str(value['cik']).zfill(10) != cik:
                raise ValueError('issuer_identity_mismatch')
            data = packet(value, cutoff)
            return cik, {'status': 'COLLECTED', 'raw_sha256': digest, 'source': source, 'financials': data}
        except (ValueError, TypeError, KeyError) as exc:
            safe = str(exc) if re.fullmatch(r'[A-Za-z_0-9]+', str(exc)) else 'PARSE_OR_PROVIDER_ERROR'
            return cik, {'status': 'UNAVAILABLE', 'reason': safe}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        for index, (cik, observed) in enumerate(pool.map(one, sorted(groups)), 1):
            for symbol in groups[cik]:
                rows.append({'ticker': symbol, 'cik': cik, **observed})
            if index % 100 == 0:
                print(json.dumps({'issuers_completed': index, 'issuers_requested': len(groups)}), flush=True)
    rows.sort(key=lambda r: r['ticker'])
    if {r['ticker'] for r in rows} != {r['ticker'] for r in members} or len(rows) != len(members):
        raise ValueError('coverage_reconciliation_failed')
    metadata = {'schema_version': 'whole-cohort-financial-coverage-v1', 'data_kind': 'REAL_CURRENT_OBSERVATIONS',
                'analysis_at': datetime.now(timezone.utc).isoformat(), 'filing_cutoff_date': cutoff,
                'source_sha': os.environ.get('GITHUB_SHA'), 'cohort_sha256': sha(raw),
                'cohort_price_as_of': cohort['as_of'], 'mapping_sha256': mapping_hash,
                'requested_securities': len(members), 'requested_unique_issuers': len(groups),
                'collected_securities': sum(r['status'] == 'COLLECTED' for r in rows),
                'usable_current_quarters': sum(r.get('financials', {}).get('current_quarter_usable', False) for r in rows),
                'revenue_yoy_available': sum(r.get('financials', {}).get('revenue_yoy') is not None for r in rows),
                'revenue_acceleration_available': sum(r.get('financials', {}).get('revenue_growth_acceleration_pp') is not None for r in rows),
                'fcf_ttm_available': sum(r.get('financials', {}).get('fcf_ttm') is not None for r in rows),
                'orders_allowed': False, 'portfolio_weights': None,
                'blockers': ['CURRENT_PRICE_ALIGNMENT', 'FORWARD_ESTIMATES_AND_VALUATION',
                             'SECTOR_SPECIFIC_ACCOUNTING', 'UNDERWRITING_AND_RISK_REVIEW', 'DURABLE_RAW_ARCHIVE'],
                'raw_archival_status': 'RUNNER_TEMP_ONLY_NOT_DURABLE',
                'macro': macro_snapshot(private_root, cutoff), 'rows': rows}
    (output / 'whole_cohort_financials.json').write_bytes(canonical(metadata))
    summary = {k: v for k, v in metadata.items() if k != 'rows'}
    (output / 'coverage_summary.json').write_bytes(canonical(summary))
    print(json.dumps(summary, indent=2), flush=True)
    return metadata


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--input', required=True)
    p.add_argument('--output', required=True)
    p.add_argument('--private-root', required=True)
    p.add_argument('--cutoff', required=True)
    p.add_argument('--input-sha256', required=True)
    a = p.parse_args()
    date.fromisoformat(a.cutoff)
    if a.cutoff >= datetime.now(timezone.utc).date().isoformat():
        raise ValueError('completed_filing_date_required')
    run(a.input, a.output, a.private_root, a.cutoff, a.input_sha256)
