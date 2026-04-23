# Phase A — Aggressive Engine Architecture (r1000_aggressive)

**Date**: 2026-04-23
**Status**: Design approved by user. Implementation queued.
**Goal**: CAGR 100% via real-time theme rotation + concentrated N=2-3 + dynamic leverage.
**Track**: Parallel to existing 정석 engine (monthly batch).

## 0. Two-track strategy overview

```
TRACK 1 (정석 engine, existing)        TRACK 2 (Aggressive, new)
────────────────────────────────       ──────────────────────────────
Monthly batch rebalance                Real-time + event-driven
Main N=18 + Concentrated N=5           Concentrated N=2-3
Target: 25-30% CAGR                    Target: 100% CAGR (stretch)
Conservative ship gate                  Aggressive ship (A/B paper trade)
1x leverage only                       Empirical leverage (1-2x after validation)
Free tier: 정석 portfolio              Paid tier (when validated)
                                   
             ↓ SHARED ↓
         ─────────────────
         Data platform:
         - cache_sec_actual/ (SEC companyfacts JSONs)
         - feature_store/    (parquet features)
         - macro_cache/      (FRED data)
         - themes.yaml       (taxonomy)
         - Universe membership
         ─────────────────
```

## 1. Key architecture differences

| 속성 | 정석 | Aggressive |
|---|---|---|
| Rebalance cadence | Monthly (calendar) | Event-driven + daily check |
| Universe | R1000 top 30 | Themed subset (~50-100 names) |
| Portfolio N | 18 / 5 | **2-3** |
| Data latency | EOD | **Real-time (websocket)** |
| Event awareness | Next rebal | **Intraday (minutes-hours)** |
| Backtest framework | Monthly walk-forward | **Daily replay** |
| Risk management | -25% hard stop (spec only) | **-10% trailing + theme break** |
| Leverage | 1x | **1-2x dynamic (Phase 17)** |
| ML target | r_1m / r_3m | **r_1w + event-response** |
| Ship gate | ΔCAGR ≥ +0.5pp | **Paper trade 3 months first** |

## 2. Technology stack

### Market data — Alpaca API (user account: andrewcha231@gmail.com)
- **Free tier benefits**:
  - Real-time IEX data (1-second bars)
  - Historical data 2015+
  - Paper trading account
  - Python SDK (`alpaca-py`)
- **Limitations**:
  - IEX quote only (not full NBBO) — acceptable for mid-cap themes
  - Paper limit: $100k simulated
- **Free tier sufficient for**: MVP, paper trading, small live
- **Paid upgrade ($100/mo)** if scaled up: SIP data, unlimited REST

### SEC events
- **Form 4 (insider trades)**: free from SEC EDGAR RSS
- **8-K (material events)**: free from SEC EDGAR RSS  
- **10-Q/K**: free (already collected by 정석)
- **Earnings calendar**: `python-earnings-calendar` (scraped) OR Alpaca (if available)

### News / sentiment (optional, Phase B4)
- Free: SEC EDGAR 8-K + press releases from companies' SEC filings
- Paid tier (later): Benzinga API, NewsAPI

### Infrastructure
- Python 3.12 (same as 정석)
- Postgres (optional, for event log) — or SQLite MVP
- No Docker yet — local Python process sufficient
- Windows Task Scheduler OR cloud cron (AWS Lambda $5/mo)

## 3. Directory structure

```
H:\codex\tmp_r1000_quant_engine\
├── r1000_top30_institutional.py    # 정석 engine (existing)
├── r1000_data_collector.py         # 정석 collector (existing)
├── r1000_config.py / signals.py / pipeline.py / features.py / helpers.py
├── themes.yaml                     # SHARED (committed)
│
├── aggressive/                     # NEW DIR for Track 2
│   ├── __init__.py
│   ├── agg_config.py               # Aggressive-specific config
│   ├── realtime_feed.py            # Alpaca websocket wrapper
│   ├── event_triggers.py           # earnings / form4 / 8-K detectors
│   ├── theme_live_detector.py      # Phase 16 lifecycle in real-time
│   ├── concentrated_pm.py          # N=2-3 portfolio manager
│   ├── leverage_overlay.py         # Phase 17 leverage logic
│   ├── fast_backtest.py            # Daily replay framework
│   ├── agg_run.py                  # CLI entry (like run_local.py)
│   └── live_trader.py              # Alpaca order execution
│
├── research/
│   ├── aggressive/                 # Aggressive-specific research
│   │   ├── theme_retrospective.py  # validate theme lifecycle signals
│   │   ├── event_response_study.py # how fast does price react?
│   │   └── backtest_comparison.py  # daily vs monthly
│   └── (existing 정석 research dirs)
│
└── docs/
    ├── MASTER_PLAN.md              # both tracks (existing)
    ├── PHASE_16_THEMES_PROPOSAL.md # Phase 16 (existing)
    └── PHASE_A_AGGRESSIVE_ARCHITECTURE.md  # this doc
```

