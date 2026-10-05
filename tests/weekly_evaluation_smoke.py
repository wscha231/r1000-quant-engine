#!/usr/bin/env python3
"""Smoke checks for weekly mark-to-market evaluation sidecar."""
from __future__ import annotations

import tempfile
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.run_weekly_evaluation import px_cache_name, run


def _write_px(cache_dir: Path, ticker: str, start: str = "2026-01-02", periods: int = 70, step: float = 0.01) -> None:
    idx = pd.bdate_range(start=start, periods=periods)
    base = 100.0
    close = [base * ((1.0 + step) ** i) for i in range(periods)]
    df = pd.DataFrame(
        {
            "Open": close,
            "Close": close,
            "Adj Close": close,
            "Volume": [1_000_000] * periods,
        },
        index=idx,
    )
    df.to_parquet(cache_dir / px_cache_name(ticker))


def test_weekly_evaluation_marks_to_weekly_and_reports_staleness() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        latest = root / "outputs"
        reports = latest / "reports"
        cache = root / "cache_prices"
        out = root / "weekly"
        reports.mkdir(parents=True)
        cache.mkdir()

        for ticker in ["AAA", "BBB", "SPY", "QQQ"]:
            _write_px(cache, ticker)

        pd.DataFrame(
            [
                {"ticker": "AAA", "rebalance_date": "2026-01-30", "weight": 0.60, "Name": "AAA Inc", "sector": "Tech"},
                {"ticker": "BBB", "rebalance_date": "2026-01-30", "weight": 0.30, "Name": "BBB Inc", "sector": "Tech"},
                {"ticker": "AAA", "rebalance_date": "2026-02-27", "weight": 0.50, "Name": "AAA Inc", "sector": "Tech"},
                {"ticker": "BBB", "rebalance_date": "2026-02-27", "weight": 0.40, "Name": "BBB Inc", "sector": "Tech"},
            ]
        ).to_csv(reports / "main_monthly_weights.csv", index=False)
        pd.DataFrame(
            [
                {"rebalance_date": "2026-01-30", "next_rebalance_date": "2026-02-27"},
                {"rebalance_date": "2026-02-27", "next_rebalance_date": "2026-03-31"},
            ]
        ).to_csv(reports / "regime_by_month.csv", index=False)

        pd.DataFrame(
            [
                {"ticker": "AAA", "rebalance_date": "2026-01-30", "weight": 0.50},
                {"ticker": "BBB", "rebalance_date": "2026-02-27", "weight": 0.50},
            ]
        ).to_csv(reports / "concentrated_strategy_holdings.csv", index=False)
        pd.DataFrame(
            [
                {"rebalance_date": "2026-01-30", "next_rebalance_date": "2026-02-27"},
                {"rebalance_date": "2026-02-27", "next_rebalance_date": "2026-03-31"},
            ]
        ).to_csv(reports / "concentrated_strategy_monthly.csv", index=False)
        pd.DataFrame([{"ticker": "AAA", "rebalance_date": "2026-04-15", "feature_date": "2026-04-15"}]).to_csv(
            latest / "scored_latest.csv",
            index=False,
        )

        payload = run(latest, out, cache, stale_days_threshold=10)
        assert payload["status"] == "ok"
        assert payload["latest_scored_date"] == "2026-04-15"
        assert payload["primary_weekly_eval_date"] > "2026-03-31"
        assert payload["scored_vs_weekly_eval_lag_days"] <= 10
        assert (out / "weekly_equity_curve.csv").exists()
        assert (out / "weekly_freshness_audit.json").exists()
        assert (out / "weekly_freshness_audit.md").exists()

        curve = pd.read_csv(out / "weekly_equity_curve.csv")
        assert {"main", "concentrated"}.issubset(set(curve["portfolio_kind"]))
        assert curve["week_end_date"].max() > "2026-03-31"
        metrics = payload["metrics"]["main"]
        assert metrics["uses_stale_final_holdings_extension"] is True


