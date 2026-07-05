# Trade Attribution Report - concentrated

- Generated: 2026-07-05T04:30:11.462308+00:00
- Schema: `trade-attribution-findings-v1`
- Analysis mode: `round_trip_journal`

## Broker-Ledger Headline

- CAGR: 46.99%
- Sharpe: 1.455
- MaxDD: -23.22%
- Trade count: 724

## Win/Loss Distribution

- Round trips: 449
- Win rate: 58.8%
- Avg winner: $6,298
- Avg loser: $-1,941
- Total winners P&L: $1,662,727
- Total losers P&L: $-359,096

## MDD Window

- Peak: 2025-02-18, $499,027
- Trough: 2025-04-08, $383,138
- Drawdown: -23.22%
- Trades exited inside window: 12 (total P&L $2,519)

## Broker Trades In MDD Window

- Executions: 19
- Buys / sells: 8 / 11
- Gross traded: $550,756
- Net cash delta: $204,460

## Top Position P&L Contributors

| Ticker | P&L | Avg weight | Max weight | Days held |
| --- | ---: | ---: | ---: | ---: |
| PLTR | $-57,128 | 31.5% | 33.6% | 8 |
| TPR | $-29,236 | 5.4% | 7.6% | 27 |
| BROS | $-25,387 | 5.4% | 7.6% | 27 |
| APP | $-22,304 | 11.8% | 13.5% | 8 |
| UBER | $-13,819 | 5.0% | 5.3% | 6 |
| CORT | $-5,794 | 7.1% | 7.4% | 8 |
| HUBS | $-3,889 | 8.3% | 8.7% | 8 |
| LI | $-2,413 | 7.7% | 8.4% | 21 |
| GOOGL | $-2,053 | 6.2% | 6.4% | 8 |
| KVUE | $-1,741 | 4.3% | 4.5% | 6 |

## MDD Target-Book Feature Buckets

| Bucket | Linked P&L | Tickers | Avg weight | Max weight | Top tickers |
| --- | ---: | ---: | ---: | ---: | --- |
| qqq_underperforms_spy_weighted | $-146,151 | 7 | 11.3% | 28.5% | PLTR, TPR, BROS, APP, CORT, HUBS, LI |
| high_weight_market_leader | $-83,321 | 3 | 16.3% | 28.5% | PLTR, APP, HUBS |
| information_technology_loss_cluster | $-83,321 | 3 | 16.3% | 28.5% | PLTR, APP, HUBS |
| weak_confirmation_weighted | $-66,719 | 5 | 7.9% | 8.9% | TPR, BROS, CORT, HUBS, LI |
| high_vol_weighted | $-25,387 | 1 | 7.6% | 7.6% | BROS |
| negative_short_rs_weighted | $-13,819 | 1 | 5.2% | 5.2% | UBER |
| below_ma50_weighted | $-13,819 | 1 | 5.2% | 5.2% | UBER |

## MDD Target-Book Context By Ticker

| Ticker | Linked P&L | Date range | Rows | Max weight | Lane | Regime |
| --- | ---: | --- | ---: | ---: | --- | --- |
| PLTR | $-57,128 | 2025-01-31 to 2025-01-31 | 1 | 28.5% | MARKET_LEADER | neutral |
| TPR | $-29,236 | 2025-02-28 to 2025-03-31 | 2 | 7.6% | MARKET_LEADER | bear |
| BROS | $-25,387 | 2025-02-28 to 2025-03-31 | 2 | 7.6% | MARKET_LEADER | bear |
| APP | $-22,304 | 2025-01-31 to 2025-01-31 | 1 | 11.4% | MARKET_LEADER | neutral |
| UBER | $-13,819 | 2025-03-31 to 2025-03-31 | 1 | 5.2% | QUALITY_COMPOUNDER | bear |
| CORT | $-5,794 | 2025-01-31 to 2025-01-31 | 1 | 7.6% | MARKET_LEADER | neutral |
| HUBS | $-3,889 | 2025-01-31 to 2025-01-31 | 1 | 8.9% | MARKET_LEADER | neutral |
| LI | $-2,413 | 2025-02-28 to 2025-02-28 | 1 | 7.6% | MARKET_LEADER | neutral |
| GOOGL | $-2,053 | 2025-01-31 to 2025-01-31 | 1 | 7.3% | MARKET_LEADER | neutral |
| KVUE | $-1,741 | 2025-03-31 to 2025-03-31 | 1 | 4.5% | QUALITY_COMPOUNDER | bear |

## Findings (machine-readable in findings.json)

### [HIGH] `F1_mdd_dominated_by_unrealized_holdings_concentrated`

**Evidence**: MDD window 2025-02-18 to 2025-04-08 (-23.22% drawdown, equity loss $115,889) had only 12 round-trip exits totaling $2,519 P&L. The drawdown is therefore dominated by unrealized loss on still-held positions (realized share 2.2%).

**Candidate fix**: Add a portfolio-level drawdown circuit breaker: when running DD exceeds 10% within 5 trading days, force trim each position by 50% at next close. Re-entry permitted only after equity recovers to within 5% of prior peak. Implementation point: extend tools/run_broker_position_risk_replay.py or wire into operating_main/concentrated_target_book builder.

### [MEDIUM] `F2_loss_concentration_in_neutral_regime_concentrated`

**Evidence**: 56% of total realized losses ($-199,548 of $-359,096) occurred in neutral regime, across 101 trades (avg $-1,976). The engine over-allocates or over-trades in this regime.

**Candidate fix**: Reduce capacity_for_regime['neutral'] in the operating book builder by 20-30%, or tighten entry quality threshold (e.g. raise min_score_quantile) for neutral signal dates. Re-measure F2 share on next broker-ledger replay.

### [MEDIUM] `F8_mdd_target_book_feature_bucket_concentrated_qqq_underperforms_spy_weighted`

**Evidence**: Operating target-book rows linked to MDD losers show bucket `qqq_underperforms_spy_weighted` with $-146,151 linked position P&L (88% of top context loss), 7 tickers, avg weight 11.3%, max weight 28.5%. Top tickers: PLTR, TPR, BROS, APP, CORT, HUBS, LI.

**Candidate fix**: Use the emitted mdd_policy_bucket_summary.csv and mdd_target_rows.csv to design one narrow PIT-safe entry/hold sizing rule. Do not promote the bucket itself; validate any rule through broker-ledger fast replay.

Research-only analysis. Production decisions still require broker-ledger and human review.
