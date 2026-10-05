"""H1 review-invalidation bridge, not a scorer, dispatcher or accepted-state writer.

Existing C1/H1 and Chameleon adapters supply diagnostic observations. This module
compares frozen observations, identifies affected candidate slices, and prepares
ONE aggregate parameter proposal per existing A0 agent. Native producer/current
reference authentication and A0 materialization remain mandatory outside it.
No I/O occurs in this module, including imports of the optional producer adapters.
"""
from __future__ import annotations
import hashlib
import json
import math
import re
from datetime import date, datetime, timezone
from typing import Any

SCHEMA = 'candidate-reassessment-review-v1'
CLOSED = dict(execute=False, specialist_dispatch=False, economic_admission=False,
              er_calculated=False, ranking_allowed=False, canonical_write=False,
              orders_allowed=False, source_authenticated=False)
FAMILIES = {'ACTUAL','GUIDANCE','CONSENSUS','PRICE','MACRO','REGIME',
            'SENTIMENT','POSITIONING','OPTIONS','LEADERSHIP','HARD_RISK','FILING'}
KINDS = {'SECURITY','ISSUER','MACRO_SERIES','MARKET','THEME'}
CHANNELS = {'EARNINGS','CASHFLOW','VALUATION','TIMING','RISK','COMPETITIVE_POSITION'}
# Unscoped code/config/model/parameter/dependency and index changes cannot prove
# that any candidate computation remains reusable. Review only, never execution.
FULL_REASSESSMENT_SLICES = frozenset({
    'EARNINGS','CASHFLOW','VALUATION','EXPECTED_RETURN','RS_PATH','TIMING',
    'RISK_CONTEXT','THESIS_RISK','COMPETITIVE_POSITION','FULL_EARNINGS_THESIS_REVIEW',
    'FILING_CONTENT_REVIEW','ACTUALS_EXTRACTION_REVIEW',
})
FIELDS = {'family','provider','entity_kind','entity_id','metric','fiscal_period',
          'observation_period','identity','values','status','available_at',
          'collected_at','revision_id','source_sha256','causal_event_id'}
_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9._:/+@-]{0,199}\Z')
_HASH = re.compile(r'[a-f0-9]{64}\Z')
_STAMP = re.compile(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})\Z')
MAX_BYTES = 4_000_000
MAX_ROWS = 10_000

class ReassessmentError(ValueError):
    pass

def need(ok: bool, reason: str) -> None:
    if not ok: raise ReassessmentError(reason)

def clean(value: Any) -> Any:
    stack=[(value,0)]; count=0
    while stack:
        x,d=stack.pop(); count+=1
        need(d<=24 and count<=200_000,'JSON_BUDGET')
        if type(x) is dict:
            need(all(type(k) is str for k in x),'JSON_KEY')
            stack.extend((v,d+1) for v in x.values())
        elif type(x) is list: stack.extend((v,d+1) for v in x)
        elif type(x) is float: need(math.isfinite(x),'NONFINITE')
        elif type(x) is int: need(x.bit_length()<=1024,'INTEGER_BUDGET')
        else: need(x is None or type(x) in (str,bool),'JSON_TYPE')
    raw=json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
    need(len(raw)<=MAX_BYTES,'BYTE_BUDGET')
    return json.loads(raw)

