"""Thin test-only SPY/QQQ wrapper over the existing price collector.

Returned DataFrame snapshots are not raw HTTP originals or qualified Source
inputs. This component grants no supplier, historical-PIT or learning rights.
"""
from __future__ import annotations
from datetime import timedelta
import math
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import pandas as pd
from tools import a4_primary_sources as primary,build_replay_price_cache as collector
from tools import market_analysis_engine as market
from tools.macro_history_sources import digest,encoded
TARGETS=('SPY','QQQ')
PURPOSE='PRIVATE_CURRENT_VINTAGE_FLOW_ASSOCIATION'
MAX_VIEW_BYTES=4*1024**2
MAX_TRANSPORT_COMMANDS=128
MAX_TRANSPORT_BYTES=32*1024**2
MAX_TRANSPORT_SECONDS=600

def _file_pins():
    return {p.name:digest(p.read_bytes().replace(b'\r\n',b'\n') if p.name=='build_replay_price_cache.py' else p.read_bytes())
            for p in (Path(__file__),Path(collector.__file__),Path(market.__file__),Path(primary.__file__))}

LOADED_PRODUCER_PINS=_file_pins()

def producer_pins():
    pins=_file_pins()
    need(pins==LOADED_PRODUCER_PINS,'LOADED_PRODUCER_CHANGED')
    return pins

def need(ok,why):
    if not ok:raise ValueError('A4_FLOW_PRICE_'+why)

def validate_policy(raw,expected_sha256,cutoff):
    need(type(raw) is bytes and 0<len(raw)<=65536 and digest(raw)==expected_sha256,'EXTERNAL_POLICY_PIN')
    policy=primary.f.strict_json(raw);now=primary.clock(cutoff)
    need(policy.get('schema')=='a4-flow-test-policy-v1' and policy.get('purpose')==PURPOSE,'POLICY_PURPOSE')
    start,end=primary.clock(policy['available_at']),primary.clock(policy['expires_at'])
    need(start<=now<end and end-start<=timedelta(days=31),'POLICY_CLOCK')
    need(policy.get('targets')==list(TARGETS) and policy.get('price_start')=='2016-01-01'
         and type(policy.get('maximum_batch_calls_per_attempt')) is int and policy['maximum_batch_calls_per_attempt']==1
         and type(policy.get('maximum_attempts_per_session')) is int and policy['maximum_attempts_per_session']==1,'BOUNDED_PROFILE')
    need(policy.get('price_column')=='Close' and policy.get('currency_expectation')=='USD'
         and policy.get('source_quality')=='UNQUALIFIED_DATAFRAME_SNAPSHOT'
         and policy.get('supplier_training_permission_granted') is False,'PRICE_PURPOSE')
    expected=producer_pins()
    need(policy.get('producer_sha256')==expected,'PRODUCER_IMPLEMENTATION')
    need(policy.get('model_fits_allowed')==0 and policy.get('portfolio_changes_allowed') is False,'NO_FIT_OR_PORTFOLIO')
    return policy

