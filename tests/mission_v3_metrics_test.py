from __future__ import annotations

import copy
import json
import sys
import unittest
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research_only" / "mission_v3"))
import mission_metrics as m


def synthetic_bundle():
    # Deliberately synthetic weekday calendar, NOT an exchange calendar.
    current = date.fromisoformat(m.REFERENCE["start"])
    end = date.fromisoformat(m.REFERENCE["end"])
    sessions = []
    while current <= end:
        if current.weekday() < 5:
            sessions.append(current.isoformat())
        current += timedelta(days=1)
    result = {"contract": dict(m.REFERENCE), "sessions": sessions, "portfolios": {}}
    for sleeve, final in (("main", Decimal("2000000")),
                          ("concentrated", Decimal("5000000"))):
        meta = {
            "sleeve": sleeve, "run_id": "SYNTHETIC-TEST-ONLY",
            "source_commit": "a" * 40, "kernel_sha256": "b" * 64,
            "data_release_sha256": "c" * 64,
            "execution_policy_sha256": "d" * 64,
            "cost_policy_sha256": "e" * 64,
            "portfolio_policy_sha256": ("f" if sleeve == "main" else "a") * 64,
            "currency": "USD", "sampling": "DAILY_EOD_LEDGER",
            "nav_basis": "NET_WITHOUT_EXTERNAL_FLOWS",
        }
        initial = Decimal(m.REFERENCE["initial_nav"])
        rows = [{"date": stamp,
                 "nav": str(initial + (final - initial) * Decimal(i)
                            / Decimal(len(sessions) - 1)),
                 "external_flow": "0"}
                for i, stamp in enumerate(sessions)]
        result["portfolios"][sleeve] = {"metadata": meta, "nav_rows": rows}
    return result


def small(values):
    sessions = ["2020-01-02", "2020-01-03", "2020-01-06"]
    rows = [{"date": stamp, "nav": value, "external_flow": 0}
            for stamp, value in zip(sessions, values)]
    return rows, sessions


def calculate(rows, sessions):
    return m.daily_metrics(rows, sessions, start="2020-01-02",
                           end="2020-01-06", initial_nav="100000")


