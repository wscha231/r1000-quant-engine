#!/usr/bin/env python3
"""Smoke coverage for the fail-closed Run287 review gate v3."""
from __future__ import annotations
import json, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import check_pr_review_complete as gate

TOOL = ROOT / "tools" / "check_pr_review_complete.py"
WORKFLOW = ROOT / ".github" / "workflows" / "review_complete_gate.yml"
CONTRACT = ROOT / "data_static" / "run287_review_complete_gate_contract.json"
HEAD = "a" * 40
PRIOR = "b" * 40

def check(condition, message=None):
    if not condition:
        raise AssertionError(message or "check failed")

def user(login="chatgpt-codex-connector[bot]"):
    return {"login": login}

def review(rid, *, state="COMMENTED", commit=HEAD, when="2026-09-16T01:05:00Z",
           login="chatgpt-codex-connector[bot]", association="NONE"):
    return {"id": rid, "state": state, "commit_id": commit, "submitted_at": when,
            "user": user(login), "author_association": association}

def file(path, patch="@@ -0,0 +1 @@\n+safe = True", *, status="modified", previous=None):
    row = {"filename": path, "status": status, "patch": patch}
    if previous is not None:
        row["previous_filename"] = previous
    return row

def canonical_runs(*, validate="success", guard="success", head=HEAD, extra=None):
    rows = [
        {"id": 101, "path": ".github/workflows/pr_validation.yml", "head_sha": head,
         "event": "pull_request", "status": "completed", "conclusion": validate,
         "run_started_at": "2026-09-16T01:05:00Z"},
        {"id": 102, "path": ".github/workflows/portfolio_system_guard.yml", "head_sha": head,
         "event": "pull_request", "status": "completed", "conclusion": guard,
         "run_started_at": "2026-09-16T01:06:00Z"},
    ]
    if extra:
        rows.extend(extra)
    return {"workflow_runs": rows}

def run_case(*, files, reviews=None, reactions=None, draft=False,
             observation=None, attestation=None, include_attestation=True, author="author",
             changed_files=None, runs=None, threads=None):
    pr = {"number": 446, "draft": draft, "head": {"sha": HEAD}, "user": {"login": author},
          "changed_files": len(files) if changed_files is None else changed_files}
    att = None
    if include_attestation:
        att = attestation or {
            "head_sha": HEAD, "created_at": "2026-09-16T01:20:00Z",
            "actor": "maintainer", "permission": "write", "source": "issue_comment"}
    payload = gate.evaluate(
        pull_request=pr,
        head_observation=observation or {
            "head_sha": HEAD, "observed_at": "2026-09-16T01:00:00Z", "check_run_id": 11},
        attestation=att,
        reviews=reviews or [],
        reactions=reactions or [],
        files=files,
        runs=canonical_runs() if runs is None else runs,
        threads={"reviewThreads": []} if threads is None else threads,
    )
    return (0 if payload["passed"] else 2), payload

def expect(files, *, tier, code, **kwargs):
    rc, payload = run_case(files=files, **kwargs)
    check(rc == code, (rc, payload))
    check(payload["risk_tier"] == tier, payload)
    return payload

def cli_smoke():
    with tempfile.TemporaryDirectory() as tmp:
        r = Path(tmp)
        files = [file("docs/a.md")]
        values = {
            "pr.json": {"number":446,"draft":False,"head":{"sha":HEAD},"user":{"login":"author"},"changed_files":1},
            "observation.json":{"head_sha":HEAD,"observed_at":"2026-09-16T01:00:00Z","check_run_id":11},
            "attestation.json":{"head_sha":HEAD,"created_at":"2026-09-16T01:20:00Z","actor":"maintainer","permission":"write","source":"issue_comment"},
            "reviews.json":[],
            "reactions.json":[],
            "files.json":files,
            "runs.json":canonical_runs(),
            "threads.json":{"reviewThreads":[]},
        }
        for name,value in values.items():
            (r/name).write_text(json.dumps(value), encoding="utf-8")
        out=r/"out.json"
        proc=subprocess.run([
            sys.executable,str(TOOL),
            "--pull-request",str(r/"pr.json"),"--head-observation",str(r/"observation.json"),
            "--attestation",str(r/"attestation.json"),"--reviews",str(r/"reviews.json"),
            "--reactions",str(r/"reactions.json"),"--files",str(r/"files.json"),
            "--runs",str(r/"runs.json"),"--threads",str(r/"threads.json"),"--output",str(out)
        ],capture_output=True,text=True,timeout=10)
        check(proc.returncode==0, proc.stderr or proc.stdout)
        check(json.loads(out.read_text(encoding="utf-8"))["passed"] is True)

