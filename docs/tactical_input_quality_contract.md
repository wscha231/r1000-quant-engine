# Tactical research input integrity

This gate does not change tactical scores, selection, costs, or risk limits.
It determines whether a current-session trade proposal may be published.

- Resolve the last completed NYSE close from the exchange calendar; never treat an intraday calendar date as a completed close. A date-only historical request means UTC end of day, capped at the actual current time.
- Require the scored cross-section and every candidate close to refer to that session. Monthly or older scores remain research context, not a current ranking or replacement instruction.
- Reject dates older than the prior successful tactical report, missing held names, invalid prices/ranks, duplicate tickers, or a candidate count below half the preceding count. The 50% guard is an explicit input-health threshold, not a fitted alpha signal.
- A failed gate writes only a separate dated diagnostic and exits nonzero. A duplicate session writes a no-op diagnostic. Neither overwrites the latest portfolio, trade plan, or prior successful summary.
- Direct trade-plan calls also retain an existing holding when its price/rank evidence is absent or stale. Missing evidence cannot generate a rank-replacement sale.
- Non-finite macro and ETF inputs produce `unknown`, not an inferred market regime.
- Required scanner, score-file, and tactical failures propagate through After-Close. Diagnostic artifact upload remains available; failed runs do not commit daily cloud results.

This contract does not authorize orders, accepted-account migration, historical PIT backfill, or strategy promotion. Daily accepted-account and sector-research skip propagation use their separate workflow contracts.
