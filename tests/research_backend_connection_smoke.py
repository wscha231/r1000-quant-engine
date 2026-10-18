"""Actual C/D integration with synthetic supplied bytes, never source admission."""
from __future__ import annotations

import copy
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import run_research_backend_connection as runner
from research import a2_research_intake_v1 as intake

CUTOFF = "2026-10-18T01:00:00Z"
AVAILABLE = "2026-10-18T00:00:00Z"
EXPIRY = "2026-10-19T00:00:00Z"


def raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def original_schema_fixture_bytes(schema_bytes: bytes, expected_sha: str) -> bytes:
    # Test corpus only, matching a2_research_intake_v1_smoke.inventory(): a
    # CRLF checkout can reconstruct the known original Git blob, never rebind it.
    if runner.digest(schema_bytes) == expected_sha:
        return schema_bytes
    original = schema_bytes.replace(b"\r\n", b"\n")
    if runner.digest(original) != expected_sha:
        raise RuntimeError("Fixture requires original pinned Git schema bytes")
    return original


def fixture(bundle_root: Path):
    """Writes a reproducible fixture manifest, including original schema bytes."""
    bundle_root.mkdir()
    inputs = bundle_root / "input"
    inputs.mkdir()
    manifest = {
        "schema": runner.SCHEMA, "case_id": "SYNTHETIC:E:0", "cutoff": CUTOFF,
        "input_root": str(inputs), "identifiers": {
            "security_id": "US:S0", "issuer_id": "CIK:0", "benchmark_id": "US:SPY"},
        "inputs": {}, "artifacts": {}, "code_sha": "35b36d289dbae9104042c2158532466076844f9b",
        "code_pins": {name: runner.digest((ROOT / name).read_bytes()) for name in runner.REQUIRED_CODE},
        "config": {"synthetic_fixture": True},
    }

    def add(key, data, *, artifact=False):
        name = "artifact-" + str(len(manifest["artifacts"])) + ".bin" if artifact else key + ".json"
        (inputs / name).write_bytes(data)
        descriptor = {"path": name, "expected_sha256": runner.digest(data),
                      "available_at": AVAILABLE, "collected_at": AVAILABLE, "valid_through": EXPIRY}
        manifest["artifacts" if artifact else "inputs"][key] = descriptor

    identities = {"scope": "SUPPLIED_US_IDENTITY_ASSERTIONS", "rows": [
        {"security_id": "US:S0", "issuer_id": "CIK:0", "tickers": ["S0"], "country": "US", "currency": "USD"}]}
    event = dict(event_id="E:0", cohort_id="C:0", event_family="EARNINGS", observed_at=AVAILABLE,
                 published_at=AVAILABLE, available_at=AVAILABLE, collected_at=AVAILABLE, expires_at=EXPIRY,
                 source_graph_artifact_id=None, source_graph_sha256=None, primary_source="TELEGRAM_SECONDARY",
                 verification_level="V0", claim="Synthetic discovery fixture", verified_fact=None,
                 issuer_ids=["CIK:0"], security_ids=["US:S0"], tickers=["S0"], asset_ids=["US:S0"],
                 themes=["T0"], industry_ids=[], underlyings=[], transmission_channel="DEMAND",
                 affected_pillars=["earnings_revision_operating_acceleration"], horizon="1M", materiality="LOW",
                 invalidation="Recheck source", state="DISCOVERED", assessment_eligible=False,
                 score_contribution=0, requires_a3_refresh=False, authority=intake.closed())
    add("identities", raw(identities))
    add("events", raw({"schema_version": "a2-event-handoff-v1", "as_of": CUTOFF,
                       "events": [event], "research_only": True, "authority": intake.closed()}))
    # This underlying hold-policy call is actual; no callback/module is replaced.
    record = {"ticker": "XAAA", "alphaops_vnext_score": 1.0, "rs_benchmark_1w": -0.02,
              "rs_benchmark_3m": 0.3, "price_above_ma50": 0.0, "price_above_ma200": 1.0,
              "leader_tier": "DUAL_LEADER", "rs_sector_3m": 0.1, "industry_group_strength_score": 0.2,
              "portfolio_risk_entry_block_score": 0.1, "portfolio_stale_mega_leader_score": 0.0,
              "emerging_tenbagger_hard_reject_reason": "", "top7_standalone_blocked": False,
              "pit_evidence_blocked": False, "primary_lane": "MARKET_LEADER", "sector": "Tech",
              "industry_group": "Tech Group"}
    add("risk_request", raw({"hold_policy": {"portfolio": "main", "available_at": AVAILABLE,
        "challenger": {"record": record, "lifecycle_terminal": False}}}))
    for name, expected_sha in intake.SCHEMAS.values():
        schema_bytes = (ROOT / "research" / "control_plane" / name).read_bytes()
        schema_bytes = original_schema_fixture_bytes(schema_bytes, expected_sha)
        add("SCHEMA:" + name, schema_bytes, artifact=True)
    path = bundle_root / "manifest.json"
    path.write_bytes(raw(manifest))
    return path, manifest


