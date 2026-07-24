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
| `RUN287_DURABLE_GOOGLE_SERVICE_ACCOUNT_KEY` | Reserved for a future contract version; it must remain unset under v2. |
| `RUN287_DURABLE_RCLONE_CONFIG_GDRIVE` | Required sole Drive credential under v2; marker-bound rclone configuration for the durable paper archive. |
| `RUN287_DURABLE_ENVIRONMENT_ATTESTATION` | Random environment-only authorization value whose SHA-256 is pinned by the reviewed durable-environment contract. |

The daily Run287 workflow maps these environment-only names to its local rclone
variables. Generic repository-level `GOOGLE_SERVICE_ACCOUNT_KEY` and
`RCLONE_CONFIG_GDRIVE` values cannot satisfy its catch-up authentication gate.
The workflow also verifies the environment name and the attestation value
against
`data_static/run287_durable_environment_contract.json`; a same-named repository
secret with an arbitrary value cannot satisfy that cryptographic check. The
same contract pins an HMAC of exactly one configured Drive credential, keyed by
the environment attestation. Therefore an attested environment mixed with a
different repository-scoped credential also fails before Drive setup. The
environment copy of the rclone configuration carries an additional random
comment marker that is absent from the ordinary local/repository credential,
so even the same functional Drive token copied from the unbound local config
does not match the environment-bound HMAC.

Before dispatching catch-up, verify that the attestation and
`RUN287_DURABLE_RCLONE_CONFIG_GDRIVE` exist in the environment, that the
reserved service-account name is absent, and that none of the three names
exists at repository scope:

```bash
gh secret list --repo wscha231/r1000-quant-engine \
  --env run287-paper-durable
gh secret list --repo wscha231/r1000-quant-engine
```

These commands list names and update times only. Never paste any value into
chat or a command transcript. Rotating the attestation requires a new random
value in the environment, a recomputed credential HMAC, and the corresponding
hash updates to the reviewed contract in the same change; never print either
secret while computing those hashes. Normalize the marker-bound rclone
configuration to LF line endings with no trailing newline before both computing
the HMAC and storing the environment secret. GitHub Actions verifies the exact
Linux environment-variable bytes, so a hash computed from a Windows CRLF copy
will fail closed. On Windows, send a multiline rclone value through redirected
standard input rather than `--body`; native argument quoting can rewrite token
content. If a binding fails, use only the secret-safe fingerprint emitted by
the readiness gate to pin the bytes that Actions actually received.

GitHub's default workflow token cannot read repository/environment secret
inventories. Do not add a broad PAT to the workflow. Instead, an owner runs the
reviewed local preflight from the exact current `master` commit. It queries the
two secret-name inventories with the owner's existing `gh` session, checks the
fixed repository/environment/workflow/issue identities, and posts a canonical
15-minute attestation to issue
[#324](https://github.com/wscha231/r1000-quant-engine/issues/324):

```bash
python tools/create_run287_catchup_scope_attestation.py \
  --expected-default-branch-sha <exact-master-sha> \
  --session-date <YYYY-MM-DD> \
  --price-evidence-run-id <run-id> \
  --price-evidence-artifact-digest <sha256:digest> \
  --post \
  --output run287_scope_attestation_receipt.json
```

The command refuses to post unless local `HEAD`, remote `master`, the owner,
repository, workflow, and open anchor issue all match their pinned identities,
and every critical preflight/verifier/workflow/contract path is clean at that
`HEAD`.
It lists names and timestamps only; no secret value is put in the issue or
receipt. `--post` is explicit because it creates an external append-only audit
record.

Dispatch catch-up before the receipt expires and pass its exact `comment_id` as
`catchup_secret_scope_attestation_comment_id`. Pass all other workflow inputs
explicitly: `force_run=true`, `latest_run=outputs`, `strict_selection=true`,
and all three bootstrap flags `false`. The workflow binds the comment to the
exact master SHA, session, price-evidence run/digest, workflow identity, owner
identity, environment-contract hash, and every safe dispatch input. It allows
only run attempt 1.

After initial verification, the serialized workflow appends a
`github-actions[bot]` one-time consumption record to issue #324. Reuse of the
same attestation comment or nonce is blocked. Immediately before paper-ledger
mutation, both comments are fetched again and their immutable timestamps,
authors, bodies, hashes, run binding, and initial receipts are reverified.
The consumed authority is valid only for that exact run/attempt. Its 60-minute
lease must still be live both before the local paper transaction and again
immediately before durable Drive persistence starts; the original 15-minute
dispatch window does not become an open-ended mutation token. Once the checked
durable transaction starts, it is allowed to finish so lease expiry cannot
strand a partially published accepted state.
Only sanitized verification/consumption receipts enter the catch-up artifact;
raw comments and secret metadata do not.

This design deliberately avoids a stored privileged PAT. The short-lived owner
preflight plus runtime environment-attestation and credential-HMAC checks
minimize the metadata-to-run race; an administrator intentionally changing
secret scope after attestation still requires a fresh owner audit before any
further catch-up.

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
