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

### 2026-07-18 - A successful daily job must not silently replace the forward-paper genesis

- Agent: Codex
- Branch/run:
  - `codex/run287-paper-ledger-continuity-20260718`
  - affected successful run `29554723038`
  - recovery proof runs `29624921914` and `29625744031`
- Context:
  - The 2026-07-16 daily operating job found neither a GitHub paper-state
    cache nor the dedicated Google Drive paper archive and therefore created a
    new $100,000 seed, losing the valid 2026-07-13 forward-performance anchor.
- Attempt:
  - Preserved the displaced 2026-07-16 Drive state both locally and under a
    separate Drive recovery-backup folder.
  - Restored the validated 2026-07-13 review-only ledger to the dedicated Drive
    archive with `rclone copy`; no remote or local files were deleted.
  - Added an explicit `--expected-seed-date 2026-07-13` continuity contract.
    A later session may reuse that frozen seed or a matching restored account,
    but it may not manufacture a replacement seed.
- Result:
  - Source, Drive archive, and Drive recovery backup each contain 20 files.
    `rclone check --checksum --one-way` reported 20 matches and zero
    differences for the restored canonical state.
  - Manual workflow run `29624921914` restored both exact 2026-07-13 account
    hashes with `created_account_count=0`; the new continuity guard therefore
    worked against the real Drive/cache restore order.
  - The same run then failed closed at exact-close coverage because SOXX ended
    at 2026-07-16 while the required session was 2026-07-17. The refresh tool
    had treated a cache exactly two calendar days old as fresh under `age > 2`.
  - Added `--refresh-through-date "$LAST_NYSE_SESSION_DATE"` so every selected
    ticker behind the required market session is refreshed regardless of its
    calendar-age bucket. Focused validation passed `3/3`.
  - Bounded rerun `29625744031` completed successfully with exact-close
    coverage `24/24`, `23` required-session price refreshes, and zero refresh
    failures. Both accounts reported `seeded_this_run=false` and retained the
    canonical 2026-07-13 seed.
  - The 2026-07-17 review-only marks were Main equity `$97,724.6624`, cash
    `1.3988%`, forward return/MDD `-2.2753%`; Concentrated equity
    `$84,279.8008`, cash `0.8472%`, forward return/MDD `-15.7202%`.
    These four-session observations remain `UNDERPOWERED` for CAGR inference.
  - The workflow persisted the advanced 20-file ledger to the dedicated Drive
    archive. A post-run `rclone check --checksum --one-way` found 20 matches
    and zero differences between the artifact and Drive.
  - Subsequent same-session retry runs exposed two additional append-only
    boundaries. Run `29627879721` rejected a duplicate holding-risk event whose
    only change was `available_from`; run `29628711412` then showed that a
    provider/cache revision can also change the recomputed risk payload. The
    retry path now reuses the first verified 2026-07-17 risk snapshot only when
    account hashes, contract hash, stored output hashes, event IDs, and safety
    flags all match. Any semantic input or stored-output change remains blocked.
  - Run `29629644686` passed required-session close coverage and reached review
    output construction, but a same-date provider revision changed Main equity
    from `$97,724.66236877441` to `$97,724.71708679199` (about `$0.055`). The
    ledger correctly rejected the changed 2026-07-17 mark, but the old path had
    already written `account_state_latest.json` before raising.
  - The ledger retry path now validates manifest, target/seed hashes, cost and
    lag policy, account/curve/position consistency, pending counts, and the
    fill/rejection event chain before reusing a same-session mark. A price-only
    cache revision is ignored after the first exact mark; target, seed, policy,
    or stored-state changes fail closed before any portfolio state file is
    written.
  - Focused fixture validation passed, including a deliberately revised same-day
    close and a changed-target negative control. A copied real artifact from
    successful run `29625744031` reused both 2026-07-17 portfolio marks, with
    zero hash differences across all 30 portfolio and preview files.
  - Bounded run `29630940290` exposed one restore-contract gap: the dedicated
    Drive archive intentionally persists the ledger but not disposable
    `account_ledger_preview` files. Reuse validation therefore stopped on four
    missing preview files before reaching the lifecycle scorer. The retry path
    now leaves the verified portfolio state frozen and rebuilds only a missing
    advisory preview from that frozen account; existing previews remain
    byte-for-byte unchanged.
- Failure or caveat:
  - The Google Drive connector could read the archive but returned HTTP 403
    for raw-file replacement because that app lacked file-specific write
    authorization. The already configured local rclone remote completed the
    bounded recovery instead.
  - This repairs forward-paper continuity only. It does not change historical
    CAGR/MDD, target weights, orders, or production state.
  - Run `29624921914` did not advance the paper ledger because exact-close
    coverage correctly blocked on SOXX before review outputs were built.
  - The daily workflow can now advance marks and holding-risk review through
    2026-07-17, but `master` and this focused PR still fail closed at
    `scored_latest`: GTLS has no 2026-07-17 close because its verified cash
    merger ended trading after 2026-07-15. Minimal terminal-lifecycle evidence
    and scorer handling are isolated on stacked draft PR #301; broader research
    changes remain on draft PR #299.
- Root cause:
  - The bootstrap correctly refused partial ledger state but had no canonical
    genesis-date contract. Complete absence was therefore indistinguishable
    from a legitimate first launch.
- Reusable lesson:
  - Persistent paper systems need a pinned genesis identity in addition to
    cache/Drive restore. Missing persistence after genesis must fail closed,
    not reset equity to starting capital.
  - Append-only forward marks need same-session idempotency at the orchestration
    boundary. Provider revisions must not trigger a second valuation write for
    an already archived date, and validation must happen before partial writes.
- Next action:
  - Merge the focused persistence/required-session fix only after review, then
    split the minimal verified GTLS terminal-lifecycle handling out of draft
    PR #299 so the exact selector packet can advance without importing that
    PR's unrelated research surface.
- Do-not-repeat:
  - Do not infer continuity from a successful workflow conclusion.
  - Do not accept a later exact-close bootstrap merely because all prices are
    available.
  - Do not use calendar-age freshness as a substitute for required-session
    close coverage.
  - Do not overwrite a displaced archive without preserving a recovery copy.
- Evidence files:
  - `tools/bootstrap_run287_daily_paper_accounts.py`
  - `tools/run_daily_simulated_fill_ledger.py`
  - `tests/run287_daily_paper_bootstrap_smoke.py`
  - `tests/daily_simulated_fill_ledger_smoke.py`
  - `.github/workflows/daily_operating_selection_refresh.yml`
  - `outputs/run287_daily_pipeline_replay_29305572139/daily_simulated_fill_ledger/`
  - `outputs/run287_paper_drive_backup_pre_recovery_20260718_1006/`

### 2026-07-20 - A forward-paper session is one directory transaction, not two portfolio writes

- Agent: Codex
- Branch/PR:
  - `codex/run287-paper-ledger-continuity-20260718`
  - draft PR #300; issue #306 P0
- Context:
  - Same-session reuse had been repaired, but a new-session run still wrote
    Main files before validating Concentrated. Root summaries, bootstrap
    summaries, and Drive copies also lacked one exact checksum contract.
- Attempt:
  - Compute bootstrap accounts and both portfolio sessions in isolated sibling
    directories, validate the complete candidate, and publish the directory
    bundle through recovery-backed atomic renames.
  - Added a deterministic genesis identity and exact-file SHA-256 snapshot
    manifest. Restore validates before replacement; Drive save writes and checks
    a run-specific recovery copy before syncing the canonical archive.
  - Required exact completed-session closes for held, target, and pending
    securities and rejected duplicate client order IDs and negative cash.
- Result:
  - A 20-business-session fixture retained the original seed and account IDs,
    produced 20 equity observations, and returned a byte-identical state hash
    on same-session retry.
  - A stale Concentrated close failed after Main candidate computation with zero
    durable changes. An injected interruption after the first directory publish
    restored both state and preview hashes exactly.
  - Focused PR validation passed `6/6` in `26.25s`; full Tier-1 PR
    validation passed `177/177` in `475.61s`. No fullrun was executed.
- Failure or caveat:
  - Existing legacy archives have no new checksum. They may be migrated only by
    a successful semantic validation and transactional session; checksum
    mismatch is always fail-closed.
  - This does not improve historical CAGR/MDD and does not authorize production
    or live trading.
