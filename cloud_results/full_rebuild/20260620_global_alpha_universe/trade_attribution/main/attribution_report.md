# Trade Attribution Report - main

- Generated: 2026-06-20T17:53:39.431304+00:00
- Schema: `trade-attribution-findings-v1`
- Analysis mode: `round_trip_journal`

## Broker-Ledger Headline

- CAGR: 34.73%
- Sharpe: 1.267
- MaxDD: -26.05%
- Trade count: 1657

## Win/Loss Distribution

- Round trips: 1125
- Win rate: 56.9%
- Avg winner: $1,146
- Avg loser: $-640
- Total winners P&L: $733,719
- Total losers P&L: $-310,631

## MDD Window

- Peak: 2020-02-19, $125,085
- Trough: 2020-03-18, $92,497
- Drawdown: -26.05%
- Trades exited inside window: 14 (total P&L $-2,384)

## Broker Trades In MDD Window

- Executions: 16
- Buys / sells: 4 / 12
- Gross traded: $48,228
- Net cash delta: $39,358

## Top Position P&L Contributors

| Ticker | P&L | Avg weight | Max weight | Days held |
| --- | ---: | ---: | ---: | ---: |
| AMD | $-10,253 | 8.9% | 13.2% | 20 |
| PENN | $-7,279 | 3.8% | 6.7% | 20 |
| NOW | $-7,005 | 9.0% | 11.9% | 20 |
| STM | $-6,008 | 2.9% | 5.7% | 20 |
| PCTY | $-5,491 | 2.8% | 5.3% | 20 |
| FTNT | $-5,286 | 2.8% | 5.2% | 20 |
| PAYC | $-5,013 | 2.8% | 5.1% | 20 |
| QRVO | $-4,763 | 2.8% | 5.4% | 20 |
| TSLA | $-4,478 | 5.2% | 6.2% | 20 |
| SHOP | $-4,457 | 4.3% | 5.9% | 20 |

## MDD Target-Book Feature Buckets

| Bucket | Linked P&L | Tickers | Avg weight | Max weight | Top tickers |
| --- | ---: | ---: | ---: | ---: | --- |
| information_technology_loss_cluster | $-29,845 | 6 | 6.5% | 12.0% | AMD, NOW, FTNT, QRVO, RNG, UI |
| weak_confirmation_weighted | $-19,367 | 3 | 9.2% | 12.0% | AMD, NOW, RNG |
| high_weight_market_leader | $-17,259 | 2 | 12.0% | 12.0% | AMD, NOW |
| negative_short_rs_weighted | $-15,445 | 3 | 6.1% | 7.0% | AMD, QRVO, UI |
| below_ma50_weighted | $-15,445 | 3 | 6.1% | 7.0% | AMD, QRVO, UI |
| high_vol_weighted | $-10,253 | 1 | 7.0% | 7.0% | AMD |

## MDD Target-Book Context By Ticker

| Ticker | Linked P&L | Date range | Rows | Max weight | Lane | Regime |
| --- | ---: | --- | ---: | ---: | --- | --- |
| AMD | $-10,253 | 2020-01-31 to 2020-02-28 | 2 | 12.0% | MARKET_LEADER | bear |
| PENN | $-7,279 | 2020-01-31 to 2020-02-28 | 2 | 5.6% | MARKET_LEADER | bear |
| NOW | $-7,005 | 2020-01-31 to 2020-02-28 | 2 | 12.0% | MARKET_LEADER | bear |
| STM | $-6,008 | 2020-01-31 to 2020-02-28 | 2 | 5.6% | MARKET_LEADER | bear |
| PCTY | $-5,491 | 2020-01-31 to 2020-02-28 | 2 | 5.6% | MARKET_LEADER | bear |
| FTNT | $-5,286 | 2020-01-31 to 2020-02-28 | 2 | 5.6% | QUALITY_COMPOUNDER | bear |
| PAYC | $-5,013 | 2020-01-31 to 2020-02-28 | 2 | 5.6% | MARKET_LEADER | bear |
| QRVO | $-4,763 | 2020-01-31 to 2020-02-28 | 2 | 5.6% | MARKET_LEADER | bear |
| TSLA | $-4,478 | 2020-01-31 to 2020-02-28 | 2 | 5.7% | MARKET_LEADER | bear |
| SHOP | $-4,457 | 2020-01-31 to 2020-02-28 | 2 | 5.6% | MARKET_LEADER | bear |

## Findings (machine-readable in findings.json)

### [HIGH] `F1_mdd_dominated_by_unrealized_holdings_main`

**Evidence**: MDD window 2020-02-19 to 2020-03-18 (-26.05% drawdown, equity loss $32,588) had only 14 round-trip exits totaling $-2,384 P&L. The drawdown is therefore dominated by unrealized loss on still-held positions (realized share 7.3%).

**Candidate fix**: Add a portfolio-level drawdown circuit breaker: when running DD exceeds 10% within 5 trading days, force trim each position by 50% at next close. Re-entry permitted only after equity recovers to within 5% of prior peak. Implementation point: extend tools/run_broker_position_risk_replay.py or wire into operating_main/concentrated_target_book builder.

### [MEDIUM] `F2_loss_concentration_in_neutral_regime_main`

**Evidence**: 56% of total realized losses ($-173,878 of $-310,631) occurred in neutral regime, across 257 trades (avg $-677). The engine over-allocates or over-trades in this regime.

**Candidate fix**: Reduce capacity_for_regime['neutral'] in the operating book builder by 20-30%, or tighten entry quality threshold (e.g. raise min_score_quantile) for neutral signal dates. Re-measure F2 share on next broker-ledger replay.

### [MEDIUM] `F3_target_exit_losers_deeper_than_rebalance_main`

**Evidence**: target_exit losers average $-715 loss over 365 trades, while target_rebalance losers average $-414 over 120 trades. Explicit exits are firing too late.

**Candidate fix**: Tighten the leader-rescue / stale-trim threshold so a position is exit-flagged earlier in its decline. Inspect tools/run_lifecycle_review_overlay.py and the stale_mega_leader_score weighting in r1000_main_v2.py.

### [MEDIUM] `F8_mdd_target_book_feature_bucket_main_information_technology_loss_cluster`

**Evidence**: Operating target-book rows linked to MDD losers show bucket `information_technology_loss_cluster` with $-29,845 linked position P&L (41% of top context loss), 6 tickers, avg weight 6.5%, max weight 12.0%. Top tickers: AMD, NOW, FTNT, QRVO, RNG, UI.

**Candidate fix**: Use the emitted mdd_policy_bucket_summary.csv and mdd_target_rows.csv to design one narrow PIT-safe entry/hold sizing rule. Do not promote the bucket itself; validate any rule through broker-ledger fast replay.

Research-only analysis. Production decisions still require broker-ledger and human review.