def price_series(view,*,policy_sha256,cutoff,expected_session=None):
    need(type(view) is dict and view.get('schema')=='a4-flow-test-price-view-v1'
         and view.get('policy_sha256')==policy_sha256 and view.get('purpose')==PURPOSE,'VIEW_SCOPE')
    need(primary.clock(view['available_at'])<=primary.clock(cutoff),'FUTURE_VIEW')
    need(view.get('basis')=='VENDOR_CLOSE_CURRENT_VINTAGE_UNQUALIFIED'
         and view.get('raw_http_originals_available') is False and view.get('provider_currency_verified') is False,'VIEW_EVIDENCE')
    need(view.get('producer_sha256')==producer_pins(),'VIEW_PRODUCER')
    if expected_session is not None:need(view.get('target_session')==expected_session,'SESSION_NOT_CURRENT')
    series={}
    need(type(view.get('targets')) is dict and set(view['targets'])==set(TARGETS),'BOTH_TARGETS')
    for target,rows in view['targets'].items():
        need(type(rows) is list and 2<=len(rows)<=10000,'ROW_BUDGET')
        dates=[];values=[]
        for row in rows:
            need(type(row) is list and len(row)==2,'ROW_FORMAT');day=primary.day(row[0]);value=row[1]
            need(value is None or (type(value) in (int,float) and math.isfinite(value) and 0<value<=1e12),'VALUE')
            need(day<=primary.day(view['target_session']),'FUTURE_PRICE');dates.append(pd.Timestamp(day));values.append(value)
        index=pd.DatetimeIndex(dates)
        need(index.is_unique and index.is_monotonic_increasing,'DATE_GRID')
        series[target]=pd.Series(values,index=index,dtype=float)
        endpoint=pd.Timestamp(primary.day(view['target_session']))
        need(endpoint in index and pd.notna(series[target].loc[endpoint]),'EXACT_SESSION_CLOSE')
    grid=series['SPY'].index.union(series['QQQ'].index).sort_values()
    return {target:values.reindex(grid) for target,values in series.items()}

def collect(policy_raw,expected_policy_sha256,*,cutoff,download=None):
    """Exactly one existing collector batch. Caller owns one-shot session scope.

    This intentionally returns an unqualified research view. Missing raw HTTP,
    currency, CA/identity or supplier training evidence is never manufactured.
    """
    policy=validate_policy(policy_raw,expected_policy_sha256,cutoff)
    target_session=market.current_session(cutoff)
    begin=primary.now();download=download or collector.download_yfinance
    frames,audit=download(list(TARGETS),policy['price_start'],(primary.day(target_session)+timedelta(days=1)).isoformat())
    completed=primary.now();validate_policy(policy_raw,expected_policy_sha256,completed)
    need(type(frames) is dict and set(frames)==set(TARGETS),'RETURNED_TARGETS')
    snapshots={};closes={}
    for target,frame in frames.items():
        need(isinstance(frame,pd.DataFrame) and 'Close' in frame and 2<=len(frame)<=10000,'FRAME')
        index=pd.DatetimeIndex(frame.index)
        need(index.tz is None and index.is_unique and index.is_monotonic_increasing and index.equals(index.normalize()),'INDEX')
        frame=frame.loc[(index>=pd.Timestamp(policy['price_start']))&(index<=pd.Timestamp(target_session))].copy()
        need(not frame.empty and collector.has_valid_exact_close(frame,pd.Timestamp(target_session)),'LATEST_SESSION_CLOSE')
        need(set(frame.columns)<=set(('Open','High','Low','Close','Adj Close','Volume')),'FRAME_COLUMNS')
        data=frame.to_numpy(float);need(not pd.DataFrame(data).isin([float('inf'),-float('inf')]).any().any(),'FRAME_FINITE')
        snapshots[target]=dict(columns=list(frame.columns),dates=[d.date().isoformat() for d in frame.index],
            values=[[float(x) if math.isfinite(x) else None for x in row] for row in data])
        closes[target]=[[d.date().isoformat(),None if pd.isna(v) else float(v)] for d,v in frame['Close'].items()]
    snapshot=dict(schema='a4-collector-dataframe-snapshot-v1',purpose=PURPOSE,collection_started_at=begin,
        collection_completed_at=completed,provider='EXISTING_YFINANCE_COLLECTOR',frames=snapshots,
        raw_http_originals_available=False,source_admitted=False,training_admitted=False)
    snapshot_raw=encoded(snapshot);need(len(snapshot_raw)<=MAX_VIEW_BYTES,'SNAPSHOT_SIZE')
    view=dict(schema='a4-flow-test-price-view-v1',purpose=PURPOSE,policy_sha256=expected_policy_sha256,
        available_at=completed,target_session=target_session,targets=closes,snapshot_sha256=digest(snapshot_raw),producer_sha256=producer_pins(),
        basis='VENDOR_CLOSE_CURRENT_VINTAGE_UNQUALIFIED',currency_owner_expectation='USD',provider_currency_verified=False,
        raw_http_originals_available=False,source_admitted=False,training_admitted=False,historical_pit_certified=False,
        model_fits=0,portfolio_changed=False,collector_batch_calls=1,collector_python_retries=0,backend_HTTP_count='UNKNOWN')
    need(len(encoded(view))<=MAX_VIEW_BYTES,'VIEW_SIZE');price_series(view,policy_sha256=expected_policy_sha256,cutoff=completed)
    return snapshot,view



