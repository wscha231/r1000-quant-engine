# GitHub Secrets Setup Guide

GitHub Actions workflows use repository secrets for market data, brokerage
paper-account access, notifications, and Google Drive sync. Do not put secret
values in this file, PR bodies, issue comments, artifacts, or handoff notes.

## Setup

1. Open the repository on GitHub.
2. Go to **Settings** -> **Secrets and variables** -> **Actions**.
3. Add each secret by exact name.
4. Paste the value only into GitHub's encrypted secret field.
5. Never commit `.env`, copied keys, screenshots of keys, or vendor messages
   that echo a key.

## Current Secret Names

| Name | Purpose | Notes |
|------|---------|-------|
| `ALPACA_API_KEY` | Alpaca paper-account key | Paper only unless an explicit live gate says otherwise. |
| `ALPACA_API_SECRET` | Alpaca paper-account secret | Paper only unless an explicit live gate says otherwise. |
| `FINNHUB_API_KEY` | Finnhub market/earnings endpoints | Current key is not entitled for Finnhub estimate endpoints. |
| `ALPHAVANTAGE_API_KEY` | Alpha Vantage earnings-estimate fallback / listing lifecycle | Paused in default estimate workflow until key rotation is confirmed. |
| `FMP_API_KEY` | Financial Modeling Prep estimate fallback | Free endpoint currently returns usable rows for some tickers. |
| `FRED_API_KEY` | Macro data | Optional unless a workflow explicitly requires it. |
| `TELEGRAM_BOT_TOKEN` | Notifications | Optional for local research-only work. |
| `TELEGRAM_CHAT_ID` | Notifications | Optional for local research-only work. |
| `GOOGLE_SERVICE_ACCOUNT_KEY` | Google Drive sync | Use only in workflows that sync artifacts. |
| `RCLONE_CONFIG_GDRIVE` | Google Drive sync | Alternative to service-account JSON. |
| `GDRIVE_ROOT_FOLDER_ID` | Google Drive root | May be a secret or repository variable. |

## Run287 Durable Environment Secrets

Chronological Run287 paper-ledger catch-up uses dedicated secrets in the
`run287-paper-durable` GitHub environment. Add these names to that environment,
not to repository secrets:

| Environment-only name | Purpose |
|-----------------------|---------|
| `RUN287_DURABLE_GOOGLE_SERVICE_ACCOUNT_KEY` | Service-account JSON for the durable paper archive. |
| `RUN287_DURABLE_RCLONE_CONFIG_GDRIVE` | Alternative rclone configuration for the durable paper archive. |

The daily Run287 workflow maps these environment-only names to its local rclone
variables. Generic repository-level `GOOGLE_SERVICE_ACCOUNT_KEY` and
`RCLONE_CONFIG_GDRIVE` values cannot satisfy its catch-up authentication gate.
Before dispatching catch-up, verify that at least one dedicated name exists in
the environment and that neither dedicated name exists at repository scope.
Never paste either value into chat or a command transcript.

## Agent Access Contract

Agents must use these secrets through one of two paths:

- GitHub Actions environment variables, for example
  `${{ secrets.FMP_API_KEY }}` inside a workflow.
- Local environment variables on the user's machine, provided outside the repo.

Agents must not ask another agent to paste a key into chat or commit a key into
the repository. If an API response echoes a key, redact it before writing logs,
summaries, artifacts, or review packets.

## Verification

Use `gh secret list --repo wscha231/r1000-quant-engine` to confirm names only.
This command must never print values.

For the forward estimates feed, a safe smoke is:

```bash
gh workflow run earnings_estimates_daily.yml \
  --repo wscha231/r1000-quant-engine \
  --ref master \
  -f tickers='AAPL' \
  -f ticker_limit=1
```

The default estimate workflow vendor order is `fmp,finnhub`; this intentionally
pauses Alpha Vantage calls until the prior key-exposure incident is closed with a
rotated key. After rotation, an Alpha Vantage-only smoke can be run manually with
`-f vendor_order='alphavantage'`.

Expected behavior:

- workflow conclusion: `success`
- `backtest_acceptance_allowed=false`
- `production_activation_allowed=false`
- `live_trading_enabled=false`
- no raw API key appears in logs or artifacts

## Incident Handling

If a key appears in a log, artifact, document, PR, or chat:

1. Delete the affected artifact/run when possible.
2. Patch redaction before rerunning.
3. Add an entry to `docs/AGENT_SHARED_LESSONS_LEDGER.md`.
4. Rotate the key if it may have been exposed outside GitHub's encrypted secret
   store.
