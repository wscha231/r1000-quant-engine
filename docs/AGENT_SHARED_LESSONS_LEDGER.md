# Agent Shared Lessons Ledger

This is the shared "mistake notebook" for Codex, Claude, GPT Pro, and any other
agent working on `wscha231/r1000-quant-engine`.

Every non-trivial task must leave a short entry here or in a linked dated
directive/report when it discovers any of the following:

- a failed test, failed workflow, or failed hypothesis
- a data entitlement, coverage, freshness, or provenance blocker
- a measurement-contract caveat that could be misread later
- a negative alpha result worth not repeating
- a security or credential-handling issue
- a meaningful positive result that changes the next step

Do not paste secrets, raw API keys, account tokens, or private credentials into
this ledger. Use secret names only.

## Entry Template

```text
### YYYY-MM-DD - short title

- Agent:
- Branch/PR/run:
- Context:
- Attempt:
- Result:
- Failure or caveat:
- Root cause:
- Reusable lesson:
- Next action:
- Do-not-repeat:
- Evidence files:
```

## Standing Rules For Agents

- Keep run287 and related strategy work research-only unless the user explicitly
  reopens production promotion.
- Do not dispatch a fullrun unless a gate explicitly requests human approval and
  the user gives it.
- Do not add new alpha hooks, tune thresholds, or edit losing dates to fit a
  known bad period.
- Frozen-book, regenerated-book, zero-yield, cash-carry, and replay-window
  results must be labeled separately.
- `pit_universe_label_clean=false` means production promotion is blocked.
- Forward-label screens are audit-only until independently validated out of
  sample.
- Forward-only API snapshots can build future evidence but cannot be pasted into
  historical 7Y backtests.
- API keys live in GitHub encrypted secrets or local environment variables, not
  repo files, chats, PR text, or artifacts.
- If a vendor echoes a key in an error body, redact before writing artifacts and
  delete affected runs/artifacts.

## Current API Access Surface

GitHub repository secrets now include these names:

- `FINNHUB_API_KEY`
- `ALPHAVANTAGE_API_KEY`
- `FMP_API_KEY`

Other agents can use them through GitHub Actions workflows or local environment
variables with the same names. They cannot read the encrypted values from the
repository, and they must not ask the user to paste keys into source files.

The active forward estimate workflow is:

- `.github/workflows/earnings_estimates_daily.yml`

Safe one-ticker smoke:

```bash
gh workflow run earnings_estimates_daily.yml \
  --repo wscha231/r1000-quant-engine \
  --ref master \
  -f tickers='AAPL' \
  -f ticker_limit=1
```

Expected contract:

- `status=completed` if enough requested tickers return forward estimates
- `available_from=fetch_date`
- `backtest_acceptance_allowed=false`
- `production_activation_allowed=false`
- `live_trading_enabled=false`

## Ledger

### 2026-07-10 - SEC identity coverage repaired and forward-only queue/ledger hardened

- Agent: Codex GPT-5.6
- Branch/PR/run:
  - branch `codex/sec-cik-coverage-20260710`
  - source backfill run `29064427303`
  - source estimate catch-up run `29028159934`
  - no new API workflow or fullrun dispatched
- Context:
  - The handoff required validation of the downloaded successful artifact,
    repair of 252 blank CIK rows, an exact-universe resumable collection queue,
    a latest-only overlay rerun, and a forward paper ledger.
- Attempt:
  - Recomputed the artifact counts and hashes, collected the current official
    SEC ticker/CIK reference plus companyfacts bulk, filled only unique blank
    CIKs, and preserved all existing CIKs.
  - Reworked the estimate add-on planner into a 993-row durable queue/checkpoint.
  - Required true forward-estimate coverage before any forward score and made
    auxiliary actual, recommendation, and lifecycle evidence explicit.
  - Started an append-only 21D/63D/126D SPY-relative paper ledger.
- Result:
  - CIK coverage improved from `741/993` to `992/993`; 251 equity names were
    filled and `CASH` remained an unmapped non-equity placeholder.
  - SEC companyfacts coverage improved from `739/993` to `990/993`, or
    `990/992` eligible equity issuers. `IBN` and `OZK` have CIKs but remain
    absent from the current companyfacts ZIP.
  - SEC ticker reference SHA-256 is
    `354f84eb0c74c56244e824cec2876815df0e5ee864212e84518c26fcc879f49c`,
    available from `2026-07-08T20:56:16Z` and ingested at
    `2026-07-10T03:07:24Z`.
  - The exact queue reports 993 total rows, 992 vendor-eligible tickers, one
    placeholder, 13 fresh successes reused, 153 missing equity snapshots, and
    826 uncovered slow-retry rows. The bounded request is 150 names: 100
    missing plus 50 rotating retries.
  - Queue seeds/checkpoints now require the exact `993/992/1` contract; zero
    disables a lane, negative limits fail, and retry rotation advances only for
    tickers the collector actually reaches.
  - Overlay v2 has 11 true forward-estimate matches. It neutralized 613 rows
    that previously received a positive forward component without an estimate,
    reports 664 auxiliary actual rows, 739 lifecycle matches, and two
    lifecycle-missing neutral rows. Top-30 additions are `NUE,QCOM`; removals
    are `FIX,WDC`. No target book changed.
  - The paper ledger captured 30 contemporaneous observations. With no local
    adjusted-price cache, all next-close references and 21D/63D/126D outcomes
    remain pending. An identical rerun left the 30-event JSONL hash unchanged.
    New observations also fail closed when their receipt is stale, and NYSE
    calendar gaps cannot be replaced by a later cached close.
  - FMP earnings-calendar 401/402/403 responses now stop after one chunk. The
    known HTTP 402 endpoint is opt-in and disabled by default.
  - SEC refreshes validate and stage the response before atomic replacement;
    the shared estimate archive is serialized across refs, and scanned outputs
    are not uploaded/synced if the manifest secret gate fails.
- Failure or caveat:
  - `pit_universe_label_clean=false`; the 993 rows are a current-universe proxy,
    not historical Russell 1000 membership.
  - True usable forward estimates remain `13/993`; FMP calendar remains `0/993`;
    Alpha Vantage delisted history remains a partial zero-row/2-byte response.
  - The downloaded backfill artifact omitted companyfacts ZIP and estimate raw
    snapshots. The SEC audit was therefore re-derived from a newly downloaded
    official bulk ZIP, while forward counts were reproduced from the separate
    successful catch-up artifact.
  - No credential value could appear in the new SEC fetch or local queue/ledger
    runs. Existing vendor errors remained redacted; only secret names are used.
  - One local audit rerun initially used the absent default
    `cloud_results/full_rebuild/latest_global_alpha_universe` path and wrote a
    `blocked_no_universe` summary. It was immediately re-run with the downloaded
    run artifact's exact `universe_coverage.csv`, listing snapshot, and separate
    estimate artifact, restoring the verified `993`-row output and original
    `741 -> 992` before/after mapping evidence.
- Root cause:
  - The prior audit relied only on CIKs already present in each latest-run file;
    251 candidate-book rows had no CIK join and `CASH` collided with a real SEC
    ticker.
  - The prior overlay treated recommendation breadth as part of a forward score
    even when `has_forward_estimate=0`.
- Reusable lesson:
  - Current SEC identity data may fill blank CIKs only when ticker-to-CIK is
    unique. Preserve and report existing conflicts such as `XOM`; never map a
    portfolio cash placeholder to an issuer.
  - A broad API queue must fail closed without an exact universe, reuse fresh
    successes, persist retry state, and keep missing coverage neutral.
  - Report true forward estimates, auxiliary actuals, recommendations, and
    lifecycle evidence as separate coverage sources.
- Next action:
  - Review the draft PR, then let the bounded scheduled archive accumulate new
    forward snapshots. Evaluate paper-ledger outcomes only as 21D/63D/126D
    windows and adjusted-price data become available.
- Do-not-repeat:
  - Do not dispatch a fullrun, retry the entitlement-blocked FMP endpoint,
    infer positive alpha from missing estimates, map `CASH`, or call the current
    993-name proxy PIT-clean.
- Evidence files:
  - `outputs/free_historical_data_coverage/summary.json`
  - `outputs/free_historical_data_coverage/sec_cik_mapping_report.md`
  - `outputs/earnings_estimate_queue_validation_20260710/summary.json`
  - `outputs/free_data_selection_overlay/summary.json`
  - `outputs/free_data_selection_overlay/report.md`
  - `outputs/free_data_forward_paper_ledger/summary.json`
  - `outputs/free_data_forward_paper_ledger/schema.json`

### 2026-07-09 - Broad estimate archive needs catch-up mode, not only one daily shard

- Agent: Codex
- Branch/PR/run:
  - branch `codex/earnings-estimate-universe-catchup-20260709`
  - PR #256
  - PR #257
  - cancelled run `29026640545`
  - successful run `29028159934`
- Context:
  - User objected that the forward estimate archive collected only about 65
    names in the latest auto-shard run.
- Attempt:
  - Kept the scheduled archive quota-safe, but added a manual all-shards
    catch-up path that combines every checked-in forward-estimate shard into one
    deduped universe file.
- Result:
  - Workflow input `catchup_all_universe_shards=true` now requests the full
    checked-in candidate universe instead of one rotating shard.
  - Archive manifest/index records `shard_id=all_shards` and
    `shard_mode=all_shards_catchup`.
  - Catch-up raises the collector error cap to avoid stopping after the first
    100 expected free-vendor coverage/entitlement errors.
  - Successful all-shards run requested 863 tickers and wrote 863 snapshot rows.
  - Only 13 tickers had true forward-estimate rows, for 1.506% estimate
    coverage.
- Failure or caveat:
  - This can consume materially more free API quota and may still return low
    usable estimate coverage.
  - Missing vendor coverage remains neutral, not bearish.
  - Current snapshots remain forward-only and cannot revise 7Y CAGR/MDD.
  - First-day archive rows do not yet provide 30/90-day revision deltas; they
    are baseline snapshots for future forward scoring.
- Root cause:
  - The previous daily schedule intentionally optimized safety over immediate
    broad coverage.
- Reusable lesson:
  - Separate safe daily rotation from explicit broad catch-up collection.
  - Label catch-up provenance so later analysis does not mix one-shard and
    all-universe coverage.
  - Broad coverage paths need a larger explicit error cap than smoke-size
    archive paths.
  - Free FMP/Finnhub coverage is not presently enough for a broad
    estimate-revision alpha source.
- Next action:
  - Feed the 13 covered names into forward paper-ledger tracking.
  - Treat broad estimate-revision alpha as data-blocked unless paid PIT
    estimates or better entitlement is added.
- Do-not-repeat:
  - Do not infer universe-wide estimate coverage from a single 50-name shard.
  - Do not treat broad catch-up as historical backtest evidence.
- Evidence files:
  - `.github/workflows/earnings_estimates_daily.yml`
  - `tools/build_forward_estimate_catchup_universe.py`
  - `tests/earnings_estimate_catchup_universe_smoke.py`

### 2026-07-10 - Forward estimate archive should refresh covered and new names incrementally

- Agent: Codex
- Branch/PR/run:
  - branch `codex/earnings-estimate-incremental-addons-20260710`
- Context:
  - User asked where estimate data is stored permanently and whether the system
    should collect only new forward data plus newly added universe tickers.
- Attempt:
  - Added an incremental add-on universe builder for the daily estimate archive.
- Result:
  - Scheduled runs keep the rotating shard, but also add known-covered tickers
    from restored archive history and current-universe tickers not yet seen in
    the archive.
  - Existing uncovered names are not all retried daily; they are retried slowly
    through the rotating shard.
- Failure or caveat:
  - Estimate snapshots are historically usable only from their
    `available_from=fetch_date` forward.
  - Pre-archive estimate history still requires a paid PIT estimate source.
- Root cause:
  - Free/current estimate APIs expose snapshots, not full historical revision
    history.
- Reusable lesson:
  - After a broad baseline catch-up, use incremental covered/new/rotating-retry
    collection instead of repeating a full all-universe pull every day.
- Next action:
  - Use the archive as forward paper-ledger evidence once enough dates exist for
    21/63/126-day outcome scoring.
- Do-not-repeat:
  - Do not call current snapshots "past data" for dates before collection.
  - Do not collect all uncovered tickers every day when a rotating retry shard is
    enough.
- Evidence files:
  - `tools/build_forward_estimate_incremental_universe.py`
  - `tests/earnings_estimate_incremental_universe_smoke.py`
  - `.github/workflows/earnings_estimates_daily.yml`

### 2026-07-10 - Same-day estimate archive writes must merge, not overwrite

- Agent: Codex
- Branch/PR/run:
  - branch `codex/earnings-estimate-sameday-merge-20260710`
- Context:
  - The durable snapshot filename is date-based:
    `data_pit/events/earnings_estimates/estimates_YYYYMMDD.parquet`.
- Attempt:
  - Added same-day merge semantics to the forward estimate collector.
- Result:
  - If a same-date snapshot already exists, the collector unions existing and
    current rows by ticker and keeps the latest row for duplicated tickers.
  - Summary/manifest/index now expose same-day merge fields.
- Failure or caveat:
  - This does not create historical estimate data before the fetch date.
- Root cause:
  - Same-day manual smokes, broad catch-ups, and incremental runs can otherwise
    overwrite a larger durable snapshot with a smaller request.
- Reusable lesson:
  - Date-partitioned durable archives need append/merge semantics whenever run
    size can vary.
- Next action:
  - Keep using one date-partition per fetch date; rely on merge fields to audit
    same-day run behavior.
- Do-not-repeat:
  - Do not let a small same-day incremental archive shrink a prior all-shards
    catch-up file.
- Evidence files:
  - `tools/collect_earnings_estimates_finnhub.py`
  - `tests/collect_earnings_estimates_smoke.py`
  - `tools/build_earnings_estimate_archive_manifest.py`

### 2026-07-09 - Estimate confirmation now requires actual forward estimate coverage

- Agent: Codex
- Branch/PR/run:
  - workflow run `28997279936`
  - branch `codex/fix-estimate-confirmation-coverage-20260709`
- Context:
  - User asked to continue setup and search for the best CAGR/MDD path.
  - A bounded forward archive was run on the latest Concentrated holdings:
    `MU,SNDK,AMD,UMC,TXN`.
- Attempt:
  - Ran the default `fmp,finnhub` estimate archive and inspected the artifact.
  - Aggregated existing run287 cheap A/B outputs into a local candidate
    inventory.
- Result:
  - Workflow run `28997279936` succeeded but returned usable forward estimates
    for only `1/5` tickers, with `AMD` covered by FMP.
  - Initial signal inspection showed non-covered tickers could still be marked
    as estimate-confirmed from positive recommendation breadth.
  - The collector and latest-confirmation helper were changed so confirmation
    requires `has_forward_estimate > 0`.
  - After the fix, only `AMD` passes latest estimate confirmation; `MU`, `SNDK`,
    `TXN`, and `UMC` are neutral.
- Failure or caveat:
  - Free vendor coverage is too low for a Concentrated confirmation decision.
  - Forward archive evidence still cannot change historical 7Y CAGR/MDD.
  - The best nominal historical candidate remains rejected on OOS CAGR.
- Root cause:
  - Recommendation breadth is not the same as forward EPS/revenue estimate
    coverage.
- Reusable lesson:
  - Missing estimate rows must be neutral, even when a vendor can return
    earnings surprises or recommendation counts.
  - Gate latest confirmation on actual forward-estimate availability, not on
    auxiliary sentiment fields.
- Next action:
  - Rotate `ALPHAVANTAGE_API_KEY` before Alpha Vantage-only smoke or
    `LISTING_STATUS` work.
  - Continue forward archive collection as paper-ledger evidence only.
- Do-not-repeat:
  - Do not count recommendation-only rows as estimate revision confirmation.
  - Do not claim historical CAGR/MDD improvement from current API snapshots.
- Evidence files:
  - `tools/collect_earnings_estimates_finnhub.py`
  - `tests/estimate_revision_features_smoke.py`
  - `tests/estimate_confirm_selection_smoke.py`
  - `outputs/run287_forward_concentrated_estimates_20260709/report.md`
  - `docs/CODEX_RUN287_CAGR_MDD_SEARCH_STATUS_20260709.md`

