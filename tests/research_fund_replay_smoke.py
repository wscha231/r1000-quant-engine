"""Synthetic full H1 -> quality -> USD fund regressions. No return-performance claim."""
from __future__ import annotations
import copy
import importlib.util
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from tools.research_decision_v1 import data, engine, portfolio, currency, fund_replay as replay
from tools.research_decision_v1 import fund_metrics
from research_decision_v1_decision_fixture import with_scenario, context as old_context
from research_workflow_quality_smoke import quality_entry
from research_quality_v1_smoke import receipt

CFG=json.loads((ROOT/'docs/research_fund_replay_config.json').read_text())
SOURCE='https://fixture.example.org/fund'
START='2026-09-08T15:45:00Z'


def scalar(value,stamp):
    return {'source':SOURCE,'value':value,'payload_hash':data.digest(value),'published_at':stamp,'observed_at':stamp}


def close(day,price=100.,market='US',sid='US:TEST',fx=1300.):
    stamp=data.session_close(market,day).isoformat()
    return {'type':'close','time':stamp,'market':market,'session':day,'source':SOURCE,
            'available_at':stamp,'price_basis':'raw_unadjusted','corporate_actions_through':day,
            'corporate_actions':[],'fx':scalar(fx,stamp),'risk_free':scalar(.04,stamp),
            'benchmark_total_return_index':100.,
            'quotes':[{'security_id':sid,'close':price,'volume':1000000.,'tradable':True}]}


def packet(cutoff=START,latest_price=100.,fx=1300.):
    b=with_scenario('US','TEST');b['decision_cutoff']=cutoff
    s=b['securities'][0]
    for block in s['blocks'].values(): block['decision_cutoff']=cutoff
    last=data.sessions('US','2026-09-01',cutoff)[-1]
    p=s['blocks']['price'];bars=p['payload']['bars']
    if bars[-1]['session'] != last:
        bars.append(dict(bars[-1],session=last,close=latest_price))
    else: bars[-1]['close']=latest_price
    p['payload']['benchmark_bars']=copy.deepcopy(bars)
    for bar in p['payload']['benchmark_bars']: bar['close']=100.
    p['payload']['corporate_actions_through']=last;p['payload']['benchmark_actions_through']=last
    p.update(public_available_at=cutoff,first_seen_at=cutoff,ingested_at=cutoff,
             report_period={'start':bars[0]['session'],'end':last},data_hash=data.digest(p['payload']))
    sc=s['blocks']['scenario'];day=cutoff[:10];target=str(int(day[:4])+1)+day[4:]
    sc['report_period']={'start':day,'end':target};sc['payload']['target_date']=target
    sc['data_hash']=data.digest(sc['payload'])
    exported=data.export_market(b,'US')
    ctx=old_context();ctx['decision_cutoff']=cutoff
    ctx['fx'].update(spot=fx,observed_at=cutoff,scenario_rates={'Bear':fx,'Base':fx,'Bull':fx})
    ctx['regime'].update(observed_at=cutoff,state='RISK_ON')
    macro=[dict(scalar(2.,'2026-09-04T12:00:00Z'),vintage_at='2026-09-04T12:00:00Z',series='synthetic_growth')]
    ctx['regime']['input_hash']=data.digest(macro)
    members=['US:TEST']
    quality={'schema_version':'research-quality-bundle-v1','data_kind':'SYNTHETIC',
             'decision_cutoff':cutoff,'assessments':{'US:TEST':quality_entry('US:TEST')}}
    return {'data_kind':'SYNTHETIC','decision_cutoff':cutoff,'market_exports':[exported],
            'context':ctx,'quality_bundle':quality,'macro':macro,
            'universe':{'source':SOURCE,'public_available_at':'2026-09-04T12:00:00Z',
                        'members':members,'members_hash':data.digest(members)}}


