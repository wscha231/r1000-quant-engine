# Trade Attribution Report - main

- Generated: 2026-07-05T04:30:11.266014+00:00
- Schema: `trade-attribution-findings-v1`
- Analysis mode: `round_trip_journal`

## Broker-Ledger Headline

- CAGR: 32.94%
- Sharpe: 1.237
- MaxDD: -25.65%
- Trade count: 1612

## Win/Loss Distribution

- Round trips: 1067
- Win rate: 58.4%
- Avg winner: $1,440
- Avg loser: $-719
- Total winners P&L: $896,824
- Total losers P&L: $-319,068

## MDD Window

- Peak: 2021-11-19, $257,680
- Trough: 2022-09-26, $191,578
- Drawdown: -25.65%
- Trades exited inside window: 133 (total P&L $-36,123)

## Broker Trades In MDD Window

- Executions: 203
- Buys / sells: 104 / 99
- Gross traded: $1,100,352
- Net cash delta: $110,011

## Top Position P&L Contributors

| Ticker | P&L | Avg weight | Max weight | Days held |
| --- | ---: | ---: | ---: | ---: |
| AMD | $-28,845 | 0.9% | 1.0% | 20 |
| NVDA | $-26,683 | 7.8% | 13.7% | 48 |
| NET | $-25,732 | 3.8% | 11.5% | 28 |
| TSLA | $-23,521 | 6.5% | 11.1% | 48 |
| DDOG | $-18,375 | 4.9% | 8.9% | 51 |
| SAIA | $-13,486 | 5.3% | 9.0% | 26 |
| ENPH | $-13,263 | 7.0% | 10.2% | 28 |
| NOW | $-9,979 | 0.4% | 0.4% | 20 |
| U | $-9,557 | 3.2% | 5.8% | 28 |
| STLD | $-8,374 | 2.5% | 3.4% | 42 |

## MDD Target-Book Feature Buckets

| Bucket | Linked P&L | Tickers | Avg weight | Max weight | Top tickers |
| --- | ---: | ---: | ---: | ---: | --- |
| information_technology_loss_cluster | $-148,355 | 14 | 4.5% | 13.3% | AMD, NVDA, NET, DDOG, ENPH, NOW, U, ON |
| high_weight_market_leader | $-122,607 | 7 | 10.1% | 13.3% | NVDA, NET, TSLA, DDOG, SAIA, ENPH, BE |
| weak_confirmation_weighted | $-109,121 | 6 | 9.8% | 13.3% | NVDA, NET, TSLA, DDOG, ENPH, BE |
| negative_short_rs_weighted | $-17,596 | 2 | 5.3% | 5.9% | SAIA, ON |
| below_ma50_weighted | $-4,110 | 1 | 5.9% | 5.9% | ON |
| high_vol_weighted | $-1,546 | 1 | 8.4% | 8.4% | BE |

## MDD Target-Book Context By Ticker

| Ticker | Linked P&L | Date range | Rows | Max weight | Lane | Regime |
| --- | ---: | --- | ---: | ---: | --- | --- |
| AMD | $-28,845 | 2021-12-31 to 2021-12-31 | 1 | 1.1% | MARKET_LEADER | bull |
| NVDA | $-26,683 | 2021-10-29 to 2021-12-31 | 3 | 13.3% | MARKET_LEADER | bull |
| NET | $-25,732 | 2021-10-29 to 2021-11-30 | 2 | 11.3% | MARKET_LEADER | neutral |
| TSLA | $-23,521 | 2021-10-29 to 2021-12-31 | 3 | 11.3% | MARKET_LEADER | bull |
| DDOG | $-18,375 | 2021-10-29 to 2022-02-28 | 3 | 8.1% | TOP7_MANAGER_DISCOVERY | bear |
| SAIA | $-13,486 | 2021-10-29 to 2021-12-31 | 2 | 8.6% | MARKET_LEADER | bull |
| ENPH | $-13,263 | 2021-10-29 to 2021-11-30 | 2 | 9.6% | MARKET_LEADER | neutral |
| NOW | $-9,979 | 2022-06-30 to 2022-06-30 | 1 | 0.4% | QUALITY_COMPOUNDER | bear |
| U | $-9,557 | 2021-10-29 to 2021-11-30 | 2 | 4.9% | MARKET_LEADER | neutral |
| STLD | $-8,374 | 2022-04-29 to 2022-05-31 | 2 | 3.2% | MARKET_LEADER | bear |

## Findings (machine-readable in findings.json)

### [MEDIUM] `F3_target_exit_losers_deeper_than_rebalance_main`

**Evidence**: target_exit losers average $-782 loss over 345 trades, while target_rebalance losers average $-498 over 99 trades. Explicit exits are firing too late.

**Candidate fix**: Tighten the leader-rescue / stale-trim threshold so a position is exit-flagged earlier in its decline. Inspect tools/run_lifecycle_review_overlay.py and the stale_mega_leader_score weighting in r1000_main_v2.py.

### [MEDIUM] `F8_mdd_target_book_feature_bucket_main_information_technology_loss_cluster`

**Evidence**: Operating target-book rows linked to MDD losers show bucket `information_technology_loss_cluster` with $-148,355 linked position P&L (61% of top context loss), 14 tickers, avg weight 4.5%, max weight 13.3%. Top tickers: AMD, NVDA, NET, DDOG, ENPH, NOW, U, ON, FICO, FTNT, SNOW, ANET.

**Candidate fix**: Use the emitted mdd_policy_bucket_summary.csv and mdd_target_rows.csv to design one narrow PIT-safe entry/hold sizing rule. Do not promote the bucket itself; validate any rule through broker-ledger fast replay.

Research-only analysis. Production decisions still require broker-ledger and human review.