### 2026-07-09 - Default FMP/Finnhub estimate smoke succeeded after AV pause

- Agent: Codex
- Branch/PR/run:
  - workflow run `28994832444`
- Context:
  - After Alpha Vantage was paused pending key rotation, the user asked Codex to
    run the safe estimate workflow.
- Attempt:
  - Ran `earnings_estimates_daily.yml` on `master` for AAPL with
    `ticker_limit=1` and the default vendor order.
- Result:
  - Workflow conclusion was `success`.
  - `vendor_order=["fmp","finnhub"]`.
  - `fetch_sources=["fmp"]`.
  - `status=completed`, `estimate_coverage_ratio=1.0`, and
    `has_forward_estimate_rows=1`.
  - `backtest_acceptance_allowed=false`,
    `production_activation_allowed=false`, and `live_trading_enabled=false`.
  - Artifact scan found no raw key pattern in `summary.json` or
    `collector.log`.
- Failure or caveat:
  - This is a forward-only archive smoke, not historical CAGR/MDD evidence.
  - Alpha Vantage remains paused until key rotation is completed.
- Root cause:
  - FMP can supply at least one usable forward estimate row under the current
    free-vendor setup.
- Reusable lesson:
  - The default post-pause path can continue collecting forward archive evidence
    without calling Alpha Vantage.
- Next action:
  - Rotate `ALPHAVANTAGE_API_KEY` before any Alpha-Vantage-only smoke or
    `LISTING_STATUS` work.
- Do-not-repeat:
  - Do not treat this run as 7Y backtest acceptance.
  - Do not run broad Alpha Vantage jobs before rotation.
- Evidence files:
  - `.github/workflows/earnings_estimates_daily.yml`
  - `outputs/earnings_estimates_daily/summary.json` from run `28994832444`
  - `outputs/earnings_estimates_daily/collector.log` from run `28994832444`

### 2026-07-09 - Alpha Vantage calls paused pending key rotation

- Agent: Codex
- Branch/PR/run:
  - `codex/pause-alphavantage-until-rotation-20260709`
- Context:
  - Claude review directive identified Alpha Vantage key rotation as the only
    open credential incident after a vendor response echoed a key in a
    rate-limit body.
- Attempt:
  - Removed Alpha Vantage from the default estimate vendor order.
  - Left explicit `vendor_order='alphavantage'` available only for the bounded
    post-rotation smoke.
- Result:
  - Scheduled/default estimate archive uses FMP then Finnhub and does not call
    Alpha Vantage by default.
- Failure or caveat:
  - This does not rotate the key. The user still needs to create/install a new
    Alpha Vantage key and verify the old one is dead.
- Root cause:
  - Key exposure risk cannot be fully closed by log deletion and redaction
    alone.
- Reusable lesson:
  - Pause a vendor in default workflows when rotation is pending, even if
    redaction has been hardened.
- Next action:
  - User rotates `ALPHAVANTAGE_API_KEY`, then run a one-ticker
    Alpha-Vantage-only smoke and scan `summary.json` plus `collector.log`.
- Do-not-repeat:
  - Do not run broad Alpha Vantage jobs with the pre-rotation key.
  - Do not record any key value in this ledger, PR text, or artifacts.
- Evidence files:
  - `.github/workflows/earnings_estimates_daily.yml`
  - `tools/collect_earnings_estimates_finnhub.py`
  - `docs/AGENT_API_ACCESS_CONTRACT.md`

### 2026-07-09 - Finnhub replacement key smoke failed authorization

- Agent: Codex
- Branch/PR/run:
  - local smoke only, no workflow run
- Context:
  - User supplied a candidate replacement for `FINNHUB_API_KEY` and asked to try
    it.
- Attempt:
  - Temporarily set the candidate key in a local environment variable and ran
    the forward estimate collector with `--vendor-order finnhub` on AAPL.
- Result:
  - Finnhub returned HTTP 401 Unauthorized for `/stock/eps-estimate`,
    `/stock/revenue-estimate`, `/stock/earnings`, and `/stock/recommendation`.
  - GitHub `FINNHUB_API_KEY` was restored to the previous repository secret
    value after the failed smoke.
- Failure or caveat:
  - This is not merely lack of estimate entitlement; HTTP 401 indicates the
    candidate key itself was not accepted by Finnhub.
- Root cause:
  - Candidate key invalid, inactive, or not provisioned for the API account.
- Reusable lesson:
  - Test replacement secrets with a one-ticker local or workflow smoke before
    leaving them as the repo default.
  - Do not run broad workflows with an unverified replacement key.
- Next action:
  - If a new Finnhub key is desired, verify it on a non-sensitive endpoint first,
    then on estimate endpoints, then update the GitHub secret.
- Do-not-repeat:
  - Do not leave a failed replacement key installed in `FINNHUB_API_KEY`.
  - Do not record the key value in this ledger, PR text, or artifacts.
- Evidence files:
  - `tools/collect_earnings_estimates_finnhub.py`
  - `docs/AGENT_API_ACCESS_CONTRACT.md`

### 2026-07-09 - Forward estimate feed made usable with free vendor fallback

- Agent: Codex
- Branch/PR/run:
  - PR #242, #243, #244, #245, #246, #247
  - final safe workflow run: `28989287304`
- Context:
  - User wanted daily EPS/revenue estimate and revision data to support
    Concentrated strengthening.
- Attempt:
  - Implemented forward-only estimate archive, then promoted it to `master`.
  - Added Alpha Vantage and FMP fallbacks after Finnhub estimate endpoints were
    blocked.
- Result:
  - FMP returned usable forward estimate rows for AAPL in the final smoke.
  - Earlier 5-ticker smoke returned FMP rows for AAPL, MSFT, NVDA, AMD and no
    forward estimate for AVGO.
- Failure or caveat:
  - Finnhub `/stock/eps-estimate` and `/stock/revenue-estimate` returned 403.
  - FMP returned 402 for some tickers.
  - Alpha Vantage free tier returned rate-limit messages.
  - These snapshots are forward-only and cannot change historical CAGR/MDD.
- Root cause:
  - Vendor entitlement and free-tier coverage/rate limits.
- Reusable lesson:
  - Use multi-vendor fallback and classify partial coverage by
    `estimate_coverage_ratio`, not by the existence of any vendor error.
  - A usable row should be preserved even if another vendor failed for the same
    ticker.
- Next action:
  - Continue daily bounded archive for Concentrated candidates.
  - Use forward paper-ledger evidence until enough PIT history exists.
  - Decide later whether paid PIT estimate history is worth buying.
- Do-not-repeat:
  - Do not mark a whole feed blocked when 80%+ of requested tickers have usable
    estimates.
  - Do not treat current estimate snapshots as historical PIT data.
- Evidence files:
  - `docs/CODEX_FORWARD_EARNINGS_ESTIMATE_FEED_20260709.md`
  - `.github/workflows/earnings_estimates_daily.yml`
  - `tools/collect_earnings_estimates_finnhub.py`
  - `tests/collect_earnings_estimates_smoke.py`

### 2026-07-09 - Vendor error messages can leak API keys

- Agent: Codex
- Branch/PR/run:
  - PR #247
  - affected runs deleted: `28987731184`, `28988568483`
  - final safe workflow run: `28989287304`
- Context:
  - Alpha Vantage returned a rate-limit message that included the key in the
    response body.
- Attempt:
  - Downloaded artifacts for verification and scanned summary/logs.
- Result:
  - The final run has no raw API keys in summary/log artifacts.
- Failure or caveat:
  - Initial redaction covered `token=` and `apikey=` URL query strings but not
    body text like `API key as ...`.
- Root cause:
  - Vendors may echo credentials outside URL query parameters.
- Reusable lesson:
  - Redaction must cover URL query parameters and vendor prose messages.
  - Always scan both `summary.json` and `collector.log` before declaring a
    credentialed workflow safe.
- Next action:
  - Rotate any key that may have appeared in chat, vendor logs, or deleted
    artifacts.
- Do-not-repeat:
  - Do not persist vendor error bodies without sanitization.
- Evidence files:
  - `tools/collect_earnings_estimates_finnhub.py::sanitize_error_message`
  - `tests/collect_earnings_estimates_smoke.py`

### 2026-07-08 - Concentrated source search: current cheap sources mostly weak

- Agent: Codex plus external review synthesis
- Branch/PR/run:
  - run287 fixed-book / one-pass A/B artifacts in local `outputs/run287_*`
- Context:
  - User wanted Concentrated CAGR strengthened toward the 50% target.
- Attempt:
  - Tested several cheap or existing source paths, including 13F/Form4-style
    evidence, financial proxy screens, multisource fusion, actual-results
    one-pass, consensus variants, and best-path source searches.
- Result:
  - Several candidates were rejected or left as negative evidence.
  - Estimated revision/guidance data remained the most plausible missing source,
    but historical PIT data was not available for 7Y acceptance.
- Failure or caveat:
  - Free/current snapshots can support forward monitoring only.
  - Some apparent full-window improvements did not hold on OOS or were too
    underpowered to justify hooks.
- Root cause:
  - Missing W4/PIT estimate history and weak coverage of free evidence sources.
- Reusable lesson:
  - For Concentrated, do screen-first and fixed-book A/B before hook design.
  - Treat `present` and `capturable` as different claims.
- Next action:
  - Keep 13F/fixed-book A/B evidence separate from forward estimate archive.
  - Use forward archive to accumulate evidence rather than forcing backtest use.
- Do-not-repeat:
  - Do not combine weak signals into a hook just because each has a plausible
    story.
- Evidence files:
  - `outputs/run287_13f_fixedbook_ab/` local untracked artifacts
  - `outputs/run287_multisource_fusion_broker_ab/` local untracked artifacts
  - `outputs/run287_w4_consensus_broker_ab_cash_carry/` local untracked artifacts

### 2026-07-09 - Forward estimates must scan the broad universe, not only current holdings

- Agent: Codex
- Branch/PR/run:
  - `codex/universe-forward-estimate-scan-20260709`
  - first shard workflow run `29015925250`
- Context:
  - User correctly challenged the current-holdings-only estimate scan and asked
    whether every universe ticker should be analyzed before selection.
- Attempt:
  - Added a forward-only universe planning tool that reads broad ticker sources,
    dedupes tickers, removes non-equity placeholders, and emits shard inputs for
    `.github/workflows/earnings_estimates_daily.yml`.
  - Added an archive manifest/index writer so every future estimate archive run
    records file hashes, run metadata, coverage, and storage pointers.
  - Added scheduled shard rotation so the daily archive keeps a core watchlist
    fresh while walking the broad 858-ticker universe over time.
- Result:
  - Broad scans can now be staged from tracked candidate sources such as
    `research/entry_classifier_predictions.csv` rather than only the latest
    Concentrated names.
  - Shard 0 workflow completed successfully, but collector status was
    `blocked_partial_coverage`: only 2 of 50 requested tickers had true forward
    estimates (`AAPL`, `ADBE`).
- Failure or caveat:
  - Free API coverage can still be partial or blocked.
  - Current estimate snapshots remain forward-only and cannot restate run287 7Y
    CAGR/MDD.
- Root cause:
  - Holding-only scans create selection bias and miss replacement/missed-leader
    candidates before the data can score them.
- Reusable lesson:
  - Build broad-universe coverage first, then rank confirmed names.
  - Missing vendor coverage is neutral, not a sell/reject signal.
  - Persist snapshot hashes and run ids outside chat so future agents can
    reproduce which data was used.
  - Rotate broad universe shards gradually; do not dispatch all shards at once
    on free APIs.
- Next action:
  - Treat the current free-vendor estimate feed as coverage-blocked for broad
    alpha use unless later shards or a higher-entitlement vendor materially
    improve coverage.
  - Continue shard measurement only as a data-coverage audit; do not rank
    missing-coverage tickers negatively.
- Do-not-repeat:
  - Do not use a current snapshot archive as historical backtest evidence.
  - Do not add Alpha Vantage back into the default vendor order before key
    rotation is complete.
- Evidence files:
  - `tools/build_forward_estimate_universe_plan.py`
  - `tools/build_earnings_estimate_archive_manifest.py`
  - `tests/forward_estimate_universe_plan_smoke.py`
  - `tests/earnings_estimate_archive_manifest_smoke.py`
  - `tests/earnings_estimate_workflow_rotation_smoke.py`
  - `docs/CODEX_FORWARD_ESTIMATE_UNIVERSE_SCAN_20260709.md`

### 2026-07-06 - run287 baseline and measurement discipline

- Agent: Codex plus external review synthesis
- Branch/PR/run:
  - run287 evidence and run287 reinforcement PRs
- Context:
  - Frozen/local policy combo was stronger than the regenerated fullrun result.
- Attempt:
  - Decomposed metric-mode, window, book, and hook differences.
- Result:
  - Latest generated-book cash-carry baseline remained below targets:
    Main around 33.81% CAGR / -25.36% MDD, Concentrated around 48.41% CAGR /
    -22.96% MDD.
- Failure or caveat:
  - Cash-carry did not fully restore 35/50.
  - Regenerated-book parity was not established.
  - Main MDD was structural, not merely latest-window shock.
- Root cause:
  - Window honesty, target-book regeneration drift, and substrate/provenance
    gaps.
- Reusable lesson:
  - Do not read frozen-book results as regenerated fullrun acceptance.
  - Do not add alpha before measurement substrate is honest.
- Next action:
  - Keep generated-book acceptance separate from fixed-book diagnostics.
  - Prioritize data/provenance and forward evidence.
- Do-not-repeat:
  - Do not hide bad windows by clamping only the losing side.
  - Do not revive falsified crash-prediction or threshold-tuning levers.
- Evidence files:
  - `docs/CODEX_DIRECTIVE_POST_RUN287_REINFORCEMENT_20260706.md`
  - `docs/CODEX_POST_RUN287_ALPHA_WORKPLAN_20260706.md`
  - `outputs/run287_alpha_closure_summary/report.md`

### 2026-07-05 - Business-day audit age fixed but exchange-calendar caution remains

- Agent: Codex plus external review synthesis
- Branch/PR/run:
  - commit `15176b58` and prefullrun gate discussions
- Context:
  - Price freshness gate falsely blocked over a weekend using calendar-day age.
- Attempt:
  - Changed audit-age logic to business-day age.
- Result:
  - Weekend false-block was fixed.
- Failure or caveat:
  - Plain weekday calendars are not always exchange calendars.
  - Good Friday, Thanksgiving, Independence Day observed, and Christmas/New Year
    edges need XNYS-aware handling or loud fallback.
- Root cause:
  - Calendar-day freshness conflated record age with trading-day data staleness.
- Reusable lesson:
  - Separate record freshness from bar freshness.
  - Use XNYS/market calendar where the gate is trading-day-specific.
- Next action:
  - Keep calendar source in readiness summaries.
- Do-not-repeat:
  - Do not silently treat weekday count as market trading-day count.
- Evidence files:
  - readiness/gate docs around `CODEX_PREFULLRUN_GATE_STATUS_20260705.md`

### 2026-07-05 - Production gate separation remains mandatory

- Agent: Codex plus external review synthesis
- Branch/PR/run:
  - run287 and prefullrun governance reviews
- Context:
  - User asked whether `pit_universe_label_clean=false` blocks research fullrun
    or only production promotion.
- Attempt:
  - Verified gate separation in code and reports.
- Result:
  - Research evidence can be collected with explicit approval.
  - Production promotion, live trading, and public return claims remain blocked.
- Failure or caveat:
  - Survivorship-biased current-constituents proxy can inflate absolute CAGR.
- Root cause:
  - PIT membership data contract is not clean.
- Reusable lesson:
  - Label outputs `production_blocked_research_pass` or
    `ready_for_human_review`, not `production_ready`.
- Next action:
  - Keep PIT membership unblock as a strategic data track.
- Do-not-repeat:
  - Do not quote proxy CAGR/MDD as production acceptance.
- Evidence files:
  - run287 post-run reports
  - PIT membership audit docs

### 2026-07-13 - Public portfolio dashboard must separate executed replay from review proposals

