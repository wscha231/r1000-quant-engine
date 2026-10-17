# Offline index research engine v1

`python -m tools.macro_index_research_engine --manifest FILE --manifest-sha256 SHA --config FILE --config-sha256 SHA --output NEW_EXTERNAL_DIRECTORY`

The CLI consumes six pinned local reference datasets: SP500, NASDAQCOM,
NASDAQ100 and monthly UNRATE/PAYEMS/CPIAUCSL ALFRED originals. No network,
provider, Drive, workflow, book or order operation is implemented. Input paths,
bytes, source hashes, identity, purpose, dates and clocks are checked before
scoring. Price gaps stay on the XNYS session grid; no price forward filling,
ETF substitution, index stitching or total-return claim is supported.

Manifest schema `macro-index-research-input-v1` has `datasets`; each row needs
the exact `REQUIRED` fields in the module. Price CSV uses `date,close` and
`identity_type=PRICE_INDEX`, `frequency=daily`, calendar rule `XNYS`.
ALFRED JSONL retains the original `series,observation_date,value,vintage_date,
available_at,realtime_end,evidence` plus `effective_session`. Three manifest
rows may bind one shared JSONL; row_count counts each row's series only.
Macro identity_type is MACRO_SERIES, frequency monthly, calendar rule
MONTHLY_ALFRED_VINTAGE. All rows require rights_status
PRIVATE_RESEARCH_REFERENCE_ONLY and purpose_limit EXPLORATORY_RESEARCH_ONLY;
these labels constrain use and do not certify supplier rights or PIT admission.

Config schema `macro-index-research-config-v1` fixes start1996-01-01,
comparison_start2016-01-01, horizons21/63/126/252, entry_delay1, min_train504,
macro_min_train60, initial756, fold_size252, primary_metric oos_mse_improvement,
prior_exposed_families336, parameter_search false, max_seconds300 and
max_rss_bytes1073741824. End/as_of and preregistered_at_utc must be explicitly
pinned. No search over settings or post-result tuning is implemented.

Existing technical_features (21), archive_release_changes (three monthly
release changes), labels and evaluate are reused. Labels use t+1 completed
close entry. The evaluator receives maturity-delay253-horizon for its
already-built labels, enforcing a253-session train purge in every family;
the report distinguishes this adapter argument from actual label entry_delay1.
No train normalization, baseline or regression fit sees test rows. Monthly
release-only features use the existing study's60-release minimum, frozen before
actual results; technical features retain504. No daily macro replication is used.

The shared OOS grid begins756 XNYS sessions after2016-01-01. SP500's1996
and2016 training arms use identical test boundaries and labels. The1996-2015
increment is separately descriptive/training coverage, not an additional
optimized scoring run. Per-date loss improvements compare each model with
its training-only mean baseline. A paired circular253-session block bootstrap
(seed0,1000 draws) on original XNYS positions, including unscored gaps, reports
descriptive uncertainty. Sparse monthly-release comparisons remain INDETERMINATE
without claiming daily block evidence. Material exploratory change
requires a baseline-relative mean sign reversal, or95% paired interval excluding
zero and absolute difference >=0.2 pooled per-date improvement SD. Fewer than
three blocks is INDETERMINATE. Existing BY adjustment covers all384 declared
comparisons including insufficient families. No feature is selected or promoted.

Outputs: metrics JSON/CSV, predictions, original-clock macro events, drawdown
episodes (including unrecovered censoring and gap counts), and common-date
relative price performance. The deterministic receipt binds inputs, code,
dependencies, calendar and output hashes. Runtime wall time/peak resident memory
is separate. A budget/input failure publishes no completed output directory.
The output directory must be new and external to the repository.

These are current-vintage FREE_PROXY price-index and isolated ALFRED reference
diagnostics, excluding dividends and execution costs. The existing336 families
and historical holdout have prior exposure. Results are exploratory/post-selection,
not independent confirmation, current ER, net CAGR, an investable strategy,
canonical Lake success, full historical PIT certification, selector admission,
portfolio backtest, or economic approval.

Standalone tests: `python -m tests.macro_index_research_engine_smoke` and
`python -O -m tests.macro_index_research_engine_smoke`. The common CI runner is
unchanged and does not automatically register these new tests. H1 source and
fixtures belong in this PR; H2 preregistration, reference inputs and results
remain outside the repository.
