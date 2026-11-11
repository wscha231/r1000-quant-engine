"""One bounded research index over existing originals; no new collector or authority."""
from __future__ import annotations
import argparse
from collections import defaultdict
from datetime import timedelta
import os
from pathlib import Path
import re
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools import a4_primary_sources as p,a4_primary_macro_sources as e,a4_financing_sources as f
from tools import market_analysis_engine as market,collect_a4_primary_data as collector
from tools import a4_macro_learning as learning,run_a4_research_cycle as cycle
from tools.macro_history_sources import digest,encoded,exclusive
from tools.macro_research_checkpoint import LocalTransport,RcloneTransport

SCHEMA='a4-data-center-catalog-v1'
MAX_CAPTURES=8
MAX_ROWS=150000
MAX_BYTES=64*1024**2
FEEDS=collector.FEED_ORDER+e.FEEDS+f.FEEDS
ADAPTERS={adapter.SCHEMA:adapter for adapter in (p,e,f)}
SAFETY=dict(source_admitted=False,historical_pit_certified=False,training_admitted=False,
    automatic_promotion_allowed=False,accepted_model_changed=False,accepted_portfolio_changed=False,
    ledger_mutated=False,orders_generated=False)


def pin(value):
    p.check(type(value) is str and re.fullmatch('[a-f0-9]{64}',value),'DATA_CENTER_PIN')
    return value


class OriginalReader:
    """Cache exact objects within one invocation, never bypass the paired Reader."""
    def __init__(self,transport,*,local=False,budget=None):
        self.transport=transport;self.local=local;self.cache={};self.budget=budget if budget is not None else {'bytes':0}
    def read(self,path):
        p.check(path.startswith(p.PREFIX+'/'),'DATA_CENTER_ORIGINAL_SCOPE')
        suffix=path[len(p.PREFIX)+1:]
        p.check(re.fullmatch(r'(objects/[a-f0-9]{64}|generations/[a-f0-9]{64}\.json|executions/[a-f0-9]{64}\.json)',suffix),
            'DATA_CENTER_ORIGINAL_SCOPE')
        if path not in self.cache:
            raw=self.transport.read(suffix if self.local else path)
            p.check(type(raw) is bytes and 0<len(raw)<=p.MAX_ORIGINAL,'DATA_CENTER_OBJECT_BUDGET')
            self.budget['bytes']+=len(raw);p.check(self.budget['bytes']<=MAX_BYTES,'DATA_CENTER_READ_BUDGET')
            self.cache[path]=raw
        return self.cache[path]
    def write(self,*args):raise ValueError('DATA_CENTER_ORIGINAL_READ_ONLY')


def summarise(rows,feed,cutoff):
    groups=defaultdict(list)
    for row in rows:
        key=row.get('logical_id')
        if key is None:
            key=(row['sector']+':'+row['measure'] if row['kind']=='SLOOS' else
                'term_'+str(row['original_term_years']) if row['kind']=='TREASURY_AUCTION' else feed)
        groups[key].append(row)
    result=[]
    fields=('value','unit','frequency','measurement_basis','seasonal_basis','bank_aggregation',
        'observation_date','available_at','collected_at','published_at','source_id','source_uri',
        'kind','bid_to_cover','reopening','original_term_years','measure','sector','respondents',
        'term_premium_10y_percent','fitted_yield_10y_percent','expected_short_rate_10y_percent')
    for key,series in sorted(groups.items()):
        latest=max(series,key=lambda r:r['observation_date'])
        age=(p.clock(cutoff).date()-p.day(latest['observation_date'])).days
        max_age=latest.get('max_age_days',45 if feed.startswith('auction_') else
            150 if feed.startswith('sloos_') else 7 if feed=='acm_daily' else 62)
        missing=('value' in latest and latest['value'] is None) or latest.get('native_value_status')=='MISSING'
        result.append(dict(series=key,observations=len(series),first_observation=min(r['observation_date'] for r in series),
            last_observation=latest['observation_date'],native_frequency=latest.get('frequency',
                'auction_event' if feed.startswith('auction_') else 'release_event'),
            status='MISSING_LATEST' if missing else 'STALE' if age>max_age else 'OBSERVED',
            missing_values=sum('value' in r and r['value'] is None for r in series),
            latest={k:latest[k] for k in fields if k in latest},historical_use='FORWARD_CAPTURE_ONLY'))
    return result