- Agent: Codex
- Branch/PR/run:
  - `codex/run287-public-dashboard-20260713`
- Context:
  - User requested a GitHub-hosted website with daily system changes, current
    Main/Concentrated holdings and cash weights, and BUY/SELL history, with a
    custom domain to be added later.
- Attempt:
  - Replaced the GitHub Pages placeholder with a static Korean dashboard and a
    standard-library JSON exporter.
  - Added a `workflow_run` deployment lane that consumes the successful
    `Daily Operating Selection Refresh` review artifact from `master`.
  - Published the latest validated replay snapshot as of the 2026-07-10 close.
- Result:
  - The public contract contains weights, prices, normalized performance,
    replay BUY/SELL records, and review-only target deltas.
  - Share quantities, dollar account/cash values, cost basis, P&L, fees,
    secrets, and local paths are rejected before deployment.
  - The initial public snapshot reports Main 14 equities / 10.63% cash and
    Concentrated 5 equities / 16.40% cash.
- Failure or caveat:
  - The daily operating artifact does not include an executed trade ledger.
    Its `03_order_preview.csv` is a human-review proposal, not a fill record.
  - The Pages repository setting was found in legacy `master:/docs` mode and
    must be changed to `build_type=workflow` before the new deployment is used.
- Root cause:
  - Previous Pages work stopped at a placeholder and had no privacy-safe bridge
    between review artifacts and a public dataset.
- Reusable lesson:
  - Preserve last validated executed history when a daily artifact has no
    fills; never relabel order previews as trades.
  - Build public data from an explicit allowlist and fail closed on local paths,
    secret-like values, missing review flags, or production/live flags.
  - Use relative asset URLs so moving from the GitHub project URL to a custom
    domain does not require an application rewrite.
- Next action:
  - Validate the public-only Pages artifact in PR checks, change Pages source to
    GitHub Actions, merge, and verify the live URL plus the next successful
    daily artifact refresh.
- Do-not-repeat:
  - Do not publish `outputs/`, `docs/`, user_current, or broker artifacts
    directly.
  - Do not expose quantities or account dollar values on a public Pages site.
  - Do not treat a review-only target delta as an executed BUY/SELL.
- Evidence files:
  - `tools/build_public_portfolio_dashboard.py`
  - `tests/public_portfolio_dashboard_smoke.py`
  - `docs/public/`
  - `.github/workflows/pages_deploy.yml`

### 2026-07-13 - Daily forward paper fills require persistent state and next-close resolution

- Agent: Codex
- Branch/PR/run:
  - `codex/run287-daily-paper-ledger-20260713`
- Context:
  - The public dashboard retained validated replay trades because the daily
    workflow emitted order previews but no confirmed simulated fills.
- Attempt:
  - Added a private, review-only forward paper ledger that restores its last
    validated state, resolves prior pending orders at the next cached close,
    builds the next preview from the updated paper account, and enqueues only a
    changed normalized target hash.
  - Added deterministic client-order idempotency, sell-before-buy integer-share
    execution, 25 bps costs, no-negative-cash enforcement, a seven-day fill-lag
    bound, and a hash chain across fill/rejection events.
  - Wired validated state to a dedicated GitHub cache and Google Drive
    `paper_archive`, while publishing only allowlisted forward fill fields.
- Result:
  - A synthetic two-session scenario queued on the signal close, filled once at
    the next close, preserved nonnegative cash, rejected an expired missing-price
    order, detected a tampered event, and remained idempotent on rerun.
  - The public table now distinguishes `Backtest` from `Forward 모의`; private
    quantities, fees, and account dollars remain excluded.
- Failure or caveat:
  - No scheduled real-market artifact has run this code yet; synthetic success
    is not operating evidence.
  - The forward account currently records zero-yield cash for execution
    monitoring. Historical acceptance metrics retain the separate DGS3MO cash
    carry contract and must not be replaced by forward metrics.
  - Forward CAGR is underpowered until at least 252 observations and 300 elapsed
    days.
- Root cause:
  - The prior daily preview was rebuilt from the fixed historical account state
    and had no persistent pending-to-fill lifecycle.
- Reusable lesson:
  - Resolve yesterday before proposing today, persist only validated state, and
    never infer a fill from a same-day preview.
  - Target-hash idempotency is necessary to prevent unchanged target books from
    causing daily drift rebalancing.
  - Operational forward evidence measures implementation durability; it does
    not establish seven-year CAGR/MDD.
- Next action:
  - Run targeted PR validation, review the first scheduled artifact, and verify
    the next Pages deployment shows only actual forward simulated fills.
  - Use 21/63/126-session forward checkpoints and open a timestamped PIT
    estimate/guidance source procurement gate rather than retuning rejected SEC
    or downside-beta arms.
- Do-not-repeat:
  - Do not persist partial state after a failed resolver.
  - Do not publish paper quantities or account dollars.
  - Do not call forward paper fills live or broker-executed trades.
  - Do not tune the rejected Main downside-beta arm or rejected SEC source
    screen to cross an endpoint.
- Evidence files:
  - `tools/run_daily_simulated_fill_ledger.py`
  - `tests/daily_simulated_fill_ledger_smoke.py`
  - `.github/workflows/daily_operating_selection_refresh.yml`
  - `tools/build_public_portfolio_dashboard.py`
  - `tests/public_portfolio_dashboard_smoke.py`
  - `docs/RUN287_FORWARD_DURABILITY_AND_IMPROVEMENT_PLAN_20260713.md`

### 2026-07-13 - Daily publication must require a real completed session and exact closes

- Agent: Codex
- Branch/PR/run:
  - `codex/run287-daily-paper-ledger-20260713`, PR #266 update
- Context:
  - The user requested automatic portfolio and homepage updates only after the
    prior US trading close, with correct weekend and exchange-holiday handling.
- Attempt:
  - Replaced the age-only inline check with an exact NYSE calendar gate that
    recognizes holidays and early closes, requires a 90-minute settlement
    buffer, and rejects scheduled sessions older than 18 hours.
  - Added a fail-closed coverage audit for every current target, held position,
    pending-order ticker, and required benchmark before the paper ledger runs.
  - Made the Pages workflow verify that the successful daily run actually
    produced a completed-session artifact before deploying.
- Result:
  - Synthetic regular-day, too-soon, Independence Day holiday, weekend, and
    post-Thanksgiving early-close cases pass.
  - A stale single-ticker price blocks the entire portfolio/public refresh;
    exact same-session coverage passes.
  - A holiday/no-new-close run leaves the previous valid website deployed.
- Failure or caveat:
  - The first scheduled real-market artifact still must be reviewed after the
    PR is merged; synthetic calendar/price fixtures are not operating evidence.
  - Manual `force_run` may replay an older completed session, but exact-close
    coverage and paper-ledger idempotency still apply.
- Root cause:
  - The previous workflow knew a recent NYSE close existed but did not prove
    exact session-date coverage across the complete operating book, and the
    Pages follower could run after a successful holiday no-op.
- Reusable lesson:
  - Calendar completion, data availability, account marking, artifact
    publication, and Pages deployment are separate gates and must all agree on
    the same exchange session date.
- Next action:
  - Merge only after CI passes, then inspect the first scheduled artifact's
    session and close-price coverage manifests before trusting daily updates.
- Do-not-repeat:
  - Do not label a portfolio with a new as-of date using prior-session prices.
  - Do not deploy Pages from a successful workflow that emitted no completed-
    session artifact.
  - Do not turn a holiday skip into a failed trade or invented fill.
- Evidence files:
  - `tools/run_daily_market_session_gate.py`
  - `tools/validate_daily_close_prices.py`
  - `tests/daily_market_close_gate_smoke.py`
  - `.github/workflows/daily_operating_selection_refresh.yml`
  - `.github/workflows/pages_deploy.yml`

### 2026-07-13 - Partial-resize confirmation saves fees but destroys target-book alpha

- Agent: Codex
- Branch/PR/run:
  - `codex/run287-partial-resize-confirm-20260713`
  - local fixed-book replay only; no fullrun
- Context:
  - A 25bps versus 0bps upper-bound diagnostic showed enough theoretical cost
    headroom to cover the remaining headline CAGR gaps, while small trades were
    too small to matter. Monthly partial resize and reversal churn was the only
    cost bucket large enough to investigate cheaply.
- Attempt:
  - Added one fixed research-only execution mechanism: entries, full exits, and
    partial sells during a total target-gross reduction execute immediately;
    every other held-name partial resize requires the same side at two
    consecutive decisions.
  - Used integer shares, next-close fills, 25bps per side, lag at most seven
    days, the frozen generated baseline books, cash-carry as primary, and
    zero-yield sensitivity. No threshold grid was run.
- Result:
  - Control parity passed with exact Main and Concentrated trade-ledger SHA-256
    matches.
  - Main cash-carry fell from 34.4032% CAGR / -25.3619% MDD to 31.5886% /
    -27.0363%; OOS dCAGR was -14.4485pp and OOS2 dCAGR was -6.9461pp.
  - Concentrated cash-carry fell from 49.0971% / -22.9552% to 38.2025% /
    -23.5305%; OOS dCAGR was -31.9098pp and OOS2 dCAGR was -15.6199pp.
  - Zero-yield OOS and OOS2 deltas were also negative for both portfolios.
  - Main saved $5,259.96 of fees and 295 trades; Concentrated saved $21,147.52
    and 91 trades. The forgone target-weight alpha was much larger.
- Failure or caveat:
  - `REJECT_OOS_CAGR_WORSE`; this is a genuine firing arm, not a no-op.
  - The proxy universe remains `pit_universe_label_clean=false`, so even a pass
    would have remained production-blocked research evidence.
- Root cause:
  - Monthly target-weight changes contain useful allocation information. A
    generic delay treats informative conviction changes as execution noise.
- Reusable lesson:
  - Cost upper bounds identify an opportunity size, not a valid mechanism.
  - Reduce costs only when a new decision-time signal can distinguish noisy
    resizes from informative resizes; do not suppress the target book blindly.
- Next action:
  - Open the preregistered PIT estimate/guidance source lane. Continue free
    snapshots as forward paper evidence only.
- Do-not-repeat:
  - Do not retune confirmation count, add a resize threshold grid, or rename
    this as a deadband/no-trade-band arm on the same books and window.
  - Exact key:
    `target_weight_direction+partial_resize_two_signal_confirmation+generated_baseline_books+2019-06-03_2026-07-10`.
- Evidence files:
  - `docs/CODEX_RUN287_PARTIAL_RESIZE_CONFIRMATION_RESULT_20260713.md`
  - `outputs/run287_partial_resize_two_signal_20260713/summary.json`
  - `outputs/run287_partial_resize_two_signal_20260713/{main,concentrated}/{control,arm}_{cash_carry,zero_yield}/`

### 2026-07-13 - PIT estimate/guidance procurement is now fail-closed before alpha

- Agent: Codex
- Branch/PR/run:
  - `codex/run287-pit-estimate-source-gate-20260713`
  - provider-neutral local data audit only; no fullrun
- Context:
  - The remaining Main and Concentrated CAGR gaps require a genuinely new
    historical source lane. The free estimate archive is forward-only and its
    successful catch-up artifact found true estimates for only 13 of 863
    requested names.
- Attempt:
  - Preregistered one new combination:
    `pit_estimate_guidance_composite_revision_state + single_source_screen + single_source_events + 2019-06-03_2026-07-10`.
  - Added a provider-neutral gate for exact timestamps, stable IDs, source
    hashes, EPS/revenue revisions, guidance pairs, delisted coverage, OOS/OOS2
    coverage, reproduction rights, approved sample cost, and no lock-in.
- Result:
  - Do-not-repeat preflight: `ALLOWED_NEW_COMBINATION`.
  - Synthetic complete export: `READY_FOR_SOURCE_SCREEN`.
  - Synthetic date-only, chronology, schema, coverage, and lock-in faults each
    reached their intended blocked state.
  - Existing free run `29028159934`: `BLOCKED_SCHEMA`; it remains valid only as
    forward evidence and was not backfilled or scored historically.
  - Local standard PR validation passed 137 of 141 tests. The four failures are
    the existing sparse-checkout omissions; the new gate and adjacent estimate
    tests passed.
- Failure or caveat:
  - No real historical provider sample has passed yet. The new lane is data-
    ready, not alpha-ready, portfolio-ready, purchase-approved, or production-
    ready.
- Root cause:
  - A current snapshot cannot reconstruct when a historical consensus or
    guidance value became available. Ticker-only identity also cannot prove
    delisted and symbol-change coverage.
- Reusable lesson:
  - Audit schema, PIT chronology, stable identity, coverage, rights, and cost
    before joining returns or purchasing a broad license.
  - `READY_FOR_SOURCE_SCREEN` authorizes only the next research gate.
- Next action:
  - Build a deterministic 50-security sample request with at least five
    delisted stable IDs and obtain a zero-cost schema sample first.
- Do-not-repeat:
  - Do not retrofit the 13 current free snapshots into 2019-2026.
  - Do not weaken the frozen sample thresholds after seeing provider coverage
    or return labels.
  - Do not buy full-universe history before sample gate and source screen pass.
- Evidence files:
  - `tools/audit_pit_estimate_guidance_source.py`
  - `tests/pit_estimate_guidance_source_gate_smoke.py`
  - `docs/run287_pit_estimate_guidance_source_requirements.json`
  - `docs/CODEX_RUN287_PIT_ESTIMATE_GUIDANCE_SOURCE_GATE_20260713.md`

### 2026-07-14 - Long estimate/guidance outcomes and unbiased sample request frozen before labels

- Agent: Codex
- Branch/PR/run:
  - `codex/run287-long-horizon-source-contract-20260714`
  - local request preparation only; no provider call, return join, or fullrun
- Context:
  - The final research must cover the historical eligible union, not only a
    small sample or the current 993-row snapshot. The user also requested
    longer post-event trading-day outcomes.
- Attempt:
  - Froze 21/63/126/252/504-session roles before any estimate/guidance return
    labels are available.
  - Built a deterministic 50-row zero-cost schema request from the 993-row
    current research queue without using holdings or future returns.
- Result:
  - Current reference: 992 equity issuers and 64 ADR/global listings.
  - Sample: 45 current active issuers, exactly five ADR/global listings, and
    five historical-delisted provider-query slots across 13 current sector
    labels.
  - Status: `READY_ZERO_COST_SCHEMA_REQUEST_WITH_PROVIDER_DELISTED_QUERY`.
  - 252D is a powered long-confirmation gate; 504D is a powered directional
    sensitivity because endpoint censoring is material.
  - Synthetic deterministic, delisted-slot, and missing-long-horizon cases
    passed.
  - Local standard PR validation passed 138 of 142 tests. The four failures are
    the existing sparse-checkout omissions; both estimate/guidance tests passed.
- Failure or caveat:
  - The free listing artifact returned zero delisted rows. The historical union
    count remains unknown and `pit_universe_label_clean=false`.
  - No real provider sample or historical return was evaluated.
- Root cause:
  - Projecting current constituents backward would omit failed/delisted names.
    Treating unresolved 504D outcomes as zero would also bias recent events.
- Reusable lesson:
  - Separate sample procurement QA from final all-universe research.
  - Long outcomes require explicit right censoring, longer bootstrap blocks,
    and verified terminal returns for delisted securities.
- Next action:
  - Send only the zero-cost schema request. Run the source gate on the delivered
    50-security export before joining any price outcomes.
- Do-not-repeat:
  - Do not back-project the current 993 rows as historical membership.
  - Do not fill unresolved 252D/504D labels with zero or remove delisted names.
  - Do not change horizon lengths or the 2026-07-10 endpoint after results.
- Evidence files:
  - `docs/run287_pit_estimate_guidance_outcome_contract.json`
  - `tools/build_pit_estimate_guidance_sample_request.py`
  - `tests/pit_estimate_guidance_sample_request_smoke.py`
  - `docs/CODEX_RUN287_LONG_HORIZON_SAMPLE_REQUEST_20260714.md`
  - `outputs/run287_pit_estimate_guidance_sample_request_20260714/`

### 2026-07-14 - Exact-time management guidance can be scouted without vendor email