- Root cause:
  - File-level append-only checks were present, but the orchestration boundary
    was not a transaction. A later failure could therefore expose a mixed-date
    two-portfolio state.
- Reusable lesson:
  - Durable multi-account paper state needs validate-first/write-second at the
    directory generation level. Same-session idempotency must include the root
    summary and integrity manifest, not only each portfolio subdirectory.
- Next action:
  - Update draft PR #300 and request review. Do not begin P1 until P0 is
    merged or explicitly closed.
- Do-not-repeat:
  - Do not write Main before Concentrated has validated.
  - Do not restore or replace canonical paper state without exact checksums and
    a recovery copy.
  - Do not use a prior close as the current exact-session mark.
- Evidence files:
  - `tools/run287_paper_ledger_integrity.py`
  - `tools/run_daily_simulated_fill_ledger.py`
  - `tools/bootstrap_run287_daily_paper_accounts.py`
  - `tests/run287_paper_ledger_transaction_smoke.py`
  - `docs/CODEX_RUN287_P0_PAPER_LEDGER_TRANSACTION_RESULT_20260720.md`

### 2026-07-20 - Missing quotes are lifecycle states, not permission to delete securities

- Agent: Codex
- Branch/PR:
  - `codex/run287-gtls-terminal-lifecycle-20260718`
  - draft PR #301; issue #306 P1
- Context:
  - The exact-close scorer stopped permanently when a verified cash merger
    ended trading. The isolated draft handled one terminal ticker but did not
    share identity, proceeds, or alias semantics with the paper ledger.
- Attempt:
  - Rebased the isolated change on merged P0 and replaced the ticker-specific
    parser with `run287-security-lifecycle-v1`.
  - Gave scorer and paper ledger the same PIT resolver for stable IDs, aliases,
    exact availability, effective/last-trading dates, verified proceeds,
    source hashes, and review status.
  - Added fee-free cash-merger settlement, pending-order cancellation, residual
    cash preservation, and successor-quote fallback inside P0's atomic
    transaction boundary.
- Result:
  - Generic fixtures cover cash merger, future-known and pre-effective events,
    duplicates, bankruptcy without recovery, ticker rename,
    predecessor/successor, malformed identity/hash, missing proceeds, and an
    ordinary active ticker.
  - A held terminal fixture settled without a future close, cancelled its stale
    pending order, preserved a valid event chain, and changed zero durable
    files on failure.
  - The pinned actual sidecar hash is
    `09e2fd19a127c281dd8f69988d8ac454183133a638752fbb6d7884c947e86f24`;
    the 2026-07-17 decision resolves one terminal event and one identity event.
  - Full Tier-1 validation passed `178/178` in `617.12s`. No fullrun or
    historical backtest was executed.
- Failure or caveat:
  - The local bounded upstream preflight remained skipped because model,
    price-cache, and static-anchor dependencies are not materialized in this
    checkout. The lifecycle source itself existed and matched its pinned hash;
    zero network requests were made.
  - This is not historical delisted-membership coverage and does not make
    `pit_universe_label_clean=true`.
  - P1 does not improve or recalculate CAGR/MDD.
- Root cause:
  - Trading symbols, quote availability, and economic-security lifecycle were
    conflated. Removing the no-quote row could create survivorship bias, while
    retaining it forever could block every exact-close refresh.
- Reusable lesson:
  - Quote absence is evidence of a data/lifecycle problem, never an exit rule.
    Terminal removal requires exact public evidence plus deterministic economic
    proceeds; ticker changes require identity continuity rather than historical
    rewrites.
- Next action:
  - Review and merge P1, then start P2 same-close selector recomputation from
    the merged lifecycle-aware substrate.
- Do-not-repeat:
  - Do not hardcode a real ticker in scorer, selector, or ledger logic.
  - Do not treat active-symbol coverage as delisted/survivorship coverage.
  - Do not set missing delisting recovery to zero or drop the security.
  - Do not apply ticker aliases before their exact `available_from` and
    effective date.
- Evidence files:
  - `tools/security_lifecycle.py`
  - `tools/run_run287_scored_latest_refresh.py`
  - `tools/run_daily_simulated_fill_ledger.py`
  - `tests/security_lifecycle_smoke.py`
  - `docs/CODEX_RUN287_P1_SECURITY_LIFECYCLE_RESULT_20260720.md`

### 2026-07-20 - A current price mark is not a current selector decision

- Agent: Codex
- Branch/PR:
  - `codex/run287-same-close-selector-20260720`
  - issue #306 P2
- Context:
  - The scheduled workflow appended the latest price date to restored targets,
    built paper orders from those rows, and only afterward ran the real
    989-name score/selector path as no-write advisory output.
- Attempt:
  - Added a seven-field timestamp contract and an exact same-close paper target
    gate over selector, model-head, holding-risk, candidate-risk, and source
    hashes.
  - Added a transaction-safe suppressed mark pass so prior orders are resolved
    before risk/selection while bad selector provenance creates zero new order.
  - Ported only the adjusted-close restatement repair needed for candidate-risk
    source continuity; draft PR #299's unrelated changes were not mixed in.
- Result:
  - Restored books now report `RESTORED_TARGET_REVALUATION_ONLY` and
    `same_close_selector_recomputed=false`.
  - A bounded actual 2026-07-16 replay passed all six active model-head and
    timestamp/hash gates after the legitimate dividend restatement repair.
  - Full Tier-1 PR validation passed `179/179` in `555.59s`.
  - The paper target hashes were
    `b771bf9046d113d2780f05954df810577914f6e0660cb29c6e391a97d8a277f1`
    (Main) and
    `0f1bf3afa242825241615606744685e734d387dea0eab39bceea245def5e815b`
    (Concentrated).
- Failure or caveat:
  - The one-date risk intersection leaves Main 46.7804% cash and Concentrated
    88.6000% cash with 93.59%/99.16% one-way turnover. It is shadow evidence,
    not an approved transition or evidence of improved CAGR/MDD.
  - PIT universe membership remains unclean, so production remains blocked.
- Root cause:
  - Valuation freshness, feature freshness, selection recomputation, and order
    eligibility were represented by one overloaded date. A later price could
    therefore make an old decision appear current.
- Reusable lesson:
  - Set `same_close_selector_recomputed=true` only when the feature, score,
    selector, valuation, risk, and target hashes form one date-consistent
    decision bundle. Marking an account and deciding its next target are
    separate transactions.
- Next action:
  - Merge P2, then implement P3's single defense/re-entry state machine. Do not
    tune P2's one-date veto or cash outcome.
- Do-not-repeat:
  - Do not overwrite a restored target's decision date with a current price
    date.
  - Do not create a new order before exact-date selector and risk provenance
    pass.
  - Do not treat adjusted-close dividend restatement as raw-price identity
    failure; compare raw overlap and rebase old adjusted history.
  - Do not tune the risk veto after seeing one date's cash or turnover.
- Evidence files:
  - `docs/run287_same_close_target_contract.json`
  - `tools/build_run287_same_close_target_books.py`
  - `tests/run287_same_close_target_books_smoke.py`
  - `docs/CODEX_RUN287_P2_SAME_CLOSE_SELECTOR_RESULT_20260720.md`
## 2026-07-20 — P3 canonical crisis state, selective defense, and re-entry

- Scope: issue #306 P3, bounded fixed-book research only.
- Canonical implementation: `tools/run287_crisis_policy.py` with eight states,
  fixed component weights, exact `0.40/0.60/0.75` re-entry thresholds,
  `0.25/0.60/1.00` gross multipliers, six Reserve reasons, and lexicographic
  selective sells. Missing components are not renormalized and critical
  missing data enters `DEGRADED_DATA`.
- The legacy uniform noncash scaler was a real implementation gap: behavioral
  flags were computed but not enforced. It is replaced by a compatibility
  facade over the canonical selective policy.
- Exact generated-book zero-yield result at 25 bps/side:
  - Main: `33.5352269% / -25.6526842%` baseline versus
    `22.7350546% / -21.5507252%` P3.
  - Concentrated: `47.6897570% / -23.2216426%` baseline versus
    `31.4554902% / -23.2630311%` P3.
