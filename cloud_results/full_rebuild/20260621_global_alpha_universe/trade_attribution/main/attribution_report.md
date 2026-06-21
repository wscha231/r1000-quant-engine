# Trade Attribution Report - main

- Generated: 2026-06-21T02:49:58.832558+00:00
- Schema: `trade-attribution-findings-v1`
- Analysis mode: `round_trip_journal`

## Broker-Ledger Headline

- CAGR: 34.27%
- Sharpe: 1.255
- MaxDD: -27.18%
- Trade count: 1656

## Win/Loss Distribution

- Round trips: 1126
- Win rate: 56.9%
- Avg winner: $1,123
- Avg loser: $-639
- Total winners P&L: $720,058
- Total losers P&L: $-309,792

## MDD Window

- Peak: 2020-02-19, $126,854
- Trough: 2020-03-18, $92,372
- Drawdown: -27.18%
- Trades exited inside window: 15 (total P&L $-4,525)

## Broker Trades In MDD Window

- Executions: 17
- Buys / sells: 5 / 12
- Gross traded: $51,800
- Net cash delta: $39,102

## Top Position P&L Contributors

| Ticker | P&L | Avg weight | Max weight | Days held |
| --- | ---: | ---: | ---: | ---: |
| AMD | $-10,724 | 8.8% | 13.2% | 20 |
| NOW | $-7,387 | 8.9% | 12.0% | 20 |
| PENN | $-7,377 | 3.9% | 6.7% | 20 |
| TREX | $-6,047 | 1.4% | 1.7% | 13 |
| PCTY | $-5,640 | 2.8% | 5.4% | 20 |
| FTNT | $-5,373 | 2.7% | 5.3% | 20 |
| PAYC | $-5,013 | 2.8% | 5.1% | 20 |
| QRVO | $-4,940 | 2.8% | 5.5% | 20 |
| SHOP | $-4,532 | 4.3% | 5.9% | 20 |
| TSLA | $-4,442 | 5.3% | 6.1% | 20 |

## MDD Target-Book Feature Buckets

| Bucket | Linked P&L | Tickers | Avg weight | Max weight | Top tickers |
| --- | ---: | ---: | ---: | ---: | --- |
| information_technology_loss_cluster | $-30,960 | 6 | 6.5% | 12.0% | AMD, NOW, FTNT, QRVO, RNG, UI |
| weak_confirmation_weighted | $-20,219 | 3 | 9.1% | 12.0% | AMD, NOW, RNG |
| negative_short_rs_weighted | $-18,135 | 4 | 5.9% | 6.7% | AMD, QRVO, CZR, UI |
| high_weight_market_leader | $-18,110 | 2 | 12.0% | 12.0% | AMD, NOW |
| below_ma50_weighted | $-16,093 | 3 | 6.0% | 6.7% | AMD, QRVO, UI |
| high_vol_weighted | $-10,724 | 1 | 6.7% | 6.7% | AMD |

## MDD Target-Book Context By Ticker

| Ticker | Linked P&L | Date range | Rows | Max weight | Lane | Regime |
| --- | ---: | --- | ---: | ---: | --- | --- |
| AMD | $-10,724 | 2020-01-31 to 2020-02-28 | 2 | 12.0% | MARKET_LEADER | bear |
| NOW | $-7,387 | 2020-01-31 to 2020-02-28 | 2 | 12.0% | MARKET_LEADER | bear |
| PENN | $-7,377 | 2020-01-31 to 2020-02-28 | 2 | 5.6% | MARKET_LEADER | bear |
| TREX | $-6,047 | 2020-02-28 to 2020-02-28 | 1 | 1.6% | QUALITY_COMPOUNDER | bear |
| PCTY | $-5,640 | 2020-01-31 to 2020-02-28 | 2 | 5.6% | MARKET_LEADER | bear |
| FTNT | $-5,373 | 2020-01-31 to 2020-02-28 | 2 | 5.6% | QUALITY_COMPOUNDER | bear |
| PAYC | $-5,013 | 2020-01-31 to 2020-02-28 | 2 | 5.6% | MARKET_LEADER | bear |
| QRVO | $-4,940 | 2020-01-31 to 2020-02-28 | 2 | 5.6% | MARKET_LEADER | bear |
| SHOP | $-4,532 | 2020-01-31 to 2020-02-28 | 2 | 5.6% | MARKET_LEADER | bear |
| TSLA | $-4,442 | 2020-01-31 to 2020-02-28 | 2 | 5.8% | MARKET_LEADER | bear |

## Findings (machine-readable in findings.json)

### [HIGH] `F1_mdd_dominated_by_unrealized_holdings_main`

**Evidence**: MDD window 2020-02-19 to 2020-03-18 (-27.18% drawdown, equity loss $34,482) had only 15 round-trip exits totaling $-4,525 P&L. The drawdown is therefore dominated by unrealized loss on still-held positions (realized share 13.1%).

**Candidate fix**: Add a portfolio-level drawdown circuit breaker: when running DD exceeds 10% within 5 trading days, force trim each position by 50% at next close. Re-entry permitted only after equity recovers to within 5% of prior peak. Implementation point: extend tools/run_broker_position_risk_replay.py or wire into operating_main/concentrated_target_book builder.

### [MEDIUM] `F2_loss_concentration_in_neutral_regime_main`

**Evidence**: 56% of total realized losses ($-172,288 of $-309,792) occurred in neutral regime, across 257 trades (avg $-670). The engine over-allocates or over-trades in this regime.

**Candidate fix**: Reduce capacity_for_regime['neutral'] in the operating book builder by 20-30%, or tighten entry quality threshold (e.g. raise min_score_quantile) for neutral signal dates. Re-measure F2 share on next broker-ledger replay.

### [MEDIUM] `F3_target_exit_losers_deeper_than_rebalance_main`

**Evidence**: target_exit losers average $-709 loss over 365 trades, while target_rebalance losers average $-425 over 120 trades. Explicit exits are firing too late.

**Candidate fix**: Tighten the leader-rescue / stale-trim threshold so a position is exit-flagged earlier in its decline. Inspect tools/run_lifecycle_review_overlay.py and the stale_mega_leader_score weighting in r1000_main_v2.py.

### [MEDIUM] `F8_mdd_target_book_feature_bucket_main_information_technology_loss_cluster`

**Evidence**: Operating target-book rows linked to MDD losers show bucket `information_technology_loss_cluster` with $-30,960 linked position P&L (40% of top context loss), 6 tickers, avg weight 6.5%, max weight 12.0%. Top tickers: AMD, NOW, FTNT, QRVO, RNG, UI.

**Candidate fix**: Use the emitted mdd_policy_bucket_summary.csv and mdd_target_rows.csv to design one narrow PIT-safe entry/hold sizing rule. Do not promote the bucket itself; validate any rule through broker-ledger fast replay.

Research-only analysis. Production decisions still require broker-ledger and human review.
