# Run287 H1 paper-integrity contract repair — 2026-09-02

Repository: `wscha231/r1000-quant-engine`

Base: `2056dcc13687dff55a9c71bea23c74ec47032ad9`

Branch: `codex/run287-paper-integrity-contract-h1-20260902`

Scope: H1 verifier/preflight repair only

## Result

The H1 change repairs the impossible producer/consumer contract without
changing the raw paper manifest schema. The raw
`snapshot_integrity.json` remains an exact
`run287-paper-ledger-snapshot-integrity-v2` object with no `status` key.
Verification state now lives in a separate deterministic
`run287-paper-ledger-integrity-verifier-receipt-v1` envelope.

The preflight recomputes that envelope from the current raw manifest, all
manifest-declared files, and the immutable-head tree on disk. It independently
reopens every committed head, verifies each manifest and file map, proves one
content-continuous parent chain, and exact-compares the recomputed selection to
the supplied selection receipt. It accepts the supplied verifier receipt only
when the complete JSON object and canonical serialized bytes equal the
recomputed result. Missing, reformatted, forged, stale, hash-mismatched, or
symlink-backed evidence fails closed.

## Pinned operating evidence

| Evidence | Exact value |
| --- | --- |
| Audited base | `2056dcc13687dff55a9c71bea23c74ec47032ad9` |
| Failed run / job | `33476672130` / `99757265767` |
| Failed artifact / ID | `daily-operating-selection-refresh-33476672130` / `9789280452` |
| Requested session | `2026-08-31` |
| Raw canonical manifest SHA-256 | `82ffee50ee262fef5bd16e2881eecb5b359b2b00702f8de24208dff2630b4900` |
| Paper terminal | `65fa6f5b4b12729811b72a90661fc744320826dfe868ec6da2632768b1ec02a7` |
| Paper previous | `086904f693a94027fda661d0da8041744bb941ebb68cb7547fa5e737caee3b57` |
| Paper root / chain size | `f904fa6bd1d4280f688f99b4562837e48ad196942f75a3b9ad0b2aeb917709a3` / `6` |
| Paper as-of / file count | `2026-07-24` / `243` |
| Accepted risk-outcome heads | `0` |
| Legacy state / summary SHA-256 | `PRESENT_FETCHED` / `5a57e4becef19668dce45803eb77185bc6c60bcf9b58522df939e9a48a56654c` |
| Earliest pending NYSE session | `2026-07-27` |

## Root cause and contract change

| Boundary | Before H1 | After H1 |
| --- | --- | --- |
| Raw producer schema | Exact v2 keys; `status` forbidden | Unchanged |
| Canonical verification | Verifies schema, snapshot hash, exact file map/count, every file hash, genesis, and ancestry; adds `status=VERIFIED` only in memory | Unchanged |
| Immutable-head selection | Verifies and selects one linear immutable chain | Public complete-ledger selector is unchanged; preflight also independently reopens the physical head tree, verifies content continuity, and exact-compares the selection |
| Preflight input | Reopened raw JSON and required raw `status == VERIFIED` | Recomputes the canonical verifier envelope and exact-compares the supplied receipt |
| Verification status | Incorrectly expected inside raw evidence | Present only in the separate verifier receipt |
| Failure policy | Producer-valid evidence was structurally impossible to accept | Missing or inconsistent raw, files, physical heads, selection, or receipt blocks; all state/head symlinks block |
| Migration authority | Ordinary daily dispatch could forward risk-outcome genesis/quarantine inputs into preflight | Compatibility inputs are fail-closed safety traps: either `true` exits before checkout; neither is mapped to an environment variable or forwarded to preflight |

The raw schema was not widened, and the status predicate was not deleted. The
predicate moved to the correctly typed verifier receipt and is accepted only
after the canonical verifier succeeds.

## Changed paths

| Path | H1 purpose |
| --- | --- |
| `tools/run287_paper_ledger_integrity.py` | Build and securely write the deterministic verifier receipt; reverify complete physical immutable heads; no-follow/unique-temp copy diagnostic bytes; reject symlinks and outputs inside accepted state. |
| `tools/build_run287_risk_outcome_parent_preflight.py` | Replace raw-status inspection with canonical verification plus exact receipt comparison. |
| `.github/workflows/daily_operating_selection_refresh.yml` | Generate the read-only receipt before preflight, retain diagnostic evidence, and hard-disable risk-outcome migration authority in ordinary daily before checkout. |
| `tests/run287_risk_outcome_parent_preflight_smoke.py` | Use 243 tracked files and six physically materialized hash-linked heads; cover missing heads, symlinks, output isolation, and receipt attacks. |
| `tests/workflow_artifact_smoke.py` | Lock receipt ordering, artifact separation, the pre-checkout migration trap, and absence of migration environment/CLI flag forwarding. |
| `docs/CODEX_RUN287_H1_PAPER_INTEGRITY_CONTRACT_RESULT_20260902.md` | Record root cause, contract delta, evidence decisions, rollback, and the next blocker. |
| `docs/AGENT_SHARED_LESSONS_LEDGER.md` | Preserve the raw-manifest/verifier-receipt boundary for later agents. |

