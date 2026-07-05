# Entry/Exit Timing Audit

Measurement-only diagnostic. No strategy or target-book mutation.

## Summary

- status: `completed`
- metric mode: `broker_ledger_next_close`
- production mutation allowed: `False`
- entry rows: 1516
- exit rows: 1516
- premature sell candidates: 541

## Portfolio Metrics

- `concentrated`: trades 449, median hold 32.0d, held 180d+ 0.0%, held 365d+ 0.0%
- `main`: trades 1067, median hold 33.0d, held 180d+ 2.3%, held 365d+ 0.0%

## Interpretation Rules

- Forward returns after a sell are audit labels only, not live signals.
- Premature sell candidates require positive sold-name forward return and a non-broken leader state at exit.
