# SEC 13F and Form 4 Evidence Score Plan

## Decision

SEC filing evidence stays research-only until an 8-year point-in-time replay
proves it improves official broker-ledger metrics.

Form 4 is a fast insider conviction signal. Form 13F is a delayed institutional
ownership signal. They should support the existing future-winner and market
confirmation stack, not replace it.

## Current Data Timing

- Form 4: use `accepted_at` / `available_from`; never use `transaction_date` for availability.
- Form 13F: use `accepted_at` / `available_from`; never use `report_period` for availability.
- 2026 Q1 13F reports were due on 2026-05-15, so the May 2026 update is current operating evidence, not evidence available to earlier historical rows.

## Features

### Form 4

- `sec_form4_open_market_buy_score`
- `sec_form4_cluster_buy_score`
- `sec_form4_ceo_cfo_buy_score`
- `sec_form4_sale_pressure_score`
- `early_evidence_score`
- `evidence_confidence_score`

### Form 13F

- `sec_13f_manager_count`
- `sec_13f_buying_manager_count`
- `sec_13f_selling_manager_count`
- `sec_13f_new_position_manager_count`
- `sec_13f_total_value_usd`
- `sec_13f_value_delta_usd`
- `sec_13f_value_delta_to_mcap`
- `sec_13f_consensus_buy_score`
- `sec_13f_conviction_score`
- `sec_13f_accumulation_score`
- `sec_13f_new_position_score`
- `sec_13f_crowding_score`
- `sec_13f_stale_penalty`
- `sec_13f_smart_money_score`
- `institutional_evidence_score`
- `institutional_evidence_confidence_score`

## Initial Score

```text
sec_combined_evidence_score =
  0.45 * form4_early_evidence
+ 0.35 * institutional_evidence_score
+ 0.10 * sec_13f_value_delta_to_mcap_score
+ 0.10 * evidence_confidence_blend
```

```text
leader_onset_sec_v3_score =
  0.30 * future_winner_rank
+ 0.18 * market_confirmation
+ 0.17 * sec_combined_evidence_score
+ 0.10 * institutional_evidence_score
+ 0.12 * industry_leadership_rank
+ 0.08 * rs_acceleration_rank
+ 0.05 * entry_quality
```

## 8-Year Backtest Protocol

1. Backfill PIT SEC data for the candidate universe plus a manager CIK watchlist.
2. Map 13F holdings to tickers using a CUSIP map when available; use issuer-name fallback only when the candidate book has a unique match.
3. Build monthly candidate rows with only filings whose `available_from <= rebalance_date 23:59:59 UTC`.
4. Run `selection_quality_report` on the SEC-enriched candidate book.
5. Only if IC/top-k improves, run `alpha_selector_broker_grid` with `sec_evidence_shadow`.
6. Promote nothing unless official `broker_ledger_next_close` improves against locked baselines.

## Search Grid

Test only small evidence weights first.

```text
form4_weight: 0.05, 0.10, 0.15, 0.20
13f_weight: 0.00, 0.05, 0.10, 0.15
market_confirmation_weight: 0.15, 0.20, 0.25
future_winner_weight: 0.25, 0.30, 0.35
crowding_penalty: 0.00, 0.05, 0.10, 0.15
```

## Promotion Gate

Main candidate must beat:

```text
CAGR 21.84%
MDD -28.62%
```

Concentrated candidate must beat:

```text
CAGR 35.10%
MDD -22.68%
```

The final decision must use `broker_ledger_next_close`, not proxy or legacy metrics.

## Operations

SEC data is stored outside git and reused across computers.

```text
data_raw/sec/
  Raw SEC company tickers, submissions JSON, and filing XML cache.

data_pit/sec/
  Normalized PIT parquet/csv tables used by evidence scoring and backtests.

outputs/sec_ownership_signals/
outputs/sec_institutional_signals/
outputs/sec_evidence_learning/
  Report and research artifacts.
```

Google Drive is the long-term shared data lake. GitHub Actions cache is only a
speed layer and can expire. Scheduled SEC workflows restore from Google Drive
first, update the local data lake, upload artifacts, then sync back to Google
Drive.

Before manually starting SEC or backtest workflows, check recent GitHub Actions
runs for overlap:

```powershell
gh run list --repo wscha231/r1000-quant-engine --limit 20
gh run list --repo wscha231/r1000-quant-engine --status in_progress --limit 20
```

The SEC workflows also use GitHub Actions `concurrency` groups so Form 4, 13F,
and SEC learning jobs do not write the shared SEC data lake at the same time.
