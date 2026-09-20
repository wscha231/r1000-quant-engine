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
from tools import theme_etf_upstream_admission as admission

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
           "status": "completed", "conclusion": "success", "created_at": "2026-09-18T21:31:00Z",
           "updated_at": "2026-09-18T22:05:00Z"}
    policy = copy.deepcopy(CONTRACT["theme_etf_bridge"])
    policy["allowed_sample_origins"] = ["SYNTHETIC_FIXTURE"]
    policy["approved_membership_reviews"] = {bridge.sha(bridge.canonical(event)): {
        "decision": "APPROVED_BUSINESS_RELATIONSHIP", "reviewer_id": "synthetic-reviewer",
        "reviewed_at": stamp, "document_hashes": {doc["document_id"]: bridge.sha(bridge.canonical(doc))}}}
    return parts, run, policy


def recovery_fixture(run):
    valid = {"schema_version": "run287-risk-outcome-parent-preflight-v1",
             "status": "READY_ONE_TIME_GENESIS", "generated_at_utc": "2026-09-18T21:38:00Z",
             "source": {"event_name": "workflow_dispatch", "source_commit_sha": run["head_sha"],
                 "source_run_id": str(run["id"]), "source_run_attempt": str(run["run_attempt"]),
                 "source_job_key": "refresh", "session_date": SESSION},
             "authorization": {"mode": "genesis", "required_event_name": "workflow_dispatch",
                 "required_input": "allow_risk_outcome_genesis_bootstrap", "requested": True,
                 "conflicting_authorization_requested": False, "satisfied": True,
                 "one_time_only": True, "separate_user_approval_required": True},
             "review_only": True, "blockers": [], "exit_code": 0,
             "observed_state": {"remote_accepted_head_discovery_confirmed": True,
                 "remote_committed_accepted_head_count": 0, "remote_committed_accepted_head_absence_proven": True,
                 "legacy_parent": {"state": "PROVEN_ABSENT", "summary_sha256": "", "summary_bytes": 0,
                     "event_log_sha256": bridge.sha(b""), "event_log_bytes": 0, "event_count": 0,
                     "byte_exact_allowlist_match": False, "review_only": True},
                 "paper_ledger": {"schema_version": "run287-paper-ledger-snapshot-integrity-v2", "status": "VERIFIED",
                     "verifier_receipt_schema_version": "run287-paper-ledger-integrity-verifier-receipt-v1",
                     "file_sha256": "b" * 64, "files_sha256": "b" * 64, "snapshot_hash": "b" * 64,
                     "genesis_identity_sha256": "b" * 64, "verifier_receipt_sha256": "b" * 64,
                     "immutable_head_selection_sha256": "b" * 64, "immutable_root_snapshot_hash": "b" * 64,
                     "immutable_terminal_snapshot_hash": "b" * 64, "file_bytes": 123, "file_count": 1,
                     "verifier_receipt_bytes": 123, "immutable_head_count": 1, "ancestor_snapshot_count": 0,
                     "immutable_chain_snapshot_hashes": ["b" * 64], "previous_snapshot_hash": "", "as_of_date": SESSION}}}
    from tools.build_run287_risk_outcome_parent_preflight import FALSE_SAFETY_FLAGS
    valid.update({k: False for k in FALSE_SAFETY_FLAGS})
    return valid


