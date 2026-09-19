# [PROJECT_HANDOFF] Verified history into the model-cycle input

## Scope and source

Implemented the handoff's first integration: a read-only adapter from current
master's `Lake` into `run_model_cycle.py prepare-history`. It creates a private,
hash-bound research input, preserving the complete caller cohort and missing
securities. It does not create a stock ranking or model portfolio.

- Base: `bcb14c06613e34420ce7988e5bb1ac5547b22b57` (`master`, rechecked during work).
- Reused PR #426 head: `4721ee507ffe699cac1af93e0e2e93d4ae6624fd`.
- `continuous.py` is byte-identical to that head, Git blob
  `913452d7153a42dba9b97b9af6a4e1bba656995d`. Its 30 journal/learning regressions
  are retained separately; queue and legacy-trade modules are not imported.
- The model runner is adapted to expose the history-input command. Actual REAL
  event replay now stops before creating a journal, because authenticated
  quote/calendar/review/delivery adapters are still absent. Synthetic replay and
  parent-copy restoration remain supported.
- #426 remains a separate unmerged draft. This is a scoped reconstruction on
  current master, not a merge of its older parent stack. Reconcile the runner
  changes explicitly if #426 is later integrated. PR #428's ALFRED fix remains
  separate; the collector and archive reader are unchanged here.

## Implemented checks

1. Use `Lake`'s full commit-chain and all retained pack/member hash verification.
   Require the exact pinned commit, catalog, execution, collector source and
   input-cohort hashes. Verify the execution-linked reports and recompute quality
   counts from the catalog. A metadata preview cannot substitute for this path.
2. Match every `security_id` and ticker against the caller's full cohort, then
   reconstruct the issuer mapping from its preserved SEC reference. Reject a
   different same-sized cohort, duplicate identities and inconsistent issuer
   relationships. Keep all missing/blocked securities in the denominator.
3. Check execution and dataset timestamps, with a declared default 48-hour
   freshness window. Fresh execution cannot hide stale datasets. Require
   COLLECTED/UNCHANGED for requested records; reject BLOCKED/STALE_RETAINED.
   PARTIAL can supply labelled research inventory, or be explicitly rejected.
4. Preserve original normalized objects, raw-object references, financial periods,
   coverage and evidence labels. Current archive contents are not certified PIT,
   full statements, current quotes, or verified historical membership.
5. Allow only listing/download operations. The existing Rclone constructor can
   attempt `mkdir` when a folder is missing; the read-only subclass rejects it
   before a network write. Outputs/cache cannot be placed inside the archive.
6. Write a new input directory only after successful validation. Recheck the
   exact commit inventory before output. Include implementation file hashes and
   an input manifest; never advance an accepted pointer or overwrite a parent.

## Actual data execution — completed 2026-09-14

Input cutoff: `2026-09-14T04:42:59.826450+00:00` (13:42:59 KST).

Authenticated Google Drive raw downloads recovered **39 files**, including all
**27 packs / 503,129,850 bytes**, three catalogs, three commits, three execution
receipts and the latest execution's three reports. Each file's SHA256 and size
matched the Drive inventory. The unchanged master reader then validated the
complete retained archive chain and pack members on these downloaded bytes.

The process used LocalTransport for the recovered copy, so its
`remote_verified=false` is intentionally preserved. Authenticated connector
download evidence is recorded separately; a local Boolean is not used to claim
that the process authenticated to Drive using GitHub's rclone credentials.

| Result | Observed value |
|---|---|
| Command result | exit 0, PARTIAL_RESEARCH_INPUT |
| Securities retained | 1,118 |
| Mapped issuers | 1,106 |
| Issuers with collected financial archive | 1,104 |
| Securities linked to readable financial archive | 1,115 |
| Preserved missing securities | HOLX: unresolved CIK; IBN/OZK: blocked Companyfacts |
| Financial fact rows reported by matching catalog/quality | 15,173,078; not a new complete-statement calculation |
| Actual UNRATE records read into the input | 367, 1996-01-01 through 2026-08-01 |
| Collector requested-through date | 2026-09-12 |
| Price-cohort snapshot | 2026-09-09; current_prices_verified=false |
| Historical PIT / 10-year three-statement completeness | not certified |
| Model events / orders / new training records | 0 / 0 / 0 |

