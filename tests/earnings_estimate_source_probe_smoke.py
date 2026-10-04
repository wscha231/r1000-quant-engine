"""Offline regression for source-only credential wiring and access probes."""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import requests
import yaml

from tools import probe_earnings_estimate_sources as probe

NOW = datetime(2026, 10, 4, 1, 0, tzinfo=timezone.utc)
KEY1, KEY2, EODKEY = "fixture-primary-token-only", "fixture-secondary-token-only", "fixture-eodhd-token-only"
ENV = {"FMP_API_KEY": KEY1, "FMP_API_KEY2": KEY2, "EODHD_API_KEY": EODKEY}
FMP = [{"symbol": "AAPL", "date": "2027-09-30", "epsAvg": 0,
        "revenueAvg": 100, "numberAnalystsEstimatedEps": 4}]


def eod_payload():
    return {"General": {"Code": "AAPL"}, "Earnings": {
        "Annual": {"2025-09-30": {"epsActual": 999}},
        "History": {"2026-06-30": {"epsEstimate": 999}},
        "Trend": {"Annual": {"2027-09-30": {"date": "2027-09-30", "earningsEstimateAvg": "0", "revenueEstimateAvg": "100"}},
                  "Quarterly": {"2027-09-30": {"date": "2027-09-30", "earningsEstimateAvg": "1", "revenueEstimateAvg": None}}}}}


class Response:
    def __init__(self, data, status=200, raw=None):
        self.status_code, self.closed = status, False
        self.raw = json.dumps(data).encode() if raw is None else raw
    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError("private request details " + KEY2, response=self)
    def iter_content(self, chunk_size):
        yield self.raw
    def close(self): self.closed = True


class Transport:
    def __init__(self, *responses):
        self.responses, self.calls = list(responses), []
        self.trust_env = True
    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if not self.responses:
            raise AssertionError("unexpected network request")
        return self.responses.pop(0)


