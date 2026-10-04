# Evaluation V2 common-byte admission

The existing `tools/run_ab_result_verifier.py` has an opt-in precheck for supplied
common environment bytes. It is not a backtester or execution approval. With no
comparison options, numeric verdicts, the multi-candidate interface and economic
gates are unchanged. Fresh default and opt-in reports both use the versioned
publication protocol below. Its existing eight-year gate differs from the
requested research window; this change does not resolve or weaken that gate.
The legacy verifier also trusts an explicit `window_gate_valid=true` before its
numeric fallback. Byte admission does not certify that claim or repair conflicting
economic summaries; that existing semantic boundary remains unverified.

Native schema `r1000-evaluation-v2-comparison-precheck-v2` requires 16 shared roles.
It reuses the prepared prototype's strict JSON, byte snapshots and common-context
comparison, adding three roles and a bounded local-file resolver. Prototype v1
and its 13-role context are rejected rather than described as full TEAM4-R2 parity.

| Native shared role | Requested comparison identity |
| --- | --- |
| `data_release` | market data manifest |
| `pit_availability` | separate PIT availability manifest |
| `eligible_universe` | historical universe manifest |
| `corporate_actions` | combined corporate-action **and delisting** manifest |
| `calendar` | trading calendar |
| `fx` | FX manifest |
| `benchmark` | benchmark manifest |
| `risk_free` | risk-free manifest |
| `execution_contract` | execution clock contract |
| `cost_contract` | cost/liquidity contract |
| `cash_accounting` | cash accounting contract |
| `evaluator_source` | canonical evaluator source bytes resolved from its declared code identity |
| `mission_contract` | mission contract |
| `reference_initial_capital` | reference initial capital contract |
| `decision_clock_schema` | decision clock schema |
| `metric_contract` | additional explicit common metric conventions |

The context has exactly `schema`, `window_start`, `window_end`, `base_currency`,
`initial_capital`, `official_metric_mode`, `data_scope` and `shared_refs`. Capital
is a positive finite number, not a broker balance claim. Dates are valid ordered
ISO dates. The official mode remains `broker_ledger_next_close`. Data scope is
`SYNTHETIC`, `HISTORICAL_RESEARCH` or `FORWARD_RESEARCH`; those are declarations,
not independently verified classifications. `shared_refs` contains exactly the
16 roles above, each with `artifact_id` and lowercase SHA256 of actual supplied
bytes. A Git commit SHA is not substituted for a source-byte SHA256.

Each arm JSON has exactly `schema`, `role`, `context_ref` and `strategy_ref`.
Roles are `CONTROL` and `CHALLENGER`. Both contexts must resolve to the same exact
bytes and the separately expected context hash. Strategy references are resolved
and hashed separately; differing strategy policies are allowed. Declared strategy
bytes are not proof that those policies produced the supplied result directories.

Opt in with all four options:

- `--comparison-admission-root`: explicit caller-selected immutable artifact bundle.
- `--comparison-control-arm`: flat ID of the control arm JSON in that bundle.
- `--comparison-challenger-arm`: flat ID of the challenger arm JSON in that bundle.
- `--expected-context-sha256`: context hash independently pinned by the caller.

The pin is supplied directly by API/CLI; there is no third contract-file option
and no default hash derived from either arm. The caller must obtain it from an
independently frozen comparison contract. The requested `comparison_spec.json`
with null identities and `REQUESTED_RESEARCH_SPEC_NOT_ADMITTED_CONTRACT` is not an
admitted executable context. C0 must resolve verified identities separately.

