# Mobile-Only Google Drive Auto-Sync Setup

When GitHub Actions full_rebuild_manual finishes, results auto-sync to
`r1000_top30_institutional/outputs/` on your Google Drive — visible from
mobile/PC/web instantly.

**Setup time**: 10-15 minutes, **once**. After this, every workflow
run pushes results to Drive automatically.

**No PC required.** All steps are doable on mobile browser + Drive app.

---

## Step 1 — Google Cloud Console (mobile browser, ~5 min)

Open: https://console.cloud.google.com on Chrome/Safari (mobile).
Sign in with the **same Google account** that owns Drive.

### a. Create a project
- Top-left project picker → **NEW PROJECT**
- Name: `r1000-sync` → **CREATE**
- Wait ~10s, switch to the new project (top-left picker shows it)

### b. Enable the Drive API
- Left menu (≡) → **APIs & Services** → **Library**
- Search: "**Google Drive API**" → tap result
- **ENABLE**

### c. Create a Service Account
- **APIs & Services** → **Credentials**
- **+ CREATE CREDENTIALS** → **Service account**
- Name: `r1000-bot` → **CREATE AND CONTINUE**
- Skip "Grant access" step (optional) → **DONE**

### d. Download JSON key (most important)
- On Credentials page, tap the new `r1000-bot@...` service account
- **KEYS** tab → **ADD KEY** → **Create new key** → **JSON** → **CREATE**
- A JSON file downloads to your phone (filename like `r1000-sync-abc123.json`)
- ⚠️ This file is the credential — keep it private

### e. Copy the service account email
- Same page, top section shows email like:
  `r1000-bot@r1000-sync.iam.gserviceaccount.com`
- Copy this email — you'll need it in Step 2

---

## Step 2 — Share Drive folder (mobile Drive app, ~1 min)

- Open **Google Drive** app on your phone
- Find the `r1000_top30_institutional` folder
- Long-press the folder → **Share** (or 3-dot menu → Share)
- Tap **Add people**
- Paste the service account email from Step 1e
- Permission: **Editor** (must be Editor, not just Viewer)
- Tap **Send** (or done)
- The folder is now writable by the service account

---

## Step 3 — GitHub Secret (mobile browser, ~2 min)

Open: https://github.com/wscha231/r1000-quant-engine/settings/secrets/actions

- **New repository secret**
- Name: `GOOGLE_SERVICE_ACCOUNT_KEY`
- Secret value: paste the **entire content** of the JSON file from Step 1d
  - On Android: open Files app → tap JSON file → "Open as text" → select all → copy → paste
  - On iOS: Files app → JSON → text editor → select all → copy → paste
  - The pasted content should start with `{` and end with `}`
- **Add secret**

Optional but recommended for service accounts:
- Open the Drive folder in a browser and copy the folder ID from the URL:
  `https://drive.google.com/drive/folders/<FOLDER_ID>`
- In GitHub **Actions variables**, add:
  - Name: `GDRIVE_ROOT_FOLDER_ID`
  - Value: the copied folder ID

This makes rclone write directly inside `r1000_top30_institutional/` instead
of relying on Drive's "Shared with me" folder lookup.

---

## Step 4 — Trigger workflow

Open: https://github.com/wscha231/r1000-quant-engine/actions/workflows/full_rebuild_manual.yml

- Branch: `master`
- universe_mode: `r1000+adr`
- skip data collection: ☑
- **Run workflow**

After ~5-6 hours, the workflow finishes and:
1. Telegram sends verdict text + zip attachment (mobile-direct)
2. **Files appear in Google Drive** under `r1000_top30_institutional/outputs/`:
   - `scored_latest.csv`
   - `scored_unified.csv`
   - `portfolio_latest.csv`
   - `concentrated_portfolio_latest.csv`
   - `backtest_metrics.json`
   - `concentrated_backtest_metrics.json`
   - `full_rebuild_logs/` (run log + verdict)

---

## How to verify it worked

After the next successful workflow run:

1. Open Drive app → `r1000_top30_institutional/outputs/`
2. Check that file timestamps match workflow finish time
3. Open `backtest_metrics.json` (Drive auto-preview) — see SHIP/PARTIAL/REGRESS

If files don't appear:
- Workflow log step "Sync outputs to user's Google Drive" — check for errors
- Most common: forgot to share folder with service account email (Step 2)
- 2nd most common: JSON pasted incorrectly (must be valid JSON, opens with `{`)

---

## Security notes

The service account JSON has access only to:
- The specific Google Drive folder you shared in Step 2 (and its contents)
- It does NOT have access to your Gmail, Photos, Calendar, or any other Drive folder

If you ever want to revoke access:
1. Drive app → folder share settings → remove the service account email
2. OR: Cloud Console → Service Accounts → delete `r1000-bot`

---

## Cost

Free. Google Cloud Free Tier includes:
- Drive API: 1,000 requests / 100 seconds (more than enough)
- Service Account creation: free
- Project: free (no billing required for read/write Drive)

---

## What about other workflows (daily_review, paper_executor, etc)?

Currently only `full_rebuild_manual.yml` has the gdrive sync step. Other
workflows still commit to repo `cloud_results/` only.

To extend: copy the "Sync outputs to user's Google Drive" step from
`.github/workflows/full_rebuild_manual.yml` into the desired workflow,
adjust the file list to match what that workflow produces, and push.

Or wait — the next session can do this if needed.