## 4. Phase breakdown (Phase A..G)

### Phase A — Architecture (this doc, 1-2 hours) ✅

### Phase B — Foundation (2-3 weeks)

**B1. Data infrastructure** (1 week)
- Alpaca SDK integration (paper account first)
- Websocket real-time bar subscriber
- Historical data alignment with existing feature_store
- Event calendar loader (earnings dates for R1000)

**B2. Event triggers** (1 week)
- `earnings_beat_detector`: compare EPS actual vs estimate within hours
- `insider_cluster_detector`: ≥3 C-suite buys in past 2 weeks
- `rs_break_detector`: 1-week RS breakdown from top decile
- `theme_phase_detector`: phase=ending → broadcast all theme members

**B3. Paper trading infra** (1 week)
- Alpaca order placement wrapper
- Position tracking JSON (separate from 정석 live_portfolio_state)
- Trade log with decision rationale
- Slippage + cost simulator matching Alpaca's actual fills

### Phase C — Core logic (2-3 weeks)

**C1. Theme live detector** (1 week)
- Load themes.yaml
- Per-theme real-time aggregates (mom, breadth, acceleration, drawdown)
- Phase classifier (early/maturing/peaking/ending/dead)
- Output: `theme_state_current.json` updated every 5 min

**C2. Concentrated PM** (1-2 weeks)
- N=2-3 target
- Selection: top theme_leadership × maturing phase × fundamental floor
- Cash buffer (0-30% dynamic by regime)
- Intraday stop rules:
  - Stock trailing -10% (tighter than 정석 -15%)
  - Theme exit: immediate
  - Regime turn: full liquidation + cash

**C3. Fast-rotation backtest** (1 week)
- Daily rebalance simulation using existing feature_store as starting point
- Apply aggressive rules retroactively 2019-2026
- Compare to 정석 results

### Phase D — Paper trading (3-4 weeks)

**D1. Paper deployment** (1 week)
- Connect agg_run to Alpaca paper account
- Set $100k simulated capital
- Daily cron (market open + close)

**D2. Monitoring** (2-3 weeks)
- Compare paper performance to backtest prediction (tracking error)
- Refine entry/exit thresholds based on live behavior
- Event response latency measurement

### Phase E — Live small ($1-5k) (continuous)

Only after paper trade shows:
- Backtest tracking error < 10%
- No catastrophic bug (negative days > -5%)
- Event response < 30 min lag

### Phase F — Scale-up / Phase 17 leverage (future)

- Gradually increase capital
- Add leverage overlay if paper trade validates
- 2x ETF (TQQQ/UPRO) for bull regime
- Deleverage trigger: regime turn detected

## 5. Data sharing contract (Track 1 ↔ Track 2)

### Shared (read-only for Aggressive):
```
/feature_store/
├── feature_store_latest.parquet    # built by 정석 monthly
├── scored_oos_latest.parquet       # ML predictions from 정석
├── fund_panel_latest.parquet       # SEC fundamentals
└── macro_regime_latest.parquet     # macro signals

/cache_sec_actual/
└── companyfacts_*.json             # SEC company facts

themes.yaml                          # taxonomy
```

### Aggressive-owned (write):
```
/aggressive/state/
├── live_positions.json             # current holdings (Alpaca paper)
├── event_log.jsonl                 # timestamped event stream
├── theme_state_current.json        # theme phase snapshots
└── trade_log.jsonl                 # executed trades + rationale

/aggressive/cache/
└── alpaca_bars/                    # real-time bar history
```

## 6. Agg-specific CFG

