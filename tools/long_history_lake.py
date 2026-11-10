#!/usr/bin/env python3
"""Partitioned, append-only research history. No target, ledger or trading writes.

Reuse the bounded FRED parser and verified Drive transport from macro research.
Batch content-addressed objects in small packs to avoid thousands of Drive calls.
Only a hash-verified catalog commit exposes new data to consumers. Source failures
remain explicit even when an older version is retained. Never certify current
SEC companyfacts or revised macro histories as historical point-in-time truth.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import itertools
from concurrent.futures import ThreadPoolExecutor
import copy
from datetime import date, datetime, timedelta, timezone
import gzip
import io
import inspect
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import sys
import tempfile
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, build_opener
import zipfile
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.macro_history_sources import (NoRedirect, digest, encoded, exclusive,
    fetch as fetch_fred, parse_alfred, parse_current, registry, require, utc_now)
from tools.macro_research_checkpoint import (LocalTransport, RcloneTransport, relative,
    checked_bytes, is_safe_transport_failure, PACK_BATCH_FILES, PACK_BATCH_BYTES)
from tools.twelve_private_capture import Refused
from tools.macro_history_sources import MAX_BYTES as FRED_MAX_BYTES, MAX_PAGES as FRED_MAX_PAGES

SCHEMA = 'long-history-catalog-v1'
PREFIX = 'long-history-v1'
MAX_OBJECT = 18 * 1024 * 1024
PACK_BYTES = 18 * 1024 * 1024
COHORT_SHA = '4e1eb090f8137395603228dbc55c35907307ad6d049ec778f2722d1cbb87f4b4'
ARCHIVES = ('UNRATE','PAYEMS','CPIAUCSL','PCEPILFE','RSAFS','DSPIC96','PSAVERT','M2SL','ICSA','NFCI','WALCL','WRESBAL')
SCOPED_ALFRED_IDS = frozenset(('VIXCLS','DGS10','BAMLH0A0HYM2','DTWEXBGS',
    'RRPTSYD','WDTGAL','CPILFESL','PPIFDG','SAHMREALTIME'))
SCOPED_PAGE_RESERVATION_BYTES = FRED_MAX_BYTES + 1  # Existing oversized-body probe.
COUNTRIES = ('USA','CHN','JPN','KOR','EMU')
WB_INDICATORS = ('NY.GDP.MKTP.KD.ZG','FP.CPI.TOTL.ZG','SP.POP.TOTL','SP.POP.65UP.TO.ZS')
FORMS = {'10-K','10-K/A','10-Q','10-Q/A','20-F','20-F/A','40-F','40-F/A','6-K','6-K/A'}
LEGACY_SEC_MAPPING_PRODUCERS = frozenset({
    'aafcc11fab92d5cc14448652799f213aa8a26408',
    '09ce60ff1e55ced7fb309301d67b388aa2f45dd5',
    '1c48a92587f5b31c355804e694f03ece2cc52acd',
    '74765812b8f198818289ae1e082ee0ac70b18c2a',
    'd5a9cb11627d42432bddc7a72dfb7ff9d8dae30d',
    '8af844c74521a75c71cec37a1672540dadae86e3',
    'f20410549464e3f2557ae6d90ba8b20ee8bcc42e',
    '2b0e9dbe7084069ecc5f1749a33d9d497483a10c',
    '4f8ecd3186539e84d4243d01b98f29e87e902337',
})
_LOCK = threading.Lock()
_LAST = 0.0
HYBRID_MODES = frozenset(('HYBRID_DAILY', 'HYBRID_WEEKLY'))
HYBRID_OWNER_TAG = 'A1_HYBRID_HISTORY_EXECUTION_V1 '
HYBRID_READ_RESERVATION = 20 * 1024 * 1024



_PHASE_STAGES = frozenset({
    'COMMIT_INVENTORY', 'REMOTE_HASH_READ', 'PACK_DEPENDENCIES',
    'PUBLICATION_PRECHECK', 'NEW_PACK_WRITE_READBACK', 'CATALOG_WRITE_READBACK',
    'PUBLICATION_RECHECK', 'COMMIT_WRITE', 'POST_COMMIT_RESTORE',
    'INITIAL_RESTORE', 'MACRO_COLLECTION', 'FINANCIAL_COLLECTION', 'QUALITY_LOCAL',
    'PUBLICATION', 'CLEAN_CONSUMER_RESTORE', 'SQL_MATERIALIZATION', 'STUDY',
    'LOCAL_STUDY_REPORTS', 'REPORT_PUBLICATION', 'EXECUTION_RECEIPT_WRITE',
    'LOCAL_PUBLICATION_WRITE', 'PACK_BATCH_READ', 'FINALIZATION_RECHECK',
})
_PHASE_COUNTS = frozenset({'commits', 'packs', 'objects', 'index', 'total',
                           'application_bytes', 'datasets', 'rows', 'reports',
                           'reserved_bytes', 'staged_bytes', 'subprocess_attempts'})
_PHASE_IDS = itertools.count(1)


_PHASE_LOG_ERRORS = frozenset({
    ValueError, TypeError, OverflowError, RuntimeError, OSError, BrokenPipeError,
    BlockingIOError, PermissionError, FileNotFoundError, FileExistsError,
    IsADirectoryError, NotADirectoryError, UnicodeError, UnicodeEncodeError,
    UnicodeDecodeError, UnicodeTranslateError,
})


@contextmanager
def _history_phase(stage, *, commit_sha256=None, catalog_sha256=None, **counts):
    """Best-effort progress; never alter operation acceptance or cancellation."""
    phase_id, started, disabled = None, None, False

    def emit(state):
        nonlocal phase_id, started, disabled
        if disabled:
            return False
        try:
            require(stage in _PHASE_STAGES, 'history_phase_stage')
            require(set(counts) <= _PHASE_COUNTS and all(type(v) is int and 0 <= v < 2**63
                    for v in counts.values()), 'history_phase_counts')
            hashes = {}
            for name, value in (('commit_sha256', commit_sha256), ('catalog_sha256', catalog_sha256)):
                if value is not None:
                    require(isinstance(value, str) and re.fullmatch('[a-f0-9]{64}', value),
                            'history_phase_hash')
                    hashes[name] = value
            if phase_id is None:
                phase_id, started = next(_PHASE_IDS), time.monotonic_ns()
            elapsed = 0 if state == 'BEGIN' else max(0, (time.monotonic_ns()-started)//1000000)
            print('LONG_HISTORY_PHASE '+json.dumps(dict(stage=stage, state=state,
                phase_id=phase_id, elapsed_ms=elapsed, **hashes, **counts), sort_keys=True), flush=True)
        except Exception as exc:
            # Exact ordinary logger errors only. Preserve cancellation subclasses,
            # TimeoutError/InterruptedError and the existing Refused deadline.
            if type(exc) not in _PHASE_LOG_ERRORS:
                raise
            disabled = True
            return False
        return True

    emit('BEGIN')
    try:
        yield counts
    except BaseException:
        emit('ERROR')
        raise
    else:
        emit('END')


class SourceHTTPError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__('HTTP_'+str(code))


def packed(raw):
    return gzip.compress(raw, compresslevel=6, mtime=0)


def unpacked(raw):
    with gzip.GzipFile(fileobj=io.BytesIO(raw)) as handle:
        result = handle.read(128 * 1024 * 1024 + 1)
    require(len(result) <= 128 * 1024 * 1024, 'decompressed_size')
    return result


def get_public(url, conditional=None):
    """Bounded retry, conditional GET; no response bodies or secret URLs in logs."""
    global _LAST
    host = urlsplit(url).hostname
    require(urlsplit(url).scheme == 'https' and host in
        {'www.sec.gov','data.sec.gov','api.worldbank.org'}, 'source_host')
    headers = {'User-Agent':'R1000Research andrewcha231@gmail.com','Accept':'application/json'}
    if conditional:
        if conditional.get('etag'):
            headers['If-None-Match'] = conditional['etag']
        if conditional.get('last_modified'):
            headers['If-Modified-Since'] = conditional['last_modified']
    for attempt in range(3):
        if host.endswith('sec.gov'):
            with _LOCK:
                time.sleep(max(0, .28 - (time.monotonic() - _LAST)))
                _LAST = time.monotonic()
        try:
            with build_opener(NoRedirect()).open(Request(url,headers=headers),timeout=30) as response:
                raw = response.read(32*1024*1024+1)
                metadata = {'etag':response.headers.get('ETag'),
                    'last_modified':response.headers.get('Last-Modified')}
            require(0 < len(raw) <= 32*1024*1024, 'source_size')
            return raw, metadata
        except HTTPError as exc:
            if exc.code == 304 and conditional:
                return None, conditional
            if exc.code in (429,500,502,503,504) and attempt < 2:
                time.sleep(2**attempt)
                continue
            raise SourceHTTPError(exc.code) from None
        except (URLError, TimeoutError, OSError):
            if attempt < 2:
                time.sleep(2**attempt)
                continue
            raise ValueError('TRANSPORT_ERROR') from None
    raise ValueError('REQUEST_EXHAUSTED')


def sec_rows(raw, cik, start, through):
    """All available statement concepts/units/forms, including distinct revisions.

    Do not sum fiscal YTD and quarterly rows, infer missing quarters, convert
    currencies, apply current shares to ADRs, or collapse amended filings.
    """
    payload = json.loads(raw)
    require(str(payload.get('cik','')).zfill(10) == cik, 'issuer_identity')
    require(isinstance(payload.get('facts'),dict), 'facts_schema')
    rows, seen, rejected = [], {}, 0
    for namespace, concepts in payload['facts'].items():
        if namespace not in ('us-gaap','ifrs-full','dei'):
            continue
        for concept, fact in concepts.items():
            for unit, entries in fact.get('units',{}).items():
                for r in entries:
                    if r.get('form') not in FORMS:
                        continue
                    try:
                        end = date.fromisoformat(r['end'])
                        filed = date.fromisoformat(r['filed'])
                        begin = date.fromisoformat(r['start']) if r.get('start') else None
                        require(begin is None or begin <= end, 'period_order')
                        value = r['val']
                        require(type(value) in (int,float) and math.isfinite(value), 'finite_fact')
                        require(bool(re.fullmatch(r'\d{10}-\d{2}-\d{6}',r['accn'])), 'accession')
                    except (KeyError,TypeError,ValueError):
                        rejected += 1
                        continue
                    if end.isoformat() < start or end.isoformat() > through or filed.isoformat() > through:
                        continue
                    identity = (namespace,concept,unit,r.get('start'),r['end'],r['filed'],r['accn'],r['form'],
                                r.get('fy'),r.get('fp'),r.get('frame'))
                    require(identity not in seen or seen[identity] == value, 'conflicting_fact_version')
                    if identity in seen:
                        continue
                    seen[identity] = value
                    rows.append(dict(cik=cik,namespace=namespace,concept=concept,unit=unit,
                        start=r.get('start'),end=r['end'],filed=r['filed'],accession=r['accn'],
                        form=r['form'],value=value,fy=r.get('fy'),fp=r.get('fp'),frame=r.get('frame'),
                        duration_days=(end-begin).days+1 if begin else None,
                        evidence='SEC_FILED_DATE_CURRENT_ARCHIVE_NOT_CERTIFIED_PIT'))
    rows.sort(key=lambda r:(r['end'],r['filed'],r['namespace'],r['concept'],r['unit'],r['accession'],r['start'] or '',
                            str(r['fy']),r['fp'] or '',r['frame'] or ''))
    return rows, rejected


def fact_coverage(rows, start, through):
    years = sorted({int(r['end'][:4]) for r in rows})
    annual = sorted({int(r['end'][:4]) for r in rows if r['duration_days'] and 330 <= r['duration_days'] <= 400})
    # Presence of some concepts is NOT three-statement or per-quarter completeness.
    return dict(rows=len(rows),earliest=min((r['end'] for r in rows),default=None),
        latest=max((r['end'] for r in rows),default=None),years_with_any_facts=years,
        annual_period_end_years=annual,
        missing_years=[y for y in range(int(start[:4]),int(through[:4])) if y not in years],
        statement_completeness='NOT_CERTIFIED',quarter_completeness='NOT_CERTIFIED',
        currencies_and_units=sorted({r['unit'] for r in rows}),
        first_filed=min((r['filed'] for r in rows),default=None),
        last_filed=max((r['filed'] for r in rows),default=None))


def extraction_identity():
    return digest(encoded(dict(parser=inspect.getsource(sec_rows),
        coverage=inspect.getsource(fact_coverage),future=inspect.getsource(sec_future_boundary),forms=sorted(FORMS))))


def sec_future_boundary(raw,through):
    """Force re-extraction when a previously filtered source period becomes due."""
    future=[]
    for namespace,concepts in json.loads(raw).get('facts',{}).items():
        if namespace not in ('us-gaap','ifrs-full','dei'): continue
        for fact in concepts.values():
            for entries in fact.get('units',{}).values():
                for row in entries:
                    if row.get('form') not in FORMS: continue
                    try: boundary=max(date.fromisoformat(row['end']),date.fromisoformat(row['filed'])).isoformat()
                    except (KeyError,ValueError,TypeError): continue
                    if boundary>through: future.append(boundary)
    return min(future,default=None)


def sec_conditional(old,start,through):
    return old.get('http') if (old.get('start')==start and old.get('through','9999')<=through
        and 'deferred_until' in old and (old['deferred_until'] is None or old['deferred_until']>through)
        and old.get('extraction_sha256')==extraction_identity()) else None


def hybrid_clock(value):
    require(isinstance(value,str) and not value.endswith('-00:00')
            and re.search(r'(Z|[+-][0-9]{2}:[0-9]{2})$',value), 'hybrid_explicit_clock')
    result=datetime.fromisoformat(value.replace('Z','+00:00'))
    require(result.utcoffset() is not None,'hybrid_explicit_clock')
    return result.astimezone(timezone.utc)


def hybrid_request(raw, expected_sha256, mode, *, now=None, _auto_provider_scope=None):
    """Integrity/shape only; live OWNER authorization is independently required."""
    require(type(raw) is bytes and 0<len(raw)<=65536 and mode in HYBRID_MODES
            and isinstance(expected_sha256,str) and re.fullmatch('[a-f0-9]{64}',expected_sha256)
            and digest(raw)==expected_sha256,'hybrid_request_hash_or_mode')
    def unique(pairs):
        value={}
        for k,v in pairs:
            require(k not in value,'hybrid_duplicate_key'); value[k]=v
        return value
    r=json.loads(raw,object_pairs_hook=unique,
                 parse_constant=lambda _:require(False,'hybrid_nonfinite_json'))
    fields={'schema','request_id','mode','purpose','code_sha','registry_sha256','roster_sha256',
            'cohort_sha256','mapping_object_sha256','mapping_source_sha256','focus_pairs','baseline',
            'macro_start','financial_start','through','decision_at','available_at','not_before',
            'expires_at','weekly','budget','rights_sha256'}
    require(type(r) is dict and set(r)==fields and r['schema']=='long-history-hybrid-v1'
            and r['mode']==mode and r['purpose']=='PRIVATE_NONCOMMERCIAL_RESEARCH', 'hybrid_request_fields')
    require(isinstance(r['request_id'],str) and re.fullmatch('[A-Za-z0-9_-]{1,100}',r['request_id']),
            'hybrid_request_id')
    require(isinstance(r['code_sha'],str) and re.fullmatch('[a-f0-9]{40}',r['code_sha'])
            and r['code_sha']==os.environ.get('GITHUB_SHA'), 'hybrid_code_changed_NEEDS_REBIND')
    for k in ('registry_sha256','roster_sha256','cohort_sha256','mapping_object_sha256','mapping_source_sha256'):
        require(isinstance(r[k],str) and re.fullmatch('[a-f0-9]{64}',r[k]),'hybrid_pin')
    require(r['cohort_sha256']==COHORT_SHA and r['registry_sha256']==digest(encoded(registry())),
            'hybrid_registry_or_cohort_changed_NEEDS_REBIND')
    baseline=r['baseline']
    require(type(baseline) is dict and set(baseline)=={'commit','catalog','execution'}
            and all(isinstance(v,str) and re.fullmatch('[a-f0-9]{64}',v) for v in baseline.values()),
            'hybrid_baseline')
    pairs=r['focus_pairs']
    require(type(pairs) is list and 0<len(pairs)<=1500 and all(type(p) is dict
            and set(p)=={'ticker','cik'} and isinstance(p['ticker'],str)
            and re.fullmatch('[A-Z][A-Z0-9.-]{0,13}',p['ticker'])
            and isinstance(p['cik'],str) and re.fullmatch('[0-9]{10}',p['cik']) for p in pairs),
            'hybrid_focus_pairs')
    require([(p['ticker'],p['cik']) for p in pairs]==sorted(set((p['ticker'],p['cik']) for p in pairs))
            and len({p['ticker'] for p in pairs})==len(pairs),'hybrid_focus_duplicate')
    now=hybrid_clock(utc_now()) if now is None else now
    first,last,decision,expiry=(hybrid_clock(r[k]) for k in
        ('not_before','available_at','decision_at','expires_at'))
    require(first<=last<=decision<=now<expiry and expiry-first<=timedelta(days=31), 'hybrid_window')
    for key in ('macro_start','financial_start','through'):
        require(isinstance(r[key],str) and date.fromisoformat(r[key]).isoformat()==r[key], 'hybrid_date')
    require(r['macro_start']<=r['through'] and r['financial_start']<=r['through']
            and r['through']<=decision.date().isoformat(), 'hybrid_date_window')
    rights=r['rights_sha256']
    require(type(rights) is dict and set(rights)=={'fred','sec','worldbank'}
            and all((isinstance(v,str) and re.fullmatch('[a-f0-9]{64}',v))
                    if _auto_provider_scope is None or _auto_provider_scope[k] else v is None
                    for k,v in rights.items()),
            'hybrid_rights_evidence_required')
    b=r['budget']
    require(type(b) is dict and set(b)=={'provider_gets','provider_bytes','transport_calls',
        'transport_reserved_bytes','write_bytes','active_seconds','max_chain_commits','max_issuers'}
        and all(type(v) is int and 0<v<=2**53-1 for v in b.values())
        and 480<=b['active_seconds']<=7200 and b['max_chain_commits']<=20000
        and b['max_issuers']<=20000,'hybrid_finite_budget')
    from tools.run_daily_market_session_gate import evaluate_market_session, mcal
    if mode=='HYBRID_DAILY':
        gate=evaluate_market_session(now_utc=decision,min_close_age_minutes=120)
        require(r['weekly'] is None and gate['ready'] and gate['session_date']==r['through'],
                'hybrid_daily_session')
    else:
        w=r['weekly']; day=date.fromisoformat(r['through']); monday=day-timedelta(days=day.weekday())
        schedule=mcal.get_calendar('NYSE').schedule(start_date=monday,end_date=monday+timedelta(days=4))
        require(type(w) is dict and set(w)=={'week_start','session'} and not schedule.empty
                and w==dict(week_start=monday.isoformat(),session=r['through'])
                and schedule.index[-1].strftime('%Y-%m-%d')==r['through']
                and schedule.iloc[-1]['market_close'].to_pydatetime()+timedelta(minutes=120)<=decision
                and expiry<=datetime.combine(monday+timedelta(days=7),datetime.min.time(),
                                               ZoneInfo('America/New_York')).astimezone(timezone.utc),
                'hybrid_weekly_session')
    return r


def authorize_hybrid(request, request_sha256, approval_reference, *, gh=None, context=None):
    """Reuse the existing A0 OWNER surface; hashes/flags cannot approve themselves."""
    if gh is None:
        from tools.alpaca_sip_campaign import gh_json
        gh=gh_json
    context=context or {k:os.environ.get(k,'') for k in
        ('GITHUB_REPOSITORY','GITHUB_REF','GITHUB_RUN_ID','GITHUB_RUN_ATTEMPT','GITHUB_SHA')}
    require(context['GITHUB_REPOSITORY']=='wscha231/r1000-quant-engine'
            and context['GITHUB_REF']=='refs/heads/master' and context['GITHUB_RUN_ATTEMPT']=='1'
            and context['GITHUB_SHA']==request['code_sha'] and context['GITHUB_RUN_ID'].isdigit(),
            'hybrid_live_context')
    match=re.fullmatch(r'https://github.com/wscha231/r1000-quant-engine/issues/448#issuecomment-([0-9]+)',
                       approval_reference)
    require(match is not None,'hybrid_owner_reference')
    c=gh('repos/wscha231/r1000-quant-engine/issues/comments/'+match[1])
    require(c.get('id')==int(match[1]) and c.get('author_association')=='OWNER'
            and c.get('user',{}).get('type')=='User' and c.get('created_at')==c.get('updated_at')
            and c.get('issue_url')=='https://api.github.com/repos/wscha231/r1000-quant-engine/issues/448'
            and hybrid_clock(request['available_at'])<=hybrid_clock(c.get('created_at'))
            <=hybrid_clock(utc_now()),'hybrid_owner_approval')
    records=[line[len(HYBRID_OWNER_TAG):] for line in c.get('body','').splitlines()
             if line.startswith(HYBRID_OWNER_TAG)]
    require(len(records)==1 and json.loads(records[0])==dict(schema='long-history-hybrid-owner-v1',
        request_sha256=request_sha256,producer_code_sha=request['code_sha'],
        purpose=request['purpose'],rights_sha256=request['rights_sha256'],
        expires_at=request['expires_at']),'hybrid_owner_scope')
    # Failed or concurrent executions consume this exact request identity too.
    # A new OWNER-reviewed recovery request, not an Actions rerun, is required.
    query=urlencode(dict(created='>='+request['not_before'],per_page=100))
    payload=gh('repos/wscha231/r1000-quant-engine/actions/workflows/long_history_research.yml/runs?'+query)
    runs=payload.get('workflow_runs')
    require(type(runs) is list and payload.get('total_count')==len(runs)<100,
            'hybrid_history_bound_NEEDS_REBIND')
    title='history-'+request['mode']+'-'+request_sha256
    same=[v for v in runs if v.get('display_title')==title]
    require(len(same)==1 and same[0].get('id')==int(context['GITHUB_RUN_ID'])
            and same[0].get('run_attempt')==1 and same[0].get('head_sha')==request['code_sha'],
            'hybrid_request_replay_or_unknown')
    return dict(approval_reference=approval_reference,request_sha256=request_sha256,
                owner_comment_sha256=digest(encoded(c)),run_id=int(context['GITHUB_RUN_ID']))


AUTO_WORKFLOW='.github/workflows/long_history_research.yml'
AUTO_OWNER_TAG='LONG_HISTORY_AUTO_OWNER_V1 '
AUTO_RESOURCES=('provider_gets','provider_bytes','transport_calls','transport_reserved_bytes',
                'write_bytes','active_seconds')
# Execution dependencies, including the pre-Source offline callers. No test or
# runtime file can be changed under an unchanged external standing profile.
AUTO_PINS=(AUTO_WORKFLOW,'tools/long_history_lake.py','tools/macro_history_sources.py',
    'tools/macro_technical_study.py','tools/macro_research_cycle.py','tools/macro_research_checkpoint.py',
    'tools/configure_macro_research_drive.py','tools/research_data_access.py','tools/research_model_inputs.py',
    'tools/run_data_freshness_contract.py','tools/prepare_a1_reader_generation.py',
    'tools/alpaca_sip_private_backfill_v1.py','tools/twelve_private_capture.py',
    'tools/alpaca_sip_source_revision.py','tools/alpaca_sip_managed_refresh.py',
    'tools/alpaca_sip_campaign.py','tools/prepare_a1_managed_ohlcv.py',
    'tools/run_daily_market_session_gate.py','tools/run_pr_validation.py','r1000_legacy_input_guard.py',
    'tests/research_data_access_smoke.py','tests/research_model_inputs_smoke.py',
    'tests/a1_reader_generation_binding_smoke.py','tests/alpaca_sip_private_backfill_v1_smoke.py',
    'tests/long_history_lake_smoke.py','tests/macro_technical_evidence_smoke.py',
    'tests/macro_research_cycle_smoke.py','data_static/research_dataset_registry_v1.json',
    'docs/research_dataset_generation_v1.schema.json','docs/research_data_access.json',
    'docs/macro_indicator_registry.json','docs/run287_chameleon_macro_inputs_contract.json')


def auto_profile(raw, expected_sha256, *, now=None):
    """An immutable external allocation, not a profile or budget issuer."""
    require(type(raw) is bytes and 0<len(raw)<=65536 and digest(raw)==expected_sha256,
            'auto_original_profile_hash')
    def unique(pairs):
        value={}
        for k,v in pairs:
            require(k not in value,'auto_duplicate_key'); value[k]=v
        return value
    r=json.loads(raw,object_pairs_hook=unique,
                 parse_constant=lambda _:require(False,'auto_nonfinite_json'))
    fixed={'schema','profile_id','mode','purpose','code_sha','code_pins','registry_sha256',
        'roster_sha256','cohort_sha256','mapping_object_sha256','mapping_source_sha256',
        'focus_pairs','baseline','macro_start','financial_start','available_at','not_before',
        'expires_at','rights_sha256','repository_id','workflow_id','workflow_path',
        'first_run_number','last_run_number','per_run_allowance','total_reservation','opening_floor','provider_scope'}
    require(type(r) is dict and set(r)==fixed and r['schema']=='long-history-hybrid-auto-v1'
            and r['mode']=='HYBRID_AUTO' and r['purpose']=='PRIVATE_NONCOMMERCIAL_RESEARCH'
            and isinstance(r['profile_id'],str) and re.fullmatch('[A-Za-z0-9_-]{1,65}',r['profile_id']),
            'auto_profile_fields')
    require(type(r['provider_scope']) is dict and set(r['provider_scope'])=={'sec','fred','worldbank'}
            and all(type(v) is bool for v in r['provider_scope'].values())
            and any(r['provider_scope'].values()),'auto_explicit_provider_scope')
    now=hybrid_clock(utc_now()) if now is None else now
    first,available,expiry=(hybrid_clock(r[k]) for k in ('not_before','available_at','expires_at'))
    require(first<=available<=now<expiry and expiry-first<=timedelta(days=31),'auto_original_window')
    require(all(type(r[k]) is int and 0<r[k]<=2**53-1 for k in
        ('repository_id','workflow_id','first_run_number','last_run_number'))
        and r['first_run_number']<=r['last_run_number'] and r['workflow_path']==AUTO_WORKFLOW,
        'auto_counter_identity')
    require(isinstance(r['code_sha'],str) and re.fullmatch('[a-f0-9]{40}',r['code_sha'])
            and type(r['code_pins']) is dict and set(r['code_pins'])==set(AUTO_PINS)
            and all(isinstance(v,str) and re.fullmatch('[a-f0-9]{64}',v)
                    for v in r['code_pins'].values()),'auto_code_pins')
    b=r['per_run_allowance']
    require(type(b) is dict and set(b)==set(AUTO_RESOURCES)|{'max_chain_commits','max_issuers'}
            and all(type(v) is int and 0<v<=2**53-1 for v in b.values())
            and b['active_seconds']==7200 and b['max_chain_commits']<=20000
            and b['max_issuers']<=20000,'auto_per_run_allowance')
    slots=r['last_run_number']-r['first_run_number']+1
    for name in ('total_reservation','opening_floor'):
        require(type(r[name]) is dict and set(r[name])==set(AUTO_RESOURCES)
                and all(type(v) is int and 0<=v<=2**53-1 for v in r[name].values()),'auto_total_shape')
    require(r['total_reservation']=={k:slots*b[k] for k in AUTO_RESOURCES},'auto_total_not_full_slots')
    # Validate the rest through the fixed-v1 contract on a runtime-derived view.
    # That view never replaces, reissues or hashes as the original OWNER profile.
    auto_request(r,expected_sha256,now=now)
    return r


def auto_request(profile, profile_sha256, *, now=None, run=None, reservation=None):
    now=hybrid_clock(utc_now()) if now is None else now
    from tools.run_daily_market_session_gate import evaluate_market_session, mcal
    local=now.astimezone(ZoneInfo('America/New_York'))
    weekly=local.weekday()>=5
    gate=evaluate_market_session(now_utc=now,min_close_age_minutes=120,
                                 max_close_age_hours=96 if weekly else 18)
    require(gate['ready'],'auto_no_completed_due_session')
    through=gate['session_date']; monday=date.fromisoformat(through)
    monday-=timedelta(days=monday.weekday())
    expiry=hybrid_clock(profile['expires_at'])
    if weekly:
        schedule=mcal.get_calendar('NYSE').schedule(start_date=monday,end_date=monday+timedelta(days=4))
        require(not schedule.empty and schedule.index[-1].strftime('%Y-%m-%d')==through,
                'auto_week_not_complete')
        expiry=min(expiry,datetime.combine(monday+timedelta(days=7),datetime.min.time(),
                                          ZoneInfo('America/New_York')).astimezone(timezone.utc))
    keys=('purpose','registry_sha256','roster_sha256','cohort_sha256','mapping_object_sha256',
          'mapping_source_sha256','focus_pairs','baseline','macro_start','financial_start',
          'available_at','not_before','rights_sha256')
    r={k:copy.deepcopy(profile[k]) for k in keys}
    r.update(schema='long-history-hybrid-v1',request_id=profile['profile_id']+'-'+str((run or {}).get('run_number','prepare')),
        mode='HYBRID_WEEKLY' if weekly else 'HYBRID_DAILY',code_sha=os.environ.get('GITHUB_SHA'),
        through=through,decision_at=now.isoformat(),expires_at=expiry.isoformat(),
        weekly=dict(week_start=monday.isoformat(),session=through) if weekly else None,
        budget=copy.deepcopy(profile['per_run_allowance']))
    raw=encoded(r); hybrid_request(raw,digest(raw),r['mode'],now=now,
                                   _auto_provider_scope=profile['provider_scope'])
    r['_auto']=dict(profile_sha256=profile_sha256,original_available_at=profile['available_at'],
        original_not_before=profile['not_before'],original_expires_at=profile['expires_at'],
        observed_at=now.isoformat(),selected_session=through,run=copy.deepcopy(run),
        provider_scope=copy.deepcopy(profile['provider_scope']),
        reservation=copy.deepcopy(reservation),code_pins_sha256=digest(encoded(profile['code_pins'])))
    return r


def auto_slot_reservation(profile, run_number):
    require(type(run_number) is int and profile['first_run_number']<=run_number<=profile['last_run_number'],
            'auto_run_number_outside_original_allocation')
    used=run_number-profile['first_run_number']+1
    total=profile['last_run_number']-profile['first_run_number']+1
    charged={k:used*profile['per_run_allowance'][k] for k in AUTO_RESOURCES}
    return dict(metric='FULL_COUNTER_SLOTS_NOT_ACTUAL_USAGE_NO_REFUNDS',consumed_slots=used,
        allocated_slots=total,reserved_allowance=charged,
        cumulative_with_opening_floor={k:profile['opening_floor'][k]+charged[k] for k in AUTO_RESOURCES},
        remaining_allowance={k:profile['total_reservation'][k]-charged[k] for k in AUTO_RESOURCES},
        actual_failed_wire_bytes=None,actual_Drive_API_requests=None)


def verify_auto_code(profile, context, gh):
    """Reuse the existing deployed ancestor + exact local/remote byte contract."""
    import base64
    import yaml
    head=context['GITHUB_SHA']; repo='repos/wscha231/r1000-quant-engine'
    compare=gh(repo+'/compare/'+profile['code_sha']+'...'+head)
    require(compare.get('status') in ('identical','ahead')
            and compare.get('merge_base_commit',{}).get('sha')==profile['code_sha'],'auto_deployed_ancestor')
    for path,pin in profile['code_pins'].items():
        remote=gh(repo+'/contents/'+path+'?'+urlencode(dict(ref=head)))
        require(remote.get('encoding')=='base64' and remote.get('type')=='file'
                and digest(base64.b64decode(remote.get('content',''),validate=False))==pin
                and digest((ROOT/path).read_bytes().replace(b'\r\n',b'\n'))==pin,
                'auto_deployed_code_changed_NEEDS_REBIND')
    workflow=yaml.safe_load((ROOT/AUTO_WORKFLOW).read_text(encoding='utf-8'))
    jobs=workflow['jobs']; require(set(jobs)=={'history'},'auto_one_fixed_job')
    job=jobs['history']; require('strategy' not in job,'auto_no_matrix')
    require(job.get('timeout-minutes')==120 and job.get('if','').endswith(
        " && ((inputs.hybrid_refresh_mode || vars.LONG_HISTORY_REFRESH_MODE || 'LEGACY') != 'HYBRID_AUTO' || github.run_attempt == 1)"),
        'auto_whole_job_reservation_and_rerun_gate')
    steps=job['steps']; name='Collect full history, persist changes, verify clean consumption'
    collector=[s for s in steps if s.get('name')==name]
    require(len(collector)==1 and collector[0].get('run','').count('python tools/long_history_lake.py')==1
            and sum(s.get('run','').count('python tools/long_history_lake.py') for s in steps)==2
            and len([s for s in steps if s.get('name')=='Finalize one pinned stored generation without collection'
                and s.get('if')=="${{ inputs.finalize_commit_sha256 != '' }}"])==1,
            'auto_one_collector_invocation')


def authorize_auto(profile, profile_sha256, approval_reference, *, gh=None, context=None):
    if gh is None:
        from tools.alpaca_sip_campaign import gh_json
        gh=gh_json
    names=('GITHUB_REPOSITORY','GITHUB_REPOSITORY_ID','GITHUB_REF','GITHUB_RUN_ID','GITHUB_RUN_NUMBER',
           'GITHUB_RUN_ATTEMPT','GITHUB_SHA','GITHUB_EVENT_NAME','GITHUB_JOB','GITHUB_ACTIONS',
           'GITHUB_WORKFLOW_REF','GITHUB_WORKFLOW_SHA')
    context=dict(os.environ) if context is None else context
    require(all(isinstance(context.get(k),str) and context[k] for k in names),'auto_live_context')
    repo='wscha231/r1000-quant-engine'; prefix='repos/'+repo
    require(context['GITHUB_REPOSITORY']==repo and context['GITHUB_REF']=='refs/heads/master'
            and context['GITHUB_JOB']=='history' and context['GITHUB_ACTIONS']=='true'
            and context['GITHUB_RUN_ATTEMPT']=='1'
            and context['GITHUB_EVENT_NAME'] in ('schedule','workflow_dispatch')
            and context['GITHUB_WORKFLOW_REF']==repo+'/'+AUTO_WORKFLOW+'@refs/heads/master'
            and context['GITHUB_WORKFLOW_SHA']==context['GITHUB_SHA']
            and re.fullmatch('[a-f0-9]{40}',context['GITHUB_SHA'])
            and all(re.fullmatch('[1-9][0-9]*',context[k]) for k in
                    ('GITHUB_REPOSITORY_ID','GITHUB_RUN_ID','GITHUB_RUN_NUMBER')),'auto_live_identity')
    run=gh(prefix+'/actions/runs/'+context['GITHUB_RUN_ID'])
    require(all(type(run.get(k)) is int for k in ('id','run_number','run_attempt','workflow_id'))
            and run['id']==int(context['GITHUB_RUN_ID']) and run['run_attempt']==1
            and run['run_number']==int(context['GITHUB_RUN_NUMBER'])
            and run['workflow_id']==profile['workflow_id'] and run.get('path')==AUTO_WORKFLOW
            and run.get('repository',{}).get('id')==profile['repository_id']==int(context['GITHUB_REPOSITORY_ID'])
            and run['repository'].get('full_name')==repo
            and run.get('head_repository',{}).get('id')==profile['repository_id']
            and run['head_repository'].get('full_name')==repo
            and run.get('head_sha')==context['GITHUB_SHA'] and run.get('head_branch')=='master'
            and run.get('event')==context['GITHUB_EVENT_NAME'],'auto_rest_run_mismatch')
    now=hybrid_clock(utc_now())
    require(hybrid_clock(profile['not_before'])<=hybrid_clock(run.get('created_at'))<=now
            <hybrid_clock(profile['expires_at']),'auto_run_original_window')
    reservation=auto_slot_reservation(profile,run['run_number'])
    workflow=gh(prefix+'/actions/workflows/'+str(profile['workflow_id']))
    require(workflow.get('id')==profile['workflow_id'] and workflow.get('path')==AUTO_WORKFLOW
            and workflow.get('state')=='active','auto_workflow_identity')
    match=re.fullmatch(r'https://github.com/wscha231/r1000-quant-engine/issues/448#issuecomment-([0-9]+)',
                       approval_reference)
    require(match is not None,'auto_owner_reference')
    c=gh(prefix+'/issues/comments/'+match[1])
    require(c.get('id')==int(match[1]) and c.get('author_association')=='OWNER'
            and c.get('user',{}).get('type')=='User' and c.get('created_at')==c.get('updated_at')
            and c.get('issue_url')=='https://api.github.com/repos/'+repo+'/issues/448'
            and hybrid_clock(profile['available_at'])<=hybrid_clock(c.get('created_at'))<=now,
            'auto_owner_approval')
    records=[line[len(AUTO_OWNER_TAG):] for line in c.get('body','').splitlines() if line.startswith(AUTO_OWNER_TAG)]
    require(len(records)==1 and json.loads(records[0])==dict(schema='long-history-auto-owner-v1',
        profile_sha256=profile_sha256,code_pins_sha256=digest(encoded(profile['code_pins'])),
        purpose=profile['purpose'],rights_sha256=profile['rights_sha256'],expires_at=profile['expires_at']),
        'auto_owner_original_profile')
    verify_auto_code(profile,context,gh)
    return dict(approval_reference=approval_reference,profile_sha256=profile_sha256,
        owner_comment_sha256=digest(encoded(c)),run={k:run[k] for k in
            ('id','run_number','run_attempt','workflow_id','head_sha','event','created_at')},
        reservation=reservation)


def claim_auto_invocation(authorization):
    # This is job-local exclusion, NOT a durable ledger. The pinned no-matrix
    # job is the sole caller. Identical second calls must fail too (unlike the
    # content-addressed exclusive() helper's intentional idempotent readback).
    root=Path(os.environ.get('RUNNER_TEMP',''))
    require(os.environ.get('RUNNER_TEMP') and root.is_dir()
            and not any(p.is_symlink() for p in [root,*root.parents]),'auto_runner_temp')
    run=authorization['run']
    path=root/('history-auto-'+str(run['id'])+'-'+str(run['run_attempt'])+'.entry')
    try:
        with path.open('xb') as stream:
            stream.write(encoded(dict(profile_sha256=authorization['profile_sha256'],run=run)))
        path.chmod(0o600)
    except FileExistsError:
        require(False,'auto_collector_already_invoked')


class HybridBudget:
    """Ephemeral ceiling reservations, never a new ledger or actual-wire claim."""
    def __init__(self, request, *, live_transport=True, monotonic=time.monotonic):
        self.limits=request['budget']; self.monotonic=monotonic; self.start=monotonic()
        self.allowed_seconds=min(self.limits['active_seconds'],max(0.0,
            (hybrid_clock(request['expires_at'])-hybrid_clock(utc_now())).total_seconds()))
        self.live_transport=live_transport; self.alarm_active=False
        self.used=dict(provider_gets=0,provider_bytes=0,transport_calls=0,
                       transport_reserved_bytes=0,write_bytes=0)
        self.returned_bytes=0
    def remaining_seconds(self):
        return max(0.0,self.allowed_seconds-(self.monotonic()-self.start))
    def check(self):
        require(self.remaining_seconds()>0,'hybrid_active_deadline')
    def reserve(self, **amounts):
        self.check()
        require(all(self.used[k]+v<=self.limits[k] for k,v in amounts.items()),'hybrid_budget_exhausted')
        for k,v in amounts.items(): self.used[k]+=v
    def provider(self, gets, bytes_):
        self.reserve(provider_gets=gets,provider_bytes=bytes_)
    def summary(self):
        return dict(reserved=dict(self.used),active_seconds=self.monotonic()-self.start,
            returned_application_bytes=self.returned_bytes,actual_provider_gets=None,
            actual_failed_wire_bytes=None,actual_Drive_API_requests=None,
            metric='FULL_FETCH_AND_CLI_BODY_CEILINGS_NO_REFUNDS_NOT_WIRE_OR_DRIVE_QUOTA')


class HybridTransport(RcloneTransport):
    # Keep the original per-pack verification path. The batch subprocess bypasses
    # call(), so it is not silently exempted from the opt-in reservation meter.
    read_pack_batch=None
    def __init__(self, remote, budget):
        self.hybrid_budget=budget
        super().__init__(remote)
    def call(self, *args):
        require(args and args[0]!='mkdir','hybrid_existing_root_required')
        self.hybrid_budget.reserve(transport_calls=1,transport_reserved_bytes=HYBRID_READ_RESERVATION)
        result=super().call(*args)
        self.hybrid_budget.returned_bytes+=len(result)
        self.hybrid_budget.check()
        return result
    def names(self, prefix):
        result=super().names(prefix)
        if prefix==PREFIX+'/commits':
            require(len(result)<=self.hybrid_budget.limits['max_chain_commits'],
                    'hybrid_chain_bound_NEEDS_REBIND')
        return result
    def write(self, path, raw):
        self.hybrid_budget.reserve(write_bytes=len(raw))
        return super().write(path,raw)


def hybrid_continuation_identity(r):
    if '_auto' in r:
        return digest(encoded(dict(standing_profile_sha256=r['_auto']['profile_sha256'])))
    keys=('purpose','code_sha','registry_sha256','roster_sha256','cohort_sha256',
          'mapping_object_sha256','mapping_source_sha256','focus_pairs',
          'macro_start','financial_start','rights_sha256')
    return digest(encoded({k:r[k] for k in keys}))


def hybrid_execution_ready(receipt, *, allow_source_scope=False):
    complete=('cycle_scope' not in receipt or receipt['cycle_scope'].get('requested_cycle_complete') is True)
    return complete and receipt['quality_status']!='PARTIAL' and (
        receipt['study_recomputed_from_drive'] or (allow_source_scope
            and type(receipt.get('source_cycle_readback')) is dict))


def hybrid_source_scope_readback(lake, summary):
    """Only an explicitly FRED-disabled AUTO cycle; never a macro-study receipt."""
    auto=summary.get('standing_auto',{})
    require(auto.get('provider_scope',{}).get('fred') is False,'hybrid_source_scope_only')
    detail=lake.catalog['config']['hybrid_refresh'];keys=detail['checked_keys']
    require(digest(encoded(keys))==summary['checked_scope_sha256']
            and keys==sorted(set(keys)) and bool(keys),'hybrid_source_scope_binding')
    observed=[]
    for key in keys:
        require(not key.startswith(('current/','alfred/')),'hybrid_disabled_fred_consumption')
        provider='sec' if key.startswith('sec/') else 'worldbank' if key.startswith('worldbank/') else None
        require(provider and auto['provider_scope'].get(provider) is True,'hybrid_disabled_provider_consumption')
        entry=lake.catalog['datasets'][key]
        require(entry['status'] in ('COLLECTED','UNCHANGED'),'hybrid_source_scope_blocked')
        rows=lake.get_records(key)
        observed.append(dict(key=key,normalized=entry['normalized'],objects=entry['objects'],rows=len(rows)))
    return dict(schema='long-history-hybrid-source-readback-v1',commit=lake.parent,
        catalog=digest(encoded(lake.catalog)),profile_sha256=auto['profile_sha256'],
        checked_scope_sha256=summary['checked_scope_sha256'],checked=observed,
        macro_regime_ready=False,whole_macro_complete=False,source_admission=False,historical_pit_certified=False)


def prepare_hybrid_scope(lake, request, request_sha256, budget, authorization):
    """Resolve only the existing verified descendant chain, never auto-rebind."""
    require(lake.parent and not lake.pending and lake.catalog==lake.before,'hybrid_unclean_parent')
    parent,current=lake.restore_catalog()
    require(parent==lake.parent and current==lake.before,'hybrid_parent_changed_NEEDS_REBIND')
    latest=lake.verified_execution()
    require(hybrid_execution_ready(latest,allow_source_scope='_auto' in request),
            'hybrid_parent_execution_incomplete')
    baseline=request['baseline']; cursor=parent; descendants=[]; base_catalog=None
    identity=hybrid_continuation_identity(request)
    for _ in range(budget.limits['max_chain_commits']):
        require(cursor,'hybrid_baseline_not_ancestor_NEEDS_REBIND')
        commit=json.loads(lake.read_hash('commits',cursor))
        catalog=json.loads(lake.read_hash('catalogs',commit['catalog']))
        if cursor==baseline['commit']:
            require(commit['catalog']==baseline['catalog'],'hybrid_baseline_catalog')
            base_catalog=catalog
            break
        detail=catalog.get('config',{}).get('hybrid_refresh',{})
        require((catalog.get('code_sha')==request['code_sha'] or '_auto' in request)
                and detail.get('continuation_identity')==identity
                and detail.get('resolved_parent')==commit['parent']
                and detail.get('through','9999')<=request['through'],
                'hybrid_lineage_changed_NEEDS_REBIND')
        require(detail.get('request_sha256')!=request_sha256,'hybrid_request_already_executed')
        descendants.append(cursor); cursor=commit['parent']
    require(base_catalog is not None,'hybrid_chain_bound_NEEDS_REBIND')
    view=copy.copy(lake); view.parent=baseline['commit']; view.catalog=base_catalog
    original=latest if parent==baseline['commit'] else view.verified_execution()
    require(original['execution_receipt_sha256']==baseline['execution']
            and original['study_recomputed_from_drive'],'hybrid_baseline_execution')
    cohort,mapping_sha,mapping=verified_cohort_source(lake)
    universe=lake.catalog['datasets']['universe/cohort']
    require(mapping_sha==request['mapping_object_sha256'] and
            universe.get('sec_ticker_mapping_source_sha256')==request['mapping_source_sha256'],
            'hybrid_mapping_changed_NEEDS_REBIND')
    members=json.loads(cohort)['rows']
    names={r['ticker'].upper().replace('.','-') for r in members}; lookup=sec_ticker_lookup(mapping)
    require(all(p['ticker'].upper().replace('.','-') in names
                and lookup.get(p['ticker'].upper().replace('.','-'))=={p['cik']}
                for p in request['focus_pairs']),'hybrid_ticker_cik_proof')
    prior=prior_sec_mapping(lake)
    groups,_,_=issuer_queue(members,mapping,prior)
    focus={p['cik'] for p in request['focus_pairs']}
    require(focus<=set(groups),'hybrid_focus_outside_cohort')
    selected=focus if request['mode']=='HYBRID_DAILY' else set(groups)
    providers=request.get('_auto',{}).get('provider_scope',dict(sec=True,fred=True,worldbank=True))
    if not providers['sec']: selected=set()
    require(len(selected)<=budget.limits['max_issuers'],'hybrid_issuer_budget')
    specs=[s for s in registry()['series'] if s.get('collection_scope')!='scoped_alfred_only']
    require(len(specs)==34 and len(ARCHIVES)==12,'hybrid_macro_scope_changed_NEEDS_REBIND')
    weekly=request['mode']=='HYBRID_WEEKLY'
    fred_gets=(len(specs)*3+(len(ARCHIVES)*3*FRED_MAX_PAGES if weekly else 0)) if providers['fred'] else 0
    wb_gets=len(WB_INDICATORS)*3 if weekly and providers['worldbank'] else 0
    gets=len(selected)*6+fred_gets+wb_gets
    bytes_=len(selected)*6*(32*1024*1024+1)+fred_gets*SCOPED_PAGE_RESERVATION_BYTES+wb_gets*(32*1024*1024+1)
    require(gets<=budget.limits['provider_gets'] and bytes_<=budget.limits['provider_bytes'],
            'hybrid_provider_budget_preflight')
    keys={'sec/'+c for c in selected}
    if providers['fred']:
        keys|={'current/'+s['id'] for s in specs}
        if weekly:keys|={'alfred/'+s for s in ARCHIVES}
    if weekly and providers['worldbank']:keys|={'worldbank/'+i for i in WB_INDICATORS}
    require(keys,'hybrid_no_due_authorized_scope')
    return dict(request=request,request_sha256=request_sha256,budget=budget,authorization=authorization,
        cohort=cohort,mapping=mapping,prior_mapping=prior,groups=groups,selected=selected,checked_keys=keys,
        attempted_keys=set(),completed_keys=set(),
        focus_keys={'sec/'+c for c in focus},provider_scope=providers,resolved_parent=parent,
        resolved_parent_execution=latest['execution_receipt_sha256'],descendants_verified=len(descendants),
        continuation_identity=identity,provider_reservation_plan=dict(gets=gets,bytes=bytes_))


def finish_hybrid_cycle(lake, scope):
    old=lake.before['datasets']; now=lake.catalog['datasets']; checked=scope['checked_keys']
    require(scope['attempted_keys']==checked,'hybrid_incomplete_request_scope')
    require(set(now)-set(old)<=checked,'hybrid_unrequested_dataset')
    for key in set(old)-checked:
        require(now.get(key)==old[key],'hybrid_unchecked_dataset_changed')
    for key in checked & set(old) & set(now):
        before,after=old[key],now[key]
        if after.get('status')=='COLLECTED' and before.get('objects')==after.get('objects'):
            after.update(status='UNCHANGED',changed=False)
            for field in ('retrieved_at','first_available_at'):
                if field in before: after[field]=before[field]
    counts={s:sum(now.get(k,{}).get('status')==s for k in checked) for s in
            ('COLLECTED','UNCHANGED','COVERAGE_GAP','BLOCKED','STALE_RETAINED')}
    unchecked=sorted(set(old)-checked)
    providers=scope['provider_scope']
    disabled={key:'RIGHTS_BLOCKED_OR_DISABLED_BY_OWNER_PROFILE' for key in unchecked
        if (key.startswith('sec/') and not providers['sec'])
        or (key.startswith(('current/','alfred/')) and not providers['fred'])
        or (key.startswith('worldbank/') and not providers['worldbank'])}
    not_due=[k for k in unchecked if scope['request']['mode']=='HYBRID_DAILY'
             and k.startswith(('alfred/','worldbank/')) and k not in disabled]
    complete=scope['completed_keys']==checked and all(
        now.get(k,{}).get('status') in ('COLLECTED','UNCHANGED') for k in checked)
    summary=dict(schema='long-history-hybrid-cycle-scope-v1',mode=scope['request']['mode'],
        request_sha256=scope['request_sha256'],effective_through=scope['request']['through'],
        checked_scope_sha256=digest(encoded(sorted(checked))),checked_datasets=len(checked),
        checked_status_counts=counts,focus_current=sum(k in scope['completed_keys'] and
            now.get(k,{}).get('status') in ('COLLECTED','UNCHANGED') for k in scope['focus_keys']),
        focus_requested=len(scope['focus_keys']),
        retained_NOT_CHECKED_THIS_CYCLE=len(unchecked),retained_NOT_DUE=len(not_due),
        unchecked_scope_sha256=digest(encoded(unchecked)),requested_cycle_complete=complete,
        full_universe_current=False,historical_pit_certified=False,source_admission=False,
        integrity_scope='FULL_EXISTING_HISTORY_NOT_A_FOCUS_ONLY_RESTORE',
        full_restore_elapsed_cost='UNKNOWN_UNTIL_MEASURED',
        collection_budget=scope['budget'].summary())
    if '_auto' in scope['request']:
        summary['standing_auto']=copy.deepcopy(scope['request']['_auto'])
        summary.update(provider_scope=copy.deepcopy(providers),provider_exclusions=disabled,
                       macro_regime_ready=False,whole_macro_complete=False,data_ready=False)
    scope['summary']=summary
    scope['detail']=dict(request_sha256=scope['request_sha256'],mode=scope['request']['mode'],
        continuation_identity=scope['continuation_identity'],baseline=scope['request']['baseline'],
        resolved_parent=scope['resolved_parent'],resolved_parent_execution=scope['resolved_parent_execution'],
        descendants_verified=scope['descendants_verified'],through=scope['request']['through'],
        checked_keys=sorted(checked),NOT_CHECKED_THIS_CYCLE=unchecked,NOT_DUE=not_due,
        summary_sha256=digest(encoded(summary)),cycle_scope=summary,authorization=scope['authorization'])
    if '_auto' in scope['request']:
        scope['detail']['standing_auto']=copy.deepcopy(scope['request']['_auto'])
    return summary


def fred_missing(rows,missing):
    dates=sorted(set(missing)|{r['observation_date'] for r in rows if r['value'] is None})
    return dict(missing_values=len(missing)+sum(r['value'] is None for r in rows),
        missing_observation_dates=dates)


def sec_ticker_lookup(mapping):
    require(isinstance(mapping,dict) and bool(mapping),'sec_ticker_mapping_schema')
    lookup={}
    for row in mapping.values():
        require(isinstance(row,dict),'sec_ticker_mapping_row')
        symbol=row.get('ticker')
        require(isinstance(symbol,str) and bool(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]{0,14}',symbol)),
                'sec_ticker_identity')
        raw_cik=row.get('cik_str')
        require(type(raw_cik) in (int,str) and str(raw_cik).isdigit() and int(raw_cik)>0,
                'cik_identity')
        cik=str(raw_cik).zfill(10)
        require(re.fullmatch(r'\d{10}',cik),'cik_identity')
        lookup.setdefault(symbol.upper().replace('.','-'),set()).add(cik)
    return lookup


def verified_cohort_source(lake,catalog=None):
    """Verify both source roles; legacy order is valid only for reviewed producers."""
    catalog=catalog or lake.catalog
    old=catalog['datasets'].get('universe/cohort',{})
    objects=old.get('raw_objects')
    require(old.get('evidence')=='CURRENT_COHORT_NOT_HISTORICAL_MEMBERSHIP'
            and isinstance(objects,list) and len(objects)==2 and objects[0]!=objects[1],
            'cohort_source_role')
    role=old.get('source_role_contract_version')
    if role=='cohort-sec-mapping-v1':
        cohort_sha=old.get('cohort_source_object_sha256')
        mapping_sha=old.get('sec_ticker_mapping_object_sha256')
        require(isinstance(cohort_sha,str) and isinstance(mapping_sha,str)
                and set(objects)=={cohort_sha,mapping_sha}
                and isinstance(old.get('sec_ticker_mapping_retrieved_at'),str),
                'cohort_source_role')
    else:
        require(role is None and catalog.get('code_sha') in LEGACY_SEC_MAPPING_PRODUCERS,
                'cohort_legacy_producer')
        cohort_sha,mapping_sha=objects
    cohort=unpacked(lake.get_bytes(cohort_sha))
    require(digest(cohort)==COHORT_SHA,'durable_cohort_identity')
    payload=json.loads(cohort)
    require(isinstance(payload,dict) and isinstance(payload.get('rows'),list)
            and type(payload.get('candidate_count')) is int
            and payload['candidate_count']==len(payload['rows'])==old.get('requested_securities')
            and isinstance(payload.get('as_of'),str), 'durable_cohort_schema')
    date.fromisoformat(payload['as_of'])
    mapping_raw=unpacked(lake.get_bytes(mapping_sha))
    if role=='cohort-sec-mapping-v1':
        require(digest(mapping_raw)==old.get('sec_ticker_mapping_source_sha256'),
                'sec_ticker_mapping_source_hash')
    mapping=json.loads(mapping_raw)
    sec_ticker_lookup(mapping)
    return cohort,mapping_sha,mapping


def prior_sec_mapping(lake,with_sources=False):
    """Retain verified official mappings across generations, without current eligibility."""
    if 'universe/cohort' not in lake.catalog['datasets']:
        return (None,[]) if with_sources else None
    sources=[]; seen=set()
    _,sha,mapping=verified_cohort_source(lake)
    sources.append((sha,mapping)); seen.add(sha)
    historical=lake.catalog['datasets']['universe/cohort'].get('historical_sec_mapping_object_sha256s')
    if historical is not None:
        require(isinstance(historical,list) and len(historical)==len(set(historical)),
                'historical_mapping_roles')
        for source_sha in historical:
            require(isinstance(source_sha,str) and re.fullmatch(r'[0-9a-f]{64}',source_sha),
                    'historical_mapping_role_sha')
            if source_sha in seen: continue
            value=json.loads(unpacked(lake.get_bytes(source_sha)))
            sec_ticker_lookup(value)
            sources.append((source_sha,value)); seen.add(source_sha)
    else:
        cursor=lake.parent
        while cursor:
            commit=json.loads(lake.read_hash('commits',cursor))
            cursor=commit['parent']
            if cursor is None: break
            older=json.loads(lake.read_hash('commits',cursor))
            catalog=json.loads(lake.read_hash('catalogs',older['catalog']))
            if 'universe/cohort' not in catalog['datasets']:
                continue
            _,source_sha,value=verified_cohort_source(lake,catalog)
            if source_sha not in seen:
                sources.append((source_sha,value)); seen.add(source_sha)
    rows={(row['ticker'],str(row['cik_str']).zfill(10)) for _,mapping in sources
          for row in mapping.values()}
    combined={str(i):dict(ticker=ticker,cik_str=cik)
              for i,(ticker,cik) in enumerate(sorted(rows))}
    result=(combined if combined else None,[sha for sha,_ in sources])
    return result if with_sources else result[0]


def issuer_queue(members, mapping, prior_mapping=None):
    require(isinstance(members,list) and len(members)>=1000,'cohort_below_1000')
    symbols = [r['ticker'] for r in members]
    require(len(symbols)==len(set(symbols)), 'duplicate_security')
    lookup=sec_ticker_lookup(mapping)
    prior=sec_ticker_lookup(prior_mapping) if prior_mapping is not None else {}
    groups,missing,resolution={},[],[]
    for symbol in symbols:
        require(isinstance(symbol,str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]{0,14}',symbol),'ticker_identity')
        key=symbol.upper().replace('.','-')
        matches=lookup.get(key,set())
        prior_matches=prior.get(key,set())
        if len(matches)==1:
            cik=next(iter(matches))
            groups.setdefault(cik,[]).append(symbol)
            history=sorted(prior_matches-{cik})
            for old_cik in history:
                groups.setdefault(old_cik,[]).append(symbol)
            resolution.append(dict(ticker=symbol,cik=cik,
                identity_status=('CURRENT_SEC_MAPPING_WITH_HISTORY_CONFLICT' if history
                    else 'CURRENT_SEC_MAPPING'),
                history_retained_ciks=history,current_mapping_present=True,
                lifecycle_review_required=bool(history)))
        elif not matches and prior_matches:
            history=sorted(prior_matches)
            for old_cik in history:
                groups.setdefault(old_cik,[]).append(symbol)
            if len(history)>1:
                missing.append(dict(ticker=symbol,reason='CIK_HISTORICAL_AMBIGUOUS',
                    current_ciks=[],prior_ciks=history))
            resolution.append(dict(ticker=symbol,cik=history[0] if len(history)==1 else None,
                identity_status=('PRIOR_SEC_MAPPING_RETAINED_LIFECYCLE_REVIEW'
                    if len(history)==1 else 'PRIOR_SEC_MAPPING_AMBIGUOUS_LIFECYCLE_REVIEW'),
                history_retained_ciks=history,current_mapping_present=False,
                lifecycle_review_required=True))
        else:
            history=sorted(prior_matches)
            for old_cik in history:
                groups.setdefault(old_cik,[]).append(symbol)
            missing.append(dict(ticker=symbol,reason='CIK_MISSING_OR_AMBIGUOUS',
                current_ciks=sorted(matches),prior_ciks=sorted(prior_matches)))
            resolution.append(dict(ticker=symbol,cik=None,identity_status='CIK_MISSING_OR_AMBIGUOUS',
                history_retained_ciks=history,current_mapping_present=bool(matches),
                lifecycle_review_required=True))
    return groups,missing,resolution


def sec_submissions_profile(raw,cik):
    payload=json.loads(raw)
    require(str(payload.get('cik','')).zfill(10)==cik,'sec_submissions_identity')
    recent=((payload.get('filings') or {}).get('recent') or {})
    forms=recent.get('form')
    require(isinstance(forms,list) and all(isinstance(v,str) for v in forms),'sec_submissions_forms')
    accessions=recent.get('accessionNumber')
    require(isinstance(accessions,list) and len(accessions)==len(forms)
            and all(isinstance(v,str) and re.fullmatch(r'\d{10}-\d{2}-\d{6}',v)
                    for v in accessions),
            'sec_submissions_accessions')
    clean=sorted(set(forms))
    issuer_forms=sorted(set(clean)&FORMS)
    issuer_accessions=sorted({accessions[i] for i,form in enumerate(forms) if form in FORMS})
    return dict(cik=cik,issuer_forms=issuer_forms,has_fundamental_issuer_role=bool(issuer_forms),
        issuer_accessions=issuer_accessions,recent_forms=clean)


def wb_rows(raw, indicator, start, through, retrieved):
    payload = json.loads(raw)
    require(isinstance(payload,list) and len(payload)==2,'worldbank_schema')
    meta, data = payload
    require(meta.get('pages')==1 and int(meta.get('total',-1))==len(data),'worldbank_pagination')
    rows, seen = [], set()
    for r in data:
        require(r['indicator']['id']==indicator and r['countryiso3code'] in COUNTRIES,'worldbank_identity')
        year = int(r['date'])
        require(int(start[:4])<=year<=int(through[:4]),'worldbank_period')
        key=(r['countryiso3code'],year)
        require(key not in seen,'worldbank_duplicate'); seen.add(key)
        value = r['value']
        require(value is None or (type(value) in (int,float) and math.isfinite(value)),'worldbank_value')
        rows.append(dict(country=key[0],series=indicator,observation_date=f'{year}-01-01',
            value=value,available_at=retrieved,evidence='current_only',published_at=None))
    require(rows,'worldbank_empty')
    return sorted(rows,key=lambda r:(r['country'],r['observation_date']))


def wb_coverage(rows,start,through):
    expected_years=range(int(start[:4]),int(through[:4])+1)
    returned={(r['country'],int(r['observation_date'][:4])):r['value'] for r in rows}
    missing=[dict(country=country,year=year) for country in COUNTRIES for year in expected_years
             if returned.get((country,year)) is None]
    omitted=[dict(country=country,year=year) for country in COUNTRIES for year in expected_years
             if (country,year) not in returned]
    countries={}
    for country in COUNTRIES:
        valid=[r['observation_date'] for r in rows if r['country']==country and r['value'] is not None]
        countries[country]=dict(nonmissing=len(valid),earliest=min(valid,default=None),latest=max(valid,default=None),
            missing_years=[r['year'] for r in missing if r['country']==country])
    return dict(missing_values=len(missing),missing_country_years=missing,
        omitted_country_years=omitted,expected_country_years=len(COUNTRIES)*len(expected_years),
        country_coverage=countries)


def safe_error(exc):
    if isinstance(exc,HTTPError): return 'HTTP_'+str(exc.code)
    if isinstance(exc,TimeoutError): return 'TRANSPORT_TIMEOUT'
    if isinstance(exc,(URLError,OSError)): return 'TRANSPORT_ERROR'
    text = str(exc)
    if is_safe_transport_failure(text): return text
    return text if re.fullmatch(r'[A-Za-z0-9_]{1,90}',text) else 'SOURCE_OR_CONTRACT_ERROR'


def fetch_fred_retry(series,start,through,mode):
    for attempt in range(3):
        try: return fetch_fred(series,start,through,mode)
        except HTTPError as exc:
            if exc.code not in (429,500,502,503,504) or attempt==2:
                raise ValueError(safe_error(exc)) from None
        except (URLError,TimeoutError,OSError) as exc:
            if attempt==2: raise ValueError(safe_error(exc)) from None
        time.sleep(2**attempt)


def retain_price_prefix(old_rows,new_rows,retrieved,window_start=None):
    """Keep observations that age out of a provider window, never interior holes."""
    first=window_start or min(r['observation_date'] for r in new_rows)
    prefix=[]
    for row in old_rows:
        if row['observation_date']<first:
            row=dict(row)
            row.setdefault('source_retrieved_at',retrieved)
            prefix.append(row)
    return sorted(prefix+new_rows,key=lambda r:r['observation_date']),len(prefix)


class Lake:
    """Catalog chain and small immutable pack objects, independent of paper state."""
    def __init__(self, transport, workspace):
        self.transport=transport
        self.workspace=Path(workspace)
        self.workspace.mkdir(parents=True,exist_ok=True)
        self.pending={}
        self._pack_cache=(None,None)
        self.pack_batch_observations=[]
        self.parent,self.catalog=self.restore_catalog()
        self.before=copy.deepcopy(self.catalog)

    def read_hash(self, folder, sha):
        require(re.fullmatch(r'[a-f0-9]{64}',sha),'hash_identity')
        with _history_phase('REMOTE_HASH_READ') as phase_counts:
            raw=self.transport.read(f'{PREFIX}/{folder}/{sha}')
            require(digest(raw)==sha,'remote_hash')
            phase_counts['application_bytes']=len(raw)
        return raw

    def restore_catalog(self):
        with _history_phase('COMMIT_INVENTORY') as phase_counts:
            names=self.transport.names(f'{PREFIX}/commits')
            phase_counts['commits']=len(names)
        require(len(names)==len(set(names)) and len(names)<=20000,'commit_inventory')
        entries={n:json.loads(self.read_hash('commits',n)) for n in names}
        parent=None; generation=0; last=None
        pack_dependencies={}
        while entries:
            following=[(s,v) for s,v in entries.items() if v.get('parent')==parent]
            require(len(following)==1,'catalog_fork_or_broken_chain')
            parent,last=following[0]
            generation+=1
            require(last.get('generation')==generation and last.get('schema')=='long-history-commit-v1','commit_schema')
            catalog=json.loads(self.read_hash('catalogs',last['catalog']))
            require(catalog.get('schema')==SCHEMA and catalog.get('generation')==generation,'catalog_schema')
            require(catalog.get('eligible_for_selector') is False,'research_only')
            for dataset in catalog['datasets'].values():
                for obj in dataset.get('objects',[]):
                    require(obj in catalog['locations'],'catalog_dependency')
            # Retained locations are reusable data, including superseded versions.
            # A valid latest catalog must not hide broken historical dependencies.
            for obj,pack_id in catalog['locations'].items():
                require(isinstance(obj,str) and re.fullmatch(r'[a-f0-9]{64}',obj),'hash_identity')
                require(isinstance(pack_id,str) and re.fullmatch(r'[a-f0-9]{64}',pack_id),'hash_identity')
                pack_dependencies.setdefault(pack_id,set()).add(obj)
            del entries[parent]
        if last is None:
            return None,dict(schema=SCHEMA,generation=0,datasets={},locations={},eligible_for_selector=False)
        self.verify_pack_dependencies(pack_dependencies)
        return parent,catalog

    def verify_pack_dependencies(self,dependencies):
        """Verify each remote pack once per restore, never substituting local cache.

        Source 304 responses and macro-only consumers do not prove financial
        recovery. Recheck remote bytes at publication boundaries as well, since
        a pack can disappear after this Lake was constructed.
        """
        def verify(raw, objects):
            require(len(raw)<20*1024*1024,'pack_size')
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                names=archive.namelist()
                require(len(names)==len(set(names)),'pack_inventory')
                require(objects.issubset(set(names)),'pack_dependency')
                for obj in sorted(objects):
                    info=archive.getinfo(obj)
                    require(0<info.file_size<=MAX_OBJECT,'pack_member_size')
                    require(digest(archive.read(info))==obj,'pack_object_hash')
        with _history_phase('PACK_DEPENDENCIES', packs=len(dependencies), objects=sum(map(len, dependencies.values()))):
            batch=getattr(self.transport,'read_pack_batch',None)
            if not callable(batch) or not dependencies:
                for pack_id,objects in sorted(dependencies.items()):
                    verify(self.read_hash('packs',pack_id),objects)
                return
            inventory=self.transport.names(f'{PREFIX}/packs')
            require(isinstance(inventory,list) and len(inventory)==len(set(inventory))
                    and len(inventory)<=20000,'pack_batch_inventory')
            require(set(dependencies).issubset(set(inventory)),'checkpoint_object_size')
            names=sorted(dependencies)
            for offset in range(0,len(names),PACK_BATCH_FILES):
                group=names[offset:offset+PACK_BATCH_FILES]
                observation={}
                self.pack_batch_observations.append(observation)
                with _history_phase('PACK_BATCH_READ',packs=len(group),
                                    reserved_bytes=PACK_BATCH_BYTES) as counts:
                    try:
                        with batch(group,observation) as stage:
                            for pack_id in group:
                                with _history_phase('REMOTE_HASH_READ') as read_counts:
                                    raw=checked_bytes(stage/pack_id)
                                    require(digest(raw)==pack_id,'remote_hash')
                                    read_counts['application_bytes']=len(raw)
                                verify(raw,dependencies[pack_id])
                    finally:
                        counts['staged_bytes']=observation.get('staged_bytes',0)
                        counts['subprocess_attempts']=observation.get('subprocess_attempts',0)

    def object(self, raw):
        require(0<len(raw)<=MAX_OBJECT,'object_size')
        sha=digest(raw)
        if sha not in self.catalog['locations']:
            path=self.workspace/'objects'/sha
            exclusive(path,raw)
            self.pending[sha]=path
        return sha

    def dataset(self,key,pages,rows,metadata):
        raw_hashes=[self.object(packed(p)) for p in pages]
        normalized=self.object(packed(b''.join(encoded(r) for r in rows)))
        old=self.catalog['datasets'].get(key,{})
        self.catalog['datasets'][key]=dict(metadata,status='COLLECTED',objects=raw_hashes+[normalized],
            raw_objects=raw_hashes,normalized=normalized,encoding='gzip_jsonl',
            changed=old.get('objects')!=raw_hashes+[normalized],checked_at=utc_now())

    def blocked(self,key,exc):
        old=self.catalog['datasets'].get(key,{})
        self.catalog['datasets'][key]=dict(old,status='STALE_RETAINED' if old.get('objects') else 'BLOCKED',
            last_failure=safe_error(exc),checked_at=utc_now())

    def coverage_gap(self,key,pages,metadata):
        """Archive official identity bytes without inventing financial observations."""
        require(isinstance(pages,list) and bool(pages),'coverage_gap_pages')
        raw_hashes=[self.object(packed(page)) for page in pages]
        old=self.catalog['datasets'].get(key,{})
        self.catalog['datasets'][key]=dict(metadata,status='COVERAGE_GAP',
            objects=raw_hashes,raw_objects=raw_hashes,normalized=None,
            changed=old.get('objects')!=raw_hashes,checked_at=utc_now())

    def get_bytes(self,sha):
        if sha in self.pending:
            raw=self.pending[sha].read_bytes()
        else:
            pack_id=self.catalog['locations'][sha]
            if self._pack_cache[0]!=pack_id:
                cache=self.workspace/'pack-cache'/pack_id
                if not cache.exists():
                    exclusive(cache,self.read_hash('packs',pack_id))
                self._pack_cache=(pack_id,checked_bytes(cache,pack_id))
            pack=self._pack_cache[1]
            with zipfile.ZipFile(io.BytesIO(pack)) as z:
                info=z.getinfo(sha)
                require(info.file_size<=MAX_OBJECT,'pack_member_size')
                raw=z.read(info)
            require(digest(raw)==sha,'object_hash')
        return raw

    def get_records(self,key):
        entry=self.catalog['datasets'][key]
        require(entry['status'] in ('COLLECTED','UNCHANGED') and isinstance(entry.get('normalized'),str),
                'stale_dataset')
        return self._verified_normalized_records(entry)

    def _verified_normalized_records(self,entry):
        """Internal lineage recovery; caller must never treat stale bytes as admitted input."""
        require(isinstance(entry.get('normalized'),str),'normalized_missing')
        raw=self.get_bytes(entry['normalized'])
        return [json.loads(line) for line in unpacked(raw).splitlines()]

    def verified_execution(self, *, allow_missing=False):
        """Bind shared consumption to this restored commit's completed receipt.

        Writers still restore storage-only commits so an interrupted cycle can
        recover. Shared readers must explicitly require execution evidence.
        """
        require(self.parent is not None,'execution_without_commit')
        commit=json.loads(self.read_hash('commits',self.parent))
        names=self.transport.names(f'{PREFIX}/executions')
        require(len(names)==len(set(names)) and len(names)<=20000,'execution_inventory')
        matches=[]
        for sha in names:
            receipt=json.loads(self.read_hash('executions',sha))
            if receipt.get('commit_sha256')!=self.parent:
                continue
            require(receipt.get('catalog_sha256')==commit['catalog'],'execution_catalog_mismatch')
            matches.append((sha,receipt))
        if not matches and allow_missing:
            return None
        require(len(matches)==1,'execution_receipt_missing_or_ambiguous')
        sha,receipt=matches[0]
        require(receipt.get('schema')=='long-history-execution-v1' and
                receipt.get('run_id')==commit['run_id'] and
                receipt.get('eligible_for_selector') is False,'execution_schema')
        require(type(receipt.get('study_recomputed_from_drive')) is bool and
                type(receipt.get('consumer_rows')) is int and receipt['consumer_rows']>=0,
                'execution_consumer_evidence')
        reports=receipt.get('reports')
        require(isinstance(reports,dict) and 'quality.json' in reports,'execution_reports')
        verified={name:self.read_hash('reports',report_sha) for name,report_sha in reports.items()}
        quality=json.loads(verified['quality.json'])
        require(quality.get('schema')=='long-history-quality-v1' and
                quality.get('eligible_for_selector') is False and
                quality.get('status') in {'PARTIAL','PARTIAL_COVERAGE','COLLECTED_NOT_PIT_CERTIFIED'} and
                quality['status']==receipt.get('quality_status'),'execution_quality_mismatch')
        if ('cycle_scope' in receipt or 'cycle_scope' in quality
                or self.catalog.get('config',{}).get('hybrid_refresh') is not None):
            require(receipt.get('cycle_scope')==quality.get('cycle_scope')
                    and type(receipt.get('cycle_scope')) is dict
                    and digest(encoded(receipt['cycle_scope']))==self.catalog.get('config',{}).get(
                        'hybrid_refresh',{}).get('summary_sha256'),'hybrid_execution_scope_mismatch')
        if 'source_cycle_readback' in receipt:
            require(receipt['source_cycle_readback']==hybrid_source_scope_readback(self,receipt['cycle_scope'])
                    and receipt['study_recomputed_from_drive'] is False,'hybrid_source_scope_readback_mismatch')
        return dict(receipt,execution_receipt_sha256=sha)

    def publish(self,run_id,config):
        require(re.fullmatch('[A-Za-z0-9_-]{1,100}',run_id),'run_id')
        with _history_phase('PUBLICATION_PRECHECK'):
            require(self.restore_catalog()[0]==self.parent,'stale_writer')
        groups=[]; current=[]; size=0
        for sha,path in sorted(self.pending.items()):
            n=path.stat().st_size
            if current and size+n>PACK_BYTES:
                groups.append(current); current=[]; size=0
            current.append((sha,path)); size+=n
        if current: groups.append(current)
        verified_bytes=0
        for i,group in enumerate(groups):
            output=io.BytesIO()
            with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_STORED) as z:
                for sha,path in group:
                    info=zipfile.ZipInfo(sha,date_time=(1980,1,1,0,0,0))
                    z.writestr(info,path.read_bytes())
            raw=output.getvalue()
            require(len(raw)<20*1024*1024,'pack_size')
            pack_sha=digest(raw)
            with _history_phase('NEW_PACK_WRITE_READBACK', index=i+1, total=len(groups)):
                self.transport.write(f'{PREFIX}/packs/{pack_sha}',raw)
                restored=self.read_hash('packs',pack_sha)
                with zipfile.ZipFile(io.BytesIO(restored)) as z:
                    require(set(z.namelist())=={sha for sha,_ in group},'pack_inventory')
                    for sha,_ in group:
                        require(digest(z.read(sha))==sha,'pack_object_hash')
                        self.catalog['locations'][sha]=pack_sha
            verified_bytes+=len(raw)
            print(json.dumps(dict(phase='PACK_VERIFIED',pack=i+1,total=len(groups))),flush=True)
        self.catalog.update(generation=self.catalog['generation']+1,run_id=run_id,created_at=utc_now(),
            config=config,config_sha256=digest(encoded(config)),code_sha=os.environ.get('GITHUB_SHA'),
            eligible_for_selector=False,fullrun_executed=False)
        raw=encoded(self.catalog); catalog_sha=digest(raw)
        require(len(raw)<=MAX_OBJECT,'catalog_size')
        with _history_phase('CATALOG_WRITE_READBACK', catalog_sha256=catalog_sha, application_bytes=len(raw)):
            self.transport.write(f'{PREFIX}/catalogs/{catalog_sha}',raw)
            require(self.read_hash('catalogs',catalog_sha)==raw,'catalog_roundtrip')
        with _history_phase('PUBLICATION_RECHECK', catalog_sha256=catalog_sha):
            require(self.restore_catalog()[0]==self.parent,'stale_writer')
        commit=dict(schema='long-history-commit-v1',parent=self.parent,catalog=catalog_sha,
            generation=self.catalog['generation'],run_id=run_id,created_at=utc_now())
        commit_raw=encoded(commit); commit_sha=digest(commit_raw)
        with _history_phase('COMMIT_WRITE', commit_sha256=commit_sha, catalog_sha256=catalog_sha, application_bytes=len(commit_raw)):
            self.transport.write(f'{PREFIX}/commits/{commit_sha}',commit_raw)
        with _history_phase('POST_COMMIT_RESTORE', commit_sha256=commit_sha, catalog_sha256=catalog_sha):
            require(self.restore_catalog()[0]==commit_sha,'publication_conflict')
        return dict(commit_sha256=commit_sha,catalog_sha256=catalog_sha,
            new_packs=len(groups),verified_new_bytes=verified_bytes,
            remote_verified=self.transport.remote_verified,eligible_for_selector=False)


def collect_financials(lake,cohort,start,through,*,_hybrid=None):
    if _hybrid is not None and not _hybrid['provider_scope']['sec']:
        return dict(status='NOT_CHECKED_THIS_CYCLE',reason='RIGHTS_BLOCKED_OR_DISABLED_BY_OWNER_PROFILE')
    raw=_hybrid['cohort'] if _hybrid is not None else Path(cohort).read_bytes()
    require(digest(raw)==COHORT_SHA,'cohort_hash')
    payload=json.loads(raw)
    members=payload['rows']
    require(payload['candidate_count']==len(members) and payload['as_of']<=through,'cohort_identity')
    if _hybrid is None:
        mapping_raw,_=get_public('https://www.sec.gov/files/company_tickers.json')
        prior_mapping,prior_sources=prior_sec_mapping(lake,with_sources=True)
        mapping=json.loads(mapping_raw)
    else:
        mapping=_hybrid['mapping']; prior_mapping=_hybrid['prior_mapping']
    groups,missing,resolution=issuer_queue(members,mapping,prior_mapping)
    full_issuer_count=len(groups)
    current_ciks={row['cik'] for row in resolution if row['identity_status'] in
        ('CURRENT_SEC_MAPPING','CURRENT_SEC_MAPPING_WITH_HISTORY_CONFLICT')}
    history_ciks={cik for row in resolution for cik in row.get('history_retained_ciks',
        [row['cik']] if row['identity_status']=='PRIOR_SEC_MAPPING_RETAINED_LIFECYCLE_REVIEW' else [])}
    retrieved=utc_now()
    if _hybrid is None:
        lake.dataset('universe/cohort',[raw,mapping_raw],members,dict(evidence='CURRENT_COHORT_NOT_HISTORICAL_MEMBERSHIP',
            rows=len(members),requested_securities=len(members),mapped_issuers=len(current_ciks),
            current_mapped_issuer_count=len(current_ciks),history_retained_issuer_count=len(history_ciks),
            collection_issuer_count=len(groups),
            current_mapping_issuer_keys=sorted('sec/'+cik for cik in current_ciks),
            history_retained_issuer_keys=sorted('sec/'+cik for cik in history_ciks),
            collection_issuer_keys=sorted('sec/'+cik for cik in groups),
            active_issuer_keys=sorted('sec/'+cik for cik in groups),missing=missing,
            lifecycle_review_count=sum(row['lifecycle_review_required'] for row in resolution),
            sec_identity_resolution=resolution,
            cohort_source_object_sha256=digest(packed(raw)),
            sec_ticker_mapping_object_sha256=digest(packed(mapping_raw)),
            sec_ticker_mapping_source_sha256=digest(mapping_raw),
            sec_ticker_mapping_retrieved_at=retrieved,
            historical_sec_mapping_object_sha256s=list(dict.fromkeys(
                [digest(packed(mapping_raw))]+prior_sources)),
            source_role_contract_version='cohort-sec-mapping-v1'))
    else:
        require(groups==_hybrid['groups'],'hybrid_issuer_scope_changed')
        groups={c:groups[c] for c in sorted(_hybrid['selected'])}
    def one(item):
        cik,symbols=item; key='sec/'+cik
        old=lake.catalog['datasets'].get(key,{})
        if _hybrid is not None:
            # Covers both the existing three-attempt companyfacts call and its
            # possible three-attempt404 submissions fallback, without refunds.
            _hybrid['budget'].provider(6,6*(32*1024*1024+1))
            _hybrid['attempted_keys'].add(key)
        try:
            # An older restored object can only be reused for the same extraction
            # floor/schema. A changed window forces a full response.
            conditional=sec_conditional(old,start,through)
            data,http=get_public(f'https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json',conditional)
            if data is None:
                require(old.get('objects') and old.get('normalized'),'304_without_prior')
                return key,None,None,dict(old,tickers=symbols,through=through,
                    missing_years=[y for y in range(int(start[:4]),int(through[:4])) if y not in old['years_with_any_facts']],
                    status='UNCHANGED',changed=False,checked_at=utc_now())
            rows,rejected=sec_rows(data,cik,start,through)
            require(rows,'NO_FACTS_IN_WINDOW')
            metadata=dict(cik=cik,tickers=symbols,start=start,through=through,http=http,
                extraction_sha256=extraction_identity(),
                deferred_until=sec_future_boundary(data,through),
                retrieved_at=utc_now(),evidence='SEC_FILED_DATE_CURRENT_ARCHIVE_NOT_CERTIFIED_PIT',
                rejected_rows=rejected,**fact_coverage(rows,start,through))
            return key,[data],rows,metadata
        except (ValueError,KeyError,TypeError,OSError) as exc:
            if _hybrid is not None and isinstance(exc,(Refused,TimeoutError,InterruptedError)):
                raise
            if isinstance(exc,SourceHTTPError) and exc.code==404:
                try:
                    submissions,_=get_public(f'https://data.sec.gov/submissions/CIK{cik}.json')
                    profile=sec_submissions_profile(submissions,cik)
                    reason=('SEC_COMPANYFACTS_UNAVAILABLE_ISSUER_FILINGS_PRESENT'
                        if profile['has_fundamental_issuer_role']
                        else 'SEC_FUNDAMENTAL_ENTITY_ROLE_UNRESOLVED')
                    now=utc_now()
                    return key,[submissions],None,dict(coverage_gap=True,coverage_gap_reason=reason,
                        tickers=symbols,start=start,through=through,
                        evidence='SEC_SUBMISSIONS_ROLE_EVIDENCE_NO_COMPANYFACTS',
                        retrieved_at=now,available_at=now,submissions_source_sha256=digest(submissions),
                        **profile)
                except (ValueError,KeyError,TypeError,OSError) as sub_exc:
                    return key,None,None,ValueError('SEC_SUBMISSIONS_'+safe_error(sub_exc))
            return key,None,None,exc
    work=(map(one,sorted(groups.items())) if _hybrid is not None else
          ThreadPoolExecutor(max_workers=6).map(one,sorted(groups.items())))
    for count,(key,pages,rows,result) in enumerate(work,1):
        if _hybrid is not None: _hybrid['budget'].check()
        if isinstance(result,Exception): lake.blocked(key,result)
        elif result.get('coverage_gap') is True: lake.coverage_gap(key,pages,result)
        elif pages is None: lake.catalog['datasets'][key]=result
        else: lake.dataset(key,pages,rows,result)
        if _hybrid is not None and not isinstance(result,Exception):
            _hybrid['completed_keys'].add(key)
        if count%100==0: print(json.dumps(dict(phase='SEC_COLLECTED',issuers=count,total=len(groups))),flush=True)
    return dict(requested_securities=len(members),mapped_issuers=len(current_ciks),
        history_retained_issuer_count=len(history_ciks),collection_issuer_count=full_issuer_count,
        lifecycle_review_count=sum(row['lifecycle_review_required'] for row in resolution),missing=missing)


def scoped_alfred_request(raw, expected_sha256):
    """Validate the entire explicit request before transport/credential access."""
    require(type(raw) is bytes and 0 < len(raw) <= 16384, 'scoped_request_size')
    require(isinstance(expected_sha256,str) and re.fullmatch('[a-f0-9]{64}',expected_sha256)
            and digest(raw)==expected_sha256, 'scoped_request_hash')
    def unique(pairs):
        result={}
        for key,value in pairs:
            require(key not in result,'scoped_request_duplicate_key')
            result[key]=value
        return result
    try:
        request=json.loads(raw,object_pairs_hook=unique)
    except (UnicodeError,json.JSONDecodeError):
        raise ValueError('scoped_request_json') from None
    fields={'schema','request_id','mode','series','observation_start','through',
            'expected_parent','expected_catalog','registry_sha256','budget'}
    require(type(request) is dict and set(request)==fields,'scoped_request_fields')
    require(request['schema']=='long-history-scoped-alfred-v1'
            and request['mode']=='alfred_missing_only','scoped_request_mode')
    require(isinstance(request['request_id'],str)
            and re.fullmatch('[A-Za-z0-9_-]{1,100}',request['request_id']),'scoped_request_id')
    for key in ('expected_parent','expected_catalog','registry_sha256'):
        require(isinstance(request[key],str) and re.fullmatch('[a-f0-9]{64}',request[key]),
                'scoped_request_pin')
    ids=request['series']
    require(type(ids) is list and 0<len(ids)<=len(SCOPED_ALFRED_IDS)
            and all(type(s) is str and s in SCOPED_ALFRED_IDS for s in ids)
            and len(ids)==len(set(ids)),'scoped_request_series')
    require(request['registry_sha256']==digest((ROOT/'docs/macro_indicator_registry.json').read_bytes()),
            'scoped_registry_changed')
    require(set(ids)<={s['id'] for s in registry()['series']},'scoped_unknown_series')
    try:
        first=date.fromisoformat(request['observation_start'])
        last=date.fromisoformat(request['through'])
        require(first.isoformat()==request['observation_start'] and last.isoformat()==request['through']
                and first<=last<=date.today(),'scoped_request_window')
    except (TypeError,ValueError):
        raise ValueError('scoped_request_window') from None
    budget=request['budget']
    require(type(budget) is dict and set(budget)=={'provider_gets','provider_bytes','pages_per_series'}
            and all(type(v) is int and v>0 for v in budget.values()),'scoped_request_budget')
    # The unchanged fetch primitive has no per-page injection hook. Reserve its
    # full known ceiling before each call, with no retry and no refund. Smaller
    # grants must fail before I/O rather than pretend to meter hidden requests.
    require(FRED_MAX_PAGES==20 and FRED_MAX_BYTES==16*1024*1024
            and budget['pages_per_series']==FRED_MAX_PAGES
            and len(ids)*FRED_MAX_PAGES<=budget['provider_gets']<=180
            and len(ids)*FRED_MAX_PAGES*SCOPED_PAGE_RESERVATION_BYTES<=budget['provider_bytes']
            <=180*SCOPED_PAGE_RESERVATION_BYTES,
            'scoped_fetch_reservation_budget')
    return request


def collect_scoped_alfred(lake, request):
    """Only missing exact ALFRED keys; publication remains the caller's boundary."""
    request=scoped_alfred_request(encoded(request),digest(encoded(request)))
    require(not lake.pending and lake.catalog==lake.before,'scoped_unclean_lake')
    require(lake.parent==request['expected_parent']
            and digest(encoded(lake.before))==request['expected_catalog'],'scoped_parent_mismatch')
    current_parent,current_catalog=lake.restore_catalog()
    require(current_parent==lake.parent and digest(encoded(current_catalog))==request['expected_catalog'],
            'scoped_parent_mismatch')
    require(all('alfred/'+s not in lake.before['datasets'] for s in request['series']),
            'scoped_dataset_already_present')
    specs={s['id']:s for s in registry()['series']}
    meter=dict(reserved_provider_gets=0,reserved_provider_bytes=0,
               returned_pages=0,returned_body_bytes=0,actual_failed_request_count=None,
               reservation_policy='FULL_FETCH_CEILING_NO_RETRY_NO_REFUND')
    for sid in request['series']:
        require(meter['reserved_provider_gets']+FRED_MAX_PAGES<=request['budget']['provider_gets']
                and meter['reserved_provider_bytes']+FRED_MAX_PAGES*SCOPED_PAGE_RESERVATION_BYTES
                <=request['budget']['provider_bytes'],'scoped_budget_exhausted')
        meter['reserved_provider_gets']+=FRED_MAX_PAGES
        meter['reserved_provider_bytes']+=FRED_MAX_PAGES*SCOPED_PAGE_RESERVATION_BYTES
        try:
            # One existing bounded fetch, never the retry wrapper or current fallback.
            pages,retrieved=fetch_fred(sid,request['observation_start'],request['through'],'alfred')
            require(0<len(pages)<=FRED_MAX_PAGES
                    and all(type(p) is bytes and 0<len(p)<=FRED_MAX_BYTES for p in pages),
                    'scoped_response_bounds')
            meter['returned_pages']+=len(pages)
            meter['returned_body_bytes']+=sum(map(len,pages))
            rows=parse_alfred(pages,sid,request['observation_start'],request['through'],retrieved)
            spec=specs[sid]
            clean=[{k:v for k,v in r.items() if k!='retrieved_at'} for r in rows]
            lake.dataset('alfred/'+sid,pages,clean,dict(series=sid,frequency=spec['frequency'],
                group=spec['group'],unit=spec['unit'],rows=len(clean),
                earliest=min(r['observation_date'] for r in rows),
                latest=max((r['observation_date'] for r in rows if r['value'] is not None),default=None),
                retrieved_at=retrieved,evidence='alfred_date_archive',
                first_vintage_date=min(r['vintage_date'] for r in rows),
                first_available_at=min(r['available_at'] for r in rows),
                requested_start=request['observation_start'],requested_through=request['through'],
                raw_redistribution=spec['raw_redistribution'],**fred_missing(rows,[])))
        except (Refused,TimeoutError,InterruptedError):
            print('SCOPED_ALFRED_STOP '+json.dumps(meter,sort_keys=True),flush=True)
            raise
        except (HTTPError,URLError,OSError,ValueError,TypeError,KeyError) as exc:
            # No raw exception/credential URL and no partial publication. Full
            # failed-call reservations remain visible; returned bytes are not wire.
            if isinstance(exc,HTTPError):
                exc.close()
            print('SCOPED_ALFRED_STOP '+json.dumps(meter,sort_keys=True),flush=True)
            raise ValueError('scoped_alfred_collection_blocked') from None
    return meter


