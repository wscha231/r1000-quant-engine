# Run287 scientific weighting input materialization result (2026-08-19)

## Outcome

The three files required by the scientific weighting readiness gate are now
materialized. The readiness status remains correctly blocked, but the blocker
is no longer an absent file. It is now the substantive point-in-time evidence
gap that must be solved before a real fit.

Local research packet:

- `H:\codex\run287_scientific_inputs_materialized_20260819\component_frame.parquet`
- `H:\codex\run287_scientific_inputs_materialized_20260819\daily_returns.parquet`
- `H:\codex\run287_scientific_inputs_materialized_20260819\prior_weights.csv`
- `H:\codex\run287_scientific_inputs_materialized_20260819\input_manifest.json`
- `H:\codex\run287_scientific_inputs_materialized_20260819\materialization_summary.json`
- `H:\codex\run287_scientific_inputs_materialized_20260819\readiness\data_readiness.json`

The packet contains:

- 989 component-frame rows for one exact scored decision snapshot;
- 1,091,097 exact-consecutive-session daily return rows;
- 363 securities with at least 252 daily return sessions;
- 1,207 historical prior-weight rows;
- 15 latest prior-weight rows dated 2026-07-02, including explicit cash;
- latest prior-weight sum `0.9999999999999993`;
- zero fitted models, selected stocks, proposed weights, target writes, orders,
  ledger mutations, fullruns, or production/live actions.

## Source identity

The historical price substrate came from the existing Run287 research-static
archive. It was downloaded read-only from the configured Google Drive remote
and restored only after its exact SHA-256 matched:

`66ca4b6a6a61cb7e9a3a47e2f6d26aa42f30a9b96a25d07699c6cdeb8faf1d84`

The archive restore verified 387 payload files, including 363 selector price
histories. The prior weights came from the archive member:

`run287_static_anchor/outputs/alphaops_vnext/official_main_target_book.csv`

Its exact source SHA-256, repeated on every prior-weight row, is:

`3e863068e118af3f832b9490defc38baa9f4b0718e024e2870f44bd27a979f22`

Materialized output SHA-256 values are:

- component frame:
  `06021fabed08c860979b295226774fb866b57257e1b2f15f643892c779e6cdb8`;
- daily returns:
  `f490cfc890960a7276690a98f24b6a9ac5ba2bac5a69d67c41daf674b262d291`;
- prior weights:
  `515fd121f3f26b5f8b2ba01f282be33f8a2d6efe6dd981ce4e340a2e29e0dcd6`.

## Scientific materialization rules

The new materializer enforces these boundaries:

1. A component is usable only when its value is finite, its explicit observed
   flag is true, and its own availability timestamp is on or before the row's
   decision time.
2. Usable components are transformed only by decision-date cross-sectional
   average-percentile rank minus 0.5. Missing or unobserved components remain
   missing and never become a neutral zero.
3. Daily returns use adjusted closes from exact consecutive NYSE sessions.
   A missing session is not converted into a multi-session daily return.
4. Labels enter at the first NYSE session after the feature date and use exact
   63- and 126-interval endpoints against SPY. A label is not materialized
   before all four endpoint prices are available.
5. Prior weights are copied exactly. They are not normalized or redistributed,
   and an explicit cash row is preserved.
6. Stored machine paths in the selector price map are not trusted. Each price
   file is resolved by basename inside the restore root and must match exactly
   one declared SHA-256.
7. A current CIK/ticker fallback is labeled `UNVERIFIED_*` and always forces
   `pit_universe_label_clean=false`.

## Remaining readiness blockers

The readiness audit now reports substantive blockers:

- historical component and daily-return universe labels are not PIT-clean;
- the exact scored component substrate has one decision date, below the fixed
  60 mature-date minimum;
- quality/moat, valuation, and growth/revision components have zero admissible
  observations because the current scored snapshot says its decision feature
  set is incomplete and latest-only inputs were neutralized;
- event actuals have 74.6208% admissible coverage, below the fixed 98% minimum;
- the official 13F component has zero admissible observations in this scored
  snapshot;
- there are no mature 63/126-session labels for the one current decision date;
- selector-archive lifecycle state remains current-vintage and unverified.

The daily return shape and prior-weight provenance themselves pass their
quantitative minimums. The correct next work is therefore an append-only
historical PIT component/universe/lifecycle source, not another scoring or
weighting formula.

## Verification

- a complete synthetic PIT dataset with 60 decision dates, 100 securities per
  date, exact NYSE prices, six fully observed components, mature 63/126 labels,
  and accepted prior-weight provenance passed the existing readiness gate;
- a scored-snapshot diagnostic fixture proved that incomplete fundamental and
  absent 13F evidence remain missing rather than becoming zeros;
- the existing readiness smoke and the new materialization smoke passed;
- Python compilation and Git whitespace checks passed;
- full local Tier-1 validation passed 221 of 223 files in 756.95 seconds. The
  two unrelated OHLCV pattern tests failed because the Windows worktree has 94
  CRLF line endings in an unchanged pinned contract: worktree SHA-256
  `dd8b9a...` versus exact Git-blob/pinned SHA-256 `30c1e1...`. The scientific
  readiness and materialization tests both passed, and this change did not
  modify the OHLCV contract or its consumers.

The real historical fit, outer test, portfolio replay, and performance claim
remain unopened.
