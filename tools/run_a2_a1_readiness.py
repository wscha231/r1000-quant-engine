"""Read existing research/price records into the existing A0 A1 input.

No collector, canonical Registry, scheduler or admission service. A refreshed
transport snapshot is not a refreshed filing, price, identity or right.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from research import a2_a1_ohlcv_handoff_v1 as handoff
from tools import run_agent_board as board

h = handoff.h
SCHEMA = 'a2-a1-readiness-lookup-v1'
REFRESH_MARKER = 'refresh_failed.json'
REFRESH_BLOCKED = b'{"schema":"a2-readiness-refresh-failed-v1","status":"BLOCKED"}\n'


def read_bytes(path, *, limit=None):
    cap=h.MAX_BYTES
    if limit is not None:
        h.need(type(limit) is int and limit>=0, 'LOOKUP_FILE_BUDGET')
        cap=min(cap,limit)
    with Path(path).open('rb') as stream:
        raw = stream.read(cap + 1)
    h.need(len(raw) <= cap, 'LOOKUP_FILE_BUDGET')
    return raw


def immutable_bytes(path, content):
    """Never truncate an existing cache inode (including a hard-linked input)."""
    try:
        with path.open('xb') as stream:
            stream.write(content)
    except FileExistsError:
        h.need(read_bytes(path) == content, 'LOOKUP_IMMUTABLE_CONFLICT')


def block_refresh(path):
    """Invalidate scratch proposals without deleting an unknown source child."""
    # Invalidation must not depend on publication safety of old proposals.
    marker=safe_output(path,names=(REFRESH_MARKER,))/REFRESH_MARKER
    try:
        with marker.open('xb') as stream:stream.write(REFRESH_BLOCKED)
    except FileExistsError:
        pass  # Unknown/colliding marker bytes are evidence, never overwritten.
    return marker


def lookup(value, memory, *, cutoff):
    """Observe actual sealed references; never translate presence to admission."""
    h._memory(memory)
    fields=('schema', 'as_of', 'subjects', 'registry_manifest_id',
        'capture_inventory_id', 'checkpoint_ids', 'ohlcv_inventory_id', 'artifacts')
    h.need(set(value) in (set(fields),set(fields)|{'chatgpt_report_id'}), 'FIELDS')
    h.need(value['schema'] == SCHEMA and h.stamp(value['as_of']) <= h.stamp(cutoff)
           <= datetime.now(timezone.utc),
           'LOOKUP_CLOCK')
    h.need(type(value['subjects']) is list and 1 <= len(value['subjects']) <= 30,
           'LOOKUP_SUBJECT_COUNT')
    def raw(aid):
        h.identifier(aid)
        h.need(aid in value['artifacts'], 'LOOKUP_REFERENCE')
        return memory.read(aid, value['artifacts'][aid]['sha256'])
    def obj(aid):
        return h.decode(raw(aid))
    by_hash = {ref['sha256']: aid for aid, ref in value['artifacts'].items()}
    def ref_object(ref):
        h.need(type(ref) is dict and set(ref) == {'path', 'sha256'}
               and re.fullmatch(r'artifacts/[0-9a-f]{64}', ref['path'])
               and ref['path'].split('/')[-1] == ref['sha256']
               and ref['sha256'] in by_hash, 'LOOKUP_STORED_REFERENCE')
        return obj(by_hash[ref['sha256']])
    records = []
    if value['registry_manifest_id'] is not None:
        store = obj(value['registry_manifest_id'])
        h.need(store.get('schema') == 'sec-research-request-store-v1'
               and type(store.get('requests')) is dict and len(store['requests']) <= 1000,
               'LOOKUP_REGISTRY_SCHEMA')
        for key, request in store['requests'].items():
            h.need(key == request['request_id'], 'LOOKUP_REQUEST_ID')
            record = ref_object(request['registry_ref'])
            h.need(record.get('schema') == 'candidate-registry-filing-request-v1'
                   and record.get('request_id') == key, 'LOOKUP_RECORD_ID')
            h.need(h.stamp(request['created_at']) <= h.stamp(value['as_of']), 'LOOKUP_RECORD_CLOCK')
            events = [ref_object(ref) for ref in record['event_refs']]
            h.need(h.digest(json.dumps(events, sort_keys=True, separators=(',', ':'),
                allow_nan=False).encode()) == request['events_sha256'],
                'LOOKUP_EVENT_SET')
            a2 = ref_object(record['a2_intake_ref'])
            a3 = [ref_object(ref) for ref in record['a3_filing_review_refs']]
            receipt = ref_object(request['source_receipt_ref'])
            ref_object(request['bridge_ref'])
            h.need([e['event_id'] for e in a2['input']['events']] == [e['event_id'] for e in events]
                   == [e['event_id'] for e in a3], 'LOOKUP_EVENT_BINDING')
            for event, review, original in zip(events, a3, request['raw_refs'], strict=True):
                h.need(event['event_id'] in receipt['event_scope']
                       and review['asset_id'] == record['asset_id']
                       and review['issuer_id'] == record['issuer_id']
                       and review['raw_sha256'] == original['sha256']
                       and review['source_receipt_sha256'] == request['source_receipt_ref']['sha256']
                       and original['sha256'] in by_hash, 'LOOKUP_SOURCE_BINDING')
                raw(by_hash[original['sha256']])
                h.need(h.stamp(event['available_at']) <= h.stamp(value['as_of']), 'LOOKUP_EVENT_CLOCK')
            levels = sorted({e['verification_level'] for e in a2['input']['events']})
            records.append(dict(record=record, tickers=sorted({e['ticker'] for e in events}),
                levels=levels, record_sha256=request['registry_ref']['sha256'],
                request_id=key, event_ids=[e['event_id'] for e in events],
                a3_declared_states=sorted({r.get('status','UNKNOWN') for r in a3})))
    holdings = {}
    if value['capture_inventory_id'] is not None:
        inventory = obj(value['capture_inventory_id'])
        h.need(type(inventory.get('rows')) is list and len(inventory['rows']) <= 10000
               and inventory.get('count') == len(inventory['rows'])
               and h.stamp(inventory['prepared_at_utc']) <= h.stamp(value['as_of']),
               'LOOKUP_CAPTURE_INVENTORY')
        for row in inventory['rows']:
            h.need(type(row) is list and len(row) >= 10 and type(row[1]) is str
                   and row[1] not in holdings, 'LOOKUP_CAPTURE_DUPLICATE')
            holdings[row[1]] = row
    h.need(type(value['checkpoint_ids']) is list and len(value['checkpoint_ids']) <= 32,
           'LOOKUP_CHECKPOINT_COUNT')
    checkpoints = []
    for aid in value['checkpoint_ids']:
        cp = obj(aid)
        h.need(cp.get('schema') == 'alpaca-private-sip-history-v1'
               and cp.get('source') == 'ALPACA_STOCK_BARS_V2_HISTORICAL_SIP'
               and cp.get('state') == 'PRIVATE_RESEARCH_ONLY'
               and cp.get('source_admission') is False and cp.get('pit_verified') is False,
               'LOOKUP_CHECKPOINT_SCHEMA')
        for field in ('completed', 'examined', 'held'):
            handoff.discovery._strings(cp[field], 'LOOKUP_CHECKPOINT_SYMBOLS', 1500)
        h.need(set(cp['completed']) <= set(cp['examined'])
               and not set(cp['held']) & set(cp['completed'])
               and handoff._day(cp['start']) < handoff._day(cp['end'])
               <= h.stamp(value['as_of']).date() + timedelta(days=1), 'LOOKUP_CHECKPOINT_STATE')
        checkpoints.append((aid, cp))
    observations, seen = [], set()
    for subject in value['subjects']:
        h._fields(subject, ('country', 'ticker', 'security_id', 'issuer_id'))
        country, ticker = subject['country'], subject['ticker']
        h.need(country in {'US', 'KR'} and type(ticker) is str and
               re.fullmatch(r'[A-Z][A-Z0-9.-]{0,13}' if country == 'US' else r'[0-9]{6}', ticker),
               'LOOKUP_SUBJECT')
        h.need((country, ticker) not in seen, 'LOOKUP_SUBJECT_DUPLICATE'); seen.add((country, ticker))
        for key in ('security_id', 'issuer_id'):
            if subject[key] is not None: h.identifier(subject[key])
        matches = [r for r in records if ticker in r['tickers'] and country == 'US']
        exact = [r for r in matches if subject['security_id'] == r['record']['asset_id']
                 and subject['issuer_id'] == r['record']['issuer_id']]
        h.need(all(all(subject[key] is None or subject[key] == r['record'][record_key]
               for key,record_key in (('security_id','asset_id'),('issuer_id','issuer_id')))
               for r in matches),
               'LOOKUP_SUBJECT_IDENTITY_CONFLICT')
        cp_rows = [dict(checkpoint_sha256=value['artifacts'][aid]['sha256'],
            declared_start=cp['start'], declared_end_exclusive=cp['end'],
            state='HELD' if ticker in cp['held'] else 'COMPLETED_CLAIM_NO_ROW_PROOF'
                if ticker in cp['completed'] else 'EXAMINED_NOT_COMPLETED',
            raw_row_coverage_verified=False)
            for aid, cp in checkpoints if country == 'US' and ticker in cp['examined']]
        # A completed ticker may have no bars. Presence never proves row coverage.
        obs = dict(**subject, registry_state='STORED_RESEARCH_REQUEST' if matches
            else 'NOT_FOUND_IN_INSPECTED_STORE' if value['registry_manifest_id'] else 'UNKNOWN',
            identity_match='EXACT_SUPPLIED_KEYS_NOT_ADMISSION' if exact else 'TICKER_ONLY_NOT_VERIFIED',
            research_requests=[dict(request_id=r['request_id'],
                registry_record_sha256=r['record_sha256'], event_ids=r['event_ids'],
                verification_levels=r['levels'], status=r['record']['status'],
                a3_declared_states=r['a3_declared_states']) for r in matches],
            canonical_registry_state='NOT_VERIFIED', checkpoint_observations=cp_rows,
            price_state='CAPTURE_INDEX_MATCH_ONLY' if country == 'US' and ticker in holdings
                else 'NOT_FOUND_IN_INSPECTED_INDEX' if value['capture_inventory_id'] else 'UNKNOWN',
            data_ready=False, collection_required='UNDETERMINED', consumer_eligible=False,
            blockers=['CURRENT_REGISTRY_ACCEPTANCE_NOT_BOUND', 'RAW_PRICE_WINDOW_REVIEW_REQUIRED'],
            authority=h.closed())
        observations.append(obs)
    if value['ohlcv_inventory_id'] is not None:
        inner = obj(value['ohlcv_inventory_id'])
        # Full Stage3 validation remains mandatory; lookup labels cannot supply
        # absent identity/source/calendar/policy or overwrite its result.
        result = handoff.build_plan(inner, memory, cutoff=cutoff)
    else:
        result = dict(schema='a0-a1-ohlcv-proposals-v1', mode='DRY_RUN', requests=[],
            coverage_results=[], discovery_other_events=[], authority=h.closed(),
            dispatch_count=0, canonical_write_performed=False)
    result['readiness_observations'] = observations
    result['lookup_as_of'] = value['as_of']
    result['event_connection'] = 'STAGE3_VALIDATOR' if value['ohlcv_inventory_id'] else 'EVENT_INPUT_MISSING'
    result['automatic_chatgpt_delivery'] = 'NOT_CONNECTED'
    if value.get('chatgpt_report_id') is not None:
        exported=obj(value['chatgpt_report_id'])
        h._fields(exported,('schema','source_url','observed_at','extraction','reports'))
        h.need(exported['schema']=='chatgpt-a2-observed-reports-v1'
               and re.fullmatch(r'https://chatgpt\.com/share/[0-9a-f-]{36}(?:\?ogimg=plain)?',exported['source_url'])
               and h.stamp(exported['observed_at'])<=h.stamp(value['as_of'])
               and exported['extraction'] in {'BROWSER_VISIBLE_EXCERPT','USER_EXPORTED_TEXT'}
               and type(exported['reports']) is list and 0<len(exported['reports'])<=100,
               'LOOKUP_CHATGPT_REFERENCE')
        seen_reports=set();quarantine=[]
        for report in exported['reports']:
            h._fields(report,('reported_at_text','source_excerpt','source_links','claimed_event_count'))
            h.need(type(report['reported_at_text']) is str and len(report['reported_at_text'])<=100
                   and type(report['source_excerpt']) is str and 0<len(report['source_excerpt'])<=50000
                   and type(report['claimed_event_count']) is int and 0<=report['claimed_event_count']<=1000
                   and type(report['source_links']) is list and len(report['source_links'])<=100,
                   'LOOKUP_CHATGPT_REPORT')
            for url in report['source_links']:handoff.discovery._url(url)
            key=h.digest(h.canonical(dict(source_url=exported['source_url'].split('?')[0],report=report)))
            if key in seen_reports:continue
            seen_reports.add(key)
            quarantine.append(dict(report_id=key,source_url=exported['source_url'],
                export_sha256=value['artifacts'][value['chatgpt_report_id']]['sha256'],
                reported_at_text=report['reported_at_text'],extraction=exported['extraction'],
                claimed_event_count=report['claimed_event_count'],status='UNADMITTED',
                source_verification='NOT_RUN',original_public_available_at=None,
                original_source_byte_hash=None,security_identity='NOT_VERIFIED',
                A3_handoff='REVALIDATION_REQUIRED_NOT_DISPATCHED',authority=h.closed()))
        result['chatgpt_report_intake']=quarantine
    return result


def snapshot(args):
    """Trusted caller acquires explicit local sources; original times preserved."""
    out = Path(args.output_dir).resolve()
    registry_root = Path(args.registry_root).resolve() if args.registry_root else None
    inputs = [Path(p).resolve() for p in [args.subjects, args.capture_inventory,
              *args.checkpoint, args.ohlcv_inventory, getattr(args,'chatgpt_report',None)] if p]
    h.need(not registry_root or (not out.is_relative_to(registry_root)
           and not registry_root.is_relative_to(out)), 'LOOKUP_OUTPUT_SCOPE')
    inner = inner_content = None
    try:
        h.need(all(not p.is_relative_to(out) for p in inputs), 'LOOKUP_OUTPUT_SCOPE')
        if args.ohlcv_inventory:
            path = Path(args.ohlcv_inventory).resolve()
            inner_content = read_bytes(path); inner = h.decode(inner_content)
            h.need(type(inner) is dict and type(inner.get('artifacts')) is dict
                   and len(inner['artifacts']) <= 128,
                   'LOOKUP_ARTIFACT_COUNT')
            # A captured inventory can reference an original inside out. Check
            # all paths before unlink; preserve these same bytes for import.
            children = [board.artifact_path(path.parent, ref['path']).resolve()
                        for ref in inner['artifacts'].values()]
            h.need(all(not p.is_relative_to(out) for p in children), 'LOOKUP_OUTPUT_SCOPE')
    except (OSError,ValueError,KeyError,TypeError):
        block_refresh(args.output_dir)
        raise
    marker=block_refresh(args.output_dir)
    out = safe_output(args.output_dir)
    h.need(read_bytes(marker)==REFRESH_BLOCKED,'LOOKUP_REFRESH_MARKER_CONFLICT')
    marker_identity=(marker.stat().st_dev,marker.stat().st_ino)
    for name in ('source_inventory.json', 'readiness_report.json', 'request_fragment.json'):
        (out/name).unlink(missing_ok=True)  # Revoke previous current proposals first.
    now = datetime.now(timezone.utc); at = now.isoformat(); expires = (now+timedelta(hours=1)).isoformat()
    values, refs = {}, {}
    def add(aid, content):
        h.need(aid not in values or values[aid] == content, 'LOOKUP_ARTIFACT_COLLISION')
        values[aid] = content
        h.need(len(values) <= 128 and sum(map(len, values.values())) <= h.MAX_TOTAL_BYTES,
               'LOOKUP_TOTAL_BUDGET')
        name = 'bytes/'+h.digest(content)
        refs[aid] = dict(path=name,sha256=h.digest(content),observed_at=at,
            available_at=at,collected_at=at,expires_at=expires,status='VERIFIED')
        return aid
    if registry_root:
        manifest = read_bytes(board.artifact_path(registry_root,
            'control_plane/candidate_registry/filing_requests.json'))
        add('REGISTRY', manifest)
        pending = [h.decode(manifest)]; visited = set()
        while pending:
            node = pending.pop()
            if type(node) is list: pending.extend(node)
            elif type(node) is dict:
                if set(node) == {'path','sha256'}:
                    h.need(re.fullmatch(r'artifacts/[0-9a-f]{64}',node['path'])
                           and node['path'].split('/')[-1] == node['sha256'], 'LOOKUP_STORED_REFERENCE')
                    if node['sha256'] in visited: continue
                    content=read_bytes(board.artifact_path(registry_root,node['path']))
                    h.need(h.digest(content)==node['sha256'], 'LOOKUP_STORED_HASH')
                    visited.add(node['sha256']);add('B'+node['sha256'],content)
                    if content.lstrip().startswith((b'{',b'[')): pending.append(h.decode(content))
                else: pending.extend(node.values())
        h.need(read_bytes(board.artifact_path(registry_root,
            'control_plane/candidate_registry/filing_requests.json')) == manifest, 'LOOKUP_STORE_CHANGED')
    if args.capture_inventory: add('CAPTURE',read_bytes(args.capture_inventory))
    cp_ids=[add('CP'+str(i),read_bytes(p)) for i,p in enumerate(args.checkpoint)]
    if args.ohlcv_inventory:
        path=Path(args.ohlcv_inventory).resolve()
        for aid,ref in inner['artifacts'].items():
            raw=read_bytes(board.artifact_path(path.parent,ref['path']))
            h.need(h.digest(raw)==ref['sha256'], 'LOOKUP_EVENT_ARTIFACT_HASH')
            # Preserve the existing event artifact clocks. Refreshing transport
            # does not extend stale/expired event or identity evidence.
            observed,available,collected,child_expires=(board.timestamp(ref[k]) for k in
                ('observed_at','available_at','collected_at','expires_at'))
            h.need(observed<=available<=collected<=now<child_expires,'LOOKUP_EVENT_ARTIFACT_CLOCK')
            add(aid,raw)
            refs[aid] = {**ref, 'path': refs[aid]['path']}
        add('OHLCV',inner_content)
    subjects = h.decode(read_bytes(args.subjects))['subjects']
    value = dict(schema=SCHEMA,as_of=at,subjects=subjects,
        registry_manifest_id='REGISTRY' if registry_root else None,
        capture_inventory_id='CAPTURE' if args.capture_inventory else None,
        checkpoint_ids=cp_ids,ohlcv_inventory_id='OHLCV' if args.ohlcv_inventory else None,artifacts=refs)
    if getattr(args,'chatgpt_report',None):
        value['chatgpt_report_id']=add('CHATGPT_REPORT',read_bytes(args.chatgpt_report))
    report=lookup(value,h.MemoryArtifacts(values),cutoff=at)
    for aid,raw in values.items():
        path=board.artifact_path(out,refs[aid]['path']);path.parent.mkdir(exist_ok=True);immutable_bytes(path,raw)
    board.write_json(out/'readiness_report.json',report)
    board.write_json(out/'source_inventory.json',value)
    inventory_ref=dict(path='source_inventory.json',sha256=board.file_hash(out/'source_inventory.json'),
        observed_at=at,available_at=at,collected_at=at,expires_at=expires,status='VERIFIED')
    board.write_json(out/'request_fragment.json',dict(agent='A1',inputs={'source_inventory':inventory_ref},
        parameters={},model={'name':'DETERMINISTIC','version':'a2-a1-readiness-v1'}))
    h.need(not marker.is_symlink() and marker.stat().st_nlink==1
           and (marker.stat().st_dev,marker.stat().st_ino)==marker_identity
           and read_bytes(marker)==REFRESH_BLOCKED,'LOOKUP_REFRESH_MARKER_CONFLICT')
    marker.unlink()  # Last publication step; only the recognized marker clears.
    return report


def safe_output(path, *, names=None):
    supplied=Path(path)
    h.need(not supplied.is_symlink(), 'LOOKUP_OUTPUT_SYMLINK')
    out=supplied.resolve();out.mkdir(parents=True,exist_ok=True)
    if names is None:names=('bytes','source_inventory.json','readiness_report.json','request_fragment.json',
                 'agent_task_queue.json','manifest.json','state.json','intake.json',
                 'board_summary.json','promotion_gate_review.json','report.md','evidence',REFRESH_MARKER)
    for name in names:
        h.need(not (out/name).is_symlink() and not (out/(name+'.tmp')).is_symlink(),
               'LOOKUP_OUTPUT_SYMLINK')
        for candidate in (out/name,out/(name+'.tmp')):
            h.need(not candidate.is_file() or candidate.stat().st_nlink==1,
                   'LOOKUP_OUTPUT_HARDLINK')
    return out


def connect(lookup_dir, canonical_inputs, evidence_root, output_dir):
    """Bind an already acquired lookup to fresh A0 sources and its public API.

    The caller refreshes GitHub/control observations AFTER snapshot acquisition.
    Missing durable research sources remain UNKNOWN; no G0 success is invented.
    """
    from tools import materialize_system_state as materializer
    out=Path(output_dir).resolve();sources=Path(evidence_root).resolve();lookup_root=Path(lookup_dir).resolve()
    h.need(not sources.is_relative_to(out) and not out.is_relative_to(sources)
           and not lookup_root.is_relative_to(out) and not out.is_relative_to(lookup_root)
           and not Path(canonical_inputs).resolve().is_relative_to(out),
           'LOOKUP_OUTPUT_SCOPE')
    out=safe_output(output_dir)
    board.write_json(out/'manifest.json',{'status':'BLOCKED','reason':'REFRESH_STARTED'})
    board.write_json(out/'agent_task_queue.json',[])
    marker=lookup_root/REFRESH_MARKER
    h.need(not marker.exists() and not marker.is_symlink(),'LOOKUP_REFRESH_BLOCKED')
    now=datetime.now(timezone.utc);manifest=board.read_json(Path(canonical_inputs))
    materializer.intake_validate(manifest,now)
    fragment=board.read_json(lookup_root/'request_fragment.json')
    # Preserve canonical relative paths, including references inside immutable
    # review bundles. A per-input namespace avoids overwriting prior snapshots.
    root=safe_output(out/'evidence'/h.digest(h.canonical([manifest,fragment])))
    total=0;count=0;staged={}
    def copy_descriptor(ref, base, depth=0, bundle=False):
        nonlocal total,count
        h.need(depth <= h.MAX_DEPTH, 'LOOKUP_BIND_DEPTH')
        h.need(count<128 and total<h.MAX_TOTAL_BYTES, 'LOOKUP_BIND_HASH_OR_BUDGET')
        count+=1
        content=read_bytes(board.artifact_path(base,ref['path']),limit=h.MAX_TOTAL_BYTES-total)
        total+=len(content)
        h.need(h.digest(content)==ref['sha256'],'LOOKUP_BIND_HASH_OR_BUDGET')
        observed,available,collected,expires=(board.timestamp(ref[k]) for k in
            ('observed_at','available_at','collected_at','expires_at'))
        h.need(observed<=available<=collected<=board.timestamp(manifest['observed_at'])<=now<expires,
               'LOOKUP_BIND_CLOCK')
        dest=board.artifact_path(root,ref['path'])
        signature={k:ref[k] for k in ('path','sha256','observed_at','available_at',
                                     'collected_at','expires_at','status')}
        key=dest.resolve()
        if key in staged:
            h.need(staged[key][1]==signature and staged[key][2]==content,
                   'LOOKUP_BIND_PATH_CONFLICT')
            return dict(ref)
        h.need(all(not key.is_relative_to(previous) and not previous.is_relative_to(key)
                   for previous in staged), 'LOOKUP_BIND_PATH_CONFLICT')
        staged[key]=(dest,signature,content)
        node=None
        if bundle or content.lstrip().startswith(b'{'):
            try:node=h.decode(content)
            except ValueError:
                if bundle:raise
        if bundle or type(node) is dict and node.get('schema_version')=='qa-review-bundle-v2':
            board.schema_validate(node,'system_state_schema.json','qa_bundle')
            for child in node['artifacts'].values():
                h.need(board.timestamp(child['collected_at'])<=collected,
                       'LOOKUP_BIND_BUNDLE_CLOCK')
                copy_descriptor(child,base,depth+1)
        return dict(ref)
    for role,refs in manifest['sources'].items():
        manifest['sources'][role]=[copy_descriptor(ref,sources) for ref in refs]
    # Preserve existing input roles/requests, but never replace another A1 job.
    existing=manifest.get('requests',[])
    h.need(not any(r.get('agent')=='A1' for r in existing),'LOOKUP_A1_REQUEST_CONFLICT')
    for request in existing:
        request['inputs']={role:copy_descriptor(ref,sources,
            bundle=request.get('agent')=='A6' and role=='review_bundle')
            for role,ref in request['inputs'].items()}
    inv_ref=fragment['inputs']['source_inventory']
    inventory=board.read_json(board.artifact_path(lookup_root,inv_ref['path']))
    for ref in inventory['artifacts'].values():
        copied=copy_descriptor(ref,lookup_root)
        # Same content-addressed relative paths under the new root.
        h.need(copied['path']==ref['path'],'LOOKUP_CHILD_PATH')
    fragment['inputs']['source_inventory']=copy_descriptor(inv_ref,lookup_root)
    manifest['requests']=[*existing,fragment]
    h.need(not marker.exists() and not marker.is_symlink(),'LOOKUP_REFRESH_BLOCKED')
    # Every bounded input/hash/clock/path conflict is checked before publishing
    # any evidence. Immutable writes never truncate a conflicting prior inode.
    for dest,_,content in staged.values():
        dest.parent.mkdir(parents=True,exist_ok=True);immutable_bytes(dest,content)
    board.write_json(out/'intake.json',manifest)
    state=materializer.materialize(manifest,root,now)
    board.write_json(out/'state.json',state)
    args=argparse.Namespace(latest_run=str(root),output_dir=str(out),run_url='',max_tasks=0,
        system_state=str(out/'state.json'),canonical_inputs=str(out/'intake.json'),evidence_root=str(root))
    return board.run(args)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--subjects')
    parser.add_argument('--registry-root')
    parser.add_argument('--capture-inventory')
    parser.add_argument('--checkpoint',action='append',default=[])
    parser.add_argument('--ohlcv-inventory')
    parser.add_argument('--chatgpt-report')
    parser.add_argument('--output-dir',required=True)
    parser.add_argument('--connect-lookup')
    parser.add_argument('--canonical-inputs')
    parser.add_argument('--evidence-root')
    try:
        args=parser.parse_args()
        if args.connect_lookup:
            report=connect(args.connect_lookup,args.canonical_inputs,args.evidence_root,args.output_dir)
            print(json.dumps({'status':report['status'],'dispatch_count':0}))
            return 2 if report['status']=='BLOCKED' else 0
        report=snapshot(args)
    except (ValueError,KeyError,TypeError,OSError):
        print(json.dumps({'status':'BLOCKED','reason':'READINESS_REFRESH_FAILED','dispatch_count':0}))
        return 2
    print(json.dumps(dict(status='OBSERVED_NOT_ADMITTED',subjects=len(report['readiness_observations']),
        event_connection=report['event_connection'],requests=len(report['requests']),dispatch_count=0)))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