- Verdict: `REJECTED_POLICY_PROMOTION`. Main MDD improved but CAGR lost
  `10.8002pp`; Concentrated CAGR lost `16.2343pp` and MDD worsened slightly.
  Green cash traps and very slow 95% gross recovery also failed the gate.
- Historical selective-sell evidence was underpowered: only low-conviction
  fallback fired (`606` Main, `259` Concentrated); thesis, trend, explicit
  loss/beta/vol, and duplicate exposure fields were absent from the historical
  target books. Do not claim selective-defense alpha from this run.
- `do_not_repeat`:
  `canonical_crisis_selective_defense+fixed_025_060_100_reentry+generated_books+2019-06-03_2026-07-10`.
  Do not retune thresholds or use cash carry to rescue this arm.
- Current 2026-07-16 no-network sidecar v2 passed as canonical GREEN with no
  missing critical component and physically excluded nine future-label
  columns. Same-close operating targets remain champion; the rejected policy
  writes separate shadow targets only.
- Full Tier-1 PR validation passed `181/181` in `576.74s`.
- Fullrun executed: false. Production enabled: false. Live trading enabled:
  false.

## 2026-07-20 - P4 canonical ReserveAssetPolicy

- Scope: issue #306 P4, bounded same-stock-book Reserve comparison only.
- Added one canonical policy for `BROKER_CASH_OR_MMF`, `DGS3MO_CARRY`,
  `BIL_TOTAL_RETURN`, and `SGOV_TOTAL_RETURN`. Historical research defaults to
  DGS3MO; current forward paper remains broker cash/MMF unless explicitly
  changed by a later user-approved migration.
- Zero-yield exact parity passed for Main and Concentrated, including exact
  trade CSV hashes. All completed modes reconciled the six Reserve reasons.
- DGS3MO used past-only daily forward-fill and ACT/365 with zero future-rate
  uses. It produced Main `34.4032% / -25.3629%` and Concentrated
  `49.0968% / -22.9560%`.
- BIL produced Main `33.7965% / -25.8378%` and Concentrated
  `47.8700% / -23.0549%`. Main MDD worsened, and 85 Reserve fills added
  material fees, so BIL is not the common default.
- SGOV returned `BLOCKED_SHORT_HISTORY`: history starts 2020-06-01 versus the
  required 2019-05-31 generated-book start. The endpoint was not shortened.
- `do_not_repeat`:
  `bil_total_return+fixed_generated_books+2019-05-31_2026-07-10+25bps`.
  Do not tune a trading threshold or cite Concentrated alone to rescue common
  BIL adoption.
- Reusable lesson: Reserve accounting can close part of a CAGR gap, but it is
  not selection alpha. A tradeable cash substitute must clear MDD after its
  own fills and fees, and incomplete ETF history must block rather than splice.
- Evidence: `_tmp_tests/p4_reserve_actual_v2_20260720/summary.json` and
  `reserve_mode_metrics.csv` (local untracked research output).
- Repository smoke tests passed `129/129`; full Tier-1 PR validation passed
  `183/183` in `744.61s`.
- Fullrun executed: false. Production enabled: false. Live trading enabled:
  false.

## 2026-07-20 - P5 strict leadership persistence was a no-op

- Scope: issue #306 P5, one preregistered generated-book hold/replacement arm.
- Added the exact sell taxonomy `THESIS_EXIT`, `RISK_EXIT`,
  `REPLACEMENT_EXIT`, `LIFECYCLE_EXIT`, and `EXECUTION_RECONCILIATION` to
  order previews and durable paper-ledger events.
- Exact DGS3MO control parity passed for Main and Concentrated, including
  trade count, fees, and trade CSV hashes. Future-return columns were
  physically excluded from the 47,435-row scored-candidate cache.
- The strict arm retained zero incumbents. Main remained `34.4032% / -25.3629%`
  and Concentrated remained `49.0968% / -22.9560%`; every OOS, OOS2, embargo,
  and 25/50/100 bps delta was zero.
- Root cause: `rs_sector_3m` was missing for 506 Main and 259 Concentrated
  departure observations; another 19 and 11 lacked an exact candidate row.
  Missing evidence is not protection and is an execution/data reconciliation
  issue, not a thesis break.
- Holding diagnostics showed 33/32-day median completed holds, zero completed
  365-day holds, and 42/35 exits followed by re-entry within 63 sessions for
  Main/Concentrated. This identifies a question, not profitable alpha.
- Verdict: `REJECT_NO_OP`. Do not tune thresholds or substitute a convenient
  sector proxy after observing this failure.
- `do_not_repeat`:
  `leadership_persistence_v2_strict+generated_books+2019-05-31_2026-07-10+25bps+dgs3mo`.
- Next action: P6 candidate-gate and model-stability audit must repair or
  explicitly neutralize the upstream coverage contract before any new hold
  arm is admissible.
- Evidence: `docs/CODEX_RUN287_P5_HOLD_EXIT_REPLACEMENT_RESULT_20260720.md`
  and `_tmp_tests/p5_hold_exit_actual_v2_20260720/summary.json`.
- Repository pytest passed `129/129`; full Tier-1 PR validation passed
  `185/185` in `280.63s`.
- Fullrun executed: false. Production enabled: false. Live trading enabled:
  false.

## 2026-07-20 - P6 candidate-gate audit and rejected sector-RS repair

- Scope: issue #306 P6, candidate-funnel/model-stability diagnosis plus one
  preregistered input remediation. No threshold grid or second arm was run.
- The 47,435-row candidate artifact had 0% `rs_sector_3m` coverage although
  `mom_3m`, sector, industry strength, and the other momentum inputs were
  complete. A same-date sector residual sidecar restored 100% coverage without
  future-return use.
- Current bounded score-stack audit passed six of six finite, nonzero,
  nonconstant prediction heads with no silent-zero fallback or suffix
  collision. The prior four-head constant-zero snapshot is not a valid drift
  reference, so distribution drift remains `UNDERPOWERED` until another active
  six-head snapshot exists.
- All 989 current candidates used at least one missing-neutral model feature
  and had a critical field missing; complete-versus-neutralized performance is
  therefore underpowered. Missing values remain neutral rather than passing a
  quality gate by exception.
- Existing selected names beat nearest-score-rank controls in both portfolios,
  all Full/OOS/OOS2 windows, and 21/63/126/252-session outcomes. The selector
  has useful nonlinear selection evidence even though raw short-horizon score
  IC is weak.
- Stability is a material operating bottleneck: adjacent-month score Spearman
  was `0.6358`, top-10 overlap `33.57%`, and top-30 overlap `42.62%` across 84
  pairs. P7 must co-display rank stability, turnover, costs, and outcomes.
- The repair changed 44/85 Main and 35/85 Concentrated decisions and reduced
  average cash, but failed. At 25bp, Main dCAGR/dMDD was
  `-0.67pp / -1.20pp`; Concentrated was `-1.74pp / -1.99pp`. OOS and OOS2
  dCAGR were negative for both, and 100bp plus turnover-cost gates failed.
- Verdict: `REJECT_OOS_AND_COST`. The repair is not active in the daily
  selector and the official `34.4032% / -25.3629%` Main and
  `49.0968% / -22.9560%` Concentrated baselines are unchanged.
- `do_not_repeat`:
  `canonical_sector_relative_strength+materialize_missing_rs_sector_3m+alphaops_vnext_regenerated_main15_concentrated5+2019-05-31_2026-05-29`.
- Evidence: `docs/CODEX_RUN287_P6_CANDIDATE_GATE_STABILITY_RESULT_20260720.md`,
  `_tmp_tests/p6_candidate_gate_actual_v2_20260720/summary.json`, and
  `_tmp_tests/p6_sector_rs_broker_ab_20260720/summary.json`.
- Repository pytest passed `129/129`; full Tier-1 PR validation passed
  `187/187` in `730.57s`.
- Fullrun executed: false. Production enabled: false. Live trading enabled:
  false.

## 2026-07-20 - P7 canonical private operating scorecard

- Scope: issue #306 P7. Added one private/review-only command that aggregates
  validated P3-P6 artifacts by reference and emits JSON plus Markdown without
  copying source archives.
