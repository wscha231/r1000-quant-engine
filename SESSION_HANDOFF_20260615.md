# SESSION_HANDOFF_20260615

> Active cross-agent handoff for r1000 Quant Engine.
>
> Status date: 2026-06-15 KST.
>
> Purpose: Claude Code, ChatGPT Pro, Codex, and the user can continue from the same GitHub-visible plan instead of relying on chat-only memory.

## Canonical Reading Order

1. `SESSION_HANDOFF_20260615.md`
2. `docs/AGENT_COORDINATION.md`
3. `CLAUDE.md`
4. `CHANGELOG.md` latest dated section
5. current branch, status, and recent commits

Commands:

```powershell
git status --short
git branch --show-current
git log --oneline -8 --decorate
```

## Active Inbox

The current operating goal is to keep all agents aligned through GitHub Markdown while work proceeds on AlphaOps/rebuild/ledger/promotion tasks.

Immediate shared rule:

- GitHub Markdown is the coordination source of truth.
- Google Drive is for large artifacts and exported reports.
- Chat-only claims are not enough for the next agent to act.

## Role Split

Claude Code:

- primary in-repo executor.
- owns code edits, tests, commits, pushes, CI dispatch, and paper-mode broker wiring.
- must not merge default/protected branches, force-push, skip checks, or manually rewrite ledgers without explicit approval.

ChatGPT Pro:

- strategy, statistics, and design reviewer.
- owns methodology audit, design reviews, acceptance criteria, and risk framing.
- must not claim implementation unless code was applied and verified.

Codex:

- parallel implementation and breadth worker.
- owns mechanical refactors, smoke-test backfill, docs, config cleanup, diagnostics, and independent diff review.
- must not mutate append-only ledgers or rewrite unrelated worktree changes.

User:

- final authority for production, live trading, broker actions, protected branch merges, and risk tradeoffs.

## Priority Plan

### P0.1 - Verify Latest A/B Or Rebuild Verdict

Owner: Claude Code.

Reviewer: ChatGPT Pro if result is ambiguous.

Codex support: artifact parsing and summary scripts.

Acceptance:

- verdict is reproduced from artifacts, not chat text.
- run records include commit, policy, config/data snapshot, and run ID.
- result separates IS/OOS and regime/era attribution.
- missing `portfolio_policy` means the verdict is not trustworthy.

### P0.2 - Close Signal-To-Action Gap In Paper Mode

Owner: Claude Code.

Reviewer: ChatGPT Pro.

Codex support: tests, fixtures, docs, config cleanup.

Acceptance:

- crisis/regime signal creates structured paper-mode action candidates.
- risk gate, kill switch, and audit trail are mandatory.
- no live broker orders without explicit user approval.

### P0.3 - Per-Regime Or Era-Aware Model Evaluation

Owner: Claude Code.

Reviewer: ChatGPT Pro.

Codex support: diagnostic tables, registry cleanup, smoke tests.

Acceptance:

- global and regime-aware candidates use identical universe, costs, policy, and dates.
- comparison includes per-regime attribution.
- model selection logic is explicit and test-covered.

### P1.1 - Ledger To Auto-Action Router

Owner: Claude Code.

Codex support: parser, validation CLI, tests.

Acceptance:

- append-only ledgers remain immutable.
- router never acts on incomplete rows.
- outputs distinguish recommend, queue, paper execute, and block.

### P1.2 - Production Activation Gate

Owner: Claude Code.

Reviewer: ChatGPT Pro.

Acceptance:

- default state is block.
- gate returns structured reasons for allow/block.
- missing evidence never allows promotion.

### P1.3 - Data Readiness Lockdown

Owner: Codex or Claude Code.

Acceptance:

- data freshness checks fail closed.
- missing critical columns fail loudly.
- phase columns survive config and feature-store keep lists.

## Hard Rules

1. No A/B trust without explicit `portfolio_policy`.
2. No full-period CAGR as engine-quality proof.
3. New phase columns must be registered in config and keep-list tests.
4. No manual ledger rewrite.
5. Paper mode before live broker mode.
6. Missing evidence blocks promotion.
7. No default/protected branch merge without user approval.
8. No hook, test, or CI bypass.
9. Do not revert unrelated dirty-worktree changes.

## Open Questions

1. What exact artifact set defines the latest trustworthy A/B verdict?
2. Which paper-mode action is first allowed: alert, hedge, cash raise, rebalance, or no-op only?
3. What regime/era taxonomy should be used for sub-model evaluation?
4. What evidence is sufficient for `production_activation_allowed=True`?
5. Should ledger automation recommend only, queue paper actions, or execute paper actions automatically?

## Next Agent Prompt

```text
Continue r1000 Quant Engine from SESSION_HANDOFF_20260615.md.

Read:
- SESSION_HANDOFF_20260615.md
- docs/AGENT_COORDINATION.md
- CLAUDE.md
- latest CHANGELOG.md entries

Then verify git branch/status/log and inspect the latest artifacts before acting.

Use the role split:
- Claude Code = executor
- ChatGPT Pro = strategy/methodology reviewer
- Codex = breadth implementation/tests/docs
- User = production/live/merge approval

Do not rely on chat-only claims. Record material updates in GitHub-visible Markdown.
```

## Completion Rule

Before ending a session, update either this handoff or `CHANGELOG.md` with:

- what changed
- branch and commit
- tests run
- artifacts read/generated
- current verdict
- next action
- blockers or assumptions
