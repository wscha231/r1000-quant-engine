"""Persistent retry queue and legacy trade audit for the subscription model.

This module does not fetch, schedule, select securities, publish or send orders.
Queue completion requires matching locally produced and remotely restored bytes.
A transport receipt is still external provenance, not authenticated by this code.
"""
from __future__ import annotations
import argparse
from collections import Counter
from contextlib import closing
import csv
from datetime import datetime, timedelta
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import secrets
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from tools.subscription_manager.continuous import encode, hashed, ident, money, safe_path, sha, stamp


def plus(value: str, seconds: int) -> str:
    return (datetime.fromisoformat(stamp(value)) + timedelta(seconds=seconds)).isoformat()


class UpdateQueue:
    def __init__(self, path: str | Path):
        self.path = Path(path); safe_path(self.path); self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY, source TEXT NOT NULL, entity TEXT NOT NULL, version TEXT NOT NULL, status TEXT NOT NULL, attempts INTEGER NOT NULL, due_at TEXT NOT NULL, token TEXT, lease_until TEXT, artifact_sha TEXT, receipt_sha TEXT, last_error TEXT)')

    def enqueue(self, source: str, entity: str, version: str, due_at: str) -> str:
        source, entity, version = ident(source), ident(entity), ident(version)
        key = hashed([source, entity, version]); due = stamp(due_at)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('INSERT OR IGNORE INTO tasks VALUES(?,?,?,?,?,?,?,?,?,?,?,?)', (key,source,entity,version,'PENDING',0,due,None,None,None,None,None))
        return key

    def claim(self, now: str, lease_seconds: int = 300) -> dict | None:
        at = stamp(now)
        if type(lease_seconds) is not int or not 1 <= lease_seconds <= 3600: raise ValueError('lease_seconds')
        with closing(sqlite3.connect(self.path, timeout=15)) as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute("SELECT id,source,entity,version,attempts FROM tasks WHERE (status IN ('PENDING','RETRY') AND due_at<=?) OR (status='RUNNING' AND lease_until<=?) ORDER BY due_at,id LIMIT 1", (at,at)).fetchone()
            if not row: db.rollback(); return None
            token = secrets.token_hex(16); until = plus(at,lease_seconds)
            db.execute("UPDATE tasks SET status='RUNNING',attempts=attempts+1,token=?,lease_until=? WHERE id=?", (token,until,row[0])); db.commit()
        return dict(task_id=row[0],source=row[1],entity=row[2],version=row[3],attempt=row[4]+1,lease_token=token,lease_until=until)

    @staticmethod
    def _owned(db, task: dict, now: str):
        row = db.execute('SELECT status,token,lease_until,attempts FROM tasks WHERE id=?',(task['task_id'],)).fetchone()
        if not row or row[0]!='RUNNING' or row[1]!=task['lease_token'] or stamp(now)>=row[2]:
            raise ValueError('lost_or_expired_lease')
        return row

    def complete(self, task: dict, now: str, produced: bytes, restored: bytes, transport_receipt_sha256: str):
        """Call only AFTER a real durable write and readback; no fake acknowledgement."""
        sha(transport_receipt_sha256)
        if not isinstance(produced,bytes) or not isinstance(restored,bytes) or not produced or produced!=restored:
            raise ValueError('durable_readback_mismatch')
        value = hashlib.sha256(produced).hexdigest()
        with closing(sqlite3.connect(self.path,timeout=15)) as db, db:
            db.execute('BEGIN IMMEDIATE'); self._owned(db,task,now)
            db.execute("UPDATE tasks SET status='COMPLETE',artifact_sha=?,receipt_sha=?,token=NULL,lease_until=NULL,last_error=NULL WHERE id=?", (value,transport_receipt_sha256,task['task_id']))
        return value

    def fail(self, task: dict, now: str, error_code: str):
        if error_code not in ('HTTP_429','SOURCE_UNAVAILABLE','DATA_INVALID','WRITE_FAILED','READBACK_FAILED','WORKER_ERROR'):
            raise ValueError('safe_error_code_required')
        with closing(sqlite3.connect(self.path,timeout=15)) as db, db:
            db.execute('BEGIN IMMEDIATE'); row=self._owned(db,task,now)
            seconds = min(86400, 30 * 2 ** min(row[3]-1,12))
            db.execute("UPDATE tasks SET status='RETRY',due_at=?,token=NULL,lease_until=NULL,last_error=? WHERE id=?", (plus(now,seconds),error_code,task['task_id']))

    def status(self, now: str) -> dict:
        at=stamp(now)
        with closing(sqlite3.connect(self.path)) as db:
            counts=dict(db.execute('SELECT status,COUNT(*) FROM tasks GROUP BY status'))
            overdue=db.execute("SELECT COUNT(*) FROM tasks WHERE status IN ('PENDING','RETRY') AND due_at<?",(at,)).fetchone()[0]
            abandoned=db.execute("SELECT COUNT(*) FROM tasks WHERE status='RUNNING' AND lease_until<=?",(at,)).fetchone()[0]
        return {'counts':counts,'overdue':overdue,'expired_leases':abandoned,
                'checkpoint_semantics':'ONLY_COMPLETE_AFTER_MATCHED_READBACK','scheduler_active':False}