- Every metric records source path, SHA-256, as-of date, metric mode, evidence
  class, and availability. Historical, current paper, and true-forward lanes
  cannot overwrite one another.
- Actual headline historical evidence is `TRUSTED`: Main
  `34.4032% / -25.3629%`, Concentrated `49.0968% / -22.9560%`. The evidence is
  through 2026-07-10; the 2026-07-20 generation date is not a July 17 market
  refresh.
- Current durable paper execution is `UNAVAILABLE` because its summary and
  checksum manifest are absent locally. The P0 transaction tests are not used
  as a substitute for a real current account.
- True-forward evidence remains `UNDERPOWERED`: 10 distinct tickers and zero
  resolved 21/63/126-day outcomes as of 2026-07-10; 252-day evidence is not in
  the current contract and is `UNAVAILABLE`.
- Attribution shows positive selector-versus-matched-control evidence, short
  32/33-day median holds, underpowered exit counterfactuals, rejected
  crisis/re-entry shadow policy, positive Reserve carry that is not selection
  alpha, and material 25-to-100bp CAGR drag.
- Historical mean Reserve is 29.31% Main and 40.80% Concentrated and is almost
  entirely `capacity_unallocated`, not crisis defense. This explains why high
  Concentrated cash cannot be described as an active volatility call.
- Ten redundant P3-P6 results are registered as `ABSORBED_SOURCE`. Their files
  remain in place; the scorecard stores provenance and values only.
- Fixture tests prove that missing sections remain null/`UNAVAILABLE`, a paper
  account reset makes headline performance `NOT_TRUSTED`, and metric-definition
  changes require a migration note.
- Evidence: `docs/CODEX_RUN287_P7_OPERATING_SCORECARD_RESULT_20260720.md` and
  `_tmp_tests/p7_operating_scorecard_actual_v3_20260720/operating_scorecard.json`.
- Repository pytest passed `129/129`; full Tier-1 PR validation passed
  `188/188` in `479.59s`.
- Fullrun executed: false. Production enabled: false. Live trading enabled:
  false.

## 2026-07-20 - P8 canonical CI fixture and fail-closed artifact contract

- Scope: issue #306 P8. Repository/CI/artifact hygiene only; no alpha arm and
  no historical artifact deletion or Git history rewrite.
- The tracked tree measured 6,838,888,405 bytes across 11,737 files; existing
  `cloud_results/` represented about 6.81 GB. These legacy bytes are preserved.
- Replaced the roughly 581 MB Tier-1 canonical rebuild dependency with a
  deterministic 26-file fixture: 4,629 payload bytes and about 9.4 KB including
  its exhaustive SHA-256 manifest.
- Fixture replay passed AutoLearning v2, orchestrator replay, portfolio goal
  search, and Portfolio System Guard with zero guard hard errors.
- Arbitrary manual baselines now fail explicitly as
  `UNSUPPORTED_BASELINE_PATH` unless an exhaustive compatible manifest verifies
  every payload file and rejects undeclared files.
- Pull-request validation no longer also runs on every non-master branch push,
  removing one duplicate same-SHA validation while preserving PR coverage.
- PR sparse checkout no longer includes `cloud_results/`; a merge guard blocks
  new runtime blobs, dated/failed output bundles, and ordinary Git blobs over
  2 MiB without deleting them.
- Core hidden dated baseline dependencies are zero. Active versus historical
  evidence labels are registered in `docs/run287_evidence_status_registry.json`.
- This work improves the trust and cost of later CAGR/MDD research; it does not
  change official Main `34.4032% / -25.3629%` or Concentrated
  `49.0968% / -22.9560%` metrics.
- Evidence: `docs/CODEX_RUN287_P8_REPO_CI_ARTIFACT_HYGIENE_RESULT_20260720.md`
  and local `_tmp_tests/p8_repo_ci_hygiene/repo_ci_hygiene_audit.json`.
- Repository pytest passed `129/129`; full Tier-1 PR validation passed
  `189/189` in `348.21s`.
- Fullrun executed: false. Production enabled: false. Live trading enabled:
  false.

## 2026-07-20 - P9 single promotion and rollback gate

- Scope: issue #306 P9. Governance and long-forward-paper state contract; no
  alpha arm, fullrun, production activation, or live orders.
- Added the single state vocabulary `RESEARCH_ONLY`,
  `SHADOW_OPERATION_READY`, `FORWARD_PAPER_VALIDATING`,
  `FORWARD_PAPER_REVIEW_READY`,
  `PRODUCTION_CANDIDATE_USER_APPROVAL_REQUIRED`, and
  `BLOCKED_OR_ROLLED_BACK`.
- Canonical state is `RESEARCH_ONLY`. No accepted challenger exists,
  PIT/delisted evidence remains incomplete, and 63/126D outcomes are unresolved.
- Fixed forward minimums before further outcomes were inspected: 60 completed
  sessions, 12 decision weeks, and 200/100/50 resolved 21/63/126D outcomes.
  Low signal frequency extends time and never lowers these thresholds.
- Fully passing evidence changes only `maximum_evidence_supported_state`; it
  never mutates the canonical state. A hash-bound authorization still requires
  a reviewed state-pointer change.
- Champion and challenger require separate account IDs and ledger roots with
  identical data/close/cost/Reserve/lifecycle contracts and paired dates.
  Collision or mismatch fails closed.
- Rollback triggers restore the champion policy pointer, preserve forward paper
  history, and require separate review for any code rollback.
- Daily workflow, private operating scorecard, public dashboard, and
  user-current report now consume the same effective state. Legacy local
  promotion labels cannot authorize production.
- The downloaded July 16 runtime overlay showed 1 completed session, 1 decision
  week, and 0 resolved 21/63/126D outcomes: `RESEARCH_ONLY / UNDERPOWERED`, no
  rollback. This is not a July 17 performance refresh.
- Current user approval packet is `NOT_ELIGIBLE`; production activation and live
  trading are false.
- Evidence: `docs/CODEX_RUN287_P9_PROMOTION_ROLLBACK_GATE_RESULT_20260720.md`
  and local `_tmp_tests/p9_runtime_overlay/promotion_gate.json`.
- Repository pytest passed `129/129`; full Tier-1 PR validation passed
  `190/190` in `260.48s`; P9 gate fixtures passed `9/9`.
- Fullrun executed: false. Production enabled: false. Live trading enabled:
  false.

## 2026-07-21 - Issue #315 G0/H1 review and paper-transaction hardening

- G0 merged as `0ab5b2f203ba7efb93ebcbb3ee170040e4b26012` after two
  current-head review findings were corrected. `master` now requires strict
  `validate`, `portfolio_guard`, and trusted `review_complete` checks, resolved
  conversations, stale-review dismissal, and administrator enforcement.
- The review gate accepts only an exact `/review-complete <40-char head SHA>`
  attestation from a write-authorized actor after a trusted head observation
  and clean current-head Codex review evidence. A GitHub-rejected personal-token
  bootstrap attempt was recorded and not bypassed.
- H1 binds each paper preview to exact account, source/effective target,
  normalized target, order, weight, date, mode, and next-close eligibility
  hashes. Mark-only now emits explicit `NO_NEW_ORDER` evidence instead of an
  absent preview.
- Same-session behavior is deterministic for
  `MARK_ONLY -> SELECTED_TARGET -> MARK_ONLY`; missing or stale previews are
  rebuilt from the frozen account, and the final mark-only pass leaves durable
  ledger bytes unchanged.
- A separate preview-only crash journal is recovered before staging the next
  run. A synthetic interrupted publish restored the prior preview exactly and
  removed both the uncommitted sentinel and recovery journal.
- When preview-only and later full-bundle recovery journals coexist, recovery
  runs oldest/smallest scope first and lets the later full-bundle backup win;
  otherwise an older preview can overwrite the preview paired with the restored
  ledger.
- Main and Concentrated public operating targets publish atomically with ledger
  and preview state. Injected failure after the second published item rolls all
  four destinations back. `accepted_publication.json` binds the accepted files
  and uses portable repository-relative paths where possible.
- A legacy same-session snapshot is semantically attested at most once and is
  byte-identical on the next rerun. Failure/evidence artifacts exclude
  executable targets, user order reports, previews, and ledger state; accepted
  paper state is uploaded/synced only after success and integrity verification.
