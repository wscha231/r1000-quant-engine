# A1 actual-source E2E audit — 2026-10-09

TASK_KEY: `R1000-A1-POST-READER-ACTUAL-SOURCE-E2E-V1-20261009`.
Parent: #590. Control: #448 / roadmap comment 6073268961.
Base: `11163fb3e30125359346102eb2b12c04aa52ae15`.
Source tree: `2e7ffae8551cacbd5ed0f8199c4734db35bdb35b`.
Result: **BLOCKED_ACTUAL_SOURCE_E2E**. `a3_ready=false`.

## Material correction to #590

#591 is merged into the audited master. Its Reader is reusable; the earlier
"waiting for #591" premise is superseded. This does not admit source data.
No Reader, registry, collector, scheduler, source pointer or economic code is
changed by this audit. This PR preserves the actual source findings only.

Current `ResearchDataReader` intentionally registers only
`ds.us.prices.daily` / `price-daily-v1`. SEC companyfacts cannot be represented
as OHLCV, and are not a compatible Reader generation. A SEC adapter is a later
bounded implementation only after its actual provenance is available.

## Actual bytes and execution boundary

| Object | Exact identity | Verification |
| --- | --- | --- |
| Latest Lake commit, generation20, Oct6 | `75fd9f6504010824127bdbbd8cdb611aa0d21fe7b0185981e70722d8242abf65` | 286 bytes, exact hash |
| Latest catalog | `63632beaa7563cbd770816b42bbd3e404cb382cb144d8263d5eb7fdbb02a6643` | 2,264,192 bytes, exact hash and commit binding |
| Comparison catalog, generation13, Sep27 | `ce0d64e6066018ce04869850c479d2eb944b2864bf16f97788f5e2166dd42530` | Existing retained original, exact hash; historical comparison only |
| Latest available execution | `10880eb916cd463ec4246f1f7aeb6d2384c40df632a30b4fca148e7aa6c09914` | 685 bytes; binds Sep27 commit `d2583562...`, not latest commit |
| Linked historical quality | `1c323ff5f765f237bee115c18aee7883a4fcdf1941abef1071c1f5848699863b` | 357,159 bytes, exact hash; PARTIAL_COVERAGE, historical PIT false |

All11 files in the currently listed execution folder were downloaded and
individually hashed. **None binds latest commit20**. The actual existing
`Lake.verified_execution()` receipt guard refuses with
`execution_receipt_missing_or_ambiguous`. The reproducer exercises that guard
on the real commit/receipt bytes without claiming full Lake constructor,
ancestor/catalog-chain, all-pack or linked-report verification.

Four exact original pack hashes and selected raw/normalized member hashes were
verified. A transient direct download HTTP403 was resolved through the returned
authenticated file reference; actual bytes became available. HTTP403 is no
longer the task's source-byte blocker. No provider was contacted or refreshed.

