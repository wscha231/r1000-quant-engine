"""Explicit standalone H1 acceptance tests; not registered in the common runner."""
import copy
from datetime import datetime, time, timedelta
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from tools import macro_index_research_engine as engine


def config():
    return dict(schema='macro-index-research-config-v1', start='1996-01-01', end='2020-12-31',
        as_of='2026-10-17T14:00:00+00:00', horizons=[21,63,126,252], entry_delay=1,
        min_train=504, macro_min_train=60, initial=756, fold_size=252, comparison_start='2016-01-01',
        primary_metric='oos_mse_improvement', max_seconds=300, max_rss_bytes=1073741824,
        prior_exposed_families=336, parameter_search=False, preregistered_at_utc='2026-10-17T13:00:00+00:00')


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


if __name__=='__main__':
    unittest.main(verbosity=2)