def fixture(second=True):
    spec={'schema_version':replay.SCHEMA,'data_kind':'SYNTHETIC','base_currency':'USD',
          'initial_cash_usd':100000.,'start_at':START,'end_date':'2026-09-09','markets':['US'],
          'decision_config_hash':data.digest(CFG),'selection_objective':fund_metrics.OBJECTIVE,
          'fill_mode':'next_close','cash_carry_mode':'none','evidence_mode':'RETROSPECTIVE_RECONSTRUCTION',
          'evaluation_scope':'MECHANICAL_PILOT',
          'decision_schedule':{'mode':'EXPLICIT_FROZEN','times':[START]+(['2026-09-09T15:45:00Z'] if second else [])},
          'cost_bps':{'US':25.},'fx_conversion_bps':0.,'max_pending_sessions':5,
          'benchmark_weights':{'US':1.},'opening_risk_free':scalar(.04,'2026-09-04T12:00:00Z'),
          'seed_closes':[close('2026-09-04')],'event_shards':[]}
    packets={'one':packet()}
    events=[{'type':'decision','time':START,'packet':'one'},close('2026-09-08',120.)]
    if second:
        packets['two']=packet('2026-09-09T15:45:00Z',120.)
        events.append({'type':'decision','time':'2026-09-09T15:45:00Z','packet':'two'})
    events.append(close('2026-09-09',125.))
    return spec,events,packets


def run(spec=None,events=None,packets=None):
    if spec is None: spec,events,packets=fixture()
    return replay.replay(spec,events,CFG,lambda ref:copy.deepcopy(packets[ref]),now='2026-09-10T02:00:00Z')