- H1 fixture, Python compilation, workflow YAML parse, repository pytest
  (`129/129`), and full Tier-1 PR validation (`191/191`, `591.30s`) passed.
- Official historical evidence is unchanged: Main
  `34.4032% / -25.3629%`, Concentrated `49.0968% / -22.9560%`, through
  2026-07-10. This work is not a July 17/20 performance refresh.
- Evidence:
  `docs/CODEX_RUN287_G0_H1_TRANSACTION_HARDENING_RESULT_20260721.md`.
- Fullrun executed: false. Durable daily catch-up executed: false. Production
  enabled: false. Live trading enabled: false.

## 2026-07-31 - exact-close shock/rebound pattern memory

- A violent one-day rebound after a drawdown is an observation, not proof that
  the damaged trend has repaired. Preserve the prior-day and current-day
  return signs, two-day compounded return, prior-loss recovery fraction,
  true-range/ATR, volume, volatility, range, trend, benchmark, and VIX context
  without tuning a threshold to the observed episode.
- Persist pattern observations and outcomes as separate append-only hash
  chains. Resolve 1/5/21/63/126-session outcomes only when the exact archived
  NYSE target session exists; never substitute a later price.
- Carry every unresolved ticker through its last registered horizon even after
  it leaves the portfolio or selector. Resolve the origin and target close
  from one target-session adjusted-history snapshot so later splits and
  dividends cannot corrupt returns, and require both exact SPY endpoints for
  every resolved security outcome.
- Persist immutable parent-linked accepted-head manifests and verify that a
  restored archive is an exact chain and byte-prefix descendant. An internally
  valid older prefix or fork is a rollback blocker, not a fallback.
- Freeze the full source-kind/ticker cohort after a session head is accepted.
  Retry-generated outcomes must also be reconstructed and economically
  compared before an existing event ID is treated as idempotent.
- Use producer-exact feature names in the archive allowlist; inverse aliases
  silently discard PIT context. Treat every NYSE session from the immutable
  forward launch date as required: a missing session remains in accepted-head
  provenance and suppresses all directional statistics and proposals.
- Count accepted rows with missing origin closes as matured-but-unresolved;
  never remove them from coverage. Allow a hash-valid unaccepted first-session
  suffix to reach the archive recovery path, reject every pre-launch date, and
  replace stale READY summaries/reports with an exact-session BLOCKED marker
  immediately when either sidecar stage fails.
- A finite close does not make a `data_ready=false` observation resolvable.
  Proposal power must come from a security aggregate, never benchmarks alone,
  and immutable acceptance must occur only after the human-readable report is
  durable so report failure leaves an unaccepted resumable suffix.
- Never roll an unaccepted session suffix into a later accepted head: require
  the original exact session to be retried first. Preserve its source summary
  and resolved outputs as a content-addressed bundle before appending events,
  so a delayed retry can revalidate the first-attempt evidence without creating
  a new observation timestamp. Match the recovery bundle to the unaccepted
  suffix's stored summary hash; multiple prior attempts are not ambiguity when
  exactly one has the required provenance. A legacy outcome-only suffix can
  match its stored source/benchmark endpoint-payload hashes instead. Do not
  change a hash-pinned contract without an explicit chain migration; workflow
  hardening that does not alter event semantics stays in code and this ledger.
  Invalidate pattern READY before the first fallible same-close or ledger
  command, and keep that BLOCKED marker untouched while recovery advances the
  durable head or returns a recovery failure; the preservation-mode exception
  path must not call a public-file writer. A deferred recovery validates and
  stages only; it does not advance the accepted head. Missing rows completed
  during retry retain the bundle that actually supplied their evidence, and
  subsequent recovery selects one bundle satisfying all suffix summary and
  endpoint identities. Equivalent legacy endpoint bundles may be
  deterministically deduplicated only when their complete endpoint signatures
  match. Only the post-ledger call may publish READY; report, summary, and
  last-attempt finalization precede the accepted-head commit, whose parent
  provenance comes from the immutable manifest. If the scheduled run is later
  than the pending session, publish that exact recovered session first after
  the ledger boundary and suppress current-session pattern construction unless
  it commits successfully. The atomic accepted pointer is the sole head commit
  marker: a validated descendant manifest left by process interruption remains
  an unaccepted exact-session suffix until the pointer is advanced by retry.
  When recovered D is committed during a D+1 run, commit only the immutable
  head and retain D+1's BLOCKED summary, report, and last-attempt bytes until
  D+1 finishes. Never accept D+2 while D+1 is absent: the first observation
  must equal the contract launch session and every later new observation must
  be the immediate NYSE successor of the accepted head. Validate all historical
  manifest prefix hashes by streaming each append-only chain once and comparing
  digests at declared byte boundaries; rehashing from byte zero per manifest is
  quadratic and eventually becomes an operational availability defect.
  A chronological guard is incomplete without a reachable catch-up route.
  Manual older-session dispatch now restores only the operator-pinned prior
  daily artifact, revalidates its GitHub/workflow/repository/commit lineage,
  rebuilds the pattern sidecar from that exact-session packet, tags the delayed
  materialization, and accepts one immediate NYSE successor per dispatch while
  paper operation stays replay-only with zero new orders or targets.
- Invalidate restored pattern READY before the first mark-only ledger call,
  stale-output cleanup, or holding-risk build. A producer-success guard is too
  late because any earlier `set -e` exit would otherwise republish stale
  proposal eligibility.
- Recovery-bundle equivalence includes the complete stable observation payload
  set as well as outcome endpoints. Equal empty endpoint files do not make two
  launch-session attempts equivalent when only one reproduces every observation
  already present in the unaccepted suffix.
- An exact current close is insufficient when the prior/current transition
  sessions are nonconsecutive. Propagate the transition-specific reason into
  `data_ready=false`, keep its outcomes unresolved, and activate the global
  observation-coverage blocker.
- Publish counts and missingness only until a pattern/horizon has at least 30
  resolved observations and 100% exact-target resolution coverage for every
  matured observation in that group. This prevents exited or disappeared
  names from creating survivorship-biased pattern results. Forward memory may
  propose research after the session/week gates, but it cannot automatically
  update a model, champion, target, order, or cash policy.
- Pattern-memory failure is isolated from the accepted portfolio ledger. Do
  not retry a partial ledger mutation; resume by event identity and chain
  validation on the next run.
- The 2026-07-30 mark remains `RESEARCH_ONLY` while the official durable
  account head is blocked after 2026-07-23 by the explicit legacy
  risk-outcome-parent migration gate. Do not silently jump sessions or use
  stale fallback evidence.
- Fullrun executed: false. Durable daily catch-up executed: false. Production
  enabled: false. Live trading enabled: false.

## 2026-07-29 - OHLCV location timing must remain confirmation-only

- A range low, range high, or Fibonacci retracement is a location coordinate,
  not an independently validated alpha signal. Freeze every level before
  forward outcomes exist and publish all levels so a later analyst cannot
  select only the level that happened to work.
- VIX is non-directional expected S&P 500 volatility. A high VIX observation
  alone must never generate a stock exit, entry block, cash floor, or portfolio
  mutation. Require contemporaneous SPY/QQQ damage and security-specific price
  damage before an exit-review label can appear.
- High proximity alone is not a sell rule and low proximity alone is not a buy
  rule. Entry confirmation needs a support-zone reversal, trend support, and
  volume confirmation; exit review needs stock breakdown, confirmed market
  damage, and the independent held-security risk watch.
- Use adjusted close to place Open/High/Low/Close on one economic scale, but
  compare overlapping raw closes when verifying immutable and provider
  snapshots. Provider adjusted closes may legitimately restate after a
  dividend; rebase only the older frozen adjusted history and preserve provider
  share volume.
- Compute thresholds and percentiles from prior rows only, exclude all rows
  after the valuation close, and require the exact completed close. Store the
  current event as `UNRESOLVED`; do not backfill future returns into live
  features or call an unresolved observation learned evidence.
- The daily OHLCV location artifact is a non-gating research sidecar. It may be
  archived for forward resolution but cannot feed same-close target books,
  orders, cash, champion selection, accepted paper state, production, or live
  trading.
