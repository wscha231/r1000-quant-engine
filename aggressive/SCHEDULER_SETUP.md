# Windows Task Scheduler Setup - Aggressive Engine

Two scheduled tasks:

## 1. Daily Review (weekdays during market hours)

**Purpose**: Scan universe, evaluate positions, generate trade decisions, execute orders (if enabled).

**File**: `aggressive\run_daily.bat`

**Recommended schedule**: Mon-Fri at 23:00 KST (10:00 AM ET, 30 min after US market open)

### Setup (Windows Task Scheduler GUI)

1. Open `taskschd.msc` (Task Scheduler)
2. Right-click "Task Scheduler Library" -> "Create Task..."
3. **General tab**:
   - Name: `r1000_aggressive_daily`
   - Security: "Run whether user is logged on or not" (so it fires when PC is locked)
   - Check "Run with highest privileges" (for log file access)
4. **Triggers tab** -> New:
   - Begin: "On a schedule"
   - Weekly, Mon-Fri, at `23:00` KST
   - Enabled: checked
5. **Actions tab** -> New:
   - Action: "Start a program"
   - Program/script: `H:\codex\tmp_r1000_quant_engine\aggressive\run_daily.bat`
   - Start in (optional): `H:\codex\tmp_r1000_quant_engine`
6. **Conditions tab**:
   - Uncheck "Start the task only if the computer is on AC power" (if laptop)
   - Check "Wake the computer to run this task"
7. **Settings tab**:
   - "Stop the task if it runs longer than": 30 minutes
   - "If the task is already running": "Do not start a new instance"

### Enabling LIVE paper execution

By default the scheduled task runs in DRY-RUN mode (signals + plan logged, but NO real orders placed).

To enable live paper orders:
- **Option A (environment variable)**: set `AGGRESSIVE_EXECUTE=1` in Windows system env
- **Option B (edit batch)**: uncomment the `--execute` flag in `run_daily.bat`

**Recommended workflow**:
1. Week 1: Run in DRY-RUN mode. Review logs daily.
2. Week 2: If dry-run decisions look sane, enable live paper execution.
3. Review execution audit trail at `aggressive/state/executions/latest.json` daily.


## 2. Weekly Theme Discovery

**Purpose**: Unsupervised clustering to find emerging themes + missing theme members.

**File**: `aggressive\run_weekly_discovery.bat`

**Recommended schedule**: Sunday at 22:00 KST (before Monday US market open)

### Setup

Same as above but:
- Name: `r1000_aggressive_weekly_discovery`
- Triggers: Weekly, **Sunday** at `22:00`
- Action program: `H:\codex\tmp_r1000_quant_engine\aggressive\run_weekly_discovery.bat`
- Settings: stop if > 45 min


## 3. Logs & Monitoring

- All scheduler runs write to `aggressive/state/scheduler_logs/daily_YYYYMMDD_HHMM.log`
- Daily review output: `aggressive/state/daily_review/latest.json`
- Execution audit:   `aggressive/state/executions/latest.json`
- Theme proposals:   `aggressive/state/theme_discovery/latest.json`
- Telegram: alerts sent automatically

## 4. Manual execution

Anytime you want to run manually:

```powershell
# Dry-run (default)
cd H:\codex\tmp_r1000_quant_engine
py -3 aggressive\daily_review.py

# Live paper execution
py -3 aggressive\daily_review.py --execute

# With theme discovery (slow, weekly)
py -3 aggressive\daily_review.py --discover-themes

# Specific universe
py -3 aggressive\daily_review.py --universe themes     # legacy fast
py -3 aggressive\daily_review.py --universe r1000      # default

# Use positions from JSON file (for testing without Alpaca)
py -3 aggressive\daily_review.py --positions-source json ^
    --positions-json aggressive\state\positions_sample.json
```

## 5. Paper account funding

If your Alpaca paper account shows $0 equity:

1. Log in to https://app.alpaca.markets/paper/dashboard/overview
2. Settings -> "Reset Paper Account" - resets balance to $100,000
3. Or top up: Deposit -> paper funds

## 6. Troubleshooting

**Task fires but no output**: Check `aggressive\state\scheduler_logs\` for error logs.

**"py -3" not found**: Task Scheduler might not inherit your PATH. Edit `run_daily.bat`
to use full Python path, e.g. `C:\Python312\python.exe` instead of `py -3`.

**Telegram alerts not arriving**: Verify `aggressive\.env` has both `TELEGRAM_BOT_TOKEN`
and `TELEGRAM_CHAT_ID`. Test with `py -3 aggressive\telegram_alert.py`.

**Alpaca errors**: Verify `ALPACA_API_KEY` and `ALPACA_API_SECRET` in `.env`.
Test connection: `py -3 aggressive\test_alpaca_connection.py`.
