# Run287 GitHub Agent Operating Standard

Status: mandatory repository-wide agent guidance

Repository: `wscha231/r1000-quant-engine`

Operating boundary: `RESEARCH_ONLY`, automatic paper research, manual live
decisions

## 1. Purpose

This standard turns the connected GitHub capabilities into a repeatable,
auditable operating system for Run287. It applies to repository research,
implementation, PR review, CI diagnosis, durable paper-session recovery, and
release evidence.

The goal is not to maximize automation at any cost. The goal is to make every
agent use the same canonical sources, fail-closed transitions, review
requirements, and evidence format while allowing low-risk inspection and
research to remain fast.

`AGENTS.md` is the short mandatory contract. This document explains how to
apply it. The data, paper-ledger, publication, and promotion contracts remain
authoritative for their specific domains.

## 2. Canonical Source Map

| Concern | Canonical authority | Non-canonical convenience copies |
|---|---|---|
| Source and review | GitHub default branch at exact SHA, PR threads, required checks | Local notes, chat summaries |
| In-progress edits | Existing local worktree and its explicit diff | Remote direct-file editor |
| Accepted paper state | Contract-approved durable Google Drive account and ledger | Local cache, workflow artifact |
| Workflow evidence | Exact GitHub run/job/step plus accepted manifest and artifact hashes | Screenshots, terminal summaries |
| Research history | Experiment ledger, feature registry, do-not-repeat registry | Issues, project boards, Notion |
| Operational lessons | `docs/AGENT_SHARED_LESSONS_LEDGER.md` or linked dated report | Chat history |

Agents must distinguish source publication, workflow execution, and durable
state. A green GitHub run does not by itself prove that an accepted paper
account was durably published. Conversely, a local file does not prove GitHub
or Drive acceptance.

## 3. GitHub Capability Map

Use the connected GitHub plugin first when it is available.

| Capability | Run287 use | Required evidence |
|---|---|---|
| Repository, branch, PR, and commit search | U0 branch/PR census and ancestry audit | audit commit, branch/PR IDs, head/base SHAs |
| Compare, patch, and blob reads | Recover a capability without merging a stale stack | source SHA, path, causal-family mapping |
| Review threads and replies | Find, fix, reply to, and resolve actionable feedback | exact PR head, unresolved count |
| Actions runs, jobs, steps, logs, artifacts | Diagnose the real failure boundary | run attempt, job/step, artifact ID/hash |
| Check status and review state | Enforce exact-head merge readiness | required-check result, review head SHA |
| Expected-head merge | Prevent merging a changed or unreviewed head | expected head SHA, merge SHA |
| Issues, labels, assignees | Track incidents, SLO breaches, and human blockers | canonical artifact/report links |

Use local `git` for status, diff, branching, commits, and preservation of
user-owned files. Use `gh` for connector gaps such as detailed Actions log
downloads or GraphQL review-thread fields. The fallback must not weaken the
same evidence or safety rules.

Remote direct-file commits are intentionally excluded from the normal path.
They can bypass the user-visible worktree, local validation, and unrelated-file
protection.

## 4. Mandatory Agent Workflow

### 4.1 Orient

1. Confirm the existing worktree and current branch.
2. Inspect `git status`, staged changes, and unstaged diff.
3. Read `AGENTS.md`, the shared lessons ledger, this standard, and relevant
   task contracts.
4. Query GitHub for the default-branch SHA, target PR state, reviews, checks,
   and recent runs when the task depends on current remote state.
5. State material assumptions. Do not silently substitute a stale result.

### 4.2 Implement

1. Create one current-master branch for one causal feature or fix.
2. Preserve untracked and unrelated user files.
3. Prefer focused reconstruction over merging a stale experiment branch.
4. Add a test for each new invariant and register fast contract tests in
   `tools/run_pr_validation.py`.
5. Update the shared lessons ledger when the work produces a reusable lesson.
6. Do not execute fullrun, production, or live trading as an implementation
   side effect.

### 4.3 Review and Publish

1. Inspect the final local diff and stage explicit files only.
2. Run focused tests, then the proportionate PR validation tier.
3. Commit and push the current branch.
4. Open a scoped PR and verify the remote diff.
5. Review the exact head SHA. Resolve every actionable review thread and
   rerun affected checks.
6. Require zero unresolved threads, green required checks, and the repository
   review-complete signal.
7. Merge with the expected head SHA. If the head changed, stop and re-review.
8. Record the merge SHA and any resulting workflow or artifact evidence.

Auto-merge is prohibited for changes affecting durable state, accepted
publication, safety gates, promotion, portfolio policy, or trading behavior.
Those PRs require an explicit final-state check.

## 5. CI Failure and Recovery Workflow

### 5.1 Side-effect-free PR checks

For a normal PR check:

1. Read job and step status.
2. Download only the necessary logs or artifact.
3. Identify whether the failure is code, test, environment, dependency, or
   flaky infrastructure.
4. Implement a focused fix with a regression test.
5. A selective failed-job rerun is permitted only when the job is proven
   side-effect free.

### 5.2 Transactional daily workflows

Do not use a blind failed-job rerun for a workflow that can produce targets,
orders, fills, account/ledger mutations, accepted manifests, cache heads, or
durable publications. A GitHub rerun starts the job again and can replay work
that succeeded before the failed step.

Instead:

1. Identify the scheduled session and next chronological unprocessed session.
2. Inspect the accepted durable account/ledger head and its origin evidence.
3. Determine the exact failed boundary and whether any mutation or publication
   already occurred.
