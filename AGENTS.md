# Run287 Agent Instructions

These instructions apply to the entire repository. They are the minimum
operating contract for Codex, Claude, GPT, and any other coding or research
agent working here.

## Read Before Acting

Read these files before making a non-trivial change:

1. `AGENTS.md`
2. `docs/AGENT_SHARED_LESSONS_LEDGER.md`
3. `docs/RUN287_GITHUB_AGENT_OPERATING_STANDARD.md`
4. The task-specific data, workflow, or promotion contract named by the code
   being changed

If these instructions conflict with an older handoff, use the current
repository contract and the most recent accepted evidence. Do not infer current
state from a stale branch, PR description, terminal transcript, or dashboard.

## Canonical Authorities

- The existing local worktree is canonical for edits. Inspect `git status` and
  `git diff` before editing and before staging.
- The GitHub default branch, exact commit SHA, PR review threads, required
  checks, and accepted GitHub artifacts are canonical for source publication
  evidence.
- The configured durable Google Drive state is canonical for accepted paper
  account and ledger state. A local cache or GitHub artifact is not a
  replacement when the workflow contract requires Drive.
- The experiment ledger and do-not-repeat registry are canonical for research
  history. GitHub issues, Slack, Teams, email, and Notion are notification or
  coordination surfaces only.

## GitHub Tool Policy

- When available, use the connected GitHub plugin for repository, branch, PR,
  review-thread, check, run, job, artifact, issue, and merge metadata.
- Use local `git` for worktree inspection and edits. Use `gh` only when the
  connector lacks required Actions logs, GraphQL thread detail, or another
  exact capability.
- Record evidence with repository, branch, exact head SHA, workflow/run/job,
  artifact ID or hash, and accepted manifest where applicable.
- Never use remote direct-file writes to bypass the local worktree, review, or
  validation path.

## Worktree and Change Scope

- Do not create a new worktree unless the user explicitly approves it.
- Preserve all user-owned changes and untracked files. Never stage, delete,
  rewrite, or commit unrelated files.
- Stage explicit paths, not `git add .` or another broad pattern.
- Keep one causal feature or fix per branch and PR. Do not mix unrelated review
  fixes, research arms, or historical branch salvage.
- Reimplement validated capabilities on current `master`; do not merge or
  cherry-pick stale experimental stacks merely because they contain useful
  ideas.

## PR and Review Contract

Before merging:

1. Confirm the PR diff and exact head SHA.
2. Run proportionate local validation.
3. Obtain an exact-head review and address every actionable thread.
4. Confirm unresolved review threads are zero and required checks are green.
5. Submit the repository review-complete signal when required.
6. Merge only with the expected head SHA so a changed head fails closed.

Do not enable auto-merge for safety, durable-state, promotion, or trading-policy
changes. Do not merge a review that applies to an older head.

## Actions and Durable Workflow Safety

- Inspect failed jobs, steps, logs, and artifacts before changing code or
  rerunning anything.
- A normal, side-effect-free PR check may be rerun selectively.
- Never blindly rerun a failed transactional daily workflow. GitHub reruns the
  job, not merely the failed step, and may replay paper-account work.
- Resume a transactional workflow only through its explicit dispatch contract
  with the intended session, accepted-state check, idempotency evidence, and
  required durable-state authorization.
- Verify the accepted account/ledger head before dispatch and after
  publication. If persistence or the accepted publication manifest was
  skipped, the session is not durably completed.
- Do not publish targets, mutate a ledger, or save an accepted artifact after a
  failed prerequisite.

## Run287 Safety Boundary

- Keep the system `RESEARCH_ONLY`: automatic paper research and manual live
  decisions only.
- Do not run a fullrun without explicit user approval after all preflight gates
  pass for one named candidate.
- Do not enable production or live trading.
- Do not auto-promote or auto-replace the champion. Automated learning may
  produce challenger proposals only.
- Do not backfill forward-only snapshots into historical PIT evidence.
- Process missing NYSE sessions chronologically. Safe failure is not a
  completed session.
- Preserve exact-close, PIT, cost, cash/reserve, lifecycle, and promotion
  contracts. Fail closed on missing or conflicting provenance.

## Evidence and Shared Learning

- Report what was changed, what was validated, what was not run, and any
  remaining blocker.
- Add a concise entry to `docs/AGENT_SHARED_LESSONS_LEDGER.md` for every
  non-trivial failure, caveat, security finding, negative result, or reusable
  operational lesson.
- Never put credentials, secret values, or credential-bearing responses in
  source, logs, issues, PR text, artifacts, or the lesson ledger.
- Optional collaboration plugins may distribute links and alerts, but they
  must point back to canonical GitHub or durable-state evidence.
