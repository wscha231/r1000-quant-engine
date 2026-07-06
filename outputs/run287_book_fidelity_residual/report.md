# Run287 Book Fidelity Residual Audit

Status: `completed`

Research-only R1 diagnostic. No fullrun was dispatched, no market data was
downloaded, no target book was regenerated, and no threshold was tuned.

## Verdict

- runner_parity_status: `parity_documented_gap`
- runner_fidelity_status: `residual_documented`
- residual_gap_classification: `book_generation_gap`
- residual_source_candidates: `price_cache_manifest_sha_mismatch,code_provenance_missing_or_mismatch,macro_input_sha_mismatch,operating_append_end_date_mismatch,book_generation_gap`

## Manifest

- manifest_mismatch_count: `5`
- env_mismatch_count: `0`

## Books

| Portfolio | Status | Ticker mismatch dates | Max weight delta | Avg L1 diff | Max L1 diff |
| --- | --- | ---: | ---: | ---: | ---: |
| main | parity_gap | 70 | 0.15653 | 0.165911 | 0.414971 |
| concentrated | parity_gap | 1 | 0.431168 | 0.0170911 | 0.915537 |

Interpretation:

- Cache coverage can be complete while runner fidelity is still not exact.
- Treat this as residual provenance/book-generation evidence, not a strategy pass.
- Regeneration-based attribution remains blocked until this residual is resolved
  or explicitly carried as a caveat.