def learning_readiness(root,policy_sha,cutoff):
    result=dict(status='BLOCKED',blockers=['REVIEWED_LEARNING_REQUEST_POLICY_AND_ORIGINALS_REQUIRED'],
        target_prices={},missing_targets=list(learning.analysis.TARGETS),model_fit_performed=False,
        execution_route='tools/run_a4_research_cycle.py; existing restored-state and monthly challenger gates',
        financing_recipe='INDEPENDENT_FEATURE_RECIPE_REVIEW_REQUIRED')
    if root is None or policy_sha is None:return result
    try:
        payload,policy,resolve=cycle.load_learning(Path(root),policy_sha)
        p.check(type(payload) is dict and type(policy) is dict,'DATA_CENTER_LEARNING_SCHEMA')
        p.check(p.clock(payload['cutoff'])<=p.clock(cutoff),'DATA_CENTER_FUTURE_LEARNING_INPUT')
        sessions=learning.validate_inputs(payload,policy,digest(encoded(policy)),resolve)
        prices={}
        for target,records in sorted(payload['prices'].items()):
            p.check(records,'DATA_CENTER_EMPTY_PRICE_TARGET')
            learning.price_series(records,sessions,payload['cutoff'])
            prices[target]=dict(observations=len(records),first_session=min((r['session'] for r in records),default=None),
                last_session=max((r['session'] for r in records),default=None))
        p.check(prices and payload['observations'],'DATA_CENTER_EMPTY_LEARNING_INPUTS')
        missing=sorted(set(learning.analysis.TARGETS)-set(prices))
        result.update(status='PARTIAL_VALIDATED_INPUTS' if missing else 'VALIDATED_RESEARCH_INPUTS_NOT_EXECUTED',
            blockers=['DECLARED_TARGET_COVERAGE_INCOMPLETE'] if missing else [],target_prices=prices,
            missing_targets=sorted(set(learning.analysis.TARGETS)-set(prices)),
            input_sha256=digest(encoded(payload)),external_policy_sha256=policy_sha,
            input_cutoff=payload['cutoff'])
    except (ValueError,OSError,KeyError,TypeError,OverflowError,RecursionError):
        result['blockers']=['LEARNING_POLICY_ORIGINALS_CLOCK_OR_PRICE_BASIS_NOT_VERIFIED']
    return result


def lake_metadata(transport,cutoff):
    """Discover current legacy storage only. Never restore packs or claim Reader admission."""
    result=dict(status='NOT_PROBED',execution_verified=False,original_packs_verified=False,
        source_admitted=False,training_admitted=False,reader='tools/long_history_lake.py:Lake.verified_execution')
    if transport is None:return result
    try:
        from tools.long_history_lake import PREFIX,SCHEMA as lake_schema
        used=0
        def read(folder,sha,limit):
            nonlocal used
            pin(sha);raw=transport.read(PREFIX+'/'+folder+'/'+sha)
            p.check(type(raw) is bytes and 0<len(raw)<=limit and digest(raw)==sha,'DATA_CENTER_LAKE_OBJECT')
            used+=len(raw);p.check(used<=8*1024**2,'DATA_CENTER_LAKE_BUDGET')
            value=p.f.strict_json(raw);p.check(type(value) is dict,'DATA_CENTER_LAKE_SCHEMA');return value
        names=transport.names(PREFIX+'/commits')
        p.check(type(names) is list and len(names)==len(set(names)) and len(names)<=256,'DATA_CENTER_LAKE_INVENTORY')
        entries={pin(name):read('commits',name,128*1024) for name in names}
        parent=None;generation=0;last=None
        while entries:
            following=[(sha,row) for sha,row in entries.items() if row.get('parent')==parent]
            p.check(len(following)==1,'DATA_CENTER_LAKE_FORK')
            parent,last=following[0];generation+=1
            p.check(last.get('schema')=='long-history-commit-v1' and type(last.get('generation')) is int and last['generation']==generation,
                'DATA_CENTER_LAKE_CHAIN')
            del entries[parent]
        p.check(last is not None and p.clock(last['created_at'])<=p.clock(cutoff),'DATA_CENTER_LAKE_CLOCK')
        catalog=read('catalogs',last['catalog'],4*1024**2)
        p.check(catalog.get('schema')==lake_schema and catalog.get('generation')==generation
            and catalog.get('eligible_for_selector') is False and type(catalog.get('datasets')) is dict
            and len(catalog['datasets'])<=4096,'DATA_CENTER_LAKE_CATALOG')
        p.check(all(type(k) is str and re.fullmatch('[A-Za-z0-9_./:-]{1,128}',k) and type(v) is dict
            and type(v.get('status')) is str and re.fullmatch('[A-Z_]{1,40}',v['status'])
            for k,v in catalog['datasets'].items()),'DATA_CENTER_LAKE_DATASET_SCHEMA')
        executions=transport.names(PREFIX+'/executions')
        p.check(type(executions) is list and len(executions)==len(set(executions)) and len(executions)<=256,
            'DATA_CENTER_LAKE_EXECUTIONS')
        matches=[]
        for sha in executions:
            item=read('executions',sha,256*1024)
            if item.get('commit_sha256')==parent:matches.append(sha)
        result.update(status='METADATA_ONLY',commit_sha256=parent,catalog_sha256=last['catalog'],generation=generation,
            matching_execution_metadata=matches,datasets=[dict(dataset=key,status=value.get('status','UNKNOWN'),
                source_namespace=key.split('/')[0]) for key,value in sorted(catalog['datasets'].items())],
            blockers=['ORIGINAL_PACKS_AND_MATCHING_EXECUTION_READER_VERIFICATION_REQUIRED',
                'FRED_ALFRED_RIGHTS_REQUIRED_BEFORE_ANALYSIS_OR_TRAINING'],metadata_bytes=used)
    except (ValueError,OSError,KeyError,TypeError,OverflowError,RecursionError):
        result.update(status='METADATA_BLOCKED',blockers=['LATEST_LAKE_METADATA_UNAVAILABLE_INVALID_OR_OVER_BUDGET'])
    return result