No selector, alpha, model, risk limit, target builder, order path, paper
transaction, outcome migration, or broker path changed.

## Evidence decisions

| Evidence case | Expected H1 decision |
| --- | --- |
| Producer-valid raw v2 manifest with no `status`, 243 exact files, five ancestors, and matching six-head selection | Pass integrity gate |
| Raw manifest with inserted `status` | Block: raw exact-key schema mismatch |
| Verifier receipt missing | Block: `paper_integrity_verifier_receipt_missing` |
| Verifier receipt forged or raw-manifest hash changed | Block: `paper_integrity_verifier_receipt_mismatch` |
| Tracked file missing, extra, or changed | Block: canonical snapshot checksum mismatch |
| Parent, terminal, head count, or ordered chain mismatch | Block: canonical ancestry or immutable selection mismatch |
| Empty head tree or missing selected head directory | Block: physical immutable-head revalidation failure |
| State or head file replaced by an identical-byte symlink | Block: symlink evidence is forbidden |
| Canonical diagnostic-copy source is a symlink | Block before reading or publishing diagnostic bytes |
| Verifier output inside accepted state | Block before writing any output |
| Pre-existing fixed temporary-file symlink for receipt or diagnostic copy | Ignored safely; unique exclusive temp file is used and external bytes remain unchanged |
| Same raw bytes, files, and selection receipt rerun | Identical verifier receipt bytes and SHA-256 |
| Scheduled, zero accepted heads, `PRESENT_FETCHED`, no migration authorization | `BLOCKED_ONE_TIME_LEGACY_QUARANTINE_AUTHORIZATION_REQUIRED` |

## Validation

| Check | Result |
| --- | --- |
| H1 producer/preflight smoke | `16/16` passed |
| Immutable paper-head selector smoke | passed |
| Paper-ledger transaction smoke | passed |
| Workflow artifact/order smoke | passed |
| GitHub secret-scope smoke | passed |
| Shared-lessons contract smoke | passed |
| Registered Tier-1 PR validation | pending automatic push-triggered PR CI |
| Changed Python compilation | passed |
| Workflow YAML parsing | passed through workflow artifact smoke |
| `git diff --check` | passed |

No workflow was dispatched or rerun. No fullrun, backtest, catch-up, migration,
quarantine, Drive write, target/order/ledger mutation, or broker order was
executed for this validation.

## Expected next blocker

For the pinned current state, the repaired scheduled-style preflight must stop
at:

```text
BLOCKED_ONE_TIME_LEGACY_QUARANTINE_AUTHORIZATION_REQUIRED
```

That is a successful H1 outcome, not authorization to migrate. The ordinary
daily workflow rejects either compatibility authorization input before
checkout and never forwards either input, so `READY` is impossible there on
both scheduled and manual events.

## Why migration must be a separate workflow

The daily workflow reaches target construction and the transactional paper
ledger before `Freeze accepted risk-outcome parent`. H1 therefore turns its
legacy-compatible risk-outcome inputs into pre-checkout fail-closed traps and
removes all forwarding instead of leaving a manual route that grants more
authority than the intended one-time parent transition.

A later migration-only workflow must be reviewed separately and perform only:

1. restore pinned read-only evidence;
2. reverify exact code, Drive paths, paper terminal, zero accepted heads, and
   allowlisted legacy bytes;
3. create and persist exactly one quarantined accepted parent;
4. prove accepted-head count `0 -> 1`; and
5. stop before target, paper-ledger, catch-up, fullrun, or order stages.

The existing conditional approval packet remains **not ready to sign** until
that isolated path and its exact implementation SHA exist.

## Rollback

Revert the H1 code commit. There is no data rollback: H1 writes only diagnostic
run-local receipts/logs and adds them to the evidence artifact. It does not
change Drive, accepted heads, targets, orders, cash, positions, or ledger
state. After rollback, scheduled preflight returns to the known false blocker
`paper_integrity_contract_invalid`; migration still remains unauthorized.
