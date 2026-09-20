"""Synthetic byte-bound E2E and adversarial admission checks; no provider calls."""
from __future__ import annotations

import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tools import theme_etf_source_bridge as bridge
from tools import run_run287_daily_research_monitor as monitor

NOW = datetime(2026, 9, 18, 22, 30, tzinfo=timezone.utc)
SESSION = "2026-09-18"
CONTRACT = json.loads(monitor.CONTRACT.read_text())


def fixture():
    import pandas_market_calendars as mcal
    base = [f"SYN_BASE_{i:04d}" for i in range(1118)]
    stamp = "2026-09-18T21:35:00Z"
    securities = [{"security_id": sid, "issuer_id": f"issuer:{sid}", "ticker": sid,
                   "currency": "USD", "available_at": stamp, "identity_verified": True,
                   "listing_country": "US", "instrument": "ADR" if sid == "SYN_NEW" else "COMMON",
                   "exchange": "XNYS", "research_eligible": True} for sid in base + ["SYN_NEW"]]
    schedule = mcal.get_calendar("NYSE").schedule(start_date="2026-08-01", end_date=SESSION)
    prices = [{"security_id": sid, "session": str(day.date()), "total_return_index": 100 + i * factor,
               "available_at": close.isoformat()}
              for i, (day, close) in enumerate(zip(schedule.index, schedule["market_close"]))
              for sid, factor in (("SPY", .1), ("SYN_ETF", .2))]
    doc = {"document_id": "syn-doc", "available_at": stamp, "source_group": "SYNTHETIC",
           "title": "Synthetic optical capacity", "summary": "fixture only, not real research"}
    event = {"event_id": "syn-link", "security_id": "SYN_NEW", "theme_id": "SYN_OPTICS",
             "action": "LINK", "role": "ENABLER", "relevance": .8, "reviewed": True,
             "effective_at": stamp, "observed_at": stamp, "reviewed_at": stamp}
    snapshots = [{"fund_id": "SYN_ETF", "source_id": "SYNTHETIC",
                  "portfolio_scope": "PORTFOLIO", "coverage_kind": coverage,
                  "weight_unit": "PERCENT", "holdings_as_of": day,
                  "observed_at": day + "T21:00:00Z", "validated_at": day + "T21:00:00Z",
                  "expected_unique_rows": 1,
                  "rows": [{"security_id": sid, "instrument": "COMMON", "identity_verified": True,
                            "weight": "100%"}]} for day, coverage, sid in (
                      ("2026-09-17", "FULL", "SYN_NEW"), (SESSION, "TOP_ONLY", base[0]))]
    parts = {"base_universe": {"scope": "FULL_BASE_UNIVERSE", "security_ids": base, "available_at": stamp},
             "securities": securities, "prices": {"rows": prices, "basis": "TOTAL_RETURN_INDEX",
              "currency": "USD", "methodology_id": "distributions_reinvested_v1", "benchmark_id": "SPY"},
             "etf_snapshots": snapshots, "documents": [doc], "membership_events": [event]}
    run = {"id": 123, "run_attempt": 2, "head_sha": "a" * 40, "head_branch": "master",
           "head_repository": {"full_name": CONTRACT["repository"]}, "event": "schedule",
           "path": ".github/workflows/daily_operating_selection_refresh.yml",
           "status": "completed", "conclusion": "success", "created_at": "2026-09-18T21:31:00Z"}
    policy = copy.deepcopy(CONTRACT["theme_etf_bridge"])
    policy["allowed_sample_origins"] = ["SYNTHETIC_FIXTURE"]
    policy["approved_membership_reviews"] = {bridge.sha(bridge.canonical(event)): {
        "decision": "APPROVED_BUSINESS_RELATIONSHIP", "reviewer_id": "synthetic-reviewer",
        "reviewed_at": stamp, "document_hashes": {doc["document_id"]: bridge.sha(bridge.canonical(doc))}}}
    return parts, run, policy


