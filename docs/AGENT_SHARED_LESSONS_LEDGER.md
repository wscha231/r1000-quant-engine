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
