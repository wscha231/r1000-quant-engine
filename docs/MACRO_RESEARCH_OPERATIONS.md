# Macro research operations

Status: implementation awaiting exact-head review and default-branch publication.
This is the bounded continuation of PR #413. Execution receipts determine what
actually ran. All exports remain RESEARCH_ONLY with selector weights set to zero.

## Connected lifecycle

`tools/macro_research_cycle.py` restores the previous verified checkpoint,
registers the attempt, refreshes 12 current histories and three ALFRED histories,
retrieves official release dates, compares economic records, reruns the fixed
336-test family, exports engine context, and publishes the next checkpoint.
The requested starting date is 2000-01-01; actual provider coverage is retained.

Raw data, normalized rows and receipts remain hash-addressed. Earlier versions
are not overwritten. A price row that ages out of FRED's rolling window remains
in the consolidated research history with its old receipt/raw hashes. Only
dates older than the new window are retained: internal missing sessions are
never patched with stale prices. Mixed retrieval dates remain current_only
research observations, not historical PIT or total-return certification.

This transport uses the existing source bundle format. It does not recreate
PR #411's proposed SQLite catalog or import an unreviewed branch. Repository-wide
experiment-census integration remains a separate gate for promotion evidence.

## Schedule and completeness

| Process | Configured frequency | Success evidence |
|---|---|---|
| SP500, NASDAQCOM, DGS2, DGS10, UNRATE, PAYEMS, CPIAUCSL, WALCL, WTREGEN, RRPONTSYD, SOFR, M2SL current histories | Daily 06:37 UTC / 15:37 Korea | Each response parsed, actual coverage recorded |
| UNRATE, PAYEMS, CPIAUCSL ALFRED archives | Daily full bounded history | Complete pagination and valid vintage intervals |
| Official calendars for those three monthly series | Daily, prior 30/next 90 days | Provider dates returned, date precision retained |
| Influence/horizon reevaluation | Each successful collection cycle | 336 comparisons with mature labels and previous-result comparison |
| Remote persistence and clean restore | Every publication and next-run startup | Referenced bytes and receipt dependencies verify |
| Model replacement or selector activation | No automatic schedule | Separate reviewed promotion evidence |

The daily refresh deliberately rechecks every selected series even when a
calendar says to wait. This small initial universe is bounded and catches
delayed releases and older revisions. A successful poll never confirms an
expected release. Only three official macro calendars are connected; the
others do not yet have verified release-completeness logic. Reports expose
latest observation dates, missing periods and missing price tail sessions.
Added, revised and removed records and changed vintage intervals are compared
separately from changed retrieval timestamps.

`macro_research_daily.yml` runs only on the default branch. A fixed concurrency
group serializes manual and scheduled writes; cancellation is disabled. Once
merged and operational, no chat session has to remain open. GitHub schedules
can be delayed/dropped and public repository schedules can stop after inactivity.
YAML alone does not prove liveness: inspect the last successful run and checkpoint.
[GitHub schedule contract](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule).

## Storage and recovery

The transport restricts destinations to the existing configured repository
Drive base plus `research/macro_technical_evidence/v1/pr-413` or `scheduled`.
The first is an isolated PR verification lane. Their chains are independent;
a PR checkpoint is not silently adopted as a scheduled baseline. No accepted
paper ledger, account, target, portfolio or broker endpoint is addressed.

The remote contains content-addressed `objects`, immutable `manifests`, an
append-only `commits` chain, and STARTED/FAILED/COMPLETED `attempts`. Publication
downloads the referenced objects to a clean directory and verifies hashes and
receipt dependencies before appending a commit. Interrupted uploads leave
unreferenced objects. Failed research bundles are archived when possible without
advancing the chain. A failed final journal write can happen after a successful
commit: inspect the chain before declaring nothing was saved. There is no
destructive sync or automatic deletion.

