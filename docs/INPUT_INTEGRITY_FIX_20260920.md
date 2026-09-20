# [PROJECT_HANDOFF] Legacy input integrity repair — 2026-09-20

Issue: [#462](https://github.com/wscha231/r1000-quant-engine/issues/462).
Repository: wscha231/r1000-quant-engine. Audited master:
`f20410549464e3f2557ae6d90ba8b20ee8bcc42e`.
Branch: `codex/input-integrity-20260920`. Scope: H1 current input admission.

## Verified facts

The September 12 report is historical. Master has advanced, but still contained
the synthetic universe bridge. PR415 remains draft/unmerged at
`e39387bbc442e4de35d771ee19ba7487c5683555`. Its PR Validation run34664643653,
job103474002105 failed the SEC candidate enrichment smoke (227/228 tests).
That SEC smoke passes locally on the audited master. Historical CI success
has not been relabeled as a new run.

A direct before/after probe on the same missing-score fixture showed:
score 0.7 -> null, capitalization $10B -> null, forward PE 20 -> null, and
missing percentile 0.5 -> missing. These are synthetic counterexamples.

## Implemented correction

| Defect | New behavior |
|---|---|
| Missing model score synthesized from Finnhub ranks | Keep every requested security in diagnostic inventory; no invented model score, sleeve or confidence |
| Fixed $10B cap, TTM PE labeled forward PE | Missing cap/forward PE stay missing; separate trailing PE diagnostic |
| Missing values treated as neutral | Preserve missing observations and genuine numeric zero |
| Partial coverage published as complete | Reject small/theme fallback cohorts; publish coverage/missing reasons and preserve prior CSV bytes |
| Preserved old CSV consumed after failed refresh | Revoke prior success at build start; blocked receipt vetoes reads; success receipt binds output SHA256 and is published last |
| Fresh prices mask old scores | Require current NYSE-session score/target and price dates plus aware availability; reject conflicting date fields |
| Invalid or unapproved input enters legacy consumers | Reject duplicate IDs, nonfinite/boolean scores, bad/conflicting prices, synthetic source, ineligibility, explicit valuation rejection and split quarantine |
| RS weakness alone emits swaps | Legacy suggestion API/CLI returns BLOCKED with no swaps and nonzero CLI status |

The shared guard is connected to advisor v1/v3/v4 CLI score loaders, the paper
executor target loader, Layer4 candidate loader and unified bridge publication.
The exchange calendar includes holidays and early closes. File mtime and job
timestamps do not stand in for observation dates.

PR415's bridge and 13 fixtures were inspected and reconstructed on current
master, then extended. Its collector/workflow/historical branch stack were not
imported. This supersedes only the overlapping bridge scope; existing branches
remain preserved.

## Validation

- 13 bridge methods + 28 current-input methods = 41 unique unittest methods.
- Existing 14 freshness cases + 3 SEC candidate cases also pass: 58 total.
- Reruns are not counted again.
- Includes a 1,118-name missing-score inventory and 1,000-row valid fixture
  publication/readback. These are schema fixtures, not live coverage.
- Tests cover stale/future/mixed dates, missing/naive availability, NYSE
  holidays/early closes, byte tampering, interrupted builds, stale retained
  files, quarantine, numeric zero and RS-only rejection.
- Compilation and explicit diff checks pass.
- Existing registered `tests/data_freshness_contract_smoke.py` executes both
  added suites. The frozen Tier1 registry and gate rules are unchanged.
- Broker/message dependencies in the target-loader test are stubs that fail
  if called. No actual provider, broker or message call occurs.
- Initial runs exposed local dependency/import omissions, corrected before
  the final tests. No credential or live collection was needed.

Remote exact-head CI/review and merge are separate from this local evidence.
Admission checks do not authenticate arbitrary data claims, certify valuations,
approve targets, or authorize trading.

## Remaining scope

| Item | Status / next evidence |
|---|---|
| Current whole-universe model scores | Not regenerated; restore admitted source/feature/model inputs and verify real output coverage |
| MU/NVT SEC accounting and TTM | No issuer adapter fix here; reconcile period, units, continuing operations, quarter vs YTD and filing availability |
| APH split; TSM ADR/FX/share basis | Explicit quarantine is honored; correct corporate actions/issuer conversion are not produced by this patch |
| Korean split-adjusted prices/KRW benchmarks | Separate kr-quant-engine work; no cross-market ranking claimed |
| 13F/Form4 freshness, consensus coverage | Not recollected; execution time must not replace source availability time |
| Transactional refresh/Drive accepted state | Not rerun or mutated; accepted-head verification and chronological recovery remain separate |
| CAGR/MDD, official targets, actual holdings | Not recalculated, certified or changed |

Legacy outputs without genuine dates/availability now stop explicitly.
Their producers must supply true observation metadata; stamping them with
today's date would be an invalid repair. RS-only swaps stay blocked until a
reviewed thesis/risk decision path exists. This is not a replacement selector.

Confidence: high for tested rejection boundaries; live recovery and issuer
valuation correctness remain unverified. Stop on missing, stale, conflicting or
ineligible input. Never fabricate scores or dates to restore a green status.


## Publication authorization history

Local implementation commit: f29d58566a5d90e06a6718962bac36e1d80e0264.
Automatic approval review rejected the GitHub push: it judged the short user
fix request insufficient authorization to publish changed source, tests and
internal documentation to the repository. No alternate upload or push was
attempted. A subsequent connected GitHub branch search returned no matching
remote branch. Issue462 exists, but this patch has no remote PR or CI run.
The user subsequently explicitly authorized publication of this prepared patch
to wscha231/r1000-quant-engine, PR creation, merge after code review and required
validation, and post-merge verification on 2026-09-20. The earlier authorization
blocker is resolved. Remote PR, exact-head CI/review and merge results must be
recorded from the actual GitHub evidence; authorization alone is not completion.

## PR463 exact-head review corrections

The patch was published as [PR463](https://github.com/wscha231/r1000-quant-engine/pull/463)
at `bd4d6070cd47d2e681b8ac8a971c8ef53a1bbd3b`, whose tree exactly matches the
validated local tree. Codex review identified three gaps, corrected together:

- Bridge reads require the coverage receipt by default; direct legacy producers
  use an explicit `legacy_source` mode, which cannot exempt named or marked
  bridge packets. The monthly artifact and single repository commit include
  both CSV and receipt, as do full-rebuild snapshots. Publication validates the
  copied pair and does not suppress missing-receipt or push failures.
- Score packets require aware `score_available_from` at or after feature
  availability/current close and no later than the decision time.
- The existing registered Layer4 regression now executes the API and CLI and
  asserts blocked, nonzero, no-action behavior instead of requiring RS evaluator
  wiring. Its registration and all merge gates remain unchanged.

Five additional methods cover these gaps: 63 focused checks (46 input/bridge,
14 existing freshness, 3 SEC) pass. The registered Layer4 regression also passes
in isolation. A broader local smoke run encounters missing sparse-checkout
fixtures and optional dependencies including yfinance; it is not reported as
passing. GitHub's fully provisioned exact-head validation remains required.

The second review identified four additional transport/runtime gaps. The local
Drive-mirror helper now copies verified packet bytes with a blocked destination
receipt during transport and publishes success last. Research Drive manifests
include and require both packet members when present and validate their hashes;
historical transport does not relabel rows as current. The daily workflow records
the retired Layer4 state as a no-action diagnostic instead of executing its
intentionally failing CLI. Explicit ignored publication paths use `git add -f`.
The bridge admits only the upstream `iwb_live` universe family with at least
1,000 names; historical-membership unions and other fallback sources are rejected.
That upstream label still includes its bounded IWB cache and is not a new
independent certification of index membership or live financial coverage.

Seven additional regressions exercise actual temporary-directory Drive copies,
interrupted copies, manifest admission, the daily Bash step, ignored-file staging
in a temporary Git repository, and historical-union rejection. Focused checks
now total70 (53 input/bridge,14 existing freshness,3 SEC), all passing. The
registered Layer4 and daily/monthly workflow regressions also pass in isolation.
No real Drive transport or daily workflow was dispatched as part of these tests.
