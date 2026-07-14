# Run287 estimate queue cost-control result (2026-07-15)

## Outcome

The 993-name forward archive queue is valid, but scheduled run `29304288757`
reached only 36 of its 150 selected names because 102 raw vendor errors hit the
collector's `max_errors=100` guard. This was an operational coverage bottleneck,
not evidence for a new portfolio arm.

The collector now separates three cases:

1. repeated global authorization failures (`401/403`),
2. symbol-level or plan-level coverage misses (`402`), and
3. other collection errors that should still consume the safety budget.

A run-scoped circuit opens only after the same `401/403 + endpoint` signature
appears for three distinct tickers and that vendor has produced no accessible
response. It never writes a persistent vendor block. Once opened, only that
vendor's estimate endpoints are skipped; other vendors and Finnhub's separate
earnings/recommendation endpoints continue normally.

## Why 402 is not a global circuit signal

The downloaded scheduled artifact showed the following exact facts:

- queue status: `ready_for_forward_archive_incremental`
- canonical universe: 993; eligible equities: 992; cash placeholder: 1
- selected names: 150
- collector attempted names: 36
- raw errors: 102
- request snapshot rows: 36
- request rows with a forward estimate: 2
- first repeated signatures: FMP `402 /stable/analyst-estimates`, Finnhub
  `403 /stock/eps-estimate`, and Finnhub
  `403 /stock/revenue-estimate`
- the same selected batch nevertheless contained valid FMP estimate rows for
  `ABBV` and `BABA`

Therefore FMP 402 is demonstrably not a safe global-disable condition. Those
rows remain in the immutable error audit as warning-only coverage misses and do
not consume `max_errors`. Finnhub's repeated 403 estimate signatures can open a
run-scoped circuit after three distinct names.

## Recorded diagnostics

The daily summary, archive manifest, and append-only archive index now record:

- circuit threshold and eligible status codes,
- tripped vendors and exact trip signature,
- accessible-response and estimate-data counts by vendor,
- skipped vendor/ticker calls,
- exact estimated estimate-HTTP requests avoided,
- raw error count,
- safety-budget error count,
- warning-only entitlement count, and
- probe count before a circuit decision.

The workflow fixes the threshold at 3. Threshold 0 remains available only as a
test/debug disable switch; it is not used by the daily schedule.

## Verification

Focused smokes cover both sides of the decision:

- a vendor with repeated Finnhub-like 403 signatures trips after three distinct
  names and avoids later estimate calls;
- FMP-like 402 rows do not trip the global circuit;
- one accessible vendor response prevents a later global trip;
- warning-only 402 rows do not exhaust even a deliberately small error budget;
- a 150-name blocked-endpoint simulation reaches all 150 names, limits Finnhub
  estimate probes to 6 calls, and records 294 avoided Finnhub estimate calls;
- queue acknowledgement, archive manifest hashing, and secret redaction remain
  intact.

No real provider workflow was dispatched for this change. The next scheduled
artifact must confirm the actual avoided-request count and whether all 150
selected names are acknowledged.

Full local PR validation passed `173/173` test files in `219.26` seconds.

## CAGR/MDD relevance and boundary

This change does not alter Main or Concentrated holdings, cash, orders, target
books, or historical CAGR/MDD. It improves the probability that the forward PIT
archive matures without silently stopping at the alphabetic head of the queue,
and it preserves valid partial FMP coverage that could otherwise be lost by an
over-broad circuit. That is necessary data substrate for a future preregistered
source screen, but forward snapshots cannot be promoted to seven-year
CAGR/MDD evidence.

No fullrun, backtest, production activation, live trading, provider purchase,
or portfolio mutation was performed.
