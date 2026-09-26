"""Validation helpers for sovereign/fiscal source contracts.

Research-only. This module validates provenance/PIT/source contracts only. It has
no selector, expected-return, target-weight or order authority.
"""
from __future__ import annotations
import hashlib, json
from datetime import datetime, timedelta, time
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parents[2]
REGISTRY=ROOT/'docs/sovereign_fiscal_source_contracts_v1.json'
SCHEMA=ROOT/'docs/sovereign_fiscal_source_contract_schema_v1.json'

class ContractError(ValueError): pass

def require(cond,msg):
    if not cond: raise ContractError(msg)

def digest(raw: bytes) -> str: return hashlib.sha256(raw).hexdigest()

def load(path: Path): return json.loads(path.read_bytes())

def registry(): return load(REGISTRY)

def schema(): return load(SCHEMA)

def _unique(values,msg): require(len(values)==len(set(values)),msg)

def _aware(value,msg):
    try:
        parsed=datetime.fromisoformat(value)
    except (TypeError,ValueError) as e:
        raise ContractError(msg) from e
    require(parsed.tzinfo is not None and parsed.utcoffset() is not None,msg)
    return parsed

def _hex64(value,msg):
    require(isinstance(value,str) and len(value)==64 and all(c in '0123456789abcdef' for c in value.lower()),msg)
    return value

def validate_registry(payload=None):
    r=registry() if payload is None else payload
    s=schema()
    require(isinstance(r,dict),'registry_root')
    for f in s['required_root_fields']: require(f in r,'missing_root:'+f)
    require(r['schema']=='sovereign-fiscal-source-contract-registry-v1','registry_schema')
    require(r['version']==1,'registry_version')
    require(r['mode']=='RESEARCH_ONLY','mode')
    require(r['selector_execution_allowed'] is False,'selector_authority')
    require(r['portfolio_authority'] is False,'portfolio_authority')
    _unique([x['source_contract_id'] for x in r['source_contracts']],'duplicate_contract_id')
    require(set(r['allowed_pit_classes'])==set(s['pit_classes']),'pit_enum_drift')
    require(set(r['allowed_revision_statuses'])==set(s['revision_statuses']),'revision_enum_drift')
    require(set(r['allowed_downstream_contexts'])==set(s['downstream_contexts']),'context_enum_drift')
    require(set(r['allowed_risk_families'])==set(s['risk_families']),'risk_family_enum_drift')
    require(set(r['forbidden_economic_fields'])==set(s['forbidden_economic_fields']),'forbidden_enum_drift')
    _unique(r['allowed_perimeters'],'duplicate_perimeter')
    forbidden=set(s['forbidden_economic_fields'])
    for c in r['source_contracts']:
        validate_source_contract(c,r,s,forbidden)
    return r

def validate_source_contract(c,r,s,forbidden=None):
    forbidden=set(s['forbidden_economic_fields']) if forbidden is None else forbidden
    require(isinstance(c,dict),'contract_root')
    for f in s['required_contract_fields']: require(f in c,'missing_contract:'+f)
    require(isinstance(c['source_contract_id'],str) and c['source_contract_id'],'contract_id')
    require(c['country'] in {'USA','CHN'},'country')
    require(isinstance(c['source_authority'],str) and c['source_authority'].strip(),'source_authority')
    require(isinstance(c['canonical_source_uri'],str) and c['canonical_source_uri'],'source_uri')
    if c['pit_class'] not in {'HISTORICAL_BLOCKED','DERIVED_AFTER_PIT_INPUTS'}:
        require(c['canonical_source_uri'].startswith('https://'),'source_uri')
    require(isinstance(c['frequency'],str) and c['frequency'],'frequency')
    require(c['risk_family'] in r['allowed_risk_families'],'risk_family')
    require(c['pit_class'] in r['allowed_pit_classes'],'pit_class')
    require(c['perimeter'] in r['allowed_perimeters'],'perimeter')
    require(c['unit_contract'] not in {None,''},'unit_contract')
    require(c['currency_contract'] not in {None,''},'currency_contract')
    for policy in ('revision_policy','methodology_policy','historical_archive_policy','raw_redistribution_policy'):
        require(isinstance(c[policy],str) and c[policy].strip(),'policy:'+policy)
    require(bool(c['source_timezone']),'timezone')
    try: ZoneInfo(c['source_timezone'])
    except Exception as e: raise ContractError('timezone') from e
    require(set(c['downstream_contexts']) <= set(r['allowed_downstream_contexts']),'downstream_context')
    require(forbidden.isdisjoint(c.keys()),'forbidden_economic_field')
    require(forbidden.issubset(set(c['forbidden_uses'])),'forbidden_use_contract')
    require(set(s['required_row_fields']) <= set(c['required_row_fields']),'row_contract')
    if c['pit_class'] in {'FORWARD_PIT_ONLY','HISTORICAL_BLOCKED'}:
        require('HISTORICAL_REPLAY_ALLOWED' not in c.get('historical_archive_policy',''),'historical_replay_forbidden')
    if c['pit_class']=='HISTORICAL_DATE_PIT':
        require(c['publication_precision']=='DATE_ONLY','date_precision')
        require(c['availability_rule']=='NEXT_CALENDAR_DAY_00_LOCAL','date_availability')
    if c['pit_class']=='HISTORICAL_EXACT_PIT':
        require(c['publication_precision']=='EXACT_TIMESTAMP','exact_precision')
        require(c['availability_rule']=='OFFICIAL_TIMESTAMP','exact_availability')
    if c['perimeter'].startswith('CN_IMF_'):
        authority=c['source_authority'].upper()
        require('IMF' in authority or 'INTERNATIONAL MONETARY FUND' in authority,'imf_source_authority')
    if c['perimeter'].startswith('CN_OFFICIAL_'):
        require('IMF' not in c['source_authority'].upper(),'official_source_not_staff_estimate')
    if c['source_contract_id']=='CN_IMF_AUGMENTED_DEBT':
        require(c['perimeter']=='CN_IMF_AUGMENTED_GENERAL_GOVERNMENT','imf_augmented_perimeter')
        require('STAFF_ESTIMATE' in c['methodology_policy'],'imf_staff_estimate')
    if c['source_contract_id']=='CN_LGFV_MONTHLY_HIDDEN_DEBT':
        require(c['pit_class']=='HISTORICAL_BLOCKED','lgfv_monthly_blocked')
    if c['source_contract_id']=='US_ACM_TERM_PREMIUM':
        require(c['pit_class']=='FORWARD_PIT_ONLY','acm_forward_only')
    return c

