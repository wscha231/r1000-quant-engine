"""Synthetic lifecycle fixtures; not observed trades or strategy performance."""
from copy import deepcopy
from contextlib import closing
from datetime import datetime,timedelta,timezone
from decimal import Decimal
from pathlib import Path
import json
import sqlite3
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.subscription_manager.continuous import (Journal,ZERO,hashed,stamp,apply,initial,learning_report,calibration_challenger)

H='a'*64
T='2026-01-05T15:00:00+00:00'

def event(eid,kind,p,at=T):return {'event_id':eid,'type':kind,'at':at,'payload':p}
def opening():return event('open','OPEN',{'book_kind':'MODEL_PAPER','data_kind':'SYNTHETIC','currency':'USD','cash':'1000','policy_sha256':H})
def decision(did='d1',action='BUY',qty='5',at='2026-01-05T16:00:00+00:00'):
 return event(did,'DECISION',{'decision_id':did,'security_id':'US:TEST','action':action,'max_quantity':qty,
 'information_available_at':T,'valid_until':'2026-03-31T23:00:00+00:00','snapshot_sha256':H,'review_sha256':H,
 'config_sha256':H,'thesis_id':'THESIS','model_version':'TEST_V1','reason_codes':['THESIS_CONFIRMED'],
 'forecasts':{'21':{'expected_return':'0.1','p_positive':'0.7'}}},at)
def delivery(d):
 return event('publish-'+d['event_id'],'DELIVERY',{'decision_id':d['event_id'],'decision_sha256':hashed(d),
 'delivery_receipt_sha256':H,'calendar_receipt_sha256':H,'channel':'INTERNAL_SHADOW',
 'execution_window_start':'2026-01-06T14:30:00+00:00','execution_window_end':'2026-03-30T20:00:00+00:00'},'2026-01-05T17:00:00+00:00')
def fill(fid='f1',did='d1',q='5',price='100',fee='1',at='2026-01-06T14:30:00+00:00'):
 return event(fid,'FILL',{'fill_id':fid,'decision_id':did,'quantity':q,'price':price,'fee':fee,
 'quote_at':at,'price_basis':'RAW_EXECUTABLE','quote_sha256':H,'calendar_receipt_sha256':H},at)

class ContinuousTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
  self.j=Journal(Path(self.temp.name)/'journal.sqlite');self.add(opening())
 def add(self,e):return self.j.append(e,self.j.read()['head'])
 def buy(self,q='5'):
  d=decision(qty=q);self.add(d);self.add(delivery(d));self.add(fill(q=q));return d
 def test_normal_buy_and_mark(self):
  self.buy();self.add(event('mark','MARK',{'prices':{'US:TEST':'110'},'quote_at':'2026-01-06T20:00:00Z','source_sha256':H,'price_basis':'RAW_CLOSE'},'2026-01-06T20:00:00Z'))
  s=self.j.read()['state'];self.assertEqual(Decimal(s['cash']),499);self.assertEqual(Decimal(s['nav']['value']),1049)
 def test_no_delivery_no_fill(self):
  self.add(decision())
  with self.assertRaisesRegex(ValueError,'authorized'):self.add(fill())
 def test_before_publication_window_rejected(self):
  d=decision();self.add(d);self.add(delivery(d))
  with self.assertRaisesRegex(ValueError,'window'):self.add(fill(at='2026-01-05T18:00:00Z'))
 def test_duplicate_event_once(self):
  d=self.buy();head=self.j.read()['head'];self.assertFalse(self.j.append(fill(),ZERO)['inserted']);self.assertEqual(self.j.read()['head'],head)
 def test_duplicate_id_conflict(self):
  self.buy()
  with self.assertRaisesRegex(ValueError,'conflict'):self.j.append(fill(price='101'),self.j.read()['head'])
 def test_same_fill_different_event_id_rejected(self):
  self.buy();e=fill();e['event_id']='another'
  with self.assertRaisesRegex(ValueError,'authorized'):self.add(e)
 def test_stale_parent(self):
  with self.assertRaisesRegex(ValueError,'stale_parent'):self.j.append(decision(),ZERO)
 def test_partial_fill_limit(self):
  d=decision();self.add(d);self.add(delivery(d));self.add(fill(q='3'))
  with self.assertRaisesRegex(ValueError,'quantity'):self.add(fill(fid='f2',q='3'))
  self.add(fill(fid='f2',q='2'));self.assertEqual(self.j.read()['state']['positions']['US:TEST']['quantity'],'5')
 def test_no_insufficient_cash_partial_write(self):
  d=decision(qty='20');self.add(d);self.add(delivery(d));before=self.j.read()['head']
  with self.assertRaisesRegex(ValueError,'insufficient'):self.add(fill(q='20'))
  self.assertEqual(before,self.j.read()['head'])
 def test_sell_without_ownership(self):
  d=decision(action='SELL');self.add(d);self.add(delivery(d))
  with self.assertRaisesRegex(ValueError,'oversell'):self.add(fill())
 def test_sell_fees_cost_basis(self):
  d=decision();s=decision('s','SELL','2');self.add(d);self.add(s);self.add(delivery(d));self.add(delivery(s));self.add(fill());self.add(fill('f2','s','2','120','1'))
  state=self.j.read()['state'];self.assertEqual(Decimal(state['cash']),738);self.assertEqual(Decimal(state['realized_pnl']),Decimal('38.6'))
 def test_sale_not_short_rs_only(self):
  d=decision(action='SELL');d['payload']['reason_codes']=['RS_SHORT_WEAK']
  with self.assertRaisesRegex(ValueError,'short_rs'):self.add(d)
 def test_quote_basis(self):
  d=decision();self.add(d);self.add(delivery(d));e=fill();e['payload']['price_basis']='ADJUSTED'
  with self.assertRaisesRegex(ValueError,'basis'):self.add(e)
 def test_future_information(self):
  d=decision();d['payload']['information_available_at']='2026-01-07T00:00:00Z'
  with self.assertRaisesRegex(ValueError,'availability'):self.add(d)
 def test_cancel_blocks_remaining(self):
  self.buy();self.add(event('cancel','CANCEL',{'decision_id':'d1','reason':'THESIS_CHANGED','evidence_sha256':H},'2026-01-07T00:00:00Z'))
  with self.assertRaisesRegex(ValueError,'authorized'):self.add(fill('f2',q='1',at='2026-01-07T14:30:00Z'))
 def test_split_keeps_cost_invalidates_instruction(self):
  self.buy();e=event('split','SPLIT',{'security_id':'US:TEST','ratio':'2','source_sha256':H,'action_id':'CA1'},'2026-01-07T00:00:00Z');self.add(e)
  s=self.j.read()['state'];self.assertEqual(s['positions']['US:TEST'],{'quantity':'10','cost':'501'});self.assertTrue(s['decisions']['d1']['invalidated'])
  e['event_id']='split-copy'
  with self.assertRaisesRegex(ValueError,'duplicate_corporate'):self.add(e)
 def test_dividend_receivable_paid_once(self):
  self.buy();self.add(event('ex','DIVIDEND_EX',{'action_id':'DIV1','security_id':'US:TEST','source_sha256':H,'cash_per_share':'2','ex_at':'2026-01-07T00:00:00Z','pay_at':'2026-01-20T00:00:00Z'},'2026-01-07T00:00:00Z'))
  self.add(event('pay','DIVIDEND_PAY',{'action_id':'DIV1','source_sha256':H},'2026-01-20T00:00:00Z'));self.assertEqual(Decimal(self.j.read()['state']['cash']),509)
  with self.assertRaises(KeyError):self.add(event('pay2','DIVIDEND_PAY',{'action_id':'DIV1','source_sha256':H},'2026-01-20T00:00:00Z'))
 def test_missing_marks_not_zero(self):
  self.buy()
  with self.assertRaisesRegex(ValueError,'coverage'):self.add(event('mark','MARK',{'prices':{},'quote_at':'2026-01-06T20:00:00Z','source_sha256':H,'price_basis':'RAW_CLOSE'},'2026-01-06T20:00:00Z'))
 def test_backup_and_tamper(self):
  self.buy();backup=Path(self.temp.name)/'backup.sqlite';result=self.j.backup(backup);self.assertEqual(result['head'],self.j.read()['head'])
  with closing(sqlite3.connect(backup)) as db, db:db.execute("UPDATE events SET body='{}' WHERE seq=1")
  with self.assertRaises((ValueError,KeyError)):Journal(backup).read()
 def test_backup_no_overwrite(self):
  dest=Path(self.temp.name)/'keep';dest.write_text('existing')
  with self.assertRaises(FileExistsError):self.j.backup(dest)
  self.assertEqual(dest.read_text(),'existing')
 def outcome(self,d):
  start=datetime(2026,1,6,20,tzinfo=timezone.utc);sessions=[(start+timedelta(days=i)).isoformat() for i in range(22)]
  return event('outcome','OUTCOME',{'decision_id':d['event_id'],'decision_sha256':hashed(d),'horizon_sessions':21,
   'return_basis':'TOTAL_RETURN_INDEX','source_sha256':H,'calendar_receipt_sha256':H,'sessions':sessions,
   'available_at':sessions[-1],'stock_start':'100','stock_end':'120','benchmark_start':'100','benchmark_end':'105'},sessions[-1])
 def test_outcome_requires_maturity(self):
  d=self.buy();e=self.outcome(d);e['at']='2026-01-10T20:00:00Z'
  with self.assertRaisesRegex(ValueError,'maturity'):self.add(e)
 def test_outcome_calendar_count(self):
  d=self.buy();e=self.outcome(d);e['payload']['sessions'].pop()
  with self.assertRaisesRegex(ValueError,'maturity'):self.add(e)
 def test_learning_maturity_and_holdout_floor(self):
  d=self.buy();self.add(self.outcome(d));r=learning_report(self.j,'2026-01-10T20:00:00Z');self.assertEqual(r['pending_forecast_outcomes'],1);self.assertEqual(r['groups'],{})
  r=learning_report(self.j,'2026-02-01T00:00:00Z');self.assertEqual(Decimal(r['groups']['TEST_V1:21']['mae']),Decimal('0.1'));self.assertFalse(r['auto_promotion'])
  c=calibration_challenger(self.j,'2026-02-01T00:00:00Z','2026-03-01T00:00:00Z');self.assertEqual(c['results']['TEST_V1:21']['status'],'INSUFFICIENT_MATURE_HOLDOUT')
 def test_watch_nontrade_outcome_retained(self):
  d=decision(action='WATCH',qty='0');self.add(d);self.add(self.outcome(d));r=learning_report(self.j,'2026-02-01T00:00:00Z');self.assertEqual(r['groups']['TEST_V1:21']['actions'],{'WATCH':1})
 def test_outcome_duplicate_no_relabel(self):
  d=self.buy();e=self.outcome(d);self.add(e);e['event_id']='edited';e['payload']['stock_end']='130'
  with self.assertRaisesRegex(ValueError,'already_recorded'):self.add(e)
 def test_published_input_mode_not_customer_book(self):
  bad=opening();bad['payload']['book_kind']='ACTUAL_BROKER'
  with self.assertRaisesRegex(ValueError,'model_paper'):apply(initial(),bad)
 def test_timestamp_requires_timezone(self):
  with self.assertRaisesRegex(ValueError,'timezone'):stamp('2026-01-01T00:00:00')
 def test_learning_small_floor_not_overrideable(self):
  with self.assertRaisesRegex(ValueError,'floor'):calibration_challenger(self.j,T,'2026-03-01T00:00:00Z',1,1)