def upstream_fixture(files, run):
    from tools.run287_code_identity import IDENTITY_FILES, identity_sha256
    identity = {"schema_version": "run287-exact-packet-code-identity-v1", "source_commit_sha": run["head_sha"],
                "source_tree_sha": "b" * 40, "files": {label: {"path": path, "sha256": "b" * 64}
                    for label, path in IDENTITY_FILES.items()}}
    identity["identity_sha256"] = identity_sha256(identity)
    def add(path, obj):
        raw = bridge.canonical(obj) if not isinstance(obj, bytes) else obj
        files[path] = raw
        return {"path": path, "sha256": bridge.sha(raw), "bytes": len(raw), "exists": True}
    root = f"outputs/run287_exact_packet_upstream/attempts/{run['id']}-{run['run_attempt']}"
    inputs, stages, by_stage = {}, [], {}
    for index, (name, tool, status, date_field, label) in enumerate(admission.STAGES):
        obj = {"status": status, "research_only": True, **{k: False for k in admission.SAFE_FALSE}}
        if date_field:
            obj[date_field] = SESSION
        obj["outputs"] = {key: add(root + "/" + name + "/" + (key + ".csv" if key == "ticker_order_score_stack" else key),
                           b"security_id,value\nSYN_FIXTURE,1\n") for key in admission.OUTPUTS.get(label, ())}
        obj["source_inputs"] = {key: inputs[source] for owner, key, source in admission.EDGES if owner == label}
        obj["source_inputs"].update({key: by_stage[source] for owner, key, source in admission.STAGE_EDGES if owner == name})
        if name in ("score_only", "score_stack"):
            obj["source_inputs"]["decision_frame_manifest"] = inputs["decision_manifest"]
        if name == "score_stack":
            obj["source_inputs"]["score_only_manifest"] = by_stage["score_only"]
        record = add(root + "/" + name + "/manifest.json", obj)
        by_stage[name] = record
        if label:
            inputs[label] = {k: record[k] for k in ("path", "sha256")}
        stages.append({"name": name, "tool": "tools/" + tool + ".py", "status": status,
                       "return_code": 0, "failures": [], "network_requests_executed": 0,
                       "elapsed_seconds": .1, "completed_at_utc": f"2026-09-18T21:{40 + index}:00Z", "manifest": record,
                       "log": add(root + "/logs/" + name + ".log", b"synthetic fixture only\n")})
    policy = json.loads((ROOT / "docs/run287_exact_packet_producer_contract.json").read_text())
    plan = json.loads((ROOT / "docs/run287_exact_packet_upstream_plan.json").read_text())
    plan_raw = (ROOT / "docs/run287_exact_packet_upstream_plan.json").read_bytes()
    plan_record = add(root + "/plan.json", plan_raw)
    inputs.update({label: {"path": plan["paths"][label]["path"], "sha256": pin}
                   for label, pin in policy["required_fixed_inputs"].items()})
    bundle = {"schema_version": admission.BUNDLE_SCHEMA, "status": admission.BUNDLE_STATUS,
              "valuation_price_cutoff_date": SESSION, "research_only": True, "network_requests_executed": 0,
              **{k: False for k in admission.SAFE_FALSE}, "code_identity": identity, "inputs": inputs}
    record = add("outputs/run287_exact_packet_input_sources/source_bundle.json", bundle)
    return {"schema_version": "run287-exact-packet-upstream-orchestrator-v3", "status": admission.READY,
            "upstream_ready": True, "valuation_price_cutoff_date": SESSION, "research_only": True,
            **{k: False for k in admission.SAFE_FALSE}, "historical_cagr_mdd_evidence_changed": False,
            "network_requests_executed": 0, "elapsed_seconds": 1, "completed_at_utc": "2026-09-18T21:55:00Z",
            "preflight": {"code_identity": identity, "decision_time_utc": "2026-09-18T21:38:00Z",
                "archived_plan": plan_record, "plan": {**plan_record, "path": "docs/run287_exact_packet_upstream_plan.json"}},
            "source_bundle": record, "stage_audit": stages}


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
        raw = add(root + "/raw/source.json", part)
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
        if key == "recovery":
            continue  # Optional receipt is absent for normal accepted-parent runs.
        name = name.format(run_id=run["id"], run_attempt=run["run_attempt"])
        files[name] = b"ticker,previous_close,latest_price_date,currency\n" if name.endswith(".csv") else b"{}\n"
        if key == "upstream":
            files[name] = bridge.canonical(upstream_fixture(files, run))
    if alter:
        alter(files, bundle, bundle_name)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as out:
        for name, raw in files.items():
            out.writestr(name, raw)
    artifact = {"id": 456, "name": "daily-operating-selection-refresh-123", "expired": False,
                "created_at": "2026-09-18T22:02:00Z",
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

    def collect(self, alter=None):
        artifact = package(self.parts, self.run, self.policy, self.path, alter)
        raw, run = self.path.read_bytes(), self.run
        class Client:
            def json(self, path):
                return {"workflow_runs": [run]} if "/workflows/" in path else {"artifacts": [artifact]}
            def archive(self, artifact_id, destination, limit):
                destination.write_bytes(raw)
                return "sha256:" + bridge.sha(raw)
        contract = copy.deepcopy(CONTRACT)
        contract["theme_etf_bridge"] = self.policy
        return monitor.collect_source(Client(), "operating", contract["sources"]["operating"], contract,
                                      now=NOW, session=SESSION)

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
        # Names alone are insufficient when the receipt says blocked or stale.
        upstream = contract["sources"]["operating"]["members"]["upstream"].format(
            run_id=run["id"], run_attempt=run["run_attempt"])
        for change in ({"status": "BLOCKED"}, {"upstream_ready": False},
                       {"valuation_price_cutoff_date": "2026-09-17"}):
            def bad_receipt(files, bundle, name):
                value = json.loads(files[upstream]); value.update(change)
                files[upstream] = bridge.canonical(value)
            artifact = package(self.parts, self.run, self.policy, self.path, bad_receipt)
            raw = self.path.read_bytes()
            failed = monitor.collect_source(Client(), "operating", contract["sources"]["operating"], contract,
                                            now=NOW, session=SESSION)
            self.assertEqual(failed["data"]["theme_etf_bridge"]["reason"], "upstream_contract_not_ready")
            self.assertFalse(failed["data"]["theme_etf_bridge"]["runtime_executed"])

    def test_reviewed_boolean_without_external_pin_cannot_add_security(self):
        self.policy["approved_membership_reviews"] = {}
        self.check_blocked("membership_review_not_anchored")

    def test_recovery_observation_contradictions_cannot_authorize_runtime(self):
        self.run["event"] = "workflow_dispatch"
        valid = recovery_fixture(self.run)
        mutations = [("remote_accepted_head_discovery_confirmed", False),
                     ("remote_committed_accepted_head_count", 1), ("remote_committed_accepted_head_count", False),
                     ("remote_committed_accepted_head_absence_proven", False), ("legacy_parent", {}), ("paper_ledger", {})]
        receipts = []
        for key, value in mutations:
            receipt = copy.deepcopy(valid); receipt["observed_state"][key] = value; receipts.append(receipt)
        for key, value in (("state", "PRESENT_FETCHED"), ("summary_sha256", "a" * 64),
                           ("event_count", 1), ("summary_bytes", False), ("byte_exact_allowlist_match", True)):
            receipt = copy.deepcopy(valid); receipt["observed_state"]["legacy_parent"][key] = value; receipts.append(receipt)
        for key, value in (("status", "BLOCKED"), ("immutable_head_count", 2), ("snapshot_hash", "a" * 64),
                           ("previous_snapshot_hash", "a" * 64), ("as_of_date", "2026-02-30"), ("file_bytes", True)):
            receipt = copy.deepcopy(valid); receipt["observed_state"]["paper_ledger"][key] = value; receipts.append(receipt)
        receipts += [{**valid, "observed_state": value} for value in ({}, None, True)]
        path = CONTRACT["sources"]["operating"]["members"]["recovery"]
        for receipt in receipts:
            with self.subTest(receipt=receipt):
                source = self.collect(lambda files, bundle, name: files.__setitem__(path, bridge.canonical(receipt)))
                self.assertEqual(source["status"], "VERIFIED_ARTIFACT")
                self.assertFalse(source["data"]["theme_etf_bridge"]["runtime_executed"])

    def test_upstream_producer_contract_requires_more_than_ready_labels(self):
        path = CONTRACT["sources"]["operating"]["members"]["upstream"].format(
            run_id=self.run["id"], run_attempt=self.run["run_attempt"])
        mutations = [{"schema_version": "wrong"}, {"research_only": False}, {"orders_generated": True},
                     {"historical_cagr_mdd_evidence_changed": True}, {"preflight": {}},
                     {"stage_audit": []}, {"source_bundle": {}}, {"network_requests_executed": True},
                     {"network_requests_executed": 1}, {"elapsed_seconds": -1}, {"contract_failures": ["broken"]}]
        for mutation in mutations + [None]:
            def alter(files, bundle, name):
                upstream = json.loads(files[path])
                if mutation is None:
                    upstream = {k: upstream[k] for k in ("status", "upstream_ready", "valuation_price_cutoff_date")}
                else:
                    upstream.update(mutation)
                files[path] = bridge.canonical(upstream)
            with self.subTest(mutation=mutation):
                source = self.collect(alter)
                self.assertEqual(source["status"], "VERIFIED_ARTIFACT")
                self.assertTrue({"upstream", "market", "prices"}.issubset(source["data"]))
                self.assertFalse(source["data"]["theme_etf_bridge"]["runtime_executed"])

    def test_upstream_graph_reads_bound_original_bytes_and_stage_identity(self):
        upstream_path = CONTRACT["sources"]["operating"]["members"]["upstream"].format(
            run_id=self.run["id"], run_attempt=self.run["run_attempt"])
        for mutation in ("bundle_hash", "bundle_missing", "dynamic_hash", "output_hash", "log_hash",
                         "stage_failure", "stage_return", "stage_order", "stage_duplicate", "stage_copy",
                         "code_identity", "code_files", "bundle_schema", "bundle_unsafe", "fixed_pin", "lineage", "duplicate_json"):
            def alter(files, bundle, name):
                upstream = json.loads(files[upstream_path]); ref = upstream["source_bundle"]
                source_bundle = json.loads(files[ref["path"]]); first = upstream["stage_audit"][0]
                if mutation == "bundle_hash":
                    files[ref["path"]] += b" "
                elif mutation == "bundle_missing":
                    files.pop(ref["path"])
                elif mutation == "dynamic_hash":
                    files[source_bundle["inputs"]["price_manifest"]["path"]] += b" "
                elif mutation == "output_hash":
                    manifest = json.loads(files[first["manifest"]["path"]])
                    files[next(iter(manifest["outputs"].values()))["path"]] += b" "
                elif mutation == "log_hash":
                    files[first["log"]["path"]] += b" "
                elif mutation == "stage_failure":
                    first["failures"] = ["failed"]
                elif mutation == "stage_return":
                    first["return_code"] = False
                elif mutation == "stage_order":
                    upstream["stage_audit"].reverse()
                elif mutation == "stage_duplicate":
                    upstream["stage_audit"].append(copy.deepcopy(first))
                elif mutation == "stage_copy":
                    first["manifest"]["path"] = first["manifest"]["path"].replace("123-2", "122-1")
                elif mutation == "code_identity":
                    upstream["preflight"]["code_identity"]["source_commit_sha"] = "c" * 40
                elif mutation == "code_files":
                    from tools.run287_code_identity import identity_sha256
                    identity = upstream["preflight"]["code_identity"]
                    identity["files"] = {key: None for key in identity["files"]}
                    identity["identity_sha256"] = identity_sha256(identity)
                else:
                    if mutation == "bundle_schema":
                        source_bundle["schema_version"] = "wrong"
                    elif mutation == "bundle_unsafe":
                        source_bundle["orders_generated"] = True
                    elif mutation == "fixed_pin":
                        source_bundle["inputs"]["main_prior_book"]["sha256"] = "c" * 64
                    elif mutation == "lineage":
                        record = source_bundle["inputs"]["decision_manifest"]
                        obj = json.loads(files[record["path"]]); obj["source_inputs"]["macro_manifest"] = record
                        files[record["path"]] = bridge.canonical(obj); record["sha256"] = bridge.sha(files[record["path"]])
                    raw = bridge.canonical(source_bundle)
                    if mutation == "duplicate_json":
                        raw = raw[:-1] + b',"status":"READY_EXACT_PACKET_INPUT_SOURCE_PATHS_REVIEW_ONLY"}'
                    files[ref["path"]] = raw; ref.update(sha256=bridge.sha(raw), bytes=len(raw))
                files[upstream_path] = bridge.canonical(upstream)
            with self.subTest(mutation=mutation):
                source = self.collect(alter)
                self.assertEqual(source["status"], "VERIFIED_ARTIFACT")
                self.assertFalse(source["data"]["theme_etf_bridge"]["runtime_executed"])
                self.assertIn("theme_upstream_error", source)

    def test_upstream_same_close_reuse_verifies_dated_source_bytes(self):
        path = CONTRACT["sources"]["operating"]["members"]["upstream"].format(
            run_id=self.run["id"], run_attempt=self.run["run_attempt"])
        for corrupted in (False, True):
            def alter(files, bundle, name):
                upstream = json.loads(files[path]); ref = upstream["source_bundle"]
                dated = "outputs/run287_exact_packet_input_sources/by_date/" + SESSION + "/source_bundle.json"
                files[dated] = files[ref["path"]] + (b" " if corrupted else b"")
                upstream.update(status=admission.REUSED, network_execution_authorized=False,
                    stage_audit=[{"name": "existing_source_bundle",
                        "status": "READY_EXISTING_EXACT_PACKET_INPUT_SOURCE_BUNDLE_REVIEW_ONLY",
                        "network_requests_executed": 0, "completed_at_utc": "2026-09-18T21:54:00Z",
                        "failures": [], "manifest": {**ref, "path": dated}}])
                files[path] = bridge.canonical(upstream)
            source = self.collect(alter)
            self.assertEqual(source["data"]["theme_etf_bridge"]["runtime_executed"], not corrupted)
            if not corrupted:
                self.assertIn("theme_upstream_reused_bundle", source["files"])

    def test_runtime_decision_must_follow_upstream_completion(self):
        path = CONTRACT["sources"]["operating"]["members"]["upstream"].format(
            run_id=self.run["id"], run_attempt=self.run["run_attempt"])
        def alter(files, bundle, name):
            upstream = json.loads(files[path]); upstream["completed_at_utc"] = "2026-09-18T22:01:00Z"
            files[path] = bridge.canonical(upstream)
        source = self.collect(alter)
        self.assertEqual(source["data"]["theme_etf_bridge"]["reason"], "decision_predates_prerequisite")
        self.assertFalse(source["data"]["theme_etf_bridge"]["runtime_executed"])

    def test_upstream_plan_identity_and_request_budgets_are_required(self):
        path = CONTRACT["sources"]["operating"]["members"]["upstream"].format(
            run_id=self.run["id"], run_attempt=self.run["run_attempt"])
        for mutation in ("total_cap", "stage_cap", "stage_count", "plan_missing", "plan_hash", "plan_identity", "raised_cap"):
            def alter(files, bundle, name):
                upstream = json.loads(files[path]); plan = upstream["preflight"]["archived_plan"]
                if mutation in ("total_cap", "stage_cap", "stage_count"):
                    count = {"total_cap": 131, "stage_cap": 33, "stage_count": 1}[mutation]
                    upstream["stage_audit"][0]["network_requests_executed"] = count
                    upstream["network_requests_executed"] = count
                elif mutation == "plan_missing":
                    files.pop(plan["path"])
                elif mutation == "plan_hash":
                    files[plan["path"]] += b" "
                elif mutation == "plan_identity":
                    upstream["preflight"]["plan"]["sha256"] = "c" * 64
                else:
                    obj = json.loads(files[plan["path"]]); obj["network_budgets"]["maximum_total_recorded_requests"] = 999
                    raw = bridge.canonical(obj); files[plan["path"]] = raw
                    for ref in (plan, upstream["preflight"]["plan"]):
                        ref.update(sha256=bridge.sha(raw), bytes=len(raw))
                files[path] = bridge.canonical(upstream)
            with self.subTest(mutation=mutation):
                source = self.collect(alter)
                self.assertEqual(source["status"], "VERIFIED_ARTIFACT")
                self.assertFalse(source["data"]["theme_etf_bridge"]["runtime_executed"])

    def test_all_producer_stage_dependencies_match_the_audited_manifests(self):
        path = CONTRACT["sources"]["operating"]["members"]["upstream"].format(
            run_id=self.run["id"], run_attempt=self.run["run_attempt"])
        for owner, key, dependency in admission.STAGE_EDGES:
            def alter(files, bundle, name):
                upstream = json.loads(files[path]); audits = {a["name"]: a for a in upstream["stage_audit"]}
                obj = json.loads(files[audits[owner]["manifest"]["path"]])
                other = copy.deepcopy(audits[dependency]["manifest"])
                other["path"] = other["path"].replace("/" + dependency + "/", "/other_" + dependency + "/")
                files[other["path"]] = files[audits[dependency]["manifest"]["path"]]
                obj["source_inputs"][key] = other
                files[audits[owner]["manifest"]["path"]] = bridge.canonical(obj)
                # Rehash every downstream reference so byte checks alone pass.
                updated = {}
                def rebind(value):
                    if isinstance(value, dict):
                        if isinstance(value.get("path"), str) and value["path"] in updated:
                            value["sha256"] = updated[value["path"]]["sha256"]
                            if "bytes" in value:
                                value["bytes"] = updated[value["path"]]["bytes"]
                        for child in value.values():
                            rebind(child)
                    elif isinstance(value, list):
                        for child in value:
                            rebind(child)
                for audit in upstream["stage_audit"]:
                    ref = audit["manifest"]; obj = json.loads(files[ref["path"]]); rebind(obj)
                    raw = bridge.canonical(obj); files[ref["path"]] = raw
                    ref.update(sha256=bridge.sha(raw), bytes=len(raw)); updated[ref["path"]] = ref
                ref = upstream["source_bundle"]; obj = json.loads(files[ref["path"]]); rebind(obj)
                raw = bridge.canonical(obj); files[ref["path"]] = raw; ref.update(sha256=bridge.sha(raw), bytes=len(raw))
                files[path] = bridge.canonical(upstream)
            with self.subTest(edge=(owner, key, dependency)):
                source = self.collect(alter)
                self.assertEqual(source["status"], "VERIFIED_ARTIFACT")
                self.assertFalse(source["data"]["theme_etf_bridge"]["runtime_executed"])

    def test_upstream_completion_order_and_existing_score_graph_gate_runtime(self):
        path = CONTRACT["sources"]["operating"]["members"]["upstream"].format(
            run_id=self.run["id"], run_attempt=self.run["run_attempt"])
        for mutation in ("completion_missing", "completion_before_stages", "completion_after_artifact", "stage_time_missing",
                         "stage_time_reversed", "score_csv_shape"):
            def alter(files, bundle, name):
                upstream = json.loads(files[path])
                if mutation == "completion_missing":
                    upstream.pop("completed_at_utc")
                elif mutation == "completion_before_stages":
                    upstream["completed_at_utc"] = "2026-09-18T21:39:00Z"
                elif mutation == "completion_after_artifact":
                    upstream["completed_at_utc"] = "2026-09-18T22:03:00Z"
                elif mutation == "stage_time_missing":
                    upstream["stage_audit"][0].pop("completed_at_utc")
                elif mutation == "stage_time_reversed":
                    upstream["stage_audit"][0]["completed_at_utc"] = "2026-09-18T21:54:00Z"
                else:
                    # Use a byte-consistent graph with duplicate CSV headers.
                    audit = next(a for a in upstream["stage_audit"] if a["name"] == "score_stack")
                    manifest = json.loads(files[audit["manifest"]["path"]]); output = manifest["outputs"]["ticker_order_score_stack"]
                    raw = b"ticker,ticker\nSYN_A,SYN_B\n"; files[output["path"]] = raw
                    output.update(sha256=bridge.sha(raw), bytes=len(raw))
                    raw = bridge.canonical(manifest); files[audit["manifest"]["path"]] = raw
                    audit["manifest"].update(sha256=bridge.sha(raw), bytes=len(raw))
                    ref = upstream["source_bundle"]; obj = json.loads(files[ref["path"]])
                    obj["inputs"]["score_stack_manifest"]["sha256"] = bridge.sha(raw)
                    raw = bridge.canonical(obj); files[ref["path"]] = raw; ref.update(sha256=bridge.sha(raw), bytes=len(raw))
                files[path] = bridge.canonical(upstream)
            with self.subTest(mutation=mutation):
                source = self.collect(alter)
                self.assertEqual(source["status"], "VERIFIED_ARTIFACT")
                self.assertFalse(source["data"]["theme_etf_bridge"]["runtime_executed"])

    def test_optional_recovery_requires_affirmative_producer_semantics(self):
        contract = copy.deepcopy(CONTRACT)
        contract["theme_etf_bridge"] = self.policy
        run = self.run
        run["event"] = "workflow_dispatch"
        recovery_path = contract["sources"]["operating"]["members"]["recovery"]
        artifact, raw = None, None
        class Client:
            def json(self, path):
                return {"workflow_runs": [run]} if "/workflows/" in path else {"artifacts": [artifact]}
            def archive(self, artifact_id, destination, limit):
                destination.write_bytes(raw)
                return "sha256:" + hashlib.sha256(raw).hexdigest()
        valid = recovery_fixture(run)
        legacy = copy.deepcopy(valid)
        legacy["status"] = "READY_ONE_TIME_LEGACY_QUARANTINE"
        legacy["authorization"].update(mode="legacy_quarantine", required_input="allow_quarantined_legacy_outcome_parent")
        from tools.build_run287_risk_outcome_parent_anchor import KNOWN_LEGACY_SAFETY_MIGRATIONS
        pin_hash, pin = next(iter(KNOWN_LEGACY_SAFETY_MIGRATIONS.items()))
        legacy["observed_state"]["legacy_parent"] = {"state": "PRESENT_FETCHED", "summary_sha256": pin_hash,
            "summary_bytes": 123, "as_of_date": pin["as_of_date"], "status": pin["status"],
            "event_log_sha256": bridge.sha(b""), "event_log_bytes": 0, "event_count": 0,
            "allowlist_evidence_workflow_run_id": pin["evidence_workflow_run_id"],
            "byte_exact_allowlist_match": True, "review_only": True}
        cases = [(valid, True), (legacy, True)]
        cases += [({**valid, "status": state}, False) for state in ("FAILED", "ERROR", {}, [], None, 1)]
        cases += [({**valid, "authorization": auth}, False) for auth in ({}, {"satisfied": False},
                   {"satisfied": "true"}, None, True)]
        cases += [({}, False), ({**valid, "blockers": ["conflict"]}, False),
                  ({**valid, "exit_code": False}, False), ({**valid, "exit_code": 2}, False)]
        for field, value in (("event_name", "schedule"), ("source_commit_sha", "b" * 40),
                             ("source_run_id", "122"), ("source_run_attempt", "1"),
                             ("source_job_key", "other"), ("session_date", "2026-09-17")):
            cases.append(({**valid, "source": {**valid["source"], field: value}}, False))
        for field, value in (("schema_version", "other"), ("source", {}), ("ledger_mutated", True),
                             ("generated_at_utc", "2026-09-18T21:30:00Z"),
                             ("generated_at_utc", "2026-09-18T22:03:00Z")):
            cases.append(({**valid, field: value}, False))
        for receipt, admitted in cases:
            with self.subTest(receipt=receipt):
                artifact = package(self.parts, run, self.policy, self.path,
                    lambda files, bundle, name: files.__setitem__(recovery_path, bridge.canonical(receipt)))
                raw = self.path.read_bytes()
                source = monitor.collect_source(Client(), "operating", contract["sources"]["operating"],
                                                contract, now=NOW, session=SESSION)
                out = source["data"]["theme_etf_bridge"]
                self.assertEqual(out["runtime_executed"], admitted, out)
                if not admitted:
                    self.assertEqual(out["reason"], "upstream_contract_not_ready")
        run["event"] = "schedule"
        artifact = package(self.parts, run, self.policy, self.path,
            lambda files, bundle, name: files.__setitem__(recovery_path, bridge.canonical(valid)))
        raw = self.path.read_bytes()
        source = monitor.collect_source(Client(), "operating", contract["sources"]["operating"], contract,
                                        now=NOW, session=SESSION)
        self.assertEqual(source["data"]["theme_etf_bridge"]["reason"], "upstream_contract_not_ready")

    def test_canonical_document_ids_cannot_inflate_source_counts(self):
        doc = self.parts["documents"][0]
        self.parts["documents"].append({**doc, "document_id": " " + doc["document_id"] + " "})
        self.check_blocked("duplicate_document")
        self.parts["documents"] = [self.parts["documents"][-1]]
        self.check_blocked("noncanonical_document_id")

    def test_decision_and_receipts_cannot_predate_authenticated_run(self):
        self.run["created_at"] = "2026-09-18T22:01:00Z"
        self.check_blocked("decision_predates_producer")
        self.run["created_at"] = "2026-09-18T21:31:00Z"
        self.run["run_started_at"] = "2026-09-18T22:01:00Z"
        self.check_blocked("decision_predates_producer")
        self.run["run_started_at"] = "2026-09-18T21:41:00Z"
        self.check_blocked("receipt_predates_producer")

    def test_decision_cannot_postdate_artifact_or_predate_prerequisite(self):
        artifact = package(self.parts, self.run, self.policy, self.path)
        artifact["created_at"] = "2026-09-18T21:45:00Z"
        out = bridge.read_bundle(self.path, self.run, artifact, self.policy, SESSION, NOW)
        self.assertEqual(out["reason"], "decision_postdates_artifact")
        artifact["created_at"] = "2026-09-18T22:02:00Z"
        self.run["updated_at"] = "2026-09-18T21:45:00Z"
        out = bridge.read_bundle(self.path, self.run, artifact, self.policy, SESSION, NOW)
        self.assertEqual(out["reason"], "invalid_artifact_timeline")
        self.run["updated_at"] = "2026-09-18T22:05:00Z"
        out = bridge.read_bundle(self.path, self.run, artifact, self.policy, SESSION, NOW,
                                 prerequisite_at="2026-09-18T22:01:00Z")
        self.assertEqual(out["reason"], "decision_predates_prerequisite")

    def test_all_security_references_require_canonical_identity(self):
        pristine = copy.deepcopy(self.parts)
        for role, container in (("securities", None), ("membership_events", None),
                                ("prices", "rows"), ("etf_snapshots", "rows")):
            for bad in (" SYN_NEW ", "syn_new"):
                with self.subTest(role=role, bad=bad):
                    self.parts = copy.deepcopy(pristine)
                    if role == "etf_snapshots":
                        row = self.parts[role][0][container][0]
                    elif container:
                        row = self.parts[role][container][-1]
                    else:
                        row = self.parts[role][-1]
                    row["security_id"] = bad
                    self.check_blocked("noncanonical_security_id")

    def test_review_pin_binds_document_bytes(self):
        self.parts["documents"][0]["title"] = "forged replacement"
        self.check_blocked("membership_review_evidence_mismatch")

    def test_business_pin_requires_canonical_textual_reviewer(self):
        approval = next(iter(self.policy["approved_membership_reviews"].values()))
        for value in (True, 1, {"name": "reviewer"}, ["reviewer"], None, " ", " reviewer "):
            with self.subTest(reviewer=value):
                approval["reviewer_id"] = value
                self.check_blocked("invalid_source_identity")

    def test_prerequisite_json_rejects_conflicts_and_nonfinite_values(self):
        contract = copy.deepcopy(CONTRACT)
        contract["theme_etf_bridge"] = self.policy
        run = self.run
        run["event"] = "workflow_dispatch"
        artifact, raw = None, None
        class Client:
            def json(self, path):
                return {"workflow_runs": [run]} if "/workflows/" in path else {"artifacts": [artifact]}
            def archive(self, artifact_id, destination, limit):
                destination.write_bytes(raw)
                return "sha256:" + hashlib.sha256(raw).hexdigest()
        spec = contract["sources"]["operating"]
        for kind in ("upstream_status", "recovery_status", "recovery_authorization", "NaN", "1e999"):
            def alter(files, bundle, name):
                role = "recovery" if kind.startswith("recovery") else "upstream"
                path = spec["members"][role].format(run_id=run["id"], run_attempt=run["run_attempt"])
                value = bridge.canonical(recovery_fixture(run)) if role == "recovery" else files[path]
                if kind.endswith("status"):
                    value = b'{"status":"BLOCKED",' + value[1:]
                elif kind == "recovery_authorization":
                    value = value.replace(b'"satisfied":true', b'"satisfied":false,"satisfied":true')
                else:
                    value = b'{"diagnostic":' + kind.encode() + b',' + value[1:]
                files[path] = value
            with self.subTest(kind=kind):
                artifact = package(self.parts, run, self.policy, self.path, alter)
                raw = self.path.read_bytes()
                source = monitor.collect_source(Client(), "operating", spec, contract, now=NOW, session=SESSION)
                self.assertEqual(source["status"], "BLOCKED_SOURCE", source)
                self.assertFalse(bridge.observation(source, SESSION)["runtime_executed"])

    def test_review_pin_binds_event_identity(self):
        self.parts["membership_events"][0]["security_id"] = self.parts["base_universe"]["security_ids"][0]
        self.check_blocked("membership_review_not_anchored")

    def test_ticker_reuse_does_not_copy_business_reason_to_other_identity(self):
        self.parts["securities"][0]["ticker"] = "SYN_NEW"
        out = self.read()
        self.assertEqual(out["status"], "ADMITTED_RESEARCH_ONLY")
        rows = {r["security_id"]: r for r in out["data_queue_preview"]["items"]}
        self.assertEqual(rows["SYN_BASE_0000"]["membership_reasons"], [])
        self.assertEqual(rows["SYN_NEW"]["membership_reasons"][0]["security_id"], "SYN_NEW")

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

    def test_issuer_and_ticker_are_canonical_text(self):
        row = self.parts["securities"][-1]
        original = copy.deepcopy(row)
        for key, bad in (("issuer_id", True), ("issuer_id", " "), ("issuer_id", " issuer "),
                         ("ticker", True), ("ticker", " "), ("ticker", "syn_new"), ("ticker", " SYN_NEW ")):
            with self.subTest(key=key, bad=bad):
                row.update(original)
                row[key] = bad
                self.check_blocked("security_identity_unverified")

    def test_raw_bytes_mismatch(self):
        self.check_blocked("member_hash_mismatch", lambda f, b, n: f.__setitem__(
            "outputs/theme_etf_bridge/prices/raw/source.json", b"tampered"))

    def test_receipt_bytes_mismatch(self):
        self.check_blocked("member_hash_mismatch", lambda f, b, n: f.__setitem__(
            "outputs/theme_etf_bridge/prices/receipt.json", b'{"status":"VERIFIED"}'))

    def test_receipt_cannot_validate_data_before_it_was_available(self):
        def alter(files, bundle, name):
            ref = bundle["components"]["prices"]["receipt"]
            receipt = json.loads(files[ref["path"]])
            receipt["validated_at"] = "2026-09-18T21:32:00Z"
            files[ref["path"]] = bridge.canonical(receipt)
            ref["sha256"] = bridge.sha(files[ref["path"]])
            files[name] = bridge.canonical(bundle)
        self.parts["prices"]["rows"][-1]["available_at"] = "2026-09-18T21:35:00Z"
        self.check_blocked("receipt_predates_component", alter)

    def test_normalized_data_cannot_substitute_for_distinct_raw_source(self):
        def alter(files, bundle, name):
            refs = bundle["components"]["prices"]
            receipt = json.loads(files[refs["receipt"]["path"]])
            receipt["raw_objects"] = [refs["data"]]
            files[refs["receipt"]["path"]] = bridge.canonical(receipt)
            refs["receipt"]["sha256"] = bridge.sha(files[refs["receipt"]["path"]])
            files[name] = bridge.canonical(bundle)
        self.check_blocked("raw_source_reference_invalid", alter)

    def test_cross_role_data_cannot_masquerade_as_raw_source(self):
        def alter(files, bundle, name):
            refs = bundle["components"]
            data = refs["base_universe"]["data"]
            raw_path = "outputs/theme_etf_bridge/prices/raw/alias.json"
            files[raw_path] = files[data["path"]]
            data["path"] = raw_path
            receipt_ref = refs["prices"]["receipt"]
            receipt = json.loads(files[receipt_ref["path"]])
            receipt["raw_objects"] = [dict(data)]
            files[receipt_ref["path"]] = bridge.canonical(receipt)
            receipt_ref["sha256"] = bridge.sha(files[receipt_ref["path"]])
            files[name] = bridge.canonical(bundle)
        self.check_blocked("component_namespace_mismatch", alter)

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
        self.check_blocked("component_namespace_mismatch", alter)

    def test_duplicate_json_key_rejected(self):
        self.check_blocked("duplicate_json_key", lambda f, b, n: f.__setitem__(n, b'{"schema":1,"schema":2}'))

    def test_deep_optional_json_does_not_erase_required_monitor_evidence(self):
        def alter(files, bundle, name):
            refs = bundle["components"]["documents"]
            data = b"[" * 2000 + b"0" + b"]" * 2000
            files[refs["data"]["path"]] = data
            refs["data"]["sha256"] = bridge.sha(data)
            receipt = json.loads(files[refs["receipt"]["path"]])
            receipt["data_sha256"] = bridge.sha(data)
            files[refs["receipt"]["path"]] = bridge.canonical(receipt)
            refs["receipt"]["sha256"] = bridge.sha(files[refs["receipt"]["path"]])
            files[name] = bridge.canonical(bundle)
        artifact = package(self.parts, self.run, self.policy, self.path, alter)
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
        self.assertTrue({"upstream", "market", "prices"}.issubset(source["data"]))
        self.assertTrue(source["data"]["upstream"]["upstream_ready"])
        self.assertEqual(source["data"]["theme_etf_bridge"]["reason"], "invalid_source_bundle")
        self.assertFalse(source["data"]["theme_etf_bridge"]["runtime_executed"])

    def test_provenance_ids_cannot_be_fabricated_by_string_coercion(self):
        original = copy.deepcopy(self.parts)
        for role, field in (("etf_snapshots", "fund_id"), ("etf_snapshots", "source_id"),
                            ("documents", "source_group"), ("membership_events", "event_id"),
                            ("membership_events", "theme_id")):
            for value in (True, 123, {}, [], None, " "):
                with self.subTest(role=role, field=field, value=value):
                    self.parts = copy.deepcopy(original)
                    self.parts[role][0][field] = value
                    self.check_blocked("fund_identity_missing" if field == "fund_id" else "invalid_source_identity")

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

    def test_fund_case_or_spaces_cannot_bypass_history_order(self):
        self.parts["etf_snapshots"][-1]["fund_id"] = " syn_etf "
        self.parts["etf_snapshots"][-1]["holdings_as_of"] = "2026-09-01"
        self.check_blocked("late_etf_history_requires_separate_adapter")

    def test_equal_availability_respects_revisions_and_rejects_ambiguity(self):
        for row in self.parts["etf_snapshots"]:
            row["observed_at"] = SESSION + "T21:00:00Z"
            row["validated_at"] = SESSION + "T21:00:00Z"
        self.parts["etf_snapshots"][0]["revision_number"] = 2
        self.parts["etf_snapshots"][1]["revision_number"] = 1
        self.check_blocked("late_etf_history_requires_separate_adapter")
        self.parts["etf_snapshots"][1]["revision_number"] = 2
        self.check_blocked("ambiguous_etf_revision_order")

    def test_same_date_etf_revision_must_advance_without_reuse(self):
        old, new = self.parts["etf_snapshots"]
        old["holdings_as_of"] = SESSION
        old.update(observed_at=SESSION + "T21:00:00Z", validated_at=SESSION + "T21:00:00Z", revision_number=2)
        new.update(observed_at=SESSION + "T21:10:00Z", validated_at=SESSION + "T21:10:00Z", coverage_kind="FULL")
        for revision in (1, 2):
            new["revision_number"] = revision
            self.check_blocked("etf_revision_not_advancing")
        new["revision_number"] = 3
        out = self.read()
        self.assertEqual(out["status"], "ADMITTED_RESEARCH_ONLY", out)
        self.assertEqual(out["result"]["latest_snapshots"]["SYN_ETF"]["revision_number"], 3)

    def test_alternate_iso_date_cannot_hide_revision_regression(self):
        old, new = self.parts["etf_snapshots"]
        old.update(holdings_as_of=SESSION, observed_at=SESSION + "T21:00:00Z",
                   validated_at=SESSION + "T21:00:00Z", revision_number=2)
        new.update(observed_at=SESSION + "T21:10:00Z", validated_at=SESSION + "T21:10:00Z",
                   revision_number=1, coverage_kind="FULL")
        for day in ("20260918", "2026-W38-5"):
            new["holdings_as_of"] = day
            self.check_blocked("noncanonical_holdings_date")

    def test_missing_or_incompatible_portfolio_scope_cannot_prove_removal(self):
        for scope in (None, "UNKNOWN", "SLEEVE", "PCF"):
            with self.subTest(scope=scope):
                self.parts["etf_snapshots"][-1]["coverage_kind"] = "FULL"
                self.parts["etf_snapshots"][-1]["portfolio_scope"] = scope
                self.check_blocked("etf_portfolio_scope_unverified")

    def test_numeric_strings_cannot_create_nonfinite_runtime_outputs(self):
        for value in ("NaN", "Infinity", "-Infinity", "1e999", True):
            with self.subTest(value=value):
                self.parts["etf_snapshots"][-1]["rows"][0]["quantity"] = value
                self.check_blocked("nonfinite_or_boolean_numeric")

    def test_etf_instruments_cannot_bypass_full_snapshot_identity_gate(self):
        original = copy.deepcopy(self.parts)
        for value in (True, 1, {}, [], None, "UNKNOWN", "TRUE", "CASH", "FUTURE"):
            with self.subTest(instrument=value):
                self.parts = copy.deepcopy(original)
                self.parts["etf_snapshots"][0]["rows"][0].update(instrument=value, identity_verified=False)
                self.check_blocked("etf_instrument_not_supported")
        for key in ("issuer_id", "ticker"):
            self.parts = copy.deepcopy(original)
            self.parts["etf_snapshots"][0]["rows"][0][key] = True
            self.check_blocked("invalid_source_identity")
        self.parts = copy.deepcopy(original)
        self.parts["etf_snapshots"][0]["revision_id"] = True
        self.check_blocked("invalid_source_identity")
        self.parts = copy.deepcopy(original)
        self.parts["etf_snapshots"][0]["rows"][0]["identity_verified"] = False
        self.parts["etf_snapshots"][-1]["coverage_kind"] = "FULL"
        out = self.read()
        self.assertEqual(out["status"], "ADMITTED_RESEARCH_ONLY", out)
        self.assertFalse(any(e["event_type"] in {"INCLUSION", "REMOVAL"}
                             for e in out["result"]["holding_events"]))

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