def next_day_available(publication_date: str, timezone: str) -> str:
    d=datetime.fromisoformat(publication_date).date()+timedelta(days=1)
    return datetime.combine(d,time(0,0),ZoneInfo(timezone)).isoformat()

def validate_row(contract,row,decision_cutoff=None):
    r=registry(); s=schema(); validate_source_contract(contract,r,s)
    for f in contract['required_row_fields']: require(f in row,'missing_row:'+f)
    require(row['series_id']==contract['source_contract_id'],'row_series_identity')
    require(row['pit_class']==contract['pit_class'],'row_pit_class')
    require(row['perimeter']==contract['perimeter'],'row_perimeter')
    require(row['published_at_precision']==contract['publication_precision'],'row_publication_precision')
    require(row['frequency']==contract['frequency'],'row_frequency')
    require(row['revision_status'] in r['allowed_revision_statuses'],'revision_status')
    require(row['unit'] not in {None,'','UNKNOWN'},'unit')
    require(row['currency'] not in {None,''},'currency')
    _hex64(row['raw_sha256'],'raw_sha256')
    _hex64(row['parsed_row_sha256'],'parsed_row_sha256')
    if row['revision_status']=='PROJECTION': require(row['estimate_type']=='PROJECTION','projection_estimate_type')
    if row['revision_status']=='STAFF_ESTIMATE':
        require(contract['perimeter'].startswith('CN_IMF_'),'staff_estimate_perimeter')
        require(row['estimate_type'] in {'STAFF_ESTIMATE','PROJECTION'},'staff_estimate_type')
    if contract['pit_class']=='HISTORICAL_BLOCKED':
        require(row['decision_available_at'] is None,'blocked_decision_availability')
        return row
    if contract['pit_class']=='DERIVED_AFTER_PIT_INPUTS':
        require(row['decision_available_at'] is not None,'derived_availability')
    else:
        require(row['public_available_at'] is not None,'public_availability')
        require(row['decision_available_at'] is not None,'decision_availability')
    public_at=None
    decision_at=_aware(row['decision_available_at'],'decision_availability_timestamp') if row['decision_available_at'] else None
    if row['public_available_at']:
        public_at=_aware(row['public_available_at'],'public_availability_timestamp')
        require(decision_at is not None and decision_at>=public_at,'decision_before_public_availability')
    if contract['pit_class']=='HISTORICAL_DATE_PIT':
        require(row['published_at_precision']=='DATE_ONLY','row_date_precision')
        try:
            published=datetime.fromisoformat(row['published_at_source'])
        except (TypeError,ValueError) as e:
            raise ContractError('published_date') from e
        require('T' not in row['published_at_source'],'published_date_precision')
        expected=next_day_available(row['published_at_source'],contract['source_timezone'])
        require(row['public_available_at']==expected,'same_day_or_wrong_date_availability')
    if contract['pit_class']=='HISTORICAL_EXACT_PIT':
        published=_aware(row['published_at_source'],'published_timestamp')
        require(public_at==published,'exact_public_availability_mismatch')
    if row['reconstructed_from_release_archive']:
        _hex64(row.get('publication_metadata_sha256'),'publication_metadata_sha256')
        require(row['revision_status']!='CURRENT_VINTAGE','current_vintage_historical_reconstruction')
    if decision_cutoff and row['decision_available_at']:
        require(decision_at<=_aware(decision_cutoff,'decision_cutoff'),'future_availability')
    return row

def validate_vintage_chain(rows):
    ids=[]; seen={}
    for row in rows:
        vid=row['vintage_id']; require(vid not in seen,'vintage_overwrite_or_duplicate')
        if row.get('supersedes_vintage_id'):
            require(row['supersedes_vintage_id'] in seen,'supersedes_unknown_vintage')
        seen[vid]=row; ids.append(vid)
    return ids

def contract_hashes():
    return {'registry_sha256':digest(REGISTRY.read_bytes()),'schema_sha256':digest(SCHEMA.read_bytes())}
