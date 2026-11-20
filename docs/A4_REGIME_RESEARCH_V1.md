# A4 bear/bull research transforms

These pure offline components implement hypotheses for the seven requested
indicator groups. They make zero provider requests, model fits, forecast
releases, scheduler changes, Source admissions or A3/A5 calls. The native
ten-axis risk engine and its readiness conditions remain authoritative. The
JSON hypothesis register records source and historical-data gaps; its presence
is not current coverage or a signal-voting scheme.

`tools/a4_regime_features.py` covers 10y-2y and 10y-3m curve re-crossings,
21/63-session short/long yield contributions, credit levels/changes in bp,
prior-only credit distributions, VIX-family tenor context, supplied-population
A-D/high-low/MA participation and 21/63-session sector rotation. It keeps energy
separate from the XLP/XLU/XLV defensive basket. VIX/VIX3M is an index-tenor
ratio, not the listed-futures curve. A 4 pp HY threshold is a user hypothesis,
not a universal normal-range rule. A current research cohort cannot claim
historical NYSE or S&P500 membership. Missing counts, gaps and pre-launch ETF
prices are never filled with zero observations or historical market breadth.
MA50 and MA200 each retain their own eligible-history denominator; they need
not equal the full advances/declines population. Signed OAS values are retained
in bp instead of being silently floored at zero.

The dated-economy transform reuses the existing calendar and typed RTDSM
preflight, then selects one full visible vintage for each input. Fifteen
consecutive monthly unemployment levels produce the current three-month mean
minus the minimum of the previous 12 three-month means; the threshold is 0.50
percentage points. Quarterly-vintage RUC produces a delayed proxy, not official
real-time Sahm. Payroll/CPI growth uses native monthly periods; daily state
repetition is not a new independent release. Missing months in a newer vintage
are not restored from an older column.

`tools/a4_regime_context.py` separates an announced target from the effective
target, and an observed first cut of a known cycle from unknown initial
history. Consecutive-decision counters are not daily event counts. QE/QT labels
require separately reviewed original announcements; increasing Fed assets is
not converted into QE or a QE probability. LEI calculations keep the six-
consecutive-decline hypothesis distinct from a versioned six-month depth and
diffusion condition. CAPE is context, not a short-horizon timer; analyst revision
breadth requires complete dated up/down/unchanged counts.

Availability gates which policy decisions are visible, then announcement and
effective chronology determine their respective targets. A delayed older
announcement cannot restore a superseded announced target. Conflicting originals
for the same announcement are refused. Output dtypes remain fixed when later
visible events add previously unknown values. LEI's confirmed decline suffix
length is separate from a six-change hypothesis, which stays unknown when any
required month is missing. Monthly expansion is capped before allocation.
Breadth validates each present count relationship even on partial rows; its
divergence flag requires current values and both complete 252-session references.

Callers independently pin/replay original bytes, applicable rights, publisher
identity, historical availability and input policy. These math APIs do not
authenticate supplied data or manufacture PIT evidence. Revised current
histories and arbitrary lags cannot become historical originals. CNN's current
index and the older VIX/return proxy are not a qualified CNN history; overlapping
components are not independent votes. No FRED/ALFRED service content is newly
collected or admitted for machine learning.

Actual private tests retain their original code/input hashes, distinct from
synthetic smoke tests and publication of these modules. They are exploratory,
not a qualified after-cost portfolio backtest, blind holdout, calibrated
bear/QE probability, accepted trial or production forecast. Negative and
unavailable cases remain in the testing family and private research history.
The prior 576-case and additional 144-case discovery comparison found no positive
MSE-improvement case at q<=0.05. That result does not select a model.

The standalone504-session horizon remains exploratory. With the current
10,000-session input cap and756-session initial split, even ignoring feature
warmup and training maturity yields at most18 nonoverlap OOS windows at504.
It cannot meet the existing20-window evidence gate under this budget. More
overlapping daily rows do not remove that limit; changing a budget, target or
qualification policy requires a separate reviewed contract and adequate history.

Validation: `python tests/a4_regime_signals_smoke.py`. Registration also binds
the smoke, three implementations, consumed legacy vintage codec and JSON in the
independent A6 proof inventory. The legacy codec bytes remain unchanged; separate
literal witnesses reject its changed bytes and omission after caller rebinding.

## Coverage in the V2 market report

`market-analysis-report-v2.recession_watch` displays the seven families with
item-level coverage and source evidence. The two Treasury slopes use matching
observations for the report session. The 3-month leg comes from the same
verified Treasury original as the 2- and 10-year legs. The watch retains the
NYSE grid for 21- and 63-session changes and leaves a change unfilled when its
lookback has a gap. The prior available NYSE row is required to report a
crossing. This extra Treasury tenor is scoped to the watch.

When the original BLS data supply 15 contiguous, nonmissing unemployment
months, the watch shows a current-vintage Sahm proxy. Its 0.50 percentage-point
level follows the published metric definition. Retain the current collection
clocks of all source windows used and list any missing months. Official
realtime Sahm and qualified LEI vintages have their own evidence requirements.
The credit view lists SLOOS separately from market spreads. Market breadth, corporate
credit, policy cycles, analyst revisions and matched sector histories expose
their respective missing inputs explicitly.

For one-time private research, an existing V2 request can include an optional
`valuation_cape` input with `source_id: shiller:ie_data`. Supply the exact
original workbook path, byte SHA-256 and actual `collected_at`, using the
ordinary request clock and session checks. The bounded reader takes the CAPE
column from the publisher's `Data` sheet and retains the publisher's cutoff
and estimate notes. It shows the last observation month and its prior-only
120-month comparison. A terminal blank stays missing. The workbook becomes
visible at the actual capture clock. Its history is current vintage, and it
confers no training or history admission. Scheduled collection and durable
storage require the corresponding source use evidence.

The watch supplies observed context alongside the existing 21/63/126-session
handoff. A missing family retains its blocker. No composite recession
probability, independent signal count, native-risk override or portfolio
action comes from this view.
