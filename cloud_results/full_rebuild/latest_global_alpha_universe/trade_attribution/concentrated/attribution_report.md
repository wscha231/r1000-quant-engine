# Trade Attribution Report - concentrated

- Generated: 2026-06-19T12:31:54.188746+00:00
- Schema: `trade-attribution-findings-v1`
- Analysis mode: `round_trip_journal`

## Broker-Ledger Headline

- CAGR: 50.62%
- Sharpe: 1.518
- MaxDD: -23.83%
- Trade count: 519

## Win/Loss Distribution

- Round trips: 343
- Win rate: 54.8%
- Avg winner: $5,413
- Avg loser: $-1,328
- Total winners P&L: $1,017,621
- Total losers P&L: $-205,821

## MDD Window

- Peak: 2021-11-18, $217,540
- Trough: 2023-08-17, $165,704
- Drawdown: -23.83%
- Trades exited inside window: 93 (total P&L $-22,546)

## Broker Trades In MDD Window

- Executions: 142
- Buys / sells: 69 / 73
- Gross traded: $1,577,572
- Net cash delta: $-8,956

## Top Position P&L Contributors

| Ticker | P&L | Avg weight | Max weight | Days held |
| --- | ---: | ---: | ---: | ---: |
| DDOG | $-41,201 | 7.6% | 21.9% | 29 |
| BLD | $-22,445 | 13.4% | 21.6% | 41 |
| NVDA | $-20,868 | 7.4% | 7.9% | 22 |
| ORLY | $-15,148 | 6.0% | 10.5% | 41 |
| STLD | $-12,722 | 1.9% | 3.1% | 42 |
| MA | $-12,041 | 4.6% | 10.9% | 123 |
| MLI | $-11,278 | 7.4% | 10.7% | 42 |
| XPO | $-10,614 | 18.3% | 23.1% | 33 |
| AMD | $-8,637 | 5.6% | 7.9% | 42 |
| NET | $-8,210 | 26.5% | 27.5% | 7 |

## MDD Target-Book Feature Buckets

| Bucket | Linked P&L | Tickers | Avg weight | Max weight | Top tickers |
| --- | ---: | ---: | ---: | ---: | --- |
| weak_confirmation_weighted | $-126,183 | 14 | 10.6% | 26.3% | BLD, NVDA, ORLY, MA, MLI, XPO, AMD, NET |
| information_technology_loss_cluster | $-84,058 | 7 | 11.6% | 28.5% | DDOG, NVDA, AMD, NET, ONTO, JBL, MSI |
| high_weight_market_leader | $-69,588 | 9 | 15.9% | 28.5% | DDOG, XPO, NET, DXCM, ONTO, JBL, TSLA, PCTY |
| qqq_underperforms_spy_weighted | $-67,993 | 10 | 11.8% | 28.5% | BLD, ORLY, MA, XPO, LOPE, JBL, MSI, TXRH |
| negative_short_rs_weighted | $-49,268 | 6 | 9.3% | 20.0% | BLD, ORLY, AMD, JBL, TXRH, CHE |
| high_vol_weighted | $-3,557 | 2 | 9.5% | 11.4% | RKLB, TXRH |

## MDD Target-Book Context By Ticker

| Ticker | Linked P&L | Date range | Rows | Max weight | Lane | Regime |
| --- | ---: | --- | ---: | ---: | --- | --- |
| DDOG | $-41,201 | 2021-10-29 to 2021-11-30 | 2 | 19.6% | MARKET_LEADER | neutral |
| BLD | $-22,445 | 2023-03-31 to 2023-04-28 | 2 | 20.0% | MARKET_LEADER | neutral |
| NVDA | $-20,868 | 2021-11-30 to 2021-11-30 | 1 | 7.6% | MARKET_LEADER | neutral |
| ORLY | $-15,148 | 2022-11-30 to 2022-12-30 | 2 | 10.2% | QUALITY_COMPOUNDER | bear |
| STLD | $-12,722 | 2022-04-29 to 2022-05-31 | 2 | 3.0% | MARKET_LEADER | bear |
| MA | $-12,041 | 2022-01-31 to 2023-01-31 | 6 | 10.8% | QUALITY_COMPOUNDER | neutral |
| MLI | $-11,278 | 2023-02-28 to 2023-03-31 | 2 | 10.6% | MARKET_LEADER | bull |
| XPO | $-10,614 | 2023-06-30 to 2023-07-31 | 2 | 20.0% | MARKET_LEADER | bull |
| AMD | $-8,637 | 2021-11-30 to 2021-12-31 | 2 | 7.6% | MARKET_LEADER | bull |
| NET | $-8,210 | 2021-10-29 to 2021-10-29 | 1 | 26.3% | MARKET_LEADER | bull |

## Findings (machine-readable in findings.json)

### [MEDIUM] `F8_mdd_target_book_feature_bucket_concentrated_weak_confirmation_weighted`

**Evidence**: Operating target-book rows linked to MDD losers show bucket `weak_confirmation_weighted` with $-126,183 linked position P&L (64% of top context loss), 14 tickers, avg weight 10.6%, max weight 26.3%. Top tickers: BLD, NVDA, ORLY, MA, MLI, XPO, AMD, NET, WCC, LOPE, DXCM, RKLB.

**Candidate fix**: Use the emitted mdd_policy_bucket_summary.csv and mdd_target_rows.csv to design one narrow PIT-safe entry/hold sizing rule. Do not promote the bucket itself; validate any rule through broker-ledger fast replay.

Research-only analysis. Production decisions still require broker-ledger and human review.