- In a `set -u` workflow, a sidecar added after a paper transaction must reuse
  the exact defined as-of variable. A spelling-only variable drift can strand
  an already-mutated session before integrity and durable publication.
- Missing SPY/QQQ context is not evidence of a benign market. It must suppress
  entry confirmation and produce a data-insufficient review label.
- OHLCV validation must require finite positive Open/High/Low/Close and finite
  nonnegative volume. Filling missing volume solely for validation or allowing
  a zero low can create invalid Fibonacci endpoints and false READY evidence.
- Write forward observations to staged files, rehash inputs before and after
  publication, and remove every run-local data output before a BLOCKED summary.
  A non-gating workflow still archives its directory, so conflicted files left
  beside a BLOCKED marker are not harmless.
- Write the human report before the READY summary commit marker. If report
  finalization fails, remove every run-local data artifact and publish only a
  BLOCKED summary.
- Reject a nonfinite or nonpositive latest VIX observation instead of silently
  treating invalid volatility context as benign. A prior valid row cannot
  substitute for the audited latest date.
- A forward event needs a registered launch anchor and a bounded same-close
  acceptance window. An old hash-valid packet rerun after outcomes are visible
  is historical replay, not an unresolved forward observation.
- If one daily outside bar contains both the range high and range low, OHLCV
  does not reveal their intraday order. Mark the swing ambiguous and exclude
  directional Fibonacci confirmation.
- Do not trust a caller-supplied forward acceptance timestamp. Bind it to the
  observed invocation clock within a small tolerance, and use the official
  NYSE calendar close so half-day sessions remain valid.
- Tied extrema are ambiguous even when `idxmin()` and `idxmax()` choose
  different first occurrences. Directional anchors must be unique and must
  not share any session.
- Downstream research sidecars must enforce the producer schema, accepted
  status, and `exact_packet_ready=true`, not merely one status string.
- Never rebase a frozen adjusted-price prefix from a single overlap row. Use a
  minimum stable initial adjustment regime, its median factor, and a bounded
  dispersion check.
- A forward acceptance window must match the workflow's actual start and
  runtime, including early-close sessions. Keep it bounded before the shortest
  forward outcome can exist; do not register a window the scheduled producer
  chain can never meet.
- Do not take the maximum of availability timestamps after silently dropping
  missing inputs. Every consumed selector, price, macro, VIX, and applicable
  holding timestamp must parse before READY.
- A 252-session return needs 253 observations. A fixed feature family must
  require enough history for every registered return and range rather than
  changing definitions for younger listings.
- When the minimum-history contract changes, update feature-specific regression
  fixtures as well; a 252-row ambiguity fixture correctly became
  `history_underpowered` after this gate was raised to 253.
- Fullrun executed: false. Historical challenger replay executed: false.
  Production enabled: false. Live trading enabled: false.

### 2026-07-29 - Repository-wide GitHub agent operating standard

- Agent: Codex.
- Branch/PR/run:
  `codex/run287-agent-github-operating-standard-20260729`; no workflow
  dispatched.
- Context: Connected GitHub capabilities were available to agents, but the
  repository did not define a shared policy for choosing the connector, local
  git, `gh`, review actions, CI recovery, or optional collaboration plugins.
- Attempt: Added root agent instructions, a detailed GitHub operating
  standard, a PR checklist, and an enforced Tier-1 contract smoke.
- Result: Every future repository-aware agent now receives the same canonical
  source map, exact-head review/merge contract, worktree-preservation rules,
  and Run287 safety boundary.
- Failure or caveat: GitHub's failed-job rerun restarts the job. It is unsafe
  as a generic recovery mechanism for workflows that may already have produced
  targets, orders, fills, ledger mutations, or accepted publications.
- Root cause: Repository guidance previously described individual workflow
  contracts but not a tool-level policy shared across agent implementations.
- Reusable lesson: Tool automation must be classified by side effect. Use
  selective reruns only for proven side-effect-free checks; recover
  transactional work through explicit session, accepted-state, idempotency,
  and durable-publication contracts.
- Review follow-up: A keyword-only policy smoke can pass after a prohibition is
  reversed. Safety enforcement now checks the complete normalized prohibition
  clauses for fullrun, production/live trading, champion auto-promotion,
  transactional reruns, auto-merge, worktrees, PIT backfill, and external
  plugin actions.
- Next action: Build the U0-v2 GitHub census exporter and CI incident evidence
  packet under this standard; add one approved Slack or Teams alert route only
  after the user identifies the project's actual collaboration system.
- Do-not-repeat: Do not remotely overwrite local worktree files, blindly rerun
  transactional jobs, treat notifications as canonical state, enable
  safety/promotion auto-merge, or merge a head not covered by the exact review.
- Evidence files: `AGENTS.md`,
  `docs/RUN287_GITHUB_AGENT_OPERATING_STANDARD.md`,
  `.github/PULL_REQUEST_TEMPLATE.md`, and
  `tests/run287_agent_github_operating_standard_smoke.py`.
- Fullrun executed: false. Durable daily catch-up executed: false. Production
  enabled: false. Live trading enabled: false.

## 2026-07-21 - Issue #315 H2 security-lifecycle correctness

- Unified the scorer, exact-packet evidence, paper ledger, and order preview on
  one point-in-time lifecycle contract. Verified predecessor prices apply
  through `last_trading_date`; successor prices apply only after that date.
- Fixture-first tests reproduced four real defects: a pre-terminal eligible
  fill was skipped, a ticker change marked `80` instead of successor `120`,
  final-stock removal left `CASH=0.5`, and lifecycle-hash-free same-session
  reuse was accepted.
- Pending fills now resolve before terminal settlement, subject to the terminal
  last-trade cutoff. Remaining ineligible orders are then cancelled by the
  lifecycle action.
- Terminal proceeds remain fail-closed. Non-USD proceeds now use the dedicated
  status `BLOCKED_NON_USD_LIFECYCLE_PROCEEDS`; no unverified FX assumption is
  made.
- Removing the last eligible stock materializes explicit `CASH=1.0`.
- Same-session reuse and exact source bundles require lifecycle source and
  snapshot hashes; changed source bytes invalidate reuse.
- Replaced the fixed 989-name assumption with the dynamic invariant
  `pre_lifecycle = excluded + post_lifecycle`, anchored to the independent
  upstream plan's expected pre-lifecycle count. Missing remains neutral and no
  PIT-membership or survivorship-clean claim is added.
- PR review found five valid gaps: scorer cutover was not wired, empty targets
  could become `CASH=1.0`, preview could cross the cutover on fallback, the
  dynamic count was not externally anchored, and proceeds were absent from the
  snapshot hash. All five received regression fixtures and fail-closed fixes.
- Exact-head re-review found one additional valid cutover gap: an existing but
  stale successor cache could still return a prior successor quote. Successor
  rows are now filtered to the effective-date side of the boundary and the
  preview requires the exact requested successor session close.
- Final exact-head review found four more valid integration gaps: future-only
  successor caches could fall back to account basis, preview orders retained
  the untradeable predecessor ticker, restored `data_static` lifecycle paths
  were not portable, and standalone CLI preview calls did not load lifecycle
  links. All four now fail closed or use the verified successor, with focused
  regression fixtures and workflow invocation coverage.
- A subsequent exact-head review found four further execution-boundary gaps:
  successor-symbol sells could miss predecessor-keyed ledger positions,
  legacy sidecar previews supplied lifecycle evidence without an exact
  decision timestamp and hid failure behind `|| true`, `--target-date` could
  use a later snapshot's decision timestamp, and a canonicalized successor
  target could bypass exact-close enforcement. Preview orders now carry both
  execution and ledger tickers, pending fills retain both identities, manual
  workflows require an explicit UTC decision time and fail loud, snapshot
  selection is shared, and target pricing follows the audited logical link.
- The next exact-head review found three caller/safety gaps: Phase A/B quick
  rescore did not pass the now-required decision timestamp, standalone preview
  ignored verified terminal lifecycle tickers, and the script-style smoke had
  gained a CI-unavailable `pytest` import. Quick rescore now requires and
  forwards UTC decision time without masking sidecar failure, standalone
  preview fails closed before emitting terminal-ticker orders, and the smoke
  uses a stdlib assertion context manager.
