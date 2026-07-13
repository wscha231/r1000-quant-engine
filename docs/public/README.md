# Run287 public portfolio dashboard

This directory is the **only** content published to GitHub Pages at:

`https://wscha231.github.io/r1000-quant-engine/`

The site is a static, read-only view of the Run287 simulated broker ledger. It
shows Main and Concentrated portfolio weights, cash weights, validated research
metrics, recent replay trades, review-only target deltas, and a filtered code
change log.

## Public data boundary

Published:

- ticker and current/target portfolio weights;
- latest completed US-market close and public market price;
- CAGR, MDD, Sharpe, average/latest cash weight, OOS metrics;
- replay BUY/SELL date, signal date, fill price, target weight, and reason;
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

1. `Daily Operating Selection Refresh` runs after the latest completed NYSE
   close and emits a review-only GitHub artifact.
2. `.github/workflows/pages_deploy.yml` runs only after that workflow succeeds
   on `master`.
3. The Pages workflow downloads the exact artifact, overlays current holdings,
   target weights, and review previews on the last validated public snapshot,
   re-runs the privacy smoke test, and deploys **only `docs/public/`**.
4. If the source is missing, not review-only, unsafe, or malformed, deployment
   fails and the previously valid site remains live.

Daily artifacts do not currently include an executed broker trade ledger. The
site therefore retains the last validated replay trade history and displays
daily target deltas in a separate **not executed** table. It never converts an
order preview into a trade record.

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
