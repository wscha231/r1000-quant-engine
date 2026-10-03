# Evaluation V2 common-byte admission

The existing `tools/run_ab_result_verifier.py` has an opt-in precheck for supplied
common environment bytes. It is not a backtester or execution approval. With no
comparison options, the existing verifier behavior, multi-candidate interface and
economic gates are unchanged. Its existing eight-year gate differs from the
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
leaf aliases are rejected. Existing multiply linked report files are ambiguous
write targets and also block. Unsafe output geometry returns the bounded result
in memory/CLI only and never publishes even a blocked report. A safe separate
summary/CSV/report destination receives other blocked results with no stale
candidate rows. Geometry is checked again immediately before publication.
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
budget is 16 MiB, including arm declarations. Strict JSON also caps depth at 32
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
Its assertions remain active in normal and optimized Python modes.
