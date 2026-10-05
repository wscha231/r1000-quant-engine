"""Frozen E2 mathematical and source-binding families, synthetic inputs only."""
from __future__ import annotations
import copy
import json
import math
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from tools import nav_metrics_v2 as nav


def rows(values=(90.0, 95.0, 95.0)):
    days = ("2026-01-05", "2026-01-06", "2026-01-07")
    return [dict(session=d, timestamp=d+"T21:00:00Z", nav=value)
            for d,value in zip(days, values)]


def ref(value, identity, available):
    return dict(identity=identity, sha256=nav.digest(value), available_at=available)


def context(data, *, anchor_nav=100.0, anchor_time="2026-01-02T21:00:00Z",
            frequency="daily", rf_values=None, anchor_kind="PREFILL"):
    grid = [{k:r[k] for k in ("session", "timestamp")} for r in data]
    end = data[-1]["timestamp"]
    anchor = dict(kind=anchor_kind, timestamp=anchor_time, nav=anchor_nav)
    anchor["ref"] = ref(anchor.copy(), "synthetic-independent-anchor", anchor_time)
    rf_rows = []
    previous = anchor_time
    for r, value in zip(data, rf_values if rf_values is not None else [0.0]*len(data)):
        rf_rows.append(dict(start=previous, end=r["timestamp"], value=value, available_at=r["timestamp"]))
        previous = r["timestamp"]
    flow = dict(kind="ZERO_EXTERNAL_FLOW_ONLY", start=anchor_time, end=end, events=[])
    flow["ref"] = ref(flow.copy(), "synthetic-zero-flow-receipt", end)
    return dict(schema="nav-measurement-context-v2", frequency=frequency, cutoff=end,
                grid=dict(kind="INDEPENDENT_NYSE_REGULAR_CLOSE_GRID", rows=grid,
                          ref=ref(grid,"synthetic-independent-NYSE-grid",anchor_time)),
                anchor=anchor, nav_ref=ref(data,"synthetic-net-nav",end),
                risk_free=dict(kind="ACTUAL_INTERVAL_SIMPLE_RETURN", rows=rf_rows,
                               ref=ref(rf_rows,"synthetic-actual-interval-RF",end)),
                external_flows=flow)


def binding(data):
    points = [{k:r[k] for k in ("session","timestamp")} for r in data]
    return dict(rows=points, ref=ref(points,"synthetic-independent-valuation-clock",data[-1]["timestamp"]),
                cutoff=data[-1]["timestamp"])


def frame(data):
    import pandas as pd
    return pd.DataFrame([dict(date=r["session"], valuation_time_utc=r["timestamp"],
                              equity_usd=r["nav"], fill_mode="next_close") for r in data])


