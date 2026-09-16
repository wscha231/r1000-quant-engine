#!/usr/bin/env python3
"""Smoke coverage for the Run287 risk-tiered review-complete merge gate v3."""
from __future__ import annotations
import json, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "check_pr_review_complete.py"
WORKFLOW = ROOT / ".github" / "workflows" / "review_complete_gate.yml"
CONTRACT = ROOT / "data_static" / "run287_review_complete_gate_contract.json"
HEAD = "a" * 40; PRIOR = "b" * 40

def check(condition, message=None):
    if not condition:
        raise AssertionError(message or "check failed")

def user(login="chatgpt-codex-connector[bot]"): return {"login": login}

def review(rid, *, state="COMMENTED", commit=HEAD, when="2026-09-16T01:05:00Z",
           login="chatgpt-codex-connector[bot]", association="NONE"):
    return {"id": rid, "state": state, "commit_id": commit, "submitted_at": when,
            "user": user(login), "author_association": association}

def file(path, patch="@@ -0,0 +1 @@\n+safe = True"):
    return {"filename": path, "status": "modified", "patch": patch}

def run_case(root: Path, *, files, reviews=None, reactions=None, checks=None, threads=None, draft=False,
             observation=None, attestation=None, include_attestation=True, author="author"):
    inputs = {
        "pr.json": {"number": 441, "draft": draft, "head": {"sha": HEAD}, "user": {"login": author}},
        "observation.json": observation or {"head_sha": HEAD, "observed_at": "2026-09-16T01:00:00Z", "check_run_id": 11},
        "reviews.json": reviews or [], "reactions.json": reactions or [], "files.json": files,
        "checks.json": checks if checks is not None else {"check_runs":[
            {"id":101,"name":"validate","head_sha":HEAD,"status":"completed","conclusion":"success","completed_at":"2026-09-16T01:12:00Z"},
            {"id":102,"name":"portfolio_guard","head_sha":HEAD,"status":"completed","conclusion":"success","completed_at":"2026-09-16T01:13:00Z"}
        ]},
        "threads.json": threads if threads is not None else {"data":{"repository":{"pullRequest":{"reviewThreads":{"nodes":[]}}}}},
    }
    if include_attestation:
        inputs["attestation.json"] = attestation or {"head_sha": HEAD, "created_at": "2026-09-16T01:20:00Z",
            "actor": "maintainer", "permission": "write", "source": "issue_comment"}
    for name,payload in inputs.items(): (root/name).write_text(json.dumps(payload),encoding="utf-8")
    output=root/"result.json"
    cmd=[sys.executable,str(TOOL),"--pull-request",str(root/"pr.json"),"--head-observation",str(root/"observation.json"),
         "--reviews",str(root/"reviews.json"),"--reactions",str(root/"reactions.json"),"--files",str(root/"files.json"),
         "--checks",str(root/"checks.json"),"--threads",str(root/"threads.json"),"--output",str(output)]
    if include_attestation: cmd += ["--attestation",str(root/"attestation.json")]
    proc=subprocess.run(cmd,capture_output=True,text=True)
    return proc.returncode,json.loads(output.read_text(encoding="utf-8"))

