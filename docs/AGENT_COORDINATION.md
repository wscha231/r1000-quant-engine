# Agent Coordination Protocol

> Purpose: keep Claude Code, ChatGPT Pro, Codex, and the user aligned through GitHub-visible Markdown.
>
> Status date: 2026-06-15 KST.

## Source Of Truth

GitHub Markdown is the shared coordination surface.

Use these files in order:

1. `SESSION_HANDOFF_20260615.md` - current active handoff and next actions.
2. `CHANGELOG.md` - chronological machine-scannable record of material changes.
3. `CLAUDE.md` - repo operating rules and bootstrap reading order.
4. `docs/AGENT_COORDINATION.md` - stable cross-agent collaboration rules.

Google Drive may store large artifacts, reports, exports, and run bundles. It is not the source of truth for decisions unless the GitHub handoff links the exact Drive artifact path or file ID and records the commit/config/data snapshot that produced it.

## Role Split

### Claude Code

Primary in-repo executor.

Owns:

- code edits that touch strategy behavior, backtest logic, ledger logic, CI, and GitHub Actions.
- smoke tests and regression tests.
- branch hygiene, commits, pushes, and PR setup when authenticated.
- broker-action wiring after design review.

Must not:

- merge to the default branch without explicit user approval.
- force-push unless explicitly requested.
- skip hooks or CI to make progress look clean.
- manually rewrite append-only ledgers.
- claim production readiness from one headline metric.

### ChatGPT Pro

Strategy and methodology reviewer.

Owns:

- design review before large or trading-adjacent work.
- statistical review: IS/OOS split, regime attribution, leakage, selection bias, and sample-size risk.
- reviewing diffs for hidden assumptions.
- writing specs, acceptance criteria, and test plans.

Must not:

- claim production code was implemented unless the patch was applied and verified in the repo.
- turn noisy experiments into production recommendations.
- judge engine quality from full-period CAGR alone.

### Codex

Parallel implementation and breadth worker.

Owns:

- mechanical refactors.
- smoke-test backfill.
- documentation and handoff updates.
- config normalization.
- artifact scanners and diagnostic utilities.
- independent review of changed files.

Must not:

- push directly to shared branches without explicit user approval.
- mutate append-only ledgers by hand.
- rewrite unrelated user or agent changes.
- silently clean up files outside scope.

### User

Final risk and activation authority.

Owns:

- live or production-adjacent approval.
- broker/live-order approval.
- final choice when strategy tradeoffs conflict.
- approval to merge protected/default branches.

## Coordination Rules

- Small local fix: Claude Code or Codex can implement directly with tests.
- Broad mechanical work: Codex implements, Claude reviews and commits.
- Strategy behavior change: ChatGPT Pro reviews design, Claude implements, Codex backfills tests/docs.
- Trading or broker action: ChatGPT Pro reviews safety model, Claude implements paper mode, user approves any live mode.

Escalate to ChatGPT Pro before coding when:

- portfolio construction, risk controls, order routing, or production activation changes.
- more than five files will change.
- expected work is longer than four focused hours.
- a result will be used to compare strategy quality.
- a metric looks too good, too bad, or unexplained.

## Required Handoff Payload

Every agent handoff must include:

- repo path
- branch name
- last commit
- files changed
- tests run
- artifacts read or generated
- unresolved assumptions
- exact next command or next file to inspect

## GitHub Workflow

Use GitHub for coordination:

- `CHANGELOG.md` records every material code/config/pipeline/docs change in the required format.
- `SESSION_HANDOFF_YYYYMMDD.md` records the active plan, priorities, blockers, and next action.
- PR descriptions should link the handoff and changelog entry.
- PR comments can carry status updates, but they do not replace the handoff.

Do not rely on chat-only state. If another agent must know it, put it in GitHub-visible Markdown.

## Google Drive Workflow

Use Google Drive for large or binary artifacts:

- full rebuild bundles
- exported reports
- large run outputs
- paper-trading logs
- zipped data snapshots

When a Drive artifact matters, record in GitHub:

- Drive path or file ID
- producing commit
- run ID
- config hash or policy name
- data snapshot/date window
- whether the artifact is evidence, exploratory output, or stale context

## Hard Rules

1. Do not trust A/B results without explicit `portfolio_policy`.
2. Do not interpret full-period CAGR as engine quality; require IS/OOS and regime/era attribution.
3. New phase columns must be registered in config and feature-store keep lists, with tests.
4. Do not manually delete, truncate, or rewrite append-only ledgers.
5. Paper mode comes before broker live mode.
6. Missing evidence blocks promotion.
7. Do not merge default/protected branches without user approval.
8. Do not skip tests, hooks, or CI to look green.
9. Do not rewrite unrelated dirty-worktree changes.

## End-Of-Session Checklist

Before ending a session, update GitHub-visible Markdown with:

- what changed
- branch and commit
- tests run
- artifacts read/generated
- current verdict
- next single action
- blockers or assumptions

If no code changed, say so explicitly.
