## Summary

-

## Validation

- [ ] Local validation command(s) run:
- [ ] GitHub Actions checks reviewed:

## GitHub Agent Operating Standard

- [ ] I read and followed `AGENTS.md` and
      `docs/RUN287_GITHUB_AGENT_OPERATING_STANDARD.md`.
- [ ] This PR has one causal scope and does not stage unrelated or user-owned
      files.
- [ ] The exact head SHA was reviewed, actionable threads are resolved, and
      required checks are green.
- [ ] Any workflow/run/artifact claim records the exact run, SHA, and accepted
      manifest or durable-state evidence.
- [ ] I did not blindly rerun a transactional workflow or enable auto-merge for
      a safety, durable-state, promotion, or trading-policy change.

## Shared Lessons / Mistake Notebook

- [ ] I checked whether this PR creates or resolves a failed test, failed
      workflow, data blocker, measurement caveat, security issue, or negative
      alpha result.
- [ ] I updated `docs/AGENT_SHARED_LESSONS_LEDGER.md` or linked the dated
      directive/report that records the lesson.
- [ ] If no ledger update is needed, reason:

## Research / Production Boundary

- [ ] No fullrun was dispatched unless the PR explicitly documents user
      approval.
- [ ] No production promotion, live trading, or public-return claim is implied.
- [ ] Any forward-only API snapshot is labeled forward-only and not used as
      historical PIT backtest evidence.

## Credential Safety

- [ ] No API key, token, secret, `.env` value, or vendor response that echoes a
      key is committed.
- [ ] If a credential could have appeared in a log/artifact, the affected
      artifact/run was deleted or documented for rotation.
