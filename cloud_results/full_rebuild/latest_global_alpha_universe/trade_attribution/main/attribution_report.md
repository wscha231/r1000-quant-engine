# Trade Attribution Report - main

- Generated: 2026-06-19T12:31:53.893010+00:00
- Schema: `trade-attribution-findings-v1`
- Analysis mode: `round_trip_journal`

## Broker-Ledger Headline

- CAGR: 39.56%
- Sharpe: 1.389
- MaxDD: -24.46%
- Trade count: 1459

## Win/Loss Distribution

- Round trips: 990
- Win rate: 57.7%
- Avg winner: $1,270
- Avg loser: $-701
- Total winners P&L: $725,308
- Total losers P&L: $-293,646

## MDD Window

- Peak: 2021-11-19, $233,276
- Trough: 2022-09-26, $176,207
- Drawdown: -24.46%
- Trades exited inside window: 137 (total P&L $-29,119)

## Broker Trades In MDD Window

- Executions: 203
- Buys / sells: 103 / 100
- Gross traded: $977,987
- Net cash delta: $103,828

## Top Position P&L Contributors

| Ticker | P&L | Avg weight | Max weight | Days held |
| --- | ---: | ---: | ---: | ---: |
| NET | $-24,940 | 4.0% | 12.3% | 28 |
| AMD | $-22,873 | 0.8% | 1.0% | 20 |
| TSLA | $-22,763 | 7.0% | 12.0% | 48 |
| NVDA | $-21,707 | 7.0% | 12.4% | 48 |
| SAIA | $-20,235 | 2.1% | 9.8% | 48 |
| ENPH | $-10,188 | 6.5% | 9.0% | 28 |
| CIEN | $-8,650 | 3.7% | 6.0% | 39 |
| U | $-8,514 | 3.3% | 5.9% | 28 |
| LAD | $-8,015 | 1.9% | 2.1% | 42 |
| STLD | $-7,825 | 2.9% | 4.0% | 42 |

## MDD Target-Book Feature Buckets

| Bucket | Linked P&L | Tickers | Avg weight | Max weight | Top tickers |
| --- | ---: | ---: | ---: | ---: | --- |
| information_technology_loss_cluster | $-113,876 | 12 | 4.9% | 12.0% | NET, AMD, NVDA, ENPH, CIEN, U, DDOG, ON |
| high_weight_market_leader | $-106,087 | 6 | 10.3% | 12.0% | NET, TSLA, NVDA, SAIA, ENPH, DDOG |
| weak_confirmation_weighted | $-102,286 | 8 | 9.0% | 12.0% | NET, TSLA, NVDA, ENPH, CIEN, WCC, DDOG, BE |
| qqq_underperforms_spy_weighted | $-8,650 | 1 | 6.1% | 6.1% | CIEN |
| negative_short_rs_weighted | $-4,137 | 1 | 5.0% | 5.0% | ON |
| below_ma50_weighted | $-4,137 | 1 | 5.0% | 5.0% | ON |
| high_vol_weighted | $-1,282 | 1 | 7.7% | 7.7% | BE |

## MDD Target-Book Context By Ticker

| Ticker | Linked P&L | Date range | Rows | Max weight | Lane | Regime |
| --- | ---: | --- | ---: | ---: | --- | --- |
| NET | $-24,940 | 2021-10-29 to 2021-11-30 | 2 | 12.0% | MARKET_LEADER | neutral |
| AMD | $-22,873 | 2021-12-31 to 2021-12-31 | 1 | 1.0% | MARKET_LEADER | bull |
| TSLA | $-22,763 | 2021-10-29 to 2021-12-31 | 3 | 12.0% | MARKET_LEADER | bull |
| NVDA | $-21,707 | 2021-10-29 to 2021-12-31 | 3 | 12.0% | MARKET_LEADER | bull |
| SAIA | $-20,235 | 2021-10-29 to 2021-12-31 | 3 | 9.3% | MARKET_LEADER | bull |
| ENPH | $-10,188 | 2021-10-29 to 2021-11-30 | 2 | 8.5% | MARKET_LEADER | neutral |
| CIEN | $-8,650 | 2021-12-31 to 2022-01-31 | 2 | 6.1% | MARKET_LEADER | neutral |
| U | $-8,514 | 2021-10-29 to 2021-11-30 | 2 | 4.9% | MARKET_LEADER | neutral |
| LAD | $-8,015 | 2022-01-31 to 2022-02-28 | 2 | 2.0% | MARKET_LEADER | bear |
| STLD | $-7,825 | 2022-04-29 to 2022-05-31 | 2 | 3.8% | MARKET_LEADER | bear |

## Findings (machine-readable in findings.json)

### [MEDIUM] `F3_target_exit_losers_deeper_than_rebalance_main`

**Evidence**: target_exit losers average $-786 loss over 316 trades, while target_rebalance losers average $-441 over 103 trades. Explicit exits are firing too late.

**Candidate fix**: Tighten the leader-rescue / stale-trim threshold so a position is exit-flagged earlier in its decline. Inspect tools/run_lifecycle_review_overlay.py and the stale_mega_leader_score weighting in r1000_main_v2.py.

### [MEDIUM] `F8_mdd_target_book_feature_bucket_main_information_technology_loss_cluster`

**Evidence**: Operating target-book rows linked to MDD losers show bucket `information_technology_loss_cluster` with $-113,876 linked position P&L (52% of top context loss), 12 tickers, avg weight 4.9%, max weight 12.0%. Top tickers: NET, AMD, NVDA, ENPH, CIEN, U, DDOG, ON, FTNT, AAPL, SNOW, MDB.

**Candidate fix**: Use the emitted mdd_policy_bucket_summary.csv and mdd_target_rows.csv to design one narrow PIT-safe entry/hold sizing rule. Do not promote the bucket itself; validate any rule through broker-ledger fast replay.

Research-only analysis. Production decisions still require broker-ledger and human review.
