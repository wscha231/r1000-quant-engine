"""Maturity, observation-time, fixed forecasts and monthly trial regressions."""
import copy
from datetime import timedelta
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools import a4_macro_learning as l
from tools import a4_liquidity_analysis as a
from tools import macro_technical_study as study
from tools.macro_history_sources import digest,encoded


def sessions(n=20):
    schedule=l.mcal.get_calendar("NYSE").schedule(start_date="2018-01-01",end_date="2026-11-06").iloc[:n]
    return [dict(session=d.date().isoformat(),close_utc=t.isoformat()) for d,t in schedule.market_close.items()]


def fixture(n=20):
    days=sessions(n); cutoff=days[-1]["close_utc"]
    original=b"SYNTHETIC reviewed input export; not provider/PIT evidence"; sha=digest(original)
    observations=[]
    for i,day in enumerate(days):
        for sid,value in (("SOFR",4+np.sin(i/7)/10),("IORB",4)):
            raw=("observation_date,"+sid+"\n"+day["session"]+","+str(value)+"\n").encode()
            row=a.parse_original(raw,dict(source_id="fred:"+sid,collected_at=day["close_utc"]))[0]
            row["original_sha256"]=sha
            observations.append(row)
    price=100.;prices=[]
    for i,day in enumerate(days):
        if i>=2:price*=np.exp(.001*np.sin((i-2)/7)+.0002*np.cos((i-2)/11))
        prices.append(dict(session=day["session"],value=float(price),available_at=day["close_utc"],
            original_sha256=sha,return_basis="TOTAL_RETURN"))
    payload=dict(schema="a4-macro-learning-inputs-v1",sessions=days,cutoff=cutoff,
                 observations=observations,prices={"SPY":prices})
    policy=dict(schema="a4-learning-input-policy-v1",purpose="MACRO_RELATIONSHIP_RESEARCH",
        available_at=days[0]["close_utc"],expires_at=(l.free.utc(cutoff)+timedelta(days=2)).isoformat(),
        input_pins=[digest(encoded(payload))],reviewed_rights_pins=["a"*64],reviewed_source_receipt_pins=["b"*64],
        source_bindings={sha:dict(purpose="MACRO_RELATIONSHIP_RESEARCH",historical_use="FORWARD_CAPTURE_ONLY",
            rights_evidence_sha256="a"*64,source_receipt_sha256="b"*64,size_bytes=len(original),source_ids=["fred:SOFR","fred:IORB","price:SPY"])},
        trial_identity=dict(signal="A4 funding and bank relationships",mechanism="association research only",book="benchmark sector research",window="fixture"))
    return payload,policy,lambda expected:original


