# Trade Attribution Report - concentrated

- Generated: 2026-07-02T23:49:29.019767+00:00
- Schema: `trade-attribution-findings-v1`
- Analysis mode: `round_trip_journal`

## Broker-Ledger Headline

- CAGR: 44.53%
- Sharpe: 1.354
- MaxDD: -23.27%
- Trade count: 600

## Win/Loss Distribution

- Round trips: 406
- Win rate: 57.1%
- Avg winner: $6,174
- Avg loser: $-1,684
- Total winners P&L: $1,432,373
- Total losers P&L: $-292,957

## MDD Window

- Peak: 2025-02-18, $455,334
- Trough: 2025-04-08, $349,386
- Drawdown: -23.27%
- Trades exited inside window: 11 (total P&L $-74)

## Broker Trades In MDD Window

- Executions: 16
- Buys / sells: 7 / 9
- Gross traded: $466,433
- Net cash delta: $166,529

## Top Position P&L Contributors

| Ticker | P&L | Avg weight | Max weight | Days held |
| --- | ---: | ---: | ---: | ---: |
| PLTR | $-156,404 | 8.0% | 33.5% | 35 |
| TPR | $-26,305 | 5.4% | 7.6% | 27 |
| BROS | $-22,400 | 5.5% | 7.6% | 27 |
| APP | $-20,091 | 11.8% | 13.5% | 8 |
| UBER | $-10,994 | 5.0% | 5.3% | 6 |
| AXON | $-7,626 | 5.8% | 6.4% | 8 |
| CORT | $-5,217 | 7.1% | 7.4% | 8 |
| HUBS | $-3,492 | 8.3% | 8.7% | 8 |
| LI | $-2,198 | 7.7% | 8.4% | 21 |
| KVUE | $-1,757 | 4.8% | 4.9% | 6 |

## MDD Target-Book Feature Buckets

| Bucket | Linked P&L | Tickers | Avg weight | Max weight | Top tickers |
| --- | ---: | ---: | ---: | ---: | --- |
| qqq_underperforms_spy_weighted | $-243,732 | 8 | 10.8% | 28.5% | PLTR, TPR, BROS, APP, AXON, CORT, HUBS, LI |
| high_weight_market_leader | $-179,987 | 3 | 16.3% | 28.5% | PLTR, APP, HUBS |
| information_technology_loss_cluster | $-179,987 | 3 | 10.3% | 28.5% | PLTR, APP, HUBS |
| weak_confirmation_weighted | $-67,237 | 6 | 7.8% | 9.0% | TPR, BROS, AXON, CORT, HUBS, LI |
| high_vol_weighted | $-22,400 | 1 | 7.6% | 7.6% | BROS |
| negative_short_rs_weighted | $-10,994 | 1 | 5.2% | 5.2% | UBER |
| below_ma50_weighted | $-10,994 | 1 | 5.2% | 5.2% | UBER |

## MDD Target-Book Context By Ticker

| Ticker | Linked P&L | Date range | Rows | Max weight | Lane | Regime |
| --- | ---: | --- | ---: | ---: | --- | --- |
| PLTR | $-156,404 | 2025-01-31 to 2025-03-31 | 3 | 28.5% | MARKET_LEADER | bear |
| TPR | $-26,305 | 2025-02-28 to 2025-03-31 | 2 | 7.6% | MARKET_LEADER | bear |
| BROS | $-22,400 | 2025-02-28 to 2025-03-31 | 2 | 7.6% | MARKET_LEADER | bear |
| APP | $-20,091 | 2025-01-31 to 2025-01-31 | 1 | 11.4% | MARKET_LEADER | neutral |
| UBER | $-10,994 | 2025-03-31 to 2025-03-31 | 1 | 5.2% | QUALITY_COMPOUNDER | bear |
| AXON | $-7,626 | 2025-01-31 to 2025-01-31 | 1 | 7.3% | MARKET_LEADER | neutral |
| CORT | $-5,217 | 2025-01-31 to 2025-01-31 | 1 | 7.6% | MARKET_LEADER | neutral |
| HUBS | $-3,492 | 2025-01-31 to 2025-01-31 | 1 | 9.0% | MARKET_LEADER | neutral |
| LI | $-2,198 | 2025-02-28 to 2025-02-28 | 1 | 7.6% | MARKET_LEADER | neutral |
| KVUE | $-1,757 | 2025-03-31 to 2025-03-31 | 1 | 4.9% | QUALITY_COMPOUNDER | bear |

## Findings (machine-readable in findings.json)

### [HIGH] `F1_mdd_dominated_by_unrealized_holdings_concentrated`

**Evidence**: MDD window 2025-02-18 to 2025-04-08 (-23.27% drawdown, equity loss $105,948) had only 11 round-trip exits totaling $-74 P&L. The drawdown is therefore dominated by unrealized loss on still-held positions (realized share 0.1%).

**Candidate fix**: Add a portfolio-level drawdown circuit breaker: when running DD exceeds 10% within 5 trading days, force trim each position by 50% at next close. Re-entry permitted only after equity recovers to within 5% of prior peak. Implementation point: extend tools/run_broker_position_risk_replay.py or wire into operating_main/concentrated_target_book builder.

### [MEDIUM] `F2_loss_concentration_in_neutral_regime_concentrated`

**Evidence**: 55% of total realized losses ($-161,991 of $-292,957) occurred in neutral regime, across 90 trades (avg $-1,800). The engine over-allocates or over-trades in this regime.

**Candidate fix**: Reduce capacity_for_regime['neutral'] in the operating book builder by 20-30%, or tighten entry quality threshold (e.g. raise min_score_quantile) for neutral signal dates. Re-measure F2 share on next broker-ledger replay.

### [MEDIUM] `F3_target_exit_losers_deeper_than_rebalance_concentrated`

**Evidence**: target_exit losers average $-1,843 loss over 125 trades, while target_rebalance losers average $-1,278 over 49 trades. Explicit exits are firing too late.

**Candidate fix**: Tighten the leader-rescue / stale-trim threshold so a position is exit-flagged earlier in its decline. Inspect tools/run_lifecycle_review_overlay.py and the stale_mega_leader_score weighting in r1000_main_v2.py.

### [MEDIUM] `F8_mdd_target_book_feature_bucket_concentrated_qqq_underperforms_spy_weighted`

**Evidence**: Operating target-book rows linked to MDD losers show bucket `qqq_underperforms_spy_weighted` with $-243,732 linked position P&L (95% of top context loss), 8 tickers, avg weight 10.8%, max weight 28.5%. Top tickers: PLTR, TPR, BROS, APP, AXON, CORT, HUBS, LI.

**Candidate fix**: Use the emitted mdd_policy_bucket_summary.csv and mdd_target_rows.csv to design one narrow PIT-safe entry/hold sizing rule. Do not promote the bucket itself; validate any rule through broker-ledger fast replay.

Research-only analysis. Production decisions still require broker-ledger and human review.