def restore_reference(transport,execution_sha,root,*,cutoff):
    """Restore only immutable receipt/native references; primary bytes stay in their archive."""
    pin(execution_sha);root=Path(root)
    p.check(not root.exists() and not any(q.is_symlink() for q in (root,*root.parents)),'DATA_CENTER_REFERENCE_EXISTS_OR_SYMLINK')
    raw=p.read_object(transport,p.PREFIX+'/executions/'+execution_sha+'.json',execution_sha,128*1024)
    value=p.f.strict_json(raw);p.check(type(value) is dict and value.get('schema')=='a4-primary-collection-execution-v1',
        'DATA_CENTER_REFERENCE_SCHEMA')
    exclusive(root/'execution.json',raw)
    if p.clock(value['completed_at'])>p.clock(cutoff):return dict(root=str(root),execution_sha256=execution_sha)
    publications=value.get('analysis_publication',[])
    p.check(type(publications) is list and len(publications)<=2 and all(type(r) is dict for r in publications),
        'DATA_CENTER_REFERENCE_PUBLICATION')
    refs=[r for r in publications if r.get('kind')=='request']
    if refs:
        p.check(len(refs)==1,'DATA_CENTER_REFERENCE_REQUEST');ref=refs[0];pin(ref['sha256'])
        p.check(ref['path']==p.PREFIX+'/reports/'+ref['sha256']+'.json','DATA_CENTER_REFERENCE_SCOPE')
        raw=p.read_object(transport,ref['path'],ref['sha256'],256*1024)
        request=market.verify_request(raw,ref['sha256'],value['cutoff'],market.current_session(value['cutoff']))
        exclusive(root/'inputs/request.json',raw)
        try:
            market.verify_request(raw,ref['sha256'],cutoff,market.current_session(cutoff))
            for spec in request['inputs']:
                if spec['kind'] not in {'risk_metrics','risk_calendar','risk_context'}:continue
                body=p.read_object(transport,p.PREFIX+'/objects/'+pin(spec['sha256']),spec['sha256'],market.input_limit(spec))
                dest=root/'inputs'/market.safe_path(spec['path']);exclusive(dest,body)
        except (ValueError,OSError,KeyError,TypeError,OverflowError,RecursionError):
            exclusive(root/'native_restore_blocked.json',encoded(dict(status='BLOCKED',reason='NATIVE_ORIGINALS_NOT_CURRENT_OR_NOT_ARCHIVED')))
    return dict(root=str(root),execution_sha256=execution_sha)


