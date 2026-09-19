"""Production bridge regression tests with no network or provider credentials."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('bridge', ROOT/'r1000_unified_universe.py')
b=importlib.util.module_from_spec(spec);spec.loader.exec_module(b)


class BridgeTests(unittest.TestCase):
    def test_missing_percentile_is_missing(self):
        r=b.percentile_rank(pd.Series([1,None,2,float('inf')]))
        self.assertTrue(pd.isna(r.iloc[1]) and pd.isna(r.iloc[3]))

    def test_no_fake_score_cap_or_forward_pe(self):
        row=b.build_synthetic_row('A',{'fh_peExclExtra_ttm':20},0,'Tech','A',{'rs_A':1},50)
        for key in ['score','score_model_core','score_total','model_score','market_cap_live','forward_pe_final']:
            self.assertIsNone(row[key])
        self.assertEqual(row['trailing_pe_ttm'],20)
        self.assertEqual(row['current_price_live'],50)
        self.assertFalse(row['ranking_eligible'])

    def test_true_zero_preserved(self):
        row=b.build_synthetic_row('A',{'fh_revenueGrowthQuarterlyYoy':0,'fh_epsGrowthQuarterlyYoy':0},0,None,None,{},1)
        self.assertEqual(row['sales_growth_yoy'],0)
        self.assertEqual(row['earnings_growth_final'],0)
        self.assertEqual(row['rs_benchmark_12m'],0)

    def test_missing_rs_not_zero(self):
        row=b.build_synthetic_row('A',{},None,None,None,{},None)
        self.assertIsNone(row['rs_benchmark_12m'])
        self.assertIsNone(row['current_price_live'])

    def test_all_1118_names_retained(self):
        universe=['T'+str(i) for i in range(1118)]
        inv,summary,compatible=b.reconcile_inventory(pd.DataFrame({'ticker':['T0'],'score':[1]}),universe)
        self.assertEqual(len(inv),1118)
        self.assertEqual(summary['unscored_securities'],1117)
        self.assertEqual(len(compatible),1)
        self.assertIsNone(summary['portfolio_weights'])

    def test_synthetic_input_not_laundered(self):
        frame=pd.DataFrame({'ticker':['A','B'],'score':[2,3], 'score_source':['model','finnhub_synthetic']})
        inv,s,valid=b.reconcile_inventory(frame,['A','B'])
        self.assertEqual(s['rejected_synthetic_rows'],1)
        self.assertEqual(s['missing_tickers'],['B'])
        self.assertEqual(valid['ticker'].tolist(),['A'])

    def test_outside_rows_do_not_inflate_coverage(self):
        frame=pd.DataFrame({'ticker':['A','OUTSIDE'],'score':[1,9]})
        _,s,_=b.reconcile_inventory(frame,['A','B'])
        self.assertEqual(s['existing_score_rows'],1)
        self.assertEqual(s['outside_requested_universe'],['OUTSIDE'])

    def test_duplicate_identity_rejected(self):
        with self.assertRaisesRegex(ValueError,'score_identity'):
            b.reconcile_inventory(pd.DataFrame({'ticker':['A',' a '],'score':[1,2]}),['A'])

    def test_bad_score_rejected_not_neutralized(self):
        frame=pd.DataFrame({'ticker':['A','B'],'score':[float('inf'),None]})
        _,s,_=b.reconcile_inventory(frame,['A','B'])
        self.assertEqual(s['unscored_securities'],2)

    def test_ineligible_score_cannot_be_promoted(self):
        frame=pd.DataFrame({'ticker':['A','B'],'score':[5,6],'ranking_eligible':[True,False]})
        _,s,valid=b.reconcile_inventory(frame,['A','B'])
        self.assertEqual(s['missing_tickers'],['B'])
        self.assertEqual(valid['ticker'].tolist(),['A'])

    def test_output_preserved_before_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder);source=folder/'source.csv';output=folder/'output.csv'
            source.write_text('ticker,score\nA,1\n');output.write_bytes(b'old-output-unchanged\n')
            universe=types.ModuleType('aggressive.universe');universe.load_universe=lambda _: (['A']+['T'+str(i) for i in range(1117)],{'source_used':'fixture'})
            features=types.ModuleType('aggressive.finnhub_cache_loader');features.load_finnhub_features_dict=lambda: {}
            with patch.dict(sys.modules,{'aggressive.universe':universe,'aggressive.finnhub_cache_loader':features}):
                with self.assertRaises(b.IncompleteUniverseError):
                    b.build_unified_scored(str(source),str(output))
            self.assertEqual(output.read_bytes(),b'old-output-unchanged\n')
            self.assertEqual(json.loads(Path(str(output)+'.coverage.json').read_text())['unscored_securities'],1117)
            self.assertEqual(len(pd.read_csv(str(output)+'.coverage.csv')),1118)

    def test_theme_fallback_is_not_a_full_universe(self):
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'s.csv';output=Path(folder)/'o.csv'
            source.write_text('ticker,score\nA,1\n');output.write_text('preserve')
            universe=types.ModuleType('aggressive.universe')
            universe.load_universe=lambda _: (['A'],{'source_used':'themes_fallback'})
            features=types.ModuleType('aggressive.finnhub_cache_loader')
            features.load_finnhub_features_dict=lambda: self.fail('must stop before cache load')
            with patch.dict(sys.modules,{'aggressive.universe':universe,'aggressive.finnhub_cache_loader':features}):
                with self.assertRaisesRegex(b.IncompleteUniverseError,'universe_coverage'):
                    b.build_unified_scored(str(source),str(output))
            self.assertEqual(output.read_text(),'preserve')
            self.assertEqual(json.loads(Path(str(output)+'.coverage.json').read_text())['status'],'BLOCKED_UNIVERSE_SOURCE')

    def test_complete_legacy_not_investment_approval(self):
        _,s,valid=b.reconcile_inventory(pd.DataFrame({'ticker':['A'],'score':[2]}),['A'])
        self.assertEqual(valid['score'].iloc[0],2)
        self.assertFalse(s['investment_approved'])

if __name__=='__main__':unittest.main()