class ExtraTests(unittest.TestCase):
 def test_batch_failure_rolls_back_whole_batch(self):
  with tempfile.TemporaryDirectory() as temp:
   j=Journal(Path(temp)/'j.sqlite')
   with self.assertRaisesRegex(ValueError,'authorized'):
    j.append_batch([opening(),decision(),fill()],ZERO)
   self.assertEqual(j.read()['events'],0)
 def test_challenger_has_true_chronological_test_and_no_promotion(self):
  class Stub:
   def read(self):return snap
  decisions={};outcomes={}
  for i in range(41):
   did='d'+str(i);train=i<30;purged=i==40
   at='2025-01-01T00:00:00+00:00' if train or purged else '2026-02-01T00:00:00+00:00'
   recorded='2025-03-01T00:00:00+00:00' if train else '2026-03-01T00:00:00+00:00'
   decisions[did]={'at':at,'model_version':'fixture'}
   outcomes[did]={'decision_id':did,'recorded_at':recorded,'available_at':recorded,
    'horizon_sessions':21,'forecast':{'expected_return':'0.3'},'stock_return':'0.1'}
  snap={'head':H,'state':{'decisions':decisions,'outcomes':outcomes,'mode':'SYNTHETIC'}}
  result=calibration_challenger(Stub(),'2026-01-01T00:00:00Z','2026-04-01T00:00:00Z')
  g=result['results']['fixture:21'];self.assertEqual(g['train'],30);self.assertEqual(g['test'],10)
  self.assertEqual(g['status'],'REVIEW_CANDIDATE');self.assertEqual(Decimal(g['candidate_test_mae']),Decimal('0.1'));self.assertFalse(result['auto_promotion'])

if __name__=='__main__':unittest.main()
