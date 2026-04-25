# Monday Paper Trading Plan (2026-04-27)

_Created 2026-04-25 after Phase 1+2 audit complete._

## Validation Status

| Strategy | 84-mo CAGR | Bootstrap CI | P(alpha>0) | Backtest realism |
|---|---|---|---|---|
| **Concentrated 3-name** | **33.17%** | [7.79% .. 62.79%] | **97.9%** | adj_open + 25bps + historical membership ✓ |
| **Core (정석 v1, ~20 names)** | **22.95%** | [8.87% .. 39.88%] | **99.5%** | same ✓ |
| SPY benchmark | 13.49% | - | - | FRED:SP500 |

Both validated through:
- Production score leakage audit: **PASS** (cfg.features 0 contamination)
- 84-month walk-forward (2019-04 ~ 2026-02)
- Bootstrap 10,000 resamples (3-month blocks)
- Adjusted open prices (split/div), 25bps/side cost, historical R1000 membership

## Risk Sensing Findings (Phase 2)

❌ **L1 fixed-percentage stops EMPIRICALLY DISPROVEN** for monthly rebalanced concentrated:
- 25 threshold combinations tested, NONE beat baseline
- Best (-20% hard, no trail) → CAGR 28.8% / Sharpe 1.09 (still worse than 33.22%/1.21 baseline)
- Whipsaw: 30%+ stops triggered, half are noise → cash misses recoveries

✅ **L2 (DD circuit breaker) already in production**, working since 2020-03 COVID
✅ **L3/L4 (regime defense + position swap)** = manual additions, low risk

## Monday Allocation Plan

```
Total Alpaca Paper: $100,000

Sleeve A: Concentrated (60%)        = $60,000
  PR  41.70% → $25,020 → 1184 sh @ $21.13
  ETR 38.25% → $22,950 → 200 sh @ $114.57
  GEV 20.05% → $12,030 → 13 sh @ $897.36

Sleeve B: Core 정석 v1 (30%)         = $30,000
  17 names from portfolio_latest.csv
  NVDA 14% × 30% = $1,260 → 7 shares
  GOOG 14% × 30% = $1,260 → 4 shares
  ... (scaled down 3.33x from 100% allocation)

Cash buffer (10%)                    = $10,000
```

## Execution Commands

```bash
# Saturday/Sunday verification (current)
py -3 r1000_paper_executor.py --advisor concentrated --capital 60000   # dry-run
py -3 r1000_paper_executor.py --advisor core         --capital 30000   # dry-run

# Monday 22:00 KST (15min before market open) - final dry-run
py -3 r1000_paper_executor.py --advisor concentrated --capital 60000

# Monday 22:30 KST (market open) - LIVE
py -3 r1000_paper_executor.py --advisor concentrated --capital 60000 --execute --confirm
py -3 r1000_paper_executor.py --advisor core         --capital 30000 --execute --confirm

# Audit trail: aggressive/state/paper_executions/exec_*.json
# Telegram alert auto-fires on each execution
```

## Risk Sensing Configuration (manual, weekly review)

For first 4 weeks, MANUAL risk monitoring (not auto-executing):

### Weekly checks (Sundays):
1. **Portfolio DD**: NAV vs 60-day peak. If < -10% → reduce position 30%
2. **VIX**: > 30 → halt new buys (next rebalance only)
3. **SPY 200MA**: below → +20% cash buffer
4. **Position RS**: Any holding with 12m RS < 0 for 60+ days → flag for swap

### Manual stop rules (DO NOT auto-execute):
- Individual position -25% from peak: REVIEW (not auto-exit)
- Position -8% within 30d of entry: REVIEW (proven net-negative if auto)

### Concentrated specific:
- 3 names × 60% allocation = high single-name risk by design
- Expected MaxDD: -27% (per backtest)
- Expected month worst-case: -20%
- Tolerate or rotate at month-end (NOT intra-month)

## Monitoring Tools

| Tool | Frequency | Action |
|---|---|---|
| `aggressive/state/paper_executions/exec_*.json` | Daily | Verify fills vs target |
| Telegram alerts | Real-time | Each execution |
| Equity curve drift | Weekly | Live vs backtest expectation |
| Production engine refresh | Monthly | New rebalance picks |

## Drift Detection Targets

If after 3 months live performance:
- Sharpe < 0.6 (vs backtest 1.18) → review/pause
- Live MaxDD > -30% → review L2 trigger
- Win rate < 45% (vs backtest ~54%) → review entry timing

## Phase 3 Background Work (parallel with paper)

- **Opus rule discovery**: Multibagger analysis, regime conditional rules
- **Vol-adjusted stops**: Replace fixed % with ATR-based (future)
- **84mo full strategy backtester**: Currently running, validates new advisors
- **Drift detection auto-pause**: Add to monitoring (Phase 5)

## Decision Log

- 2026-04-25 audit found: ML clean = 0 edge → v4 deprecated
- Production 정석 + concentrated = validated alpha sources
- L1 stops = net-negative for monthly rebalance → SKIP
- Risk sensing: L2 only (already in production), L3/L4 manual

## Next Review

- Daily P&L Mon-Fri (first week)
- Weekly review every Sunday
- Monthly rebalance review on production engine refresh date
- Quarterly: bootstrap CI re-run with live data added