def render_catalog(catalog):
    lines=['# A4 unified research data center','',f"As of: {catalog['cutoff']}",
        f"Current diagnosis: {catalog['current_diagnosis']['status']}",
        f"Historical evaluation: {catalog['historical_evaluation']['status']} (not executed)",
        f"Future view: {catalog['future_view']['status']} (no calibrated forecast)",'',
        'Originals remain in the existing archives. Source, PIT, training and portfolio admission remain separate.','',
        '| Feed | Source state | Series | Native observations | Observation range | Latest source availability |',
        '| --- | --- | ---: | ---: | --- | --- |']
    for feed,item in catalog['selected_sources'].items():
        series=item['series'];first=min((r['first_observation'] for r in series),default='UNKNOWN')
        last=max((r['last_observation'] for r in series),default='UNKNOWN')
        lines.append(f"| {feed} | {item['status']} | {len(series)} | {item.get('observations',0)} | {first} .. {last} | {item.get('collected_at','UNKNOWN')} |")
    lines+=['','Native weekly/monthly/quarterly observations are not multiplied into independent daily samples.',
        'Current revised histories do not certify what was known at an earlier investment decision.','',
        'Legacy Lake: '+catalog['legacy_lake']['status']+'; original packs/execution require their existing Reader.',
        'Price/financial route: '+catalog['price_and_financial_route']['status'],
        'Missing learning targets: '+', '.join(catalog['learning']['missing_targets']),
        'Learning blockers: '+', '.join(catalog['learning']['blockers']),
        'Rights-blocked sources: '+', '.join(catalog['rights_blocked_sources']),'']
    return '\n'.join(lines)