def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(clean(value),sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

def ident(value: Any) -> str:
    need(type(value) is str and _ID.fullmatch(value) is not None,'IDENTIFIER')
    return value

def sha(value: Any) -> str:
    need(type(value) is str and _HASH.fullmatch(value) is not None,'HASH')
    return value

def stamp(value: Any) -> datetime:
    need(type(value) is str and _STAMP.fullmatch(value) is not None,'EXACT_TIMESTAMP')
    try: return datetime.fromisoformat(value.replace('Z','+00:00')).astimezone(timezone.utc)
    except ValueError: raise ReassessmentError('EXACT_TIMESTAMP') from None

def day(value: Any) -> str:
    need(type(value) is str,'DATE')
    try: need(date.fromisoformat(value).isoformat()==value,'DATE')
    except ValueError: raise ReassessmentError('DATE') from None
    return value

def seal(payload: dict) -> dict:
    result=clean(payload);result['content_sha256']=digest(result);return result

def verify(value: dict, schema: str) -> None:
    clean(value)
    need(type(value) is dict and value.get('schema')==schema,'SCHEMA')
    sha(value.get('content_sha256'))
    need(value['content_sha256']==digest({k:v for k,v in value.items() if k!='content_sha256'}),'CONTENT_HASH')

def row_key(row: dict) -> str:
    # Provider and fiscal identity never join by rolling FY1/FY2 labels.
    return digest({k:row[k] for k in ('family','provider','entity_kind','entity_id','metric','fiscal_period','identity')})

def semantic(row: dict) -> dict:
    # Receipt/transport freshness is not a new economic observation by itself.
    omit={'available_at','collected_at','source_sha256'}
    if row['family']=='CONSENSUS': omit.add('observation_period')
    result={k:v for k,v in row.items() if k not in omit}
    if row['family']=='FILING':
        result['values']={k:v for k,v in row['values'].items() if k!='source_observed_at'}
    return result

def validate_row(row: dict, cutoff: str) -> None:
    need(type(row) is dict and set(row)==FIELDS,'ROW_FIELDS')
    need(row['family'] in FAMILIES and row['entity_kind'] in KINDS,'ROW_CLASS')
    for name in ('provider','entity_id','metric','status','revision_id'): ident(row[name])
    need(row['status'] in {'OBSERVED','MISSING','STALE','FAILED','UNKNOWN_IDENTITY','UNKNOWN_PUBLICATION'},'ROW_STATUS')
    sha(row['source_sha256']); day(row['observation_period'])
    if row['fiscal_period'] is not None: day(row['fiscal_period'])
    need(type(row['identity']) is dict and type(row['values']) is dict,'ROW_CONTENT')
    if row['causal_event_id'] is not None: ident(row['causal_event_id'])
    # A collected response may become usable later. We require both times before
    # cutoff but do NOT impose the incompatible A0 observed<=available<=collected.
    need(stamp(row['available_at'])<=stamp(cutoff) and stamp(row['collected_at'])<=stamp(cutoff),'FUTURE_EVIDENCE')
    need(date.fromisoformat(row['observation_period'])<=stamp(row['collected_at']).date(),'FUTURE_OBSERVATION')

def snapshot(rows: list[dict], *, scope_id: str, cutoff: str, expires_at: str) -> dict:
    ident(scope_id);need(stamp(cutoff)<stamp(expires_at),'EXPIRY')
    rows=clean(rows);need(type(rows) is list and len(rows)<=MAX_ROWS,'ROWS_BUDGET')
    seen=set()
    for row in rows:
        validate_row(row,cutoff);key=row_key(row)
        need(key not in seen,'DUPLICATE_OBSERVATION');seen.add(key)
    return seal(dict(schema='review-observation-snapshot-v1',scope_id=scope_id,cutoff=cutoff,
                     expires_at=expires_at,rows=sorted(rows,key=row_key),source_authenticated=False))

def exposure_index(*, candidates: list[dict], edges: list[dict], available_at: str,
                   expires_at: str) -> dict:
    """Supplied evidence only. No automatic macro exposure or peer inference."""
    need(stamp(available_at)<stamp(expires_at),'INDEX_EXPIRY')
    candidates,edges=clean(candidates),clean(edges)
    need(len(candidates)<=MAX_ROWS and len(edges)<=MAX_ROWS,'INDEX_BUDGET')
    assets=set();edge_keys=set()
    for row in candidates:
        need(set(row)=={'asset_id','issuer_id'},'CANDIDATE_FIELDS')
        ident(row['asset_id']);ident(row['issuer_id']);need(row['asset_id'] not in assets,'DUPLICATE_ASSET');assets.add(row['asset_id'])
    for edge in edges:
        need(set(edge)=={'entity_kind','entity_id','asset_id','channels','evidence_sha256','available_at'},'EDGE_FIELDS')
        need(edge['entity_kind'] in KINDS and edge['asset_id'] in assets,'EDGE_TARGET')
        ident(edge['entity_id']);sha(edge['evidence_sha256'])
        need(type(edge['channels']) is list and 0<len(edge['channels'])==len(set(edge['channels'])) and set(edge['channels'])<=CHANNELS,'EDGE_CHANNELS')
        need(stamp(edge['available_at'])<=stamp(available_at),'FUTURE_EDGE')
        key=(edge['entity_kind'],edge['entity_id'],edge['asset_id'])
        need(key not in edge_keys,'DUPLICATE_EDGE');edge_keys.add(key)
    return seal(dict(schema='review-exposure-index-v1',candidates=sorted(candidates,key=lambda x:x['asset_id']),
                     edges=sorted(edges,key=lambda x:(x['entity_kind'],x['entity_id'],x['asset_id'])),
                     available_at=available_at,expires_at=expires_at,source_authenticated=False))

def _targets(row: dict, index: dict) -> dict[str,set[str]]:
    out={}
    for c in index['candidates']:
        if ((row['entity_kind']=='SECURITY' and c['asset_id']==row['entity_id']) or
            (row['entity_kind']=='ISSUER' and c['issuer_id']==row['entity_id'])):
            out[c['asset_id']]=set()
    for e in index['edges']:
        if e['entity_kind']==row['entity_kind'] and e['entity_id']==row['entity_id']:
            out.setdefault(e['asset_id'],set()).update(e['channels'])
    return out

def plan_reassessment(previous: dict|None, current: dict, index: dict, *, now: str,
                      contract_identity: dict, previous_contract_identity: dict|None=None,
                      previous_index_sha256: str|None=None, due_events: list[dict]|None=None) -> dict:
    """Produce review intents and revocation suggestions, never update old ER.

    contract_identity binds the actual source/config/model/parameters/dependencies.
    It is a supplied identity, not authenticated CI or model approval. The native
    A0 must verify current receipts and materialize fresh state independently.
    """
    verify(current,'review-observation-snapshot-v1');verify(index,'review-exposure-index-v1')
    need(current==snapshot(current['rows'],scope_id=current['scope_id'],cutoff=current['cutoff'],expires_at=current['expires_at']),'SNAPSHOT_CONTRACT')
    need(index==exposure_index(candidates=index['candidates'],edges=index['edges'],available_at=index['available_at'],expires_at=index['expires_at']),'INDEX_CONTRACT')
    need(stamp(current['cutoff'])<=stamp(now),'FUTURE_SNAPSHOT')
    need(stamp(index['available_at'])<=stamp(current['cutoff']) and stamp(now)<stamp(index['expires_at']),'INDEX_NOT_CURRENT')
    required={'code_sha','config_sha256','model_version','parameters_sha256','dependency_sha256'}
    need(type(contract_identity) is dict and set(contract_identity)==required,'CONTRACT_IDENTITY')
    need(type(contract_identity['code_sha']) is str and re.fullmatch('[a-f0-9]{40}',contract_identity['code_sha']) is not None,'CODE_SHA')
    for k in ('config_sha256','parameters_sha256','dependency_sha256'):sha(contract_identity[k])
    ident(contract_identity['model_version'])
    if previous is not None:
        verify(previous,'review-observation-snapshot-v1')
        need(previous==snapshot(previous['rows'],scope_id=previous['scope_id'],cutoff=previous['cutoff'],expires_at=previous['expires_at']),'PRIOR_CONTRACT')
        need(previous['scope_id']==current['scope_id'],'SCOPE_CHANGED_REAUDIT')
        need(stamp(previous['cutoff'])<=stamp(current['cutoff']),'TIME_REGRESSION')
    old={} if previous is None else {row_key(r):r for r in previous['rows']}
    new={row_key(r):r for r in current['rows']}
    events=[]
    def event(row,reason):
        payload={'key':row_key(row),'reason':reason,'family':row['family'],
                 'entity_kind':row['entity_kind'],'entity_id':row['entity_id'],
                 'causal_event_id':row['causal_event_id'],'observation':semantic(row)}
        payload['event_id']=digest(payload);events.append(payload)
    expired=stamp(now)>=stamp(current['expires_at'])
    for key in sorted(set(old)|set(new)):
        a,b=old.get(key),new.get(key)
        if b is None:event(a,'MISSING_FROM_COMPLETE_SCOPE');continue
        # Unavailable/expired rows cannot bypass same-identity source clocks.
        if a is not None:
            need(stamp(a['available_at'])<=stamp(b['available_at']) and stamp(a['collected_at'])<=stamp(b['collected_at']),'ROW_TIME_REGRESSION')
            same_clocks=(stamp(a['available_at'])==stamp(b['available_at']) and
                         stamp(a['collected_at'])==stamp(b['collected_at']))
            need(not (same_clocks and semantic(a)!=semantic(b)), 'CONFLICTING_VINTAGE')
        if expired:event(b,'SOURCE_EXPIRED');continue
        if b['status']!='OBSERVED':event(b,'SOURCE_'+b['status']);continue
        if a is None:event(b,'NEW_OBSERVATION');continue
        if b['observation_period']<a['observation_period']:event(b,'OBSERVATION_REGRESSION');continue
        if semantic(a)==semantic(b):continue
        if b['family']!='CONSENSUS' and b['observation_period']!=a['observation_period']:event(b,'NEW_OBSERVATION')
        elif b['revision_id']!=a['revision_id']:event(b,'CORRECTION')
        else:event(b,'VALUE_OR_STATUS_CHANGED')
    due_events=clean(due_events or [])
    need(len(due_events)<=MAX_ROWS,'DUE_BUDGET'); due_seen=set()
    for due in due_events:
        need(set(due)=={'event_id','kind','entity_kind','entity_id','due_at','evidence_sha256'},'DUE_FIELDS')
        ident(due['event_id']);ident(due['entity_id']);sha(due['evidence_sha256'])
        need(due['kind'] in {'CATALYST_DUE','OUTCOME_MATURED','SOURCE_FAILURE','HARD_RISK_REVIEW'} and due['entity_kind'] in KINDS,'DUE_KIND')
        need(due['event_id'] not in due_seen,'DUPLICATE_DUE');due_seen.add(due['event_id'])
        need(stamp(due['due_at'])<=stamp(now),'NOT_YET_DUE')
        events.append(dict(event_id=digest(due),key=due['event_id'],reason=due['kind'],
                           family='HARD_RISK' if due['kind']=='HARD_RISK_REVIEW' else 'LEADERSHIP',
                           entity_kind=due['entity_kind'],entity_id=due['entity_id'],
                           causal_event_id=None,observation=due))
    contract_change=previous is not None and previous_contract_identity!=contract_identity
    index_change=previous is not None and previous_index_sha256!=index['content_sha256']
    if contract_change or index_change:
        for c in index['candidates']:
            events.append(dict(event_id=digest({'asset':c['asset_id'],'contract':contract_identity,'index':index['content_sha256']}),
                               key=c['asset_id'],reason='CONTRACT_OR_INDEX_CHANGED',family='CONTRACT_CHANGE',
                               entity_kind='SECURITY',entity_id=c['asset_id'],causal_event_id=None,observation={}))
    requests={};invalidations={};unmapped=[]
    def request(agent,asset,slices,eid,conditions):
        r=requests.setdefault(agent,{'agent':agent,'asset_ids':set(),'global_review':False,'slices':set(),
                                     'event_ids':set(),'requires':set(),'asset_slices':{}})
        if asset is None:r['global_review']=True
        else:
            r['asset_ids'].add(asset)
            r['asset_slices'].setdefault(asset,set()).update(slices)
        r['slices'].update(slices);r['event_ids'].add(eid);r['requires'].update(conditions)
    for e in events:
        targets=_targets(e,index);reason=e['reason'];family=e['family'];eid=e['event_id']
        market=(family in {'MACRO','REGIME','SENTIMENT','OPTIONS','POSITIONING'} or e['entity_kind'] in {'MACRO_SERIES','MARKET'})
        hard=family=='HARD_RISK'
        repair=(reason.startswith('SOURCE_') or reason in {'MISSING_FROM_COMPLETE_SCOPE','OBSERVATION_REGRESSION'})
        if reason=='OUTCOME_MATURED':
            for asset in targets or {None:set()}:request('A8',asset,{'MATURED_COHORT'},eid,{'OUTCOME_SOURCE_VERIFIED'})
            continue
        request('A1',None if market or not targets else next(iter(sorted(targets))),{'SOURCE_IDENTITY_PIT'},eid,{'CURRENT_SOURCE_RECEIPT'})
        if market:
            request('A4',None,{'MACRO_CONTEXT','RISK_TRANSMISSION'},eid,{'A1_CURRENT_VERIFIED'})
            if not repair: request('A5',None,{'PORTFOLIO_COMMON_RISK_REVIEW'},eid,{'CURRENT_A4','CURRENT_REVALIDATED_A3_ER','INDEPENDENT_A6'})
        if not targets and not market:
            unmapped.append(eid);request('A2',None,{'IDENTITY_DISCOVERY_NO_EXCLUSION'},eid,{'IDENTITY_RESOLVED'})
        if market and not targets:
            unmapped.append(eid);request('A4',None,{'EXPOSURE_MAP_REVIEW'},eid,{'EXPOSURE_MEMBERSHIP_VERIFIED'})
        if repair:
            request('A6',None,{'SOURCE_FAILURE_REVIEW'},eid,{'FAILURE_ARTIFACT_VERIFIED'})
        for asset,channels in sorted(targets.items()):
            request('A1',asset,{'SOURCE_IDENTITY_PIT'},eid,{'CURRENT_SOURCE_RECEIPT'})
            slices=set()
            if family=='CONTRACT_CHANGE':slices|=FULL_REASSESSMENT_SLICES
            if family in {'ACTUAL','GUIDANCE','CONSENSUS'}:slices|={'EARNINGS','CASHFLOW','VALUATION','EXPECTED_RETURN'}
            if family=='ACTUAL':slices.add('FULL_EARNINGS_THESIS_REVIEW')
            if family=='FILING':slices|={'FILING_CONTENT_REVIEW','ACTUALS_EXTRACTION_REVIEW'}
            if family in {'PRICE','LEADERSHIP'}:slices|={'RS_PATH','TIMING','VALUATION','EXPECTED_RETURN'}
            if family=='MACRO':
                slices|={'RISK_CONTEXT'}
                if channels&{'CASHFLOW','EARNINGS'}:slices|={'CASHFLOW','EXPECTED_RETURN'}
                if 'VALUATION' in channels:slices|={'VALUATION','EXPECTED_RETURN'}
            if family in {'REGIME','SENTIMENT','POSITIONING','OPTIONS'}:slices|={'RISK_CONTEXT','TIMING'}
            if hard:slices={'P0_VERIFICATION','THESIS_RISK'}
            inv=invalidations.setdefault(asset,{'asset_id':asset,'slices':set(),'event_ids':set(),'status':'REVIEW_REQUIRED'})
            inv['slices'].update(slices);inv['event_ids'].add(eid)
            if repair:
                inv['status']='DATA_REPAIR_REQUIRED'
                if hard: request('A6',asset,{'P0_VERIFICATION_NO_RS_WAIT'},eid,{'HARD_RISK_SOURCE_AUTHENTICATION'})
                continue
            if hard:
                request('A6',asset,{'P0_VERIFICATION_NO_RS_WAIT'},eid,{'HARD_RISK_SOURCE_AUTHENTICATION'})
                request('A3',asset,{'THESIS_RISK'},eid,{'HARD_RISK_SOURCE_AUTHENTICATION'})
            elif family=='FILING':
                # A3 owns initial content/extraction review. Verified metrics are
                # a later ER admission gate, not an input to their own extraction.
                request('A3',asset,slices,eid,{'A1_CURRENT_VERIFIED'})
            else:
                request('A2',asset,{'FULL_CANDIDATE_REASSESSMENT'} if family=='CONTRACT_CHANGE' else
                        {'LEADERSHIP_REVIEW'},eid,{'A1_CURRENT_VERIFIED'})
                requirements={'A1_CURRENT_VERIFIED','RELEVANT_A2_A4_EVIDENCE_VERIFIED'}
                request('A3',asset,slices,eid,requirements)
            # Filing metadata alone does not provide new company values or ER.
            # Let the later verified ACTUAL/GUIDANCE event request A5 competition.
            if family!='FILING':
                request('A5',asset,{'CANDIDATE_COMPETITION_REVIEW'},eid,
                        {'CURRENT_REVALIDATED_A3_ER','CURRENT_A4','INDEPENDENT_A6','VERIFIED_COST_RISK_CONTEXT'})
    # One aggregate proposal per agent fits the board's existing one-request-per-agent contract.
    def export(row):
        return {k:(sorted(v) if isinstance(v,set) else
                   {a:sorted(parts) for a,parts in sorted(v.items())} if k=='asset_slices' else v)
                for k,v in row.items()}
    intents=[export(requests[k]) for k in sorted(requests)]
    for r in intents:r.update(status='PROPOSAL_ONLY_NOT_A0_READY',execute=False)
    result=dict(schema=SCHEMA,status='REVIEW_REQUESTED' if events else 'NO_NEW_REVIEW_INTENT',
                previous_snapshot_sha256=None if previous is None else previous['content_sha256'],
                current_snapshot_sha256=current['content_sha256'],index_sha256=index['content_sha256'],
                contract_identity=contract_identity,as_of=now,events=sorted(events,key=lambda x:x['event_id']),
                review_intents=intents,invalidations=[export(invalidations[k]) for k in sorted(invalidations)],
                unmapped_event_ids=sorted(set(unmapped)),
                a0_connection='PARAMETER_PROPOSAL_ONLY_REQUIRES_TRUSTED_MATERIALIZER',**CLOSED)
    return seal(result)

def a0_parameter_proposals(plan: dict) -> dict:
    verify(plan,SCHEMA)
    need(all(type(plan.get(k)) is bool and plan[k] is False for k in CLOSED),'AUTHORITY')
    need(type(plan['review_intents']) is list,'INTENTS')
    agents=set()
    for r in plan['review_intents']:
        need(r.get('agent') in {'A1','A2','A3','A4','A5','A6','A8'} and r['agent'] not in agents,'INTENT_AGENT')
        agents.add(r['agent'])
        need(r.get('execute') is False and r.get('status')=='PROPOSAL_ONLY_NOT_A0_READY','INTENT_AUTHORITY')
    return {r['agent']:{'candidate_reassessment':{'plan_sha256':plan['content_sha256'],
                'input_snapshot_sha256':plan['current_snapshot_sha256'],
                'exposure_index_sha256':plan['index_sha256'], 'scope':r,
                'meaning':'REVIEW_REQUEST_NOT_COMPLETION_OR_DISPATCH'}} for r in plan['review_intents']}

def calendar_rows(payload: dict, symbols: list[str], *, observed_at: str, collected_at: str) -> list[dict]:
    """Invoke actual C1/H1, preserve response-time vendor semantics and identity nulls."""
    from tools.eodhd_calendar_trends import build_h1_batch
    snapshots,batch=build_h1_batch(payload,symbols,observed_at=observed_at,collected_at=collected_at)
    h1_by_symbol={s['ticker']+'.US':s for s in snapshots}
    rows=[]
    for symbol in batch['symbols']:
        s=batch['by_symbol'][symbol]
        h1=h1_by_symbol[symbol]
        publication_unknown=h1['available_from'] is None
        available=h1['available_from'] or collected_at
        for item,eps,rev in zip(s['vendor_observations'],s['eps_payload']['data'],s['revenue_payload']['data']):
            identity={k:eps.get(k) for k in ('issuer_id','security_id','accounting_basis','currency','share_or_ADR_unit')}
            identity['period_type']=item['period_type']
            rows.append(dict(family='CONSENSUS',provider='eodhd_calendar',entity_kind='SECURITY',
                entity_id=eps.get('security_id') or symbol,metric='EPS_REVENUE_CONSENSUS',
                fiscal_period=item['fiscal_period_end'],observation_period=stamp(collected_at).date().isoformat(),
                identity=identity,values={'fields':item['fields'],'lookback_status':item['lookback_status'],
                    'breadth_status':item['breadth_status'],'publication_status':h1['publication_status']},
                status=('UNKNOWN_PUBLICATION' if publication_unknown else 'UNKNOWN_IDENTITY' if not all(identity.values()) else
                        'MISSING' if eps['avg'] is None and rev['avg'] is None else 'OBSERVED'),
                available_at=available,collected_at=collected_at,
                revision_id=eps.get('provider_version') or 'response-observation',source_sha256=batch['normalized_payload_sha256'],causal_event_id=None))
    return rows

def macro_rows_from_context(context: dict, *, observed_at: str) -> list[dict]:
    """Connect the actual #576 context contract; no broad market-to-ER inference."""
    from tools.chameleon_market_context_v2 import verify_context
    verify_context(context);need(stamp(context['cutoff'])<=stamp(observed_at),'CONTEXT_NOT_YET_OBSERVED')
    rows=[]
    for entity,item in sorted(context['macro'].items()):
        family='OPTIONS' if item['family'].startswith('OPTION_') else 'MACRO'
        rows.append(dict(family=family,provider=item['source_id'].split(':')[0],entity_kind='MACRO_SERIES',
            entity_id=entity,metric='level',fiscal_period=None,observation_period=item['observation_date'],
            identity={'unit':item['unit'],'truth_class':item['truth_class']},values={'value':item['value']},
            status='OBSERVED' if item['status']=='OBSERVED' else 'STALE' if 'STALE' in item['status'] else 'MISSING',
            available_at=observed_at,collected_at=observed_at,revision_id='context-observation',
            source_sha256=sha(item['source_sha256']),causal_event_id=None))
    return rows

# FREE_FIRST_C1: descriptive review dependency profile, NOT an economic model.
FREE_FIRST_PROFILE = 'free-first-review-inputs-v1'
_CORE_CAPABILITIES = {
    'filing_content_review': frozenset({'FILING'}),
    'actuals_review': frozenset({'ACTUAL'}),
    'price_leadership_review': frozenset({'PRICE'}),
    'actuals_price_joint_review': frozenset({'ACTUAL', 'PRICE'}),
}
_SEC_FORMS = frozenset({'10-K','10-K/A','10-Q','10-Q/A','8-K','8-K/A',
                        '20-F','20-F/A','40-F','40-F/A','6-K','6-K/A'})
_ACCESSION = re.compile(r'[0-9]{10}-[0-9]{2}-[0-9]{6}\Z')


def _strict_raw_object(raw: bytes, expected_sha256: str) -> dict:
    """Bounded byte/hash check only. The caller still authenticates the source."""
    need(type(raw) is bytes and 0 < len(raw) <= MAX_BYTES, 'RAW_BYTES_BUDGET')
    need(hashlib.sha256(raw).hexdigest() == sha(expected_sha256), 'RAW_HASH_MISMATCH')
    def pairs(items):
        out={}
        for k,v in items:
            need(k not in out, 'DUPLICATE_JSON_KEY');out[k]=v
        return out
    def constant(_):raise ReassessmentError('NONFINITE_RAW_JSON')
    try:
        obj=json.loads(raw,object_pairs_hook=pairs,parse_constant=constant)
        need(type(obj) is dict,'RAW_OBJECT')
        return clean(obj)
    except ReassessmentError:raise
    except (ValueError,UnicodeError,RecursionError,OverflowError):
        raise ReassessmentError('INVALID_RAW_JSON') from None


def sec_submission_filing_rows(raw: bytes, *, expected_sha256: str,
        expected_cik: str, issuer_id: str, accessions: list[str],
        observed_at: str, collected_at: str, cutoff: str) -> list[dict]:
    """Adapt explicit existing SEC discoveries to FILING metadata observations.

    Not a downloader, complete SEC-history reader, XBRL normalizer, or issuer
    authenticator. No actual earnings, company guidance, surprise or ER is
    inferred from 8-K Item 2.02. The caller supplies the already verified issuer
    mapping and accession selection; missing historical pages fail explicitly.
    Strategy availability is at least collection. Acceptance is retained as a
    separate clock, never equated to original market-publication time.
    """
    need(type(expected_cik) is str and re.fullmatch(r'[0-9]{10}',expected_cik) is not None
         and int(expected_cik)>0,'EXPECTED_CIK')
    ident(issuer_id)
    observed,collected,decision=stamp(observed_at),stamp(collected_at),stamp(cutoff)
    need(observed <= collected <= decision,'COLLECTION_CLOCK')
    selected=clean(accessions)
    need(type(selected) is list and 0<len(selected)<=1000,'ACCESSION_SELECTION')
    need(all(type(a) is str and _ACCESSION.fullmatch(a) is not None for a in selected)
         and len(set(selected))==len(selected),'ACCESSION_SELECTION')
    obj=_strict_raw_object(raw,expected_sha256)
    cik=obj.get('cik')
    need((type(cik) is int and 0<cik<10**10) or
         (type(cik) is str and re.fullmatch(r'[0-9]{1,10}',cik) is not None and int(cik)>0),
         'SOURCE_CIK')
    need(str(cik).zfill(10)==expected_cik,'CIK_MISMATCH')
    filings=obj.get('filings');need(type(filings) is dict,'SUBMISSIONS_FILINGS')
    recent=filings.get('recent');need(type(recent) is dict,'SUBMISSIONS_RECENT')
    required=('accessionNumber','form','filingDate','reportDate','acceptanceDateTime','primaryDocument')
    need(all(type(recent.get(k)) is list for k in required),'SUBMISSIONS_COLUMNS')
    n=len(recent['accessionNumber']);need(n<=MAX_ROWS,'SUBMISSIONS_ROW_BUDGET')
    need(all(len(recent[k])==n for k in required),'SUBMISSIONS_COLUMN_LENGTH')
    items=recent.get('items')
    need(items is None or (type(items) is list and len(items)==n),'SUBMISSIONS_ITEMS_LENGTH')
    positions={}
    for i,a in enumerate(recent['accessionNumber']):
        need(type(a) is str and _ACCESSION.fullmatch(a) is not None,'SOURCE_ACCESSION')
        need(a not in positions,'DUPLICATE_SOURCE_ACCESSION');positions[a]=i
    need(set(selected)<=set(positions),'ACCESSION_NOT_IN_RECENT_USE_EXISTING_HISTORY_RESOLVER')
    out=[]
    for a in sorted(selected):
        i=positions[a];form=recent['form'][i]
        need(type(form) is str and form in _SEC_FORMS,'UNSUPPORTED_SEC_FORM')
        filed=day(recent['filingDate'][i]);period=recent['reportDate'][i]
        need(period is None or type(period) is str,'REPORT_DATE')
        period=day(period) if period else None
        need(date.fromisoformat(filed)<=collected.date(),'FUTURE_FILING_DATE')
        need(period is None or date.fromisoformat(period)<=collected.date(),'FUTURE_REPORT_DATE')
        accepted=stamp(recent['acceptanceDateTime'][i])
        need(accepted<=collected,'FUTURE_ACCEPTANCE')
        document=recent['primaryDocument'][i]
        need(type(document) is str and 0<len(document)<=200 and
             re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*',document) is not None,
             'PRIMARY_DOCUMENT_ID')
        item_text='' if items is None else items[i]
        need(type(item_text) is str and len(item_text)<=500,'FILING_ITEMS')
        row=dict(family='FILING',provider='sec_submissions',entity_kind='ISSUER',
            entity_id=issuer_id,metric='SEC_FILING_METADATA',fiscal_period=period,
            observation_period=accepted.date().isoformat(),
            identity={'cik':expected_cik,'accession_number':a,'form':form,
                      'evidence_kind':'FILING_METADATA_NOT_ACTUALS'},
            values={'filing_date':filed,'accepted_at':accepted.isoformat(),
                    'provider_published_at':None,'source_observed_at':observed.isoformat(),
                    'first_seen_at':None,'primary_document':document,
                    'items':item_text,'actual_financial_values':None,
                    'guidance_values':None,'company_fundamentals_verified':False},
            status='OBSERVED',available_at=collected.isoformat(),collected_at=collected.isoformat(),
            revision_id='filing-metadata-v1',source_sha256=expected_sha256,
            causal_event_id='SEC:'+expected_cik+':'+a)
        validate_row(row,cutoff);out.append(row)
    return out


def free_first_review_plan(previous: dict | None, current: dict, index: dict, *,
        now: str, contract_identity: dict, previous_profile_id: str | None=None,
        previous_contract_identity: dict | None=None,
        previous_index_sha256: str | None=None, due_events: list[dict] | None=None) -> dict:
    """Use the existing planner without a Calendar dependency or new authority.

    This explicit FREE_FIRST_PROFILE has no consensus input. It never downgrades
    a model that requires consensus: such models remain blocked by their native
    contracts. A change from a prior different/unknown profile requires an
    explicit new comparison baseline, not deletion of the unavailable inputs.
    Present input means supplied observation only; no producer authentication,
    licensed rights, current universe coverage, A3 or economic admission follows.
    """
    if previous is not None:
        need(previous_profile_id==FREE_FIRST_PROFILE,'PROFILE_CHANGED_REBASELINE_REQUIRED')
    else:
        need(previous_profile_id in (None,FREE_FIRST_PROFILE),'PROFILE_WITHOUT_PREVIOUS')
    for snap in (previous,current):
        if snap is None:continue
        verify(snap,'review-observation-snapshot-v1')
        for r in snap['rows']:
            need(r.get('family')!='CONSENSUS' and
                 str(r.get('provider','')).lower()!='eodhd_calendar',
                 'CALENDAR_OR_CONSENSUS_NOT_SELECTED_NO_SILENT_DROP')
    # Reuse generic delta/repair/clock/role batching exactly; no new dispatcher.
    plan=plan_reassessment(previous,current,index,now=now,contract_identity=contract_identity,
        previous_contract_identity=previous_contract_identity,
        previous_index_sha256=previous_index_sha256,due_events=due_events)
    present={c['asset_id']:set() for c in index['candidates']}
    family_counts={};unusable_counts={}
    fresh=stamp(now)<stamp(current['expires_at'])
    for r in current['rows']:
        family=r['family']
        if not fresh or r['status']!='OBSERVED':
            unusable_counts[family]=unusable_counts.get(family,0)+1;continue
        family_counts[family]=family_counts.get(family,0)+1
        for asset in _targets(r,index):present[asset].add(family)
    assets=[]
    for asset,seen in sorted(present.items()):
        caps={}
        for name,required in _CORE_CAPABILITIES.items():
            missing=sorted(required-seen)
            caps[name]={'status':'INPUTS_PRESENT_REVIEW_ONLY' if not missing else 'INPUT_GAP',
                        'missing_families':missing,'economic_admission':False}
        assets.append({'asset_id':asset,'observed_families':sorted(seen),'capabilities':caps})
    return seal({'schema':'free-first-reassessment-bundle-v1','profile_id':FREE_FIRST_PROFILE,
        'as_of':now,'review_plan':plan,'a0_parameter_proposals':a0_parameter_proposals(plan),
        'per_asset':assets,'observed_family_row_counts':family_counts,
        'unusable_family_row_counts':unusable_counts,
        'calendar_status':'NOT_SELECTED_UNPURCHASED','consensus_estimate':None,
        'consensus_revision':None,'consensus_surprise':None,
        'provider_http_requests':0,'secret_reads':0,'model_requirements_unchanged':True,
        'profile_is_model_approval':False,'full_universe_complete':False,
        **CLOSED})
