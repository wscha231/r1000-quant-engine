# Trade Attribution Report - concentrated

- Generated: 2026-06-21T22:53:56.386883+00:00
- Schema: `trade-attribution-findings-v1`
- Analysis mode: `round_trip_journal`

## Broker-Ledger Headline

- CAGR: 44.60%
- Sharpe: 1.395
- MaxDD: -24.62%
- Trade count: 591

## Win/Loss Distribution

- Round trips: 392
- Win rate: 54.8%
- Avg winner: $4,779
- Avg loser: $-1,338
- Total winners P&L: $1,027,467
- Total losers P&L: $-236,800

## MDD Window

- Peak: 2021-11-18, $227,264
- Trough: 2023-08-17, $171,306
- Drawdown: -24.62%
- Trades exited inside window: 92 (total P&L $-25,246)

## Broker Trades In MDD Window

- Executions: 143
- Buys / sells: 69 / 74
- Gross traded: $1,640,828
- Net cash delta: $-9,536

## Top Position P&L Contributors

| Ticker | P&L | Avg weight | Max weight | Days held |
| --- | ---: | ---: | ---: | ---: |
| DDOG | $-43,107 | 7.4% | 21.9% | 29 |
| NVDA | $-30,209 | 5.5% | 7.9% | 42 |
| BLD | $-23,268 | 13.4% | 21.7% | 41 |
| ORLY | $-15,210 | 5.9% | 10.2% | 41 |
| STLD | $-13,318 | 1.6% | 2.3% | 42 |
| MA | $-12,457 | 4.6% | 10.7% | 123 |
| MLI | $-11,951 | 7.4% | 10.8% | 42 |
| XPO | $-11,121 | 18.3% | 23.0% | 33 |
| NET | $-8,674 | 26.8% | 27.8% | 7 |
| TMUS | $-5,036 | 2.3% | 4.1% | 42 |

## MDD Target-Book Feature Buckets

| Bucket | Linked P&L | Tickers | Avg weight | Max weight | Top tickers |
| --- | ---: | ---: | ---: | ---: | --- |
| weak_confirmation_weighted | $-130,841 | 13 | 10.7% | 26.7% | NVDA, BLD, ORLY, MA, MLI, XPO, NET, WCC |
| information_technology_loss_cluster | $-90,875 | 7 | 12.0% | 28.5% | DDOG, NVDA, NET, ON, ONTO, JBL, MSI |
| high_weight_market_leader | $-76,376 | 10 | 15.5% | 28.5% | DDOG, XPO, NET, ON, DXCM, ONTO, JBL, TSLA |
| negative_short_rs_weighted | $-71,601 | 6 | 9.3% | 20.0% | NVDA, BLD, ORLY, JBL, TXRH, CHE |
| qqq_underperforms_spy_weighted | $-70,224 | 10 | 11.7% | 28.5% | BLD, ORLY, MA, XPO, LOPE, JBL, MSI, TXRH |
| high_vol_weighted | $-3,704 | 2 | 9.5% | 11.4% | RKLB, TXRH |

## MDD Target-Book Context By Ticker

| Ticker | Linked P&L | Date range | Rows | Max weight | Lane | Regime |
| --- | ---: | --- | ---: | ---: | --- | --- |
| DDOG | $-43,107 | 2021-10-29 to 2021-11-30 | 2 | 19.4% | MARKET_LEADER | neutral |
| NVDA | $-30,209 | 2021-11-30 to 2021-12-31 | 2 | 7.6% | MARKET_LEADER | bull |
| BLD | $-23,268 | 2023-03-31 to 2023-04-28 | 2 | 20.0% | MARKET_LEADER | neutral |
| ORLY | $-15,210 | 2022-11-30 to 2022-12-30 | 2 | 9.9% | QUALITY_COMPOUNDER | bear |
| STLD | $-13,318 | 2022-04-29 to 2022-05-31 | 2 | 2.2% | MARKET_LEADER | bear |
| MA | $-12,457 | 2022-01-31 to 2023-01-31 | 6 | 10.6% | QUALITY_COMPOUNDER | neutral |
| MLI | $-11,951 | 2023-02-28 to 2023-03-31 | 2 | 10.7% | MARKET_LEADER | bull |
| XPO | $-11,121 | 2023-06-30 to 2023-07-31 | 2 | 20.0% | MARKET_LEADER | bull |
| NET | $-8,674 | 2021-10-29 to 2021-10-29 | 1 | 26.7% | MARKET_LEADER | bull |
| TMUS | $-5,036 | 2022-09-30 to 2022-10-31 | 2 | 3.8% | MARKET_LEADER | bear |

## Findings (machine-readable in findings.json)

### [MEDIUM] `F3_target_exit_losers_deeper_than_rebalance_concentrated`

**Evidence**: target_exit losers average $-1,418 loss over 129 trades, while target_rebalance losers average $-1,123 over 48 trades. Explicit exits are firing too late.

**Candidate fix**: Tighten the leader-rescue / stale-trim threshold so a position is exit-flagged earlier in its decline. Inspect tools/run_lifecycle_review_overlay.py and the stale_mega_leader_score weighting in r1000_main_v2.py.

### [MEDIUM] `F8_mdd_target_book_feature_bucket_concentrated_weak_confirmation_weighted`

**Evidence**: Operating target-book rows linked to MDD losers show bucket `weak_confirmation_weighted` with $-130,841 linked position P&L (63% of top context loss), 13 tickers, avg weight 10.7%, max weight 26.7%. Top tickers: NVDA, BLD, ORLY, MA, MLI, XPO, NET, WCC, LOPE, DXCM, RKLB, ONTO.

**Candidate fix**: Use the emitted mdd_policy_bucket_summary.csv and mdd_target_rows.csv to design one narrow PIT-safe entry/hold sizing rule. Do not promote the bucket itself; validate any rule through broker-ledger fast replay.

Research-only analysis. Production decisions still require broker-ledger and human review.
