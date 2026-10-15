"""Real Chameleon producer fixtures; no real-source eligibility is asserted."""
from __future__ import annotations

import argparse
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import pandas as pd
import pandas_market_calendars as mcal
import run287_chameleon_macro_risk_smoke as fixtures
from tools import daily_crisis_report_clock as clock
from tools.run_daily_crisis_monitor import build_monitor


class ReportClockTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temporary.name)
        dates = fixtures.xnys_dates("2024-01-02", 260)
        schedule = mcal.get_calendar("NYSE").schedule(dates[0], dates[-1])
        calendar = pd.DataFrame(dict(
            decision_date=dates.strftime("%Y-%m-%d"),
            decision_time_utc=[(v+pd.Timedelta(minutes=15)).isoformat() for v in schedule.market_close],
            nyse_session_ordinal=range(len(dates))))
        calendar_path = cls.root / "calendar.csv"
        calendar.to_csv(calendar_path, index=False)
        calendar_hash = clock.digest(calendar_path.read_bytes())
        metrics = fixtures.metric_fixture(dates, calendar_hash=calendar_hash)
        context = fixtures.context_fixture(dates, calendar_hash=calendar_hash)
        mapping = dict(zip(calendar.decision_date, calendar.decision_time_utc))
        for frame in (metrics, context):
            frame["decision_time_utc"] = frame.decision_date.map(mapping)
            frame["available_from"] = frame.decision_time_utc
        cls.session = dates[-1].date().isoformat()
        cls.previous_session = dates[-2].date().isoformat()
        cls.current = cls.build_bundle("current", metrics, context, calendar_path)
        cls.previous = cls.build_bundle("previous", metrics[metrics.decision_date != cls.session],
                                        context[context.decision_date != cls.session], calendar_path)
        # Canonical producer handles a real missing mandatory axis, not a
        # handcrafted snapshot that merely claims readiness is false.
        missing = metrics[~((metrics.decision_date == cls.session) & (metrics.axis == "credit"))]
        cls.partial = cls.build_bundle("partial", missing, context, calendar_path)
        anchor = dict(schema="daily-crisis-report-history-v1", recipient="owner", input_kind="FIXTURE",
                      parent_sha256=None, last_counted_completed_session=None,
                      completed_session_count=0, slots=[])
        anchor["content_sha256"] = clock.digest(clock.canonical(anchor))
        cls.anchor = clock.canonical(anchor)+b"\n"

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    @classmethod
    def build_bundle(cls, name, metrics, context, calendar):
        metrics_path, context_path = cls.root / (name+".csv"), cls.root / (name+"-context.csv")
        metrics.to_csv(metrics_path, index=False)
        context.to_csv(context_path, index=False)
        contract = clock.risk.DEFAULT_CONTRACT
        args = argparse.Namespace(contract=str(contract), calendar=str(calendar),
            input_metrics=str(metrics_path), input_context=str(context_path), as_of="",
            output_dir=str(cls.root / name))
        manifest = clock.risk.build(args)
        if not manifest["status"].startswith("READY_CHAMELEON_MACRO_RISK_REPORT_ONLY"):
            raise RuntimeError(manifest.get("blockers"))
        clocks = []
        for source in ("a"*64, "b"*64):
            clocks.append(dict(source_sha256=source, source_id="SYNTHETIC_"+source[0],
                precision="SECOND", published_at="2023-12-29T18:00:00Z",
                available_at="2023-12-29T18:00:00Z", collected_at="2023-12-29T18:01:00Z",
                expiry="2030-01-01T00:00:00Z", purpose="US_MACRO_REPORT", purpose_eligible=True,
                rights="PRIVATE_RESEARCH_ALLOWED", identity_verified=True,
                availability_evidence_verified=True, availability_evidence_ref="fixture-only",
                unit="fixture-unit", expected_unit="fixture-unit", seasonal_basis="fixture",
                expected_seasonal_basis="fixture", input_kind="FIXTURE", revision="ORIGINAL",
                eligible_breadth_symbols=500, breadth_denominator_verified=True))
        view = dict(schema="daily-crisis-source-view-v1", input_kind="FIXTURE", source_clocks=clocks,
                    chameleon_manifest=clock.risk.fingerprint(cls.root / name / "manifest.json"))
        path = cls.root / (name+"-view.json")
        path.write_bytes(clock.canonical(view))
        return path

    def run_cycle(self, *, view=None, slot="AFTER_CLOSE", previous=None, parent=None, code="e"*64, **overrides):
        view = view or self.current
        raw = self.anchor if previous is None else previous
        args = dict(source_view=view, expected_source_sha=clock.digest(view.read_bytes()), source_root=self.root,
                    session=self.session, slot=slot, recipient="owner",
                    now=clock.session_times(self.session)[slot].isoformat(), previous_raw=raw,
                    expected_previous_sha=clock.digest(raw), expected_parent_sha=parent, code_sha=code)
        args.update(overrides)
        return clock.report_cycle(**args)

    def changed_view(self, change):
        value = json.loads(self.current.read_bytes())
        change(value)
        path = self.root / "changed-view.json"
        path.write_bytes(clock.canonical(value))
        return path

    def rebound(self, name, change, view_path=None):
        view = json.loads((view_path or self.current).read_bytes())
        manifest = json.loads(Path(view["chameleon_manifest"]["path"]).read_bytes())
        change(manifest, view)
        path = self.root / (name+"-manifest.json")
        path.write_bytes(clock.canonical(manifest))
        view["chameleon_manifest"] = clock.risk.fingerprint(path)
        path = self.root / (name+"-view.json")
        path.write_bytes(clock.canonical(view))
        return path

    def actual_shape_fixture(self):
        """Attack simulation only: no real source or accepted A0 proof."""
        def change(manifest, view):
            for name in ("metrics", "context"):
                frame = pd.read_csv(manifest["inputs"][name]["path"])
                frame["source_kind"] = "ARCHIVE"
                path = self.root / ("actual-shape-"+name+".csv")
                frame.to_csv(path, index=False)
                manifest["inputs"][name] = clock.risk.fingerprint(path)
            view["input_kind"] = "ACTUAL"
            fields = list(clock.risk.load_contract()["context_columns"]["optional_numeric"])
            fields += list(clock.risk.load_contract()["context_columns"]["optional_boolean"])
            names = [c for s in clock.risk.load_contract()["axes"].values() for c in s["components"]]+fields
            for item in view["source_clocks"]:
                item.update(input_kind="ACTUAL", source_id="ALFRED",
                            units={n:dict(unit="fixture-unit",seasonal_basis="fixture") for n in names})
        path = self.rebound("actual-shape", change)
        view = json.loads(path.read_bytes())
        manifest = json.loads(Path(view["chameleon_manifest"]["path"]).read_bytes())
        contract = clock.risk.load_contract()
        spec = dict(unit="fixture-unit",seasonal_basis="fixture",source_ids=["ALFRED"])
        cfg = dict(schema="daily-crisis-expectations-v1",purpose="US_MACRO_REPORT",
            producer_sha256=manifest["code"]["builder"]["sha256"],
            risk_contract_semantic_sha256=clock.risk.CANONICAL_CONTRACT_SEMANTIC_SHA256,
            inputs={n:r["sha256"] for n,r in manifest["inputs"].items() if n in ("metrics","context","calendar")},
            sources={r["source_sha256"]:dict(source_id="ALFRED",source_kind="ARCHIVE",clock_sha256=clock.digest(clock.canonical(r)))
                     for r in view["source_clocks"]},
            components={c:dict(spec,axis=a) for a,s in contract["axes"].items() for c in s["components"]},
            context_fields={f:dict(spec) for f in contract["context_columns"]["optional_numeric"]+contract["context_columns"]["optional_boolean"]})
        cfg_path = self.root / "actual-shape-expectations.json"
        cfg_path.write_bytes(clock.canonical(cfg))
        return path, cfg_path

    def test_completed_session_once_across_two_slots_and_changed_hash(self):
        intraday = self.run_cycle(view=self.previous, slot="INTRADAY")
        self.assertEqual(intraday["current_report_status"], "READY_DRY_RUN", intraday)
        self.assertIsNone(intraday["risk_score"])
        self.assertEqual(intraday["completed_session_increment"], 0)
        intraday_raw = clock.canonical(intraday["next_history"])
        after = self.run_cycle(previous=intraday_raw, parent=clock.digest(self.anchor))
        self.assertEqual(after["current_report_status"], "READY_DRY_RUN", after)
        self.assertEqual(after["completed_session_increment"], 1)
        self.assertEqual(after["next_history"]["completed_session_count"], 1)
        after_raw = clock.canonical(after["next_history"])
        duplicate = self.run_cycle(previous=after_raw, parent=clock.digest(intraday_raw), code="f"*64)
        self.assertEqual(duplicate["current_report_status"], "ALREADY_PREPARED_SAME_SLOT", duplicate)
        self.assertEqual(duplicate["completed_session_increment"], 0)
        self.assertEqual(duplicate["delivery_key"], after["delivery_key"])
        self.assertNotEqual(duplicate["analysis_artifact_key"], after["analysis_artifact_key"])

    def test_missing_pin_parent_or_forged_count_blocks_restore(self):
        for overrides, reason in ((dict(previous_raw=None), "HISTORY_UNAVAILABLE"),
                                  (dict(expected_previous_sha="0"*64), "PREVIOUS_HISTORY_PIN_MISMATCH"),
                                  (dict(expected_parent_sha="1"*64), "PREVIOUS_HISTORY_PARENT_MISMATCH")):
            result = self.run_cycle(**overrides)
            self.assertEqual(result["current_report_status"], "BLOCKED", result)
            self.assertIn(reason, result["blockers"])
            self.assertIsNone(result["next_history"])
        forged = json.loads(self.anchor)
        forged["completed_session_count"] = 1
        forged.pop("content_sha256")
        forged["content_sha256"] = clock.digest(clock.canonical(forged))
        raw = clock.canonical(forged)
        result = self.run_cycle(previous_raw=raw, expected_previous_sha=clock.digest(raw))
        self.assertIn("PREVIOUS_HISTORY_COUNT", result["blockers"])

    def test_history_missing_source_wait_and_stale_success(self):
        result = self.run_cycle(view=self.previous)
        self.assertIn("STALE_SUCCESS_NOT_CURRENT_REPORT", result["blockers"])
        result = self.run_cycle(source_view=None)
        self.assertIn("REAL_INPUT_WAIT", result["blockers"])

    def test_intraday_requires_exact_previous_completed_session(self):
        session = "2025-01-15"
        result = self.run_cycle(view=self.previous, slot="INTRADAY", session=session,
                               now=clock.session_times(session)["INTRADAY"].isoformat())
        self.assertIn("STALE_INTRADAY_SOURCE_SESSION", result["blockers"])

    def test_hash_rebound_tail_history_is_not_a_full_restore(self):
        view = json.loads(self.current.read_bytes())
        manifest = json.loads(Path(view["chameleon_manifest"]["path"]).read_bytes())
        raw = Path(manifest["outputs"]["market_state_history"]["path"]).read_bytes()
        lines = raw.splitlines(keepends=True)
        tail = self.root / "tail-history.csv"
        tail.write_bytes(lines[0]+b"".join(lines[-2:]))
        manifest["outputs"]["market_state_history"] = clock.risk.fingerprint(tail)
        path = self.root / "tail-manifest.json"
        path.write_bytes(clock.canonical(manifest))
        view["chameleon_manifest"] = clock.risk.fingerprint(path)
        path = self.root / "tail-view.json"
        path.write_bytes(clock.canonical(view))
        self.assertIn("HISTORY_INPUT_COVERAGE_MISMATCH", self.run_cycle(view=path)["blockers"])

    def test_exact_clock_rights_revision_unit_and_breadth_fail_closed(self):
        changes = (("precision", "DATE", "DATE_ONLY_PUBLICATION_UNKNOWN"),
                   ("available_at", "2024-01-02", "EXACT_SOURCE_CLOCK_REQUIRED"),
                   ("available_at", "2030-01-01T00:00:00Z", "SOURCE_CLOCK_OUT_OF_RANGE"),
                   ("rights", "UNKNOWN", "SOURCE_RIGHTS_OR_IDENTITY_UNKNOWN"),
                   ("revision", "CURRENT_VINTAGE", "REVISION_PROOF_MISSING"),
                   ("unit", "wrong", "UNIT_OR_SEASONAL_BASIS_MISMATCH"),
                   ("eligible_breadth_symbols", 16, "BREADTH_DENOMINATOR_UNVERIFIED"),
                   ("expiry", "2024-01-01T00:00:00Z", "SOURCE_CLOCK_OUT_OF_RANGE"))
        for key, value, reason in changes:
            with self.subTest(key=key, value=value):
                view = self.changed_view(lambda v: v["source_clocks"][0].update({key:value}))
                result = self.run_cycle(view=view)
                self.assertEqual(result["current_report_status"], "BLOCKED", result)
                self.assertIn(reason, result["blockers"])
                self.assertIsNone(result["risk_score"])
                self.assertFalse(result["delivery_candidate"])

    def test_context_clock_is_also_required(self):
        view = self.changed_view(lambda v: v["source_clocks"].pop())
        self.assertIn("SOURCE_CLOCK_MISSING", self.run_cycle(view=view)["blockers"])

    def test_actual_relabel_cannot_admit_explicit_fixture_sources(self):
        def relabel(value):
            value["input_kind"] = "ACTUAL"
            for item in value["source_clocks"]: item["input_kind"] = "ACTUAL"
        view = self.changed_view(relabel)
        self.assertIn("FIXTURE_ACTUAL_MIX", self.run_cycle(view=view)["blockers"])

    def test_claimed_axis_needs_real_historical_observations(self):
        view = json.loads(self.current.read_bytes())
        manifest = json.loads(Path(view["chameleon_manifest"]["path"]).read_bytes())
        frame = pd.read_csv(manifest["inputs"]["metrics"]["path"])
        frame = frame[(frame.axis != "credit") | (frame.decision_date == self.session)]
        path = self.root / "one-credit-session.csv"
        frame.to_csv(path, index=False)
        manifest["inputs"]["metrics"] = clock.risk.fingerprint(path)
        path = self.root / "one-credit-manifest.json"
        path.write_bytes(clock.canonical(manifest))
        view["chameleon_manifest"] = clock.risk.fingerprint(path)
        path = self.root / "one-credit-view.json"
        path.write_bytes(clock.canonical(view))
        self.assertIn("READY_AXIS_HISTORY_INSUFFICIENT", self.run_cycle(view=path)["blockers"])

    def test_ready_axis_missing_score_cannot_reduce_to_zero_risk(self):
        view = json.loads(self.current.read_bytes())
        manifest = json.loads(Path(view["chameleon_manifest"]["path"]).read_bytes())
        frame = pd.read_csv(manifest["outputs"]["macro_risk_axes"]["path"])
        frame.loc[frame.decision_date.str[:10] == self.session, "axis_score"] = float("nan")
        path = self.root / "missing-axis-scores.csv"
        frame.to_csv(path, index=False)
        manifest["outputs"]["macro_risk_axes"] = clock.risk.fingerprint(path)
        path = self.root / "missing-axis-scores-manifest.json"
        path.write_bytes(clock.canonical(manifest))
        view["chameleon_manifest"] = clock.risk.fingerprint(path)
        path = self.root / "missing-axis-scores-view.json"
        path.write_bytes(clock.canonical(view))
        result = self.run_cycle(view=path)
        self.assertIn("READY_AXIS_SCORE_INVALID", result["blockers"])
        self.assertIsNone(result["risk_score"])

    def test_partial_has_no_score_or_market_risk_upgrade(self):
        result = self.run_cycle(view=self.partial)
        self.assertEqual(result["data_health"], "DATA_PARTIAL", result)
        self.assertIsNone(result["risk_score"])
        self.assertIsNone(result["market_state"])
        self.assertEqual(result["completed_session_increment"], 0)

    def test_calendar_dst_early_close_holiday_and_late_intraday(self):
        self.assertIsNone(clock.session_times("2026-12-25"))
        early = clock.session_times("2026-11-27")
        self.assertEqual(early["INTRADAY"].astimezone(clock.NY).hour, 12)
        self.assertEqual(early["AFTER_CLOSE"].astimezone(clock.NY).hour, 14)
        self.assertEqual(clock.session_times("2026-03-06")["INTRADAY"].hour, 18)
        self.assertEqual(clock.session_times("2026-03-09")["INTRADAY"].hour, 17)
        result = self.run_cycle(slot="INTRADAY", now=clock.session_times(self.session)["close"].isoformat())
        self.assertIn("LATE_INTRADAY_NOT_RETROACTIVE", result["blockers"])

    def test_no_economic_or_notification_authority(self):
        result = self.run_cycle()
        self.assertEqual(result["current_report_status"], "READY_DRY_RUN", result)
        self.assertEqual(result["input_kind"], "FIXTURE")
        self.assertIsNone(result["target_weights"])
        self.assertEqual(result["company_impacts"], [])
        for key, expected in clock.SAFETY.items():
            self.assertIs(result[key], expected)

    def test_bounded_csv_and_hash_mismatch(self):
        for raw in (b'a,b\n'+b'x'*17000+b',y', b'a,a\nx,y', b'a,b\n"unterminated,y'):
            with self.assertRaises(clock.Blocked): clock.table(raw)
        result = self.run_cycle(expected_source_sha="0"*64)
        self.assertIn("SOURCE_VIEW_PIN_MISMATCH", result["blockers"])

    def test_deep_decoder_error_is_a_structured_blocker(self):
        path = self.root / "deep-source-view.json"
        path.write_bytes(b'{"x":'+b'['*10000+b'0'+b']'*10000+b'}')
        result = self.run_cycle(view=path)
        self.assertEqual(result["current_report_status"], "BLOCKED")
        self.assertIn("INVALID_JSON", result["blockers"])

    def test_full_producer_safety_envelope_is_required_even_with_warm_cache(self):
        self.assertEqual(self.run_cycle()["current_report_status"], "READY_DRY_RUN")
        flags = {"research_only":False,"stock_alpha_allowed":True,"trade_intents_written":True,
                 "production_activation_allowed":True,"live_trading_enabled":True,
                 "automatic_promotion_allowed":True,"backtest_executed":True}
        for name, value in flags.items():
            path = self.rebound("unsafe", lambda m,v: m.update({name:value}))
            self.assertIn("UPSTREAM_SAFETY_ENVELOPE", self.run_cycle(view=path)["blockers"])

    def test_expiry_must_cover_collection_and_evaluation(self):
        cutoff = clock.session_times(self.session)["AFTER_CLOSE"]
        from datetime import timedelta
        view = self.changed_view(lambda v: v["source_clocks"][0].update(
            expiry=(cutoff+timedelta(seconds=1)).isoformat(),
            collected_at=(cutoff+timedelta(seconds=2)).isoformat()))
        result = self.run_cycle(view=view, now=(cutoff+timedelta(seconds=3)).isoformat())
        self.assertIn("SOURCE_CLOCK_OUT_OF_RANGE", result["blockers"])

    def test_actual_clock_uses_runtime_not_caller_date(self):
        view, _ = self.actual_shape_fixture()
        result = self.run_cycle(view=view)
        self.assertIn("ACTUAL_CLOCK_NOT_CURRENT", result["blockers"])

    def test_actual_units_need_separately_pinned_component_and_context_expectations(self):
        view, cfg = self.actual_shape_fixture()
        now = clock.session_times(self.session)["AFTER_CLOSE"]
        args = dict(session=self.session,slot="AFTER_CLOSE",expectations_path=cfg,
                    expected_expectations_sha=clock.digest(cfg.read_bytes()))
        with patch.object(clock,"trusted_now",return_value=now):
            source = clock.load_source(view,clock.digest(view.read_bytes()),self.root,now,now,**args)
            self.assertEqual(source["issues"], [])
            with self.assertRaisesRegex(clock.Blocked,"ACTUAL_EXPECTATIONS_REQUIRED"):
                clock.load_source(view,clock.digest(view.read_bytes()),self.root,now,now,
                                  session=self.session,slot="AFTER_CLOSE")
            for field in ("vix_level", "spy_close"):
                value = json.loads(view.read_bytes())
                for item in value["source_clocks"]:
                    item["unit"] = item["expected_unit"] = "RATIO"
                    item["units"][field]["unit"] = "RATIO"
                changed = self.root / "coordinated-units.json"
                changed.write_bytes(clock.canonical(value))
                cfg_value = json.loads(cfg.read_bytes())
                for item in value["source_clocks"]:
                    cfg_value["sources"][item["source_sha256"]]["clock_sha256"] = clock.digest(clock.canonical(item))
                cfg.write_bytes(clock.canonical(cfg_value))
                args["expected_expectations_sha"] = clock.digest(cfg.read_bytes())
                source = clock.load_source(changed,clock.digest(changed.read_bytes()),self.root,now,now,**args)
                self.assertIn("COMPONENT_UNIT_CONTRACT_MISMATCH", source["issues"])

    def test_expectations_unknown_identity_and_nontext_units_are_blocked(self):
        view, cfg_path = self.actual_shape_fixture()
        original = json.loads(cfg_path.read_bytes())
        producer = original["producer_sha256"]
        mutations = (lambda v:v["sources"]["a"*64].update(source_id=None),
                     lambda v:v["components"]["vix_level"].update(source_ids=[None]),
                     lambda v:v["sources"]["a"*64].update(source_kind="UNKNOWN"),
                     lambda v:v["components"]["vix_level"].update(unit=1),
                     lambda v:v["context_fields"]["spy_close"].update(seasonal_basis=""))
        for mutate in mutations:
            value = json.loads(clock.canonical(original))
            mutate(value); cfg_path.write_bytes(clock.canonical(value))
            with self.assertRaises(clock.Blocked):
                clock.load_expectations(cfg_path,clock.digest(cfg_path.read_bytes()),producer)

    def test_actual_expiry_is_rechecked_after_verification(self):
        from datetime import timedelta
        view, cfg = self.actual_shape_fixture()
        now = clock.session_times(self.session)["AFTER_CLOSE"]
        value = json.loads(view.read_bytes())
        expectations = json.loads(cfg.read_bytes())
        for item in value["source_clocks"]:
            item["expiry"] = (now+timedelta(seconds=1)).isoformat()
            expectations["sources"][item["source_sha256"]]["clock_sha256"] = clock.digest(clock.canonical(item))
        view.write_bytes(clock.canonical(value)); cfg.write_bytes(clock.canonical(expectations))
        anchor = json.loads(self.anchor); anchor.pop("content_sha256")
        anchor["input_kind"] = "ACTUAL"; anchor["content_sha256"] = clock.digest(clock.canonical(anchor))
        raw = clock.canonical(anchor)
        with patch.object(clock,"trusted_now",side_effect=[now,now+timedelta(seconds=2)]):
            result = self.run_cycle(view=view,previous_raw=raw,expected_previous_sha=clock.digest(raw),
                expectations_path=cfg,expected_expectations_sha=clock.digest(cfg.read_bytes()))
        self.assertIn("SOURCE_EXPIRED_DURING_VERIFICATION",result["blockers"])
        self.assertEqual(result["completed_session_increment"],0)

    def test_duplicate_slot_cannot_complete_previously_uncounted_session(self):
        good = self.run_cycle()
        value = good["next_history"]
        value.update(parent_sha256=None,completed_session_count=0,last_counted_completed_session=None)
        value.pop("content_sha256")
        value["content_sha256"] = clock.digest(clock.canonical(value))
        raw = clock.canonical(value)
        result = self.run_cycle(previous_raw=raw,expected_previous_sha=clock.digest(raw))
        self.assertEqual(result["current_report_status"], "ALREADY_PREPARED_SAME_SLOT", result)
        self.assertEqual(result["completed_session_increment"], 0)

    def test_partial_correction_cannot_silently_complete(self):
        partial = self.run_cycle(view=self.partial)
        raw = clock.canonical(partial["next_history"])
        result = self.run_cycle(previous=raw,parent=clock.digest(self.anchor))
        self.assertIn("SOURCE_HISTORY_PREFIX_CHANGED", result["blockers"])
        self.assertEqual(result["completed_session_increment"],0)

    def test_rebound_earlier_observation_cannot_change_effective_state(self):
        def change(manifest, view):
            frame = pd.read_csv(manifest["outputs"]["market_state_history"]["path"])
            frame.loc[frame.index[-5:-3], "observed_state"] = "RISK_DEFENSE"
            frame = clock.risk.apply_state_hysteresis(frame, clock.risk.load_contract())
            path = self.root / "forged-earlier-history.csv"
            path.write_bytes(clock.frame_bytes(frame))
            manifest["outputs"]["market_state_history"] = clock.risk.fingerprint(path)
        path = self.rebound("earlier-state", change)
        self.assertIn("FULL_DERIVED_HISTORY_MISMATCH", self.run_cycle(view=path)["blockers"])

    def test_coordinated_axes_snapshot_history_cannot_invent_metric_scores(self):
        self.assertEqual(self.run_cycle()["current_report_status"], "READY_DRY_RUN")
        def change(manifest, view):
            axes = pd.read_csv(manifest["outputs"]["macro_risk_axes"]["path"])
            selected = axes.decision_date.str[:10] == self.session
            axes.loc[selected,"axis_score"] = 99.0
            axes.loc[selected,"red_axis"] = True
            domains = axes.loc[selected,"red_domain"].nunique()
            path = self.root / "invented-axes.csv"; path.write_bytes(clock.frame_bytes(axes))
            manifest["outputs"]["macro_risk_axes"] = clock.risk.fingerprint(path)
            history = pd.read_csv(manifest["outputs"]["market_state_history"]["path"])
            history.loc[history.index[-1],"risk_score"] = 99.0
            history.loc[history.index[-1],"observed_state"] = clock.risk.classify_market_state(99,10,domains,clock.risk.load_contract())
            history = clock.risk.apply_state_hysteresis(history,clock.risk.load_contract())
            path = self.root / "invented-history.csv"; path.write_bytes(clock.frame_bytes(history))
            manifest["outputs"]["market_state_history"] = clock.risk.fingerprint(path)
            snapshot = json.loads(Path(manifest["outputs"]["macro_risk_snapshot"]["path"]).read_bytes())
            snapshot.update(risk_score=99.0,red_axis_count=10,red_domain_count=int(domains))
            for axis in snapshot["axes"]: axis.update(axis_score=99.0,red_axis=True)
            path = self.root / "invented-snapshot.json"; path.write_bytes(clock.canonical(snapshot))
            manifest["outputs"]["macro_risk_snapshot"] = clock.risk.fingerprint(path)
        path = self.rebound("invented-scores",change)
        self.assertIn("FULL_DERIVED_HISTORY_MISMATCH",self.run_cycle(view=path)["blockers"])

    def test_rewritten_raw_source_prefix_is_refused_even_if_scores_unchanged(self):
        prior = self.run_cycle(view=self.previous,slot="INTRADAY")
        def change(manifest, view):
            frame = pd.read_csv(manifest["inputs"]["metrics"]["path"])
            frame.loc[frame.decision_date == frame.decision_date.min(),"source_sha256"] = "c"*64
            path = self.root / "rewritten-prefix-metrics.csv"
            frame.to_csv(path,index=False)
            manifest["inputs"]["metrics"] = clock.risk.fingerprint(path)
            item = dict(view["source_clocks"][0]); item["source_sha256"] = "c"*64
            view["source_clocks"].append(item)
        path = self.rebound("rewritten-prefix",change)
        result = self.run_cycle(view=path,previous=clock.canonical(prior["next_history"]),parent=clock.digest(self.anchor))
        self.assertIn("SOURCE_HISTORY_PREFIX_CHANGED",result["blockers"])

    def test_completed_anchor_requires_next_nyse_session(self):
        schedule = mcal.get_calendar("NYSE").schedule("2024-12-01",self.session)
        last_two = [d.date().isoformat() for d in schedule.index[-3:-1]]
        for last, expected in ((last_two[0],"BLOCKED"),(last_two[1],"READY_DRY_RUN")):
            prior = self.run_cycle(view=self.previous,session=self.previous_session,
                                   now=clock.session_times(self.previous_session)["AFTER_CLOSE"].isoformat())
            value = dict(prior["next_history"]); value.pop("content_sha256")
            value.update(last_counted_completed_session=last)
            value["content_sha256"] = clock.digest(clock.canonical(value))
            raw = clock.canonical(value)
            result = self.run_cycle(previous_raw=raw,expected_previous_sha=clock.digest(raw),expected_parent_sha=clock.digest(self.anchor))
            self.assertEqual(result["current_report_status"],expected,result)
            if expected == "BLOCKED":
                self.assertIn("COMPLETED_SESSION_GAP",result["blockers"])
                self.assertIsNone(result["next_history"])
            else:
                self.assertEqual(result["completed_session_increment"],1)

    def test_consumed_clock_provenance_cannot_rewrite_accepted_prefix(self):
        prior = self.run_cycle(view=self.previous,slot="INTRADAY")
        view = self.changed_view(lambda v:v["source_clocks"][0].update(
            availability_evidence_ref="replaced-fixture-provenance"))
        result = self.run_cycle(view=view,previous=clock.canonical(prior["next_history"]),
                                parent=clock.digest(self.anchor))
        self.assertIn("SOURCE_HISTORY_PREFIX_CHANGED",result["blockers"])
        self.assertEqual(result["completed_session_increment"],0)

    def test_failed_producer_status_and_blockers_cannot_supply_report(self):
        for fields in ({"status":"BLOCKED_CHAMELEON_MACRO_RISK_INPUT_CONTRACT","blockers":["failure"]},
                       {"blockers":["upstream-failure"]}, {"status":"UNKNOWN"}):
            view = self.rebound("failed-producer",lambda m,v:m.update(fields))
            result = self.run_cycle(view=view)
            self.assertIn("CHAMELEON_PRODUCER_NOT_READY",result["blockers"])
            self.assertEqual(result["completed_session_increment"],0)

    def test_null_optional_context_uses_existing_producer_contract(self):
        view = json.loads(self.current.read_bytes())
        manifest = json.loads(Path(view["chameleon_manifest"]["path"]).read_bytes())
        output = self.root / "without-context"
        built = clock.risk.build(argparse.Namespace(contract=str(clock.risk.DEFAULT_CONTRACT),
            calendar=manifest["inputs"]["calendar"]["path"],
            input_metrics=manifest["inputs"]["metrics"]["path"],input_context="",as_of="",output_dir=str(output)))
        self.assertIsNone(built["inputs"]["context"])
        view["chameleon_manifest"] = clock.risk.fingerprint(output / "manifest.json")
        path = self.root / "without-context-view.json"; path.write_bytes(clock.canonical(view))
        result = self.run_cycle(view=path)
        self.assertEqual(result["current_report_status"],"READY_DRY_RUN",result)
        self.assertEqual(result["completed_session_increment"],1)

    def test_missing_view_cannot_write_diagnostics_inside_source_root(self):
        output = self.root / "missing-view-diagnostic"
        args = argparse.Namespace(output_dir=str(output),history=str(self.root / "unused-history.json"),
            update_history=False,report_slot="AFTER_CLOSE",report_source_view=None,report_source_root=str(self.root))
        with self.assertRaisesRegex(clock.Blocked,"INPUT_OUTPUT_OVERLAP"):
            build_monitor(args)
        self.assertFalse(output.exists())

    def test_explicit_producer_asof_ignores_later_input_rows_only(self):
        view = json.loads(self.current.read_bytes())
        manifest = json.loads(Path(view["chameleon_manifest"]["path"]).read_bytes())
        output = self.root / "explicit-earlier-asof"
        built = clock.risk.build(argparse.Namespace(contract=str(clock.risk.DEFAULT_CONTRACT),
            calendar=manifest["inputs"]["calendar"]["path"],input_metrics=manifest["inputs"]["metrics"]["path"],
            input_context=manifest["inputs"]["context"]["path"],as_of=self.previous_session,output_dir=str(output)))
        self.assertEqual(built["decision_date"],self.previous_session)
        view["chameleon_manifest"] = clock.risk.fingerprint(output / "manifest.json")
        path = self.root / "explicit-asof-view.json"; path.write_bytes(clock.canonical(view))
        result = self.run_cycle(view=path,slot="INTRADAY")
        self.assertEqual(result["current_report_status"],"READY_DRY_RUN",result)
        self.assertEqual(result["risk_as_of_session"],self.previous_session)
        view["source_clocks"][0].update(available_at=self.previous_session+"T22:01:00Z",
                                      collected_at=self.previous_session+"T22:02:00Z")
        path.write_bytes(clock.canonical(view))
        result = self.run_cycle(view=path,slot="INTRADAY")
        self.assertIn("HISTORICAL_AVAILABILITY_VIOLATION",result["blockers"])

    def test_intraday_markdown_displays_verified_prior_session_state(self):
        result = self.run_cycle(view=self.previous,slot="INTRADAY")
        report = clock.render_report(result)
        self.assertIsNone(result["risk_score"])
        self.assertIsNone(result["market_state"])
        self.assertIn("Prior session: "+self.previous_session,report)
        self.assertIn("Prior-session risk score: "+str(result["last_completed_risk_score"]),report)
        self.assertIn("Prior-session market state: "+result["last_completed_market_state"],report)

    def test_completed_anchor_cannot_clear_slots_or_shorten_prefix(self):
        prior = self.run_cycle(view=self.previous,session=self.previous_session,
                               now=clock.session_times(self.previous_session)["AFTER_CLOSE"].isoformat())
        changes = (({"slots":[]},"COMPLETED_HISTORY_SLOTS_REQUIRED"),
                   ({"source_prefix_date":"2024-01-02"},"SOURCE_PREFIX_DOES_NOT_COVER_COMPLETED_SESSION"))
        for change, reason in changes:
            value = dict(prior["next_history"]); value.pop("content_sha256"); value.update(change)
            value["content_sha256"] = clock.digest(clock.canonical(value)); raw = clock.canonical(value)
            result = self.run_cycle(previous_raw=raw,expected_previous_sha=clock.digest(raw),expected_parent_sha=clock.digest(self.anchor))
            self.assertIn(reason,result["blockers"])
            self.assertIsNone(result["next_history"])
            self.assertEqual(result["completed_session_increment"],0)

    def test_producer_raw_cell_errors_are_redacted(self):
        sentinel = "PRIVATE_CREDENTIAL_SENTINEL_DO_NOT_PERSIST"
        boolean = clock.risk.load_contract()["context_columns"]["optional_boolean"][0]
        for name, column in (("metrics","component"),("context",boolean)):
            def change(manifest, view):
                frame = pd.read_csv(manifest["inputs"][name]["path"])
                frame.loc[frame.index[-1],column] = sentinel
                path = self.root / ("invalid-secret-"+name+".csv"); frame.to_csv(path,index=False)
                manifest["inputs"][name] = clock.risk.fingerprint(path)
            result = self.run_cycle(view=self.rebound("secret-"+name,change))
            self.assertIn("CHAMELEON_INPUT_CONTRACT",result["blockers"])
            self.assertNotIn(sentinel,json.dumps(result))
            self.assertNotIn(sentinel,clock.render_report(result))

    def test_post_asof_only_clocks_do_not_enter_validation_or_expiry_min(self):
        view = json.loads(self.previous.read_bytes())
        manifest = json.loads(Path(view["chameleon_manifest"]["path"]).read_bytes())
        current = json.loads(Path(json.loads(self.current.read_bytes())["chameleon_manifest"]["path"]).read_bytes())
        for name, key in (("metrics","c"*64),("context","d"*64)):
            frame = pd.read_csv(current["inputs"][name]["path"])
            frame.loc[frame.decision_date == self.session,"source_sha256"] = key
            path = self.root / ("later-hash-"+name+".csv"); frame.to_csv(path,index=False)
            manifest["inputs"][name] = clock.risk.fingerprint(path)
            item = dict(view["source_clocks"][0]); item.update(source_sha256=key,expiry="2000-01-01T00:00:00Z")
            view["source_clocks"].append(item)
        path = self.root / "later-hash-manifest.json"; path.write_bytes(clock.canonical(manifest))
        view["chameleon_manifest"] = clock.risk.fingerprint(path)
        path = self.root / "later-hash-view.json"; path.write_bytes(clock.canonical(view))
        result = self.run_cycle(view=path,slot="INTRADAY")
        self.assertEqual(result["current_report_status"],"READY_DRY_RUN",result)
        cutoff = clock.session_times(self.session)["INTRADAY"]
        source = clock.load_source(path,clock.digest(path.read_bytes()),self.root,cutoff,cutoff)
        self.assertGreater(source["expiry_min"],cutoff)
        view["source_clocks"] += [{"source_sha256":"f"*64}]*5001
        path.write_bytes(clock.canonical(view))
        self.assertIn("CLOCK_MANIFEST",self.run_cycle(view=path,slot="INTRADAY")["blockers"])

    def test_monitor_integration_candidate_only_and_no_overwrite(self):
        output = self.root / "monitor-dry-run"
        history = self.root / "approved-history.json"
        history.write_bytes(self.anchor)
        args = argparse.Namespace(output_dir=str(output), history=str(history), update_history=False,
            report_slot="AFTER_CLOSE", report_session=self.session, report_recipient="owner",
            report_now=clock.session_times(self.session)["AFTER_CLOSE"].isoformat(),
            report_source_view=str(self.current), report_source_root=str(self.root),
            expected_source_view_sha256=clock.digest(self.current.read_bytes()),
            expected_history_sha256=clock.digest(self.anchor), expected_history_parent_sha256=None)
        # Outputs must be outside the approved immutable input root.
        with self.assertRaises(clock.Blocked): build_monitor(args)
        with tempfile.TemporaryDirectory() as out:
            args.output_dir = str(Path(out) / "new")
            result = build_monitor(args)
            self.assertEqual(result["current_report_status"], "READY_DRY_RUN", result)
            self.assertEqual(history.read_bytes(), self.anchor)
            self.assertTrue((Path(args.output_dir) / "report_history.candidate.json").is_file())
            with self.assertRaises(FileExistsError): build_monitor(args)
            args.update_history = True
            with self.assertRaises(clock.Blocked): build_monitor(args)


