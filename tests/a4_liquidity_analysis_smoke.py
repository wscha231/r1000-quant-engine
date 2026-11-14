"""Funding, H8 definitions, original normalization and v1/v2 integration."""
import copy
from datetime import date, timedelta
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import a4_liquidity_analysis as a
from tools import market_analysis_engine as m
from tools import a4_macro_bridge as bridge

NOW = "2026-11-07T10:00:00Z"
COLLECTED = "2026-11-06T22:00:00Z"
SESSION = "2026-11-06"


def raw(sid, values):
    return ("observation_date,"+sid+"\n"+"".join(d+","+str(v)+"\n" for d,v in values)).encode()


def rows(sid, values):
    return a.parse_original(raw(sid, values), dict(source_id="fred:"+sid, collected_at=COLLECTED))


def h10_rows(start="2026-11-02", collected="2026-11-14T03:35:42Z"):
    point = a.parse_original(raw("DTWEXBGS", [(start, 120)]),
                             dict(source_id="fred:DTWEXBGS", collected_at=collected))[0]
    return [dict(point, source_id="frb:H10_BROAD", observation_date=(date.fromisoformat(start)+timedelta(days=n)).isoformat(),
                 value=120+n, collected_at=collected, available_at=collected) for n in range(5)]


def analyze(sources):
    entries, blobs = [], {}
    for n, (sid, body) in enumerate(sources):
        path = "source"+str(n)+".raw"; blobs[path] = body
        entries.append(dict(kind="macro_v2", path=path, source_id=sid, sha256=m.sha(body),
                            status="COLLECTED", collected_at=COLLECTED))
    request = dict(schema=m.REQUEST_SCHEMA_V2, market="US", session=SESSION, inputs=entries,
                   available_at="2026-11-07T09:00:00Z", expires_at="2026-11-08T09:00:00Z")
    body = json.dumps(request).encode()
    return m.analyze(body, blobs, expected_sha=m.sha(body), cutoff=NOW, session=SESSION)


