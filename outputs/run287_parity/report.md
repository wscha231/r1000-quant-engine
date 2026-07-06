# Run287 Runner Parity Cache Audit

Status: `completed`

Research-only R1 audit. No fullrun was dispatched, no market data was downloaded,
and no target book was regenerated.

## Verdict

- runner_parity_status: `parity_documented_gap`
- reason: `local_cache_coverage_complete_but_book_differs`

## Price Cache

- runner_required_ticker_count: `981`
- runner_existing_price_file_count: `981`
- local_manifest_ticker_count: `983`
- local_present_price_file_count: `981`
- local_missing_price_file_count: `0`
- cache_coverage_status: `cache_coverage_complete`
- cache_manifest_sha_matches_runner: `False`

## Runner Fidelity

- runner_fidelity_status: `residual_documented`
- residual_gap_classification: `book_generation_gap`

## Book Parity

| Portfolio | Status | Common dates | Ticker mismatch dates | Max weight delta | Avg L1 diff |
| --- | --- | ---: | ---: | ---: | ---: |
| main | parity_gap | 86 | 70 | 0.157 | 0.1659 |
| concentrated | parity_gap | 86 | 1 | 0.431 | 0.0171 |

Anti-leakage: missing cache entries are listed explicitly in `missing_bars.csv`.
No ticker was dropped to force a parity match.
