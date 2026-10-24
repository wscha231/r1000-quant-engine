# Retained OHLCV reuse and managed refresh

## Find and reuse the existing prices

The owner reconciliation prepared2026-10-21T22:36:00.857306Z records
**820 distinct ticker keys: Alpaca776, Twelve312, overlap268**. Original inventory
SHA256: `ad60fb7c4f2b8c34b2aa23ab7505e83eefc681c3bc2c6d78f6f9187a4ae79924`.
Reuse the [original completion receipts](https://github.com/wscha231/r1000-quant-engine/issues/590#issuecomment-6287362816)
and [machine index](../data_static/a1_ohlcv_inventory_v1.json). This change does
not repeat a full-cohort audit or certify current coverage, names, rights or PIT.

| Existing location | Retained evidence |
| --- | --- |
| Configured owner-only private root / `alpaca_sip_historical_research_v1` | `<sha>.zip` originals, `<sha>.jsonl.gz` normalized raw/split rows, `<sha>.json` receipts/checkpoints. Resolve private IDs through the existing Source control and original receipt map. |
| Existing Twelve private root (`R1000_PRIVATE_RESEARCH_FOLDER_ID`) | Its original contract resolves `01-provider-raw`, `02-normalized`, `05-checkpoints`, `06-receipts`. Preserve separate provider/adjustment/account lineage. An asset list is not price coverage. |
| `research/macro_technical_evidence/v1/scheduled/long-history-v1` | Separate Macro/SEC Lake commit/catalog/execution chain; not the private Alpaca price namespace. |
| Existing default Drive base / `cache_prices` | Separate consumer cache; do not substitute it for original private Source receipts. |

Do not publish private IDs, vendor raw bytes, keys or tokens to GitHub. The public
index strips original Drive URLs, names and FIGIs; it is a locator rather than
verified company identity. Drive search returning zero is not absence: inspect
the grounded folder or original receipt when needed.

For a requested security/window:

1. Find its existing provider/receipt keys in the index, then resolve only the
   relevant original private checkpoint/receipts.
2. Read back the exact raw pack, normalized bytes and receipt; verify full hashes.
   Reuse `tools.alpaca_sip_private_backfill_v1.verify_archived_group(raw, normalized, receipt)`
   for Alpaca original-to-normalized membership. Do not download prices again.
3. Keep actual window/basis, source code and original collection/availability
   clocks. Missing Open stays missing. Identity, lifecycle, CA and supplier
   retention/purpose proof remain separate from byte integrity.
4. Consume an exact frozen generation only through the existing Reader gate.
   Use A0 and the existing Source controller for any proven missing interval.
   A static index or green CI does not grant Source/PIT/economic admission.

## Focus, watch and re-entry

The human chose **existing820 + A0-confirmed managed-list changes**, rather than
automatic index reconstitution. The follow-up explicitly retains tracking after
removal: **FOCUS -> WATCH -> FOCUS**. WATCH keeps price tracking, original bytes,
research and exit/re-entry history. These820 data targets are not820 active
investment candidates. The original1009 seed/campaigns remain unchanged.

The [managed policy](../data_static/a1_ohlcv_managed_v1.json) contains disjoint
`active_tickers` and `watch_tickers`. For each A0-confirmed revision:

- Archive the exact previous policy at
  `data_static/a1_ohlcv_managed_history/<old-file-SHA256>.json` and bind that hash
  in `previous_policy_sha256`; increment revision once.
- A new focus member or re-entry has START_UPDATE; a removed focus member has
  MOVE_TO_WATCH. Each carries a stable event ID and actual A0 comment reference.
- The adapter refuses an incorrect parent, duplicate/unrecorded changes,
  focus/watch overlap or silently dropped watch history. Re-entry reuses old
  bytes and does not create duplicate price targets. A genuinely necessary stop
  such as delisting, rights failure or permanent source loss needs its own
  evidenced Source handling; do not silently delete or redirect the issuer.

The offline adapter checks config consistency, not GitHub authority. Existing
protected A0/Source acceptance and dispatch still apply. Stable plan/event IDs
support that existing route; this is not another canonical job ledger.

## Calendar and existing daily job

Reuse `free_data_daily_update.yml` at **23:30 UTC Monday-Friday**, which is
**08:30 KST Tuesday-Saturday**: normally2.5 hours after the winter US close or
3.5 hours after the summer close. GitHub scheduling can be delayed. Early-close
days use the same later scheduled slot; no duplicate scheduler is created.

The adapter reuses the existing NYSE calendar gate and independently requires
at least **120 minutes after the actual close**. Weekends, holidays and stale
sessions skip. Force cannot bypass this buffer. It records the session and due
time instead of inferring the US close from a fixed Korean time.

The existing daily job prepares `outputs/a1_managed_ohlcv/refresh_plan.json`,
shows focus/watch/add/re-entry counts in its GitHub run summary, and copies the
non-sensitive plan to its existing
`research_runs/<branch>/<run>/a1_managed_ohlcv/` output location. Invalid input
revokes prior success with BLOCKED_INPUT; an output alias to input is refused.

```powershell
python -m tools.prepare_a1_managed_ohlcv `
  --inventory data_static/a1_ohlcv_inventory_v1.json `
  --policy data_static/a1_ohlcv_managed_v1.json `
  --market-gate outputs/free_data_daily_update/market_gate.json `
  --output outputs/a1_managed_ohlcv/refresh_plan.json
```

## Exact activation boundary

**Actual private820 daily collection remains disabled.** A Draft PR is not
deployed automation. The separate daily yfinance action is capped80 target-book
tickers; its green job does not mean the private820 histories were updated.
The execution adapter reuses the collector, timeout and meter primitives without
changing their implementation or the original campaign guards.

The missing execution dependencies are actual account-bound private research
retention/purpose terms and a reviewed standing maintenance contract binding
deployed pins, one writer, private storage, bounded API/Drive/storage/runtime
costs, original receipts, gap/CA/identity checks and idempotent checkpoints.
Free-plan text or API success alone does not certify rights. Do not renew/reset
expired993/174 authorizations or invent a numeric budget. After those evidence
bindings, the existing Source owner can validate a small authorized incremental
witness before wider operation. No Source/PIT, ER, portfolio or trading change
is implied by reuse, tracking or successful collection.

## Bounded automatic execution, implemented but disabled

`tools/alpaca_sip_managed_refresh.py` is the execution adapter in the existing
daily workflow. It uses `capture_one_group`, original ZIP/raw/split verification,
content-addressed private writes, `OwnerDrive` and `RuntimeMeter`. It introduces
no separate cron, downloader or canonical ledger. The existing schedule remains
23:30 UTC weekdays; the shared NYSE calendar independently requires close+120
minutes and a fresh completed session. Holidays/weekends skip. Manual force in
the older daily job cannot bypass the private adapter's calendar or rights gate.

The optional job shares `a1-private-research-single-writer` with the historical
Source workflow. A cancellation, replaced pending job or unknown publication is
not a completed update. Every observed workflow run reserves a slot; only an
actual skipped managed-job record proves it produced no Source checkpoint.
Unknown/failed prior attempts stop continuation. Never blindly rerun a workflow
that also contains the older daily replay work.

Three independent enablement conditions remain unset: the deployed policy's
`automatic_capture_enabled=true`, repository variable
`A1_MANAGED_OHLCV_ENABLED=true`, and private `A1_MANAGED_OHLCV_CONTROL`. A boolean
alone cannot authorize execution. No secret, variable, OWNER attestation, rights
document or numeric maintenance grant is created by this PR. With the committed
false policy the adapter returns `WAIT_OWNER_EVIDENCE` before credentials or
remote reads. The human explicitly confirmed rights evidence is still absent.

### Actual standing contract required before activation

The private control has schema `a1-managed-sip-maintenance-v1`. Its authoritative
values must come from actual owner receipts and separately reviewed permission:

| Binding | Required fields/evidence |
| --- | --- |
| Scope | `repository`, `task_key`, exact inventory/policy byte hashes, sorted `authorized_tickers`, explicit `backfill_tickers`; a policy revision needs a matching reviewed contract. |
| Finite window | `not_before`, `expires_at` (up to31 days), `max_runs` (up to40), `max_symbols_per_run`, `max_active_seconds_per_run` (up to4800); these bounds are implementation ceilings, not granted amounts. |
| Cumulative costs | Original `opening_usage`, actual `opening_evidence_ref`/SHA, explicit `per_run_allowance`, `cumulative_ceiling`. Reserve every slot in full. Preserve opening provider/Drive/bytes/storage/active-seconds/dispatch costs and unresolved reservations; never reset the993/174 campaigns. Each slot reserves the full5400-second job timeout including setup/publication, regardless of a shorter worker limit. |
| Account and private storage | Actual credential binding, owner hash and distinct existing root/data/journal/evidence folder IDs, same OAuth owner, private permissions and at least2GiB verified free space. Nothing sensitive belongs in GitHub. |
| Rights | `rights_ref`: `a1-reviewed-account-rights-v1`, exact binding, provider, personal noncommercial purpose, reviewed historical-SIP and private-retention permissions, actual source-document refs. Read back all bounded source documents. Supplier expiry is checked only if explicitly documented; execution expiry is not supplier expiry. |
| Opening accounting | `opening_evidence_ref`: `a1-managed-opening-accounting-v1`, exact opening usage/binding, original-campaign preservation, unresolved costs reserved, actual source-document refs and the same `source_history_sha256` as the control. Hash the original Source workflow's complete bounded run prefix (ID/attempt/head/status/conclusion/created/updated; sorted by ID). Missing pages, active runs, added runs or older rerun attempts block maintenance pending reconciliation. Owner review is explicit; this adapter does not infer old platform cost from missing receipts. |
| Original reuse | `bootstrap_ref`: `a1-managed-reuse-bootstrap-v1`, inventory hash, opening-usage/evidence hash, existing provider groups/receipt refs and `asset_identity_refs` to actual retained provider-asset bytes. Reconcile only selected groups' actual bytes; compare stable asset IDs and hold missing/changed IDs. This bootstrap has not yet been supplied or certified. |
| Protected deployment | Exact reviewed PR HEAD/merge, protected current master ancestry and LF-normalized `code_pins` for every runtime dependency listed in `PIN_PATHS`. A Draft is ineligible. |
| Standing owner grant | An actual immutable OWNER comment on A0, created after deployment and within the execution window. Exactly one `A1_MANAGED_SIP_EXECUTION_V1 <JSON>` line binds `control_sha256`, `rights_sha256`, `opening_evidence_sha256`, expiry and explicit rights/budget review booleans. The control hash excludes only `approval_reference`, whose real comment ID is returned after posting; do not predict an ID or invent an auth hash. |

Rights documents and opening-accounting evidence are separate. API success,
free-plan text, privacy policy or a generic customer agreement cannot substitute
for missing account-specific retention/purpose review. Implementation ceilings
and synthetic test controls do not approve any new numeric resource grant.

### Incremental data and durable continuation

FOCUS and WATCH both receive tracking. The adapter reads back only relevant
original groups, verifies raw/split provenance and derives each last observed
date from actual normalized bytes. It requests only the missing interval;
already-current names reuse existing data. Twelve-only names remain held until
an explicit provider-transition/backfill scope is reviewed. No old Twelve bytes
are overwritten or silently represented as Alpaca coverage. Unsupported assets,
no-data and incomplete session grids remain held with separate reasons.

Each run must publish/read back an immutable RESERVED checkpoint before provider
I/O and a linked terminal checkpoint afterward. A later run requires both and
the exact finalized meter artifact including terminal-publication costs. Missing
meters, changed attempts, broken chains or any prior BLOCKED state fail closed;
partial raw packs stay intact for explicit reconciliation, not automatic replay.
The final safe artifact is `a1-managed-ohlcv-<run>`; actual originals stay private.
Checkpoints are the refresh namespace, not a replacement investment ledger.

A holiday/outside-window return writes an explicit `a1-managed-no-capture-v1`
artifact before credentials, with the actual clock/calendar and zero Source
I/O. Continuation authenticates that artifact and recomputes its calendar;
missing checkpoints alone are never zero-cost proof. Such slots retain their
full reservation. Already-current bootstrap cutoffs are saved in the terminal
coverage map so a bounded batch can progress past reused names to the tail.
The shared concurrency lock prevents simultaneous Source work; the full legacy
run/attempt fingerprint separately detects intervening Source activity. A
changed fingerprint requires reconciling actual extra costs and a new reviewed
standing contract, never silent subtraction or budget renewal.

An incremental update is complete only when raw and split grids both cover every
requested NYSE session. A last-day bar alone is insufficient. Newly listed or
halted names with gaps require lifecycle review; do not invent prelisting bars.
New split-adjusted segments are separate immutable research generations; this
does not retrospectively certify an adjustment/CA chain across old generations.
Collection clocks are recorded; original publication time remains unknown when
the provider supplied none. Historical issuer identity, CA/PIT and investment
admission remain false, even after a successful private price refresh.

Offline tests inject synthetic transport/owner storage and exercise the existing
collector and real meter; no test is an actual provider/Drive execution receipt.
Operational activation and the first small real witness remain blocked pending
the missing evidence and protected deployment. No activation is claimed here.