def verify_snapshot(view,raw):
    need(type(raw) is bytes and 0<len(raw)<=MAX_VIEW_BYTES and digest(raw)==view['snapshot_sha256'],'SNAPSHOT_PIN')
    snapshot=primary.f.strict_json(raw)
    need(snapshot.get('schema')=='a4-collector-dataframe-snapshot-v1' and snapshot.get('purpose')==PURPOSE
         and snapshot.get('raw_http_originals_available') is False
         and snapshot.get('collection_completed_at')==view['available_at'],'SNAPSHOT_EVIDENCE')
    need(type(snapshot.get('frames')) is dict and set(snapshot['frames'])==set(TARGETS),'SNAPSHOT_TARGETS')
    for target,frame in snapshot['frames'].items():
        columns=frame['columns'];dates=frame['dates'];values=frame['values']
        need(type(columns) is list and len(columns)<=6 and len(set(columns))==len(columns) and 'Close' in columns,'SNAPSHOT_COLUMNS')
        need(type(dates) is list and type(values) is list and 2<=len(dates)<=10000 and len(dates)==len(values),'SNAPSHOT_ROWS')
        need(all(type(row) is list and len(row)==len(columns) for row in values),'SNAPSHOT_ROW_WIDTH')
        close=columns.index('Close')
        need([[day,row[close]] for day,row in zip(dates,values)]==view['targets'][target],'NORMALIZATION_REPLAY')
    return snapshot


