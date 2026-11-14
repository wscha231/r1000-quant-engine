# Philadelphia Fed dated-vintage research inputs

`tools/a4_rtdsm_sources.py` is an offline, bounded original adapter in the
existing A4 primary archive. It installs no collector, schedule, cloud enable
flag or model. Explicit originals come from the Philadelphia Fed's
[RTDSM](https://www.philadelphiafed.org/surveys-and-data/real-time-data-research/real-time-data-set-for-macroeconomists).
Its [terms](https://www.philadelphiafed.org/about-us/privacy-notice) describe
research use, subject to applicable third-party rights. A stored notice is
evidence for review, not a supplier permission or an approved learning policy.

| Feed | Observation semantics | Vintage semantics | Conservative research availability |
| --- | --- | --- | --- |
| `rtdsm_employ` / `rtdsm:EMPLOY` | SA monthly payroll level, thousands of persons | Monthly | Midnight in New York after the vintage month ends |
| `rtdsm_pcpi` / `rtdsm:PCPI` | SA monthly CPI index, source basis retained | Monthly | Midnight in New York after the vintage month ends |
| `rtdsm_ruc` / `rtdsm:RUC` | SA monthly unemployment rate, percent | Quarterly | Midnight in New York after February/May/August/November 15 |

These bounds are a deliberately delayed reconstruction of documented vintage
information sets. They are **not exact publication times**, first-release
values or operational Source/PIT admission. `published_at` remains null.
`vintage_reference_month` identifies the label's reference month; only RUC
has a separately documented vintage day. Do not infer an 08:30 timestamp,
first-Friday calendar or CPI announcement instant from a month label. A
vintage collected today cannot recreate a contemporaneously captured archive.

The pinned employment documentation describes deep-history publication-lag
assumptions, later-within-month corrections (including December 2002), unusual
revisions and omitted minor June 2003 revisions to pre-1990 observations in
July–October 2003 vintages. Preserve the source values and these limitations;
do not repair older vintages from a later column or describe this adapter as
an exact initial-release dataset. CPI monthly and quarterly vintages can
differ; the adapter chooses the monthly workbook explicitly. Unemployment's
quarterly vintages remain quarterly even though their observations are monthly.

## Original replay and archive

Only three registered workbooks are supported. ZIP/member, actual XML bytes,
depth, node/cell counts, shared strings, ordered reference months, vintage
labels and sheet identity are bounded. Formula cells, external relationships,
path traversal, duplicate columns and missing reference grids are rejected.
No workbook code or external link is executed. No Excel parser dependency or
source HTTP retry is introduced.

The original workbook is retained in full. The normalized research view keeps
at most 24 monthly observations ending with the expected latest reference
month **within each vintage**. Missing latest values stay missing. The default
vintage window starts November1998; an explicit earlier bounded window is
possible, subject to the documentation caveats and independent policy review.
Omitted early observations are outside the normalized view, not globally absent.
Full raw history remains available for a separately reviewed wider extraction.

`store_capture` binds the original, deterministic normalized gzip JSONL,
method-document original, rights-notice original, actual collection clock,
window, normalizer and shared-codec hashes. Existing
`shared-research-v1/macro-primary/{objects,generations}` paths are reused.
`read_generation` verifies those objects and recomputes every normalized row
from the workbook. It never substitutes an older capture. Code or object
changes refuse replay. `publish_capture` publishes data before the manifest
and re-reads the complete pairs through the shared transport.

## A4 integration and the learning hold

The data center accepts explicit `--vintage-generation-sha256` pins, with
`--vintage-archive-root` for a local existing archive or the current approved
Drive transport when omitted. They appear under `dated_vintage_sources` with
their clocks and references, separately from revised-current risk inputs.
They cannot satisfy native breadth/volatility/credit gates or overwrite newer
current macro context. Future captures are excluded into the audit. A broken
newest visible capture fails instead of falling back to an older success.

Learning validation recognizes only the three `rtdsm:` source IDs. An
externally reviewed binding must use `DATE_ARCHIVE_RESEARCH_ONLY`, bind
`vintage_manifest_sha256` to the reviewed source receipt, and include the
original rights-notice pin in `reviewed_rights_pins` as well as its reviewed
purpose evidence. The existing original resolver supplies the manifest,
workbook, method document, notice and normalized object. These references
share the 128-object/64MiB budget. Each submitted row must match the paired
original replay exactly; even a newly pinned policy cannot legitimize an
edited availability time. Existing FRED restrictions and government
forward-only bindings are unchanged. One source per logical series is retained.

Feature preparation reuses `a4_macro_learning.replay_features`: one release
sample per new reference period, with no daily multiplication of monthly or
quarterly snapshots. No actual price fit, accepted policy or forecast release
is created. Keep unverified-price learning disabled while supplier review is
pending. Recipe/code/release review, purge, outcome maturity and the complete
fourteen-target multiple-testing family remain mandatory.

Dated-vintage trials identify their source IDs and remain challenger proposals.
The current report can contain BLS points available earlier than these delayed
research bounds. Without a separately reviewed dated forward packet,
`forecast_release` still refuses RTDSM trials with
`A4_DATED_VINTAGE_FORECAST_CLOCK_ALIGNMENT_REQUIRED`.

The dated forward consumer accepts a macro-only learning payload (`prices={}`),
its original-bound input policy and original resolver. The fixed release policy
must independently include `forward_input_pins` and
`forward_input_policy_pins` (canonical decoded SHA256 identities). All workbook,
normalized, method and notice originals replay through the same bounded Reader.
The supplied observations must contain every visible row from those generations;
omitting a later column, null latest cell or inconvenient revision is rejected.
The initial consumer supports RTDSM-only trials, with the same logical/source
mapping as training; mixed current-source trials remain unsupported.

New trials bind `logical_sources` and `feature_history`: the complete actual
training calendar and sparse feature prefix's digest, including missing values.
The forward packet must reproduce that prefix exactly before applying a fixed
model. Appending a later release is allowed; changing a past feature through a
reissued archive requires a new independently reviewed trial. Existing trial
code/recipe checks remain in force; old trials are not relabeled or promoted.

Features are replayed on the same completed NYSE close grid as training. A new
weekend or post-close vintage cannot enter the preceding close. A monthly or
quarterly release produces only its original new-reference-period sample;
ordinary days with no new sample produce no new quantitative forecast. Current
BLS context never fills a missing dated feature. Provenance records the original
input/policy hashes, source mapping and actual feature-anchor close separately
from forecast creation time. Native risk readiness and evidence thresholds are
unchanged; a correctly replayed context alone does not qualify a model.

For a native A4 v2 request, a `learning_release` body may additionally contain
`forward_inputs` and `forward_policy`, with an independently pinned canonical
`forward_policy_sha256` in its input specification. Supply each needed archived
object as a hash-bound `learning_original` input; these objects never become risk
operands. Existing64-input/64MiB total and32MiB member bounds remain unchanged.
The legacy two-field release and v1 request remain compatible.

The cloud's separate `forward_request.json` uses the existing
`a4-learning-request-v1` structure (`inputs`, `policy`, `originals`). The externally
pinned main learning/release policy also binds its exact raw
`forward_request_sha256`. Its separate forward input policy contains no reference
back to the main policy, avoiding a self-referential hash. The auxiliary forecast
report remains separate from the original native report until its release is
explicitly included in that native request. No new collector, enable flag,
learning permission, accepted model or A3/A5 authority is created.

## 504-session preparation

`prospective_horizon_capacity` reports an optimistic arithmetic upper bound,
not observed price coverage, sparse-release sample counts or a backtest. Under
the existing 20-window rule, 504-session labels need at least 10,101 sessions
before allowing for OOS training and purging. The current 10,000-session cap
permits at most 19 such windows. A 2,639-row history permits at most five.
Do not lift the cap or reduce the evidence requirement merely to emit a result.

The released horizon family stays 1/5/10/21/63/126/252. A future 504 extension
needs an independently reviewed long-horizon design, actual qualified price
coverage, costs, maturity and uncertainty assessment. Historical scenario
descriptions can remain useful with limited evidence; they are not a
calibrated two-year direction forecast or QE-start probability.