class NavMetricTests(unittest.TestCase):
    def assertBlocked(self, result):
        self.assertEqual(result["status"], nav.BLOCKED)
        self.assertFalse(result["metric_admission_complete"])
        for key in nav.METRIC_FIELDS:
            self.assertIsNone(result[key], key)
        self.assertFalse(result["valid_for_production"])
        json.dumps(result, allow_nan=False)

    def test_independent_anchor_includes_initial_loss_and_fee_once(self):
        for values, expected in (((90.0,90.0,90.0),-.1), ((99.0,99.0,99.0),-.01)):
            with self.subTest(values=values):
                data=rows(values); c=context(data)
                out=nav.calculate(data,c)
                self.assertEqual(out["status"],nav.COMPLETE)
                self.assertAlmostEqual(out["total_return"],expected)
                self.assertAlmostEqual(out["first_interval_return"],expected)
                self.assertAlmostEqual(out["max_dd"],expected)
                self.assertEqual(out["starting_capital_usd"],100.0)
                self.assertEqual(out["input_row_count"],3)
                self.assertEqual(out["cost_basis"],"SUPPLIED_NET_NAV_NO_SECOND_FEE")

    def test_elapsed_ACT_not_session_count_and_daily_RF_oracle(self):
        data=rows((101.0,103.02,106.1106))
        c=context(data,anchor_time="2026-01-04T21:00:00Z",rf_values=[.005,.006,.007])
        out=nav.calculate(data,c)
        self.assertEqual(out["status"],nav.COMPLETE)
        self.assertAlmostEqual(out["years"],3/365.25)
        self.assertAlmostEqual(out["sharpe_raw"],31.74901573277509,places=8)
        self.assertAlmostEqual(out["sharpe_excess_rf"],24.693678903269518,places=8)
        self.assertEqual(out["standard_deviation_ddof"],1)

    def test_anchor_missing_mismatch_naive_or_not_prior(self):
        data=rows()
        for mutate in ("missing","hash","first","naive","zero","bool","future_available"):
            with self.subTest(mutate=mutate):
                c=context(data)
                if mutate=="missing": c.pop("anchor")
                elif mutate=="hash": c["anchor"]["ref"]["sha256"]="0"*64
                elif mutate=="first": c["anchor"]["timestamp"]=data[0]["timestamp"]
                elif mutate=="naive": c["anchor"]["timestamp"]="2026-01-02T21:00:00"
                elif mutate=="zero": c["anchor"]["nav"]=0
                elif mutate=="bool": c["anchor"]["nav"]=True
                else: c["anchor"]["ref"]["available_at"]="2026-01-05T21:00:00Z"
                self.assertBlocked(nav.calculate(data,c))

    def test_original_rows_missing_extra_duplicate_shuffled_and_bad_clocks(self):
        data=rows(); c=context(data)
        cases=[data[:2],data+[data[-1]], [data[0],data[0],data[2]],data[::-1]]
        for key,value in (("session","2026-01-10"),("timestamp","2026-01-05T20:00:00Z"),
                          ("timestamp","2026-01-05T21:00:00"),("timestamp",None)):
            bad=copy.deepcopy(data);bad[0][key]=value;cases.append(bad)
        for bad in cases:
            with self.subTest(bad=bad):
                before=copy.deepcopy(bad)
                self.assertBlocked(nav.calculate(bad,c))
                self.assertEqual(bad,before)

    def test_strict_NAV_family_is_never_coerced_dropped_or_epsilon_repaired(self):
        for value in ("90",True,None,0,-1,float("inf"),float("nan")):
            with self.subTest(value=value):
                data=rows();c=context(data);data[1]["nav"]=value
                self.assertBlocked(nav.calculate(data,c))

    def test_independent_grid_hash_clocks_domain_and_order(self):
        for mutate in ("hash","kind","duplicate","order","future","not_close","late_receipt"):
            with self.subTest(mutate=mutate):
                data=rows();c=context(data);g=c["grid"]
                if mutate=="hash":g["ref"]["sha256"]="0"*64
                elif mutate=="kind":g["kind"]="PRICE_DATE_UNION"
                elif mutate=="duplicate":g["rows"][1]=g["rows"][0]
                elif mutate=="order":g["rows"]=g["rows"][::-1]
                elif mutate=="future":g["rows"][2]["timestamp"]="2026-01-08T21:00:00Z"
                elif mutate=="not_close":g["rows"][0]["timestamp"]="2026-01-05T15:00:00Z"
                else:g["ref"]["available_at"]=data[1]["timestamp"]
                self.assertBlocked(nav.calculate(data,c))

    def test_RF_missing_alignment_quote_identity_and_future_family(self):
        for mutate in ("missing","drop","duplicate","shift","extra","quote","hash","identity","future","nonfinite"):
            with self.subTest(mutate=mutate):
                data=rows();c=context(data); rf=c["risk_free"]
                if mutate=="missing":c.pop("risk_free")
                elif mutate=="drop":rf["rows"].pop()
                elif mutate=="duplicate":rf["rows"][1]=rf["rows"][0]
                elif mutate=="shift":rf["rows"][0]["start"]="2026-01-03T21:00:00Z"
                elif mutate=="extra":rf["rows"].append(rf["rows"][-1])
                elif mutate=="quote":rf["kind"]="ANNUAL_YIELD"
                elif mutate=="hash":rf["ref"]["sha256"]="0"*64
                elif mutate=="identity":rf["ref"]["identity"]=""
                elif mutate=="future":rf["rows"][0]["available_at"]="2026-01-06T21:00:00Z"
                else:rf["rows"][0]["value"]=float("inf")
                if mutate not in ("hash","identity","nonfinite","missing"):
                    rf["ref"]=ref(rf["rows"],"actual-rf",data[-1]["timestamp"])
                self.assertBlocked(nav.calculate(data,c))

    def test_external_deposit_withdrawal_untimed_and_scope_reject(self):
        for amount in (50.0,-50.0,True,None):
            with self.subTest(amount=amount):
                data=rows(); c=context(data);f=c["external_flows"]
                f["events"]=[dict(timestamp=data[0]["timestamp"],amount=amount)]
                f["ref"]=ref({k:v for k,v in f.items() if k!="ref"},"bound-flow",data[-1]["timestamp"])
                self.assertBlocked(nav.calculate(data,c))
        for mutate in ("missing","scope","untimed","kind","hash"):
            with self.subTest(mutate=mutate):
                data=rows();c=context(data);f=c["external_flows"]
                if mutate=="missing":c.pop("external_flows")
                elif mutate=="scope":f["start"]=data[0]["timestamp"]
                elif mutate=="untimed":f["events"]=[dict(amount=0.0)]
                elif mutate=="kind":f["kind"]="INFER_ZERO"
                else:f["ref"]["sha256"]="0"*64
                self.assertBlocked(nav.calculate(data,c))

    def test_zero_variance_and_one_interval_unavailable_without_epsilon(self):
        for data in (rows((100.,100.,100.)), rows((100.,))):
            with self.subTest(length=len(data)):
                out=nav.calculate(data,context(data))
                self.assertEqual(out["status"],nav.COMPLETE)
                self.assertIsNone(out["sharpe_raw"]);self.assertIsNone(out["sharpe_excess_rf"])
                self.assertIn(out["statistic_reasons"]["sharpe_raw"],("ZERO_VARIANCE","INSUFFICIENT_SAMPLE"))

    def test_derived_ratio_power_variance_overflow_is_bounded_finite_JSON(self):
        scenarios=[(rows((1e308,1e308,1e308)),1e-308,"2026-01-02T21:00:00Z"),
                   (rows((1e100,1e-100,1e100)),1e-100,"2026-01-02T21:00:00Z"),
                   (rows((2.,)),1.,"2026-01-05T20:59:59.999999Z")]
        for data,anchor,time in scenarios:
            with self.subTest(anchor=anchor,time=time):
                self.assertBlocked(nav.calculate(data,context(data,anchor_nav=anchor,anchor_time=time)))

    def test_weekly_declared_grid_and_annualization_are_diagnostic(self):
        data=[dict(session=d,timestamp=d+"T21:00:00Z",nav=n) for d,n in
              (("2026-01-09",101.),("2026-01-16",103.02),("2026-01-23",106.1106))]
        out=nav.calculate(data,context(data,frequency="weekly",rf_values=[.005,.006,.007]))
        self.assertEqual(out["status"],nav.COMPLETE)
        self.assertAlmostEqual(out["sharpe_excess_rf"],.014/.009*math.sqrt(52),places=8)
        self.assertEqual(out["annualization"],52)
        self.assertFalse(out["historical_pit_certified"])

    def test_UTC_equivalent_close_and_declared_early_close_controls(self):
        data=rows(); c=context(data)
        data[0]["timestamp"]="2026-01-05T16:00:00-05:00"
        c["nav_ref"]=ref(data,"same-NAV-source",c["cutoff"])
        self.assertEqual(nav.calculate(data,c)["status"],nav.COMPLETE)
        data=[dict(session="2026-11-27",timestamp="2026-11-27T18:00:00Z",nav=100.)]
        c=context(data,anchor_time="2026-11-25T21:00:00Z")
        self.assertEqual(nav.calculate(data,c)["status"],nav.COMPLETE)

    def test_actual_calendar_holidays_gaps_DST_and_false_halfday(self):
        for data in ([dict(session='2026-01-19',timestamp='2026-01-19T21:00:00Z',nav=100.)],
                     [rows()[0],rows()[2]],
                     [dict(session='2026-01-05',timestamp='2026-01-05T18:00:00Z',nav=100.)]):
            with self.subTest(data=data):
                self.assertBlocked(nav.calculate(data,context(data)))
        data=[dict(session='2026-07-01',timestamp='2026-07-01T20:00:00Z',nav=100.)]
        self.assertEqual(nav.calculate(data,context(data,anchor_time='2026-06-30T20:00:00Z'))['status'],nav.COMPLETE)

    def test_reference_byte_hash_and_future_clock_fail_closed(self):
        data=rows()
        for key in ("nav_ref","anchor","grid","external_flows","risk_free"):
            with self.subTest(key=key):
                c=context(data);r=c[key] if key=="nav_ref" else c[key]["ref"]
                r["available_at"]="2026-01-08T21:00:00Z"
                self.assertBlocked(nav.calculate(data,c))

    def test_resource_limits_and_duplicate_JSON_are_bounded(self):
        import tempfile
        data=rows();c=context(data)
        with patch.object(nav,"MAX_ROWS",2):
            self.assertBlocked(nav.calculate(data,c))
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"ctx.json";path.write_text('{"schema":1,"schema":2}',encoding="utf-8")
            with self.assertRaises(nav.MetricError):nav.load_context(path)

    def test_source_and_context_objects_are_not_mutated_by_measurement(self):
        data=rows();c=context(data);before=copy.deepcopy((data,c))
        out=nav.calculate(data,c)
        self.assertEqual((data,c),before)
        self.assertEqual(out["status"],nav.COMPLETE)
        self.assertFalse(out["valid_for_production"]);self.assertFalse(out["eligible_for_selector"])
        self.assertFalse(out["production_activation_allowed"]);self.assertFalse(out["fullrun_allowed"])
        self.assertNotEqual(out["status"],"completed")
        self.assertEqual(out["metric_mode"],nav.MODE)


if __name__ == "__main__":
    unittest.main(verbosity=2)

