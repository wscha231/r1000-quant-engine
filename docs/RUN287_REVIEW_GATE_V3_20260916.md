# Run287 review-complete gate v3 — 2026-09-16

Status: governance/safety change. This change itself is classified `R3` and must receive independent exact-head review under the existing v2 gate before merge.

## Purpose

The previous gate required Codex evidence for every PR. That made documentation, research-only tools, and data/PIT work depend on Codex review quota even when the PR could not mutate portfolio targets, accepted state, orders, or live behavior.

v3 keeps exact-head maintainer attestation for every tier but reserves independent review for higher-risk changes.

- `R0`: documentation/general-test-only or equivalent non-mutating changes. Maintainer exact-head attestation is sufficient.
- `R1`: research/data/PIT/tooling and side-effect-free workflows. Maintainer exact-head attestation is sufficient unless classification escalates.
- `R2`: portfolio/target/sizing/allocation/selector/regime/risk/execution policy. Independent exact-head review plus maintainer attestation is required.
- `R3`: governance/safety gates, broker/live/order/ledger/accepted-state/secrets, scheduler activation, or mutation-authority changes. Independent exact-head review plus maintainer attestation is required. Operational activation still needs separate explicit user approval.

The PR body cannot lower its own risk tier. Classification uses the actual changed filenames and patches. Missing file evidence, an unavailable workflow patch, or an unknown executable path fails closed to `R2` or `R3`.

## Independent review evidence

For `R2/R3`, the gate accepts one of:

1. exact-head Codex review (`COMMENTED` or `APPROVED`),
2. exact-head GitHub `APPROVED` review from a non-author `OWNER`, `MEMBER`, or `COLLABORATOR`,
3. a fresh Codex `+1` reaction bound by the maintainer attestation.

A trusted current-head `CHANGES_REQUESTED` review blocks completion.

## Invariants retained

- trusted default-branch head observation,
- exact 40-character head binding,
- maintainer write/maintain/admin attestation,
- required `validate`, `portfolio_guard`, and `review_complete` checks,
- unresolved-conversation requirement,
- no automatic merge authorization,
- no fullrun, production activation, live trading, or accepted-state mutation authority from this gate.

## Validation

The dedicated v3 smoke suite covers R0/R1 low-risk completion, R2/R3 review requirements, Codex and trusted-human evidence, stale-head rejection, maintainer attestation, schedule/mutation escalation, missing-patch fail-closed behavior, current-head change requests, and empty-change-set failure.
