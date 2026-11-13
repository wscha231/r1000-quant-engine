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
research bounds. `forecast_release` therefore refuses RTDSM trials with
`A4_DATED_VINTAGE_FORECAST_CLOCK_ALIGNMENT_REQUIRED`. A source/clock-aligned
forward consumer needs its own implementation and independent release review
before these relationships can supply a current direction prediction.

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
