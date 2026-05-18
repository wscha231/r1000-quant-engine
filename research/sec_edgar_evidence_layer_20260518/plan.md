# SEC EDGAR Evidence Layer Plan - 2026-05-18

## Objective

Build a free SEC EDGAR evidence layer before paid data services. The first
production-safe milestone is Form 4 open-market insider transaction ingestion as
a point-in-time shadow signal. It must never change production selection until
broker-ledger evidence and leakage audits justify promotion.

## Contact / Fair Access

- Default SEC User-Agent: `r1000-quant-engine contact: andrewcha231@gmail.com`
- Backup contact: `andrewcha0116@gmail.com`
- Collectors throttle requests and expose `--sec-user-agent` so CI/manual runs
  can override contact details without code changes.

## Phase 1 Implemented

- `tools/run_sec_submissions_collector.py`
  - downloads SEC company ticker map
  - keeps `cik10` as a 10-character string
  - polls submissions metadata for selected tickers
  - writes `accepted_at` and conservative `available_from`
- `tools/run_sec_form4_parser.py`
  - parses Form 4 XML and SEC rendered HTML primary documents
  - writes normalized insider transactions
- `tools/run_sec_ownership_signals.py`
  - creates shadow Form 4 evidence scores
  - filters strictly by `available_from <= as_of_date`
  - can build historical PIT signal panels from candidate replay dates

## Phase 2 Implemented

- `tools/sec_signal_merge.py`
  - merges `sec_ownership_signals.parquet` into dated candidate/scored frames
  - enforces `signal.as_of_date <= row.rebalance_date` for historical rows
  - uses latest-per-ticker only for latest snapshot frames without dates
- `tools/run_selection_quality_report.py`
  - merges SEC shadow signals before factor IC / top-k / decile diagnostics
  - reports SEC signal coverage without changing target weights
- `tools/run_alpha_selector_broker_grid.py`
  - merges SEC signals before leader-onset scoring
  - adds `leader_onset_sec_shadow` as a research-only broker-ledger challenger style
- `tools/run_leader_drop_diagnostics.py`
  - merges SEC signals into missed-leader path diagnostics
  - surfaces SEC evidence and signal dates in leader drop reports

## Outputs

- `data_pit/sec/ticker_cik_map.parquet`
- `data_pit/sec/sec_filings_index.parquet`
- `data_pit/sec/form4_transactions.parquet`
- `data_pit/sec/sec_ownership_signals.parquet`
- `outputs/sec_ownership_signals/form4_latest.csv`
- `outputs/sec_ownership_signals/ownership_signal_summary.json`
- `outputs/sec_ownership_signals/report.md`

## Shadow Features

- `sec_form4_open_market_buy_score`
- `sec_form4_cluster_buy_score`
- `sec_form4_ceo_cfo_buy_score`
- `sec_form4_sale_pressure_score`
- `early_evidence_score`
- `evidence_confidence_score`

These are available for diagnostics, selection-quality reports, leader-drop
reports, and research-only alpha-selector challenger styles. They are not added
to `score`, `score_total`, `DEFAULT_FEATURES`, production portfolio defaults,
or live target selection.

## Anti-Leakage Rules

- `transaction_date` is never used for feature availability.
- `filing_date` alone is not enough for feature availability.
- Form 4 rows become usable only at `available_from`, which is derived from
  SEC `accepted_at` plus a configurable safety delay.
- 13F, 13D/G, and 8-K must follow the same `accepted_at` / `available_from`
  pattern when implemented.

## Next Phases

1. Run a fast replay/full sidecar on real artifacts to measure SEC signal
   coverage and whether `leader_onset_sec_shadow` changes broker-ledger results.
2. Add 13D/G activist event parser.
3. Add 8-K material event parser.
4. Add 13F smart-money validation layer.
5. Consider tiny production weights only after broker-ledger challenger results
   improve under cost/stress/leakage gates.