def build(captures,*,cutoff,output_dir,transport=None,source_transport=None,probe_lake=False,learning_root=None,learning_policy_sha256=None):
    """Produce a hash-bound as-of view; old successes never hide newer failed attempts."""
    now=p.clock(cutoff);cutoff=now.isoformat()
    p.check(type(captures) is list and 0<len(captures)<=MAX_CAPTURES and
        all(type(s) is dict and set(s)=={'root','execution_sha256'} for s in captures),'DATA_CENTER_CAPTURE_BUDGET')
    root=Path(output_dir);p.check(not root.exists() and not any(q.is_symlink() for q in (root,*root.parents)),
        'DATA_CENTER_OUTPUT_EXISTS_OR_SYMLINK')
    originals=[Path(item['root']) for item in captures]
    p.check(all(not any(q.is_symlink() for q in (r,*r.parents)) for r in originals),'DATA_CENTER_SOURCE_SYMLINK')
    roots=[r.resolve(strict=True) for r in originals]
    p.check(all(not (r.is_relative_to(root.resolve()) or root.resolve().is_relative_to(r)) for r in roots),
        'DATA_CENTER_OUTPUT_OVERLAP')
    if learning_root is not None:
        lr=Path(learning_root).resolve();p.check(not(lr.is_relative_to(root.resolve()) or root.resolve().is_relative_to(lr)),
            'DATA_CENTER_LEARNING_OVERLAP')
    root.mkdir(parents=True);audit=[];attempts=[];sources=[];prepared={};seen=set();rows_used=0
    source_transport=source_transport or transport
    budget={'bytes':0};remote=OriginalReader(source_transport,budget=budget) if source_transport is not None else None
    for spec,source in zip(captures,roots):
        sha=pin(spec['execution_sha256']);p.check(sha not in seen,'DATA_CENTER_DUPLICATE_EXECUTION');seen.add(sha)
        p.check(not (source/'execution.json').is_symlink(),'DATA_CENTER_EXECUTION_SYMLINK')
        raw=market.bounded(source/'execution.json',128*1024)
        p.check(digest(raw)==sha,'DATA_CENTER_EXECUTION_HASH');execution=p.f.strict_json(raw)
        p.check(type(execution) is dict and execution.get('schema')=='a4-primary-collection-execution-v1'
            and type(execution.get('code_sha')) is str and re.fullmatch('[a-f0-9]{40}',execution['code_sha']),
            'DATA_CENTER_EXECUTION_SCHEMA')
        p.check(execution.get('status') in {'BLOCKED_SOURCE_CAPTURE','PARTIAL_RESEARCH_CAPTURE',
            'LOCAL_RESEARCH_CAPTURE_COMPLETE','DURABLE_PARTIAL_RESEARCH_CAPTURE','LOCAL_PARTIAL_RESEARCH_CAPTURE',
            'DURABLE_RESEARCH_CAPTURE_COMPLETE','LOCAL_TRANSPORT_CHECKED','BLOCKED_DURABLE_PUBLICATION'},
            'DATA_CENTER_EXECUTION_STATUS')
        completed=p.clock(execution['completed_at'])
        p.check(p.clock(execution['cutoff'])<=completed,'DATA_CENTER_EXECUTION_CLOCK')
        if completed>now:
            audit.append(dict(execution_sha256=sha,status='EXCLUDED_FUTURE_ATTEMPT'));continue
        requested=execution.get('requested_feeds')
        p.check(type(requested) is list and all(type(s) is str for s in requested) and len(requested)==len(set(requested))
            and set(collector.FEED_ORDER)<=set(requested)<=set(FEEDS),
            'DATA_CENTER_REQUESTED_FEEDS')
        failures=execution.get('failures')
        p.check(type(failures) is list and len(failures)<=32 and all(type(r) is dict and
            set(r)<={'feed','blocker','http_status'} and r.get('feed') in (*FEEDS,'archive','analysis') and
            type(r.get('blocker')) is str and re.fullmatch('[A-Z0-9_]{1,100}',r['blocker']) and
            ('http_status' not in r or type(r['http_status']) is int and 100<=r['http_status']<=599) for r in failures),
            'DATA_CENTER_FAILURE_SCHEMA')
        generations=execution['generation_sha256s']
        p.check(type(generations) is list and len(generations)==len(set(generations)) and len(generations)<=len(FEEDS),
            'DATA_CENTER_GENERATION_BUDGET')
        attempt=dict(execution_sha256=sha,cutoff=execution['cutoff'],completed_at=execution['completed_at'],producer_code_sha=execution['code_sha'],
            declared_status=execution['status'],requested_feeds=requested,failures=execution['failures'])
        refs=execution.get('analysis_publication',[])
        p.check(type(refs) is list and len(refs) in {0,2},'DATA_CENTER_ANALYSIS_REFERENCES')
        kinds=set()
        for ref in refs:
            p.check(type(ref) is dict and set(ref)=={'kind','path','sha256','bytes'} and ref['kind'] in {'request','report'}
                and ref['kind'] not in kinds,'DATA_CENTER_ANALYSIS_REFERENCES')
            pin(ref['sha256']);p.check(ref['path']==p.PREFIX+'/reports/'+ref['sha256']+'.json'
                and type(ref['bytes']) is int and 0<ref['bytes']<=market.MAX_FILE_BYTES,'DATA_CENTER_ANALYSIS_SCOPE')
            kinds.add(ref['kind'])
        attempt['analysis_request_sha256']=next((r['sha256'] for r in refs if r['kind']=='request'),None)
        attempts.append(attempt)
        reader=remote or OriginalReader(LocalTransport(source/'archive'),local=True,budget=budget)
        durable=True
        if remote is not None:
            try:p.check(p.read_object(remote,p.PREFIX+'/executions/'+sha+'.json',sha,128*1024)==raw,'DATA_CENTER_REMOTE_EXECUTION')
            except (ValueError,OSError):durable=False
        feeds_seen=set()
        for gen in generations:
            meta_raw=p.read_object(reader,p.PREFIX+'/generations/'+pin(gen)+'.json',gen,65536)
            meta=p.f.strict_json(meta_raw);p.check(type(meta) is dict,'DATA_CENTER_GENERATION_SCHEMA');feed=meta['feed']
            p.check(feed in requested and feed not in feeds_seen,'DATA_CENTER_GENERATION_FEED');feeds_seen.add(feed)
            p.check(p.clock(meta['collected_at'])<=p.clock(execution['cutoff']),'DATA_CENTER_CAPTURE_AVAILABILITY')
            pin(meta['original_sha256']);pin(meta['normalized_sha256'])
            item=dict(feed=feed,generation_sha256=gen,execution_sha256=sha,completed_at=execution['completed_at'],
                attempt_cutoff=execution['cutoff'],collected_at=meta['collected_at'],original_sha256=meta['original_sha256'],
                normalized_sha256=meta['normalized_sha256'],status='ARCHIVED_METADATA_ONLY',series=[],**SAFETY)
            prepared[(sha,gen)]=(reader,meta)
            if not durable or (source/'publication_failed.json').exists():
                item.update(status='BLOCKED',blocker='DURABLE_EXECUTION_NOT_VERIFIED')
            sources.append(item)
        failed={r['feed'] for r in execution['failures']}
        for feed in requested:
            if feed not in feeds_seen or feed in failed or execution['status'].startswith('BLOCKED'):
                sources.append(dict(feed=feed,execution_sha256=sha,attempt_cutoff=execution['cutoff'],completed_at=execution['completed_at'],status='BLOCKED',
                    blocker='LATEST_CAPTURE_OR_PUBLICATION_FAILED',series=[],**SAFETY))
    selected={}
    for item in sorted(sources,key=lambda r:(p.clock(r['attempt_cutoff']),r['execution_sha256'],r['status']=='BLOCKED')):
        old=selected.get(item['feed'])
        p.check(old is None or p.clock(old['attempt_cutoff'])!=p.clock(item['attempt_cutoff']) or old['execution_sha256']==item['execution_sha256'],
            'DATA_CENTER_AMBIGUOUS_LATEST_ATTEMPT')
        selected[item['feed']]=item
    # Verify selected originals only. Earlier vintages stay discoverable, never
    # counted again as independent samples or substituted after a latest failure.
    for feed,item in selected.items():
        if item['status']=='BLOCKED':continue
        try:
            reader,meta=prepared[(item['execution_sha256'],item['generation_sha256'])]
            adapter=ADAPTERS[meta['schema']]
            p.check(feed in adapter.FEEDS,'DATA_CENTER_ADAPTER_FEED')
            records,checked=adapter.read_generation(reader,item['generation_sha256'],cutoff=cutoff)
            rows_used+=len(records);p.check(rows_used<=MAX_ROWS,'DATA_CENTER_ROW_BUDGET')
            item.update(status='VERIFIED_BYTES_ONLY',observations=len(records),original_bytes=checked['original_bytes'],
                original_pair_remote_verified=remote is not None and source_transport.remote_verified is True,
                series=summarise(records,feed,cutoff))
        except (ValueError,OSError,KeyError,TypeError,OverflowError,RecursionError):
            item.update(status='BLOCKED',blocker='ORIGINAL_NORMALIZATION_CLOCK_OR_BUDGET_NOT_VERIFIED')
    inputs=root/'inputs';entries=[]
    for feed in FEEDS:
        item=selected.get(feed)
        if item is None or item['status']!='VERIFIED_BYTES_ONLY':continue
        reader,meta=prepared[(item['execution_sha256'],item['generation_sha256'])]
        body=p.read_object(reader,p.PREFIX+'/objects/'+meta['original_sha256'],meta['original_sha256'],p.MAX_ORIGINAL)
        name='originals/'+meta['original_sha256']
        if not (inputs/name).exists():exclusive(inputs/name,body)
        entry=dict(kind='financing_primary' if feed in f.FEEDS else 'macro_primary',feed=feed,path=name,
            sha256=meta['original_sha256'],status='COLLECTED',collected_at=meta['collected_at'],
            observation_start=meta.get('requested_start',meta['first_observation']),observation_through=meta['requested_through'])
        if feed in e.FEEDS:entry['source_request_year']=meta['request_year']
        if feed in f.FEEDS:entry['source_period']=meta['period']
        entries.append(entry)
    # Only the newest attempt may contribute a current native request, never an older fallback.
    native_state=dict(status='NO_EXECUTION_PINNED_NATIVE_REQUEST',operands=0)
    if attempts:
        newest=max(attempts,key=lambda r:p.clock(r['cutoff']))
        source=roots[next(i for i,s in enumerate(captures) if s['execution_sha256']==newest['execution_sha256'])]
        try:
            p.check(newest['analysis_request_sha256'] is not None,'DATA_CENTER_NATIVE_EXTERNAL_BINDING')
            p.check(not any(q.is_symlink() for q in (source/'inputs/request.json',source/'inputs')),'DATA_CENTER_NATIVE_SYMLINK')
            raw=market.bounded(source/'inputs/request.json',256*1024)
            request=market.verify_request(raw,newest['analysis_request_sha256'],cutoff,market.current_session(cutoff))
            for spec in request['inputs']:
                if spec['kind'] not in {'risk_metrics','risk_calendar','risk_context'}:continue
                path=source/'inputs'/market.safe_path(spec['path']);body=market.bounded(path,market.input_limit(spec))
                p.check(digest(body)==spec['sha256'] and not any(q.is_symlink() for q in (path,*path.parents)),
                    'DATA_CENTER_NATIVE_ORIGINAL')
                name='native/'+spec['sha256'];exclusive(inputs/name,body);entries.append(dict(spec,path=name))
            count=sum(s['kind'] in {'risk_metrics','risk_calendar','risk_context'} for s in entries)
            native_state=dict(status='ORIGINAL_HASHES_VERIFIED' if count else 'NO_NATIVE_OPERANDS_IN_PINNED_REQUEST',operands=count)
        except (ValueError,OSError,KeyError,TypeError,OverflowError,RecursionError):
            entries=[s for s in entries if s['kind'] not in {'risk_metrics','risk_calendar','risk_context'}]
            native_state=dict(status='BLOCKED',operands=0,blocker='NATIVE_REQUEST_BINDING_CLOCK_OR_ORIGINAL_NOT_VERIFIED')
    request=dict(schema=market.REQUEST_SCHEMA_V2,market='US',session=market.current_session(cutoff),available_at=cutoff,
        expires_at=(now+timedelta(days=1)).isoformat(),inputs=entries)
    raw=encoded(request);exclusive(inputs/'request.json',raw);exclusive(inputs/'request.sha256',digest(raw).encode('ascii'))
    core=all(selected.get(feed,{}).get('status')=='VERIFIED_BYTES_ONLY' for feed in collector.FEED_ORDER)
    report=market.load_report(inputs/'request.json',inputs,digest(raw),cutoff=cutoff) if core else market.blocked(
        'DATA_CENTER_LATEST_CORE_INPUT_FAILED_OR_MISSING',cutoff=cutoff,session=request['session'])
    learn=learning_readiness(learning_root,learning_policy_sha256,cutoff)
    shared_index=Path(__file__).resolve().parents[1]/'docs/research_data_access.json'
    legacy=lake_metadata(source_transport if probe_lake else None,cutoff)
    catalog=dict(schema=SCHEMA,cutoff=cutoff,mode='RESEARCH_ONLY',status='PARTIAL_RESEARCH',
        catalog_implementation_sha256=digest(Path(__file__).read_bytes()),access_routes_sha256=digest(shared_index.read_bytes()),
        attempts=sorted(attempts,key=lambda r:(p.clock(r['completed_at']),r['execution_sha256'])),
        sources=sorted(sources,key=lambda r:(r['feed'],r['completed_at'],r['execution_sha256'],r['status'])),
        selected_sources={key:selected[key] for key in sorted(selected)},native_frequencies_preserved=True,
        native_input_state=native_state,
        legacy_lake=legacy,price_and_financial_route=dict(status='LOCATOR_ONLY_NOT_COVERAGE',
            reader='tools/research_model_inputs.py:replay_model_inputs',source_originals_reverified_here=False),
        learning=learn,current_diagnosis=dict(status=report['status'],report_sha256=digest(encoded(report)),
            report_mode='VALIDATED_A4_REPLAY' if report.get('schema')=='market-analysis-report-v2' else 'BLOCKED_LOCAL_DIAGNOSTIC_ONLY',
            enhanced_readiness=report.get('enhanced_readiness',{}),blockers=report.get('market_assessment',{}).get('blockers',[])),
        historical_evaluation=dict(status='INPUTS_VERIFIED_EXECUTION_REQUIRED' if learn['status']=='VALIDATED_RESEARCH_INPUTS_NOT_EXECUTED'
            else 'BLOCKED',executed=False,horizons=list(learning.analysis.HORIZONS),outcomes=list(learning.OUTCOMES),
            blockers=learn['blockers'],current_revised_histories_are_historical_pit=False),
        future_view=dict(status='SCENARIO_CONTEXT_ONLY',forecasts_calibrated=False,
            horizons=report.get('horizon_outlook',[]),conditions=report.get('financing_conditions',{}).get('conditional_scenarios',{}),
            required='Externally reviewed fixed trial and original inputs; existing forecast_release gate'),
        rights_blocked_sources=['ICI_ETF_MMF','ICE_CCC_HY','FINRA_MARGIN_DEBT'],
        request_sha256=digest(raw),provider_requests_executed=0,**SAFETY)
    encoded_catalog=encoded(catalog);p.check(len(encoded_catalog)<=4*1024**2,'DATA_CENTER_CATALOG_SIZE');catalog_sha=digest(encoded_catalog)
    exclusive(root/'catalog.json',encoded_catalog);exclusive(root/'market_analysis.json',encoded(report))
    exclusive(root/'catalog.md',render_catalog(catalog).encode('utf-8'))
    exclusive(root/'market_analysis.md',market.render_report(report).encode('utf-8'))
    exclusive(root/'audit.json',encoded(dict(schema='a4-data-center-audit-v1',excluded_attempts=audit,provider_requests_executed=0)))
    publication=[]
    if transport is not None:
        try:
            if report.get('schema')=='market-analysis-report-v2':
                # Native derived operands were not primary capture generations.
                # Retain their exact bytes once by content hash for later replay.
                for spec in request['inputs']:
                    if spec['kind'] not in {'risk_metrics','risk_calendar','risk_context'}:continue
                    body=market.bounded(inputs/market.safe_path(spec['path']),market.input_limit(spec))
                    name=p.PREFIX+'/objects/'+spec['sha256'];transport.write(name,body)
                    p.check(p.read_object(transport,name,spec['sha256'],market.input_limit(spec))==body,'DATA_CENTER_NATIVE_READBACK')
                publication=collector.publish_analysis(transport,raw,encoded(report),cutoff=cutoff)
            name=p.PREFIX+'/catalogs/'+catalog_sha+'.json';transport.write(name,encoded_catalog)
            p.check(p.read_object(transport,name,catalog_sha,4*1024**2)==encoded_catalog,'DATA_CENTER_CATALOG_READBACK')
        except (ValueError,OSError,KeyError,TypeError,OverflowError,RecursionError):
            exclusive(root/'publication_failed.json',encoded(dict(stage='CATALOG_OR_REPORT',status='BLOCKED')))
            raise ValueError('DATA_CENTER_PUBLICATION_FAILED') from None
    receipt=dict(schema='a4-data-center-execution-v1',catalog_sha256=catalog_sha,cutoff=cutoff,
        selected_core_verified=core,
        status='DURABLE_RESEARCH_INDEX_COMPLETE' if transport is not None and transport.remote_verified is True else 'LOCAL_RESEARCH_INDEX_COMPLETE',
        source_executions=[r['execution_sha256'] for r in catalog['attempts']],analysis_publication=publication,
        completed_at=p.now(),provider_requests_executed=0,model_fit_performed=False,**SAFETY)
    body=encoded(receipt);exclusive(root/'execution.json',body)
    if transport is not None:
        try:
            name=p.PREFIX+'/index-executions/'+digest(body)+'.json';transport.write(name,body)
            p.check(p.read_object(transport,name,digest(body),128*1024)==body,'DATA_CENTER_EXECUTION_READBACK')
        except (ValueError,OSError,KeyError,TypeError,OverflowError,RecursionError):
            exclusive(root/'publication_failed.json',encoded(dict(stage='EXECUTION_RECEIPT',status='BLOCKED',execution_sha256=digest(body))))
            raise ValueError('DATA_CENTER_EXECUTION_READBACK_FAILED') from None
    return catalog,receipt


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture-root',action='append',default=[])
    parser.add_argument('--execution-sha256',action='append',default=[])
    parser.add_argument('--remote-execution-sha256',action='append',default=[])
    parser.add_argument('--cutoff',required=True);parser.add_argument('--output-dir',required=True)
    parser.add_argument('--publish',action='store_true');parser.add_argument('--probe-lake-metadata',action='store_true')
    parser.add_argument('--learning-input-root');parser.add_argument('--learning-policy-sha256')
    args=parser.parse_args()
    attempt_root=Path(args.output_dir)
    owned=not attempt_root.exists() and not any(q.is_symlink() for q in (attempt_root,*attempt_root.parents))
    try:
        p.check(len(args.capture_root)==len(args.execution_sha256),'DATA_CENTER_CAPTURE_BINDING')
        reader=RcloneTransport(os.environ['MACRO_RESEARCH_REMOTE']) if args.publish or args.remote_execution_sha256 else None
        specs=[dict(root=r,execution_sha256=s) for r,s in zip(args.capture_root,args.execution_sha256)]
        p.check(len(specs)+len(args.remote_execution_sha256)<=MAX_CAPTURES,'DATA_CENTER_CAPTURE_BUDGET')
        cache=Path(args.output_dir).with_name(Path(args.output_dir).name+'-references')
        for sha in args.remote_execution_sha256:specs.append(restore_reference(reader,sha,cache/pin(sha),cutoff=args.cutoff))
        catalog,receipt=build(specs,
            cutoff=args.cutoff,output_dir=args.output_dir,transport=reader if args.publish else None,source_transport=reader,
            probe_lake=args.probe_lake_metadata,
            learning_root=args.learning_input_root,learning_policy_sha256=args.learning_policy_sha256)
        print(encoded(dict(status=receipt['status'],catalog_sha256=receipt['catalog_sha256'],
            current_diagnosis=catalog['current_diagnosis']['status'],historical_evaluation=catalog['historical_evaluation']['status'],
            future_view=catalog['future_view']['status'])).decode().strip())
        return 0 if receipt['selected_core_verified'] else 2
    except (ValueError,OSError,KeyError,TypeError,OverflowError,RecursionError):
        if owned and attempt_root.is_dir() and not any(q.is_symlink() for q in (attempt_root,*attempt_root.parents)):
            if not (attempt_root/'failure.json').exists():
                exclusive(attempt_root/'failure.json',encoded(dict(schema='a4-data-center-failure-v1',
                    status='BLOCKED',blocker='DATA_CENTER_INPUT_OR_READBACK_INVALID',completed_at=p.now(),**SAFETY)))
        print('{"status":"BLOCKED","blocker":"DATA_CENTER_INPUT_OR_READBACK_INVALID"}')
        return 2


if __name__=='__main__':raise SystemExit(main())
