# Earnings Data Inventory

This is a research-only inventory. It separates SEC actuals, candidate proxy scores, and true PIT revision/guidance feeds.

- generated_at_utc: `2026-07-06T13:02:11Z`
- true_revision_guidance_ready: `false`
- production_activation_allowed: `false`

## Layer Status

| Layer | Status | Coverage Ready | Path |
|---|---:|---:|---|
| sec_companyfacts_actuals | missing |  | `H:\codex\r1000_run287_r1r2_20260706\data_raw\free\sec\companyfacts.zip` |
| raw_true_revision_guidance_feed | missing | False | `H:\codex\r1000_run287_r1r2_20260706\data_raw\events\earnings_revisions.csv` |
| pit_true_revision_guidance_signals | missing | False | `H:\codex\r1000_run287_r1r2_20260706\data_pit\events\earnings_revision_signals.parquet` |
| candidate_book_actuals_and_proxy_scores | available | False | `H:\codex\r1000_run287_r1r2_20260706\cloud_results\full_rebuild\20260705_28725350727_global_alpha_universe\reports\candidate_replay_book.csv` |

## Interpretation

- SEC companyfacts actuals can confirm historical fundamentals, but they are not analyst estimate revisions.
- Candidate-book scores such as `actual_results_score` and `eps_revision_score` are internal/proxy fields unless a true feed is joined.
- `sec_actual_snapshot` and `current_snapshot` source types are allowed for inventory, but they do not count toward R1 earnings/guidance coverage.
- A true revision/guidance layer requires dated PIT rows with coverage-eligible source types and `available_from <= decision_date`.

## Service Labels

| Label | Meaning | Revision Confirmed | Guidance Confirmed |
|---|---|---:|---:|
| `actuals_confirmed` | Backward-looking SEC actuals. This does not imply analyst estimate revision. | False | False |
| `analyst_revision_confirmed` | Forward estimate revision from a dated, coverage-eligible source. | True | False |
| `company_guidance_confirmed` | Company guidance direction from a dated, coverage-eligible source. | False | True |
| `proxy_score_diagnostic_only` | Internal proxy score. Not a substitute for analyst revision or guidance. | False | False |
| `data_insufficient` | Do not use as earnings confirmation. | False | False |
