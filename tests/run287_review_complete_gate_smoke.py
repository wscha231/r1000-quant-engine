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
ACTUAL_ABOUT_DETAILS = '''<details> <summary>ℹ️ About Codex in GitHub</summary>
<br/>

[Your team has set up Codex to review pull requests in this repo](https://chatgpt.com/codex/cloud/settings/general). Reviews are triggered when you
- Open a pull request for review
- Mark a draft as ready
- Comment "@codex review".

If Codex has suggestions, it will comment; otherwise it will react with 👍.


Codex can also answer questions or update the PR. Try commenting "@codex address that feedback".

</details>'''
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
            f"**Reviewed commit:** `{HEAD[:10]}`\n\n"+ACTUAL_ABOUT_DETAILS, "2026-07-21T01:10:00Z")
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

    def pin_fixture(self, decoration="Delightful!"):
        args = self.fixture()
        args["issue_comments"][1]["body"] = args["issue_comments"][1]["body"].replace("More of your lovely PRs please.", decoration)
        args["attestation"].update(source="issue_comment", actor_id=73)
        comment = dict(id=9001, body="", created_at=args["attestation"]["created_at"], updated_at=args["attestation"]["created_at"],
            issue_url="https://api.github.com/repos/"+args["repository"]+"/issues/709", user=dict(login="maintainer", id=73, type="User"))
        args["attestation_comment"] = comment
        args["attestation_event"] = dict(action="created", repository=dict(full_name=args["repository"]),
            issue=dict(number=709, pull_request=dict(url="https://api.github.com/repos/"+args["repository"]+"/pulls/709")),
            sender=dict(login="maintainer", id=73), comment=deepcopy(comment))
        self.repin(args)
        return args

    def repin(self, args, *, receipt_id=None, digest=None):
        receipt = args["issue_comments"][1]
        pin = dict(receipt_comment_id=receipt["id"] if receipt_id is None else receipt_id,
            receipt_body_sha256=hashlib.sha256(receipt["body"].encode("utf-8")).hexdigest() if digest is None else digest)
        args["attestation"]["receipt_pin"] = pin
        command = f"/review-complete {HEAD} codex-receipt {pin['receipt_comment_id']} sha256:{pin['receipt_body_sha256']}"
        args["attestation_comment"]["body"] = command
        args["attestation_event"]["comment"]["body"] = command

    def test_pinned_receipt_keeps_v2_and_all_clean_evidence_bindings(self):
        for token in ("Delightful!", "Hooray!", "A!", "a"*32+"!", ":rocket:", "Keep it up!"):
            args = self.pin_fixture(token); result = gate.evaluate(**args)
            self.assertIs(result["passed"], True, token)
            self.assertEqual(result["schema_version"], "run287-review-complete-gate-v2")
            self.assertEqual(result["evidence_type"], gate.COMMENT_EVIDENCE)
            binding = result["comment_receipt_binding"]
            self.assertEqual(binding["pin_binding"]["maintainer_comment_id"], 9001)
            self.assertEqual(binding["pin_binding"]["maintainer_user_id"], 73)
            self.assertEqual(binding["pin_binding"]["receipt_body_sha256"], binding["receipt_body_sha256"])
            self.assertIsNone(binding["summary_finding_flags"]["has_any_findings"])
        args = self.pin_fixture()
        args.pop("attestation_comment"); args.pop("attestation_event"); args["attestation"].pop("receipt_pin")
        self.blocked(args)  # No unpinned decoration broadening.

    def test_pinned_terminal_punctuation_is_one_bounded_ascii_token(self):
        for token in ("Bravo.", "A.", "z"*32+".", "Bravo!", "A!", "z"*32+"!"):
            self.assertIs(gate.evaluate(**self.pin_fixture(token))["passed"], True, token)
        for token in (".", "!", "Bravo..", "Bravo.!", "Bravo!.", "Bravo. More.", "A. B.",
            "Bravo.Next.", "a"*33+".", "123.", "Brav0.", "Bravo_.", "Bravo-.", "Brav\u00f3.",
            "Bravo\u2024", "<b>Bravo.</b>", "Bravo.\nAnother sentence", "Bravo. [P1] finding"):
            self.blocked(self.pin_fixture(token))
        for token in ("Bravo.", "Bravo!"):
            args = self.pin_fixture(token)
            args.pop("attestation_comment"); args.pop("attestation_event"); args["attestation"].pop("receipt_pin")
            self.blocked(args)  # Bare/unpinned grammar is unchanged.
        args = self.pin_fixture("Bravo.")
        args["reactions"] = [dict(id=99, user=user(), content="+1", created_at="2026-07-21T01:05:00Z")]
        self.repin(args, digest="0"*64)
        self.blocked(args)  # Explicit bad dot pin cannot use a legacy fallback.

    def test_explicit_bad_pin_never_falls_back_to_formal_review_or_reaction(self):
        for legacy in ("review", "reaction"):
            for mode in ("hash", "id", "dto", "dispatch", "extra"):
                args = self.pin_fixture()
                if legacy == "review":
                    args["reviews"] = [dict(id=99, user=user(), commit_id=HEAD, state="COMMENTED", submitted_at="2026-07-21T01:05:00Z")]
                else:
                    args["reactions"] = [dict(id=99, user=user(), content="+1", created_at="2026-07-21T01:05:00Z")]
                if mode == "hash": self.repin(args, digest="0"*64)
                if mode == "id": self.repin(args, receipt_id=123)
                if mode == "dto": args.pop("attestation_comment"); args.pop("attestation_event")
                if mode == "dispatch": args["attestation"]["source"] = "workflow_dispatch"
                if mode == "extra": args["attestation"]["receipt_pin"]["unknown"] = True
                self.blocked(args)

    def test_pin_requires_actual_immutable_same_pr_actor_and_exact_event_body(self):
        for mutate in (
            lambda a: a["attestation"].update(permission="read"),
            lambda a: a["attestation"].update(actor_id=True),
            lambda a: a["attestation"].update(actor="other"),
            lambda a: a["attestation_comment"].update(id=True),
            lambda a: a["attestation_comment"]["user"].update(id=True),
            lambda a: a["attestation_comment"]["user"].update(type="Bot"),
            lambda a: a["attestation_comment"].update(updated_at="2026-07-21T01:20:01Z"),
            lambda a: a["attestation_comment"].update(issue_url="https://api.github.com/repos/other/repo/issues/709"),
            lambda a: a["attestation_event"].update(action="edited"),
            lambda a: a["attestation_event"]["repository"].update(full_name="other/repo"),
            lambda a: a["attestation_event"]["issue"].update(number=710),
            lambda a: a["attestation_event"]["sender"].update(id=74),
            lambda a: a["attestation_event"]["comment"].update(body="other"),
            lambda a: a["attestation_event"]["comment"]["user"].update(login="other"),
            lambda a: a.update(attestation_comment=None),
        ):
            args = self.pin_fixture(); mutate(args); self.blocked(args)
        for suffix in (" extra", "\n", "\r\n", " ", "\nmore"):
            args = self.pin_fixture()
            args["attestation_comment"]["body"] += suffix; args["attestation_event"]["comment"]["body"] += suffix
            self.blocked(args)
        for bad_id in ("0", "01", "-1", "true", str(2**63)):
            with self.assertRaises(ValueError):
                gate.parse_review_complete_command(f"/review-complete {HEAD} codex-receipt {bad_id} sha256:"+"a"*64, HEAD)

    def test_pinned_body_raw_hash_and_bounded_fullmatch_are_independent(self):
        args = self.pin_fixture(); args["issue_comments"][1]["body"] += " "
        self.blocked(args)
        args = self.pin_fixture(); args["issue_comments"][1]["body"] = args["issue_comments"][1]["body"].replace("\n", "\r\n")
        self.blocked(args)
        self.repin(args); self.assertIs(gate.evaluate(**args)["passed"], True)
        for token in ("Too many words!", "a"*33+"!", "Delightful!!", "123!", "D\u0435lightful!", "A! B!",
            "Delightful! :rocket:", "<b>Delightful!</b>", "Delightful!\nAdditional text", "[P1] finding"):
            self.blocked(self.pin_fixture(token))
        for mutate in (lambda b: b+"\nextra", lambda b: b.replace("</details>", "[P2] issue</details>"),
            lambda b: b.replace(ACTUAL_ABOUT_DETAILS, "<details>other footer</details>"),
            lambda b: b+"\n<!-- codex-code-review-finding:v1 -->",
            lambda b: b.replace("Didn't find", "Did find")):
            args = self.pin_fixture(); args["issue_comments"][1]["body"] = mutate(args["issue_comments"][1]["body"])
            self.repin(args); self.blocked(args)

    def test_pin_cannot_cherry_pick_or_relax_common_review_requirements(self):
        for mutate in (
            lambda a: a["issue_comments"][1]["user"].update(id=1),
            lambda a: a["issue_comments"][1]["performed_via_github_app"].update(id=1),
            lambda a: a["issue_comments"][1].update(updated_at="2026-07-21T01:10:01Z"),
            lambda a: self.change_state(a, status="running"),
            lambda a: self.change_state(a, has_any_findings=True),
            lambda a: self.change_state(a, has_unresolved_findings="false"),
            lambda a: a["commit_binding"].update(sha=PRIOR),
            lambda a: a.update(commit_binding=None),
            lambda a: a["review_thread_pages"][0]["data"]["repository"]["pullRequest"]["reviewThreads"]["nodes"][0].update(isResolved=False),
            lambda a: a["review_thread_pages"][0]["data"]["repository"]["pullRequest"]["reviewThreads"].update(totalCount=2),
        ):
            args = self.pin_fixture(); mutate(args); self.blocked(args)
        for kind in ("summary", "receipt"):
            args = self.pin_fixture(); target = 0 if kind == "summary" else 1
            duplicate = deepcopy(args["issue_comments"][target]); duplicate["id"] += 1
            args["issue_comments"].append(duplicate); self.blocked(args)
        args = self.pin_fixture(); newer = deepcopy(args["issue_comments"][1])
        newer.update(id=10000, created_at="2026-07-21T01:11:00Z", updated_at="2026-07-21T01:11:00Z")
        args["issue_comments"].append(newer); self.blocked(args)
        args = self.pin_fixture(); state = gate._summary_state(args["issue_comments"][0]["body"])
        state["security_review"] = dict(commit_sha=HEAD, status="running", has_any_findings=None, has_unresolved_findings=None)
        args["issue_comments"][0]["body"] = "<!-- codex-pull-request-review-summary -->\n<!-- codex-review-state:v1 "+json.dumps(state)+" -->"
        self.blocked(args)
        args = self.pin_fixture(); args["review_comments"] = [dict(user=user(), commit_id=HEAD,
            body="<!-- codex-code-review-finding:v1 -->", updated_at="2026-07-21T01:11:00Z")]
        self.blocked(args)

        for key in ("has_any_findings", "has_unresolved_findings"):
            args = self.pin_fixture(); state = gate._summary_state(args["issue_comments"][0]["body"])
            state["code_review"].pop(key)
            args["issue_comments"][0]["body"] = "<!-- codex-pull-request-review-summary -->\n<!-- codex-review-state:v1 "+json.dumps(state)+" -->"
            self.blocked(args)
        for review_state in ("PENDING", "CHANGES_REQUESTED", "COMMENTED"):
            args = self.pin_fixture(); args["reviews"] = [dict(user=user(), commit_id=HEAD,
                state=review_state, submitted_at="2026-07-21T01:11:00Z")]
            self.blocked(args)

    def test_pinned_cli_requires_collected_api_snapshots_and_records_binding(self):
        args = self.pin_fixture()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            command = [sys.executable, "-B", str(TOOL), "--repository", args["repository"]]
            for key, option in (("pull_request", "pull-request"), ("head_observation", "head-observation"),
                    ("attestation", "attestation"), ("reviews", "reviews"), ("reactions", "reactions"),
                    ("issue_comments", "issue-comments"), ("review_comments", "review-comments"),
                    ("review_thread_pages", "review-threads"), ("commit_binding", "commit-binding"),
                    ("attestation_comment", "attestation-comment"), ("attestation_event", "attestation-event")):
                path = root / (key+".json")
                path.write_text(json.dumps(args[key]), encoding="utf-8")
                command.extend(["--"+option, str(path)])
            result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", check=False)
            self.assertEqual(result.returncode, 0, result.stderr+result.stdout)
            self.assertEqual(json.loads(result.stdout)["comment_receipt_binding"]["pin_binding"]["maintainer_comment_id"], 9001)
            result = subprocess.run(command[:-4], capture_output=True, text=True, encoding="utf-8", check=False)
            self.assertEqual(result.returncode, 2, result.stderr+result.stdout)
            self.assertIn("missing_authenticated_pin_comment", json.loads(result.stdout)["failures"])

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

    def test_latest_summary_and_receipt_timestamp_ties_refuse_in_both_orders(self):
        args=self.fixture(); clean=args["issue_comments"][0]; pending=deepcopy(clean); pending["id"]=30
        self.change_state({"issue_comments": [pending]}, status="pending")
        for pair in ((clean,pending),(pending,clean),(clean,deepcopy(clean))):
            case=self.fixture(); case["issue_comments"]=list(pair)+[case["issue_comments"][1]]
            self.blocked(case)
        args=self.fixture(); clean=args["issue_comments"][1]; bad=deepcopy(clean); bad["id"]=31
        bad["body"]=bad["body"].replace("More of your lovely PRs please.", "[P1] unresolved issue.")
        for pair in ((clean,bad),(bad,clean),(clean,deepcopy(clean))):
            case=self.fixture(); case["issue_comments"]=[case["issue_comments"][0]]+list(pair)
            self.blocked(case)

    def test_clean_line_and_optional_about_footer_accept_only_observed_formats(self):
        for cheer in ("Keep it up!", "Breezy!", ":rocket:", ":tada:", ":a:",
                      ":party_2026:", ":" + "a" * 32 + ":", ""):
            args=self.fixture(); row=args["issue_comments"][1]
            row["body"]=row["body"].replace(" More of your lovely PRs please.", " "+cheer if cheer else "")
            self.assertIs(gate.evaluate(**args)["passed"], True)
        for mutate in (
            lambda b: b.replace("More of your lovely PRs please.", "[P1] unresolved issuer bug"),
            lambda b: b.replace("More of your lovely PRs please.", "Unreviewed arbitrary trailing claim."),
            lambda b: b.replace("</details>", "[P2] unresolved finding</details>"),
            lambda b: b.replace("</details>", "Additional unreviewed claim</details>"),
            lambda b: b.replace(ACTUAL_ABOUT_DETAILS, "<details>About Codex</details>"),
            lambda b: b+"\n<!-- codex-code-review-finding:v1 -->",
        ):
            case=self.fixture(); row=case["issue_comments"][1]; row["body"]=mutate(row["body"])
            self.blocked(case)

    def test_shortcodes_are_one_bounded_ascii_decoration_not_free_text(self):
        for suffix in (":rocket: extra", "extra :tada:", ":rocket::tada:", ":rocket: :tada:",
                       ":" + "a" * 33 + ":", "::", ":1rocket:", ":_rocket:", ":Rocket:",
                       ":rocket-ship:", ":r\u043ecket:", "\U0001f680", ":rocket:\n:tada:",
                       "Breezy! extra", "You rock!", "Keep it up! :rocket:",
                       ":rocket: [P1] unresolved issue", ":rocket:\nExtra finding"):
            with self.subTest(suffix=suffix):
                args=self.fixture()
                row=args["issue_comments"][1]
                row["body"]=row["body"].replace("More of your lovely PRs please.", suffix)
                self.blocked(args)

    def test_valid_shortcode_never_replaces_identity_clock_finding_or_thread_checks(self):
        for mutate in (
            lambda a: a["issue_comments"][1]["user"].update(id=1),
            lambda a: a["issue_comments"][1]["performed_via_github_app"].update(id=1),
            lambda a: a["issue_comments"][1].update(updated_at="2026-07-21T01:10:01Z"),
            lambda a: a["head_observation"].update(observed_at="2026-07-21T01:11:00Z"),
            lambda a: self.change_state(a, has_any_findings=True),
            lambda a: a["commit_binding"].update(sha=PRIOR),
            lambda a: a["review_thread_pages"][0]["data"]["repository"]["pullRequest"]["reviewThreads"]["nodes"][0].update(isResolved=False),
        ):
            args=self.fixture()
            row=args["issue_comments"][1]
            row["body"]=row["body"].replace("More of your lovely PRs please.", ":rocket:")
            mutate(args)
            self.blocked(args)
        for priority in range(4):
            for location in (":rocket:", f"`{HEAD[:10]}`", "</details>"):
                args=self.fixture(); row=args["issue_comments"][1]
                row["body"]=row["body"].replace("More of your lovely PRs please.", ":rocket:")
                row["body"]=row["body"].replace(location, location + f" [P{priority}] finding")
                self.blocked(args)

    def test_workflow_and_contract_preserve_protected_default_branch_boundary(self):
        contract=json.loads(CONTRACT.read_text(encoding="utf-8"))
        self.assertEqual(contract["required_status_checks"], ["validate", "portfolio_guard", "review_complete"])
        self.assertIs(contract["required_conversation_resolution"], True)
        self.assertIs(contract["maintainer_attestation_required"], True)
        self.assertIs(contract["admin_merge_bypass_allowed"], False)
        self.assertIs(contract["issue_comment_receipt_protocol"]["maintainer_receipt_pin"]["invalid_explicit_pin_legacy_fallback_allowed"], False)
        self.assertIn(gate.COMMENT_EVIDENCE, contract["accepted_evidence"])
        decoration=contract["issue_comment_receipt_protocol"]["clean_decoration_policy"]
        self.assertEqual(decoration["ascii_shortcode_name_max_characters"], 32)
        self.assertEqual(decoration["maximum_shortcodes"], 1)
        self.assertIs(decoration["arbitrary_prose_allowed"], False)
        workflow=WORKFLOW.read_text(encoding="utf-8")
        self.assertIn('ref: ${{ github.event.repository.default_branch }}', workflow)
        self.assertIn('reviewThreads(first:100,after:$endCursor)', workflow)
        self.assertIn('gh api graphql --paginate --slurp', workflow)
        self.assertIn('/commits/${HEAD_SHA:0:10}', workflow)
        self.assertIn('issues/comments/$PIN_COMMENT_ID', workflow)
        self.assertIn('github.event.changes.body.from', workflow)
        self.assertIn('--attestation-event', workflow)
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
