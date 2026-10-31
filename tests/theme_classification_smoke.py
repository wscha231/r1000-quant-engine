"""Offline regression for archived PSA/EXR contamination and both consumers."""
import sys
import csv
import json
import hashlib
import unittest
import socket
import tempfile
from pathlib import Path
from unittest.mock import patch

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
import run_theme_leadership_tape as tape
import run_theme_concentration_challenger as challenger


class ThemeTests(unittest.TestCase):
    def theme(self, **row):
        return tape.infer_theme(pd.Series(row))

    def test_archived_six_members(self):
        # Membership is from the 2026-05-10 report, not invented price rows.
        # Exact aggregate row copied from theme_leadership.csv at base 481bcf5.
        with (ROOT / "tests/fixtures/theme_memory_20260510.csv").open(newline="") as source:
            archived = next(csv.DictReader(source))
        self.assertEqual(int(archived["member_count"]), 6)
        self.assertEqual(archived["top_tickers"], "MU,SNDK,STX,WDC,PSA,EXR")
        for ticker in ("MU", "SNDK", "STX", "WDC"):
            self.assertEqual(self.theme(ticker=ticker), "memory_semiconductors")
        for ticker, name in (("PSA", "Public Storage"), ("EXR", "Extra Space Storage")):
            self.assertNotEqual(self.theme(ticker=ticker, Name=name), "memory_semiconductors")

    def test_actual_archived_business_rows(self):
        rows = pd.read_csv(ROOT / "tests/fixtures/theme_memory_members_20260510.csv")
        expected = {"MU": "memory_semiconductors", "SNDK": "memory_semiconductors",
                    "STX": "memory_semiconductors", "WDC": "memory_semiconductors",
                    "PSA": "real_estate", "EXR": "real_estate"}
        self.assertEqual(rows.set_index("ticker")["leadership_theme"].to_dict(),
                         {ticker: "memory_semiconductors" for ticker in expected})
        self.assertEqual(dict(zip(rows["ticker"], rows.apply(tape.infer_theme, axis=1))), expected)
        self.assertEqual(dict(zip(rows["ticker"], challenger.add_theme_and_scores(rows)["leadership_theme"])), expected)

    def test_real_estate_separator_normalization(self):
        for sector in ("Real Estate", "Real-Estate", "Real_Estate", "real/estate"):
            for name in ("Public Storage", "Extra Space Storage"):
                self.assertEqual(self.theme(ticker="TEST", Name=name, sector=sector), "real_estate")
        for industry in ("REIT-Industrial", "REIT_Industrial", "REIT / Industrial"):
            self.assertEqual(self.theme(ticker="TEST", Name="Storage", industry=industry), "real_estate")

    def test_plural_reit_business_labels(self):
        for industry in ("Equity REITs", "Specialized REITs", "Self-Storage REITs"):
            self.assertEqual(self.theme(ticker="TEST", Name="Public Storage", industry=industry),
                             "real_estate")
            self.assertEqual(self.theme(ticker="TEST", Name="Extra Space Storage", industry=industry),
                             "real_estate")
        self.assertNotEqual(self.theme(ticker="TEST", Name="Flash Memory", sector="Equity REITs"),
                            "memory_semiconductors")

    def test_hot_path_reuses_compiled_patterns(self):
        with patch.object(tape.re, "compile", side_effect=AssertionError("per-row compile")), \
             patch.object(tape.re, "search", side_effect=AssertionError("per-row pattern construction")), \
             patch.object(tape.re, "sub", side_effect=AssertionError("per-row normalization pattern")):
            self.assertEqual(self.theme(ticker="TEST", Name="Flash Memory", industry="Semiconductors"),
                             "memory_semiconductors")
            self.assertEqual(self.theme(ticker="EXR", Name="Extra Space Storage", sector="Real-Estate"),
                             "real_estate")

    def test_recorded_diagnostic_evidence_hashes(self):
        evidence = ROOT / "docs/theme_memory_fix_evidence_20261015"
        manifest = json.loads((evidence / "manifest.json").read_text())
        required = {f"{date}_{kind}.csv" for date in ("20260510", "20260512")
                    for kind in ("themes_before", "themes_after", "score_comparison", "membership_changes")}
        self.assertTrue(required.issubset({entry["path"] for entry in manifest["files"]}))
        for entry in manifest["files"]:
            data = (evidence / entry["path"]).read_bytes()
            self.assertEqual(len(data), entry["size_bytes"])
            self.assertEqual(hashlib.sha256(data).hexdigest(), entry["sha256"])

    def test_all_curated_memory_issuers_preserved(self):
        for ticker in tape.THEME_TAXONOMY["memory_semiconductors"]["tickers"]:
            self.assertEqual(self.theme(ticker=ticker), "memory_semiconductors")

    def test_hardware_storage_and_memory(self):
        for name in ("Storage Systems", "NAND", "DRAM", "HBM", "SSD", "Flash", "Memory"):
            for industry in ("Semiconductors", "Computer Hardware", "Electronic Components", "Electronic Equipment & Parts"):
                with self.subTest(name=name, industry=industry):
                    self.assertEqual(self.theme(ticker="TEST", Name=name, industry=industry),
                                     "memory_semiconductors")

    def test_precise_digital_hardware_phrases(self):
        for name in ("Flash Memory", "Hard-Disk Drives", "Solid-State Drives",
                     "Data Storage Devices", "High Bandwidth Memory"):
            self.assertEqual(self.theme(ticker="TEST", Name=name), "memory_semiconductors")

    def test_physical_and_energy_storage_excluded(self):
        for industry in ("REIT - Specialty", "Real Estate", "Self-Storage",
                         "Warehousing", "Cold Storage", "Battery Storage",
                         "Energy Storage", "Gas Storage", "Oil Storage", "Logistics"):
            self.assertNotEqual(self.theme(ticker="TEST", Name="Flash Memory Storage",
                                           industry=industry), "memory_semiconductors")

    def test_inherited_labels_cannot_certify_business(self):
        for key in ("theme_phase_primary", "theme_horizon_primary",
                    "theme_holding_profile_primary", "portfolio_sleeve_label"):
            self.assertNotEqual(self.theme(ticker="TEST", Name="Public Storage",
                                           **{key: "memory_semiconductors flash dram storage"}),
                                "memory_semiconductors")

    def test_contradictory_industry_rejects_name_only_hardware(self):
        for industry in ("Software - Application", "Healthcare", "Financial Services"):
            self.assertNotEqual(self.theme(ticker="TEST", Name="Flash Memory", industry=industry),
                                "memory_semiconductors")

    def test_word_boundaries(self):
        for name in ("Dramatic Health", "Brandy Foods", "Flashlight Rental", "Memory Care"):
            self.assertNotEqual(self.theme(ticker="TEST", Name=name), "memory_semiconductors")

    def test_missing_metadata_and_no_cross_field_phrase(self):
        for value in (None, float("nan"), pd.NA, ""):
            self.assertEqual(self.theme(ticker="TEST", Name=value), "unclassified")
        self.assertNotEqual(self.theme(ticker="TEST", Name="Flash", industry="Memory Care"),
                            "memory_semiconductors")

    def test_missing_string_industries_preserve_precise_evidence(self):
        for industry in ("Unknown", "N/A", "nan", "none", "null", "NA"):
            self.assertEqual(self.theme(ticker="TEST", Name="Flash Memory", industry=industry),
                             "memory_semiconductors")

    def test_other_theme_and_fallback_preserved(self):
        self.assertEqual(self.theme(ticker="NVDA"), "ai_compute_semiconductors")
        self.assertEqual(self.theme(ticker="FLNC", Name="Battery Storage"), "power_grid_gas_turbine")
        self.assertEqual(self.theme(ticker="PSA", Name="Public Storage", sector="Real Estate"),
                         "real_estate")

    def test_two_real_consumers_agree(self):
        scored = pd.DataFrame([{"ticker": t, "Name": n, "industry": i}
                               for t, n, i in (("PSA", "Public Storage", "REIT - Specialty"),
                                               ("EXR", "Extra Space Storage", "REIT - Specialty"),
                                               ("MU", "Micron", "Semiconductors"),
                                               ("STX", "Seagate", "Computer Hardware"),
                                               ("TEST", "Storage", "Computer Hardware"))])
        def metrics(_cache, ticker):
            return dict(ticker=ticker, dollar_volume_20d=1e8, ret_1d=.01, ret_5d=.02,
                        ret_21d=.04, ret_63d=.08, ret_126d=.1, volume_z_20d=0)
        with patch.object(tape, "price_metrics", side_effect=metrics):
            daily = tape.build_ticker_tape(scored, Path("unused"), 0, 0)
        monthly = challenger.add_theme_and_scores(scored)
        self.assertEqual(daily.set_index("ticker")["leadership_theme"].to_dict(),
                         monthly.set_index("ticker")["leadership_theme"].to_dict())

    def test_aggregate_uses_corrected_membership(self):
        # Synthetic arithmetic control only; no historical score claim.
        scored = pd.DataFrame([{"ticker":t, "Name":n} for t,n in
                               (("MU","Micron"),("SNDK","Sandisk"),("STX","Seagate"),
                                ("WDC","Western Digital"),("PSA","Public Storage"),
                                ("EXR","Extra Space Storage"))])
        scored["leadership_theme"] = scored.apply(tape.infer_theme, axis=1)
        for col, value in (("ret_1d",.01),("ret_5d",.02),("ret_21d",.04),("ret_63d",.08),
                           ("participation_score",1.),("bubble_climax_score",1.),
                           ("early_leadership_score",1.),("dollar_volume_20d",1e8)):
            scored[col] = value
        scored["liquidity_pass"] = True
        row = tape.aggregate_leadership(scored, "leadership_theme").set_index("leadership_theme").loc["memory_semiconductors"]
        self.assertEqual(row["member_count"], 4)
        self.assertEqual(set(row["top_tickers"].split(",")), {"MU","SNDK","STX","WDC"})

    def local_tape(self, root, specs, *, comparison_session=None):
        cache = root / 'cache'; cache.mkdir()
        roster = []
        for ticker, count, end, rising in specs:
            close = [100.0 + (i if rising else 0) for i in range(count)]
            pd.DataFrame({'Close':close, 'Adj Close':close, 'Volume':[1_000_000]*count},
                index=pd.bdate_range(end=end, periods=count)).to_parquet(cache/tape.px_cache_name(ticker))
            roster.append(dict(ticker=ticker, Name='Fixture '+ticker, sector='Health Care',
                               industry='Fixture Devices', mktcap=5e9))
        scored = root/'roster.csv'; pd.DataFrame(roster).to_csv(scored,index=False)
        with patch.object(tape,'fetch_yfinance_history',side_effect=AssertionError('implicit fetch')), \
             patch.object(socket.socket,'connect',side_effect=AssertionError('network')):
            summary = tape.run(scored,cache,root/'out',1e9,1e6,
                               comparison_session=comparison_session)
        return summary, pd.read_csv(root/'out/ticker_leadership.csv'), \
            pd.read_csv(root/'out/theme_leadership.csv'), (root/'out/report.md').read_text(encoding='utf-8')

    def test_native_all_missing_returns_are_pending_and_render_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, rows, groups, report = self.local_tape(Path(tmp),
                [('AAA',6,'2026-10-29',True),('BBB',6,'2026-10-29',True)])
        self.assertTrue(rows.ret_21d.isna().all())
        self.assertEqual(groups.iloc[0].leadership_state,'data_pending')
        self.assertEqual((groups.iloc[0].observed_count_21d,groups.iloc[0].missing_count_21d),(0,2))
        self.assertTrue(pd.isna(groups.iloc[0].breadth_21d_positive))
        self.assertTrue(pd.isna(groups.iloc[0].leadership_score))
        self.assertIn('21d UNKNOWN',report)
        self.assertNotIn('21d 0.00%',report)

    def test_native_breadth_keeps_both_denominators(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, _, groups, _ = self.local_tape(Path(tmp),
                [(t,n,'2026-10-29',True) for t,n in [('AAA',30),('BBB',30),('CCC',6),('DDD',6)]])
        row=groups.iloc[0]
        self.assertEqual((row.member_count,row.observed_count_21d,row.missing_count_21d,row.positive_count_21d),(4,2,2,2))
        self.assertEqual(row.breadth_21d_positive,1.0)
        self.assertEqual(row.positive_share_all_liquid_members,.5)
        self.assertEqual(row.coverage_21d,.5)
        self.assertEqual(row.breadth_21d_denominator,'OBSERVED_LIQUID_MEMBERS')
        self.assertEqual(row.leadership_state,'data_pending')

    def test_native_actual_zero_remains_zero_and_neutral(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, rows, groups, report=self.local_tape(Path(tmp),[('AAA',160,'2026-10-29',False)])
        self.assertEqual(rows.iloc[0].ret_21d,0)
        self.assertEqual(groups.iloc[0].leadership_state,'neutral')
        self.assertIn('21d 0.00%',report)
        for value in (None,float('nan'),float('inf'),'invalid'):
            self.assertEqual(tape.format_percent(value),'UNKNOWN')

    def test_native_missing_etf_never_fetches(self):
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(tape,'fetch_yfinance_history',side_effect=AssertionError('implicit fetch')) as fetch, \
             patch.object(socket.socket,'connect',side_effect=AssertionError('network')):
            self.assertTrue(tape.etf_price_frame(Path(tmp),'FIXTURE_ETF').empty)
            etfs=tape.etf_attention(Path(tmp))
            self.assertTrue(etfs.price_status.eq('missing_or_short').all())
            self.assertTrue(etfs.attention_score.isna().all())
            watches=tape.build_etf_lookthrough_watchlist(pd.DataFrame(),etfs)
            self.assertTrue(watches.etf_attention_score.isna().all())
            self.assertTrue(watches.combined_watch_score.isna().all())
        fetch.assert_not_called()

    def test_native_mixed_age_is_partial_and_watermark_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            summary, rows, _, report=self.local_tape(Path(tmp),
                [('AAA',160,'2020-01-02',True),('BBB',160,'2026-10-29',True)],
                comparison_session='2026-10-29')
        self.assertEqual(summary['status'],'completed')  # computation only
        self.assertEqual(summary['observation_status'],'PARTIAL')
        self.assertEqual(summary['freshness_status'],'MIXED_AS_OF')
        self.assertEqual(summary['stale_price_rows'],1)
        self.assertEqual(summary['price_date_counts'],{'2020-01-02':1,'2026-10-29':1})
        self.assertIsNone(summary['top_theme'])
        self.assertFalse(summary['currentness_verified'])
        self.assertFalse(summary['whole_market_coverage_verified'])
        self.assertEqual(set(rows.price_as_of_status),{'STALE','ALIGNED_TO_SUPPLIED_SESSION'})
        self.assertIn('watermark only',report)

    def test_stale_etf_cannot_become_top_current_attention(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            _,_,_,_=self.local_tape(root,[('DRAM',160,'2020-01-02',True),
                ('AAA',160,'2026-10-29',True)],comparison_session='2026-10-29')
            summary=json.loads((root/'out/summary.json').read_bytes())
            etfs=pd.read_csv(root/'out/etf_attention.csv').set_index('etf')
            self.assertEqual(etfs.loc['DRAM','price_as_of_status'],'STALE')
            self.assertEqual(etfs.loc['DRAM','price_date'],'2020-01-02')
            self.assertTrue(pd.isna(etfs.loc['DRAM','attention_score']))
            self.assertIsNone(summary['top_etf_attention'])
            self.assertEqual(summary['etf_stale_rows'],1)

    def test_etf_missing_volume_is_unknown_but_real_zero_is_observed(self):
        for missing in ('column','current','prior',None):
            with self.subTest(missing=missing),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);close=[100.0+i for i in range(160)]
                px=pd.DataFrame({'Close':close,'Adj Close':close},
                    index=pd.bdate_range(end='2026-10-29',periods=160))
                if missing != 'column':
                    px['Volume']=[float(i+100) for i in range(160)]
                    px.iloc[-1,px.columns.get_loc('Volume')]=0.0
                    if missing in ('current','prior'):
                        px.iloc[-1 if missing=='current' else -2,px.columns.get_loc('Volume')]=float('nan')
                px.to_parquet(root/tape.px_cache_name('DRAM'))
                row=tape.etf_attention(root,session='2026-10-29').set_index('etf').loc['DRAM']
                self.assertIsNotNone(row.ret_21d)
                if missing is None:
                    self.assertTrue(pd.notna(row.attention_score))
                    self.assertTrue(pd.notna(row.volume_z_20d))
                else:
                    self.assertTrue(pd.isna(row.attention_score))
                    self.assertTrue(pd.isna(row.volume_z_20d))

    def test_stale_rows_cannot_change_valid_normalization(self):
        etf_scores,ticker_scores,group_scores=[],[],[]
        for rising in (False,True):
            with tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp)
                _,tickers,_,_=self.local_tape(root,[('AAA',160,'2026-10-29',True),
                    ('BBB',160,'2020-01-02',rising)],comparison_session='2026-10-29')
                ticker_scores.append(tickers.set_index('ticker').loc['AAA','participation_score'])
                # The same fresh ETF bytes, with only a stale peer changed.
                cache=root/'cache'
                for name,end,multiplier in [('SOXX','2026-10-29',1),('DRAM','2020-01-02',1 if rising else .01)]:
                    close=[100.0+i*multiplier for i in range(160)]
                    pd.DataFrame({'Close':close,'Adj Close':close,'Volume':[1000]*160},
                        index=pd.bdate_range(end=end,periods=160)).to_parquet(cache/tape.px_cache_name(name))
                etfs=tape.etf_attention(cache,session='2026-10-29').set_index('etf')
                etf_scores.append(etfs.loc['SOXX','attention_score'])
                rows=pd.DataFrame([dict(ticker='AAA',leadership_theme='valid',liquidity_pass=True,
                    price_as_of_status='ALIGNED_TO_SUPPLIED_SESSION',ret_1d=.01,ret_5d=.02,ret_21d=.04,
                    ret_63d=.1,participation_score=1.,bubble_climax_score=1.,early_leadership_score=1.,dollar_volume_20d=1e8),
                    dict(ticker='BBB',leadership_theme='stale',liquidity_pass=True,price_as_of_status='STALE',
                    ret_1d=.5,ret_5d=10. if rising else -1.,ret_21d=100. if rising else -.99,
                    ret_63d=10.,participation_score=100.,bubble_climax_score=100.,early_leadership_score=100.,dollar_volume_20d=1e15)])
                groups=tape.aggregate_leadership(rows,'leadership_theme').set_index('leadership_theme')
                group_scores.append(groups.loc['valid','leadership_score'])
                self.assertTrue(pd.isna(groups.loc['stale','leadership_score']))
        self.assertEqual(etf_scores[0],etf_scores[1])
        self.assertEqual(ticker_scores[0],ticker_scores[1])
        self.assertEqual(group_scores[0],group_scores[1])

    def test_incomplete_score_group_label_and_top_names_stay_pending(self):
        valid=dict(ticker='AAA',leadership_theme='fixture',liquidity_pass=True,
            price_as_of_status='ALIGNED_TO_SUPPLIED_SESSION',ret_1d=.01,ret_5d=.15,
            ret_21d=.25,ret_63d=.4,dollar_volume_20d=1e8,
            participation_score=1.,bubble_climax_score=1.,early_leadership_score=1.)
        missing=dict(valid,ticker='MISSING',volume_z_20d=float('nan'),
            participation_score=float('nan'),bubble_climax_score=float('nan'),early_leadership_score=float('nan'))
        for rows in ([missing],[dict(valid,ticker=f'VALID{i}') for i in range(8)]+[missing]):
            group=tape.aggregate_leadership(pd.DataFrame(rows),'leadership_theme').iloc[0]
            self.assertEqual(group.leadership_state,'data_pending')
            self.assertTrue(pd.isna(group.leadership_score))
            self.assertNotIn('MISSING',group.top_tickers)
        # Finite existing scores are sufficient; no new volume_z field gate.
        self.assertEqual(tape.aggregate_leadership(pd.DataFrame([valid]),'leadership_theme').iloc[0].leadership_state,'climax_hot')
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);cache=root/'cache';cache.mkdir()
            px=pd.DataFrame({'Close':[100.+i for i in range(100)],
                'Adj Close':[100.+i for i in range(100)],'Volume':[1e6+i for i in range(100)]},
                index=pd.bdate_range(end='2026-10-29',periods=100))
            px.iloc[-2,px.columns.get_loc('Volume')]=float('nan')
            px.to_parquet(cache/tape.px_cache_name('AAA'))
            source=root/'roster.csv';pd.DataFrame([dict(ticker='AAA',sector='Fixture',mktcap=5e9)]).to_csv(source,index=False)
            summary=tape.run(source,cache,root/'out',1e9,1e6,comparison_session='2026-10-29')
            groups=pd.read_csv(root/'out/theme_leadership.csv')
            raw=pd.read_csv(root/'out/ticker_leadership.csv')
            report=(root/'out/report.md').read_text(encoding='utf-8')
        self.assertEqual(len(raw),1)
        self.assertEqual(groups.iloc[0].leadership_state,'data_pending')
        self.assertEqual(summary['top_tickers'],[])
        self.assertEqual(summary['tickers_with_observed_scores'],0)
        self.assertIn('score UNKNOWN',report)
        self.assertNotIn('state `emerging_leader`',report)

    def test_native_missing_cache_row_is_retained_without_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); (root/'cache').mkdir()
            source=root/'roster.csv';pd.DataFrame([dict(ticker='AAA',Name='Unknown')]).to_csv(source,index=False)
            summary=tape.run(source,root/'cache',root/'out',1e9,1e6)
            row=pd.read_csv(root/'out/ticker_leadership.csv').iloc[0]
        self.assertEqual(summary['observation_status'],'DATA_PENDING')
        self.assertEqual(summary['universe_scope'],'SELECTED_SUBSET')
        self.assertEqual(summary['missing_price_rows'],1)
        self.assertTrue(pd.isna(row.market_cap)); self.assertTrue(pd.isna(row.dollar_volume_20d))
        self.assertTrue(pd.isna(row.ret_21d))

    def test_missing_cache_cannot_inherit_scored_prices_or_returns(self):
        # Independent A6's Native RED: metadata cannot impersonate a cache read.
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'cache').mkdir()
            source=root/'scored.csv'
            pd.DataFrame([dict(ticker='AAA',sector='Health Care',industry='Devices',
                mktcap=5e9,price_date='2026-10-29',ret_5d=.15,ret_21d=.25,
                dollar_volume_20d=50e6)]).to_csv(source,index=False)
            summary=tape.run(source,root/'cache',root/'out',1e9,1e6,comparison_session='2026-10-29')
            row=pd.read_csv(root/'out/ticker_leadership.csv').iloc[0]
        self.assertEqual(summary['observation_status'],'DATA_PENDING')
        self.assertEqual(summary['missing_price_rows'],1)
        self.assertIsNone(summary['latest_price_date'])
        self.assertIsNone(summary['top_theme']);self.assertIsNone(summary['top_etf_attention'])
        for value in (row.price_date,row.ret_5d,row.ret_21d,row.dollar_volume_20d):
            self.assertTrue(pd.isna(value))
        self.assertEqual(row.price_status,'missing_or_short')
        self.assertEqual(row.sector,'Health Care')

    def research_fixture(self):
        import technical_feature_h1_smoke as ft
        from tools import run_a2_research_intake as caller
        fixture=ft.FeatureTests();fixture.setUp()
        identities=dict(scope='SUPPLIED_US_IDENTITY_ASSERTIONS',rows=[
            dict(security_id=ft.IDS['TEST'],issuer_id='FIXTURE:ISSUER:TEST',tickers=['TEST'],country='US',currency='USD'),
            dict(security_id='FIXTURE:US:MISSING',issuer_id='FIXTURE:ISSUER:MISSING',tickers=['MISSING'],country='US',currency='USD')])
        roster=dict(scope='PRE_RANKING_RESEARCH_ROSTER',rows=[
            dict(ticker='TEST',sector='Health Care'),dict(ticker='MISSING',sector='Financials')])
        kwargs=dict(roster_raw=caller.intake.canonical(roster),
            identities_raw=caller.intake.canonical(identities),session=ft.SESSION,as_of=ft.ASOF,
            observed_at='2026-10-30T06:30:00Z',intake_cutoff='2026-10-30T06:31:00Z',
            source_kind='FUSION_REVIEW')
        return ft,fixture,caller,kwargs

    def test_actual_reader_feature_to_a2_preserves_unranked_missing_roster(self):
        ft,fixture,caller,kwargs=self.research_fixture()
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(socket.socket,'connect',side_effect=AssertionError('network')):
            result=tape.prepare_research_roster(fixture.reader,{ft.IDS['TEST']:fixture.generation()},
                                               out_dir=Path(tmp)/'new',**kwargs)
            observation=result['observation'];queue=result['a2_result']['queue']
            self.assertEqual((observation['requested_count'],observation['source_observed_count'],observation['missing_source_count']),(2,1,1))
            self.assertEqual({i['ticker'] for i in queue['items']},{'TEST','MISSING'})
            self.assertTrue(all(i['state']=='DATA_PENDING' for i in queue['items']))
            self.assertIsNone(observation['rows'][1]['ret_20s'])
            snapshot=observation['snapshots'][0]
            self.assertIsNone(snapshot['features']['rs_log_spy_20s'])
            self.assertIsNotNone(observation['rows'][0]['ret_20s'])
            self.assertNotIn('ret_21d',observation['rows'][0])
            self.assertFalse(snapshot['ranking_allowed']);self.assertFalse(observation['ranking_allowed'])
            self.assertEqual(snapshot['source_available_from'],'2026-10-13T21:05:00Z')
            self.assertIsNone(result['a3_consumer_ack'])
            self.assertTrue(all(v is False for v in observation['authority'].values()))
            request_path=Path(tmp)/'new/request.json'
            repeated=caller.prepare(input_root=Path(tmp)/'new',request_path='request.json',
                request_sha256=hashlib.sha256(request_path.read_bytes()).hexdigest(),cutoff=kwargs['intake_cutoff'])
            self.assertEqual(repeated,result['a2_result'])
            # Real file-hash gate, not a replayed local predicate.
            with (Path(tmp)/'new/observations.csv').open('ab') as stream:stream.write(b'changed')
            with self.assertRaisesRegex(caller.intake.IntakeError,'FILE_HASH_MISMATCH'):
                caller.prepare(input_root=Path(tmp)/'new',request_path='request.json',
                    request_sha256=hashlib.sha256(request_path.read_bytes()).hexdigest(),cutoff=kwargs['intake_cutoff'])

    def test_research_handoff_unknown_identity_and_source_refusal_stop_before_outputs(self):
        ft,fixture,caller,kwargs=self.research_fixture()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            unknown=dict(kwargs,roster_raw=caller.intake.canonical(dict(scope='PRE_RANKING_RESEARCH_ROSTER',rows=[dict(ticker='UNKNOWN')])))
            with self.assertRaisesRegex(caller.intake.IntakeError,'OBSERVATION_EXACT_IDENTITY'):
                tape.prepare_research_roster(fixture.reader,{},out_dir=root/'unknown',**unknown)
            self.assertFalse((root/'unknown').exists())
            generation=fixture.generation()
            source_path=next(k for k in fixture.transport.objects if '/objects/' in k)
            fixture.transport.objects[source_path]+=b'corrupt'
            with self.assertRaisesRegex(caller.intake.IntakeError,'OBSERVATION_SOURCE_REFUSED:'):
                tape.prepare_research_roster(fixture.reader,{ft.IDS['TEST']:generation},out_dir=root/'bad',**kwargs)
            self.assertFalse((root/'bad').exists())

    def test_research_handoff_keeps_future_expiry_and_rights_refusals(self):
        for field,value in [('available_from','2099-01-01T00:00:00Z'),
                            ('expires_at','2026-10-13T23:30:00Z'),
                            ('eligible_purposes',[])]:
            with self.subTest(field=field),tempfile.TemporaryDirectory() as tmp:
                ft,fixture,caller,kwargs=self.research_fixture()
                fixture.data_spec['source'][field]=value
                with self.assertRaisesRegex(caller.intake.IntakeError,'OBSERVATION_SOURCE_REFUSED:'):
                    tape.prepare_research_roster(fixture.reader,{ft.IDS['TEST']:fixture.generation()},
                        out_dir=Path(tmp)/'refused',**kwargs)
                self.assertFalse((Path(tmp)/'refused').exists())

    def test_research_handoff_never_backdates_new_output_or_overwrites_directory(self):
        ft,fixture,caller,kwargs=self.research_fixture()
        with tempfile.TemporaryDirectory() as tmp:
            changed=dict(kwargs,observed_at='2026-10-13T00:00:00Z')
            with self.assertRaisesRegex(caller.intake.IntakeError,'OBSERVATION_HANDOFF_CLOCK'):
                tape.prepare_research_roster(fixture.reader,{},out_dir=Path(tmp)/'bad',**changed)
            self.assertFalse((Path(tmp)/'bad').exists())
            destination=Path(tmp)/'existing';destination.mkdir();(destination/'owned').write_bytes(b'preserve')
            with self.assertRaises(FileExistsError):
                tape.prepare_research_roster(fixture.reader,{},out_dir=destination,**kwargs)
            self.assertEqual((destination/'owned').read_bytes(),b'preserve')