```python
# aggressive/agg_config.py
@dataclass
class AggressiveConfig:
    # Portfolio
    agg_portfolio_n: int = 3         # concentrated N
    agg_cash_target_min: float = 0.00  # aggressive: 0% cash default
    agg_cash_target_bear: float = 0.50  # bear regime: 50% cash
    
    # Event triggers
    earnings_beat_entry: bool = True
    earnings_miss_exit: bool = True
    insider_cluster_entry: bool = True
    form4_alert_threshold: int = 3   # 3+ C-suite buys
    
    # Stops
    agg_trailing_stop_pct: float = 0.10
    agg_theme_exit_immediate: bool = True
    regime_turn_liquidation: bool = True
    
    # Leverage (Phase 17, default OFF)
    leverage_enabled: bool = False
    leverage_max: float = 2.0
    leverage_regime_allow: list = ['bull_strong']  # only when bull
    leverage_deleverage_on_turn: bool = True
    
    # Alpaca API
    alpaca_mode: str = 'paper'       # 'paper' | 'live'
    alpaca_capital_usd: float = 100000.0
    alpaca_max_order_size_pct: float = 0.33  # max 33% of portfolio per order
    
    # Timing
    agg_cron_interval_minutes: int = 5     # main loop
    event_reaction_lag_seconds: int = 60   # min delay after event
    
    # Backtest
    agg_backtest_horizon_years: int = 5    # start: 5 years
    agg_backtest_daily: bool = True
```

## 7. Risk management

### 7.1 Catastrophic loss prevention
- **Hard cap**: per-position -15% intraday → force exit
- **Portfolio drawdown**: -10% single day → immediate full cash
- **Theme rollover**: breadth < 30% + acceleration < 0 → full theme exit
- **Regime turn**: VIX > 30 OR SPY MA200 break → deleverage + cash ≥ 50%

### 7.2 Position sizing
- N=2: 50% each (no cash) bull / 33% each + 34% cash balanced
- N=3: 33.3% each bull / 25% each + 25% cash balanced
- Extreme bull with leverage: 2x total × 33% each = 66% per name

### 7.3 Execution realism
- Alpaca fractional shares (allows exact % allocation)
- Limit orders only (no market orders for $1M+ positions in illiquid names)
- Scale-in / scale-out over 2-3 bars (reduce slippage)

## 8. Success criteria (per phase)

### Paper trade (Phase D)
- Backtest → Paper tracking error < 10% over 30 days
- No single-day loss > -5%
- Event response latency < 30 minutes from alert to order

### Live small (Phase E)
- Monthly returns within 1σ of paper prediction
- MaxDD never exceeds 2x of 30-day backtest implication
- All stops fire correctly

### Scale-up (Phase F)
- 6-month live at ≥ 60% annualized
- Sharpe ≥ 1.5 (real after slippage + taxes)
- MaxDD ≤ -40%

## 9. Timeline + resource

| Phase | Duration | Effort |
|---|---|---|
| A Architecture | 1-2 hours | DONE this session |
| B Foundation | 2-3 weeks | 15-20h |
| C Core logic | 2-3 weeks | 20-25h |
| D Paper trade | 3-4 weeks | 5-10h/week monitoring |
| E Live small | Continuous | Weekly review |
| F Leverage/scale | Future | TBD |
| **MVP live small** | **~3 months** | ~40-50h total impl + monitoring |

## 10. Open design questions for user

1. **Starting capital for paper**: $10k / $100k / custom?
2. **Max drawdown tolerance**: -30% / -40% / -50% before forced pause?
3. **Leverage**: explicitly deferred to Phase 17 after empirical results? ✅ (user confirmed)
4. **정석 engine parallel operation**: continuous or freeze at Phase 16 complete? (user: **continue**)
5. **Alpaca paper capital**: default $100k (their setting) OK?
6. **Daily cron location**: local Windows Task Scheduler OR cloud (AWS $5)?
7. **Alert channel**: email / Telegram / just logs?

## 11. Immediate next steps (this week)

1. User reviews this doc + answers Q10
2. Create `aggressive/` directory skeleton
3. Install `alpaca-py` SDK
4. Write `agg_config.py` skeleton
5. Test Alpaca connection (paper account read)
6. Start Phase B1 (data infrastructure)

## 12. Design principles (philosophical)

**Different from 정석 engine**:
- 정석: **Outperform market by 5-10pp**, low risk, broad diversification
- Aggressive: **100% CAGR stretch**, high risk, concentrated conviction bets

**Common** (both tracks):
- Data integrity first
- Research-driven (not gut)
- Paper validation before live capital
- Transparent logs (user can audit every decision)

## Files
- This doc: `PHASE_A_AGGRESSIVE_ARCHITECTURE.md`
- Shared: `themes.yaml`, `MASTER_PLAN.md`, `PHASE_16_THEMES_PROPOSAL.md`
- Future: `aggressive/*.py`, `aggressive/state/*.json`
