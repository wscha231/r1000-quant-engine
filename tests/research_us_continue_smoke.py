import copy
from datetime import date,timedelta
import json
import os
from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tools'))
import research_rs_horizons as rs
import research_us_fund_replay as us_fund
import research_us_decision as us_decision
from research_interim_financials import normalize
from extend_us_rs_history import merge_histories
from tools.research_decision_v1 import data,fund_replay
from research_fund_replay_smoke import fixture
from research_decision_v1_fixture import bundle


class Continuation(unittest.TestCase):
    def test_extended_window_requires_consistent_raw_overlap(self):
        old=[dict(t=f'2025-04-{i:02d}T04:00:00Z',c=100.+i) for i in range(1,16)]
        current={'raw':{'SPY':copy.deepcopy(old[5:])},'all':{'SPY':copy.deepcopy(old[5:])}}
        earlier={'raw':{'SPY':copy.deepcopy(old)},'all':{'SPY':[dict(r,c=r['c']/2) for r in old]}}
        joined,status=merge_histories(current,earlier,'2025-04-06')
        self.assertEqual(status['SPY'],'extended')
        self.assertEqual(joined['all']['SPY'],old)
        earlier['raw']['SPY'][-1]['c']*=3
        joined,status=merge_histories(current,earlier,'2025-04-06')
        self.assertEqual(status['SPY'],'source_overlap_conflict')
        self.assertEqual(joined,current)

    def test_interim_revision_is_available_only_after_its_observation(self):
        registry=json.loads((ROOT/'docs/research_interim_financials_20260910.json').read_text())
        original=normalize(registry,'ASML','2026-09-11T00:00:00Z')
        changed=copy.deepcopy(next(r for r in registry['records'] if r['ticker']=='ASML'))
        changed['observed_at']='2026-09-12T00:00:00Z';changed['values']['revenue']+=1
        registry['records'].append(changed)
        self.assertEqual(normalize(registry,'ASML','2026-09-11T00:00:00Z'),original)
        self.assertEqual(normalize(registry,'ASML','2026-09-13T00:00:00Z')['ttm_company_totals']['revenue'],
            original['ttm_company_totals']['revenue']+1000000)

    def test_us_entrypoint_rejects_legacy_profile_before_loading_inputs(self):
        config=json.loads((ROOT/'docs/research_decision_v1_config.json').read_text())
        self.assertRaisesRegex(ValueError,'us_market_profile_required',us_decision.run_decisions,[],{},config)

    def test_interim_observation_not_backdated_or_mixed_across_currency(self):
        registry=json.loads((ROOT/'docs/research_interim_financials_20260910.json').read_text())
        self.assertEqual(normalize(registry,'ASML','2026-09-09T23:59:59Z')['status'],'MISSING')
        r=normalize(registry,'ASML','2026-09-11T00:00:00Z')
        self.assertEqual(r['status'],'CURRENT_TTM_NORMALIZED')
        self.assertAlmostEqual(r['ttm_company_totals']['operating_cash_flow'],11486800000.)
        self.assertFalse(r['historical_use_allowed'])
        next(r for r in registry['records'] if r['ticker']=='ASML')['currency']='USD'
        self.assertIsNone(normalize(registry,'ASML','2026-09-11T00:00:00Z')['ttm_company_totals'])

    def test_interim_missing_quarter_cannot_be_annualized(self):
        registry=json.loads((ROOT/'docs/research_interim_financials_20260910.json').read_text())
        registry['records']=[r for r in registry['records'] if r['period_end']!='2026-03-31']
        self.assertIsNone(normalize(registry,'TSM','2026-09-11T00:00:00Z')['ttm_company_totals'])

    def prices(self):
        start=date(2024,1,1)
        rows=[dict(t=(start+timedelta(days=i)).isoformat()+'T04:00:00Z',c=100.+i) for i in range(530)]
        stocks={'SPY':rows,'AAA':[dict(r,c=r['c']**1.2) for r in rows],'BBB':copy.deepcopy(rows)}
        members=[dict(ticker=t,market='US',sector='Industry',candidate_origins=['US_IWB']) for t in ('AAA','BBB')]
        return stocks,members,rows[-1]['t'][:10]

    def test_every_candidate_every_horizon_and_ties(self):
        stocks,members,end=self.prices();r=rs.analyze(stocks,members,end)
        self.assertEqual(r['candidate_count'],2)
        self.assertTrue(all(n==2 for n in r['coverage'].values()))
        self.assertEqual(r['rows'][0]['strength']['long'],'outperforming')
        self.assertEqual(r['rows'][1]['horizons']['20']['market_percentile'],0.)
        values=[dict(x=1.),dict(x=1.),dict(x=2.)];rs.percentiles(values,'x')
        self.assertEqual(values[0]['percentile'],values[1]['percentile'])

    def test_gap_and_short_history_not_filled_or_ranked(self):
        stocks,members,end=self.prices();stocks['AAA'].pop(-10);stocks['BBB']=stocks['BBB'][-100:]
        r=rs.analyze(stocks,members,end)
        self.assertEqual(r['rows'][0]['horizons']['20']['status'],'missing')
        self.assertEqual(r['rows'][1]['strength']['long'],'insufficient_history')
        self.assertNotIn('market_percentile',r['rows'][0]['horizons']['20'])

    def test_future_observation_cannot_change_past_rs(self):
        stocks,members,end=self.prices();before=rs.analyze(stocks,members,end)
        stocks['AAA'].append(dict(t='2030-01-01T00:00:00Z',c=999999.))
        self.assertEqual(before,rs.analyze(stocks,members,end))

    def test_us_profile_runs_through_real_fund_engine_with_next_close_costs(self):
        spec,events,packets=fixture()
        cfg=json.loads((ROOT/'docs/research_us_fund_config.json').read_text())
        spec['decision_config_hash']=data.digest(cfg)
        for packet in packets.values():packet['context']['fx']={'status':'missing'}
        r=us_fund.replay(spec,events,cfg,lambda ref:copy.deepcopy(packets[ref]),now='2026-09-10T02:00:00Z')
        self.assertEqual(r['status'],'COMPLETED_RESEARCH_REPLAY',r)
        self.assertGreater(r['metrics']['trade_count'],0)
        self.assertGreater(r['metrics']['transaction_cost_usd'],0)
        self.assertTrue(all(row.get('time','')>row.get('decision_time','') for row in r['trades'] if row['status']=='FILLED'))
        self.assertFalse(r['historical_pit_certified'])
        spec['markets']=['US','KR']
        blocked=us_fund.replay(spec,events,cfg,lambda ref:packets[ref])
        self.assertEqual(blocked['reason'],'fund_us_profile_scope')

    def test_archive_retrieval_is_separate_from_publication_and_not_a_judgment_bypass(self):
        b=bundle();s=b['securities'][0];block=s['blocks']['financials'];cut=b['decision_cutoff']
        block.update(evidence_mode='ARCHIVE_RECONSTRUCTION',first_seen_at='2026-09-10T00:00:00Z',ingested_at='2026-09-10T00:01:00Z')
        block['archive_version']=dict(kind='ORIGINAL_FILING',raw_sha256='a'*64,source='https://www.sec.gov/Archives/example',
            public_available_at=block['public_available_at'],retrieved_at=block['first_seen_at'])
        self.assertEqual(data.envelope_errors(block,s,cut),[])
        block['published_at']='2026-09-09T00:00:00Z'
        self.assertIn('published_at_after_cutoff',data.envelope_errors(block,s,cut))
        block['published_at']='2026-08-01T00:00:00Z';block['unit']='text'
        self.assertIn('archive_judgment_not_allowed',data.envelope_errors(block,s,cut))

    def test_unversioned_late_macro_still_blocked(self):
        r=dict(source='https://api.stlouisfed.org',published_at='2020-01-01T00:00:00Z',
            observed_at='2026-09-10T00:00:00Z',value=.02,payload_hash=data.digest(.02))
        self.assertRaises((ValueError,TypeError),fund_replay.scalar_evidence,r,'2020-02-01T00:00:00Z',evidence_mode='RETROSPECTIVE_RECONSTRUCTION')
        r['archive_version']=dict(kind='ORIGINAL_RELEASE',source=r['source'],published_at=r['published_at'],retrieved_at=r['observed_at'],raw_sha256='a'*64)
        self.assertEqual(fund_replay.scalar_evidence(r,'2020-02-01T00:00:00Z',evidence_mode='RETROSPECTIVE_RECONSTRUCTION'),.02)

if __name__=='__main__':unittest.main()
