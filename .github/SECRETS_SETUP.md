# GitHub Secrets Setup Guide

GitHub Actions workflows need 5 secrets. Register them ONCE via the GitHub web UI.

## Steps

1. Go to your GitHub repo page: `https://github.com/<your-username>/<repo-name>`
2. Click **Settings** (top right of repo header)
3. Left sidebar: **Secrets and variables** → **Actions**
4. Click **New repository secret** for each entry below
5. Paste the value, click **Add secret**

## Required Secrets

Copy each NAME exactly (case-sensitive). Values from `aggressive/.env`:

| Name | Value | Source |
|------|-------|--------|
| `ALPACA_API_KEY` | `PKN6G6BTQVTGFNDB4MNO3UOKDV` | Alpaca Paper dashboard |
| `ALPACA_API_SECRET` | `CHvYPYy5GzGMJtgYD7SsLrjfCiaJWf4ohr5bom49iaWp` | Alpaca Paper dashboard |
| `FINNHUB_API_KEY` | `d2s60dhr01qiq7a2q0h0d2s60dhr01qiq7a2q0hg` | Finnhub (Free tier) |
| `TELEGRAM_BOT_TOKEN` | `8645815408:AAFiFze421PxrcAgwdvPJapn7dvniyJ_C2k` | @BotFather on Telegram |
| `TELEGRAM_CHAT_ID` | `506878539` | Your Telegram chat ID |

After adding all 5, the **Actions** tab will show workflows as runnable.

## Workflows Installed

| Workflow | Schedule (UTC / KST) | Duration | Purpose |
|----------|----------------------|----------|---------|
| `daily_review.yml` | 14:00 UTC Mon-Fri / 23:00 KST | ~15-30 min | R1000 scan + Finnhub gates + advisor + Telegram |
| `finnhub_weekly.yml` | 13:30 UTC Mon / 22:30 KST | ~65-90 min | Full Finnhub metric/insider/earnings refresh |
| `theme_discovery.yml` | 13:00 UTC Sun / 22:00 KST | ~15-30 min | Phase 18A unsupervised theme discovery |

All 3 can be manually triggered via **Actions** tab → select workflow → **Run workflow**.

## Free Tier Budget

- GitHub Actions free tier: **2000 minutes/month** (private repos) or **unlimited** (public)
- Our monthly usage estimate:
  - daily_review: 22 days × 25 min = 550 min/month
  - finnhub_weekly: 4 runs × 75 min = 300 min/month
  - theme_discovery: 4 runs × 25 min = 100 min/month
  - **Total: ~950 min/month** (well under 2000 limit)

## Verifying a Workflow Run

1. Go to **Actions** tab
2. Click workflow name (e.g. "Daily Review (Scanner + Advisor)")
3. Click the most recent run
4. Expand step logs to see output
5. Check **Artifacts** section (bottom) for result JSON
6. Check Telegram for digest alert

## Result Persistence

- **Summary JSONs** get auto-committed to `cloud_results/` directory
  - `cloud_results/daily_review/20260424.json`
  - `cloud_results/scanner/20260424.json`
  - `cloud_results/theme_discovery/20260424.json`
- **Large artifacts** (parquet files) go to workflow artifacts (14-30 day retention)
- **Consolidated Finnhub parquet** gets committed to `aggressive/state/finnhub/`

Read `cloud_results/*/latest.json` from any device — phone, laptop, another PC.

## Troubleshooting

### Workflow fails with "credentials not set"
→ Verify each secret is spelled EXACTLY as the table above.

### Workflow timeout
→ Free tier max job time: 6 hours. Shouldn't hit for our workloads.

### "Permission denied" on git push
→ Already configured via `permissions: contents: write` in workflow YAML.
   If still failing, check repo Settings → Actions → General → Workflow permissions:
   set to "Read and write permissions".

### Rate limited by Finnhub
→ Free tier: 60 calls/min. Our collector respects this via RateLimiter class.
   If still hits, the collection simply takes longer (auto-retries).

### Alpaca data fetch fails
→ Free tier works fine for daily bars. If paper account gets suspended, re-check
   your credentials (keys may rotate).

## Deleting Test Runs

Workflow runs (including artifacts) can be deleted manually from the **Actions** tab
if the repo fills up. Consider gitignoring `cloud_results/` if you don't want the
history in git. Otherwise let it accumulate — tiny files, worth the audit trail.

## One-Time Push Instructions

After committing these workflow files:

```bash
cd H:\codex\tmp_r1000_quant_engine
git push origin master
```

Then go to https://github.com/<your-repo>/actions to verify they appear.

First automatic run happens at the next scheduled time. Manual test run via
web UI is recommended to verify setup.