- Agent: Codex
- Branch/PR/run:
  - `codex/run287-email-free-guidance-scout-20260714`
  - bounded SEC public-data run only; no fullrun or portfolio run
- Context:
  - The user asked for a way to obtain useful PIT estimate/guidance evidence
    without emailing a commercial data provider.
- Attempt:
  - Preserved the frozen provider-neutral consensus/guidance contract.
  - Preregistered a separate management-guidance revision source lane.
  - Reused existing exact accepted-time indexes and collected only the missing
    NVS/RIO foreign-issuer submission indexes.
  - Scanned at most eight recent 8-K/6-K complete submissions for each of ten
    deterministic sample names.
- Result:
  - Do-not-repeat preflight: `ALLOWED_NEW_COMBINATION`.
  - Selected/indexed names: 10/10; ADR/global identity routes: 5/5.
  - SEC complete submissions: 80/80; exact accepted-time: 80/80.
  - Untrusted heuristic candidates: 17 filings and 42 passage rows across
    NVS, PG, RIO, VZ, and YMM.
  - Hardened offline replay verified 80/80 raw SEC acceptance headers and
    reduced the heuristic candidate set to 16 filings without using returns.
  - Status: `READY_FOR_MANUAL_SCHEMA_REVIEW`.
  - Provider email, API key, purchase, returns, portfolio A/B, fullrun,
    production, and live trading were not used.
- Failure or caveat:
  - Historical analyst consensus, stable historical membership, and verified
    delisting returns/cash proceeds remain unavailable from SEC alone.
  - Five tickers without a candidate in their latest eight filings remain
    neutral; this bounded scout does not prove complete historical absence.
  - A post-run audit found calendar-year, qualitative-outlook, physical-volume,
    one-time-effect, and republication false-positive risks. The 17 filings are
    not 17 validated revision events.
- Root cause:
  - Company guidance is public issuer disclosure, while analyst consensus and
    exchange terminal-return histories are separate proprietary or
    market-data records.
- Reusable lesson:
  - Separate public management-guidance revision semantics from analyst-
    consensus surprise semantics instead of weakening the original gate.
  - Use strict explicit guidance/outlook anchors; generic words such as
    `expected`, `projected`, `lower`, or `update` create material boilerplate
    and current-results false positives.
- Next action:
  - Label all 80 inspected filings to measure recall, apply detailed labels to
    the 16 hardened candidates, and build the EPS/revenue range, fiscal-period,
    currency, unit, and prior-guidance pairing parser.
  - Expand to all 45 active sample names only if review precision is at least
    90% and registered-schema completeness is at least 80%.
- Do-not-repeat:
  - Do not treat SEC management guidance as historical analyst consensus.
  - Do not join returns, run A/B, or expand the full archive before candidate
    precision and schema completeness pass.
  - Do not treat missing guidance as negative.
- Evidence files:
  - `docs/run287_sec_management_guidance_scout_contract.json`
  - `tools/run_sec_management_guidance_scout.py`
  - `tests/sec_management_guidance_scout_smoke.py`
  - `docs/CODEX_RUN287_EMAIL_FREE_GUIDANCE_SCOUT_RESULT_20260714.md`
  - `outputs/run287_sec_guidance_foreign_gap_index_20260714/`
  - `outputs/run287_sec_management_guidance_scout_20260714/`
  - `outputs/run287_sec_management_guidance_scout_20260714_hardened_v2/`
### 2026-07-14 - Held-security risk must be measured separately from broad-market regime

- Agent: Codex
- Branch/PR/run:
  - `codex/run287-holding-risk-watch-20260714`
  - local exact-close diagnostic for 2026-07-13; no fullrun or execution
- Context:
  - SPY remained above MA20/MA50 and the broad crisis state stayed green while
    several held semiconductor and storage names fell much more sharply.
- Attempt:
  - Registered a current/forward-only, past-quantile held-security risk watch
    with no stop, exit delay, partial resize, cluster cap, tilt, or order hook.
  - Added an idempotent daily history and exact-close workflow integration.
  - Regenerated the deterministic 50-row estimate/guidance request with a
    provider-ready no-cost message.
- Result:
  - Exact 2026-07-13 prices were available for SPY and all 15 unique holdings.
  - Main alerts: SNDK, NXT, ALAB, MRVL. Main watches: FLEX, WDC, ON, CIEN, MU,
    QCOM. Concentrated alert: SNDK. Concentrated watch: MU.
  - Estimated one-session return: Main -5.4295%; Concentrated -6.0107%.
  - The provider request remained 45 active plus five deterministic delisted
    query slots with exactly five ADR/global active names and unchanged CSV
    hashes.
  - Local standard PR validation passed 139 of 143 tests. The four failures are
    the existing sparse-checkout omissions; all new and adjacent tests passed.
- Failure or caveat:
  - This is one current event and does not prove that selling, trimming, or
    delaying buys improves CAGR/MDD.
  - No provider/contact is selected, so the request was not dispatched.
- Root cause:
  - A broad SPY crisis gate cannot identify idiosyncratic held-name damage when
    the index remains healthy. The prior workflow also lacked a persistent
    per-position forward warning archive.
- Reusable lesson:
  - Separate observation from execution. Rank held-name shock and loss
    contribution first; require forward outcomes and a separately preregistered
    broker-ledger A/B before changing weights.
  - Record data availability after the exact close, not at an earlier decision
    timestamp.
- Next action:
  - Let the daily archive accumulate and resolve 1/5/21/63/126-session outcomes.
  - Select a provider/contact and send only the zero-cost 50-row package; then
    run the frozen PIT source gate before any return join.
- Do-not-repeat:
  - Do not convert this watch into the rejected stop/exit-delay, partial-resize,
    aggregate-cluster-cap, or generic technical-risk-control mechanisms.
  - Do not tune quantiles after observing 2026-07-13.
- Evidence files:
  - `docs/run287_holding_risk_watch_contract.json`
  - `tools/build_run287_holding_risk_watch.py`
  - `tests/run287_holding_risk_watch_smoke.py`
  - `docs/CODEX_RUN287_HOLDING_RISK_WATCH_RESULT_20260714.md`
  - `outputs/run287_holding_risk_watch_20260714_close_20260713/`
  - `outputs/run287_pit_estimate_guidance_sample_request_20260714_v2/`
### 2026-07-14 - Scheduled full rebuild violated the separate-approval boundary

- Agent: Codex
- Branch/PR/run:
  - `codex/disable-scheduled-fullrun-20260714`
  - GitHub Actions incident run `29249021773`; governance fix only, no fullrun
- Context:
  - Run287 requires exact hashes and expected cost to be shown for separate
    user approval before any fullrun.
  - The nominally manual full-rebuild workflow still contained a weekly cron.
- Attempt:
  - Audited the live workflow and the failed scheduled run before editing.
  - Removed the automatic trigger and added a first-step manual approval guard.
- Result:
  - The workflow is `workflow_dispatch`-only.
  - A dispatch now requires `FULLRUN_APPROVED`, the exact dispatched commit
    SHA, a frozen source-manifest SHA-256, and expected runner minutes.
  - Blank core inputs and `alphaops_vnext_production` fail before expensive
    runner work; approved manual runs are serialized.
- Failure or caveat:
  - Run `29249021773` had already started automatically on 2026-07-13. It
    failed at `run_local.py --full` because the scheduled event supplied an
    empty `fast_mode`, after earlier setup, SEC refresh, and restore steps ran.
  - This fix does not make a future fullrun approved; it only enforces the
    prerequisites. No fullrun was used to validate the fix.
- Root cause:
  - A `schedule` trigger was combined with logic that read
    `workflow_dispatch`-only inputs. GitHub scheduled events do not populate
    those dispatch inputs.
- Reusable lesson:
  - Expensive manual workflows must not also have automatic triggers.
  - Approval evidence must be validated before checkout, collection, restore,
    or any other material runner work.
- Next action:
  - Run targeted smoke and standard PR CI, then merge this governance fix
    before integrating the SEC/CIK and risk-watch PRs.
- Do-not-repeat:
  - Do not restore a cron, `workflow_call`, or chained automatic trigger to the
    full-rebuild workflow.
  - Do not use a fullrun to test the governance guard.
  - Do not treat incident artifacts or diagnostics as a valid performance
    baseline.
- Evidence files:
  - `.github/workflows/full_rebuild_manual.yml`
  - `tests/smoke_test.py`
  - `docs/CODEX_FULLRUN_SCHEDULE_GOVERNANCE_RESULT_20260714.md`
### 2026-07-14 - Candidate-only review cannot measure SEC guidance recall

- Agent: Codex
- Branch/PR/run:
  - `codex/run287-guidance-goldset-20260714`
  - hardened v3 offline scout and dual-review packet; no fullrun or execution
- Context:
  - The hardened scout found 16 heuristic candidate filings, but reviewing only
    those rows could estimate precision and could not reveal false negatives.
- Attempt:
  - Froze all 80 bounded filings with exact acceptance, raw-header agreement,
    complete-submission SHA-256, full allowed-document text, and separate blank
    reviewer A/B files.
  - Registered EPS/revenue-only extraction fields and fixed promotion gates.
- Result:
  - Source integrity passed for 80/80 filings across 10 issuers, including all
    five ADR/global sample names.
  - The packet contains 16 heuristic candidates and 64 heuristic negatives.
  - No return or portfolio outcome label is present in the packet.
- Failure or caveat:
  - The packet is evidence ready, not a validated signal. Precision, recall,
    schema completeness, and revision-pair availability are still unknown.
  - The repository-wide smoke has six unrelated sparse-checkout failures from
    absent `aggressive/` and IWB seed files; the new and adjacent SEC tests pass.
- Root cause:
  - Candidate discovery is a retrieval heuristic. Candidate-only review
    conditions the sample on the heuristic firing and therefore hides false
    negatives and inflates apparent recall.
- Reusable lesson:
  - Freeze the complete bounded denominator and source hashes before labeling.
  - Keep reviewers blind to one another and keep market outcomes out of source
    labeling so financial results cannot influence semantic judgments.
- Next action:
  - Complete two independent 80-filing reviews, adjudicate every disagreement,
    and calculate frozen precision, recall, and registered-schema completeness.
  - Build the deterministic parser only if those gates pass; do not join returns.
- Do-not-repeat:
  - Do not label only heuristic candidates or treat missing labels as negatives.
  - Do not expand to 45 names, join returns, run A/B, or tune extraction rules
    after seeing market outcomes before the gold-set gates pass.
- Evidence files:
  - `docs/run287_sec_guidance_goldset_contract.json`
  - `tools/build_sec_guidance_goldset_packet.py`
  - `tests/sec_guidance_goldset_packet_smoke.py`
  - `docs/CODEX_RUN287_SEC_GUIDANCE_GOLDSET_PACKET_RESULT_20260714.md`
  - `outputs/run287_sec_management_guidance_scout_20260714_hardened_v3/`
  - `outputs/run287_sec_guidance_goldset_packet_20260714/`
### 2026-07-14 - SEC guidance heuristic failed frozen precision before parser work

- Agent: Codex with independent reviewer A and reviewer B agents
- Branch/PR/run:
  - `codex/run287-guidance-goldset-adjudication-20260714`
  - source-only dual review and adjudication; no returns, fullrun, or execution
- Context:
  - The 80-filing packet required two blind reviews and filing-level
    adjudication before any parser, archive expansion, or outcome join.
- Attempt:
  - Independently classified all 80 filings, reconciled exactly three filing-
    level disagreements from frozen text, and evaluated fixed precision/recall
    gates without seeing market outcomes.
- Result:
  - Agreement was 77/80. Adjudicated TP/FP/TN/FN was 13/3/61/1.
  - Recall passed at 92.86%; precision failed at 81.25% versus the fixed 90%.
  - The evaluator returned `CLOSED_SOURCE_PRECISION_OR_RECALL_GATE` and blocked
    parser work, component adjudication, 45-name expansion, returns, and A/B.
- Failure or caveat:
  - Two packet rows were unreadable because allowed attachments were not plain
    extractable text, including a uuencoded PDF payload.
  - Reviewer component counts differed materially, but resolving them cannot
    rescue the already failed mandatory filing precision gate.
- Root cause:
  - The broad text-window heuristic admitted qualitative growth language,
    physical-volume/unit-cost disclosures, and one-time transaction text while
    missing one conditional long-horizon revenue outlook.
- Reusable lesson:
  - Blind-label the entire bounded denominator and adjudicate semantic scope
    before parser tuning or market-outcome access.
  - Stop at the first failed mandatory gate; downstream schema work cannot
    repair source precision without becoming post-result retuning.
- Next action:
  - Register this exact lane as closed and move to an independent planned lane,
    such as the existing accepted-time filing-quality event or forward paper
    evidence, without reusing these rows for threshold tuning.
- Do-not-repeat:
  - Do not add special-case rules for the known NVS, RIO, VZ, or TPL rows.
  - Do not expand this heuristic to 45 names, build its parser, join returns,
    or run portfolio A/B under the same research key.
- Evidence files:
  - `docs/run287_sec_guidance_goldset_adjudication.csv`
  - `tools/evaluate_sec_guidance_goldset_reviews.py`
  - `tests/sec_guidance_goldset_review_gate_smoke.py`
  - `docs/CODEX_RUN287_SEC_GUIDANCE_GOLDSET_REVIEW_GATE_RESULT_20260714.md`
  - `outputs/run287_sec_guidance_goldset_review_gate_20260714/`
### 2026-07-14 - PR CI spends more time fetching archived rebuilds than validating

- Agent: Codex with GitHub dependency audit agent
- Branch/PR/run:
  - `codex/ci-sparse-checkout-cost-20260714`
  - read-only timing audit of PR #271 through #274 followed by workflow-only fix
- Context:
  - Repeated PR checks took about five minutes in checkout before tests or the
    portfolio guard could start.
- Attempt:
  - Compared job-step timings and measured the master Git tree by subtree.
  - Added identical cone-mode sparse checkout contracts to the two PR workflows.
- Result:
  - Seven observed checkouts across PR #271-#273 took 300-321 seconds.
  - PR #273 fetched for 289 seconds and checked out files for about 31 seconds;
    its 145 tests then took 107 seconds, while the guard's post-checkout work
    took about five seconds.
  - The 6.36 GiB master tree is approximately 99.6% `cloud_results/`, dominated
    by repeated dated full-rebuild snapshots. The bounded checkout retains all
    code/test directories and `latest_global_alpha_universe` while excluding
    dated and failed-run copies.
- Failure or caveat:
  - `fetch-depth: 1` limits history but not blobs in the current tree.
  - Sparse checkout can expose a hidden test dependency on an archived path;
    complete PR validation and guard success are mandatory before merge.
- Root cause:
  - Large run artifacts are stored as ordinary Git blobs, and the workflows
    had no sparse path filter. Push and pull-request events also run duplicate
    validation for the same open-PR SHA.
- Reusable lesson:
  - Keep immutable run archives in Actions/Drive and keep only a canonical
    manifest or latest baseline in the code checkout.
  - Optimize the checkout tree before dropping validation coverage.
- Next action:
  - Measure the sparse-checkout PR job timings and merge only if full validation
    and the portfolio guard remain green.
  - Consider removing duplicate push validation in a separate decision; do not
    combine that trigger-policy change with this data-path change.
- Do-not-repeat:
  - Do not restore the entire dated `cloud_results/full_rebuild` archive to
    automatic PR jobs merely to hide an undeclared dependency.
  - Do not rewrite Git history, delete user artifacts, or move LFS data as part
    of this reversible workflow optimization.
- Evidence files:
  - `.github/workflows/pr_validation.yml`
  - `.github/workflows/portfolio_system_guard.yml`
  - `tests/workflow_artifact_smoke.py`

### 2026-07-14 - Forward archives need exact cohorts and a durable state path

- Agent: Codex
- Branch/PR/run:
  - `codex/run287-forward-paper-ledger-recovery-20260714`
  - local recovery and targeted tests; no fullrun or execution
- Context:
  - A valid v2 forward ledger existed in an earlier commit and local outputs,
    but the source had been lost from later squash/merge history and the daily
    collector did not durably append the fixed comparison cohorts.
