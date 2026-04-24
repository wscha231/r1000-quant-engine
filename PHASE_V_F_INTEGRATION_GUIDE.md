# Phase V+F Integration Guide — What's Next

_Generated 2026-04-24 during autonomous session while user 퇴근_

## What was committed tonight (commit `217fd41`)

**Aggressive engine integration COMPLETE**. Scanner now uses:
- Finnhub PEG (fixed AAPL 8.32 → 1.90 bug)
- Insider cluster score
- Earnings event risk window
- Analyst bull ratio
- MSPR sentiment

**정석 engine integration NOT DONE**. Still uses old SEC-based values.
Needs manual review before touching main pipeline (risk of breaking backtest).

## Tomorrow Morning Workflow

### Step 1: Verify Finnhub collection completed
```powershell
cd H:\codex\tmp_r1000_quant_engine
py -3 aggressive\verify_phase_v_f.py
```
Expected: ~1000/1008 tickers collected. If < 900, re-run collector.

### Step 2: See the PEG fix in action
The verify script shows before/after PEG for AAPL/NVDA/GOOG. Main changes:
- AAPL PEG 8.32 → 1.90 (growth rate was understated)
- NVDA PEG 0.18 → ~1.2 (growth rate was overstated cyclically)
- AMD blended growth uses Q YoY +210% → reasonable PEG

### Step 3: Run scanner with Finnhub gates
```powershell
py -3 aggressive\daily_review.py --universe r1000 --dry-run
```
Now output includes `val_mult` column showing fundamental gate penalties.

## Integration into 정석 Engine (3-4 hours)

Location: `r1000_pipeline.py` function `build_universe_monthly` around line 6428.

### Current sequence
```python
monthly = merge_live_fundamentals(monthly, live_df)
monthly = merge_live_event_alert_features(cfg, paths, monthly)
# ... scoring happens later
```

### Proposed change
```python
monthly = merge_live_fundamentals(monthly, live_df)
# NEW: Live recompute of valuations (Strategy A)
from r1000_valuations import compute_live_valuations, load_finnhub_features
finnhub_df = load_finnhub_features()
monthly = compute_live_valuations(monthly, finnhub_df=finnhub_df, verbose=True)
monthly = merge_live_event_alert_features(cfg, paths, monthly)
```

**Risks to evaluate before integrating**:
1. `peg_final` override changes ML model inputs → may invalidate training
2. `forward_pe_final` override changes factor IC
3. Sleeve composite `score_model_core` may shift significantly
4. Sleeve targets (core 60% / future 25% / early 15%) may no longer balance
5. Backtest replay could produce different results for 2020-2026

### Recommended integration plan
Phase 1 (safe): Use Finnhub as additional fallback in earnings_growth_final chain
Phase 2 (testing): Recompute peg_final in shadow column, diff against legacy
Phase 3 (production): Override only if diff magnitude < 2x (auto-reject extremes)
Phase 4 (full): Replace legacy entirely after 2-week shadow run shows stability

### What to commit first
Shadow recompute that ADDS new columns without overriding:
```python
monthly["peg_shadow"] = compute_live_valuations(monthly, finnhub_df).peg_live
# Log diff vs peg_final for sanity
diff = (monthly["peg_shadow"] - monthly["peg_final"]).abs()
print(f"PEG diff stats: median {diff.median():.2f}, max {diff.max():.2f}")
```

Run for a week, validate, then override.

## Windows Task Scheduler Entries Needed

Create 2 scheduled tasks for data collection:

### Task 1: Finnhub weekly batch (metric + recommendations)
- Name: `r1000_finnhub_weekly`
- Trigger: Mondays 22:30 KST
- Action: `py -3 aggressive/finnhub_collector.py --mode weekly`
- Timeout: 45 min

### Task 2: Finnhub daily batch (insider + earnings)
- Name: `r1000_finnhub_daily`
- Trigger: Every day 23:30 KST
- Action: `py -3 aggressive/finnhub_collector.py --mode daily`
- Timeout: 30 min

## Monitoring

Key artifacts:
- `aggressive/state/finnhub/r1000_features.parquet` — consolidated data
- `aggressive/state/finnhub/r1000_features_YYYYMMDD_HHMMSS.parquet` — timestamped
- `aggressive/cache/finnhub/{endpoint}/{ticker}.json` — per-ticker cache
- `aggressive/state/finnhub/r1000_features_partial.parquet` — in-flight checkpoint

If collection stalls/fails:
```powershell
# Resume where it left off (cache TTL respects existing files)
py -3 aggressive\finnhub_collector.py --mode full
```

## Architecture Decision Log

**Why blended growth (5y + Q YoY + 3y median)?**
- 5y alone: understates cyclicals (AMD 5y=5.13% hides current +210% Q)
- Q YoY alone: overshoots boom phase
- Median: robust to both edges
- Floor 5% + ceiling 30%: avoids division-by-zero and unsustainable growth assumption

**Why val_mult multiplicative layers vs simple gate?**
- Score-wise transparent (can see each penalty/bonus)
- Composable (multiple factors combine naturally)
- No single-factor cliff (not "pass/fail" but "partial discount")

**Why preserve old columns when fixing?**
- Backtest consistency (don't retroactively change historical factor IC)
- A/B testing (shadow vs override)
- Rollback safety