class LearningTests(unittest.TestCase):
    def test_all_declared_targets_horizons_outcomes_remain_present_when_insufficient(self):
        p,policy,resolve=fixture()
        result=l.fit_trial(p,policy,digest(encoded(policy)),resolve)
        self.assertEqual(result["tests_declared"],len(l.FEATURES)*14*7*3)
        self.assertEqual(set(r["target"] for r in result["results"]),set(a.TARGETS))
        self.assertTrue(all(r["status"]=="INSUFFICIENT_EVIDENCE" for r in result["results"]))
        self.assertFalse(result["automatic_promotion_allowed"])

    def test_no_external_pin_or_rights_or_original_bytes_means_no_fit(self):
        p,policy,resolve=fixture()
        for change in ("external_pin","rights","bytes","input_pin"):
            q=copy.deepcopy(policy);pin=digest(encoded(q));resolver=resolve
            if change=="external_pin":pin="c"*64
            if change=="rights":q["reviewed_rights_pins"]=[];pin=digest(encoded(q))
            if change=="bytes":resolver=lambda _:b"foreign"
            if change=="input_pin":q["input_pins"]=[];pin=digest(encoded(q))
            with self.subTest(change=change),self.assertRaises(ValueError): l.fit_trial(p,q,pin,resolver)

    def test_current_download_cannot_be_backdated_into_history(self):
        p,policy,resolve=fixture()
        p["observations"][0]["collected_at"]=p["cutoff"]
        policy["input_pins"]=[digest(encoded(p))]
        with self.assertRaisesRegex(ValueError,"BACKDATED_CURRENT"):
            l.fit_trial(p,policy,digest(encoded(policy)),resolve)

    def test_price_original_requires_the_target_specific_reviewed_source(self):
        p,policy,resolve=fixture()
        for source_ids in (["fred:SOFR","fred:IORB"],["fred:SOFR","fred:IORB","price:QQQ"]):
            q=copy.deepcopy(policy)
            next(iter(q["source_bindings"].values()))["source_ids"]=source_ids
            with self.subTest(source_ids=source_ids),self.assertRaisesRegex(ValueError,"PRICE_SOURCE_BINDING"):
                l.fit_trial(p,q,digest(encoded(q)),resolve)

    def test_future_versions_do_not_change_prior_feature_prefix(self):
        p,_,_=fixture()
        before=l.replay_features(p["observations"],p["sessions"])
        future={**p["observations"][0],"value":100,"available_at":(l.free.utc(p["cutoff"])+timedelta(days=1)).isoformat()}
        after=l.replay_features(p["observations"]+[future],p["sessions"])
        for key in before:pd.testing.assert_series_equal(before[key],after[key])

    def test_future_observation_cannot_become_a_past_feature(self):
        p,policy,resolve=fixture()
        p['observations'][0]['observation_date']=(l.free.utc(p['cutoff'])+timedelta(days=7)).date().isoformat()
        policy['input_pins']=[digest(encoded(p))]
        with self.assertRaisesRegex(ValueError,'OBSERVATION_AFTER_AVAILABILITY'):
            l.validate_inputs(p,policy,digest(encoded(policy)),resolve)
        with self.assertRaisesRegex(ValueError,'OBSERVATION_AFTER_AVAILABILITY'):
            l.replay_features(p['observations'],p['sessions'])
        p,policy,resolve=fixture()
        p['observations'][0].update(observation_date=p['sessions'][1]['session'],
                                   available_at=p['sessions'][1]['close_utc'])
        policy['input_pins']=[digest(encoded(p))]
        with self.assertRaisesRegex(ValueError,'OBSERVATION_AFTER_COLLECTION'):
            l.validate_inputs(p,policy,digest(encoded(policy)),resolve)
        with self.assertRaisesRegex(ValueError,'OBSERVATION_AFTER_COLLECTION'):
            l.replay_features(p['observations'],p['sessions'])

    def test_weekly_release_count_is_not_daily_sample_count(self):
        days=sessions(100);records=[]
        for i,d in enumerate(days):
            if pd.Timestamp(d["session"]).weekday()!=2:continue
            row=a.parse_original(("observation_date,DPSACBW027SBOG\n"+d["session"]+","+str(100+i)+"\n").encode(),
                dict(source_id="fred:DPSACBW027SBOG",collected_at=d["close_utc"]))[0]
            records.append(row)
        result=l.replay_features(records,days)["change_4_weeks:deposits_all"]
        self.assertLess(result.notna().sum(),len(records))
        self.assertTrue(all(d.weekday()==2 for d in result.dropna().index))

    def test_target_path_gap_and_one_day_volatility_remain_null(self):
        close=pd.Series([100.,110.,99.,120.,130.,140.])
        values=l.outcome_labels(close,2)
        self.assertAlmostEqual(values["return"].iloc[0],120/110-1)
        self.assertAlmostEqual(values["maximum_drawdown"].iloc[0],-.1)
        self.assertTrue(l.outcome_labels(close,1)["realized_volatility"].isna().all())
        close.iloc[2]=np.nan
        self.assertTrue(all(pd.isna(series.iloc[0]) for series in l.outcome_labels(close,2).values()))

    def test_labels_collected_after_test_fold_cannot_train_that_fold(self):
        x=pd.Series(np.sin(np.arange(1600)/7),index=pd.date_range("2018-01-01",periods=1600))
        y=x*.01
        decisions=pd.date_range("2018-01-01",periods=1600,tz="UTC")
        late=[decisions[-1]+timedelta(days=1)]*1600
        result=study.evaluate(x,y,1,label_available_at=late,decision_times=decisions)
        self.assertEqual(result["oos_rows"],0)
        early=study.evaluate(x,y,1,label_available_at=decisions,decision_times=decisions)
        self.assertGreater(early["oos_rows"],0)
        self.assertTrue(all(f["last_training_label_position"]<f["first_test_position"] for f in early["folds"]))

    def test_trial_write_once_idempotency_and_tamper_refusal(self):
        p,policy,resolve=fixture(); trial=l.fit_trial(p,policy,digest(encoded(policy)),resolve)
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(l.store_trial(trial,d),l.store_trial(trial,d))
            trial["automatic_promotion_allowed"]=True
            with self.assertRaises(ValueError):l.store_trial(trial,d)

    def test_trial_writer_and_restore_use_one_exact_size_budget(self):
        from tools.run_a4_research_cycle import restored_trials
        p,policy,resolve=fixture();trial=l.fit_trial(p,policy,digest(encoded(policy)),resolve)
        size=len(encoded(trial))
        with tempfile.TemporaryDirectory() as d:
            with patch.object(l,"MAX_TRIAL_BYTES",size-1),self.assertRaisesRegex(ValueError,"TRIAL_SIZE"):
                l.store_trial(trial,d)
            self.assertFalse((Path(d)/"trials").exists())
            with patch.object(l,"MAX_TRIAL_BYTES",size):
                l.store_trial(trial,d)
                self.assertEqual(restored_trials(d,p["cutoff"]),[trial])

    def test_monthly_weekly_cadence_and_no_automatic_promotion(self):
        first=l.cadence("2026-11-07T10:00:00Z")
        repeated=l.cadence("2026-11-07T10:00:00Z",previous_training_month=first["month"],previous_week=first["week"])
        self.assertTrue(first["monthly_trial_due"])
        self.assertFalse(repeated["monthly_trial_due"])
        self.assertFalse(repeated["weekly_score_due"])
        self.assertFalse(first["automatic_promotion_allowed"])

    def test_fixed_prediction_is_scored_only_after_whole_path_matures(self):
        p,_,_=fixture();days=p["sessions"]
        prediction=dict(target="SPY",horizon_sessions=5,outcome="return",estimate=.01,
            created_at=days[0]["close_utc"],decision_session=days[0]["session"])
        first=l.score_predictions([prediction],{"SPY":p["prices"]["SPY"][:3]},days[:3],days[2]["close_utc"])
        self.assertEqual(first[0]["status"],"PENDING_OR_MISSING_PATH")
        mature=l.score_predictions([prediction],p["prices"],days,p["cutoff"])
        self.assertEqual(mature[0]["status"],"MATURED")
        prediction["created_at"]=days[3]["close_utc"]
        with self.assertRaisesRegex(ValueError,"RETROSPECTIVE"):
            l.score_predictions([prediction],p["prices"],days,p["cutoff"])

    def test_scoring_reuses_paths_without_changing_order_or_missingness(self):
        p,_,_=fixture(300);days=p["sessions"]
        predictions=[dict(target="SPY",horizon_sessions=h,outcome=outcome,estimate=.01,
            created_at=days[i]["close_utc"],decision_session=days[i]["session"])
            for i in (0,1,2,295) for h in (5,252) for outcome in l.OUTCOMES]
        expected=[l.score_predictions([r],p["prices"],days,p["cutoff"])[0] for r in predictions]
        with patch.object(l,"price_series",wraps=l.price_series) as prices,patch.object(l,"outcome_labels",wraps=l.outcome_labels) as labels:
            actual=l.score_predictions(predictions,p["prices"],days,p["cutoff"])
            self.assertEqual(prices.call_count,1)
            self.assertEqual(labels.call_count,2)
        self.assertEqual(actual,expected)
        self.assertTrue(any(r["status"]=="PENDING_OR_MISSING_PATH" for r in actual))

    def test_do_not_repeat_remains_closed_for_rejected_identity(self):
        p,policy,resolve=fixture()
        identity=policy["trial_identity"]
        registry=dict(entries=[dict(identity,id="rejected",blocked_reuse=True)])
        with self.assertRaisesRegex(ValueError,"DO_NOT_REPEAT"):
            l.fit_trial(p,policy,digest(encoded(policy)),resolve,registry=registry)

    def test_real_expanding_fit_finds_synthetic_signal_without_promoting_it(self):
        p,policy,resolve=fixture(1600)
        trial=l.fit_trial(p,policy,digest(encoded(policy)),resolve)
        selected=[r for r in trial["results"] if r["target"]=="SPY" and r["horizon_sessions"]==1
                  and r["feature"]=="funding:sofr_minus_iorb" and r["outcome"]=="return"][0]
        self.assertEqual(selected["status"],"SHADOW_CANDIDATE")
        self.assertLessEqual(selected["family_q_value"],.05)
        self.assertGreater(selected["oos_mse_improvement"],0)
        self.assertLessEqual(selected["frozen_model"]["last_training_label_session"],p["sessions"][-1]["session"])
        self.assertFalse(trial["eligible_for_selector"])
        from tests.a4_liquidity_analysis_smoke import analyze,raw,NOW
        report=analyze([("fred:SOFR",raw("SOFR",[("2026-11-06",4.2)])),
                        ("fred:IORB",raw("IORB",[("2026-11-06",4)]))])
        release=dict(available_at="2026-11-06T23:00:00Z",expires_at="2026-11-09T00:00:00Z",reviewed_trial_pins=[])
        with self.assertRaisesRegex(ValueError,"RELEASE_NOT_REVIEWED"):
            l.forecast_release(report,trial,release,digest(encoded(release)))
        release["reviewed_trial_pins"]=[trial["trial_sha256"]]
        forecasts=l.forecast_release(report,trial,release,digest(encoded(release)))
        self.assertTrue(forecasts)
        self.assertTrue(all(not r["qualified_company_er"] for r in forecasts))
        self.assertFalse(report["portfolio_overlay_allowed"])
        # The current-session grace period must not admit a forecast after its
        # next-close entry. Reject before changing the report or storing it.
        late=copy.deepcopy(report);late['cutoff']='2026-11-09T21:05:00Z'
        late_policy={**release,'expires_at':'2026-11-10T00:00:00Z'}
        before=copy.deepcopy(late)
        with self.assertRaisesRegex(ValueError,'PREDICTION_ENTRY_WINDOW'):
            l.forecast_release(late,trial,late_policy,digest(encoded(late_policy)))
        self.assertEqual(late,before)
        # A fixed report replay cannot backdate a newly created cloud forecast.
        with self.assertRaisesRegex(ValueError,'PREDICTION_ENTRY_WINDOW'):
            l.forecast_release(report,trial,late_policy,digest(encoded(late_policy)),created_at=late['cutoff'])


if __name__=="__main__":unittest.main()
