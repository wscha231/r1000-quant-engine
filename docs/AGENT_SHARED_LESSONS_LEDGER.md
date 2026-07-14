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
