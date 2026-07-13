# Run287 long-horizon estimate/guidance sample request - 2026-07-14

## Decision

Add 252- and 504-trading-day outcomes to the frozen PIT
estimate/guidance research contract before any provider export or return label
is inspected.

This change prepares measurement and a zero-cost schema request only. It does
not collect provider data, join historical returns, run an alpha screen, alter
the 993-row current research queue, change either portfolio, authorize a
purchase, dispatch a fullrun, or enable production/live trading.

## Frozen outcome horizons

`docs/run287_pit_estimate_guidance_outcome_contract.json` fixes five horizons:

| Sessions | Role | Use |
|---:|---|---|
| 21 | short support | early reaction direction |
| 63 | primary | main source-screen decision |
| 126 | intermediate support | half-year durability |
| 252 | long confirmation | required promotion confirmation when powered |
| 504 | long sensitivity | two-year direction report when powered; not a standalone promotion gate |

All horizons begin at the first exchange close strictly after exact
`available_from`. Returns use a split- and dividend-adjusted total-return series
and are compared with SPY plus a reproducible sector/industry benchmark when
available.

Unresolved 252D or 504D outcomes are right-censored as null with an explicit
status. They must never be filled with zero, counted as failures, or dropped
silently. A security that delists before a horizon requires a verified
delisting return or cash-merger proceeds; otherwise that outcome is unresolved
and reduces coverage.

The 252D result uses calendar-quarter blocks because long outcomes overlap. It
is required in full, OOS2, and OOS only when each window has at least 100
positive events, 100 negative events, and eight independent blocks. The 504D
result uses half-year blocks and is reported for full/OOS2 when at least 50
positive events, 50 negative events, and six independent blocks are resolved.
This prevents the 2026-07-10 endpoint from turning recent events into fabricated
two-year labels.

## Actual request generated from the local research queue

Input:

`outputs/run287_full_universe_research_routing_20260712_commit_df12943a/full_universe_research_queue.csv`

Observed current snapshot:

- 993 rows total;
- 992 equity issuers after excluding cash;
- 64 ADR/global listings in the current queue;
- `pit_universe_label_clean=false`;
- current snapshot only, not historical membership.

Generated request:

`outputs/run287_pit_estimate_guidance_sample_request_20260714/`

Result:

- status: `READY_ZERO_COST_SCHEMA_REQUEST_WITH_PROVIDER_DELISTED_QUERY`;
- 45 current active issuers selected without return labels;
- exactly five ADR/global issuers reserved in the active sample;
- 13 current sector labels represented;
- five historical-delisted provider query slots;
- all rows request EPS, revenue, consensus estimate, company guidance, and
  21/63/126/252/504-session outcome compatibility;
- input and output files carry SHA-256 hashes in `summary.json`.

The active sample uses a fixed seed, then a five-ADR minimum and
sector-round-robin SHA-256 ordering. Current holdings, historical winners, and
future returns do not affect selection.

## Delisted gap and deterministic provider query

The successful free historical-data artifact returned 14,140 active listing
rows but zero delisted rows. Therefore no local delisted security is silently
substituted.

Each of the five open slots instructs the provider to:

1. form the complete pool of securities eligible at any decision time from
   2019-06-03 through 2026-07-10 that subsequently delisted;
2. use its permanent security ID and the frozen seed;
3. order by SHA-256 of `seed|permanent_id`;
4. return the first five, including symbol chain, delisting return or cash
   proceeds, and complete PIT estimate/guidance history.

The delivered export must still pass the existing source gate. Provider choice
does not waive the stable-ID or delisted-coverage requirements.

## All-universe boundary

The generated `current_universe_reference_request.csv` contains all 992 current
equity issuers only as a provider reference. It is not the final historical
universe.

The final acquisition and source screen must add the union of every
decision-time eligible security, including historical members, delisted names,
and symbol predecessors. Its unique count remains unknown until a PIT
membership/delisted source is supplied. Current 993 membership must never be
projected backward.

## Promotion rules

- 63D remains the primary source-screen horizon.
- 21D and 126D must support the direction.
- 252D becomes a powered long-confirmation gate.
- 504D is always reported when powered but remains sensitivity-only because of
  endpoint censoring.
- Positive-minus-negative mean and median benchmark-excess returns must be
  positive in the registered windows.
- Required bootstrap lower bounds must be nonnegative.
- A weak or negative long result closes the lane; horizons and endpoint are not
  changed after viewing outcomes.

## Next action

Send only the zero-cost schema/sample request. Do not purchase full history.
When a provider returns the 50-security export, first run
`tools/audit_pit_estimate_guidance_source.py`. Historical return labeling and
the single-source screen remain blocked until it reaches
`READY_FOR_SOURCE_SCREEN`.