class AllRequestedObservationTests(unittest.TestCase):
    def fixture(self, count=250):
        import technical_feature_h1_smoke as ft
        from tools import run_a2_research_intake as caller
        with patch.object(ft, 'DAYS', ft.DAYS[-count:]):
            fixture = ft.FeatureTests(); fixture.setUp()
        negative_id = 'FIXTURE:US:NEG'
        fixture.rows[negative_id] = [dict(r, instrument_id=negative_id, ticker='NEG')
                                    for r in fixture.rows[ft.IDS['TEST']]]
        for iid, base, direction in [(ft.IDS['TEST'], 100, 1), (ft.IDS['SPY'], 100, 0),
                                     (negative_id, 400, -1)]:
            for i, row in enumerate(fixture.rows[iid]):
                close = base + direction * i
                row.update(open=close, high=close+1, low=close-1, close=close)
            fixture.add_file(iid)
        ids = {'TEST': ft.IDS['TEST'], 'SPY': ft.IDS['SPY'], 'NEG': negative_id,
               'MISSING': 'FIXTURE:US:MISSING'}
        identities = dict(scope='SUPPLIED_US_IDENTITY_ASSERTIONS', rows=[dict(
            security_id=sid, issuer_id='FIXTURE:ISSUER:'+ticker, tickers=[ticker],
            country='US', currency='USD') for ticker, sid in ids.items()])
        rows = [dict(ticker='NEG', sector='Health Care'), dict(ticker='UNKNOWN'),
                dict(ticker='SPY', sector='Health Care'), dict(ticker='MISSING', sector=None),
                dict(ticker='TEST', sector='Health Care')]
        kwargs = dict(roster_raw=caller.intake.canonical(dict(scope='PRE_RANKING_RESEARCH_ROSTER', rows=rows)),
            identities_raw=caller.intake.canonical(identities), session=ft.SESSION, as_of=ft.ASOF,
            observed_at='2026-10-30T06:30:00Z', intake_cutoff='2026-10-30T06:31:00Z',
            source_kind='FUSION_REVIEW')
        generation = fixture.generation()
        generations = {ids[k]: generation for k in ('TEST', 'SPY', 'NEG')}
        return ft, fixture, caller, ids, identities, kwargs, generations

    def test_actual_reader_feature_a2_subset_preserves_full_denominator_and_replay(self):
        ft, fixture, caller, ids, _, kwargs, generations = self.fixture()
        benchmark_ids = {'SPY': ids['SPY']}
        benchmark_generations = {'SPY': fixture.generation()}
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(socket.socket, 'connect', side_effect=AssertionError('network')), \
             patch.object(fixture.reader, 'read_components', wraps=fixture.reader.read_components) as read, \
             patch.object(tape, 'prepare_research_roster', wraps=tape.prepare_research_roster) as strict:
            first = tape.prepare_all_requested_research_roster(fixture.reader, generations,
                out_dir=Path(tmp)/'first', benchmark_ids=benchmark_ids,
                benchmark_generations=benchmark_generations, **kwargs)
            self.assertEqual(read.call_count, 3)
            self.assertIs(strict.call_args.kwargs['benchmark_ids'], benchmark_ids)
            self.assertIs(strict.call_args.kwargs['benchmark_generations'], benchmark_generations)
            full = first['all_requested_observation']
            self.assertEqual((full['requested_count'], full['identity_assertion_resolved_count'],
                full['identity_unknown_count'], full['source_observed_count'], full['source_missing_resolved_count']), (5,4,1,3,1))
            self.assertEqual([r['ticker'] for r in full['rows']], ['NEG','UNKNOWN','SPY','MISSING','TEST'])
            self.assertEqual([r['input_ordinal'] for r in full['rows']], list(range(5)))
            unknown = full['rows'][1]
            self.assertEqual(unknown['identity_status'], 'UNKNOWN_IDENTITY')
            self.assertIsNone(unknown['security_id']); self.assertIsNone(unknown['issuer_id'])
            queue = first['resolved_subset']['a2_result']['queue']['items']
            self.assertEqual({r['ticker'] for r in queue}, {'NEG','SPY','MISSING','TEST'})
            self.assertTrue(all(r['state'] == 'DATA_PENDING' for r in queue))
            group = next(g for g in full['sector_groups'] if g['group'] == 'Health Care')
            for n in (5,20,60,120,240):
                h = group['horizons'][str(n)]
                self.assertEqual((h['full_member_count'],h['observed_count'],h['positive_count'],
                    h['negative_count'],h['zero_count'],h['missing_count'],h['stale_count']), (3,3,1,1,1,0,0))
                self.assertEqual(h['observed_subset_median_return'], 0.0)
                self.assertEqual(h['median_basis'], 'OBSERVED_SUBSET_SPLIT_ADJUSTED_PRICE_RETURN')
                self.assertFalse(h['total_return']);self.assertFalse(h['formal_benchmark_RS']);self.assertFalse(h['net_ER'])
            unclassified = next(g for g in full['sector_groups'] if g['group'] == 'UNCLASSIFIED')
            self.assertEqual(unclassified['full_member_count'], 2)
            self.assertEqual(unclassified['horizons']['5']['missing_count'], 2)
            self.assertIsNone(unclassified['horizons']['5']['observed_subset_median_return'])
            for name in ('identity_verified_count','fundamental_admissible_count','price_admissible_count'):
                self.assertIsNone(full[name])
            self.assertTrue(all(r['fundamental_admissibility'] == 'UNKNOWN' for r in full['rows']))
            self.assertFalse(full['currentness_verified']);self.assertFalse(full['whole_market_coverage_verified'])
            self.assertFalse(full['ranking_allowed']);self.assertTrue(all(v is False for v in full['authority'].values()))
            self.assertIsNone(first['a3_consumer_ack']);self.assertFalse(first['canonical_current_verified'])
            # New output clocks with an old matching comparison cannot certify latest/current prices.
            self.assertEqual(full['comparison_session'], ft.SESSION)
            self.assertNotIn('ret_21d', full['rows'][0]);self.assertNotIn('leader', full)
            raw = (Path(tmp)/'first/all_requested_observations.json').read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(), first['all_requested_observation_sha256'])
            again = tape.prepare_all_requested_research_roster(fixture.reader, generations,
                out_dir=Path(tmp)/'again', benchmark_ids=benchmark_ids,
                benchmark_generations=benchmark_generations, **kwargs)
            self.assertEqual(first, again)
            self.assertEqual(read.call_count, 6)

    def test_all_unknown_unclassified_skips_reader_feature_and_a2(self):
        ft, fixture, caller, _, _, kwargs, _ = self.fixture(6)
        kwargs['identities_raw'] = caller.intake.canonical(dict(scope='SUPPLIED_US_IDENTITY_ASSERTIONS', rows=[]))
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(tape,'prepare_research_roster',side_effect=AssertionError('STRICT_NOT_ALLOWED')), \
             patch.object(ft.target,'research_feature_snapshot',side_effect=AssertionError('FEATURE_NOT_ALLOWED')), \
             patch.object(fixture.reader,'read_components',side_effect=AssertionError('READER_NOT_ALLOWED')), \
             patch.object(caller,'prepare',side_effect=AssertionError('A2_NOT_ALLOWED')):
            result = tape.prepare_all_requested_research_roster(fixture.reader,{},out_dir=Path(tmp)/'new',**kwargs)
            self.assertEqual(sorted(p.name for p in (Path(tmp)/'new').iterdir()), ['all_requested_observations.json'])
            with self.assertRaisesRegex(caller.intake.IntakeError,'OBSERVATION_GENERATION_SUBJECT'):
                tape.prepare_all_requested_research_roster(fixture.reader,{'UNBOUND:SECURITY':'1'*64},
                    out_dir=Path(tmp)/'unbound-source',**kwargs)
            self.assertFalse((Path(tmp)/'unbound-source').exists())
        full = result['all_requested_observation']
        self.assertEqual(full['identity_unknown_count'],5);self.assertEqual(full['source_observed_count'],0)
        self.assertEqual(full['a2_status'],'NOT_RUN');self.assertIsNone(full['resolved_subset_ref'])
        self.assertIsNone(result['resolved_subset'])
        for group in full['sector_groups']:
            for h in group['horizons'].values():
                self.assertEqual(h['observed_count'],0)
                self.assertEqual(h['missing_count'],h['full_member_count'])
                self.assertIsNone(h['observed_subset_median_return'])
        self.assertIn('UNCLASSIFIED',{g['group'] for g in full['sector_groups']})

    def test_explicit_older_observations_stay_stale_and_short_horizons_stay_missing(self):
        _, fixture, _, _, _, kwargs, generations = self.fixture(21)
        kwargs.update(as_of='2026-10-15T00:00:00Z',comparison_session='2026-10-14')
        with tempfile.TemporaryDirectory() as tmp:
            result=tape.prepare_all_requested_research_roster(fixture.reader,generations,out_dir=Path(tmp)/'new',**kwargs)
        full=result['all_requested_observation']
        h=next(g for g in full['sector_groups'] if g['group']=='Health Care')['horizons']
        self.assertEqual((h['5']['stale_count'],h['5']['observed_count']), (3,0))
        self.assertIsNone(h['5']['observed_subset_median_return'])
        self.assertEqual((h['60']['missing_count'],h['60']['stale_count']), (3,0))
        self.assertFalse(full['currentness_verified'])

    def test_future_calendar_and_mismatched_comparisons_refuse_before_io(self):
        _,fixture,caller,_,_,kwargs,generations=self.fixture(6)
        for comparison, as_of in [('2026-10-12',kwargs['as_of']),('2026-10-14',kwargs['as_of']),
                                 ('2026-10-17','2026-10-18T00:00:00Z'),('2099-01-01',kwargs['as_of'])]:
            with self.subTest(comparison=comparison),tempfile.TemporaryDirectory() as tmp, \
                 patch.object(fixture.reader,'read_components',side_effect=AssertionError('EARLY_READER')):
                destination=Path(tmp)/'new'
                with self.assertRaisesRegex(caller.intake.IntakeError,'OBSERVATION_COMPARISON'):
                    tape.prepare_all_requested_research_roster(fixture.reader,generations,
                        comparison_session=comparison,out_dir=destination,**dict(kwargs,as_of=as_of))
                self.assertFalse(destination.exists())

    def test_ambiguous_and_duplicate_identities_keep_strict_pre_io_refusal(self):
        _,fixture,caller,ids,identities,kwargs,generations=self.fixture(6)
        ambiguous=json.loads(json.dumps(identities))
        ambiguous['rows'].append(dict(security_id='FIXTURE:US:OTHER',issuer_id='FIXTURE:ISSUER:OTHER',
            tickers=['TEST'],country='US',currency='USD'))
        bad=dict(kwargs,identities_raw=caller.intake.canonical(ambiguous))
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(fixture.reader,'read_components',side_effect=AssertionError('EARLY_READER')):
            for function in (tape.prepare_research_roster,tape.prepare_all_requested_research_roster):
                call_kwargs = bad if function is tape.prepare_all_requested_research_roster else dict(bad,
                    roster_raw=caller.intake.canonical(dict(scope='PRE_RANKING_RESEARCH_ROSTER',rows=[dict(ticker='TEST')])))
                with self.subTest(function=function.__name__),self.assertRaisesRegex(caller.intake.IntakeError,'OBSERVATION_EXACT_IDENTITY'):
                    function(fixture.reader,generations,out_dir=Path(tmp)/function.__name__,**call_kwargs)
            duplicate=dict(kwargs,roster_raw=caller.intake.canonical(dict(scope='PRE_RANKING_RESEARCH_ROSTER',rows=[dict(ticker='TEST'),dict(ticker='TEST')])))
            with self.assertRaisesRegex(caller.intake.IntakeError,'OBSERVATION_DUPLICATE_TICKER'):
                tape.prepare_all_requested_research_roster(fixture.reader,generations,out_dir=Path(tmp)/'dup',**duplicate)

    def test_source_integrity_rights_and_expiry_are_never_optional_absence(self):
        for mode in ('hash','expiry','rights'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as tmp:
                _,fixture,caller,ids,_,kwargs,generations=self.fixture(6)
                if mode=='hash':
                    item=next(f for f in fixture.data_spec['files'] if f['instrument']['instrument_id']==ids['NEG'])
                    fixture.transport.objects['shared-research-v1/objects/'+item['sha256']]+=b' '
                else:
                    fixture.data_spec['source']['expires_at' if mode=='expiry' else 'eligible_purposes'] = (
                        '2026-10-13T23:30:00Z' if mode=='expiry' else [])
                    generations={sid:fixture.generation() for sid in generations}
                destination=Path(tmp)/'new'
                with self.assertRaisesRegex(caller.intake.IntakeError,'OBSERVATION_SOURCE_REFUSED:'):
                    tape.prepare_all_requested_research_roster(fixture.reader,generations,out_dir=destination,**kwargs)
                self.assertFalse(destination.exists())


if __name__ == "__main__":
    unittest.main()