def package(parts, run, policy, path, alter=None):
    producer = {"repository": CONTRACT["repository"], "workflow": run["path"],
                "head_sha": run["head_sha"], "run_id": run["id"], "run_attempt": run["run_attempt"]}
    files, components = {}, {}
    def add(name, obj):
        raw = bridge.canonical(obj)
        files[name] = raw
        return {"path": name, "sha256": bridge.sha(raw)}
    for role, part in parts.items():
        root = f"outputs/theme_etf_bridge/{role}"
        raw = add(root + "/raw.json", part)
        data = add(root + "/data.json", part)
        receipt = add(root + "/receipt.json", {"schema": "theme-etf-component-receipt-v1",
            "producer": producer, "role": role, "data_sha256": data["sha256"], "raw_objects": [raw],
            "status": "COLLECTED", "failures": [], "research_only": True,
            "validated_at": "2026-09-18T21:40:00Z"})
        components[role] = {"data": data, "receipt": receipt}
    bundle = {"schema": bridge.SCHEMA, "producer": producer,
              "sample_origin": "SYNTHETIC_FIXTURE",
              "decision_at": "2026-09-18T22:00:00Z", "components": components}
    bundle_name = policy["bundle_member"].format(run_id=run["id"], run_attempt=run["run_attempt"])
    add(bundle_name, bundle)
    # Existing monitor contract members, with no claim of ready engine scores.
    for key, name in CONTRACT["sources"]["operating"]["members"].items():
        name = name.format(run_id=run["id"], run_attempt=run["run_attempt"])
        files[name] = b"ticker,previous_close,latest_price_date,currency\n" if name.endswith(".csv") else b"{}\n"
    if alter:
        alter(files, bundle, bundle_name)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as out:
        for name, raw in files.items():
            out.writestr(name, raw)
    artifact = {"id": 456, "name": "daily-operating-selection-refresh-123", "expired": False,
                "digest": "sha256:" + bridge.sha(path.read_bytes()), "size_in_bytes": path.stat().st_size,
                "workflow_run": {"id": run["id"], "head_sha": run["head_sha"]}}
    return artifact


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "source.zip"
        self.parts, self.run, self.policy = fixture()

    def read(self, alter=None):
        artifact = package(self.parts, self.run, self.policy, self.path, alter)
        return bridge.read_bundle(self.path, self.run, artifact, self.policy, SESSION, NOW)

    def check_blocked(self, reason=None, alter=None):
        out = self.read(alter)
        self.assertEqual(out["status"], "BLOCKED", out.get("reason"))
        self.assertFalse(out["runtime_executed"])
        self.assertNotIn("membership_reasons", out)
        if reason:
            self.assertEqual(out["reason"], reason)
        return out

    def test_complete_synthetic_cycle_preserves_base_and_reports_every_candidate(self):
        before = copy.deepcopy(self.parts)
        out = self.read()
        self.assertEqual(out["status"], "ADMITTED_RESEARCH_ONLY", out)
        self.assertEqual(out["result"]["summary"]["universe"]["base_count"], 1118)
        inventory = out["evaluation_inventory"]
        self.assertEqual(len(inventory), 1119)
        self.assertEqual(len({r["security_id"] for r in inventory}), 1119)
        self.assertTrue(all(r["expected_return_12m"] is None for r in inventory))
        self.assertTrue(all(r["status"].startswith("BLOCKED_") for r in inventory))
        self.assertFalse(out["end_to_end_ready"])
        self.assertFalse(out["company_evaluator_executed"])
        self.assertEqual(self.parts, before)
        self.assertEqual(out["membership_policy"]["score_bonus"], 0)
        self.assertEqual(out["membership_reasons"][0]["reason_type"], "REVIEWED_THEME_RESEARCH")
        queue = out["data_queue_preview"]
        self.assertEqual(queue["schema_version"], "candidate-data-queue-v1")
        self.assertEqual({r["security_id"] for r in queue["items"]}, {r["security_id"] for r in inventory})
        self.assertTrue(all(r["state"] == "DATA_PENDING" for r in queue["items"]))
        self.assertFalse(out["safety"]["orders_allowed"])
        self.assertGreater(out["result"]["leadership"][0]["rs_log_20"], 0)
        self.assertIsNone(out["result"]["leadership"][0]["rs_log_240"])

    def test_same_bytes_replay_is_deterministic(self):
        artifact = package(self.parts, self.run, self.policy, self.path)
        before = self.path.read_bytes()
        first = bridge.read_bundle(self.path, self.run, artifact, self.policy, SESSION, NOW)
        self.assertEqual(first, bridge.read_bundle(self.path, self.run, artifact, self.policy, SESSION, NOW))
        self.assertEqual(before, self.path.read_bytes())

    def test_monitor_authentication_path_reuses_artifact_and_executes_strict_runtime(self):
        artifact = package(self.parts, self.run, self.policy, self.path)
        raw, run = self.path.read_bytes(), self.run
        class Client:
            def json(self, path):
                return {"workflow_runs": [run]} if "/workflows/" in path else {"artifacts": [artifact]}
            def archive(self, artifact_id, destination, limit):
                destination.write_bytes(raw)
                return "sha256:" + hashlib.sha256(raw).hexdigest()
        contract = copy.deepcopy(CONTRACT)
        contract["theme_etf_bridge"] = self.policy
        source = monitor.collect_source(Client(), "operating", contract["sources"]["operating"], contract,
                                        now=NOW, session=SESSION)
        self.assertEqual(source["status"], "VERIFIED_ARTIFACT", source)
        observation = bridge.observation(source, SESSION)
        self.assertTrue(observation["runtime_executed"])
        self.assertEqual(observation["requested_security_count"], 1119)
        self.assertEqual(observation["evaluated_security_count"], 0)
        # A valid optional bundle cannot reopen missing upstream prerequisites.
        market = contract["sources"]["operating"]["members"]["market"]
        artifact = package(self.parts, self.run, self.policy, self.path,
                           lambda files, bundle, name: files.pop(market))
        raw = self.path.read_bytes()
        failed = monitor.collect_source(Client(), "operating", contract["sources"]["operating"], contract,
                                        now=NOW, session=SESSION)
        self.assertEqual(failed["status"], "MISSING_CONTRACT_MEMBERS")
        self.assertFalse(failed["data"]["theme_etf_bridge"]["runtime_executed"])

    def test_reviewed_boolean_without_external_pin_cannot_add_security(self):
        self.policy["approved_membership_reviews"] = {}
        self.check_blocked("membership_review_not_anchored")

    def test_review_pin_binds_document_bytes(self):
        self.parts["documents"][0]["title"] = "forged replacement"
        self.check_blocked("membership_review_evidence_mismatch")

    def test_review_pin_binds_event_identity(self):
        self.parts["membership_events"][0]["security_id"] = self.parts["base_universe"]["security_ids"][0]
        self.check_blocked("membership_review_not_anchored")

    def test_review_cannot_predate_its_pinned_document(self):
        doc = self.parts["documents"][0]
        doc["available_at"] = "2026-09-18T21:39:00Z"
        approval = next(iter(self.policy["approved_membership_reviews"].values()))
        approval["document_hashes"][doc["document_id"]] = bridge.sha(bridge.canonical(doc))
        self.check_blocked("review_predates_document")

    def test_partial_etf_absence_does_not_remove_business_link(self):
        out = self.read()
        rows = [e for e in out["result"]["holding_events"] if e["security_id"] == "SYN_NEW"]
        self.assertEqual(rows[-1]["event_type"], "ABSENCE_UNCONFIRMED")
        self.assertFalse(rows[-1]["sell_proven"])
        self.assertIn("SYN_NEW", out["result"]["summary"]["universe"]["research_universe_proposal"])

    def test_weight_units_flow_through_strict_normalization(self):
        self.parts["etf_snapshots"][-1]["rows"][0]["weight"] = "0.5%"
        out = self.read()
        self.assertEqual(out["result"]["latest_snapshots"]["SYN_ETF"]["rows"][0]["weight"], .005)
        self.parts["etf_snapshots"][-1]["weight_unit"] = "FRACTION"
        self.check_blocked()

    def test_small_fallback_cohort_is_rejected(self):
        self.parts["base_universe"]["security_ids"] = ["SYN_NEW"]
        self.check_blocked("partial_base_universe")

    def test_missing_base_identity_is_rejected(self):
        self.parts["securities"].pop(0)
        self.check_blocked("registry_coverage")

    def test_boolean_identity_claim_is_not_string_coerced(self):
        self.parts["securities"][0]["identity_verified"] = "false"
        self.check_blocked("security_identity_unverified")

    def test_raw_bytes_mismatch(self):
        self.check_blocked("member_hash_mismatch", lambda f, b, n: f.__setitem__(
            "outputs/theme_etf_bridge/prices/raw.json", b"tampered"))

    def test_receipt_bytes_mismatch(self):
        self.check_blocked("member_hash_mismatch", lambda f, b, n: f.__setitem__(
            "outputs/theme_etf_bridge/prices/receipt.json", b'{"status":"VERIFIED"}'))

    def test_archive_hash_mismatch(self):
        artifact = package(self.parts, self.run, self.policy, self.path)
        artifact["digest"] = "sha256:" + "b" * 64
        self.assertEqual(bridge.read_bundle(self.path, self.run, artifact, self.policy, SESSION, NOW)["reason"],
                         "artifact_hash_mismatch")

    def test_failed_or_forked_producer_is_rejected(self):
        for key, value in (("conclusion", "failure"), ("head_branch", "feature"),
                           ("event", "pull_request"), ("path", ".github/workflows/fake.yml")):
            with self.subTest(key=key):
                old = self.run[key]
                self.run[key] = value
                self.check_blocked("untrusted_or_failed_producer")
                self.run[key] = old

    def test_attempt_identity_mismatch(self):
        def alter(files, bundle, name):
            bundle["producer"]["run_attempt"] = 1
            files[name] = bridge.canonical(bundle)
        self.check_blocked("bundle_producer_mismatch", alter)

    def test_unsafe_path_rejected_even_without_extraction(self):
        def alter(files, bundle, name):
            bundle["components"]["prices"]["data"]["path"] = "outputs/theme_etf_bridge/../secret.json"
            files[name] = bridge.canonical(bundle)
        self.check_blocked("invalid_member_path", alter)

    def test_duplicate_json_key_rejected(self):
        self.check_blocked("duplicate_json_key", lambda f, b, n: f.__setitem__(n, b'{"schema":1,"schema":2}'))

    def test_stale_benchmark_is_not_current_by_run_time(self):
        self.parts["prices"]["rows"] = [r for r in self.parts["prices"]["rows"] if r["session"] != SESSION]
        self.check_blocked("stale_benchmark")

    def test_missing_benchmark_session_does_not_stretch_rs(self):
        self.parts["prices"]["rows"].pop(10)
        self.check_blocked("benchmark_session_gap")

    def test_close_before_market_close_rejected(self):
        self.parts["prices"]["rows"][-1]["available_at"] = SESSION + "T18:00:00Z"
        self.check_blocked("price_not_available_after_close")

    def test_adjusted_close_cannot_be_renamed_total_return(self):
        self.parts["prices"]["methodology_id"] = "adjusted_close"
        self.check_blocked("unapproved_return_basis")

    def test_future_and_naive_rows_rejected(self):
        for stamp in ("2026-09-19T00:00:00Z", "2026-09-18T20:00:00"):
            with self.subTest(stamp=stamp):
                self.parts["prices"]["rows"][-1]["available_at"] = stamp
                self.check_blocked()

    def test_nested_order_permission_cannot_be_forwarded(self):
        self.parts["documents"][0]["hidden"] = {"orders_allowed": True}
        self.check_blocked("forbidden_authority")

    def test_multiple_themes_block_until_lifecycle_fix(self):
        event = copy.deepcopy(self.parts["membership_events"][0])
        event.update(event_id="syn-second", theme_id="OTHER", reviewed=False)
        self.parts["membership_events"].append(event)
        self.check_blocked("multi_theme_lifecycle_not_supported")

    def test_late_historical_etf_cannot_become_new_latest(self):
        self.parts["etf_snapshots"][-1]["holdings_as_of"] = "2026-09-01"
        self.check_blocked("late_etf_history_requires_separate_adapter")

    def test_late_publication_cannot_reverse_etf_order(self):
        self.parts["etf_snapshots"][0]["published_at"] = "2026-09-18T21:30:00Z"
        self.check_blocked("late_etf_history_requires_separate_adapter")

    def test_fixture_origin_requires_explicit_test_policy(self):
        self.policy["allowed_sample_origins"] = CONTRACT["theme_etf_bridge"]["allowed_sample_origins"]
        self.check_blocked("sample_origin_not_admitted")

    def test_standalone_artifact_binds_consumer_code_config_and_output(self):
        source = self.read()
        out = bridge.publication(source, code_sha="a" * 40, contract_hash="b" * 64)
        self.assertEqual(out["bridge_sha256"], bridge.sha(bridge.canonical(
            {k: v for k, v in out.items() if k != "bridge_sha256"})))
        self.assertNotIn("bridge_sha256", source)
        self.assertNotEqual(out["bridge_sha256"], bridge.publication(source,
            code_sha="c" * 40, contract_hash="b" * 64)["bridge_sha256"])

    def test_blocked_upstream_cannot_reuse_admitted_result(self):
        out = bridge.observation({"status": "UPSTREAM_FAILED", "data": {"theme_etf_bridge": self.read()}}, SESSION)
        self.assertEqual(out["reason"], "upstream_not_verified")
        self.assertFalse(out["runtime_executed"])

    def test_missing_producer_explicitly_visible(self):
        out = bridge.observation({"status": "VERIFIED_ARTIFACT", "data": {}}, SESSION)
        self.assertEqual(out["reason"], "source_bundle_not_published")
        self.assertFalse(out["end_to_end_ready"])

    def test_no_implicit_business_approvals_in_shipped_policy(self):
        self.assertEqual(CONTRACT["theme_etf_bridge"]["approved_membership_reviews"], {})

    def test_sparse_runtime_dependencies_present(self):
        for name in ("run287_daily_research_monitor.yml", "pages_deploy.yml"):
            self.assertIn("research/theme_etf_runtime_v1", (ROOT / ".github/workflows" / name).read_text())


if __name__ == "__main__":
    unittest.main()
