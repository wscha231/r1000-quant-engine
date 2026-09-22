# Candidate Lifecycle V1 — A2 → A3 → ER → A5 connection

[PROJECT_HANDOFF]

- Date: 2026-09-23 KST
- Mode: `RESEARCH_ONLY`
- Scope: connection contract only; no new scheduler, target write, paper-ledger write, broker order, model promotion or fullrun authority.
- Parent issues: #516, #504, #479.

## Why this exists

A2 discovery is already useful, but a chat handoff is not canonical research state. Existing Methodology V1, Moat V2 and A3 Candidate Packet V1 are reviewed research components, while A5 must consume their reviewed outputs rather than re-search headlines.

Candidate Lifecycle V1 adds the missing deterministic glue:

`A2 handoff -> Event Registry -> delta refresh plan -> A3 reviewed result -> Candidate Registry -> separately validated ER -> A5 research input`

## Event admission

A0 must canonicalize A2 output into `a2-event-handoff-v1`.

- V0: discovery only, score contribution 0, no A3 refresh.
- V1/V2 + WATCH: TRACK only.
- V1/V2 + MATERIAL/CRITICAL: A3 refresh candidate.
- V1/V2 requires an immutable source-graph reference before canonical admission.
- same subject + event family inside 24 hours updates one cohort rather than creating another.
- active watch is 90 days; outcome tracking is 365 days.
- fail closed above 30 active tickers or 10 active themes; expired watches do not consume the active cap.

Theme-only events are allowed. They do not become ticker candidates until a direct investable asset relationship is separately established.

## Delta refresh

Fingerprint identities:

- `source_graph_hash`
- `fundamental_hash`
- `methodology_hash`
- `market_price_hash`
- `earnings_consensus_hash`
- `regime_hash`

Refresh behavior:

- unchanged -> `SKIP_UNCHANGED`
- price only -> market/valuation + ER
- earnings/guidance/consensus -> earnings + valuation + ER
- MATERIAL/CRITICAL event -> affected Methodology/Moat dimensions + valuation/ER
- regime only -> downside/regime + portfolio overlay
- issuer/security identity, source/accounting/data-trust break -> full A3 review

A price move never forces a full moat review by itself.

## Candidate Registry

There is one current record per investable asset/security. Superseded reviewed A3 artifacts remain immutable upstream evidence, while the registry points only to the current artifact identities.

The registry contains no BUY/SELL/rank/target/weight fields.

A candidate is not A5-input-ready unless:

- freshness is `CURRENT`;
- data gate is `PASS`;
- PIT gate is `PASS`;
- a separately reviewed `WALK_FORWARD_VALIDATED`, net-of-costs ER artifact exists;
- thesis is not invalid.

Missing ER stays missing. It is never converted to neutral or zero expected return.

## A5 read-only consumer

`build_a5_candidate_view()` resolves the immutable A3 result and validated ER bytes by exact SHA-256. It rejects:

- stale/refresh-due candidates;
- blocked data/PIT gates;
- missing validated ER;
- A3 packets that have not linked the same ER hash;
- ER without signal/thesis confidence;
- invalid thesis.

A ready view exposes reviewed ER/alpha, signal confidence, thesis confidence and downside for later portfolio competition. It does not recreate Methodology/Moat or write portfolio/target/order state.

## A0 CLI

`tools/run_candidate_lifecycle_v1.py` provides four network-free commands:

- `admit-event`
- `plan-refresh`
- `upsert-candidate`
- `build-a5-view`

This is intentionally not a scheduler. Existing orchestration should invoke it from a verified producer receipt/event, preserving the repository rule of one scheduler per causal producer.

## Current A2 examples

Recent BABA, Texas AI-power, Brent/WTI Hormuz-bypass and similar handoffs are discovery inputs only until A0 rebuilds their reviewed source graph with immutable bytes/hash. This implementation does not backfill chat prose as canonical evidence.

## Safety

- A3 remains `selector_eligible=false` and `portfolio_weight_effect=0`.
- A5 view is a research proposal input only.
- no target book, accepted paper ledger, broker book or order mutation occurs.
- no validated ER is invented from Bull/Base/Bear scenario research.
