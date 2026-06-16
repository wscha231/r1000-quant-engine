# Data Refresh Operating Plan - 2026-06-16

This plan defines how AlphaOps vNext keeps data current without repeatedly
re-downloading the full historical lake. It is an operating handoff for Claude
Code, Codex, and ChatGPT Pro.

## Source Of Truth

- `[GITHUB]` is the code, workflow, run artifact, commit SHA, and PR source of
  truth.
- `[DRIVE]` (`r1000_top30_institutional/`) is the large-data and user-facing
  mirror. It stores raw archives, PIT parquet stores, price caches, manifests,
  and research run outputs that should not live in git.
- `[LOCAL]` is an execution workspace. Local files are not official until they
  are committed/pushed or trace to a GitHub run artifact.

Official current recommendation evidence must be traceable to all of:

- GitHub workflow run ID
- commit SHA / branch
- restored data lake snapshot
- `outputs/data_readiness/summary.json`
- `outputs/data_freshness_contract/status.json`
- broker-ledger metric mode, when performance is discussed

## Persistent Data Lake Layout

Large stores live in `[DRIVE]` and are restored into GitHub Actions before
selection/replay:

| Store | Purpose | Canonical path |
| --- | --- | --- |
| Prices | adjusted bars and replay fill cache | `cache_prices/`, `data_raw/free/prices/` |
| Macro/crisis | market stress, regime, crisis features | `data_pit/macro/`, `outputs/macro_policy_engine/` |
| SEC companyfacts | fundamentals bulk archive | `data_raw/free/sec/companyfacts.zip` |
| SEC Form 4 | insider transaction PIT store | `data_raw/sec/`, `data_pit/sec/form4_transactions.parquet` |
| SEC 13F | institutional holdings PIT store | `data_raw/sec/`, `data_pit/sec/institutional_13f_holdings.parquet` |
| ETF holdings | theme/ETF constituent evidence | `data_raw/etf_holdings/`, `data_pit/etf_holdings/` |
| Manifests | freshness, coverage, row counts, gaps | `manifests/free_data/`, run-local `outputs/data_freshness_contract/` |
| Research runs | branch/run-isolated outputs | `research_runs/<branch>/<run_id>/...` |

GitHub may cache these stores as an accelerator, but Drive/object storage is
the durable copy.

## Scheduled Update Chain

All cron times below are UTC; KST is UTC+9.

| Order | Workflow | Schedule | KST | Main updates |
| ---: | --- | --- | --- | --- |
| 1 | `daily_crisis_monitor.yml` | `30 22 * * 1-5` | 07:30 Tue-Sat | crisis status and macro/crisis monitor outputs |
| 2 | `sec_form4_daily_refresh.yml` | `20 23 * * 1-5` | 08:20 Tue-Sat | Form 4 raw/PIT shards and ownership signals |
| 3 | `free_data_daily_update.yml` | `30 23 * * 1-5` | 08:30 Tue-Sat | price cache, free macro/free-data manifests, optional companyfacts |
| 4 | `data_readiness_preflight.yml` | `15 0 * * 2-6` | 09:15 Tue-Sat | restore Drive lake and audit readiness without full rebuild |
| 5 | `daily_operating_selection_refresh.yml` | `15 1 * * 2-6` | 10:15 Tue-Sat | rebuild current operating target books from latest restored data |
| Monthly | `etf_holdings_monthly_refresh.yml` | `55 23 1 * *` | 08:55 day 2 KST | ETF holdings and N-PORT PIT series |
| Monthly | `adr_candidate_monthly.yml` | `20 9 2 * *` | 18:20 day 2 KST | review-only ADR candidates, no direct universe mutation |
| Quarterly window | `sec_13f_quarterly_refresh.yml` | `40 23 1-20 2,5,8,11 *` | 08:40 KST | 13F holdings during filing windows |
| Weekly evidence | `full_rebuild_manual.yml` | `0 9 * * 1` | 18:00 Mon | full broker-ledger rebuild after merge to default branch |

Manual runs remain allowed for recovery, but agents must state `[GITHUB]`
workflow, ref, inputs, and expected artifact before dispatching.

## Freshness Contract

`tools/run_data_freshness_contract.py` is the operating gate that connects the
data lake to current recommendations.

It writes:

- `outputs/data_freshness_contract/status.json`
- `outputs/data_freshness_contract/data_watermarks.json`
- `outputs/data_freshness_contract/data_snapshot_manifest.json`
- `outputs/data_freshness_contract/report.md`

Selection is blocked when hard current-selection sources are stale or missing:

- prices older than 3 calendar days
- macro/crisis source older than 3 calendar days or missing
- `data_readiness.ready_for_policy_replay=false`
- future `available_from` rows are detected
- required current operating target books are not current

Promotion is stricter than selection. Coverage warnings for ETF, SEC v1
evidence, 13F, smart-money, and top-manager layers keep
`promotion_allowed=false` until floors are met, even when
`selection_allowed=true`.

The contract is read-only. It never mutates scores, target books, gates,
portfolio sizing, cash policy, universe files, or broker actions.

## How Current Selection Uses Fresh Data

`daily_operating_selection_refresh.yml` performs the lightweight daily path:

1. restore GitHub cache and `[DRIVE]` stores;
2. hydrate `outputs/` from Drive or committed `cloud_results` when needed;
3. refresh replay price cache from monthly books;
4. rebuild `outputs/reports/operating_*_target_book.csv` with
   `--require-current-latest-target`;
5. run `audit_data_readiness.py`;
6. run `run_data_freshness_contract.py --require-current-operating-books`,
   write `outputs/daily_operating_selection_refresh/summary.json`, and only
   then enforce strict selection from the written status;
7. produce operating snapshots, user portfolio reports, and paper-only order
   previews when broker state exists;
8. upload the run artifact and sync the review bundle to
   `research_runs/<branch>/<run_id>/daily_operating_selection_refresh`.

If strict selection blocks the run, `status.json`, `report.md`,
`data_freshness_contract.log`, and the daily review-only summary remain in the
artifact. Current recommendations are `DO_NOT_USE_REVIEW_REQUIRED`.

The daily workflow also writes a `DAILY_REVIEW_ONLY.md` marker inside
`outputs/user_current/` when that directory is produced. Daily outputs sync
under `research_runs/`; they do not update canonical production outputs.

## Full Rebuild Integration

`tools/run_full_rebuild_sidecars.py` now runs data readiness and the freshness
contract before primary broker replay in operating and official paths. The
outputs are preserved in:

- GitHub artifacts (`user-operating-minimal`, `official-broker-ledger`)
- `cloud_results/full_rebuild/<date>_<mode>/data_freshness_contract/`
- Drive allowlist sync via `tools/build_gdrive_sync_manifest.py`
- local Drive helper sync via `tools/sync_cloud_to_drive.py`

In full rebuild sidecars the freshness contract is non-fatal and records
`source_context=full_rebuild_sidecar` plus
`freshness_contract_non_fatal=true`. In the daily operating refresh context,
strict selection can fail the workflow after the status/report/log have been
written.

## Review Rules

- Do not call a result current if `selection_allowed=false`.
- Do not call a result promotable if `promotion_allowed=false`.
- Do not treat Drive-only files as official without a run ID and SHA.
- Do not use latest-only data as historical PIT evidence.
- Do not live trade or mutate production automatically from this workflow.
- If a source is stale, fix the source workflow or restore path before changing
  strategy logic.

