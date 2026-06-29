# Trade Attribution Report - main

- Generated: 2026-06-29T12:58:57.185621+00:00
- Schema: `trade-attribution-findings-v1`
- Analysis mode: `round_trip_journal`

## Broker-Ledger Headline

- CAGR: 35.28%
- Sharpe: 1.268
- MaxDD: -24.25%
- Trade count: 1679

## Win/Loss Distribution

- Round trips: 1136
- Win rate: 58.2%
- Avg winner: $1,274
- Avg loser: $-728
- Total winners P&L: $842,283
- Total losers P&L: $-345,841

## MDD Window

- Peak: 2025-02-18, $383,407
- Trough: 2025-04-04, $290,421
- Drawdown: -24.25%
- Trades exited inside window: 34 (total P&L $-20,927)

## Broker Trades In MDD Window

- Executions: 44
- Buys / sells: 17 / 27
- Gross traded: $568,645
- Net cash delta: $125,808

## Top Position P&L Contributors

| Ticker | P&L | Avg weight | Max weight | Days held |
| --- | ---: | ---: | ---: | ---: |
| PLTR | $-47,645 | 11.6% | 14.8% | 33 |
| TPR | $-18,826 | 5.3% | 7.4% | 33 |
| ETR | $-11,152 | 5.1% | 5.8% | 25 |
| BROS | $-10,256 | 4.0% | 4.9% | 25 |
| HWM | $-10,189 | 4.6% | 5.2% | 25 |
| APP | $-9,875 | 6.6% | 7.7% | 8 |
| VRSN | $-9,462 | 4.7% | 5.4% | 25 |
| GILD | $-9,378 | 4.5% | 5.3% | 25 |
| NTNX | $-8,790 | 4.7% | 5.0% | 21 |
| FOX | $-6,296 | 3.4% | 3.9% | 25 |

## MDD Target-Book Feature Buckets

| Bucket | Linked P&L | Tickers | Avg weight | Max weight | Top tickers |
| --- | ---: | ---: | ---: | ---: | --- |
| information_technology_loss_cluster | $-88,292 | 8 | 6.1% | 11.6% | PLTR, APP, VRSN, NTNX, MSTR, MRVL, FTNT, HUBS |
| qqq_underperforms_spy_weighted | $-66,288 | 4 | 8.5% | 11.6% | PLTR, APP, MSTR, MRVL |
| weak_confirmation_weighted | $-56,412 | 3 | 8.3% | 11.4% | PLTR, MSTR, MRVL |
| high_vol_weighted | $-53,299 | 2 | 9.3% | 11.4% | PLTR, MSTR |
| below_ma50_weighted | $-53,299 | 2 | 7.9% | 11.4% | PLTR, MSTR |
| negative_short_rs_weighted | $-50,758 | 2 | 5.8% | 6.5% | PLTR, MRVL |
| high_weight_market_leader | $-47,645 | 1 | 11.5% | 11.6% | PLTR |

## MDD Target-Book Context By Ticker

| Ticker | Linked P&L | Date range | Rows | Max weight | Lane | Regime |
| --- | ---: | --- | ---: | ---: | --- | --- |
| PLTR | $-47,645 | 2025-01-31 to 2025-03-31 | 3 | 11.6% | MARKET_LEADER | bear |
| TPR | $-18,826 | 2025-01-31 to 2025-03-31 | 3 | 5.9% | MARKET_LEADER | bear |
| ETR | $-11,152 | 2025-02-28 to 2025-03-31 | 2 | 5.7% | MARKET_LEADER | bear |
| BROS | $-10,256 | 2025-02-28 to 2025-03-31 | 2 | 5.0% | MARKET_LEADER | bear |
| HWM | $-10,189 | 2025-02-28 to 2025-03-31 | 2 | 5.0% | MARKET_LEADER | bear |
| APP | $-9,875 | 2025-01-31 to 2025-01-31 | 1 | 6.0% | MARKET_LEADER | neutral |
| VRSN | $-9,462 | 2025-02-28 to 2025-03-31 | 2 | 5.0% | MARKET_LEADER | bear |
| GILD | $-9,378 | 2025-02-28 to 2025-03-31 | 2 | 5.0% | MARKET_LEADER | bear |
| NTNX | $-8,790 | 2025-02-28 to 2025-02-28 | 1 | 5.0% | MARKET_LEADER | neutral |
| FOX | $-6,296 | 2025-02-28 to 2025-03-31 | 2 | 3.8% | MARKET_LEADER | bear |

## Findings (machine-readable in findings.json)

### [MEDIUM] `F2_loss_concentration_in_neutral_regime_main`

**Evidence**: 56% of total realized losses ($-193,450 of $-345,841) occurred in neutral regime, across 250 trades (avg $-774). The engine over-allocates or over-trades in this regime.

**Candidate fix**: Reduce capacity_for_regime['neutral'] in the operating book builder by 20-30%, or tighten entry quality threshold (e.g. raise min_score_quantile) for neutral signal dates. Re-measure F2 share on next broker-ledger replay.

### [MEDIUM] `F3_target_exit_losers_deeper_than_rebalance_main`

**Evidence**: target_exit losers average $-819 loss over 356 trades, while target_rebalance losers average $-456 over 119 trades. Explicit exits are firing too late.

**Candidate fix**: Tighten the leader-rescue / stale-trim threshold so a position is exit-flagged earlier in its decline. Inspect tools/run_lifecycle_review_overlay.py and the stale_mega_leader_score weighting in r1000_main_v2.py.

### [MEDIUM] `F8_mdd_target_book_feature_bucket_main_information_technology_loss_cluster`

**Evidence**: Operating target-book rows linked to MDD losers show bucket `information_technology_loss_cluster` with $-88,292 linked position P&L (49% of top context loss), 8 tickers, avg weight 6.1%, max weight 11.6%. Top tickers: PLTR, APP, VRSN, NTNX, MSTR, MRVL, FTNT, HUBS.

**Candidate fix**: Use the emitted mdd_policy_bucket_summary.csv and mdd_target_rows.csv to design one narrow PIT-safe entry/hold sizing rule. Do not promote the bucket itself; validate any rule through broker-ledger fast replay.

Research-only analysis. Production decisions still require broker-ledger and human review.
