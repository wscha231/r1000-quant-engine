"""Real Chameleon producer fixtures; no real-source eligibility is asserted."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import tempfile
import unittest

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


def run_tests():
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ReportClockTests))
    if not result.wasSuccessful(): raise SystemExit(1)


if __name__ == "__main__":
    run_tests()
