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

These are available for diagnostics and selection-quality reports only. They
are not added to `score`, `score_total`, `DEFAULT_FEATURES`, or live target
selection.

## Anti-Leakage Rules

- `transaction_date` is never used for feature availability.
- `filing_date` alone is not enough for feature availability.
- Form 4 rows become usable only at `available_from`, which is derived from
  SEC `accepted_at` plus a configurable safety delay.
- 13F, 13D/G, and 8-K must follow the same `accepted_at` / `available_from`
  pattern when implemented.

## Next Phases

1. Add 13D/G activist event parser.
2. Add 8-K material event parser.
3. Add 13F smart-money validation layer.
4. Merge `sec_ownership_signals.parquet` into candidate replay books as shadow
   features only.
5. Evaluate Form 4 shadow features in selection quality and leader-drop reports.
6. Consider tiny production weights only after broker-ledger challenger results
   improve under cost/stress/leakage gates.

