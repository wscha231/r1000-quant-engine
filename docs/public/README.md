# Run287 public portfolio dashboard

This directory is the **only** content published to GitHub Pages at:

`https://wscha231.github.io/r1000-quant-engine/`

The site is a static, read-only view of the Run287 simulated broker ledger. It
shows Main and Concentrated portfolio weights, cash weights, validated research
metrics, recent replay trades, separately labelled forward paper fills,
review-only target deltas, and a filtered code change log.

The current allocation view includes side-by-side donut charts for both
portfolios. Each chart has an explicit button that opens the matching backtest
BUY/SELL ledger; the ledger can switch portfolios, filter by side or ticker,
and progressively reveal the complete published history.

## Public data boundary

Published:

- ticker and current/target portfolio weights;
- latest completed US-market close and public market price;
- CAGR, MDD, Sharpe, average/latest cash weight, OOS metrics;
- replay and forward-paper BUY/SELL date, signal date, fill price, target
  weight, reason, and explicit record type;
- review-only current-vs-target deltas, explicitly marked as not executed.

Never published:

- total account or cash dollar value;
- share/order quantity, market value, cost basis, realized/unrealized P&L;
- fees in dollars, local paths, source artifact internals, API secrets;
- automatic order tickets or live-trading instructions.

`tools/build_public_portfolio_dashboard.py` enforces this allowlist and fails if
a forbidden field, secret-like value, or absolute local path reaches
`data/dashboard.json`. The dashboard itself also refuses payloads whose
`review_only` and `live_trading_enabled=false` safety flags are absent.

## Daily update flow

1. `Daily Operating Selection Refresh` is scheduled for 10:15 KST Tuesday
   through Saturday. An exact NYSE calendar gate identifies weekends, US
   holidays, and early closes, then requires at least a 90-minute data buffer.
   A stale session older than 18 hours is skipped.
2. `.github/workflows/pages_deploy.yml` ingests a portfolio artifact only after
   that workflow succeeds on `master`. Independent public close observations
   also refresh at 02:35 UTC Tuesday–Saturday and after a failed daily run.
3. The daily workflow restores the last validated private paper state, resolves
   prior pending orders at the next cached close, and enqueues a new batch only
   when the normalized target allocation changed.
4. Before any paper mark or fill, every current holding, current target,
   pending-order ticker, and required benchmark must have an exact close for
   that completed session. A prior-session price is not an allowed fallback.
5. The Pages workflow downloads the exact artifact, overlays current holdings,
   target weights, review previews, and allowlisted forward paper fills on the
   last validated public snapshot, re-runs the privacy smoke test, and deploys
   **only `docs/public/`**.
6. Missing or failed daily artifacts cannot update the portfolio. The last
   deployed public portfolio is restored before any asset/quote publication,
   avoiding a reset to the older tracked seed. Invalid portfolio artifacts
   still abort publication. Missing quotes are explicitly unavailable; no
   prior-session fallback is shown as the requested close.

## Independent prices and freshness

`market-quotes.json` observes only tickers already in the public holdings.
It is not a new selection, portfolio revaluation, or performance calculation.
`dashboard.json` retains its own portfolio, weights, metrics, and history dates.
The UI shows both price columns with dates and suppresses stale target deltas
and proposals. A stale portfolio gets an amber notice even if quotes are absent.

Quotes use existing Alpaca credentials against the market-data-only SIP
daily-bar endpoint, with raw (unadjusted) closes. No broker endpoint is called.
If credentials are absent, public Yahoo daily bars are used. Authentication
errors do not trigger credential retries or silently change feeds. Every bar
must match the NYSE session in New York time, be finite and positive, and have
one unambiguous observation. A response hash records the public source bytes.
The exchange calendar, holidays, early closes, and a 90-minute settlement
buffer are required. Partial observations cannot claim a complete quote date.
Freshness proof expires at the next NYSE close, using the exchange calendar.
Missing/malformed proof or an expired deadline suppresses target deltas and
proposals, including when the portfolio is only one day old. Weekends and
exchange holidays do not invent an intervening close.

