#!/usr/bin/env python3
"""Smoke coverage for the Run287 review-complete merge gate."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "check_pr_review_complete.py"
WORKFLOW = ROOT / ".github" / "workflows" / "review_complete_gate.yml"
CONTRACT = ROOT / "data_static" / "run287_review_complete_gate_contract.json"
HEAD = "a" * 40
PRIOR = "b" * 40


def user(login: str = "chatgpt-codex-connector[bot]") -> dict[str, str]:
    return {"login": login}


def run_case(
    root: Path,
    *,
    reviews: list[dict] | list[list[dict]],
    reactions: list[dict] | list[list[dict]],
    draft: bool = False,
    observation: dict | None = None,
    attestation: dict | None = None,
    include_attestation: bool = True,
) -> tuple[int, dict]:
    inputs = {
        "pr.json": {"number": 315, "draft": draft, "head": {"sha": HEAD}},
        "observation.json": observation or {
            "head_sha": HEAD,
            "observed_at": "2026-07-21T01:00:00Z",
            "check_run_id": 11,
        },
        "reviews.json": reviews,
        "reactions.json": reactions,
    }
    if include_attestation:
        inputs["attestation.json"] = attestation or {
                "head_sha": HEAD,
                "created_at": "2026-07-21T01:20:00Z",
                "actor": "maintainer",
                "permission": "write",
                "source": "issue_comment",
            }
    for name, payload in inputs.items():
        (root / name).write_text(json.dumps(payload), encoding="utf-8")
    output = root / "result.json"
    command = [
            sys.executable,
            str(TOOL),
            "--pull-request", str(root / "pr.json"),
            "--head-observation", str(root / "observation.json"),
            "--reviews", str(root / "reviews.json"),
            "--reactions", str(root / "reactions.json"),
            "--output", str(output),
        ]
    if include_attestation:
        command.extend(["--attestation", str(root / "attestation.json")])
    proc = subprocess.run(
        command,
        capture_output=True,
        text=True,
    )
    return proc.returncode, json.loads(output.read_text(encoding="utf-8"))


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)

        code, payload = run_case(
            root,
            reviews=[{
                "id": 1,
                "state": "COMMENTED",
                "commit_id": HEAD,
                "submitted_at": "2026-07-21T01:05:00Z",
                "user": user(),
            }],
            reactions=[],
        )
        assert code == 0
        assert payload["status"] == "PASS_REVIEW_COMPLETE"
        assert payload["evidence_type"] == "ATTESTED_EXACT_HEAD_REVIEW"

        code, payload = run_case(
            root,
            reviews=[[{
                "id": 2,
                "state": "COMMENTED",
                "commit_id": PRIOR,
                "submitted_at": "2026-07-21T01:05:00Z",
                "user": user(),
            }]],
            reactions=[],
        )
        assert code == 2
        assert "no_codex_evidence_for_current_head" in payload["failures"]

        code, payload = run_case(
            root,
            reviews=[],
            reactions=[[{
                "id": 3,
                "content": "+1",
                "created_at": "2026-07-21T01:10:00Z",
                "user": user(),
            }]],
        )
        assert code == 0
        assert payload["evidence_type"] == "MAINTAINER_BOUND_CLEAN_REACTION"

        for content, created_at in (("eyes", "2026-07-21T01:10:00Z"), ("+1", "2026-07-21T00:59:59Z")):
            code, payload = run_case(
                root,
                reviews=[],
                reactions=[{
                    "id": 4,
                    "content": content,
                    "created_at": created_at,
                    "user": user(),
                }],
            )
            assert code == 2
            assert payload["passed"] is False

        code, payload = run_case(
            root,
            reviews=[{
                "id": 5,
                "state": "DISMISSED",
                "commit_id": HEAD,
                "submitted_at": "2026-07-21T01:05:00Z",
                "user": user(),
            }],
            reactions=[],
            draft=True,
        )
        assert code == 2
        assert set(payload["failures"]) == {
            "no_codex_evidence_for_current_head",
            "pull_request_is_draft",
        }

        code, payload = run_case(
            root,
            reviews=[{
                "id": 6,
                "state": "COMMENTED",
                "commit_id": HEAD,
                "submitted_at": "2026-07-21T01:05:00Z",
                "user": user(),
            }],
            reactions=[],
            observation={
                "head_sha": HEAD,
                "observed_at": "2026-07-21T01:10:00Z",
                "check_run_id": 12,
            },
        )
        assert code == 2
        assert "no_codex_evidence_for_current_head" in payload["failures"]

        code, payload = run_case(
            root,
            reviews=[],
            reactions=[{
                "id": 7,
                "content": "+1",
                "created_at": "2026-07-21T01:10:00Z",
                "user": user(),
            }],
            observation={
                "head_sha": PRIOR,
                "observed_at": "2026-07-21T01:00:00Z",
                "check_run_id": 13,
            },
        )
        assert code == 2
        assert "head_observation_sha_mismatch" in payload["failures"]

        code, payload = run_case(
            root,
            reviews=[],
            reactions=[{
                "id": 8,
                "content": "+1",
                "created_at": "2026-07-21T01:10:00Z",
                "user": user(),
            }],
            attestation={
                "head_sha": HEAD,
                "created_at": "2026-07-21T01:20:00Z",
                "actor": "reader",
                "permission": "read",
                "source": "issue_comment",
            },
        )
        assert code == 2
        assert "attestor_lacks_write_permission" in payload["failures"]

        code, payload = run_case(
            root,
            reviews=[{
                "id": 9,
                "state": "COMMENTED",
                "commit_id": HEAD,
                "submitted_at": "2026-07-21T01:05:00Z",
                "user": user(),
            }],
            reactions=[],
            include_attestation=False,
        )
        assert code == 2
        assert "missing_maintainer_attestation" in payload["failures"]

    workflow = WORKFLOW.read_text(encoding="utf-8")
    for required in (
        "pull_request_target:",
        "issue_comment:",
        "checks: write",
        "review_complete",
        "review_head_observed",
        "tools/check_pr_review_complete.py",
        "/review-complete $HEAD_SHA",
        "collaborators/$ACTOR/permission",
    ):
        assert required in workflow, required
    assert "pull_request_review:" not in workflow

    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    assert contract["required_status_checks"] == ["validate", "portfolio_guard", "review_complete"]
    assert contract["required_conversation_resolution"] is True
    assert contract["enforce_admins"] is True
    assert contract["maintainer_attestation_required"] is True
    assert contract["automatic_merge_allowed"] is False
    print("run287 review-complete gate smoke: PASS")


if __name__ == "__main__":
    main()
