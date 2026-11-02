#!/usr/bin/env python3
"""Smoke coverage for the Run287 review-complete merge gate."""

from __future__ import annotations

import json
import hashlib
import importlib.util
from copy import deepcopy
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "check_pr_review_complete.py"
WORKFLOW = ROOT / ".github" / "workflows" / "review_complete_gate.yml"
CONTRACT = ROOT / "data_static" / "run287_review_complete_gate_contract.json"
HEAD = "a" * 40
PRIOR = "b" * 40
spec = importlib.util.spec_from_file_location("review_complete_gate_under_test", TOOL)
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


class CommentReceiptTests(unittest.TestCase):
    def fixture(self):
        repository, number = "wscha231/r1000-quant-engine", 709
        def comment(cid, body, created, updated=None):
            return dict(id=cid, body=body, created_at=created, updated_at=updated or created,
                issue_url=f"https://api.github.com/repos/{repository}/issues/{number}",
                user=dict(login="chatgpt-codex-connector[bot]", id=199175422, type="Bot"),
                performed_via_github_app=dict(id=1144995, slug="chatgpt-codex-connector"))
        state = dict(code_review=dict(commit_sha=HEAD, status="completed", has_any_findings=None,
            has_unresolved_findings=None), security_review=dict(commit_sha=None, status=None))
        summary = comment(6553560183, "<!-- codex-pull-request-review-summary -->\n<!-- codex-review-state:v1 "
            +json.dumps(state)+" -->", "2026-07-20T01:00:00Z", "2026-07-21T01:10:03Z")
        receipt = comment(6579005459, "<!-- codex-review-receipt:v1 -->\n\n"
            "Codex Review: Didn't find any major issues. More of your lovely PRs please.\n\n"
            f"**Reviewed commit:** `{HEAD[:10]}`\n\n<details>About Codex</details>", "2026-07-21T01:10:00Z")
        pages = [dict(data=dict(repository=dict(nameWithOwner=repository, pullRequest=dict(number=number,
            headRefOid=HEAD, reviewThreads=dict(totalCount=1, nodes=[dict(id="THREAD:1", isResolved=True)],
            pageInfo=dict(hasNextPage=False, endCursor="CURSOR:1"))))))]
        return dict(pull_request=dict(number=number, draft=False, head=dict(sha=HEAD),
                    base=dict(repo=dict(full_name=repository))),
            head_observation=dict(head_sha=HEAD, observed_at="2026-07-21T01:00:00Z", check_run_id=11),
            attestation=dict(head_sha=HEAD, created_at="2026-07-21T01:20:00Z", actor="maintainer", permission="write"),
            reviews=[], reactions=[], issue_comments=[summary, receipt], review_comments=[],
            review_thread_pages=pages, repository=repository,
            commit_binding=dict(repository=repository, requested_prefix=HEAD[:10], sha=HEAD,
                url=f"https://api.github.com/repos/{repository}/commits/{HEAD}"))

    def blocked(self, args):
        result = gate.evaluate(**args)
        self.assertIs(result["passed"], False)
        self.assertIsNone(result["comment_receipt_binding"])
        self.assertIn("no_codex_evidence_for_current_head", result["failures"])
        return result

    def change_state(self, args, **changes):
        row = args["issue_comments"][0]
        state = gate._summary_state(row["body"])
        state["code_review"].update(changes)
        row["body"] = "<!-- codex-pull-request-review-summary -->\n<!-- codex-review-state:v1 "+json.dumps(state)+" -->"

    def test_paired_null_summary_explicit_receipt_records_exact_binding(self):
        args = self.fixture(); result = gate.evaluate(**args)
        self.assertIs(result["passed"], True)
        self.assertEqual(result["evidence_type"], gate.COMMENT_EVIDENCE)
        binding = result["comment_receipt_binding"]
        self.assertEqual(binding["head_sha"], HEAD)
        self.assertEqual(binding["receipt_comment_id"], 6579005459)
        self.assertEqual(binding["summary_comment_id"], 6553560183)
        self.assertIsNone(binding["summary_finding_flags"]["has_any_findings"])
        self.assertEqual(binding["receipt_body_sha256"], hashlib.sha256(args["issue_comments"][1]["body"].encode()).hexdigest())
        self.assertEqual(binding["resolved_thread_count"], 1)

    def test_trusted_identity_scope_and_commit_expansion_matrix(self):
        for mutate in (
            lambda a: a["issue_comments"][1]["user"].update(id=True),
            lambda a: a["issue_comments"][1]["user"].update(id=1),
            lambda a: a["issue_comments"][1]["user"].update(type="User"),
            lambda a: a["issue_comments"][1]["performed_via_github_app"].update(id="1144995"),
            lambda a: a["issue_comments"][1]["performed_via_github_app"].update(id=True),
            lambda a: a["issue_comments"][1]["performed_via_github_app"].update(slug="other"),
            lambda a: a["issue_comments"][1].update(issue_url="https://api.github.com/repos/other/repo/issues/709"),
            lambda a: a["commit_binding"].update(sha=PRIOR),
            lambda a: a["commit_binding"].update(requested_prefix=PRIOR[:10]),
            lambda a: a["commit_binding"].update(url=f"https://api.github.com/repos/other/repo/commits/{HEAD}"),
            lambda a: a.update(commit_binding=None),
        ):
            with self.subTest(mutate=mutate):
                args=self.fixture(); mutate(args); self.blocked(args)

    def test_summary_alone_pending_old_head_true_and_nonboolean_flags_refuse(self):
        args=self.fixture(); args["issue_comments"].pop(); self.blocked(args)
        args=self.fixture(); args["issue_comments"].pop(0); self.blocked(args)
        for changes in (dict(status="running"), dict(status="pending"), dict(commit_sha=PRIOR),
                        dict(has_any_findings=True), dict(has_unresolved_findings=True),
                        dict(has_any_findings=0), dict(has_unresolved_findings="false")):
            with self.subTest(changes=changes):
                args=self.fixture(); self.change_state(args, **changes); self.blocked(args)
        args=self.fixture(); self.change_state(args, has_any_findings=False, has_unresolved_findings=False)
        self.assertIs(gate.evaluate(**args)["passed"], True)
        args=self.fixture(); later=deepcopy(args["issue_comments"][0]); later.update(id=20, updated_at="2026-07-21T01:12:00Z")
        self.change_state({"issue_comments": [later]}, status="running")
        args["issue_comments"].append(later)
        self.blocked(args)

    def test_modified_future_old_or_ambiguous_receipt_is_not_a_clean_pair(self):
        for key, value in (("updated_at", "2026-07-21T01:10:01Z"),
                           ("created_at", "2026-07-21T00:59:59Z"),
                           ("created_at", "2026-07-21T01:21:00Z"),
                           ("body", "<!-- codex-review-receipt:v1 -->\nNo issues")):
            args=self.fixture(); args["issue_comments"][1][key]=value; self.blocked(args)
        for at in ("2026-07-21T00:59:59Z", "2026-07-21T01:21:00Z", "2026-07-21T01:10:03"):
            args=self.fixture(); args["issue_comments"][0]["updated_at"]=at; self.blocked(args)
        args=self.fixture(); newer=deepcopy(args["issue_comments"][1]); newer.update(id=10, updated_at="2026-07-21T01:11:00Z")
        args["issue_comments"].append(newer); self.blocked(args)

    def test_newer_findings_or_blocking_review_refuse(self):
        args=self.fixture(); args["review_comments"]=[dict(user=user(), commit_id=HEAD,
            body="<!-- codex-code-review-finding:v1 -->", updated_at="2026-07-21T01:11:00Z")]
        self.blocked(args)
        for state in ("CHANGES_REQUESTED", "PENDING", "COMMENTED"):
            args=self.fixture(); args["reviews"]=[dict(user=user(), commit_id=HEAD, state=state,
                submitted_at="2026-07-21T01:11:00Z")]
            # The new path is tested directly: the unchanged legacy COMMENTED
            # review route remains independently covered below.
            with self.assertRaisesRegex(ValueError, "newer_or_blocking_codex_review"):
                gate.paired_comment_evidence(comments=args["issue_comments"], review_comments=[],
                    thread_pages=args["review_thread_pages"], commit_binding=args["commit_binding"],
                    repository=args["repository"], pull_request=args["pull_request"], head_sha=HEAD,
                    observed_at=gate.parse_time("2026-07-21T01:00:00Z"),
                    attested_at=gate.parse_time("2026-07-21T01:20:00Z"), reviews=args["reviews"])

    def test_threads_require_exact_head_scope_booleans_and_complete_pages(self):
        for mutate in (
            lambda p: p[0].update(errors=[dict(message="partial")]),
            lambda p: p[0]["data"]["repository"].update(nameWithOwner="other/repo"),
            lambda p: p[0]["data"]["repository"]["pullRequest"].update(headRefOid=PRIOR),
            lambda p: p[0]["data"]["repository"]["pullRequest"]["reviewThreads"]["nodes"][0].update(isResolved=False),
            lambda p: p[0]["data"]["repository"]["pullRequest"]["reviewThreads"]["nodes"][0].update(isResolved=None),
            lambda p: p[0]["data"]["repository"]["pullRequest"]["reviewThreads"]["pageInfo"].update(hasNextPage=True),
            lambda p: p[0]["data"]["repository"]["pullRequest"]["reviewThreads"].update(totalCount=2),
        ):
            args=self.fixture(); mutate(args["review_thread_pages"]); self.blocked(args)
        args=self.fixture(); args["review_thread_pages"]=[]; self.blocked(args)
        args=self.fixture(); first=args["review_thread_pages"][0]
        conn=first["data"]["repository"]["pullRequest"]["reviewThreads"]
        conn["nodes"]=[dict(id=f"THREAD:{i}",isResolved=True) for i in range(100)]
        conn["totalCount"]=101
        conn["pageInfo"]["hasNextPage"]=True
        last=deepcopy(first); lastconn=last["data"]["repository"]["pullRequest"]["reviewThreads"]
        lastconn["nodes"]=[dict(id="THREAD:LAST", isResolved=True)]
        lastconn["pageInfo"]["hasNextPage"]=False
        args["review_thread_pages"].append(last); self.blocked(args)  # repeated cursor
        lastconn["pageInfo"]["endCursor"]="CURSOR:2"
        self.assertIs(gate.evaluate(**args)["passed"], True)

    def test_maintainer_gate_is_not_replaced_and_legacy_evidence_still_works(self):
        for change in (dict(permission="read"), dict(head_sha=PRIOR)):
            args=self.fixture(); args["attestation"].update(change)
            self.assertIs(gate.evaluate(**args)["passed"], False)
        args=self.fixture(); args["issue_comments"]=None
        args["reviews"]=[dict(id=1,user=user(),commit_id=HEAD,state="COMMENTED",submitted_at="2026-07-21T01:05:00Z")]
        self.assertEqual(gate.evaluate(**args)["evidence_type"], "ATTESTED_EXACT_HEAD_REVIEW")

    def test_workflow_and_contract_preserve_protected_default_branch_boundary(self):
        contract=json.loads(CONTRACT.read_text(encoding="utf-8"))
        self.assertEqual(contract["required_status_checks"], ["validate", "portfolio_guard", "review_complete"])
        self.assertIs(contract["required_conversation_resolution"], True)
        self.assertIs(contract["maintainer_attestation_required"], True)
        self.assertIs(contract["admin_merge_bypass_allowed"], False)
        self.assertIn(gate.COMMENT_EVIDENCE, contract["accepted_evidence"])
        workflow=WORKFLOW.read_text(encoding="utf-8")
        self.assertIn('ref: ${{ github.event.repository.default_branch }}', workflow)
        self.assertIn('reviewThreads(first:100,after:$endCursor)', workflow)
        self.assertIn('gh api graphql --paginate --slurp', workflow)
        self.assertIn('/commits/${HEAD_SHA:0:10}', workflow)
        self.assertNotIn('ref: ${{ github.event.pull_request.head.sha }}', workflow)


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
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(CommentReceiptTests))
    raise SystemExit(0 if result.wasSuccessful() else 1)
