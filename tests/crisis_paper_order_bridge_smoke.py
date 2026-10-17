#!/usr/bin/env python3
"""B2 synthetic parity/preflight tests. No actual account preview or network."""
from __future__ import annotations
import copy
import hashlib
import json
import sys
import unittest
from argparse import Namespace
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import pandas as pd
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tools import run_crisis_paper_order_bridge as bridge
from tools import daily_crisis_report_clock as clock
from tools.run287_crisis_policy import apply_selective_defense


def sha(raw):return hashlib.sha256(raw).hexdigest()


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.latest = self.root/'inputs'
        self.output = self.root/'bridge'
        self.now = datetime(2026,1,2,23,tzinfo=timezone.utc)
        self.target = pd.DataFrame([dict(ticker='AAA',target_weight=.20),dict(ticker='BBB',target_weight=.58),dict(ticker='CASH',target_weight=.22)])
        self.monitor = dict(schema_version='daily-crisis-monitor-v2',state='DEFENSE',raw_state='DEFENSE',
            current_report_status='CURRENT_LEGACY_DIAGNOSTIC',data_health='DATE_CURRENT_DIAGNOSTIC',
            risk_as_of_session='2026-01-02',generated_at_utc='2026-01-02T22:30:00Z',
            source_clock_authenticated=True,canonical_regime_authorized=True,
            auto_trade_allowed=False,paper_actions_only=True,paper_action_candidates=[
                dict(action_type='block_new_buys'),dict(action_type='raise_cash',target_cash_weight=.25),
                dict(action_type='trim_position',ticker='AAA',current_weight=.20,trim_weight=.03)])
        self.proof = dict(schema='crisis-paper-bridge-evidence-v1',report_session='2026-01-02',
            policy_sha256=sha((ROOT/'tools/run287_crisis_policy.py').read_bytes()),portfolios={})
        for portfolio in bridge.PORTFOLIOS:
            account = dict(as_of_date='2026-01-02',cash_usd=8000.,positions=[dict(ticker='AAA',shares=20.,cost_basis=90.)])
            a=self.latest/'broker_replay'/portfolio/'account_state_latest.json';a.parent.mkdir(parents=True);a.write_text(json.dumps(account))
            t=self.latest/'reports'/f'operating_{portfolio}_target_book.csv';t.parent.mkdir(parents=True,exist_ok=True);self.target.to_csv(t,index=False)
            self.proof['portfolios'][portfolio]=dict(book_session='2026-01-02',accepted_book_receipt_sha256='b'*64,
                account_sha256=sha(a.read_bytes()),target_sha256=sha(t.read_bytes()),economics={
                    ticker:dict(net_er=.12,downside=.20,cost_bps=25.,liquidity_usd=1e7,receipt_sha256='c'*64)
                    for ticker in ('AAA','BBB')})
        self.monitor_path=self.latest/'daily_crisis_monitor/summary.json';self.monitor_path.parent.mkdir()
        self.proof_path=self.root/'fixture-proof.json'
        self.args=Namespace(latest_run=str(self.latest),output_dir=str(self.output),price_cache=str(self.root/'cache'),
            cost_bps=25.,evidence_manifest=str(self.proof_path),expected_evidence_sha256=None)
        self.bind()

    def bind(self):
        # Synthetic external-pin-shaped fixtures only, never actual acceptance.
        self.monitor_path.write_text(json.dumps(self.monitor))
        self.proof['monitor_sha256']=sha(self.monitor_path.read_bytes())
        self.proof_path.write_text(json.dumps(self.proof))
        self.args.expected_evidence_sha256=sha(self.proof_path.read_bytes())

    def run_blocked(self):
        self.output.mkdir(exist_ok=True)
        (self.output/'summary.json').write_text('{"status":"completed","old":true}')
        old=self.output/'main/account_order_preview/orders_preview.csv';old.parent.mkdir(parents=True,exist_ok=True);old.write_text('old numeric orders')
        keep=self.output/'unrelated.txt';keep.write_text('preserve')
        before={str(p):sha(p.read_bytes()) for p in self.latest.rglob('*') if p.is_file()}
        with patch.object(clock,'trusted_now',return_value=self.now),patch.object(bridge,'run_order_preview',side_effect=AssertionError('actual preview reached')) as preview:
            result=bridge.run(self.args)
        self.assertEqual(result['status'],'blocked');self.assertEqual(result['data_health'],'REAL_INPUT_WAIT')
        self.assertEqual(result['portfolios'],[]);self.assertIsNone(result['monitor_state']);preview.assert_not_called()
        self.assertFalse(old.exists());self.assertEqual(keep.read_text(),'preserve')
        self.assertIn('REAL_INPUT_WAIT',(self.output/'summary.md').read_text())
        self.assertEqual(before,{str(p):sha(p.read_bytes()) for p in self.latest.rglob('*') if p.is_file()})
        return result

    def test_missing_blocked_stale_untyped_unproven_monitors_refuse(self):
        valid=copy.deepcopy(self.monitor)
        for changes in [dict(current_report_status='BLOCKED'),dict(state=None),dict(raw_state='DEFENSE_REVIEW'),
                        dict(source_clock_authenticated=False),dict(canonical_regime_authorized=False),
                        dict(generated_at_utc='2026-01-01T21:30:00Z'),dict(generated_at_utc='2026-01-03T00:00:00Z'),
                        dict(state={}),dict(auto_trade_allowed=True),dict(risk_as_of_session='2026-01-01')]:
            with self.subTest(changes=changes):
                self.monitor=dict(valid,**changes);self.bind();self.run_blocked()
        self.monitor_path.unlink();self.run_blocked()

    def test_missing_hash_and_malformed_evidence_refuse(self):
        self.args.expected_evidence_sha256=None;self.run_blocked()
        self.args.expected_evidence_sha256='d'*64;self.run_blocked()
        self.proof_path.write_text('[]');self.args.expected_evidence_sha256=sha(self.proof_path.read_bytes());self.run_blocked()

    def test_missing_economic_dimensions_and_receipts_refuse(self):
        baseline=copy.deepcopy(self.proof)
        for field in ('net_er','downside','cost_bps','liquidity_usd','receipt_sha256'):
            with self.subTest(field=field):
                self.proof=copy.deepcopy(baseline);self.proof['portfolios']['main']['economics']['AAA'].pop(field)
                self.bind();self.run_blocked()
        self.proof=copy.deepcopy(baseline);self.proof['portfolios']['main'].pop('accepted_book_receipt_sha256');self.bind();self.run_blocked()

    def test_book_session_hash_cost_and_policy_binding_refuse(self):
        baseline=copy.deepcopy(self.proof)
        changes=[('book_session','2026-01-01'),('target_sha256','d'*64),('account_sha256','e'*64)]
        for field,value in changes:
            self.proof=copy.deepcopy(baseline);self.proof['portfolios']['main'][field]=value;self.bind();self.run_blocked()
        self.proof=copy.deepcopy(baseline);self.proof['policy_sha256']='f'*64;self.bind();self.run_blocked()
        self.proof=copy.deepcopy(baseline);self.proof['portfolios']['main']['economics']['AAA']['cost_bps']=26.;self.bind();self.run_blocked()

    def test_nonfinite_boolean_oversized_or_missing_trim_never_defaults_half(self):
        for invalid in (None,True,float('nan'),float('inf'),10**400,-.01,.21):
            with self.subTest(value=str(invalid)[:20]):
                m=copy.deepcopy(self.monitor);m['paper_action_candidates'][-1]['trim_weight']=invalid
                with self.assertRaises(ValueError):bridge.action_plan(m)
        m=copy.deepcopy(self.monitor);m['paper_action_candidates'][-1].pop('trim_weight')
        with self.assertRaises(ValueError):bridge.action_plan(m)

    def test_twenty_percent_minus_three_points_is_seventeen_and_winner_unchanged(self):
        out=bridge.derive_target_book(self.target,'main',bridge.action_plan(self.monitor)).set_index('ticker')
        self.assertAlmostEqual(out.loc['AAA','target_weight'],.17)
        self.assertAlmostEqual(out.loc['BBB','target_weight'],.58)
        self.assertAlmostEqual(out.loc['CASH','target_weight'],.25)
        self.assertAlmostEqual(out.loc['CASH','capacity_unallocated'],.22)
        self.assertAlmostEqual(out.loc['CASH','crisis_reserve'],.03)
        self.assertAlmostEqual(out.target_weight.sum(),1.)

    def test_fixture_canonical_policy_cash_and_selective_trim_parity(self):
        original=self.target.rename(columns={'target_weight':'weight'})
        canonical,audit,summary=apply_selective_defense(original,state='DEFENSE',portfolio_kind='main',
            evidence=pd.DataFrame([dict(ticker='AAA',thesis_broken=True),dict(ticker='BBB',current_conviction=100.)]))
        self.assertAlmostEqual(audit[0]['trim_weight'],.03)
        out=bridge.derive_target_book(self.target,'main',bridge.action_plan(self.monitor)).set_index('ticker')
        for row in canonical.itertuples():self.assertAlmostEqual(out.loc[row.ticker,'target_weight'],row.weight)
        for reason,value in summary['reserve_reasons'].items():self.assertAlmostEqual(out[reason].sum(),value)

    def test_unsupported_cash_target_or_mismatched_trim_refuses(self):
        m=copy.deepcopy(self.monitor);m['paper_action_candidates'][1]['target_cash_weight']=.50
        with self.assertRaises(ValueError):bridge.derive_target_book(self.target,'main',bridge.action_plan(m))
        m=copy.deepcopy(self.monitor);m['paper_action_candidates'][-1]['current_weight']=.80
        with self.assertRaises(ValueError):bridge.derive_target_book(self.target,'main',bridge.action_plan(m))
        m=copy.deepcopy(self.monitor);m['paper_action_candidates'].append(m['paper_action_candidates'][-1])
        with self.assertRaises(ValueError):bridge.action_plan(m)

    def test_overlap_and_symlink_outputs_refuse_before_mutation(self):
        before=self.monitor_path.read_bytes();self.args.output_dir=str(self.latest)
        with self.assertRaises(ValueError):bridge.run(self.args)
        self.assertEqual(self.monitor_path.read_bytes(),before)
        self.args.output_dir=str(self.output)
        with patch.object(type(self.output),'is_symlink',lambda p:p==self.output/'summary.json'):
            with self.assertRaises(ValueError):bridge.run(self.args)

    def fake_preview(self,args):
        # Stub only: never call the actual account/order calculation.
        out=Path(args.output_dir);out.mkdir(parents=True,exist_ok=True)
        pd.DataFrame([dict(ticker='BBB',side='BUY',status='ready')]).to_csv(out/'orders_preview.csv',index=False)
        return dict(status='completed')

    def test_mocked_fixture_preview_stays_approval_required_and_blocks_new_buys(self):
        with patch.object(clock,'trusted_now',return_value=self.now),patch.object(bridge,'ACTUAL_PREVIEW_ACTIVATED',True),patch.object(bridge,'run_order_preview',side_effect=self.fake_preview) as engine:
            result=bridge.run(self.args)
        self.assertEqual(result['status'],'completed');self.assertEqual(engine.call_count,2)
        self.assertFalse(result['auto_trade_allowed']);self.assertTrue(result['approval_required']);self.assertTrue(result['paper_only'])
        orders=pd.read_csv(self.output/'main/paper_orders_preview.csv')
        self.assertEqual(orders.loc[0,'status'],'blocked_new_buy_pending_approval')
        self.assertTrue(orders.approval_required.all())
        target=pd.read_csv(self.output/'main/paper_action_target_book.csv').set_index('ticker')
        self.assertAlmostEqual(target.loc['AAA','target_weight'],.17)

    def test_preview_failure_invalidates_partial_derived_outputs(self):
        with patch.object(clock,'trusted_now',return_value=self.now),patch.object(bridge,'ACTUAL_PREVIEW_ACTIVATED',True),patch.object(bridge,'run_order_preview',side_effect=[dict(status='blocked'),RuntimeError('private')]):
            result=bridge.run(self.args)
        self.assertEqual(result['status'],'blocked')
        self.assertFalse((self.output/'main/paper_action_target_book.csv').exists())
        self.assertNotIn('private',(self.output/'summary.json').read_text())

    def test_actual_activation_stays_off_even_with_synthetic_complete_pins(self):
        self.assertIs(bridge.ACTUAL_PREVIEW_ACTIVATED,False)
        self.run_blocked()

    def test_empty_sentinel_alias_or_unnormalized_identity_never_becomes_cash(self):
        plan=bridge.action_plan(dict(self.monitor,paper_action_candidates=[dict(action_type='no_op')]))
        for invalid in ('',None,float('nan'),'NAN','NONE','NULL','__CASH__',' aaa','AAA '):
            with self.subTest(value=invalid):
                target=self.target.copy();target.loc[0,'ticker']=invalid
                with self.assertRaises(ValueError):bridge.derive_target_book(target,'main',plan)
                target_path=self.latest/'reports/operating_main_target_book.csv';target.to_csv(target_path,index=False)
                self.proof['portfolios']['main']['target_sha256']=sha(target_path.read_bytes());self.bind()
                with patch.object(clock,'trusted_now',return_value=self.now):
                    with self.assertRaises(ValueError):bridge.checked_inputs(self.args,self.latest,self.monitor_path.read_bytes())

    def test_cli_blocked_exit_status(self):
        with patch.object(bridge,'run',return_value=dict(status='blocked')):
            self.assertEqual(bridge.main([]),2)


def test_crisis_paper_order_bridge_requires_approval_and_blocks_new_buys():
    result=unittest.TextTestRunner().run(unittest.defaultTestLoader.loadTestsFromTestCase(BridgeTests))
    if not result.wasSuccessful():raise RuntimeError('B2_FIXTURE_FAILED')

if __name__=='__main__':
    test_crisis_paper_order_bridge_requires_approval_and_blocks_new_buys()
    print('crisis_paper_order_bridge_smoke: PASS; synthetic fixtures/mock preview only')
