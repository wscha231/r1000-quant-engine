# CODEX RUN287 R1/R2 VERDICT 20260706

Status: `research_only_committed_verdict`

This verdict records the first two reinforcement tasks from
`docs/CODEX_DIRECTIVE_POST_RUN287_REINFORCEMENT_20260706.md`.

No fullrun was dispatched. No market data was downloaded. No target book was
regenerated. No threshold tuning, alpha hook, production promotion, or live
trading action was performed.

## R1 runner-parity cache verdict

Verdict: `runner_parity_status=parity_documented_gap`

Artifacts:

- `outputs/run287_parity/summary.json`
- `outputs/run287_parity/report.md`
- `outputs/run287_parity/missing_bars.csv`
- `outputs/run287_parity/book_parity.csv`

Key evidence:

- Runner required ticker count: `981`
- Runner existing price file count: `981`
- Runner missing price file count: `0`
- Local manifest ticker count: `983`
- Local present price file count: `981`
- Local missing price file count versus runner/candidate requirement: `0`
- Cache coverage status: `cache_coverage_complete`
- Runner fidelity status: `residual_documented`
- Residual gap classification: `book_generation_gap`
- Runner price-cache manifest sha256:
  `fdcf36399cb75225423ce71a92e9cc36e580482015c8bf07718d02376acb4a18`
- Local price-cache manifest sha256:
  `1328919074a8ad2ad1916003860ca747183f58f2263bf9af13ebe673810f536a`
- `cache_manifest_sha_matches_runner=false`; local coverage is complete, but
  byte-identical runner cache provenance is not established from the published
  artifacts.

Target-book parity is not exact:

| Portfolio | Common dates | Ticker mismatch dates | Max weight delta | Avg L1 diff | Max L1 diff |
| --- | ---: | ---: | ---: | ---: | ---: |
| main | 86 | 70 | 0.1565297563 | 0.1659106531 | 0.4149711458 |
| concentrated | 86 | 1 | 0.4311683310 | 0.0170911441 | 0.9155366620 |

Interpretation:

- The original 498-cache gap is no longer the dominant explanation after using
  `outputs/run287_price_cache_full_candidate/cache_prices`.
- Local cache coverage now reaches the runner/candidate 981-ticker requirement,
  but target-book parity is still not exact.
- The remaining blocker is book-generation fidelity, not missing local price
  files.
- Any R3 exposure-cap or subsequent attribution work must either restore the
  exact runner cache/book substrate or explicitly carry
  `runner_parity_status=parity_documented_gap`.
- This is a measurement substrate verdict, not a strategy pass or production
  readiness verdict.

## R2 survivorship lower-bound verdict

Verdict: `label=proxy`

Artifacts:

- `outputs/run287_survivorship/summary.json`
- `outputs/run287_survivorship/report.md`
- `outputs/run287_survivorship/membership_delta.csv`

Method:

- `first_price_date_stricter_arm_on_committed_candidate_and_target_books`
- Metric source: `generated_book_cash_carry_sidecar`
- Metric mode: `broker_ledger_next_close_cash_carry`

Key evidence:

| Portfolio | Current proxy CAGR | Current proxy MaxDD | Measurable inflation pp | Deflated lower-bound CAGR | Target gap after bound pp | Late-inclusion rows |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| main | 33.8057% | -25.3619% | 0.00 | 33.8057% | 1.1943 | 0 |
| concentrated | 48.4053% | -22.9552% | 0.00 | 48.4053% | 1.5947 | 0 |

Interpretation:

- The measurable first-price-date late-inclusion lower bound is `0.0pp` for
  both sleeves on the committed run287 candidate and target books.
- `survivorship_dominant_component_measured=false`. The `0.0pp` value is only
  the measured late-inclusion slice; it must not be quoted as a
  clean-survivorship estimate.
- The dominant unmeasured component remains `delisted_exclusion`, which cannot
  be reconstructed from the free-tier current-constituents proxy artifacts.
- `pit_universe_label_clean=false` remains a hard production blocker.
- Production promotion remains `false`; the valid label remains research-only
  proxy evidence.

## Next allowed actions

- R3 may run only as a cheap, measurement-only exposure-cap audit and must carry
  the R1 parity status.
- R4 concentrated alpha-source work remains blocked until the user explicitly
  decides whether to open a new data feed.
- No new fullrun is allowed without separate gate clearance and explicit user
  approval.
