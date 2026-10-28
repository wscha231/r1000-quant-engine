# Derived library-boundary test unit; original full parent suite remains immutable.
# Original: tests/eodhd_calendar_trends_smoke.py SHA256 b0f52c6792931b2a56a1130aee36e721d9f19198978c00aa276647d98b038691
# Retained 53 unchanged cases; excluded 26 unadopted activation cases.
"""Synthetic Calendar/H1/transport contracts. Never send provider HTTP."""

from __future__ import annotations

import copy

import hashlib

import json

import sys

import unittest

from datetime import datetime, timezone

from pathlib import Path

from unittest.mock import patch

import requests

ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import eodhd_calendar_trends as cal

from tools import earnings_consensus_h1 as h1

NOW = datetime(2026, 10, 4, 10, 0, tzinfo=timezone.utc)

CLOCK = "2026-10-04T10:00:00Z"

KEY = "FIXTURE_ONLY_NOT_A_REAL_API_KEY"

def row(code="XAAA.US", fiscal="2026-12-31", period="0y", **changes):
    value = {"code": code, "date": fiscal, "period": period,
        "earningsEstimateAvg": "2.0", "earningsEstimateLow": "1.0",
        "earningsEstimateHigh": "3.0", "earningsEstimateNumberOfAnalysts": "4.0000",
        "revenueEstimateAvg": "200.0", "revenueEstimateLow": "100.0",
        "revenueEstimateHigh": "300.0", "revenueEstimateNumberOfAnalysts": "5.00",
        "epsTrendCurrent": "2.0", "epsTrend7daysAgo": "1.9",
        "epsTrend30daysAgo": "1.8", "epsTrend60daysAgo": "1.7",
        "epsTrend90daysAgo": "1.6", "epsRevisionsUpLast7days": "1.0",
        "epsRevisionsUpLast30days": "2.0", "epsRevisionsDownLast30days": "0.0"}
    value.update(changes)
    return value

def payload(symbols=("XAAA.US",), groups=None):
    return {"type": "Trends", "description": "SYNTHETIC TEST ONLY",
            "symbols": ",".join(symbols),
            "trends": groups if groups is not None else [[row(s)] for s in symbols]}

def build(value=None, symbols=("XAAA.US",), **clocks):
    args = {"observed_at": CLOCK, "collected_at": CLOCK}
    args.update(clocks)
    return cal.build_h1_batch(payload(symbols) if value is None else value, symbols, **args)

