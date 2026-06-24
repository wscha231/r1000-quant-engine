# Trade Attribution Report - main

- Generated: 2026-06-24T08:08:23.191491+00:00
- Schema: `trade-attribution-findings-v1`
- Analysis mode: `round_trip_journal`

## Broker-Ledger Headline

- CAGR: 33.15%
- Sharpe: 1.219
- MaxDD: -26.02%
- Trade count: 1681

## Win/Loss Distribution

- Round trips: 1140
- Win rate: 57.5%
- Avg winner: $1,131
- Avg loser: $-658
- Total winners P&L: $742,121
- Total losers P&L: $-318,269

## MDD Window

- Peak: 2020-02-19, $126,221
- Trough: 2020-03-18, $93,384
- Drawdown: -26.02%
- Trades exited inside window: 14 (total P&L $-2,391)

## Broker Trades In MDD Window

- Executions: 16
- Buys / sells: 4 / 12
- Gross traded: $48,869
- Net cash delta: $39,634

## Top Position P&L Contributors

| Ticker | P&L | Avg weight | Max weight | Days held |
| --- | ---: | ---: | ---: | ---: |
| AMD | $-10,391 | 8.9% | 13.2% | 20 |
| PENN | $-7,349 | 3.8% | 6.7% | 20 |
| NOW | $-7,093 | 9.0% | 11.9% | 20 |
| STM | $-6,091 | 2.9% | 5.7% | 20 |
| PCTY | $-5,491 | 2.8% | 5.3% | 20 |
| FTNT | $-5,333 | 2.7% | 5.2% | 20 |
| PAYC | $-5,013 | 2.7% | 5.0% | 20 |
| QRVO | $-4,867 | 2.8% | 5.5% | 20 |
| TSLA | $-4,515 | 5.2% | 6.2% | 20 |
| SHOP | $-4,512 | 4.3% | 5.9% | 20 |

## MDD Target-Book Feature Buckets

| Bucket | Linked P&L | Tickers | Avg weight | Max weight | Top tickers |
| --- | ---: | ---: | ---: | ---: | --- |
| information_technology_loss_cluster | $-30,221 | 6 | 6.5% | 12.0% | AMD, NOW, FTNT, QRVO, RNG, UI |
| weak_confirmation_weighted | $-19,592 | 3 | 9.2% | 12.0% | AMD, NOW, RNG |
| high_weight_market_leader | $-17,484 | 2 | 12.0% | 12.0% | AMD, NOW |
| negative_short_rs_weighted | $-15,687 | 3 | 6.1% | 7.0% | AMD, QRVO, UI |
| below_ma50_weighted | $-15,687 | 3 | 6.1% | 7.0% | AMD, QRVO, UI |
| high_vol_weighted | $-10,391 | 1 | 7.0% | 7.0% | AMD |

## MDD Target-Book Context By Ticker

| Ticker | Linked P&L | Date range | Rows | Max weight | Lane | Regime |
| --- | ---: | --- | ---: | ---: | --- | --- |
| AMD | $-10,391 | 2020-01-31 to 2020-02-28 | 2 | 12.0% | MARKET_LEADER | bear |
| PENN | $-7,349 | 2020-01-31 to 2020-02-28 | 2 | 5.6% | MARKET_LEADER | bear |
| NOW | $-7,093 | 2020-01-31 to 2020-02-28 | 2 | 12.0% | MARKET_LEADER | bear |
| STM | $-6,091 | 2020-01-31 to 2020-02-28 | 2 | 5.6% | MARKET_LEADER | bear |
| PCTY | $-5,491 | 2020-01-31 to 2020-02-28 | 2 | 5.6% | MARKET_LEADER | bear |
| FTNT | $-5,333 | 2020-01-31 to 2020-02-28 | 2 | 5.6% | QUALITY_COMPOUNDER | bear |
| PAYC | $-5,013 | 2020-01-31 to 2020-02-28 | 2 | 5.6% | MARKET_LEADER | bear |
| QRVO | $-4,867 | 2020-01-31 to 2020-02-28 | 2 | 5.6% | MARKET_LEADER | bear |
| TSLA | $-4,515 | 2020-01-31 to 2020-02-28 | 2 | 5.7% | MARKET_LEADER | bear |
| SHOP | $-4,512 | 2020-01-31 to 2020-02-28 | 2 | 5.6% | MARKET_LEADER | bear |

## Findings (machine-readable in findings.json)

### [HIGH] `F1_mdd_dominated_by_unrealized_holdings_main`

**Evidence**: MDD window 2020-02-19 to 2020-03-18 (-26.02% drawdown, equity loss $32,837) had only 14 round-trip exits totaling $-2,391 P&L. The drawdown is therefore dominated by unrealized loss on still-held positions (realized share 7.3%).

**Candidate fix**: Add a portfolio-level drawdown circuit breaker: when running DD exceeds 10% within 5 trading days, force trim each position by 50% at next close. Re-entry permitted only after equity recovers to within 5% of prior peak. Implementation point: extend tools/run_broker_position_risk_replay.py or wire into operating_main/concentrated_target_book builder.

### [MEDIUM] `F2_loss_concentration_in_neutral_regime_main`

**Evidence**: 57% of total realized losses ($-179,827 of $-318,269) occurred in neutral regime, across 257 trades (avg $-700). The engine over-allocates or over-trades in this regime.

**Candidate fix**: Reduce capacity_for_regime['neutral'] in the operating book builder by 20-30%, or tighten entry quality threshold (e.g. raise min_score_quantile) for neutral signal dates. Re-measure F2 share on next broker-ledger replay.

### [MEDIUM] `F3_target_exit_losers_deeper_than_rebalance_main`

**Evidence**: target_exit losers average $-736 loss over 364 trades, while target_rebalance losers average $-418 over 120 trades. Explicit exits are firing too late.

**Candidate fix**: Tighten the leader-rescue / stale-trim threshold so a position is exit-flagged earlier in its decline. Inspect tools/run_lifecycle_review_overlay.py and the stale_mega_leader_score weighting in r1000_main_v2.py.

### [MEDIUM] `F8_mdd_target_book_feature_bucket_main_information_technology_loss_cluster`

**Evidence**: Operating target-book rows linked to MDD losers show bucket `information_technology_loss_cluster` with $-30,221 linked position P&L (41% of top context loss), 6 tickers, avg weight 6.5%, max weight 12.0%. Top tickers: AMD, NOW, FTNT, QRVO, RNG, UI.

**Candidate fix**: Use the emitted mdd_policy_bucket_summary.csv and mdd_target_rows.csv to design one narrow PIT-safe entry/hold sizing rule. Do not promote the bucket itself; validate any rule through broker-ledger fast replay.

Research-only analysis. Production decisions still require broker-ledger and human review.