class BackendConnectionTests(unittest.TestCase):
    def publication_result(self):
        result = runner._base_result()
        result.update(status="DONE", case_id="SYNTHETIC:OWNERSHIP", cutoff=CUTOFF)
        return result

    def test_success_requires_returned_acceptance_not_stored_preparation(self):
        publication = runner._publish(self.output, self.publication_result())
        stored = json.loads((self.output / "receipt.json").read_bytes())
        self.assertEqual(stored["status"], "UNACCEPTED")
        self.assertEqual(stored["publication_state"], "PREPARED_ONLY")
        self.assertEqual(stored["result_status"], "DONE")
        acceptance = publication["acceptance"]
        self.assertEqual(acceptance["state"], "LOCAL_READBACK_ACCEPTED")
        self.assertEqual(acceptance["attempt_id"], stored["attempt_id"])
        self.assertEqual(acceptance["files"], publication["files"])
        self.assertEqual(acceptance["directory_identity"]["ino"], self.output.stat().st_ino)
        self.assertEqual(runner.digest(raw(acceptance) + b"\n"), publication["acceptance_sha256"])
        self.assertTrue(publication["readback_verified"])
        for name, expected in publication["files"].items():
            self.assertEqual(runner.digest((self.output / name).read_bytes()), expected)

    def moved_publication(self, replace):
        moved = self.directory / "claimed-batch"
        original_read = runner._read
        acted = []

        def move_before_read(path, limit):
            if path == self.output / "result.json" and not acted:
                code = ("import os,pathlib,sys; os.rename(sys.argv[1],sys.argv[2]); "
                        + ("pathlib.Path(sys.argv[1]).mkdir(); "
                           "(pathlib.Path(sys.argv[1])/'competitor.txt').write_bytes(b'preserve-me')" if replace else ""))
                child = subprocess.run([sys.executable, "-B", "-c", code, str(self.output), str(moved)],
                                       capture_output=True, timeout=10)
                self.assertEqual(child.returncode, 0, child.stderr)
                acted.append(True)
                raise runner.BundleError("OUTPUT_READBACK_MISMATCH")
            return original_read(path, limit)

        with patch.object(runner, "_read", side_effect=move_before_read):
            with self.assertRaises(runner.BundleError):
                runner._publish(self.output, self.publication_result())
        self.assertEqual(acted, [True])
        stored = json.loads((moved / "receipt.json").read_bytes())
        self.assertEqual(stored["status"], "UNACCEPTED")
        self.assertEqual(stored["publication_state"], "PREPARED_ONLY")
        self.assertEqual(set(p.name for p in moved.iterdir()), {"result.json", "inputs.json", "receipt.json"})
        if replace:
            self.assertEqual((self.output / "competitor.txt").read_bytes(), b"preserve-me")
            self.assertEqual([p.name for p in self.output.iterdir()], ["competitor.txt"])
        else:
            self.assertFalse(self.output.exists())

    def test_moved_publication_preserves_competitor_and_leaves_no_stored_acceptance(self):
        self.moved_publication(replace=True)

    def test_moved_publication_without_replacement_stays_unaccepted(self):
        self.moved_publication(replace=False)

    def test_identical_competitor_bytes_cannot_substitute_directory_identity(self):
        moved = self.directory / "moved-before-final-check"
        original_read = runner._read
        replaced = []

        def copy_before_final_check(path, limit):
            if path == self.output / "receipt.json" and not replaced:
                child = subprocess.run([sys.executable, "-B", "-c",
                                        "import os,shutil,sys; os.rename(sys.argv[1],sys.argv[2]); "
                                        "shutil.copytree(sys.argv[2],sys.argv[1])", str(self.output), str(moved)],
                                       capture_output=True, timeout=10)
                self.assertEqual(child.returncode, 0, child.stderr)
                replaced.append({p.name: p.read_bytes() for p in self.output.iterdir()})
            return original_read(path, limit)

        with patch.object(runner, "_read", side_effect=copy_before_final_check):
            with self.assertRaisesRegex(runner.BundleError, "PUBLICATION_OWNERSHIP_LOST"):
                runner._publish(self.output, self.publication_result())
        self.assertEqual(len(replaced), 1)
        self.assertNotEqual(self.output.stat().st_ino, moved.stat().st_ino)
        self.assertEqual(replaced[0], {p.name: p.read_bytes() for p in self.output.iterdir()})
        self.assertEqual(json.loads((moved / "receipt.json").read_bytes())["status"], "UNACCEPTED")

    def assert_unaccepted_staging(self):
        staged = list(self.directory.glob("." + self.output.name + ".tmp-*"))
        self.assertEqual(len(staged), 1)
        self.assertEqual(json.loads((staged[0] / "receipt.json").read_bytes())["status"], "UNACCEPTED")

    @unittest.skipUnless(os.name == "posix" and hasattr(os, "mkfifo"), "requires real POSIX FIFO")
    def test_fifo_manifest_descriptor_artifact_and_code_pin_refuse_without_writer(self):
        code = r'''
import json, os, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from tools import run_research_backend_connection as r
root, role = Path(sys.argv[2]), sys.argv[3]
root.mkdir()
fifo = root / "pipe"
os.mkfifo(fifo)
if role == "manifest":
    result = r.run_bundle(fifo, root / "research-out")
    print(json.dumps(result["reasons"]))
else:
    try:
        if role == "code":
            r.ROOT = root
            pins = {}
            for index, name in enumerate(r.REQUIRED_CODE):
                path = root / name
                path.parent.mkdir(exist_ok=True)
                if index == 0:
                    os.mkfifo(path)
                else:
                    path.write_bytes(b"# fixture")
                pins[name] = r.digest(b"# fixture")
            r._verify_pins(pins)
        else:
            descriptor = dict(path="pipe", expected_sha256=r.digest(b"{}"),
                              available_at="2026-10-18T00:00:00Z", collected_at="2026-10-18T00:00:00Z",
                              valid_through="2026-10-19T00:00:00Z")
            r._descriptor(root, descriptor, r.clock("2026-10-18T01:00:00Z"), [0], parse=role != "artifact")
    except r.BundleError as error:
        print(json.dumps([str(error)]))
'''
        for role in ("manifest", "descriptor", "artifact", "code"):
            with self.subTest(role=role):
                command = [sys.executable, "-B"] + (["-O"] if sys.flags.optimize else [])
                completed = subprocess.run(command + ["-c", code, str(ROOT), str(self.directory / role), role],
                                           capture_output=True, text=True, timeout=8)
                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertEqual(json.loads(completed.stdout), ["INPUT_NOT_REGULAR"])

    @unittest.skipUnless(os.name == "posix" and hasattr(os, "mkfifo"), "requires real POSIX FIFO replacement")
    def test_file_swapped_to_fifo_before_open_is_nonblocking(self):
        code = r'''
import json, os, sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, sys.argv[1])
from tools import run_research_backend_connection as r
path = Path(sys.argv[2])
path.write_bytes(b"regular")
original = os.open
def swapped(name, flags):
    path.unlink()
    os.mkfifo(path)
    return original(name, flags)
try:
    with patch.object(r.os, "open", side_effect=swapped):
        r._read(path, 100)
except r.BundleError as error:
    print(json.dumps(str(error)))
'''
        command = [sys.executable, "-B"] + (["-O"] if sys.flags.optimize else [])
        completed = subprocess.run(command + ["-c", code, str(ROOT), str(self.directory / "swap")],
                                   capture_output=True, text=True, timeout=8)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout), "INPUT_NOT_REGULAR")

    def test_publication_race_preserves_other_process_empty_namespace(self):
        original_exists = Path.exists
        reserved = []

        def race(path):
            present = original_exists(path)
            staged = list(self.directory.glob("." + self.output.name + ".tmp-*/receipt.json"))
            if path == self.output and not present and staged and not reserved:
                child = subprocess.run([sys.executable, "-B", "-c",
                                        "import pathlib,sys; pathlib.Path(sys.argv[1]).mkdir()", str(path)],
                                       capture_output=True, timeout=10)
                self.assertEqual(child.returncode, 0, child.stderr)
                reserved.append(path.stat().st_ino)
                return False  # The existence check raced with the reservation.
            return present

        with patch.object(Path, "exists", new=race):
            result = self.run_case()
        self.assertEqual(len(reserved), 1)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertIn("OUTPUT_ALREADY_EXISTS", result["reasons"])
        self.assertIsNone(result["publication"])
        self.assertEqual(self.output.stat().st_ino, reserved[0])
        self.assertEqual(list(self.output.iterdir()), [])
        self.assert_unaccepted_staging()

    def test_unsupported_publication_platform_fails_closed(self):
        with patch.object(runner.sys, "platform", "unsupported-no-replace-platform"):
            result = runner._base_result()
            with self.assertRaisesRegex(runner.BundleError, "PUBLICATION_NOREPLACE_UNAVAILABLE"):
                runner._publish(self.output, result)
        self.assertFalse(self.output.exists())
        self.assert_unaccepted_staging()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.manifest_path, self.manifest = fixture(self.directory / "bundle")
        self.output = self.directory / "research-result"

    def save(self):
        self.manifest_path.write_bytes(raw(self.manifest))

    def run_case(self):
        return runner.run_bundle(self.manifest_path, self.output)

    def test_actual_modules_research_to_risk_readback_closed_authority(self):
        result = self.run_case()
        self.assertEqual(result["calls"], ["build_research_path", "build_risk_connection"])
        research = result["stages"]["research_path"]["result"]
        risk = result["stages"]["risk_connection"]["result"]
        self.assertIsInstance(research, dict)
        self.assertIsInstance(risk, dict)
        self.assertEqual(risk["company_research"], research)
        self.assertEqual(research["stages"]["events"]["status"], "DONE")
        self.assertIn("er_preview", " ".join(str(item) for item in research["calls"]))
        self.assertEqual(risk["stages"]["challenger"]["status"], "DIAGNOSTIC_ONLY")
        self.assertTrue(risk["call_trace"])
        self.assertIsNone(result["validated_er"])
        self.assertFalse(result["A5_eligible_input"])
        self.assertTrue(all(value is False for value in result["authority"].values()))
        self.assertTrue(result["synthetic_fixture"])
        self.assertTrue(result["publication"]["readback_verified"])
        for name, sha in result["publication"]["files"].items():
            self.assertEqual(runner.digest((self.output / name).read_bytes()), sha)
        stored = json.loads((self.output / "result.json").read_bytes())
        self.assertEqual(stored["manifest_sha256"], runner.digest(self.manifest_path.read_bytes()))
        self.assertEqual(stored["code_file_sha256"], self.manifest["code_pins"])
        self.assertEqual(stored["runtime_dependency_status"], "SOURCE_BYTES_HASHED_NOT_COMPLETE_CLOSURE")
        for name in runner.DEPENDENCY_SOURCES:
            self.assertEqual(stored["runtime_dependency_file_sha256"][name], runner.digest((ROOT / name).read_bytes()))

    def test_crlf_checkout_fixture_requires_exact_original_schema(self):
        original_read = Path.read_bytes
        checkout_bytes = {}
        for name, expected_sha in intake.SCHEMAS.values():
            path = ROOT / "research" / "control_plane" / name
            original = original_schema_fixture_bytes(original_read(path), expected_sha)
            checkout_bytes[path] = original.replace(b"\n", b"\r\n")
            self.assertNotEqual(runner.digest(checkout_bytes[path]), expected_sha)

        def checkout_read(path):
            return checkout_bytes[path] if path in checkout_bytes else original_read(path)

        # Reproduce a real CRLF checkout at the fixture file-read boundary;
        # the downstream modules and runtime file reads remain actual.
        with patch.object(Path, "read_bytes", new=checkout_read):
            manifest_path, manifest = fixture(self.directory / "crlf-bundle")
        result = runner.run_bundle(manifest_path, self.directory / "research-crlf")
        self.assertEqual(result["stages"]["research_path"]["result"]["stages"]["events"]["status"], "DONE")
        for name, expected_sha in intake.SCHEMAS.values():
            descriptor = manifest["artifacts"]["SCHEMA:" + name]
            self.assertEqual(descriptor["expected_sha256"], expected_sha)
            self.assertEqual(runner.digest((Path(manifest["input_root"]) / descriptor["path"]).read_bytes()), expected_sha)

        # Normalizing line endings cannot accept any other original mutation.
        first = next(iter(checkout_bytes))
        checkout_bytes[first] += b" "
        with patch.object(Path, "read_bytes", new=checkout_read):
            with self.assertRaises(RuntimeError):
                fixture(self.directory / "tampered-schema-bundle")

    def test_missing_input_remains_blocked_without_fixture_substitution(self):
        descriptor = self.manifest["inputs"]["events"]
        (Path(self.manifest["input_root"]) / descriptor["path"]).unlink()
        result = self.run_case()
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["reasons"], ["INPUT_UNAVAILABLE"])
        self.assertEqual(result["calls"], [])
        self.assertTrue(all(stage["status"] == "NOT_RUN" for stage in result["stages"].values()))
        self.assertTrue((self.output / "result.json").exists())

    def test_missing_optional_stages_are_preserved(self):
        self.manifest["inputs"] = {}
        self.manifest["artifacts"] = {}
        self.save()
        result = self.run_case()
        self.assertEqual(result["calls"], ["build_research_path", "build_risk_connection"])
        research = result["stages"]["research_path"]["result"]
        self.assertEqual(research["stages"]["events"]["status"], "NOT_RUN")
        self.assertEqual(research["stages"]["er"]["status"], "BLOCKED")
        self.assertIsNone(research["validated_er"])

    def test_tamper_and_code_tamper_refuse_before_calls(self):
        for target in ("input", "code"):
            with self.subTest(target=target):
                manifest = copy.deepcopy(self.manifest)
                if target == "input":
                    manifest["inputs"]["events"]["expected_sha256"] = "0" * 64
                    expected = "INPUT_HASH_MISMATCH"
                else:
                    manifest["code_pins"][runner.REQUIRED_CODE[0]] = "0" * 64
                    expected = "CODE_HASH_MISMATCH"
                self.manifest_path.write_bytes(raw(manifest))
                result = runner.run_bundle(self.manifest_path, self.directory / ("research-" + target))
                self.assertIn(expected, result["reasons"])
                self.assertEqual(result["calls"], [])

    def test_stale_future_and_repeated_invocation_recheck(self):
        original = self.run_case()
        self.assertIsNotNone(original["publication"])
        for name, value, expected in (
            ("valid_through", CUTOFF, "INPUT_STALE"),
            ("collected_at", EXPIRY, "INPUT_FUTURE_OR_TIME_ORDER"),
        ):
            with self.subTest(name=name):
                manifest = copy.deepcopy(self.manifest)
                manifest["inputs"]["events"][name] = value
                self.manifest_path.write_bytes(raw(manifest))
                result = runner.run_bundle(self.manifest_path, self.directory / ("research-" + name))
                self.assertIn(expected, result["reasons"])
                self.assertEqual(result["calls"], [])
                self.assertIsNone(result["validated_er"])

    def test_path_traversal_and_input_output_alias(self):
        self.manifest["inputs"]["events"]["path"] = "../events.json"
        self.save()
        result = self.run_case()
        self.assertIn("PATH_TRAVERSAL_REFUSED", result["reasons"])
        alias = Path(self.manifest["input_root"]) / "research-overwrite"
        result = runner.run_bundle(self.manifest_path, alias)
        self.assertIn("INPUT_OUTPUT_ALIAS", result["reasons"])
        self.assertFalse(alias.exists())

    def test_actual_directory_link_is_refused(self):
        target = Path(self.manifest["input_root"])
        link = self.directory / "input-link"
        try:
            link.symlink_to(target, target_is_directory=True)
        except OSError:
            if os.name != "nt":
                raise
            # A Windows directory junction needs no developer-mode privilege.
            created = subprocess.run(["cmd", "/d", "/c", "mklink", "/J", str(link), str(target)],
                                     capture_output=True, timeout=10)
            self.assertEqual(created.returncode, 0)
        def remove_link():
            if link.is_symlink():
                link.unlink()
            elif link.exists():
                link.rmdir()
        self.addCleanup(remove_link)
        self.manifest["input_root"] = str(link)
        self.save()
        result = self.run_case()
        self.assertIn("PATH_LINK_REFUSED", result["reasons"])
        self.assertEqual(result["calls"], [])
        self.assertTrue(target.is_dir())

    def test_failed_invocation_never_returns_previous_summary(self):
        first = self.run_case()
        before = {name: (self.output / name).read_bytes() for name in first["publication"]["files"]}
        self.manifest["inputs"]["events"]["expected_sha256"] = "0" * 64
        self.save()
        retry = self.run_case()
        self.assertEqual(retry["reasons"], ["OUTPUT_ALREADY_EXISTS"])
        self.assertIsNone(retry["publication"])
        self.assertEqual(retry["calls"], [])
        self.assertTrue(all(stage["result"] is None for stage in retry["stages"].values()))
        self.assertEqual(before, {name: (self.output / name).read_bytes() for name in before})

    def test_strict_json_and_size_gate(self):
        cases = (b'{"duplicate":0,"duplicate":1}', b'{"x":NaN}', b'{"x":1e9999}',
                 b'[' * 33 + b'0' + b']' * 33, b' ' * (runner.MAX_FILE + 1))
        descriptor = self.manifest["inputs"]["events"]
        path = Path(self.manifest["input_root"]) / descriptor["path"]
        for index, data in enumerate(cases):
            with self.subTest(index=index):
                path.write_bytes(data)
                descriptor["expected_sha256"] = runner.digest(data)
                self.save()
                result = runner.run_bundle(self.manifest_path, self.directory / ("research-json-" + str(index)))
                self.assertEqual(result["status"], "BLOCKED")
                self.assertEqual(result["calls"], [])

    def test_post_publish_readback_failure_leaves_no_accepted_receipt(self):
        original_read = runner._read

        def failing_read(path, limit):
            if path == self.output / "result.json":
                return b"tampered"
            return original_read(path, limit)

        with patch.object(runner, "_read", side_effect=failing_read):
            result = self.run_case()
        self.assertEqual(result["status"], "BLOCKED")
        self.assertIn("OUTPUT_READBACK_MISMATCH", result["reasons"])
        self.assertIsNone(result["publication"])
        self.assertTrue(self.output.exists())
        stored = json.loads((self.output / "receipt.json").read_bytes())
        self.assertEqual(stored["status"], "UNACCEPTED")
        self.assertEqual(stored["publication_state"], "PREPARED_ONLY")

    def test_cli_help_and_actual_fixture_process(self):
        optimization = ["-O"] if sys.flags.optimize else []
        command = [sys.executable, "-B", *optimization, str(ROOT / runner.REQUIRED_CODE[0])]
        help_result = subprocess.run(command + ["--help"], capture_output=True, text=True, timeout=30)
        self.assertEqual(help_result.returncode, 0, help_result.stderr)
        self.assertIn("--manifest", help_result.stdout)
        run = subprocess.run(command + ["--manifest", str(self.manifest_path), "--output-dir", str(self.output)],
                             capture_output=True, text=True, timeout=30)
        self.assertIn(run.returncode, (0, 2), run.stderr)
        self.assertEqual(run.stderr, "")
        result = json.loads(run.stdout)
        self.assertEqual(result["calls"], ["build_research_path", "build_risk_connection"])
        self.assertTrue(result["publication"]["readback_verified"])


