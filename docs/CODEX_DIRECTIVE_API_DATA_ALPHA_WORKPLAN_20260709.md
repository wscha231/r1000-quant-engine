# Codex / Claude Directive - API Data Archive And Alpha Evidence Plan - 2026-07-09

## Purpose

Use the newly available API secret surface to collect forward data, evaluate
whether it can strengthen Concentrated CAGR/MDD, and keep every failed or useful
attempt in the shared lessons ledger.

This directive is for Codex, Claude, GPT Pro, and any other agent reviewing or
continuing the work. Do not paste raw API key values into docs, PRs, issues,
artifacts, or chat. Use secret names only.

## Current API Access Surface

GitHub repository secrets are the source of truth:

- `FMP_API_KEY`
- `ALPHAVANTAGE_API_KEY`
- `FINNHUB_API_KEY`

Known status:

- FMP returned usable forward estimate rows in the final safe smoke.
- Alpha Vantage is available but free-tier/rate-limit behavior must be expected.
- Finnhub's current repo key is not entitled for estimate endpoints.
- A candidate Finnhub replacement key failed authorization with HTTP 401 and was
  not left installed.

Reference docs:

- `docs/AGENT_API_ACCESS_CONTRACT.md`
- `docs/AGENT_SHARED_LESSONS_LEDGER.md`
- `docs/CODEX_FORWARD_EARNINGS_ESTIMATE_FEED_20260709.md`

## Hard Boundary

The new free API data is current/forward snapshot data unless a vendor provides
true point-in-time estimate history with decision-time availability stamps.

Allowed:

- daily forward-only estimate archive
- latest candidate confirmation
- forward paper-ledger evidence
- research-only coverage and source-quality reports
- PIT-safe historical A/B using already timestamped sources such as SEC Form 4,
  SEC 13F, and accepted filing timestamps

Forbidden:

- retrofitting current estimate snapshots into 2019-2026 replay windows
- claiming 7Y CAGR/MDD improvement from forward-only snapshots
- adding a production alpha hook from unvalidated current estimates
- dispatching a fullrun
- production promotion or live trading
- quoting raw API keys in any shared artifact

## Existing Workflow To Use

The forward estimate archive already exists:

- `.github/workflows/earnings_estimates_daily.yml`
- `tools/collect_earnings_estimates_finnhub.py`

Safe one-ticker smoke:

```bash
gh workflow run earnings_estimates_daily.yml \
  --repo wscha231/r1000-quant-engine \
  --ref master \
  -f tickers='AAPL' \
  -f ticker_limit=1
```

Expected contract:

- `status=completed` if at least one usable estimate row is returned
- `fetch_sources` identifies the vendor used
- `available_from=fetch_date`
- `backtest_acceptance_allowed=false`
- `production_activation_allowed=false`
- `live_trading_enabled=false`

Archive outputs are persisted through workflow artifacts/cache and optional
GDrive sync. Do not commit a growing data lake to the repository.

## Can This Improve CAGR/MDD?

Short answer:

- It can improve future selection discipline and paper-ledger evidence now.
- It cannot honestly improve historical 7Y CAGR/MDD until enough forward PIT
  archive exists or a paid PIT estimate-history source is added.

Near-term safe value:

- identify Concentrated candidates with positive estimate revision breadth
- reject or down-rank candidates with deteriorating estimates or widening
  dispersion
- confirm replacement/missed-leader candidates only when estimate revisions
  support the move
- report whether the new data would have changed the latest target book without
  changing historical backtest claims

Historical CAGR/MDD work that remains allowed:

- fixed-book 13F/Form4/SEC accepted-ts A/B
- broker-ledger replay on PIT-safe event data only
- OOS-first screening before hook design
- no signal combination until a single source has positive OOS evidence

## Immediate Work Plan

### A. Daily Archive And Coverage

1. Run bounded forward estimate archive jobs for a small watchlist first:
   - current Concentrated holdings
   - replacement candidates
   - recent missed leaders
   - SPY/QQQ benchmark symbols if supported by the vendor
