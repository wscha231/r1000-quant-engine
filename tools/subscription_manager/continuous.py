"""Internal subscription-model lifecycle and maturity-aware learning records.

No broker calls, subscriber delivery, alpha selection or automatic promotion.
External source/review/calendar receipts must be authenticated by the caller;
format validation is not that authentication. SQLite runs on one local worker,
not on a shared Drive mount. Persist a closed snapshot and verify its readback.
"""
from __future__ import annotations

from contextlib import closing
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from typing import Any

SCHEMA = 'subscription-continuous-v1'
ZERO = '0' * 64
HORIZONS = (21, 63, 126, 252)


def encode(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def hashed(value: Any) -> str:
    return hashlib.sha256(encode(value).encode()).hexdigest()


def sha(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch('[a-f0-9]{64}', value):
        raise ValueError('sha256_required')
    return value


def stamp(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError('timestamp_required')
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('timezone_required')
    return result.astimezone(timezone.utc).isoformat()


def money(value: Any, positive: bool = False) -> Decimal:
    # JSON numbers are not accepted for amounts; preserve exact decimal strings.
    if not isinstance(value, str) or not re.fullmatch(r'-?\d+(\.\d+)?', value) or len(value) > 60:
        raise ValueError('decimal_string_required')
    out = Decimal(value)
    if not out.is_finite() or (positive and out <= 0):
        raise ValueError('invalid_decimal')
    return out


def ident(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_.:\-]{1,120}', value):
        raise ValueError('invalid_identity')
    return value


def safe_path(path: Path) -> None:
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('symlink_path')


def initial() -> dict:
    return dict(opened=False, kind=None, mode=None, cash='0', positions={}, decisions={},
                deliveries={}, fills={}, accrued={}, paid=[], fees='0', realized_pnl='0',
                nav=None, last_at=None, outcomes={}, corporate_actions=[])


def apply(state: dict, event: dict) -> dict:
    """Pure validated event reducer. Errors never partly update the old state."""
    s = deepcopy(state)
    if set(event) != {'event_id', 'type', 'at', 'payload'}:
        raise ValueError('event_schema')
    ident(event['event_id']); at = stamp(event['at']); p = event['payload']; kind = event['type']
    if not isinstance(p, dict):
        raise ValueError('payload_object')
    if s['last_at'] and at < s['last_at']:
        raise ValueError('out_of_order_event')
    if not s['opened'] and kind != 'OPEN':
        raise ValueError('open_required')
    if kind == 'OPEN':
        if s['opened'] or p.get('book_kind') != 'MODEL_PAPER' or p.get('data_kind') not in ('REAL', 'SYNTHETIC'):
            raise ValueError('model_paper_only')
        s.update(opened=True, kind='MODEL_PAPER', mode=p['data_kind'], cash=str(money(p['cash'], True)))
        if p.get('currency') != 'USD':
            raise ValueError('usd_only_initial_adapter')
        sha(p['policy_sha256'])
    elif kind == 'DECISION':
        did = ident(p['decision_id']); action = p['action']; security = ident(p['security_id'])
        if did in s['decisions'] or action not in ('BUY', 'SELL', 'HOLD', 'WATCH', 'REJECT'):
            raise ValueError('decision_identity_or_action')
        if not (stamp(p['information_available_at']) <= at < stamp(p['valid_until'])):
            raise ValueError('decision_availability')
        for field in ('snapshot_sha256', 'config_sha256', 'review_sha256'):
            sha(p[field])
        for field in ('thesis_id', 'model_version'):
            ident(p[field])
        quantity = money(p['max_quantity'])
        if quantity < 0 or ((action in ('BUY', 'SELL')) != (quantity > 0)):
            raise ValueError('decision_quantity')
        if not isinstance(p.get('reason_codes'), list) or not p['reason_codes']:
            raise ValueError('decision_reasons_required')
        for reason in p['reason_codes']: ident(reason)
        if action == 'SELL' and set(p['reason_codes']) <= {'RS_SHORT_WEAK'}:
            raise ValueError('short_rs_is_not_sale_authority')
        forecasts = p.get('forecasts', {})
        if not isinstance(forecasts, dict): raise ValueError('forecast_schema')
        for horizon, forecast in forecasts.items():
            if horizon not in {str(h) for h in HORIZONS} or set(forecast) != {'expected_return', 'p_positive'}:
                raise ValueError('forecast_schema')
            if money(forecast['expected_return']) < -1 or not 0 <= money(forecast['p_positive']) <= 1:
                raise ValueError('forecast_range')
        s['decisions'][did] = {**p, 'at': at, 'decision_sha256': hashed(event), 'filled_quantity': '0', 'invalidated': False}
    elif kind == 'DELIVERY':
        did = p['decision_id']; d = s['decisions'][did]
        if did in s['deliveries'] or d['invalidated'] or not d['at'] <= at < stamp(d['valid_until']):
            raise ValueError('delivery_state')
        sha(p['delivery_receipt_sha256']); sha(p['calendar_receipt_sha256'])
        if p['decision_sha256'] != d['decision_sha256']:
            raise ValueError('delivery_decision_binding')
        if p.get('channel') not in ('INTERNAL_SHADOW', 'SUBSCRIBER_MODEL'):
            raise ValueError('delivery_channel')
        # Exact eligible window is supplied by the reviewed exchange-calendar adapter.
        opening, closing = stamp(p['execution_window_start']), stamp(p['execution_window_end'])
        if not at < opening <= closing <= stamp(d['valid_until']):
            raise ValueError('post_delivery_execution_window')
        s['deliveries'][did] = {**p, 'at': at}
    elif kind == 'CANCEL':
        d = s['decisions'][p['decision_id']]
        ident(p['reason']); sha(p['evidence_sha256']); d['invalidated'] = True
    elif kind == 'FILL':
        fid = ident(p['fill_id']); did = p['decision_id']; d = s['decisions'][did]
        receipt = s['deliveries'].get(did)
        if fid in s['fills'] or not receipt or d['invalidated'] or d['action'] not in ('BUY', 'SELL'):
            raise ValueError('fill_not_authorized')
        if not stamp(receipt['execution_window_start']) <= at <= stamp(receipt['execution_window_end']):
            raise ValueError('fill_outside_execution_window')
        if stamp(p['quote_at']) != at or p['price_basis'] != 'RAW_EXECUTABLE':
            raise ValueError('fill_quote_basis_or_time')
        sha(p['quote_sha256'])
        if p['calendar_receipt_sha256'] != receipt['calendar_receipt_sha256']:
            raise ValueError('fill_calendar_binding')
        quantity, price, fee = money(p['quantity'], True), money(p['price'], True), money(p['fee'])
        if fee < 0 or money(d['filled_quantity']) + quantity > money(d['max_quantity']):
            raise ValueError('fill_quantity_or_fee')
        sec = d['security_id']; pos = s['positions'].setdefault(sec, {'quantity': '0', 'cost': '0'})
        cash, qty, cost = money(s['cash']), money(pos['quantity']), money(pos['cost'])
        gross = quantity * price
        if d['action'] == 'BUY':
            if cash < gross + fee: raise ValueError('insufficient_cash')
            cash -= gross + fee; qty += quantity; cost += gross + fee
        else:
            if qty < quantity: raise ValueError('oversell')
            if gross < fee: raise ValueError('fee_exceeds_proceeds')
            basis = cost if qty == quantity else cost * quantity / qty
            cash += gross - fee; qty -= quantity; cost -= basis
            s['realized_pnl'] = str(money(s['realized_pnl']) + gross - fee - basis)
        pos.update(quantity=str(qty), cost=str(cost))
        s['cash'] = str(cash); s['fees'] = str(money(s['fees']) + fee)
        d['filled_quantity'] = str(money(d['filled_quantity']) + quantity)
        s['fills'][fid] = {**p, 'at': at}; s['nav'] = None
    elif kind == 'SPLIT':
        sec = ident(p['security_id']); sha(p['source_sha256']); ratio = money(p['ratio'], True)
        aid = ident(p['action_id'])
        if aid in s['corporate_actions']: raise ValueError('duplicate_corporate_action')
        s['corporate_actions'].append(aid)
        if sec in s['positions']:
            pos = s['positions'][sec]; pos['quantity'] = str(money(pos['quantity']) * ratio)
        # Do not silently reinterpret quantities/prices of pre-split instructions.
        for d in s['decisions'].values():
            if d['security_id'] == sec: d['invalidated'] = True
        s['nav'] = None
    elif kind == 'DIVIDEND_EX':
        aid = ident(p['action_id']); sec = ident(p['security_id']); sha(p['source_sha256'])
        if aid in s['accrued'] or aid in s['paid']: raise ValueError('duplicate_dividend')
        # Upstream adapter must place the event at ex-date before all ex-date fills.
        if stamp(p['ex_at']) != at or stamp(p['pay_at']) < at: raise ValueError('dividend_date')
        if any(f['at'] >= at and s['decisions'][f['decision_id']]['security_id'] == sec for f in s['fills'].values()):
            raise ValueError('ex_event_must_precede_ex_time_fills')
        per = money(p['cash_per_share'])
        if per < 0: raise ValueError('negative_dividend')
        qty = money(s['positions'].get(sec, {'quantity': '0'})['quantity'])
        s['accrued'][aid] = {'amount': str(qty * per), 'pay_at': stamp(p['pay_at'])}
        s['nav'] = None
    elif kind == 'DIVIDEND_PAY':
        aid = p['action_id']; accrued = s['accrued'][aid]; sha(p['source_sha256'])
        if at < accrued['pay_at']: raise ValueError('dividend_not_due')
        s['cash'] = str(money(s['cash']) + money(accrued['amount']))
        del s['accrued'][aid]; s['paid'].append(aid); s['nav'] = None
    elif kind == 'MARK':
        marks = p['prices']; sha(p['source_sha256'])
        held = {k for k,v in s['positions'].items() if money(v['quantity']) > 0}
        if not isinstance(marks, dict) or set(marks) != held or p.get('price_basis') != 'RAW_CLOSE' or stamp(p['quote_at']) != at:
            raise ValueError('mark_coverage_or_basis')
        value = sum((money(v['quantity']) * money(marks[k], True) for k,v in s['positions'].items() if k in held), Decimal(0))
        value += money(s['cash']) + sum((money(v['amount']) for v in s['accrued'].values()), Decimal(0))
        s['nav'] = {'at': at, 'value': str(value), 'kind': 'INTERNAL_MODEL_NOT_CUSTOMER_RETURN'}
    elif kind == 'OUTCOME':
        did = p['decision_id']; d = s['decisions'][did]; h = p['horizon_sessions']
        if type(h) is not int or h not in HORIZONS: raise ValueError('horizon_contract')
        key = did + ':' + str(h)
        if key in s['outcomes']: raise ValueError('outcome_already_recorded')
        if p.get('return_basis') != 'TOTAL_RETURN_INDEX' or p['decision_sha256'] != d['decision_sha256']:
            raise ValueError('outcome_basis_or_binding')
        for field in ('source_sha256', 'calendar_receipt_sha256'): sha(p[field])
        sessions = [stamp(v) for v in p['sessions']]
        if len(sessions) != h + 1 or sessions != sorted(set(sessions)) or d['at'] >= sessions[0] or sessions[-1] > stamp(p['available_at']) or stamp(p['available_at']) > at:
            raise ValueError('outcome_maturity_or_calendar')
        # Fixed forecast evaluation window is different from a trade exit/P&L label.
        stock = money(p['stock_end'], True) / money(p['stock_start'], True) - 1
        bench = money(p['benchmark_end'], True) / money(p['benchmark_start'], True) - 1
        s['outcomes'][key] = {'decision_id': did, 'security_id': d['security_id'], 'action': d['action'],
            'horizon_sessions': h, 'start_at': sessions[0], 'end_at': sessions[-1],
            'available_at': stamp(p['available_at']), 'recorded_at': at, 'stock_return': str(stock),
            'benchmark_return': str(bench), 'active_return': str(stock-bench),
            'forecast': d.get('forecasts', {}).get(str(h)), 'model_version': d['model_version'],
            'decision_sha256': d['decision_sha256'], 'source_sha256': p['source_sha256']}
    else:
        raise ValueError('unsupported_event')
    s['last_at'] = at
    return s


class Journal:
    """Transactional, hash-chained internal journal; explicit compare-and-swap head."""
    def __init__(self, path: str | Path):
        self.path = Path(path); safe_path(self.path); self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self.connect()) as db, db:
            db.execute('CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY, event_id TEXT UNIQUE NOT NULL, parent TEXT NOT NULL, digest TEXT NOT NULL, body TEXT NOT NULL)')

    def connect(self):
        return sqlite3.connect(self.path, timeout=15)

    @staticmethod
    def replay(db):
        s = initial(); head = ZERO; seq = 0
        for number, eid, parent, value, body in db.execute('SELECT * FROM events ORDER BY seq'):
            event = json.loads(body)
            if number != seq + 1 or eid != event['event_id'] or parent != head or value != hashed({'parent': parent, 'event': event}):
                raise ValueError('journal_chain_invalid')
            s = apply(s, event); seq = number; head = value
        return s, head, seq

    def read(self):
        with closing(self.connect()) as db:
            s, head, seq = self.replay(db)
        return {'head': head, 'events': seq, 'state': s, 'orders_allowed': False, 'commercial_release_allowed': False}

    def append(self, event: dict, expected_head: str):
        result = self.append_batch([event], expected_head)
        return {'head': result['head'], 'inserted': bool(result['inserted_events'])}

    def append_batch(self, events: list[dict], expected_head: str):
        sha(expected_head)
        if not isinstance(events, list) or not events: raise ValueError('event_batch_required')
        with closing(self.connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                state, head, seq = self.replay(db); inserted = 0
                for event in events:
                    body = encode(event)
                    old = db.execute('SELECT body FROM events WHERE event_id=?', (event['event_id'],)).fetchone()
                    if old:
                        if old[0] != body: raise ValueError('event_id_conflict')
                        continue
                    if inserted == 0 and head != expected_head: raise ValueError('stale_parent')
                    state = apply(state, event)
                    value = hashed({'parent': head, 'event': event}); seq += 1
                    db.execute('INSERT INTO events VALUES(?,?,?,?,?)', (seq, event['event_id'], head, value, body))
                    head = value; inserted += 1
                db.commit(); return {'head': head, 'inserted_events': inserted}
            except BaseException:
                db.rollback(); raise

    def backup(self, destination: str | Path):
        dest = Path(destination); safe_path(dest)
        # Atomic exclusive creation protects unrelated existing files.
        with dest.open('xb'): pass
        with closing(self.connect()) as src, closing(sqlite3.connect(dest)) as out:
            self.replay(src); src.backup(out)
        restored = Journal(dest).read()
        return {'sha256': hashlib.sha256(dest.read_bytes()).hexdigest(), 'head': restored['head'],
                'events': restored['events'], 'drive_restored': False}


def learning_report(journal: Journal, cutoff: str) -> dict:
    """Score only matured fixed-horizon forecasts. No coefficient/policy mutation."""
    when = stamp(cutoff); snapshot = journal.read(); groups = {}; pending = 0
    s = snapshot['state']
    for did,d in s['decisions'].items():
        if d['at'] > when: continue
        for h in d.get('forecasts', {}):
            o = s['outcomes'].get(did + ':' + h)
            if not o or max(o['available_at'], o['recorded_at']) > when:
                pending += 1; continue
            g = groups.setdefault(d['model_version'] + ':' + h, {'count': 0, 'abs_error': Decimal(0),
                'bias': Decimal(0), 'brier': Decimal(0), 'positive': 0, 'negative': 0, 'actions': {}, 'issuers': set()})
            actual = money(o['stock_return']); forecast = o['forecast']
            if forecast is None: raise ValueError('missing_original_forecast')
            predicted, probability = money(forecast['expected_return']), money(forecast['p_positive'])
            g['count'] += 1; g['abs_error'] += abs(actual-predicted); g['bias'] += predicted-actual
            g['brier'] += (probability-Decimal(int(actual>0))) ** 2
            g['positive'] += int(actual>0); g['negative'] += int(actual<0)
            g['actions'][d['action']] = g['actions'].get(d['action'], 0)+1; g['issuers'].add(d['security_id'])
    output = {}
    for key,g in groups.items():
        n = Decimal(g['count'])
        output[key] = {'mature_records': g['count'], 'unique_securities': len(g['issuers']),
            'mae': str(g['abs_error']/n), 'forecast_bias': str(g['bias']/n), 'brier': str(g['brier']/n),
            'negative_return_fraction': str(Decimal(g['negative'])/n), 'actions': g['actions'],
            'independent_sample_count': None, 'uncertainty_interval': None}
    return {'schema': SCHEMA, 'cutoff': when, 'journal_head': snapshot['head'], 'data_kind': s['mode'],
        'groups': output, 'pending_forecast_outcomes': pending, 'auto_promotion': False,
        'status': 'MATURE_OUTCOME_DIAGNOSTICS' if output else 'WAITING_FOR_MATURE_OUTCOMES',
        'next_research': 'PREREGISTER_CHALLENGER_THEN_CHRONOLOGICAL_OOS' if output else None,
        'performance_claim_allowed': False}


def calibration_challenger(journal: Journal, train_cutoff: str, evaluate_at: str,
                           min_train: int = 30, min_test: int = 10) -> dict:
    """Research-only shrunk forecast-bias candidate; chronological holdout required.

An intercept adjustment is NOT a new stock selector or a trade backtest. Repeated
issuer/event observations are not asserted independent; no significance claim.
"""
    train, end = stamp(train_cutoff), stamp(evaluate_at)
    if train >= end or type(min_train) is not int or min_train < 30 or type(min_test) is not int or min_test < 10:
        raise ValueError('research_split_or_sample_floor')
    snap = journal.read(); state = snap['state']; groups = {}
    for o in state['outcomes'].values():
        available = max(o['available_at'], o['recorded_at']); d=state['decisions'][o['decision_id']]
        if available > end or o['forecast'] is None: continue
        key = d['model_version'] + ':' + str(o['horizon_sessions'])
        g=groups.setdefault(key,{'train':[],'test':[]})
        error=money(o['forecast']['expected_return'])-money(o['stock_return'])
        if available <= train: g['train'].append(error)
        elif d['at'] > train: g['test'].append((money(o['forecast']['expected_return']), money(o['stock_return'])))
        # A pre-cutoff decision whose target crosses the split is purged.
    results={}
    for key,g in groups.items():
        nt,nv=len(g['train']),len(g['test'])
        if nt < min_train or nv < min_test:
            results[key]={'status':'INSUFFICIENT_MATURE_HOLDOUT','train':nt,'test':nv};continue
        # Fixed ridge penalty; never searched over the holdout.
        offset=sum(g['train'],Decimal(0))/Decimal(nt+30)
        baseline=sum((abs(pred-actual) for pred,actual in g['test']),Decimal(0))/Decimal(nv)
        candidate=sum((abs(max(Decimal(-1),pred-offset)-actual) for pred,actual in g['test']),Decimal(0))/Decimal(nv)
        results[key]={'status':'REVIEW_CANDIDATE' if candidate<baseline else 'REJECT_KEEP_BASELINE',
            'train':nt,'test':nv,'subtract_from_original_forecast':str(offset),
            'baseline_test_mae':str(baseline),'candidate_test_mae':str(candidate),
            'prediction_floor':'-1', 'significance_verified':False,'transaction_cost_performance':None}
    return {'schema':SCHEMA,'experiment':'SHRUNK_FORECAST_BIAS_V1','train_cutoff':train,
            'evaluate_at':end,'data_kind':state['mode'],'journal_head':snap['head'],'results':results,
            'auto_promotion':False,'production_mutated':False,'repeated_tuning_allowed':False}