class PriceChildHookTests(unittest.TestCase):
    def test_missing_empty_and_import_failing_child_refuse(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / "tests/research_price_incremental_plan_smoke.py"
            path.parent.mkdir()
            with patch.dict(load_tests.__globals__, ROOT=root), contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(FileNotFoundError):
                    load_tests(unittest.defaultTestLoader, unittest.TestSuite(), None)
                path.write_text("# no test cases\n", encoding="utf-8")
                with self.assertRaisesRegex(RuntimeError, "PRICE_CHILD_SUITE_EMPTY"):
                    load_tests(unittest.defaultTestLoader, unittest.TestSuite(), None)
                path.write_text("raise RuntimeError('PRICE_CHILD_IMPORT_FAILED')\n", encoding="utf-8")
                with self.assertRaisesRegex(RuntimeError, "PRICE_CHILD_IMPORT_FAILED"):
                    load_tests(unittest.defaultTestLoader, unittest.TestSuite(), None)

    def test_failed_child_fails_caller_and_preserves_standard_tests(self):
        seen = []
        standard = unittest.TestSuite([unittest.FunctionTestCase(lambda: seen.append("standard"))])
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / "tests/research_price_incremental_plan_smoke.py"
            path.parent.mkdir()
            path.write_text("import unittest\nclass FailedChild(unittest.TestCase):\n"
                            "    def test_probe(self): self.fail('PRICE_CHILD_FAILURE')\n", encoding="utf-8")
            with patch.dict(load_tests.__globals__, ROOT=root), contextlib.redirect_stdout(io.StringIO()):
                suite = load_tests(unittest.defaultTestLoader, standard, None)
            result = unittest.TextTestRunner(stream=io.StringIO()).run(suite)
        self.assertEqual(seen, ["standard"])
        self.assertEqual(result.testsRun, 2)
        self.assertEqual(len(result.failures), 1)
        self.assertFalse(result.wasSuccessful())


def load_tests(loader, standard_tests, pattern):
    # Extend the existing registered entry; retain its complete original suite.
    path = ROOT / "tests/research_price_incremental_plan_smoke.py"
    spec = importlib.util.spec_from_file_location("research_price_incremental_plan_registered", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    child_tests = loader.loadTestsFromModule(module)
    count = child_tests.countTestCases()
    if count == 0:
        raise RuntimeError("PRICE_CHILD_SUITE_EMPTY")
    standard_tests.addTests(child_tests)
    print(f"research_price_incremental_plan_smoke: {count} child tests", flush=True)
    return standard_tests


if __name__ == "__main__":
    unittest.main()