def project_alfred_versions(rows, decision_at, archive_through):
    """Conservative date-archive projection, not original intraday/PIT admission.

    A future revision can shorten raw realtime_end retroactively. Its end is
    retained as source evidence, never used to erase an earlier eligible value
    before the successor's conservative availability boundary.
    """
    try:
        cutoff=datetime.fromisoformat(decision_at.replace('Z','+00:00'))
        require(cutoff.tzinfo is not None and cutoff.utcoffset() is not None,'alfred_decision_clock')
        through=date.fromisoformat(archive_through)
    except (AttributeError,TypeError,ValueError):
        raise ValueError('alfred_decision_clock') from None
    cutoff=cutoff.astimezone(timezone.utc)
    local_day=cutoff.astimezone(ZoneInfo('America/New_York')).date()
    require(through>=local_day-timedelta(days=1),'alfred_incomplete_asof_archive')
    require(through.isoformat()==archive_through,'alfred_archive_clock')
    require(type(rows) is list and bool(rows),'alfred_empty_archive')
    selected={}; seen=set(); series=None
    for row in rows:
        try:
            observed=date.fromisoformat(row['observation_date'])
            vintage=date.fromisoformat(row['vintage_date'])
            end=date.fromisoformat(row['realtime_end'])
            boundary=datetime.combine(vintage+timedelta(days=1),datetime.min.time(),
                                      ZoneInfo('America/New_York')).astimezone(timezone.utc)
            available=datetime.fromisoformat(row['available_at'].replace('Z','+00:00'))
        except (AttributeError,TypeError,KeyError,ValueError):
            raise ValueError('alfred_archive_clock') from None
        require(row.get('evidence')=='alfred_date_archive' and row.get('published_at') is None
                and available.tzinfo is not None and available==boundary
                and row['observation_date']==observed.isoformat()
                and row['vintage_date']==vintage.isoformat() and row['realtime_end']==end.isoformat()
                and observed<=vintage<=through and end>=vintage,'alfred_archive_clock')
        value=row.get('value')
        require('value' in row and (value is None or type(value) in (int,float) and math.isfinite(value)),
                'alfred_archive_value')
        require(type(row.get('series')) is str and row['series'],'alfred_archive_series')
        series=series or row['series']
        require(row['series']==series,'alfred_mixed_series')
        identity=(observed,vintage)
        require(identity not in seen,'alfred_duplicate_vintage')
        seen.add(identity)
        if observed>local_day or vintage>=local_day or available>cutoff:
            continue
        if observed not in selected or vintage>selected[observed][0]:
            selected[observed]=(vintage,dict(series=series,observation_date=observed.isoformat(),
                vintage_date=vintage.isoformat(),available_at=boundary.isoformat(),value=value))
    return dict(status='DATE_ARCHIVE_RESEARCH_ONLY' if selected else 'NO_ELIGIBLE_VINTAGE',decision_at=cutoff.isoformat(),
        archive_through=through.isoformat(),published_at_precision='DATE_ONLY',
        completeness='CALLER_MUST_BIND_COMPLETE_ARCHIVE_RECEIPT',historical_pit_certified=False,
        records=[selected[day][1] for day in sorted(selected)])


