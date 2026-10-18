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
Calendar rules are dataset-typed exact values, including only the two explicit
legacy XNYS descriptions in the code; substring/NOT_XNYS or price/macro rule
substitution is refused. Price last-session close (including early closes) and
every macro availability must be at or before the aware retrieval clock, which
must be at or before as_of. ALFRED intervals are inclusive: each revision's
realtime_end must be strictly before the next vintage of the same observation.
Null macro values remain missing release samples; the unchanged shared release
function already refuses differencing either null member. They are not zeros.
Availability must strictly increase with vintage for each observation; equal or
backward revision clocks refuse. Every source price date, including off-window
descriptive rows, is checked against the declared XNYS calendar. Censored
drawdowns stop at the last finite observation, not an unobserved calendar tail.
Macro admission uses the same next-eligible-open effective session as validation.
An internal derived-clock view gates the reused release helper; original source
availability is unchanged and events expose both available_at and admitted_at.

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

The declared OOS grid remains756 XNYS sessions after2016-01-01. Before any
SP500 paired fit, the engine checks the entire mature fixed fold grid for both
arms' eligible training counts, train variance and identical test coverage.
With purge253/min_train504, even zero warmup leaves only503 short-arm train
rows at that first boundary;240-session warmup leaves263. A gap-free technical
arm would structurally need offset997, but the engine does not adopt that
offset, change the frozen config, lower minima or inspect scores to choose a
boundary. Such a comparison returns BLOCKED_SHARED_OOS_COVERAGE for both
declared arms, including per-fold counts/reasons and no fits/predictions. All
declared hypotheses remain in the family count. No intersecting later dates
rescues an invalid first fold. If the fixed grid is feasible, actual first fold
and full scored-position parity are checked after fitting. Immature final label
tails are not scored; wholly missing interior folds still refuse the pair.
The2016 arm
separately masks pre2016 prices and benchmark before computing technical warmup.
It is a2016-01-01 truncated reference, not exact reproduction of the prior
FRED2016-09-12 input or its336 results. Sparse macro sample shortfalls retain
missing predictions and explicit unmatched-date counts. The1996-2015
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
Each bootstrap draw is trimmed to exactly the original session span, including
unscored gaps, without changing seed0,1000 draws or253-session blocks.

Outputs: metrics JSON/CSV, predictions, original-clock macro events, drawdown
episodes (including unrecovered censoring and gap counts), and common-date
relative price performance. The deterministic receipt binds inputs, code,
dependencies, calendar and output hashes. Runtime wall time/peak resident memory
is separate. A budget/input failure publishes no completed output directory.
The output directory must be new and external to the repository.
The unchanged300s/1GiB limits start before manifest/config I/O. Files are hashed
in bounded chunks with deadline/RSS checks; raw source proofs are not retained.
Retained parse inputs reserve a conservative64x byte expansion within the same
RSS ceiling before reading. JSON depth64 and finite bounded numeric tokens,
CSV row iteration and JSONL per-record checks bound parsing. This can refuse
an input well below1GiB rather than allowing whole-object expansion past the
ceiling. Lists/scalars/deep or malformed JSON and allocation/parser refusals
produce only the redacted BLOCKED_RESEARCH_RUN CLI response.
Prediction CSV chunks reserve the final joined buffer before allocation too.
These are cooperative checks/reservations, not OS hard-preemption guarantees.

The original frozen config, manifest,384-comparison outputs and4 historical
SHADOW labels are retained under their original hashes. The original shared-OOS
claim is superseded by this integrity finding, not repaired by relabelling old
results. No384-run repetition or retuning accompanies this H1 correction. All
four old labels' direction accuracy was at or below its training-mean baseline;
that negative limitation remains, and no alpha/economic claim is added.

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
