# Run287 source archive recovery — 2026-09-10

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

The eight offline tests passed: archive identity, manifest-only rejection,
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