def project_alfred_asof(lake, series, decision_at):
    """Bind a conservative projection to the existing verified Lake receipt."""
    require(type(series) is str and series,'alfred_archive_series')
    require(not lake.pending and lake.catalog==lake.before,'scoped_unclean_lake')
    entry=lake.catalog['datasets'].get('alfred/'+series,{})
    require(entry.get('status') in ('COLLECTED','UNCHANGED')
            and entry.get('evidence')=='alfred_date_archive','alfred_dataset_unavailable')
    receipt=lake.verified_execution()
    require(receipt.get('study_recomputed_from_drive') is True,'alfred_execution_incomplete')
    rows=lake.get_records('alfred/'+series)
    require(all(row.get('series')==series for row in rows),'alfred_archive_series')
    result=project_alfred_versions(rows,decision_at,entry.get('requested_through'))
    result.update(source_commit=lake.parent,execution_receipt_sha256=receipt['execution_receipt_sha256'])
    return result


def collect_macros(lake,start,through,*,_hybrid=None):
    specs=[] if _hybrid is not None and not _hybrid['provider_scope']['fred'] else registry()['series']
    for spec in specs:
        if spec.get('collection_scope')=='scoped_alfred_only':
            continue
        sid=spec['id']
        modes=(['current'] if _hybrid is not None and _hybrid['request']['mode']=='HYBRID_DAILY'
               else ['current','alfred'] if sid in ARCHIVES else ['current'])
        for mode in modes:
            key=f'{mode}/{sid}'
            if _hybrid is not None:
                pages=1 if mode=='current' else FRED_MAX_PAGES
                _hybrid['budget'].provider(3*pages,3*pages*SCOPED_PAGE_RESERVATION_BYTES)
                _hybrid['attempted_keys'].add(key)
            try:
                pages,retrieved=fetch_fred_retry(sid,start,through,mode)
                if mode=='current': rows,missing=parse_current(pages,sid,start,through,retrieved)
                else: rows=parse_alfred(pages,sid,start,through,retrieved); missing=[]
                # Retrieval belongs to the version receipt, not every unchanged row.
                clean=[{k:v for k,v in r.items() if k!='retrieved_at'} for r in rows]
                if mode=='current':
                    for r in clean: r.pop('available_at',None)
                old=lake.catalog['datasets'].get(key,{})
                retained=0
                retained_missing=[]
                if mode=='current' and spec['group']=='price' and old.get('normalized'):
                    # The provider window includes explicit missing rows, even
                    # though the current parser omits them from normalized records.
                    window_start=min([r['observation_date'] for r in rows]+missing)
                    clean,retained=retain_price_prefix(lake._verified_normalized_records(old),clean,
                        old['retrieved_at'],window_start)
                    retained_missing=[d for d in old.get('missing_observation_dates',[])
                                      if start<=d<window_start]
                coverage=fred_missing(rows,missing)
                if retained_missing:
                    coverage['missing_observation_dates']=sorted(set(coverage['missing_observation_dates'])|set(retained_missing))
                    coverage['missing_values']+=len(set(retained_missing))
                lake.dataset(key,pages,clean,dict(series=sid,frequency=spec['frequency'],group=spec['group'],unit=spec['unit'],
                    rows=len(clean),earliest=min(r['observation_date'] for r in clean),
                    latest=max(r['observation_date'] for r in rows if r['value'] is not None),retrieved_at=retrieved,
                    evidence='alfred_date_archive' if mode=='alfred' else 'current_only',
                    first_vintage_date=min((r['vintage_date'] for r in rows),default=None) if mode=='alfred' else None,
                    first_available_at=min((r['available_at'] for r in rows),default=None) if mode=='alfred' else retrieved,
                    **coverage,
                    requested_start=start,requested_through=through,raw_redistribution=spec['raw_redistribution'],
                    retained_expired_provider_rows=retained))
                if retained or retained_missing:
                    entry=lake.catalog['datasets'][key]
                    dependencies=old.get('retained_source_objects',[])+old['raw_objects']+[old['normalized']]
                    entry['retained_source_objects']=sorted(set(dependencies))
                    entry['objects']=sorted(set(entry['objects']+dependencies))
                    entry['retained_from_commit']=lake.parent
                if _hybrid is not None: _hybrid['completed_keys'].add(key)
            except Exception as exc:
                if _hybrid is not None:
                    if isinstance(exc,(Refused,TimeoutError,InterruptedError)): raise
                    _hybrid['budget'].check()
                lake.blocked(key,exc)
    if _hybrid is not None and (_hybrid['request']['mode']=='HYBRID_DAILY'
                               or not _hybrid['provider_scope']['worldbank']):
        return
    for indicator in WB_INDICATORS:
        key='worldbank/'+indicator
        if _hybrid is not None:
            _hybrid['budget'].provider(3,3*(32*1024*1024+1))
            _hybrid['attempted_keys'].add(key)
        try:
            url='https://api.worldbank.org/v2/country/'+';'.join(COUNTRIES)+'/indicator/'+indicator+'?'+urlencode(
                dict(format='json',date=start[:4]+':'+through[:4],per_page=20000))
            pages,_=get_public(url); retrieved=utc_now()
            rows=wb_rows(pages,indicator,start,through,retrieved)
            for r in rows: r.pop('available_at',None)
            lake.dataset(key,[pages],rows,dict(rows=len(rows),evidence='current_only',retrieved_at=retrieved,
                earliest=min(r['observation_date'] for r in rows if r['value'] is not None),latest=max(r['observation_date'] for r in rows if r['value'] is not None),
                countries=list(COUNTRIES),indicator=indicator,frequency='annual',
                requested_start=start,requested_through=through,**wb_coverage(rows,start,through)))
            if _hybrid is not None: _hybrid['completed_keys'].add(key)
        except Exception as exc: lake.blocked(key,exc)


