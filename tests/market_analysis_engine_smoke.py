"""Synthetic integration and fail-closed tests; not actual Source or PIT proof."""
from __future__ import annotations
import argparse
import copy
import csv
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from tools import market_analysis_engine as m
from tools import chameleon_market_context_v2 as c
from tools import free_market_context as f
from tools import run_daily_crisis_monitor as monitor

NOW = "2026-10-27T10:00:00Z"
COLLECTED = "2026-10-27T09:00:00Z"
DAY = "2026-10-26"

def encode(value):
    return json.dumps(value, sort_keys=True, allow_nan=False).encode()


def source(raw, kind="macro", name="fred:NFCI", path="raw.csv", **kw):
    spec = {"kind":kind,"path":path,"sha256":m.sha(raw),"status":"COLLECTED","collected_at":COLLECTED}
    if kind == "macro":spec["source_id"] = name
    spec.update(kw)
    return spec


def request(entries=None, **kw):
    r = {"schema":m.REQUEST_SCHEMA,"market":"US","session":DAY,
         "available_at":"2026-10-27T09:30:00Z","expires_at":"2026-10-28T09:30:00Z","inputs":entries or []}
    r.update(kw)
    return r


def analyze(r=None, blobs=None):
    raw = encode(request() if r is None else r)
    return m.analyze(raw, blobs or {}, expected_sha=m.sha(raw), cutoff=NOW, session=DAY)


