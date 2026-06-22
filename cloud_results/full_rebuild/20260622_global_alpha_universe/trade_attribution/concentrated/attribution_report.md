# Trade Attribution Report - concentrated

- Generated: 2026-06-22T05:52:00.379571+00:00
- Schema: `trade-attribution-findings-v1`
- Analysis mode: `round_trip_journal`

## Broker-Ledger Headline

- CAGR: 44.67%
- Sharpe: 1.394
- MaxDD: -25.87%
- Trade count: 591

## Win/Loss Distribution

- Round trips: 392
- Win rate: 54.6%
- Avg winner: $4,815
- Avg loser: $-1,329
- Total winners P&L: $1,030,389
- Total losers P&L: $-236,590

## MDD Window

- Peak: 2021-11-08, $231,637
- Trough: 2023-08-17, $171,706
- Drawdown: -25.87%
- Trades exited inside window: 93 (total P&L $-25,011)

## Broker Trades In MDD Window

- Executions: 143
- Buys / sells: 69 / 74
- Gross traded: $1,646,025
- Net cash delta: $-9,829

## Top Position P&L Contributors

| Ticker | P&L | Avg weight | Max weight | Days held |
| --- | ---: | ---: | ---: | ---: |
| DDOG | $-44,639 | 10.7% | 22.6% | 37 |
| NVDA | $-30,088 | 5.5% | 7.9% | 42 |
| BLD | $-23,268 | 13.4% | 21.6% | 41 |
| ORLY | $-15,267 | 5.9% | 10.2% | 41 |
| STLD | $-13,262 | 1.6% | 2.4% | 42 |
| MA | $-12,839 | 4.6% | 10.7% | 123 |
| MLI | $-11,881 | 7.4% | 10.7% | 42 |
| XPO | $-11,170 | 18.3% | 23.1% | 33 |
| NET | $-6,550 | 26.9% | 28.3% | 15 |
| TMUS | $-5,036 | 2.3% | 4.1% | 42 |

## MDD Target-Book Feature Buckets

| Bucket | Linked P&L | Tickers | Avg weight | Max weight | Top tickers |
| --- | ---: | ---: | ---: | ---: | --- |
| weak_confirmation_weighted | $-129,652 | 13 | 10.8% | 26.9% | NVDA, BLD, ORLY, MA, MLI, XPO, NET, WCC |
| qqq_underperforms_spy_weighted | $-118,153 | 12 | 12.5% | 28.5% | DDOG, BLD, ORLY, MA, XPO, LOPE, DXCM, JBL |
| information_technology_loss_cluster | $-94,199 | 8 | 11.7% | 28.5% | DDOG, NVDA, NET, BILL, ON, ONTO, JBL, MSI |
| high_weight_market_leader | $-79,660 | 10 | 15.8% | 28.5% | DDOG, XPO, NET, BILL, ON, DXCM, ONTO, TSLA |
| negative_short_rs_weighted | $-71,541 | 6 | 9.3% | 20.0% | NVDA, BLD, ORLY, JBL, TXRH, CHE |
| high_vol_weighted | $-3,716 | 2 | 9.5% | 11.4% | RKLB, TXRH |

## MDD Target-Book Context By Ticker

| Ticker | Linked P&L | Date range | Rows | Max weight | Lane | Regime |
| --- | ---: | --- | ---: | ---: | --- | --- |
| DDOG | $-44,639 | 2021-09-30 to 2021-11-30 | 3 | 20.1% | MARKET_LEADER | neutral |
| NVDA | $-30,088 | 2021-11-30 to 2021-12-31 | 2 | 7.6% | MARKET_LEADER | bull |
| BLD | $-23,268 | 2023-03-31 to 2023-04-28 | 2 | 20.0% | MARKET_LEADER | neutral |
| ORLY | $-15,267 | 2022-11-30 to 2022-12-30 | 2 | 9.9% | QUALITY_COMPOUNDER | bear |
| STLD | $-13,262 | 2022-04-29 to 2022-05-31 | 2 | 2.2% | MARKET_LEADER | bear |
| MA | $-12,839 | 2022-01-31 to 2023-01-31 | 6 | 10.6% | QUALITY_COMPOUNDER | neutral |
| MLI | $-11,881 | 2023-02-28 to 2023-03-31 | 2 | 10.6% | MARKET_LEADER | bull |
| XPO | $-11,170 | 2023-06-30 to 2023-07-31 | 2 | 20.0% | MARKET_LEADER | bull |
| NET | $-6,550 | 2021-10-29 to 2021-10-29 | 1 | 26.9% | MARKET_LEADER | bull |
| TMUS | $-5,036 | 2022-09-30 to 2022-10-31 | 2 | 3.8% | MARKET_LEADER | bear |

## Findings (machine-readable in findings.json)

### [MEDIUM] `F3_target_exit_losers_deeper_than_rebalance_concentrated`

**Evidence**: target_exit losers average $-1,405 loss over 130 trades, while target_rebalance losers average $-1,124 over 48 trades. Explicit exits are firing too late.

**Candidate fix**: Tighten the leader-rescue / stale-trim threshold so a position is exit-flagged earlier in its decline. Inspect tools/run_lifecycle_review_overlay.py and the stale_mega_leader_score weighting in r1000_main_v2.py.

### [MEDIUM] `F8_mdd_target_book_feature_bucket_concentrated_weak_confirmation_weighted`

**Evidence**: Operating target-book rows linked to MDD losers show bucket `weak_confirmation_weighted` with $-129,652 linked position P&L (61% of top context loss), 13 tickers, avg weight 10.8%, max weight 26.9%. Top tickers: NVDA, BLD, ORLY, MA, MLI, XPO, NET, WCC, LOPE, RKLB, DXCM, ONTO.

**Candidate fix**: Use the emitted mdd_policy_bucket_summary.csv and mdd_target_rows.csv to design one narrow PIT-safe entry/hold sizing rule. Do not promote the bucket itself; validate any rule through broker-ledger fast replay.

Research-only analysis. Production decisions still require broker-ledger and human review.
