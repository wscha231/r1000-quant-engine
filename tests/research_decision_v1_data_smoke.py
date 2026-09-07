"""Counterexamples for isolated research input admission."""
import copy
import os
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from research_decision_v1_fixture import bundle, rehash
from tools.research_decision_v1.data import export_market, total_return_series, envelope_errors
from tools.research_decision_v1.io import immutable_json, read_json
from tools.research_decision_v1.platform_io import input_descriptor


class DataContractTests(unittest.TestCase):
    def result(self, b):
        return export_market(b, b["market"])["securities"][0]

    def test_valid_and_deterministic(self):
        b = bundle()
        self.assertEqual(export_market(b, "US"), export_market(copy.deepcopy(b), "US"))
        r = self.result(b)
        self.assertTrue(r["data_quality_pass"])
        self.assertEqual(r["discovery"]["rs"]["240"]["value"], 0.)

    def test_future_stale_identity_currency_period_hash(self):
        mutations = [
            lambda s: s["blocks"]["financials"].update(public_available_at="2026-09-08T00:00:00Z"),
            lambda s: s["blocks"]["price"]["payload"]["bars"].pop(),
            lambda s: s["blocks"]["financials"].update(security_id="US:OTHER"),
            lambda s: s["blocks"]["financials"].update(currency="KRW"),
            lambda s: s["blocks"]["financials"]["payload"]["period"].update(end="2024-01-01"),
            lambda s: s["blocks"]["financials"].update(data_hash="0" * 64),
        ]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                b = bundle(); mutate(b["securities"][0])
                self.assertFalse(self.result(b)["data_quality_pass"])

    def test_optional_failure_no_event_and_zero(self):
        b = bundle(); s = b["securities"][0]
        s["optional"] = {"estimates": {"status": "provider_error", "http": 403},
                         "form4": {"status": "no_event"}, "news": {"status": "missing"}}
        s["blocks"]["financials"]["payload"]["ttm"]["net_debt"] = 0.
        rehash(s["blocks"]["financials"])
        r = self.result(b)
        self.assertTrue(r["data_quality_pass"])
        self.assertEqual(r["optional"]["estimates"]["status"], "provider_error")
        s["blocks"]["financials"]["payload"]["ttm"]["net_debt"] = None
        rehash(s["blocks"]["financials"])
        self.assertFalse(self.result(b)["data_quality_pass"])

    def test_nonranking_forbidden(self):
        for field in ("nonranking_score", "score", "current_engine_score", "ownership_score"):
            b = bundle(); b["securities"][0][field] = 999
            with self.assertRaisesRegex(ValueError, "NONRANKING"): export_market(b, "US")
        b = bundle(); b["securities"][0]["status"] = "NONRANKING"
        with self.assertRaisesRegex(ValueError, "NONRANKING"): export_market(b, "US")

    def test_legacy_rank_and_readiness_aliases_are_not_raw_inputs(self):
        for field in ("rank", "ranking_eligible", "ranking-ready", "rankEligible", "readiness"):
            b = bundle(); b["securities"][0][field] = 1
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "NONRANKING"):
                export_market(b, "US")
        for value in ("RANKING_READY", "ranking-eligible", "RANKABLE"):
            b = bundle(); b["securities"][0]["status"] = value
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "NONRANKING"):
                export_market(b, "US")

    def test_basic_authorization_values_cannot_reach_blocked_snapshots(self):
        # Explicit dummy credentials, never a provider response or real secret.
        from tools.research_decision_v1.data import validate_persistable_sources
        validate_persistable_sources({"note": "Basic assumptions are disclosed."})
        for value in ("Basic dXNlcjpwYXNzd29yZA==", "note: basic\tdGVzdDp0ZXN0"):
            b = bundle(); b["securities"][0]["optional"] = {"provider": {"status": "missing", "note": value}}
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "credential_value"):
                export_market(b, "US")

    def test_output_parent_replacement_cannot_redirect_publication(self):
        import tools.research_decision_v1.io as io
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); parent = root / "accepted"; parent.mkdir()
            outside = root / "outside"; outside.mkdir()
            original = io.publish_staged
            def replace_parent(*args, **kwargs):
                if os.name == "nt":
                    with self.assertRaises(OSError): parent.rename(root / "moved")
                else:
                    parent.rename(root / "moved")
                    parent.symlink_to(outside, target_is_directory=True)
                return original(*args, **kwargs)
            with patch.object(io, "publish_staged", side_effect=replace_parent):
                if os.name == "nt": immutable_json(parent / "record.json", {"x": 1})
                else:
                    with self.assertRaises(ValueError): immutable_json(parent / "record.json", {"x": 1})
            self.assertEqual(list(outside.iterdir()), [])
            if os.name != "nt": self.assertEqual(list((root / "moved").iterdir()), [])

    def test_staged_leaf_replacement_cannot_publish_unverified_bytes(self):
        import tools.research_decision_v1.io as io
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); target = root / "record.json"; original = io.publish_staged
            def replace_leaf(temporary, path, **kwargs):
                if os.name == "nt":
                    with self.assertRaises(OSError): temporary.rename(root / "moved")
                    with self.assertRaises(OSError): temporary.write_bytes(b'{"x":999}')
                else:
                    temporary.write_bytes(b'{"x":999}')
                return original(temporary, path, **kwargs)
            with patch.object(io, "publish_staged", side_effect=replace_leaf):
                immutable_json(target, {"x": 1})
            self.assertEqual(read_json(target), {"x": 1})
            if os.name == "nt": return
        # An in-place write at the final publication boundary must not change
        # the bytes selected by the retained anonymous Linux descriptor.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); target = root / "record.json"; held = {}; link = os.link
            def capture(temporary, path, **kwargs):
                held['path'] = temporary; return original(temporary, path, **kwargs)
            def replace_at_link(*args, **kwargs):
                held['path'].write_bytes(b'{"x":999}')
                return link(*args, **kwargs)
            with patch.object(io, "publish_staged", side_effect=capture), patch('tools.research_decision_v1.platform_io.os.link', side_effect=replace_at_link):
                immutable_json(target, {"x": 1})
            self.assertEqual(read_json(target), {"x": 1})

    def test_public_availability_and_official_close(self):
        for market in ("US", "KR"):
            b = bundle(market); price = b["securities"][0]["blocks"]["price"]
            price["public_available_at"] = None
            self.assertIn("price:public_available_at_unknown", self.result(b)["blockers"])
            price["public_available_at"] = "2026-09-04T00:00:00Z"
            self.assertFalse(self.result(b)["data_quality_pass"])
        b = bundle(); financials = b["securities"][0]["blocks"]["financials"]
        financials.update(published_at="2026-06-01T00:00:00Z", public_available_at="2026-06-01T00:00:00Z")
        self.assertIn("financials:period_after_published_at", self.result(b)["blockers"])

    def test_forecast_period_is_not_a_future_reported_actual(self):
        b = bundle(); security = b["securities"][0]
        block = copy.deepcopy(security["blocks"]["financials"])
        block.update(accounting_basis="RESEARCH_ASSUMPTION", report_period={"start": "2026-09-07", "end": "2027-09-07"})
        self.assertEqual(envelope_errors(block, security, b["decision_cutoff"]), [])
        block["accounting_basis"] = "US_GAAP"
        self.assertIn("period_after_published_at", envelope_errors(block, security, b["decision_cutoff"]))

    def test_benchmark_identity_actions_and_board(self):
        for market in ("US", "KR"):
            b = bundle(market); p = b["securities"][0]["blocks"]["price"]
            p["payload"]["benchmark_actions_through"] = "2020-01-01"; rehash(p)
            self.assertIn("price:benchmark_actions_stale", self.result(b)["blockers"])
            b = bundle(market); p = b["securities"][0]["blocks"]["price"]
            p["payload"]["benchmark_id"] = "OTHER"; rehash(p)
            self.assertIn("price:benchmark_identity_mismatch", self.result(b)["blockers"])
        b = bundle("KR"); b["securities"][0]["listing_board"] = "KOSDAQ"
        self.assertFalse(self.result(b)["data_quality_pass"])
        p = b["securities"][0]["blocks"]["price"]; p["payload"]["benchmark_id"] = "KOSDAQ150"; rehash(p)
        self.assertTrue(self.result(b)["data_quality_pass"])

    def test_recent_financial_recency_and_continuity(self):
        for field in ("recent_quarters", "recent_annual"):
            b = bundle(); f = b["securities"][0]["blocks"]["financials"]
            for row in f["payload"][field]:
                row["start"] = row["start"].replace("2026", "2010").replace("2025", "2009")
                row["end"] = row["end"].replace("2026", "2010").replace("2025", "2009")
            rehash(f); self.assertFalse(self.result(b)["data_quality_pass"])
        b = bundle(); f = b["securities"][0]["blocks"]["financials"]
        f["payload"]["recent_quarters"].append({"start": "2025-10-01", "end": "2025-12-31", "revenue": 2000.})
        rehash(f); self.assertIn("recent_quarters_gap_or_overlap", self.result(b)["blockers"])

    def test_unsafe_sources_never_reach_blocked_snapshot(self):
        sources = ("https://example.org/a?apikey=dummy", "https://example.org/a#access_token=dummy",
                   "https://example.org/token/dummy", "https://user:dummy@example.org/a")
        for source in sources:
            b = bundle(); b["securities"][0]["blocks"]["price"] = {"status": "missing", "source": source}
            with self.assertRaises(ValueError): export_market(b, "US")
        b = bundle(); b["data_kind"] = "REAL"
        with self.assertRaisesRegex(ValueError, "synthetic_source"): export_market(b, "US")

    def test_common_credential_aliases_never_persist(self):
        for key in ("token", "session_token", "auth_token", "client_secret", "private_key", "clientSecret", "authorization", "cookie",
                    "passwd", "pwd", "dbPwd", "db_passwd", "pswd", "psw", "pword", "passphrase",
                    "passcode", "pass_word", "user_pass", "pass", "userPass", "passCode", "pass_key", "passhash",
                    "password1", "password2", "pass123", "userPassword42", "pass_123", "pass\uFF11",
                    "token1", "secret42", "apiKey2", "authorization2", "cookies2", "privateKey99", "jwt", "bearer", "sessionid", "sessionId", "access_key", "clientKey", "signing_key", "sid", "session", "ＪＷＴ", "session-id", "session.id", "session id", "session::id", "session__id", "session－id", "sessionUuid", "sessionGUID"):


            b = bundle(); b["securities"][0]["optional"] = {"provider": {"status": "missing", key: "dummy"}}
            with self.assertRaisesRegex(ValueError, "credential_field"): export_market(b, "US")

    def test_real_provenance_rejects_nonpublic_literal_and_local_hosts(self):
        from tools.research_decision_v1.data import validate_persistable_sources
        for host in ("127.0.0.1", "[::1]", "[::ffff:127.0.0.1]", "10.2.3.4", "169.254.169.254", "100.64.0.1",
                     "192.0.2.1", "127.1", "2130706433", "internal", "data.local", "data.internal", "localhost.", "0x7f.0.0.1", "0x7f.1", "127.0x0.0.1", "０x７f.１", "%31%32%37.1", "8.8.8.8", "router.home.arpa", "resolver.arpa", "service.arpa", "hidden.onion", "name.alt", "router.lan"):


            with self.assertRaises(ValueError): validate_persistable_sources({"source": "https://"+host+"/report"}, real=True)
        validate_persistable_sources({"source": "https://www.sec.gov/Archives/report"}, real=True)

    def test_opaque_bearer_and_jwt_values_do_not_persist_in_notes(self):
        for value in ("Bearer abcdefghijklmnop", "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjMifQ.signature"):
            b = bundle(); b["securities"][0]["optional"] = {"provider": {"status": "missing", "note": value}}
            with self.assertRaisesRegex(ValueError, "credential_value"): export_market(b, "US")

    def test_reporting_timezone_uses_pinned_package_not_system_lookup(self):
        from tools.research_decision_v1.data import reporting_zone
        from zoneinfo import ZoneInfo
        with patch("tools.research_decision_v1.data.ZoneInfo") as zone:
            zone.side_effect = AssertionError("host lookup forbidden")
            zone.from_file.side_effect = ZoneInfo.from_file
            self.assertEqual(reporting_zone("America/New_York").key, "America/New_York")
            self.assertFalse(zone.called)
            self.assertTrue(zone.from_file.called)
        with patch("tzdata.__version__", "unfrozen"):
            with self.assertRaisesRegex(ValueError, "version_mismatch"): reporting_zone("America/New_York")
        with self.assertRaises(ValueError): reporting_zone("../UTC")

    def test_export_carries_admission_source_fingerprint(self):
        import hashlib
        from tools.research_decision_v1 import data
        result = export_market(bundle(), "US")
        expected = hashlib.sha256(Path(data.__file__).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
        self.assertEqual(result["admission_source"]["sha256"], expected)
        changed = copy.deepcopy(result); changed["admission_source"]["sha256"] = "0"*64
        from tools.research_decision_v1.data import digest
        changed.pop("export_hash")
        self.assertNotEqual(digest(changed), result["export_hash"])

    def test_financial_timezone_cannot_move_the_market_boundary(self):
        for market in ("US", "KR"):
            b = bundle(market); security = b["securities"][0]; block = security["blocks"]["financials"]
            block["reporting_timezone"] = "Pacific/Kiritimati"
            for field in ("published_at", "public_available_at", "first_seen_at", "ingested_at"): block[field] = "2026-06-30T11:00:00Z"
            self.assertIn("reporting_timezone_market_mismatch", envelope_errors(block, security, b["decision_cutoff"]))

    def test_history_boundaries_reject_datetime_truncation(self):
        for field in ("recent_quarters", "recent_annual"):
            b = bundle(); block = b["securities"][0]["blocks"]["financials"]
            block["payload"][field][0]["start"] += "T23:59:59"; rehash(block)
            self.assertIn("financials_invalid_or_missing", self.result(b)["blockers"])

    def test_publication_cannot_follow_claimed_public_availability(self):
        b = bundle(); security = b["securities"][0]; block = security["blocks"]["financials"]
        block.update(published_at="2026-08-02T12:00:00Z", public_available_at="2026-08-01T12:00:00Z")
        self.assertIn("publication_after_public_availability", envelope_errors(block, security, b["decision_cutoff"]))
        block["published_at"] = None
        self.assertNotIn("publication_after_public_availability", envelope_errors(block, security, b["decision_cutoff"]))

    def test_source_url_ports_are_validated(self):
        from tools.research_decision_v1.data import validate_persistable_sources
        for port in ("bad", "99999", "-1", "0"):
            with self.assertRaisesRegex(ValueError, "invalid_source_url"):
                validate_persistable_sources({"source":"https://www.sec.gov:"+port+"/report"}, real=True)
        validate_persistable_sources({"source":"https://www.sec.gov:443/report"}, real=True)

    def test_benchmark_volume_is_unused_and_security_volume_is_required(self):
        for market in ("US", "KR"):
            b = bundle(market); block = b["securities"][0]["blocks"]["price"]
            block["payload"]["benchmark_bars"] = copy.deepcopy(block["payload"]["benchmark_bars"])
            for bar in block["payload"]["benchmark_bars"]: del bar["volume"]
            rehash(block); self.assertTrue(self.result(b)["data_quality_pass"])
            del block["payload"]["bars"][-1]["volume"]; rehash(block)
            self.assertFalse(self.result(b)["data_quality_pass"])

    def test_fcf_identity_does_not_allow_magnitude_scaled_error(self):
        b = bundle(); block = b["securities"][0]["blocks"]["financials"]
        block["payload"]["ttm"].update(operating_cash_flow=1e12, capex=500000., fcf=1e12); rehash(block)
        self.assertIn("fcf_identity_mismatch", self.result(b)["blockers"])
        block["payload"]["ttm"]["fcf"] = 1e12-500000.; rehash(block)
        self.assertNotIn("fcf_identity_mismatch", self.result(b)["blockers"])

    def test_reporting_day_completion_in_explicit_timezone(self):
        for market, before, complete in (("US", "2026-07-01T03:59:59Z", "2026-07-01T04:00:00Z"),
                                         ("KR", "2026-06-30T14:59:59Z", "2026-06-30T15:00:00Z")):
            b = bundle(market); security = b["securities"][0]; block = security["blocks"]["financials"]
            for field in ("published_at", "public_available_at", "first_seen_at", "ingested_at"): block[field] = before
            self.assertIn("period_incomplete_at_public_available_at", envelope_errors(block, security, b["decision_cutoff"]))
            for field in ("published_at", "public_available_at", "first_seen_at", "ingested_at"): block[field] = complete
            self.assertEqual(envelope_errors(block, security, b["decision_cutoff"]), [])
            del block["reporting_timezone"]
            self.assertIn("reporting_timezone_required", envelope_errors(block, security, b["decision_cutoff"]))

    def test_real_cannot_relabel_synthetic_feed(self):
        import json
        b = json.loads(json.dumps(bundle()).replace("https://example.org/synthetic", "https://www.sec.gov/Archives/filing"))
        b["data_kind"] = "REAL"
        with self.assertRaisesRegex(ValueError, "synthetic_feed"): export_market(b, "US")

    def test_price_period_matches_security_bars(self):
        b = bundle(); block = b["securities"][0]["blocks"]["price"]
        block["report_period"] = {"start": "2020-01-01", "end": "2020-01-31"}
        self.assertIn("price:report_period_bar_range_mismatch", self.result(b)["blockers"])

    def test_descriptor_read_parent_symlink_size_and_leaf_replacement(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); p = root / "record.json"; p.write_text('{"x":1}')
            alias = root / "alias"; alias.symlink_to(root, target_is_directory=True)
            with self.assertRaises(ValueError): read_json(alias/"record.json")
            huge = root / "huge.json"
            with huge.open("wb") as handle: handle.truncate(32_000_001)
            with self.assertRaises(ValueError): read_json(huge)
            if os.name == "nt":
                with input_descriptor(p.absolute()) as descriptor:
                    self.assertEqual(os.read(descriptor, 100), b'{"x":1}')
                    with self.assertRaises(OSError): p.rename(root/"old.json")
                    with self.assertRaises(OSError): p.write_text('{"x":2}')
                p.write_text('{"x":2}')
                self.assertEqual(read_json(p), {"x": 2})
                return
            original_open = os.open
            def swap_after_open(path, *args, **kwargs):
                fd = original_open(path, *args, **kwargs)
                if path == "record.json":
                    p.rename(root/"old.json"); p.write_text('{"x":2}')
                return fd
            with patch("tools.research_decision_v1.io.os.open", side_effect=swap_after_open):
                self.assertEqual(read_json(p), {"x": 1})
            self.assertEqual(read_json(p), {"x": 2})

    def test_uri_scheme_case_credentials_and_units(self):
        for uri in ("ftp://user:dummy@example.org/file", "HTTPS://user:dummy@example.org/file", "FiLe:///private/file"):
            b = bundle(); b["securities"][0]["optional"] = {"provider": {"status": "missing", "detail": uri}}
            with self.assertRaises(ValueError): export_market(b, "US")
        for key, wrong_unit in (("price", "cents"), ("risk", "percent"), ("thesis", "score_units")):
            b = bundle(); b["securities"][0]["blocks"][key]["unit"] = wrong_unit
            self.assertIn(key+":unit_mismatch", self.result(b)["blockers"])
        b = bundle(); p = b["securities"][0]["blocks"]["price"]
        p["payload"]["volume_unit"] = "lots"; rehash(p)
        self.assertIn("price:volume_unit_unverified", self.result(b)["blockers"])

    def test_pre_split_dividends_share_the_adjusted_price_basis(self):
        raw = [{"close": 100., "dividend": 0., "split_ratio": 1.},
               {"close": 99., "dividend": 1., "split_ratio": 1.},
               {"close": 49.5, "dividend": 0., "split_ratio": 2.}]
        adjusted = copy.deepcopy(raw)
        for bar in adjusted[:2]: bar["close"] /= 2.
        self.assertEqual(total_return_series(raw, "raw_unadjusted"), [1., 1., 1.])
        self.assertEqual(total_return_series(adjusted, "split_adjusted"), [1., 1., 1.])
        # The same identity holds for reverse splits and an earlier dividend.
        raw[-1].update(close=198., split_ratio=.5)
        adjusted = copy.deepcopy(raw)
        for bar in adjusted[:2]: bar["close"] *= 2.
        self.assertEqual(total_return_series(adjusted, "split_adjusted"), total_return_series(raw, "raw_unadjusted"))

    def test_valid_losses_are_distinct_from_valuation_eligibility(self):
        b = bundle(); f = b["securities"][0]["blocks"]["financials"]
        f["payload"]["ttm"].update(net_income=-1., ebitda=-1.); rehash(f)
        row = self.result(b)
        self.assertTrue(row["data_quality_pass"])
        self.assertEqual(row["valuation_method_eligibility"], {"PE": False, "EV_EBITDA": False})

    def test_kr_benchmark_must_be_total_return_without_double_distribution(self):
        b = bundle("KR"); p = b["securities"][0]["blocks"]["price"]
        p["payload"]["benchmark_return_kind"] = "PRICE_ONLY"; rehash(p)
        self.assertIn("price:benchmark_return_kind_mismatch", self.result(b)["blockers"])
        p["payload"]["benchmark_return_kind"] = "TOTAL_RETURN_INDEX"
        p["payload"]["benchmark_bars"] = copy.deepcopy(p["payload"]["benchmark_bars"])
        p["payload"]["benchmark_bars"][-1]["dividend"] = 1.; rehash(p)
        self.assertIn("price:total_return_index_action_double_count", self.result(b)["blockers"])

    def test_atomic_write_failure_can_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory) / "record.json"
            with patch("tools.research_decision_v1.io.os.fsync", side_effect=OSError("interrupted")):
                with self.assertRaises(OSError): immutable_json(p, {"x": 1})
            self.assertFalse(p.exists())
            self.assertEqual(list(Path(directory).iterdir()), [])
            immutable_json(p, {"x": 1})
            self.assertEqual(read_json(p), {"x": 1})

    def test_short_history_and_split_dividend(self):
        b = bundle(); p = b["securities"][0]["blocks"]["price"]
        p["payload"]["bars"] = p["payload"]["bars"][-240:]
        p["payload"]["benchmark_bars"] = p["payload"]["benchmark_bars"][-240:]
        p["report_period"]["start"] = p["payload"]["bars"][0]["session"]
        rehash(p)
        self.assertEqual(self.result(b)["discovery"]["rs"]["240"]["status"], "missing")
        raw = [{"close": 100., "split_ratio": 1., "dividend": 0.},
               {"close": 49., "split_ratio": 2., "dividend": 1.}]
        self.assertEqual(total_return_series(raw, "raw_unadjusted"), [1., 1.])
        adjusted = [{"close": 50., "split_ratio": 1., "dividend": 0.},
                    {"close": 49., "split_ratio": 2., "dividend": 1.}]
        self.assertEqual(total_return_series(adjusted, "split_adjusted"), [1., 1.])

    def test_market_cutoff_and_fcf(self):
        us, kr = bundle(), bundle("KR")
        self.assertEqual(self.result(us)["required_session"], "2026-09-04")
        self.assertEqual(self.result(kr)["required_session"], "2026-09-07")
        with self.assertRaises(ValueError): export_market(kr, "US")
        b = bundle(); f = b["securities"][0]["blocks"]["financials"]
        f["payload"]["ttm"]["fcf"] += 100.; rehash(f)
        self.assertFalse(self.result(b)["data_quality_pass"])

    def test_stale_rehashed_price_and_calendar_gap(self):
        b = bundle(); p = b["securities"][0]["blocks"]["price"]
        p["payload"]["bars"] = p["payload"]["bars"][:-1]; rehash(p)
        self.assertIn("price:stale_or_future_price", self.result(b)["blockers"])
        b = bundle(); p = b["securities"][0]["blocks"]["price"]
        p["payload"]["bars"] = p["payload"]["bars"][:5] + p["payload"]["bars"][6:]; rehash(p)
        self.assertIn("price:calendar_gap_or_non_session", self.result(b)["blockers"])

    def test_immutable_conflict_json_and_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory) / "record.json"
            immutable_json(p, {"x": 0}); immutable_json(p, {"x": 0})
            with self.assertRaisesRegex(ValueError, "immutable_history_conflict"): immutable_json(p, {"x": 1})
            bad = Path(directory) / "bad.json"; bad.write_text('{"a":1,"a":2}')
            with self.assertRaisesRegex(ValueError, "duplicate_json_key"): read_json(bad)
            link = Path(directory) / "link.json"; link.symlink_to(p)
            with self.assertRaisesRegex(ValueError, "output_symlink"): immutable_json(link, {"x": 0})


if __name__ == "__main__": unittest.main()