- Attempt:
  - Restored the original v2 overlay, ledger, tests, and manual workflow exactly
    from commit `2f3c9750`.
  - Added a fail-closed bounded price-universe builder and integrated the lane
    after the completed-NYSE-session gate in the durable estimate workflow.
- Result:
  - Exact 30-name base, 30-name overlay, and 30-name ranks 31-60 control cohorts
    are required for every new decision date.
  - The dedicated price cache contains only current cohort names, unresolved
    prior observations, and SPY and begins on 2026-07-01.
  - Existing 30 observations and their immutable event log were preserved; the
    lane remains `UNDERPOWERED` with 10 distinct true-forward tickers and zero
    resolved 63D outcomes.
- Failure or caveat:
  - The pre-v2 overlay lacks `free_data_base_selection_rank`, so it cannot be
    used to invent historical base/control membership. It remains outcome-
    refreshable but cannot seed a new fixed-cohort capture.
  - The canonical tracked score snapshot has feature date 2026-06-24. Fresh
    estimate evidence does not make that base ranking a same-day score refresh.
- Root cause:
  - Source recovery and output preservation were not coupled to a durable daily
    append path, and a candidate-only file cannot reconstruct an unselected
    control cohort.
- Reusable lesson:
  - Persist forward state in both a serialized global path and immutable per-run
    evidence. Derive comparison cohorts from the contemporaneous full ranked
    universe, never from the selected book.
  - Bound price refreshes by unresolved evidence instead of repeatedly fetching
    the entire universe.
- Next action:
  - Merge only after targeted and complete PR CI pass, seed or verify the global
    Drive state without overwriting a newer ledger, and inspect the first
    scheduled exact-cohort run.
- Do-not-repeat:
  - Do not backfill observations before their recorded source time.
  - Do not infer base or control membership from top-30 candidates.
  - Do not use FMP calendar HTTP 402, fullrun, production, or live execution for
    this lane.
- Evidence files:
  - `tools/run_free_data_forward_paper_ledger.py`
  - `tools/build_forward_paper_price_universe.py`
  - `.github/workflows/earnings_estimates_daily.yml`
  - `docs/CODEX_RUN287_FORWARD_PAPER_LEDGER_RECOVERY_RESULT_20260714.md`

### 2026-07-14 - The first durable forward run passed while vendor coverage stayed partial

- Agent: Codex
- Branch/PR/run:
  - PR #276 merge `29060b0c3731cd74b11818e17ec8af378ac2625b`
  - GitHub Actions run `29303018492`
- Context:
  - The recovered ledger needed one real completed-session execution to prove
    that cache/Drive restore, exact cohorts, bounded prices, append-only events,
    artifact upload, and Drive persistence work together.
- Attempt:
  - Dispatched the manual 16-name default watchlist on merged `master`; no
    fullrun, broad catch-up, portfolio A/B, or execution path was enabled.
- Result:
  - The run succeeded in 7m03s and used the completed 2026-07-13 NYSE session.
  - Exact 30/30/30 cohorts produced 60 unique current names, 60 new signal
    observations, and 30 next-close references for the earlier decision date.
  - The ledger now has 90 observations, 11 distinct true-forward tickers, and
    zero resolved 63D outcomes; the review state remains `UNDERPOWERED`.
  - The bounded price cache wrote 61 of 61 tickers with zero failures.
  - Current Drive ledger and overlay state matched the artifact with zero
    differences; immutable per-run copies also exist.
- Failure or caveat:
  - Only 10 of 16 requested watchlist names had true forward estimates. The
    collector reported `blocked_partial_coverage` and 18 vendor-blocked errors.
  - The queue acknowledgement was absent because this was a manual watchlist
    smoke, not an incremental 993-name scheduled queue run.
- Root cause:
  - Free vendor entitlement and symbol coverage remain incomplete even when the
    archive workflow itself is healthy.
- Reusable lesson:
  - Separate transport/workflow health from signal coverage. Partial vendor
    coverage must remain missing-neutral and must not invalidate exact cohort
    persistence or be presented as full-universe coverage.
  - A source observed after a session close must enter at the next close; the
    just-completed close cannot be reused as its reference.
- Next action:
  - Let the serialized scheduled queue continue bounded incremental collection,
    inspect the first scheduled queue manifest, and wait for frozen sample gates
    before any portfolio A/B.
- Do-not-repeat:
  - Do not promote 62.5% watchlist coverage to a 993-name coverage claim.
  - Do not use the 2026-07-13 close as the entry reference for the cohort
    observed at 2026-07-14T03:16:59Z.
  - Do not run fullrun, production, live trading, or return-driven retuning.
- Evidence files:
  - `outputs/earnings_estimates_daily_29303018492/`
  - `docs/CODEX_RUN287_FORWARD_PAPER_LEDGER_RECOVERY_RESULT_20260714.md`

### 2026-07-14 - Positive SEC event point estimates failed clustered OOS confidence

- Agent: Codex
- Branch/PR/run:
  - `codex/run287-sec-filing-quality-closure-20260714`
  - frozen existing output; no rerun, fullrun, or portfolio replay
- Context:
  - The preregistered accepted-time filing-quality event had complete output
    evidence, but its producer and smoke were lost from later squash history.
- Attempt:
  - Restored only the exact single-source producer and offline smoke from commit
    `2f3c9750`, verified frozen output and producer hashes, and audited the fixed
    power and return gates.
- Result:
  - Exact acceptance was 100% for 115,185 eligible ticker events; the source
    screen contained 113,466 unique issuer/accession events.
  - OOS and OOS2 were well powered, but their 63D filing-week bootstrap lower
    bounds were -1.2681%p and -0.6535%p. OOS 21D direction was -0.2468%p.
  - The existing `REJECT_SOURCE_SCREEN` verdict was confirmed and the exact
    combination was added to the do-not-repeat registry.
- Failure or caveat:
  - Large full-period positive-minus-negative return does not generalize with
    nonnegative clustered confidence in the registered OOS windows.
  - Current ticker identity is not PIT historical index membership.
- Root cause:
  - The accounting-improvement event has weak and unstable conditional return
    separation in recent periods despite a strong long-history average.
- Reusable lesson:
  - Apply power checks before interpretation, but do not waive clustered OOS
    confidence merely because the sample is large or the point estimate is
    positive.
  - Recover rejected-lane code only for reproducibility; never interpret code
    availability as permission to tune after outcomes.
- Next action:
  - Keep the historical SEC event lane closed. Continue forward paper evidence
    and open a portfolio A/B only for a genuinely independent source that first
    passes its frozen single-source gates.
- Do-not-repeat:
  - Do not change event component thresholds, horizons, weights, tickers, eras,
    or bootstrap units after this rejection.
  - Do not build Main veto or Concentrated replacement arms from this event.
- Evidence files:
  - `outputs/sec_filing_quality_event/source_screen_summary.json`
  - `tools/run_sec_filing_quality_event.py`
  - `docs/CODEX_RUN287_SEC_FILING_QUALITY_SOURCE_SCREEN_CLOSURE_20260714.md`

### 2026-07-14 - Current scoring needs an exact-close lane and explicit symbol lifecycle

- Agent: Codex
- Branch/PR/run:
  - `codex/run287-scored-latest-20260713`
  - local bounded refresh for completed NYSE session `2026-07-13`
- Context:
  - The canonical tracked `scored_latest.csv` still represented the prior full
    rebuild while the source price cache was split across several stale dates.
  - A current score was needed without running fullrun or changing any book.
- Attempt:
  - Restored the previously validated non-ranking feature/model/score helpers.
  - Added a source-cache-immutable incremental lane that downloads a short
    provider overlap, recomputes 42 registered technical fields, applies the
    frozen 238-feature scaler and model heads, and emits an append-only packet.
  - Ran the exact-session gate before download and required every current
    context ticker to have the 2026-07-13 close.
- Result:
  - 989/989 current-context tickers have an exact 2026-07-13 close; future
    provider rows are zero and all ticker refresh audits pass.
  - The refreshed snapshot contains 989 unique tickers, 705 columns, finite
    scores, 347 research-eligible names, and exact ranks 1 through 347.
  - All six non-ranker prediction heads are nonzero for all 989 rows. The new
    score has 0.9121 Spearman correlation on 738 names shared with the prior
    canonical snapshot.
  - The canonical score file and append-only output copy have identical SHA-256
    `9cbb6586f995b59446d4c65d67acca3c428ebfbf9c75d1e33ebde58efcf906a0`.
- Failure or caveat:
  - The first pass blocked at 988/989 because stale universe symbol `IAC` has no
    2026-07-13 quote. SEC identity and provider metadata show the same issuer
    now trades as `PPLI`; the successful pass records explicit alias
    `IAC=PPLI` and uses PPLI close 45.89 without rewriting historical identity.
  - A diagnostic overlay using the archived estimate signal snapshot has no
    local listing-status source, so 989 lifecycle rows remain missing-neutral.
    Its top-30 differences are diagnostic only.
  - Initial PR validation passed 150/151 but the new smoke could not import in
    the minimal CI image because CatBoost was loaded at module import time.
    Moving CatBoost imports into the actual scoring functions preserved runtime
    behavior and lets pure contract tests run without the optional dependency.
- Root cause:
  - Daily operations updated prices and forward evidence but did not own a
    current full-universe score refresh. Symbol lifecycle and the score audit's
    stale `pred_*` merge collision were not explicit in that path.
- Reusable lesson:
  - Fail closed on the exact completed session, preserve price caches, and put
    symbol changes in a reviewed logical-to-provider map with provenance.
  - Drop stale prediction columns before merging new model heads; otherwise
    pandas suffixes can silently route registered scoring to default zeros.
  - Heavy optional model libraries must be imported at the execution boundary,
    not at module import time, so low-cost contract CI stays usable.
  - A score observed after the close is eligible only for the next close. Never
    revise an immutable forward cohort already recorded for the same date.
- Next action:
  - Run targeted and complete CI, publish this lane, then use the refreshed
    ranking only for a separate selector-diff review. Do not mutate target
    books or the 2026-07-13 forward ledger without a new decision-time gate.
- Do-not-repeat:
  - Do not carry the 2026-07-10 IAC close into 2026-07-13.
  - Do not overwrite the Google Drive source cache or rerun full history for a
    one-session score update.
  - Do not treat the diagnostic overlay as a portfolio instruction while its
    lifecycle evidence is missing-neutral.
- Evidence files:
  - `outputs/run287_scored_latest_refresh_20260714_close_20260713/manifest.json`
  - `outputs/run287_scored_latest_refresh_20260714_close_20260713_v2/manifest.json`
  - `outputs/free_data_selection_overlay_scored_20260713_v2/summary.json`
  - `docs/CODEX_RUN287_SCORED_LATEST_REFRESH_RESULT_20260714.md`

### 2026-07-14 - Exact-close scoring still needs benchmark, macro, and accepted-time SEC completion

- Agent: Codex
- Branch/run:
  - `codex/run287-decision-complete-frame-20260714`
  - bounded current decision for completed NYSE session `2026-07-13`
- Context:
  - The 989-ticker price/technical score packet was exact-close, but benchmark
    and macro fields still represented the prior decision substrate and the
    canonical accepted-time SEC index ended at July 9.
- Attempt:
  - Restored the previously validated isolated macro, official FRED benchmark,
    exact Companyfacts, and complete-cross-section contracts.
  - Added an EDGAR daily-index prefilter that requests submissions JSON only
    for universe CIKs with relevant July 10/13 filings.
  - Rebuilt the 989-row selection context, refreshed the only new statement
    candidate (DAL), and regenerated the frozen 238-feature scaled matrix.
- Result:
  - Macro passed 9/9 market, 13/13 FRED, and 49/49 finite-column coverage.
  - Official FRED SP500 was refreshed to the latest observation available by
    the decision time, July 10; the previous five-day tolerance would have
    incorrectly accepted July 9 without fetching.
  - SEC discovery found 56 relevant filings across 49 CIKs. All 56 have exact
    acceptance, zero future rows, 55 metadata-only event rows, and one 10-Q.
  - DAL's July 10 10-Q resolved with 331 exact Companyfacts records, 271
    selected records, 35 panel rows, 71 changed shared values, and 41 changed
    frozen model inputs.
  - The final frame has 989 unique tickers, 238 model features, 100% finite
    scaled coverage, zero missing-neutral violations, and zero future rows.
  - Total bounded requests were 55; source caches, canonical SEC index,
    scored_latest, target books, and forward ledgers were not mutated.
  - Local Tier-1 PR validation passed 159/159.
- Failure or caveat:
  - The first frame attempt stopped on mixed tz-aware/tz-naive acceptance
    timestamps. The second stopped while serializing a mixed period type. Both
    append-only failure directories remain preserved; `v3` is the valid packet.
  - Current Companyfacts is current-vintage and current-decision-only. Historical
    PIT membership remains unclean, so no historical or production claim is
    permitted.
- Root cause:
  - An exact current stock close does not make global or filing-derived model
    inputs current. The older benchmark freshness gate was too permissive, and
    refreshing all 989 SEC CIKs would have hidden the real one-statement delta.
- Reusable lesson:
  - Prefilter recent EDGAR daily indexes, then fetch exact submissions only for
    matching universe CIKs. Require the latest benchmark session actually
    available at decision time, not a broad stale-day tolerance.
  - Normalize UTC storage representation before frozen feature formulas, while
    retaining the exact source instant for leakage checks.
  - Keep producer row flags false; certify completeness only in a separate
    hash-pinned manifest with ranking and portfolio actions still disabled.
- Next action:
  - Produce a separate score-only packet from the verified frame, then run the
    pinned advisory selector and 25/50/100 bps cost comparison. Do not mutate a
    target book or run fullrun.
- Do-not-repeat:
  - Do not infer a complete decision frame from current prices alone.
  - Do not accept a five-business-day-old benchmark when a newer observation
    was already publicly available.
  - Do not refresh all universe submissions when daily-index prefiltering can
    isolate the exact candidate CIKs.
  - Do not delete failed append-only outputs or promote current-vintage data to
    historical PIT evidence.
- Evidence files:
  - `outputs/run287_macro_sidecar_20260714_close_20260713/manifest.json`
  - `outputs/run287_benchmark_event_sidecar_20260714_close_20260713_v2/manifest.json`
  - `outputs/run287_recent_sec_delta_20260714_close_20260713/manifest.json`
  - `outputs/run287_recent_companyfacts_20260714_close_20260713/manifest.json`
  - `outputs/run287_current_decision_frame_20260714_close_20260713_v4/manifest.json`
  - `docs/CODEX_RUN287_CURRENT_DECISION_FRAME_20260714.md`

### 2026-07-14 - Complete current inputs must be rescored before any selector comparison

- Agent: Codex
- Branch/run:
  - `codex/run287-current-score-only-20260714`
  - score-only research packet for completed NYSE session `2026-07-13`
- Context:
  - The exact-close 989-ticker decision frame passed its data gate, but the
    prior score-only runner was tied to an older feature manifest plus a
    separate verifier and could not safely consume the new single manifest.
- Attempt:
  - Added a single-manifest, hash-pinned lane for the four frozen linear heads.
  - Verified the scaled matrix, selection context, ticker coverage, frozen
    model metadata, availability timestamps, ticker order, and independent
    matrix/engine parity before emitting any predictions.
  - Added fail-closed fixtures for a wrong manifest hash, future feature
    availability, and ranking-enabled model metadata.
- Result:
  - All 989 tickers and 3,956 prediction cells are finite; all four frozen
    heads match independent direct matrix calculations within `1e-16`.
  - The source order is preserved, network requests are zero, and no score
    sort, rank, selector, backtest, fullrun, or source/target-book mutation ran.
  - The earlier embedded predictions were finite for only 738 tickers. The
    complete missing-neutral matrix provides first-time scores for 251 tickers.
  - Local Tier-1 PR validation passed `160/160` in 238.8 seconds.
- Failure or caveat:
  - All 738 overlap rows changed in every head and overlap correlations range
    from 0.3115 to 0.8025. The embedded prior predictions are not a control
    replay because their decision substrate was incomplete and different.
  - Raw `decision_feature_complete` remains false and current ticker identity
    is not PIT historical membership.