def stage(policy_raw,expected_policy_sha256,*,cutoff,output_root,transport=None,previous=None,download=None):
    """Single-writer session claim precedes one batch; same-session reuse is read-only.

    A content-addressed immutable claim in the existing reports directory is
    consumed before collection. Failure never refunds or silently retries it.
    A previous verified view is only a cache; it cannot grant admission.
    """
    from tools.macro_history_sources import exclusive
    policy=validate_policy(policy_raw,expected_policy_sha256,cutoff)
    root=Path(output_root);need(not root.exists() and not any(p.is_symlink() for p in (root,*root.parents)),'ATTEMPT_EXISTS_OR_SYMLINK')
    root.mkdir(parents=True);session=market.current_session(cutoff)
    try:
        if previous is not None:
            old_policy=previous.get('policy_sha256')
            price_series(previous,policy_sha256=old_policy,cutoff=cutoff)
            if previous.get('target_session')==session:
                exclusive(root/'price-view.json',encoded(previous));exclusive(root/'execution.json',encoded(dict(
                    schema='a4-flow-test-price-execution-v1',status='REUSED_SAME_COMPLETED_SESSION',
                    target_session=session,view_sha256=digest(encoded(previous)),policy_sha256=expected_policy_sha256,
                    provider_batch_calls=0,backend_HTTP_count='UNKNOWN',source_admitted=False,training_admitted=False)))
                return previous
        claim=dict(schema='a4-flow-price-session-claim-v1',purpose=PURPOSE,targets=list(TARGETS),target_session=session)
        claim_raw=encoded(claim);claim_pin=digest(claim_raw);claim_path=primary.PREFIX+'/reports/'+claim_pin+'.json'
        if transport is not None:
            names=transport.names(primary.PREFIX+'/reports')
            need(claim_pin+'.json' not in names,'SESSION_ALREADY_CONSUMED_OWNER_RECOVERY_REQUIRED')
            validate_policy(policy_raw,expected_policy_sha256,primary.now());transport.write(claim_path,claim_raw)
        exclusive(root/'session-consumed.json',claim_raw)
        snapshot,view=collect(policy_raw,expected_policy_sha256,cutoff=cutoff,download=download)
        snapshot_raw,view_raw=encoded(snapshot),encoded(view)
        exclusive(root/'dataframe-snapshot.json',snapshot_raw);exclusive(root/'price-view.json',view_raw)
        if transport is not None:
            for raw in (snapshot_raw,view_raw):
                validate_policy(policy_raw,expected_policy_sha256,primary.now());transport.write(primary.PREFIX+'/objects/'+digest(raw),raw)
        receipt=dict(schema='a4-flow-test-price-execution-v1',status='DURABLE_UNQUALIFIED_PRICE_VIEW' if transport is not None and transport.remote_verified else 'LOCAL_UNQUALIFIED_PRICE_VIEW',
            target_session=session,policy_sha256=expected_policy_sha256,claim_sha256=claim_pin,
            snapshot_sha256=digest(snapshot_raw),view_sha256=digest(view_raw),provider_batch_calls=1,
            backend_HTTP_count='UNKNOWN',raw_http_originals_available=False,provider_currency_verified=False,
            source_admitted=False,training_admitted=False,model_fits=0,accepted_portfolio_changed=False)
        raw=encoded(receipt);exclusive(root/'execution.json',raw)
        if transport is not None:
            validate_policy(policy_raw,expected_policy_sha256,primary.now());transport.write(primary.PREFIX+'/reports/'+digest(raw)+'.json',raw)
            validate_policy(policy_raw,expected_policy_sha256,primary.now())
        return view
    except Exception as exc:
        failure_raw=encoded(dict(schema='a4-flow-test-price-failure-v1',status='BLOCKED',
            target_session=session,reason=str(exc) if isinstance(exc,ValueError) and str(exc).startswith('A4_FLOW_PRICE_') else 'PRICE_COLLECTION_OR_READBACK_FAILED',
            policy_sha256=expected_policy_sha256,completed_at=primary.now(),
            source_admitted=False,training_admitted=False,model_fits=0,accepted_portfolio_changed=False))
        exclusive(root/'failure.json',failure_raw)
        if transport is not None:
            try:
                validate_policy(policy_raw,expected_policy_sha256,primary.now())
                transport.write(primary.PREFIX+'/reports/'+digest(failure_raw)+'.json',failure_raw)
            except (ValueError,OSError):
                # Keep the consumed claim and local witness; never retry a batch.
                exclusive(root/'failure-publication-blocked.json',encoded(dict(status='BLOCKED',
                    reason='FAILURE_RECEIPT_NOT_DURABLE',failure_sha256=digest(failure_raw))))
        raise


def previous_view(transport,cutoff):
    """Reuse only the newest completed data-center catalog, without older fallback."""
    names=transport.names(primary.PREFIX+'/index-executions')
    need(0<len(names)<=64,'INDEX_DISCOVERY_BOUND')
    receipts=[]
    for name in names:
        need(len(name)==69 and name.endswith('.json'),'INDEX_NAME')
        raw=primary.read_object(transport,primary.PREFIX+'/index-executions/'+name,name[:-5],128*1024)
        receipt=primary.f.strict_json(raw)
        need(receipt.get('schema')=='a4-data-center-execution-v1','INDEX_SCHEMA')
        if primary.clock(receipt['completed_at'])<=primary.clock(cutoff):receipts.append(receipt)
    need(receipts,'NO_VISIBLE_INDEX')
    newest=max(receipts,key=lambda r:primary.clock(r['completed_at']))
    need(newest.get('status')=='DURABLE_RESEARCH_INDEX_COMPLETE','LATEST_INDEX_NOT_DURABLE')
    pin=newest['catalog_sha256'];catalog=primary.f.strict_json(primary.read_object(transport,primary.PREFIX+'/catalogs/'+pin+'.json',pin,4*1024**2))
    context=catalog.get('flow_relationships',{})
    if context.get('status') in (None,'NOT_CONFIGURED'):return None
    need(context.get('status')=='CURRENT_VINTAGE_DESCRIPTIVE_ONLY','LATEST_FLOW_CONTEXT_BLOCKED')
    pin=context['price_view_sha256'];view=primary.f.strict_json(primary.read_object(transport,primary.PREFIX+'/objects/'+pin,pin,MAX_VIEW_BYTES))
    price_series(view,policy_sha256=view['policy_sha256'],cutoff=cutoff)
    return view