This price panel does not resolve the legacy risk-outcome migration or
Google Drive OAuth errors in the transactional daily workflow. Recover that
state through its reviewed chronological contract before reporting updated
account weights, fills, or CAGR/MDD.

The daily ledger is simulated and review-only. It freezes integer-share order
quantities after a completed close, resolves them no earlier than the next
observable close with 25 bps cost and no negative cash, and records fills or
rejections in a hash chain. It never calls a broker and never converts the
same-day order preview into a fill. Private quantities and dollar values remain
inside the workflow artifact and persistent paper archive; the public payload
contains only the allowlisted fill fields.

The forward equity curve is an operating monitor, not a replacement for the
validated historical CAGR/MDD evidence. Forward CAGR remains `UNDERPOWERED`
until at least 252 observations and 300 elapsed days are available.

## Local refresh

From the repository root:

```powershell
python tools/build_public_portfolio_dashboard.py `
  --source outputs\<validated-run-directory> `
  --output docs\public\data\dashboard.json `
  --repo-root .

python tests\public_portfolio_dashboard_smoke.py
```

Serve the folder with any static server. For example:

```powershell
python -m http.server 8000 --directory docs\public
```

Then open `http://localhost:8000/`.

## GitHub Pages source protection

The repository Pages setting must be **GitHub Actions** (`build_type=workflow`),
not the legacy `master:/docs` branch source. The workflow packages
`docs/public/` as the artifact root, so internal strategy documents under
`docs/` are not included in the website deployment.

## Adding a custom domain later

No application rewrite is required. All site assets and data use relative URLs.
After buying and verifying a domain:

1. set the custom domain in repository **Settings → Pages**;
2. create the DNS record requested by GitHub (for a subdomain, point its CNAME
   to `wscha231.github.io`, without the repository name);
3. wait for DNS/certificate activation and enable HTTPS enforcement.

For an Actions-based Pages deployment, GitHub stores the custom-domain setting;
a tracked `CNAME` file is not required.
The publisher reads `actions/configure-pages`' canonical `base_url` before
restoring public data, so custom domains do not require following redirects.
For a manual local restoration, pass the canonical full JSON URL with
`--preserve-deployed --deployed-url https://your-domain/data/dashboard.json`.


## Project results connection

The homepage's Project Results panel is built by
`tools/build_public_project_results.py` on every Pages build. It reuses the
existing daily research monitor's exact master workflow, artifact SHA-256,
member and score-lineage checks. Four read-only source requests run concurrently.
It never executes source artifacts or publishes the private monitor report.
Only the explicit public field allowlist reaches `data/project-results.json`.

After-close, estimates, ownership, research-monitor and long-history completions
also trigger Pages, regardless of success, so failed producers remain visible.
A daily 08:45 UTC reconciliation supplements the existing post-close schedule.
Only the **Daily Operating Selection Refresh** event with a successful
completed-session artifact can enter the existing portfolio publisher. All
other events refresh research and quotes only.

The table is the existing 33-name US/KR research watchlist, **not the 1,118-name
universe or a stock ranking**. Valid nonranking score exports appear automatically;
missing scores stay unavailable. Korea needs its upstream adapter. Source runs
and artifact hashes, source commit, config hash and public content hash are kept
in the public JSON. Long-history status reports workflow execution only until a
separate accepted catalog adapter exists; it does not certify its data coverage.

The theme panel reports input dates and aggregate coverage only, not unvalidated
legacy top-stock recommendations. Legacy macro/ETF exporters lack individual
observation dates, so their collection dates and missing-price counts are
reported without treating their regimes/returns as current investment signals.
The browser refreshes every five minutes and on focus; score/price display
expires with the matching quote session freshness deadline. Account dates,
weights, replay metrics and paper-ledger publication retain their existing gates.
