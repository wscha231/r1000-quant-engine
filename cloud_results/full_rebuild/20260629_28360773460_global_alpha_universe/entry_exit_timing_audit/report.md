# Entry/Exit Timing Audit

Measurement-only diagnostic. No strategy or target-book mutation.

## Summary

- status: `completed`
- metric mode: `broker_ledger_next_close`
- production mutation allowed: `False`
- entry rows: 1574
- exit rows: 1574
- premature sell candidates: 550

## Portfolio Metrics

- `concentrated`: trades 438, median hold 32.5d, held 180d+ 0.7%, held 365d+ 0.0%
- `main`: trades 1136, median hold 57.0d, held 180d+ 2.4%, held 365d+ 0.0%

## Interpretation Rules

- Forward returns after a sell are audit labels only, not live signals.
- Premature sell candidates require positive sold-name forward return and a non-broken leader state at exit.