def diagnostics(lake):
    all_datasets=lake.catalog['datasets']
    universe=all_datasets.get('universe/cohort',{})
    collection=set(universe.get('collection_issuer_keys',universe.get('active_issuer_keys',[])))
    current=set(universe.get('current_mapping_issuer_keys',universe.get('active_issuer_keys',[])))
    history=set(universe.get('history_retained_issuer_keys',[]))
    datasets={k:d for k,d in all_datasets.items() if not k.startswith('sec/') or k in collection}
    sec=[d for k,d in datasets.items() if k.startswith('sec/')]
    macro={k:d for k,d in datasets.items() if k.startswith(('current/','alfred/','worldbank/'))}
    counts={s:sum(d['status']==s for d in datasets.values()) for s in
        ('COLLECTED','UNCHANGED','COVERAGE_GAP','STALE_RETAINED','BLOCKED')}
    gap=bool(counts['COVERAGE_GAP'] or universe.get('missing') or universe.get('lifecycle_review_count'))
    status=('PARTIAL' if counts['BLOCKED'] or counts['STALE_RETAINED']
            else 'PARTIAL_COVERAGE' if gap else 'COLLECTED_NOT_PIT_CERTIFIED')
    return dict(schema='long-history-quality-v1',as_of=utc_now(),status=status,
        status_counts=counts,financial_issuers=len(sec),financial_fact_rows=sum(d.get('rows',0) for d in sec),
        current_mapped_issuer_count=len(current),history_retained_issuer_count=len(history),
        collection_issuer_count=len(collection),
        current_financial_issuers_collected=sum(all_datasets[k]['status'] in ('COLLECTED','UNCHANGED')
            for k in current if k in all_datasets),
        archived_inactive_issuers=sum(k.startswith('sec/') and k not in collection for k in all_datasets),
        financial_issuers_collected=sum(d['status'] in ('COLLECTED','UNCHANGED') for d in sec),
        issuers_with_ten_calendar_years=sum(len(d.get('years_with_any_facts',[]))>=10 for d in sec),
        three_statement_ten_year_completeness='NOT_CERTIFIED',
        macro_coverage={k:{f:d.get(f) for f in ('status','rows','earliest','latest','evidence','first_vintage_date','first_available_at','missing_values','missing_observation_dates','missing_country_years','omitted_country_years','expected_country_years','country_coverage','last_failure')} for k,d in macro.items()},
        universe=universe,eligible_for_selector=False,weights_activated=False,
        historical_membership_verified=False,historical_pit_certified=False,
        provider_failures={k:d.get('last_failure') for k,d in datasets.items() if d['status'] in ('BLOCKED','STALE_RETAINED')},
        provider_coverage_gaps={k:d.get('coverage_gap_reason') for k,d in datasets.items()
            if d['status']=='COVERAGE_GAP'})


