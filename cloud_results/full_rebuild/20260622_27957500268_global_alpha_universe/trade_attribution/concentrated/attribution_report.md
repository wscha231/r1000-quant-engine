# Trade Attribution Report - concentrated

- Generated: 2026-06-22T16:34:56.489183+00:00
- Schema: `trade-attribution-findings-v1`
- Analysis mode: `round_trip_journal`

## Broker-Ledger Headline

- CAGR: 45.95%
- Sharpe: 1.434
- MaxDD: -24.59%
- Trade count: 587

## Win/Loss Distribution

- Round trips: 388
- Win rate: 55.2%
- Avg winner: $4,933
- Avg loser: $-1,346
- Total winners P&L: $1,055,556
- Total losers P&L: $-234,185

## MDD Window

- Peak: 2021-11-18, $224,544
- Trough: 2023-08-17, $169,322
- Drawdown: -24.59%
- Trades exited inside window: 90 (total P&L $-24,871)

## Broker Trades In MDD Window

- Executions: 141
- Buys / sells: 69 / 72
- Gross traded: $1,616,677
- Net cash delta: $-9,891

## Top Position P&L Contributors

| Ticker | P&L | Avg weight | Max weight | Days held |
| --- | ---: | ---: | ---: | ---: |
| DDOG | $-42,141 | 7.3% | 21.6% | 29 |
| NVDA | $-30,088 | 5.6% | 7.9% | 42 |
| BLD | $-23,061 | 13.4% | 21.7% | 41 |
| ORLY | $-15,021 | 5.8% | 10.1% | 41 |
| STLD | $-13,214 | 1.9% | 3.2% | 42 |
| MA | $-12,457 | 4.7% | 10.9% | 123 |
| MLI | $-11,599 | 7.4% | 10.7% | 42 |
| XPO | $-11,121 | 18.2% | 23.0% | 33 |
| NET | $-8,761 | 27.4% | 28.4% | 7 |
| WCC | $-6,251 | 4.8% | 7.0% | 65 |

## MDD Target-Book Feature Buckets

| Bucket | Linked P&L | Tickers | Avg weight | Max weight | Top tickers |
| --- | ---: | ---: | ---: | ---: | --- |
| weak_confirmation_weighted | $-131,119 | 13 | 10.8% | 27.3% | NVDA, BLD, ORLY, MA, MLI, XPO, NET, WCC |
| information_technology_loss_cluster | $-88,700 | 7 | 11.9% | 28.5% | DDOG, NVDA, NET, ON, ONTO, MSI, JBL |
| high_weight_market_leader | $-73,791 | 10 | 15.5% | 28.5% | DDOG, XPO, NET, ON, DXCM, ONTO, PCTY, JBL |
| negative_short_rs_weighted | $-69,976 | 6 | 9.3% | 20.0% | NVDA, BLD, ORLY, TXRH, JBL, CHE |
| qqq_underperforms_spy_weighted | $-68,801 | 10 | 11.7% | 28.5% | BLD, ORLY, MA, XPO, LOPE, MSI, TXRH, JBL |
| high_vol_weighted | $-3,658 | 2 | 9.5% | 11.4% | RKLB, TXRH |

## MDD Target-Book Context By Ticker

| Ticker | Linked P&L | Date range | Rows | Max weight | Lane | Regime |
| --- | ---: | --- | ---: | ---: | --- | --- |
| DDOG | $-42,141 | 2021-10-29 to 2021-11-30 | 2 | 19.2% | MARKET_LEADER | neutral |
| NVDA | $-30,088 | 2021-11-30 to 2021-12-31 | 2 | 7.6% | MARKET_LEADER | bull |
| BLD | $-23,061 | 2023-03-31 to 2023-04-28 | 2 | 20.0% | MARKET_LEADER | neutral |
| ORLY | $-15,021 | 2022-11-30 to 2022-12-30 | 2 | 9.8% | QUALITY_COMPOUNDER | bear |
| STLD | $-13,214 | 2022-04-29 to 2022-05-31 | 2 | 3.0% | MARKET_LEADER | bear |
| MA | $-12,457 | 2022-01-31 to 2023-01-31 | 6 | 10.9% | QUALITY_COMPOUNDER | neutral |
| MLI | $-11,599 | 2023-02-28 to 2023-03-31 | 2 | 10.6% | MARKET_LEADER | bull |
| XPO | $-11,121 | 2023-06-30 to 2023-07-31 | 2 | 20.0% | MARKET_LEADER | bull |
| NET | $-8,761 | 2021-10-29 to 2021-10-29 | 1 | 27.3% | MARKET_LEADER | bull |
| WCC | $-6,251 | 2022-07-29 to 2022-10-31 | 3 | 6.3% | QUALITY_COMPOUNDER | bear |

## Findings (machine-readable in findings.json)

### [MEDIUM] `F3_target_exit_losers_deeper_than_rebalance_concentrated`

**Evidence**: target_exit losers average $-1,407 loss over 129 trades, while target_rebalance losers average $-1,171 over 45 trades. Explicit exits are firing too late.

**Candidate fix**: Tighten the leader-rescue / stale-trim threshold so a position is exit-flagged earlier in its decline. Inspect tools/run_lifecycle_review_overlay.py and the stale_mega_leader_score weighting in r1000_main_v2.py.

### [MEDIUM] `F8_mdd_target_book_feature_bucket_concentrated_weak_confirmation_weighted`

**Evidence**: Operating target-book rows linked to MDD losers show bucket `weak_confirmation_weighted` with $-131,119 linked position P&L (65% of top context loss), 13 tickers, avg weight 10.8%, max weight 27.3%. Top tickers: NVDA, BLD, ORLY, MA, MLI, XPO, NET, WCC, LOPE, DXCM, RKLB, ONTO.

**Candidate fix**: Use the emitted mdd_policy_bucket_summary.csv and mdd_target_rows.csv to design one narrow PIT-safe entry/hold sizing rule. Do not promote the bucket itself; validate any rule through broker-ledger fast replay.

Research-only analysis. Production decisions still require broker-ledger and human review.