def main():
  with tempfile.TemporaryDirectory() as tmp:
    r=Path(tmp)
    code,p=run_case(r,files=[file("docs/note.md")]); check(code==0 and p["risk_tier"]=="R0" and p["evidence_type"]=="MAINTAINER_ATTESTED_LOW_RISK")
    code,p=run_case(r,files=[file("tools/liquidity_probe.py")]); check(code==0 and p["risk_tier"]=="R1" and not p["independent_review_required"])
    code,p=run_case(r,files=[file(".github/workflows/research_ci.yml","@@\n+jobs:\n+  test:\n+    runs-on: ubuntu-latest")]); check(code==0 and p["risk_tier"]=="R1")
    code,p=run_case(r,files=[file(".github/workflows/manual_refresh.yml","@@\n+jobs:\n+  refresh:\n+    runs-on: ubuntu-latest")]); check(code==2 and p["risk_tier"]=="R2")
    code,p=run_case(r,files=[file(".github/workflows/research_ci.yml","@@\n+on:\n+  schedule:\n+    - cron: '0 1 * * *'")]); check(code==2 and p["risk_tier"]=="R3" and "independent_review_required_for_r2_r3" in p["failures"])
    code,p=run_case(r,files=[{"filename":".github/workflows/opaque.yml","patch":None}]); check(code==2 and p["risk_tier"]=="R3")
    code,p=run_case(r,files=[file("engine/new_logic.py")]); check(code==2 and p["risk_tier"]=="R2")
    code,p=run_case(r,files=[file("tools/unclassified_helper.py")]); check(code==2 and p["risk_tier"]=="R2")
    code,p=run_case(r,files=[file("tools/trading.py")]); check(code==2 and p["risk_tier"]=="R3")
    rates_banks=[
      file("tools/liquidity_rates_banks.py"), file("tests/liquidity_rates_banks_smoke.py"),
      file("docs/LIQUIDITY_RATES_BANKS_MERGE_20260916.md"),
      file(".github/workflows/liquidity_rates_banks_ci.yml","@@\n+jobs:\n+  contracts:\n+    runs-on: ubuntu-latest")
    ]
    code,p=run_case(r,files=rates_banks); check(code==0 and p["risk_tier"]=="R1")
    code,p=run_case(r,files=[file("tools/portfolio_target.py")]); check(code==2 and p["risk_tier"]=="R2")
    code,p=run_case(r,files=[file("tools/portfolio_target.py")],reviews=[review(1)]); check(code==0 and p["evidence_type"]=="ATTESTED_EXACT_HEAD_CODEX_REVIEW")
    code,p=run_case(r,files=[file("tools/portfolio_target.py")],reviews=[review(2,commit=PRIOR)]); check(code==2 and "independent_review_required_for_r2_r3" in p["failures"])
    code,p=run_case(r,files=[file("tools/check_pr_review_complete.py")]); check(code==2 and p["risk_tier"]=="R3")
    code,p=run_case(r,files=[file("tools/check_pr_review_complete.py")],reviews=[review(5)]); check(code==0 and p["risk_tier"]=="R3")
    code,p=run_case(r,files=[file("tools/portfolio_target.py")],reactions=[{"id":6,"content":"+1","created_at":"2026-09-16T01:10:00Z","user":user()}]); check(code==0 and p["evidence_type"]=="MAINTAINER_BOUND_CODEX_CLEAN_REACTION")
    code,p=run_case(r,files=[file("tools/portfolio_target.py")],reactions=[{"id":7,"content":"+1","created_at":"2026-09-16T00:59:00Z","user":user()}]); check(code==2)
    code,p=run_case(r,files=[file("tools/portfolio_target.py")],reviews=[review(8),review(9,state="CHANGES_REQUESTED",login="reviewer",association="COLLABORATOR")]); check(code==2 and "trusted_current_head_changes_requested" in p["failures"])
    bad_checks={"check_runs":[
      {"id":201,"name":"validate","head_sha":HEAD,"status":"completed","conclusion":"failure","completed_at":"2026-09-16T01:12:00Z"},
      {"id":202,"name":"portfolio_guard","head_sha":HEAD,"status":"completed","conclusion":"success","completed_at":"2026-09-16T01:13:00Z"}
    ]}
    code,p=run_case(r,files=[file("docs/a.md")],checks=bad_checks); check(code==2 and "required_check_not_green:validate" in p["failures"])
    code,p=run_case(r,files=[file("docs/a.md")],checks={"check_runs":[]}); check(code==2 and "missing_required_check:validate" in p["failures"])
    unresolved={"data":{"repository":{"pullRequest":{"reviewThreads":{"nodes":[{"isResolved":False},{"isResolved":True}]}}}}}
    code,p=run_case(r,files=[file("docs/a.md")],threads=unresolved); check(code==2 and "unresolved_review_threads" in p["failures"] and p["unresolved_review_thread_count"]==1)
    code,p=run_case(r,files=[file("docs/a.md")],include_attestation=False); check(code==2 and "missing_maintainer_attestation" in p["failures"])
    code,p=run_case(r,files=[file("docs/a.md")],attestation={"head_sha":HEAD,"created_at":"2026-09-16T01:20:00Z","actor":"reader","permission":"read","source":"issue_comment"}); check(code==2 and "attestor_lacks_write_permission" in p["failures"])
    code,p=run_case(r,files=[file("docs/a.md")],observation={"head_sha":PRIOR,"observed_at":"2026-09-16T01:00:00Z","check_run_id":12}); check(code==2 and "head_observation_sha_mismatch" in p["failures"])
    code,p=run_case(r,files=[file("docs/a.md")],draft=True); check(code==2 and "pull_request_is_draft" in p["failures"])
    code,p=run_case(r,files=[]); check(code==2 and p["risk_tier"]=="R3" and "risk_classification_incomplete" in p["failures"])
    code,p=run_case(r,files=[file("tools/research_probe.py","@@\n+orders_allowed = True")]); check(code==2 and p["risk_tier"]=="R3")

  workflow=WORKFLOW.read_text(encoding="utf-8")
  for required in ("pull_request_target:","issue_comment:","checks: write","review_complete","review_head_observed",
      "tools/check_pr_review_complete.py","/review-complete $HEAD_SHA","collaborators/$ACTOR/permission","pulls/$PR_NUMBER/files","--files","risk_tier",
      "check-runs?per_page=100","reviewThreads(first:100","--checks","--threads"):
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

if __name__=="__main__": main()
