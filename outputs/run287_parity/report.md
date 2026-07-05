# Run287 Runner Parity Cache Audit

Status: `completed`

Research-only R1 audit. No fullrun was dispatched, no market data was downloaded,
and no target book was regenerated.

## Verdict

- runner_parity_status: `parity_documented_gap`
- reason: `local_cache_or_book_differs_from_runner_manifest`

## Price Cache

- runner_required_ticker_count: `981`
- runner_existing_price_file_count: `981`
- local_manifest_ticker_count: `498`
- local_present_price_file_count: `489`
- local_missing_price_file_count: `492`

## Book Parity

| Portfolio | Status | Common dates | Ticker mismatch dates | Max weight delta | Avg L1 diff |
| --- | --- | ---: | ---: | ---: | ---: |
| main | parity_gap | 86 | 84 | 0.14 | 0.3580 |
| concentrated | parity_gap | 86 | 72 | 0.411 | 0.3825 |

Anti-leakage: missing cache entries are listed explicitly in `missing_bars.csv`.
No ticker was dropped to force a parity match.