class ReportCliTests(unittest.TestCase):
    def test_report_main_preflight_errors_are_bounded_and_redacted(self):
        from tools import run_daily_crisis_monitor as monitor
        for error in (clock.Blocked("PRIVATE_CREDENTIAL_SENTINEL"),FileExistsError("PRIVATE_PATH_SENTINEL")):
            with patch.object(sys,"argv",["monitor","--report-slot","AFTER_CLOSE","--report-session","2026-10-14"]), patch.object(monitor,"build_monitor",side_effect=error), redirect_stdout(io.StringIO()) as output:
                self.assertEqual(monitor.main(),2)
            payload = json.loads(output.getvalue())
            self.assertEqual(payload["blockers"],["REPORT_PREFLIGHT_OR_OUTPUT_REFUSED"])
            self.assertFalse(payload["notification_enabled"])
            self.assertNotIn("PRIVATE_",output.getvalue())

    def test_explicit_clock_and_recipient_values_are_validated(self):
        from tools.run_daily_crisis_monitor import parse_args
        for option,value in (("--report-now","not-a-time"),("--report-now","2026-10-14"),
                             ("--report-recipient","bad name"),("--report-recipient","x"*81)):
            with patch.object(sys,"argv",["monitor","--report-slot","AFTER_CLOSE","--report-session","2026-10-14",option,value]), redirect_stderr(io.StringIO()) as errors:
                with self.assertRaises(SystemExit) as caught:
                    parse_args()
            self.assertEqual(caught.exception.code,2)
            self.assertNotIn("Traceback",errors.getvalue())

    def test_present_invalid_report_session_has_normal_argument_error(self):
        from tools.run_daily_crisis_monitor import parse_args
        for value in ("not-a-date","2026-02-30","2026-2-3","0001-01-01"):
            with patch.object(sys,"argv",["monitor","--report-slot","AFTER_CLOSE","--report-session",value]), redirect_stderr(io.StringIO()) as errors:
                with self.assertRaises(SystemExit) as caught:
                    parse_args()
            self.assertEqual(caught.exception.code,2)
            self.assertIn("valid YYYY-MM-DD calendar date",errors.getvalue())
            self.assertNotIn("Traceback",errors.getvalue())

    def test_report_mode_requires_session_with_normal_argument_error(self):
        from tools.run_daily_crisis_monitor import parse_args
        for slot in clock.SLOTS:
            with patch.object(sys,"argv",["monitor","--report-slot",slot]), redirect_stderr(io.StringIO()) as errors:
                with self.assertRaises(SystemExit) as caught:
                    parse_args()
            self.assertEqual(caught.exception.code,2)
            self.assertIn("--report-session is required",errors.getvalue())
            self.assertNotIn("Traceback",errors.getvalue())

    def test_legacy_and_complete_report_arguments_still_parse(self):
        from tools.run_daily_crisis_monitor import parse_args
        for arguments in ([],["--report-slot","AFTER_CLOSE","--report-session","2026-10-14"]):
            with patch.object(sys,"argv",["monitor",*arguments]):
                args = parse_args()
            self.assertEqual(args.report_session,"2026-10-14" if arguments else None)


def run_tests():
    suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromTestCase(c) for c in (ReportClockTests,ReportCliTests))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful(): raise SystemExit(1)


if __name__ == "__main__":
    run_tests()
