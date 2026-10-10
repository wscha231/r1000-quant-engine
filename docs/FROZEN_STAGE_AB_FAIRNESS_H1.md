# M3 Frozen Stage A/B all-source H1 contract — 2026-10-10

Task: `R1000-M3-STAGEAB-FROZEN-ALL-SOURCE-FAIRNESS-H1-20261010`.
Author base: `11163fb3e30125359346102eb2b12c04aa52ae15`.
Status: contract-only, **WAIT_INPUT**, no actual Stage A/B fairness certificate.
User-authorized Main single writer; P1-B PREP #448/6064846916 reused.

## Boundary and reuse

`tools/frozen_stage_ab_fairness.py` is a bounded offline adapter and independent
byte reconstructor. It has no scheduler, provider, backtester, NAV evaluator,
strategy, refresh, fallback, source admission or economic approval route.
Existing `build_fullrun_runtime_source_manifest` canonical group hashing and
`evaluation_v2_admission.compare_environment`/native bounded resolver are reused.
All 16 existing shared roles must bind to their actual consumed group sources;
the context's data_release digest must bind the price generation.

The merged #591 Reader remains the explicit-generation price-byte boundary.
Its price manifest/objects and immutable read result can supply a later
reviewed generation. The adapter does not normalize raw legacy Parquet, bypass
the Reader, publish a generation or assert that Reader bytes are admitted.
The master registry has zero admitted generations. Reader, producers, economic
verifier, config, models, risk limits, fees, next_close rules and workflows are
unchanged. No economic code is called by the adapter itself.

This slice deliberately does not modify the two manual workflows or the legacy
sidecar scripts: without authentic A1 inputs, wiring an unproven consumer closure
would add execution authority without usable source evidence. Their legacy cache,
refresh and fallback routes remain as identified in the existing PREP. They cannot
produce an M3 certificate. Before any later workflow edit, name its precise path
and necessity in #448 and verify Main/Source allowlists again.

## Contract and phase evidence

The exact UTF-8 contract SHA256 is pinned by an independent caller. It is distinct
from the price-generation SHA256 and from each workflow/run receipt identity.
Twelve fixed groups cover prices/OHLCV/adjustment; universe/security identity;
candidates/selection inputs; SPY/VIX/used macro; fundamentals/earnings/consensus/
guidance; SEC/events; calendar/PIT; costs/slippage/tax/FX; capital/cash/accounting;
strategy/model/parameters; code/evaluator; and session/decision identity.
SEC/event sources may be empty only when unused. Other groups are mandatory.
Within a stage the engine and broker can consume different subsets; both stages'
consumer unions must cover the same complete nonempty group set. Strategy outputs
are not common inputs and do not enter this equality rule.

Each source has an opaque flat artifact ID, exact SHA256 and size, original aware
availability, collection and expiry clocks; every group has a declared basis.
The clocks must satisfy available <= collected <= decision <= expiry. Unknown,
naive, malformed/future/stale clocks refuse. Bytes bind adjustment, identities,
calendar grid and source metadata; declarations alone do not authenticate PIT.
Limits intentionally reuse the existing bounded precheck: 1 MiB per artifact,
16 MiB per resolver snapshot, at most 2,048 partitions per group, bounded JSON.
This is a limited contract/slice, **not** a complete R1000 Fullrun transport.
Larger future generations require a separately reviewed partition/transport
binding; these limits must not be silently relaxed to make a run green.

Stage A order: FROZEN -> RESTORE -> PRE_engine -> EXECUTION_engine -> POST_engine
-> PRE_broker -> EXECUTION_broker -> POST_broker -> POST.
Stage B: FROZEN -> RESTORE -> PRE_replay -> EXECUTION_replay -> POST_replay -> POST.
Restore happens externally before `FrozenStage` construction. Each snapshot uses
a fresh native resolver and checks all groups, including groups not consumed by
that particular callback. Stage A engine-to-broker drift therefore fails before
the broker callback. Actual repo HEAD is checked before and after the guarded
callbacks. A failure poisons the invocation; finish seals successful receipts.