def bounded_transport(remote,policy_raw,expected_policy_sha256):
    """Existing scoped transport with cumulative test-only caps, including discovery.

    The hosted caller also enforces an outer 12-minute process timeout. Existing
    per-command timeout/retry semantics remain; a soft budget cannot extend them.
    """
    import time
    from tools.macro_research_checkpoint import RcloneTransport
    class Bounded(RcloneTransport):
        def __init__(self):
            self.commands=0;self.read_bytes=0;self.upload_bytes=0
            self.deadline=time.monotonic()+MAX_TRANSPORT_SECONDS
            super().__init__(remote)
        def call(self,*args):
            validate_policy(policy_raw,expected_policy_sha256,primary.now())
            need(time.monotonic()<self.deadline and self.commands<MAX_TRANSPORT_COMMANDS,'TRANSPORT_BUDGET')
            size=Path(args[1]).stat().st_size if args[0]=='copyto' else 0
            need(self.read_bytes+self.upload_bytes+size<=MAX_TRANSPORT_BYTES,'TRANSPORT_BYTE_BUDGET')
            self.commands+=1;self.upload_bytes+=size
            raw=super().call(*args);self.read_bytes+=len(raw)
            need(self.read_bytes+self.upload_bytes<=MAX_TRANSPORT_BYTES,'TRANSPORT_BYTE_BUDGET')
            need(time.monotonic()<self.deadline,'TRANSPORT_DEADLINE')
            validate_policy(policy_raw,expected_policy_sha256,primary.now())
            return raw
    return Bounded()


def main():
    import argparse,os
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--policy-root',required=True);parser.add_argument('--policy-sha256',required=True)
    parser.add_argument('--output-dir',required=True);parser.add_argument('--execute',action='store_true')
    parser.add_argument('--publish',action='store_true');args=parser.parse_args()
    policy=Path(args.policy_root)/'flow-research-policy.json'
    need(policy.is_file() and not any(p.is_symlink() for p in (policy,*policy.parents)),'POLICY_PATH')
    raw=market.bounded(policy,65536);cutoff=primary.now();validate_policy(raw,args.policy_sha256,cutoff)
    if not args.execute:
        print('{"status":"PREPARED_NO_PROVIDER_CALLS"}');return 0
    remote=bounded_transport(os.environ['MACRO_RESEARCH_REMOTE'],raw,args.policy_sha256) if args.publish else None
    old=previous_view(remote,cutoff) if remote is not None else None
    view=stage(raw,args.policy_sha256,cutoff=cutoff,output_root=args.output_dir,transport=remote,previous=old)
    print(encoded(dict(status='TEST_PRICE_VIEW_AVAILABLE',source_admitted=False,training_admitted=False,
        transport_commands=remote.commands if remote is not None else 0,
        transport_read_bytes=remote.read_bytes if remote is not None else 0,
        transport_upload_bytes=remote.upload_bytes if remote is not None else 0)).decode().strip())
    return 0

if __name__=='__main__':
    import sys
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
    raise SystemExit(main())
