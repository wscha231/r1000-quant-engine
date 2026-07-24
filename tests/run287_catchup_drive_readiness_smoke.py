#!/usr/bin/env python3
"""Behavioral and workflow checks for durable Run287 catch-up Drive gating."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import yaml


ROOT = Path(__file__).resolve().parent.parent
TOOL = ROOT / "tools" / "check_run287_catchup_drive_readiness.py"
WORKFLOW = (
    ROOT / ".github" / "workflows" / "daily_operating_selection_refresh.yml"
)

sys.path.insert(0, str(ROOT))
from tools.check_run287_catchup_drive_readiness import (  # noqa: E402
    ENVIRONMENT_CONTRACT_PATH,
    VALID_RESTORE_MODE_STATES,
    evaluate_readiness,
    evaluate_environment,
    load_environment_contract,
    verify_environment_attestation,
    verify_environment_credential_binding,
)


def evaluate(
    *,
    phase: str,
    catchup: bool,
    auth: bool = False,
    scope: bool = False,
    attested: bool = False,
    credential_bound: bool = False,
    ready: bool = False,
    rclone: bool = False,
    state: str = "",
    mode: str = "",
    consumed: bool = False,
    reverified: bool = False,
    consumption_reverified: bool = False,
) -> dict[str, object]:
    return evaluate_readiness(
        phase=phase,
        catchup_mode=catchup,
        auth_configured=auth,
        secret_scope_verified=scope,
        environment_attested=attested,
        credential_attested=credential_bound,
        gdrive_ready=ready,
        rclone_available=rclone,
        canonical_state=state,
        durable_restore_mode=mode,
        scope_consumed=consumed,
        scope_reverified=reverified,
        consumption_reverified=consumption_reverified,
    )


def test_environment_attestation_contract() -> None:
    contract = load_environment_contract()
    assert ENVIRONMENT_CONTRACT_PATH.is_file()
    assert contract["environment"] == "run287-paper-durable"
    assert contract["repository_scope_allowed"] is False
    assert contract["attestation"]["secret_name"] == (
        "RUN287_DURABLE_ENVIRONMENT_ATTESTATION"
    )
    assert set(contract["credential_hmac_sha256"]) == {
        "RUN287_DURABLE_GOOGLE_SERVICE_ACCOUNT_KEY",
        "RUN287_DURABLE_RCLONE_CONFIG_GDRIVE",
    }
    assert (
        contract["credential_hmac_sha256"][
            "RUN287_DURABLE_GOOGLE_SERVICE_ACCOUNT_KEY"
        ]
        is None
    )
    assert len(
        contract["credential_hmac_sha256"][
            "RUN287_DURABLE_RCLONE_CONFIG_GDRIVE"
        ]
    ) == 64
    assert contract["credential_binding_marker_required"] is True

    test_value = "offline-test-environment-attestation"
    unbound_test_credential = "[gdrive]\ntype = drive\ntoken = offline-test"
    test_credential = (
        unbound_test_credential
        + "\n# run287_environment_binding="
        + "AbCdEfGhIjKlMnOpQrStUvWxYz012345"
    )
    test_contract = {
        **contract,
        "attestation": {
            **contract["attestation"],
            "sha256": hashlib.sha256(test_value.encode("utf-8")).hexdigest(),
        },
        "credential_hmac_sha256": {
            "RUN287_DURABLE_GOOGLE_SERVICE_ACCOUNT_KEY": None,
            "RUN287_DURABLE_RCLONE_CONFIG_GDRIVE": hmac.new(
                test_value.encode("utf-8"),
                test_credential.encode("utf-8"),
                hashlib.sha256,
            ).hexdigest(),
        },
    }
    assert verify_environment_attestation(
        contract=test_contract,
        environment_name="run287-paper-durable",
        attestation_value=test_value,
    )
    assert not verify_environment_attestation(
        contract=test_contract,
        environment_name="wrong-environment",
        attestation_value=test_value,
    )
    assert not verify_environment_attestation(
        contract=test_contract,
        environment_name="run287-paper-durable",
        attestation_value="wrong-attestation",
    )
    assert not verify_environment_attestation(
        contract=test_contract,
        environment_name="run287-paper-durable",
        attestation_value="",
    )
    assert verify_environment_credential_binding(
        contract=test_contract,
        attestation_value=test_value,
        credentials={"RCLONE_CONFIG_GDRIVE": test_credential},
    )
    assert not verify_environment_credential_binding(
        contract=test_contract,
        attestation_value=test_value,
        credentials={"RCLONE_CONFIG_GDRIVE": "different-credential"},
    )
    assert not verify_environment_credential_binding(
        contract=test_contract,
        attestation_value=test_value,
        credentials={"RCLONE_CONFIG_GDRIVE": unbound_test_credential},
    )
    assert not verify_environment_credential_binding(
        contract=test_contract,
        attestation_value=test_value,
        credentials={
            "RCLONE_CONFIG_GDRIVE": test_credential,
            "GOOGLE_SERVICE_ACCOUNT_KEY": "ambiguous-second-credential",
        },
    )
    assert not verify_environment_credential_binding(
        contract=test_contract,
        attestation_value=test_value,
        credentials={},
    )

    with tempfile.TemporaryDirectory() as tmp:
        contract_path = Path(tmp) / "contract.json"
        contract_path.write_text(
            json.dumps(test_contract, sort_keys=True),
            encoding="utf-8",
        )
        correct_environment = {
            "PAPER_CATCHUP_MODE": "yes",
            "RUN287_DURABLE_SCOPE_VERIFIED": "yes",
            "RUN287_DURABLE_ENVIRONMENT_NAME": "run287-paper-durable",
            "RUN287_DURABLE_ENVIRONMENT_ATTESTATION": test_value,
            "RCLONE_CONFIG_GDRIVE": test_credential,
        }
        with patch.dict(os.environ, correct_environment, clear=True):
            ready = evaluate_environment(
                "authentication", contract_path=contract_path
            )
        assert ready["allowed"] is True
        assert ready["status"] == "READY_AUTH_CONFIGURED_AND_ATTESTED"

        for changed_key, changed_value, expected_status in (
            (
                "RUN287_DURABLE_ENVIRONMENT_NAME",
                "",
                "BLOCKED_DURABLE_ENVIRONMENT_ATTESTATION",
            ),
            (
                "RUN287_DURABLE_ENVIRONMENT_ATTESTATION",
                "",
                "BLOCKED_DURABLE_ENVIRONMENT_ATTESTATION",
            ),
            (
                "RCLONE_CONFIG_GDRIVE",
                "different-credential",
                "BLOCKED_DURABLE_CREDENTIAL_BINDING",
            ),
        ):
            changed_environment = {
                **correct_environment,
                changed_key: changed_value,
            }
            with patch.dict(os.environ, changed_environment, clear=True):
                blocked = evaluate_environment(
                    "authentication", contract_path=contract_path
                )
            assert blocked["allowed"] is False, changed_key
            assert blocked["status"] == expected_status, changed_key

        restored_environment = {
            **correct_environment,
            "GDRIVE_READY": "yes",
            "PAPER_CANONICAL_REMOTE_STATE": "PROVEN_PRESENT",
            "PAPER_DURABLE_RESTORE_MODE": "VERIFIED_CANONICAL",
        }
        with (
            patch.dict(os.environ, restored_environment, clear=True),
            patch(
                "tools.check_run287_catchup_drive_readiness.shutil.which",
                return_value="/usr/local/bin/rclone",
            ),
        ):
            restored = evaluate_environment(
                "restored", contract_path=contract_path
            )
        assert restored["allowed"] is True
        wrong_restored_environment = {
            **restored_environment,
            "RCLONE_CONFIG_GDRIVE": "different-credential",
        }
        with (
            patch.dict(os.environ, wrong_restored_environment, clear=True),
            patch(
                "tools.check_run287_catchup_drive_readiness.shutil.which",
                return_value="/usr/local/bin/rclone",
            ),
        ):
            blocked_restored = evaluate_environment(
                "restored", contract_path=contract_path
            )
        assert blocked_restored["allowed"] is False
        assert (
            blocked_restored["status"]
            == "BLOCKED_DURABLE_CREDENTIAL_BINDING"
        )


def test_behavior_matrix() -> None:
    normal = evaluate(phase="authentication", catchup=False)
    assert normal["schema_version"] == "run287-catchup-drive-readiness-v5"
    assert normal["allowed"] is True
    assert normal["status"] == "READY_NON_CATCHUP_CACHE_ONLY"
    assert normal["github_env_updates"] == {"GDRIVE_READY": "no"}

    blocked_scope = evaluate(phase="authentication", catchup=True)
    assert blocked_scope["allowed"] is False
    assert blocked_scope["status"] == "BLOCKED_DURABLE_SECRET_SCOPE"
    blocked_auth = evaluate(
        phase="authentication", catchup=True, scope=True
    )
    assert blocked_auth["allowed"] is False
    assert blocked_auth["status"] == "BLOCKED_DURABLE_DRIVE_AUTH"
    blocked_attestation = evaluate(
        phase="authentication", catchup=True, scope=True, auth=True
    )
    assert blocked_attestation["allowed"] is False
    assert (
        blocked_attestation["status"]
        == "BLOCKED_DURABLE_ENVIRONMENT_ATTESTATION"
    )
    assert evaluate(
        phase="authentication",
        catchup=True,
        scope=True,
        auth=True,
        attested=True,
    )["status"] == "BLOCKED_DURABLE_CREDENTIAL_BINDING"
    assert evaluate(
        phase="authentication",
        catchup=True,
        scope=True,
        auth=True,
        attested=True,
        credential_bound=True,
    )["allowed"] is True
    assert evaluate(
        phase="authentication", catchup=False, auth=True
    )["status"] == "BLOCKED_DURABLE_ENVIRONMENT_ATTESTATION"

    assert evaluate(phase="restored", catchup=False)["allowed"] is True
    assert evaluate(
        phase="restored", catchup=True, ready=True, rclone=True
    )["status"] == "BLOCKED_DURABLE_SECRET_SCOPE"
    assert evaluate(
        phase="restored",
        catchup=True,
        scope=True,
        ready=True,
        rclone=True,
    )["status"] == "BLOCKED_DURABLE_ENVIRONMENT_ATTESTATION"
    assert evaluate(
        phase="restored",
        catchup=True,
        scope=True,
        attested=True,
        ready=True,
        rclone=True,
    )["status"] == "BLOCKED_DURABLE_CREDENTIAL_BINDING"
    assert evaluate(
        phase="restored",
        catchup=True,
        scope=True,
        attested=True,
        credential_bound=True,
        ready=False,
        rclone=True,
    )["status"] == "BLOCKED_DURABLE_DRIVE_RESTORE"
    assert evaluate(
        phase="restored",
        catchup=True,
        scope=True,
        attested=True,
        credential_bound=True,
        ready=True,
        rclone=False,
    )["status"] == "BLOCKED_DURABLE_DRIVE_RESTORE"
    for mode, states in sorted(VALID_RESTORE_MODE_STATES.items()):
        for state in sorted(states):
            passed = evaluate(
                phase="restored",
                catchup=True,
                scope=True,
                attested=True,
                credential_bound=True,
                ready=True,
                rclone=True,
                state=state,
                mode=mode,
            )
            assert passed["allowed"] is True, (mode, state)
            assert passed["status"] == "READY_DURABLE_DRIVE"
            assert passed["durable_restore_mode"] == mode
    for mode in ("", "UNAVAILABLE", "CACHE_ONLY", "UNKNOWN"):
        blocked = evaluate(
            phase="restored",
            catchup=True,
            scope=True,
            attested=True,
            credential_bound=True,
            ready=True,
            rclone=True,
            state="PROVEN_PRESENT",
            mode=mode,
        )
        assert blocked["allowed"] is False, mode
        assert blocked["status"] == "BLOCKED_DURABLE_DRIVE_ANCHOR"
    known_states = {
        "PROVEN_PRESENT",
        "PROVEN_ABSENT",
        "REPAIR_FROM_IMMUTABLE",
        "UNKNOWN",
    }
    for mode, allowed_states in VALID_RESTORE_MODE_STATES.items():
        for state in known_states:
            result = evaluate(
                phase="restored",
                catchup=True,
                scope=True,
                attested=True,
                credential_bound=True,
                ready=True,
                rclone=True,
                state=state,
                mode=mode,
            )
            assert result["allowed"] is (state in allowed_states), (
                mode,
                state,
            )
            if state not in allowed_states:
                assert result["status"] == "BLOCKED_DURABLE_DRIVE_STATE"

    mutation_base = {
        "phase": "mutation",
        "catchup": True,
        "scope": True,
        "attested": True,
        "credential_bound": True,
        "ready": True,
        "rclone": True,
        "state": "PROVEN_PRESENT",
        "mode": "IMMUTABLE_HEAD",
    }
    assert evaluate(**mutation_base)["status"] == (
        "BLOCKED_SCOPE_ATTESTATION_NOT_CONSUMED"
    )
    assert evaluate(
        **mutation_base,
        consumed=True,
    )["status"] == "BLOCKED_SCOPE_ATTESTATION_NOT_REVERIFIED"
    assert evaluate(
        **mutation_base,
        consumed=True,
        reverified=True,
    )["status"] == "BLOCKED_SCOPE_CONSUMPTION_NOT_REVERIFIED"
    mutation_ready = evaluate(
        **mutation_base,
        consumed=True,
        reverified=True,
        consumption_reverified=True,
    )
    assert mutation_ready["allowed"] is True
    assert mutation_ready["status"] == "READY_DURABLE_DRIVE"


def test_cli_preserves_normal_fallback_and_blocks_catchup() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        github_env = Path(tmp) / "github_env.txt"
        base_env = os.environ.copy()
        for key in (
            "GOOGLE_SERVICE_ACCOUNT_KEY",
            "RCLONE_CONFIG_GDRIVE",
            "GDRIVE_READY",
            "PAPER_CANONICAL_REMOTE_STATE",
            "PAPER_DURABLE_RESTORE_MODE",
            "RUN287_DURABLE_SCOPE_VERIFIED",
            "RUN287_DURABLE_ENVIRONMENT_ATTESTATION",
            "RUN287_DURABLE_ENVIRONMENT_NAME",
        ):
            base_env.pop(key, None)
        base_env["GITHUB_ENV"] = str(github_env)

        normal_env = dict(base_env, PAPER_CATCHUP_MODE="no")
        normal = subprocess.run(
            [sys.executable, str(TOOL), "--phase", "authentication"],
            cwd=ROOT,
            env=normal_env,
            check=False,
            capture_output=True,
            text=True,
        )
        assert normal.returncode == 0, normal.stderr
        assert github_env.read_text(encoding="utf-8") == "GDRIVE_READY=no\n"

        github_env.write_text("", encoding="utf-8")
        scope_missing_env = dict(base_env, PAPER_CATCHUP_MODE="yes")
        blocked_scope = subprocess.run(
            [sys.executable, str(TOOL), "--phase", "authentication"],
            cwd=ROOT,
            env=scope_missing_env,
            check=False,
            capture_output=True,
            text=True,
        )
        assert blocked_scope.returncode == 2
        assert "secret scope attestation was not verified" in (
            blocked_scope.stdout
        )

        catchup_env = dict(
            base_env,
            PAPER_CATCHUP_MODE="yes",
            RUN287_DURABLE_SCOPE_VERIFIED="yes",
        )
        blocked = subprocess.run(
            [sys.executable, str(TOOL), "--phase", "authentication"],
            cwd=ROOT,
            env=catchup_env,
            check=False,
            capture_output=True,
            text=True,
        )
        assert blocked.returncode == 2
        assert "durable Drive authentication is required" in blocked.stdout
        assert github_env.read_text(encoding="utf-8") == ""

        scoped_wrong = dict(
            catchup_env,
            RCLONE_CONFIG_GDRIVE="[gdrive]\ntype = drive\n",
            RUN287_DURABLE_ENVIRONMENT_NAME="run287-paper-durable",
            RUN287_DURABLE_ENVIRONMENT_ATTESTATION="not-the-attestation",
        )
        blocked_scope = subprocess.run(
            [sys.executable, str(TOOL), "--phase", "authentication"],
            cwd=ROOT,
            env=scoped_wrong,
            check=False,
            capture_output=True,
            text=True,
        )
        assert blocked_scope.returncode == 2
        assert "environment-scoped attestation" in blocked_scope.stdout
        assert "not-the-attestation" not in blocked_scope.stdout


def test_workflow_scope_and_order() -> None:
    workflow_text = WORKFLOW.read_text(encoding="utf-8")
    workflow = yaml.safe_load(workflow_text)
    steps = workflow["jobs"]["refresh"]["steps"]
    names = [str(step.get("name")) for step in steps]
    by_name = {str(step.get("name")): step for step in steps}
    for step in steps:
        run = step.get("run")
        if isinstance(run, str) and "${{" in run:
            assert len(run) < 20_000, (
                f"{step.get('name')} embeds GitHub expressions in a "
                f"{len(run)}-character run block; inject the values through "
                "env before GitHub's 21,000-character parser limit"
            )
    trigger = workflow.get("on") or workflow.get(True)
    inputs = trigger["workflow_dispatch"]["inputs"]
    assert len(inputs) == 10

    assert workflow["jobs"]["refresh"]["environment"] == (
        "run287-paper-durable"
    )
    assert workflow["jobs"]["refresh"]["env"][
        "RUN287_DURABLE_ENVIRONMENT_NAME"
    ] == "run287-paper-durable"
    assert (
        "catchup_secret_scope_attestation_comment_id" in inputs
    )
    assert workflow["permissions"]["issues"] == "write"
    assert "/actions/secrets?per_page=100" not in workflow_text
    assert "/environments/${DURABLE_ENVIRONMENT}/secrets" not in (
        workflow_text
    )

    scope_name = "Verify owner scope attestation for catch-up"
    scope_gate = by_name[scope_name]
    assert str(scope_gate["if"]) == (
        "steps.market.outputs.ready == 'yes' && "
        "steps.market.outputs.catchup_mode == 'yes'"
    )
    assert scope_gate["env"]["GH_TOKEN"] == "${{ github.token }}"
    assert scope_gate["env"]["SCOPE_COMMENT_ID"] == (
        "${{ inputs.catchup_secret_scope_attestation_comment_id }}"
    )
    assert "continue-on-error" not in scope_gate
    scope_run = scope_gate["run"]
    for token in (
        "/issues/comments/${SCOPE_COMMENT_ID}",
        "tools/verify_run287_catchup_scope_attestation.py",
        '--run "$RUN_EVIDENCE"',
        '--event "$GITHUB_EVENT_PATH"',
        '--expected-default-branch-sha "$GITHUB_SHA"',
        '--expected-session-date "$LAST_NYSE_SESSION_DATE"',
        '--expected-evidence-run-id "$EXPECTED_EVIDENCE_RUN_ID"',
        '--expected-workflow-run-id "$GITHUB_RUN_ID"',
        '--workflow-actor "$GITHUB_ACTOR"',
        '--github-env "$GITHUB_ENV"',
        "RUN287_DURABLE_SCOPE_INITIAL_SHA256",
    ):
        assert token in scope_run, token
    consume_name = "Consume owner scope attestation once"
    consume = by_name[consume_name]
    assert "continue-on-error" not in consume
    consume_run = consume["run"]
    for token in (
        "--paginate",
        "--slurp",
        "/issues/324/comments?per_page=100",
        "tools/run287_catchup_scope_consumption.py prepare",
        "--method POST",
        "tools/run287_catchup_scope_consumption.py verify",
        "RUN287_DURABLE_SCOPE_CONSUMPTION_RECORD_SHA256",
        "RUN287_DURABLE_SCOPE_CONSUMPTION_RECEIPT_SHA256",
        '--github-env "$GITHUB_ENV"',
    ):
        assert token in consume_run, token

    configure = by_name["Configure rclone"]
    configure_env = configure["env"]
    assert configure_env["GOOGLE_SERVICE_ACCOUNT_KEY"] == (
        "${{ secrets.RUN287_DURABLE_GOOGLE_SERVICE_ACCOUNT_KEY }}"
    )
    assert configure_env["RCLONE_CONFIG_GDRIVE"] == (
        "${{ secrets.RUN287_DURABLE_RCLONE_CONFIG_GDRIVE }}"
    )
    assert configure_env["RUN287_DURABLE_ENVIRONMENT_ATTESTATION"] == (
        "${{ secrets.RUN287_DURABLE_ENVIRONMENT_ATTESTATION }}"
    )
    assert "${{ secrets.GOOGLE_SERVICE_ACCOUNT_KEY }}" not in str(configure_env)
    assert "${{ secrets.RCLONE_CONFIG_GDRIVE }}" not in str(configure_env)
    configure_run = configure["run"]
    assert (
        "python tools/check_run287_catchup_drive_readiness.py"
        in configure_run
    )
    assert "--phase authentication" in configure_run
    assert configure_run.index(
        "python tools/check_run287_catchup_drive_readiness.py"
    ) < configure_run.index('if [ -z "${RCLONE_CONFIG_GDRIVE:-}" ]')
    assert "continue-on-error" not in configure

    guard_name = "Enforce durable Drive for chronological catch-up"
    guard = by_name[guard_name]
    assert str(guard["if"]) == (
        "steps.market.outputs.ready == 'yes' && "
        "steps.market.outputs.catchup_mode == 'yes'"
    )
    assert "continue-on-error" not in guard
    assert guard["env"]["RUN287_DURABLE_ENVIRONMENT_ATTESTATION"] == (
        "${{ secrets.RUN287_DURABLE_ENVIRONMENT_ATTESTATION }}"
    )
    assert guard["env"]["GOOGLE_SERVICE_ACCOUNT_KEY"] == (
        "${{ secrets.RUN287_DURABLE_GOOGLE_SERVICE_ACCOUNT_KEY }}"
    )
    assert guard["env"]["RCLONE_CONFIG_GDRIVE"] == (
        "${{ secrets.RUN287_DURABLE_RCLONE_CONFIG_GDRIVE }}"
    )
    assert (
        "python tools/check_run287_catchup_drive_readiness.py --phase restored"
        in guard["run"]
    )
    reverify_name = (
        "Reverify one-time scope attestation before local paper transaction"
    )
    reverify = by_name[reverify_name]
    assert "continue-on-error" not in reverify
    for token in (
        "--prior-verification \"$SCOPE_INITIAL\"",
        "tools/verify_run287_catchup_scope_attestation.py",
        "--prior-receipt \"$CONSUMPTION_INITIAL\"",
        "tools/run287_catchup_scope_consumption.py verify",
        "RUN287_DURABLE_SCOPE_CONSUMPTION_COMMENT_ID",
        "verify_receipt_hash",
        "RUN287_DURABLE_SCOPE_INITIAL_SHA256",
        "RUN287_DURABLE_SCOPE_CONSUMPTION_RECORD_SHA256",
        "RUN287_DURABLE_SCOPE_CONSUMPTION_RECEIPT_SHA256",
        "RUN287_DURABLE_SCOPE_PRE_TRANSACTION_SHA256",
        "RUN287_DURABLE_SCOPE_CONSUMPTION_PRE_TRANSACTION_SHA256",
    ):
        assert token in reverify["run"], token
    mutation_guard_name = (
        "Enforce one-time durable scope before local paper transaction"
    )
    mutation_guard = by_name[mutation_guard_name]
    assert "continue-on-error" not in mutation_guard
    assert (
        "tools/check_run287_catchup_drive_readiness.py --phase mutation"
        in mutation_guard["run"]
    )
    persist_reverify_name = (
        "Reverify one-time scope attestation before durable persistence"
    )
    persist_reverify = by_name[persist_reverify_name]
    assert persist_reverify["id"] == "durable_scope_persist_preflight"
    assert "continue-on-error" not in persist_reverify
    for token in (
        "RUN287_DURABLE_SCOPE_PRE_TRANSACTION_SHA256",
        "RUN287_DURABLE_SCOPE_CONSUMPTION_PRE_TRANSACTION_SHA256",
        "tools/verify_run287_catchup_scope_attestation.py",
        "tools/run287_catchup_scope_consumption.py verify",
        '--prior-verification "$SCOPE_INITIAL"',
        '--prior-receipt "$CONSUMPTION_INITIAL"',
        "run287_durable_scope_persist.json",
        "run287_durable_scope_consumption_persist.json",
        "RUN287_DURABLE_SCOPE_PRE_PERSIST_SHA256",
        "RUN287_DURABLE_SCOPE_CONSUMPTION_PRE_PERSIST_SHA256",
    ):
        assert token in persist_reverify["run"], token
    persist = by_name["Persist validated forward paper ledger state"]
    assert (
        "steps.durable_scope_persist_preflight.outcome == 'success'"
        in str(persist["if"])
    )
    assert (
        persist["env"]["ACCEPTED_PUBLICATION_MANIFEST_SHA256"]
        == "${{ steps.accepted_publication.outputs.manifest_sha256 }}"
    )
    assert "${{" not in persist["run"], (
        "large persistence script must receive step outputs through env; "
        "inline expressions make GitHub parse the full run block as one "
        "expression and can exceed the 21,000-character limit"
    )
    for token in (
        "RUN287_DURABLE_SCOPE_PRE_PERSIST_SHA256",
        "RUN287_DURABLE_SCOPE_CONSUMPTION_PRE_PERSIST_SHA256",
        "run287-durable-scope-comment-verification-v2",
        "run287-durable-scope-consumption-receipt-v1",
        "exact workflow-run lease expired before persistence start",
    ):
        assert token in persist["run"], token
    assert persist["run"].index(
        "exact workflow-run lease expired before persistence start"
    ) < persist["run"].index("assert_current_default_head()")
    restore = by_name["Restore persistent data and operating outputs"]
    restore_run = restore["run"]
    assert "PAPER_DURABLE_RESTORE_MODE=UNAVAILABLE" in restore_run
    assert "PAPER_DURABLE_RESTORE_MODE=IMMUTABLE_HEAD" in restore_run
    assert "PAPER_DURABLE_RESTORE_MODE=VERIFIED_CANONICAL" in restore_run
    assert (
        "PAPER_DURABLE_RESTORE_MODE=VERIFIED_LEGACY_MIGRATION_SOURCE"
        in restore_run
    )
    assert restore_run.index(
        "PAPER_DURABLE_RESTORE_MODE=UNAVAILABLE"
    ) < restore_run.index("PAPER_DURABLE_RESTORE_MODE=IMMUTABLE_HEAD")
    for assignment in (
        "PAPER_DURABLE_RESTORE_MODE=UNAVAILABLE",
        "PAPER_DURABLE_RESTORE_MODE=IMMUTABLE_HEAD",
        "PAPER_DURABLE_RESTORE_MODE=VERIFIED_CANONICAL",
        "PAPER_DURABLE_RESTORE_MODE=VERIFIED_LEGACY_MIGRATION_SOURCE",
    ):
        assert restore_run.count(assignment) == 1, assignment
    immutable_branch = restore_run.split(
        'if [ "$PAPER_HAS_IMMUTABLE_HEAD" = "yes" ]; then',
        1,
    )[1].split(
        'elif [ -s "$PAPER_REMOTE_CANDIDATE/snapshot_integrity.json" ]',
        1,
    )[0]
    assert "PAPER_DURABLE_RESTORE_MODE=IMMUTABLE_HEAD" in immutable_branch
    canonical_branch = restore_run.split(
        'elif [ -s "$PAPER_REMOTE_CANDIDATE/snapshot_integrity.json" ]',
        1,
    )[1].split(
        "elif [ -s outputs/daily_simulated_fill_ledger/snapshot_integrity.json ]",
        1,
    )[0]
    assert "PAPER_DURABLE_RESTORE_MODE=VERIFIED_CANONICAL" in (
        canonical_branch
    )
    legacy_branch = restore_run.split(
        'elif [ "$PAPER_CANONICAL_REMOTE_PRESENT" = "yes" ]',
        1,
    )[1].split(
        'elif [ "$PAPER_CANONICAL_REMOTE_PRESENT" = "no" ]',
        1,
    )[0]
    assert (
        "PAPER_DURABLE_RESTORE_MODE=VERIFIED_LEGACY_MIGRATION_SOURCE"
        in legacy_branch
    )
    assert (
        names.index(scope_name)
        < names.index(consume_name)
        < names.index("Configure rclone")
        < names.index("Restore persistent data and operating outputs")
        < names.index(guard_name)
        < names.index(reverify_name)
        < names.index(mutation_guard_name)
        < names.index("Run transactional paper ledger and same-close selector")
        < names.index(persist_reverify_name)
        < names.index("Persist validated forward paper ledger state")
    )


def main() -> int:
    test_environment_attestation_contract()
    test_behavior_matrix()
    test_cli_preserves_normal_fallback_and_blocks_catchup()
    test_workflow_scope_and_order()
    print("run287_catchup_drive_readiness_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
