# Trade Attribution Report - concentrated

- Generated: 2026-06-22T05:48:35.021604+00:00
- Schema: `trade-attribution-findings-v1`
- Analysis mode: `round_trip_journal`

## Broker-Ledger Headline

- CAGR: 45.06%
- Sharpe: 1.399
- MaxDD: -26.05%
- Trade count: 590

## Win/Loss Distribution

- Round trips: 390
- Win rate: 54.6%
- Avg winner: $4,815
- Avg loser: $-1,354
- Total winners P&L: $1,025,516
- Total losers P&L: $-239,693

## MDD Window

- Peak: 2021-11-08, $229,479
- Trough: 2023-08-17, $169,703
- Drawdown: -26.05%
- Trades exited inside window: 92 (total P&L $-25,148)

## Broker Trades In MDD Window

- Executions: 142
- Buys / sells: 69 / 73
- Gross traded: $1,809,971
- Net cash delta: $-9,899

## Top Position P&L Contributors

| Ticker | P&L | Avg weight | Max weight | Days held |
| --- | ---: | ---: | ---: | ---: |
| DDOG | $-44,256 | 10.7% | 22.7% | 37 |
| NVDA | $-29,767 | 5.6% | 7.9% | 42 |
| BLD | $-23,061 | 13.4% | 21.6% | 41 |
| TMUS | $-16,423 | 5.8% | 11.3% | 42 |
| MA | $-15,132 | 4.9% | 11.4% | 123 |
| FANG | $-14,835 | 5.8% | 10.9% | 43 |
| ORLY | $-14,611 | 6.0% | 10.2% | 41 |
| STLD | $-11,962 | 3.8% | 6.6% | 42 |
| MLI | $-11,808 | 7.4% | 10.8% | 42 |
| XPO | $-11,101 | 18.3% | 23.1% | 33 |

## MDD Target-Book Feature Buckets

| Bucket | Linked P&L | Tickers | Avg weight | Max weight | Top tickers |
| --- | ---: | ---: | ---: | ---: | --- |
| weak_confirmation_weighted | $-174,385 | 16 | 10.6% | 27.0% | NVDA, BLD, TMUS, MA, FANG, ORLY, STLD, MLI |
| qqq_underperforms_spy_weighted | $-171,044 | 17 | 11.7% | 28.5% | DDOG, BLD, TMUS, MA, FANG, ORLY, STLD, XPO |
| negative_short_rs_weighted | $-104,531 | 9 | 9.4% | 20.0% | NVDA, BLD, TMUS, FANG, ORLY, JBL, TXRH, PLNT |
| information_technology_loss_cluster | $-95,474 | 8 | 11.8% | 28.5% | DDOG, NVDA, NET, BILL, JBL, ON, ONTO, MSI |
| high_weight_market_leader | $-80,784 | 10 | 15.8% | 28.5% | DDOG, XPO, NET, BILL, JBL, ON, DXCM, ONTO |
| below_ma50_weighted | $-31,258 | 2 | 10.5% | 10.5% | TMUS, FANG |
| high_vol_weighted | $-30,472 | 4 | 8.9% | 11.4% | FANG, STLD, RKLB, TXRH |

## MDD Target-Book Context By Ticker

| Ticker | Linked P&L | Date range | Rows | Max weight | Lane | Regime |
| --- | ---: | --- | ---: | ---: | --- | --- |
| DDOG | $-44,256 | 2021-09-30 to 2021-11-30 | 3 | 20.1% | MARKET_LEADER | neutral |
| NVDA | $-29,767 | 2021-11-30 to 2021-12-31 | 2 | 7.6% | MARKET_LEADER | bull |
| BLD | $-23,061 | 2023-03-31 to 2023-04-28 | 2 | 20.0% | MARKET_LEADER | neutral |
| TMUS | $-16,423 | 2022-09-30 to 2022-10-31 | 2 | 10.5% | MARKET_LEADER | bear |
| MA | $-15,132 | 2022-01-31 to 2023-01-31 | 6 | 11.4% | QUALITY_COMPOUNDER | neutral |
| FANG | $-14,835 | 2022-06-30 to 2022-07-29 | 2 | 10.5% | QUALITY_COMPOUNDER | bear |
| ORLY | $-14,611 | 2022-11-30 to 2022-12-30 | 2 | 9.9% | QUALITY_COMPOUNDER | bear |
| STLD | $-11,962 | 2022-04-29 to 2022-05-31 | 2 | 6.2% | MARKET_LEADER | bear |
| MLI | $-11,808 | 2023-02-28 to 2023-03-31 | 2 | 10.7% | MARKET_LEADER | bull |
| XPO | $-11,101 | 2023-06-30 to 2023-07-31 | 2 | 20.0% | MARKET_LEADER | bull |

## Findings (machine-readable in findings.json)

### [MEDIUM] `F3_target_exit_losers_deeper_than_rebalance_concentrated`

**Evidence**: target_exit losers average $-1,437 loss over 131 trades, while target_rebalance losers average $-1,118 over 46 trades. Explicit exits are firing too late.

**Candidate fix**: Tighten the leader-rescue / stale-trim threshold so a position is exit-flagged earlier in its decline. Inspect tools/run_lifecycle_review_overlay.py and the stale_mega_leader_score weighting in r1000_main_v2.py.

### [MEDIUM] `F8_mdd_target_book_feature_bucket_concentrated_weak_confirmation_weighted`

**Evidence**: Operating target-book rows linked to MDD losers show bucket `weak_confirmation_weighted` with $-174,385 linked position P&L (74% of top context loss), 16 tickers, avg weight 10.6%, max weight 27.0%. Top tickers: NVDA, BLD, TMUS, MA, FANG, ORLY, STLD, MLI, XPO, LOPE, NET, RKLB.

**Candidate fix**: Use the emitted mdd_policy_bucket_summary.csv and mdd_target_rows.csv to design one narrow PIT-safe entry/hold sizing rule. Do not promote the bucket itself; validate any rule through broker-ledger fast replay.

Research-only analysis. Production decisions still require broker-ledger and human review.
