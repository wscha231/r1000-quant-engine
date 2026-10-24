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
This adapter changes no collector, timeout, meter or original campaign guard.

The missing execution dependencies are actual account-bound private research
retention/purpose terms and a reviewed standing maintenance contract binding
deployed pins, one writer, private storage, bounded API/Drive/storage/runtime
costs, original receipts, gap/CA/identity checks and idempotent checkpoints.
Free-plan text or API success alone does not certify rights. Do not renew/reset
expired993/174 authorizations or invent a numeric budget. After those evidence
bindings, the existing Source owner can validate a small authorized incremental
witness before wider operation. No Source/PIT, ER, portfolio or trading change
is implied by reuse, tracking or successful collection.
