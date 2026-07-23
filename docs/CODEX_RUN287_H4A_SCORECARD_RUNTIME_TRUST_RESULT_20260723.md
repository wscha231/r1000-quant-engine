# Run287 H4a scorecard/runtime trust result

Date: 2026-07-23

Scope: Issue #315 H4a only

## Result

The operating scorecard now derives trust from immutable source hashes and the
actual paper-ledger directory manifest. A tracked boolean is not accepted as
runtime evidence.

- The nine historical P3-P6 sources previously referenced from ignored
  `_tmp_tests` paths and the fixed 2026-07-10 forward summary are committed under
  `data_static/run287_operating_scorecard_sources_v1`.
- `manifest.json` binds every canonical source id, path, and SHA-256. The
  registry also pins the manifest SHA-256.
- Historical, current-paper, and true-forward integrity errors are attributed
  to separate trust lanes. A current-paper fault cannot relabel historical
  performance evidence.
- Global `scorecard_trusted` is true only when all loaded sources are intact,
  the current paper summary exists, and `snapshot_integrity.json` verifies the
  complete paper directory.
- `verified=true`, `status=PASS`, and similar payload fields are ignored as
  trust evidence.
- The tracked promotion evidence now keeps `scorecard_trusted=false`; H4b must
  overlay the runtime-verified scorecard result after ledger integrity and
  outcome resolution.
- A missing or inactive P6 prediction head now produces an append-only
  `BLOCKED_PREDICTION_HEAD_INTEGRITY` report and head audit CSV instead of an
  exception with no diagnostic artifact.

## Fixtures

The focused fixtures prove:

1. a complete paper directory manifest produces runtime `VERIFIED`;
2. absent paper evidence remains `UNAVAILABLE` and cannot make the scorecard
   trusted;
3. a forged `verified=true` document is rejected;
4. current-paper errors do not poison the historical headline lane;
5. the committed source registry contains no `_tmp_tests` path and its bundle
   manifest verifies all ten canonical sources;
6. a missing prediction head writes a blocked summary without running any
   downstream outcome evaluation.

## Validation

- Candidate-gate stability smoke: PASS.
- Operating scorecard smoke: PASS.
- Promotion gate smoke: `9/9` PASS with tracked scorecard trust fail-closed.
- Repository pytest: `129/129` PASS.
- Full PR validation: `191/191` PASS in `715.88s` on the final local
  follow-up head.
- Python compilation and `git diff --check`: PASS.

## Exact-head review follow-up

The first exact-head Codex review identified two valid provenance gaps.

- The bundle verifier compared manifest and registry declarations without
  hashing each referenced source file. It now requires every source file to
  exist and match the manifest SHA-256 before reporting `VERIFIED`.
- Six JSON declarations were based on their former CRLF bytes even though the
  committed canonical blobs are LF-normalized. The bundle manifest and source
  registry now pin the actual LF blob hashes, and the manifest hash is updated.
- Source-specific bundle errors are attributed to the registry source's
  evidence lane. A true-forward-only path or hash error no longer relabels the
  historical headline as untrusted.
- Missing and duplicate bundle entries retain their source id as well, so a
  true-forward-only source-set defect stays in the true-forward lane.
- Raw manifest hash drift no longer short-circuits member inspection. When the
  parsed delta is source-scoped and no global structural fault exists, the
  manifest mismatch retains those source ids; parse/global faults still block
  every managed lane.
- A missing or blank registry pin for the bundle manifest is a global trust
  failure; member declarations and file hashes cannot substitute for the
  immutable manifest SHA-256.
- Canonical source and manifest paths are resolved before trust. Required
  `ABSORBED_SOURCE` rows are selected independently of their path string, and
  any resolved path outside the canonical bundle root fails closed.
- Current-paper trust now requires the loaded summary and canonical
  `snapshot_integrity.json` to share one directory, and the verified manifest
  must contain the summary's exact relative path and SHA-256.
- A P6 summary with a blocked status, explicit invalid-for-absorption flag, or
  explicit downstream-evaluation false flag blocks the historical lane and
  suppresses any stale companion selection metrics.
- Any required absorbed source rejected by bundle verification is removed from
  the usable source set and marked `BUNDLE_INTEGRITY_ERROR`; its bytes cannot
  remain visible as `AVAILABLE` metrics merely because its registry hash
  matched.
- P6 companion metrics are suppressed whenever the required P6 summary is not
  verified, including missing, hash-mismatched, and unparsable summaries.
- Current-paper values are emitted only after the exact summary path and hash
  are bound by the successfully verified ledger manifest. A failed binding
  leaves every paper metric explicitly `UNAVAILABLE`.
- New regressions mutate source bytes behind unchanged declarations and inject
  true-forward-only bundle path and source-set mismatches. All fail closed in
  the intended lane.
- Additional regressions cover path traversal from a required absorbed source,
  a paper summary outside the verified ledger directory, and a blocked P6
  summary paired with stale metrics. Final follow-up regressions also prove
  that bundle-rejected sources, unattested paper values, and P6 metrics whose
  required summary failed verification cannot leak into the scorecard.

## Safety and next gate

This branch does not reorder the daily workflow and does not perform dynamic
21D/63D/126D promotion overlay. Those remain H4b.

- Fullrun executed: false.
- Durable catch-up executed: false.
- Production activation allowed: false.
- Live trading enabled: false.
