"""Focused actual local C/D queue and interruption counterexamples."""
from __future__ import annotations

import copy
from datetime import datetime, timezone, timedelta
import json
import importlib
import types
from pathlib import Path
import pickle
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from tools import run_research_queue_batch as queue
from research_backend_connection_smoke import fixture, raw, CUTOFF, EXPIRY


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="research-queue-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.inputs = self.root / "inputs"
        self.inputs.mkdir()
        self.path, bundle = fixture(self.inputs / "case-a")
        # Keep the original fixture's historical clocks; explicit queue expiry
        # is runtime metadata, never invented provider availability.
        self.case = {"case_id": bundle["case_id"], "bundle_path": "case-a/manifest.json",
                     "bundle_sha256": queue.backend.digest(self.path.read_bytes()),
                     "as_of": CUTOFF, "identifiers": bundle["identifiers"],
                     "valid_through": EXPIRY, "review_due_at": None,
                     "correction": False, "source_failure": False, "outcome_due": False}
        self.manifest = {"schema": queue.SCHEMA, "queue_id": "TEST:LOCAL", "as_of": CUTOFF,
                         "cases": [self.case], "authority": queue.backend._closed()}
        self.manifest_path = self.inputs / "queue.json"
        self.output = self.root / "research-queue-result"
        self.limits = dict(queue.LIMITS)

    def save(self):
        self.manifest_path.write_bytes(raw(self.manifest))
        return self.manifest_path

    def session(self):
        return queue.QueueSession(self.inputs, self.output, self.manifest["queue_id"], self.limits)

    def run_one(self):
        session = self.session()
        report = session.run(self.save())
        self.assertEqual(report["rows"][0]["status"], "RAN_LOCAL_RESEARCH")
        self.assertEqual(report["rows"][0]["result_status"], "BLOCKED")
        return session, report

    def test_missing_case_does_not_stop_actual_independent_c_d(self):
        missing = copy.deepcopy(self.case)
        missing.update(case_id="MISSING", bundle_path="missing/manifest.json")
        self.manifest["cases"].insert(0, missing)
        result = self.session().run(self.save())
        self.assertEqual([x["status"] for x in result["rows"]],
                         ["INPUT_BLOCKED", "RAN_LOCAL_RESEARCH"])
        self.assertTrue(result["local_progress_acceptance"]["readback_verified"])
        self.assertFalse(any(result["authority"].values()))
        self.assertIsNone(result["validated_er"])
        self.assertFalse(result["A5_eligible_input"])

    def test_live_return_only_unchanged_reuse(self):
        session, first = self.run_one()
        second = session.run(self.save())
        self.assertEqual(second["rows"][0]["status"], "SKIP_UNCHANGED")
        self.assertEqual(second["attempts_reserved"], first["attempts_reserved"])
        self.assertEqual(second["input_bytes_reserved"], first["input_bytes_reserved"])
        publication = first["rows"][0]["publication"]
        receipt = json.loads((Path(publication["directory"]) / "receipt.json").read_bytes())
        self.assertEqual(receipt["status"], "UNACCEPTED")

    def test_expiry_due_correction_source_failure_and_outcome_never_skip(self):
        session, _ = self.run_one()
        for key, value in [("valid_through", CUTOFF), ("review_due_at", CUTOFF),
                           ("correction", True), ("source_failure", True), ("outcome_due", True)]:
            original = self.case[key]
            self.case[key] = value
            with self.subTest(key=key), patch.object(queue.backend, "run_bundle", side_effect=AssertionError):
                report = session.run(self.save())
                self.assertEqual(report["rows"][0]["status"], "REVIEW_DUE")
            self.case[key] = original

    def test_hash_and_identity_refusal(self):
        self.case["bundle_sha256"] = "0" * 64
        session = self.session()
        self.assertEqual(session.run(self.save())["rows"][0]["reason"], "BUNDLE_HASH_MISMATCH")
        self.case["bundle_sha256"] = queue.backend.digest(self.path.read_bytes())
        self.case["identifiers"]["issuer_id"] = "CIK:OTHER"
        self.assertEqual(session.run(self.save())["rows"][0]["reason"],
                         "BUNDLE_IDENTITY_OR_CLOCK_MISMATCH")
        self.assertEqual(len(session.reservations), 0)

    def test_late_traversal_refuses_entire_batch_before_any_case_runs(self):
        second = copy.deepcopy(self.case)
        second.update(case_id="BAD", bundle_path="../outside.json")
        self.manifest["cases"].append(second)
        session = self.session()
        with patch.object(queue.backend, "run_bundle", side_effect=AssertionError), \
                self.assertRaisesRegex(queue.Error, "TRAVERSAL"):
            session.run(self.save())
        self.assertEqual(session.reservations, {})

    def test_nested_bundle_traversal_is_batch_security_refusal(self):
        bundle = json.loads(self.path.read_bytes())
        bundle["inputs"]["events"]["path"] = "../outside"
        self.path.write_bytes(raw(bundle))
        self.case["bundle_sha256"] = queue.backend.digest(self.path.read_bytes())
        with self.assertRaisesRegex(queue.Error, "TRAVERSAL"):
            self.session().run(self.save())

    def test_authority_and_limits_fail_closed(self):
        self.manifest["authority"]["orders"] = True
        with self.assertRaisesRegex(queue.Error, "AUTHORITY"):
            self.session().run(self.save())
        for limit in queue.LIMITS:
            bad = dict(queue.LIMITS)
            bad[limit] += 1
            with self.subTest(limit=limit), self.assertRaisesRegex(queue.Error, "LIMITS"):
                queue.QueueSession(self.inputs, self.root / ("research-queue-" + limit), "X", bad)

    def test_no_disk_rehydration_or_serialized_session(self):
        session, _ = self.run_one()
        with self.assertRaises(TypeError):
            pickle.dumps(session)
        with self.assertRaisesRegex(queue.Error, "OWNER_RECOVERY"):
            self.session()
        session.proofs.clear()  # Lost actual return cannot be rebuilt from disk.
        report = session.run(self.save())
        self.assertEqual(report["rows"][0]["status"], "REVIEW_DUE")
        self.assertEqual(report["rows"][0]["reason"], "UNRESOLVED_PRIOR_INTENT")

    def test_accepted_bytes_tampering_prevents_skip(self):
        session, first = self.run_one()
        output = Path(first["rows"][0]["publication"]["directory"])
        (output / "result.json").write_bytes(b"{}")
        report = session.run(self.save())
        self.assertEqual(report["rows"][0]["status"], "REVIEW_DUE")
        self.assertEqual(report["rows"][0]["reason"], "ACCEPTED_BYTES_CHANGED")

    def test_interrupted_downstream_keeps_intent_and_no_retry(self):
        session = self.session()
        publish = queue._publish
        def interrupted(parent, name, value):
            result = publish(parent, name, value)
            if name.startswith("intent-"):
                raise OSError("interrupted after durable intent, before downstream")
            return result
        with patch.object(queue, "_publish", side_effect=interrupted), self.assertRaises(OSError):
            session.run(self.save())
        self.assertEqual(len(list(self.output.glob("intent-*"))), 1)
        self.assertEqual(len(session.reservations), 1)
        self.assertGreater(session.used_bytes, 0)
        with self.assertRaisesRegex(queue.Error, "NOT_LIVE"):
            session.run(self.save())

    def test_progress_failure_cannot_mint_acceptance(self):
        session = self.session()
        original = queue._publish
        def publish(parent, name, value):
            if name.startswith("progress-"):
                raise queue.Error("INJECTED_PROGRESS_READBACK_FAILURE")
            return original(parent, name, value)
        with patch.object(queue, "_publish", side_effect=publish), self.assertRaises(queue.Error):
            session.run(self.save())
        self.assertFalse(session.proofs)
        self.assertEqual(len(session.reservations), 1)
        self.assertEqual(len(list(self.output.glob("research-*"))), 1)

    def test_cumulative_attempt_and_input_caps_never_refund(self):
        self.limits["max_input_bytes"] = 1
        session = self.session()
        result = session.run(self.save())
        self.assertEqual(result["rows"][0]["reason"], "QUEUE_CUMULATIVE_BUDGET")
        self.assertEqual(session.used_bytes, 0)
        with self.assertRaises(TypeError):
            session.limits["max_input_bytes"] = queue.MAX_INPUT_BYTES
        self.output = self.root / "research-queue-separate-attempt-cap"
        self.limits = dict(queue.LIMITS)
        self.limits["max_attempts"] = 1
        session = self.session()
        first = session.run(self.save())
        self.assertEqual(first["rows"][0]["status"], "RAN_LOCAL_RESEARCH")
        bundle = json.loads(self.path.read_bytes())
        bundle["code_sha"] = "f" * 40  # Explicit changed metadata, not authenticated HEAD.
        self.path.write_bytes(raw(bundle))
        self.case["bundle_sha256"] = queue.backend.digest(self.path.read_bytes())
        result = session.run(self.save())
        self.assertEqual(result["rows"][0]["reason"], "QUEUE_CUMULATIVE_BUDGET")
        self.assertEqual(result["attempts_reserved"], 1)

    def test_time_and_progress_caps_refuse_without_dispatch(self):
        session = self.session()
        session.started -= queue.MAX_SECONDS + 1
        with self.assertRaisesRegex(queue.Error, "TIME_BUDGET"):
            session.run(self.save())
        self.assertEqual(session.reservations, {})

    def test_progress_namespace_collision_preserves_other_owners_bytes(self):
        session = self.session()
        occupied = self.output / "progress-1"
        occupied.mkdir()
        sentinel = occupied / "unrelated.txt"
        sentinel.write_bytes(b"another owner")
        with self.assertRaisesRegex(queue.Error, "PUBLICATION_EXISTS"):
            session.run(self.save())
        self.assertEqual(sentinel.read_bytes(), b"another owner")
        self.assertFalse(session.proofs)
        self.assertEqual(len(session.reservations), 1)

    def test_returned_json_cannot_edit_internal_live_proof(self):
        session, report = self.run_one()
        report["rows"][0]["publication"]["acceptance"]["state"] = "FORGED"
        second = session.run(self.save())
        self.assertEqual(second["rows"][0]["status"], "SKIP_UNCHANGED")
        self.assertEqual(second["rows"][0]["publication"]["acceptance"]["state"],
                         "LOCAL_READBACK_ACCEPTED")
        second["rows"][0]["publication"]["acceptance"]["state"] = "FORGED_AGAIN"
        third = session.run(self.save())
        self.assertEqual(third["rows"][0]["status"], "SKIP_UNCHANGED")

    def test_progress_cap_and_changed_loaded_module_do_not_reinvoke(self):
        session, _ = self.run_one()
        with patch.object(queue, "_module_stamp", return_value={"changed": -1}):
            result = session.run(self.save())
        self.assertEqual(result["rows"][0]["status"], "REVIEW_DUE")
        self.assertEqual(result["rows"][0]["reason"], "LOADED_MODULES_CHANGED")
        session.progress_count = session.limits["max_progress"]
        with self.assertRaisesRegex(queue.Error, "PROGRESS_BUDGET"):
            session.run(self.save())

    def test_expired_preflight_never_reserves_or_invokes_backend(self):
        elapsed = [0.0]
        self.limits["max_seconds"] = 1
        with patch.object(queue.time, "monotonic", side_effect=lambda: elapsed[0]):
            session = self.session()
            snapshot = queue._code_snapshot
            def slow_snapshot():
                result = snapshot()
                elapsed[0] = 1.01
                return result
            with patch.object(queue, "_code_snapshot", side_effect=slow_snapshot), \
                    patch.object(queue.backend, "run_bundle", side_effect=AssertionError), \
                    self.assertRaisesRegex(queue.Error, "TIME_BUDGET"):
                session.run(self.save())
        self.assertEqual(session.reservations, {})
        self.assertEqual(list(self.output.glob("intent-*")), [])

    def test_expired_intent_keeps_charge_without_backend_invocation(self):
        elapsed = [0.0]
        self.limits["max_seconds"] = 1
        with patch.object(queue.time, "monotonic", side_effect=lambda: elapsed[0]):
            session = self.session()
            original = queue._publish
            def slow_intent(parent, name, value):
                result = original(parent, name, value)
                if name.startswith("intent-"):
                    elapsed[0] = 1.01
                return result
            with patch.object(queue, "_publish", side_effect=slow_intent), \
                    self.assertRaisesRegex(queue.Error, "TIME_BUDGET"):
                session.run(self.save())
        self.assertEqual(len(session.reservations), 1)
        self.assertEqual(len(list(self.output.glob("intent-*"))), 1)
        self.assertGreater(session.used_bytes, 0)

    def test_wall_clock_expiry_crossing_preflight_cannot_skip(self):
        moment = [datetime.fromisoformat(CUTOFF.replace("Z", "+00:00"))]
        class Clock:
            @staticmethod
            def now(tz):
                return moment[0].astimezone(tz)
        self.case["valid_through"] = (moment[0] + timedelta(seconds=1)).isoformat()
        with patch.object(queue, "datetime", Clock):
            session, _ = self.run_one()
            original = queue._code_snapshot
            def slow_snapshot():
                result = original()
                moment[0] += timedelta(seconds=2)
                return result
            with patch.object(queue, "_code_snapshot", side_effect=slow_snapshot), \
                    patch.object(queue.backend, "run_bundle", side_effect=AssertionError):
                result = session.run(self.save())
        self.assertEqual(result["rows"][0]["status"], "REVIEW_DUE")
        self.assertEqual(result["rows"][0]["reason"], "CLOCK_EXPIRED_DURING_PREFLIGHT")
        self.assertEqual(len(session.reservations), 1)

    def test_cli_has_one_shot_explicit_paths_and_refuses_existing_root(self):
        command = [sys.executable, "-B", str(ROOT / "tools/run_research_queue_batch.py"),
                   "--manifest", str(self.save()), "--input-root", str(self.inputs),
                   "--output-dir", str(self.output), "--queue-id", self.manifest["queue_id"]]
        first = subprocess.run(command, capture_output=True, timeout=60)
        self.assertEqual(first.returncode, 0, first.stderr.decode(errors="replace"))
        self.assertEqual(json.loads(first.stdout)["rows"][0]["status"], "RAN_LOCAL_RESEARCH")
        second = subprocess.run(command, capture_output=True, timeout=60)
        self.assertEqual(second.returncode, 2)
        self.assertEqual(json.loads(second.stdout)["status"], "BLOCKED")

    def test_full_tree_ignored_files_do_not_consume_code_inventory(self):
        code = self.root / "consumer.py"
        code.write_bytes(b"def value():\n return 1\n")
        names = ["ignored-" + str(i) + ".csv" for i in range(12000)] + [code.name]
        with patch.object(queue, "ROOT", self.root), \
                patch.object(queue.os, "walk", return_value=[(str(self.root), [], names)]):
            self.assertEqual(len(queue._code_snapshot()["files_sha256"]), 64)
        with patch.object(queue, "ROOT", self.root), \
                patch.object(queue.os, "walk", return_value=[(str(self.root), [], names * 3)]), \
                self.assertRaisesRegex(queue.Error, "TRAVERSAL_BUDGET"):
            queue._code_snapshot()
        selected = ["code" + str(i) + ".py" for i in range(8193)]
        with patch.object(queue, "ROOT", self.root), \
                patch.object(queue.os, "walk", return_value=[(str(self.root), [], selected)]), \
                patch.object(queue.backend, "_read", return_value=b""), \
                self.assertRaisesRegex(queue.Error, "INVENTORY_BUDGET"):
            queue._code_snapshot()

    def test_cached_code_patch_defaults_and_reload_are_bound(self):
        name = "_queue_runtime_consumer"
        source = self.root / (name + ".py")
        original = b"LIMIT = 1\ndef value(x=1):\n return x + LIMIT\n"
        source.write_bytes(original)
        module = types.ModuleType(name)
        module.__file__ = str(source)
        module.__package__ = ""
        exec(compile(original, str(source), "exec", dont_inherit=True), vars(module))
        with patch.dict(sys.modules, {name: module}), patch.object(queue, "ROOT", self.root):
            first = queue._module_stamp()
            source.write_bytes(original.replace(b"return x + LIMIT", b"return x - LIMIT"))
            self.assertEqual(module.value(), 2)  # Cached old implementation actually survives.
            with self.assertRaisesRegex(queue.Error, "SOURCE_CODE_MISMATCH"):
                queue._module_stamp()
            source.write_bytes(original)
            keep = module.value
            module.value = lambda x=1: -1
            with self.assertRaisesRegex(queue.Error, "SOURCE_CODE_MISMATCH"):
                queue._module_stamp()
            module.value = keep
            module.value.__defaults__ = (5,)
            self.assertNotEqual(queue._module_stamp(), first)
            module.value.__defaults__ = (1,)
            source.write_bytes(original.replace(b"LIMIT = 1", b"LIMIT = 2"))
            with self.assertRaisesRegex(queue.Error, "SOURCE_CONSTANT_MISMATCH"):
                queue._module_stamp()
            source.write_bytes(original)
            old_id = id(module)
            exec(compile(original, str(source), "exec", dont_inherit=True), vars(module))  # Reload same object.
            self.assertEqual(id(module), old_id)
            self.assertNotEqual(queue._module_stamp(), first)

    def test_batch_boundary_expires_earlier_case_before_proof(self):
        instant = [datetime.fromisoformat(CUTOFF.replace("Z", "+00:00"))]
        class Clock:
            @staticmethod
            def now(tz):
                return instant[0].astimezone(tz)
        self.case["review_due_at"] = (instant[0] + timedelta(seconds=1)).isoformat()
        second_path, second_bundle = fixture(self.inputs / "case-b")
        second_bundle["case_id"] = "SYNTHETIC:B:0"
        second_path.write_bytes(raw(second_bundle))
        second = copy.deepcopy(self.case)
        second.update(case_id=second_bundle["case_id"], bundle_path="case-b/manifest.json",
                      bundle_sha256=queue.backend.digest(second_path.read_bytes()), review_due_at=None)
        self.manifest["cases"].append(second)
        original = queue._publish
        intents = []
        def publication(parent, name, value):
            result = original(parent, name, value)
            if name.startswith("intent-"):
                intents.append(name)
                if len(intents) == 2:
                    instant[0] += timedelta(seconds=2)
            return result
        with patch.object(queue, "datetime", Clock), patch.object(queue, "_publish", side_effect=publication):
            session = self.session()
            result = session.run(self.save())
        self.assertEqual([r["status"] for r in result["rows"]], ["REVIEW_DUE", "RAN_LOCAL_RESEARCH"])
        self.assertEqual(len(session.proofs), 1)
        self.assertEqual(len(session.reservations), 2)
        self.assertEqual(result["rows"][0]["reason"], "CLOCK_EXPIRED_AT_BATCH_BOUNDARY")

    def test_expiry_during_progress_cannot_accept_stale_record(self):
        instant = [datetime.fromisoformat(CUTOFF.replace("Z", "+00:00"))]
        class Clock:
            @staticmethod
            def now(tz):
                return instant[0].astimezone(tz)
        self.case["valid_through"] = (instant[0] + timedelta(seconds=1)).isoformat()
        original = queue._publish
        def slow_progress(parent, name, value):
            result = original(parent, name, value)
            if name.startswith("progress-"):
                instant[0] += timedelta(seconds=2)
            return result
        with patch.object(queue, "datetime", Clock), patch.object(queue, "_publish", side_effect=slow_progress):
            session = self.session()
            result = session.run(self.save())
        self.assertEqual(result["rows"][0]["status"], "REVIEW_DUE")
        self.assertIsNone(result["local_progress_acceptance"])
        self.assertFalse(session.proofs)
        stored = json.loads((self.output / "progress-1/record.json").read_bytes())
        self.assertEqual(stored["progress_state"], "PREPARED_ONLY")
        self.assertEqual(len(list(self.output.glob("progress-*"))), 1)


if __name__ == "__main__":
    unittest.main()
