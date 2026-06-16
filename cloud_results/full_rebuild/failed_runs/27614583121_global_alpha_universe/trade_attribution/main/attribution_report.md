# Trade Attribution Report - main

- Generated: 2026-06-16T15:48:53.816399+00:00
- Schema: `trade-attribution-findings-v1`
- Analysis mode: `round_trip_journal`

## Broker-Ledger Headline

- CAGR: 35.01%
- Sharpe: 1.291
- MaxDD: -26.05%
- Trade count: 1680

## Win/Loss Distribution

- Round trips: 1138
- Win rate: 58.4%
- Avg winner: $1,231
- Avg loser: $-710
- Total winners P&L: $818,546
- Total losers P&L: $-336,036

## MDD Window

- Peak: 2020-02-19, $134,830
- Trough: 2020-03-18, $99,706
- Drawdown: -26.05%
- Trades exited inside window: 15 (total P&L $-2,229)

## Broker Trades In MDD Window

- Executions: 17
- Buys / sells: 4 / 13
- Gross traded: $59,646
- Net cash delta: $42,271

## Top Position P&L Contributors

| Ticker | P&L | Avg weight | Max weight | Days held |
| --- | ---: | ---: | ---: | ---: |
| AMD | $-11,549 | 8.5% | 13.1% | 20 |
| NOW | $-8,261 | 8.5% | 11.9% | 20 |
| PENN | $-7,887 | 3.6% | 6.7% | 20 |
| STM | $-6,064 | 3.3% | 5.7% | 20 |
| DAR | $-5,749 | 3.2% | 5.6% | 20 |
| PCTY | $-5,391 | 3.2% | 5.3% | 20 |
| TSLA | $-5,269 | 4.7% | 6.1% | 20 |
| SHOP | $-5,223 | 4.0% | 5.9% | 20 |
| DXCM | $-4,827 | 5.1% | 7.0% | 20 |
| QRVO | $-4,627 | 3.2% | 5.4% | 20 |

## MDD Target-Book Feature Buckets

| Bucket | Linked P&L | Tickers | Avg weight | Max weight | Top tickers |
| --- | ---: | ---: | ---: | ---: | --- |
| information_technology_loss_cluster | $-27,338 | 5 | 7.1% | 12.0% | AMD, NOW, QRVO, RNG, UI |
| negative_short_rs_weighted | $-22,386 | 4 | 5.8% | 6.5% | AMD, DAR, QRVO, UI |
| weak_confirmation_weighted | $-22,251 | 3 | 8.9% | 12.0% | AMD, NOW, RNG |
| high_weight_market_leader | $-19,810 | 2 | 12.0% | 12.0% | AMD, NOW |
| below_ma50_weighted | $-16,636 | 3 | 5.9% | 6.5% | AMD, QRVO, UI |
| high_vol_weighted | $-11,549 | 1 | 6.5% | 6.5% | AMD |

## MDD Target-Book Context By Ticker

| Ticker | Linked P&L | Date range | Rows | Max weight | Lane | Regime |
| --- | ---: | --- | ---: | ---: | --- | --- |
| AMD | $-11,549 | 2020-01-31 to 2020-02-28 | 2 | 12.0% | MARKET_LEADER | bear |
| NOW | $-8,261 | 2020-01-31 to 2020-02-28 | 2 | 12.0% | MARKET_LEADER | bear |
| PENN | $-7,887 | 2020-01-31 to 2020-02-28 | 2 | 5.6% | MARKET_LEADER | bear |
| STM | $-6,064 | 2020-01-31 to 2020-02-28 | 2 | 5.6% | MARKET_LEADER | bear |
| DAR | $-5,749 | 2020-01-31 to 2020-02-28 | 2 | 5.6% | MARKET_LEADER | bear |
| PCTY | $-5,391 | 2020-01-31 to 2020-02-28 | 2 | 5.6% | MARKET_LEADER | bear |
| TSLA | $-5,269 | 2020-01-31 to 2020-02-28 | 2 | 5.6% | MARKET_LEADER | bear |
| SHOP | $-5,223 | 2020-01-31 to 2020-02-28 | 2 | 5.6% | MARKET_LEADER | bear |
| DXCM | $-4,827 | 2020-01-31 to 2020-02-28 | 2 | 5.6% | MARKET_LEADER | bear |
| QRVO | $-4,627 | 2020-01-31 to 2020-02-28 | 2 | 5.6% | MARKET_LEADER | bear |

## Findings (machine-readable in findings.json)

### [HIGH] `F1_mdd_dominated_by_unrealized_holdings_main`

**Evidence**: MDD window 2020-02-19 to 2020-03-18 (-26.05% drawdown, equity loss $35,124) had only 15 round-trip exits totaling $-2,229 P&L. The drawdown is therefore dominated by unrealized loss on still-held positions (realized share 6.3%).

**Candidate fix**: Add a portfolio-level drawdown circuit breaker: when running DD exceeds 10% within 5 trading days, force trim each position by 50% at next close. Re-entry permitted only after equity recovers to within 5% of prior peak. Implementation point: extend tools/run_broker_position_risk_replay.py or wire into operating_main/concentrated_target_book builder.

### [MEDIUM] `F2_loss_concentration_in_neutral_regime_main`

**Evidence**: 55% of total realized losses ($-185,581 of $-336,036) occurred in neutral regime, across 248 trades (avg $-748). The engine over-allocates or over-trades in this regime.

**Candidate fix**: Reduce capacity_for_regime['neutral'] in the operating book builder by 20-30%, or tighten entry quality threshold (e.g. raise min_score_quantile) for neutral signal dates. Re-measure F2 share on next broker-ledger replay.

### [MEDIUM] `F3_target_exit_losers_deeper_than_rebalance_main`

**Evidence**: target_exit losers average $-795 loss over 358 trades, while target_rebalance losers average $-446 over 115 trades. Explicit exits are firing too late.

**Candidate fix**: Tighten the leader-rescue / stale-trim threshold so a position is exit-flagged earlier in its decline. Inspect tools/run_lifecycle_review_overlay.py and the stale_mega_leader_score weighting in r1000_main_v2.py.

### [MEDIUM] `F8_mdd_target_book_feature_bucket_main_information_technology_loss_cluster`

**Evidence**: Operating target-book rows linked to MDD losers show bucket `information_technology_loss_cluster` with $-27,338 linked position P&L (36% of top context loss), 5 tickers, avg weight 7.1%, max weight 12.0%. Top tickers: AMD, NOW, QRVO, RNG, UI.

**Candidate fix**: Use the emitted mdd_policy_bucket_summary.csv and mdd_target_rows.csv to design one narrow PIT-safe entry/hold sizing rule. Do not promote the bucket itself; validate any rule through broker-ledger fast replay.

Research-only analysis. Production decisions still require broker-ledger and human review.
