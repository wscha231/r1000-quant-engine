# CODEX RUN287 BOOK FIDELITY RESIDUAL VERDICT 20260707

Status: `research_only_committed_verdict`

This verdict records the Phase 0/R1 follow-up after PR #220. It narrows the
remaining runner-fidelity gap after local cache coverage was restored to the
runner/candidate 981-ticker requirement.

No fullrun was dispatched. No market data was downloaded by this PR path. No
target book was regenerated for scoring. No threshold tuning, alpha hook,
production promotion, or live trading action was performed.

## Artifacts

- `outputs/run287_book_fidelity_residual/summary.json`
- `outputs/run287_book_fidelity_residual/report.md`
- `outputs/run287_book_fidelity_residual/manifest_diff.csv`
- `outputs/run287_book_fidelity_residual/book_gap_by_date.csv`
- `outputs/run287_book_fidelity_residual/ticker_gap.csv`

## Verdict

- `runner_parity_status=parity_documented_gap`
- `runner_fidelity_status=residual_documented`
- `residual_gap_classification=book_generation_gap`
- `cache_coverage_status=cache_coverage_complete`
- `env_mismatch_count=0`
- `manifest_mismatch_count=5`

Residual source candidates:

- `price_cache_manifest_sha_mismatch`
- `code_provenance_missing_or_mismatch`
- `macro_input_sha_mismatch`
- `operating_append_end_date_mismatch`
- `book_generation_gap`

Interpretation: the old local 498-cache coverage gap is no longer the live
blocker. The local full-candidate cache covers the 981 required tickers, but the
local regenerated books still do not reproduce the official runner target books.

## Manifest mismatches

| Field | Runner | Local |
| --- | --- | --- |
| `code.github_ref` | `refs/heads/codex/integration-fullrun-clean-20260630` | blank |
| `code.github_sha` | `15176b588d5bb0792bce1df6367758d795a8a33a` | blank |
| `price_cache.manifest.sha256` | `fdcf36399cb75225423ce71a92e9cc36e580482015c8bf07718d02376acb4a18` | `1328919074a8ad2ad1916003860ca747183f58f2263bf9af13ebe673810f536a` |
| `macro_crisis_inputs.long_crisis_features.sha256` | `0059b029d0f304c5030b78c5673cc430d4307904e06e6fb425b7ce6c27fe3ffc` | `0ef3bdaa313f0956bb74db2d2c85e01d8988c111d9be36f7cc27995e6c4537db` |
| `operating_append_end_date` | blank | `2026-07-02` |

The frozen policy env keys match (`env_mismatch_count=0`), so the residual is
not explained by the eight-key policy payload being ignored.

## Book gap

| Portfolio | Ticker mismatch dates | Max weight delta | Avg L1 diff | Max L1 diff |
| --- | ---: | ---: | ---: | ---: |
| Main | 70 | 0.1565297563 | 0.1659106531 | 0.4149711458 |
| Concentrated | 1 | 0.4311683310 | 0.0170911441 | 0.9155366620 |

Largest date-level gaps:

- Concentrated `2024-10-31`: L1 `0.9155366620`
- Concentrated `2019-07-31`: L1 `0.4301235816`
- Main `2021-08-31`: L1 `0.4149711458`
- Main `2024-10-31`: L1 `0.3785953419`
- Main `2023-02-28`: L1 `0.3767133956`

Largest ticker-level cumulative absolute deltas:

- Main `CASH`: `3.2283629738`
- Concentrated `CASH`: `0.5896027443`
- Main `ZM`: `0.3909718390`
- Main `BRBR`: `0.3670167665`
- Main `NVDA`: `0.3304611483`

## Decision

R1 is improved but not complete.

The next concrete R1 action is a same-artifact reproduction attempt with all
currently identified residual knobs aligned:

1. code checkout/provenance pinned to `15176b588d5bb0792bce1df6367758d795a8a33a`;
2. runner-style `GITHUB_REF` / `GITHUB_SHA` provenance populated in the local
   manifest;
3. `operating_append_end_date` matched to runner blank state, not local
   `2026-07-02`;
4. macro crisis feature artifact matched to runner sha
   `0059b029d0f304c5030b78c5673cc430d4307904e06e6fb425b7ce6c27fe3ffc`;
5. price-cache manifest sha mismatch carried explicitly unless the exact runner
   cache manifest can be restored.

Until that pass is attempted, regeneration-based attribution and hook design
remain blocked or must carry `runner_fidelity_status=residual_documented`.
