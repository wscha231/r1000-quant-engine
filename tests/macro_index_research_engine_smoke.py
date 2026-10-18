"""Explicit standalone H1 acceptance tests; not registered in the common runner."""
import copy
import contextlib
from datetime import datetime, time, timedelta
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo
from types import SimpleNamespace

import numpy as np
import pandas as pd

from tools import macro_index_research_engine as engine


def config():
    return dict(schema='macro-index-research-config-v1', start='1996-01-01', end='2020-12-31',
        as_of='2026-10-17T14:00:00+00:00', horizons=[21,63,126,252], entry_delay=1,
        min_train=504, macro_min_train=60, initial=756, fold_size=252, comparison_start='2016-01-01',
        primary_metric='oos_mse_improvement', max_seconds=300, max_rss_bytes=1073741824,
        prior_exposed_families=336, parameter_search=False, preregistered_at_utc='2026-10-17T13:00:00+00:00')


def input_fixture(root):
    c=config();c['end']='2016-03-31'
    days=engine.mcal.get_calendar('NYSE').schedule(start_date='1996-01-02',end_date='1996-02-15').index
    rows=[]
    for sid in engine.PRICE_IDS:
        p=root/(sid+'.csv');p.write_bytes(pd.DataFrame({'date':days.strftime('%Y-%m-%d'),'close':np.arange(len(days))+100.}).to_csv(index=False).encode())
        rows.append(dict(dataset_id=sid,path=str(p),sha256=engine.sha(p.read_bytes()),byte_count=p.stat().st_size,
            row_count=len(days),identity_type='PRICE_INDEX',source_name='FIXTURE',source_url_or_drive_object_id='fixture',
            source_file_path=str(p),source_file_sha256=engine.sha(p.read_bytes()),frequency='daily',units='PRICE_INDEX',
            calendar_or_period_rule='XNYS',date_start=str(days[0].date()),date_end=str(days[-1].date()),
            observation_clock_definition='fixture',availability_clock_definition='fixture',vintage_policy='fixture',
            retrieved_at_utc=c['as_of'],rights_status='PRIVATE_RESEARCH_REFERENCE_ONLY',
            purpose_limit='EXPLORATORY_RESEARCH_ONLY',producer_or_normalizer_code_sha='0'*40))
    records=[dict(series=sid,observation_date='1996-01-01',vintage_date='1996-02-02',
        available_at='1996-02-03T05:00:00+00:00',effective_session='1996-02-05',realtime_end='9999-12-31',
        value=1.,published_at=None,evidence='alfred_date_archive') for sid in engine.MACRO_IDS]
    p=root/'macro.jsonl'
    for sid in engine.MACRO_IDS:
        rows.append(dict(rows[0],dataset_id=sid,path=str(p),source_file_path=str(p),identity_type='MACRO_SERIES',
            frequency='monthly',calendar_or_period_rule='MONTHLY_ALFRED_VINTAGE',date_start='1996-01-01',date_end='1996-01-01'))
    manifest=dict(schema='macro-index-research-input-v1',datasets=rows)
    def refresh():
        p.write_bytes(b''.join(engine.encoded(x) for x in records))
        for row in rows[3:]:
            row.update(sha256=engine.sha(p.read_bytes()),source_file_sha256=engine.sha(p.read_bytes()),byte_count=p.stat().st_size,
                       row_count=sum(x['series']==row['dataset_id'] for x in records))
    refresh()
    return c,manifest,records,refresh


