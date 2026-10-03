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
| `FMP_API_KEY2` | Explicit FMP account selection in the collector/manual workflow and source-only sample | Registered; actual endpoint entitlement unverified. No automatic fallback or quota pooling. |
| `EODHD_API_KEY` | EODHD account usage and v1.1 analyst Trend sample | Registered; Fundamentals entitlement unverified. Not enabled in the operational collector. |
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
gh workflow run earnings_estimate_source_probe.yml \
  --repo wscha231/r1000-quant-engine \
  --ref master \
  -f expected_head='<exact reviewed and approved master SHA>' \
  -f provider='eodhd' -f tickers='AAPL' \
  -f max_http_requests=2 -f verified_api_units=10
```

This example is not dispatch approval. Obtain the attached task's explicit
execution approval after review and authorized merge. Do not dispatch the
transactional earnings workflow as a credential test: it includes overlays,
paper and durable publication. EODHD's live usage response must admit the budget;
FMP/FMP2 require fresh verified shared-quota evidence within 15 minutes.

Expected diagnostic contract:

- source GET attempts, including quota check, never exceed the approved cap
- selected credential name identifies one account; no key values/fingerprints
- observed EPS/revenue counts and identity completeness are reported separately
- `SAMPLE_PROBED` does not prove usable universe coverage
- provider 402/403, missing data and missing economic identity remain explicit
- raw provider/account responses and estimate values are not persisted
- `historical_pit_certified=false`
- `production_activation_allowed=false`
- `live_trading_enabled=false`

The operational default vendor order remains `fmp,finnhub`. Alpha Vantage must be requested
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