def materialize(lake,destination,keys,cutoff):
    """Rebuildable SQL cache from pinned, verified versions. No PIT relabelling."""
    require(not Path(destination).exists(),'database_already_exists')
    conn=sqlite3.connect(destination)
    try:
        conn.execute('create table records(dataset text, observation_date text, filed_date text, concept text, unit text, value real, evidence text, payload text)')
        conn.execute('create table provenance(catalog_generation integer, cutoff text, historical_pit_certified integer)')
        conn.execute('insert into provenance values(?,?,0)',(lake.catalog['generation'],cutoff))
        count=0
        with conn:
            for key in keys:
                entry=lake.catalog['datasets'][key]
                require(entry['status'] in ('COLLECTED','UNCHANGED'),'stale_dataset')
                require(entry.get('evidence')!='current_only' or cutoff>=entry['retrieved_at'][:10],
                        'current_vintage_historical_cutoff_forbidden')
                for row in lake.get_records(key):
                    observed=row.get('observation_date',row.get('end'))
                    if observed and observed>cutoff: continue
                    if row.get('filed') and row['filed']>cutoff: continue
                    if row.get('available_at') and row['available_at'][:10]>cutoff: continue
                    conn.execute('insert into records values(?,?,?,?,?,?,?,?)',(key,observed,row.get('filed'),row.get('concept',row.get('series')),row.get('unit'),row.get('value'),row.get('evidence',entry['evidence']),json.dumps(row)))
                    count+=1
            conn.execute('create index lookup on records(dataset,observation_date,filed_date)')
        return count
    finally:
        conn.close()