- A further exact-head review found four PIT/audit gaps: arbitrary older refs
  could reject the new quick-rescore CLI flag, explicit decision time could
  disagree with target metadata, resolved events lost the broker execution
  ticker, and old cutovers downloaded only a recent successor overlap. The
  workflow now feature-detects the flag, explicit/embedded timestamps must
  match, event rows durably retain both ledger and execution symbols with
  legacy hash compatibility, and lifecycle-linked successor history starts at
  the verified cutover and fails closed on a material post-cutover gap.
- The final date-ordering review found that a stale restored account date could
  be paired with the latest target before lifecycle resolution. Preview now
  infers valuation as-of from explicit input or available holding/target
  prices first, reselects the target at that cutoff, and only then resolves the
  matching decision-time lifecycle snapshot.
- The next exact-head review exposed the remaining circular edge: resolving
  lifecycle only after as-of inference meant a predecessor cache ending on the
  last-trading date could hide an exact successor close and pull standalone
  preview backward. Preview now derives a requested session floor solely from
  account/selected-target/decision evidence, resolves verified lifecycle links
  before price inference, and re-resolves at the final cutoff. The dedicated
  regression and repository pytest passed (`129/129`).
- Focused H2 tests passed `52/52`, repository pytest passed `129/129`, and full
  Tier-1 validation passed `191/191` initially in `692.56s` and again on the
  reviewed head in `582.37s`; the exact-successor follow-up passed `191/191`
  in `499.92s`, and final CLI/symbol/archive integration passed `191/191` in
  `464.10s`.
- The four execution-boundary regression fixtures passed, repository pytest
  remained `129/129`, and the first local Tier-1 rerun passed `190/191`; its
  sole failure was the existing structural test counting the four fullrun
  approval inputs after the new non-approval decision-time input was inserted
  inside that block. Moving the input to the normal execution-input section
  restored the structural suite to `129/129`; exact-head CI remains required.
- Official historical evidence remains Main `34.4032% / -25.3629%` and
  Concentrated `49.0968% / -22.9560%`, through 2026-07-10. This is not a July
  17/20 performance refresh.
- Evidence:
  `docs/CODEX_RUN287_H2_LIFECYCLE_CORRECTNESS_RESULT_20260721.md`.
- Fullrun executed: false. Durable daily catch-up executed: false. Production
  enabled: false. Live trading enabled: false.

## 2026-07-22 - Issue #315 H3 risk and Reserve correctness

- Legacy crisis aliases now terminate at explicit input adapters; downstream
  consumers operate on canonical states only.
- Missing and unknown crisis states are fail-closed `DEGRADED_DATA`, source
  stale flags are parsed strictly, and re-entry cannot regress without a new
  worsening risk state.
- Residual cash is explicit, Reserve reasons carry a stable source hash through
  target/preview/ledger/account, and conflicts fail closed.
- Position metrics now split total, equity, and Reserve counts. Explicit
  tradeable Reserve replays remain research-only and invalid for production.
- Integrated broker replay is clamped to the stock evidence end date.
- Focused H3 tests, repository pytest (`129/129`), and full Tier-1 validation
  (`191/191`, `452.77s`) passed.
- Evidence:
  `docs/CODEX_RUN287_H3_RISK_RESERVE_CORRECTNESS_RESULT_20260722.md`.
- Fullrun executed: false. Durable daily catch-up executed: false. Production
  enabled: false. Live trading enabled: false.

## 2026-07-23 - Issue #315 H4a scorecard/runtime trust

- A tracked `verified` or `scorecard_trusted` boolean is not trust evidence.
  Runtime trust must recompute file hashes from the directory-level integrity
  manifest that contains the claimed paper summary.
- Evidence-lane failures must remain local: a current-paper checksum failure
  blocks current-paper and global operating trust but must not rewrite a
  separately verified historical headline as untrusted.
- Required scorecard inputs must not depend on ignored `_tmp_tests` paths.
  Small immutable evidence should be committed with a source-id/path/hash
  bundle manifest; larger restored evidence must use the equivalent checksum
  restore contract.
- A fixed absorbed forward summary is also an immutable input: leaving it under
  ignored `outputs/` breaks clean-checkout scorecard reproduction even when all
  historical fixtures are committed.
- A bundle is not verified by agreement between two declarations. Hash every
  referenced source file's committed bytes, and pin hashes after line-ending
  normalization; otherwise manifest and registry can agree on the same stale
  CRLF digest while the LF blob differs.
- Bundle integrity errors must retain the affected source id and evidence lane.
  A true-forward-only provenance fault must block true-forward/global trust
  without poisoning independently verified historical headline evidence. This
  includes path/hash faults and missing/duplicate source-set members.
- Do not return on a bundle-manifest raw-hash mismatch before parsing its
  members. A stale/tampered manifest hash can otherwise erase the affected
  source id and turn a lane-local true-forward defect into a false historical
  integrity failure. Preserve global fail-closed behavior for parse or
  structural faults.
- The bundle manifest hash is a required root of trust, not an optional
  optimization. Even perfectly matching member declarations and file hashes
  cannot produce `VERIFIED` when the registry's expected manifest SHA-256 is
  absent.
- Required absorbed evidence must be identified by its contract fields, not by
  an already-trusted path prefix. Resolve both registry and manifest paths and
  reject traversal outside the canonical bundle root.
- Directory-manifest verification attests only files in that directory. Bind
  the exact loaded paper summary path and hash to the verified manifest before
  using its metrics or setting runtime paper trust.
- A diagnostic producer's explicit blocked/invalid absorption state outranks
  stale companion artifacts. Suppress those metrics and mark the source lane
  untrusted even when all file hashes are internally consistent.
- Lane trust alone is not enough to fail closed: remove bundle-rejected
  absorbed sources from the usable payload set so downstream builders cannot
  publish their values as `AVAILABLE`. Likewise, a companion CSV is unusable
  whenever its required semantic summary is missing, corrupt, or unparsable.
- Verify a paper summary's exact manifest path and hash before extracting any
  values. Recording a later integrity error does not undo metrics that were
  already emitted, so extraction must occur only after successful binding.
- A verification result and an object loaded before that verification are not
  an atomic snapshot. Re-read one byte buffer after manifest verification,
  compare its hash to the returned manifest, and parse that same buffer for
  metric emission and provenance.
- Rebind the manifest bytes too. If a concurrent publish is supported, leaving
  a pre-verification manifest SHA beside a post-verification snapshot hash and
  summary SHA creates an internally inconsistent trust record.
- Availability and trust blockers must use the rebound payload as well. It is
  inconsistent to emit verified metrics from a post-verification snapshot but
  retain `UNAVAILABLE` or a blocker from a transient pre-verification read.
- Rebound verification must start from the registry path, not from whether the
  initial source loader happened to parse the manifest. Atomic directory swaps
  can make an optional file briefly absent and then restore a complete snapshot.
- Immutable evidence must not embed private machine paths. Rebind committed
  companions to repo-relative paths and explicitly label uncommitted historical
  companions as external with null paths while retaining their hashes.
- Bundle source scoping applies only to members governed by the bundle. If an
  unregistered member id collides with a non-managed registry source, it is
  still a global bundle fault and must not be routed to that source's lane.
- Missing model heads are an expected fail-closed operating condition, not an
  unstructured crash. Emit a blocked report with input hashes and suppress all
  downstream outcome evaluation.
- Focused H4a tests, promotion gate `9/9`, repository pytest `129/129`, and full
  Tier-1 validation (`191/191`, `532.21s` on the final local follow-up head)
  passed.
- Evidence:
  `docs/CODEX_RUN287_H4A_SCORECARD_RUNTIME_TRUST_RESULT_20260723.md`.
- Fullrun executed: false. Durable daily catch-up executed: false. Production
  enabled: false. Live trading enabled: false.

## 2026-07-23 - Issue #315 H4b workflow/promotion trust

- Promotion evidence must be constructed after the accepted transaction and
  must bind to the exact verified paper snapshot; merely running integrity and
  scorecard steps in the same workflow is insufficient.
- Runtime overlays must clear tracked trust and outcome counts first. Otherwise
  a missing runtime artifact can inherit stale positive evidence from source
  control. The reset must precede even the missing-paper early return and must
  include session and decision-week counts.