class SourceProbeTests(unittest.TestCase):
    def run_fmp(self, transport, provider="fmp2", env=None, **kwargs):
        options = dict(max_http=3, api_units=3, quota_verified_at=NOW.isoformat(),
                       env=ENV if env is None else env, transport=transport, now=lambda: NOW)
        options.update(kwargs)
        return probe.run_probe(provider, ["AAPL"], **options)

    def test_secondary_key_selected_without_rotation(self):
        transport = Transport(Response(FMP))
        report, rows = self.run_fmp(transport)
        self.assertEqual(transport.calls[0][1]["params"]["apikey"], KEY2)
        self.assertEqual(len(transport.calls), 1)
        self.assertEqual(report["credential_alias"], "FMP_API_KEY2")
        self.assertEqual(rows[0]["est_eps_fy1"], 0)
        self.assertEqual(report["results"][0]["records_with_verified_identity"], 0)
        self.assertFalse(report["h2_eligible"])
        self.assertNotIn(KEY2, json.dumps(report))

    def test_missing_secondary_never_falls_back_to_primary(self):
        transport = Transport()
        report, _ = self.run_fmp(transport, env={"FMP_API_KEY": KEY1})
        self.assertEqual(report["status"], "MISSING_SELECTED_SECRET")
        self.assertEqual(transport.calls, [])

    def test_stale_unknown_and_future_quota_perform_no_request(self):
        for stamp in ("", "2026-10-03T01:00:00Z", "2026-10-04T01:01:00Z", "bad"):
            transport = Transport()
            report, _ = self.run_fmp(transport, quota_verified_at=stamp)
            self.assertEqual(report["status"], "FRESH_SHARED_QUOTA_EVIDENCE_REQUIRED")
            self.assertEqual(transport.calls, [])

    def test_zero_quota_and_malformed_secret_perform_no_request(self):
        for options in ({"api_units": 0}, {"env": {"FMP_API_KEY2": "secret\nwith newline"}}):
            transport = Transport()
            report, _ = self.run_fmp(transport, **options)
            self.assertEqual(report["http_requests_attempted"], 0)
            self.assertEqual(transport.calls, [])

    def test_global_request_and_unit_reservations_precede_network(self):
        transport = Transport(Response(FMP))
        session = probe.BoundedSession(1, 1, transport)
        session.get("https://financialmodelingprep.com/stable/analyst-estimates", params={"symbol": "AAPL"}, timeout=20)
        with self.assertRaises(probe.ProbeBlocked):
            session.get("https://financialmodelingprep.com/stable/analyst-estimates", params={"symbol": "AAPL"}, timeout=20)
        self.assertEqual((session.http_attempts, session.api_units_reserved), (1, 1))
        self.assertFalse(transport.calls[0][1]["allow_redirects"])
        self.assertFalse(transport.trust_env)
        self.assertEqual(len(transport.calls), 1)

    def test_unapproved_hosts_and_embedded_credentials_are_rejected(self):
        session = probe.BoundedSession(3, 3, Transport())
        for url in ("http://eodhd.com/api/user", "https://example.invalid/api/user",
                    "https://eodhd.com/api/user?api_token=" + EODKEY,
                    "https://eodhd.com/api/user#fragment"):
            with self.assertRaises(probe.ProbeBlocked):
                session.get(url, params={}, timeout=20)
        self.assertEqual(session.http_attempts, 0)

    def test_redirect_and_oversized_response_are_not_followed_or_retried(self):
        for response in (Response({}, status=302), Response({}, raw=b"x" * (probe.MAX_BYTES + 1))):
            transport = Transport(response)
            session = probe.BoundedSession(3, 3, transport)
            with self.assertRaises(probe.ProbeBlocked):
                session.get("https://financialmodelingprep.com/stable/analyst-estimates", params={}, timeout=20)
            self.assertEqual(len(transport.calls), 1)
            self.assertTrue(response.closed)

    def test_security_specific_402_preserves_other_fmp_successes(self):
        transport = Transport(Response({}, 402), Response(FMP))
        report, rows = probe.run_probe("fmp2", ["ARM", "AAPL"], max_http=2, api_units=2,
            quota_verified_at=NOW.isoformat(), env=ENV, transport=transport, now=lambda: NOW)
        self.assertEqual(len(transport.calls), 2)
        self.assertEqual(report["results"][0]["http_statuses"], [402])
        self.assertEqual(len(rows), 1)
        self.assertEqual(report["status"], "SAMPLE_PROBED")
        self.assertNotIn(KEY2, json.dumps(report))

    def test_fmp_403_stops_without_switching_keys(self):
        transport = Transport(Response({}, 403))
        report, _ = probe.run_probe("fmp2", ["AAPL", "MSFT"], max_http=2, api_units=2,
            quota_verified_at=NOW.isoformat(), env=ENV, transport=transport, now=lambda: NOW)
        self.assertEqual(len(transport.calls), 1)
        self.assertEqual(report["http_requests_attempted"], 1)
        self.assertEqual(report["status"], "PROVIDER_AUTHORIZATION_REJECTED")

    def test_fmp_auth_rejection_after_success_retains_data_but_is_terminal(self):
        for provider, selected_key in (("fmp", KEY1), ("fmp2", KEY2)):
            for status in (401, 403):
                with self.subTest(provider=provider, status=status):
                    transport = Transport(Response(FMP), Response({}, status),
                                          Response([dict(FMP[0], symbol="TSLA")]))
                    report, rows = probe.run_probe(provider, ["AAPL", "MSFT", "TSLA"],
                        max_http=3, api_units=3, quota_verified_at=NOW.isoformat(),
                        env=ENV, transport=transport, now=lambda: NOW)
                    self.assertEqual(report["status"], "PROVIDER_AUTHORIZATION_REJECTED")
                    self.assertEqual(report["results"][1]["http_statuses"], [status])
                    self.assertEqual([r["ticker"] for r in report["results"]], ["AAPL", "MSFT"])
                    self.assertEqual(len(rows), 1)
                    self.assertEqual(rows[0]["est_eps_fy1"], 0)
                    self.assertEqual(report["securities_with_observed_eps"], 1)
                    self.assertEqual((report["http_requests_attempted"],
                                      report["api_units_reserved_upper_bound"]), (2, 2))
                    self.assertEqual(len(transport.calls), 2)
                    self.assertEqual(len(transport.responses), 1)
                    self.assertTrue(all(call[1]["params"]["apikey"] == selected_key
                                        for call in transport.calls))
                    self.assertNotIn(selected_key, json.dumps(report))

    def test_fmp_local_blocks_after_success_are_terminal_and_keep_prior_data(self):
        cases = (("REQUEST_BUDGET_EXHAUSTED", 1, 3, lambda: Response(FMP)),
                 ("REQUEST_BUDGET_EXHAUSTED", 3, 1, lambda: Response(FMP)),
                 ("REDIRECT_REFUSED", 3, 3, lambda: Response({}, 302)),
                 ("RESPONSE_TOO_LARGE", 3, 3, lambda: Response({}, raw=b"x" * (probe.MAX_BYTES + 1))),
                 ("PROVIDER_SECURITY_MISMATCH", 3, 3, lambda: Response(FMP)),
                 ("INVALID_PROVIDER_SCHEMA", 3, 3, lambda: Response({"Error Message": KEY2})))
        for provider in ("fmp", "fmp2"):
            for expected, max_http, api_units, second in cases:
                with self.subTest(provider=provider, status=expected, http=max_http, units=api_units):
                    transport = Transport(Response(FMP), second(), Response([dict(FMP[0], symbol="TSLA")]))
                    report, rows = probe.run_probe(provider, ["AAPL", "MSFT", "TSLA"],
                        max_http=max_http, api_units=api_units, quota_verified_at=NOW.isoformat(),
                        env=ENV, transport=transport, now=lambda: NOW)
                    attempts = 1 if expected == "REQUEST_BUDGET_EXHAUSTED" else 2
                    self.assertEqual(report["status"], expected)
                    self.assertEqual((len(rows), report["source_snapshots_in_memory"]), (1, 1))
                    self.assertEqual(report["securities_with_observed_eps"], 1)
                    self.assertEqual(report["securities_with_observed_revenue"], 1)
                    self.assertEqual(report["http_requests_attempted"], attempts)
                    self.assertEqual(report["api_units_reserved_upper_bound"], attempts)
                    self.assertEqual(len(transport.calls), attempts)
                    self.assertTrue(all(call[1]["params"]["symbol"] != "TSLA" for call in transport.calls))
                    self.assertNotIn(KEY2, json.dumps(report))

    def test_cli_fmp_local_blocks_after_success_exit_nonzero(self):
        cases = (("REQUEST_BUDGET_EXHAUSTED", 1, 3, lambda: Response(FMP)),
                 ("REQUEST_BUDGET_EXHAUSTED", 3, 1, lambda: Response(FMP)),
                 ("REDIRECT_REFUSED", 3, 3, lambda: Response({}, 302)),
                 ("RESPONSE_TOO_LARGE", 3, 3, lambda: Response({}, raw=b"x" * (probe.MAX_BYTES + 1))),
                 ("PROVIDER_SECURITY_MISMATCH", 3, 3, lambda: Response(FMP)))
        for provider in ("fmp", "fmp2"):
            for expected, max_http, api_units, second in cases:
                with self.subTest(provider=provider, status=expected, http=max_http, units=api_units), \
                     tempfile.TemporaryDirectory() as folder:
                    root = Path(folder).resolve()
                    output = root / "outputs" / "earnings_estimate_source_probe" / "report.json"
                    transport = Transport(Response(FMP), second(), Response([dict(FMP[0], symbol="TSLA")]))
                    argv = ["probe", "--provider", provider, "--tickers", "AAPL,MSFT,TSLA",
                            "--max-http-requests", str(max_http), "--verified-api-units", str(api_units),
                            "--quota-verified-at-utc", datetime.now(timezone.utc).isoformat(),
                            "--output", str(output)]
                    with patch.object(probe, "ROOT", root), patch.object(sys, "argv", argv), \
                         patch.dict(os.environ, ENV, clear=True), \
                         patch.object(probe.requests, "Session", return_value=transport), \
                         contextlib.redirect_stdout(io.StringIO()):
                        self.assertEqual(probe.main(), 2)
                    report = json.loads(output.read_text(encoding="utf-8"))
                    self.assertEqual(report["status"], expected)
                    self.assertEqual(report["source_snapshots_in_memory"], 1)
                    self.assertLessEqual(len(transport.calls), 2)
                    self.assertNotIn("TSLA", [call[1]["params"]["symbol"] for call in transport.calls])

    def test_only_security_specific_402_can_continue_after_prior_success(self):
        for provider in ("fmp", "fmp2"):
            for status in (404, 429, 500, 503):
                with self.subTest(provider=provider, status=status):
                    transport = Transport(Response(FMP), Response({}, status), Response(FMP))
                    report, rows = probe.run_probe(provider, ["AAPL", "MSFT", "TSLA"],
                        max_http=3, api_units=3, quota_verified_at=NOW.isoformat(),
                        env=ENV, transport=transport, now=lambda: NOW)
                    self.assertEqual(report["status"], "PROVIDER_HTTP_REJECTED")
                    self.assertEqual(report["http_status"], status)
                    self.assertEqual(report["results"][1]["http_statuses"], [status])
                    self.assertEqual((len(rows), len(transport.calls)), (1, 2))

    def test_network_failure_after_prior_success_is_terminal(self):
        class TimeoutTransport(Transport):
            def get(self, url, **kwargs):
                if len(self.calls) == 1:
                    self.calls.append((url, kwargs))
                    raise requests.Timeout("private request " + KEY2)
                return super().get(url, **kwargs)
        for provider in ("fmp", "fmp2"):
            transport = TimeoutTransport(Response(FMP), Response(FMP))
            report, rows = probe.run_probe(provider, ["AAPL", "MSFT", "TSLA"],
                max_http=3, api_units=3, quota_verified_at=NOW.isoformat(),
                env=ENV, transport=transport, now=lambda: NOW)
            self.assertEqual(report["status"], "NETWORK_OR_INVALID_PROVIDER_RESPONSE")
            self.assertEqual((len(rows), len(transport.calls), report["http_requests_attempted"]), (1, 2, 2))
            self.assertNotIn(KEY2, json.dumps(report))

    def test_partial_402_cannot_hide_utc_day_change(self):
        later = datetime(2026, 10, 5, 0, 0, tzinfo=timezone.utc)
        timestamps = iter((NOW, NOW, NOW, NOW))
        transport = Transport(Response(FMP), Response({}, 402), Response(FMP))
        report, rows = probe.run_probe("fmp2", ["AAPL", "MSFT", "TSLA"],
            max_http=3, api_units=3, quota_verified_at=NOW.isoformat(),
            env=ENV, transport=transport, now=lambda: next(timestamps, later))
        self.assertEqual(report["status"], "UTC_COLLECTION_DAY_CHANGED")
        self.assertEqual((len(rows), len(transport.calls)), (1, 2))

    def test_required_pr_runner_registers_wrapper_with_probe_suite(self):
        from tools.run_pr_validation import DEFAULT_TESTS
        from tests import earnings_consensus_h1_smoke as wrapper
        self.assertEqual([path for path, _ in DEFAULT_TESTS].count("tests/earnings_consensus_h1_smoke.py"), 1)
        self.assertIs(wrapper.SourceProbeTests, SourceProbeTests)

    def test_cli_fmp_auth_rejection_after_success_exits_nonzero(self):
        for provider in ("fmp", "fmp2"):
            for status in (401, 403):
                with self.subTest(provider=provider, status=status), tempfile.TemporaryDirectory() as folder:
                    root = Path(folder).resolve()
                    output = root / "outputs" / "earnings_estimate_source_probe" / "report.json"
                    transport = Transport(Response(FMP), Response({}, status),
                                          Response([dict(FMP[0], symbol="TSLA")]))
                    argv = ["probe", "--provider", provider, "--tickers", "AAPL,MSFT,TSLA",
                            "--max-http-requests", "3", "--verified-api-units", "3",
                            "--quota-verified-at-utc", datetime.now(timezone.utc).isoformat(),
                            "--output", str(output)]
                    with patch.object(probe, "ROOT", root), patch.object(sys, "argv", argv), \
                         patch.dict(os.environ, ENV, clear=True), \
                         patch.object(probe.requests, "Session", return_value=transport), \
                         contextlib.redirect_stdout(io.StringIO()):
                        self.assertEqual(probe.main(), 2)
                    report = json.loads(output.read_text(encoding="utf-8"))
                    self.assertEqual(report["status"], "PROVIDER_AUTHORIZATION_REJECTED")
                    self.assertEqual(report["source_snapshots_in_memory"], 1)
                    self.assertEqual(report["securities_with_observed_eps"], 1)
                    self.assertEqual(report["http_requests_attempted"], 2)
                    self.assertEqual(len(transport.calls), 2)
                    self.assertEqual(list(output.parent.glob(".estimate_probe_*.json")), [])

    def test_eodhd_missing_security_identity_remains_unknown_with_other_metadata_complete(self):
        payload = eod_payload()
        for section in payload["Earnings"]["Trend"].values():
            for item in section.values():
                item.update(issuer_id="provider-issuer-123", accounting_basis="ADJUSTED",
                            currency="USD", share_or_ADR_unit="PER_SHARE")
        transport = Transport(Response({"apiRequests": "0", "dailyRateLimit": "20",
                                        "apiRequestsDate": None}), Response(payload))
        report, rows = probe.run_probe("eodhd", ["AAPL"], max_http=2, api_units=10,
            env=ENV, transport=transport, now=lambda: NOW)
        self.assertEqual(report["status"], "SAMPLE_PROBED")
        self.assertEqual(report["results"][0]["records_with_verified_identity"], 0)
        self.assertEqual(rows[0]["identity_status"], "UNKNOWN_IDENTITY")
        records = json.loads(rows[0]["consensus_observations_json"])
        self.assertEqual(len(records), 4)
        self.assertTrue(all(record["identity"]["security_id"] is None for record in records))
        self.assertTrue(all(record["identity"]["issuer_id"] == "provider-issuer-123" for record in records))
        self.assertFalse(report["current_universe_usable_coverage_certified"])

    def test_eodhd_explicit_security_identity_survives_all_periods_and_metrics(self):
        payload = eod_payload()
        for section in payload["Earnings"]["Trend"].values():
            for item in section.values():
                item.update(issuer_id="provider-issuer-123", security_id="provider-security-456",
                            accounting_basis="ADJUSTED", currency="USD", share_or_ADR_unit="PER_SHARE")
        transport = Transport(Response({"apiRequests": 0, "dailyRateLimit": 20,
                                        "apiRequestsDate": None}), Response(payload))
        report, rows = probe.run_probe("eodhd", ["AAPL"], max_http=2, api_units=10,
            env=ENV, transport=transport, now=lambda: NOW)
        records = json.loads(rows[0]["consensus_observations_json"])
        self.assertEqual(len(records), 4)
        self.assertEqual({record["identity"]["metric"] for record in records}, {"EPS", "REVENUE"})
        self.assertEqual({record["identity"]["period_type"] for record in records}, {"ANNUAL", "QUARTERLY"})
        self.assertTrue(all(record["identity"]["security_id"] == "provider-security-456" for record in records))
        self.assertEqual(report["results"][0]["records_with_verified_identity"], 4)
        self.assertEqual(rows[0]["identity_status"], "VERIFIED")
        self.assertEqual(len(transport.calls), 2)
        self.assertFalse(report["current_universe_usable_coverage_certified"])

    def test_eodhd_routes_new_secret_to_usage_and_fundamentals_only(self):
        transport = Transport(Response({"apiRequests": 0, "dailyRateLimit": 20,
                              "apiRequestsDate": None, "name": EODKEY, "inviteToken": EODKEY}), Response(eod_payload()))
        report, rows = probe.run_probe("eodhd", ["AAPL"], max_http=2, api_units=10,
            env=ENV, transport=transport, now=lambda: NOW)
        self.assertEqual(report["status"], "SAMPLE_PROBED")
        self.assertEqual((report["http_requests_attempted"], report["api_units_reserved_upper_bound"]), (2, 10))
        self.assertEqual(transport.calls[1][1]["params"]["api_token"], EODKEY)
        self.assertEqual(report["results"][0]["eps_rows_with_value"], 2)
        self.assertEqual(rows[0]["identity_status"], "UNKNOWN_IDENTITY")
        self.assertNotIn(EODKEY, json.dumps(report))

    def test_eodhd_annual_quarterly_collision_preserved_without_actual_substitution(self):
        eps, rev = probe.eodhd_payloads(eod_payload(), "AAPL")
        self.assertEqual([r["period_type"] for r in eps["data"]], ["ANNUAL", "QUARTERLY"])
        self.assertEqual([r["avg"] for r in eps["data"]], [0, 1])
        self.assertIsNone(rev["data"][1]["avg"])
        self.assertTrue(all(row["accounting_basis"] is None for row in eps["data"]))

    def test_documented_string_or_mixed_eodhd_counters_reach_estimate_endpoint(self):
        for used, limit in (("0", "20"), (0, "20"), ("0", 20), ("000", "020")):
            with self.subTest(used=used, limit=limit):
                transport = Transport(Response({"apiRequests": used, "dailyRateLimit": limit,
                                                "apiRequestsDate": None}), Response(eod_payload()))
                report, rows = probe.run_probe("eodhd", ["AAPL"], max_http=2, api_units=10,
                    env=ENV, transport=transport, now=lambda: NOW)
                self.assertEqual(report["status"], "SAMPLE_PROBED")
                self.assertEqual(report["eodhd_daily_quota_lower_bound"], 20)
                self.assertEqual((len(transport.calls), len(rows)), (2, 1))
                self.assertEqual(report["api_units_reserved_upper_bound"], 10)
        previous = {"apiRequests": "5", "dailyRateLimit": "20", "apiRequestsDate": "2026-10-03"}
        self.assertEqual(probe.eodhd_daily_lower_bound(previous, NOW, NOW), 15)

    def test_invalid_eodhd_counter_strings_never_reach_data_endpoint(self):
        for invalid in (True, None, 20.0, "+20", "-20", "20.0", " 20", "20 ",
                        "2e1", "", "twenty", "٢٠", "100000001", "9" * 1000):
            with self.subTest(invalid=repr(invalid)[:40]):
                transport = Transport(Response({"apiRequests": "0", "dailyRateLimit": invalid,
                                                "apiRequestsDate": None}))
                report, rows = probe.run_probe("eodhd", ["AAPL"], max_http=2, api_units=10,
                    env=ENV, transport=transport, now=lambda: NOW)
                self.assertEqual(report["status"], "UNVERIFIED_EODHD_QUOTA")
                self.assertEqual(len(transport.calls), 1)
                self.assertEqual(report["api_units_reserved_upper_bound"], 0)
                self.assertEqual(rows, [])

    def test_eodhd_never_spends_bonus_or_more_than_verified_lower_bound(self):
        for quota in ({"apiRequests": 15, "dailyRateLimit": 20, "apiRequestsDate": "2026-10-04", "extraLimit": 500},
                      {"apiRequests": 15, "dailyRateLimit": 20, "apiRequestsDate": "2026-10-03"}):
            transport = Transport(Response(quota))
            report, _ = probe.run_probe("eodhd", ["AAPL"], max_http=2, api_units=10,
                env=ENV, transport=transport, now=lambda: NOW)
            self.assertEqual(report["status"], "API_UNIT_BUDGET_EXCEEDS_DAILY_LOWER_BOUND")
            self.assertEqual(len(transport.calls), 1)
            self.assertEqual(report["api_units_reserved_upper_bound"], 0)

    def test_eodhd_403_not_retried(self):
        transport = Transport(Response({"apiRequests": 0, "dailyRateLimit": 20, "apiRequestsDate": None}), Response({}, 403))
        report, _ = probe.run_probe("eodhd", ["AAPL"], max_http=2, api_units=10,
            env=ENV, transport=transport, now=lambda: NOW)
        self.assertEqual(report["status"], "PROVIDER_HTTP_REJECTED")
        self.assertEqual(report["http_status"], 403)
        self.assertEqual(len(transport.calls), 2)

    def test_wrong_symbol_flat_v1_and_conflicting_period_rejected(self):
        payload = eod_payload()
        payload["General"]["Code"] = "MSFT"
        with self.assertRaises(probe.ProbeBlocked): probe.eodhd_payloads(payload, "AAPL")
        payload = eod_payload()
        payload["Earnings"]["Trend"] = {"2027-09-30": {"earningsEstimateAvg": 9}}
        with self.assertRaises(probe.ProbeBlocked): probe.eodhd_payloads(payload, "AAPL")
        payload = eod_payload()
        payload["Earnings"]["Trend"]["Annual"]["2027-09-30"]["date"] = "2027-12-31"
        with self.assertRaises(probe.ProbeBlocked): probe.eodhd_payloads(payload, "AAPL")

    def test_unverified_quota_types_dates_and_midnight_fail_closed(self):
        for data in ({"apiRequests": True, "dailyRateLimit": 20},
                     {"apiRequests": 0, "dailyRateLimit": 20, "apiRequestsDate": "2026-10-05"},
                     {"apiRequests": 1, "dailyRateLimit": 20, "apiRequestsDate": None}):
            with self.assertRaises(probe.ProbeBlocked): probe.eodhd_daily_lower_bound(data, NOW, NOW)
        later = datetime(2026, 10, 5, 0, 0, tzinfo=timezone.utc)
        with self.assertRaises(probe.ProbeBlocked): probe.eodhd_daily_lower_bound({}, NOW, later)

    def test_cli_rejects_operational_output_before_fetch(self):
        argv = ["probe", "--provider", "fmp2", "--output", str(probe.ROOT / "data_pit" / "summary.json")]
        with patch.object(sys, "argv", argv), patch.object(probe, "run_probe") as fetch, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(probe.main(), 2)
            fetch.assert_not_called()

    def test_cli_replaces_hardlinked_report_without_mutating_operational_inode(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            operational = root / "data_pit" / "accepted.json"
            operational.parent.mkdir()
            original = b'{"accepted": "preserve"}\n'
            operational.write_bytes(original)
            output = root / "outputs" / "earnings_estimate_source_probe" / "report.json"
            output.parent.mkdir(parents=True)
            os.link(operational, output)
            transport = Transport()
            argv = ["probe", "--provider", "fmp2", "--output", str(output)]
            with patch.object(probe, "ROOT", root), patch.object(sys, "argv", argv), \
                 patch.dict(os.environ, {}, clear=True), patch.object(probe.requests, "Session", return_value=transport), \
                 contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(probe.main(), 2)
            self.assertEqual(operational.read_bytes(), original)
            self.assertEqual(json.loads(output.read_text())["status"], "MISSING_SELECTED_SECRET")
            self.assertFalse(os.path.samefile(operational, output))
            self.assertEqual(transport.calls, [])
            self.assertEqual(list(output.parent.glob(".estimate_probe_*.json")), [])

    def test_ambiguous_or_duplicate_symbols_not_guessed(self):
        for symbols in ("AAPL,AAPL", "BRK.B", "005930", "AAPL.US", "", "AAPL,"):
            with self.assertRaises(probe.ProbeBlocked): probe.ticker_list(symbols)

    def test_workflow_manual_exact_head_and_operational_isolation(self):
        source = (probe.ROOT / ".github/workflows/earnings_estimate_source_probe.yml").read_text(encoding="utf-8")
        config = yaml.load(source, Loader=yaml.BaseLoader)
        existing = yaml.load((probe.ROOT / ".github/workflows/earnings_estimates_daily.yml").read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
        self.assertEqual(set(config["on"]), {"workflow_dispatch"})
        self.assertEqual(config["permissions"], {"contents": "read"})
        self.assertEqual(config["concurrency"]["group"], existing["concurrency"]["group"])
        self.assertEqual(config["on"]["workflow_dispatch"]["inputs"]["verified_api_units"]["default"], "0")
        self.assertNotIn("if", config["jobs"]["probe"])
        steps = config["jobs"]["probe"]["steps"]
        self.assertEqual(steps[0]["name"], "Verify approved repository ref and exact head")
        self.assertEqual(steps[0]["env"], {"PROBE_EXPECTED_HEAD": "${{ inputs.expected_head }}"})
        self.assertFalse(any("secrets." in str(value) for value in steps[0]["env"].values()))
        call = next(step for step in steps if step.get("name") == "Probe selected estimate source")
        self.assertEqual({name for name in call["env"] if name.startswith(("FMP_", "EODHD_"))}, set(probe.KEY_NAMES.values()))
        self.assertNotIn("ALPHAVANTAGE", source)
        self.assertNotIn("RCLONE", source)
        self.assertNotIn("GOOGLE_SERVICE_ACCOUNT", source)
        self.assertIn("outputs/earnings_estimate_source_probe/report.json", steps[-1]["with"]["path"])


    def test_workflow_head_guard_rejects_mismatches_before_credentials(self):
        import shutil
        import subprocess
        config = yaml.load((probe.ROOT / ".github/workflows/earnings_estimate_source_probe.yml").read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
        self.assertNotIn("if", config["jobs"]["probe"])
        step = config["jobs"]["probe"]["steps"][0]
        self.assertEqual(step.get("shell"), "bash")
        git_bash = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Git/bin/bash.exe"
        bash = str(git_bash) if os.name == "nt" and git_bash.is_file() else shutil.which("bash")
        self.assertIsNotNone(bash, "The workflow's actual bash guard requires bash")
        head = "6353c040739f0113ae1af80a3ccbc0ccecceecb5"
        valid = {"GITHUB_REPOSITORY": "wscha231/r1000-quant-engine", "GITHUB_REF": "refs/heads/master", "GITHUB_SHA": head, "PROBE_EXPECTED_HEAD": head}
        cases = [{}, {"GITHUB_REPOSITORY": "other/r1000-quant-engine"}, {"GITHUB_REF": "refs/heads/feature"}, {"GITHUB_REF": "refs/tags/master"}, {"GITHUB_SHA": "0" * 40}, {"PROBE_EXPECTED_HEAD": "f" * 40}, {"PROBE_EXPECTED_HEAD": ""}, {"PROBE_EXPECTED_HEAD": "$(exit 0)"}]
        for delta in cases:
            with self.subTest(delta=delta), tempfile.TemporaryDirectory() as directory:
                env = {k: v for k, v in os.environ.items() if k not in probe.KEY_NAMES.values()}
                env.update(valid, **delta)
                result = subprocess.run([bash, "--noprofile", "--norc", "-c", step["run"]], cwd=directory, env=env, capture_output=True, timeout=10)
                if delta:
                    self.assertNotEqual(result.returncode, 0)
                else:
                    self.assertEqual(result.returncode, 0)
                self.assertEqual(list(Path(directory).iterdir()), [])

    def test_workflow_exports_only_selected_provider_credential(self):
        import re
        config = yaml.load((probe.ROOT / ".github/workflows/earnings_estimate_source_probe.yml").read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
        steps = config["jobs"]["probe"]["steps"]
        call = next(step for step in steps if step.get("name") == "Probe selected estimate source")
        secrets = {name: "fixture-only-" + name for name in probe.KEY_NAMES.values()}
        # This bounded evaluator checks the documented &&/|| expression form;
        # it is an offline regression, not a GitHub runner/credential dispatch.
        pattern = re.compile(r"\$\{\{ inputs\.provider == '([a-z0-9]+)' && secrets\.([A-Z0-9_]+) \|\| '' \}\}")
        expressions = {name: value for name, value in call["env"].items() if name in probe.KEY_NAMES.values()}
        self.assertEqual(set(expressions), set(probe.KEY_NAMES.values()))
        parsed = {}
        for name, expression in expressions.items():
            match = pattern.fullmatch(expression)
            self.assertIsNotNone(match, "An unconditioned credential is available to every provider")
            selected, secret = match.groups()
            self.assertIn(selected, probe.KEY_NAMES)
            self.assertEqual(secret, probe.KEY_NAMES[selected])
            parsed[name] = (selected, secret)
        for selected in (*probe.KEY_NAMES, "unknown", ""):
            with self.subTest(provider=selected):
                exported = {name: secrets[secret] if selected.lower() == provider else "" for name, (provider, secret) in parsed.items()}
                nonempty = {name: value for name, value in exported.items() if value}
                expected = {} if selected not in probe.KEY_NAMES else {probe.KEY_NAMES[selected]: secrets[probe.KEY_NAMES[selected]]}
                self.assertEqual(nonempty, expected)

    def test_empty_responses_are_not_reported_as_estimate_success(self):
        transport = Transport(Response([]))
        report, _ = self.run_fmp(transport)
        self.assertEqual(report["status"], "NO_ESTIMATE_SAMPLE_CONFIRMED")
        self.assertEqual(report["securities_with_observed_eps"], 0)
        self.assertEqual(report["securities_with_observed_revenue"], 0)
        self.assertFalse(report["current_universe_usable_coverage_certified"])

    def test_eodhd_usage_consumes_aggregate_http_cap_before_data(self):
        transport = Transport(Response({"apiRequests": 0, "dailyRateLimit": 20, "apiRequestsDate": None}))
        report, _ = probe.run_probe("eodhd", ["AAPL"], max_http=1, api_units=10,
            env=ENV, transport=transport, now=lambda: NOW)
        self.assertEqual(report["status"], "REQUEST_BUDGET_EXHAUSTED")
        self.assertEqual(report["http_requests_attempted"], 1)
        self.assertEqual(report["api_units_reserved_upper_bound"], 0)
        self.assertEqual(len(transport.calls), 1)

    def test_fmp_wrong_or_missing_symbol_cannot_be_attributed_to_requested_security(self):
        for data, expected in (([dict(FMP[0], symbol="MSFT")], "PROVIDER_SECURITY_MISMATCH"),
                               ([{"date": "2027-09-30", "epsAvg": 9}], "PROVIDER_SECURITY_MISMATCH"),
                               ({"Error Message": KEY2}, "INVALID_PROVIDER_SCHEMA")):
            transport = Transport(Response(data))
            report, rows = self.run_fmp(transport)
            self.assertEqual(report["status"], expected)
            self.assertEqual(rows, [])
            self.assertEqual(report["securities_with_observed_eps"], 0)
            self.assertNotIn(KEY2, json.dumps(report))

    def test_explicit_provider_identity_is_preserved_without_fabricating_missing_fields(self):
        payload = eod_payload()
        item = payload["Earnings"]["Trend"]["Annual"]["2027-09-30"]
        item.update(issuer_id="provider-issuer-123", accounting_basis="ADJUSTED", currency="USD", share_or_ADR_unit="PER_SHARE")
        eps, _ = probe.eodhd_payloads(payload, "AAPL")
        self.assertEqual(eps["data"][0]["accounting_basis"], "ADJUSTED")
        self.assertEqual(eps["data"][0]["currency"], "USD")
        self.assertIsNone(eps["data"][1]["accounting_basis"])


    def test_daily_workflow_exports_only_effective_fmp_account(self):
        import re
        config = yaml.load((probe.ROOT / ".github/workflows/earnings_estimates_daily.yml").read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
        call = next(step for job in config["jobs"].values() for step in job["steps"] if step.get("name") == "Collect forward-only estimate archive")
        names = ("FMP_API_KEY", "FMP_API_KEY2")
        expressions = {name: call["env"][name] for name in names}
        self.assertEqual(call["env"]["FMP_KEY_NAME"], "${{ github.event.inputs.fmp_key_name || 'FMP_API_KEY' }}")
        # Restricted offline evaluation of the exact Actions expression forms.
        # Fixture credentials only; this does not exercise a hosted runner.
        direct = re.compile(r"\$\{\{ secrets\.([A-Z0-9_]+) \}\}")
        conditional = re.compile(r"\$\{\{ \(github\.event\.inputs\.fmp_key_name \|\| 'FMP_API_KEY'\) == '(FMP_API_KEY2?)' && secrets\.([A-Z0-9_]+) \|\| '' \}\}")
        parsed = {}
        for name, expression in expressions.items():
            match = conditional.fullmatch(expression)
            if match:
                selected, secret = match.groups()
                self.assertEqual(secret, name)
                self.assertEqual(selected, name)
                parsed[name] = (selected, secret)
            else:
                match = direct.fullmatch(expression)
                self.assertIsNotNone(match, "Unsupported credential expression requires reviewer verification")
                parsed[name] = (None, match.group(1))
        complete = {name: "fixture-only-" + name for name in names}
        variants = [complete]
        for absent in names:
            variants.extend(({name: value for name, value in complete.items() if name != absent}, {**complete, absent: ""}))
        for supplied in (None, "", *names, "invalid"):
            effective = supplied or "FMP_API_KEY"
            for fixture in variants:
                with self.subTest(input=supplied, present=[name for name, value in fixture.items() if value]):
                    exported = {name: fixture.get(secret, "") if selected is None or selected.lower() == effective.lower() else "" for name, (selected, secret) in parsed.items()}
                    nonempty = {name: value for name, value in exported.items() if value}
                    expected = {effective: fixture[effective]} if effective in fixture and fixture[effective] else {}
                    self.assertEqual(nonempty, expected)

    def test_existing_collector_cli_explicit_secondary_and_unchanged_default(self):
        for argv, expected in ((["collector"], KEY1),
                               (["collector", "--fmp-key-name", "FMP_API_KEY2"], KEY2)):
            with patch.dict(os.environ, ENV, clear=True), patch.object(sys, "argv", argv):
                self.assertEqual(probe.collector.parse_args().fmp_api_key, expected)

    def test_existing_collector_cli_missing_secondary_does_not_pool_or_fall_back(self):
        with patch.dict(os.environ, {"FMP_API_KEY": KEY1}, clear=True), \
             patch.object(sys, "argv", ["collector", "--fmp-key-name", "FMP_API_KEY2"]):
            self.assertEqual(probe.collector.parse_args().fmp_api_key, "")

    def test_existing_collector_cli_explicit_override_and_workflow_wiring(self):
        with patch.dict(os.environ, ENV, clear=True), \
             patch.object(sys, "argv", ["collector", "--fmp-key-name", "FMP_API_KEY2", "--fmp-api-key", KEY1]):
            self.assertEqual(probe.collector.parse_args().fmp_api_key, KEY1)
        config = yaml.load((probe.ROOT / ".github/workflows/earnings_estimates_daily.yml").read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
        selected = config["on"]["workflow_dispatch"]["inputs"]["fmp_key_name"]
        self.assertEqual(selected["default"], "FMP_API_KEY")
        self.assertEqual(selected["options"], ["FMP_API_KEY", "FMP_API_KEY2"])
        collection = next(step for job in config["jobs"].values() for step in job["steps"]
                          if step.get("name") == "Collect forward-only estimate archive")
        self.assertEqual(collection["env"]["FMP_API_KEY2"], "${{ (github.event.inputs.fmp_key_name || 'FMP_API_KEY') == 'FMP_API_KEY2' && secrets.FMP_API_KEY2 || '' }}")
        self.assertIn('--fmp-key-name "$FMP_KEY_NAME"', collection["run"])


if __name__ == "__main__":
    unittest.main()