The existing history workflow [37876451731](https://github.com/wscha231/r1000-quant-engine/actions/runs/37876451731),
job113646069362 at audited master, was observed IN_PROGRESS. It moved from
cohort restore to step10, collection/persistence/verification at 03:12:23 UTC.
This task did not dispatch, rerun, cancel or modify it. Its pending result
cannot replace a completed matching receipt. No overlapping active Source/Data
code PR was observed; Main/control-plane writer comment6073409978 remains
separate. This PR uses only the new dated note, avoiding shared learning files.

## Small real engineering gold set

### NKE: actual source change and normal reconstruction

SEC raw issuer CIK `0000320187` matches NIKE, Inc.; the catalog ticker is NKE.
CIK verification proves issuer identity, not complete stable share-class/security,
historical lifecycle, currency/share basis or approved purpose/license admission.

| NKE evidence | Before, generation13 | After, generation20 |
| --- | --- | --- |
| Raw compressed object | `30ea8175508f932f98ccb452ca23c0063fb349f37b3b54a701d4e41fb19b5f8f` | `7c0f846323528ce24cfdc6d093645065a89383fc2e7468be31cfaefce8155bdc` |
| Normalized compressed object | `fedb31bf0f1d236a212a3be1f0dd3d37456e535d296bea6a00ea0a52d6644d2b` | `64f0adb93de39ce3c26502a1ee545c582fc2e1a87af5d88c7a94213acc3933f6` |
| Actual normalized rows | 11,803 | 12,004 |
| Retained collector clock | `2026-09-27T12:52:47.240941+00:00` | `2026-10-06T14:36:16.072676+00:00` |

The unchanged native `sec_rows` parser plus deterministic gzip/JSONL producer
reproduces both normalized SHA256 identities exactly, with zero rejected rows.
Its extraction identity equals the catalog's
`b4e4384aaaf6929d5b0613739d311d5805dd81215e56139f81509a660ad2d059`.

Exact record comparison yields **300 added /99 removed**, net201 rows; net201
is not a claim of201 new economic observations. The newly present accession
is `0000320187-26-000193`, form10-Q, filed date `2026-10-02`. It contains both
new-period actuals and repeated older-period facts. FY/frame/filing metadata
changes and new fiscal periods must not become same-period consensus revisions.
No new-period result is mislabeled as a same-key correction.

For period2026-06-01–2026-08-31, the retained raw facts include revenue
USD11,213,000,000, net income USD712,000,000, diluted EPS USD/shares0.48 and
operating cash flow USD135,000,000. These are source-audit examples, not current
valuation, financial-quality certification, complete cashflow/FCF or ER approval.
The original concept/unit/accession/period are preserved. Companyfacts supplies
`filed` as a date; it does **not** supply exact original publication,
strategy availability or acceptance time for these facts. Null clocks remain
null. Collector retrieval is not manufactured into earlier publication/PIT.

### NVDA: unchanged and adjustment-sensitive controls

CIK `0001045810`, entity NVIDIA CORP, raw compressed object
`bf3c4f971c3e21ee9ca8bcb87effc57d2cf127eceb246042821f81408723072d` and
normalized object `7b12780c616c954711891d761618502283809423e77745670c38b7b34a99cfbb`
are identical in catalogs13 and20. All16,956 normalized rows reproduce exactly.
New collector timestamps alone are **not** a material source-value delta.

Actual same-period FY2024 diluted EPS versions include11.93 in accession
`0001045810-24-000029` and1.19 in `0001045810-25-000023`. Share/adjustment basis
must be authenticated before comparing these versions. This audit does not
call it a90% earnings decline, a verified restatement or an admitted correction.

### Real failure and lifecycle controls

- The Sep27 execution/quality cannot certify Oct6 catalog20; latest receipt
  admission refuses on the actual missing linkage.
- Current cohort identity resolution marks HOLX `CIK_MISSING_OR_AMBIGUOUS`,
  `cik=null`, `lifecycle_review_required=true`. This is a real unresolved
  identity case, not a finding that HOLX delisted or failed financially.
- Historical quality is PARTIAL_COVERAGE with historical PIT/membership false.
  Neither this small subset nor valid hashes certify whole-universe G0/7Y.

## Readback, tests and authority

Two author-controlled read paths independently reconstruct from SEC raw and
decode the stored normalized member. Current NKE and NVDA bytes and row sets
are identical. They are **not** independent A6, merged Reader SEC readback,
or admitted eligible rows; admitted eligible rows remain0.

The actual-source audit reproducer was executed in normal Python and `python -O`.
Both return the same byte-identical JSON result and the expected blocked status;
18 named files/pack hashes were reverified in each run. Repeated modes do not
double the source/test count. A preliminary exploratory comparison was stopped
after an inefficient repeated-set construction; the linear comparison in the
final reproducer completed. No product defect or PASS is inferred from that
interrupted exploratory command.

The code tree stays identical to master. Fresh checks on this documentation PR
are recorded in #590/#448 after publication; #591's235/235 is historical and is
not relabeled as this task's CI. The reproducer is separately preserved with
the actual evidence receipt; no new synthetic Reader contract is introduced.

`provider_refresh_count=0`; `eligible_for_economics=false`;
`eligible_for_selector=false`; `a3_ready=false`.
No shared immutable generation was created, restored through the merged Reader
or promoted. No provider fallback, Fullrun, historical-universe certification,
official ER, Approved Target, paper/broker, production/public investment signal,
workflow dispatch or merge was performed.

## Minimal resume / independent A6 request preparation

1. Source/Data owner checks the existing collector's final matching
   commit/catalog/execution/quality and actual byte readback, without a blind
   rerun or replacing missing current evidence with historical success.
2. Ground one real issuer/security, explicit permitted purpose/license,
   publication/availability/collection precision, lifecycle and adjustment.
   Reuse retained raw; authenticate clock evidence via existing submissions,
   filing/IR or earnings hooks. Do not stamp unknown original clocks with now.
3. Only once those actual fields exist, add the minimal SEC research dataset
   adapter beside the merged price Reader, preserve its closed economic/selector
   authority, and build one content-addressed research generation. No pointer.
4. Read it through two separate merged Reader consumers, independently compare
   exact bytes/eligible rows, and pass the fact delta to the existing
   `candidate_reassessment_bridge` ACTUAL/FILING research contract. Missing
   fields must route to repair, not manufacture an A3-ready OBSERVED record.
5. Independent A6 verifies exact implementation head, actual source evidence,
   original clocks and license/basis, normal/-O and fresh CI. Until an admissible
   generation exists, the prepared request is **blocked-source evidence review**,
   not implementation/source/A3 approval. No self-issued CLEAN verdict.

Reusable lessons: receipt/transport-time changes are not new economic facts;
date-only SEC provenance cannot authenticate an intraday availability clock;
share-basis-sensitive EPS must not become an economic correction by value
comparison alone; immutable catalog storage does not imply completed execution.
These lessons are retained here and in #590/#448 for the Main learning owner to
append to the shared ledger after its active lease releases.