def analyze_restored(lake, root, start, through):
    """Run the existing fixed study on a freshly restored catalog's real bytes."""
    from tools.macro_technical_study import study
    from tools.macro_research_cycle import CURRENT, engine_context
    from tools.macro_history_sources import REGISTRY
    require(lake.catalog['config']['registry_sha256']==digest(encoded(registry())),
            'analysis_registry_version_mismatch')
    store=Path(root)/'store'
    registry_raw=REGISTRY.read_bytes()
    exclusive(store/'registries'/(digest(registry_raw)+'.json'),registry_raw)
    receipts=[]
    for mode,ids in [('current',CURRENT),('alfred',['UNRATE','PAYEMS','CPIAUCSL'])]:
        sources=[]
        for sid in ids:
            entry=lake.catalog['datasets'][mode+'/'+sid]
            require(entry['status'] in ('COLLECTED','UNCHANGED'),'study_required_source_blocked')
            raw_pages=[unpacked(lake.get_bytes(sha)) for sha in entry['raw_objects']]
            retrieved=entry['retrieved_at']
            if mode=='current':
                rows,_=parse_current(raw_pages,sid,start,through,retrieved)
                if entry.get('retained_expired_provider_rows'):
                    for sha in entry['retained_source_objects']:
                        lake.get_bytes(sha)  # Verify original lineage dependencies too.
                    rows=lake.get_records(mode+'/'+sid)
                    rows=[dict(r,retrieved_at=r.get('source_retrieved_at',retrieved),
                               available_at=r.get('source_retrieved_at',retrieved)) for r in rows]
            else: rows=parse_alfred(raw_pages,sid,start,through,retrieved)
            raw_hashes=[]
            for raw in raw_pages:
                sha=digest(raw); exclusive(store/'objects'/sha,raw); raw_hashes.append(sha)
            normalized=encoded(rows); sha=digest(normalized)
            exclusive(store/'objects'/sha,normalized)
            sources.append(dict(series=sid,status='COLLECTED',records_sha256=sha,raw_sha256=raw_hashes,
                earliest=entry['earliest'],latest=entry['latest'],retrieved_at=retrieved,evidence=entry['evidence']))
        receipt=dict(schema='macro-history-bundle-v1',mode=mode,requested_start=start,
            requested_through=through,created_at=utc_now(),registry_sha256=digest(registry_raw),
            sources=sources,durable_remote_verified=True,historical_price_pit_verified=False)
        raw=encoded(receipt); path=store/'receipts'/(digest(raw)+'.json')
        exclusive(path,raw); receipts.append(path)
    result=study(store,receipts[0],utc_now(),[receipts[1]])
    result['durable_remote_verified']=lake.transport.remote_verified
    result['long_history_catalog_generation']=lake.catalog['generation']
    return result,engine_context(result)


