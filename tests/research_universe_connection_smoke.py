"""Broad membership provenance, selection bias and temporal regressions."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import research_source_connection as source
import research_universe_connection as m


def iwb(day='Sep 09, 2026',rows=None):
    rows=rows or ['BRK B,Berkshire,Financials,Equity,NYSE,USD',
                  'ABC,Example,Health Care,Equity,NASDAQ,USD',
                  'USD,Cash,Cash,Cash,NYSE,USD']
    return ('iShares Russell 1000 ETF\nFund Holdings as of,"'+day+'"\n'
            'Ticker,Name,Sector,Asset Class,Exchange,Market Currency\n'+'\n'.join(rows)+'\n\nDisclaimer\n').encode()


def krrow(ticker,day='20260909',close='10,000',volume='0'):
    return dict(ISU_CD=ticker,ISU_NM='Example',BAS_DD=day,TDD_CLSPRC=close,ACC_TRDVOL=volume)


class Universe(unittest.TestCase):
    def test_sample_origin_matches_existing_monitor_not_quantitative_rank(self):
        r=m.connection_sample()
        self.assertEqual({k:len(v) for k,v in r['symbols'].items()},{'US':24,'KR':9})
        self.assertIsNone(r['quantitative_selection_rule'])
        self.assertFalse(r['historical_selection_allowed'])

    def test_iwb_date_class_and_sector_are_preserved(self):
        r=m.parse_iwb(iwb(),'2026-09-09')
        self.assertEqual([m['ticker'] for m in r['members']],['BRK.B','ABC'])
        self.assertEqual(r['excluded'],{'non_equity':1})
        self.assertEqual(r['sector_counts'],{'Financials':1,'Health Care':1})
        self.assertTrue(r['exact_requested_date']);self.assertFalse(r['historical_selection_allowed'])

    def test_current_iwb_cannot_be_relabelled_as_2019(self):
        self.assertRaisesRegex(ValueError,'future_membership',m.parse_iwb,iwb(),'2019-05-31')

    def test_stale_membership_keeps_actual_date(self):
        r=m.parse_iwb(iwb('Sep 08, 2026'),'2026-09-09')
        self.assertEqual(r['membership_as_of'],'2026-09-08');self.assertFalse(r['exact_requested_date'])

    def test_duplicate_or_unresolved_symbols_not_silently_ranked(self):
        self.assertRaisesRegex(ValueError,'duplicate_member',m.parse_iwb,
            iwb(rows=['ABC,A,Tech,Equity,NYSE,USD','ABC,B,Tech,Equity,NYSE,USD']),'2026-09-09')
        r=m.parse_iwb(iwb(rows=['ABC,A,Tech,Equity,NYSE,USD','??,B,Tech,Equity,NYSE,USD']),'2026-09-09')
        self.assertEqual(r['excluded']['unresolved_symbol'],1)

    def test_kr_halted_names_remain_in_universe_and_future_day_fails(self):
        r=m.parse_krx({'OutBlock_1':[krrow('000010'),krrow('000020',close='-')]},'2026-09-09','KOSDAQ')
        self.assertEqual(len(r['members']),2)
        self.assertFalse(r['members'][0]['has_positive_trade']);self.assertIsNone(r['members'][1]['close'])
        self.assertRaisesRegex(ValueError,'krx_date',m.parse_krx,{'OutBlock_1':[krrow('000010')]},'2019-05-31','KOSDAQ')

    def test_historical_listing_ipo_and_delisting_contradictions_block(self):
        r=m.listing_temporal_audit([dict(ipoDate='2024-01-01',delistingDate='null',status='Active'),
            dict(ipoDate='2000-01-01',delistingDate='2018-01-01',status='Active')],'2019-05-31','active')
        self.assertFalse(r['temporal_consistency_pass'])
        self.assertEqual(r['temporal_issues'],{'ipo_after_requested_date':1,'delisted_by_requested_date':1})
        self.assertFalse(r['historical_universe_verified'])

    def test_date_consistency_alone_does_not_certify_historical_completeness(self):
        r=m.listing_temporal_audit([dict(ipoDate='2000-01-01',delistingDate='null',status='Active')],'2019-05-31','active')
        self.assertTrue(r['temporal_consistency_pass']);self.assertFalse(r['historical_universe_verified'])

    def test_current_and_historical_kr_snapshots_are_not_union_backfilled(self):
        def board(c,end,b):
            return m.parse_krx({'OutBlock_1':[krrow(('000010' if b=='KOSPI' else '000020')
                if end=='2019-05-31' else ('111110' if b=='KOSPI' else '111120'),day=end.replace('-',''))]},end,b)
        with tempfile.TemporaryDirectory() as d,patch.object(m,'collect_iwb',side_effect=OSError),patch.object(m,'collect_kr_board',side_effect=board):
            r=m.collect_current_universe(source.Capture(d),'2026-09-09','2019-05-31')
        self.assertEqual({x['ticker'] for x in r['members']},{'111110','111120'})
        self.assertEqual({x['ticker'] for s in r['historical_probes'] for x in s['data']['members']},{'000010','000020'})
        self.assertFalse(r['source_coverage_complete'])
        self.assertFalse(r['continuous_historical_membership_verified'])

    def test_broad_mode_never_falls_back_to_33_on_source_failure(self):
        with tempfile.TemporaryDirectory() as d,patch.object(source,'request_raw',side_effect=OSError),patch.object(m,'connection_sample',side_effect=AssertionError('sample fallback')):
            r=source.run(d,'2025-05-01','2026-09-09')
        self.assertEqual(r['universe']['members'],[]);self.assertIsNone(r['portfolio_weights'])

    def test_price_collection_batches_over_33_without_truncation(self):
        symbols=['SYM'+str(i) for i in range(107)]
        calls=[]
        def request(base,params,headers):
            batch=params['symbols'].split(',');calls.append(batch)
            return json.dumps({'bars':{s:[{'t':'2026-09-09T04:00:00Z','c':10}] for s in batch}}).encode()
        with tempfile.TemporaryDirectory() as d,patch.object(source,'key',return_value='test'),patch.object(source,'request_raw',side_effect=request):
            r=source.collect_bars(source.Capture(d),'2026-09-08','2026-09-09',symbols)
        self.assertEqual(len(calls),6);self.assertEqual(len(r['securities']),107)
        self.assertEqual({x['ticker'] for x in r['securities']},set(symbols))

    def test_public_summary_does_not_publish_full_inventory(self):
        result=dict(members=[dict(ticker='PRIVATE',market='US')],sources=[],historical_probes=[])
        self.assertNotIn('PRIVATE',json.dumps(m.summarize_universe(result)))
        self.assertEqual(m.summarize_universe(result)['member_count'],1)


if __name__=='__main__':unittest.main()