class ResearchWeeklyCallerTests(__import__('unittest').TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.latest=self.root/'latest';self.reports=self.latest/'reports'
        self.reports.mkdir(parents=True);self.cache=self.root/'cache';self.cache.mkdir();self.out=self.root/'out'
        dates=pd.bdate_range('2026-01-02','2026-01-23')
        for name in ('AAA','SPY','QQQ'):
            pd.DataFrame({'Open':100.,'Close':100.,'Adj Close':100.,'Volume':1000000},index=dates).to_parquet(self.cache/px_cache_name(name))
        for name in ('main_monthly_weights.csv','concentrated_strategy_holdings.csv'):
            pd.DataFrame([dict(ticker='AAA',rebalance_date='2026-01-02',weight=1.)]).to_csv(self.reports/name,index=False)
        for name in ('regime_by_month.csv','concentrated_strategy_monthly.csv'):
            pd.DataFrame([dict(rebalance_date='2026-01-02',next_rebalance_date='2026-01-23')]).to_csv(self.reports/name,index=False)
        pd.DataFrame([dict(ticker='AAA',rebalance_date='2026-01-23',feature_date='2026-01-23')]).to_csv(self.latest/'scored_latest.csv',index=False)
        from unittest.mock import patch
        guard=patch('socket.socket',side_effect=RuntimeError('offline fixture'))
        guard.start();self.addCleanup(guard.stop)

    def data(self):
        return [dict(session=d,timestamp=d+'T21:00:00Z',nav=1.) for d in ('2026-01-09','2026-01-16','2026-01-23')]

    def measurement(self):
        from nav_metrics_v2_smoke import context,binding
        data=self.data();c=context(data,anchor_nav=1.,frequency='weekly')
        return {name:dict(full=c,valuation_binding=binding(data)) for name in ('main','concentrated')}

    def test_native_weekly_complete_research_and_legacy_default_parity(self):
        from tools import nav_metrics_v2 as nav
        legacy=run(self.latest,self.out,self.cache)
        self.assertEqual(legacy['status'],'ok')
        old={p.name:p.read_bytes() for p in self.out.iterdir()}
        out=run(self.latest,self.out,self.cache,measurement_contexts=self.measurement())
        self.assertEqual(out['status'],nav.COMPLETE,out)
        self.assertEqual(out['freshness_status'],'ok')
        self.assertFalse(out['valid_for_production'])
        for name,metric in out['metrics'].items():
            self.assertEqual(metric['status'],nav.COMPLETE,name)
            self.assertEqual(metric['annualization'],52)
            self.assertEqual(metric['starting_capital_usd'],1.)
            self.assertEqual(metric['total_return'],0.)
            self.assertIsNone(metric['sharpe_excess_rf'])
        self.assertEqual({p.name:p.read_bytes() for p in self.out.iterdir() if p.is_file()},old)
        dest=self.out/nav.NAMESPACE
        self.assertTrue((dest/'weekly_equity_curve.research_v2.csv').exists())
        self.assertFalse((dest/'weekly_equity_curve.csv').exists())

    def test_current_dates_do_not_certify_missing_or_invalid_measurement(self):
        import copy
        from tools import nav_metrics_v2 as nav
        complete=self.measurement()
        self.assertEqual(run(self.latest,self.out,self.cache,measurement_contexts=complete)['status'],nav.COMPLETE)
        for name in ('main','concentrated'):
            for kind in ('missing','malformed_entry','RF','NAV','clock'):
                with self.subTest(portfolio=name,kind=kind):
                    bad=copy.deepcopy(complete)
                    if kind=='missing':bad.pop(name)
                    elif kind=='malformed_entry':bad[name]=[]
                    elif kind=='RF':bad[name]['full'].pop('risk_free')
                    elif kind=='NAV':bad[name]['full']['nav_ref']['sha256']='0'*64
                    else:bad[name]['valuation_binding']['rows'][0]['timestamp']='2026-01-09T20:00:00Z'
                    out=run(self.latest,self.out,self.cache,measurement_contexts=bad)
                    self.assertEqual(out['status'],nav.BLOCKED,out)
                    self.assertEqual(out['freshness_status'],'unknown' if kind in {'missing','malformed_entry'} else 'ok')
                    self.assertEqual(out['metrics'][name]['status'],nav.BLOCKED)
                    self.assertFalse(out['metric_admission_complete'])
                    self.assertFalse(list((self.out/nav.NAMESPACE).glob('*.csv')))
                    self.assertIsNone(out['metrics'][name]['cagr'])
        out=run(self.latest,self.out,self.cache,measurement_contexts={})
        self.assertEqual(out['status'],nav.BLOCKED)

    def test_raw_weekly_rows_reject_duplicates_missing_strings_before_repair(self):
        from tools.run_weekly_evaluation import weekly_metrics,build_weekly_curve,normalize_holdings
        from tools import nav_metrics_v2 as nav
        from nav_metrics_v2_smoke import context,binding
        data=self.data();c=context(data,anchor_nav=1.,frequency='weekly')
        f=pd.DataFrame([dict(week_end_date=r['session'],valuation_time_utc=r['timestamp'],equity=r['nav']) for r in data])
        for bad in (f.iloc[::-1],f.iloc[:2],pd.concat([f,f.iloc[:1]]),f.assign(equity='1')):
            with self.subTest(rows=bad.to_dict('records')):
                before=bad.copy(deep=True)
                out=weekly_metrics(bad,'main',measurement_context=c)
                self.assertEqual(out['status'],nav.BLOCKED)
                pd.testing.assert_frame_equal(bad,before)
        # Duplicate final actual closes emitted by the native builder cannot be deduplicated in V2.
        from unittest.mock import patch
        holdings=normalize_holdings(pd.read_csv(self.reports/'main_monthly_weights.csv'),'main')
        with patch('tools.run_weekly_evaluation.weekly_targets',return_value=[pd.Timestamp('2026-01-09')]*2):
            curve,out=build_weekly_curve(holdings,{pd.Timestamp('2026-01-02'):pd.Timestamp('2026-01-23')},self.cache,'main',
                                        measurement_context=c,valuation_binding=binding(data))
        self.assertEqual(len(curve),2)
        self.assertEqual(out['status'],nav.BLOCKED)

    def test_generated_unit_base_and_partial_IO_fail_closed(self):
        import copy
        from unittest.mock import patch
        from tools import nav_metrics_v2 as nav
        from nav_metrics_v2_smoke import ref
        c=self.measurement();bad=copy.deepcopy(c)
        for name in bad:
            anchor=bad[name]['full']['anchor'];anchor['nav']=2.
            anchor['ref']=ref({k:v for k,v in anchor.items() if k!='ref'},'independently-bound-wrong-unit',anchor['timestamp'])
        out=run(self.latest,self.out,self.cache,measurement_contexts=bad)
        self.assertEqual(out['status'],nav.BLOCKED)
        for metric in out['metrics'].values():
            self.assertEqual(metric['reason'],'CALLER_WEEKLY_INITIAL_UNIT_MISMATCH')
            self.assertFalse(metric['supplied_net_account_nav'])
        original=pd.DataFrame.to_csv
        def fail_second_export(df,path,*args,**kwargs):
            if Path(path).name.startswith('concentrated_weekly_equity_curve.research_v2'):
                raise OSError('synthetic disk failure')
            return original(df,path,*args,**kwargs)
        inputs={p:p.read_bytes() for p in self.reports.iterdir()}
        with patch.object(pd.DataFrame,'to_csv',fail_second_export):
            out=run(self.latest,self.out,self.cache,measurement_contexts=c)
        self.assertEqual(out['status'],nav.BLOCKED)
        self.assertEqual(out['reason'],'RESEARCH_IO_FAILURE')
        self.assertFalse(list((self.out/nav.NAMESPACE).glob('*.csv')))
        self.assertEqual({p:p.read_bytes() for p in self.reports.iterdir()},inputs)

    def test_collision_and_physical_cache_alias_preserve_entire_input_namespace(self):
        from tools import nav_metrics_v2 as nav
        from unittest.mock import patch
        dest=self.cache/'bad'/nav.NAMESPACE;dest.mkdir(parents=True)
        sentinel=dest/'weekly_equity_curve.research_v2.csv';sentinel.write_bytes(b'input bytes')
        with patch('tools.run_weekly_evaluation._read_csv',side_effect=AssertionError('no source reads')):
            out=run(self.latest,self.cache/'bad',self.cache,measurement_contexts={})
        self.assertEqual(out['status'],nav.BLOCKED)
        self.assertEqual(sentinel.read_bytes(),b'input bytes')
        import os
        alias=self.root/'cache-alias'
        if os.name=='nt':
            import subprocess
            proc=subprocess.run(['cmd','/c','mklink','/J',str(alias),str(self.cache)],capture_output=True,text=True)
            self.assertEqual(proc.returncode,0,proc.stderr)
        else:alias.symlink_to(self.cache,target_is_directory=True)
        try:
            out=run(self.latest,alias/'bad',self.cache,measurement_contexts={})
            self.assertEqual(out['status'],nav.BLOCKED)
            self.assertEqual(sentinel.read_bytes(),b'input bytes')
        finally:
            alias.rmdir() if os.name=='nt' else alias.unlink()
        dest=self.out/nav.NAMESPACE;dest.mkdir(parents=True)
        protected=dest/'weekly_metrics.research_v2.json';protected.write_bytes(b'context input')
        note=dest/'weekly_equity_curve.research_v2.csv';note.write_bytes(b'other retained input')
        out=run(self.latest,self.out,self.cache,measurement_contexts={},measurement_context_path=protected)
        self.assertEqual(out['status'],nav.BLOCKED)
        self.assertEqual(protected.read_bytes(),b'context input');self.assertEqual(note.read_bytes(),b'other retained input')

    def test_research_IO_all_exports_and_cleanup_failures_are_bounded(self):
        from tools import nav_metrics_v2 as nav
        from unittest.mock import patch
        dest=self.out/nav.NAMESPACE
        before={p:p.read_bytes() for p in self.reports.iterdir()}
        original_csv=pd.DataFrame.to_csv;original_text=Path.write_text
        for scene in ('success','measurement_blocked'):
            options=self.measurement() if scene=='success' else {}
            calls=[];counter=0;fail_at=None
            def observe(path):
                nonlocal counter
                if Path(path).parent==dest:
                    counter+=1;calls.append(Path(path).name)
                    if counter==fail_at:raise OSError('export denied')
            def csv(df,path,*a,**kw):observe(path);return original_csv(df,path,*a,**kw)
            def text(path,*a,**kw):observe(path);return original_text(path,*a,**kw)
            with patch.object(pd.DataFrame,'to_csv',csv),patch.object(Path,'write_text',text):
                baseline=run(self.latest,self.out,self.cache,measurement_contexts=options)
            self.assertTrue(calls)
            self.assertEqual(baseline['status'],nav.COMPLETE if scene=='success' else nav.BLOCKED)
            for index,name in enumerate(tuple(calls),1):
                with self.subTest(scene=scene,write=index,name=name):
                    counter=0;calls=[];fail_at=index
                    with patch.object(pd.DataFrame,'to_csv',csv),patch.object(Path,'write_text',text):
                        out=run(self.latest,self.out,self.cache,measurement_contexts=options)
                    self.assertEqual(out['reason'],'RESEARCH_IO_FAILURE')
                    self.assertFalse(out['current_publication_complete']);self.assertTrue(out['cleanup_complete'])
                    self.assertIsNone(out['cagr']);self.assertFalse(out['valid_for_production'])
                    self.assertEqual({p:p.read_bytes() for p in self.reports.iterdir()},before)
                    self.assertFalse(list(dest.glob('*.research_v2.*')))
        original_mkdir=Path.mkdir;original_unlink=Path.unlink
        original_resolve=Path.resolve
        def resolve(path,*a,**kw):
            if path==dest:raise PermissionError('resolve denied')
            return original_resolve(path,*a,**kw)
        with patch.object(Path,'resolve',resolve):
            out=run(self.latest,self.out,self.cache,measurement_contexts={})
        self.assertEqual(out['reason'],'RESEARCH_IO_FAILURE');self.assertFalse(out['current_publication_complete'])
        def mkdir(path,*a,**kw):
            if path==dest:raise PermissionError('mkdir denied')
            return original_mkdir(path,*a,**kw)
        with patch.object(Path,'mkdir',mkdir):
            out=run(self.latest,self.out,self.cache,measurement_contexts={})
        self.assertEqual(out['reason'],'RESEARCH_IO_FAILURE');self.assertFalse(out['current_publication_complete'])
        names=('weekly_equity_curve.research_v2.csv','main_weekly_equity_curve.research_v2.csv',
               'concentrated_weekly_equity_curve.research_v2.csv','weekly_metrics.research_v2.json',
               'weekly_freshness_audit.research_v2.json','weekly_freshness_audit.research_v2.md')
        for name in names:
            with self.subTest(unlink=name):
                leaf=dest/name;leaf.write_bytes(b'prior output')
                def unlink(path,*a,**kw):
                    if path==leaf:raise PermissionError('unlink denied')
                    return original_unlink(path,*a,**kw)
                with patch.object(Path,'unlink',unlink):
                    out=run(self.latest,self.out,self.cache,measurement_contexts={})
                self.assertEqual(out['reason'],'RESEARCH_IO_FAILURE');self.assertFalse(out['cleanup_complete'])
                self.assertIn(name,out['uncleared_generated_outputs']);self.assertEqual(leaf.read_bytes(),b'prior output')
                leaf.unlink()
        metric=dest/'weekly_metrics.research_v2.json'
        def late_text(path,*a,**kw):
            if path.name=='weekly_freshness_audit.research_v2.md':raise OSError('late report failed')
            return original_text(path,*a,**kw)
        def retain_metric(path,*a,**kw):
            if path==metric:raise PermissionError('cleanup denied')
            return original_unlink(path,*a,**kw)
        with patch.object(Path,'write_text',late_text),patch.object(Path,'unlink',retain_metric):
            out=run(self.latest,self.out,self.cache,measurement_contexts=self.measurement())
        self.assertFalse(out['cleanup_complete']);self.assertFalse(out['current_publication_complete'])
        self.assertIn(metric.name,out['uncleared_generated_outputs']);self.assertTrue(metric.exists())
        original_lstat=nav.os.lstat
        def lstat(path,*a,**kw):
            if Path(path)==metric:raise PermissionError('stat denied')
            return original_lstat(path,*a,**kw)
        with patch.object(nav.os,'lstat',lstat):
            out=run(self.latest,self.out,self.cache,measurement_contexts={})
        self.assertEqual(out['reason'],'RESEARCH_IO_FAILURE');self.assertFalse(out['cleanup_complete'])
        self.assertTrue(metric.exists());self.assertFalse(out['current_publication_complete']);metric.unlink()
        def after_write_lstat(path,*a,**kw):
            if Path(path)==metric:
                try:original_lstat(path,*a,**kw)
                except FileNotFoundError:pass
                else:raise PermissionError('cleanup stat denied')
            return original_lstat(path,*a,**kw)
        with patch.object(Path,'write_text',late_text),patch.object(nav.os,'lstat',after_write_lstat):
            out=run(self.latest,self.out,self.cache,measurement_contexts=self.measurement())
        self.assertEqual(out['reason'],'RESEARCH_IO_FAILURE');self.assertFalse(out['cleanup_complete'])
        self.assertIn(metric.name,out['uncleared_generated_outputs']);self.assertTrue(metric.exists())

    def test_full_weekly_input_cone_reverse_aliases_and_disjoint_controls(self):
        from tools import nav_metrics_v2 as nav
        from unittest.mock import patch
        import os
        dest=self.out/nav.NAMESPACE;dest.mkdir(parents=True)
        names=('weekly_equity_curve.research_v2.csv','main_weekly_equity_curve.research_v2.csv',
               'concentrated_weekly_equity_curve.research_v2.csv','weekly_metrics.research_v2.json',
               'weekly_freshness_audit.research_v2.json','weekly_freshness_audit.research_v2.md')
        (self.latest/'portfolio_latest.csv').write_text('ticker,weight\nAAA,1.0\n')
        (self.latest/'orchestrator').mkdir();(self.latest/'orchestrator'/'unified_target_latest.json').write_text('{"targets":[]}')
        sources=[self.reports/n for n in ('main_monthly_weights.csv','concentrated_strategy_holdings.csv',
                  'regime_by_month.csv','concentrated_strategy_monthly.csv')]
        sources += [self.latest/'scored_latest.csv',self.latest/'portfolio_latest.csv',
                    self.latest/'orchestrator'/'unified_target_latest.json']
        sources += [self.cache/px_cache_name(n) for n in ('AAA','SPY','QQQ')]
        context_input=self.root/'context.json';context_input.write_text('{}');sources.append(context_input)
        original_resolve=Path.resolve
        for source in sources:
            for name in names:
                with self.subTest(source=source.name,output=name):
                    raw=source.read_bytes();leaf=dest/name;leaf.write_bytes(raw)
                    sentinel=dest/'caller-notes';sentinel.write_bytes(b'preserve')
                    def resolve(path,*a,**kw):
                        return original_resolve(leaf,*a,**kw) if path==source else original_resolve(path,*a,**kw)
                    with patch.object(Path,'resolve',resolve):
                        out=run(self.latest,self.out,self.cache,measurement_contexts={},measurement_context_path=context_input)
                    self.assertEqual(out['reason'],'caller_input_collides_with_weekly_research_output',out)
                    self.assertEqual(source.read_bytes(),raw);self.assertEqual(leaf.read_bytes(),raw)
                    self.assertEqual(sentinel.read_bytes(),b'preserve');leaf.unlink()
        # Hardlink unlink/replacement preserves distinct native source bytes.
        source=self.cache/px_cache_name('AAA');raw=source.read_bytes();leaf=dest/names[0];os.link(source,leaf)
        out=run(self.latest,self.out,self.cache,measurement_contexts=self.measurement())
        self.assertEqual(out['status'],nav.COMPLETE);self.assertEqual(source.read_bytes(),raw)
        if os.name!='nt':
            leaf.unlink();leaf.write_bytes(raw);source.unlink();source.symlink_to(leaf)
            try:
                out=run(self.latest,self.out,self.cache,measurement_contexts={})
                self.assertEqual(out['reason'],'caller_input_collides_with_weekly_research_output')
                self.assertEqual(leaf.read_bytes(),raw)
            finally:source.unlink();source.write_bytes(raw)

    def test_research_guard_does_not_swallow_programming_or_legacy_IO_errors(self):
        from unittest.mock import patch
        with patch('tools.run_weekly_evaluation.normalize_holdings',side_effect=ValueError('programming error')):
            with self.assertRaisesRegex(ValueError,'programming error'):
                run(self.latest,self.out,self.cache,measurement_contexts={})
        original=Path.mkdir
        def mkdir(path,*a,**kw):
            if path==self.out:raise OSError('legacy IO')
            return original(path,*a,**kw)
        with patch.object(Path,'mkdir',mkdir):
            with self.assertRaisesRegex(OSError,'legacy IO'):run(self.latest,self.out,self.cache)


    def test_opt_in_selected_input_read_and_stat_failures_propagate(self):
        from unittest.mock import patch
        from tools import nav_metrics_v2 as nav
        import tools.run_weekly_evaluation as weekly
        (self.latest/'portfolio_latest.csv').write_text('rebalance_date,cash_target\n2026-01-23,0\n')
        (self.latest/'orchestrator').mkdir(exist_ok=True)
        (self.latest/'orchestrator/unified_target_latest.json').write_text('{}')
        sources=[self.reports/n for n in ('main_monthly_weights.csv','concentrated_strategy_holdings.csv',
                   'regime_by_month.csv','concentrated_strategy_monthly.csv')]+[self.latest/n for n in
                   ('scored_latest.csv','portfolio_latest.csv','orchestrator/unified_target_latest.json')]+[self.cache/px_cache_name('AAA')]
        real_open=Path.open
        for source in sources:
            for stage in ('read','stat'):
                with self.subTest(source=str(source.relative_to(self.root)),stage=stage):
                    if stage=='read':
                        if source.suffix=='.parquet':
                            original=pd.read_parquet
                            def denied(p,*a,**kw):
                                if Path(p)==source:raise PermissionError('denied selected parquet')
                                return original(p,*a,**kw)
                            guard=patch.object(pd,'read_parquet',denied)
                        elif source.suffix=='.csv':
                            original=pd.read_csv
                            def denied(p,*a,**kw):
                                if isinstance(p,(str,Path)) and Path(p)==source:raise PermissionError('denied selected CSV')
                                return original(p,*a,**kw)
                            guard=patch.object(pd,'read_csv',denied)
                        else:
                            def denied(p,*a,**kw):
                                if p==source:raise PermissionError('denied selected JSON')
                                return real_open(p,*a,**kw)
                            guard=patch.object(Path,'open',denied)
                    else:
                        original=Path.stat
                        def denied(p,*a,**kw):
                            if p==source:raise PermissionError('denied selected stat')
                            return original(p,*a,**kw)
                        guard=patch.object(Path,'stat',denied)
                    with guard: out=run(self.latest,self.out,self.cache,measurement_contexts=self.measurement())
                    self.assertEqual(out.get('reason'),'RESEARCH_IO_FAILURE',out)
                    self.assertFalse(out['current_publication_complete']);self.assertIsNone(out['cagr'])
        absent=self.latest/'never_present.csv'
        self.assertTrue(weekly._read_csv(absent).empty);self.assertEqual(weekly._read_json(absent),{})
        self.assertTrue(weekly._read_csv(absent,strict_io=True).empty)
        self.assertEqual(weekly._read_json(absent,strict_io=True),{})
        self.assertTrue(weekly.load_price_series(self.cache,'NEVER_PRESENT',strict_io=True).empty)
        with patch.object(pd,'read_csv',side_effect=PermissionError('legacy read')):
            self.assertTrue(weekly._read_csv(sources[0]).empty)
        for source in (self.latest/'scored_latest.csv',self.latest/'portfolio_latest.csv',
                       self.latest/'orchestrator/unified_target_latest.json'):
            source.unlink()
        out=run(self.latest,self.out,self.cache,measurement_contexts=self.measurement())
        self.assertEqual(out['status'],nav.COMPLETE,out);self.assertEqual(out['freshness_status'],'unknown')
        (self.reports/'main_monthly_weights.csv').unlink()
        out=run(self.latest,self.out,self.cache,measurement_contexts=self.measurement())
        self.assertEqual(out['status'],nav.BLOCKED,out);self.assertIsNone(out['metrics']['main']['cagr'])

    def test_preflight_refusal_discloses_every_retained_generation_without_mutation(self):
        from unittest.mock import patch
        from tools import nav_metrics_v2 as nav
        names=('weekly_equity_curve.research_v2.csv','main_weekly_equity_curve.research_v2.csv',
               'concentrated_weekly_equity_curve.research_v2.csv','weekly_metrics.research_v2.json',
               'weekly_freshness_audit.research_v2.json','weekly_freshness_audit.research_v2.md')
        self.assertEqual(run(self.latest,self.out,self.cache,measurement_contexts=self.measurement())['status'],nav.COMPLETE)
        dest=self.out/nav.NAMESPACE;before={n:(dest/n).read_bytes() for n in names}
        source=self.reports/'main_monthly_weights.csv';real_resolve=Path.resolve
        for kind in ('input','directory','reverse_price','denied_stat'):
            with self.subTest(kind=kind):
                if kind=='input':
                    def resolve(p,*a,**kw):return real_resolve(source) if p==dest/names[0] else real_resolve(p,*a,**kw)
                    guard=patch.object(Path,'resolve',resolve)
                elif kind=='directory':
                    original=nav.research_output_kind
                    def probe(p):return 'other' if p==dest/names[0] else original(p)
                    guard=patch.object(nav,'research_output_kind',probe)
                elif kind=='reverse_price':
                    def resolve(p,*a,**kw):return real_resolve(dest/names[0]) if p==self.cache/px_cache_name('AAA') else real_resolve(p,*a,**kw)
                    guard=patch.object(Path,'resolve',resolve)
                else:
                    original=nav.os.lstat
                    def probe(p,*a,**kw):
                        if Path(p)==dest/names[0]:raise PermissionError('unknown retained leaf')
                        return original(p,*a,**kw)
                    guard=patch.object(nav.os,'lstat',probe)
                with guard:out=run(self.latest,self.out,self.cache,measurement_contexts=self.measurement())
                self.assertEqual(out['status'],nav.BLOCKED,out)
                self.assertFalse(out['current_publication_complete']);self.assertFalse(out['cleanup_complete'])
                self.assertEqual(set(out['uncleared_generated_outputs']),set(names))
                self.assertEqual(before,{n:(dest/n).read_bytes() for n in names})
        self.assertEqual(run(self.latest,self.out,self.cache,measurement_contexts=self.measurement())['status'],nav.COMPLETE)

    def test_weekly_context_package_rejects_unknown_keys_before_measurement(self):
        import copy
        from unittest.mock import patch
        from tools import nav_metrics_v2 as nav
        import tools.run_weekly_evaluation as weekly
        good=self.measurement()
        for where in ('top','main','concentrated'):
            for key in ('windows','ful','unexpected'):
                with self.subTest(where=where,key=key):
                    bad=copy.deepcopy(good);(bad if where=='top' else bad[where])[key]={}
                    with patch.object(weekly,'build_weekly_curve',side_effect=AssertionError('measurement before strict package check')):
                        out=run(self.latest,self.out,self.cache,measurement_contexts=bad)
                    self.assertEqual(out['status'],nav.BLOCKED,out)
                    self.assertFalse(out['metric_admission_complete'])
                    self.assertTrue(all(m['status']==nav.BLOCKED for m in out['metrics'].values()))
        for bad in ([],{'main':[],'concentrated':good['concentrated']},dict(main=good['main']),
                    {'main':dict(full=[]),'concentrated':good['concentrated']},
                    {'main':dict(full=good['main']['full'],valuation_binding=[]),'concentrated':good['concentrated']}):
            with self.subTest(shape=type(bad).__name__):
                out=run(self.latest,self.out,self.cache,measurement_contexts=bad)
                self.assertEqual(out['status'],nav.BLOCKED,out)
        self.assertEqual(run(self.latest,self.out,self.cache,measurement_contexts=good)['status'],nav.COMPLETE)


    def test_weekly_flow_and_RF_receipts_block_without_restamping_or_source_mutation(self):
        import copy
        from tools import nav_metrics_v2 as nav
        from nav_metrics_v2_smoke import ref
        good=self.measurement();self.assertEqual(run(self.latest,self.out,self.cache)['status'],'ok')
        official={p.name:p.read_bytes() for p in self.out.iterdir() if p.is_file()}
        inputs={p:p.read_bytes() for p in [*self.reports.iterdir(),*self.cache.iterdir(),self.latest/'scored_latest.csv'] if p.is_file()};dest=self.out/nav.NAMESPACE
        for portfolio in ('main','concentrated'):
            for kind in ('flow_empty','flow_zero','RF'):
                for valid in (False,True):
                    with self.subTest(portfolio=portfolio,kind=kind,valid=valid):
                        c=copy.deepcopy(good);m=c[portfolio]['full']
                        if kind.startswith('flow'):
                            f=m['external_flows']
                            if kind=='flow_zero':f['events']=[dict(timestamp=f['end'],amount=0.)]
                            f['ref']=ref({k:v for k,v in f.items() if k!='ref'},'actual-weekly-zero-flow',f['end'] if valid else f['start'])
                        else:m['risk_free']['ref']['available_at']=m['risk_free']['rows'][-1]['available_at'] if valid else m['anchor']['timestamp']
                        before=nav.encoded(c);self.assertEqual(run(self.latest,self.out,self.cache,measurement_contexts=good)['status'],nav.COMPLETE)
                        (dest/'caller_note.txt').write_bytes(b'preserve weekly note');result=run(self.latest,self.out,self.cache,measurement_contexts=c)
                        self.assertEqual(result['status'],nav.COMPLETE if valid else nav.BLOCKED,result);selected=result['metrics'][portfolio]
                        if not valid:
                            self.assertEqual(selected['status'],nav.BLOCKED);self.assertIsNone(selected['cagr'])
                            self.assertFalse(result['metric_admission_complete']);self.assertFalse(list(dest.glob('*.csv')))
                        else:self.assertEqual(selected['status'],nav.COMPLETE)
                        self.assertFalse(result['fullrun_allowed']);self.assertFalse(result['valid_for_production'])
                        self.assertEqual(nav.encoded(c),before);self.assertEqual({p:p.read_bytes() for p in inputs},inputs)
                        self.assertEqual({p.name:p.read_bytes() for p in self.out.iterdir() if p.is_file()},official)
                        self.assertEqual((dest/'caller_note.txt').read_bytes(),b'preserve weekly note')


def main() -> int:
    test_weekly_evaluation_marks_to_weekly_and_reports_staleness()
    import unittest
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ResearchWeeklyCallerTests))
    if not result.wasSuccessful():
        return 1
    print("weekly evaluation smoke passed")
    return 0




if __name__ == "__main__":
    raise SystemExit(main())