Snapshots are bounded to 10,000 files, 20 MiB per file and 512 MiB total. Before
reaching this limit, migrate reviewed history to the partitioned lifecycle;
do not discard old receipts to keep the job green. Rclone uses immutable copies
and downloaded byte verification.
[Copy contract](https://rclone.org/commands/rclone_copyto/),
[download verification](https://rclone.org/commands/rclone_check/).

One writer is required. The workflow serializes it. An out-of-band concurrent
writer may create a fork; chain validation then fails closed instead of choosing
by timestamp. Rclone/Drive is not claimed to provide atomic compare-and-swap.
Hashes establish integrity, not provider authenticity or immunity to remote
administrator deletion. No permanent-retention guarantee is asserted.

Existing `RCLONE_CONFIG_GDRIVE` or `GOOGLE_SERVICE_ACCOUNT_KEY`, optional
`GDRIVE_ROOT_FOLDER_ID`, and `FRED_API_KEY` are isolated to necessary steps.
Credentials never enter reports, Git or checkpoints. Whole-config and version
environment variables are excluded from rclone's option parser. Rclone 1.75.0
uses the checksum already pinned by the repository's preflight. Temporary
configuration is removed in an always-run cleanup. Remote sharing permissions
are neither changed nor certified. Raw index data is not attached to public
GitHub artifacts; check source redistribution rights and destination access
policy before sharing it.

Manual clean recovery after configuring temporary transport credentials:

```bash
python tools/macro_research_checkpoint.py restore \
  --remote "$MACRO_RESEARCH_REMOTE" \
  --root /tmp/macro-clean-restore \
  --report /tmp/macro-restore-receipt.json
```

The destination must not exist. Missing permissions, corrupt objects or broken
lineage stop recovery. To retry, dispatch `Macro research daily lifecycle` on
the default branch. A new attempt restores and verifies the accepted predecessor
first. There is no trading workflow rerun.

## Engine and OpenAI Developers interface

`reports/engine-context.json` exports per-index/feature/horizon effects,
confidence intervals, adjusted q-values, OOS errors and sample status, bound
to the exact evidence report hash. It sets `allowed_use=RESEARCH_CONTEXT_ONLY`,
`stock_selection_weight=0`, `eligible_for_selector=false`, and
`predictions_for_future_dates_available=false`. Verify the checkpoint before
reading it and inspect coverage/freshness. Existing selector engines are not
modified by this export.

The OpenAI Developers Agents SDK skill and
[official Agents guide](https://developers.openai.com/api/docs/guides/agents)
were consulted. A future SDK tool can expose this verified read-only context
with explicit input/output fields. This change adds no API call, key requirement
or deployed agent. Numerical validation owns the estimates; an AI explanation
cannot upgrade an insufficient sample or turn an association into a causal claim.
An actual SDK app needs a focused eval against its real agent path before use.

## Validation and activation

- Preceding head `b78bdd70ec25d3857741b7fec0a1195237740119` passed full Tier-1
  validation in run `34559216242`, job `103138297161`.
- New offline regressions cover clean restore, stale writers, corrupt/partial
  uploads, broken chains, path/symlink rejection, environment redaction, delayed
  releases, economic revisions, rolling price history and two successful cycles
  around a failed attempt. Synthetic fixtures are never remote-data proof.
- The PR pilot checks real configured Drive storage and clean download, then
  recomputes all 336 comparisons from restored raw inputs. Its
  `CHECKPOINT_SUMMARY` is the execution evidence; code alone is not success.
- The new suite is registered through the existing macro-input Tier-1 suite.
  The protected validator publication pin is unchanged.

Activation requires the exact final head to pass the new pilot, required checks,
independent review and the repository review-complete gate, then merge. The old
replay-workflow failure belongs to PR #408 and is not bundled into this feature.
After the first scheduled run, verify its COMPLETED journal and checkpoint;
until then, report scheduled operation as unverified.

Archive expansion, nonlinear/conditional tests, sector/theme/security PIT data,
costs, portfolio replay, frozen future predictions and model promotion remain
subsequent research stages. Negative first-screen results are retained and do
not justify permanent exclusion of every indicator.


## Remote transport finding, 2026-09-11

Run `34574014021` stopped reading back the just-uploaded manifest. Diagnostic
head `ae747b9adeac38677f9b70e52c120738a705bb87`, run `34574331469`,
job `103183261609`, reached full raw roundtrip verification, then encountered
a quota-class error reading the just-written commit. The acknowledgement can
fail after the remote commit exists: recovery must inspect and verify the chain
before retrying, not assume the earlier head survived. No accepted paper state
is involved. The fixed error classifier exposes no provider bodies or keys.

The transport now limits API requests to two per second with a burst of one.
Rate-limited reads and temporarily missing known hash-addressed files receive
a bounded exponential backoff; download/storage quotas and permission errors stop. It never retries
a write to recover an acknowledgement. This follows the provider's
[quota/backoff guidance](https://developers.google.com/workspace/drive/api/guides/limits).
The PR pilot additionally runs a complete subsequent collection/revision/
reevaluation cycle against the restored checkpoint, including its journal and
engine context export. Final success still requires its actual run receipt.

The later preflight (`e6898c696c28ac1363adc9967f644c7473e4c5b5`,
run `34574989846`, job `103185300025`) explicitly classified the provider
response as RATE_LIMIT, not missing data. Reads now have at most seven attempts
with 1/2/4/8/16/32-second plus jitter delays, spanning a one-minute quota window.
A `CHECKPOINT_PREPARED` line records the manifest and proposed commit after byte
verification but before publication, so an acknowledgement failure is traceable.
It is not a COMMITTED receipt. A failed cycle reports that remote reconciliation
is required, because a commit could exist even when its readback failed.


A connected Drive metadata check found one matching research folder and the
expected objects/manifests/commits children. The transport now resolves its
research folder once and pins that narrower folder ID for subsequent commands,
reducing repeated ancestor lookups while using the same credential and limits.
No account rotation, permission change or quota bypass is involved. A folder
listing remains metadata evidence, not proof that all stored bytes were restored.
See the [rclone folder-root contract](https://rclone.org/drive/#root-folder-id).

The folder-pinning probe (`5d81684b4fc33e7cd3906ae35013bda6b0035428`,
run `34575826929`, job `103187942626`) exposed another contract detail:
`lsjson --stat` can omit the filesystem root's directory ID. Resolve the named
research child from its parent's directory listing instead; require exactly one
matching folder and a valid ID. Missing IDs or duplicate names remain blockers.
A regression covers the actual parent-list shape and duplicate rejection.

The parent-list implementation passed folder resolution in run `34576081880`
(job `103188728261`), but the same manifest disappeared from a subsequent path
lookup after its immediate upload readback had succeeded. Known hash-addressed
file reads now retry the exact same path within the same bounded window. A
persistently missing file still fails; it cannot select an older head or create
a new genesis. New-namespace discovery does not use this missing-file retry.
