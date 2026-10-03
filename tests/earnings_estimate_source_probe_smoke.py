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
        self.assertNotIn(KEY2, json.dumps(report))

    def test_fmp_403_stops_without_switching_keys(self):
        transport = Transport(Response({}, 403))
        report, _ = probe.run_probe("fmp2", ["AAPL", "MSFT"], max_http=2, api_units=2,
            quota_verified_at=NOW.isoformat(), env=ENV, transport=transport, now=lambda: NOW)
        self.assertEqual(len(transport.calls), 1)
        self.assertEqual(report["http_requests_attempted"], 1)

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
        guard = config["jobs"]["probe"]["if"]
        self.assertIn("github.sha == inputs.expected_head", guard)
        self.assertIn("github.ref == 'refs/heads/master'", guard)
        self.assertIn("github.repository == 'wscha231/r1000-quant-engine'", guard)
        steps = config["jobs"]["probe"]["steps"]
        call = next(step for step in steps if step.get("name") == "Probe selected estimate source")
        self.assertEqual({name for name in call["env"] if name.startswith(("FMP_", "EODHD_"))}, set(probe.KEY_NAMES.values()))
        self.assertNotIn("ALPHAVANTAGE", source)
        self.assertNotIn("RCLONE", source)
        self.assertNotIn("GOOGLE_SERVICE_ACCOUNT", source)
        self.assertIn("outputs/earnings_estimate_source_probe/report.json", steps[-1]["with"]["path"])

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
        for data in ([dict(FMP[0], symbol="MSFT")], [{"date": "2027-09-30", "epsAvg": 9}], {"Error Message": KEY2}):
            transport = Transport(Response(data))
            report, rows = self.run_fmp(transport)
            self.assertEqual(report["status"], "NO_ESTIMATE_SAMPLE_CONFIRMED")
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
        self.assertEqual(collection["env"]["FMP_API_KEY2"], "${{ secrets.FMP_API_KEY2 }}")
        self.assertIn('--fmp-key-name "$FMP_KEY_NAME"', collection["run"])


if __name__ == "__main__":
    unittest.main()
