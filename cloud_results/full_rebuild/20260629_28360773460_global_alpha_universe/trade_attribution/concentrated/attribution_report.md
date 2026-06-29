# Trade Attribution Report - concentrated

- Generated: 2026-06-29T12:58:57.484000+00:00
- Schema: `trade-attribution-findings-v1`
- Analysis mode: `round_trip_journal`

## Broker-Ledger Headline

- CAGR: 46.66%
- Sharpe: 1.401
- MaxDD: -24.12%
- Trade count: 672

## Win/Loss Distribution

- Round trips: 438
- Win rate: 57.5%
- Avg winner: $5,336
- Avg loser: $-1,605
- Total winners P&L: $1,344,780
- Total losers P&L: $-298,442

## MDD Window

- Peak: 2021-11-19, $284,722
- Trough: 2023-03-15, $216,045
- Drawdown: -24.12%
- Trades exited inside window: 70 (total P&L $-35,469)

## Broker Trades In MDD Window

- Executions: 112
- Buys / sells: 54 / 58
- Gross traded: $1,296,021
- Net cash delta: $706

## Top Position P&L Contributors

| Ticker | P&L | Avg weight | Max weight | Days held |
| --- | ---: | ---: | ---: | ---: |
| DDOG | $-53,766 | 6.9% | 21.5% | 28 |
| ORLY | $-19,042 | 5.9% | 10.2% | 41 |
| STLD | $-16,440 | 1.5% | 2.3% | 42 |
| MA | $-16,032 | 4.6% | 10.7% | 123 |
| NVDA | $-11,828 | 5.7% | 7.9% | 48 |
| BLDR | $-10,084 | 3.6% | 6.8% | 84 |
| NET | $-8,436 | 26.3% | 27.3% | 6 |
| TMUS | $-6,328 | 2.3% | 4.1% | 42 |
| WCC | $-6,002 | 5.0% | 6.8% | 65 |
| LOPE | $-4,439 | 7.6% | 9.1% | 42 |

## MDD Target-Book Feature Buckets

| Bucket | Linked P&L | Tickers | Avg weight | Max weight | Top tickers |
| --- | ---: | ---: | ---: | ---: | --- |
| information_technology_loss_cluster | $-76,568 | 4 | 8.2% | 26.7% | DDOG, NVDA, NET, ACLS |
| weak_confirmation_weighted | $-76,396 | 11 | 10.0% | 26.7% | ORLY, MA, NVDA, NET, WCC, LOPE, RKLB, DXCM |
| high_weight_market_leader | $-68,928 | 5 | 15.0% | 26.7% | DDOG, NET, DXCM, PCTY, TSLA |
| qqq_underperforms_spy_weighted | $-39,512 | 3 | 9.1% | 10.6% | ORLY, MA, LOPE |
| negative_short_rs_weighted | $-30,870 | 2 | 6.9% | 9.9% | ORLY, NVDA |
| high_vol_weighted | $-3,643 | 1 | 7.6% | 7.6% | RKLB |

## MDD Target-Book Context By Ticker

| Ticker | Linked P&L | Date range | Rows | Max weight | Lane | Regime |
| --- | ---: | --- | ---: | ---: | --- | --- |
| DDOG | $-53,766 | 2021-10-29 to 2021-11-30 | 2 | 19.5% | MARKET_LEADER | neutral |
| ORLY | $-19,042 | 2022-11-30 to 2022-12-30 | 2 | 9.9% | QUALITY_COMPOUNDER | bear |
| STLD | $-16,440 | 2022-04-29 to 2022-05-31 | 2 | 2.2% | MARKET_LEADER | bear |
| MA | $-16,032 | 2022-01-31 to 2023-01-31 | 6 | 10.6% | QUALITY_COMPOUNDER | neutral |
| NVDA | $-11,828 | 2021-10-29 to 2021-12-31 | 3 | 7.6% | MARKET_LEADER | bull |
| BLDR | $-10,084 | 2021-11-30 to 2022-02-28 | 4 | 5.5% | MARKET_LEADER | bear |
| NET | $-8,436 | 2021-10-29 to 2021-10-29 | 1 | 26.7% | MARKET_LEADER | bull |
| TMUS | $-6,328 | 2022-09-30 to 2022-10-31 | 2 | 3.8% | MARKET_LEADER | bear |
| WCC | $-6,002 | 2022-07-29 to 2022-10-31 | 3 | 6.3% | QUALITY_COMPOUNDER | bear |
| LOPE | $-4,439 | 2022-10-31 to 2022-11-30 | 2 | 8.2% | MARKET_LEADER | neutral |

## Findings (machine-readable in findings.json)

### [MEDIUM] `F3_target_exit_losers_deeper_than_rebalance_concentrated`

**Evidence**: target_exit losers average $-1,658 loss over 141 trades, while target_rebalance losers average $-1,437 over 45 trades. Explicit exits are firing too late.

**Candidate fix**: Tighten the leader-rescue / stale-trim threshold so a position is exit-flagged earlier in its decline. Inspect tools/run_lifecycle_review_overlay.py and the stale_mega_leader_score weighting in r1000_main_v2.py.

### [MEDIUM] `F8_mdd_target_book_feature_bucket_concentrated_information_technology_loss_cluster`

**Evidence**: Operating target-book rows linked to MDD losers show bucket `information_technology_loss_cluster` with $-76,568 linked position P&L (43% of top context loss), 4 tickers, avg weight 8.2%, max weight 26.7%. Top tickers: DDOG, NVDA, NET, ACLS.

**Candidate fix**: Use the emitted mdd_policy_bucket_summary.csv and mdd_target_rows.csv to design one narrow PIT-safe entry/hold sizing rule. Do not promote the bucket itself; validate any rule through broker-ledger fast replay.

Research-only analysis. Production decisions still require broker-ledger and human review.