class CalendarTrendsTests(unittest.TestCase):
    def test_h1_persisted_validator_and_authority(self):
        snapshots, batch = build()
        self.assertEqual(len(snapshots), 1)
        h1.validate_persisted_snapshot(snapshots[0])
        self.assertFalse(snapshots[0]["h2_eligible"])
        self.assertFalse(batch["historical_pit_certified"])
        self.assertEqual(snapshots[0]["fetch_source"], "eodhd_calendar")

    def test_zero_is_not_missing(self):
        data = payload(groups=[[row(earningsEstimateAvg="0", earningsEstimateLow="-1")]])
        snapshot = build(data)[0][0]
        self.assertEqual(snapshot["est_eps_fy1"], 0)
        self.assertEqual(snapshot["eps_fy1_status"], "EXPLICIT_ZERO")
        self.assertEqual(snapshot["has_forward_estimate"], 1)

    def test_negative_eps_is_retained(self):
        data = payload(groups=[[row(earningsEstimateAvg="-2", earningsEstimateLow="-3", earningsEstimateHigh="-1")]])
        self.assertEqual(build(data)[0][0]["est_eps_fy1"], -2)

    def test_invalid_numeric_strings_and_boolean_stay_null(self):
        for value in ("NaN", "Infinity", "", "garbage", True, [], {}):
            with self.subTest(value=value):
                data = payload(groups=[[row(earningsEstimateAvg=value)]])
                snapshots, batch = build(data)
                self.assertIsNone(snapshots[0]["est_eps_fy1"])
                self.assertEqual(batch["by_symbol"]["XAAA.US"]["vendor_observations"][0]
                                 ["fields"]["earningsEstimateAvg"]["status"], "INVALID")

    def test_none_is_missing_and_not_invalid(self):
        self.assertEqual(cal.measurement(None)["status"], "MISSING")
        self.assertEqual(cal.measurement("0")["status"], "EXPLICIT_ZERO")

    def test_counts_require_nonnegative_integral_numbers(self):
        for value in (-1, True, "2.5", "Infinity", 1_000_001):
            self.assertIsNone(cal.measurement(value, count=True)["value"])
        self.assertEqual(cal.measurement("4.0000", count=True)["value"], 4)
        self.assertEqual(cal.measurement("0.0000", count=True)["value"], 0)

    def test_unknown_identity_not_inferred_from_us_ticker(self):
        snapshot = build()[0][0]
        identity = json.loads(snapshot["eps_fy1_identity"])
        for field in ("issuer_id", "security_id", "currency", "accounting_basis", "share_or_ADR_unit"):
            self.assertIsNone(identity[field])
        self.assertEqual(snapshot["identity_status"], "UNKNOWN_IDENTITY")
        self.assertIsNone(h1.same_period_revision(snapshot, snapshot))

    def test_supplied_identity_fields_are_preserved(self):
        data = payload(groups=[[row(issuer_id="CIK:FIXTURE1", security_id="FIGI:FIXTURE1",
            currency="USD", accounting_basis="NON_GAAP", share_or_ADR_unit="ADR:2")]])
        identity = json.loads(build(data)[0][0]["eps_fy1_identity"])
        self.assertEqual(identity["share_or_ADR_unit"], "ADR:2")
        self.assertEqual(identity["accounting_basis"], "NON_GAAP")

    def test_response_wide_issuer_is_not_broadcast_to_symbols(self):
        data = payload(("XAAA.US", "XBBB.US")); data["issuer_id"] = "CIK:WRONG"
        snapshots, _ = build(data, ("XAAA.US", "XBBB.US"))
        self.assertTrue(all(json.loads(s["eps_fy1_identity"])["issuer_id"] is None for s in snapshots))

    def test_metadata_boolean_is_rejected(self):
        with self.assertRaisesRegex(cal.CalendarError, "METADATA_TYPE"):
            build(payload(groups=[[row(currency=True)]]))

    def test_row_date_only_publication_blocks_availability(self):
        snapshot = build(payload(groups=[[row(provider_published_at="2026-10-04")]]))[0][0]
        self.assertIsNone(snapshot["available_from"])
        self.assertEqual(snapshot["publication_status"], "UNKNOWN_PUBLICATION_PRECISION")

    def test_response_date_only_publication_blocks_availability(self):
        data = payload(); data["provider_published_at"] = "2026-10-04"
        self.assertIsNone(build(data)[0][0]["available_from"])

    def test_fiscal_date_is_not_publication_date(self):
        snapshot = build()[0][0]
        self.assertIsNone(snapshot["provider_published_at"])
        self.assertEqual(snapshot["available_from"], CLOCK)

    def test_future_publication_does_not_backdate_availability(self):
        snapshot = build(payload(groups=[[row(provider_published_at="2026-10-05T10:00:00Z")]]))[0][0]
        self.assertEqual(snapshot["available_from"], "2026-10-05T10:00:00Z")

    def test_first_seen_is_response_completion(self):
        snapshot = build(collected_at="2026-10-04T10:00:05Z")[0][0]
        self.assertEqual(snapshot["first_seen_at"], "2026-10-04T10:00:05Z")
        self.assertEqual(snapshot["available_from"], "2026-10-04T10:00:05Z")

    def test_naive_or_backward_clocks_rejected(self):
        for kwargs in ({"observed_at": "2026-10-04"}, {"collected_at": "2026-10-03T10:00:00Z"}):
            with self.assertRaises(cal.CalendarError):
                build(**kwargs)

    def test_quarter_is_not_fy1(self):
        snapshot = build(payload(groups=[[row(period="+1q")]]))[0][0]
        self.assertIsNone(snapshot["est_eps_fy1"])
        self.assertEqual(snapshot["has_forward_estimate"], 0)
        self.assertEqual(h1.consensus_records(snapshot)[0]["identity"]["period_type"], "QUARTERLY")

    def test_all_four_relative_horizons_map_only_to_period_type(self):
        data = payload(groups=[[row(fiscal="2026-10-31", period="0q"),
            row(fiscal="2027-01-31", period="+1q"), row(period="0y"),
            row(fiscal="2027-12-31", period="+1y")]])
        snapshots, batch = build(data)
        self.assertEqual(len(h1.consensus_records(snapshots[0])), 8)
        self.assertEqual(snapshots[0]["eps_fy1_period_end"], "2026-12-31")
        self.assertEqual([r["relative_horizon"] for r in batch["by_symbol"]["XAAA.US"]["vendor_observations"]],
                         ["0q", "+1q", "0y", "+1y"])

    def test_old_fiscal_period_is_not_historical_snapshot(self):
        snapshot = build(payload(groups=[[row(fiscal="2017-12-31")]]))[0][0]
        self.assertEqual(snapshot["as_of_date"], "2026-10-04")
        self.assertEqual(snapshot["has_forward_estimate"], 0)
        self.assertEqual(len(h1.consensus_records(snapshot)), 2)

    def test_actual_and_year_ago_fields_are_not_consensus(self):
        data = payload(groups=[[{"code": "XAAA.US", "date": "2026-12-31", "period": "0y",
                                 "actual": 999, "earningsEstimateYearAgoEps": 777}]])
        snapshot = build(data)[0][0]
        self.assertIsNone(snapshot["est_eps_fy1"])
        self.assertIsNone(snapshot["earnings_surprise_last"])

    def test_lookbacks_are_separate_not_new_h1_fields_or_snapshots(self):
        snapshots, batch = build()
        self.assertEqual(len(snapshots), 1)
        self.assertFalse(set(cal.LOOKBACK_FIELDS) & set(snapshots[0]))
        self.assertIsNone(snapshots[0]["est_eps_revision_breadth"])
        obs = batch["by_symbol"]["XAAA.US"]["vendor_observations"][0]
        self.assertEqual(obs["fields"]["epsTrend90daysAgo"]["value"], 1.6)
        self.assertEqual(obs["lookback_status"], "PROVIDER_REPORTED_NOT_HISTORICAL_VINTAGES")
        self.assertNotIn("available_from", obs)

    def test_missing_down_revisions_not_zero_breadth(self):
        data = payload(groups=[[row(epsRevisionsDownLast30days=None)]])
        snapshots, batch = build(data)
        self.assertIsNone(batch["by_symbol"]["XAAA.US"]["vendor_observations"][0]
                          ["fields"]["epsRevisionsDownLast30days"]["value"])
        self.assertIsNone(snapshots[0]["est_eps_revision_breadth"])

    def test_reordered_response_maps_by_verified_echo_not_request_position(self):
        data = payload(("XBBB.US", "XAAA.US"), [[row("XBBB.US", earningsEstimateAvg="3")], [row()]])
        snapshots, _ = build(data, ("XAAA.US", "XBBB.US"))
        self.assertEqual([s["ticker"] for s in snapshots], ["XAAA", "XBBB"])
        self.assertEqual([s["est_eps_fy1"] for s in snapshots], [2, 3])

    def test_wrong_row_code_rejected(self):
        with self.assertRaisesRegex(cal.CalendarError, "SECURITY_MISMATCH"):
            build(payload(groups=[[row("XBBB.US")]]))

    def test_missing_or_extra_echo_symbol_rejected(self):
        with self.assertRaisesRegex(cal.CalendarError, "SYMBOL_SET_MISMATCH"):
            build(payload(("XAAA.US", "XBBB.US")))

    def test_no_row_code_inference_from_group_index(self):
        data = payload(); del data["trends"][0][0]["code"]
        with self.assertRaisesRegex(cal.CalendarError, "SECURITY_MISMATCH"):
            build(data)

    def test_empty_group_is_no_coverage_not_a_missing_symbol(self):
        snapshots, _ = build(payload(groups=[[]]))
        self.assertEqual(snapshots[0]["eps_fy1_status"], "NO_COVERAGE")
        with self.assertRaisesRegex(cal.CalendarError, "GROUP_COUNT"):
            build(payload(groups=[]))

    def test_flat_schema_or_error_payload_is_rejected(self):
        for data in ({"type": "Trends", "symbols": "XAAA.US", "trends": [row()]},
                     {"error": "fixture"}, {"General": {}, "Earnings": {}}):
            with self.assertRaises(cal.CalendarError):
                build(data)

    def test_duplicate_symbol_rejected(self):
        with self.assertRaises(cal.CalendarError):
            cal.symbols_checked(("XAAA.US", "XAAA.US"))

    def test_duplicate_period_rejected_even_when_relative_label_differs(self):
        for duplicate in (row(), row(period="+1y")):
            with self.assertRaisesRegex(cal.CalendarError, "DUPLICATE_FISCAL"):
                build(payload(groups=[[row(), duplicate]]))

    def test_quarter_and_year_same_end_are_distinct(self):
        snapshots, _ = build(payload(groups=[[row(period="0q"), row(period="0y")]]))
        self.assertEqual(len(h1.consensus_records(snapshots[0])), 4)

    def test_unsupported_period_and_invalid_date_rejected(self):
        for item in (row(period="+2y"), row(fiscal="2026-02-30"), row(fiscal="20261231"), row(fiscal=None)):
            with self.assertRaises(cal.CalendarError):
                build(payload(groups=[[item]]))

    def test_invalid_range_rejected(self):
        for item in (row(earningsEstimateLow="4"), row(revenueEstimateHigh="150")):
            with self.assertRaisesRegex(cal.CalendarError, "RANGE_CONFLICT"):
                build(payload(groups=[[item]]))

    def test_duplicate_json_keys_rejected_before_normalization(self):
        with self.assertRaisesRegex(cal.CalendarError, "DUPLICATE_JSON_KEY"):
            cal.strict_json_loads(b'{"type":"Trends","type":"Other"}')

    def test_nonfinite_json_literals_rejected(self):
        for token in (b'NaN', b'Infinity', b'-Infinity', b'1e999'):
            with self.assertRaises(cal.CalendarError):
                cal.strict_json_loads(b'{"x":' + token + b'}')

    def test_invalid_utf8_and_malformed_json_rejected(self):
        for data in (b'\xff', b'{', b''):
            with self.assertRaises(cal.CalendarError):
                cal.strict_json_loads(data)

    def test_byte_depth_node_and_record_limits(self):
        with patch.object(cal, "MAX_BYTES", 10):
            with self.assertRaises(cal.CalendarError):
                cal.strict_json_loads(b' ' * 11)
        with self.assertRaisesRegex(cal.CalendarError, "JSON_LIMIT"):
            cal.strict_json_loads(b'[' * 30 + b'0' + b']' * 30)
        with patch.object(cal, "MAX_NODES", 2):
            with self.assertRaises(cal.CalendarError):
                cal.strict_json_loads(b'[1,2]')
        with patch.object(cal, "MAX_RECORDS_PER_SYMBOL", 0):
            with self.assertRaises(cal.CalendarError):
                build()

    def test_symbols_are_explicit_simple_us_only(self):
        for symbols in ((), ("BRK.B.US",), ("AAPL",), ("7203.TSE",), ("xaaa.US",), (True,)):
            with self.assertRaises(cal.CalendarError):
                cal.symbols_checked(symbols)

    def test_deterministic_without_input_mutation(self):
        data = payload(); original = copy.deepcopy(data)
        self.assertEqual(build(data), build(data))
        self.assertEqual(data, original)

    def test_correction_nonzero_string_underflow_is_invalid_not_zero(self):
        data = payload(groups=[[row(earningsEstimateAvg="1e-999", earningsEstimateLow="-1")]])
        snapshots, batch = build(data)
        self.assertIsNone(snapshots[0]["est_eps_fy1"])
        field = batch["by_symbol"]["XAAA.US"]["vendor_observations"][0]["fields"]["earningsEstimateAvg"]
        self.assertEqual(field["status"], "INVALID")
        self.assertEqual(field["raw"], "1e-999")

    def test_correction_nonzero_count_underflow_is_not_zero_count(self):
        self.assertIsNone(cal.measurement("1e-999", count=True)["value"])

    def test_correction_rounded_fractional_count_is_not_integer(self):
        for value in ("4.0000000000000001", "0.0000000000000000001", "999999.99999999999"):
            with self.subTest(value=value):
                self.assertIsNone(cal.measurement(value, count=True)["value"])

    def test_correction_json_float_underflow_is_rejected_before_decode_loss(self):
        with self.assertRaisesRegex(cal.CalendarError, "NUMERIC_UNDERFLOW"):
            cal.strict_json_loads(b'{"value":1e-999}')

    def test_correction_json_negative_underflow_is_rejected(self):
        with self.assertRaisesRegex(cal.CalendarError, "NUMERIC_UNDERFLOW"):
            cal.strict_json_loads(b'{"value":-1e-999}')

    def test_correction_explicit_decimal_and_json_zero_are_preserved(self):
        for value in ("0", "-0", "0e-999", "0.0000000000"):
            self.assertEqual(cal.measurement(value)["status"], "EXPLICIT_ZERO")
        self.assertEqual(cal.strict_json_loads(b'{"value":0e-999}')["value"], 0)

    def test_correction_conflicting_explicit_fiscal_end_blocks(self):
        with self.assertRaisesRegex(cal.CalendarError, "CONFLICTING_FISCAL"):
            build(payload(groups=[[row(fiscal_period_end="2027-12-31")]]))

    def test_correction_conflicting_explicit_fiscal_date_ending_blocks(self):
        with self.assertRaisesRegex(cal.CalendarError, "CONFLICTING_FISCAL"):
            build(payload(groups=[[row(fiscalDateEnding="2027-12-31")]]))

    def test_correction_conflicting_explicit_period_type_blocks(self):
        with self.assertRaisesRegex(cal.CalendarError, "CONFLICTING_PERIOD_TYPE"):
            build(payload(groups=[[row(period_type="QUARTERLY")]]))

    def test_correction_agreeing_optional_period_metadata_is_retained(self):
        data = payload(groups=[[row(fiscal_period_end="2026-12-31", fiscalDateEnding="2026-12-31", period_type="ANNUAL")]])
        snapshot = build(data)[0][0]
        self.assertEqual(snapshot["est_eps_fy1"], 2)
        self.assertEqual(json.loads(snapshot["eps_fy1_identity"])["period_type"], "ANNUAL")

    def test_correction_explicit_actual_class_cannot_be_estimate(self):
        with self.assertRaisesRegex(cal.CalendarError, "NOT_ESTIMATE_RECORD"):
            build(payload(groups=[[row(is_estimate=False)]]))

    def test_correction_invalid_estimate_flag_is_not_truthy_admission(self):
        for value in (None, "false", "true", 0, 1, [], {}):
            with self.subTest(value=value), self.assertRaisesRegex(cal.CalendarError, "NOT_ESTIMATE_RECORD"):
                build(payload(groups=[[row(is_estimate=value)]]))

    def test_correction_explicit_estimate_true_still_passes(self):
        self.assertEqual(build(payload(groups=[[row(is_estimate=True)]]))[0][0]["est_eps_fy1"], 2)

    def test_correction_explicit_actual_or_history_type_blocks(self):
        for kind in ("actual", "ACTUAL", "history"):
            with self.subTest(kind=kind), self.assertRaisesRegex(cal.CalendarError, "NOT_ESTIMATE_RECORD"):
                build(payload(groups=[[row(type=kind)]]))


if __name__ == "__main__":
    unittest.main()

