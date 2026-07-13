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
2. `.github/workflows/pages_deploy.yml` runs only after that workflow succeeds
   on `master`.
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
6. If the market was closed, the exact-close artifact is absent and Pages
   deployment is skipped. If the source is stale, incomplete, not review-only,
   unsafe, or malformed, publication fails closed and the previously valid site
   remains live.

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
