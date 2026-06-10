# Portable Data Strategy

This project must remain usable when the local computer changes. Treat the
local checkout as replaceable. Durable state lives in GitHub plus external
storage; local folders are rebuilt or restored from manifests.

## Storage Roles

- GitHub repository:
  - Source code, workflows, configs, docs, small JSON/CSV summaries, and
    manifests.
  - Do not store large PIT parquet datasets or raw bulk archives here.
- GitHub Actions artifacts:
  - Run outputs for a specific workflow run.
  - Useful for replay verification and short-term recovery, but not the only
    long-term data store.
- Google Drive or object storage:
  - Durable large data and run bundles that must survive a laptop change.
  - Preferred home for full-rebuild outputs, replay outputs, SEC bulk archives,
    price cache bundles, and future `data_pit/` parquet files.
- GitHub Actions cache:
  - Speed-up layer for `cache_prices`, SEC/macro caches, and collector outputs.
  - It can expire; never treat it as the only copy of important data.
- Local checkout:
  - Working cache and current run output only.
  - A new machine should be able to clone the repo, restore large data from
    Drive/object storage, and continue.

## Repo Path Contract

- `data_raw/`
  - Raw or near-raw durable inputs.
  - Examples: historical universe membership, SEC companyfacts archive,
    vendor exports, raw macro inputs.
  - Free-first subpaths should follow `data_raw/free/<source>/`, as documented
    in `docs/FREE_DATA_LAKE_PLAN.md`.
- `data_pit/`
  - Point-in-time normalized datasets.
  - Target examples:
    - `prices_daily.parquet`
    - `universe_membership.parquet`
    - `fundamentals_pit.parquet`
    - `feature_store_monthly.parquet`
    - `scored_history.parquet`
  - Free-first normalized datasets should live under `data_pit/free/`.
- `manifests/free_data/`
  - Small, portable data snapshot manifests, coverage reports, PIT labels, and
    source limitations that let GitHub Actions and future machines understand
    what Drive data was restored.
- `cache_prices/`
  - Fast replay cache. Rebuildable, but expensive enough to preserve.
- `outputs/`
  - Current run workspace. Rebuildable.
- `cloud_results/`
  - GitHub Actions result mirror. Small committed summaries are useful; large
    durable run bundles should also be in Drive/object storage.

## Restore On A New Computer

1. Clone the GitHub repository.
2. Install Python dependencies from `requirements_github.txt`.
3. Pull latest branch and small `cloud_results` summaries if tracked.
4. Restore large data from Google Drive/object storage into the same relative
   paths:
   - `data_raw/`
   - `data_pit/`
   - `cache_prices/`
   - any required `outputs/companyfacts.zip` or SEC cache files
5. Run:

```powershell
py -3 tools\check_portable_data_readiness.py
```

6. If the readiness output has missing required paths, restore those first.
   If only optional caches are missing, the next full rebuild or replay can
   regenerate them.

## Daily Operation Rule

Daily GitHub workflows should use the latest available trading close and skip
when no new close exists. They should not depend on a local computer being on.
Codex heartbeat checks are only temporary notification helpers, not the system
of record.

## Backtest Rule

Daily decision backtests must distinguish:

- PIT-safe replay:
  - Uses historical universe membership and filing-accepted financial data.
  - Eligible for serious performance comparison.
- Proxy replay:
  - Uses current constituents, latest rescue lists, or incomplete historical
    fundamentals.
  - Useful for research only; label outputs as proxy/survivorship-risk.

The readiness checker does not prove PIT correctness. It only verifies that the
expected durable folders and manifests exist.

## GitHub Actions And Google Drive

GitHub Actions can use Google Drive data only after Drive authentication is
configured in repository secrets. The current workflows already use rclone with
either `GOOGLE_SERVICE_ACCOUNT_KEY` or `RCLONE_CONFIG_GDRIVE`. Run
`.github/workflows/gdrive_smoke_test.yml` after changing those credentials.

For free-first data, Actions should restore large data from Drive into
`data_raw/free/`, `data_pit/free/`, and optional caches at the start of a job,
then sync updated manifests and outputs back to Drive at the end. GitHub should
only keep small manifests and summaries.