This opt-in invocation accepts exactly one candidate result directory. Use the
existing portfolio selector and separate invocations for distinct arm pairs.
Partial options, missing or malformed pins and zero/multiple candidates block
before legacy result collection. API `run()` returns `blocked_comparison_admission`
with a bounded reason; CLI exits 2. Before admission or legacy byte reads, physical
output paths must be separate from the admission bundle: equal, descendant and
ancestor directories, case aliases, symlinks/junctions into the bundle and report
leaf aliases are rejected. Existing endpoint/ancestor device and inode identities
also bind aliases when POSIX path normalization preserves case spelling. The
nearest existing output ancestor is checked for a missing output directory;
disjoint missing destinations sharing an ordinary parent remain valid.
Existing multiply linked report files are ambiguous
write targets and also block. Unsafe output geometry returns the bounded result
in memory/CLI only and never publishes even a blocked report. A safe separate
summary/CSV/report destination receives other blocked results with no stale
candidate rows. Geometry is checked again immediately before publication. If
that final check fails, `run()` returns an empty bounded blocked payload with
all authority false on both admitted and initially blocked paths, without
retrying publication. The standalone publisher still raises its bounded
`AdmissionError` before writing to an unsafe destination.
Publication anchors every existing output path component; the opt-in path also
retains the native resolver's actually admitted root device/inode through legacy
result collection and publication. A missing, moved or replaced root cannot be
substituted by a surviving parent or a new directory at the original spelling.
Publication anchors every existing root/output path
component before creating directories or report files. POSIX uses directory
descriptors, no-follow exclusive temporary files and descriptor-relative
replacement. Windows uses native listing/traversal handles denying write/delete
sharing, then exclusive `CREATE_NEW` file handles; attribute-only handles are
insufficient. Existing leaves are opened for identity and cleanup only, never
truncated. Windows writes through each new exclusive handle and deletes only
the exact held owned handle on failure. A new occupant winning a `CREATE_NEW`
gap is preserved without deletion or retry. Unsupported native operations block.

This is not an atomic four-file transaction. The original CSV, Markdown and
`summary.json` names remain; all three installed anchored identities and expected
serialized bytes must be verified. Each report is at most 1 MiB. The held stage
descriptor alone cannot bind a POSIX source-name replacement. The summary uses
`ab-result-verifier-publication-v2` and `comparison_publication` with exactly
`schema=r1000-ab-comparison-publication-v1` and a fresh 32-character lowercase
hex generation for every invocation, including default calls and retries.

After all report/source/output checks, the publisher stages the fixed fourth
leaf `comparison_publication_complete.json`. This completion witness has exactly
`schema`, the same `generation`, and `reports`: exactly the original three names,
each with exact `bytes` and lowercase SHA256. Its staging bytes are verified;
final witness installation is the commit attempt. The final fallible delivery
step verifies its installed identity and bytes. There is no later source or
geometry rejection. The witness receives the same anchored, exclusive,
no-follow and single-link protections as the reports. POSIX late leaf reopens
use nonblocking descriptors and verify regular type/device/inode before reading,
so a regular-to-FIFO substitution needs no writer to return a bounded failure.

A precommit error returns empty blocked evidence, `current_receipt=false`, and
CLI2. Windows ordinary partial failures clear held owned files. Portable POSIX
cannot conditionally unlink an inode, so it preserves potentially raced names
and reports `OUTPUT_PUBLICATION_CLEANUP_INCOMPLETE`. A retained positive summary
is uncommitted without a matching witness. The publisher never recursively
retries into retained names or erases foreign bytes to manufacture rollback.
An error during witness installation/readback instead returns empty bounded
`comparison_publication_uncertain`, `current_receipt=null`, and CLI2: delivery
may already have committed. Potentially committed reports/witness are preserved.
A readable valid witness can establish a completed file receipt despite this
delivery uncertainty. A verified acknowledged publication, including a report
of blocked admission, has `current_receipt=true`. These states grant no new
comparison, promotion, production or economic authority.

The existing queue-closure reader now requires a verified witness for new reports
and for any summary carrying comparison/current-receipt/publication indicators.
It hashes the same raw summary bytes from which it parses candidate rows, before
adding `_summary_path`, and checks the exact report membership, sizes, hashes,
fresh generation and immutable file snapshots. Missing, partial, stale,
malformed or mixed-generation states expose no candidate rows. Unsupported or
stripped required new metadata never falls back to historical consumption.
Historical plain v1/no-version summaries without any new/comparison indicator
retain ordinary legacy behavior within the 1 MiB summary cap. The consumer checks
the descriptor size before any summary read, allocation or JSON decoding, for
every protocol version. Oversized historical plain summaries are now ineligible
for queue transitions; they have no unbounded legacy fallback.
Historical opt-in summaries without a witness
are ineligible for queue transitions. A complete untouched prior receipt remains
distinguishable from a failed retry; file existence alone proves neither.