- Root cause:
  - Price freshness and complete current-decision inputs were established in
    separate stages. Reusing embedded prior predictions would silently ignore
    the completed macro, benchmark, and accepted-time SEC/fundamental matrix.
- Reusable lesson:
  - Freeze and verify the complete decision-frame manifest first, then score
    every ticker in source order with the frozen model metadata. Treat prior
    prediction deltas as sensitivity diagnostics, never as selector evidence.
  - Independent head parity proves arithmetic only; it does not prove the
    cross-sectional score stack, eligibility, turnover, or portfolio outcome.
- Next action:
  - Run a separate pinned score-stack parity audit with ranking and selection
    still disabled. If it passes, open an advisory selector diff and
    25/50/100 bps turnover-cost review without changing a target book.
- Do-not-repeat:
  - Do not feed the old two-manifest dry-run contract with the new decision
    frame by bypassing its verifier relation.
  - Do not sort or choose securities from raw head deltas.
  - Do not interpret 989 finite predictions as historical CAGR/MDD evidence.
- Evidence files:
  - `outputs/run287_current_decision_score_only_20260714_close_20260713/manifest.json`
  - `tools/run_run287_current_decision_score_only.py`
  - `tests/run287_current_decision_score_only_smoke.py`
  - `docs/CODEX_RUN287_CURRENT_DECISION_SCORE_ONLY_20260714.md`

### 2026-07-14 - Score-stack parity must verify live prediction passthrough, not only deterministic zeros

- Agent: Codex
- Branch/run:
  - `codex/run287-current-score-stack-20260714`
  - non-ranking score-stack audit for completed NYSE session `2026-07-13`
- Context:
  - The complete 989 x 238 current-decision frame and four frozen linear heads
    had passed, but the older score-stack audit could not be trusted as a score
    control: every emitted linear and CatBoost prediction was zero.
- Attempt:
  - Froze the current decision and score-only manifests plus the older READY
    score-stack manifest as an engine-artifact anchor.
  - Removed embedded stale `pred_*` fields before joining the six current
    non-ranker heads, then verified CatBoost batch/chunk parity, adaptive
    weights, exact prediction passthrough, ticker order, and two-run registered
    stack determinism.
  - Added low-cost regression fixtures that do not require CatBoost.
- Result:
  - All six active heads are finite, nonzero, and nonconstant across 989 names.
  - Fresh prediction passthrough passed 6/6, CatBoost parity 2/2, and registered
    stack determinism 13/13.
  - The registered engine marks 347 tickers eligible; the frozen DD corporate
    action quarantine is retained. No sort, rank, selector, sizing, book write,
    backtest, fullrun, network request, or trade ran.
  - Local PR validation passed `161/161` in 340.7 seconds.
- Failure or caveat:
  - The 2026-07-10 score-stack packet's deterministic parity was a false comfort
    because both compared runs consumed the same silent zeros. Its score values
    must never be used as a parity control.
  - `decision_feature_complete` and PIT universe membership remain false. This
    output is a current advisory substrate, not historical alpha evidence.
- Root cause:
  - The context already carried prediction fields. A merge created suffixed
    columns, so registered scoring could not find the expected names and used
    its missing-column zero defaults.
- Reusable lesson:
  - Before a current model join, remove stale predictions explicitly and prove
    the fresh values survive the join. Determinism alone cannot detect a
    deterministic all-zero failure.
  - Use an older READY packet only to pin immutable engine artifacts when its
    emitted values are independently shown to be invalid.
- Next action:
  - Run a separate no-write Main/Concentrated selector audit from the immutable
    current score stack, followed by advisory turnover and 25/50/100 bps cost
    comparison. Keep target books, fullrun, and trading disabled.
- Do-not-repeat:
  - Do not merge fresh predictions into a context that still owns `pred_*`.
  - Do not accept score-stack parity without nonzero/nonconstant head activity
    and exact input-to-output passthrough checks.
  - Do not merge PR #280 or use its incomplete partial ranking as current
    selector evidence.
- Evidence files:
  - `outputs/run287_current_decision_score_stack_20260714_close_20260713/manifest.json`
  - `tools/run_run287_current_decision_score_stack_audit.py`
  - `tests/run287_current_decision_score_stack_smoke.py`
  - `docs/CODEX_RUN287_SYSTEM_FLOW_AND_SCORE_STACK_20260714.md`

### 2026-07-14 - A valid current score stack is not an executable transition plan

- Agent: Codex
- Branch/run:
  - `codex/run287-selector-no-write-20260714`
  - exact-close current selector audit for completed NYSE session `2026-07-13`
- Context:
  - The complete current decision frame and six-head registered score stack had
    passed, but holdings, current marked cash, official prior-book semantics,
    candidate relative strength, transition costs, and held-security risk had
    not yet been reconciled in one no-write gate.
- Attempt:
  - Restored the exact pinned Git-object loader, crisis-state sidecar, official
    selector adapter, and bounded SOXX price recovery from the previously
    verified policy-reproduction branch.
  - Advanced the pinned crisis state and all four selector benchmarks to the
    2026-07-13 close, then ran the official policy commit on 347 registered
    names under Main strict, Main prior-hold bridge, and Concentrated strict.
  - Compared every advisory weight with both the frozen official prior book and
    the exact-close marked account. Added 25/50/100 bps cost, concentration,
    held-risk conflict, and unassessed-new-entry diagnostics.
- Result:
  - The pinned crisis state is GREEN and deterministic. The selector itself
    used zero network requests and emitted no target book or order.
  - Main one-way turnover is 50.1923% strict and 44.7147% bridge. Concentrated
    turnover is 60.8017% and its advisory cash is 34.0937% versus 17.4686%
    marked cash.
  - Main strict has two incremental buys into WATCH/ALERT holdings, one under a
    freeze warning; the bridge has four such conflicts, two under freeze.
    Concentrated has none, but two proposed new entries are not yet covered by
    the holding-risk watch. Every scenario remains review-only.
  - Local PR validation passed `165/165` in `427.1` seconds.
- Failure or caveat:
  - This is one current date, not a policy-book sequence or historical replay.
    It cannot establish CAGR/MDD improvement or transition stability.
  - Concentrated high cash is mostly structural: risk caps leave 30.625%
    unallocated before the neutral-regime 0.95 gross multiplier raises cash to
    34.0937%.
  - Six official prior holdings are currently ineligible as new entries. The
    bridge is a transition diagnostic, not permission to grandfather them.
- Root cause:
  - Correctly rescoring the complete input substrate materially changes the
    current cross-section. Immediate execution would convert repaired data
    integrity into large turnover, cost, and candidate-risk uncertainty.
- Reusable lesson:
  - Always compare selector output with exact-close marked accounts as well as
    frozen target books; they answer different questions.
  - Include cash in one-way turnover, exclude cash from transaction fees, and
    intersect proposed incremental buys with held-security risk warnings.
  - A GREEN market crisis state does not imply full investment when name caps,
    candidate gates, and regime capacity independently constrain gross.
- Next action:
  - Build a no-order risk packet for every proposed new entry, then append
    selector observations across distinct future decision weeks. Do not choose
    a transition rule, mutate a book, or run fullrun from this one-date result.
- Do-not-repeat:
  - Do not treat a current selector projection as historical CAGR/MDD evidence.
  - Do not hide turnover by comparing only with stale target weights.
  - Do not increment ALERT/WATCH holdings or buy unassessed new entries merely
    because the market-level crisis state is GREEN.
  - Do not grid-search cash, turnover, or replacement thresholds after seeing
    this packet.
- Evidence files:
  - `outputs/run287_current_crisis_state_20260714_close_20260713/manifest.json`
  - `outputs/run287_selector_benchmark_price_20260714_close_20260713/manifest.json`
  - `outputs/run287_current_selector_no_write_20260714_close_20260713_v2/manifest.json`
  - `docs/CODEX_RUN287_CURRENT_SELECTOR_NO_WRITE_RESULT_20260714.md`

### 2026-07-14 - A candidate risk packet closes missing data, not the transition gate

- Agent: Codex
- Branch/run:
  - `codex/run287-candidate-risk-no-write-20260714`
  - exact-close proposed-new-entry risk packet for `2026-07-13`
- Context:
  - The current selector proposed seven new entries that were absent from the
    marked accounts and therefore outside the held-security risk archive.
- Attempt:
  - Derived the exact candidate union mechanically from the hash-pinned
    no-write selector comparison.
  - Reused the held-security price-feature and classification functions without
    adding candidate-specific thresholds.
  - Joined immutable long histories through 2026-07-10 to the hash-pinned
    provider increment for 2026-07-13, and verified SPY through the macro
    manifest and market-component audit.
  - Added fail-closed tests for future rows, overlap mismatch, SPY hash mismatch,
    source mutation, deterministic rerun, and non-executable safety fields.
- Result:
  - All seven candidates had exact 2026-07-13 closes and sufficient history.
    STX is ALERT; AMAT and COHU are WATCH; ARM, DELL, FTNT, and PANW are NORMAL.
  - The maximum 130-session provider overlap error was about `1.14e-7`, below
    the frozen `1e-5` ceiling. Network requests were zero and source inputs
    remained unchanged.
  - The first run archived seven events and the exact same-date rerun appended
    zero. No selector weight, target book, cash, order, backtest, fullrun, or
    production state changed.
  - Local standard PR validation passed `166/166` in `228.94` seconds.
- Failure or caveat:
  - ARM's -7.55% one-session move did not fire the narrow frozen quantile
    contract. NORMAL is not a complete company-risk review or buy evidence.
  - One date cannot establish candidate risk efficacy, transition stability,
    or CAGR/MDD improvement.
- Root cause:
  - The held-security watch intentionally covered current positions only; the
    candidate set was not known until the repaired current selector ran.
- Reusable lesson:
  - Evaluate proposed entries with the exact same preregistered contract as
    holdings, but keep candidate state separate from selector alpha and sizing.
  - Pin both long-history and current-increment hashes, validate their overlap,
    and verify the benchmark through its owning manifest before classification.
- Next action:
  - Append the unchanged selector and risk packets across distinct completed
    decision weeks. Review STX/AMAT/COHU manually, but do not retune or convert
    the warning into a forced trade rule.
- Do-not-repeat:
  - Do not treat NORMAL as buy authorization.
  - Do not tune risk thresholds after seeing the 2026-07-13 semiconductor drop.
  - Do not use this current forward packet as seven-year CAGR/MDD evidence.
- Evidence files:
  - `outputs/run287_candidate_risk_watch_20260714_close_20260713/summary.json`
  - `docs/run287_candidate_risk_watch_contract.json`
  - `tools/build_run287_candidate_risk_watch.py`
  - `tests/run287_candidate_risk_watch_smoke.py`
  - `docs/CODEX_RUN287_CANDIDATE_RISK_WATCH_RESULT_20260714.md`

### 2026-07-14 - Conditional exact-packet ingestion must not substitute another selector

- Agent: Codex
- Branch/run:
  - `codex/run287-decision-week-archive-20260714`
  - first exact-close decision observation for `2026-07-13` / `2026-W29`
- Context:
  - The no-write selector and proposed-candidate risk packets were valid, but
    no durable common archive existed for distinct-date and decision-week
    stability measurement.
- Attempt:
  - Added a frozen identity contract for the policy commit, selector contract,
    held-risk contract, candidate-risk contract, and three scenario keys.
  - Normalized decision, scenario, position/cash, and candidate-risk events into
    separate append-only histories with same-date exact-payload enforcement.
  - Wired conditional ingestion and archive persistence into the completed-close
    daily workflow after the held-risk step.
- Result:
  - The first run appended 1 decision, 3 scenarios, 50 position/cash rows, and
    7 candidate-risk rows. The exact rerun appended zero in every family.
  - There is one decision date and one ISO week, so neither the four-week early
    review nor twelve-week minimum gate is met. Archive promotion stays false.
  - A missing current-date Run287 packet records SKIPPED without overwriting the
    last READY manifest or history. Cache, GitHub artifact, and Drive persistence
    are wired under `paper_archive/run287_decision_observation_archive`.
  - Local standard PR validation passed `167/167` in `212.23` seconds.
- Failure or caveat:
  - The workflow ingests only an already validated exact Run287 packet. It does
    not yet generate the decision frame, score stack, selector, or candidate
    risk packet automatically.
  - The existing daily operating selector is semantically different and is not
    accepted as a fallback.
- Root cause:
  - The repaired Run287 current-decision stages were developed as hash-pinned
    local research tools; the daily workflow predates that pipeline and only
    produces its separate operating outputs.
- Reusable lesson:
  - Separate durable archive ingestion from upstream packet generation. A safe
    missing-input skip is better than silently changing selector semantics.
  - Exclude environment-specific paths and timestamps from same-date event
    identity, while freezing semantic rows and policy/contract identities.
- Next action:
  - Design a separate cost-audited exact Run287 packet producer workflow. Do
    not invoke fullrun or reuse the daily operating selector to fill missing
    weeks.
- Do-not-repeat:
  - Do not count a skipped day as a decision observation or decision week.
  - Do not accept an older observation after a newer archived close.
  - Do not interpret four or twelve weeks alone as promotion without resolved
    forward outcomes and a separate approval gate.
- Evidence files:
  - `outputs/run287_decision_observation_archive/manifest.json`
  - `docs/run287_decision_observation_archive_contract.json`
  - `tools/archive_run287_decision_observation.py`
  - `tests/run287_decision_observation_archive_smoke.py`
  - `docs/CODEX_RUN287_DECISION_OBSERVATION_ARCHIVE_RESULT_20260714.md`

### 2026-07-14 - Exact packet automation must require an explicit same-close registry

- Agent: Codex
- Branch/run:
  - `codex/run287-exact-packet-producer-20260714`
  - zero-network selector/risk replay for the 2026-07-13 close
- Context:
  - The decision archive could ingest a validated packet but could not create
    the no-write selector and proposed-candidate risk pair.
- Attempt:
  - Added a hash-pinned input-registry contract separating the expensive
    decision-frame/score-stack refresh from the zero-network selector/risk
    stage.
  - Added portable manifest and price-map resolution that verifies content
    hashes before replacing stored Windows paths.
  - Wired the daily workflow to use producer paths explicitly and disabled
    discovery fallback when the producer is not ready.
  - Hardened archive contract hashing against Windows checkout line-ending
    conversion by requiring both the committed Git blob hash and parsed JSON
    equality.
- Result:
  - The actual 2026-07-13 producer reproduced three scenarios and the same
    seven proposed entries in about 17.9 seconds with zero network requests.
  - The exact rerun reused the existing packet. Archive ingestion appended zero
    in all four history families because the normalized decision was identical.
  - Missing registry skips; stale or changed registry blocks. No target book,
    order, backtest, fullrun, production, or live-trading state changed.
  - Local standard PR validation passed `168/168` in `225.10` seconds.
- Failure or caveat:
  - The daily workflow still needs the upstream exact-close decision frame,
    score stack, crisis/benchmark inputs, and registry to be produced for each
    date. This change does not claim that expensive half is automated.
- Root cause:
  - The valid local research packet used hash-pinned but environment-specific
    paths, while the daily workflow had neither a semantic input handoff nor a
    safe way to distinguish current Run287 inputs from its separate operating
    selector.
- Reusable lesson:
  - Split costly source refresh from deterministic portfolio projection, but
    join them through one exact-date hash registry rather than path discovery.
  - A restored packet is not current evidence unless its registry, close date,
    source hashes, and prior producer provenance all match.
- Next action:
  - Build the bounded upstream input-registry producer with explicit SEC and
    market request ceilings; do not run fullrun or silently reuse a prior-date
    registry.
- Do-not-repeat:
  - Do not accept a same-date packet solely because its directory name matches.
  - Do not fall back to the daily operating selector when Run287 inputs are
    missing.
  - Do not count producer automation as historical CAGR/MDD improvement.
- Evidence files:
  - `docs/run287_exact_packet_producer_contract.json`
  - `tools/run_run287_exact_packet_producer.py`
  - `tests/run287_exact_packet_producer_smoke.py`
  - `docs/CODEX_RUN287_EXACT_PACKET_PRODUCER_RESULT_20260714.md`