- Horizon outcome counts must be mapped independently from the ready runtime
  archive. Reusing a single historical count for 21D, 63D, and 126D can make an
  immature challenger appear promotion-ready.
- Publication is part of the transaction boundary: accepted artifacts must
  require both ledger mutation success and all post-gate operating checks.
- Automatic promotion remains prohibited. A complete evidence packet is a
  review input, not authorization to replace the champion.
- Focused H4b tests, repository pytest (`129/129`), and full Tier-1 validation
  (`191/191`, `389.94s` after merging the final H4a branch head into the local
  H4b branch) passed.
- Evidence:
  `docs/CODEX_RUN287_H4B_WORKFLOW_PROMOTION_TRUST_RESULT_20260723.md`.
- Fullrun executed: false. Durable daily catch-up executed: false. Production
  enabled: false. Live trading enabled: false.

## 2026-07-24 - H4b chronological catch-up and durable publication hardening

- A historical market session is not a normal forced daily run. It must be a
  separate replay-only transition that suppresses target recomputation,
  same-close selection, new orders, outcomes, scorecards, and promotion.
- Exact replay prices must become immutable files inside the accepted paper
  snapshot. A pointer to an external cache or a manifest alone is insufficient
  because later cache replacement can silently change historical evidence.
- Replay equity marks must never inflate forward promotion sample counts.
  Recompute eligible sessions from verified `FORWARD_MARK` rows after excluding
  every session in the durable replay-evidence registry.
- Preserve anomalous source OHLC instead of silently repairing it. Record the
  anomaly and allow only the independently valid field required by the narrow
  replay contract; explicitly mark the reference OHLC as execution-ineligible.
- Validate APIs against actual response shapes. GitHub's compare response has
  `base_commit`, `merge_base_commit`, `ahead_by`, and `behind_by`, but no
  `head_commit`. Tests should include captured real payload shapes, not only
  invented fixtures.
- Artifact provenance is a tuple: exact run and artifact IDs, API/ZIP digest,
  repository, workflow identity, branch, SHA lineage, event, terminal state,
  timestamps, and a closed metadata schema. Self-asserted booleans or a digest
  without origin identity are not sufficient.
- Cross-mode continuity requires one shared cache containing the complete
  immutable chain. Separate normal/catch-up caches or terminal-only caching
  lose mode transitions and cannot recover safely from multiple offline runs.
- Append-only CSV acceptance is byte-level, not merely dataframe-equivalent.
  Re-serializing prior floating-point rows can break a valid descendant, so
  retain the frozen header and append bytes without rewriting the prefix.
- Default-branch validation only at workflow start leaves a TOCTOU window.
  Recheck the remote SHA immediately before data/marker writes, canonical and
  accepted publication, cache save, and once more after final publication.
- Real pinned artifacts for 2026-07-17, 20, 21, and 22 produced a four-head
  replay-only chain with zero new orders/fills and terminal
  `f2c95d8c1ca3b1f1fe1fd76f25a65be42734ab5238722222d02a6b8d88b79ebf`.
  All four observations were excluded from promotion counts.
- Pre-H4b workflow reruns cannot be retroactively protected by new YAML. The
  master-only `run287-paper-durable` environment exists and the daily job
  declares it, but isolation is incomplete until fresh Drive credentials are
  added there and the repository-level copies are deleted.
- Focused tests, actual artifact v2 replay/consumer validation, YAML and Bash
  syntax checks, read-only security audit, and final full Tier-1 validation
  (`196/196`, `857.13s`) passed.
- Evidence:
  `docs/CODEX_RUN287_H4B_WORKFLOW_PROMOTION_TRUST_RESULT_20260723.md`.
- Fullrun executed: false. Durable daily catch-up executed: false. Production
  enabled: false. Live trading enabled: false.

## 2026-07-24 - H4b freshness-to-ledger fail-closed boundary

- Setting a strictness input or environment variable is not enforcement. The
  invoked tool must receive its strict flag, and the workflow must reject any
  operator attempt to disable a mandatory target-mutation gate.
- A freshness report is not sufficient evidence for a target builder unless
  the builder consumes it. Bind the exact status and snapshot hashes, source
  run, commit, branch, artifact, session date, and blocker state at the
  same-close materialization boundary. A restored pre-refresh score is
  diagnostic; mutation authority belongs to the attempt-specific exact scorer.
- Candidate coverage needs a declared semantic denominator and fields. Run287
  now uses the post-lifecycle candidate count and requires 98% completeness for
  price, score, 1/3/6/12-month momentum, relative strength, valuation cutoff,
  and feature availability. Ranking eligibility flags are validated separately.
  Duplicate, placeholder, substituted, unexpected, wrong-date, and
  future-available rows fail closed.
- Hashing only the gate JSON leaves a TOCTOU gap. Bind the actual scored-file
  SHA and ticker-set SHA, reconcile it with the decision context, use streaming
  hashes even above 50 MB, and reverify every mutation-bound file immediately
  before target bytes are written.
- A source bundle is not an internally consistent packet merely because each
  member independently has a valid status/date/hash. Verify the downstream
  manifests' recorded upstream SHA edges so same-date artifacts from different
  attempts cannot be spliced into one registry.
- Data identity is not code identity. Freeze one self-hashed Git HEAD/tree plus
  normalized workflow/builder byte identity before upstream work, carry it
  through the immutable source bundle and registry, and compare it with the
  current checkout again at every READY boundary. Otherwise a same-date
  immutable data bundle can be reused under different executable logic.
- Count equality is not universe identity. Freeze the exact universe,
  pre-/post-lifecycle ticker-set hashes, fixed scorer inputs, and consumed
  historical price-cache fingerprints before network work; bind the scorer
  back to that attempt and rehash before publication. Normalize absent-cache
  fingerprints so a legitimate first download is distinct from mutation but
  remains portable across fingerprint implementations.
- Row-level availability must move when exact-close features move. Advance
  refreshed feature rows to at least the scheduled NYSE close while keeping
  score-completion and ingestion timing separate; malformed or future
  holding-watch timestamps must never inflate the effective selector time.
- A ratio allowance for missing alpha values must not relax PIT integrity.
  Invalid tickers, wrong valuation dates, and future availability timestamps
  are absolute blockers even when 99% or more of rows are otherwise complete.
- Every benchmark read by relative strength is an input. Validate and isolate
  SPY, QQQ, and SMH from the macro audit, retain SOXX's separate manifest
  binding, and rehash both original and isolated bytes after selector use.
- Immutable reuse must repeat the fresh-build transitive checks. A matching
  top-level registry/selector/status hash does not excuse revalidating manifest
  outputs, price-map source files, or the final input snapshot. Bind the exact
  producer contract and all non-generated packet inputs, including the holding
  watch and code builders, before accepting an existing selector/risk packet.
- Generated outputs need the same treatment as inputs. Freeze the exact selector
  and candidate-risk output key sets, canonical packet paths and filenames,
  symlink policy, byte sizes, and SHA-256 values; revalidate them after each
  dependent stage and immediately before fresh or reused READY publication.
  `risk_history.jsonl` is part of that contract, not an incidental side file.
- Boolean readiness alone is not a type contract. The target builder must
  require the producer schema and exact READY status as well as
  `exact_packet_ready=true`.
- A skipped downstream builder must still invalidate restored READY markers and
  run-local outputs. Clear the known same-close materializations before the
  chain and emit a current BLOCKED marker when upstream, registry, or producer
  is unavailable.
- A blocked rerun must remove only prior run-local target materializations and
  its READY marker. Accepted paper ledger and canonical state remain untouched.
- Rehash materialized targets after all writes and pass the exact same-close
  status SHA plus both target SHAs into the ledger. The ledger must validate
  that handoff before processing and immediately before atomic publication;
  workflow step order alone is not an integrity boundary.
- A blocked freshness step must precede even the mark-only normal-session
  paper transaction. Historical catch-up remains a separate replay-only path
  and never enters same-close target materialization. Catch-up must also clear
  any restored run-local target bytes before emitting its replay-only marker.
- Fullrun executed: false. Durable daily catch-up executed: false. Production
  enabled: false. Live trading enabled: false.
