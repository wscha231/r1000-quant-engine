#!/usr/bin/env python3
"""Offline regressions: publication leakage, revised data, labels and inference."""
from __future__ import annotations

from datetime import timezone
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import macro_history_sources as source
from tools import macro_technical_study as study


def alfred_page(rows):
    return source.encoded(dict(units="lin", output_type=1, count=len(rows), offset=0, observations=rows))


class EvidenceTests(unittest.TestCase):
    def test_current_history_is_not_backdated(self):
        rows, missing = source.parse_graph(b"observation_date,UNRATE\n2020-01-01,3.5\n2020-02-01,.\n", "UNRATE", "2020-01-01", "2020-02-28", "2026-09-11T12:00:00Z")
        self.assertEqual(rows[0]["available_at"], "2026-09-11T12:00:00Z")
        self.assertEqual(rows[0]["evidence"], "current_only")
        self.assertIsNone(rows[0]["published_at"])
        self.assertEqual(missing, ["2020-02-01"])
        with self.assertRaisesRegex(ValueError, "historical_vintage"):
            study.archive_release_changes(rows, [], [], "monthly")

    def test_bad_graph_schema_duplicate_and_nonfinite(self):
        for raw in (b"DATE,PAYEMS\n2020-01-01,1\n", b"DATE,UNRATE\n2020-01-01,1\n2020-01-01,2\n", b"DATE,UNRATE\n2020-01-01,inf\n", b"DATE,UNRATE\n2030-01-01,1\n"):
            with self.assertRaises(ValueError):
                source.parse_graph(raw, "UNRATE", "2020-01-01", "2020-12-31", "2026-09-11T12:00:00Z")

    def test_vintages_keep_revisions_and_conservative_dst(self):
        rows=[dict(date="2020-01-01", value="3.5", realtime_start="2020-02-07", realtime_end="2020-03-05"),
              dict(date="2020-01-01", value="3.6", realtime_start="2020-03-06", realtime_end="9999-12-31"),
              dict(date="2020-02-01", value="3.7", realtime_start="2020-03-06", realtime_end="9999-12-31")]
        parsed=source.parse_alfred([alfred_page(rows)], "UNRATE", "2020-01-01", "2020-03-31", "2026-09-11T00:00:00Z")
        self.assertEqual(len(parsed), 3)
        self.assertEqual(parsed[0]["available_at"], "2020-02-08T05:00:00+00:00")
        dates=pd.bdate_range("2020-02-06", "2020-03-10")
        closes=[d.to_pydatetime().replace(hour=21,tzinfo=timezone.utc) for d in dates]
        changes=study.archive_release_changes(parsed, dates, closes, "monthly")
        self.assertEqual(changes.dropna().index.tolist(), [pd.Timestamp("2020-03-09")])
        self.assertAlmostEqual(changes.dropna().iloc[0], .1)
        summer=[dict(date="2020-06-01",value="5",realtime_start="2020-07-02",realtime_end="9999-12-31")]
        summer_row=source.parse_alfred([alfred_page(summer)], "UNRATE", "2020-01-01", "2020-07-31", "2026-09-11T00:00:00Z")[0]
        self.assertEqual(summer_row["available_at"], "2020-07-03T04:00:00+00:00")

    def test_alfred_rejects_incomplete_and_overlapping_pages(self):
        row=dict(date="2020-01-01",value="3.5",realtime_start="2020-02-07",realtime_end="9999-12-31")
        for payload in [dict(units="lin",output_type=1,count=2,offset=0,observations=[row]),
                        dict(units="lin",output_type=1,count=2,offset=0,observations=[row,dict(row,realtime_start="2020-03-06")])]:
            with self.assertRaises(ValueError):
                source.parse_alfred([source.encoded(payload)],"UNRATE","2020-01-01","2020-03-31","2026-09-11T00:00:00Z")

    def test_missing_month_does_not_become_monthly_change(self):
        records=[]
        for period, available, value in [("2020-01-01","2020-02-08T05:00:00Z",3), ("2020-03-01","2020-04-04T04:00:00Z",4)]:
            records.append(dict(observation_date=period,available_at=available,value=value,realtime_end="9999-12-31",evidence="alfred_date_archive"))
        days=pd.bdate_range("2020-02-01","2020-04-10")
        closes=[d.to_pydatetime().replace(hour=21,tzinfo=timezone.utc) for d in days]
        self.assertTrue(study.archive_release_changes(records,days,closes,"monthly").isna().all())

    def test_objects_receipts_idempotency_and_tamper(self):
        with tempfile.TemporaryDirectory() as tmp:
            fetcher=lambda *args: ([b"DATE,UNRATE\n2020-01-01,3.5\n2020-02-01,3.6\n"], "2026-09-11T00:00:00Z")
            receipt, path=source.collect(tmp,["UNRATE"],"2020-01-01","2020-02-29",fetcher=fetcher)
            _, loaded=source.load_bundle(tmp,path)
            self.assertEqual(len(loaded["UNRATE"]),2)
            count=len(list((Path(tmp)/"objects").iterdir()))
            source.collect(tmp,["UNRATE"],"2020-01-01","2020-02-29",fetcher=fetcher)
            self.assertEqual(len(list((Path(tmp)/"objects").iterdir())),count)
            obj=Path(tmp)/"objects"/receipt["sources"][0]["records_sha256"]
            obj.write_text("[]")
            with self.assertRaisesRegex(ValueError,"object_hash"):
                source.load_bundle(tmp,path)

    def test_label_entry_maturity_and_gap(self):
        prices=pd.Series(np.arange(100.,115.),index=pd.bdate_range("2020-01-01",periods=15))
        result=study.labels(prices,5)
        self.assertAlmostEqual(result.iloc[0],106/101-1)
        self.assertTrue(result.iloc[-6:].isna().all())
        prices.iloc[3]=np.nan
        self.assertTrue(study.labels(prices,5).iloc[:4].isna().all())

    def test_features_have_no_future_dependency_and_single_cross(self):
        dates=pd.bdate_range("2000-01-01",periods=650)
        close=pd.Series(np.r_[np.linspace(200,80,300),np.linspace(80,240,350)],index=dates)
        features,_=study.technical_features(close,close)
        self.assertEqual(features["golden_cross_50_200"].sum(),1)
        self.assertEqual(features["relative_strength_60"].dropna().abs().max(),0)
        modified=close.copy(); modified.iloc[450:]*=20
        other,_=study.technical_features(modified,modified)
        for name in features:
            pd.testing.assert_series_equal(features[name].iloc[:450],other[name].iloc[:450])

    def test_walk_forward_purges_unmatured_labels(self):
        rng=np.random.default_rng(75)
        index=pd.bdate_range("2000-01-01",periods=1500)
        x=pd.Series(rng.normal(size=len(index)),index=index)
        y=pd.Series(.05*x+rng.normal(0,.02,len(index)),index=index)
        result=study.evaluate(x,y,63,initial=400,min_train=200,fold_size=200)
        self.assertGreater(result["oos_mse_improvement"],0)
        for fold in result["folds"]:
            self.assertLess(fold["last_training_label_position"],fold["first_test_position"])
        self.assertEqual(result["status"],"INSUFFICIENT_INDEPENDENT_EVIDENCE")

    def test_dependence_and_rare_events_do_not_pass(self):
        self.assertEqual(study.independent_windows(np.arange(1000),252),4)
        dates=pd.bdate_range("2000-01-01",periods=2000)
        x=pd.Series((np.arange(2000)%200==0).astype(float),index=dates)
        y=x*.1+.01
        result=study.evaluate(x,y,5,kind="event",initial=400,min_train=200)
        self.assertLess(result["event_count"],20)
        self.assertIsNone(result["p_value"])

    def test_multiple_testing_counts_unavailable_tests(self):
        results=[dict(p_value=.01,status="TESTED_SHADOW",oos_mse_improvement=.01,folds=[dict(mse_improvement=.01)]*3)]
        results += [dict(p_value=None,status="INSUFFICIENT_DATA") for _ in range(99)]
        study.adjust_family(results)
        self.assertEqual(results[0]["status"],"NO_INCREMENTAL_EVIDENCE")
        self.assertEqual(results[0]["family_q_value"],1)

    def test_due_plan_requires_actual_calendar(self):
        before={"UNRATE":dict(retrieved_at="2026-09-01T00:00:00Z")}
        events=[dict(series="UNRATE",release_at="2026-09-04T12:30:00Z")]
        plan={r["series"]:r for r in source.update_plan("2026-09-11T00:00:00Z",before,events)}
        self.assertEqual(plan["UNRATE"]["status"],"RELEASE_DUE")
        self.assertEqual(plan["PAYEMS"]["status"],"BACKFILL_REQUIRED")
        no_calendar={r["series"]:r for r in source.update_plan("2026-09-11T00:00:00Z",before,[])}
        self.assertEqual(no_calendar["UNRATE"]["status"],"CALENDAR_REFRESH_REQUIRED")


def run_tests():
    result=unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.loadTestsFromTestCase(EvidenceTests))
    if not result.wasSuccessful():
        raise AssertionError("macro_technical_evidence_smoke_failed")


if __name__ == "__main__":
    run_tests()
