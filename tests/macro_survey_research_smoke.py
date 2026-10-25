#!/usr/bin/env python3
"""Synthetic-only survey regression cases. All assertions survive python -O."""
from __future__ import annotations
from copy import deepcopy
from datetime import datetime, timezone
import json
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import macro_survey_research as survey

CUT = "2026-10-15T16:00:00Z"
NOW = datetime(2026, 10, 24, 0, tzinfo=timezone.utc)


def fixture():
    rows = []
    specs = survey._contract()[1]["sources"]
    for spec in specs:
        pairs = [("2026-08", "2026-09-03T14:00:00Z"), ("2026-09", "2026-10-05T14:00:00Z")]
        if spec["id"] == "AAII":
            pairs = [("2026-10-07", "2026-10-08T12:00:00Z"), ("2026-10-14", "2026-10-15T12:00:00Z")]
        for index, (period, clock) in enumerate(pairs):
            for component in spec["components"]:
                value = 50.0 + index
                if spec["id"] == "AAII":
                    value = {"bullish": 30 + index, "neutral": 30, "bearish": 40 - index}[component]
                rows.append(dict(source=spec["id"], component=component,
                    reference_period=period, release_id=spec["id"] + "." + period,
                    revision=0, published_at=clock, available_at=clock,
                    collected_at=clock, value=value, unit=spec["unit"], raw_sha256="a" * 64))
    return dict(evidence_mode="SYNTHETIC_FIXTURE", records=rows)


