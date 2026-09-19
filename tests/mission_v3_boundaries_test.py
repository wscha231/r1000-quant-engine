"""Additional executable boundaries. All generated NAVs/calendars are synthetic."""
from __future__ import annotations

import contextlib
import io
import json
import math
import random
import subprocess
import sys
import tempfile
import unittest
from datetime import date, timedelta
from decimal import (Inexact, ROUND_DOWN, ROUND_UP, localcontext, Decimal)
from pathlib import Path
from unittest import mock

from mission_v3_metrics_test import m, small, calculate, synthetic_bundle, ROOT


class MissionBoundaryTests(unittest.TestCase):
    def test_external_decimal_traps_cannot_break_measurement(self):
        rows, sessions = small(["100000", "33333", "100001"])
        expected = calculate(rows, sessions)
        with localcontext() as ctx:
            ctx.traps[Inexact] = True
            ctx.prec = 3
            ctx.Emax = 9
            self.assertEqual(calculate(rows, sessions), expected)

    def test_external_rounding_cannot_change_measurement(self):
        rows, sessions = small(["100000", "33333.333333", "100003.27"])
        expected = calculate(rows, sessions)
        for rounding in (ROUND_DOWN, ROUND_UP):
            with localcontext() as ctx:
                ctx.rounding = rounding
                self.assertEqual(calculate(rows, sessions), expected)

    def test_ambiguous_numeric_text_rejected(self):
        for value in ("1_000", "١٠٠", "１２３", "+1", "01", ".5", "1."):
            with self.subTest(value=value), self.assertRaises(m.InputError):
                m.number(value, "probe")

    def test_exponent_and_number_size_bounded(self):
        for value in ("1e-1001", "0e1001", "1e999999999", "1" * 121, 10 ** 121):
            with self.subTest(value=repr(value)), self.assertRaises(m.InputError):
                m.number(value, "probe")

    def test_reference_mapping_cannot_be_mutated(self):
        with self.assertRaises(TypeError):
            m.REFERENCE["main_max_mdd_loss"] = "0.25"

    def test_committed_reference_contract_matches_code(self):
        contract = json.loads((ROOT / "contracts/mission_v3.research.json").read_text())
        self.assertEqual(contract, dict(m.REFERENCE))

    def test_random_paths_match_independent_float_oracle(self):
        rng = random.Random(458)
        start = date(2020, 1, 1)
        sessions = [(start + timedelta(days=i * 10)).isoformat() for i in range(40)]
        for _ in range(100):
            values = [100000.0]
            for _ in sessions[1:]:
                values.append(round(values[-1] * rng.uniform(0.85, 1.20), 6))
            rows = [dict(date=d, nav=str(v), external_flow=0) for d, v in zip(sessions, values)]
            got = m.daily_metrics(rows, sessions, start=sessions[0], end=sessions[-1], initial_nav=100000)
            peak = values[0]
            expected_dd = 0.0
            for nav in values:
                peak = max(peak, nav)
                expected_dd = max(expected_dd, 1 - nav / peak)
            expected_cagr = math.expm1(math.log(values[-1] / values[0]) * 365.2425 / 390)
            self.assertAlmostEqual(float(got["mdd_loss_on_supplied_grid"]), expected_dd, places=12)
            self.assertAlmostEqual(float(got["cagr"]), expected_cagr, places=12)

    def test_peak_and_recovery_path(self):
        rows, sessions = small(["100000", "200000", "100000"])
        self.assertEqual(Decimal(calculate(rows, sessions)["mdd_loss_on_supplied_grid"]), Decimal("0.5"))

    def test_reference_window_cannot_drift(self):
        for key, value in (("start", "2019-09-17"), ("end", "2026-09-18"),
                           ("initial_nav", "1000000"), ("currency", "KRW")):
            bundle = synthetic_bundle()
            bundle["contract"][key] = value
            with self.subTest(key=key), self.assertRaises(m.InputError):
                m.assess_pair(bundle)

    def test_pair_shared_contracts_must_match(self):
        for key in ("run_id", "source_commit", "kernel_sha256", "execution_policy_sha256", "cost_policy_sha256"):
            bundle = synthetic_bundle()
            meta = bundle["portfolios"]["concentrated"]["metadata"]
            meta[key] = "DIFFERENT" if key == "run_id" else "9" * (40 if key == "source_commit" else 64)
            with self.subTest(key=key), self.assertRaises(m.InputError):
                m.assess_pair(bundle)

    def test_two_point_grid_never_authenticated(self):
        # Caller could lie about sampling. M0-A must NEVER certify the calendar.
        bundle = synthetic_bundle()
        bundle["sessions"] = [bundle["sessions"][0], bundle["sessions"][-1]]
        for p in bundle["portfolios"].values():
            p["nav_rows"] = [p["nav_rows"][0], p["nav_rows"][-1]]
        got = m.assess_pair(bundle)
        self.assertEqual(got["numeric_status"], "METRIC_PASS_UNVERIFIED")
        self.assertEqual(got["mission_status"], "NOT_PROVEN")
        for p in got["portfolios"].values():
            self.assertFalse(p["metrics"]["calendar_and_accounting_authenticated"])

    def test_oversized_session_list_rejected(self):
        with self.assertRaises(m.InputError):
            m.daily_metrics([], ["2020-01-01"] * (m.MAX_OBSERVATIONS + 1),
                            start="2020-01-01", end="2020-01-02", initial_nav=100000)

    def test_nested_duplicate_json_key_rejected(self):
        with self.assertRaises(m.InputError):
            m.strict_json('{"outer":{"nav":"1","nav":"2"}}')

    def test_json_huge_exponent_rejected(self):
        with self.assertRaises(m.InputError):
            m.strict_json('{"nav":1e1000000}')

    def test_deep_json_error_is_controlled(self):
        with self.assertRaises(m.InputError):
            m.strict_json("[" * 5000 + "0" + "]" * 5000)

    def test_missing_metadata_and_wrong_sleeve_rejected(self):
        for kind in ("missing", "wrong_sleeve", "hash", "run_id"):
            b = synthetic_bundle()
            meta = b["portfolios"]["main"]["metadata"]
            if kind == "missing":
                del meta["source_commit"]
            elif kind == "wrong_sleeve":
                meta["sleeve"] = "concentrated"
            elif kind == "hash":
                meta["source_commit"] = "a" * 39
            else:
                meta["run_id"] = "  "
            with self.subTest(kind=kind), self.assertRaises(m.InputError):
                m.assess_pair(b)

    def test_output_metadata_is_detached_from_input(self):
        b = synthetic_bundle()
        out = m.assess_pair(b)
        b["portfolios"]["main"]["metadata"]["run_id"] = "CHANGED"
        self.assertEqual(out["declared_metadata"]["main"]["run_id"], "SYNTHETIC-TEST-ONLY")

    def test_cli_numeric_success_and_failure_never_promote(self):
        with tempfile.TemporaryDirectory() as tmp:
            for passing in (True, False):
                b = synthetic_bundle()
                if not passing:
                    for p in b["portfolios"].values():
                        for row in p["nav_rows"]:
                            row["nav"] = "100000"
                path = Path(tmp) / "bundle.json"
                text = json.dumps(b)
                path.write_text(text, encoding="utf-8")
                process = subprocess.run([sys.executable, str(Path(m.__file__)), str(path)],
                                         capture_output=True, text=True, timeout=10)
                self.assertEqual(process.returncode, 0, process.stderr)
                out = json.loads(process.stdout)
                self.assertEqual(out["numeric_status"], "METRIC_PASS_UNVERIFIED" if passing else "METRIC_FAIL")
                self.assertEqual(out["mission_status"], "NOT_PROVEN")
                self.assertFalse(out["orders_allowed"])
                self.assertEqual(path.read_text(), text)

    def test_cli_invalid_utf8_json_and_missing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            for kind, data in (("utf8", b"\xff"), ("json", b'{"nav":NaN}'), ("missing", None)):
                path = Path(tmp) / kind
                if data is not None:
                    path.write_bytes(data)
                process = subprocess.run([sys.executable, str(Path(m.__file__)), str(path)],
                                         capture_output=True, text=True, timeout=10)
                self.assertEqual(process.returncode, 2)
                out = json.loads(process.stdout)
                self.assertEqual(out["numeric_status"], "INVALID_INPUT")
                self.assertFalse(out["production_promotion_allowed"])
                self.assertNotIn("Traceback", process.stderr)

    def test_cli_read_size_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "oversize.json"
            path.write_bytes(b" " * 129)
            capture = io.StringIO()
            with mock.patch.object(m, "MAX_INPUT_BYTES", 128), contextlib.redirect_stdout(capture):
                result = m.main([str(path)])
            self.assertEqual(result, 2)
            self.assertEqual(json.loads(capture.getvalue())["error"], "INPUT_TOO_LARGE")

    def test_numeric_domains_and_unknown_sleeve(self):
        for sleeve, cagr, dd in (("other", "1", "0"), ("main", "-1.1", "0"),
                                ("main", "1", "-0.01"), ("main", "1", "1.01")):
            with self.subTest(sleeve=sleeve, cagr=cagr, dd=dd), self.assertRaises(m.InputError):
                m.threshold_check(sleeve, dict(cagr=cagr, mdd_loss_on_supplied_grid=dd))

    def test_depth_counter_ignores_brackets_inside_strings(self):
        payload = {"s": "[" * 100 + '\"' + "\\" + "]" * 100}
        self.assertEqual(m.strict_json(json.dumps(payload)), payload)

    def test_json_exact_nesting_limit(self):
        self.assertIsInstance(m.strict_json("[" * 64 + "0" + "]" * 64), list)
        with self.assertRaises(m.InputError):
            m.strict_json("[" * 65 + "0" + "]" * 65)

    def test_negative_zero_is_zero_not_missing(self):
        self.assertEqual(m.number("-0.0", "x"), Decimal(0))


if __name__ == "__main__":
    unittest.main()
