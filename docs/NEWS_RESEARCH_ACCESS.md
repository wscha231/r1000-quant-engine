# News research: executable source + shared capture reader

Implementation integration, 2026-09-19. Related: #456, #448, #433, PR #455.
This is RESEARCH_ONLY. A branch/green test is not a deployed pipeline or alpha result.

## One source path, no repeated user-PC installation

The initial P0-3 source modules and four regression suites were imported from
`news_event_p0_3_20260919.zip` (SHA256
`ef312256b8873ddd60403fa3c8f6b32c5997733ee0a2535761edbd92b5e210a6`).
The shared reader and manual cloud adapter reuse their parser, capture,
identity/admission and return contracts. No second pricing/selection engine.
The three historical package progress reports are left in their original archive,
not duplicated into source; this guide is the current integration entrypoint.

`research/news_event_alpha_v1/shared_reader.py` validates a manifest-pinned
capture and exposes at most five filing references, not investment picks.
`tools/read_news_research.py` reads an explicitly chosen complete attempt:

    python tools/read_news_research.py --attempt-dir <restored-run> --as-of <UTC timestamp>

A failed or missing terminal is blocked. This reader does NOT automatically
choose the latest successful run. Caller must read the actual latest attempt
when making a current-state claim; a selected old run is only a dated reference.
Raw data is passed through the P0-3 parser, never executed as instructions.
Expected returns/RS/theme breadth remain null; score contribution stays zero.

## Drive linkage

Existing folder: `1GdikTcHjAnhWLFXLiaVO4zcpUgetVFdH`.
Existing discovery file: `1i0f0cQ4BfreWiFJdMl7okO9kJkChOn08`.
Existing guide: `1SMAQnbWckguYEgOyGrvDpYeSWR18PQ_i`.
Server root is set to that exact folder and the existing registry must agree.
Never infer parity from two remotes both being named gdrive. No new Lake.
Existing `catalogs/commits/predictions` and paper/account heads are NOT written.

Manual captures use `source_captures/<GitHub-run>-<attempt>/`:
- STARTED.json before SEC fetches
- bundle/ with source export, report and SHA256 manifest
- TERMINAL.json only after upload check AND separate restore/reader check

These are SOURCE captures pending business/security/price/rights review, not
accepted model inputs. PARTIAL stays partial. Failure yields BLOCKED or an
unfinished attempt; neither can silently consume a prior successful batch.
Original source terms govern storage/reuse; byte integrity grants no rights.

## Cloud execution

`.github/workflows/news_research.yml` runs offline tests on PRs, without secrets.
No cron, no pull_request_target. Manual runs require master and exact reviewed
SHA. `inspect` only checks the selected Drive root. `capture` additionally
requires the phrase `capture-source-only`, explicit CIKs and date window.
Only the existing OAuth-form `RCLONE_CONFIG_GDRIVE` and `SEC_USER_AGENT` secret
names are used. Values are never printed. Service-account-only setups currently
block rather than being silently reconfigured. GitHub runner root/authentication
have NOT been tested by local mocked tests.

Bounded capture: at most 10 CIKs, 100 primary documents, 150 requests, 732-day
window. No historical ticker eligibility is invented. Review seed is not the
stratified 100-document economic-validation pilot. The existing local capture
supports resume. The cloud adapter now checkpoints verified plan/URL receipts
and objects; explicitly pinned continuation restores that cache and selects the
remaining documents instead of repeatedly selecting the first 100.
One workflow writer path, cancel-in-progress=false. Existing other SEC workflows
are not covered by a global shared IP rate limiter; coordinate before expansion.
No arbitrary code/ZIP is fetched from Drive. Existing pinned rclone release/hash
is reused from the durable-history workflow.

## Remaining gates

Exact-head independent review and all required CI precede merge. Then inspect
and a bounded real capture can be authorized; no automatic dispatch is part of
source publication. Actual price/security review, historical fit, TTL/150-30-5
research lifecycle, scheduled updates, and selector integration remain separate.
The original fit path is still blocked until a real reviewed receipt exists.
No trading, target, portfolio, champion or approved model weight is changed.

## 2026-09-19 operational lesson

Native Git networking in the chat sandbox failed DNS. Files were edited,
regression-tested and explicitly committed in an isolated local source scope;
only those committed bytes are published through Git data objects, retaining
the entire current master tree and recording matching blob IDs. This is not a
clone of the user's H worktree or a full-repository validation. Do not count
Python -O repetitions as extra tests. Source capture readback is not prediction
validation. Preserve both material-agreement and financing tags in multi-item
8-K fixtures, rather than silently reducing them to a bullish contract tag.

## 2026-09-19 continuation update and operational lesson

One existing workflow, no new scheduler or Lake. For a new capture provide
CIKs/window and leave resume fields empty. For continuation provide
`resume_from=<run_id>-<attempt>` and `resume_checkpoint=<SHA256 from TERMINAL>`;
leave CIK/start/end empty. Both modes still require exact current master SHA
and `capture-source-only`. The original collection plan/cutoff stays frozen.

- `source_checkpoint.py` verifies frozen plan, receipt URLs, CIK scope, raw bytes,
  timestamps, allowed fields, missing/orphan objects and immutable hashes.
- Common `source_captures/_objects/<SHA256>` stores resumable cache blobs once;
  each run's `CHECKPOINT.json` references them. Restoration copies only listed
  blobs, not the entire pool. Consumer bundles are still bounded per-run copies;
  not every duplicate byte throughout the existing publication layout is eliminated.
- `coverage_counts` splits indexed/captured/pending_download/missing_primary_path.
  Metadata completeness is independent of a primary-document request failure.
  'Complete' covers the specified frozen CIK/window only, not all market news.
- A partial run may have a verified checkpoint even when its reader is BLOCKED.
  That checkpoint permits continued collection, not analysis/model admission.
  No terminal or failed checkpoint publication means no automatic resume.
- Reusing a parent already continued by a child is blocked. This relies on the
  existing single-writer workflow and a bounded attempt-list check; it is not a
  distributed lock against arbitrary out-of-band writes. Incomplete children
  require inspection rather than silently forking from an older success.
- Relevant code bytes are fingerprinted. Unrelated bot commits do not force a
  full refetch; changing capture/validation code blocks resume pending reviewed
  migration. Export source_commit records the actual executing revision.
- New requests stop after 600 seconds (an in-flight HTTP request may finish);
  request/document/byte limits still apply. Numeric Retry-After is persisted and
  enforced across runs. Hard runner termination before durable checkpointing
  can still lose only that attempt's unpublished progress; no crash-proof claim.

The first-100 trap was reproduced using three synthetic documents and a budget
of two: the old second run kept two documents; the repaired run reaches three
with one new request. Independent fresh-workspace restore/reuse is covered by
offline tests. Actual GitHub OAuth, SEC access and remote Drive data readback
remain unexecuted. A 24-month multi-company shard planner, non-SEC history feeds,
company/market impact models and score/lifecycle consumers remain later work.
This update neither certifies historical PIT data nor changes scoring authority.