def complete_consumer(consumer, result, reports, workspace, *, run_id, macro_start, through, report,
                      recovery=None, cycle=None):
    transport=consumer.transport
    require(consumer.parent==result['commit_sha256'] and digest(encoded(consumer.catalog))==result['catalog_sha256'],
            'consumer_generation_mismatch')
    keys=[k for k,d in consumer.catalog['datasets'].items() if k.startswith(('current/','alfred/','worldbank/'))
          and d['status'] in ('COLLECTED','UNCHANGED')]
    if cycle is not None:
        keys=[k for k in keys if k in cycle['checked_keys']]
    source_only=cycle is not None and cycle['summary'].get('standing_auto',{}).get(
        'provider_scope',{}).get('fred') is False
    with _history_phase('SQL_MATERIALIZATION', datasets=len(keys)) as phase_counts:
        consumer_rows=(0 if source_only and not keys else
                       materialize(consumer,Path(workspace)/'macro.sqlite',keys,through))
        phase_counts['rows']=consumer_rows
    try:
        if source_only:
            proof=(hybrid_source_scope_readback(consumer,cycle['summary'])
                   if cycle['summary']['requested_cycle_complete'] else None)
            result.update(study_recomputed_from_drive=False,macro_regime_ready=False,
                          whole_macro_complete=False,study_blocked_reason='FRED_RIGHTS_BLOCKED_OR_DISABLED_THIS_CYCLE')
            if proof is not None:result['source_cycle_readback']=proof
        else:
            study_result,context=None,None
            with _history_phase('STUDY'):
                study_result,context=analyze_restored(consumer,Path(workspace)/'study',macro_start,through)
            context['catalog_sha256']=result['catalog_sha256']
            if cycle is not None:
                context.update(cycle_scope=cycle['summary'],
                    study_input_scope='ARCHIVAL_RESEARCH_WITH_RETAINED_NOT_CHECKED_INPUTS',
                    whole_universe_current=False)
            with _history_phase('LOCAL_STUDY_REPORTS', reports=2):
                (reports/'macro-evaluation.json').write_bytes(encoded(study_result))
                (reports/'engine-context.json').write_bytes(encoded(context))
            result.update(study_recomputed_from_drive=True,study_tests=study_result['tests_declared'])
    except (Refused,TimeoutError,InterruptedError):
        # Cancellation is not a partial study result and must not publish a receipt.
        raise
    except (ValueError,KeyError,TypeError,OSError) as exc:
        result.update(study_recomputed_from_drive=False,study_blocked_reason=safe_error(exc))
    result.update(consumer_rows=consumer_rows,consumer='VERIFIED_HYBRID_SOURCE_SCOPE' if source_only
                  else 'VERIFIED_SQL_RESEARCH_CACHE',quality_status=report['status'])
    if recovery is not None:
        require(result['study_recomputed_from_drive'] or (source_only and
                'source_cycle_readback' in result),'finalization_study_not_complete')
        with _history_phase('FINALIZATION_RECHECK', commit_sha256=result['commit_sha256'], catalog_sha256=result['catalog_sha256']):
            require(consumer.restore_catalog()[0]==result['commit_sha256'],'finalization_head_changed')
            require(consumer.verified_execution(allow_missing=True) is None,'finalization_execution_changed')
    durable_reports={}
    with _history_phase('REPORT_PUBLICATION') as phase_counts:
        for path in sorted(reports.glob('*.json')):
            raw=path.read_bytes(); sha=digest(raw)
            require(len(raw)<=MAX_OBJECT,'report_size')
            transport.write(f'{PREFIX}/reports/{sha}',raw)
            durable_reports[path.name]=sha
        phase_counts['reports']=len(durable_reports)
    receipt=dict(schema='long-history-execution-v1',run_id=run_id,created_at=utc_now(),
        catalog_sha256=result['catalog_sha256'],commit_sha256=result['commit_sha256'],
        reports=durable_reports,consumer_rows=consumer_rows,
        study_recomputed_from_drive=result['study_recomputed_from_drive'],
        quality_status=report['status'],eligible_for_selector=False)
    if recovery is not None:
        receipt['recovery']=recovery
    if cycle is not None:
        receipt['cycle_scope']=cycle['summary']
        if source_only and 'source_cycle_readback' in result:
            receipt['source_cycle_readback']=result['source_cycle_readback']
        result.update(cycle_scope=cycle['summary'],whole_universe_current=False)
    raw=encoded(receipt); receipt_sha=digest(raw)
    with _history_phase('EXECUTION_RECEIPT_WRITE', commit_sha256=result['commit_sha256'], catalog_sha256=result['catalog_sha256'], application_bytes=len(raw)):
        transport.write(f'{PREFIX}/executions/{receipt_sha}',raw)
    if recovery is not None:
        verified=consumer.verified_execution()
        require(verified['execution_receipt_sha256']==receipt_sha and verified.get('recovery')==recovery,
                'finalization_execution_readback')
        result['recovery']=recovery
    result['execution_receipt_sha256']=receipt_sha
    with _history_phase('LOCAL_PUBLICATION_WRITE'):
        (reports/'publication.json').write_bytes(encoded(result))
    print('LONG_HISTORY_SUMMARY '+json.dumps(dict(result,financial_issuers=report['financial_issuers'],financial_fact_rows=report['financial_fact_rows'])),flush=True)
    if cycle is not None:
        return 0 if cycle['summary']['requested_cycle_complete'] and (result['study_recomputed_from_drive']
            or (source_only and 'source_cycle_readback' in result)) else 2
    if report['status'] in ('PARTIAL','PARTIAL_COVERAGE') or not result['study_recomputed_from_drive']: return 2
    return 0


