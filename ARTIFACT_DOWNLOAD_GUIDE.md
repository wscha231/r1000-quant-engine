# Artifact Download Guide

When workflow `full_rebuild_manual.yml` succeeds but its `git push` fails
(race condition), the results are still preserved as **GitHub Actions artifact**
for 365 days. This doc explains how to retrieve them.

## When this matters

Run 24961673988 (started 2026-04-26 16:38 UTC, finished 19:19 UTC):
- ✅ Workflow execution: SUCCESS
- ✅ Verdict: **SHIP** (Phase 14 + ADR vs Phase 9 C3 baseline)
- ✅ Lifetime CAGR: **23.48%** over 6.84 years (+0.57pp vs 22.91% baseline)
- ✅ Lifetime total: **+323.45%** ($100k → $423k)
- ❌ `git push` rejected (concurrent fixes during 7h run)
- ❌ Telegram failed (URL encoding bug, fixed in b6c8bf8)
- ✅ **Artifact saved** — retrievable for 365 days

Subsequent runs (after b6c8bf8) have push-retry + URL-encoding fix, so
artifact-only retrieval is the fallback path, not the primary one.

## How to download (mobile)

1. Open in mobile browser:
   ```
   https://github.com/wscha231/r1000-quant-engine/actions/runs/24961673988
   ```
2. Scroll to bottom → **Artifacts** section
3. Tap `full-rebuild-r1000+adr-24961673988`
4. ZIP downloads to phone
5. Open ZIP → see contents below

## How to download (PC, faster)

```bash
# Using gh CLI (if installed)
gh run download 24961673988 -R wscha231/r1000-quant-engine

# Or browser at the URL above
```

## What's inside the ZIP

```
full-rebuild-r1000+adr-24961673988.zip
├── full_rebuild_logs/
│   ├── 20260426_<ts>_r1000+adr.log    # Full pipeline log (~100k lines)
│   └── verdict.log                     # SHIP/PARTIAL/REGRESS judgment
├── scored_latest.csv                   # 1008+ ticker scores (R1000 + 26 ADR)
├── scored_unified.csv                  # 정석 + Finnhub synthetic merge
├── portfolio_latest.csv                # Production main portfolio (~18 names)
├── concentrated_portfolio_latest.csv   # 3-name concentrated portfolio
├── backtest_metrics.json               # Main: CAGR, Sharpe, MaxDD, IR
└── concentrated_backtest_metrics.json  # Concentrated 3-name metrics
```

## Quick verification commands (after extraction)

```bash
# Check verdict
cat full_rebuild_logs/verdict.log | grep -E "SHIP|PARTIAL|REGRESS"

# Main metrics
python3 -c "import json; m = json.load(open('backtest_metrics.json')); \
  print(f\"CAGR: {m.get('strategy_cagr', 0)*100:.2f}%, \
       Sharpe: {m.get('strategy_sharpe', 0):.3f}, \
       MaxDD: {m.get('strategy_max_dd', 0)*100:.2f}%\")"

# Top 5 holdings
python3 -c "import pandas as pd; \
  df = pd.read_csv('portfolio_latest.csv'); \
  print(df.nlargest(5, 'weight')[['ticker', 'weight', 'portfolio_sleeve_label']])"

# Sleeve composition
python3 -c "import pandas as pd; \
  df = pd.read_csv('portfolio_latest.csv'); \
  print(df['portfolio_sleeve_label'].value_counts())"

# Concentrated 3-name
python3 -c "import pandas as pd; \
  print(pd.read_csv('concentrated_portfolio_latest.csv'))"

# vs CURRENT_BASELINE
py -3 tools/compare_adr_backtest.py \
  --variant backtest_metrics.json \
  --use-pinned-baseline
```

## Sync to gdrive (PC)

If using PC + Drive sync:
```bash
# After extracting zip to <unzip_path>:
cp <unzip_path>/scored_latest.csv "G:/내 드라이브/r1000_top30_institutional/outputs/"
cp <unzip_path>/portfolio_latest.csv "G:/내 드라이브/r1000_top30_institutional/outputs/"
cp <unzip_path>/concentrated_portfolio_latest.csv "G:/내 드라이브/r1000_top30_institutional/outputs/"
cp <unzip_path>/backtest_metrics.json "G:/내 드라이브/r1000_top30_institutional/outputs/"
cp <unzip_path>/concentrated_backtest_metrics.json "G:/내 드라이브/r1000_top30_institutional/outputs/"
cp <unzip_path>/scored_unified.csv "G:/내 드라이브/r1000_top30_institutional/outputs/"

# Now local scripts can use the cloud results
py -3 r1000_paper_executor.py --advisor concentrated  # dry-run
py -3 r1000_layer4_swap.py                            # check swap suggestions
```

## Decision: SHIP or rerun?

If artifact contents confirm SHIP (CAGR 23.48% / +0.57pp), then:

1. **Rotate CURRENT_BASELINE** in `run_local.py`:
   ```python
   CURRENT_BASELINE = {
       "name": "Phase 14 + ADR (SHIPPED 2026-04-26 via cloud run 24961673988)",
       "cagr": 0.2348,
       "sharpe": <from backtest_metrics.json>,
       "max_dd": <from backtest_metrics.json>,
       ...
   }
   ```

2. **Update CLAUDE.md** "Current Production Baseline" section

3. **CHANGELOG entry** per Agent Update Contract format (see CHANGELOG.md top)

4. **Commit + push** to master

5. **Optional**: re-trigger workflow (now b6c8bf8) to verify push-retry works
   and confirm Telegram + cloud_results auto-commit succeed.