Collector source: `1c48a92587f5b31c355804e694f03ece2cc52acd`;
run `history-34719702944-1`, corresponding to
[Actions run 34719702944](https://github.com/wscha231/r1000-quant-engine/actions/runs/34719702944).
That is the existing collector execution, not a newly dispatched run.

| Evidence | SHA256 |
|---|---|
| Archive commit | `cf6f88321a2c1f86da5719af1771cf711668059e06203202d2c6e00bcf1c9475` |
| Catalog | `23ebbf52f26b5ea46ff8b82e59f7ad41942d93fde627123049cf4735b8812227` |
| Execution receipt | `bbc28eac3c21a859e0be22b21d34079119299599a2e6e818aadba4a98c58c76b` |
| Cohort input | `4e1eb090f8137395603228dbc55c35907307ad6d049ec778f2722d1cbb87f4b4` |
| Generated history-input.json | `52912eb1f029d5c9b61fb4e1e1246091ad2557eceb21b003ebfbb73ef7e2e0bd` |
| Generated manifest.json | `4da38f53558e46e742f5a24c682b995033dfa6d417d734d8cf736fe881fbc400` |
| Private input ZIP | `9b0e141ce439e089bcc830928e510fcac72431de61ebd5499f141e847e6dd166` |

The new 163,370-byte `R1000_History_Model_Input_20260914.zip` was saved in the
existing private research folder. Authenticated re-download at
`2026-09-14T04:44:49.852275+00:00` matched the entire ZIP and all four members.
The restored manifest matched the input, catalog and execution identities.
No Drive IDs, original provider rows or private input files are committed here.

This verifies **research-input storage/restoration**, not an accepted model
journal head or a daily operating service. The manifest's `drive_saved=false`
records the earlier local preparation stage; the subsequent external roundtrip
receipt is separate. No accepted-state pointer was advanced.

## Validation and reproduction

The scoped checkout reused an available cloud Git object database without
modifying that other worktree. Unrelated historical artifact blobs are absent
locally: ordinary commit creation reported the missing pre-existing
`.refactor_baseline/backtest_metrics.ref.json` object. The scoped tree preserves
all unchanged master object IDs using Git's missing-object-aware tree builder;
no frozen artifact is regenerated. Local/remote tree equality is a publication
requirement. This is not a complete original-PC recovery or a local full Tier-1
run; the published PR must pass its independent CI and review gates.

**57 unique tests pass**: 27 new adapter/CLI faults and 30 reused model-journal
regressions, in normal and optimized Python with ResourceWarning treated as an
error. Repeated environments are not counted as additional test cases.

```sh
python -W error::ResourceWarning tools/run_pr_validation.py \
  --include subscription_history_adapter_smoke \
  --include subscription_model_cycle_smoke \
  --only subscription_history_adapter_smoke --only subscription_model_cycle_smoke
python -O -W error::ResourceWarning tests/subscription_history_adapter_smoke.py
python -O -W error::ResourceWarning tests/subscription_model_cycle_smoke.py
```

The dedicated CI uses this existing `--include`/`--only` interface, leaving the
protected validator unchanged. An initial comma-separated invocation tried one
nonexistent test filename and was corrected to repeated options. A new restore
fixture initially supplied an empty event batch, which the existing journal
correctly rejects; the fixture now verifies an idempotent nonempty replay.
Neither correction relaxes a production or data gate.

Use `python tools/subscription_manager/run_model_cycle.py prepare-history --help`
for the read-only CLI. Supply an approved `--remote` or a verified downloaded
`--local-archive`, all five source/input pins, an explicit `--decision-at`, a full
`--cohort`, and new `--workspace`/`--output` paths. `--required-dataset` can read
specific verified financial or macro records without recollection. Resolve new
catalog/execution pins on each future run; do not reuse this dated example as
current-readiness evidence.

## Remaining boundaries and next minimum change

- Code implementation and actual input integration are complete for this slice.
  Exact published head and CI/review results belong to the accompanying PR.
- Actual reviewed company proposals, current quotes/calendar, internal delivery,
  publication-following fills, accepted model-head storage and a single scheduler
  connection remain incomplete. No recurring job was added or activated.
- Correct the existing synthetic market-cap/forward-PE path and financial
  restatement/date defects in separate scoped changes before affected data is
  admitted to investment evaluation or historical learning.
- Preserve HOLD/WATCH/REJECT and immutable decision evidence when integrating
  the existing journal. Historical economic-period/exit-label/cost correction,
  matured-only training, untouched OOS, shadow comparison and separate approval
  remain required. No new learning approval or holdout population was invented.
- Next minimum integration: bind current price/session evidence and reviewed
  company-decision inputs to this exact full-cohort packet, keeping unavailable
  inputs blocked. Historical performance, live orders, automatic promotion,
  accepted-ledger migration and paid launch are outside this change.