def finalization_mode(commit_sha256, catalog_sha256, source_head_sha):
    pins=(commit_sha256,catalog_sha256,source_head_sha)
    if not any(pins):
        return False
    require(all(type(v) is str for v in pins) and all(pins)
            and all(re.fullmatch('[a-f0-9]{64}',v) is not None for v in pins[:2])
            and re.fullmatch('[a-f0-9]{40}',pins[2]) is not None,'finalization_pins_required')
    return True


def finalize_existing(lake, args, reports):
    """Complete one already committed generation without collection or a new data commit."""
    require(finalization_mode(args.finalize_commit_sha256,args.finalize_catalog_sha256,args.source_head_sha),
            'finalization_pins_required')
    require(not lake.pending,'finalization_requires_clean_consumer')
    require(lake.parent==args.finalize_commit_sha256,'finalization_head_mismatch')
    commit=json.loads(lake.read_hash('commits',lake.parent))
    require(commit['catalog']==args.finalize_catalog_sha256,'finalization_catalog_mismatch')
    require(lake.catalog.get('code_sha')==args.source_head_sha,'finalization_source_code_mismatch')
    require(lake.catalog.get('run_id')==commit['run_id'],'finalization_source_run_mismatch')
    config=lake.catalog['config']
    require(lake.catalog.get('config_sha256')==digest(encoded(config)),'finalization_config_mismatch')
    macro_start,through=config['macro_start'],config['through']
    require(date.fromisoformat(macro_start).isoformat()==macro_start
            and date.fromisoformat(through).isoformat()==through
            and macro_start<=through<=date.today().isoformat(),'finalization_source_window')
    require(not any(reports.iterdir()),'finalization_report_directory_not_empty')
    code=os.environ.get('GITHUB_SHA','')
    actual_run='history-'+os.environ.get('GITHUB_RUN_ID','')+'-'+os.environ.get('GITHUB_RUN_ATTEMPT','')
    require(re.fullmatch('[a-f0-9]{40}',code) is not None and args.run_id==actual_run
            and re.fullmatch('history-[1-9][0-9]*-[1-9][0-9]*',args.run_id) is not None
            and args.run_id!=commit['run_id'],'finalization_run_identity')
    existing=lake.verified_execution(allow_missing=True)
    result=dict(commit_sha256=lake.parent,catalog_sha256=commit['catalog'],new_packs=0,
                verified_new_bytes=0,remote_verified=lake.transport.remote_verified,eligible_for_selector=False)
    if existing is not None:
        source_only=config.get('hybrid_refresh',{}).get('standing_auto',{}).get(
            'provider_scope',{}).get('fred') is False
        require(existing['study_recomputed_from_drive'] or (source_only and hybrid_execution_ready(
            existing,allow_source_scope=True)),'finalization_existing_incomplete_execution')
        result.update(status='ALREADY_FINALIZED',execution_receipt_sha256=existing['execution_receipt_sha256'],
                      quality_status=existing['quality_status'],consumer_rows=existing['consumer_rows'])
        (reports/'publication.json').write_bytes(encoded(result))
        print('LONG_HISTORY_SUMMARY '+json.dumps(result),flush=True)
        return 0 if source_only and hybrid_execution_ready(existing,allow_source_scope=True) else (
            2 if existing['quality_status'] in ('PARTIAL','PARTIAL_COVERAGE') else 0)
    recovery=dict(schema='long-history-finalization-v1',source_run_id=commit['run_id'],
                  source_head_sha=args.source_head_sha,finalization_run_id=args.run_id,
                  finalizer_head_sha=code,provider_requests_executed=0,new_data_commits=0)
    report=diagnostics(lake)
    cycle=None
    if config.get('hybrid_refresh') is not None:
        detail=config['hybrid_refresh']; summary=detail.get('cycle_scope')
        require(type(summary) is dict and digest(encoded(summary))==detail.get('summary_sha256')
                and digest(encoded(detail.get('checked_keys')))==summary.get('checked_scope_sha256'),
                'hybrid_recovery_scope')
        cycle=dict(summary=summary,checked_keys=set(detail['checked_keys']))
        report.update(inventory_quality_status=report['status'],status='PARTIAL_COVERAGE',cycle_scope=summary)
    (reports/'quality.json').write_bytes(encoded(report))
    return complete_consumer(lake,result,reports,args.workspace,run_id=commit['run_id'],
                             macro_start=macro_start,through=through,report=report,recovery=recovery,cycle=cycle)


def run_hybrid(args, request, request_sha256, *, auto=None):
    """Same Source/Lake publication path, with a checked explicit subset boundary."""
    from tools.alpaca_sip_campaign import RuntimeMeter
    budget=HybridBudget(request)
    reports=Path(args.report_dir)
    require(not reports.exists() or not any(reports.iterdir()),'hybrid_report_replay')
    reports.mkdir(parents=True,exist_ok=True)
    try:
        with RuntimeMeter.process_deadline(budget):
            if auto is None:
                approval=authorize_hybrid(request,request_sha256,args.hybrid_approval_reference)
            else:
                profile,original_sha=auto
                approval=authorize_auto(profile,original_sha,args.hybrid_approval_reference)
                request=auto_request(profile,original_sha,run=approval['run'],reservation=approval['reservation'])
                request_sha256=digest(encoded(request))
                require(args.run_id=='history-'+str(approval['run']['id'])+'-1','auto_cli_run_identity')
                claim_auto_invocation(approval)
            transport=HybridTransport(args.remote,budget)
            with _history_phase('INITIAL_RESTORE'):
                lake=Lake(transport,args.workspace)
            scope=prepare_hybrid_scope(lake,request,request_sha256,budget,approval)
            with _history_phase('MACRO_COLLECTION'):
                collect_macros(lake,request['macro_start'],request['through'],_hybrid=scope)
            with _history_phase('FINANCIAL_COLLECTION'):
                collect_financials(lake,args.cohort,request['financial_start'],request['through'],_hybrid=scope)
            budget.check()
            summary=finish_hybrid_cycle(lake,scope)
            report=diagnostics(lake)
            report.update(inventory_quality_status=report['status'],
                status=('PARTIAL_COVERAGE' if summary['requested_cycle_complete'] else 'PARTIAL')
                    if auto is not None else ('PARTIAL' if report['status']=='PARTIAL' else 'PARTIAL_COVERAGE'),
                cycle_scope=summary)
            (reports/'quality.json').write_bytes(encoded(report))
            config=dict(macro_start=request['macro_start'],financial_start=request['financial_start'],
                through=request['through'],cohort_sha256=COHORT_SHA,archives=list(ARCHIVES),
                countries=list(COUNTRIES),worldbank_indicators=list(WB_INDICATORS),
                registry_sha256=digest(encoded(registry())),hybrid_refresh=scope['detail'])
            with _history_phase('PUBLICATION'):
                result=lake.publish(args.run_id,config)
            with _history_phase('CLEAN_CONSUMER_RESTORE',commit_sha256=result['commit_sha256'],
                                catalog_sha256=result['catalog_sha256']):
                consumer=Lake(transport,Path(args.workspace)/'clean-consumer')
            return complete_consumer(consumer,result,reports,args.workspace,run_id=args.run_id,
                macro_start=request['macro_start'],through=request['through'],report=report,cycle=scope)
    except BaseException:
        print('HYBRID_STOP '+json.dumps(dict(request_sha256=request_sha256,
              state='FAILED_NOT_COMPLETE',budget=budget.summary()),sort_keys=True),flush=True)
        raise
    finally:
        # A small local attempt receipt, not accepted Source state or a new ledger.
        (reports/'hybrid-meter.json').write_bytes(encoded(dict(schema='long-history-hybrid-meter-v1',
            request_sha256=request_sha256,budget=budget.summary(),source_admission=False,
            historical_pit_certified=False,economic_authority=False)))


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--remote',required=True)
    p.add_argument('--workspace',required=True)
    p.add_argument('--cohort',required=True)
    p.add_argument('--run-id',required=True)
    p.add_argument('--report-dir',required=True)
    p.add_argument('--macro-start',default='1996-01-01')
    p.add_argument('--financial-start',default='2016-01-01')
    p.add_argument('--finalize-commit-sha256',default='')
    p.add_argument('--finalize-catalog-sha256',default='')
    p.add_argument('--source-head-sha',default='')
    p.add_argument('--scoped-alfred-request',default='')
    p.add_argument('--scoped-alfred-request-sha256',default='')
    p.add_argument('--hybrid-mode',default='LEGACY')
    p.add_argument('--hybrid-request',default='')
    p.add_argument('--hybrid-request-sha256',default='')
    p.add_argument('--hybrid-approval-reference',default='')
    args=p.parse_args()
    finalizing=finalization_mode(args.finalize_commit_sha256,args.finalize_catalog_sha256,args.source_head_sha)
    scoped=bool(args.scoped_alfred_request or args.scoped_alfred_request_sha256)
    hybrid=args.hybrid_mode!='LEGACY' or bool(args.hybrid_request or args.hybrid_request_sha256
                                            or args.hybrid_approval_reference)
    if hybrid:
        require(args.hybrid_mode in HYBRID_MODES|{'HYBRID_AUTO'} and args.hybrid_request
                and args.hybrid_request_sha256 and args.hybrid_approval_reference
                and not scoped and not finalizing,'hybrid_explicit_inputs_required')
        with Path(args.hybrid_request).open('rb') as stream:
            raw=stream.read(65537)
        auto=None
        if args.hybrid_mode=='HYBRID_AUTO':
            profile=auto_profile(raw,args.hybrid_request_sha256)
            auto=(profile,args.hybrid_request_sha256)
            request=auto_request(profile,args.hybrid_request_sha256)
        else:
            request=hybrid_request(raw,args.hybrid_request_sha256,args.hybrid_mode)
        require(args.macro_start==request['macro_start'] and args.financial_start==request['financial_start'],
                'hybrid_cli_window_conflict')
        return run_hybrid(args,request,args.hybrid_request_sha256,auto=auto)
    require(not scoped or (args.scoped_alfred_request and args.scoped_alfred_request_sha256
                          and not finalizing),'scoped_request_inputs')
    request=None
    if scoped:
        with Path(args.scoped_alfred_request).open('rb') as stream:
            request=scoped_alfred_request(stream.read(16385),args.scoped_alfred_request_sha256)
    reports=Path(args.report_dir); reports.mkdir(parents=True,exist_ok=True)
    # A separate local temp root avoids concurrent collection touching a previous
    # verified source bundle. Network destination is the configured research lane.
    transport=RcloneTransport(args.remote)
    transport.call('mkdir',transport.path(f'{PREFIX}/commits'))
    with _history_phase('INITIAL_RESTORE'):
        lake=Lake(transport,args.workspace)
    if finalizing:
        return finalize_existing(lake,args,reports)
    if scoped:
        # The existing workflow's single-writer concurrency and full history
        # verification also apply here. Publish independently rechecks staleness.
        with _history_phase('MACRO_COLLECTION'):
            meter=collect_scoped_alfred(lake,request)
        config=copy.deepcopy(lake.before['config'])
        # A separately scoped ALFRED run is not a continuation authorization for
        # the previous financial hybrid family. Its old record stays in history.
        config.pop('hybrid_refresh',None)
        config.update(registry_sha256=digest(encoded(registry())),
            scoped_alfred_request_sha256=args.scoped_alfred_request_sha256,
            scoped_alfred_request=request,scoped_alfred_reservations=meter)
        with _history_phase('QUALITY_LOCAL'):
            report=diagnostics(lake)
            (reports/'quality.json').write_bytes(encoded(report))
        with _history_phase('PUBLICATION'):
            result=lake.publish(args.run_id,config)
        with _history_phase('CLEAN_CONSUMER_RESTORE',commit_sha256=result['commit_sha256'],catalog_sha256=result['catalog_sha256']):
            consumer=Lake(transport,Path(args.workspace)/'clean-consumer')
        return complete_consumer(consumer,result,reports,args.workspace,run_id=args.run_id,
            macro_start=config['macro_start'],through=config['through'],report=report)
    through=date.today().isoformat()
    config=dict(macro_start=args.macro_start,financial_start=args.financial_start,through=through,
        cohort_sha256=COHORT_SHA,archives=list(ARCHIVES),countries=list(COUNTRIES),
        worldbank_indicators=list(WB_INDICATORS),registry_sha256=digest(encoded(registry())))
    with _history_phase('MACRO_COLLECTION'):
        collect_macros(lake,args.macro_start,through)
    with _history_phase('FINANCIAL_COLLECTION'):
        collect_financials(lake,args.cohort,args.financial_start,through)
    with _history_phase('QUALITY_LOCAL'):
        report=diagnostics(lake)
        (reports/'quality.json').write_bytes(encoded(report))
    with _history_phase('PUBLICATION'):
        result=lake.publish(args.run_id,config)
    # Exercise the consumer with every macro dataset that passed. Full financial
    # SQL materialization is available on demand. Restore separately verifies
    # all retained pack dependencies, including financial and historical data.
    with _history_phase('CLEAN_CONSUMER_RESTORE', commit_sha256=result['commit_sha256'], catalog_sha256=result['catalog_sha256']):
        consumer=Lake(transport,Path(args.workspace)/'clean-consumer')
    return complete_consumer(consumer,result,reports,args.workspace,run_id=args.run_id,
                             macro_start=args.macro_start,through=through,report=report)

if __name__=='__main__':
    try: raise SystemExit(main())
    except (ValueError,KeyError,TypeError,OSError) as exc:
        raise SystemExit('LONG_HISTORY_BLOCKED:'+safe_error(exc)) from None