4. Merge a regression-tested fix on the expected head when code is at fault.
5. Use the workflow's explicit dispatch inputs for session, mode, accepted
   anchor, and idempotency or scope attestation.
6. Monitor all prerequisite, transaction, integrity, publication, and
   persistence steps.
7. Verify accepted manifest membership, artifact hashes, Drive parity, and the
   new durable head.
8. Count the session complete only after the durable contract accepts it.

If the accepted publication manifest or durable persistence step was skipped,
the session remains incomplete even if upstream computation succeeded.

## 6. Full GitHub Census and Capability Recovery

The GitHub plugin should power the U0-v2 census without treating every branch
as mergeable code.

1. Pin one default-branch audit commit.
2. Enumerate all branches and PRs at that audit point.
3. Record head/base SHA, ancestry, merged/open/closed status, review state, and
   linked experiment identity.
4. Read changed paths, patches, and only the blobs needed to identify the
   causal capability.
5. Map each result to a canonical experiment ID and exact parameter/data hash.
6. Preserve failed and summary-only outcomes in the multiple-testing
   population and do-not-repeat registry.
7. Reconstruct only a validated capability on current master.

An issue, label, branch name, or PR title is not an experiment identity.
Historical return series, PIT/universe contract, target-book hash, costs, and
cash/reserve rules must be recoverable. Otherwise mark the record
`SUMMARY_ONLY` and block promotion use.

## 7. Incident and SLO Use

GitHub issues may be used as a human-visible incident queue. Recommended labels
are:

- `run287:blocker`
- `run287:data`
- `run287:integrity`
- `run287:slo`
- `run287:do-not-repeat`

Each incident must link to canonical evidence: exact run/job, commit SHA,
artifact or manifest, accepted head, and a dated report or ledger entry.
Closing an issue does not mutate the canonical account, experiment ledger, or
do-not-repeat state.

The following conditions merit an issue or equivalent durable incident record:

- decision packet misses the post-close SLO
- required exact-close or candidate coverage blocks mutation
- target, preview, ledger, account, or manifest hash parity fails
- duplicate, future, or same-day fill is detected
- accepted state cannot be restored or replayed
- a challenger is halted for structural error

## 8. Optional Plugin Extensions

The GitHub plugin and configured Google Drive integration cover the current
canonical workflow. Additional plugins should be added only when the user
confirms the project actually uses that system.

| Plugin | Appropriate use | Boundary |
|---|---|---|
| Slack or Teams | SLO, failed-run, review, and promotion-proposal alerts | Choose one collaboration system; alerts contain links, not canonical state |
| Atlassian Rovo | Jira incident/change tickets and Confluence runbooks | GitHub and repository contracts remain technical authority |
| Notion | Readable research index or stakeholder mirror | Never replace experiment ledger or accepted manifests |
| Gmail/Outlook | Escalation summaries to named recipients | No credentials or account/position payloads in mail |
| Calendar | Monthly rebalance and quarterly validation reminders | Scheduler is not execution authority |
| Figma | Dashboard design only | No operational or research state |
| Box/SharePoint | Organization-required distribution | Do not create a second accepted paper-state authority |

No agent may silently install an optional collaboration plugin or begin sending
external messages. Installation and external notification require a confirmed
target system and user authorization.

## 9. Improvement Roadmap

### G0 — Enforced agent standard

- Maintain root `AGENTS.md`, this operating standard, PR checklist, and a
  Tier-1 smoke test.
- Require exact-head review, expected-head merge, explicit-path staging, and
  transactional-rerun safety.

### G1 — GitHub census automation

- Export branch, PR, commit, ancestry, review, check, and changed-path metadata
  at a fixed audit SHA.
- Join it to the experiment ledger and do-not-repeat registry.
- Report missing evidence, duplicate causal families, and `SUMMARY_ONLY`
  blockers without starting a new historical challenger.

### G2 — CI evidence packets

- Produce a machine-readable incident packet containing run attempt, failed
  boundary, prior successful mutation-capable steps, artifact IDs/hashes,
  accepted-head status, and safe recovery route.
- Add side-effect classification so only proven non-transactional jobs can be
  selectively rerun.

### G3 — Review and SLO dashboards

- Summarize open Run287 PRs, unresolved threads, exact-head review status,
  required checks, delayed decision packets, catch-up queue depth, and durable
  publication parity.
- Keep dashboards read-only; they do not grant mutation or promotion authority.

### G4 — Approved notifications and drills

- After the user chooses Slack or Teams, route blocker and SLO links to that
  system with deduplication and severity thresholds.
- Run monthly restore/replay drills and quarterly GitHub census integrity
  audits. Store drill evidence in canonical repository artifacts and reports.

## 10. Completion Checklist for Every Agent

- [ ] Used the existing worktree and preserved unrelated/untracked files.
- [ ] Based the change on current master and kept one causal scope.
- [ ] Used GitHub plugin metadata where available and recorded exact SHAs.
- [ ] Added or updated regression tests and ran proportionate validation.
- [ ] Updated shared lessons or explained why no update was needed.
- [ ] Reviewed the exact PR head; unresolved actionable threads are zero.
- [ ] Required checks are green and merge uses the expected head SHA.
- [ ] Did not blindly rerun a transactional workflow.
- [ ] Did not run fullrun, enable production/live trading, or auto-promote.
- [ ] Reported accepted artifact/durable-state evidence separately from code
      merge status.
