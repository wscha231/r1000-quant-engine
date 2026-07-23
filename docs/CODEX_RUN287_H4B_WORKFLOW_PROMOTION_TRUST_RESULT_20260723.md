# Run287 H4b workflow/promotion trust result

Date: 2026-07-23

Scope: Issue #315 H4b only

## Result

The daily operating workflow now evaluates promotion only after the accepted
paper transaction has been verified, forward outcomes have been resolved, and
the runtime scorecard has been rebuilt from that exact paper snapshot.

- The enforced order is paper transaction, paper snapshot integrity, outcome
  resolution, runtime scorecard, promotion gate, post-gate reports, and only
  then artifact publication.
- Accepted artifact and Drive publication require both the transactional paper
  step and the post-gate operating review to succeed.
- The promotion gate resets tracked scorecard trust and resolved outcome counts
  before applying runtime evidence.
- A missing paper snapshot also clears tracked session, decision-week, and all
  horizon counts before returning a blocked runtime result.
- Runtime scorecard trust is accepted only when its integrity-manifest SHA and
  paper-snapshot hash bind to the exact verified paper directory being gated.
- Completed 21D, 63D, and 126D counts and distinct decision weeks are overlaid
  from the runtime outcome archive only when that archive reports
  `READY_RISK_OUTCOME_ARCHIVE_REVIEW_ONLY`.
- A missing, stale, forged, or not-ready scorecard/outcome artifact remains
  fail-closed and cannot advance promotion state.
- Automatic champion replacement or promotion-state advancement remains
  disabled; the workflow produces evidence for manual review only.

## Fixtures

The focused fixtures prove:

1. the top-level workflow order cannot move promotion ahead of transaction,
   integrity, outcome, or scorecard construction;
2. a runtime scorecard bound to the exact paper snapshot can overlay trust;
3. a forged paper-snapshot hash is rejected;
4. runtime completed counts are mapped independently for 21D, 63D, and 126D;
5. accepted publication remains blocked unless both transactional and
   post-gate review steps succeed.

## Validation

- Workflow artifact smoke: PASS.
- Paper-ledger transaction smoke: PASS.
- Promotion gate smoke: `11/11` PASS.
- Repository pytest: `129/129` PASS.
- Full PR validation: `191/191` PASS in `694.76s` on the final local head.
- YAML parse and `git diff --check`: PASS.

## Safety and next gate

H4b is ready to publish only after H4a is merged and exact-merge validation has
passed. Durable session catch-up remains the next separate P0 operation after
H4b merge.

- Fullrun executed: false.
- Durable catch-up executed: false.
- Production activation allowed: false.
- Live trading enabled: false.
