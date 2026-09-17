# Run287 source archive recovery — 2026-09-10

## Verified result, not a new backtest

[Source audit run 34450814925](https://github.com/wscha231/r1000-quant-engine/actions/runs/34450814925),
job `102785917503`, succeeded on audit source
`7f6467db083bd6175f502df5295a71c993fd9df2`. It opened the original ZIP inside
Actions and verified all **369,243,166 bytes** against the frozen SHA256.
The original failed run remains failed. Its ZIP contains 1,391 files totaling
1,349,507,015 expanded bytes. The aggregate JSON and report-artifact identity
are retained in `docs/run287_source_recovery_evidence.json`.

| Actual inspected input | Result | Consequence |
|---|---|---|
| Raw and SEC-enriched candidate books | Each 47,435 rows, 981 tickers, 85 decision dates, 2019-05-31 through 2026-05-29 | Candidates do not extend through the requested 2026-09-09 close. |
| Official Main / Concentrated targets | 1,207 / 545 rows, 317 / 188 tickers, 86 decision dates, through 2026-07-02 | These are archived targets, not new USD100k strategy decisions. |
| Frozen six-file source contract | Five expected member hashes matched; macro Parquet absent at expected suffix | Recover the exact separately stored macro bytes; a same-name file is insufficient. |
| Candidate provenance | `feature_available_from` and `valuation_price_cutoff_date` absent from both candidate books | Zero detected future rows cannot certify PIT when the columns are absent. |
| Recognized Parquet price-cache directories | Zero files, one other Parquet in the ZIP | A price manifest is insufficient to reproduce fills. Other formats require separate inspection. |

Current `full_rebuild_manual.yml` uploads the cache manifest, not raw price
Parquet files, in the official evidence artifact. The source run's collector
and engine cache logs both report cache misses; their post-save steps were
skipped. Do not assume the original run created a recoverable Actions cache.

Additional read-only Drive inspection on 2026-09-10 found a separate
`run287_exact_static_archive_v1.zip` (38,646,212 bytes, modified 2026-07-14).
The existing repository builder specifies 363 price-map files, and the
operating workflow pins its ZIP SHA256 to
`66ca4b6a6a61cb7e9a3a47e2f6d26aa42f30a9b96a25d07699c6cdeb8faf1d84`.
The extended [run 34452252116](https://github.com/wscha231/r1000-quant-engine/actions/runs/34452252116),
job `102790421533`, subsequently hit that cache and **verified the entire ZIP**
on source `9179ec46d20bd4ba9074b6a1e4c3cf946b0f8b02`. Its 388 members include
363 dated price-cache Parquet files totaling **1,091,464 rows**, all ending
2026-07-10. Earliest observed history is 2011-03-07. The latest individual
start date is 2025-02-13: this intersection is not a new permissible backtest
start and does not prove a gap; listing dates and session coverage must be
checked per security. The cache is a frozen selection substrate, not proof of
historical universe membership or delisting coverage.

The original ZIP's alternate-format audit found 914 CSV files with zero
date-plus-close header candidates. Its one other Parquet has 1,797 rows,
2019-05-09 through 2026-07-02, no close column, and a hash different from the
missing macro anchor. The static ZIP's two non-cache Parquets likewise do not
match that macro hash. No original raw price history was recovered from those
alternate members. Opaque formats were not executed or deserialized.

The audit restores **only that existing exact cache key** with
`actions/cache/restore`; it never saves a cache or runs the daily workflow.
No Drive credentials are introduced into PR execution. Cache absence is an
explicit `SOURCE_NOT_AVAILABLE`, and a wrong hash is a failed source audit.

The mutable Drive cache manifest, modified 2026-09-05, declares 80 cached
tickers, a 400-ticker book, maximum date 2026-09-04, and common end 2026-07-02.
Its folder's bounded first page contains 99 Parquet files plus the manifest;
neither that partial listing nor the manifest certifies the folder's complete
coverage. A same-name macro file exists but was modified 2026-05-26, so it
cannot be silently substituted for the pinned July source. Streamed file
references have not materialized usable bytes in the workspace. Private Drive
identifiers, transfer references and raw source payloads are not published.

Remaining gates: recover the pinned macro input and historical
release/availability evidence; establish
the full historical investable universe including lifecycle/delistings; extend
price/corporate-action/FX and decision inputs through 2026-09-09; then run
source-only and post-book preflights. Historical quality/H1 inputs must be
contemporaneous. The initial capital remains USD100,000; no current research
judgment is copied backward and no new CAGR/MDD/Sharpe is claimed here.

The user requested continued real-data recovery and baseline reproduction after
PR #409. Its head `3eb068e76d676ec3fc75288b645db8448615aa2d` passed PR Validation
`34435823730` and Portfolio System Guard `34435823724`. It remains unmerged.

A fresh connector download again returned an authenticated file reference, but
its transport host `sdmntprcentralus.oaiusercontent.com` returned HTTP 403 to
the workspace. No original ZIP bytes were validated locally. This is distinct
from the GitHub artifact's existence and its unexpired state.

## Recovery path

`.github/workflows/run287_source_archive_audit.yml` downloads the fixed original
artifact **inside GitHub Actions**, where `github.token` has `actions: read`.
It uses no provider secrets, Drive credentials, broker connection, model,
accepted-ledger writer or full-rebuild command. Same-repository PR changes to
this audit run the job; fork code does not receive this execution. Manual
dispatch remains available once the workflow is on the default branch.

Frozen source:

- repository: `wscha231/r1000-quant-engine`
- run: `28725350727`, head `15176b588d5bb0792bce1df6367758d795a8a33a`
- artifact: `8088582521`, `369243166` bytes
- SHA256: `ebdbbe7e764b735ca129f662c42ec80b68659f4e3196b5a364cf32c506c4c818`

The source run previously failed. A verified archive is recoverable data, not
evidence that its pipeline/backtest succeeded. File-level expected hashes reuse
`docs/run287_next_single_ab_readiness_contract.json`; regression checks prevent
those copied constants from drifting from the existing contract.

The standalone reader validates the complete ZIP identity before reading
members, rejects unsafe/duplicate/symlink/encrypted entries, and never extracts
or executes archive code. It streams candidate/target CSV date and provenance
coverage, checks expected member hashes, and scans actual cached Parquet date
columns. A cache manifest alone is not a price observation. Daily gaps,
lifecycle coverage and intraday PIT still require the existing preflights.

Only bounded aggregate diagnostics are printed and retained as a report
artifact. No raw prices, account rows, provider/config bodies, original ZIP,
download URLs or credentials are uploaded. Original payloads remain temporary
runner files. Metric JSON values, when present, are explicitly **reported
historical values**, not independently recalculated performance.

## Commands and tests

```sh
python tests/run287_source_archive_audit_smoke.py
python tools/run_pr_validation.py --only clean7y_window_preflight_smoke --quiet
python tools/audit_run287_source_archive.py --download \
  --zip "$RUNNER_TEMP/run287-source-audit/source.zip" \
  --output "$RUNNER_TEMP/run287-source-audit/report.json"
```

The initial eight offline tests passed: archive identity, manifest-only rejection,
date/provenance coverage, actual Parquet scanning, traversal/duplicate/symlink
rejection, ambiguous anchors, sensitive-field suppression, and contract hashes.
The existing registered clean7y suite calls them; no protected runner pin,
required check or promotion gate is changed.

Local integration caveat: the registered clean7y suite reached an existing
all-book missing-file assertion and failed (exit 1). A diagnostic trace observed
the deliberately removed official CSV fixtures reappearing across a child
preflight invocation. Direct in-process execution did not reproduce that write.
Its cause is not established; do not relax the assertion or claim the entire
suite passed. The clean GitHub runner's exact-head validation remains required.
The standalone archive reader's eight tests and workflow syntax/permissions
checks passed independently, allowing the separate read-only source audit.

This change implements source inspection only. `AUDIT_COMPLETED` is separate
from `research_replay_ready`, `historical_pit_certified`, and performance
recalculation. The next step uses actual audit coverage to select the missing
source path, then runs source-only and post-book preflight before any baseline
reproduction. A new performance result is never manufactured from old summary
metrics or renamed current snapshots.

The extended audit's eleven regressions passed locally and in run 34452252116.
It inventories bounded CSV
headers without publishing unknown column names or rows, scans every Parquet
even outside recognized cache folders, tests the separate static source
identity, and never decodes pickle/opaque executable formats. Header similarity
alone remains unverified coverage. Guard passed for the extended source head;
full PR Validation was still running at the observation. This does not resolve
the separately recorded local integration-test caveat. No full-suite success or
independent review is claimed.