class MissionMetricTests(unittest.TestCase):
    def test_first_loss_is_included(self):
        rows, sessions = small(["100000", "80000", "100000"])
        self.assertEqual(Decimal(calculate(rows, sessions)["mdd_loss_on_supplied_grid"]),
                         Decimal("0.2"))

    def test_elapsed_days_not_observation_count(self):
        rows, sessions = small(["100000", "100000", "100001"])
        result = calculate(rows, sessions)
        self.assertEqual(result["elapsed_calendar_days"], 4)
        self.assertEqual(result["observations_in_supplied_grid"], 3)

    def test_constant_nav_is_zero_growth(self):
        rows, sessions = small(["100000"] * 3)
        result = calculate(rows, sessions)
        self.assertEqual(Decimal(result["cagr"]), 0)
        self.assertEqual(Decimal(result["mdd_loss_on_supplied_grid"]), 0)

    def test_total_loss_not_missing(self):
        rows, sessions = small(["100000", "0", "0"])
        result = calculate(rows, sessions)
        self.assertEqual(Decimal(result["cagr"]), -1)
        self.assertEqual(Decimal(result["mdd_loss_on_supplied_grid"]), 1)

    def test_resurrection_rejected(self):
        rows, sessions = small(["100000", "0", "1"])
        with self.assertRaises(m.InputError):
            calculate(rows, sessions)

    def test_invalid_numeric_inputs_rejected(self):
        for value in (None, True, False, "", "NaN", "Infinity", float("nan"),
                      float("inf"), " 100000", {}, []):
            with self.subTest(value=repr(value)):
                rows, sessions = small(["100000", value, "100000"])
                with self.assertRaises(m.InputError):
                    calculate(rows, sessions)

    def test_negative_nav_rejected(self):
        rows, sessions = small(["100000", "-1", "100000"])
        with self.assertRaises(m.InputError):
            calculate(rows, sessions)

    def test_external_flow_not_alpha(self):
        for flow in ("1", "-1", True, None):
            with self.subTest(flow=flow):
                rows, sessions = small(["100000"] * 3)
                rows[1]["external_flow"] = flow
                with self.assertRaises(m.InputError):
                    calculate(rows, sessions)

    def test_missing_row_rejected(self):
        rows, sessions = small(["100000"] * 3)
        with self.assertRaises(m.InputError):
            calculate(rows[1:], sessions)

    def test_duplicate_session_rejected(self):
        rows, sessions = small(["100000"] * 3)
        sessions[1] = sessions[0]
        with self.assertRaises(m.InputError):
            calculate(rows, sessions)

    def test_out_of_order_rejected(self):
        rows, sessions = small(["100000"] * 3)
        with self.assertRaises(m.InputError):
            calculate(list(reversed(rows)), list(reversed(sessions)))

    def test_nav_date_mismatch_rejected(self):
        rows, sessions = small(["100000"] * 3)
        rows[1]["date"] = "2020-01-04"
        with self.assertRaises(m.InputError):
            calculate(rows, sessions)

    def test_initial_anchor_mismatch_rejected(self):
        rows, sessions = small(["99999", "100000", "100000"])
        with self.assertRaises(m.InputError):
            calculate(rows, sessions)

    def test_unknown_row_field_rejected(self):
        rows, sessions = small(["100000"] * 3)
        rows[0]["certified"] = True
        with self.assertRaises(m.InputError):
            calculate(rows, sessions)

    def test_target_relaxation_rejected(self):
        bundle = synthetic_bundle()
        bundle["contract"]["main_max_mdd_loss"] = "0.25"
        with self.assertRaises(m.InputError):
            m.assess_pair(bundle)

    def test_different_release_between_sleeves_rejected(self):
        bundle = synthetic_bundle()
        bundle["portfolios"]["concentrated"]["metadata"]["data_release_sha256"] = "f" * 64
        with self.assertRaises(m.InputError):
            m.assess_pair(bundle)

    def test_checkpoint_declaration_rejected(self):
        bundle = synthetic_bundle()
        bundle["portfolios"]["main"]["metadata"]["sampling"] = "MONTHLY_CHECKPOINT"
        with self.assertRaises(m.InputError):
            m.assess_pair(bundle)

    def test_self_attested_pit_flag_not_admitted(self):
        bundle = synthetic_bundle()
        bundle["portfolios"]["main"]["metadata"]["pit_ok"] = True
        with self.assertRaises(m.InputError):
            m.assess_pair(bundle)

    def test_numeric_pass_never_certifies(self):
        result = m.assess_pair(synthetic_bundle())
        self.assertEqual(result["numeric_status"], "METRIC_PASS_UNVERIFIED")
        self.assertEqual(result["mission_status"], "NOT_PROVEN")
        self.assertFalse(result["orders_allowed"])
        self.assertFalse(result["production_promotion_allowed"])
        self.assertTrue(result["unverified_domains"])

    def test_exact_thresholds(self):
        metric = lambda c, d: {"cagr": c, "mdd_loss_on_supplied_grid": d}
        self.assertTrue(m.threshold_check("main", metric("0.35", "0.20")))
        self.assertFalse(m.threshold_check("main", metric("0.349999999", "0.20")))
        self.assertFalse(m.threshold_check("main", metric("0.35", "0.200000001")))
        self.assertTrue(m.threshold_check("concentrated", metric("0.50", "0.25")))
        self.assertFalse(m.threshold_check("concentrated", metric("0.50", "0.250000001")))

    def test_json_duplicates_and_nonfinite_rejected(self):
        for text in ('{"nav":1,"nav":2}', '{"nav":NaN}', '{"nav":Infinity}'):
            with self.subTest(text=text):
                with self.assertRaises(m.InputError):
                    m.strict_json(text)

    def test_invalid_calendar_dates_rejected(self):
        for value in (20240331, "20240331", "2026-02-30", "2026-09-19T00:00:00Z"):
            with self.subTest(value=value):
                with self.assertRaises(m.InputError):
                    m.day(value)

    def test_inputs_unchanged_and_deterministic(self):
        bundle = synthetic_bundle()
        original = copy.deepcopy(bundle)
        first = m.assess_pair(bundle)
        second = m.assess_pair(bundle)
        self.assertEqual(bundle, original)
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
