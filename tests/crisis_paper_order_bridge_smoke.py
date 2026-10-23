#!/usr/bin/env python3
"""B2 synthetic parity/preflight tests. No actual account preview or network."""
from __future__ import annotations
import copy
import hashlib
import io
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
from tools.reserve_asset_policy import RESERVE_REASON_SOURCE_HASH_FIELD, reserve_reason_reconciliation, resolve_reserve_asset_policy


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
        self.target[RESERVE_REASON_SOURCE_HASH_FIELD] = reserve_reason_reconciliation(self.target,
            policy=resolve_reserve_asset_policy(context='current_paper'),weight_col='target_weight')[RESERVE_REASON_SOURCE_HASH_FIELD]
        self.cache=self.root/'cache';self.cache.mkdir()
        self.price_proof={}
        for ticker in ('AAA','BBB'):
            name=bridge.px_cache_name(ticker)
            buffer=io.BytesIO()
            pd.DataFrame({'Close':[100.]},index=pd.DatetimeIndex(['2026-01-02'])).to_parquet(buffer,index=True)
            raw=buffer.getvalue()
            (self.cache/name).write_bytes(raw)
            self.price_proof[ticker]=dict(relative_path=name,sha256=sha(raw),byte_count=len(raw))
        self.monitor = dict(schema_version='daily-crisis-monitor-v2',state='DEFENSE',raw_state='DEFENSE',
            current_report_status='CURRENT_LEGACY_DIAGNOSTIC',data_health='DATE_CURRENT_DIAGNOSTIC',
            risk_as_of_session='2026-01-02',generated_at_utc='2026-01-02T22:30:00Z',
            source_clock_authenticated=True,canonical_regime_authorized=True,
            auto_trade_allowed=False,paper_actions_only=True,paper_action_candidates=[
                dict(action_type='block_new_buys'),dict(action_type='raise_cash',portfolio_kind='main',target_cash_weight=.25),
                dict(action_type='raise_cash',portfolio_kind='concentrated',target_cash_weight=.25),
                dict(action_type='trim_position',portfolio_kind='concentrated',ticker='AAA',current_weight=.40,trim_weight=.03),
                dict(action_type='trim_position',portfolio_kind='main',ticker='AAA',current_weight=.20,trim_weight=.03)])
        self.proof = dict(schema='crisis-paper-bridge-evidence-v1',report_session='2026-01-02',
            policy_sha256=sha((ROOT/'tools/run287_crisis_policy.py').read_bytes()),portfolios={})
        for portfolio in bridge.PORTFOLIOS:
            account = dict(portfolio_kind=portfolio,as_of_date='2026-01-02',cash_usd=8000.,positions=[dict(ticker='AAA',shares=20.,cost_basis=90.)])
            a=self.latest/'broker_replay'/portfolio/'account_state_latest.json';a.parent.mkdir(parents=True);a.write_text(json.dumps(account))
            t=self.latest/'reports'/f'operating_{portfolio}_target_book.csv';t.parent.mkdir(parents=True,exist_ok=True);portfolio_target=self.target.copy()
            if portfolio=='concentrated':
                portfolio_target.loc[portfolio_target.ticker=='AAA','target_weight']=.40
                portfolio_target.loc[portfolio_target.ticker=='BBB','target_weight']=.38
            portfolio_target.to_csv(t,index=False)
            self.proof['portfolios'][portfolio]=dict(book_session='2026-01-02',accepted_book_receipt_sha256='b'*64,
                prices=copy.deepcopy(self.price_proof),
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

    def replace_price(self, ticker, frame=None, raw=None):
        if raw is None:
            buffer=io.BytesIO();frame.to_parquet(buffer,index=True);raw=buffer.getvalue()
        name=bridge.px_cache_name(ticker);(self.cache/name).write_bytes(raw)
        for portfolio in bridge.PORTFOLIOS:
            prices=self.proof['portfolios'][portfolio]['prices']
            if ticker in prices:prices[ticker]=dict(relative_path=name,sha256=sha(raw),byte_count=len(raw))
        self.bind()

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
                with self.assertRaises(ValueError):bridge.action_plan(m,'main')
        m=copy.deepcopy(self.monitor);m['paper_action_candidates'][-1].pop('trim_weight')
        with self.assertRaises(ValueError):bridge.action_plan(m,'main')

    def test_twenty_percent_minus_three_points_is_seventeen_and_winner_unchanged(self):
        out=bridge.derive_target_book(self.target,'main',bridge.action_plan(self.monitor,'main')).set_index('ticker')
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
        out=bridge.derive_target_book(self.target,'main',bridge.action_plan(self.monitor,'main')).set_index('ticker')
        for row in canonical.itertuples():self.assertAlmostEqual(out.loc[row.ticker,'target_weight'],row.weight)
        for reason,value in summary['reserve_reasons'].items():self.assertAlmostEqual(out[reason].sum(),value)

    def test_unsupported_cash_target_or_mismatched_trim_refuses(self):
        m=copy.deepcopy(self.monitor);m['paper_action_candidates'][1]['target_cash_weight']=.50
        with self.assertRaises(ValueError):bridge.derive_target_book(self.target,'main',bridge.action_plan(m,'main'))
        m=copy.deepcopy(self.monitor);m['paper_action_candidates'][-1]['current_weight']=.80
        with self.assertRaises(ValueError):bridge.derive_target_book(self.target,'main',bridge.action_plan(m,'main'))
        m=copy.deepcopy(self.monitor);m['paper_action_candidates'].append(m['paper_action_candidates'][-1])
        with self.assertRaises(ValueError):bridge.action_plan(m,'main')

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
        return dict(status='completed',account_source_kind='simulated_broker_replay')

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
        other=pd.read_csv(self.output/'concentrated/paper_action_target_book.csv').set_index('ticker')
        self.assertAlmostEqual(other.loc['AAA','target_weight'],.37)
        self.assertAlmostEqual(other.loc['BBB','target_weight'],.38)

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
        plan=bridge.action_plan(dict(self.monitor,paper_action_candidates=[dict(action_type='no_op')]),'main')
        for invalid in ('',None,float('nan'),'NAN','NONE','NULL','__CASH__',' aaa','AAA '):
            with self.subTest(value=invalid):
                target=self.target.copy();target.loc[0,'ticker']=invalid
                with self.assertRaises(ValueError):bridge.derive_target_book(target,'main',plan)
                target_path=self.latest/'reports/operating_main_target_book.csv';target.to_csv(target_path,index=False)
                self.proof['portfolios']['main']['target_sha256']=sha(target_path.read_bytes());self.bind()
                with patch.object(clock,'trusted_now',return_value=self.now):
                    with self.assertRaises(ValueError):bridge.checked_inputs(self.args,self.latest,self.monitor_path.read_bytes())

    def test_dated_book_selects_pinned_snapshot_before_identity_and_economics(self):
        prior=self.target.copy();prior['rebalance_date']='2025-12-31'
        prior.loc[prior.ticker=='AAA','target_weight']=.10
        prior.loc[prior.ticker=='CASH','target_weight']=.32
        current=self.target.copy();current['rebalance_date']='2026-01-02'
        future=self.target.copy();future['rebalance_date']='2026-01-05'
        future.loc[future.ticker=='BBB','ticker']='FUTURE_ONLY'
        history=pd.concat([prior,current,future],ignore_index=True)
        path=self.latest/'reports/operating_main_target_book.csv';history.to_csv(path,index=False)
        self.proof['portfolios']['main']['target_sha256']=sha(path.read_bytes());self.bind()
        with patch.object(clock,'trusted_now',return_value=self.now):
            prepared=bridge.checked_inputs(self.args,self.latest,self.monitor_path.read_bytes())
        self.assertEqual(set(prepared['portfolios']['main']['target'].rebalance_date),{'2026-01-02'})
        out=bridge.derive_target_book(history,'main',bridge.action_plan(self.monitor,'main'),'2026-01-02').set_index('ticker')
        self.assertAlmostEqual(out.loc['AAA','target_weight'],.17)
        self.assertNotIn('FUTURE_ONLY',out.index)
        with self.assertRaises(ValueError):bridge.derive_target_book(history,'main',bridge.action_plan(self.monitor,'main'))
        with self.assertRaises(ValueError):bridge.session_target(future,'2026-01-02')

    def test_reserve_hash_is_verified_then_reissued_for_derived_cash(self):
        from tools.reserve_asset_policy import RESERVE_REASONS, RESERVE_REASON_SOURCE_HASH_FIELD, reserve_reason_reconciliation, resolve_reserve_asset_policy
        source=self.target.copy()
        for reason in RESERVE_REASONS:source[reason]=0.
        source.loc[source.ticker=='CASH','capacity_unallocated']=.22
        policy=resolve_reserve_asset_policy(context='current_paper')
        original=reserve_reason_reconciliation(source,policy=policy,weight_col='target_weight')
        source[RESERVE_REASON_SOURCE_HASH_FIELD]=original[RESERVE_REASON_SOURCE_HASH_FIELD]
        out=bridge.derive_target_book(source,'main',bridge.action_plan(self.monitor,'main'))
        after=reserve_reason_reconciliation(out,policy=policy,weight_col='target_weight')
        self.assertNotEqual(after[RESERVE_REASON_SOURCE_HASH_FIELD],original[RESERVE_REASON_SOURCE_HASH_FIELD])
        self.assertEqual(set(out[RESERVE_REASON_SOURCE_HASH_FIELD]),{after[RESERVE_REASON_SOURCE_HASH_FIELD]})
        source[RESERVE_REASON_SOURCE_HASH_FIELD]='d'*64
        with self.assertRaises(ValueError):bridge.derive_target_book(source,'main',bridge.action_plan(self.monitor,'main'))

    def test_zero_weight_rows_cannot_erase_embedded_reserve_hash(self):
        from tools.reserve_asset_policy import RESERVE_REASON_SOURCE_HASH_FIELD, reserve_reason_reconciliation, resolve_reserve_asset_policy
        source=pd.DataFrame({'ticker':['AAA','BBB','CASH'], 'target_weight':[.5,.5,0.]})
        policy=resolve_reserve_asset_policy(context='current_paper')
        valid=reserve_reason_reconciliation(source,policy=policy,weight_col='target_weight')[RESERVE_REASON_SOURCE_HASH_FIELD]
        source[RESERVE_REASON_SOURCE_HASH_FIELD]=['','',valid]
        before=source.copy(deep=True)
        plan={'portfolio_kind':'main','trim_tickers':{'AAA':{'current_weight':.5,'trim_weight':.03}}}
        out=bridge.derive_target_book(source,'main',plan).set_index('ticker')
        self.assertAlmostEqual(out.loc['AAA','target_weight'],.47)
        self.assertAlmostEqual(out.loc['BBB','target_weight'],.5)
        self.assertAlmostEqual(out.loc['CASH','target_weight'],.03)
        reserve_reason_reconciliation(out.reset_index(),policy=policy,weight_col='target_weight')
        pd.testing.assert_frame_equal(source,before)
        for declarations in (['','','d'*64],[valid,'','d'*64]):
            with self.subTest(declarations=declarations):
                bad=source.copy();bad[RESERVE_REASON_SOURCE_HASH_FIELD]=declarations
                with self.assertRaises(ValueError):bridge.derive_target_book(bad,'main',plan)
        extra=pd.concat([source,pd.DataFrame({'ticker':['ZERO'],'target_weight':[0.],RESERVE_REASON_SOURCE_HASH_FIELD:['d'*64]})],ignore_index=True)
        with self.assertRaises(ValueError):bridge.derive_target_book(extra,'main',plan)

    def test_numeric_actions_require_exact_portfolio_scope(self):
        missing=copy.deepcopy(self.monitor);missing['paper_action_candidates'][-1].pop('portfolio_kind')
        with self.assertRaises(ValueError):bridge.action_plan(missing,'main')
        main=bridge.action_plan(self.monitor,'main');other=bridge.action_plan(self.monitor,'concentrated')
        self.assertEqual(main['trim_tickers']['AAA']['current_weight'],.20)
        self.assertEqual(other['trim_tickers']['AAA']['current_weight'],.40)
        with self.assertRaises(ValueError):bridge.derive_target_book(self.target,'main',other)

    def test_missing_or_blank_accepted_reserve_hash_is_not_derived_proof(self):
        plan=bridge.action_plan(self.monitor,'main')
        for value in (None,'','nan','d'*63):
            bad=self.target.drop(columns=[RESERVE_REASON_SOURCE_HASH_FIELD]) if value is None else self.target.assign(**{RESERVE_REASON_SOURCE_HASH_FIELD:value})
            with self.subTest(value=value):
                with self.assertRaises(ValueError):bridge.derive_target_book(bad,'main',plan)
                path=self.latest/'reports/operating_main_target_book.csv';bad.to_csv(path,index=False)
                self.proof['portfolios']['main']['target_sha256']=sha(path.read_bytes());self.bind()
                with patch.object(clock,'trusted_now',return_value=self.now):
                    with self.assertRaises(ValueError):bridge.checked_inputs(self.args,self.latest,self.monitor_path.read_bytes())

    def test_account_portfolio_identity_cannot_be_relabelled_by_manifest(self):
        path=self.latest/'broker_replay/main/account_state_latest.json';original=json.loads(path.read_bytes())
        for identity in (None,'concentrated','MAIN'):
            bad=copy.deepcopy(original)
            if identity is None:bad.pop('portfolio_kind')
            else:bad['portfolio_kind']=identity
            path.write_text(json.dumps(bad));self.proof['portfolios']['main']['account_sha256']=sha(path.read_bytes());self.bind()
            with patch.object(clock,'trusted_now',return_value=self.now):
                with self.assertRaisesRegex(ValueError,'ACCOUNT_PORTFOLIO_IDENTITY_REQUIRED'):
                    bridge.checked_inputs(self.args,self.latest,self.monitor_path.read_bytes())

    def test_price_artifacts_must_match_all_consumed_cache_bytes(self):
        baseline=copy.deepcopy(self.proof)
        for change in ('missing','hash','size','path','extra'):
            self.proof=copy.deepcopy(baseline);prices=self.proof['portfolios']['main']['prices']
            if change=='missing':prices.pop('AAA')
            elif change=='hash':prices['AAA']['sha256']='d'*64
            elif change=='size':prices['AAA']['byte_count']+=1
            elif change=='path':prices['AAA']['relative_path']='../unbound.parquet'
            else:prices['UNBOUND']=copy.deepcopy(prices['AAA'])
            self.bind()
            with self.subTest(change=change),patch.object(clock,'trusted_now',return_value=self.now):
                with self.assertRaises(ValueError):bridge.checked_inputs(self.args,self.latest,self.monitor_path.read_bytes())
        self.proof=copy.deepcopy(baseline);self.bind();path=self.cache/bridge.px_cache_name('AAA');path.write_bytes(b'changed-after-pin')
        with patch.object(clock,'trusted_now',return_value=self.now):
            with self.assertRaises(ValueError):bridge.checked_inputs(self.args,self.latest,self.monitor_path.read_bytes())

    def test_bound_price_copy_and_broker_provenance_survive_source_changes(self):
        with patch.object(clock,'trusted_now',return_value=self.now):
            prepared=bridge.checked_inputs(self.args,self.latest,self.monitor_path.read_bytes())
        original_account=(self.latest/'broker_replay/main/account_state_latest.json').read_bytes()
        captured={}
        def inspect(args):
            self.assertEqual(args.account_source_kind,'simulated_broker_replay')
            self.assertIn('broker_replay',str(args.account_state))
            self.assertEqual(Path(args.account_state).read_bytes(),original_account)
            self.assertNotEqual(Path(args.price_cache).resolve(),self.cache.resolve())
            for ticker,spec in self.price_proof.items():
                self.assertEqual(sha((Path(args.price_cache)/spec['relative_path']).read_bytes()),spec['sha256'])
            captured['scratch']=str(Path(args.account_state).parent)
            return self.fake_preview(args)
        for p in self.cache.iterdir():p.write_bytes(b'changed-original-after-preflight')
        (self.latest/'broker_replay/main/account_state_latest.json').write_text('{"changed":true}')
        with patch.object(bridge,'ACTUAL_PREVIEW_ACTIVATED',True),patch.object(bridge,'run_order_preview',side_effect=inspect):
            result=bridge.run_preview_for_portfolio(latest_run=self.latest,price_cache=self.cache,output_dir=self.output,
                portfolio='main',plan=bridge.action_plan(self.monitor,'main'),cost_bps=25.,
                prepared=prepared['portfolios']['main'],report_session='2026-01-02')
        self.assertEqual(result['account_source_kind'],'simulated_broker_replay')
        self.assertEqual(result['price_artifact_sha256'],{x['relative_path']:x['sha256'] for x in self.price_proof.values()})
        self.assertFalse(Path(captured['scratch']).exists())
        self.assertIs(bridge.ACTUAL_PREVIEW_ACTIVATED,False)

    def test_bound_price_requires_exact_finite_report_session_close_before_preview(self):
        day=pd.DatetimeIndex(['2026-01-02'])
        invalid=[pd.DataFrame({'Close':[100.]},index=pd.DatetimeIndex(['2025-12-31'])),
                 pd.DataFrame({'Close':[100.]},index=pd.DatetimeIndex(['2026-01-05'])),
                 pd.DataFrame({'Close':pd.Series(dtype=float)},index=pd.DatetimeIndex([])),
                 pd.DataFrame({'unrelated':[100.]},index=day),
                 pd.DataFrame({'Close':[100.,101.]},index=pd.DatetimeIndex(['2026-01-02','2026-01-02'])),
                 pd.DataFrame({'Close':[100.],'Adj Close':[float('nan')]},index=day)]
        invalid.extend(pd.DataFrame({'Close':[value],'Open':[100.]},index=day)
                       for value in (float('nan'),float('inf'),0.,-1.,'bad-close'))
        for frame in invalid:
            with self.subTest(columns=list(frame.columns),rows=len(frame)):
                self.replace_price('AAA',frame)
                with patch.object(clock,'trusted_now',return_value=self.now):
                    with self.assertRaises((ValueError,OSError)):
                        bridge.checked_inputs(self.args,self.latest,self.monitor_path.read_bytes())
                with patch.object(bridge,'ACTUAL_PREVIEW_ACTIVATED',True):self.run_blocked()
        self.replace_price('AAA',raw=b'corrupt-parquet-with-valid-external-hash')
        with patch.object(clock,'trusted_now',return_value=self.now):
            with self.assertRaises((ValueError,OSError)):
                bridge.checked_inputs(self.args,self.latest,self.monitor_path.read_bytes())

    def test_exact_close_matches_engine_basis_and_includes_held_only_tickers(self):
        self.replace_price('AAA',pd.DataFrame({'Close':[100.,1000.],'Adj Close':[80.,800.]},
            index=pd.DatetimeIndex(['2026-01-02','2026-01-05'])))
        with patch.object(clock,'trusted_now',return_value=self.now):
            prepared=bridge.checked_inputs(self.args,self.latest,self.monitor_path.read_bytes())
        item=prepared['portfolios']['main']['price_artifacts'][bridge.px_cache_name('AAA')]
        self.assertEqual(item['report_session'],'2026-01-02');self.assertEqual(item['close'],80.)
        account_path=self.latest/'broker_replay/main/account_state_latest.json'
        account=json.loads(account_path.read_bytes());account['positions'].append(dict(ticker='CCC',shares=1.,cost_basis=10.))
        account_path.write_text(json.dumps(account));entry=self.proof['portfolios']['main']
        entry['account_sha256']=sha(account_path.read_bytes());entry['economics']['CCC']=copy.deepcopy(entry['economics']['AAA'])
        entry['prices']['CCC']={}
        self.replace_price('CCC',pd.DataFrame({'Close':[10.]},index=pd.DatetimeIndex(['2025-12-31'])))
        with patch.object(clock,'trusted_now',return_value=self.now):
            with self.assertRaisesRegex(ValueError,'EXACT_REPORT_SESSION_PRICE_REQUIRED'):
                bridge.checked_inputs(self.args,self.latest,self.monitor_path.read_bytes())
        self.replace_price('CCC',pd.DataFrame({'Close':[11.]},index=pd.DatetimeIndex(['2026-01-02'])))
        with patch.object(clock,'trusted_now',return_value=self.now):
            prepared=bridge.checked_inputs(self.args,self.latest,self.monitor_path.read_bytes())
        self.assertEqual(prepared['portfolios']['main']['price_artifacts'][bridge.px_cache_name('CCC')]['close'],11.)

    def test_cli_blocked_exit_status(self):
        with patch.object(bridge,'run',return_value=dict(status='blocked')):
            self.assertEqual(bridge.main([]),2)


def test_crisis_paper_order_bridge_requires_approval_and_blocks_new_buys():
    result=unittest.TextTestRunner().run(unittest.defaultTestLoader.loadTestsFromTestCase(BridgeTests))
    if not result.wasSuccessful():raise RuntimeError('B2_FIXTURE_FAILED')

if __name__=='__main__':
    test_crisis_paper_order_bridge_requires_approval_and_blocks_new_buys()
    print('crisis_paper_order_bridge_smoke: PASS; synthetic fixtures/mock preview only')
