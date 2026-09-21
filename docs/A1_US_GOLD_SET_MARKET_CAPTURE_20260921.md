# [PROJECT_HANDOFF] U.S. Gold Set A3 market capture v1 — 2026-09-21

Upstream issue: #484
Authority: A1 Data/PIT research evidence only.

## Purpose

Supply the 12 U.S. equity candidates in the cross-market Gold Set with an
`a3-market-valuation-snapshot-v1` market/RS artifact without using Work/Codex or
a fullrun.

## Admission

- latest completed NYSE session from the existing strict calendar;
- 281-session request window, exact 241-session computation grid;
- Alpaca Market Data v2, IEX daily bars;
- exact HTTP bytes archived and SHA-256 hashed;
- both `adjustment=raw` and `adjustment=split` captured;
- asset + SPY raw/split close grids must agree on all required 241 sessions;
- any mismatch, missing session, stale endpoint, HTTP/schema failure or missing
  credentials => whole capture BLOCKED;
- 20/60/120/240D RS is recomputed as
  `log(1+asset_return)-log(1+SPY_return)`.

When admitted the snapshot is `REVIEWED_OBSERVED` for this bounded source/time/
basis contract, but remains:
- `return_basis=PROVIDER_ADJUSTED_CLOSE_PROXY`;
- `historical_pit_certified=false`;
- `validated_er_eligible=false`;
- selector/portfolio/target/order authority = zero.

Thus a clean capture can feed A3 market/RS research, not validated ER or production
weights. A future split or other raw/split discrepancy deliberately blocks the
candidate until a separate corporate-action review resolves it.

## Evidence

Each candidate points to an immutable evidence bundle. That bundle contains the
hashes and request metadata of the provider-raw HTTP pages for both raw and split
queries plus the pinned Gold Set registry hash. Secrets are never written.

## Stop conditions

Missing credentials; incomplete 241-session grid; nonpositive/nonfinite prices;
SPY mismatch; raw/split mismatch; duplicate session; provider HTTP/schema failure;
or incomplete 12-name cohort => fail closed.
