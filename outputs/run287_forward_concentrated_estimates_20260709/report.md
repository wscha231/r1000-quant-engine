# Run287 Forward Concentrated Estimate Archive - 2026-07-09

- Workflow run: `28997279936`
- Status: `blocked_partial_coverage`
- Reason: `coverage_below_80pct_warn_only`
- Vendor order: `['fmp', 'finnhub']`
- Fetch sources: `['finnhub', 'fmp']`
- Estimate coverage: `1/5` (20.0%)
- Raw key pattern found: `False`
- Backtest acceptance allowed: `False`
- Production activation allowed: `False`
- Live trading enabled: `False`

## Snapshot Rows

| ticker | fetch_source | has_forward_estimate | vendor_estimate_access | est_eps_fy1 | est_eps_fy2 | est_rev_fy1 | est_dispersion | earnings_surprise_last | surprise_streak | available_from |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| MU | finnhub | 0 | False | 0 | 0 | 0 | 0 | 17.326 | 4 | 2026-07-09 |
| SNDK | finnhub | 0 | False | 0 | 0 | 0 | 0 | 57.8834 | 4 | 2026-07-09 |
| AMD | fmp | 1 | True | 2.64582 | 3.49889 | 2.35204e+10 | 0.294414 | 4.7881 | 3 | 2026-07-09 |
| UMC | finnhub | 0 | False | 0 | 0 | 0 | 0 | 48.6518 | 1 | 2026-07-09 |
| TXN | finnhub | 0 | False | 0 | 0 | 0 | 0 | 21.6069 | 1 | 2026-07-09 |

## Corrected Confirmation Signals

| ticker | has_forward_estimate | estimate_revision_confirmed | estimate_revision_replacement_gate_pass | estimate_revision_future_winner_multiplier | est_eps_revision_30d | est_eps_revision_90d | est_eps_revision_breadth | est_rev_revision_30d | est_dispersion_change_30d | available_from |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| AMD | 1 | 1 | 1 | 1.05 | 0 | 0 | 1 | 0 | 0 | 2026-07-09 00:00:00 |
| MU | 0 | 0 | 0 | 1 | 0 | 0 | 0.961538 | 0 | 0 | 2026-07-09 00:00:00 |
| SNDK | 0 | 0 | 0 | 1 | 0 | 0 | 1 | 0 | 0 | 2026-07-09 00:00:00 |
| TXN | 0 | 0 | 0 | 1 | 0 | 0 | 0.727273 | 0 | 0 | 2026-07-09 00:00:00 |
| UMC | 0 | 0 | 0 | 1 | 0 | 0 | 0.555556 | 0 | 0 | 2026-07-09 00:00:00 |

## Verdict

- `blocked_partial_coverage`: free vendor coverage is too low for a Concentrated confirmation decision.
- Confirmed tickers after the forward-estimate guard: `AMD`.
- This is forward-only archive evidence and cannot change historical 7Y CAGR/MDD.