class LiquidityTests(unittest.TestCase):
    def test_h10_daily_observations_follow_weekly_publication_without_changing_clocks(self):
        history = h10_rows()
        out = a.summarize(history, "2026-11-14T06:36:37Z")
        self.assertEqual(out["status"], "OBSERVED")
        self.assertEqual(out["observation_date"], "2026-11-06")
        self.assertEqual(out["max_age_days"], 7)
        self.assertEqual(out["available_at"], history[-1]["available_at"])
        self.assertIsNone(out["published_at"])
        self.assertFalse(out["historical_pit_certified"])
        calendar = out["publication_freshness"]
        self.assertEqual(calendar["latest_scheduled_release_at"], "2026-11-09T21:15:00+00:00")
        self.assertEqual(calendar["next_scheduled_release_at"], "2026-11-16T21:15:00+00:00")
        self.assertFalse(calendar["scheduled_times_are_actual_availability"])
        self.assertTrue(a.current_observation(out, "2026-11-14T06:36:37Z"))

    def test_h10_release_boundary_and_fresh_fetch_cannot_renew_the_old_week(self):
        before = "2026-11-16T21:14:59Z"
        at = "2026-11-16T21:15:00Z"
        history = h10_rows()
        point = a.summarize(history, before)
        self.assertTrue(a.current_observation(point, before))
        self.assertFalse(a.current_observation(point, at))
        for collected in ("2026-11-14T03:35:42Z", "2026-11-16T21:16:00Z"):
            stale = a.summarize(h10_rows(collected=collected), "2026-11-16T21:17:00Z")
            self.assertEqual(stale["status"], "STALE")
            self.assertIsNone(stale["value"])

    def test_h10_expected_week_gaps_nulls_and_unexpected_early_values_are_not_masked(self):
        for mode in ("missing", "null", "old_week", "future_week", "early_capture"):
            with self.subTest(mode=mode):
                history = h10_rows()
                if mode == "missing": del history[2]
                if mode == "null": history[2]["value"] = None
                if mode == "old_week": history = h10_rows("2026-10-26")
                if mode == "future_week": history = h10_rows("2026-11-09")
                if mode == "early_capture": history = h10_rows(collected="2026-11-09T21:14:59Z")
                out = a.summarize(history, "2026-11-14T06:36:37Z")
                self.assertNotEqual(out["status"], "OBSERVED")
                self.assertIsNone(out["value"])
                self.assertFalse(a.current_observation(out, "2026-11-14T06:36:37Z"))
        history = h10_rows(); history[-1]["value"] = None
        self.assertEqual(a.summarize(history, "2026-11-14T06:36:37Z")["status"], "MISSING")

    def test_h10_federal_monday_holiday_dst_and_calendar_review_window(self):
        holiday = a.h10_schedule("2026-09-07T21:00:00Z")
        self.assertEqual(holiday["next_scheduled_release_at"], "2026-09-08T20:15:00+00:00")
        due = a.h10_schedule("2026-09-08T20:15:00Z")
        self.assertEqual(due["expected_period_start"], "2026-08-31")
        self.assertEqual(due["expected_period_end"], "2026-09-04")
        self.assertEqual(a.h10_schedule("2026-03-09T20:15:00Z")["latest_scheduled_release_at"], "2026-03-09T20:15:00+00:00")
        self.assertEqual(a.h10_schedule("2026-03-02T21:15:00Z")["latest_scheduled_release_at"], "2026-03-02T21:15:00+00:00")
        self.assertNotIn("2026-11-11", a.h10_schedule("2026-11-16T21:15:00Z")["required_observation_dates"])
        self.assertIsNone(a.h10_schedule("2008-11-14T00:00:00Z"))
        self.assertIsNone(a.h10_schedule("2036-11-14T00:00:00Z"))

    def test_h10_future_versions_preserve_the_fixed_past_and_fred_mirror_keeps_own_rule(self):
        now = "2026-11-14T06:36:37Z"
        history = h10_rows()
        later = [dict(r, value=r["value"]+10, available_at="2026-11-17T00:00:00Z") for r in history]
        first = a.visible_histories(history, now)["broad_usd"]
        second = a.visible_histories(history+later, now)["broad_usd"]
        self.assertEqual(a.summarize(first, now), a.summarize(second, now))
        mirror = [dict(r, source_id="fred:DTWEXBGS") for r in history]
        out = a.summarize(mirror, now)
        self.assertEqual(out["status"], "STALE")
        self.assertNotIn("publication_freshness", out)

    def test_spreads_use_basis_points_and_share_one_evidence_family(self):
        data = []
        for sid, v in (("SOFR", 4.2), ("TGCR", 4.1), ("IORB", 4.0), ("DFF", 3.98)):
            data.extend(rows(sid, [("2026-11-05", v-.01), ("2026-11-06", v)]))
        histories = a.visible_histories(data, NOW)
        panel = {k: a.summarize(v, NOW) for k,v in histories.items()}
        spreads = a.funding_spreads(histories, panel)
        self.assertAlmostEqual(spreads["sofr_minus_iorb"]["value"], 20)
        self.assertAlmostEqual(spreads["tgcr_minus_iorb"]["value"], 10)
        self.assertAlmostEqual(spreads["sofr_minus_tgcr"]["value"], 10)
        self.assertAlmostEqual(spreads["effr_minus_iorb"]["value"], -2)
        self.assertTrue(all(not r["independent_vote"] for r in spreads.values()))

    def test_mismatched_date_and_latest_null_never_use_old_common_value(self):
        for value in (".", 4):
            data = rows("SOFR", [("2026-11-05",4), ("2026-11-06", value)])+rows("IORB",[("2026-11-05",4)])
            h = a.visible_histories(data,NOW); p = {k:a.summarize(v,NOW) for k,v in h.items()}
            out = a.funding_spreads(h,p)["sofr_minus_iorb"]
            self.assertIsNone(out["value"])
            self.assertNotEqual(out["status"], "OBSERVED")

    def test_week_changes_require_complete_native_grid_and_keep_units(self):
        days = [(date(2026,8,5)+timedelta(weeks=i)).isoformat() for i in range(14)]
        series = rows("DPSACBW027SBOG",list(zip(days,range(100,114))))
        item = a.summarize(series,NOW)
        self.assertEqual([item["changes"][str(n)]["value"] for n in (1,4,13)], [1,4,13])
        self.assertEqual(item["unit"], "billions_usd")
        self.assertFalse(a.bank_comparison({})["deposit_change_is_identified_transfer"])
        del series[-3]
        self.assertIsNone(a.summarize(series,NOW)["changes"]["4"]["value"])

    def test_week_average_does_not_become_wednesday_level(self):
        panel = {sid: rows(sid,[("2026-11-04", 3000000)])[0] for sid in ("WRESBAL","WALCL","WTREGEN","WDTGAL")}
        self.assertEqual(panel["WRESBAL"]["measurement_basis"], "WEEK_AVERAGE")
        self.assertEqual(panel["WALCL"]["measurement_basis"], "WEDNESDAY_LEVEL")
        self.assertNotEqual(panel["WTREGEN"]["logical_id"], panel["WDTGAL"]["logical_id"])

    def test_domestic_reconciliation_does_not_include_foreign_bank_total(self):
        values = {"DPSACBW027SBOG":120,"DPSDCBW027SBOG":100,"DPSLCBW027SBOG":70,
                  "DPSSCBW027SBOG":30,"TOTLL":60,"TOTCI":20,"CASACBW027SBOG":10,"TLAACBW027SBOG":180}
        p = {}
        for sid, value in values.items():
            history = rows(sid, [("2026-11-04", value)])
            p[history[0]["logical_id"]] = a.summarize(history,NOW)
        result = a.bank_comparison(p)
        self.assertEqual(result["status"], "OBSERVED")
        self.assertEqual(result["loans_to_deposits"], .5)
        p["deposits_small"]["value"] = 35
        self.assertEqual(a.bank_comparison(p)["status"], "PARTIAL")

    def test_nyfed_volume_percentiles_and_original_clock(self):
        body = json.dumps(dict(refRates=[dict(type="TGCR", effectiveDate="2026-11-06", percentRate=4.1,
            volumeInBillions=1200,percentPercentile1=4.0,percentPercentile25=4.05,
            percentPercentile75=4.15,percentPercentile99=4.2)])).encode()
        out = a.parse_original(body,dict(source_id="nyfed:TGCR",collected_at=COLLECTED))[0]
        self.assertEqual(out["transaction_volume_billions_usd"],1200)
        self.assertEqual(out["available_at"],COLLECTED)
        self.assertIsNone(out["published_at"])
        self.assertFalse(out["historical_pit_certified"])
        self.assertEqual(out["rate_percentile_99"],4.2)

    def test_duplicate_provider_and_conflicting_version_are_refused(self):
        x = rows("SOFR",[("2026-11-06",4)])[0]
        for other in ({**x,"source_id":"nyfed:SOFR"},{**x,"value":5}):
            with self.assertRaises(ValueError): a.visible_histories([x,other],NOW)

    def test_nyfed_non_object_documents_become_blocked_loader_reports(self):
        for sid in ("SOFR","TGCR","EFFR"):
            for document in ([],None,"rates",4,True):
                with self.subTest(sid=sid,document=document),tempfile.TemporaryDirectory() as folder:
                    root=Path(folder);body=json.dumps(document).encode()
                    (root/"source.json").write_bytes(body)
                    request=dict(schema=m.REQUEST_SCHEMA_V2,market="US",session=SESSION,
                        available_at="2026-11-07T09:00:00Z",expires_at="2026-11-08T09:00:00Z",
                        inputs=[dict(kind="macro_v2",path="source.json",sha256=m.sha(body),
                                     source_id="nyfed:"+sid,status="COLLECTED",collected_at=COLLECTED)])
                    raw_request=json.dumps(request).encode();(root/"request.json").write_bytes(raw_request)
                    result=m.load_report(root/"request.json",root,m.sha(raw_request),cutoff=NOW,session=SESSION)
                    self.assertEqual(result["status"],"DATA_BLOCKED")
                    self.assertFalse(result["order_generation_allowed"])

    def test_future_availability_is_excluded_without_changing_past(self):
        old = rows("SOFR",[("2026-11-06",4)])[0]
        future = {**old,"value":5,"available_at":"2026-11-08T00:00:00Z"}
        self.assertEqual(a.visible_histories([old],NOW),a.visible_histories([old,future],NOW))

    def test_current_json_requires_replayable_original_normalization(self):
        from tests.a4_macro_bridge_smoke import original
        for body in (original(),b'\xef\xbb\xbf'+original()):
            with self.subTest(bom=body.startswith(b'\xef\xbb\xbf')):
                csv, manifest = bridge.normalize_current(body,series_id="SOFR",
                    start="2026-10-01",through="2026-11-06",collected_at=COLLECTED)
                spec = dict(source_id="fred:SOFR",collected_at=COLLECTED,normalization=manifest)
                parsed=a.parse_original(body,spec)
                self.assertIsNone(parsed[-1]["value"])
                self.assertEqual(parsed[-1]["original_sha256"],m.sha(body))
                spec["normalization"] = {**manifest,"published_at":COLLECTED}
                with self.assertRaises(ValueError): a.parse_original(body,spec)

    def test_engine_v2_preserves_incumbent_block_and_exposes_all_horizons(self):
        out = analyze([("fred:SOFR",raw("SOFR",[("2026-11-06",4)])),
                       ("fred:IORB",raw("IORB",[("2026-11-06",3.9)]))])
        self.assertEqual(out["schema"],"market-analysis-report-v2")
        self.assertEqual(out["status"],"DATA_BLOCKED")
        self.assertIsNone(out["market_assessment"]["state"])
        self.assertFalse(out["liquidity"]["fixed_reserve_threshold_used"])
        self.assertEqual([r["horizon_sessions"] for r in out["horizon_outlook"]],list(a.HORIZONS))
        self.assertTrue(all(r["direction"]=="INSUFFICIENT_EVIDENCE" for r in out["horizon_outlook"]))
        self.assertIn("Bank balances",m.render_report(out))
        self.assertFalse(out["target_book_write_allowed"])

    def test_unknown_source_bad_header_nonfinite_and_negative_balances_refuse(self):
        for sid, body in (("fred:BAD",b"x"),("fred:SOFR",b"observation_date,IORB\n2026-11-06,4\n"),
                          ("fred:SOFR",raw("SOFR",[("2026-11-06","NaN")])),
                          ("fred:DPSACBW027SBOG",raw("DPSACBW027SBOG",[("2026-11-04",-1)]))):
            with self.subTest(sid=sid),self.assertRaises(ValueError): analyze([(sid,body)])

    def test_monthly_gaps_do_not_compress_calendar_time(self):
        series = rows("UNRATE",[("2026-08-01",4),("2026-10-01",5)])
        self.assertIsNone(a.summarize(series,NOW)["changes"]["1"]["value"])


if __name__ == "__main__": unittest.main()
