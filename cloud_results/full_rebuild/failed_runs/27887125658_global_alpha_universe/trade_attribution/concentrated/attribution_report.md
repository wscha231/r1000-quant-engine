# Trade Attribution Report - concentrated

- Generated: 2026-06-21T03:12:28.444382+00:00
- Schema: `trade-attribution-findings-v1`
- Analysis mode: `round_trip_journal`

## Broker-Ledger Headline

- CAGR: 44.37%
- Sharpe: 1.399
- MaxDD: -24.70%
- Trade count: 589

## Win/Loss Distribution

- Round trips: 390
- Win rate: 54.6%
- Avg winner: $4,763
- Avg loser: $-1,321
- Total winners P&L: $1,014,432
- Total losers P&L: $-233,802

## MDD Window

- Peak: 2021-09-03, $226,149
- Trough: 2023-08-17, $170,280
- Drawdown: -24.70%
- Trades exited inside window: 100 (total P&L $-26,800)

## Broker Trades In MDD Window

- Executions: 155
- Buys / sells: 74 / 81
- Gross traded: $1,906,100
- Net cash delta: $12,254

## Top Position P&L Contributors

| Ticker | P&L | Avg weight | Max weight | Days held |
| --- | ---: | ---: | ---: | ---: |
| BILL | $-60,996 | 16.2% | 31.4% | 39 |
| DDOG | $-31,853 | 14.8% | 22.3% | 82 |
| NVDA | $-30,292 | 5.6% | 7.9% | 42 |
| BLD | $-23,064 | 13.5% | 21.7% | 41 |
| TSLA | $-18,079 | 7.4% | 8.1% | 43 |
| ORLY | $-15,135 | 5.8% | 10.1% | 41 |
| STLD | $-13,262 | 1.6% | 2.3% | 42 |
| DXCM | $-12,596 | 12.9% | 17.1% | 42 |
| MA | $-12,457 | 4.7% | 11.0% | 123 |
| MLI | $-11,742 | 7.4% | 10.8% | 42 |

## MDD Target-Book Feature Buckets

| Bucket | Linked P&L | Tickers | Avg weight | Max weight | Top tickers |
| --- | ---: | ---: | ---: | ---: | --- |
| weak_confirmation_weighted | $-257,503 | 17 | 12.6% | 30.0% | BILL, DDOG, NVDA, BLD, TSLA, ORLY, DXCM, MA |
| high_weight_market_leader | $-167,237 | 13 | 17.0% | 30.0% | BILL, DDOG, TSLA, DXCM, XPO, NTLA, MRNA, ON |
| information_technology_loss_cluster | $-132,778 | 8 | 13.1% | 30.0% | BILL, DDOG, NVDA, ON, ONTO, NET, MSI, JBL |
| qqq_underperforms_spy_weighted | $-123,906 | 13 | 12.1% | 28.5% | DDOG, BLD, ORLY, DXCM, MA, XPO, MRNA, LOPE |
| negative_short_rs_weighted | $-70,366 | 6 | 9.3% | 20.0% | NVDA, BLD, ORLY, TXRH, JBL, CHE |
| high_vol_weighted | $-16,440 | 4 | 12.4% | 28.5% | MRNA, RKLB, DKS, TXRH |
| below_ma50_weighted | $-10,372 | 1 | 7.6% | 7.6% | MRNA |

## MDD Target-Book Context By Ticker

| Ticker | Linked P&L | Date range | Rows | Max weight | Lane | Regime |
| --- | ---: | --- | ---: | ---: | --- | --- |
| BILL | $-60,996 | 2021-08-31 to 2021-09-30 | 2 | 30.0% | MARKET_LEADER | neutral |
| DDOG | $-31,853 | 2021-08-31 to 2021-11-30 | 4 | 19.2% | MARKET_LEADER | neutral |
| NVDA | $-30,292 | 2021-11-30 to 2021-12-31 | 2 | 7.6% | MARKET_LEADER | bull |
| BLD | $-23,064 | 2023-03-31 to 2023-04-28 | 2 | 20.0% | MARKET_LEADER | neutral |
| TSLA | $-18,079 | 2021-10-29 to 2021-11-30 | 2 | 8.0% | MARKET_LEADER | neutral |
| ORLY | $-15,135 | 2022-11-30 to 2022-12-30 | 2 | 9.8% | QUALITY_COMPOUNDER | bear |
| STLD | $-13,262 | 2022-04-29 to 2022-05-31 | 2 | 2.2% | MARKET_LEADER | bear |
| DXCM | $-12,596 | 2021-07-30 to 2021-10-29 | 3 | 15.9% | MARKET_LEADER | bull |
| MA | $-12,457 | 2022-01-31 to 2023-01-31 | 6 | 10.9% | QUALITY_COMPOUNDER | neutral |
| MLI | $-11,742 | 2023-02-28 to 2023-03-31 | 2 | 10.7% | MARKET_LEADER | bull |

## Findings (machine-readable in findings.json)

### [MEDIUM] `F3_target_exit_losers_deeper_than_rebalance_concentrated`

**Evidence**: target_exit losers average $-1,389 loss over 130 trades, while target_rebalance losers average $-1,133 over 47 trades. Explicit exits are firing too late.

**Candidate fix**: Tighten the leader-rescue / stale-trim threshold so a position is exit-flagged earlier in its decline. Inspect tools/run_lifecycle_review_overlay.py and the stale_mega_leader_score weighting in r1000_main_v2.py.

### [MEDIUM] `F8_mdd_target_book_feature_bucket_concentrated_weak_confirmation_weighted`

**Evidence**: Operating target-book rows linked to MDD losers show bucket `weak_confirmation_weighted` with $-257,503 linked position P&L (87% of top context loss), 17 tickers, avg weight 12.6%, max weight 30.0%. Top tickers: BILL, DDOG, NVDA, BLD, TSLA, ORLY, DXCM, MA, MLI, XPO, MRNA, WCC.

**Candidate fix**: Use the emitted mdd_policy_bucket_summary.csv and mdd_target_rows.csv to design one narrow PIT-safe entry/hold sizing rule. Do not promote the bucket itself; validate any rule through broker-ledger fast replay.

Research-only analysis. Production decisions still require broker-ledger and human review.