2. Produce a coverage summary:
   - ticker count requested
   - ticker count with usable estimates
   - `estimate_coverage_ratio`
   - vendor source by ticker
   - missing ticker list
   - endpoint/status-code failures after redaction
3. Leave missing names neutral. Do not penalize a ticker just because a free
   vendor lacks coverage.

### B. Latest Candidate Confirmation

Use existing default-OFF logic only:

- `apply_estimate_revision_confirmation()`
- `PHASE_ESTIMATE_REVISION_CONFIRM_ENABLED=false`

Test it as a latest-only sidecar:

- input: latest Concentrated candidate/replacement set
- output: confirmed, neutral, and rejected-by-estimate-deterioration buckets
- no historical backtest mutation
- no fullrun

### C. Forward Paper Ledger

Start measuring whether the estimate-confirmed bucket improves future outcomes:

- append-only date/ticker/signal snapshot
- next-close reference price
- benchmark reference, preferably SPY total-return proxy if available
- 21D/63D/126D forward outcome once elapsed
- excess return vs benchmark
- drawdown during holding window

Labels:

- `forward_signal_observed`
- `paper_ledger_candidate`
- `not_backtest_acceptance`

### D. Historical Evidence Still Needed

For immediate CAGR/MDD claims, do not use current API snapshots. Use only:

- SEC 13F with filing accepted timestamp or `available_from`
- SEC Form 4 with accepted timestamp
- SEC financial-statement events with accepted timestamp
- existing broker-ledger fixed-book replay paths

If paid PIT estimate history becomes available later, the first task is a data
contract audit:

- vendor/source name
- source hash
- ticker/entity id
- estimate type
- estimate period
- estimate value
- analyst count or breadth when available
- revision timestamp
- `available_from`
- ingestion timestamp
- no use before `available_from`

Only then can historical estimate revision signals enter a 7Y replay.

## CAGR/MDD Decision Gates

For any candidate derived from API data, report:

- Main and Concentrated separately
- CAGR
- MDD
- Sharpe
- excess CAGR vs SPY or selected benchmark
- down-capture in weak benchmark windows
- beta-adjusted alpha if available
- zero-yield and cash-carry accounting separately when broker replay is used
- PIT status and production promotion status

Gate rules:

- Concentrated is the only near-term alpha target.
- Main MDD remains a structural risk problem, not a free-API alpha problem.
- A current-snapshot improvement is not a 7Y pass.
- Single-source OOS positive evidence must come before fusion.
- Fusion of weak signals is forbidden until one source works alone.

## Shared Lessons Requirement

Every non-trivial API-backed attempt must add or link an entry in:

- `docs/AGENT_SHARED_LESSONS_LEDGER.md`

Minimum entry fields:

- agent
- branch / PR / workflow run id
- vendor/source used
- endpoints used
- coverage ratio
- failures and status codes
- whether any credential could have appeared in logs or artifacts
- result label
- next action
- do-not-repeat note

If a key appears in a vendor message, artifact, workflow log, or chat:

- redact code paths immediately
- delete affected artifacts/runs when possible
- record the incident without the key value
- recommend rotation

## Claude Review Request

Claude should review the current repo state and answer:

1. Does the forward estimate archive remain backtest-neutral?
2. Are all key references secret-name-only, with no raw values in docs/artifacts?
3. Is FMP/Alpha/Finnhub coverage classified by usable rows instead of by any
   vendor error?
4. Is the proposed latest-only Concentrated confirmation path safe from
   look-ahead?
5. Which single-source PIT-safe historical path should be tested next:
   13F, Form 4, SEC actual-results event, or paid PIT estimate history?

Expected Claude verdict labels:

- `archive_safe_forward_only`
- `needs_secret_rotation`
- `historical_backtest_blocked_without_pit_estimates`
- `single_source_oos_test_allowed`
- `fusion_forbidden_until_single_source_positive`

## Default Next Action

Run and inspect a bounded forward archive for the active Concentrated watchlist,
then produce a latest-only confirmation report. Do not modify target books,
dispatch fullrun, or claim CAGR/MDD improvement from it.

In parallel, continue PIT-safe fixed-book historical A/B only for single-source
signals with real decision-time availability.