class FullFundTests(unittest.TestCase):
    def test_actual_h1_quality_and_account_advance(self):
        spec,events,packets=fixture()
        for p in packets.values():
            self.assertTrue(p['market_exports'][0]['securities'][0]['data_quality_pass'],p['market_exports'][0]['securities'][0]['blockers'])
        r=run(spec,events,packets)
        self.assertEqual(r['status'],'COMPLETED_RESEARCH_REPLAY',r)
        fills=[t for t in r['trades'] if t['status']=='FILLED']
        self.assertGreater(len(fills),1)
        first=fills[0];second=r['decisions'][1]['account_before']
        self.assertEqual(second['shares']['US:TEST'],first['quantity'])
        self.assertAlmostEqual(second['cash_usd'],first['cash_after_usd'])
        self.assertNotEqual(second['spendable_nav_usd'],100000.)
        self.assertEqual(first['price_local'],120.)
        self.assertEqual(fills[1]['side'],'SELL')
        self.assertTrue(all(data.timestamp(t['decision_at']) < data.timestamp(t['time']) for t in fills))
        self.assertGreater(r['final_cash_usd'],0.)
        self.assertAlmostEqual(sum(r['equity_curve'][-1]['cumulative_pnl_by_security_usd'].values()),r['metrics']['ending_capital_usd']-100000.)
        self.assertFalse(r['historical_pit_certified'])

    def test_future_price_change_cannot_change_earlier_order(self):
        spec,events,packets=fixture();a=run(spec,events,packets)
        events[-1]['quotes'][0]['close']=80.
        b=run(spec,events,packets)
        self.assertEqual(a['status'],b['status'])
        self.assertEqual(a['decisions'],b['decisions'])
        self.assertNotEqual(a['metrics']['ending_capital_usd'],b['metrics']['ending_capital_usd'])

    def test_future_financial_revision_blocks_instead_of_cash_result(self):
        spec,events,packets=fixture()
        raw=packets['one']['market_exports'][0]['input_snapshot']
        raw['securities'][0]['blocks']['financials']['public_available_at']='2026-09-10T00:00:00Z'
        packets['one']['market_exports']=[data.export_market(raw,'US')]
        r=run(spec,events,packets)
        self.assertEqual(r['status'],'BLOCKED');self.assertIsNone(r['metrics'])

    def test_future_macro_and_vintage_rejected(self):
        for field in ('observed_at','vintage_at'):
            spec,events,packets=fixture()
            packets['one']['macro'][0][field]='2026-09-10T00:00:00Z'
            packets['one']['context']['regime']['input_hash']=data.digest(packets['one']['macro'])
            self.assertEqual(run(spec,events,packets)['status'],'BLOCKED')

    def test_missing_session_duplicate_and_reverse_clock_rejected(self):
        for mutation in ('missing','duplicate','reverse'):
            spec,events,packets=fixture(False)
            if mutation=='missing':events.pop(1)
            if mutation=='duplicate':events.insert(2,copy.deepcopy(events[1]))
            if mutation=='reverse':events.reverse()
            r=run(spec,events,packets)
            self.assertEqual(r['status'],'BLOCKED');self.assertIsNone(r['metrics'])

    def test_missing_held_price_is_not_forward_filled_on_open_market(self):
        spec,events,packets=fixture(False);events[-1]['quotes']=[]
        self.assertEqual(run(spec,events,packets)['reason'],'fund_held_or_pending_price_missing')

    def test_last_day_order_remains_pending_no_forced_final_sale(self):
        spec,events,packets=fixture(False)
        p=packet('2026-09-09T20:01:00Z',125.)
        # Build the last completed price row for this later cutoff.
        raw=p['market_exports'][0]['input_snapshot'];price=raw['securities'][0]['blocks']['price']
        price['payload']['bars'].insert(-1,dict(price['payload']['bars'][-1],session='2026-09-08',close=120.))
        price['payload']['benchmark_bars'].insert(-1,dict(price['payload']['benchmark_bars'][-1],session='2026-09-08',close=100.))
        price['data_hash']=data.digest(price['payload']);p['market_exports']=[data.export_market(raw,'US')]
        packets['last']=p;events.append({'type':'decision','time':p['decision_cutoff'],'packet':'last'})
        spec['decision_schedule']['times'].append(p['decision_cutoff'])
        r=run(spec,events,packets)
        self.assertEqual(r['status'],'COMPLETED_RESEARCH_REPLAY',r)
        self.assertTrue(r['pending_after_cutoff'])
        self.assertTrue(r['final_holdings']['US:TEST']>0)

    def test_gapped_price_cannot_borrow_cash(self):
        spec,events,packets=fixture(False);events[1]['quotes'][0]['close']=10000.
        r=run(spec,events,packets)
        self.assertEqual(r['status'],'COMPLETED_RESEARCH_REPLAY',r)
        self.assertGreaterEqual(min(row['cash_usd'] for row in r['equity_curve']),0.)
        self.assertTrue(any(t['quantity']<t['target_quantity'] for t in r['trades'] if t['status']=='FILLED'))

    def test_blocked_quality_and_mismatched_config_remain_blocked(self):
        spec,events,packets=fixture();packets['one']['quality_bundle']['assessments']={}
        self.assertEqual(run(spec,events,packets)['status'],'BLOCKED')
        spec,events,packets=fixture();spec['cost_bps']['US']=0.
        self.assertEqual(run(spec,events,packets)['reason'],'fund_cost_mismatch')
        for kind in ([],{},'untrusted input text'):
            spec,events,packets=fixture();spec['data_kind']=kind
            result=run(spec,events,packets)
            self.assertEqual(result['status'],'BLOCKED');self.assertIsNone(result['data_kind'])

    def test_end_after_now_and_missing_decisions_rejected(self):
        spec,events,packets=fixture(False)
        self.assertEqual(replay.replay(spec,events,CFG,packets.get,now='2026-09-09T12:00:00Z')['status'],'BLOCKED')
        events=[e for e in events if e['type']=='close']
        self.assertEqual(run(spec,events,packets)['reason'],'fund_decision_schedule_incomplete')

    def test_full_history_label_cannot_certify_short_or_synthetic_run(self):
        spec,events,packets=fixture();spec['evaluation_scope']='FULL_7_8_YEAR'
        self.assertEqual(run(spec,events,packets)['reason'],'fund_full_history_length_or_kind')

    def test_verified_adverse_quality_exits_without_becoming_missing_data(self):
        spec,events,packets=fixture()
        entry=packets['two']['quality_bundle']['assessments']['US:TEST']
        entry['packet']['claims'][4].update(impact='adverse',severity='critical')
        entry['receipt']=receipt(entry['packet'],entry['corpus'])
        r=run(spec,events,packets)
        self.assertEqual(r['status'],'COMPLETED_RESEARCH_REPLAY',r)
        self.assertEqual(r['final_holdings'].get('US:TEST',0.),0.)
        self.assertTrue(any('fund_reviewed_quality_exit' in t.get('reasons',[]) for t in r['trades']))

    def test_membership_exit_keeps_risk_evidence_and_liquidates(self):
        spec,events,packets=fixture()
        packets['two']['universe'].update(members=[],members_hash=data.digest([]))
        r=run(spec,events,packets)
        self.assertEqual(r['status'],'COMPLETED_RESEARCH_REPLAY',r)
        self.assertEqual(r['final_holdings'].get('US:TEST',0.),0.)

    def test_streaming_archive_preserves_identical_account_result(self):
        spec,events,packets=fixture();saved=[]
        original=run(spec,events,packets)
        def sink(record,packet):
            saved.append(copy.deepcopy((record,packet)))
            return {'record_hash':data.digest(record),'packet_hash':data.digest(packet)}
        streamed=replay.replay(spec,iter(events),CFG,packets.get,now='2026-09-10T02:00:00Z',decision_sink=sink)
        self.assertEqual(streamed['status'],'COMPLETED_RESEARCH_REPLAY',streamed)
        self.assertEqual(streamed['equity_curve'],original['equity_curve'])
        self.assertEqual(streamed['event_hash'],original['event_hash'])
        self.assertEqual(len(saved),2)
        self.assertNotIn('decision',streamed['decisions'][0])

    def test_daily_schedule_cannot_skip_a_bad_decision_day(self):
        spec,events,packets=fixture(False)
        spec['decision_schedule']={'mode':'DAILY_AFTER_LAST_CLOSE'}
        self.assertEqual(run(spec,events,packets)['reason'],'fund_decision_schedule_incomplete')

    def test_usd_only_fund_does_not_require_unrelated_krw_feed(self):
        spec,events,packets=fixture()
        for event in spec['seed_closes']+events:
            event.pop('fx',None)
        for p in packets.values():p['context'].pop('fx')
        r=run(spec,events,packets)
        self.assertEqual(r['status'],'COMPLETED_RESEARCH_REPLAY',r)


