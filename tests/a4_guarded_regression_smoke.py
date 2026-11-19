"""Synthetic leakage, extrapolation and domain counterexamples only."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
import pandas as pd
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools import a4_guarded_regression as guarded
from tools import a4_daily_direction as direction
from tools.macro_history_sources import digest, encoded


class GuardedRegression(unittest.TestCase):
    def setUp(self):
        self.rng=np.random.default_rng(287)

    def test_unseen_scale_and_novel_constant_fall_back(self):
        x=np.column_stack([np.linspace(-1,1,600),np.zeros(600)])
        y=.01+.02*x[:,0]
        test=np.array([[178.,0.],[0.,1.],[.3,0.]])
        pred,pin=guarded.predictions(x,y,test)
        np.testing.assert_allclose(pred[:2],y.mean(),rtol=0,atol=1e-15)
        self.assertEqual(pin['fallback_rows'],2)
        self.assertEqual(pin['novel_constant_rows'],1)
        self.assertNotAlmostEqual(pred[2],y.mean())

    def test_valid_target_domains_remain_valid(self):
        x=self.rng.normal(size=(600,8));test=self.rng.normal(size=(40,8))
        for y in (self.rng.uniform(-.9,2,600),self.rng.uniform(-.9,0,600),
                  self.rng.uniform(0,2,600)):
            pred,_=guarded.predictions(x,y,test)
            self.assertTrue(((pred>=y.min())&(pred<=y.max())).all())

    def test_batch_has_no_test_distribution_preprocessing(self):
        x=self.rng.normal(size=(600,5));y=self.rng.normal(size=600)
        one,pin=guarded.predictions(x,y,x[:1])
        many,pin2=guarded.predictions(x,y,np.vstack([x[:1],np.full((20,5),178.)]))
        np.testing.assert_array_equal(one,many[:1])
        self.assertEqual(pin['parameter_sha256'],pin2['parameter_sha256'])

    def test_future_inputs_and_labels_do_not_change_first_fold(self):
        dates=pd.bdate_range('2000-01-03',periods=1600)
        x=pd.DataFrame(self.rng.normal(size=(1600,4)),index=dates)
        y=self.rng.normal(0,.02,1600);complete=np.ones(1600,dtype=bool)
        a,base,folds=guarded.walk_forward(x,y,horizon=63,complete=complete)
        later=x.copy();later.iloc[1008:]=1e6
        later_y=y.copy();later_y[756:]=-1e6
        b,base2,_=guarded.walk_forward(later,later_y,horizon=63,complete=complete)
        np.testing.assert_array_equal(a[756:1008],b[756:1008])
        np.testing.assert_array_equal(base[756:1008],base2[756:1008])
        for f in folds:
            self.assertLess(f['last_training_label_position'],f['first_test_position'])
        c,_,_=guarded.walk_forward(x.iloc[:1008],y[:1008],horizon=63,complete=complete[:1008])
        np.testing.assert_array_equal(a[:1008],c)

    def test_ineligible_and_unmatured_rows_do_not_enter_training(self):
        dates=pd.bdate_range('2000-01-03',periods=1100)
        x=pd.DataFrame(self.rng.normal(size=(1100,2)),index=dates)
        y=self.rng.normal(size=1100);complete=np.ones(1100,dtype=bool);complete[10]=False
        a,_,_=guarded.walk_forward(x,y,horizon=21,complete=complete)
        x.iloc[10]=1e90;y[10]=1e90;y[734:]=1e90
        b,_,_=guarded.walk_forward(x,y,horizon=21,complete=complete)
        np.testing.assert_array_equal(a[756:1008],b[756:1008])

    def test_constant_and_invalid_inputs(self):
        p,pin=guarded.predictions(np.zeros((600,2)),np.ones(600),np.zeros((3,2)))
        np.testing.assert_array_equal(p,np.ones(3));self.assertEqual(pin['active_features'],0)
        for bad in (np.nan,np.inf,1e200):
            with self.assertRaises(ValueError):
                guarded.predictions(np.array([[0.,bad],[1.,0.]]),np.ones(2),np.ones((1,2)))

    def test_indexed_labels_and_cohort_must_match_exact_dates(self):
        dates=pd.bdate_range('2000-01-03',periods=1100)
        x=pd.DataFrame(self.rng.normal(size=(1100,2)),index=dates)
        y=pd.Series(self.rng.normal(size=1100),index=dates)
        complete=pd.Series(True,index=dates)
        a,_,_=guarded.walk_forward(x,y,horizon=21,complete=complete)
        b,_,_=guarded.walk_forward(x,y.to_numpy(),horizon=21,complete=complete.to_numpy())
        np.testing.assert_array_equal(a,b)
        with self.assertRaisesRegex(ValueError,'LABEL_INDEX'):
            guarded.walk_forward(x,y.iloc[::-1],horizon=21,complete=complete)
        with self.assertRaisesRegex(ValueError,'COHORT_INDEX'):
            guarded.walk_forward(x,y,horizon=21,complete=complete.iloc[::-1])


class DirectionJournal(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.calendar = direction.learning.mcal.get_calendar('NYSE').schedule('2017-01-01', '2022-03-01')

    def prepared(self, count):
        schedule = self.calendar.iloc[:count]
        frame = np.arange(count, dtype=float)
        close = 100*np.exp(frame/5000 + np.sin(frame/20)*.04)
        anchors = [t.to_pydatetime()+direction.timedelta(hours=1) for t in schedule.market_close]
        price_times = direction.timestamps([t.isoformat() for t in schedule.market_close])
        index = schedule.index
        return dict(days=index, anchors=anchors, clocks=direction.timestamps([t.isoformat() for t in anchors]),
                    closes={target: pd.Series(close.copy(), index=index) for target in direction.TARGETS},
                    panels={target: pd.DataFrame({'signal': np.sin(frame/20)}, index=index) for target in direction.TARGETS},
                    times={target: price_times.copy() for target in direction.TARGETS},
                    bases=dict.fromkeys(direction.TARGETS, 'TOTAL_RETURN'), feeds={target: 'fixture:'+target for target in direction.TARGETS},
                    cutoff=anchors[-1], policy_expires_at=anchors[-1]+direction.timedelta(days=4), input_sha256='a'*64, policy_sha256='b'*64)

    def test_replay_preserves_daily_predictions_when_future_inputs_and_labels_change(self):
        prefix = self.prepared(900)
        extended = self.prepared(1050)
        for target in direction.TARGETS:
            extended['closes'][target].iloc[900:] *= 1.5
            extended['panels'][target].iloc[900:] += 25
        result = direction.replay(prefix)
        future = direction.replay(extended)
        rows = result['predictions']
        self.assertEqual(len(rows), (900-756)*6)
        prior = {direction.row_key(row):row for row in rows}
        last_prefix = prefix['days'][-1].date().isoformat()
        other = {direction.row_key(row):row for row in future['predictions'] if row['decision_session'] <= last_prefix}
        self.assertEqual(len(prior), len(other))
        for key,row in prior.items():
            self.assertIn(key, other)
            self.assertAlmostEqual(row['estimate'], other[key]['estimate'], places=15)
            self.assertEqual(row['model_sha256'], other[key]['model_sha256'])
        for stat in result['summary']:
            h = stat['horizon_sessions']
            self.assertEqual(stat['matured'], 900-756-h-1)
            self.assertEqual(stat['pending'], h+1)
            self.assertEqual(stat['status'], 'INSUFFICIENT_EVIDENCE')
            self.assertLess(stat['nonoverlap_windows'], 20)
            self.assertIsNotNone(stat['past_mean_rmse'])

    def test_late_prices_are_excluded_from_training_and_scoring(self):
        prepared = self.prepared(900)
        first = next(row for row in direction.forecast(prepared) if row['target']=='SPY' and row['horizon_sessions']==21)
        original = first['train_rows']
        prepared['times']['SPY'][720] = prepared['clocks'][756]
        changed = next(row for row in direction.forecast(prepared) if direction.row_key(row)==direction.row_key(first))
        self.assertEqual(changed['train_rows'], original-23)
        prepared['times']['SPY'][778] = prepared['clocks'][-1]+1
        self.assertEqual(direction.score([first], prepared), [])
        prepared['times']['SPY'][778] -= 1
        matured = direction.score([first], prepared)[0]
        close = prepared['closes']['SPY']
        self.assertAlmostEqual(matured['realized_return'], close.iloc[778]/close.iloc[757]-1)

    def test_journal_reuses_session_and_settles_old_prediction_without_refitting_it(self):
        first, later = self.prepared(900), self.prepared(922)
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            receipt=direction.daily_journal(first, root, clock=lambda: first['cutoff'])
            path=next((root/'daily_direction').iterdir())
            frozen=path.read_bytes()
            self.assertEqual(receipt['current_forecasts'], 6)
            with patch.object(direction, 'forecast', side_effect=AssertionError('repeat fit')):
                second=direction.daily_journal(first, root, clock=lambda: first['cutoff']+direction.timedelta(minutes=3))
            self.assertEqual(receipt, second)
            self.assertEqual(path.read_bytes(), frozen)
            result=direction.daily_journal(later, root, clock=lambda: later['cutoff'])
            self.assertEqual([r['matured'] for r in result['summary']], [1,0,0,1,0,0])
            self.assertEqual(path.read_bytes(), frozen)
            path.write_bytes(frozen.replace(b'"train_rows":', b'"other_rows":', 1))
            with self.assertRaisesRegex(ValueError, 'STATE_IDENTITY'):
                direction.daily_journal(later, root, clock=lambda: later['cutoff'])

    def test_real_entry_clock_cannot_be_backdated(self):
        first=self.prepared(900)
        next_close=self.calendar.market_close.iloc[900].to_pydatetime()
        with tempfile.TemporaryDirectory() as temp, self.assertRaisesRegex(ValueError, 'FORWARD_ENTRY_CLOCK'):
            direction.daily_journal(first, Path(temp), clock=lambda: next_close)
        with tempfile.TemporaryDirectory() as temp:
            clocks=iter([first['cutoff'], next_close])
            with self.assertRaisesRegex(ValueError, 'FORWARD_ENTRY_CLOCK'):
                direction.daily_journal(first, Path(temp), clock=lambda: next(clocks))
            self.assertEqual(list(Path(temp).iterdir()), [])

    def test_adapter_requires_reviewed_clock_and_masks_delayed_benchmark_features(self):
        prepared = self.prepared(260)
        days = prepared['days']
        sessions = [dict(session=day.date().isoformat(), close_utc=close.isoformat())
                    for day, close in self.calendar.market_close.iloc[:len(days)].items()]
        original, receipt = 'a'*64, 'b'*64
        policy = dict(daily_direction_protocol_sha256=digest(encoded(direction.specification())),
                      trial_identity=dict(signal='x', mechanism='x', book='x', window='x'),
                      daily_direction_calendar_origin_session=sessions[0]['session'], reviewed_source_receipt_pins=[receipt],
                      expires_at='2030-01-01T00:00:00Z',
                      source_bindings={original:dict(historical_use='DATE_ARCHIVE_RESEARCH_ONLY', price_series_id='fixture')})
        prices={target:[dict(session=s['session'], available_at=s['close_utc'], value=100+i,
                            original_sha256=original,return_basis='TOTAL_RETURN') for i,s in enumerate(sessions)]
                for target in direction.TARGETS}
        prices['SPY'][-2]['available_at']=(prepared['anchors'][-2]+direction.timedelta(minutes=5)).isoformat()
        observations=[dict(logical_id=logical, source_id='rtdsm:'+logical) for logical in ('cpi','payrolls','unemployment')]
        payload=dict(sessions=sessions, prices=prices, observations=observations, cutoff=prepared['cutoff'].isoformat())
        macro=pd.DataFrame(1., index=days, columns=direction.daily.ECON)
        with patch.object(direction.learning, 'validate_inputs', return_value=days), \
             patch.object(direction, 'evaluate_candidate', return_value={'allowed':True}), \
             patch.object(direction.daily, 'macro_state', return_value=macro):
            with self.assertRaisesRegex(ValueError, 'PRICE_PUBLICATION_EVIDENCE'):
                direction.prepare(payload, policy, 'c'*64, None)
            policy['source_bindings'][original]['price_publication_clock_evidence_sha256']=receipt
            result=direction.prepare(payload, policy, 'c'*64, None)
        self.assertEqual(result['panels']['SPY'].shape[1], 21)
        self.assertTrue(result['panels']['SPY']['momentum_20'].iloc[-2:-1].isna().all())
        self.assertTrue(np.isfinite(result['panels']['SPY']['momentum_20'].iloc[-1]))
        self.assertTrue(np.isfinite(result['panels']['QQQ']['momentum_20'].iloc[-2]))


if __name__=='__main__':unittest.main()