def plan_updates(queue: UpdateQueue, security_rows: list[dict], versions: dict, due_at: str) -> dict:
    """All names retained. Separate price identity from deduplicated issuer identity."""
    names=[r['ticker'] for r in security_rows]
    if len(names)!=len(set(names)) or len(names)<1000: raise ValueError('whole_universe_identity')
    tasks=set(); issuers=set(); unresolved=[]
    for row in security_rows:
        symbol=ident(row['ticker'])
        tasks.add(queue.enqueue('price',symbol,versions['price'],due_at))
        cik=row.get('cik')
        if cik:
            if not isinstance(cik,str) or len(cik)!=10 or not cik.isdigit(): raise ValueError('cik')
            issuers.add(cik)
        else:
            unresolved.append(symbol);tasks.add(queue.enqueue('identity',symbol,versions['identity'],due_at))
    for cik in sorted(issuers):
        tasks.add(queue.enqueue('filing_inventory',cik,versions['filing_inventory'],due_at))
    return {'security_count':len(names),'issuer_count':len(issuers),'queued_unique_tasks':len(tasks),
            'unresolved_identities':unresolved,'downloads_performed':0,'scope':'PLAN_NOT_DATA_REFRESH'}


def audit_legacy(path: str|Path, expected_sha256: str) -> dict:
    raw=Path(path).read_bytes();sha(expected_sha256)
    if hashlib.sha256(raw).hexdigest()!=expected_sha256: raise ValueError('legacy_hash_mismatch')
    import io
    rows=list(csv.DictReader(io.StringIO(raw.decode('utf-8-sig'))))
    records=[]; negative=positive=zero=0; same=0; all_errors=Counter(); sources=Counter()
    for n,row in enumerate(rows,1):
        # Keep original values and interpretation; never infer a missing time boundary.
        errors=['EXACT_ENTRY_EXIT_TIMES_UNVERIFIED','PUBLICATION_RECEIPT_MISSING',
                'COST_AND_CORPORATE_ACTION_BASIS_UNVERIFIED','OUTCOME_AVAILABILITY_MISSING',
                'POINT_IN_TIME_FEATURE_PROVENANCE_MISSING']
        value=None
        try:
            value=money(row['realized_return'])
            if value < -1: errors.append('IMPOSSIBLE_UNLEVERED_RETURN')
        except (ValueError,KeyError): errors.append('RETURN_MISSING_OR_INVALID')
        if value is not None:
            negative+=int(value<0);positive+=int(value>0);zero+=int(value==0)
        if row.get('entry_date')==row.get('exit_date'):
            same+=1;errors.append('SAME_LABEL_DATE_PERIOD_RETURN_REQUIRES_REPAIR')
        source=row.get('source_journal','UNKNOWN');sources[source]+=1
        all_errors.update(errors)
        records.append({'record_id':hashed([expected_sha256,n]),'source_row':n,'ticker':row.get('ticker'),
                        'reported_return':row.get('realized_return'), 'reported_holding_days':row.get('holding_days'),
                        'source_journal':source,'historical_research_only':True,'learning_admitted':False,'blockers':errors})
    observed=negative+positive+zero
    return {'source_sha256':expected_sha256,'record_count':len(rows),'reported_positive':positive,'reported_negative':negative,
            'reported_zero':zero,'reported_negative_fraction':negative/observed if observed else None,
            'same_label_date_count':same,'source_journals':dict(sources),'issue_counts':dict(all_errors),
            'admitted_learning_records':0,'actual_trade_claim_allowed':False,'performance_claim_allowed':False,
            'interpretation':'DESCRIPTIVE_REPORTED_RETURNS_NOT_WIN_RATE_OF_A_LIVE_STRATEGY',
            'records':records,'next_repairs':['RECONSTRUCT_PERIOD_START_END_AND_OPEN_POSITIONS',
                'SEPARATE_PNL_SIGN_FROM_STRATEGY_GRADE','EXPLICIT_EXIT_CAUSE_NOT_INFERRED_FROM_ABSENCE',
                'EXCLUDE_FUTURE_FEATURES_AND_UNMATURED_LABELS','RETAIN_NONTRADE_CANDIDATES_AND_COSTS']}