class AccountingTests(unittest.TestCase):
    def fund(self):
        spec,_,_=fixture(False);f=replay.Fund(spec,CFG)
        f.close(spec['seed_closes'][0],seed=True)
        f.shares={'US:TEST':500.};f.cash=50000.;f.net_cash_flow={'US:TEST':-50000.}
        return f

    def action(self,kind,**kwargs):
        return dict(action_id='A'+kind,security_id='US:TEST',kind=kind,source=SOURCE,
                    public_available_at='2026-09-04T12:00:00Z',effective_at='2026-09-08T13:30:00Z',**kwargs)

    def test_split_and_dividend_not_double_counted_or_spent_early(self):
        f=self.fund();event=close('2026-09-08',48.)
        event['corporate_actions']=[self.action('SPLIT',ratio=2.),self.action('DIVIDEND',cash_per_share=2.,pay_at='2026-09-09T12:00:00Z')]
        f.close(event)
        nav,_,rights=f.equity()
        self.assertEqual(f.shares['US:TEST'],1000.)
        self.assertEqual(f.cash,50000.);self.assertEqual(rights,2000.);self.assertEqual(nav,100000.)
        f.close(close('2026-09-09',48.))
        self.assertEqual(f.cash,52000.);self.assertEqual(f.equity()[0],100000.)

    def test_cash_delisting_including_zero_recovery(self):
        for recovery in (0.,20.):
            f=self.fund();e=close('2026-09-08');e['quotes']=[]
            e['corporate_actions']=[self.action('CASH_DELIST',cash_per_share=recovery,pay_at='2026-09-09T12:00:00Z')]
            f.close(e)
            self.assertEqual(f.shares,{})
            self.assertEqual(f.equity()[0],50000.+500*recovery)

    def test_reverse_split_fraction_receivable(self):
        f=self.fund();f.shares['US:TEST']=501.
        e=close('2026-09-08',200.)
        e['corporate_actions']=[self.action('SPLIT',ratio=.5,cash_in_lieu_price=200.,pay_at='2026-09-09T12:00:00Z')]
        f.close(e)
        self.assertEqual(f.shares['US:TEST'],250.)
        self.assertEqual(f.equity()[2],100.)

    def test_later_us_sale_cannot_fund_earlier_kr_close(self):
        spec,_,_=fixture(False)
        spec.update(markets=['KR','US'],cost_bps={'US':25.,'KR':25.},benchmark_weights={'US':.5,'KR':.5},
                    start_at='2026-09-08T01:00:00Z',seed_closes=[close('2026-09-04')])
        f=replay.Fund(spec,CFG);f.close(close('2026-09-04'),seed=True)
        f.cash=0.;f.shares={'US:TEST':100.}
        f.pending={sid:dict(security_id=sid,decision_at=spec['start_at'],target_quantity=qty,
                           attempted_sessions=0,capacity_local=1e9,reasons=[]) for sid,qty in [('US:TEST',0),('KR:999999',100)]}
        f.close(close('2026-09-08',10000.,market='KR',sid='KR:999999'))
        self.assertNotIn('KR:999999',f.shares);self.assertEqual(f.cash,0.)
        f.close(close('2026-09-08'))
        self.assertGreater(f.cash,0.)

    def test_raw_adjusted_confusion_rejected(self):
        f=self.fund();e=close('2026-09-08');e['price_basis']='split_adjusted'
        with self.assertRaisesRegex(ValueError,'raw_prices'):f.close(e)


