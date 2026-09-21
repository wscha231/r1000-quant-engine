# Moat / Quality V2 — evidence-bound qualitative research layer

[PROJECT_HANDOFF]

- Date: 2026-09-21 KST
- Audited source: `wscha231/r1000-quant-engine` master `0140c81eab1ad7ec94eadaef2e03a22892419a7d`
- Governance: `RESEARCH_ONLY`
- Scope: issuer-level qualitative moat/company-quality evidence contract only
- Parallel work intentionally not modified: Phase 2A whole-equity ER PR #471, selector/portfolio/risk, Control Plane v2 contracts, broker/ledger/scheduler
- Existing model surfaces not reinterpreted: `moat_proxy_score`, `moat_quality_blueprint_score`, manual moat overrides

## Role in the project

This is an A3-style thesis evidence input, not a ranking authority. A0 may route
a reviewed company-research packet to this validator; A6 may independently audit
the evidence graph. The result cannot change target books, portfolio weights or
orders. Any future weighting is a separate experiment/promotion decision.

## Six required dimensions

1. `qualification_switching_cost`
2. `market_structure_position`
3. `ip_patent_durability`
4. `pricing_power`
5. `replacement_difficulty`
6. `next_generation_relevance`

The score is an unweighted mean only after all six dimensions pass the evidence
contract. Evidence confidence is reported separately.

## Evidence contract

Every evidence row is bound to the reviewed `asset_id` and `issuer_id` and must
include:

- immutable source identity and raw SHA-256
- source type, source affiliation and independence group
- `published_at`, `available_at`, `verified_at`, `valid_through`
- SUPPORT or CHALLENGE direction
- a concrete claim

`evaluate_packet` requires a trusted caller `cutoff`; a packet cannot use its own
future timestamps to authorize itself. The caller must also provide a trusted
raw-artifact resolver. Claimed SHA-256 values are recomputed from the resolved
bytes before the evidence is admitted.

Freshness is based on `verified_at`, not the age of the original fact. A long-lived
patent may be old, but its status must be re-verified from a current authoritative
record. `valid_through` must cover the packet `as_of`.

Positive assessments require independent SUPPORT evidence. Negative assessments
require CHALLENGE evidence. A neutral 0.5 assessment requires both. Every
dimension also records a counter-argument, reviewed reconciliation and explicit
invalidation conditions. Packet-level evidence must span at least two independent
source groups.

## Safety

Every successful result declares:

- `historical_pit_certified=false`
- `oos_validated=false`
- `selector_eligible=false`
- `portfolio_weight_effect=0`
- `target_book_write_allowed=false`
- `orders_allowed=false`
- `production_authority=false`

Current qualitative research must never be backfilled into earlier decision dates.
Historical use requires evidence availability and verification timestamps that were
actually observable at each historical cutoff.

## Review findings addressed

The revised contract closes the six material review gaps found on the first Korean
implementation:

1. caller-supplied trusted cutoff is mandatory;
2. every evidence row binds to the reviewed asset/issuer;
3. stale/expired evidence fails closed;
4. positive moat claims require non-management corroboration;
5. raw evidence hashes are verified against resolved immutable bytes;
6. assessment direction must agree with SUPPORT/CHALLENGE evidence.

## Validation

The focused offline suite has 20 deterministic regressions covering the above
review findings plus missing dimensions, genuine zero, nonfinite/range errors,
future evidence, source-affiliation spoofing, duplicate evidence IDs, mandatory
counter/reconciliation/invalidation, confidence separation and digest determinism.

The Tier-1 registry itself remains frozen. The new focused suite is invoked from
the already-registered generic smoke entrypoint instead of modifying
`tools/run_pr_validation.py`.

## Next action

After merge, create timestamped evidence packets only for the post-quantitative
shortlist rather than the full universe. Recommended funnel:

whole universe -> RS/revisions/valuation/liquidity -> 30-50 thesis candidates ->
20-30 Moat V2 packets -> Bull/Base/Bear ER/downside -> portfolio competition.

Accumulate forward packets first. Only after sufficient PIT history exists should
a preregistered purged walk-forward/OOS experiment test incremental 1/3/6/12m
alpha versus the existing model. No selector weight changes before that gate.

Stop on missing, stale, conflicting, future-dated, unresolvable or identity-mismatched evidence.