class IntegratedMarketTests(unittest.TestCase):
    def test_native_missing_blocks_instead_of_neutral(self):
        report = analyze()
        self.assertEqual(report["status"], "DATA_BLOCKED")
        self.assertIsNone(report["market_assessment"]["state"])
        self.assertIsNone(report["market_assessment"]["risk_score"])
        self.assertFalse(report["regime_authorized"])
        self.assertEqual(report["network_requests_executed"],0)

    def test_real_native_parser_and_context_family(self):
        raw = b"observation_date,NFCI\n2026-10-16,-0.5\n2026-10-23,-0.3\n"
        report = analyze(request([source(raw)]), {"raw.csv":raw})
        item = report["existing_market_context"]["macro"]["nfci"]
        self.assertEqual(item["value"],-.3)
        self.assertEqual(item["family"],"FINANCIAL_CONDITIONS_COMPOSITE")
        self.assertEqual(report["status"],"DATA_BLOCKED")

    def test_new_exact_four_do_not_alias_similarly_named_series(self):
        for symbol,logical in [("BAMLC0A0CM","ig_oas"),("DGS3MO","yield_3mo"),
                               ("WDTGAL","tga_weekly_close"),("RRPTSYD","rrp_total_daily")]:
            with self.subTest(symbol=symbol):
                raw = ("observation_date,"+symbol+"\n2026-10-23,1.5\n").encode()
                r = analyze(request([source(raw,name="fred:"+symbol)]),{"raw.csv":raw})
                self.assertEqual(r["existing_market_context"]["macro"][logical]["value"],1.5)
        self.assertNotEqual(c.SERIES["fred:WTREGEN"][0],c.SERIES["fred:WDTGAL"][0])
        self.assertNotEqual(c.SERIES["fred:RRPONTSYD"][0],c.SERIES["fred:RRPTSYD"][0])

    def test_null_latest_does_not_fall_back(self):
        raw=b"observation_date,NFCI\n2026-10-16,-0.5\n2026-10-23,.\n"
        out=analyze(request([source(raw)]),{"raw.csv":raw})
        item=out["existing_market_context"]["macro"]["nfci"]
        self.assertEqual(item["status"],"MISSING");self.assertIsNone(item["value"])

    def test_stale_observation_cannot_be_freshened_by_new_collection(self):
        raw=b"observation_date,NFCI\n2026-08-01,-0.5\n"
        item=analyze(request([source(raw)]),{"raw.csv":raw})["existing_market_context"]["macro"]["nfci"]
        self.assertEqual(item["status"],"STALE");self.assertIsNone(item["value"])

    def test_byte_tampering_rejected(self):
        raw=b"observation_date,NFCI\n2026-10-23,-0.3\n"
        with self.assertRaises(ValueError):analyze(request([source(raw)]),{"raw.csv":raw+b" "})

    def test_failed_source_cannot_use_old_success(self):
        raw=b"x"
        for state in ("FAILED","BLOCKED","STALE_RETAINED"):
            with self.subTest(state=state),self.assertRaises(ValueError):
                analyze(request([source(raw,status=state)]),{"raw.csv":raw})

    def test_request_pin_required(self):
        raw=encode(request())
        for pin in (None,"a"*64):
            with self.subTest(pin=pin),self.assertRaises(ValueError):
                m.analyze(raw,{},expected_sha=pin,cutoff=NOW,session=DAY)

    def test_old_session_and_holiday_session_refused(self):
        for session in ("2026-10-23","2026-10-25","2026-10-27"):
            with self.subTest(session=session),self.assertRaises(ValueError):
                analyze(request(session=session))

    def test_current_session_close_delay_and_early_close(self):
        self.assertEqual(m.current_session("2026-11-27T18:14:59Z"),"2026-11-25")
        self.assertEqual(m.current_session("2026-11-27T18:15:00Z"),"2026-11-27")
        self.assertEqual(m.current_session("2026-03-09T20:14:59Z"),"2026-03-06")
        self.assertEqual(m.current_session("2026-03-09T20:15:00Z"),"2026-03-09")

    def test_expired_or_future_request_refused(self):
        for fields in ({"expires_at":"2026-10-27T09:59:59Z"},
                       {"available_at":"2026-10-27T10:00:01Z"},
                       {"expires_at":"2026-11-30T00:00:00Z"}):
            with self.subTest(fields=fields),self.assertRaises(ValueError):analyze(request(**fields))

    def test_future_collection_refused(self):
        raw=b"x"
        with self.assertRaises(ValueError):
            analyze(request([source(raw,collected_at="2026-10-27T09:30:01Z")]),{"raw.csv":raw})

    def test_duplicate_paths_roles_and_unselected_extra_refused(self):
        raw=b"x";s=source(raw)
        for entries,blobs in (([s,s],{"raw.csv":raw}),([s,{**s,"path":"other.csv"}],{"raw.csv":raw,"other.csv":raw}),
                              ([],{"foreign.csv":raw})):
            with self.subTest(entries=entries),self.assertRaises(ValueError):analyze(request(entries),blobs)

    def test_traversal_absolute_ads_and_windows_devices_refused(self):
        for path in ("../a.csv","/a.csv","a\\b","a:stream","a/../b","a//b","NUL.csv","dir/COM1.txt"):
            with self.subTest(path=path),self.assertRaises(ValueError):m.safe_path(path)

    def test_sce_means_probability_is_not_aaii_bull_share(self):
        raw=b"month,mean_probability_stock_prices_higher_12m_percent\n2026-09,40.2\n"
        out=analyze(request([source(raw,kind="sce_export")]),{"raw.csv":raw})
        row=out["household_expectations"][0]
        self.assertAlmostEqual(row["current_value"],.402)
        self.assertEqual(row["metric"],"mean_probability_stock_prices_higher_12m")
        self.assertFalse(row["original_workbook_verified"])
        self.assertFalse(row["conversion_verified"])
        self.assertEqual(out["existing_market_context"]["public"],[])

    def test_sce_wrong_units_null_duplicate_and_range(self):
        header=b"month,mean_probability_stock_prices_higher_12m_percent\n"
        for payload in (header+b"2026-09,101\n",header+b"2026-09,40\n2026-09,41\n",
                        b"date,bullish,neutral,bearish\n2026-09-01,40,20,40"):
            with self.subTest(payload=payload),self.assertRaises(ValueError):m.sce_rows(payload,COLLECTED,NOW)
        rows=m.sce_rows(header+b"2026-08,40\n2026-09,.\n",COLLECTED,NOW)
        self.assertIsNone(f.trailing_context(rows,cutoff=NOW,max_age_days=75)[0]["current_value"])

    def test_tff_retains_participant_identity_and_observation_clock(self):
        raw=encode([{"cftc_contract_market_code":"13874A","report_date_as_yyyy_mm_dd":"2026-10-20T00:00:00.000",
                    "open_interest_all":"100","asset_mgr_positions_long_all":"60","asset_mgr_positions_short_all":"20"}])
        out=analyze(request([source(raw,kind="cot_tff")]),{"raw.csv":raw})
        row=next(x for x in out["existing_market_context"]["public"] if x["entity_id"]=="13874A:ASSET_MANAGER" and x["metric"]=="net_fraction_oi")
        self.assertEqual(row["current_value"],.4)
        self.assertEqual(row["observation_date"],"2026-10-20")
        self.assertIsNone(row["provider_published_at"])
        self.assertNotEqual(row["available_at"][:10],row["observation_date"])

    def test_duplicate_vol_provider_refused(self):
        a=b"observation_date,VIXCLS\n2026-10-26,20\n"
        b=b"DATE,CLOSE\n2026-10-26,20\n"
        with self.assertRaises(ValueError):
            analyze(request([source(a,name="fred:VIXCLS"),source(b,name="cboe:VIX",path="b.csv")]),{"raw.csv":a,"b.csv":b})

    def test_authority_cannot_leak_from_prices(self):
        from tests.chameleon_market_context_v2_library_smoke import price
        row=price();row.update(session=DAY,available_at=COLLECTED,collected_at=COLLECTED,
                               mapping_available_at=COLLECTED,portfolio_mutation_allowed=True)
        raw=encode([row])
        with self.assertRaises(ValueError):analyze(request([source(raw,kind="price_context")]),{"raw.csv":raw})

    def test_load_failure_replaces_assessment_and_never_reads_previous_success(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);p=root/"request.json";raw=encode(request());p.write_bytes(raw)
            out=m.load_report(p,root,m.sha(raw),cutoff=NOW)
            self.assertEqual(out["status"],"DATA_BLOCKED")
            self.assertIn("implementation",out)
            p.write_text("invalid")
            self.assertIsNone(m.load_report(p,root,m.sha(raw),cutoff=NOW)["market_assessment"]["state"])

    def test_no_network_is_used(self):
        with patch("socket.socket",side_effect=AssertionError("NETWORK_NOT_ALLOWED")):
            self.assertEqual(analyze()["network_requests_executed"],0)

    def test_engine_registered_in_existing_active_umbrella(self):
        t=(ROOT/"tests/daily_crisis_monitor_long_crisis_smoke.py").read_text(encoding="utf-8")
        self.assertIn("from market_analysis_engine_smoke import run_tests",t)
        t=(ROOT/".github/workflows/daily_crisis_monitor.yml").read_text(encoding="utf-8")
        self.assertIn("--market-analysis-request ",t)
        self.assertIn("outputs/market_analysis_inputs",t)
        self.assertEqual(t.count("cron:"),1)

    def test_fixed_independent_proof_closure_contains_new_dependencies(self):
        from tools import manual_foundation as manual
        self.assertIn("tools/market_analysis_engine.py",manual.A6_FIXED_PROOF_PROGRAMS)
        self.assertIn("tests/market_analysis_engine_smoke.py",manual.A6_FIXED_PROOF_PROGRAMS)
        self.assertIn("docs/market_analysis_contract_v1.json",manual.A6_FIXED_PROOF_INPUTS)

    def test_nonobject_price_rows_are_structured_blocked_at_file_boundary(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);p=root/"request.json"
            for item in (None,1,"row",[],True):
                with self.subTest(item=item):
                    raw=encode([item]);(root/"raw.csv").write_bytes(raw)
                    req=encode(request([source(raw,kind="price_context")]))
                    p.write_bytes(req)
                    out=m.load_report(p,root,m.sha(req),cutoff=NOW)
                    self.assertEqual(out["status"],"DATA_BLOCKED")
                    self.assertIsNone(out["market_assessment"]["state"])

    def test_calendar_failure_returns_structured_refusal(self):
        with patch.object(m,"current_session",side_effect=ValueError("CALENDAR_UNAVAILABLE")):
            out=m.load_report(None,None,None,cutoff=NOW)
        self.assertEqual(out["status"],"DATA_BLOCKED")
        self.assertIsNone(out["market_assessment"]["state"])

    def test_expiry_exact_boundary_is_closed(self):
        with self.assertRaises(ValueError):analyze(request(expires_at=NOW))

    def test_existing_candidate_reassessment_consumer_receives_typed_rows(self):
        from tools import candidate_reassessment_bridge as bridge
        raw=b"observation_date,NFCI\n2026-10-23,-0.3\n"
        out=analyze(request([source(raw)]),{"raw.csv":raw})
        snap=out["candidate_reassessment_snapshot"]
        bridge.verify(snap,"review-observation-snapshot-v1")
        self.assertEqual(len(snap["rows"]),1)
        self.assertEqual(snap["rows"][0]["entity_id"],"nfci")
        self.assertEqual(snap["rows"][0]["values"]["value"],-.3)
        for key in bridge.CLOSED:self.assertIs(snap[key],False)

    def test_invalid_current_input_overwrites_previous_success_with_blocked_summary(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);inputs=root/"inputs";inputs.mkdir()
            raw=encode([None]);(inputs/"raw.csv").write_bytes(raw)
            req=encode(request([source(raw,kind="price_context")]))
            p=inputs/"request.json";p.write_bytes(req)
            output=root/"report";output.mkdir()
            (output/"summary.json").write_text('{"marker":"previous_success"}')
            args=argparse.Namespace(latest_run=str(root),output_dir=str(output),
                history=str(root/"history.json"),long_crisis_features=str(root/"absent.parquet"),
                long_crisis_thresholds=str(root/"thresholds.json"),update_history=False,
                market_analysis_request=str(p),market_analysis_root=str(inputs),
                expected_market_analysis_request_sha256=m.sha(req),market_analysis_request_sha_file=None)
            with patch("tools.daily_crisis_report_clock.trusted_now",return_value=m.clock.stamp(NOW)):
                report=monitor.build_monitor(args)
            saved=json.loads((output/"summary.json").read_text())
            self.assertNotIn("marker",saved)
            self.assertEqual(saved["market_analysis"]["status"],"DATA_BLOCKED")
            self.assertIsNone(saved["market_analysis"]["market_assessment"]["state"])
            self.assertIn("Unified Market Analysis",(output/"crisis_action_status.md").read_text())
            self.assertEqual(report["paper_action_candidates"],[])

    def test_monitor_handoff_cannot_change_legacy_state(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);raw=encode(request());p=root/"request.json";p.write_bytes(raw)
            args=argparse.Namespace(market_analysis_request=str(p),market_analysis_root=str(root),
                expected_market_analysis_request_sha256=m.sha(raw),market_analysis_request_sha_file=None)
            payload={"state":"WATCH","paper_action_candidates":[]}
            monitor.attach_market_analysis(payload,args,NOW)
            self.assertEqual(payload["state"],"WATCH")
            self.assertEqual(payload["paper_action_candidates"],[])
            self.assertEqual(payload["market_analysis"]["status"],"DATA_BLOCKED")
            self.assertEqual(payload["market_analysis"]["consumer_handoff"]["A5"],"RESEARCH_CONTEXT_ONLY_NO_PORTFOLIO_EFFECT")


class NativeRiskPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tests import run287_chameleon_macro_risk_smoke as fixture
        dates=m.clock.mcal.get_calendar("NYSE").schedule(start_date="2025-01-01",end_date=DAY).index[-260:]
        cal=fixture.calendar_fixture(dates);calraw=cal.to_csv(index=False).encode()
        metrics=fixture.metric_fixture(dates,calendar_hash=m.sha(calraw))
        context=fixture.context_fixture(dates,calendar_hash=m.sha(calraw))
        cls.blobs={"risk_calendar":calraw,"risk_metrics":metrics.to_csv(index=False).encode(),
                   "risk_context":context.to_csv(index=False).encode()}
        cls.result=m.native_risk(cls.blobs,DAY,NOW)

    def test_incumbent_full_pipeline_readiness_and_thresholds(self):
        self.assertEqual(self.result["status"],"READY_RESEARCH_ONLY")
        self.assertEqual(self.result["ready_axis_count"],10)
        self.assertTrue(self.result["required_axes_ready"])
        self.assertEqual(self.result["risk_score"],50.)
        self.assertEqual(self.result["state"],"NORMAL")
        self.assertFalse(self.result["calibration_or_economic_approval"])
        self.assertEqual(len(self.result["axes"]),10)

    def test_complete_native_model_is_consumed_by_unified_report(self):
        entries=[source(v,kind=k,path=k+".csv") for k,v in self.blobs.items()]
        out=analyze(request(entries),{k+".csv":v for k,v in self.blobs.items()})
        self.assertEqual(out["market_assessment"],self.result)
        self.assertEqual(out["status"],"READY_RESEARCH_ONLY")
        for key,value in m.SAFETY.items():self.assertEqual(out[key],value)
        self.assertFalse(out["source_and_pit_admission"])
        self.assertEqual(out["household_expectations"],[])

    def test_same_calendar_different_metric_session_refused(self):
        with self.assertRaises(ValueError):m.native_risk(self.blobs,"2026-10-27",NOW)


def run_tests():
    suite=unittest.TestSuite([unittest.defaultTestLoader.loadTestsFromTestCase(c)
                             for c in (IntegratedMarketTests,NativeRiskPipelineTests)])
    r=unittest.TextTestRunner(verbosity=2).run(suite)
    if not r.wasSuccessful():raise RuntimeError("MARKET_ANALYSIS_INTEGRATION_FAILED")


if __name__ == "__main__":run_tests()
