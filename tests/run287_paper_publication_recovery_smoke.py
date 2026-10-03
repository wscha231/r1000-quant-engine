#!/usr/bin/env python3
"""Publication-only contract checks; all API/authority inputs are synthetic."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import unittest
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tools import prepare_run287_paper_publication_recovery as recovery
import yaml
from tests.workflow_artifact_smoke import bash_executable

NOW = datetime(2026, 10, 3, 1, 0, tzinfo=timezone.utc)
PUBLISHER_SHA = "f" * 40
MOCK_RUN = 999999

# Narrow context-availability regression, not a complete Actions parser.
# https://docs.github.com/en/actions/reference/workflows-and-actions/contexts#context-availability
JOB_ENV_CONTEXTS = {"github", "needs", "strategy", "matrix", "vars", "secrets", "inputs"}
NAMED_CONTEXTS = JOB_ENV_CONTEXTS | {"env", "job", "jobs", "runner", "steps"}
RECOVERY_PATHS = {
    "RECOVERY_INPUTS": "run287-publication-inputs",
    "RECOVERY_API": "run287-publication-api",
    "RECOVERY_BUNDLE": "run287-publication-bundle",
}


def job_env_context_violations(workflow: dict) -> list:
    violations = []
    for job_id, job in workflow["jobs"].items():
        for name, value in job.get("env", {}).items():
            for expression in re.findall(r"\$\{\{(.*?)\}\}", str(value), flags=re.S):
                # Ignore quoted strings and property names such as github.runner.
                unquoted = re.sub(r"'(?:[^']|'')*'", "", expression)
                tokens = {v.lower() for v in re.findall(r"(?<![\w.])\b([A-Za-z_][A-Za-z0-9_-]*)\b", unquoted)}
                roots = {v.lower() for v in re.findall(r"(?<![\w.])([A-Za-z_][A-Za-z0-9_-]*)\s*(?=[.\[])", unquoted)}
                invalid = ((tokens & NAMED_CONTEXTS) | roots) - JOB_ENV_CONTEXTS
                if invalid:
                    violations.append((job_id, name, sorted(invalid)))
    return violations


def recovery_workflow() -> dict:
    return yaml.safe_load((ROOT / recovery.WORKFLOW_PATH).read_text(encoding="utf-8"))


def recovery_initializer() -> str:
    return next(step["run"] for step in recovery_workflow()["jobs"]["publication_recovery"]["steps"]
                if step.get("id") == "initialize_recovery_paths")


def dump(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def owner() -> dict:
    return {"login": recovery.scope.OWNER_LOGIN, "id": recovery.scope.OWNER_ID,
            "node_id": recovery.scope.OWNER_NODE_ID, "type": "User"}


def repository() -> dict:
    return {"full_name": recovery.scope.REPOSITORY, "id": recovery.scope.REPOSITORY_ID,
            "node_id": recovery.scope.REPOSITORY_NODE_ID, "default_branch": "master", "owner": owner()}


def publisher_fixture(root: Path) -> dict:
    data = {
        "repository": repository(),
        "master": {"ref": "refs/heads/master", "object": {"sha": PUBLISHER_SHA}},
        "event": {"inputs": {"expected_master_sha": PUBLISHER_SHA,
                  "allow_publication_recovery": "true", "save_continuity_cache": "false"}},
        "publisher_run": {"id": MOCK_RUN, "run_attempt": 1, "event": "workflow_dispatch",
                "path": recovery.WORKFLOW_PATH, "head_branch": "master", "head_sha": PUBLISHER_SHA,
                "status": "in_progress", "conclusion": None, "actor": owner(), "triggering_actor": owner(),
                "repository": repository(), "head_repository": repository(),
                "created_at": (NOW - timedelta(minutes=2)).isoformat(),
                "run_started_at": (NOW - timedelta(minutes=1)).isoformat()},
        "writers_in_progress": {"total_count": 1, "workflow_runs": [{"id": MOCK_RUN}]},
        "writers_queued": {"total_count": 0, "workflow_runs": []},
        "writers_waiting": {"total_count": 0, "workflow_runs": []},
        "prior_recoveries": {"total_count": 1, "workflow_runs": [{"id": MOCK_RUN}], "artifacts": {}},
    }
    for name, payload in data.items():
        dump(root / (name + ".json"), payload)
    return data


def prior_recovery(run_id: int = 123, *, conclusion: str = "cancelled", run_attempt: int = 1) -> dict:
    return {"id": run_id, "run_attempt": run_attempt, "status": "completed", "conclusion": conclusion}


def prior_jobs(run_id: int = 123, *, step_conclusion: str = "skipped",
               duplicate: bool = False, attempts: tuple[int, ...] = (1,)) -> dict:
    jobs = [{"id": 1000 * attempt + run_id, "run_id": run_id, "run_attempt": attempt,
             "name": "publication_recovery", "status": "completed", "conclusion": "failure",
             "steps": [{"name": recovery.ACCEPTED_ARTIFACT_STEP, "conclusion": step_conclusion,
                        "number": 20, "status": "completed"}]} for attempt in attempts]
    if duplicate:
        jobs.extend(prior_jobs(run_id, step_conclusion="cancelled", attempts=(2,))["jobs"])
    return {"total_count": len(jobs), "jobs": jobs}


def install_prior_recovery(root: Path, *, run_id: int = 123, run_conclusion: str = "cancelled",
                           step_conclusion: str = "skipped", artifacts: list | None = None,
                           jobs_payload: dict | None = None, run_attempt: int = 1) -> dict:
    current = json.loads((root / "prior_recoveries.json").read_text(encoding="utf-8"))
    previous = prior_recovery(run_id, conclusion=run_conclusion, run_attempt=run_attempt)
    current["workflow_runs"] = [current["workflow_runs"][0], previous]
    current["total_count"] = len(current["workflow_runs"])
    current.setdefault("artifacts", {})[str(run_id)] = {
        "total_count": len(artifacts or []), "artifacts": artifacts or [],
    }
    if jobs_payload is not None:
        current.setdefault("jobs", {})[str(run_id)] = jobs_payload
    dump(root / "prior_recoveries.json", current)
    return current


class PublicationRecoveryChecks(unittest.TestCase):
    def test_job_env_context_rejects_original_runner_path_expressions(self):
        workflow = recovery_workflow()
        self.assertEqual(job_env_context_violations(workflow), [])
        original = copy.deepcopy(workflow)
        for name, suffix in RECOVERY_PATHS.items():
            original["jobs"]["publication_recovery"]["env"][name] = "${{ runner.temp }}/" + suffix
        self.assertEqual(job_env_context_violations(original), [
            ("publication_recovery", name, ["runner"]) for name in RECOVERY_PATHS])
        for expression in ("${{ Runner['temp'] }}", "${{ toJSON(runner) }}", "${{ env.OTHER }}"):
            with self.subTest(expression=expression):
                original["jobs"]["publication_recovery"]["env"] = {"INVALID": expression}
                self.assertTrue(job_env_context_violations(original))
        original["jobs"]["publication_recovery"]["env"] = {"VALID": "${{ format('runner.temp', github.runner) }}"}
        self.assertEqual(job_env_context_violations(original), [])

    def test_initializer_precedes_collect_authorize_and_all_path_consumers(self):
        job = recovery_workflow()["jobs"]["publication_recovery"]
        self.assertTrue(set(RECOVERY_PATHS).isdisjoint(job["env"]))
        initializers = [(i, step) for i, step in enumerate(job["steps"])
                        if step.get("id") == "initialize_recovery_paths"]
        self.assertEqual(len(initializers), 1)
        index, initializer = initializers[0]
        self.assertNotIn("if", initializer)
        self.assertNotRegex(initializer["run"], r"\$\{?RECOVERY_(INPUTS|API|BUNDLE)\b")
        consumers = 0
        for i, step in enumerate(job["steps"]):
            if i == index:
                continue
            if re.search(r"\$\{?RECOVERY_(INPUTS|API|BUNDLE)\b|\$\{\{\s*env\.RECOVERY_(INPUTS|API|BUNDLE)\b", json.dumps(step)):
                consumers += 1
                self.assertGreater(i, index, step["name"])
            if re.search(r"publication_recovery\.py (collect|authorize)\b", step.get("run", "")):
                self.assertGreater(i, index, step["name"])
        self.assertGreater(consumers, 0)

    def test_initializer_hands_exact_plain_and_space_paths_to_subsequent_step(self):
        for dirname in ("runner-temp", "runner temp with spaces"):
            with self.subTest(dirname=dirname), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                runner_temp = root / dirname
                runner_temp.mkdir()
                sentinel = runner_temp / "unrelated-file"
                sentinel.write_bytes(b"preserved")
                github_env = root / "github env"
                prefix = b"UNRELATED_ENV=existing env entry\n"
                github_env.write_bytes(prefix)
                env = {**os.environ, "RUNNER_TEMP": runner_temp.as_posix(), "GITHUB_ENV": github_env.as_posix(),
                       "UNRELATED_PROCESS_ENV": "existing process value", **{k: "same-step-stale-value" for k in RECOVERY_PATHS}}
                probe = "\nprintf '%s\\n' \"$RECOVERY_INPUTS\" \"$RECOVERY_API\" \"$RECOVERY_BUNDLE\" \"$UNRELATED_PROCESS_ENV\"\n"
                result = subprocess.run([bash_executable(), "--noprofile", "--norc", "-c", recovery_initializer() + probe],
                                        cwd=root, env=env, capture_output=True, text=True, encoding="utf-8")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.splitlines(), ["same-step-stale-value"] * 3 + ["existing process value"])
                self.assertTrue(github_env.read_bytes().startswith(prefix))
                emitted = dict(line.split("=", 1) for line in github_env.read_text(encoding="utf-8").splitlines())
                expected = {k: runner_temp.as_posix() + "/" + suffix for k, suffix in RECOVERY_PATHS.items()}
                self.assertEqual({k: emitted[k] for k in RECOVERY_PATHS}, expected)
                subsequent = subprocess.run([sys.executable, "-B", "-X", "utf8", "-c",
                    "import json,os;print(json.dumps({k:os.environ[k] for k in " + repr(list(expected) + ["UNRELATED_ENV", "UNRELATED_PROCESS_ENV"]) + "}))"],
                    cwd=root, env={**env, **emitted}, capture_output=True, text=True, encoding="utf-8")
                self.assertEqual(subsequent.returncode, 0, subsequent.stderr)
                consumed = json.loads(subsequent.stdout)
                self.assertEqual({k: consumed[k] for k in RECOVERY_PATHS}, expected)
                self.assertEqual(consumed["UNRELATED_ENV"], "existing env entry")
                self.assertEqual(consumed["UNRELATED_PROCESS_ENV"], "existing process value")
                self.assertEqual(sentinel.read_bytes(), b"preserved")
                self.assertEqual(list(runner_temp.iterdir()), [sentinel])

    def test_initializer_missing_or_empty_runner_temp_fails_before_env_write(self):
        for value in (None, ""):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                sentinel = root / "unrelated-file"
                sentinel.write_bytes(b"preserved")
                github_env = root / "github.env"
                prefix = b"UNRELATED_ENV=keep\n"
                github_env.write_bytes(prefix)
                env = {**os.environ, "GITHUB_ENV": github_env.as_posix()}
                env.pop("RUNNER_TEMP", None)
                if value is not None:
                    env["RUNNER_TEMP"] = value
                result = subprocess.run([bash_executable(), "--noprofile", "--norc", "-c", recovery_initializer()],
                                        cwd=root, env=env, capture_output=True, text=True, encoding="utf-8")
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("RUNNER_TEMP is required", result.stderr)
                self.assertEqual(github_env.read_bytes(), prefix)
                self.assertEqual(sentinel.read_bytes(), b"preserved")
                self.assertEqual(set(root.iterdir()), {sentinel, github_env})

    def test_prior_publication_step_name_matches_current_workflow(self):
        workflow_jobs = recovery_workflow()["jobs"]
        job = workflow_jobs["publication_recovery"]
        self.assertEqual(job.get("name", "publication_recovery"), recovery.PUBLICATION_JOB_NAME)
        steps = job["steps"]
        self.assertEqual(sum(step.get("name") == recovery.ACCEPTED_ARTIFACT_STEP for step in steps), 1)

    def test_collect_records_all_attempt_prior_job_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            evidence = Path(td) / "api"
            event = Path(td) / "event.json"
            dump(event, {"inputs": {}})
            prior_run = {"id": 123}
            responses = {
                "/actions/workflows/run287_paper_publication_recovery.yml/runs?per_page=100":
                    {"total_count": 2, "workflow_runs": [prior_run, {"id": MOCK_RUN}]},
                "/actions/runs/123/artifacts?per_page=100": {"total_count": 0, "artifacts": []},
                "/actions/runs/123/jobs?filter=all&per_page=100": prior_jobs(),
            }
            seen = []

            def fake_run(command, capture_output=True, check=True):
                endpoint = command[-1].split("repos/" + recovery.scope.REPOSITORY, 1)[1]
                seen.append(endpoint)
                payload = responses.get(endpoint, {})
                return subprocess.CompletedProcess(command, 0, stdout=json.dumps(payload).encode(), stderr=b"")

            with patch.object(recovery.subprocess, "run", side_effect=fake_run), \
                 patch.object(recovery, "validate_github_compare_payload", return_value=None):
                recovery.collect(evidence, event, str(MOCK_RUN), PUBLISHER_SHA)
            observed = json.loads((evidence / "prior_recoveries.json").read_text(encoding="utf-8"))
            self.assertEqual(observed["jobs"]["123"], prior_jobs())
            self.assertIn("/actions/runs/123/jobs?filter=all&per_page=100", seen)

    def test_owner_current_master_and_explicit_cache_scope(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            data = publisher_fixture(root)
            result = recovery.validate_publisher(root, PUBLISHER_SHA, now=NOW)
            self.assertFalse(result["save_continuity_cache"])
            self.assertEqual(result["source_sha"], PUBLISHER_SHA)
            self.assertNotEqual(result["run_id"], recovery.PROFILE["producer_run"])
            data["event"]["inputs"]["save_continuity_cache"] = True
            dump(root / "event.json", data["event"])
            self.assertTrue(recovery.validate_publisher(root, PUBLISHER_SHA, now=NOW)["save_continuity_cache"])

    def test_dispatch_source_actor_attempt_and_stale_authority_fail_closed(self):
        changes = [
            ("event", lambda d: d["inputs"].update(allow_publication_recovery="false")),
            ("event", lambda d: d["inputs"].update(save_continuity_cache=1)),
            ("event", lambda d: d["inputs"].update(catchup_secret_scope_attestation_comment_id="5951667349")),
            ("master", lambda d: d["object"].update(sha="0" * 40)),
            ("publisher_run", lambda d: d.update(head_branch="foreign")),
            ("publisher_run", lambda d: d.update(run_attempt=2)),
            ("publisher_run", lambda d: d.update(id=recovery.PROFILE["producer_run"])),
            ("publisher_run", lambda d: d["actor"].update(id=1)),
            ("publisher_run", lambda d: d["triggering_actor"].update(id=1)),
            ("publisher_run", lambda d: d["head_repository"].update(id=1)),
            ("publisher_run", lambda d: d.update(created_at=(NOW - timedelta(hours=2)).isoformat())),
            ("publisher_run", lambda d: d.update(status="completed", conclusion="cancelled")),
        ]
        for name, change in changes:
            with self.subTest(name=name, change=str(change)), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                data = publisher_fixture(root)
                change(data[name])
                dump(root / (name + ".json"), data[name])
                with self.assertRaises(ValueError):
                    recovery.validate_publisher(root, PUBLISHER_SHA, now=NOW)

    def test_writer_conflict_incomplete_census_and_duplicate_publication(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            data = publisher_fixture(root)
            data["writers_queued"] = {"total_count": 1, "workflow_runs": [{"id": 123}]}
            dump(root / "writers_queued.json", data["writers_queued"])
            with self.assertRaisesRegex(ValueError, "conflicting_active_writer"):
                recovery.validate_publisher(root, PUBLISHER_SHA, now=NOW)
            publisher_fixture(root)
            dump(root / "writers_in_progress.json", {"total_count": 2, "workflow_runs": [{"id": MOCK_RUN}]})
            with self.assertRaisesRegex(ValueError, "writer_census_incomplete"):
                recovery.validate_publisher(root, PUBLISHER_SHA, now=NOW)
            publisher_fixture(root)
            dump(root / "prior_recoveries.json", {"total_count": 2, "workflow_runs": [{"id": MOCK_RUN}, {"id": 123}],
                    "artifacts": {"123": {"total_count": 1, "artifacts": [
                        {"name": "accepted-paper-catchup-2026-07-27-123", "expired": True}]}}})
            with self.assertRaisesRegex(ValueError, "already_published"):
                recovery.validate_publisher(root, PUBLISHER_SHA, now=NOW)

    def test_prior_successful_upload_blocks_after_artifact_retention_deletion(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            publisher_fixture(root)
            install_prior_recovery(root, step_conclusion="success", jobs_payload=prior_jobs(step_conclusion="success"))
            with self.assertRaisesRegex(ValueError, "already_published_requires_separate_recovery"):
                recovery.validate_publisher(root, PUBLISHER_SHA, now=NOW)

    def test_prior_prepublication_skip_allows_controlled_retry(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            publisher_fixture(root)
            install_prior_recovery(root, run_conclusion="cancelled", step_conclusion="skipped",
                                   jobs_payload=prior_jobs(step_conclusion="skipped"))
            result = recovery.validate_publisher(root, PUBLISHER_SHA, now=NOW)
            self.assertEqual(result["source_sha"], PUBLISHER_SHA)

    def test_prior_job_and_step_evidence_fail_closed(self):
        cases = [
            ("missing_jobs", None, "prior_job_census_missing"),
            ("incomplete_jobs", {"total_count": 2, "jobs": prior_jobs()["jobs"]}, "prior_job_census_incomplete"),
            ("missing_step", {"total_count": 1, "jobs": [{"id": 1123, "run_id": 123, "run_attempt": 1,
                "name": "publication_recovery", "status": "completed", "conclusion": "failure", "steps": []}]}, "prior_publication_step_missing"),
            ("cancelled_step", prior_jobs(step_conclusion="cancelled"), "prior_publication_side_effect_ambiguous"),
            ("failed_step", prior_jobs(step_conclusion="failure"), "prior_publication_side_effect_ambiguous"),
            ("mixed_attempts", prior_jobs(step_conclusion="skipped", duplicate=True), "prior_publication_side_effect_ambiguous"),
        ]
        for name, jobs_payload, error in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                publisher_fixture(root)
                install_prior_recovery(root, jobs_payload=jobs_payload, run_attempt=2 if name == "mixed_attempts" else 1)
                with self.assertRaisesRegex(ValueError, error):
                    recovery.validate_publisher(root, PUBLISHER_SHA, now=NOW)

    def test_complete_two_attempt_retry_allows_unrelated_jobs_without_shared_census(self):
        for conclusion in ("failure", "cancelled"):
            with self.subTest(conclusion=conclusion), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                publisher_fixture(root)
                jobs = prior_jobs(attempts=(2, 1))
                for job_id in (9001, 9002):
                    jobs["jobs"].append({"id": job_id, "run_id": 123, "run_attempt": 1,
                        "name": "unrelated_" + str(job_id), "status": "completed", "steps": []})
                jobs["total_count"] = len(jobs["jobs"])
                install_prior_recovery(root, run_attempt=2, run_conclusion=conclusion, jobs_payload=jobs)
                result = recovery.validate_publisher(root, PUBLISHER_SHA, now=NOW)
                self.assertEqual(result["run_id"], MOCK_RUN)

    def test_prior_attempt_and_evidence_shape_matrix_fails_closed(self):
        cases = []

        def case(name, change, *, attempts=(1, 2), run_attempt=2):
            jobs = prior_jobs(attempts=attempts)
            change(jobs)
            cases.append((name, run_attempt, jobs))

        for label, attempts in (("missing_latest", (1,)), ("missing_first", (2,)),
                                ("missing_middle", (1, 3)), ("extra_attempt", (1, 2, 3)),
                                ("duplicate_all_skipped", (1, 1, 2))):
            case(label, lambda d: None, attempts=attempts, run_attempt=3 if label == "missing_middle" else 2)
        case("duplicate_attempt_distinct_job_ids", lambda d: d["jobs"][1].update(run_attempt=1))
        case("duplicate_job_id_across_attempts", lambda d: d["jobs"][1].update(id=d["jobs"][0]["id"]))
        case("wrong_run", lambda d: d["jobs"][1].update(run_id=124))
        case("missing_publication_job", lambda d: d["jobs"][1].update(name="unrelated", steps=[]))
        case("upload_on_wrong_job", lambda d: d["jobs"][1].update(name="unrelated"))
        case("missing_upload_in_latest", lambda d: d["jobs"][1].update(steps=[]))
        case("incomplete_job", lambda d: d["jobs"][1].update(status="in_progress"))
        case("incomplete_upload", lambda d: d["jobs"][1]["steps"][0].update(status="in_progress"))
        for field in ("id", "run_id", "run_attempt"):
            for value in (None, True, False, 0, -1, "2", 2.0):
                case(f"job_{field}_{value!r}", lambda d, f=field, v=value: d["jobs"][1].update({f: v}))
        for value in (None, True, False, 0, -1, "2", 2.0):
            case(f"prior_attempt_{value!r}", lambda d: None, run_attempt=value)
            case(f"step_number_{value!r}", lambda d, v=value: d["jobs"][1]["steps"][0].update(number=v))
        for number in (20, 21):
            case(f"duplicate_upload_{number}", lambda d, n=number: d["jobs"][1]["steps"].append(
                {**d["jobs"][1]["steps"][0], "number": n}))
        case("duplicate_step_number", lambda d: d["jobs"][1]["steps"].append(
            {**d["jobs"][1]["steps"][0], "name": "Unrelated step"}))
        case("null_step", lambda d: d["jobs"][1]["steps"].append(None))
        case("missing_steps", lambda d: d["jobs"][1].pop("steps"))
        case("null_job", lambda d: d["jobs"].__setitem__(1, None))
        for name, attempt_count, jobs in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                publisher_fixture(root)
                install_prior_recovery(root, run_attempt=attempt_count, jobs_payload=jobs)
                with self.assertRaises(ValueError):
                    recovery.validate_publisher(root, PUBLISHER_SHA, now=NOW)

    def test_boolean_run_identity_cannot_alias_integer_one(self):
        for field in ("id", "run_id"):
            previous = prior_recovery(1)
            jobs = prior_jobs(1)
            if field == "id":
                previous[field] = True
            else:
                jobs["jobs"][0][field] = True
            with self.subTest(field=field), self.assertRaises(ValueError):
                recovery.prior_publication_step_state(previous, jobs)

    def test_prior_job_page_truncation_blocks_retry(self):
        jobs = prior_jobs(attempts=(1,))
        for job_id in range(9000, 9099):
            jobs["jobs"].append({"id": job_id, "run_id": 123, "run_attempt": 1,
                "name": "unrelated_" + str(job_id), "status": "completed", "steps": []})
        self.assertEqual(len(jobs["jobs"]), 100)
        for total_count in (100, 101, True, "100"):
            with self.subTest(total_count=total_count), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                publisher_fixture(root)
                jobs["total_count"] = total_count
                install_prior_recovery(root, run_attempt=2, jobs_payload=jobs)
                with self.assertRaises(ValueError):
                    recovery.validate_publisher(root, PUBLISHER_SHA, now=NOW)

    def test_complete_attempts_do_not_override_incomplete_api_censuses(self):
        for census in ("workflow_runs", "artifacts", "jobs"):
            with self.subTest(census=census), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                publisher_fixture(root)
                prior = install_prior_recovery(root, run_attempt=2, jobs_payload=prior_jobs(attempts=(1, 2)))
                if census == "workflow_runs":
                    prior["total_count"] += 1
                else:
                    prior[census]["123"]["total_count"] += 1
                dump(root / "prior_recoveries.json", prior)
                with self.assertRaisesRegex(ValueError, "census_incomplete"):
                    recovery.validate_publisher(root, PUBLISHER_SHA, now=NOW)

    def test_complete_attempts_success_and_ambiguous_steps_never_retry(self):
        for attempt in (1, 2):
            for conclusion in ("success", "failure", "cancelled", "unknown", None):
                with self.subTest(attempt=attempt, conclusion=conclusion), tempfile.TemporaryDirectory() as td:
                    root = Path(td)
                    publisher_fixture(root)
                    jobs = prior_jobs(attempts=(1, 2))
                    jobs["jobs"][attempt - 1]["steps"][0]["conclusion"] = conclusion
                    install_prior_recovery(root, run_attempt=2, jobs_payload=jobs)
                    error = ("already_published_requires_separate_recovery" if conclusion == "success"
                             else "prior_publication_side_effect_ambiguous")
                    with self.assertRaisesRegex(ValueError, error):
                        recovery.validate_publisher(root, PUBLISHER_SHA, now=NOW)

    def test_prior_success_run_with_skipped_upload_is_not_retry_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            publisher_fixture(root)
            install_prior_recovery(root, run_conclusion="success", step_conclusion="skipped",
                                   jobs_payload=prior_jobs(step_conclusion="skipped"))
            with self.assertRaisesRegex(ValueError, "prior_retry_not_proven_prepublication"):
                recovery.validate_publisher(root, PUBLISHER_SHA, now=NOW)

    def test_prior_expired_artifact_still_blocks_without_job_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            publisher_fixture(root)
            name = "accepted-paper-catchup-2026-07-27-123"
            install_prior_recovery(root, artifacts=[{"name": name, "expired": True}], jobs_payload=None)
            with self.assertRaisesRegex(ValueError, "already_published_requires_separate_recovery"):
                recovery.validate_publisher(root, PUBLISHER_SHA, now=NOW)

    def test_current_run_exclusion_does_not_hide_other_prior_run(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            publisher_fixture(root)
            install_prior_recovery(root, step_conclusion="success", jobs_payload=prior_jobs(step_conclusion="success"))
            with self.assertRaisesRegex(ValueError, "already_published_requires_separate_recovery"):
                recovery.validate_publisher(root, PUBLISHER_SHA, now=NOW)

    def test_outer_run_census_identity_and_current_metadata_fail_closed(self):
        cases = []
        cases.append(("duplicate_prior", lambda p: p.update(
            workflow_runs=[copy.deepcopy(p["workflow_runs"][1])] * 2)))
        cases.append(("duplicate_current", lambda p: p.update(
            workflow_runs=[copy.deepcopy(p["workflow_runs"][0])] * 2, jobs={}, artifacts={})))
        cases.append(("missing_current", lambda p: p.update(
            total_count=1, workflow_runs=[p["workflow_runs"][1]])))
        cases.append(("empty_current_census", lambda p: p.update(
            total_count=0, workflow_runs=[], jobs={}, artifacts={})))
        cases.append(("null_run", lambda p: p["workflow_runs"].__setitem__(1, None)))
        cases.append(("list_run", lambda p: p["workflow_runs"].__setitem__(1, [])))
        cases.append(("missing_prior_id", lambda p: p["workflow_runs"][1].pop("id")))
        cases.append(("missing_current_id", lambda p: p["workflow_runs"][0].pop("id")))
        for index in (0, 1):
            for value in (None, True, False, 0, -1, str(MOCK_RUN if index == 0 else 123),
                          float(MOCK_RUN if index == 0 else 123)):
                cases.append((f"row_{index}_id_{value!r}",
                    lambda p, i=index, v=value: p["workflow_runs"][i].update(id=v)))
        conflicts = {
            "head_sha": "0" * 40, "path": ".github/workflows/unrelated.yml", "event": "push",
            "head_branch": "other", "run_attempt": 2, "status": "completed", "conclusion": "success",
            "created_at": "2026-10-02T00:00:00Z", "run_started_at": "2026-10-02T00:00:00Z",
            "actor": {**owner(), "id": 1}, "triggering_actor": {**owner(), "id": 1},
            "repository": {**repository(), "id": 1}, "head_repository": {**repository(), "id": 1},
        }
        for field, value in conflicts.items():
            cases.append(("current_conflict_" + field,
                lambda p, f=field, v=value: p["workflow_runs"][0].update({f: v})))
        for value in (True, 1.0, "1"):
            cases.append(("current_attempt_type_" + repr(value),
                lambda p, v=value: p["workflow_runs"][0].update(run_attempt=v)))
        for name, change in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                publisher_fixture(root)
                prior = install_prior_recovery(root, jobs_payload=prior_jobs())
                change(prior)
                dump(root / "prior_recoveries.json", prior)
                with self.assertRaises(ValueError):
                    recovery.validate_publisher(root, PUBLISHER_SHA, now=NOW)

    def test_current_census_boolean_id_cannot_alias_run_one(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            data = publisher_fixture(root)
            data["publisher_run"]["id"] = 1
            data["writers_in_progress"]["workflow_runs"] = [{"id": 1}]
            data["prior_recoveries"]["workflow_runs"] = [{"id": True}]
            for name in ("publisher_run", "writers_in_progress", "prior_recoveries"):
                dump(root / (name + ".json"), data[name])
            with self.assertRaises(ValueError):
                recovery.validate_publisher(root, PUBLISHER_SHA, now=NOW)

    def test_active_writer_census_run_identity_and_metadata_fail_closed(self):
        for status in ("in_progress", "queued", "waiting"):
            cases = [
                ("duplicate_current", [{"id": MOCK_RUN}, {"id": MOCK_RUN}]),
                ("null_run", [None]), ("list_run", [[]]), ("missing_id", [{}]),
            ]
            for value in (None, True, False, 0, -1, str(MOCK_RUN), float(MOCK_RUN)):
                cases.append(("invalid_id_" + repr(value), [{"id": value}]))
            for field, value in (("path", ".github/workflows/unrelated.yml"), ("head_sha", "0" * 40),
                                 ("run_attempt", True), ("run_attempt", 1.0), ("run_attempt", 2),
                                 ("actor", {**owner(), "id": 1})):
                cases.append(("current_conflict_" + field, [{"id": MOCK_RUN, field: value}]))
            for name, rows in cases:
                with self.subTest(status=status, name=name), tempfile.TemporaryDirectory() as td:
                    root = Path(td)
                    publisher_fixture(root)
                    dump(root / ("writers_" + status + ".json"), {"total_count": len(rows), "workflow_runs": rows})
                    with self.assertRaises(ValueError):
                        recovery.validate_publisher(root, PUBLISHER_SHA, now=NOW)

    def test_active_writer_boolean_id_cannot_alias_run_one(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            data = publisher_fixture(root)
            data["publisher_run"]["id"] = 1
            data["writers_in_progress"]["workflow_runs"] = [{"id": True}]
            data["prior_recoveries"]["workflow_runs"] = [{"id": 1}]
            for name in ("publisher_run", "writers_in_progress", "prior_recoveries"):
                dump(root / (name + ".json"), data[name])
            with self.assertRaises(ValueError):
                recovery.validate_publisher(root, PUBLISHER_SHA, now=NOW)

    def test_current_only_census_with_consistent_metadata_is_first_publication_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            data = publisher_fixture(root)
            prior = data["prior_recoveries"]
            prior["workflow_runs"] = [copy.deepcopy(data["publisher_run"])]
            dump(root / "prior_recoveries.json", prior)
            self.assertEqual(recovery.validate_publisher(root, PUBLISHER_SHA, now=NOW)["run_id"], MOCK_RUN)

    def test_original_cancelled_boundary_and_pinned_artifact_identity(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            profile = copy.deepcopy(recovery.PROFILE)
            for label in ("capture", "diagnostic"):
                raw = ("synthetic_original_" + label).encode()
                (root / (label + ".zip")).write_bytes(raw)
                profile[label + "_digest"] = hashlib.sha256(raw).hexdigest()
            base = {"run_attempt": 1, "head_sha": profile["producer_sha"], "head_branch": "master",
                    "workflow_id": recovery.scope.WORKFLOW_ID, "path": recovery.scope.WORKFLOW_PATH,
                    "repository": repository(), "head_repository": repository(), "status": "completed"}
            dump(root / "original_run.json", {**base, "id": profile["producer_run"], "conclusion": "cancelled"})
            dump(root / "capture_run.json", {**base, "id": profile["capture_run"], "conclusion": "success"})
            names = [("Run transactional paper ledger and same-close selector", "success"),
                    ("Verify transactional forward paper snapshot", "success"),
                    ("Persist validated forward paper ledger state", "cancelled"),
                    ("Upload accepted chronological catch-up artifact", "skipped"),
                    ("Save validated cross-mode paper continuity cache", "skipped")]
            dump(root / "original_job.json", {"id": profile["producer_job"], "run_id": profile["producer_run"],
                    "conclusion": "cancelled", "steps": [{"name": n, "conclusion": c} for n, c in names]})
            for label, run_id, name in [("capture", profile["capture_run"], f"daily-operating-selection-refresh-{profile['capture_run']}"),
                    ("diagnostic", profile["producer_run"], f"blocked-paper-catchup-2026-07-27-{profile['producer_run']}")]:
                dump(root / (label + "_artifact.json"), {"id": profile[label + "_artifact"], "name": name,
                        "expired": False, "digest": "sha256:" + profile[label + "_digest"],
                        "workflow_run": {"id": run_id, "head_sha": profile["producer_sha"]}})
            recovery.validate_original_evidence(root, root, profile=profile)
            original = recovery.read(root / "original_run.json")
            original["conclusion"] = "success"
            dump(root / "original_run.json", original)
            with self.assertRaisesRegex(ValueError, "original_producer_identity"):
                recovery.validate_original_evidence(root, root, profile=profile)
            original["conclusion"] = "cancelled"
            dump(root / "original_run.json", original)
            (root / "capture.zip").write_bytes(b"tampered")
            with self.assertRaisesRegex(ValueError, "capture_zip_digest"):
                recovery.validate_original_evidence(root, root, profile=profile)

    def test_remote_hashes_new_empty_fork_and_alias_drift_are_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            profile = {**recovery.PROFILE, "chain": ["a" * 64], "outcome_root": "b" * 64}
            inventories = {}
            for name in recovery.INPUT_DIRECTORIES:
                prefix = "a" * 64 + "/" if name == "paper_heads_current" else "b" * 64 + "/" if name == "accepted" else ""
                path = root / name / (prefix + "payload.txt")
                path.parent.mkdir(parents=True)
                path.write_bytes(b"synthetic_payload")
                items = [{"Path": prefix + "payload.txt", "IsDir": False, "Size": path.stat().st_size,
                         "Hashes": {"sha256": hashlib.sha256(path.read_bytes()).hexdigest()}}]
                if prefix:
                    items.insert(0, {"Path": prefix[:-1], "IsDir": True, "Size": 0})
                inventories[name] = items
                dump(root / (name + ".before.json"), items)
                dump(root / (name + ".after.json"), items)
            recovery.verify_remote_inventories(root, profile=profile)
            forked = inventories["paper_heads_current"] + [{"Path": "c" * 64, "IsDir": True, "Size": 0}]
            dump(root / "paper_heads_current.after.json", forked)
            with self.assertRaisesRegex(ValueError, "remote_inventory_drift"):
                recovery.verify_remote_inventories(root, profile=profile)
            dump(root / "paper_heads_current.before.json", forked)
            with self.assertRaisesRegex(ValueError, "remote_head_directory_frontier"):
                recovery.verify_remote_inventories(root, profile=profile)
            dump(root / "paper_heads_current.before.json", inventories["paper_heads_current"])
            dump(root / "paper_heads_current.after.json", inventories["paper_heads_current"])
            (root / "paper_current/payload.txt").write_bytes(b"drift")
            with self.assertRaises(ValueError):
                recovery.verify_remote_inventories(root, profile=profile)

    def test_readback_matches_all_bytes_and_rejects_modified_or_missing_member(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            bundle = root / "bundle"
            bundle.mkdir()
            (bundle / "payload").write_bytes(b"original")
            archive = root / "readback.zip"
            with zipfile.ZipFile(archive, "w") as zipped:
                zipped.write(bundle / "payload", "payload")
            digest = recovery.paper.file_hash(archive)
            self.assertEqual(recovery.readback(archive, bundle, digest)["files_verified"], 1)
            publisher = {"run_id": MOCK_RUN, "source_sha": PUBLISHER_SHA}
            metadata = {"expired": False, "digest": "sha256:" + digest,
                "workflow_run": {"id": MOCK_RUN, "head_sha": PUBLISHER_SHA},
                "name": f"accepted-paper-catchup-2026-07-27-{MOCK_RUN}"}
            self.assertEqual(recovery.readback(archive, bundle, digest, artifact=metadata, publisher=publisher)["status"],
                             "PERSISTED_ARTIFACT_READBACK_VERIFIED")
            metadata["workflow_run"]["id"] = recovery.PROFILE["producer_run"]
            with self.assertRaisesRegex(ValueError, "published_artifact_producer_identity"):
                recovery.readback(archive, bundle, digest, artifact=metadata, publisher=publisher)
            with self.assertRaisesRegex(ValueError, "published_zip_digest"):
                recovery.readback(archive, bundle, "0" * 64)
            with zipfile.ZipFile(archive, "w") as zipped:
                zipped.writestr("payload", "modified")
            with self.assertRaisesRegex(ValueError, "published_payload_checksum"):
                recovery.readback(archive, bundle, recovery.paper.file_hash(archive))
            with zipfile.ZipFile(archive, "w") as zipped:
                zipped.writestr("different", "original")
            with self.assertRaisesRegex(ValueError, "published_zip_inventory"):
                recovery.readback(archive, bundle, recovery.paper.file_hash(archive))

    def test_output_cannot_overwrite_source_or_original_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            root.mkdir(exist_ok=True)
            for candidate in (root, root / "overwrite", ROOT / "outputs/recovery_test_forbidden"):
                with self.assertRaises(ValueError):
                    recovery.prepare(root, root, candidate)
            self.assertFalse((ROOT / "outputs/recovery_test_forbidden").exists())

    def test_self_rehashed_bundle_cannot_claim_orders_or_relabeled_producer(self):
        receipt = {
            "schema_version": recovery.SCHEMA, "status": recovery.READY, "review_only": True,
            "session_date": recovery.PROFILE["session_date"], "snapshot_hash": recovery.PROFILE["terminal"],
            "original_producer": {"source_sha": recovery.PROFILE["producer_sha"],
                "run_id": recovery.PROFILE["producer_run"], "run_attempt": 1, "conclusion": "cancelled"},
            "recovery_verifier": {}, "recovery_publisher": None, "publication_ready": False,
            "original_consumed_scope_reused": False,
            "historical_consumed_scope_comment": recovery.PROFILE["consumed_scope_comment"],
            "new_orders_generated": 0, "new_heads_created": 0, "Drive_writes": 0,
            "forward_promotion_eligible": False, "live_trading_enabled": False,
            "original_artifact_context": recovery.ORIGINAL_CONTEXT,
        }
        for field, value in [("new_orders_generated", 1), ("Drive_writes", False),
                ("forward_promotion_eligible", True), ("original_consumed_scope_reused", True),
                ("original_producer", {"conclusion": "success"}), ("unknown_authority", True)]:
            with self.subTest(field=field), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                changed = {**receipt, field: value}
                dump(root / "recovery_receipt.json", changed)
                dump(root / "INVENTORY.json", {"schema_version": recovery.SCHEMA, "files": recovery.tree(root)})
                with self.assertRaisesRegex(ValueError, "bundle_producer_publisher_binding"):
                    recovery.verify_bundle(root, root)

    def test_extracted_originals_cannot_be_changed_even_with_rehashed_inventory(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            archive = root / "original.zip"
            with zipfile.ZipFile(archive, "w") as zipped:
                zipped.writestr("nested/payload", "original")
            destination = root / "extract"
            recovery.unpack(archive, destination)
            recovery.verify_archive_tree(archive, destination)
            (destination / "nested/payload").write_text("modified", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "original_extracted_byte_changed"):
                recovery.verify_archive_tree(archive, destination)

    def test_workflow_is_manual_owner_gated_readonly_and_cache_is_explicit(self):
        workflow = yaml.safe_load((ROOT / recovery.WORKFLOW_PATH).read_text(encoding="utf-8"))
        events = workflow.get("on") or workflow[True]
        self.assertEqual(set(events), {"workflow_dispatch"})
        self.assertFalse(events["workflow_dispatch"]["inputs"]["allow_publication_recovery"]["default"])
        self.assertFalse(events["workflow_dispatch"]["inputs"]["save_continuity_cache"]["default"])
        self.assertEqual(workflow["concurrency"], {"group": "daily-operating-selection-refresh", "cancel-in-progress": False})
        self.assertEqual(workflow["permissions"], {"contents": "read", "actions": "read"})
        job = workflow["jobs"]["publication_recovery"]
        self.assertEqual(job["environment"], "run287-paper-durable")
        scripts = "\n".join(step.get("run", "") for step in job["steps"])
        for forbidden in ("run_daily_simulated_fill_ledger.py", "--install-source", "--reconcile-immutable-head-cache",
                          "rclone sync", "rclone move", "rclone copyto", "--method POST", "gh workflow run"):
            self.assertNotIn(forbidden, scripts)
        self.assertIn("RCLONE_CONFIG_GDRIVE_SCOPE=drive.readonly", scripts)
        steps = {step.get("id"): step for step in job["steps"]}
        upload = steps["accepted_artifact"]
        self.assertIn("steps.publication_gate.outcome == 'success'", upload["if"])
        self.assertEqual(upload["with"]["name"], "accepted-paper-catchup-2026-07-27-${{ github.run_id }}")
        save = steps["continuity_cache"]
        self.assertIn("inputs.save_continuity_cache == true", save["if"])
        self.assertIn("steps.cache_gate.outcome == 'success'", save["if"])
        self.assertEqual(save["with"]["key"], steps["cache_readback"]["with"]["key"])
        self.assertEqual(save["with"]["path"], steps["cache_readback"]["with"]["path"])
        clearing = steps["clear_cache_staging"]
        self.assertIn("steps.continuity_cache.outcome == 'success'", clearing["if"])
        self.assertIn('test "$(realpath "$target")" = "$WORKSPACE/outputs/$name"', clearing["run"])
        self.assertIn('rm -rf -- "$target"', clearing["run"])
        self.assertIn("steps.clear_cache_staging.outcome == 'success'", steps["cache_readback"]["if"])
        self.assertTrue(steps["cache_readback"]["with"]["fail-on-cache-miss"])
        ordinary = yaml.safe_load((ROOT / ".github/workflows/daily_operating_selection_refresh.yml").read_text(encoding="utf-8"))
        ordinary_events = ordinary.get("on") or ordinary[True]
        self.assertEqual(set(ordinary_events["workflow_dispatch"]["inputs"]), recovery.scope.EVENT_INPUT_KEYS)
        for step in ordinary["jobs"]["refresh"]["steps"]:
            if step.get("name") in ("Upload accepted chronological catch-up artifact", "Save validated cross-mode paper continuity cache"):
                self.assertIn("steps.paper_persist.outcome == 'success'", step["if"])


def main() -> int:
    def denied(*args, **kwargs):
        raise RuntimeError("network forbidden in synthetic publication recovery tests")
    with patch.object(socket, "create_connection", denied), patch.object(socket.socket, "connect", denied):
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(PublicationRecoveryChecks)
        result = unittest.TextTestRunner(verbosity=1).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
