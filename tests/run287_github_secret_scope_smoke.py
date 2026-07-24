#!/usr/bin/env python3
"""Behavioral checks for the Run287 GitHub secret-scope metadata gate."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parent.parent
TOOL = ROOT / "tools" / "check_run287_github_secret_scope.py"
VERIFIER = (
    ROOT / "tools" / "verify_run287_catchup_scope_attestation.py"
)
CONSUMPTION_TOOL = (
    ROOT / "tools" / "run287_catchup_scope_consumption.py"
)

sys.path.insert(0, str(ROOT))
from tools.check_run287_github_secret_scope import (  # noqa: E402
    ATTESTATION_SECRET,
    RCLONE_SECRET,
    RESERVED_SERVICE_ACCOUNT_SECRET,
    evaluate_scope_metadata,
)
from tools.create_run287_catchup_scope_attestation import (  # noqa: E402
    SafeCommandError,
    build_attestation,
    combine_secret_pages,
    require_clean_critical_sources,
)
from tools.run287_catchup_scope_consumption import (  # noqa: E402
    GITHUB_ACTIONS_BOT_ID,
    GITHUB_ACTIONS_BOT_LOGIN,
    GITHUB_ACTIONS_BOT_NODE_ID,
    build_consumption_record,
    verify_consumption_comment,
)
from tools.verify_run287_catchup_scope_attestation import (  # noqa: E402
    ANCHOR_ISSUE_NUMBER,
    DEFAULT_BRANCH,
    OWNER_LOGIN,
    OWNER_ID,
    OWNER_NODE_ID,
    REPOSITORY,
    REPOSITORY_ID,
    REPOSITORY_NODE_ID,
    WORKFLOW_ID,
    WORKFLOW_PATH,
    canonical_json,
    expected_dispatch_inputs,
    file_sha256,
    utc_text,
    verify_attestation_comment,
)


DEFAULT_SHA = "a" * 40
SESSION_DATE = "2026-07-17"
EVIDENCE_RUN_ID = "29625744031"
EVIDENCE_DIGEST = "sha256:" + ("7" * 64)
COMMENT_ID = 123456789
WORKFLOW_RUN_ID = "987654321"
CHECKED_AT = datetime(2026, 7, 24, 1, 0, 0, tzinfo=timezone.utc)


def metadata(*names: str, total: int | None = None) -> dict[str, object]:
    rows = [{"name": name} for name in names]
    return {
        "total_count": len(rows) if total is None else total,
        "secrets": rows,
    }


def test_scope_matrix() -> None:
    good = evaluate_scope_metadata(
        repository=metadata("UNRELATED_REPOSITORY_SECRET"),
        environment=metadata(
            ATTESTATION_SECRET,
            RCLONE_SECRET,
            "UNRELATED_ENVIRONMENT_SECRET",
        ),
    )
    assert good["allowed"] is True
    assert good["status"] == "VERIFIED_ENVIRONMENT_ONLY"
    assert good["github_env_updates"] == {
        "RUN287_DURABLE_SCOPE_VERIFIED": "yes"
    }

    for collision in (
        ATTESTATION_SECRET,
        RCLONE_SECRET,
        RESERVED_SERVICE_ACCOUNT_SECRET,
    ):
        blocked = evaluate_scope_metadata(
            repository=metadata(collision),
            environment=metadata(ATTESTATION_SECRET, RCLONE_SECRET),
        )
        assert blocked["allowed"] is False, collision
        assert (
            f"repository_secret_forbidden:{collision}"
            in blocked["failures"]
        )
        assert blocked["github_env_updates"] == {}

    for missing in (ATTESTATION_SECRET, RCLONE_SECRET):
        present = (
            RCLONE_SECRET if missing == ATTESTATION_SECRET else ATTESTATION_SECRET
        )
        blocked = evaluate_scope_metadata(
            repository=metadata(),
            environment=metadata(present),
        )
        assert blocked["allowed"] is False, missing
        assert (
            f"missing_environment_secret:{missing}" in blocked["failures"]
        )

    reserved = evaluate_scope_metadata(
        repository=metadata(),
        environment=metadata(
            ATTESTATION_SECRET,
            RCLONE_SECRET,
            RESERVED_SERVICE_ACCOUNT_SECRET,
        ),
    )
    assert reserved["allowed"] is False
    assert (
        "reserved_environment_secret_present:"
        + RESERVED_SERVICE_ACCOUNT_SECRET
        in reserved["failures"]
    )

    incomplete = evaluate_scope_metadata(
        repository=metadata("UNRELATED", total=2),
        environment=metadata(ATTESTATION_SECRET, RCLONE_SECRET),
    )
    assert incomplete["allowed"] is False
    assert (
        "repository_secret_metadata_pagination_incomplete"
        in incomplete["failures"]
    )
    malformed = evaluate_scope_metadata(
        repository={"unexpected": []},
        environment=metadata(ATTESTATION_SECRET, RCLONE_SECRET),
    )
    assert malformed["allowed"] is False
    assert "repository_secret_metadata_shape_invalid" in malformed["failures"]
    duplicate = evaluate_scope_metadata(
        repository=metadata("UNRELATED", "UNRELATED"),
        environment=metadata(ATTESTATION_SECRET, RCLONE_SECRET),
    )
    assert duplicate["allowed"] is False
    assert "repository_secret_metadata_name_duplicate" in duplicate["failures"]


def test_cli_handoff() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        temp_root = Path(tmp)
        repository_path = temp_root / "repository.json"
        environment_path = temp_root / "environment.json"
        output_path = temp_root / "scope.json"
        github_env = temp_root / "github_env.txt"
        repository_path.write_text(
            json.dumps(metadata("UNRELATED")),
            encoding="utf-8",
        )
        environment_path.write_text(
            json.dumps(metadata(ATTESTATION_SECRET, RCLONE_SECRET)),
            encoding="utf-8",
        )
        passed = subprocess.run(
            [
                sys.executable,
                str(TOOL),
                "--repository-metadata",
                str(repository_path),
                "--environment-metadata",
                str(environment_path),
                "--output",
                str(output_path),
                "--github-env",
                str(github_env),
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        assert passed.returncode == 0, passed.stderr
        assert github_env.read_text(encoding="utf-8") == (
            "RUN287_DURABLE_SCOPE_VERIFIED=yes\n"
        )
        output = json.loads(output_path.read_text(encoding="utf-8"))
        assert output["status"] == "VERIFIED_ENVIRONMENT_ONLY"

        github_env.write_text("", encoding="utf-8")
        repository_path.write_text(
            json.dumps(metadata(RCLONE_SECRET)),
            encoding="utf-8",
        )
        blocked = subprocess.run(
            [
                sys.executable,
                str(TOOL),
                "--repository-metadata",
                str(repository_path),
                "--environment-metadata",
                str(environment_path),
                "--output",
                str(output_path),
                "--github-env",
                str(github_env),
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        assert blocked.returncode == 2
        assert github_env.read_text(encoding="utf-8") == ""


def verified_scope() -> dict[str, object]:
    result = evaluate_scope_metadata(
        repository=metadata("UNRELATED_REPOSITORY_SECRET"),
        environment=metadata(ATTESTATION_SECRET, RCLONE_SECRET),
    )
    assert result["allowed"] is True
    return result


def attestation() -> dict[str, object]:
    return build_attestation(
        scope_result=verified_scope(),
        default_branch_sha=DEFAULT_SHA,
        session_date=SESSION_DATE,
        evidence_run_id=EVIDENCE_RUN_ID,
        evidence_artifact_digest=EVIDENCE_DIGEST,
        checked_at=CHECKED_AT,
        ttl_seconds=600,
        nonce="12345678-1234-4234-9234-123456789abc",
    )


def comment(
    body: dict[str, object] | None = None,
) -> dict[str, object]:
    created_at = CHECKED_AT + timedelta(seconds=5)
    return {
        "id": COMMENT_ID,
        "url": (
            f"https://api.github.com/repos/{REPOSITORY}/issues/comments/"
            f"{COMMENT_ID}"
        ),
        "html_url": (
            f"https://github.com/{REPOSITORY}/issues/"
            f"{ANCHOR_ISSUE_NUMBER}#issuecomment-{COMMENT_ID}"
        ),
        "issue_url": (
            f"https://api.github.com/repos/{REPOSITORY}/issues/"
            f"{ANCHOR_ISSUE_NUMBER}"
        ),
        "user": {
            "login": OWNER_LOGIN,
            "id": OWNER_ID,
            "node_id": OWNER_NODE_ID,
            "type": "User",
        },
        "author_association": "OWNER",
        "performed_via_github_app": None,
        "created_at": utc_text(created_at),
        "updated_at": utc_text(created_at),
        "body": canonical_json(body or attestation()),
    }


def event() -> dict[str, object]:
    return {
        "inputs": expected_dispatch_inputs(
            session_date=SESSION_DATE,
            evidence_run_id=EVIDENCE_RUN_ID,
            evidence_artifact_digest=EVIDENCE_DIGEST,
            comment_id=COMMENT_ID,
        )
    }


def workflow_run() -> dict[str, object]:
    owner = {
        "login": OWNER_LOGIN,
        "id": OWNER_ID,
        "node_id": OWNER_NODE_ID,
        "type": "User",
    }
    created_at = utc_text(CHECKED_AT + timedelta(seconds=10))
    return {
        "id": int(WORKFLOW_RUN_ID),
        "run_attempt": 1,
        "event": "workflow_dispatch",
        "head_sha": DEFAULT_SHA,
        "head_branch": DEFAULT_BRANCH,
        "path": WORKFLOW_PATH,
        "workflow_id": WORKFLOW_ID,
        "created_at": created_at,
        "run_started_at": created_at,
        "actor": dict(owner),
        "triggering_actor": dict(owner),
        "repository": {
            "id": REPOSITORY_ID,
            "node_id": REPOSITORY_NODE_ID,
            "full_name": REPOSITORY,
            "owner": dict(owner),
        },
    }


def verify(
    value: dict[str, object],
    *,
    now: datetime | None = None,
    workflow_actor: str = OWNER_LOGIN,
    expected_session_date: str = SESSION_DATE,
    expected_run_id: str = EVIDENCE_RUN_ID,
    expected_digest: str = EVIDENCE_DIGEST,
    run_value: dict[str, object] | None = None,
    event_value: dict[str, object] | None = None,
    prior: dict[str, object] | None = None,
) -> dict[str, object]:
    return verify_attestation_comment(
        comment=value,
        run=run_value or workflow_run(),
        event=event_value or event(),
        expected_comment_id=COMMENT_ID,
        expected_repository=REPOSITORY,
        expected_default_branch=DEFAULT_BRANCH,
        expected_default_branch_sha=DEFAULT_SHA,
        expected_session_date=expected_session_date,
        expected_evidence_run_id=expected_run_id,
        expected_evidence_artifact_digest=expected_digest,
        expected_workflow_run_id=WORKFLOW_RUN_ID,
        workflow_actor=workflow_actor,
        now=now or CHECKED_AT + timedelta(seconds=30),
        prior_verification=prior,
    )


def test_attestation_builder_and_pagination() -> None:
    built = attestation()
    assert built["authorization"] == {
        "automatic_promotion_authorized": False,
        "fullrun_authorized": False,
        "live_trading_authorized": False,
        "paper_catchup_only": True,
        "production_activation_authorized": False,
    }
    assert built["expires_at"] == "2026-07-24T01:10:00Z"
    assert built["scope"]["failures"] == []
    assert built["request_nonce"] == (
        "12345678-1234-4234-9234-123456789abc"
    )
    assert set(built["dispatch_inputs"]) == {
        "allow_quarantined_legacy_outcome_parent",
        "allow_risk_outcome_genesis_bootstrap",
        "allow_verified_paper_canonical_head_bootstrap",
        "catchup_price_evidence_artifact_digest",
        "catchup_price_evidence_run_id",
        "force_run",
        "latest_run",
        "session_date",
        "strict_selection",
    }
    pages = combine_secret_pages(
        [
            {"total_count": 2, "secrets": [{"name": "ONE"}]},
            {"total_count": 2, "secrets": [{"name": "TWO"}]},
        ],
        label="repository",
    )
    assert pages["total_count"] == 2
    assert [row["name"] for row in pages["secrets"]] == ["ONE", "TWO"]
    with patch(
        "tools.create_run287_catchup_scope_attestation.subprocess.run",
        return_value=subprocess.CompletedProcess(
            args=["git", "status"],
            returncode=0,
            stdout="",
            stderr="",
        ),
    ):
        require_clean_critical_sources()
    with patch(
        "tools.create_run287_catchup_scope_attestation.subprocess.run",
        return_value=subprocess.CompletedProcess(
            args=["git", "status"],
            returncode=0,
            stdout=" M tools/check_run287_github_secret_scope.py\n",
            stderr="",
        ),
    ):
        try:
            require_clean_critical_sources()
        except SafeCommandError as exc:
            assert "not clean" in str(exc)
        else:
            raise AssertionError("dirty attestation sources were accepted")
    with tempfile.TemporaryDirectory() as tmp:
        temp_root = Path(tmp)
        lf_path = temp_root / "lf.json"
        crlf_path = temp_root / "crlf.json"
        contract_fixture = {"b": [2, 3], "a": 1}
        rendered = json.dumps(contract_fixture, indent=2) + "\n"
        lf_path.write_text(rendered, encoding="utf-8", newline="\n")
        crlf_path.write_text(rendered, encoding="utf-8", newline="\r\n")
        assert file_sha256(lf_path) == file_sha256(crlf_path)

    blocked_scope = verified_scope()
    blocked_scope["allowed"] = False
    try:
        build_attestation(
            scope_result=blocked_scope,
            default_branch_sha=DEFAULT_SHA,
            session_date=SESSION_DATE,
            evidence_run_id=EVIDENCE_RUN_ID,
            evidence_artifact_digest=EVIDENCE_DIGEST,
            checked_at=CHECKED_AT,
            ttl_seconds=600,
        )
    except ValueError:
        pass
    else:
        raise AssertionError("blocked scope unexpectedly built an attestation")


def test_attestation_verification_matrix() -> None:
    good = verify(comment())
    assert good["allowed"] is True
    assert good["status"] == "VERIFIED_OWNER_SCOPE_ATTESTATION"
    assert good["github_env_updates"] == {
        "RUN287_DURABLE_SCOPE_VERIFIED": "yes"
    }
    assert good["workflow_run_created_at"] == "2026-07-24T01:00:10Z"
    assert good["workflow_run_lease_expires_at"] == (
        "2026-07-24T02:00:10Z"
    )

    cases: list[tuple[str, dict[str, object], str]] = []
    wrong_author = comment()
    wrong_author["user"] = deepcopy(wrong_author["user"])
    wrong_author["user"]["login"] = "other"
    cases.append(("author", wrong_author, "comment_author_login_mismatch"))
    wrong_association = comment()
    wrong_association["author_association"] = "MEMBER"
    cases.append(
        (
            "association",
            wrong_association,
            "comment_author_association_not_owner",
        )
    )
    wrong_issue = comment()
    wrong_issue["issue_url"] = (
        f"https://api.github.com/repos/{REPOSITORY}/issues/325"
    )
    cases.append(("issue", wrong_issue, "comment_anchor_issue_mismatch"))
    edited = comment()
    edited["updated_at"] = "2026-07-24T01:00:06Z"
    cases.append(("edited", edited, "comment_was_edited"))
    noncanonical = comment()
    noncanonical["body"] = json.dumps(attestation(), indent=2)
    cases.append(
        ("canonical", noncanonical, "comment_body_not_canonical")
    )

    body_mutations: list[tuple[str, object, str]] = [
        ("session_date", "2026-07-20", "attestation_session_date_mismatch"),
        (
            "catchup_price_evidence_run_id",
            "29801446668",
            "attestation_catchup_price_evidence_run_id_mismatch",
        ),
        (
            "catchup_price_evidence_artifact_digest",
            "sha256:" + ("8" * 64),
            "attestation_catchup_price_evidence_artifact_digest_mismatch",
        ),
        (
            "request_nonce",
            "not-a-uuid",
            "attestation_request_nonce_invalid",
        ),
    ]
    for field, value, failure in body_mutations:
        mutated = attestation()
        mutated[field] = value
        cases.append((field, comment(mutated), failure))

    bad_scope = attestation()
    bad_scope["scope"] = deepcopy(bad_scope["scope"])
    bad_scope["scope"]["allowed"] = False
    bad_scope["scope"]["failures"] = ["repository_secret_forbidden"]
    cases.append(
        (
            "scope",
            comment(bad_scope),
            "attestation_scope_not_verified",
        )
    )
    bad_authorization = attestation()
    bad_authorization["authorization"] = deepcopy(
        bad_authorization["authorization"]
    )
    bad_authorization["authorization"]["fullrun_authorized"] = True
    cases.append(
        (
            "authorization",
            comment(bad_authorization),
            "attestation_authorization_invalid",
        )
    )
    extra = attestation()
    extra["unexpected"] = True
    cases.append(
        (
            "shape",
            comment(extra),
            "attestation_top_level_shape_invalid",
        )
    )

    for label, candidate, expected_failure in cases:
        result = verify(candidate)
        assert result["allowed"] is False, label
        assert expected_failure in result["failures"], (
            label,
            result["failures"],
        )
        assert result["github_env_updates"] == {}, label

    wrong_workflow = attestation()
    wrong_workflow["workflow"] = deepcopy(wrong_workflow["workflow"])
    wrong_workflow["workflow"]["default_branch_sha"] = "b" * 40
    wrong_workflow_result = verify(comment(wrong_workflow))
    assert wrong_workflow_result["allowed"] is False
    assert (
        "attestation_workflow_identity_mismatch"
        in wrong_workflow_result["failures"]
    )

    assert verify(
        comment(),
        workflow_actor="repository-collaborator",
    )["allowed"] is False
    assert verify(
        comment(),
        expected_session_date="2026-07-20",
    )["allowed"] is False
    assert verify(
        comment(),
        expected_run_id="29801446668",
    )["allowed"] is False
    assert verify(
        comment(),
        expected_digest="sha256:" + ("8" * 64),
    )["allowed"] is False

    for input_name in sorted(event()["inputs"]):
        changed_event = event()
        changed_event["inputs"] = deepcopy(changed_event["inputs"])
        original = changed_event["inputs"][input_name]
        changed_event["inputs"][input_name] = (
            not original if type(original) is bool else f"{original}-changed"
        )
        changed = verify(comment(), event_value=changed_event)
        assert changed["allowed"] is False, input_name
        assert (
            "workflow_dispatch_inputs_not_exact_safe_catchup"
            in changed["failures"]
        ), (input_name, changed["failures"])

    missing_input_event = event()
    missing_input_event["inputs"] = deepcopy(
        missing_input_event["inputs"]
    )
    missing_input_event["inputs"].pop("latest_run")
    missing_input = verify(comment(), event_value=missing_input_event)
    assert missing_input["allowed"] is False
    assert (
        "workflow_dispatch_inputs_shape_invalid"
        in missing_input["failures"]
    )

    rerun = workflow_run()
    rerun["run_attempt"] = 2
    rerun_result = verify(comment(), run_value=rerun)
    assert rerun_result["allowed"] is False
    assert "workflow_run_run_attempt_mismatch" in rerun_result["failures"]

    wrong_run_actor = workflow_run()
    wrong_run_actor["actor"] = deepcopy(wrong_run_actor["actor"])
    wrong_run_actor["actor"]["id"] = 1
    wrong_run_actor_result = verify(comment(), run_value=wrong_run_actor)
    assert wrong_run_actor_result["allowed"] is False
    assert (
        "workflow_run_actor_id_mismatch"
        in wrong_run_actor_result["failures"]
    )

    expired = verify(
        comment(),
        now=CHECKED_AT + timedelta(seconds=601),
    )
    assert expired["allowed"] is False
    assert "attestation_expired" in expired["failures"]

    initial = verify(comment())
    reverified_after_expiry = verify(
        comment(),
        now=CHECKED_AT + timedelta(minutes=30),
        prior=initial,
    )
    assert reverified_after_expiry["allowed"] is True
    assert reverified_after_expiry["verification_phase"] == "REVERIFICATION"
    assert reverified_after_expiry["github_env_updates"] == {
        "RUN287_DURABLE_SCOPE_REVERIFIED": "yes"
    }
    lease_expired = verify(
        comment(),
        now=CHECKED_AT + timedelta(minutes=61),
        prior=initial,
    )
    assert lease_expired["allowed"] is False
    assert "workflow_run_lease_expired" in lease_expired["failures"]
    changed_after_initial = comment()
    changed_after_initial["updated_at"] = "2026-07-24T01:00:06Z"
    final_blocked = verify(
        changed_after_initial,
        now=CHECKED_AT + timedelta(minutes=30),
        prior=initial,
    )
    assert final_blocked["allowed"] is False

    future_body = attestation()
    future_body["checked_at"] = "2026-07-24T01:05:00Z"
    future_body["expires_at"] = "2026-07-24T01:15:00Z"
    future_comment = comment(future_body)
    future_comment["created_at"] = "2026-07-24T01:05:05Z"
    future_comment["updated_at"] = "2026-07-24T01:05:05Z"
    future = verify(future_comment, now=CHECKED_AT)
    assert future["allowed"] is False
    assert "attestation_checked_at_in_future" in future["failures"]
    assert "comment_created_at_in_future" in future["failures"]


def test_attestation_cli_handoff() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        temp_root = Path(tmp)
        comment_path = temp_root / "comment.json"
        run_path = temp_root / "run.json"
        event_path = temp_root / "event.json"
        output_path = temp_root / "verification.json"
        github_env = temp_root / "github_env.txt"
        comment_path.write_text(
            json.dumps(comment()),
            encoding="utf-8",
        )
        run_path.write_text(
            json.dumps(workflow_run()),
            encoding="utf-8",
        )
        event_path.write_text(
            json.dumps(event()),
            encoding="utf-8",
        )
        command = [
            sys.executable,
            str(VERIFIER),
            "--comment",
            str(comment_path),
            "--run",
            str(run_path),
            "--event",
            str(event_path),
            "--expected-comment-id",
            str(COMMENT_ID),
            "--expected-repository",
            REPOSITORY,
            "--expected-default-branch",
            DEFAULT_BRANCH,
            "--expected-default-branch-sha",
            DEFAULT_SHA,
            "--expected-session-date",
            SESSION_DATE,
            "--expected-evidence-run-id",
            EVIDENCE_RUN_ID,
            "--expected-evidence-artifact-digest",
            EVIDENCE_DIGEST,
            "--expected-workflow-run-id",
            WORKFLOW_RUN_ID,
            "--workflow-actor",
            OWNER_LOGIN,
            "--now",
            "2026-07-24T01:00:30Z",
            "--output",
            str(output_path),
            "--github-env",
            str(github_env),
        ]
        passed = subprocess.run(
            command,
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        assert passed.returncode == 0, passed.stdout + passed.stderr
        assert github_env.read_text(encoding="utf-8") == (
            "RUN287_DURABLE_SCOPE_VERIFIED=yes\n"
        )
        result = json.loads(output_path.read_text(encoding="utf-8"))
        assert result["allowed"] is True
        assert "body" not in result

        github_env.write_text("", encoding="utf-8")
        bad = comment()
        bad["author_association"] = "MEMBER"
        comment_path.write_text(json.dumps(bad), encoding="utf-8")
        blocked = subprocess.run(
            command,
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        assert blocked.returncode == 2
        assert github_env.read_text(encoding="utf-8") == ""


def consumption_comment(
    record: dict[str, object],
    *,
    comment_id: int = 2233445566,
) -> dict[str, object]:
    consumed_at = datetime.strptime(
        str(record["consumed_at"]),
        "%Y-%m-%dT%H:%M:%SZ",
    ).replace(tzinfo=timezone.utc)
    created_at = utc_text(consumed_at + timedelta(seconds=1))
    return {
        "id": comment_id,
        "url": (
            f"https://api.github.com/repos/{REPOSITORY}/issues/comments/"
            f"{comment_id}"
        ),
        "html_url": (
            f"https://github.com/{REPOSITORY}/issues/"
            f"{ANCHOR_ISSUE_NUMBER}#issuecomment-{comment_id}"
        ),
        "issue_url": (
            f"https://api.github.com/repos/{REPOSITORY}/issues/"
            f"{ANCHOR_ISSUE_NUMBER}"
        ),
        "user": {
            "login": GITHUB_ACTIONS_BOT_LOGIN,
            "id": GITHUB_ACTIONS_BOT_ID,
            "node_id": GITHUB_ACTIONS_BOT_NODE_ID,
            "type": "Bot",
        },
        "author_association": "NONE",
        "created_at": created_at,
        "updated_at": created_at,
        "body": canonical_json(record),
    }


def test_one_time_consumption() -> None:
    verification = verify(comment())
    record = build_consumption_record(
        verification=verification,
        run=workflow_run(),
        existing_comments=[],
        now=CHECKED_AT + timedelta(seconds=31),
    )
    created = consumption_comment(record)
    receipt = verify_consumption_comment(
        comment=created,
        expected_record=record,
        verification=verification,
        run=workflow_run(),
        now=CHECKED_AT + timedelta(seconds=35),
    )
    assert receipt["allowed"] is True
    assert receipt["github_env_updates"] == {
        "RUN287_DURABLE_SCOPE_CONSUMED": "yes",
        "RUN287_DURABLE_SCOPE_CONSUMPTION_COMMENT_ID": "2233445566",
    }

    foreign_claim = deepcopy(created)
    foreign_claim["user"] = {
        "login": "untrusted-user",
        "id": 1,
        "node_id": "foreign",
        "type": "User",
    }
    foreign_ignored = build_consumption_record(
        verification=verification,
        run=workflow_run(),
        existing_comments=[foreign_claim],
        now=CHECKED_AT + timedelta(seconds=40),
    )
    assert foreign_ignored["attestation_comment_id"] == COMMENT_ID

    try:
        build_consumption_record(
            verification=verification,
            run=workflow_run(),
            existing_comments=[created],
            now=CHECKED_AT + timedelta(seconds=40),
        )
    except ValueError as exc:
        assert "already has a consumption claim" in str(exc)
    else:
        raise AssertionError("consumed attestation was reusable")

    malformed_bot_claim = deepcopy(created)
    malformed_payload = json.loads(malformed_bot_claim["body"])
    malformed_payload["default_branch_sha"] = "b" * 40
    malformed_bot_claim["body"] = canonical_json(malformed_payload)
    try:
        build_consumption_record(
            verification=verification,
            run=workflow_run(),
            existing_comments=[malformed_bot_claim],
            now=CHECKED_AT + timedelta(seconds=40),
        )
    except ValueError as exc:
        assert "malformed Actions-bot" in str(exc)
    else:
        raise AssertionError("malformed bot claim was not blocked")

    reverified = verify_consumption_comment(
        comment=created,
        expected_record=record,
        verification=verification,
        run=workflow_run(),
        now=CHECKED_AT + timedelta(minutes=30),
        prior_receipt=receipt,
    )
    assert reverified["allowed"] is True
    assert reverified["github_env_updates"] == {
        "RUN287_DURABLE_SCOPE_CONSUMPTION_REVERIFIED": "yes"
    }
    expired_lease = verify_consumption_comment(
        comment=created,
        expected_record=record,
        verification=verification,
        run=workflow_run(),
        now=CHECKED_AT + timedelta(minutes=61),
        prior_receipt=receipt,
    )
    assert expired_lease["allowed"] is False
    assert "workflow_run_lease_expired" in expired_lease["failures"]

    edited = deepcopy(created)
    edited["updated_at"] = "2026-07-24T01:00:33Z"
    edited_result = verify_consumption_comment(
        comment=edited,
        expected_record=record,
        verification=verification,
        run=workflow_run(),
        now=CHECKED_AT + timedelta(minutes=30),
        prior_receipt=receipt,
    )
    assert edited_result["allowed"] is False
    assert "consumption_comment_was_edited" in edited_result["failures"]

    wrong_author = deepcopy(created)
    wrong_author["user"]["id"] = 1
    wrong_author_result = verify_consumption_comment(
        comment=wrong_author,
        expected_record=record,
        verification=verification,
        run=workflow_run(),
        now=CHECKED_AT + timedelta(seconds=35),
    )
    assert wrong_author_result["allowed"] is False
    assert (
        "consumption_author_id_mismatch"
        in wrong_author_result["failures"]
    )


def test_consumption_cli_handoff() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        temp_root = Path(tmp)
        verification_path = temp_root / "verification.json"
        run_path = temp_root / "run.json"
        inventory_path = temp_root / "comments.json"
        record_path = temp_root / "record.json"
        request_path = temp_root / "request.json"
        created_path = temp_root / "created.json"
        receipt_path = temp_root / "receipt.json"
        github_env = temp_root / "github_env.txt"
        verification = verify(comment())
        verification_path.write_text(
            json.dumps(verification),
            encoding="utf-8",
        )
        run_path.write_text(
            json.dumps(workflow_run()),
            encoding="utf-8",
        )
        inventory_path.write_text("[]", encoding="utf-8")
        prepared = subprocess.run(
            [
                sys.executable,
                str(CONSUMPTION_TOOL),
                "prepare",
                "--verification",
                str(verification_path),
                "--run",
                str(run_path),
                "--existing-comments",
                str(inventory_path),
                "--now",
                "2026-07-24T01:00:31Z",
                "--record-output",
                str(record_path),
                "--request-output",
                str(request_path),
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        assert prepared.returncode == 0, prepared.stdout + prepared.stderr
        record = json.loads(record_path.read_text(encoding="utf-8"))
        request = json.loads(request_path.read_text(encoding="utf-8"))
        assert request == {"body": canonical_json(record)}
        created_path.write_text(
            json.dumps(consumption_comment(record)),
            encoding="utf-8",
        )
        verified = subprocess.run(
            [
                sys.executable,
                str(CONSUMPTION_TOOL),
                "verify",
                "--comment",
                str(created_path),
                "--expected-record",
                str(record_path),
                "--verification",
                str(verification_path),
                "--run",
                str(run_path),
                "--now",
                "2026-07-24T01:00:35Z",
                "--output",
                str(receipt_path),
                "--github-env",
                str(github_env),
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        assert verified.returncode == 0, verified.stdout + verified.stderr
        assert github_env.read_text(encoding="utf-8") == (
            "RUN287_DURABLE_SCOPE_CONSUMED=yes\n"
            "RUN287_DURABLE_SCOPE_CONSUMPTION_COMMENT_ID=2233445566\n"
        )


def main() -> int:
    test_scope_matrix()
    test_cli_handoff()
    test_attestation_builder_and_pagination()
    test_attestation_verification_matrix()
    test_attestation_cli_handoff()
    test_one_time_consumption()
    test_consumption_cli_handoff()
    print("run287_github_secret_scope_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
