# Moat / Quality V2 — evidence-bound qualitative research layer

[PROJECT_HANDOFF]

- Date: 2026-09-20
- Audited source: `wscha231/r1000-quant-engine` master `3f8986dbad6d590ae97e7276e01f59766e91d8b0`
- Mode: `RESEARCH_ONLY`
- Scope: qualitative moat/company-quality evidence contract only
- Not changed: existing selector/composite weights, ER models, target books, portfolio sizing, risk ceilings, broker/order paths, schedules, champion, production state

## Why this is separate from the existing moat proxy

The repository already contains `moat_proxy_score`, `moat_quality_blueprint_score`,
and manual moat overrides. Those are existing model/proxy surfaces and must not be
silently reinterpreted as reviewed evidence of a durable competitive advantage.
This V2 layer records a different object: explicit, time-bound evidence supporting
or challenging a company thesis.

## Six required dimensions

1. `qualification_switching_cost` — qualification time, validation burden, workflow integration, customer switching cost.
2. `market_structure_position` — monopoly/oligopoly position, share durability, capacity scarcity, concentration and credible competitors.
3. `ip_patent_durability` — patents, trade secrets, process know-how, court/regulatory challenges, expiry and design-around risk.
4. `pricing_power` — ability to preserve price/margin through cycles without relying only on temporary shortages.
5. `replacement_difficulty` — time, cost, yield, reliability, certification or infrastructure burden required to replace the supplier/product.
6. `next_generation_relevance` — whether the advantage remains relevant as technology and architecture move to the next generation.

Every dimension requires a 0..1 assessment, separate 0..1 evidence confidence,
primary-source evidence with publication/availability timestamps and raw hashes (availability must be no later than the packet `as_of`),
a counter-argument, and explicit invalidation conditions. Missing dimensions do
not receive a neutral zero and do not contribute a partial average; the packet
fails closed.

## Score and authority

When all six dimensions satisfy the contract, the module emits an **unweighted
mean** called `moat_quality_score`. Equal treatment is deliberate: no empirical
weighting has been validated yet. Evidence confidence is reported separately and
is not multiplied into the score. The result always declares:

- `historical_pit_certified=false`
- `oos_validated=false`
- `selector_eligible=false`
- `portfolio_weight_effect=0`
- target/order/production authority `false`

This prevents a current qualitative opinion from being backfilled into historical
PIT data or becoming an arbitrary new alpha weight. After enough timestamped
history accumulates, a separate experiment may test the six dimensions and any
candidate aggregation using purged walk-forward/OOS validation, costs,
multiple-testing control and untouched holdout data.

## Validation

The focused smoke suite covers complete deterministic scoring, missing-dimension
fail-closed behavior, genuine zero preservation, boolean/nonfinite/range errors,
future evidence, publication/availability ordering, duplicate evidence IDs, raw
hash/source/direction validation, counter-arguments/invalidation conditions,
confidence separation, digest determinism, and contract/code parity.

## Next action

1. Use this schema for current US and Korean issuer research packets.
2. Add only source-backed evidence; do not infer monopoly from margin or recent
   share-price performance.
3. Archive evidence with real availability timestamps before any historical test.
4. Once coverage is adequate, compare the V2 dimensions against the existing
   `moat_proxy_score` and test incremental 1/3/6/12-month alpha. No selector
   weight changes before that gate.

Stop if evidence is missing, stale, conflicting, future-dated, synthetic, or
cannot be tied to the reviewed issuer/security identity.
