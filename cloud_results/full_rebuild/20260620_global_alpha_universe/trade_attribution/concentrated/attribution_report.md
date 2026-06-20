# Trade Attribution Report - concentrated

- Generated: 2026-06-20T17:53:39.692167+00:00
- Schema: `trade-attribution-findings-v1`
- Analysis mode: `round_trip_journal`

## Broker-Ledger Headline

- CAGR: 45.47%
- Sharpe: 1.412
- MaxDD: -24.59%
- Trade count: 589

## Win/Loss Distribution

- Round trips: 390
- Win rate: 54.9%
- Avg winner: $4,977
- Avg loser: $-1,342
- Total winners P&L: $1,064,990
- Total losers P&L: $-236,120

## MDD Window

- Peak: 2021-11-18, $224,968
- Trough: 2023-08-17, $169,658
- Drawdown: -24.59%
- Trades exited inside window: 91 (total P&L $-24,842)

## Broker Trades In MDD Window

- Executions: 142
- Buys / sells: 69 / 73
- Gross traded: $1,626,816
- Net cash delta: $-9,618

## Top Position P&L Contributors

| Ticker | P&L | Avg weight | Max weight | Days held |
| --- | ---: | ---: | ---: | ---: |
| DDOG | $-42,725 | 7.5% | 21.9% | 29 |
| NVDA | $-29,850 | 5.6% | 7.9% | 42 |
| BLD | $-23,061 | 13.4% | 21.6% | 41 |
| ORLY | $-15,038 | 5.9% | 10.2% | 41 |
| STLD | $-13,151 | 1.9% | 3.2% | 42 |
| MA | $-12,457 | 4.6% | 10.6% | 123 |
| MLI | $-11,844 | 7.4% | 10.8% | 42 |
| XPO | $-11,041 | 18.3% | 23.0% | 33 |
| NET | $-8,587 | 26.8% | 27.8% | 7 |
| TMUS | $-4,903 | 2.3% | 4.0% | 42 |

## MDD Target-Book Feature Buckets

| Bucket | Linked P&L | Tickers | Avg weight | Max weight | Top tickers |
| --- | ---: | ---: | ---: | ---: | --- |
| weak_confirmation_weighted | $-129,269 | 13 | 10.7% | 26.7% | NVDA, BLD, ORLY, MA, MLI, XPO, NET, WCC |
| information_technology_loss_cluster | $-89,919 | 7 | 12.0% | 28.5% | DDOG, NVDA, NET, ON, ONTO, JBL, MSI |
| high_weight_market_leader | $-75,289 | 10 | 15.5% | 28.5% | DDOG, XPO, NET, ON, DXCM, ONTO, JBL, PCTY |
| negative_short_rs_weighted | $-70,802 | 6 | 9.3% | 20.0% | NVDA, BLD, ORLY, JBL, TXRH, CHE |
| qqq_underperforms_spy_weighted | $-69,593 | 10 | 11.7% | 28.5% | BLD, ORLY, MA, XPO, LOPE, JBL, MSI, TXRH |
| high_vol_weighted | $-3,666 | 2 | 9.5% | 11.4% | RKLB, TXRH |

## MDD Target-Book Context By Ticker

| Ticker | Linked P&L | Date range | Rows | Max weight | Lane | Regime |
| --- | ---: | --- | ---: | ---: | --- | --- |
| DDOG | $-42,725 | 2021-10-29 to 2021-11-30 | 2 | 19.5% | MARKET_LEADER | neutral |
| NVDA | $-29,850 | 2021-11-30 to 2021-12-31 | 2 | 7.6% | MARKET_LEADER | bull |
| BLD | $-23,061 | 2023-03-31 to 2023-04-28 | 2 | 20.0% | MARKET_LEADER | neutral |
| ORLY | $-15,038 | 2022-11-30 to 2022-12-30 | 2 | 9.9% | QUALITY_COMPOUNDER | bear |
| STLD | $-13,151 | 2022-04-29 to 2022-05-31 | 2 | 3.0% | MARKET_LEADER | bear |
| MA | $-12,457 | 2022-01-31 to 2023-01-31 | 6 | 10.6% | QUALITY_COMPOUNDER | neutral |
| MLI | $-11,844 | 2023-02-28 to 2023-03-31 | 2 | 10.7% | MARKET_LEADER | bull |
| XPO | $-11,041 | 2023-06-30 to 2023-07-31 | 2 | 20.0% | MARKET_LEADER | bull |
| NET | $-8,587 | 2021-10-29 to 2021-10-29 | 1 | 26.7% | MARKET_LEADER | bull |
| TMUS | $-4,903 | 2022-09-30 to 2022-10-31 | 2 | 3.8% | MARKET_LEADER | bear |

## Findings (machine-readable in findings.json)

### [MEDIUM] `F3_target_exit_losers_deeper_than_rebalance_concentrated`

**Evidence**: target_exit losers average $-1,408 loss over 130 trades, while target_rebalance losers average $-1,153 over 46 trades. Explicit exits are firing too late.

**Candidate fix**: Tighten the leader-rescue / stale-trim threshold so a position is exit-flagged earlier in its decline. Inspect tools/run_lifecycle_review_overlay.py and the stale_mega_leader_score weighting in r1000_main_v2.py.

### [MEDIUM] `F8_mdd_target_book_feature_bucket_concentrated_weak_confirmation_weighted`

**Evidence**: Operating target-book rows linked to MDD losers show bucket `weak_confirmation_weighted` with $-129,269 linked position P&L (63% of top context loss), 13 tickers, avg weight 10.7%, max weight 26.7%. Top tickers: NVDA, BLD, ORLY, MA, MLI, XPO, NET, WCC, LOPE, DXCM, RKLB, ONTO.

**Candidate fix**: Use the emitted mdd_policy_bucket_summary.csv and mdd_target_rows.csv to design one narrow PIT-safe entry/hold sizing rule. Do not promote the bucket itself; validate any rule through broker-ledger fast replay.

Research-only analysis. Production decisions still require broker-ledger and human review.