class SurveyTests(unittest.TestCase):
    def setUp(self):
        self.clock = patch.object(survey, "_now", return_value=NOW)
        self.clock.start()
        self.addCleanup(self.clock.stop)

    def build(self, value=None, cutoff=CUT):
        return survey.build_context(survey.encoded(fixture() if value is None else value),
                                    cutoff, "SYNTHETIC_FIXTURE")

    def test_complete_synthetic_16_components(self):
        out = self.build()
        self.assertEqual(out["status"], "SYNTHETIC_DIAGNOSTIC_ONLY")
        self.assertEqual(sum(len(v["values"]) for v in out["sources"].values()), 16)
        self.assertEqual(out["sources"]["ISM_MANUFACTURING"]["changes_pp"]["new_orders"], 1)
        self.assertEqual(out["sources"]["AAII"]["bull_bear_spread_pp"], -8)

    def test_actual_default_refuses_before_decoding(self):
        out = survey.build_context(b"not JSON", CUT)
        self.assertEqual(out["status"], "BLOCKED_SOURCE_ADMISSION")
        self.assertEqual(out["sources"], {})
        self.assertIsNone(out["input_sha256"])

    def test_self_claimed_verified_never_admits(self):
        p = fixture()
        p.update(supplier_rights_verified=True, source_status="VERIFIED",
                 historical_pit_verified=True, eligible_for_selector=True)
        out = self.build(p)
        for key in ["source_authenticated", "supplier_rights_verified",
                    "historical_pit_verified", "eligible_for_selector", "economic_authority"]:
            self.assertIs(out[key], False)

    def test_future_decision_refused(self):
        with self.assertRaisesRegex(ValueError, "future_decision"):
            self.build(cutoff="2027-01-01T00:00:00Z")

    def test_naive_decision_refused(self):
        with self.assertRaisesRegex(ValueError, "timezone_required"):
            self.build(cutoff="2026-10-15T16:00:00")

    def test_missing_fixture_label_refused(self):
        p = fixture()
        p.pop("evidence_mode")
        with self.assertRaisesRegex(ValueError, "fixture_label_required"):
            self.build(p)

    def test_nonstandard_json_refused(self):
        for literal in ["NaN", "Infinity", "-Infinity"]:
            with self.subTest(literal=literal), self.assertRaisesRegex(ValueError, "nonstandard_json_number"):
                survey.read_json(('{"value":' + literal + '}').encode())

    def test_duplicate_json_key_refused(self):
        with self.assertRaisesRegex(ValueError, "duplicate_json_key"):
            survey.read_json(b'{"records": [], "records": []}')

    def test_boolean_nonfinite_and_bad_units_refused(self):
        for value in [True, "51", None, -1, 101, 1e309]:
            p = fixture()
            p["records"][0]["value"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                # repr JSON Infinity must be refused by the strict decoder too.
                survey.build_context(json.dumps(p).encode(), CUT, "SYNTHETIC_FIXTURE")
        p = fixture()
        p["records"][0]["unit"] = "percent_0_1"
        with self.assertRaisesRegex(ValueError, "unit_mismatch"):
            self.build(p)

    def test_unknown_provider_and_component_refused(self):
        for field, value, reason in [("source", "SP_GLOBAL_FLASH", "unknown_source"),
                                      ("component", "bullish", "unknown_component")]:
            p = fixture()
            p["records"][0][field] = value
            with self.assertRaisesRegex(ValueError, reason):
                self.build(p)

    def test_duplicate_component_refused(self):
        p = fixture()
        p["records"].append(deepcopy(p["records"][0]))
        with self.assertRaisesRegex(ValueError, "duplicate_component"):
            self.build(p)

    def test_clock_order_and_naive_publication_refused(self):
        for field, value in [("published_at", "2026-09-04T14:00:00Z"),
                              ("published_at", "2026-09-03T14:00:00"),
                              ("collected_at", "2027-01-01T00:00:00Z")]:
            p = fixture()
            p["records"][0][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                self.build(p)

    def test_later_collected_data_cannot_enter_old_decision(self):
        p = fixture()
        for row in p["records"]:
            if row["source"] == "AAII" and row["reference_period"] == "2026-10-14":
                row["collected_at"] = "2026-10-16T12:00:00Z"
        out = self.build(p)
        self.assertEqual(out["sources"]["AAII"]["reference_period"], "2026-10-07")
        self.assertIsNone(out["sources"]["AAII"]["changes_pp"])

    def test_no_premature_use_of_release(self):
        out = self.build(cutoff="2026-10-15T11:59:59Z")
        self.assertEqual(out["sources"]["AAII"]["reference_period"], "2026-10-07")

    def test_missing_component_blocks_source_not_zero_fill(self):
        p = fixture()
        p["records"] = [r for r in p["records"] if not
                        (r["source"] == "AAII" and r["reference_period"] == "2026-10-14" and r["component"] == "bearish")]
        out = self.build(p)
        self.assertEqual(out["status"], "PARTIAL_SYNTHETIC_DIAGNOSTIC")
        self.assertEqual(out["sources"]["AAII"]["status"], "BLOCKED")
        self.assertIsNone(out["sources"]["AAII"]["values"])

    def test_aaii_rounded_sum_and_bad_sum(self):
        for value, status in [(30.1, "SYNTHETIC_DIAGNOSTIC_ONLY"), (32.0, "BLOCKED")]:
            p = fixture()
            for row in p["records"]:
                if row["source"] == "AAII" and row["component"] == "neutral":
                    row["value"] = value
            self.assertEqual(self.build(p)["sources"]["AAII"]["status"], status)

    def test_same_release_clock_raw_conflict_refused(self):
        for field, value in [("available_at", "2026-09-03T13:59:59Z"), ("raw_sha256", "b" * 64)]:
            p = fixture()
            p["records"][0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.build(p)

    def test_latest_explicit_revision_and_period_count(self):
        p = fixture()
        revised = []
        for row in p["records"]:
            if row["source"] == "AAII" and row["reference_period"] == "2026-10-14":
                x = deepcopy(row)
                x.update(revision=1, published_at="2026-10-15T13:00:00Z",
                         available_at="2026-10-15T13:00:00Z",
                         collected_at="2026-10-15T13:00:00Z", raw_sha256="b" * 64)
                revised.append(x)
        p["records"] += revised
        out = self.build(p)
        self.assertEqual(out["sources"]["AAII"]["revision"], 1)
        self.assertEqual(out["sources"]["AAII"]["independent_reference_periods"], 2)

    def test_conflicting_releases_do_not_keep_last(self):
        p = fixture()
        for row in list(p["records"]):
            if row["source"] == "AAII" and row["reference_period"] == "2026-10-14":
                r = deepcopy(row)
                r["release_id"] += ".conflicting"
                p["records"].append(r)
        self.assertEqual(self.build(p)["sources"]["AAII"]["status"], "BLOCKED")

    def test_stale_reference_not_refreshed_by_new_collection(self):
        out = self.build(cutoff="2026-10-24T00:00:00Z")
        self.assertEqual(out["sources"]["AAII"]["status"], "SYNTHETIC_DIAGNOSTIC_ONLY")
        p = fixture()
        for row in p["records"]:
            if row["source"] == "AAII":
                row["reference_period"] = ("2026-09-02" if row["reference_period"] == "2026-10-07" else "2026-09-09")
        self.assertEqual(self.build(p)["sources"]["AAII"]["status"], "STALE")
        self.assertIsNone(self.build(p)["sources"]["AAII"]["values"])

    def test_gap_has_no_delta_or_daily_pseudoreplication(self):
        p = fixture()
        for row in p["records"]:
            if row["source"] == "ISM_MANUFACTURING" and row["reference_period"] == "2026-08":
                row["reference_period"] = "2026-07"
        a = self.build(p)
        b = self.build(p, cutoff="2026-10-16T16:00:00Z")
        self.assertIsNone(a["sources"]["ISM_MANUFACTURING"]["changes_pp"])
        self.assertEqual(a["sources"]["ISM_MANUFACTURING"]["independent_reference_periods"],
                         b["sources"]["ISM_MANUFACTURING"]["independent_reference_periods"])

    def test_empty_all_blocked_and_strict_json(self):
        out = self.build(dict(evidence_mode="SYNTHETIC_FIXTURE", records=[]))
        self.assertEqual(out["status"], "BLOCKED_INPUT")
        self.assertEqual(len(out["missing_sources"]), 3)
        self.assertIsNone(out["current_market_regime"])
        self.assertNotIn(b"NaN", survey.encoded(out))
        self.assertNotIn(b"Infinity", survey.encoded(out))

    def test_input_and_record_resource_bounds(self):
        with self.assertRaisesRegex(ValueError, "input_size"):
            survey.read_json(b"x" * (survey.MAX_INPUT_BYTES + 1))
        with patch.object(survey, "MAX_RECORDS", 1), self.assertRaisesRegex(ValueError, "record_scope"):
            self.build()

    def test_legacy_fred_allowlist_is_unchanged(self):
        from tools import macro_history_sources as legacy
        self.assertEqual(len(legacy.registry()["series"]), 30)
        with patch.object(legacy, "fetch", side_effect=AssertionError("provider must not run")):
            with self.assertRaisesRegex(ValueError, "unknown_series"):
                legacy.collect("unused", ["ISM_MANUFACTURING"], "2026-01-01", "2026-10-15")

    def test_all_candidate_collection_and_economic_gates_closed(self):
        raw, contract = survey._contract()
        self.assertFalse(contract["default_collection_enabled"])
        self.assertFalse(contract["economic_authority"])
        self.assertEqual(len(contract["conditional_candidates"]), 6)
        out = self.build()
        for item in out["sources"].values():
            self.assertFalse(item["raw_bytes_verified"])
        self.assertEqual(out["contract_sha256"], survey.digest(raw))

    def test_non_string_clock_is_refused(self):
        p = fixture()
        p["records"][0]["published_at"] = None
        with self.assertRaisesRegex(ValueError, "clock_type"):
            self.build(p)

    def review(self, raw=None, **overrides):
        raw = b"date,bullish,neutral,bearish\n2026-10-14,31,30,39\n" if raw is None else raw
        args = dict(expected_sha256=survey.digest(raw),
                    collected_at="2026-10-15T12:00:00Z", decision_at=CUT, unit="percent")
        args.update(overrides)
        return survey.inspect_aaii_export(raw, **args)

    def test_export_reuses_existing_parser_and_preserves_unknown_publication(self):
        with patch.object(survey.free_context, "aaii_observations",
                          wraps=survey.free_context.aaii_observations) as parser:
            out = self.review()
        self.assertEqual(parser.call_count, 1)
        self.assertEqual(out["status"], "UNADMITTED_RESEARCH_CONTEXT")
        self.assertAlmostEqual(out["bull_bear_spread_pp"], -8)
        self.assertIsNone(out["published_at"])
        self.assertEqual(out["available_at"], "2026-10-15T12:00:00+00:00")
        self.assertTrue(out["input_bytes_verified"])
        for field in ["original_publisher_bytes_verified", "source_authenticated",
                      "supplier_rights_verified", "historical_pit_verified", "economic_authority"]:
            self.assertFalse(out[field])

    def test_export_percent_fraction_share_one_native_contract(self):
        raw = b"date,bullish,neutral,bearish\n2026-10-14,0.31,0.30,0.39\n"
        out = self.review(raw, unit="fraction")
        self.assertAlmostEqual(out["bull_bear_spread_pp"], -8)
        with self.assertRaises(survey.free_context.ContextError):
            self.review(raw, unit="percent")

    def test_export_hash_and_clock_refusals(self):
        for args in [dict(expected_sha256=None), dict(expected_sha256="b" * 64),
                     dict(collected_at="2026-10-16T12:00:00Z"),
                     dict(collected_at="2026-10-15"),
                     dict(decision_at="2027-01-01T00:00:00Z")]:
            with self.subTest(args=args), self.assertRaises(ValueError):
                self.review(**args)

    def test_export_invalid_raw_refused_by_existing_native_parser(self):
        for raw in [b"date,bullish,neutral,bearish\n2026-10-14,NaN,30,39\n",
                    b"date,bullish,neutral,bearish\n2026-10-14,,30,39\n",
                    b"date,bullish,neutral,bearish\n2026-10-14,31,30,39\n2026-10-14,31,30,39\n",
                    b"date,bullish,neutral,bearish\n2026-10-16,31,30,39\n"]:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                self.review(raw)

    def test_export_stale_latest_has_no_favorable_cache_fallback(self):
        raw = b"date,bullish,neutral,bearish\n2026-09-02,60,20,20\n2026-09-09,31,30,39\n"
        out = self.review(raw)
        self.assertEqual(out["status"], "BLOCKED_STALE")
        self.assertIsNone(out["bull_bear_spread_pp"])
        self.assertEqual(out["reference_period"], "2026-09-09")

    def test_existing_aaii_rounding_tolerance_is_not_relaxed(self):
        p = fixture()
        for row in p["records"]:
            if row["source"] == "AAII" and row["component"] == "neutral":
                row["value"] = 30.15
        self.assertEqual(self.build(p)["sources"]["AAII"]["status"], "BLOCKED")

    def test_fixture_aaii_math_reuses_existing_parser_each_release(self):
        with patch.object(survey.free_context, "aaii_observations",
                          wraps=survey.free_context.aaii_observations) as parser:
            self.build()
        self.assertEqual(parser.call_count, 2)

    def test_export_revisions_do_not_manufacture_independent_periods(self):
        raw = b"date,bullish,neutral,bearish\n2026-10-07,30,30,40\n2026-10-14,31,30,39\n"
        out = self.review(raw)
        self.assertEqual(out["independent_reference_periods"], 2)
        self.assertFalse(out["historical_pit_verified"])

    def test_cli_export_outputs_review_but_never_success_admission(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "authorized_fixture.csv"
            raw = b"date,bullish,neutral,bearish\n2026-10-14,31,30,39\n"
            source.write_bytes(raw)
            output = Path(temp) / "review.json"
            args = ["survey", "--input", str(source), "--decision-at", CUT,
                    "--evidence-mode", survey.EXPORT_REVIEW_MODE,
                    "--expected-input-sha256", survey.digest(raw),
                    "--collected-at", "2026-10-15T12:00:00Z", "--unit", "percent",
                    "--report", str(output)]
            with patch.object(sys, "argv", args), patch("sys.stdout", new_callable=io.StringIO):
                self.assertEqual(survey.main(), 2)
            payload = survey.read_json(output.read_bytes())
            self.assertEqual(payload["schema"], "r1000-aaii-local-export-review-v1")
            self.assertEqual(payload["status"], "UNADMITTED_RESEARCH_CONTEXT")
            self.assertFalse(payload["eligible_for_selector"])

    def test_deep10000_json_is_finite_refusal(self):
        raw = b'{"evidence_mode":"SYNTHETIC_FIXTURE","records":' + b'['*10000 + b'0' + b']'*10000 + b'}'
        with self.assertRaisesRegex(ValueError, "json_complexity"):
            survey.read_json(raw)

    def test_parsed_json_depth_is_bounded(self):
        raw = b'{"records":' + b'['*30 + b'0' + b']'*30 + b'}'
        with self.assertRaisesRegex(ValueError, "json_complexity"):
            survey.read_json(raw)

    def test_deep10000_cli_publishes_blocked_json(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "deep_fixture.json"
            source.write_bytes(b'{"evidence_mode":"SYNTHETIC_FIXTURE","records":' + b'['*10000 + b'0' + b']'*10000 + b'}')
            output = Path(temp) / "blocked.json"
            args = ["survey", "--input", str(source), "--decision-at", CUT,
                    "--evidence-mode", "SYNTHETIC_FIXTURE", "--report", str(output)]
            with patch.object(sys, "argv", args), patch("sys.stdout", new_callable=io.StringIO):
                self.assertEqual(survey.main(), 2)
            payload = survey.read_json(output.read_bytes())
            self.assertEqual(payload["status"], "BLOCKED_INPUT")
            self.assertFalse(payload["economic_authority"])

    def test_cli_actual_never_opens_supplied_source(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "blocked.json"
            argv = ["survey", "--input", str(Path(temp) / "must-not-read"),
                    "--decision-at", CUT, "--report", str(output)]
            with patch.object(sys, "argv", argv), patch("sys.stdout", new_callable=io.StringIO):
                self.assertEqual(survey.main(), 2)
            result = survey.read_json(output.read_bytes())
            self.assertEqual(result["status"], "BLOCKED_SOURCE_ADMISSION")
            self.assertFalse(result["economic_authority"])

    def test_cli_missing_or_malformed_fixture_publishes_blocked(self):
        with tempfile.TemporaryDirectory() as temp:
            raw = Path(temp) / "source.json"
            for index, content in enumerate([None, b"{broken", b'{"value":NaN}']):
                if content is not None:
                    raw.write_bytes(content)
                output = Path(temp) / (str(index) + ".json")
                argv = ["survey", "--input", str(raw), "--decision-at", CUT,
                        "--evidence-mode", "SYNTHETIC_FIXTURE", "--report", str(output)]
                with patch.object(sys, "argv", argv), patch("sys.stdout", new_callable=io.StringIO):
                    self.assertEqual(survey.main(), 2)
                self.assertEqual(survey.read_json(output.read_bytes())["status"], "BLOCKED_INPUT")


def run_tests():
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(SurveyTests))
    if not result.wasSuccessful():
        raise AssertionError("macro_survey_research_smoke_failed")


if __name__ == "__main__":
    run_tests()
