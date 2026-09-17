# Read-only ResearchCandidatePacket Adapter — 2026-09-17

This is a pure integration adapter, not an alpha model.

It admits only source envelopes with:
- explicit `VERIFIED` status;
- `available_at` and `observed_at` no later than the decision cutoff;
- collection time not preceding observation;
- a SHA-256 matching the exact payload;
- no target/order/broker authority fields.

Each upstream source may populate only its own semantic section. A missing, stale,
partial or future source is retained as a provenance reason; the adapter never
substitutes zero or a favorable default.

The adapter is intentionally agnostic to current unmerged producer schemas. Producer-
specific translation belongs in separately tested thin adapters after each producer
contract is canonical. This prevents #445/#405/#441/KR#2 from being silently treated
as merged merely because their conceptual fields are known.

KR PR #2 remains the preferred KR boundary: KR owns KRX identity, KRW units and XKRX
cutoff; the global packet only consumes a verified export.
