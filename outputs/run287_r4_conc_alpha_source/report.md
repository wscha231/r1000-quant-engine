# Run287 R4 Concentrated Alpha Source Readiness

Status: `completed`
Decision label: `blocked_missing_w4_decision_time_source`

Research-only readiness audit. No fullrun, hook, data download, threshold
tuning, production promotion, or live-trading action was performed.

## Decision

- user_decision: `open_w4_decision_time_source`
- rank_rs_revenue_variants_allowed: `false`
- hook_allowed: `false`
- next_action_requires_oos_source_screen: `true`

## Earnings / Guidance Source

- input_used: `data_pit\events\earnings_revision_signals.parquet`
- raw_feed_exists: `false`
- signals_exists: `false`
- coverage_status: `DATA_INSUFFICIENT`
- research_ready: `false`
- coverage_eligible_rows: `0`
- coverage_eligible_tickers: `0`
- directional_guidance_rows: `0`
- history_depth_ticker_count: `0`

## Alternate Source Inventory

| Source | Exists | Rows | Tickers | Decision-time usable |
| --- | ---: | ---: | ---: | ---: |
| form4_transactions | false | 0 | 0 | false |
| institutional_13f_holdings | false | 0 | 0 | false |
| sec_ownership_signals | false | 0 | 0 | false |
| etf_thematic_signals | false | 0 | 0 | false |

## Verdict

- candidate_source_ready: `false`
- candidate_allowed: `false`
- A source becoming research-ready only permits an OOS source screen.
- It does not permit a Concentrated hook or fullrun by itself.
