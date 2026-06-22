# Decision Cadence Review

- production_mutated: `false`
- daily full-universe rerank: `false`
- full_universe_rerank_frequency: `monthly_or_event_triggered`
- crisis_state: `GREEN`
- daily_exit_review_count: `7`
- daily_warning_or_no_add_count: `4`
- weekly_add_candidate_count: `31`
- mid_month_reentry_allowed: `true`

## Cadence

- Daily: crisis/reentry plus current holdings breakdown/no-add review.
- Weekly: holdings/watchlist RS, technicals, and valuation snapshot refresh.
- Monthly/Event: full universe re-ranking and target book rebuild review.

## Re-entry

- If crisis defense triggers early in the month, re-entry does not wait for month-end.
- `REENTRY_READY` plus confirmation can mutate the target book mid-month.
- Redeploy is staged: DUAL_LEADER first, then sector leaders, then normal lane allocation.

This report is operator-review only and does not place trades.
