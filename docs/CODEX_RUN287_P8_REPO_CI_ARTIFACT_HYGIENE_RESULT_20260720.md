# Run287 P8 repository, CI, and artifact hygiene result

Status label: `ACTIVE_REPOSITORY_POLICY`

## Result

P8 replaces the ordinary PR lanes' dependency on the 581 MB canonical rebuild
directory with a 26-file deterministic fixture. The payload is 4,629 bytes;
including its manifest it is about 9.4 KB. Every payload file is locked by
relative path, byte count, and SHA-256. The fixture reproduced all four fast
consumers: AutoLearning v2, orchestrator replay, portfolio goal search, and
Portfolio System Guard with zero hard errors.

The repository's existing large history was not deleted or rewritten. At the
start of P8, the tracked tree was 6,838,888,405 bytes across 11,737 files and
the Git pack was about 2.59 GiB. `cloud_results/` accounted for about 6.81 GB
of the checked-out tree. P8 prevents growth; shrinking history is a separate
destructive migration and is not authorized.

## Enforced contracts

- PR validation and Portfolio System Guard sparse checkout no longer includes
  any `cloud_results/` path.
- Core Tier-1 baseline consumers use
  `tests/fixtures/run287_canonical_baseline` and its manifest.
- A custom/manual baseline without a complete compatible manifest returns
  `UNSUPPORTED_BASELINE_PATH`; there is no silent fallback.
- External artifacts are trusted only after every declared file's size and
  SHA-256 matches and no undeclared payload file exists.
- PR changes adding a `cloud_results/` blob, a dated/failed runtime output, or
  a non-fixture blob above 2 MiB are blocked. The check is report-only and
  never deletes files.
- `PR Validation (Fast)` now runs on `pull_request` and manual dispatch, not
  both branch push and pull request for the same SHA. Pull-request coverage is
  unchanged while the redundant same-SHA validator is removed.
- Generated/review evidence is classified in
  `docs/run287_evidence_status_registry.json`; unlabeled runtime output is not
  canonical.

## Measurements

| Measurement | Before | P8 result |
|---|---:|---:|
| Tracked Git tree | 6.84 GB / 11,737 files | historical bytes preserved |
| PR baseline subtree | about 581 MB / 1,104 files | about 9.4 KB / 27 files including manifest |
| Core hidden dated baseline dependencies | 3 consumers | 0 |
| Same-SHA fast validation jobs | 2 | 1 trigger path |
| New dated/full runtime artifact bytes | not guarded | 0 in this change; blocked in future PRs |
| Fixture checksum | path trust | 26/26 files trusted |

The pre-change GitHub checkout took about 20–21 seconds and duplicate fast
validators took about 224–255 seconds each. Post-change runner time is recorded
by the P8 PR checks; it must not be inferred before the check completes. The
complete local Tier-1 suite passed 189/189 in 348.21 seconds, and repository
pytest passed 129/129. `pytest.ini` also prevents local `_tmp_tests`, runtime
outputs, and legacy artifacts from being mistaken for product test suites.

## Restoration contract

A large artifact manifest uses schema `run287-artifact-manifest-v1` and must
contain source commit, source run ID, generated time, retention policy, restore
command, privacy/safety classification, and an exhaustive file list with sizes
and SHA-256 digests. Restoring bytes is not enough: verification must return
`TRUSTED` before any replay or scorecard reads them.

## Scope and safety

This is infrastructure integrity work, not a new alpha result. Official
generated-book metrics remain Main `34.4032% / -25.3629%` and Concentrated
`49.0968% / -22.9560%`, with evidence through 2026-07-10. No fullrun was run,
and production/live trading remains disabled.
