# Run287 Chameleon forward/PIT archive result — 2026-08-30

## Outcome

The next Chameleon data layer is implemented as an isolated, report-only,
append-only observation archive. It records exact source capture times, raw
response hashes, normalized-row hashes, code and contract identity, immutable
snapshot identity, and a chained archive index.

Official network captures are labelled FORWARD_PIT and can be used only from
their exact capture time. Fixture or supplied-file captures are always
FREE_PROXY. This collector never emits PIT_VERIFIED and does not authorize
historical A/B.

## Sources

- FRED/ALFRED uses the official series/observations API with explicit
  realtime_start and realtime_end. The API key is accepted only through the
  FRED_API_KEY environment variable and is never written to persisted request
  metadata, manifests, errors, or archive rows.
- VIX, VIX3M, and VVIX use the official Cboe history sources.
- Current equity and index put/call ratios are extracted separately from the
  official Cboe Daily Market Statistics response and cross-checked against
  their corresponding call, put, and total volume.
- Cross-asset daily closes have a strict source-bundle schema but remain
  FREE_PROXY until a trusted network provider is registered.

Official references:

- https://fred.stlouisfed.org/docs/api/fred/series_observations.html
- https://fred.stlouisfed.org/docs/api/fred/series_vintagedates.html
- https://www.cboe.com/tradable_products/vix/vix_historical_data
- https://www.cboe.com/markets/us/options/market-statistics/daily
- https://www.cboe.com/us/options/market_statistics/historical_data/

## Important source correction

The initially inspected Cboe equity/index put-call archive endpoints ended in
2012 and therefore could not represent current options sentiment. The
collector does not use those legacy endpoints for the current signal. It uses
the Cboe Daily Market Statistics page, whose captured 2026-08-30 response
identified the completed 2026-08-28 session and exposed equity and index
ratios separately.

## Archive invariants

- Same collection time plus identical payload is idempotent.
- Same collection time plus changed payload is blocked.
- Older collection times are blocked.
- Every raw and normalized object is content addressed by SHA-256.
- Existing snapshot, index-chain, or content-object tampering blocks the next
  collection before a new snapshot is created.
- A present but invalid source blocks the complete snapshot. A missing source
  is recorded as missing and is never carried or imputed.
- FRED response-level and row-level vintage dates must match the requested
  vintage date.
- Equity and index put-call components cannot substitute for one another.
- available_from equals the exact source capture timestamp. No observation
  may have a future source date.
- Fixture time injection is allowed only in explicit fixture mode. Normal
  network collection uses the runtime clock.

## Local official-network proof

At 2026-08-30T02:33:08Z, a local report-only network proof archived four
official Cboe sources and 18,618 normalized rows:

- cboe.daily_put_call: two rows for 2026-08-28.
- cboe.vix: 9,261 rows, latest 2026-08-28.
- cboe.vix3m: 4,262 rows, latest 2026-08-28.
- cboe.vvix: 5,093 rows, latest 2026-08-28.

Snapshot ID:
20260830T023308Z-b167c4de9014dcd9

Snapshot manifest SHA-256:
ab040f4599772eed9afd1170430b093145cae1c1bd21aaf9209bc378448b99c6

This proof is local and is not a canonical durable publication. Thirteen
FRED/ALFRED series remained missing because no FRED_API_KEY was present.
Cross-asset closes remained missing because no trusted network provider is
registered. Missing inputs were not synthesized.

## Validation

The dedicated smoke covers:

- complete fixture capture and safety envelope;
- fixture FREE_PROXY versus network FORWARD_PIT;
- secret exclusion;
- idempotent retry and same-time conflict;
- out-of-order capture rejection;
- FRED vintage and duplicate-date rejection;
- Cboe equity/index separation;
- missing cross-asset neutrality;
- existing-object tamper detection; and
- pre-launch and caller-injected network time rejection.

The dedicated smoke and Python compilation passed. The official Cboe network
proof also passed after the stale legacy options endpoint was removed.

## Remaining boundary and next causal change

This change does not feed the macro engine automatically. The next isolated
change should materialize only hash-verified archive observations into the
existing report-only macro normalizer, while preserving available_from and
missing-source semantics. Durable scheduling requires a separately approved
publication destination and repository secret configuration; no workflow was
dispatched here.

Historical backtest, market-state portfolio routing, fear/greed allocation,
holding exits, target/order generation, accepted-head mutation, production,
live trading, and automatic promotion all remain blocked.
