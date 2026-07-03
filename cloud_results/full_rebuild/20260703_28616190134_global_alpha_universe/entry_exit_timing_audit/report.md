# Entry/Exit Timing Audit

Measurement-only diagnostic. No strategy or target-book mutation.

## Summary

- status: `completed`
- metric mode: `broker_ledger_next_close`
- production mutation allowed: `False`
- entry rows: 1563
- exit rows: 1563
- premature sell candidates: 559

## Portfolio Metrics

- `concentrated`: trades 406, median hold 33.0d, held 180d+ 0.7%, held 365d+ 0.0%
- `main`: trades 1157, median hold 58.0d, held 180d+ 2.4%, held 365d+ 0.0%

## Interpretation Rules

- Forward returns after a sell are audit labels only, not live signals.
- Premature sell candidates require positive sold-name forward return and a non-broken leader state at exit.
