# [PROJECT_HANDOFF] H1 security-basis registry — 2026-09-21

Issue: #476
Base: 0140c81eab1ad7ec94eadaef2e03a22892419a7d
Scope: COMMON/ADR identity and corporate-action/share-basis evidence only.

## Problem

Phase2A #471 correctly requires an identity registry with a verified
corporate-action-adjusted total-return basis for every admitted security and,
for ADRs, a verified ADR-to-underlying share ratio and underlying currency.

Current master has lifecycle handling for ticker changes/delistings and separate
price caches, but no canonical per-security registry that proves those basis
facts at decision time. Provider names, current prices and ticker labels are not
evidence.

## Contract

tools/build_security_basis_registry.py consumes:

1. a stable security identity source; and
2. reviewed basis evidence keyed by security_id.

Every corporate-action or ADR evidence item must have an exact available_at,
approved review state, HTTPS source URL and source SHA-256. Evidence available
after the decision time is not admitted. Unknown evidence IDs and non-unique
ticker identities fail the build.

Missing basis evidence does not delete the security. The row stays present with
basis_status=BLOCKED_SECURITY_BASIS and explicit blockers. The overall registry
is READY only when every requested security is ready.

The emitted securities array intentionally matches the identity-registry shape
consumed by #471. The CLI also binds exact input-file byte hashes. It has no
selector, target, ledger or order authority.

## Real evidence examples

APH is a split counterexample, but #474 handles research price-bar split
adjustment separately. TSMC official financial statements state that one TSM
ADR represents five ordinary shares. Those facts are examples for reviewed
evidence; neither ticker is hard-coded in the implementation.

## Validation

A local no-network synthetic probe passed:
- fully reviewed COMMON + ADR;
- ADR ratio=5 and TWD causal availability;
- missing ADR evidence preserved but blocked;
- future corporate-action evidence blocked;
- RAW basis rejected;
- duplicate ticker identity and orphan evidence fail closed.

The registered Tier-1 security_lifecycle_smoke.py is extended with equivalent
contract tests. Exact-head CI/review remain required before merge.

No fullrun, target, account/ledger, broker/order, selector-weight or production
change is part of this H1 slice.
