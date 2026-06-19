# Entry/Exit Timing Audit

Measurement-only diagnostic. No strategy or target-book mutation.

## Summary

- status: `completed`
- metric mode: `broker_ledger_next_close`
- production mutation allowed: `False`
- entry rows: 1333
- exit rows: 1333
- premature sell candidates: 461

## Portfolio Metrics

- `concentrated`: trades 343, median hold 33.0d, held 180d+ 0.9%, held 365d+ 0.0%
- `main`: trades 990, median hold 58.0d, held 180d+ 2.5%, held 365d+ 0.0%

## Interpretation Rules

- Forward returns after a sell are audit labels only, not live signals.
- Premature sell candidates require positive sold-name forward return and a non-broken leader state at exit.