class CurrencyAndObjectiveTests(unittest.TestCase):
    def test_usd_krw_fx_direction_and_no_mislabel(self):
        ctx={'base_currency':'USD','capital_base':100000.,'fx':{'spot':1000.,'scenario_rates':{'Bear':2000.,'Base':1000.,'Bull':500.}}}
        self.assertEqual(currency.scenario_fx_ratio(ctx,'USD','Bear'),1.)
        self.assertEqual(currency.scenario_fx_ratio(ctx,'KRW','Bear'),.5)
        self.assertEqual(currency.scenario_fx_ratio(ctx,'KRW','Bull'),2.)
        ctx['capital_krw']=100000.
        with self.assertRaisesRegex(ValueError,'ambiguous_capital'):currency.capital(ctx)

    def test_cagr_precedes_sharpe_within_risk_limit(self):
        def curve(values):
            return [{'time':t+'T00:00:00Z','equity_usd':v,'cash_usd':0.,'risk_free_return':0.} for t,v in zip(
                ['2020-01-01','2020-05-01','2020-09-01','2021-01-01'],values)]
        a=curve([100.,115.,108.,125.]);b=curve([100.,105.,110.,115.])
        self.assertGreater(fund_metrics.metrics(b)['sharpe'],fund_metrics.metrics(a)['sharpe'])
        result=fund_metrics.select_cagr_trial([{'trial_id':'A','curve':a},{'trial_id':'B','curve':b}],
            development_end='2021-01-01T00:00:00Z',test_start='2021-01-02T00:00:00Z',max_drawdown=-.25,registered_trial_ids=['A','B'])
        self.assertEqual(result['selected_trial_id'],'A')
        with self.assertRaisesRegex(ValueError,'future_data'):
            fund_metrics.select_cagr_trial([{'trial_id':'A','curve':a}],development_end='2020-09-01T00:00:00Z',
                test_start='2021-01-01T00:00:00Z',max_drawdown=-.25,registered_trial_ids=['A'])

    def test_initial_loss_counted_in_drawdown_and_actual_elapsed_cagr(self):
        curve=[{'time':'2020-01-01T00:00:00Z','equity_usd':100000.,'cash_usd':100000.,'risk_free_return':0.},
               {'time':'2021-01-01T00:00:00Z','equity_usd':90000.,'cash_usd':0.,'risk_free_return':.04}]
        m=fund_metrics.metrics(curve)
        self.assertAlmostEqual(m['max_drawdown'],-.1)
        self.assertAlmostEqual(m['cagr'],.9**(365.25/366)-1)
        self.assertTrue(m['unrecovered_drawdown'])

    def test_required_risk_reduction_and_legacy_default_separate(self):
        from research_workflow_funding_smoke import security,context,run_fixture
        s=security();ctx=context();ctx['regime']['state']='RISK_OFF'
        ctx.update(mode='EXISTING_BOOK_PROPOSAL',book={'source':SOURCE,'currency':'KRW','decision_cutoff':ctx['decision_cutoff'],
                   'verified_at':ctx['decision_cutoff'],'positions':{'US:EXAM':.3},'cash_weight':.7,'pending_orders':[]})
        old=run_fixture(ctx,s)
        self.assertFalse(old['portfolio_proposal']['ready'])
        new=run_fixture(ctx,s,CFG)
        self.assertTrue(new['portfolio_proposal']['ready'],new['portfolio_proposal'])
        self.assertEqual(new['portfolio_proposal']['rows'][0]['action'],'REDUCE')

    def test_hashed_shard_read_rejects_mutation(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'part.json';path.write_text('[1]')
            ref={'path':'part.json','sha256':data.digest([1])}
            self.assertEqual(replay.read_reference(folder,ref),[1])
            path.write_text('[2]')
            with self.assertRaisesRegex(ValueError,'hash'):replay.read_reference(folder,ref)
            with self.assertRaisesRegex(ValueError,'path'):replay.read_reference(folder,dict(ref,path='../part.json'))

    def test_pbo_uses_compound_returns_and_validates_shape(self):
        result=fund_metrics.cagr_selection_pbo({'A':[.03,-.01]*4,'B':[.005,.006]*4},blocks=4)
        self.assertEqual(result['objective'],'after_cost_usd_cagr')
        self.assertEqual(result['splits'],6)
        with self.assertRaises(ValueError):fund_metrics.cagr_selection_pbo({'A':[0.]*8,'B':[-1.]*8},blocks=4)


if __name__=='__main__':unittest.main(verbosity=2)