Post-verification resource-close errors produce bounded cleanup-warning
telemetry without demoting committed evidence. Teardown never retries a failed
close against a potentially reused descriptor. Persistent IO failures and a host
actor able to forge all files remain outside an atomicity or OS-sandbox claim;
the reader admits only a coherent verified snapshot of the declared receipt.
Tests assert that each injected publication phase is reached. Actual Windows
locks, junctions and handle deletion are tested locally; actual POSIX operations
require Linux validation, and no macOS execution is claimed.
Status telemetry catches only stdout `OSError` (including broken pipes); it
preserves the installed valid receipt and API/CLI outcome. Publication failures
still return blocked evidence and are not swallowed as telemetry.
Telemetry flushes immediately and closes only a failed original process stdout
to prevent a buffered shutdown flush overriding the CLI exit code. Caller-owned
redirected streams are preserved; an already closed stream receives no telemetry.
Matching admission continues through
the existing result verifier and cannot override any economic or mission gate.

Artifact IDs are flat ASCII `[A-Za-z0-9][A-Za-z0-9_.-]{0,199}` names. Separators,
drive/stream syntax, trailing dots and Windows device aliases are forbidden.
Root and ancestor links/junctions/reparse points, nonregular files, missing files,
root replacement and file/descriptor identity changes fail closed. The resolver
checks size before reading, binds actual file identity before/after the read and
revalidates root/leaf identity on native cache hits and after the final comparison
read, including previously read leaves. It returns no provider/OS exception text.
Native `resolved_bytes`/`resolved_artifacts` report the resolver's actual bounded
reads, including the two preloaded arm declarations. Repeated flat artifact IDs
are charged once; distinct IDs are separate reads even when physically hardlinked.
The generic callable API receives arm dictionaries in memory and reports only
artifacts it actually resolves, without inventing arm-file reads.
Maximum blob size is 1 MiB; total read
budget is 16 MiB, including arm declarations. Each native read is capped by the
observed file size, remaining blob allowance and remaining aggregate allowance;
no sentinel byte is read beyond those limits. Actual bytes are charged after
each read, including partial bytes consumed before a later error. Final size and
identity checks detect raced growth even when the read cap prevents consuming it.
Strict JSON also caps depth at 32
and nodes at 50,000, rejecting duplicate keys, nonfinite values and malformed UTF8.
Use compact immutable manifests for large datasets; this does not inspect every
referenced dataset object's provider/PIT semantics.

The root is a caller-selected read boundary, not an OS sandbox or a defense
against a malicious actor controlling the host. The module reads a bounded byte
snapshot; it authenticates neither the caller pin nor a provider. On Windows,
descriptor comparisons use explicit birth time rather than deprecated ctime,
while retaining file ID, size and modification-time checks. Python documents the
Windows timestamp distinction in its [os stat reference](https://docs.python.org/3.14/library/os.html#os.stat_result).

A matching result is `BYTE_COMPARABLE_RESEARCH_ONLY`. All output paths retain:
`g0_certified=false`, `economic_comparison_ready=false`,
`champion_promotion_allowed=false`, `public_publication_allowed=false`,
`fullrun_allowed=false` and `target_paper_broker_mutation_allowed=false`.
Production and live trading remain disabled. Enumerated unverified domains are
provider authenticity/public availability; PIT universe/data completeness;
executed versus declared code; execution/cost/cash/corporate-action reconciliation;
and OOS exposure/independent review. Matching bytes cannot certify provider or PIT
correctness, calendar semantics, economic outputs, approval or true forward use.

The native `tests/evaluation_v2_admission_smoke.py` suite runs through the existing
registered A/B smoke hook; no gate/validation registration file is changed.
Its assertions remain active in normal and optimized Python modes. Geometry
fixtures include actual Windows aliases and portable POSIX spelling simulations
using filesystem identities; they do not claim execution on macOS.