def main():
    p = expect([file("docs/note.md")], tier="R0", code=0)
    check(p["evidence_type"] == "MAINTAINER_ATTESTED_LOW_RISK")

    p = expect([file("data_static/macro_snapshot.csv")], tier="R1", code=0)
    check(not p["independent_review_required"])
    p = expect([file("research_only/liquidity_probe.py")], tier="R1", code=0)
    check(not p["independent_review_required"])

    for path in ("tools/research_probe.py", "tools/deploy.js", "tools/run_mutator",
                 "Dockerfile", "engine/new_logic.py"):
        p = expect([file(path)], tier="R2", code=2)
        check("independent_review_required_for_r2_r3" in p["failures"])

    p = expect([file(".github/workflows/research_ci.yml")], tier="R2", code=2)
    check("independent_review_required_for_r2_r3" in p["failures"])

    workflow_r3 = "@@\n+permissions:\n+  contents: write\n+on: {schedule: [{cron: '0 1 * * *'}]}"
    p = expect([file(".github/workflows/research_ci.yml", workflow_r3)], tier="R3", code=2)
    check("workflow_scheduler_secret_or_write_change" in p["risk_reasons"])

    for marker in (
        "+  'schedule':",
        "+secrets: inherit",
        "+TOKEN: ${{ secrets['TOKEN'] }}",
        "+permissions: write-all",
        "+on: repository_dispatch",
        "+on: pull_request_target",
        "+on: workflow_run",
    ):
        p = expect([file(".github/workflows/research_ci.yml", "@@\n" + marker)], tier="R3", code=2)
        check("workflow_scheduler_secret_or_write_change" in p["risk_reasons"])

    for patch in ("@@\n-orders_allowed = False", "@@\n+orders_allowed = False"):
        p = expect([file("research_only/probe.py", patch)], tier="R3", code=2)
        check("authority_control_changed" in p["risk_reasons"])

    p = expect([file("research_only/probe.py", status="renamed",
                     previous="tools/live_trading.py")], tier="R3", code=2)
    check(any("previous:live_durable_or_secret_path" in x for x in p["risk_reasons"]))

    p = expect([file("tools/AGENTS.md")], tier="R3", code=2)
    check("governance_or_gate_path" in p["risk_reasons"])

    p = expect([{"filename":"tools/run_mutator","status":"modified","patch":None}], tier="R3", code=2)
    check("executable_patch_unavailable" in p["risk_reasons"])

    p = expect([file("docs/only.md")], tier="R3", code=2, changed_files=2)
    check("risk_classification_incomplete" in p["failures"])
    check("changed_file_inventory_count_mismatch" in p["risk_reasons"])

    p = expect([file("docs/a.md"), file("docs/a.md")], tier="R3", code=2, changed_files=2)
    check("duplicate_changed_file_records" in p["risk_reasons"])

    p = expect([file("docs/a.md")], tier="R0", code=2, runs=canonical_runs(validate="failure"))
    check("required_check_not_green:validate" in p["failures"])

    p = expect([file("docs/a.md")], tier="R0", code=2,
               runs={"workflow_runs": canonical_runs()["workflow_runs"][:1]})
    check("missing_required_check:portfolio_guard" in p["failures"])

    spoof = canonical_runs(validate="failure", extra=[
        {"id":999,"path":".github/workflows/fake.yml","head_sha":HEAD,"event":"pull_request",
         "status":"completed","conclusion":"success","name":"validate",
         "run_started_at":"2026-09-16T01:10:00Z"}])
    p = expect([file("docs/a.md")], tier="R0", code=2, runs=spoof)
    check("required_check_not_green:validate" in p["failures"])

    unresolved={"data":{"repository":{"pullRequest":{"reviewThreads":{"nodes":[{"isResolved":False}]}}}}}
    p = expect([file("docs/a.md")], tier="R0", code=2, threads=unresolved)
    check("unresolved_review_threads" in p["failures"])

    p = expect([file("tools/check_pr_review_complete.py")], tier="R3", code=2)
    p = expect([file("tools/check_pr_review_complete.py")], tier="R3", code=0, reviews=[review(1)])
    check(p["evidence_type"] == "ATTESTED_EXACT_HEAD_CODEX_REVIEW")

    p = expect([file("tools/portfolio_target.py")], tier="R2", code=2, reviews=[review(2,commit=PRIOR)])
    check("independent_review_required_for_r2_r3" in p["failures"])

    p = expect([file("tools/portfolio_target.py")], tier="R2", code=0,
               reactions=[{"id":3,"content":"+1","created_at":"2026-09-16T01:10:00Z","user":user()}])
    check(p["evidence_type"] == "MAINTAINER_BOUND_CODEX_CLEAN_REACTION")

    p = expect([file("tools/portfolio_target.py")], tier="R2", code=2,
               reviews=[review(4), review(5,state="CHANGES_REQUESTED",login="reviewer",association="COLLABORATOR")])
    check("trusted_current_head_changes_requested" in p["failures"])

    p = expect([file("docs/a.md")], tier="R0", code=2, include_attestation=False)
    check("missing_maintainer_attestation" in p["failures"])
    p = expect([file("docs/a.md")], tier="R0", code=2,
               attestation={"head_sha":HEAD,"created_at":"2026-09-16T01:20:00Z","actor":"reader","permission":"read","source":"issue_comment"})
    check("attestor_lacks_write_permission" in p["failures"])
    p = expect([file("docs/a.md")], tier="R0", code=2,
               observation={"head_sha":PRIOR,"observed_at":"2026-09-16T01:00:00Z","check_run_id":12})
    check("head_observation_sha_mismatch" in p["failures"])
    p = expect([file("docs/a.md")], tier="R0", code=2, draft=True)
    check("pull_request_is_draft" in p["failures"])

    cli_smoke()

    workflow = WORKFLOW.read_text(encoding="utf-8")
    for required in (
        "pull_request_target:", "issue_comment:", "checks: write", "actions: read",
        "review_complete", "review_head_observed", "tools/check_pr_review_complete.py",
        "/review-complete $HEAD_SHA", "collaborators/$ACTOR/permission",
        "pulls/$PR_NUMBER/files", "--files", "--runs", "--threads",
        "actions/runs?head_sha=$HEAD_SHA&event=pull_request",
    ):
        check(required in workflow, required)
    check("pull_request_review:" not in workflow)

    contract=json.loads(CONTRACT.read_text(encoding="utf-8"))
    check(contract["schema_version"]=="run287-review-complete-gate-contract-v3")
    check(contract["risk_tiers"]["R0"]["independent_review_required"] is False)
    check(contract["risk_tiers"]["R1"]["independent_review_required"] is False)
    check(contract["risk_tiers"]["R2"]["independent_review_required"] is True)
    check(contract["risk_tiers"]["R3"]["independent_review_required"] is True)
    check(contract["maintainer_attestation_required"] is True)
    check(contract["automatic_merge_allowed"] is False)
    print("run287 review-complete gate v3 smoke: PASS")

if __name__=="__main__":
    main()