class EngineTests(unittest.TestCase):
    def test_prices_reject_duplicates_bad_order_and_nonfinite(self):
        for raw in (b'date,date,close\n1996-01-02,1996-01-02,1\n',
                    b'date,close\n1996-01-02,1\n1996-01-02,2\n',
                    b'date,close\n1996-01-03,1\n1996-01-02,2\n',
                    b'date,close\n1996-01-02,inf\n', b'date,close\n1996-01-02,0\n',
                    b'date,close\n1996-01-02,1,extra\n'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):engine.price_frame(raw)
        self.assertEqual(len(engine.price_frame(b'date,close\n1996-01-02,1\n')),1)

    def test_strict_json_fixed_config_and_clock(self):
        for raw in (b'{"x":1,"x":2}', b'{"x":NaN}'):
            with self.assertRaises(ValueError):engine.read_json(raw)
        engine.validate_config(config())
        for key, value in (('entry_delay',0), ('min_train',True), ('parameter_search',True),
                           ('horizons',[1,21]), ('preregistered_at_utc','2027-01-01T00:00:00Z')):
            c=config();c[key]=value
            with self.assertRaises(ValueError):engine.validate_config(c)

    def test_file_hash_and_bytes_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'input';p.write_bytes(b'fixture')
            self.assertEqual(engine.verified_file(p,engine.sha(b'fixture'),7),b'fixture')
            with self.assertRaises(ValueError):engine.verified_file(p,'0'*64)
            with self.assertRaises(ValueError):engine.verified_file(p,engine.sha(b'fixture'),8)

    def test_label_gap_delay_and_maturity(self):
        x=pd.Series([10.,20.,30.,40.,50.,60.],index=pd.bdate_range('2000-01-03',periods=6))
        self.assertAlmostEqual(engine.labels(x,2).iloc[0],1.)
        self.assertTrue(engine.labels(x,2).iloc[-3:].isna().all())
        x.iloc[2]=np.nan
        self.assertTrue(engine.labels(x,2).iloc[:3].isna().all())

    def test_train_only_baseline_scaling_and_maximum_purge(self):
        n=1500; idx=pd.bdate_range('2000-01-03',periods=n)
        x=pd.Series(np.sin(np.arange(n)/31)+np.arange(n)/10000,index=idx)
        y=pd.Series(np.cos(np.arange(n)/73)/100,index=idx)
        c=config();first=900
        a, pred=engine.evaluate_pinned(x,y,21,c,first)
        changed=x.copy();changed.iloc[first:]+=5000
        b,_=engine.evaluate_pinned(changed,y,21,c,first)
        for key in ('training_feature_mean','training_feature_sd','training_target_mean','coefficient_per_train_sd'):
            self.assertEqual(a['folds'][0][key],b['folds'][0][key])
        self.assertEqual(a['entry_delay_sessions'],1)
        self.assertEqual(a['training_purge_sessions'],253)
        self.assertLess(a['folds'][0]['last_training_label_position'],first)
        self.assertEqual(a['folds'][0]['n_train'],first-253)
        self.assertEqual(len(pred),a['oos_rows'])

    def test_macro_revisions_never_enter_before_available_cutoff(self):
        schedule=engine.mcal.get_calendar('NYSE').schedule(start_date='2020-01-02',end_date='2020-04-15')
        def record(obs,vintage,value):
            available=datetime.combine(datetime.fromisoformat(vintage).date()+timedelta(days=1),time(),ZoneInfo('America/New_York'))
            return dict(series='UNRATE',observation_date=obs,vintage_date=vintage,value=value,
                        evidence='alfred_date_archive',available_at=available.isoformat(),realtime_end='9999-12-31')
        rows=[record('2019-12-01','2020-01-03',2.),record('2020-01-01','2020-02-07',3.),
              record('2020-02-01','2020-03-06',5.)]
        a,events=engine.macro_features({'UNRATE':rows},schedule)
        later=rows+[record('2020-01-01','2020-04-03',9999.)]
        b,_=engine.macro_features({'UNRATE':later},schedule)
        pd.testing.assert_series_equal(a['macro_change_UNRATE'].loc[:'2020-04-02'],b['macro_change_UNRATE'].loc[:'2020-04-02'])
        self.assertEqual(a['macro_change_UNRATE'].notna().sum(),2)
        for e in events:
            self.assertLessEqual(engine.instant(e['available_at']),engine.instant(e['decision_cutoff']))
        with self.assertRaises(ValueError):engine.macro_features({'UNRATE':[dict(rows[0],evidence='current_only')]},schedule)

    def test_manifest_calendar_gap_and_macro_integrity(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp);c=config()
            schedule=engine.mcal.get_calendar('NYSE').schedule(start_date=c['start'],end_date=c['end'])
            datasets=[]
            for sid in engine.PRICE_IDS:
                days=schedule.index if sid!='NASDAQ100' else schedule.index.delete(40)
                f=p/(sid+'.csv');f.write_bytes(pd.DataFrame({'date':days.strftime('%Y-%m-%d'),'close':np.arange(len(days))+100.}).to_csv(index=False).encode())
                datasets.append(dict(dataset_id=sid,path=str(f),sha256=engine.sha(f.read_bytes()),byte_count=f.stat().st_size,
                    row_count=len(days),identity_type='PRICE_INDEX',source_name='SYNTHETIC_FIXTURE',source_url_or_drive_object_id='fixture',
                    source_file_path=str(f),source_file_sha256=engine.sha(f.read_bytes()),frequency='daily',units='PRICE_INDEX',
                    calendar_or_period_rule='XNYS',date_start=str(days[0].date()),date_end=str(days[-1].date()),
                    observation_clock_definition='fixture',availability_clock_definition='fixture',vintage_policy='fixture',
                    retrieved_at_utc=c['as_of'],rights_status='PRIVATE_RESEARCH_REFERENCE_ONLY',
                    purpose_limit='EXPLORATORY_RESEARCH_ONLY',producer_or_normalizer_code_sha='0'*40))
            records=[]
            for sid in engine.MACRO_IDS:
                records.append(dict(series=sid,observation_date='1996-01-01',vintage_date='1996-02-02',
                    available_at='1996-02-03T05:00:00+00:00',effective_session='1996-02-05',realtime_end='9999-12-31',
                    value=1.,published_at=None,evidence='alfred_date_archive'))
            f=p/'macro.jsonl';f.write_bytes(b''.join(engine.encoded(r) for r in records))
            for sid in engine.MACRO_IDS:
                r=dict(datasets[0],dataset_id=sid,path=str(f),sha256=engine.sha(f.read_bytes()),byte_count=f.stat().st_size,
                    row_count=1,identity_type='MACRO_SERIES',source_file_path=str(f),source_file_sha256=engine.sha(f.read_bytes()),
                    frequency='monthly',calendar_or_period_rule='MONTHLY_ALFRED_VINTAGE',date_start='1996-01-01',date_end='1996-01-01')
                datasets.append(r)
            manifest=dict(schema='macro-index-research-input-v1',datasets=datasets)
            prices,_,_,audit,_=engine.load_inputs(manifest,c)
            self.assertEqual(len(audit['NASDAQ100']['missing_sessions']),1)
            self.assertTrue(pd.isna(prices['NASDAQ100'].iloc[40]))
            wrong=copy.deepcopy(manifest);wrong['datasets'][0]['dataset_id']='QQQ'
            with self.assertRaises(ValueError):engine.load_inputs(wrong,c)
            wrong=copy.deepcopy(manifest);wrong['datasets'][3]['rights_status']='UNKNOWN'
            with self.assertRaises(ValueError):engine.load_inputs(wrong,c)
            records[0]['evidence']='current_only';f.write_bytes(b''.join(engine.encoded(r) for r in records))
            for row in datasets[3:]:
                row.update(sha256=engine.sha(f.read_bytes()),source_file_sha256=engine.sha(f.read_bytes()),byte_count=f.stat().st_size)
            with self.assertRaises(ValueError):engine.load_inputs(manifest,c)

    def test_monthly_minimum_preserves_sparse_samples(self):
        idx=pd.bdate_range('2000-01-03',periods=2000);x=pd.Series(np.nan,index=idx)
        x.iloc[::21]=np.sin(np.arange(len(x.iloc[::21])))
        y=pd.Series(np.cos(np.arange(2000)/73)/100,index=idx)
        macro,_=engine.evaluate_pinned(x,y,21,config(),1600,kind='release')
        daily,_=engine.evaluate_pinned(x,y,21,config(),1600)
        self.assertEqual(macro['min_train_samples'],60);self.assertGreater(macro['oos_rows'],0)
        self.assertEqual(daily['oos_rows'],0)

    def test_short_technical_arm_has_its_own_warmup(self):
        idx=pd.bdate_range('2015-01-01',periods=1000)
        close=pd.Series(np.arange(1000)+100.,index=idx)
        full,_,short=engine.feature_views(close,close*2,{},'2016-01-01')
        first=idx.searchsorted(pd.Timestamp('2016-01-01'))
        self.assertTrue(short['distance_sma200'].iloc[first:first+199].isna().all())
        self.assertTrue(full['distance_sma200'].iloc[first:first+199].notna().all())
        self.assertTrue(short['momentum_240'].iloc[first:first+240].isna().all())

    def test_drawdown_recovery_censoring_and_gap_disclosure(self):
        x=pd.Series([100.,80.,np.nan,100.,110.,88.],index=pd.bdate_range('2020-01-01',periods=6))
        rows=engine.drawdowns(x,'SP500')
        self.assertEqual(len(rows),2)
        self.assertFalse(rows[0]['censored']);self.assertEqual(rows[0]['missing_sessions_in_episode'],1)
        self.assertTrue(rows[1]['censored']);self.assertIsNone(rows[1]['recovery_date'])
        self.assertAlmostEqual(rows[1]['drawdown'],-.2)

    def test_paired_comparison_is_deterministic_and_matches_dates(self):
        dates=pd.bdate_range('2000-01-03',periods=1000)
        a=[dict(date=str(dates[i].date()),position=i,mse_improvement=.1+np.sin(i)/100) for i in range(1000)]
        b=[dict(date=str(dates[i].date()),position=i,mse_improvement=-.1+np.sin(i)/100) for i in range(1000)]
        result=engine.paired_comparison(a,b)
        self.assertEqual(result,engine.paired_comparison(a,b))
        self.assertTrue(result['sign_reversal']);self.assertEqual(result['matched_rows'],1000)
        sparse_a=a[::5];sparse_b=b[::5]
        self.assertEqual(engine.paired_comparison(sparse_a,sparse_b)['original_session_span'],996)
        self.assertEqual(engine.paired_comparison(a[:20],b)['status'],'INDETERMINATE')

    def test_resource_limits_are_active_under_optimization(self):
        c=config();budget=engine.Budget(c)
        with patch.object(engine,'peak_rss',return_value=2**31):
            with self.assertRaises(ValueError):budget.check()
        budget.start-=301
        with self.assertRaises(ValueError):budget.check()

    def test_receipt_deterministic_runtime_separate_no_partial_publish(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp);manifest=p/'manifest.json';conf=p/'config.json'
            manifest.write_bytes(engine.encoded({'fixture':True}));conf.write_bytes(engine.encoded(config()))
            result=dict(metrics=[],input_bindings=[],calendar_sha256='0'*64,coverage={'SP500':{'study_rows':1}})
            with patch.object(engine,'study',return_value=(result,[],[],[],[])):
                engine.run(manifest,engine.sha(manifest.read_bytes()),conf,engine.sha(conf.read_bytes()),p/'a')
                engine.run(manifest,engine.sha(manifest.read_bytes()),conf,engine.sha(conf.read_bytes()),p/'b')
            for name in ('metrics.json','metrics.csv','predictions.csv','receipt.json'):
                self.assertEqual((p/'a'/name).read_bytes(),(p/'b'/name).read_bytes())
            with patch.object(engine,'study',side_effect=ValueError('fixture refusal')):
                with self.assertRaises(ValueError):engine.run(manifest,engine.sha(manifest.read_bytes()),conf,engine.sha(conf.read_bytes()),p/'failed')
            self.assertFalse((p/'failed').exists())

    def test_fixed_first_fold_is_blocked_without_moving_boundary_or_minimum(self):
        idx=pd.bdate_range('2000-01-03',periods=2500);positions=np.arange(len(idx));short_start=1000
        x=pd.Series(np.sin(positions/37),index=idx);short=x.copy();short.iloc[:short_start+240]=np.nan
        y=pd.Series(np.cos(positions/53)/100,index=idx);c=config();first=short_start+c['initial']
        long_result,_=engine.evaluate_pinned(x,y,21,c,first)
        short_result,_=engine.evaluate_pinned(short,y,21,c,first,short_start)
        self.assertEqual(long_result['folds'][0]['first_test_position'],first)
        self.assertGreater(short_result['folds'][0]['first_test_position'],first)
        plan=engine.paired_oos_plan(x,short,y,c,first,short_start)
        self.assertEqual(plan['status'],'BLOCKED_SHARED_OOS_COVERAGE')
        self.assertEqual(plan['first_test_position'],1756)
        self.assertEqual(plan['folds'][0]['short_train_samples'],263)
        self.assertEqual(plan['folds'][0]['required_train_samples'],504)
        self.assertEqual(plan['first_fold_structural_minimum_offset'],997)
        with patch.object(engine.np.linalg,'lstsq',side_effect=AssertionError('blocked pair must not fit')):
            a,ap,b,bp,detail=engine.evaluate_shared_pair(x,short,y,21,c,first,short_start)
        self.assertEqual((ap,bp),([],[]));self.assertEqual(a['status'],plan['status']);self.assertEqual(b['status'],plan['status'])
        self.assertFalse(detail['boundary_moved']);self.assertEqual(c,config())

    def test_sufficient_shared_grid_preserves_first_fold_and_rejects_missing_coverage(self):
        idx=pd.bdate_range('2000-01-03',periods=2400);p=np.arange(len(idx));x=pd.Series(np.sin(p/37),index=idx)
        short=x.copy();short.iloc[:1240]=np.nan;y=pd.Series(np.cos(p/53)/100,index=idx);c=config();first=1997
        a,ap,b,bp,plan=engine.evaluate_shared_pair(x,short,y,21,c,first,1000)
        self.assertEqual(plan['status'],'SHARED_OOS_VERIFIED');self.assertEqual(a['folds'][0]['first_test_position'],first)
        self.assertEqual(b['folds'][0]['n_train'],504);self.assertEqual([r['date'] for r in ap],[r['date'] for r in bp])
        mature=y.copy();mature.iloc[-253:]=np.nan
        aa,aap,bb,bbp,tail=engine.evaluate_shared_pair(x,short,mature,21,c,first,1000)
        self.assertEqual(tail['status'],'SHARED_OOS_VERIFIED');self.assertEqual([r['date'] for r in aap],[r['date'] for r in bbp])
        self.assertEqual(aa['folds'][0]['first_test_position'],first)
        short.iloc[first+1]=np.nan
        self.assertEqual(engine.paired_oos_plan(x,short,y,c,first,1000)['status'],'BLOCKED_SHARED_OOS_COVERAGE')

    def test_calendar_rules_are_exact_and_dataset_typed(self):
        with tempfile.TemporaryDirectory() as d:
            c,m,_,_=input_fixture(Path(d));engine.load_inputs(m,c)
            for index,rule in ((0,'MONTHLY_ALFRED_VINTAGE'),(0,'NOT_XNYS'),(0,'XNYS invented'),(3,'XNYS'),(3,'NOT_XNYS')):
                wrong=copy.deepcopy(m);wrong['datasets'][index]['calendar_or_period_rule']=rule
                with self.subTest(index=index,rule=rule),self.assertRaisesRegex(ValueError,'CALENDAR_RULE'):engine.load_inputs(wrong,c)

    def test_null_macro_pairs_remain_sparse_without_invented_values(self):
        schedule=engine.mcal.get_calendar('NYSE').schedule(start_date='2020-01-02',end_date='2020-04-15')
        rows=[]
        for obs,vintage,value in (('2019-12-01','2020-01-03',2.),('2020-01-01','2020-02-07',None),('2020-02-01','2020-03-06',5.)):
            available=datetime.combine(datetime.fromisoformat(vintage).date()+timedelta(days=1),time(),ZoneInfo('America/New_York'))
            rows.append(dict(series='UNRATE',observation_date=obs,vintage_date=vintage,value=value,
                evidence='alfred_date_archive',available_at=available.isoformat(),realtime_end='9999-12-31'))
        original=copy.deepcopy(rows);features,events=engine.macro_features({'UNRATE':rows},schedule)
        self.assertTrue(features['macro_change_UNRATE'].isna().all());self.assertEqual(events,[]);self.assertEqual(rows,original)
        rows[0]['value']=None;rows[1]['value']=3.
        features,events=engine.macro_features({'UNRATE':rows},schedule)
        self.assertEqual(features['macro_change_UNRATE'].notna().sum(),1);self.assertEqual(events[0]['value'],2.)
        with tempfile.TemporaryDirectory() as d:
            c,m,records,refresh=input_fixture(Path(d));records[0]['value']=None;refresh()
            _,_,_,audit,_=engine.load_inputs(m,c);self.assertEqual(audit['UNRATE']['missing_values'],1)

    def test_cli_malformed_objects_and_depth_are_redacted(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);p=root/'private-manifest';q=root/'private-config';valid=engine.encoded(config())
            invalid=(b'[]',b'1',b'"private-path"',b'{"x":'+b'['*1100+b'0'+b']'*1100+b'}')
            for raw in invalid:
                for target in ('manifest','config'):
                    p.write_bytes(raw if target=='manifest' else b'{}');q.write_bytes(raw if target=='config' else valid)
                    output=io.StringIO();error=io.StringIO()
                    with contextlib.redirect_stdout(output),contextlib.redirect_stderr(error):
                        result=engine.main(['--manifest',str(p),'--manifest-sha256',engine.sha(p.read_bytes()),'--config',str(q),
                            '--config-sha256',engine.sha(q.read_bytes()),'--output',str(root/'out')])
                    self.assertEqual(result,2);self.assertEqual(json.loads(output.getvalue()),dict(status='BLOCKED_RESEARCH_RUN',completed=False))
                    self.assertEqual(error.getvalue(),'');self.assertNotIn('private',output.getvalue());self.assertFalse((root/'out').exists())

    def test_input_and_parser_budget_precede_allocation_and_check_during_parsing(self):
        budget=engine.Budget(config())
        with patch.object(Path,'is_file',return_value=True),patch.object(Path,'is_symlink',return_value=False),\
             patch.object(Path,'stat',return_value=SimpleNamespace(st_size=1073741825,st_mode=0o100644)),\
             patch.object(engine.os,'open') as opened:
            with self.assertRaisesRegex(ValueError,'MEMORY_BUDGET'):engine.verified_file('fixture','0'*64,budget=budget)
            opened.assert_not_called()
        with patch.object(engine.timer,'monotonic',return_value=budget.start+301):
            with self.assertRaisesRegex(ValueError,'RUNTIME_BUDGET'):engine.read_json(b'{}',budget=budget)
        raw=b'{"rows":['+b'0,'*5000+b'0]}'
        with patch.object(engine.timer,'monotonic',side_effect=[budget.start]*3+[budget.start+301]*50):
            with self.assertRaisesRegex(ValueError,'RUNTIME_BUDGET'):engine.read_json(raw,budget=budget)

    def test_retrieval_bounds_price_close_and_macro_availability(self):
        with tempfile.TemporaryDirectory() as d:
            c,m,_,_=input_fixture(Path(d));engine.load_inputs(m,c)
            for index,clock,reason in ((0,'1996-02-15T20:59:59Z','PRICE_AFTER_RETRIEVAL'),
                                       (3,'1996-02-03T04:59:59Z','MACRO_AFTER_RETRIEVAL')):
                wrong=copy.deepcopy(m);wrong['datasets'][index]['retrieved_at_utc']=clock
                with self.assertRaisesRegex(ValueError,reason):engine.load_inputs(wrong,c)
            wrong=copy.deepcopy(m);wrong['datasets'][0]['retrieved_at_utc']='1996-02-15T21:00:00Z'
            engine.load_inputs(wrong,c)

    def test_early_close_retrieval_uses_actual_session_and_aware_clocks(self):
        with tempfile.TemporaryDirectory() as d:
            c,m,_,_=input_fixture(Path(d));p=Path(m['datasets'][0]['path'])
            raw=p.read_bytes()+b'2016-11-25,999\n';p.write_bytes(raw)
            row=m['datasets'][0];row.update(sha256=engine.sha(raw),source_file_sha256=engine.sha(raw),
                byte_count=len(raw),row_count=row['row_count']+1,date_end='2016-11-25',retrieved_at_utc='2016-11-25T13:00:00-05:00')
            engine.load_inputs(m,c)
            row['retrieved_at_utc']='2016-11-25T17:59:59Z'
            with self.assertRaisesRegex(ValueError,'PRICE_AFTER_RETRIEVAL'):engine.load_inputs(m,c)
            row['retrieved_at_utc']='2016-11-25T18:00:00'
            with self.assertRaisesRegex(ValueError,'AWARE_CLOCK_REQUIRED'):engine.load_inputs(m,c)

    def test_bootstrap_draws_trim_original_span_with_fixed_seed(self):
        n=760;p=np.arange(n);dates=pd.bdate_range('2000-01-03',periods=n)
        a=[dict(date=str(d.date()),position=i,mse_improvement=float(np.sin(i/71))) for i,d in enumerate(dates)]
        b=[dict(r,mse_improvement=r['mse_improvement']+float(i/n)) for i,r in enumerate(a)]
        got=engine.paired_comparison(a,b);rng=np.random.default_rng(0);starts=rng.integers(0,n,size=(1000,4))
        draws=np.array([np.concatenate([(np.arange(s,s+253)%n) for s in row])[:n].mean()/n for row in starts])
        np.testing.assert_allclose(got['ci95'],np.quantile(draws,[.025,.975]),rtol=1e-12)
        self.assertEqual(got['sampled_sessions_per_draw'],760);self.assertEqual(got['bootstrap_draws'],1000)

    def test_alfred_vintage_intervals_are_inclusive_and_nonoverlapping(self):
        with tempfile.TemporaryDirectory() as d:
            c,m,records,refresh=input_fixture(Path(d));original=copy.deepcopy(records[0])
            second=dict(original,vintage_date='1996-02-06',available_at='1996-02-07T05:00:00Z',effective_session='1996-02-07',value=2.)
            records.append(second);refresh()
            with self.assertRaisesRegex(ValueError,'OVERLAPPING_VINTAGE_INTERVALS'):engine.load_inputs(m,c)
            records[0]['realtime_end']='1996-02-05';refresh();engine.load_inputs(m,c)
            records[0]['realtime_end']='1996-02-06';refresh()
            with self.assertRaisesRegex(ValueError,'OVERLAPPING_VINTAGE_INTERVALS'):engine.load_inputs(m,c)
            records[0]['realtime_end']='1996-02-01';refresh()
            with self.assertRaisesRegex(ValueError,'VINTAGE_END'):engine.load_inputs(m,c)
            records[0]=original;records[-1]=copy.deepcopy(original);refresh()
            with self.assertRaisesRegex(ValueError,'MACRO_DUPLICATE'):engine.load_inputs(m,c)

    def test_revision_availability_must_follow_vintage_order(self):
        with tempfile.TemporaryDirectory() as d:
            c,m,records,refresh=input_fixture(Path(d));records[0].update(realtime_end='1996-02-05',
                available_at='1996-02-09T05:00:00Z',effective_session='1996-02-09')
            records.append(dict(records[0],vintage_date='1996-02-06',realtime_end='9999-12-31',
                available_at='1996-02-07T05:00:00Z',effective_session='1996-02-07'))
            refresh()
            with self.assertRaisesRegex(ValueError,'VINTAGE_AVAILABILITY_ORDER'):engine.load_inputs(m,c)
            records[0].update(available_at='1996-02-07T05:00:00Z',effective_session='1996-02-07');refresh()
            with self.assertRaisesRegex(ValueError,'VINTAGE_AVAILABILITY_ORDER'):engine.load_inputs(m,c)
            records[0].update(available_at='1996-02-03T05:00:00Z',effective_session='1996-02-05');refresh();engine.load_inputs(m,c)

    def test_censored_drawdown_stops_at_last_observed_price(self):
        x=pd.Series([100.,80.,np.nan,np.nan],index=pd.bdate_range('2020-01-02',periods=4))
        row=engine.drawdowns(x,'SP500')[0]
        self.assertEqual(row['observed_through'],'2020-01-03');self.assertEqual(row['duration_sessions'],1)
        self.assertTrue(row['censored']);self.assertIsNone(row['recovery_date'])

    def test_prediction_join_reserves_before_buffer_allocation(self):
        class HugeLogicalChunk:
            def __len__(self):return 1073741824
        with self.assertRaisesRegex(ValueError,'MEMORY_BUDGET'):
            engine.join_predictions([HugeLogicalChunk()],engine.Budget(config()))
        self.assertEqual(engine.join_predictions([b'a',b'b'],engine.Budget(config())),b'ab')

    def test_intraday_macro_waits_for_its_next_open_effective_session(self):
        schedule=engine.mcal.get_calendar('NYSE').schedule(start_date='2020-01-02',end_date='2020-02-14')
        rows=[dict(series='UNRATE',observation_date='2019-12-01',vintage_date='2020-01-03',
            value=2.,evidence='alfred_date_archive',available_at='2020-01-04T05:00:00Z',
            effective_session='2020-01-06',realtime_end='9999-12-31'),
            dict(series='UNRATE',observation_date='2020-01-01',vintage_date='2020-02-06',
            value=5.,evidence='alfred_date_archive',available_at='2020-02-07T16:00:00Z',
            effective_session='2020-02-10',realtime_end='9999-12-31')]
        original=copy.deepcopy(rows);features,events=engine.macro_features({'UNRATE':rows},schedule)
        self.assertTrue(pd.isna(features['macro_change_UNRATE'].loc['2020-02-07']))
        self.assertEqual(features['macro_change_UNRATE'].loc['2020-02-10'],3.)
        self.assertEqual(events[0]['available_at'],'2020-02-07T16:00:00Z')
        self.assertEqual(events[0]['admitted_at'],'2020-02-10T14:30:00+00:00');self.assertEqual(rows,original)

    def test_off_window_source_prices_still_obey_declared_calendar(self):
        with tempfile.TemporaryDirectory() as d:
            c,m,_,_=input_fixture(Path(d));row=m['datasets'][0];p=Path(row['path'])
            original=p.read_bytes()
            for day in ('1995-12-31','2016-04-02'):
                raw=(b'date,close\n'+day.encode()+b',90\n'+original.split(b'\n',1)[1]
                     if day<'1996' else original+day.encode()+b',90\n')
                p.write_bytes(raw);row.update(sha256=engine.sha(raw),source_file_sha256=engine.sha(raw),byte_count=len(raw),
                    row_count=len(engine.price_frame(raw)),date_start='1995-12-31' if day<'1996' else '1996-01-02',
                    date_end='1996-02-15' if day<'1996' else day)
                with self.assertRaisesRegex(ValueError,'OFF_CALENDAR_PRICE|PRICE_OBSERVATION_NOT_SESSION'):engine.load_inputs(m,c)

    def test_coalesced_revision_admission_preserves_original_clock_order(self):
        schedule=engine.mcal.get_calendar('NYSE').schedule(start_date='2020-01-02',end_date='2020-02-14')
        base=dict(series='UNRATE',observation_date='2019-12-01',vintage_date='2020-01-03',value=1.,
            evidence='alfred_date_archive',available_at='2020-01-04T05:00:00Z',effective_session='2020-01-06',realtime_end='9999-12-31')
        old=dict(base,observation_date='2020-01-01',vintage_date='2020-02-07',value=3.,
            available_at='2020-02-08T05:00:00Z',effective_session='2020-02-10',realtime_end='2020-02-07')
        new=dict(old,vintage_date='2020-02-08',value=5.,available_at='2020-02-09T05:00:00Z',realtime_end='9999-12-31')
        rows=[base,old,new];original=copy.deepcopy(rows)
        a,events=engine.macro_features({'UNRATE':rows},schedule)
        b,reverse=engine.macro_features({'UNRATE':list(reversed(rows))},schedule)
        pd.testing.assert_series_equal(a['macro_change_UNRATE'],b['macro_change_UNRATE'])
        self.assertEqual(a['macro_change_UNRATE'].loc['2020-02-10'],4.);self.assertEqual(events,reverse)
        self.assertEqual(events[0]['vintage_date'],'2020-02-08');self.assertEqual(rows,original)


if __name__=='__main__':
    unittest.main(verbosity=2)