### 2026-07-14 - Exact input publication must be explicit and immutable by close

- Agent: Codex
- Branch/run:
  - `codex/run287-upstream-input-registry-20260714`
  - actual 2026-07-13 registry and fresh-root selector/risk replay
- Context:
  - The exact packet producer was deterministic after a registry existed, but
    the validated local registry was hand assembled and the daily workflow
    could not safely distinguish one of several similarly named manifests.
  - The 2026-07-13 semiconductor shock also raised pressure to change portfolio
    risk rules before the one-date warning had resolved outcomes.
- Attempt:
  - Added an explicit twelve-path source-bundle contract and a zero-discovery,
    zero-network registry builder.
  - Validated dynamic status/date/safety fields, required manifest output
    hashes, all 363 price-map sources, and six frozen input hashes.
  - Added immutable dated publication, exact rerun reuse, same-date collision
    blocking, older-date blocking, and safe missing-bundle behavior.
  - Wired the registry attempt between the held-risk watch and exact packet
    producer in the daily completed-close workflow.
- Result:
  - The actual registry built in about 0.33 seconds with zero failures and hash
    `f592436927f961ea717467c1db90bab4d4909d18281db9b94ab3758d1fb655c4`.
  - A fresh packet replay completed in about 11.47 seconds with three scenarios
    and the same seven candidates. Selector output matched the prior packet on
    50 rows/15 semantic columns; candidate risk matched on 7 rows/53 semantic
    columns.
  - The 2026-07-13 marked accounts remained Main -5.4295% and Concentrated
    -6.0107% for the session. Broad crisis stayed GREEN, while ALERT weights
    were 26.0836% and 27.7027%, respectively. SNDK generated about 62.6% of the
    Concentrated session loss.
  - No network request, target-book write, order, backtest, fullrun, production,
    live-trading, cash-policy, or selector-weight mutation occurred.
  - Full local PR validation passed `169/169` in `236.11` seconds.
- Failure or caveat:
  - The workflow still needs an upstream producer to publish the exact source
    bundle for each completed close. The builder intentionally does not infer
    paths from directory names.
  - One shock does not prove that an exit, trim, replacement, or cash change
    improves forward or historical CAGR/MDD.
- Root cause:
  - Operational reproducibility and alpha evidence are separate bottlenecks.
    The first required a deterministic handoff; the second still requires
    resolved forward observations or a true historical PIT source.
- Reusable lesson:
  - Freeze explicit upstream paths and their internal outputs before running a
    selector. Never use latest-file discovery to bridge research stages.
  - Security-level warnings can be severe while the broad crisis state is
    green, but observation alone is not authority to change a book.
- Next action:
  - Build the bounded upstream source-bundle orchestrator without fullrun.
  - In parallel, continue the unchanged weekly observation archive and advance
    the timestamped PIT estimate/guidance source gate; do not wait for twelve
    weeks to perform data-source validation.
- Do-not-repeat:
  - Do not turn the 2026-07-13 shock into a tuned stop, partial resize, cluster
    cap, generic technical-risk rule, or immediate portfolio replacement.
  - Do not count registry automation as CAGR/MDD improvement.
  - Do not overwrite an immutable same-date registry after any input changes.
- Evidence files:
  - `docs/run287_exact_packet_input_source_bundle_contract.json`
  - `tools/build_run287_exact_packet_input_registry.py`
  - `tests/run287_exact_packet_input_registry_smoke.py`
  - `docs/CODEX_RUN287_EXACT_PACKET_INPUT_REGISTRY_RESULT_20260714.md`

### 2026-07-14 - Premium estimate metadata is not PIT or sample entitlement

- Agent: Codex
- Branch/run:
  - `codex/run287-nasdaq-zeeh-sample-20260714`
  - local `20260714_local_preflight`
- Context:
  - Historical analyst-consensus revisions remain the principal external-data
    gap after the accepted-time SEC management-guidance source lane failed its
    preregistered precision gate.
  - Nasdaq Data Link exposes public metadata for the premium ZACKS/EEH history
    table, whose primary key includes `obs_date`, but a prior keyless data
    request returned HTTP 403.
- Attempt:
  - Added a secret-safe probe limited to two HTTP requests and 50 returned
    rows, with append-only raw evidence and SHA-256 provenance.
  - Registered fail-closed checks for row limits, future dates, duplicate
    provider keys, exact timestamp coverage, stable identity, delisted fields,
    ADR identity, and immutable collisions.
  - Ran the local preflight without a configured provider key.
- Result:
  - The local status was `BLOCKED_CREDENTIAL_MISSING` with exactly zero HTTP
    requests and no provider charge or trial activation.
  - Fixture validation passed for missing-key, entitlement, 50-row, date-only,
    future-row, row-limit, redaction, idempotence, and collision paths.
  - Full local PR validation passed `170/170` in `214.76` seconds.
  - Return joins, source screen, portfolio A/B, book mutation, orders, fullrun,
    production, and live trading remained prohibited.
- Failure or caveat:
  - No entitled sample has been received, so actual EEH columns, stable-ID,
    delisted, ADR, and exact timestamp coverage remain unverified.
  - A date-only `obs_date` cannot satisfy the existing 100% exact-timestamp
    source gate and must not be promoted by assigning a synthetic time.
- Root cause:
  - Public premium-table metadata proves the dataset identity, not data access
    or Run287's PIT and historical-universe requirements.
- Reusable lesson:
  - Separate schema-review readiness from source-screen readiness.  A 50-row
    response is evidence for procurement only until exact availability and
    historical security identity pass the frozen audit.
  - Missing credentials should make zero requests; entitlement failures should
    stop after one bounded attempt and never leak the key into artifacts.
- Next action:
  - If an existing self-service ZEEH-entitled key becomes available, run one
    bounded sample probe and audit its real columns.  Do not authorize a paid
    purchase from metadata alone.
- Do-not-repeat:
  - Do not retry the same keyless ZACKS/EEH data request.
  - Do not coerce `obs_date` to a fabricated exact timestamp.
  - Do not infer stable delisted or ADR identity from a current ticker.
  - Do not join returns or run portfolio A/B from a schema sample.
- Evidence files:
  - `docs/run287_nasdaq_zeeh_sample_contract.json`
  - `tools/probe_run287_nasdaq_zeeh_sample.py`
  - `tests/run287_nasdaq_zeeh_sample_smoke.py`
  - `docs/CODEX_RUN287_NASDAQ_ZEEH_SAMPLE_PROBE_RESULT_20260714.md`
  - `outputs/run287_nasdaq_zeeh_sample/20260714_local_preflight/`
  - `outputs/run287_exact_packet_input_registry_20260714_local/`

### 2026-07-14 - Risk warnings need resolved downside and recovery outcomes

- Agent: Codex
- Branch/run:
  - `codex/run287-risk-outcome-strengthening-20260714`
  - local `run287_risk_outcome_archive_20260714_local`
- Context:
  - The exact-close held and candidate risk watches produced review states, but
    every archived candidate row remained `UNRESOLVED` and there was no tool to
    learn whether warnings predicted additional weakness or a strong rebound.
  - Converting the 2026-07-13 semiconductor shock directly into a stop, exit,
    resize, cluster cap, or cash rule would repeat rejected hindsight tuning.
- Attempt:
  - Added a separate append-only outcome archive for held and proposed-candidate
    risk observations.
  - Frozen adjusted-close/SPY outcomes at 1, 5, 21, 63, and 126 sessions, with
    signal-close and next-close-actionable metrics kept separate.
  - Added return, excess return, maximum drawdown, maximum gain, and trough
    recovery so downside protection and right-tail CAGR cost are both visible.
  - Wired an unresolved-only daily price queue with a 150-ticker hard cap,
    GitHub persistence, and Google Drive persistence when configured.
- Result:
  - The first 2026-07-13 capture recorded 26 immutable observations: 19 held
    and seven candidate rows across six ALERT, nine WATCH, and 11 NORMAL states.
  - The bounded queue contains 22 securities plus SPY.  Forward outcomes are
    correctly zero because no session after the signal close had elapsed at
    the fixed as-of date.
  - Missing initial source safely skips; restored prior signals continue to
    resolve even when a later exact packet skips.
  - Targeted risk, archive, workflow, and direct-fullrun tests pass.
  - Full local PR validation passed `171/171` in `216.25` seconds.
  - No book, cash, order, historical CAGR/MDD, fullrun, production, or live
    trading state changed.
- Failure or caveat:
  - The first 1D outcome is unavailable until the 2026-07-14 close; the first
    63D endpoint is 2026-10-09.
  - One week and zero resolved outcomes cannot select an execution mechanism.
- Root cause:
  - Warning generation and performance evidence were separated by a missing
    outcome-resolution step.  Without recovery metrics, a naive MDD defense
    could discard right-tail winners and reduce CAGR.
- Reusable lesson:
  - Evaluate both maximum subsequent drawdown and recovery/right-tail return
    before proposing a defensive action.
  - Preserve old unresolved observations even when today's upstream packet is
    absent; a source skip must not stop elapsed outcomes from resolving.
  - Separate signal-close predictiveness from next-close tradability.
- Next action:
  - Continue bounded daily collection.  Review 1D only as a diagnostic, 21D as
    early direction, and 63D only after the frozen 12-week and sample gates.
- Do-not-repeat:
  - Do not claim the watch avoided the loss that occurred before it was built.
  - Do not tune thresholds from the 2026-07-13 shock.
  - Do not turn one warning or one horizon into a stop/exit/resize/cash rule.
  - Do not zero-fill missing or delisted price paths.
  - Do not count forward outcome evidence as seven-year CAGR/MDD proof.
- Evidence files:
  - `docs/run287_risk_outcome_archive_contract.json`
  - `tools/resolve_run287_risk_outcomes.py`
  - `tests/run287_risk_outcome_archive_smoke.py`
  - `docs/CODEX_RUN287_RISK_OUTCOME_ARCHIVE_RESULT_20260714.md`
  - `outputs/run287_risk_outcome_archive_20260714_local/`

### 2026-07-15 - Restored candidate artifacts do not reopen a failed source lane

- Agent: Codex
- Branch/run:
  - `codex/run287-next-ab-readiness-20260715`
  - local `run287_next_single_ab_readiness_20260715_local`
- Context:
  - The next Main or Concentrated experiment must preserve the source-screen,
    fixed-book, then generated-book sequence while avoiding another expensive
    OOS-negative arm.
  - The current checkout did not visibly contain the large original candidate
    CSVs under its own `outputs/`, which made the Concentrated blocker
    ambiguous.
- Attempt:
  - Located the official run `28725350727` artifacts in the existing local
    workspace and independently hashed the raw candidate book, SEC-enriched
    candidate book, selector metadata, target-generation manifest,
    long-crisis payload, and long-crisis thresholds.
  - Added a fail-closed readiness audit that accepts at most one preregistered
    arm, checks the do-not-repeat registry, and distinguishes source-data,
    source-screen, fixed-book, generated-book, and forward mechanism-review
    gates.
  - Audited current public Alpha Vantage, Intrinio, and Nasdaq Data Link
    documentation before authorizing any paid data action.
- Result:
  - All six local artifact hashes exactly matched the frozen evidence manifest;
    generated-book substrate status is `READY`.
  - Historical A/B status is `BLOCKED_NO_ELIGIBLE_SINGLE_AB`: both SEC lanes
    are terminally closed and no external PIT source has passed both the data
    gate and a separate alpha screen.
  - The SEC guidance keyword scout was added to the machine-readable
    do-not-repeat registry after its 81.25% precision missed the 90% gate.
  - Public vendor schemas do not yet prove exact historical availability plus
    stable delisted/ADR identity. No email, signup, purchase, provider request,
    return join, A/B, backtest, or fullrun was performed.
  - Full local PR validation passed `173/173` test files in `230.81` seconds.
- Failure or caveat:
  - Restoring candidate artifacts removes a reproducibility blocker but creates
    no new alpha. It cannot override a failed source screen.
  - The current forward risk archive has only one decision week and no elapsed
    63D sample, so it cannot select an execution mechanism.
- Root cause:
  - Artifact availability and signal validity are independent gates. Treating
    an absent copy in one `outputs/` tree as the portfolio blocker obscured the
    actual terminal SEC evidence.
- Reusable lesson:
  - Verify frozen hashes across preserved local workspaces before declaring a
    generated-book substrate missing.
  - A schema sample can open only source screening; source alpha must pass
    before fixed-book, and fixed-book must pass before generated-book.
  - Paid request capacity is irrelevant when the schema does not prove exact
    point-in-time availability and historical security identity.
- Next action:
  - Continue the bounded forward archive. If an already-entitled ZACKS/EEH key
    appears, run exactly one 50-row probe; otherwise accept only a zero-cost
    provider sample against the frozen contract.
  - After a provider reaches `READY_FOR_SOURCE_SCREEN`, run one preregistered
    single-source screen. Only one winning arm may open the fixed-book gate.
- Do-not-repeat:
  - Do not run the rank/RS/revenue candidate replacement audit; it matches the
    rejected `rank_rs_or_revenue + replacement_rule` family and uses forward
    labels to choose a best rule.
  - Do not reopen SEC filing quality or retune the SEC guidance keyword scout.
  - Do not buy Alpha Vantage, Intrinio, Nasdaq, FMP, or another feed before a
    free 50-row exact-time and identity sample passes.
  - Do not treat forward 1D or 63D review evidence as historical CAGR/MDD proof.
- Evidence files:
  - `docs/run287_next_single_ab_readiness_contract.json`
  - `tools/audit_run287_next_single_ab_readiness.py`
  - `tests/run287_next_single_ab_readiness_smoke.py`
  - `docs/CODEX_RUN287_NEXT_SINGLE_AB_READINESS_RESULT_20260715.md`
  - `docs/CODEX_RUN287_PIT_PROVIDER_COST_SCREEN_20260715.md`
  - `outputs/run287_next_single_ab_readiness_20260715_local/`

### 2026-07-14 - A forward ledger needs an explicit first seed

- Agent: Codex
- Branch/run:
  - `codex/run287-first-risk-outcome-20260715`
  - failed scheduled run `29305572139`
- Context:
  - PR #290 made risk outcomes append-only and persistent, but the most recent
    daily workflow had failed before any validated paper state could be saved.
- Attempt:
  - Inspected the failed GitHub Actions job and traced the first hard error to
    `FileNotFoundError: missing bootstrap account for main`.
  - Added a fail-closed one-time seed from the unchanged target books and exact
    completed-session adjusted closes, with fixed USD 100,000 research notional,
    integer shares, 25 bps contract metadata, and residual cash.
  - Kept historical broker replay and fullrun out of the daily workflow.
- Result:
  - The bootstrap can start the review-only next-close ledger even when no
    `outputs/broker_replay/*` artifact was restored.
  - Existing state wins; a frozen bootstrap is reused exactly; partial event
    evidence without account state blocks instead of resetting history.
  - No target book, target weight, production state, order, or live-trading
    path is changed.
  - Full local PR validation passed `172/172` in `216.31` seconds.
- Failure or caveat:
  - The seed is a current-close starting assumption, not an actual historical
    fill record. Only subsequent next-close events are true-forward simulated
    fills.
  - Historical CAGR/MDD remains unchanged; this repair only enables the
    evidence archive needed for a later mechanism review.
- Root cause:
  - The scheduled workflow implicitly depended on a fullrun-produced broker
    account that was absent from both restored state channels.
- Reusable lesson:
  - Forward paper systems need a labeled genesis state that is independent of
    optional historical artifacts, exact-close verified, and never recreated
    after an event chain begins.
- Next action:
  - Validate the focused smoke and full PR suite, publish a draft PR, and run
    the completed-close workflow after the 2026-07-14 settlement buffer.
- Do-not-repeat:
  - Do not describe the bootstrap as an actual fill.
  - Do not backfill trades or use a prior-session price to force initialization.
  - Do not reset a paper ledger because its account file is missing.
  - Do not count this operational repair as historical CAGR/MDD improvement.