def audit_period_links(trades_path, trades_hash, holdings_path, holdings_hash):
    """Trace existing period labels without inventing actual execution dates."""
    import io
    trade_raw=Path(trades_path).read_bytes(); hold_raw=Path(holdings_path).read_bytes()
    if hashlib.sha256(trade_raw).hexdigest()!=sha(trades_hash) or hashlib.sha256(hold_raw).hexdigest()!=sha(holdings_hash):
        raise ValueError('period_link_hash_mismatch')
    trades=list(csv.DictReader(io.StringIO(trade_raw.decode('utf-8-sig'))))
    holds=list(csv.DictReader(io.StringIO(hold_raw.decode('utf-8-sig'))))
    keys=[(r['ticker'],r['rebalance_date']) for r in holds]
    if len(keys)!=len(set(keys)):raise ValueError('duplicate_holding_period')
    linked=[]; matched=0; lost_risk_reason=0
    for n,t in enumerate(trades,1):
        block=sorted([r for r in holds if r['ticker']==t['ticker'] and t['entry_date']<=r['rebalance_date']<=t['exit_date']],key=lambda r:r['rebalance_date'])
        compound=Decimal(1)
        for r in block:compound*=1+money(r['period_forward_return'])
        match=bool(block) and len(block)==int(t['n_periods']) and abs(compound-1-money(t['realized_return']))<Decimal('0.0000000001')
        matched+=int(match)
        risk=[r['position_risk_action'] for r in block if r.get('position_risk_action') not in ('hold','',None)]
        generic=bool(risk) and t.get('exit_reason') in ('single_period_hold','scheduled_rebalance','dropped_from_topk')
        lost_risk_reason+=int(generic)
        linked.append({'source_row':n,'ticker':t['ticker'],'reported_entry_label':t['entry_date'],
            'reported_exit_label':t['exit_date'],'matched_forward_period_product':match,
            'last_period_scheduled_end':block[-1].get('next_scheduled_rebalance_date') if block else None,
            'underlying_model_risk_actions':risk,'generic_exit_hides_risk_context':generic,
            'actual_exit_at':None,'learning_admitted':False})
    return {'holdings_rows':len(holds),'trade_rows':len(trades),'matched_period_products':matched,
        'trades_with_risk_action_hidden_by_generic_label':lost_risk_reason,'holdings_sha256':holdings_hash,
        'records':linked,'interpretation':'SCHEDULE_AND_RISK_CONTEXT_RECOVERY_NOT_EXECUTION_RECONSTRUCTION'}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--legacy',type=Path,required=True);p.add_argument('--legacy-sha256',required=True)
    p.add_argument('--coverage',type=Path,required=True);p.add_argument('--coverage-sha256',required=True)
    p.add_argument('--holdings',type=Path);p.add_argument('--holdings-sha256')
    p.add_argument('--now',required=True);p.add_argument('--price-version',required=True)
    p.add_argument('--inventory-version',required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();safe_path(a.output)
    if a.output.exists():raise ValueError('new_output_directory_required')
    raw=a.coverage.read_bytes();sha(a.coverage_sha256)
    if hashlib.sha256(raw).hexdigest()!=a.coverage_sha256:raise ValueError('coverage_hash_mismatch')
    coverage=json.loads(raw);audit=audit_legacy(a.legacy,a.legacy_sha256)
    if bool(a.holdings)!=bool(a.holdings_sha256):raise ValueError('paired_holdings_arguments')
    links=audit_period_links(a.legacy,a.legacy_sha256,a.holdings,a.holdings_sha256) if a.holdings else None
    a.output.mkdir(parents=True)
    q=UpdateQueue(a.output/'update_queue.sqlite')
    plan=plan_updates(q,coverage,{'price':a.price_version,'filing_inventory':a.inventory_version,'identity':'v1'},a.now)
    result={'schema':'subscription-loop-replay-v1','source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'coverage_sha256':a.coverage_sha256,'as_of':stamp(a.now),'update_plan':plan,'queue':q.status(a.now),
            'legacy_audit':{k:v for k,v in audit.items() if k!='records'},
            'period_link_audit':{k:v for k,v in links.items() if k!='records'} if links else None, 'orders_allowed':False,
            'auto_promotion':False,'scheduler_active':False,'commercial_release_allowed':False}
    (a.output/'cycle_summary.json').write_text(encode(result),encoding='utf-8')
    (a.output/'legacy_quarantine.json').write_text(encode(audit),encoding='utf-8')
    if links: (a.output/'period_links.json').write_text(encode(links),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
