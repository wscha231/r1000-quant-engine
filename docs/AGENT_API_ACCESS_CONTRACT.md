# Agent API Access Contract

This repository exposes vendor API access through GitHub Actions secrets and
local environment variables. It does not expose plaintext keys in source.

## Available Secret Names

Use these names only. Never write the values to a file, PR, issue, chat, or
artifact.

| Secret/env name | Intended use | Current status |
|-----------------|--------------|----------------|
| `FINNHUB_API_KEY` | Finnhub market data, earnings, recommendations | Estimate endpoints are not entitled on the current key. |
| `ALPHAVANTAGE_API_KEY` | Alpha Vantage earnings-estimate fallback / listing lifecycle | Paused in the default estimate workflow until key rotation is confirmed. |
| `FMP_API_KEY` | Financial Modeling Prep analyst estimates fallback | Returned usable rows in the 2026-07-09 smoke. |
| `FRED_API_KEY` | Macro and rates | Optional for workflows that need macro data. |
| `GOOGLE_SERVICE_ACCOUNT_KEY` / `RCLONE_CONFIG_GDRIVE` | Artifact persistence | Optional but useful for shared archives. |

## How Agents Should Use The Keys

### In GitHub Actions

Use encrypted secrets:

```yaml
env:
  FINNHUB_API_KEY: ${{ secrets.FINNHUB_API_KEY }}
  ALPHAVANTAGE_API_KEY: ${{ secrets.ALPHAVANTAGE_API_KEY }}
  FMP_API_KEY: ${{ secrets.FMP_API_KEY }}
```

### Locally

Use environment variables set outside the repository:

```bash
export FINNHUB_API_KEY=...
export ALPHAVANTAGE_API_KEY=...
export FMP_API_KEY=...
```

Do not commit `.env` files. Do not put example values in docs.

## Safe Smoke For Estimate Feed

```bash
gh workflow run earnings_estimates_daily.yml \
  --repo wscha231/r1000-quant-engine \
  --ref master \
  -f tickers='AAPL' \
  -f ticker_limit=1
```

Expected output contract:

- workflow conclusion: `success`
- `status=completed` when at least one usable estimate row is present
- `fetch_sources` identifies the vendor used
- `available_from=fetch_date`
- `backtest_acceptance_allowed=false`
- `production_activation_allowed=false`
- `live_trading_enabled=false`

Default vendor order is `fmp,finnhub`. Alpha Vantage must be requested
explicitly, for example after key rotation with `-f vendor_order='alphavantage'`.

## What This Does Not Authorize

- No fullrun dispatch.
- No production promotion.
- No live trading.
- No historical backtest use of current estimate snapshots.
- No alpha hook based only on forward snapshots.
- No Alpha Vantage calls until the exposed-key rotation checklist is completed,
  except a bounded post-rotation smoke.

## Required Sharing Discipline

After using an API-backed tool or workflow, update or link an entry in:

- `docs/AGENT_SHARED_LESSONS_LEDGER.md`

Required if anything fails or is caveated:

- workflow run id
- vendor/source used
- coverage ratio
- failed endpoint/status code
- whether any key could have appeared in artifacts/logs
- next action and do-not-repeat note