- Evidence files:
  - `tools/bootstrap_run287_daily_paper_accounts.py`
  - `tests/run287_daily_paper_bootstrap_smoke.py`
  - `docs/CODEX_RUN287_DAILY_PAPER_BOOTSTRAP_RECOVERY_RESULT_20260714.md`

### 2026-07-15 - The first forward horizon must be visible but cannot become a rule

- Agent: Codex
- Branch/run:
  - `codex/run287-risk-1d-diagnostic-20260715`
- Context:
  - The archive already froze and resolved 1D outcomes, but automatic group
    summaries exposed only 21D and 63D results.
- Attempt:
  - Added contract-driven 1D, 21D, and 63D warning-versus-normal summaries.
  - Labeled 1D as diagnostic-only and kept the mechanism review gate fixed at
    63 trading days.
  - Added report and smoke assertions that 1D next-close actionable metrics
    remain not applicable.
- Result:
  - The first completed 1D close can now be reviewed without an ad-hoc
    spreadsheet or threshold change.
  - The change affects measurement output only; no stop, exit, resize, cash,
    order, target-book, selector, backtest, fullrun, production, or live path
    is changed.
- Failure or caveat:
  - One decision week and one trading-day outcome are underpowered and cannot
    establish a CAGR or MDD improvement.
- Root cause:
  - Outcome capture and early-horizon diagnostic visibility were implemented
    separately, leaving the first frozen endpoint out of the summary.
- Reusable lesson:
  - Expose preregistered early diagnostics automatically, while keeping their
    inability to promote a portfolio mechanism explicit and test-enforced.
- Next action:
  - Resolve the 2026-07-14 close after the settlement buffer, review the 1D
    warning-versus-normal direction, and continue collecting toward the frozen
    21D direction and 63D mechanism-review gates.
- Do-not-repeat:
  - Do not tune risk thresholds from the first 1D cross-section.
  - Do not treat same-close 1D evidence as an actionable next-close return.
  - Do not use 1D direction to change portfolio weights or cash.
- Evidence files:
  - `docs/run287_risk_outcome_archive_contract.json`
  - `tools/resolve_run287_risk_outcomes.py`
  - `tests/run287_risk_outcome_archive_smoke.py`

### 2026-07-15 - Vendor entitlement failures need evidence-specific cost control

- Agent: Codex
- Branch/run:
  - `codex/run287-estimate-entitlement-circuit-20260715`
  - audited scheduled artifact `29304288757`
- Context:
  - The valid 993-name incremental queue selected 150 names but the collector
    stopped after 36 because 102 raw vendor errors exhausted `max_errors=100`.
- Attempt:
  - Added a run-scoped, repeated-signature circuit for global estimate endpoint
    authorization failures and split raw errors from the collector safety
    budget.
  - Initially considered 401/402/403 equivalent, then rejected that design
    after the real artifact showed valid FMP estimate rows in the same batch as
    repeated FMP 402 rows.
- Result:
  - Only identical 401/403 endpoint signatures across three distinct tickers,
    with zero accessible responses from that vendor, can open the circuit.
  - FMP 402 remains visible as a warning-only coverage miss and cannot stop the
    queue; valid partial FMP rows remain discoverable.
  - Summary, archive manifest, and append-only index record circuit decisions,
    raw versus budget errors, warning-only errors, and avoided requests.
  - Focused collector, queue, and manifest smokes passed. Full local PR
    validation passed `173/173` in `219.26` seconds. No live provider run was
    dispatched.
- Failure or caveat:
  - The next scheduled artifact is still required to measure the real avoided
    request count and verify all 150 selected names are acknowledged.
  - This is forward-data infrastructure, not historical alpha or a CAGR/MDD
    change.
- Root cause:
  - A single undifferentiated error cap treated partial symbol coverage and
    global endpoint denial as the same failure, repeatedly spending calls on a
    globally denied endpoint while stopping a partially useful vendor early.
- Reusable lesson:
  - Never infer a global provider block from a status code alone when the same
    run contains successful rows from that provider.
  - Keep raw errors immutable, but use an evidence-specific operational budget
    so expected coverage misses do not starve a bounded universe queue.
- Next action:
  - Let the next scheduled archive run validate the circuit without a manual
    paid/provider dispatch, then audit selected, attempted, acknowledged,
    estimate-row, and avoided-request counts.
- Do-not-repeat:
  - Do not persist a global vendor disable from one run.
  - Do not trip on FMP 402 while partial successful symbols exist.
  - Do not hide warning-only coverage misses from the archive.
  - Do not describe queue completion as CAGR/MDD evidence.
- Evidence files:
  - `tools/collect_earnings_estimates_finnhub.py`
  - `tools/build_earnings_estimate_archive_manifest.py`
  - `tests/collect_earnings_estimates_smoke.py`
  - `tests/earnings_estimate_archive_manifest_smoke.py`
  - `docs/CODEX_RUN287_ESTIMATE_QUEUE_COST_CONTROL_RESULT_20260715.md`

### 2026-07-15 - Exact daily packets need a portable upstream source bundle

- Agent: Codex
- Branch/run:
  - `codex/run287-exact-source-bundle-orchestrator-20260715`
  - local portable validation for the 2026-07-13 close
- Context:
  - The exact registry, selector/risk producer, append-only observation archive,
    and outcome resolver existed, but the daily workflow never created their
    required twelve-path source bundle.
  - Frozen selector manifests referenced 363 exact historical parquet files
    whose hashes differ from current cache files.
- Attempt:
  - Added a ten-stage, explicit-path, bounded upstream orchestrator and an
    immutable source-bundle publisher.
  - Built a deterministic hash-indexed static archive, uploaded it under the
    Drive `research_static` folder, added collision-safe restore logic, and
    cached the archive after its first workflow download.
  - Added same-date validated reuse so a retry performs zero provider calls.
- Result:
  - Static archive SHA-256 is
    `66ca4b6a6a61cb7e9a3a47e2f6d26aa42f30a9b96a25d07699c6cdeb8faf1d84`;
    it contains 387 verified files including all 363 frozen price sources.
  - Isolated real-data portability produced a READY input registry with zero
    contract failure and all 363 price hashes matching.
  - A no-network preflight found all inputs for the 993-name universe and
    estimated 25 price batches.
  - Full local PR validation passed `175/175` in `218.29` seconds.
- Failure or caveat:
  - This automation creates forward evidence; it does not improve historical
    CAGR/MDD by itself and does not reopen either failed historical SEC lane.
  - The first scheduled completed-close artifact is still needed to verify the
    Linux runner's real stage counts and first automatically archived packet.
- Root cause:
  - Downstream fail-closed consumers were automated before their expensive,
    path-sensitive upstream manifests and frozen price substrate were made
    portable.
- Reusable lesson:
  - Preserve frozen evidence by exact hash; never substitute a same-name current
    cache file for an old source manifest.
  - Put large immutable research anchors in a verified archive with a fixed
    hash, then cache it; keep dynamic same-close inputs outside that archive.
  - A same-date retry should revalidate and reuse immutable evidence with zero
    calls, not create a second data cut after seeing the first result.
- Next action:
  - Let the next post-settlement scheduled daily workflow produce the first
    automatic exact packet, then audit stage statuses, request counts, registry,
    observation archive, and resolved 1D diagnostic without changing a rule.
  - Continue waiting for the existing 21D direction and 63D mechanism-review
    gates and for a separate historical PIT source-screen winner.
- Do-not-repeat:
  - Do not discover a selected book's source inputs by latest directory or
    basename.
  - Do not replace any of the 363 frozen price files with a newer cache byte.
  - Do not manually dispatch before the market-close settlement buffer or rerun
    a valid same-date bundle.
  - Do not call this infrastructure change a historical CAGR/MDD improvement.
- Evidence files:
  - `docs/run287_exact_packet_upstream_plan.json`
  - `tools/build_run287_exact_packet_source_bundle.py`
  - `tools/run_run287_exact_packet_upstream.py`
  - `tools/build_run287_exact_static_archive.py`
  - `tools/restore_run287_exact_static_archive.py`
  - `tests/run287_exact_packet_source_bundle_smoke.py`
  - `tests/run287_exact_packet_upstream_smoke.py`
  - `docs/CODEX_RUN287_EXACT_PACKET_UPSTREAM_RESULT_20260715.md`

### 2026-07-15 - Scheduled evidence needs one explicit same-session fail-closed gate

- Agent: Codex
- Branch/run:
  - `codex/run287-next-scheduled-gate-audit-20260715`
  - negative control estimate artifact `29304288757`
- Context:
  - Estimate queue, exact packet, observation archive, and risk outcome each
    had local contracts, but no single audit proved that their next artifacts
    were complete, same-session, safe, and ready for the first 1D review.
- Attempt:
  - Added an explicit-path auditor for the estimate manifest plus seven daily
    evidence files. No latest-directory discovery is permitted.
  - Froze `150/150/150` queue acknowledgement, the 993-name universe shape,
    the 401/403-only circuit, exact session dates, row-level close coverage,
    component READY states, and portfolio-safety flags.
- Result:
  - Missing artifacts are pending; present invalid artifacts are blocked; a
    valid chain with no elapsed 1D is pending rather than failed.
  - The old real artifact was correctly blocked at `36/150` acknowledgement
    and also exposed its missing new circuit evidence.
  - Six focused gate scenarios passed, related subsystem smokes passed, and
    full local PR validation passed `176/176` in `232.42` seconds.
- Failure or caveat:
  - The next scheduled post-settlement estimate and daily artifacts have not
    yet arrived, so `150/150` and the first real 1D direction remain unproven.
  - A completed 1D result is diagnostic only and cannot establish historical
    CAGR or MDD improvement.
- Root cause:
  - Independent READY labels do not prove cross-artifact date consistency,
    completeness, or that an older partial artifact was not selected by hand.
- Reusable lesson:
  - Pass evidence paths and expected dates explicitly; never infer the current
    research cut from a latest directory.
  - Separate `pending because time/data has not arrived` from `blocked because
    present evidence violates contract`.
- Next action:
  - Audit the next scheduled artifacts after the settlement buffer, review the
    1D warning-minus-normal diagnostic without tuning, and continue collecting
    toward the frozen 21D and 63D gates.
- Do-not-repeat:
  - Do not accept selected count as proof that all names were attempted.
  - Do not treat FMP HTTP 402 as a global vendor circuit.
  - Do not combine artifacts from different NYSE sessions.
  - Do not use 1D direction to change a rule, cash, weight, or target book.
- Evidence files:
  - `docs/run287_next_scheduled_artifact_gate_contract.json`
  - `tools/audit_run287_next_scheduled_artifact_gate.py`
  - `tests/run287_next_scheduled_artifact_gate_smoke.py`
  - `docs/CODEX_RUN287_NEXT_SCHEDULED_ARTIFACT_GATE_RESULT_20260715.md`

### 2026-07-15 - Active listing coverage is not delisted coverage

- Agent: Codex
- Branch/run:
  - `codex/run287-delisted-coverage-truth-20260715`
  - successful collection artifact `29064427303`
- Context:
  - The free-data coverage summary labeled a 990/993 ticker match as
    `active/delisted listing lifecycle`, while the underlying Alpha Vantage
    artifact had 14,140 active rows and zero delisted rows.
- Attempt:
  - Classified non-CSV provider bytes before parsing, preserved and hashed the
    two-byte `{}` response, and split active versus delisted evidence in the
    coverage table, summary, and report.
  - Re-audited the real 993-name universe and current downloaded estimate
    snapshots without any new private-key provider request.
- Result:
  - Active current-universe reference coverage is 990/993; delisted source
    rows and current-universe delisted matches are both zero.
  - Forward estimates increased from 13 to 17 true-estimate names, about
    +0.40pp, below the frozen +5pp repeat threshold.
  - Full local PR validation passed `176/176` in `219.97` seconds.
- Failure or caveat:
  - The official docs expose a delisted query, but both the actual keyed run
    and the official historical demo currently returned `{}` rather than CSV.
  - Current active identity coverage does not solve historical Russell
    membership, delisted outcomes, or symbol-predecessor joins.
- Root cause:
  - The coverage audit reduced a mixed lifecycle file to one ticker set and
    discarded `source_state`, so active-only bytes could inherit a broader
    lifecycle label.
- Reusable lesson:
  - Preserve source-state semantics through coverage reporting; row presence
    must never prove a component that the response did not contain.
  - A syntactically successful HTTP response can still be unusable evidence;
    classify content before parsing and retain the raw hash.
- Next action:
  - Keep the historical A/B gate closed, continue bounded forward archives,
    and accept only a 50-row exact-time PIT sample with real delisted and ADR
    evidence before joining returns.
- Do-not-repeat:
  - Do not call active listing matches survivorship or delisted coverage.
  - Do not coerce `{}` into an empty but successful CSV source.
  - Do not rerun a failed source arm for a +0.40pp coverage change.
  - Do not use current identity snapshots as historical universe membership.
- Evidence files:
  - `tools/collect_alphavantage_listing_status.py`
  - `tools/audit_free_historical_data_coverage.py`
  - `tests/free_historical_data_backfill_smoke.py`
  - `docs/CODEX_RUN287_DELISTED_COVERAGE_TRUTH_RESULT_20260715.md`

### 2026-07-18 - Full/OOS-positive growth tilt failed the recent 126-session embargo fold

- Agent: Codex
- Branch/run:
  - `codex/run287-sec-balance-resilience-20260718`
  - `outputs/run287_growth_embargo_walk_forward_20260718/`
- Context:
  - Main `growth_confirmation_top_quintile_tilt10` had full-period CAGR
    35.7897% and positive legacy OOS/OOS2 deltas, but MDD was -25.9265%, one
    era supplied 59.59% of incremental P&L, and the required 126-session
    embargo check had not been completed.
- Attempt:
  - Kept the formula and tilt fixed, used the existing 25 bps cash-carry
    broker-ledger curves, and evaluated two non-overlapping test segments only
    after 126 common trading sessions were completely embargoed.
  - Audited five target-book provenance date columns and the source summary's
    `used_forward_return_in_ranking=false` assertion.
- Result:
  - The post-2022 fold passed with dCAGR +9.4606 pp and dSharpe +0.2447.
  - The post-2024H1 fold failed with dCAGR -0.1993 pp despite dSharpe +0.0031.
  - Provenance violations were zero, so the rejection is performance
    non-generalization rather than detected future-row leakage.
  - Status is `REJECT_EMBARGO_FOLD`; no accepted-time debt veto was built.
- Failure or caveat:
  - This fixed deterministic policy was not retrained per fold, and the output
    explicitly does not claim walk-forward model retraining.
  - Historical PIT membership and delisted bias remain unresolved.
- Root cause:
  - Positive overlapping OOS windows hid temporal instability. Once a full
    126-session gap isolated the recent segment, incremental CAGR turned
    negative, consistent with the existing era-concentration failure.
- Reusable lesson:
  - A positive long OOS window is not enough when it overlaps a dominant era.
    Require disjoint, embargoed recent segments before spending on a
    neutralizer or source sidecar for that arm.
  - Stop at the first negative gate; adding a new veto after observing the
    failed segment is retuning, not independent validation.
- Next action:
  - Keep this Main growth lane closed. If exact accepted-time balance-sheet
    data is pursued later, preregister it as a standalone source screen and do
    not attach it to this rejected arm unless the do-not-repeat exception is
    independently satisfied.
  - Continue the independent 988-name selector/candidate substrate work for
    Concentrated rather than adding an underpowered sector sell rule.
- Do-not-repeat:
  - `growth_confirmation_score+top_quintile_tilt10_fixed_policy_126_session_embargo+run287_generated_main+post_2022_and_post_2024h1_embargo_to_2026-07-02`
  - Do not move fold endpoints, shorten the embargo, tune tilt, or add a debt
    veto to rescue the failed recent fold.
- Evidence files:
  - `docs/run287_growth_embargo_contract_v1.json`
  - `tools/audit_run287_growth_embargo.py`
  - `tests/run287_growth_embargo_smoke.py`
  - `docs/CODEX_RUN287_GROWTH_EMBARGO_RESULT_20260718.md`
  - `outputs/run287_growth_embargo_walk_forward_20260718/summary.json`