`ConsumerView.read(group, artifact_id)` returns only exact verified runtime bytes
and sends those same bytes to the caller's immutable evidence sink. Every planned
source must be read; an asserted hash or unobserved source cannot complete a stage.
No external/refresh/stale-repair/cache/fallback input method is provided;
`external_input()` refuses any such attempt. Missing candidates/targets cannot
be replaced by failed_runs or archived books. No economic result is accepted
merely because a callback returns a value. Callback values are returned unchanged.

Independent `verify()` takes separately pinned A/B receipts and rereads both the
frozen source objects and all retained evidence objects. It rebuilds each
phase/group digest from actual bytes, validates exact path/size/hash membership,
availability contract, phase order, consumed coverage, context/source links and
same session/code/decision. It does not trust a declared runtime hash and does
not require the two full runtime/workflow/run identity hashes to match.
The evidence sink and receipt pins must be held outside mutable run output.

## Native API and verification

Create a `FrozenStage` with the pinned contract, A/B name, separately restored
runtime/frozen roots, safe immutable evidence sink, existing environment arms
and environment root. Invoke A engine then broker, or B replay, with callbacks
whose **entire read closure** uses `ConsumerView`; call finish for receipt bytes.
The sink returns `{artifact_id, sha256}` of the exact retained bytes. It must
preserve original evidence, reject conflicts, and avoid shared mutable inputs.
For independent verification call `verify()` with both receipt byte hashes or
run the module's CLI with `--contract`, `--stage-a`, `--stage-b`,
`--generation-sha256`, `--stage-a-sha256`, `--stage-b-sha256`, `--frozen-root`,
`--evidence-root`, `--control`, `--challenger`, `--environment-root`.
CLI rejects unsafe/missing evidence with exit 2, positive byte contract with 0.

The native consumer boundary is **trusted, not an OS sandbox**. A malicious or
uninstrumented callback can read/network outside the view; the adapter cannot
authenticate its read completeness. Thus even PASS always returns
`FROZEN_CONTRACT_BYTE_PASS_RESEARCH_ONLY`, `fairness_certified=false`,
`g0_certified=false`, `economic_comparison_ready=false`, `fullrun_allowed=false`
and every economic/target/paper/broker/promotion/public/live authority false.
Native consumer closure, source authenticity, row-level PIT and real A1 admission
remain explicitly unverified. A fabricated receipt with matching hashes cannot
be treated as native consumer provenance; the caller's independently retained
runner/consumer evidence is mandatory in any future real audit.

## Tests, regression and remaining gates

The new unittest suite uses physical temporary frozen/runtime/evidence roots,
actual guarded byte reads, before/after mutations, independent rehashing and
actual child CLI invocations. Synthetic sources are labeled SYNTHETIC.
It covers F01–F10, phase/receipt/environment forgery, missing or undisclosed reads,
availability/expiry, symlinks, code drift, sealed/poisoned sessions and callback
result preservation. Unittest checks remain active in Python -O; the existing
registered runtime smoke launches the new suite with the same optimization mode.
The shared validation runner, its protected registration and #593 files are not
modified. Existing verifier and context-admission smokes are separate regressions.
Normal/-O logs and exact native/published identities belong to the worker result,
not this static note. Repeated/optimized cases do not multiply unique test counts.

Prerequisites for the next real stage: A1 authentic price/security generation,
all actually used nonprice objects and original clocks, immutable readback;
reviewed Reader-to-native format/identity binding; independently audited complete
native engine/broker/replay read closure and environment/parameter capture.
Then perform a separately authorized limited same-generation consumer audit.
Actual economic Stage A/B/R0/Fullrun remains a separate approval and gate.
New-head CI and independent A6 precede any merge. This task does not merge.

Reusable lesson: same source_run_id, price digest or green environment precheck
cannot prove identical consumed inputs. Reconstruct group bytes across all
phases; distinguish bytes returned to a guarded consumer from authentication of
the real native read closure. Missing consumption evidence must stay blocked.
This dated linked note records the lesson instead of editing the shared lessons
ledger, whose concurrent #593 change scope is preserved.
