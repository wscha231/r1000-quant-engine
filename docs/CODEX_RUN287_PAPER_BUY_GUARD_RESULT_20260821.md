# Run287 paper buy guard result — 2026-08-21

## Conclusion

The daily virtual-trading path now has a fail-closed handoff between the exact
same-close selector and the second paper-ledger transaction.  The handoff binds
the current marked paper accounts to the hash-verified canonical crisis state,
which already consumes current market, credit, volatility, rate, liquidity,
and breadth evidence.

The guard does not promote the rejected July fixed-book crisis policy.  It does
not force a portfolio-wide cash raise or sell a holding merely because the
market state deteriorated.  It limits only selector-requested new or increased
equity exposure:

| State | Incremental-buy multiplier |
|---|---:|
| GREEN / REENTRY_STAGE_3 | 100% |
| REENTRY_STAGE_2 | 60% |
| REENTRY_STAGE_1 | 25% |
| WATCH / DEFENSE / CRISIS / DEGRADED_DATA | 0% |

Selector-requested reductions, lifecycle settlements, prior pending-order
resolution, and exact-close account marking remain available.  Missing,
stale, mismatched, or invalid crisis/macro evidence blocks the second paper
transaction and preserves the already accepted mark.

## Evidence boundary

- virtual/paper trading only
- next-close, integer-share execution contract retained
- target and manifest hashes are pinned at the paper-ledger handoff
- Reserve reasons are reconciled after blocked incremental weight is retained
- no fullrun executed
- no historical CAGR/MDD claim
- no live or production trading path enabled
- no automatic model or policy promotion

The next performance gate is one preregistered broker-ledger replay comparing
the unguarded current selector target with this incremental-buy guard on
identical price, universe, lifecycle, macro, and cost inputs.  The older July
result remains diagnostic only because its fixed-book crisis arm reduced CAGR
materially even while improving Main drawdown.
